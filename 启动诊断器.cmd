@echo off
setlocal
if exist "%~dp0CTRLHelper.exe" (
  start "" "%~dp0CTRLHelper.exe"
  exit /b
)
if defined LITERACY_ASSISTANT_PYTHON goto configured
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys; sys.exit(sys.version_info < (3,12))" >nul 2>nul
  if not errorlevel 1 goto python_launcher
)
set "CTRL_PYTHON="
if exist "C:\Python312\python.exe" set "CTRL_PYTHON=C:\Python312\python.exe"
if defined CTRL_PYTHON goto probe
for /f "delims=" %%P in ('where python 2^>nul ^| findstr /v /i "WindowsApps"') do if not defined CTRL_PYTHON set "CTRL_PYTHON=%%P"
if not defined CTRL_PYTHON goto missing
:probe
"%CTRL_PYTHON%" -c "import sys; sys.exit(sys.version_info < (3,12))" >nul 2>nul
if errorlevel 1 goto missing
"%CTRL_PYTHON%" -X utf8 -B "%~dp0scripts\windows_launcher.py"
goto finished
:configured
"%LITERACY_ASSISTANT_PYTHON%" -c "import sys; sys.exit(sys.version_info < (3,12))" >nul 2>nul
if errorlevel 1 goto missing
"%LITERACY_ASSISTANT_PYTHON%" -X utf8 -B "%~dp0scripts\windows_launcher.py"
goto finished
:python_launcher
py -3 -X utf8 -B "%~dp0scripts\windows_launcher.py"
:finished
if errorlevel 1 (
  echo Launch failed. Use the portable Windows ZIP, or install Python 3.12+ first.
  pause
)
exit /b
:missing
echo This is the SOURCE package. No usable Python 3.12+ was found.
echo Recommended: fully extract ctrl-assistant-windows-x64.zip,
echo then open CTRLHelper.exe. Keep _internal, dist and vendor folders.
echo GitHub Code - Download ZIP downloads source, not the portable program.
echo Alternatively install Python 3.12+ from https://www.python.org/downloads/windows/
echo and enable Add Python to PATH, then run this script again.
pause
exit /b 1
