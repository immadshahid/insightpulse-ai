@echo off
title InsightPulse server
rem Runs the server from the folder this file is in. Keep that folder's path short
rem (for example C:\InsightPulse) so Python stays under the Windows path length limit.
cd /d "%~dp0backend"
if not exist run_server.py (
  echo Could not find backend\run_server.py next to this file.
  pause
  exit /b 1
)
.venv\Scripts\python.exe run_server.py
echo.
echo The server has stopped.
pause
