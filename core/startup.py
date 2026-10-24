"""
startup.py
"Launch Bepo when I sign in to Windows", via the current user's Run key (no admin rights needed).
"""

import logging
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Bepo"


def startup_command() -> str:
    """Command line Windows should run at sign-in for this installation."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    main_py = Path(__file__).resolve().parent.parent / "main.py"
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else Path(sys.executable)
    return f'"{interpreter}" "{main_py}"'


def _read_value() -> str | None:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            return winreg.QueryValueEx(key, VALUE_NAME)[0]
    except OSError:
        return None


def is_enabled() -> bool:
    return _read_value() is not None


def set_enabled(enabled: bool) -> bool:
    """Add or remove the startup entry. Returns True on success."""
    import winreg
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            if enabled:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, startup_command())
            else:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError as exc:
        logging.warning("[Startup] Could not update the startup entry: %s", exc)
        return False


def refresh_if_enabled() -> None:
    """If startup is on but points at an old location (app moved/reinstalled), repair it."""
    current = _read_value()
    if current is not None and current != startup_command():
        set_enabled(True)
