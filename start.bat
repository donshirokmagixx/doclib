@echo off
chcp 65001 >nul
setlocal
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
title DocLib 个人 Word 资料库

echo.
echo   DocLib - 个人 Word 资料库
echo   ---------------------------------------------
echo.

set "PY="
for %%P in (
  "C:\ProgramData\anaconda3\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
) do (
  if not defined PY if exist %%P (
    %%P -c "import sys" >nul 2>nul && set "PY=%%~P"
  )
)

if not defined PY (
  for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined PY (
      echo %%P | findstr /i "WindowsApps" >nul || set "PY=%%P"
    )
  )
)

if not defined PY (
  echo   [x] 没有找到可用的 Python 3.10 或更高版本。
  echo.
  echo       请安装 Python: https://www.python.org/downloads/
  echo       安装时务必勾选 "Add Python to PATH"。
  echo.
  pause
  exit /b 1
)

echo   使用 Python : %PY%
echo   正在启动，浏览器会自动打开（端口以窗口内显示的地址为准）
echo   停止方法   : 在本窗口按 Ctrl+C，或直接关掉本窗口
echo.

"%PY%" -m doclib serve
set "CODE=%ERRORLEVEL%"

echo.
if "%CODE%"=="3" (
  echo   已有 DocLib 在运行，浏览器已为你打开对应界面。
  echo   本窗口无需保留，2 秒后自动关闭。
  ping -n 3 127.0.0.1 >nul 2>&1
  exit /b 0
)
if "%CODE%"=="4" (
  echo   [x] 端口 8765 被其它程序占用，DocLib 无法启动。
  echo       请关闭占用该端口的程序，或改用其它端口：
  echo         "%PY%" -m doclib serve --port 8766
  echo.
  pause
  exit /b 0
)
if not "%CODE%"=="0" (
  echo   [x] DocLib 异常退出（错误码 %CODE%）。
  echo       请把上面的报错信息截图发给 AI 助手。
  echo       也可以先运行同目录下的 诊断.bat 检查环境。
) else (
  echo   DocLib 已停止。
)
echo.
pause
