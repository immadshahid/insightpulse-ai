@echo off
title InsightPulse server
cd /d "%~dp0"
where docker >nul 2>&1 || (
  echo Docker is not installed. Install Docker Desktop, then run this again.
  pause & exit /b 1
)
docker info >nul 2>&1 || (
  echo Docker Desktop is not running. Open it from the Start menu, wait until it says
  echo "Engine running", then run this again.
  pause & exit /b 1
)
echo Starting InsightPulse in Docker. The first start downloads and builds everything
echo and can take 10 minutes or more; later starts take seconds.
echo.
docker compose up -d --build || (pause & exit /b 1)
echo.
echo Waiting for the server to answer...
for /l %%i in (1,1,60) do (
  curl -sf http://127.0.0.1:8000/health >nul 2>&1 && goto :up
  timeout /t 3 /nobreak >nul
)
echo The server did not answer. Recent log lines:
docker compose logs --tail 40 backend
pause & exit /b 1

:up
echo.
echo InsightPulse is running. You can close this window: the server keeps running
echo whenever Docker Desktop is open, and starts again with it.
echo.
echo   Android emulator:  http://10.0.2.2:8000
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.PrefixOrigin -eq 'Dhcp' } | Select-Object -First 1).IPAddress"`) do echo   Phone on Wi-Fi:    http://%%a:8000
echo.
echo To stop it, run "Stop InsightPulse Server.bat".
pause
