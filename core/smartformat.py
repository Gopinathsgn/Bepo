"""
smartformat.py
Spoken punctuation, numbers and web addresses -> the characters people actually want typed.

Pure Python (no Qt). Everything here is deliberately conservative: a phrase is only rewritten when
it is unambiguous enough that leaving it as words would almost never be what the speaker meant.

  Punctuation   "question mark", "exclamation point", "full stop", "comma", "colon", "semicolon",
                "open/close quote", "open/close paren" (and "period" when it ends the utterance)
  Numbers       "twenty five" -> 25, "two hundred" -> 200, "three point five" -> 3.5,
                "twenty twenty six" -> 2026, "fifty percent" -> 50%, "ten dollars" -> $10.
                Single small numbers ("one", "two" ... "ten") stay words: "no one knows" is prose.
  Addresses     "name at gmail dot com" -> name@gmail.com, "example dot com" -> example.com
"""

import re

_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALES = {"thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}
_DIGIT_WORDS = {w: v for w, v in _ONES.items() if v <= 9}

_NUM_WORD = "|".join(sorted([*_ONES, *_TENS, "hundred", *_SCALES], key=len, reverse=True))
_RUN = rf"(?:{_NUM_WORD})(?:[\s-]+(?:and[\s-]+)?(?:{_NUM_WORD}))*"
_DIGIT_RUN = "(?:" + "|".join([*_DIGIT_WORDS, "oh"]) + r")(?:[\s-]+(?:" + "|".join([*_DIGIT_WORDS, "oh"]) + "))*"

_RUN_RE = re.compile(rf"(?i)\b{_RUN}\b")
_DECIMAL_RE = re.compile(rf"(?i)\b(?P<int>{_RUN})\s+point\s+(?P<frac>{_DIGIT_RUN})\b")
_YEAR_OH = re.compile(
    r"(?i)\b(nineteen|twenty)[\s-]+oh[\s-]+(one|two|three|four|five|six|seven|eight|nine)\b")
_UNIT_AFTER = re.compile(r"(?i)\s*(?:percent|per\s*cent|dollars?)\b")


def _parse_cardinal(words: list[str]) -> int | None:
    """Value of a cardinal written in words, or None if the words are not a well-formed number."""
    total, current = 0, 0
    last = None                    # kind of the previous word
    last_scale = None
    for w in words:
        if w == "and":
            if last not in ("hundred", "scale"):
                return None
            continue
        if w == "hundred":
            if last != "ones":
                return None
            current *= 100
            last = "hundred"
        elif w in _SCALES:
            if last not in ("ones", "teens", "tens", "hundred") or current == 0:
                return None
            if last_scale is not None and _SCALES[w] >= last_scale:
                return None
            total += current * _SCALES[w]
            current, last, last_scale = 0, "scale", _SCALES[w]
        elif w in _TENS:
            if last not in (None, "hundred", "scale"):
                return None
            current += _TENS[w]
            last = "tens"
        elif w in _ONES:
            value = _ONES[w]
            if value == 0:
                if len(words) != 1:
                    return None
                return 0
            kind = "ones" if value <= 9 else "teens"
            if kind == "ones" and last not in (None, "tens", "hundred", "scale"):
                return None
            if kind == "teens" and last not in (None, "hundred", "scale"):
                return None
            current += value
            last = kind
        else:
            return None
    if last is None or words[-1] == "and":
        return None
    return total + current


def _parse_year(words: list[str]) -> int | None:
    """Years such as "twenty twenty six", "nineteen ninety nine", "twenty oh five", "nineteen hundred"."""
    if len(words) < 2 or words[0] not in ("nineteen", "twenty"):
        return None
    century = 1900 if words[0] == "nineteen" else 2000
    rest = words[1:]
    if rest == ["hundred"]:
        return century
    if rest[0] == "oh" and len(rest) == 2 and rest[1] in _DIGIT_WORDS and rest[1] != "zero":
        return century + _ONES[rest[1]]
    if rest[0] in _TENS and len(rest) == 1:
        return century + _TENS[rest[0]]
    if rest[0] in _TENS and len(rest) == 2 and rest[1] in _DIGIT_WORDS and rest[1] != "zero":
        return century + _TENS[rest[0]] + _ONES[rest[1]]
    if len(rest) == 1 and 10 <= _ONES.get(rest[0], -1) <= 19:
        return century + _ONES[rest[0]]
    return None


def _words(run: str) -> list[str]:
    return [w for w in re.split(r"[\s-]+", run.lower()) if w]


def _convert_run(match: re.Match) -> str:
    original = match.group(0)
    words = _words(original)
    year = _parse_year(words)
    if year is not None:
        return str(year)
    value = _parse_cardinal(words)
    if value is None:
        return original
    unit_follows = _UNIT_AFTER.match(match.string, match.end()) is not None
    if value <= 10 and not unit_follows:
        return original          # "one", "two" ... "ten" read better as words in prose
    return str(value)


def _convert_decimal(match: re.Match) -> str:
    whole = _parse_cardinal(_words(match.group("int")))
    if whole is None:
        return match.group(0)
    digits = "".join("0" if w == "oh" else str(_DIGIT_WORDS[w]) for w in _words(match.group("frac")))
    return f"{whole}.{digits}"


def normalize_numbers(text: str) -> str:
    """Spoken numbers -> digits, "percent" -> %, "dollars" -> $ (see the module docstring)."""
    text = _YEAR_OH.sub(
        lambda m: str((1900 if m.group(1).lower() == "nineteen" else 2000) + _ONES[m.group(2).lower()]), text)
    text = _DECIMAL_RE.sub(_convert_decimal, text)
    text = _RUN_RE.sub(_convert_run, text)
    text = re.sub(r"(?i)(\d(?:[\d,]*\d)?(?:\.\d+)?)\s*(?:percent|per\s*cent)\b", r"\1%", text)
    text = re.sub(r"(?i)\b(\d(?:[\d,]*\d)?(?:\.\d+)?)\s+dollars?\b", r"$\1", text)
    return text


# ---------------------------------------------------------------------- #
# Punctuation                                                             #
# ---------------------------------------------------------------------- #

_PUNCTUATION = tuple(
    (re.compile(rf"(?i)\s*[,.]?\s*\b{phrase}\b[,.?!]?"), symbol + " ")
    for phrase, symbol in (
        (r"question\s+mark", "?"),
        (r"exclamation\s+(?:mark|point)", "!"),
        (r"full\s+stop", "."),
        (r"semi-?colon", ";"),
        (r"colon", ":"),
        (r"comma", ","),
    )
)
_PERIOD_AT_END = re.compile(r"(?i)\s*[,.]?\s*\bperiod\b[.!?]?\s*$")
_OPEN_BRACKET = re.compile(r"(?i)\bopen\s+(?:quotes?|paren(?:thesis|theses)?|brackets?)\s*")
_CLOSE_BRACKET = re.compile(r"(?i)\s*\bclose\s+(?:quotes?|paren(?:thesis|theses)?|brackets?)\b[,.]?")
_BRACKET_KIND = re.compile(r"(?i)(quote|paren|bracket)")


def _bracket(match: re.Match, opening: bool) -> str:
    kind = _BRACKET_KIND.search(match.group(0)).group(1).lower()
    return {"quote": '"', "paren": "()"[0 if opening else 1], "bracket": "[]"[0 if opening else 1]}[kind]


def spoken_punctuation(text: str) -> str:
    """"hello comma how are you question mark" -> "hello, how are you?"."""
    for pattern, replacement in _PUNCTUATION:
        text = pattern.sub(replacement, text)
    text = _PERIOD_AT_END.sub(". ", text)
    text = _OPEN_BRACKET.sub(lambda m: _bracket(m, True), text)
    text = _CLOSE_BRACKET.sub(lambda m: _bracket(m, False), text)
    return text


# ---------------------------------------------------------------------- #
# Addresses                                                               #
# ---------------------------------------------------------------------- #

_TLDS = r"(?:com|org|net|edu|gov|io|dev|ai|app|co)"
_EMAIL = re.compile(rf"(?i)\b([a-z0-9][a-z0-9._-]*)\s+at\s+([a-z0-9-]+)\s+dot\s+({_TLDS})\b")
_DOMAIN = re.compile(rf"(?i)\b([a-z0-9][a-z0-9-]*)\s+dot\s+({_TLDS})\b")


def spoken_addresses(text: str) -> str:
    """"jane at gmail dot com" -> "jane@gmail.com"; "example dot com" -> "example.com"."""
    text = _EMAIL.sub(lambda m: f"{m.group(1)}@{m.group(2)}.{m.group(3)}".lower(), text)
    return _DOMAIN.sub(lambda m: f"{m.group(1)}.{m.group(2)}".lower(), text)


def _tidy(text: str) -> str:
    text = re.sub(r"\s+([,.:;?!)\]])", r"\1", text)
    text = re.sub(r"([(\[])\s+", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def smart_format(text: str) -> str:
    """Apply spoken punctuation, address and number formatting to one utterance."""
    if not text:
        return text
    text = spoken_addresses(text)
    text = spoken_punctuation(text)
    text = normalize_numbers(text)
    return _tidy(text)
