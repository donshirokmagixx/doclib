@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title 打包 DocLib

echo.
echo   ===== 打包 DocLib �? exe =====
echo.

set "PY="
for %%P in (
  "C:\ProgramData\anaconda3\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
) do (
  if not defined PY if exist %%P (
    %%P -c "import sys" >nul 2>nul && set "PY=%%~P"
  )
)
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo   [x] 没找�? Python
  pause
  exit /b 1
)

echo   使用 Python: %PY%
echo   1/4 �?�? PyInstaller...
"%PY%" -c "import PyInstaller" 2>nul
if errorlevel 1 (
  echo   安�?? PyInstaller...
  "%PY%" -m pip install pyinstaller
)

rem ---- 关键：先把产品数�?�?到安全位�?（PyInstaller --noconfirm 会清�? dist\DocLib�?----
echo   2/4 备份产品数据...
if exist "dist\DocLib\data" (
  if exist "_pkgdata_tmp" rmdir /s /q "_pkgdata_tmp"
  move "dist\DocLib\data" "_pkgdata_tmp" >nul
  echo       已把 dist\DocLib\data 临时移到 _pkgdata_tmp
) else (
  echo       没有现成产品数据，稍后用 DocLib\data 生成
)

echo   3/4 �?始打包（�? 1-2 分钟，�?�稍等）...
"%PY%" -m PyInstaller --noconfirm --log-level WARN DocLib.spec
if errorlevel 1 (
  echo.
  echo   [x] 打包失败，�?�看上面的报错�??
  if exist "_pkgdata_tmp" (
    echo       正在还原产品数据...
    if exist "dist\DocLib\data" rmdir /s /q "dist\DocLib\data"
    move "_pkgdata_tmp" "dist\DocLib\data" >nul
  )
  pause
  exit /b 1
)

rem ---- 还原：优先用刚才移走的产品数�?，否则用源码数据 ----
echo   4/4 还原产品数据...
if exist "_pkgdata_tmp" (
  if exist "dist\DocLib\data" rmdir /s /q "dist\DocLib\data"
  move "_pkgdata_tmp" "dist\DocLib\data" >nul
  echo       已还原原产品数据
) else (
  if exist "data" (
    robocopy "data" "dist\DocLib\data" /E /NFL /NDL /NJH /NJS /NP /XD models >nul
    echo       已从 DocLib\data 复制�?份（不含 models�?
  )
)
if exist "build" rmdir /s /q "build"

echo.
echo   ===== 完成 =====
echo   产物: dist\DocLib\  (�? DocLibW.exe 原生窗口 / DocLib.exe 浏�?�器�? / data)
echo.
pause
