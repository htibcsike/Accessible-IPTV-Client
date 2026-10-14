"""Quick start plus a cushion built by slow play (live channels in the built-in player)."""
import os
import sys

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


def test_saved_small_buffer_still_grows_a_ten_second_cushion():
    assert internal_player.LIVE_CUSHION_SECONDS == 10.0
    src = open(internal_player.__file__, encoding="utf-8").read()
    assert "max(LIVE_CUSHION_SECONDS, self.base_buffer_seconds)" in src


def test_default_cushion_is_ten_and_saved_values_are_kept():
    assert options.DEFAULT_INTERNAL_PLAYER_BUFFER_SECONDS == 10.0
    cfg = {}
    options._apply_internal_player_bounds(cfg)
    assert cfg["internal_player_buffer_seconds"] == 10.0
    cfg = {"internal_player_buffer_seconds": 2.0}  # saved: an explicit choice
    options._apply_internal_player_bounds(cfg)
    assert cfg["internal_player_buffer_seconds"] == 2.0


class _Frame:
    """Just the attributes _compute_buffer_profile reads."""

    _max_buffer_seconds = 18.0
    base_buffer_seconds = 10.0

    def _estimate_stream_bitrate(self, url, headers=None):
        return None


def test_new_live_channel_opens_on_the_quick_cache():
    f = _Frame()
    f._quick_start = True
    target, profile, _ = internal_player.InternalPlayerFrame._compute_buffer_profile(f, "http://h/live/u/p/1.ts")
    assert target == 10.0
    assert profile["network_ms"] == profile["live_ms"] == 2000
    assert f._live_cache_seconds == 2.0


def test_restart_after_a_stall_opens_on_the_full_cache():
    f = _Frame()
    f._quick_start = False
    _, profile, _ = internal_player.InternalPlayerFrame._compute_buffer_profile(f, "http://h/live/u/p/1.ts")
    assert profile["network_ms"] == 10000
