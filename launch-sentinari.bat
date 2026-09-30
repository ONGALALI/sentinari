@echo off
REM ============================================================
REM  launch-sentinari.bat - Sentinari core launcher (formerly
REM  launch-smi-core.bat; old name kept working where referenced).
REM
REM  §50 FIX: the server was fine but no browser appeared. Evidence
REM  (Logs/launch-sentinari-core.log): the wait loop PASSED via the
REM  netstat fallback (endpoint protection refuses fresh-process
REM  loopback REST - same quirk as 0fc32c1), so the fault sat in the
REM  bare `start "" "http://..."` browser-open, which silently no-ops
REM  in some console contexts. All browser-opens now go through
REM  open_url.bat (PowerShell Start-Process with rundll32 fallback,
REM  method logged), and BOTH paths open /ui/start - the front-door
REM  launch menu - including the "already running" path that used to
REM  just print and exit.
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
    echo Sentinari core is already running. Opening the front door...
    call "%ROOT%open_url.bat" "http://127.0.0.1:8099/ui/start" "%LOG%"
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

echo Sentinari core is running. Opening the front door...
call "%ROOT%open_url.bat" "http://127.0.0.1:8099/ui/start" "%LOG%"
pause
