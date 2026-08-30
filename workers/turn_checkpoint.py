"""对话内 checkpoint · 只退本会话 write_file / edit_file。"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
SNAP_ROOT = ROOT / "data" / "runtime" / "turn_checkpoints"
MAX_BLOB = 2 * 1024 * 1024
MAX_LEDGER = 400
_BLOCK_PREFIX = (".git/", "sessions/", "data/runtime/", "data/provider_configs")
_BLOCK_EXACT = {".env", "soul/identity.json"}


def _norm(path: str) -> str:
    p = (path or "").strip().replace("\\", "/")
    root = str(ROOT).replace("\\", "/").rstrip("/")
    if p.lower().startswith(root.lower() + "/"):
        p = p[len(root) + 1 :]
    return p.lstrip("/")


def _blocked(rel: str) -> bool:
    r = (rel or "").replace("\\", "/").lower()
    if not r or r in _BLOCK_EXACT or r.startswith(".env."):
        return True
    return any(r.startswith(p) for p in _BLOCK_PREFIX)


def _ids(sid: str = "", turn_id: str = "") -> tuple[str, str]:
    if not sid or not turn_id:
        try:
            from agent_tools import current_session_id, current_turn_id
            sid = sid or current_session_id()
            turn_id = turn_id or current_turn_id()
        except Exception:
            pass
    return sid or "", turn_id or ""


def _ledger(sid: str) -> Path:
    return SNAP_ROOT / sid / "ledger.jsonl"


def _read_ledger(sid: str) -> list[dict]:
    p = _ledger(sid)
    if not p.exists():
        return []
    out: list[dict] = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                out.append(rec)
    except OSError:
        return []
    return out


def snapshot_before(path: str, sid: str = "", turn_id: str = "") -> None:
    """写盘前记一份。同一轮同一文件只记第一次。失败静默。"""
    sid, turn_id = _ids(sid, turn_id)
    rel = _norm(path)
    if not sid or not turn_id or _blocked(rel):
        return
    existing = _read_ledger(sid)
    if len(existing) >= MAX_LEDGER:
        return
    for rec in existing:
        if rec.get("turn_id") == turn_id and rec.get("path") == rel:
            return
    abs_p = ROOT / rel
    kind = "create"
    blob = ""
    if abs_p.exists() and abs_p.is_file():
        try:
            if abs_p.stat().st_size > MAX_BLOB:
                return
            raw = abs_p.read_bytes()
        except OSError:
            return
        kind = "edit"
        digest = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:12]
        dest = SNAP_ROOT / sid / turn_id
        dest.mkdir(parents=True, exist_ok=True)
        (dest / digest).write_bytes(raw)
        blob = f"{turn_id}/{digest}"
    SNAP_ROOT.joinpath(sid).mkdir(parents=True, exist_ok=True)
    rec = {"ts": time.time(), "sid": sid, "turn_id": turn_id, "path": rel, "kind": kind, "blob": blob}
    with _ledger(sid).open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def preview(sid: str, keep_turn_id: str) -> dict:
    return _plan(sid, keep_turn_id)


def _plan(sid: str, keep_turn_id: str) -> dict:
    entries = _read_ledger(sid)
    start = next((i for i, e in enumerate(entries) if e.get("turn_id") == keep_turn_id), None)
    files: dict[str, dict] = {}
    if start is not None:
        for e in entries[start:]:
            rel = e.get("path") or ""
            if rel and rel not in files:
                files[rel] = e
    restore, delete, skip = [], [], []
    for rel, e in files.items():
        why = _skip_why(rel, sid)
        if why:
            skip.append({"path": rel, "reason": why})
            continue
        item = {"path": rel, "kind": e.get("kind") or "edit"}
        if e.get("kind") == "create":
            delete.append(item)
        else:
            restore.append(item)
    return {
        "ok": True, "sid": sid, "turn_id": keep_turn_id,
        "restore": restore, "delete": delete, "skip": skip,
        "has_snaps": start is not None,
    }


def _skip_why(rel: str, sid: str) -> str:
    if _blocked(rel):
        return "protected"
    try:
        from workers.edit_attribution import lookup
        rec = lookup(rel)
        other = (rec or {}).get("session") or ""
        if other and other != sid:
            return "other-session"
    except Exception:
        pass
    return ""


def _fence(sid: str, on: bool) -> None:
    try:
        from daemon_session import set_restore_fence
        set_restore_fence(sid, on)
    except Exception:
        pass


def run(
    sid: str,
    keep_turn_id: str = "",
    keep_line: Optional[int] = None,
    do_apply: bool = False,
    drop_keep: bool = False,
) -> dict:
    if not sid or (not keep_turn_id and keep_line is None):
        return {"ok": False, "error": "sid 和 turn_id 或 line 必填"}
    if not do_apply:
        return preview(sid, keep_turn_id)
    _fence(sid, True)
    try:
        _abort_sid(sid)
        out = restore(sid, keep_turn_id, keep_line=keep_line, drop_keep=drop_keep)
        try:
            from daemon_api import drop_session_cache
            drop_session_cache(sid)
        except Exception:
            pass
        return out
    finally:
        _fence(sid, False)


def _abort_sid(sid: str) -> None:
    try:
        from daemon_api import find_session_turn, get_turn_cancel
        tid = find_session_turn(sid)
        if not tid:
            return
        ev = get_turn_cancel(tid)
        if ev is not None:
            ev.set()
        for _ in range(25):
            if not find_session_turn(sid):
                return
            time.sleep(0.2)
    except Exception:
        pass


def restore(
    sid: str,
    keep_turn_id: str,
    keep_line: Optional[int] = None,
    drop_keep: bool = False,
) -> dict:
    plan = _plan(sid, keep_turn_id)
    if not plan.get("ok"):
        return plan
    cut = truncate_session(sid, keep_turn_id, keep_line=keep_line, drop_keep=drop_keep)
    if not cut:
        plan["applied"] = False
        plan["truncated"] = False
        plan["error"] = "对话截不断 · 文件没动"
        return plan
    entries = _read_ledger(sid)
    start = next((i for i, e in enumerate(entries) if e.get("turn_id") == keep_turn_id), None)
    first: dict[str, dict] = {}
    if start is not None:
        for e in entries[start:]:
            rel = e.get("path") or ""
            if rel and rel not in first:
                first[rel] = e
    done_r, done_d, failed = [], [], []
    for rel, e in first.items():
        if _skip_why(rel, sid):
            continue
        abs_p = ROOT / rel
        try:
            if e.get("kind") == "create":
                if abs_p.exists() and abs_p.is_file():
                    abs_p.unlink()
                done_d.append(rel)
                continue
            blob = e.get("blob") or ""
            src = SNAP_ROOT / sid / blob if blob else None
            if not src or not src.exists():
                failed.append({"path": rel, "error": "no-blob"})
                continue
            abs_p.parent.mkdir(parents=True, exist_ok=True)
            abs_p.write_bytes(src.read_bytes())
            done_r.append(rel)
        except OSError as exc:
            failed.append({"path": rel, "error": str(exc)})
    plan["applied"] = True
    plan["restored"] = done_r
    plan["deleted"] = done_d
    plan["failed"] = failed
    plan["truncated"] = True
    return plan


def truncate_session(
    sid: str,
    keep_turn_id: str = "",
    keep_line: Optional[int] = None,
    drop_keep: bool = False,
) -> bool:
    """默认收到那句 user（含）。drop_keep=True 时这句也砍。"""
    from daemon_session import session_path
    path = session_path(sid)
    if not path.exists():
        return False
    keep: list[str] = []
    found = False
    try:
        raw = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(raw):
            if not line.strip():
                if keep_line is not None and i == keep_line:
                    found = True
                    break
                continue
            keep.append(line)
            if keep_turn_id:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                meta = rec.get("meta") or {}
                if rec.get("role") == "user" and meta.get("turn_id") == keep_turn_id:
                    found = True
                    if drop_keep:
                        keep.pop()
                    break
            elif keep_line is not None and i == keep_line:
                found = True
                if drop_keep:
                    keep.pop()
                break
    except OSError:
        return False
    if not found and keep_turn_id and keep_line is not None:
        return truncate_session(sid, "", keep_line, drop_keep)
    if not found:
        return False
    tmp = path.with_suffix(".jsonl.restore-tmp")
    tmp.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
    os.replace(tmp, path)
    return True
