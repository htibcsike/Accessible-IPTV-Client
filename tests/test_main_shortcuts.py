"""Regression tests for main-window keyboard shortcut ownership."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

wx = pytest.importorskip("wx")

import main  # noqa: E402


def _shortcut_map():
    entries = main._main_window_accelerator_entries()
    shortcuts = {(modifiers, key): command_id
                 for modifiers, key, command_id in entries}
    assert len(shortcuts) == len(entries), "main-window shortcut collision"
    return shortcuts


def test_ctrl_shift_j_only_shows_the_built_in_player():
    shortcuts = _shortcut_map()
    ctrl_shift = wx.ACCEL_CTRL | wx.ACCEL_SHIFT

    assert shortcuts[(ctrl_shift, ord("J"))] == main._MAIN_ACCEL_SHOW_PLAYER_ID
    assert (ctrl_shift, ord("K")) not in shortcuts


def test_volume_uses_documented_ctrl_arrow_shortcuts():
    shortcuts = _shortcut_map()

    assert shortcuts[(wx.ACCEL_CTRL, wx.WXK_UP)] == 4015
    assert shortcuts[(wx.ACCEL_CTRL, wx.WXK_DOWN)] == 4016


def test_show_player_command_is_silent_without_loaded_media():
    class Client:
        ensured = False

        def _internal_player_has_media(self):
            return False

        def _ensure_internal_player(self):
            self.ensured = True
            raise AssertionError("an empty player must not be created")

    client = Client()
    main.IPTVClient._menu_show_player(client)

    assert client.ensured is False
