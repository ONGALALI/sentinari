@echo off
REM ============================================================
REM  launch-sentinari.bat - Sentinari core launcher (formerly
REM  launch-smi-core.bat; old name kept working where referenced).
REM
REM  HOTFIX (§49): the §45 rewrite used a pure REST health probe.
REM  This box intermittently refuses loopback connects from fresh
REM  processes (endpoint-protection quirk - see 0fc32c1, which fixed
REM  the same thing in launch-all.bat). The wait loop then timed out
REM  WHILE the server was already running and never opened the
REM  browser. Both probes now fall back to a netstat listener check,
REM  carry the DefaultWebProxy=$null hardening, and the wait window
REM  is 45s (launch-all.bat parity).
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
REM Robust probe: REST first, then netstat listener fallback.
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { [System.Net.WebRequest]::DefaultWebProxy = $null; $h=Invoke-RestMethod -Uri 'http://127.0.0.1:8099/health' -TimeoutSec 2; if ($h.ok) { exit 0 } } catch {}; if (Get-NetTCPConnection -LocalPort 8099 -State Listen -ErrorAction SilentlyContinue) { exit 0 }; exit 1"
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
REM Health first; if REST is refused but the port LISTENS, give the server
REM 1.5s to finish booting and re-check both. Deadline 45s (cold boots run
REM auto-ingest startup work; launch-all.bat uses the same window).
powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(45); do { try { [System.Net.WebRequest]::DefaultWebProxy = $null; $h=Invoke-RestMethod -Uri 'http://127.0.0.1:8099/health' -TimeoutSec 2; if ($h.ok) { exit 0 } } catch {}; if (Get-NetTCPConnection -LocalPort 8099 -State Listen -ErrorAction SilentlyContinue) { Start-Sleep -Milliseconds 1500; if (Get-NetTCPConnection -LocalPort 8099 -State Listen -ErrorAction SilentlyContinue) { exit 0 } }; Start-Sleep -Milliseconds 700 } while ((Get-Date) -lt $deadline); exit 1"

if errorlevel 1 (
    echo Sentinari core did not answer in time. Check the log: %LOG%
    echo Previous run log (if any): %LEGACY_LOG%
    pause
    exit /b 1
)

echo Sentinari core is running. Opening playground...
start "" "http://127.0.0.1:8099/ui/playground"
pause
