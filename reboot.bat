:: Tento skript byl upraven pomocí Gemini API
@echo off
title Restarting AI Code Box...

echo Ukoncuji vsechny Python procesy...
:: Použijeme >nul 2>&1 pro skrytí chybových hlášek, pokud proces neběží
taskkill /f /im pythonw.exe >nul 2>&1
taskkill /f /im python.exe >nul 2>&1

echo Cekam 2 sekundy na uvolneni systemu...
timeout /t 2 /nobreak >nul

echo Spoustim AI Code Box znovu ve virtualnim prostredi...
:: Změníme adresář na umístění tohoto .bat souboru
cd /d "%~dp0"

:: Spustíme aplikaci pomocí Pythonu z našeho .venv
start "AI Code Box" /d "%~dp0" .\.venv\Scripts\python.exe ai_codebox_app.py

exit