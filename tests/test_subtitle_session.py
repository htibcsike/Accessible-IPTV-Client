"""Tests for the subtitle session controller (subtitle_session.py).

GUI-free and dependency-free. The controller owns one subtitle-speech session
at a time, and the whole point of the token is that a cue from a session that
has already been replaced is never spoken.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle_session import SubtitleSessionController  # noqa: E402


class _Manager:
    def __init__(self):
        self.source = None
        self.cleared = 0

    def set_source(self, name):
        self.source = name

    def clear(self):
        self.cleared += 1


class _Adapter:
    def __init__(self):
        self.closed = 0
        self.done = threading.Event()

    def cancel(self):
        pass

    def close(self, terminate=True):
        self.closed += 1
        self.done.set()


def test_a_new_session_supersedes_the_old_one():
    manager = _Manager()
    controller = SubtitleSessionController(manager)
    first = controller.activate_session("Sky Mix")
    second = controller.activate_session("CNN")

    assert first != second
    assert controller.session_token == second
    assert controller.is_current(second)
    assert not controller.is_current(first)
    assert manager.source == "CNN"


def test_cancelling_closes_the_adapter_and_clears_the_manager():
    manager = _Manager()
    controller = SubtitleSessionController(manager)
    controller.activate_session("Sky Mix")
    adapter = _Adapter()
    controller.set_adapter(adapter, controller.session_token)

    controller.cancel_session()

    assert controller.session_token is None
    assert not controller.is_current("anything")
    assert adapter.done.wait(1)
    assert adapter.closed == 1
    assert manager.source == ""


def test_replacing_the_adapter_closes_the_old_one():
    controller = SubtitleSessionController(_Manager())
    token = controller.activate_session("MPV")
    first = _Adapter()
    second = _Adapter()
    controller.set_adapter(first, token)
    controller.set_adapter(second, token)
    assert first.done.wait(1)
    assert first.closed == 1
    assert second.closed == 0


def test_a_stale_cue_is_never_spoken():
    """A cue from the previous channel must not reach the screen reader."""
    manager = _Manager()
    controller = SubtitleSessionController(manager)
    spoken = []
    old = controller.activate_session("Sky Mix")
    controller.activate_session("CNN")

    assert controller.speak_validated(old, "stale line", spoken.append) is False
    assert spoken == []


def test_the_current_session_is_spoken_on_the_ui_thread():
    manager = _Manager()
    controller = SubtitleSessionController(manager)
    queued = []
    controller.set_ui_thread(queued.append)
    token = controller.activate_session("Sky Mix")
    spoken = []

    assert controller.speak_validated(token, "hello", spoken.append) is True
    assert spoken == [], "the speech must wait for the UI thread"
    queued.pop()()
    assert spoken == ["hello"]


def test_a_cue_dropped_between_the_queue_and_the_ui_thread_is_not_spoken():
    manager = _Manager()
    controller = SubtitleSessionController(manager)
    queued = []
    controller.set_ui_thread(queued.append)
    token = controller.activate_session("Sky Mix")
    spoken = []

    controller.speak_validated(token, "hello", spoken.append)
    controller.activate_session("CNN")  # the channel changed while it was queued
    queued.pop()()
    assert spoken == []


import threading

from subtitle_speech import SubtitleSpeechManager


def test_old_producer_and_queued_state_cannot_touch_new_session():
    spoken, queued, states = [], [], []
    manager = SubtitleSpeechManager(spoken.append, ui_thread=queued.append)
    manager.set_auto_speech(True)
    owner = SubtitleSessionController(manager)
    owner.set_ui_thread(queued.append)
    old = owner.activate_session("MPV")
    producer = owner.bind(old)
    producer.on_cue("Old")
    owner.dispatch(old, states.append, "unavailable")
    new = owner.activate_session("built-in")
    owner.bind(new).on_cue("New")
    producer.clear()
    producer.on_cue("Late old")
    producer.set_capability("MPV", "timed_cues", "available")
    for callback in queued:
        callback()
    assert spoken == ["New"]
    assert states == []
    assert [cue.text for cue in manager.get_recent()] == ["New"]
    assert manager.get_capability("MPV", "timed_cues") == "unverified"


def test_retirement_cancels_now_but_cleans_up_off_ui():
    cancelled, cleaned, closed = threading.Event(), threading.Event(), []
    caller = threading.get_ident()

    class Adapter:
        def cancel(self):
            cancelled.set()

        def close(self, terminate):
            closed.append((terminate, threading.get_ident()))
            cleaned.set()

    owner = SubtitleSessionController(SubtitleSpeechManager(lambda text: None))
    token = owner.activate_session()
    owner.set_adapter(Adapter(), token)
    owner.cancel_session()
    assert cancelled.is_set()
    assert cleaned.wait(1)
    assert closed[0][0] is False  # detaching speech need not terminate playback
    assert closed[0][1] != caller


def test_late_adapter_registration_is_retired():
    closed = threading.Event()

    class Adapter:
        def cancel(self):
            pass

        def close(self, terminate):
            assert terminate
            closed.set()

    owner = SubtitleSessionController(SubtitleSpeechManager(lambda text: None))
    old = owner.activate_session()
    owner.activate_session()
    assert not owner.set_adapter(Adapter(), old)
    assert closed.wait(1)


def test_pause_purges_once_and_manual_review_survives_timer_ticks():
    spoken, purged = [], []
    manager = SubtitleSpeechManager(spoken.append)
    owner = SubtitleSessionController(manager, stop_speech=lambda: purged.append(True))
    sink = owner.bind(owner.activate_session())
    purged.clear()
    sink.set_paused(True)
    sink.speak_review("Review")
    sink.set_paused(True)
    assert len(purged) == 1
    assert spoken == ["Review"]
