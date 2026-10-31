"""Settings: defaults, validation and persistence (core/config.py)."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import config


class NormalizeTests(unittest.TestCase):
    def test_defaults_are_complete_and_stable(self):
        cfg = config.normalize({})
        self.assertEqual(cfg, config.normalize(cfg))                 # idempotent
        self.assertEqual(set(cfg), set(config.DEFAULT_CONFIG))
        self.assertEqual(cfg["responsiveness"], "efficient")         # lower-CPU default
        self.assertEqual(config.update_interval(cfg), 1.0)
        self.assertEqual(cfg["speech_model"], "small")

    def test_line_break_and_formatting_settings(self):
        self.assertTrue(config.normalize({})["voice_formatting"])
        self.assertEqual(config.normalize({})["line_break_key"], "shift_enter")
        self.assertEqual(config.normalize({"line_break_key": "enter"})["line_break_key"], "enter")
        self.assertEqual(config.normalize({"line_break_key": "tab"})["line_break_key"], "shift_enter")
        self.assertFalse(config.normalize({"voice_formatting": False})["voice_formatting"])

    def test_accuracy_and_ux_settings(self):
        cfg = config.normalize({})
        self.assertTrue(cfg["smart_formatting"])
        self.assertFalse(cfg["keep_history"])
        self.assertEqual(cfg["custom_word_strength"], "normal")
        self.assertEqual(config.normalize({"custom_word_strength": "strong"})["custom_word_strength"], "strong")
        self.assertEqual(config.normalize({"custom_word_strength": "loud"})["custom_word_strength"], "normal")
        self.assertFalse(config.normalize({"smart_formatting": False})["smart_formatting"])
        self.assertTrue(config.normalize({"keep_history": True})["keep_history"])

    def test_bad_values_fall_back_to_defaults(self):
        cfg = config.normalize({
            "continuous_mode": "maybe", "safety_idle_timeout_seconds": "soon",
            "speech_model": "gigantic", "responsiveness": "ludicrous",
            "microphone": 42, "hotkey_ptt": 7, "custom_vocabulary": 5,
        })
        d = config.DEFAULT_CONFIG
        self.assertEqual(cfg["continuous_mode"], d["continuous_mode"])
        self.assertEqual(cfg["safety_idle_timeout_seconds"], d["safety_idle_timeout_seconds"])
        self.assertEqual(cfg["speech_model"], "small")
        self.assertEqual(cfg["responsiveness"], "efficient")
        self.assertIsNone(cfg["microphone"])
        self.assertEqual(cfg["hotkey_ptt"], d["hotkey_ptt"])
        self.assertEqual(cfg["custom_vocabulary"], [])

    def test_numbers_are_clamped_and_strings_booleans_accepted(self):
        cfg = config.normalize({"safety_idle_timeout_seconds": 1, "pause_duration_seconds": 999,
                                "enable_emojis": "false"})
        self.assertEqual(cfg["safety_idle_timeout_seconds"], 10.0)
        self.assertEqual(cfg["pause_duration_seconds"], 10.0)
        self.assertFalse(cfg["enable_emojis"])

    def test_disabled_hotkeys_are_kept(self):
        cfg = config.normalize({"hotkey_ptt": "", "hotkey_toggle": None})
        self.assertEqual(cfg["hotkey_ptt"], "")
        self.assertIsNone(cfg["hotkey_toggle"])

    def test_responsiveness_maps_to_intervals(self):
        self.assertEqual(config.update_interval({"responsiveness": "fast"}), 0.5)
        self.assertEqual(config.update_interval({"responsiveness": "efficient"}), 1.0)


class VocabularyTests(unittest.TestCase):
    def test_split_trim_dedupe(self):
        self.assertEqual(config.clean_vocabulary(" Kubernetes \n\nkubernetes\nMoon  shine, Ceph"),
                         ["Kubernetes", "Moon shine", "Ceph"])

    def test_commas_never_survive(self):
        self.assertTrue(all("," not in t for t in config.clean_vocabulary(["a,b", "c, d"])))

    def test_limits(self):
        many = [f"term{i}" for i in range(500)]
        self.assertEqual(len(config.clean_vocabulary(many)), config.MAX_VOCABULARY_TERMS)
        self.assertEqual(len(config.clean_vocabulary(["x" * 500])[0]), config.MAX_TERM_LENGTH)

    def test_non_text_ignored(self):
        self.assertEqual(config.clean_vocabulary([None, 3, "ok"]), ["ok"])
        self.assertEqual(config.clean_vocabulary(None), [])


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "Bepo" / "config.json"
        p = mock.patch.object(config, "USER_CONFIG_PATH", self.path)
        p.start()
        self.addCleanup(p.stop)

    def test_only_differences_from_defaults_are_written(self):
        cfg = config.normalize({"speech_model": "tiny", "custom_vocabulary": ["Bepo"]})
        written = config.save_user_config(cfg)
        self.assertEqual(written, {"speech_model": "tiny", "custom_vocabulary": ["Bepo"]})
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), written)

    def test_round_trip(self):
        cfg = config.normalize({"hotkey_ptt": "", "microphone": "USB Mic", "responsiveness": "fast",
                                "safety_idle_timeout_seconds": 90})
        config.save_user_config(cfg)
        self.assertEqual(config.load_config(), cfg)

    def test_saving_defaults_leaves_an_empty_file(self):
        config.save_user_config(config.load_config())
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {})

    def test_broken_user_file_is_ignored(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(config.load_config()["hotkey_toggle"], "ctrl+win")

    def test_non_object_user_file_is_ignored(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("[1, 2]", encoding="utf-8")
        self.assertEqual(config.load_config()["speech_model"], "small")

    def test_user_overrides_win_over_bundled(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({"enable_emojis": False}), encoding="utf-8")
        cfg = config.load_config()
        self.assertFalse(cfg["enable_emojis"])
        self.assertTrue(cfg["filter_filler_words"])

    def test_bundled_config_json_only_uses_known_keys(self):
        bundled = json.loads(config.BUNDLED_CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(set(bundled) - set(config.DEFAULT_CONFIG), set())


if __name__ == "__main__":
    unittest.main()
