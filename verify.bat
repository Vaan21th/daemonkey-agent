@echo off
REM ============================================================
REM verify.bat · 卷四十六 III 补丁 5 · 一键自测 · 双击就跑
REM ============================================================
REM 干什么:
REM   1. 自动 cd 到工程根
REM   2. 用 .venv 的 python 跑 tools/self_verify.py
REM   3. 跑完汇总 PASS/FAIL · 留窗口看结果
REM 行为:
REM   - 7860 有 daemon 在跑 → 通过真 HTTP 测
REM   - 7860 没 daemon → 自动 TestClient fallback (in-process)
REM ============================================================
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [FAIL] 找不到 .venv\Scripts\python.exe
    echo        先跑 run.ps1 准备虚拟环境
    pause
    exit /b 2
)
".venv\Scripts\python.exe" "tools\self_verify.py"
set exit_code=%errorlevel%
echo.
echo ============================================================
if %exit_code% equ 0 (
    echo  ALL CHECKS PASSED
) else (
    echo  SOME CHECKS FAILED · exit code %exit_code%
)
echo ============================================================
echo.
pause
exit /b %exit_code%
