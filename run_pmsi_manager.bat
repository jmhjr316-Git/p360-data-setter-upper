@echo off
echo PMSI Simulator Data Manager
echo ========================

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH
    echo Please install Python from https://python.org
    pause
    exit /b 1
)

REM Install dependencies
echo Installing dependencies...
python -m pip install --user requests>=2.25.0 tkcalendar>=1.6.0 pymongo>=4.0.0

REM Launch the application
echo Launching PMSI Data Manager...
python pmsi_data_ui.py

pause