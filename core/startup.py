"""
startup.py
"Launch Bepo when I sign in to Windows".

Two mechanisms, chosen at run time:
  * installed with the .exe installer / portable zip / source: the current user's Run key (no admin rights needed);
  * installed from the Microsoft Store (MSIX): the package's `windows.startupTask` (see
    packaging/msix/AppxManifest.xml). Registry writes are virtualised inside a package, so a Run-key entry would
    never fire; Windows owns the on/off state and the user can also flip it in Settings > Apps > Startup.
"""

import ctypes
import logging
import sys
import threading
from ctypes import wintypes
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Bepo"
STARTUP_TASK_ID = "BepoStartup"      # must match <desktop:StartupTask TaskId=...> in the MSIX manifest
_TASK_TIMEOUT_S = 15

_ERROR_INSUFFICIENT_BUFFER = 122     # GetCurrentPackageFullName: "a package name exists, buffer too small"


def is_packaged() -> bool:
    """True when running with MSIX package identity (installed from the Microsoft Store)."""
    try:
        length = wintypes.UINT(0)
        rc = ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(length), None)
    except (AttributeError, OSError):
        return False
    return rc == _ERROR_INSUFFICIENT_BUFFER


def startup_command() -> str:
    """Command line Windows should run at sign-in for this installation."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    main_py = Path(__file__).resolve().parent.parent / "main.py"
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else Path(sys.executable)
    return f'"{interpreter}" "{main_py}"'


# ---- Run key (unpackaged installs) -------------------------------------------------------------------

def _read_value() -> str | None:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            return winreg.QueryValueEx(key, VALUE_NAME)[0]
    except OSError:
        return None


def _set_run_key(enabled: bool) -> bool:
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


# ---- StartupTask (Microsoft Store / MSIX) ------------------------------------------------------------

def _run_in_thread(func):
    """Run `func` on a throw-away thread and return its result (raises what it raised).

    WinRT calls get their own thread so they can never clash with the apartment Qt set up on the GUI thread.
    """
    outcome: dict = {}

    def target():
        try:
            outcome["value"] = func()
        except BaseException as exc:          # re-raised on the caller's thread
            outcome["error"] = exc

    worker = threading.Thread(target=target, name="bepo-startup-task", daemon=True)
    worker.start()
    worker.join(_TASK_TIMEOUT_S)
    if worker.is_alive():
        raise TimeoutError("StartupTask call timed out")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


def _startup_task_enabled() -> bool:
    import asyncio
    from winrt.windows.applicationmodel import StartupTask, StartupTaskState

    async def query():
        task = await StartupTask.get_async(STARTUP_TASK_ID)
        return task.state

    state = asyncio.run(query())
    return state in (StartupTaskState.ENABLED, StartupTaskState.ENABLED_BY_POLICY)


def _set_startup_task(enabled: bool) -> bool:
    import asyncio
    from winrt.windows.applicationmodel import StartupTask, StartupTaskState

    async def apply():
        task = await StartupTask.get_async(STARTUP_TASK_ID)
        if not enabled:
            task.disable()
            return True
        state = await task.request_enable_async()
        # DISABLED_BY_USER / DISABLED_BY_POLICY: only the user (Settings > Apps > Startup) or an admin can undo that
        return state in (StartupTaskState.ENABLED, StartupTaskState.ENABLED_BY_POLICY)

    return asyncio.run(apply())


# ---- Public API --------------------------------------------------------------------------------------

def is_enabled() -> bool:
    if is_packaged():
        try:
            return bool(_run_in_thread(_startup_task_enabled))
        except Exception as exc:
            logging.warning("[Startup] Could not read the startup task state: %s", exc)
            return False
    return _read_value() is not None


def set_enabled(enabled: bool) -> bool:
    """Turn "launch at sign-in" on or off. Returns True on success."""
    if is_packaged():
        try:
            return bool(_run_in_thread(lambda: _set_startup_task(enabled)))
        except Exception as exc:
            logging.warning("[Startup] Could not update the startup task: %s", exc)
            return False
    return _set_run_key(enabled)


def refresh_if_enabled() -> None:
    """If startup is on but points at an old location (app moved/reinstalled), repair it.

    Nothing to repair for a Store install: Windows resolves the package's startup task itself.
    """
    if is_packaged():
        return
    current = _read_value()
    if current is not None and current != startup_command():
        set_enabled(True)
