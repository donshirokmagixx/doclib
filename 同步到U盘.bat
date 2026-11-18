@echo off
chcp 65001 >nul
title 同步 DocLib 到 U 盘（保留 data）
cd /d "%~dp0"
setlocal enabledelayedexpansion
set "SRC=%~dp0dist\DocLib"
set "DST="
for %%D in (D E F G H I J K L M N O P Q R S T U V W X Y Z) do (
  if exist "%%D:\MySoftWare_Vision1_1_0\DocLib.exe" if not defined DST set "DST=%%D:\MySoftWare_Vision1_1_0"
)
if not defined DST (
  echo.
  echo [x] 没找到 U 盘上的 MySoftWare_Vision1_1_0 目录。
  echo     请先插入 U 盘，并确认包在 U 盘根目录（...\MySoftWare_Vision1_1_0\DocLib.exe）。
  echo.
  pause
  exit /b 1
)
if not exist "%SRC%\DocLib.exe" (
  echo [x] 本地 dist\DocLib 不完整，请先打包。
  pause
  exit /b 1
)
echo 本地：%SRC%
echo 目标：%DST%
echo.
echo 正在同步程序文件（data 目录保持不动）...
robocopy "%SRC%" "%DST%" DocLib.exe DocLibW.exe /NJH /NJS /NP >nul
robocopy "%SRC%\_internal" "%DST%\_internal" /E /NFL /NDL /NJH /NJS /NP >nul
copy /y "%SRC%\*.bat" "%DST%\" >nul
copy /y "%SRC%\使用说明.txt" "%DST%\" >nul
if exist "%SRC%\UserNotesV1.0.0.docx" copy /y "%SRC%\UserNotesV1.0.0.docx" "%DST%\" >nul
echo.
echo 完成。U 盘上的 data 未改动；换电脑后先运行「解除锁定.bat」再启动。
pause
