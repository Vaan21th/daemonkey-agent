"""叠层自检。只解析，不执行用户代码。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from workers.mod_runtime import ROOT, _iter_py, list_mods, sanitize_id, set_enabled


def _syntax(path: Path) -> str:
    try:
        src = path.read_text(encoding="utf-8-sig")
    except Exception as e:
        return f"读不了 ({type(e).__name__})"
    try:
        compile(src, str(path), "exec")
    except SyntaxError as e:
        return f"SyntaxError:{e.lineno}"
    except Exception as e:
        return type(e).__name__
    return ""


def inspect(root: Optional[Path] = None) -> dict:
    base = root or ROOT
    mods = []
    for m in list_mods(base):
        folder = Path(m["path"])
        problems = []
        if not (folder / "mod.json").is_file():
            problems.append("缺 mod.json")
        for p in _iter_py(folder / "tools"):
            err = _syntax(p)
            if err:
                problems.append(f"tools/{p.name}: {err}")
        for p in _iter_py(folder / "routes"):
            err = _syntax(p)
            if err:
                problems.append(f"routes/{p.name}: {err}")
        js = folder / "ui" / "mod.js"
        if js.is_file() and js.stat().st_size == 0:
            problems.append("ui/mod.js 是空的")
        mods.append({
            "id": m["id"],
            "enabled": bool(m.get("enabled")),
            "ok": not problems,
            "problems": problems,
        })
    user = []
    ud = base / "agent_tools_user"
    for p in _iter_py(ud):
        err = _syntax(p)
        if err:
            user.append({"file": f"agent_tools_user/{p.name}", "ok": False,
                         "problems": [err]})
    return {"mods": mods, "user_tools": user}


def format_report(rep: dict) -> str:
    mods = rep.get("mods") or []
    user = rep.get("user_tools") or []
    if not mods and not user:
        return ""
    bad = [m for m in mods if m.get("enabled") and not m.get("ok")]
    lines = ["叠层自检:"]
    for m in mods:
        flag = "开" if m.get("enabled") else "关"
        if m.get("ok"):
            lines.append(f"  [{flag}] {m['id']} · 正常")
            continue
        lines.append(f"  [{flag}][坏] {m['id']}")
        for p in m.get("problems") or []:
            lines.append(f"    · {p}")
        if m.get("enabled"):
            lines.append(f"    说「停用 MOD {m['id']}」回官方，或修好再说「启用 MOD {m['id']}」。")
    for u in user:
        lines.append(f"  [本机][坏] {u['file']} · {', '.join(u.get('problems') or [])}")
        lines.append("    官方同名工具会露出来。修好或把文件挪走。")
    if not bad and not user:
        n = sum(1 for m in mods if m.get("enabled"))
        return f"叠层自检：{n} 个启用中的 MOD 都正常。"
    return "\n".join(lines)


def disable(mod_id: str, *, root: Optional[Path] = None) -> tuple[bool, str]:
    return set_enabled(sanitize_id(mod_id), False, root=root)


def enable(mod_id: str, *, root: Optional[Path] = None) -> tuple[bool, str]:
    return set_enabled(sanitize_id(mod_id), True, root=root)
