"""Real wx controls must stay reachable and reflect failed playback."""
import types

import pytest
import wx

from internal_player import InternalPlayerFrame


@pytest.fixture
def player_frame():
    app = wx.GetApp() or wx.App()
    frame = InternalPlayerFrame(None)
    frame.Show()
    app.Yield()
    frame._notify_box = lambda *args: None
    yield frame
    frame.Destroy()
    app.Yield()


def test_tab_skips_disabled_and_hidden_controls(player_frame):
    frame = player_frame
    frame._current_url = "https://example.invalid/stream"
    frame._update_status_label("Opening")
    frame.play_pause_btn.SetFocus()
    frame._focus_control_step(False)
    assert wx.Window.FindFocus() is frame.volume_slider
    frame.record_btn.Hide()
    frame.stop_btn.SetFocus()
    frame._focus_control_step(True)
    assert wx.Window.FindFocus() is frame.cast_btn


def test_tab_from_slider_stays_in_named_controls(player_frame):
    frame = player_frame
    frame._current_url = "https://example.invalid/stream"
    frame._update_status_label("Opening")
    frame.volume_slider.SetFocus()
    event = types.SimpleNamespace(
        GetKeyCode=lambda: wx.WXK_TAB, ControlDown=lambda: False,
        AltDown=lambda: False, ShiftDown=lambda: False, Skip=lambda: None)
    frame._on_key_down(event)
    assert wx.Window.FindFocus() is frame.play_pause_btn


@pytest.mark.parametrize("fast_refresh", [False, True])
def test_failed_connection_disables_buttons_menus_and_pause_shortcut(player_frame, fast_refresh):
    frame = player_frame
    frame._current_url = frame._last_resolved_url = "https://example.invalid/live/user/pass/123.ts"
    frame._current_stream_kind = "live"
    frame._has_seen_playing = True
    frame._xtream_refresh_count = frame._max_xtream_refreshes
    frame._reconnect_attempts = frame._max_reconnect_attempts
    frame._update_status_label("Playing")
    frame.play_pause_btn.SetFocus()
    if fast_refresh:
        frame._restart_expected_xtream_live()
    else:
        frame._schedule_restart("playback error")
    assert not frame.play_pause_btn.IsEnabled()
    assert not frame.stop_btn.IsEnabled()
    items = frame.GetMenuBar().GetMenu(0).GetMenuItems()
    assert not items[0].IsEnabled()
    assert not items[1].IsEnabled()
    assert wx.Window.FindFocus() is frame.record_btn
    calls = []
    frame._vlc_call = calls.append
    frame._on_toggle_pause()
    assert calls == []


def test_manual_stop_keeps_play_available_but_disables_stop(player_frame):
    frame = player_frame
    frame._current_url = frame._last_resolved_url = "https://example.invalid/stream"
    frame.stop(manual=True)
    assert frame.play_pause_btn.IsEnabled()
    assert frame.play_pause_btn.GetLabel() == "Play"
    assert not frame.stop_btn.IsEnabled()
