from __future__ import annotations

import unrealsdk # type: ignore

import sys
import time
import urllib
import webbrowser
import uuid
import json
import threading
import random

from collections import deque
from select import select

from typing import Callable, Optional, Sequence, Tuple

from Mods.Archipelago import _utilities

with _utilities.ImportContext:
    import requests
    import socket
    import websocket
    import rel

log = _utilities.log.getChild("Authorization")

MessageCallback: Callable[[str, Dict[str, Any]], None]

_websocket_thread: Optional[threading.Thread] = None

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

    def log_incoming(self, caller: unrealsdk.UObject, function: unrealsdk.UFunction, params: unrealsdk.FStruct) -> bool:
        try:
            sstatus = self.server.recv()
        except websocket.WebSocketConnectionClosedException:
            sstatus = '["closed"]'
        if sstatus: 
            self.parse(json.loads(sstatus))
        return True
