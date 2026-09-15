@echo off
chcp 65001 >nul
title 17Money Algorithm - Baslatici
echo ============================================
echo    17MONEY ALGORITHM
echo ============================================
echo.

cd /d "%~dp0"

:: --- Eski calisan sunuculari temizle (port cakismasini onler) ---
echo Eski sunucular kontrol ediliyor...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    echo   Port 8000 mesgul (PID %%a) - kapatiliyor...
    taskkill /F /PID %%a >nul 2>&1
)
echo.

:: --- Backend ayri pencerede (kendi basina ayakta kalir) ---
echo [1/2] Backend baslatiliyor (port 8000)...
start "17Money Backend" cmd /k "cd /d "%~dp0backend" && set PYTHONPATH=%~dp0backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000"

:: Backend ayaga kalkana kadar bekle
echo       Backend hazirlaniyor...
timeout /t 6 /nobreak >nul

:: --- Frontend ayri pencerede ---
echo [2/2] Frontend baslatiliyor (port 3000)...
start "17Money Frontend" cmd /k "cd /d "%~dp0frontend" && npm start"

echo.
echo ============================================
echo  Backend : http://localhost:8000
echo  Arayuz  : http://localhost:3000
echo  Swagger : http://localhost:8000/docs
echo ============================================
echo.
echo  Iki pencere acildi - KAPATMAYIN.
echo  Durdurmak icin o pencereleri kapatin.
echo.
echo  Tarayici birazdan acilacak...
timeout /t 12 /nobreak >nul
start http://localhost:3000
echo.
echo  Bu pencereyi kapatabilirsiniz (sunucular acik kalir).
pause
