#!/usr/bin/env pwsh
# 安装 git 钩子 · 把 tools/git-hooks/* 拷进 .git/hooks/
#
# 为什么需要: .git/ 不进版本控制 · 钩子真相源在 tools/git-hooks/ ·
# 重新 clone / 用户拉下来后 · 跑一次这个脚本才有 pre-commit 保护。
# (Daemonkey 的 pre-commit 会在 launcher 变动时自动重编 Daemonkey.exe 保鲜)
#
# 用法: 在工程根目录跑  powershell -ExecutionPolicy Bypass -File tools\install_hooks.ps1
$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent $PSScriptRoot
$src = Join-Path $ROOT "tools\git-hooks"
$dst = Join-Path $ROOT ".git\hooks"

if (-not (Test-Path (Join-Path $ROOT ".git"))) {
    Write-Host "[install_hooks] 这里不是 git 仓库 (.git 不存在) · 先 git init" -ForegroundColor Red
    exit 1
}
New-Item -ItemType Directory -Force -Path $dst | Out-Null

Get-ChildItem -Path $src -File | ForEach-Object {
    $target = Join-Path $dst $_.Name
    Copy-Item -Path $_.FullName -Destination $target -Force
    # 类 Unix 环境 (git bash) 需要可执行位 · Windows 上 git 不看 · best-effort
    if (Get-Command chmod -ErrorAction SilentlyContinue) { chmod +x $target 2>$null }
    Write-Host "[install_hooks] 已装 $($_.Name) -> .git\hooks\" -ForegroundColor Green
}
Write-Host "[install_hooks] 完成 · 改 launcher 后 commit 会自动重编 Daemonkey.exe 保鲜" -ForegroundColor Cyan
