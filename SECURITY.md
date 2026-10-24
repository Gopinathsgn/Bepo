# Security policy

## Supported versions

Only the latest release receives security fixes.

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's private reporting instead:
**Security → Report a vulnerability** on this repository
(<https://github.com/Gopinathsgn/bepo/security/advisories/new>).

Include what you found, how to reproduce it, and the Bepo and Windows versions. You can expect an acknowledgement
within a few days.

## What is in scope

Bepo runs locally and handles microphone audio, global shortcuts and keystroke injection, so reports about these are
especially welcome:

- dictated text or audio leaving the machine, or being written to logs or the clipboard unexpectedly
- ways to make Bepo type text the user didn't dictate (injection into other apps)
- problems in the build, installer or release pipeline (e.g. unsigned or tampered artifacts)

## Good to know

- Bepo only uses the network to download the speech model on first run (release builds already bundle it).
- Typing into elevated (Administrator) windows requires running Bepo as Administrator — this is a Windows UIPI
  restriction, not a bug.
- Release binaries are not code-signed yet, so Windows SmartScreen may warn on first run.
