"""Countdown deadlines, stale deliveries and the actual player expiry path."""
import math
from types import SimpleNamespace

import pytest

from playback_timer import PlaybackTimer
from tests.test_subtitle_integration import extract_class


@pytest.mark.parametrize("value", [-1, 1441, True, False, 1.5, "30", None, float("nan")])
def test_invalid_input_cannot_replace_a_running_timer(value):
    timer = PlaybackTimer(lambda: 10)
    timer.set_minutes(30)
    before = timer.deadline, timer.generation
    with pytest.raises(ValueError):
        timer.set_minutes(value)
    assert (timer.deadline, timer.generation) == before


def test_countdown_can_be_replaced_cancelled_and_consumed_only_once():
    now = [100.0]
    timer = PlaybackTimer(lambda: now[0])
    old = timer.set_minutes(1)
    latest = timer.set_minutes(2)
    now[0] = 160.0
    assert not timer.take_due(old)
    assert not timer.take_due(latest)
    assert timer.remaining_minutes() == 1
    now[0] = 220.0
    assert timer.take_due(latest)
    assert not timer.take_due(latest)
    assert timer.remaining_minutes() == 0
    latest = timer.set_minutes(1)
    timer.set_minutes(0)
    now[0] += 100
    assert not timer.take_due(latest)


def test_player_expiry_stops_only_playback_and_ignores_early_stale_or_closed_callbacks():
    now, delayed, stops = [0.0], [], []
    timer = PlaybackTimer(lambda: now[0])
    cls, _ = extract_class("internal_player.py", "InternalPlayerFrame", ["_expire_sleep_timer"], {
        "math": math, "time": SimpleNamespace(monotonic=lambda: now[0]),
        "wx": SimpleNamespace(CallLater=lambda *args: delayed.append(args)),
    })
    player = cls()
    player._destroyed = False
    player._sleep_countdown = timer
    player.stop = lambda **kwargs: stops.append(kwargs)
    generation = timer.set_minutes(1)
    player._expire_sleep_timer(generation)
    assert delayed[0][0] == 60000 and stops == []
    now[0] = 60.0
    player._expire_sleep_timer(generation)
    player._expire_sleep_timer(generation)
    assert stops == [{"manual": True}]
    generation = timer.set_minutes(1)
    player._destroyed = True
    now[0] = 120.0
    player._expire_sleep_timer(generation)
    assert len(stops) == 1


@pytest.mark.parametrize('accepted,minutes', [(False, 5), (True, 0), (True, 5)])
def test_actual_timer_dialog_honours_cancellation_and_replaces_old_delivery(accepted, minutes):
    destroyed, stopped, delayed, topics = [], [], [], []
    class Dialog:
        def __init__(self, *args): pass
        def ShowModal(self): return int(accepted)
        def GetValue(self): return minutes
        def Destroy(self): destroyed.append(True)
    wx = SimpleNamespace(NumberEntryDialog=Dialog, ID_OK=1,
                         CallLater=lambda *args: delayed.append(args))
    cls, _ = extract_class('internal_player.py', 'InternalPlayerFrame', ['_configure_sleep_timer'], {
        'wx': wx, 'user_guide': SimpleNamespace(set_help_topic=lambda *args: topics.append(args[1])),
    })
    frame = cls()
    frame._sleep_countdown = PlaybackTimer(lambda: 0)
    old = frame._sleep_countdown.set_minutes(10)
    frame._sleep_call = SimpleNamespace(Stop=lambda: stopped.append(True))
    frame._expire_sleep_timer = lambda generation: None
    frame._configure_sleep_timer()
    assert destroyed == [True] and topics == ['built-in-player']
    assert bool(stopped) == accepted
    assert bool(delayed) == (accepted and minutes > 0)
    assert (frame._sleep_countdown.generation != old) == accepted
