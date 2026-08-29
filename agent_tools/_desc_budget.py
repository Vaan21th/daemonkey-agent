"""工具名片预算：简介两句，字段一句。

超线 = 工艺被焊进每轮 tools JSON。闸在 register_tool 导入时拦。
写完 / 重启把超线写进 ToolResult，模型当场看见怎么收。
CLI: tools/check_tool_descriptions.py
"""
from __future__ import annotations

import ast
from pathlib import Path

MAX_DESC_TOKENS = 180
MAX_FIELD_TOKENS = 60

_FIX = (
    "怎么改：简介两句 ≤{desc} tok；每个 schema 字段一句 ≤{field} tok。"
    "工艺写进 data/cognition/scenarios/ 用 read_scenario 取。"
    "工坊 create_app 的应用简介不受这道闸管。"
).format(desc=MAX_DESC_TOKENS, field=MAX_FIELD_TOKENS)

_enc = None


def _approx_tokens(text: str) -> int:
    """tiktoken 不在时的近似：汉字≈1 tok，拉丁≈4 字/tok。宁松勿误杀。"""
    n = 0.0
    for ch in text or "":
        if "\u3400" <= ch <= "\u9fff":
            n += 0.8
        else:
            n += 0.22
    return max(1, int(n + 0.999))


def count_desc_tokens(text: str) -> int:
    global _enc
    try:
        if _enc is None:
            import tiktoken
            _enc = tiktoken.get_encoding("cl100k_base")
        return len(_enc.encode(text or ""))
    except Exception:
        return _approx_tokens(text or "")


def iter_schema_fields(schema: dict | None, path: str = ""):
    """Yield (dotted_path, description) for every field that has prose."""
    if not isinstance(schema, dict):
        return
    desc = schema.get("description")
    if isinstance(desc, str) and desc.strip() and path:
        yield path, desc
    for key, child in (schema.get("properties") or {}).items():
        child_path = f"{path}.{key}" if path else key
        yield from iter_schema_fields(child, child_path)
    items = schema.get("items")
    if isinstance(items, dict):
        yield from iter_schema_fields(items, f"{path}[]" if path else "[]")


def assert_description_budget(name: str, text: str) -> None:
    n = count_desc_tokens(text)
    if n > MAX_DESC_TOKENS:
        raise ValueError(
            f"tool {name!r} description {n} tok > {MAX_DESC_TOKENS} "
            f"(简介两句 · 工艺进 read_scenario)"
        )


def assert_schema_budget(name: str, schema: dict | None) -> None:
    overs = []
    for path, text in iter_schema_fields(schema or {}, name):
        n = count_desc_tokens(text)
        if n > MAX_FIELD_TOKENS:
            overs.append(f"{path} {n}tok")
    if overs:
        raise ValueError(
            f"tool {name!r} schema field over {MAX_FIELD_TOKENS} tok: "
            + ", ".join(overs)
            + " (字段一句 · 工艺进 read_scenario)"
        )


def audit_registry(registry: dict) -> list[dict]:
    over = []
    for name, spec in sorted(registry.items()):
        n = count_desc_tokens(getattr(spec, "description", "") or "")
        if n > MAX_DESC_TOKENS:
            over.append({"name": name, "tok": n, "over": n - MAX_DESC_TOKENS})
    return over


def audit_schema_registry(registry: dict) -> list[dict]:
    over = []
    for name, spec in sorted(registry.items()):
        schema = getattr(spec, "input_schema", None) or {}
        for path, text in iter_schema_fields(schema, name):
            n = count_desc_tokens(text)
            if n > MAX_FIELD_TOKENS:
                over.append({
                    "name": name,
                    "path": path,
                    "tok": n,
                    "over": n - MAX_FIELD_TOKENS,
                })
    return over


def _str_const(node):
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _str_const(node.left), _str_const(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _call_name(node) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def extract_toolspecs(src: str) -> list[tuple[str, str, dict | None]]:
    """Pull (name, description, schema-or-None) from ToolSpec(...) literals."""
    tree = ast.parse(src)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node.func) != "ToolSpec":
            continue
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        name = _str_const(kw.get("name"))
        desc = _str_const(kw.get("description"))
        if name is None and node.args:
            name = _str_const(node.args[0])
        if desc is None and len(node.args) > 1:
            desc = _str_const(node.args[1])
        schema = None
        raw_schema = kw.get("input_schema")
        if raw_schema is not None:
            try:
                schema = ast.literal_eval(raw_schema)
            except Exception:
                schema = None
        if name and desc is not None:
            found.append((name, desc, schema if isinstance(schema, dict) else None))
    return found


def audit_source(src: str, *, label: str = "") -> list[dict]:
    overs = []
    try:
        specs = extract_toolspecs(src)
    except SyntaxError:
        return overs
    for name, desc, schema in specs:
        n = count_desc_tokens(desc)
        if n > MAX_DESC_TOKENS:
            overs.append({
                "kind": "desc",
                "name": name,
                "path": name,
                "tok": n,
                "over": n - MAX_DESC_TOKENS,
                "file": label,
            })
        if not schema:
            continue
        for path, text in iter_schema_fields(schema, name):
            n = count_desc_tokens(text)
            if n > MAX_FIELD_TOKENS:
                overs.append({
                    "kind": "field",
                    "name": name,
                    "path": path,
                    "tok": n,
                    "over": n - MAX_FIELD_TOKENS,
                    "file": label,
                })
    return overs


def audit_file(path) -> list[dict]:
    p = Path(path)
    try:
        src = p.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return []
    return audit_source(src, label=p.name)


_SKIP_STEMS = {"set_model"}  # 与 __init__._OPT_OUT 对齐 · 不注册就不审盘


def audit_tools_dir(tools_dir=None) -> list[dict]:
    d = Path(tools_dir) if tools_dir else Path(__file__).resolve().parent
    overs = []
    for p in sorted(d.glob("*.py")):
        if p.name.startswith("_") or p.stem in _SKIP_STEMS:
            continue
        overs.extend(audit_file(p))
    return overs


def format_budget_hint(overs: list[dict], *, blocked_restart: bool = False) -> str:
    try:
        from identity import localize_narration as _ln
    except Exception:
        def _ln(text: str) -> str:
            return text
    if blocked_restart:
        head = "⛔ 重启被拦下 · 工具简介或字段超线（铁律 15）。现在重启，超标的那只手会装不上。"
    else:
        head = "⚠️  工具名片超线（铁律 15）· 这版直接重启，超标的那只手会装不上 —"
    lines = [head]
    for o in overs[:12]:
        where = o.get("path") or o.get("name")
        cap = MAX_FIELD_TOKENS if o.get("kind") == "field" else MAX_DESC_TOKENS
        kind = "字段" if o.get("kind") == "field" else "简介"
        lines.append(f"  · {where}  {kind} {o['tok']} tok（上限 {cap}，多 {o['over']}）")
    if len(overs) > 12:
        lines.append(f"  · …还有 {len(overs) - 12} 处")
    lines.append(_FIX)
    return _ln("\n".join(lines))


def boot_discovery_notice() -> str:
    """Empty when every tool loaded. Only then does the prefix grow."""
    try:
        from agent_tools import discovery_failures
        fails = discovery_failures()
    except Exception:
        return ""
    if not fails:
        return ""
    try:
        from identity import localize_narration as _ln
    except Exception:
        def _ln(text: str) -> str:
            return text
    lines = [
        "\n\n### 工具装载告警\n",
        "下面这些手启动时没挂上（简介/字段超线或 import 失败）。别的还能用。\n",
    ]
    for mod, err in fails[:8]:
        lines.append(f"  · {mod}: {err}\n")
    if len(fails) > 8:
        lines.append(f"  · …还有 {len(fails) - 8} 个\n")
    lines.append(_FIX + "\n")
    return _ln("".join(lines))


def unknown_tool_error(name: str) -> str:
    try:
        from agent_tools import discovery_failures
        fails = discovery_failures()
    except Exception:
        fails = []
    matched = [
        f"{mod}: {err}"
        for mod, err in fails
        if name == mod or f"'{name}'" in err or f'"{name}"' in err
    ]
    if not matched:
        return f"unknown tool: {name}"
    return f"unknown tool: {name}\n启动时没挂上: {matched[0]}\n{_FIX}"
