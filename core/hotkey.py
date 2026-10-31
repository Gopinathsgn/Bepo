"""
hotkey.py
Global hotkey manager for Bepo.

Default Hotkeys (configurable via "hotkey_toggle" / "hotkey_ptt" in config.json):
  1. Ctrl + Win   — Toggle mode (Tap to start, tap again to finish)
  2. Ctrl + Space — Push-to-Talk mode (Hold to speak, release to finish)
  3. Alt + Win + Z — Undo the last dictation ("hotkey_undo")

Implementation:
  - Win32 RegisterHotKey with MOD_NOREPEAT.
  - Dedicated background thread with blocking GetMessageW (0% CPU, no polling).
  - GetAsyncKeyState watcher for instantaneous Push-to-Talk release detection.
  - Signal for thread-safe Qt main thread dispatch.
  - Hotkeys that could not be registered (e.g. already owned by another app) are
    reported through the `registration_issue` signal instead of failing silently.
"""

import time
import logging
import threading
import ctypes
import ctypes.wintypes
from dataclasses import dataclass
from PySide6.QtCore import QObject, Signal


# Windows constants
MOD_ALT      = 0x0001
MOD_CONTROL  = 0x0002
MOD_SHIFT    = 0x0004
MOD_WIN      = 0x0008
MOD_NOREPEAT = 0x4000

VK_SHIFT     = 0x10
VK_CONTROL   = 0x11
VK_MENU      = 0x12     # Alt
VK_SPACE     = 0x20
VK_ESCAPE    = 0x1B
VK_LWIN      = 0x5B
VK_RWIN      = 0x5C

WM_HOTKEY    = 0x0312
WM_QUIT      = 0x0012

HOTKEY_ID_TOGGLE_L = 1
HOTKEY_ID_TOGGLE_R = 2
HOTKEY_ID_PTT      = 3
HOTKEY_ID_PTT_R    = 4
HOTKEY_ID_UNDO_L   = 5
HOTKEY_ID_UNDO_R   = 6

DEFAULT_TOGGLE = "ctrl+win"
DEFAULT_PTT    = "ctrl+space"
# Not Ctrl+Win+Z: Ctrl+Win is the toggle shortcut and fires the moment both keys are down, before Z.
DEFAULT_UNDO   = "alt+win+z"
_KEEP = object()   # reconfigure(): leave the undo shortcut as it is

_MODIFIER_NAMES = {
    "ctrl": "ctrl", "control": "ctrl",
    "alt": "alt",
    "shift": "shift",
    "win": "win", "windows": "win", "super": "win",
}
_NAMED_KEYS = {"space": VK_SPACE, "enter": 0x0D, "tab": 0x09}


@dataclass(frozen=True)
class HotkeySpec:
    """A parsed hotkey, ready for RegisterHotKey and for held-key polling."""
    text: str                              # normalised display text, e.g. "ctrl+space"
    mods: int                              # MOD_* flags for RegisterHotKey
    vks: tuple[int, ...]                   # virtual keys to register (Win key = L + R)
    held: tuple[tuple[int, ...], ...]      # groups; each needs one key down while held


def parse_hotkey(spec: str) -> HotkeySpec | None:
    """
    Parse strings like "ctrl+win", "ctrl+space", "ctrl+alt+d", "f9".
    Returns None if the text is not a usable hotkey.
    """
    if not isinstance(spec, str):
        return None
    tokens = [t.strip().lower() for t in spec.split("+") if t.strip()]
    if not tokens:
        return None

    *mod_tokens, key_token = tokens
    mods = 0
    held: list[tuple[int, ...]] = []
    names: list[str] = []
    for tok in mod_tokens:
        name = _MODIFIER_NAMES.get(tok)
        if name is None or name in names:
            return None
        names.append(name)

    for name in names:
        if name == "ctrl":
            mods |= MOD_CONTROL; held.append((VK_CONTROL,))
        elif name == "alt":
            mods |= MOD_ALT; held.append((VK_MENU,))
        elif name == "shift":
            mods |= MOD_SHIFT; held.append((VK_SHIFT,))
        elif name == "win":
            mods |= MOD_WIN; held.append((VK_LWIN, VK_RWIN))

    key_name = _MODIFIER_NAMES.get(key_token)
    if key_name == "win":
        # "ctrl+win": the Win key itself is the trigger key, with Win also a modifier.
        if "win" in names:
            return None
        mods |= MOD_WIN
        vks: tuple[int, ...] = (VK_LWIN, VK_RWIN)
        held.append((VK_LWIN, VK_RWIN))
    elif key_name is not None:
        return None   # ends in a bare modifier such as "ctrl+alt"
    elif key_token in _NAMED_KEYS:
        vks = (_NAMED_KEYS[key_token],)
        held.append(vks)
    elif len(key_token) == 1 and key_token.isascii() and key_token.isalnum():
        vks = (ord(key_token.upper()),)
        held.append(vks)
    elif key_token.startswith("f") and key_token[1:].isdigit() and 1 <= int(key_token[1:]) <= 24:
        vks = (0x70 + int(key_token[1:]) - 1,)
        held.append(vks)
    else:
        return None

    return HotkeySpec(text="+".join(names + [key_token]), mods=mods, vks=vks, held=tuple(held))


class HotkeyManager(QObject):
    """
    Manages global shortcuts for Bepo:
      - toggle_activated: emitted on the toggle hotkey (default Ctrl+Win)
      - ptt_pressed:      emitted on the push-to-talk hotkey down (default Ctrl+Space)
      - ptt_released:     emitted when the push-to-talk combination is released
      - esc_pressed:      emitted when Esc is pressed while recording
      - undo_activated:   emitted on the undo shortcut (default Alt+Win+Z)
      - registration_issue: human-readable problem (bad config, shortcut already taken)
    """

    toggle_activated   = Signal()
    ptt_pressed        = Signal()
    ptt_released       = Signal()
    esc_pressed        = Signal()
    undo_activated     = Signal()
    registration_issue = Signal(str)
    activated          = toggle_activated   # backward compatibility alias

    def __init__(self, parent=None, toggle: str | None = DEFAULT_TOGGLE,
                 ptt: str | None = DEFAULT_PTT, undo: str | None = DEFAULT_UNDO):
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready_event = threading.Event()
        self._ptt_watching = False
        self._esc_watching = False
        self._issues: list[str] = []
        self._registered: list[str] = []
        self._set_specs(toggle, ptt, undo)

    def _set_specs(self, toggle, ptt, undo):
        self._toggle = self._resolve(toggle, DEFAULT_TOGGLE, "toggle")
        self._ptt = self._resolve(ptt, DEFAULT_PTT, "push-to-talk")
        if self._toggle and self._ptt and self._toggle.text == self._ptt.text:
            self._issues.append(
                f"Toggle and push-to-talk both use '{self._ptt.text}'; push-to-talk is disabled."
            )
            self._ptt = None
        self._undo = self._resolve(undo, DEFAULT_UNDO, "undo")
        taken = {s.text for s in (self._toggle, self._ptt) if s}
        if self._undo and self._undo.text in taken:
            self._issues.append(f"The undo shortcut duplicates '{self._undo.text}'; undo is disabled.")
            self._undo = None

    def _resolve(self, value, default: str, label: str) -> HotkeySpec | None:
        """Parse a configured hotkey. Empty/None disables it; invalid falls back to default."""
        if value is None or (isinstance(value, str) and not value.strip()):
            return None   # explicitly disabled
        parsed = parse_hotkey(value)
        if parsed is None:
            self._issues.append(
                f"Invalid {label} hotkey {value!r} in config; using '{default}' instead."
            )
            parsed = parse_hotkey(default)
        return parsed

    @staticmethod
    def _pretty(spec: "HotkeySpec | None") -> str:
        return "+".join(t.capitalize() for t in spec.text.split("+")) if spec else ""

    @property
    def toggle_label(self) -> str:
        """Display text of the toggle hotkey (e.g. "Ctrl+Win"), or "" if disabled."""
        return self._pretty(self._toggle)

    @property
    def ptt_label(self) -> str:
        """Display text of the push-to-talk hotkey (e.g. "Ctrl+Space"), or "" if disabled."""
        return self._pretty(self._ptt)

    @property
    def undo_label(self) -> str:
        """Display text of the undo shortcut (e.g. "Alt+Win+Z"), or "" if disabled."""
        return self._pretty(self._undo)

    def start(self):
        """Start hotkey listener on dedicated background message pump."""
        self._registered = []
        self._ready_event.clear()
        self._thread = threading.Thread(
            target=self._register_hotkey_loop, daemon=True, name="HotkeyListener"
        )
        self._thread.start()
        self._ready_event.wait(timeout=1.0)

        if self._registered:
            logging.info("[Hotkey] Registered: %s", ", ".join(self._registered))
        else:
            logging.warning("[Hotkey] No shortcuts registered")
        issues, self._issues = self._issues, []
        for issue in issues:
            logging.warning("[Hotkey] %s", issue)
            self.registration_issue.emit(issue)

    def stop(self):
        """Cleanly unregister and terminate background pump (waits until it has exited)."""
        self.stop_esc_watcher()
        thread, thread_id = self._thread, self._thread_id
        self._thread_id = None
        if thread_id is not None:
            try:
                ctypes.windll.user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0)
            except Exception:
                pass
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        self._thread = None

    def suspend(self):
        """Temporarily release the shortcuts (e.g. while the user records a new one)."""
        self.stop()

    def resume(self):
        """Re-register the current shortcuts after suspend()."""
        if self._thread is None:
            self.start()

    def reconfigure(self, toggle: str | None, ptt: str | None, undo=_KEEP):
        """Apply new shortcuts at runtime (problems are reported via registration_issue)."""
        self.stop()
        if undo is _KEEP:
            undo = self._undo.text if self._undo else None
        self._set_specs(toggle, ptt, undo)
        self.start()

    def start_esc_watcher(self):
        """Watch for the Escape key while recording is active."""
        if self._esc_watching:
            return
        self._esc_watching = True
        threading.Thread(target=self._watch_esc, daemon=True, name="EscWatcher").start()

    def stop_esc_watcher(self):
        """Stop watching for the Escape key."""
        self._esc_watching = False

    def _watch_esc(self):
        """Watch GetAsyncKeyState until Esc is pressed."""
        user32 = ctypes.windll.user32
        time.sleep(0.04)
        while self._esc_watching:
            time.sleep(0.015)
            if user32.GetAsyncKeyState(VK_ESCAPE) & 0x8000:
                self._esc_watching = False
                self.esc_pressed.emit()
                break

    # ------------------------------------------------------------------ #
    # Win32 RegisterHotKey loop                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _register(hotkey_id: int, spec: HotkeySpec, vk: int) -> bool:
        return bool(ctypes.windll.user32.RegisterHotKey(
            None, hotkey_id, spec.mods | MOD_NOREPEAT, vk
        ))

    def _register_hotkey_loop(self):
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        registered_ids: list[int] = []

        try:
            self._thread_id = kernel32.GetCurrentThreadId()

            if self._toggle is not None:
                results = [
                    self._register(HOTKEY_ID_TOGGLE_L + i, self._toggle, vk)
                    for i, vk in enumerate(self._toggle.vks)
                ]
                registered_ids += [HOTKEY_ID_TOGGLE_L + i for i, ok in enumerate(results) if ok]
                if any(results):
                    self._registered.append(f"{self._toggle.text} (toggle)")
                else:
                    self._issues.append(
                        f"Could not register the toggle shortcut '{self._toggle.text}' - "
                        "another app may be using it. Change \"hotkey_toggle\" in the settings file "
                        "(tray menu > Open Settings File) or start dictation from the tray menu."
                    )

            if self._ptt is not None:
                results = [
                    self._register(HOTKEY_ID_PTT + i, self._ptt, vk)
                    for i, vk in enumerate(self._ptt.vks)
                ]
                registered_ids += [HOTKEY_ID_PTT + i for i, ok in enumerate(results) if ok]
                if any(results):
                    self._registered.append(f"{self._ptt.text} (push-to-talk)")
                else:
                    self._issues.append(
                        f"Could not register the push-to-talk shortcut '{self._ptt.text}' - "
                        "another app may be using it. Change \"hotkey_ptt\" in the settings file "
                        "(tray menu > Open Settings File)."
                    )

            if self._undo is not None:
                results = [
                    self._register(HOTKEY_ID_UNDO_L + i, self._undo, vk)
                    for i, vk in enumerate(self._undo.vks)
                ]
                registered_ids += [HOTKEY_ID_UNDO_L + i for i, ok in enumerate(results) if ok]
                if any(results):
                    self._registered.append(f"{self._undo.text} (undo)")
                else:
                    self._issues.append(
                        f"Could not register the undo shortcut '{self._undo.text}' - "
                        "another app may be using it. Change it in Settings."
                    )
        finally:
            self._ready_event.set()

        if not registered_ids:
            return

        msg = ctypes.wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                hotkey_id = msg.wParam
                if hotkey_id in (HOTKEY_ID_TOGGLE_L, HOTKEY_ID_TOGGLE_R):
                    self.toggle_activated.emit()
                elif hotkey_id in (HOTKEY_ID_PTT, HOTKEY_ID_PTT_R):
                    self._on_ptt_pressed()
                elif hotkey_id in (HOTKEY_ID_UNDO_L, HOTKEY_ID_UNDO_R):
                    self.undo_activated.emit()

        for hotkey_id in registered_ids:
            user32.UnregisterHotKey(None, hotkey_id)

    def _on_ptt_pressed(self):
        self.ptt_pressed.emit()
        if not self._ptt_watching:
            self._ptt_watching = True
            threading.Thread(
                target=self._watch_ptt_release, daemon=True, name="PTTWatcher"
            ).start()

    def _watch_ptt_release(self):
        """Watch GetAsyncKeyState until any key of the push-to-talk combination is released."""
        user32 = ctypes.windll.user32
        groups = self._ptt.held if self._ptt is not None else ((VK_CONTROL,), (VK_SPACE,))
        # Small settling delay
        time.sleep(0.05)

        while True:
            time.sleep(0.015)
            all_down = all(
                any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in group)
                for group in groups
            )
            if not all_down:
                break

        self._ptt_watching = False
        self.ptt_released.emit()
