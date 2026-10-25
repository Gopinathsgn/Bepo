"""Injector tests: clipboard handling. SendInput, keybd_event and pyperclip are all mocked."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.injector as injector


class InjectorClipboardTests(unittest.TestCase):
    def setUp(self):
        injector.configure(clipboard_safety_net=False)
        fake_windll = mock.MagicMock()
        fake_windll.user32.GetAsyncKeyState.return_value = 0
        fake_windll.user32.SendInput.side_effect = lambda n, arr, size: n
        patches = [
            mock.patch.object(injector.ctypes, "windll", fake_windll, create=True),
            mock.patch.object(injector.time, "sleep"),
            mock.patch.object(injector, "pyperclip"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.windll = fake_windll
        self.clip = injector.pyperclip
        self.addCleanup(injector.configure, False)

    def test_default_does_not_touch_clipboard(self):
        with mock.patch.object(injector, "_send_unicode_string", return_value=True):
            self.assertTrue(injector.inject_text("hello", "hello world"))
        self.clip.copy.assert_not_called()
        self.clip.paste.assert_not_called()

    def test_safety_net_copies_whole_session(self):
        injector.configure(clipboard_safety_net=True)
        with mock.patch.object(injector, "_send_unicode_string", return_value=True):
            injector.inject_text("world", "hello world")
        self.clip.copy.assert_called_once_with("hello world")

    def test_deletion_does_not_touch_clipboard_by_default(self):
        injector.delete_backspaces(3, "whatever")
        self.clip.copy.assert_not_called()

    def test_paste_fallback_restores_previous_clipboard(self):
        self.clip.paste.return_value = "my precious clipboard"
        with mock.patch.object(injector, "_send_unicode_string", return_value=False),                 mock.patch.object(injector, "_clipboard_is_text_only", return_value=True):
            self.assertTrue(injector.inject_text("dictated text"))
        copies = [c.args[0] for c in self.clip.copy.call_args_list]
        self.assertEqual(copies, ["dictated text", "my precious clipboard"])
        # Ctrl+V was simulated (down/up for Ctrl and V)
        self.assertEqual(self.windll.user32.SendInput.call_args.args[0], 4)

    def test_paste_fallback_leaves_non_text_clipboard_alone(self):
        with mock.patch.object(injector, "_send_unicode_string", return_value=False),                 mock.patch.object(injector, "_clipboard_is_text_only", return_value=False):
            self.assertFalse(injector.inject_text("dictated text"))
        self.clip.copy.assert_not_called()

    def test_paste_fallback_reports_failure_when_keystroke_rejected(self):
        self.windll.user32.SendInput.side_effect = lambda n, arr, size: 0
        with mock.patch.object(injector, "_send_unicode_string", return_value=False),                 mock.patch.object(injector, "_clipboard_is_text_only", return_value=True):
            self.assertFalse(injector.inject_text("dictated text"))

    def test_clipboard_format_probe(self):
        user32 = self.windll.user32
        user32.OpenClipboard.return_value = 1
        user32.EnumClipboardFormats.side_effect = [13, 16, 0]
        self.assertTrue(injector._clipboard_is_text_only())
        user32.EnumClipboardFormats.side_effect = [13, 2, 0]      # CF_BITMAP
        self.assertFalse(injector._clipboard_is_text_only())
        user32.EnumClipboardFormats.side_effect = [0]             # empty clipboard
        self.assertTrue(injector._clipboard_is_text_only())
        self.assertEqual(user32.CloseClipboard.call_count, 3)

    def test_empty_text_is_a_noop(self):
        self.assertTrue(injector.inject_text(""))
        self.clip.copy.assert_not_called()


class InjectorLineBreakTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(injector.configure)
        self.calls = []
        patches = [
            mock.patch.object(injector, "_send_unicode_string", lambda t: self.calls.append(("text", t)) or True),
            mock.patch.object(injector, "_send_line_break", lambda: self.calls.append(("break",)) or True),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_newlines_become_line_break_keystrokes(self):
        self.assertTrue(injector._send_text("a\nb\n\nc"))
        self.assertEqual(self.calls, [("text", "a"), ("break",), ("text", "b"), ("break",), ("break",), ("text", "c")])

    def test_text_without_newlines_is_sent_in_one_piece(self):
        injector._send_text("hello world")
        self.assertEqual(self.calls, [("text", "hello world")])

    def test_windows_line_endings_count_once(self):
        injector._send_text("a\r\nb")
        self.assertEqual(self.calls, [("text", "a"), ("break",), ("text", "b")])


class InjectorLineBreakKeyTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(injector.configure)
        fake_windll = mock.MagicMock()
        fake_windll.user32.SendInput.side_effect = lambda n, arr, size: n
        p = mock.patch.object(injector.ctypes, "windll", fake_windll, create=True)
        p.start()
        self.addCleanup(p.stop)
        self.windll = fake_windll

    def keys_sent(self):
        arr = self.windll.user32.SendInput.call_args.args[1]
        return [(i.union.ki.wVk, bool(i.union.ki.dwFlags & injector.KEYEVENTF_KEYUP)) for i in arr]

    def test_shift_enter_is_the_default(self):
        injector.configure()
        self.assertTrue(injector._send_line_break())
        self.assertEqual(self.keys_sent(), [(injector.VK_SHIFT, False), (injector.VK_RETURN, False),
                                            (injector.VK_RETURN, True), (injector.VK_SHIFT, True)])

    def test_plain_enter_when_configured(self):
        injector.configure(line_break_key="enter")
        self.assertTrue(injector._send_line_break())
        self.assertEqual(self.keys_sent(), [(injector.VK_RETURN, False), (injector.VK_RETURN, True)])
