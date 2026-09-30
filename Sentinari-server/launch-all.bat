@echo off
REM ============================================================
REM  launch-all.bat — ONE startup for the whole stack
REM  Starts the Sentinari inference server (port 8100), waits
REM  for its health, then starts Sentinari core (port 8099) and
REM  opens the playground. One double-click instead of two.
REM ============================================================

set "ROOT=%~dp0..\"
set "SRV=%~dp0"
set "PYTHON=%ROOT%.venv\Scripts\python.exe"
set "LOGDIR=%ROOT%Logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
set "SRVLOG=%SRV%inference_server.log"
set "CORELOG=%LOGDIR%\launch-sentinari-core.log"

echo.
echo SENTINARI STACK LAUNCHER
echo ------------------------
echo 1/2  Inference server (port 8100)
echo 2/2  Sentinari core (port 8099)
echo.

if not exist "%PYTHON%" (
    echo Could not find Python runtime at %PYTHON%
    pause
    exit /b 1
)

REM ---- 1/2: inference server (start if not already answering) ----
REM Robust probe: REST first, then netstat fallback (some endpoint-protection
REM stacks intermittently refuse loopback connects from fresh processes).
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { [System.Net.WebRequest]::DefaultWebProxy = $null; $h=Invoke-RestMethod -Uri 'http://127.0.0.1:8100/health' -TimeoutSec 2; if ($h.ok) { exit 0 } } catch {}; if (Get-NetTCPConnection -LocalPort 8100 -State Listen -ErrorAction SilentlyContinue) { exit 0 }; exit 1"
if not errorlevel 1 (
    echo Inference server already running. Reusing it...
) else (
    echo Starting Sentinari inference server...
    start "Sentinari Inference" /min cmd /c "cd /d "%SRV%" && "%PYTHON%" server_onnx.py >> "%SRVLOG%" 2>&1"

    echo Waiting for inference health...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(30); do { try { [System.Net.WebRequest]::DefaultWebProxy = $null; $h=Invoke-RestMethod -Uri 'http://127.0.0.1:8100/health' -TimeoutSec 2; if ($h.ok) { exit 0 } } catch {}; if (Get-NetTCPConnection -LocalPort 8100 -State Listen -ErrorAction SilentlyContinue) { Start-Sleep -Milliseconds 1500; if (Get-NetTCPConnection -LocalPort 8100 -State Listen -ErrorAction SilentlyContinue) { exit 0 } }; Start-Sleep -Milliseconds 700 } while ((Get-Date) -lt $deadline); exit 1"
    if errorlevel 1 (
        echo Inference server did not answer in time. Check: %SRVLOG%
        echo Continuing with SMI core anyway - it does not depend on 8100 yet.
    ) else (
        echo Inference server is up ^(degraded mode is fine for now^).
    )
)

REM ---- 2/2: Sentinari core (same never-duplicate logic as launch-sentinari.bat) ----
REM NOTE: the bottom "Stack is up" open covers the already-running path too -
REM keep exactly ONE browser-open in this file (§50: start "" silently no-ops).
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { [System.Net.WebRequest]::DefaultWebProxy = $null; $h=Invoke-RestMethod -Uri 'http://127.0.0.1:8099/health' -TimeoutSec 2; if ($h.ok) { exit 0 } } catch {}; if (Get-NetTCPConnection -LocalPort 8099 -State Listen -ErrorAction SilentlyContinue) { exit 0 }; exit 1"
if not errorlevel 1 (
    echo Sentinari core already running. Reusing the existing server...
) else (
    echo Starting Sentinari Core Server...
    set "SENTINARI_SHARED_SKILLS_ROOT=%ROOT%data\skills"
    set "OLLAMA_GPU_OVERRIDE=0"
    start "Sentinari Core" /min cmd /c "cd /d "%ROOT%" && set SENTINARI_SHARED_SKILLS_ROOT=%ROOT%data\skills && set OLLAMA_GPU_OVERRIDE=0 && "%PYTHON%" run_smi.py serve >> "%CORELOG%" 2>&1"

    echo Waiting for Sentinari core health...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(45); do { try { [System.Net.WebRequest]::DefaultWebProxy = $null; $h=Invoke-RestMethod -Uri 'http://127.0.0.1:8099/health' -TimeoutSec 2; if ($h.ok) { exit 0 } } catch {}; if (Get-NetTCPConnection -LocalPort 8099 -State Listen -ErrorAction SilentlyContinue) { Start-Sleep -Milliseconds 1500; if (Get-NetTCPConnection -LocalPort 8099 -State Listen -ErrorAction SilentlyContinue) { exit 0 } }; Start-Sleep -Milliseconds 700 } while ((Get-Date) -lt $deadline); exit 1"
    if errorlevel 1 (
        echo Sentinari core did not answer in time. Last log lines:
        powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Test-Path '%CORELOG%') { Get-Content '%CORELOG%' -Tail 8 } else { Write-Host '(log not found)' }"
        echo.
        echo The server MAY still be coming up. Check: http://127.0.0.1:8099/ui/playground
        pause
        exit /b 1
    )
)

echo.
echo Stack is up:
echo   Inference   : http://127.0.0.1:8100/health
echo   Sentinari   : http://127.0.0.1:8099/ui/start
call "%ROOT%open_url.bat" "http://127.0.0.1:8099/ui/start" "%CORELOG%"
pause
