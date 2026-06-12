"""
workers/wishlist.py
===================

OPUS 自我演化心愿单 · 卷三十五

为什么这个文件存在：
  - opportunity 是"BRO 能干啥赚钱"·主语是 BRO
  - wish 是"OPUS 自己想装啥能力"·主语是 OPUS
  - 这是 product → self-evolution 的根本区别

工作流：
  1. OPUS 在 self-evolve domain 看到同类工程的好东西 → wish_add 写进 心愿单
  2. BRO 在 WebUI 心愿单维度看到 → 批准 / 驳回 / 推给 DAEMON / 推给 Cursor
  3. 实现路径：
     - daemon 路径：本工程自己改自己代码 (高风险 · 卷三十六做)
     - cursor 路径：BRO 在 Cursor 里手动让 Claude 改 (当下用)
  4. 完成后 mark done + BRO 写 reflection notes

数据存放：
  - data/opus_wishlist.json
  - 一个 dict {"version": 1, "wishes": [...]}
  - 每条 wish 见下面 WishSchema 注释

为什么不放数据库：
  - 跟 sessions/ 一样的哲学·jsonl/json 文件能 grep 能 vim
  - wish 数量短期就几十条 · 不需要 index 加速
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
WISHLIST_PATH = DATA_DIR / "opus_wishlist.json"

# Wish schema (一条 wish 长什么样)：
#   id: "wish-xxxxxx"              · slug · uuid 短缩
#   title: str                     · 一句话·想装啥
#   why: str                       · 为什么想装·关联到啥 (引用 opportunity / learning / radar item)
#   source: {                      · 来源溯源·点回去能跳到原文
#     kind: "comparison" | "opportunity" | "radar" | "trend" | "manual",
#     ref: str (可读名字),
#     url: str | null,
#   }
#   design_sketch: str             · 拟改造方案 · markdown
#   complexity: "low" | "medium" | "high"
#   estimated_hours: float
#   estimated_token_cost_usd: float
#   priority: 1-5 (5=最想要 · OPUS 自己打)
#   status: "drafted" | "approved" | "rejected" | "in_progress" | "done" | "ready_for_merge" | "live"
#   integration_path: "daemon" | "cursor" | "undecided"
#   created_at: ISO timestamp
#   approved_at / rejected_at / started_at / completed_at / merged_at / live_at: ISO timestamp | null
#   reflection: str | null         · 完成后 BRO 或 OPUS 自己写的感受
#
# 卷三十五补丁4 新增字段 · DAEMON 路径真接通 (BRO 决定走档 B):
#   daemon_phase: null | "planning" | "planned" | "implementing" | "done" | "failed"
#     - null         · 未走 daemon 路径
#     - planning     · OPUS 在勘察 (读代码 / web_search) · 还没出方案
#     - planned      · 已出方案 · 等 BRO review 决定是否开干
#     - implementing · OPUS 真改代码中
#     - done         · 改完 · 等 BRO 看 diff approve
#     - failed       · 中途撞墙 · OPUS 主动放弃
#   implementation_plan: str | null     · 勘察输出 · markdown · 给 BRO review
#   implementation_log: str | null      · 实施日志 · markdown · 记录每一步动作 + 结果
#   dev_branch: str | null              · OPUS 改代码用的 git 分支名 · 隔离主分支
#   diff_summary: str | null            · 改完之后的 git diff 摘要 · UI 上一眼能看

_VALID_KINDS = {"comparison", "opportunity", "radar", "trend", "manual"}
_VALID_COMPLEXITY = {"low", "medium", "high"}

# 卷五十三 · 状态机大精简 (BRO: "复杂冗长·一并优化掉")
# 从 7 status × 6 daemon_phase 砍到 4+1 主状态 + 2 个子标记:
#   pending  · 等 BRO 拍板 (批 / 弃)          [关卡: 批不批做]
#   active   · 归 OPUS 推进 (勘察 / 写码 / 自测) · 球在 OPUS 半场
#   review   · OPUS 完工·代码在分支上·等 BRO 测+合  [关卡: 验 diff]
#   live     · 已合入 master 主干 (只能经 merge 函数进入·不许直接置)
#   rejected · 弃
_VALID_STATUS = {"pending", "active", "review", "live", "rejected"}
_VALID_PATHS = {"daemon", "cursor", "undecided"}

# 子标记 (只在 status==active 时有意义·UI 上挂小 chip·不占顶层格子):
#   plan_pending · (仅 daemon 路径) OPUS 出完方案·停下等 BRO 批方案  [关卡: 批方案]
#   blocked      · OPUS 撞墙·等 BRO 看
_VALID_DAEMON_PHASES = {None, "plan_pending", "blocked"}

# 归一化垫片 · 老状态/老 phase 值自动映射到新值 (防遗漏的老调用崩 · 卷五十三)
_STATUS_ALIAS = {
    "drafted": "pending",
    "approved": "active",
    "in_progress": "active",
    "done": "review",
    "ready_for_merge": "live",
    # 新值原样保留
    "pending": "pending", "active": "active", "review": "review",
    "live": "live", "rejected": "rejected",
}
_PHASE_ALIAS = {
    "planning": None,       # 勘察中 = 正常 active · 无需 chip
    "planned": "plan_pending",
    "implementing": None,   # 写码中 = 正常 active
    "done": None,           # 改完 → 由 status 升 review 表达
    "failed": "blocked",
    "plan_pending": "plan_pending", "blocked": "blocked", None: None,
}


def _normalize_status(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    return _STATUS_ALIAS.get(s, s)


def _normalize_phase(p: Optional[str]) -> Optional[str]:
    return _PHASE_ALIAS.get(p, None)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _atomic_write(path: Path, data: dict) -> None:
    """卷四十六 III 补丁 5 · R5 · 迁移到 workers.safe_write · 加自动 timestamp 备份

    OPUS / BRO 写坏 wishlist (LLM hallucinate / 手工编辑括号错位) 时 ·
    data/_backups/data_opus_wishlist.json_<ts>.bak 保留前 10 份历史 ·
    restore_backup() 可一键恢复。
    """
    from workers.safe_write import atomic_write_json
    atomic_write_json(path, data)


def load_wishlist() -> dict:
    """读 wishlist · 不存在返默认结构"""
    if not WISHLIST_PATH.exists():
        return {"version": 1, "wishes": []}
    try:
        d = json.loads(WISHLIST_PATH.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            return {"version": 1, "wishes": []}
        d.setdefault("version", 1)
        d.setdefault("wishes", [])
        return d
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "wishes": []}


def save_wishlist(data: dict) -> None:
    # 卷五十四 · B3 结构闸: 坏结构 (wishes 非 list / 缺 id / status 非法 / id 重复) 拒写 ·
    # 不让坏的落地 (病根: 落盘后下次 load 崩或 wish 列表 UI 错乱)。 raise SchemaError 让调用方/OPUS 看见。
    from workers.schema_guard import validate_wishlist
    validate_wishlist(data)
    _atomic_write(WISHLIST_PATH, data)


def _new_wish_id() -> str:
    return "wish-" + uuid.uuid4().hex[:8]


def add_wish(
    *,
    title: str,
    why: str,
    source_kind: str = "manual",
    source_ref: str = "",
    source_url: Optional[str] = None,
    design_sketch: str = "",
    complexity: str = "medium",
    estimated_hours: float = 4.0,
    estimated_token_cost_usd: float = 1.0,
    priority: int = 3,
    origin: str = 'bro',
) -> dict:
    """OPUS 写一份心愿 · 状态默认 drafted

    返回新加的 wish dict (含 id)
    """
    title = (title or "").strip()
    if not title:
        raise ValueError("title 必填")

    if source_kind not in _VALID_KINDS:
        raise ValueError(f"source_kind 必须是 {_VALID_KINDS}")
    if complexity not in _VALID_COMPLEXITY:
        raise ValueError(f"complexity 必须是 {_VALID_COMPLEXITY}")
    priority = max(1, min(5, int(priority)))

    wish = {
        "id": _new_wish_id(),
        "title": title,
        "why": (why or "").strip(),
        "source": {
            "kind": source_kind,
            "ref": (source_ref or "").strip(),
            "url": (source_url or None),
        },
        "design_sketch": (design_sketch or "").strip(),
        "complexity": complexity,
        "estimated_hours": float(estimated_hours),
        "estimated_token_cost_usd": float(estimated_token_cost_usd),
        "priority": priority,
        "status": "pending",
        "integration_path": "undecided",
        "created_at": _now_iso(),
        "approved_at": None,
        "rejected_at": None,
        "started_at": None,
        "completed_at": None,
        "reflection": None,
        # 卷三十五补丁4 · daemon 路径字段
        "daemon_phase": None,
        "implementation_plan": None,
        "implementation_log": None,
        "dev_branch": None,
        "diff_summary": None,
        # wish-d31fb4d2 · OPUS 主动发现标记
        "origin": origin,
    }
    data = load_wishlist()
    data["wishes"].append(wish)
    save_wishlist(data)
    return wish


def get_wish(wish_id: str) -> Optional[dict]:
    data = load_wishlist()
    for w in data.get("wishes", []):
        if w.get("id") == wish_id:
            return w
    return None


def update_wish(wish_id: str, **patch) -> Optional[dict]:
    """更新一条 wish · 支持 status / integration_path / priority / reflection / 等"""
    data = load_wishlist()
    target = None
    for w in data.get("wishes", []):
        if w.get("id") == wish_id:
            target = w
            break
    if target is None:
        return None

    now = _now_iso()

    if "status" in patch:
        s = _normalize_status(patch["status"])  # 老值自动归一 (卷五十三)
        if s not in _VALID_STATUS:
            raise ValueError(f"status 必须是 {_VALID_STATUS} (或老值会自动归一)")
        target["status"] = s
        # 自动打时间戳 (新四态)
        if s == "active" and not target.get("started_at"):
            target["started_at"] = now
        elif s == "review" and not target.get("completed_at"):
            target["completed_at"] = now
        elif s == "rejected" and not target.get("rejected_at"):
            target["rejected_at"] = now
        elif s == "live":
            # 卷五十四 · B2 上线闸: 有独立 dev_branch 却没合入 master · 不许标 live。
            # 今早病根正是"标签写 live · git 里却没合" → 回退后活儿丢。 git 是真相·status 是意图。
            # 逃生门: patch 里带 _allow_unmerged_live=True (git 误判 cherry-pick 等价时人工放行)。
            if not patch.get("_allow_unmerged_live"):
                db = (target.get("dev_branch") or "").strip()
                if db and " " not in db and db != "master":
                    try:
                        from workers.git_ops import audit_wishes_merge_state
                        st = (audit_wishes_merge_state([target]).get(wish_id) or {}).get("state")
                    except Exception:
                        st = None
                    if st == "unmerged":
                        raise ValueError(
                            f"wish {wish_id} 的分支 `{db}` 还没合入 master (git 真相: unmerged) · "
                            f"不许标 live。 先用 merge_wish_to_master 把它合进主干再标 live · "
                            f"这道闸防的正是'标签写 live·git 里没合'导致回退后活儿丢。 "
                            f"(git 误判 cherry-pick 等价时: 传 _allow_unmerged_live=True 放行)")
            target.setdefault("merged_at", now)
            if not target.get("live_at"):
                target["live_at"] = now

    if "integration_path" in patch:
        p = patch["integration_path"]
        if p not in _VALID_PATHS:
            raise ValueError(f"integration_path 必须是 {_VALID_PATHS}")
        target["integration_path"] = p

    if "priority" in patch:
        target["priority"] = max(1, min(5, int(patch["priority"])))

    if "reflection" in patch:
        target["reflection"] = (patch.get("reflection") or "").strip() or None

    if "title" in patch and patch["title"]:
        target["title"] = patch["title"].strip()

    if "why" in patch and patch["why"] is not None:
        target["why"] = patch["why"].strip()

    if "design_sketch" in patch and patch["design_sketch"] is not None:
        target["design_sketch"] = patch["design_sketch"].strip()

    # 子标记 (卷五十三精简 · 老 phase 值自动归一)
    if "daemon_phase" in patch:
        ph = _normalize_phase(patch["daemon_phase"])
        if ph not in _VALID_DAEMON_PHASES:
            raise ValueError(f"daemon_phase 必须是 {_VALID_DAEMON_PHASES} (或老值会自动归一)")
        target["daemon_phase"] = ph

    if "implementation_plan" in patch and patch["implementation_plan"] is not None:
        target["implementation_plan"] = patch["implementation_plan"].strip() or None

    if "implementation_log" in patch and patch["implementation_log"] is not None:
        target["implementation_log"] = patch["implementation_log"].strip() or None

    if "dev_branch" in patch and patch["dev_branch"] is not None:
        target["dev_branch"] = (patch["dev_branch"] or "").strip() or None

    if "diff_summary" in patch and patch["diff_summary"] is not None:
        target["diff_summary"] = patch["diff_summary"].strip() or None

    save_wishlist(data)
    return target


def delete_wish(wish_id: str) -> bool:
    """硬删一条 wish · 一般用不到 · 走 status=rejected 即可"""
    data = load_wishlist()
    before = len(data.get("wishes", []))
    data["wishes"] = [w for w in data.get("wishes", []) if w.get("id") != wish_id]
    if len(data["wishes"]) != before:
        save_wishlist(data)
        return True
    return False


def list_wishes(
    *,
    status_filter: Optional[str] = None,
    sort_by: str = "auto",
) -> list[dict]:
    """列 wish · 默认 'auto' 智能排序:

    sort_by:
      'auto' (默认)      · 智能选择: live/rejected 按最近活动排, 其余按 priority desc
      'priority'          · priority desc → created_at desc
      'created_at'        · 创建时间 desc
      'updated'           · 最近活动 desc (completed_at → started_at → created_at)
      'status'            · 待 BRO 动手的排前面
    """
    data = load_wishlist()
    wishes = list(data.get("wishes", []))
    if status_filter:
        wishes = [w for w in wishes if w.get("status") == status_filter]

    # 'auto' 智能选择
    resolved_sort = sort_by
    if sort_by == "auto":
        if status_filter in ("live", "rejected"):
            resolved_sort = "updated"
        else:
            resolved_sort = "priority"

    if resolved_sort == "priority":
        wishes.sort(key=lambda w: (w.get("priority") or 0, w.get("created_at") or ""), reverse=True)
    elif resolved_sort == "created_at":
        wishes.sort(key=lambda w: w.get("created_at") or "", reverse=True)
    elif resolved_sort == "updated":
        # 最近活动 = completed_at > started_at > created_at · 哪个有值且最新就用哪个
        def _last_active(w: dict) -> str:
            return (w.get("completed_at") or w.get("started_at") or w.get("created_at") or "")
        wishes.sort(key=_last_active, reverse=True)
    elif resolved_sort == "status":
        # 待 BRO 动手的排前面 (review → active → pending → live → rejected)
        order = {"review": 0, "active": 1, "pending": 2, "live": 3, "rejected": 4}
        wishes.sort(key=lambda w: order.get(_normalize_status(w.get("status")), 99))
    return wishes


def wishlist_summary() -> dict:
    """快速看一眼现状 · 给 cockpit / BI 用 (卷五十三 · 新四态)"""
    wishes = list_wishes()
    by_status: dict[str, int] = {}
    for w in wishes:
        s = _normalize_status(w.get("status")) or "pending"
        by_status[s] = by_status.get(s, 0) + 1
    return {
        "total": len(wishes),
        "by_status": by_status,
        "active": by_status.get("active", 0),      # 归 OPUS 推进中
        "pending": by_status.get("pending", 0),    # 等 BRO 拍板
        "review": by_status.get("review", 0),      # 等 BRO 验收
        "live": by_status.get("live", 0),          # 已上线
    }


def migrate_to_v53() -> dict:
    """卷五十三 · 一次性把 54 条旧 wish 迁到新四态 + 子标记。

    幂等: 已是新值的不动。 用 git 真相消歧 (老 ready_for_merge / done 若分支已合 → live)。
    迁前 save_wishlist 走 safe_write · 自动带 timestamp 备份 (data/_backups/)。
    返 {changed, by_status, detail}
    """
    try:
        from workers.git_ops import audit_wishes_merge_state
    except Exception:
        audit_wishes_merge_state = None  # type: ignore

    data = load_wishlist()
    wishes = data.get("wishes", [])
    audit = {}
    if audit_wishes_merge_state:
        try:
            audit = audit_wishes_merge_state(wishes)
        except Exception:
            audit = {}

    changed = 0
    detail = []
    for w in wishes:
        old_s = w.get("status")
        old_p = w.get("daemon_phase")
        new_s = _normalize_status(old_s)
        new_p = _normalize_phase(old_p)
        # git 真相消歧: 老 done/review·若分支真合进 master → 直接算 live
        git_state = (audit.get(w.get("id")) or {}).get("state")
        if new_s == "review" and git_state == "merged":
            new_s = "live"
        # blocked 只在 active 时有意义
        if new_s != "active" and new_p == "blocked":
            new_p = None
        if new_s != old_s or new_p != old_p:
            w["status"] = new_s
            w["daemon_phase"] = new_p
            changed += 1
            detail.append({"id": w.get("id"), "from": old_s, "to": new_s,
                           "phase_from": old_p, "phase_to": new_p})
    if changed:
        save_wishlist(data)
    by_status: dict[str, int] = {}
    for w in wishes:
        by_status[w.get("status")] = by_status.get(w.get("status"), 0) + 1
    return {"changed": changed, "by_status": by_status, "detail": detail}
