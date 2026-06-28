@echo off
REM One-click launcher for AI Edge Monitor local dashboard.
REM Detects Python, installs the package if needed, and opens the dashboard.

setlocal EnableDelayedExpansion

set "PYTHON_CMD="
set "PIP_CMD="

REM 1. Try to find python / python3
where python >nul 2>&1 && set "PYTHON_CMD=python"
if not defined PYTHON_CMD (
  where python3 >nul 2>&1 && set "PYTHON_CMD=python3"
)

if not defined PYTHON_CMD (
  echo [ERROR] Python not found. Please install Python 3.8+ from https://www.python.org
  pause
  exit /b 1
)

echo [INFO] Using Python: %PYTHON_CMD%
for /f "delims=" %%i in ('%PYTHON_CMD% --version') do echo [INFO] %%i

set "PIP_CMD=%PYTHON_CMD% -m pip"

REM 2. Ensure the package is installed in editable mode
if exist "pyproject.toml" (
    echo [INFO] Installing / updating ai-edge-monitor ...
    %PIP_CMD% install -q -e ".[all]" || (
        echo [ERROR] Failed to install package. See error above.
        pause
        exit /b 1
    )
) else (
    echo [WARNING] pyproject.toml not found in current directory. Assuming package is already installed.
)

REM 3. Start the monitor with web dashboard
set "PORT=8080"
echo [INFO] Starting ai-edge-monitor web dashboard on port %PORT% ...
start /b %PYTHON_CMD% -m cli.__main__ dashboard --port %PORT% > ai-edge-monitor.log 2>&1

REM 4. Wait a moment for the server to start
timeout /t 3 /nobreak >nul

REM 5. Open browser
echo [INFO] Opening dashboard in default browser ...
start http://localhost:%PORT%

echo [INFO] Monitor is running in the background. Logs: ai-edge-monitor.log
echo [INFO] Press any key to stop.
pause >nul

REM 6. Stop background process on exit
taskkill /f /im python.exe >nul 2>&1
taskkill /f /im python3.exe >nul 2>&1

endlocal
