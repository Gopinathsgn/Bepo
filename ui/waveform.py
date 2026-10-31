"""
waveform.py
Animated waveform bar widget shown while speech is being recognised.
7 vertical bars with smooth height transitions. The bar motion is a simulated
speech-like animation until the microphone loudness is wired in with set_level(): once levels
arrive (and set_meter(True) is on) the bars follow what the microphone really hears, so the user
can see at a glance whether they are being heard.
"""

import random
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtGui import QPainter, QColor


BAR_COUNT  = 7
BAR_WIDTH  = 3
BAR_GAP    = 3
BAR_COLOR  = QColor(255, 255, 255, 180)
MIN_HEIGHT = 4
MAX_HEIGHT = 22
IDLE_HEIGHT = 4
METER_TTL_TICKS = 20      # ticks (1 s) without a level before falling back to the simulation


class WaveformWidget(QWidget):
    """
    Renders 7 animated bars as a "speech is being recognised" indicator.
    Optionally call set_level(0..1) with a real RMS level to drive the animation.
    Call set_active(False) to collapse bars to idle state.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._heights = [IDLE_HEIGHT] * BAR_COUNT
        self._target_heights = [IDLE_HEIGHT] * BAR_COUNT
        self._level = 0.0
        self._active = False
        self._meter_on = False
        self._meter_ttl = 0

        w = BAR_COUNT * BAR_WIDTH + (BAR_COUNT - 1) * BAR_GAP
        self.setFixedSize(w, MAX_HEIGHT)

        self._timer = QTimer(self)
        self._timer.setInterval(50)   # 20 fps
        self._timer.timeout.connect(self._tick)

    def set_active(self, active: bool):
        self._active = active
        if active:
            self._tick_count = 0
            self._randomize_targets()
            self._timer.start()
        else:
            # Keep animating until the bars have settled back to idle (_tick stops the timer then)
            self._target_heights = [IDLE_HEIGHT] * BAR_COUNT
            self._timer.start()

    def set_meter(self, on: bool):
        """Follow the real microphone level (even before speech is recognised) while `on`."""
        self._meter_on = on
        if not on:
            self._meter_ttl = 0
            if not self._active:
                self._target_heights = [IDLE_HEIGHT] * BAR_COUNT
                self._timer.start()

    def set_level(self, level: float):
        """level: 0..1 from audio RMS"""
        self._level = max(0.0, min(1.0, level))
        self._meter_ttl = METER_TTL_TICKS
        if self._active or self._meter_on:
            self._randomize_targets()
            self._timer.start()

    def _randomize_targets(self):
        # Real microphone level when one is arriving, otherwise a speech-like simulation
        if self._meter_ttl > 0:
            effective_level = self._level
        else:
            effective_level = self._level if self._level > 0.05 else random.uniform(0.35, 0.85)
        base = MIN_HEIGHT + effective_level * (MAX_HEIGHT - MIN_HEIGHT)
        jitter_scale = effective_level if self._meter_ttl > 0 else 1.0     # silence stays flat
        for i in range(BAR_COUNT):
            # Center bars tend to be higher than edges for natural voice waveform look
            edge_factor = 1.0 - abs(i - (BAR_COUNT // 2)) * 0.15
            jitter = random.uniform(-0.2, 0.2) * (MAX_HEIGHT - MIN_HEIGHT) * jitter_scale
            h = max(MIN_HEIGHT, min(MAX_HEIGHT, (base + jitter) * edge_factor))
            self._target_heights[i] = h

    def _tick(self):
        if self._meter_ttl > 0:
            self._meter_ttl -= 1
            if self._meter_ttl == 0 and not self._active:
                self._target_heights = [IDLE_HEIGHT] * BAR_COUNT
        if self._active:
            self._tick_count = getattr(self, "_tick_count", 0) + 1
            # Periodically refresh speech waveform targets
            if self._tick_count % 3 == 0:
                self._randomize_targets()

        changed = False
        for i in range(BAR_COUNT):
            diff = self._target_heights[i] - self._heights[i]
            if abs(diff) > 0.5:
                self._heights[i] += diff * 0.45   # smooth lerp
                changed = True
            elif self._heights[i] != self._target_heights[i]:
                self._heights[i] = self._target_heights[i]
                changed = True
        if changed:
            self.update()
        elif not self._active and not (self._meter_on and self._meter_ttl > 0):
            self._timer.stop()   # fully collapsed to idle

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(BAR_COLOR)

        widget_h = self.height()
        x = 0
        for i in range(BAR_COUNT):
            h = int(self._heights[i])
            y = (widget_h - h) // 2
            painter.drawRoundedRect(QRect(x, y, BAR_WIDTH, h), 2, 2)
            x += BAR_WIDTH + BAR_GAP
        painter.end()
