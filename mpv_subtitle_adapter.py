"""Application-owned MPV session adapter for subtitle text (issue #37).

Boundaries, as agreed on the issue:
- Launch or adopt only an explicitly identified MPV instance: we spawn MPV
  ourselves with a per-session IPC endpoint and keep the process handle. We
  never attach to the fixed shared endpoint, which could belong to another
  instance or an earlier run.
- One persistent read/write connection with JSON IPC request IDs. A private
  Lua helper combines property changes into complete current-cue snapshots.
- Missing, empty, null and disconnected are treated as different states.
- Cues are keyed on generation, track, start time and text; the queue is
  cleared on stop, source switch and track change.
- If the adapter drops, MPV keeps playing and the app reports speech as
  unavailable. Adapter failure must never interrupt playback.

Only text subtitles with real words are surfaced: MPV documents ``sub-text``
as empty for bitmap subtitles, so those stay honestly unreported.
"""

import json
import logging
import os
import math
import sys
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from typing import Callable, Dict, Optional
from mpv_subtitle_script import SCRIPT
from subtitle_pipeline import SubtitleSnapshot

LOG = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"

# Timeouts / pacing.
CONNECT_TIMEOUT_S = 1.5
CONNECT_POLL_S = 0.1
READ_POLL_S = 0.05
REQUEST_TIMEOUT_S = 1.0
LAUNCH_CONNECT_TIMEOUT_S = 6.0
VERSION_TIMEOUT_S = 5.0

def _session_endpoint() -> str:
    """A per-session IPC endpoint that cannot collide with other instances."""
    token = uuid.uuid4().hex[:8]
    if _IS_WINDOWS:
        return r"\\.\pipe\iptvclient-mpv-" + token
    return os.path.join(tempfile.gettempdir(), f"iptvclient-mpv-{token}.sock")


class _Transport:
    """Persistent read/write IPC transport. Never raises out of read/write."""

    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self._stop = threading.Event()
        self._write_lock = threading.Lock()
        self._sock = None
        self._pipe = None
        self._buffer = b""

    # -- connect ---------------------------------------------------------

    def connect(self, timeout=CONNECT_TIMEOUT_S) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self._stop.is_set():
            try:
                if _IS_WINDOWS:
                    if self._connect_pipe():
                        return True
                elif self._connect_socket():
                    return True
            except Exception:
                LOG.debug("mpv adapter: connect attempt failed", exc_info=True)
            self._stop.wait(CONNECT_POLL_S)
        return False


    def _connect_pipe(self) -> bool:
        import ctypes
        from ctypes import wintypes

        GENERIC_READ = 0x80000000
        GENERIC_WRITE = 0x40000000
        OPEN_EXISTING = 3
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
            wintypes.HANDLE,
        ]
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID,
            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
        kernel32.ReadFile.restype = wintypes.BOOL
        kernel32.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID,
            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
        kernel32.WriteFile.restype = wintypes.BOOL
        kernel32.PeekNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID,
            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
        kernel32.PeekNamedPipe.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.CreateFileW(
            self.endpoint, GENERIC_READ | GENERIC_WRITE,
            0, None, OPEN_EXISTING, 0, None,
        )
        if not handle or handle == wintypes.HANDLE(-1).value:
            return False
        self._pipe = (ctypes, handle)
        return True

    def _connect_socket(self) -> bool:
        s = None
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(CONNECT_POLL_S)
            s.connect(self.endpoint)
            s.settimeout(CONNECT_POLL_S)
            self._sock = s
            return True
        except OSError:
            if s is not None:
                s.close()
            return False

    # -- write ------------------------------------------------------------

    def write_line(self, line: bytes) -> bool:
        try:
            with self._write_lock:
                if self._stop.is_set():
                    return False
                if _IS_WINDOWS:
                    return self._write_pipe(line)
                if self._sock is None:
                    return False
                self._sock.sendall(line)
                return True
        except Exception:
            LOG.debug("mpv adapter: write failed", exc_info=True)
            return False


    def _write_pipe(self, line: bytes) -> bool:
        ctypes, handle = self._pipe
        from ctypes import wintypes

        written = wintypes.DWORD(0)
        ok = ctypes.windll.kernel32.WriteFile(
            handle, line, len(line), ctypes.byref(written), None)
        return bool(ok and written.value == len(line))

    # -- read --------------------------------------------------------------

    def read_line(self, deadline: Optional[float] = None) -> Optional[bytes]:
        """One newline-terminated message, or None on stop/error/timeout.

        If deadline (monotonic timestamp) is given, returns None when it
        passes, instead of looping forever on a silent peer.
        """
        try:
            while not self._stop.is_set():
                if b"\n" in self._buffer:
                    line, self._buffer = self._buffer.split(b"\n", 1)
                    return line
                if deadline is not None and time.monotonic() >= deadline:
                    return None
                chunk = self._read_chunk()
                if chunk is None:
                    return None
                if chunk:
                    self._buffer += chunk
                    if len(self._buffer) > 4 * 1024 * 1024:
                        LOG.warning("mpv adapter: oversized IPC message")
                        return None
            return None
        except Exception:
            LOG.debug("mpv adapter: read failed", exc_info=True)
            return None

    def _read_chunk(self):
        if _IS_WINDOWS:
            return self._read_pipe_chunk()
        return self._read_socket_chunk()

    def _read_socket_chunk(self):
        import select

        if self._sock is None:
            return None
        ready, _, _ = select.select([self._sock], [], [], READ_POLL_S)
        if not ready:
            return b""
        try:
            data = self._sock.recv(65536)
        except OSError:
            return None
        return data if data else None  # None: peer closed


    def _read_pipe_chunk(self):
        import ctypes
        from ctypes import wintypes

        pipe = self._pipe
        if pipe is None:
            return None
        ctypes_mod, handle = pipe
        kernel32 = ctypes_mod.windll.kernel32
        avail = wintypes.DWORD(0)
        if not kernel32.PeekNamedPipe(
                handle, None, 0, None, ctypes.byref(avail), None):
            return None
        if avail.value == 0:
            self._stop.wait(READ_POLL_S)
            return b""
        buf = ctypes.create_string_buffer(min(avail.value, 65536))
        read = wintypes.DWORD(0)
        ok = kernel32.ReadFile(
            handle, buf, len(buf), ctypes.byref(read), None)
        if not ok or read.value == 0:
            return None
        return buf.raw[:read.value]

    # -- close ---------------------------------------------------------------

    def close(self) -> None:
        self._stop.set()
        with self._write_lock:
            if _IS_WINDOWS and self._pipe:
                try:
                    ctypes_mod, handle = self._pipe
                    ctypes_mod.windll.kernel32.CloseHandle(handle)
                except Exception:
                    LOG.debug("mpv adapter: CloseHandle failed", exc_info=True)
                self._pipe = None
            if self._sock is not None:
                try:
                    self._sock.close()
                except Exception:
                    LOG.debug("mpv adapter: socket close failed", exc_info=True)
                self._sock = None


class MpvSubtitleAdapter:
    """A private MPV process with asynchronous, cancellable subtitle setup.

    launch() returns as soon as the process starts. IPC failure leaves that
    process playing, reports unavailable speech, and never starts a second
    player. Only the reader thread consumes the transport.
    """

    def __init__(self, manager, on_state_change: Optional[Callable[[str], None]] = None):
        self._manager = manager
        self._on_state_change = on_state_change
        self._transport = None
        self._process = None
        self._reader = None
        self._initializer = None
        self._directory = None
        self._stop = threading.Event()
        self._snapshot_ready = threading.Event()
        self._state_lock = threading.RLock()
        self._close_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: Dict[int, dict] = {}
        self._request_id = 0
        self._generation = 0
        self._snapshot_key = None
        self._serial = -1
        self._mpv_version = ""
        self._first_cue_sent = False
        self._bitmap_reported = False
        self.available = False

    @classmethod
    def launch_playback_only(cls, mpv_exe, url, manager, on_state_change=None):
        """Keep playback owned even if a private helper cannot be created."""
        self = cls(manager, on_state_change)
        try:
            self._process = subprocess.Popen([
                mpv_exe, "--force-window=yes", "--idle=yes", "--no-terminal", "--", url])
        except OSError:
            LOG.warning("mpv playback-only launch failed", exc_info=True)
            return None
        for capability in ("timed_cues", "read_current", "read_previous"):
            manager.set_capability("MPV", capability, "unavailable")
        self._report("unavailable")
        return self

    @classmethod
    def launch(cls, mpv_exe, url, manager, on_state_change=None, extra_args=None):
        self = cls(manager, on_state_change)
        extra = [str(arg) for arg in (extra_args or [])]
        force_window = not any(arg.startswith("--vo=null") for arg in extra)
        try:
            self._directory = tempfile.TemporaryDirectory(prefix="iptv-mpv-")
            script = os.path.join(self._directory.name, "iptv_subtitles.lua")
            with open(script, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(SCRIPT)
            endpoint = (_session_endpoint() if _IS_WINDOWS else
                        os.path.join(self._directory.name, "ipc.sock"))
            self._transport = _Transport(endpoint)
            self._process = subprocess.Popen([
                mpv_exe, f"--input-ipc-server={endpoint}",
                f"--script={script}",
                *(["--force-window=yes"] if force_window else []), "--idle=yes",
                "--no-terminal", *extra, "--", url,
            ])
        except Exception:
            LOG.warning("mpv adapter: process launch failed", exc_info=True)
            self.close()
            return None
        self._initializer = threading.Thread(
            target=self._initialize, name="mpv-subtitle-setup", daemon=True)
        self._initializer.start()
        return self

    def _initialize(self):
        try:
            if not self._transport.connect(timeout=LAUNCH_CONNECT_TIMEOUT_S) or self._stop.is_set():
                return
            self._reader = threading.Thread(
                target=self._read_loop, name="mpv-ipc", daemon=True)
            self._reader.start()
            # Version is advisory, never a gate for subtitle readiness. The
            # same single reader handles this request and the helper handshake.
            threading.Thread(target=self._verify_version, name="mpv-version", daemon=True).start()
            response = self._request(["script-message", "iptvclient-subtitle-request"])
            if not response or response.get("error") != "success":
                return
            # A command acknowledgement alone does not prove the script runs.
            self._snapshot_ready.wait(REQUEST_TIMEOUT_S)
            with self._state_lock:
                if self._stop.is_set() or self._serial < 0:
                    return
                self.available = True
                self._report("available")
        except Exception:
            LOG.exception("mpv subtitle initialization failed")
        finally:
            if not self.available:
                if not self._stop.is_set():
                    self._on_disconnect()
                self.close(terminate=False)

    def _verify_version(self):
        response = self._request(["get_property", "mpv-version"], timeout=VERSION_TIMEOUT_S)
        if not response or response.get("error") != "success":
            return False
        self._mpv_version = str(response.get("data") or "")
        return True

    def _send(self, message):
        transport = self._transport
        if transport is None or self._stop.is_set():
            return False
        try:
            line = (json.dumps(message) + "\n").encode("utf-8")
        except (TypeError, ValueError):
            return False
        return transport.write_line(line)

    def _request(self, command, timeout=REQUEST_TIMEOUT_S):
        # IDs and pending entries are installed atomically before writing, so
        # even an immediate reply is matched. Cancellation wakes every waiter.
        with self._pending_lock:
            if self._stop.is_set():
                return None
            self._request_id += 1
            rid = self._request_id
            entry = {"event": threading.Event(), "response": None, "cancelled": False}
            self._pending[rid] = entry
        try:
            if not self._send({"command": command, "request_id": rid}):
                return None
            received = entry["event"].wait(max(0, timeout))
            with self._pending_lock:
                if not received or self._stop.is_set() or entry["cancelled"]:
                    return None
                return entry["response"]
        finally:
            with self._pending_lock:
                self._pending.pop(rid, None)

    def _read_loop(self):
        transport = self._transport
        try:
            while not self._stop.is_set():
                line = transport.read_line()
                if line is None:
                    break
                if line.strip():
                    self._dispatch(line)
        except Exception:
            LOG.debug("mpv reader ended", exc_info=True)
        finally:
            self._on_disconnect()
            transport.close()

    def _dispatch(self, line):
        try:
            message = json.loads(line.decode("utf-8", "replace"))
        except ValueError:
            return
        if not isinstance(message, dict):
            return
        with self._state_lock:
            if self._stop.is_set():
                return
            rid = message.get("request_id")
            if isinstance(rid, int) and not isinstance(rid, bool):
                with self._pending_lock:
                    entry = self._pending.get(rid)
                    if entry is not None and not entry["cancelled"]:
                        entry["response"] = message
                        entry["event"].set()
                return
            if message.get("event") != "client-message":
                return
            args = message.get("args")
            if not isinstance(args, list) or len(args) != 2:
                return
            if args[0] != "iptvclient-subtitle-snapshot" or not isinstance(args[1], str):
                return
            try:
                snapshot = json.loads(args[1])
            except ValueError:
                return
            self._accept_snapshot(snapshot)

    @staticmethod
    def _timing_ms(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        # Keep conversion finite and within the integer precision of MPV's
        # JSON clock, including when a malformed peer sends an enormous int.
        if abs(value) > 9_007_199_254_740:
            return None
        return round(value * 1000) if math.isfinite(value) else None

    def _accept_snapshot(self, snapshot):
        if (not isinstance(snapshot, dict) or type(snapshot.get("protocol")) is not int
                or snapshot["protocol"] != 1):
            return
        serial, epoch = snapshot.get("serial"), snapshot.get("epoch")
        if (type(serial) is not int or type(epoch) is not int
                or serial < 1 or serial <= self._serial or epoch < 0
                or not isinstance(snapshot.get("text"), str)
                or not isinstance(snapshot.get("track"), str)
                or type(snapshot.get("paused")) is not bool
                or type(snapshot.get("active")) is not bool):
            return
        self._serial = serial
        self._snapshot_ready.set()
        key = (epoch, snapshot["track"])
        if key != self._snapshot_key:
            self._snapshot_key = key
            self._generation += 1
            self._first_cue_sent = False
            self._bitmap_reported = False
            for capability in ("timed_cues", "read_current", "read_previous"):
                self._manager.set_capability("MPV", capability, "unverified")
        text = snapshot["text"] if snapshot["active"] else ""
        if snapshot.get("image") is True:
            text = ""
            for capability in ("timed_cues", "read_current", "read_previous"):
                self._manager.set_capability("MPV", capability, "unavailable")
            if not self._bitmap_reported:
                self._bitmap_reported = True
                self._report("bitmap")
        start = self._timing_ms(snapshot.get("start"))
        end = self._timing_ms(snapshot.get("finish"))
        if start is not None and end is not None and end <= start:
            end = None
        if text.strip() and not self._first_cue_sent:
            self._first_cue_sent = True
            for capability in ("timed_cues", "read_current", "read_previous"):
                self._manager.set_capability("MPV", capability, "available")
            self._report("first_cue")
        # Queue status before the cue: a screen-reader status spoken afterward
        # could interrupt the very first subtitle it is meant to introduce.
        self._manager.on_snapshot(SubtitleSnapshot(
            text=text, start_ms=start, end_ms=end, source="mpv-ipc",
            track=snapshot["track"], generation=self._generation,
            sequence=serial, paused=snapshot["paused"], active=snapshot["active"],
            text_supported=snapshot.get("image") is not True,
        ))

    def _on_disconnect(self):
        with self._state_lock:
            if self._stop.is_set():
                return
            self.cancel()
            self._manager.clear()
            for capability in ("timed_cues", "read_current", "read_previous"):
                self._manager.set_capability("MPV", capability, "unavailable")
            self._report("unavailable")

    def _report(self, state):
        if self._on_state_change:
            try:
                self._on_state_change(state)
            except Exception:
                LOG.exception("mpv subtitle state callback failed")

    def cancel(self):
        """Immediate logical cancellation; no OS I/O or joins."""
        with self._state_lock:
            self._stop.set()
            self.available = False
            self._snapshot_ready.set()
            if self._transport:
                self._transport._stop.set()
            with self._pending_lock:
                for entry in self._pending.values():
                    entry["cancelled"] = True
                    entry["event"].set()

    def close(self, terminate=True):
        """Detach speech, optionally terminating only our own MPV process.

        Call on a worker: transport closure and bounded joins may wait.
        Initialization/disconnect failures always use terminate=False.
        """
        self.cancel()
        if terminate:
            # Stop the old stream before waiting for reader/setup retirement.
            # close itself runs on a worker, so process waits never block wx.
            self._shutdown_process()
        # Do not hold this lock across joins: the initializer may be cleaning
        # up after a failure at the same time as the session owner.
        with self._close_lock:
            transport, self._transport = self._transport, None
        if transport:
            transport.close()
        for thread in (self._reader, self._initializer):
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=1.0)
        with self._close_lock:
            directory, self._directory = self._directory, None
        if directory:
            try:
                directory.cleanup()
            except OSError:
                LOG.debug("mpv session directory cleanup failed", exc_info=True)

    def _shutdown_process(self):
        with self._close_lock:
            proc, self._process = self._process, None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=1)
        except Exception:
            LOG.debug("mpv process shutdown failed", exc_info=True)
