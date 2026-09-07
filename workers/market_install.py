"""从货架下载 .dkpkg 并按 kind 落位。"""
from __future__ import annotations

import base64
import ipaddress
import json
import socket
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

from workers.market_index import MARKET, _GITEE_RAW, catalog_by_id, mark_installed

ROOT = Path(__file__).resolve().parents[1]
_MAX = 20 * 1024 * 1024
_HOSTS = (
    "gitee.com",
    "github.com",
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
    "raw.giteeusercontent.com",
    "giteeusercontent.com",
)


def _host_ok(host: str) -> bool:
    host = (host or "").lower().rstrip(".")
    return (
        host in _HOSTS
        or host.endswith(".gitee.com")
        or host.endswith(".github.com")
        or host.endswith(".giteeusercontent.com")
    )


def _url_ok(url: str) -> bool:
    u = urlparse(url)
    host = u.hostname or ""
    return u.scheme == "https" and _host_ok(host) and not _blocked_host(host)


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Gitee raw 会 302 到 raw.giteeusercontent.com；只跟白名单 https。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _url_ok(newurl):
            raise ValueError("不允许跳转到非市集地址")
        return urllib.request.HTTPRedirectHandler.redirect_request(
            self, req, fp, code, msg, headers, newurl
        )


def cache_name(url: str) -> str:
    last = unquote(url.rstrip("/").split("/")[-1] or "pkg.dkpkg")
    name = Path(last).name
    if not name or name in (".", ".."):
        name = "pkg.dkpkg"
    name = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in name)
    if not name.lower().endswith(".dkpkg"):
        name = (Path(name).stem or "pkg") + ".dkpkg"
    return name[:80] or "pkg.dkpkg"


def _blocked_host(host: str) -> bool:
    host = (host or "").strip().lower().rstrip(".")
    if not host or host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        for info in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return True
    except Exception:
        return True
    return False


def _gitee_blob(url: str) -> bytes:
    """公开仓 contents API，避开 raw CDN 还没刷到新袋子。"""
    m = _GITEE_RAW.match(url)
    if not m:
        raise ValueError("不是 Gitee raw 地址")
    api = (
        f"https://gitee.com/api/v5/repos/{m.group(1)}/{m.group(2)}/contents/{m.group(4)}"
        f"?ref={urllib.parse.quote(m.group(3), safe='')}"
    )
    req = urllib.request.Request(api, headers={"User-Agent": "Daemonkey-market/1"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        meta = json.loads(resp.read().decode("utf-8"))
    if not (isinstance(meta, dict) and meta.get("encoding") == "base64" and meta.get("content")):
        raise ValueError("市集仓读不到这个袋子")
    data = base64.b64decode(meta["content"])
    if len(data) > _MAX:
        raise ValueError("包太大（超过 20MB）")
    return data


def _download(url: str) -> Path:
    if not _url_ok(url):
        raise ValueError("只从市集仓 https 地址拉袋子")
    cache = (MARKET / "cache").resolve()
    cache.mkdir(parents=True, exist_ok=True)
    dest = (cache / cache_name(url)).resolve()
    dest.relative_to(cache)
    data = None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Daemonkey-market/1"})
        opener = urllib.request.build_opener(_SafeRedirect)
        with opener.open(req, timeout=20) as resp:
            data = resp.read(_MAX + 1)
        if len(data) > _MAX:
            raise ValueError("包太大（超过 20MB）")
        if not data and _GITEE_RAW.match(url):
            raise ValueError("CDN 还没刷到袋子")
    except Exception:
        if not _GITEE_RAW.match(url):
            raise
        data = _gitee_blob(url)
    dest.write_bytes(data)
    return dest


def _resolve_file(item: dict) -> Path:
    raw = str(item.get("file") or "").strip()
    if not raw:
        raise ValueError("清单没写下载地址")
    if raw.startswith("https://"):
        return _download(raw)
    if raw.startswith("http://"):
        raise ValueError("只从 https 拉袋子")
    p = Path(raw)
    if not p.is_absolute():
        p = ROOT / raw
    p = p.resolve()
    try:
        p.relative_to(ROOT)
    except ValueError:
        raise ValueError("本机路径必须在工程内")
    if not p.exists():
        raise ValueError(f"文件不存在: {raw}")
    return p


def install(item_id: str, overwrite: bool = False) -> dict:
    item = catalog_by_id().get(item_id)
    if not item:
        return {"ok": False, "output": "", "error": f"货架上没有 `{item_id}`"}
    kind = str(item.get("kind") or "")
    if kind == "playbook":
        return {"ok": False, "output": "", "error": "操作手册上架安装下一刀再接（先用导入操作手册）"}
    try:
        path = _resolve_file(item)
    except Exception as e:
        return {"ok": False, "output": "", "error": str(e)}
    if kind == "mod":
        from workers.mod_pack_io import import_zip
        ok, msg = import_zip(path, overwrite=overwrite)
        if ok:
            mark_installed(item_id, str(item.get("version") or ""), path.stat().st_mtime)
        return {"ok": ok, "output": msg if ok else "", "error": "" if ok else msg}
    from agent_tools.dkpkg import _import
    result = _import({"path": str(path), "overwrite": overwrite})
    if result.ok:
        mark_installed(item_id, str(item.get("version") or ""), path.stat().st_mtime)
    return {"ok": result.ok, "output": result.output, "error": result.error}
