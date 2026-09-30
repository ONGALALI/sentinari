@echo off
REM ============================================================
REM  open_url.bat - open a URL in the default browser, with a
REM  fallback chain and logging.
REM
REM  WHY THIS EXISTS (§50): `start "" "http://..."` inside the
REM  launcher silently did nothing on the owner's session (server
REM  was up, wait loop passed, no browser appeared). We now try:
REM    1. PowerShell Start-Process (shell Execute, honours UserChoice)
REM    2. rundll32 url.dll,FileProtocolHandler (bare ShellExecute)
REM  and log which path fired to %LOG% (passed as arg 2).
REM  Usage: call open_url.bat "http://..." "%LOG%"
REM ============================================================
setlocal
set "URL=%~1"
set "LOGFILE=%~2"

if "%URL%"=="" exit /b 1

powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Start-Process '%URL%' -ErrorAction Stop; exit 0 } catch { exit 1 }"
if not errorlevel 1 (
    if not "%LOGFILE%"=="" echo [%date% %time%] Browser open via PowerShell Start-Process: %URL% >> "%LOGFILE%"
    endlocal & exit /b 0
)

start "" rundll32 url.dll,FileProtocolHandler "%URL%"
if not "%LOGFILE%"=="" echo [%date% %time%] Browser open via rundll32 fallback: %URL% >> "%LOGFILE%"
endlocal & exit /b 0
