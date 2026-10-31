"""
smooth_scroll.py
A QScrollArea whose mouse wheel glides instead of jumping.

Qt moves a plain scroll area by a fixed step per wheel notch, instantly, which looks like stutter on
long pages. Here every notch sets a new target and the scroll bar eases towards it. Notches that
arrive while it is still moving add up, so a fast spin covers more ground and stays continuous.
Touchpads (which already send pixel-precise deltas), the scroll bar itself and the keyboard keep
Qt's own behaviour.
"""

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QAbstractAnimation
from PySide6.QtWidgets import QScrollArea

NOTCH_PIXELS = 90       # distance for one wheel notch (Qt's default is 60, applied instantly)
DURATION_MS = 240


class SmoothScrollArea(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        bar = self.verticalScrollBar()
        self._target = 0
        self._animation = QPropertyAnimation(bar, b"value", self)
        self._animation.setDuration(DURATION_MS)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        bar.sliderPressed.connect(self._animation.stop)     # dragging the bar takes over
        bar.valueChanged.connect(self._follow_bar)

    def _moving(self) -> bool:
        return self._animation.state() == QAbstractAnimation.State.Running

    def _follow_bar(self, value: int) -> None:
        """Keep the target in step when the bar is moved by anything but our own animation."""
        if not self._moving():
            self._target = value

    def wheelEvent(self, event):
        bar = self.verticalScrollBar()
        notches = event.angleDelta().y() / 120
        if event.pixelDelta().y() or not notches or bar.maximum() == 0:
            super().wheelEvent(event)           # touchpad, sideways wheel, or nothing to scroll
            return

        start = self._target if self._moving() else bar.value()
        self._target = max(0, min(bar.maximum(), start - round(notches * NOTCH_PIXELS)))
        self._animation.stop()
        if self._target != bar.value():
            self._animation.setStartValue(bar.value())
            self._animation.setEndValue(self._target)
            self._animation.start()
        event.accept()
