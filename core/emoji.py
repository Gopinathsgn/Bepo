"""
emoji.py
Spoken emoji parser and converter for Bepo dictation.

Converts spoken emoji phrases (e.g., "thumbs up emoji", "fire emoji", "crying laughing emoji")
into their native Unicode characters.

Features:
  - 100+ popular emojis across smiles, gestures, hearts, objects, and symbols
  - Requires the word 'emoji' (or 'emoticon') to prevent accidental conversion of regular words
  - Smooth spacing normalization around preceding text and following punctuation
"""

import re

# Mapping of tuple of phrase synonyms -> emoji character
EMOJI_PHRASE_MAP: dict[tuple[str, ...], str] = {
    # Faces & Expressions
    ("crying laughing", "tears of joy", "laughing with tears", "crying with laughter", "laughing"): "😂",
    ("rolling on the floor laughing", "rofl"): "🤣",
    ("smiling face with heart eyes", "heart eyes"): "😍",
    ("smiling face with sunglasses", "sunglasses face", "sunglasses", "cool face"): "😎",
    ("smiling face", "smile", "smiley", "smiling"): "😊",
    ("grinning face", "grin", "grinning"): "😀",
    ("beaming face", "beaming"): "😁",
    ("winking face", "winking", "wink"): "😉",
    ("thinking face", "thinking"): "🤔",
    ("saluting face", "salute", "saluting"): "🫡",
    ("partying face", "party face", "party"): "🥳",
    ("loudly crying face", "loudly crying", "crying face", "crying", "sob", "sobbing"): "😭",
    ("screaming face", "screaming in fear", "screaming", "shocked"): "😱",
    ("exploding head", "mind blown"): "🤯",
    ("melting face", "melting"): "🫠",
    ("flushed face", "flushed", "embarrassed"): "😳",
    ("sleeping face", "sleeping", "sleepy"): "😴",
    ("pensive face", "sad face", "sad"): "😔",
    ("angry face", "angry", "mad"): "😠",
    ("smirking face", "smirk"): "😏",
    ("face with rolling eyes", "rolling eyes", "eye roll"): "🙄",
    ("shushing face", "shh", "quiet"): "🤫",
    ("zipper mouth", "zipper face"): "🤐",
    ("nerd face", "nerd"): "🤓",
    ("clown face", "clown"): "🤡",
    ("skull", "dead"): "💀",
    ("ghost",): "👻",
    ("pile of poo", "poop", "poo"): "💩",
    ("shrug", "shrugging"): "🤷",
    ("facepalm", "face palm"): "🤦",
    ("eyes", "side eye"): "👀",
    ("hugging face", "hug", "hugging"): "🤗",

    # Gestures & Hands
    ("thumbs up", "thumbs-up"): "👍",
    ("thumbs down", "thumbs-down"): "👎",
    ("clapping hands", "clapping", "applause", "clap"): "👏",
    ("folded hands", "praying hands", "prayer", "praying", "pray"): "🙏",
    ("handshake",): "🤝",
    ("peace sign", "peace", "victory"): "✌️",
    ("fingers crossed", "crossed fingers"): "🤞",
    ("high five", "raised hand"): "✋",
    ("waving hand", "wave", "waving"): "👋",
    ("flexed biceps", "muscle", "flex"): "💪",
    ("pinching hand", "pinch"): "🤏",
    ("pointing up", "point up"): "☝️",
    ("pointing down", "point down"): "👇",
    ("pointing left", "point left"): "👈",
    ("pointing right", "point right"): "👉",
    ("fist bump", "raised fist"): "👊",

    # Hearts & Affection
    ("red heart", "heart"): "❤️",
    ("broken heart",): "💔",
    ("sparkling heart",): "💖",
    ("heart on fire", "fire heart"): "❤️‍🔥",
    ("black heart",): "🖤",
    ("white heart",): "🤍",
    ("blue heart",): "💙",
    ("green heart",): "💚",
    ("purple heart",): "💜",

    # Symbols & Reactions
    ("fire", "flame", "lit"): "🔥",
    ("sparkles", "sparkle", "magic"): "✨",
    ("collision", "boom", "explosion"): "💥",
    ("hundred points", "hundred", "100"): "💯",
    ("check mark", "checkmark", "green check"): "✅",
    ("cross mark", "red x"): "❌",
    ("warning sign", "warning"): "⚠️",
    ("question mark",): "❓",
    ("exclamation mark", "exclamation point"): "❗️",
    ("star", "glowing star"): "⭐",
    ("lightning bolt", "lightning", "zap"): "⚡",
    ("sun", "sunny"): "☀️",
    ("rainbow",): "🌈",

    # Celebration & Objects
    ("party popper", "celebration", "tada", "confetti"): "🎉",
    ("balloon",): "🎈",
    ("trophy",): "🏆",
    ("medal",): "🥇",
    ("crown",): "👑",
    ("diamond", "gem stone"): "💎",
    ("gift", "present"): "🎁",
    ("rocket ship", "rocket"): "🚀",
    ("light bulb", "lightbulb", "idea"): "💡",
    ("money bag", "money", "cash", "dollar"): "💰",
    ("laptop", "computer"): "💻",
    ("mobile phone", "cell phone", "phone"): "📱",
    ("coffee", "hot beverage"): "☕",
    ("beer", "cheers", "beers"): "🍻",
    ("wine", "wine glass"): "🍷",
    ("pizza",): "🍕",
    ("birthday cake", "cake"): "🎂",
    ("airplane", "plane"): "✈️",

    # Animals
    ("dog", "puppy"): "🐶",
    ("cat", "kitten"): "🐱",
    ("goat", "the goat"): "🐐",
    ("monkey",): "🐵",
}

# Compile patterns once at import time
_COMPILED_EMOJI_PATTERNS: list[tuple[re.Pattern, str]] = []

for _phrases, _emoji in EMOJI_PHRASE_MAP.items():
    _sorted = sorted(_phrases, key=len, reverse=True)
    _joined = "|".join(re.escape(p) for p in _sorted)
    # Matches: optional leading article 'a/an/the ', target phrase, optional ' face', mandatory ' emoji/emoticon'
    _pat = re.compile(
        rf"(?i)\b(?:(?:a|an|the)\s+)?(?:{_joined})(?:\s+face)?\s+(?:emoji|emoticon)s?\b"
    )
    _COMPILED_EMOJI_PATTERNS.append((_pat, _emoji))


def parse_emojis(text: str, enabled: bool = True) -> str:
    """
    Scans `text` for spoken emoji descriptions and replaces them with Unicode emojis.

    Example:
        parse_emojis("Awesome job thumbs up emoji!") -> "Awesome job 👍!"
        parse_emojis("Launch the rocket rocket emoji now") -> "Launch the rocket 🚀 now"

    Parameters:
        text: Input string.
        enabled: If False, returns the input unmodified.

    Returns:
        String with spoken emoji phrases replaced by emoji glyphs.
    """
    if not enabled or not text or "emoji" not in text.lower() and "emoticon" not in text.lower():
        return text

    result = text
    for pat, emoji_char in _COMPILED_EMOJI_PATTERNS:
        result = pat.sub(f" {emoji_char} ", result)

    # Normalize spacing:
    # 1. No space before attaching punctuation (e.g. '🔥 !' -> '🔥!')
    result = re.sub(r"\s+([,.:;?!])", r"\1", result)
    # 2. Collapse double spaces
    result = re.sub(r"\s+", " ", result).strip()

    return result
