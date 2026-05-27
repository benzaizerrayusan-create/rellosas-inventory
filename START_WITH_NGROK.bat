@echo off
setlocal enabledelayedexpansion

title Rellosas - NGrok + Flask Integrated
color 0A

echo.
echo ================================================
echo   RELLOSAS WITH NGROK - START HERE
echo ================================================
echo.

REM Check if ngrok exists
where ngrok >nul 2>&1
if errorlevel 1 (
  echo ERROR: ngrok not found in PATH
  echo.
  echo Make sure ngrok is installed and in your PATH.
  echo Download from: https://ngrok.com/download
  echo.
  pause
  exit /b 1
)

echo [OK] ngrok found!
echo.
echo This will start:
echo   1. Flask app on http://localhost:5000
echo   2. ngrok tunnel for public access
echo.
echo ================================================
echo.

REM Start Flask in one window
echo Starting Flask app...
start "Rellosas - Flask" cmd /k "title Rellosas Flask && cd /d "%~dp0" && python app.py"

REM Wait for Flask to start
timeout /t 2 /nobreak >nul

REM Start ngrok in another window
echo Starting ngrok tunnel...
start "Rellosas - ngrok" cmd /k "title Rellosas ngrok && cd /d "%~dp0" && ngrok http 5000"

REM Wait for ngrok to initialize
timeout /t 3 /nobreak >nul

echo.
echo ================================================
echo   RELLOSAS IS RUNNING
echo ================================================
echo.
echo LOCAL ACCESS (same Wi-Fi):
echo   Browser: http://localhost:5000
echo   Phone: http://^<YOUR_PC_IP^>:5000
echo.
echo REMOTE ACCESS (any network):
echo   Check the ngrok window for: https://xxxxxx.ngrok.io
echo   Customer link: https://xxxxxx.ngrok.io/customer-order
echo.
echo LOGIN: admin / admin123
echo.
echo Press any key to close this window
echo (This will NOT stop Flask or ngrok - close those separately)
echo.
pause

