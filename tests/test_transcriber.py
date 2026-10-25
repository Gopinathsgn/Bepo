"""
core/transcriber.py: model lifecycle, dictation sessions, and settings applied at runtime.
The model and the microphone session are faked.
"""

import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core import engine
from core.engine import EngineSettings
from core.transcriber import TranscriberThread

_app = QApplication.instance() or QApplication([])


def wait_for(predicate, timeout: float = 3.0) -> bool:
    """Wait for worker threads while pumping the Qt event loop (queued signals need it)."""
    deadline = time.time() + timeout
    while not predicate() and time.time() < deadline:
        _app.processEvents()
        time.sleep(0.005)
    _app.processEvents()
    return bool(predicate())


class FakeLine:
    def __init__(self, text):
        self.text = text


class FakeModel:
    def __init__(self, name="model"):
        self.name = name
        self.closed = False
        self.keyterms = "unset"

    def set_keyterms(self, terms):
        self.keyterms = terms

    def close(self):
        self.closed = True


class FakeSession:
    """Mimics MicTranscriber: stop() flushes buffered audio and fires on_line synchronously."""

    def __init__(self, on_text, on_line, on_error, flush_lines=(), flush_partial=None, fail_start=False):
        self.on_text, self.on_line, self.on_error = on_text, on_line, on_error
        self.flush_lines, self.flush_partial, self.fail_start = flush_lines, flush_partial, fail_start
        self.started = self.stopped = self.closed = False

    def start(self):
        if self.fail_start:
            raise OSError("no input device")
        self.started = True

    def stop(self):
        self.stopped = True
        if self.flush_partial:
            self.on_text(self.flush_partial)
        for text in self.flush_lines:
            self.on_line(FakeLine(text))

    def close(self):
        self.closed = True


class Harness:
    """A TranscriberThread whose model loading and microphone sessions are faked."""

    def __init__(self, test: unittest.TestCase, settings=None, preload=None, **session_kwargs):
        self.sessions: list[FakeSession] = []
        self.opened_with: list[EngineSettings] = []
        self.models: list[FakeModel] = []
        self.loaded_models: list[str] = []
        self.session_kwargs = session_kwargs
        self.gate = threading.Event()          # clear() it to hold model loads open
        self.gate.set()

        def load(model_key, vocabulary=()):
            self.gate.wait(3)
            self.loaded_models.append(model_key)
            model = FakeModel(model_key)
            model.keyterms = list(vocabulary)
            self.models.append(model)
            return model

        def open_session(model, s, on_text, on_line, on_error):
            self.opened_with.append(s)
            session = FakeSession(on_text, on_line, on_error, **self.session_kwargs)
            self.sessions.append(session)
            return session

        for p in (mock.patch.object(engine, "load_transcriber", load),
                  mock.patch.object(engine, "open_session", open_session)):
            p.start()
            test.addCleanup(p.stop)

        self.t = TranscriberThread(settings=settings or EngineSettings(), preload=preload)
        self.segments, self.partials, self.finals, self.errors = [], [], [], []
        self.ready_count = self.loading_count = 0
        self.t.segment_text.connect(self.segments.append)
        self.t.partial_text.connect(self.partials.append)
        self.t.final_text.connect(self.finals.append)
        self.t.error.connect(self.errors.append)
        self.t.ready.connect(self._on_ready)
        self.t.loading.connect(self._on_loading)
        self.t.start_loading()

    def _on_ready(self):
        self.ready_count += 1

    def _on_loading(self):
        self.loading_count += 1

    def wait_ready(self, count=1):
        return wait_for(lambda: self.ready_count >= count)

    def finished(self):
        return bool(self.finals or self.errors)


class FlushAndSessionTests(unittest.TestCase):
    def test_sentence_finished_during_stop_is_emitted(self):
        h = Harness(self, flush_lines=["See you tomorrow."])
        self.assertTrue(h.wait_ready())
        h.t.start_recording()
        h.t._on_line(FakeLine("First sentence."))
        self.assertEqual(h.segments, ["First sentence."])
        h.t.stop_recording()
        self.assertTrue(wait_for(h.finished))
        self.assertEqual(h.segments, ["First sentence.", "See you tomorrow."])
        self.assertEqual(h.finals, ["First sentence. See you tomorrow."])
        self.assertEqual(h.errors, [])

    def test_uncommitted_partial_is_flushed_once(self):
        h = Harness(self)
        h.wait_ready()
        h.t.start_recording()
        h.t._on_partial("almost done")
        h.t.stop_recording()
        self.assertTrue(wait_for(h.finished))
        self.assertEqual((h.segments, h.finals), (["almost done"], ["almost done"]))

    def test_no_speech(self):
        h = Harness(self)
        h.wait_ready()
        h.t.start_recording()
        h.t.stop_recording()
        self.assertTrue(wait_for(h.finished))
        self.assertEqual((h.segments, h.finals, h.errors), ([], [], ["No speech detected"]))

    def test_callbacks_after_stop_are_ignored(self):
        h = Harness(self)
        h.wait_ready()
        h.t.start_recording()
        h.t.stop_recording()
        self.assertTrue(wait_for(h.finished))
        h.t._on_line(FakeLine("late"))
        self.assertEqual(h.segments, [])

    def test_microphone_session_is_closed_after_every_dictation(self):
        h = Harness(self)
        h.wait_ready()
        for n in (1, 2):
            h.t.start_recording()
            h.t.stop_recording()
            self.assertTrue(wait_for(lambda: not h.t._stopping and len(h.errors) + len(h.finals) >= n))
        self.assertEqual(len(h.sessions), 2)
        self.assertTrue(all(s.started and s.stopped and s.closed for s in h.sessions))
        self.assertIsNone(h.t._session)
        self.assertFalse(h.models[0].closed)             # the model is kept for the next dictation

    def test_mid_session_error_releases_the_microphone(self):
        h = Harness(self)
        h.wait_ready()
        h.t.start_recording()
        session = h.sessions[0]
        session.on_error(OSError("device unplugged"))
        self.assertTrue(wait_for(lambda: session.closed))
        self.assertEqual(h.errors, ["device unplugged"])
        self.assertIsNone(h.t._session)
        self.assertFalse(h.t._recording)

    def test_starting_again_closes_a_leftover_session(self):
        h = Harness(self)
        h.wait_ready()
        h.t.start_recording()
        h.t.start_recording()
        self.assertEqual(len(h.sessions), 2)
        self.assertTrue(h.sessions[0].closed)
        self.assertFalse(h.sessions[1].closed)

    def test_microphone_is_released_when_it_fails_to_open(self):
        h = Harness(self, fail_start=True)
        h.wait_ready()
        h.t.start_recording()
        self.assertTrue(h.errors and h.errors[0].startswith("Microphone error"))
        self.assertTrue(h.sessions[0].closed)
        self.assertFalse(h.t._recording)
        h.t.stop_recording()                              # harmless no-op

    def test_double_stop_and_restart_guard(self):
        h = Harness(self)
        h.wait_ready()
        h.t.start_recording()
        h.t._stopping = True
        h.t.stop_recording()
        self.assertEqual(len(h.sessions), 1)
        h.t.start_recording()
        self.assertTrue(h.errors and "previous dictation" in h.errors[-1])

    def test_not_ready_yet(self):
        with mock.patch.object(engine, "load_transcriber", lambda *a, **k: time.sleep(0.3) or FakeModel()):
            t = TranscriberThread()
            errors = []
            t.error.connect(errors.append)
            t.start_loading()
            t.start_recording()
            self.assertEqual(errors, ["Model is still loading, please wait a moment..."])
            wait_for(lambda: t._ready)


class LoadingTests(unittest.TestCase):
    def test_load_failure_is_reported_clearly(self):
        with mock.patch.object(engine, "load_transcriber", side_effect=RuntimeError("boom")):
            t = TranscriberThread()
            errors = []
            t.error.connect(errors.append)
            t.start_loading()
            self.assertTrue(wait_for(lambda: t._load_error is not None))
            t.start_recording()
        self.assertEqual(errors[0], "Model error: boom")
        self.assertEqual(errors[-1], "Speech model failed to load: boom")

    def test_preloaded_model_is_adopted_without_loading_again(self):
        model = FakeModel("preloaded")

        class Preload:
            settings = EngineSettings(model="small", vocabulary=())

            def take(self):
                return model

        h = Harness(self, settings=EngineSettings(model="small", vocabulary=("Bepo",)), preload=Preload())
        self.assertTrue(h.wait_ready())
        self.assertEqual(h.loaded_models, [])             # nothing was loaded a second time
        self.assertIs(h.t._engine, model)
        self.assertEqual(model.keyterms, ["Bepo"])        # the user's vocabulary is applied to it

    def test_preload_for_another_model_is_ignored(self):
        class Preload:
            settings = EngineSettings(model="small")

            def take(self):
                raise AssertionError("must not be used")

        h = Harness(self, settings=EngineSettings(model="tiny"), preload=Preload())
        self.assertTrue(h.wait_ready())
        self.assertEqual(h.loaded_models, ["tiny"])

    def test_cleanup_releases_everything(self):
        h = Harness(self)
        h.wait_ready()
        h.t.start_recording()
        h.t.cleanup()
        self.assertTrue(h.sessions[0].closed)
        self.assertTrue(h.models[0].closed)


class ApplySettingsTests(unittest.TestCase):
    def test_vocabulary_changes_apply_live_without_reloading(self):
        h = Harness(self)
        h.wait_ready()
        h.t.apply_settings(EngineSettings(vocabulary=("Kubernetes", "Bepo")))
        self.assertEqual(h.models[0].keyterms, ["Kubernetes", "Bepo"])
        self.assertEqual(h.loaded_models, ["small"])      # no reload
        h.t.apply_settings(EngineSettings(vocabulary=()))
        self.assertIsNone(h.models[0].keyterms)

    def test_microphone_and_interval_apply_from_the_next_dictation(self):
        h = Harness(self)
        h.wait_ready()
        h.t.apply_settings(EngineSettings(update_interval=0.5, device="USB Mic"))
        h.t.start_recording()
        self.assertEqual((h.opened_with[-1].update_interval, h.opened_with[-1].device), (0.5, "USB Mic"))
        self.assertEqual(h.loaded_models, ["small"])      # still no reload

    def test_changing_the_model_reloads_in_the_background(self):
        h = Harness(self)
        h.wait_ready()
        old = h.models[0]
        h.gate.clear()
        h.t.apply_settings(EngineSettings(model="medium"))
        self.assertEqual(h.loading_count, 1)
        self.assertTrue(old.closed)
        errors = []
        h.t.error.connect(errors.append)
        h.t.start_recording()                              # while loading
        self.assertEqual(errors, ["Model is still loading, please wait a moment..."])
        h.gate.set()
        self.assertTrue(h.wait_ready(2))
        self.assertEqual(h.loaded_models, ["small", "medium"])
        h.t.start_recording()
        self.assertTrue(h.sessions)                        # dictation works on the new model

    def test_model_change_during_dictation_waits_until_it_ends(self):
        h = Harness(self)
        h.wait_ready()
        h.t.start_recording()
        h.t.apply_settings(EngineSettings(model="tiny"))
        self.assertEqual(h.loaded_models, ["small"])      # not yet: a dictation is running
        h.t.stop_recording()
        self.assertTrue(h.wait_ready(2))
        self.assertEqual(h.loaded_models, ["small", "tiny"])

    def test_superseded_reload_is_discarded(self):
        gate = threading.Event()
        loaded: list[FakeModel] = []

        def slow_load(model_key, vocabulary=()):
            if model_key == "medium":
                gate.wait(2)
            model = FakeModel(model_key)
            loaded.append(model)
            return model

        with mock.patch.object(engine, "load_transcriber", slow_load):
            t = TranscriberThread(settings=EngineSettings(model="small"))
            t.start_loading()
            wait_for(lambda: t._ready)
            t.apply_settings(EngineSettings(model="medium"))      # slow
            t.apply_settings(EngineSettings(model="tiny"))        # supersedes it
            wait_for(lambda: t._ready)
            gate.set()
            time.sleep(0.2)
            _app.processEvents()
            self.assertEqual(t._engine.name, "tiny")
            self.assertTrue([m for m in loaded if m.name == "medium"][0].closed)   # stale one closed


if __name__ == "__main__":
    unittest.main()
