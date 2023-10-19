import unrealsdk # type: ignore

import sys
import time
import urllib
import webbrowser

from typing import Callable, Optional, Sequence, Tuple

from Mods.TwitchLogin import _utilities

with _utilities.ImportContext:
    import requests
    import socket

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


def InitiateLogin(scopes: Sequence[str]) -> None:
    """
    Begin the interactive login process, presenting a dialog in-game, starting an HTTP server, and
    opening a browser with a webpage to redirect to Twitch's authorization page.
    """
    global _requested_scopes, _http_listener, _login_dialog
    _requested_scopes = scopes

    log.info("Initiating login process for scopes %s", scopes)

    # Open a socket to listen for incoming connections on our webserver port.
    _http_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _http_listener.bind(("localhost", _PORT))
    _http_listener.listen(5)
    # Set the timeout for accepting connections to the smallest expressable float. We do this method
    # for non-blocking accept(), since setblocking() fails to accept connections for some reason.
    _http_listener.settimeout(sys.float_info.min)

    log.info("Opened HTTP server on localhost:%s", _PORT)

    url = f"http://localhost:{_PORT}{_BEGIN_PATH}"

    # Show a dialog in-game.
    _login_dialog = unrealsdk.GetEngine().GamePlayers[0].Actor.GFxUIManager.ShowTrainingDialog((
        "A window has been opened in your web browser. Follow the prompts to log in with your "
        "Twitch account."
        "\n\n"
        f"If the browser window did not open, you may open the following URL yourself: {url}"
        "\n\n"
        "Closing this dialog cancels the login process."
    ), "Twitch Login", 2, 0, True)

    # Create a callback for when an input is pressed while the dialog is open.
    def dialog_inputkey(caller: unrealsdk.UObject, function: unrealsdk.UFunction, params: unrealsdk.FStruct) -> bool:
        # If the object receiving the input is the dialog, and the input is one of the keys that
        # closes the dialog being pressed, cancel the login attempt.
        if caller is _login_dialog and params.ukey in _DIALOG_KEYS and params.uevent == 1:
            log.info("User cancelled login")
            _end_request()
            ValidationCallback()
        return True

    unrealsdk.RunHook("WillowGame.WillowGFxTrainingDialogBox.HandleInputKey", "TwitchLogin.Login", dialog_inputkey)
    unrealsdk.RunHook("WillowGame.WillowGameViewportClient.Tick", "TwitchLogin.Login", _tick_http_server)

    webbrowser.open(url)


def _end_request():
    global _http_listener, _login_dialog

    unrealsdk.RemoveHook("WillowGame.WillowGFxTrainingDialogBox.HandleInputKey", "TwitchLogin.Login")
    unrealsdk.RemoveHook("WillowGame.WillowGameViewportClient.Tick", "TwitchLogin.Login")

    if _http_listener is not None:
        log.info("Closing HTTP server")
        _http_listener.close()
        _http_listener = None

    if _login_dialog is not None:
        _login_dialog.Close()
        _login_dialog = None


def _http_respond(connection: socket.socket, code: str, content: Optional[str] = None) -> None:
    """Send a response code and optional content to the HTTP client."""

    # Create a list of components of our response, starting with the HTTP response line.
    response = ["HTTP/1.1 " + code]
    # If we are sending content, it will only ever be UTF-8 HTML. Append a content-type header
    # for that, followed by a blank line, then finally the content.
    if content is not None:
        response += ("Content-Type: text/html; charset=UTF-8", "", content)

    response = "\r\n".join(response)
    log.debug("Sending response:\n%s", response)

    # Join the response components with line breaks, send them, and close the connection.
    connection.sendall(response.encode("utf-8"))
    connection.shutdown(socket.SHUT_WR)

def _http_respond_page(connection: socket.socket, content: str) -> None:
    """Send a styled HTML page with the given content."""
    _http_respond(connection, "200 OK", f"""
        <!DOCTYPE html>
        <html lang="en">
            <head><meta charset="utf-8"><title>Borderlands Twitch Login</title></head>
            <body style="background: black;font: 1em sans-serif;color: #ddd;">
                <div style="width: 480px;margin: auto;border-radius: 15px;border: 1px solid #666;padding: 0 1em;background: #161616;">
                    <h1>Borderlands Twitch Login</h1>
                    {content}
                </div>
            </body>
        </html>
    """)

def _http_respond_redirect(connection: socket.socket, url: str) -> None:
    """Send an HTML page that uses Javascript to redirect to the specified URL."""
    _http_respond_page(connection, f"""
        <script type=\"text/javascript\">window.location = {url};</script>
        <p>You will now be redirected.</p>
        <p style="text-align: center;">
            <button onclick="window.location = {url};">Proceed</button>
        </p>
    """)


def _tick_http_server(caller: unrealsdk.UObject, function: unrealsdk.UFunction, params: unrealsdk.FStruct) -> bool:
    # Attempt to accept a connection on our HTTP socket. If none is waiting, this will time out.
    try:
        connection, _ = _http_listener.accept()
        log.debug("Received HTTP request attempt")
    except socket.timeout:
        return True

    # Split the contents of the request into lines.
    request = connection.recv(8192).decode()
    log.debug("Received request data:\n%s", request)

    request_lines = request.splitlines()
    if len(request_lines) == 0:
        _http_respond(connection, "400 Bad Request")
        return

    # We are only concerned with the start line, which contains the HTTP method, target, and
    # version, separated by spaces.
    request_start_line = request_lines[0].split(" ", maxsplit=3)
    if len(request_start_line) != 3:
        log.warn("Received invalid HTTP request")
        _http_respond(connection, "400 Bad Request")
        return True

    # Retrieve the HTTP method (ensuring it is uppercase), as well as the requested path.
    request_method, request_path, _ = request_start_line
    request_method = request_method.upper()
    log.debug("request_method: %s, request_path: %s", request_method, request_path)

    # If the we are receiving a HEAD request, respond with content headers, but empty content.
    if request_method == "HEAD":
        _http_respond(connection, "200 OK", "")
        return True

    # Reject the request if it is neither HEAD nor GET.
    elif request_method != "GET":
        _http_respond(connection, "405 Method Not Allowed")
        return True


    # With a valid GET request, parse the path of the request into its components.
    url = urllib.parse.urlparse(request_path)
    log.debug("Parsed request_path: %s", url)

    if url.path == _BEGIN_PATH:
        twitch_url = _TWITCH_URL + "%20".join(_requested_scopes)
        _http_respond_page(connection, f"""
            <p>To login to your Twitch account, click the button below to be redirected to Twitch.</p>
            <p>For your security:</p>
            <ul>
                <li>Do not stream this browser window while you proceed.</li>
                <li>Review each authorization to ensure you trust your installed mods with them.</li>
            </ul>
            <p style="text-align: center;">
                <button onclick="window.location = '{twitch_url}';">Proceed</button>
            </p>
        """)


    elif url.path == _LOGIN_PATH:
        # For whatever reason, Twitch appends its parameters to our redirect URL as a fragment
        # (`/done#access_token=...`). We cannot access URL fragments from here, so we must use
        # Javascript to redirect the URL with a `?` instead.
        if url.query == "":
            log.info("Sending JavaScript redirect to %s", _LOGIN_PATH)
            _http_respond_redirect(connection, f"'{_LOGIN_PATH}?' + window.location.hash.substring(1)")
            return

        # Send a script to the client to redirect to the done page.
        log.info("Received query parameters at %s, redirecting to %s", _LOGIN_PATH, _DONE_PATH)
        _http_respond_redirect(connection, f"'{_DONE_PATH}'")

        # With an actual query string, parts its parameters into a dictionary.
        query = urllib.parse.parse_qs(url.query)
        log.debug("Parsed URL query string: %s", query)

        # Our OAuth token should be first in its parameter list. Default to None if we did not
        # receive said parameter list.
        global Token
        Token = query.get("access_token", [None])[0]

        Validate(force=True)


    elif url.path == _DONE_PATH:
        if Token is None:
            log.warn("Redirected to %s without having received token", _DONE_PATH)
            _http_respond_page(connection, """
                <p>Something went wrong.</p>
                <p>You may now close this window and return to the game to re-attempt the login process.</p>
            """)
        else:
            log.info("%s page sent", _DONE_PATH)
            _http_respond_page(connection, """
                <p>All done!</p>
                <p>You may now close this window and return to the game.</p>
            """)

        _end_request()


    else:
        log.warn("Unknown page \"%s\" requested", url.path)
        _http_respond(connection, "404 Not Found")

    return True


def Validate(force: bool = False) -> int:
    """
    Synchronously validate our current token with Twitch, and update our information about the user
    associated with it.
    """
    global Token, Scopes, UserName, UserID, Expiration, NextValidation, ValidationStatus

    # If we currently have no token, nothing to do.
    if Token is None:
        log.debug("Validation attempted with no token")
        ValidationStatus = 401
        return 401

    current_time = time.time()

    # If we currently have a token expiration time, and it has expired, report the 
    if 0.0 < Expiration < current_time:
        log.warn("Authentication token has expired")
        ValidationStatus = 401
        Logout()
        return 401

    # If we have not yet reached one hour after our last validation, and were not specified to force
    # a validation, don't do one now.
    if NextValidation > current_time and not force:
        log.debug("Next token validation not for %.0f seconds", NextValidation)
        return 200

    log.info("Attempting token validation")

    # We will send the OAuth token as a header in the request.
    headers = { "Authorization" : "OAuth " + Token }

    # Attempt the request. If Twitch returns a server error, try again.
    response = requests.get("https://id.twitch.tv/oauth2/validate", headers=headers)
    if response.status_code == 503:
        log.warn("First token validation attempt returned 503, retrying")
        response = requests.get("https://id.twitch.tv/oauth2/validate", headers=headers)

    log.debug("Token validation returned %s:\n%s", response.status_code, response.text)
    ValidationStatus = response.status_code

    # With a successful response, update our data regarding the token.
    if ValidationStatus == 200:
        response_data = response.json()

        Scopes = response_data["scopes"]
        UserName = response_data["login"]
        UserID = response_data["user_id"]
        Expiration = response_data["expires_in"] + current_time
        NextValidation = 3600 + current_time

        log.info("Successfully validated token for user %s with scopes %s", UserName, Scopes)

        _utilities.MainThreadQueue.append(ValidationCallback)
        return

    log.warn("Token validation failed with status %s:\n%s", ValidationStatus, response.text)

    if ValidationStatus == 401:
        Token = None
        Logout()

    return ValidationStatus


def Logout() -> None:
    """
    Synchronously request the revocation of our current token, and reset our information about the
    user's authorization.
    """
    global Token, Scopes, UserName, UserID, NextValidation

    log.info("Logging out")

    # Reset our authentication-related parameters, leaving the token and expiration for now.
    Scopes = []
    UserName = None
    UserID = None
    NextValidation = 0.0

    # If we do not have a token, there is nothing to revoke.
    if Token is None:
        log.debug("No token to revoke")
        return

    log.info("Sending token revocation request")

    params = { "client_id": ClientID, "token": Token }

    # Send the request to Twitch's revocation API.
    response = requests.post("https://id.twitch.tv/oauth2/revoke", params=params)
    if response.status_code == 503:
        log.warn("First token revocation attempt returned 503, retrying")
        response = requests.post("https://id.twitch.tv/oauth2/revoke", params=params)

    # If the revocation did not return a successful response, log the details.
    if response.status_code != 200:
        log.warn("Revocation request returned %s:\n%s", response.status_code, response.text)

    Token = None

    _utilities.MainThreadQueue.append(ValidationCallback)
