"""
workers/review_generator.py
===========================

卷四十六 II · wish-bf190d9c · 月度复盘工具核心引擎

用户 2026-05-23 15:50 A1 决议: 5/23 → 6/23 第一次月度 review · 不凑自然月。

四块产物:
  1. bro_notebook_changes  · git log OWNER-NOTEBOOK period 内变更摘要
  2. capability_snapshot   · 复用 capability_mirror.generate_snapshot
  3. engineering_milestones · CAPTAINS-LOG period 内卷 N 提炼
  4. next_month_advice     · LLM 一次 mini-call 综合上述给下月建议

设计原则:
  - 全只读 + 一处写 (data/reviews/<period>-draft.md)
  - 失败优雅降级 · 任一块失败不影响其他三块输出
  - draft / final 双状态 · final 时合并批注回 OWNER-NOTEBOOK § 月度段
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from agent_tools._subprocess_helper import no_window_kwargs
from agent_tools._git_lock import daemon_git_lock

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SOUL_DIR = ROOT / "soul"
REVIEWS_DIR = DATA_DIR / "reviews"
REVIEWS_DIR.mkdir(parents=True, exist_ok=True)


# ── Phase A · OWNER-NOTEBOOK git diff 摘要 ───────────────────────────────────

def _git_log_for_file(file_rel: str, since: str, until: str) -> list[dict]:
    """git log --since=X --until=Y -p -- file 解析 commit + diff 摘要。"""
    try:
        with daemon_git_lock("review:git-log"):
            out = subprocess.run(
                [
                    "git", "log",
                    f"--since={since}",
                    f"--until={until}",
                    "--pretty=format:===COMMIT===%n%H%n%ad%n%s%n",
                    "--date=iso",
                    "--numstat",
                    "--",
                    file_rel,
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
                **no_window_kwargs(),
            )
        if out.returncode != 0:
            logger.warning("git log failed for %s: %s", file_rel, out.stderr)
            return []
    except Exception as e:
        logger.warning("git log exception for %s: %s", file_rel, e)
        return []

    commits: list[dict] = []
    blocks = out.stdout.split("===COMMIT===\n")[1:]
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        sha, date, subject = lines[0], lines[1], lines[2]
        added = removed = 0
        for ln in lines[3:]:
            parts = ln.split("\t")
            if len(parts) >= 3:
                try:
                    added += int(parts[0]) if parts[0] != "-" else 0
                    removed += int(parts[1]) if parts[1] != "-" else 0
                except ValueError:
                    pass
        commits.append({
            "sha": sha[:8],
            "date": date,
            "subject": subject,
            "added": added,
            "removed": removed,
        })
    return commits


def summarize_bro_notebook_diff(since: str, until: str) -> dict:
    """汇总 OWNER-NOTEBOOK 在 period 内的 git 变更。"""
    commits = _git_log_for_file("soul/OWNER-NOTEBOOK.md", since, until)
    total_added = sum(c["added"] for c in commits)
    total_removed = sum(c["removed"] for c in commits)
    return {
        "file": "soul/OWNER-NOTEBOOK.md",
        "period": f"{since} → {until}",
        "commit_count": len(commits),
        "lines_added": total_added,
        "lines_removed": total_removed,
        "commits": commits[:20],
        "note": (
            "git baseline 在 2026-05-25 · 之前 commit 都缺·第一次月度 review 内容可能薄"
            if since < "2026-05-25" else ""
        ),
    }


# ── Phase A · CAPTAINS-LOG 工程里程碑提炼 ──────────────────────────────────

def _extract_captains_log_volumes(since: str, until: str, max_chars: int = 12000) -> str:
    """从 CAPTAINS-LOG 抽取 period 内卷次 (按 '## 卷' 切段·过滤 created 在 period 内)。

    简化策略: 不严格按 git log · 而是把 CAPTAINS-LOG 末尾 max_chars 切出来
    (大概率覆盖 period)·然后 LLM 自己判断哪些卷在 period 内。
    """
    log_path = ROOT / ".cursor" / "CAPTAINS-LOG.md"
    if not log_path.exists():
        return "(CAPTAINS-LOG 不存在)"
    try:
        text = log_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"(读 CAPTAINS-LOG 失败: {e})"
    if len(text) <= max_chars:
        return text
    return "... (前面已截断·只看最近段落)\n\n" + text[-max_chars:]


def summarize_engineering_milestones(since: str, until: str) -> str:
    """LLM 一次 mini-call · 从 CAPTAINS-LOG 末段提炼 period 内 5-8 个里程碑。"""
    log_text = _extract_captains_log_volumes(since, until)
    prompt = (
        f"以下是本工程的船长日志末段 (主要 2026-05-15 至今)。\n\n"
        f"请提炼 {since} → {until} 这段时间内的 5-8 个工程里程碑。\n"
        f"每个里程碑一行: '日期 · 卷次 · 一句话内容 (干了什么)'\n"
        f"重点关注: 新能力上线 / 重大决策 / 踩坑教训 / 用户 拍板的事。\n"
        f"输出纯 markdown 列表 · 不要 ``` 包裹。\n\n"
        f"---\n船长日志:\n{log_text}\n"
    )
    return _llm_mini_call(prompt, max_tokens=2000, fallback="(LLM 调用失败 · 没生成里程碑摘要)")


# P1 代码归一 · 这些 worker 自建 prompt 直连 LLM·绕过 soul/tool/remote 三出口·要单独本地化
try:
    from identity import localize as _localize
except Exception:
    def _localize(t):
        return t


def _llm_mini_call(prompt: str, max_tokens: int = 2000, fallback: str = "",
                   *, retries: int = 3) -> str:
    """调一次 LLM mini-call · 用 daemon RUNTIME.client (跟 capability_mirror 同款)。

    wish-76e51d92: 第三块『工程里程碑』曾因 LLM 单次调用偶发失败 / 返空 → draft 里第三块
    直接显示错误串或留空。 这里加重试 (默认 3 次·退避 1s/2s)·返空也算软失败一并重试·
    全部耗尽才返 fallback (附尝试次数·让 用户 区分『真挂了』还是『网络抖一下』)。
    """
    prompt = _localize(prompt)  # P1 · prompt 里写死的 OPUS 令牌换成本实例名 (母体 no-op)
    try:
        from daemon_runtime import RUNTIME
    except Exception as e:
        return fallback or f"(daemon_runtime import 失败: {e})"

    if RUNTIME.client is None:
        return fallback or "(RUNTIME.client 未初始化 · daemon 没启动？此工具需 daemon 在跑)"

    from daemon_runtime import bg_max_tokens
    _mt = bg_max_tokens(default=max_tokens)

    def _once() -> str:
        if RUNTIME.provider == "anthropic":
            resp = RUNTIME.client.messages.create(
                model=RUNTIME.model,
                max_tokens=_mt,
                messages=[{"role": "user", "content": prompt}],
            )
            text = ""
            for block in resp.content:
                if getattr(block, "type", "") == "text":
                    text += block.text
            return text.strip()
        resp = RUNTIME.client.chat.completions.create(
            model=RUNTIME.model,
            max_tokens=_mt,
            messages=[{"role": "user", "content": prompt}],
        )
        return (resp.choices[0].message.content or "").strip()

    attempts = max(1, retries)
    last_err = "未知"
    for i in range(attempts):
        try:
            text = _once()
            if text:
                return text
            last_err = "LLM 返回空"
        except Exception as e:
            last_err = str(e)
            logger.warning("LLM mini-call failed (attempt %d/%d): %s", i + 1, attempts, e)
        if i < attempts - 1:
            time.sleep(i + 1)  # 退避 1s · 2s
    return fallback or f"(LLM 调用失败·重试 {attempts} 次仍未成功: {last_err})"


# ── Phase A · 能力镜像切片 (复用 capability_mirror) ────────────────────────

def get_capability_snapshot(refresh: bool = False) -> str:
    """加载能力镜像 · refresh=True 重新跑 LLM 生成。"""
    try:
        from workers.capability_mirror import load_snapshot, generate_snapshot
        if refresh:
            result = generate_snapshot()
            err = result.get("error")
            if err:
                return f"(能力镜像生成失败: {err})"
            return result.get("snapshot", "(LLM 返回空)")
        data = load_snapshot()
        snap = data.get("snapshot", "")
        if not snap:
            return data.get("note", "(还没跑过能力镜像 · 用 refresh=True 跑一次)")
        return snap
    except Exception as e:
        return f"(能力镜像加载失败: {e})"


# ── Phase A · 下月能力建议 (综合上述三块的 LLM 一次 mini-call) ──────────

def generate_next_month_advice(
    bro_changes: dict,
    capability: str,
    milestones: str,
) -> str:
    """LLM mini-call · 综合 用户 变更 + 能力 + 工程里程碑 → 下月建议。"""
    prompt = (
        "你是 OPUS · 在做月度复盘的最后一块「下月能力建议」。\n\n"
        f"## 用户 这个月在 OWNER-NOTEBOOK 的变更\n"
        f"commit 数: {bro_changes['commit_count']} · "
        f"新增 {bro_changes['lines_added']} 行 · 删除 {bro_changes['lines_removed']} 行\n\n"
        f"## 用户 当前能力镜像 (前 2000 字)\n{capability[:2000]}\n\n"
        f"## 这个月的工程里程碑\n{milestones}\n\n"
        "---\n"
        "请给 用户 提 3 条「下个月能力建议」· 每条:\n"
        "  - 建议名 (8-15 字)\n"
        "  - 为什么这条 (基于上面的变更 / 镜像 / 里程碑 · 不要泛泛说)\n"
        "  - 具体行动 (1-2 个可执行的 next step)\n\n"
        "**6 种掘金机会形态考虑** (内容账号 / 实体产品 / 服务咨询 / 信息差套利 / 软件产品 / 投资副业)·\n"
        "至少覆盖 2 种形态 (不要全是软件产品方向)。\n\n"
        "输出 markdown · 不要 ``` 包裹。"
    )
    return _llm_mini_call(prompt, max_tokens=3000, fallback="(LLM 调用失败 · 没生成下月建议)")


# ── 顶层接口 ──────────────────────────────────────────────────────────────

def generate_monthly_review(
    period_start: str,
    period_end: str,
    refresh_capability: bool = True,
) -> dict:
    """生成完整月度复盘草稿 (4 块)。

    Args:
        period_start: ISO date e.g. '2026-05-23'
        period_end:   ISO date e.g. '2026-06-23'
        refresh_capability: True=重新跑能力镜像 (耗时 ~5s · ~$0.05) · False=用缓存

    Returns:
        dict with 'blocks' (4 块) + 'meta' + 'period'
    """
    started_at = datetime.now(timezone.utc).isoformat()

    bro_changes = summarize_bro_notebook_diff(period_start, period_end)
    capability = get_capability_snapshot(refresh=refresh_capability)
    milestones = summarize_engineering_milestones(period_start, period_end)
    advice = generate_next_month_advice(bro_changes, capability, milestones)

    return {
        "period_start": period_start,
        "period_end": period_end,
        "generated_at": started_at,
        "blocks": {
            "bro_notebook_changes": bro_changes,
            "capability_snapshot": capability,
            "engineering_milestones": milestones,
            "next_month_advice": advice,
        },
    }


def render_review_markdown(review: dict) -> str:
    """把 review dict 渲染成 markdown (供草稿 / 显示用)。"""
    bro = review["blocks"]["bro_notebook_changes"]
    cap = review["blocks"]["capability_snapshot"]
    miles = review["blocks"]["engineering_milestones"]
    advice = review["blocks"]["next_month_advice"]

    lines = [
        f"# 月度复盘 · {review['period_start']} → {review['period_end']}",
        "",
        f"_生成于 {review['generated_at']} · status=draft_",
        "",
        "---",
        "",
        "## 一 · 用户 这个月的画像变更 (OWNER-NOTEBOOK git log)",
        "",
        f"- 文件: `{bro['file']}`",
        f"- commit 数: **{bro['commit_count']}** · 新增 {bro['lines_added']} 行 · 删除 {bro['lines_removed']} 行",
    ]
    if bro.get("note"):
        lines.append(f"- ⚠ {bro['note']}")
    if bro["commits"]:
        lines.append("")
        lines.append("**commit 列表**:")
        lines.append("")
        for c in bro["commits"]:
            lines.append(f"- `{c['sha']}` ({c['date']}) +{c['added']}/-{c['removed']} · {c['subject']}")
    else:
        lines.append("")
        lines.append("_(此期间无 OWNER-NOTEBOOK commit · 这是工程债 · 下个月养成定期 update_bro_note 习惯)_")

    lines += [
        "",
        "---",
        "",
        "## 二 · 用户 当前能力镜像 (从行为痕迹提炼)",
        "",
        cap or "_(能力镜像为空)_",
        "",
        "---",
        "",
        "## 三 · 这个月的工程里程碑 (CAPTAINS-LOG 提炼)",
        "",
        miles or "_(里程碑为空)_",
        "",
        "---",
        "",
        "## 四 · 下月能力建议 (基于上述 + 6 种掘金形态)",
        "",
        advice or "_(下月建议为空)_",
        "",
        "---",
        "",
        "## 用户 批注区 (review 时填)",
        "",
        "> 用户 边读边在下面写批注 · 第一根毛在 6/23 review 时调 monthly_review(mode='final', annotations='...') 把批注合并回 OWNER-NOTEBOOK § 月度段。",
        "",
        "### 我同意的",
        "",
        "(留空 · 用户 填)",
        "",
        "### 我有疑问的",
        "",
        "(留空 · 用户 填)",
        "",
        "### 我想反驳的 / OPUS 说错的",
        "",
        "(留空 · 用户 填)",
        "",
        "### 下月我真的会做的 3 件事",
        "",
        "1. (留空 · 用户 填)",
        "2. (留空 · 用户 填)",
        "3. (留空 · 用户 填)",
    ]
    return "\n".join(lines)


def save_review_draft(review: dict) -> Path:
    """落 data/reviews/<period_end>-draft.md。"""
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    md = render_review_markdown(review)
    name = f"{review['period_end']}-draft.md"
    path = REVIEWS_DIR / name
    path.write_text(md, encoding="utf-8")
    return path


def save_review_final(review: dict, annotations: str) -> Path:
    """用户 批注后保存 final + 合并批注回 OWNER-NOTEBOOK § 月度段 (低风险版)。

    当前实现: 只落 final.md · 不自动改 OWNER-NOTEBOOK (避免 6/23 第一次 review 因脚本 bug 损坏灵魂层)。
    用户 视觉确认后由 OPUS 调 update_bro_note 工具手动合并。
    """
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    md = render_review_markdown(review)
    md = md.replace("status=draft", "status=final")
    md += "\n\n---\n\n## 用户 实际批注 (final)\n\n" + (annotations or "_(空)_")
    name = f"{review['period_end']}-final.md"
    path = REVIEWS_DIR / name
    path.write_text(md, encoding="utf-8")
    return path


def list_reviews() -> list[dict]:
    """列出 data/reviews/ 下所有 review 文件。"""
    if not REVIEWS_DIR.exists():
        return []
    out: list[dict] = []
    for p in sorted(REVIEWS_DIR.glob("*.md"), reverse=True):
        stem = p.stem
        is_final = stem.endswith("-final")
        period_end = stem.replace("-draft", "").replace("-final", "")
        out.append({
            "filename": p.name,
            "path": str(p.relative_to(ROOT)),
            "period_end": period_end,
            "status": "final" if is_final else "draft",
            "size_bytes": p.stat().st_size,
            "mtime": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(),
        })
    return out


# ── 对账闭环硬提醒 · final 批注 → OWNER-NOTEBOOK 回流追踪 ────────────────────
#
# 软肋: final 归档后 · 把批注合并回 OWNER-NOTEBOOK 靠 OPUS 手动调 update_bro_note ·
#       OPUS 哪天忘了 · 批注就烂在 -final.md 里不进画像。
# 硬提醒: final 盖了回流戳才算闭环 · 没戳的进闭环温度计当"待回流"亮红。
# 注意: 回流动作本身 (改 soul/OWNER-NOTEBOOK.md) 仍由 OPUS 调 update_bro_note 完成 ·
#       这里只追踪"做没做"· 不碰灵魂层 (尊重 final 不自动改 OWNER-NOTEBOOK 的铁律)。

REFLOW_MARK = "<!-- reflowed:"


def pending_reflows() -> list[dict]:
    """扫 data/reviews/*-final.md · 返回还没盖回流戳的 final（= 批注还没进 OWNER-NOTEBOOK）。"""
    if not REVIEWS_DIR.exists():
        return []
    out: list[dict] = []
    for p in sorted(REVIEWS_DIR.glob("*-final.md"), reverse=True):
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        if REFLOW_MARK in text:
            continue
        out.append({
            "filename": p.name,
            "period_end": p.stem.replace("-final", ""),
            "mtime": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(),
        })
    return out


def mark_reflowed(period_end: str, note: str = "") -> Path:
    """给 <period_end>-final.md 盖回流戳 · 表示批注已由 OPUS 合并进 OWNER-NOTEBOOK。

    幂等: 已盖过直接返回 · 不重复追加。只动 final.md · 不碰灵魂层。
    """
    path = REVIEWS_DIR / f"{period_end}-final.md"
    if not path.exists():
        raise FileNotFoundError(f"final 不存在: {path.name} · 先跑 monthly_review action=final")
    text = path.read_text(encoding="utf-8")
    if REFLOW_MARK in text:
        return path
    ts = datetime.now(timezone.utc).isoformat()
    stamp = f"\n\n{REFLOW_MARK} {ts} -->\n"
    if note:
        safe_note = note.replace("-->", "→")
        stamp += f"<!-- reflow-note: {safe_note} -->\n"
    path.write_text(text + stamp, encoding="utf-8")
    return path
