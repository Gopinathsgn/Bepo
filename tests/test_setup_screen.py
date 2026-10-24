"""
First-run setup screen (ui/setup_screen.py): the window must always be large enough for what it
shows (no cropped text), whatever the state or the error message.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

import ui.setup_screen as ss
from ui.setup_screen import SetupScreen, DownloadThread

_app = QApplication.instance() or QApplication([])

LONG_ERROR = ("HTTPSConnectionPool(host='download.moonshine.ai', port=443): Max retries exceeded with url: "
              "/model/small-streaming-en/quantized_26_08_21/decoder_kv.ort (Caused by "
              "NewConnectionError('<urllib3.connection.HTTPSConnection object at 0x000001F4A3B2C7D0>: "
              "Failed to establish a new connection: [WinError 10060] A connection attempt failed "
              "because the connected party did not properly respond after a period of time'))")


class FitTests(unittest.TestCase):
    def make(self, model="small"):
        screen = SetupScreen(model)
        self.addCleanup(screen.deleteLater)
        return screen

    def assertFits(self, screen):
        """Nothing may be cropped: every visible label is big enough for the text it shows."""
        layout = screen.layout()
        layout.activate()
        self.assertEqual(screen.width(), ss.WINDOW_WIDTH)
        self.assertGreaterEqual(screen.height(), ss.MIN_WINDOW_HEIGHT)
        self.assertGreaterEqual(screen.height(), layout.totalHeightForWidth(ss.WINDOW_WIDTH),
                                "window is shorter than its content needs")
        screen.show()
        _app.processEvents()
        for label in screen.findChildren(QLabel):
            if not label.isVisible() or not label.text() and label.pixmap().isNull():
                continue
            if label.wordWrap():
                needed = label.heightForWidth(label.width())
                self.assertGreaterEqual(label.height() + 1, needed, f"label cropped vertically: {label.text()!r}")
            else:
                self.assertGreaterEqual(label.height() + 1, label.sizeHint().height(),
                                        f"label cropped vertically: {label.text()!r}")
                self.assertGreaterEqual(label.width() + 1, label.sizeHint().width(),
                                        f"label cropped horizontally: {label.text()!r}")
        screen.hide()

    def test_every_state_fits(self):
        for model in ("tiny", "small", "medium"):
            screen = self.make(model)
            self.assertFits(screen)                          # first run
            screen._on_progress(40, "decoder_kv.ort")
            self.assertFits(screen)                          # downloading
            screen._on_finished()
            self.assertFits(screen)                          # done

    def test_error_states_fit(self):
        for message in ("", "boom", "Read timed out.", LONG_ERROR, "line one\nline two\n" * 6,
                        "x" * 400, "https://download.moonshine.ai/" + "a" * 300):
            screen = self.make()
            screen._on_error(message)
            self.assertFits(screen)

    def test_error_grows_the_window_and_retry_shrinks_it_back(self):
        screen = self.make()
        before = screen.height()
        screen._on_error(LONG_ERROR)
        self.assertGreater(screen.height(), before)
        with mock.patch.object(ss, "DownloadThread") as thread:
            screen.start_download()
            thread.return_value.start.assert_called_once()
        self.assertAlmostEqual(screen.height(), before, delta=4)     # back to the compact size
        self.assertTrue(screen._detail_label.isHidden())
        self.assertTrue(screen._button_row.isHidden())
        self.assertEqual(screen._status_label.text(), "")

    def test_all_message_labels_wrap(self):
        screen = self.make()
        for label in (screen._info_label, screen._status_label, screen._detail_label):
            self.assertTrue(label.wordWrap())

    def test_buttons_are_big_enough_to_read(self):
        screen = self.make()
        for button in (screen._quit_btn, screen._retry_btn):
            self.assertGreaterEqual(button.minimumHeight(), 32)
            self.assertGreaterEqual(button.minimumWidth(), 96)

    def test_error_is_split_into_headline_and_wrapped_detail(self):
        screen = self.make()
        screen._on_error(LONG_ERROR)
        self.assertEqual(screen._status_label.text(), "❌  Download failed")
        text = screen._detail_label.text()
        self.assertIn("Check your internet connection", text)
        detail = text.splitlines()[1].replace(ss._ZWSP, "")
        self.assertLessEqual(len(detail), ss.MAX_ERROR_CHARS + 1)
        self.assertTrue(text.endswith("…"))
        self.assertFalse(screen._button_row.isHidden())

    def test_no_label_text_is_empty_or_missing_for_each_model(self):
        for model, size in (("tiny", 45), ("small", 142), ("medium", 269)):
            screen = self.make(model)
            self.assertIn(model, screen._info_label.text())
            self.assertIn(str(size), screen._info_label.text())

    def test_window_is_centred_on_the_screen_after_resizing(self):
        screen = self.make()
        screen._on_error(LONG_ERROR)
        area = QApplication.primaryScreen().availableGeometry()
        centre = screen.geometry().center()
        self.assertAlmostEqual(centre.x(), area.center().x(), delta=2)
        self.assertAlmostEqual(centre.y(), area.center().y(), delta=2)


class BehaviourTests(unittest.TestCase):
    def test_closing_before_completion_quits_the_app(self):
        screen = SetupScreen()
        with mock.patch.object(ss.QApplication, "quit") as quit_app:
            screen.close()
        quit_app.assert_called_once()

    def test_quit_button_quits(self):
        with mock.patch.object(ss.QApplication, "quit") as quit_app:      # patch before the button is wired
            screen = SetupScreen()
            screen._quit_btn.click()
        quit_app.assert_called_once()

    def test_download_thread_downloads_the_requested_model(self):
        calls = []
        with mock.patch.object(ss, "download_model", lambda cb, key: calls.append(key)):
            thread = DownloadThread("tiny")
            done = []
            thread.finished.connect(lambda: done.append(True))
            thread.run()                                    # synchronously, no QThread needed
        self.assertEqual(calls, ["tiny"])
        self.assertEqual(done, [True])

    def test_download_failure_is_reported_not_raised(self):
        errors = []
        with mock.patch.object(ss, "download_model", side_effect=OSError("offline")):
            thread = DownloadThread("small")
            thread.error.connect(errors.append)
            thread.run()
        self.assertEqual(errors, ["offline"])


class BreakableTests(unittest.TestCase):
    """The helper that keeps arbitrary error text from forcing a label wider than its window."""

    def test_long_unbroken_token_gets_break_opportunities(self):
        out = ss.breakable("x" * 100, limit=500)
        self.assertEqual(out.replace(ss._ZWSP, ""), "x" * 100)
        self.assertTrue(all(len(run) <= 20 for run in out.split(ss._ZWSP)))

    def test_urls_and_paths_break_after_punctuation(self):
        out = ss.breakable("https://download.moonshine.ai/model/small-streaming-en/x.ort")
        self.assertIn("/" + ss._ZWSP, out)
        self.assertIn("." + ss._ZWSP, out)

    def test_whitespace_collapsed_and_length_capped(self):
        out = ss.breakable("a  b\n\n c " + "w " * 400, limit=50)
        self.assertTrue(out.endswith("…"))
        self.assertLessEqual(len(out.replace(ss._ZWSP, "")), 51)
        self.assertNotIn("\n", out)

    def test_plain_short_text_is_unchanged(self):
        self.assertEqual(ss.breakable("Read timed out"), "Read timed out")

    def test_non_string_input_is_tolerated(self):
        self.assertEqual(ss.breakable(None), "None")


if __name__ == "__main__":
    unittest.main()
