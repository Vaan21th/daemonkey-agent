"""把已经叉进内核的魔改收成叠层 MOD。

能叠的（改过的官方工具）写进 tools/，下次升级不再跟这份文件打架。
叠不了的（chat.js / workers / 官方路由）进 legacy/ 当草稿，合并兜底仍在。
不自动改接管中的内核文件，也不假装前端 fork 已经能跑。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from workers.fork_depth import classify_file
from workers.mod_runtime import ROOT, sanitize_id

BACKUP_DIR = ROOT / "data" / "runtime" / "user_overrides"
DEFAULT_MOD_ID = "harvest_legacy"

# 叠上去会冻住升级/收割自身，或根本没有遮蔽层
_NO_LIFT = {
    "agent_tools/update_core.py",
    "agent_tools/merge_user_override.py",
    "agent_tools/kernel_takeover.py",
    "agent_tools/harvest_overrides.py",
    "workers/core_update.py",
    "workers/core_fingerprint.py",
    "workers/mod_harvest.py",
    "core_manifest.json",
    "core_fingerprints.json",
    "daemon_api.py",
    "tool_loop.py",
    "soul_loader.py",
}


def _bak_name(rel: str) -> str:
    return rel.replace("/", "__").replace("\\", "__") + ".bak"


def _bak_to_path(name: str) -> Optional[str]:
    if not name.endswith(".bak"):
        return None
    return name[:-4].replace("__", "/")


def _user_bytes(rel: str, root: Path) -> Optional[bytes]:
    bak = root / "data" / "runtime" / "user_overrides" / _bak_name(rel)
    if bak.is_file():
        return bak.read_bytes()
    p = root / rel
    if p.is_file():
        return p.read_bytes()
    return None


def _collect_rels(root: Path) -> list[str]:
    found: list[str] = []
    bak_dir = root / "data" / "runtime" / "user_overrides"
    if bak_dir.is_dir():
        for f in sorted(bak_dir.iterdir()):
            rel = _bak_to_path(f.name) if f.is_file() else None
            if rel:
                found.append(rel)
    if root.resolve() == ROOT.resolve():
        try:
            from workers.core_update import dirty_kernel_files
            for rel in dirty_kernel_files():
                if rel not in found:
                    found.append(rel)
        except Exception:
            pass
        try:
            from workers.kernel_takeover import load as load_takeover
            for rel in load_takeover():
                if rel not in found:
                    found.append(rel)
        except Exception:
            pass
    return found


def _kind(rel: str) -> str:
    rel = rel.replace("\\", "/")
    if rel in _NO_LIFT:
        return "skip"
    if rel.startswith("agent_tools/") and rel.endswith(".py"):
        if not Path(rel).name.startswith("_"):
            return "lift"
    return "draft"


def preview(root: Optional[Path] = None) -> dict:
    base = root or ROOT
    taken = set()
    try:
        from workers.kernel_takeover import load as load_takeover
        taken = set(load_takeover())
    except Exception:
        pass
    lift, draft, skip = [], [], []
    for rel in _collect_rels(base):
        rel = rel.replace("\\", "/")
        raw = _user_bytes(rel, base)
        if raw is None:
            continue
        kind = _kind(rel)
        official = None
        cur = base / rel
        if cur.is_file() and (base / "data" / "runtime" / "user_overrides" / _bak_name(rel)).is_file():
            try:
                official = cur.read_text(encoding="utf-8", errors="replace")
            except Exception:
                official = None
        user_text = None
        try:
            user_text = raw.decode("utf-8")
        except Exception:
            user_text = None
        depth = classify_file(
            rel,
            official_text=official,
            user_text=user_text,
            takeover=rel in taken,
        )
        row = {
            "file": rel,
            "depth": depth["depth"],
            "reason": depth["reason"],
            "bytes": len(raw),
        }
        if kind == "lift":
            row["dest"] = f"tools/{Path(rel).name}"
            row["why"] = "官方工具可遮蔽，收下后这份内核不再需要合并"
            lift.append(row)
        elif kind == "skip":
            row["why"] = "升级/收割机制，不能叠上去冻住"
            skip.append(row)
        else:
            row["dest"] = f"legacy/{rel}"
            row["why"] = "没有叠层位（前端/worker/官方路由），只进草稿"
            draft.append(row)
    return {"lift": lift, "draft": draft, "skip": skip}


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def already_lifted(root: Optional[Path] = None) -> dict:
    """官方工具路径 → 已经叠在哪。叠上的不要再合并回内核。"""
    base = root or ROOT
    out: dict = {}
    ud = base / "agent_tools_user"
    if ud.is_dir():
        for p in ud.glob("*.py"):
            if not p.name.startswith("_"):
                out[f"agent_tools/{p.name}"] = f"agent_tools_user/{p.name}"
    md = base / "data" / "mods"
    if md.is_dir():
        for folder in sorted(md.iterdir()):
            tools = folder / "tools"
            if not folder.is_dir() or not tools.is_dir():
                continue
            for p in tools.glob("*.py"):
                if p.name.startswith("_"):
                    continue
                out[f"agent_tools/{p.name}"] = (
                    f"data/mods/{folder.name}/tools/{p.name}")
    return out


def _exclude_set(exclude) -> set:
    out = set()
    if not exclude:
        return out
    if isinstance(exclude, str):
        exclude = [x.strip() for x in exclude.split(",") if x.strip()]
    for x in exclude:
        out.add(str(x).replace("\\", "/"))
    return out


def format_upgrade_guide(
    *,
    root: Optional[Path] = None,
    takeover: Optional[list] = None,
    incoming: Optional[list] = None,
) -> str:
    """覆盖之后唯一向导：能叠的先收，叠不了的才合并/用回。"""
    base = root or ROOT
    plan = preview(base)
    done = already_lifted(base)
    taken = {str(x).replace("\\", "/") for x in (takeover or [])}
    lift = [r for r in plan["lift"] if r["file"] not in done]
    lost = [r for r in plan["draft"] if r["file"] not in taken]
    held = [r for r in plan["draft"] if r["file"] in taken]
    if not (lift or lost or held or incoming):
        return ""
    lines = [
        "── 接下来只走这一条（不要同时合并又收割）──",
        "你的字在升级前的 checkpoint 和 data/runtime/user_overrides/，没丢。",
        "现在跑的是官方版（已接管的除外）。",
    ]
    if lift:
        lines.append("")
        lines.append(f"① 先做：能叠的工具 ({len(lift)}) · 说「把工具魔改收成 MOD」")
        lines += [f"  + {r['file']}" for r in lift]
        lines.append("  叠上后工具行为回来，这份内核不用再合并。")
    if lost:
        lines.append("")
        lines.append(f"② 叠不了 ({len(lost)}) · 收成 MOD 也不会自己跑")
        lines += [f"  · {r['file']}" for r in lost]
        one = lost[0]["file"]
        lines.append(f"  要界面/行为回来：说「用回我的 {one}」或「合并 {one}」。")
        lines.append("  先用官方这版也行，备份留着，不强迫。")
    if held:
        lines.append("")
        lines.append("已接管、磁盘没覆盖（你现在跑的还是你的字）:")
        lines += [f"  = {r['file']}" for r in held]
        if incoming:
            lines.append("  官方新版在 data/runtime/official_incoming/，可对照摘修复。")
    elif incoming:
        lines.append("")
        lines.append("已接管文件的官方新版在 data/runtime/official_incoming/。")
    return "\n".join(lines)


def apply(mod_id: str = DEFAULT_MOD_ID, *, root: Optional[Path] = None,
          scope: str = "tools", exclude=None) -> dict:
    """默认只叠工具。scope=all 才把前端/worker 存进 legacy/ 草稿。"""
    base = root or ROOT
    mid = sanitize_id(mod_id or DEFAULT_MOD_ID)
    scope = (scope or "tools").strip().lower()
    if scope not in ("tools", "draft", "all"):
        return {"ok": False, "mod_id": mid, "lifted": [], "drafted": [],
                "note": "scope 用 tools / draft / all"}
    skip = _exclude_set(exclude)
    plan = preview(base)
    want_lift = ([r for r in plan["lift"] if r["file"] not in skip]
                 if scope in ("tools", "all") else [])
    want_draft = ([r for r in plan["draft"] if r["file"] not in skip]
                  if scope in ("draft", "all") else [])
    leftover = [r["file"] for r in plan["draft"] if r["file"] not in skip]
    if not (want_lift or want_draft):
        note = "没有可叠的工具" if scope == "tools" and leftover else (
            "没有可收的内核魔改（备份/脏文件/接管都是空的）")
        return {"ok": True, "mod_id": mid, "lifted": [], "drafted": [],
                "leftover_draft": leftover, "note": note}
    folder = base / "data" / "mods" / mid
    folder.mkdir(parents=True, exist_ok=True)
    lifted, drafted = [], []
    for row in want_lift:
        raw = _user_bytes(row["file"], base)
        if raw is None:
            continue
        _write(folder / row["dest"], raw)
        lifted.append(row["file"])
    for row in want_draft:
        raw = _user_bytes(row["file"], base)
        if raw is None:
            continue
        _write(folder / row["dest"], raw)
        drafted.append(row["file"])
    if not (lifted or drafted):
        return {"ok": True, "mod_id": mid, "lifted": [], "drafted": [],
                "leftover_draft": leftover, "note": "没有可读的备份内容"}
    meta = {
        "id": mid,
        "name": "升级收割的旧魔改",
        "version": time.strftime("%Y.%m.%d"),
        "description": "从内核备份/接管收来的叠层。tools/ 能跑；legacy/ 只是草稿。",
        "enabled": True,
        "harvested_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (folder / "mod.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    still = [f for f in leftover if f not in drafted]
    lines = [
        "# 这次收割",
        "",
        "tools/ 盖住内核同名工具，升级不再跟这些文件合并。",
        "legacy/ 不会自动跑。要行为还在，用回备份或合并。",
        "",
        f"叠上的工具 ({len(lifted)}):",
    ]
    lines += [f"- {x}" for x in lifted] or ["- （无）"]
    lines += ["", f"只进草稿 ({len(drafted)}):"]
    lines += [f"- {x}" for x in drafted] or ["- （无）"]
    if still:
        lines += ["", "还没处理、叠不了:"]
        lines += [f"- {x}" for x in still]
    (folder / "HARVEST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "mod_id": mid,
        "path": str(folder).replace("\\", "/"),
        "lifted": lifted,
        "drafted": drafted,
        "leftover_draft": still,
        "skipped": [r["file"] for r in plan["skip"]],
    }
