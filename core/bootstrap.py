"""
bootstrap.py
Very early start-up work, run by main.py *before* the heavy Qt imports:

  1. logging to %LOCALAPPDATA%\\Bepo\\logs
  2. single-instance check (a second launch exits immediately, before loading anything)
  3. start loading the speech model on a background thread

Step 3 is what makes start-up fast: the model (~0.7 s of native work that does not hold the
Python GIL) loads while the main thread is still importing Qt and building the tray/UI.
Pure Python: nothing here may import PySide6.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from core import config as config_module
from core.config import APP_DATA_DIR
from version import __version__

# BEPO_MUTEX_NAME is a developer/test hook so benchmarks and smoke tests can run a second
# instance next to a real one; it is not a user-facing setting.
MUTEX_NAME = os.environ.get("BEPO_MUTEX_NAME") or "Bepo_AI_Voice_Typing_SingleInstance_Mutex"

# Keeps the mutex handle alive for the whole process
instance_mutex = None
started = False


def setup_logging():
    log_dir = APP_DATA_DIR / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "bepo.log"
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] (%(threadName)s) %(message)s",
            handlers=[
                RotatingFileHandler(log_file, maxBytes=1024 * 1024 * 2, backupCount=2, encoding="utf-8"),
                logging.StreamHandler(sys.stdout),
            ],
        )
    except Exception:
        logging.basicConfig(level=logging.INFO)


def acquire_single_instance_lock(name: str = MUTEX_NAME):
    """
    Ensure only one instance of Bepo runs at a time.
    Returns (is_first_instance, mutex_handle). If the check itself fails we let the app
    start rather than refusing to run.
    """
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        ERROR_ALREADY_EXISTS = 183
        handle = kernel32.CreateMutexW(None, False, name)
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            return False, handle
        return True, handle
    except Exception:
        return True, None


def start_preload(config: dict):
    """Begin loading the configured model in the background, if it is already on disk."""
    from core.engine import EngineSettings, Preloader
    from setup import model_downloader

    settings = EngineSettings.from_config(config)
    if not model_downloader.is_model_downloaded(settings.model):
        return None          # first run: the setup screen has to download it first
    preload = Preloader(settings)
    preload.start()
    return preload


def early_start():
    """Run steps 1-3. Exits the process if another instance is already running."""
    global instance_mutex, started
    started = True
    setup_logging()
    logging.info("[Bepo] Starting Bepo %s", __version__)
    is_first, instance_mutex = acquire_single_instance_lock()
    if not is_first:
        logging.info("[Bepo] Another instance of Bepo is already running in the background.")
        sys.exit(0)
    try:
        return start_preload(config_module.load_config())
    except Exception as exc:
        logging.warning("[Bepo] Could not start model preload: %s", exc)
        return None
