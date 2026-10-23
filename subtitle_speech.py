"""Player-independent subtitle speech: cue queue, speech routing, capabilities.

Per issue #37: one accessible presentation/speech layer fed by multiple cue
sources (built-in SRT/WebVTT files, the MPV IPC adapter). Each source uses the
clock and track identity of the player actually rendering the programme.

Capabilities are tracked per player: enumerate tracks, select/disable track,
load external subtitle, obtain timed text cues, control time/seek, and read
the current/previous cue. Each is available, unavailable, or unverified.

Speech output always goes through the injected ``speak`` callable, which the
application wires to either the screen reader (JAWS/NVDA keep ownership of
their voice, volume and audio endpoint) or the optional application-owned TTS
backend (which owns its own volume and output device). This module never
touches audio itself.
"""

import logging
import threading
from collections import deque
from dataclasses import dataclass, replace
from typing import Callable, Deque, Dict, List, Optional

from subtitle_pipeline import SubtitleSnapshot

LOG = logging.getLogger(__name__)

# Capability states per the #37 plan.
AVAILABLE = "available"
UNAVAILABLE = "unavailable"
UNVERIFIED = "unverified"

# Capability names.
CAP_ENUMERATE_TRACKS = "enumerate_tracks"
CAP_SELECT_TRACK = "select_track"
CAP_LOAD_EXTERNAL = "load_external"
CAP_TIMED_CUES = "timed_cues"
CAP_SEEK = "seek"
CAP_READ_CURRENT = "read_current"
CAP_READ_PREVIOUS = "read_previous"

ALL_CAPABILITIES = [
    CAP_ENUMERATE_TRACKS,
    CAP_SELECT_TRACK,
    CAP_LOAD_EXTERNAL,
    CAP_TIMED_CUES,
    CAP_SEEK,
    CAP_READ_CURRENT,
    CAP_READ_PREVIOUS,
]

# Bounded recent-cue history for review (per #37: "review recent cues").
MAX_RECENT_CUES = 50

#: Honest baseline for timed caption text per player, from the #37 audit.
#: A working executable, visible subtitles, or a track-selection API does not
#: establish an API for obtaining the displayed words, so every player without
#: a documented, versioned timed-text API stays unavailable rather than
#: guessed at. Runtimes promote entries to available once actually verified.
BASELINE_CAPABILITIES: Dict[str, Dict[str, str]] = {
    # Built-in player: text becomes available after loading an SRT/WebVTT file.
    "built-in": {
        CAP_ENUMERATE_TRACKS: AVAILABLE,
        CAP_SELECT_TRACK: AVAILABLE,
        CAP_LOAD_EXTERNAL: AVAILABLE,
        CAP_TIMED_CUES: UNVERIFIED,
        CAP_SEEK: AVAILABLE,
        CAP_READ_CURRENT: UNVERIFIED,
        CAP_READ_PREVIOUS: UNVERIFIED,
    },
    # MPV: sub-text/sub-start/sub-end via JSON IPC, but only through our own
    # session adapter and only for text subtitles (bitmap stays unavailable).
    "MPV": {
        CAP_ENUMERATE_TRACKS: UNVERIFIED,
        CAP_SELECT_TRACK: UNVERIFIED,
        CAP_LOAD_EXTERNAL: UNVERIFIED,
        CAP_TIMED_CUES: UNVERIFIED,
        CAP_SEEK: UNVERIFIED,
        CAP_READ_CURRENT: UNVERIFIED,
        CAP_READ_PREVIOUS: UNVERIFIED,
    },
    # VLC: single-instance flags only; no timed-text API.
    "VLC": {cap: UNAVAILABLE for cap in ALL_CAPABILITIES},
    # MPC-HC / MPC-BE: URL handoff only; no timed-text API.
    "MPC": {cap: UNAVAILABLE for cap in ALL_CAPABILITIES},
    "MPC-BE": {cap: UNAVAILABLE for cap in ALL_CAPABILITIES},
    # PotPlayer: URL handoff only; no timed-text API.
    "PotPlayer": {cap: UNAVAILABLE for cap in ALL_CAPABILITIES},
    # Kodi: JSON-RPC documents subtitle enumeration/selection, but those
    # metadata controls alone do not provide timed caption text.
    "Kodi": {cap: UNAVAILABLE for cap in ALL_CAPABILITIES},
}


@dataclass(frozen=True)
class CueEvent:
    """A single subtitle cue ready for speech or review.

    ``generation`` is the source's media-generation identity (new programme,
    new file, new subtitle track). Cues are keyed on generation + track +
    timing + text, so replay after seek is intentional but reconnects and
    late events from an old stream never speak the wrong programme.
    """

    text: str
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    source: str = ""  # "builtin-file" or "mpv-ipc"
    track: str = ""  # subtitle track identity, when known
    generation: int = 0  # media-generation identity from the source


class SubtitleSpeechManager:
    """Central subtitle speech: cue queue, speech output, capability tracking.

    Thread ownership (issue #37): cue sources may call from any thread (the
    MPV IPC reader runs off the GUI thread). All manager state is guarded by
    a lock, and speech output plus the error callback are marshalled through
    ``ui_thread`` (e.g. ``wx.CallAfter``), which must run callables on the
    application's UI thread. The injected ``speak_fn`` itself therefore only
    ever executes on the UI thread.

    Sources call :meth:`on_cue` when a new cue becomes active. The manager
    speaks it if auto-speech is enabled, and always records it for review.
    A source switch, stop, or track change must call :meth:`clear` so stale
    cues are never spoken or reviewed.
    """

    def __init__(
        self,
        speak_fn: Callable[[str], None],
        ui_thread: Optional[Callable[..., None]] = None,
        on_speak_error: Optional[Callable[[str, Exception], None]] = None,
    ):
        self._speak = speak_fn
        # Marshals callables onto the UI thread; default runs them inline
        # (single-threaded callers such as tests).
        self._ui_thread = ui_thread or (lambda fn, *args: fn(*args))
        # Accessible failure path: called on the UI thread when the speech
        # backend raises, so the user hears the failure as text rather than
        # it dying silently in a debug log.
        self._on_speak_error = on_speak_error
        self._lock = threading.RLock()
        self._auto_speech = False
        self._recent: Deque[CueEvent] = deque(maxlen=MAX_RECENT_CUES)
        self._current: Optional[CueEvent] = None
        self._previous: Optional[CueEvent] = None
        self._capabilities: Dict[str, Dict[str, str]] = {}
        self._source_name = ""
        self._epoch = 0
        self._output_epoch = 0
        self._paused = False
        self._snapshot_identity = None
        self._snapshot_sequence = 0

    # -- Configuration ----------------------------------------------------

    @property
    def auto_speech(self) -> bool:
        with self._lock:
            return self._auto_speech

    def set_auto_speech(self, enabled: bool) -> None:
        with self._lock:
            if self._auto_speech != bool(enabled):
                self._output_epoch += 1
            self._auto_speech = bool(enabled)

    def set_paused(self, paused: bool) -> bool:
        with self._lock:
            changed = self._paused != bool(paused)
            if changed:
                self._output_epoch += 1
            self._paused = bool(paused)
            return changed

    # -- Cue intake (called by sources) ------------------------------------

    def on_snapshot(self, snapshot: SubtitleSnapshot, before_reset=None) -> bool:
        """Accept player-neutral input atomically; reject late generations.

        Bridges translate their native protocol only. This is the common
        boundary for timeline replacement, pause and cue intake. The optional
        callback purges owned speech before a replacement cue is queued.
        """
        if not isinstance(snapshot, SubtitleSnapshot):
            raise TypeError("snapshot must be a SubtitleSnapshot")
        with self._lock:
            identity = (snapshot.source, snapshot.track, snapshot.generation)
            old = self._snapshot_identity
            if old is not None and old[0] == snapshot.source:
                if snapshot.generation < old[2]:
                    return False
                if snapshot.generation == old[2] and snapshot.sequence <= self._snapshot_sequence:
                    return False
            reset = identity != old
            pausing = snapshot.paused and not self._paused
            if (reset or pausing) and before_reset is not None:
                before_reset()
            if reset:
                self.clear()
            self._snapshot_identity = identity
            self._snapshot_sequence = snapshot.sequence
            self.set_paused(snapshot.paused)
            self.on_cue(
                snapshot.text if snapshot.active and snapshot.text_supported else "",
                start_ms=snapshot.start_ms, end_ms=snapshot.end_ms,
                source=snapshot.source, track=snapshot.track,
                generation=snapshot.generation,
            )
            return True

    def on_cue(
        self,
        text: str,
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
        source: str = "",
        track: str = "",
        generation: int = 0,
    ) -> None:
        """A new cue became active. Speak it if auto-speech is on.

        Duplicate suppression is keyed on generation + track + timing + text,
        never on wording alone: two genuine consecutive cues that both say
        "Yes." are both recorded and spoken. A re-send of the *same* cue
        only fills in missing timing on the current cue, without re-speaking
        or duplicating history. MPV supplies complete Lua-side snapshots.
        """
        text = (text or "").strip()
        with self._lock:
            if not text:
                self._current = None
                self._output_epoch += 1
                return
            source = source or self._source_name
            current = self._current
            if (
                current is not None
                and current.generation == generation
                and current.source == source
                and current.track == (track or "")
                and current.text == text
                and (start_ms is None or current.start_ms is None
                     or start_ms == current.start_ms)
            ):
                self.update_cue_timing(start_ms, end_ms, generation)
                return
            event = CueEvent(
                text=text,
                start_ms=start_ms,
                end_ms=end_ms,
                source=source,
                track=track or "",
                generation=generation,
            )
            self._output_epoch += 1
            self._previous = self._recent[-1] if self._recent else None
            self._current = event
            self._recent.append(event)
            if self._auto_speech and not self._paused:
                self._speak_text(text, automatic=True)

    def update_cue_timing(
        self,
        start_ms: Optional[int],
        end_ms: Optional[int],
        generation: int = 0,
    ) -> None:
        """Fill in timing for the current cue without speaking it.

        This compatibility method only enriches missing timing; production
        sources should submit complete cues through :meth:`on_cue`. A timing
        event for a different generation is ignored.
        """
        with self._lock:
            current = self._current
            if current is None or current.generation != generation:
                return
            # Only enrich missing fields. A later cue must never retime an
            # already committed entry. Sources should submit complete cues.
            if current.start_ms is not None and start_ms not in (None, current.start_ms):
                return
            updated = replace(
                current,
                start_ms=current.start_ms if current.start_ms is not None else start_ms,
                end_ms=current.end_ms if current.end_ms is not None else end_ms,
            )
            self._current = updated
            if self._recent and self._recent[-1] is current:
                self._recent[-1] = updated

    def _speak_text(self, text: str, automatic: bool = False) -> None:
        """Speak on the UI thread; route failures to the error callback."""
        with self._lock:
            epoch, output_epoch = self._epoch, self._output_epoch

        def _do() -> None:
            with self._lock:
                if epoch != self._epoch:
                    return
                if automatic and (output_epoch != self._output_epoch
                                  or not self._auto_speech or self._paused):
                    return
                try:
                    self._speak(text)
                except Exception as exc:
                    LOG.debug("subtitle speech: speak failed", exc_info=True)
                    if self._on_speak_error is not None:
                        try:
                            self._on_speak_error(text, exc)
                        except Exception:
                            LOG.debug("subtitle speech: error callback failed",
                                      exc_info=True)

        try:
            self._ui_thread(_do)
        except Exception:
            LOG.debug("subtitle speech: ui_thread marshal failed", exc_info=True)

    def clear(self) -> None:
        """Clear all cue state (track change, stop, source switch, disconnect).

        Review history is cleared too: review must never expose cues from a
        previous channel, programme, media generation or subtitle track.
        """
        with self._lock:
            self._epoch += 1
            self._current = None
            self._previous = None
            self._recent.clear()

    def set_source(self, name: str) -> None:
        """Switch the active cue source, clearing stale state first."""
        with self._lock:
            self._snapshot_identity = None
            self._snapshot_sequence = 0
            self._source_name = name or ""
            self._paused = False
            self._capabilities.clear()
            self.clear()

    def speak_review(self, text: str) -> None:
        """Read source-owned review text through the same validated backend."""
        with self._lock:
            if text:
                self._speak_text(text)

    # -- On-demand reading --------------------------------------------------

    def read_current(self) -> bool:
        """Speak the current cue. Returns True if there was one."""
        with self._lock:
            text = self._current.text if self._current else None
            if text:
                self._speak_text(text)
                return True
        return False

    def read_previous(self) -> bool:
        """Speak the previous cue. Returns True if there was one."""
        with self._lock:
            previous = self._previous if self._current else (self._recent[-1] if self._recent else None)
            if previous:
                self._speak_text(previous.text)
                return True
        return False

    def get_recent(self, count: int = 10) -> List[CueEvent]:
        """Recent cues, oldest first, for review."""
        with self._lock:
            items = list(self._recent)
        return items[-count:] if count > 0 else items

    # -- Capabilities -------------------------------------------------------

    def set_capability(self, player: str, capability: str, state: str) -> None:
        """Record a capability state for a player."""
        if capability not in ALL_CAPABILITIES:
            raise ValueError(f"Unknown capability: {capability}")
        if state not in (AVAILABLE, UNAVAILABLE, UNVERIFIED):
            raise ValueError(f"Unknown state: {state}")
        with self._lock:
            self._capabilities.setdefault(player, {})[capability] = state

    def get_capability(self, player: str, capability: str) -> str:
        """Capability state: recorded value, else the honest baseline, else unverified."""
        with self._lock:
            recorded = self._capabilities.get(player, {}).get(capability)
            if recorded is not None:
                return recorded
            return BASELINE_CAPABILITIES.get(player, {}).get(capability, UNVERIFIED)

    def get_capabilities(self, player: str) -> Dict[str, str]:
        """All capability states for a player."""
        with self._lock:
            return {cap: self.get_capability(player, cap) for cap in ALL_CAPABILITIES}

    def describe_capability(
        self,
        player: str,
        capability: str,
        gettext: Optional[Callable[[str], str]] = None,
    ) -> str:
        """Short human-readable state for UI reporting.

        User-facing descriptions go through the caller's translation
        function (issue #37) rather than staying hard-coded English.
        """
        _ = gettext or (lambda s: s)
        state = self.get_capability(player, capability)
        if state == AVAILABLE:
            return _("available")
        if state == UNAVAILABLE:
            return _("not supported by this player")
        return _("not verified yet")
