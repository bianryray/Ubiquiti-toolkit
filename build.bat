@echo off
echo ============================================
echo  Building UniFi Toolbox standalone .exe
echo ============================================
echo.

REM Install dependencies if needed
pip install -r requirements.txt

echo.
echo Building with PyInstaller ...
echo.

pyinstaller ^
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

echo.
if exist "dist\UniFi Toolbox.exe" (
    echo ============================================
    echo  SUCCESS: dist\UniFi Toolbox.exe
    echo ============================================
) else (
    echo ============================================
    echo  BUILD FAILED - check output above
    echo ============================================
)
echo.
pause
