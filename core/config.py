"""
config.py
Settings for Bepo: defaults, validation, loading and saving.

Pure Python (no Qt) so it can be used very early during start-up.

Effective settings = DEFAULT_CONFIG < bundled config.json < user config
(%LOCALAPPDATA%\\Bepo\\config.json). Only values that differ from the defaults are
written to the user file, so future default changes still reach existing users.
"""

import json
import logging
import os
import sys
from pathlib import Path

APP_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Bepo"
USER_CONFIG_PATH = APP_DATA_DIR / "config.json"


def _app_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


BUNDLED_CONFIG_PATH = _app_root() / "config.json"

MODEL_CHOICES = ("tiny", "small", "medium")

# How a spoken "new line" is typed. Shift+Enter is safe in chat boxes (Enter would send the message).
LINE_BREAK_KEYS = ("shift_enter", "enter")

# How often Moonshine refreshes the live transcript. Longer = noticeably less CPU while
# speaking, at the cost of sentences being typed a fraction of a second later.
RESPONSIVENESS_SECONDS = {"efficient": 1.0, "fast": 0.5}

DEFAULT_CONFIG = {
    "hotkey_toggle": "ctrl+win",
    "hotkey_ptt": "ctrl+space",
    "continuous_mode": True,
    "filter_filler_words": True,
    "enable_emojis": True,
    "voice_formatting": True,
    "line_break_key": "shift_enter",
    "safety_idle_timeout_seconds": 180.0,
    "auto_stop_on_pause": False,
    "pause_duration_seconds": 2.0,
    "esc_to_finish": True,
    "clipboard_safety_net": False,
    "speech_model": "small",
    "responsiveness": "efficient",
    "microphone": None,
    "custom_vocabulary": [],
}

MAX_VOCABULARY_TERMS = 200
MAX_TERM_LENGTH = 60


def _as_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    return default


def _as_float(value, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:   # NaN
        return default
    return max(low, min(high, number))


def clean_vocabulary(terms) -> list[str]:
    """Normalise custom vocabulary: split on commas/newlines, trim, de-duplicate, cap sizes."""
    if isinstance(terms, str):
        terms = terms.replace(",", "\n").splitlines()
    if not isinstance(terms, (list, tuple)):
        return []
    cleaned: list[str] = []
    seen = set()
    for raw in terms:
        if not isinstance(raw, str):
            continue
        for part in raw.replace(",", "\n").splitlines():
            term = " ".join(part.split())[:MAX_TERM_LENGTH]
            if term and term.lower() not in seen:
                seen.add(term.lower())
                cleaned.append(term)
    return cleaned[:MAX_VOCABULARY_TERMS]


def normalize(config: dict) -> dict:
    """Return a complete, type-safe config; bad or unknown values fall back to defaults."""
    d = DEFAULT_CONFIG
    out = dict(d)

    for key in ("hotkey_toggle", "hotkey_ptt"):
        value = config.get(key, d[key])
        out[key] = value if (value is None or isinstance(value, str)) else d[key]

    for key in ("continuous_mode", "filter_filler_words", "enable_emojis", "voice_formatting",
                "auto_stop_on_pause", "esc_to_finish", "clipboard_safety_net"):
        out[key] = _as_bool(config.get(key, d[key]), d[key])

    out["safety_idle_timeout_seconds"] = _as_float(
        config.get("safety_idle_timeout_seconds"), d["safety_idle_timeout_seconds"], 10.0, 7200.0)
    out["pause_duration_seconds"] = _as_float(
        config.get("pause_duration_seconds"), d["pause_duration_seconds"], 0.5, 10.0)

    model = config.get("speech_model", d["speech_model"])
    out["speech_model"] = model if model in MODEL_CHOICES else d["speech_model"]

    resp = config.get("responsiveness", d["responsiveness"])
    out["responsiveness"] = resp if resp in RESPONSIVENESS_SECONDS else d["responsiveness"]

    key = config.get("line_break_key", d["line_break_key"])
    out["line_break_key"] = key if key in LINE_BREAK_KEYS else d["line_break_key"]

    mic = config.get("microphone")
    out["microphone"] = mic.strip() if isinstance(mic, str) and mic.strip() else None

    out["custom_vocabulary"] = clean_vocabulary(config.get("custom_vocabulary", []))
    return out


def update_interval(config: dict) -> float:
    return RESPONSIVENESS_SECONDS[config.get("responsiveness", DEFAULT_CONFIG["responsiveness"])]


def _read_json(path: Path) -> dict:
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
            logging.warning("Ignoring %s: expected a JSON object", path)
        except Exception as exc:
            logging.warning("Could not parse %s: %s", path, exc)
    return {}


def base_config() -> dict:
    """Defaults overlaid with the shipped config.json (i.e. everything except user overrides)."""
    merged = dict(DEFAULT_CONFIG)
    merged.update(_read_json(BUNDLED_CONFIG_PATH))
    return normalize(merged)


def load_config() -> dict:
    merged = dict(DEFAULT_CONFIG)
    merged.update(_read_json(BUNDLED_CONFIG_PATH))
    merged.update(_read_json(USER_CONFIG_PATH))
    return normalize(merged)


def save_user_config(config: dict, path: Path | None = None) -> dict:
    """Persist `config`, keeping only values that differ from the defaults. Returns what was written."""
    path = path or USER_CONFIG_PATH
    config = normalize(config)
    base = base_config()
    changes = {k: v for k, v in config.items() if v != base.get(k)}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(changes, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)
    return changes
