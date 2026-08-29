"""原生 tools[] 只挂核心手。其余进目录，用 catalog_search / catalog_call。

对照 OpenClaw directory / dsh-economizer / Ratel：tools[] 字节锁死，
全文 schema 不进前缀。DeepSeek 前缀缓存认 tools[]，名单不能按消息变。
"""
from __future__ import annotations

import contextvars
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
CORE = frozenset({
    "read_file", "write_file", "edit_file",
    "grep_files", "glob_files", "search_code", "outline_file",
    "shell_exec", "python_exec",
    "look_at", "web_search", "web_fetch",
    "recall_memory", "session_search", "read_scenario",
    "wechat_send", "read_clipboard", "write_clipboard",
    "set_emotion", "request_restart",
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


def deferred_names(allowed: set[str] | None = None) -> list[str]:
    from agent_tools import REGISTRY
    allowed = _bound_allowed(allowed)
    vis = visible_names(allowed)
    out = []
    for name in sorted(REGISTRY):
        if name in vis:
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


def directory_block(allowed: set[str] | None = None) -> str:
    """稳定前缀里的名字目录。按名排序，字节随 REGISTRY 锁死。"""
    if not catalog_enabled() or is_tight_allowlist(allowed):
        return ""
    from agent_tools import REGISTRY
    rows = []
    for name in deferred_names(allowed):
        spec = REGISTRY.get(name)
        if spec is None:
            continue
        rows.append(f"- {name}: {_one_line(spec.description)}")
    if not rows:
        return ""
    header = (
        "\n## 更多工具（不在本轮 tools[]）\n"
        "核心手可直接调。下面这些用 catalog_search 找，或 catalog_call"
        "(name=工具名, args={...}) 直接调。名字对就行，不必先 search。\n"
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


def resolve_call(name: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """catalog_call → 目标工具。其它名字原样返回（含幻觉的延期工具名，后面按 REGISTRY 水合）。"""
    if name != CATALOG_CALL:
        return name, args
    target = str(args.get("name") or args.get("tool") or "").strip()
    inner = args.get("args")
    if not isinstance(inner, dict):
        inner = args.get("arguments")
    if not isinstance(inner, dict):
        inner = {}
    return target, inner


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
        for tok in q.replace("，", " ").replace(",", " ").split():
            if tok and tok in name.lower():
                score += 4
            if tok and tok in desc:
                score += 2
        if score:
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
