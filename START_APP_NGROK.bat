@echo off
title Rellosas Inventory System - Public Access via ngrok
color 0A

set "PORT=5000"
set "NGROK_CMD=ngrok"

if not exist "%~dp0app.py" (
  echo ERROR: app.py not found in this directory.
  pause
  exit /b 1
)

where %NGROK_CMD% >nul 2>&1
if errorlevel 1 (
  echo ERROR: ngrok is not installed or not on PATH.
  echo Download ngrok from https://ngrok.com/download and add it to your PATH.
  pause
  exit /b 1
)

echo ================================================
echo   RELLOSAS INVENTORY SYSTEM - PUBLIC ACCESS
echo ================================================
echo.
echo Starting Flask app on http://localhost:%PORT%
start "Rellosas Flask" cmd /k "python app.py"

echo Waiting 3 seconds for the app to start...
timeout /t 3 /nobreak >nul

echo Starting ngrok tunnel to port %PORT%
%NGROK_CMD% http %PORT%

echo.
echo When ngrok is ready, it will display a public URL you can share.
echo Press CTRL+C to stop ngrok, then close the other window to stop the Flask app.
echo.
pause
