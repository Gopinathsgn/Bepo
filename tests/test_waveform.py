"""Waveform indicator: bars must settle back to idle instead of freezing half-collapsed."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.waveform import IDLE_HEIGHT, WaveformWidget

_app = QApplication.instance() or QApplication([])


class WaveformTests(unittest.TestCase):
    def test_bars_settle_to_idle_and_the_timer_stops(self):
        w = WaveformWidget()
        self.addCleanup(w.deleteLater)
        w.set_active(True)
        for _ in range(12):
            w._tick()
        self.assertTrue(any(h > IDLE_HEIGHT + 3 for h in w._heights))
        w.set_active(False)
        self.assertTrue(w._timer.isActive())          # keeps animating until settled
        for _ in range(40):
            w._tick()
        self.assertEqual(w._heights, [IDLE_HEIGHT] * len(w._heights))
        self.assertFalse(w._timer.isActive())


if __name__ == "__main__":
    unittest.main()
