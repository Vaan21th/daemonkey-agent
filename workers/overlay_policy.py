"""改装两头：写的时候提醒走叠层，上架时脏核必须剥干净。

母体（桌上有发布闸脚本）不提醒、不上架闸——母体就是改官方的。
纯净版官方文件仍能改，只是说清楚：升级会盖、MOD 带不走、市集要先剥。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from workers.fork_depth import is_overlay_path
from workers.mod_runtime import ROOT

_MOTHER_MARK = Path("tools") / "check_dk_release.ps1"

WRITE_HINT = (
    "这一层是官方文件。能改，但升级会盖掉；打 MOD 带不走，上架市集会被闸拦住。"
    "优先写 data/mods/<id>/（或 agent_tools_user / api_routes_user / static/user）。"
)

CONSTITUTION_EXTRA = """\
## 改装 · 优先叠层
加能力先写 data/mods/<id>/、agent_tools_user/、api_routes_user/、static/user/（别改 EXAMPLES.js）。
官方白名单文件也能改，升级会盖掉，打出来的 MOD 带不走这一层。
要上架市集：先说「把工具魔改收成 MOD」；页面改写成 addDomain / 钩子。剥不出来不上架。
本机改官方留着自己用可以。
"""


def is_mother(*, root: Optional[Path] = None) -> bool:
    return ((root or ROOT) / _MOTHER_MARK).is_file()


def _rel(path: Path | str, root: Path) -> str:
    p = Path(path)
    if not p.is_absolute():
        p = root / p
    try:
        return str(p.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return ""


def _kernel_set() -> set[str]:
    try:
        from workers.core_update import kernel_files
        return {str(x).replace("\\", "/") for x in kernel_files()}
    except Exception:
        return set()


def write_notice(path: Path | str, *, root: Optional[Path] = None,
                 mother: Optional[bool] = None) -> str:
    base = root or ROOT
    if mother is None:
        mother = is_mother(root=base)
    if mother:
        return ""
    rel = _rel(path, base)
    if not rel or is_overlay_path(rel):
        return ""
    if rel not in _kernel_set():
        return ""
    return WRITE_HINT


def attach_write_notice(path: Path | str, output: str, *,
                        root: Optional[Path] = None) -> str:
    note = write_notice(path, root=root)
    if not note:
        return output
    return f"{output}\n\n{note}"


def constitution_extra(*, root: Optional[Path] = None,
                       mother: Optional[bool] = None) -> str:
    base = root or ROOT
    if mother is None:
        mother = is_mother(root=base)
    if mother:
        return ""
    return CONSTITUTION_EXTRA


def publish_block(*, root: Optional[Path] = None, mother: Optional[bool] = None,
                  plan: Optional[dict] = None) -> str:
    """空串=可以上架。有字=拦住，并告诉人怎么剥。"""
    base = root or ROOT
    if mother is None:
        mother = is_mother(root=base)
    if mother:
        return ""
    if plan is None:
        from workers.mod_harvest import preview
        plan = preview(base)
    lift = [r.get("file") for r in (plan.get("lift") or []) if r.get("file")]
    draft = [r.get("file") for r in (plan.get("draft") or []) if r.get("file")]
    if not lift and not draft:
        return ""
    lines = ["市集只收叠层。本机还改着官方文件，包带不走这些改动。"]
    if lift:
        lines.append("还能剥成工具叠层，先说「把工具魔改收成 MOD」:")
        lines += [f"  + {f}" for f in lift[:12]]
    if draft:
        lines.append(
            "这些叠不了，改写成 data/mods 的 ui/tools/routes，或交还官方后再上架:")
        lines += [f"  · {f}" for f in draft[:12]]
    return "\n".join(lines)
