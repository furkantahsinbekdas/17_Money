@echo off
title 17Money Algorithm
echo ============================================
echo    17MONEY ALGORITHM
echo ============================================
echo.
echo Backend + Frontend baslatiliyor...
echo.

:: Backend'i ayri pencerede baslat
start "17Money Backend" cmd /c "cd /d "%~dp0backend" && set PYTHONPATH=%~dp0backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload"

:: 3 saniye bekle, backend ayaga kalksin
timeout /t 3 /nobreak >nul

:: Frontend'i ayri pencerede baslat
start "17Money Frontend" cmd /c "cd /d "%~dp0frontend" && npm start"

echo.
echo Backend: http://localhost:8000
echo Frontend: http://localhost:3000
echo Swagger:  http://localhost:8000/docs
echo.
echo Tarayici otomatik acilacak...
echo Kapatmak icin acilan pencereleri kapatin.
echo ============================================

timeout /t 5 /nobreak >nul
start http://localhost:3000
