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
  - operation=rename_section 时只换段头那一行、正文一字不动（改格子名字用）
  - operation=edit_text 时把段内一段原文换成新文（content 传 "旧文=>新文"，须唯一命中）
  - operation=fix_headings 时只修「段头被吸进上一行」的粘连（不碰任何内容 · 不吃 section）
  - 自动在"改动记录"末尾追加一行操作记录

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
from workers.notebook_tiers import SECTIONS as _TIER_SECTIONS, section_meta


ROOT = Path(__file__).resolve().parent.parent


# section key → 段标题关键字（用于 `^## ` 标题内子串唯一匹配）。
# 设计：六维画像用「一、…」「二、…」中文序号前缀，但状态卡/了解层/变更史是
# **独立区块**，不是第七维——不该抢序号。为避免「## 二、了解层」和「## 二、关键事件流」
# 撞车，这里改用「标题关键字在 `## ` 后唯一命中」匹配，不再靠中文序号。
# 兼容性：旧版 BRO-NOTEBOOK 与新版 OWNER-NOTEBOOK 的六维标题文案不同但含相同关键字，
# 关键字匹配通吃；了解层/变更史用无序号标题，也不与六维冲突。
# section key → 段标题定位候选（**从 workers.notebook_tiers.SECTIONS 派生** · 单一真相源）
# 这里曾自己拄一份「短名 → 关键字」，跟 notebook_tiers 各说各话 ——
# 母体用「本体约束/对话图鉴/压缩段/风险与弱点」，纯净版模板用
# 「长期偏好与边界/对话风格/一句话速写/关怀雷达」，四维对不上 → 用户写不进去。
# 现在 anchor 是候选元组（按序），两套叫法都能定位；真归一后只需改 notebook_tiers 那一张表。

SECTIONS: dict[str, tuple[str, ...]] = {
    k: m.anchor for k, m in _TIER_SECTIONS.items() if m.writable and k != "state"
}

FLOW_ORD = "近期更新流水"  # 按标题关键字匹配「## 七、近期更新流水」——保留其序号但匹配用关键字

# 状态卡 · L2 易变尾巴 · 替换式更新（不进 SECTIONS 序号锚）
STATE_SECTION_MARKER = "〇、状态卡"
# 派生自内核单一真相源（2026-09-30 wish-6e6e561b）—— 此前这里手抄了一份，会分叉。
from soul_loader import STATE_CARD_FIELDS as STATE_FIELDS  # noqa: E402

# 涌现字段准入判据：字段名里带这些词根 → 它就是骨架那几格的事（2026-09-30 wish-6e6e561b）。
# 不做同义词表（那要养一套・养不全）—— 只做词根碰撞：简单・可判定・误伤低。
# 治的是「健康/作息」：它跟骨架的「健康基线」+「作息模式」说同一件事。
STATE_FIELD_ROOTS: tuple[str, ...] = (
    "工作", "作息", "健康", "情绪", "主线", "家庭", "经济", "预算", "忌口",
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


# ── 段头粘连自愈 (wish-cca82a91 · 2026-09-29) ──────────────────────────
# 病：`---## 一、背景档案` / `| 2026-09-28 | - |## 了解层` —— 段头被吸进上一行末尾。
# 为什么是硬伤：_find_section 靠 `(?m)^## [^#]` 找段头，粘连行行首不是 # →
#   那个段在工具眼里【根本不存在】，内容被上一个真段头整段吞掉。
#   2026-09-29 实测母体本子 4 处中招，其中「了解层」是核心层 ——
#   那 7 条稳定认知（产品思维/JRPG 老炮/重命名能手/释权是真意/看远也看近/不肉麻/省钱敏感）
#   因此全部没进前缀。
# 为什么只认 - 和 | 作前导：只修能被判定为「表格行 / 分隔线末尾误粘」的，
#   正文里正常引用的 `## 某某` 不动。宁可少修，不可误伤。
# 段头粘连：正文紧贴 `## 标题` 挤在同一行。
# 2026-09-30 wish-6e6e561b：判据原来只认「前面是 - 或 |」（列表/表格尾），
#   于是「他做这个产品已经快 4 个月了。## 二、他经历的事」这种**句号结尾的正文**
#   一直没被修 —— 后果是 _find_section 靠 `^## ` 找不到那个段，整格写不进去（搬数据时撞到）。
#   放宽到句末标点；`(?!#)` / `[^#\n]` 仍挡着行内引用 `## xx` 和 `### 子标题`。
# 段头自愈判据 · **单一真相源在内核**（2026-09-30 wish-a266df37）
#   为何搬内核：内核 write_global_then_sync 是所有写入的必经之路，落盘前那道闸用它；
#   这里保留调用点只做「即时修复 + 回执」（让 BRO 看得见修了什么）。
#   两份判据分叉过一次——这份只认 `-`/`|` 前导，认不出句号结尾的粘连（真文件里漏了 6 处），所以收成一份。
from soul_loader import _HEAD_GLUE as _HEAD_GLUE, heal_headings as _heal_headings  # noqa: E402, F401





def _backup_notebook(text: str) -> str:
    """改画像前先落一份到 data/runtime/（notebook_guard 不让外部备份，工具自己来）。"""
    d = ROOT / "data" / "runtime"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"BRO-NOTEBOOK.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    p.write_text(text, encoding="utf-8")
    return str(p)


def _reload_and_index(fn: str, text: str) -> None:
    """写完画像后的 best-effort：FTS5 增量 + system prompt 热重载。"""
    try:
        from workers.memory_index import incremental_update
        incremental_update(Path(fn).stem, text)
    except Exception:
        pass
    try:
        from daemon_runtime import reload_soul_into_runtime
        reload_soul_into_runtime()
    except Exception:
        pass


def _run_fix_headings() -> ToolResult:
    """只修段头粘连 · 不碰任何内容。不吃 section 白名单（它不是「往格里写东西」）。"""
    fn, text = _read_notebook()
    healed, fixed = _heal_headings(text)
    if not fixed:
        return ToolResult(True, f"{fn} 段头都健康 · 没有粘连（扫了 {len(text):,} 字）")
    bk = _backup_notebook(text)
    try:
        write_global_then_sync(fn, healed, ROOT)
    except Exception as e:
        return ToolResult(False, "", f"修段头后写盘失败: {e} · 原文件未动 · 备份在 {bk}")
    _reload_and_index(fn, healed)
    return ToolResult(
        True,
        f"{fn}: 修好 {len(fixed)} 处段头粘连（内容一字未动）\n"
        + "\n".join(f"  · {h}" for h in fixed)
        + f"\n  备份: {bk} · 索引已增量 · 前缀已热重载",
    )


def _run_normalize_entries() -> ToolResult:
    """把条目行统一成 `- **标题**（YYYY-MM-DD）：正文`（wish-66c1eac5 第 6 步）。

    只改**写法**（加 `- ` 前缀 / 加粗标题 / 调括号位置），**一个字的内容都不动**。
    跟 fix_headings 同构：不吃 section 白名单（它不是「往格里写内容」，是清格式债）。

    为何需要：写入端归一（第 4 步）只保新写入的干净，**存量里的异形条目**得洗一次 ——
    否则它们对下沉 / 升格机制持续隐形，格子水位一路顶到超预算还沉不动。
    """
    fn, text = _read_notebook()
    _norm = _kernel_attr("workers.memory_reaper", "normalize_entries")
    if _norm is None:
        return ToolResult(False, "",
                          "本环境没有 workers.memory_reaper.normalize_entries（纯净版未 port）")
    fixed, changed = _norm(text)
    if not changed:
        return ToolResult(True, f"{fn} 条目格式都健康 · 没有需要归一的（扫了 {len(text):,} 字）")
    bk = _backup_notebook(text)
    try:
        write_global_then_sync(fn, fixed, ROOT)
    except Exception as e:
        return ToolResult(False, "", f"归一后写盘失败: {e} · 原文件未动 · 备份在 {bk}")
    _reload_and_index(fn, fixed)
    return ToolResult(
        True,
        f"{fn}: 归一 {len(changed)} 条（内容一字未动，只统一了写法）\n"
        + "\n".join(f"  · {c}" for c in changed)
        + f"\n  备份: {bk} · 索引已增量 · 前缀已热重载",
    )


def _find_section(text: str, key) -> tuple[int, int]:
    """按「段标题定位候选」找 '## <含候选词的标题>' 段头。
    返回 (start_idx, end_idx)，end 是下一个 '## ' 或文末。
    :注意: 只匹配『行首是 ## 的二级标题』整行，避免 '### 子标题' 误命中；
    且要求标题行本身不以 '#' 开头(排除 ## 后的 '#'，即排除 ###)。用 finditer 遍历全部标题行，
    找到第一个含任一候选词的行即为目标段。key 可以是 str 或候选元组（按序）。
    """
    keys = (key,) if isinstance(key, str) else tuple(key or ())
    for m in re.finditer(r"(?m)^## [^#].*$", text):
        if any(k in m.group(0) for k in keys):
            start = m.start()
            next_h = text.find("\n## ", start + 1)
            end = len(text) if next_h < 0 else next_h
            return start, end
    return -1, -1


def _real_headings(text: str) -> list[str]:
    """该文件真实有哪些 `## ` 段标题 —— 写不进去时报给他看，别只说「没找到」。"""
    return [m.group(0)[3:].strip() for m in re.finditer(r"(?m)^## [^#].*$", text)]


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


def _notebook_target_label() -> str:
    """回执里说清写到了哪 —— 一格一文件后落点是目录不是单文件（2026-09-30 wish-27273a5b）。"""
    try:
        from workers import notebook_store as _NS

        if _NS.dir_exists(ROOT):
            return "灵魂层 soul/notebook/（一格一文件）"
    except Exception:
        pass
    return OWNER_NOTEBOOK_FILENAME


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


def _delete_state_field(state_field: str) -> ToolResult:
    """删掉状态卡里某一格（误建字段 / 值已归并的脏行）· wish-run-anchor-2

    为什么需要: 状态卡表里留过一行字面值就是「（误建字段 · 值已归并到「作息模式」· 待清理）」，
    9-21 标到今天没人清 —— 它让「N 个字段待更新」看着比实际乱。而工具只有覆盖、没有删。

    只删表行，不碰别的格子。删错了可从 data/runtime/BRO-NOTEBOOK.bak-* 回滚。
    """
    if not state_field:
        return ToolResult(ok=False, output="", error="delete_state_field 需要 state_field")
    try:
        notebook_fn, text = _read_notebook()
    except FileNotFoundError as e:
        return ToolResult(ok=False, output="", error=str(e))
    sec_start, sec_end = _find_state_section(text)
    if sec_start < 0:
        return ToolResult(ok=False, output="",
                          error=f"section '## {STATE_SECTION_MARKER}' not found")
    body = text[sec_start:sec_end]
    kept: list[str] = []
    removed = 0
    for line in body.split("\n"):
        cells = [c.strip() for c in line.strip("|").split("|")] if line.startswith("|") else []
        if cells and cells[0] == state_field:
            removed += 1
            continue
        kept.append(line)
    if not removed:
        return ToolResult(ok=False, output="",
                          error=f"状态卡里没找到字段 {state_field!r}")
    new_body = "\n".join(kept)
    new_text = text[:sec_start] + new_body + text[sec_end:]
    try:
        _backup_notebook(text)
        write_global_then_sync(notebook_fn, new_text, ROOT)
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"写盘失败: {e}")
    return ToolResult(ok=True,
                      output=f"已删掉状态卡字段「{state_field}」（{removed} 行）· 备份已留。")


def _run_state(args: dict) -> ToolResult:
    """状态卡替换式更新 · 不 append · 按字段名改表格行。"""
    operation = (args.get("operation") or "").strip().lower()
    state_field = (args.get("state_field") or "").strip()
    state_value = (args.get("state_value") or "").strip()
    as_of = (args.get("as_of") or "").strip()
    evidence = (args.get("evidence") or "-").strip() or "-"

    if operation == "delete_state_field":
        return _delete_state_field(state_field)

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

    # as_of 必须是 ISO 日期（2026-09-30 wish-52427d8a）——
    # 读侧只认 ISO：_state_field_fresh 解不出 → 视为「新鲜」→ 永不过期；
    # L340 又按字符串排序，『昨天』(中文码位>数字)、『9/28』(9>2) 反而排最前，
    # 把真最新的 ISO 挤下去 → 上限 5 变成「错的挤掉对的」。堵在写入口。
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", as_of):
        return ToolResult(
            ok=False,
            output="",
            error=(
                f"as_of 必须是 YYYY-MM-DD（ISO），收到 {as_of!r}。\n"
                f"  为什么：读侧 TTL 与「as_of 新的优先」只认 ISO —— 写别的形态会被"
                f"当成「解不出 = 新鲜」永不过期，还会在排序里占掉新条目的位置。\n"
                f"  改成: as_of='{datetime.now().strftime('%Y-%m-%d')}'"
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

    # ⚠ 涌现准入（2026-09-30 wish-6e6e561b）：字段名撞骨架词根 → 拒。
    # BRO：「我需要的是一直都是能在落位时候就知道该落哪，而不是我发现了之后你去搬」——
    # 这条判据就是「落位时就知道」：写的时候就被挡回骨架那格，不会拖到以后再去搬。
    _hit = [r for r in STATE_FIELD_ROOTS if r in state_field]
    if _hit:
        return ToolResult(
            ok=False,
            output="",
            error=(
                f"state_field '{state_field}' 与骨架字段撞词根（{'/'.join(_hit)}）——"
                f" 这是当下状态，请直接改那 8 个骨架字段之一；"
                f"真要记 8 条之外的，换个不带这些词的名字（或者它根本该去 stories / about-user）"
            ),
        )

    try:
        notebook_fn, text = _read_notebook()
    except FileNotFoundError as e:
        return ToolResult(ok=False, output="", error=str(e))

    # 自愈：任何一次写入都顺手清历史遗留的段头粘连（否则段头一坏，那格就永远
    # 找不到了 —— 连修都修不了）。修过先落盘止血，再干本次的正事。
    _raw_text = text
    text, _healed_now = _heal_headings(text)
    if _healed_now:
        try:
            _backup_notebook(_raw_text)
            write_global_then_sync(notebook_fn, text, ROOT)
        except Exception:
            pass

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

    # 涌现长尾的「新陈代谢」(2026-09-30 wish-6e6e561b · 收 G1 + G2)
    #   BRO 要的是「机制相同」：跟画像其他格一样 —— 新的进得来、旧的沉下去、不删、可召回。
    #   落地就一句话：把**过 TTL / 超上限 5** 的涌现行从状态卡段搬到「已下沉」段。
    #   复用 workers.memory_reaper 那套（demote_strip + append_demoted），不新造机制。
    #   动态取 + 降级（跟下面 _demote_to_fit 同规矩）：纯净版未 port 内核件时不强依赖。
    # 算「该沉的」= 全量涌现 − 过滤后的涌现（全量拿 apply_limits=False）。
    _emerged_demoted: list = []
    try:
        from workers.cognition_loader import _parse_state_card as _psc
        _s2, _e2 = _find_state_section(new_text)
        _seg2 = new_text[_s2:_e2] if _s2 >= 0 else ""
        if _seg2:
            _all_em = [f for f in _psc(_seg2, apply_limits=False) if f not in STATE_FIELDS]
            _live_em = [f for f in _psc(_seg2) if f not in STATE_FIELDS]
            _dead = [f for f in _all_em if f not in _live_em]
            if _dead:
                _strip = _kernel_attr("workers.memory_reaper", "demote_strip")
                _dapp = _kernel_attr("workers.memory_reaper", "append_demoted")
                if _strip and _dapp:
                    _rows = []
                    for _l in _seg2.splitlines():
                        _t = _l.strip()
                        if not (_t.startswith("|") and _t.endswith("|")):
                            continue
                        _cells = [c.strip() for c in _t.strip("|").split("|")]
                        if _cells and _cells[0] in _dead:
                            _rows.append({"title": _cells[0], "line": _t, "chars": len(_t)})
                    if _rows:
                        _new_seg, _removed = _strip(_seg2, _rows)
                        if _removed:
                            new_text = new_text[:_s2] + _new_seg + new_text[_e2:]
                            new_text = _dapp(new_text, _removed)
                            _emerged_demoted = _removed
    except Exception:
        _emerged_demoted = []
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
            f"{_notebook_target_label()} 已更新\n"
            f"  section : state  ({section_header})\n"
            f"  op      : replace\n"
            f"  field   : {state_field}\n"
            f"  value   : {state_value}\n"
            f"  as_of   : {as_of}\n"
            f"  evidence: {evidence}\n"
            f"{global_line}"
            f"  local   : {local_path.relative_to(ROOT)}\n"
            f"  flow    : 操作记录已追加到'改动记录'{fts_msg}{reload_msg}\n"
            f"  effect  : 本 daemon 下一轮对话即刻带上 (卷五十四热重载)" +
            ("" if global_path else " · 全局目录回来后用 soul sync script 可补同步其他容器")
        ),
    )


def _run(args: dict) -> ToolResult:
    section_key = (args.get("section") or "").strip().lower()
    if section_key == "state":
        return _run_state(args)

    # fix_headings：段头粘连自愈（见 _heal_headings）。它不往任何格里写内容，
    # 所以不吃 section 白名单 —— 否则「段头坏了 → 找不到段 → 修不了」自己堵自己。
    if (args.get("operation") or "").strip().lower() == "normalize_entries":
        return _run_normalize_entries()
    if (args.get("operation") or "").strip().lower() == "fix_headings":
        return _run_fix_headings()

    # rename_section 只换标题行、不写内容 —— 不受「谁能写这格」限制：
    # 了解层/改动记录是系统段(writable=False)，但它们的标题同样会进前缀给模型看，
    # 标题错了照样误导（例如「L1 稳定前缀」是工程黑话）。
    # edit_text 同理：它是「定点改字」（治漂移），不是「往格里加内容」，
    # 所以也放行保护段 —— 旧名引用跟进、过时表述修正靠它。
    _op_early = (args.get("operation") or "append").strip().lower()
    _anchor_tbl = (
        {k: m.anchor for k, m in _TIER_SECTIONS.items()}
        if _op_early in ("rename_section", "edit_text") else SECTIONS
    )
    if section_key not in _anchor_tbl:
        return ToolResult(
            ok=False, output="",
            error=f"unknown section: {section_key!r}; valid: {', '.join(_anchor_tbl)}",
        )

    content = (args.get("content") or "").strip()
    if not content:
        return ToolResult(ok=False, output="", error="empty content; nothing to write")

    # P0 写时闸 (wish-31fd335e) · force=true 跳过分类/预算闸 (BRO 明确要求时用)
    force = bool(args.get("force"))

    operation = (args.get("operation") or "append").strip().lower()
    if operation not in ("append", "replace_section", "rename_section", "edit_text"):
        return ToolResult(
            ok=False, output="",
            error=(f"unknown operation: {operation}; use 'append' / 'replace_section' / "
                   f"'rename_section' / 'edit_text'"),
        )

    from workers.notebook_tiers import route_write_section
    _requested_key = section_key
    section_key = route_write_section(section_key, operation, content)
    _rerouted = section_key != _requested_key

    # 落位校验（wish-0c8602ff）：过期毒 / 超长文档 → 拒收（force 可跳·与 P0 闸一致）
    if not force:
        from workers.notebook_tiers import validate_entry
        _v_err = validate_entry(section_key, content, operation)
        if _v_err:
            return ToolResult(ok=False, output="", error=_v_err)

    try:
        notebook_fn, text = _read_notebook()
    except FileNotFoundError as e:
        return ToolResult(ok=False, output="", error=str(e))

    # 自愈：任何一次写入都顺手清历史遗留的段头粘连（否则段头一坏 → _find_section
    # 靠 `^## ` 找不到那格 → 连修都修不了，整格写不进去）。
    # 2026-09-30 wish-6e6e561b：_run_state 一直有这一步，_run_write 漏了 —— 补上。
    _raw_text = text
    text, _healed_now = _heal_headings(text)
    if _healed_now:
        try:
            _backup_notebook(_raw_text)
            write_global_then_sync(notebook_fn, text, ROOT)
        except Exception:
            pass

    _meta = section_meta(section_key)
    sec_start, sec_end = _find_section(text, _anchor_tbl[section_key])
    if sec_start < 0:
        _heads = "；".join(_real_headings(text)) or "（这个文件一个 `## ` 段都没有）"
        return ToolResult(
            ok=False, output="",
            error=(
                f"在 {notebook_fn} 里没找到「{' / '.join(_anchor_tbl[section_key])}」段。\n"
                f"  · 这格放什么：{_meta.what if _meta else '（未知格）'}\n"
                f"  · 该文件真实有这些段：{_heads}"
            ),
        )

    section_header = _section_header_line(text, sec_start)
    section_body = text[sec_start:sec_end]

    _norm_changed: list = []
    if operation == "replace_section":
        new_section_body = f"{section_header}\n\n{content}\n\n"
    elif operation == "rename_section":
        # 只换标题行，正文一字节不动。content = 新的段头那一行（以 '## ' 开头）。
        _new_head = (content.splitlines()[0] if content else "").strip()
        if not _new_head.startswith("## "):
            return ToolResult(
                ok=False, output="",
                error=("rename_section 的 content 必须是新段头那一行，以 '## ' 开头，"
                       "例如 '## 三、本体约束 · 关于他（缓变）'"),
            )
        _rest = section_body[len(section_header):]   # 旧标题行之后的原文（含前导空行）
        new_section_body = f"{_new_head}{_rest}"
        # 改名后后续一切（section 行回报 / is_core_section 进前缀判据）都按新段头算，
        # 否则拿旧头部去查白名单——旧词一清账就会当场算错。
        section_header = _new_head
    elif operation == "edit_text":
        # 段内定点改字（BRO 2026-09-18 授权）：把一段精确原文换成新文，不整段覆盖。
        # 用于保护段里旧名引用跟进、过时表述修正这类「治漂移」动作。
        # content = "旧文=>新文"；旧文必须在本段**恰好命中 1 处**，否则拒收。
        if "=>" not in content:
            return ToolResult(
                ok=False, output="",
                error='edit_text 的 content 必须是 "旧文=>新文" 形式（例：对话图鉴=>口头记号）',
            )
        _old, _new = (p.strip() for p in content.split("=>", 1))
        if not _old or not _new:
            return ToolResult(ok=False, output="", error="edit_text: 旧文和新文都不能为空")
        _n_hit = section_body.count(_old)
        if _n_hit != 1:
            return ToolResult(
                ok=False, output="",
                error=(f'edit_text: 旧文「{_old}」在这段里命中 {_n_hit} 处（必须恰好 1 处）。'
                       f'0 = 原文不符或已改过；>1 = 会误伤，请给更长的原文。'),
            )
        new_section_body = section_body.replace(_old, _new, 1)
    else:
        # 写入端归一（wish-66c1eac5 第 4 步 · 2026-09-30）：
        #   原来这里是 `section_body.rstrip() + f"\n\n{content}\n\n"` —— **模型传什么就落什么**，
        #   一个字的格式都不管。于是同一个库里 4 种写法混着（括注位置 / 裸段落 / 无 `- `），
        #   读取正则认不全 → 异形条目对下沉机制隐形 → 那格水位顶到超预算还沉不动。
        #   落盘前统一成 `- **标题**（YYYY-MM-DD）：正文`，与 heal_headings 同思路：
        #   治在写入路径上，而不是等读取端一个个打补丁。
        #   动态取（跟上面 demote_to_fit 同法）：纯净版未 port 时不强依赖，退回原行为。
        _norm = _kernel_attr("workers.memory_reaper", "normalize_entries")
        if _norm is not None:
            try:
                _c2, _chg = _norm(content)
                if _chg:
                    _norm_changed = list(_chg)
                content = _c2
            except Exception:
                pass
        new_section_body = section_body.rstrip() + f"\n\n{content}\n\n"

    new_text = text[:sec_start] + new_section_body + text[sec_end:]

    # P0 预算闸 (wish-31fd335e) · 2026-09-29 升级：满了不再「拒写」→「先下沉再写」
    #   病根：旧行为是「满了 → 拒绝 + 让人去清」。BRO 定过：不可能让用户陪着
    #   定期讨论什么留什么不留。改成自动：把该格里**最老的有日期条目**沉到
    #   「已下沉」段（不进前缀 · 可召回 · 一句话捞回），腾出地方再写。
    #   沉完还是超 → 才拒（说明这格已经没有可沉的条目了，得人看）。
    _budget_used, _budget_cap = 0, 0
    _sec_used, _sec_cap = 0, 0
    _demoted: list = []
    _is_core = False
    _gate_err = ""
    if not force:
        try:
            from workers.notebook_tiers import (core_budget_estimate, is_core_section,
                                                section_budget_estimate)
            # ① 分格闸 (2026-09-29 wish-65ea4984 step5)：一格吃光后别的格就写不进来
            #    —— 所以先查这一格自己，再查整锅。
            # 2026-09-30 wish-66c1eac5 修：**分格闸只对「进前缀的格」有意义**。
            #   不进前缀的格（stories / archive / 背景档案…）不占前缀配额，它自己的
            #   tok 上限只是提示阈值 —— 此前无条件查它，导致「写 stories 溢出却去沉
            #   how-we-work」的**跟格误沉**（实测挖走 2 条 how-we-work 原则）。
            #   根因：焦点格不在核心层时，「从 focus_key 起」会退化成「从最肥的核心格起」。
            _is_core = is_core_section(section_header)
            if _is_core:
                _sec_used, _sec_cap = section_budget_estimate(new_text, section_key)
            _budget_used, _budget_cap = core_budget_estimate(new_text)
            if (_is_core and _sec_used > _sec_cap) or _budget_used > _budget_cap:
                # 下沉是「内核件 memory_reaper」的能力 —— 那份内核件可能还没到本环境
                # （纯净版未 port 时）。用动态取 + 降级：拿到就下沉，拿不到退回旧行为（拒写）。
                # 不用静态 import 是故意的：白名单依赖闸扫静态 import 就判「纯净版会崩」
                # （它只看引用关系、不看 try/except）。动态取才是真意思上的「不强依赖」。
                _demote_to_fit = _kernel_attr("workers.memory_reaper", "demote_to_fit")
                if _demote_to_fit is not None:
                    _need = max(_sec_used - _sec_cap if _is_core else 0,
                                _budget_used - _budget_cap, 0)
                    # 刚写进来的那条不参与下沉（见 demote_pick 注释）：写 = 这条现在就要在场。
                    # 实测：核心层只剩 43 tok 时写一条 192 tok 的，候选里唯一带日期的
                    # 就是刚写的这条 —— 于是它把自己沉走了，回执却说「已更新」。
                    _new_lines = {ln.strip() for ln in (content or "").splitlines() if ln.strip()}
                    new_text, _demoted = _demote_to_fit(
                        new_text, section_key if _is_core else None, need_tok=_need,
                        protect_lines=_new_lines)
                    if _is_core:
                        _sec_used, _sec_cap = section_budget_estimate(new_text, section_key)
                    _budget_used, _budget_cap = core_budget_estimate(new_text)
            if not _demoted and _is_core and _sec_used > _sec_cap:
                return ToolResult(
                    ok=False, output="",
                    error=(f"这一格满了，且没有可自动下沉的条目：{section_key} ≈{_sec_used} tok > "
                           f"该格预算 {_sec_cap} tok。（能自动沉的只有「带日期」的条目 —— "
                           f"没日期的算常驻原则，不动。）请手动合并重复条目 · 确要强写加 force=true。本次未写入。"),
                )
            if not _demoted and _budget_used > _budget_cap:
                return ToolResult(
                    ok=False, output="",
                    error=(f"prefix budget exceeded: 核心层 ≈{_budget_used} tok > 预算 {_budget_cap} tok，"
                           f"且没有可自动下沉的条目。请手动清理 · 确要强写加 force=true。本次未写入。"),
                )
        except Exception as _gate_ex:
            # 2026-09-30 wish-66c1eac5：原来是纯静默归零 —— 闸内部一抛异常，
            # 报数就变成 0/0 或错值，却完全看不出「闸根本没跑成」。
            # 实测撞到过一次（写 about-user 报「本格 ≈0/2800 · 核心层 ≈18802/5000」
            # 并触发下沉），事后**无法复现** —— 静默吞错正是它不可诊断的原因。
            # 改成留证：异常原文进回执，下次再发生就有现场可查。
            _gate_err = repr(_gate_ex)
            _budget_used, _budget_cap = 0, 0
            _sec_used, _sec_cap = 0, 0

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

    # 段落归位·说真话 (wish-9118bdab)：从 notebook_tiers 实时算, 不再硬编码。
    # 旧代码 `section_key in ("profile", "about-user")` 里 profile 段早已退役出核心层,
    # 却一直回报「✓ 进前缀」—— 写进黑洞还以为在场。判据只能有一个来源。
    from workers.notebook_tiers import is_core_section, has_distill_pipeline
    _in_prefix = is_core_section(section_header)
    _distill = has_distill_pipeline(section_key)
    if _in_prefix:
        _pfx_line = "✓ 进前缀 (每轮注入)"
    elif _distill:
        _pfx_line = "△ 不进前缀 · 有提炼管道 (周度凝练会把它提炼进「了解层」)"
    else:
        _pfx_line = "✗ 不进前缀 · 无提炼管道 (只能靠 recall_memory 按需召回)"
    if _rerouted:
        _pfx_line += f"  [已从 {_requested_key} 改道 → {section_key}]"

    # 进前缀 = 每条永久占用预算。写入者要当场看见代价与反问 (wish-c8aa92e1 · 2026-09-18)
    # 病根: 旧文案只写「✓ 进前缀」(不贵)，于是新条默认往核心层灌 —— 只增不减。
    _cost_line = ""
    _ask_line = ""
    _peer_line = ""
    if _in_prefix:
        try:
            _added_tok = len(enc.encode(content)) if (enc := _tiktoken_enc()) else 0
            _room_before = max(_budget_cap - _budget_used, 0) if _budget_cap else 0
            _room_after = max(_room_before - _added_tok, 0) if _budget_cap else 0
            if _budget_cap:
                _cost_line = f" · 本条 +{_added_tok} tok · 余量 {_room_before}→{_room_after}"
            else:
                _cost_line = f" · 本条 +{_added_tok} tok"
        except Exception:
            pass
        _ask_line = (
            "\n  ⚠ 自问  : 这条是「每轮都需要」还是「需要时能召回」 —— "
            "能召回 → 改 events (不进前缀) · 别让它在核心里永久占位。"
        )
        _peer_line = _peer_items_line(section_body)
    _warn_line = ""
    if not _in_prefix and not _distill:
        _warn_line = (
            "\n  ⚠ 自检  : 这条每轮读不到。若它是会影响我行为的偏好/原则/判断"
            "(而不是留档待召回的故事)，请去掉日期前缀、用 section='about-user' 重写一次。\n"
        )
    # 2026-09-29 wish-65ea4984 step5 · 同时报「该格水位」—— 只看整锅看不出「是谁在吃」
    _sec_part = (f" · 本格 {section_key} ≈{_sec_used}/{_sec_cap} tok"
                 if (not force and _sec_cap) else "")
    _budget_line = (f"核心层 ≈{_budget_used}/{_budget_cap} tok{_sec_part}" if (not force and _budget_cap)
                    else "(force 或未启用跳过)")
    if _gate_err:
        _budget_line += f"\n  ⚠ 闸异常: {_gate_err}（闸未真正生效 · 报数不可信）"
    # 下沉回执 (2026-09-29)：格子满过就当场说清 —— 沉了哪几条、去哪了、怎么捞回来。
    #   不说的话 BRO 只看到「写成功了」，看不见它自己腾了地方（人需要看得见它在自转）。
    _demote_line = ""
    if _demoted:
        _titles = " / ".join((d.get("title") or "")[:16] for d in _demoted[:3])
        _demote_line = (
            f"\n  ↓ 下沉  : 本格曾满 → 自动沉了 {len(_demoted)} 条到「已下沉」（不进前缀 · 可召回）：{_titles}"
            f"\n           想捞回来：说一句「把 X 捞回来」即可。"
        )
    return ToolResult(
        ok=True,
        output=(
            f"{_notebook_target_label()} 已更新\n"
            f"  section : {section_key}  ({section_header})\n"
            f"  op      : {operation}\n"
            f"  added   : {len(content)} chars\n"
            f"  prefix  : {_pfx_line}{_cost_line}\n"
            f"  where   : {_meta.what if _meta else '（未知格）'}\n"
            f"  budget  : {_budget_line}\n"
            f"{_ask_line}"
            f"{_demote_line}"
            f"{_peer_line}"
            f"{_warn_line}"
            f"{global_line}"
            f"  local   : {local_path.relative_to(ROOT)}\n"
            f"  flow    : 操作记录已追加到'改动记录'{fts_msg}{reload_msg}\n"
            f"  effect  : 本 daemon 下一轮对话即刻带上 (卷五十四热重载)" +
            ("" if global_path else " · 全局目录回来后用 soul sync script 可补同步其他容器")
        ),
    )


def _kernel_attr(module: str, name: str):
    """按需取一个内核件里的函数 · 拿不到返回 None（那份内核件还没到本环境时不炸）。

    为何用动态取而不是静态 import：`tools/check_manifest_deps.py` 的白名单依赖闸
    扫【静态 import】就判「纯净版会崩」（它只看引用关系，不看 try/except）。而这里
    要的就是「没有就优雅缺席」—— 动态取 + getattr 默认值正是这个语义。
    """
    try:
        import importlib
        return getattr(importlib.import_module(module), name, None)
    except Exception:
        return None


_ENC = None


def _tiktoken_enc():
    """best-effort token 计数（没装 tiktoken 就返回 None，调用方降级）。"""
    global _ENC
    if _ENC is None:
        try:
            import tiktoken
            _ENC = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _ENC = False
    return _ENC or None


def _peer_items_line(section_body: str, limit: int = 14) -> str:
    """列出该格现有的条目标题 —— 让写入者当场看见有没有同类的（柜子自己会说话）。

    为什么不做相似度自动判重 (wish-c8aa92e1 · 2026-09-18)：
    实测本段 18 条两两字符 2-gram Jaccard 最高仅 0.083、中位 0.006，定不出阈值（定低了全员误报）。
    短文本 + 语义相近但用词不同（「不肉麻不结端」vs「柔的时刻」）字符级抓不到。
    按 BRO 判据：「两条是不是同一件事」是语义判断 → 不可机械判定 → 不做成闸，
    改成把现状摊给写入者自己判。
    """
    titles = []
    for line in (section_body or "").splitlines():
        line = line.strip()
        if not line.startswith("- **"):
            continue
        m = re.match(r"- \*\*(.+?)\*\*", line)
        if m:
            titles.append(m.group(1).strip())
    if not titles:
        return ""
    shown = titles[:limit]
    tail = f" …共 {len(titles)} 条" if len(titles) > limit else f"（共 {len(titles)} 条）"
    return "\n  同格已有: " + " / ".join(shown) + tail + "\n"


def append_owner_note(section: str, content: str) -> ToolResult:
    """压缩前 flush / 凝练器共用。走与工具同一条 append 路由。"""
    return _run({"section": section, "content": content, "operation": "append"})


SPEC = ToolSpec(
    name="update_owner_note",
    description=(
        "记下他刚说的（**参数名是 section，不是 key**）。格子在："
        "about-user=关于他这个人的原则/偏好/边界（把主语换成别人就不成立）· "
        "stories=带日期的故事流水 · state=当下状态（配 state_field/state_value/as_of）· "
        "background/moments/archive/watch 同理。"
        "听到作息/睡眠/健康/情绪/心情/工作/主线/预算变化 → section='state'。"
        "产品/功能决策别放这 —— 走 wish_add。默认 append，只写他真说过的。"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "section": {
                "type": "string",
                "enum": list(SECTIONS.keys()) + ["state"],
                "description": "要写的维度见 enum。state 需带 state_field / state_value / as_of。更新时机 = 闲聊提到就记，不是定时汇报。",
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
                "enum": ["append", "replace_section", "rename_section", "edit_text",
                         "fix_headings", "normalize_entries", "delete_state_field"],
                "description": (
                    "append (default). Also: replace_section / rename_section / edit_text / "
                    "fix_headings / normalize_entries / delete_state_field."
                ),
            },
            "force": {
                "type": "boolean",
                "description": (
                    "Skip write-time gates (dated-content reroute + prefix budget). "
                    "Only when explicitly told to force-write."
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
