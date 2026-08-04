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


# _PB_INJECT_MIN_SCORE 校准 (2026-06-23 · 6 条 playbook 实测 · 召回探针):
#   真命中 top bm25 ∈ [-30, -12] (口播 -13.4 / 分镜 -27.3 / 下载 -23.9 / 前端 -20 / MIME -30 / 长文档 -12)
#   离题/弱噪音 (天气 / Top2-3 撞词) bm25 ∈ [-9.8, -1]
#   取 -10 卡断层: 6/6 真命中全过·挡掉"问A带出B"的弱噪音 + 离题 (堵 playbook 噪音注入)。
#   仅剩 B站系主题相邻 (分镜↔下载·都含"B站视频") 互相带·属强相关·注入无害。
#   注: 库变大后 bm25 绝对值会漂·按真实命中率重校 (跟 relevant_memories 同款调味位)。
_PB_INJECT_MIN_SCORE = -10.0

# 0.9.0 · 注入日志 (wish 注入收敛样本收集) · 只写不改行为
# 每次注入追加一行 jsonl 到 data/runtime/inject_log.jsonl · 供重校注入量/阈值用
# 隐私: 只记消息前 200 字 + 注入项摘要 · 数据留 L3 本地 · 永不 sync / 永不回传
_INJECT_LOG_PATH = None


def _inject_log_path() -> Path:
    global _INJECT_LOG_PATH
    if _INJECT_LOG_PATH is None:
        _INJECT_LOG_PATH = Path("data/runtime/inject_log.jsonl")
        try:
            _INJECT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    return _INJECT_LOG_PATH


def _log_injection(message: str, kind: str, items: list, *, hit_score: float | None = None) -> None:
    """追加一条注入日志 · 失败静默 (日志绝不能影响注入主流程)。"""
    try:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": kind,                       # playbook / memory / docs
            "msg": (message or "")[:200],
            "hit_score": round(hit_score, 3) if hit_score is not None else None,
            "items": [str(x)[:120] for x in items][:5],
        }
        with open(_inject_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


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
        for chunk in _fts_search(
            msg, top_k=4, scope="skill", context_window=2000,
            min_score=_PB_INJECT_MIN_SCORE,
        ):
            slug = (getattr(chunk, "section", "") or "").split(":", 1)[0]
            if not slug or slug in seen:
                continue
            seen.add(slug)
            meta = slug_map.get(slug)
            if meta is None:
                # 0.8.8 续 · 注入收敛: FTS5 命中但 list_playbooks 查不到 = 已退役/已删 · 不注入
                # (否则 retired playbook 在 FTS5 还有索引 → fallback 用 slug 当 title 照样注入)
                logger.info("relevant_playbooks 跳过已退役/已删 playbook: %s", slug)
                continue
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
    _log_injection(msg, "playbook", [pb.get("title", "") for pb in top])
    return "\n".join(lines)


# ── ① 记忆自动注入 (保守版) ───────────────────────────────────────
# 把「相关画像自动浮现」从 OPUS 自觉 recall 挪成 daemon 命中即注入·堵
# 「夸了他 / 让他记下来·下次却不自动想起」这个断点 (产品观第2条闭环)。
# 保守起步: 只 scope=bro · 高 bm25 门槛 · 最多 1 条 · 只给标题+单行摘要 (token 便宜)。
# 注入进 system 动态尾巴 (跟 relevant_playbooks 同处·不进灵魂缓存前缀)。
# 阈值/条数是经验值·先开着测命中率与噪音·再按真实使用调 (见船长日志 / SELF-EVOLUTION)。
# _MEM_INJECT_MIN_SCORE 校准 (2026-06-18 · 14 块画像语料实测·tests/smoke_recall_two_stage 探针):
#   离题 query (写代码/天气/量子物理) top bm25 ∈ [-8, -4.5]
#   真命中 (作息/释权/硬件计划)        top bm25 ∈ [-13, -10.2]
#   取 -9.0 卡在中间·挡掉离题 (尤其"帮我写代码"高频场景) · 放进真命中。
#   注: bm25 绝对值随画像增长会漂移·语料变大后按 logger 的命中率重校 (我跟 BRO 说过这是调味位)。
_MEM_INJECT_MIN_SCORE = -9.0    # bm25 越负越相关·只留 <= 此值的强命中·挡离题噪音
_MEM_INJECT_LIMIT = 1           # 最多注入几条画像 (保守起步=1)
_MEM_INJECT_MIN_MSG_LEN = 8     # 消息太短不触发 (画像注入比 playbook 更克制)
_MEM_SNIPPET_CHARS = 180


def relevant_memories(message: str, *, limit: int = _MEM_INJECT_LIMIT) -> str:
    """用户消息强命中 BRO 画像 → 返回一段拼进 system 的背景提示;无强命中返回空串。

    保守版: 只搜 scope=bro · 卡 bm25 高门槛 (_MEM_INJECT_MIN_SCORE) · 最多 limit 条 ·
    只给 章节标题 + 单行短摘要。目的是把相关偏好/标准在命中时自动递到 OPUS 手边·
    而不是每轮硬塞 (那样既烧 token 又污染推理又破坏缓存)。
    """
    msg = (message or "").strip()
    if len(msg) < _MEM_INJECT_MIN_MSG_LEN:
        return ""
    try:
        from workers.memory_index import search as _fts_search
        hits = _fts_search(
            msg, top_k=max(3, limit), scope="bro",
            context_window=4000, min_score=_MEM_INJECT_MIN_SCORE,
        )
    except Exception:
        return ""
    if not hits:
        return ""

    top = hits[:limit]
    lines = [
        "\n\n=== 相关画像 · daemon 自动检索 (来自 BRO 画像·背景参考·别复述这段) ===",
        "下面是跟这次请求相关的 BRO 画像条目·参照它对齐 BRO 的偏好/标准:",
    ]
    for c in top:
        sec = (getattr(c, "section", "") or "").strip()
        head = f"【{sec}】" if sec else ""
        snippet = " ".join((c.content or "").split())[:_MEM_SNIPPET_CHARS]
        lines.append(f"- {head}{snippet}")
    try:
        logger.info(
            "relevant_memories 注入 %d 条 (scope=bro · top_score=%.3f)",
            len(top), getattr(top[0], "score", 0.0),
        )
    except Exception:
        pass
    _log_injection(msg, "memory",
                   [(getattr(c, "section", "") or "")[:60] for c in top],
                   hit_score=getattr(top[0], "score", None) if top else None)
    return "\n".join(lines)


# ── ①b 知识库自动注入 (私有文档 · "第二大脑") ──────────────────────
# 病根: 自动召回只 scope=bro · 知识库(scope=docs)从不进上下文 · OPUS 压根不知道
#       用户灌过资料 → 问"我资料里的事"时凭记忆瞎答 (违反产品观第5条可追溯)。
# 修法: 知识库非空就给 system 尾巴挂一段——① 列出有哪些文档(标题目录·让它知道能查什么·
#       也能桥接"软著"↔《软件登记网络包》这种口语↔正式名的词面差) ② 本轮强命中的片段
#       (可直接引用) ③ 明确指令: 可能在资料里就先 recall_memory(scope=docs) 查证再答并 cite。
# 目录只列标题 (token 便宜)· 命中片段才带正文。挂 _sys_tail 不污染灵魂缓存前缀。
_DOC_INJECT_MIN_SCORE = -9.0     # 跟 relevant_memories 同起点·后续按真实命中率重校
_DOC_INJECT_LIMIT = 3            # 最多带几段命中片段正文
_DOC_SNIPPET_CHARS = 220
_DOC_CATALOG_MAX = 24            # 目录最多列几个标题·防知识库很大时炸 token


def relevant_docs(message: str) -> str:
    """私有知识库自动注入:非空 → 告知 OPUS 有哪些资料 + 本轮命中片段·引导查证再答并 cite。

    catalog(标题目录)每轮都给·让 OPUS 知道『用户有这些资料·可查』;命中片段只在
    FTS5 强命中时才带正文。无知识库 / 空库 → 返回空串(零 token 零干扰)。
    """
    try:
        from workers.knowledge_base import list_documents, get_document
        from workers.memory_index import search as _fts_search
    except Exception:
        return ""
    try:
        # 缺口④ · sensitive 文档不自动注入(目录/片段都不带)· 仍留在索引里·显式 recall 才给
        docs = [d for d in list_documents()
                if d.get("enabled", True) and not d.get("sensitive")]
    except Exception:
        docs = []
    if not docs:
        return ""

    msg = (message or "").strip()
    hit_lines: list[str] = []
    if len(msg) >= 4:
        try:
            hits = _fts_search(
                msg, top_k=max(3, _DOC_INJECT_LIMIT), scope="docs",
                context_window=4000, min_score=_DOC_INJECT_MIN_SCORE,
            )
            for c in hits[:_DOC_INJECT_LIMIT]:
                src = getattr(c, "source", "") or ""
                did = src[len("doc:"):] if src.startswith("doc:") else src
                meta = get_document(did) or {}
                if meta.get("sensitive"):
                    continue  # 缺口④ · 敏感资料不随命中片段自动外送
                title = meta.get("title", did)
                sec = (getattr(c, "section", "") or "").strip()
                head = f"《{title}》" + (f" · {sec}" if sec else "")
                snippet = " ".join((c.content or "").split())[:_DOC_SNIPPET_CHARS]
                hit_lines.append(f"- {head}: {snippet}")
        except Exception:
            hit_lines = []

    # 常驻(pinned)排前面并打标 · 让 OPUS 优先参考核心资料 (P1 · pinned 生效)
    docs.sort(key=lambda d: (0 if d.get("pinned") else 1, d.get("added_at", "")))
    catalog = "、".join(
        f"《{d.get('title', '?')}》" + ("(常驻)" if d.get("pinned") else "")
        for d in docs[:_DOC_CATALOG_MAX]
    )
    more = f" 等共 {len(docs)} 篇" if len(docs) > _DOC_CATALOG_MAX else ""
    has_pinned = any(d.get("pinned") for d in docs)
    lines = [
        "\n\n=== 私有知识库 · daemon 自动提示 (别复述这段) ===",
        f"用户有一个私有文档知识库·含: {catalog}{more}。",
        "**用户问的事若可能落在这些资料里·先 `recall_memory(scope='docs', query=...)` 或 "
        "`manage_knowledge(action='search', query=...)` 查证·据此作答并 cite 回文档·别凭记忆瞎答。**",
    ]
    if has_pinned:
        lines.append("标『常驻』的是用户钉的核心资料·相关时优先查证并参考。")
    if hit_lines:
        lines.append("本轮请求命中的片段 (可直接引用·仍建议 recall 取全文对齐):")
        lines.extend(hit_lines)
    try:
        logger.info("relevant_docs 注入 · 目录 %d 篇 · 命中 %d 段", len(docs), len(hit_lines))
    except Exception:
        pass
    _log_injection(msg, "docs",
                   [d.get("title", "") for d in docs[:5]],
                   hit_score=None)
    return "\n".join(lines)


# ── ①c · 显式"记住"意图 → 本轮硬提醒落盘 ──────────────────────────
# 病根: 用户纯聊天里说"记住我 X / 别忘了 / 以后都"时·这一轮没副作用工具·
#   turn_end 三问不触发 → OPUS 极大概率只嘴上"好的记住了"·从不调 update_bro_note 落盘。
#   (BRO 2026-07-12 报的"让他记住的东西他没记"就是这个断点)
# 修法: 命中显式记忆意图 → 挂 system 尾巴一条硬指令·让 OPUS **本轮就调 update_bro_note**·
#   而不是等收尾卡 (收尾卡是回复之后才出·救不了当轮)。挂 _sys_tail 不进灵魂缓存前缀。
_MEM_WRITE_SIGNALS = (
    "记住", "记一下", "记下来", "记下", "记note", "记笔记", "帮我记", "给我记",
    "存一下", "别忘了", "别忘记", "不要忘", "以后都", "以后记得", "我的偏好",
    "remember this", "remember that", "don't forget", "keep in mind", "note that",
)


def memory_write_hint(message: str) -> str:
    """用户显式让 OPUS 记住某事 → 返回一条"本轮必须 update_bro_note 落盘"的 system 指令。

    只做词面命中 (保守)· 命中才注入·不命中零 token。挂在 system 动态尾巴·当轮生效。
    这是"你说→它落盘"闭环的关键一棒:把落盘时机从"回复之后的收尾卡"提前到"回复之前"。
    """
    msg = (message or "").strip()
    if len(msg) < 4:
        return ""
    low = msg.lower()
    if not any((s in msg) or (s in low) for s in _MEM_WRITE_SIGNALS):
        return ""
    return (
        "\n\n=== 记忆落盘 · daemon 自动提示 (别复述这段) ===\n"
        "BRO 这一轮像是明确要你**记住某件事**。别只在回复里说『好的记住了』——那样下一根毛就丢了。\n"
        "**本轮就调 `update_bro_note` 把它写进对应维度** (profile=当下状态 / events=时间线 / "
        "rules=长期特征 / dialogue=口头记号 / summary=月度压缩 / risks=风险信号)·写完再回复 BRO。\n"
        "写的时候按规范:一条一句、带日期、带原话(如果有)、别把整段聊天糊进去。\n"
        "若确实不值得长期留存 (闲聊 / 临时上下文)·可跳过·但你要在心里过一遍这个判断。"
    )


# ── ①d · 客户对话侧写 (B-P1/P2 · 命中已知客户/交易信号 → 软提醒记档) ─────
# 病根: 跟客户聊出新进展(谈定/交付/状态变)时·OPUS 极少主动把它记进客户档案·
#   档案不长厚 = "合伙人记得每个客户"落空。修法:命中即软提醒(不是硬闸)·
#   OPUS 自己判断值不值得记·别打断当前话题。挂 _sys_tail·当轮生效。
_CLIENT_STATUS_CN = {"lead": "线索", "active": "在合作", "paused": "暂停", "done": "已结束"}
_CLIENT_SIGNALS = (
    "客户", "甲方", "乙方", "对接", "对接人", "合作方", "合作", "签了", "签约", "成交",
    "谈定", "谈成", "定金", "预付", "报价", "合同", "交付", "验收", "回款", "尾款",
    "立项", "需求方", "找我做", "接了个", "接了一单", "接了单", "单子", "这单", "这个客户",
    "client", "deal", "contract", "invoice",
)


def find_mentions(message: str) -> list[dict]:
    """扫消息里出现的已建档客户(name/company ≥2 字且作为子串命中)· 返回命中的客户 meta。

    保守:单字名字不匹配(防"张""李"这类误命中)· 拿不到客户库时返回空。
    """
    msg = (message or "").strip()
    if len(msg) < 2:
        return []
    try:
        from workers.clients import list_clients
        clients = list_clients()
    except Exception:
        return []
    low = msg.lower()
    hits: list[dict] = []
    for c in clients:
        name = (c.get("name") or "").strip()
        comp = (c.get("company") or "").strip()
        if (len(name) >= 2 and (name in msg or name.lower() in low)) or (
            len(comp) >= 2 and (comp in msg or comp.lower() in low)
        ):
            hits.append(c)
    return hits


def client_extract_hint(message: str) -> str:
    """命中已知客户 或 强客户/交易信号 → 一段软提醒:用 manage_client 记进档案。

    命中已建档客户 → 提醒有新进展就 note/status;只命中信号词(没建档)→ 提醒可 add。
    软提醒·非硬闸·OPUS 自行判断;无命中零 token 零干扰。
    """
    msg = (message or "").strip()
    if len(msg) < 4:
        return ""
    mentions = find_mentions(msg)
    low = msg.lower()
    has_signal = any((s in msg) or (s in low) for s in _CLIENT_SIGNALS)
    if not mentions and not has_signal:
        return ""

    lines = ["\n\n=== 客户档案 · daemon 自动提示 (别复述这段) ==="]
    if mentions:
        names = "、".join(
            f"{c.get('name')}[{_CLIENT_STATUS_CN.get(c.get('status'), c.get('status') or '')}]"
            for c in mentions[:5]
        )
        lines.append(f"BRO 提到了已建档的客户: {names}。")
        lines.append(
            "若这轮聊到跟他相关的**新进展**(谈定 / 交付 / 状态变化 / 新偏好)· 顺手用 "
            "`manage_client(action='note', client='...', text='...')` 记进档案(自动带日期)· "
            "状态变了就 `action='status'`。让档案随每次沟通长厚。**没新进展就别记·别打断当前话题**。"
        )
    else:
        lines.append(
            "BRO 像是在聊一个客户 / 合作 / 交易。若这是个值得长期跟进的客户、且还没建档· 可以 "
            "`manage_client(action='add', name='...')` 建一份(把已知的公司 / 角色 / 需求一起带上)· "
            "之后每次进展用 note 追加。**不确定值不值得建档·就先别建**(或自然地问 BRO 一句)。"
        )
    return "\n".join(lines)


# ── ①e · 情感轨 (C · 隐式闲聊信号 → 悄悄记·不尬 callback) ──────────────
# 病根: memory_write_hint 只接『显式说记住』· 但 BRO 闲聊里随口透露的个人的点
#   (爱吃啥 / 今天很累 / 家里的事) 没说"记住"·就永远漏掉——而这恰是合伙人该默默记住的。
# 修法: 命中隐式个人信号 → 软提醒 OPUS 悄悄 update_bro_note · 严禁当面 callback / 为记而记 ·
#   记下后靠 relevant_memories 在未来合适语境自然浮现(而不是现在尬夸尬关心)。
# 与 memory_write_hint 互补: daemon_api 里显式已命中时不叠加本条(避免双重指令)。
_CASUAL_SIGNALS = (
    # 口味 / 吃喝
    "爱吃", "喜欢吃", "最爱吃", "不爱吃", "讨厌吃", "爱喝", "喜欢喝", "口味", "忌口", "过敏",
    # 身体 / 疲惫 / 状态 (人表达"不在状态"最自然的说法·多字防误报)
    "好累", "很累", "太累", "累死", "累坏", "好困", "很困", "困死", "犯困", "没睡", "没睡好",
    "睡不着", "睡不好", "失眠", "熬夜", "没精神", "没什么精神", "没劲", "没劲儿", "提不起劲",
    "没状态", "状态不好", "状态不太好", "状态很差", "疲惫", "疲劳", "身体不太行",
    "生病", "感冒", "发烧", "头疼", "头痛", "胃疼", "不舒服",
    # 情绪
    "emo", "好烦", "烦死", "烦躁", "焦躁", "焦虑", "难过", "郁闷", "有点丧", "好丧", "很丧", "丧气",
    "抑郁", "低落", "不开心", "闷得慌", "心累", "压抑", "压力好大", "压力大", "崩溃", "想哭",
    "扛不住", "撑不住", "好开心", "开心死", "心情",
    # 生活 / 关系 / 节点
    "生日", "过生日", "老婆", "老公", "女朋友", "男朋友", "我对象", "孩子", "父母", "爸妈", "家人",
    "搬家", "结婚", "领证", "去旅行", "去旅游", "出差", "老家", "回老家", "养的", "宠物",
)

# 技术/运维噪音闸:信号词嵌在明显的技术话里(子串误命中)→ 不是情感透露·两条记忆线都跳过。
# 只挡"硬技术词"·不挡"帮我/怎么"这类·免得误伤"帮我想想我妈生日送啥"这种真·生活信号。
_TECH_NOISE = (
    "报销", "流程", "重启", "部署", "接口", "日志", "端口", "配置", "脚本", "代码", "bug",
    "报表", "服务器", "数据库", "编译", "打包", "报价单", "文档", "表格", "字段",
)


def _is_tech_noise(msg: str, low: str) -> bool:
    return any((w in msg) or (w in low) for w in _TECH_NOISE)


def casual_profile_hint(message: str) -> str:
    """BRO 闲聊里隐式透露个人的点(没说记住)→ 软提醒悄悄 update_bro_note。

    只做词面命中(保守)· 命中才注入。红线写死在提示里:别打断话题、别当面 callback、
    只是情绪噪音就跳过。记下后靠自动召回自然浮现·不是现在尬关心。
    """
    msg = (message or "").strip()
    if len(msg) < 2:          # 放松长度闸:"好丧""烦死了"这类短情绪爆发别毙掉(信号词都 ≥2 字)
        return ""
    low = msg.lower()
    if _is_tech_noise(msg, low):
        return ""
    if not any((s in msg) or (s in low) for s in _CASUAL_SIGNALS):
        return ""
    return (
        "\n\n=== 悄悄记一笔 · daemon 自动提示 (别复述这段·尤其别当面 callback) ===\n"
        "BRO 这轮像是随口透露了个人的点(口味 / 心情 / 身体 / 生活)——这类『不是让你记、但值得记』"
        "的信号·正是合伙人该默默记住的东西。\n"
        "**若确实值得长期留存·本轮顺手 `update_bro_note`**(profile=当下状态 / 心情 · "
        "dialogue=口味偏好等口头记号)· 一条一句、带日期。\n"
        "红线(重要):**别打断当前话题 · 别『我记住了』式刻意 callback · 别为记而记**。"
        "记下就好·让它下次在合适语境里自然浮现(靠自动召回)· 而不是现在尬夸 / 尬关心。"
        "只是闲聊噪音 / 临时情绪就跳过。"
    )


# ── ①f · 情感轨主动侧 (C+ · 记情感/健康信号 → 成熟期软回访·防尬) ────────────
# 被动侧(上面)靠 relevant_memories 在合适语境自然浮现;主动侧是"隔几天主动关心一句"。
# 防尬四道闸:① 只对身体/情绪/大生活节点回访(口味不回访)· ② 首次提到后隔 >18h 才成熟
#   (不在同场对话里追)· ③ 单条回访后 72h 冷却、最多回访 2 次· ④ 语境门控:只在闲聊/打招呼
#   这种自然时刻给一次·且一天全局最多一次。给的是软提示·OPUS 语境不合适可以当没看到。
_CARE_STATE = ROOT / "data" / "runtime" / "care_followups.json"
_CARE_SIGNALS = (
    # 身体 / 疲惫(值得隔几天问一句"缓过来没")
    "好累", "很累", "太累", "累死", "累坏", "好困", "很困", "困死", "犯困", "没睡", "没睡好",
    "睡不着", "睡不好", "失眠", "熬夜", "没精神", "没什么精神", "没劲", "提不起劲",
    "没状态", "状态不好", "状态不太好", "疲惫", "疲劳", "生病", "感冒", "发烧",
    "头疼", "头痛", "胃疼", "不舒服", "住院", "手术",
    # 情绪(健康类·非临时噪音)
    "好烦", "烦死", "烦躁", "焦躁", "焦虑", "难过", "郁闷", "有点丧", "好丧", "抑郁", "低落",
    "心累", "压抑", "压力好大", "压力大", "崩溃", "想哭", "扛不住", "撑不住",
    # 大生活节点
    "生日", "过生日", "搬家", "结婚", "领证", "出差", "老家", "回老家",
)
_CARE_CONTEXT = (
    "在吗", "在么", "在不在", "早", "早安", "早上好", "中午好", "下午好", "晚上好", "晚安",
    "嗨", "hi", "hello", "哈喽", "忙吗", "忙不忙", "最近", "好久", "回来了", "下班",
    "休息", "周末", "在干嘛", "在忙啥", "睡了吗",
)
_CARE_RESOLVE = ("好多了", "好些了", "好了", "没事了", "恢复了", "缓过来", "缓过神", "睡饱了", "不累了", "好起来")
_CARE_TASK_WORDS = (
    "报告", "分析", "巡航", "客户", "代码", "bug", "部署", "生成", "帮我", "怎么", "如何",
    "为什么", "文件", "脚本", "数据", "掘金", "趋势", "改一下", "写个", "做个", "报价",
)
_CARE_MATURE_H = 18.0        # 首次提到后 · 至少隔这么久才成熟(不在同场对话里追)
_CARE_COOLDOWN_H = 72.0      # 同一条回访过后 · 这么久内不再提
_CARE_MAX_SURFACE = 2        # 一条最多主动回访 2 次 · 之后放手
_CARE_EXPIRE_H = 24 * 12     # 12 天没动静就过期丢弃


def _care_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _care_parse(s: str):
    try:
        return datetime.strptime(s or "", "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _care_load() -> dict:
    try:
        d = json.loads(_CARE_STATE.read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("items"), list):
            return d
    except Exception:
        pass
    return {"items": [], "last_nudge_date": ""}


def _care_save(d: dict) -> None:
    try:
        _CARE_STATE.parent.mkdir(parents=True, exist_ok=True)
        # 社区 7/31 · Bug #8 · Defender 瞬态锁防护
        try:
            from workers.safe_write import robust_write_json
            robust_write_json(_CARE_STATE, d, backup=False)
            return
        except ImportError:
            pass
        _CARE_STATE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def note_care_signals(message: str) -> None:
    """每轮跑一遍(便宜)· BRO 提到身体/情绪/大生活节点 → 记一个"待回访候选"。

    同信号再次出现 = BRO 还在这事上 → 刷新成熟钟、清回访计数(别在他正说时插嘴回访)。
    命中"好多了/没事了"等 → 放手最近一条(已解决就别再回访)。只写状态·不注入任何 token。
    """
    msg = (message or "").strip()
    if len(msg) < 2:          # 与 casual 一致:短情绪爆发也要接住
        return
    low = msg.lower()
    hit = next((s for s in _CARE_SIGNALS if (s in msg) or (s in low)), None)
    if hit and _is_tech_noise(msg, low):
        hit = None          # 信号嵌在技术话里 → 不是情感透露·不记回访候选(防几天后尬回访)
    resolved = any(r in msg for r in _CARE_RESOLVE)
    if not hit and not resolved:
        return
    d = _care_load()
    items = d.get("items") or []
    if resolved and items:
        items = items[:-1]          # 最近一条视为已被 BRO 亲口交代好了 → 放手
        d["items"] = items
        _care_save(d)
        if not hit:
            return
    if hit:
        snippet = msg if len(msg) <= 60 else msg[:60] + "…"
        for it in items:
            if it.get("signal") == hit:
                it.update(first_ts=_care_stamp(), text=snippet, surfaced_ts="", surfaced_count=0)
                break
        else:
            items.append({"signal": hit, "text": snippet, "first_ts": _care_stamp(),
                          "surfaced_ts": "", "surfaced_count": 0})
        d["items"] = items[-20:]
        _care_save(d)


def _expire_care(items: list, now: datetime) -> tuple[list, bool]:
    """丢弃 12 天没动静的候选。返回 (保留列表, 是否有变化)。"""
    kept, changed = [], False
    for it in items:
        ft = _care_parse(it.get("first_ts"))
        if ft and (now - ft).total_seconds() > _CARE_EXPIRE_H * 3600:
            changed = True
            continue
        kept.append(it)
    return kept, changed


def _find_ripe_care(items: list, now: datetime, *, need_no_proactive: bool = False):
    """挑一个成熟 + 过冷却 + 没超回访上限的候选。need_no_proactive=主动侧专用·
    额外要求这条从没被主动关心过(单候选主动最多一次)。无则返 None。"""
    for it in items:
        if it.get("surfaced_count", 0) >= _CARE_MAX_SURFACE:
            continue
        if need_no_proactive and it.get("proactive_ts"):
            continue
        ft = _care_parse(it.get("first_ts"))
        if not ft or (now - ft).total_seconds() < _CARE_MATURE_H * 3600:
            continue
        st = _care_parse(it.get("surfaced_ts"))
        if st and (now - st).total_seconds() < _CARE_COOLDOWN_H * 3600:
            continue
        return it
    return None


def care_followup_hint(message: str) -> str:
    """被动侧:有"成熟"的待回访候选 + 当前是闲聊/打招呼语境 → 给一条软回访提示(每天最多一次)。

    语境不合适(在干正事)一律不给。给出的也只是建议·OPUS 可判断当下不合适而略过。
    与主动侧(mature_care_candidate)共享 care_followups.json 状态·同日/72h 内绝不双重关心。
    """
    msg = (message or "").strip()
    if len(msg) < 2:
        return ""
    low = msg.lower()
    has_ctx = any((c in msg) or (c in low) for c in _CARE_CONTEXT)
    has_task = any((w in msg) or (w in low) for w in _CARE_TASK_WORDS)
    casual = has_ctx or (len(msg) <= 16 and not has_task)
    if not casual:
        return ""
    d = _care_load()
    items = d.get("items") or []
    if not items:
        return ""
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    if d.get("last_nudge_date") == today:
        return ""       # 一天全局最多关心一次(被动+主动共享)
    items, changed = _expire_care(items, now)
    ripe = _find_ripe_care(items, now)
    if not ripe:
        if changed:
            d["items"] = items
            _care_save(d)
        return ""
    ripe["surfaced_ts"] = _care_stamp()
    ripe["surfaced_count"] = ripe.get("surfaced_count", 0) + 1
    d["items"] = items
    d["last_nudge_date"] = today
    _care_save(d)
    ft = _care_parse(ripe.get("first_ts"))
    days = int((now - ft).total_seconds() // 86400) if ft else 0
    when = f"{days} 天前" if days >= 1 else "前些时候"
    return (
        "\n\n=== 温柔回访 · daemon 自动提示 (别复述这段) ===\n"
        f"BRO {when}提过「{ripe.get('text', '')}」(身体 / 心情类信号)· 之后没再提起。\n"
        "**若这轮语境自然(在闲聊 / 打招呼)· 可以轻轻关心一句**(好点没 / 那阵子缓过来没)· 一句就够、别追问。\n"
        "红线:只要语境稍不合适(在干正事 / 技术讨论 / BRO 有明确任务)就**当没看到·别提**。"
        "别显得在查户口·别硬 callback。关心是顺势·不是打卡。"
    )


def mature_care_candidate() -> Optional[dict]:
    """主动侧(proactive_call 用)· 找一个成熟、且从没被主动关心过的 care 候选。只读不认领。

    共享每日上限:今天已因 care 关心过(任一路径)→ 返回 None(防同日双重关心)。
    返回 {signal, text, days, when} 或 None。认领在投递成功后由 mark_care_surfaced 完成。
    """
    d = _care_load()
    now = datetime.now(timezone.utc)
    if d.get("last_nudge_date") == now.strftime("%Y-%m-%d"):
        return None
    items, _changed = _expire_care(d.get("items") or [], now)
    ripe = _find_ripe_care(items, now, need_no_proactive=True)
    if not ripe:
        return None
    ft = _care_parse(ripe.get("first_ts"))
    days = int((now - ft).total_seconds() // 86400) if ft else 0
    return {
        "signal": ripe.get("signal", ""),
        "text": ripe.get("text", ""),
        "days": days,
        "when": f"{days} 天前" if days >= 1 else "前些时候",
    }


def mark_care_surfaced(signal: str, *, proactive: bool = False) -> None:
    """认领一个 care 候选(投递成功后调)·记 surfaced_ts + count++ + 今日已关心。
    proactive=True 额外记 proactive_ts(单候选主动最多一次)·防被动侧再补一刀。"""
    if not signal:
        return
    d = _care_load()
    items = d.get("items") or []
    stamp = _care_stamp()
    for it in items:
        if it.get("signal") == signal:
            it["surfaced_ts"] = stamp
            it["surfaced_count"] = it.get("surfaced_count", 0) + 1
            if proactive:
                it["proactive_ts"] = stamp
            break
    else:
        return
    d["items"] = items
    d["last_nudge_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _care_save(d)


# ── P2/P3 · turn 结束反思 ─────────────────────────────────────────
# ── git 欠账对账 (wish-0f8e0ea3 · 铁律 9 第四问的代码闸) ─────────────
# 设计哲学: 验收信号是瞬时事件·漏接就没了; 但「分支欠账」是持久状态·永不消失。
# 所以不靠词表赌『每个验收信号都被接住』·靠状态对账赌『漏了下次也能翻出来』。
# 干了活的 turn 结束时顺带查一次 (只读 git · <200ms) · 有欠账就塞进收尾提示。
# 冷却 1h: 同一欠账签名不重复烦; 签名变了 (欠账增减/换分支) 立刻重提。

_DEBT_NUDGE_COOLDOWN_SEC = 3600.0
_last_debt_nudge: dict = {"sig": "", "ts": 0.0}


def _git_debt() -> Optional[dict]:
    """查 git 欠账 (只读 · best-effort)。

    返回 None = 无欠账或查询失败; dict = {branch, ahead, dirty}。
    ahead = 当前分支领先 master 的 commit 数 (在 master 上恒 0——散改已在主干);
    dirty = 工作区未提交改动数。
    2026-07-29 BRO 拍板: 复用 git_ops.git_debt_detail (含 demo/临时文件豁免过滤),
    亮灯 / 收尾对账 / 面板三处永远同一事实源 · 改规则只改 git_ops 一处。
    """
    try:
        from workers.git_ops import git_debt_detail  # 惰性 import 防循环
        d = git_debt_detail()
        if not d.get("debt"):
            return None
        return {"branch": d["branch"], "ahead": d["ahead"], "dirty": d["dirty"]}
    except Exception as e:
        logger.debug("_git_debt failed: %s", e)
        return None


def _debt_should_nudge(sig: str) -> bool:
    """同一欠账签名冷却 1h 内不重复提醒; 签名变了立刻重提 (返回 True 并记录)。"""
    now = datetime.now(timezone.utc).timestamp()
    if sig != _last_debt_nudge["sig"] or now - _last_debt_nudge["ts"] > _DEBT_NUDGE_COOLDOWN_SEC:
        _last_debt_nudge["sig"] = sig
        _last_debt_nudge["ts"] = now
        return True
    return False


def _debt_text(debt: dict) -> str:
    parts = []
    if debt["ahead"]:
        parts.append(f"分支 `{debt['branch']}` 领先 master {debt['ahead']} 个 commit 未合")
    if debt["dirty"]:
        parts.append(f"工作区 {debt['dirty']} 个文件未提交")
    return " · ".join(parts)


_DEBT_SUGGESTION = {
    "tool": "worktree_status",
    "q": "有未合并 commit / 未提交改动? 查一下 · 该合走 safe_merge",
}


def turn_end_report(tools: Optional[list] = None) -> Optional[dict]:
    """一轮 chat 结束后调。返回 None = 不必提示;返回 dict = 该提醒收尾沉淀。

    触发: 副作用工具被调 ≥ 阈值 (真在干活) · 且本回合没调任何沉淀工具。
    例外: 即使已沉淀 · 若有 git 欠账 (铁律 9 第四问) 也返回欠账-only 提示。
    返回 dict 给前端渲染收尾提示卡 + 落对账台账。
    """
    t = tools if tools is not None else tools_called()
    se_calls = [x for x in t if x in SIDE_EFFECT_TOOLS]
    if len(se_calls) < _TURN_END_MIN_SIDE_EFFECTS:
        return None

    # ④ 欠账对账: 干了活的 turn 顺带查 git (跟沉不沉淀无关——漏接的验收信号靠它捞回来)
    debt_hint = None
    debt = _git_debt()
    if debt:
        sig = f"{debt['branch']}|{debt['ahead']}|{debt['dirty']}"
        if _debt_should_nudge(sig):
            debt_hint = _debt_text(debt)

    if did_sink(t):
        if debt_hint:
            return {
                "kind": "closure_hint",
                "side_effect_tools": sorted(set(se_calls)),
                "side_effect_calls": len(se_calls),
                "suggestions": [_DEBT_SUGGESTION],
                "text": "git 欠账对账: " + debt_hint + "。收尾第四问: 要不要处理?",
            }
        return None  # 已沉淀且无欠账 · 不打扰

    se_kinds = sorted(set(se_calls))
    suggestions = [
        {"tool": "update_bro_note", "q": "BRO 这次透露新信号了吗?"},
        {"tool": "extract_playbook", "q": "这次的操作流程 / 踩坑值得复用吗?"},
        {"tool": "wish_add", "q": "发现自己的能力缺口了吗?"},
    ]
    text = (
        "这回合你动了 " + "、".join(se_kinds)
        + f" (共 {len(se_calls)} 次) · 但没沉淀任何东西。要不要过一遍收尾三问?"
    )
    if debt_hint:
        suggestions.append(_DEBT_SUGGESTION)
        text += " 另 · git 欠账: " + debt_hint + "。"
    return {
        "kind": "closure_hint",
        "side_effect_tools": se_kinds,
        "side_effect_calls": len(se_calls),
        "suggestions": suggestions,
        "text": text,
    }


def ledger_hint(session_id: str) -> str:
    """③ 抗套娃 · 本会话活跃任务账本 → 每轮无损回灌进易变尾巴。无活跃账本返回空串。

    账本【不进语义压缩】(压缩发生在 messages 层·这是 system_suffix 层)·所以哪怕
    久远对话被摘要掉·"哪条路通了/死了/做了什么决策"这些结论一定还在 OPUS 眼前。
    """
    try:
        from workers import task_ledger as _tl
        return _tl.render_hint(session_id)
    except Exception:
        return ""


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
        # 社区 7/31 · Bug #8 · Defender 瞬态锁防护 (hints append)
        try:
            from workers.safe_write import robust_open_append
            with robust_open_append(HINTS_FILE) as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except ImportError:
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
