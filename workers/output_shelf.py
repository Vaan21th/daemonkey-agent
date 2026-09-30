"""产物货架 · 报告 / 演示稿 / 表格 / HTML 原型 清单与预览 md。"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from stat import S_ISREG

from workers.output_versions import deck_pages, family_key, fold_items, is_hidden_output, restore_current

_ROOT = Path(__file__).resolve().parent.parent

_KIND_SPEC = {
    "reports": {
        "rel": Path("data") / "reports",
        "suffix": ".docx",
        "download_prefix": "/reports/",
        "preview_prefix": "/reports/preview/",
    },
    "decks": {
        "rel": Path("data") / "presentations",
        "suffix": ".pptx",
        "download_prefix": "/presentations/",
        "preview_prefix": "/shelf/preview/decks/",
    },
    "sheets": {
        "rel": Path("data") / "spreadsheets",
        "suffix": ".xlsx",
        "download_prefix": "/spreadsheets/",
        "preview_prefix": "/shelf/preview/sheets/",
    },
    "protos": {
        "rel": Path("data") / "design",
        "suffix": ".html",
        "download_prefix": "/stage/file/data/design/",
        "preview_prefix": "/stage/file/data/design/",
    },
}


def _root(root: Path | None = None) -> Path:
    return Path(root) if root is not None else _ROOT


# ── 产物归属 (BRO 2026-09-18) ────────────────────────────────────────────
# 产物库每张卡要挂一颗「这是哪场对话做的」药丸 · 点了跳回那场。
# 数据源 = sessions/_index.json 的 working_docs[].origin (唯一权威 ·
# wish-1518b97f.2 钉死: 只认产出者 · 不认「谁碰过」) · doc_orphans.json 兜底
# 那些产出它的对话已被删的历史归属。
#
# ⚠ 覆盖面事实: 绑定机制 2026-09-14 才上线 · 125 份产物里只有 11 份有 origin。
#   所以 session_id 为空是【正常态】· 前端要给「无归属」降级药丸 (虚线 · 不可点)。
_OWNER_CACHE: dict = {"key": None, "exact": {}, "family": {}}


def _norm_rel(p) -> str:
    """归一成 data/ 开头的 posix 相对路径 (index.json 与 open_path 都是这个形态)。"""
    rel = str(p or "").strip().replace("\\", "/")
    if not rel:
        return ""
    if rel.startswith("file://"):
        rel = rel[7:]
    if rel.startswith("/"):
        rel = "data" + rel
    return rel


def _fam(name: str) -> str:
    """文件名 → family (历史版本折叠后仍认得出同一份稿的场)。"""
    try:
        return family_key(name)
    except Exception:
        return Path(name or "").stem


def _owner_map(*, root: Path | None = None) -> tuple[dict, dict]:
    """→ (相对路径→归属, family→归属)。按 _index.json 的 (mtime, size) 缓存。

    family 索引是必需的: 货架列表会把 _hist_ 旧版折进历史 · 当前行显示的是主文件名 ·
    而 _index.json 里绑定的可能正是那个历史文件名 (实例: AI_AGENT_新增页_v5)。
    """
    base = _root(root)
    idx = base / "sessions" / "_index.json"
    try:
        st = idx.stat()
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        return {}, {}
    if _OWNER_CACHE.get("key") == key:
        return _OWNER_CACHE["exact"], _OWNER_CACHE["family"]
    try:
        data = json.loads(idx.read_text(encoding="utf-8")) or {}
    except Exception:
        data = {}
    labels = {
        sid: str(m.get("label") or "").strip()
        for sid, m in data.items() if isinstance(m, dict)
    }
    exact: dict[str, dict] = {}
    fam: dict[str, dict] = {}
    for sid, meta in data.items():
        if not isinstance(meta, dict):
            continue
        for d in meta.get("working_docs") or []:
            if not isinstance(d, dict):
                continue
            rel = _norm_rel(d.get("path") or "")
            if not rel:
                continue
            org = str(d.get("origin") or "").strip() or sid
            rec = {"sid": org, "label": labels.get(org, "")}
            exact[rel] = rec
            fam.setdefault(_fam(Path(rel).name), rec)
    # 孤儿兜底: 产出它的场已删 · 归属不能跟着丢
    try:
        orph = json.loads(
            (base / "data" / "runtime" / "doc_orphans.json").read_text(encoding="utf-8")
        ) or {}
    except Exception:
        orph = {}
    for k, v in orph.items():
        rel = _norm_rel(k)
        if not rel or rel in exact:
            continue
        sid = str(v or "").strip()
        rec = {"sid": sid, "label": labels.get(sid, "")}
        exact[rel] = rec
        fam.setdefault(_fam(Path(rel).name), rec)
    _OWNER_CACHE.update({"key": key, "exact": exact, "family": fam})
    return exact, fam


def attach_session_info(items: list[dict]) -> None:
    """给【收藏项】补 session_id / session_label（wish-e16b1f52）

    favorites.json 的 item 结构跟产物库不同：它用 ref_id 存 open_path 而不是 open_path/name。
    这里适配一层扔给 _attach_sessions·带 _it 回写。只处理 kind=output 的项。
    """
    if not items:
        return
    rows: list[dict] = []
    for it in items:
        if it.get("kind") != "output":
            continue
        ref = str(it.get("ref_id") or "").replace("\\", "/")
        if not ref:
            continue
        rows.append({"open_path": ref, "name": ref.rsplit("/", 1)[-1], "_it": it})
    if not rows:
        return
    _attach_sessions(rows)
    for r in rows:
        r["_it"]["session_id"] = r.get("session_id") or ""
        r["_it"]["session_label"] = r.get("session_label") or ""


def _attach_sessions(items: list[dict], *, root: Path | None = None) -> None:
    """就地给每项补 session_id / session_label / is_favorited

    (无归属留空串 · 前端据此走降级态；is_favorited 供产物卡上的 ⭐)
    """
    if not items:
        return
    try:
        from workers.favorites import fav_set
        fav = fav_set("output")   # ref_id = open_path (跨 kind 不重 · 比 name 稳)
    except Exception:
        fav = set()
    exact, fam = _owner_map(root=root)
    for it in items:
        rec = None
        if exact or fam:
            rec = exact.get(_norm_rel(it.get("open_path") or ""))
            if not rec:
                rec = fam.get(_fam(it.get("name") or ""))
        it["session_id"] = str((rec or {}).get("sid") or "")
        it["session_label"] = str((rec or {}).get("label") or "")
        it["is_favorited"] = _norm_rel(it.get("open_path") or "") in fav


def _safe_name(name: str, suffix: str) -> str:
    name = (name or "").strip()
    if not name.lower().endswith(suffix):
        raise ValueError(f"filename 必须以 {suffix} 结尾")
    if "/" in name or "\\" in name or ".." in name or "\x00" in name:
        raise ValueError("invalid filename")
    if name.startswith(".") or name.startswith("~") or name.startswith("~$"):
        raise ValueError("hidden / temp files forbidden")
    return name


def _list_html_protos(*, root: Path | None = None) -> dict:
    """data/design 下的 html · 含子目录 · html 本身就是源。"""
    base = _root(root)
    folder = base / "data" / "design"
    folder.mkdir(parents=True, exist_ok=True)
    items = []
    found: list[Path] = []
    for ext in ("*.html", "*.htm"):
        found.extend(folder.rglob(ext))
    for p in found:
        if is_hidden_output(p.name):
            continue
        try:
            rel = p.relative_to(folder).as_posix()
            if ".." in rel.split("/"):
                continue
            stat = p.stat()
        except (ValueError, OSError):
            continue
        open_path = f"data/design/{rel}"
        items.append({
            "name": rel,
            "title": p.stem,
            "kind": "protos",
            "size_kb": round(stat.st_size / 1024, 1),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
            "download_url": "/stage/file/" + open_path,
            "preview_url": "/stage/file/" + open_path,
            "has_md_source": True,
            "open_path": open_path,
            "pages": 0,
        })
    items.sort(key=lambda it: it.get("created_at") or "", reverse=True)
    _attach_sessions(items, root=root)
    return {
        "kind": "protos",
        "count": len(items),
        "items": items,
        "directory": "data/design",
    }


def list_kind(kind: str, *, root: Path | None = None) -> dict:
    if kind == "protos":
        return _list_html_protos(root=root)
    spec = _KIND_SPEC.get(kind)
    if not spec:
        raise ValueError(f"unknown shelf kind: {kind}")
    base = _root(root)
    folder = base / spec["rel"]
    folder.mkdir(parents=True, exist_ok=True)
    items = []
    for p in sorted(folder.glob(f"*{spec['suffix']}"), key=lambda x: x.stat().st_mtime, reverse=True):
        if is_hidden_output(p.name):
            continue
        try:
            stat = p.stat()
            items.append({
                "name": p.name,
                "kind": kind,
                "size_kb": round(stat.st_size / 1024, 1),
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
                "download_url": spec["download_prefix"] + p.name,
                "preview_url": spec["preview_prefix"] + p.name,
                "has_md_source": p.with_suffix(".md").exists(),
                "open_path": str(spec["rel"] / p.name).replace("\\", "/"),
                "pages": deck_pages(p) if kind == "decks" else 0,
            })
        except OSError:
            continue
    items = fold_items(items, folder=folder, kind=kind, spec=spec)
    _attach_sessions(items, root=root)   # 折叠之后再补 · 当前行也能认出历史版本的场
    try:
        directory = str(folder.relative_to(base))
    except ValueError:
        directory = str(folder)
    return {
        "kind": kind,
        "count": len(items),
        "items": items,
        "directory": directory,
    }


# ── 产物库收全 (wish-1dc9c39d · BRO 2026-09-19) ─────────────────────────
# BRO 原话:「图1是收藏家的图2是产物库的收藏......这俩刻意区分开的吗?感觉好乱啊」
#          「有些时候工程类的你用的是出品工坊的产品开发,还有一些是产物库里面的原型」
# 病根: 产物库只认 4 类 · 而「能上中栏」的成品有 8 个目录 · 收藏夹又「有星就收」
#      → 三个圈不一样大 → 收了 6 条只找得到 2 条。
# 治法: 仓库收全。档案 = 我写的工程文档 · 工坊产物 = app 跑出来的成品。
_ARCHIVE_DIRS = ("data/dev", "data/docs", "data/content")   # 老调用方兼容用 (面板已切 4 个独立 domain)
_ARCHIVE_EXTS = (".md", ".html", ".htm", ".docx", ".pdf")
_WORKSHOP_DIR = "data/workshop/outputs"
_WORKSHOP_EXTS = (".html", ".htm", ".md", ".docx", ".pptx", ".xlsx", ".png", ".jpg", ".mp4")

# 扫描时**不进去**的目录名（2026-09-28 · wish-3586b504 · 剪枝）
#   app 的工作垃圾: 依赖 / 包缓存 / 构建缓存 / VCS / python 缓存。
#   产物扩展名白名单本就不含它们，进去纯属白翻 —— 实测占 outputs 下 19191 条目的 73%，
#   全量 rglob 723ms → 剪枝 walk 171ms (4.2×)。
#   这是「分区表」在代码里的执行者: 代码明确知道哪些目录不是产物区。
#   暂不含 dist/ build/ —— 那两处有可能被 app 当成品目录用，观察后再定。
_SHELF_PRUNE = frozenset({
    "node_modules", ".npmcache", ".cache", ".git", "__pycache__",
    ".venv", "venv", ".next", ".turbo", "site-packages",
})

# ── 预制应用四维 (wish-1dc9c39d · BRO 2026-09-19 二次定案) ────────────────
# BRO 原话:「把原型、开发、知识、内容，放到同一个一级标签...就叫预制应用，然后
#   把原型、开发、知识、内容，他们直接对应到内置应用的名字上吗，做成二级，
#   不然用户看了也容易混。结构也乱」
#
# 判据: 这 4 个目录 = draft_studio 的 4 个 domain · UI 上直接用内置应用的名字 (不用别名)。
#   每格「只放什么」写在行尾 —— 名字窄到不该进来的自己就不想来 (BRO 的落位原则)。
_PRESET_DOMAINS = {
    # key       目录              UI 名 (draft_studio 的 domain 名 · 单一叫法)
    "design":  ("data/design",  "产品设计"),   # 给人看「长什么样」的 (皮肤/界面/交互稿) · 不放施工方案
    "dev":     ("data/dev",     "产品开发"),   # 给工程看「怎么建」的 (铁律/方案/审计) · 不放设计稿
    "docs":    ("data/docs",    "文档撰写"),   # 沉淀下来的问答/手册 · 不放一次性的过程
    "content": ("data/content", "内容制作"),   # 对外发的推文/口播稿 · 不放工程文档
}
_PRESET_EXTS = {
    "design":  (".html", ".htm", ".md"),
    "dev":     (".md", ".html", ".htm", ".docx", ".pdf"),
    "docs":    (".md", ".html", ".htm", ".docx", ".pdf"),
    "content": (".md", ".html", ".htm", ".docx"),
}
# 每格一句话判据 —— 面板悬停 / 目录 README / 写入回报三个出口共用这一份 (不各写各的)
_PRESET_WHERE = {
    "design":  "此格只放「展示形态」—— 皮肤 / 界面 / 交互稿 / spec；施工方案与审计去 data/dev",
    "dev":     "此格只放「指导施工」—— 铁律 / 方案 / 架构 / 审计 / 判据；设计稿去 data/design",
    "docs":    "此格只放沉淀下来的问答 / 手册（长期可查的）；一次性的过程稿别放",
    "content": "此格只放对外发的内容 —— 推文 / 口播稿；工程文档去 data/dev",
}


def _app_labels() -> dict:
    """app_id -> 人话名字 · 二级分组要显示「白给日更」而不是 app-c5a54b7f。

    复用工坊现成注册表 (workers.workshop_assets.list_apps) · 不另造轮子。
    失败就退回 id 本身 —— 分组塌成 id 总比整个产物库崩了好。
    """
    try:
        from workers.workshop_assets import list_apps
        out = {}
        for a in list_apps(max_items=500):
            aid = a.get("id") or a.get("app_id") or ""
            if aid:
                out[aid] = (a.get("name") or "").strip() or aid
        return out
    except Exception:
        return {}


def _list_plain_dirs(kind: str, dirs, exts, *, root: Path | None = None) -> dict:
    """跨多个目录扫成品(递归·多后缀)·全库按 mtime 降序。

    不做 fold_items: 档案 / 工坊产物是各自独立的件 · 没有「同一题的历史版本」概念。
    """
    base = _root(root)
    items: list[dict] = []
    labels = _app_labels() if kind == "workshop" else {}
    for d in dirs:
        folder = base / d
        if not folder.exists():
            continue
        found: list[tuple[Path, object]] = []
        # 性能: 别按后缀逐个 rglob —— workshop 2858 个文件 × 9 后缀 = 4.25s。
        #   单次 rglob('*') + 内存过滤 = 0.63s (实测 6.7× · 2026-09-19)。
        # 2026-09-28 续·又砍两刀（BRO：打开产物库还是慢）：
        #   a) is_file() + stat() 两次系统调用 → 合并成一次 stat + S_ISREG
        #   b) has_md_source 原每个产物调一次 with_suffix('.md').exists() → 内存索引判断
        #   实测：这两刀只省下 88ms（1043→955）。
        # 2026-09-28 再续·剪枝（见下面 walk 那段）：**这才是大头**。
        #   当初判「大头是遍历目录项本身、没法再省」—— 那是在没剪枝的前提下看的。
        #   真相: 19191 个条目里 14099 个是某个 app 的 node_modules + .npmcache，压根不必进去。
        #   723ms → 171ms (4.2×)。教训:「遍历成本是物理下限」只在「确实该遍历这些文件」时成立。
        exts_l = tuple(e.lower() for e in exts)
        name_index: set[str] = set()
        # 2026-09-28 · 剪枝 (wish-3586b504): 用 walk 代替 rglob —— 遇到 _SHELF_PRUNE
        #   里的目录直接不进去 (rglob 剪不了·只能全遍历完再筛)。
        #   行为等价: 目录名照样进 name_index; 文件照样过扩展名白名单 + S_ISREG。
        for dirpath, dirnames, filenames in os.walk(folder, topdown=True):
            dirnames[:] = [x for x in dirnames if x not in _SHELF_PRUNE]
            for dname in dirnames:
                name_index.add(dname.lower())
            for fname in filenames:
                name_index.add(fname.lower())
                if Path(fname).suffix.lower() not in exts_l:
                    continue
                p = Path(dirpath) / fname
                try:
                    st = p.stat()
                except OSError:
                    continue
                if not S_ISREG(st.st_mode):
                    continue
                found.append((p, st))
        for p, stat in found:
            if is_hidden_output(p.name):
                continue
            try:
                rel = p.relative_to(folder).as_posix()
            except ValueError:
                continue
            if ".." in rel.split("/"):
                continue
            open_path = f"{d}/{rel}"
            item = {
                "name": rel,
                "title": p.stem,
                "kind": kind,
                "size_kb": round(stat.st_size / 1024, 1),
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
                "download_url": "/stage/file/" + open_path,
                "preview_url": "/stage/file/" + open_path,
                "has_md_source": (p.stem + ".md").lower() in name_index,
                "open_path": open_path,
                "pages": 0,
            }
            if kind == "workshop":
                # 二级分组的数据源: 路径首段就是 app_id (data/workshop/outputs/<app_id>/...)
                parts = rel.split("/")
                aid = parts[0] if len(parts) >= 2 else ""
                item["app_id"] = aid
                item["app_label"] = labels.get(aid, aid) if aid else "(根目录)"
            items.append(item)
    # 全库时间降序 (BRO:「保证所有的库内文件都可以按照时间排序」)
    items.sort(key=lambda it: it.get("created_at") or "", reverse=True)
    _attach_sessions(items, root=root)
    return {"kind": kind, "count": len(items), "items": items, "directory": " · ".join(dirs)}


def _list_archives(*, root: Path | None = None) -> dict:
    """档案: dev/docs/content 三目录合一 (执行报告 · 定案 · 对外文档 · 口播稿)。"""
    return _list_plain_dirs("archives", _ARCHIVE_DIRS, _ARCHIVE_EXTS, root=root)


def _list_workshop(*, root: Path | None = None) -> dict:
    """工坊产物: app 跑出来的成品(车间出的活儿, 也该进仓库)。"""
    return _list_plain_dirs("workshop", (_WORKSHOP_DIR,), _WORKSHOP_EXTS, root=root)


# ── 目录签名索引 (2026-09-28 · wish-4adb14e5) ──────────────────────
# 产物库重扫要 1148ms（工坊 955 + 演示稿现算），而「变没变」只要 stat 一遍目录。
# 地基（沙盒实测）：新建 / 删除文件会改目录 mtime；覆盖同名文件不会。
#   · 新增子目录 → 父目录 mtime 变 → 触发重扫 → 顺手更新签名
#   · 覆盖同名（revise_office 那种）签名抓不到 → revise 完主动作废 + 最长 10 分钟兜底
_SHELF_INDEX_PATH = _ROOT / "data" / "runtime" / "shelf_index.json"

# 扫描口径版本（2026-09-28 · 改了「扫什么/怎么扫」就 +1）
#   索引只比对目录 mtime —— 它不知道代码换了。实测：改完剪枝后全量仍返回旧的 2959 条
#   （旧口径算的），因为目录确实一个都没变。把口径编号写进索引：代码一改、编号一变，
#   旧索引自动作废。**不用记得手动去删 json** —— 这是「根本不会发生」那一类修法。
_SHELF_SCAN_REV = 2  # 1: rglob 全量 · 2: os.walk + _SHELF_PRUNE 剪枝
# 兜底有效期：只用来堵「覆盖同名文件」那个签名抓不到的口子（实测：改内容不换名
# → 目录 mtime 不变）。主要靠两件事保准：① 增/删文件改目录 mtime ② revise_office
# 完事主动 invalidate。所以这个 TTL 可以放长 —— 放短了每到期一次就要重扫 2.2s。
_SHELF_INDEX_TTL = 3600.0


def _shelf_roots(root: Path | None = None) -> list:
    """产物库会看的那些根目录（去重）。"""
    base = _root(root)
    rels: set = {Path(spec["rel"]) for spec in _KIND_SPEC.values()}
    rels |= {Path(d) for d, _lbl in _PRESET_DOMAINS.values()}
    rels.add(Path(_WORKSHOP_DIR))
    rels |= {Path(d) for d in _ARCHIVE_DIRS}
    return sorted(base / r for r in rels)


def _iter_all_items(payload: dict):
    """把结果里所有分类的 items 都吐出来（含 presets 的四个子包）。"""
    kinds = (payload or {}).get("kinds") or {}
    for pack in kinds.values():
        if not isinstance(pack, dict):
            continue
        for it in pack.get("items") or []:
            yield it
        subs = pack.get("subs")
        if isinstance(subs, dict):
            for sp in subs.values():
                if isinstance(sp, dict):
                    for it in sp.get("items") or []:
                        yield it


def _dir_snapshot_from(payload: dict) -> dict:
    """从扫出来的结果反推「该盯哪些目录」= 含产物的目录 + 它们的父目录。

    为什么不 os.walk 全树：实测 data/workshop/outputs 下有 3631 个目录，逐个
    stat 在机械盘上要 ~250ms（页缓存一冷就现原形），把热扫从 40ms 拉到 305ms。
    而真正会变的只有两种：① 产物所在目录（新产物）② 它的父目录（新 app 冒出来）。
    反推出来 30 个上下，stat 一遍 ≈ 1ms。
    """
    base = _ROOT
    watch: set = set()
    for it in _iter_all_items(payload):
        op = (it or {}).get("open_path") or ""
        if not op:
            continue
        d = base / str(op)
        watch.add(d.parent)
        # 不往上加祖父目录：那会把 data/ 这种「运行时文件也在写」的热目录卷进来
        #   → 签名永远失效、回回重扫。实测撞过：data/ 的 mtime 7 秒内就变了。
        #   上层靠 _shelf_roots() 兜住 —— 新 app 冒出来会改 outputs/ 的 mtime，它在名单里。
    watch |= {Path(r) for r in _shelf_roots()}
    out: dict = {}
    for d in watch:
        try:
            if d.is_dir():
                out[str(d)] = d.stat().st_mtime_ns
        except OSError:
            pass
    return out


def _sig_valid(sig: dict) -> bool:
    """签名里的目录一个都没变？实测 26 个目录 ≈ 1ms。"""
    if not sig:
        return False
    for k, v in sig.items():
        try:
            if Path(k).stat().st_mtime_ns != v:
                return False
        except OSError:
            return False  # 目录被删 / 改名
    return True


def _shelf_index_hit() -> dict | None:
    """索引还能用就吐上次结果，否则 None（调用方去真扫）。"""
    try:
        d = json.loads(_SHELF_INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    if not isinstance(d.get("payload"), dict) or not isinstance(d.get("sig"), dict):
        return None
    if int(d.get("rev") or 0) != _SHELF_SCAN_REV:
        return None  # 扫描口径变过 → 旧结果作废（哪怕目录一个都没动）
    try:
        if (time.time() - float(d.get("saved_at") or 0)) > _SHELF_INDEX_TTL:
            return None
    except (TypeError, ValueError):
        return None
    if not _sig_valid(d["sig"]):
        return None
    return d["payload"]


def _save_shelf_index(sig: dict, payload: dict) -> None:
    try:
        _SHELF_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _SHELF_INDEX_PATH.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"saved_at": time.time(), "rev": _SHELF_SCAN_REV,
                        "sig": sig, "payload": payload}, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(_SHELF_INDEX_PATH)
    except Exception:
        pass  # 索引只是加速器 · 写不进去最坏就是下次重扫


def invalidate_shelf_index() -> None:
    """产物被就地改过（revise_office 那种覆盖同名）→ 目录签名抓不到，主动作废。"""
    try:
        _SHELF_INDEX_PATH.unlink(missing_ok=True)
    except Exception:
        pass


def _deferred_pack(kind: str, directory: str = "") -> dict:
    """没被这轮请求到的分类占位符 —— 只报名字，不扫盘（2026-09-28）。

    count=None 而不是 0 —— 前端据此显示「…」· 不能拿假的 0 骗人。
    面板切到那格时再带 ?kinds=<该格> 单独拉一次。
    """
    return {"kind": kind, "count": None, "items": [], "directory": directory, "deferred": True}


def list_shelf(*, root: Path | None = None, kinds: list | None = None) -> dict:
    """产物库总览。

    kinds=None → 老行为（全量扫 · 2026-09-28 实测首屏 2102ms / 2.3MB）。
    kinds=["reports"] → 只算点名的那几类 · 其余返回 deferred 占位符。

    为什么要这个参数：实测首屏真正要的 reports 只要 32ms / 12KB，
    而全量 2.1s 里有 2.0s 花在首屏根本不看的 workshop(2959 条) 和 decks 上。
    产物库面板改成「切到哪格才拉哪格」—— 数字晚一拍出现，比每次点开都转 2 秒强。
    """
    want = {str(k).strip() for k in kinds if str(k).strip()} if kinds else None

    # 2026-09-28 · 全量扫走目录签名索引（wish-4adb14e5）：
    #   重扫 1148ms，而「变没变」只要 stat 一遍目录（实测 26 个 ≈ 1ms）。
    if want is None and root is None:
        # 索引是「真工程 root」的加速器。调用方显式传了别的 root（测试 / 干跑）时必须跳过 ——
        # 否则拿回来的是**别处**的结果（2026-09-29 实测：传 tmp_path 仍返回工程库快照）。
        # 它不只是测试问题：任何按 root 干跑的调用方都会被静默骗。
        _hit = _shelf_index_hit()
        if _hit is not None:
            # 回收站件数不进索引（它跟产物目录的 mtime 无关）· 每次都现数（毫秒级）
            _hit["trash_count"] = count_shelf_trash()
            return _hit

    def _on(k: str) -> bool:
        return want is None or k in want

    reports = list_kind("reports", root=root) if _on("reports") else _deferred_pack("reports", "data/reports")
    decks = list_kind("decks", root=root) if _on("decks") else _deferred_pack("decks", "data/presentations")
    sheets = list_kind("sheets", root=root) if _on("sheets") else _deferred_pack("sheets", "data/spreadsheets")
    workshop = _list_workshop(root=root) if _on("workshop") else _deferred_pack("workshop", _WORKSHOP_DIR)

    # ── 预制应用: 一级 presets · 二级 4 个 domain (与 draft_studio 同名) ──
    presets: dict = {}
    for k, (d, label) in _PRESET_DOMAINS.items():
        if _on(k) or _on("presets"):
            presets[k] = _list_plain_dirs(k, (d,), _PRESET_EXTS[k], root=root)
            presets[k]["label"] = label
            presets[k]["where"] = _PRESET_WHERE[k]
        else:
            presets[k] = {**_deferred_pack(k, d), "label": label, "where": _PRESET_WHERE[k]}

    # 老调用方兼容: 面板已切新 key · 但 protos/archives 这两个名字还有别处在用
    protos_compat = dict(presets["design"])
    protos_compat["kind"] = "protos"
    legacy_items = [i for k in ("dev", "docs", "content") for i in presets[k]["items"]]
    archives_compat = {
        "kind": "archives",
        "count": len(legacy_items),
        "items": sorted(legacy_items, key=lambda it: it.get("created_at") or "", reverse=True),
        "directory": "data/dev · data/docs · data/content",
    }
    _out = {
        "domain": "reports",
        "label": "产物库",
        "count": reports["count"],
        "items": reports["items"],
        "directory": reports["directory"],
        "kinds": {
            "reports": reports, "decks": decks, "sheets": sheets,
            "presets": {
                "kind": "presets", "label": "预制应用",
                # deferred 时子包 count=None · 别拿 sum 硬算（会 TypeError · 也骗人）
                "count": (
                    None if any(p.get("count") is None for p in presets.values())
                    else sum(p["count"] for p in presets.values())
                ),
                "subs": presets,
            },
            "design": presets["design"], "dev": presets["dev"],
            "docs": presets["docs"], "content": presets["content"],
            "workshop": workshop,
            "protos": protos_compat, "archives": archives_compat,
        },
    }
    # 全量扫完了：存一份目录签名 + 结果，下次先花 1ms 问一句「变了吗」
    # 写侧同理：传了别的 root 时**不许覆盖工程索引**（否则一次测试 / 干跑就把真索引洗掉）
    _out["trash_count"] = count_shelf_trash(root=root)
    if want is None and root is None:
        _save_shelf_index(_dir_snapshot_from(_out), _out)
    return _out


def resolve_item(kind: str, filename: str, *, root: Path | None = None) -> Path:
    spec = _KIND_SPEC.get(kind)
    if not spec:
        raise ValueError(f"unknown shelf kind: {kind}")
    filename = _safe_name(filename, spec["suffix"])
    folder = (_root(root) / spec["rel"]).resolve()
    path = (folder / filename).resolve()
    try:
        path.relative_to(folder)
    except ValueError:
        raise ValueError("path escapes shelf directory")
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(filename)
    return path


def restore_item(kind: str, filename: str, *, root: Path | None = None) -> dict:
    spec = _KIND_SPEC.get(kind)
    if not spec:
        raise ValueError("unknown shelf kind")
    src = resolve_item(kind, filename, root=root)
    dest, ver = restore_current(src.parent, src, family_key(src.name), spec["suffix"])
    return {
        "ok": True,
        "name": dest.name,
        "kind": kind,
        "version": ver,
        "from": filename,
        "preview_url": spec["preview_prefix"] + dest.name,
        "open_path": open_rel(kind, dest.name),
    }


def open_rel(kind: str, filename: str) -> str:
    spec = _KIND_SPEC.get(kind)
    if not spec:
        raise ValueError(f"unknown shelf kind: {kind}")
    return str(spec["rel"] / filename).replace("\\", "/")


def preview_md(kind: str, filename: str, *, root: Path | None = None) -> dict:
    spec = _KIND_SPEC[kind]
    path = resolve_item(kind, filename, root=root)
    filename = path.name
    md_path = path.with_suffix(".md")
    meta: dict = {}
    md_body = ""
    has_md = md_path.exists()
    if has_md:
        raw = md_path.read_text(encoding="utf-8")
        md_body = raw
        if raw.startswith("---\n"):
            end = raw.find("\n---\n", 4)
            if end > 0:
                fm = raw[4:end]
                md_body = raw[end + 5:].lstrip("\n")
                for line in fm.splitlines():
                    if ":" in line:
                        k, _, v = line.partition(":")
                        meta[k.strip()] = v.strip()
    size_kb = 0.0
    try:
        size_kb = round(path.stat().st_size / 1024, 1)
    except OSError:
        pass
    return {
        "ok": True,
        "name": filename,
        "kind": kind,
        "size_kb": size_kb,
        "pages": deck_pages(path) if kind == "decks" else 0,
        "has_md_source": has_md,
        "source": "md" if has_md else "none",
        "markdown": md_body,
        "meta": meta,
        "download_url": spec["download_prefix"] + filename,
        "open_path": open_rel(kind, filename),
        "note": "" if has_md else {
            "sheets": "这份表格没有 markdown 源 · 成品预览仍可看表。",
            "decks": "这份演示稿没有 markdown 源 · 请下载用本机软件打开。",
            "protos": "HTML 本身就是源 · 中栏预览，跟我说改哪里。",
        }.get(kind, "这份报告没有 markdown 源。"),
    }



# ─── wish-0c9fdbf4 · 产物库删除 + 回收站 ─────────────────────────────
#
# BRO 2026-09-30: 538 份产物只能看不能删。删掉的先进回收站（不是直接消），
# 回收站 30 天自动清理 · 并给一个按钮能当场清空。
#
# 「根本不会发生」：删除只认 _shelf_roots() 底下的路径 —— 前端就算传
# ../soul/IDENTITY.md 也过不了白名单（resolve 后比 · 挡 ../ 穿越）。

SHELF_TRASH_REL = "data/runtime/shelf_trash"
SHELF_TRASH_KEEP_DAYS = 30


def _hs(n) -> str:
    n = int(n or 0)
    for unit, div in (("GB", 1073741824), ("MB", 1048576), ("KB", 1024)):
        if n >= div:
            return f"{n / div:.1f} {unit}"
    return f"{n} B"


def _shelf_trash_dir(root: Path | None = None) -> Path:
    return _root(root) / SHELF_TRASH_REL


def _batch_time(p: Path, fallback: float = 0.0) -> float:
    """批次目录名就是时间戳 (20260930-230428) · 比目录 mtime 准。"""
    try:
        return time.mktime(time.strptime(p.name, "%Y%m%d-%H%M%S"))
    except Exception:
        return fallback


def _under_shelf_roots(p: Path, roots: list) -> bool:
    try:
        rp = p.resolve()
    except OSError:
        return False
    for ar in roots:
        try:
            rp.relative_to(ar.resolve())
            return True
        except (ValueError, OSError):
            continue
    return False


def _sidecar_paths(p: Path) -> list:
    """同名侧车（.md 文稿源 / .json 元数据）· 删主件时一起走 · 别留孤儿。"""
    out = []
    for suf in (".md", ".json"):
        try:
            s = p.with_suffix(suf)
        except ValueError:
            continue
        if s.exists() and s.is_file():
            out.append(s)
    return out


def delete_shelf_items(items: list, *, root: Path | None = None) -> dict:
    """把产物搬进回收站（可还原 · 不是直接消）。

    items: [{"path": "data/reports/x.docx", ...}, ...]
    只认文件 —— 目录不走这条路（影响面太大）。
    """
    base = _root(root)
    roots = _shelf_roots(root=base)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    tdir = _shelf_trash_dir(root=base) / stamp
    moved, freed, errors, done, seen = 0, 0, [], [], set()
    for it in items or []:
        rel = str((it or {}).get("path") or "").strip().replace("\\", "/")
        if not rel or rel in seen:
            continue
        seen.add(rel)
        p = base / rel
        if not _under_shelf_roots(p, roots):
            errors.append(f"{rel}: 不在产物目录里")
            continue
        if not p.exists() or not p.is_file():
            errors.append(f"{rel}: 不存在或不是文件")
            continue
        try:
            n = p.stat().st_size
            dst = tdir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(dst))
            for side in _sidecar_paths(p):
                srel = str(side.relative_to(base)).replace("\\", "/")
                sdst = tdir / srel
                sdst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(side), str(sdst))
        except OSError as e:
            errors.append(f"{rel}: {e}")
            continue
        moved += 1
        freed += n
        done.append(rel)
    if moved:
        try:
            invalidate_shelf_index()
        except Exception:
            pass
    return {"ok": True, "moved": moved, "freed": freed, "freed_size": _hs(freed),
            "batch": (stamp if moved else ""), "items": done, "errors": errors[:8]}


def prune_shelf_trash(*, root: Path | None = None, days: int = SHELF_TRASH_KEEP_DAYS) -> dict:
    """清掉回收站里超过 N 天的批次。零 LLM · 毫秒级 · 列清单时顺手跑。"""
    base = _shelf_trash_dir(root=root)
    if not base.exists():
        return {"removed": 0, "freed": 0, "freed_size": "0 B"}
    cut = time.time() - max(1, int(days)) * 86400
    removed, freed = 0, 0
    for batch in list(base.iterdir()):
        try:
            if not batch.is_dir():
                continue
            if _batch_time(batch, batch.stat().st_mtime) > cut:
                continue
            for f in batch.rglob("*"):
                if f.is_file():
                    freed += f.stat().st_size
            shutil.rmtree(batch, ignore_errors=True)
            removed += 1
        except OSError:
            continue
    return {"removed": removed, "freed": freed, "freed_size": _hs(freed)}


def count_shelf_trash(*, root: Path | None = None) -> int:
    """回收站里有多少件（只数·不建详情）—— 给产物库 tab 上的数字用。"""
    tdir = _shelf_trash_dir(root=root)
    if not tdir.exists():
        return 0
    n = 0
    try:
        for f in tdir.rglob("*"):
            if f.is_file():
                n += 1
    except OSError:
        pass
    return n


def list_shelf_trash(*, root: Path | None = None) -> dict:
    """回收站清单（顺手清过期的）。一批 = 一次删除动作。"""
    base = _root(root)
    pruned = prune_shelf_trash(root=base)
    tdir = _shelf_trash_dir(root=base)
    batches, total = [], 0
    if tdir.exists():
        for b in sorted(tdir.iterdir(), key=lambda x: x.name, reverse=True):
            if not b.is_dir():
                continue
            files = []
            for f in sorted(b.rglob("*")):
                if not f.is_file():
                    continue
                try:
                    st = f.stat()
                except OSError:
                    continue
                files.append({"name": f.name, "rel": str(f.relative_to(b)).replace("\\", "/"),
                              "size": _hs(st.st_size), "bytes": st.st_size})
            if not files:
                continue
            nbytes = sum(x["bytes"] for x in files)
            total += nbytes
            t = _batch_time(b, b.stat().st_mtime)
            batches.append({
                "batch": b.name,
                "when": time.strftime("%Y-%m-%d %H:%M", time.localtime(t)),
                "age_days": int(max(0, time.time() - t) / 86400),
                "left_days": int(max(0, SHELF_TRASH_KEEP_DAYS - (time.time() - t) / 86400)),
                "count": len(files), "size": _hs(nbytes), "bytes": nbytes, "files": files,
            })
    return {"ok": True, "batches": batches, "count": sum(x["count"] for x in batches),
            "size": _hs(total), "bytes": total, "keep_days": SHELF_TRASH_KEEP_DAYS,
            "pruned": pruned}


def restore_shelf_trash(paths: list, *, root: Path | None = None) -> dict:
    """把回收站里的东西挪回原位。paths 是 batch/相对路径。"""
    base = _root(root)
    tdir = _shelf_trash_dir(root=base)
    moved, errors = 0, []
    for raw in paths or []:
        rel = str(raw or "").strip().replace("\\", "/")
        parts = rel.split("/")
        if len(parts) < 2 or ".." in parts:
            errors.append(f"{rel}: 不认的相对路径")
            continue
        src = tdir / rel
        try:
            src.resolve().relative_to(tdir.resolve())
        except (ValueError, OSError):
            errors.append(f"{rel}: 越界")
            continue
        if not src.is_file():
            errors.append(f"{rel}: 不在了")
            continue
        dst = base / "/".join(parts[1:])
        if not _under_shelf_roots(dst, _shelf_roots(root=base)):
            errors.append(f"{rel}: 原位不在产物目录里")
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                dst = dst.with_name(dst.stem + "-还原" + dst.suffix)
            shutil.move(str(src), str(dst))
        except OSError as e:
            errors.append(f"{rel}: {e}")
            continue
        moved += 1
    if moved:
        try:
            invalidate_shelf_index()
        except Exception:
            pass
        try:
            for b in list(tdir.iterdir()):
                if b.is_dir() and not any(b.rglob("*")):
                    b.rmdir()
        except OSError:
            pass
    return {"ok": True, "moved": moved, "errors": errors[:8]}


def empty_shelf_trash(*, root: Path | None = None) -> dict:
    """一键清空回收站 · 永久删 · 找不回。"""
    tdir = _shelf_trash_dir(root=root)
    if not tdir.exists():
        return {"ok": True, "removed": 0, "freed": 0, "freed_size": "0 B"}
    n, freed = 0, 0
    for f in tdir.rglob("*"):
        try:
            if f.is_file():
                freed += f.stat().st_size
        except OSError:
            pass
    for b in list(tdir.iterdir()):
        try:
            if b.is_dir():
                shutil.rmtree(b, ignore_errors=True)
            else:
                b.unlink()
            n += 1
        except OSError:
            continue
    return {"ok": True, "removed": n, "freed": freed, "freed_size": _hs(freed)}
