#requires -Version 5.1
<#
.SYNOPSIS
  把 opus-launcher.ps1 重新编译成 Daemonkey.exe (BRO 双击的入口)。

.DESCRIPTION
  铁律 (卷六十三续三补四 血泪): 改完 opus-launcher.ps1 必须跑这个·否则 BRO 双击的
  Daemonkey.exe 永远是旧的——渲染 .ps1 验证 ≠ 验收·BRO 的入口是 exe。
  exe 在 .gitignore·属构建产物·本地重建即可。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\build-exe.ps1
#>

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$ps1  = Join-Path $root 'daemonkey-launcher.ps1'
$exe  = Join-Path $root 'Daemonkey.exe'
$ico  = Join-Path $root 'assets\daemonkey.ico'

if (-not (Test-Path $ps1)) { throw "找不到 $ps1" }

# 占用检查: exe 正在跑会锁文件·先让 BRO 关掉
$running = Get-Process -Name 'Daemonkey' -ErrorAction SilentlyContinue
if ($running) {
    Write-Host "[!] Daemonkey.exe 正在运行 (pid=$($running.Id -join ','))·先关掉它再重编" -ForegroundColor Yellow
    exit 1
}

# 语法 + BOM 自检 (防把坏代码编进 exe)
$bom = [byte[]](Get-Content $ps1 -Encoding Byte -TotalCount 3)
if (-not ($bom[0] -eq 0xEF -and $bom[1] -eq 0xBB -and $bom[2] -eq 0xBF)) {
    Write-Host '[!] opus-launcher.ps1 缺 UTF-8 BOM·中文可能乱码·先补 BOM' -ForegroundColor Yellow
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
