"""Execute production GUI methods with explicit wx/player substitutes.

These tests check the application wiring without claiming native wx,
Windows, COM, JAWS or NVDA coverage. The actual method bodies are compiled
from the source rather than reimplemented in the test.
"""
import ast
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from app_tts import SpeechResult
from external_player import ExternalPlayerLauncher
from subtitle_cues import Cue
import subtitle_cues
from subtitle_session import SubtitleSessionController
from subtitle_speech import SubtitleSpeechManager

ROOT = Path(__file__).resolve().parents[1]


def extract_class(filename, name, methods, namespace):
    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
    original = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)
    bodies = [node for node in original.body if isinstance(node, ast.FunctionDef) and node.name in methods]
    assert {node.name for node in bodies} == set(methods)
    cls = ast.ClassDef(name=name, bases=[], keywords=[], body=bodies, decorator_list=[])
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), cls], type_ignores=[])
    ast.fix_missing_locations(module)
    env = dict(namespace, LOG=logging.getLogger(__name__), _=lambda text: text)
    exec(compile(module, str(ROOT / filename), "exec"), env)
    return env[name], env


def app(methods):
    spoken, saved = [], []
    wx = SimpleNamespace(CallAfter=lambda fn, *args: fn(*args), OK=1, ICON_INFORMATION=2,
                         ICON_ERROR=4, ICON_WARNING=8, YES=10, NO=11, YES_NO=12,
                         ICON_QUESTION=16, ID_OK=20)
    cls, env = extract_class("main.py", "IPTVClient", methods, {
        "wx": wx, "live_announce": SimpleNamespace(speak=spoken.append),
        "save_config": lambda config: saved.append(dict(config)),
        "ExternalPlayerLauncher": ExternalPlayerLauncher, "SpeechResult": SpeechResult,
        "channel_http_headers": lambda channel: {},
        "InternalPlayerUnavailableError": RuntimeError,
        "message_box": lambda *args: None,
    })
    instance = cls()
    instance.config = {}
    instance._bool_pref = lambda value: value in (True, 1, "true", "yes")
    instance._app_tts = SimpleNamespace(stop=lambda: None)
    instance._subtitle_manager = SubtitleSpeechManager(spoken.append)
    instance._subtitle_session = SubtitleSessionController(instance._subtitle_manager)
    instance._builtin_subtitle_token = None
    return instance, spoken, saved, env


def test_toggle_from_either_window_saves_and_synchronizes_actual_speech():
    instance, spoken, saved, _ = app(["_on_player_speak_subtitles", "_on_toggle_subtitle_speech"])
    checks, player_checks = [], []
    instance._subtitle_toggle_item = SimpleNamespace(Check=checks.append)
    instance._internal_player_frame = SimpleNamespace(set_speak_subtitles=player_checks.append)
    instance._on_toggle_subtitle_speech()
    assert saved[-1]["speak_subtitles"] is True
    instance._subtitle_manager.on_cue("Enabled")
    assert spoken[-1] == "Enabled"
    instance._on_player_speak_subtitles(False)
    assert checks[-1] is False and player_checks[-1] is False
    assert saved[-1]["speak_subtitles"] is False
    instance._subtitle_manager.on_cue("Disabled")
    assert "Disabled" not in spoken


@pytest.mark.parametrize("policy", ["pause", "default"])
@pytest.mark.parametrize("result", [SpeechResult.UNAVAILABLE, SpeechResult.OUTPUT_MISSING, SpeechResult.FAILED])
def test_application_voice_failure_never_sends_caption_to_screen_reader(policy, result):
    instance, spoken, _, _ = app(["_speak_subtitle_cue", "_subtitle_backend"])
    instance.config.update(subtitle_speech_backend="app_tts", subtitle_app_device_policy=policy)
    instance._app_tts_failure_announced = False
    instance._app_tts = SimpleNamespace(available=False, last_result=result,
                                      speak=lambda text, device_policy: False)
    instance._speak_subtitle_cue("Private caption")
    instance._speak_subtitle_cue("Another caption")
    assert len(spoken) == 1
    assert all("caption" not in text for text in spoken)
    assert instance._subtitle_backend() == "app_tts"


def test_explicit_screen_reader_selection_still_speaks():
    instance, spoken, _, _ = app(["_speak_subtitle_cue", "_subtitle_backend"])
    instance._speak_subtitle_cue("Caption")
    assert spoken == ["Caption"]


def test_builtin_launch_registers_bound_sink_before_play():
    instance, _, _, env = app(["_launch_stream"])
    env["media_type"] = SimpleNamespace(channel_media_from_metadata=lambda channel: "video", MEDIA_AUDIO="audio")
    cls = type(instance)
    cls._single_stream_provider_has_recording = staticmethod(lambda self, url: False)
    instance.default_player = "Built-in Player"
    instance.show_player_on_enter = True
    calls = []

    class Frame:
        def set_subtitle_sink(self, sink):
            self.sink = sink
        def Enable(self, value):
            pass
        def Show(self):
            pass
        def Raise(self):
            pass
        def SetFocus(self):
            pass
        def play(self, url, title, **kwargs):
            self.sink.on_cue("From built-in", 1000, 2000, track="file")
            calls.append((url, title))
    frame = Frame()
    instance._ensure_internal_player = lambda: frame
    instance._channel_audio_key = lambda channel: "channel"
    instance._remember_played_channel = lambda channel: None
    instance._sync_internal_player_record_state = lambda: None
    errors = []
    env["message_box"] = lambda *args: errors.append(args)
    instance._launch_stream("test.mkv", "Title")
    assert not errors
    assert calls == [("test.mkv", "Title")]
    assert instance._subtitle_session.is_current(instance._builtin_subtitle_token)
    assert instance._subtitle_manager.get_recent()[0].text == "From built-in"


def player():
    cls, env = extract_class("internal_player.py", "InternalPlayerFrame", [
        "_on_cue_timer", "_set_subtitle_cues", "_subtitle_review_text",
        "_read_current_subtitle", "_review_subtitle", "set_subtitle_sink",
        "_select_subtitle", "_on_subtitle_cues_loaded"], {
            "subtitle_cues": subtitle_cues, "live_announce": SimpleNamespace(speak=lambda text: None)})
    frame = cls()
    frame._destroyed = False
    frame._is_paused = False
    frame._speak_subtitles = True
    frame._subtitle_generation = 0
    frame._on_cue_cb = None
    frame._subtitle_prior_track_ids = {1}
    frame._cue_timer = SimpleNamespace(Start=lambda ms: None, Stop=lambda: None)
    labels, speech = [], []
    frame.subtitle_label = SimpleNamespace(SetLabel=labels.append)
    state = {"time": 1500, "spu": 2}
    def select(track):
        state["spu"] = track
        return 0
    frame.player = SimpleNamespace(get_time=lambda: state["time"], video_get_spu=lambda: state["spu"],
                                   video_get_spu_delay=lambda: 0, video_set_spu=select)
    frame._subtitle_tracks = lambda: [(1, "embedded"), (2, "file")]
    frame._update_status_label = lambda *args, **kwargs: None
    manager = SubtitleSpeechManager(speech.append)
    manager.set_auto_speech(True)
    owner = SubtitleSessionController(manager)
    frame.set_subtitle_sink(owner.bind(owner.activate_session("builtin-file")))
    frame._set_subtitle_cues([Cue(1000, 2000, "One"), Cue(3000, 4000, "Two")])
    frame._subtitle_source_id = "file:///subtitles.srt"
    frame._subtitle_file_track = None
    return frame, state, manager, speech, labels


def test_builtin_timer_emits_real_timestamps_and_selected_file_identity():
    frame, _, manager, speech, _ = player()
    frame._on_cue_timer()
    cue = manager.get_recent()[0]
    assert (cue.text, cue.start_ms, cue.end_ms, cue.track) == ("One", 1000, 2000, "file:///subtitles.srt")
    assert speech == ["One"]


def test_paused_builtin_and_manual_review_use_chosen_backend():
    frame, _, _, speech, _ = player()
    frame._is_paused = True
    frame._on_cue_timer()
    assert speech == []
    frame._read_current_subtitle()
    assert speech == ["One"]


def test_builtin_gap_and_backward_seek_cannot_expose_future_cues():
    frame, state, manager, _, labels = player()
    frame._on_cue_timer()
    state["time"] = 3500
    frame._on_cue_timer()
    state["time"] = 4500
    frame._on_cue_timer()
    assert not manager.read_current() and labels[-1] == ""
    state["time"] = 2500
    frame._on_cue_timer()
    assert manager.get_recent() == []
    assert frame._subtitle_review_text(0) == "Last subtitle: One"
    assert frame._subtitle_review_text(1) == "No later subtitle."


def test_switch_to_embedded_track_drops_old_file_and_pending_parser():
    frame, state, manager, speech, _ = player()
    frame._on_cue_timer()
    generation = frame._subtitle_generation
    frame._select_subtitle(1)
    frame._on_subtitle_cues_loaded(generation, [Cue(1000, 4000, "Stale")])
    frame._on_cue_timer()
    assert state["spu"] == 1
    assert frame._subtitle_cues == [] and manager.get_recent() == []
    assert speech == ["One"]


def test_asynchronous_file_selection_does_not_bind_old_embedded_track():
    frame, state, manager, speech, _ = player()
    state["spu"] = 1
    frame._on_cue_timer()
    assert speech == [] and manager.get_recent() == []
    state["spu"] = 2
    frame._on_cue_timer()
    assert speech == ["One"]


@pytest.mark.parametrize("preview_ok", [True, False])
def test_output_preview_decline_or_failure_restores_default(preview_ok):
    instance, _, saved, env = app(["_choose_app_tts_output"])
    output = SimpleNamespace(id="headphones-id", name="Headphones")
    actions = []
    instance._app_tts = SimpleNamespace(
        available=True, selected_output="", list_output_devices=lambda: [output],
        set_output=lambda target: actions.append(("set", target)) or True,
        reset_output=lambda: actions.append(("reset", "")) or True,
        speak=lambda text: preview_ok, stop=lambda: None)
    wx = env["wx"]
    wx.SingleChoiceDialog = lambda *args: SimpleNamespace(
        SetSelection=lambda index: None, ShowModal=lambda: wx.ID_OK,
        GetSelection=lambda: 1, Destroy=lambda: None)
    env["message_box"] = lambda *args: wx.NO
    instance._choose_app_tts_output()
    assert actions == [("set", "headphones-id"), ("reset", "")]
    assert saved == []
    assert not instance._subtitle_output_preview


def test_close_callback_from_an_old_frame_does_not_cancel_current_owner():
    instance, _, _, _env = app(['_on_internal_player_closed'])
    current_frame = object()
    instance._internal_player_frame = current_frame
    token = instance._subtitle_session.activate_session('MPV')
    instance._on_internal_player_closed(object())
    assert instance._internal_player_frame is current_frame
    assert instance._subtitle_session.is_current(token)


def test_builtin_unknown_clock_and_negative_delay_do_not_speak_a_future_cue():
    frame, state, manager, speech, labels = player()
    state["time"] = -1
    frame.player.video_get_spu_delay = lambda: -2_000_000
    frame._on_cue_timer()
    assert speech == [] and manager.get_recent() == []
    assert not labels[-1]


def test_builtin_pause_and_rewind_use_the_common_snapshot_boundary():
    frame, state, manager, speech, _ = player()
    frame._on_cue_timer()
    assert speech == ["One"]
    frame._is_paused = True
    state["time"] = 3500
    frame._on_cue_timer()
    assert speech == ["One"]
    assert manager.read_current()
    assert speech == ["One", "Two"]
    frame._is_paused = False
    state["time"] = 1500
    frame._on_cue_timer()
    assert speech[-1] == "One"
    assert [c.text for c in manager.get_recent()] == ["One"]
