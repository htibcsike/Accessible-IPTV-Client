"""Private MPV snapshot protocol, cancellation, transport and live integration."""
import json
import shutil
import socket
import subprocess
import threading
import time

import pytest

import mpv_subtitle_adapter as module
from mpv_subtitle_adapter import MpvSubtitleAdapter, _Transport, _session_endpoint
from subtitle_speech import SubtitleSpeechManager


def adapter():
    spoken, states = [], []
    manager = SubtitleSpeechManager(spoken.append)
    manager.set_auto_speech(True)
    return MpvSubtitleAdapter(manager, states.append), manager, spoken, states


def snapshot(ad, serial, text, start=1, end=2, **changes):
    data = dict(protocol=1, serial=serial, epoch=0, active=True, paused=False,
                text=text, start=start, finish=end, track="1")
    data.update(changes)
    ad._dispatch(json.dumps({"event": "client-message", "args": [
        "iptvclient-subtitle-snapshot", json.dumps(data)]}).encode())


def test_identical_consecutive_cues_keep_independent_times():
    ad, manager, spoken, states = adapter()
    snapshot(ad, 1, "Yes.", 1, 2)
    first = manager.get_recent()[0]
    snapshot(ad, 2, "Yes.", 5, 6)
    assert spoken == ["Yes.", "Yes."]
    assert [(c.start_ms, c.end_ms) for c in manager.get_recent()] == [(1000, 2000), (5000, 6000)]
    assert first.start_ms == 1000
    assert states == ["first_cue"]


def test_different_text_and_duplicate_snapshots():
    ad, manager, spoken, _ = adapter()
    snapshot(ad, 1, "First", 1, 2)
    snapshot(ad, 2, "Second", 5, 6)
    snapshot(ad, 3, "Second", 5, 6)
    snapshot(ad, 2, "Late old", 1, 2)
    assert spoken == ["First", "Second"]
    assert [c.text for c in manager.get_recent()] == ["First", "Second"]


@pytest.mark.parametrize("change", [{"epoch": 1}, {"track": "2"}, {"active": False}])
def test_media_track_seek_and_stop_boundaries_clear_history(change):
    ad, manager, _, _ = adapter()
    snapshot(ad, 1, "Old")
    snapshot(ad, 2, "", **change)
    assert not manager.read_current()
    if change.get("active") is False:
        # Production Lua also increments epoch for end-file.
        snapshot(ad, 3, "", active=False, epoch=1)
    assert manager.get_recent() == []


def test_gap_is_not_a_current_cue_but_can_be_reviewed():
    ad, manager, spoken, _ = adapter()
    snapshot(ad, 1, "Visible")
    snapshot(ad, 2, "")
    assert not manager.read_current()
    assert manager.read_previous()
    assert spoken == ["Visible", "Visible"]


def test_paused_or_auto_off_collects_for_manual_review():
    ad, manager, spoken, _ = adapter()
    snapshot(ad, 1, "Paused", paused=True)
    assert spoken == []
    assert manager.read_current()
    manager.set_auto_speech(False)
    snapshot(ad, 2, "Auto off", 3, 4, paused=False)
    assert manager.read_current()
    assert spoken == ["Paused", "Auto off"]


def test_bitmap_status_once_and_no_words():
    ad, manager, spoken, states = adapter()
    snapshot(ad, 1, "Not text", image=True)
    snapshot(ad, 2, "Not text", image=True)
    assert spoken == []
    assert states == ["bitmap"]
    assert manager.get_capability("MPV", "timed_cues") == "unavailable"


@pytest.mark.parametrize("value", [None, "bad", float("nan"), float("inf"), True])
def test_unavailable_or_invalid_timing_is_safe(value):
    ad, manager, spoken, _ = adapter()
    snapshot(ad, 1, "Untimed", value, value)
    assert spoken == ["Untimed"]
    assert manager.get_recent()[0].start_ms is None


def test_malformed_and_foreign_messages_are_ignored():
    ad, manager, spoken, _ = adapter()
    for message in (b"not json", b"[]", b'{"request_id": []}',
                    b'{"event":"client-message","args":["other","{}"]}'):
        ad._dispatch(message)
    snapshot(ad, 1, 123)
    snapshot(ad, 2, "Missing schema", protocol=3)
    assert spoken == [] and manager.get_recent() == []


def test_matching_concurrent_responses_are_read_only_by_reader():
    ad, _, _, _ = adapter()
    sent, results = [], {}
    condition = threading.Condition()

    def send(message):
        with condition:
            sent.append(message)
            condition.notify_all()
        return True

    ad._send = send
    workers = [threading.Thread(target=lambda n=n: results.update(
        {n: ad._request([n], timeout=2)})) for n in ("one", "two")]
    for worker in workers:
        worker.start()
    with condition:
        assert condition.wait_for(lambda: len(sent) == 2, timeout=1)
    for message in reversed(sent):
        ad._dispatch(json.dumps({"request_id": message["request_id"],
                                 "error": "success", "data": message["command"][0]}).encode())
    for worker in workers:
        worker.join(1)
    assert results["one"]["data"] == "one"
    assert results["two"]["data"] == "two"
    assert ad._pending == {}


def test_cancellation_wakes_waiters_and_rejects_late_reply():
    ad, _, _, _ = adapter()
    sent, started, result = [], threading.Event(), []
    def send(message):
        sent.append(message)
        started.set()
        return True
    ad._send = send
    worker = threading.Thread(target=lambda: result.append(ad._request(["x"], timeout=10)))
    worker.start()
    assert started.wait(1)
    ad.cancel()
    ad._dispatch(json.dumps({"request_id": sent[0]["request_id"], "error": "success"}).encode())
    worker.join(0.5)
    assert not worker.is_alive()
    assert result == [None] and ad._pending == {}


def test_request_timeout_retires_pending_entry():
    ad, _, _, _ = adapter()
    ad._send = lambda message: True
    start = time.monotonic()
    assert ad._request(["x"], timeout=0.05) is None
    assert time.monotonic() - start < 0.5
    assert ad._pending == {}


@pytest.mark.skipif(module._IS_WINDOWS, reason="POSIX socket branch")
def test_fragmented_transport_silent_peer_deadline_and_eof():
    client, server = socket.socketpair()
    transport = _Transport("unused")
    transport._sock = client
    try:
        server.sendall(b'{"partial":')
        assert transport.read_line(time.monotonic() + 0.06) is None
        server.sendall(b'1}\nnext\n')
        assert transport.read_line(time.monotonic() + 1) == b'{"partial":1}'
        assert transport.read_line(time.monotonic() + 1) == b"next"
        server.close()
        assert transport.read_line(time.monotonic() + 1) is None
    finally:
        transport.close()
        server.close()


def test_failed_handshake_does_not_kill_or_duplicate_player(monkeypatch):
    launched, terminated, states = [], [], []
    done = threading.Event()
    class Process:
        def __init__(self, argv):
            launched.append(argv)
        def poll(self):
            return None
        def terminate(self):
            terminated.append(True)
        def wait(self, timeout):
            return 0
    monkeypatch.setattr(module.subprocess, "Popen", Process)
    monkeypatch.setattr(module._Transport, "connect", lambda self, **kwargs: False)
    manager = SubtitleSpeechManager(lambda text: None)
    def state(value):
        states.append(value)
        done.set()
    ad = MpvSubtitleAdapter.launch("mpv", "test.mkv", manager, state)
    assert ad is not None
    assert done.wait(1)
    ad._initializer.join(2)
    assert launched and len(launched) == 1
    assert terminated == []
    assert states == ["unavailable"]
    ad.close()
    assert terminated == [True]


def test_launch_does_not_wait_for_connection(monkeypatch):
    connecting, release = threading.Event(), threading.Event()
    class Process:
        def __init__(self, argv):
            pass
        def poll(self):
            return 0
    def connect(transport, **kwargs):
        connecting.set()
        release.wait(1)
        return False
    monkeypatch.setattr(module.subprocess, "Popen", Process)
    monkeypatch.setattr(module._Transport, "connect", connect)
    ad = MpvSubtitleAdapter.launch("mpv", "test.mkv", SubtitleSpeechManager(lambda text: None))
    try:
        assert connecting.wait(0.5)
        assert not release.is_set()  # launch returned while setup was waiting
    finally:
        ad.cancel()
        release.set()
        ad.close()


def test_endpoints_unique():
    assert _session_endpoint() != _session_endpoint()


mpv_exe, ffmpeg_exe = shutil.which("mpv"), shutil.which("ffmpeg")


@pytest.mark.skipif(not mpv_exe or not ffmpeg_exe, reason="real mpv and ffmpeg required")
def test_live_mpv_delivers_identical_cues_and_accepts_on_demand(tmp_path):
    if not module._IS_WINDOWS:
        try:
            probe = socket.socket(socket.AF_UNIX)
        except PermissionError:
            pytest.skip("host denies AF_UNIX sockets; full IPC check requires an unrestricted runner")
        else:
            probe.close()
    clip = tmp_path / "video.mp4"
    subprocess.run([ffmpeg_exe, "-y", "-v", "error", "-f", "lavfi",
                    "-i", "color=black:duration=7:size=160x120:rate=10",
                    "-pix_fmt", "yuv420p", str(clip)], check=True, timeout=30)
    srt = tmp_path / "video.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nYes.\n\n"
                   "2\n00:00:03,000 --> 00:00:04,000\nYes.\n\n"
                   "3\n00:00:05,000 --> 00:00:06,000\nNext.\n", encoding="utf-8")
    spoken, states = [], []
    manager = SubtitleSpeechManager(spoken.append)
    ad = MpvSubtitleAdapter.launch(mpv_exe, str(clip), manager, states.append,
        extra_args=["--no-config", "--vo=null", "--ao=null", f"--sub-file={srt}", "--sid=1"])
    assert ad is not None
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and len(manager.get_recent()) < 3:
            time.sleep(0.05)
        assert [c.text for c in manager.get_recent()] == ["Yes.", "Yes.", "Next."]
        assert [c.start_ms for c in manager.get_recent()] == [1000, 3000, 5000]
        assert spoken == []  # collection does not require automatic speech
        assert manager.read_current()
        assert spoken == ["Next."]
        assert "available" in states and "first_cue" in states
    finally:
        ad.close()
    assert not ad.available


@pytest.mark.skipif(not mpv_exe or not ffmpeg_exe, reason="real mpv and ffmpeg required")
def test_live_mpv_helper_emits_complete_cues_without_a_network_listener(tmp_path):
    """Run the production Lua helper in MPV, even on hosts that deny sockets.

    A second script-message listener records the same emitted JSON to stdout;
    it does not replace or mock MPV's property observations or commandv.
    """
    from mpv_subtitle_script import SCRIPT
    clip = tmp_path / "video.mp4"
    subprocess.run([ffmpeg_exe, "-y", "-v", "error", "-f", "lavfi",
                    "-i", "color=black:duration=7:size=160x120:rate=10",
                    "-pix_fmt", "yuv420p", str(clip)], check=True, timeout=30)
    srt = tmp_path / "video.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nYes.\n\n"
                   "2\n00:00:03,000 --> 00:00:04,000\nYes.\n\n"
                   "3\n00:00:05,000 --> 00:00:06,000\nNext.\n", encoding="utf-8")
    helper = tmp_path / "subtitle_test.lua"
    helper.write_text(SCRIPT + "\n" + """
mp.register_script_message('iptvclient-subtitle-snapshot', function(payload)
    mp.msg.info('TEST-SNAPSHOT ' .. payload)
end)
""", encoding="utf-8")
    run = subprocess.run([mpv_exe, "--no-config", "--vo=null", "--ao=null",
                          "--input-terminal=no", "--msg-level=all=warn,subtitle_test=info",
                          f"--script={helper}", f"--sub-file={srt}", "--sid=1", str(clip)],
                         capture_output=True, text=True, timeout=20)
    output = run.stdout + run.stderr
    assert run.returncode == 0, output
    assert "Lua error" not in output, output
    snapshots = [json.loads(line.split("TEST-SNAPSHOT ", 1)[1])
                 for line in output.splitlines() if "TEST-SNAPSHOT " in line]
    cues = [s for s in snapshots if s.get("text")]
    # Several identical snapshots are harmless; serial order and cue identity
    # are interpreted by the same Python adapter as the IPC reader uses.
    ad, manager, spoken, _ = adapter()
    for data in snapshots:
        ad._dispatch(json.dumps({"event": "client-message", "args": [
            "iptvclient-subtitle-snapshot", json.dumps(data)]}).encode())
    assert spoken == ["Yes.", "Yes.", "Next."], output
    assert {(s["text"], s["start"], s["finish"]) for s in cues} == {
        ("Yes.", 1, 2), ("Yes.", 3, 4), ("Next.", 5, 6)}


def test_first_cue_is_queued_after_status_so_status_cannot_interrupt_it():
    output, queued = [], []
    manager = SubtitleSpeechManager(output.append, ui_thread=queued.append)
    manager.set_auto_speech(True)
    ad = MpvSubtitleAdapter(manager, lambda state: queued.append(lambda: output.append(state)))
    snapshot(ad, 1, "The first subtitle")
    for callback in queued:
        callback()
    assert output == ["first_cue", "The first subtitle"]


def test_slow_version_reply_never_gates_real_helper_handshake(monkeypatch):
    import queue
    wire, ready = queue.Queue(), threading.Event()

    class Process:
        def __init__(self, argv):
            pass
        def poll(self):
            return 0

    def read_line(transport, deadline=None):
        while not transport._stop.is_set():
            try:
                return wire.get(timeout=0.02)
            except queue.Empty:
                pass
        return None

    def write_line(transport, line):
        request = json.loads(line)
        if request['command'][0] == 'get_property':
            return True  # deliberately never answer the version request
        wire.put(json.dumps({'request_id': request['request_id'], 'error': 'success'}).encode())
        data = dict(protocol=1, serial=1, epoch=0, active=True, paused=False,
                    text='', track='1')
        wire.put(json.dumps({'event': 'client-message', 'args': [
            'iptvclient-subtitle-snapshot', json.dumps(data)]}).encode())
        return True

    monkeypatch.setattr(module.subprocess, 'Popen', Process)
    monkeypatch.setattr(module._Transport, 'connect', lambda self, **kwargs: True)
    monkeypatch.setattr(module._Transport, 'read_line', read_line)
    monkeypatch.setattr(module._Transport, 'write_line', write_line)
    ad = MpvSubtitleAdapter.launch('mpv', 'file', SubtitleSpeechManager(lambda text: None),
                                  lambda state: ready.set() if state == 'available' else None)
    try:
        assert ready.wait(1), 'version response blocked usable subtitle collection'
        assert ad.available and ad._mpv_version == ''
    finally:
        ad.close()


def test_playback_only_fallback_is_owned_and_stopped_on_close(monkeypatch):
    processes = []
    class Process:
        def __init__(self, argv):
            self.argv, self.terminated = argv, False
            processes.append(self)
        def poll(self):
            return None
        def terminate(self):
            self.terminated = True
        def wait(self, timeout):
            return 0
    monkeypatch.setattr(module.subprocess, 'Popen', Process)
    manager = SubtitleSpeechManager(lambda text: None)
    states = []
    ad = MpvSubtitleAdapter.launch_playback_only('mpv', 'file', manager, states.append)
    assert ad is not None and states == ['unavailable']
    assert not ad.available
    assert not any(arg.startswith('--input-ipc-server=') for arg in processes[0].argv)
    assert manager.get_capability('MPV', 'timed_cues') == 'unavailable'
    ad.close()
    assert processes[0].terminated
