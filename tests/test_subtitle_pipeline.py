"""The same file source and snapshot contract work without a player SDK."""
from dataclasses import FrozenInstanceError, replace

import pytest

from subtitle_cues import Cue
from subtitle_pipeline import PlaybackPosition, SubtitleSnapshot, TimedTextSource
from subtitle_session import SubtitleSessionController
from subtitle_speech import SubtitleSpeechManager

CUES = [Cue(1000, 2000, "One"), Cue(3000, 4000, "Two"), Cue(5000, 6000, "Two")]


def frame(sequence=1, **kwargs):
    values = dict(text="Caption", source="bridge", generation=0, sequence=sequence,
                  start_ms=1000, end_ms=2000)
    values.update(kwargs)
    return SubtitleSnapshot(**values)


def pipeline(queued=False):
    said, tasks, purged = [], [], []
    manager = SubtitleSpeechManager(said.append, ui_thread=tasks.append if queued else None)
    manager.set_auto_speech(True)
    owner = SubtitleSessionController(manager, stop_speech=lambda: purged.append(True))
    if queued:
        owner.set_ui_thread(tasks.append)
    sink = owner.bind(owner.activate_session("bridge"))
    purged.clear()
    return manager, owner, sink, said, tasks, purged


@pytest.mark.parametrize("changes", [
    {"sequence": True}, {"sequence": 0}, {"generation": -1}, {"generation": False},
    {"text": None}, {"track": None}, {"source": ""}, {"source": None},
    {"start_ms": 1.5}, {"start_ms": True}, {"end_ms": 1000},
    {"paused": 1}, {"active": "yes"}, {"text_supported": None},
])
def test_malformed_snapshot_is_rejected(changes):
    with pytest.raises(ValueError):
        frame(**changes)


def test_snapshot_cannot_be_mutated_after_handoff():
    snapshot = frame()
    with pytest.raises(FrozenInstanceError):
        snapshot.text = "changed"


@pytest.mark.parametrize("changes", [
    {"position_ms": True}, {"position_ms": 1.5}, {"paused": 0}, {"subtitle_delay_ms": None},
])
def test_clock_contract_rejects_ambiguous_units_or_states(changes):
    values = dict(position_ms=1000)
    values.update(changes)
    with pytest.raises(ValueError):
        PlaybackPosition(**values)


@pytest.mark.parametrize("delay,position,expected", [(500, 1500, "One"), (-500, 500, "One"), (500, 500, "")])
def test_one_file_scheduler_handles_positive_and_negative_delay(delay, position, expected):
    source = TimedTextSource(CUES)
    result = source.sample(PlaybackPosition(position, subtitle_delay_ms=delay))
    assert result.snapshot.text == expected


@pytest.mark.parametrize("unknown", [None, -1])
def test_unknown_clock_never_becomes_a_caption_through_negative_delay(unknown):
    source = TimedTextSource(CUES)
    sample = source.sample(PlaybackPosition(unknown, subtitle_delay_ms=-2000))
    assert sample.index is None and not sample.snapshot.active
    assert sample.snapshot.text == ""


def test_source_owns_immutable_sorted_cues():
    cues = list(reversed(CUES))
    source = TimedTextSource(cues)
    cues.clear()
    assert source.sample(PlaybackPosition(1500)).snapshot.text == "One"


def test_overlap_uses_the_common_parser_lookup_semantics():
    source = TimedTextSource([Cue(0, 10000, "Long"), Cue(1000, 2000, "Short")])
    assert source.sample(PlaybackPosition(1500)).snapshot.text == "Short"
    assert source.sample(PlaybackPosition(2500)).snapshot.text == "Long"


def test_disabled_track_does_not_advance_review_and_reenable_detects_rewind():
    source = TimedTextSource(CUES)
    source.sample(PlaybackPosition(5500))
    off = source.sample(PlaybackPosition(500), enabled=False)
    assert off.index is None and off.latest_index == 2
    back = source.sample(PlaybackPosition(500))
    assert back.rewound and back.latest_index is None
    assert back.snapshot.generation == 1


def test_file_identity_change_and_backwards_seek_start_new_generations():
    source = TimedTextSource(CUES, generation=7)
    first = source.sample(PlaybackPosition(5500), track="first")
    back = source.sample(PlaybackPosition(1500), track="first")
    other = source.sample(PlaybackPosition(1500), track="second")
    assert [s.snapshot.generation for s in (first, back, other)] == [7, 8, 9]
    assert [s.snapshot.sequence for s in (first, back, other)] == [1, 2, 3]


@pytest.mark.parametrize("suffix,content", [
    (".srt", "1\n00:00:01,000 --> 00:00:02,000\nÁrvíztűrő szöveg\n"),
    (".vtt", "WEBVTT\n\n00:01.000 --> 00:02.000\nÁrvíztűrő szöveg\n"),
])
def test_shared_file_loader_uses_existing_unicode_parser(tmp_path, suffix, content):
    path = tmp_path / ("felirat" + suffix)
    path.write_text(content, encoding="utf-8-sig")
    source = TimedTextSource.from_file(path)
    assert source.sample(PlaybackPosition(1500)).snapshot.text == "Árvíztűrő szöveg"


def test_same_contract_accepts_clock_only_and_native_text_bridges():
    manager, owner, sink, said, _, _ = pipeline()
    source = TimedTextSource(CUES)
    sink.on_snapshot(source.sample(PlaybackPosition(1500), source="file").snapshot)
    assert said == ["One"]
    new_sink = owner.bind(owner.activate_session("native"))
    assert not sink.on_snapshot(source.sample(PlaybackPosition(3500)).snapshot)
    assert new_sink.on_snapshot(frame(text="Native text"))
    assert said == ["One", "Native text"]
    assert [c.text for c in manager.get_recent()] == ["Native text"]


def test_paused_file_is_reviewable_and_repeated_words_keep_their_times():
    manager, _, sink, said, _, _ = pipeline()
    source = TimedTextSource(CUES)
    for ms, paused in ((1500, True), (3500, False), (5500, False)):
        sink.on_snapshot(source.sample(PlaybackPosition(ms, paused=paused)).snapshot)
        if paused:
            assert said == []
            assert manager.read_current()
    assert said == ["One", "Two", "Two"]
    assert [c.start_ms for c in manager.get_recent()] == [1000, 3000, 5000]


def test_late_serial_generation_and_pause_cannot_replace_current_state():
    manager, _, sink, said, _, _ = pipeline()
    assert sink.on_snapshot(frame(2, text="New"))
    assert not sink.on_snapshot(frame(1, text="Late", paused=True))
    assert sink.on_snapshot(frame(1, generation=1, text="After seek"))
    assert not sink.on_snapshot(frame(99, text="Old generation"))
    assert said == ["New", "After seek"]
    assert [c.text for c in manager.get_recent()] == ["After seek"]


@pytest.mark.parametrize("changes", [{"text": ""}, {"active": False}, {"text_supported": False}])
def test_gap_off_and_bitmap_clear_current_without_speaking_or_losing_review(changes):
    manager, _, sink, said, _, _ = pipeline()
    sink.on_snapshot(frame())
    sink.on_snapshot(frame(2, **changes))
    assert not manager.read_current()
    assert manager.read_previous()
    assert said == ["Caption", "Caption"]


def test_clear_does_not_reopen_intake_for_delayed_snapshots():
    manager, _, sink, _, _, _ = pipeline()
    sink.on_snapshot(frame(3))
    sink.clear()
    assert not sink.on_snapshot(frame(2, text="Late"))
    assert manager.get_recent() == []


def test_new_session_allows_a_new_producer_to_restart_sequence():
    manager, owner, sink, _, _, _ = pipeline()
    sink.on_snapshot(frame(20, generation=8))
    fresh = owner.bind(owner.activate_session("another"))
    assert fresh.on_snapshot(frame())
    assert manager.get_recent()[0].generation == 0


def test_queued_replacement_purges_before_new_speech_and_rejects_old_output():
    manager, _, sink, said, tasks, purged = pipeline(queued=True)
    sink.on_snapshot(frame(text="Old"))
    sink.on_snapshot(frame(2, generation=1, text="New"))
    for task in tasks:
        task()
    assert said == ["New"] and len(purged) == 2
    assert manager.get_recent()[0].text == "New"


def test_pausing_purges_once_and_still_allows_manual_reading():
    manager, _, sink, said, _, purged = pipeline()
    sink.on_snapshot(frame())
    sink.on_snapshot(frame(2, paused=True))
    sink.on_snapshot(frame(3, paused=True))
    assert len(purged) == 2  # new timeline, then pause
    assert manager.read_current()
    assert said == ["Caption", "Caption"]


def test_serialized_snapshot_is_not_required_by_legacy_cue_callers():
    manager, _, _, said, _, _ = pipeline()
    manager.on_cue("Legacy producer", 1000, 2000)
    assert said == ["Legacy producer"]


def test_invalid_contract_never_modifies_existing_history():
    manager, _, sink, _, _, _ = pipeline()
    sink.on_snapshot(frame())
    with pytest.raises(TypeError):
        sink.on_snapshot({"text": "not a snapshot"})
    assert manager.get_recent()[0].text == "Caption"


def test_rewind_in_a_gap_does_not_retain_future_cues():
    manager, _, sink, said, _, _ = pipeline()
    source = TimedTextSource(CUES)
    sink.on_snapshot(source.sample(PlaybackPosition(5500)).snapshot)
    sink.on_snapshot(source.sample(PlaybackPosition(2500)).snapshot)
    assert manager.get_recent() == [] and not manager.read_current()
    assert said == ["Two"]


def test_backend_contract_has_no_mutable_status_aliases():
    snapshot = frame()
    paused = replace(snapshot, sequence=2, paused=True)
    assert snapshot.paused is False and paused.paused is True
