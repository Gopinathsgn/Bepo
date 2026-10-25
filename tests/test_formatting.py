"""Spoken layout commands and the list state machine (core/formatting.py)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.formatting import BULLETS, NUMBERED, FormatCommand as F, ListState, parse_format_command


class ParseTests(unittest.TestCase):
    def test_recognized_phrases(self):
        cases = {
            "New line.": F.NEW_LINE, "next line": F.NEW_LINE,
            "New paragraph": F.NEW_PARAGRAPH, "Next paragraph.": F.NEW_PARAGRAPH,
            "Numbered list.": F.START_NUMBERED, "start a numbered list": F.START_NUMBERED,
            "Please make an ordered list": F.START_NUMBERED,
            "Bullet list": F.START_BULLETS, "Bulleted list.": F.START_BULLETS, "bullet points": F.START_BULLETS,
            "Next item.": F.NEXT_ITEM, "new item": F.NEXT_ITEM, "Next bullet point.": F.NEXT_ITEM,
            "End list.": F.END_LIST, "stop the list": F.END_LIST, "Finish numbered list": F.END_LIST,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_format_command(text), expected)

    def test_ordinary_sentences_are_never_commands(self):
        for text in ("The numbered list is long.", "I need a new line of credit", "What is the next item on the agenda?",
                     "Add a bullet list to the slide deck", "end of list", "", "   ", "hello"):
            with self.subTest(text=text):
                self.assertIsNone(parse_format_command(text))


class ListStateTests(unittest.TestCase):
    def test_numbered_items_start_on_new_lines(self):
        s = ListState()
        s.start(NUMBERED)
        typed = s.compose("Milk.", "Groceries:")
        self.assertEqual(typed, "\n1. Milk.")
        previous = "Groceries:" + typed
        self.assertEqual(s.compose("Organic.", previous), " Organic.")      # same item, just a pause
        s.next_item()
        self.assertEqual(s.compose("Eggs.", previous + " Organic."), "\n2. Eggs.")

    def test_first_item_on_an_empty_line_needs_no_extra_break(self):
        s = ListState()
        s.start(BULLETS)
        self.assertEqual(s.compose("One.", ""), "- One.")
        s.next_item()
        self.assertEqual(s.compose("Two.", "- One.\n"), "- Two.")

    def test_next_item_twice_does_not_skip_a_number(self):
        s = ListState()
        s.start(NUMBERED)
        s.compose("A.", "")
        s.next_item()
        s.next_item()
        self.assertEqual(s.compose("B.", "1. A."), "\n2. B.")

    def test_text_after_a_finished_list_starts_a_new_line(self):
        s = ListState()
        s.start(NUMBERED)
        s.compose("A.", "")
        self.assertTrue(s.end())
        self.assertEqual(s.compose("Done.", "1. A."), "\nDone.")
        self.assertEqual(s.compose("Really.", "1. A.\nDone."), " Really.")

    def test_commands_without_a_list_report_it(self):
        s = ListState()
        self.assertFalse(s.next_item())
        self.assertFalse(s.end())

    def test_snapshot_restore_undoes_an_item(self):
        s = ListState()
        s.start(NUMBERED)
        s.compose("A.", "")
        s.next_item()
        before = s.snapshot()
        s.compose("B.", "1. A.")
        s.restore(before)
        self.assertEqual(s.compose("B2.", "1. A."), "\n2. B2.")

    def test_plain_text_spacing(self):
        s = ListState()
        self.assertEqual(s.compose("Hello.", ""), "Hello.")
        self.assertEqual(s.compose("World.", "Hello."), " World.")
        self.assertEqual(s.compose(".", "Hello"), ".")
        self.assertEqual(s.compose("World.", "Hello.\n"), "World.")


if __name__ == "__main__":
    unittest.main()
