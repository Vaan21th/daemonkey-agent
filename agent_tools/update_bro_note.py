"""
agent_tools/update_bro_note.py
==============================

主动维护"用户活人画像"的工具。

多维认知笔记本结构，对应 OWNER-NOTEBOOK.md 里的维度：

  - profile  · 当下画像（高频更新）
  - events   · 关键事件流
  - rules    · 本体约束（缓变）
  - dialogue · 对话图鉴（口头记号）
  - summary  · 月度压缩段

真理源 · 本地 `soul/OWNER-NOTEBOOK.md`：
  - 写入本地 soul/ 的用户画像笔记
  - 笔记自动注入到每次对话的 system prompt → 跨 session 长期连续性
  - （若存在全局 opus-soul 目录则顺带同步一份，缺失即跳过，本地 soul/ 就是真理源）

调用约定：
  - 默认 operation=append（追加到该维度末尾，不覆盖原有）
  - operation=replace_section 时整段替换（少用，慎用）
  - 自动在"近期更新流水"末尾追加一行操作记录

档位：AUTO
  - 写认知笔记是无副作用的
  - 用户看到不喜欢可以直接编辑文件——他最有权解释自己
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool
from soul_loader import (
    OWNER_NOTEBOOK_FILENAME,
    read_global_soul_file,
    write_global_then_sync,
)


ROOT = Path(__file__).resolve().parent.parent


# section key → markdown header（必须和 OWNER-NOTEBOOK.md 里的标题一字不差）
SECTIONS: dict[str, str] = {
    "profile":  "## 一、当下画像 · Profile",
    "events":   "## 二、关键事件流 · Events",
    "rules":    "## 三、长期偏好与边界 · Rules",
    "dialogue": "## 四、对话风格 · Dialogue",
    "summary":  "## 五、一句话速写 · Summary",
    # 第六维：搭档的关怀雷达——看见他过度燃烧时该出声，不沉默配合
    "risks":    "## 六、关怀雷达 · Care Radar",
}

FLOW_HEADER = "## 七、近期更新流水"


def _summarize(args: dict) -> str:
    section = args.get("section", "?")
    op = args.get("operation", "append")
    preview = (args.get("content") or "")[:60].replace("\n", " ")
    return f"update_bro_note  section={section}  op={op}\n  preview: {preview!r}"


def _find_section(text: str, header: str) -> tuple[int, int]:
    """返回 (start_idx, end_idx)。end_idx 是下一个 '## ' 的位置，或文末。"""
    start = text.find(header)
    if start < 0:
        return -1, -1
    next_h = text.find("\n## ", start + len(header))
    end = len(text) if next_h < 0 else next_h
    return start, end


def _append_to_flow(text: str, section_key: str, operation: str) -> str:
    """在'近期更新流水'表格末尾追加一行。如果找不到流水段，原样返回。"""
    flow_start, flow_end = _find_section(text, FLOW_HEADER)
    if flow_start < 0:
        return text

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    new_row = f"| {timestamp} | OPUS · update_bro_note | section={section_key} ({operation}) |"

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
        text = read_global_soul_file(OWNER_NOTEBOOK_FILENAME, ROOT)
    except FileNotFoundError as e:
        return ToolResult(ok=False, output="", error=str(e))

    section_header = SECTIONS[section_key]
    sec_start, sec_end = _find_section(text, section_header)
    if sec_start < 0:
        return ToolResult(
            ok=False, output="",
            error=f"section header not found in OWNER-NOTEBOOK.md: {section_header!r}",
        )

    section_body = text[sec_start:sec_end]

    if operation == "replace_section":
        new_section_body = f"{section_header}\n\n{content}\n\n"
    else:
        new_section_body = section_body.rstrip() + f"\n\n{content}\n\n"

    new_text = text[:sec_start] + new_section_body + text[sec_end:]
    new_text = _append_to_flow(new_text, section_key, operation)

    try:
        global_path, local_path = write_global_then_sync(
            OWNER_NOTEBOOK_FILENAME, new_text, ROOT,
        )
    except FileNotFoundError as e:
        return ToolResult(ok=False, output="", error=str(e))

    #  · 写完 OWNER-NOTEBOOK 后增量更新 FTS5 索引 (best-effort · 失败不影响主流程)
    fts_msg = ""
    try:
        from workers.memory_index import incremental_update
        n_chunks = incremental_update("OWNER-NOTEBOOK", new_text)
        fts_msg = f"\n  fts5    : 已增量索引 {n_chunks} 块"
    except Exception:
        pass

    #  · 同会话热重载 · 让刚写的画像下一轮 chat 立刻在 system prompt 里 (不必等重启)
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
            f"OWNER-NOTEBOOK 已更新\n"
            f"  section : {section_key}  ({section_header})\n"
            f"  op      : {operation}\n"
            f"  added   : {len(content)} chars\n"
            f"{global_line}"
            f"  local   : {local_path.relative_to(ROOT)}\n"
            f"  flow    : 操作记录已追加到'近期更新流水'{fts_msg}{reload_msg}\n"
            f"  effect  : 本 daemon 下一轮对话即刻带上 (热重载)" +
            ("" if global_path else " · 全局目录回来后用 sync-soul.ps1 可补同步其他容器")
        ),
    )


SPEC = ToolSpec(
    name="update_bro_note",
    description=(
        "Update OPUS's living profile of 用户 (6-dimensional cognitive notebook). "
        "Use this when 用户 reveals new info about his life, mood, schedule, projects, "
        "preferences, weaknesses, risks—or any signal worth remembering across sessions. "
        "6 sections: profile (current snapshot), events (chronological key moments), "
        "rules (用户's enduring traits), dialogue (signature phrases/signals), "
        "summary (monthly compressed), "
        "risks (用户's structural weaknesses + forward-looking risks—OPUS's early warning radar). "
        "The notebook is auto-injected into every container's runtime context (Cursor / daemon / wechat bridge), "
        "so writing here builds long-term continuity AND multi-container shared cognition. "
        "Default operation=append; use replace_section sparingly."
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
                    "'risks' (用户's structural weakness or forward-looking risk + OPUS's voicing discipline)"
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
