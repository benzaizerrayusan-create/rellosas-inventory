@echo off
title Rellosas Inventory System
color 0A
echo.
echo ================================================
echo   RELLOSAS INVENTORY SYSTEM - MYSQL MODE
echo ================================================
echo.
echo Setting environment: DB_TYPE=mysql
set DB_TYPE=mysql
set MYSQL_HOST=127.0.0.1
set MYSQL_USER=root
set MYSQL_PASSWORD=
set MYSQL_DATABASE=inventory_db

echo.
set "LOCAL_IP=localhost"
for /f "tokens=2 delims=:" %%A in ('ipconfig ^| findstr /R /C:"IPv4 Address" ^| findstr /V "169."') do (
  set "LOCAL_IP=%%A"
  goto :gotip
)
:gotip
set "LOCAL_IP=%LOCAL_IP: =%"
echo Starting Flask App...
echo.
echo Open browser on this PC: http://localhost:5000
echo Open on another device: http://%LOCAL_IP%:5000
echo Login: admin / admin123
echo.
echo Press CTRL+C anytime to stop
echo.
echo ================================================
echo.

python app.py

pause
