"""
core/engine.py: opening dictation sessions on a loaded model.

The real moonshine_voice classes are used, but the model and the audio device are faked, so
nothing here loads a model or opens a microphone.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import config, engine
from core.engine import EngineSettings


class FakeStream:
    def __init__(self):
        self.listeners, self.started, self.stopped, self.closed = [], False, False, False

    def add_listener(self, listener):
        self.listeners.append(listener)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def add_audio(self, data, sample_rate=16000):
        pass

    def close(self):
        self.closed = True


class FakeModel:
    """Stands in for moonshine_voice.Transcriber."""

    def __init__(self):
        self.interval_requested = None
        self.stream = FakeStream()
        self.closed = False
        self.keyterms = "unset"

    def create_stream(self, update_interval=None, flags=0, transcribe_flags=0):
        self.interval_requested = update_interval
        return self.stream

    def set_keyterms(self, terms):
        self.keyterms = terms

    def close(self):
        self.closed = True


class FakeInputStream:
    """Stands in for sounddevice.InputStream."""
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.started = self.closed = False
        FakeInputStream.instances.append(self)

    def start(self):
        self.started = True

    def close(self):
        self.closed = True


class EngineSettingsTests(unittest.TestCase):
    def test_from_config(self):
        cfg = config.normalize({"speech_model": "medium", "responsiveness": "fast",
                                "microphone": "USB Mic", "custom_vocabulary": ["Bepo", "Gopinath"]})
        s = EngineSettings.from_config(cfg)
        self.assertEqual((s.model, s.update_interval, s.device, s.vocabulary),
                         ("medium", 0.5, "USB Mic", ("Bepo", "Gopinath")))

    def test_default_settings_use_the_efficient_interval(self):
        self.assertEqual(EngineSettings.from_config(config.normalize({})).update_interval, 1.0)


class SessionTests(unittest.TestCase):
    def setUp(self):
        FakeInputStream.instances.clear()
        self.model = FakeModel()
        patcher = mock.patch("moonshine_voice.mic_transcriber.sd.InputStream", FakeInputStream)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _open(self, settings=None, device=None):
        with mock.patch.object(engine.audio_devices, "resolve_device", return_value=device):
            return engine.open_session(self.model, settings or EngineSettings(), lambda t: None,
                                       lambda l: None, lambda e: None)

    def test_session_reuses_the_loaded_model_and_applies_the_interval(self):
        mic = self._open(EngineSettings(update_interval=1.0))
        self.assertIs(mic.transcriber, self.model)
        self.assertEqual(self.model.interval_requested, 1.0)
        mic = self._open(EngineSettings(update_interval=0.5))
        self.assertEqual(self.model.interval_requested, 0.5)

    def test_chosen_microphone_is_used(self):
        mic = self._open(device=7)
        mic.start()
        try:
            self.assertEqual(FakeInputStream.instances[-1].kwargs["device"], 7)
        finally:
            mic.stop()
            mic.close()

    def test_default_microphone_when_none_is_chosen(self):
        mic = self._open(device=None)
        mic.start()
        try:
            self.assertIsNone(FakeInputStream.instances[-1].kwargs["device"])
        finally:
            mic.stop()
            mic.close()

    def test_close_releases_the_microphone_but_keeps_the_model(self):
        mic = self._open()
        mic.start()
        device = FakeInputStream.instances[-1]
        self.assertTrue(device.started)
        mic.stop()
        # Upstream quirk this design works around: stop() alone leaves the device open
        self.assertFalse(device.closed)
        mic.close()
        self.assertTrue(device.closed)                 # microphone released
        self.assertTrue(self.model.stream.closed)
        self.assertFalse(self.model.closed)            # model stays loaded for the next dictation

    def test_every_dictation_opens_its_own_device(self):
        for _ in range(2):
            mic = self._open()
            mic.start()
            mic.stop()
            mic.close()
        self.assertEqual(len(FakeInputStream.instances), 2)
        self.assertTrue(all(i.closed for i in FakeInputStream.instances))


class ModelLoadingTests(unittest.TestCase):
    def test_load_requires_an_installed_model(self):
        with mock.patch.object(engine.model_downloader, "find_installed_model", return_value=None):
            with self.assertRaises(RuntimeError):
                engine.load_transcriber("medium")

    def test_vocabulary_is_applied_and_failures_are_reported_not_raised(self):
        model = FakeModel()
        self.assertTrue(engine.apply_vocabulary(model, ["Kubernetes"]))
        self.assertEqual(model.keyterms, ["Kubernetes"])
        self.assertTrue(engine.apply_vocabulary(model, []))
        self.assertIsNone(model.keyterms)              # empty list switches biasing off

        class Broken:
            def set_keyterms(self, terms):
                raise ValueError("boom")
        self.assertFalse(engine.apply_vocabulary(Broken(), ["x"]))

    def test_preloader_returns_the_model_once(self):
        with mock.patch.object(engine, "load_transcriber", return_value="MODEL"):
            preload = engine.Preloader(EngineSettings(model="tiny"))
            preload.start()
            self.assertEqual(preload.take(), "MODEL")
            self.assertIsNone(preload.take())

    def test_preloader_surfaces_load_errors(self):
        with mock.patch.object(engine, "load_transcriber", side_effect=RuntimeError("no model")):
            preload = engine.Preloader(EngineSettings())
            preload.start()
            with self.assertRaises(RuntimeError):
                preload.take()


if __name__ == "__main__":
    unittest.main()
