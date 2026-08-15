#requires -Version 5.1
<#
.SYNOPSIS
  把 launcher-boot.ps1（薄壳）编译成 Daemonkey.exe（用户双击的入口）。
  壳肉分离：exe 只做「定位根目录 → 拉起 daemonkey-launcher.ps1（肉）」。
  改肉（daemonkey-launcher.ps1）不需要重编 exe；只有改壳本身才跑本脚本。

.DESCRIPTION
  和 build-exe.ps1（编译肉的旧脚本）的区别：
    - build-exe.ps1  → 编译 daemonkey-launcher.ps1（肉）· 改 UI 就要重编 exe（旧架构）
    - build-boot-exe.ps1 → 编译 launcher-boot.ps1（薄壳）· exe 逻辑几乎不变 · 一辈子不用重编
  壳逻辑零环境假设（不探测 venv / 不查端口）· 启动画面/托盘/面板/崩溃自启全在肉里随版本升级。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\build-boot-exe.ps1
#>

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$ps1  = Join-Path $root 'launcher-boot.ps1'
$exe  = Join-Path $root 'Daemonkey.exe'
$ico  = Join-Path $root 'assets\daemonkey.ico'

if (-not (Test-Path $ps1)) { throw "找不到 $ps1" }

# 占用检查：只在跑的正是【本目录这个 exe】时才拦
# （按进程名拦会误伤同名的母体进程——它锁的是别的路径，不影响本目录重编）
$running = Get-Process -Name 'Daemonkey' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe }
if ($running) {
    Write-Host "[!] 本目录的 Daemonkey.exe 正在运行 (pid=$($running.Id -join ','))·先关掉它再重编" -ForegroundColor Yellow
    exit 1
}

# 语法 + BOM 自检（防把坏代码 / 乱码编进 exe）
$bom = [byte[]](Get-Content $ps1 -Encoding Byte -TotalCount 3)
if (-not ($bom[0] -eq 0xEF -and $bom[1] -eq 0xBB -and $bom[2] -eq 0xBF)) {
    Write-Host '[!] launcher-boot.ps1 缺 UTF-8 BOM·中文可能乱码·先补 BOM' -ForegroundColor Yellow
    exit 1
}
$errs = $null
$null = [System.Management.Automation.Language.Parser]::ParseFile($ps1, [ref]$null, [ref]$errs)
if ($errs) {
    Write-Host '[X] 语法错误·拒绝编译:' -ForegroundColor Red
    $errs | ForEach-Object { Write-Host "    $($_.Message)" -ForegroundColor Red }
    exit 1
}

Import-Module ps2exe -ErrorAction Stop
$buildArgs = @{
    inputFile   = $ps1
    outputFile  = $exe
    noConsole   = $true
    title       = 'Daemonkey'
    product     = 'Daemonkey'
    description = "Daemonkey - an AI that doesn't say goodbye"
}
if (Test-Path $ico) { $buildArgs.iconFile = $ico }

Invoke-ps2exe @buildArgs
$info = Get-Item $exe
Write-Host "[OK] 已重编 $($info.Name) · $([int]($info.Length/1024)) KB · $($info.LastWriteTime)" -ForegroundColor Green
