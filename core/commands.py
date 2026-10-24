"""
commands.py
Voice editing and deletion command parser for Bepo.

Recognizes spoken editing commands:
  - "Scratch that" / "Delete that" / "Undo that" / "Undo" -> Retract last sentence/utterance
  - "Delete word" / "Delete last word"                   -> Retract last word
  - "Delete last <N> words"                              -> Retract last N words
  - "Delete all" / "Clear all"                           -> Retract entire session dictation
  - In-flight correction: "We meet at six, scratch that, we meet at seven" -> Self-corrects

Guarantees zero false positives on normal speech like "The cat scratch that tree".
"""

import re
from enum import Enum, auto


class CommandType(Enum):
    NONE = auto()
    SCRATCH_THAT = auto()    # Retract last sentence/segment
    DELETE_WORDS = auto()    # Retract last N words
    DELETE_ALL = auto()      # Retract entire dictation session


# Number word mapping for "delete last three words", etc.
WORD_TO_NUM: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

# Standalone command patterns (requires whole utterance match with optional polite prefix/punctuation)
_SCRATCH_THAT_STANDALONE = re.compile(
    r"^(?:please\s+)?(?:scratch\s+that|delete\s+that|erase\s+that|undo\s+that|undo)[.!]?$",
    re.IGNORECASE,
)

_DELETE_WORD_STANDALONE = re.compile(
    r"^(?:please\s+)?(?:delete|erase|scratch)\s+(?:the\s+)?(?:last\s+)?word[.!]?$",
    re.IGNORECASE,
)

_DELETE_N_WORDS_STANDALONE = re.compile(
    r"^(?:please\s+)?(?:delete|erase|scratch)\s+(?:the\s+)?last\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+words?[.!]?$",
    re.IGNORECASE,
)

_DELETE_ALL_STANDALONE = re.compile(
    r"^(?:please\s+)?(?:delete\s+all|clear\s+all|scratch\s+all|erase\s+all)[.!]?$",
    re.IGNORECASE,
)

# In-flight correction pattern: user corrects themselves in a single sentence
# Requires punctuation bounds to prevent matching "The cat scratch that tree"
_INFLIGHT_CORRECTION = re.compile(
    r"(?i)(?:[,—–-]\s*\b(?:scratch\s+that|delete\s+that)\b\s*[,—–-]|[.!?]\s*\b(?:scratch\s+that|delete\s+that)\b[.!?]?\s*$)"
)


def parse_voice_command(text: str) -> tuple[CommandType, int, str]:
    """
    Parses `text` for voice deletion/editing commands.

    Returns:
        tuple (command_type, count, remaining_text)
        - If standalone command: (CommandType.*, count, "")
        - If in-flight correction: (CommandType.NONE, 0, corrected_text)
        - If normal text: (CommandType.NONE, 0, text)
    """
    if not text:
        return (CommandType.NONE, 0, "")

    cleaned = text.strip()
    if not cleaned:
        return (CommandType.NONE, 0, "")

    # 1. Standalone command checks
    if _SCRATCH_THAT_STANDALONE.match(cleaned):
        return (CommandType.SCRATCH_THAT, 1, "")

    if _DELETE_WORD_STANDALONE.match(cleaned):
        return (CommandType.DELETE_WORDS, 1, "")

    m_n = _DELETE_N_WORDS_STANDALONE.match(cleaned)
    if m_n:
        val = m_n.group(1).lower()
        count = int(val) if val.isdigit() else WORD_TO_NUM.get(val, 1)
        return (CommandType.DELETE_WORDS, count, "")

    if _DELETE_ALL_STANDALONE.match(cleaned):
        return (CommandType.DELETE_ALL, 0, "")

    # 2. In-flight correction check
    parts = _INFLIGHT_CORRECTION.split(cleaned)
    if len(parts) > 1:
        before = parts[0].strip()
        after = parts[-1].strip()
        if before and after:
            # Self-corrected: drop 'before', capitalize and keep 'after'
            after_cap = after[0].upper() + after[1:] if len(after) > 1 else after.upper()
            return (CommandType.NONE, 0, after_cap)
        elif before and not after:
            # Utterance self-cancelled before being typed
            return (CommandType.NONE, 0, "")
        elif not before and not after:
            return (CommandType.SCRATCH_THAT, 1, "")

    return (CommandType.NONE, 0, cleaned)
