@echo off
chcp 65001 >nul
title 智选志愿 - 后端 FastAPI :8000
cd /d "%~dp0..\backend"

rem 本机专用 Python 路径写在 scripts\local-paths.bat（已被 .gitignore 忽略），
rem 避免把个人绝对路径提交到公开仓库。没有该文件时按下面的顺序自动探测。
set "PY="
if exist "%~dp0local-paths.bat" call "%~dp0local-paths.bat"

if not defined PY if exist "%~dp0..\backend\.venv\Scripts\python.exe" set "PY=%~dp0..\backend\.venv\Scripts\python.exe"
if not defined PY set "PY=python"

"%PY%" -c "import uvicorn, fastapi" >nul 2>&1
if errorlevel 1 (
  echo.
  echo [错误] 当前 Python 未安装后端依赖：
  echo        %PY%
  echo 请先执行：
  echo        "%PY%" -m pip install -r requirements.txt
  echo 或在 scripts\local-paths.bat 中写一行：
  echo        set "PY=你的虚拟环境\Scripts\python.exe"
  echo.
  pause
  exit /b 1
)

echo ============================================================
echo  智选志愿 · 后端已启动
echo    接口地址   http://127.0.0.1:8000
echo    接口文档   http://127.0.0.1:8000/docs
echo    健康检查   http://127.0.0.1:8000/api/health
echo  停止服务：在本窗口按 Ctrl + C
echo ============================================================
echo.

"%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
echo.
echo 后端已退出。
pause
