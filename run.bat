@echo off
rem Shugo Tracker launcher: elevates (packet capture needs it), sets up a venv on first run.
cd /d "%~dp0"
net session >nul 2>&1
if errorlevel 1 (
  if "%~1"=="" (
    powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0'"
  ) else (
    powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0' -ArgumentList '%*'"
  )
  exit /b
)
if not exist ".venv\Scripts\python.exe" (
  echo Setting up Python environment...
  py -3 -m venv .venv || python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
if not exist config.json copy config.example.json config.json >nul
".venv\Scripts\python.exe" -m shugotracker.app %*
if errorlevel 1 pause
