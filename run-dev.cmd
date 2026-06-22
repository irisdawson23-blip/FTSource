@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo Starting WN Forza Tuner v1.3.13...

set "PYTHON_CMD="

call :check_python python
call :check_python py -3.13
call :check_python py -3.12
call :check_python py -3.11
call :check_python py -3.10
call :check_python py -3.9
call :check_python py -3

if not defined PYTHON_CMD (
    echo.
    echo ERROR: No working Python installation was found.
    echo Install Python 3.12 or 3.13 from python.org and tick "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating app virtual environment...
    %PYTHON_CMD% -m venv ".venv"
    if errorlevel 1 goto :fail
)

set "VPY=%CD%\.venv\Scripts\python.exe"

echo Installing requirements...
"%VPY%" -m pip install --upgrade pip
if errorlevel 1 goto :fail
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo Launching...
"%VPY%" "src\main.py"
if errorlevel 1 goto :fail
exit /b 0

:check_python
if defined PYTHON_CMD exit /b 0
%* -c "import sys; raise SystemExit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=%*"
)
exit /b 0

:fail
echo.
echo Launch failed.
pause
exit /b 1
