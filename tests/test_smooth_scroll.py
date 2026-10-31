"""ui/smooth_scroll.py: the wheel eases towards a target instead of jumping, and the Help/Settings pages use it."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QVBoxLayout, QWidget

from ui import smooth_scroll
from ui.smooth_scroll import SmoothScrollArea

_app = QApplication.instance() or QApplication([])


def wheel(area, notches=0.0, pixels=0):
    """A mouse-wheel event, or a touchpad one when `pixels` is given, over the middle of `area`."""
    centre = QPointF(area.viewport().rect().center())
    event = QWheelEvent(centre, area.viewport().mapToGlobal(centre),
                        QPoint(0, pixels), QPoint(0, int(notches * 120)),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.ScrollUpdate if pixels else Qt.ScrollPhase.NoScrollPhase, False)
    _app.sendEvent(area.viewport(), event)
    return event


class SmoothScrollTests(unittest.TestCase):
    def make(self, cls=SmoothScrollArea):
        area = cls()
        body = QWidget()
        col = QVBoxLayout(body)
        for i in range(80):
            col.addWidget(QLabel(f"row {i}"))
        area.setWidget(body)
        area.setWidgetResizable(True)
        area.resize(300, 300)
        area.show()
        self.addCleanup(area.deleteLater)
        _app.processEvents()
        self.assertGreater(area.verticalScrollBar().maximum(), 500)
        return area

    def test_a_wheel_notch_glides_to_its_target_instead_of_jumping(self):
        area = self.make()
        bar = area.verticalScrollBar()
        wheel(area, notches=-1)                              # one notch down
        self.assertLess(bar.value(), smooth_scroll.NOTCH_PIXELS, "jumped the whole way at once")
        QTest.qWait(smooth_scroll.DURATION_MS + 150)
        self.assertEqual(bar.value(), smooth_scroll.NOTCH_PIXELS)

    def test_notches_in_quick_succession_add_up(self):
        area = self.make()
        for _ in range(4):
            wheel(area, notches=-1)
        QTest.qWait(smooth_scroll.DURATION_MS + 150)
        self.assertEqual(area.verticalScrollBar().value(), 4 * smooth_scroll.NOTCH_PIXELS)

    def test_scrolling_up_and_the_limits(self):
        area = self.make()
        bar = area.verticalScrollBar()
        wheel(area, notches=1)                               # already at the top
        QTest.qWait(50)
        self.assertEqual(bar.value(), 0)
        wheel(area, notches=-1000)
        QTest.qWait(smooth_scroll.DURATION_MS + 150)
        self.assertEqual(bar.value(), bar.maximum())
        wheel(area, notches=2)
        QTest.qWait(smooth_scroll.DURATION_MS + 150)
        self.assertEqual(bar.value(), bar.maximum() - 2 * smooth_scroll.NOTCH_PIXELS)

    def test_touchpad_scrolling_is_left_to_qt(self):
        area, plain = self.make(), self.make(QScrollArea)
        wheel(area, notches=-1, pixels=-40)                  # a touchpad sends both deltas
        wheel(plain, notches=-1, pixels=-40)
        self.assertGreater(plain.verticalScrollBar().value(), 0)
        self.assertEqual(area.verticalScrollBar().value(), plain.verticalScrollBar().value())
        self.assertNotEqual(area._animation.state(), area._animation.State.Running)

    def test_moving_the_bar_by_hand_resets_the_target(self):
        area = self.make()
        bar = area.verticalScrollBar()
        wheel(area, notches=-1)
        QTest.qWait(smooth_scroll.DURATION_MS + 150)
        bar.setValue(300)                                    # e.g. dragged, or restored by the app
        wheel(area, notches=-1)
        QTest.qWait(smooth_scroll.DURATION_MS + 150)
        self.assertEqual(bar.value(), 300 + smooth_scroll.NOTCH_PIXELS)

    def test_a_page_that_fits_ignores_the_wheel(self):
        area = SmoothScrollArea()
        area.setWidget(QLabel("short"))
        area.resize(300, 300)
        area.show()
        self.addCleanup(area.deleteLater)
        _app.processEvents()
        wheel(area, notches=-1)
        self.assertEqual(area.verticalScrollBar().value(), 0)


class WiredUpTests(unittest.TestCase):
    def test_help_and_settings_use_the_smooth_area(self):
        from core import config
        from ui.help_dialog import HelpDialog, HelpState
        from ui.settings_dialog import SettingsDialog

        help_dialog = HelpDialog(HelpState(config.normalize({})))
        self.addCleanup(help_dialog.deleteLater)
        self.assertIsInstance(help_dialog._scroll, SmoothScrollArea)

        settings = SettingsDialog(config.normalize({}))
        self.addCleanup(settings.deleteLater)
        self.assertTrue(settings.findChildren(SmoothScrollArea))


if __name__ == "__main__":
    unittest.main()
