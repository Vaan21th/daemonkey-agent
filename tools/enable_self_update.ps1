#requires -Version 5.1
<#
.SYNOPSIS
  一键启用 Daemonkey 自助升级 —— 把 ZIP 下载的"死文件夹"变成能对话升级的实例。

.DESCRIPTION
  ZIP 下载的 Daemonkey 没有 git · 用不了内核自助升级(update_core)。
  这个脚本做三件事(只增不减 · 绝不碰你的 soul/ data/ 应用):
    ① git init + 把你当前所有文件存一个基线 commit(随时能回退的安全网)
    ② 配好升级源 gitee(下游只拉不推)
    ③ fetch 一次 · 让 update_core 立刻能用
  跑完 · 对 AI 说「看看内核有没有更新」/「升级内核」就能拉最新内核了。
  升级只换内核骨架 · 你的对话 / 应用 / 记忆一个字节都不动。
#>
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$GITEE = 'https://gitee.com/vaan21th/dae-monkey.git'
$root = Split-Path -Parent $PSScriptRoot   # tools/ 的上一级 = 工程根

function Say($m, $c = 'Gray') { Write-Host $m -ForegroundColor $c }

Say "============================================" Cyan
Say "  Daemonkey · 启用自助升级" Cyan
Say "============================================" Cyan
Set-Location $root
Say "工程目录: $root"
Say ""

# 0. git 在不在
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Say "[X] 没装 git · 自助升级需要它。" Red
    Say "    去 https://git-scm.com/download/win 下载 · 一路下一步装好 · 再重跑本脚本。" Yellow
    Read-Host "按回车退出"; exit 1
}

# 1. 是不是已经 git 仓库
$inside = (git rev-parse --is-inside-work-tree 2>$null)
if ($LASTEXITCODE -eq 0 -and "$inside".Trim() -eq 'true') {
    Say "[1/3] 已经是 git 仓库 · 跳过 init。" DarkGray
} else {
    Say "[1/3] git init + 存一个基线(你现在所有文件的安全存档) ..."
    git -c init.defaultBranch=master init | Out-Null
    git add -A
    git -c user.name='daemonkey' -c user.email='daemonkey@local' commit -m "baseline · 启用自助升级前的存档" | Out-Null
    Say "      基线已存(以后任何升级都能 git 回退到这里)。" Green
}

# 2. 配 gitee 源
$remotes = @(git remote 2>$null)
if ($remotes -contains 'gitee') {
    Say "[2/3] gitee 升级源已配 · 跳过。" DarkGray
} else {
    Say "[2/3] 配置升级源 gitee ..."
    git remote add gitee $GITEE
    Say "      gitee -> $GITEE" Green
}

# 3. fetch
Say "[3/3] 联网拉取最新内核索引(git fetch) ..."
git fetch gitee --prune 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Say "[!] fetch 没成功 · 多半是网络 · 或 gitee 仓库不是「公开」的。" Yellow
    Say "    确认浏览器能打开 $GITEE 后重跑本脚本。" Yellow
} else {
    Say "      索引就绪。" Green
}

Say ""
Say "============================================" Cyan
Say "  启用完成!" Green
Say "  打开 Daemonkey · 对 AI 说:" Cyan
Say "    「看看内核有没有更新」 -> 查有没有新版" Gray
Say "    「升级内核」          -> 一键升到最新(自动备份 · 可回退)" Gray
Say "  升级只换内核骨架 · 你的对话 / 应用 / 记忆一个字节都不动。" DarkGray
Say "============================================" Cyan
Read-Host "按回车退出"
