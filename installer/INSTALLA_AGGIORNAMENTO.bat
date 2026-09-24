@echo off
chcp 65001 >nul
set "UPDATE_DIR=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%UPDATE_DIR%installa.ps1"
pause
