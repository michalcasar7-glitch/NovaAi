@echo off
title Dr. Gemi - Spousteci skript

:: Zmeni adresar na umisteni tohoto .bat souboru
cd /d "%~dp0"

echo Aktivuji nouzove prostredi (.venv v emergency_agent)...
CALL .\.venv\Scripts\activate.bat

echo.
echo Spoustim server pro "Dr. Gemi"...
:: Prikaz START spusti server v novem, neblokujicim okne
start "Dr. Gemi - Server" python app.py

echo.
echo Cekam 3 sekundy, nez se server plne spusti...
:: Timeout nam da chvilku cas, aby se Flask server stihl nacetl
timeout /t 3 /nobreak >nul

echo Oteviram rozhrani v prohlizeci Chrome...
:: Spustime Chrome s nasi adresou
start "Chrome UI" "C:\Program Files\Google\Chrome\Application\chrome.exe" "http://127.0.0.1:5000"

echo.
echo Hotovo. Server bezi na pozadi a rozhrani je otevrene.