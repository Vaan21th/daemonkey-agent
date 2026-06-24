@echo off
chcp 65001 >nul
rem ============================================================
rem  Daemonkey repair console (emergency)
rem  Double-click when the main daemon will not start / WebUI is blank.
rem  Independent channel: talks to the LLM directly so the AI can
rem  diagnose, fix and verify itself via chat + tools. No git needed.
rem ============================================================
title Daemonkey Repair Console
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo  [repair] .venv not found - falling back to system python
  set "PY=python"
)

"%PY%" "%~dp0tools\repair_console.py" %*

echo.
echo  Repair console exited. Press any key to close.
pause >nul
