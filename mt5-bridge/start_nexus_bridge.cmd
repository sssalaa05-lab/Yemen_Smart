@echo off
title Nexus MT5 Bridge
cd /d C:\nexus

echo ============================================
echo    NEXUS MT5 BRIDGE  -  launcher
echo ============================================
echo.

rem --- Step 1: start MetaTrader 5 if it is not running ---
tasklist /fi "imagename eq terminal64.exe" 2>nul | find /i "terminal64.exe" >nul
if not errorlevel 1 (
    echo [1/3] MetaTrader 5 is already running.
) else (
    echo [1/3] Starting MetaTrader 5 ...
    start "" "C:\Program Files\One Royal MT5 Terminal\terminal64.exe"
)

rem --- Step 2: wait until the terminal is ready and logged in ---
echo [2/3] Waiting for the terminal to be ready (max 120 seconds) ...
set /a tries=0

:wait_mt5
timeout /t 3 /nobreak >nul
python -c "import MetaTrader5 as m, sys; sys.exit(0 if (m.initialize() and m.account_info()) else 1)" >nul 2>&1
if not errorlevel 1 goto ready
set /a tries+=1
if %tries% geq 40 (
    echo [2/3] WARNING: terminal still not ready after 120 s.
    echo        Open MT5 and log in, then press any key to retry.
    pause >nul
    set /a tries=0
)
goto wait_mt5

:ready
echo [2/3] Terminal ready - account detected.

rem --- Step 3: run the bridge (this window stays open) ---
echo.
echo [3/3] Starting the bridge...  stop it with Ctrl+C
echo.
python bridge.py
echo.
echo [Bridge stopped] Press any key to close this window...
pause >nul
