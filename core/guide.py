"""
guide.py
What the Help window teaches: shortcuts and the things you can say.

Pure Python (no Qt). The spoken phrases and examples live here, away from the widgets, so
tests/test_guide.py can feed every one of them through the real parsers (commands.py, formatting.py,
cleaner.py): if a regex changes, the Help window cannot quietly keep teaching the old phrase.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Entry:
    say: str                          # the phrase as spoken
    does: str                         # what it does, one short sentence
    also: tuple[str, ...] = ()        # other phrases with exactly the same effect
    spoken: str = ""                  # example: a whole utterance ...
    typed: str = ""                   # ... and what ends up typed

    @property
    def phrases(self) -> tuple[str, ...]:
        return (self.say, *self.also)


@dataclass(frozen=True)
class Topic:
    key: str                          # "edit" | "layout" | "text" | "emoji": picks the parser the tests use
    title: str
    intro: str
    entries: tuple[Entry, ...]
    # Settings that must all be on for the topic to work: (config key, label of that setting)
    gates: tuple[tuple[str, str], ...] = ()
    example: tuple[tuple[str, ...], str] | None = None    # (utterances in order, text typed)


EDIT = Topic(
    key="edit",
    title="Fix mistakes",
    intro="Say these on their own, as a separate phrase. They work on what you dictated in this session.",
    entries=(
        Entry("Scratch that", "Erases your last sentence. Say it again to step back further.",
              also=("Delete that", "Undo")),
        Entry("Delete last word", "Erases the last word you typed.", also=("Delete word",)),
        Entry("Delete last 3 words", "Erases that many words. Any number works.",
              also=("Delete last two words",)),
        Entry("Clear all", "Erases everything you dictated in this session.", also=("Delete all",)),
        Entry("We meet at six, scratch that, we meet at seven",
              "Correct yourself in mid-sentence: the part before “scratch that” is dropped.",
              spoken="We meet at six, scratch that, we meet at seven", typed="We meet at seven"),
    ),
)

LAYOUT = Topic(
    key="layout",
    title="Lines & lists",
    intro="Say the command as its own phrase and pause briefly. Hands-free mode only: "
          "push-to-talk types your words as spoken.",
    entries=(
        Entry("New line", "Starts a new line.", also=("Next line",)),
        Entry("New paragraph", "Leaves a blank line.", also=("Next paragraph",)),
        Entry("Numbered list", "Starts a list: what you say next becomes item 1.",
              also=("Start a numbered list",)),
        Entry("Bullet list", "Same, with dashes instead of numbers.", also=("Start a bullet list",)),
        Entry("Next item", "The next thing you say becomes the next item. "
                           "A pause in the middle of an item does not split it.",
              also=("Next point",)),
        Entry("End list", "Leaves the list. The next sentence starts on a fresh line.",
              also=("Stop list",)),
    ),
    gates=(("voice_formatting", "Spoken line breaks and lists"),
           ("continuous_mode", "Type sentence by sentence while I speak")),
    example=(("Shopping list.", "Numbered list.", "Buy milk.", "Next item.", "Buy eggs.", "End list."),
             "Shopping list.\n1. Buy milk.\n2. Buy eggs."),
)

TEXT = Topic(
    key="text",
    title="Punctuation & numbers",
    intro="Just say them in the middle of a sentence.",
    entries=(
        Entry("Question mark", "Types the symbol.",
              also=("Exclamation point", "Comma", "Colon", "Semicolon"),
              spoken="is that right question mark", typed="Is that right?"),
        Entry("Open paren … close paren", "Wraps what you say in brackets. Quotes work the same way: open quote, close quote.",
              spoken="open paren note close paren", typed="(note)"),
        Entry("Twenty five", "Numbers become digits. A lone “one” to “ten” stays a word, so “no one knows” is safe.",
              spoken="twenty five apples", typed="25 apples"),
        Entry("Ten dollars", "Percent and dollars are understood too.",
              also=("Fifty percent",), spoken="it costs ten dollars", typed="It costs $10"),
        Entry("Alex at example dot com", "E-mail addresses and web addresses.",
              also=("Example dot com",), spoken="send it to alex at example dot com",
              typed="Send it to alex@example.com"),
    ),
    gates=(("smart_formatting", "Spoken punctuation, numbers and addresses"),),
)

EMOJI = Topic(
    key="emoji",
    title="Emoji",
    intro="Say what the emoji is, then the word “emoji”. There are over 100; here are a few. "
          "Without the word “emoji” nothing is replaced, so “we lit a fire” stays text.",
    entries=(
        Entry("Thumbs up emoji", "Types 👍", spoken="great job thumbs up emoji", typed="Great job 👍"),
        Entry("Fire emoji", "Types 🔥", spoken="that idea is fire emoji", typed="That idea is 🔥"),
        Entry("Rocket emoji", "Types 🚀", spoken="launch the update rocket emoji", typed="Launch the update 🚀"),
        Entry("Folded hands emoji", "Types 🙏", spoken="thank you so much folded hands emoji",
              typed="Thank you so much 🙏"),
        Entry("Crying laughing emoji", "Types 😂", spoken="that was hilarious crying laughing emoji",
              typed="That was hilarious 😂"),
        Entry("Red heart emoji", "Types ❤️", spoken="sending love red heart emoji", typed="Sending love ❤️"),
        Entry("Check mark emoji", "Types ✅", spoken="pull request approved check mark emoji",
              typed="Pull request approved ✅"),
        Entry("Thinking face emoji", "Types 🤔", spoken="let me think thinking face emoji",
              typed="Let me think 🤔"),
    ),
    gates=(("enable_emojis", "Turn spoken emoji into symbols"),),
)

TOPICS: tuple[Topic, ...] = (EDIT, LAYOUT, TEXT, EMOJI)


def disabled_reason(topic: Topic, config: dict) -> str:
    """Why `topic` does not work with the current settings, or "" when it does."""
    for key, label in topic.gates:
        if not config.get(key, True):
            return f"Currently off. Turn on “{label}” in Settings to use this."
    return ""


@dataclass(frozen=True)
class Shortcut:
    keys: str            # what to press, or "Off"
    does: str
    enabled: bool = True


def shortcuts(toggle: str, ptt: str, undo: str, esc_to_finish: bool = True) -> list[Shortcut]:
    """
    The start/stop shortcuts in the order a new user needs them. Each label is the shortcut as
    the running app has it ("" = disabled), so a rebinding in Settings shows up here.
    """
    rows = [
        Shortcut(toggle, "Start dictating, hands-free. Speak as long as you like, then press it again to stop.")
        if toggle else
        Shortcut("Off", "Hands-free shortcut. Choose one in Settings, or start from the tray menu.", False),
        Shortcut(f"Hold {ptt}", "Push-to-talk. Speak while you hold it; your words are typed when you let go.")
        if ptt else
        Shortcut("Off", "Push-to-talk shortcut. Choose one in Settings.", False),
    ]
    if esc_to_finish:
        rows.append(Shortcut("Esc", "Finish while dictating: the last words are typed and the microphone is released."))
    rows.append(
        Shortcut(undo, "Take back everything your last dictation typed. Works when you are not dictating, "
                       "in the window you dictated into.")
        if undo else
        Shortcut("Off", "Undo-last-dictation shortcut. Choose one in Settings.", False)
    )
    return rows
