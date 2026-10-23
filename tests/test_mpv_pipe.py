"""Execute the actual ctypes branch with deterministic Win32 stand-ins."""
import ctypes
from ctypes import wintypes
from types import SimpleNamespace

from mpv_subtitle_adapter import _Transport


class Function:
    def __init__(self, call):
        self.call = call

    def __call__(self, *args):
        return self.call(*args)


def test_one_available_byte_and_pointer_sized_handle_prototypes(monkeypatch):
    requested = []
    handle = (1 << 40) + 123

    def peek(h, buf, size, read, available, left):
        assert h == handle
        ctypes.cast(available, ctypes.POINTER(wintypes.DWORD))[0] = 1
        return 1

    def read_file(h, buf, size, count, overlapped):
        assert h == handle
        requested.append(size)
        ctypes.memmove(buf, b"\n", 1)
        ctypes.cast(count, ctypes.POINTER(wintypes.DWORD))[0] = 1
        return 1

    kernel = SimpleNamespace(
        CreateFileW=Function(lambda *args: handle),
        PeekNamedPipe=Function(peek), ReadFile=Function(read_file),
        WriteFile=Function(lambda *args: 1), CloseHandle=Function(lambda h: 1))
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=kernel), raising=False)
    transport = _Transport("test-pipe")
    assert transport._connect_pipe()
    assert transport._read_pipe_chunk() == b"\n"
    assert requested == [1]
    for name in ("ReadFile", "WriteFile", "PeekNamedPipe", "CloseHandle"):
        function = getattr(kernel, name)
        assert function.argtypes[0] is wintypes.HANDLE
        assert function.restype is wintypes.BOOL


def test_no_data_is_not_a_disconnection():
    def peek(h, buf, size, read, available, left):
        ctypes.cast(available, ctypes.POINTER(wintypes.DWORD))[0] = 0
        return 1
    kernel = SimpleNamespace(PeekNamedPipe=Function(peek))
    transport = _Transport("test-pipe")
    transport._pipe = (SimpleNamespace(windll=SimpleNamespace(kernel32=kernel)), 123)
    transport._stop.set()
    assert transport._read_pipe_chunk() == b""


def test_native_windows_pipe_round_trip():
    """Exercise real HANDLE widths and byte counts on the Windows CI runner."""
    import sys
    import threading
    import time
    import uuid
    import pytest

    if sys.platform != "win32":
        pytest.skip("requires the Windows named-pipe API")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, wintypes.LPVOID]
    kernel.CreateNamedPipeW.restype = wintypes.HANDLE
    kernel.ConnectNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
    kernel.ConnectNamedPipe.restype = wintypes.BOOL
    kernel.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID,
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    kernel.ReadFile.restype = wintypes.BOOL
    kernel.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID,
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    kernel.WriteFile.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    endpoint = r"\\.\pipe\iptv-subtitle-test-" + uuid.uuid4().hex
    handle = kernel.CreateNamedPipeW(endpoint, 3, 0, 1, 4096, 4096, 0, None)
    assert handle and handle != wintypes.HANDLE(-1).value
    result = {}

    def serve():
        try:
            ok = kernel.ConnectNamedPipe(handle, None)
            if not ok and ctypes.get_last_error() != 535:  # ERROR_PIPE_CONNECTED
                result["error"] = ctypes.get_last_error()
                return
            count = wintypes.DWORD()
            if not kernel.WriteFile(handle, b"\n", 1, ctypes.byref(count), None):
                result["error"] = ctypes.get_last_error()
                return
            buf = ctypes.create_string_buffer(5)
            ok = kernel.ReadFile(handle, buf, 5, ctypes.byref(count), None)
            result["request"] = buf.raw[:count.value] if ok else None
        finally:
            kernel.CloseHandle(handle)

    server = threading.Thread(target=serve, daemon=True)
    server.start()
    transport = _Transport(endpoint)
    try:
        assert transport.connect()
        assert transport.read_line(time.monotonic() + 2) == b""
        assert transport.write_line(b"ping\n")
        server.join(2)
        assert not server.is_alive()
        assert result == {"request": b"ping\n"}
    finally:
        transport.close()
        server.join(1)
