from requests.api import head
import unrealsdk # type: ignore

import threading
import time

from typing import Any, Callable, Dict

from Mods.TwitchLogin import _authorization, _utilities

with _utilities.ImportContext:
    import requests


def Request(
    Method: str,
    Path: str,
    Params: Any = None,
    Data: Any = None,
    *,
    Callback: Callable[[int, Dict[str, Any]], None]
) -> None:
    """
    Asynchronously send a request to the Twitch API with the user's authentication.

    The scopes required for a given Twitch API request must have been registered for with
    `TwitchLogin.RegisterMod(mod)`, with the `mod` object having the relevant
    `TwitchLogin.TwitchScope` object in its `TwitchScopes` property. The user must have then logged
    in upon being notified of their requirement to do so. Without the authorized scope, the Twitch
    API will respond to the request with an error.

    Arguments:
        Method:
            The method to use for sending the request. This can be GET, POST, PUT, PATCH, or DELETE.
        Path:
            The path in the Twitch API URL to send the request. This should be the entire path
            after "/helix/"; for example, specfying "channel_points/custom_rewards" causes the
            request to be sent to "https://api.twitch.tv/helix/channel_points/custom_rewards".
        Params:
            Optional dictionary, list of tuples, or bytes, to append to the URL of the request
            as its query. If a dictionary or sequence of tuples `(key, value)` is provided, the
            contents will be form-encoded. See: https://docs.python-requests.org/en/latest/api
        Data:
            Optional object to send as the request of the body. A JSON-serializable dictionary is
            generally recommended for the Twitch API, but this may also be a sequence of tuples,
            bytes, or file-like object. See: https://docs.python-requests.org/en/latest/api
        Callback:
            The function to be invoked upon completion of the request. This function must accept
            two arguments - An `int` representing the status code of the response, and a `dict`
            containing the content of the response, if any.
    """
    log = _utilities.log.getChild(f"Requests.{time.time_ns}")

    # Format the URL to send the request by appending the path to the API base URL.
    url = "https://api.twitch.tv/helix/" + Path

    # Create a dictionary of headers to send using our client ID and the user's OAuth token.
    headers = {
        "client-id": _authorization.ClientID,
        "Authorization": "Bearer " + _authorization.Token
    }

    log.debug(
        "Creating request: %s %s\nparams: %s\nheaders: %s\ndata: %s",
        Method, url, Params, headers, Data
    )

    # Create a record of whether we have attempted token validation during this request.
    checked_validation = False

    # We will be performing the request on another thread, so create a function to target.
    def perform_request():
        nonlocal checked_validation

        response_code = _authorization.Validate()
        if 200 > response_code > 299:
            log.warn("Authentication validation failed, aborting request")

        else:
            log.info("Sending request")

            # Perform the request. If we receive a server error, perform one more attempt.
            response = requests.request(Method, url, params=Params, headers=headers, data=Data)
            if 500 <= response_code <= 599:
                log.warn("Twitch returned %s, retrying", response.status_code)
                response = requests.request(Method, url, params=Params, headers=headers, data=Data)

            # Get the final response code.
            response_code = response.status_code

            # If we get an authentication error, and have not yet performed a second attempt in
            # which we have had our authorization framework attempt token validation, do so.
            if response_code == 401 and not checked_validation:
                log.warn("Received authentication error, retrying with token validation")
                _authorization.NextValidation = 0.0
                checked_validation = True
                perform_request()
                return

            # If the response code is not in the 200 range (success), report the error.
            if 200 > response_code > 299:
                log.error("Request failed with status %s: %s", response.status_code, response.text)

            # Attempt to decode the JSON response, if any.
            try: response_content = response.json()
            except:
                log.debug("No JSON-decodable content in response to request")
                response_content = {}

        # Invoke the provided callback with the status code and response content on the main thread.
        _utilities.MainThreadQueue.append(
            lambda: Callback(response_code, response_content)
        )

    # Start the thread with the request routine.
    threading.Thread(target=perform_request).start()


def Delete(Path: str, Params: Any = None, *, Callback: Callable[[int, Dict[str, Any]], None]) -> None:
    """
    Asynchronously send a DELETE request to the Twitch API with the user's authentication.

    The scopes required for a given Twitch API request must have been registered for with
    `TwitchLogin.RegisterMod(mod)`, with the `mod` object having the relevant
    `TwitchLogin.TwitchScope` object in its `TwitchScopes` property. The user must have then logged
    in upon being notified of their requirement to do so. Without the authorized scope, the Twitch
    API will respond to the request with an error.

    Arguments:
        Path:
            The path in the Twitch API URL to send the request. This should be the entire path
            after "/helix/"; for example, specfying "channel_points/custom_rewards" causes the
            request to be sent to "https://api.twitch.tv/helix/channel_points/custom_rewards".
        Params:
            Optional dictionary, list of tuples, or bytes, to append to the URL of the request
            as its query. If a dictionary or sequence of tuples `(key, value)` is provided, the
            contents will be form-encoded. See: https://docs.python-requests.org/en/latest/api
        Callback:
            The function to be invoked upon completion of the request. This function must accept
            two arguments - An `int` representing the status code of the response, and a `dict`
            containing the content of the response, if any.
    """
    Request("DELETE", Path, Params, None, Callback=Callback)

def Get(Path: str, Params: Any = None, *, Callback: Callable[[int, Dict[str, Any]], None]) -> None:
    """
    Asynchronously send a GET request to the Twitch API with the user's authentication.

    The scopes required for a given Twitch API request must have been registered for with
    `TwitchLogin.RegisterMod(mod)`, with the `mod` object having the relevant
    `TwitchLogin.TwitchScope` object in its `TwitchScopes` property. The user must have then logged
    in upon being notified of their requirement to do so. Without the authorized scope, the Twitch
    API will respond to the request with an error.

    Arguments:
        Path:
            The path in the Twitch API URL to send the request. This should be the entire path
            after "/helix/"; for example, specfying "channel_points/custom_rewards" causes the
            request to be sent to "https://api.twitch.tv/helix/channel_points/custom_rewards".
        Params:
            Optional dictionary, list of tuples, or bytes, to append to the URL of the request
            as its query. If a dictionary or sequence of tuples `(key, value)` is provided, the
            contents will be form-encoded. See: https://docs.python-requests.org/en/latest/api
        Callback:
            The function to be invoked upon completion of the request. This function must accept
            two arguments - An `int` representing the status code of the response, and a `dict`
            containing the content of the response, if any.
    """
    Request("GET", Path, Params, None, Callback=Callback)

def Patch(Path: str, Params: Any = None, Data: Any = None, *, Callback: Callable[[int, Dict[str, Any]], None]) -> None:
    """
    Asynchronously send a PATCH request to the Twitch API with the user's authentication.

    The scopes required for a given Twitch API request must have been registered for with
    `TwitchLogin.RegisterMod(mod)`, with the `mod` object having the relevant
    `TwitchLogin.TwitchScope` object in its `TwitchScopes` property. The user must have then logged
    in upon being notified of their requirement to do so. Without the authorized scope, the Twitch
    API will respond to the request with an error.

    Arguments:
        Path:
            The path in the Twitch API URL to send the request. This should be the entire path
            after "/helix/"; for example, specfying "channel_points/custom_rewards" causes the
            request to be sent to "https://api.twitch.tv/helix/channel_points/custom_rewards".
        Params:
            Optional dictionary, list of tuples, or bytes, to append to the URL of the request
            as its query. If a dictionary or sequence of tuples `(key, value)` is provided, the
            contents will be form-encoded. See: https://docs.python-requests.org/en/latest/api
        Data:
            The object to send as the request of the body. A JSON-serializable dictionary is
            generally recommended for the Twitch API, but this may also be a sequence of tuples,
            bytes, or file-like object. See: https://docs.python-requests.org/en/latest/api
        Callback:
            The function to be invoked upon completion of the request. This function must accept
            two arguments - An `int` representing the status code of the response, and a `dict`
            containing the content of the response, if any.
    """
    Request("PATCH", Path, Params, Data, Callback=Callback)

def Post(Path: str, Params: Any = None, Data: Any = None, *, Callback: Callable[[int, Dict[str, Any]], None]) -> None:
    """
    Asynchronously send a POST request to the Twitch API with the user's authentication.

    The scopes required for a given Twitch API request must have been registered for with
    `TwitchLogin.RegisterMod(mod)`, with the `mod` object having the relevant
    `TwitchLogin.TwitchScope` object in its `TwitchScopes` property. The user must have then logged
    in upon being notified of their requirement to do so. Without the authorized scope, the Twitch
    API will respond to the request with an error.

    Arguments:
        Path:
            The path in the Twitch API URL to send the request. This should be the entire path
            after "/helix/"; for example, specfying "channel_points/custom_rewards" causes the
            request to be sent to "https://api.twitch.tv/helix/channel_points/custom_rewards".
        Params:
            Optional dictionary, list of tuples, or bytes, to append to the URL of the request
            as its query. If a dictionary or sequence of tuples `(key, value)` is provided, the
            contents will be form-encoded. See: https://docs.python-requests.org/en/latest/api
        Data:
            The object to send as the request of the body. A JSON-serializable dictionary is
            generally recommended for the Twitch API, but this may also be a sequence of tuples,
            bytes, or file-like object. See: https://docs.python-requests.org/en/latest/api
        Callback:
            The function to be invoked upon completion of the request. This function must accept
            two arguments - An `int` representing the status code of the response, and a `dict`
            containing the content of the response, if any.
    """
    Request("POST", Path, Params, Data, Callback=Callback)

def Put(Path: str, Params: Any = None, Data: Any = None, *, Callback: Callable[[int, Dict[str, Any]], None]) -> None:
    """
    Asynchronously send a PUT request to the Twitch API with the user's authentication.

    The scopes required for a given Twitch API request must have been registered for with
    `TwitchLogin.RegisterMod(mod)`, with the `mod` object having the relevant
    `TwitchLogin.TwitchScope` object in its `TwitchScopes` property. The user must have then logged
    in upon being notified of their requirement to do so. Without the authorized scope, the Twitch
    API will respond to the request with an error.

    Arguments:
        Path:
            The path in the Twitch API URL to send the request. This should be the entire path
            after "/helix/"; for example, specfying "channel_points/custom_rewards" causes the
            request to be sent to "https://api.twitch.tv/helix/channel_points/custom_rewards".
        Params:
            Optional dictionary, list of tuples, or bytes, to append to the URL of the request
            as its query. If a dictionary or sequence of tuples `(key, value)` is provided, the
            contents will be form-encoded. See: https://docs.python-requests.org/en/latest/api
        Data:
            The object to send as the request of the body. A JSON-serializable dictionary is
            generally recommended for the Twitch API, but this may also be a sequence of tuples,
            bytes, or file-like object. See: https://docs.python-requests.org/en/latest/api
        Callback:
            The function to be invoked upon completion of the request. This function must accept
            two arguments - An `int` representing the status code of the response, and a `dict`
            containing the content of the response, if any.
    """
    Request("PUT", Path, Params, Data, Callback=Callback)
