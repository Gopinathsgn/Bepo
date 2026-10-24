"""
about_dialog.py
Credits and About screen for Bepo.
Displays author attribution (Gopinath), GitHub link, and GPLv3 license notices.
"""

import os
import sys
import ctypes
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QFont, QPixmap, QIcon, QDesktopServices

from version import __version__

IS_WINDOWS_11 = sys.platform == "win32" and hasattr(sys, "getwindowsversion") and sys.getwindowsversion().build >= 22000
UI_FONT = "Segoe UI Variable Text" if IS_WINDOWS_11 else "Segoe UI"

DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_SYSTEMBACKDROP_TYPE      = 38
DWMWCP_ROUND                   = 2
DWMSBT_MAINWINDOW              = 2   # Mica


class AboutDialog(QDialog):
    """
    Credits and About window.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_window()
        self._build_ui()

    def _setup_window(self):
        self.setWindowTitle("About Bepo")
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowCloseButtonHint
        )
        self.setFixedSize(440, 360)
        self.setStyleSheet("""
            QDialog {
                background: #1C1C1E;
                color: #F8FAFC;
            }
        """)

        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)

        # Header Row: Icon + Title & Version
        header = QHBoxLayout()
        header.setSpacing(14)

        icon_label = QLabel()
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "icon.png")
        if os.path.exists(icon_path):
            pix = QPixmap(icon_path).scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            icon_label.setPixmap(pix)
        else:
            icon_label.setText("🎙️")
            icon_label.setFont(QFont("Segoe UI Emoji", 32))
        header.addWidget(icon_label)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_lbl = QLabel("Bepo")
        title_lbl.setFont(QFont(UI_FONT, 20, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: #FFFFFF; background: transparent;")
        title_col.addWidget(title_lbl)

        version_lbl = QLabel(f"Version {__version__} • 100% On-Device Voice Typing")
        version_lbl.setFont(QFont(UI_FONT, 10))
        version_lbl.setStyleSheet("color: rgba(255, 255, 255, 0.6); background: transparent;")
        title_col.addWidget(version_lbl)

        header.addLayout(title_col)
        header.addStretch()
        layout.addLayout(header)

        # Divider line
        divider = QLabel()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: rgba(255, 255, 255, 0.1);")
        layout.addWidget(divider)

        # Author Credits
        credits_card = QVBoxLayout()
        credits_card.setSpacing(6)

        author_heading = QLabel("Created & Developed by")
        author_heading.setFont(QFont(UI_FONT, 10, QFont.Weight.Medium))
        author_heading.setStyleSheet("color: rgba(255, 255, 255, 0.55); background: transparent;")
        credits_card.addWidget(author_heading)

        author_name = QLabel("Gopinath")
        author_name.setFont(QFont(UI_FONT, 16, QFont.Weight.Bold))
        author_name.setStyleSheet("color: #38BDF8; background: transparent;")  # Sky blue accent
        credits_card.addWidget(author_name)

        github_link = QLabel('<a href="https://github.com/Gopinathsgn" style="color: #60A5FA; text-decoration: none;">github.com/Gopinathsgn</a>')
        github_link.setFont(QFont(UI_FONT, 11))
        github_link.setOpenExternalLinks(True)
        github_link.setStyleSheet("background: transparent;")
        credits_card.addWidget(github_link)

        layout.addLayout(credits_card)

        # License notice
        license_box = QLabel(
            "Copyright \u00a9 2026 Gopinath. Licensed under the GNU General Public License v3.0 (GPLv3).\n"
            "Speech recognition by Moonshine AI (MIT). Please keep the original copyright "
            "and license notices when redistributing or modifying Bepo."
        )
        license_box.setFont(QFont(UI_FONT, 9))
        license_box.setWordWrap(True)
        license_box.setStyleSheet("""
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 8px;
            padding: 10px;
            color: rgba(255, 255, 255, 0.7);
        """)
        layout.addWidget(license_box)

        layout.addStretch()

        # Action Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        github_btn = QPushButton("Open GitHub Profile")
        github_btn.setFont(QFont(UI_FONT, 10, QFont.Weight.Medium))
        github_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.1);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 6px;
                padding: 6px 14px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.18);
            }
        """)
        github_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/Gopinathsgn")))
        btn_row.addWidget(github_btn)

        btn_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setFont(QFont(UI_FONT, 10))
        close_btn.setStyleSheet("""
            QPushButton {
                background: #2563EB;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 6px 18px;
            }
            QPushButton:hover {
                background: #1D4ED8;
            }
        """)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

    def showEvent(self, event):
        super().showEvent(event)
        # Apply Windows 11 Rounded Corners & Backdrop
        if IS_WINDOWS_11 and sys.platform == "win32":
            try:
                hwnd = int(self.winId())
                corner_pref = ctypes.c_int(DWMWCP_ROUND)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd,
                    DWMWA_WINDOW_CORNER_PREFERENCE,
                    ctypes.byref(corner_pref),
                    ctypes.sizeof(corner_pref)
                )
                backdrop_pref = ctypes.c_int(DWMSBT_MAINWINDOW)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd,
                    DWMWA_SYSTEMBACKDROP_TYPE,
                    ctypes.byref(backdrop_pref),
                    ctypes.sizeof(backdrop_pref)
                )
            except Exception:
                pass
