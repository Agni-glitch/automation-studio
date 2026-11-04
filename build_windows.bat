@echo off
rem Build AutomationStudio.exe and AutomationStudio-Setup-<version>.exe into build\output.
rem Needs: Python 3.11+ venv in .venv (with the project installed), Node.js 20+, Inno Setup 6.
rem Extra arguments are passed through, e.g.  build_windows.bat --skip-frontend
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv || goto :error
)
echo Installing build dependencies...
".venv\Scripts\python.exe" -m pip install -q -e ".[dev,browser,desktop,build]" || goto :error

".venv\Scripts\python.exe" build\package.py %* || goto :error
echo.
echo Installer: build\output\AutomationStudio-Setup-*.exe
exit /b 0

:error
echo.
echo BUILD FAILED (exit code %errorlevel%)
exit /b %errorlevel%
