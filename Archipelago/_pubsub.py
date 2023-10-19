from __future__ import annotations

import unrealsdk # type: ignore

import enum
import json
import random
import threading
import time

from collections import deque
from logging import Logger
from select import select
from typing import Any, Callable, Deque, Dict, Optional, Tuple

from Mods.TwitchLogin import _authorization, _utilities

with _utilities.ImportContext:
    import websocket

log = _utilities.log.getChild("PubSub")


MessageCallback: Callable[[str, Dict[str, Any]], None]
"""
A callback to be invoked for each PubSub topic message received. The first parameter will contain
the topic of the message. The second parameter will contain the data of the message.
"""


_topic_websockets: Dict[str, _topic_websocket] = {}
"""Each of the currently active topic websocket objects, keyed by their topics."""

_websocket_thread: Optional[threading.Thread] = None
"""The current Thread object on which our topic websocket polling is performed."""


def OpenTopic(topic: str) -> None:
    """
    Open a websocket on which to listen for the specified topic, if there is not one already.
    """
    global _websocket_thread

    # If we are not currently authenticated, nothing to do.
    if _authorization.Token is None:
        log.debug("Attempted to register topic %s with no token", topic)
        return

    # If we have already registered this topic, nothing to do now.
    if topic in _topic_websockets:
        log.debug("Topic %s already registered, ignoring", topic)
        return

    # Create a websocket object for the topic, and save it in our records accordingly.
    _topic_websockets[topic] = _topic_websocket(topic)

    # If this is the first topic we've registered, we must setup our infrastructure now.
    if len(_topic_websockets) == 1:
        log.info("Starting polling thread")

        # Start the polling thread with the polling routine.
        _websocket_thread = threading.Thread(target=_poll_websockets, daemon=True)
        _websocket_thread.start()


def CloseTopic(topic: str) -> None:
    """
    Open a websocket on which to listen for the specified topic, if there is not one already.
    """
    global _websocket_thread

    # Find the websocket object for the topic. If we don't have one, nothing to do now.
    topic_websocket = _topic_websockets.get(topic)
    if topic_websocket is None:
        log.debug("No websocket for topic %s, ignoring close request", topic)
        return

    # Tell the websocket object to perform shutdown.
    topic_websocket.shutdown()
    del _topic_websockets[topic]

    # If we have no remaining topics, join our polling thread, and unregister for game ticks.
    if len(_topic_websockets) == 0:
        log.info("Closing polling thread")

        _websocket_thread.join()
        _websocket_thread = None


def _poll_websockets():
    """Repeatedly iterate over each topic websocket at an interval."""

    # Keep this routine alive so long as there is at least one websocket.
    while len(_topic_websockets) != 0:
        # Create a dictionary of the current topics with connected websockets, keyed by their
        # websockets' file descriptors.
        topic_handles: Dict[int, _topic_websocket] = {
            topic.sock.fileno() : topic
            for topic in _topic_websockets.values() if topic.connected
        }

        # Wait on the readability of the connected file descriptors for a quarter of a second.
        if len(topic_handles) > 0:
            readable_handles, _, _ = select(topic_handles, [], [], 0.25)
    
            if len(readable_handles) != 0:
                log.debug("Received readable events on handles: %s", topic_handles)

                # For each socket returned as readable, tell its topic to receive the message.
                for handle in readable_handles:
                    topic = topic_handles[handle]
                    topic.receive_message()

        for topic in _topic_websockets.values():
            topic.poll_status()


class _topic_websocket(websocket.WebSocket):
    """
    A websocket client that listens for a single PubSub topic in the Twitch API, and provides
    interfaces for the various factors relating to its maintenence.
    """

    topic: str
    """
    The topic this websocket is responsible for, as originally requested, without having had token
    replacement performed.
    """

    class states:
        """An enumeration of the various states a topic websocket can be in."""
        disconnected = enum.auto()
        """Currently attempting the initial connection to Twitch."""
        awaiting_pong = enum.auto()
        """Connected to Twitch, with initial PING send, awating the PONG response."""
        listen_sent = enum.auto()
        """Sent the LISTEN message to the socket, awaiting confirmation."""
        connected = enum.auto()
        """Fully connected with a registered LISTEN for the topic."""

    state: states = states.disconnected
    """The current state of the websocket."""

    reconnection_attempts: int = 0
    """The number of unsuccessful connection attempts that this websocket has made."""
    next_reconnect: float = 1.0
    """The time after which the websocket should next attempt a connection."""

    timeout: float = 0.0
    """The time at which the websocket should be considered to have a connection failure."""
    next_ping: float = 0.0
    """The time at which the websocket should next send a PING to maintain the connection."""

    log: Logger
    """The logger object for this websocket."""


    def __init__(self, topic: str):
        super().__init__()

        self.log = log.getChild(topic)
        self.log.info("Creating websocket")

        self.topic = topic
        self.next_reconnect = time.time() + random.random()


    def reconnect(self) -> None:
        """
        Force a new initial connection attempt (disconnecting the websocket if already connected).
        Send the initial PING upon success, or handle any errors that occur on failure.
        """
        self.state = _topic_websocket.states.disconnected

        if self.connected:
            self.log.debug("Already connected, closing")
            self.close()

        try: self.connect("wss://pubsub-edge.twitch.tv")
        except:
            self.log.warn("Failed to connect", exc_info=True)
            # If the connection fails, calculate the time when we should next attempt to connect.
            # It should be after a random "jitter" of 0 to 1 second, plus an interval that doubles
            # after each failed connection attempt, up to a maximum of 128 seconds.
            reconnect_after = random.random() + 2 ** self.reconnection_attempts
            self.next_reconnect = time.time() + reconnect_after

            self.log.info("Reconnecting after %s seconds", reconnect_after)

            # Increment our failed connection counter, up to a maximum of 8 (thus making our maximum
            # reconnection attempt interval ~128 seconds).
            if self.reconnection_attempts < 8:
                self.reconnection_attempts += 1
            return

        # With a successful connection, configure the new socket to timeout IO attempts immediately.
        self.sock.settimeout(0)

        # Reset our reconnection attempt values.
        self.reconnection_attempts = 0
        self.next_reconnect = 0.0

        # Send the initial PING to confirm the functioning connection.
        self.log.info("Connected successfully, sending initial PING")
        self.send_ping()
        self.state = _topic_websocket.states.awaiting_pong

    
    def shutdown(self) -> None:
        self.log.info("Closing websocket")
        super().shutdown()


    def poll_status(self) -> None:
        """
        Perform the periodic routine maintenence on this websocket and its state.
        """
        current_time = time.time()

        # If we're currently disconnected, and the we've reached the time at which we should make
        # another connection attempt, do so now.
        if not self.connected and current_time > self.next_reconnect:
            self.log.debug("Reconnection time reached, attempting connection")
            self.reconnect()

        # If we have reached the time at which we're considered to be timed out waiting for some
        # response, force a reconnection now.
        elif current_time > self.timeout:
            self.log.warn("Timed out, reconnecting")
            self.reconnect()

        # If we are currently fully connected, and it is time to send our next PING, do so.
        elif self.state == _topic_websocket.states.connected and current_time > self.next_ping:
            self.log.info("Sending maintenence PING")
            self.send_ping()


    def send_ping(self):
        """
        Send a PING to the server and update our timeout to wait on the response.
        """
        self.send('{"type":"PING"}')
        self.timeout = time.time() + 10


    def send_listen(self):
        """
        Send a LISTEN message to the server, complete with our topic and our OAuth token.
        """
        # If applicable, format our topic with the user's current ID.
        topic = self.topic.format(UserID = _authorization.UserID)
        self.log.debug("Sending LISTEN for topic %s", topic)

        self.send(json.dumps({
            "type": "LISTEN",
            "data": { "topics": [topic], "auth_token": _authorization.Token }
        }))
        self.state = _topic_websocket.states.listen_sent
        self.timeout = time.time() + 10


    def receive_message(self) -> None:
        """
        If an incoming message is waiting on the socket, receive and handle it.
        """
        try: message = self.recv()

        # If we timeout (immediately) trying to get a message from the socket, nothing to do.
        except websocket.WebSocketTimeoutException:
            self.log.debug("Timed out attempting receive")
            return

        # Any other exception, assume we are not properly connected.
        except:
            self.log.warn("Error attempting to receive message", exc_info=True)
            self.reconnect()
            return

        self.log.debug("Successfully received message from Twitch: %s", message)

        # All valid messages from Twitch should be JSON decodable.
        try: message = json.loads(message)
        except:
            self.log.error("Received message with invalid JSON: %s", message, exc_info=True)
            return

        # All messages from Twitch should contain a "type" entry. Ensure it is uppercase for us to
        # reliably handle special ones.
        message_type = message.get("type", "").upper()
        if message_type == "":
            self.log.warn("Received message with missing type: %s", message)
            return


        if message_type == "PONG":
            # If we are receiving our first a PONG on a newly opened connection, we are good to send
            # our LISTEN request. Give the server 10 seconds to respond to that.
            if self.state is _topic_websocket.states.awaiting_pong:
                self.log.info("Received initial PONG")
                self.send_listen()

            # If this was a response to another PING, then the connection has been verified.
            else:
                self.log.info("Received maintenence PONG")
                self.timeout = float('inf')

            # Set the next ping to be performed in 4 minutes, with a random jitter of up to 30
            # seconds as per Twitch's recommendation to prevent simultaneous pings.
            ping_after = 240 + random.random() * 30
            self.next_ping = time.time() + ping_after

            self.log.debug("Next PING in %s seconds", ping_after)
            return


        # If the server is telling us to reconnect, do so.
        if message_type == "RECONNECT":
            self.log.warn("Received RECONNECT message, reconnecting")
            self.reconnect()
            return


        if message_type == "RESPONSE":
            # If we are receiving a response to our listen request, check for an error.
            error = message.get("error", "").upper()

            # If no error, we are now fully connected and subscribed.
            if error == "":
                log.info("Received positive RESPONSE to listen, connected")
                self.timeout = float('inf')
                self.state = _topic_websocket.states.connected

            # If the server has rejected our authentication, then we likely don't have authorization
            # for the scope required by this topic.
            elif error == "ERR_BADAUTH":
                self.log.error(
                    "Twitch rejected authentication when listening for topic "
                    "(possible missing scope)"
                )
                CloseTopic(self.topic)

            # If the error was on the server's end, attempt the listen request again.
            elif error == "ERR_SERVER":
                self.log.warn("Twitch reported a server error in response to LISTEN, reattempting")
                self.send_listen()

            # Any other error type we can safely assume involves a fault with the topic, and we
            # should shutdown and unregister it. We can't account for the error type in this case:
            # https://discuss.dev.twitch.tv/t/pubsub-docs-surrounding-error-messages-are-completely-wrong/22354
            else:
                self.log.error("Twitch rejected LISTEN for topic with error: %s", error)
                CloseTopic(self.topic)

            return

        
        # The remaining message types we handle should all have a data field.
        message_data = message.get("data")
        if message_data is None:
            self.log.warn("Received unknown message type with no data field: %s", message)

        # Finally, if we have data that is not of any of the above special message types, submit it
        # to be sent to mods via the API on the main thread.
        else:
            log.info("Dispatching message to mod callbacks")
            _utilities.MainThreadQueue.append(
                lambda: MessageCallback(self.topic, message_data)
            )
