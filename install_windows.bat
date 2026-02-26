@echo off
echo ============================================
echo   Banner Print Tracker - Windows Setup
echo ============================================
echo.
echo Checking Python installation...
python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo ERROR: Python not found!
    echo Please install Python from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)
echo Python found!
echo.
echo Installing required packages...
pip install reportlab pillow
echo.
echo Creating desktop shortcut...
python -c "
import os, sys
from pathlib import Path

script_dir = Path('%~dp0')
desktop = Path.home() / 'Desktop'
shortcut_path = desktop / 'Banner Tracker.bat'

content = f'''@echo off
cd /d \"{script_dir}\"
python banner_tracker.py
'''
shortcut_path.write_text(content)
print('Desktop shortcut created!')
"
echo.
echo ============================================
echo   DONE! 
echo   - Double-click 'Banner Tracker' on Desktop to launch
echo   - Your data is stored in: %USERPROFILE%\banner_tracker.db
echo ============================================
pause
