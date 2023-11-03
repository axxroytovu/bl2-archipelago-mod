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
    unrealsdk.Log("Key Pressed")
    #chat_box = TextInputBox("Message", "", True)
    #chat_box.OnSubmit=next(iter(_pubsub._core_websocket.values())).send_chat(msg)
    #chat_box.Show()
    

class Archipelago(ModMenu.SDKMod):
    Name: str = "Archipelago Connector"
    Author: str = "Axxroy"
    Description: str = (
        "Connect to an Archipelago Multi-World Randomizer Server."
    )
    Version: str = "0.0"
    Types: ModMenu.ModTypes = ModMenu.ModTypes.Gameplay
    
    Keybinds = [
        ModMenu.Keybind("Chat Window", "F3", OnPress=lambda: unrealsdk.Log("Key Pressed")),
    ]

    Status: str = "<font color=\"#ff0000\">Not Connected</font>"
    SettingsInputs: Dict[str, str] = { "Enter": "Connect" }

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


    def LoggedIn(self) -> None:
        unrealsdk.Log("Logged In")
        self.Status = "<font color=\"#00ff00\">Logged In</font>"
        self.Description = f"{Archipelago.Description}\n\nCurrently logged in as: {_saved_player_name.CurrentValue}"
        self.SettingsInputs = { "Delete": "Disconnect" }
        self._update_mod_menu()

    def LoggedOut(self) -> None:
        self.Status = "<font color=\"#ff0000\">Logged Out</font>"
        self.Description = Archipelago.Description
        self.SettingsInputs = { "Enter": "Connect" }
        self._update_mod_menu()

    def LoginExpired(self) -> None:
        self.Status = "<font color=\"#ff0000\">Login Expired</font>"
        self.Description = (
            Archipelago.Description + 
            "\n\nYour login has expired, please login again."
        )
        self.SettingsInputs = { "Enter": "Reconnect" }
        self._update_mod_menu()
        _DisplayGameMessage(
            "Archipelago Connection Expired",
            "Please log in again to continue using Archipelago"
        )

    def ConnectionFailed(self) -> None:
        self.Status = "<font color=\"#ffff00\">Connection Failed</font>"
        self.Description = (
            Archipelago.Description + 
            "\n\nError connecting to the Archipelago server."
        )
        self.SettingsInputs = { "Enter": "Reconnect" }
        self._update_mod_menu()
        _DisplayGameMessage(
            "Archipelago Connection Failure",
            "Archipelago Mod will not be functional."
        )

    def MissingPermissions(self) -> None:
        mod_names = ", ".join(mod.Name for mod in _mods_missing_permissions)

        self.Status = "<font color=\"#ffff00\">Missing Permissions</font>"
        self.Description = (
            f"{Archipelago.Description}\n\n"
            f"Currently logged in as: {UserName}\n\n"
            f"Missing permissions required by mods: {mod_names}"
        )
        self.SettingsInputs = { "Enter": "Reconnect", "Delete": "Disconnect" }
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
            elif messageType == "RECONNECT":
                unrealsdk.Log("Received request to reconnect")
                self.Server.reconnect()
            elif messageType == "CONNECTED":
                unrealsdk.Log("CONNECTED")
                self.LoggedIn()
            elif messageType == "PRINTJSON":
                for text in content['data']:
                    _DisplayGameMessage(text['text'], "")
            #else:
            #    unrealsdk.Log(content)

    def SettingsInputPressed(self, action: str) -> None:
        unrealsdk.Log(action)
        #pc = unrealsdk.GetEngine().GamePlayers[0].Actor
        #self._mod_menu_item = pc.GetFrontendMovie().MarketplaceMovie.GetSelectedObject()

        if action == "Connect":
            
            box_server = TextInputBox("Archipelago Connection String", f"{_saved_player_name.CurrentValue}:{Passcode}@{_saved_server_port.CurrentValue}", True)
            def OnSubmit(msg):
                unrealsdk.Log(msg)
                name_code, _saved_server_port.CurrentValue = msg.split("@")
                _saved_player_name.CurrentValue, Passcode = name_code.split(":")
                _pubsub.OpenTopic(msg)
                self.Server = _pubsub._topic_websockets[msg]
            box_server.OnSubmit = OnSubmit
            box_server.Show()

        elif action == "Disconnect":
            _pubsub.CloseAll()
            self.LoggedOut()

        """
        elif action == "Re-Login":
            _authorization.Logout()
            _authorization.InitiateLogin(_registered_scopes)

        elif action == "Reconnect":
            _authorization.Validate(force=True)
        """

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
