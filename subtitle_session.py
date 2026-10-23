"""Session ownership for subtitle producers and delayed UI work.

Lifecycle transitions run on the UI thread. Reader threads feed a bound
sink that validates ownership under the transition lock. Cleanup never
waits for IPC or a process on the GUI thread.
"""

import logging
import threading
import uuid

LOG = logging.getLogger(__name__)


class _SessionSink:
    def __init__(self, owner, token):
        self._owner, self._token = owner, token

    def _call(self, method, *args, **kwargs):
        with self._owner._lock:
            if self._owner.is_current(self._token):
                return getattr(self._owner._manager, method)(*args, **kwargs)

    def on_snapshot(self, snapshot):
        with self._owner._lock:
            if not self._owner.is_current(self._token):
                return False
            def purge():
                if self._owner._stop_speech:
                    self._owner.dispatch(self._token, self._owner._stop_speech)
            return self._owner._manager.on_snapshot(snapshot, before_reset=purge)

    def on_cue(self, *args, **kwargs):
        return self._call("on_cue", *args, **kwargs)

    def clear(self):
        with self._owner._lock:
            if self._owner.is_current(self._token):
                self._owner._manager.clear()
                if self._owner._stop_speech:
                    self._owner.dispatch(self._token, self._owner._stop_speech)

    def set_paused(self, paused):
        with self._owner._lock:
            changed = self._call("set_paused", paused)
            if changed and paused and self._owner._stop_speech:
                self._owner.dispatch(self._token, self._owner._stop_speech)
            return changed

    def set_capability(self, *args):
        return self._call("set_capability", *args)

    def speak_review(self, text):
        return self._call("speak_review", text)


class SubtitleSessionController:
    def __init__(self, manager, stop_speech=None):
        self._manager = manager
        self._stop_speech = stop_speech
        self._lock = threading.RLock()
        self._session_token = None
        self._adapter = None
        self._ui_thread = lambda fn: fn()

    def set_ui_thread(self, ui_thread):
        self._ui_thread = ui_thread

    @property
    def session_token(self):
        with self._lock:
            return self._session_token

    def activate_session(self, source_name=""):
        """An accepted playback replacement revokes the previous owner."""
        self.cancel_session(stop_playback=True)
        with self._lock:
            self._session_token = uuid.uuid4().hex
            self._manager.set_source(source_name)
            return self._session_token

    def cancel_session(self, stop_playback=False):
        with self._lock:
            self._session_token = None
            adapter, self._adapter = self._adapter, None
            self._manager.set_source("")
        if self._stop_speech:
            self._stop_speech()
        self._retire(adapter, stop_playback)

    def is_current(self, token):
        with self._lock:
            return token is not None and token == self._session_token

    def bind(self, token):
        return _SessionSink(self, token)

    def set_adapter(self, adapter, token):
        with self._lock:
            if self.is_current(token):
                old, self._adapter = self._adapter, adapter
                accepted = True
            else:
                old, accepted = adapter, False
        if old is not adapter or not accepted:
            self._retire(old, True)
        return accepted

    @staticmethod
    def _retire(adapter, stop_playback):
        if adapter is None:
            return
        # Revoke callbacks and wake requests now; joins/OS I/O belong to the
        # cleanup worker. Disabling automatic speech never calls this path.
        adapter.cancel()

        def cleanup():
            try:
                adapter.close(terminate=stop_playback)
            except Exception:
                LOG.exception("subtitle adapter cleanup failed")
        threading.Thread(target=cleanup, name="subtitle-cleanup", daemon=True).start()

    def dispatch(self, token, callback, *args):
        """Marshal a state change, then validate immediately before use."""
        def run():
            with self._lock:
                if self.is_current(token):
                    callback(*args)
        self._ui_thread(run)

    def speak_validated(self, token, text, speak_fn):
        if not self.is_current(token):
            return False
        self.dispatch(token, speak_fn, text)
        return True
