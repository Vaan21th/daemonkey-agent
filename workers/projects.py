"""
workers/projects.py
===================
wish-acc37841 · 外部项目管理（左导航「我的项目」）

为什么需要它：
  BRO 要 OPUS 能独立开发**外面的真工程**（Cursor 那种按目录组织）。
  最小的一层就是这张登记表 —— "哪个目录算一个项目"。
  注意它跟出品工坊的 app 是两码事：app 是内生产物，这里登记的是**外部真目录**。

数据结构 data/projects.json:
  {
    "updated_at": "...",
    "items": {
      "<project_id>": {
        "id":         "manju-app",
        "name":       "manju-app",          # 显示名 · 可改
        "path":       "F:\\\\Desktop\\\\manju-app",       # 真目录（绝对路径）
        "profile":    "标准",               # 该项目默认档位（档位那一环用 · 先存着）
        "handoff":    "",                   # 交接条：上次停在哪 / 下一步（第三刀写）
        "created_at": "...",
        "last_used_at": "...",
        "archived_at": null
      }
    }
  }

红线（BRO 2026-09-20 定的）：
  · ⚠ 取消挂载 = **只删这条记录** · 绝不动磁盘上任何东西
  · ⚠ 同一路径只挂一次（按规范化路径去重 · Windows 大小写不敏感）
  · ⚠ 只登记"确实存在的目录" —— 挂载时校验，挡住手滑粘错的路径
  · id 用目录名（好读好认）· 撞名自动加后缀 -2 / -3
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
PROJ_FILE = DATA_DIR / "projects.json"

logger = logging.getLogger("opus.projects")

MAX_PROJECTS = 200          # 防呆上限 · 够用得很
_ID_BAD = re.compile(r"[^0-9A-Za-z\u4e00-\u9fa5._-]+")

# BRO 2026-09-20 问：「是不是什么原子态啊、防竞态啊，是不是也都要做？」
#   要。projects.json 是「读-改-写」模式：两个请求同时进来会互相覆盖（丢一条项目）。
#   RLock（可重入）—— 写函数里会嵌套调 find_by_path，普通 Lock 会自己把自己锁死。
_LOCK = threading.RLock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write(path: Path, text: str) -> None:
    from .safe_write import atomic_write_text
    atomic_write_text(path, text, backup=True)


def _norm(p: str) -> str:
    """路径规范化 · 只用于比较，不落盘"""
    try:
        return os.path.normcase(os.path.normpath(str(p).strip()))
    except Exception:
        return str(p).strip().lower()


def _load_all() -> dict:
    if not PROJ_FILE.exists():
        return {"updated_at": None, "items": {}}
    try:
        # encoding="utf-8-sig": 无 BOM 的 utf-8 照读，带 BOM 的也照读（BOM 自动吃掉）。
        # 为什么必须容错：2026-09-28 我用 PowerShell `Set-Content -Encoding UTF8` 重写过这个文件
        #   （PS 5.1 的 UTF8 会写 BOM，且中文被按 ANSI 解再按 UTF-8 写 → 二次编码损坏），
        #   read_text("utf-8") 遇 BOM 直接抛 → 这层 except 把文件判成 corrupt 并重置 →
        #   BRO 一重启发现「挂的项目全没了」。
        # 这个文件不归引擎独占（用户手改、别的工具写、编辑器保存都可能带 BOM），
        # 读的一方得容错，而不是把还能救的内容当垃圾扔掉。
        d = json.loads(PROJ_FILE.read_text(encoding="utf-8-sig"))
        if not isinstance(d.get("items"), dict):
            d["items"] = {}
        return d
    except Exception as e:
        logger.warning("projects.json corrupt: %s · 备份后重置", e)
        try:
            import shutil
            import time as _t
            bak = PROJ_FILE.with_name(f"projects.json.corrupt-{int(_t.time())}")
            shutil.copy2(PROJ_FILE, bak)
            logger.warning("已备份损坏文件到 %s", bak.name)
        except Exception:
            pass
        return {"updated_at": None, "items": {}}


def _save_all(d: dict) -> None:
    d["updated_at"] = _now_iso()
    _atomic_write(PROJ_FILE, json.dumps(d, ensure_ascii=False, indent=2))


def _make_id(name: str, taken: set[str]) -> str:
    base = _ID_BAD.sub("-", (name or "").strip()).strip("-") or "project"
    base = base[:40]
    if base not in taken:
        return base
    for i in range(2, 999):
        cand = f"{base}-{i}"
        if cand not in taken:
            return cand
    return f"{base}-{int(datetime.now().timestamp())}"


def find_by_path(path: str) -> Optional[dict]:
    """按规范化路径查已挂的项目（去重用）"""
    want = _norm(path)
    with _LOCK:
        for e in (_load_all().get("items") or {}).values():
            if _norm(e.get("path", "")) == want:
                return e
    return None


def list_projects(*, include_archived: bool = True) -> list[dict]:
    """按 last_used_at 倒序（最近动过的在上）"""
    items = list((_load_all().get("items") or {}).values())
    if not include_archived:
        items = [e for e in items if not e.get("archived_at")]
    items.sort(key=lambda e: e.get("last_used_at") or e.get("created_at") or "", reverse=True)
    return items


def get_project(pid: str) -> Optional[dict]:
    return (_load_all().get("items") or {}).get(pid)


def add_project(path: str, *, name: str = "", profile: str = "标准") -> dict:
    """挂一个目录当项目

    · 路径必须存在（挡手滑）
    · 同一路径已挂过 → 返回已有的那条（was_new=False），不重复登记
    """
    raw = str(path or "").strip().strip('"').strip("'")
    if not raw:
        return {"ok": False, "error": "路径不能为空"}
    try:
        p = Path(raw)
        if not p.exists():
            return {"ok": False, "error": f"这个目录不存在：{raw}"}
        if not p.is_dir():
            return {"ok": False, "error": f"这是一个文件不是目录：{raw}"}
        abs_path = str(p.resolve())
    except Exception as e:
        return {"ok": False, "error": f"路径不合法：{e}"}

    dup = find_by_path(abs_path)
    if dup:
        return {"ok": True, "was_new": False, "duplicate": True, "project": dup}

    with _LOCK:          # 读-改-写整体持锁 · 两个请求同时挂不会互相覆盖
        d = _load_all()
        items = d.setdefault("items", {})
        if len(items) >= MAX_PROJECTS:
            return {"ok": False, "error": f"项目数到上限了（{MAX_PROJECTS}）"}

        nm = (name or "").strip() or Path(abs_path).name or "project"
        pid = _make_id(nm, set(items.keys()))
        now = _now_iso()
        entry = {
            "id": pid,
            "name": nm[:80],
            "path": abs_path,
            "profile": (profile or "标准").strip() or "标准",
            "handoff": "",
            "created_at": now,
            "last_used_at": now,
            "archived_at": None,
        }
        items[pid] = entry
        _save_all(d)
    logger.info("add_project · %s · %s", pid, abs_path)
    return {"ok": True, "was_new": True, "project": entry}

def update_project(pid: str, **fields) -> dict:
    """改名字 / 档位 / 交接条 / 归档状态 / 最近使用时间 · 传了才改"""
    with _LOCK:
        d = _load_all()
        items = d.setdefault("items", {})
        if pid not in items:
            return {"ok": False, "error": f"没有这个项目：{pid}"}
        e = items[pid]
        for k in ("name", "profile", "handoff", "last_used_at"):
            if k in fields and fields[k] is not None:
                e[k] = str(fields[k])[:400]
        if "archived" in fields and fields["archived"] is not None:
            e["archived_at"] = _now_iso() if fields["archived"] else None
        if fields.get("touch"):
            e["last_used_at"] = _now_iso()
        _save_all(d)
        return {"ok": True, "project": e}


# ── 详情支撑 · 读项目自己的「说明书」 + git 快照（BRO 2026-09-21 定的方案）────
# 为什么版本/进度存项目自己目录里而不存 Daemonkey 侧：
#   换机器 / 换实例 / 别人接手都跟着走；而且我进那个项目干活时读得到它。
# 判定分层（BRO 认可的逻辑）：
#   · 版本号 = 能自证的全自动 → git tag 优先（api 层定优先级）
#   · 进度 = 要判断的半自动 → OPUS.md 里程碑清单，勾必须带证据

OPUS_MD_NAME = "OPUS.md"
_VER_RE = re.compile(r"(?:^|\n)\s*(?:版本|version)\s*[:：]?\s*(v?\d[\w.\-]*)", re.IGNORECASE)
_MS_RE = re.compile(r"^\s*[-*]\s*\[([ xX])\]\s*(.+?)\s*$", re.MULTILINE)
_GIT_TIMEOUT = 5


def read_opus_md(path: str) -> dict:
    """读项目目录里的 OPUS.md → {exists, version, milestones, err}

    格式约定（写在项目根，我干完活顺手更）：
        # 项目名
        版本 0.3.1
        ## 进度
        - [x] 跑通单张识别
        - [ ] 准确率对比
    """
    out: dict = {"exists": False, "version": "", "milestones": [], "err": ""}
    try:
        p = Path(path or "") / OPUS_MD_NAME
        if not p.is_file():
            return out
        txt = p.read_text(encoding="utf-8", errors="replace")[:20000]
        out["exists"] = True
        m = _VER_RE.search(txt)
        if m:
            out["version"] = m.group(1).strip()
        for mm in _MS_RE.finditer(txt):
            if len(out["milestones"]) >= 50:
                break
            t = mm.group(2).strip()[:120]
            if t:
                out["milestones"].append({"text": t, "done": mm.group(1).lower() == "x"})
    except Exception as e:
        out["err"] = str(e)[:200]
    return out


def git_snapshot(path: str) -> dict:
    """项目目录的 git 现状 → {is_repo, branch, dirty, tag, ahead, behind}

    只读子命令 + 5 秒超时 + CREATE_NO_WINDOW（不闪黑窗）；任何一步失败都降级，不抛。
    """
    out: dict = {"is_repo": False, "branch": "", "dirty": 0, "tag": "", "ahead": 0, "behind": 0}

    def _git(*args: str):
        try:
            r = subprocess.run(
                ["git", "-C", str(path), *args],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=_GIT_TIMEOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return r.stdout if r.returncode == 0 else None
        except Exception:
            return None

    if _git("rev-parse", "--is-inside-work-tree") is None:
        return out
    out["is_repo"] = True
    out["branch"] = (_git("rev-parse", "--abbrev-ref", "HEAD") or "").strip()
    st = _git("status", "--porcelain")
    if st is not None:
        out["dirty"] = len([ln for ln in st.splitlines() if ln.strip()])
    t = _git("describe", "--tags", "--abbrev=0")
    if t:
        out["tag"] = t.strip()
    lr = _git("rev-list", "--left-right", "--count", "@{upstream}...HEAD")
    if lr:
        parts = lr.strip().split()
        if len(parts) == 2:
            try:
                out["behind"], out["ahead"] = int(parts[0]), int(parts[1])
            except Exception:
                pass
    return out


def remove_project(pid: str) -> dict:
    """移出项目 —— ⚠ 只删这条登记 · 磁盘上的目录和文件一个都不动"""
    with _LOCK:
        d = _load_all()
        items = d.setdefault("items", {})
        if pid not in items:
            return {"ok": True, "no_op": True}
        gone = items.pop(pid)
        _save_all(d)
    logger.info("remove_project(只删登记) · %s · %s", pid, gone.get("path"))
    return {"ok": True, "removed": pid, "path_untouched": gone.get("path")}
