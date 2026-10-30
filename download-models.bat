@echo off
setlocal
cd /d "%~dp0"
echo =================================================================
echo   SENTINARI FOUNDATION MODEL SETUP (ACE-STEP 1.5 ^& WAN 2.1 14B)
echo   Conceived by Dr. Pierre C. Wepener ^• Inspirari Initiative
echo =================================================================
echo.
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "scripts\download_foundation_models.py"
) else (
    python "scripts\download_foundation_models.py"
)
pause
