import types

import main


def test_recent_channels_are_persistent_and_previous_channel_toggles(monkeypatch):
    a = {"name": "A", "tvg-id": "a"}
    b = {"name": "B", "tvg-id": "b"}
    frame = types.SimpleNamespace(config={}, all_channels=[a, b], recent_channel_keys=[])
    monkeypatch.setattr(main, "save_config", lambda _config: None)
    main.IPTVClient._remember_played_channel(frame, a)
    main.IPTVClient._remember_played_channel(frame, b)
    assert frame.config["recent_channels"] == frame.recent_channel_keys
    assert main.IPTVClient._recent_channels(frame) == [b, a]
    frame._recent_channels = lambda: main.IPTVClient._recent_channels(frame)
    played = []
    frame._play_live_channel = played.append
    main.IPTVClient._play_previous_channel(frame)
    assert played == [a]
