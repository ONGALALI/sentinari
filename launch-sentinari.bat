@echo off
REM ============================================================
REM  launch-sentinari.bat - Sentinari core launcher (formerly
REM  launch-smi-core.bat; old name kept working where referenced).
REM ============================================================

set "ROOT=%~dp0"
if not exist "%ROOT%Logs" mkdir "%ROOT%Logs"
set "LOG=%ROOT%Logs\launch-sentinari-core.log"
set "LEGACY_LOG=%ROOT%Logs\launch-smi-core.log"
set "SENTINARI_SHARED_SKILLS_ROOT=%ROOT%data\skills"

echo.
echo SENTINARI CORE LAUNCHER
echo -----------------------
echo Starting Sentinari core on 127.0.0.1:8099 ...
echo.
echo [%date% %time%] Launch-Sentinari-Core started > "%LOG%"

REM Python runtime (shared virtual environment)
set "PYTHON=%ROOT%.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo Could not find Python runtime at %PYTHON%
    pause
    exit /b 1
)

REM If a Sentinari core server already answers, never spawn a duplicate -
REM two servers share one SQLite database and lock each other out.
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $h=Invoke-RestMethod -Uri 'http://127.0.0.1:8099/health' -TimeoutSec 2; if ($h.ok) { exit 0 } } catch {}; exit 1"
if not errorlevel 1 (
    echo Sentinari core is already running. Reusing the existing server...
    start "" "http://127.0.0.1:8099/ui/playground"
    pause
    exit /b 0
)

REM Start the FastAPI server via the plain entrypoint
echo Starting Sentinari Core Server...
start "Sentinari Core" /min cmd /c "cd /d "%ROOT%" && echo Sentinari Core Active && set SENTINARI_SHARED_SKILLS_ROOT=%SENTINARI_SHARED_SKILLS_ROOT% && set OLLAMA_GPU_OVERRIDE=0 && "%PYTHON%" run_smi.py serve >> "%LOG%" 2>&1"

echo Waiting for Sentinari core to answer...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(25); do { try { $h=Invoke-RestMethod -Uri 'http://127.0.0.1:8099/health' -TimeoutSec 2; if ($h.ok) { exit 0 } } catch {}; Start-Sleep -Milliseconds 700 } while ((Get-Date) -lt $deadline); exit 1"

if errorlevel 1 (
    echo Sentinari core did not answer in time. Check the log: %LOG%
    echo Previous run log (if any): %LEGACY_LOG%
    pause
    exit /b 1
)

echo Sentinari core is running. Opening playground...
start "" "http://127.0.0.1:8099/ui/playground"
pause
