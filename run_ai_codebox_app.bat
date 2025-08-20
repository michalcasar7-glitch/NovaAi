@echo off
title AI Code Box - Hlavni Aplikace

:: Zajisti, ze skript bezi ve svem vlastnim adresari
cd /d "%~dp0"

echo Aktivuji hlavni virtualni prostredi (.venv)...

:: TOTO JE TEN KLICOVY KROK: Aktivace virtualniho prostredi
CALL .\.venv\Scripts\activate.bat

echo.
echo Spoustim AI Code Box...
py ai_codebox_app.py

echo.
echo Aplikace AI Code Box byla ukoncena.
pause