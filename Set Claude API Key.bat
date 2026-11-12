@echo off
title InsightPulse - set Claude API key
cd /d "%~dp0"
docker info >nul 2>&1 || (
  echo Docker Desktop is not running. Open it, then run this again.
  pause & exit /b 1
)
if not exist .env type nul > .env
docker compose run --rm --no-deps -e INSIGHTPULSE_ENV_FILE=/work/.env -v "%~dp0.env:/work/.env" backend python set_api_key.py || (pause & exit /b 1)
echo.
echo Restarting the server so it uses the key...
docker compose up -d --force-recreate backend
echo Done. Ask AI now uses Claude.
pause
