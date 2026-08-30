#requires -Version 5.1
<#
.SYNOPSIS
  调试用 PowerShell 薄壳。用户双击的 Daemonkey.exe 已改 tools/DaemonkeyBoot.cs（csc 编）。
  本文件不再编进 exe · 只给不方便跑 exe 时用。
#>
$ErrorActionPreference = 'Continue'
$root = if ($PSScriptRoot) { $PSScriptRoot }
        elseif ($PSCommandPath) { Split-Path -Parent $PSCommandPath }
        else { try { Split-Path -Parent ([System.Reflection.Assembly]::GetEntryAssembly().Location) } catch { (Get-Location).Path } }
Set-Location -Path $root

function Write-BootStamp {
    param([string]$msg)
    try {
        $p = Join-Path $root 'data\runtime\launcher-boot.log'
        $d = Split-Path $p
        if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
        Add-Content -Path $p -Value ("{0} {1}" -f (Get-Date -Format 'HH:mm:ss.fff'), $msg) -Encoding UTF8
    } catch {}
}
Write-BootStamp 'boot-start'

$meat = Join-Path $root 'daemonkey-launcher.ps1'
if (-not (Test-Path $meat)) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        "找不到 daemonkey-launcher.ps1`r`n启动器文件不完整 · 请重新解压完整包。",
        'Daemonkey', [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
    exit 1
}

# 单实例 · 预编译程序集 · 不现场 csc（csc 冷启动能把闪屏再拖几秒）
$norm = $root.TrimEnd('\').ToLowerInvariant()
$sha = [System.Security.Cryptography.SHA256]::Create()
$hex = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($norm))).Replace('-', '').Substring(0, 16)
$sha.Dispose()
$mutexName = "Local\Daemonkey-$hex"
[bool]$createdNew = $false
$script:uiMutex = New-Object System.Threading.Mutex($true, $mutexName, [ref]$createdNew)
if (-not $createdNew) {
    Write-BootStamp 'already-running'
    try { Add-Type -AssemblyName Microsoft.VisualBasic } catch {}
    foreach ($t in @('Daemonkey-splash', 'Daemonkey')) {
        try { [Microsoft.VisualBasic.Interaction]::AppActivate($t); break } catch {}
    }
    try { $script:uiMutex.Dispose() } catch {}
    exit 0
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

function P { param([int]$x, [int]$y) New-Object System.Drawing.Point($x, $y) }
function Sz { param([int]$w, [int]$h) New-Object System.Drawing.Size($w, $h) }
function Get-RoundPath {
    param([int]$w, [int]$h, [int]$r)
    $d = $r * 2
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    if ($r -le 0) { $path.AddRectangle((New-Object System.Drawing.Rectangle(0, 0, $w, $h))); return $path }
    $path.AddArc(0, 0, $d, $d, 180, 90)
    $path.AddArc($w - $d - 1, 0, $d, $d, 270, 90)
    $path.AddArc($w - $d - 1, $h - $d - 1, $d, $d, 0, 90)
    $path.AddArc(0, $h - $d - 1, $d, $d, 90, 90)
    $path.CloseFigure()
    return $path
}

$skinId = 'daimon'
try {
    $sf = Join-Path $root 'data\runtime\launcher-skin.json'
    if (Test-Path $sf) {
        $j = Get-Content $sf -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($j.skin -in @('daimon', 'classic')) { $skinId = [string]$j.skin }
    }
} catch {}

$splashPath = Join-Path $root "assets\skins\$skinId\splash.png"
if (-not (Test-Path $splashPath)) { $splashPath = Join-Path $root 'assets\banner.png' }
$firstBoot = -not (Test-Path (Join-Path $root '.venv\Scripts\python.exe'))
$isDaimon = ($skinId -eq 'daimon')
$bg = if ($isDaimon) { [System.Drawing.Color]::FromArgb(253, 251, 246) } else { [System.Drawing.Color]::FromArgb(15, 16, 24) }

$script:splash = $null
$script:splashText = $null
$script:splashOk = $false
try {
    $script:splash = New-Object System.Windows.Forms.Form
    $script:splash.Text = 'Daemonkey-splash'
    $script:splash.FormBorderStyle = 'None'
    $script:splash.StartPosition = 'CenterScreen'
    $script:splash.Size = Sz 480 320
    $script:splash.BackColor = $bg
    $script:splash.TopMost = $true
    $script:splash.ShowInTaskbar = $false
    try { $script:splash.Region = New-Object System.Drawing.Region((Get-RoundPath 480 320 18)) } catch {}

    $footH = 72
    $mask = New-Object System.Windows.Forms.Panel
    $mask.Size = Sz 480 $footH
    $mask.Location = P 0 (320 - $footH)
    $mask.BackColor = if ($isDaimon) { [System.Drawing.Color]::FromArgb(247, 240, 228) } else { [System.Drawing.Color]::FromArgb(18, 19, 30) }
    $script:splash.Controls.Add($mask)
    $mask.BringToFront()

    $ink = if ($isDaimon) { [System.Drawing.Color]::FromArgb(67, 52, 34) } else { [System.Drawing.Color]::White }
    $muted = if ($isDaimon) { [System.Drawing.Color]::FromArgb(139, 115, 85) } else { [System.Drawing.Color]::FromArgb(168, 174, 196) }

    $stitle = New-Object System.Windows.Forms.Label
    $stitle.Text = '正在启动 Daemonkey'
    $stitle.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 11)
    $stitle.ForeColor = $ink
    $stitle.BackColor = $mask.BackColor
    $stitle.TextAlign = 'MiddleCenter'
    $stitle.Size = Sz 480 24
    $stitle.Location = P 0 8
    $mask.Controls.Add($stitle)

    $stxt = New-Object System.Windows.Forms.Label
    $stxt.Text = if ($firstBoot) { '第一次会慢一点 · 在准备运行环境' } else { '马上就好' }
    $stxt.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 9)
    $stxt.ForeColor = $muted
    $stxt.BackColor = $mask.BackColor
    $stxt.TextAlign = 'MiddleCenter'
    $stxt.Size = Sz 480 22
    $stxt.Location = P 0 34
    $mask.Controls.Add($stxt)
    $script:splashText = $stxt

    $barTrack = New-Object System.Windows.Forms.Panel
    $barTrack.Size = Sz 480 4
    $barTrack.Location = P 0 ($footH - 4)
    $barTrack.BackColor = if ($isDaimon) { [System.Drawing.Color]::FromArgb(220, 200, 168) } else { [System.Drawing.Color]::FromArgb(60, 70, 110) }
    $mask.Controls.Add($barTrack)
    $script:barFill = New-Object System.Windows.Forms.Panel
    $script:barFill.Size = Sz 96 4
    $script:barFill.Location = P 0 0
    $script:barFill.BackColor = if ($isDaimon) { [System.Drawing.Color]::FromArgb(201, 138, 75) } else { [System.Drawing.Color]::FromArgb(124, 108, 240) }
    $barTrack.Controls.Add($script:barFill)
    $script:barDir = 1
    $script:barPos = 0
    $barTimer = New-Object System.Windows.Forms.Timer
    $barTimer.Interval = 100
    $barTimer.Add_Tick({
        $script:barPos += $script:barDir * 32
        if ($script:barPos -ge 384) { $script:barPos = 384; $script:barDir = -1 }
        if ($script:barPos -le 0) { $script:barPos = 0; $script:barDir = 1 }
        try { $script:barFill.Location = P $script:barPos 0 } catch {}
    })
    $barTimer.Start()

    $script:splash.Show()
    $script:splash.Refresh()
    [System.Windows.Forms.Application]::DoEvents()
    $script:splashOk = $true
    Write-BootStamp 'splash-shown'

    # 图 1.5MB · 先出字再铺图，免得解图把「马上就好」再拖半秒
    if (Test-Path $splashPath) {
        $pb = New-Object System.Windows.Forms.PictureBox
        $pb.Image = [System.Drawing.Image]::FromFile($splashPath)
        $pb.SizeMode = 'StretchImage'
        $pb.Size = Sz 480 320
        $pb.Location = P 0 0
        $pb.BackColor = $bg
        $script:splash.Controls.Add($pb)
        $pb.SendToBack()
        $script:splash.Refresh()
        Write-BootStamp 'splash-art'
    }
} catch {
    Write-BootStamp "splash-fail $_"
    $script:splash = $null
}

$cmdFile = Join-Path $root 'data\runtime\launcher-splash.cmd'
try {
    $d = Split-Path $cmdFile
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
    if (Test-Path $cmdFile) { Remove-Item $cmdFile -Force }
} catch {}

if ($script:splashOk) {
    $env:DK_BOOT_SPLASH = '1'
    $env:DK_UI_MUTEX = $mutexName
}

# 另开 Hidden PowerShell 跑肉 · 同进程会把后定义的函数在事件里找不到
$proc = Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -PassThru `
    -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File', ('"' + $meat + '"')) `
    -WorkingDirectory $root
Write-BootStamp ("meat-spawned pid={0}" -f $proc.Id)

if (-not $script:splashOk) { exit 0 }

$limitSec = if ($firstBoot) { 600 } else { 180 }
$failHold = $null
$sw = [Diagnostics.Stopwatch]::StartNew()
while ($sw.Elapsed.TotalSeconds -lt $limitSec) {
    [System.Windows.Forms.Application]::DoEvents()
    $done = $false
    if (Test-Path $cmdFile) {
        $raw = ''
        try { $raw = [IO.File]::ReadAllText($cmdFile) } catch {}
        if ($raw -match '^ready') { Write-BootStamp 'splash-ready'; $done = $true }
        elseif ($raw -match '^fail') {
            $msg = (($raw -split "`n", 2)[1] + '').Trim()
            if (-not $msg) { $msg = '界面没加载出来 · 关掉再开一次 Daemonkey.exe' }
            try { $script:splashText.Text = $msg } catch {}
            if (-not $failHold) { $failHold = [Diagnostics.Stopwatch]::StartNew(); Write-BootStamp 'splash-fail' }
        }
    }
    if ($done) { break }
    if ($failHold -and $failHold.Elapsed.TotalSeconds -ge 20) { break }
    if ($proc.HasExited -and -not (Test-Path $cmdFile)) {
        try { $script:splashText.Text = '启动中断 · 再双击一次 Daemonkey.exe' } catch {}
        if (-not $failHold) { $failHold = [Diagnostics.Stopwatch]::StartNew(); Write-BootStamp 'meat-exited' }
    }
    Start-Sleep -Milliseconds 30
}

try { if ($barTimer) { $barTimer.Stop(); $barTimer.Dispose() } } catch {}
try { if ($script:splash) { $script:splash.Close(); $script:splash = $null } } catch {}
Write-BootStamp 'boot-exit'
exit 0
