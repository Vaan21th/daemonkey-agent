#!/usr/bin/env pwsh
# 紧急回档 · daemon UI 完全打不开时用这个
#
# 用途:
#   AI 改坏了代码 · WebUI 加载不出来 · 没法用 UI 上的"回档"按钮
#   这时双击 → 这个脚本帮你:
#     0. 前置检查 git 可用 + 是 git 仓库 (没有 → 如实说明 + 引导改用维修台 · 绝不瞎跑/谎报)
#     1. 停止当前 daemon
#     2. git stash 保留任何未提交改动 (不丢东西)
#     3. git checkout master (回到上次良好状态)
#     4. 重启 daemon · 起不来则自动回 opus-last-good 再试一次 (last-good 兜底)
#     5. 弹窗如实告知状态 (绝不谎报)
#
# de-mother: 弹窗/日志里"它"的名字运行时从 soul/IDENTITY.json 读 · 缺省 OPUS (母体行为零变化)。
# 本文件已纳入内核白名单 (core_manifest.json) · 修复随 update_core 同步给所有用户。
#
# 怎么造快捷方式:
#   右键桌面 → 新建 → 快捷方式
#   位置: powershell -ExecutionPolicy Bypass -File <项目根目录>\tools\rollback_emergency.ps1

$ErrorActionPreference = "Continue"
# 开源就绪 · 不硬编码盘符 · 本脚本在 tools/ 下 · 工程根是上一级目录
$ROOT = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LOG = Join-Path $ROOT "data\rollback.log"

# ── 实例名 (de-mother · 运行时读 · 缺省 OPUS = 母体不变) ──
$AINAME = "OPUS"
$idf = Join-Path $ROOT "soul\IDENTITY.json"
if (Test-Path $idf) {
    try {
        $idj = Get-Content $idf -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($idj.name) { $AINAME = [string]$idj.name }
    } catch {}
}

function Log {
    param([string]$msg)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts  $msg" | Out-File -FilePath $LOG -Append -Encoding utf8
    Write-Host "$ts  $msg"
}

function Show-Box {
    param([string]$msg, [string]$title, [string]$icon)
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show($msg, $title, "OK", $icon) | Out-Null
}

cd $ROOT
Log "=== 紧急回档开始 ==="

# ── Step 0 · 前置检查 (图1根因: 没 git 别瞎跑 · 别谎报) ──
$gitcmd = Get-Command git -ErrorAction SilentlyContinue
if (-not $gitcmd) {
    Log "ERROR: 没检测到 git · 回档依赖 git · 中止 (不谎报)"
    Show-Box (
        "没法回档：这台电脑没装 git（或 git 没加进系统 PATH）。`n`n" +
        "回档功能依赖 git。先装 git：`nhttps://git-scm.com/download/win`n装好后重启电脑再试。`n`n" +
        "想直接修好崩溃？改用【应急维修台】(repair.bat)——它不需要 git，能直连 AI 自己查自己修。"
    ) "$AINAME 紧急回档 · 没法进行" "Warning"
    exit 2
}
if (-not (Test-Path (Join-Path $ROOT ".git"))) {
    Log "ERROR: 不是 git 仓库 (没有 .git) · 回档不可用 · 中止 (不谎报)"
    Show-Box (
        "没法回档：这个目录还没启用版本控制（不是 git 仓库），没有历史版本可回退。`n`n" +
        "想直接修好崩溃？改用【应急维修台】(repair.bat)——它不需要 git。`n`n" +
        "想以后能回档？装好 git 后，下次启动会自动建立版本控制。"
    ) "$AINAME 紧急回档 · 没法进行" "Warning"
    exit 2
}

# Step 1 · 看当前在哪个分支
$cur_branch = (git rev-parse --abbrev-ref HEAD 2>$null).Trim()
Log "当前分支: $cur_branch"

# Step 2 · stash 任何未提交改动 (不丢东西 · 无论在哪个分支只要脏就 stash · 止血关键)
$dirty = (git status --porcelain 2>$null).Trim()
if ($dirty) {
    Log "working tree 有未提交改动 · 先 stash (止血关键)"
    $stash_msg = "rollback_emergency at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    git stash push -m $stash_msg --include-untracked 2>&1 | ForEach-Object { Log "  $_" }
} else {
    Log "working tree 干净 · 无需 stash"
}

# Step 3 · 切到 master
if ($cur_branch -eq "master") {
    Log "已经在 master · 工作区已清"
} else {
    Log "git checkout master ..."
    git checkout master 2>&1 | ForEach-Object { Log "  $_" }
}

# Step 3.5 · 清掉 pending restart_request (防自动续场把刚回退掉的坏改动又拉回来)
$runtime = Join-Path $ROOT "data\runtime"
$rr = Join-Path $runtime "restart_request.json"
if (Test-Path $rr) {
    $quar = Join-Path $runtime "restart_request.quarantined.json"
    Log "隔离 pending restart_request (防自动续场)"
    Move-Item -Path $rr -Destination $quar -Force -ErrorAction SilentlyContinue
}

# Step 3.6 · 记下 known-good 恢复点 (回 master 起不来时的兜底目标)
$lastGood = (git rev-parse --verify --short opus-last-good 2>$null)
$haveLastGood = ($LASTEXITCODE -eq 0 -and $lastGood)
if ($haveLastGood) {
    Log "known-good 恢复点: opus-last-good = $($lastGood.Trim())"
} else {
    Log "没有 opus-last-good tag (还没优雅停机过) · 仅按 master HEAD 恢复"
}

# ── 停 / 启 daemon 的可复用函数 ──
function Stop-Daemon {
    $pids = Get-Process python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id
    foreach ($p in $pids) { Log "  stop pid $p"; Stop-Process -Id $p -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}
function Start-Daemon {
    $env:PYTHONIOENCODING = "utf-8"
    $py = Join-Path $ROOT ".venv\Scripts\python.exe"
    if (-not (Test-Path $py)) { $py = "python" }
    $p = Start-Process -FilePath $py `
        -ArgumentList "-u", "tools\run_api_only.py" `
        -RedirectStandardOutput "data\daemon.out" -RedirectStandardError "data\daemon.err" `
        -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 6
    return $p
}

# Step 4 · 停 daemon
Log "停止 python 进程 (daemon)"
Stop-Daemon

# Step 5 · 重启 (master baseline)
Log "启动 daemon (master baseline)"
$proc = Start-Daemon

# Step 5.5 · master 起不来 + 有 known-good → 自动回 opus-last-good 再试一次 (last-good 兜底)
$usedLastGood = $false
if ($proc.HasExited -and $haveLastGood) {
    Log "master HEAD 起不来 · 自动回 known-good (git reset --hard opus-last-good) 再试"
    git reset --hard opus-last-good 2>&1 | ForEach-Object { Log "  $_" }
    $usedLastGood = $true
    Stop-Daemon
    $proc = Start-Daemon
    if (-not $proc.HasExited) { Log "回 known-good 后 daemon 起来了 · pid=$($proc.Id)" }
}

# Step 6 · 结果如实弹窗 (绝不谎报)
$scope = if ($usedLastGood) { "已切回 master 并回退到上次正常版本" } else { "已切回 master" }
if ($proc.HasExited) {
    Log "ERROR: 回档后 daemon 仍启动失败 · 看 data/daemon.err"
    Show-Box (
        "已尝试回档（$scope），但 daemon 还是没起来。`n`n" +
        "这通常不是代码版本问题，而是环境/依赖坏了。`n" +
        "建议改用【应急维修台】(repair.bat) 直连 AI 排查，或看：`n$ROOT\data\daemon.err"
    ) "$AINAME 紧急回档 · 仍未恢复" "Error"
    exit 1
}

# 验证 UI 能拉
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:7860/ui" -TimeoutSec 5 -UseBasicParsing
    if ($r.StatusCode -eq 200 -and $r.Content.Length -gt 5000) {
        Log "/ui 正常 · length=$($r.Content.Length)"
    } else {
        Log "/ui 异常 · status=$($r.StatusCode) length=$($r.Content.Length)"
    }
} catch {
    Log "/ui 测试失败: $($_.Exception.Message)"
}

Log "=== 紧急回档完成 · daemon pid=$($proc.Id) ==="
Show-Box (
    "回档成功（$scope）· daemon 已重启 (pid $($proc.Id))。`n`n" +
    "去浏览器按 Ctrl+Shift+R 强刷：`nhttp://127.0.0.1:7860/ui`n`n" +
    "未提交改动已 stash · 用 git stash list 可找回 · 不会丢"
) "$AINAME 紧急回档 · 成功" "Information"
