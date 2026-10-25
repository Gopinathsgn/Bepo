# Third-party notices

Bepo is licensed under the GPLv3 (see [LICENSE](LICENSE)). It uses and, in release builds, redistributes the
components below, each under its own license. This file is a summary, not a substitute for the licenses
themselves; the license text of most Python packages shipped in a release build is included in the
`*.dist-info` folders inside the application directory (Qt's is provided in `licenses/`, see below).

## Moonshine AI — speech recognition engine and model

- **Package:** `moonshine-voice` (<https://github.com/moonshine-ai/moonshine>)
- **License:** MIT — Copyright (c) 2025 Moonshine AI
- **Model:** release builds bundle the English *small streaming* model (downloaded from `download.moonshine.ai`
  on first run for source installs).

  Moonshine states that its **non-English** models are under the non-commercial *Moonshine Community License*;
  Bepo only uses the English model. The authoritative terms for the model weights are published at
  <https://www.moonshine.ai/license> — please check them before redistributing the weights in your own build.

```
MIT License

Copyright (c) 2025 Moonshine AI

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Qt for Python (PySide6) / Qt

- **License:** LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only OR commercial. Bepo uses it under the **LGPLv3**
  (and, as Bepo itself is GPLv3, the GPLv3 terms are also satisfied).
- **Copyright:** The Qt Company Ltd. and contributors
- **Used modules:** QtCore, QtGui, QtWidgets and QtSvg only. Release builds do not include WebEngine, Qt Charts,
  Data Visualization, Quick 3D or Virtual Keyboard.
- **License texts:** [licenses/LGPL-3.0.txt](licenses/LGPL-3.0.txt) and [licenses/GPL-3.0.txt](licenses/GPL-3.0.txt)
  (also shipped in the `licenses` folder of every release). The PySide6 wheel itself only carries the commercial
  license text in its `dist-info`, which is why these are provided separately.
- **Unmodified:** Bepo ships the stock PySide6/Qt binaries from PyPI (the version pinned by the release, see
  `PySide6-*.dist-info` in the application folder), without changes.
- **Replacing Qt:** the Qt and PySide6 libraries are separate DLL/PYD files in the `_internal\PySide6` folder next to
  `Bepo.exe` (a one-folder build, not a single self-extracting file). You may replace them with your own build of
  a compatible Qt/PySide6 version, and Bepo's own source (GPLv3) is available to relink or rebuild.
- **Source code:** the corresponding source of the exact version is at <https://code.qt.io/cgit/pyside/pyside-setup.git/>
  and <https://download.qt.io/official_releases/QtForPython/>; Bepo's source is at
  <https://github.com/Gopinathsgn>. If you cannot get it there, open an issue on the Bepo repository and
  the source will be provided on request, for at least three years after the release.

## Other Python packages

| Package | Purpose | License |
|---|---|---|
| pyperclip | Clipboard fallback | BSD-3-Clause |
| numpy | Audio buffers (via moonshine-voice) | BSD-3-Clause |
| sounddevice / PortAudio | Microphone capture (via moonshine-voice) | MIT |
| requests, tqdm, filelock, platformdirs, google-crc32c | Model download (via moonshine-voice) | see each package's license |
| Python (CPython runtime, bundled) | Interpreter | PSF License |
| PyInstaller | Builds the executable (build time only); its bootloader is bundled | GPL-2.0 with bootloader exception |

## Build tooling

- Inno Setup (installer builder, build time only) — <https://jrsoftware.org/isinfo.php>
