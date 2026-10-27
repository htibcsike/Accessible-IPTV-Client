# VOD resume library validation

Base: `3e6ee8dcba9e9216d45faa19e6bc8363ae1ddbef` (v1.150.47).

## Final code checks

- Broad local Linux regression: **2559 passed, 162 skipped, 5 deselected**, no failures (57.33 s).
- Affected model, extracted production UI paths, VOD, modal guard, localization and Debian package tests: **119 passed, 1 skipped**, no failures.
- Ruff: passed for the repository.
- `git diff --check`: passed.
- Source extraction: 772 messages; all 13 translated application catalogues complete with matching placeholders. Every singular translation was read back from its compiled MO using GNU gettext.
- Hungarian guide: all pre-existing topic IDs retained in their original order.
- New Hungarian UI text (23 strings) and the revised VOD help section received a final contextual and language review after the implementation stabilized. Existing catalogue translations are unchanged.

The broad run uses a local headless collection helper to skip fixtures requiring `wx_app`, and ignores `tests/test_player_transport_gui.py` because this host has no graphical display. Five existing host-dependent cases were deselected:

- `test_internal_player.py::test_the_focus_leaves_the_audio_track_choice_before_it_is_disabled` — GUI focus requires a display.
- `test_startup_lazy.py::test_config_read_candidates_do_not_create_user_config_dir` — this host's config path behavior differs from the isolated APPDATA contract.
- `test_updater.py::test_update_helper_actually_starts_from_a_path_with_a_space` — Windows update-helper execution is unavailable here.
- `test_stream_proxy.py::test_the_proxy_handlers_are_daemon_threads` — this host cannot provide the required test network interface.
- `test_epg_database.py::test_a_live_imports_lock_is_not_stolen` — PID/process visibility differs in the host environment.

The headless helper is not shipped. No repository test selection, CI configuration, skip list, audit exemption or production capability gate was weakened. The 162 skips include existing GUI/native/optional-feature conditions; they do not count as successful runtime acceptance. The Windows-specific skip in the targeted set is likewise not a passed Windows test.

## Required native acceptance

Windows/frozen builds, JAWS/NVDA and real-provider/VLC seeking were not exercised. The maintainer should verify list navigation and column announcements; Delete and default-No confirmations; Resume / Play from Beginning / Escape; retaining the currently playing session after cancellation; close during a network check; source reload during a check or question; active-item history deletion; disconnected providers; and recording/update notifications while custom dialogs are open. Provider-side ID reuse and unknown/changed legacy URLs cannot be solved by title guessing and remain documented limitations.
