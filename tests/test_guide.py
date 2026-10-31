"""
The Help content (core/guide.py) must only teach what Bepo really understands: every phrase and every
example is run through the real parsers, so a changed regex breaks this test instead of the Help window.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import config, guide
from core.cleaner import clean_transcript
from core.commands import CommandType, parse_voice_command
from core.formatting import BULLETS, NUMBERED, FormatCommand, ListState, parse_format_command


def _type_session(utterances) -> str:
    """What the live typing path (main._on_segment) produces for `utterances`."""
    state, typed = ListState(), ""
    for utterance in utterances:
        command = parse_format_command(utterance)
        if command is not None:
            if command == FormatCommand.START_NUMBERED:
                state.start(NUMBERED)
            elif command == FormatCommand.START_BULLETS:
                state.start(BULLETS)
            elif command == FormatCommand.NEXT_ITEM:
                state.next_item()
            elif command == FormatCommand.END_LIST:
                state.end()
            continue
        typed += state.compose(clean_transcript(utterance), typed)
    return typed


class PhraseTests(unittest.TestCase):
    def test_every_edit_phrase_is_a_command_or_a_self_correction(self):
        for entry in guide.EDIT.entries:
            for phrase in entry.phrases:
                command, _count, remaining = parse_voice_command(phrase)
                self.assertTrue(command != CommandType.NONE or remaining != phrase,
                                f"{phrase!r} is not understood")

    def test_edit_examples_type_what_the_help_says(self):
        for entry in guide.EDIT.entries:
            if entry.spoken:
                self.assertEqual(parse_voice_command(entry.spoken)[2], entry.typed)

    def test_edit_phrases_map_to_the_documented_commands(self):
        self.assertEqual(parse_voice_command("Delete last 3 words")[:2], (CommandType.DELETE_WORDS, 3))
        self.assertEqual(parse_voice_command("Clear all")[0], CommandType.DELETE_ALL)
        self.assertEqual(parse_voice_command("Scratch that")[0], CommandType.SCRATCH_THAT)

    def test_every_layout_phrase_is_a_layout_command(self):
        for entry in guide.LAYOUT.entries:
            for phrase in entry.phrases:
                self.assertIsNotNone(parse_format_command(phrase), f"{phrase!r} is not understood")

    def test_the_list_example_types_what_the_help_says(self):
        utterances, typed = guide.LAYOUT.example
        self.assertEqual(_type_session(utterances), typed)

    def test_text_and_emoji_examples_type_what_the_help_says(self):
        for topic in (guide.TEXT, guide.EMOJI):
            for entry in topic.entries:
                if entry.spoken:
                    cleaned = clean_transcript(entry.spoken, filter_fillers=True, enable_emojis=True,
                                               smart_formatting=True)
                    self.assertEqual(cleaned, entry.typed, entry.spoken)

    def test_emoji_topic_has_eight_examples_that_all_show_their_result(self):
        self.assertEqual(len(guide.EMOJI.entries), 8)
        for entry in guide.EMOJI.entries:
            self.assertTrue(entry.spoken and entry.typed)
            self.assertIn(entry.typed.split()[-1], entry.does)

    def test_gates_name_real_settings(self):
        for topic in guide.TOPICS:
            for key, label in topic.gates:
                self.assertIn(key, config.DEFAULT_CONFIG)
                self.assertIsInstance(config.DEFAULT_CONFIG[key], bool)
                self.assertTrue(label)


class StateTests(unittest.TestCase):
    def test_nothing_is_reported_off_with_default_settings(self):
        for topic in guide.TOPICS:
            self.assertEqual(guide.disabled_reason(topic, config.normalize({})), "")

    def test_a_switched_off_feature_names_the_setting_to_turn_on(self):
        off = config.normalize({"voice_formatting": False, "smart_formatting": False, "enable_emojis": False})
        self.assertIn("Spoken line breaks and lists", guide.disabled_reason(guide.LAYOUT, off))
        self.assertIn("Spoken punctuation", guide.disabled_reason(guide.TEXT, off))
        self.assertIn("spoken emoji", guide.disabled_reason(guide.EMOJI, off))
        self.assertEqual(guide.disabled_reason(guide.EDIT, off), "")

    def test_layout_needs_sentence_by_sentence_typing(self):
        cfg = config.normalize({"continuous_mode": False})
        self.assertIn("sentence by sentence", guide.disabled_reason(guide.LAYOUT, cfg))


class ShortcutTests(unittest.TestCase):
    def test_default_shortcuts_in_teaching_order(self):
        rows = guide.shortcuts("Ctrl+Win", "Ctrl+Space", "Alt+Win+Z")
        self.assertEqual([r.keys for r in rows], ["Ctrl+Win", "Hold Ctrl+Space", "Esc", "Alt+Win+Z"])
        self.assertTrue(all(r.enabled for r in rows))

    def test_rebound_shortcuts_are_shown_as_the_user_set_them(self):
        rows = guide.shortcuts("F9", "Ctrl+Alt+Space", "Ctrl+Shift+Z")
        self.assertEqual([r.keys for r in rows][:2] + [rows[-1].keys], ["F9", "Hold Ctrl+Alt+Space", "Ctrl+Shift+Z"])

    def test_disabled_shortcuts_say_so_and_point_to_settings(self):
        rows = guide.shortcuts("", "", "")
        self.assertEqual([r.keys for r in rows], ["Off", "Off", "Esc", "Off"])
        self.assertEqual([r.enabled for r in rows], [False, False, True, False])
        for row in (rows[0], rows[1], rows[3]):
            self.assertIn("Settings", row.does)

    def test_esc_row_follows_the_setting(self):
        rows = guide.shortcuts("Ctrl+Win", "Ctrl+Space", "Alt+Win+Z", esc_to_finish=False)
        self.assertNotIn("Esc", [r.keys for r in rows])


if __name__ == "__main__":
    unittest.main()
