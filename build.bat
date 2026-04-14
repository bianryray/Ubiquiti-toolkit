@echo off
setlocal

echo ============================================
echo  Building UniFi Toolbox standalone .exe
echo ============================================
echo.

REM --- Locate a working Python interpreter -------------------------------
REM Prefer the py launcher (ships with standard Windows Python installs),
REM then fall back to `python` on PATH. This avoids relying on pip.exe /
REM pyinstaller.exe being on PATH, which is a common source of
REM "'pip' is not recognized" errors on Windows.

set "PY="
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    set "PY=py -3"
) else (
    where python >nul 2>nul
    if %ERRORLEVEL%==0 (
        set "PY=python"
    )
)

if not defined PY (
    echo ERROR: Could not find a Python interpreter.
    echo.
    echo Install Python 3.10+ from https://www.python.org/downloads/
    echo and make sure to tick "Add Python to PATH" during install,
    echo or install the "py launcher for Windows" option.
    echo.
    goto :fail
)

echo Using Python: %PY%
%PY% --version
if errorlevel 1 goto :fail
echo.

REM --- Install dependencies ----------------------------------------------
echo Installing dependencies ...
%PY% -m pip install --upgrade pip
if errorlevel 1 goto :fail

%PY% -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo.
echo Building with PyInstaller ...
echo.

%PY% -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name "UniFi Toolbox" ^
    --add-data "unifi_toolbox;unifi_toolbox" ^
    --hidden-import=paramiko ^
    --hidden-import=requests ^
    --hidden-import=customtkinter ^
    --hidden-import=_cffi_backend ^
    --collect-all customtkinter ^
    main.py
if errorlevel 1 goto :fail

echo.
if exist "dist\UniFi Toolbox.exe" (
    echo ============================================
    echo  SUCCESS: dist\UniFi Toolbox.exe
    echo ============================================
    echo.
    pause
    exit /b 0
)

:fail
echo ============================================
echo  BUILD FAILED - check output above
echo ============================================
echo.
pause
exit /b 1
