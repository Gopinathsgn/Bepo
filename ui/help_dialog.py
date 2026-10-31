"""
help_dialog.py
The Bepo Help window (tray menu > Help): every shortcut and spoken command, one card per topic,
and a "Try it" box where the user can dictate without risking text in a real document.

The content comes from core/guide.py; the shortcuts and the on/off state of each feature come from
the running app via `set_state()`, so the window shows the user's own shortcuts and says so when a
feature is switched off. Nothing here touches the running app.
"""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit,
    QWidget, QFrame,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QGuiApplication

from core import guide
from ui.settings_dialog import stylesheet
from ui.smooth_scroll import SmoothScrollArea

_ASSETS = Path(__file__).resolve().parent.parent / "assets"

_QSS = """
QLabel#say { font-size: 14px; font-weight: 700; color: #FFFFFF; }
QLabel#keys { font-size: 13px; font-weight: 700; color: #60A5FA; }
QLabel#keysOff { font-size: 13px; font-weight: 700; color: rgba(255,255,255,0.35); }
QLabel#example { font-size: 12px; color: #93C5FD; }
QLabel#block { font-size: 12px; background: rgba(0,0,0,0.25); border-radius: 6px; padding: 8px 10px; }
QFrame#sep { background: rgba(255,255,255,0.08); border: none; max-height: 1px; min-height: 1px; }
QPlainTextEdit#tryBox { font-size: 14px; }
"""

KEYS_COLUMN_WIDTH = 150


@dataclass(frozen=True)
class HelpState:
    """What the Help window needs to know about the running app."""
    config: dict
    toggle: str = ""       # shortcut labels as the app has them; "" = disabled
    ptt: str = ""
    undo: str = ""


class HelpDialog(QDialog):
    def __init__(self, state: HelpState, parent=None):
        super().__init__(parent)
        self._state = state
        self.setWindowTitle("Bepo Help")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)
        self.setStyleSheet(stylesheet() + _QSS)
        icon_path = _ASSETS / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = SmoothScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self._scroll, 1)

        outer.addWidget(self._build_try_it())
        self.set_state(state)
        self._size_to_screen()

    # ------------------------------------------------------------------ #
    # Content                                                              #
    # ------------------------------------------------------------------ #

    def set_state(self, state: HelpState) -> None:
        """(Re)build the cards, e.g. after the user changed a shortcut or a setting."""
        self._state = state
        position = self._scroll.verticalScrollBar().value()

        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(24, 22, 24, 12)
        col.setSpacing(14)

        title = QLabel("Help")
        title.setObjectName("title")
        col.addWidget(title)
        col.addWidget(self._hint("Everything you can press and say. Try any of it in the box at the bottom."))

        col.addWidget(self._shortcuts_card())
        for topic in guide.TOPICS:
            col.addWidget(self._topic_card(topic))
        col.addStretch(1)

        self._scroll.setWidget(body)         # replaces (and deletes) the previous body
        self._scroll.verticalScrollBar().setValue(position)
        self._update_try_hint()

    @staticmethod
    def _hint(text: str, name: str = "hint") -> QLabel:
        label = QLabel(text)
        label.setObjectName(name)
        label.setWordWrap(True)
        return label

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
    def _separator() -> QFrame:
        line = QFrame()
        line.setObjectName("sep")
        return line

    def _shortcuts_card(self) -> QFrame:
        frame, lay = self._card("Start & stop")
        s = self._state
        rows = guide.shortcuts(s.toggle, s.ptt, s.undo, s.config.get("esc_to_finish", True))
        for index, row in enumerate(rows):
            if index:
                lay.addWidget(self._separator())
            line = QHBoxLayout()
            line.setSpacing(12)
            keys = QLabel(row.keys)
            keys.setObjectName("keys" if row.enabled else "keysOff")
            keys.setWordWrap(True)
            keys.setFixedWidth(KEYS_COLUMN_WIDTH)
            keys.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            line.addWidget(keys)
            does = QLabel(row.does)
            does.setWordWrap(True)
            line.addWidget(does, 1)
            lay.addLayout(line)
        lay.addWidget(self._hint(
            "You can also start and stop from the tray icon. Change any shortcut in Settings."))
        return frame

    def _topic_card(self, topic: guide.Topic) -> QFrame:
        frame, lay = self._card(topic.title)
        lay.addWidget(self._hint(topic.intro))
        reason = guide.disabled_reason(topic, self._state.config)
        if reason:
            lay.addWidget(self._hint(reason, "warn"))

        for entry in topic.entries:
            lay.addWidget(self._separator())
            lay.addWidget(self._entry(entry, topic.key))

        if topic.example:
            utterances, typed = topic.example
            lay.addWidget(self._separator())
            lay.addWidget(self._hint("Example"))
            lay.addWidget(self._block("You say:   " + "  ".join(f"“{u}”" for u in utterances)))
            lay.addWidget(self._block("Bepo types:\n" + typed))
        return frame

    def _entry(self, entry: guide.Entry, topic_key: str) -> QWidget:
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        say = QLabel("   or   ".join(f"“{p}”" for p in entry.phrases))
        say.setObjectName("say")
        say.setWordWrap(True)
        col.addWidget(say)
        does = QLabel(entry.does)
        does.setWordWrap(True)
        col.addWidget(does)
        if entry.spoken:
            example = QLabel(f"“{entry.spoken}”  →  {entry.typed}")
            example.setObjectName("example")
            example.setWordWrap(True)
            col.addWidget(example)
        return box

    def _block(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("block")
        label.setWordWrap(True)
        return label

    # ------------------------------------------------------------------ #
    # Try it                                                               #
    # ------------------------------------------------------------------ #

    def _build_try_it(self) -> QFrame:
        footer = QFrame()
        footer.setObjectName("footer")
        footer.setStyleSheet("QFrame#footer { background: #1C1C1E; border-top: 1px solid rgba(255,255,255,0.08); }")
        lay = QVBoxLayout(footer)
        lay.setContentsMargins(24, 12, 24, 14)
        lay.setSpacing(8)

        heading = QLabel("TRY IT")
        heading.setObjectName("sectionTitle")
        lay.addWidget(heading)
        self._try_hint = self._hint("")
        lay.addWidget(self._try_hint)

        self.try_box = QPlainTextEdit()
        self.try_box.setObjectName("tryBox")
        self.try_box.setPlaceholderText("Click here, then dictate. Nothing leaves this box.")
        self.try_box.setMinimumHeight(56)
        self.try_box.setMaximumHeight(80)
        lay.addWidget(self.try_box)

        buttons = QHBoxLayout()
        clear = QPushButton("Clear")
        clear.setObjectName("link")
        clear.clicked.connect(self.try_box.clear)
        buttons.addWidget(clear)
        buttons.addStretch(1)
        close = QPushButton("Close")
        close.setObjectName("primary")
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        lay.addLayout(buttons)
        return footer

    def _update_try_hint(self) -> None:
        s = self._state
        if s.toggle:
            start = f"press {s.toggle}"
        elif s.ptt:
            start = f"hold {s.ptt}"
        else:
            start = "start dictation from the tray icon"
        self._try_hint.setText(
            f"Click in the box, {start} and say: “Hello world. Scratch that. Good morning.”")

    def keyPressEvent(self, event):
        # Esc finishes a dictation; it must not also close this window while the user is trying it out.
        if event.key() == Qt.Key.Key_Escape:
            event.accept()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------ #
    # Size                                                                 #
    # ------------------------------------------------------------------ #

    def _size_to_screen(self):
        screen = QGuiApplication.primaryScreen()
        available = screen.availableGeometry().height() if screen else 900
        self.setFixedWidth(600)
        self.resize(600, min(780, max(480, available - 80)))
        self.setMinimumHeight(420)
