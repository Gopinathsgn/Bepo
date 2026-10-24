"""
pill.py
The floating Acrylic capsule overlay — the primary visual feedback for Bepo dictation.

Design:
  - Frameless, always-on-top, never steals focus (WS_EX_NOACTIVATE)
  - True stadium/capsule geometry (border-radius = height / 2)
  - Soft floating drop shadow with sub-pixel anti-aliasing
  - Subtle top-lit glass rim highlight (Fluent 2 / macOS glassmorphic aesthetic)
  - Centered horizontally above the taskbar (leaves system tray completely unobstructed)
  - Responsive keyboard shortcut hint badge ([Esc] to finish)
  - State machine: IDLE → LISTENING → STREAMING → DONE/ERROR → IDLE
"""

import sys
import ctypes
from enum import Enum, auto

from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout
from PySide6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve,
    QPoint, QRect, QRectF
)
from PySide6.QtGui import (
    QPainter, QColor, QFont, QCursor, QGuiApplication,
    QPainterPath, QLinearGradient, QPen, QBrush
)

from ui.waveform import WaveformWidget


# Windows version detection for backdrop & font
IS_WINDOWS_11 = sys.platform == "win32" and hasattr(sys, "getwindowsversion") and sys.getwindowsversion().build >= 22000
UI_FONT = "Segoe UI Variable Text" if IS_WINDOWS_11 else "Segoe UI"

# ------------------------------------------------------------------ #
# State colours                                                        #
# ------------------------------------------------------------------ #

DOT_COLORS = {
    "idle":      QColor(0,   0,   0,   0),
    "listening": QColor(255, 69,  58,  255),   # #FF453A Coral Red
    "streaming": QColor(255, 159, 10,  255),   # #FF9F0A Amber
    "done":      QColor(48,  209, 88,  255),   # #30D158 Mint Green
    "error":     QColor(160, 160, 165, 200),   # Subtle Gray
}

# Capsule dimensions
PILL_W = 460
PILL_H = 48
SHADOW_PAD = 12   # Padding for soft diffused drop shadow
MARGIN = 18       # Distance above taskbar


class PillState(Enum):
    IDLE      = auto()
    LISTENING = auto()
    STREAMING = auto()
    DONE      = auto()
    ERROR     = auto()


class DotWidget(QWidget):
    """An 8px state dot with smooth breathing pulse during active listening."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(8, 8)
        self._color = DOT_COLORS["idle"]
        self._pulse_alpha = 255
        self._pulse_dir = -1

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(28)
        self._pulse_timer.timeout.connect(self._do_pulse)

    def set_state(self, state: str):
        self._color = DOT_COLORS.get(state, DOT_COLORS["idle"])
        if state == "listening":
            self._pulse_timer.start()
        else:
            self._pulse_timer.stop()
            self._pulse_alpha = 255
        self.update()

    def _do_pulse(self):
        self._pulse_alpha += self._pulse_dir * 7
        if self._pulse_alpha <= 70:
            self._pulse_dir = 1
        elif self._pulse_alpha >= 255:
            self._pulse_dir = -1
        self._pulse_alpha = max(70, min(255, self._pulse_alpha))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QColor(self._color)
        c.setAlpha(self._pulse_alpha if self._color != DOT_COLORS["idle"] else 0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(c)
        painter.drawEllipse(0, 0, 8, 8)
        painter.end()


class PillWindow(QWidget):
    """
    Frameless floating capsule positioned at bottom-center of active monitor.
    Features true capsule rounding, glassmorphic rim, and soft drop shadow.
    """

    def __init__(self):
        super().__init__()
        self._state = PillState.IDLE
        self._dwm_applied = False
        self._setup_window()
        self._build_ui()
        self._setup_animations()

    # ------------------------------------------------------------------ #
    # Window setup                                                         #
    # ------------------------------------------------------------------ #

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )

        # Translucent background enables custom anti-aliased capsule & drop shadow
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(PILL_W + SHADOW_PAD * 2, PILL_H + SHADOW_PAD * 2)

    def _build_ui(self):
        layout = QHBoxLayout(self)
        # Inset contents inside shadow margin
        layout.setContentsMargins(SHADOW_PAD + 16, SHADOW_PAD, SHADOW_PAD + 14, SHADOW_PAD)
        layout.setSpacing(10)

        # State dot
        self._dot = DotWidget(self)
        layout.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)

        # Status badge
        self._status_label = QLabel("Listening", self)
        font_status = QFont(UI_FONT, 10)
        font_status.setWeight(QFont.Weight.DemiBold)
        self._status_label.setFont(font_status)
        self._status_label.setStyleSheet("color: rgba(255, 255, 255, 0.70); background: transparent;")
        self._status_label.setFixedWidth(74)
        layout.addWidget(self._status_label, 0, Qt.AlignmentFlag.AlignVCenter)

        # Waveform audio bars
        self._waveform = WaveformWidget(self)
        layout.addWidget(self._waveform, 0, Qt.AlignmentFlag.AlignVCenter)

        # Transcript preview
        self._text_label = QLabel("", self)
        font_text = QFont(UI_FONT, 11)
        self._text_label.setFont(font_text)
        self._text_label.setStyleSheet("color: #F8FAFC; background: transparent;")
        self._text_label.setMaximumWidth(220)
        layout.addWidget(self._text_label, 1, Qt.AlignmentFlag.AlignVCenter)

        # Shortcut hint keycap badge on right edge
        self._hint_badge = QLabel("Esc", self)
        font_hint = QFont(UI_FONT, 8)
        font_hint.setWeight(QFont.Weight.Medium)
        self._hint_badge.setFont(font_hint)
        self._hint_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint_badge.setFixedSize(36, 20)
        self._hint_badge.setStyleSheet("""
            QLabel {
                color: rgba(255, 255, 255, 0.45);
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 5px;
            }
        """)
        layout.addWidget(self._hint_badge, 0, Qt.AlignmentFlag.AlignVCenter)

    def _apply_dwm(self):
        """Ensure window never steals focus via Win32 WS_EX_NOACTIVATE."""
        hwnd = int(self.winId())
        try:
            user32 = ctypes.windll.user32
            GWL_EXSTYLE = -20
            WS_EX_NOACTIVATE = 0x08000000
            ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style | WS_EX_NOACTIVATE)
        except Exception:
            pass

    def _recalculate_positions(self):
        """
        Dynamically calculate bottom-center position on the screen containing cursor.
        Keeps system tray and notification area completely unobstructed.
        """
        cursor_pos = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor_pos) or QGuiApplication.primaryScreen()
        if screen is not None:
            geom: QRect = screen.availableGeometry()
        else:
            geom: QRect = QRect(0, 0, 1920, 1080)

        # Centered horizontally above taskbar
        center_x = geom.left() + (geom.width() - self.width()) // 2
        bottom_y = geom.bottom() - self.height() - MARGIN

        self._shown_pos = QPoint(center_x, bottom_y)
        self._hidden_pos = QPoint(center_x, geom.bottom() + 30)

    def _setup_animations(self):
        self._recalculate_positions()

        self._slide_in = QPropertyAnimation(self, b"pos")
        self._slide_in.setDuration(240)
        self._slide_in.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._slide_out = QPropertyAnimation(self, b"pos")
        self._slide_out.setDuration(220)
        self._slide_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self._slide_out.finished.connect(self._on_slide_out_done)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def show_listening(self, subtitle: str = "Listening"):
        self._set_state(PillState.LISTENING)
        self._status_label.setText(subtitle)
        self._text_label.setText("")
        self._hint_badge.setText("Esc")
        self._hint_badge.show()
        self._slide_to(show=True)
        if not self._dwm_applied:
            self._apply_dwm()
            self._dwm_applied = True

    def update_partial(self, text: str):
        if self._state in (PillState.LISTENING, PillState.STREAMING):
            self._set_state(PillState.STREAMING)
            preview = text[-34:] if len(text) > 34 else text
            self._text_label.setText(preview)

    def notify_sentence_injected(self, text: str):
        """
        Called in continuous dictation when a sentence is injected into the active app.
        Confirms injection on the pill while keeping it listening seamlessly.
        """
        if self._state != PillState.IDLE:
            self._set_state(PillState.LISTENING)
            preview = text[-34:] if len(text) > 34 else text
            self._text_label.setText(preview)
            QTimer.singleShot(1400, self._clear_preview_if_listening)

    def notify_deleted(self, label: str = "Deleted ⌫"):
        """
        Called when a voice deletion command executes.
        Displays deletion confirmation on the pill while keeping it listening seamlessly.
        """
        if self._state != PillState.IDLE:
            self._set_state(PillState.LISTENING)
            self._text_label.setText(label)
            QTimer.singleShot(1400, self._clear_preview_if_listening)

    def _clear_preview_if_listening(self):
        if self._state == PillState.LISTENING:
            self._text_label.setText("")

    def show_done(self, text: str):
        self._set_state(PillState.DONE)
        preview = text[-34:] if len(text) > 34 else text
        self._text_label.setText(preview)
        self._hint_badge.hide()
        QTimer.singleShot(750, self._slide_to_hide)

    def show_error(self, msg: str = "No speech detected"):
        self._set_state(PillState.ERROR)
        self._text_label.setText(msg)
        self._hint_badge.hide()
        QTimer.singleShot(1500, self._slide_to_hide)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _set_state(self, state: PillState):
        self._state = state
        name = state.name.lower()
        self._dot.set_state(name)
        self._waveform.set_active(state == PillState.STREAMING)

        labels = {
            PillState.LISTENING: "Listening",
            PillState.STREAMING: "Streaming",
            PillState.DONE:      "Done ✓",
            PillState.ERROR:     "No speech",
        }
        self._status_label.setText(labels.get(state, ""))

    def _slide_to(self, show: bool):
        anim = self._slide_in if show else self._slide_out
        if show:
            self._recalculate_positions()
            self.move(self._hidden_pos)
            self.show()
        anim.setStartValue(self.pos())
        anim.setEndValue(self._shown_pos if show else self._hidden_pos)
        anim.start()

    def _slide_to_hide(self):
        self._slide_to(show=False)

    def _on_slide_out_done(self):
        self.hide()
        self._set_state(PillState.IDLE)

    def paintEvent(self, event):
        """
        Render true capsule geometry with multi-layer diffused shadow
        and glassmorphic top-lit rim highlight.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Capsule boundary
        capsule_rect = QRectF(
            SHADOW_PAD,
            SHADOW_PAD,
            PILL_W,
            PILL_H
        )
        radius = PILL_H / 2.0  # Perfect stadium/capsule curve (24px)

        # 1. Multi-layer soft drop shadow (simulating diffused ambient elevation)
        shadow_steps = [
            (6, 4, QColor(0, 0, 0, 16)),
            (4, 3, QColor(0, 0, 0, 28)),
            (2, 2, QColor(0, 0, 0, 48)),
            (1, 1, QColor(0, 0, 0, 70)),
        ]
        for pad, y_off, col in shadow_steps:
            s_rect = QRectF(
                capsule_rect.x() - pad,
                capsule_rect.y() - pad + y_off,
                capsule_rect.width() + pad * 2,
                capsule_rect.height() + pad * 2
            )
            s_path = QPainterPath()
            s_path.addRoundedRect(s_rect, radius + pad, radius + pad)
            painter.fillPath(s_path, col)

        # 2. Main capsule body (Deep Obsidian Glass)
        capsule_path = QPainterPath()
        capsule_path.addRoundedRect(capsule_rect, radius, radius)
        body_color = QColor(18, 18, 22, 240)  # Sleek dark acrylic tint
        painter.fillPath(capsule_path, body_color)

        # 3. Glassmorphic rim highlight (subtle top-lit gradient)
        rim_gradient = QLinearGradient(0, capsule_rect.top(), 0, capsule_rect.bottom())
        rim_gradient.setColorAt(0.0, QColor(255, 255, 255, 50))  # Top specular edge
        rim_gradient.setColorAt(0.4, QColor(255, 255, 255, 22))
        rim_gradient.setColorAt(1.0, QColor(255, 255, 255, 10))  # Muted bottom rim

        painter.setPen(QPen(QBrush(rim_gradient), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(capsule_rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

        painter.end()
