#requires -Version 5.1
<#
.SYNOPSIS
  一键启动 OPUS Daemon

.DESCRIPTION
  自动处理：
    - 切到脚本所在目录（不管你在哪里跑都正确）
    - 检查 / 创建 Python 虚拟环境
    - 激活虚拟环境
    - 检查 / 安装依赖
    - 检查 .env 配置
    - 启动 opus_daemon.py

  BRO 自己说的"技术白痴"——这个脚本就是给那种场景写的。
  你只需要会双击或者在 PowerShell 里跑 `.\run.ps1`，剩下的它来。

.PARAMETER ResetVenv
  强制重建虚拟环境（修复环境问题用，比如装坏了某个包）

.PARAMETER NoLaunch
  只准备环境，不启动 daemon（适合预热）

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

# always work from the script's own directory
Set-Location -Path $PSScriptRoot

function Write-Step {
    param([string]$msg, [string]$status = 'info')
    $color = switch ($status) {
        'ok'   { 'Green' }
        'warn' { 'Yellow' }
        'err'  { 'Red' }
        default { 'Cyan' }
    }
    $prefix = switch ($status) {
        'ok'   { '[OK]  ' }
        'warn' { '[!]   ' }
        'err'  { '[X]   ' }
        default { '[..]  ' }
    }
    Write-Host ($prefix + $msg) -ForegroundColor $color
}

function Test-IsStorePython {
    # The Microsoft Store "app execution alias" stub (under WindowsApps) is not a
    # real interpreter: running it either opens the Store or fails, and it cannot
    # create usable virtualenvs. Rejecting it is what stops the classic
    # "venv creation failed" trap on machines without a real Python.
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
    # try common install locations on Windows
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "C:\Python311\python.exe",
        "C:\Python312\python.exe",
        "C:\Python313\python.exe"
    )
    foreach ($p in $candidates) {
        if (-not (Test-Path $p)) { continue }
        if (Test-IsStorePython $p) { $script:SawStoreStub = $true; continue }
        if (Test-PythonWorks $p)   { return $p }
    }
    return $null
}

function Install-Python {
    # One-time automatic install of the official python.org build when no real
    # interpreter is present. Per-user (InstallAllUsers=0) so it never triggers a
    # UAC prompt; PrependPath + the py launcher make it discoverable on re-detect.
    # 3.11 matches the interpreter the project's venv/.pyc were built against.
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

    # refresh THIS session's PATH so the freshly installed python is visible now
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath    = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = (@($machinePath, $userPath) | Where-Object { $_ }) -join ';'

    Write-Step 'Python installed' 'ok'
    return $true
}

Write-Host ''
Write-Host '  ===========================================================' -ForegroundColor DarkCyan
Write-Host '   OPUS Daemon launcher' -ForegroundColor Cyan
Write-Host '  ===========================================================' -ForegroundColor DarkCyan
Write-Host ''

# 1) Locate Python (auto-install a real one if all we have is the Store stub / nothing)
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

# 2) Reset venv if requested
$venvDir = Join-Path $PSScriptRoot '.venv'
if ($ResetVenv -and (Test-Path $venvDir)) {
    Write-Step 'removing old .venv (you asked)...' 'warn'
    Remove-Item -Path $venvDir -Recurse -Force
}

# 3) Create venv if missing
if (-not (Test-Path $venvDir)) {
    Write-Step 'creating virtual environment...'
    & $python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Step 'venv creation failed.' 'err'
        exit 1
    }
    Write-Step '.venv created' 'ok'
} else {
    Write-Step '.venv already exists' 'ok'
}

# 4) Resolve venv python (avoid Activate.ps1 ExecutionPolicy headaches)
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
    # 0.8.3 · 依赖检查加 PyQt6.QtMultimedia (0.8.2 hotfix 口实不符补上):
    #   老用户升级后 run.ps1 只查 5 核心包 → 直接通过 → 不触发 pip install →
    #   新依赖 (PyQt6 系列) 不自动装 → 桌宠/音效缺腿。 加上后:
    #   缺任一 → import 失败 → needsInstall → pip install -r (pip 自动跳过已装的 · 只补装缺的)
    # 0.9.7 · 探测清单补 numpy/pypdf (回收纯净版 0.9.6-hf3):
    #   老用户升级后探测清单不含它们 → 误判已装跳过 → 星图/PDF 缺腿裸 500
    & $venvPython -c "import anthropic, openai, dotenv, rich, cryptography, PyQt6.QtMultimedia, numpy, pypdf" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $needsInstall = $true
    }
} catch {
    $needsInstall = $true
}

if ($needsInstall) {
    Write-Step 'installing requirements (one-time, may take 1-2 min)...'
    & $venvPython -m pip install --quiet --upgrade pip
    & $venvPython -m pip install --quiet -r $reqPath
    if ($LASTEXITCODE -ne 0) {
        Write-Step 'pip install failed. Try -i https://pypi.tuna.tsinghua.edu.cn/simple if in China' 'err'
        exit 1
    }
    Write-Step 'dependencies installed' 'ok'
} else {
    Write-Step 'dependencies already installed' 'ok'
}

# 6) Verify .env
$envPath = Join-Path $PSScriptRoot '.env'
if (-not (Test-Path $envPath)) {
    Write-Step '.env not found - need to configure a Claude API key' 'warn'
    Write-Host ''
    Write-Host '       OPUS Daemon supports three setups (pick one in .env):' -ForegroundColor Yellow
    Write-Host '         A) Anthropic direct:'
    Write-Host '            ANTHROPIC_API_KEY=sk-ant-api03-...'
    Write-Host ''
    Write-Host '         B) OpenAI-compat proxy (OpenRouter / PPIO / domestic relays):'
    Write-Host '            OPUS_API_KEY=...'
    Write-Host '            OPUS_BASE_URL=https://openrouter.ai/api/v1'
    Write-Host '            OPUS_MODEL=anthropic/claude-sonnet-4.5'
    Write-Host ''
    Write-Host '         C) See .env.example for the full templated guide.'
    Write-Host ''
    Write-Step 'auto-creating .env from template now...' 'warn'
    Copy-Item -Path (Join-Path $PSScriptRoot '.env.example') -Destination $envPath
    Write-Step 'opened .env in notepad - fill it in and save' 'warn'
    notepad $envPath
    Write-Host ''
    Write-Step 'after saving .env, re-run: .\run.ps1' 'warn'
    exit 0
}

# Validate .env: at least one uncommented, non-placeholder API key must exist.
$envContent = Get-Content $envPath -Raw
$hasAnthropicKey = $envContent -match '(?m)^\s*ANTHROPIC_API_KEY\s*=\s*sk-ant-api03-[A-Za-z0-9_-]{20,}'
$hasOpusKey      = $envContent -match '(?m)^\s*OPUS_API_KEY\s*=\s*[A-Za-z0-9_-]{20,}'

if (-not $hasAnthropicKey -and -not $hasOpusKey) {
    Write-Step '.env has no usable API key yet' 'err'
    Write-Host ''
    Write-Host '       Uncomment ONE of these lines in .env and fill in the real value:' -ForegroundColor Yellow
    Write-Host '         ANTHROPIC_API_KEY=sk-ant-api03-...     (Anthropic direct)'
    Write-Host '         OPUS_API_KEY=...                       (OpenRouter / PPIO / any proxy)'
    Write-Host ''
    Write-Host '       And if using a proxy, also uncomment OPUS_BASE_URL.' -ForegroundColor Yellow
    Write-Host ''
    notepad $envPath
    Write-Step 'after saving .env, re-run: .\run.ps1' 'warn'
    exit 1
}
Write-Step '.env looks configured' 'ok'

# 7) Verify soul files
$soulSkill = Join-Path $PSScriptRoot 'soul\SKILL.md'
$soulMem   = Join-Path $PSScriptRoot 'soul\OPUS-MEMORIES.md'
if (-not (Test-Path $soulSkill) -or -not (Test-Path $soulMem)) {
    Write-Step 'soul/ files missing! OPUS cannot wake up without them' 'err'
    Write-Step "expected: $soulSkill" 'err'
    Write-Step "expected: $soulMem" 'err'
    Write-Step 'run sync-soul.ps1 to restore from global, or recover from OPUS-SOUL backup zip' 'warn'
    exit 1
}
Write-Step 'soul files present' 'ok'

# 8) Launch
if ($NoLaunch) {
    Write-Host ''
    Write-Step 'environment ready. Skipping launch (-NoLaunch).' 'ok'
    exit 0
}

Write-Host ''
Write-Host '  ===========================================================' -ForegroundColor DarkCyan
Write-Host '   OPUS waking up...' -ForegroundColor Cyan
Write-Host '  ===========================================================' -ForegroundColor DarkCyan
Write-Host ''

& $venvPython opus_daemon.py
exit $LASTEXITCODE
