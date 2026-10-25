@echo off
setlocal enabledelayedexpansion

echo ===================================================
echo             Bepo - Windows Build Script
echo ===================================================
echo.

:: 1. Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not found in PATH. Please install Python 3.10+ and add to PATH.
    pause
    exit /b 1
)

:: 2. Ensure PyInstaller is installed
echo [1/5] Checking PyInstaller...
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo [*] PyInstaller not detected. Installing PyInstaller...
    python -m pip install --upgrade pyinstaller
)

:: 3. Clean old builds
echo [2/5] Cleaning old build artifacts...
if exist "dist\Bepo" rmdir /s /q "dist\Bepo"
if exist "build" rmdir /s /q "build"
if exist "dist\Bepo-Windows-Portable.zip" del /f /q "dist\Bepo-Windows-Portable.zip"

:: 4. Build executable using PyInstaller
echo [3/5] Compiling Bepo executable via PyInstaller...
python -m PyInstaller ^
    --noconfirm ^
    --onedir ^
    --windowed ^
    --name "Bepo" ^
    --icon "assets/icon.ico" ^
    --add-data "assets;assets" ^
    --add-data "config.json;." ^
    --collect-binaries "moonshine_voice" ^
    --exclude-module "tkinter" ^
    main.py

if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller compilation failed!
    pause
    exit /b 1
)

:: Ship the license texts and notices with the binaries (GPLv3 / LGPLv3 requirement)
copy /y "LICENSE" "dist\Bepo\" >nul
copy /y "NOTICE" "dist\Bepo\" >nul
copy /y "THIRD_PARTY_NOTICES.md" "dist\Bepo\" >nul
xcopy /e /i /y "licenses" "dist\Bepo\licenses" >nul

:: 5. Bundle Moonshine model into dist\Bepo\models
echo [4/5] Bundling Moonshine AI model into application folder...
python -m setup.model_downloader dist/Bepo/models

if errorlevel 1 (
    echo [WARNING] Could not export cached model directly into dist\Bepo\models.
    echo App will download model automatically on first launch if needed.
) else (
    echo [*] Moonshine model successfully bundled! (Offline ready)
)

:: 6. Create portable zip archive
echo [5/5] Packaging portable release ZIP...
powershell -Command "Compress-Archive -Path 'dist\Bepo\*' -DestinationPath 'dist\Bepo-Windows-Portable.zip' -Force"

echo.
echo ===================================================
echo                BUILD COMPLETED SUCCESSFULLY!
echo ===================================================
echo.
echo Standalone App Directory: dist\Bepo\Bepo.exe
echo Portable Release ZIP:     dist\Bepo-Windows-Portable.zip
echo.
echo You can run dist\Bepo\Bepo.exe right now.
echo ===================================================
pause
