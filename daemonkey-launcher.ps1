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

Ensure-RepoAndSource

# ═══════════════════════════════════════════════════
#  主窗口 · 无边框圆角 + 自绘标题栏 + 三栏
# ═══════════════════════════════════════════════════
$form = New-Object System.Windows.Forms.Form
$form.Text = 'Daemonkey'
# 锁死像素 · 不随 ps2exe 宿主字体/DPI 自动缩放 (否则编译成 exe 后窗口会被缩小)
$form.AutoScaleMode = [System.Windows.Forms.AutoScaleMode]::None
$form.ClientSize = Sz 1000 620
# 钉死最小/最大尺寸 = 不可缩放 · 防止 ps2exe 冷启动期间先弹一个小窗 (Min/Max 由 WinForms 强制 · 与设置时机无关)
$form.MinimumSize = Sz 1000 620
$form.MaximumSize = Sz 1000 620
$form.StartPosition = 'CenterScreen'
$form.BackColor = $cBg
$form.ForeColor = $cText
$form.Font = F 9
$form.FormBorderStyle = 'None'
$form.MaximizeBox = $false
# 任务栏 / Alt-Tab 图标 (窗口图标和 exe 文件图标都对齐到同一个 .ico)
$icoFile = Join-Path $script:Root 'assets\daemonkey.ico'
if (Test-Path $icoFile) { try { $form.Icon = New-Object System.Drawing.Icon($icoFile) } catch {} }
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
$btnMin.Add_Click({ $form.WindowState = [System.Windows.Forms.FormWindowState]::Minimized })
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
}

$script:termProc = $null
$script:termReaderOut = $null
$script:termReaderErr = $null

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
        $code = $script:termProc.ExitCode
        $script:termTimer.Stop()
        if ($script:termReaderOut) { $script:termReaderOut.Close(); $script:termReaderOut = $null }
        if ($script:termReaderErr) { $script:termReaderErr.Close(); $script:termReaderErr = $null }
        $script:termProc = $null
        $btnTermStop.Enabled = $false
        Term-Write "[完成 · exit $code]" $cAccent
        $script:lblStatus.Text = '就绪'
    }
})

# 在右栏终端里跑命令 (单向输出 · 不弹黑窗)
function Term-Run {
    param([string]$exe, [string]$arguments, [string]$cwd = $script:Root)
    if ($script:termProc) { Term-Write '[!] 已有命令在跑 · 等它结束或点停止' $cWarn; return }
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
$obLabel.Text = "第一次用?先去『环境』装好运行环境 · 再回来启动。"
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
$lblFirstUse.Text = "初次使用 · 请先配置环境:`r`n点左侧『环境』→【安装/修复运行环境】· 装好启动所需的 Python 等工具。"
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
$stepLbl.Text = "首次使用 · 跟着 3 步走:`r`n① 点下面【开始安装】· 装好运行环境 (Python / 依赖)`r`n② 装完回左侧『启动』页 · 点蓝色【启动】按钮`r`n③ 启动后在 WebUI『设置』里填 API key · 即可开聊"
$stepLbl.Location = P 18 12
$stepLbl.Size = Sz 500 84
$stepLbl.Font = F 9
$stepLbl.ForeColor = $cAccent
$stepCard.Controls.Add($stepLbl)

$cardEnv = New-Card $pgSetup 24 178 532 92 '① 安装 / 修复运行环境' '建虚拟环境 (.venv) + 装依赖 · 第一次必跑 · 装坏了也点它修。 输出看右栏。'
$btnEnv = New-ActionButton $cardEnv '开始安装' 372 26 142 40 $cBtn $cText
$btnEnv.Add_Click({
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
    Start-Process notepad.exe -ArgumentList $envPath | Out-Null
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

    $port = 0
    if (-not [int]::TryParse($txtPort.Text, [ref]$port) -or $port -le 0 -or $port -gt 65535) {
        Add-Log "端口不合法: $($txtPort.Text)" 'err'
        $btnStart.Enabled = $true
        $btnStart.Text = $script:StartText
        return
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
                for ($i = 0; $i -lt 30; $i++) {
                    Start-Sleep -Milliseconds 800
                    if (Test-DaemonAlive -Port $port) { $up = $true; break }
                    [System.Windows.Forms.Application]::DoEvents()
                }
                if ($up) { Add-Log "daemon 起来了 · http://127.0.0.1:$port (pid=$($proc.Id))" 'ok'; $daemonStarted = $true }
                else { Add-Log "daemon 等了 24s 没起来 · 看 $logPath" 'err' }
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
                    $petProc = Start-Process -FilePath $petPython -ArgumentList $petScript -WorkingDirectory $script:Root -PassThru -WindowStyle Hidden
                    # 桌宠崩得快 (缺 PyQt6 等)·等 1.8s 看它还在不在·别一拿到 process 就报"起来了"
                    Start-Sleep -Milliseconds 1800
                    if ($petProc -and -not $petProc.HasExited) {
                        Add-Log "桌宠起来了 (pid=$($petProc.Id)) · 在屏幕右下角" 'ok'
                    } elseif ($petProc -and $petProc.HasExited) {
                        Add-Log "桌宠起了又退了 (exit=$($petProc.ExitCode)) · 多半缺 PyQt6 · 去『环境』页点【开始安装】补依赖" 'err'
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

    Add-Log '全部完成 · 关掉本窗口不影响后台' 'ok'
    $btnStart.Text = '✓ 启动完成 · 可关窗口'
    Set-ButtonFill $btnStart $cOk
    $btnStart.Enabled = $true
})

# ───── 首次使用检测 ─────
function Test-NeedSetup {
    if (-not (Test-Path $script:VenvPython)) { return $true }
    return $false
}

# ───── 收尾 ─────
$needSetup = Test-NeedSetup
if ($needSetup) {
    $onboardBanner.Visible = $true
    Show-Page 'setup'
    Term-Write '欢迎来到 Daemonkey · 第一次用?跟着环境页走: 装环境 → 启动 → WebUI 里填 key。' $cAccent
} else {
    Show-Page 'launch'
    Term-Write '就绪 · 左侧选页 · 命令输出会显示在这里。' $cAccent
}

[System.Windows.Forms.Application]::EnableVisualStyles()
[void]$form.ShowDialog()
