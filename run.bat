@echo off
title Gmail Reminder System Orchestration
color 0B
echo ====================================================================
echo               GMAIL REMINDER SYSTEM BOOTSTRAPPER
echo ====================================================================
echo.
echo [System Check] Checking project context...
cd /d "%~dp0"

echo [Step 1/3] Validating Python environment and dependencies...
pip install -r backend\requirements.txt

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Dependency installation failed! Please verify:
    echo   1. Python 3.8+ is installed on your system.
    echo   2. Python is added to your environment variables (PATH).
    echo.
    pause
    exit /b %errorlevel%
)

echo.
echo [Step 2/3] Preparing the local browser dashboard connection...
echo Launching http://127.0.0.1:8000 in your default browser in 2 seconds...
timeout /t 2 /nobreak >nul
start http://127.0.0.1:8000

echo.
echo [Step 3/3] Commencing FastAPI Uvicorn web server...
echo ====================================================================
echo NOTE: Do not close this terminal! Closing it will stop the system 
echo       from scanning your inbox and dispatching email notifications.
echo ====================================================================
echo.

python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] The backend server encountered an error and shut down.
    pause
)
