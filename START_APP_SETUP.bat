@echo off
setlocal enabledelayedexpansion

title Rellosas Setup Helper
color 0A

echo.
echo ================================================
echo   RELLOSAS INVENTORY SYSTEM - SETUP
echo ================================================
echo.

REM Check if ngrok is installed
echo Checking for ngrok installation...
where ngrok >nul 2>&1
if errorlevel 1 (
  echo.
  echo [INFO] ngrok is NOT installed on this system.
  echo.
  echo To use public access (share with anyone outside your network):
  echo.
  echo 1. Go to: https://ngrok.com/download
  echo 2. Download ngrok for Windows
  echo 3. Extract it and add to your PATH, or just place ngrok.exe in this folder
  echo 4. Run this script again
  echo.
  echo After installing ngrok, you can use START_APP_NGROK.bat to get a public URL.
  echo.
  pause
  exit /b 1
)

echo [OK] ngrok found!
echo.
echo Starting Rellosas Inventory System with public access...
echo.

REM Start Flask app in background
start "Rellosas Flask" cmd /k "title Rellosas Flask App && python app.py"

echo Waiting 3 seconds for Flask to start...
timeout /t 3 /nobreak >nul

REM Start ngrok tunnel
echo Starting ngrok tunnel...
echo.
echo When ngrok starts, you'll see a URL like: https://xxxxxx.ngrok.io
echo Copy that URL and share it with your phone/customers
echo Example: https://xxxxxx.ngrok.io/customer-order
echo.
echo Press CTRL+C to stop everything
echo.

ngrok http 5000

pause
