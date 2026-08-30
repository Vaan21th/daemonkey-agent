#requires -Version 5.1
<#
.SYNOPSIS
  启动桌宠。默认小房间；-Cat 开旧橙猫彩蛋。
#>
param([switch]$Cat)

$ErrorActionPreference = 'Continue'
Set-Location -Path $PSScriptRoot

# 优先用 pythonw.exe 避免弹控制台
$pyw = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
$py  = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'

if (Test-Path $pyw) {
    $venvPython = $pyw
} elseif (Test-Path $py) {
    $venvPython = $py
} else {
    Write-Host "[X] venv python 不存在 · 先跑 .\run.ps1" -ForegroundColor Red
    exit 1
}

Write-Host ''
Write-Host '  ============================================================' -ForegroundColor DarkMagenta
Write-Host '   Daemonkey · 桌宠启动' -ForegroundColor Magenta
Write-Host '  ============================================================' -ForegroundColor DarkMagenta
Write-Host ''
Write-Host "  python: $venvPython" -ForegroundColor DarkGray
Write-Host ''

$petScript = Join-Path $PSScriptRoot 'desktop_pet\run.py'
if (-not (Test-Path $petScript)) {
    Write-Host "[X] 桌宠脚本不存在: $petScript" -ForegroundColor Red
    exit 1
}
$petErr = Join-Path $PSScriptRoot '_pet.err'
$al = @(('"{0}"' -f $petScript))
if ($Cat) { $al += '--cat' }
$proc = Start-Process -FilePath $venvPython `
    -ArgumentList $al `
    -WorkingDirectory $PSScriptRoot `
    -PassThru `
    -RedirectStandardError $petErr

Start-Sleep -Seconds 1
if ($proc -and $proc.HasExited) {
    Write-Host "[X] 桌宠 1 秒内退出 · 看 _pet.err" -ForegroundColor Red
    exit 1
}

if ($proc) {
    Write-Host "[OK] 桌宠已启动 (pid=$($proc.Id))" -ForegroundColor Green
    Write-Host ''
    Write-Host '  默认位置：屏幕右上角 · 拖动可移动 · 右键改大小' -ForegroundColor Gray
    Write-Host '  拖动房间 · 右键改大小 / 切状态 · 关守护面板她就回待机' -ForegroundColor Gray
    Write-Host ''
} else {
    Write-Host '[X] 桌宠启动失败' -ForegroundColor Red
    exit 1
}
