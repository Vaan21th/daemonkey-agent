#requires -Version 5.1
<#
.SYNOPSIS
  把 tools/DaemonkeyBoot.cs 编成 Daemonkey.exe（用户双击的入口）。
  真·WinForms 薄壳：双击立刻画闪屏 + 单实例 + 拉起 daemonkey-launcher.ps1。
  不用 ps2exe —— 那个宿主自己就要醒 2 秒多，闪屏再快也赶不上。
  改肉不需要重编；改闪屏布局 / 壳逻辑才跑本脚本。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\build-boot-exe.ps1
#>

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$cs   = Join-Path $PSScriptRoot 'DaemonkeyBoot.cs'
$exe  = Join-Path $root 'Daemonkey.exe'
$ico  = Join-Path $root 'assets\daemonkey.ico'

if (-not (Test-Path $cs)) { throw "找不到 $cs" }

$running = Get-Process -Name 'Daemonkey' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe }
if ($running) {
    Write-Host "[!] 本目录的 Daemonkey.exe 正在运行 (pid=$($running.Id -join ','))·先关掉它再重编" -ForegroundColor Yellow
    exit 1
}

$csc = @(
    (Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'),
    (Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe')
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $csc) { throw '找不到 csc.exe · 需要 .NET Framework 4 开发机才能编壳' }

$args = @(
    '/nologo',
    '/optimize+',
    '/target:winexe',
    '/platform:anycpu',
    '/codepage:65001',
    '/utf8output',
    '/r:System.Windows.Forms.dll',
    '/r:System.Drawing.dll',
    "/out:$exe"
)
if (Test-Path $ico) { $args += "/win32icon:$ico" }
$args += $cs

Write-Host "csc  $cs"
& $csc @args
if ($LASTEXITCODE -ne 0) { throw "csc 失败 exit=$LASTEXITCODE" }

$info = Get-Item $exe
Write-Host "[OK] 已重编 $($info.Name) · $([int]($info.Length/1024)) KB · $($info.LastWriteTime)" -ForegroundColor Green
