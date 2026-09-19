"""Keep one copy of the app running per user.

Two copies share one config directory, one EPG database, one log and one
schedule of recordings, and nothing coordinated them. Both schedulers started
the same scheduled recording seconds apart; on a one-stream provider the second
connection was refused (ffmpeg exit 3436169992, HTTP 403) and the provider then
dropped the first one as well, so the recording was lost entirely. Settings
saves collided on ``iptvclient.conf.tmp`` and EPG imports queued behind each
other's lock. A second copy is easy to start by accident: the update's status
window went quiet, the user opened the app themselves, and the updater then
started it again.

A second launch therefore hands over instead of running: it asks the running
copy to come to the front (``request_show``) and exits once that copy has
taken the request. The running copy polls for the request with a timer.

Stdlib only and wx-free, so it runs before ``wx.App`` exists and is testable.
"""

import logging
import os
import sys
import time
from typing import Optional

SHOW_REQUEST_FILE = "show_request"
# The exit code of a launch that handed over to the running copy. The update
# helper treats it as a successful restart rather than a crash at startup.
HANDED_OVER_EXIT_CODE = 12

LOG = logging.getLogger(__name__)

_MUTEX_NAME = "Local\\AccessibleIPTVClient-single-instance"
_ERROR_ALREADY_EXISTS = 183


class InstanceGuard:
    """Held for the life of the process; the OS releases it if the process dies."""

    def __init__(self, handle=None, lock_file=None):
        self._handle = handle
        self._lock_file = lock_file

    def release(self) -> None:
        if self._handle is not None and sys.platform == "win32":
            import ctypes

            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None
        if self._lock_file is not None:
            try:
                self._lock_file.close()
            except OSError:
                LOG.debug("InstanceGuard.release: close failed", exc_info=True)
            self._lock_file = None


def acquire(config_dir: str, name: str = _MUTEX_NAME) -> Optional[InstanceGuard]:
    """The guard for this process, or None when another copy already holds it."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel32.CreateMutexW
        create.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        create.restype = wintypes.HANDLE
        handle = create(None, False, name)
        if not handle:
            # Cannot tell: run rather than refuse to start at all.
            return InstanceGuard()
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return None
        return InstanceGuard(handle=handle)
    import fcntl

    os.makedirs(config_dir, exist_ok=True)
    lock_file = open(os.path.join(config_dir, "instance.lock"), "a+")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_file.close()
        return None
    return InstanceGuard(lock_file=lock_file)


def _request_path(config_dir: str) -> str:
    return os.path.join(config_dir or "", SHOW_REQUEST_FILE)


def request_show(config_dir: str) -> None:
    """Ask the running copy to come to the front."""
    os.makedirs(config_dir, exist_ok=True)
    with open(_request_path(config_dir), "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    if sys.platform == "win32":
        # We were just launched, so we hold the foreground; without handing it
        # on, the running copy's window could not take focus and NVDA would
        # say nothing about it.
        try:
            import ctypes

            ctypes.windll.user32.AllowSetForegroundWindow(0xFFFFFFFF)
        except Exception:
            LOG.debug("request_show: AllowSetForegroundWindow failed", exc_info=True)


def take_show_request(config_dir: str) -> bool:
    """Running copy: whether a later launch asked for the window (and consume it)."""
    try:
        os.remove(_request_path(config_dir))
        return True
    except FileNotFoundError:
        return False
    except OSError:
        LOG.debug("take_show_request: could not consume the request", exc_info=True)
        return False


def clear_show_request(config_dir: str) -> None:
    take_show_request(config_dir)


def hand_over(config_dir: str, timeout: float = 15.0, poll: float = 0.25,
              name: str = _MUTEX_NAME):
    """Second launch: pass the request on and wait for the answer.

    Returns ``"shown"`` once the running copy took the request, an
    ``InstanceGuard`` when that copy exited meanwhile (it was closing, so this
    launch runs after all), or ``"unresponsive"`` at the deadline.
    """
    request_show(config_dir)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not os.path.exists(_request_path(config_dir)):
            return "shown"
        guard = acquire(config_dir, name)
        if guard is not None:
            clear_show_request(config_dir)
            return guard
        time.sleep(poll)
    clear_show_request(config_dir)
    return "unresponsive"
