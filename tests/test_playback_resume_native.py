"""Opt-in real libVLC start-time smoke test; no provider or physical audio."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


def test_libvlc_honours_start_time_on_a_generated_mp4(tmp_path):
    if os.environ.get('IPTV_RUN_NATIVE_RESUME_TEST') != '1':
        pytest.skip('set IPTV_RUN_NATIVE_RESUME_TEST=1 with libVLC/FFmpeg installed')
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        pytest.skip('FFmpeg is unavailable')
    movie = tmp_path / 'Folytatás próba.mp4'
    subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=25',
                    '-t', '8', '-c:v', 'mpeg4', '-an', str(movie)], check=True, timeout=20)
    probe = r'''
import sys, time, vlc
instance = vlc.Instance('--no-audio', '--vout=dummy', '--no-video-title-show', '--no-xlib')
assert instance is not None
player = instance.media_player_new()
media = instance.media_new(sys.argv[1])
media.add_option(':start-time=3.000')
player.set_media(media)
assert player.play() != -1
limit = time.monotonic() + 8
observed = None
while time.monotonic() < limit:
    position = player.get_time()
    if player.get_state() == vlc.State.Playing and position >= 3000:
        observed = position
        break
    time.sleep(0.05)
player.stop()
player.release()
media.release()
instance.release()
assert observed is not None and 3000 <= observed < 5500, observed
print(observed)
'''
    result = subprocess.run([sys.executable, '-c', probe, str(Path(movie))], capture_output=True,
                            text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
