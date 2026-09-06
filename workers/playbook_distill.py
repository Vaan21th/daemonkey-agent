"""同簇蒸馏：先草稿，确认后才入库。叶子手册不删。"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _home() -> Path:
    from workers.playbooks import PLAYBOOK_DIR
    return PLAYBOOK_DIR


def draft_dir() -> Path:
    d = _home() / "_drafts"
    d.mkdir(parents=True, exist_ok=True)
    return d


PROPOSE_MIN = 3


def _index_path() -> Path:
    return draft_dir() / "_index.json"


def _proposal_path() -> Path:
    return draft_dir() / "_proposals.json"


def _load_proposals() -> dict:
    p = _proposal_path()
    if not p.exists():
        return {"proposals": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"proposals": {}}


def _save_proposals(data: dict) -> None:
    _proposal_path().write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def upsert_proposal(leaf_ids: list[str], title: str = "") -> dict:
    """同簇提议。不写 how_now，不能 confirm 入库。"""
    ids = sorted({str(x).strip() for x in (leaf_ids or []) if str(x).strip()})
    if len(ids) < PROPOSE_MIN:
        return {}
    data = _load_proposals()
    key = "|".join(ids)
    for rec in (data.get("proposals") or {}).values():
        if "|".join(sorted(rec.get("leaf_ids") or [])) == key:
            return rec
    pid = f"pp-{uuid.uuid4().hex[:10]}"
    rec = {
        "id": pid,
        "title": (title or "建议蒸馏").strip(),
        "status": "proposed",
        "leaf_ids": ids,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "path": "data/playbooks/_drafts/_proposals.json",
    }
    data.setdefault("proposals", {})[pid] = rec
    _save_proposals(data)
    return rec


def get_proposal(proposal_id: str) -> dict:
    return (_load_proposals().get("proposals") or {}).get((proposal_id or "").strip()) or {}


def _load_drafts() -> dict:
    p = _index_path()
    if not p.exists():
        return {"drafts": {}, "updated_at": None}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"drafts": {}, "updated_at": None}


def _save_drafts(index: dict) -> None:
    index["updated_at"] = datetime.now(timezone.utc).isoformat()
    _index_path().write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def _leaf_paths(playbook_ids: list[str]) -> list[tuple[str, str, str]]:
    from workers.playbooks import load_playbook
    rows = []
    for pid in playbook_ids:
        loaded = load_playbook(playbook_id=pid)
        if loaded.get("error"):
            continue
        meta = loaded.get("meta") or {}
        slug = meta.get("slug") or ""
        rows.append((pid, loaded.get("title") or slug, f"data/playbooks/{slug}.md"))
    return rows


def draft_cluster(playbook_ids: list[str], title: str, how_now: str) -> dict:
    """写 data/playbooks/_drafts/<id>.md · 不入库、不删叶子。"""
    ids = [str(x).strip() for x in (playbook_ids or []) if str(x).strip()]
    title = (title or "").strip()
    how_now = (how_now or "").strip()
    if len(ids) < 2:
        return {"ok": False, "error": "蒸馏至少 2 份同簇手册"}
    if not title:
        return {"ok": False, "error": "title 必填"}
    if len(how_now) < 20:
        return {"ok": False, "error": "how_now 太短 · 写清现在怎么做"}
    leaves = _leaf_paths(ids)
    if len(leaves) < 2:
        return {"ok": False, "error": "能读到的叶子不足 2 份"}
    draft_id = f"pd-{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc).isoformat()
    leaf_lines = "\n".join(f"- `{pid}` · {ttl} · file: {path}" for pid, ttl, path in leaves)
    body = (
        f"---\n"
        f'title: "{title.replace(chr(10), " ")}"\n'
        f"draft_id: {draft_id}\n"
        f"status: draft\n"
        f"created_at: {now}\n"
        f"---\n\n"
        f"# {title}\n\n"
        f"<!-- distill draft · 未入库 -->\n\n"
        f"## 叶子（确认后也不删）\n\n{leaf_lines}\n\n"
        f"## 现在怎么做\n\n{how_now}\n"
    )
    path = draft_dir() / f"{draft_id}.md"
    path.write_text(body, encoding="utf-8")
    index = _load_drafts()
    index.setdefault("drafts", {})[draft_id] = {
        "id": draft_id,
        "title": title,
        "status": "draft",
        "leaf_ids": [x[0] for x in leaves],
        "leaf_paths": [x[2] for x in leaves],
        "path": f"data/playbooks/_drafts/{draft_id}.md",
        "created_at": now,
    }
    _save_drafts(index)
    return {
        "ok": True,
        "draft_id": draft_id,
        "path": str(path),
        "leaf_ids": [x[0] for x in leaves],
        "leaf_paths": [x[2] for x in leaves],
    }


def confirm_draft(draft_id: str) -> dict:
    """确认后另存一页「现在怎么做」。叶子文件必须还在。"""
    from workers.playbook_case import save_case, source_block
    from workers.playbooks import load_playbook

    did = (draft_id or "").strip()
    if did.startswith("pp-"):
        return {"ok": False, "error": "这是蒸馏提议，不是草稿。先 distill 补 how_now。"}
    index = _load_drafts()
    meta = (index.get("drafts") or {}).get(did)
    if not meta:
        return {"ok": False, "error": f"草稿不存在: {did}"}
    if meta.get("status") == "confirmed" and meta.get("playbook_id"):
        return {"ok": False, "error": f"已经入库: {meta.get('playbook_id')}"}
    path = draft_dir() / f"{did}.md"
    if not path.exists():
        return {"ok": False, "error": "草稿文件丢失"}
    raw = path.read_text(encoding="utf-8")
    how = raw.split("## 现在怎么做", 1)[-1].strip() if "## 现在怎么做" in raw else ""
    if len(how) < 20:
        return {"ok": False, "error": "草稿缺少「现在怎么做」"}
    missing = []
    for pid in meta.get("leaf_ids") or []:
        loaded = load_playbook(playbook_id=pid)
        if loaded.get("error"):
            missing.append(pid)
    if missing:
        return {"ok": False, "error": f"叶子丢了，拒绝入库: {', '.join(missing)}"}
    src = source_block(paths=list(meta.get("leaf_paths") or []) + [meta.get("path") or ""])
    pb = save_case(
        title=meta.get("title") or did,
        task_type="distilled",
        steps=how,
        problem=f"同簇蒸馏 · 叶子 {', '.join(meta.get('leaf_ids') or [])}",
        trials="尚无失败路径",
        source=src,
        tags=["distilled"],
    )
    meta["status"] = "confirmed"
    meta["playbook_id"] = pb["id"]
    meta["confirmed_at"] = datetime.now(timezone.utc).isoformat()
    index["drafts"][did] = meta
    _save_drafts(index)
    stamp = path.read_text(encoding="utf-8")
    if "status: draft" in stamp:
        path.write_text(stamp.replace("status: draft", "status: confirmed", 1), encoding="utf-8")
    return {
        "ok": True,
        "draft_id": did,
        "playbook": pb,
        "leaves_kept": meta.get("leaf_ids") or [],
        "leaf_paths": meta.get("leaf_paths") or [],
    }


def list_drafts() -> list[dict]:
    return list((_load_drafts().get("drafts") or {}).values())


def distill_action(args: dict) -> dict:
    ids = args.get("playbook_ids") or []
    if isinstance(ids, str):
        ids = [x.strip() for x in ids.replace(",", " ").split() if x.strip()]
    prop = get_proposal(str(args.get("proposal_id") or "").strip())
    if prop and not ids:
        ids = list(prop.get("leaf_ids") or [])
    title = str(args.get("title") or "").strip() or (prop.get("title") if prop else "")
    res = draft_cluster(
        ids,
        title=title,
        how_now=str(args.get("how_now") or "").strip(),
    )
    if not res.get("ok"):
        return {"ok": False, "output": "", "error": res.get("error") or "distill 失败"}
    return {
        "ok": True,
        "error": "",
        "output": (
            f"蒸馏草稿已落 data/playbooks/_drafts/\n"
            f"  draft_id: {res['draft_id']}\n"
            f"  path: {res['path']}\n"
            f"  叶子未删: {', '.join(res['leaf_ids'])}\n"
            f"  确认入库: extract_playbook action=distill_confirm draft_id={res['draft_id']}\n"
        ),
    }


def confirm_action(args: dict) -> dict:
    res = confirm_draft(str(args.get("draft_id") or "").strip())
    if not res.get("ok"):
        return {"ok": False, "output": "", "error": res.get("error") or "confirm 失败"}
    pb = res["playbook"]
    return {
        "ok": True,
        "error": "",
        "output": (
            f"蒸馏已入库 · 叶子仍在\n"
            f"  id: {pb['id']}\n"
            f"  path: {pb['path']}\n"
            f"  leaves: {', '.join(res['leaves_kept'])}\n"
        ),
    }
