"""把本机 .dkpkg 提成市集仓的 Pull Request。模型点按钮或工具都会走这里。"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from workers.market_index import catalog_by_id, queue_outgoing
from workers.market_review import format_report, review_index_patch, review_pkg

ROOT = Path(__file__).resolve().parents[1]


def _safe(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._\-]+", "_", str(s or "").strip())
    return (s.strip("._") or "pkg")[:60]


def _export_pkg(kind: str, name: str, author: str, version: str, description: str):
    if kind == "mod":
        from workers.mod_pack_io import export_zip
        path, err = export_zip(name, author=author, version=version, description=description)
        if path is None:
            class _R:
                ok = False
                error = err
                output = ""
            return None, _R()
        class _R:
            ok = True
            error = ""
            output = f"`{path.as_posix()}`"
        return path, _R()
    from agent_tools.dkpkg import _export
    ver = version or "1.0.0"
    result = _export({
        "kind": kind, "name": name, "author": author,
        "version": ver, "description": description,
    })
    if not result.ok:
        return None, result
    m = re.search(r"`([^`]+\.dkpkg)`", result.output or "")
    path = (ROOT / m.group(1)).resolve() if m else None
    if not path or not path.exists():
        return None, result
    return path, result


def _known_authors() -> list:
    authors = []
    for it in catalog_by_id().values():
        a = str(it.get("author") or "").strip()
        if a:
            authors.append(a)
    loc = None
    from workers.market_gitee import origin
    loc = origin()
    if loc:
        authors.append(loc["owner"])
    return authors


def _upsert_index(old: dict, item: dict) -> dict:
    items = [it for it in (old.get("items") or []) if str(it.get("id") or "") != item["id"]]
    items.append(item)
    cat = dict(old)
    cat["items"] = items
    cat["updated_at"] = time.strftime("%Y-%m-%d")
    return cat


def submit(kind: str, name: str, author: str = "", version: str = "", description: str = "") -> dict:
    kind = (kind or "").strip().lower()
    name = (name or "").strip()
    if kind not in ("app", "flow", "skin", "mod") or not name:
        return {"ok": False, "error": "kind 必须是 app/flow/skin/mod，且 name 必填"}
    if kind == "mod":
        from workers.overlay_policy import publish_block
        blocked = publish_block()
        if blocked:
            return {"ok": False, "error": blocked}
    path, exported = _export_pkg(kind, name, author, version, description)
    if path is None:
        return {"ok": False, "error": getattr(exported, "error", None) or "导出失败"}
    from workers import market_gitee as gitee
    st = gitee.status()
    login = st.get("login") or author or ""
    report = review_pkg(path, author=login, known_authors=_known_authors())
    item_id = report.get("meta", {}).get("id") or name
    ver = version or report.get("meta", {}).get("version") or "1.0.0"
    queue_outgoing({
        "id": item_id, "kind": kind, "name": name, "author": login or author,
        "version": ver, "description": description,
        "note": "已打成本机 .dkpkg",
        "verdict": report.get("verdict"),
    })
    if report["verdict"] == "reject":
        return {
            "ok": False,
            "exported": True,
            "verdict": "reject",
            "error": "机器闸红灯，没有提交。\n" + format_report(report),
            "output": exported.output,
        }
    if not st.get("can_submit"):
        return {
            "ok": True,
            "exported": True,
            "submitted": False,
            "verdict": report["verdict"],
            "output": (
                exported.output + "\n\n" + format_report(report)
                + "\n要提到官方货架，这台电脑需要 Gitee 私人令牌（仓库+PR），写在 .env 的 GITEE_TOKEN。"
            ),
        }
    loc = gitee.origin()
    tok = gitee.token()
    try:
        dest_owner, dest_repo = gitee.ensure_fork(tok, loc["owner"], loc["repo"], login or loc["owner"])
        branch = f"mkt/{_safe(item_id)}-{_safe(ver)}"[:40]
        try:
            gitee.create_branch(tok, dest_owner, dest_repo, branch, loc["ref"])
        except RuntimeError as e:
            if "已存在" not in str(e) and "already" not in str(e).lower() and "422" not in str(e):
                raise
        pkg_name = f"{_safe(item_id)}-{_safe(ver)}.dkpkg"
        pkg_rel = f"packages/{pkg_name}"
        file_url = f"https://gitee.com/{loc['owner']}/{loc['repo']}/raw/{loc['ref']}/{pkg_rel}"
        try:
            old_pkg = gitee.get_file(tok, dest_owner, dest_repo, pkg_rel, branch)
            pkg_sha = old_pkg.get("sha") or ""
        except Exception:
            pkg_sha = ""
        gitee.put_file(
            tok, dest_owner, dest_repo, pkg_rel, path.read_bytes(),
            f"market: add {pkg_name}", branch, sha=pkg_sha,
        )
        orig_meta = gitee.get_file(tok, loc["owner"], loc["repo"], loc["index"], loc["ref"])
        old_cat = json.loads(gitee.file_bytes(orig_meta).decode("utf-8"))
        item = {
            "id": item_id, "kind": kind,
            "name": report.get("meta", {}).get("name") or name,
            "version": ver, "author": login or author or "佚名",
            "description": description or "", "file": file_url,
        }
        new_cat = _upsert_index(old_cat, item)
        patch = review_index_patch(old_cat.get("items") or [], new_cat.get("items") or [])
        if patch["red"]:
            return {"ok": False, "error": "清单改动不合法：" + "；".join(patch["red"])}
        try:
            br_idx = gitee.get_file(tok, dest_owner, dest_repo, loc["index"], branch)
            idx_sha = br_idx.get("sha") or ""
        except RuntimeError:
            idx_sha = orig_meta.get("sha") or ""
        text = json.dumps(new_cat, ensure_ascii=False, indent=2) + "\n"
        gitee.put_file(
            tok, dest_owner, dest_repo, loc["index"], text.encode("utf-8"),
            f"market: list {item_id}", branch, sha=idx_sha,
        )
        head = branch if dest_owner == loc["owner"] else f"{dest_owner}:{branch}"
        body = format_report(report) + f"\n\nid=`{item_id}` kind={kind} v{ver}\nfile={file_url}\n"
        pr = gitee.create_pr(
            tok, loc["owner"], loc["repo"],
            title=f"market: {kind} {item_id} {ver}",
            head=head, base=loc["ref"], body=body,
        )
        url = pr.get("html_url") or pr.get("url") or ""
        number = pr.get("number")
        if number:
            try:
                gitee.comment_pr(tok, loc["owner"], loc["repo"], int(number), body)
            except RuntimeError:
                pass
    except Exception as e:
        return {
            "ok": False,
            "exported": True,
            "verdict": report["verdict"],
            "error": f"袋子打好了，提到货架失败：{e}",
            "output": exported.output,
        }
    return {
        "ok": True,
        "exported": True,
        "submitted": True,
        "verdict": report["verdict"],
        "pr": url,
        "number": number,
        "output": exported.output + "\n\n" + format_report(report) + (f"\n已开合并申请：{url}" if url else ""),
    }
