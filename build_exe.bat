@echo off
rem Builds dist\ShugoTracker.exe (one file, no console, asks for admin on launch).
rem Needs Python 3.11+ on PATH. The finished exe does NOT need Python.
cd /d "%~dp0"
if not exist ".build-venv\Scripts\python.exe" (
  py -3 -m venv .build-venv || python -m venv .build-venv
)
".build-venv\Scripts\python.exe" -m pip install --upgrade pip
".build-venv\Scripts\python.exe" -m pip install -r requirements.txt pyinstaller
".build-venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean ShugoTracker.spec
if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)
copy /y config.example.json dist\config.json >nul
echo.
echo Built: %~dp0dist\ShugoTracker.exe
pause
