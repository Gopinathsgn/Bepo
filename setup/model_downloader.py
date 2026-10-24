"""
model_downloader.py
Locating, downloading and bundling the Moonshine speech models.

Everything that only needs to *find* a model is plain Python (no moonshine_voice import) so
start-up can check for the model without loading the speech engine's Python package first.
The moonshine_voice package is imported lazily, only when something is actually downloaded.
"""

import os
import sys
import shutil
import functools
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

LANGUAGE = "en"


@dataclass(frozen=True)
class ModelInfo:
    key: str
    label: str
    arch_name: str        # name of the moonshine_voice.ModelArch member
    folder: str           # folder name used by the Moonshine CDN / our bundle
    size_mb: int          # approximate download size
    description: str


MODELS: dict[str, ModelInfo] = {
    "tiny": ModelInfo("tiny", "Tiny", "TINY_STREAMING", "tiny-streaming-en", 45,
                      "Lightest: least RAM and CPU, fastest to load."),
    "small": ModelInfo("small", "Small (default)", "SMALL_STREAMING", "small-streaming-en", 142,
                       "Balanced accuracy and resource use."),
    "medium": ModelInfo("medium", "Medium", "MEDIUM_STREAMING", "medium-streaming-en", 269,
                        "Most capable on difficult audio; about twice the RAM of Small."),
}
DEFAULT_MODEL = "small"

# Files that must all be present for a model directory to be considered complete.
# (Presence of just *some* .ort file is not enough: an interrupted download would
# otherwise be mistaken for a usable model.)
REQUIRED_MODEL_FILES = (
    "adapter.ort",
    "cross_kv.ort",
    "decoder_kv.ort",
    "encoder.ort",
    "frontend.model.ort",
    "frontend.weights.ort",
    "streaming_config.json",
    "tokenizer.bin",
)


def model_arch(key: str):
    """The moonshine_voice.ModelArch for a model key (imports moonshine_voice)."""
    from moonshine_voice import ModelArch
    return getattr(ModelArch, MODELS[key].arch_name)


def get_model_size_mb(key: str = DEFAULT_MODEL) -> int:
    """Approximate download size in MB (shown in the UI)."""
    return MODELS[key].size_mb


def _is_complete_model_dir(path: Path) -> bool:
    """True if `path` contains every required model file (non-empty)."""
    try:
        return path.is_dir() and all(
            (path / name).is_file() and (path / name).stat().st_size > 0
            for name in REQUIRED_MODEL_FILES
        )
    except OSError:
        return False


def _find_complete_model_dir(base: Path, max_depth: int = 3) -> Optional[Path]:
    """Search `base` (bounded depth) for a directory holding a complete model."""
    if not base.is_dir():
        return None
    if _is_complete_model_dir(base):
        return base
    if max_depth <= 0:
        return None
    try:
        children = sorted((p for p in base.iterdir() if p.is_dir()), reverse=True)
    except OSError:
        return None
    for child in children:
        found = _find_complete_model_dir(child, max_depth - 1)
        if found is not None:
            return found
    return None


def get_model_cache_path() -> Path:
    """The moonshine_voice cache directory (same location the library itself uses)."""
    override = os.environ.get("MOONSHINE_VOICE_CACHE")
    if override:
        return Path(override)
    from platformdirs import user_cache_dir
    return Path(user_cache_dir("moonshine_voice"))


def _bundle_roots() -> list[Path]:
    """Dedicated `models` folders a release build may ship with (never the whole app tree)."""
    roots = []
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        roots.append(Path(sys._MEIPASS) / "models")
    roots.append(Path(sys.executable).parent / "models")
    roots.append(Path(__file__).resolve().parent.parent / "models")
    return roots


@functools.lru_cache(maxsize=None)
def get_bundled_model_path(key: str = DEFAULT_MODEL) -> Optional[Path]:
    """
    Pre-bundled copy of a model, if this build ships one. Release builds bundle the default
    model in `models/<folder>/`; older builds used `models/<version>/` (accepted for the
    default model only). Cached: bundled files never change while the app runs.
    """
    folder = MODELS[key].folder
    for root in _bundle_roots():
        found = _find_complete_model_dir(root / folder, max_depth=1)
        if found is not None:
            return found
        if key == DEFAULT_MODEL:
            legacy = _find_complete_model_dir(root, max_depth=1)
            if legacy is not None:
                return legacy
    return None


def _cache_model_path(key: str) -> Optional[Path]:
    """Newest complete copy of a model in the moonshine_voice cache."""
    base = get_model_cache_path() / "download.moonshine.ai" / "model" / MODELS[key].folder
    return _find_complete_model_dir(base, max_depth=1)


def find_installed_model(key: str = DEFAULT_MODEL) -> Optional[Path]:
    """Directory holding a complete copy of the model (bundled or cached), or None."""
    return get_bundled_model_path(key) or _cache_model_path(key)


def is_model_downloaded(key: str = DEFAULT_MODEL) -> bool:
    return find_installed_model(key) is not None


def download_model(on_progress: Callable[[float, str], None], key: str = DEFAULT_MODEL):
    """
    Download a Moonshine streaming model into the moonshine_voice cache.

    Args:
        on_progress: Called with (fraction 0..1, current_filename).
                     Supplying this silences moonshine's own tqdm bars.
    """
    from moonshine_voice.download import get_model_for_language
    return get_model_for_language(
        wanted_language=LANGUAGE,
        wanted_model_arch=model_arch(key),
        on_progress=on_progress,
    )


def export_model_for_bundling(target_dir: Path, key: str = DEFAULT_MODEL) -> bool:
    """
    Copy a model from the local cache into target_dir/<folder> for packaging into release builds.
    If the model is not cached, downloads it first.

    Returns True only if a complete model (all required files) ended up in target_dir.
    """
    if _cache_model_path(key) is None:
        print("[Build] Model not found in cache. Downloading model now...")
        download_model(lambda frac, fn: print(f"  Downloading {fn}: {int(frac * 100)}%"), key)

    source = _cache_model_path(key)
    if source is None:
        return False

    dest_dir = target_dir / MODELS[key].folder
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for file_path in source.iterdir():
        if file_path.is_file():
            shutil.copy2(file_path, dest_dir / file_path.name)
            copied += 1
    print(f"[Build] Copied {copied} model files to {dest_dir}")
    return _is_complete_model_dir(dest_dir)


if __name__ == "__main__":
    # Usage: python -m setup.model_downloader [target_dir]
    # Downloads (if needed) and copies the default model into target_dir; exits non-zero on
    # failure so build scripts can't silently ship an installer without the model.
    _target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dist/Bepo/models")
    sys.exit(0 if export_model_for_bundling(_target) else 1)
