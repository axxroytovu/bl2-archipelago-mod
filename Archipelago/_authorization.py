import unrealsdk # type: ignore

import sys
import time
import urllib
import webbrowser
import uuid
import json

from typing import Callable, Optional, Sequence, Tuple

from Mods.Archipelago import _utilities

with _utilities.ImportContext:
    import requests
    import socket
    import websocket
    import rel

log = _utilities.log.getChild("Authorization")


ClientID: str = "inuzmy8lmym3yrex7dgpeupj21ogfg"

_PORT: int = 26969
_BEGIN_PATH: str = "/"
_LOGIN_PATH: str = "/login"
_DONE_PATH: str = "/done"

_TWITCH_URL: str = "https://id.twitch.tv/oauth2/authorize?" + urllib.parse.urlencode({
    "client_id":     ClientID,
    "redirect_uri":  f"http://localhost:{_PORT}{_LOGIN_PATH}",
    "response_type": "token",
    "force_verify":  "true",
}) + "&scope="


_DIALOG_KEYS: Tuple[str, ...] = (
    "Enter", "Escape", "LeftMouseButton", "XboxTypeS_A", "XboxTypeS_B", "XboxTypeS_Start"
)


ValidationCallback: Callable[[], None] = lambda: None
"""A callback to be invoked each time the user's authentication changes."""


Token: Optional[str] = None
"""The current OAuth token providing the user's current authentication."""
Scopes: Sequence[str] = []
"""The scopes for which API access is permitted via the user's current authentication."""
UserName: Optional[str] = None
"""The username associated with the user's currently authenticated account."""
UserID: Optional[str] = None
"""The user ID associated with the user's currently authenticated account."""


Expiration: float = 0.0
"""The time at which the user's authentication will expire."""
NextValidation: float = 0.0
"""The time at which we should next valicate the current OAuth token."""
ValidationStatus: int = 0
"""The HTTP response code we last received in response to a validation attempt."""


_requested_scopes: Sequence[str]
_http_listener: socket.socket = None
_login_dialog: unrealsdk.UObject = None


class ServerConnection():
    version = _utilities.version_tuple
    tags = ["AP", "TextOnly"]
    game = ""
    items_handling = 0b111
    slot_data = False
    uuid = uuid.getnode()

    server_port = ""
    player_name = ""
    passcode = ""

    parent = None
    server = None

    def on_message(self):
        unrealsdk.Log(message)

    def on_error(self):
        unrealsdk.Log(error)

    def on_close(self):
        unrealsdk.Log("### closed ###")
        self.parent.ConnectionFailed()

    def on_open(self):
        unrealsdk.Log("Opened connection")

    def parse(self, status):
        if status == ['closed']:
            self.on_close(1, "none")
            return 'break'
        else:
            for command in status:
                if command['cmd'] == "RoomInfo":
                    payload = [{
                        'cmd': 'Connect', 'password': self.passcode, 'name': self.player_name, 'version': self.version,
                        'tags': self.tags, 'items_handling': self.items_handling, 'uuid': self.uuid, 'game': self.game,
                        'slot_data': self.slot_data
                    }]
                    self.server.send(json.dumps(payload))
                    unrealsdk.Log("Sent connection")
                elif command['cmd'] == "Connected":
                    self.parent.LoggedIn()
                elif command['cmd'] == "PrintJSON":
                    for content in command['data']:
                        unrealsdk.Log(content['text'])
                else:
                    unrealsdk.Log(command)
        return "continue"

    def __init__(self, parent, auth_string):
        self.parent = parent
        name_code, self.server_port = auth_string.split("@")
        self.player_name, self.passcode = name_code.split(":")

    def InitiateLogin(self):
        self.server = websocket.WebSocket()
        try:
            self.server.connect(f"wss://{self.server_port}")
        except:
            self.server.connect(f"ws://{self.server_port}")
        unrealsdk.RunHook("WillowGame.WillowGameViewportClient.Tick", "log_incoming", lambda a,b,c: self.log_incoming(a,b,c))

    def log_incoming(self, caller: unrealsdk.UObject, function: unrealsdk.UFunction, params: unrealsdk.FStruct) -> bool:
        try:
            sstatus = self.server.recv()
        except websocket.WebSocketConnectionClosedException:
            sstatus = '["closed"]'
        if sstatus: 
            self.parse(json.loads(sstatus))
        return True
