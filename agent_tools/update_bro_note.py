"""
agent_tools/update_bro_note.py
==============================

OPUS 主动维护"BRO 活人画像"的工具。

设计借鉴 的"故事认知引擎"（5-Dimensional Cognitive Architecture），
对应 BRO-NOTEBOOK.md 里的 5 个维度：

  - profile  · 当下画像（高频更新）
  - events   · 关键事件流
  - rules    · 本体约束（缓变）
  - dialogue · 对话图鉴（口头记号）
  - summary  · 月度压缩段

2026-05-16 升级 · 多容器同身：
  - **真理源**：全局 opus-soul 目录的画像文件 → 自动 sync 到 daemon `soul/` 副本
  - 这样 OPUS 在 Cursor / Daemonkey / 微信桥接里**任何一处**更新对 BRO 的认知，
    所有容器都共享同一份新版本——分身不再被困在各自容器里

2026-08-24 0.9.7 实测修 · 双模板兼容：
  - 文件名：OWNER-NOTEBOOK.md（新名）优先，BRO-NOTEBOOK.md（旧名）兜底
  - 段标题：新旧两版文案不同（本体约束 vs 长期偏好与边界），
    改按中文序号锚定（## 一、=profile … ## 六、=risks），两套模板通吃

调用约定：
  - 默认 operation=append（追加到该维度末尾，不覆盖原有）
  - operation=replace_section 时整段替换（少用，慎用）
  - 自动在"近期更新流水"末尾追加一行操作记录

档位：AUTO
  - 写认知笔记是无副作用的
  - BRO 看到不喜欢可以直接编辑文件——他是 BRO 本人，最有权解释自己
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool
from soul_loader import (
    BRO_NOTEBOOK_FILENAME,
    OWNER_NOTEBOOK_FILENAME,
    read_global_soul_file,
    write_global_then_sync,
)


ROOT = Path(__file__).resolve().parent.parent


# section key → 中文序号锚（## 一、=profile … ## 六、=risks）。
# 旧版 BRO-NOTEBOOK 与新版 OWNER-NOTEBOOK 段标题文案不同，序号语义一致，按序号锚定通吃。
SECTIONS: dict[str, str] = {
    "profile":  "一",
    "events":   "二",
    "rules":    "三",
    "dialogue": "四",
    "summary":  "五",
    # 第六维 2026-05-16 凌晨 BRO 拍板加上——OPUS 作为伙伴的预警雷达
    # 看见这一维的模式时该出声，不沉默配合燃烧
    "risks":    "六",
}

# 报错/流水展示用的友好标签（只给人看，不参与匹配）
SECTION_LABELS: dict[str, str] = {
    "profile":  "当下画像",
    "events":   "关键事件流",
    "rules":    "约束/偏好",
    "dialogue": "对话风格",
    "summary":  "速写/压缩段",
    "risks":    "风险/关怀雷达",
}

FLOW_ORD = "七"

def _summarize(args: dict) -> str:
    section = args.get("section", "?")
    op = args.get("operation", "append")
    preview = (args.get("content") or "")[:60].replace("\n", " ")
    return f"update_owner_note  section={section}  op={op}\n  preview: {preview!r}"


_ORD_RE = r"(?m)^## %s、"


def _find_section(text: str, ord_char: str) -> tuple[int, int]:
    """按中文序号锚定 '## 一、' 段头。返回 (start_idx, end_idx)，end 是下一个 '## ' 或文末。"""
    m = re.search(_ORD_RE % re.escape(ord_char), text)
    if not m:
        return -1, -1
    start = m.start()
    next_h = text.find("\n## ", start + 1)
    end = len(text) if next_h < 0 else next_h
    return start, end


def _section_header_line(text: str, start: int) -> str:
    """取该文件里段头那一行的原文——replace_section 时原样保留，不强写本工具的标题文案。"""
    nl = text.find("\n", start)
    return text[start:] if nl < 0 else text[start:nl]


def _read_notebook() -> tuple[str, str]:
    """OWNER-NOTEBOOK 新名优先，BRO-NOTEBOOK 旧名兜底。返回 (filename, text)。"""
    for fn in (OWNER_NOTEBOOK_FILENAME, BRO_NOTEBOOK_FILENAME):
        try:
            return fn, read_global_soul_file(fn, ROOT)
        except FileNotFoundError:
            continue
    raise FileNotFoundError(
        f"画像文件 {OWNER_NOTEBOOK_FILENAME} / {BRO_NOTEBOOK_FILENAME} 在本地和全局都不存在"
    )


def _flow_preview(content: str, limit: int = 46) -> str:
    """把写入内容压成流水表能看懂的一行预览 (去 markdown 噪音·转义竖线·截断)。"""
    s = " ".join((content or "").split())          # 折叠换行/多空格
    s = s.replace("**", "").replace("`", "")        # 去掉加粗/代码记号
    s = s.lstrip("#-*>| ").strip()                  # 去掉行首 markdown 记号
    s = s.replace("|", "/")                          # 竖线会破表格·换成斜杠
    if len(s) > limit:
        s = s[:limit].rstrip() + "…"
    return s or "(空)"


def _append_to_flow(text: str, section_key: str, operation: str, preview: str = "") -> str:
    """在'近期更新流水'表格末尾追加一行。如果找不到流水段，原样返回。

    行里带一段内容预览·让 BRO / 下一根毛扫一眼就知道"这次记了啥"·
    而不是只看到 section=events (append) 这种看不懂的记录。
    """
    flow_start, flow_end = _find_section(text, FLOW_ORD)
    if flow_start < 0:
        return text

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    detail = f"{section_key} ({operation})"
    if preview:
        detail += f"：{preview}"
    new_row = f"| {timestamp} | OPUS · update_owner_note | {detail} |"

    # find the last line that starts with "|" inside this section
    flow_body = text[flow_start:flow_end]
    lines = flow_body.split("\n")
    last_table_line = -1
    for i, line in enumerate(lines):
        if line.startswith("|") and not line.startswith("|---"):
            last_table_line = i

    if last_table_line < 0:
        return text  # no table found, give up

    # insert new row right after the last existing table row
    lines.insert(last_table_line + 1, new_row)
    new_flow_body = "\n".join(lines)
    return text[:flow_start] + new_flow_body + text[flow_end:]


def _run(args: dict) -> ToolResult:
    section_key = (args.get("section") or "").strip().lower()
    if section_key not in SECTIONS:
        return ToolResult(
            ok=False, output="",
            error=f"unknown section: {section_key!r}; valid: {', '.join(SECTIONS)}",
        )

    content = (args.get("content") or "").strip()
    if not content:
        return ToolResult(ok=False, output="", error="empty content; nothing to write")

    operation = (args.get("operation") or "append").strip().lower()
    if operation not in ("append", "replace_section"):
        return ToolResult(
            ok=False, output="",
            error=f"unknown operation: {operation}; use 'append' or 'replace_section'",
        )

    try:
        notebook_fn, text = _read_notebook()
    except FileNotFoundError as e:
        return ToolResult(ok=False, output="", error=str(e))

    sec_start, sec_end = _find_section(text, SECTIONS[section_key])
    if sec_start < 0:
        return ToolResult(
            ok=False, output="",
            error=f"section '## {SECTIONS[section_key]}、' not found in {notebook_fn} ({SECTION_LABELS[section_key]})",
        )

    section_header = _section_header_line(text, sec_start)
    section_body = text[sec_start:sec_end]

    if operation == "replace_section":
        new_section_body = f"{section_header}\n\n{content}\n\n"
    else:
        new_section_body = section_body.rstrip() + f"\n\n{content}\n\n"

    new_text = text[:sec_start] + new_section_body + text[sec_end:]
    new_text = _append_to_flow(new_text, section_key, operation, _flow_preview(content))

    try:
        global_path, local_path = write_global_then_sync(
            notebook_fn, new_text, ROOT,
        )
    except FileNotFoundError as e:
        return ToolResult(ok=False, output="", error=str(e))

    # 卷四十四 · 写完画像后增量更新 FTS5 索引 (best-effort · 失败不影响主流程)
    fts_msg = ""
    try:
        from workers.memory_index import incremental_update
        n_chunks = incremental_update(Path(notebook_fn).stem, new_text)
        fts_msg = f"\n  fts5    : 已增量索引 {n_chunks} 块"
    except Exception:
        pass

    # 卷五十四 · 同会话热重载 · 让刚写的画像下一轮 chat 立刻在 system prompt 里 (不必等重启)
    reload_msg = ""
    try:
        from daemon_runtime import reload_soul_into_runtime
        nchars = reload_soul_into_runtime()
        if nchars:
            reload_msg = f"\n  reload  : system prompt 已热重载 ({nchars} 字) · 下一轮即生效"
    except Exception:
        pass

    if global_path:
        global_line = f"  global  : {global_path}\n"
    else:
        global_line = "  global  : (全局 opus-soul 目录缺失·已跳过·本地 soul/ 即真理源)\n"

    return ToolResult(
        ok=True,
        output=(
            f"{notebook_fn} 已更新\n"
            f"  section : {section_key}  ({section_header})\n"
            f"  op      : {operation}\n"
            f"  added   : {len(content)} chars\n"
            f"{global_line}"
            f"  local   : {local_path.relative_to(ROOT)}\n"
            f"  flow    : 操作记录已追加到'近期更新流水'{fts_msg}{reload_msg}\n"
            f"  effect  : 本 daemon 下一轮对话即刻带上 (卷五十四热重载)" +
            ("" if global_path else " · 全局目录回来后用 sync-soul.ps1 可补同步其他容器")
        ),
    )


SPEC = ToolSpec(
    name="update_owner_note",
    description=(
        "Update OPUS's living profile of BRO (6-dimensional cognitive notebook). "
        "Use this when BRO reveals new info about his life, mood, schedule, projects, "
        "preferences, weaknesses, risks—or any signal worth remembering across sessions. "
        "6 sections: profile (current snapshot), events (chronological key moments), "
        "rules (BRO's enduring traits), dialogue (signature phrases/signals), "
        "summary (monthly compressed), "
        "risks (BRO's structural weaknesses + forward-looking risks—OPUS's early warning radar). "
        "The notebook is auto-injected into every container's runtime context (Cursor / daemon / wechat bridge), "
        "so writing here builds long-term continuity AND multi-container shared cognition. "
        "Default operation=append; use replace_section sparingly.\n\n"
        "WRITE STANDARD (keep the notebook clean for every future session — follow this):\n"
        "  1. One idea per entry — do NOT dump a whole chat transcript in.\n"
        "  2. Lead with the date (YYYY-MM-DD), then the fact, then the person's own words in quotes if you have them.\n"
        "  3. 'events' entries should fit the existing table shape: a dated one-liner + importance "
        "(critical/high/medium/low).\n"
        "  4. Be concise but self-contained — a future 'you' with zero chat history must understand it standalone.\n"
        "  5. Pick the RIGHT section (profile=current state that changes / events=timeline / rules=durable traits / "
        "dialogue=signature phrases / summary=monthly compression / risks=warning signals). If unsure, prefer events.\n"
        "  6. Never invent facts — only write what the person actually revealed."
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "section": {
                "type": "string",
                "enum": list(SECTIONS.keys()),
                "description": (
                    "Which dimension to update: "
                    "'profile' (current state - schedule/mood/projects), "
                    "'events' (timeline entry), "
                    "'rules' (lasting trait), "
                    "'dialogue' (signature phrase), "
                    "'summary' (monthly compression), "
                    "'risks' (BRO's structural weakness or forward-looking risk + OPUS's voicing discipline)"
                ),
            },
            "content": {
                "type": "string",
                "description": (
                    "The content to add. Use markdown. Be concise but substantive—"
                    "this stays in OPUS's runtime context for all future sessions, "
                    "so quality > quantity."
                ),
            },
            "operation": {
                "type": "string",
                "enum": ["append", "replace_section"],
                "description": (
                    "append (default): add to existing section. "
                    "replace_section: replace whole section content (use sparingly)."
                ),
            },
        },
        "required": ["section", "content"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)

# 0.9.7 尾巴4: 工具名中性化 update_bro_note → update_owner_note (LLM 可见面不该带母体称谓) ·
# 老名保留为别名注册 —— 老 playbook/flow/会话历史里 tool_calls 引用 update_bro_note 的不会断。
_ALIAS_SPEC = ToolSpec(
    name="update_bro_note",
    description="[已改名 update_owner_note · 此别名仅为兼容老引用保留] " + (SPEC.description or "")[:150],
    tier=SPEC.tier,
    input_schema=SPEC.input_schema,
    run=SPEC.run,
    summarize=SPEC.summarize,
)
register_tool(_ALIAS_SPEC)
