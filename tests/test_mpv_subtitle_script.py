"""Execute the actual embedded Lua helper with MPV's API replaced locally."""
import itertools
import json

import pytest

from mpv_subtitle_adapter import MpvSubtitleAdapter
from mpv_subtitle_script import SCRIPT
from subtitle_speech import SubtitleSpeechManager

lupa = pytest.importorskip("lupa")


def harness():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    spoken, messages = [], []
    manager = SubtitleSpeechManager(spoken.append)
    manager.set_auto_speech(True)
    adapter = MpvSubtitleAdapter(manager)

    def format_json(table):
        return json.dumps(dict(table.items())), None

    def command(*args):
        messages.append(args)
        adapter._dispatch(json.dumps({"event": "client-message", "args": list(args[1:])}).encode())

    lua.globals().encode = format_json
    lua.globals().command = command
    lua.execute('''
        props = {['idle-active'] = false, sid = 1, pause = false,
                 ['sub-visibility'] = true, ['track-list'] = {}}
        observers, events, requests = {}, {}, {}
        local mp = {}
        function mp.get_property_native(name, default)
            if props[name] == nil then return default end
            return props[name]
        end
        function mp.observe_property(name, kind, fn) observers[name] = fn end
        function mp.register_event(name, fn) events[name] = fn end
        function mp.register_script_message(name, fn) requests[name] = fn end
        function mp.register_idle(fn) idle = fn end
        mp.commandv = command
        package.preload['mp'] = function() return mp end
        package.preload['mp.utils'] = function() return {format_json = encode} end
    ''')
    lua.execute(SCRIPT)

    def update(key, value):
        lua.globals().props[key] = value
        lua.globals().observers[key]()

    return lua, update, manager, spoken, messages


@pytest.mark.parametrize("order", list(itertools.permutations(["sub-text", "sub-start", "sub-end"])))
@pytest.mark.parametrize("second_text", ["Yes.", "Different."])
def test_every_notification_order_yields_complete_independent_cues(order, second_text):
    lua, update, manager, spoken, _ = harness()
    for key, value in {"sub-text": "Yes.", "sub-start": 1.0, "sub-end": 2.0}.items():
        update(key, value)
    lua.globals().idle()
    first = manager.get_recent()[0]
    values = {"sub-text": second_text, "sub-start": 5.0, "sub-end": 6.0}
    for key in order:
        update(key, values[key])
    lua.globals().idle()
    assert spoken == ["Yes.", second_text]
    assert [(c.start_ms, c.end_ms) for c in manager.get_recent()] == [(1000, 2000), (5000, 6000)]
    assert first.start_ms == 1000 and first.end_ms == 2000


def test_identical_text_without_a_second_text_notification():
    lua, update, manager, spoken, _ = harness()
    update("sub-text", "Yes.")
    update("sub-start", 1.125)
    update("sub-end", 2.875)
    lua.globals().idle()
    update("sub-start", 3.125)
    update("sub-end", 4.875)
    lua.globals().idle()
    assert spoken == ["Yes.", "Yes."]
    assert [c.start_ms for c in manager.get_recent()] == [1125, 3125]


def test_seek_suppresses_stale_text_until_playback_restart():
    lua, update, manager, spoken, _ = harness()
    update("sub-text", "Before seek")
    lua.globals().idle()
    lua.globals().events["seek"]()
    lua.globals().idle()
    assert manager.get_recent() == []
    assert spoken == ["Before seek"]
    update("sub-text", "After seek")
    lua.globals().events["playback-restart"]()
    lua.globals().idle()
    assert spoken == ["Before seek", "After seek"]


def test_file_end_clears_and_subtitle_visibility_controls_current_text():
    lua, update, manager, spoken, _ = harness()
    update("sub-text", "Visible")
    lua.globals().idle()
    update("sub-visibility", False)
    lua.globals().idle()
    assert not manager.read_current()
    lua.globals().events["end-file"]()
    lua.globals().idle()
    assert manager.get_recent() == []
    assert spoken == ["Visible"]


def test_explicit_snapshot_request_proves_script_is_loaded():
    lua, _, _, _, messages = harness()
    lua.globals().idle()
    count = len(messages)
    lua.globals().idle()
    assert len(messages) == count
    lua.globals().requests["iptvclient-subtitle-request"]()
    lua.globals().idle()
    assert len(messages) == count + 1
