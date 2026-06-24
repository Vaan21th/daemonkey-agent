@echo off
chcp 65001 >nul
REM 紧急回档 · 双击就跑
REM   - 检查 git 可用 / 是 git 仓库（没有则引导改用维修台·绝不瞎跑）
REM   - 停 daemon · git stash 备份未提交改动 · git checkout master · 重启
REM   - master 起不来则自动回 opus-last-good · 弹窗如实告知（绝不谎报）

cd /d "%~dp0"
echo.
echo ============================================
echo   紧急回档启动 ...
echo ============================================
echo.
powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%~dp0tools\rollback_emergency.ps1"
set "RC=%errorlevel%"

echo.
echo ============================================
if "%RC%"=="0" (
  echo   回档完成 · 这个窗口可以关
  echo   现在去浏览器 Ctrl+Shift+R 强刷
  echo   http://127.0.0.1:7860/ui
) else if "%RC%"=="2" (
  echo   没法回档：缺 git 或不是 git 仓库（详见弹窗）
  echo   建议改用维修台 repair.bat —— 它不需要 git
) else (
  echo   回档执行了但 daemon 没起来（详见弹窗）
  echo   建议改用维修台 repair.bat 直连 AI 排查
)
echo ============================================
echo.
pause
