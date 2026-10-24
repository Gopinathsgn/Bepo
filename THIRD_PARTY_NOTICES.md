# Third-party notices

Bepo is licensed under the GPLv3 (see [LICENSE](LICENSE)). It uses and, in release builds, redistributes the
components below, each under its own license. This file is a summary, not a substitute for the licenses
themselves; the full license text of every Python package shipped in a release build is included in the
`*.dist-info` folders inside the application directory.

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

- **License:** LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only (Bepo uses it under the LGPLv3/GPLv3 terms)
- **Copyright:** The Qt Company Ltd. and contributors
- Release builds ship the unmodified PySide6 and Qt libraries as separate DLLs next to `Bepo.exe`, so they can be
  replaced by the user. Source code: <https://code.qt.io/> and <https://pypi.org/project/PySide6/>.

## Other Python packages

| Package | Purpose | License |
|---|---|---|
| pyperclip | Clipboard fallback | BSD-3-Clause |
| numpy | Audio buffers (via moonshine-voice) | BSD-3-Clause |
| sounddevice / PortAudio | Microphone capture (via moonshine-voice) | MIT |
| requests, tqdm, filelock, platformdirs, google-crc32c | Model download (via moonshine-voice) | see each package's license |
| PyInstaller | Builds the executable (build time only) | GPL-2.0 with bootloader exception |

## Build tooling

- Inno Setup (installer builder, build time only) — <https://jrsoftware.org/isinfo.php>
