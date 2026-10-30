@echo off
setlocal
cd /d "%~dp0"
echo Starting Sentinari Sovereign Desktop Co-Pilot...

if exist ".venv\Scripts\python.exe" (
    start "" ".venv\Scripts\python.exe" desktop_help_agent.py
) else (
    start "" python desktop_help_agent.py
)
exit /b 0
