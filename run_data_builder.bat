@echo off
REM PMSI Data Builder - Windows Launcher
REM Double-click this file or run from PowerShell/cmd

cd /d "%~dp0"

REM Try python first (Python Launcher for Windows)
where python >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    python launch_builder.py
    goto :end
)

REM Try py (Python Launcher)
where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    py launch_builder.py
    goto :end
)

REM Try python3
where python3 >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    python3 launch_builder.py
    goto :end
)

echo Python not found! Please install Python 3.10+ from python.org
pause

:end
pause
