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


# section key → 段标题关键字（用于 `^## ` 标题内子串唯一匹配）。
# 设计：六维画像用「一、…」「二、…」中文序号前缀，但状态卡/了解层/变更史是
# **独立区块**，不是第七维——不该抢序号。为避免「## 二、了解层」和「## 二、关键事件流」
# 撞车，这里改用「标题关键字在 `## ` 后唯一命中」匹配，不再靠中文序号。
# 兼容性：旧版 BRO-NOTEBOOK 与新版 OWNER-NOTEBOOK 的六维标题文案不同但含相同关键字，
# 关键字匹配通吃；了解层/变更史用无序号标题，也不与六维冲突。
SECTIONS: dict[str, str] = {
    "profile":  "当下画像",
    "events":   "关键事件流",
    "rules":    "本体约束",
    "dialogue": "对话图鉴",
    "summary":  "压缩段",
    # 第六维 2026-05-16 凌晨 BRO 拍板加上——OPUS 作为伙伴的预警雷达
    # 看见这一维的模式时该出声，不沉默配合燃烧
    "risks":    "风险与弱点",
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

FLOW_ORD = "近期更新流水"  # 按标题关键字匹配「## 七、近期更新流水」——保留其序号但匹配用关键字

# 状态卡 · L2 易变尾巴 · 替换式更新（不进 SECTIONS 序号锚）
STATE_SECTION_MARKER = "〇、状态卡"
STATE_FIELDS: tuple[str, ...] = (
    "工作状态",
    "作息模式",
    "健康基线",
    "情绪基线",
    "当前主线",
    "关系家庭",
    "经济预算",
    "忌口过敏",
)
_STATE_SECTION_RE = re.compile(r"(?m)^## 〇、状态卡")
STATE_HISTORY_MARKER = "状态卡变更史"
_STATE_HISTORY_RE = re.compile(r"(?m)^## 状态卡变更史")

# 了解层 · L1 稳定前缀 · 独立区块（无序号，避免与「## 二、关键事件流」抢「二」）
UNDERSTANDING_SECTION_MARKER = "了解层"

def _summarize(args: dict) -> str:
    section = args.get("section", "?")
    op = args.get("operation", "append")
    preview = (args.get("content") or "")[:60].replace("\n", " ")
    return f"update_owner_note  section={section}  op={op}\n  preview: {preview!r}"


def _find_section(text: str, key: str) -> tuple[int, int]:
    """按「段标题关键字」定位 '## <含关键字的标题>' 段头。
    返回 (start_idx, end_idx)，end 是下一个 '## ' 或文末。
    :注意: 只匹配『行首是 ## 的二级标题』整行，避免 '### 子标题' 误命中；
    且要求标题行本身不以 '#' 开头(排除 ## 后的 '#'，即排除 ###)。用 finditer 遍历全部标题行，
    找到第一个含 key 的行即为目标段。关键字需在全文标题里语义唯一（调用方保证）。
    """
    for m in re.finditer(r"(?m)^## [^#].*$", text):
        if key in m.group(0):
            start = m.start()
            next_h = text.find("\n## ", start + 1)
            end = len(text) if next_h < 0 else next_h
            return start, end
    return -1, -1


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

    # 找段内最后一个 "|" 开头的行：新表(只有表头+分隔行)插在分隔行后·老表插在最后一条数据后
    flow_body = text[flow_start:flow_end]
    lines = flow_body.split("\n")
    last_table_line = -1
    for i, line in enumerate(lines):
        if line.startswith("|"):
            last_table_line = i

    if last_table_line < 0:
        return text  # no table found, give up

    # insert new row right after the last existing table row
    lines.insert(last_table_line + 1, new_row)
    new_flow_body = "\n".join(lines)
    return text[:flow_start] + new_flow_body + text[flow_end:]


def _find_state_section(text: str) -> tuple[int, int]:
    """定位 `## 〇、状态卡` 段。返回 (start_idx, end_idx)，end 是下一个 '## ' 或文末。"""
    m = _STATE_SECTION_RE.search(text)
    if not m:
        return -1, -1
    start = m.start()
    next_h = text.find("\n## ", start + 1)
    end = len(text) if next_h < 0 else next_h
    return start, end


def _escape_table_cell(s: str) -> str:
    return (s or "").replace("|", "/")


def _read_state_table_value(section_body: str, field: str) -> str:
    """读状态卡表格某字段当前值（替换前取旧值用）。"""
    for line in section_body.split("\n"):
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if cells[0] in ("字段", "field") or set(cells[0]) <= set("-: |"):
            continue
        if cells[0] == field:
            return cells[1]
    return ""


def _find_state_history_section(text: str) -> tuple[int, int]:
    """定位 `## 一、状态卡变更史` 段。返回 (start_idx, end_idx)。"""
    m = _STATE_HISTORY_RE.search(text)
    if not m:
        return -1, -1
    start = m.start()
    next_h = text.find("\n## ", start + 1)
    end = len(text) if next_h < 0 else next_h
    return start, end


def _append_state_history(
    text: str,
    state_sec_end: int,
    field: str,
    old_value: str,
    new_value: str,
    as_of: str,
    evidence: str,
) -> str:
    """状态卡替换成功后 · 在变更史段 append 一行（段不存在则在状态卡后创建）。"""
    old_disp = _escape_table_cell(old_value or "待确认")
    new_disp = _escape_table_cell(new_value)
    row = (
        f"| {field} | {old_disp} → {new_disp} | "
        f"{_escape_table_cell(as_of)} | {_escape_table_cell(evidence or '-')} |"
    )

    hist_start, hist_end = _find_state_history_section(text)
    if hist_start >= 0:
        hist_body = text[hist_start:hist_end]
        lines = hist_body.split("\n")
        last_table_line = -1
        for i, line in enumerate(lines):
            if line.startswith("|"):
                last_table_line = i
        if last_table_line >= 0:
            lines.insert(last_table_line + 1, row)
        else:
            lines.extend([
                "",
                "| 字段 | 旧值 → 新值 | as_of | evidence |",
                "| --- | --- | --- | --- |",
                row,
            ])
        return text[:hist_start] + "\n".join(lines) + text[hist_end:]

    new_section = (
        "\n\n## 状态卡变更史\n\n"
        "| 字段 | 旧值 → 新值 | as_of | evidence |\n"
        "| --- | --- | --- | --- |\n"
        f"{row}\n"
    )
    return text[:state_sec_end] + new_section + text[state_sec_end:]


def _update_state_table_row(
    section_body: str,
    field: str,
    value: str,
    as_of: str,
    evidence: str,
) -> tuple[str, bool]:
    """在状态卡表格里按字段名替换一行；骨架字段不存在时追加新行(涌现长尾字段)。
    返回 (新段正文, 是否命中/写入)。"""
    lines = section_body.split("\n")
    updated = False
    for i, line in enumerate(lines):
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        if cells[0] in ("字段", "field") or set(cells[0]) <= set("-: |"):
            continue
        if cells[0] != field:
            continue
        cells[1] = _escape_table_cell(value)
        cells[2] = _escape_table_cell(as_of)
        cells[3] = _escape_table_cell(evidence or "-")
        lines[i] = "| " + " | ".join(cells) + " |"
        updated = True
        break
    if not updated:
        # 涌现长尾字段 · 表格无此行 → 追加到最后一个表格行之后（表头/分隔行后也行，只要行内）
        # 找到表格最后一个 "|" 行(非分隔/表头)作为插入点
        insert_at = -1
        for i, line in enumerate(lines):
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 2 and cells[0] not in ("字段", "field"):
                if not (set(cells[0]) <= set("-: |")):
                    insert_at = i
        if insert_at >= 0:
            new_row = (
                f"| {_escape_table_cell(field)} | {_escape_table_cell(value)} | "
                f"{_escape_table_cell(as_of)} | {_escape_table_cell(evidence or '-')} |"
            )
            lines.insert(insert_at + 1, new_row)
            updated = True
    return "\n".join(lines), updated


def _run_state(args: dict) -> ToolResult:
    """状态卡替换式更新 · 不 append · 按字段名改表格行。"""
    state_field = (args.get("state_field") or "").strip()
    state_value = (args.get("state_value") or "").strip()
    as_of = (args.get("as_of") or "").strip()
    evidence = (args.get("evidence") or "-").strip() or "-"

    missing = []
    if not state_field:
        missing.append("state_field")
    if not state_value:
        missing.append("state_value")
    if not as_of:
        missing.append("as_of")
    if missing:
        return ToolResult(
            ok=False,
            output="",
            error=(
                f"section='state' 需要 {', '.join(missing)} · "
                f"示例: state_field='作息模式' state_value='正常' as_of='2026-08-27'"
            ),
        )

    # 涌现长尾：允许 8 骨架字段以外的自定义字段（口味/健身/宠物等相处中长出的了解）。
    # 读侧 _parse_state_card 的 elif 分支已支持涌现字段；写侧原先用 STATE_FIELDS 硬拦会拒绝它们。
    # 安全灯：字段名过短(1 char)或恰是无意义占位(待确认/待更新)仍拦，避免脏写。
    if state_field in ("待确认", "待更新", "-", ""):
        return ToolResult(
            ok=False,
            output="",
            error=f"state_field '{state_field}' 是无意义占位值, 请给具体字段名",
        )
    if len(state_field) < 2:
        return ToolResult(
            ok=False,
            output="",
            error=f"state_field 太短: {state_field!r}; 请用 2+ 字符的字段名",
        )

    try:
        notebook_fn, text = _read_notebook()
    except FileNotFoundError as e:
        return ToolResult(ok=False, output="", error=str(e))

    sec_start, sec_end = _find_state_section(text)
    if sec_start < 0:
        return ToolResult(
            ok=False,
            output="",
            error=f"section '## {STATE_SECTION_MARKER}' not found in {notebook_fn}",
        )

    section_header = _section_header_line(text, sec_start)
    section_body = text[sec_start:sec_end]
    old_value = _read_state_table_value(section_body, state_field)
    new_section_body, hit = _update_state_table_row(
        section_body, state_field, state_value, as_of, evidence,
    )
    if not hit:
        return ToolResult(
            ok=False,
            output="",
            error=f"state_field {state_field!r} not found in state card table",
        )

    new_text = text[:sec_start] + new_section_body + text[sec_end:]
    new_sec_end = sec_start + len(new_section_body)
    new_text = _append_state_history(
        new_text, new_sec_end, state_field, old_value, state_value, as_of, evidence,
    )
    preview = f"{state_field} → {state_value} (as_of={as_of})"
    new_text = _append_to_flow(new_text, "state", "replace", preview)

    try:
        global_path, local_path = write_global_then_sync(
            notebook_fn, new_text, ROOT,
        )
    except FileNotFoundError as e:
        return ToolResult(ok=False, output="", error=str(e))

    fts_msg = ""
    try:
        from workers.memory_index import incremental_update
        n_chunks = incremental_update(Path(notebook_fn).stem, new_text)
        fts_msg = f"\n  fts5    : 已增量索引 {n_chunks} 块"
    except Exception:
        pass

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
            f"  section : state  ({section_header})\n"
            f"  op      : replace\n"
            f"  field   : {state_field}\n"
            f"  value   : {state_value}\n"
            f"  as_of   : {as_of}\n"
            f"  evidence: {evidence}\n"
            f"{global_line}"
            f"  local   : {local_path.relative_to(ROOT)}\n"
            f"  flow    : 操作记录已追加到'近期更新流水'{fts_msg}{reload_msg}\n"
            f"  effect  : 本 daemon 下一轮对话即刻带上 (卷五十四热重载)" +
            ("" if global_path else " · 全局目录回来后可用 soul sync script 补同步其他容器")
        ),
    )


def _run(args: dict) -> ToolResult:
    section_key = (args.get("section") or "").strip().lower()
    if section_key == "state":
        return _run_state(args)

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

    from workers.notebook_tiers import route_write_section
    section_key = route_write_section(section_key, operation, content)

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
            ("" if global_path else " · 全局目录回来后可用 soul sync script 补同步其他容器")
        ),
    )


def append_owner_note(section: str, content: str) -> ToolResult:
    """压缩前 flush / 凝练器共用。走与工具同一条 append 路由。"""
    return _run({"section": section, "content": content, "operation": "append"})


SPEC = ToolSpec(
    name="update_owner_note",
    description=(
        "更新活画像（profile/events/rules/dialogue/summary/risks/state）。日期故事写 events，改判断的短条写 rules。默认 append。只写他真说过的。"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "section": {
                "type": "string",
                "enum": list(SECTIONS.keys()) + ["state"],
                "description": "要写的维度，见 enum。state 还要带 state_field / state_value / as_of。",
            },
            "content": {
                "type": "string",
                "description": (
                    "The content to add. Use markdown. Be concise but substantive—"
                    "this stays in OPUS's runtime context for all future sessions, "
                    "so quality > quantity. "
                    "Not required when section='state'."
                ),
            },
            "state_field": {
                "type": "string",
                "enum": list(STATE_FIELDS),
                "description": (
                    "State card field name (required when section='state'). "
                    "Replace-style update—old value is overwritten, not appended."
                ),
            },
            "state_value": {
                "type": "string",
                "description": "Current value for state_field (required when section='state').",
            },
            "as_of": {
                "type": "string",
                "description": (
                    "Last confirmed date YYYY-MM-DD for this field "
                    "(required when section='state')."
                ),
            },
            "evidence": {
                "type": "string",
                "description": (
                    "One-line evidence for this update (optional when section='state'; default '-')."
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
        "required": ["section"],
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
