@echo off
REM ============================================================
REM  launch-smi-core.bat
REM  Starts the isolated SMI Standalone Instance.
REM ============================================================

set "ROOT=%~dp0"
if not exist "%ROOT%Logs" mkdir "%ROOT%Logs"
set "LOG=%ROOT%Logs\launch-smi-core.log"
set "SMI_SHARED_SKILLS_ROOT=%ROOT%data\skills"

echo.
echo SMI CORE STANDALONE LAUNCHER
echo -----------------------------
echo Starting isolated SMI instance...
echo.
echo [%date% %time%] Launch-SMI-Core started > "%LOG%"

REM Set Python path to the existing virtual environment
set "PYTHON=%ROOT%.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo Could not find Python runtime at %PYTHON%
    pause
    exit /b 1
)

REM If an SMi Core server already answers, never spawn a duplicate —
REM two servers share one SQLite database and lock each other out.
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $h=Invoke-RestMethod -Uri 'http://127.0.0.1:8099/health' -TimeoutSec 2; if ($h.ok) { exit 0 } } catch {}; exit 1"
if not errorlevel 1 (
    echo SMi Core is already running. Reusing the existing server...
    start "" "http://127.0.0.1:8099/ui/playground"
    pause
    exit /b 0
)

REM Start the FastAPI server via the plain entrypoint (no vault, no key)
echo Starting SMi Core Server...
start "SMi Core Standalone" cmd /k "cd /d ""%ROOT%"" && echo SMi Core Active && set SMI_SHARED_SKILLS_ROOT=%SMI_SHARED_SKILLS_ROOT% && set OLLAMA_GPU_OVERRIDE=0 && ""%PYTHON%"" run_smi.py serve >> ""%LOG%"" 2>&1"

echo Waiting for SMi Core to answer...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(25); do { try { $h=Invoke-RestMethod -Uri 'http://127.0.0.1:8099/health' -TimeoutSec 2; if ($h.ok) { exit 0 } } catch {}; Start-Sleep -Milliseconds 700 } while ((Get-Date) -lt $deadline); exit 1"

if errorlevel 1 (
    echo SMi Core did not answer in time. Check the log: %LOG%
    pause
    exit /b 1
)

echo SMi Core is running. Opening playground...
start "" "http://127.0.0.1:8099/ui/playground"
pause
