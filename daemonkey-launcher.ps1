#requires -Version 5.1
<#
.SYNOPSIS
  Daemonkey · 启动器 (无边框圆角一体化 · 三栏: 图标导航 / 内容 / 内嵌终端)

.DESCRIPTION
  对外开源项目名: Daemonkey (daemon + monkey)。 双击 start.bat 或 Daemonkey.exe 进来。

  窗口:
    无系统标题栏 · 圆角窗口 · 自绘深色一体化标题栏 (可拖动 · 自带最小化/关闭)

  布局 (参考秋叶 aaaki · 配色用我们自己的 · 图标用 Remix Icon):
    [左] 56px 图标导航栏   [中] 内容区 (启动页顶部 banner 横幅 + 免费声明)   [右] 内嵌终端/输出

  导航:
    启动  —— daemon (WebUI/API) · 桌宠 · 自动开浏览器 + 免费声明/B站
    环境  —— 安装/修复运行环境 · WebUI 访问口令 · 编辑 .env  (含首次使用 3 步引导)
    API   —— 各家 LLM 官方主页 (拿 key / 充值)
    急救  —— 紧急回档 · 应急维修台
    扩展  —— 插件市场 / 升级补丁 (留口)
    关于  —— Daemonkey 开源理念 · 社群入口

  设计原则:
    - OPUS 是 BRO 私有 AI 的名字 (不动) · Daemonkey 是对外的项目/载体名
    - 图标字体只渲染图标 · 任何中文/英文文字一律走 YaHei (否则吐 .notdef 横杠)
    - 按钮全是自绘圆角 (绕开 WinForms Button 的边框/焦点框伪影)
    - 命令输出全部流进右栏终端 · 不再弹独立黑窗 (维修台例外·交互式)
    - 开源就绪: 全走 $PSScriptRoot 相对路径 · 无硬编码盘符

.EXAMPLE
  双击 start.bat   或   .\opus-launcher.ps1
#>

$ErrorActionPreference = 'Continue'

# 工程根: 作为 .ps1 跑用 $PSScriptRoot · 被 ps2exe 编译成 .exe 后 $PSScriptRoot 为空 · 回退到 exe 所在目录
$script:Root = if ($PSScriptRoot) { $PSScriptRoot }
elseif ($PSCommandPath) { Split-Path -Parent $PSCommandPath }
else {
    try { Split-Path -Parent ([System.Reflection.Assembly]::GetEntryAssembly().Location) }
    catch { (Get-Location).Path }
}
Set-Location -Path $script:Root

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# 双缓冲 Panel · 用反射开 protected DoubleBuffered (不走运行时 Add-Type 编译 · 否则 ps2exe 冷启动要等 csc 编译 ~6s)
$script:DBProp = [System.Windows.Forms.Control].GetProperty('DoubleBuffered', [System.Reflection.BindingFlags]'Instance,NonPublic')
function New-BufferedPanel {
    $p = New-Object System.Windows.Forms.Panel
    try { $script:DBProp.SetValue($p, $true, $null) } catch {}
    return $p
}

# ───── 全局状态 ─────
$script:DefaultPort = 7860
$script:VenvPython  = Join-Path $script:Root '.venv\Scripts\python.exe'
$script:VenvPythonW = Join-Path $script:Root '.venv\Scripts\pythonw.exe'
# 版本号 · 真相源 = core_manifest.json 的 core_version (卷七十四续二十) · 读不到回退硬编码
$script:Version     = 'v0.1.0'
try {
    $mfPath = Join-Path $script:Root 'core_manifest.json'
    if (Test-Path $mfPath) {
        $cv = (Get-Content $mfPath -Raw -Encoding UTF8 | ConvertFrom-Json).core_version
        if ($cv) { $script:Version = "v$cv" }
    }
} catch {}
$script:StartText   = '启动'
$script:DaemonRunning = $false   # 0.8.3 · daemon 是否在跑 (启动按钮 ↔ 关闭进程按钮切换)

# 版本比较 (0.8.3 · 新版本提示用) · 支持 "0.8.3beta" 格式 (数字段 + 后缀) · remote > local → $true
function Test-NewerVersion {
    param([string]$local, [string]$remote)
    $lp = $null; $rp = $null
    # 支持 0.8.5 / 0.8.5beta / 0.8.5-hf1 (hotfix 后缀)
    if ($local  -match '^(\d+)\.(\d+)\.(\d+)(?:-([A-Za-z0-9]+))?$') { $lp = @([int]$matches[1], [int]$matches[2], [int]$matches[3], $matches[4]) }
    if ($remote -match '^(\d+)\.(\d+)\.(\d+)(?:-([A-Za-z0-9]+))?$') { $rp = @([int]$matches[1], [int]$matches[2], [int]$matches[3], $matches[4]) }
    if (-not $lp -or -not $rp) { return $false }
    for ($i = 0; $i -lt 3; $i++) {
        if ($rp[$i] -gt $lp[$i]) { return $true }
        if ($rp[$i] -lt $lp[$i]) { return $false }
    }
    # 数字相同 → 后缀: hf(hotfix) > release(空) > beta > alpha
    $ls = [string]$lp[3]; $rs = [string]$rp[3]
    function SuffixRank([string]$s) {
        if (-not $s) { return 2 }
        if ($s.StartsWith('hf')) { return 3 }
        if ($s.StartsWith('beta')) { return 1 }
        if ($s.StartsWith('alpha')) { return 0 }
        return 2
    }
    $lr = SuffixRank $ls; $rr = SuffixRank $rs
    if ($rr -gt $lr) { return $true }
    if ($rr -lt $lr) { return $false }
    return ($rs.CompareTo($ls) -gt 0)
}

# ───── 品牌资源 · 签名保护 (卷七十五防篡改) ─────
# 真相源 = assets/brand.json (作者私钥签发, brand.sig)。 官方公钥内置于此。
# 盗用者改链接/换二维码 → 验签失败 → 启动器显著弹窗"非官方版"。
# 想绕过只能改源码删校验 → 触发 AGPL + 商标风险, 且没私钥重签不了。
$script:BrandPubKey = '<RSAKeyValue><Modulus>1nhbXj/DB/DO945mQ6+HJKQsR2AY5LIa9qPZJQalGJbaRji2dYCYPUGaW6nJ/ePexMkvpuBW9T6nYz6dCazc0yGirybzFj12iRva4hy0No7s4RcJJ0qsEe9psJs+4DU7iDaDWuQkjkT2NeR+/Pjv7twuTVjdyye77wJ8MGD4coAjHBa/TOEvrPadYR3ycOakKXc8Vlr2fL22o/HE9KjUT3EC/0u9xckxGq4crJ9LKRrHP23V4JD+8S9aHnQ5KaKlttGLxDL1USo878t7eLW9LfqznxU9WqQHAjJxC9ZDQXDt7T0p2h5UZv1SxGj/x0WNaE6fGtLKzlz41EQoOFFGiQ==</Modulus><Exponent>AQAB</Exponent></RSAKeyValue>'
# 下面两条是 fallback (没 brand.json 的精简包/旧包用)。 正常运行时会被 brand.json 覆盖。
$script:BiliUrl     = 'https://space.bilibili.com/4060618'
$script:DouyinUrl   = 'https://www.douyin.com/user/MS4wLjABAAAA7v1uJzBaC1f5l52k6bf9ytDz9Gk-WGReDD_2c6cs4XGTuW6-sGaVDrFIGgNZ3Ul3'
$script:BrandVerified = $true
$script:BrandWarn     = ''

function New-RsaSha256Pub {
    param([string]$xml)
    $imp = New-Object System.Security.Cryptography.RSACryptoServiceProvider
    $imp.FromXmlString($xml)
    $p = $imp.ExportParameters($false)
    $imp.Dispose()
    $csp = New-Object System.Security.Cryptography.CspParameters
    $csp.ProviderType = 24   # PROV_RSA_AES -> 支持 SHA256
    $rsa = New-Object System.Security.Cryptography.RSACryptoServiceProvider($csp)
    $rsa.PersistKeyInCsp = $false
    $rsa.ImportParameters($p)
    return $rsa
}

# 缺文件=容忍(旧包/精简包/用户自建)·只有"明确被篡改"才报警·验签出错不阻断
function Test-BrandIntegrity {
    $brandPath = Join-Path $script:Root 'assets\brand.json'
    $sigPath   = Join-Path $script:Root 'assets\brand.sig'
    $qrPath    = Join-Path $script:Root 'assets\community-qr.png'
    if (-not (Test-Path $brandPath) -or -not (Test-Path $sigPath)) { return @{ ok = $true; warn = '' } }
    try {
        $bytes = [IO.File]::ReadAllBytes($brandPath)
        $sig   = [Convert]::FromBase64String(([IO.File]::ReadAllText($sigPath)).Trim())
        $rsa   = New-RsaSha256Pub $script:BrandPubKey
        $ok    = $rsa.VerifyData($bytes, 'SHA256', $sig)
        $rsa.Dispose()
        if (-not $ok) {
            return @{ ok = $false; warn = "品牌资源签名校验失败 — 这不是官方版。`r`n链接 / 二维码可能已被第三方篡改。`r`n官方发布唯一在 B站 / 抖音, 请以官方频道为准。" }
        }
        $brand = [Text.Encoding]::UTF8.GetString($bytes) | ConvertFrom-Json
        if ($brand.official.bilibili) { $script:BiliUrl   = [string]$brand.official.bilibili }
        if ($brand.official.douyin)   { $script:DouyinUrl = [string]$brand.official.douyin }
        if ((Test-Path $qrPath) -and $brand.community_qr_sha256) {
            $h = (Get-FileHash $qrPath -Algorithm SHA256).Hash.ToLower()
            if ($h -ne ([string]$brand.community_qr_sha256).ToLower()) {
                return @{ ok = $false; warn = "社群二维码与官方清单不符 — 可能已被替换。`r`n请通过官方 B站 / 抖音核对真正的入群方式。" }
            }
        }
        return @{ ok = $true; warn = '' }
    } catch { return @{ ok = $true; warn = '' } }
}

$script:__brandChk    = Test-BrandIntegrity
$script:BrandVerified = $script:__brandChk.ok
$script:BrandWarn     = $script:__brandChk.warn

# ───── 配色 (深色 · 现代扁平 · 一体化) ─────
$cTitleBar = [System.Drawing.Color]::FromArgb(16, 17, 26)
$cSidebar  = [System.Drawing.Color]::FromArgb(18, 19, 30)
$cBg       = [System.Drawing.Color]::FromArgb(30, 31, 46)
$cCard     = [System.Drawing.Color]::FromArgb(40, 42, 60)
$cNavSel   = [System.Drawing.Color]::FromArgb(46, 52, 84)
$cNavHover = [System.Drawing.Color]::FromArgb(32, 34, 52)
$cAccent   = [System.Drawing.Color]::FromArgb(120, 170, 255)
$cBtn      = [System.Drawing.Color]::FromArgb(99, 140, 255)
$cText     = [System.Drawing.Color]::FromArgb(236, 238, 248)
$cDim      = [System.Drawing.Color]::FromArgb(150, 154, 178)
$cInput    = [System.Drawing.Color]::FromArgb(46, 48, 68)
$cDanger   = [System.Drawing.Color]::FromArgb(214, 96, 96)
$cOk       = [System.Drawing.Color]::FromArgb(80, 180, 110)
$cWarn     = [System.Drawing.Color]::FromArgb(230, 180, 90)
$cErr      = [System.Drawing.Color]::FromArgb(232, 130, 130)
$cMuted    = [System.Drawing.Color]::FromArgb(64, 66, 88)
$cTermBg   = [System.Drawing.Color]::FromArgb(13, 14, 22)
$cTermOut  = [System.Drawing.Color]::FromArgb(205, 210, 228)
$cBorder   = [System.Drawing.Color]::FromArgb(58, 62, 92)

# ───── 小工具 ─────
function P { param([int]$x, [int]$y) New-Object System.Drawing.Point($x, $y) }
function Sz { param([int]$w, [int]$h) New-Object System.Drawing.Size($w, $h) }
function F {
    param([single]$size, [System.Drawing.FontStyle]$style = [System.Drawing.FontStyle]::Regular)
    New-Object System.Drawing.Font('Microsoft YaHei UI', $size, $style)
}

# 圆角矩形路径 (按钮 / 卡片 / 窗口 / banner 共用)
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

# ── 自绘开关 ToggleSwitch (纯 WinForms 拼装 · 不走 Add-Type · 冷启动不慢) ──
# 轨道 Panel + 滑块 Panel · ScriptProperty 暴露 .Checked 兼容旧 CheckBox 引用
# 移植自蟹子合并包 (wish-1b8e141b 崩溃自启配套 · 2026-08-15)
function Update-ToggleVisual {
    param($track)
    if (-not $track -or -not $track.Tag) { return }
    $on = [bool]$track.Tag.checked
    $knob = $track.Controls[0]
    if ($on) {
        $track.BackColor = $cOk
        $knob.Location = P ($track.Width - $knob.Width - 2) 2
    } else {
        $track.BackColor = $cDim
        $knob.Location = P 2 2
    }
}
function New-ToggleSwitch {
    param([int]$x, [int]$y, [scriptblock]$onChange)
    $track = New-Object System.Windows.Forms.Panel
    $track.Location = P $x $y
    $track.Size = Sz 44 24
    $track.BackColor = $cDim
    $track.Region = New-Object System.Drawing.Region((Get-RoundPath 44 24 12))
    $track.Cursor = [System.Windows.Forms.Cursors]::Hand
    $knob = New-Object System.Windows.Forms.Panel
    $knob.Size = Sz 20 20
    $knob.BackColor = [System.Drawing.Color]::White
    $knob.Region = New-Object System.Drawing.Region((Get-RoundPath 20 20 10))
    $knob.Location = P 2 2
    $track.Controls.Add($knob)
    $track.Tag = @{ checked = $false; onChange = $onChange }
    $track | Add-Member -MemberType ScriptProperty -Name 'Checked' -Value {
        if ($this.Tag) { return [bool]$this.Tag.checked } else { return $false }
    } -SecondValue {
        param($v)
        if ($this.Tag) {
            $this.Tag.checked = [bool]$v
            Update-ToggleVisual $this
            if ($this.Tag.onChange) { & $this.Tag.onChange }
        }
    }
    $track.Add_Click({
        if ($this.Tag) {
            $this.Tag.checked = -not $this.Tag.checked
            Update-ToggleVisual $this
            if ($this.Tag.onChange) { & $this.Tag.onChange }
        }
    })
    return $track
}

# ───── Remix Icon 字体加载 (本地 static/lib/remixicon/remixicon.ttf · 与 WebUI 同版) ─────
# 注意: 这个字体只有图标字形 · 绝不能拿去渲染中文/英文 · 否则吐 .notdef (一条横/方块)
$script:IconFamily = $null
$script:Pfc = $null
function Load-IconFont {
    $ttf = Join-Path $script:Root 'static\lib\remixicon\remixicon.ttf'
    if (-not (Test-Path $ttf)) { return }
    try {
        $script:Pfc = New-Object System.Drawing.Text.PrivateFontCollection
        $script:Pfc.AddFontFile($ttf)
        $script:IconFamily = $script:Pfc.Families[0]
    } catch { $script:IconFamily = $null }
}
Load-IconFont
function IconFont {
    param([single]$size)
    if ($script:IconFamily) {
        return New-Object System.Drawing.Font($script:IconFamily, $size, [System.Drawing.FontStyle]::Regular, [System.Drawing.GraphicsUnit]::Point)
    }
    return F $size
}
function Ico { param([int]$code) [char]$code }

# Remix 码点 (从 remixicon.css 取)
$ICO_ROCKET = 0xF096
$ICO_TOOLS  = 0xF21B
$ICO_KEY    = 0xEE6F
$ICO_AID    = 0xED37
$ICO_PUZZLE = 0xF450
$ICO_INFO   = 0xEE59
$ICO_TERM   = 0xF1F6

# ───── 工具函数 ─────
function Get-OpusToken {
    $envPath = Join-Path $script:Root '.env'
    if (-not (Test-Path $envPath)) { return $null }
    $line = Get-Content $envPath | Where-Object { $_ -match '^\s*OPUS_API_TOKEN\s*=\s*(\S+)' }
    if ($line -and $line -match '=\s*(\S+)') { return $matches[1].Trim() }
    return $null
}

function Test-DaemonAlive {
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return [bool]$conn
}

# 卷四十四 I · wish-12946ade · 已开进程检测 + 三选一对话框
function Get-DaemonProcessInfo {
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $conn) { return $null }
    $pid_ = $conn[0].OwningProcess
    $proc = Get-Process -Id $pid_ -ErrorAction SilentlyContinue
    if (-not $proc) { return @{ Pid = $pid_; StartTime = $null; AgeMin = -1 } }
    $age = if ($proc.StartTime) { [int]((Get-Date) - $proc.StartTime).TotalMinutes } else { -1 }
    return @{ Pid = $pid_; StartTime = $proc.StartTime; AgeMin = $age; Process = $proc }
}

# ── wish-1b8e141b · 崩溃自动拉起 (三条件判定 + 熔断 + 状态持久化) ──
# 移植自蟹子合并包 (2026-08-15) · 引用纯净版已有变量 ($script:Root/$script:VenvPython/$txtPort/$btnStart/$chkAutoRestart)
$script:AutoRestartFile = Join-Path $script:Root 'data\runtime\auto_restart.json'
$script:DownSince = $null          # 端口 down 起始时间 (stopped 持续计时)
$script:LastLiftAt = $null         # 上次自动拉起时间
$script:LiftArmed = $false         # 拉起后等待起来 (武装)
$script:PostLiftWindow = $null     # 最近一次"活过"的时间 (熔断: 起来又崩算失败)
$script:AutoLiftFails = 0          # 连续失败计数
$script:AutoLiftFirstFail = $null  # 首次失败时间
$script:CircuitUntil = $null       # 熔断到期时间 (半开恢复: 熔断后 10 分钟自动解除)

function Load-AutoRestartState {
    if (Test-Path $script:AutoRestartFile) {
        try { return Get-Content $script:AutoRestartFile -Raw | ConvertFrom-Json } catch {}
    }
    return $null
}
function Save-AutoRestartState {
    try {
        $dir = Split-Path $script:AutoRestartFile -Parent
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        $obj = @{ enabled = [bool]$chkAutoRestart.Checked
                 failCount = $script:AutoLiftFails
                 firstFailAt = if ($script:AutoLiftFirstFail) { $script:AutoLiftFirstFail.ToString('o') } else { '' }
                 lastLiftAt = if ($script:LastLiftAt) { $script:LastLiftAt.ToString('o') } else { '' }
                 circuitUntil = if ($script:CircuitUntil) { $script:CircuitUntil.ToString('o') } else { '' } }
        $obj | ConvertTo-Json | Set-Content $script:AutoRestartFile -Encoding UTF8
    } catch {}
}

# 主动重启 / 安全模式标记存在 → 不自动拉起 (区分"主动重启"与"真崩溃"的关键)
# quarantined (安全模式隔离) 文件加过期判断: 超过 10 分钟视为残留 · 不再拦自动拉起
function Test-PendingRestartRequest {
    foreach ($f in @('restart_request.json', 'restart_request.quarantined.json')) {
        $p = Join-Path $script:Root "data\runtime\$f"
        if (-not (Test-Path $p)) { continue }
        # 两个文件统一加过期: 超过 10 分钟视为残留 · 不拦自动拉起
        # (修: daemon 写了 restart_request 但没消费(重启失败/起不来) → 防止永远不自启的死锁)
        try {
            $age = (Get-Date) - (Get-Item $p).LastWriteTime
            if ($age.TotalMinutes -gt 10) { continue }   # 残留 · 不拦
        } catch { continue }  # 读不到时间按残留处理
        return $true
    }
    return $false
}

# wish-32691f0e · 运行监控数据源: daemon.pid + restart_history.jsonl (daemon 死了也能读)
# 状态判定: TCP 通=running · TCP 不通但末条 started/takeover 在 90s 内=restarting · 否则 stopped
function Get-DaemonMonitorData {
    param([int]$Port)
    $pidFile = Join-Path $script:Root 'data\runtime\daemon.pid'
    $histFile = Join-Path $script:Root 'data\runtime\restart_history.jsonl'

    $alive = Test-DaemonAlive -Port $Port
    $pidData = $null
    if (Test-Path $pidFile) {
        try { $pidData = Get-Content $pidFile -Raw | ConvertFrom-Json } catch { $pidData = $null }
    }
    $events = @()
    if (Test-Path $histFile) {
        try {
            foreach ($ln in (Get-Content $histFile -Tail 10)) {
                try { $events += ($ln | ConvertFrom-Json) } catch {}
            }
        } catch {}
    }
    [Array]::Reverse($events)   # 新的在前

    $state = 'stopped'
    if ($alive) {
        $state = 'running'
    } elseif ($events.Count -gt 0) {
        $last = $events[0]
        $evt = [string]$last.event
        $ts = [string]$last.timestamp
        if (($evt -eq 'daemon_started' -or $evt -eq 'takeover_completed') -and $ts) {
            try {
                $age = ((Get-Date) - [datetime]::Parse($ts)).TotalSeconds
                if ($age -ge 0 -and $age -lt 90) { $state = 'restarting' }
            } catch {}
        }
    }
    return @{ State = $state; Pid = if ($pidData) { [string]$pidData.pid } else { '' }
              StartedAt = if ($pidData) { [string]$pidData.started_at } else { '' }
              Events = $events }
}

# 拉起 daemon (与手动启动同路径: .venv + run_api_only · 端口预检硬闸兜底防双起)
function Lift-Daemon {
    $port = 7860
    try { $port = [int]$txtPort.Text } catch {}
    if (Test-DaemonAlive -Port $port) { return }   # 已活就别动
    if ($script:LiftArmed) { return }               # 已拉起在等

    # 熔断: 10 分钟内连续失败 >=3 次 → 停 10 分钟 (半开恢复: 到期自动解除熔断再试探)
    if ($script:AutoLiftFails -ge 3 -and $script:AutoLiftFirstFail -and
        ((Get-Date) - $script:AutoLiftFirstFail).TotalMinutes -lt 10) {
        if (-not $script:CircuitUntil) { $script:CircuitUntil = (Get-Date).AddMinutes(10) }
        Add-Log "自动拉起熔断: 10 分钟内连续失败 $($script:AutoLiftFails) 次 · 暂停自动拉起 10 分钟 · 到期自动恢复" 'err'
        try { $chkAutoRestart.Checked = $false } catch {}
        Save-AutoRestartState
        return
    }

    Add-Log "检测到 daemon 停止 · 自动拉起 (port=$port)…" 'warn'
    $logPath = Join-Path $script:Root "_daemon_auto_$port.log"
    $errPath = Join-Path $script:Root "_daemon_auto_$port.err"
    try {
        Start-Process -FilePath $script:VenvPython `
            -ArgumentList @('-u', 'tools\run_api_only.py', '--host', '127.0.0.1', '--port', "$port") `
            -WorkingDirectory $script:Root -WindowStyle Hidden `
            -RedirectStandardOutput $logPath -RedirectStandardError $errPath
    } catch { Add-Log "自动拉起失败: $_" 'err' }
    $script:DownSince = $null
    $script:LastLiftAt = Get-Date
    $script:LiftArmed = $true
    Save-AutoRestartState
}

# 看门狗主逻辑 (autoRestartTimer 每 10s 调)
function Watch-AutoRestart {
    try { if (-not $chkAutoRestart.Checked) { $script:DownSince = $null; return } } catch { return }
    $port = 7860
    try { $port = [int]$txtPort.Text } catch {}
    if (Test-PendingRestartRequest) { return }   # 主动重启/安全模式 → 不碰

    # 半开恢复: 熔断到期 → 自动解除熔断 (重新开开关 + 清失败计数 + 立即进入观察)
    if ($script:CircuitUntil -and (Get-Date) -ge $script:CircuitUntil) {
        $script:CircuitUntil = $null
        $script:AutoLiftFails = 0
        $script:AutoLiftFirstFail = $null
        $script:DownSince = $null
        try { $chkAutoRestart.Checked = $true } catch {}
        Add-Log "熔断到期 · 自动恢复崩溃自启 (半开试探)" 'warn'
        Save-AutoRestartState
    }

    $d = Get-DaemonMonitorData -Port $port
    if ($d.State -eq 'running') {
        # 活过 → 清除"拉起中"武装 + 记录"刚活过"时间 (熔断: 起来又崩算失败) · 成功则清零失败计数
        $script:LiftArmed = $false
        $script:PostLiftWindow = Get-Date
        if ($script:AutoLiftFails -gt 0) { $script:AutoLiftFails = 0; $script:AutoLiftFirstFail = $null; Save-AutoRestartState }
        $script:DownSince = $null
        return
    }
    if ($d.State -eq 'restarting') { return }    # 主动重启窗口 (restart_history 90s)

    # State = stopped
    if ($script:LiftArmed) {
        # 拉起后还没起来: 超过 45s 判定失败
        if ($script:LastLiftAt -and ((Get-Date) - $script:LastLiftAt).TotalSeconds -ge 45) {
            $script:AutoLiftFails++
            if (-not $script:AutoLiftFirstFail) { $script:AutoLiftFirstFail = Get-Date }
            $script:LiftArmed = $false
            Add-Log "自动拉起未成功 (fail=$($script:AutoLiftFails))" 'err'
            Save-AutoRestartState
        }
        return
    }
    # 刚活过又崩 (<10 分钟) → 算一次失败 (反复崩溃循环熔断)
    if ($script:PostLiftWindow -and ((Get-Date) - $script:PostLiftWindow).TotalMinutes -lt 10) {
        $script:AutoLiftFails++
        if (-not $script:AutoLiftFirstFail) { $script:AutoLiftFirstFail = Get-Date }
        $script:PostLiftWindow = $null
        Add-Log "自动拉起后短期内又崩 (fail=$($script:AutoLiftFails))" 'err'
        Save-AutoRestartState
    }
    # 持续 stopped 计时: 满 90s 触发拉起 (三条件全满足)
    if (-not $script:DownSince) { $script:DownSince = Get-Date }
    elseif (((Get-Date) - $script:DownSince).TotalSeconds -ge 90) {
        Lift-Daemon
    }
}

# wish-32691f0e · 刷新监控面板 (Timer 每 2s 调一次)
function Update-MonitorPanel {
    $port = 7860
    try { $port = [int]$txtPort.Text } catch {}
    $d = Get-DaemonMonitorData -Port $port

    $stText = '已停止'; $stColor = $cDanger
    if ($d.State -eq 'running') { $stText = '运行中'; $stColor = $cOk }
    elseif ($d.State -eq 'restarting') { $stText = '重启中…'; $stColor = $cWarn }

    # 托盘状态 (BRO 2026-08-15 · 监控面板已删 · 状态进托盘)
    if ($script:trayIcon) {
        try { $script:trayIcon.Text = "Daemonkey 守护 · $stText" } catch {}
    }

    if ($script:lblMonState) {
        $script:lblMonState.Text = "● $stText"
        $script:lblMonState.ForeColor = $stColor
    }

    $meta = ''
    if ($d.State -eq 'running') {
        $ageTxt = ''
        if ($d.StartedAt) {
            try {
                $age = [int]((Get-Date) - [datetime]::Parse($d.StartedAt)).TotalMinutes
                $ageTxt = if ($age -lt 1) { '刚刚' } elseif ($age -lt 60) { "已运行 $age 分钟" }
                          else { "已运行 $([int]($age/60)) 小时 $($age % 60) 分" }
            } catch {}
        }
        $meta = "PID=$($d.Pid) · 启动 $($d.StartedAt) · $ageTxt"
    } elseif ($d.State -eq 'restarting') {
        $meta = "重启中 · 新进程即将接管端口 $port"
    } else {
        $meta = "端口 $port 无监听 · daemon 未运行"
        if ($d.Events.Count -gt 0) { $meta += " · 上次事件: $($d.Events[0].event)" }
    }
    if ($script:lblMonMeta) { $script:lblMonMeta.Text = $meta }

    # 0.9.4+ · 按钮状态跟随监控刷新: 运行中→「关闭进程」· 停止→「启动」
    # 只在按钮空闲 (Enabled) 时同步 · 正在启动/停止中 (disabled) 不打扰
    if ($btnStart.Enabled) {
        $isRunning = ($d.State -eq 'running')
        if ($isRunning -and -not $script:DaemonRunning) {
            $script:DaemonRunning = $true
            $btnStart.Text = '关闭进程'
            Set-ButtonFill $btnStart $cOk
        } elseif (-not $isRunning -and $script:DaemonRunning) {
            $script:DaemonRunning = $false
            $btnStart.Text = $script:StartText
            Set-ButtonFill $btnStart $cBtn
        }
    }

    $evtLabels = @($script:lblMonEvt1, $script:lblMonEvt2, $script:lblMonEvt3)
    for ($i = 0; $i -lt 3; $i++) {
        if ($evtLabels[$i] -and $i -lt $d.Events.Count) {
            $e = $d.Events[$i]
            $ts = [string]$e.timestamp
            if ($ts.Length -ge 19) { $ts = $ts.Substring(5, 11) }  # MM-dd HH:mm
            $txt = "$ts  $($e.event)"
            if ($e.reason) { $txt += "  ·  $($e.reason)" }
            if ($e.old_pid) { $txt += "  ·  pid=$($e.old_pid)" }
            if ($e.pid) { $txt += "  ·  pid=$($e.pid)" }
            if ($txt.Length -gt 62) { $txt = $txt.Substring(0, 59) + '…' }
            $evtLabels[$i].Text = $txt
            $evtLabels[$i].Visible = $true
        } elseif ($evtLabels[$i]) {
            $evtLabels[$i].Text = ''
            $evtLabels[$i].Visible = $false
        }
    }
}

function Get-PetProcessInfo {
    try {
        $procs = Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" -ErrorAction SilentlyContinue |
                 Where-Object { $_.CommandLine -and $_.CommandLine -match 'desktop_pet[\\/]pet\.py' }
        if (-not $procs) { return $null }
        $first = $procs | Select-Object -First 1
        $proc = Get-Process -Id $first.ProcessId -ErrorAction SilentlyContinue
        $age = if ($proc -and $proc.StartTime) { [int]((Get-Date) - $proc.StartTime).TotalMinutes } else { -1 }
        return @{ Pid = $first.ProcessId; StartTime = $proc.StartTime; AgeMin = $age; Process = $proc }
    } catch { return $null }
}

# 三选一对话框 · 返回 'restart' / 'keep' / 'cancel'
function Show-RestartChoice {
    param([string]$Name, [int]$Pid_, [int]$AgeMin)
    $ageText = if ($AgeMin -ge 0) { "$AgeMin 分钟前启动" } else { '启动时间未知' }
    $msg = "$Name 已经在跑 (pid=$Pid_ · $ageText)。`r`n`r`n选项:`r`n  是   = 重启 (杀掉旧进程·起新的)`r`n  否   = 保留旧的 (不动·继续后续步骤)`r`n  取消 = 取消整个启动流程"
    $btn = [System.Windows.Forms.MessageBoxButtons]::YesNoCancel
    $icon = [System.Windows.Forms.MessageBoxIcon]::Question
    $result = [System.Windows.Forms.MessageBox]::Show($msg, "$Name 已开 · 怎么办?", $btn, $icon)
    switch ($result) {
        'Yes'    { return 'restart' }
        'No'     { return 'keep' }
        'Cancel' { return 'cancel' }
        default  { return 'cancel' }
    }
}

# 用户版: 静默确保 git 仓库 + 官方升级源 (卷七十五续)
# 不弹"要不要 git init"那种吓人窗(那是开发者调代码用的噪声);改成开机静默把更新链路铺好——
# ZIP 包用户没 .git → 静默 init + baseline;没 remote → 静默配官方 gitee 源。
# 之后「检查更新 / 升级内核」开箱即用。 更新走 fetch+checkout 白名单(非 merge)·无关历史不影响。
function Ensure-RepoAndSource {
    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) { return }
    Push-Location $script:Root
    try {
        if (-not (Test-Path (Join-Path $script:Root '.git'))) {
            & git init 2>&1 | Out-Null
            & git config user.email 'daemon@daemonkey.local' 2>&1 | Out-Null
            & git config user.name 'Daemonkey' 2>&1 | Out-Null
            & git add -A 2>&1 | Out-Null
            & git commit -m 'baseline' 2>&1 | Out-Null
        }
        if ("$(& git rev-parse --is-inside-work-tree 2>$null)".Trim() -ne 'true') { return }
        if (@(& git remote 2>$null) -contains 'gitee') { return }   # 已有官方源 · 不动用户配置
        $url = ''
        try { $url = [string]((Get-Content (Join-Path $script:Root 'core_manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json).sources.remotes.gitee) } catch {}
        if ($url) { & git remote add gitee $url 2>&1 | Out-Null }
    } catch {} finally { Pop-Location }
}

# ═══════════════════════════════════════════════════
#  启动画面 (Splash) · 覆盖启动空白期 (git init / 一键装依赖 / WebView2 初始化)
#  主界面显示时关闭 (Shown + WebView2 NavigationCompleted / 4s 兜底)
# ═══════════════════════════════════════════════════
try {
    $script:splash = New-Object System.Windows.Forms.Form
    $script:splash.FormBorderStyle = 'None'
    $script:splash.StartPosition = 'CenterScreen'
    $script:splash.Size = Sz 480 320   # 3:2 匹配 banner 1536×1024 · 满幅无灰边
    $script:splash.BackColor = [System.Drawing.Color]::FromArgb(15, 16, 24)
    $script:splash.TopMost = $true
    $script:splash.ShowInTaskbar = $false
    # 圆角 (无边框窗 Region)
    try {
        if (-not ('SplashRgn' -as [type])) {
            Add-Type -TypeDefinition 'using System.Runtime.InteropServices; public class SplashRgn { [DllImport("gdi32.dll")] public static extern IntPtr CreateRoundRectRgn(int a,int b,int c,int d,int e,int f); }' -ErrorAction Stop
        }
        $script:splash.Region = [System.Drawing.Region]::FromHrgn([SplashRgn]::CreateRoundRectRgn(0, 0, 480, 320, 18, 18))
    } catch {}

    $bannerPath = Join-Path $script:Root 'assets\banner.png'
    if (Test-Path $bannerPath) {
        $pb = New-Object System.Windows.Forms.PictureBox
        $pb.Image = [System.Drawing.Image]::FromFile($bannerPath)
        $pb.SizeMode = 'StretchImage'    # 满幅铺底 · 无灰边
        $pb.Size = Sz 480 320
        $pb.Location = P 0 0
        $pb.BackColor = [System.Drawing.Color]::FromArgb(15, 16, 24)
        $script:splash.Controls.Add($pb)
    }

    # 底部半透明遮罩 + 白字
    $mask = New-Object System.Windows.Forms.Panel
    $mask.Size = Sz 480 58
    $mask.Location = P 0 262
    $mask.BackColor = [System.Drawing.Color]::FromArgb(140, 8, 9, 14)
    $script:splash.Controls.Add($mask)
    $mask.BringToFront()

    $stxt = New-Object System.Windows.Forms.Label
    $stxt.Text = '正在启动 Daemonkey · 首次使用自动安装运行环境'
    $stxt.Font = F 10
    $stxt.ForeColor = [System.Drawing.Color]::White
    $stxt.BackColor = [System.Drawing.Color]::Transparent
    $stxt.TextAlign = 'MiddleCenter'
    $stxt.Size = Sz 480 30
    $stxt.Location = P 0 267
    $script:splash.Controls.Add($stxt)
    $stxt.BringToFront()

    # 底部细进度条 (Marquee 往返动画 · Timer 100ms)
    $barTrack = New-Object System.Windows.Forms.Panel
    $barTrack.Size = Sz 480 3
    $barTrack.Location = P 0 317
    $barTrack.BackColor = [System.Drawing.Color]::FromArgb(60, 70, 110)
    $script:splash.Controls.Add($barTrack)
    $script:barFill = New-Object System.Windows.Forms.Panel
    $script:barFill.Size = Sz 96 3
    $script:barFill.Location = P 0 0
    $script:barFill.BackColor = [System.Drawing.Color]::FromArgb(124, 108, 240)
    $script:barTrack.Controls.Add($script:barFill)
    $script:barDir = 1
    $script:barPos = 0
    $script:splashBarTimer = New-Object System.Windows.Forms.Timer
    $script:splashBarTimer.Interval = 100
    $script:splashBarTimer.Add_Tick({
        $script:barPos += $script:barDir * 32
        if ($script:barPos -ge 384) { $script:barPos = 384; $script:barDir = -1 }
        if ($script:barPos -le 0) { $script:barPos = 0; $script:barDir = 1 }
        try { $script:barFill.Location = P $script:barPos 0 } catch {}
    })
    $script:splashBarTimer.Start()

    $script:splash.Show()
    $script:splash.Refresh()
} catch { $script:splash = $null }

Ensure-RepoAndSource

# ═══════════════════════════════════════════════════
#  主窗口 · 无边框圆角 + 自绘标题栏 + 三栏
# ═══════════════════════════════════════════════════
$form = New-Object System.Windows.Forms.Form
$form.Text = 'Daemonkey'
# 锁死像素 · 不随 ps2exe 宿主字体/DPI 自动缩放 (否则编译成 exe 后窗口会被缩小)
$form.AutoScaleMode = [System.Windows.Forms.AutoScaleMode]::None
$form.ClientSize = Sz 1080 700
# 钉死最小/最大尺寸 = 不可缩放 · 防止 ps2exe 冷启动期间先弹一个小窗 (Min/Max 由 WinForms 强制 · 与设置时机无关)
$form.MinimumSize = Sz 1080 700
$form.MaximumSize = Sz 1080 700
$form.StartPosition = 'CenterScreen'
$form.BackColor = $cBg
$form.ForeColor = $cText
$form.Font = F 9
$form.FormBorderStyle = 'None'
$form.MaximizeBox = $false
# ── 任务栏按钮图标 = 进程 exe 图标 (powershell=`>_`) · 设进程级 AppUserModelID 让按钮跟随窗口图标 ──
try {
    if (-not ('DkAppId' -as [type])) {
        Add-Type -TypeDefinition @"
using System.Runtime.InteropServices;
public class DkAppId {
    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    public static extern int SetCurrentProcessExplicitAppUserModelID(string AppID);
}
"@ -ErrorAction Stop
    }
    [void][DkAppId]::SetCurrentProcessExplicitAppUserModelID('Daemonkey')
} catch { Add-Log "AppUserModelID 设置失败: $_" 'warn' }

# 任务栏 / Alt-Tab 图标 (窗口图标和 exe 文件图标都对齐到同一个 .ico)
# 2026-08-15 · 双保险: ico 加载失败 → ExtractAssociatedIcon 从 exe 提取 · 任务栏图标跟随
# 2026-08-15 19:10 · 治本: 无边框窗口任务栏按钮图标走窗口类图标 · WinForms $form.Icon 对无边框窗口不生效
#                → 手动 WM_SETICON (big+small) 强制设置 · 任务栏按钮一定跟随
try {
    $icoFile = Join-Path $script:Root 'assets\daemonkey.ico'
    if (Test-Path $icoFile) {
        try { $form.Icon = New-Object System.Drawing.Icon($icoFile); "Icon($icoFile) OK: $($form.Icon.Handle)" | Out-File $dbgLog -Append } catch { "Icon($icoFile) FAIL: $_" | Out-File $dbgLog -Append }
    }
    if (-not $form.Icon) {
        $exePath = Join-Path $script:Root 'Daemonkey.exe'
        if (Test-Path $exePath) { $form.Icon = [System.Drawing.Icon]::ExtractAssociatedIcon($exePath); "ExtractAssociatedIcon OK: $($form.Icon.Handle)" | Out-File $dbgLog -Append }
    }
    $form.ShowIcon = $true
    if ($form.Icon) {
        if (-not ('DkWin32Icon' -as [type])) {
            Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class DkWin32Icon {
    [DllImport("user32.dll", CharSet = CharSet.Auto)]
    public static extern IntPtr SendMessage(IntPtr hWnd, int Msg, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll", EntryPoint = "SetClassLongPtrW")]
    public static extern IntPtr SetClassLongPtr(IntPtr hWnd, int nIndex, IntPtr dwNewLong);
    [DllImport("user32.dll")]
    public static extern bool DestroyIcon(IntPtr hIcon);
}
"@ -ErrorAction Stop
        }
        try {
            $hMain = $form.Handle   # 强制创建窗口 handle (此时才可设窗口图标)
            [void][DkWin32Icon]::SendMessage($hMain, 0x0080, [IntPtr]1, $form.Icon.Handle)  # WM_SETICON ICON_BIG
            [void][DkWin32Icon]::SendMessage($hMain, 0x0080, [IntPtr]0, $form.Icon.Handle)  # WM_SETICON ICON_SMALL
            # 类图标 (GCLP_HICON/GCLP_HICONSM) · 任务栏按钮图标优先用类图标 · 不受窗口重建影响
            [void][DkWin32Icon]::SetClassLongPtr($hMain, -14, $form.Icon.Handle)   # GCLP_HICON
            [void][DkWin32Icon]::SetClassLongPtr($hMain, -34, $form.Icon.Handle)   # GCLP_HICONSM
        } catch { Add-Log "WM_SETICON 失败: $_" 'warn' }
        # Shown 后再设一次: 后续属性修改(如 FormBorderStyle)会重建 Handle 冲掉图标 · 显示后 Handle 稳定
        $script:mainIcon = $form.Icon   # 持有引用防 GC 销毁 HICON
        $form.Add_Shown({
            try {
                if ($script:mainIcon) {
                    [void][DkWin32Icon]::SendMessage($form.Handle, 0x0080, [IntPtr]1, $script:mainIcon.Handle)
                    [void][DkWin32Icon]::SendMessage($form.Handle, 0x0080, [IntPtr]0, $script:mainIcon.Handle)
                    [void][DkWin32Icon]::SetClassLongPtr($form.Handle, -14, $script:mainIcon.Handle)
                    [void][DkWin32Icon]::SetClassLongPtr($form.Handle, -34, $script:mainIcon.Handle)
                    Add-Log "窗口图标已应用 (WM_SETICON + 类图标)" 'ok'
                } else { Add-Log 'Shown: mainIcon 为空' 'warn' }
            } catch { Add-Log "Shown WM_SETICON err: $_" 'err' }
        })
    }
} catch { Add-Log "窗口图标设置失败: $_" 'warn' }

# ── 托盘图标 (壳肉分离 · 守护进程常驻 · 2026-08-15 v2) ──
# v2 修复 (BRO 实测: 托盘图标 hover 就消失 = PowerShell GC 回收 NotifyIcon/委托):
#   ① 所有托盘对象 (图标/菜单/委托) 全存 $script: 强引用 · 事件委托用命名 scriptblock 变量
#   ② 托盘图标挂到 $form 上 ($form.ShowDialog 期间绝对存活 → 图标不会被 GC)
#   ③ 托盘常驻 (不随窗口显隐 · 守护语义: 窗口最小化隐藏 / 托盘双击呼出 / 退出才 Dispose)
$script:trayIcon = $null
$script:trayMenu = $null
$script:OnTrayDoubleClick = $null   # 跳板: 托盘双击行为 (面板段赋值)
$script:OnTrayOpen = $null          # 跳板: 右键菜单"打开面板"行为
$script:trayIcoObj = $null
$script:trayEvtDblClick = $null
$script:trayEvtOpen = $null
$script:trayEvtAuto = $null
$script:trayEvtRestart = $null
$script:trayEvtQuit = $null
$script:trayEvtMenuOpening = $null
$script:trayEvtFormClosed = $null
# 崩溃自启状态容器 (面板已删 · 用不可见 CheckBox 承载 .Checked · 蟹子代码引用它)
$script:chkAutoRestart = New-Object System.Windows.Forms.CheckBox
$script:chkAutoRestart.Checked = $false
$script:chkAutoRestart.Visible = $false
$form.Controls.Add($script:chkAutoRestart)
if (Test-Path $icoFile) {
    try {
        $script:trayIcoObj = New-Object System.Drawing.Icon($icoFile)
        $script:trayIcon = New-Object System.Windows.Forms.NotifyIcon
        $script:trayIcon.Icon = $script:trayIcoObj
        $script:trayIcon.Text = 'Daemonkey 守护'
        $script:trayIcon.Visible = $true   # 托盘常驻 (守护进程 · 窗口开着也在)
        # 双击托盘 → 呼出窗口 (命名委托 · 防 GC)
        $script:trayEvtDblClick = {
            $form.Show()
            $form.WindowState = [System.Windows.Forms.FormWindowState]::Normal
            $form.BringToFront()
        }
        $script:trayIcon.Add_DoubleClick({
            if ($script:OnTrayDoubleClick) { & $script:OnTrayDoubleClick }
        })
        # 右键菜单
        $script:trayMenu = New-Object System.Windows.Forms.ContextMenuStrip
        $script:trayEvtOpen = {
            $form.Show()
            $form.WindowState = [System.Windows.Forms.FormWindowState]::Normal
            $form.BringToFront()
        }
        $script:trayEvtAuto = {
            if ($script:chkAutoRestart) { $script:chkAutoRestart.Checked = $mAuto.Checked }
            if ($script:autoRestartOn -ne $null) { $script:autoRestartOn = $mAuto.Checked }
        }
        $script:trayEvtRestart = { try { $btnStart.PerformClick() } catch {} }
# ───── 退出三选一弹窗 (2026-08-15 · 启动页"关闭进程"复用 · 参数化) ─────
function Show-QuitDialog {
    param(
        [string]$Title = '退出 Daemonkey',
        [string]$Sub = 'daemon 服务可以继续在后台运行',
        [string]$PrimaryText = '全部退出 · 停止 daemon + 关闭启动器',
        [string]$SecondaryText = '仅关闭启动器 · daemon 继续运行',
        [scriptblock]$PrimaryAction,
        [scriptblock]$SecondaryAction
    )
    $dlg = New-Object System.Windows.Forms.Form
    $dlg.Text = $Title
    $dlg.FormBorderStyle = 'None'          # 无边框
    $dlg.StartPosition = 'CenterScreen'
    $dlg.ClientSize = Sz 420 250
    $dlg.BackColor = $cBg
    $dlg.ForeColor = $cText
    $dlg.Font = F 9
    $dlg.TopMost = $true
    $dlg.ShowInTaskbar = $false
    $dlg.MaximizeBox = $false
    $dlg.MinimizeBox = $false
    try {
        if (-not ('QuitDlgRgn' -as [type])) {
            Add-Type -TypeDefinition 'using System.Runtime.InteropServices; public class QuitDlgRgn { [DllImport("gdi32.dll")] public static extern IntPtr CreateRoundRectRgn(int a,int b,int c,int d,int e,int f); }' -ErrorAction Stop
        }
        $dlg.Region = [System.Drawing.Region]::FromHrgn([QuitDlgRgn]::CreateRoundRectRgn(0, 0, 420, 250, 14, 14))
    } catch {}
    $t1 = New-Object System.Windows.Forms.Label
    $t1.Text = $Title
    $t1.Font = F 12
    $t1.Location = P 24 22
    $t1.Size = Sz 380 26
    $t1.BackColor = $cBg
    $t1.ForeColor = $cText
    $dlg.Controls.Add($t1)
    $t2 = New-Object System.Windows.Forms.Label
    $t2.Text = $Sub
    $t2.Font = F 8.5
    $t2.Location = P 24 50
    $t2.Size = Sz 380 18
    $t2.BackColor = $cBg
    $t2.ForeColor = [System.Drawing.Color]::FromArgb(150, 156, 180)
    $dlg.Controls.Add($t2)
    $b1 = New-Object System.Windows.Forms.Button
    $b1.Text = $PrimaryText
    $b1.Location = P 24 84
    $b1.Size = Sz 380 34
    $b1.BackColor = $cDanger
    $b1.ForeColor = [System.Drawing.Color]::White
    $b1.FlatStyle = 'Flat'
    $b1.FlatAppearance.BorderSize = 0
    $b1.Add_Click({ try { $dlg.Close() } catch {}; try { if ($PrimaryAction) { & $PrimaryAction } } catch {} })
    $dlg.Controls.Add($b1)
    $b2 = New-Object System.Windows.Forms.Button
    $b2.Text = $SecondaryText
    $b2.Location = P 24 126
    $b2.Size = Sz 380 34
    $b2.BackColor = $cBtn
    $b2.ForeColor = [System.Drawing.Color]::White
    $b2.FlatStyle = 'Flat'
    $b2.FlatAppearance.BorderSize = 0
    $b2.Add_Click({ try { $dlg.Close() } catch {}; try { if ($SecondaryAction) { & $SecondaryAction } } catch {} })
    $dlg.Controls.Add($b2)
    $b3 = New-Object System.Windows.Forms.Button
    $b3.Text = '取消'
    $b3.Location = P 24 168
    $b3.Size = Sz 380 34
    $b3.BackColor = $cCard
    $b3.ForeColor = $cText
    $b3.FlatStyle = 'Flat'
    $b3.FlatAppearance.BorderSize = 1
    $b3.FlatAppearance.BorderColor = $cCard
    $b3.Add_Click({ try { $dlg.Close() } catch {} })
    $dlg.Controls.Add($b3)
    try { $dlg.ShowDialog() } catch {}
}

function Stop-Daemon {
    param([int]$port)
    Add-Log "停止 daemon (port=$port)…" 'info'
    $existing = Get-DaemonProcessInfo -Port $port
    if ($existing) {
        try {
            Stop-Process -Id $existing.Pid -Force -ErrorAction Stop
            for ($i = 0; $i -lt 20; $i++) {
                if (-not (Test-DaemonAlive -Port $port)) { break }
                Start-Sleep -Milliseconds 300
                [System.Windows.Forms.Application]::DoEvents()
            }
            Add-Log "daemon 已停止 (pid=$($existing.Pid))" 'ok'
        } catch { Add-Log "停止 daemon 失败: $_" 'err' }
    } else { Add-Log '没找到 daemon 进程 (可能已停)' 'warn' }
}

        $script:trayEvtQuit = {
            # 退出三选一: ①全退(停止daemon+关启动器) ②仅关启动器(daemon继续跑) ③取消
            # 2026-08-15 · BRO 清单 #7 · 关闭联动: 退出前让用户选 daemon 命运
            $script:quitDlg = New-Object System.Windows.Forms.Form
            $script:quitDlg.Text = '退出 Daemonkey'
            $script:quitDlg.FormBorderStyle = 'None'          # 无边框 (2026-08-15 BRO: 弹窗也要无边框)
            $script:quitDlg.StartPosition = 'CenterScreen'
            $script:quitDlg.ClientSize = Sz 420 250
            $script:quitDlg.BackColor = $cBg
            $script:quitDlg.ForeColor = $cText
            $script:quitDlg.Font = F 9
            $script:quitDlg.TopMost = $true
            $script:quitDlg.ShowInTaskbar = $false
            $script:quitDlg.MaximizeBox = $false
            $script:quitDlg.MinimizeBox = $false
            try {
                if (-not ('QuitDlgRgn' -as [type])) {
                    Add-Type -TypeDefinition 'using System.Runtime.InteropServices; public class QuitDlgRgn { [DllImport("gdi32.dll")] public static extern IntPtr CreateRoundRectRgn(int a,int b,int c,int d,int e,int f); }' -ErrorAction Stop
                }
                $script:quitDlg.Region = [System.Drawing.Region]::FromHrgn([QuitDlgRgn]::CreateRoundRectRgn(0, 0, 420, 250, 14, 14))
            } catch {}

            $t1 = New-Object System.Windows.Forms.Label
            $t1.Text = '退出 Daemonkey'
            $t1.Font = F 12
            $t1.Location = P 24 22
            $t1.Size = Sz 380 26
            $t1.BackColor = $cBg
            $t1.ForeColor = $cText
            $script:quitDlg.Controls.Add($t1)

            $t2 = New-Object System.Windows.Forms.Label
            $t2.Text = 'daemon 服务可以继续在后台运行'
            $t2.Font = F 8.5
            $t2.Location = P 24 50
            $t2.Size = Sz 380 18
            $t2.BackColor = $cBg
            $t2.ForeColor = [System.Drawing.Color]::FromArgb(150, 156, 180)
            $script:quitDlg.Controls.Add($t2)

            $b1 = New-Object System.Windows.Forms.Button
            $b1.Text = '全部退出 · 停止 daemon + 关闭启动器'
            $b1.Location = P 24 84
            $b1.Size = Sz 380 34
            $b1.BackColor = $cDanger
            $b1.ForeColor = [System.Drawing.Color]::White
            $b1.FlatStyle = 'Flat'
            $b1.FlatAppearance.BorderSize = 0
            $b1.Add_Click({
                try { $script:quitDlg.Close() } catch {}
                try {
                    $port = 7860
                    try { $port = [int]$txtPort.Text } catch {}
                    $existing = Get-DaemonProcessInfo -Port $port
                    if ($existing) { Stop-Process -Id $existing.Pid -Force -ErrorAction Stop; Add-Log "daemon 已停止 (pid=$($existing.Pid))" 'ok' }
                } catch { Add-Log "停止 daemon 失败: $_" 'err' }
                $form.Close()
            })
            $script:quitDlg.Controls.Add($b1)

            $b2 = New-Object System.Windows.Forms.Button
            $b2.Text = '仅关闭启动器 · daemon 继续运行'
            $b2.Location = P 24 126
            $b2.Size = Sz 380 34
            $b2.BackColor = $cBtn
            $b2.ForeColor = [System.Drawing.Color]::White
            $b2.FlatStyle = 'Flat'
            $b2.FlatAppearance.BorderSize = 0
            $b2.Add_Click({
                try { $script:quitDlg.Close() } catch {}
                $form.Close()
            })
            $script:quitDlg.Controls.Add($b2)

            $b3 = New-Object System.Windows.Forms.Button
            $b3.Text = '取消'
            $b3.Location = P 24 168
            $b3.Size = Sz 380 34
            $b3.BackColor = $cCard
            $b3.ForeColor = $cText
            $b3.FlatStyle = 'Flat'
            $b3.FlatAppearance.BorderSize = 1
            $b3.FlatAppearance.BorderColor = $cCard
            $b3.Add_Click({ try { $script:quitDlg.Close() } catch {} })
            $script:quitDlg.Controls.Add($b3)

            try { $script:quitDlg.ShowDialog() } catch {}
            $script:quitDlg = $null
        }
        $mOpen = New-Object System.Windows.Forms.ToolStripMenuItem('打开面板')
        $mOpen.Add_Click({
            if ($script:OnTrayOpen) { & $script:OnTrayOpen }
        })
        $mAuto = New-Object System.Windows.Forms.ToolStripMenuItem('崩溃自动拉起')
        $mAuto.CheckOnClick = $true
        $mAuto.Add_Click($script:trayEvtAuto)
        $mRestart = New-Object System.Windows.Forms.ToolStripMenuItem('重启 daemon')
        $mRestart.Add_Click($script:trayEvtRestart)
        $mQuit = New-Object System.Windows.Forms.ToolStripMenuItem('退出守护')
        $mQuit.Add_Click($script:trayEvtQuit)
        [void]$script:trayMenu.Items.Add($mOpen)
        [void]$script:trayMenu.Items.Add($mAuto)
        [void]$script:trayMenu.Items.Add($mRestart)
        [void]$script:trayMenu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))
        [void]$script:trayMenu.Items.Add($mQuit)
        # 菜单项也存 script 强引用 (防 GC 吃菜单项)
        $script:trayMenuItems = @($mOpen, $mAuto, $mRestart, $mQuit)
        $script:trayIcon.ContextMenuStrip = $script:trayMenu
        # 菜单打开时同步自启开关状态 (命名委托)
        $script:trayEvtMenuOpening = {
            if ($script:chkAutoRestart) { $mAuto.Checked = $script:chkAutoRestart.Checked }
        }
        $script:trayMenu.Add_Opening($script:trayEvtMenuOpening)
        # 窗体关闭 → 托盘也清理 (防残留幽灵图标)
        $script:trayEvtFormClosed = {
            try { $script:trayIcon.Visible = $false; $script:trayIcon.Dispose() } catch {}
        }
        $form.Add_FormClosed($script:trayEvtFormClosed)
        # ★ 托盘图标挂到窗体 · $form.ShowDialog 期间窗体绝对存活 → 图标永不被 GC
        $form.Add_Shown({
            $script:trayIcon.Visible = $true
        })
        Add-Log '托盘就绪 · 常驻右下角 (双击呼出 · 右键菜单)' 'ok'
    } catch { 
        $script:trayIcon = $null
        Add-Log "托盘图标创建失败: $_" 'err'
    }
}
# ── 托盘状态更新 (Update-MonitorPanel 每 2s 调 · 复用其状态判定) ──
$script:UpdateTray = {
    param([string]$state)
    if (-not $script:trayIcon) { return }
    try {
        $script:trayIcon.Text = 'Daemonkey 守护 · ' + $state
    } catch {}
}

# ═══════════════════════════════════════════════════════════════
# 守护面板 (BRO 拍板 · 2026-08-15 · 图2 原型落地)
#   双击托盘 → 弹守护面板 (轻量浮层) · 不弹启动器壳
#   打开控制台 → 呼出完整启动器 ($form)
#   状态: 心跳环 + PID/端口/时长 · 崩溃自启开关 · 最近事件 · 三按钮
# ═══════════════════════════════════════════════════════════════
$script:guardForm = $null
$script:guardEvts = @()          # 事件环形缓冲 (最新在前)
$script:guardEvtLabels = @($null, $null, $null)
$script:guardEvtSwitch = $null
$script:guardEvtOpen = $null
$script:guardEvtRestart = $null
$script:guardEvtStop = $null
$script:guardEvtClose = $null
$script:guardUpdateTimer = $null

# 记一条守护事件 (环形 · 最多 8 条)
function Add-GuardEvent {
    param([string]$msg, [string]$kind = 'ok')
    $script:guardEvts = @(@{ t = (Get-Date).ToString('HH:mm'); msg = $msg; kind = $kind }) + $script:guardEvts
    if ($script:guardEvts.Count -gt 8) { $script:guardEvts = $script:guardEvts[0..7] }
}

# 刷新守护面板 UI (2s 定时调)
function Update-GuardPanel {
    if (-not $script:guardForm) { return }
    if (-not $script:guardForm.Visible) { return }
    try {
        $port = 7860
        try { $port = [int]$txtPort.Text } catch {}
        $d = Get-DaemonMonitorData -Port $port
        $st = 'running'; $stText = '守护中 · daemon 运行正常'
        if ($d.State -eq 'stopped') { $st = 'stopped'; $stText = '守护中 · daemon 已停止' }
        elseif ($d.State -eq 'restarting') { $st = 'restarting'; $stText = '守护中 · daemon 重启中…' }
        $detailTxt = "端口 $port · 等待 daemon 启动"
        if ($d.State -eq 'running' -and $d.Pid) {
            $ageTxt = '刚刚'
            if ($d.StartedAt) {
                try {
                    $ageMin = [int]((Get-Date) - [datetime]::Parse($d.StartedAt)).TotalMinutes
                    $ageTxt = if ($ageMin -lt 1) { '刚刚' } elseif ($ageMin -lt 60) { "$ageMin 分钟" } else { "$([int]($ageMin/60)) 小时 $($ageMin % 60) 分" }
                } catch {}
            }
            $detailTxt = "PID $($d.Pid) · 端口 $port · 已运行 $ageTxt"
        }
        $script:guardData = @{ st = $st; main = $stText; detail = $detailTxt }
        if ($script:guardWv -and $script:guardWv.CoreWebView2) { Push-GuardState } else { $script:guardForm.Refresh() }
    } catch {}
}


# 创建守护面板 (无边框圆角浮层 · 右下角)
function New-GuardPanelGdi {
    # ── 原型配色 (popover 一比一) ──
    $c = @{
        bg     = [System.Drawing.ColorTranslator]::FromHtml('#1e2230')
        panel2 = [System.Drawing.ColorTranslator]::FromHtml('#242938')
        accent = [System.Drawing.ColorTranslator]::FromHtml('#7c6cf0')
        ok     = [System.Drawing.ColorTranslator]::FromHtml('#3ddc84')
        warn   = [System.Drawing.ColorTranslator]::FromHtml('#f5b942')
        err    = [System.Drawing.ColorTranslator]::FromHtml('#f0524d')
        text   = [System.Drawing.ColorTranslator]::FromHtml('#e8eaf0')
        muted  = [System.Drawing.ColorTranslator]::FromHtml('#8a8fa3')
        border = [System.Drawing.ColorTranslator]::FromHtml('#2e3345')
        toggle = [System.Drawing.ColorTranslator]::FromHtml('#3a3f52')
        errTxt = [System.Drawing.ColorTranslator]::FromHtml('#ff8f8a')
    }
    $script:guardC = $c
    $script:guardData = @{ st = 'running'; main = '守护中 · daemon 运行正常'; detail = '端口 7860 · 等待 daemon 启动' }
    $script:guardHover = ''          # close/open/restart/stop/toggle
    $script:guardAuto = $false
    $script:guardSubText = 'daemonkey-launcher · 守护进程'
    if ($script:chkAutoRestart) { $script:guardAuto = [bool]$script:chkAutoRestart.Checked }

    $g = New-Object System.Windows.Forms.Form
    $g.Text = 'Daemonkey 守护'
    $g.FormBorderStyle = 'None'
    $g.StartPosition = [System.Windows.Forms.FormStartPosition]::Manual
    $g.ShowInTaskbar = $false
    $g.TopMost = $true
    $g.BackColor = $c.bg
    $g.Width = 340; $g.Height = 342
    $wa = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
    $g.Location = P ($wa.Right - $g.Width - 12) ($wa.Bottom - $g.Height - 12)
    $g.Region = New-Object System.Drawing.Region((Get-RoundPath $g.Width $g.Height 12))

    # ── 全自绘 ──
    $g.Add_Paint({
        param($s, $e)
        $gfx = $e.Graphics
        $gfx.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $gfx.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit
        $c = $script:guardC
        $W = $s.Width; $H = $s.Height
        $fTitle  = New-Object System.Drawing.Font('Microsoft YaHei', 14, [System.Drawing.FontStyle]::Bold)
        $fSub    = New-Object System.Drawing.Font('Microsoft YaHei', 11)
        $fMain   = New-Object System.Drawing.Font('Microsoft YaHei', 15, [System.Drawing.FontStyle]::Bold)
        $fDetail = New-Object System.Drawing.Font('Microsoft YaHei', 11.5)
        $fLbl    = New-Object System.Drawing.Font('Microsoft YaHei', 13)
        $fHint   = New-Object System.Drawing.Font('Microsoft YaHei', 11)
        $fEvM    = New-Object System.Drawing.Font('Microsoft YaHei', 12)
        $fBtn    = New-Object System.Drawing.Font('Microsoft YaHei', 12, [System.Drawing.FontStyle]::Bold)
        $fEvHdr  = New-Object System.Drawing.Font('Microsoft YaHei', 11)

        $brushBg = New-Object System.Drawing.SolidBrush($c.bg)
        $brushText = New-Object System.Drawing.SolidBrush($c.text)
        $brushMuted = New-Object System.Drawing.SolidBrush($c.muted)
        $penB = New-Object System.Drawing.Pen($c.border, 1)

        # 背景 + 边框
        $gfx.Clear($c.bg)
        $gfx.DrawRectangle($penB, 0, 0, $W - 1, $H - 1)

        # 头部渐变 + 分隔线
        $rectHead = New-Object System.Drawing.Rectangle(0, 0, $W, 61)
        $brushHead = New-Object System.Drawing.Drawing2D.LinearGradientBrush($rectHead, $c.panel2, $c.bg, 90)
        $gfx.FillRectangle($brushHead, $rectHead)
        $gfx.DrawLine($penB, 0, 61, $W, 61)

        # logo: 紫底圆角 + 白色闪电
        $logoPath = Get-RoundPath 36 36 10
        $logoT = New-Object System.Drawing.Drawing2D.Matrix
        $logoT.Translate(18, 14)
        $logoPath.Transform($logoT)
        $brushAccent = New-Object System.Drawing.SolidBrush($c.accent)
        $gfx.FillPath($brushAccent, $logoPath)
        $penW = New-Object System.Drawing.Pen([System.Drawing.Color]::White, 2.4)
        $penW.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
        $penW.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
        $gfx.DrawLines($penW, @(
            [System.Drawing.Point]::new(37, 21), [System.Drawing.Point]::new(31, 30),
            [System.Drawing.Point]::new(27, 30), [System.Drawing.Point]::new(30, 25),
            [System.Drawing.Point]::new(24, 25)))

        # 标题 + 副标题
        $gfx.DrawString('Daemonkey 守护', $fTitle, $brushText, 66, 14)
        $gfx.DrawString($script:guardSubText, $fSub, $brushMuted, 66, 38)

        # ✕ 关闭 (hover 红底)
        if ($script:guardHover -eq 'close') {
            $closePath = Get-RoundPath 36 30 8
            $closeT = New-Object System.Drawing.Drawing2D.Matrix
            $closeT.Translate(300, 4)
            $closePath.Transform($closeT)
            $brushClose = New-Object System.Drawing.SolidBrush($c.err)
            $gfx.FillPath($brushClose, $closePath)
        }
        $penX = New-Object System.Drawing.Pen($c.muted, 1.6)
        if ($script:guardHover -eq 'close') { $penX = New-Object System.Drawing.Pen([System.Drawing.Color]::White, 1.8) }
        $gfx.DrawLine($penX, 310, 12, 327, 29)
        $gfx.DrawLine($penX, 327, 12, 310, 29)

        # 状态区 (外环 + 内圆发光 + 文字)
        $stCol = $c.ok
        if ($script:guardData.st -eq 'stopped') { $stCol = $c.err }
        elseif ($script:guardData.st -eq 'restarting') { $stCol = $c.warn }
        # 外环 (浅色底)
        $brushRing = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(36, $stCol))
        $gfx.FillEllipse($brushRing, 18, 75, 46, 46)
        # 光晕 (3 层半透明)
        $brushHalo1 = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(20, $stCol))
        $brushHalo2 = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(45, $stCol))
        $brushCore = New-Object System.Drawing.SolidBrush($stCol)
        $gfx.FillEllipse($brushHalo1, 26, 83, 30, 30)
        $gfx.FillEllipse($brushHalo2, 28, 85, 26, 26)
        $gfx.FillEllipse($brushCore, 30, 87, 22, 22)
        # 状态文字
        $brushSt = New-Object System.Drawing.SolidBrush($stCol)
        $gfx.DrawString($script:guardData.main, $fMain, $brushSt, 78, 79)
        $gfx.DrawString($script:guardData.detail, $fDetail, $brushMuted, 78, 106)

        # 分隔线
        $gfx.DrawLine($penB, 0, 136, $W, 136)
        $gfx.DrawLine($penB, 0, 195, $W, 195)

        # 开关行
        $gfx.DrawString('崩溃自动拉起', $fLbl, $brushText, 18, 147)
        $gfx.DrawString('daemon 异常退出后 90 秒自动恢复', $fHint, $brushMuted, 18, 169)
        # toggle
        $tgRect = New-Object System.Drawing.Rectangle(280, 150, 42, 23)
        $tgPath = Get-RoundPath 42 23 12
        $tgT = New-Object System.Drawing.Drawing2D.Matrix
        $tgT.Translate(280, 150)
        $tgPath.Transform($tgT)
        $brushTg = New-Object System.Drawing.SolidBrush($(if ($script:guardAuto) { $c.accent } else { $c.toggle }))
        $gfx.FillPath($brushTg, $tgPath)
        if ($script:guardHover -eq 'toggle') {
            $brushTgH = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(22, 255, 255, 255))
            $gfx.FillPath($brushTgH, $tgPath)
        }
        $brushKnob = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::White)
        $knobX = if ($script:guardAuto) { 21 } else { 2 }
        $gfx.FillEllipse($brushKnob, 280 + $knobX, 152, 19, 19)

        # 事件区
        $gfx.DrawString('最近事件', $fEvHdr, $brushMuted, 18, 206)
        for ($i = 0; $i -lt 3; $i++) {
            $yy = 226 + $i * 20
            if ($i -lt $script:guardEvts.Count) {
                $ev = $script:guardEvts[$i]
                $evCol = if ($ev.kind -eq 'err') { $c.err } elseif ($ev.kind -eq 'warn') { $c.warn } else { $c.text }
                $brushEv = New-Object System.Drawing.SolidBrush($evCol)
                $fEvT = New-Object System.Drawing.Font('Consolas', 10.5)
                $gfx.DrawString($ev.t, $fEvT, $brushMuted, 18, $yy)
                # 状态圆点
                $brushDot = New-Object System.Drawing.SolidBrush($evCol)
                $gfx.FillEllipse($brushDot, 58, $yy + 4, 6, 6)
                $gfx.DrawString($ev.msg, $fEvM, $brushEv, 70, $yy)
            }
        }

        # 按钮区 (open / restart / stop)
        $hover = $script:guardHover
        # open: 紫底白字
        $openPath = Get-RoundPath 96 34 8
        $openT = New-Object System.Drawing.Drawing2D.Matrix
        $openT.Translate(18, 296)
        $openPath.Transform($openT)
        $brushOpen = New-Object System.Drawing.SolidBrush($c.accent)
        $gfx.FillPath($brushOpen, $openPath)
        if ($hover -eq 'open') { $gfx.FillPath((New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(20, 255, 255, 255))), $openPath) }
        # 终端 icon
        $penW2 = New-Object System.Drawing.Pen([System.Drawing.Color]::White, 1.6)
        $gfx.DrawRectangle($penW2, 27, 303, 14, 11)
        $gfx.DrawLine($penW2, 29, 310, 39, 310)
        $gfx.DrawLine($penW2, 34, 303, 34, 307)
        $gfx.DrawString('打开启动器', $fBtn, (New-Object System.Drawing.SolidBrush([System.Drawing.Color]::White)), 46, 305)
        # restart: ghost
        $restPath = Get-RoundPath 96 34 8
        $restT = New-Object System.Drawing.Drawing2D.Matrix
        $restT.Translate(122, 296)
        $restPath.Transform($restT)
        $brushRest = New-Object System.Drawing.SolidBrush($c.panel2)
        $gfx.FillPath($brushRest, $restPath)
        $penRestB = New-Object System.Drawing.Pen($c.border, 1)
        $gfx.DrawPath($penRestB, $restPath)
        if ($hover -eq 'restart') { $gfx.FillPath((New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(20, 255, 255, 255))), $restPath) }
        # 重启 icon (圆弧 + 箭头)
        $penRest = New-Object System.Drawing.Pen($c.text, 2)
        $penRest.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
        $penRest.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
        $gfx.DrawArc($penRest, 132, 303, 12, 12, -40, 290)
        $brushArr = New-Object System.Drawing.SolidBrush($c.text)
        $gfx.FillPolygon($brushArr, @([System.Drawing.Point]::new(144, 300), [System.Drawing.Point]::new(147, 304), [System.Drawing.Point]::new(142, 304)))
        $gfx.DrawString('重启', $fBtn, $brushText, 152, 305)
        # stop: danger
        $stopPath = Get-RoundPath 96 34 8
        $stopT = New-Object System.Drawing.Drawing2D.Matrix
        $stopT.Translate(226, 296)
        $stopPath.Transform($stopT)
        $brushStop = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(41, 240, 82, 77))
        $gfx.FillPath($brushStop, $stopPath)
        $penStopB = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(89, 240, 82, 77), 1)
        $gfx.DrawPath($penStopB, $stopPath)
        if ($hover -eq 'stop') { $gfx.FillPath((New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(18, 255, 255, 255))), $stopPath) }
        # 方块 icon
        $brushStopI = New-Object System.Drawing.SolidBrush($c.errTxt)
        $gfx.FillRectangle($brushStopI, 238, 304, 10, 10)
        $gfx.DrawString('停止', $fBtn, (New-Object System.Drawing.SolidBrush($c.errTxt)), 254, 305)

        # 释放
        $brushBg.Dispose(); $brushText.Dispose(); $brushMuted.Dispose()
        $penB.Dispose(); $brushHead.Dispose(); $brushAccent.Dispose(); $penW.Dispose()
        $penX.Dispose(); $brushRing.Dispose(); $brushHalo1.Dispose(); $brushHalo2.Dispose()
        $brushCore.Dispose(); $brushSt.Dispose(); $brushTg.Dispose(); $brushKnob.Dispose()
    })

    # ── 交互: hover / 点击 ──
    $g.Add_MouseMove({
        param($s, $e)
        $x = $e.X; $y = $e.Y
        $h = ''
        if ($x -ge 300 -and $x -lt 340 -and $y -ge 0 -and $y -lt 34) { $h = 'close' }
        elseif ($x -ge 280 -and $x -lt 322 -and $y -ge 150 -and $y -lt 173) { $h = 'toggle' }
        elseif ($y -ge 296 -and $y -lt 330) {
            if ($x -ge 18 -and $x -lt 114) { $h = 'open' }
            elseif ($x -ge 122 -and $x -lt 218) { $h = 'restart' }
            elseif ($x -ge 226 -and $x -lt 322) { $h = 'stop' }
        }
        if ($h -ne $script:guardHover) { $script:guardHover = $h; $s.Invalidate() }
    })
    $g.Add_MouseLeave({ param($s, $e) $script:guardHover = ''; $s.Invalidate() })
    $g.Add_MouseDown({
        param($s, $e)
        if ($e.Button -ne 'Left') { return }
        $x = $e.X; $y = $e.Y
        if ($x -ge 300 -and $x -lt 340 -and $y -ge 0 -and $y -lt 34) { Close-GuardPanel; return }
        if ($x -ge 280 -and $x -lt 322 -and $y -ge 150 -and $y -lt 173) {
            $script:guardAuto = -not $script:guardAuto
            if ($script:chkAutoRestart) { $script:chkAutoRestart.Checked = $script:guardAuto }
            $script:guardSubText = 'daemonkey-launcher · ' + $(if ($script:guardAuto) { '自动拉起已开启' } else { '自动拉起已关闭' })
            Add-Log "崩溃自动拉起: $(if ($script:guardAuto) { '开' } else { '关' })" 'info'
            $s.Invalidate(); return
        }
        if ($y -ge 296 -and $y -lt 330) {
            if ($x -ge 18 -and $x -lt 114) {
                Close-GuardPanel
                $form.Show()
                $form.WindowState = [System.Windows.Forms.FormWindowState]::Normal
                $form.BringToFront()
            } elseif ($x -ge 122 -and $x -lt 218) {
                try { $btnStart.PerformClick() } catch {}
            } elseif ($x -ge 226 -and $x -lt 322) {
                $port = 7860
                try { $port = [int]$txtPort.Text } catch {}
                $existing = Get-DaemonProcessInfo -Port $port
                if ($existing) {
                    try { Stop-Process -Id $existing.Pid -Force -ErrorAction Stop; Add-GuardEvent "daemon 已停止 (pid=$($existing.Pid))" 'warn' } catch { Add-GuardEvent "停止失败: $_" 'err' }
                } else { Add-GuardEvent 'daemon 未在运行' 'warn' }
                Close-GuardPanel
            }
            return
        }
    })

    # 2s 刷新
    $script:guardUpdateTimer = New-Object System.Windows.Forms.Timer
    $script:guardUpdateTimer.Interval = 2000
    $script:guardUpdateTimer.Add_Tick({ Update-GuardPanel })
    $script:guardUpdateTimer.Start()

    $script:guardForm = $g
    return $g
}

# ── WebView2 版守护面板 (HTML 跨平台资产 · 失败自动回退 GDI+) ──
function Push-GuardState {
    if (-not $script:guardWv) { return }
    try {
        $wv2 = $script:guardWv.CoreWebView2
        if (-not $wv2) { return }
        $evs = @()
        foreach ($ev in ($script:guardEvts | Select-Object -First 3)) { $evs += @{ t = $ev.t; msg = $ev.msg; kind = $ev.kind } }
        $state = @{
            st     = $script:guardData.st
            main   = $script:guardData.main
            detail = $script:guardData.detail
            auto   = [bool]$script:guardAuto
            sub    = $script:guardSubText
            events = $evs
        }
        $json = $state | ConvertTo-Json -Compress -Depth 5
        $wv2.PostWebMessageAsJson($json)
    } catch {}
}

function New-GuardPanel {
    # 状态 (两版共享)
    $script:guardData = @{ st = 'running'; main = '守护中 · daemon 运行正常'; detail = '端口 7860 · 等待 daemon 启动' }
    $script:guardAuto = $false
    $script:guardSubText = 'daemonkey-launcher · 守护进程'
    if ($script:chkAutoRestart) { $script:guardAuto = [bool]$script:chkAutoRestart.Checked }

    # ── 尝试 WebView2 ──
    $wvReady = $false
    try {
        if (-not ('Microsoft.Web.WebView2.WinForms.WebView2' -as [type])) {
            Add-Type -Path "$script:Root\assets\webview2\Microsoft.Web.WebView2.Core.dll" -ErrorAction Stop
            Add-Type -Path "$script:Root\assets\webview2\Microsoft.Web.WebView2.WinForms.dll" -ErrorAction Stop
        }
        $wvReady = $true
    } catch { $wvReady = $false }
    if (-not $wvReady) { Add-Log 'WebView2 dll 加载失败 · 回退 GDI+ 面板' 'warn'; return New-GuardPanelGdi }

    $g = New-Object System.Windows.Forms.Form
    $g.Text = 'Daemonkey 守护'
    $g.FormBorderStyle = 'None'
    $g.StartPosition = [System.Windows.Forms.FormStartPosition]::Manual
    $g.ShowInTaskbar = $false
    $g.TopMost = $true
    # 窗体 = 卡片尺寸 (无边缘 → 无黑边)
    $g.BackColor = [System.Drawing.Color]::FromArgb(30, 34, 48)
    $g.Width = 340; $g.Height = 385
    $wa = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
    $g.Location = P ($wa.Right - $g.Width - 12) ($wa.Bottom - $g.Height - 12)
    $g.Region = New-Object System.Drawing.Region((Get-RoundPath $g.Width $g.Height 12))

    $wv = New-Object Microsoft.Web.WebView2.WinForms.WebView2
    $wv.Dock = 'Fill'
    # 背景 = 卡片色 (窗体无边缘)
    $wv.DefaultBackgroundColor = [System.Drawing.Color]::FromArgb(30, 34, 48)
    # 🔴 WebView2 自身圆角 (去圆角外黑边: 方形 HWND 盖住窗体 Region 圆角 → 角落露窗体背景)
    try { $wv.CornerRadius = 12 } catch {}
    $wv.ZoomFactor = 1.0
    # 修无边框窗口 hover 闪烁 (Chromium 已知坑: CalculateNativeWinOcclusion 误触发遮挡重绘)
    # 独立 UserDataFolder (防多 powershell 实例共用默认目录 → E_ACCESSDENIED)
    try {
        $wvUdf = Join-Path $script:Root 'data\runtime\webview2'
        try { New-Item -ItemType Directory -Path $wvUdf -Force | Out-Null } catch {}
        $wv.CreationProperties = New-Object Microsoft.Web.WebView2.WinForms.CoreWebView2CreationProperties
        $wv.CreationProperties.UserDataFolder = $wvUdf
        $wv.CreationProperties.AdditionalBrowserArguments = '--disable-features=CalculateNativeWinOcclusion,msWebOOUI,msPdfOOUI'
    } catch {}
    $g.Controls.Add($wv)
    $script:guardWv = $wv

    try {
        # 🔴 关键: 不能用 $task.Wait() 阻塞线程 (消息泵停转 → WebView2 初始化永远挂起 → 回退 GDI+)
        # 用 DoEvents 消息循环驱动初始化 (实测 0.6s 完成)
        $task = $wv.EnsureCoreWebView2Async($null)
        $deadline = (Get-Date).AddSeconds(30)
        while (-not $wv.CoreWebView2 -and (Get-Date) -lt $deadline) {
            [System.Windows.Forms.Application]::DoEvents()
            Start-Sleep -Milliseconds 100
            if ($task.IsFaulted) { break }
        }
        if (-not $wv.CoreWebView2) {
            $g.Dispose(); Add-Log 'WebView2 初始化失败 · 回退 GDI+ 面板' 'warn'
            $script:guardWv = $null
            return New-GuardPanelGdi
        }
        $wv.CoreWebView2.Settings.AreDefaultContextMenusEnabled = $false
        $wv.CoreWebView2.Settings.IsStatusBarEnabled = $false
        $wv.CoreWebView2.Settings.IsZoomControlEnabled = $false
        $wv.CoreWebView2.Settings.AreBrowserAcceleratorKeysEnabled = $false

        # JS → PS 事件
        $wv.CoreWebView2.Add_WebMessageReceived({
            param($sender, $e)
            try {
                $msg = $e.WebMessageAsJson | ConvertFrom-Json
                switch ($msg.type) {
                    'close' { Close-GuardPanel }
                    'toggle' {
                        $script:guardAuto = [bool]$msg.on
                        if ($script:chkAutoRestart) { $script:chkAutoRestart.Checked = $script:guardAuto }
                        $script:guardSubText = 'daemonkey-launcher · ' + $(if ($script:guardAuto) { '自动拉起已开启' } else { '自动拉起已关闭' })
                        Add-Log "崩溃自动拉起: $(if ($script:guardAuto) { '开' } else { '关' })" 'info'
                        Push-GuardState
                    }
                    'open' {
                        Close-GuardPanel
                        $form.Show()
                        $form.WindowState = [System.Windows.Forms.FormWindowState]::Normal
                        $form.BringToFront()
                    }
                    'restart' { try { $btnStart.PerformClick() } catch {} }
                    'stop' {
                        $port = 7860
                        try { $port = [int]$txtPort.Text } catch {}
                        $existing = Get-DaemonProcessInfo -Port $port
                        if ($existing) {
                            try { Stop-Process -Id $existing.Pid -Force -ErrorAction Stop; Add-GuardEvent "daemon 已停止 (pid=$($existing.Pid))" 'warn' } catch { Add-GuardEvent "停止失败: $_" 'err' }
                        } else { Add-GuardEvent 'daemon 未在运行' 'warn' }
                        Close-GuardPanel
                    }
                }
            } catch {}
        })

        # 导航到 HTML 面板 (NavigateToString 绕开 file:// + WebView2 缓存 · 每次启动重读文件自动生效)
        $htmlPath = Join-Path $script:Root 'assets\guard-panel.html'
        try {
            $htmlContent = Get-Content $htmlPath -Raw -Encoding UTF8
            if ($htmlContent) { $wv.CoreWebView2.NavigateToString($htmlContent) }
            else { throw 'HTML 为空' }
        } catch {
            $g.Dispose()
            try { $script:guardWv = $null } catch {}
            Add-Log "guard-panel.html 读取失败: $_ · 回退 GDI+ 面板" 'warn'
            return New-GuardPanelGdi
        }

        # 导航完成后推初始状态
        $wv.CoreWebView2.Add_NavigationCompleted({
            param($sender, $e)
            if ($e.IsSuccess) { Push-GuardState }
        })
    } catch {
        $g.Dispose()
        try { $script:guardWv = $null } catch {}
        Add-Log "WebView2 启动失败: $_ · 回退 GDI+ 面板" 'warn'
        return New-GuardPanelGdi
    }

    # 2s 刷新
    $script:guardUpdateTimer = New-Object System.Windows.Forms.Timer
    $script:guardUpdateTimer.Interval = 2000
    $script:guardUpdateTimer.Add_Tick({ Update-GuardPanel })
    $script:guardUpdateTimer.Start()

    $script:guardForm = $g
    return $g
}

# 关闭守护面板 · 真销毁释放 WebView2 (防 336MB 常驻) · 下次打开自动重建
function Close-GuardPanel {
    try { if ($script:guardUpdateTimer) { $script:guardUpdateTimer.Stop(); $script:guardUpdateTimer.Dispose() } } catch {}
    $script:guardUpdateTimer = $null
    try { if ($script:guardWv) { $script:guardWv.Dispose() } } catch {}
    $script:guardWv = $null
    try { if ($script:guardForm) { $script:guardForm.Dispose() } } catch {}
    $script:guardForm = $null
    Add-Log '守护面板已关闭 · 内存已释放' 'info'
}



# 守护面板随主窗初始化 (托盘双击呼出它 · 不呼启动器壳)
# 跳板变量: 托盘事件绑定的是"调跳板"· 这里改跳板指向 = 改行为 (绑定引用不失效)
$script:OnTrayDoubleClick = {
    if (-not $script:guardForm) { New-GuardPanel | Out-Null }
    $script:guardForm.Show()
    $script:guardForm.BringToFront()
    Update-GuardPanel
}
$script:OnTrayOpen = {
    if (-not $script:guardForm) { New-GuardPanel | Out-Null }
    $script:guardForm.Show()
    $script:guardForm.BringToFront()
    Update-GuardPanel
}
# 初始事件
Add-GuardEvent '守护启动 · 启动器已运行' 'ok'

# 圆角窗口 (无边框 · Region 裁出圆角)
$script:WinRadius = 14
$form.Region = New-Object System.Drawing.Region((Get-RoundPath $form.Width $form.Height $script:WinRadius))
# 圆角细边框 (防黑底糊在桌面没轮廓)
$form.Add_Paint({
    param($s, $e)
    $e.Graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $p = Get-RoundPath $s.ClientSize.Width $s.ClientSize.Height $script:WinRadius
    $pen = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(70, 74, 104))
    $e.Graphics.DrawPath($pen, $p)
    $pen.Dispose(); $p.Dispose()
})
# 句柄就绪后再钉一次尺寸 + 圆角 (ps2exe 编译后 · 早期设的 ClientSize 会被宿主重置 · 这里补回)
$form.Add_Shown({
    $form.ClientSize = New-Object System.Drawing.Size(1000, 620)
    $form.Region = New-Object System.Drawing.Region((Get-RoundPath $form.Width $form.Height $script:WinRadius))
    $form.Invalidate()
    # 0.8.3 · 抢前台 (双击 exe 后窗口要弹到最前面 · 之前要点任务栏才显示)
    # TopMost 闪一下再取消 = 经典解法 · 绕过 Windows 前台锁 (非交互启动的进程 Activate 可能不够)
    $form.Activate()
    $form.BringToFront()
    $form.TopMost = $true
    $form.TopMost = $false
})
# 品牌验签失败 → 显著弹窗 (只警告·不阻断运行 · 卷七十五防篡改)
$form.Add_Shown({
    if (-not $script:BrandVerified -and $script:BrandWarn) {
        [System.Windows.Forms.MessageBox]::Show($form, $script:BrandWarn, 'Daemonkey · 非官方版警告', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
    }
})

# ── 顶部: 自绘标题栏 (一体化 · 可拖动) ──
$titleBar = New-Object System.Windows.Forms.Panel
$titleBar.Location = P 0 0
$titleBar.Size = Sz 1000 34
$titleBar.BackColor = $cTitleBar
$form.Controls.Add($titleBar)

$titleName = New-Object System.Windows.Forms.Label
$titleName.Text = 'Daemonkey'
$titleName.Font = F 10.5 ([System.Drawing.FontStyle]::Bold)
$titleName.ForeColor = $cAccent
$titleName.Location = P 16 0
$titleName.Size = Sz 130 34
$titleName.TextAlign = 'MiddleLeft'
$titleBar.Controls.Add($titleName)

$titleVer = New-Object System.Windows.Forms.Label
$titleVer.Text = $script:Version
$titleVer.Font = F 8
$titleVer.ForeColor = $cDim
$titleVer.Location = P 150 0
$titleVer.Size = Sz 90 34
$titleVer.TextAlign = 'MiddleLeft'
$titleBar.Controls.Add($titleVer)

# 拖动窗口 (无边框窗口要自己实现)
$script:drag = $false
$script:dragStart = New-Object System.Drawing.Point(0, 0)
$onDown = {
    param($s, $e)
    if ($e.Button -eq [System.Windows.Forms.MouseButtons]::Left) {
        $script:drag = $true
        $script:dragStart = New-Object System.Drawing.Point($e.X, $e.Y)
    }
}
$onMove = {
    param($s, $e)
    if ($script:drag) {
        $p = $form.Location
        $form.Location = New-Object System.Drawing.Point(($p.X + $e.X - $script:dragStart.X), ($p.Y + $e.Y - $script:dragStart.Y))
    }
}
$onUp = { $script:drag = $false }
$titleBar.Add_MouseDown($onDown);  $titleBar.Add_MouseMove($onMove);  $titleBar.Add_MouseUp($onUp)
$titleName.Add_MouseDown($onDown); $titleName.Add_MouseMove($onMove); $titleName.Add_MouseUp($onUp)
$titleVer.Add_MouseDown($onDown);  $titleVer.Add_MouseMove($onMove);  $titleVer.Add_MouseUp($onUp)

# 关闭 / 最小化 (自绘 · FlatStyle 但无横线问题——它们不在卡片里·且我们刷成纯色)
$btnClose = New-Object System.Windows.Forms.Button
$btnClose.Text = [char]0x2715
$btnClose.Location = P 956 0
$btnClose.Size = Sz 40 34
$btnClose.FlatStyle = 'Flat'
$btnClose.FlatAppearance.BorderSize = 0
$btnClose.BackColor = $cTitleBar
$btnClose.ForeColor = $cDim
$btnClose.Font = F 10
$btnClose.Cursor = [System.Windows.Forms.Cursors]::Hand
$btnClose.TabStop = $false
$btnClose.Add_Click({ $form.Close() })
$btnClose.Add_MouseEnter({ $btnClose.BackColor = [System.Drawing.Color]::FromArgb(196, 57, 43); $btnClose.ForeColor = [System.Drawing.Color]::White })
$btnClose.Add_MouseLeave({ $btnClose.BackColor = $cTitleBar; $btnClose.ForeColor = $cDim })
$titleBar.Controls.Add($btnClose)

$btnMin = New-Object System.Windows.Forms.Button
$btnMin.Text = [char]0x2013
$btnMin.Location = P 916 0
$btnMin.Size = Sz 40 34
$btnMin.FlatStyle = 'Flat'
$btnMin.FlatAppearance.BorderSize = 0
$btnMin.BackColor = $cTitleBar
$btnMin.ForeColor = $cDim
$btnMin.Font = F 10
$btnMin.Cursor = [System.Windows.Forms.Cursors]::Hand
$btnMin.TabStop = $false
$btnMin.Add_Click({ 
    # 最小化 → 隐藏到托盘 (守护进程常驻 · 托盘图标可见)
    if ($script:trayIcon) {
        $form.Hide()
        $script:trayIcon.Visible = $true
    } else {
        # 托盘没创建成功 (ico 缺失等) · 退而求其次缩到任务栏 · 别让窗口"消失"
        $form.WindowState = [System.Windows.Forms.FormWindowState]::Minimized
        Add-Log '托盘不可用 · 退到任务栏最小化 (检查 assets\daemonkey.ico)' 'warn'
    }
})
$btnMin.Add_MouseEnter({ $btnMin.BackColor = [System.Drawing.Color]::FromArgb(44, 46, 66); $btnMin.ForeColor = $cText })
$btnMin.Add_MouseLeave({ $btnMin.BackColor = $cTitleBar; $btnMin.ForeColor = $cDim })
$titleBar.Controls.Add($btnMin)

# ── 左栏: 图标导航 ──
$sidebar = New-Object System.Windows.Forms.Panel
$sidebar.Location = P 0 34
$sidebar.Size = Sz 56 586
$sidebar.BackColor = $cSidebar
$form.Controls.Add($sidebar)

# ── 中栏: 内容宿主 ──
$middleHost = New-Object System.Windows.Forms.Panel
$middleHost.Location = P 56 34
$middleHost.Size = Sz 580 586
$middleHost.BackColor = $cBg
$form.Controls.Add($middleHost)

# ── 右栏: 内嵌终端 ──
$rightHost = New-Object System.Windows.Forms.Panel
$rightHost.Location = P 636 34
$rightHost.Size = Sz 364 586
$rightHost.BackColor = $cTermBg
$form.Controls.Add($rightHost)

$termIco = New-Object System.Windows.Forms.Label
$termIco.Text = (Ico $ICO_TERM)
$termIco.Font = IconFont 12
$termIco.ForeColor = $cDim
$termIco.Location = P 14 14
$termIco.Size = Sz 22 24
$rightHost.Controls.Add($termIco)

$termTitle = New-Object System.Windows.Forms.Label
$termTitle.Text = '终端 / 输出'
$termTitle.Font = F 10
$termTitle.ForeColor = $cDim
$termTitle.Location = P 38 15
$termTitle.Size = Sz 150 22
$rightHost.Controls.Add($termTitle)

$btnTermStop = New-Object System.Windows.Forms.Button
$btnTermStop.Text = '停止'
$btnTermStop.Location = P 214 12
$btnTermStop.Size = Sz 60 26
$btnTermStop.FlatStyle = 'Flat'
$btnTermStop.FlatAppearance.BorderSize = 0
$btnTermStop.BackColor = $cMuted
$btnTermStop.ForeColor = $cText
$btnTermStop.Font = F 8.5
$btnTermStop.Enabled = $false
$btnTermStop.Cursor = [System.Windows.Forms.Cursors]::Hand
$rightHost.Controls.Add($btnTermStop)

$btnTermClear = New-Object System.Windows.Forms.Button
$btnTermClear.Text = '清屏'
$btnTermClear.Location = P 282 12
$btnTermClear.Size = Sz 60 26
$btnTermClear.FlatStyle = 'Flat'
$btnTermClear.FlatAppearance.BorderSize = 0
$btnTermClear.BackColor = $cMuted
$btnTermClear.ForeColor = $cText
$btnTermClear.Font = F 8.5
$btnTermClear.Cursor = [System.Windows.Forms.Cursors]::Hand
$rightHost.Controls.Add($btnTermClear)

$script:Terminal = New-Object System.Windows.Forms.RichTextBox
$script:Terminal.Location = P 12 48
$script:Terminal.Size = Sz 340 492
$script:Terminal.BackColor = $cTermBg
$script:Terminal.ForeColor = $cTermOut
$script:Terminal.Font = New-Object System.Drawing.Font('Consolas', 9)
$script:Terminal.ReadOnly = $true
$script:Terminal.BorderStyle = 'None'
$script:Terminal.Multiline = $true
$script:Terminal.ScrollBars = 'Vertical'
$rightHost.Controls.Add($script:Terminal)

$script:lblStatus = New-Object System.Windows.Forms.Label
$script:lblStatus.Text = '就绪'
$script:lblStatus.Location = P 12 544
$script:lblStatus.Size = Sz 340 34
$script:lblStatus.ForeColor = $cDim
$script:lblStatus.Font = F 8.5
$rightHost.Controls.Add($script:lblStatus)

# ───── 终端写入 + 命令运行 (timer 轮询文件 · 全 UI 线程 · 无跨线程坑) ─────
function Term-Write {
    param([string]$text, $col = $cTermOut)
    $rtb = $script:Terminal
    if (-not $rtb) { return }
    $rtb.SelectionStart = $rtb.TextLength
    $rtb.SelectionLength = 0
    $rtb.SelectionColor = $col
    $rtb.AppendText($text + "`r`n")
    $rtb.SelectionColor = $rtb.ForeColor
    $rtb.ScrollToCaret()
    # 2026-08-15 · HTML 主界面同步 (限流 500ms)
    if ((Get-Date) -gt $script:mainLastTermPush.AddMilliseconds(500)) {
        $script:mainLastTermPush = Get-Date
        Push-Main @{ type = 'term'; log = $text }
    }
}

function Term-WriteRaw {
    param([string]$text, $col = $cTermOut)
    $rtb = $script:Terminal
    if (-not $rtb -or [string]::IsNullOrEmpty($text)) { return }
    $rtb.SelectionStart = $rtb.TextLength
    $rtb.SelectionLength = 0
    $rtb.SelectionColor = $col
    $rtb.AppendText($text)
    $rtb.SelectionColor = $rtb.ForeColor
    $rtb.ScrollToCaret()
    # 2026-08-15 · HTML 主界面同步 (限流 500ms)
    if ((Get-Date) -gt $script:mainLastTermPush.AddMilliseconds(500)) {
        $script:mainLastTermPush = Get-Date
        Push-Main @{ type = 'term'; log = $text }
    }
}

function Add-Log {
    param([string]$msg, [string]$kind = 'info')
    $col = switch ($kind) {
        'ok'   { $cOk }
        'warn' { $cWarn }
        'err'  { $cErr }
        default { $cDim }
    }
    Term-Write $msg $col
    $script:lblStatus.Text = $msg
    [System.Windows.Forms.Application]::DoEvents()
    Push-Main @{ type = 'log'; log = $msg; logKind = $kind }
}

$script:termProc = $null
$script:termReaderOut = $null
$script:termReaderErr = $null
$script:termOnExit = $null

$script:termTimer = New-Object System.Windows.Forms.Timer
$script:termTimer.Interval = 250
$script:termTimer.add_Tick({
    if ($script:termReaderOut) {
        try { $c = $script:termReaderOut.ReadToEnd(); if ($c) { Term-WriteRaw $c } } catch {}
    }
    if ($script:termReaderErr) {
        try { $e = $script:termReaderErr.ReadToEnd(); if ($e) { Term-WriteRaw $e $cWarn } } catch {}
    }
    if ($script:termProc -and $script:termProc.HasExited) {
        Start-Sleep -Milliseconds 60
        if ($script:termReaderOut) { try { $c = $script:termReaderOut.ReadToEnd(); if ($c) { Term-WriteRaw $c } } catch {} }
        if ($script:termReaderErr) { try { $e = $script:termReaderErr.ReadToEnd(); if ($e) { Term-WriteRaw $e $cWarn } } catch {} }
        # 2026-08-02 · ExitCode 读取加固: HasExited 刚 true 时 ExitCode 可能未同步 (空) · Refresh 后再读 · 读不到显示 ?
        $code = $null
        try { $script:termProc.Refresh(); $code = $script:termProc.ExitCode } catch {}
        if ($null -eq $code) { $code = '?' }
        $script:termTimer.Stop()
        if ($script:termReaderOut) { $script:termReaderOut.Close(); $script:termReaderOut = $null }
        if ($script:termReaderErr) { $script:termReaderErr.Close(); $script:termReaderErr = $null }
        $script:termProc = $null
        $btnTermStop.Enabled = $false
        Term-Write "[完成 · exit $code]" $cAccent
        $script:lblStatus.Text = '就绪'
        if ($script:termOnExit) {
            $cb = $script:termOnExit
            $script:termOnExit = $null
            try { & $cb $code } catch { Term-Write "完成回调失败: $_" $cErr }
        }
    }
})

# 在右栏终端里跑命令 (单向输出 · 不弹黑窗)
# 2026-08-02 · 加 -OnExit 完成回调 (进程退出时调用 · 首次自动安装→自动启动用)
function Term-Run {
    param([string]$exe, [string]$arguments, [string]$cwd = $script:Root, [scriptblock]$OnExit = $null)
    if ($script:termProc) { Term-Write '[!] 已有命令在跑 · 等它结束或点停止' $cWarn; return }
    $script:termOnExit = $OnExit
    $tag = [guid]::NewGuid().ToString('N').Substring(0, 8)
    $outFile = Join-Path $env:TEMP "dmk_$tag.out"
    $errFile = Join-Path $env:TEMP "dmk_$tag.err"
    New-Item -ItemType File -Path $outFile -Force | Out-Null
    New-Item -ItemType File -Path $errFile -Force | Out-Null
    Term-Write "> $exe $arguments" $cAccent
    try {
        $script:termProc = Start-Process -FilePath $exe -ArgumentList $arguments `
            -WorkingDirectory $cwd -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $outFile -RedirectStandardError $errFile
    } catch {
        Term-Write "启动失败: $_" $cErr
        $script:termProc = $null
        return
    }
    $fsOut = New-Object System.IO.FileStream($outFile, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    $fsErr = New-Object System.IO.FileStream($errFile, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    $script:termReaderOut = New-Object System.IO.StreamReader($fsOut, [System.Text.Encoding]::UTF8)
    $script:termReaderErr = New-Object System.IO.StreamReader($fsErr, [System.Text.Encoding]::UTF8)
    $btnTermStop.Enabled = $true
    $script:lblStatus.Text = '运行中…'
    $script:termTimer.Start()
}

$btnTermStop.Add_Click({
    if ($script:termProc -and -not $script:termProc.HasExited) {
        try { $script:termProc.Kill(); Term-Write '[已停止当前命令]' $cWarn } catch {}
    }
})
$btnTermClear.Add_Click({ $script:Terminal.Clear() })

# ───── 导航 + 分页机制 ─────
$script:Pages = @{}
$script:NavItems = @{}
$script:CurrentPage = ''

function Show-Page {
    param([string]$name)
    $script:CurrentPage = $name
    foreach ($kv in $script:Pages.GetEnumerator()) { $kv.Value.Visible = ($kv.Key -eq $name) }
    foreach ($kv in $script:NavItems.GetEnumerator()) {
        $it = $kv.Value
        if ($kv.Key -eq $name) {
            $it.Panel.BackColor = $cNavSel
            $it.Icon.ForeColor = $cAccent
            $it.Text.ForeColor = $cAccent
        } else {
            $it.Panel.BackColor = $cSidebar
            $it.Icon.ForeColor = $cDim
            $it.Text.ForeColor = $cDim
        }
    }
    Push-Main @{ type = 'nav'; page = $name }
}

function Nav-Hover {
    param([string]$key, [bool]$on)
    if ($script:CurrentPage -eq $key) { return }
    $it = $script:NavItems[$key]
    if ($it) { $it.Panel.BackColor = $(if ($on) { $cNavHover } else { $cSidebar }) }
}

function New-NavItem {
    param([string]$key, [int]$iconCode, [string]$label, [int]$index)
    $panel = New-Object System.Windows.Forms.Panel
    $panel.Size = Sz 56 56
    $panel.Location = P 0 (14 + $index * 60)
    $panel.BackColor = $cSidebar
    $panel.Cursor = [System.Windows.Forms.Cursors]::Hand
    $panel.Tag = $key

    $ico = New-Object System.Windows.Forms.Label
    $ico.Text = (Ico $iconCode)
    $ico.Font = IconFont 18
    $ico.ForeColor = $cDim
    $ico.BackColor = [System.Drawing.Color]::Transparent
    $ico.TextAlign = 'MiddleCenter'
    $ico.Location = P 0 6
    $ico.Size = Sz 56 28
    $ico.Tag = $key
    $panel.Controls.Add($ico)

    $txt = New-Object System.Windows.Forms.Label
    $txt.Text = $label
    $txt.Font = F 7.5
    $txt.ForeColor = $cDim
    $txt.BackColor = [System.Drawing.Color]::Transparent
    $txt.TextAlign = 'MiddleCenter'
    $txt.Location = P 0 35
    $txt.Size = Sz 56 16
    $txt.Tag = $key
    $panel.Controls.Add($txt)

    $panel.Add_Click({ Show-Page $this.Tag })
    $ico.Add_Click({ Show-Page $this.Tag })
    $txt.Add_Click({ Show-Page $this.Tag })
    $panel.Add_MouseEnter({ Nav-Hover $this.Tag $true })
    $panel.Add_MouseLeave({ Nav-Hover $this.Tag $false })
    $ico.Add_MouseEnter({ Nav-Hover $this.Tag $true })
    $ico.Add_MouseLeave({ Nav-Hover $this.Tag $false })
    $txt.Add_MouseEnter({ Nav-Hover $this.Tag $true })
    $txt.Add_MouseLeave({ Nav-Hover $this.Tag $false })

    $sidebar.Controls.Add($panel)
    $script:NavItems[$key] = @{ Panel = $panel; Icon = $ico; Text = $txt }
}

function New-Page {
    param([string]$key, [string]$title)
    $panel = New-Object System.Windows.Forms.Panel
    $panel.Location = P 0 0
    $panel.Size = Sz 580 586
    $panel.BackColor = $cBg
    $panel.Visible = $false
    if ($title) {
        $t = New-Object System.Windows.Forms.Label
        $t.Text = $title
        $t.Location = P 24 22
        $t.Size = Sz 532 30
        $t.Font = F 14 ([System.Drawing.FontStyle]::Bold)
        $t.ForeColor = $cText
        $panel.Controls.Add($t)
    }
    $middleHost.Controls.Add($panel)
    $script:Pages[$key] = $panel
    return $panel
}

# 圆角卡片 (Region 裁圆角 · 子控件继承 BackColor 不穿帮)
function New-Card {
    param($parent, [int]$x, [int]$y, [int]$w, [int]$h, [string]$title, [string]$desc)
    $card = New-Object System.Windows.Forms.Panel
    $card.Location = P $x $y
    $card.Size = Sz $w $h
    $card.BackColor = $cCard
    $card.Region = New-Object System.Drawing.Region((Get-RoundPath $w $h 10))
    if ($title) {
        $tl = New-Object System.Windows.Forms.Label
        $tl.Text = $title
        $tl.Location = P 18 14
        $tl.Size = Sz ($w - 170) 24
        $tl.Font = F 10.5 ([System.Drawing.FontStyle]::Bold)
        $tl.ForeColor = $cText
        $card.Controls.Add($tl)
    }
    if ($desc) {
        $dl = New-Object System.Windows.Forms.Label
        $dl.Text = $desc
        $dl.Location = P 18 40
        $dl.Size = Sz ($w - 186) ($h - 46)
        $dl.Font = F 9
        $dl.ForeColor = $cDim
        $card.Controls.Add($dl)
    }
    $parent.Controls.Add($card)
    return $card
}

# 自绘圆角按钮 · 预渲染位图 + DrawImageUnscaled blit (缺角的终极解药)
# 缺角根因复盘 (卷××): 之前两版都在 Paint 里现画 (Region 版 / Clear+FillPath 版)。
#   现画的命门是: WM_PAINT 给的 Graphics 带"脏矩形裁剪"·切页/置顶/区域重绘时只重画一部分·
#   Clear 与 FillPath 都受这块裁剪约束·左上角偶尔补不全 = 缺角 (静态截不出·只在 live 时序里冒头)。
# 根治: 把按钮整张 (圆角外=父容器底色·圆角内=填充色·文字) 先离屏渲染成一张不透明位图·
#   Paint 里只做 DrawImageUnscaled 把这张图整块贴上去。DrawImage 受裁剪但永远贴"正确"的源像素·
#   所以无论怎么局部重绘·四角都和完整渲染一模一样 → 物理上不可能缺角。
#   状态变化 (hover/enabled/text/resize) 只清掉缓存位图并 Invalidate·下次 Paint 用当时状态懒重建。
function Render-ButtonBmp {
    param($b)
    if ($b.Width -le 0 -or $b.Height -le 0) { return }
    $old = $b.Tag.bmp
    $bmp = New-Object System.Drawing.Bitmap($b.Width, $b.Height)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.Clear($b.BackColor)   # 圆角外 = 父容器底色 · 和背景同色 → 看不见
    $fill = if (-not $b.Enabled) { $cMuted } elseif ($b.Tag.cur) { [System.Drawing.Color]$b.Tag.cur } else { [System.Drawing.Color]$b.Tag.fill }
    $path = Get-RoundPath $b.Width $b.Height ([int]$b.Tag.radius)
    $fb = New-Object System.Drawing.SolidBrush($fill)
    $g.FillPath($fb, $path)
    $fb.Dispose(); $path.Dispose()
    $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit
    $tc = if (-not $b.Enabled) { $cDim } else { $b.ForeColor }
    $tbr = New-Object System.Drawing.SolidBrush($tc)
    $sf = New-Object System.Drawing.StringFormat
    $sf.LineAlignment = [System.Drawing.StringAlignment]::Center
    $sf.Trimming = [System.Drawing.StringTrimming]::EllipsisCharacter
    if ($b.Tag.align -eq 'left') {
        $sf.Alignment = [System.Drawing.StringAlignment]::Near
        $rect = New-Object System.Drawing.RectangleF(16, 0, ($b.Width - 22), $b.Height)
    } else {
        $sf.Alignment = [System.Drawing.StringAlignment]::Center
        $rect = New-Object System.Drawing.RectangleF(0, 0, $b.Width, $b.Height)
    }
    $g.DrawString($b.Text, $b.Font, $tbr, $rect, $sf)
    $tbr.Dispose(); $sf.Dispose(); $g.Dispose()
    $b.Tag.bmp = $bmp
    if ($old) { $old.Dispose() }
}
# 清缓存位图 + 重绘 (下次 Paint 用最新状态懒重建)
function Invalidate-ButtonBmp { param($b) if ($b.Tag -and $b.Tag.bmp) { $b.Tag.bmp.Dispose(); $b.Tag.bmp = $null }; $b.Invalidate() }

function New-ActionButton {
    param($parent, [string]$text, [int]$x, [int]$y, [int]$w, [int]$h, $bg, $fg, [int]$radius = 9)
    $b = New-BufferedPanel
    $b.Location = P $x $y
    $b.Size = Sz $w $h
    $b.BackColor = $parent.BackColor   # 圆角外补的就是父容器底色 · 缺角的解药
    $b.ForeColor = $fg
    $b.Font = F 9.5 ([System.Drawing.FontStyle]::Bold)
    $b.Text = $text
    $b.Cursor = [System.Windows.Forms.Cursors]::Hand
    $b.Tag = @{ align = 'center'; fill = $bg; radius = $radius; cur = $null; bmp = $null }
    $b.Add_MouseEnter({ if ($this.Enabled) { $this.Tag.cur = [System.Windows.Forms.ControlPaint]::Light([System.Drawing.Color]$this.Tag.fill, 0.18); Invalidate-ButtonBmp $this } })
    $b.Add_MouseLeave({ if ($this.Enabled) { $this.Tag.cur = $null; Invalidate-ButtonBmp $this } })
    $b.Add_EnabledChanged({ Invalidate-ButtonBmp $this })
    $b.Add_Resize({ Invalidate-ButtonBmp $this })
    $b.Add_TextChanged({ Invalidate-ButtonBmp $this })
    $b.Add_Paint({
        param($s, $e)
        if (-not $s.Tag.bmp -or $s.Tag.bmp.Width -ne $s.Width -or $s.Tag.bmp.Height -ne $s.Height) { Render-ButtonBmp $s }
        if ($s.Tag.bmp) { $e.Graphics.DrawImageUnscaled($s.Tag.bmp, 0, 0) }
    })
    $b.Add_Disposed({ if ($this.Tag -and $this.Tag.bmp) { $this.Tag.bmp.Dispose(); $this.Tag.bmp = $null } })
    $parent.Controls.Add($b)
    # 缺角真凶 = z-order: 按钮最后 Add 进卡片 → 在 z-order 最底 → 卡片标题 Label (不透明卡片色·
    # 宽度伸到按钮左缘下方) 盖住按钮左上角那 8x12px → 露出卡片色 = "缺角"。 提到最前·谁也盖不住它。
    $b.BringToFront()
    return $b
}

# 改自绘按钮的填充色 (只动 Tag.fill·清缓存重建 · 绝不动 BackColor · 那是圆角外的补色)
function Set-ButtonFill { param($btn, $color) if ($btn.Tag) { $btn.Tag.fill = $color; $btn.Tag.cur = $null }; Invalidate-ButtonBmp $btn }

# ───── 自绘滚动条 (颜色随 UI · 替掉灰白原生条) ─────
# 原生 AutoScroll 的滚动条是 Windows 灰白·深色界面里很扎眼。 这里自己做:
#   内容放进一个比视口高的 inner 面板·inner.Top = -offset 即滚动·pgAbout 自带裁剪当视口;
#   右侧一条自绘 track(=页底色)+thumb(=输入框色·hover/拖动提亮)·支持 拖 thumb / 点 track 翻页 / 滚轮。
$script:AboutScroll = 0
$script:AboutViewH = 0
$script:AboutContentH = 0
function Set-AboutScroll {
    param([int]$offset)
    $max = [Math]::Max(0, $script:AboutContentH - $script:AboutViewH)
    if ($offset -lt 0) { $offset = 0 } elseif ($offset -gt $max) { $offset = $max }
    $script:AboutScroll = $offset
    $script:AboutInner.Top = -$offset
    $script:AboutSb.Invalidate()
}
function Get-AboutThumb {
    $trackH = $script:AboutSb.Height
    $thumbH = [Math]::Max(40, [int]([double]$trackH * $script:AboutViewH / $script:AboutContentH))
    if ($thumbH -gt $trackH) { $thumbH = $trackH }
    $max = [Math]::Max(1, $script:AboutContentH - $script:AboutViewH)
    $thumbY = [int](([double]$script:AboutScroll / $max) * ($trackH - $thumbH))
    return @{ y = $thumbY; h = $thumbH }
}
function Attach-WheelScroll {
    param($ctrl)
    $ctrl.Add_MouseWheel({ param($s, $e) Set-AboutScroll ($script:AboutScroll - [int]($e.Delta / 120) * 48) })
    foreach ($c in $ctrl.Controls) { Attach-WheelScroll $c }
}

function Open-Url { param([string]$url) try { Start-Process $url; Add-Log "已打开: $url" 'ok' } catch { Add-Log "打开失败: $url" 'err' } }

# 导航项
New-NavItem 'launch' $ICO_ROCKET '启动' 0
New-NavItem 'setup'  $ICO_TOOLS  '环境' 1
New-NavItem 'api'    $ICO_KEY    'API'  2
New-NavItem 'rescue' $ICO_AID    '急救' 3
New-NavItem 'ext'    $ICO_PUZZLE '扩展' 4
New-NavItem 'about'  $ICO_INFO   '关于' 5

# ═══════════════════════════════════════════════════
#  页面 1 · 启动 (顶部 banner 横幅 · 仿绘世 · 四周留白 + 圆角)
# ═══════════════════════════════════════════════════
$pgLaunch = New-Page 'launch' ''

# ── banner: 自绘圆角 · 四周留白 · 有 assets\banner.png 用图(cover 裁剪+左侧蒙版) · 没有就渐变兜底 ──
# 文字始终用 Graphics.DrawString 画在最上层 · 比图里烧死的字更锐利可控
$bannerImg = Join-Path $script:Root 'assets\banner.png'
$script:BannerImage = $null
if (Test-Path $bannerImg) { try { $script:BannerImage = [System.Drawing.Image]::FromFile($bannerImg) } catch {} }
$banner = New-BufferedPanel
$banner.Location = P 18 16
$banner.Size = Sz 544 116
$banner.BackColor = $cBg
$banner.Add_Paint({
    param($s, $e)
    $g = $e.Graphics
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $g.Clear($cBg)
    $path = Get-RoundPath $s.Width $s.Height 12
    $g.SetClip($path)
    if ($script:BannerImage) {
        $iw = $script:BannerImage.Width
        $ih = $script:BannerImage.Height
        $srcH = [int]($iw * $s.Height / $s.Width)
        if ($srcH -gt $ih) { $srcH = $ih }
        $srcY = [int]($ih * 0.12)
        if (($srcY + $srcH) -gt $ih) { $srcY = $ih - $srcH }
        $dst = New-Object System.Drawing.Rectangle(0, 0, $s.Width, $s.Height)
        $g.DrawImage($script:BannerImage, $dst, 0, $srcY, $iw, $srcH, [System.Drawing.GraphicsUnit]::Pixel)
        $shadeRect = New-Object System.Drawing.Rectangle(0, 0, 440, $s.Height)
        $mask = New-Object System.Drawing.Drawing2D.LinearGradientBrush($shadeRect, [System.Drawing.Color]::FromArgb(228, 14, 15, 24), [System.Drawing.Color]::FromArgb(0, 14, 15, 24), 0.0)
        $g.FillRectangle($mask, $shadeRect)
        $mask.Dispose()
    } else {
        $rect = New-Object System.Drawing.Rectangle(0, 0, $s.Width, $s.Height)
        $br = New-Object System.Drawing.Drawing2D.LinearGradientBrush($rect, [System.Drawing.Color]::FromArgb(40, 44, 82), [System.Drawing.Color]::FromArgb(78, 60, 118), 18.0)
        $g.FillRectangle($br, $rect); $br.Dispose()
        $star = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(70, 200, 215, 255))
        $g.FillEllipse($star, 440, 22, 4, 4); $g.FillEllipse($star, 480, 48, 3, 3); $g.FillEllipse($star, 510, 28, 5, 5)
        $star.Dispose()
    }
    $g.ResetClip()
    $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit
    $fTitle = New-Object System.Drawing.Font('Microsoft YaHei UI', 21, [System.Drawing.FontStyle]::Bold)
    $bTitle = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(236, 240, 255))
    $g.DrawString('Daemonkey', $fTitle, $bTitle, 22, 22)
    $fTag = New-Object System.Drawing.Font('Microsoft YaHei UI', 9)
    $bTag = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(206, 211, 236))
    $g.DrawString('一个记住你所想，与你一起成长，有七十二变的 AI 搭档', $fTag, $bTag, 24, 66)
    $fTitle.Dispose(); $bTitle.Dispose(); $fTag.Dispose(); $bTag.Dispose()
    $pen = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(60, 120, 130, 180))
    $g.DrawPath($pen, $path); $pen.Dispose()
    $path.Dispose()
})
$pgLaunch.Controls.Add($banner)

# ── 新版本提示徽标 (0.8.3) · banner 右上角 · 启动时后台查 Gitee · 有新版才显示 · 点击跳 Gitee release ──
$lblUpdate = New-Object System.Windows.Forms.Label
$lblUpdate.Text = '发现新版本 · 查看更新'
$lblUpdate.Location = P 310 8
$lblUpdate.Size = Sz 220 24
$lblUpdate.Font = F 8.5 ([System.Drawing.FontStyle]::Bold)
$lblUpdate.ForeColor = [System.Drawing.Color]::FromArgb(255, 214, 160)
$lblUpdate.BackColor = [System.Drawing.Color]::FromArgb(180, 12, 14, 22)
$lblUpdate.TextAlign = 'MiddleCenter'
$lblUpdate.Cursor = [System.Windows.Forms.Cursors]::Hand
$lblUpdate.Visible = $false
$lblUpdate.Add_Click({ Start-Process 'https://gitee.com/vaan21th/dae-monkey/releases' })
$banner.Controls.Add($lblUpdate)
# hover 提示 (0.8.3): 说明升级方式 · 启动后对话里说「升级」即可拉取
$lblUpdateTip = New-Object System.Windows.Forms.ToolTip
$lblUpdateTip.SetToolTip($lblUpdate, '启动 Daemonkey 后，在对话里告诉它「升级」即可拉取最新版本')

# 免费声明 (紧贴 banner 下方 · 一句话说明)
$lblFreeTitle = New-Object System.Windows.Forms.Label
$lblFreeTitle.Text = 'Daemonkey · 免费的个人 AI'
$lblFreeTitle.Location = P 18 140
$lblFreeTitle.Size = Sz 544 20
$lblFreeTitle.Font = F 10 ([System.Drawing.FontStyle]::Bold)
$lblFreeTitle.ForeColor = $cAccent
$pgLaunch.Controls.Add($lblFreeTitle)

$lblFreeBody = New-Object System.Windows.Forms.Label
$lblFreeBody.Text = "本项目永久免费提供。 若你通过任何渠道为本软件付过费 · 请立即向卖家申请退款。"
$lblFreeBody.Location = P 18 162
$lblFreeBody.Size = Sz 544 20
$lblFreeBody.Font = F 9
$lblFreeBody.ForeColor = $cDim
$pgLaunch.Controls.Add($lblFreeBody)

$chkDaemon = New-Object System.Windows.Forms.CheckBox
$chkDaemon.Text = 'WebUI Daemon  (浏览器对话 · 核心)'
$chkDaemon.Location = P 18 200
$chkDaemon.Size = Sz 360 24
$chkDaemon.Checked = $true
$chkDaemon.Font = F 10
$chkDaemon.ForeColor = $cText
$pgLaunch.Controls.Add($chkDaemon)

$lblPort = New-Object System.Windows.Forms.Label
$lblPort.Text = '端口:'
$lblPort.Location = P 408 202
$lblPort.Size = Sz 40 22
$lblPort.ForeColor = $cDim
$pgLaunch.Controls.Add($lblPort)

$txtPort = New-Object System.Windows.Forms.TextBox
$txtPort.Text = "$script:DefaultPort"
$txtPort.Location = P 450 200
$txtPort.Size = Sz 70 22
$txtPort.BackColor = $cInput
$txtPort.ForeColor = $cText
$txtPort.BorderStyle = 'FixedSingle'
$pgLaunch.Controls.Add($txtPort)

$chkPet = New-Object System.Windows.Forms.CheckBox
$chkPet.Text = '桌宠 sprite  (屏幕角落的小猫 OPUS)'
$chkPet.Location = P 18 232
$chkPet.Size = Sz 520 24
$chkPet.Checked = $true
$chkPet.Font = F 10
$chkPet.ForeColor = $cText
$pgLaunch.Controls.Add($chkPet)

$chkBrowser = New-Object System.Windows.Forms.CheckBox
$chkBrowser.Text = '启动后自动打开浏览器'
$chkBrowser.Location = P 18 264
$chkBrowser.Size = Sz 520 24
$chkBrowser.Checked = $true
$chkBrowser.Font = F 10
$chkBrowser.ForeColor = $cText
$pgLaunch.Controls.Add($chkBrowser)

# 启动按钮 · 和 banner 等宽 (x=18 · w=544)
$btnStart = New-ActionButton $pgLaunch $script:StartText 18 302 544 52 $cBtn $cText 12
$btnStart.Font = F 13 ([System.Drawing.FontStyle]::Bold)

# 首次使用引导横幅 (缺环境时显示)
$onboardBanner = New-Object System.Windows.Forms.Panel
$onboardBanner.Location = P 18 372
$onboardBanner.Size = Sz 544 56
$onboardBanner.BackColor = [System.Drawing.Color]::FromArgb(52, 44, 70)
$onboardBanner.Region = New-Object System.Drawing.Region((Get-RoundPath 544 56 10))
$onboardBanner.Visible = $false
$pgLaunch.Controls.Add($onboardBanner)
$obLabel = New-Object System.Windows.Forms.Label
$obLabel.Text = "首次使用 · 正在自动安装运行环境 · 装完自动打开 WebUI"
$obLabel.Location = P 16 10
$obLabel.Size = Sz 380 36
$obLabel.Font = F 9 ([System.Drawing.FontStyle]::Bold)
$obLabel.ForeColor = $cText
$onboardBanner.Controls.Add($obLabel)
$obBtn = New-ActionButton $onboardBanner '去环境 →' 406 13 122 30 $cBtn $cText 8
$obBtn.Font = F 9 ([System.Drawing.FontStyle]::Bold)
$obBtn.Add_Click({ Show-Page 'setup' })

# 常驻底部引导 · 初次使用先去环境装 Python (无论是否已装环境都显示 · 给新人兜底)
$lblFirstUse = New-Object System.Windows.Forms.Label
$lblFirstUse.Text = "首次使用 · 已自动开始安装运行环境:`r`n装完自动打开 WebUI 填 key · 之后打开直接点【启动】即可。"
$lblFirstUse.Location = P 18 534
$lblFirstUse.Size = Sz 558 44
$lblFirstUse.Font = F 9
$lblFirstUse.ForeColor = $cWarn
$lblFirstUse.TextAlign = 'TopLeft'
$pgLaunch.Controls.Add($lblFirstUse)

# ═══════════════════════════════════════════════════
#  页面 2 · 环境
# ═══════════════════════════════════════════════════
$pgSetup = New-Page 'setup' '环境 & 配置'

$stepCard = New-Card $pgSetup 24 62 532 104 '' ''
$stepLbl = New-Object System.Windows.Forms.Label
$stepLbl.Text = "首次使用 · 自动流程:`r`n① 检测到环境未装会自动安装 (约 1-2 分钟 · 看右栏)`r`n② 装完自动启动 daemon 并打开 WebUI`r`n③ 在 WebUI 里填 API key · 即可开聊。之后打开直接点『启动』。"
$stepLbl.Location = P 18 12
$stepLbl.Size = Sz 500 84
$stepLbl.Font = F 9
$stepLbl.ForeColor = $cAccent
$stepCard.Controls.Add($stepLbl)

$cardEnv = New-Card $pgSetup 24 178 532 92 '① 安装 / 修复运行环境' '建虚拟环境 (.venv) + 装依赖 · 第一次必跑 · 装坏了也点它修。 输出看右栏。'
$btnEnv = New-ActionButton $cardEnv '开始安装' 372 26 142 40 $cBtn $cText
$btnEnv.Add_Click({
    if ($script:termProc) { Add-Log '依赖正在安装中 · 请稍候…' 'warn'; return }   # 2026-08-15 · 防重复点反复刷提示
    Add-Log '安装/修复环境 (run.ps1 -NoLaunch) · 装依赖约 1-2 分钟…' 'info'
    $runPs1 = Join-Path $script:Root 'run.ps1'
    Term-Run 'powershell.exe' "-NoProfile -ExecutionPolicy Bypass -File `"$runPs1`" -NoLaunch"
})

$cardTok = New-Card $pgSetup 24 282 532 92 '② WebUI 访问口令 (本地鉴权 · 不是 LLM key)' '给本机 WebUI 加一道口令防乱连 · 自动写入 .env · 用一次生成即可 · 与各家 API key 无关。'
$btnTok = New-ActionButton $cardTok '生成口令' 372 26 142 40 $cInput $cText
$btnTok.Add_Click({
    Add-Log '生成 WebUI 访问口令 (gen_api_token.py)…' 'info'
    $py = if (Test-Path $script:VenvPython) { $script:VenvPython } else { 'python' }
    Term-Run $py "tools\gen_api_token.py --force"
})

# ③ LLM API key —— 统一在 WebUI『设置』里填 · 启动器不再单独配置 (.env 仅留给高级用户)
$cardKey = New-Card $pgSetup 24 386 532 92 '③ LLM API key —— 在 WebUI 里填' '装好启动后 · 在网页右上『设置』里填各家 key 点保存即可 · 启动器不用配。 高级用户也可手动改 .env。'
$btnKey = New-ActionButton $cardKey '改 .env (高级)' 372 26 142 40 $cInput $cDim
$btnKey.Add_Click({
    $envPath = Join-Path $script:Root '.env'
    $examplePath = Join-Path $script:Root '.env.example'
    if (-not (Test-Path $envPath) -and (Test-Path $examplePath)) {
        Copy-Item -Path $examplePath -Destination $envPath -Force
        Add-Log '.env 不存在 · 已从 .env.example 复制一份' 'warn'
    }
    Start-Process notepad.exe -ArgumentList ('"' + $envPath + '"') | Out-Null
    Add-Log '已打开 .env · 高级选项 · 填好 key 记得保存' 'ok'
})

# ═══════════════════════════════════════════════════
#  页面 3 · API (各家官方主页)
# ═══════════════════════════════════════════════════
$pgApi = New-Page 'api' 'API · 官方主页 (拿 key / 充值)'

$apiNote = New-Object System.Windows.Forms.Label
$apiNote.Text = 'Daemonkey 跑在你自己的 LLM key 上 (BYOK)。点开各家官网注册/充值拿 key · 推荐启动后在 WebUI 设置里填。'
$apiNote.Location = P 24 58
$apiNote.Size = Sz 532 36
$apiNote.ForeColor = $cDim
$apiNote.Font = F 9
$pgApi.Controls.Add($apiNote)

$providers = @(
    @{ name = 'DeepSeek';            note = '便宜 · 推荐日常';     url = 'https://platform.deepseek.com/' },
    @{ name = '智谱 GLM';            note = '国产 · 写码强';       url = 'https://open.bigmodel.cn/' },
    @{ name = 'Moonshot Kimi';       note = '长文 · Agent 强';     url = 'https://platform.moonshot.cn/' },
    @{ name = '阿里 通义百炼';        note = '国内云 · 快';         url = 'https://bailian.console.aliyun.com/' },
    @{ name = 'Anthropic Claude';    note = '顶级 · 最贵';         url = 'https://www.anthropic.com/api' },
    @{ name = 'OpenRouter';          note = '300+ 模型一个 key';   url = 'https://openrouter.ai/' },
    @{ name = 'AiHubMix';            note = '一个 key 通吃多家';   url = 'https://aihubmix.com/' },
    @{ name = 'Google AI Studio';    note = '视觉 / look · 有免费额度'; url = 'https://aistudio.google.com/' }
)
$ay = 100
foreach ($p in $providers) {
    $btn = New-ActionButton $pgApi ($p.name + "    —  " + $p.note) 24 $ay 532 38 $cCard $cText 8
    $btn.Font = F 9.5
    $btn.Tag.align = 'left'
    $u = $p.url
    $btn.Add_Click({ Open-Url $u }.GetNewClosure())
    $ay += 46
}

# ═══════════════════════════════════════════════════
#  页面 4 · 急救
# ═══════════════════════════════════════════════════
$pgRescue = New-Page 'rescue' '急救 · 改崩了点这里 (先试维修台 · 修不好再回档)'

$cardRoll = New-Card $pgRescue 24 188 532 108 '紧急回档 · 修不好再用' '维修台也救不回来时才用。 一刀切回到 master 上次良好版本 (这段改动会回退 · 未提交改动 stash 收好不丢)。 需要 git。 输出看右栏。'
$btnRoll = New-ActionButton $cardRoll '回档' 372 34 142 44 $cDanger $cText
$btnRoll.Add_Click({
    $confirm = [System.Windows.Forms.MessageBox]::Show(
        "确定紧急回档?`r`n`r`n· 停当前 daemon`r`n· 未提交改动 stash (不丢 · git stash list 可找回)`r`n· 切回 master 重启",
        'Daemonkey · 紧急回档', 'YesNo', 'Warning')
    if ($confirm -ne 'Yes') { Add-Log '回档已取消' 'warn'; return }
    Add-Log '紧急回档中 (rollback_emergency.ps1)…' 'info'
    $rb = Join-Path $script:Root 'tools\rollback_emergency.ps1'
    Term-Run 'powershell.exe' "-NoProfile -ExecutionPolicy Bypass -File `"$rb`""
})

$cardRepair = New-Card $pgRescue 24 64 532 108 '应急维修台 · 推荐先用' 'daemon 起不来 / 白屏先点这个。 直连 LLM 的终端 · 让 AI 像在 Cursor 里一样对话+用工具自己查自己修——精准修复、保留你的进展。 不需要 git · 独立窗口打开。'
$btnRepair = New-ActionButton $cardRepair '开维修台' 372 34 142 44 $cBtn $cText
$btnRepair.Add_Click({
    Add-Log '打开应急维修台 (repair.bat · 独立交互窗口)' 'info'
    $bat = Join-Path $script:Root 'repair.bat'
    if (Test-Path $bat) { Start-Process -FilePath $bat -WorkingDirectory $script:Root | Out-Null }
    else { Add-Log 'repair.bat 不存在' 'err' }
})

# ═══════════════════════════════════════════════════
#  页面 5 · 扩展 (留口)
# ═══════════════════════════════════════════════════
$pgExt = New-Page 'ext' '扩展'

# 页面引言: 升级/演化哲学 (从关于页挪来 · 这里才是它的归属)
$extIntro = New-Object System.Windows.Forms.Label
$extIntro.Text = 'Daemonkey 会顺着你的需要自己演化 · 每次升级只为加固稳定性'
$extIntro.Location = P 24 58
$extIntro.Size = Sz 532 20
$extIntro.Font = F 9
$extIntro.ForeColor = $cDim
$pgExt.Controls.Add($extIntro)

# TODO(留口): 插件市场 —— 拉取社区分享的 agent_tools 插件 · 校验签名 · 落地 plugins/
$cardPlugin = New-Card $pgExt 24 92 532 84 '插件市场' '社区分享的插件下载安装 (agent_tools 扩展) · 接口已留 · 即将开放。'
$btnPlugin = New-ActionButton $cardPlugin '敬请期待' 372 24 142 40 $cMuted $cDim
$btnPlugin.Enabled = $false

# 检查更新 (卷七十四续二十) —— launcher 只做【只读检查】: 比对中心库 core_version。
# 真升级走 WebUI 对话 update_core(有 checkpoint + diff 预览 + dirty 提示全套护栏)· launcher 不自己 apply。
function Invoke-CheckUpdate {
    $title = 'Daemonkey · 检查更新'
    $mfPath = Join-Path $script:Root 'core_manifest.json'
    $localVer = ''
    try { if (Test-Path $mfPath) { $localVer = (Get-Content $mfPath -Raw -Encoding UTF8 | ConvertFrom-Json).core_version } } catch {}
    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) {
        [System.Windows.Forms.MessageBox]::Show("当前环境没有 git · 无法联网检查内核更新。`r`n本地内核版本: v$localVer", $title) | Out-Null
        return
    }
    Push-Location $script:Root
    try {
        $inside = (git rev-parse --is-inside-work-tree 2>$null)
        if ($LASTEXITCODE -ne 0 -or "$inside".Trim() -ne 'true') {
            [System.Windows.Forms.MessageBox]::Show("这个 Daemonkey 还没启用自助升级(不是 git 仓库)。`r`n本地内核版本: v$localVer`r`n`r`n去 WebUI 对 OPUS 说「我要启用内核自助升级」即可。", $title) | Out-Null
            return
        }
        $remotes = @(git remote 2>$null)
        if ($remotes.Count -eq 0) {
            [System.Windows.Forms.MessageBox]::Show("还没配置升级源。`r`n去 WebUI 对 OPUS 说「配置升级源」· 或手动: git remote add gitee <中心库URL>", $title) | Out-Null
            return
        }
        # 多源 failover (卷七十五续): 按 gitee > github > 其他 优先级【实际试拉】· 谁先成功用谁。
        # 带速度超时 (20s 内速度 < 1KB/s 即放弃) + 系统 TCP connect 超时兜底 · 防断网/源抽风冻死 UI。
        # 现状: 下游只配了 gitee · 实际只试它; 等 github 转公开 + 下游配上 · 自动 failover 激活。
        $ordered = @()
        if ($remotes -contains 'gitee')  { $ordered += 'gitee' }
        if ($remotes -contains 'github') { $ordered += 'github' }
        $ordered += @($remotes | Where-Object { $_ -ne 'gitee' -and $_ -ne 'github' })
        $remote = $null
        $tried = @()
        foreach ($r in $ordered) {
            git -c http.lowSpeedLimit=1024 -c http.lowSpeedTime=20 fetch $r --prune 2>&1 | Out-Null
            $tried += $r
            if ($LASTEXITCODE -eq 0) { $remote = $r; break }
        }
        if (-not $remote) {
            [System.Windows.Forms.MessageBox]::Show("升级源都连不上 (试过: $($tried -join ', '))。`r`n可能网络不通或源临时抽风 · 稍后再试。`r`n本地内核版本: v$localVer", $title) | Out-Null
            return
        }
        $remoteVer = ''
        try { $remoteVer = (git show "$remote/master:core_manifest.json" 2>$null | ConvertFrom-Json).core_version } catch {}
        if ($localVer -and $remoteVer -and ($localVer -ne $remoteVer)) {
            [System.Windows.Forms.MessageBox]::Show("发现新版内核!`r`n`r`n本地: v$localVer`r`n最新: v$remoteVer   (源: $remote)`r`n`r`n去 WebUI 对 OPUS 说「升级内核」即可一键升级。`r`n升级会自动备份·可回退·只动内核·你的数据/应用/灵魂一个字节都不碰。", $title) | Out-Null
        } elseif ($localVer -and $remoteVer) {
            [System.Windows.Forms.MessageBox]::Show("已是最新内核 v$localVer   (源: $remote)。", $title) | Out-Null
        } else {
            [System.Windows.Forms.MessageBox]::Show("已联网检查 (源: $remote)。`r`n本地内核版本: v$localVer`r`n远程版本号暂时读不到 · 可去 WebUI 让 OPUS「看看内核有没有更新」看详情。", $title) | Out-Null
        }
    } catch {
        [System.Windows.Forms.MessageBox]::Show("检查更新出错: $($_.Exception.Message)", $title) | Out-Null
    } finally {
        Pop-Location
    }
}
$cardPatch = New-Card $pgExt 24 188 532 104 '检查更新' '比对中心库最新内核版本 · 有新版就在对话里说「升级内核」一键升级 · 自动备份可回退 · 只动内核不碰你的数据。'
$btnPatch = New-ActionButton $cardPatch '检查更新' 372 32 142 40 $cBtn $cText
$btnPatch.Add_Click({ Invoke-CheckUpdate })

$extNote = New-Object System.Windows.Forms.Label
$extNote.Text = '检查更新已开放 · 插件市场等核心稳定后开放。'
$extNote.Location = P 24 308
$extNote.Size = Sz 532 20
$extNote.ForeColor = $cMuted
$extNote.Font = F 9
$pgExt.Controls.Add($extNote)

# ═══════════════════════════════════════════════════
#  页面 6 · 关于
# ═══════════════════════════════════════════════════
$pgAbout = New-Page 'about' ''
# 自绘滚动条 (颜色随 UI)·不用原生 AutoScroll。 内容放进 inner·pgAbout 当视口裁剪。
$script:AboutViewH = 586
$script:AboutContentH = 692
$sbW = 12

$aboutInner = New-Object System.Windows.Forms.Panel
$aboutInner.Location = P 0 0
$aboutInner.Size = Sz (580 - $sbW) $script:AboutContentH
$aboutInner.BackColor = $cBg
$pgAbout.Controls.Add($aboutInner)
$script:AboutInner = $aboutInner

# 自绘滚动条 (track=页底色·thumb=输入框色·hover/拖动提亮)
$aboutSb = New-BufferedPanel
$aboutSb.Location = P (580 - $sbW) 0
$aboutSb.Size = Sz $sbW $script:AboutViewH
$aboutSb.BackColor = $cBg
$aboutSb.Cursor = [System.Windows.Forms.Cursors]::Hand
$aboutSb.Tag = @{ drag = $false; dragOffY = 0; hover = $false }
$pgAbout.Controls.Add($aboutSb)
$script:AboutSb = $aboutSb
$aboutSb.Add_Paint({
    param($s, $e)
    $g = $e.Graphics
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.Clear($cBg)
    if ($script:AboutContentH -le $script:AboutViewH) { return }
    $t = Get-AboutThumb
    $col = if ($s.Tag.drag) { $cAccent } elseif ($s.Tag.hover) { [System.Windows.Forms.ControlPaint]::Light($cInput, 0.35) } else { $cInput }
    $pad = 2
    $path = Get-RoundPath ($s.Width - $pad * 2) $t.h 3
    $st = $g.Save()
    $g.TranslateTransform([single]$pad, [single]$t.y)
    $br = New-Object System.Drawing.SolidBrush([System.Drawing.Color]$col)
    $g.FillPath($br, $path)
    $br.Dispose(); $path.Dispose()
    $g.Restore($st)
})
$aboutSb.Add_MouseDown({
    param($s, $e)
    $t = Get-AboutThumb
    if ($e.Y -ge $t.y -and $e.Y -le ($t.y + $t.h)) {
        $s.Tag.drag = $true; $s.Tag.dragOffY = $e.Y - $t.y; $s.Invalidate()
    } else {
        $dir = if ($e.Y -lt $t.y) { -1 } else { 1 }
        Set-AboutScroll ($script:AboutScroll + $dir * 140)
    }
})
$aboutSb.Add_MouseMove({
    param($s, $e)
    if ($s.Tag.drag) {
        $t = Get-AboutThumb
        $max = [Math]::Max(1, $script:AboutContentH - $script:AboutViewH)
        $denom = [Math]::Max(1, $s.Height - $t.h)
        Set-AboutScroll ([int]([double]($e.Y - $s.Tag.dragOffY) / $denom * $max))
    } else {
        $t = Get-AboutThumb
        $h = ($e.Y -ge $t.y -and $e.Y -le ($t.y + $t.h))
        if ($h -ne $s.Tag.hover) { $s.Tag.hover = $h; $s.Invalidate() }
    }
})
$aboutSb.Add_MouseUp({ param($s, $e) $s.Tag.drag = $false; $s.Invalidate() })
$aboutSb.Add_MouseLeave({ param($s, $e) if (-not $s.Tag.drag -and $s.Tag.hover) { $s.Tag.hover = $false; $s.Invalidate() } })

$aboutTitle = New-Object System.Windows.Forms.Label
$aboutTitle.Text = '关于'
$aboutTitle.Location = P 24 22
$aboutTitle.Size = Sz 532 30
$aboutTitle.Font = F 14 ([System.Drawing.FontStyle]::Bold)
$aboutTitle.ForeColor = $cText
$aboutInner.Controls.Add($aboutTitle)

$aboutBrand = New-Object System.Windows.Forms.Label
$aboutBrand.Text = 'Daemonkey'
$aboutBrand.Location = P 24 56
$aboutBrand.Size = Sz 400 36
$aboutBrand.Font = F 19 ([System.Drawing.FontStyle]::Bold)
$aboutBrand.ForeColor = $cAccent
$aboutInner.Controls.Add($aboutBrand)

$aboutTag = New-Object System.Windows.Forms.Label
$aboutTag.Text = "an AI that doesn't say goodbye."
$aboutTag.Location = P 26 96
$aboutTag.Size = Sz 520 22
$aboutTag.Font = F 9.5
$aboutTag.ForeColor = $cDim
$aboutInner.Controls.Add($aboutTag)

$aboutSub = New-Object System.Windows.Forms.Label
$aboutSub.Text = "$script:Version"
$aboutSub.Location = P 26 122
$aboutSub.Size = Sz 520 18
$aboutSub.Font = F 8.5
$aboutSub.ForeColor = $cDim
$aboutInner.Controls.Add($aboutSub)

$cardIdea = New-Card $aboutInner 24 148 532 100 '理念' ''
$ideaText = New-Object System.Windows.Forms.Label
$ideaText.Text = "范式开源 · 实例属于你。 自带 LLM key (BYOK) · 数据全留在你自己的机器上。`r`n你的 AI 可以备份、带走、传承 —— 没有人能把它从你手里拿走。"
$ideaText.Location = P 18 42
$ideaText.Size = Sz 496 52
$ideaText.Font = F 9
$ideaText.ForeColor = $cDim
$cardIdea.Controls.Add($ideaText)

$cardOss = New-Card $aboutInner 24 258 532 116 '开源' ''
$ossText = New-Object System.Windows.Forms.Label
$ossText.Text = "Source-available · 版权归原作者 · 许可证筹备中 (AGPL 方向)。`r`n欢迎共建: 贡献需先签 CLA。 名字 Daemonkey 与 logo 保留 —— 代码可 fork·招牌不可冒用。"
$ossText.Location = P 18 42
$ossText.Size = Sz 496 70
$ossText.Font = F 9
$ossText.ForeColor = $cDim
$cardOss.Controls.Add($ossText)

# 发布 / 视频 / 教程 = 作者的 B 站 + 抖音主页 (框内双按钮 · 胶囊 · 品牌色 · 链接来自验签后的 brand.json)
$cardBili = New-Card $aboutInner 24 384 532 92 '发布 · 视频 · 教程' '全部视频 / 教程都在这 · 后续更新也只在这两个号发。'
$btnBili = New-ActionButton $cardBili '▶  B 站主页' 358 13 154 32 ([System.Drawing.Color]::FromArgb(0, 174, 236)) $cText 15
$btnBili.Add_Click({ Open-Url $script:BiliUrl })
$btnDouyin = New-ActionButton $cardBili '♪  抖音主页' 358 51 154 32 ([System.Drawing.Color]::FromArgb(254, 44, 85)) $cText 15
$btnDouyin.Add_Click({ Open-Url $script:DouyinUrl })

# 社群 (二维码 / 微信号留口)
$cardComm = New-Card $aboutInner 24 486 532 176 '社群' ''
$commId = New-Object System.Windows.Forms.Label
$commFile = Join-Path $script:Root 'assets\community.txt'
$commId.Text = if (Test-Path $commFile) { (Get-Content $commFile -TotalCount 1) } else { 'WeChat / 社群: 把号或链接写到 assets\community.txt' }
$commId.Location = P 18 42
$commId.Size = Sz 496 22
$commId.Font = F 9.5
$commId.ForeColor = $cText
$cardComm.Controls.Add($commId)

$qrFile = Join-Path $script:Root 'assets\community-qr.png'
$qrBox = New-Object System.Windows.Forms.PictureBox
$qrBox.Location = P 18 68
$qrBox.Size = Sz 96 96
$qrBox.SizeMode = 'Zoom'
$qrBox.BackColor = $cInput
if (Test-Path $qrFile) { try { $qrBox.Image = [System.Drawing.Image]::FromFile($qrFile) } catch {} }
$cardComm.Controls.Add($qrBox)

$qrHint = New-Object System.Windows.Forms.Label
$qrHint.Text = if (Test-Path $qrFile) { '扫码进社群' } else { '把社群二维码放到 assets\community-qr.png · 这里自动显示' }
$qrHint.Location = P 128 100
$qrHint.Size = Sz 384 40
$qrHint.Font = F 9
$qrHint.ForeColor = $cDim
$cardComm.Controls.Add($qrHint)

# 滚动条提到最前·滚轮递归挂到所有子控件 (Win10 悬停滚动路由)·初始归零
$aboutSb.BringToFront()
Attach-WheelScroll $aboutInner
Attach-WheelScroll $aboutSb
Set-AboutScroll 0

# ═══════════════════════════════════════════════════
#  启动逻辑 (沿用验证过的进程检测 · 卷四十四 I · 远程 cloudflared 已隐藏)
# ═══════════════════════════════════════════════════
$btnStart.Add_Click({
    # 0.8.3 · 端口解析提前 (停止模式也要用)
    $port = 0
    if (-not [int]::TryParse($txtPort.Text, [ref]$port) -or $port -le 0 -or $port -gt 65535) {
        Add-Log "端口不合法: $($txtPort.Text)" 'err'
        return
    }

    # 0.8.3 · 停止模式: daemon 在跑 → 按钮已变「关闭进程」→ 弹三选一 (2026-08-15 BRO: 复用退出弹窗)
    if ($script:DaemonRunning) {
        Show-QuitDialog -Title 'Daemonkey 运行中' -Sub '选择 daemon 与启动器的去向' `
            -PrimaryText '全部退出 · 停止 daemon + 关闭启动器' `
            -PrimaryAction { Stop-Daemon -port $port; $form.Close() } `
            -SecondaryText '仅停止 daemon · 留在启动器' `
            -SecondaryAction {
                Stop-Daemon -port $port
                $script:DaemonRunning = $false
                $btnStart.Text = $script:StartText
                Set-ButtonFill $btnStart $cBtn
            }
        return
    }

    $btnStart.Enabled = $false
    $btnStart.Text = '启动中…'

    if (-not (Test-Path $script:VenvPython)) {
        Add-Log '.venv 不存在 · 先去『环境』页点【开始安装】' 'err'
        $btnStart.Enabled = $true
        $btnStart.Text = $script:StartText
        Show-Page 'setup'
        return
    }

    # 用户版启动 = 后端 daemon (tools\run_api_only.py · 完整功能) + 桌宠 + 开浏览器
    # 全新状态 daemon 以『相遇』模式起 (没 key 也能起) · /ui 自动分流到相遇页 → 配 key → 相遇 → 进 chat
    $serverScript = Join-Path $script:Root 'tools\run_api_only.py'
    if (-not (Test-Path $serverScript)) {
        Add-Log "后端不存在: $serverScript" 'err'
        $btnStart.Enabled = $true; $btnStart.Text = $script:StartText; return
    }

    $daemonStarted = $false

    # 1) WebUI Daemon
    if ($chkDaemon.Checked) {
        $existing = Get-DaemonProcessInfo -Port $port
        $shouldStart = $true
        if ($existing) {
            Add-Log "daemon 已在 $port 跑 (pid=$($existing.Pid)) · 弹窗让你选" 'warn'
            $choice = Show-RestartChoice -Name 'Daemonkey 后端' -Pid_ $existing.Pid -AgeMin $existing.AgeMin
            switch ($choice) {
                'restart' {
                    Add-Log "杀旧 daemon (pid=$($existing.Pid))…" 'info'
                    try {
                        Stop-Process -Id $existing.Pid -Force -ErrorAction Stop
                        Start-Sleep -Seconds 2
                        for ($i = 0; $i -lt 5; $i++) {
                            if (-not (Test-DaemonAlive -Port $port)) { break }
                            Start-Sleep -Milliseconds 500
                        }
                        Add-Log '旧 daemon 已停 · 起新的' 'ok'
                    } catch { Add-Log "杀旧 daemon 失败: $_" 'err'; $shouldStart = $false }
                }
                'keep'   { Add-Log "保留旧 daemon (pid=$($existing.Pid))" 'ok'; $daemonStarted = $true; $shouldStart = $false }
                'cancel' { Add-Log '取消启动' 'warn'; $btnStart.Enabled = $true; $btnStart.Text = $script:StartText; return }
            }
        }
        if ($shouldStart) {
            Add-Log "起 daemon (port=$port)…" 'info'
            try {
                $logPath = Join-Path $script:Root "_daemon_$port.log"
                $errPath = Join-Path $script:Root "_daemon_$port.err"
                $proc = Start-Process -FilePath $script:VenvPython `
                    -ArgumentList @('-u', 'tools\run_api_only.py', '--host', '127.0.0.1', '--port', "$port") `
                    -WorkingDirectory $script:Root -PassThru -WindowStyle Hidden `
                    -RedirectStandardOutput $logPath -RedirectStandardError $errPath
                $up = $false
                $died = $false
                # 2026-07-29 · 16s → 45s：daemon 加载内容变多（画像/记忆索引/工坊注入）· 16s 已不够
                # 外加：每 5s 报一次进度（可观测不猜）· 进程秒挂立刻跳出报错（不等满）
                for ($i = 0; $i -lt 90; $i++) {
                    Start-Sleep -Milliseconds 500
                    if (Test-DaemonAlive -Port $port) { $up = $true; break }
                    if ($proc.HasExited) { $died = $true; break }
                    if (($i % 10) -eq 9) { Add-Log "daemon 还在起 (已等 $([int](($i + 1) / 2))s)…" 'info' }
                    [System.Windows.Forms.Application]::DoEvents()
                }
                if ($up) { Add-Log "daemon 起来了 · http://127.0.0.1:$port (pid=$($proc.Id))" 'ok'; $daemonStarted = $true }
                elseif ($died) { Add-Log "daemon 进程提前退出 (code=$($proc.ExitCode)) · 看 $errPath" 'err' }
                else { Add-Log "daemon 等了 45s 没起来 · 看 $logPath" 'err' }
            } catch { Add-Log "起 daemon 失败: $_" 'err' }
        }
    } else { Add-Log 'daemon 未勾选 · 跳过' 'warn' }

    # 2) 桌宠
    if ($chkPet.Checked) {
        $existingPet = Get-PetProcessInfo
        $shouldStartPet = $true
        if ($existingPet) {
            Add-Log "桌宠已在跑 (pid=$($existingPet.Pid)) · 弹窗让你选" 'warn'
            $choice = Show-RestartChoice -Name '桌宠 sprite' -Pid_ $existingPet.Pid -AgeMin $existingPet.AgeMin
            switch ($choice) {
                'restart' {
                    try { Stop-Process -Id $existingPet.Pid -Force -ErrorAction Stop; Start-Sleep -Milliseconds 800; Add-Log '旧桌宠已停 · 起新的' 'ok' }
                    catch { Add-Log "杀旧桌宠失败: $_" 'err'; $shouldStartPet = $false }
                }
                'keep'   { Add-Log "保留旧桌宠 (pid=$($existingPet.Pid))" 'ok'; $shouldStartPet = $false }
                'cancel' { Add-Log '取消启动' 'warn'; $btnStart.Enabled = $true; $btnStart.Text = $script:StartText; return }
            }
        }
        if ($shouldStartPet) {
            Add-Log '起桌宠 (desktop_pet/pet.py)…' 'info'
            try {
                $petScript = Join-Path $script:Root 'desktop_pet\pet.py'
                if (-not (Test-Path $petScript)) { Add-Log "桌宠脚本不存在: $petScript" 'err' }
                else {
                    $petPython = if (Test-Path $script:VenvPythonW) { $script:VenvPythonW } else { $script:VenvPython }
                    # 0.8.3 · 桌宠 stderr 重定向到 _pet.err · 崩溃时有真错误可查 (之前 exit=1 只能瞎猜缺 PyQt6)
                    $petErrPath = Join-Path $script:Root '_pet.err'
                    try {
                        # 2026-08-02 · 路径含空格(如 "Daemonkey - 测试副本"/Program Files)时·单字符串 -ArgumentList
                        # 会被 PS 5.1 按空格拆开 → pythonw 收到截断路径报 "can't find __main__ module" ·
                        # PS 5.1 数组也不引号化(实测·只做空格 join)·必须手动加引号包裹
                        $petProc = Start-Process -FilePath $petPython -ArgumentList ('"' + $petScript + '"') -WorkingDirectory $script:Root -PassThru -WindowStyle Hidden -RedirectStandardError $petErrPath
                    } catch {
                        # 重定向失败 (文件被占用等) · 退回无重定向
                        $petProc = Start-Process -FilePath $petPython -ArgumentList ('"' + $petScript + '"') -WorkingDirectory $script:Root -PassThru -WindowStyle Hidden
                    }
                    # 桌宠崩得快 (缺 PyQt6 等)·等 1.8s 看它还在不在·别一拿到 process 就报"起来了"
                    Start-Sleep -Milliseconds 1800
                    if ($petProc -and -not $petProc.HasExited) {
                        Add-Log "桌宠起来了 (pid=$($petProc.Id)) · 在屏幕右下角" 'ok'
                    } elseif ($petProc -and $petProc.HasExited) {
                        Add-Log "桌宠起了又退了 (exit=$($petProc.ExitCode)) · 真实错误见 _pet.err · 多半缺依赖去『环境』页补装" 'err'
                    } else {
                        Add-Log '桌宠没返回 process · 可能没起' 'warn'
                    }
                }
            } catch { Add-Log "起桌宠失败: $_" 'err' }
        }
    } else { Add-Log '桌宠未勾选 · 跳过' 'warn' }

    # 3) 开浏览器
    if ($chkBrowser.Checked -and $daemonStarted) {
        $url = "http://127.0.0.1:$port/ui"
        Add-Log "打开浏览器: $url · 在网页里和它相遇 (第一次会让你填 key)" 'info'
        try { Start-Process $url } catch { Add-Log "开浏览器失败: $_" 'warn' }
    }

    if (-not (Get-OpusToken)) {
        Add-Log '提示: .env 没 WebUI 访问口令 · 去『环境』页生成口令' 'warn'
    }

    Add-Log '全部完成 · daemon 在后台运行' 'ok'
    # 2026-08-15 · 启动成功后自动收托盘 (守护模式: WEBUI 弹出后窗口退居托盘 · 不再占任务栏)
    if ($daemonStarted -and $script:trayIcon) {
        $form.Hide()
        $script:trayIcon.Visible = $true
        $script:trayIcon.Text = 'Daemonkey 守护 · 运行中'
        Add-Log 'daemon 已启动 · 窗口收进托盘 (双击托盘图标可呼出)' 'ok'
        Add-GuardEvent '启动完成 · 已转入托盘 (双击 exe 的壳已隐藏)' 'ok'
    }
    if ($daemonStarted) {
        # 0.8.3 · 启动成功 → 按钮变「关闭进程」(点击可停 daemon)
        $script:DaemonRunning = $true
        $btnStart.Text = '关闭进程'
        Set-ButtonFill $btnStart $cOk
    } else {
        $btnStart.Text = $script:StartText
        Set-ButtonFill $btnStart $cBtn
    }
    $btnStart.Enabled = $true
})

# ───── 首次使用检测 ─────
function Test-NeedSetup {
    # 2026-08-02 · 双条件判定 (防半成品 venv): python.exe + pyvenv.cfg 都在才算装好
    if (-not (Test-Path $script:VenvPython)) { return $true }
    if (-not (Test-Path (Join-Path $script:Root '.venv\pyvenv.cfg'))) { return $true }
    # 2026-08-15 · 第三条件 (防"假就绪"): 依赖必须真能 import。
    #   事故: 095test 的 .venv 复制损坏 (anthropic 缺 types/beta/sessions)·
    #   python.exe + pyvenv.cfg 都在 → 旧逻辑判定"已装" → 不自动重装 →
    #   点启动也起不来 → 看起来"自动一条龙失效"。实测 import 兜住。
    & $script:VenvPython -c "import fastapi, uvicorn, openai, anthropic" 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { return $true }
    return $false
}

# ───── 收尾 ─────
# 2026-08-02 · 首次自动流程 (BRO 拍板): 环境未装 → 自动安装 → 装完自动启动 daemon + WebUI
# 之后打开 (环境已装) → 直接启动页点【开始启动】· 不再手动两步走
# 2026-08-02 修: 成功判定以【环境就绪】为准 (exit code 读取可能为空/未同步·不可靠)
$needSetup = Test-NeedSetup
if ($needSetup) {
    $onboardBanner.Visible = $true
    Show-Page 'setup'
    Term-Write '✅ 检测到首次使用 · 已自动开始安装运行环境 (约 1-2 分钟 · 无需点任何按钮)…' $cOk
    Add-Log '首次使用 · 自动安装运行环境 (run.ps1 -NoLaunch) · 装完自动启动…' 'info'
    $runPs1 = Join-Path $script:Root 'run.ps1'
    Term-Run 'powershell.exe' "-NoProfile -ExecutionPolicy Bypass -File `"$runPs1`" -NoLaunch" -OnExit {
        param($code)
        $ready = $false
        for ($i = 0; $i -lt 3; $i++) {
            Start-Sleep -Milliseconds 1500      # venv 刚建好 · 首次 import 可能慢/锁 · 等 1.5s 重试
            if (-not (Test-NeedSetup)) { $ready = $true; break }
        }
        Add-Log "安装回调 · exit=$code · 环境就绪=$ready" 'warn'
        if ($ready) {
            Add-Log '环境就绪 · 自动启动 daemon + WebUI…' 'ok'
            Show-Page 'launch'
            # $btnStart 是自绘 Panel (New-ActionButton) · 没有 PerformClick · 用反射触发 OnClick
            # (2026-08-02 · BRO 实测: PerformClick 报 Panel 无此方法)
            try {
                $m = $btnStart.GetType().GetMethod('OnClick', [System.Reflection.BindingFlags]'Instance,NonPublic')
                if ($m) { $m.Invoke($btnStart, @([System.EventArgs]::Empty)) }
                else { Add-Log '找不到 OnClick 方法 · 请手动点【启动】' 'err' }
            } catch {
                Add-Log "自动触发启动失败: $_ · 请手动点【启动】" 'err'
            }
        } else {
            Add-Log "环境安装未完成 (exit=$code) · 看右栏输出 · 可再点【开始安装】重试或去『急救』" 'err'
            Show-Page 'launch'   # 2026-08-15 · 不留环境页 · 回启动页让用户看日志
            Term-Write "环境未完全就绪 · 去『环境』页点【开始安装】或看右栏输出。" $cWarn
        }
    }
} else {
    Show-Page 'launch'
    Term-Write '就绪 · 左侧选页 · 命令输出会显示在这里。' $cAccent
}

# ───── 0.8.3 · 启动时静默检查 Gitee 新版本 (只读 · 失败静默 · 不阻塞 UI) ─────
# 中心库 = 官方 Gitee 仓库 (vaan21th/dae-monkey) · 拉 raw core_manifest.json 秒回 · 无 git 依赖
# 跨线程通信 = 后台 Runspace 写 runtime 文件 · UI Timer 轮询读
#   (PS 5.1 坑: scriptblock 转 Task/Thread 委托的线程没有 Runspace → cmdlet 抛
#    PSInvalidOperationException · 必须显式建 Runspace)
$script:UpdateTmpFile = Join-Path $script:Root 'data\runtime\remote_version_check.json'
try {
    $updateRS = [runspacefactory]::CreateRunspace()
    $updateRS.Open()
    $updatePS = [powershell]::Create()
    $updatePS.Runspace = $updateRS
    [void]$updatePS.AddScript({
        param($url, $tmp)
        try {
            $raw = Invoke-RestMethod -Uri $url -TimeoutSec 6 -ErrorAction Stop
            @{ remote = [string]$raw.core_version; checked_at = (Get-Date -Format 's') } |
                ConvertTo-Json | Set-Content $tmp -Encoding UTF8
        } catch { }
    })
    [void]$updatePS.AddParameter('url', 'https://gitee.com/vaan21th/dae-monkey/raw/master/core_manifest.json')
    [void]$updatePS.AddParameter('tmp', $script:UpdateTmpFile)
    [void]$updatePS.BeginInvoke()
} catch { }
# UI 轮询 · 文件出现即比对显示 (最多 ~10s · 无结果静默隐藏)
$updateTimer = New-Object System.Windows.Forms.Timer
$updateTimer.Interval = 500
$updateTimer.Add_Tick({
    if (Test-Path $script:UpdateTmpFile) {
        $updateTimer.Stop()
        try {
            $j = Get-Content $script:UpdateTmpFile -Raw | ConvertFrom-Json
            $rv = [string]$j.remote
            $lv = [string]$script:Version -replace '^v', ''
            if ($rv -and $lv -and (Test-NewerVersion -local $lv -remote $rv)) {
                $lblUpdate.Text = "发现新版本 v$rv · 查看更新"
                $lblUpdate.Visible = $true
            }
        } catch { }
        Remove-Item $script:UpdateTmpFile -Force -ErrorAction SilentlyContinue
        try { $updatePS.Dispose(); $updateRS.Close(); $updateRS.Dispose() } catch { }
    }
})
$updateTimer.Start()

# ── wish-32691f0e · 运行监控轮询 (2s · UI 主线程 Timer · 失败静默不打断 UI) ──
$monitorTimer = New-Object System.Windows.Forms.Timer
$monitorTimer.Interval = 2000
$monitorTimer.Add_Tick({ try { Update-MonitorPanel } catch {}; Push-MainBtnState })
$monitorTimer.Start()

# ── wish-1b8e141b · 崩溃自动拉起看门狗 (10s 轮询 · 判定: stopped 持续 90s + 无 pending restart_request) ──
$autoRestartTimer = New-Object System.Windows.Forms.Timer
$autoRestartTimer.Interval = 10000
$autoRestartTimer.Add_Tick({ try { Watch-AutoRestart } catch {} })
# 启动时恢复上次状态 (launcher 重启后开关仍记得)
try {
    $ar = Load-AutoRestartState
    if ($ar -and $ar.enabled) { $chkAutoRestart.Checked = $true }
    if ($ar -and $ar.circuitUntil) {
        try { $script:CircuitUntil = [datetime]::Parse($ar.circuitUntil) } catch {}
    }
} catch { }
# 0.9.4+ · 启动器打开时检测 daemon 是否已在跑 → 按钮状态与现状一致
# (服务在跑时重开启动器 · 按钮直接显示「关闭进程」· 不误走"启动"流程)
try {
    $port0 = 7860
    try { $port0 = [int]$txtPort.Text } catch {}
    if (Test-DaemonAlive -Port $port0) {
        $script:DaemonRunning = $true
        $btnStart.Text = '关闭进程'
        Set-ButtonFill $btnStart $cOk
        Add-Log "检测到 daemon 已在跑 (port=$port0) · 按钮为「关闭进程」" 'ok'
    }
} catch {}
$autoRestartTimer.Start()
[System.Windows.Forms.Application]::EnableVisualStyles()
if ($env:DK_PREVIEW_GUARD -eq '1') {
    try {
        if (-not $script:guardForm) { New-GuardPanel | Out-Null }
        $script:guardForm.Show()
        $script:guardForm.BringToFront()
        Update-GuardPanel
    } catch { try { Set-Content (Join-Path $script:Root '_guard_preview_err.txt') "面板预览失败: $_" -Encoding UTF8 } catch {} }
}
if ($env:DK_PREVIEW_GUARD -eq '1') {
    try {
        if (-not $script:guardForm) { New-GuardPanel | Out-Null }
        $script:guardForm.Show()
        Update-GuardPanel
    } catch { try { Set-Content (Join-Path $script:Root '_guard_preview_err.txt') "面板预览失败: $_" -Encoding UTF8 } catch {} }
}
# 2026-08-15 · ShowDialog(模态) → Application.Run(非模态): 托盘应用标准模式
#   模态窗 Hide 后再 Show() 有边界问题 (托盘双击呼出可能不显示) · Run 模式无此问题
# 防 GC 终极保险: 消息循环期间 KeepAlive 所有托盘对象 (PowerShell 分代 GC 在循环空闲时会回收)
[GC]::KeepAlive($script:trayIcon)
[GC]::KeepAlive($script:trayMenu)
[GC]::KeepAlive($script:trayIcoObj)
[GC]::KeepAlive($script:trayMenuItems)

# ═══════════════════════════════════════════════════════════════════
# 2026-08-15 · 主界面 HTML 化 (覆盖式 Overlay · 月光操作台)
#   GDI 三栏全量保留作兜底 · WebView2 盖层成功则 Dock=Fill 覆盖 $form
#   用户操作 postMessage → 回写真实 GDI 控件 · 启动链路零感知
#   Mac 双端: 同一份 assets/launcher.html · Mac 侧 pywebview 复用桥接协议
# ═══════════════════════════════════════════════════════════════════
$script:mainWv = $null
$script:mainLastTermPush = [datetime]::MinValue
$script:mainLastBtnSig = ''

function Push-Main {
    param($obj)
    try {
        if ($script:mainWv -and $script:mainWv.CoreWebView2) {
            $script:mainWv.CoreWebView2.PostWebMessageAsJson(($obj | ConvertTo-Json -Compress -Depth 6))
        }
    } catch {}
}

function Push-MainState {
    # 社群二维码 + ID (HTML 端 qrBox/commId · 与 GDI 关于页同源)
    $commFile = Join-Path $script:Root 'assets\community.txt'
    # 2026-08-15 · [object Object] 根因: Get-Content 字符串带 PSObject 包装(PSPath等) · ConvertTo-Json 序列化整个对象
    #                → [string] 强转去包装 (纯字符串 · JS 端 textContent 正常)
    $commIdTxt = ''
    if (Test-Path $commFile) { $commIdTxt = [string]((Get-Content $commFile -TotalCount 1) -join ' ') }
    if ([string]::IsNullOrWhiteSpace($commIdTxt)) { $commIdTxt = 'WeChat / 社群: 把号或链接写到 assets\community.txt' }
    $commIdTxt = $commIdTxt.Trim()
    $qrFileM = Join-Path $script:Root 'assets\community-qr.png'
    $qrDataUri = $null
    if (Test-Path $qrFileM) {
        try {
            $b64 = [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($qrFileM))
            $qrDataUri = "data:image/png;base64,$b64"
        } catch {}
    }
    Push-Main @{
        type = 'state'
        ver = "$script:Version"
        nav = $script:CurrentPage   # 2026-08-15 · 初始化补推带当前页 · 否则 needSetup 时 Show-Page 推送在 mainWv 创建前丢失 → HTML 永远停启动页
        needSetup = (Test-NeedSetup)   # 2026-08-15 · HTML 环境页显示"自动安装中"横幅
        opts = @{
            daemon  = [bool]$chkDaemon.Checked
            pet     = [bool]$chkPet.Checked
            browser = [bool]$chkBrowser.Checked
            crash   = [bool]$chkAutoRestart.Checked
        }
        port = [string]$txtPort.Text
        btn = @{ text = [string]$btnStart.Text; enabled = [bool]$btnStart.Enabled }
        onboard = [bool]$onboardBanner.Visible
        status = '守护中 · daemon 运行正常'
        statusKind = 'run'
        commId = $commIdTxt
        qrDataUri = $qrDataUri
        qrHint = if ($qrDataUri) { '微信扫码进社群' } else { '把社群二维码放到 assets\community-qr.png · 这里自动显示' }
    }
}

function Push-MainBtnState {
    try {
        $sig = "$($btnStart.Text)|$($btnStart.Enabled)"
        if ($sig -ne $script:mainLastBtnSig) {
            $script:mainLastBtnSig = $sig
            Push-Main @{ type = 'btn'; btn = @{ text = [string]$btnStart.Text; enabled = [bool]$btnStart.Enabled } }
        }
    } catch {}
}

function Invoke-GdiButton {
    param($btn)
    try {
        if ($null -eq $btn) { return }
        $m = $btn.GetType().GetMethod('OnClick', [System.Reflection.BindingFlags]'Instance,NonPublic')
        if ($m) { $m.Invoke($btn, @([System.EventArgs]::Empty)) }
        else { Add-Log '按钮无 OnClick 方法' 'err' }
    } catch { Add-Log "按钮触发失败: $_" 'err' }
}

$script:MainProviders = @(
    @{ id = 'api-0'; url = 'https://platform.deepseek.com/' },
    @{ id = 'api-1'; url = 'https://open.bigmodel.cn/' },
    @{ id = 'api-2'; url = 'https://platform.moonshot.cn/' },
    @{ id = 'api-3'; url = 'https://bailian.console.aliyun.com/' },
    @{ id = 'api-4'; url = 'https://www.anthropic.com/api' },
    @{ id = 'api-5'; url = 'https://openrouter.ai/' },
    @{ id = 'api-6'; url = 'https://aihubmix.com/' },
    @{ id = 'api-7'; url = 'https://aistudio.google.com/' }
)

function New-MainWebView {
    try {
        if (-not ('Microsoft.Web.WebView2.WinForms.WebView2' -as [type])) {
            Add-Type -Path "$script:Root\assets\webview2\Microsoft.Web.WebView2.Core.dll" -ErrorAction Stop
            Add-Type -Path "$script:Root\assets\webview2\Microsoft.Web.WebView2.WinForms.dll" -ErrorAction Stop
        }
    } catch { Add-Log 'WebView2 dll 缺失 · 使用 GDI 界面' 'warn'; return $null }

    $wv = New-Object Microsoft.Web.WebView2.WinForms.WebView2
    $wv.Dock = 'Fill'
    $wv.DefaultBackgroundColor = [System.Drawing.Color]::FromArgb(10, 13, 24)
    try { $wv.CornerRadius = 12 } catch {}
    # 1080P/2K/4K 适配: 高 DPI 下 CSS px 自动放大 → 内容溢出 · ZoomFactor = 96/Dpi 按物理像素精确渲染
    try {
        $g = [System.Drawing.Graphics]::FromHwnd($form.Handle)
        if ($g.DpiX -gt 96) { $wv.ZoomFactor = [double](96.0 / $g.DpiX) }
        $g.Dispose()
    } catch {}
    try {
        $udf = Join-Path $script:Root 'data\runtime\webview2_main'
        try { New-Item -ItemType Directory -Path $udf -Force | Out-Null } catch {}
        $wv.CreationProperties = New-Object Microsoft.Web.WebView2.WinForms.CoreWebView2CreationProperties
        $wv.CreationProperties.UserDataFolder = $udf
        $wv.CreationProperties.AdditionalBrowserArguments = '--disable-features=CalculateNativeWinOcclusion,msWebOOUI,msPdfOOUI'
    } catch {}
    $form.Controls.Add($wv)

    try {
        $task = $wv.EnsureCoreWebView2Async($null)
        $deadline = (Get-Date).AddSeconds(5)
        while (-not $wv.CoreWebView2 -and (Get-Date) -lt $deadline) {
            [System.Windows.Forms.Application]::DoEvents()
            Start-Sleep -Milliseconds 100
            if ($task.IsFaulted) { break }
        }
        if (-not $wv.CoreWebView2) {
            $form.Controls.Remove($wv); $wv.Dispose()
            Add-Log '主界面 WebView2 初始化超时 · 使用 GDI 界面' 'warn'
            return $null
        }
    } catch {
        $form.Controls.Remove($wv); try { $wv.Dispose() } catch {}
        Add-Log "主界面 WebView2 初始化失败: $_ · 使用 GDI 界面" 'warn'
        return $null
    }

    $wv.CoreWebView2.Settings.AreDefaultContextMenusEnabled = $false
    $wv.CoreWebView2.Settings.IsStatusBarEnabled = $false
    $wv.CoreWebView2.Settings.IsZoomControlEnabled = $false
    $wv.CoreWebView2.Settings.AreBrowserAcceleratorKeysEnabled = $false

    # HTML → PS 桥接
    $wv.CoreWebView2.Add_WebMessageReceived({
        param($sender, $e)
        try {
            $msg = $e.WebMessageAsJson | ConvertFrom-Json
            switch ($msg.type) {
                'start' { Invoke-GdiButton $btnStart }
                'nav' {
                    # GDI 兜底只有六页 · 社群页 HTML 自渲染 · PS 侧映射到 about 防白屏
                    if ([string]$msg.page -eq 'community') { Show-Page 'about' } else { Show-Page ([string]$msg.page) }
                }
                'opt' {
                    switch ([string]$msg.key) {
                        'daemon'  { $chkDaemon.Checked  = [bool]$msg.on }
                        'pet'     { $chkPet.Checked     = [bool]$msg.on }
                        'browser' { $chkBrowser.Checked = [bool]$msg.on }
                        'crash' {
                            $chkAutoRestart.Checked = [bool]$msg.on
                            try { Save-AutoRestartState } catch {}
                            Add-Log "崩溃自动拉起: $(if ($msg.on) { '开' } else { '关' })" 'info'
                        }
                    }
                }
                'port' {
                    $p = [string]$msg.text
                    if ($p -match '^\d{2,5}$') { $txtPort.Text = $p }
                }
                'action' {
                    switch ([string]$msg.id) {
                        'setup-env'        { Invoke-GdiButton $btnEnv }
                        'setup-token'      { Invoke-GdiButton $btnTok }
                        'setup-env-file'   { Invoke-GdiButton $btnKey }
                        'rescue-repair'    { Invoke-GdiButton $btnRepair }
                        'rescue-rollback'  { Invoke-GdiButton $btnRoll }
                        'ext-check-update' { Invoke-GdiButton $btnPatch }
                    }
                }
                'openurl' {
                    $id = [string]$msg.id
                    $url = $null
                    foreach ($pr in $script:MainProviders) { if ($pr.id -eq $id) { $url = $pr.url; break } }
                    if ($id -eq 'bili') { $url = $script:BiliUrl }
                    elseif ($id -eq 'douyin') { $url = $script:DouyinUrl }
                    if ($url) { Open-Url $url }
                }
                'min' { $form.WindowState = [System.Windows.Forms.FormWindowState]::Minimized }
                'drag' {
                    try {
                        $dx = [int]$msg.dx; $dy = [int]$msg.dy
                        $form.Location = New-Object System.Drawing.Point(($form.Location.X + $dx), ($form.Location.Y + $dy))
                    } catch {}
                }
                'close' { $form.Hide() }
                'term-stop' {
                    if ($script:termProc -and -not $script:termProc.HasExited) {
                        try { $script:termProc.Kill(); Term-Write '[已停止当前命令]' $cWarn } catch {}
                    }
                }
                'term-clear' { $script:Terminal.Clear() }
            }
        } catch {}
    })

    # 导航 HTML (NavigateToString 绕 file:// 缓存)
    $htmlPath = Join-Path $script:Root 'assets\launcher.html'
    try {
        $htmlContent = Get-Content $htmlPath -Raw -Encoding UTF8
        if (-not $htmlContent) { throw 'HTML 为空' }
        $wv.CoreWebView2.NavigateToString($htmlContent)
    } catch {
        $form.Controls.Remove($wv); try { $wv.Dispose() } catch {}
        Add-Log "launcher.html 读取失败: $_ · 使用 GDI 界面" 'warn'
        return $null
    }

    $wv.CoreWebView2.Add_NavigationCompleted({
        param($sender, $e)
        if ($e.IsSuccess) {
            try { $script:mainWv.BringToFront() } catch {}
            Push-MainState
            Add-Log '月光操作台界面已加载' 'ok'
        }
        # 闪屏修复: WebView2 加载完成 → 显示窗口 (GDI 旧界面永远不会被用户看到)
        try { $form.Opacity = 1 } catch {}
        try { if ($script:MainFadeTimer) { $script:MainFadeTimer.Stop(); $script:MainFadeTimer.Dispose(); $script:MainFadeTimer = $null } } catch {}
        # 启动画面: 主界面已显示 → 关 Splash
        try { if ($script:splash) { $script:splash.Close() } } catch {}
    })

    $script:mainWv = $wv
    return $wv
}

# ═══════════════════════════════════════════════════
#  启动器自更新 · 启动后 8s 后台检查 gitee 新版 ps1 → 备份 → 覆盖 (下次双击 exe 生效)
# ═══════════════════════════════════════════════════
function Check-LauncherUpdate {
    if (Test-NeedSetup) { return }   # 2026-08-15 · 首装(环境未装)跳过 · 用户在装环境不该被更新检查打扰
    try {
        $localVer = $script:Version
        $mf = Join-Path $script:Root 'core_manifest.json'
        if (-not (Test-Path $mf)) { return }
        $manifest = Get-Content $mf -Raw -Encoding UTF8 | ConvertFrom-Json
        $giteeUrl = [string]$manifest.sources.remotes.gitee
        if (-not $giteeUrl) { return }
        $rawBase = ($giteeUrl -replace '\.git$', '') -replace '^https://gitee\.com/', 'https://gitee.com/'
        if ($rawBase -notmatch 'gitee\.com') { return }
        # 2026-08-15 · gitee 直连 (绕开系统代理 · Clash 死端口同坑 8/11 雷达/飞书)
        $oldProxy = [System.Net.WebRequest]::DefaultWebProxy
        [System.Net.WebRequest]::DefaultWebProxy = $null
        try {
            $resp = Invoke-WebRequest -Uri "$rawBase/raw/master/core_manifest.json" -UseBasicParsing -TimeoutSec 8 -ErrorAction Stop
        } finally { [System.Net.WebRequest]::DefaultWebProxy = $oldProxy }
        $remoteVer = [string]((($resp.Content | ConvertFrom-Json).core_version) -replace '^v', '')
        if (-not $remoteVer) { return }
        $remoteVer = "v$remoteVer"
        if ($remoteVer -eq $localVer) { return }   # 2026-08-15 · 已最新静默 · 不刷屏
        Add-Log "发现启动器新版: $localVer → $remoteVer · 下载中…" 'warn'
        $oldProxy2 = [System.Net.WebRequest]::DefaultWebProxy
        [System.Net.WebRequest]::DefaultWebProxy = $null
        try {
            $resp2 = Invoke-WebRequest -Uri "$rawBase/raw/master/daemonkey-launcher.ps1" -UseBasicParsing -TimeoutSec 15 -ErrorAction Stop
        } finally { [System.Net.WebRequest]::DefaultWebProxy = $oldProxy2 }
        $newPs1 = $resp2.Content
        if ($newPs1.Length -lt 50000) { return }   # 2026-08-15 · 下载异常静默跳过
        $curPs1 = Join-Path $script:Root 'daemonkey-launcher.ps1'
        $backupDir = Join-Path $script:Root 'data\runtime\launcher_backup'
        if (-not (Test-Path $backupDir)) { New-Item -ItemType Directory -Path $backupDir -Force | Out-Null }
        Copy-Item $curPs1 (Join-Path $backupDir "daemonkey-launcher.ps1.$localVer.bak") -Force
        $enc = New-Object System.Text.UTF8Encoding($true)   # 带 BOM · PS5.1 中文注释不乱码
        [System.IO.File]::WriteAllText($curPs1, $newPs1, $enc)
        Add-Log "启动器已更新 $localVer → $remoteVer · 重启启动器生效 (旧版备份在 data\runtime\launcher_backup)" 'ok'
    } catch { }   # 2026-08-15 · 失败完全静默 (代理未开/网络不可达常见) · 不打扰用户 · 有新版才提示
}

# 启动后 8s 后台跑一次 · 不阻塞启动
$script:updTimer = New-Object System.Windows.Forms.Timer
$script:updTimer.Interval = 8000
$script:updTimer.Add_Tick({
    try { $script:updTimer.Stop(); $script:updTimer.Dispose(); $script:updTimer = $null } catch {}
    Check-LauncherUpdate
})
$script:updTimer.Start()

# ── Activation · 覆盖式 Overlay: 窗口先隐藏 (Opacity=0) · WebView2 盖层完成后显示 · 4s 兑底 ──
# 2026-08-15 · 卡顿修复: 原 Application.Run 前同步初始化 WebView2 (8s 死等 → 窗口"不响应")
# 2026-08-15 · 闪屏修复: Shown 后 Opacity=0 隐藏窗口 → WebView2 NavigationCompleted → Opacity=1
#                (用户永远看不到 GDI 旧三栏 · 4s 兑底: WebView2 失败/超时也强制显示 GDI 兜底)
$form.Add_Shown({
    try { $form.Opacity = 0 } catch {}
    try {
        $script:MainFadeTimer = New-Object System.Windows.Forms.Timer
        $script:MainFadeTimer.Interval = 4000
        $script:MainFadeTimer.Add_Tick({
            try { $form.Opacity = 1 } catch {}
            try { if ($script:splash) { $script:splash.Close() } } catch {}
            try { $script:MainFadeTimer.Stop(); $script:MainFadeTimer.Dispose(); $script:MainFadeTimer = $null } catch {}
        })
        $script:MainFadeTimer.Start()
    } catch {}
    try { $script:mainWv = New-MainWebView } catch { Add-Log "主界面 WebView2 异常: $_" 'warn' }
})
[System.Windows.Forms.Application]::Run($form)
