@echo off
title Sentinari Autonomous Meta-Pattern Discovery Stream
cd /d %~dp0
echo ===============================================================================
echo Starting Sentinari Autonomous Meta-Pattern Discovery Stream Daemon
echo Conceived, Researched & Engineered by Dr. Pierre C. Wepener
echo ===============================================================================
.\.venv\Scripts\python.exe scripts\meta_discovery_stream.py --daemon --delay 3.0
pause
