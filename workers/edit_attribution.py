"""
workers/edit_attribution.py
===========================
编辑归属登记表 —— 多实例并行安全 (wish-e19edb92 · 2026-07-29)

为什么造它:
  2026-07-29 凌晨三实例虚惊事故: 实例②改完代码没 commit 裸奔工作区 ·
  实例① request_restart 的 checkpoint (git add -A) 把这些改动卷进自己的 commit ·
  实例②回来看到工作区干净以为改动被删 · 排查 20 分钟 · BRO 恐慌
  "多实例合并互相覆盖" (其实 git 什么都没丢 · 丢的是【信息可见性】)。

  根因: checkpoint 不知道"哪个文件是哪个会话改的" · 只能一刀切 add -A。
  本模块把"谁最后碰过这个文件"记成一张【落盘】的表 · checkpoint 据此做精准 add:
    - 本会话改的文件            → 收 (正常)
    - 别的活跃会话 (<24h) 改的  → 留在工作区不动 · 通知对方"你的改动还在"
    - 老会话 (>24h) 改的        → 全收兜底 · commit message 标 [卷入] · 通知对方"已被收录"
    - 归属不明的                → 全收兜底 · 标 [卷入·归属不明]
  核心不变量: 【宁可全收 · 绝不丢改动】。精准只是让"别人的活改动"别被误卷。

为什么落盘而不是内存:
  checkpoint 最常发生在 request_restart 前 —— 重启后内存登记表全没了 ·
  恰恰那一刻最需要知道归属。 所以写 data/runtime/edit_attribution.json。

覆盖范围 (诚实声明):
  只记【工具层写盘】—— write_file / edit_file 成功后由 _edit_lock.note_write 同步记。
  shell_exec 命令改的 / Cursor 等外部编辑器改的 → 表里没记录 = 归属不明 =
  checkpoint 全收兜底。 不丢 · 只是没法精准。 这是刻意的安全侧设计。

设计原则 (照 _edit_lock 的克制):
  - 表有上限 (2000 条 · FIFO 淘汰最老) · 不会无限胀
  - 文件坏了 / 读不动 → 当空表 (= 全部归属不明 = 全收) · 永远 fail 到安全侧
  - 纯 stdlib · 不引第三方
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data" / "runtime" / "edit_attribution.json"

MAX_ENTRIES = 2000
# 别的会话的改动 · 距今小于这个秒数 = "活跃会话" → checkpoint 跳过 (留在工作区);
# 超过 = 那个会话大概率早收尾了 → 全收兜底 + 标 [卷入]。
FOREIGN_ACTIVE_SEC = 24 * 3600

_LOCK = threading.Lock()


def _norm(path: str) -> str:
    """统一 key 形态: 相对工程根 + 正斜杠。 绝对路径/相对路径进来都能对上 git porcelain。"""
    p = (path or "").strip().replace("\\", "/")
    if not p:
        return p
    root = str(ROOT).replace("\\", "/").rstrip("/")
    if p.lower().startswith(root.lower() + "/"):
        p = p[len(root) + 1:]
    return p.lstrip("/")


def _load() -> dict:
    """读表 · 坏了/没有都当空表 (安全侧)。"""
    try:
        if STORE.exists():
            data = json.loads(STORE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save(table: dict) -> None:
    """写表 · 先写 tmp 再替换 (防写一半断电留坏文件) · 失败静默 (下次再记)。"""
    try:
        STORE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STORE.with_suffix(".tmp")
        tmp.write_text(json.dumps(table, ensure_ascii=False, indent=0), encoding="utf-8")
        tmp.replace(STORE)
    except Exception:
        pass


def note_edit(path: str, session: str, tool: str = "edit") -> None:
    """工具层写盘成功后调 · 登记"这个文件最后是谁碰的"。 绝不抛异常。"""
    key = _norm(path)
    if not key or not session:
        return
    try:
        with _LOCK:
            table = _load()
            table[key] = {"session": session, "ts": time.time(), "tool": tool}
            # FIFO: 超上限按 ts 淘汰最老 (保最近的归属 · 老记录价值低)
            if len(table) > MAX_ENTRIES:
                by_ts = sorted(table.items(), key=lambda kv: kv[1].get("ts", 0))
                for k, _ in by_ts[: len(table) - MAX_ENTRIES]:
                    table.pop(k, None)
            _save(table)
    except Exception:
        pass


def lookup(path: str) -> Optional[dict]:
    """查单个文件的归属 · 没记录返 None。"""
    key = _norm(path)
    if not key:
        return None
    with _LOCK:
        rec = _load().get(key)
    return dict(rec) if isinstance(rec, dict) else None


def classify(paths: list[str], owner: str) -> dict:
    """把一组 git 改动文件按归属分类 (checkpoint 精准 add 的核心判定)。

    Args:
        paths: git porcelain 解析出的相对路径清单
        owner: 发起 checkpoint 的会话 id (本会话)

    Returns:
        {
          "own":     [path...]   # 本会话最后碰的 → 收
          "foreign": [path...]   # 别的活跃会话 (<24h) 碰的 → 跳过·留工作区
          "stale":   [path...]   # 别的老会话 (>24h) 碰的 → 收 + 标 [卷入]
          "unknown": [path...]   # 表里没记录 (外部/shell/Cursor) → 收 + 标 [卷入·归属不明]
          "meta":    {path: {"session","ts","tool","age_sec"}}  # 全量元信息 (文案/通知用)
        }
    """
    out: dict = {"own": [], "foreign": [], "stale": [], "unknown": [], "meta": {}}
    now = time.time()
    with _LOCK:
        table = _load()
    for raw in paths:
        key = _norm(raw)
        if not key:
            continue
        rec = table.get(key)
        if not isinstance(rec, dict):
            out["unknown"].append(key)
            continue
        sess = str(rec.get("session", ""))
        ts = float(rec.get("ts", 0) or 0)
        age = max(0.0, now - ts)
        out["meta"][key] = {
            "session": sess,
            "ts": ts,
            "tool": rec.get("tool", "?"),
            "age_sec": age,
        }
        if sess == owner:
            out["own"].append(key)
        elif age < FOREIGN_ACTIVE_SEC:
            out["foreign"].append(key)
        else:
            out["stale"].append(key)
    return out


def short_sid(session: str) -> str:
    """会话 id 显示用短形态 (尾部随机段最可认)。"""
    s = (session or "").strip()
    return s[-6:] if len(s) > 6 else (s or "?")


def fmt_age(seconds: float) -> str:
    """年龄显示: '47 分钟前' / '3 小时前' / '2 天前'。"""
    s = int(max(0, seconds))
    if s < 60:
        return f"{s} 秒前"
    if s < 3600:
        return f"{s // 60} 分钟前"
    if s < 86400:
        return f"{s // 3600} 小时前"
    return f"{s // 86400} 天前"
