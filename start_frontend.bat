@echo off
title 17Money Frontend
echo ============================================
echo    17MONEY ALGORITHM - Frontend
echo ============================================
echo.

cd /d "%~dp0frontend"

echo Adres: http://localhost:3000
echo.
echo NOT: Backend'in de calisiyor olmasi gerekir!
echo      Backend icin start.bat'i calistirin.
echo ============================================

start http://localhost:3000

npm start
pause
