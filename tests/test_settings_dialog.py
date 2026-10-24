"""The Settings window (ui/settings_dialog.py), driven with real Qt key events on the offscreen platform."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core import config
import ui.settings_dialog as sd
from ui.settings_dialog import HotkeyEdit, SettingsDialog

_app = QApplication.instance() or QApplication([])
CTRL, ALT, SHIFT, META = (Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.AltModifier,
                          Qt.KeyboardModifier.ShiftModifier, Qt.KeyboardModifier.MetaModifier)


class FakeDownload(QObject):
    progress = Signal(int, str)
    finished = Signal()
    error = Signal(str)
    outcome = "ok"
    started_with = []

    def __init__(self, model_key, parent=None):
        super().__init__(parent)
        FakeDownload.started_with.append(model_key)

    def start(self):
        self.progress.emit(50, "encoder.ort")
        if FakeDownload.outcome == "ok":
            self.finished.emit()
        else:
            self.error.emit("network unreachable")


class DialogTestCase(unittest.TestCase):
    installed = {"tiny": True, "small": True, "medium": False}

    def make(self, cfg=None, startup=False, devices=("Mic A", "Mic B")):
        patches = [
            mock.patch.object(sd, "is_model_downloaded", lambda key: self.installed[key]),
            mock.patch.object(sd.audio_devices, "list_input_devices", lambda: list(devices)),
            mock.patch.object(sd, "DownloadThread", FakeDownload),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        FakeDownload.started_with = []
        FakeDownload.outcome = "ok"
        self.suspended = self.resumed = 0
        dialog = SettingsDialog(
            cfg or config.normalize({}), launch_at_startup=startup,
            suspend_hotkeys=self._suspend, resume_hotkeys=self._resume,
        )
        self.addCleanup(dialog.close)
        self.saved = []
        dialog.saved.connect(lambda c, s: self.saved.append((c, s)))
        return dialog

    def _suspend(self):
        self.suspended += 1

    def _resume(self):
        self.resumed += 1


class RoundTripTests(DialogTestCase):
    def test_untouched_dialog_returns_the_same_config(self):
        cfg = config.normalize({"hotkey_ptt": "", "custom_vocabulary": ["Bepo"], "microphone": "Mic B",
                                "speech_model": "tiny", "responsiveness": "fast",
                                "safety_idle_timeout_seconds": 90, "pause_duration_seconds": 3.0,
                                "auto_stop_on_pause": True, "continuous_mode": False})
        self.assertEqual(self.make(cfg).collect(), cfg)

    def test_saving_emits_the_config_and_startup_choice_and_closes(self):
        d = self.make(startup=False)
        d.fillers_check.setChecked(False)
        d.startup_check.setChecked(True)
        d.show()
        d._on_save()
        self.assertEqual(len(self.saved), 1)
        cfg, startup = self.saved[0]
        self.assertFalse(cfg["filter_filler_words"])
        self.assertTrue(startup)
        self.assertFalse(d.isVisible())

    def test_cancel_emits_nothing(self):
        d = self.make()
        d.show()
        d.fillers_check.setChecked(False)
        d.reject()
        self.assertEqual(self.saved, [])

    def test_restore_defaults(self):
        d = self.make(config.normalize({"speech_model": "tiny", "enable_emojis": False,
                                        "custom_vocabulary": ["x"], "hotkey_ptt": ""}))
        d._restore_defaults()
        self.assertEqual(d.collect(), config.base_config())

    def test_pause_length_is_only_available_when_it_applies(self):
        d = self.make()
        d.continuous_check.setChecked(True)
        self.assertFalse(d.autostop_check.isEnabled())
        self.assertFalse(d.pause_combo.isEnabled())
        d.continuous_check.setChecked(False)
        self.assertTrue(d.autostop_check.isEnabled())
        self.assertFalse(d.pause_combo.isEnabled())
        d.autostop_check.setChecked(True)
        self.assertTrue(d.pause_combo.isEnabled())

    def test_exact_idle_timeout_is_preserved_unless_changed(self):
        d = self.make(config.normalize({"safety_idle_timeout_seconds": 100}))
        self.assertEqual(d.collect()["safety_idle_timeout_seconds"], 100.0)
        d.idle_combo.setCurrentIndex(d.idle_combo.findData(10))
        self.assertEqual(d.collect()["safety_idle_timeout_seconds"], 600.0)

    def test_custom_words_are_cleaned(self):
        d = self.make()
        d.vocab_edit.setPlainText("  Kubernetes \n\nkubernetes\nMoonshine, Bepo ")
        self.assertEqual(d.collect()["custom_vocabulary"], ["Kubernetes", "Moonshine", "Bepo"])


class MicrophoneTests(DialogTestCase):
    def test_lists_devices_and_selects_the_saved_one(self):
        d = self.make(config.normalize({"microphone": "Mic B"}))
        items = [d.mic_combo.itemText(i) for i in range(d.mic_combo.count())]
        self.assertEqual(items, ["System default", "Mic A", "Mic B"])
        self.assertEqual(d.collect()["microphone"], "Mic B")

    def test_saved_microphone_that_is_unplugged_is_kept(self):
        d = self.make(config.normalize({"microphone": "Headset"}))
        self.assertIn("Headset (not connected)", [d.mic_combo.itemText(i) for i in range(d.mic_combo.count())])
        self.assertEqual(d.collect()["microphone"], "Headset")

    def test_default_microphone_is_none(self):
        self.assertIsNone(self.make().collect()["microphone"])

    def test_no_devices_found_still_works(self):
        d = self.make(devices=())
        self.assertEqual(d.mic_combo.count(), 1)
        self.assertIsNone(d.collect()["microphone"])


class ValidationTests(DialogTestCase):
    def test_both_shortcuts_the_same_is_rejected(self):
        d = self.make()
        d.ptt_edit.set_value("ctrl+win")
        d._on_save()
        self.assertEqual(self.saved, [])
        self.assertFalse(d.status_label.isHidden())

    def test_no_shortcut_at_all_is_rejected(self):
        d = self.make()
        d.toggle_edit.set_value("")
        d.ptt_edit.set_value("")
        d._on_save()
        self.assertEqual(self.saved, [])

    def test_disabling_one_shortcut_is_fine(self):
        d = self.make()
        d.ptt_off.click()
        d._on_save()
        self.assertEqual(self.saved[0][0]["hotkey_ptt"], "")


class ModelDownloadTests(DialogTestCase):
    def test_installed_model_saves_without_downloading(self):
        d = self.make()
        d.model_combo.setCurrentIndex(d.model_combo.findData("tiny"))
        d._on_save()
        self.assertEqual(FakeDownload.started_with, [])
        self.assertEqual(self.saved[0][0]["speech_model"], "tiny")

    def test_missing_model_is_downloaded_first_then_everything_is_saved(self):
        d = self.make()
        d.model_combo.setCurrentIndex(d.model_combo.findData("medium"))
        d.enable_emoji = d.emoji_check.setChecked(False)
        self.assertIn("Not downloaded", d.model_hint.text())
        d._on_save()
        self.assertEqual(FakeDownload.started_with, ["medium"])
        self.assertEqual(len(self.saved), 1)
        self.assertEqual(self.saved[0][0]["speech_model"], "medium")
        self.assertFalse(self.saved[0][0]["enable_emojis"])

    def test_failed_download_keeps_the_window_open_and_saves_nothing(self):
        d = self.make()
        d.show()
        FakeDownload.outcome = "error"
        d.model_combo.setCurrentIndex(d.model_combo.findData("medium"))
        d._on_save()
        self.assertEqual(self.saved, [])
        self.assertTrue(d.isVisible())
        self.assertIn("Download failed", d.status_label.text())
        self.assertTrue(d.save_btn.isEnabled())
        self.assertEqual(d.save_btn.text(), "Save")

    def test_closing_during_a_download_cancels_the_pending_save(self):
        d = self.make()
        d.model_combo.setCurrentIndex(d.model_combo.findData("medium"))
        d._pending = d.collect()
        d.reject()
        self.assertIsNone(d._pending)


class ErrorTextFitsTests(DialogTestCase):
    def test_long_download_error_is_not_cropped(self):
        long_error = ("HTTPSConnectionPool(host='download.moonshine.ai', port=443): Max retries exceeded with url: "
                      "/model/medium-streaming-en/quantized_26_08_21/decoder_kv.ort " + "z" * 300)
        d = self.make()
        d.show()
        d._on_download_error(object(), long_error)
        _app.processEvents()
        label = d.status_label
        self.assertFalse(label.isHidden())
        self.assertGreaterEqual(label.height() + 1, label.heightForWidth(label.width()))
        self.assertLessEqual(label.minimumSizeHint().width(), d.width())
        self.assertLess(len(label.text().replace("​", "")), 400)      # shortened, not a wall of text
        d.close()


class HotkeyCaptureTests(DialogTestCase):
    def capture(self, edit, key, modifiers=Qt.KeyboardModifier.NoModifier):
        edit.begin_capture()
        QTest.keyClick(edit, key, modifiers)

    def test_ctrl_space(self):
        d = self.make()
        self.capture(d.ptt_edit, Qt.Key.Key_Space, CTRL)
        self.assertEqual(d.ptt_edit.value(), "ctrl+space")

    def test_ctrl_alt_letter(self):
        d = self.make()
        self.capture(d.toggle_edit, Qt.Key.Key_D, CTRL | ALT)
        self.assertEqual(d.toggle_edit.value(), "ctrl+alt+d")

    def test_ctrl_win(self):
        d = self.make()
        self.capture(d.toggle_edit, Qt.Key.Key_Meta, CTRL)
        self.assertEqual(d.toggle_edit.value(), "ctrl+win")

    def test_pressing_win_with_a_modifier_held_finishes_the_capture(self):
        # Win acts as the trigger key (like the default Ctrl+Win), so capture ends right there
        # and a following letter is not added.
        d = self.make()
        self.capture(d.toggle_edit, Qt.Key.Key_J, META | CTRL)
        self.assertEqual(d.toggle_edit.value(), "ctrl+win")
        self.assertFalse(d.toggle_edit._capturing)

    def test_function_key_alone_is_allowed(self):
        d = self.make()
        self.capture(d.ptt_edit, Qt.Key.Key_F9)
        self.assertEqual(d.ptt_edit.value(), "f9")

    def test_plain_letter_is_refused_and_capture_continues(self):
        d = self.make()
        before = d.ptt_edit.value()
        self.capture(d.ptt_edit, Qt.Key.Key_A)
        self.assertEqual(d.ptt_edit.value(), before)
        self.assertTrue(d.ptt_edit._capturing)
        self.assertIn("Add Ctrl", d.ptt_edit.text())
        QTest.keyClick(d.ptt_edit, Qt.Key.Key_A, CTRL)           # now with a modifier
        self.assertEqual(d.ptt_edit.value(), "ctrl+a")
        self.assertFalse(d.ptt_edit._capturing)

    def test_win_key_alone_is_refused(self):
        d = self.make()
        self.capture(d.toggle_edit, Qt.Key.Key_Meta)
        self.assertEqual(d.toggle_edit.value(), "ctrl+win")
        self.assertTrue(d.toggle_edit._capturing)

    def test_escape_cancels(self):
        d = self.make()
        self.capture(d.ptt_edit, Qt.Key.Key_Escape)
        self.assertEqual(d.ptt_edit.value(), "ctrl+space")
        self.assertFalse(d.ptt_edit._capturing)

    def test_global_hotkeys_are_suspended_only_while_capturing(self):
        d = self.make()
        d.toggle_edit.begin_capture()
        self.assertEqual((self.suspended, self.resumed), (1, 0))
        QTest.keyClick(d.toggle_edit, Qt.Key.Key_F8)
        self.assertEqual((self.suspended, self.resumed), (1, 1))

    def test_closing_mid_capture_resumes_the_hotkeys(self):
        d = self.make()
        d.show()
        d.ptt_edit.begin_capture()
        d.reject()
        self.assertEqual(self.resumed, 1)

    def test_disable_button_clears_the_shortcut(self):
        d = self.make()
        d.toggle_off.click()
        self.assertEqual(d.toggle_edit.value(), "")
        self.assertEqual(d.toggle_edit.text(), "Disabled")

    def test_every_captured_value_is_accepted_by_the_hotkey_parser(self):
        from core.hotkey import parse_hotkey
        d = self.make()
        for key, mods in ((Qt.Key.Key_Space, CTRL | SHIFT), (Qt.Key.Key_5, ALT), (Qt.Key.Key_Return, CTRL),
                          (Qt.Key.Key_Tab, CTRL | ALT), (Qt.Key.Key_F24, CTRL)):
            self.capture(d.ptt_edit, key, mods)
            self.assertIsNotNone(parse_hotkey(d.ptt_edit.value()), d.ptt_edit.value())


if __name__ == "__main__":
    unittest.main()
