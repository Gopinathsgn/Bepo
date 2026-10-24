"""
setup_screen.py
Premium first-run setup screen.
Downloads the Moonshine small streaming model with a live progress bar.
Uses PySide6 with DWM Acrylic + frameless window for a premium Win11 look.
"""

import os
import re
import ctypes

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton
)
from PySide6.QtCore import Qt, QTimer, Signal, QThread, Slot
from PySide6.QtGui import QFont, QColor, QPainter, QPixmap, QIcon

from setup.model_downloader import download_model, get_model_size_mb, MODELS, DEFAULT_MODEL


WINDOW_WIDTH = 480
MIN_WINDOW_HEIGHT = 300
MAX_ERROR_CHARS = 200          # keep a pathological error message from filling the screen
_ZWSP = "​"               # zero-width space: an invisible line-break opportunity


def breakable(text: str, limit: int = MAX_ERROR_CHARS) -> str:
    """
    Make arbitrary error text safe for a word-wrapped QLabel.

    Qt only wraps at spaces, so one long unbroken token (a URL, a file path, an exception repr)
    forces the label wider than the window and gets cropped. This shortens the text, collapses
    whitespace, and inserts invisible break opportunities after punctuation and inside long runs.
    """
    text = " ".join(str(text).split())
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    text = re.sub(r"([/\\._\-:,;()<>=?&])", "\\1" + _ZWSP, text)
    return re.sub(r"(\S{20})(?=\S)", "\\1" + _ZWSP, text)

DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_SYSTEMBACKDROP_TYPE      = 38
DWMWCP_ROUND                   = 2
DWMSBT_MAINWINDOW              = 2   # Mica — suits a setup window


# ------------------------------------------------------------------ #
# Download worker thread                                               #
# ------------------------------------------------------------------ #

class DownloadThread(QThread):
    progress  = Signal(int, str)   # (percent 0-100, current_file)
    finished  = Signal()
    error     = Signal(str)

    def __init__(self, model_key: str = DEFAULT_MODEL, parent=None):
        super().__init__(parent)
        self._model_key = model_key

    def run(self):
        try:
            def on_progress(fraction: float, filename: str = ""):
                pct = min(100, int(fraction * 100))
                fname = filename.split("/")[-1] if filename else ""
                self.progress.emit(pct, fname)

            download_model(on_progress, self._model_key)
            self.finished.emit()
        except Exception as exc:
            self.error.emit(str(exc))


# ------------------------------------------------------------------ #
# Setup screen window                                                  #
# ------------------------------------------------------------------ #

class SetupScreen(QWidget):
    """
    First-run setup screen. Shows model download progress.
    Emits `setup_complete` when ready.
    """

    setup_complete = Signal()

    def __init__(self, model_key: str = DEFAULT_MODEL):
        super().__init__()
        self._model_key = model_key
        self._download_thread: DownloadThread | None = None
        self._finished = False
        self._setup_window()
        self._build_ui()
        # NOTE: DWM is applied in show_and_start(), after the window is visible

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        # Solid dark background — DWM Acrylic/Mica is composited on top after show()
        self.setStyleSheet("background: #1C1C1E;")
        self.setFixedWidth(WINDOW_WIDTH)

    def _fit_to_content(self):
        """
        Size the window to what it currently shows (all text wraps), then centre it.
        Called after every state change so nothing is ever cropped, whatever the error text.
        """
        layout = self.layout()
        layout.activate()
        height = max(MIN_WINDOW_HEIGHT, layout.totalHeightForWidth(WINDOW_WIDTH))
        self.setFixedSize(WINDOW_WIDTH, height)
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - WINDOW_WIDTH // 2, screen.center().y() - height // 2)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 32, 36, 28)
        layout.setSpacing(14)

        # App icon + title
        title_row = QHBoxLayout()
        title_row.setSpacing(12)

        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "icon.png")
        icon_label = QLabel()
        icon_label.setStyleSheet("background: transparent;")
        if os.path.exists(icon_path):
            pix = QPixmap(icon_path).scaled(36, 36, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            icon_label.setPixmap(pix)
        else:
            icon_label.setText("🎙️")
            icon_label.setFont(QFont("Segoe UI Emoji", 28))
        title_row.addWidget(icon_label)

        title = QLabel("Bepo")
        title.setFont(QFont("Segoe UI Variable", 22, QFont.Weight.Bold))
        title.setStyleSheet("color: white; background: transparent;")
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)

        # Subtitle
        subtitle = QLabel("Blazing fast voice typing for Windows")
        subtitle.setFont(QFont("Segoe UI Variable", 11))
        subtitle.setStyleSheet("color: rgba(255,255,255,0.65); background: transparent;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        layout.addSpacing(8)

        # Download info
        self._info_label = QLabel(
            f"Downloading Moonshine {MODELS[self._model_key].key} speech model "
            f"(~{get_model_size_mb(self._model_key)} MB)\n"
            "This is a one-time download. The app works offline after this."
        )
        self._info_label.setFont(QFont("Segoe UI Variable", 10))
        self._info_label.setStyleSheet("color: rgba(255,255,255,0.5); background: transparent;")
        self._info_label.setWordWrap(True)
        layout.addWidget(self._info_label)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(6)
        self._progress.setStyleSheet("""
            QProgressBar {
                background: rgba(255,255,255,0.12);
                border-radius: 3px;
                border: none;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #FF9F0A, stop:1 #30D158);
                border-radius: 3px;
            }
        """)
        layout.addWidget(self._progress)

        # File + percent row
        pct_row = QHBoxLayout()
        self._file_label = QLabel("Preparing download...")
        self._file_label.setFont(QFont("Segoe UI Variable", 9))
        self._file_label.setStyleSheet("color: rgba(255,255,255,0.4); background: transparent;")
        pct_row.addWidget(self._file_label)
        pct_row.addStretch()
        self._pct_label = QLabel("0%")
        self._pct_label.setFont(QFont("Segoe UI Variable", 9, QFont.Weight.Medium))
        self._pct_label.setStyleSheet("color: rgba(255,255,255,0.6); background: transparent;")
        pct_row.addWidget(self._pct_label)
        layout.addLayout(pct_row)

        layout.addStretch()

        # Status / complete message
        self._status_label = QLabel("")
        self._status_label.setFont(QFont("Segoe UI Variable", 11))
        self._status_label.setStyleSheet("color: #30D158; background: transparent;")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        # Error details (technical message), small and wrapped so long text is never cropped
        self._detail_label = QLabel("")
        self._detail_label.setFont(QFont("Segoe UI Variable", 9))
        self._detail_label.setStyleSheet("color: rgba(255,255,255,0.55); background: transparent;")
        self._detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detail_label.setWordWrap(True)
        self._detail_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._detail_label.hide()
        layout.addWidget(self._detail_label)

        # Retry / Quit buttons (only shown if the download fails)
        self._button_row = QWidget()
        self._button_row.setStyleSheet("background: transparent;")
        btn_layout = QHBoxLayout(self._button_row)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(10)
        btn_layout.addStretch()
        self._quit_btn = QPushButton("Quit")
        self._retry_btn = QPushButton("Retry")
        for btn, bg, hover in ((self._quit_btn, "rgba(255,255,255,0.12)", "rgba(255,255,255,0.2)"),
                               (self._retry_btn, "#2563EB", "#1D4ED8")):
            btn.setFont(QFont("Segoe UI Variable", 10))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumSize(96, 32)
            btn.setStyleSheet(
                f"QPushButton {{ background: {bg}; color: white; border: none; "
                f"border-radius: 6px; padding: 6px 18px; }}"
                f"QPushButton:hover {{ background: {hover}; }}"
            )
            btn_layout.addWidget(btn)
        btn_layout.addStretch()
        self._quit_btn.clicked.connect(QApplication.quit)
        self._retry_btn.clicked.connect(self.start_download)
        self._button_row.hide()
        layout.addWidget(self._button_row)

        # Author attribution
        credits_lbl = QLabel('Created by <a href="https://github.com/Gopinathsgn" style="color: #60A5FA; text-decoration: none;">Gopinath</a>')
        credits_lbl.setFont(QFont("Segoe UI Variable", 9))
        credits_lbl.setOpenExternalLinks(True)
        credits_lbl.setStyleSheet("color: rgba(255,255,255,0.45); background: transparent;")
        credits_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(credits_lbl)

        self._fit_to_content()

    def _apply_dwm(self):
        """Apply DWM rounded corners + Mica backdrop. Called after show()."""
        hwnd = int(self.winId())
        try:
            dwmapi = ctypes.windll.dwmapi
            pref = ctypes.c_int(DWMWCP_ROUND)
            dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(pref), ctypes.sizeof(pref)
            )
            backdrop = ctypes.c_int(DWMSBT_MAINWINDOW)
            dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_SYSTEMBACKDROP_TYPE,
                ctypes.byref(backdrop), ctypes.sizeof(backdrop)
            )
        except Exception:
            pass  # graceful fallback — solid dark bg still shows

    def show_and_start(self):
        """Show the window, apply DWM effects, then begin download."""
        self.show()
        self._apply_dwm()
        self.start_download()

    def start_download(self):
        """Begin (or retry) the model download in a background thread."""
        if self._download_thread is not None:
            self._download_thread.wait(2000)   # let a failed attempt fully wind down
        self._button_row.hide()
        self._detail_label.hide()
        self._status_label.setText("")
        self._status_label.setStyleSheet("color: #30D158; background: transparent;")
        self._progress.setValue(0)
        self._pct_label.setText("0%")
        self._file_label.setText("Preparing download...")
        self._fit_to_content()
        self._download_thread = DownloadThread(self._model_key)
        self._download_thread.progress.connect(self._on_progress)
        self._download_thread.finished.connect(self._on_finished)
        self._download_thread.error.connect(self._on_error)
        self._download_thread.start()

    @Slot(int, str)
    def _on_progress(self, pct: int, filename: str):
        self._progress.setValue(pct)
        self._pct_label.setText(f"{pct}%")
        if filename:
            self._file_label.setText(filename)

    @Slot()
    def _on_finished(self):
        self._progress.setValue(100)
        self._pct_label.setText("100%")
        self._status_label.setText("✅  You're all set! Starting Bepo...")
        self._fit_to_content()
        QTimer.singleShot(2000, self._complete)

    @Slot(str)
    def _on_error(self, msg: str):
        detail = breakable(msg)
        self._status_label.setStyleSheet("color: #FF453A; background: transparent;")
        self._status_label.setText("❌  Download failed")
        self._detail_label.setText(
            "Check your internet connection and try again."
            + (f"\n{detail}" if detail else "")
        )
        self._detail_label.show()
        self._button_row.show()
        self._fit_to_content()

    def _complete(self):
        self._finished = True
        self.hide()
        self.setup_complete.emit()

    def closeEvent(self, event):
        """Closing the setup window before it finishes (Alt+F4) exits the app instead of
        leaving an invisible background process that blocks the next launch."""
        if not self._finished:
            QApplication.quit()
        super().closeEvent(event)

    def paintEvent(self, event):
        """Draw subtle border over the solid background."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(0, 0, 0, 0))  # transparent fill — bg handled by stylesheet
        painter.setPen(QColor(255, 255, 255, 18))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 16, 16)
        painter.end()
