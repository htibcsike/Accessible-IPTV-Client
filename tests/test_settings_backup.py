import pytest

import settings_backup


def test_encrypted_backup_round_trip_and_wrong_password(tmp_path):
    path = tmp_path / "settings.aiptv"
    config = {"playlists": [{"url": "https://user:secret@example.test/list"}],
              "epgs": [], "favorites": ["BBC"]}
    settings_backup.export_settings(str(path), config, "long secret phrase")
    assert b"secret@example" not in path.read_bytes()
    assert settings_backup.import_settings(str(path), "long secret phrase") == config
    with pytest.raises(ValueError, match="Wrong password"):
        settings_backup.import_settings(str(path), "wrong")
