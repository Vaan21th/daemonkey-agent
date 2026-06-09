# -*- coding: utf-8 -*-
"""workers/edit_selfcheck.py · 编辑后即时自检 (卷五十四 · B4 · "锁出口不锁动作")

write_file / python_exec 改完 daemon 核心 .py 或 static/*.js 后 · 即时验一下语法。
**只告警 · 不回退 · 不拦** —— OPUS 可能正改到一半 (多步编辑中途文件本就可能瞬时坏)。
等于给 OPUS 一面随身镜子: "你刚把 X 改出语法错了 · 这版直接重启/上线会崩"。

真正的硬拦在【出口】:
  request_restart (前端 JS 闸) · merge_wish_to_master (B2 上线闸) · daemon 启动 (A2 自检自愈)。
这里只负责让 OPUS【当场看见】· 不剥夺它继续改 / 改到一半 / 用奇技淫巧的自由。

ast.parse 只验语法 · 不执行代码 · 不写 .pyc · 零副作用。
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent

_SURFACE_DIRS = ("workers", "agent_tools", "api_routes")
_SURFACE_TOP_FILES = ("daemon_api.py", "daemon_runtime.py", "soul_loader.py",
                      "opus_daemon.py", "tool_loop.py")


def _rel(p) -> str:
    try:
        return str(Path(p).resolve().relative_to(ROOT)).replace("\\", "/")
    except Exception:
        return str(p).replace("\\", "/")


def _is_surface_py(rel: str) -> bool:
    return rel.endswith(".py") and (
        rel in _SURFACE_TOP_FILES or any(rel.startswith(d + "/") for d in _SURFACE_DIRS))


def _is_surface_js(rel: str) -> bool:
    return rel.startswith("static/") and rel.endswith(".js")


def _py_syntax_error(path: Path) -> Optional[str]:
    try:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        return None
    except SyntaxError as e:
        return f"SyntaxError 第 {e.lineno} 行: {e.msg}"
    except FileNotFoundError:
        return None  # 删了 · 不是语法问题
    except Exception as e:
        return f"{type(e).__name__}: {e}"


def _surface_files() -> list[Path]:
    files: list[Path] = []
    for d in _SURFACE_DIRS:
        dp = ROOT / d
        if dp.exists():
            files += list(dp.rglob("*.py"))
    for f in _SURFACE_TOP_FILES:
        p = ROOT / f
        if p.exists():
            files.append(p)
    sd = ROOT / "static"
    if sd.exists():
        files += list(sd.glob("*.js"))
    return files


def snapshot_mtimes() -> dict[str, float]:
    """python_exec 跑代码前拍一张 surface 文件 mtime 快照 · 用来精准定位它改了哪些 (避免误报别人的脏文件)。"""
    out: dict[str, float] = {}
    for p in _surface_files():
        try:
            out[str(p)] = p.stat().st_mtime
        except OSError:
            pass
    return out


def _format_warning(problems: list[str]) -> str:
    # 这条警告会被 append 到 write_file/edit_file/python_exec(透传类·不在 tool_loop 白名单)的
    # output 里喂回 LLM·所以在源头去母体化(抹卷号·母体 no-op)。
    from identity import localize_narration as _ln
    return _ln(
        "⚠️  编辑后自检 (卷五十四 B4): 你刚改的文件现在【语法坏了】· 这版直接重启/上线会崩 —\n"
        + "\n".join(problems)
        + "\n  (这只是提醒 · 没拦你 · 你可能正改到一半。 但记得修好再 request_restart / merge ·"
          " 否则会被出口硬闸挡下 · 或启动时被 A2 自动回退到 last-good。)"
    )


def selfcheck(paths: list[str]) -> tuple[bool, str]:
    """校验给定路径里的 daemon 表面 .py / static js。 返 (ok, warning) · ok=True 时 warning 空。"""
    rels = [_rel(p) for p in paths]
    problems: list[str] = []
    for rel in rels:
        if _is_surface_py(rel):
            err = _py_syntax_error(ROOT / rel)
            if err:
                problems.append(f"  · {rel}: {err}")
    if any(_is_surface_js(r) for r in rels):
        try:
            from workers.frontend_check import check_static_js
            fe = check_static_js()
            if not fe["ok"]:
                problems.append("  · 前端 JS: " + ("; ".join(fe.get("problems", []))[:200] or "语法错"))
        except Exception:
            pass
    if not problems:
        return True, ""
    return False, _format_warning(problems)


def selfcheck_changed(before: dict[str, float]) -> tuple[bool, str]:
    """对比 before 快照 · 只校验本次 (python_exec) 真改动/新建过的 surface 文件。"""
    after = snapshot_mtimes()
    changed = [p for p, m in after.items() if before.get(p) != m]
    if not changed:
        return True, ""
    return selfcheck(changed)
