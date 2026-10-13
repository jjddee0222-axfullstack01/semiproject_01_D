@echo off
REM Start the server from the backend folder, no matter where this is run from.
cd /d "%~dp0"
python -m uvicorn main:app --reload
pause
