"""货架打分：装过才能评。先记本机，能写回市集仓才进公共分。"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from workers.market_index import MARKET, _GITEE_RAW, catalog_by_id, config, installed_ids
from workers.safe_write import atomic_write_json

_FILE = "ratings.json"


def local_scores() -> dict:
    raw = {}
    p = MARKET / _FILE
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
    items = raw.get("items") if isinstance(raw, dict) else {}
    out = {}
    for k, v in (items or {}).items():
        if isinstance(v, dict) and v.get("score") is not None:
            out[str(k)] = int(v["score"])
    return out


def _store() -> dict:
    p = MARKET / _FILE
    if not p.exists():
        return {"items": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("items", {})
    return data


def apply_vote(item: dict, voter_id: str, score: int) -> dict:
    """按投票人去重。同一台再评是改分，不加人。"""
    score = int(score)
    raters = dict(item.get("raters") or {})
    raters[str(voter_id)] = score
    vals = [int(v) for v in raters.values()]
    item = dict(item)
    item["raters"] = raters
    item["votes"] = len(vals)
    item["score"] = round(sum(vals) / len(vals), 2) if vals else 0
    return item


def _voter_id(data: dict) -> str:
    vid = str(data.get("voter_id") or "").strip()
    if not vid:
        vid = uuid.uuid4().hex
        data["voter_id"] = vid
    return vid


def _gitee_token() -> str:
    for k in ("GITEE_TOKEN", "DAEMONKEY_GITEE_TOKEN"):
        v = (os.environ.get(k) or "").strip()
        if v:
            return v
    env = Path(__file__).resolve().parents[1] / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("GITEE_TOKEN=") or line.startswith("DAEMONKEY_GITEE_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    p = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=gitee.com\n\n",
        text=True,
        capture_output=True,
    )
    for line in p.stdout.splitlines():
        if line.startswith("password="):
            return line[9:]
    return ""


def _gitee_repo():
    m = _GITEE_RAW.match(config().get("catalog_url") or "")
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3), m.group(4)


def _publish(item_id: str, voter_id: str, score: int) -> dict:
    loc = _gitee_repo()
    if not loc:
        return {"ok": False, "error": "没配市集仓地址"}
    token = _gitee_token()
    if not token:
        return {"ok": False, "error": "这台电脑写不了市集仓"}
    owner, repo, ref, path = loc
    api = f"https://gitee.com/api/v5/repos/{owner}/{repo}/contents/{path}?ref={urllib.parse.quote(ref, safe='')}"
    headers = {"User-Agent": "Daemonkey-market/1", "Authorization": "token " + token}
    req = urllib.request.Request(api, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        meta = json.loads(resp.read().decode("utf-8"))
    raw = base64.b64decode(meta.get("content") or "").decode("utf-8")
    cat = json.loads(raw)
    items = list(cat.get("items") or [])
    found = None
    for i, it in enumerate(items):
        if str(it.get("id") or "") == item_id:
            items[i] = apply_vote(it, voter_id, score)
            found = items[i]
            break
    if not found:
        return {"ok": False, "error": "货架上没有这一行"}
    cat["items"] = items
    cat["updated_at"] = time.strftime("%Y-%m-%d")
    body = urllib.parse.urlencode({
        "access_token": token,
        "content": base64.b64encode(
            (json.dumps(cat, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        ).decode("ascii"),
        "sha": meta.get("sha") or "",
        "message": f"rate {item_id}",
        "branch": ref,
    }).encode("utf-8")
    put = urllib.request.Request(
        f"https://gitee.com/api/v5/repos/{owner}/{repo}/contents/{path}",
        data=body,
        method="PUT",
        headers=headers,
    )
    with urllib.request.urlopen(put, timeout=20) as resp:
        resp.read()
    return {"ok": True, "score": found.get("score"), "votes": found.get("votes")}


def rate(item_id: str, score: int, publish: bool = True) -> dict:
    item_id = str(item_id or "").strip()
    try:
        score = int(score)
    except (TypeError, ValueError):
        return {"ok": False, "error": "分必须是 1 到 5"}
    if score < 1 or score > 5:
        return {"ok": False, "error": "分必须是 1 到 5"}
    if item_id not in catalog_by_id():
        return {"ok": False, "error": "货架上没有这一行，没法打分"}
    if item_id not in installed_ids():
        return {"ok": False, "error": "装过才能打分。没用过的分不算。"}
    data = _store()
    rec = dict((data.get("items") or {}).get(item_id) or {})
    rec["score"] = score
    rec["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    voter = _voter_id(data)
    pub = {"ok": False}
    if publish:
        try:
            pub = _publish(item_id, voter, score)
        except Exception:
            pub = {"ok": False, "error": "写回货架失败"}
        if pub.get("ok"):
            rec["published"] = score
    data.setdefault("items", {})[item_id] = rec
    MARKET.mkdir(parents=True, exist_ok=True)
    atomic_write_json(MARKET / _FILE, data)
    if pub.get("ok"):
        msg = f"记下 {score} 分，货架现在 {pub.get('score')} 分 · {pub.get('votes')} 人"
    else:
        why = pub.get("error") or "货架还没写上"
        msg = f"记下 {score} 分（这台电脑）。{why}。别人暂时还看不到你的分。"
    return {"ok": True, "output": msg, "local": score, "published": bool(pub.get("ok"))}
