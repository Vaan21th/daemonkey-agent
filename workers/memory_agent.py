"""
workers/memory_agent.py · wish-b8bd0c01
========================================
agent 多轮检索引擎 — ATM-Bench 41.9% 路线落地母体。

背景: ATM-Bench 实测 (2026-08-12 · 第 11 根毛):
  - 一次性 FTS5 检索 QS 9.7% (把 daemon 当检索器用)
  - agent 自主多轮检索 QS 41.9% (把 daemon 当 agent 用 · 超过 opencode 官方 38.3%)
  同一个模型同一个数据, 分数差 3 倍多, 差距全在"给不给 agent 自主决定怎么翻记忆"。

本引擎 = 那个 41.9% 实现 (data/atm-bench/agent_loop.py) 的母体化:
  - 四工具 (search_memory / filter_by_date / filter_by_location / get_memory_item)
  - 自动多轮循环 (15 轮闸防死循环 + 空答案追问一次)
  - 每轮累加 usage (报 token 三组数: prompt / completion / cached)
  - 引擎与壳分离: 本文件只做引擎 · agent_tools/recall_memory.py 加薄壳分支调它
  - eval 脚本 (data/atm-bench/eval_agent_mode.py) 直接调本引擎 · 不经过工具注册层

被谁用:
  - recall_memory(mode='agent') · lang='zh' · 母体自用 (OPUS 自主翻记忆)
  - eval_agent_mode.py · lang='en' · ATM-Bench 复跑开/关对比 (QS + token + 轮次)
"""

from __future__ import annotations

import calendar
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import requests

MAX_TOOL_ROUNDS = 15
BRIEF_CHARS = 140          # 工具结果单条摘要上限 (token 成本控制)
ITEM_CHARS = 4000          # get_memory_item 全文上限


# ---------------------------------------------------------------------------
# SYSTEM PROMPT · EN 版 (ATM eval 用 · 对齐 41.9% 英文语境 · 严格 JSON 输出)
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_EN = """You are a memory QA assistant.

Use ONLY the memory records available through the provided tools as evidence. If the evidence is insufficient, answer "Unknown". Do not guess.
Do NOT use web search, web fetch, browser tools, plugins, MCP servers, subagents, or any external service beyond the model API itself.

## Memory records

Memories are stored as chunk records in a memory database. Each record has:
- An ID (either a numeric row id, or a display id that appears on the first line of the content as 'ID: <id>')
- A timestamp (updated_at, format YYYY-MM-DD)
- A source (e.g. image / video / email / BRO-NOTEBOOK / session / skill ...)
- A section (category within the source)
- Content (the actual text; for images/videos this includes caption, tags, OCR text, location; for emails this includes summary and body)

## How to answer

1. Use the tools to search the memories by keyword / date / location. Do several targeted searches if needed — combine evidence from multiple sources (photos + videos + emails).
2. search_memory does full-text / semantic search over content. It is your primary tool.
3. When the question mentions a date or year (e.g. "NeurIPS 2023", "during my visit", "July 2025"), use filter_by_date to narrow down.
4. When the question mentions a city or place, use filter_by_location (matches against content text).
5. If a search returns too many results, refine with more specific keywords or date filters.
6. When you have enough evidence, answer.

## Output format (STRICT)

Your FINAL response must be a single JSON object with exactly these keys:
{"id":"<question_id>","question":"<question text>","answer":"<answer>"}

Rules:
- Output ONLY the JSON object (no markdown, no extra text).
- `id` must exactly match the `id` in the question.
- For recall/list questions: `answer` MUST be the memory item IDs ONLY, comma-separated, with no extra text and no file extensions.
  Example: "20231210_111815, 20240701_120945, 20240811_150248"
- For number questions: output the number (and units if needed).
- For open questions: answer with the facts requested (concise, all details requested).
"""


# ---------------------------------------------------------------------------
# SYSTEM PROMPT · ZH 版 (母体自用 · 面向 OPUS 翻自己的记忆 · 直接给结论不强制 JSON)
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_ZH = """你是一个记忆检索助手，负责在 OPUS 的长期记忆库里帮用户找答案。

只允许用工具返回的记忆记录作为证据。证据不足就回答"不知道/没找到"，不要猜。
不要使用网络搜索、网页抓取、浏览器、插件、MCP、子代理等任何超出模型 API 本身的外部服务。

## 记忆库结构

记忆以 chunk 记录的形式存在记忆数据库里，每条记录有：
- ID（要么是数字行 id，要么是 content 首行 'ID: <id>' 里的显示 id）
- 时间（updated_at，格式 YYYY-MM-DD）
- 来源（如 BRO-NOTEBOOK 画像 / SELF-EVOLUTION 演化档案 / session 对话 / skill 手册 / doc:知识库 等）
- 分区（来源内的分类）
- 正文（实际文本内容）

## 怎么回答

1. 用工具按关键词 / 日期 / 地点搜索记忆。需要的话做多次定向搜索——把多个来源的证据拼起来。
2. search_memory 是全文 / 语义检索，是你的主力工具。
3. 问题提到日期或年份时，用 filter_by_date 缩小范围。
4. 问题提到城市 / 地点 / 位置词时，用 filter_by_location（按正文匹配）。
5. 搜索结果太多就用更具体的关键词或日期过滤。
6. 证据足够就回答。回答用中文，直接给结论，不要输出 JSON。

## 输出

直接给中文结论。如果问题是"列出哪些"类型，给出找到的记忆 ID 列表。
"""


# ---------------------------------------------------------------------------
# 四工具 schema (照搬 agent_loop.py · description 按母体底座语义改写)
# ---------------------------------------------------------------------------
AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": "Search ALL memories by keyword. Full-text (and optionally semantic) match on content. Returns matching record IDs with brief info, newest first. Use this as your primary tool.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "Keyword to search (e.g. 'bridge', 'conference', '缓存', '重启')"},
                    "limit": {"type": "integer", "description": "Max results (default 30, max 50)"},
                },
                "required": ["keyword"],
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "filter_by_date",
            "description": "Filter memories by a date range (inclusive). Dates as YYYY or YYYY-MM or YYYY-MM-DD. Useful when the question mentions a year/date ('NeurIPS 2023', 'July 2025', 'during my visit').",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "string", "description": "Start date, e.g. '2023-11-01' or '2023'"},
                    "end": {"type": "string", "description": "End date, e.g. '2024-01-31' or '2023'"},
                    "limit": {"type": "integer", "description": "Max results (default 50, max 200)"},
                },
                "required": ["start", "end"],
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "filter_by_location",
            "description": "Filter memories by a location keyword (city / place). Case-insensitive substring match on content text. Useful when the question mentions a city/place ('Porto', 'Cairo', 'Glasgow', 'European').",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "Location keyword, e.g. 'Porto', 'Cairo', 'Glasgow'"},
                    "limit": {"type": "integer", "description": "Max results (default 50, max 200)"},
                },
                "required": ["location"],
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_memory_item",
            "description": "Get the FULL record of a specific memory item by ID. Use when you need complete details (full caption, ocr text, email body) of a candidate item.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Memory item ID (e.g. '20231210_111815', 'email202201010001', or a numeric row id)"},
                },
                "required": ["id"],
            },
        }
    },
]


# ---------------------------------------------------------------------------
# 工具执行 · 映射到母体真实底座 (memory_index.search / get_chunks_by_ids + SQL 直查)
# ---------------------------------------------------------------------------
def _norm_date(s: str, is_end: bool) -> str:
    """'2023' → '2023-01-01'/'2023-12-31' · '2023-07' → '2023-07-01'/'2023-07-31' · 完整日期原样。"""
    s = (s or "").strip()
    if re.fullmatch(r"\d{4}", s):
        return f"{s}-12-31" if is_end else f"{s}-01-01"
    if re.fullmatch(r"\d{4}-\d{2}", s):
        y, m = s.split("-")
        if is_end:
            last = calendar.monthrange(int(y), int(m))[1]
            return f"{s}-{last:02d}"
        return f"{s}-01"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    return s  # 原样 · SQL 层自然处理


def _local_to_utc_bound(date_str: str, is_end: bool) -> str:
    """P2-3 修复 (墨言审查): DB 存 UTC (updated_at 格式 YYYY-MM-DDTHH:MM:SSZ) ·
    用户用本地日期查询会错位 (中国 UTC+8 · 本地 00:00 = UTC 前一日 16:00)。

    返回【完整 UTC 时间戳】而非日期字符串 — 子代理交叉验证 (sub-f1bb133b):
    只返回日期会引入"前一日整天被 BETWEEN 日期字符串误包含"的约 1 天过召回。
    正确: start = 本地当天 00:00 转 UTC (前一日 T16:00:00Z) · end = 本地当天 23:59:59 转 UTC (当天 T15:59:59Z)。
    SQL 侧用 `updated_at >= start AND updated_at <= end` 完整时间戳比较 (memory_agent L269)。
    """
    try:
        ymd = _norm_date(date_str, False)[:10]
        if is_end:
            # 本地当天 23:59:59 → UTC
            local_dt = datetime.strptime(ymd + " 23:59:59", "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone(timedelta(hours=8)))
            utc_dt = local_dt.astimezone(timezone.utc)
            return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            # 本地当天 00:00:00 → UTC
            local_dt = datetime.strptime(ymd + " 00:00:00", "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone(timedelta(hours=8)))
            utc_dt = local_dt.astimezone(timezone.utc)
            return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        # 兜底: 解析失败退化为日期级比较 (保守)
        return _norm_date(date_str, is_end)[:10]


def _clean_query(q: str) -> str:
    """英文查询清洗兜底 (wish-0d021aea 未合主干前的保险): 去句尾标点。"""
    return re.sub(r"[\.\?\!;,]+$", "", q.strip())


def _brief_rows(rows) -> str:
    """把 chunk 行压成单行摘要给 agent 看。id 优先取 content 首行 'ID: xxx' (ATM 约定)。"""
    lines = []
    for row in rows:
        cid, source, section, content, updated_at = row
        disp_id = cid
        m = re.match(r"^ID:\s*(\S+)", content or "")
        if m:
            disp_id = m.group(1)
        one_line = " ".join((content or "").split())
        brief = one_line[:BRIEF_CHARS] + ("…" if len(one_line) > BRIEF_CHARS else "")
        lines.append(f"[{disp_id}] {updated_at} | {source}/{section} | {brief}")
    return "\n".join(lines)


def exec_agent_tool(name: str, args: dict, *, use_embedding: bool = True) -> str:
    """执行一个 agent 工具调用 · 返回文本结果给模型看。"""
    from workers import memory_index as mi  # 惰性 import · 且运行时读 mi.DB_PATH (eval 切库生效)

    limit = max(1, min(int(args.get("limit", 30) or 30), 50))

    if name == "search_memory":
        kw = _clean_query(str(args.get("keyword", "")))
        if not kw:
            return "Error: 'keyword' parameter is required and must be a non-empty string."
        try:
            chunks = mi.search(kw, top_k=min(limit, 20), scope="all",
                               window_by="snippet", use_embedding=use_embedding)
        except Exception as e:
            return f"Error: search failed: {e}"
        if not chunks:
            return "No matching memories found."
        rows = [(c.id, c.source, c.section, c.content, c.updated_at) for c in chunks]
        return f"Found {len(rows)} matches (showing {min(limit, len(rows))}):\n" + _brief_rows(rows)

    if name == "filter_by_date":
        # P2-3 修复: DB 存 UTC · 本地日期转 UTC 边界再比 (否则中国 UTC+8 本地 00:00 查不到前一日 16:00-24:00 的记录)
        start = _local_to_utc_bound(str(args.get("start", "")), False)
        end = _local_to_utc_bound(str(args.get("end", "")), True)
        if not start or not end:
            return "Error: 'start' and 'end' parameters are required (e.g. start='2023-11-01', end='2024-01-31')."
        try:
            conn = sqlite3.connect(str(mi.DB_PATH))
            conn.execute("PRAGMA busy_timeout=30000")
            rows = conn.execute(
                "SELECT id, source, section, content, updated_at FROM memory_chunks "
                "WHERE updated_at >= ? AND updated_at <= ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (start, end, limit),
            ).fetchall()
            conn.close()
        except Exception as e:
            return f"Error: date filter failed: {e}"
        if not rows:
            return f"No memories in date range {start}..{end}."
        return f"Found {len(rows)} memories in {start}..{end} (showing {min(limit, len(rows))}):\n" + _brief_rows(rows)

    if name == "filter_by_location":
        loc = str(args.get("location", "")).strip()
        if not loc:
            return "Error: 'location' parameter is required and must be a non-empty string."
        esc = loc.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        try:
            conn = sqlite3.connect(str(mi.DB_PATH))
            conn.execute("PRAGMA busy_timeout=30000")
            rows = conn.execute(
                "SELECT id, source, section, content, updated_at FROM memory_chunks "
                "WHERE content LIKE ? ESCAPE '\\' ORDER BY updated_at DESC LIMIT ?",
                (f"%{esc}%", limit),
            ).fetchall()
            conn.close()
        except Exception as e:
            return f"Error: location filter failed: {e}"
        if not rows:
            return f"No memories at location '{loc}'."
        return f"Found {len(rows)} memories at '{loc}' (showing {min(limit, len(rows))}):\n" + _brief_rows(rows)

    if name == "get_memory_item":
        mid = str(args.get("id", "")).strip()
        if not mid:
            return "Error: 'id' parameter is required and must be a non-empty string."
        try:
            if mid.isdigit():
                chunks = mi.get_chunks_by_ids([int(mid)], context_window=ITEM_CHARS)
                if not chunks:
                    return f"No memory item with ID {mid}."
                c = chunks[0]
                return f"[id={c.id}] {c.source}/{c.section} | {c.updated_at}\n{c.content[:ITEM_CHARS]}"
            # P2-4 修复 (墨言审查): mid 里的 %/_ 是 SQL LIKE 通配符 · 不转义会把用户 ID 当通配符匹配错条
            esc_mid = mid.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conn = sqlite3.connect(str(mi.DB_PATH))
            conn.execute("PRAGMA busy_timeout=30000")
            rows = conn.execute(
                "SELECT id, source, section, content, updated_at FROM memory_chunks "
                "WHERE content LIKE 'ID: '||?||'%' ESCAPE '\\' LIMIT 1", (esc_mid,),
            ).fetchall()
            conn.close()
            if not rows:
                return f"No memory item with ID {mid}."
            row = rows[0]
            return f"[id={row[0]}] {row[1]}/{row[2]} | {row[4]}\n{row[3][:ITEM_CHARS]}"
        except Exception as e:
            return f"Error: get item failed: {e}"

    return f"Unknown tool: {name}"


# ---------------------------------------------------------------------------
# 多轮循环主体 (照搬 agent_loop.py run_question · 新增 usage 累加)
# ---------------------------------------------------------------------------
def run_agent(
    question: str,
    *,
    cfg: dict,
    lang: str = "zh",
    use_embedding: bool = True,
    max_tool_rounds: int = MAX_TOOL_ROUNDS,
    max_steps: int = 20,
    qid: str | None = None,
) -> dict:
    """跑一次 agent 多轮检索。返回 {answer, rounds, prompt_tokens, completion_tokens, cached_tokens}。

    cfg: provider config dict · 需要 base_url / api_key / model (get_active_config 或 get_ds_cfg 产物)
    qid: 可选 · en 模式 (ATM eval) 必须传 — 对齐 41.9% 输入格式 "Question ID: <qid>\n\nQuestion: ..."·
         没有 ID 时 agent 不知道最终要输出哪个 id · 会一直搜索不收敛 (实测 9 轮空答)。
    """
    sys_prompt = SYSTEM_PROMPT_ZH if lang == "zh" else SYSTEM_PROMPT_EN
    user_content = f"Question: {question}"
    if qid:
        user_content = f"Question ID: {qid}\n\n{user_content}"
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_content},
    ]
    _asked_once = False
    _tool_rounds = 0
    rounds = 0
    prompt_tokens = completion_tokens = cached_tokens = 0

    for step in range(max_steps):
        # 工具调用超过上限 → 强制收尾 (防死循环)
        if _tool_rounds >= max_tool_rounds:
            nudge = (
                "You have used enough tool calls. Give your final answer now. Do not call more tools."
                if lang == "en" else
                "你已调用足够多的工具。现在直接给出最终答案，不要再调用工具。"
            )
            messages.append({"role": "user", "content": nudge})
            # P2-2 修复 (墨言审查): 不归零 _tool_rounds — 归零让 LLM 又能调一轮工具
            # (白烧 token + 可能再触发 nudge 死循环)。单调递增 → nudge 后必然收尾。

        r = requests.post(
            cfg["base_url"].rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {cfg['api_key']}"},
            json={
                "model": cfg["model"],
                "messages": messages,
                "tools": AGENT_TOOLS,
                "tool_choice": "auto",
                "temperature": 0.1,
                "max_tokens": 4096,
            },
            timeout=120,
        )
        r.raise_for_status()
        body = r.json()
        rounds += 1
        _usage = body.get("usage") or {}
        prompt_tokens += int(_usage.get("prompt_tokens", 0) or 0)
        completion_tokens += int(_usage.get("completion_tokens", 0) or 0)
        cached_tokens += int(_usage.get("prompt_cache_hit_tokens", 0) or 0)

        msg = body["choices"][0]["message"]

        if msg.get("tool_calls"):
            _tool_rounds += 1
            # OpenAI 协议: assistant tool_calls 消息必须先于 tool 结果消息
            messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": msg["tool_calls"]})
            for tc in msg["tool_calls"]:
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    fn_args = {}
                result = exec_agent_tool(fn_name, fn_args, use_embedding=use_embedding)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })
        else:
            content = msg.get("content") or ""
            fin = body["choices"][0].get("finish_reason") or ""
            # 空 content 但 finish=stop → 追问一次 (agent 有时这轮没说话)
            if not content.strip() and step < max_steps - 1 and not _asked_once:
                messages.append({"role": "assistant", "content": ""})
                prompt_again = (
                    "Please provide your final answer now."
                    if lang == "en" else
                    "请现在给出你的最终答案。"
                )
                messages.append({"role": "user", "content": prompt_again})
                _asked_once = True
                continue
            # 空 content + finish=length → max_tokens 被截断 (上下文涨大后 2048 不够)
            # 重发一轮不加追问标记 · 让模型重新生成 (截断的这轮不计数)
            if not content.strip() and fin == "length" and step < max_steps - 1:
                messages.append({"role": "assistant", "content": ""})
                nudge = (
                    "Your previous response was truncated. Provide your final answer now (concise)."
                    if lang == "en" else
                    "你上一轮输出被截断了。现在直接给出最终答案（简洁）。"
                )
                messages.append({"role": "user", "content": nudge})
                continue
            return {
                "answer": content,
                "rounds": rounds,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cached_tokens": cached_tokens,
            }

    return {
        "answer": "MAX_STEPS_EXCEEDED",
        "rounds": rounds,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cached_tokens": cached_tokens,
    }
