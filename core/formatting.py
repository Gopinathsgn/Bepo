"""
formatting.py
Spoken layout commands for Bepo dictation: line breaks and numbered / bulleted lists.

Recognized as a whole utterance only (like the editing commands in commands.py), so ordinary
sentences such as "the numbered list is long" are never mistaken for a command:
  - "New line" / "New paragraph"
  - "Numbered list" / "Bullet list"  -> start a list (the next thing you say becomes item 1)
  - "Next item"                      -> the next thing you say starts a new item
  - "End list"                       -> leave list mode; following text starts on a new line

Pure Python (no Qt): the controller feeds utterances in and types whatever `ListState.compose` returns.
"""

import re
from enum import Enum, auto


class FormatCommand(Enum):
    NEW_LINE = auto()
    NEW_PARAGRAPH = auto()
    START_NUMBERED = auto()
    START_BULLETS = auto()
    NEXT_ITEM = auto()
    END_LIST = auto()


_END = r"[.,!?]?$"
_PLEASE = r"^(?:please\s+)?"

_PATTERNS: tuple[tuple[FormatCommand, re.Pattern], ...] = tuple(
    (cmd, re.compile(_PLEASE + body + _END, re.IGNORECASE))
    for cmd, body in (
        (FormatCommand.NEW_LINE, r"(?:new|next)\s+line"),
        (FormatCommand.NEW_PARAGRAPH, r"(?:new|next)\s+paragraph"),
        (FormatCommand.START_NUMBERED,
         r"(?:(?:start|begin|make)\s+)?(?:an?\s+|the\s+)?(?:numbered|number|ordered)\s+list"),
        (FormatCommand.START_BULLETS,
         r"(?:(?:start|begin|make)\s+)?(?:an?\s+|the\s+)?(?:bullet(?:ed)?|bullets)\s+(?:list|points?)"),
        (FormatCommand.NEXT_ITEM, r"(?:next|new)\s+(?:item|number|bullet(?:\s+point)?|point)"),
        (FormatCommand.END_LIST,
         r"(?:end|stop|finish|exit|close)\s+(?:the\s+)?(?:(?:numbered|bullet(?:ed)?)\s+)?list"),
    )
)


def parse_format_command(text: str) -> FormatCommand | None:
    """The layout command `text` consists of, or None if it is ordinary speech."""
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    for command, pattern in _PATTERNS:
        if pattern.match(cleaned):
            return command
    return None


NUMBERED = "numbered"
BULLETS = "bullets"
BULLET_MARKER = "- "

# (kind, number, need_marker, after_list)
Snapshot = tuple


class ListState:
    """
    Where the dictation currently is inside a list.

    The first utterance after "numbered list" gets "1. ", further utterances continue the same item
    (a pause mid-item must not split it) until "next item" is said.
    """

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.kind: str | None = None
        self.number = 0
        self.need_marker = False     # the next utterance opens a new item
        self.after_list = False      # the list just ended: the next text starts a fresh line

    @property
    def active(self) -> bool:
        return self.kind is not None

    # --- snapshots let "scratch that" put the list back exactly as it was -------------
    def snapshot(self) -> Snapshot:
        return (self.kind, self.number, self.need_marker, self.after_list)

    def restore(self, snap: Snapshot) -> None:
        self.kind, self.number, self.need_marker, self.after_list = snap

    # --- spoken commands -------------------------------------------------------------
    def start(self, kind: str) -> None:
        self.kind, self.number, self.need_marker, self.after_list = kind, 0, True, False

    def next_item(self) -> bool:
        """Returns False when there is no list to continue."""
        if not self.active:
            return False
        self.need_marker = True
        return True

    def end(self) -> bool:
        """Returns False when there was no list to end."""
        if not self.active:
            return False
        self.kind, self.need_marker, self.after_list = None, False, True
        return True

    # --- typing ----------------------------------------------------------------------
    def compose(self, text: str, previous: str) -> str:
        """
        What to type for the cleaned utterance `text`, given everything typed so far (`previous`):
        a list marker on a new line when an item starts, a line break after a finished list,
        otherwise a single space between sentences.
        """
        at_line_start = not previous or previous[-1] == "\n"

        if self.active and self.need_marker:
            self.number += 1
            self.need_marker = False
            marker = f"{self.number}. " if self.kind == NUMBERED else BULLET_MARKER
            return ("" if at_line_start else "\n") + marker + text

        if self.after_list:
            self.after_list = False
            if not at_line_start:
                return "\n" + text

        if previous and not previous[-1].isspace() and text[0] not in ".,!?;:)]}":
            return " " + text
        return text
