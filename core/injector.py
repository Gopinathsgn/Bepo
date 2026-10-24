"""
injector.py
Injects text at the current cursor position in the active window.

Strategy:
  1. Release any modifier keys still physically held (Ctrl, Win, Alt, Shift, Space)
  2. Win32 SendInput with KEYEVENTF_UNICODE (proper 64-bit 40-byte INPUT structure)
  3. Fallback: clipboard + simulated Ctrl+V, restoring the user's previous clipboard

Privacy note: by default Bepo never touches the clipboard unless SendInput fails.
The optional "clipboard safety net" (config: clipboard_safety_net) additionally keeps
the whole dictated session on the clipboard. Only character counts are ever logged.
"""

import ctypes
import logging
import time
import queue
import threading
import pyperclip


# Opt-in: also copy the accumulated dictation to the clipboard (see configure()).
_clipboard_safety_net = False


def configure(clipboard_safety_net: bool = False) -> None:
    """Apply user settings. Called once by the app controller at start-up."""
    global _clipboard_safety_net
    _clipboard_safety_net = bool(clipboard_safety_net)


# ---------------------------------------------------------------------- #
# Windows Win64 INPUT structures for SendInput (40 bytes on x64)         #
# ---------------------------------------------------------------------- #

INPUT_KEYBOARD    = 1
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP   = 0x0002
VK_CONTROL        = 0x11
VK_V              = 0x56
VK_BACK           = 0x08
VK_SPACE          = 0x20

# Keys that would turn typed characters into shortcuts (Ctrl+x, Win+x, ...) if they were
# still physically held when text is injected. L/R variants of each modifier + Space.
_KEYS_TO_RELEASE = (
    0xA2, 0xA3,   # VK_LCONTROL, VK_RCONTROL
    0xA0, 0xA1,   # VK_LSHIFT,   VK_RSHIFT
    0xA4, 0xA5,   # VK_LMENU,    VK_RMENU (Alt)
    0x5B, 0x5C,   # VK_LWIN,     VK_RWIN
    VK_SPACE,
)

ULONG_PTR = ctypes.c_ulonglong


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx",          ctypes.c_long),
        ("dy",          ctypes.c_long),
        ("mouseData",   ctypes.c_ulong),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk",         ctypes.c_ushort),
        ("wScan",       ctypes.c_ushort),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg",    ctypes.c_ulong),
        ("wParamL", ctypes.c_ushort),
        ("wParamH", ctypes.c_ushort),
    ]


class _INPUTunion(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type",  ctypes.c_ulong),
        ("union", _INPUTunion),
    ]


def _send_unicode_string(text: str) -> bool:
    """Send text via SendInput KEYEVENTF_UNICODE events with UTF-16 surrogate pair support."""
    user32 = ctypes.windll.user32
    inputs = []

    # Encode as UTF-16LE to safely handle characters above 0xFFFF (such as emojis)
    raw_bytes = text.encode("utf-16-le")
    code_units = [
        int.from_bytes(raw_bytes[i:i + 2], "little")
        for i in range(0, len(raw_bytes), 2)
    ]

    for unit in code_units:
        # Key down
        ki_down = KEYBDINPUT(
            wVk=0, wScan=unit, dwFlags=KEYEVENTF_UNICODE,
            time=0, dwExtraInfo=0
        )
        inputs.append(INPUT(type=INPUT_KEYBOARD, union=_INPUTunion(ki=ki_down)))

        # Key up
        ki_up = KEYBDINPUT(
            wVk=0, wScan=unit, dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
            time=0, dwExtraInfo=0
        )
        inputs.append(INPUT(type=INPUT_KEYBOARD, union=_INPUTunion(ki=ki_up)))

    arr = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    return sent == len(inputs)


def _release_held_keys() -> None:
    """Send key-up events for modifiers (and Space) that are still physically held."""
    user32 = ctypes.windll.user32
    held = [vk for vk in _KEYS_TO_RELEASE if user32.GetAsyncKeyState(vk) & 0x8000]
    if not held:
        return
    inputs = []
    for vk in held:
        ki_up = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=0)
        inputs.append(INPUT(type=INPUT_KEYBOARD, union=_INPUTunion(ki=ki_up)))
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def _clipboard_inject(text: str, restore_text: str | None) -> bool:
    """
    Fallback: copy text to the clipboard and simulate Ctrl+V.
    Afterwards the clipboard is put back: to `restore_text` if given (safety-net mode),
    otherwise to whatever text the user had on it before (text formats only).
    """
    user32 = ctypes.windll.user32
    previous = None
    if restore_text is None:
        try:
            previous = pyperclip.paste()
        except Exception:
            previous = None

    try:
        pyperclip.copy(text)
        time.sleep(0.03)

        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_V, 0, 0, 0)
        user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
        user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
        # Give the target app time to read the clipboard before we restore it
        time.sleep(0.15)
    except Exception as exc:
        logging.warning("[Injector] Clipboard paste failed: %s", exc)
        return False
    finally:
        try:
            if restore_text is not None:
                pyperclip.copy(restore_text)
            elif previous is not None:
                pyperclip.copy(previous)
        except Exception:
            pass
    return True


def inject_text(text: str, full_session_text: str | None = None) -> bool:
    """
    Inject `text` at the current cursor position in the active window.

    The clipboard is left untouched unless SendInput fails (the paste fallback then
    restores it) or the opt-in clipboard safety net is enabled, in which case
    `full_session_text` (or `text`) is also copied so the whole dictation can be
    pasted with Ctrl+V.
    """
    if not text:
        return True

    session_text = full_session_text if full_session_text else text

    if _clipboard_safety_net:
        try:
            pyperclip.copy(session_text)
        except Exception as exc:
            logging.warning("[Injector] Clipboard copy error: %s", exc)

    # Wait for physical release of Space if held (e.g. from Ctrl+Space PTT)
    # This prevents Windows hardware key-repeat from spamming spaces into the active text box
    user32 = ctypes.windll.user32
    for _ in range(25):  # up to 250ms
        if not (user32.GetAsyncKeyState(VK_SPACE) & 0x8000):
            break
        time.sleep(0.01)

    # Release modifier keys that might still be held from the hotkey
    try:
        _release_held_keys()
    except Exception as exc:
        logging.warning("[Injector] Could not release held keys: %s", exc)

    # Brief delay to allow Windows key-state queue to settle
    time.sleep(0.02)

    # 1. SendInput (Unicode with UTF-16 surrogates)
    try:
        if _send_unicode_string(text):
            logging.info("[Injector] Injected %d characters via SendInput", len(text))
            return True
    except Exception as exc:
        logging.warning("[Injector] SendInput exception: %s", exc)

    # 2. Fallback to clipboard Ctrl+V simulation
    if _clipboard_inject(text, restore_text=session_text if _clipboard_safety_net else None):
        logging.info("[Injector] Injected %d characters via clipboard paste", len(text))
        return True

    logging.error("[Injector] Could not inject %d characters", len(text))
    return False


def delete_backspaces(count: int, full_session_text: str | None = None) -> bool:
    """
    Sends `count` Backspace keystrokes at high speed via SendInput.
    With the opt-in clipboard safety net, also updates the clipboard with `full_session_text`.
    """
    if count <= 0:
        return True

    if _clipboard_safety_net and full_session_text is not None:
        try:
            pyperclip.copy(full_session_text)
        except Exception:
            pass

    user32 = ctypes.windll.user32
    chunk_size = 50
    remaining = count
    while remaining > 0:
        batch = min(remaining, chunk_size)
        inputs = []
        for _ in range(batch):
            ki_down = KEYBDINPUT(wVk=VK_BACK, wScan=0, dwFlags=0, time=0, dwExtraInfo=0)
            inputs.append(INPUT(type=INPUT_KEYBOARD, union=_INPUTunion(ki=ki_down)))
            ki_up = KEYBDINPUT(wVk=VK_BACK, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=0)
            inputs.append(INPUT(type=INPUT_KEYBOARD, union=_INPUTunion(ki=ki_up)))
        arr = (INPUT * len(inputs))(*inputs)
        user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
        remaining -= batch
        if remaining > 0:
            time.sleep(0.01)
    logging.info("[Injector] Deleted %d characters via SendInput backspaces", count)
    return True


# ---------------------------------------------------------------------- #
# Sequential injection queue                                              #
# Guarantees multiple streamed sentences never interleave keystrokes     #
# ---------------------------------------------------------------------- #

_inject_queue = queue.Queue()
_worker_thread = None
_worker_lock = threading.Lock()


def _injection_worker():
    while True:
        item = _inject_queue.get()
        if item is None:
            break
        action, payload, session_text = item
        try:
            if action == "inject":
                inject_text(payload, session_text)
            elif action == "delete":
                delete_backspaces(payload, session_text)
        except Exception as exc:
            logging.error("[Injector] Worker error: %s", exc)
        finally:
            _inject_queue.task_done()


def enqueue_injection(text: str, full_session_text: str | None = None):
    """Safely queue text for sequential injection without blocking GUI threads."""
    global _worker_thread
    with _worker_lock:
        if _worker_thread is None or not _worker_thread.is_alive():
            _worker_thread = threading.Thread(
                target=_injection_worker, daemon=True, name="SequentialInjector"
            )
            _worker_thread.start()
    _inject_queue.put(("inject", text, full_session_text))


def enqueue_deletion(count: int, full_session_text: str | None = None):
    """Safely queue deletion for sequential execution without blocking GUI threads."""
    global _worker_thread
    with _worker_lock:
        if _worker_thread is None or not _worker_thread.is_alive():
            _worker_thread = threading.Thread(
                target=_injection_worker, daemon=True, name="SequentialInjector"
            )
            _worker_thread.start()
    _inject_queue.put(("delete", count, full_session_text))

