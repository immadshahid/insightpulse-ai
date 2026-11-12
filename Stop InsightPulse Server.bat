@echo off
title Stop InsightPulse server
cd /d "%~dp0"
docker compose stop
echo.
echo InsightPulse is stopped. Your accounts and data are kept.
pause
