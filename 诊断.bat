@echo off
chcp 65001 >nul
setlocal
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
title DocLib 环境诊断

echo.
echo   ===== DocLib 环境诊断 =====
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
  echo   [x] 没找到 Python，请先安装 Python 3.10+ 并勾选 Add to PATH
  echo.
  pause
  exit /b 1
)

echo   1) Python：%PY%
"%PY%" -c "import sys,sqlite3;print('     Python 版本:',sys.version.split()[0]);print('     SQLite 版本:',sqlite3.sqlite_version)"
echo.

echo   2) 目录检查：
if exist "doclib\cli.py" (echo     doclib 代码目录: 存在) else (echo     [x] doclib 代码目录缺失)
if exist "data\doclib.db" (echo     数据库文件: 存在) else (echo     数据库文件: 不存在（首次运行会自动创建）)
if exist "doclib\web\static\index.html" (echo     界面文件: 存在) else (echo     [x] 界面文件缺失)
echo.

echo   3) 端口检查：
netstat -ano | findstr ":8765" | findstr "LISTENING"
if errorlevel 1 (echo     端口 8765 空闲，可以正常启动) else (echo     [!] 端口 8765 已被占用：多半是 DocLib 已经在运行，直接打开浏览器即可；要重启请先关掉旧的 DocLib 窗口)
echo.

echo   4) 程序自检：
"%PY%" -m doclib doctor
echo.

echo   5) 数据概况：
"%PY%" -m doclib tree
echo.

echo   ===== 诊断结束 =====
echo.
pause
