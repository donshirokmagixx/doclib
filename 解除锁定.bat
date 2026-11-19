@echo off
setlocal
cd /d "%~dp0"
echo Removing "downloaded from the internet" marks (Zone.Identifier)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '%~dp0' -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue"
echo Done. You can start DocLib.exe now.
pause
