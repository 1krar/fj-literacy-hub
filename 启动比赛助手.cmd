@echo off
if defined LITERACY_ASSISTANT_PYTHON (
  "%LITERACY_ASSISTANT_PYTHON%" -B "%~dp0scripts\start_assistant.py"
) else if exist "C:\Python312\python.exe" (
  "C:\Python312\python.exe" -B "%~dp0scripts\start_assistant.py"
) else (
  python -B "%~dp0scripts\start_assistant.py"
)
if errorlevel 1 pause
