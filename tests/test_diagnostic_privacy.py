from diagnostic_privacy import sharing_excerpt

import pytest


@pytest.mark.parametrize("line", [
    'Opening https://example.invalid/live/testuser/testpass/1.ts',
    "GET HTTP://example.invalid/get.php?username=test&password='test pass' extra",
    'url=rtsp://example.invalid/live',
    'Authorization: Bearer test-token',
    'Cookie: session=test-cookie',
    "{'password': 'test pass', 'username': 'test user'}",
    'access_token = test-token',
    'X-Api-Key: test-key',
    'mac="00:00:00:00:00:00"',
    'Authorization: Basic dGVzdDp0ZXN0',
])
def test_access_data_is_removed_as_a_whole_line(line):
    assert sharing_excerpt('Before\n' + line + '\nAfter') == 'Before\n[***]\nAfter'


def test_ordinary_diagnostics_and_unicode_are_preserved_and_filter_is_idempotent():
    value = 'Állapot: Buffering\r\nTimeout after 5 seconds\nERROR VLC: connection lost'
    result = sharing_excerpt(value)
    assert result == value.replace('\r\n', '\n')
    assert sharing_excerpt(result) == result


def test_actual_copy_command_filters_only_the_shared_copy():
    from types import SimpleNamespace
    from tests.test_subtitle_integration import extract_class
    from pathlib import Path
    copied, notices = [], []
    class Clipboard:
        def Open(self): return True
        def SetData(self, value): copied.append(value)
        def Close(self): pass
    wx = SimpleNamespace(TheClipboard=Clipboard(), TextDataObject=lambda value: value,
                         version=lambda: 'test', OK=1, ICON_ERROR=2, ICON_INFORMATION=4)
    cls, _ = extract_class('main.py', 'IPTVClient', ['_copy_diagnostic_information'], {
        'wx': wx, 'sys': SimpleNamespace(platform='test', version='3.12'),
        'get_epg_log_path': lambda: Path('unused'),
        'message_box': lambda *args: notices.append(args),
    })
    frame = cls()
    frame.config = {'playlists': [], 'epgs': []}
    frame.recorder = SimpleNamespace(list_active=lambda: [])
    original = 'ERROR connection timeout\nOpening https://example.invalid/live/testuser/testpass/1.ts'
    frame._read_diagnostic_log_tail = lambda path: original
    frame._copy_diagnostic_information()
    assert len(copied) == 1
    assert 'ERROR connection timeout' in copied[0]
    assert 'testpass' not in copied[0]
    assert '[***]' in copied[0]
    assert 'testpass' in original
    assert notices
