from __future__ import annotations

import unrealsdk # type: ignore

import enum
import json
import random
import threading
import time
import uuid

from collections import deque
from logging import Logger
from typing import Any, Callable, Deque, Dict, Optional, Tuple
from copy import deepcopy

from Mods.Archipelago import  _utilities

with _utilities.ImportContext:
    import websocket
    from select import select

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


def OpenTopic(address: str) -> None:
    """
    Open a websocket on which to listen for the specified topic, if there is not one already.
    """
    global _websocket_thread

    # If we have already registered this topic, nothing to do now.
    if address in _topic_websockets:
        unrealsdk.Log(f"Address {address} already registered, ignoring")
        return

    # Create a websocket object for the address, and save it in our records accordingly.
    _topic_websockets[address] = _topic_websocket(address)
    _topic_websockets[address].reconnect()

    # If this is the first address we've registered, we must setup our infrastructure now.
    if len(_topic_websockets) == 1:
        unrealsdk.Log("Starting polling thread")

        # Start the polling thread with the polling routine.
        _websocket_thread = threading.Thread(target=_poll_websockets, daemon=True)
        _websocket_thread.start()

    return _topic_websockets[address]


def CloseTopic(address: str) -> None:
    """
    Close a websocket on which to listen for the specified topic, if there is not one already.
    """
    global _websocket_thread

    # Find the websocket object for the address. If we don't have one, nothing to do now.
    topic_websocket = _topic_websockets.get(address)
    if topic_websocket is None:
        log.debug("No websocket for address %s, ignoring close request", address)
        return

    # Tell the websocket object to perform shutdown.
    topic_websocket.shutdown()
    del _topic_websockets[address]

    # If we have no remaining topics, join our polling thread, and unregister for game ticks.
    if len(_topic_websockets) == 0:
        log.info("Closing polling thread")

        _websocket_thread.join()
        _websocket_thread = None

def CloseAll() -> None:
    global _websocket_thread
    for address in list(_topic_websockets.keys()):
        CloseTopic(address)


def _poll_websockets():
    """Repeatedly iterate over each topic websocket at an interval."""

    # Keep this routine alive so long as there is at least one websocket.
    while len(_topic_websockets) != 0:
        # Create a dictionary of the current topics with connected websockets, keyed by their
        # websockets' file descriptors.
        topic_handles: Dict[int, _topic_websocket] = {
            address.sock.fileno() : address
            for address in _topic_websockets.values() if address.connected
        }

        # Wait on the readability of the connected file descriptors for a quarter of a second.
        if len(topic_handles) > 0:
            readable_handles, _, _ = select(topic_handles, [], [], 0.25)
    
            if len(readable_handles) != 0:
                unrealsdk.Log(f"Received readable events on handles: {topic_handles}")

                # For each socket returned as readable, tell its topic to receive the message.
                for handle in readable_handles:
                    address = topic_handles[handle]
                    address.receive_message()

        for address in _topic_websockets.values():
            address.poll_status()


class _topic_websocket(websocket.WebSocket):
    """
    A websocket client that listens for a single PubSub topic in the Twitch API, and provides
    interfaces for the various factors relating to its maintenence.
    """

    version = _utilities.version_tuple
    tags = ["AP", "TextOnly"]
    game = ""
    items_handling = 0b111
    slot_data = False
    uuid = uuid.getnode()

    server_port = ""
    player_name = ""
    passcode = ""
    """
    The topic this websocket is responsible for, as originally requested, without having had token
    replacement performed.
    """

    class states:
        """An enumeration of the various states a topic websocket can be in."""
        disconnected = enum.auto()
        """Currently attempting the initial connection to Twitch."""
        connected = enum.auto()
        """Fully connected with a registered LISTEN for the topic."""

    state: states = states.disconnected
    """The current state of the websocket."""

    timeout: float = 0.0
    """The time at which the websocket should be considered to have a connection failure."""

    log: Logger
    """The logger object for this websocket."""


    def __init__(self, auth_string):
        super().__init__()
        name_code, self.address = auth_string.split("@")
        self.player_name, self.passcode = name_code.split(":")

        self.log = log.getChild(self.address)
        unrealsdk.Log("Creating websocket")

        self.address = self.address


    def reconnect(self) -> None:
        """
        Force a new initial connection attempt (disconnecting the websocket if already connected).
        Send the initial PING upon success, or handle any errors that occur on failure.
        """
        self.state = _topic_websocket.states.disconnected

        if self.connected:
            self.log.debug("Already connected, closing")
            self.close()

        try: self.connect(f"wss://{self.address}")
        except: 
            try: self.connect(f"ws://{self.address}")
            except:
                self.log.warn("Failed to connect", exc_info=True)
                return
        
        # With a successful connection, configure the new socket to timeout IO attempts immediately.
        # self.sock.settimeout(0)

    
    def shutdown(self) -> None:
        self.log.info("Closing websocket")
        super().shutdown()


    def poll_status(self) -> None:
        """
        Perform the periodic routine maintenence on this websocket and its state.
        """
        current_time = time.time()

    
    def send_connect(self) -> None:
        payload = [{
            'cmd': 'Connect', 'password': self.passcode, 'name': self.player_name, 'version': self.version,
            'tags': self.tags, 'items_handling': self.items_handling, 'uuid': self.uuid, 'game': self.game,
            'slot_data': self.slot_data
        }]
        self.send(json.dumps(payload))
        unrealsdk.Log("Sent connection")
        self.state = _topic_websocket.states.connected

    def send_chat(self, msg) -> None:
        payload = [{'cmd': 'Say', 'text': msg}]
        self.send(json.dumps(payload))


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
        except Exception as e:
            unrealsdk.Log(f"Error attempting to receive message {e}")
            self.reconnect()
            return

        self.log.debug("Successfully received message from AP Server: %s", message)

        # All valid messages from Twitch should be JSON decodable.
        try: message = json.loads(message)
        except:
            self.log.error("Received message with invalid JSON: %s", message, exc_info=True)
            return

        log.info("Dispatching message to mod callbacks")
        _utilities.MainThreadQueue.append(lambda: MessageCallback(self.address, message))

