"""
settings_dialog.py
The Bepo settings window (opened from the tray menu).

Changes are applied immediately on Save — no restart. If a speech model that has not been
downloaded yet is selected, Save first downloads it (with progress) and then applies everything.

The dialog itself never touches the running app: it emits `saved(config, launch_at_startup)`
and the controller (main.BepoApp) applies and persists it.
"""

import sys
import ctypes
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox, QComboBox,
    QPlainTextEdit, QScrollArea, QWidget, QFrame, QProgressBar,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QGuiApplication

from core import audio_devices
from core import config as app_config
from core.hotkey import parse_hotkey
from setup.model_downloader import MODELS, is_model_downloaded
from ui.about_dialog import AboutDialog
from ui.setup_screen import DownloadThread, breakable

IS_WINDOWS_11 = sys.platform == "win32" and hasattr(sys, "getwindowsversion") and sys.getwindowsversion().build >= 22000

DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_SYSTEMBACKDROP_TYPE      = 38
DWMWCP_ROUND                   = 2
DWMSBT_MAINWINDOW              = 2   # Mica

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
# Downloads keep running even if the window is closed; hold a reference until they finish.
_ACTIVE_DOWNLOADS: set = set()

IDLE_MINUTE_CHOICES = (1, 2, 3, 5, 10, 15, 30, 60)
PAUSE_SECOND_CHOICES = (1.0, 1.5, 2.0, 3.0, 5.0)

_QSS = """
QDialog, QScrollArea, QScrollArea > QWidget > QWidget { background: #1C1C1E; }
QWidget { color: #F8FAFC; font-family: 'Segoe UI Variable Text', 'Segoe UI', sans-serif; font-size: 13px; }
QLabel { background: transparent; }
QLabel#title { font-size: 20px; font-weight: 700; color: #FFFFFF; }
QLabel#sectionTitle { font-size: 11px; font-weight: 700; color: rgba(255,255,255,0.55); letter-spacing: 1px; }
QLabel#hint { font-size: 11px; color: rgba(255,255,255,0.55); }
QLabel#warn { font-size: 11px; color: #FF9F0A; }
QLabel#error { font-size: 12px; color: #FF453A; }
QFrame#card { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; }
QCheckBox { spacing: 10px; background: transparent; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 5px; border: 1px solid rgba(255,255,255,0.35); background: transparent; }
QCheckBox::indicator:hover { border-color: rgba(255,255,255,0.6); }
QCheckBox::indicator:checked { background: #2563EB; border-color: #2563EB; image: url(@CHECK@); }
QCheckBox:disabled { color: rgba(255,255,255,0.35); }
QComboBox { background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.14); border-radius: 6px; padding: 6px 10px; min-height: 18px; }
QComboBox:hover { border-color: rgba(255,255,255,0.3); }
QComboBox:disabled { color: rgba(255,255,255,0.35); }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox::down-arrow { image: url(@CHEVRON@); width: 14px; height: 14px; }
QComboBox QAbstractItemView { background: #2A2A2D; border: 1px solid rgba(255,255,255,0.14); selection-background-color: #2563EB; outline: none; padding: 4px; }
QPlainTextEdit { background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.14); border-radius: 6px; padding: 6px 8px; }
QPlainTextEdit:focus { border-color: #2563EB; }
QPushButton { background: rgba(255,255,255,0.10); border: 1px solid rgba(255,255,255,0.14); border-radius: 6px; padding: 6px 16px; }
QPushButton:hover { background: rgba(255,255,255,0.18); }
QPushButton:disabled { color: rgba(255,255,255,0.35); background: rgba(255,255,255,0.05); }
QPushButton#primary { background: #2563EB; border: none; color: #FFFFFF; font-weight: 600; }
QPushButton#primary:hover { background: #1D4ED8; }
QPushButton#primary:disabled { background: rgba(37,99,235,0.4); }
QPushButton#link { background: transparent; border: none; color: #60A5FA; padding: 6px 8px; }
QPushButton#link:hover { color: #93C5FD; }
QPushButton#hotkey { text-align: center; min-width: 190px; font-weight: 600; }
QPushButton#hotkey[capturing="true"] { border: 1px solid #2563EB; background: rgba(37,99,235,0.22); }
QProgressBar { background: rgba(255,255,255,0.12); border: none; border-radius: 3px; max-height: 6px; }
QProgressBar::chunk { background: #2563EB; border-radius: 3px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: rgba(255,255,255,0.22); border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


def _stylesheet() -> str:
    return (_QSS
            .replace("@CHECK@", (_ASSETS / "check.svg").as_posix())
            .replace("@CHEVRON@", (_ASSETS / "chevron-down.svg").as_posix()))


# ---------------------------------------------------------------------- #
# Shortcut capture widget                                                #
# ---------------------------------------------------------------------- #

def _key_name(key: int) -> str | None:
    """Name used in hotkey strings for a Qt key code, or None if unsupported."""
    K = Qt.Key
    if K.Key_A.value <= key <= K.Key_Z.value:
        return chr(key).lower()
    if K.Key_0.value <= key <= K.Key_9.value:
        return chr(key)
    if K.Key_F1.value <= key <= K.Key_F24.value:
        return f"f{key - K.Key_F1.value + 1}"
    return {K.Key_Space.value: "space", K.Key_Return.value: "enter",
            K.Key_Enter.value: "enter", K.Key_Tab.value: "tab"}.get(key)


class HotkeyEdit(QPushButton):
    """Button that records a keyboard shortcut: click it, then press the combination."""

    changed = Signal()

    def __init__(self, value: str | None, suspend=None, resume=None, parent=None):
        super().__init__(parent)
        self.setObjectName("hotkey")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._value = (value or "").strip().lower()
        self._suspend, self._resume = suspend, resume
        self._capturing = False
        self.clicked.connect(self.begin_capture)
        self._refresh()

    def value(self) -> str:
        """The shortcut as a config string; "" means disabled."""
        return self._value

    def set_value(self, value: str | None):
        self._value = (value or "").strip().lower()
        self._refresh()
        self.changed.emit()

    @staticmethod
    def pretty(value: str) -> str:
        return "+".join(t.capitalize() for t in value.split("+")) if value else "Disabled"

    def _refresh(self, text: str | None = None):
        self.setText(text if text is not None else self.pretty(self._value))
        self.setProperty("capturing", self._capturing)
        self.style().unpolish(self)
        self.style().polish(self)

    def begin_capture(self):
        if self._capturing:
            return
        self._capturing = True
        if self._suspend:
            self._suspend()           # otherwise Bepo's own shortcut would fire while recording
        self.grabKeyboard()
        self._refresh("Press the new shortcut…  (Esc to cancel)")

    def _end_capture(self):
        if not self._capturing:
            return
        self._capturing = False
        self.releaseKeyboard()
        if self._resume:
            self._resume()
        self._refresh()

    def focusOutEvent(self, event):
        self._end_capture()
        super().focusOutEvent(event)

    def hideEvent(self, event):
        self._end_capture()
        super().hideEvent(event)

    def keyPressEvent(self, event):
        if not self._capturing:
            super().keyPressEvent(event)
            return
        event.accept()
        K = Qt.Key
        key = event.key()
        mods = event.modifiers()
        names = []
        if mods & Qt.KeyboardModifier.ControlModifier:
            names.append("ctrl")
        if mods & Qt.KeyboardModifier.AltModifier:
            names.append("alt")
        if mods & Qt.KeyboardModifier.ShiftModifier:
            names.append("shift")

        if key == K.Key_Escape.value:
            self._end_capture()
            return
        if key in (K.Key_Control.value, K.Key_Alt.value, K.Key_Shift.value, K.Key_AltGr.value):
            self._refresh("+".join(t.capitalize() for t in names) + "+…" if names else None)
            return

        if key in (K.Key_Meta.value, K.Key_Super_L.value, K.Key_Super_R.value):
            if not names:
                self._refresh("Hold Ctrl, Alt or Shift together with the Win key")
                return
            names.append("win")
        else:
            token = _key_name(key)
            if token is None:
                self._refresh("That key isn't supported — try a letter, F-key or Space")
                return
            if mods & Qt.KeyboardModifier.MetaModifier:
                names.append("win")
            if not names and not token.startswith("f"):
                self._refresh("Add Ctrl, Alt, Shift or Win to the shortcut")
                return
            names.append(token)

        candidate = "+".join(names)
        if parse_hotkey(candidate) is None:
            self._refresh("That combination isn't supported")
            return
        self._value = candidate
        self._end_capture()
        self.changed.emit()


# ---------------------------------------------------------------------- #
# Settings window                                                        #
# ---------------------------------------------------------------------- #

class SettingsDialog(QDialog):
    """Bepo settings. Emits `saved(config, launch_at_startup)` when the user saves."""

    saved = Signal(dict, bool)

    def __init__(self, config: dict, launch_at_startup: bool = False,
                 suspend_hotkeys=None, resume_hotkeys=None, parent=None):
        super().__init__(parent)
        self._original = app_config.normalize(config)
        self._suspend, self._resume = suspend_hotkeys, resume_hotkeys
        self._download = None
        self._pending: dict | None = None
        self._about = None

        self.setWindowTitle("Bepo Settings")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)
        self.setStyleSheet(_stylesheet())
        icon_path = _ASSETS / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._build_ui(launch_at_startup)
        self._load(self._original, launch_at_startup)
        self._size_to_screen()

    # ------------------------------------------------------------------ #
    # Layout                                                              #
    # ------------------------------------------------------------------ #

    def _size_to_screen(self):
        screen = QGuiApplication.primaryScreen()
        available = screen.availableGeometry().height() if screen else 900
        self.setFixedWidth(600)
        self.resize(600, min(780, max(480, available - 80)))
        self.setMinimumHeight(420)

    @staticmethod
    def _card(title: str):
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        heading = QLabel(title.upper())
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        return frame, layout

    @staticmethod
    def _hint(text: str, name: str = "hint") -> QLabel:
        label = QLabel(text)
        label.setObjectName(name)
        label.setWordWrap(True)
        return label

    @staticmethod
    def _labeled(text: str, widget: QWidget, extra: QWidget | None = None) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        label = QLabel(text)
        label.setMinimumWidth(150)
        row.addWidget(label)
        row.addWidget(widget, 1)
        if extra is not None:
            row.addWidget(extra)
        return row

    def _build_ui(self, launch_at_startup: bool):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(24, 22, 24, 12)
        col.setSpacing(14)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        title = QLabel("Settings")
        title.setObjectName("title")
        col.addWidget(title)

        # ---- Shortcuts
        card, lay = self._card("Shortcuts")
        self.toggle_edit = HotkeyEdit("", self._suspend, self._resume)
        self.toggle_off = QPushButton("Disable")
        self.toggle_off.setObjectName("link")
        self.toggle_off.clicked.connect(lambda: self.toggle_edit.set_value(""))
        lay.addLayout(self._labeled("Start / stop dictation", self.toggle_edit, self.toggle_off))
        self.ptt_edit = HotkeyEdit("", self._suspend, self._resume)
        self.ptt_off = QPushButton("Disable")
        self.ptt_off.setObjectName("link")
        self.ptt_off.clicked.connect(lambda: self.ptt_edit.set_value(""))
        lay.addLayout(self._labeled("Push-to-talk (hold)", self.ptt_edit, self.ptt_off))
        lay.addWidget(self._hint(
            "Click a box, then press the shortcut you want. Note: a shortcut Bepo uses is taken "
            "from every other app — for example Ctrl+Space no longer reaches the autocomplete "
            "in code editors."))
        self.esc_check = QCheckBox("Pressing Esc finishes dictation")
        lay.addWidget(self.esc_check)
        col.addWidget(card)

        # ---- Dictation
        card, lay = self._card("Dictation")
        self.continuous_check = QCheckBox("Type sentence by sentence while I speak")
        lay.addWidget(self.continuous_check)
        self.fillers_check = QCheckBox("Remove filler words (um, uh, hmm…)")
        lay.addWidget(self.fillers_check)
        self.emoji_check = QCheckBox('Turn spoken emoji into symbols ("thumbs up emoji" → 👍)')
        lay.addWidget(self.emoji_check)
        self.autostop_check = QCheckBox("Finish automatically after a pause")
        lay.addWidget(self.autostop_check)
        self.pause_combo = QComboBox()
        lay.addLayout(self._labeled("   Pause length", self.pause_combo))
        self.autostop_hint = self._hint("Only used when typing sentence by sentence is turned off.")
        lay.addWidget(self.autostop_hint)
        self.idle_combo = QComboBox()
        lay.addLayout(self._labeled("Stop listening after", self.idle_combo))
        lay.addWidget(self._hint("Safety timer: the microphone is released if nothing is said for this long."))
        col.addWidget(card)

        # ---- Speech recognition
        card, lay = self._card("Speech recognition")
        self.model_combo = QComboBox()
        for key, info in MODELS.items():
            self.model_combo.addItem(f"{info.label} — {info.size_mb} MB", key)
        lay.addLayout(self._labeled("Speech model", self.model_combo))
        self.model_hint = self._hint("")
        lay.addWidget(self.model_hint)
        self.speed_combo = QComboBox()
        self.speed_combo.addItem("Efficient — less CPU, text appears ≈0.2 s later", "efficient")
        self.speed_combo.addItem("Fast — quickest typing, uses more CPU", "fast")
        lay.addLayout(self._labeled("Responsiveness", self.speed_combo))
        self.mic_combo = QComboBox()
        self.mic_refresh = QPushButton("↻")
        self.mic_refresh.setToolTip("Refresh the list of microphones")
        self.mic_refresh.setFixedWidth(40)
        self.mic_refresh.setStyleSheet("padding: 6px 0px; font-size: 15px;")
        self.mic_refresh.clicked.connect(lambda: self._fill_microphones(self._selected_microphone()))
        lay.addLayout(self._labeled("Microphone", self.mic_combo, self.mic_refresh))
        vocab_label = QLabel("Custom words")
        lay.addWidget(vocab_label)
        self.vocab_edit = QPlainTextEdit()
        self.vocab_edit.setPlaceholderText("One word or phrase per line, e.g.\nKubernetes\nMoonshine\nYour Name")
        self.vocab_edit.setFixedHeight(92)
        lay.addWidget(self.vocab_edit)
        lay.addWidget(self._hint(
            "Names, product names and jargon Bepo should prefer. Write them the way you want "
            "them typed. This nudges recognition; it can't guarantee a result."))
        col.addWidget(card)

        # ---- System & privacy
        card, lay = self._card("System & privacy")
        self.startup_check = QCheckBox("Start Bepo when I sign in to Windows")
        lay.addWidget(self.startup_check)
        self.clipboard_check = QCheckBox("Also keep the dictated text on the clipboard")
        lay.addWidget(self.clipboard_check)
        lay.addWidget(self._hint(
            "Off by default so Bepo never touches your clipboard. When on, Windows clipboard "
            "history (Win+V) and cloud clipboard sync may store what you dictate.", "warn"))
        col.addWidget(card)
        col.addStretch(1)

        # ---- Footer
        footer = QFrame()
        footer.setStyleSheet("QFrame { background: #1C1C1E; border-top: 1px solid rgba(255,255,255,0.08); }")
        foot = QVBoxLayout(footer)
        foot.setContentsMargins(24, 10, 24, 14)
        foot.setSpacing(8)
        self.status_label = self._hint("", "error")
        self.status_label.hide()
        foot.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.hide()
        foot.addWidget(self.progress)
        buttons = QHBoxLayout()
        self.defaults_btn = QPushButton("Restore defaults")
        self.defaults_btn.setObjectName("link")
        self.defaults_btn.clicked.connect(self._restore_defaults)
        buttons.addWidget(self.defaults_btn)
        self.about_btn = QPushButton("About")
        self.about_btn.setObjectName("link")
        self.about_btn.clicked.connect(self._show_about)
        buttons.addWidget(self.about_btn)
        buttons.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        self.save_btn = QPushButton("Save")
        self.save_btn.setObjectName("primary")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._on_save)
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.save_btn)
        foot.addLayout(buttons)
        outer.addWidget(footer)

        # Reactions
        self.continuous_check.toggled.connect(self._update_enabled)
        self.autostop_check.toggled.connect(self._update_enabled)
        self.model_combo.currentIndexChanged.connect(self._update_model_hint)

    def _show_about(self):
        if self._about is None:
            self._about = AboutDialog(self)
        self._about.show()
        self._about.raise_()
        self._about.activateWindow()

    # ------------------------------------------------------------------ #
    # Loading values into the widgets                                     #
    # ------------------------------------------------------------------ #

    def _fill_microphones(self, selected: str | None):
        self.mic_combo.blockSignals(True)
        self.mic_combo.clear()
        self.mic_combo.addItem("System default", None)
        names = audio_devices.list_input_devices()
        for name in names:
            self.mic_combo.addItem(name, name)
        if selected and selected not in names:
            self.mic_combo.addItem(f"{selected} (not connected)", selected)
        index = self.mic_combo.findData(selected)
        self.mic_combo.setCurrentIndex(index if index >= 0 else 0)
        self.mic_combo.blockSignals(False)

    def _selected_microphone(self) -> str | None:
        return self.mic_combo.currentData()

    def _fill_choice_combo(self, combo: QComboBox, values, current, fmt):
        combo.clear()
        items = list(values)
        if current not in items:
            items.append(current)
            items.sort()
        for value in items:
            combo.addItem(fmt(value), value)
        combo.setCurrentIndex(combo.findData(current))

    def _load(self, cfg: dict, launch_at_startup: bool):
        self.toggle_edit.set_value(cfg["hotkey_toggle"])
        self.ptt_edit.set_value(cfg["hotkey_ptt"])
        self.esc_check.setChecked(cfg["esc_to_finish"])
        self.continuous_check.setChecked(cfg["continuous_mode"])
        self.fillers_check.setChecked(cfg["filter_filler_words"])
        self.emoji_check.setChecked(cfg["enable_emojis"])
        self.autostop_check.setChecked(cfg["auto_stop_on_pause"])
        self._fill_choice_combo(self.pause_combo, PAUSE_SECOND_CHOICES, cfg["pause_duration_seconds"],
                                lambda v: f"{v:g} seconds")
        minutes = max(1, round(cfg["safety_idle_timeout_seconds"] / 60))
        self._idle_minutes_initial = minutes
        self._fill_choice_combo(self.idle_combo, IDLE_MINUTE_CHOICES, minutes,
                                lambda v: "1 minute of silence" if v == 1 else f"{v} minutes of silence")
        self.model_combo.setCurrentIndex(self.model_combo.findData(cfg["speech_model"]))
        self.speed_combo.setCurrentIndex(self.speed_combo.findData(cfg["responsiveness"]))
        self._fill_microphones(cfg["microphone"])
        self.vocab_edit.setPlainText("\n".join(cfg["custom_vocabulary"]))
        self.startup_check.setChecked(launch_at_startup)
        self.clipboard_check.setChecked(cfg["clipboard_safety_net"])
        self._update_enabled()
        self._update_model_hint()

    def _update_enabled(self, *_):
        continuous = self.continuous_check.isChecked()
        self.autostop_check.setEnabled(not continuous)
        self.pause_combo.setEnabled(not continuous and self.autostop_check.isChecked())
        self.autostop_hint.setVisible(continuous)

    def _update_model_hint(self, *_):
        key = self.model_combo.currentData()
        if key is None:
            return
        info = MODELS[key]
        if is_model_downloaded(key):
            status = "Installed."
        else:
            status = f"Not downloaded yet — Save will download it first (≈{info.size_mb} MB, one time)."
        self.model_hint.setText(f"{info.description} {status}")

    # ------------------------------------------------------------------ #
    # Reading values back                                                 #
    # ------------------------------------------------------------------ #

    def collect(self) -> dict:
        """The settings currently shown in the window (not yet validated)."""
        cfg = dict(self._original)
        cfg["hotkey_toggle"] = self.toggle_edit.value()
        cfg["hotkey_ptt"] = self.ptt_edit.value()
        cfg["esc_to_finish"] = self.esc_check.isChecked()
        cfg["continuous_mode"] = self.continuous_check.isChecked()
        cfg["filter_filler_words"] = self.fillers_check.isChecked()
        cfg["enable_emojis"] = self.emoji_check.isChecked()
        cfg["auto_stop_on_pause"] = self.autostop_check.isChecked()
        cfg["pause_duration_seconds"] = self.pause_combo.currentData()
        minutes = self.idle_combo.currentData()
        if minutes != self._idle_minutes_initial:           # keep exact seconds if untouched
            cfg["safety_idle_timeout_seconds"] = float(minutes * 60)
        cfg["speech_model"] = self.model_combo.currentData()
        cfg["responsiveness"] = self.speed_combo.currentData()
        cfg["microphone"] = self._selected_microphone()
        cfg["custom_vocabulary"] = app_config.clean_vocabulary(self.vocab_edit.toPlainText())
        cfg["clipboard_safety_net"] = self.clipboard_check.isChecked()
        return app_config.normalize(cfg)

    def _validate(self, cfg: dict) -> str | None:
        toggle, ptt = cfg["hotkey_toggle"], cfg["hotkey_ptt"]
        if toggle and ptt and toggle == ptt:
            return "The two shortcuts must be different."
        if not toggle and not ptt:
            return "Keep at least one shortcut, or you will only be able to start Bepo from the tray menu."
        return None

    # ------------------------------------------------------------------ #
    # Actions                                                             #
    # ------------------------------------------------------------------ #

    def _restore_defaults(self):
        base = app_config.base_config()
        self._load(base, launch_at_startup=False)
        self.status_label.hide()

    def _show_error(self, text: str):
        self.status_label.setText(text)
        self.status_label.show()

    def _set_busy(self, busy: bool):
        for widget in (self.save_btn, self.defaults_btn):
            widget.setEnabled(not busy)
        self.save_btn.setText("Downloading…" if busy else "Save")
        self.progress.setVisible(busy)
        if busy:
            self.progress.setValue(0)

    def _on_save(self):
        self.status_label.hide()
        cfg = self.collect()
        problem = self._validate(cfg)
        if problem:
            self._show_error(problem)
            return
        if is_model_downloaded(cfg["speech_model"]):
            self._finish(cfg)
        else:
            self._start_download(cfg)

    def _finish(self, cfg: dict):
        self.saved.emit(cfg, self.startup_check.isChecked())
        self.accept()

    def _start_download(self, cfg: dict):
        self._pending = cfg
        self._set_busy(True)
        thread = DownloadThread(cfg["speech_model"])       # no parent: survives closing this window
        self._download = thread
        _ACTIVE_DOWNLOADS.add(thread)
        thread.progress.connect(self._on_download_progress)
        thread.finished.connect(lambda t=thread: self._on_download_done(t))
        thread.error.connect(lambda msg, t=thread: self._on_download_error(t, msg))
        thread.start()

    def _on_download_progress(self, pct: int, filename: str):
        self.progress.setValue(pct)

    def _on_download_done(self, thread):
        _ACTIVE_DOWNLOADS.discard(thread)
        self._set_busy(False)
        if self._pending is not None and thread is self._download:
            cfg, self._pending = self._pending, None
            self._finish(cfg)

    def _on_download_error(self, thread, message: str):
        _ACTIVE_DOWNLOADS.discard(thread)
        self._set_busy(False)
        self._pending = None
        self._show_error(f"Download failed: {breakable(message, 160)}\n"
                         "Check your connection and try again, or choose a model that is already installed.")

    def done(self, result):
        # Never leave Bepo's own shortcuts suspended if the window closes mid-capture
        for edit in (self.toggle_edit, self.ptt_edit):
            edit._end_capture()
        self._pending = None            # closing the window cancels the pending save
        super().done(result)

    def showEvent(self, event):
        super().showEvent(event)
        if IS_WINDOWS_11:
            try:
                hwnd = int(self.winId())
                for attr, value in ((DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND),
                                    (DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_MAINWINDOW)):
                    v = ctypes.c_int(value)
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
            except Exception:
                pass
