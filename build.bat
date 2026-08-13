@echo off
rem Rebuild the standalone exe (requires: pip install pyinstaller customtkinter)
cd /d "%~dp0"
python -m PyInstaller main.spec --noconfirm
if errorlevel 1 (
  echo Build FAILED.
  exit /b 1
)
echo.
echo Build complete: dist\D2RAutoPotion.exe
pause
