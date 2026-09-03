"""市集目录 +「可以上架」判定。

货架是独立市集仓的 index.json（第一期可先放本机 data/market/）。
不是 Daemonkey 源码仓。落位不在这里发明，安装仍走 dkpkg。
"""
from __future__ import annotations

import base64
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from workers.safe_write import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
MARKET = ROOT / "data" / "market"
KINDS = ("skin", "app", "flow", "playbook")
_PLAYBOOK_DAYS = 14


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def config() -> dict:
    MARKET.mkdir(parents=True, exist_ok=True)
    raw = _read_json(MARKET / "config.json", {})
    return {"catalog_url": str(raw.get("catalog_url") or "").strip()}


def _ver_tuple(s) -> tuple:
    nums = [int(x) for x in re.findall(r"\d+", str(s or "0"))]
    return tuple(nums or (0,))


def newer(local, remote) -> bool:
    return _ver_tuple(local) > _ver_tuple(remote)


_GITEE_RAW = re.compile(
    r"https?://gitee\.com/([^/]+)/([^/]+)/raw/([^/]+)/(.+)$"
)


def _http_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Daemonkey-market/1"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _gitee_contents(owner: str, repo: str, ref: str, path: str):
    """Gitee /raw 经常 403，公开仓走 contents API。"""
    api = (
        f"https://gitee.com/api/v5/repos/{owner}/{repo}/contents/{path}"
        f"?ref={urllib.parse.quote(ref, safe='')}"
    )
    data = _http_json(api)
    if isinstance(data, dict) and data.get("encoding") == "base64" and data.get("content"):
        raw = base64.b64decode(data["content"]).decode("utf-8")
        return json.loads(raw)
    return None


def load_catalog() -> dict:
    """远程网址优先，失败或没配则读本机 data/market/index.json。"""
    cfg = config()
    url = cfg.get("catalog_url") or ""
    if url.startswith(("http://", "https://")):
        remote = None
        m = _GITEE_RAW.match(url)
        # Gitee /raw 会 302 到 CDN，清单经常是旧的；公开仓先走 contents API
        if m:
            try:
                remote = _gitee_contents(m.group(1), m.group(2), m.group(3), m.group(4))
            except Exception:
                remote = None
        if remote is None:
            try:
                remote = _http_json(url)
            except Exception:
                remote = None
        if isinstance(remote, dict) and isinstance(remote.get("items"), list):
            remote["source"] = url
            return remote
    local = _read_json(MARKET / "index.json", {"items": []})
    if not isinstance(local, dict):
        local = {"items": []}
    local.setdefault("items", [])
    local["source"] = "local"
    return local


def catalog_by_id() -> dict:
    return {str(it.get("id") or ""): it for it in load_catalog().get("items") or [] if it.get("id")}


def _ledger() -> dict:
    return _read_json(MARKET / "ledger.json", {"items": {}})


def mark_installed(item_id: str, version: str, src_mtime: float = 0) -> None:
    data = _ledger()
    items = data.setdefault("items", {})
    items[item_id] = {
        "version": str(version or ""),
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "src_mtime": float(src_mtime or 0),
    }
    MARKET.mkdir(parents=True, exist_ok=True)
    atomic_write_json(MARKET / "ledger.json", data)


def outgoing() -> list:
    return list(_read_json(MARKET / "outgoing.json", {"items": []}).get("items") or [])


def queue_outgoing(entry: dict) -> None:
    data = _read_json(MARKET / "outgoing.json", {"items": []})
    items = [it for it in (data.get("items") or []) if it.get("id") != entry.get("id")]
    items.append(entry)
    data["items"] = items
    MARKET.mkdir(parents=True, exist_ok=True)
    atomic_write_json(MARKET / "outgoing.json", data)


def _skins() -> list:
    d = ROOT / "static" / "user" / "skins"
    if not d.is_dir():
        return []
    out = []
    for folder in sorted(d.iterdir()):
        if not folder.is_dir():
            continue
        meta = _read_json(folder / "skin.json", {})
        name = str(meta.get("name") or folder.name)
        sj = folder / "skin.json"
        out.append({
            "id": folder.name,
            "kind": "skin",
            "name": name,
            "version": str(meta.get("version") or "1.0.0"),
            "author": str(meta.get("author") or ""),
            "description": str(meta.get("description") or meta.get("desc") or ""),
            "mtime": sj.stat().st_mtime if sj.exists() else folder.stat().st_mtime,
            "preview": str(meta.get("preview") or ""),
            "shipped": False,
        })
    return out


def _workshop(kind: str) -> list:
    if kind == "app":
        from workers.workshop_assets import list_apps
        rows = list_apps(max_items=200)
    else:
        from workers.workshop_assets import list_flows
        rows = list_flows(max_items=200)
    out = []
    folder = ROOT / "data" / "workshop" / (kind + "s")
    for row in rows:
        aid = str(row.get("id") or "")
        if not aid:
            continue
        p = folder / f"{aid}.json"
        out.append({
            "id": aid,
            "kind": kind,
            "name": str(row.get("name") or aid),
            "version": str(row.get("version") or "1"),
            "author": str(row.get("created_by") or ""),
            "description": str(row.get("description") or ""),
            "mtime": p.stat().st_mtime if p.exists() else 0,
            "preview": "",
            "shipped": bool(row.get("shipped")),
        })
    return out


def _playbooks() -> list:
    from workers.playbooks import PLAYBOOK_DIR, list_playbooks
    out = []
    now = time.time()
    for row in list_playbooks():
        slug = str(row.get("slug") or row.get("id") or "")
        if not slug:
            continue
        p = PLAYBOOK_DIR / f"{slug}.md"
        mtime = p.stat().st_mtime if p.exists() else 0
        if mtime and (now - mtime) > _PLAYBOOK_DAYS * 86400:
            continue
        out.append({
            "id": slug,
            "kind": "playbook",
            "name": str(row.get("title") or slug),
            "version": "1.0.0",
            "author": "",
            "description": "",
            "mtime": mtime,
            "preview": "",
            "shipped": False,
        })
    return out


def list_shareable() -> list:
    """本机有、货架没有或更旧/装完后又改过 → 可以上架。出厂 shipped 且没改过的不算。"""
    shelf = catalog_by_id()
    led = (_ledger().get("items") or {})
    found = []
    # 技能文导出/安装还没接上 · 先不进「可以上架」，避免一堆近两周笔记冒充待分享
    for asset in _skins() + _workshop("app") + _workshop("flow"):
        cat = shelf.get(asset["id"])
        rec = led.get(asset["id"]) or {}
        if asset.get("shipped") and not rec:
            continue
        reason = None
        if not cat:
            reason = "unpublished"
        elif newer(asset["version"], cat.get("version")):
            reason = "newer"
        elif rec and asset["mtime"] > float(rec.get("src_mtime") or 0) + 2:
            reason = "edited"
        else:
            continue
        asset["reason"] = reason
        asset["shelf_version"] = (cat or {}).get("version")
        found.append(asset)
    found.sort(key=lambda x: -float(x.get("mtime") or 0))
    return found


def installed_ids() -> set:
    return {str(k) for k in ((_ledger().get("items") or {}).keys())}


def snapshot() -> dict:
    cat = load_catalog()
    from workers.market_rate import local_scores
    try:
        from workers.market_gitee import status
        auth = status()
    except Exception:
        auth = {"can_submit": False, "is_owner": False, "login": ""}
    return {
        "catalog_url": config().get("catalog_url") or "",
        "source": cat.get("source") or "local",
        "items": cat.get("items") or [],
        "shareable": list_shareable(),
        "outgoing": outgoing(),
        "installed": sorted(installed_ids()),
        "ratings": local_scores(),
        "can_submit": bool(auth.get("can_submit")),
        "is_owner": bool(auth.get("is_owner")),
        "login": auth.get("login") or "",
    }
