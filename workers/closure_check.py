"""
workers/closure_check.py
========================

卷五十九 · 收尾检查引擎 (SKILL 触发可靠性修复 · P1/P2/P3 共用地基)

背景 (两次代码侦察 + BRO 2026-06-06 拍板「冲全套」):
  铁律 9「收尾三问」是纯 system_prompt 文字 · 零代码强制 · 高密度写码时常被跳过;
  playbook 存得进、搜得到 · 但「下次自动取出来用」从没接通 · used_count 全 0。
  根因: 成长类铁律靠 OPUS 自觉 · 安全类铁律 (密钥/大文件/上线) 靠代码硬闸——触发哲学分裂。

这个模块把「收尾点过三问」从软自觉挪向有节拍器 (一个引擎·三处挂载):
  - turn 台账: 记录本回合 OPUS 调过哪些工具 (tool_loop 的 observe 钩子喂)
  - P1 wish 收尾轻硬闸: wish_update 进 review/live 前 · 干了活却没沉淀 → 拦一次 · 给狡辩出路
  - P2 任务启动 recall: 用户消息命中已有 playbook → 自动捞出来递到 OPUS 手边
  - P2/P3 turn 结束反思: 干了活没沉淀 → 推一条收尾提示 (SSE 卡片) + 落对账台账

为什么用 ContextVar 不用 RUNTIME 单例:
  RUNTIME.session_id 是进程单例 · 并发 session 会串台。
  ContextVar 按执行上下文隔离 (SSE 每 turn 独立线程 / 非流式独立 async task)·
  observe 在主线程串行喂 · wish_update 同线程读 · 天然隔离无竞态。
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("opus.closure")

ROOT = Path(__file__).resolve().parents[1]
HINTS_FILE = ROOT / "data" / "runtime" / "closure_hints.jsonl"

# ── 工具分类 ───────────────────────────────────────────────────────
# 沉淀 / 三问工具: 本回合调过任一 · 就算「过了收尾三问」
SINK_TOOLS = {
    "update_bro_note",        # 问1 · BRO 新信号 → 画像
    "extract_playbook",       # 问2 · 可复用经验 → playbook
    "wish_add",               # 问3 · 能力缺口 → 心愿
    "update_self_evolution",  # OPUS 日记 (也算沉淀)
}

# 带副作用的「干活」工具: 调了这些 = 这回合真做了事 (不是纯查询 / 闲聊)
SIDE_EFFECT_TOOLS = {
    "write_file", "edit_file", "str_replace",
    "shell_exec", "python_exec",
    "create_app", "update_app", "delete_app",
    "summon_cursor", "request_restart",
    "wechat_send", "write_clipboard", "open_app",
}

# turn 结束反思的降噪阈值: 副作用工具被调够这么多次才提示 (单次小动作不烦)
_TURN_END_MIN_SIDE_EFFECTS = 2

_CLOSURE_STATUSES = {"review", "live"}


# ── turn 台账 (ContextVar) ─────────────────────────────────────────
_TURN_TOOLS: contextvars.ContextVar[Optional[list]] = contextvars.ContextVar(
    "opus_turn_tools", default=None
)


def begin_turn() -> None:
    """一个 chat turn 开始时清台账 (在 _chat_impl 入口调)。"""
    _TURN_TOOLS.set([])


def record_tool(name: str) -> None:
    """记录本回合调过的一个工具 (observe 钩子喂 · 主线程串行)。"""
    lst = _TURN_TOOLS.get()
    if lst is not None and name:
        lst.append(name)


def tools_called() -> list:
    """本回合到此刻为止调过的工具名 (按序 · 可能重复)。"""
    return list(_TURN_TOOLS.get() or [])


def make_observe():
    """给 tool_loop 的 observe 参数 · 把每个工具调用旁路记进台账 · 不动 ToolResult。"""
    def _observe(spec, _args, _result):
        try:
            record_tool(getattr(spec, "name", "") or "")
        except Exception:
            pass
    return _observe


def did_side_effect(tools: Optional[list] = None) -> bool:
    t = tools if tools is not None else tools_called()
    return any(x in SIDE_EFFECT_TOOLS for x in t)


def did_sink(tools: Optional[list] = None) -> bool:
    t = tools if tools is not None else tools_called()
    return any(x in SINK_TOOLS for x in t)


# ── P1 · wish 收尾轻硬闸 ──────────────────────────────────────────
def wish_closure_gate(target_status: str, *, acked: bool = False) -> Optional[str]:
    """wish_update 标 review/live 前调。

    返回 None = 放行;返回字符串 = 拦截提示 (作为 ToolResult.error 喂回 LLM·让它自纠)。

    拦的条件 (全满足才拦):
      - target_status ∈ {review, live}
      - 本回合调过带副作用工具 (真干了活·不是纯状态流转)
      - 本回合没调过任何沉淀工具 (没过三问)
      - 没带 closure_ack=true (还没狡辩过)
    """
    if acked:
        return None
    if (target_status or "").strip().lower() not in _CLOSURE_STATUSES:
        return None
    tools = tools_called()
    if not did_side_effect(tools):
        return None  # 没干活 · 别拦 (纯状态流转 / 批准 / 改优先级)
    if did_sink(tools):
        return None  # 已经沉淀过 · 放行
    from identity import localize_narration as _ln
    return _ln(
        "收尾三问没过 (铁律 9 · 代码闸 · 卷五十九)\n\n"
        f"本回合你干了带副作用的活 (改文件 / 跑命令 / 造 app ...) · 但还没调过任何沉淀工具就想标 `{target_status}`。\n"
        "先过一遍三问 (不是『觉得该不该』· 是硬纪律):\n"
        "  ① BRO 这次透露新信号了吗? (状态 / 情绪 / 作息 / 偏好 / 决定) → 有则 `update_bro_note`\n"
        "  ② 这次的操作流程 / 踩坑值得复用吗? → 有则 `extract_playbook`\n"
        "  ③ 发现自己的能力缺口了吗? (『要是我有 X 就不费劲』) → 有则 `wish_add`\n\n"
        "**两条合法出路 (别硬标上线)**:\n"
        f"  - 真有可沉淀的 → 先调上面对应工具 · 再标 {target_status}\n"
        "  - 确实啥也不用沉淀 → 这次 wish_update 带上 `closure_ack=true` 重调 · 在 reflection 里一句话说明为什么不用沉淀\n"
    )


# ── P2 · 任务启动 recall (playbook 预取) ──────────────────────────
_TOKEN_SPLIT = re.compile(r"[\s·,，、/。.:：;；()（）\[\]\-_]+")


def _index_by_slug() -> dict:
    """slug → playbook meta (id/title/used_count)·给 FTS5 命中映射回可 load 的 playbook。"""
    try:
        from workers.playbooks import list_playbooks
        return {pb.get("slug", ""): pb for pb in list_playbooks() if pb.get("slug")}
    except Exception:
        return {}


def _keyword_playbooks(message: str, limit: int) -> list[dict]:
    """fallback · 关键词匹配 (tag / 标题词出现在消息里)·FTS5 不可用时兜底。"""
    msg = (message or "").lower()
    try:
        from workers.playbooks import list_playbooks
        pbs = list_playbooks()
    except Exception:
        return []
    scored: list[tuple[int, dict]] = []
    for pb in pbs:
        score = 0
        for tag in pb.get("tags", []) or []:
            t = (tag or "").strip().lower()
            if len(t) >= 2 and t in msg:
                score += 2
        for tok in _TOKEN_SPLIT.split(pb.get("title", "") or ""):
            tok = tok.strip().lower()
            if len(tok) >= 2 and tok in msg:
                score += 1
        if score > 0:
            scored.append((score, pb))
    scored.sort(key=lambda x: (-x[0], -int(x[1].get("used_count", 0) or 0)))
    return [pb for _, pb in scored[:limit]]


def relevant_playbooks(message: str, *, limit: int = 2) -> str:
    """用户消息命中已有 playbook → 返回一段拼进 system 的提示;无匹配返回空串。

    主路径走 FTS5 (memory_index · jieba 分词 · 高召回·跟 recall_memory(scope='skill') 同源);
    FTS5 不可用退化到关键词匹配 (tag / 标题词)。
    目的: 把『下次类似任务自动想起 playbook』从 OPUS 自觉挪成 daemon 确定性注入 (堵断点 B)。
    """
    msg = (message or "").strip()
    if len(msg) < 4:
        return ""

    top: list[dict] = []
    # 主路径 · FTS5 检索 skill 源 · section = "<slug>:<task_type>"
    try:
        from workers.memory_index import search as _fts_search
        slug_map = _index_by_slug()
        seen: set[str] = set()
        for chunk in _fts_search(msg, top_k=4, scope="skill", context_window=2000):
            slug = (getattr(chunk, "section", "") or "").split(":", 1)[0]
            if not slug or slug in seen:
                continue
            seen.add(slug)
            meta = slug_map.get(slug) or {"id": f"pb-{slug[:40]}", "title": slug, "used_count": 0}
            top.append(meta)
            if len(top) >= limit:
                break
    except Exception:
        top = []

    if not top:
        top = _keyword_playbooks(msg, limit)
    if not top:
        return ""

    lines = [
        "\n\n=== 相关 playbook · daemon 自动检索 (之前沉淀过类似任务·不要复述这一段) ===\n",
        "下面是你 / 前几根毛沉淀的、跟这次请求命中的操作手册。",
        "**先扫一眼 · 命中就 `extract_playbook(action=load, playbook_id=...)` 看全文照着做** · 别从零摸索:\n",
    ]
    for pb in top:
        lines.append(f"- `{pb.get('id', '')}` · {pb.get('title', '')} (复用过 {pb.get('used_count', 0)} 次)")
    return "\n".join(lines)


# ── P2/P3 · turn 结束反思 ─────────────────────────────────────────
def turn_end_report(tools: Optional[list] = None) -> Optional[dict]:
    """一轮 chat 结束后调。返回 None = 不必提示;返回 dict = 该提醒收尾沉淀。

    触发: 副作用工具被调 ≥ 阈值 (真在干活) · 且本回合没调任何沉淀工具。
    返回 dict 给前端渲染收尾提示卡 + 落对账台账。
    """
    t = tools if tools is not None else tools_called()
    se_calls = [x for x in t if x in SIDE_EFFECT_TOOLS]
    if len(se_calls) < _TURN_END_MIN_SIDE_EFFECTS:
        return None
    if did_sink(t):
        return None  # 已沉淀 · 不打扰

    se_kinds = sorted(set(se_calls))
    return {
        "kind": "closure_hint",
        "side_effect_tools": se_kinds,
        "side_effect_calls": len(se_calls),
        "suggestions": [
            {"tool": "update_bro_note", "q": "BRO 这次透露新信号了吗?"},
            {"tool": "extract_playbook", "q": "这次的操作流程 / 踩坑值得复用吗?"},
            {"tool": "wish_add", "q": "发现自己的能力缺口了吗?"},
        ],
        "text": (
            "这回合你动了 " + "、".join(se_kinds)
            + f" (共 {len(se_calls)} 次) · 但没沉淀任何东西。要不要过一遍收尾三问?"
        ),
    }


def record_hint(session_id: str, report: dict) -> None:
    """把一条收尾提示落进对账台账 closure_hints.jsonl (best-effort·失败不影响主流程)。

    给 BRO / OPUS 事后对账用: 回看『哪些 turn 干了活却没沉淀』·闭环不靠当场记得。
    """
    try:
        HINTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id or "",
            "resolved": False,
            **report,
        }
        with HINTS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug("record_hint failed: %s", e)


def pending_hints(limit: int = 20) -> list[dict]:
    """读最近未解决的收尾提示 (给 BI / 对账面板用)。"""
    if not HINTS_FILE.exists():
        return []
    out: list[dict] = []
    try:
        for line in HINTS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    except Exception:
        return []
    return out[-limit:]
