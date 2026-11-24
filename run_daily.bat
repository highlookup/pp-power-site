@echo off
chcp 65001 >nul
rem pp-power-site daily update - FALLBACK ONLY (pure safety net)
rem
rem Primary updater is the cloud: cron-job.org at 16:30/18:30/20:30 plus
rem GitHub Actions cron as backup. This local task is the last resort.
rem
rem Window: 21:00, repeat every 20 min for 3 hours (till 23:40), wake-to-run.
rem Behaviour: before 21:00 it exits immediately; after 21:00 it checks the
rem live site and only builds/uploads if the cloud genuinely failed.
rem Pass --force to skip both the time-window and the live-site checks.

set PATH=C:\Users\Paul\.local\share\TeleAgent\runtimes\python;C:\Program Files\GitHub CLI;C:\Program Files\Git\cmd;%PATH%
cd /d "%~dp0"

"C:\Users\Paul\.local\share\TeleAgent\runtimes\python\python.exe" "%~dp0update_local.py" %*
exit /b %ERRORLEVEL%