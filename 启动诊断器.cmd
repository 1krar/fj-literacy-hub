@echo off
if exist "%~dp0CTRLHelper.exe" (
  start "" "%~dp0CTRLHelper.exe"
  exit /b
)
if defined LITERACY_ASSISTANT_PYTHON (
  "%LITERACY_ASSISTANT_PYTHON%" -X utf8 -B "%~dp0scripts\windows_launcher.py"
) else (
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3 -X utf8 -B "%~dp0scripts\windows_launcher.py"
  ) else if exist "C:\Python312\python.exe" (
    "C:\Python312\python.exe" -X utf8 -B "%~dp0scripts\windows_launcher.py"
  ) else (
    python -X utf8 -B "%~dp0scripts\windows_launcher.py"
  )
)
if errorlevel 1 (
  echo Launch failed. Use the portable Windows ZIP, or install Python 3.12+ first.
  pause
)
