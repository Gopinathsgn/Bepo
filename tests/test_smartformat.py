"""Spoken punctuation, numbers and addresses (core/smartformat.py) and their use by the cleaner."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cleaner import clean_transcript
from core.smartformat import smart_format


class PunctuationTests(unittest.TestCase):
    def test_spoken_marks(self):
        self.assertEqual(smart_format("Hello comma how are you question mark"), "Hello, how are you?")
        self.assertEqual(smart_format("Wait exclamation point"), "Wait!")
        self.assertEqual(smart_format("one thing colon eggs semicolon milk"), "one thing: eggs; milk")

    def test_model_punctuation_around_the_spoken_word_is_absorbed(self):
        self.assertEqual(smart_format("Hello, comma, how are you?"), "Hello, how are you?")

    def test_period_only_counts_at_the_end_of_an_utterance(self):
        self.assertEqual(smart_format("that was the end period"), "that was the end.")
        self.assertEqual(smart_format("the period was long"), "the period was long")

    def test_quotes_and_parentheses(self):
        self.assertEqual(smart_format("he said open quote hi there close quote loudly"), 'he said "hi there" loudly')
        self.assertEqual(smart_format("open paren note close paren done"), "(note) done")

    def test_ordinary_sentences_are_untouched(self):
        for text in ("I will call you tomorrow.", "Send it to the printer, please.", "Is it ready?"):
            self.assertEqual(smart_format(text), text)


class NumberTests(unittest.TestCase):
    def test_compound_numbers_become_digits(self):
        self.assertEqual(smart_format("twenty five apples"), "25 apples")
        self.assertEqual(smart_format("one hundred and twenty three cats"), "123 cats")
        self.assertEqual(smart_format("two thousand five hundred"), "2500")
        self.assertEqual(smart_format("twelve people"), "12 people")

    def test_years(self):
        self.assertEqual(smart_format("in twenty twenty six"), "in 2026")
        self.assertEqual(smart_format("born nineteen ninety nine"), "born 1999")
        self.assertEqual(smart_format("two thousand twenty six"), "2026")
        self.assertEqual(smart_format("twenty oh five"), "2005")

    def test_decimals_percent_and_money(self):
        self.assertEqual(smart_format("three point five percent"), "3.5%")
        self.assertEqual(smart_format("it grew 50 percent"), "it grew 50%")
        self.assertEqual(smart_format("pay me fifty dollars"), "pay me $50")
        self.assertEqual(smart_format("five dollars"), "$5")

    def test_small_numbers_in_prose_stay_words(self):
        for text in ("no one knows", "I have two cats", "one two three", "ten minutes"):
            self.assertEqual(smart_format(text), text)

    def test_malformed_number_phrases_are_left_alone(self):
        self.assertEqual(smart_format("twenty thirty forty"), "twenty thirty forty")
        self.assertEqual(smart_format("hundred"), "hundred")


class AddressTests(unittest.TestCase):
    def test_email_and_domain(self):
        self.assertEqual(smart_format("mail jane at gmail dot com now"), "mail jane@gmail.com now")
        self.assertEqual(smart_format("visit example dot com"), "visit example.com")

    def test_at_and_dot_in_normal_speech_are_left_alone(self):
        self.assertEqual(smart_format("meet me at noon"), "meet me at noon")
        self.assertEqual(smart_format("connect the dot"), "connect the dot")


class CleanerIntegrationTests(unittest.TestCase):
    def test_off_by_default(self):
        self.assertEqual(clean_transcript("twenty five apples"), "Twenty five apples")

    def test_on(self):
        self.assertEqual(clean_transcript("twenty five apples", smart_formatting=True), "25 apples")

    def test_capitalises_after_a_spoken_sentence_end(self):
        self.assertEqual(
            clean_transcript("is it ready question mark yes it is", smart_formatting=True),
            "Is it ready? Yes it is",
        )

    def test_a_lone_spoken_mark_is_kept(self):
        self.assertEqual(clean_transcript("question mark", smart_formatting=True), "?")


if __name__ == "__main__":
    unittest.main()
