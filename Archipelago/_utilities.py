import unrealsdk # type: ignore

import io
import logging
import os
import sys

from collections import deque
from typing import Callable, Deque, Optional, Tuple


# Determine the absolute path to our directory from that of the currently executing file. From that,
# also determine the path to the directory with our bundled libraries.
_mod_dir: str = os.path.dirname(os.path.abspath(__file__))
_lib_dir: str = os.path.join(_mod_dir, "lib")


# Create a logger object to handle logging throughout our module. It should not propogate to the
# global logger. The base name to be inserted in logging messages is "TwitchLogin", which we may
# append to by creating child loggers with getChild().
log: logging.Logger = logging.getLogger("TwitchLogin")
log.propagate = False

# Module-wide logging level may be assigned here:
log.setLevel(logging.INFO)

# Log messages should begin with the logger name, followed by the time, including seconds to three
# decimal places.
_formatter: logging.Formatter = logging.Formatter(
    fmt = "[{name}] {asctime}.{msecs:03.0f}: {message}",
    datefmt = "%H:%M:%S",
    style = "{",
)


# To log to the game console, create a generic log handler, and assign it a simple function as its
# `emit` method. This saves us from having to make an entire subclass of `logging.Handler`.
_console_handler: logging.Handler = logging.Handler()
_console_handler.emit = lambda record: unrealsdk.Log(_console_handler.format(record))
_console_handler.setFormatter(_formatter)
# Only messages of ERROR or higher should appear in the console.
_console_handler.setLevel(logging.ERROR)
log.addHandler(_console_handler)


# Open a handle to our logging file. This should be created new each time we run.
_log_file: io.TextIOWrapper = open(os.path.join(_mod_dir, "logging.log"), "w")

# Add a handler to our logger that passes all messages to our log file.
_file_handler: logging.Handler = logging.StreamHandler(_log_file)
_file_handler.setFormatter(_formatter)
_file_handler.setLevel(logging.DEBUG)
log.addHandler(_file_handler)


class ImportContext():
    """
    A context manager that provides an environment fit to import our bundled libraries. For the
    lifetime of the context, our module search path is included in `sys.path`, and this program's
    stdio handles will be assigned sane values.
    """
    stdio: Tuple[Optional[io.TextIOBase], Optional[io.TextIOBase], Optional[io.TextIOBase]]
    path_had_lib_dir: bool

    def __enter__(self) -> None:
        # Record whether our bundled libraries directory is already in Python's path list. If it
        # isn't, add it now.
        self.path_had_lib_dir = _lib_dir in sys.path
        if not self.path_had_lib_dir:
            sys.path.append(_lib_dir)

        # Various modules related to file-like objects (such as sockets) will fail to import if
        # stdio handles don't exist, so we will be temporarily opening handles for each. First
        # record their current values to revert afterwards.
        self.stdio = (sys.stdin, sys.stdout, sys.stderr)

        # Open the nul file and assign it as stdin. Assign the log file as stdout and stderr.
        sys.stdin, sys.stdout, sys.stderr = open("nul", "r"), _log_file, _log_file

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Upon release of this context manager, close the handle we opened for the nul file, and
        # revert the program's stdio handles.
        sys.stdin.close()
        sys.stdin, sys.stdout, sys.stderr = self.stdio

        # If Python's path did not already contain our libraries directory, remove it again now.
        if not self.path_had_lib_dir:
            sys.path.remove(_lib_dir)


ImportContext = ImportContext()


MainThreadQueue: Deque[Callable[[], None]] = deque()
"""
A queue of callables which are automatically dequeued and invoked on the main thread as they are
appended.
"""

def _tick(caller: unrealsdk.UObject, function: unrealsdk.UFunction, params: unrealsdk.FStruct) -> bool:
    """
    Invoked repeatedly on the main thread. Each invocation, we dequeue and invoke each callback that
    has been enqueued for us to invoke on the main thread.
    """
    while len(MainThreadQueue) != 0:
        MainThreadQueue.popleft()()
    return True

unrealsdk.RunHook("WillowGame.WillowGameViewportClient.Tick", "TwitchLogin", _tick)
