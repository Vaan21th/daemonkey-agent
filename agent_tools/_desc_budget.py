"""工具 description 预算。

简介只写「何时伸这只手」。超线 = 工艺被焊进了 schema。
闸在 register_tool 导入时拦截 · CLI 见 tools/check_tool_descriptions.py。
"""

from __future__ import annotations

MAX_DESC_TOKENS = 180

_enc = None


def count_desc_tokens(text: str) -> int:
    global _enc
    try:
        if _enc is None:
            import tiktoken
            _enc = tiktoken.get_encoding("cl100k_base")
        return len(_enc.encode(text or ""))
    except Exception:
        # 没装 tiktoken 也不能放行 · 按偏严估算
        return max(1, (len(text or "") + 1) // 2)


def assert_description_budget(name: str, text: str) -> None:
    n = count_desc_tokens(text)
    if n > MAX_DESC_TOKENS:
        raise ValueError(
            f"tool {name!r} description {n} tok > {MAX_DESC_TOKENS} "
            f"(简介两句 · 工艺进 read_scenario/playbook · 每回合事故句进铁律/Runtime)"
        )


def audit_registry(registry: dict) -> list[dict]:
    over = []
    for name, spec in sorted(registry.items()):
        n = count_desc_tokens(getattr(spec, "description", "") or "")
        if n > MAX_DESC_TOKENS:
            over.append({"name": name, "tok": n, "over": n - MAX_DESC_TOKENS})
    return over
