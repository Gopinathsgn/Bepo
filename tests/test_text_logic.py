"""Unit tests for the pure text-processing modules (no Qt, no Windows APIs)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.commands import CommandType, parse_voice_command
from core.cleaner import clean_transcript
from core.emoji import parse_emojis


class VoiceCommandTests(unittest.TestCase):
    def test_standalone_commands(self):
        self.assertEqual(parse_voice_command("Scratch that.")[0], CommandType.SCRATCH_THAT)
        self.assertEqual(parse_voice_command("undo")[0], CommandType.SCRATCH_THAT)
        self.assertEqual(parse_voice_command("Delete all")[0], CommandType.DELETE_ALL)
        self.assertEqual(parse_voice_command("Delete word.")[0], CommandType.DELETE_WORDS)

    def test_delete_n_words(self):
        cmd, count, _ = parse_voice_command("Delete last three words")
        self.assertEqual((cmd, count), (CommandType.DELETE_WORDS, 3))
        cmd, count, _ = parse_voice_command("delete last 12 words.")
        self.assertEqual((cmd, count), (CommandType.DELETE_WORDS, 12))

    def test_normal_speech_is_never_a_command(self):
        for text in ("The cat scratch that tree", "I need to undo", "Please delete the file"):
            cmd, _, remaining = parse_voice_command(text)
            self.assertEqual(cmd, CommandType.NONE, text)
            self.assertEqual(remaining, text)

    def test_inflight_correction(self):
        cmd, _, remaining = parse_voice_command("We meet at six, scratch that, we meet at seven")
        self.assertEqual(cmd, CommandType.NONE)
        self.assertEqual(remaining, "We meet at seven")

    def test_self_cancelled_utterance(self):
        cmd, _, remaining = parse_voice_command("We will meet at six. Scratch that.")
        self.assertEqual((cmd, remaining), (CommandType.NONE, ""))

    def test_empty(self):
        self.assertEqual(parse_voice_command(""), (CommandType.NONE, 0, ""))
        self.assertEqual(parse_voice_command("   "), (CommandType.NONE, 0, ""))


class CleanerTests(unittest.TestCase):
    def test_fillers_removed(self):
        self.assertEqual(clean_transcript("Um, hello world"), "Hello world")
        self.assertEqual(clean_transcript("I was um thinking"), "I was thinking")

    def test_only_fillers_is_empty(self):
        self.assertEqual(clean_transcript("Um."), "")
        self.assertEqual(clean_transcript("uh, hmm"), "")

    def test_real_words_containing_fillers_untouched(self):
        self.assertEqual(clean_transcript("Her herd is here"), "Her herd is here")
        self.assertEqual(clean_transcript("The summer is hot"), "The summer is hot")

    def test_filter_can_be_disabled(self):
        self.assertIn("um", clean_transcript("hello um world", filter_fillers=False).lower())

    def test_capitalisation(self):
        self.assertEqual(clean_transcript("hello there. how are you"), "Hello there. How are you")

    def test_words_with_internal_capitals_are_left_alone(self):
        self.assertEqual(clean_transcript("iPhone sales are up. eBay too. macOS next"),
                         "iPhone sales are up. eBay too. macOS next")
        self.assertEqual(clean_transcript("the iPhone is here"), "The iPhone is here")


class EmojiTests(unittest.TestCase):
    def test_requires_the_word_emoji(self):
        self.assertEqual(parse_emojis("We lit a fire"), "We lit a fire")
        self.assertEqual(parse_emojis("SpaceX built a rocket"), "SpaceX built a rocket")

    def test_conversion(self):
        self.assertEqual(parse_emojis("Great job thumbs up emoji!"), "Great job \U0001F44D!")
        self.assertEqual(parse_emojis("Launch the update rocket emoji"), "Launch the update \U0001F680")

    def test_disabled(self):
        self.assertEqual(parse_emojis("fire emoji", enabled=False), "fire emoji")


if __name__ == "__main__":
    unittest.main()
