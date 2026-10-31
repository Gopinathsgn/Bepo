"""
main.py
Bepo — Blazing fast voice typing for Windows.
Wires together: setup screen, system tray, settings, hotkey, transcriber, pill, injector.
"""

import re
import sys
import logging
from collections import deque
from pathlib import Path

from core import bootstrap

# Start-up speed: when run as the program, do the cheap pure-Python work (logging, single
# instance check, starting the speech model loading in the background) *before* the heavy Qt
# imports below, so the model loads in parallel with the UI being built.
_PRELOAD = bootstrap.early_start() if __name__ == "__main__" else None

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor
from PySide6.QtCore import Qt, QObject, Slot, QTimer, QRectF
from PySide6.QtSvg import QSvgRenderer

from core import config as app_config
from core import memory, startup
from core.engine import EngineSettings
from setup.model_downloader import is_model_downloaded
from core.transcriber import TranscriberThread
from core.injector import (
    configure as configure_injector, enqueue_injection, enqueue_deletion, foreground_window,
)
from core.cleaner import clean_transcript
from core.commands import CommandType, parse_voice_command
from core.formatting import BULLETS, NUMBERED, FormatCommand, ListState, parse_format_command
from core.hotkey import HotkeyManager, DEFAULT_TOGGLE, DEFAULT_PTT
from ui.pill import PillWindow
from ui.setup_screen import SetupScreen
from ui.settings_dialog import SettingsDialog

# Seconds of idleness before Bepo hands its idle memory back to Windows
IDLE_TRIM_DELAY_MS = 15_000

# Consecutive empty dictations before Bepo suggests checking the microphone
NO_SPEECH_HINT_AFTER = 2
# Dictations remembered for the tray's "Recent dictations" menu (memory only, opt-in)
HISTORY_SIZE = 10


def _load_config() -> dict:
    """Defaults < bundled config.json < user config (see core/config.py)."""
    return app_config.load_config()


# ------------------------------------------------------------------ #
# Audio cue feedback (earcons)                                         #
# ------------------------------------------------------------------ #

def _play_earcon(cue: str):
    """Play subtle Windows audio cue for hands-free feedback."""
    try:
        import winsound
        if cue == "start":
            winsound.MessageBeep(winsound.MB_OK)
        elif cue == "done":
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        elif cue == "delete":
            winsound.MessageBeep(winsound.MB_ICONHAND)
    except Exception:
        pass


# ------------------------------------------------------------------ #
# Tray icon helper                                                     #
# ------------------------------------------------------------------ #

def _is_light_taskbar() -> bool:
    """Detect if Windows taskbar is running in light mode."""
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            val, _ = winreg.QueryValueEx(key, "SystemUsesLightTheme")
            return val == 1
    except Exception:
        return False


def _make_tray_icon(active: bool = False) -> QIcon:
    """
    Generate native Windows silhouette system tray icon (Option A):
    - Idle: High-contrast crisp bear silhouette on transparent background (full size).
    - Active: Glowing coral red bear silhouette.
    """
    icon = QIcon()
    if active:
        fill_color = "#FF453A"
    else:
        fill_color = "#1E293B" if _is_light_taskbar() else "#FFFFFF"

    # Render vector bear silhouette
    svg_path = Path(__file__).parent / "assets" / "logo.svg"
    renderer = None
    if svg_path.exists():
        try:
            with open(svg_path, "r", encoding="utf-8") as f:
                content = f.read()
            import re
            m = re.search(r'd="([^"]+)"', content)
            if m:
                path_d = m.group(1)
                svg_data = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="42 85 128 128"><path fill="{fill_color}" d="{path_d}" /></svg>'
                renderer = QSvgRenderer(svg_data.encode("utf-8"))
        except Exception:
            renderer = None

    for size in (16, 20, 24, 32, 48):
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        if renderer and renderer.isValid():
            renderer.render(p, QRectF(0, 0, size, size))
        else:
            color = QColor(255, 69, 58) if active else QColor(255, 255, 255)
            p.setBrush(color)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(1, 1, size - 2, size - 2)

        p.end()
        icon.addPixmap(pix)

    return icon


ICON_IDLE    = None
ICON_ACTIVE  = None


# ------------------------------------------------------------------ #
# App controller                                                       #
# ------------------------------------------------------------------ #

class BepoApp(QObject):
    """
    Central controller. Owns all major components and coordinates them.
    All signal connections happen here — no cross-module coupling.
    """

    def __init__(self, app: QApplication, preload=None):
        super().__init__(app)
        global ICON_IDLE, ICON_ACTIVE
        if ICON_IDLE is None:
            ICON_IDLE = _make_tray_icon(active=False)
        if ICON_ACTIVE is None:
            ICON_ACTIVE = _make_tray_icon(active=True)

        self._app = app
        self._config = app_config.normalize(_load_config())
        self._recording = False
        self._mode = "toggle"   # "toggle" or "ptt"
        self._last_partial: str = ""
        self._has_spoken: bool = False
        self._settings_dialog = None
        self._history: deque[str] = deque(maxlen=HISTORY_SIZE)
        self._history_menu = None
        self._last_dictation: tuple[int, int] | None = None   # (characters typed, window) for "Undo"
        self._session_window: int = 0                        # window the latest segment was typed into
        self._no_speech_streak: int = 0

        # Configurable features (re-read by _apply_runtime_settings whenever settings change)
        self._apply_runtime_settings()

        # Session tracking for continuous streaming
        self._session_injected_text: str = ""
        self._session_segments: list[str] = []
        self._session_segment_states: list[tuple] = []   # list state before each segment (for "scratch that")
        self._list = ListState()
        self._session_segments_count: int = 0
        self._session_handled_segments: int = 0   # utterances processed live (any outcome)
        self._session_had_output: bool = False    # something was typed or a voice command ran

        # Safety idle timer for continuous mode (stands down after prolonged silence)
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._on_idle_timeout)

        # Silence auto-commit timer (used only when continuous_mode is False)
        self._silence_timer = QTimer(self)
        self._silence_timer.setSingleShot(True)
        self._silence_timer.timeout.connect(self._on_silence_timeout)

        # Idle memory trim: shortly after the last activity, let Windows reclaim the model's RAM
        self._trim_timer = QTimer(self)
        self._trim_timer.setSingleShot(True)
        self._trim_timer.timeout.connect(self._trim_memory)

        # Build components
        self._pill        = PillWindow()
        self._transcriber = TranscriberThread(
            parent=self, settings=EngineSettings.from_config(self._config), preload=preload
        )
        self._hotkey      = HotkeyManager(
            parent=self,
            toggle=self._config.get("hotkey_toggle", DEFAULT_TOGGLE),
            ptt=self._config.get("hotkey_ptt", DEFAULT_PTT),
        )

        # Tray
        self._tray = self._build_tray()
        self._tray.show()

        # Wire signals
        self._transcriber.partial_text.connect(self._on_partial)
        self._transcriber.segment_text.connect(self._on_segment)
        self._transcriber.final_text.connect(self._on_final)
        self._transcriber.error.connect(self._on_transcriber_error)
        self._transcriber.ready.connect(self._on_transcriber_ready)
        self._transcriber.loading.connect(self._on_transcriber_loading)
        self._transcriber.level.connect(self._on_level)

        # Hotkey signals (Toggle, Push-to-Talk, Esc finish)
        self._hotkey.toggle_activated.connect(self._toggle_recording)
        self._hotkey.ptt_pressed.connect(self._on_ptt_pressed)
        self._hotkey.ptt_released.connect(self._on_ptt_released)
        self._hotkey.esc_pressed.connect(self._on_esc_pressed)
        self._hotkey.registration_issue.connect(self._on_hotkey_issue)

        # Start loading the model only now that ready/error are connected (see start_loading)
        self._transcriber.start_loading()

        # Start hotkey listener
        self._hotkey.start()

    def _apply_runtime_settings(self):
        """Copy the settings that are read while dictating into plain attributes."""
        c = self._config
        self._continuous_mode = c["continuous_mode"]
        self._filter_fillers = c["filter_filler_words"]
        self._enable_emojis = c["enable_emojis"]
        self._voice_formatting = c["voice_formatting"]
        self._safety_idle_timeout = c["safety_idle_timeout_seconds"]
        self._auto_stop_on_pause = c["auto_stop_on_pause"]
        self._pause_seconds = c["pause_duration_seconds"]
        self._esc_to_finish = c["esc_to_finish"]
        self._smart_formatting = c["smart_formatting"]
        self._keep_history = c["keep_history"]
        if not self._keep_history:
            self._history.clear()
        if self._history_menu is not None:
            self._history_menu.menuAction().setVisible(self._keep_history)
        configure_injector(clipboard_safety_net=c["clipboard_safety_net"], line_break_key=c["line_break_key"])

    # ------------------------------------------------------------------ #
    # Hotkey handlers (marshalled to Qt main thread)                      #
    # ------------------------------------------------------------------ #

    @Slot()
    def _toggle_recording(self):
        if not self._recording:
            self._start_recording(mode="toggle")
        else:
            self._stop_recording()

    @Slot()
    def _on_ptt_pressed(self):
        if not self._recording:
            self._start_recording(mode="ptt")

    @Slot()
    def _on_ptt_released(self):
        if self._recording and self._mode == "ptt":
            self._stop_recording()

    @Slot()
    def _on_esc_pressed(self):
        if self._recording:
            self._stop_recording()

    @Slot(str)
    def _on_hotkey_issue(self, message: str):
        self._tray.showMessage("Bepo", message, QSystemTrayIcon.MessageIcon.Warning, 10000)

    @Slot()
    def _on_silence_timeout(self):
        if self._recording and self._mode == "toggle" and not self._continuous_mode and self._has_spoken:
            self._stop_recording()

    @Slot()
    def _on_idle_timeout(self):
        logging.info("[Bepo] Safety idle timeout reached (%ss inactivity). Stopping dictation.", self._safety_idle_timeout)
        if self._recording:
            self._stop_recording()

    # ------------------------------------------------------------------ #
    # Recording control                                                    #
    # ------------------------------------------------------------------ #

    def _start_recording(self, mode: str = "toggle"):
        self._recording = True
        self._mode = mode
        self._last_partial = ""
        self._has_spoken = False
        self._session_injected_text = ""
        self._session_segments = []
        self._session_segment_states = []
        self._list.reset()
        self._session_segments_count = 0
        self._session_handled_segments = 0
        self._session_had_output = False
        self._silence_timer.stop()
        self._idle_timer.stop()
        self._trim_timer.stop()
        self._last_dictation = None
        self._session_window = 0

        if self._continuous_mode:
            self._idle_timer.start(int(self._safety_idle_timeout * 1000))

        if self._esc_to_finish:
            self._hotkey.start_esc_watcher()

        self._update_tray_state(recording=True)
        label = "Hold..." if mode == "ptt" else "Listening"
        self._pill.show_listening(label)
        # Open the microphone first, then beep: the start cue now means "speak now".
        # (On failure the transcriber reports the error and _recording is reset.)
        self._transcriber.start_recording()
        if self._recording:
            _play_earcon("start")

    def _stop_recording(self):
        if not self._recording:
            return
        self._recording = False
        self._silence_timer.stop()
        self._idle_timer.stop()
        self._hotkey.stop_esc_watcher()
        self._update_tray_state(recording=False)
        self._transcriber.stop_recording()

    # ------------------------------------------------------------------ #
    # Transcriber signal handlers (Qt main thread)                        #
    # ------------------------------------------------------------------ #

    @Slot()
    def _on_transcriber_ready(self):
        logging.info("[Bepo] Speech model ready")
        self._update_tray_state(recording=False)
        self._schedule_trim()

    @Slot()
    def _on_transcriber_loading(self):
        self._tray.setToolTip("Bepo: Loading speech model...")

    @Slot(float)
    def _on_level(self, level: float):
        self._pill.set_level(level)

    @Slot(str)
    def _on_partial(self, text: str):
        self._last_partial = text
        self._has_spoken = True
        self._pill.update_partial(text)

        # Reset safety idle timer on speech activity
        if self._recording and self._continuous_mode:
            self._idle_timer.start(int(self._safety_idle_timeout * 1000))

        # Reset silence auto-commit timer only in non-continuous mode
        if self._recording and self._mode == "toggle" and not self._continuous_mode and self._auto_stop_on_pause:
            self._silence_timer.start(int(self._pause_seconds * 1000))

    @Slot(str)
    def _on_segment(self, raw_text: str):
        """Fires when Moonshine finalizes an individual utterance/sentence."""
        if not self._continuous_mode:
            return

        # CRITICAL FIX for infinite spaces bug on Ctrl+Space:
        # In Push-to-Talk mode, user is holding Ctrl+Space physically.
        # Do not inject intermediate text while PTT keys are physically held.
        if self._mode == "ptt":
            return

        self._session_handled_segments += 1

        # Check for voice editing & deletion commands (Scratch that, Delete last word, Clear all)
        cmd_type, count, remaining = parse_voice_command(raw_text)
        if cmd_type != CommandType.NONE:
            self._session_had_output = True
            self._handle_voice_command(cmd_type, count)
            return

        if not remaining:
            # Self-cancelled in-flight (e.g. "We will meet at six. Scratch that.")
            return

        if self._voice_formatting:
            layout_cmd = parse_format_command(remaining)
            if layout_cmd is not None:
                self._handle_format_command(layout_cmd)
                return

        cleaned = clean_transcript(
            remaining,
            filter_fillers=self._filter_fillers,
            enable_emojis=self._enable_emojis,
            smart_formatting=self._smart_formatting,
        )
        if not cleaned:
            logging.info("[Bepo] Filtered out hesitation filler (%d chars)", len(raw_text))
            return

        # Smart spacing between sentences, plus list markers while a list is open
        state_before = self._list.snapshot()
        to_inject = self._list.compose(cleaned, self._session_injected_text)
        self._type_segment(to_inject, state_before)

        # Confirm injected sentence on pill without closing
        self._pill.notify_sentence_injected(cleaned)

        # Reset inactivity timer
        if self._recording and self._continuous_mode:
            self._idle_timer.start(int(self._safety_idle_timeout * 1000))

    def _type_segment(self, text: str, state_before: tuple):
        """Record `text` as the latest segment of this session and queue it for typing."""
        self._session_segments.append(text)
        self._session_segment_states.append(state_before)
        self._session_injected_text += text
        self._session_segments_count += 1
        self._session_had_output = True
        self._session_window = foreground_window()
        # Enqueue text for sequential background injection (safe against interleaving)
        enqueue_injection(text, self._session_injected_text)

    def _handle_format_command(self, command: FormatCommand):
        """Execute a spoken layout command: line breaks and numbered / bulleted lists."""
        logging.info("[Bepo] Executing layout command: %s", command.name)
        self._session_had_output = True

        if command in (FormatCommand.NEW_LINE, FormatCommand.NEW_PARAGRAPH):
            paragraph = command == FormatCommand.NEW_PARAGRAPH
            self._type_segment("\n\n" if paragraph else "\n", self._list.snapshot())
            self._pill.notify_status("New paragraph ↵" if paragraph else "New line ↵")
        elif command in (FormatCommand.START_NUMBERED, FormatCommand.START_BULLETS):
            numbered = command == FormatCommand.START_NUMBERED
            self._list.start(NUMBERED if numbered else BULLETS)
            self._pill.notify_status("Numbered list" if numbered else "Bullet list")
        elif command == FormatCommand.NEXT_ITEM:
            self._pill.notify_status("Next item" if self._list.next_item() else "No list started")
        elif command == FormatCommand.END_LIST:
            self._pill.notify_status("List ended" if self._list.end() else "No list started")

        if self._recording and self._continuous_mode:
            self._idle_timer.start(int(self._safety_idle_timeout * 1000))

    def _handle_voice_command(self, cmd_type: CommandType, count: int):
        """Execute spoken editing & deletion command."""
        logging.info("[Bepo] Executing voice command: %s (count=%s)", cmd_type.name, count)

        if not self._session_injected_text and not self._session_segments:
            self._pill.notify_deleted("Nothing to delete")
            return

        if not self._same_window(self._session_window):
            # Backspaces go to whatever has focus: never delete in a window we didn't type into
            logging.info("[Bepo] Voice deletion skipped: focus moved to another window")
            self._pill.notify_deleted("Window changed - nothing deleted")
            return

        if cmd_type == CommandType.SCRATCH_THAT:
            if self._session_segments:
                last_chunk = self._session_segments.pop()
                self._list.restore(self._session_segment_states.pop())
                chars_to_delete = len(last_chunk)
                self._session_injected_text = "".join(self._session_segments)
                self._session_segments_count = len(self._session_segments)
                enqueue_deletion(chars_to_delete, self._session_injected_text)
                preview = last_chunk.strip() or "line break"
                preview = preview[-16:] if len(preview) > 16 else preview
                self._pill.notify_deleted(f"Deleted \"{preview}\" ⌫")
                _play_earcon("delete")
            elif self._session_injected_text:
                chars_to_delete = len(self._session_injected_text)
                self._session_injected_text = ""
                self._session_segments_count = 0
                enqueue_deletion(chars_to_delete, "")
                self._pill.notify_deleted("Deleted ⌫")
                _play_earcon("delete")

        elif cmd_type == CommandType.DELETE_WORDS:
            if self._session_injected_text:
                current = self._session_injected_text.rstrip()
                words = list(re.finditer(r"\S+", current))
                if words:
                    num_to_drop = max(1, min(count, len(words)))
                    # Cut at the start of the first dropped word; keep any line breaks before it
                    kept = current[:words[-num_to_drop].start()].rstrip(" \t")
                    chars_to_delete = len(self._session_injected_text) - len(kept)
                    first_state = self._session_segment_states[0] if self._session_segment_states else None
                    if kept.strip():
                        self._session_injected_text = kept
                        self._session_segments = [kept]
                        self._session_segment_states = [first_state] if first_state else []
                    else:
                        chars_to_delete = len(self._session_injected_text)
                        self._session_injected_text = ""
                        self._session_segments.clear()
                        self._session_segment_states.clear()
                        if first_state:
                            self._list.restore(first_state)
                    self._session_segments_count = len(self._session_segments)
                    enqueue_deletion(chars_to_delete, self._session_injected_text)
                    w_str = f"{num_to_drop} word{'s' if num_to_drop > 1 else ''}"
                    self._pill.notify_deleted(f"Deleted {w_str} ⌫")
                    _play_earcon("delete")

        elif cmd_type == CommandType.DELETE_ALL:
            if self._session_injected_text:
                chars_to_delete = len(self._session_injected_text)
                self._session_injected_text = ""
                if self._session_segment_states:
                    self._list.restore(self._session_segment_states[0])
                self._session_segments.clear()
                self._session_segment_states.clear()
                self._session_segments_count = 0
                enqueue_deletion(chars_to_delete, "")
                self._pill.notify_deleted("Cleared all ⌫")
                _play_earcon("delete")

        # Reset inactivity timer
        if self._recording and self._continuous_mode:
            self._idle_timer.start(int(self._safety_idle_timeout * 1000))

    @Slot(str)
    def _on_final(self, text: str):
        self._recording = False
        self._idle_timer.stop()
        self._silence_timer.stop()
        self._update_tray_state(recording=False)
        self._schedule_trim()

        if self._continuous_mode and self._mode != "ptt" and self._session_handled_segments > 0:
            # Everything was already processed live, utterance by utterance. Do NOT re-parse
            # the transcriber's full text here: it still contains sentences that were typed
            # and later deleted (and the delete commands themselves).
            if self._session_had_output:
                self._pill.show_done(self._session_injected_text)
                _play_earcon("done")
                self._finish_dictation(self._session_injected_text, self._session_window)
            else:
                self._pill.show_error("No speech detected")
                self._note_no_speech()
            return

        # PTT, non-continuous mode, or nothing was handled live: inject the whole transcript now
        self._finalize_full_text(text)

    def _finalize_full_text(self, text: str):
        """Parse, clean and inject a complete transcript in one go."""
        cmd_type, count, remaining = parse_voice_command(text)
        if cmd_type != CommandType.NONE:
            self._handle_voice_command(cmd_type, count)
            self._pill.show_done(self._session_injected_text)
            return
        if not remaining:
            self._pill.show_error("No speech detected")
            self._note_no_speech()
            return
        cleaned = clean_transcript(
            remaining,
            filter_fillers=self._filter_fillers,
            enable_emojis=self._enable_emojis,
            smart_formatting=self._smart_formatting,
        )
        if cleaned:
            enqueue_injection(cleaned, cleaned)
            self._pill.show_done(cleaned)
            _play_earcon("done")
            self._finish_dictation(cleaned, foreground_window())
        else:
            self._pill.show_error("No speech detected")
            self._note_no_speech()

    # ------------------------------------------------------------------ #
    # After a dictation: undo, history, "not hearing you" hint            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _same_window(expected: int) -> bool:
        """False only when we know text went into a window other than the one focused now."""
        current = foreground_window()
        return not expected or not current or current == expected

    def _finish_dictation(self, text: str, window: int):
        self._no_speech_streak = 0
        if text:
            self._last_dictation = (len(text), window)
            if self._keep_history and text.strip():
                self._history.appendleft(text.strip())

    def _note_no_speech(self):
        self._no_speech_streak += 1
        if self._no_speech_streak >= NO_SPEECH_HINT_AFTER:
            self._no_speech_streak = 0
            mic = self._config.get("microphone") or "System default"
            self._tray.showMessage(
                "Bepo can't hear you",
                f"Microphone in use: {mic}. Check it under Settings > Microphone, "
                "make sure it isn't muted, or try a larger speech model.",
                QSystemTrayIcon.MessageIcon.Warning, 8000,
            )

    @Slot()
    def undo_last_dictation(self):
        """Delete the text typed by the last dictation (tray menu), if focus is still where it went."""
        if self._recording:
            return
        if self._last_dictation is None:
            self._tray.showMessage("Bepo", "Nothing to undo.", QSystemTrayIcon.MessageIcon.Information, 3000)
            return
        count, window = self._last_dictation
        if not self._same_window(window):
            self._tray.showMessage(
                "Bepo", "Switch back to the window you dictated into, then undo again.",
                QSystemTrayIcon.MessageIcon.Warning, 5000,
            )
            return
        self._last_dictation = None
        enqueue_deletion(count, "")
        _play_earcon("delete")

    def _rebuild_history_menu(self):
        menu = self._history_menu
        menu.clear()
        if not self._history:
            menu.addAction("(nothing yet)").setEnabled(False)
            return
        for text in self._history:
            label = " ".join(text.split())
            label = label if len(label) <= 48 else label[:47] + "…"
            action = menu.addAction(label.replace("&", "&&"))
            action.triggered.connect(lambda _checked=False, t=text: self._copy_to_clipboard(t))

    def _copy_to_clipboard(self, text: str):
        QApplication.clipboard().setText(text)

    @Slot(str)
    def _on_transcriber_error(self, msg: str):
        self._recording = False
        self._idle_timer.stop()
        self._silence_timer.stop()
        self._hotkey.stop_esc_watcher()
        self._update_tray_state(recording=False)
        self._pill.show_error(msg)
        if msg == "No speech detected":
            self._note_no_speech()
        self._schedule_trim()

    # ------------------------------------------------------------------ #
    # Idle memory                                                          #
    # ------------------------------------------------------------------ #

    def _schedule_trim(self):
        self._trim_timer.start(IDLE_TRIM_DELAY_MS)

    @Slot()
    def _trim_memory(self):
        if not self._recording:
            memory.trim_working_set()

    # ------------------------------------------------------------------ #
    # Settings                                                             #
    # ------------------------------------------------------------------ #

    def apply_settings(self, new_config: dict):
        """Apply and persist new settings immediately (no restart needed)."""
        previous = self._config
        self._config = config = app_config.normalize(new_config)
        self._apply_runtime_settings()

        if (config["hotkey_toggle"], config["hotkey_ptt"]) != (previous["hotkey_toggle"], previous["hotkey_ptt"]):
            self._hotkey.reconfigure(config["hotkey_toggle"], config["hotkey_ptt"])
        self._transcriber.apply_settings(EngineSettings.from_config(config))
        self._update_tray_state(recording=self._recording)

        try:
            app_config.save_user_config(config)
        except OSError as exc:
            logging.warning("[Bepo] Could not save settings: %s", exc)
            self._tray.showMessage(
                "Bepo", "Settings were applied but could not be saved to disk.",
                QSystemTrayIcon.MessageIcon.Warning, 8000,
            )
        self._schedule_trim()

    @Slot(dict, bool)
    def _on_settings_saved(self, config: dict, launch_at_startup: bool):
        self.apply_settings(config)
        if launch_at_startup != startup.is_enabled():
            if not startup.set_enabled(launch_at_startup):
                self._tray.showMessage(
                    "Bepo", "Could not change the 'launch at Windows startup' setting.",
                    QSystemTrayIcon.MessageIcon.Warning, 8000,
                )

    def _show_settings(self):
        if self._settings_dialog is not None and self._settings_dialog.isVisible():
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        dialog = SettingsDialog(
            self._config,
            launch_at_startup=startup.is_enabled(),
            suspend_hotkeys=self._hotkey.suspend,
            resume_hotkeys=self._hotkey.resume,
        )
        dialog.saved.connect(self._on_settings_saved)
        self._settings_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    # ------------------------------------------------------------------ #
    # System tray                                                          #
    # ------------------------------------------------------------------ #

    def _update_tray_state(self, recording: bool):
        """Update system tray icon, tooltip, and menu text dynamically."""
        toggle = self._hotkey.toggle_label
        suffix = f" ({toggle})" if toggle else ""
        if recording:
            self._tray.setIcon(ICON_ACTIVE)
            stop_keys = f"{toggle} or Esc" if toggle else "Esc"
            self._tray.setToolTip(f"Bepo: Listening ({stop_keys} to stop)")
            if hasattr(self, "_dictate_action"):
                self._dictate_action.setText(f"⏹  Stop & Type{suffix}")
        else:
            self._tray.setIcon(ICON_IDLE)
            self._tray.setToolTip(f"Bepo: Press {toggle} to start" if toggle else "Bepo: Ready (use the tray menu to start)")
            if hasattr(self, "_dictate_action"):
                self._dictate_action.setText(f"🎙  Start Dictation{suffix}")

    def _build_tray(self) -> QSystemTrayIcon:
        tray = QSystemTrayIcon(ICON_IDLE, self._app)
        tray.setToolTip("Bepo: Starting model...")

        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background: #1C1C1E;
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 8px;
                padding: 4px;
                color: white;
                font-family: 'Segoe UI Variable', 'Segoe UI', sans-serif;
                font-size: 13px;
            }
            QMenu::item { padding: 6px 20px; border-radius: 4px; }
            QMenu::item:selected { background: rgba(255,255,255,0.1); }
            QMenu::separator { height: 1px; background: rgba(255,255,255,0.1); margin: 4px 8px; }
        """)

        toggle = self._hotkey.toggle_label
        self._dictate_action = QAction(
            f"🎙  Start Dictation ({toggle})" if toggle else "🎙  Start Dictation", self._app
        )
        self._dictate_action.triggered.connect(self._toggle_recording)
        menu.addAction(self._dictate_action)

        undo_action = QAction("↶  Undo last dictation", self._app)
        undo_action.triggered.connect(self.undo_last_dictation)
        menu.addAction(undo_action)

        self._history_menu = menu.addMenu("🕘  Recent dictations")
        self._history_menu.aboutToShow.connect(self._rebuild_history_menu)
        self._history_menu.menuAction().setVisible(self._keep_history)

        settings_action = QAction("⚙️  Settings", self._app)
        settings_action.triggered.connect(self._show_settings)
        menu.addAction(settings_action)

        menu.addSeparator()

        quit_action = QAction("Quit Bepo", self._app)
        quit_action.triggered.connect(self._app.quit)
        menu.addAction(quit_action)

        tray.setContextMenu(menu)
        return tray

    def cleanup(self):
        self._silence_timer.stop()
        self._trim_timer.stop()
        self._hotkey.stop()
        self._transcriber.stop_recording()
        self._transcriber.quit()
        self._transcriber.wait(2000)


# ------------------------------------------------------------------ #
# Entry point                                                          #
# ------------------------------------------------------------------ #

def main():
    global ICON_IDLE, ICON_ACTIVE, _PRELOAD

    if not bootstrap.started:           # not run as a script (e.g. imported): do the early work now
        _PRELOAD = bootstrap.early_start()

    config = app_config.load_config()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Bepo")
    app._instance_mutex = bootstrap.instance_mutex

    app_icon_path = Path(__file__).parent / "assets" / "icon.png"
    if app_icon_path.exists():
        app.setWindowIcon(QIcon(str(app_icon_path)))

    ICON_IDLE   = _make_tray_icon(active=False)
    ICON_ACTIVE = _make_tray_icon(active=True)

    if getattr(sys, "frozen", False):
        startup.refresh_if_enabled()    # keep "launch at startup" pointing at this install

    def launch_main_app():
        app._controller = BepoApp(app, preload=_PRELOAD)
        app.aboutToQuit.connect(app._controller.cleanup)

    if not is_model_downloaded(config["speech_model"]):
        setup = SetupScreen(config["speech_model"])
        setup.setup_complete.connect(launch_main_app)
        setup.setup_complete.connect(setup.deleteLater)
        setup.show_and_start()
    else:
        launch_main_app()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
