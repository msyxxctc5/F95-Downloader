@echo off
title AkinaSync - F95zone Collection Updater
cd /d "%~dp0"
echo Starting AkinaSync Server on http://127.0.0.1:8899 ...
python -m uvicorn server:app --host 127.0.0.1 --port 8899
pause
