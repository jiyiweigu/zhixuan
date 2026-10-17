@echo off
chcp 65001 >nul
title 智选志愿 - 前端 Vite :5173
cd /d "%~dp0..\frontend"

if not exist "node_modules\vite\bin\vite.js" (
  echo.
  echo [首次运行] 未检测到前端依赖，开始安装（耗时较长，请耐心等待）...
  echo.
  call npm install
  if errorlevel 1 (
    echo.
    echo [错误] 依赖安装失败，请检查网络后重试，或改用国内镜像：
    echo        npm config set registry https://registry.npmmirror.com
    echo.
    pause
    exit /b 1
  )
)

echo ============================================================
echo  智选志愿 · 前端已启动
echo    访问地址   http://127.0.0.1:5173
echo    管理端     http://127.0.0.1:5173/admin/login
echo  停止服务：在本窗口按 Ctrl + C
echo  说明：frontend\.env.local 已关闭 Mock，直连本机 8000 后端
echo ============================================================
echo.

call npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
echo.
echo 前端已退出。
pause
