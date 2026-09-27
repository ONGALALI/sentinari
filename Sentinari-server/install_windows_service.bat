@echo off
REM Install the Sentinari ONNX inference server as a Windows service.
REM
REM Requires NSSM (Non-Sucking Service Manager) - a small, well-known
REM tool for running any executable as a proper Windows service.
REM Download once, on a connected machine, from nssm.cc, then carry
REM nssm.exe across to the interim Windows box the same way you'd
REM carry any other tool.
REM
REM EDIT the paths below to match your actual layout, then run this
REM script as Administrator.

set NSSM_PATH=C:\Tools\nssm\nssm.exe
set SERVICE_NAME=SentinariInference
set PYTHON_PATH=D:\inpirari\Sentinari\.venv\Scripts\python.exe
set SCRIPT_PATH=D:\inpirari\Sentinari\Sentinari-server\server_onnx.py
set WORKING_DIR=D:\inpirari\Sentinari\Sentinari-server

echo Installing %SERVICE_NAME% as a Windows service...

%NSSM_PATH% install %SERVICE_NAME% "%PYTHON_PATH%" "%SCRIPT_PATH%"
%NSSM_PATH% set %SERVICE_NAME% AppDirectory "%WORKING_DIR%"
%NSSM_PATH% set %SERVICE_NAME% DisplayName "Sentinari Inference Server (Gemma, ONNX, air-gapped)"
%NSSM_PATH% set %SERVICE_NAME% Start SERVICE_AUTO_START
%NSSM_PATH% set %SERVICE_NAME% AppStdout "%WORKING_DIR%\service_stdout.log"
%NSSM_PATH% set %SERVICE_NAME% AppStderr "%WORKING_DIR%\service_stderr.log"
%NSSM_PATH% set %SERVICE_NAME% AppRotateFiles 1

echo.
echo Done. Starting the service now...
%NSSM_PATH% start %SERVICE_NAME%

echo.
echo To check on it later:
echo   %NSSM_PATH% status %SERVICE_NAME%
echo To stop it:
echo   %NSSM_PATH% stop %SERVICE_NAME%
echo To remove it entirely:
echo   %NSSM_PATH% remove %SERVICE_NAME% confirm
echo.
echo Note: Windows Firewall may prompt on first run since the server
echo binds a local port. Allow it for Private/local networks only.
REM
REM AIR-GAP NOTE (superseded by owner decision, 2026-09-27):
REM This interim box IS internet-connected (cloud Gemini gateway in daily
REM use; the ONNX conversion phase will also run on a connected machine).
REM The strict air-gap discipline applies to the FUTURE rig: that machine
REM stays offline, gets models only by hand-carried transfer, and never
REM runs a conversion. The systemd unit (sentinari-inference.service) is
REM where offline enforcement actually belongs (IPAddressDeny=any).
pause
