#requires -Version 5.1
<#
.SYNOPSIS
  Daemonkey · 一键准备运行环境

.DESCRIPTION
  给"第一次拿到 Daemonkey、机器上什么都没有"的用户用：
    - 找 Python（只有商店假 python / 啥都没有 → 自动从 python.org 装一个真的）
    - 建虚拟环境 .venv
    - 装依赖（requirements.txt·国内走清华镜像）
    - 确保 .env 存在（没有就从 .env.example 复制·key 启动后在网页里填）
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

function Test-IsStorePython {
    # 微软商店那个 "app execution alias" 占位 python（WindowsApps 路径下）不是真解释器：
    # 跑它要么打开商店要么直接失败，更建不出可用的 venv。识别并跳过它，
    # 才能避开没装真 Python 的机器上经典的 "venv creation failed" 陷阱。
    param([string]$path)
    return ($path -like '*\WindowsApps\*')
}

function Test-PythonWorks {
    param([string]$path)
    try {
        & $path --version *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Find-Python {
    $script:SawStoreStub = $false

    foreach ($cmd in @('py', 'python', 'python3')) {
        $c = Get-Command $cmd -ErrorAction SilentlyContinue
        if (-not $c) { continue }
        if (Test-IsStorePython $c.Source) { $script:SawStoreStub = $true; continue }
        if (Test-PythonWorks $c.Source)   { return $c.Source }
    }
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "C:\Python311\python.exe", "C:\Python312\python.exe", "C:\Python313\python.exe"
    )
    foreach ($p in $candidates) {
        if (-not (Test-Path $p)) { continue }
        if (Test-IsStorePython $p) { $script:SawStoreStub = $true; continue }
        if (Test-PythonWorks $p)   { return $p }
    }
    return $null
}

function Install-Python {
    # 机器上没有真解释器时，一次性自动装官方 python.org 版本。
    # per-user（InstallAllUsers=0）不触发 UAC；PrependPath + py launcher 让重新探测能发现它。
    # 3.11 对齐项目 venv/.pyc 的构建解释器。
    $ver  = '3.11.9'
    $arch = if ([Environment]::Is64BitOperatingSystem) { 'amd64' } else { 'win32' }
    $file = if ($arch -eq 'amd64') { "python-$ver-amd64.exe" } else { "python-$ver.exe" }
    $url  = "https://www.python.org/ftp/python/$ver/$file"
    $dest = Join-Path $env:TEMP $file

    Write-Step "downloading Python $ver from python.org (~25 MB, one-time)..."
    try {
        $oldPref = $ProgressPreference
        $ProgressPreference = 'SilentlyContinue'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
        $ProgressPreference = $oldPref
    } catch {
        Write-Step "download failed: $($_.Exception.Message)" 'err'
        return $false
    }

    Write-Step 'installing Python silently (a progress window may appear, no clicks needed)...'
    try {
        $proc = Start-Process -FilePath $dest `
            -ArgumentList '/passive','InstallAllUsers=0','PrependPath=1','Include_launcher=1','Include_pip=1' `
            -Wait -PassThru
    } catch {
        Write-Step "could not run the installer: $($_.Exception.Message)" 'err'
        return $false
    }
    if ($proc.ExitCode -ne 0) {
        Write-Step "Python installer exited with code $($proc.ExitCode)" 'err'
        return $false
    }

    # 刷新本会话 PATH，让刚装好的 python 立刻可见
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath    = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = (@($machinePath, $userPath) | Where-Object { $_ }) -join ';'

    Write-Step 'Python installed' 'ok'
    return $true
}

Write-Host ''
Write-Host '  ===========================================================' -ForegroundColor DarkCyan
Write-Host '   Daemonkey · 准备运行环境' -ForegroundColor Cyan
Write-Host '  ===========================================================' -ForegroundColor DarkCyan
Write-Host ''

# 1) Python（只有商店假 python / 啥都没有时，自动装一个真的）
Write-Step 'looking for Python interpreter...'
$python = Find-Python
if (-not $python) {
    if ($script:SawStoreStub) {
        Write-Step 'only the Microsoft Store placeholder python (WindowsApps) is here - it cannot build a venv.' 'warn'
    } else {
        Write-Step 'no real Python found on this machine.' 'warn'
    }
    Write-Step 'doing a one-time automatic Python install for you...' 'warn'
    if (Install-Python) {
        $python = Find-Python
    }
}
if (-not $python) {
    Write-Step 'automatic install did not work. Please install Python manually, then re-run.' 'err'
    Write-Host ''
    if ($script:SawStoreStub) {
        Write-Host '       The python on PATH is the Microsoft Store placeholder (fake). Either:' -ForegroundColor Yellow
        Write-Host '         1) Install real Python 3.10+ from https://www.python.org/downloads/'
        Write-Host '            and CHECK "Add python.exe to PATH" during setup; or'
        Write-Host '         2) Turn the Store aliases OFF:'
        Write-Host '            Settings > Apps > App execution aliases'
        Write-Host '            > switch off python.exe and python3.exe'
    } else {
        Write-Host '       Download: https://www.python.org/downloads/'
        Write-Host '       During install, MUST check "Add python.exe to PATH".'
    }
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
    & $venvPython -c "import openai, fastapi, uvicorn, PyQt6, cryptography" 2>&1 | Out-Null
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
