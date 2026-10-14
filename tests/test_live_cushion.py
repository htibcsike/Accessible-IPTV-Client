"""Quick start plus a cushion built by slow play (live channels in the built-in player)."""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import internal_player  # noqa: E402
import options  # noqa: E402
from internal_player import QUICK_START_SECONDS, SLOW_RATE, live_cushion_seconds, pace_rate  # noqa: E402


def test_cushion_is_cache_plus_unread_backlog():
    # 4 Mbps = 500 kB/s; 10 s played on a 2 s cache = 12 s demuxed = 6 MB. 1 MB more read = 2 s.
    assert live_cushion_seconds(7_000_000, 6_000_000, 10_000, 2.0) == 4.0


def test_cushion_without_history_is_the_cache():
    assert live_cushion_seconds(500_000, 400_000, 1_000, 2.0) == 2.0
    assert live_cushion_seconds(9_000_000, 1_000_000, 3_000, 2.0) == 2.0  # startup burst: not trusted yet
    assert live_cushion_seconds(0, 0, 30_000, 2.0) == 2.0


def test_cushion_never_counts_negative_backlog():
    assert live_cushion_seconds(5_000_000, 6_000_000, 10_000, 2.0) == 2.0


def test_slow_until_full_then_normal_without_flapping():
    assert pace_rate(2.0, 10.0, 1.0) == SLOW_RATE
    assert pace_rate(9.9, 10.0, SLOW_RATE) == SLOW_RATE  # keeps building
    assert pace_rate(10.0, 10.0, SLOW_RATE) == 1.0  # full
    assert pace_rate(9.5, 10.0, 1.0) == 1.0  # just under: no flip back
    assert pace_rate(8.9, 10.0, 1.0) == SLOW_RATE  # a second short: rebuild


def test_slow_rate_keeps_speech_natural():
    assert 0.9 <= SLOW_RATE < 1.0
    assert QUICK_START_SECONDS <= 2.0


def test_saved_small_buffer_still_grows_a_twenty_five_second_cushion(monkeypatch):
    stats = SimpleNamespace(read_bytes=0, demux_read_bytes=0)
    monkeypatch.setattr(internal_player.vlc, "MediaStats", lambda: stats)
    rates = []
    frame = SimpleNamespace(
        _current_stream_kind="live", _is_paused=False, _paced_rate=1.0,
        _max_buffer_seconds=30.0, base_buffer_seconds=2.0, _live_cache_seconds=10.0,
        player=SimpleNamespace(get_media=lambda: SimpleNamespace(get_stats=lambda _: True),
                               get_time=lambda: 30_000, set_rate=rates.append),
        _vlc_call=lambda call: call(),
    )
    internal_player.InternalPlayerFrame._pace_live(frame, "playing")
    assert rates == [SLOW_RATE]
    frame._live_cache_seconds = 25.0
    internal_player.InternalPlayerFrame._pace_live(frame, "playing")
    assert rates == [SLOW_RATE, 1.0]


def test_default_cushion_is_twenty_five_and_saved_values_are_kept():
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
    assert profile["network_ms"] == profile["live_ms"] == 2000
    assert f._live_cache_seconds == 2.0


def test_restart_after_a_stall_opens_on_the_full_cache():
    f = _Frame()
    f._quick_start = False
    _, profile, _ = internal_player.InternalPlayerFrame._compute_buffer_profile(f, "http://h/live/u/p/1.ts")
    assert profile["network_ms"] == 25000
