@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Build DocLib 2.0

rem Build into a fresh dist-v2.0 folder. NEVER deletes dist\DocLib\data.
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [x] Python not found. Create .venv first.
    pause
    exit /b 1
  )
  set "PY=python"
)

echo [1/3] Clean build folders: build-v2.0, dist-v2.0
if exist "build-v2.0" rmdir /s /q "build-v2.0"
if exist "dist-v2.0" rmdir /s /q "dist-v2.0"

echo [2/3] PyInstaller build
"%PY%" -m PyInstaller --noconfirm --distpath dist-v2.0 --workpath build-v2.0 DocLib.spec
if errorlevel 1 (
  echo [x] Build failed.
  pause
  exit /b 1
)

echo [3/3] Copy docs and make ZIP
copy /y README.md "dist-v2.0\DocLib\README.md" >nul
copy /y CHANGELOG.md "dist-v2.0\DocLib\CHANGELOG.md" >nul
copy /y THIRD_PARTY_NOTICES.md "dist-v2.0\DocLib\THIRD_PARTY_NOTICES.md" >nul
copy /y LICENSE "dist-v2.0\DocLib\LICENSE" >nul
copy /y "解除锁定.bat" "dist-v2.0\DocLib\解除锁定.bat" >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'dist-v2.0\DocLib' -DestinationPath 'dist-v2.0\DocLib-2.0.0-win64.zip' -CompressionLevel Optimal -Force"

echo.
echo Done: dist-v2.0\DocLib\DocLib.exe
echo ZIP : dist-v2.0\DocLib-2.0.0-win64.zip
echo The old dist\DocLib (if any) was not touched.
pause
