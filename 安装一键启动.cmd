@echo off
choice /C YN /N /M "Start local assistant after Windows sign-in? [Y/N] "
set "STARTUP_SWITCH=--startup"
if errorlevel 2 set "STARTUP_SWITCH=--no-startup"
if defined LITERACY_ASSISTANT_PYTHON (
  "%LITERACY_ASSISTANT_PYTHON%" -B "%~dp0scripts\install_assistant.py" %STARTUP_SWITCH%
) else if exist "C:\Python312\python.exe" (
  "C:\Python312\python.exe" -B "%~dp0scripts\install_assistant.py" %STARTUP_SWITCH%
) else (
  python -B "%~dp0scripts\install_assistant.py" %STARTUP_SWITCH%
)
if errorlevel 1 pause
