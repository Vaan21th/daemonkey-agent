"""原生 tools[] 只挂核心手。其余进目录，用 catalog_search / catalog_call。

对照 OpenClaw directory / dsh-economizer / Ratel：tools[] 字节锁死，
全文 schema 不进前缀。DeepSeek 前缀缓存认 tools[]，名单不能按消息变。
"""
from __future__ import annotations

import contextvars
import json
import os
from typing import Any

_allowed_cv: contextvars.ContextVar[set[str] | None] = contextvars.ContextVar(
    "tool_catalog_allowed", default=None
)


def set_catalog_allowed(allowed: set[str] | None) -> None:
    _allowed_cv.set(allowed)


def _bound_allowed(allowed: set[str] | None) -> set[str] | None:
    return allowed if allowed is not None else _allowed_cv.get()

CATALOG_SEARCH = "catalog_search"
CATALOG_CALL = "catalog_call"

# 闲聊和写代码都要直接伸、不能先搜的手。工坊施工不在这里。
# 2026-09-16 B1（wish-be50a93a）：7 个生成类移出 → 进延迟目录（catalog_search/catalog_call）。
#   AB 实测：手边 37→30 命中率 69.8%→74.4%（+4.6pt，超波动 ±1.1pt）· 前缀 -2,230 tok。
#   原本担心的「Flash 嵌套 catalog_call.args 会吐空串」实测不成立：B1 比只移 4 个还高 3.5pt。
#   回档：把下面 7 个名字加回 CORE 即可（generate_presentation/report/image/spreadsheet +
#   revise_office/extend_office/illustrate_office）。
CORE = frozenset({
    "read_file", "write_file", "edit_file",
    "grep_files", "glob_files", "search_code", "outline_file",
    "shell_exec", "python_exec",
    "look_at", "web_search", "web_fetch", "inspect_office",
    "recall_memory", "session_search", "read_scenario",
    "wechat_send", "read_clipboard", "write_clipboard",
    "set_emotion", "request_restart", "note_style_shift", "note_mood", "note_gallery",
    "set_wakeup",  # wish-1b00ca00 · 延迟唤醒(计时器) · 「我 N 分钟后回来收结果」是热路径
    "mcp_list", "mcp_describe_tool", "mcp_call_tool",
    CATALOG_SEARCH, CATALOG_CALL,
})

# 分身 / taste 这种短名单保持全文暴露，不走目录。
_TIGHT_MAX = 40


def catalog_enabled() -> bool:
    v = (os.environ.get("OPUS_TOOL_CATALOG") or "1").strip().lower()
    return v not in ("0", "false", "off", "no")


def is_tight_allowlist(allowed: set[str] | None) -> bool:
    return allowed is not None and len(allowed) <= _TIGHT_MAX


def visible_names(allowed: set[str] | None) -> set[str]:
    from agent_tools import REGISTRY
    if not catalog_enabled():
        return set(REGISTRY) if allowed is None else set(allowed)
    if is_tight_allowlist(allowed):
        return set(allowed)
    names = set(CORE)
    if allowed is not None:
        names &= allowed
    return names


def visible_specs(allowed: set[str] | None) -> list:
    from agent_tools import REGISTRY
    keep = visible_names(allowed)
    return [REGISTRY[n] for n in sorted(keep) if n in REGISTRY]


def deferred_names(allowed: set[str] | None = None, exclude: set[str] | None = None) -> list[str]:
    """不在本轮可见集里的工具名（延迟目录候选）。

    exclude（wish-9de9bce3 · 精准磨）：已经全量进 tools[] 的那批 —— 不在目录里重复出现。
    """
    from agent_tools import REGISTRY
    allowed = _bound_allowed(allowed)
    vis = visible_names(allowed)
    ex = set(exclude) if exclude else ()
    out = []
    for name in sorted(REGISTRY):
        if name in vis:
            continue
        if ex and name in ex:
            continue
        if allowed is not None and name not in allowed:
            continue
        out.append(name)
    return out


def _one_line(text: str, n: int = 72) -> str:
    line = (text or "").strip().replace("\n", " ")
    return line if len(line) <= n else line[: n - 1] + "…"


# OpenClaw directory 上限 1.8 万字。超了按名截断，剩的靠 catalog_search。
_MAX_DIR_CHARS = 18000


def directory_block(allowed: set[str] | None = None, exclude: set[str] | None = None) -> str:
    """稳定前缀里的名字目录。按名排序，字节随 REGISTRY 锁死。

    exclude：已全量进 tools[] 的工具 —— 从目录里剔掉（不重复列出 · wish-9de9bce3）。
    """
    if not catalog_enabled() or is_tight_allowlist(allowed):
        return ""
    from agent_tools import REGISTRY
    rows = []
    for name in deferred_names(allowed, exclude=exclude):
        spec = REGISTRY.get(name)
        if spec is None:
            continue
        rows.append(f"- {name}: {_one_line(spec.description)}")
    if not rows:
        return ""
    header = (
        "\n=== 工具层 · 延迟工具目录（不在本轮 tools[] 里的） ===\n"
        "核心手可直接调。下面这些用 catalog_search 找，或 catalog_call"
        "(name=工具名, 参数与 name 平级；或 args 传 JSON 字符串)。"
        "名字对就行，不必先 search。args 不要空字符串。\n"
    )
    kept = list(rows)
    omitted = 0
    body = "\n".join(kept)
    while kept and len(header) + len(body) + 1 > _MAX_DIR_CHARS:
        kept.pop()
        omitted += 1
        body = "\n".join(kept)
    if omitted:
        body += f"\n…另有 {omitted} 个未列出，用 catalog_search 按能力找。"
    return header + body + "\n"


_CALL_META = frozenset({"name", "tool", "args", "arguments"})


def _as_object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def resolve_call(name: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """catalog_call → 目标工具。其它名字原样返回（含幻觉的延期工具名，后面按 REGISTRY 水合）。

    Flash 常把嵌套 args 吐成空串；也认 JSON 字符串，以及跟 name 平级的字段。
    """
    if name != CATALOG_CALL:
        return name, args
    target = str(args.get("name") or args.get("tool") or "").strip()
    inner = _as_object(args.get("args"))
    if inner is None:
        inner = _as_object(args.get("arguments"))
    if not inner:
        inner = {k: v for k, v in args.items() if k not in _CALL_META}
    return target, inner or {}


def _catalog_tokens(q: str) -> list[str]:
    """切词给 catalog_search 打分用。

    病根（2026-09-18 实测）：旧实现只按**空格**切，而中文没有空格 ——
    「记录他的状态」整串当一个 token，只有简介里逐字出现这七个字才得非零分。
    实测 9 条中文 query 里 8 条返空（唯一命中的是简介逐字含「状态卡」那条），
    延迟目录 110 件对中文使用者等于不可检索。
    修法：中文切 2-gram + 单字（英文照旧按空格），让「状态」「作息」这类词能命中。
    """
    raw = (q or "").replace("，", " ").replace(",", " ").replace("。", " ").split()
    out: list[str] = []
    for t in raw:
        if any("\u4e00" <= ch <= "\u9fff" for ch in t):
            if len(t) == 1:
                out.append(t)
            else:
                out.extend(t[i:i + 2] for i in range(len(t) - 1))
                out.append(t)
        else:
            out.append(t)
    return out


#: 单打独斗的噪声 bigram（如「他的」）不该把工具顶进结果 —— 低于此分不返回。
#: 实测（2026-09-18）：**4 太严会误伤已有检索**（「做个 PPT」从命中变空）；
#: 2 是「噪声可接受 + 不误伤」的分界。真正的信噪比靠**简介里有没有那批口语词**。
_MIN_CATALOG_SCORE = 2


def search(query: str, allowed: set[str] | None = None, limit: int = 8) -> list[dict[str, Any]]:
    from agent_tools import REGISTRY
    allowed = _bound_allowed(allowed)
    q = (query or "").strip().lower()
    if not q:
        return []
    scored: list[tuple[int, str]] = []
    for name in deferred_names(allowed):
        spec = REGISTRY.get(name)
        if spec is None:
            continue
        desc = (spec.description or "").lower()
        score = 0
        if q == name.lower():
            score += 50
        elif q in name.lower():
            score += 20
        if q in desc:
            score += 10
        for tok in _catalog_tokens(q):
            if tok and tok in name.lower():
                score += 4
            if tok and tok in desc:
                score += 2
        if score >= _MIN_CATALOG_SCORE:
            scored.append((score, name))
    scored.sort(key=lambda x: (-x[0], x[1]))
    out = []
    for score, name in scored[: max(1, min(limit, 20))]:
        spec = REGISTRY[name]
        item = {
            "name": name,
            "description": spec.description or "",
            "required": list((spec.input_schema or {}).get("required") or []),
        }
        if q == name.lower() or score >= 50:
            item["input_schema"] = spec.input_schema or {}
        out.append(item)
    return out
