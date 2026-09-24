@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 avvia_bot.py
  goto fine
)
where python >nul 2>nul
if not errorlevel 1 (
  python avvia_bot.py
  goto fine
)
echo Python non trovato. Installa Python 3 da python.org con Tcl/Tk.
pause
exit /b 1
:fine
if errorlevel 1 pause
