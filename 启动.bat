@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 企业信用一键截图工具 - 启动器

set PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe
if not exist "%PY%" set PY=python

rem ---- 检查依赖（playwright / pillow / fastapi / uvicorn），缺失则安装 ----
"%PY%" -c "import playwright, PIL, fastapi, uvicorn" >nul 2>&1
if errorlevel 1 (
  echo [提示] 缺少依赖，正在安装 playwright 与 pillow 与 fastapi 与 uvicorn ...
  "%PY%" -m pip install playwright pillow fastapi uvicorn
  if errorlevel 1 (
    echo [错误] 依赖安装失败，请检查网络后重试
    pause
    exit /b 1
  )
  echo [提示] 依赖安装完成
)

rem ---- 以无控制台窗口方式启动图形界面 ----
echo [提示] 正在启动图形界面 ...
for %%f in ("%~dp0*.vbs") do start "" wscript "%%f"
exit
