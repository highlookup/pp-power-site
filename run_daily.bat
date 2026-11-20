@echo off
chcp 65001 >nul
rem Daily update for pp-power-site (called by Windows Task Scheduler 16:30-23:30 every 30 min)
rem update_local.py does: time-window check -> build -> compare -> upload -> verify -> align
rem Pass --force to skip the time window and idempotency checks.

set PATH=C:\Users\Paul\.local\share\TeleAgent\runtimes\python;C:\Program Files\GitHub CLI;C:\Program Files\Git\cmd;%PATH%
cd /d "%~dp0"

"C:\Users\Paul\.local\share\TeleAgent\runtimes\python\python.exe" "%~dp0update_local.py" %*
exit /b %ERRORLEVEL%