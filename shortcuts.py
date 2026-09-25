"""Validated keyboard shortcuts shared by the main window and player."""

import wx
from i18n import gettext as _

MAIN = {
    "playlist_manager": ("Ctrl+M", 4001),
    "epg_manager": ("Ctrl+E", 4002),
    "import_epg": ("Ctrl+I", 4003),
    "exit": ("Ctrl+Q", 4004),
    "play_pause": ("Ctrl+Shift+P", 4010),
    "stop": ("Ctrl+Shift+S", 4011),
    "cast": ("Ctrl+Shift+C", 4012),
    "volume_up": ("Ctrl+Up", 4015),
    "volume_down": ("Ctrl+Down", 4016),
    "record": ("Ctrl+Shift+R", 4017),
    "account": ("Ctrl+Shift+A", 4018),
    "favorite": ("Ctrl+D", 4019),
    "downloads": ("Ctrl+Shift+D", 4020),
    "show_player": ("Ctrl+Shift+J", 4021),
    "previous_channel": ("Ctrl+0", 4022),
    "channel_number": ("Ctrl+G", 4023),
    "recent_channels": ("Ctrl+H", 4024),
    "whats_on_now": ("Ctrl+W", 4025),
    "what_is_playing": ("Ctrl+Shift+I", 4026),
}

PLAYER = {
    "play_pause": "Ctrl+P",
    "stop": "Ctrl+S",
    "record": "Ctrl+R",
    "cast": "Ctrl+C",
    "volume_up": "Up",
    "volume_down": "Down",
    "audio_track": "A",
    "subtitles": "S",
    "fullscreen": "F11",
    "hide": "Ctrl+W",
    "exit": "Ctrl+Q",
    "what_is_playing": "I",
}


def parse(value: str):
    entry = wx.AcceleratorEntry()
    if not isinstance(value, str) or not entry.FromString(value.strip()):
        raise ValueError(_("Invalid keyboard shortcut."))
    return entry.GetFlags(), entry.GetKeyCode(), entry.ToString()


def effective(config: dict, context: str) -> dict:
    defaults = MAIN if context == "main" else PLAYER
    saved = config.get("shortcuts") if isinstance(config, dict) else {}
    saved = saved if isinstance(saved, dict) else {}
    result = {}
    for action, spec in defaults.items():
        default = spec[0] if context == "main" else spec
        override = saved.get(context + "." + action)
        try:
            result[action] = parse(override)[2] if override else default
        except ValueError:
            result[action] = default
    return result


def set_shortcut(config: dict, context: str, action: str, value: str) -> None:
    defaults = MAIN if context == "main" else PLAYER
    if action not in defaults:
        raise ValueError(_("Unknown command."))
    default = defaults[action][0] if context == "main" else defaults[action]
    value = parse(value)[2] if value.strip() else default
    flags, key, _label = parse(value)
    if context == "main" and not flags & (wx.ACCEL_CTRL | wx.ACCEL_ALT):
        raise ValueError(_("Main-window shortcuts need Ctrl or Alt."))
    if key == wx.WXK_F1:
        raise ValueError(_("F1 is reserved for Help."))
    current = effective(config, context)
    for other, existing in current.items():
        if other != action and parse(existing)[:2] == (flags, key):
            raise ValueError(_("Shortcut conflicts with {command}.").format(command=other.replace("_", " ")))
    saved = config.get("shortcuts")
    saved = dict(saved) if isinstance(saved, dict) else {}
    key_name = context + "." + action
    if value == default:
        saved.pop(key_name, None)
    else:
        saved[key_name] = value
    config["shortcuts"] = saved


def main_entries(config: dict):
    keys = effective(config, "main")
    return [(*parse(keys[action])[:2], command_id)
            for action, (_default, command_id) in MAIN.items()]
