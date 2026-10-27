"""Bookmarks and the actual file-player checkpoint/prompt integration."""
from types import SimpleNamespace

import pytest

import playback_resume as resume
from tests.test_subtitle_integration import extract_class

KEY = resume.item_key({'kind': 'movie', 'url': 'https://example.invalid/movie/test/1.mp4'})


def test_only_explicit_vod_gets_a_stable_nonplaintext_identity():
    movie = {'kind': 'movie', 'url': 'https://example.invalid/movie/test/1.mp4', 'provider-id': 'test'}
    key = resume.item_key(movie)
    assert len(key) == 64 and 'example' not in key
    assert resume.item_key(dict(movie, name='Renamed')) == key
    assert resume.item_key(dict(movie, kind='live')) == ''
    assert resume.item_key({'url': movie['url']}) == ''
    assert resume.item_key(None) == ''


@pytest.mark.parametrize('position,length', [(False, 100000), (float('inf'), 100000),
                                           ('100', 1000), (-1, 100000), (2000, 1000),
                                           (100000, resume.MAX_MS + 1)])
def test_invalid_times_do_not_replace_existing_progress(position, length):
    entries = resume.checkpoint({}, KEY, 60000, 600000, now=1)
    assert resume.checkpoint(entries, KEY, position, length, now=2) == entries


def test_unknown_duration_keeps_progress_and_finishing_clears_it():
    entries = resume.checkpoint({}, KEY, 60000, 600000, now=1)
    assert resume.checkpoint(entries, KEY, 0, 0) == entries
    assert resume.checkpoint(entries, KEY, 590000, 600000) == {}
    assert resume.checkpoint(entries, KEY, 0, 600000) == {}
    assert resume.normalize({'bad': {}, KEY: {'position_ms': True, 'length_ms': 100000, 'updated': 1}}) == {}


def test_storage_is_bounded_and_malformed_config_is_ignored():
    entries = {}
    for i in range(250):
        key = resume.item_key({'kind': 'movie', 'url': str(i)})
        entries = resume.checkpoint(entries, key, 60000, 600000, now=i)
    assert len(entries) == 200
    assert min(value['updated'] for value in entries.values()) == 50
    assert resume.normalize([]) == {}
    assert resume.checkpoint({}, None, 60000, 600000) == {}


def frame(accepted=True):
    clock, saved, statuses = [100.0], [], []
    wx = SimpleNamespace(YES_NO=1, NO_DEFAULT=2, ICON_QUESTION=4, ID_YES=5)
    cls, _ = extract_class('internal_player.py', 'InternalPlayerFrame',
                          ['configure_vod_resume', 'prepare_vod_resume', '_save_resume_checkpoint'], {
        'playback_resume': resume, 'time': SimpleNamespace(monotonic=lambda: clock[0]),
        'wx': wx, 'message_box': lambda *args, **kwargs: 5 if accepted else 6,
    })
    instance = cls()
    instance._resume_key = ''
    instance._resume_start_ms = 0
    instance._resume_config = None
    instance._resume_save = None
    instance._current_stream_kind = 'vod'
    instance._destroyed = instance._manual_stop = False
    instance._has_seen_playing = True
    instance._play_start_monotonic = 100.0
    instance._resume_last_save = 0
    instance.player = SimpleNamespace(get_time=lambda: 120000, get_length=lambda: 600000)
    instance._update_status_label = lambda *args, **kwargs: statuses.append(args[0])
    config = {'playback_bookmarks': resume.checkpoint({}, KEY, 60000, 600000, now=1)}
    instance.configure_vod_resume(config, lambda: saved.append(dict(config)))
    return instance, clock, saved, statuses, config


@pytest.mark.parametrize('accepted', [True, False])
def test_prompt_restores_only_after_consent_or_clears_the_old_bookmark(accepted):
    instance, _, saved, _, config = frame(accepted)
    instance.prepare_vod_resume({'kind': 'movie', 'url': 'https://example.invalid/movie/test/1.mp4'})
    assert instance._resume_start_ms == (60000 if accepted else 0)
    assert (KEY in config['playback_bookmarks']) == accepted
    assert bool(saved) != accepted


def test_periodic_checkpoint_is_throttled_and_failed_seek_preserves_the_bookmark():
    instance, clock, saved, statuses, config = frame()
    instance._resume_key = KEY
    instance._resume_start_ms = 180000
    instance._save_resume_checkpoint(force=True)
    assert config['playback_bookmarks'][KEY]['position_ms'] == 60000
    clock[0] = 161
    instance._save_resume_checkpoint()
    assert statuses and not saved
    assert instance._resume_start_ms == 0
    clock[0] = 192
    instance._save_resume_checkpoint()
    assert config['playback_bookmarks'][KEY]['position_ms'] == 120000
    assert len(saved) == 1
    instance._save_resume_checkpoint()
    assert len(saved) == 1
    instance._current_stream_kind = 'live'
    instance._save_resume_checkpoint(force=True)
    assert len(saved) == 1
