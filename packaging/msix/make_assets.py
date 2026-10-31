"""
Generate the tile/logo PNGs an MSIX package needs from assets/icon.png.

    python packaging/msix/make_assets.py <output-dir>

Uses Qt's QImage (PySide6 is already a dependency), so no extra imaging library is needed.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage, QPainter

ICON = Path(__file__).resolve().parents[2] / "assets" / "icon.png"

# name -> (width, height). The icon is centred, keeping its aspect ratio.
TILES = {
    "StoreLogo.png": (50, 50),
    "Square44x44Logo.png": (44, 44),
    "Square150x150Logo.png": (150, 150),
    "Wide310x150Logo.png": (310, 150),
}
# Taskbar / Start-menu list icons: Windows picks `targetsize-N` files when present (unplated = no tile background).
TARGET_SIZES = (16, 24, 32, 48, 256)


def render(source: QImage, width: int, height: int, margin: float = 0.0) -> QImage:
    canvas = QImage(width, height, QImage.Format.Format_ARGB32)
    canvas.fill(Qt.GlobalColor.transparent)
    side = round(min(width, height) * (1.0 - 2 * margin))
    scaled = source.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    painter = QPainter(canvas)
    painter.drawImage(QRect((width - scaled.width()) // 2, (height - scaled.height()) // 2,
                            scaled.width(), scaled.height()), scaled)
    painter.end()
    return canvas


def main(out_dir: Path) -> None:
    source = QImage(str(ICON))
    if source.isNull():
        raise SystemExit(f"Cannot read {ICON}")
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs = dict(TILES)
    for size in TARGET_SIZES:
        jobs[f"Square44x44Logo.targetsize-{size}_altform-unplated.png"] = (size, size)
    for name, (w, h) in jobs.items():
        # a little breathing room on the tiles, full bleed on the small list icons
        margin = 0.12 if name in ("Square150x150Logo.png", "Wide310x150Logo.png") else 0.0
        if not render(source, w, h, margin).save(str(out_dir / name)):
            raise SystemExit(f"Could not write {name}")
    print(f"Wrote {len(jobs)} images to {out_dir}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]))
