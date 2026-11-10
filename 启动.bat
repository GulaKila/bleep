@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo [!] Python not found. Install Python 3.9+ first.
  pause
  exit /b 1
)
python -c "import numpy" >nul 2>nul
if errorlevel 1 (
  echo [!] numpy is required. Run: pip install numpy
  pause
  exit /b 1
)
where pythonw >nul 2>nul
if errorlevel 1 (
  python bleep_gui.py
  exit /b
)
start "" pythonw bleep_gui.py