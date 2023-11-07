import unrealsdk # type: ignore
from Mods import ModMenu #, PickupMessages as _messenger

import functools
import os
import sys
import time
import json
import urllib

from collections.abc import Mapping
from typing import Any, Dict, List, Sequence, Set, Optional, Type

if __name__ == "__main__":
    import importlib
    for submodule in ("_utilities", "_pubsub"):
        submodule = "Mods.Archipelago." + submodule
        if submodule in sys.modules:
            importlib.reload(sys.modules[submodule])

    # See: https://github.com/bl-sdk/PythonSDK/issues/68
    try: raise NotImplementedError
    except NotImplementedError:
        __file__ = os.path.abspath(sys.exc_info()[-1].tb_frame.f_code.co_filename)

from Mods.Archipelago import _utilities, _pubsub
from Mods.UserFeedback import TextInputBox

with _utilities.ImportContext:
    import requests
    import websocket


_saved_server_port: ModMenu.Options.Base = ModMenu.Options.Hidden(Caption="AP Server & Port", StartingValue="localhost:38281")
"""A ModMenu Option to save the last connected archipelago server."""
_saved_player_name: ModMenu.Options.Base = ModMenu.Options.Hidden(Caption="AP Name", StartingValue="Axxroy")
"""A ModMenu Option to save the last connected archipelago name."""
Passcode = ""

def _DisplayGameMessage(message: str, subtitle: str, duration: float = 5) -> None:
    """Display a small UI message (in the same place as Steam connection messages, for example)."""
    unrealsdk.GetEngine().GamePlayers[0].Actor.DisplayGameMessage(
        MessageType = 5, Duration = duration, Message = message, Subtitle = subtitle
    )

def send_chat():
    chat_box = TextInputBox("Message", "", True)
    chat_box.OnSubmit=next(iter(_pubsub._topic_websockets.values())).send_chat
    chat_box.Show()

def send_check():
    next(iter(_pubsub._topic_websockets.values())).send_check()
    

class Archipelago(ModMenu.SDKMod):
    Name: str = "Archipelago Connector"
    Author: str = "Axxroy"
    Description: str = (
        "Connect to an Archipelago Multi-World Randomizer Server."
    )
    Version: str = "0.0"
    Types: ModMenu.ModTypes = ModMenu.ModTypes.Gameplay
    
    Keybinds = [
        ModMenu.Keybind("Chat Window", "F3", OnPress=send_chat),
        ModMenu.Keybind("Send Check", "F4", OnPress=send_check)
    ]

    Status: str = "<font color=\"#ff0000\">Not Connected</font>"

    Options: Sequence[ModMenu.Options.Base] = ( _saved_server_port, _saved_player_name )

    Passcode: str
    Server = None

    _mod_menu_item: Optional[unrealsdk.UObject] = None
    """Our last known GFX object in the marketplace (mod menu)."""
    
    def _update_mod_menu(self) -> None:
        """Update our details for our mod menu entry, and force the mod menu to refresh."""

        # If we do not have a record of our current marketplace GFX object, we have nothing to do.
        if self._mod_menu_item is None:
            return

        # Get the current player, and from that, the current player controller and main menu object.
        player = unrealsdk.GetEngine().GamePlayers[0]
        pc = player.Actor
        menu = pc.GetFrontendMovie()

        # If there currently isn't a menu object and marketplace movie, we have nothing to do.
        if menu is None or menu.MarketplaceMovie is None:
            return
        mod_menu = menu.MarketplaceMovie

        # Update the relevant fields of our menu GFX object with our new status and description.
        translation = player.GetTranslationContext()
        self._mod_menu_item.SetString(mod_menu.Prop_messageText, self.Status, translation)
        self._mod_menu_item.SetString(mod_menu.Prop_descriptionText, self.Description, translation)

        # Ported from WillowGame.MarketplaceGFxMovie.RefreshDLC to force the marketplace menu to
        # update.
        mod_menu.ShowMarketplaceElements(False)
        mod_menu.SetShoppingTooltips(False, False, False, False, True)
        mod_menu.SetContentData()

        controller_id = pc.GetMyControllerId()
        pc.OnlineSub.ContentInterface.ObjectPointer.ReadDownloadableContentList(controller_id)


    def Enable(self) -> None:
        ModMenu.HookManager.RegisterHooks(self)
        ModMenu.NetworkManager.RegisterNetworkMethods(self)
        box_server = TextInputBox("Archipelago Connection String", f"{_saved_player_name.CurrentValue}:{Passcode}@{_saved_server_port.CurrentValue}", True)
        def OnSubmit(msg):
            unrealsdk.Log(msg)
            name_code, _saved_server_port.CurrentValue = msg.split("@")
            _saved_player_name.CurrentValue, Passcode = name_code.split(":")
            _pubsub.OpenTopic(msg)
            self.Server = _pubsub._topic_websockets[msg]
        box_server.OnSubmit = OnSubmit
        box_server.Show()
        unrealsdk.Log("Logged In")
        self.Status = "<font color=\"#00ff00\">Logged In</font>"
        self._update_mod_menu()

    def Disable(self) -> None:
        ModMenu.HookManager.RemoveHooks(self)
        ModMenu.NetworkManager.UnregisterNetworkMethods(self)
        _pubsub.CloseAll()
        self.Status = "<font color=\"#ff0000\">Logged Out</font>"
        self._update_mod_menu()

    def parse_inputs(self, address, message):
        for content in message:
            messageType = content.get("cmd", "").upper()
            unrealsdk.Log(content)
            if messageType == "":
                unrealsdk.Log("Received empty message")
            elif messageType == "ROOMINFO":
                unrealsdk.Log("Received room info")
                self.Server.send_connect()
            elif messageType == "DATAPACKAGE":
                self.Server.data_package = content['data']
                #self.items = {v: k for k, v in content['data']['games']['Borderlands 2']['item_name_to_id'].items()}
                unrealsdk.Log("Received data package")
            elif messageType == "RECONNECT":
                unrealsdk.Log("Received request to reconnect")
                self.Server.reconnect()
            elif messageType == "CONNECTED":
                unrealsdk.Log("CONNECTED")
            elif messageType == "RECEIVEDITEMS":
                for i in content['items']:
                    unrealsdk.Log(f"Received item {i}")
            elif messageType == "PRINTJSON":
                for text in content['data']:
                    _DisplayGameMessage(text['text'], "")
            #else:
            #    unrealsdk.Log(content)

    def __init__(self):
        _pubsub.MessageCallback = self.parse_inputs
        unrealsdk.Log(self.Keybinds)


_mod_instance = Archipelago()

if __name__ == "__main__":
    for mod in ModMenu.Mods:
        if mod.Name == _mod_instance.Name:
            if mod.IsEnabled:
                mod.Disable()
            ModMenu.Mods.remove(mod)
            _mod_instance.__class__.__module__ = mod.__class__.__module__
            break

ModMenu.RegisterMod(_mod_instance)
