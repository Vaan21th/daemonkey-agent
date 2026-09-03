"""
workers/state_condenser.py
==========================

L2 → L1 周度凝练 · 条件触发 + 开机补偿。

条件：距上次凝练 ≥7 天 或 状态卡变更史新增 ≥30 条（先到先跑）。
失败静默降级 · 绝不影响主对话。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("opus.state_condenser")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME = ROOT / "data" / "runtime" / "state_condenser.json"
# 旧 fork 写 json，对话读 SHE-STATE → 四维不生长。家就是 identity 那份。
DEFAULT_STYLE_DIMS = ROOT / "soul" / "SHE-STATE.md"
_OLD_STYLE_DIMS_JSON = ROOT / "data" / "runtime" / "style_dims.json"


def _resolve_notebook() -> tuple[str, Path]:
    for name in ("OWNER-NOTEBOOK.md", "BRO-NOTEBOOK.md"):
        p = ROOT / "soul" / name
        if p.exists():
            return name, p
    return "BRO-NOTEBOOK.md", ROOT / "soul" / "BRO-NOTEBOOK.md"


NOTEBOOK_FILENAME, DEFAULT_NOTEBOOK = _resolve_notebook()

STYLE_DIM_KEYS = ("话量", "调性", "语气", "礼节", "表现力")

UNDERSTANDING_HEADING_KEY = "了解层"
HISTORY_HEADING_KEY = "状态卡变更史"
EVENTS_HEADING_KEY = "关键事件流"
STATE_CARD_HEADING_KEY = "〇、状态卡"  # 用「〇、」前缀唯一锁定状态卡段, 避免误命中「状态卡变更史」
CONDENSE_DAYS = 7
HISTORY_DELTA_THRESHOLD = 30

_UNDERSTANDING_SECTION_RE = re.compile(
    rf"(?m)^##\s+[^\n]*{re.escape(UNDERSTANDING_HEADING_KEY)}[^\n]*\n"
)
_HISTORY_SECTION_RE = re.compile(
    rf"(?m)^##\s+[^\n]*{re.escape(HISTORY_HEADING_KEY)}[^\n]*\n"
)

CONDENSE_SYSTEM = """你是 OPUS 的认知凝练器——从 L2 状态卡变更史提炼跨周稳定的 L1 了解。

规则：
1. 只提炼**跨周稳定**的模式（同一字段至少两次变更且最近一次 ≥3 天前、或用户显式说过"记住"）
2. 不把临时状态写进 L1（如"昨天没睡好"、"今天累了"）
3. 每条必须有 evidence 字段，带 as_of/来源
4. 短条：content ≤ 200 字，禁止整段聊天糊进去。日期故事不属于了解层。
5. 输出合法 JSON 对象，不要 markdown 围栏、不要前后解释

格式：{"entries": [{"field": "了解条目名", "content": "凝练内容", "evidence": "依据（带 as_of/来源）"}, ...], "style_dims": {"话量": 55, "调性": 50, "语气": 48, "礼节": 52, "表现力": 60}}

- entries：无符合条目时 []
- style_dims：**可选** · 只在相处模式有明确风格信号时给出微调值（0-100 整数）· 每次最多变动几个点 · 无信号则省略整个 style_dims 字段
  · 认他要的，不认关怀学：他说「别太正经」→ 调性略降 · 多次嫌话多 → 话量略降
  · 深夜 / 累 / 谢谢 / 难过 ≠ 语气往温柔。没人要软，语气不动"""


def _load_runtime_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_runtime_state(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _find_section(text: str, heading_key: str) -> tuple[int, int]:
    """按段标题关键字定位。返回 (start_idx, end_idx)。
    :注意: 不再限死只认二级标题(##) —— 了解层是无序号独立块，且它后面会紧跟着
    一级标题 `# BRO · 活人画像`。若只用 `## ` 切分，会把 `# BRO` 标题整段吞进了解层 body 一起替换。
    改为同时认 `# ` 与 `## `：任何以 '#' 开头的标题行都是切分点，一级标题不会再被误吞。
    """
    parts = re.split(r"^(#+ .+)$", text, flags=re.MULTILINE)
    if len(parts) < 3:
        return -1, -1
    for i in range(1, len(parts), 2):
        heading = parts[i].strip().lstrip("# ").strip()
        if heading_key in heading:
            start = text.find(parts[i])
            body = parts[i + 1] if i + 1 < len(parts) else ""
            end = start + len(parts[i]) + len(body)
            return start, end
    return -1, -1


def _count_history_rows(text: str) -> int:
    start, end = _find_section(text, HISTORY_HEADING_KEY)
    if start < 0:
        return 0
    body = text[start:end]
    n = 0
    for line in body.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        field = cells[0]
        if field in ("字段", "field") or set(field) <= set("-: |"):
            continue
        n += 1
    return n


def _parse_understanding_entries(section_body: str) -> dict[str, dict]:
    """解析了解层现有条目 · {field: {content, evidence}}。"""
    out: dict[str, dict] = {}
    for line in section_body.splitlines():
        m = re.match(
            r"^-\s+\*\*(.+?)\*\*[：:]\s*(.+?)(?:（依据[：:]\s*(.+?)）)?\s*$",
            line.strip(),
        )
        if not m:
            continue
        field, content, evidence = m.group(1).strip(), m.group(2).strip(), (m.group(3) or "").strip()
        out[field] = {"content": content, "evidence": evidence}
    return out


def _extract_events_excerpt(text: str, max_chars: int = 4000) -> str:
    start, end = _find_section(text, EVENTS_HEADING_KEY)
    if start < 0:
        return "（无事件流水段）"
    body = text[start:end].strip()
    if len(body) <= max_chars:
        return body
    return "…（截尾）\n" + body[-max_chars:]


def _format_state_card_for_prompt(state_card: dict) -> str:
    lines = []
    for field, entry in (state_card or {}).items():
        if not isinstance(entry, dict) or not entry.get("value"):
            continue
        lines.append(
            f"- {field}: {entry.get('value')} "
            f"(as_of={entry.get('as_of', '-')}, evidence={entry.get('evidence', '-')})"
        )
    return "\n".join(lines) if lines else "（状态卡为空）"


def _format_history_for_prompt(history: dict) -> str:
    if not history:
        return "（变更史为空）"
    lines = []
    for field, entries in history.items():
        for e in entries:
            lines.append(
                f"- {field}: {e.get('from', '?')} → {e.get('to', '?')} "
                f"(as_of={e.get('as_of', '-')}, evidence={e.get('evidence', '-')})"
            )
    return "\n".join(lines) if lines else "（变更史为空）"


def _format_existing_understanding(existing: dict[str, dict]) -> str:
    if not existing:
        return "（了解层当前为空）"
    lines = []
    for field, entry in existing.items():
        lines.append(
            f"- **{field}**：{entry.get('content', '')}"
            f"（依据：{entry.get('evidence', '-')}）"
        )
    return "\n".join(lines)


def _should_condense(
    *,
    force: bool,
    runtime: dict,
    history_count: int,
) -> tuple[bool, str]:
    if force:
        return True, "force"
    now = datetime.now(timezone.utc)
    last_at_raw = runtime.get("last_condensed_at")
    last_count = int(runtime.get("last_history_count") or 0)
    delta = history_count - last_count

    if last_at_raw:
        try:
            last_at = datetime.fromisoformat(str(last_at_raw).replace("Z", "+00:00"))
            if last_at.tzinfo is None:
                last_at = last_at.replace(tzinfo=timezone.utc)
            if now - last_at >= timedelta(days=CONDENSE_DAYS):
                return True, f">= {CONDENSE_DAYS} days since last condense"
        except Exception:
            pass
    elif history_count > 0:
        return True, "never condensed but history exists"

    if delta >= HISTORY_DELTA_THRESHOLD:
        return True, f">= {HISTORY_DELTA_THRESHOLD} new history rows ({delta})"

    reasons = []
    if last_at_raw:
        reasons.append(f"< {CONDENSE_DAYS} days since last condense")
    else:
        reasons.append("no prior condense")
    reasons.append(f"history delta {delta} < {HISTORY_DELTA_THRESHOLD}")
    return False, "; ".join(reasons)


def _call_llm(system: str, user: str) -> tuple[str, dict, Optional[str]]:
    from daemon_runtime import RUNTIME, bg_max_tokens

    if RUNTIME.client is None:
        return "", {}, "RUNTIME.client 未初始化 · daemon 没启动?"
    raw, usage, error = "", {}, None
    _bg_mt = bg_max_tokens()
    try:
        if RUNTIME.provider == "anthropic":
            resp = RUNTIME.client.messages.create(
                model=RUNTIME.model,
                max_tokens=_bg_mt,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            for block in resp.content:
                if getattr(block, "type", "") == "text":
                    raw += block.text
            usage = {
                "input_tokens": getattr(resp.usage, "input_tokens", 0),
                "output_tokens": getattr(resp.usage, "output_tokens", 0),
            }
        else:
            resp = RUNTIME.client.chat.completions.create(
                model=RUNTIME.model,
                max_tokens=_bg_mt,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            raw = resp.choices[0].message.content or ""
            usage = {
                "input_tokens": getattr(resp.usage, "prompt_tokens", 0),
                "output_tokens": getattr(resp.usage, "completion_tokens", 0),
            }
    except Exception as e:
        error = f"LLM call failed: {e}"
        logger.exception("state_condenser LLM error")
    return raw, usage, error


def _load_style_dims(path: Path) -> dict:
    from identity import style_dims

    return style_dims(path=path).get("dims") or {k: 50 for k in STYLE_DIM_KEYS}


def _save_style_dims(path: Path, dims: dict) -> bool:
    """写回 SHE-STATE.md。生产 json 旧路径一律重定向，避免再分叉。"""
    from identity import adjust_style_dims, style_dims

    try:
        if path.resolve() == _OLD_STYLE_DIMS_JSON.resolve() or path.suffix.lower() == ".json":
            path = DEFAULT_STYLE_DIMS
    except Exception:
        if path.suffix.lower() == ".json":
            path = DEFAULT_STYLE_DIMS
    cleaned: dict[str, int] = {}
    if isinstance(dims, dict) and "语气" not in dims and "力度" in dims:
        dims = {**dims, "语气": dims["力度"]}
    for k in STYLE_DIM_KEYS:
        v = dims.get(k)
        if not isinstance(v, (int, float)):
            continue
        iv = int(round(v))
        if iv < 0 or iv > 100:
            return False
        cleaned[k] = iv
    if len(cleaned) != len(STYLE_DIM_KEYS):
        return False
    current = style_dims(path=path).get("dims") or {k: 50 for k in STYLE_DIM_KEYS}
    signals: dict[str, int] = {}
    for k in STYLE_DIM_KEYS:
        delta = cleaned[k] - int(current.get(k, 50))
        if delta:
            signals[f"{k}_delta"] = delta
    if not signals:
        return True
    try:
        adjust_style_dims(signals, evidence="周度凝练", path=path)
        return True
    except Exception:
        logger.exception("save style dims to SHE-STATE failed")
        return False


def _format_style_dims_for_prompt(dims: dict) -> str:
    lines = []
    for k in STYLE_DIM_KEYS:
        lines.append(f"- {k}: {dims.get(k, 50)}")
    return "\n".join(lines)


def _parse_condense_response(raw: str) -> tuple[list[dict], Optional[dict]]:
    from workers.trend_finder import _extract_json_array

    text = (raw or "").strip()
    if not text:
        return [], None

    style_dims: Optional[dict] = None
    entries: list[dict] = []

    obj = None
    try:
        obj = json.loads(text)
    except Exception:
        pass

    if isinstance(obj, dict):
        style_raw = obj.get("style_dims")
        if isinstance(style_raw, dict):
            style_dims = style_raw
        items = obj.get("entries")
        if items is None:
            items = obj.get("understanding")
        if isinstance(items, list):
            entries = _parse_entry_list(items)
            return entries, style_dims

    parsed = _extract_json_array(text) or []
    if parsed and isinstance(parsed[0], dict) and "entries" not in parsed[0]:
        return _parse_entry_list(parsed), None
    return [], None


def _parse_entry_list(items: list) -> list[dict]:
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        field = (item.get("field") or "").strip()
        content = (item.get("content") or item.get("value") or "").strip()
        evidence = (item.get("evidence") or "").strip()
        if not field or not content:
            continue
        if len(content) > 200 or content.count("\n") >= 6:
            continue
        out.append({"field": field, "content": content, "evidence": evidence})
    return out


def _parse_entries(raw: str) -> list[dict]:
    entries, _ = _parse_condense_response(raw)
    return entries


def _merge_entries(
    existing: dict[str, dict],
    new_entries: list[dict],
) -> dict[str, dict]:
    merged = dict(existing)
    for item in new_entries:
        merged[item["field"]] = {
            "content": item["content"],
            "evidence": item.get("evidence") or "-",
        }
    return merged


def _render_understanding_body(merged: dict[str, dict]) -> str:
    intro = (
        "> 长期模式：\"BRO 是 JRPG 老炮\" / \"上班后易冲突\" 这类跨周稳定的了解。\n"
        "> 唯一写入者：周度凝练 worker（每周最多一次）或 BRO 显式说\"记住这个\"。\n"
    )
    if not merged:
        return intro + "> 当前为空 · 等第一次凝练写入。\n"
    lines = [intro.rstrip(), ""]
    for field in sorted(merged.keys()):
        entry = merged[field]
        lines.append(
            f"- **{field}**：{entry.get('content', '')}"
            f"（依据：{entry.get('evidence', '-')}）"
        )
    return "\n".join(lines) + "\n"


def _replace_understanding_section(text: str, new_body: str) -> str:
    start, end = _find_section(text, UNDERSTANDING_HEADING_KEY)
    if start < 0:
        # 纯净版/空文件可能还没有了解层段 —— 不能静默丢弃凝练结果。
        # 在「状态卡」段结束之后插入「## 了解层」段（用 sc_end 避免状态卡在文首时插到最前）。
        # 若没有状态卡段则插到文件开头（此时文件通常很空/全新）。
        intro = f"## 了解层（L1 稳定前缀 · 周度凝练 · 只有凝练/用户显式能写）\n\n{new_body.rstrip()}\n\n"
        sc_start, sc_end = _find_section(text, STATE_CARD_HEADING_KEY)
        if sc_start >= 0:
            return text[:sc_end] + intro + text[sc_end:]
        return intro + text
    parts = re.split(r"^(#+ .+)$", text, flags=re.MULTILINE)
    for i in range(1, len(parts), 2):
        heading = parts[i].strip().lstrip("# ").strip()
        if UNDERSTANDING_HEADING_KEY in heading:
            header = parts[i]
            new_section = f"{header}\n\n{new_body.rstrip()}\n"
            old_section = header + (parts[i + 1] if i + 1 < len(parts) else "")
            sec_start = text.find(old_section)
            if sec_start < 0:
                return text
            return text[:sec_start] + new_section + text[sec_start + len(old_section):]
    return text


def _write_notebook(text: str, notebook_path: Path) -> None:
    from soul_loader import write_global_then_sync

    write_global_then_sync(NOTEBOOK_FILENAME, text, ROOT)
    try:
        from workers.memory_index import incremental_update
        incremental_update(Path(NOTEBOOK_FILENAME).stem, text)
    except Exception:
        pass
    if notebook_path.resolve() == DEFAULT_NOTEBOOK.resolve():
        try:
            from daemon_runtime import reload_soul_into_runtime
            reload_soul_into_runtime()
        except Exception:
            pass


def condense_state_card(
    *,
    force: bool = False,
    notebook_path: Optional[Path] = None,
    runtime_path: Optional[Path] = None,
    style_dims_path: Optional[Path] = None,
) -> dict:
    """L2 → L1 周度凝练 · 条件触发 + 开机补偿。"""
    nb_path = notebook_path or DEFAULT_NOTEBOOK
    rt_path = runtime_path or DEFAULT_RUNTIME
    sd_path = style_dims_path or DEFAULT_STYLE_DIMS
    try:
        if not nb_path.exists():
            return {"skipped": True, "reason": f"notebook not found: {nb_path}"}

        text = nb_path.read_text(encoding="utf-8")
        runtime = _load_runtime_state(rt_path)
        history_count = _count_history_rows(text)

        # 了解层已抽过。自动跑不再让模型改写；force 只落提案，不覆盖本子。
        if not force:
            return {
                "skipped": True,
                "reason": "了解层冻结 · 只追加不重写",
                "frozen": True,
                "history_count": history_count,
            }

        ok, reason = _should_condense(
            force=force, runtime=runtime, history_count=history_count,
        )
        if not ok:
            return {"skipped": True, "reason": reason, "history_count": history_count}

        from workers.cognition_loader import _parse_state_card, _parse_state_card_history

        state_card = _parse_state_card(text)
        history = _parse_state_card_history(text)

        u_start, u_end = _find_section(text, UNDERSTANDING_HEADING_KEY)
        existing = {}
        if u_start >= 0:
            body = text[u_start:u_end]
            header_end = body.find("\n")
            existing = _parse_understanding_entries(body[header_end:] if header_end >= 0 else body)

        current_style_dims = _load_style_dims(sd_path)

        user_prompt = f"""## 状态卡当前值
{_format_state_card_for_prompt(state_card)}

## 状态卡变更史（全部）
{_format_history_for_prompt(history)}

## 事件流水（最近段 · 可追溯）
{_extract_events_excerpt(text)}

## 了解层现有条目（合并时保留未被推翻的）
{_format_existing_understanding(existing)}

## 风格四维当前值（慢旋钮 · 无明确相处信号时不要给 style_dims）
{_format_style_dims_for_prompt(current_style_dims)}

请输出 JSON 对象 · entries 只含跨周稳定的新增/更新条目 · style_dims 仅在确有信号时微调（省略=不动）。"""

        raw, usage, error = _call_llm(CONDENSE_SYSTEM, user_prompt)
        if error:
            return {"skipped": True, "error": error, "reason": reason}
        if not raw.strip():
            return {"skipped": True, "error": "LLM returned empty", "reason": reason}

        new_entries, new_style_dims = _parse_condense_response(raw)
        merged = _merge_entries(existing, new_entries)
        new_body = _render_understanding_body(merged)
        _ = new_style_dims

        proposal = (ROOT / "data" / "runtime" / "understanding_proposal.md")
        if runtime_path is not None:
            proposal = Path(runtime_path).parent / "understanding_proposal.md"
        proposal.parent.mkdir(parents=True, exist_ok=True)
        proposal.write_text(
            "# 了解层提案 · 未写入本子\n\n"
            f"reason: {reason}\n\n"
            f"{new_body.rstrip()}\n",
            encoding="utf-8",
        )

        now_iso = datetime.now(timezone.utc).isoformat()
        runtime.update({
            "last_proposal_at": now_iso,
            "last_history_count": history_count,
            "last_entry_count": len(merged),
        })
        _save_runtime_state(rt_path, runtime)

        return {
            "skipped": False,
            "applied": False,
            "proposal": str(proposal),
            "condensed": len(new_entries),
            "entries": new_entries,
            "total_entries": len(merged),
            "history_count": history_count,
            "reason": reason,
            "usage": usage,
            "style_dims_updated": False,
        }
    except Exception as e:
        logger.exception("state_condenser failed")
        return {"skipped": True, "error": str(e)}
