"""市集仓 Gitee 薄封装。令牌复用打分那条，不打印。"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from workers.market_rate import _gitee_repo, _gitee_token

UA = {"User-Agent": "Daemonkey-market/1"}
_STATUS = {"at": 0.0, "data": None}


def token() -> str:
    return _gitee_token()


def origin():
    loc = _gitee_repo()
    if not loc:
        return None
    return {"owner": loc[0], "repo": loc[1], "ref": loc[2], "index": loc[3]}


def _req(method: str, path: str, tok: str, fields: dict | None = None, query: dict | None = None):
    q = dict(query or {})
    if method == "GET":
        q["access_token"] = tok
    url = "https://gitee.com/api/v5" + path
    if q:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(q)
    data = None
    headers = dict(UA)
    headers["Authorization"] = "token " + tok
    if fields is not None:
        body = dict(fields)
        body["access_token"] = tok
        data = urllib.parse.urlencode(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:240]
        raise RuntimeError(f"Gitee {e.code} {path}: {detail}") from e
    return json.loads(raw.decode("utf-8")) if raw else {}


def whoami(tok: str) -> dict:
    return _req("GET", "/user", tok)


def repo_perm(tok: str, owner: str, repo: str) -> dict:
    data = _req("GET", f"/repos/{owner}/{repo}", tok)
    return data.get("permission") or {}


def status() -> dict:
    now = time.time()
    if _STATUS["data"] and now - _STATUS["at"] < 45:
        return dict(_STATUS["data"])
    loc = origin()
    tok = token()
    out = {
        "can_submit": bool(tok and loc),
        "is_owner": False,
        "login": "",
        "catalog_host": f"{loc['owner']}/{loc['repo']}" if loc else "",
    }
    if tok and loc:
        try:
            me = whoami(tok)
            out["login"] = str(me.get("login") or "")
            perm = repo_perm(tok, loc["owner"], loc["repo"])
            out["is_owner"] = bool(perm.get("push") or perm.get("admin"))
        except Exception:
            out["can_submit"] = False
    _STATUS.update(at=now, data=out)
    return dict(out)


def get_file(tok: str, owner: str, repo: str, path: str, ref: str) -> dict:
    data = _req("GET", f"/repos/{owner}/{repo}/contents/{path}", tok, query={"ref": ref})
    if not isinstance(data, dict):
        raise RuntimeError("不是文件：" + path)
    return data


def put_file(tok: str, owner: str, repo: str, path: str, content: bytes, message: str, branch: str, sha: str = ""):
    fields = {
        "content": base64.b64encode(content).decode("ascii"),
        "message": message,
        "branch": branch,
    }
    if sha:
        fields["sha"] = sha
        return _req("PUT", f"/repos/{owner}/{repo}/contents/{path}", tok, fields)
    return _req("POST", f"/repos/{owner}/{repo}/contents/{path}", tok, fields)


def create_branch(tok: str, owner: str, repo: str, name: str, refs: str):
    return _req("POST", f"/repos/{owner}/{repo}/branches", tok, {"refs": refs, "branch_name": name})


def ensure_fork(tok: str, owner: str, repo: str, login: str) -> tuple[str, str]:
    if login == owner:
        return owner, repo
    try:
        data = _req("POST", f"/repos/{owner}/{repo}/forks", tok)
    except RuntimeError as e:
        if "403" not in str(e) and "400" not in str(e):
            raise
        data = {}
    ns = data.get("namespace") if isinstance(data, dict) else {}
    owner_obj = data.get("owner") if isinstance(data, dict) else {}
    dest_owner = ""
    if isinstance(ns, dict):
        dest_owner = str(ns.get("path") or "")
    if not dest_owner and isinstance(owner_obj, dict):
        dest_owner = str(owner_obj.get("login") or "")
    dest_owner = dest_owner or login
    dest_repo = str((data.get("path") or data.get("name") or repo) if isinstance(data, dict) else repo)
    for _ in range(8):
        try:
            _req("GET", f"/repos/{dest_owner}/{dest_repo}", tok)
            return dest_owner, dest_repo
        except RuntimeError:
            time.sleep(1.2)
    return dest_owner, dest_repo


def create_pr(tok: str, owner: str, repo: str, title: str, head: str, base: str, body: str) -> dict:
    return _req("POST", f"/repos/{owner}/{repo}/pulls", tok, {
        "title": title, "head": head, "base": base, "body": body,
    })


def list_prs(tok: str, owner: str, repo: str, state: str = "open") -> list:
    data = _req("GET", f"/repos/{owner}/{repo}/pulls", tok, query={"state": state, "per_page": 50})
    return data if isinstance(data, list) else []


def pr_files(tok: str, owner: str, repo: str, number: int) -> list:
    data = _req("GET", f"/repos/{owner}/{repo}/pulls/{int(number)}/files", tok)
    return data if isinstance(data, list) else []


def merge_pr(tok: str, owner: str, repo: str, number: int) -> dict:
    return _req("PUT", f"/repos/{owner}/{repo}/pulls/{int(number)}/merge", tok, {
        "merge_method": "merge",
    })


def close_pr(tok: str, owner: str, repo: str, number: int) -> dict:
    return _req("PATCH", f"/repos/{owner}/{repo}/pulls/{int(number)}", tok, {"state": "closed"})


def comment_pr(tok: str, owner: str, repo: str, number: int, body: str) -> dict:
    return _req("POST", f"/repos/{owner}/{repo}/issues/{int(number)}/comments", tok, {"body": body})


def file_bytes(meta: dict) -> bytes:
    if meta.get("encoding") == "base64" and meta.get("content"):
        return base64.b64decode(meta["content"])
    raise RuntimeError("读不到文件内容")
