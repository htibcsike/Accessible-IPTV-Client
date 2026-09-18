"""Live casting against the one receiver used for testing: R&B Room.

Skipped unless IPTV_RUN_LIVE_CAST_TESTS=1. Never aim these at any other
device: R&B Room (Cast name "RB Room") is the only one tests may touch.
"""

import logging
import os
import time

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("IPTV_RUN_LIVE_CAST_TESTS") != "1",
    reason="live cast test; set IPTV_RUN_LIVE_CAST_TESTS=1 to run",
)

logging.basicConfig(level=logging.INFO)

TARGET_NAMES = ("rb room", "r&b room")
# A public HLS test stream: no provider account involved.
HLS_URL = "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8"
RADIO_URL = "https://radio.serrebiradio.com/listen/serrebiradio/SerrebiRadio"


def _target(devices, kind):
    for device in devices:
        if device.kind == kind and device.name.lower() in TARGET_NAMES:
            return device
    return None


@pytest.fixture(scope="module")
def manager():
    import casting
    mgr = casting.CastingManager()
    mgr.start()
    yield mgr
    mgr.disconnect()
    mgr.stop()


@pytest.fixture(scope="module")
def devices(manager):
    found = manager.discover_all()
    logging.info("Discovered: %s", [d.display_name for d in found])
    return found


def test_chromecast_plays_hls(manager, devices):
    device = _target(devices, "chromecast")
    if device is None:
        pytest.skip("RB Room is not on the network as a Cast device")
    manager.connect(device)
    manager.play(HLS_URL, "Cast test")
    time.sleep(8)
    status = manager._cast.media_controller.status
    assert status.player_state in ("PLAYING", "BUFFERING")
    manager.stop_playback()


def test_airplay_plays_radio(manager, devices):
    device = _target(devices, "airplay")
    if device is None:
        pytest.skip("R&B Room is not on the network as an AirPlay device")
    manager.connect(device)
    manager.play(RADIO_URL, "AirPlay test")
    time.sleep(10)
    manager.stop_playback()
