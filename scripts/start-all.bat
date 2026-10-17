@echo off
chcp 65001 >nul
title 智选志愿 - 一键启动
echo.
echo  正在启动「智选志愿」开发环境...
echo    1/3 后端 FastAPI   http://127.0.0.1:8000
echo    2/3 前端 Vite      http://127.0.0.1:5173
echo    3/3 打开浏览器
echo.

start "zhixuan-backend" cmd /k "%~dp0start-backend.bat"
timeout /t 3 /nobreak >nul
start "zhixuan-frontend" cmd /k "%~dp0start-frontend.bat"
timeout /t 6 /nobreak >nul
start "" http://127.0.0.1:5173

echo.
echo  已在新窗口启动前后端；关闭对应窗口即可停止服务。
echo  本窗口可以关闭。
timeout /t 5 >nul
