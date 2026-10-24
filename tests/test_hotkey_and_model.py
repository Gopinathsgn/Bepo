"""Tests for hotkey parsing and model-completeness detection (no real hotkeys are registered)."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.hotkey import (
    parse_hotkey, HotkeyManager, MOD_CONTROL, MOD_WIN, MOD_ALT,
    VK_LWIN, VK_RWIN, VK_SPACE, VK_CONTROL,
)
from setup.model_downloader import (
    REQUIRED_MODEL_FILES, _is_complete_model_dir, _find_complete_model_dir,
)


class ParseHotkeyTests(unittest.TestCase):
    def test_default_toggle_matches_legacy_registration(self):
        spec = parse_hotkey("ctrl+win")
        self.assertEqual(spec.mods, MOD_CONTROL | MOD_WIN)
        self.assertEqual(spec.vks, (VK_LWIN, VK_RWIN))

    def test_default_ptt(self):
        spec = parse_hotkey("Ctrl+Space")
        self.assertEqual(spec.text, "ctrl+space")
        self.assertEqual(spec.mods, MOD_CONTROL)
        self.assertEqual(spec.vks, (VK_SPACE,))
        self.assertIn((VK_CONTROL,), spec.held)
        self.assertIn((VK_SPACE,), spec.held)

    def test_other_combos(self):
        self.assertEqual(parse_hotkey("ctrl+alt+d").mods, MOD_CONTROL | MOD_ALT)
        self.assertEqual(parse_hotkey("f9").vks, (0x78,))

    def test_invalid(self):
        for bad in ("", "   ", "banana", "ctrl+alt", "ctrl+ctrl+a", "ctrl+f25", None, 5):
            self.assertIsNone(parse_hotkey(bad), bad)


class HotkeyManagerConfigTests(unittest.TestCase):
    """Only exercises config resolution; start() is never called so nothing is registered."""

    def test_defaults(self):
        m = HotkeyManager()
        self.assertEqual((m.toggle_label, m.ptt_label), ("Ctrl+Win", "Ctrl+Space"))

    def test_disable_ptt(self):
        m = HotkeyManager(ptt="")
        self.assertEqual(m.ptt_label, "")
        self.assertEqual(m._issues, [])

    def test_invalid_falls_back_and_reports(self):
        m = HotkeyManager(toggle="nonsense")
        self.assertEqual(m.toggle_label, "Ctrl+Win")
        self.assertEqual(len(m._issues), 1)

    def test_duplicate_disables_ptt(self):
        m = HotkeyManager(toggle="ctrl+space", ptt="ctrl+space")
        self.assertEqual(m.ptt_label, "")
        self.assertEqual(len(m._issues), 1)


class ModelDetectionTests(unittest.TestCase):
    def _make_model(self, path: Path, skip: str | None = None):
        path.mkdir(parents=True, exist_ok=True)
        for name in REQUIRED_MODEL_FILES:
            if name != skip:
                (path / name).write_bytes(b"x")

    def test_complete_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "m"
            self._make_model(d)
            self.assertTrue(_is_complete_model_dir(d))

    def test_partial_download_is_not_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "m"
            self._make_model(d, skip="encoder.ort")
            self.assertFalse(_is_complete_model_dir(d))
            (d / "decoder_kv.ort").write_bytes(b"")   # zero-byte file also rejected
            self.assertFalse(_is_complete_model_dir(d))

    def test_nested_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_model(Path(tmp) / "a" / "b" / "model")
            found = _find_complete_model_dir(Path(tmp))
            self.assertEqual(found, Path(tmp) / "a" / "b" / "model")
            self.assertIsNone(_find_complete_model_dir(Path(tmp) / "missing"))


if __name__ == "__main__":
    unittest.main()
