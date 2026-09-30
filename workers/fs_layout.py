"""data/ 分区登记 · 建目录的唯一入口 + 未登记自检

BRO 2026-09-28 原话:
    「不是不让新建，如果新建，就必须要让后面的人知道什么东西放在哪里。
      就好比书架不够用了，要买新的，新的书架也要有标签。」

所以这里不是白名单硬拦 —— 是「建格子必须当场贴标签」:

    ensure_dir(path, purpose="装什么 · 谁写 · 丢了会怎样")
        ↑ 建目录 = 顺手写下用途。purpose 不填 → 直接报错，目录建不出来。

    scan_unregistered()
        ↑ 启动时自查: 基线之后有没有冒出来没贴标签的格子。

标签分散两处（人看一份、机器记一份）:
    · 给人看 —— data/cognition/LAYOUT.md（八个区 · 精选分区表 · 待归位清单）
    · 给机器 —— KNOWN_AREAS（在母体清单 fs_layout_mother.py 里）+ data/runtime/dir_registry.jsonl（建目录流水）

设计取舍（为什么不硬拦）:
    硬白名单会让「合法的新书架」寸步难行；这里要的是**建之前先想清用途**这个动作本身。
    报出来的东西 BRO 看得见 —— 这就够了。

发布边界（2026-09-28 · BRO 拍「拆两半」）:
    BRO 原话:「我希望母体的个人数据都不要给到纯净版，但是这些核心功能是要给的。」
    · **核心功能**（本文件）→ 进 core_manifest 白名单 · 给纯净版:
        ensure_dir 闸门（用途不填就报错）+ 基线自检（首跑自动建基线，只报之后的新增）
    · **母体个人数据**（目录清单）→ workers/fs_layout_mother.py · 进 port_map 的 mother_only
        纯净版没这份 → KNOWN_AREAS 退化成空 → 自检只靠基线，不报母体存量、不泄母体结构
    调用方（daemon_api.py 的 startup 钩子）保留 `except ImportError` 软降级 —— 模块不在就安静跳过。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = ROOT / "data"
REGISTRY_PATH = DATA_ROOT / "runtime" / "dir_registry.jsonl"
BASELINE_PATH = DATA_ROOT / "runtime" / "data_root_baseline.json"

# ── 已登记的一级区 —— 在母体清单里（2026-09-28 拆分 · BRO 拍）────────────────
#   BRO:「我希望母体的个人数据都不要给到纯净版，但是这些核心功能是要给的。」
#   核心功能（本文件）进白名单给纯净版；母体目录清单进 mother_only 不下发。
#   纯净版没这份 → KNOWN_AREAS 退化成空 → 自检只靠基线（首跑自动建），
#   既不报母体的存量，也不把母体的目录结构泄给用户。
#   ⚠ 别把清单抄回本文件 —— 那等于又把个人数据塞进要下发的文件里。
def _mother_areas() -> dict[str, str]:
    """读母体目录清单 —— **延迟 import**。

    为什么不在模块级 import: 模块级 import 会被发布闸判 HARD（白名单内文件硬依赖
    白名单外的模块）；函数体内 import 算 SOFT，母体清单又已在 port_map.mother_only 里 ——
    三重口径（白名单 / mother_only / 闸）才对得上。

    纯净版没这份 → 返回空 dict → 自检只靠基线（首跑自动建），
    既不报母体存量、也不把母体目录结构泄给用户。
    """
    try:
        from workers.fs_layout_mother import KNOWN_AREAS
        return KNOWN_AREAS
    except ImportError:  # 纯净版：本机没有母体清单
        return {}

# 废止的前缀 —— 再建就是走回头路。替代: data/runtime/scratch/
RETIRED_PREFIXES = ("_tmp_",)

# 运行时伴生文件 —— 跟着主文件走，**不算新格子**。
#   SQLite 的 -shm/-wal/-journal 一打开数据库就自动生成（基线是库关着时建的 → 不豁免的话
#   每次重启都误报「新增文件」。2026-09-28 首次接入自检时当场暴露的）。
COMPANION_SUFFIXES = ("-shm", "-wal", "-journal", ".lock", ".tmp", ".bak")


def _is_companion(name: str) -> bool:
    """运行时伴生文件（不是新格子）—— 后缀匹配即可，简单且够用。"""
    return name.endswith(COMPANION_SUFFIXES)

# 母体目录清单（KNOWN_AREAS）在 fs_layout_mother.py —— 由 _mother_areas() 延迟 import。
# 它描述的是母体自己的目录历史，不下发。


def ensure_dir(path, *, purpose: str, writer: str = "") -> Path:
    """建目录的唯一入口。

    purpose 必填 —— 写清「装什么 / 谁写 / 丢了会怎样」。
    不填（或太短）直接抛错，目录建不出来: 这就是「当场贴标签」的强制执行点。

    Args:
        path:    目标目录（相对工程根或绝对）
        purpose: 用途说明 · 至少 6 字
        writer:  谁建的（模块名 / 工具名）

    Returns:
        建好的 Path
    """
    text = (purpose or "").strip()
    if len(text) < 6:
        _tip = ("分区规则见 data/cognition/LAYOUT.md。" if _mother_areas()
                else "分区规则见你的分区登记表（若还没有，现在就是立它的时机）。")
        raise ValueError(
            "ensure_dir 拒绝建目录: purpose 必须写清「装什么 / 谁写 / 丢了会怎样」"
            "（至少 6 字）。" + _tip
        )

    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    p.mkdir(parents=True, exist_ok=True)

    # 建目录流水（append · 一行一条 · 失败不挡干活）
    try:
        REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "path": str(p.relative_to(ROOT)).replace("\\", "/") if p.is_relative_to(ROOT) else str(p),
            "purpose": text,
            "writer": writer or "unknown",
        }
        with REGISTRY_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass

    return p


def _read_baseline() -> dict:
    try:
        return json.loads(BASELINE_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _adopt(data_root: Path) -> dict:
    """第一次跑: 把**现状**收成基线（存量归位走另一条线 · LAYOUT.md 第五节）。

    这样自检的职责保持单一 —— **只报新增的**，不天天拿存量刷屏。
    """
    base = {
        "adopted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "note": "data/ 根一级的现状快照。此后的新增会被 scan_unregistered 报出来。",
        # 废止前缀（_tmp_*）与运行时伴生文件（*.db-shm 等）**不进基线** —— 前者是待归位清单、
        # 每次启动都该被提一句；后者会随数据库开关变化，记进基线反而错。
        "dirs": sorted(p.name for p in data_root.iterdir() if p.is_dir() and not p.name.startswith(RETIRED_PREFIXES)),
        "files": sorted(
            p.name for p in data_root.iterdir()
            if p.is_file() and not p.name.startswith(RETIRED_PREFIXES) and not _is_companion(p.name)
        ),
    }
    try:
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(json.dumps(base, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass
    return base


def scan_unregistered(*, data_root: Path | None = None, adopt_first_run: bool = True) -> dict:
    """扫 data/ 一级，报告**基线之后新出现**的目录 / 文件。

    Returns:
        {
          "first_run": bool,          # 是否本次刚建立基线（本次没有可比对象）
          "new_dirs": [名字...],      # 新增的一级目录（未登记 / 废止前缀）
          "new_files": [名字...],     # 新增的一级文件（根上不该有文件）
          "unregistered": [名字...],  # 不受基线保护、当前就未登记的目录
        }
    """
    dr = Path(data_root) if data_root else DATA_ROOT
    if not dr.is_dir():
        return {"first_run": False, "new_dirs": [], "new_files": [], "unregistered": []}

    base = _read_baseline()
    first_run = False
    if not base and adopt_first_run:
        base = _adopt(dr)
        first_run = True

    base_dirs = set(base.get("dirs") or [])
    base_files = set(base.get("files") or [])

    all_dirs = sorted(p.name for p in dr.iterdir() if p.is_dir())
    all_files = sorted(p.name for p in dr.iterdir() if p.is_file())

    # 新增 = 基线之后冒出来的，且不是废止前缀（废止的由 unregistered 单独报，叫「待归位」）
    new_dirs = [
        n for n in all_dirs
        if n not in base_dirs and not n.startswith(RETIRED_PREFIXES)
    ]
    new_files = [
        n for n in all_files
        if n not in base_files and not n.startswith(RETIRED_PREFIXES) and not _is_companion(n)
    ]

    # 当前就不该在的（废止前缀 / 没登记过的）—— 与基线无关，存量也报
    _areas = _mother_areas()   # 取一次就够（别在推导式里反复 import）
    unregistered = [
        n for n in all_dirs
        if n.startswith(RETIRED_PREFIXES) or (n not in _areas and n not in base_dirs)
    ]

    return {
        "first_run": first_run,
        "new_dirs": new_dirs,
        "new_files": new_files,
        "unregistered": unregistered,
    }


def render_notice(scan: dict) -> str:
    """把 scan 结果压成一行日志（没有异常就返回空串）。"""
    if scan.get("first_run"):
        return ""  # 首跑只建基线，不刷屏
    bits = []
    if scan.get("new_dirs"):
        bits.append("新增目录 " + ", ".join(scan["new_dirs"][:6]))
    if scan.get("new_files"):
        bits.append("根上新增文件 " + ", ".join(scan["new_files"][:6]))
    if scan.get("unregistered"):
        bits.append("待归位 " + ", ".join(scan["unregistered"][:6]))
    if not bits:
        return ""
    # 提示语分两版: 母体有 LAYOUT.md，纯净版没有 —— 别下发一个指向不存在文件的指引
    _tip = ("按 data/cognition/LAYOUT.md 归位并按用途登记" if _mother_areas()
            else "按你自己的分区规则归位")
    return (
        "[fs_layout] data/ 出现未登记的格子 · " + " · ".join(bits)
        + f" —— {_tip}（建目录请走 ensure_dir）。"
    )
