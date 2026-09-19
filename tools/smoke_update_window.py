"""Drive update_helper.ps1's status window the way a real update does.

pytest cannot see this: the window is a WinForms form in a separate Windows
PowerShell process, and what matters about it is exactly what pytest has no
view of - that it appears, that its title follows every step (the title is
what NVDA reads, because nothing in the window takes focus), that it refuses
to close while the update runs, and that its Cancel button reaches the app.

Run it after touching update_helper.ps1 or the session protocol in updater.py:

    python tools/smoke_update_window.py

It never installs anything: the install it asks for has no installer, which is
the path a failed install takes. Everything it starts besides the status
window itself is windowless, so the only thing that appears on screen - and
the only thing that takes focus - is the window under test.
"""
import ctypes
import ctypes.wintypes as wintypes
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import updater  # noqa: E402

TITLE_PREFIX = "Accessible IPTV Client - "
WM_CLOSE = 0x0010
BM_CLICK = 0x00F5

user32 = ctypes.windll.user32
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def _window_text(hwnd) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def _windows_of(pid: int):
    found = []

    def callback(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return found


def _status_window(pid: int):
    for hwnd in _windows_of(pid):
        if _window_text(hwnd).startswith(TITLE_PREFIX):
            return hwnd
    return None


def _child_buttons(hwnd):
    buttons = []

    def callback(child, _lparam):
        name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(child, name, 256)
        # WinForms classes are "WindowsForms10.BUTTON.app.0.…", not "Button".
        if "BUTTON" in name.value.upper():
            buttons.append((child, _window_text(child)))
        return True

    user32.EnumChildWindows(hwnd, EnumWindowsProc(callback), 0)
    return buttons


def _wait(predicate, seconds=20.0, what=""):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.15)
    raise AssertionError("timed out waiting for {what}".format(what=what or predicate))


def _check(label: str, condition, detail=None):
    if condition:
        print("PASS  " + label)
        return
    print("FAIL  " + label + (" - " + str(detail) if detail else ""))
    raise SystemExit(1)


def _install_handover(session_root: str) -> None:
    """The step the window used to disappear at: download done, install starts.

    The app writes the install instruction and exits; the helper has to keep
    the same window, move it on to "Preparing the update", notice the app is
    gone, and - when the install itself fails - record why and bring the old
    app back. The installer is missing on purpose, so nothing is installed.
    """
    session = os.path.join(session_root, "handover")
    os.makedirs(session)
    shutil.copy2(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "update_helper.ps1"),
                 os.path.join(session, "update_helper.ps1"))
    install_dir = os.path.join(session_root, "app")
    os.makedirs(install_dir)
    # Something that really starts and stays up, standing in for the app. It
    # has to be windowless: the helper starts it the way it starts the real
    # app, and a console stand-in put a window on screen and took the focus
    # away from whoever was running this. wscript.exe running a script that
    # only sleeps shows nothing at all.
    fake_app = os.path.join(install_dir, "FakeApp.exe")
    shutil.copy2(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                              "System32", "wscript.exe"), fake_app)
    sleeper = os.path.join(install_dir, "sleep.vbs")
    with open(sleeper, "w", encoding="ascii") as handle:
        handle.write("WScript.Sleep 20000\n")
    ready = os.path.join(session, "update_window_ready")
    quit_flag = os.path.join(session, "quit").replace("\\", "/")

    # A stand-in app that exits on cue, the way the real one hands over.
    parent = subprocess.Popen(
        [updater.windows_powershell_path(), "-NoProfile", "-Command",
         "while (-not (Test-Path '{flag}')) {{ Start-Sleep -Milliseconds 100 }}".format(
             flag=quit_flag)],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    updater.write_update_status(session, "Downloading update...", 90.0, True)
    helper = updater.launch_update_helper(os.path.join(session, "update_helper.ps1"), [
        "-ParentPid", str(parent.pid),
        "-SessionDir", session,
        "-ReadyFile", ready,
        "-Language", "en",
    ])
    try:
        _wait(lambda: os.path.exists(ready), 40, "the helper to report its window")
        hwnd = _wait(lambda: _status_window(helper.pid), 20, "the status window")

        updater.write_update_command(
            session, "install", parent_pid=parent.pid, install_dir=install_dir,
            exe_name="FakeApp.exe", installer=os.path.join(session, "no-installer.exe"),
            version="9.9.9", restart_args='"{script}"'.format(script=sleeper))
        _wait(lambda: "Preparing the update" in _window_text(hwnd), 20,
              "the window to move on to the install")
        _check("the same window carries on into the install", True)

        # The app exits: the window must still be there, and still be ours.
        open(os.path.join(session, "quit"), "w").close()
        _wait(lambda: parent.poll() is not None, 20, "the stand-in app to exit")
        time.sleep(2.0)
        _check("the window survives the app closing",
               _status_window(helper.pid) == hwnd, "window gone")

        _wait(lambda: helper.poll() is not None, 120, "the helper to finish")
        result = updater.read_update_result() or {}
        _check("a failed install is recorded for the app to report",
               result.get("status") == "failed", result)
        _check("the old app is started again", helper.returncode == 1, helper.returncode)
    finally:
        for process in (helper, parent):
            if process.poll() is None:
                process.kill()
        updater.clear_update_result()


def main() -> int:
    if os.name != "nt":
        print("SKIP: the update status window is Windows only.")
        return 0
    source = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "update_helper.ps1")
    session = tempfile.mkdtemp(prefix=updater.UPDATE_TEMP_PREFIX)
    helper = os.path.join(session, "update_helper.ps1")
    shutil.copy2(source, helper)
    ready = os.path.join(session, "update_window_ready")

    updater.write_update_status(session, "Starting the update...", None, True)
    process = updater.launch_update_helper(helper, [
        "-ParentPid", str(os.getpid()),
        "-SessionDir", session,
        "-ReadyFile", ready,
        "-Language", "en",
    ])
    try:
        _wait(lambda: os.path.exists(ready), 40, "the helper to report its window")
        hwnd = _wait(lambda: _status_window(process.pid), 20, "the status window")
        _check("the window is on screen before the download starts",
               _window_text(hwnd).endswith("Starting the update..."), _window_text(hwnd))

        updater.write_update_status(session, "Downloading update...", 42.0, True)
        _wait(lambda: _window_text(hwnd).endswith("Downloading update..."), 10,
              "the title to follow the download")
        _check("the title follows each step", True, _window_text(hwnd))

        buttons = _wait(lambda: [b for b in _child_buttons(hwnd)
                                 if user32.IsWindowVisible(b[0])], 10, "the Cancel button")
        _check("Cancel is offered while downloading",
               any(text == "Cancel" for _hwnd, text in buttons), buttons)

        # The window must survive everything but its own script closing it.
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        time.sleep(1.5)
        _check("Alt+F4 / the close button cannot take the window away",
               _status_window(process.pid) == hwnd, "window gone")

        cancel_button = [b for b, text in buttons if text == "Cancel"][0]
        user32.SendMessageW(cancel_button, BM_CLICK, 0, 0)
        _wait(lambda: updater.update_cancel_requested(session), 10,
              "Cancel to reach the app")
        _check("Cancel reaches the app", True)

        # What the app writes when the download was cancelled or failed.
        updater.write_update_command(session, "abort", message="Update cancelled.")
        _wait(lambda: _window_text(hwnd).endswith("Update cancelled."), 15,
              "the window to report the cancellation")
        _check("the reason is shown in the same window", True, _window_text(hwnd))

        close_button = _wait(
            lambda: [b for b, text in _child_buttons(hwnd)
                     if text == "Close" and user32.IsWindowVisible(b)], 10, "the Close button")
        user32.SendMessageW(close_button[0], BM_CLICK, 0, 0)
        _wait(lambda: process.poll() is not None, 20, "the helper to exit")
        _check("Close ends the update", process.returncode == 4, process.returncode)
        _check("nothing is left on screen", _status_window(process.pid) is None)
    finally:
        if process.poll() is None:
            process.kill()

    handover_root = tempfile.mkdtemp(prefix=updater.UPDATE_TEMP_PREFIX)
    try:
        _install_handover(handover_root)
    finally:
        shutil.rmtree(handover_root, ignore_errors=True)
        shutil.rmtree(session, ignore_errors=True)
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
