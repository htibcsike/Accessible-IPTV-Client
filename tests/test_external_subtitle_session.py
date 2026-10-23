import threading

import external_player
from external_player import ExternalPlayerLauncher
from subtitle_session import SubtitleSessionController
from subtitle_speech import SubtitleSpeechManager


def test_regular_mpv_ignores_stale_custom_path(monkeypatch):
    launcher = ExternalPlayerLauncher()
    selected = []
    monkeypatch.setattr(launcher, "_find_mpv_exe", lambda path: selected.append(path) or "mpv")
    ready = threading.Event()
    def spawn(*args):
        ready.set()
        return object()
    monkeypatch.setattr(external_player.MpvSubtitleAdapter, "launch", spawn)
    manager = SubtitleSpeechManager(lambda text: None)
    assert launcher.launch("MPV", "movie", "/custom/vlc.exe", subtitle_manager=manager)[0]
    assert ready.wait(1)
    assert selected == [""]


def test_custom_mpv_keeps_exact_executable(monkeypatch):
    launcher = ExternalPlayerLauncher()
    selected = []
    monkeypatch.setattr(launcher, "_find_mpv_exe", lambda path: selected.append(path) or path)
    ready = threading.Event()
    def spawn(*args):
        ready.set()
        return object()
    monkeypatch.setattr(external_player.MpvSubtitleAdapter, "launch", spawn)
    assert launcher.launch("Custom", "movie", "/Árvíz tűrő/mpv.exe",
                           subtitle_manager=SubtitleSpeechManager(lambda text: None))[0]
    assert ready.wait(1)
    assert selected == ["/Árvíz tűrő/mpv.exe"]


def test_auto_off_still_collects_and_duplicate_launch_keeps_owner(monkeypatch):
    launcher, spoken, producers = ExternalPlayerLauncher(), [], []
    manager = SubtitleSpeechManager(spoken.append)
    owner = SubtitleSessionController(manager)

    class Adapter:
        available = True
        def cancel(self):
            pass
        def close(self, terminate=True):
            pass

    ready = threading.Event()
    def launch(exe, url, sink, callback):
        producers.append(sink)
        sink.on_cue("Available on demand", 1000, 2000)
        ready.set()
        return Adapter()

    monkeypatch.setattr(external_player.MpvSubtitleAdapter, "launch", launch)
    monkeypatch.setattr(launcher, "_find_mpv_exe", lambda path: "mpv")
    assert launcher.launch("MPV", "movie", subtitle_session=owner)[0]
    token = owner.session_token
    assert ready.wait(1)
    assert manager.read_current()
    assert spoken == ["Available on demand"]
    assert launcher.launch("MPV", "movie", subtitle_session=owner)[0]
    assert owner.session_token == token
    assert len(producers) == 1
    owner.activate_session("built-in")
    producers[0].on_cue("Stale MPV")
    assert manager.get_recent() == []


def test_worker_cannot_fall_back_over_a_newer_launch(monkeypatch):
    launcher = ExternalPlayerLauncher()
    launched = []
    monkeypatch.setattr(launcher, '_spawn_posix', lambda argv: launched.append(argv) or (True, ''))
    monkeypatch.setattr(launcher, '_spawn_windows', lambda argv: launched.append(argv) or (True, ''))
    launcher.launch('VLC', 'new channel')
    assert launcher.launch('MPV', 'old channel', expected_generation=0) == (True, '')
    assert len(launched) == 1 and launched[0][-1] == 'new channel'


def test_late_owned_process_is_retired_when_builtin_session_takes_over(monkeypatch):
    launcher = ExternalPlayerLauncher()
    owner = SubtitleSessionController(SubtitleSpeechManager(lambda text: None))
    started, release, retired = threading.Event(), threading.Event(), threading.Event()
    class Adapter:
        available = True
        def cancel(self):
            pass
        def close(self, terminate=True):
            retired.set()
    def spawn(*args):
        started.set()
        assert release.wait(2)
        return Adapter()
    monkeypatch.setattr(external_player.MpvSubtitleAdapter, 'launch', spawn)
    monkeypatch.setattr(launcher, '_find_mpv_exe', lambda path: 'mpv')
    launcher.launch('MPV', 'old', subtitle_session=owner)
    try:
        assert started.wait(1)
        new = owner.activate_session('built-in')
        release.set()
        assert retired.wait(1)
        assert owner.is_current(new)
    finally:
        release.set()
