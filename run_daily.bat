@echo off
rem 购买力顶底模型站点 · 每日更新（Windows 计划任务 16:30 调用）
rem 由 update_local.py 完成：构建 -> 比对 -> 上传 -> 对齐

set PATH=C:\Users\Paul\.local\share\TeleAgent\runtimes\python;C:\Program Files\GitHub CLI;C:\Program Files\Git\cmd;%PATH%
cd /d "%~dp0"

"C:\Users\Paul\.local\share\TeleAgent\runtimes\python\python.exe" "%~dp0update_local.py"
exit /b %ERRORLEVEL%