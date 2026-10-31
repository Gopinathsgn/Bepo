"""Windows helpers: startup entry, microphone lookup, memory trim, model files, hotkey re-registration."""

import os
import sys
import tempfile
import time
import unittest
import winreg
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core import audio_devices, memory, startup
from setup import model_downloader as md


class StartupEntryTests(unittest.TestCase):
    """Uses a throw-away registry key, never the real Run key."""

    def setUp(self):
        self.key_path = rf"Software\BepoTest_{os.getpid()}_{time.time_ns()}"
        p = mock.patch.object(startup, "RUN_KEY", self.key_path)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self._remove_key)

    def _remove_key(self):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, self.key_path)
        except OSError:
            pass

    def test_enable_disable_round_trip(self):
        self.assertFalse(startup.is_enabled())
        self.assertTrue(startup.set_enabled(True))
        self.assertTrue(startup.is_enabled())
        self.assertTrue(startup.set_enabled(False))
        self.assertFalse(startup.is_enabled())
        self.assertTrue(startup.set_enabled(False))          # disabling twice is fine

    def test_command_is_quoted_and_points_at_this_install(self):
        command = startup.startup_command()
        self.assertTrue(command.startswith('"'))
        self.assertIn("main.py", command)                    # (not frozen under test)

    def test_frozen_command_is_just_the_exe(self):
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "executable", r"C:\Apps\Bepo\Bepo.exe"):
            self.assertEqual(startup.startup_command(), '"C:\\Apps\\Bepo\\Bepo.exe"')

    def test_stale_entry_is_repaired_but_missing_entry_is_not_created(self):
        startup.refresh_if_enabled()
        self.assertFalse(startup.is_enabled())               # user never enabled it
        startup.set_enabled(True)
        with mock.patch.object(startup, "startup_command", return_value='"C:\\New\\Bepo.exe"'):
            startup.refresh_if_enabled()
            self.assertEqual(startup._read_value(), '"C:\\New\\Bepo.exe"')


class AudioDeviceTests(unittest.TestCase):
    DEVICES = [(1, "Microphone (Realtek High Definition Audio)"), (4, "USB Headset"), (6, "Webcam Mic")]

    def resolve(self, name):
        with mock.patch.object(audio_devices, "_input_devices", return_value=self.DEVICES):
            return audio_devices.resolve_device(name)

    def test_exact_and_default(self):
        self.assertEqual(self.resolve("USB Headset"), 4)
        self.assertIsNone(self.resolve(None))
        self.assertIsNone(self.resolve(""))

    def test_tolerates_truncated_driver_names(self):
        self.assertEqual(self.resolve("Microphone (Realtek High Definition Audio)"), 1)
        self.assertEqual(self.resolve("Microphone (Realtek High Definit"), 1)

    def test_unplugged_microphone_falls_back_to_default(self):
        self.assertIsNone(self.resolve("Studio Condenser"))

    def test_listing_dedupes_and_survives_failures(self):
        dup = [(1, "Mic"), (2, "Mic"), (3, "Other")]
        with mock.patch.object(audio_devices, "_input_devices", return_value=dup):
            self.assertEqual(audio_devices.list_input_devices(), ["Mic", "Other"])
        with mock.patch.object(audio_devices, "_input_devices", side_effect=OSError("no audio")):
            self.assertEqual(audio_devices.list_input_devices(), [])
            self.assertIsNone(audio_devices.resolve_device("Mic"))

    def test_real_query_does_not_crash(self):
        names = audio_devices.list_input_devices()           # may be empty on CI runners
        self.assertIsInstance(names, list)


class MemoryTests(unittest.TestCase):
    def test_trim_returns_a_bool_and_never_raises(self):
        self.assertIsInstance(memory.trim_working_set(), bool)

    def test_trim_failure_is_swallowed(self):
        with mock.patch.object(memory.ctypes, "WinDLL", side_effect=OSError("nope")):
            self.assertFalse(memory.trim_working_set())


def _make_model(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    for name in md.REQUIRED_MODEL_FILES:
        (path / name).write_bytes(b"x")


class ModelFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.cache = self.root / "cache"
        self.bundle = self.root / "bundle" / "models"
        patches = [
            mock.patch.dict(os.environ, {"MOONSHINE_VOICE_CACHE": str(self.cache)}),
            mock.patch.object(md, "_bundle_roots", lambda: [self.bundle]),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        md.get_bundled_model_path.cache_clear()
        self.addCleanup(md.get_bundled_model_path.cache_clear)

    def cache_dir(self, key, version="quantized_1"):
        return self.cache / "download.moonshine.ai" / "model" / md.MODELS[key].folder / version

    def test_cache_location_matches_the_library(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MOONSHINE_VOICE_CACHE", None)
            from moonshine_voice.download import get_cache_dir
            self.assertEqual(md.get_model_cache_path(), get_cache_dir())

    def test_each_model_is_found_separately(self):
        _make_model(self.cache_dir("tiny"))
        self.assertTrue(md.is_model_downloaded("tiny"))
        self.assertFalse(md.is_model_downloaded("small"))
        self.assertFalse(md.is_model_downloaded("medium"))

    def test_partial_download_does_not_count(self):
        d = self.cache_dir("medium")
        _make_model(d)
        (d / "encoder.ort").unlink()
        self.assertFalse(md.is_model_downloaded("medium"))

    def test_newest_cached_version_is_preferred(self):
        _make_model(self.cache_dir("small", "quantized_26_08_21"))
        _make_model(self.cache_dir("small", "quantized_26_09_01"))
        self.assertEqual(md.find_installed_model("small").name, "quantized_26_09_01")

    def test_bundled_model_layout(self):
        _make_model(self.bundle / "small-streaming-en")
        self.assertEqual(md.find_installed_model("small"), self.bundle / "small-streaming-en")
        self.assertFalse(md.is_model_downloaded("medium"))

    def test_legacy_bundle_layout_still_works_for_the_default_model_only(self):
        _make_model(self.bundle / "quantized_26_08_21")
        self.assertIsNotNone(md.find_installed_model("small"))
        self.assertIsNone(md.find_installed_model("tiny"))

    def test_bundle_beats_cache(self):
        _make_model(self.bundle / "small-streaming-en")
        _make_model(self.cache_dir("small"))
        self.assertEqual(md.find_installed_model("small"), self.bundle / "small-streaming-en")

    def test_export_for_bundling_copies_a_complete_model(self):
        _make_model(self.cache_dir("small"))
        target = self.root / "dist" / "models"
        self.assertTrue(md.export_model_for_bundling(target))
        self.assertTrue(md._is_complete_model_dir(target / "small-streaming-en"))

    def test_export_fails_loudly_when_the_download_cannot_produce_a_model(self):
        with mock.patch.object(md, "download_model", lambda *a, **k: None):
            self.assertFalse(md.export_model_for_bundling(self.root / "out"))

    def test_catalog_matches_the_installed_moonshine_library(self):
        from moonshine_voice import ModelArch
        from moonshine_voice.download import find_model_info
        for key, info in md.MODELS.items():
            arch = getattr(ModelArch, info.arch_name)
            url = find_model_info("en", arch)["download_url"]
            self.assertIn(f"/{info.folder}/", url, key)


class HotkeyReregistrationTests(unittest.TestCase):
    """Real message-loop thread, but RegisterHotKey is faked so no system shortcut is touched."""

    def setUp(self):
        from PySide6.QtWidgets import QApplication
        self._app = QApplication.instance() or QApplication([])
        from core.hotkey import HotkeyManager
        patch = mock.patch.object(HotkeyManager, "_register", staticmethod(lambda *a: True))
        patch.start()
        self.addCleanup(patch.stop)
        self.manager = HotkeyManager(toggle="ctrl+alt+f10", ptt="ctrl+alt+f11", undo="")
        self.addCleanup(self.manager.stop)
        self.issues = []
        self.manager.registration_issue.connect(self.issues.append)

    def test_reconfigure_swaps_the_shortcuts(self):
        self.manager.start()
        self.assertEqual(len(self.manager._registered), 2)
        self.manager.reconfigure("ctrl+alt+f9", "")
        self.assertEqual(self.manager._registered, ["ctrl+alt+f9 (toggle)"])
        self.assertEqual((self.manager.toggle_label, self.manager.ptt_label), ("Ctrl+Alt+F9", ""))

    def test_undo_shortcut_registers_and_survives_reconfigure(self):
        self.manager.reconfigure("ctrl+alt+f10", "ctrl+alt+f11", "ctrl+alt+f12")
        self.assertEqual(self.manager.undo_label, "Ctrl+Alt+F12")
        self.assertIn("ctrl+alt+f12 (undo)", self.manager._registered)
        self.manager.reconfigure("ctrl+alt+f9", "")                  # undo left out: kept as it was
        self.assertEqual(self.manager.undo_label, "Ctrl+Alt+F12")

    def test_undo_shortcut_cannot_duplicate_another(self):
        self.manager.reconfigure("ctrl+alt+f10", "ctrl+alt+f11", "ctrl+alt+f10")
        self._app.processEvents()
        self.assertEqual(self.manager.undo_label, "")
        self.assertEqual(len(self.issues), 1)

    def test_default_undo_shortcut_does_not_start_with_the_toggle(self):
        from core.hotkey import DEFAULT_TOGGLE, DEFAULT_UNDO, parse_hotkey
        toggle, undo = parse_hotkey(DEFAULT_TOGGLE), parse_hotkey(DEFAULT_UNDO)
        self.assertFalse(set(toggle.held) <= set(undo.held))   # else the toggle fires before the key

    def test_suspend_and_resume(self):
        self.manager.start()
        self.manager.suspend()
        self.assertIsNone(self.manager._thread)
        self.manager.resume()
        self.assertIsNotNone(self.manager._thread)
        self.assertEqual(len(self.manager._registered), 2)
        self.manager.resume()                                  # resuming twice is harmless
        self.assertEqual(len(self.manager._registered), 2)

    def test_invalid_new_shortcut_is_reported_and_default_used(self):
        self.manager.start()
        self.manager.reconfigure("nonsense", "ctrl+alt+f11")
        self._app.processEvents()
        self.assertEqual(self.manager.toggle_label, "Ctrl+Win")
        self.assertEqual(len(self.issues), 1)

    def test_stop_waits_for_the_message_loop_to_exit(self):
        self.manager.start()
        thread = self.manager._thread
        self.manager.stop()
        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
