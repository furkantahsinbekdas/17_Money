@echo off
:: ============================================================================
::  python_env.bat — Python yorumlayicisini bulur ve %PYTHON_EXE% olarak disari verir
:: ----------------------------------------------------------------------------
::  Amac: `python` PATH'te olmasa bile (Windows Store taklidi veya "Add to PATH"
::        isaretlenmemis kurulum) BASLAT.bat / start.bat sorunsuz calissin.
::
::  Kullanim (baska bir .bat icinden):
::      call "%~dp0scripts\python_env.bat"
::      if not defined PYTHON_EXE ( ... hata ver ... )
::      "%PYTHON_EXE%" -m uvicorn main:app ...
::
::  Arama sirasi (ilk bulunan kazanir):
::      1) Disaridan verilmis gecerli %PYTHON_EXE%
::      2) py launcher      : py -3
::      3) PATH uzerindeki  : python
::      4) Kullanici kurulumu: %LOCALAPPDATA%\Programs\Python\PythonN\python.exe
::      5) Sistem kurulumu  : %ProgramFiles%\PythonN\python.exe
::
::  Cikis kodu: 0 = bulundu (%PYTHON_EXE% tanimli), 1 = bulunamadi
:: ============================================================================

:: --- 1) Cagiran taraf zaten gecerli bir yol verdiyse ona saygi duy ---
if defined PYTHON_EXE if exist "%PYTHON_EXE%" exit /b 0
set "PYTHON_EXE="

:: --- 2) py launcher (Windows'ta en guvenilir yol) ---
for /f "usebackq delims=" %%P in (`py -3 -c "import sys;print(sys.executable)" 2^>nul`) do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
if defined PYTHON_EXE exit /b 0

:: --- 3) PATH uzerindeki python ---
for /f "usebackq delims=" %%P in (`python -c "import sys;print(sys.executable)" 2^>nul`) do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
if defined PYTHON_EXE exit /b 0

:: --- 4) Kullanici kurulumlari: en yeni surum once (Python 3.8 - 3.15) ---
for %%V in (315 314 313 312 311 310 39 38) do (
    if not defined PYTHON_EXE if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
)
if defined PYTHON_EXE exit /b 0

:: --- 5) Sistem kurulumlari (all users) ---
for %%V in (315 314 313 312 311 310 39 38) do (
    if not defined PYTHON_EXE if exist "%ProgramFiles%\Python%%V\python.exe" set "PYTHON_EXE=%ProgramFiles%\Python%%V\python.exe"
)
if defined PYTHON_EXE exit /b 0

exit /b 1
