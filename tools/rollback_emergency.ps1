#!/usr/bin/env pwsh
# 紧急回档 · BRO 在 daemon UI 完全打不开时用这个
#
# 用途:
#   OPUS 改坏了代码 · WebUI 加载不出来 · BRO 无法用 UI 上的"回档"按钮
#   这时双击桌面快捷方式 → 这个脚本帮你:
#     1. 停止当前 daemon
#     2. git stash 保留任何未提交改动 (不丢东西)
#     3. git checkout master (回到上次良好状态)
#     4. 重启 daemon
#     5. 弹窗告知 BRO 状态
#
# 怎么造快捷方式:
#   右键桌面 → 新建 → 快捷方式
#   位置: powershell -ExecutionPolicy Bypass -File F:\Desktop\OPUS-DAEMON\tools\rollback_emergency.ps1
#   名字: OPUS 紧急回档

$ErrorActionPreference = "Continue"
# 卷六十三 · 开源就绪 · 不再硬编码 F:\ · 本脚本在 tools/ 下 · 工程根是上一级目录
$ROOT = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LOG = Join-Path $ROOT "data\rollback.log"

function Log {
    param([string]$msg)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts  $msg" | Out-File -FilePath $LOG -Append -Encoding utf8
    Write-Host "$ts  $msg"
}

cd $ROOT
Log "=== 紧急回档开始 ==="

# Step 1 · 看当前在哪个分支
$cur_branch = (git rev-parse --abbrev-ref HEAD 2>$null).Trim()
Log "当前分支: $cur_branch"

# Step 2 · stash 任何未提交改动 (不丢东西)
# 卷四十七 修 bug: 老版只在"不在 master"时 stash · 于是第二次回档 (已经在 master 但
#   工作区被自动续场又改坏了) 直接跳过清理 → 拿同一份坏代码重启 → 救不回来。
#   现在: 无论在哪个分支 · 只要工作区脏就先 stash 清干净 (这才是真正的止血)。
$dirty = (git status --porcelain 2>$null).Trim()
if ($dirty) {
    Log "working tree 有未提交改动 · 先 stash (无论在不在 master · 这是止血关键)"
    $stash_msg = "rollback_emergency at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    git stash push -m $stash_msg --include-untracked 2>&1 | ForEach-Object { Log "  $_" }
} else {
    Log "working tree 干净 · 无需 stash"
}

# Step 3 · 切到 master (已经在就免了)
if ($cur_branch -eq "master") {
    Log "已经在 master · 工作区已清 · 不需切分支"
} else {
    Log "git checkout master ..."
    git checkout master 2>&1 | ForEach-Object { Log "  $_" }
}

# Step 3.5 · 清掉 pending restart_request (卷四十七关键修复)
# 不清的话 · 刚重启的 daemon 会自动续场 · 把刚回退掉的坏改动又重做一遍 → 崩溃循环复发。
$runtime = Join-Path $ROOT "data\runtime"
$rr = Join-Path $runtime "restart_request.json"
if (Test-Path $rr) {
    $quar = Join-Path $runtime "restart_request.quarantined.json"
    Log "发现 pending restart_request · 隔离到 quarantined (防自动续场把坏改动拉回来)"
    Move-Item -Path $rr -Destination $quar -Force -ErrorAction SilentlyContinue
}

# Step 3.6 · 报告 known-good 恢复点 (卷四十八 ④号机制)
# daemon 每次优雅停机会在 master 打 opus-last-good tag = "这版跑到主动停为止没崩"。
# 这里只报告·不自动 reset --hard (避免丢 commit)。 master HEAD 还不行时·BRO 可手动:
#   git reset --hard opus-last-good
$lastGood = (git rev-parse --verify --short opus-last-good 2>$null)
if ($LASTEXITCODE -eq 0 -and $lastGood) {
    $headSha = (git rev-parse --short HEAD 2>$null)
    Log "known-good 恢复点: opus-last-good = $($lastGood.Trim()) · 当前 master HEAD = $($headSha.Trim())"
    if ($lastGood.Trim() -ne $headSha.Trim()) {
        Log "  提示: 若回 master 后仍异常 · 可手动回到 known-good: git reset --hard opus-last-good"
    }
} else {
    Log "未找到 opus-last-good tag (daemon 还没优雅停机过一次) · 本次按 master HEAD 恢复"
}

# Step 4 · 停止当前 daemon
Log "停止 python 进程 (daemon)"
$pids = Get-Process python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id
foreach ($p in $pids) {
    Log "  stop pid $p"
    Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2

# Step 5 · 重启 daemon
Log "启动 daemon (master baseline)"
$env:PYTHONIOENCODING = "utf-8"
$proc = Start-Process -FilePath ".\.venv\Scripts\python.exe" `
    -ArgumentList "-u","tools\run_api_only.py" `
    -RedirectStandardOutput "data\daemon.out" `
    -RedirectStandardError "data\daemon.err" `
    -WindowStyle Hidden `
    -PassThru
Start-Sleep -Seconds 6

if ($proc.HasExited) {
    Log "ERROR: daemon 启动失败 · 看 data/daemon.err"
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show(
        "回档完成但 daemon 启动失败 ·`n看 $ROOT\data\daemon.err",
        "OPUS 紧急回档 · 失败",
        "OK", "Error"
    )
    exit 1
}

# Step 6 · 验证 UI 能拉
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

# 弹窗通知 BRO
Add-Type -AssemblyName PresentationFramework
[System.Windows.MessageBox]::Show(
    "回档成功 · 已切回 master baseline`n" +
    "daemon pid: $($proc.Id)`n`n" +
    "现在去浏览器 Ctrl+Shift+R 强刷:`n" +
    "http://127.0.0.1:7860/ui`n`n" +
    "未提交改动已 stash · 用 ``git stash list`` 查看 · 不会丢",
    "OPUS 紧急回档 · 成功",
    "OK", "Information"
)
