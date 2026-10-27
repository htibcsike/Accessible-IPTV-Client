import pytest
import wx

import shortcuts


def test_shortcut_override_replaces_default_and_rejects_conflicts():
    config = {}
    shortcuts.set_shortcut(config, "main", "previous_channel", "Ctrl+Shift+0")
    entries = shortcuts.main_entries(config)
    assert (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("0"), 4022) in entries
    assert (wx.ACCEL_CTRL, ord("0"), 4022) not in entries
    with pytest.raises(ValueError, match="conflicts with Previous Channel"):
        shortcuts.set_shortcut(config, "main", "channel_number", "Ctrl+Shift+0")
    with pytest.raises(ValueError, match="Ctrl or Alt"):
        shortcuts.set_shortcut(config, "main", "channel_number", "G")


def test_every_command_has_a_conflict_label():
    assert shortcuts.LABELS["main"].keys() == shortcuts.MAIN.keys()
    assert shortcuts.LABELS["player"].keys() == shortcuts.PLAYER.keys()


def test_a_hand_edited_config_cannot_install_a_bare_main_shortcut():
    """The config file is the user's, and a hand-edited entry is read too.

    A main-window shortcut without Ctrl or Alt would swallow ordinary typing
    in the search box, and F1 is the help key. Both fall back to the default.
    """
    config = {"shortcuts": {"main.favorite": "F", "main.exit": "F1"}}

    entries = shortcuts.main_entries(config)

    assert (wx.ACCEL_CTRL, ord("D"), 4019) in entries  # the default Ctrl+D
    assert not [e for e in entries if e[1] == ord("F") and not e[0]]
    assert (wx.ACCEL_CTRL, ord("Q"), 4004) in entries  # the default Ctrl+Q
    assert not [e for e in entries if e[1] == wx.WXK_F1]


def test_a_player_shortcut_may_stay_bare():
    """The player's own keys are single keys on purpose."""
    config = {"shortcuts": {"player.audio_track": "A"}}

    assert shortcuts.effective(config, "player")["audio_track"] == "A"


def test_searchable_commands_include_every_binding_and_use_current_keys_and_language():
    config = {}
    rows = shortcuts.searchable_commands(config)
    assert {(context, action) for context, action, _, _ in rows} == {
        *(("main", action) for action in shortcuts.MAIN),
        *(("player", action) for action in shortcuts.PLAYER),
    }
    shortcuts.set_shortcut(config, 'player', 'fullscreen', 'Ctrl+F11')
    rows = shortcuts.searchable_commands(config, 'CTRL+F11')
    assert [(context, action) for context, action, _, _ in rows] == [('player', 'fullscreen')]
    translated = shortcuts.searchable_commands(config, 'felirat', translate=lambda text: {
        'Subtitles': 'Feliratok', 'Built-in Player': 'Beépített lejátszó'}.get(text, text))
    assert any(action == 'subtitles' and 'Beépített lejátszó' in label
               for _, action, _, label in translated)
    assert shortcuts.searchable_commands(config, 'no such command xyz') == []


def test_actual_editor_search_selects_the_correct_action_and_validates_the_new_key():
    from types import SimpleNamespace
    from tests.test_subtitle_integration import extract_class
    calls, saved = [], []
    class TextDialog:
        def __init__(self, *args):
            self.value = 'Read Current Subtitle' if not calls else 'Ctrl+Alt+Z'
            calls.append(args)
        def ShowModal(self): return 1
        def GetValue(self): return self.value
        def Destroy(self): pass
    class Choice:
        def __init__(self, parent, prompt, title, labels):
            assert len(labels) == 1 and 'Read Current Subtitle' in labels[0]
        def ShowModal(self): return 1
        def GetSelection(self): return 0
        def Destroy(self): pass
    wx_stub = SimpleNamespace(TextEntryDialog=TextDialog, SingleChoiceDialog=Choice, ID_OK=1,
                              OK=2, ICON_INFORMATION=4, ICON_WARNING=8)
    cls, _ = extract_class('main.py', 'IPTVClient', ['_customize_shortcuts'], {
        'wx': wx_stub, 'shortcuts': shortcuts,
        'user_guide': SimpleNamespace(set_help_topic=lambda *args: None),
        'save_config': lambda config: saved.append(dict(config)),
        'message_box': lambda *args: None,
    })
    instance = cls()
    instance.config = {}
    instance._customize_shortcuts()
    assert saved
    assert shortcuts.effective(instance.config, 'player')['read_subtitle'] == shortcuts.parse('Ctrl+Alt+Z')[2]
