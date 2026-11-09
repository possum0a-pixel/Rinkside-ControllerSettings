@echo off
title RinkStick Pro - NHL Legacy Stick Sensitivity Engine
cd /d "%~dp0"

echo ============================================================
echo  RinkStick Pro // NHL Legacy Stick Sensitivity Engine
echo ============================================================
echo.
echo  RinkSide binds your account to the physical controller on
echo  Player 1 (input0). Transformed sticks are written onto that
echo  same pad in RAM when NHL Legacy launches.
echo.
echo  Launch order:
echo    1. Plug in / turn on your controller
echo    2. Start RinkStick Pro (this window)
echo    3. Sign in and Play from RinkSide
echo.

python main.py %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo RinkStick exited with code %ERRORLEVEL%.
    pause
)
