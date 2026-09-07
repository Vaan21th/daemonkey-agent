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


def apply(mod_id: str = DEFAULT_MOD_ID, *, root: Optional[Path] = None) -> dict:
    base = root or ROOT
    mid = sanitize_id(mod_id or DEFAULT_MOD_ID)
    plan = preview(base)
    if not (plan["lift"] or plan["draft"]):
        return {"ok": True, "mod_id": mid, "lifted": [], "drafted": [],
                "note": "没有可收的内核魔改（备份/脏文件/接管都是空的）"}
    folder = base / "data" / "mods" / mid
    folder.mkdir(parents=True, exist_ok=True)
    lifted, drafted = [], []
    for row in plan["lift"]:
        raw = _user_bytes(row["file"], base)
        if raw is None:
            continue
        _write(folder / row["dest"], raw)
        lifted.append(row["file"])
    for row in plan["draft"]:
        raw = _user_bytes(row["file"], base)
        if raw is None:
            continue
        _write(folder / row["dest"], raw)
        drafted.append(row["file"])
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
    lines = [
        "# 这次收割",
        "",
        "tools/ 里的官方工具会盖住内核同名工具，升级不再跟这些文件合并。",
        "legacy/ 里的前端和 worker **不会自动生效**。要行为还在，仍走合并或接管。",
        "重启 daemon 后 tools/ 才挂上。",
        "",
        f"叠上的工具 ({len(lifted)}):",
    ]
    lines += [f"- {x}" for x in lifted] or ["- （无）"]
    lines += ["", f"只进草稿 ({len(drafted)}):"]
    lines += [f"- {x}" for x in drafted] or ["- （无）"]
    (folder / "HARVEST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "mod_id": mid,
        "path": str(folder).replace("\\", "/"),
        "lifted": lifted,
        "drafted": drafted,
        "skipped": [r["file"] for r in plan["skip"]],
    }
