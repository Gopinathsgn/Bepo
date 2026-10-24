"""
Whole dictation sessions through the real BepoApp controller, with fakes for the transcriber,
hotkey manager and pill and with SendInput/clipboard mocked. Qt runs on the offscreen platform.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


class FakeTranscriber(QObject):
    partial_text = Signal(str)
    segment_text = Signal(str)
    final_text = Signal(str)
    error = Signal(str)
    ready = Signal()
    loading = Signal()

    def __init__(self, parent=None, settings=None, preload=None):
        super().__init__(parent)
        self.settings = settings
        self.applied = []
        self.fail_to_start = False

    def start_loading(self):
        pass

    def start_recording(self):
        if self.fail_to_start:
            self.error.emit("Microphone error: nope")

    def stop_recording(self):
        pass

    def apply_settings(self, settings):
        self.applied.append(settings)

    def quit(self):
        pass

    def wait(self, ms=0):
        pass


class FakeHotkey(QObject):
    toggle_activated = Signal()
    ptt_pressed = Signal()
    ptt_released = Signal()
    esc_pressed = Signal()
    registration_issue = Signal(str)

    def __init__(self, parent=None, toggle=None, ptt=None):
        super().__init__(parent)
        self.toggle_label = "Ctrl+Win"
        self.ptt_label = "Ctrl+Space"
        self.reconfigured = []
        self.calls = []

    def start(self):
        pass

    def stop(self):
        pass

    def suspend(self):
        self.calls.append("suspend")

    def resume(self):
        self.calls.append("resume")

    def reconfigure(self, toggle, ptt):
        self.reconfigured.append((toggle, ptt))

    def start_esc_watcher(self):
        pass

    def stop_esc_watcher(self):
        pass


class FakePill:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args))
        return record

    def names(self):
        return [c[0] for c in self.calls]


class SessionFlowTests(unittest.TestCase):
    def setUp(self):
        import main
        self.main = main
        self.injections, self.deletions, self.earcons = [], [], []
        self.injector_config = []
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.user_cfg = Path(self._tmp.name) / "config.json"
        patches = [
            mock.patch.object(main, "TranscriberThread", FakeTranscriber),
            mock.patch.object(main, "HotkeyManager", FakeHotkey),
            mock.patch.object(main, "PillWindow", FakePill),
            mock.patch.object(main, "_play_earcon", lambda cue: self.earcons.append(cue)),
            mock.patch.object(main, "_load_config", lambda: dict(main.app_config.DEFAULT_CONFIG)),
            mock.patch.object(main, "enqueue_injection",
                              lambda text, session=None: self.injections.append(text)),
            mock.patch.object(main, "enqueue_deletion",
                              lambda count, session=None: self.deletions.append(count)),
            mock.patch.object(main, "configure_injector",
                              lambda **kw: self.injector_config.append(kw)),
            mock.patch.object(main.app_config, "USER_CONFIG_PATH", self.user_cfg),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        main.ICON_IDLE = main.ICON_ACTIVE = None
        self.ctrl = main.BepoApp(_app)
        self.addCleanup(self.ctrl._tray.hide)
        self.pill = self.ctrl._pill

    # helpers -------------------------------------------------------------
    def start(self, mode="toggle"):
        self.ctrl._start_recording(mode=mode)

    def say(self, text):
        self.ctrl._transcriber.segment_text.emit(text)
        _app.processEvents()

    def stop(self, final_text):
        self.ctrl._stop_recording()
        self.ctrl._transcriber.final_text.emit(final_text)
        _app.processEvents()

    # dictation scenarios -------------------------------------------------
    def test_multi_sentence_session_is_not_retyped_on_stop(self):
        self.start()
        self.say("Hello world.")
        self.say("How are you today?")
        self.stop("Hello world. How are you today?")
        self.assertEqual(self.injections, ["Hello world.", " How are you today?"])
        self.assertIn("show_done", self.pill.names())

    def test_delete_all_then_stop_does_not_retype_deleted_text(self):
        self.start()
        self.say("Hello world.")
        self.say("Delete all.")
        self.stop("Hello world. Delete all.")
        self.assertEqual(self.injections, ["Hello world."])
        self.assertEqual(self.deletions, [len("Hello world.")])
        self.assertNotIn("show_error", self.pill.names())

    def test_delete_last_word_to_empty_then_stop(self):
        self.start()
        self.say("Hello.")
        self.say("Delete last word.")
        self.stop("Hello. Delete last word.")
        self.assertEqual(self.injections, ["Hello."])

    def test_scratch_only_segment_then_stop_is_not_an_error(self):
        self.start()
        self.say("Send the report.")
        self.say("Scratch that.")
        self.stop("Send the report. Scratch that.")
        self.assertEqual(self.injections, ["Send the report."])
        self.assertNotIn("show_error", self.pill.names())

    def test_only_fillers_reports_no_speech(self):
        self.start()
        self.say("Um.")
        self.stop("Um.")
        self.assertEqual(self.injections, [])
        self.assertIn("show_error", self.pill.names())

    def test_single_utterance_flushed_at_stop_is_typed_once(self):
        self.start()
        self.say("Just one sentence.")
        self.stop("Just one sentence.")
        self.assertEqual(self.injections, ["Just one sentence."])

    def test_ptt_injects_full_transcript_on_release(self):
        self.start(mode="ptt")
        self.say("hello there")
        self.assertEqual(self.injections, [])
        self.stop("hello there")
        self.assertEqual(self.injections, ["Hello there"])

    def test_nothing_handled_falls_back_to_full_text(self):
        self.start()
        self.stop("fallback text")
        self.assertEqual(self.injections, ["Fallback text"])

    def test_empty_session_reports_no_speech(self):
        self.start()
        self.stop("")
        self.assertEqual(self.injections, [])
        self.assertIn("show_error", self.pill.names())

    def test_state_resets_between_sessions(self):
        self.start()
        self.say("First.")
        self.stop("First.")
        self.injections.clear()
        self.start()
        self.say("Second.")
        self.stop("Second.")
        self.assertEqual(self.injections, ["Second."])

    # start cue ------------------------------------------------------------
    def test_start_cue_plays_once_the_microphone_is_open(self):
        self.start()
        self.assertEqual(self.earcons, ["start"])

    def test_no_start_cue_when_the_microphone_fails(self):
        self.ctrl._transcriber.fail_to_start = True
        self.start()
        _app.processEvents()
        self.assertEqual(self.earcons, [])
        self.assertFalse(self.ctrl._recording)
        self.assertIn("show_error", self.pill.names())

    # tray / hotkeys -------------------------------------------------------
    def test_tray_labels_follow_hotkey(self):
        self.assertIn("Ctrl+Win", self.ctrl._dictate_action.text())
        self.ctrl._hotkey.toggle_label = ""
        self.ctrl._update_tray_state(recording=False)
        self.assertNotIn("Ctrl+Win", self.ctrl._dictate_action.text())

    def test_hotkey_issue_is_shown_in_tray(self):
        with mock.patch.object(self.ctrl._tray, "showMessage") as show:
            self.ctrl._hotkey.registration_issue.emit("Ctrl+Space is taken")
            _app.processEvents()
        show.assert_called_once()
        self.assertIn("Ctrl+Space is taken", show.call_args.args[1])

    def test_tray_menu_has_settings_not_a_file_opener(self):
        texts = [a.text() for a in self.ctrl._tray.contextMenu().actions()]
        self.assertTrue(any("Settings" in t for t in texts))
        self.assertFalse(any("Settings File" in t for t in texts))

    # idle memory ------------------------------------------------------------
    def test_memory_trim_is_scheduled_after_a_session_and_skipped_while_recording(self):
        self.start()
        self.assertFalse(self.ctrl._trim_timer.isActive())
        self.stop("")
        self.assertTrue(self.ctrl._trim_timer.isActive())
        with mock.patch.object(self.main.memory, "trim_working_set") as trim:
            self.ctrl._recording = True
            self.ctrl._trim_memory()
            trim.assert_not_called()
            self.ctrl._recording = False
            self.ctrl._trim_memory()
            trim.assert_called_once()

    # settings -----------------------------------------------------------------
    def _config(self, **changes):
        cfg = dict(self.ctrl._config)
        cfg.update(changes)
        return cfg

    def test_apply_settings_updates_behaviour_immediately(self):
        self.ctrl.apply_settings(self._config(continuous_mode=False, enable_emojis=False,
                                              clipboard_safety_net=True,
                                              safety_idle_timeout_seconds=600))
        self.assertFalse(self.ctrl._continuous_mode)
        self.assertFalse(self.ctrl._enable_emojis)
        self.assertEqual(self.ctrl._safety_idle_timeout, 600.0)
        self.assertEqual(self.injector_config[-1], {"clipboard_safety_net": True})

    def test_apply_settings_reconfigures_hotkeys_only_when_they_changed(self):
        self.ctrl.apply_settings(self._config(enable_emojis=False))
        self.assertEqual(self.ctrl._hotkey.reconfigured, [])
        self.ctrl.apply_settings(self._config(hotkey_ptt="ctrl+alt+space"))
        self.assertEqual(self.ctrl._hotkey.reconfigured, [("ctrl+win", "ctrl+alt+space")])

    def test_apply_settings_forwards_engine_settings(self):
        self.ctrl.apply_settings(self._config(speech_model="medium", responsiveness="fast",
                                              custom_vocabulary=["Kubernetes"], microphone="USB Mic"))
        applied = self.ctrl._transcriber.applied[-1]
        self.assertEqual((applied.model, applied.update_interval, applied.device, applied.vocabulary),
                         ("medium", 0.5, "USB Mic", ("Kubernetes",)))

    def test_apply_settings_persists_only_changes(self):
        import json
        self.ctrl.apply_settings(self._config(enable_emojis=False, speech_model="tiny"))
        saved = json.loads(self.user_cfg.read_text(encoding="utf-8"))
        self.assertEqual(saved, {"enable_emojis": False, "speech_model": "tiny"})

    def test_apply_settings_survives_unwritable_config(self):
        with mock.patch.object(self.main.app_config, "save_user_config", side_effect=OSError("disk full")), \
                mock.patch.object(self.ctrl._tray, "showMessage") as show:
            self.ctrl.apply_settings(self._config(enable_emojis=False))
        self.assertFalse(self.ctrl._enable_emojis)          # still applied
        show.assert_called_once()

    def test_saved_signal_toggles_launch_at_startup(self):
        with mock.patch.object(self.main.startup, "is_enabled", return_value=False), \
                mock.patch.object(self.main.startup, "set_enabled", return_value=True) as set_enabled:
            self.ctrl._on_settings_saved(self._config(), True)
            set_enabled.assert_called_once_with(True)
        with mock.patch.object(self.main.startup, "is_enabled", return_value=True), \
                mock.patch.object(self.main.startup, "set_enabled") as set_enabled:
            self.ctrl._on_settings_saved(self._config(), True)       # unchanged -> untouched
            set_enabled.assert_not_called()

    def test_settings_window_opens_once_and_gets_hotkey_hooks(self):
        created = []

        class FakeDialog(QObject):
            saved = Signal(dict, bool)

            def __init__(self, config, launch_at_startup, suspend_hotkeys, resume_hotkeys):
                super().__init__()
                created.append((config, launch_at_startup, suspend_hotkeys, resume_hotkeys))
                self.shown = 0

            def isVisible(self):
                return self.shown > 0

            def show(self):
                self.shown += 1

            def raise_(self):
                pass

            def activateWindow(self):
                pass

        with mock.patch.object(self.main, "SettingsDialog", FakeDialog), \
                mock.patch.object(self.main.startup, "is_enabled", return_value=True):
            self.ctrl._show_settings()
            self.ctrl._show_settings()                # second click re-uses the open window
        self.assertEqual(len(created), 1)
        config, startup_on, suspend, resume = created[0]
        self.assertTrue(startup_on)
        suspend()
        resume()
        self.assertEqual(self.ctrl._hotkey.calls, ["suspend", "resume"])


class BootstrapTests(unittest.TestCase):
    def test_single_instance_lock(self):
        from core import bootstrap
        name = f"Bepo_Test_Mutex_{os.getpid()}_{__import__('time').time_ns()}"   # never the real app's mutex
        first, _h1 = bootstrap.acquire_single_instance_lock(name)
        second, _h2 = bootstrap.acquire_single_instance_lock(name)
        self.assertTrue(first)
        self.assertFalse(second)

    def test_preload_is_skipped_when_the_model_is_missing(self):
        from core import bootstrap, config
        with mock.patch("setup.model_downloader.is_model_downloaded", return_value=False):
            self.assertIsNone(bootstrap.start_preload(config.normalize({})))

    def test_preload_starts_when_the_model_is_present(self):
        from core import bootstrap, config, engine
        with mock.patch("setup.model_downloader.is_model_downloaded", return_value=True), \
                mock.patch.object(engine, "load_transcriber", return_value="MODEL") as load:
            preload = bootstrap.start_preload(config.normalize({"speech_model": "tiny"}))
            self.assertEqual(preload.take(), "MODEL")
            load.assert_called_once_with("tiny", ())


if __name__ == "__main__":
    unittest.main()
