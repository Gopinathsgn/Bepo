"""The Help window (ui/help_dialog.py): live shortcuts, honest on/off state, nothing cropped, and a working Try-it box."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from core import config, guide
from ui.help_dialog import HelpDialog, HelpState

_app = QApplication.instance() or QApplication([])


def state(cfg=None, toggle="Ctrl+Win", ptt="Ctrl+Space", undo="Alt+Win+Z") -> HelpState:
    return HelpState(config.normalize(cfg or {}), toggle, ptt, undo)


def button(dialog, text):
    return next(b for b in dialog.findChildren(QPushButton) if b.text() == text)


def texts(dialog) -> str:
    return "\n".join(label.text() for label in dialog.findChildren(QLabel))


class HelpDialogTests(unittest.TestCase):
    def make(self, st=None):
        dialog = HelpDialog(st or state())
        self.addCleanup(dialog.deleteLater)
        return dialog

    def assertNothingCropped(self, dialog):
        dialog.show()
        _app.processEvents()
        body = dialog._scroll.widget()
        for label in body.findChildren(QLabel):
            if not label.text():
                continue
            self.assertTrue(label.wordWrap() or label.sizeHint().width() <= label.width() + 1,
                            f"label wider than its card: {label.text()!r}")
            if label.wordWrap():
                self.assertGreaterEqual(label.height() + 1, label.heightForWidth(label.width()),
                                        f"label cropped vertically: {label.text()!r}")
        self.assertEqual(dialog._scroll.horizontalScrollBar().maximum(), 0, "page scrolls sideways")
        dialog.hide()

    def test_every_topic_and_the_shortcuts_are_there_in_order(self):
        dialog = self.make()
        text = texts(dialog)
        headings = [t for t in ("START & STOP", *(t.title.upper() for t in guide.TOPICS)) if t in text]
        self.assertEqual(headings, ["START & STOP", "FIX MISTAKES", "LINES & LISTS",
                                    "PUNCTUATION & NUMBERS", "EMOJI"])
        for topic in guide.TOPICS:
            for entry in topic.entries:
                self.assertIn(f"“{entry.say}”", text)

    def test_default_shortcuts_are_listed(self):
        text = texts(self.make())
        for keys in ("Ctrl+Win", "Hold Ctrl+Space", "Esc", "Alt+Win+Z"):
            self.assertIn(keys, text)

    def test_nothing_is_cropped_with_defaults_and_with_everything_off(self):
        self.assertNothingCropped(self.make())
        off = state({"voice_formatting": False, "smart_formatting": False, "enable_emojis": False,
                     "esc_to_finish": False}, toggle="", ptt="", undo="")
        self.assertNothingCropped(self.make(off))

    def test_it_shows_the_users_own_shortcuts_after_set_state(self):
        dialog = self.make()
        dialog.set_state(state(toggle="F9", ptt="Ctrl+Alt+Space", undo="Ctrl+Shift+Z"))
        text = texts(dialog)
        self.assertIn("F9", text)
        self.assertIn("Hold Ctrl+Alt+Space", text)
        self.assertNotIn("Ctrl+Win", text.replace("Alt+Win", ""))     # the old toggle is gone
        self.assertIn("press F9", dialog._try_hint.text())

    def test_switched_off_features_say_so(self):
        dialog = self.make(state({"voice_formatting": False}))
        self.assertIn("Currently off", texts(dialog))
        self.assertIn("Spoken line breaks and lists", texts(dialog))
        self.assertNotIn("Currently off", texts(self.make()))

    def test_set_state_keeps_the_scroll_position(self):
        dialog = self.make()
        dialog.show()
        _app.processEvents()
        bar = dialog._scroll.verticalScrollBar()
        bar.setValue(bar.maximum() // 2)
        before = bar.value()
        self.assertGreater(before, 0)
        dialog.set_state(state({"voice_formatting": False}))
        _app.processEvents()
        self.assertEqual(dialog._scroll.verticalScrollBar().value(), before)

    def test_try_hint_falls_back_when_the_toggle_is_disabled(self):
        self.assertIn("hold Ctrl+Space", self.make(state(toggle=""))._try_hint.text())
        self.assertIn("tray icon", self.make(state(toggle="", ptt=""))._try_hint.text())

    def test_esc_does_not_close_the_window_but_the_close_button_does(self):
        dialog = self.make()
        dialog.show()
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        self.assertTrue(dialog.isVisible())
        QTest.keyClick(dialog.try_box, Qt.Key.Key_Escape)
        self.assertTrue(dialog.isVisible())
        button(dialog, "Close").click()
        self.assertFalse(dialog.isVisible())

    def test_try_box_takes_typed_text_and_can_be_cleared(self):
        dialog = self.make()
        dialog.show()
        dialog.try_box.setFocus()
        QTest.keyClicks(dialog.try_box, "Hello world")
        self.assertEqual(dialog.try_box.toPlainText(), "Hello world")
        button(dialog, "Clear").click()
        self.assertEqual(dialog.try_box.toPlainText(), "")

    def test_dialog_has_a_fixed_width_and_sensible_height(self):
        dialog = self.make()
        self.assertEqual(dialog.minimumWidth(), dialog.maximumWidth())
        self.assertGreaterEqual(dialog.minimumHeight(), 420)


if __name__ == "__main__":
    unittest.main()
