@echo off
REM Run the whole test suite from the backend folder (extra pytest options are passed through).
cd /d "%~dp0"
python -m pytest %*
pause
