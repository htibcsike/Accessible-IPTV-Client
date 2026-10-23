# Subtitle speech integration after v1.150.37

Prepared on 23 October 2026 against `de169d0a61a26a01a602f6532fe3a19f80b7bbb9` (the current main branch after v1.150.37). This is a developer review candidate for the outstanding subtitle findings in #45 and the design in #37. It supersedes the patch supplied on 15 October against v1.150.3; applying that older patch over the current code would discard or conflict with intervening fixes.

## Problem and resulting behavior

Starting MPV with automatic subtitle speech off previously created no collector. Identical successive captions could collapse into one entry with rewritten times. The built-in player's direct manual review bypassed the configured application voice, and unvalidated callbacks could outlive their playback owner. A missing application voice or selected endpoint also had paths to an unintended speech destination.

The patch binds producers to one playback token, gathers supported MPV text independently of automatic output, commits immutable complete cue snapshots, and routes built-in automatic/manual speech through the selected backend. Missing-device routing retains the requested stable ID and blocks captions under the pause policy; an approved default fallback is temporary. No caption implicitly falls through to the screen reader when application TTS fails.

## Current upstream fixes preserved

- MPV launch runs on a worker; monotonic debounce and launch-generation checks remain.
- A slow version reply is advisory, not a prerequisite for usable subtitle speech. Cold connection setup retains a separate six-second budget; runtime requests remain bounded.
- The plain MPV handoff keeps its per-launcher private endpoint.
- Existing config persistence corrections, built-in cue integration and `Cue.start/end` timestamps remain; the sink is strengthened with ownership and pause/file identity.
- Clearing a manager invalidates queued speech; disabling automatic speech also invalidates queued automatic work. Manual review is still available with automatic output off.
- Application-owned speech is purged on transitions, and the built-in cue timer is stopped during teardown.
- No player-rate, live-buffer, provider/catch-up, recording, channel matching, casting engine, existing translation or user-help changes are included.

## Implementation map

| Component | Change |
| --- | --- |
| `subtitle_speech.py` | Frozen cue history, full source/track identity, missing-only timing enrichment, pause/output epochs, latest-current automatic output when the UI is late, stable review snapshots. |
| `subtitle_session.py` | Session-bound producer sink; token validation for intake and delayed UI callbacks; immediate logical cancellation and worker cleanup; token-required adapter registration rejects late owners. Lifecycle changes run on the GUI thread. |
| `mpv_subtitle_script.py` | Embedded private Lua helper. Observes relevant native properties and reads a complete snapshot during `register_idle`, with media/seek epoch and serial identity. Explicit handshake proves that the helper runs. |
| `mpv_subtitle_adapter.py` | Single IPC reader, request-ID/event dispatch, cancellable pending requests, bounded buffers/reads and full Win32 prototypes. Reads an available byte instead of asking for zero bytes. Snapshot assembly replaces independent text/time property merging. Version checks cannot gate readiness. |
| `external_player.py` | Collection while automatic speech is off, exact Custom executable resolution, ownership after duplicate suppression, validated worker results, superseded fallback entry checks, and controller registration. |
| `internal_player.py` | Source-bound cue emission and selected-file identity; external cues do not follow a different selected track; parser generation and backward-seek clearing; backend-routed manual review; pause state and teardown clearing. |
| `main.py` | One synchronized toggle setter, bound sink before playback, validated close callbacks, backend-only caption dispatch, stable output picker with preview rollback, and GUI/COM-thread output checks during active sessions. |
| `app_tts.py` | Stable SAPI token IDs, explicit routing/result states, exact unique legacy-name migration, output loss/recovery/fallback handling, owning-thread checks, purge before route changes and explicit plain-text Speak flags. Prior IDispatch/VARIANT fixes remain. |
| Tests and requirements | Integrated method-body regressions, real helper test, Windows pipe round trip, routing-state tests and Lua harness. Lupa is a development test dependency. Routing tests are separate from the native SAPI test file so the existing CI exclusion cannot hide them. |

### Failure and lifecycle contracts

- Failure after creating the MPV process leaves that same process playing; it cannot launch a duplicate player. If private helper creation fails before playback starts, the app can launch a playback-only MPV that is still owned and retired through the same controller. It is reported as unavailable for subtitle speech.
- A channel/player transition revokes the prior token before retiring resources. Reader/setup joins and process waits run off the GUI thread. An obsolete worker cannot register an adapter over the new session.
- Turning automatic speech off does not close playback or the collector. Pause suppresses automatic output, while explicit review remains available.
- A gap clears the current displayed cue. Review history is retained within the current timeline. Seek/media/track replacement clears the old timeline.
- Both windows use the same configured backend. SAPI failure reports a non-sensitive status; a system-default policy does not authorize a separate screen-reader fallback.

## Verification

Local environment: Linux / CPython 3.12, with wxPython available for imports and display-independent class-method tests. A real MPV 0.37.0 process ran the production Lua helper against an FFmpeg-generated local video/SRT. Three timed captions were emitted correctly, including two distinct occurrences of the same words.

The combined targeted run completed with **1022 passed, 4 skipped, 2 deselected**. Ruff and Python compilation passed. The skipped cases require a host allowing AF_UNIX listener creation, native Windows named pipes, real SAPI, or Windows UI-language detection. Socketpair transport tests and the real MPV helper without a network listener did run.

The deselected cases are explicitly outside this host's usable coverage:

- `test_internal_player.py::test_the_focus_leaves_the_audio_track_choice_before_it_is_disabled` needs a native wx display; this host has no X display.
- `test_startup_lazy.py::test_config_read_candidates_do_not_create_user_config_dir` assumes Windows APPDATA directory selection on Linux. An isolated run still fails its platform-dependent path assertion; the test and `options.py` are unchanged by this patch.

The method-body integration tests use the actual source with explicit surrounding fakes. Existing player/review tests import actual classes. Neither is presented as a native Windows GUI, frozen-build, JAWS/NVDA or physical-audio acceptance test.

Reproduce the targeted selection with the project's dependencies plus Lupa:

```sh
python -m pytest -q -ra \
  tests/test_subtitle_cues.py tests/test_subtitle_speech.py \
  tests/test_subtitle_session.py tests/test_subtitle_integration.py \
  tests/test_mpv_subtitle_adapter.py tests/test_mpv_subtitle_script.py \
  tests/test_mpv_pipe.py tests/test_app_tts.py tests/test_app_tts_routing.py \
  tests/test_external_player_debounce.py tests/test_external_subtitle_session.py \
  tests/test_subtitle_review.py tests/test_internal_player.py \
  tests/test_source_hygiene.py tests/test_no_local_wx_import.py \
  tests/test_i18n.py tests/test_translation_audit.py tests/test_debian_package.py \
  tests/test_startup_lazy.py tests/test_main_shortcuts.py \
  tests/test_player_menu_help.py tests/test_cast_from_player_focus.py \
  tests/test_live_cushion.py \
  --deselect tests/test_internal_player.py::test_the_focus_leaves_the_audio_track_choice_before_it_is_disabled \
  --deselect tests/test_startup_lazy.py::test_config_read_candidates_do_not_create_user_config_dir
```

The existing Windows checks workflow automatically discovers the new display-independent tests. It still excludes the native SAPI/player files under its current policy. Real endpoint and screen-reader acceptance must therefore be recorded separately, and the full MPV IPC test must run on an unrestricted host with MPV/FFmpeg.

## Acceptance required before release

1. Source and packaged Windows startup with JAWS and NVDA separately; verify that the preserved SAPI constructor/volume path does not crash.
2. Toggle from either window, check both menus, actual speech, immediate exit and restored preference on restart. Exercise the screen-reader and application-voice backends separately.
3. Built-in SRT/WebVTT with Unicode paths, an initially selected embedded track, another selected track, Off/on, reload of the same file, channel replacement, pause/manual review, backward seek and gaps. Check late parser results and the last/current/previous review semantics.
4. Normal MPV and Custom MPV paths, collection with automatic output initially off, enabling it without restarting playback, identical successive captions, track change, seek and disconnect. Include a slow version reply and unavailable helper/IPC.
5. Rapid MPV → built-in → MPV changes, double Enter, an old worker finishing late, cast handoff, player close and application exit. Verify no old text/state takes over and no owned process is orphaned. Include a one-stream provider: process cleanup is asynchronous and brief process-lifetime overlap is possible.
6. Headphones missing at startup and wired/USB/Bluetooth removal during and between utterances, both routing policies, default-output changes, reconnection and sleep/resume. Under pause, verify no captions reach an unapproved destination; under approved fallback, verify the requested ID survives and is reselected.
7. Output preview Yes/No, selection/synthesis failure, previous system-default selection and duplicate friendly names. Confirm independent application/programme/screen-reader volumes and focus restoration.

## Deliberate boundaries

MPV current-text observations are not a lossless subtitle extraction API: idle snapshots cannot recover intermediate text coalesced by MPV. Only the primary text track is collected; bitmap OCR and secondary simultaneous subtitle speech are not implemented. Other external players retain their existing capabilities.

The built-in path reads application-parsed SRT/WebVTT, not arbitrary embedded caption text. A libVLC build that reuses an existing SPU ID when loading a file may leave the conservative new-track binding unverified; test that case before claiming broad libVLC compatibility rather than speaking the wrong file's text.

A successful asynchronous SAPI call or an enumerated token is not physical proof of delivery. Driver-specific rerouting needs the endpoint matrix above. The patch validates SAPI routing and purges detected losses; it does not claim sample-accurate hardware failover prevention.

User help and untranslated Hungarian elements are intentionally deferred until the maintainer accepts and integrates the behavior, as requested by Tibor. No binary or release is produced by this patch.

References: [MPV manual](https://mpv.io/manual/stable/) (`register_idle`, script messages, subtitle properties and IPC); [Microsoft Speak flags](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/ms720892(v=vs.85)).
