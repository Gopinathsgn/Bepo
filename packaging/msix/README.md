# Microsoft Store package (MSIX)

`build_msix.ps1` packs the PyInstaller output (`dist\Bepo`, model included) into `Bepo-Store-v<version>.msix`.

## One-time setup

1. In [Partner Center](https://partner.microsoft.com/dashboard) create the app and reserve the name **Bepo**.
2. Open *Product management → Product identity* and copy three values:

   | Partner Center | GitHub repository variable |
   |---|---|
   | Package/Identity/Name | `MSIX_IDENTITY_NAME` |
   | Package/Identity/Publisher (`CN=…`) | `MSIX_PUBLISHER` |
   | Package/Properties/PublisherDisplayName | `MSIX_PUBLISHER_DISPLAY_NAME` |

3. Add them under *GitHub → Settings → Secrets and variables → Actions → Variables*. Until all three exist the
   release workflow skips the MSIX step; the installer and zip are built as usual.

## Every release

1. Bump `version.py`, commit, tag `vX.Y.Z`, push the tag. The workflow attaches `Bepo-Store-vX.Y.Z.msix` to the
   GitHub Release (and lists it in `SHA256SUMS.txt`).
2. Partner Center → the app → *Start update* → *Packages* → upload the `.msix` → *Submit*. Certification usually
   takes 1–3 days.

The `.msix` is **unsigned on purpose**: the Store signs it. It can't be double-click installed from GitHub; users
who want to install outside the Store use the `Bepo-Setup` installer.

## Build locally

```powershell
.\build.bat                                   # produces dist\Bepo
.\packaging\msix\build_msix.ps1 -Version 1.2.1 `
    -IdentityName <Name> -Publisher "<CN=...>" -PublisherDisplayName <Name>
```

Needs the Windows 10/11 SDK (`makeappx.exe`). `-LayoutOnly` builds `build\msix\layout` without it.
To test an `.msix` on your own PC, sign a copy with a self-signed certificate whose subject equals `-Publisher`,
trust that certificate, then double-click the package.

## Store listing checklist

- **Privacy policy URL** (required because the app uses the microphone):
  `https://github.com/Gopinathsgn/Bepo/blob/main/PRIVACY.md`
- Capabilities to justify when asked: *runFullTrust* (desktop app: global shortcuts, typing into other apps,
  tray icon) and *microphone* (dictation).
- Screenshots (at least one, 1366×768 or larger), a short and a long description, age rating questionnaire.
- Open-source: link the repository and keep the licence files that ship inside the package.

## What differs when running from the Store

- *Launch at Windows startup* uses the package's `windows.startupTask` instead of the Run key (`core/startup.py`).
  Windows owns the state; if the user turned it off in *Settings → Apps → Startup*, only they can turn it on again.
- Writes to `%LOCALAPPDATA%` (settings, log, downloaded models) are redirected by Windows into the package's private
  folder and removed on uninstall. The app behaves the same.
- Updates come through the Store.
