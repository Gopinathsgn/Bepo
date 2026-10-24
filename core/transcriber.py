"""
transcriber.py
Manages speech recognition on top of core.engine (Moonshine).
All UI updates are emitted via Signal — never touch Qt widgets directly.

Lifecycle:
  * the model is loaded once, on a background thread (or adopted from the early preloader);
  * each dictation opens a short-lived microphone session and closes it afterwards, so the
    microphone is only open while you are actually dictating;
  * settings can be re-applied at runtime: vocabulary immediately, microphone and update
    interval from the next dictation, and a different model by reloading in the background.
"""

import logging
import threading
from PySide6.QtCore import QObject, Signal

from core import engine
from core.engine import EngineSettings


class TranscriberThread(QObject):
    """
    Manages the speech model and dictation sessions and emits Qt signals.

    Signals:
        partial_text(str)  — streaming partial transcript (live pill preview)
        segment_text(str)  — one finished utterance (typed live in continuous mode)
        final_text(str)    — all finalized text of the session
        error(str)         — error message (no speech, mic failure, etc.)
        ready()            — emitted when the model is loaded and ready
        loading()          — emitted when a (re)load of the model starts
    """

    partial_text = Signal(str)
    segment_text = Signal(str)
    final_text   = Signal(str)
    error        = Signal(str)
    ready        = Signal()
    loading      = Signal()

    def __init__(self, parent=None, settings: EngineSettings | None = None, preload=None):
        super().__init__(parent)
        self._settings = settings or EngineSettings()
        self._engine = None                 # loaded moonshine Transcriber (the model)
        self._session = None                # live MicTranscriber, only while dictating
        self._ready = False
        self._load_error: str | None = None
        self._load_generation = 0
        self._reload_pending = False
        # True while a dictation session is live. It deliberately stays True while
        # the microphone is being stopped: stopping flushes the audio that is still
        # buffered and fires the final line callbacks *during* the call, and those
        # last words must still be emitted.
        self._recording = False
        self._stopping = False
        self._completed_lines: list[str] = []
        self._current_partial: str = ""
        self._lock = threading.Lock()
        self._preload = preload

    # ------------------------------------------------------------------ #
    # Model loading                                                       #
    # ------------------------------------------------------------------ #

    def start_loading(self):
        """
        Begin loading the model on a background thread. Call this *after* connecting to
        `ready` / `error`: with the early preloader the model can already be in memory, so
        the signal would otherwise fire before anyone is listening.
        """
        preload, self._preload = self._preload, None
        self._start_loader(preload)

    def _start_loader(self, preload=None):
        self._ready = False
        self._load_error = None
        self._load_generation += 1
        threading.Thread(
            target=self._load_engine, args=(self._load_generation, self._settings, preload),
            daemon=True, name="ModelLoader",
        ).start()

    def _load_engine(self, generation: int, settings: EngineSettings, preload):
        try:
            if preload is not None and preload.settings.model == settings.model:
                loaded = preload.take()
                engine.apply_vocabulary(loaded, settings.vocabulary)
            else:
                loaded = engine.load_transcriber(settings.model, settings.vocabulary)
        except Exception as exc:
            logging.error("[Transcriber] Error loading model: %s", exc)
            if generation == self._load_generation:
                self._load_error = str(exc)
                self.error.emit(f"Model error: {exc}")
            return

        with self._lock:
            if generation != self._load_generation:      # superseded by a newer reload
                stale = loaded
            else:
                stale, self._engine = None, loaded
                self._ready = True
        if stale is not None:
            self._close_engine(stale)
            return
        logging.info("[Transcriber] Moonshine %s model loaded and pre-warmed", settings.model)
        self.ready.emit()

    @staticmethod
    def _close_engine(model):
        try:
            model.close()
        except Exception:
            pass

    def _reload(self):
        """Replace the loaded model with the one in the current settings (background)."""
        with self._lock:
            old, self._engine = self._engine, None
        if old is not None:
            self._close_engine(old)
        self._reload_pending = False
        self.loading.emit()
        self._start_loader()

    # ------------------------------------------------------------------ #
    # Settings                                                            #
    # ------------------------------------------------------------------ #

    def apply_settings(self, settings: EngineSettings):
        """Re-apply settings at runtime (see module docstring for what takes effect when)."""
        previous, self._settings = self._settings, settings
        if settings.model != previous.model:
            if self._recording or self._stopping:
                self._reload_pending = True          # reload as soon as this dictation ends
            else:
                self._reload()
        elif settings.vocabulary != previous.vocabulary and self._engine is not None:
            engine.apply_vocabulary(self._engine, settings.vocabulary)

    # ------------------------------------------------------------------ #
    # Public API (called from Qt main thread)                            #
    # ------------------------------------------------------------------ #

    def start_recording(self):
        """Open the microphone and begin listening."""
        if self._load_error is not None:
            self.error.emit(f"Speech model failed to load: {self._load_error}")
            return
        if not self._ready or self._engine is None:
            self.error.emit("Model is still loading, please wait a moment...")
            return
        if self._stopping:
            self.error.emit("Still finishing the previous dictation, try again in a moment...")
            return

        with self._lock:
            self._recording = True
            self._completed_lines.clear()
            self._current_partial = ""

        try:
            self._session = engine.open_session(
                self._engine, self._settings, self._on_partial, self._on_line, self._on_error
            )
            self._session.start()
            logging.info("[Transcriber] Microphone listening started")
        except Exception as exc:
            self._recording = False
            self._release_session()
            self.error.emit(f"Microphone error: {exc}")

    def stop_recording(self):
        """Stop listening and finalize speech on a worker thread."""
        if not self._recording or self._stopping:
            return

        self._stopping = True
        threading.Thread(target=self._async_stop, daemon=True, name="TranscriberStop").start()

    def _release_session(self):
        """Close the dictation session, which releases the microphone (the model stays loaded)."""
        session, self._session = self._session, None
        if session is not None:
            try:
                session.close()
            except Exception as exc:
                logging.warning("[Transcriber] Error closing microphone: %s", exc)

    def _async_stop(self):
        try:
            # Callbacks fired while the mic flushes still count (self._recording is
            # True), so the last utterance is injected like every earlier one.
            if self._session is not None:
                self._session.stop()
        except Exception as exc:
            logging.error("[Transcriber] Error stopping mic: %s", exc)
            self._release_session()
            self._recording = False
            self._stopping = False
            self.error.emit(str(exc))
            return

        self._release_session()

        # Assemble finalized text and check for uncommitted partials
        with self._lock:
            self._recording = False
            trailing = self._current_partial.strip()
            self._current_partial = ""
            if trailing:
                if not self._completed_lines or self._completed_lines[-1] != trailing:
                    self._completed_lines.append(trailing)
                    trailing_to_emit = trailing
                else:
                    trailing_to_emit = ""
            else:
                trailing_to_emit = ""
            full_text = " ".join(self._completed_lines).strip()

        # Flush any trailing words that were spoken right before stop
        if trailing_to_emit:
            self.segment_text.emit(trailing_to_emit)

        self._stopping = False
        logging.info("[Transcriber] Transcription finalized (%d characters)", len(full_text))
        if full_text:
            self.final_text.emit(full_text)
        else:
            self.error.emit("No speech detected")

        if self._reload_pending:
            self._reload()

    def cleanup(self):
        """Release audio devices and model resources."""
        self._recording = False
        self._stopping = False
        self._release_session()
        with self._lock:
            model, self._engine = self._engine, None
            self._ready = False
        if model is not None:
            self._close_engine(model)

    def quit(self):
        """Compatibility shim for QThread callers."""
        self.cleanup()

    def wait(self, ms: int = 0):
        """Compatibility shim for QThread callers."""
        pass

    # ------------------------------------------------------------------ #
    # Moonshine callbacks (fire on Moonshine worker thread)              #
    # Signal.emit is thread-safe and safely marshals to Qt main thread     #
    # ------------------------------------------------------------------ #

    def _on_partial(self, text: str):
        if not self._recording:
            return
        with self._lock:
            self._current_partial = text.strip()
        if self._recording and self._current_partial:
            self.partial_text.emit(self._current_partial)

    def _on_line(self, line) -> None:
        """Called when an utterance or phrase is finalized by Moonshine."""
        text = line.text if hasattr(line, "text") else str(line)
        text = text.strip()
        if not text:
            return
        with self._lock:
            self._completed_lines.append(text)
            self._current_partial = ""
        if self._recording:
            self.segment_text.emit(text)

    def _on_error(self, exc: BaseException):
        self.error.emit(str(exc))
