"""Live buffering in the built-in player: a quick start, and a fill that never slows playback."""
import os
import pathlib
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import internal_player  # noqa: E402
import options  # noqa: E402
from internal_player import QUICK_START_SECONDS  # noqa: E402


def test_playback_is_never_slowed_down_to_fill_the_buffer():
    """Filling the buffer used to play live streams at 0.95, which made speech
    drag. Every provider now fills at 1.0 or faster - the buffer grows from what
    the server hands over ahead of real time - so the player must never touch
    the media player's rate at all."""
    source = pathlib.Path(internal_player.__file__).read_text(encoding="utf-8")
    assert "set_rate" not in source


def test_quick_start_cache_is_half_a_second():
    assert QUICK_START_SECONDS == 0.5


def test_default_buffer_is_twenty_five_and_saved_values_are_kept():
    assert options.DEFAULT_INTERNAL_PLAYER_BUFFER_SECONDS == 25.0
    cfg = {}
    options._apply_internal_player_bounds(cfg)
    assert cfg["internal_player_buffer_seconds"] == 25.0
    assert cfg["internal_player_max_buffer_seconds"] >= 25.0
    cfg = {"internal_player_buffer_seconds": 2.0}  # saved: an explicit choice
    options._apply_internal_player_bounds(cfg)
    assert cfg["internal_player_buffer_seconds"] == 2.0


class _Frame:
    """Just the attributes _compute_buffer_profile reads."""

    _max_buffer_seconds = 30.0
    base_buffer_seconds = 25.0

    def _estimate_stream_bitrate(self, url, headers=None):
        return None


def test_new_live_channel_opens_on_the_quick_cache():
    f = _Frame()
    f._quick_start = True
    target, profile, _ = internal_player.InternalPlayerFrame._compute_buffer_profile(f, "http://h/live/u/p/1.ts")
    assert target == 25.0
    assert profile["network_ms"] == profile["live_ms"] == 500


def test_restart_after_a_stall_opens_on_the_full_cache():
    f = _Frame()
    f._quick_start = False
    _, profile, _ = internal_player.InternalPlayerFrame._compute_buffer_profile(f, "http://h/live/u/p/1.ts")
    assert profile["network_ms"] == 25000


def test_dispatcharr_stall_does_not_raise_the_saved_buffer(monkeypatch):
    """Dispatcharr buffers server-side, so its channels keep the saved buffer:
    a stall reconnects without growing the client cache."""
    later = []
    monkeypatch.setattr(internal_player.wx, "CallLater", lambda ms, fn: later.append(fn))
    monkeypatch.setattr(internal_player.time, "monotonic", lambda: 100.0)
    frame = SimpleNamespace(
        _destroyed=False, _manual_stop=False, _gave_up=False, _dispatcharr=True,
        _current_url="http://h/live/u/p/1", _current_title="A", _current_stream_kind="live",
        _pending_xtream_refresh=False, _pending_restart=False,
        _last_restart_ts=0.0, _reconnect_reset_window=120.0, _restart_cooldown=2.0,
        _reconnect_attempts=0, _max_reconnect_attempts=6, _last_restart_reason="",
        _vlc_generation=5, _update_status_label=lambda *a, **k: None,
        _reconnect_delay_ms=internal_player.InternalPlayerFrame._reconnect_delay_ms,
        base_buffer_seconds=0.5, _buffer_step_seconds=1.0, _max_buffer_seconds=30.0,
        _refresh_ts_floor=lambda: None, _update_cache_bounds=lambda: None,
        _estimate_stream_bitrate=lambda *a, **k: None, play=lambda *a, **k: None,
    )
    internal_player.InternalPlayerFrame._schedule_restart(frame, "playback stalled", adjust_buffer=True)
    later[0]()
    assert frame.base_buffer_seconds == 0.5
    assert frame._reconnect_attempts == 1
