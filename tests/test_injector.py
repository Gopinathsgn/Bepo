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
        with mock.patch.object(injector, "_send_unicode_string", return_value=False):
            self.assertTrue(injector.inject_text("dictated text"))
        copies = [c.args[0] for c in self.clip.copy.call_args_list]
        self.assertEqual(copies, ["dictated text", "my precious clipboard"])
        # Ctrl+V was simulated
        self.assertTrue(self.windll.user32.keybd_event.called)

    def test_empty_text_is_a_noop(self):
        self.assertTrue(injector.inject_text(""))
        self.clip.copy.assert_not_called()


