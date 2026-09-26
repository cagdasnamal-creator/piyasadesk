@echo off
REM ============================================================
REM  Telefondan/tabletten erisim icin baslat (ayni Wi-Fi agi)
REM
REM  Fark: sunucu 0.0.0.0 e baglanir, yani ayni agdaki diger
REM  cihazlar da erisebilir. Asagida yazdirilan adresi
REM  telefonun tarayicisina yazin.
REM
REM  NOT: Windows Guvenlik Duvari ilk seferde izin sorabilir --
REM  "Ozel aglar" icin izin verin.
REM ============================================================
cd /d "%~dp0"

echo Bu bilgisayarin ag adresleri:
ipconfig ^| findstr /i "IPv4"
echo.
echo Telefondan acmak icin: http://YUKARIDAKI-ADRES:8000
echo.

start "Hisse Haber - Toplayici" cmd /k python -m haber.collector --loop 300
start "Hisse Haber - Sunucu (ag)" cmd /k python -m uvicorn haber.api:app --host 0.0.0.0 --port 8000
timeout /t 4 /nobreak >nul
start http://127.0.0.1:8000
pause
