# Contributing to Bepo

Thanks for helping make Bepo better! Bug reports, fixes and focused features are all welcome.

## Getting set up

Windows 10/11 and Python 3.10+ are required (Bepo uses Win32 APIs).

```powershell
git clone https://github.com/Gopinathsgn/bepo.git
cd bepo
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

## Before you open a pull request

```powershell
# Syntax check
python -c "import glob, py_compile; [py_compile.compile(f, doraise=True) for f in ['main.py', 'version.py'] + glob.glob('core/*.py') + glob.glob('ui/*.py') + glob.glob('setup/*.py') + glob.glob('tests/*.py')]; print('All files compiled successfully!')"

# Tests (no microphone, model or real keyboard input needed)
python -m unittest discover -s tests -v
```

The tests mock `SendInput`, the clipboard, the microphone and the model, so they are safe to run anywhere. CI runs the same
commands on every pull request.

## Guidelines

- Read [`AGENTS.md`](AGENTS.md) first: it documents the threading rules (never touch widgets from non-GUI threads), the
  Moonshine API contract and other invariants.
- Keep start-up fast: don't add Qt or heavy imports to `core/bootstrap.py`, `core/config.py` or `core/engine.py`, and keep `moonshine_voice`/`sounddevice` imports lazy.
- Keep the app fast and private. No telemetry, no network calls during dictation, and **don't touch the user's
  clipboard** unless it is the paste fallback (which must restore it) or the opt-in `clipboard_safety_net`.
- Never log dictated text — character counts only. The microphone must only be open while dictating.
- New settings: add the key to `DEFAULT_CONFIG` and `normalize()` in `core/config.py`, to `config.json`, add a control to the Settings window (`ui/settings_dialog.py`) that applies live, and document it in the README. See `AGENTS.md` §7.
- Add or update a test for behavior changes (`tests/`).
- Keep pull requests focused, and describe how you tested on Windows.

## Reporting bugs

Use the bug report template and include your Windows version, how Bepo was installed (installer, portable or source),
and the relevant lines from `%LOCALAPPDATA%\Bepo\logs\bepo.log` (it contains no dictated text).

Security issues: see [SECURITY.md](SECURITY.md) — please don't file them as public issues.

By contributing you agree that your contributions are licensed under the project's GPLv3 license.
