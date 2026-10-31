# Privacy policy

_Last updated: 31 October 2026_

Bepo is a free, open-source voice dictation app for Windows, made by Gopinath
(<https://github.com/Gopinathsgn/Bepo>). This page says what Bepo does with your data. The short version:
**Bepo has no accounts, no analytics and no telemetry, and your voice is recognised on your own computer.**

## What Bepo does not do

- It does not send your audio, your dictated text or anything about how you use the app to me or to any server.
- It has no sign-in, no tracking and no advertising.
- It does not read your keystrokes. It registers its own shortcuts with Windows (`RegisterHotKey`) and checks only the
  state of the Esc key while recording and of the push-to-talk keys.

## Microphone

Bepo opens your microphone only while you are dictating and releases it when you finish. Audio is processed in memory
by the speech model on your device and is not saved to disk.

## Text it types

Dictated text is typed into whichever app has focus, using Windows `SendInput`. That app receives the text like any
other typing, and what it does with it is governed by that app's own privacy policy.

## Clipboard

By default Bepo does not read or write your clipboard. If typing fails in some app, Bepo falls back to a paste and then
restores your previous clipboard text. Two features you can switch on do use the clipboard: the "clipboard safety net"
(keeps the whole dictation on the clipboard) and the recent-dictations list (copies an entry when you click it).
Both are off by default.

## What is stored on your device

- **Settings:** `%LOCALAPPDATA%\Bepo\config.json` (your shortcuts, chosen microphone, custom vocabulary and similar
  preferences).
- **Log file:** `%LOCALAPPDATA%\Bepo\logs\bepo.log`. It holds diagnostics and character counts, never dictated text.
- **Recent dictations (optional, off by default):** the last 10 dictations are kept in memory only, never written to
  disk or to the log, and are gone when you quit Bepo.
- **Speech model:** the model files, either bundled with the app or downloaded once (see below).

Uninstalling Bepo removes the program. To delete the settings and logs too, remove the `%LOCALAPPDATA%\Bepo` folder.

## Network use

Bepo's only network access is the one-time download of the speech model, from Moonshine AI's server
(`download.moonshine.ai`), when the model is not already included in your copy. Like any download, this reveals your IP
address to that server. Bepo uses no network during dictation and works offline afterwards. Bepo has no automatic update
check.

## Third parties

- The speech engine and model are made by [Moonshine AI](https://github.com/moonshine-ai/moonshine) and run locally
  inside Bepo.
- If you get Bepo from the Microsoft Store or GitHub, those services collect their own download and usage statistics
  under their own privacy policies. Bepo does not control or receive that data.

## Children

Bepo does not collect personal information from anyone, including children.

## Changes

If this policy changes, the new version will be published in this repository with a new date. The full history is
visible in the repository.

## Contact

Questions about privacy: open an issue at <https://github.com/Gopinathsgn/Bepo/issues> or write to
[sgn@outlook.in](mailto:sgn@outlook.in). For security problems, see [SECURITY.md](SECURITY.md).
