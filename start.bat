@echo off
title 17Money Algorithm
echo ============================================
echo    17MONEY ALGORITHM
echo ============================================
echo.
echo Backend + Frontend baslatiliyor...
echo.

:: --- Python yorumlayicisini otomatik bul (PATH'te olmasa da calisir) ---
call "%~dp0scripts\python_env.bat"
if not defined PYTHON_EXE (
    echo [HATA] Python bulunamadi.
    echo        Python 3 kurun  : https://www.python.org/downloads/
    echo        Ozelse tam yol  : set PYTHON_EXE=C:\tam\yol\python.exe
    echo.
    pause
    exit /b 1
)
echo Python: %PYTHON_EXE%
echo.

:: Backend'i ayri pencerede baslat
start "17Money Backend" cmd /c "cd /d "%~dp0backend" && set PYTHONPATH=%~dp0backend && "%PYTHON_EXE%" -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload"

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
