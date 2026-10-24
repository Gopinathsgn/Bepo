"""
engine.py
The speech engine layer: loading the Moonshine model and opening dictation sessions.
Pure Python (no Qt), so the model can start loading while the UI is still being built.

Design:
  * The model (`moonshine_voice.Transcriber`) is loaded once and kept for the life of the app
    (or until the user picks another model).
  * Every dictation opens a short-lived `MicTranscriber` on top of that model and closes it
    afterwards. MicTranscriber.stop() alone leaves the microphone device open, so closing the
    session is what actually releases the microphone between dictations.
"""

import logging
import threading
from dataclasses import dataclass

from core import audio_devices
from core.config import update_interval as _update_interval
from setup import model_downloader


@dataclass(frozen=True)
class EngineSettings:
    model: str = model_downloader.DEFAULT_MODEL
    update_interval: float = 1.0
    device: str | None = None
    vocabulary: tuple[str, ...] = ()

    @classmethod
    def from_config(cls, config: dict) -> "EngineSettings":
        return cls(
            model=config["speech_model"],
            update_interval=_update_interval(config),
            device=config.get("microphone"),
            vocabulary=tuple(config.get("custom_vocabulary") or ()),
        )


def load_transcriber(model_key: str, vocabulary=()):
    """Load a model from disk (never downloads). Blocking: run it on a worker thread."""
    from moonshine_voice import Transcriber

    path = model_downloader.find_installed_model(model_key)
    if path is None:
        raise RuntimeError(f"The {model_downloader.MODELS[model_key].label} speech model is not downloaded")
    logging.info("[Engine] Loading %s model from %s", model_key, path)
    transcriber = Transcriber(str(path), model_downloader.model_arch(model_key))
    apply_vocabulary(transcriber, vocabulary)
    _prewarm(transcriber)
    return transcriber


def _prewarm(transcriber) -> None:
    """Run 0.1 s of silence through the model to build its execution plan up front."""
    try:
        import numpy as np
        transcriber.transcribe_without_streaming(np.zeros(1600, dtype=np.float32), 16000)
    except Exception:
        pass


def apply_vocabulary(transcriber, terms) -> bool:
    """Bias recognition towards custom words/phrases (can be changed at any time)."""
    try:
        transcriber.set_keyterms(list(terms) if terms else None)
        return True
    except Exception as exc:
        logging.warning("[Engine] Could not apply custom vocabulary: %s", exc)
        return False


def open_session(transcriber, settings: EngineSettings, on_text, on_line, on_error):
    """
    Create a dictation session on a loaded model. Call .start() to open the microphone and
    .stop() then .close() when done (close() releases the microphone; the model stays loaded).
    """
    from moonshine_voice import MicTranscriber

    mic = (
        MicTranscriber()
        .use_transcriber(transcriber)
        .update_interval(settings.update_interval)
        .on_text(on_text)
        .on_line(on_line)
        .on_error(on_error)
    )
    device = audio_devices.resolve_device(settings.device)
    if device is not None:
        mic.device(device)
    mic.load()      # cheap here: the model is already loaded, this only creates the stream
    return mic


class Preloader(threading.Thread):
    """Loads the model in the background as early as possible during start-up."""

    def __init__(self, settings: EngineSettings):
        super().__init__(daemon=True, name="ModelPreloader")
        self.settings = settings
        self.transcriber = None
        self.error: BaseException | None = None

    def run(self):
        try:
            self.transcriber = load_transcriber(self.settings.model, self.settings.vocabulary)
        except BaseException as exc:      # reported by whoever collects the result
            self.error = exc

    def take(self):
        """Wait for the load to finish and return the Transcriber (raises the load error)."""
        self.join()
        if self.error is not None:
            raise self.error
        transcriber, self.transcriber = self.transcriber, None
        return transcriber
