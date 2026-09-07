"""市集包静态闸。你审的是结论，不是每个袋子打开看。

红灯：明显危险，不许上架 / 待审里直接关。
黄灯：第一次上架或带网络手，才需要人看一眼。
绿灯：结构干净，可以一批合。
装本身不执行代码；空 tools = 工坊里拿到全部手，所以空名单算红灯。
"""
from __future__ import annotations

import io
import ipaddress
import json
import re
import zipfile
from pathlib import Path
from urllib.parse import urlparse

DANGER_TOOLS = frozenset({
    "shell_exec", "python_exec", "write_file", "edit_file",
    "request_restart", "update_core", "import_dkpkg", "install_market",
    "empty_trash", "delete_app_to_trash",
})
NET_TOOLS = frozenset({
    "web_search", "feishu_send", "wechat_send", "manage_client",
})
SKIN_BAD = {
    ".js", ".html", ".htm", ".py", ".ps1", ".exe", ".bat",
    ".cmd", ".vbs", ".msi", ".dll", ".sh",
}
_URL = re.compile(r"https?://[^\s\"']+", re.I)
_MAX = 20 * 1024 * 1024


def _read_zip(src) -> zipfile.ZipFile:
    if isinstance(src, (bytes, bytearray)):
        return zipfile.ZipFile(io.BytesIO(src))
    p = Path(src)
    return zipfile.ZipFile(p)


def _private_host(host: str) -> bool:
    host = (host or "").strip().lower().rstrip(".")
    if not host or host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    except ValueError:
        return False


def _scan_urls(blob: str, red: list, yellow: list) -> None:
    for raw in _URL.findall(blob or ""):
        u = urlparse(raw)
        if u.scheme == "http":
            red.append(f"明文 http：{raw[:80]}")
        if _private_host(u.hostname or ""):
            red.append(f"打到本机/内网：{raw[:80]}")


def _review_app(body: dict, red: list, yellow: list) -> None:
    tools = body.get("tools")
    if not isinstance(tools, list) or not tools:
        red.append("应用没写工具名单（空名单=全部工具，含 shell）")
        return
    names = [str(t).strip() for t in tools if str(t).strip()]
    bad = [n for n in names if n in DANGER_TOOLS]
    if bad:
        red.append("含危险工具：" + "、".join(bad))
    net = [n for n in names if n in NET_TOOLS]
    if net:
        yellow.append("带网络/发信手：" + "、".join(net))
    if (body.get("exec_kind") or "").strip().lower() == "scripted":
        _scan_urls(json.dumps(body.get("exec_template") or {}, ensure_ascii=False), red, yellow)


def _review_flow(body: dict, red: list, yellow: list) -> None:
    steps = body.get("steps") or []
    if not steps and not body.get("litegraph_json"):
        red.append("流程是空的")
    if isinstance(steps, list) and len(steps) > 8:
        yellow.append(f"流程 {len(steps)} 步，偏长")
    _scan_urls(json.dumps(body, ensure_ascii=False), red, yellow)


def _review_skin(z: zipfile.ZipFile, red: list, yellow: list) -> None:
    for name in z.namelist():
        lower = name.lower()
        ext = Path(lower).suffix
        if ext in SKIN_BAD:
            red.append(f"皮肤里有不该出现的文件：{name}")
        if ext == ".svg":
            yellow.append(f"皮肤含 SVG（可能夹脚本）：{name}")


def _review_mod(z, red: list, yellow: list, meta: dict) -> None:
    from workers.mod_pack_io import safe_members
    try:
        names = safe_members(z)
    except ValueError as e:
        red.append(str(e))
        return
    if "mod.json" in z.namelist():
        try:
            body = json.loads(z.read("mod.json").decode("utf-8"))
            mid = str(body.get("id") or "").strip()
            if mid:
                meta["id"] = mid
        except Exception:
            red.append("mod.json 不是 JSON")
    pys = [n for n in names if n.endswith(".py")]
    if pys:
        yellow.append(f"含 {len(pys)} 个 Python 叠层，需确认不改内核白名单")
    if not any(n.startswith(("tools/", "routes/", "ui/")) for n in names):
        yellow.append("没有 tools/routes/ui，空壳")


def review_pkg(src, *, author: str = "", known_authors: list | None = None) -> dict:
    """src: 路径或 bytes。返回 verdict=reject|review|pass。"""
    red: list[str] = []
    yellow: list[str] = []
    meta = {"kind": "", "name": "", "version": "", "id": ""}
    raw = src if isinstance(src, (bytes, bytearray)) else Path(src).read_bytes()
    if len(raw) > _MAX:
        return {"verdict": "reject", "red": ["超过 20MB"], "yellow": [], "meta": meta}
    try:
        z = _read_zip(raw)
    except zipfile.BadZipFile:
        return {"verdict": "reject", "red": ["不是合法 zip"], "yellow": [], "meta": meta}
    dest = Path(".").resolve()
    for member in z.namelist():
        target = (dest / member).resolve()
        try:
            target.relative_to(dest)
        except ValueError:
            red.append(f"路径越界：{member}")
            break
    if "manifest.json" not in z.namelist():
        red.append("缺 manifest.json")
        return {"verdict": "reject", "red": red, "yellow": yellow, "meta": meta}
    try:
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))
    except Exception:
        return {"verdict": "reject", "red": ["manifest 不是 JSON"], "yellow": [], "meta": meta}
    kind = str(manifest.get("kind") or "").lower()
    name = str(manifest.get("name") or "").strip()
    meta.update(kind=kind, name=name, version=str(manifest.get("version") or "1.0.0"), id=name)
    if kind not in ("app", "flow", "skin", "mod") or not name:
        red.append(f"manifest 非法 kind={kind} name={name}")
    if kind == "mod":
        _review_mod(z, red, yellow, meta)
    elif kind == "skin":
        _review_skin(z, red, yellow)
    elif kind in ("app", "flow"):
        src_name = "app.json" if kind == "app" else "flow.json"
        if src_name not in z.namelist():
            red.append(f"缺 {src_name}")
        else:
            try:
                body = json.loads(z.read(src_name).decode("utf-8"))
            except Exception:
                red.append(f"{src_name} 不是 JSON")
                body = {}
            meta["id"] = str(body.get("id") or name)
            if kind == "app":
                _review_app(body, red, yellow)
            else:
                _review_flow(body, red, yellow)
    if not str(manifest.get("description") or "").strip():
        yellow.append("没有一句话介绍")
    login = str(author or "").strip()
    known = {str(a).strip() for a in (known_authors or []) if str(a).strip()}
    if login and known and login not in known:
        yellow.append(f"第一次上架（{login}）")
    if red:
        verdict = "reject"
    elif yellow:
        verdict = "review"
    else:
        verdict = "pass"
    return {"verdict": verdict, "red": red, "yellow": yellow, "meta": meta}


def review_index_patch(old_items: list, new_items: list) -> dict:
    """别人改别人的下载地址 = 红灯。只加自己一行 = 过。"""
    red, yellow = [], []
    old = {str(it.get("id") or ""): it for it in (old_items or []) if it.get("id")}
    new = {str(it.get("id") or ""): it for it in (new_items or []) if it.get("id")}
    added = [i for i in new if i not in old]
    removed = [i for i in old if i not in new]
    if len(added) != 1 or removed:
        red.append("清单必须正好新增 1 行，不能删别人的")
    for iid, it in new.items():
        if iid not in old:
            continue
        if str((it or {}).get("file") or "") != str((old[iid] or {}).get("file") or ""):
            red.append(f"改了已有条目的下载地址：{iid}")
    file_url = str((new.get(added[0]) or {}).get("file") or "") if added else ""
    u = urlparse(file_url)
    if added and (u.scheme != "https" or "packages/" not in (u.path or "") or not u.path.endswith(".dkpkg")):
        red.append("下载地址必须是市集仓 packages/ 下的 https .dkpkg")
    return {"red": red, "yellow": yellow}


def format_report(got: dict) -> str:
    v = got.get("verdict") or "?"
    title = {"reject": "红灯 · 自动挡下", "review": "黄灯 · 要看一眼", "pass": "绿灯 · 可以合"}.get(v, v)
    lines = [title]
    for x in got.get("red") or []:
        lines.append("红：" + x)
    for x in got.get("yellow") or []:
        lines.append("黄：" + x)
    if len(lines) == 1:
        lines.append("静态闸没挑出问题。")
    return "\n".join(lines)
