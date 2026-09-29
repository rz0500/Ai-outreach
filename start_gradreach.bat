@echo off
rem Keeps GradReach running: web app + background scheduler (lead discovery,
rem scheduled sends, follow-ups, reply monitoring). Restarts itself if it crashes.
cd /d "%~dp0"
:loop
python web_app.py >> gradreach.log 2>&1
timeout /t 30 /nobreak >nul
goto loop
