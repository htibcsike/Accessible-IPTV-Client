# Shared subtitle processing and thin player bridges

## Problem and resulting behavior

The existing subtitle speech manager already owned output routing and recent-cue review, but the built-in file timer also implemented scheduling and playback-boundary decisions. MPV sent a different set of individual calls. Adding another player risked duplicating the same processing or omitting a pause, clear or ownership check.

Both production sources now submit the same immutable `SubtitleSnapshot` through the session-bound sink to `SubtitleSpeechManager.on_snapshot`. The manager applies one set of generation/sequence checks, timeline replacement, pause transitions, duplicate suppression, history and backend dispatch. The built-in player obtains file cues from `TimedTextSource`, which is independent of wx, libVLC, MPV, timers, sockets and audio devices.

This is an incremental extension of PR #83, based on its Windows-CI-green follow-up (`e0aa91b1c14867c7d08da7da15bffb4a41da1c43`). It does not replace the earlier routing, IPC transport, Lua snapshot or session-ownership fixes.

## Shared responsibilities

- `subtitle_cues.py`: the existing SRT/WebVTT loading, decoding and parsing rules.
- `subtitle_pipeline.py`: validated immutable clock/snapshot values and one reusable file timeline. It applies subtitle delay to an observed media clock, identifies active/started cues, advances generation on backward movement or source/track replacement, and emits ordered snapshots. Unknown or negative player time never becomes valid through a negative subtitle delay. Disabled tracks do not advance file review history.
- `subtitle_session.py`: every snapshot remains bound to its playback owner. Old workers/producers cannot modify the new session. Purging owned speech is dispatched through the validated UI path before a replacement cue is queued.
- `subtitle_speech.py`: one atomic snapshot intake, stale-generation/sequence rejection, pause/reset handling, cue history, duplicate rules, manual reading and output callback. A gap, disabled track or unsupported text clears current text without discarding review history. A new timeline discards old history.
- Existing application/SAPI layers: selected backend, volume, endpoint identity, missing-device policy and UI/COM thread ownership. No additional speech engine is introduced.

## Responsibilities that remain in a player bridge

A bridge retrieves the actual media clock and state, identifies the selected subtitle source/track, translates protocol units and marshals player controls. A native-text bridge must assemble a complete snapshot; it must not independently implement speech or output routing. MPV's private Lua helper still assembles native properties because that protocol-specific operation cannot be guessed centrally.

For a clock-only player and a separately supplied supported file, use the same file source:

```python
from subtitle_pipeline import PlaybackPosition, TimedTextSource

# Activate/bind only after accepting a playback owner. Load files off the GUI
# thread and reject stale loading results with that owner's generation/token.
token = controller.activate_session("external-file")
sink = controller.bind(token)
source = TimedTextSource.from_file(subtitle_path)

# Called serially when the bridge observes a real player clock/state.
sample = source.sample(
    PlaybackPosition(position_ms, paused=paused, subtitle_delay_ms=delay_ms),
    source="external-file",
    track=subtitle_file_identity,
    enabled=subtitle_track_enabled,
)
sink.on_snapshot(sample.snapshot)
```

The application owns scheduling. No second provider connection, timer thread, network listener, screen scrape or hidden playback instance is created by the shared source. Playback rate and buffering are followed through the *observed media time*, not wall-clock extrapolation. A wrong file/version or offset is not automatically repaired.

For native text, construct `SubtitleSnapshot` and call the same `sink.on_snapshot`. Supply media milliseconds, a nonempty source, track identity, nonnegative generation and positive sequence. Increase generation on seek/track/media boundaries and sequence within a generation. Use a new session/token when replacing producers. Consumers reject older sequences/generations; `clear()` does not reopen intake for delayed input. Session replacement resets intake identity. A source object is called serially by its bridge; the manager and bound sink protect concurrent intake.

## Existing application integration

The built-in player uses the shared file timeline for the file it has selected and verified. The frame retains labels, localized review-command messages and the asynchronous libVLC track-binding checks. Its legacy callback/standalone speech path remains compatible.

MPV converts complete Lua notifications into the same snapshot model. It retains transport-level serial validation, helper/epoch/track identity and bitmap capability/status reporting. Invalid zero serials, boolean protocol versions and unbounded native timing values are rejected safely before they can break the shared boundary.

The new module is imported by the production graph and is checked in the Debian package payload. It has no additional dependency or user-visible strings.

## Verification

- Final broad local Linux selection: **2165 passed, 158 skipped, 4 deselected**, no failures. Unlike the Windows gate, it also includes display-independent internal-player and application-TTS tests. GUI fixture cases are skipped through an external local harness; native/host limits are described below. CI configuration is unchanged.
- The initial CI-shaped local selection passed with **2011 passed, 157 skipped, 3 deselected**. The additional internal-player/TTS selection passed with **154 passed, 1 skipped, 1 deselected** after installing the declared python-vlc dependency; initial missing-module failures were environmental and required no code changes.
- Affected subtitle/session/MPV/integration/package selection: **185 passed, 2 skipped**, no failures.
- Ruff and Python compilation passed.
- Real MPV 0.37.0 executed the unchanged production Lua helper with generated local video/SRT. Its script messages traversed the actual adapter, a bound session sink and the shared manager. Three correctly timed cues were spoken through the injected test output, including two consecutive `Yes.` captions. A test-only in-process message receiver captured messages; no socket restriction was bypassed. This verifies the helper/adapter/shared pipeline, not full production IPC or physical audio.

The final broad local run excludes the native player-transport GUI file. It deselects the CI's slow updater-helper test, the internal-player focus test that directly creates a GUI, the unchanged Windows-APPDATA assumption and the unchanged stream-proxy listener test (`EADDRNOTAVAIL` on this host). GUI fixture cases are skipped locally because there is no desktop. The full MPV IPC case and native named-pipe case also skip on the local restricted/non-Windows host. These exceptions are **not** added to the repository or its Windows gate. The prior Windows result of 2093 passing tests belongs to the earlier commit, not to this new architecture change; Windows CI must run again after submission.

## Scope and acceptance

Production integration currently covers the built-in file source and the controlled MPV text source. This supplies a reusable processing boundary for additional players; it does not automatically establish new VLC/Kodi/MPC/PotPlayer integrations. A bridge needs trustworthy clock/state access, and either native timed text or a matching separately supplied file. A visible subtitle track, a player name or an installed executable alone proves none of those capabilities.

Before release, run the new Windows gate and repeat the PR #83 native GUI, JAWS/NVDA, physical output-loss/reconnection and frozen-build matrix. Specifically check pause/manual review, a backward seek into a gap, initially disabled subtitles, a negative subtitle delay while the clock is unknown, same-file reload and rapid MPV/built-in transitions. No bitmap OCR, live subtitle demuxer, automatic speech-speed adaptation or lossless MPV caption extraction is claimed.

Help and Hungarian translations remain deferred until behavior is accepted, as requested by Tibor. There is no automatic merge, release or version change.
