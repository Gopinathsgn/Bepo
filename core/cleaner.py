"""
cleaner.py
Post-processing and sanitization for transcribed speech.

Features:
  - Filters non-lexical hesitation fillers (um, uh, erm, er, ah, hmm, mm, etc.)
  - Removes dangling or orphan commas left by removed fillers
  - Preserves sentence capitalization and punctuation
  - Normalizes whitespace
"""

import re
from core.emoji import parse_emojis

# Non-lexical conversational fillers in English (hesitation disfluencies)
FILLER_WORDS_PATTERN = r'\b(?:um+|uh+|erm|er+|ah+|hmm+|mm+)\b'


def clean_transcript(
    text: str,
    filter_fillers: bool = True,
    enable_emojis: bool = True
) -> str:
    """
    Cleans transcribed text:
    - Strips non-lexical filler words if filter_fillers is True
    - Converts spoken emoji descriptions to Unicode characters if enable_emojis is True
    - Normalizes punctuation and dangling commas
    - Fixes sentence capitalization
    - Collapses duplicate whitespace

    Returns sanitized string, or empty string if input was purely fillers/silence.
    """
    if not text:
        return ""

    cleaned = text.strip()
    if not cleaned:
        return ""

    if filter_fillers:
        # 1. Leading filler at start of string or right after sentence end (. ! ?):
        # e.g., ". Uh, " -> ". ", "Um, hello" -> "hello"
        cleaned = re.sub(
            rf'(?i)(^|[.!?]\s*){FILLER_WORDS_PATTERN}\s*[,—–-]?\s*',
            r'\1',
            cleaned
        )

        # 2. Filler surrounded by commas: ', um,' -> ','
        cleaned = re.sub(rf'(?i),\s*{FILLER_WORDS_PATTERN}\s*,', ',', cleaned)

        # 3. Filler preceded by comma: ', um ' -> ' '
        cleaned = re.sub(rf'(?i),\s*{FILLER_WORDS_PATTERN}\s*', ' ', cleaned)

        # 4. Filler followed by comma: ' um, ' -> ', '
        cleaned = re.sub(rf'(?i)\s*{FILLER_WORDS_PATTERN}\s*,', ', ', cleaned)

        # 5. Any standalone filler remaining:
        cleaned = re.sub(rf'(?i){FILLER_WORDS_PATTERN}', '', cleaned)

    if enable_emojis:
        cleaned = parse_emojis(cleaned, enabled=True)

    # 6. Normalize punctuation and collapse duplicate spaces
    cleaned = re.sub(r'\s*,\s*,+', ',', cleaned)             # duplicate commas
    cleaned = re.sub(r'[.!?]\s*,', '.', cleaned)             # dangling comma immediately after period
    cleaned = re.sub(r'\s+([,.:;?!])', r'\1', cleaned)       # space before punctuation
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()            # collapsed whitespace
    cleaned = re.sub(r'^[,\s;:]+', '', cleaned).strip()        # leading punctuation

    # If only whitespace and punctuation remains (e.g. '...' or ','), return empty string
    if not re.sub(r'[\s.,:;!?\'"—–-]+', '', cleaned):
        return ""

    # 7. Sentence capitalization (leave words that already have an internal capital alone:
    #    "iPhone", "eBay", "macOS" must not become "IPhone", "EBay", "MacOS")
    def _capitalize_match(match: re.Match) -> str:
        prefix, char, rest = match.group(1), match.group(2), match.group(3)
        if any(c.isupper() for c in rest):
            return match.group(0)
        return prefix + char.upper() + rest

    cleaned = re.sub(r"(^|[.!?]\s+)([a-z])([A-Za-z0-9'’]*)", _capitalize_match, cleaned)

    return cleaned
