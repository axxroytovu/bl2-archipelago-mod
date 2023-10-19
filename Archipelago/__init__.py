import unrealsdk # type: ignore
from Mods import ModMenu

import functools
import os
import sys
import time

from collections.abc import Mapping
from typing import Any, Dict, List, Sequence, Set, Optional, Type

if __name__ == "__main__":
    import importlib
    for submodule in ("_authorization", "_pubsub", "_requests"):
        submodule = "Mods.TwitchLogin." + submodule
        if submodule in sys.modules:
            importlib.reload(sys.modules[submodule])

    # See: https://github.com/bl-sdk/PythonSDK/issues/68
    try: raise NotImplementedError
    except NotImplementedError:
        __file__ = os.path.abspath(sys.exc_info()[-1].tb_frame.f_code.co_filename)

from Mods.TwitchLogin import _authorization, _pubsub, _requests as Requests
from Mods.TwitchLogin._utilities import log


__all__: List[str] = [
    "RegisterMod", "UnregisterMod", "RegisterWhileEnabled",
    "Token", "Scopes", "UserName", "UserID",
    "Requests",
]


def RegisterMod(mod: ModMenu.SDKMod) -> None:
    """
    Register the Twitch scopes and PubSub topics specified by the given mod's `TwitchScopes` and/or
    `TwitchTopics` attributes, and register the mod to have its `TwitchLoginChanged()` method called
    when the user's authentication changes.

    The mod may optionally define a `TwitchScopes` attribute, containing a sequence of strings
    representing scopes in the Twitch API; e.g. "channel:read:redemptions". See:
    https://dev.twitch.tv/docs/authentication#scopes

    TwitchLogin attempts to acquire authorization for each scope requested by mods in this way. The
    user is directed to the Twitch authorization webpage, in which they are presented with the
    complete list of scopes requested.

    Upon authorization, Twitch grants permission for each valid scope. If any scopes requested by
    mods were not granted, i.e. they were invalid scopes, an error will be logged to the console
    and TwitchLogin's "logging.log" file.

    The mod may optionally define a `TwitchTopics` attribute, containing a mapping of strings to
    callables. The strings serving as keys represent topics in the Twitch PubSub API. See:
    https://dev.twitch.tv/docs/pubsub#topics

    Topic strings may optionally include the format token `{UserID}`. If it does, the token will be
    replaced with the user ID (A.K.A. channel ID) of the user's Twitch account when listening for
    the topic. For example, a string of "channel-points-channel-v1.{UserID}" will listen for the
    topic "channel-points-channel-v1.44322889".

    The callable each topic maps to is invoked each time a message is received for its respective
    topic. Callables should accept a single parameter; upon invocation of the callable, a dictionary
    containing the `data` field of the message will be passed to this parameter.

    If Twitch returns any errors when attempting to listen for a topic, the error will be logged to
    the console and TwitchLogin's "logging.log" file.

    If the mod defines a `TwitchLoginChanged` method, it will be invoked each time the user's login
    status changes. This method should accept a boolean as the only parameter after `self`. If the
    user has successfully authenticated, a value of `True` will be provided. If they have logged
    out, a value of `False` will be instead.
    """
    log.info("Registering mod %s", mod)

    _register_mod_scopes(mod)
    _register_mod_topics(mod)

    _registered_mods.add(mod)

    # If we are currently logged in as per having an authorization token, notify the mod.
    if _authorization.Token is not None:
        _notify_mod_of_login(mod, True)


def UnregisterMod(mod: ModMenu.SDKMod):
    """
    Remove the given mod's registration from TwitchLogin. It will no longer receive messages on its
    PubSub topic callbacks, and scopes it registered for will not be requested in future user
    authorizations. It will also not receive notifications of the user's login status changing on
    its `TwitchLoginChanged` method.
    """
    log.info("Unregistering mod %s", mod)

    if mod not in _registered_mods:
        return

    _registered_mods.remove(mod)

    unregistered_scopes = set()
    unregistered_topics = set()

    # Iterate over each scope in our registry that is registered for by this mod.
    for scope, mods in _registered_scopes.items():
        if mod in mods:
            # Remove the mod from the set of registering mods.
            mods.remove(mod)
            # If there are no more mods registering this scope, we will remove it from the registry.
            if len(mods) == 0:
                unregistered_scopes.add(scope)

    # Remove each scope from the registry that had no remaining mods registering it.
    for scope in unregistered_scopes:
        if scope in _registered_scopes:
            del _registered_scopes[scope]

    # Iterate over each scope in our registry that is registered for by this mod.
    for topic, mods in _registered_topics.items():
        if mod in mods:
            # Remove the mod from the set of registering mods.
            mods.remove(mod)
            # If there are no more mods registering this scope, remove it from the registry.
            if len(mods) == 0:
                unregistered_topics.add(scope)

    # Close and remove each topic from the registry that had no remaining mods registering it.
    for topic in unregistered_topics:
        _pubsub.CloseTopic(topic)
        if topic in _registered_topics:
            del _registered_topics[topic]


def RegisterWhileEnabled(cls: Type[ModMenu.SDKMod]) -> Type[ModMenu.SDKMod]:
    """
    A decorator for SDKMod classes that configures them to be registered with TwitchLogin while
    enabled.
    
    More specifically, `TwitchLogin.RegisterMod()` is called on instances of the mod class at the
    end of its `Enable()` method, and `TwitchLogin.UnregisterMod()` is called on it before its
    `Disable()` method is run.
    """

    # Retrieve the class's Enable and Disable implementations.
    original_enable = cls.Enable
    original_disable = cls.Disable

    # Define new Enable and Disable methods that invoke the originals, as well as our registration
    # methods.
    @functools.wraps(original_enable)
    def Enable(self):
        original_enable(self)
        RegisterMod(self)

    @functools.wraps(original_disable)
    def Disable(self):
        UnregisterMod(self)
        original_disable(self)

    # Replace the Enable and Disable methods with the new versions, then return the class.
    cls.Enable = Enable
    cls.Disable = Disable
    return cls


Token: Optional[str] = None
"""
The OAuth token providing the user's current authentication. If the user is not currently
authenticated, this will be `None`.
"""

Scopes: Sequence[str] = []
"""The scopes for which API access is permitted via the user's current authentication."""

UserName: Optional[str] = None
"""
The username associated with the user's currently authenticated account. If the user is not
currently authenticated, this will be `None`.
"""

UserID: Optional[str] = None
"""
The user ID associated with the user's currently authenticated account. If the user is not currently
authenticated, this will be `None`.
"""


_registered_mods: Set[ModMenu.SDKMod] = set()
"""
A set containing each mod that has been registered with us.
"""
_registered_scopes: Dict[str, Set[ModMenu.SDKMod]] = {}
"""
The scopes that mods have registered with us, each keying a set containing the mods that have
registered them.
"""
_registered_topics: Dict[str, Set[ModMenu.SDKMod]] = {}
"""
The PubSub topics that mods have registered with us, each keying a set containing the mods that have
registered them.
"""

_mods_missing_permissions: Set[ModMenu.SDKMod] = set()
"""
A set of mods that have been found to be requesting scopes that the user's current authentication
doesn't include.
"""

_saved_token: ModMenu.Options.Base = ModMenu.Options.Hidden(Caption="Token", StartingValue=None)
"""A ModMenu Option to save the user's authorization token."""
_saved_expiration: ModMenu.Options.Base = ModMenu.Options.Hidden(Caption="Expiration", StartingValue=0.0)
"""A ModMenu Option to save the expiration time of the user's authorization token."""


def _register_mod_scopes(mod: ModMenu.SDKMod) -> None:
    """
    Register the mod for the scopes specified in its `TwitchScopes` attribute, if it has one.
    """

    # If the registering mod doesn't have a TwitchScopes attribute, nothing to do.
    scopes = getattr(mod, "TwitchScopes")
    if scopes is None:
        log.debug("No TwitchScopes registered by mod %s", mod)
        return

    # If the TwitchScopes attribute is not iterable, report the error.
    if not hasattr(scopes, '__iter__'):
        log.error("TwitchScopes attribute of %s is not iterable", mod)
        return

    for scope in scopes:
        # If we encounter any non-strings, report the error and skip them.
        if not isinstance(scope, str):
            log.error("Found non-str object %s in TwitchScopes attribute of %s", scope, mod)
            continue

        # Append the mod to our list for the scope, creating one if necessary.
        _registered_scopes.setdefault(scope, set()).add(mod)

        # If the user is currently authenticated but not for the requested scope, this mod will be
        # reported as missing permissions.
        if _authorization.Token is not None and scope not in _authorization.Scopes:
            log.warn("Current authorization missing scope %s for mod %s", scope, mod)
            _mods_missing_permissions.add(mod)

        else:
            log.debug("Registering scope '%s' for mod %s", scope, mod)

    # If the mod is missing any permissions after iterating its scopes, update our mod's status.
    if mod in _mods_missing_permissions:
        _mod_instance.MissingPermissions()


def _register_mod_topics(mod: ModMenu.SDKMod) -> None:
    """
    Register the mod for the PubSub topics specified in its `TwitchTopics` attribute, if it has one.
    """

    # If the registering mod doesn't have a TwitchTopics attribute, nothing to do.
    topics = getattr(mod, "TwitchTopics")
    if topics is None:
        log.debug("No TwitchTopics registered by mod %s", mod)
        return

    # If the TwitchScopes attribute is not iterable, report the error.
    if not isinstance(topics, Mapping):
        log.error("TwitchScopes attribute of %s is not a mapping type", mod)
        return

    for topic in topics.keys():
        # If we encounter any non-strings, report the error and skip them.
        if not isinstance(topic, str):
            log.error("Found non-str object %s in TwitchScopes attribute of %s", topic, mod)
            continue

        # Append the mod to our list for the topic, creating one if necessary.
        _registered_topics.setdefault(topic, set()).add(mod)

        if _authorization.Token is not None:
            log.info("Registering PubSub topic '%s' for mod %s", topic, mod)
            _pubsub.OpenTopic(topic)


def _notify_mod_of_login(mod: ModMenu.SDKMod, logged_in: bool) -> None:
    """Invoke the TwitchLoginChanged method for the given mod, if it defines one."""
    if not hasattr(mod, "TwitchLoginChanged"):
        log.debug("No TwitchLoginChanged for mod %s", mod)
        return

    try: mod.TwitchLoginChanged(logged_in)
    except:
        log.error("Exception while invoking TwitchLoginChanged for mod %s", mod, exc_info=True)


def _DisplayGameMessage(message: str, subtitle: str, duration: float = 5) -> None:
    """Display a small UI message (in the same place as Steam connection messages, for example)."""
    unrealsdk.GetEngine().GamePlayers[0].Actor.DisplayGameMessage(
        MessageType = 5, Duration = duration, Message = message, Subtitle = subtitle
    )


def _handle_validation() -> None:
    """
    The callback we provide to our authorization framework, to be invoked each time the user's
    authentication state changes.
    """
    global Token, Scopes, UserName, UserID, _mods_missing_permissions

    # Update our local copies of the authorization-related variables, such that they are
    # accessible from the top level of this module.
    Token = _authorization.Token
    Scopes = _authorization.Scopes
    UserName = _authorization.UserName
    UserID = _authorization.UserID

    # Update the saved copies of the user's authentication token, and its expiration.
    _saved_token.CurrentValue = _authorization.Token
    _saved_expiration.CurrentValue = _authorization.Expiration
    ModMenu.SaveModSettings(_mod_instance)

    # If we are now logged out as evidence by not having an authentication token, we will present a
    # relevant message to the user, and update our status in the mod menu accordingly.
    if _authorization.Token is None:
        log.debug("Validation callback invoked with no token")

        # If the previous token had expired, indicate as such.
        if 0.0 < _authorization.Expiration < time.time():
            log.debug("Previous token had expired")
            _mod_instance.LoginExpired()

        # If the last validation request's status code indicates an authorization error,
        # indicate as such.
        elif 400 <= _authorization.ValidationStatus <= 499:
            log.debug("Previous token was not authorized")
            _DisplayGameMessage(
                "Twitch Login Error",
                "Please log in again to continue using mods with Twitch features"
            )
            _mod_instance.LoggedOut()

        else:
            _mod_instance.LoggedOut()

        # Shutdown each PubSub topic we may be listening for.
        for topic in _registered_topics:
            _pubsub.CloseTopic(topic)

        # Notify our registered mods that we are now not logged in.
        for mod in _registered_mods:
            _notify_mod_of_login(mod, False)

    else:
        log.debug("Validation callback invoked with token")

        # If the last validation request's received a server error, indicate as such.
        if 500 <= _authorization.ValidationStatus <= 599:
            log.debug("Validation failed to connect to Twitch")
            _mod_instance.ConnectionFailed()
            return

        # If we are now logged in, first reset our set of mods that are missing permissions.
        _mods_missing_permissions = set()

        # Iterate over each scope mods requested authorization for. If any is missing from the
        # scopes authorized by Twitch, add the requesting mods to the ones missing permissions.
        for scope, mods in _registered_scopes.items():
            if scope not in _authorization.Scopes:
                log.error("Twitch did not authorize for '%s' (requested by %s)", scope, mods)
                _mods_missing_permissions.update(mods)

        # If there are in fact any mods missing persmissions, update our status as such.
        if len(_mods_missing_permissions) == 0:
            _mod_instance.LoggedIn()
        # Otherwise, display that we are cleanly logged in.
        else:
            _mod_instance.MissingPermissions()

        # Start listening for each topic that was requested of us.
        for topic, mods in _registered_topics.items():
            log.info("Registering PubSub topic '%s' for mods %s", topic, mods)
            _pubsub.OpenTopic(topic)

        # Notify our registered mods that we are now logged in.
        for mod in _registered_mods:
            _notify_mod_of_login(mod, True)


def _handle_pubsub_message(topic: str, data: Dict[str, Any]) -> None:
    """
    The callback we provide to our PubSub framework, to be invoked each time a topic we are
    listening for receives a message.
    """
    for mod in _registered_topics[topic]:
        try: mod.TwitchTopics[topic](data)
        except:
            log.error(
                "Mod %s raised an exception in its callback for topic %s",
                mod, topic, exc_info=True
            )


class TwitchLogin(ModMenu.SDKMod):
    Name: str = "Twitch Login"
    Author: str = "apple1417 & mopioid"
    Description: str = (
        "Log in with your (or your bot's) Twitch account to enable mods with Twitch functionality."
    )
    Version: str = "1.1"
    Types: ModMenu.ModTypes = ModMenu.ModTypes.Utility

    Status: str = "<font color=\"#ff0000\">Not Logged In</font>"
    SettingsInputs: Dict[str, str] = { "Enter": "Login" }

    Options: Sequence[ModMenu.Options.Base] = ( _saved_token, _saved_expiration )


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
        self.Status = "<font color=\"#00ff00\">Logged In</font>"
        self.Description = f"{TwitchLogin.Description}\n\nCurrently logged in as: {UserName}"
        self.SettingsInputs = { "Delete": "Logout" }
        self._update_mod_menu()

    def LoggedOut(self) -> None:
        self.Status = "<font color=\"#ff0000\">Logged Out</font>"
        self.Description = TwitchLogin.Description
        self.SettingsInputs = { "Enter": "Login" }
        self._update_mod_menu()

    def LoginExpired(self) -> None:
        self.Status = "<font color=\"#ff0000\">Login Expired</font>"
        self.Description = (
            TwitchLogin.Description + 
            "\n\nYour login has expired, please login again."
        )
        self.SettingsInputs = { "Enter": "Re-Login" }
        self._update_mod_menu()
        _DisplayGameMessage(
            "Twitch Login Expired",
            "lease log in again to continue using mods with Twitch features"
        )

    def ConnectionFailed(self) -> None:
        self.Status = "<font color=\"#ffff00\">Connection Failed</font>"
        self.Description = (
            TwitchLogin.Description + 
            "\n\nError connecting to the Twitch servers."
        )
        self.SettingsInputs = { "Enter": "Reconnect" }
        self._update_mod_menu()
        _DisplayGameMessage(
            "Twitch Connection Failure",
            "Mods with Twitch features will not be fully functional."
        )

    def MissingPermissions(self) -> None:
        mod_names = ", ".join(mod.Name for mod in _mods_missing_permissions)

        self.Status = "<font color=\"#ffff00\">Missing Permissions</font>"
        self.Description = (
            f"{TwitchLogin.Description}\n\n"
            f"Currently logged in as: {UserName}\n\n"
            f"Missing permissions required by mods: {mod_names}"
        )
        self.SettingsInputs = { "Enter": "Re-Login", "Delete": "Logout" }
        self._update_mod_menu()


    def SettingsInputPressed(self, action: str) -> None:
        pc = unrealsdk.GetEngine().GamePlayers[0].Actor
        self._mod_menu_item = pc.GetFrontendMovie().MarketplaceMovie.GetSelectedObject()

        if action == "Login":
            _authorization.InitiateLogin(_registered_scopes)

        elif action == "Logout":
            _authorization.Logout()

        elif action == "Re-Login":
            _authorization.Logout()
            _authorization.InitiateLogin(_registered_scopes)

        elif action == "Reconnect":
            _authorization.Validate(force=True)


    def __init__(self):
        _authorization.ValidationCallback = _handle_validation
        _pubsub.MessageCallback = _handle_pubsub_message

        ModMenu.SettingsManager.LoadModSettings(self)
        if _saved_token.CurrentValue is not None:
            if _saved_expiration.CurrentValue < time.time():
                self.LoginExpired()
            else:
                _authorization.Token = _saved_token.CurrentValue
                _authorization.Validate(force=True)


_mod_instance = TwitchLogin()

if __name__ == "__main__":
    for mod in ModMenu.Mods:
        if mod.Name == _mod_instance.Name:
            if mod.IsEnabled:
                mod.Disable()
            ModMenu.Mods.remove(mod)
            _mod_instance.__class__.__module__ = mod.__class__.__module__
            break

ModMenu.RegisterMod(_mod_instance)
