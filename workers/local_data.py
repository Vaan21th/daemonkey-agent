"""本地磁盘占用 · 设置页可选清理的唯一事实源。

只扫/只删白名单桶。soul / .env / 工坊应用配方 / 知识库不在这里。
"""
from __future__ import annotations

import threading

import json
import logging
import os
import re
import shutil
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# suggest=True 的默认可勾：缓存/草稿，不是用户成品
BUCKETS = (
    {
        "id": "workshop_outputs",
        "label": "工坊产出",
        "hint": "应用跑出来的图、音、视频",
        "rel": "data/workshop/outputs",
        "danger": False,
        "suggest": False,
    },
    {
        "id": "presentations",
        "label": "演示稿",
        "hint": "PPT、配图、历史版",
        "rel": "data/presentations",
        "danger": False,
        "suggest": False,
    },
    {
        "id": "reports",
        "label": "报告",
        "hint": "生成的 Word",
        "rel": "data/reports",
        "danger": False,
        "suggest": False,
    },
    {
        "id": "spreadsheets",
        "label": "表格",
        "hint": "生成的 Excel",
        "rel": "data/spreadsheets",
        "danger": False,
        "suggest": False,
    },
    {
        "id": "design",
        "label": "HTML 原型",
        "hint": "可点的页面稿",
        "rel": "data/design",
        "danger": False,
        "suggest": False,
    },
    {
        "id": "workshop_exports",
        "label": "工坊导出包",
        "hint": "分享用的导出文件",
        "rel": "data/workshop/exports",
        "danger": False,
        "suggest": False,
    },
    {
        "id": "attachments",
        "label": "对话附件",
        "hint": "往对话里丢过的文件",
        "rel": "data/runtime/attachments",
        "danger": False,
        "suggest": False,
    },
    {
        "id": "shelf_preview",
        "label": "成品预览缓存",
        "hint": "翻页预览用的临时图，清了会再生成",
        "rel": "data/runtime/shelf_preview",
        "danger": False,
        "suggest": True,
    },
    {
        "id": "scratch",
        "label": "运行草稿",
        "hint": "探针和临时文件",
        "rel": "data/runtime/scratch",
        "danger": False,
        "suggest": True,
    },
    {
        "id": "cache",
        "label": "本地缓存",
        "hint": "检索等缓存，清了会再长",
        "rel": "data/cache",
        "danger": False,
        "suggest": True,
    },
    {
        "id": "sessions",
        "label": "对话记录",
        "hint": "工作台聊过的记录，清了找不回",
        "rel": "sessions",
        "danger": True,
        "suggest": False,
    },
)

_BUCKET_BY_ID = {b["id"]: b for b in BUCKETS}


def human_bytes(n: int) -> str:
    n = max(0, int(n or 0))
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.1f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def _root(root: Path | None) -> Path:
    return Path(root).resolve() if root is not None else Path(__file__).resolve().parent.parent


def _bucket_dir(root: Path, rel: str) -> Path:
    base = (root / rel).resolve()
    base.relative_to(root)
    return base


def _walk_files(folder: Path):
    if not folder.exists():
        return
    for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
        keep = []
        for name in dirnames:
            p = Path(dirpath) / name
            if p.is_symlink():
                continue
            keep.append(name)
        dirnames[:] = keep
        for name in filenames:
            p = Path(dirpath) / name
            if p.is_symlink():
                continue
            yield p


def _dir_stats(folder: Path) -> tuple[int, int]:
    files = 0
    bytes_ = 0
    for p in _walk_files(folder):
        try:
            bytes_ += p.stat().st_size
            files += 1
        except OSError:
            continue
    return files, bytes_


def usage(*, root: Path | None = None) -> dict:
    base = _root(root)
    buckets = []
    total_files = 0
    total_bytes = 0
    for spec in BUCKETS:
        folder = _bucket_dir(base, spec["rel"])
        files, nbytes = _dir_stats(folder) if folder.exists() else (0, 0)
        total_files += files
        total_bytes += nbytes
        buckets.append({
            "id": spec["id"],
            "label": spec["label"],
            "hint": spec["hint"],
            "rel": spec["rel"],
            "danger": spec["danger"],
            "suggest": spec["suggest"],
            "exists": folder.exists(),
            "files": files,
            "bytes": nbytes,
            "size": human_bytes(nbytes),
        })
    return {
        "buckets": buckets,
        "total_files": total_files,
        "total_bytes": total_bytes,
        "total_size": human_bytes(total_bytes),
    }


def _purge_tree(folder: Path) -> tuple[int, int, list[str]]:
    deleted = 0
    freed = 0
    errors: list[str] = []
    if not folder.exists():
        return deleted, freed, errors
    for p in list(_walk_files(folder)):
        try:
            freed += p.stat().st_size
            p.unlink()
            deleted += 1
        except OSError as e:
            errors.append(f"{p.name}: {e}")
    for dirpath, dirnames, _filenames in os.walk(folder, topdown=False, followlinks=False):
        here = Path(dirpath)
        if here == folder:
            continue
        try:
            here.rmdir()
        except OSError:
            pass
    return deleted, freed, errors


def purge(ids: list[str], *, root: Path | None = None) -> dict:
    wanted = []
    for raw in ids or []:
        bid = str(raw or "").strip()
        if bid and bid not in wanted:
            wanted.append(bid)
    unknown = [i for i in wanted if i not in _BUCKET_BY_ID]
    if unknown:
        raise ValueError("unknown buckets: " + ", ".join(unknown))
    if not wanted:
        raise ValueError("没有选要清理的类别")
    base = _root(root)
    results = []
    total_deleted = 0
    total_freed = 0
    for bid in wanted:
        spec = _BUCKET_BY_ID[bid]
        folder = _bucket_dir(base, spec["rel"])
        deleted, freed, errors = _purge_tree(folder)
        total_deleted += deleted
        total_freed += freed
        results.append({
            "id": bid,
            "label": spec["label"],
            "deleted": deleted,
            "freed": freed,
            "freed_size": human_bytes(freed),
            "errors": errors[:8],
        })
    return {
        "ok": True,
        "deleted": total_deleted,
        "freed": total_freed,
        "freed_size": human_bytes(total_freed),
        "results": results,
        "usage": usage(root=base),
    }


# ─── wish-9d30a22e · 临时件扫描 + 可恢复清理（LLM 清理入口的落地）─────
#
# 这一段只做「找」和「搬」两件确定性的事 · 「判能不能删」交给 LLM
# （本文件的 analyze_cleanup · 干净上下文 · 不注入灵魂前缀）。
# 交接口的红线在这里体现：
#   ① 清理必须当事人点头 —— 这里只给候选 + 搬运 · 从不自己删
#   ② 别把「文件多」当「垃圾」—— 按丢了会怎样命名分组 · 不确定的留给用户
#   ③ 别自己发明目录规范 —— 扫的规则照抄现有命名惯例（_tmp_ / _pt / _daemon）

# 根目录散件：按命名惯例匹配（顺序敏感 · 先具体后泛化）
_ROOT_RULES = (
    ("守护进程日志", re.compile(r"^_daemon.*\.(log|err)$", re.I)),
    ("临时文本", re.compile(r"^_pt.*\.(txt|md|json)$", re.I)),
    ("临时脚本/数据", re.compile(r"^_tmp_", re.I)),
    ("环境备份", re.compile(r"^\.env\.(bak|old|save|prev)", re.I)),
    ("散落网页稿", re.compile(r"\.html?$", re.I)),
    ("日志/转储", re.compile(r".*\.(log|err|tmp|bak|dump|old)$", re.I)),
    ("其他临时件", re.compile(r"^_")),
)

# 这些名字永远不进候选（是不可再生的入口 / 正在被进程占用）
_NEVER = {
    ".env", ".env.example", ".gitignore",
    "Daemonkey.exe", "ROLLBACK.bat", "repair.bat", "start.bat", "run.bat",
}

# data/ 顶层只认这些前缀（别的地方一概不碰）
_DATA_PREFIXES = ("_tmp_", "_pt", "_scratch_", "_probe_")


def _sample_names(folder: Path, limit: int = 8) -> list:
    names = []
    try:
        for _dirpath, _dirnames, filenames in os.walk(folder, followlinks=False):
            for nm in sorted(filenames)[:limit]:
                names.append(nm)
                if len(names) >= limit:
                    return names
            if len(names) >= limit:
                break
    except OSError:
        pass
    return names


def _candidate(rel: str, kind: str, files: int, nbytes: int, mtime: float,
               sample=None, note: str = "") -> dict:
    rel = rel.replace("\\", "/")
    return {
        "id": ("d:" if kind == "dir" else "f:") + rel,
        "path": rel,
        "kind": kind,
        "files": files,
        "bytes": nbytes,
        "size": human_bytes(nbytes),
        "mtime": time.strftime("%Y-%m-%d", time.localtime(mtime)) if mtime else "",
        "sample": list(sample or []),
        "note": note,
    }


def scan_temp_candidates(*, root: Path | None = None) -> dict:
    """扫出「可能是临时件」的候选 · 只扫根目录 + data/ 顶层 · 纯工程零 LLM。"""
    base = _root(root)
    cands: list = []

    # ① 根目录散件
    try:
        for e in os.scandir(base):
            if e.is_symlink() or e.is_dir(follow_symlinks=False):
                continue
            name = e.name
            if name in _NEVER:
                continue
            label = ""
            for lab, pat in _ROOT_RULES:
                if pat.search(name):
                    label = lab
                    break
            if not label:
                continue
            try:
                stt = e.stat()
            except OSError:
                continue
            cands.append(_candidate(name, "file", 1, stt.st_size, stt.st_mtime, note=label))
    except OSError:
        pass

    # ② data/ 顶层的临时目录 / 散件
    data_dir = base / "data"
    if data_dir.exists():
        try:
            for e in os.scandir(data_dir):
                if e.is_symlink() or not e.name.startswith(_DATA_PREFIXES):
                    continue
                try:
                    stt = e.stat()
                except OSError:
                    continue
                if e.is_dir(follow_symlinks=False):
                    files, nbytes = _dir_stats(Path(e.path))
                    cands.append(_candidate(f"data/{e.name}", "dir", files, nbytes,
                                            stt.st_mtime, _sample_names(Path(e.path)),
                                            note="项目临时产物"))
                else:
                    cands.append(_candidate(f"data/{e.name}", "file", 1, stt.st_size,
                                            stt.st_mtime, note="临时散件"))
        except OSError:
            pass

    cands.sort(key=lambda c: -(c.get("bytes") or 0))
    total_bytes = sum(c["bytes"] for c in cands)
    return {
        "candidates": cands,
        "total_files": sum(c["files"] for c in cands),
        "total_bytes": total_bytes,
        "total_size": human_bytes(total_bytes),
        "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


TRASH_DIR = "data/runtime/trash"


def purge_paths(paths: list, *, mode: str = "trash", root: Path | None = None) -> dict:
    """把选中的候选清掉 · 只认扫描出的 id。

    mode="trash"（默认）→ 搬到 data/runtime/trash/<ts>/ · 还能捞回来
    mode="delete"        → 直接删干净 · 找不回

    「根本不会发生」：前端就算传了别的路径也过不了这关 ——
    只有本次 scan_temp_candidates() 扫得出来的东西才动得了。
    """
    if mode not in ("trash", "delete"):
        raise ValueError("不认的清理方式: " + str(mode))
    base = _root(root)
    allowed = {c["id"] for c in scan_temp_candidates(root=base)["candidates"]}
    picked, bad = [], []
    for raw in paths or []:
        pid = str(raw or "").strip()
        if not pid:
            continue
        (picked if pid in allowed else bad).append(pid)
    if bad:
        raise ValueError("不在可清理候选里: " + ", ".join(bad[:5]))
    if not picked:
        raise ValueError("没有选要清理的东西")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    trash = base / TRASH_DIR / stamp
    if mode == "trash":
        trash.mkdir(parents=True, exist_ok=True)

    moved, freed, errors, items = 0, 0, [], []
    for pid in picked:
        rel = pid.split(":", 1)[1]
        src_p = (base / rel).resolve()
        try:
            src_p.relative_to(base)        # 越界直接拒
        except ValueError:
            errors.append(f"{rel}: 越界")
            continue
        if not src_p.exists():
            errors.append(f"{rel}: 已不存在")
            continue
        files, nbytes = (_dir_stats(src_p) if src_p.is_dir() else (1, src_p.stat().st_size))
        try:
            if mode == "trash":
                dst = trash / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    if dst.is_dir():
                        shutil.rmtree(dst, ignore_errors=True)
                    else:
                        dst.unlink()
                shutil.move(str(src_p), str(dst))
            elif src_p.is_dir():
                shutil.rmtree(src_p)
            else:
                src_p.unlink()
        except OSError as ex:
            errors.append(f"{rel}: {ex}")
            continue
        moved += 1
        freed += nbytes
        items.append({"path": rel, "files": files, "size": human_bytes(nbytes)})

    # 顺手把已清掉的从扫描结果里摘掉 —— 不然切走再回来，清单里还挂着已经没了的条目
    if moved and items:
        try:
            st = load_scan_state(root=base)
            res = st.get("result") or {}
            if res.get("items"):
                gone = {it["path"] for it in items}
                res["items"] = [x for x in res["items"] if x.get("path") not in gone]
                st["result"] = res
                _save_scan_state(st, root=base)
        except Exception:
            pass

    return {
        "ok": True,
        "mode": mode,
        "moved": moved,
        "freed": freed,
        "freed_size": human_bytes(freed),
        "trash": (f"{TRASH_DIR}/{stamp}" if mode == "trash" and moved else ""),
        "items": items,
        "errors": errors[:8],
    }


# ─── 回收站：列出 / 还原 / 清空 / 剪枝 ─────────────────────
#
# 2026-10-01 补。之前只有 purge_paths() 往里【写】，没有任何往外的通道 ——
# 挪进回收站的东西既看不见也清不掉，等于把垃圾从 A 搬到 B。
# （BRO 问「时间久了文件会很多吗」时顺出来的；知识库删档也要把拖拽副本挪进来，
#   所以这个口必须先补全，否则一边修一边漏。）
#
# 布局：TRASH_DIR/<ts>/<原相对路径> · 一个 <ts> 目录 = 一次清理 = 一个「批次」。
# 用批次日录名算年龄，比看文件 mtime 准（mtime 会被拷来拷去改掉）。

TRASH_KEEP_DAYS = 30


def _trash_root(root: Path | None = None) -> Path:
    return _root(root) / TRASH_DIR


def list_trash(*, root: Path | None = None) -> dict:
    """列回收站里的全部批次（最新的排前面）。"""
    tdir = _trash_root(root)
    batches: list[dict] = []
    if tdir.exists():
        for b in sorted(tdir.iterdir(), reverse=True):
            if not b.is_dir():
                continue
            files, nbytes = _dir_stats(b)
            if not files:
                continue
            try:
                age = max(0.0, (time.time() - b.stat().st_mtime) / 86400)
            except OSError:
                age = 0.0
            batches.append({
                "batch": b.name,
                "files": files,
                "bytes": nbytes,
                "size": human_bytes(nbytes),
                "age_days": round(age, 1),
                "left_days": int(max(0, TRASH_KEEP_DAYS - age)),
                "items": [p.relative_to(b).as_posix() for p in b.rglob("*") if p.is_file()][:200],
            })
    total = sum(x["bytes"] for x in batches)
    return {
        "batches": batches,
        "count": len(batches),
        "total_files": sum(x["files"] for x in batches),
        "total_bytes": total,
        "total_size": human_bytes(total),
        "keep_days": TRASH_KEEP_DAYS,
        "trash_rel": TRASH_DIR,
        "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def restore_trash(items: list, *, root: Path | None = None) -> dict:
    """还原：把 trash/<batch>/<rel> 挪回 base/<rel>。

    items = ["<batch>/<rel>", ...] —— 注意【必须带批次名】。
    list_trash 返回的每个批里有两样东西，别拿错:
        b["batch"]          = 批次名（如 20261001-002941）
        b["items"]          = 批次内相对路径，【不含批次名】
    所以入参要自己拼:  f"{b['batch']}/{item}"
    越界判据：拼出的目标必须落在 base 底下，否则直接拒。
    """
    base = _root(root)
    tdir = _trash_root(root)
    moved, errors = 0, []
    for raw in items or []:
        rel = str(raw or "").strip().replace("\\", "/")
        if not rel or "/" not in rel:
            errors.append(f"{rel or '(空)'}: 写法应是 <批次>/<相对路径>")
            continue
        src = (tdir / rel).resolve()
        try:
            src.relative_to(tdir.resolve())        # 越界直接拒
        except ValueError:
            errors.append(f"{rel}: 越界")
            continue
        if not src.is_file():
            errors.append(f"{rel}: 已不在回收站里")
            continue
        # 去掉批次层 = 原始相对工程根的路径
        origin = src.relative_to(tdir.resolve())
        origin = Path(*origin.parts[1:]) if len(origin.parts) > 1 else Path(origin.name)
        dst = base / origin
        try:
            dst.resolve().relative_to(base)
        except ValueError:
            errors.append(f"{rel}: 目标越界")
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                errors.append(f"{origin.as_posix()}: 原位置已有同名文件")
                continue
            shutil.move(str(src), str(dst))
            moved += 1
        except OSError as ex:
            errors.append(f"{rel}: {ex}")
    return {"ok": True, "moved": moved, "errors": errors[:8]}


def empty_trash(*, root: Path | None = None, batch: str | None = None) -> dict:
    """清空回收站（给了 batch 就只清那一批）—— 真删，找不回。"""
    tdir = _trash_root(root)
    freed, removed = 0, 0
    errors = []
    targets = []
    if batch:
        p = tdir / str(batch).strip()
        try:
            p.resolve().relative_to(tdir.resolve())
            targets = [p]
        except ValueError:
            return {"ok": False, "error": "批次名不合法"}
    elif tdir.exists():
        targets = [b for b in tdir.iterdir() if b.is_dir()]
    for t in targets:
        if not t.exists():
            continue
        _, nbytes = _dir_stats(t)
        try:
            shutil.rmtree(t)
            freed += nbytes
            removed += 1
        except OSError as ex:
            # 不抛（面板不该因此打不开），但也不能静默 —— 文件被占用时 Windows 上很常见，
            # 吞掉就会把「清空失败」显示成「清空成功」。
            logger.warning("回收站批次删除失败 %s: %s", t.name, ex)
            errors.append(f"{t.name}: {ex}")
    return {"ok": True, "batches_removed": removed, "freed": freed,
            "freed_size": human_bytes(freed), "errors": errors[:8]}


def prune_trash(*, root: Path | None = None, days: int = TRASH_KEEP_DAYS) -> dict:
    """过了保留期的批次自动清掉（超过 days 天没人动过）。"""
    tdir = _trash_root(root)
    if not tdir.exists():
        return {"ok": True, "batches_removed": 0, "freed": 0, "freed_size": "0 B"}
    cutoff = time.time() - days * 86400
    freed, removed = 0, 0
    for b in list(tdir.iterdir()):
        if not b.is_dir():
            continue
        try:
            if b.stat().st_mtime >= cutoff:
                continue
        except OSError:
            continue
        _, nbytes = _dir_stats(b)
        try:
            shutil.rmtree(b)
            freed += nbytes
            removed += 1
        except OSError:
            pass
    return {"ok": True, "batches_removed": removed, "freed": freed,
            "freed_size": human_bytes(freed), "days": days}


# ─── wish-9d30a22e · 临时件「清理顾问」──────────────────────
#
# 上面 scan_temp_candidates() 只做「找」（确定性 · 零 LLM）。
# 这一段把扫出来的清单喂给一个【干净上下文】的子推理判「能删 / 要留」：
# run_subagent 用完整替换的 system prompt · 【天然不注入 2 万 token 的灵魂前缀】
# （replan 走的就是同一条路）。判完出表单 · 用户勾 · purge_paths() 搬走。

CLEANUP_SYSTEM = (
    "你是被请来看一眼【本地项目目录里堆着的临时文件】、帮用户判断哪些可以清掉的助手。\n"
    "你只能【看】（可以 read_file / glob_files 确认）· 【绝不执行任何删除】。\n\n"
    "会给你一份已经扫好的候选清单（路径 / 类型 / 大小 / 最后改动 / 里头几个文件名 · 以及初步归类）。\n"
    "清单本身已经很全 —— 优先直接判，只有某条实在看不出来源时，才用 read_file 看一眼它开头几行。\n\n"
    "判定要点：\n"
    "  · 日志 / 临时文本 / 临时脚本 —— 基本可清（丢了无感）\n"
    "  · 环境备份 (.env.bak.*) —— 留最近一个，其余可清\n"
    "  · 项目临时产物（某个功能开发时留下的整份源码拷 / patch / 测试件）—— 重点看 · 读不出用途就 keep\n"
    "  · 不确定的一律 keep：宁可留着，也别让人丢还要用的东西\n\n"
    "【输出格式 · 严格 JSON 数组 · 不要 markdown 围栏 · 不要任何多余的话】\n"
    "[\n"
    '  {"path": "候选里的 path 原样", "what": "大概是什么时候、做什么事留下的（一句话）",'
    ' "keep": true/false, "reason": "为什么（一句话）", "risk": "low|medium|high"}\n'
    "]\n"
    "risk = 删了真出问题的可能性。path 必须与清单里给的一字不差，不能多不能少。"
)

_ITEM_KEYS = ("id", "path", "kind", "files", "size", "bytes", "mtime")


def _render_candidates(cands: list) -> str:
    total = human_bytes(sum(c["bytes"] for c in cands))
    lines = [f"共 {len(cands)} 条候选 · 合计 {total}\n"]
    for c in cands:
        samples = "、".join(c.get("sample") or [])[:120]
        lines.append(
            f"- path: {c['path']}\n"
            f"  类型: {'目录' if c['kind'] == 'dir' else '文件'} · {c['files']} 个文件 · {c['size']}"
            f" · 最后改动 {c['mtime'] or '?'} · 归类: {c.get('note') or '?'}\n"
            f"  里头: {samples or '(无)'}"
        )
    return "\n".join(lines)


def _extract_json(text: str) -> list:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    i, j = t.find("["), t.rfind("]")
    if i < 0 or j < i:
        raise ValueError("顾问没给出 JSON 数组")
    data = json.loads(t[i:j + 1])
    if not isinstance(data, list):
        raise ValueError("顾问给的不是数组")
    return data


def analyze_cleanup(*, root=None, max_iterations: int = 6) -> dict:
    """扫 + 判 · 返回可直接给前端渲染的表单。"""
    scan = scan_temp_candidates(root=root)
    cands = scan["candidates"]
    if not cands:
        return {"ok": True, "items": [], "scanned": 0,
                "suggest_size": "0 B", "suggest_bytes": 0,
                "summary": "没扫到可清理的临时件"}

    from daemon_runtime import RUNTIME
    if getattr(RUNTIME, "client", None) is None:
        raise RuntimeError("RUNTIME.client 未就绪（daemon 还没起完？）")

    from workers.subagent_runner import run_subagent

    wl = {"read_file", "glob_files"}
    try:
        from agent_tools import REGISTRY
        wl = {t for t in wl if t in REGISTRY}
    except Exception:
        pass

    r = run_subagent(
        system=CLEANUP_SYSTEM,
        user_msg=_render_candidates(cands),
        runtime=RUNTIME,
        tools_whitelist=wl,
        max_iterations=max_iterations,
        persist=False,
        ledger_source="cleanup_advisor",
    )
    if not r or not r.ok:
        raise RuntimeError(getattr(r, "error", None) or "顾问没跑通")

    raw = _extract_json(r.text)
    by_path = {c["path"]: c for c in cands}
    items = []
    for row in raw:
        p = str((row or {}).get("path") or "").strip().replace("\\", "/")
        c = by_path.get(p)
        if not c:
            continue  # 顾问编了个不存在的路径 → 丢掉
        items.append({
            **{k: c[k] for k in _ITEM_KEYS},
            "note": c.get("note") or "",
            "what": str(row.get("what") or "")[:200],
            "keep": bool(row.get("keep")),
            "reason": str(row.get("reason") or "")[:200],
            "risk": str(row.get("risk") or "medium")[:10],
        })

    # 顾问漏掉的候选 → 兜底列成「没判出来 · 先留着」，不让它凭空消失
    seen = {i["path"] for i in items}
    for c in cands:
        if c["path"] in seen:
            continue
        items.append({
            **{k: c[k] for k in _ITEM_KEYS},
            "note": c.get("note") or "",
            "what": "（顾问没给结论）",
            "keep": True,
            "reason": "没判出来 · 先留着",
            "risk": "medium",
        })

    droppable = [i for i in items if not i["keep"]]
    suggest_bytes = sum(i["bytes"] for i in droppable)
    return {
        "ok": True,
        "scanned": len(cands),
        "items": items,
        "suggest_bytes": suggest_bytes,
        "suggest_size": human_bytes(suggest_bytes),
        "summary": f"扫到 {len(cands)} 条 · 建议清 {len(droppable)} 条（{human_bytes(suggest_bytes)}）",
    }


# ─── wish-9d30a22e 续 · 扫描状态持久化 ──────────────────────
#
# BRO 实测反馈：扫完切个页面结果就没了；扫到一半切走再回来也不认。
# 根因是扫描挂在「一次同步 POST 等 68 秒」上 —— 状态只活在那个请求里。
# 改成：后台线程跑 · 状态落 data/runtime/temp_scan.json ·
#       前端挂载时查这个文件 → 进行中 / 已完成 / 失败都留得住。

SCAN_STATE_REL = "data/runtime/temp_scan.json"
_scan_lock = threading.Lock()
_SCAN_STALE_SEC = 900          # 15 分钟没动静 → 当它死在半路了


def _scan_state_path(root: Path | None = None) -> Path:
    return _root(root) / SCAN_STATE_REL


def load_scan_state(*, root: Path | None = None) -> dict:
    try:
        d = json.loads(_scan_state_path(root).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {"status": "idle"}
    except Exception:
        return {"status": "idle"}


def _save_scan_state(d: dict, *, root: Path | None = None) -> None:
    p = _scan_state_path(root)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


def _is_scan_stale(st: dict) -> bool:
    try:
        t0 = time.mktime(time.strptime(str(st.get("started_at") or ""), "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return True
    return (time.time() - t0) > _SCAN_STALE_SEC


def start_scan(*, root: Path | None = None) -> dict:
    """起一次后台扫描。已经在跑就把当前状态原样给它 —— 绝不重复起第二个。"""
    with _scan_lock:
        cur = load_scan_state(root=root)
        if cur.get("status") == "running" and not _is_scan_stale(cur):
            return cur
        st = {"status": "running", "step": "扫目录…",
              "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        _save_scan_state(st, root=root)
    threading.Thread(target=_scan_worker, args=(root,), daemon=True).start()
    return st


def _scan_worker(root: Path | None = None) -> None:
    started = (load_scan_state(root=root).get("started_at")
               or time.strftime("%Y-%m-%dT%H:%M:%S"))
    try:
        _save_scan_state({"status": "running", "step": "扫目录…", "started_at": started}, root=root)
        _save_scan_state({"status": "running", "started_at": started,
                          "step": "让模型逐条判「能删 / 要留」…"}, root=root)
        result = analyze_cleanup(root=root)
        _save_scan_state({"status": "done", "started_at": started,
                          "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                          "result": result}, root=root)
    except Exception as e:            # 失败也要留痕 · 别让前端永远转圈
        _save_scan_state({"status": "error", "started_at": started,
                          "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                          "error": f"{type(e).__name__}: {e}"}, root=root)


def scan_status(*, root: Path | None = None) -> dict:
    """前端查的当前状态（含结果）。顺手把僵死的 running 判成 error。"""
    st = load_scan_state(root=root)
    if st.get("status") == "running" and _is_scan_stale(st):
        st = {"status": "error", "error": "扫描进程失联（超时）· 可以再扫一遍"}
        _save_scan_state(st, root=root)
    return st
