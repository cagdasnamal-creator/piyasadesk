@echo off
REM ============================================================
REM  Hisse Haber Merkezi -- tek tikla baslat
REM
REM  Iki ayri surec baslatir:
REM    1) collector  -- aga cikan toplayici (5 dakikada bir)
REM    2) uvicorn    -- salt-okunur arayuz sunucusu
REM  Sonra tarayiciyi acar.
REM
REM  Kapatmak icin: acilan iki siyah pencereyi kapat.
REM ============================================================
cd /d "%~dp0"

echo [1/3] Toplayici baslatiliyor (5 dakikada bir)...
start "Hisse Haber - Toplayici" cmd /k python -m haber.collector --loop 300

echo [2/3] Arayuz sunucusu baslatiliyor...
start "Hisse Haber - Sunucu" cmd /k python -m uvicorn haber.api:app --host 127.0.0.1 --port 8000

echo [3/3] Tarayici aciliyor...
timeout /t 4 /nobreak >nul
start http://127.0.0.1:8000

echo.
echo Hazir. Iki pencere acik kalmali.
echo Kapatmak icin o pencereleri kapatin.
timeout /t 5 /nobreak >nul
