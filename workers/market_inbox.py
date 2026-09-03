"""仓主待审：拉开放的 PR，复跑静态闸。红灯可一批关，绿灯可一批合。"""
from __future__ import annotations

from workers.market_index import catalog_by_id
from workers.market_review import format_report, review_pkg


def _head_repo(pr: dict) -> tuple[str, str, str]:
    head = pr.get("head") or {}
    repo = head.get("repo") or {}
    full = str(repo.get("full_name") or repo.get("path") or "")
    if "/" in full:
        owner, name = full.split("/", 1)
    else:
        ns = (repo.get("namespace") or {}).get("path") or ""
        owner, name = str(ns), str(repo.get("name") or repo.get("path") or "")
    ref = str(head.get("ref") or "master")
    return owner, name, ref


def _inspect(tok: str, loc: dict, pr: dict) -> dict:
    from workers import market_gitee as gitee
    number = int(pr.get("number") or 0)
    title = str(pr.get("title") or "")
    url = str(pr.get("html_url") or "")
    user = str((pr.get("user") or {}).get("login") or "")
    row = {
        "number": number, "title": title, "url": url, "author": user,
        "verdict": "review", "red": [], "yellow": ["还没读到袋子"], "report": "",
    }
    try:
        files = gitee.pr_files(tok, loc["owner"], loc["repo"], number)
    except RuntimeError as e:
        row["yellow"] = [str(e)]
        row["report"] = format_report(row)
        return row
    pkg = ""
    for f in files:
        name = str(f.get("filename") or f.get("path") or f.get("name") or "")
        if name.endswith(".dkpkg"):
            pkg = name
            break
    if not pkg:
        row["verdict"] = "reject"
        row["red"] = ["这个申请里没有 .dkpkg"]
        row["yellow"] = []
        row["report"] = format_report(row)
        return row
    ho, hr, ref = _head_repo(pr)
    if not ho or not hr:
        row["yellow"] = ["读不到来源仓"]
        row["report"] = format_report(row)
        return row
    try:
        meta = gitee.get_file(tok, ho, hr, pkg, ref)
        raw = gitee.file_bytes(meta)
    except Exception as e:
        row["yellow"] = [f"下载袋子失败：{e}"]
        row["report"] = format_report(row)
        return row
    known = [str(it.get("author") or "") for it in catalog_by_id().values()]
    known.append(loc["owner"])
    got = review_pkg(raw, author=user, known_authors=known)
    row.update(verdict=got["verdict"], red=got["red"], yellow=got["yellow"], meta=got.get("meta") or {})
    row["report"] = format_report(got)
    return row


def list_inbox() -> dict:
    from workers import market_gitee as gitee
    st = gitee.status()
    if not st.get("is_owner"):
        return {"ok": False, "error": "这台电脑写不了货架仓，待审只给仓主看", "items": [], "auth": st}
    loc = gitee.origin()
    tok = gitee.token()
    items = []
    for pr in gitee.list_prs(tok, loc["owner"], loc["repo"], "open"):
        items.append(_inspect(tok, loc, pr))
    counts = {"pass": 0, "review": 0, "reject": 0}
    for it in items:
        counts[it.get("verdict") or "review"] = counts.get(it.get("verdict") or "review", 0) + 1
    return {"ok": True, "items": items, "counts": counts, "auth": st}


def _need_owner():
    from workers import market_gitee as gitee
    st = gitee.status()
    loc = gitee.origin()
    tok = gitee.token()
    if not (st.get("is_owner") and loc and tok):
        return None, None, None, {"ok": False, "error": "这台电脑不是货架仓主"}
    return tok, loc, st, None


def merge_one(number: int) -> dict:
    tok, loc, _st, err = _need_owner()
    if err:
        return err
    from workers import market_gitee as gitee
    try:
        gitee.merge_pr(tok, loc["owner"], loc["repo"], int(number))
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "output": f"已合并 #{number}"}


def close_one(number: int, reason: str = "") -> dict:
    tok, loc, _st, err = _need_owner()
    if err:
        return err
    from workers import market_gitee as gitee
    try:
        if reason:
            try:
                gitee.comment_pr(tok, loc["owner"], loc["repo"], int(number), reason)
            except RuntimeError:
                pass
        gitee.close_pr(tok, loc["owner"], loc["repo"], int(number))
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "output": f"已关掉 #{number}"}


def sweep(action: str) -> dict:
    """sweep_red 关掉红灯；merge_green 合全部绿灯。黄灯不动。"""
    box = list_inbox()
    if not box.get("ok"):
        return box
    done = []
    errors = []
    for it in box.get("items") or []:
        num = it.get("number")
        v = it.get("verdict")
        if action == "sweep_red" and v == "reject":
            got = close_one(num, it.get("report") or "机器闸红灯，自动关掉")
        elif action == "merge_green" and v == "pass":
            got = merge_one(num)
        else:
            continue
        if got.get("ok"):
            done.append(num)
        else:
            errors.append(f"#{num} {got.get('error')}")
    if action == "sweep_red":
        msg = f"关掉红灯 {len(done)} 个"
    else:
        msg = f"合并绿灯 {len(done)} 个"
    if errors:
        msg += "。失败：" + "；".join(errors)
    return {"ok": not errors, "output": msg, "done": done, "errors": errors}
