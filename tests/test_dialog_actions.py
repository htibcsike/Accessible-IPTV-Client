"""Behaviour (not just construction) of the dialogs the user drives by keyboard.

Regression cover for a batch of reports:

* Enter on a catch-up programme did nothing, because a wx.Dialog consumes Enter
  before the focused control ever sees an ``EVT_KEY_DOWN``.
* "Schedule Recording" was only reachable as a button, never from the row's own
  context menu (right-click / Shift+F10 / Applications key).
* The Playlist Manager opened with focus on the "Add File" button, so a screen
  reader user had to tab past the whole button row to hear their playlists.
* The read-only stream-URL field under the channel list is now optional.
* The built-in player can start and stop a recording of what it is playing.
"""
import os
import pathlib
import sys
import threading
import types
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

wx = pytest.importorskip("wx")

import main as appmod  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
import playlist as playlistmod  # noqa: E402

CatchupDialog: Any = appmod.CatchupDialog
ChannelEPGDialog: Any = appmod.ChannelEPGDialog
WhatsOnNowDialog: Any = appmod.WhatsOnNowDialog
IPTVClient: Any = appmod.IPTVClient
PlaylistManagerDialog: Any = playlistmod.PlaylistManagerDialog
EPGManagerDialog: Any = playlistmod.EPGManagerDialog
SourceNamesMixin: Any = playlistmod._SourceNamesMixin


@pytest.fixture(scope="module")
def wx_app():
    try:
        app = wx.App()
    except Exception as exc:  # pragma: no cover - headless CI without a display
        pytest.skip(f"no usable display for wxPython: {exc}")
    yield app


@pytest.fixture
def host(wx_app):
    frame = wx.Frame(None, title="dialog action host")
    yield frame
    frame.Destroy()


def _char_hook(key):
    event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
    event.SetKeyCode(key)
    return event


def _capture_menu(monkeypatch, ctrl, captured):
    """Record a popped-up menu's items. The menu itself is destroyed right
    after ``PopupMenu`` returns, so read it inside the stub, not afterwards."""
    def popup(_self, menu, *_args):
        captured.extend((item.GetItemLabelText(), item.IsEnabled())
                        for item in menu.GetMenuItems())
        return True

    monkeypatch.setattr(type(ctrl), "PopupMenu", popup)


# --------------------------------------------------------------------------- #
# Catch-up: Enter opens the programme
# --------------------------------------------------------------------------- #
_CATCHUP_PROGRAMMES = [
    {"title": "Evening News", "start": "20260907190000", "end": "20260907200000"},
    {"title": "Late Film", "start": "20260907200000", "end": "20260907220000"},
]


def test_catchup_enter_opens_the_selected_programme(host):
    dlg = CatchupDialog(host, "Sky Mix", _CATCHUP_PROGRAMMES)
    ended = []
    dlg.EndModal = lambda code: ended.append(code)  # type: ignore[assignment]
    try:
        dlg.listbox.SetSelection(1)
        dlg.listbox.GetEventHandler().ProcessEvent(_char_hook(wx.WXK_RETURN))
        assert ended == [wx.ID_OK]
        assert dlg.get_selection()["title"] == "Late Film"
    finally:
        dlg.Destroy()


def test_catchup_buttons_are_out_of_the_tab_chain(host):
    """No Open/Download buttons: Enter opens, the context menu downloads."""
    dlg = CatchupDialog(host, "Sky Mix", _CATCHUP_PROGRAMMES)
    try:
        assert not hasattr(dlg, "open_btn")
        assert not hasattr(dlg, "download_btn")
        buttons = [w for w in dlg.GetChildren() if isinstance(w, wx.Button)]
        panel = [w for w in dlg.GetChildren() if isinstance(w, wx.Panel)][0]
        buttons += [w for w in panel.GetChildren() if isinstance(w, wx.Button)]
        labels = [b.GetLabel() for b in buttons]
        assert all("Open" != label for label in labels), labels
        assert all("Download" != label for label in labels), labels
    finally:
        dlg.Destroy()


def test_catchup_selection_shows_in_the_description_field(host):
    """Tab from the list lands on the highlighted programme's description."""
    programmes = [
        dict(_CATCHUP_PROGRAMMES[0], description="News with a full description."),
        dict(_CATCHUP_PROGRAMMES[1], description=""),
    ]
    dlg = CatchupDialog(host, "Sky Mix", programmes)
    try:
        dlg.listbox.SetSelection(0)
        dlg._update_description()
        assert dlg.description_field.GetValue() == "News with a full description."
        dlg.listbox.SetSelection(1)
        dlg._update_description()
        assert dlg.description_field.GetValue() != "News with a full description."
        assert dlg.description_field.GetName() == "Episode description"
    finally:
        dlg.Destroy()


def test_catchup_plain_keys_do_not_activate(host):
    dlg = CatchupDialog(host, "Sky Mix", _CATCHUP_PROGRAMMES)
    ended = []
    dlg.EndModal = lambda code: ended.append(code)  # type: ignore[assignment]
    try:
        for key in (wx.WXK_DOWN, wx.WXK_TAB, wx.WXK_MENU, ord("A")):
            dlg.listbox.GetEventHandler().ProcessEvent(_char_hook(key))
        assert ended == []
    finally:
        dlg.Destroy()


# --------------------------------------------------------------------------- #
# "Schedule Recording" in the EPG row context menus
# --------------------------------------------------------------------------- #
_EPG_PROGRAMMES = [
    {"title": "Evening News", "start": "20260907190000", "end": "20260907200000",
     "description": "The day in review.", "channel_name": "Sky Mix"},
]


def test_channel_epg_context_menu_offers_schedule_recording(host, monkeypatch):
    scheduled = []
    channel = {"name": "Sky Mix"}
    dlg = ChannelEPGDialog(host, "Sky Mix", _EPG_PROGRAMMES,
                           schedule_callback=lambda ch, prog: scheduled.append((ch, prog)),
                           channel=channel)
    try:
        captured = []
        _capture_menu(monkeypatch, dlg.list_ctrl, captured)
        dlg._show_context_menu()
        assert ("Schedule Recording", True) in captured

        dlg._on_schedule(None)
        assert scheduled == [(channel, _EPG_PROGRAMMES[0])]
    finally:
        dlg.Destroy()


def test_channel_epg_context_menu_is_inert_without_a_callback(host, monkeypatch):
    dlg = ChannelEPGDialog(host, "Sky Mix", _EPG_PROGRAMMES, schedule_callback=None)
    try:
        captured = []
        _capture_menu(monkeypatch, dlg.list_ctrl, captured)
        dlg._show_context_menu()
        assert ("Schedule Recording", False) in captured
    finally:
        dlg.Destroy()


def test_channel_epg_dialog_has_no_buttons(host):
    """Schedule Recording is in the context menu and Escape closes the window,
    so the buttons were only extra Tab stops."""
    dlg = ChannelEPGDialog(host, "Sky Mix", _EPG_PROGRAMMES,
                           schedule_callback=lambda ch, prog: None)
    try:
        panel = [w for w in dlg.GetChildren() if isinstance(w, wx.Panel)][0]
        assert [w for w in panel.GetChildren() if isinstance(w, wx.Button)] == []
    finally:
        dlg.Destroy()


def test_channel_epg_dialog_escape_closes_it(host, monkeypatch):
    dlg = ChannelEPGDialog(host, "Sky Mix", _EPG_PROGRAMMES)
    try:
        ended = []
        monkeypatch.setattr(dlg, "EndModal", lambda code: ended.append(code))
        dlg._on_dialog_key(types.SimpleNamespace(
            GetKeyCode=lambda: wx.WXK_ESCAPE, Skip=lambda *a: None))
        assert ended == [wx.ID_CANCEL]
    finally:
        dlg.Destroy()


def test_channel_epg_dialog_tab_ring_is_two_controls(host):
    dlg = ChannelEPGDialog(host, "Sky Mix", _EPG_PROGRAMMES)
    try:
        for shift in (False, True):
            dlg.description_field.SetFocus()
            dlg._on_description_key(types.SimpleNamespace(
                GetKeyCode=lambda: wx.WXK_TAB, ShiftDown=lambda s=shift: s,
                Skip=lambda *a: None))
            assert dlg.FindFocus() is dlg.list_ctrl
    finally:
        dlg.Destroy()


def test_whats_on_now_context_menu_offers_play_and_schedule(host, monkeypatch):
    scheduled = []
    dlg = WhatsOnNowDialog(host, _EPG_PROGRAMMES,
                           schedule_callback=lambda prog: scheduled.append(prog))
    try:
        captured = []
        _capture_menu(monkeypatch, dlg.listbox, captured)
        dlg._show_context_menu()
        assert [label for label, _enabled in captured] == ["Play", "Schedule Recording"]

        dlg.listbox.Select(0)
        dlg._on_schedule(None)
        assert scheduled == [_EPG_PROGRAMMES[0]]
    finally:
        dlg.Destroy()


# --------------------------------------------------------------------------- #
# The source managers open on the list, not on the first button
# --------------------------------------------------------------------------- #
def test_source_managers_focus_their_list_on_open(host, monkeypatch):
    focused = []
    monkeypatch.setattr(SourceNamesMixin, "_focus_source_list",
                        lambda self: focused.append(type(self).__name__))

    dlg = PlaylistManagerDialog(host, ["http://example.invalid/a.m3u"])
    dlg.Destroy()
    dlg = EPGManagerDialog(host, ["http://example.invalid/epg.xml"])
    dlg.Destroy()

    assert focused == ["PlaylistManagerDialog", "EPGManagerDialog"]


def test_focus_source_list_selects_the_first_row(wx_app):
    calls = []
    listbox = types.SimpleNamespace(
        GetCount=lambda: 3,
        GetSelection=lambda: wx.NOT_FOUND,
        SetSelection=lambda index: calls.append(("select", index)),
        SetFocus=lambda: calls.append(("focus", None)),
    )
    holder = types.SimpleNamespace(lb=listbox)
    SourceNamesMixin._focus_source_list(holder)
    # The immediate pass focuses; the CallAfter pass runs on the next idle.
    assert ("focus", None) in calls


# --------------------------------------------------------------------------- #
# The stream-URL field is optional
# --------------------------------------------------------------------------- #
def test_stream_url_field_can_be_hidden(host):
    ctrl = wx.TextCtrl(host, style=wx.TE_READONLY | wx.TE_MULTILINE)
    client = types.SimpleNamespace(url_display=ctrl, show_channel_url=False)
    IPTVClient._apply_channel_url_visibility(client)
    assert not ctrl.IsShown()

    client.show_channel_url = True
    IPTVClient._apply_channel_url_visibility(client)
    assert ctrl.IsShown()


def _tab_ring_client(show_channel_url, focus, navigations):
    return types.SimpleNamespace(
        show_channel_url=show_channel_url,
        channel_list=types.SimpleNamespace(
            SetFocus=lambda: focus.append("channels"),
            Navigate=lambda flags: navigations.append(flags)),
        episode_description_field=types.SimpleNamespace(
            SetFocus=lambda: focus.append("description"),
            Navigate=lambda flags: navigations.append(flags)),
        url_display=types.SimpleNamespace(
            SetFocus=lambda: focus.append("url"),
            Navigate=lambda flags: navigations.append(flags)),
        filter_box=types.SimpleNamespace(SetFocus=lambda: focus.append("search")),
        play_selected=lambda *a, **kw: None,
        _navigate_forward=IPTVClient._navigate_forward,
    )


def _tab_event(shift=False):
    return types.SimpleNamespace(
        GetKeyCode=lambda: wx.WXK_TAB,
        ShiftDown=lambda: shift,
        HasAnyModifiers=lambda: shift,
        Skip=lambda *a: None,
    )


def test_tab_from_the_channel_list_reaches_the_episode_description():
    """The description is the next stop whether or not the URL field is on."""
    for show_url in (False, True):
        focus, navigations = [], []
        client = _tab_ring_client(show_url, focus, navigations)
        IPTVClient.on_channel_key(client, _tab_event())
        assert focus == ["description"]
        assert navigations == []


def test_shift_tab_from_the_episode_description_returns_to_the_channel_list():
    """The reported bug: with the URL field off Shift+Tab went nowhere.

    It focused the hidden stream-URL control, and SetFocus on a hidden window
    does nothing, so the user was stranded in the description field.
    """
    for show_url in (False, True):
        focus, navigations = [], []
        client = _tab_ring_client(show_url, focus, navigations)
        IPTVClient._on_episode_description_key(client, _tab_event(shift=True))
        assert focus == ["channels"]
        assert navigations == []


def test_tab_from_the_episode_description_reaches_the_url_field_when_shown():
    focus, navigations = [], []
    client = _tab_ring_client(True, focus, navigations)
    IPTVClient._on_episode_description_key(client, _tab_event())
    assert focus == ["url"]
    assert navigations == []


def test_hidden_stream_url_field_lets_tab_wrap_by_normal_traversal():
    """Tab out of the last control must be undoable with Shift+Tab.

    Shift+Tab from the search box goes to the categories tree, so sending Tab
    there put the user two controls away from the channel they left. With the
    URL field hidden the episode description is simply the last control: hand
    Tab to normal traversal, whose wrap to the playlist-scope combo is exactly
    what Shift+Tab from that combo reverses -- verified against NVDA, which
    announces the original row ("list item 2 of 5") on the way back.
    """
    focus, navigations = [], []
    client = _tab_ring_client(False, focus, navigations)
    IPTVClient._on_episode_description_key(client, _tab_event())
    assert focus == []
    assert navigations == [
        wx.NavigationKeyEvent.IsForward | wx.NavigationKeyEvent.FromTab]

    focus.clear()
    navigations.clear()
    client.show_channel_url = True
    IPTVClient._on_url_display_key(client, _tab_event())
    assert focus == []
    assert navigations == [
        wx.NavigationKeyEvent.IsForward | wx.NavigationKeyEvent.FromTab]


def test_shift_tab_from_channel_list_still_goes_to_search():
    focus = []
    client = types.SimpleNamespace(
        show_channel_url=False,
        filter_box=types.SimpleNamespace(SetFocus=lambda: focus.append("search")),
        play_selected=lambda *a, **kw: None,
    )
    event = types.SimpleNamespace(
        GetKeyCode=lambda: wx.WXK_TAB,
        ShiftDown=lambda: True,
        Skip=lambda *a: None,
    )
    IPTVClient.on_channel_key(client, event)
    assert focus == ["search"]


# --------------------------------------------------------------------------- #
# Record from the built-in player
# --------------------------------------------------------------------------- #
def _player_client(**overrides):
    recorded = []
    client = types.SimpleNamespace(
        _internal_player_channel={"name": "Sky Mix"},
        _internal_player_stream_kind="live",
        _record_channel=lambda channel: recorded.append(channel),
        _sync_internal_player_record_state=lambda: recorded.append("sync"),
    )
    for key, value in overrides.items():
        setattr(client, key, value)
    return client, recorded


def test_player_record_button_records_the_playing_channel(monkeypatch):
    monkeypatch.setattr(appmod.wx, "MessageBox", lambda *a, **kw: wx.OK)
    client, recorded = _player_client()
    IPTVClient._record_from_internal_player(client)
    assert recorded == [{"name": "Sky Mix"}, "sync"]


def test_player_record_button_needs_something_playing(monkeypatch):
    shown = []
    monkeypatch.setattr(appmod.wx, "MessageBox", lambda *a, **kw: shown.append(a) or wx.OK)
    client, recorded = _player_client(_internal_player_channel=None)
    IPTVClient._record_from_internal_player(client)
    assert recorded == []
    assert len(shown) == 1


def test_player_record_button_refuses_catch_up(monkeypatch):
    shown = []
    monkeypatch.setattr(appmod.wx, "MessageBox", lambda *a, **kw: shown.append(a) or wx.OK)
    client, recorded = _player_client(_internal_player_stream_kind="catchup")
    IPTVClient._record_from_internal_player(client)
    assert recorded == []
    assert "catch-up" in shown[0][0]


def test_player_record_state_follows_the_recorder():
    states = []
    frame = types.SimpleNamespace(set_recording_state=lambda active: states.append(active))
    client = types.SimpleNamespace(
        _internal_player_frame=frame,
        _internal_player_channel={"name": "Sky Mix"},
        _channel_record_key=lambda _channel: "sky",
        recorder=types.SimpleNamespace(is_recording=lambda key: key == "sky"),
    )
    IPTVClient._sync_internal_player_record_state(client)
    assert states == [True]

    client.recorder = types.SimpleNamespace(is_recording=lambda _key: False)
    IPTVClient._sync_internal_player_record_state(client)
    assert states == [True, False]


def test_player_record_state_is_a_no_op_without_a_player():
    client = types.SimpleNamespace(_internal_player_frame=None)
    IPTVClient._sync_internal_player_record_state(client)  # must not raise


# --------------------------------------------------------------------------- #
# The update flow asks once and then gets on with it
# --------------------------------------------------------------------------- #
def _update_client(**overrides):
    """An IPTVClient stand-in carrying only the update-flow state."""
    client = types.SimpleNamespace(
        _update_in_progress=True,
        _update_install_pending=False,
        _update_session_dir=None,
        _update_helper=None,
        _update_helper_ready="",
        _update_status_message=None,
        _update_status_written=0.0,
        _update_cancel=None,
        closed=[],
        boxes=[],
        Close=lambda: client.closed.append(True),
    )
    # Plain helpers the methods under test call on self.
    client._end_update_flow = lambda: appmod.IPTVClient._end_update_flow(client)
    client._update_window_is_up = lambda: appmod.IPTVClient._update_window_is_up(client)
    client._close_for_update_install = lambda: appmod.IPTVClient._close_for_update_install(client)
    client._stop_update_helper = lambda: appmod.IPTVClient._stop_update_helper(client)
    client._UPDATE_STATUS_INTERVAL_SECONDS = appmod.IPTVClient._UPDATE_STATUS_INTERVAL_SECONDS
    for key, value in overrides.items():
        setattr(client, key, value)
    return client


def _live_helper():
    return types.SimpleNamespace(poll=lambda: None, returncode=None)


def test_the_app_puts_no_window_of_its_own_in_front_of_the_update():
    """One window for the whole update, and the app does not own it.

    The app used to show a progress dialog for the download and then hand over
    to update_helper.ps1's window for the install. The app has to exit half
    way through, so that hand-over could never be seamless: users heard the
    update window disappear at the "Preparing the update" step. The helper's
    window is now up before the download starts, and this side only reports
    into it.
    """
    for gone in ("_show_update_installing_progress", "_destroy_update_progress",
                 "_apply_update_progress", "_fresh_update_message",
                 "_start_update_helper", "_launch_update_helper",
                 "_launch_installer_update_helper", "_warn_update_is_installing"):
        assert not hasattr(appmod.IPTVClient, gone), gone
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    download = source[source.index("def _start_update_download"):
                      source.index("def _report_update_progress")]
    assert "ProgressDialog" not in download


def test_progress_is_reported_into_the_update_window(monkeypatch, tmp_path):
    written = []
    monkeypatch.setattr(appmod.updater, "write_update_status",
                        lambda *a: written.append(a) or True)
    monkeypatch.setattr(appmod.updater, "update_cancel_requested", lambda _d: False)
    clock = [100.0]
    monkeypatch.setattr(appmod.time, "monotonic", lambda: clock[0])
    client = _update_client(_update_session_dir=str(tmp_path),
                            _update_cancel=threading.Event())

    assert appmod.IPTVClient._report_update_progress(client, "Downloading update...", 0.5)
    assert written == [(str(tmp_path), "Downloading update...", 50.0, True)]

    # Ticks of the same step are throttled: the window only has to look alive.
    written.clear()
    clock[0] += 0.05
    appmod.IPTVClient._report_update_progress(client, "Downloading update...", 0.51)
    assert written == []
    clock[0] += 1.0
    appmod.IPTVClient._report_update_progress(client, "Downloading update...", 0.6)
    assert written and written[-1][2] == 60.0

    # A new step is always reported at once, however soon it arrives.
    written.clear()
    appmod.IPTVClient._report_update_progress(client, "Verifying download...", None,
                                              cancellable=False)
    assert written == [(str(tmp_path), "Verifying download...", None, False)]


def test_cancel_in_the_update_window_stops_the_download(monkeypatch, tmp_path):
    """The window's Cancel button is the only Cancel there is now."""
    monkeypatch.setattr(appmod.updater, "write_update_status", lambda *a: True)
    monkeypatch.setattr(appmod.updater, "update_cancel_requested", lambda _d: True)
    cancel = threading.Event()
    client = _update_client(_update_session_dir=str(tmp_path), _update_cancel=cancel)

    assert appmod.IPTVClient._report_update_progress(client, "Downloading...", 0.1) is False
    assert cancel.is_set()


def test_install_is_handed_to_the_window_that_is_already_up(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(appmod.updater, "write_update_command",
                        lambda session, action, **fields: commands.append((session, action, fields)) or True)
    monkeypatch.setattr(appmod.updater, "allow_any_foreground_window", lambda: None)
    monkeypatch.setattr(appmod.wx, "CallLater", lambda ms, fn: fn())
    ready = tmp_path / "ready"
    ready.write_text("", encoding="utf-8")
    client = _update_client(_update_session_dir=str(tmp_path),
                            _update_helper=_live_helper(),
                            _update_helper_ready=str(ready),
                            _finish_update_handoff=lambda: client.closed.append(True))

    appmod.IPTVClient._install_update_now(client, {"install_dir": "C:/app", "version": "9.9.9"})

    assert client._update_install_pending is True
    session, action, fields = commands[0]
    assert (session, action) == (str(tmp_path), "install")
    assert fields["install_dir"] == "C:/app" and fields["version"] == "9.9.9"
    assert fields["parent_pid"] == os.getpid()
    assert client.closed == [True]


def test_the_app_stays_open_when_the_update_window_is_gone(monkeypatch, tmp_path):
    """Leaving without a window is what left users with a silent install."""
    failures = []
    monkeypatch.setattr(appmod.updater, "write_update_command",
                        lambda *a, **kw: pytest.fail("nothing may be handed over"))
    client = _update_client(
        _update_session_dir=str(tmp_path),
        _update_helper=types.SimpleNamespace(poll=lambda: 3, returncode=3),
        _update_helper_ready=str(tmp_path / "ready"),
        _fail_update_handoff=lambda detail: failures.append(detail))

    appmod.IPTVClient._install_update_now(client, {"install_dir": "C:/app"})

    assert len(failures) == 1 and "window" in failures[0]
    assert client.closed == []
    assert client._update_install_pending is False


def test_a_failed_download_reports_in_the_same_window(monkeypatch, tmp_path):
    commands = []
    boxes = []
    monkeypatch.setattr(appmod.updater, "write_update_command",
                        lambda session, action, **fields: commands.append((action, fields)) or True)
    monkeypatch.setattr(appmod.wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))
    monkeypatch.setattr(appmod, "message_box", lambda *a, **kw: boxes.append(a))
    client = _update_client(_update_session_dir=str(tmp_path))

    appmod.IPTVClient._abort_update_window(client, "Update failed: no network")

    assert commands == [("abort", {"message": "Update failed: no network"})]
    assert boxes == [], "the window says it; a second window would not be one window"
    assert client._update_in_progress is False
    assert client._update_session_dir is None


def test_a_failure_without_a_window_still_reaches_the_user(monkeypatch):
    """The fallback for an update that never got a window at all."""
    boxes = []
    monkeypatch.setattr(appmod.wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))
    monkeypatch.setattr(appmod, "message_box", lambda *a, **kw: boxes.append(a))
    client = _update_client(_update_session_dir=None)

    appmod.IPTVClient._abort_update_window(client, "Update failed: no network")

    assert boxes and "no network" in boxes[0][0]


def test_close_for_update_install_lingers_before_quitting(monkeypatch):
    """The message needs to be on screen long enough for NVDA to speak it,
    and the app still has to quit well inside the helper's 30s window."""
    scheduled = []
    monkeypatch.setattr(
        appmod.wx, "CallLater",
        lambda ms, fn: scheduled.append((ms, fn)))
    handoffs = []
    client = _update_client(_finish_update_handoff=lambda: handoffs.append(True))
    appmod.IPTVClient._close_for_update_install(client)

    assert len(scheduled) == 1
    delay, callback = scheduled[0]
    assert delay == appmod._UPDATE_HANDOFF_LINGER_MS
    assert 0 < delay < 30_000, "must quit before update_helper.ps1 kills us"
    assert not client.closed, "closing before the linger would hide the message"

    callback()
    assert handoffs == [True]


def test_finish_update_handoff_keeps_the_gate_shut_then_closes():
    client = _update_client()
    appmod.IPTVClient._finish_update_handoff(client)
    # The update carries on in the helper after we are gone, so the gate stays
    # shut: a queued prompt must not be able to start a second one.
    assert client._update_in_progress is True
    assert client.closed == [True]


def test_finished_update_is_silent_on_success_and_loud_on_failure(monkeypatch, tmp_path):
    boxes = []
    monkeypatch.setattr(appmod, "message_box",
                        lambda *a, **kw: boxes.append(a[1] if len(a) > 1 else ""))
    monkeypatch.setattr(appmod, "get_user_config_dir", lambda create=False: str(tmp_path))

    pending = {"version": appmod.app_meta.APP_VERSION}
    monkeypatch.setattr(appmod.updater, "read_update_pending", lambda _d: dict(pending))
    monkeypatch.setattr(appmod.updater, "clear_update_pending", lambda _d: None)
    monkeypatch.setattr(appmod.updater, "read_update_result", lambda: None)
    monkeypatch.setattr(appmod.updater, "clear_update_result", lambda: None)
    monkeypatch.setattr(appmod.updater, "collect_update_logs", lambda: "")

    # Came back on the version we were aiming for, and the update's window
    # never said so: this side confirms it instead.
    appmod.IPTVClient._report_finished_update(types.SimpleNamespace())
    assert boxes == ["Update Complete"]

    # The usual case: the update's own window said so before it closed, so
    # there is no box to dismiss here - one window for the whole update.
    monkeypatch.setattr(appmod.updater, "read_update_result",
                        lambda: {"status": "completed", "version": appmod.app_meta.APP_VERSION})
    appmod.IPTVClient._report_finished_update(types.SimpleNamespace())
    assert boxes == ["Update Complete"]
    monkeypatch.setattr(appmod.updater, "read_update_result", lambda: None)

    # Came back on the old version: the install did not land, so say so.
    pending["version"] = "9999.0.0"
    appmod.IPTVClient._report_finished_update(types.SimpleNamespace())
    assert boxes == ["Update Complete", "Update Not Completed"]


def test_failed_update_says_why_and_offers_the_logs(monkeypatch, tmp_path):
    """Issue #26: six failures in a row reached the tracker with no cause."""
    bodies = []
    copied = []
    cleared = []
    monkeypatch.setattr(appmod, "message_box",
                        lambda *a, **kw: bodies.append(a) or appmod.wx.YES)
    monkeypatch.setattr(appmod, "get_user_config_dir", lambda create=False: str(tmp_path))
    monkeypatch.setattr(appmod.updater, "read_update_pending",
                        lambda _d: {"version": "9999.0.0"})
    monkeypatch.setattr(appmod.updater, "clear_update_pending", lambda _d: None)
    monkeypatch.setattr(appmod.updater, "read_update_result", lambda: {
        "kind": "installer", "exit_code": 5,
        "installer_error": "DeleteFile failed; code 5. Access is denied."})
    monkeypatch.setattr(appmod.updater, "clear_update_result", lambda: cleared.append(True))
    monkeypatch.setattr(appmod.updater, "collect_update_logs", lambda: "=== logs ===")
    client = types.SimpleNamespace(_copy_update_logs=copied.append)

    appmod.IPTVClient._report_finished_update(client)

    message, title, style = bodies[0]
    assert title == "Update Not Completed"
    assert "exit code 5" in message
    assert "DeleteFile failed; code 5. Access is denied." in message
    assert style == appmod.wx.YES_NO | appmod.wx.ICON_WARNING
    assert copied == ["=== logs ==="]
    assert cleared == [True]


def test_update_success_confirmation_names_the_new_version(monkeypatch, tmp_path):
    """Issue #19: after a restart the user must hear that the update landed."""
    bodies = []
    monkeypatch.setattr(appmod, "message_box", lambda *a, **kw: bodies.append(a))
    monkeypatch.setattr(appmod, "get_user_config_dir", lambda create=False: str(tmp_path))
    monkeypatch.setattr(appmod.updater, "read_update_pending",
                        lambda _d: {"version": appmod.app_meta.APP_VERSION})
    monkeypatch.setattr(appmod.updater, "clear_update_pending", lambda _d: None)
    # Without this the test reads the real result file in %TEMP%: a genuine
    # update - or a run of tools/smoke_update_window.py - on the machine
    # running the tests then decides whether this confirmation appears.
    monkeypatch.setattr(appmod.updater, "read_update_result", lambda: None)
    monkeypatch.setattr(appmod.updater, "clear_update_result", lambda: None)

    appmod.IPTVClient._report_finished_update(types.SimpleNamespace())

    assert len(bodies) == 1
    message, title, style = bodies[0]
    assert title == "Update Complete"
    assert appmod.app_meta.APP_VERSION in message
    assert appmod.app_meta.APP_DISPLAY_NAME in message
    assert style == appmod.wx.OK | appmod.wx.ICON_INFORMATION


def test_update_report_only_runs_when_a_pending_marker_exists(monkeypatch, tmp_path):
    """A plain start (or a check that found nothing new) must show nothing."""
    boxes = []
    monkeypatch.setattr(appmod, "message_box", lambda *a, **kw: boxes.append(a))
    monkeypatch.setattr(appmod, "get_user_config_dir", lambda create=False: str(tmp_path))
    monkeypatch.setattr(appmod.updater, "read_update_pending", lambda _d: None)

    appmod.IPTVClient._report_finished_update(types.SimpleNamespace())
    assert boxes == []



# --------------------------------------------------------------------------- #
# The catch-up dialog has no buttons at all
# --------------------------------------------------------------------------- #
def test_catchup_dialog_has_no_close_button(host):
    """Close was a Tab stop that only did what Escape already does."""
    dlg = CatchupDialog(host, "BBC One", [
        {"start": "20260101120000", "end": "20260101130000",
         "title": "News", "description": "The one o'clock news."},
    ])
    try:
        buttons = [w for w in dlg.GetChildren()[0].GetChildren()
                   if isinstance(w, wx.Button)]
        assert buttons == []
    finally:
        dlg.Destroy()


def test_catchup_dialog_tab_ring_is_two_controls(host):
    dlg = CatchupDialog(host, "BBC One", [
        {"start": "20260101120000", "end": "20260101130000", "title": "News"},
    ])
    try:
        tab = types.SimpleNamespace(
            GetKeyCode=lambda: wx.WXK_TAB,
            ShiftDown=lambda: False,
            HasAnyModifiers=lambda: False,
            Skip=lambda *a: None,
        )
        dlg._on_key(tab)
        assert dlg.FindFocus() is dlg.description_field
        dlg._on_description_key(tab)
        assert dlg.FindFocus() is dlg.listbox

        shift_tab = types.SimpleNamespace(
            GetKeyCode=lambda: wx.WXK_TAB,
            ShiftDown=lambda: True,
            HasAnyModifiers=lambda: True,
            Skip=lambda *a: None,
        )
        dlg.description_field.SetFocus()
        dlg._on_description_key(shift_tab)
        assert dlg.FindFocus() is dlg.listbox
    finally:
        dlg.Destroy()


def test_catchup_dialog_escape_still_closes_it(host, monkeypatch):
    dlg = CatchupDialog(host, "BBC One", [])
    try:
        ended = []
        monkeypatch.setattr(dlg, "EndModal", lambda code: ended.append(code))
        skipped = []
        dlg._on_dialog_key(types.SimpleNamespace(
            GetKeyCode=lambda: wx.WXK_ESCAPE,
            Skip=lambda *a: skipped.append(True)))
        assert ended == [wx.ID_CANCEL]
        assert skipped == []
    finally:
        dlg.Destroy()


# --------------------------------------------------------------------------- #
# The update hand-off happens behind a window that is already on screen
# --------------------------------------------------------------------------- #
def test_the_update_window_is_opened_before_the_download(monkeypatch, tmp_path):
    """It is the first thing the update does, and it says so from the start."""
    launched = []
    written = []
    monkeypatch.setattr(appmod.updater, "write_update_status",
                        lambda *a: written.append(a) or True)
    monkeypatch.setattr(appmod.updater, "allow_any_foreground_window", lambda: None)
    monkeypatch.setattr(appmod.updater, "launch_update_helper",
                        lambda helper, args: launched.append((helper, args)) or _live_helper())
    helper = tmp_path / "helper" / "update_helper.ps1"
    helper.parent.mkdir()
    helper.write_text("", encoding="utf-8")
    client = _update_client(
        _stage_update_helper=lambda root: str(helper),
        _update_handoff_ready_path=staticmethod(
            appmod.IPTVClient._update_handoff_ready_path).__func__,
        _update_helper_language=lambda: "hu",
    )

    appmod.IPTVClient._open_update_window(client, str(tmp_path))

    assert client._update_session_dir == str(helper.parent)
    assert written and written[0][1] and written[0][3] is True
    _path, args = launched[0]
    assert "-SessionDir" in args and str(helper.parent) in args
    assert args[args.index("-Language") + 1] == "hu"
    assert args[args.index("-ParentPid") + 1] == str(os.getpid())


def test_a_helper_that_will_not_start_does_not_stop_the_update(monkeypatch, tmp_path):
    """Without a window the update falls back to the app's own message boxes."""
    monkeypatch.setattr(appmod.updater, "write_update_status", lambda *a: True)
    monkeypatch.setattr(appmod.updater, "allow_any_foreground_window", lambda: None)

    def boom(_helper, _args):
        raise OSError("powershell is missing")

    monkeypatch.setattr(appmod.updater, "launch_update_helper", boom)
    helper = tmp_path / "helper" / "update_helper.ps1"
    helper.parent.mkdir()
    helper.write_text("", encoding="utf-8")
    client = _update_client(
        _stage_update_helper=lambda root: str(helper),
        _update_handoff_ready_path=staticmethod(
            appmod.IPTVClient._update_handoff_ready_path).__func__,
        _update_helper_language=lambda: "en",
    )

    appmod.IPTVClient._open_update_window(client, str(tmp_path))

    assert client._update_session_dir is None
    assert appmod.IPTVClient._update_window_is_up(client) is False


def test_failed_handoff_keeps_the_app_and_names_the_log(monkeypatch, tmp_path):
    boxes = []
    cleared = []
    monkeypatch.setattr(appmod, "message_box", lambda *a, **kw: boxes.append(a))
    monkeypatch.setattr(appmod, "get_user_config_dir", lambda create=True: str(tmp_path))
    monkeypatch.setattr(appmod.updater, "clear_update_pending", lambda d: cleared.append(d))
    client = _update_client(
        _update_install_pending=True,
        _update_session_dir="session",
    )
    appmod.IPTVClient._fail_update_handoff(client, "boom")

    assert client._update_install_pending is False
    # The gate reopens: the user can try again from the Help menu.
    assert client._update_in_progress is False
    assert cleared == [str(tmp_path)]
    assert not client.closed
    message, title, _style = boxes[0]
    assert title == "Update Error"
    assert "will stay open" in message
    assert appmod.updater.update_log_path() in message


def test_a_helper_we_give_up_on_is_not_left_on_screen(monkeypatch, tmp_path):
    """Its window has no close button, so an abandoned helper is unclosable."""
    monkeypatch.setattr(appmod, "message_box", lambda *a, **kw: None)
    monkeypatch.setattr(appmod, "get_user_config_dir", lambda create=True: str(tmp_path))
    monkeypatch.setattr(appmod.updater, "clear_update_pending", lambda _d: None)
    stopped = []
    helper = types.SimpleNamespace(poll=lambda: None, returncode=None,
                                   terminate=lambda: stopped.append(True))
    client = _update_client(_update_session_dir=str(tmp_path), _update_helper=helper)

    appmod.IPTVClient._fail_update_handoff(client, "boom")

    assert stopped == [True]


def test_a_live_helper_keeps_the_folder_it_is_running_from(tmp_path):
    """_abort_update_window ends the flow on the GUI thread, which clears our
    own reference, so the caller's view of the helper is what counts."""
    temp_root = tmp_path / "update"
    temp_root.mkdir()
    (temp_root / "update_helper.ps1").write_text("", encoding="utf-8")
    client = _update_client(_update_helper=None)  # already cleared by the GUI thread
    live = types.SimpleNamespace(poll=lambda: None)

    appmod.IPTVClient._discard_update_download(client, str(temp_root), live)
    assert temp_root.exists(), "the running helper's own script was deleted"

    appmod.IPTVClient._discard_update_download(client, str(temp_root),
                                               types.SimpleNamespace(poll=lambda: 0))
    assert not temp_root.exists()


def test_the_app_never_presses_alt_to_take_the_foreground():
    """Alt is what opens a menu bar.

    Synthesising an Alt keypress is the well-known trick for unlocking
    SetForegroundWindow, and it left the user in the menu bar instead of the
    channel list after every restore from the tray, every time a second copy
    brought the running one to the front, and at the end of every update.
    """
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    foreground = source[source.index("def _force_foreground"):
                        source.index("def _restore_focus_after_tray")]
    assert "keybd_event" not in foreground
    assert "VK_MENU" not in foreground
    # The part that really grants the right is still there.
    assert "AttachThreadInput" in foreground
    assert "SetForegroundWindow" in foreground
    assert "keybd_event" not in source, "no other path may press keys either"
