#requires -Version 5.1
<#
.SYNOPSIS
  Daemonkey · 一键准备运行环境

.DESCRIPTION
  给"第一次拿到 Daemonkey、机器上什么都没有"的用户用：
    - 找 Python（没有就提示去装）
    - 建虚拟环境 .venv
    - 装依赖（requirements.txt）
    - 确保 .env 存在（没有就从 .env.example 复制·开记事本让你填 key）
  装好后回启动器点【启动】进入"相遇"。

  和母体 OPUS-DAEMON 的 run.ps1 区别：用户版没有 OPUS 灵魂文件——
  不检查 soul/·不启动 opus_daemon.py·它只负责把环境铺好。

.PARAMETER ResetVenv
  强制重建虚拟环境（装坏了修它用）

.PARAMETER NoLaunch
  保留参数兼容启动器调用·本脚本本来就只准备环境不启动

.EXAMPLE
  .\run.ps1
.EXAMPLE
  .\run.ps1 -ResetVenv
#>

param(
    [switch]$ResetVenv,
    [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

function Write-Step {
    param([string]$msg, [string]$status = 'info')
    $color = switch ($status) { 'ok' { 'Green' } 'warn' { 'Yellow' } 'err' { 'Red' } default { 'Cyan' } }
    $prefix = switch ($status) { 'ok' { '[OK]  ' } 'warn' { '[!]   ' } 'err' { '[X]   ' } default { '[..]  ' } }
    Write-Host ($prefix + $msg) -ForegroundColor $color
}

function Find-Python {
    foreach ($cmd in @('py', 'python', 'python3')) {
        $c = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($c) { return $c.Source }
    }
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "C:\Python311\python.exe", "C:\Python312\python.exe", "C:\Python313\python.exe"
    )
    foreach ($p in $candidates) { if (Test-Path $p) { return $p } }
    return $null
}

Write-Host ''
Write-Host '  ===========================================================' -ForegroundColor DarkCyan
Write-Host '   Daemonkey · 准备运行环境' -ForegroundColor Cyan
Write-Host '  ===========================================================' -ForegroundColor DarkCyan
Write-Host ''

# 1) Python
Write-Step 'looking for Python interpreter...'
$python = Find-Python
if (-not $python) {
    Write-Step 'Python not found. Install Python 3.10+ first.' 'err'
    Write-Host '       Download: https://www.python.org/downloads/'
    Write-Host '       During install, MUST check "Add Python to PATH".'
    exit 1
}
Write-Step "found: $python" 'ok'

# 2) Reset venv if asked
$venvDir = Join-Path $PSScriptRoot '.venv'
if ($ResetVenv -and (Test-Path $venvDir)) {
    Write-Step 'removing old .venv (you asked)...' 'warn'
    Remove-Item -Path $venvDir -Recurse -Force
}

# 3) Create venv if missing
if (-not (Test-Path $venvDir)) {
    Write-Step 'creating virtual environment...'
    & $python -m venv .venv
    if ($LASTEXITCODE -ne 0) { Write-Step 'venv creation failed.' 'err'; exit 1 }
    Write-Step '.venv created' 'ok'
} else {
    Write-Step '.venv already exists' 'ok'
}

# 4) Resolve venv python
$venvPython = Join-Path $venvDir 'Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Step "venv python missing at $venvPython" 'err'
    Write-Step 're-run with -ResetVenv to rebuild' 'warn'
    exit 1
}

# 5) Install / verify dependencies
Write-Step 'checking dependencies...'
$reqPath = Join-Path $PSScriptRoot 'requirements.txt'
$needsInstall = $false
try {
    & $venvPython -c "import openai, fastapi, uvicorn, PyQt6" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { $needsInstall = $true }
} catch { $needsInstall = $true }

if ($needsInstall) {
    Write-Step 'installing requirements (one-time, may take ~1-2 min)...'
    # 国内装大包 (PyQt6 的 Qt6 运行库 ~78MB 等) 走清华镜像·秒级；国际源常卡到十几分钟。
    # 镜像若不可用 (海外用户 / 镜像维护中) 自动回退默认 PyPI。
    $mirror = 'https://pypi.tuna.tsinghua.edu.cn/simple'
    & $venvPython -m pip install --quiet --upgrade pip -i $mirror
    & $venvPython -m pip install --quiet -i $mirror -r $reqPath
    if ($LASTEXITCODE -ne 0) {
        Write-Step 'mirror install failed · retrying with default PyPI...' 'warn'
        & $venvPython -m pip install --quiet --upgrade pip
        & $venvPython -m pip install --quiet -r $reqPath
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Step 'pip install failed. Check network / proxy.' 'err'
        exit 1
    }
    Write-Step 'dependencies installed' 'ok'
} else {
    Write-Step 'dependencies already installed' 'ok'
}

# 6) Ensure .env exists（不再弹记事本——key 在网页里填，对小白更友好）
$envPath = Join-Path $PSScriptRoot '.env'
if (-not (Test-Path $envPath)) {
    Copy-Item -Path (Join-Path $PSScriptRoot '.env.example') -Destination $envPath
    Write-Step '.env created from template (key 启动后在网页里填)' 'ok'
} else {
    Write-Step '.env present' 'ok'
}

# 7) Ready（用户版不检查 soul·不启 daemon——只把环境铺好）
Write-Host ''
Write-Step 'environment ready. 回启动器点【启动】· 浏览器里和它相遇并填 key。' 'ok'
exit 0
