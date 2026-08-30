@echo off
rem 1.0.0 · 有 exe 走薄壳（闪屏立刻出）· 否则直接拉肉
rem opus-launcher 仍作 GDI 兜底可手调 · 老 start.ps1 还在
chcp 65001 >nul
title Daemonkey
cd /d "%~dp0"
if exist "%~dp0Daemonkey.exe" (
  start "" "%~dp0Daemonkey.exe"
  exit /b 0
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0daemonkey-launcher.ps1" %*
if errorlevel 1 (
  echo.
  echo  启动器异常退出 · 按任意键关闭
  pause >nul
)
