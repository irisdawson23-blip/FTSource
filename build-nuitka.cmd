@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo ================================
echo Building WN Forza Tuner
echo Nuitka standalone public build
echo ================================
echo.
echo This build uses Nuitka instead of PyInstaller.
echo It may reduce antivirus false positives, but it is not guaranteed.
echo.
echo Requirement:
echo - Visual Studio 2022 Build Tools with C++ tools installed
echo.

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
    echo Install Python 3.12 or 3.13 from python.org, then run this again.
    echo Make sure "Add python.exe to PATH" is ticked during install.
    echo.
    pause
    exit /b 1
)

echo Using Python:
%PYTHON_CMD% -c "import sys; print(sys.executable); print(sys.version)"
if errorlevel 1 goto :fail

echo.
echo Creating Nuitka build virtual environment...
if exist ".nuitka_venv\Scripts\python.exe" (
    echo Existing Nuitka venv found.
) else (
    %PYTHON_CMD% -m venv ".nuitka_venv"
    if errorlevel 1 goto :fail
)

set "VPY=%CD%\.nuitka_venv\Scripts\python.exe"

echo.
echo Installing app and Nuitka requirements...
"%VPY%" -m pip install --upgrade pip
if errorlevel 1 goto :fail
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 goto :fail
"%VPY%" -m pip install --upgrade nuitka ordered-set zstandard
if errorlevel 1 goto :fail

echo.
echo Cleaning old Nuitka output...
rmdir /S /Q "dist-nuitka" 2>nul

echo.
echo Running Nuitka...
"%VPY%" -m nuitka ^
  --standalone ^
  --msvc=latest ^
  --windows-console-mode=disable ^
  --enable-plugin=pyside6 ^
  --include-data-dir=data=data ^
  --output-dir=dist-nuitka ^
  --output-filename="WN Forza Tuner.exe" ^
  --windows-icon-from-ico=data\WNFT.ico ^
  --file-version=1.1.3.0 ^
  --product-version=1.1.3.0 ^
  --file-description="WN Forza Tuner" ^
  --product-name="WN Forza Tuner" ^
  --company-name="WN" ^
  --copyright="WN Forza Tuner" ^
  --remove-output ^
  src\main.py
if errorlevel 1 goto :fail

echo.
echo ================================
echo Nuitka build complete.
echo ================================
echo.
echo EXE folder:
echo dist-nuitka\main.dist
echo.
echo EXE:
echo dist-nuitka\main.dist\WN Forza Tuner.exe
echo.
echo For release, ZIP this whole folder:
echo dist-nuitka\main.dist
echo.
pause
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
echo ================================
echo NUITKA BUILD FAILED
echo ================================
echo.
echo Common fix:
echo Install Visual Studio 2022 Build Tools and select:
echo - Desktop development with C++
echo - MSVC v143 C++ build tools
echo - Windows 10/11 SDK
echo.
echo Then run build-nuitka.cmd again.
echo.
pause
exit /b 1
