"""
agent_tools/wish_update.py
==========================

 · 更新一条心愿的状态 / 路径 / 反思

典型调用：
  - 用户 说 "wish-xxx 批准 · 推给 daemon 装" → wish_update(status=approved, integration_path=daemon)
  - 用户 说 "wish-yyy 我去 Cursor 装" → wish_update(status=in_progress, integration_path=cursor)
  - 用户 说 "wish-zzz 装完了·感觉 X" → wish_update(status=done, reflection=...)
  - OPUS 自己跑 daemon 装路径 → wish_update(status=in_progress) 开干前打一下

tier: TIER_CONFIRM
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool


ROOT = Path(__file__).resolve().parent.parent


def _slugify(title: str, max_len: int = 30) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff\-]+", "-", title or "")
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:max_len] or "wip"


def _maybe_create_dev_branch(wid: str, title: str) -> tuple[Optional[str], str]:
    """ 起 /  改 · OPUS 改 daemon 代码前自动起 wish-xxx/<slug> 分支

     ③号机制: 委托给 workers.git_ops.branch_from_master · 分支固定从 master 切
    (不再从"当前 HEAD"切) · 消除"在别的 wish 分支上开新 wish · 丢掉前一个没合并的 wish"
    这类幽灵 ( BI 退样式的直接原因)。 脚下脏会先 checkpoint 不丢。

    返回 (要写入 wish.dev_branch 的分支名 or None, 给 用户 看的消息)。
    """
    try:
        from workers.git_ops import branch_from_master
        return branch_from_master(wid, _slugify(title))
    except Exception as e:
        return None, f"git 操作异常 · {type(e).__name__}: {e}"


def _summarize(args: dict) -> str:
    wid = args.get("wish_id") or "?"
    bits = []
    if args.get("status"):
        bits.append(f"status→{args['status']}")
    if args.get("integration_path"):
        bits.append(f"path→{args['integration_path']}")
    if args.get("priority") is not None:
        bits.append(f"priority→{args['priority']}")
    if args.get("reflection"):
        bits.append("写反思")
    return f"更新心愿 {wid} · " + (" · ".join(bits) or "无改动")


def _run(args: dict) -> ToolResult:
    from workers.wishlist import get_wish, update_wish

    wid = (args.get("wish_id") or "").strip()
    if not wid:
        return ToolResult(ok=False, output="", error="wish_id 必填")

    cur = get_wish(wid)
    if cur is None:
        return ToolResult(ok=False, output="", error=f"找不到 wish: {wid}")

    patch = {}
    for k in (
        "status", "integration_path", "priority", "reflection",
        "title", "why", "design_sketch",
        # 补丁4 · daemon 路径字段
        "daemon_phase", "implementation_plan", "implementation_log",
        "dev_branch", "diff_summary",
    ):
        if k in args and args[k] is not None:
            patch[k] = args[k]
    if not patch:
        return ToolResult(ok=False, output="", error="至少要传一个要改的字段")

    # wish-83fe7c7b 补丁 · 状态离开 active 时自动清 daemon_phase
    # daemon_phase 只在 active 状态有意义 · 进 review/live/rejected 时残留会误导 UI
    new_status = args.get("status")
    if new_status and new_status != "active" and "daemon_phase" not in args:
        patch["daemon_phase"] = None

    from workers.wishlist import _normalize_status

    #  · P1 · 收尾三问轻硬闸 (wish-c0c34012 · SKILL 触发修复)
    # 标 review/live 前·若本回合干了带副作用的活却没调任何沉淀工具 → 拦一次·逼 OPUS 过三问。
    # 给狡辩出路: 确实不用沉淀就带 closure_ack=true 重调放行。 闸自身异常不拦 (不把正常流程搞挂)。
    _target_status = _normalize_status(args.get("status"))
    if _target_status in ("review", "live"):
        try:
            from workers.closure_check import wish_closure_gate
            _gate = wish_closure_gate(_target_status, acked=bool(args.get("closure_ack")))
            if _gate:
                return ToolResult(ok=False, output="", error=_gate)
        except Exception:
            pass

    #  · ②号机制升级 · live 是唯一的"真合并"闸门 (不再有 ready_for_merge 假态)
    # 病根 (/四九/五十): 好活儿没合进 master · status 却谎报上线 → 一回退就丢。
    # 现在: 标 live 必须先真 merge 成功 (有真分支时) · 冲突则 abort 回干净 master + 报错 ·
    #       状态不变。 cursor 直改 master 的 wish 没分支 → 代码本就在主干 · 直接放行 live。
    merge_note: Optional[str] = None
    if _normalize_status(args.get("status")) == "live":
        target = (cur.get("dev_branch") or "").strip()
        is_real_branch = bool(target) and " " not in target and target != "master"
        if is_real_branch:
            try:
                from workers.git_ops import merge_wish_to_master
                mres = merge_wish_to_master(target, expected_wish_id=cur.get("id") or wid)
                merge_note = mres.get("note")
                if not mres.get("ok"):
                    return ToolResult(
                        ok=False, output="",
                        error=f"merge 回 master 失败 · 状态未改为 live (代码没真进主干·不许谎报上线):\n  {merge_note}",
                    )
            except Exception as e:
                return ToolResult(ok=False, output="", error=f"merge 异常: {type(e).__name__}: {e}")
        else:
            merge_note = "无独立分支 (cursor 直改 master) · 代码本就在主干 · 直接上线"

    try:
        new = update_wish(wid, **patch)
    except ValueError as e:
        return ToolResult(ok=False, output="", error=str(e))
    if new is None:
        return ToolResult(ok=False, output="", error=f"更新失败: {wid}")

    #  · ③号机制改触发点 · 分支在"该写码了"时自动从 master 切:
    #   daemon 路径 + 已进 active + 没卡在 plan_pending (= 方案已批/无需批) + 还没分支
    # 这样勘察阶段 (plan_pending) 不建分支 · 用户 批方案后一进写码态就自动建。
    dev_branch_note: Optional[str] = None
    if (new.get("integration_path") == "daemon"
            and new.get("status") == "active"
            and new.get("daemon_phase") is None
            and not (new.get("dev_branch") or "").strip()):
        branch, msg = _maybe_create_dev_branch(wid, new.get("title") or wid)
        dev_branch_note = msg
        if branch:
            new = update_wish(wid, dev_branch=branch) or new

    # 友好状态摘要 ( · 新四态 + 子标记)
    status_icon = {
        "pending":  "💡",
        "active":   "🔨",
        "review":   "🔍",
        "live":     "🚀",
        "rejected": "❌",
    }.get(new["status"], "·")
    path_icon = {
        "daemon": "🤖 DAEMON",
        "cursor": "🎯 Cursor",
        "undecided": "·",
    }.get(new.get("integration_path") or "undecided", "·")

    sub = new.get("daemon_phase")
    sub_label = {"plan_pending": "⏸ 等 用户 批方案", "blocked": "⚠️ 撞墙·等 用户 看"}.get(sub or "", "")

    lines = [
        f"# {status_icon} 心愿已更新 · `{new['id']}`",
        f"  - 标题: {new['title']}",
        f"  - 状态: **{new['status']}**" + (f" · {sub_label}" if sub_label and new['status'] == 'active' else "") + f" · 路径: {path_icon}",
        f"  - 优先级: {'⭐' * new['priority']}",
    ]
    if new["status"] == "live":
        lines.append("")
        lines.append("→ 🚀 已上线 · 代码已真合进 master 主干 · 真完成了")
        if merge_note:
            lines.append(f"  git: {merge_note}")
    elif new["status"] == "review":
        lines.append("")
        lines.append("→ 🔍 OPUS 完工 · 代码在分支上 · 等 用户 看 diff + 验收 · 通过后 mark live (自动合主干)")
    elif new["status"] == "rejected" and new.get("reflection"):
        lines.append("")
        lines.append("**反思**:")
        for ln in new["reflection"].splitlines()[:10]:
            lines.append(f"  > {ln}")
    elif new["status"] == "active":
        _ip = new.get("integration_path") or "undecided"
        if sub == "plan_pending":
            lines.append("")
            lines.append("→ ⏸ OPUS 出完方案 · 停下等 用户 批方案 (关卡1) · 批了才开始写码")
        elif _ip == "daemon":
            lines.append("")
            lines.append("→ 🔨 DAEMON 路径 · OPUS 在自己的分支上写码 · 完工进 review 等验收")
        elif _ip == "cursor":
            lines.append("")
            lines.append("→ 🔨 Cursor 路径 · 用户 把这个 wish_id 丢给 Claude · 装完回来 mark review")

    if dev_branch_note:
        lines.append("")
        lines.append(f"**git**: {dev_branch_note}")

    #  · 关键状态联动桌宠 (新态):
    #   live → happy (真上线) / rejected → confused / plan_pending → surprised (出方案等审) / blocked → confused
    pet_state = {
        "live": "happy",
        "rejected": "confused",
    }.get(new["status"])
    if new.get("daemon_phase") == "plan_pending":
        pet_state = "surprised"
    elif new.get("daemon_phase") == "blocked":
        pet_state = "confused"
    if pet_state:
        try:
            from agent_tools.set_emotion import SPEC as _emo_spec
            _emo_spec.run({"state": pet_state, "note": f"wish-update · {new['id']} · {new['status']}"})
        except Exception:
            pass

    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="wish_update",
    description=(
        "更新一条 OPUS 心愿的状态 / 集成路径 / 反思 ( · 四态精简)\n\n"
        "**状态机 (4+1 态 · 砍掉了老的 drafted/approved/in_progress/done/ready_for_merge)**:\n"
        "  pending → active → review → live    任何态 → rejected\n"
        "  - pending  = 等 用户 拍板 (批 / 弃)\n"
        "  - active   = 归 OPUS 推进 (勘察 / 写码 / 自测) · 球在 OPUS 半场\n"
        "  - review   = OPUS 完工·代码在分支上·等 用户 看 diff + 验收\n"
        "  - live     = 已真合进 master 主干 (标 live 会自动 merge·合不进就拒绝·防谎报上线)\n"
        "  - rejected = 弃\n\n"
        "**子标记 daemon_phase (仅 active 时有意义·UI 挂小 chip)**:\n"
        "  - plan_pending = (daemon 路径) OPUS 出完方案·停下等 用户 批方案 (关卡1)\n"
        "  - blocked      = OPUS 撞墙·等 用户 看\n\n"
        "**典型场景**:\n"
        "  - 用户 批准让 daemon 装 → status=active + integration_path=daemon (会先勘察出方案·设 daemon_phase=plan_pending 等批)\n"
        "  - 用户 批方案 → daemon_phase=null (清空·自动从 master 切分支开始写码)\n"
        "  - OPUS 写完自测过 → status=review (等 用户 看 diff)\n"
        "  - 用户 验收通过 → status=live (自动 merge 回 master)\n"
        "  - 撞墙 → daemon_phase=blocked · 不靠谱 → status=rejected\n"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "wish_id": {"type": "string", "description": "wish-xxxxxx 形式"},
            "status": {
                "type": "string",
                "enum": ["pending", "active", "review", "live", "rejected"],
                "description": "pending=等批 · active=OPUS推进 · review=完工待验 · live=合主干上线(自动merge) · rejected=弃",
            },
            "integration_path": {
                "type": "string",
                "enum": ["daemon", "cursor", "undecided"],
                "description": "由谁去装 · daemon=Daemonkey 自己·cursor=用户 拉 Cursor 里的 Claude",
            },
            "priority": {
                "type": "integer", "minimum": 1, "maximum": 5,
            },
            "reflection": {
                "type": "string",
                "description": "完成 / 改主意后的反思 · 装完写感受用",
            },
            "title": {"type": "string"},
            "why": {"type": "string"},
            "design_sketch": {"type": "string"},
            #  · 子标记 (仅 active 时有意义)
            "daemon_phase": {
                "type": "string",
                "enum": ["plan_pending", "blocked"],
                "description": (
                    "子标记 (仅 status=active 时有意义·UI 挂小 chip):\n"
                    "  plan_pending · (daemon 路径) OPUS 出完方案·停下等 用户 批方案 (关卡1)\n"
                    "  blocked      · OPUS 撞墙·等 用户 看\n"
                    "  传 null/不传 = 正常推进 (勘察/写码)\n"
                ),
            },
            "implementation_plan": {
                "type": "string",
                "description": "勘察阶段产物 · markdown 格式 · 给 用户 review 用",
            },
            "implementation_log": {
                "type": "string",
                "description": "实施日志 · markdown · 记录每步动作和结果",
            },
            "dev_branch": {
                "type": "string",
                "description": "OPUS 改代码用的 git 分支名 (如 wish-58af621e/装压缩层)",
            },
            "diff_summary": {
                "type": "string",
                "description": "改完后的 git diff 摘要 · UI 一眼能看",
            },
            "closure_ack": {
                "type": "boolean",
                "description": (
                    "收尾三问豁免 ( · 铁律9代码闸的狡辩出路):\n"
                    "  标 review/live 时若本回合干了活却没沉淀·会被拦下逼你过三问。\n"
                    "  确实啥也不用沉淀 (用户 没新信号 / 无可复用经验 / 无能力缺口) → 传 closure_ack=true 放行·\n"
                    "  并在 reflection 里一句话说明为什么不用沉淀。 别为了过闸乱标·这是给真无需沉淀的情况留的。"
                ),
            },
        },
        "required": ["wish_id"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
