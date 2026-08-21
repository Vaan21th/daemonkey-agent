"""
workers/kernel_takeover.py
==========================
用户接管的内核文件清单 · 0.9.6

为什么存在:
  Daemonkey 是"用户和他的 Daemonkey 一起装修的工作室"。 有些内核文件用户会改到面目全非
  (最典型是前端)·这时官方升级带来的价值远小于"改动被覆盖"的代价。
  接管清单就是用户的一句声明:【这个文件归我管 · 官方升级别碰它】。

与 user_overrides 备份的分工 (两层不是重复 · 是被动/主动之别):
  备份 = 已经被覆盖了 · 事后把用户版合并回来   (亡羊补牢)
  接管 = 压根不让它被覆盖                      (一次声明 · 长期有效)

清单落在 data/runtime/ (never_sync) → 升级本身永远不会覆盖这份声明·
所以"我宣布过的接管"不会在下次升级后神秘失效。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAKEOVER_PATH = ROOT / "data" / "runtime" / "kernel_takeover.json"

# 这几个文件不允许接管:它们【就是升级机制本身】。 冻住它们 = 以后所有内核修复
# (包括升级机制自己的 bug 修复、安全修复) 永久进不来 · 而用户不会意识到自己关掉了什么。
# 其余白名单文件全部可接管 —— 这份清单必须保持极小·它是"承重墙里的承重墙"。
PROTECTED = frozenset({
    "core_manifest.json",
    "workers/core_update.py",
    "workers/kernel_takeover.py",
    "agent_tools/update_core.py",
})


def _norm(p: str) -> str:
    p = str(p or "").strip().replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def _read_raw() -> dict:
    try:
        raw = json.loads(TAKEOVER_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {"files": raw}
    except Exception:
        return {}


def load() -> list[str]:
    """用户接管的文件清单 (posix 相对路径) · 读不到/格式坏返空。

    读取时就把 PROTECTED 滤掉 —— 用户手工往 JSON 里塞也不生效。
    任何异常都返空:宁可照常升级·也不要因为这份配置坏了就静默停止升级。
    """
    files = _read_raw().get("files")
    if not isinstance(files, list):
        return []
    out: list[str] = []
    for f in files:
        p = _norm(f)
        if p and p not in PROTECTED and p not in out:
            out.append(p)
    return out


def _kernel_files() -> list[str]:
    """当前白名单 · 延迟 import(core_update 顶层会反向 import 本模块 · 避免循环)。"""
    try:
        from workers.core_update import kernel_files
        return kernel_files()
    except Exception:
        return []


def _write(files: list[str], notes: dict) -> None:
    TAKEOVER_PATH.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "files": files,
        "notes": {k: v for k, v in notes.items() if k in files},
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    TAKEOVER_PATH.write_text(
        json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")


def add(paths: list[str], note: str = "") -> dict:
    """把文件加进接管清单 · 返 {added, already, rejected, not_kernel, files}。

    not_kernel = 不在当前白名单里的:接管它没坏处但也没用(官方本来就不碰)·
    仍然收下 —— 白名单以后可能扩到它·用户提前声明是合理的。
    """
    cur = load()
    notes = _read_raw().get("notes")
    notes = dict(notes) if isinstance(notes, dict) else {}
    kernel = _kernel_files()
    res: dict = {"added": [], "already": [], "rejected": [], "not_kernel": []}
    for raw in paths or []:
        p = _norm(raw)
        if not p:
            continue
        if p in PROTECTED:
            res["rejected"].append({
                "file": p,
                "reason": "升级机制自身 · 接管它会让以后所有内核修复(含安全修复)都进不来",
            })
            continue
        if p in cur:
            res["already"].append(p)
            if note:
                notes[p] = note
            continue
        if kernel and p not in kernel:
            res["not_kernel"].append(p)
        cur.append(p)
        if note:
            notes[p] = note
        res["added"].append(p)
    _write(cur, notes)
    res["files"] = cur
    return res


def remove(paths: list[str]) -> dict:
    """从接管清单移除(交还给官方管) · 返 {removed, missing, files}。"""
    cur = load()
    notes = _read_raw().get("notes")
    notes = dict(notes) if isinstance(notes, dict) else {}
    res: dict = {"removed": [], "missing": []}
    for raw in paths or []:
        p = _norm(raw)
        if not p:
            continue
        if p in cur:
            cur.remove(p)
            notes.pop(p, None)
            res["removed"].append(p)
        else:
            res["missing"].append(p)
    _write(cur, notes)
    res["files"] = cur
    return res


def status() -> dict:
    """给报告 / WebUI / 工具用的快照。"""
    files = load()
    notes = _read_raw().get("notes")
    kernel = _kernel_files()
    return {
        "count": len(files),
        "files": files,
        "notes": notes if isinstance(notes, dict) else {},
        "stale": [f for f in files if kernel and f not in kernel],
        "path": str(TAKEOVER_PATH),
    }
