"""
workers/outcomes.py
===================

卷三十一 · 闭环反馈机制

把"掘金机会 → 可行性分析 → 决策 → 执行 → 反馈"串成闭环：
当 BRO 决定不做某个机会（或做完之后）·反馈记录在这里·
下次 mine_opportunities / analyze_feasibility 跑 LLM 时·
会把这些历史塞进 prompt——让 OPUS 不重蹈覆辙·也越来越懂 BRO 的能力边界。

数据结构 data/outcomes/{opp_id}.json：
  - opp_id           · 对应掘金机会 id
  - opp_title        · 机会标题快照
  - opp_domain       · 领域
  - status           · not_started / in_progress / completed / abandoned
  - decision_reason  · 为什么做 / 为什么不做（拒做原因）· 这是最重要的
  - actual_revenue_cny    · 已实现的实际收入（人民币·允许 0）
  - actual_cost_cny       · 已支出的实际成本
  - efficiency_gain       · 增效部分文字描述（自动化省了多少时间等）
  - lessons_learned       · 经验教训
  - updates          · 状态变更历史 [{at, status, note}]
  - created_at / updated_at

红线：
  - 一次只动 data/outcomes/ 下自己的文件
  - 写之前先读·防止并发覆盖（同进程足够·分布式后续再说）
  - 历史 updates 永远追加·不删
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
OUTCOMES_DIR = DATA_DIR / "outcomes"
OUTCOMES_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("opus.outcomes")


VALID_STATUS = {"not_started", "in_progress", "completed", "abandoned"}
_STATUS_LABEL = {
    "not_started": "未启动",
    "in_progress": "进行中",
    "completed":   "已完成",
    "abandoned":   "已放弃",
}


def _display_title(out: dict) -> str:
    """机会标题兜底（卷七十四续十四）。

    opp_title 是新建 outcome 时从 opportunities.json 抓的快照·但机会列表会轮替·
    旧机会被挤出后 _opp_lookup 拿不到标题·title 就成了 None·UI 只能显示裸 "?"。
    这里按 opp_title → 决策理由摘要 → opp_id → 占位文案逐级兜底·让卡片永远有意义。
    """
    t = (out.get("opp_title") or "").strip()
    if t:
        return t
    dr = (out.get("decision_reason") or "").strip()
    if dr:
        return (dr[:24] + "…") if len(dr) > 24 else dr
    oid = (out.get("opp_id") or "").strip()
    if oid:
        return f"机会 {oid}"
    return "未命名机会"


def _atomic_write(path: Path, text: str) -> None:
    """卷四十六 III · wish-badd4 收编到 safe_write
    outcomes.json 是 BRO 实战收益记录·backup=True"""
    from .safe_write import atomic_write_text
    atomic_write_text(path, text, backup=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _opp_lookup(opp_id: str) -> dict:
    """从 opportunities.json 拿到 title / domain 快照·只读"""
    opp_file = DATA_DIR / "opportunities.json"
    if not opp_file.exists():
        return {}
    try:
        data = json.loads(opp_file.read_text(encoding="utf-8"))
        for opp in data.get("opportunities") or []:
            if opp.get("id") == opp_id:
                return {
                    "title": opp.get("title"),
                    "domain": opp.get("domain"),
                }
    except Exception as e:
        logger.warning("opportunities.json read failed: %s", e)
    return {}


def load_outcome(opp_id: str) -> Optional[dict]:
    """读单条 outcome · 不存在返回 None"""
    f = OUTCOMES_DIR / f"{opp_id}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("outcome %s corrupt: %s", opp_id, e)
        return None


def record_outcome(
    opp_id: str,
    *,
    status: Optional[str] = None,
    opp_title: Optional[str] = None,
    decision_reason: Optional[str] = None,
    actual_revenue_cny: Optional[float] = None,
    actual_cost_cny: Optional[float] = None,
    efficiency_gain: Optional[str] = None,
    lessons_learned: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """
    记录/更新一条 outcome·返回最新完整 outcome。

    所有可选字段：None 表示不动·只更新非 None 字段。
    每次调用都会在 updates 数组里追加一条变更记录。
    """
    if not opp_id:
        return {"ok": False, "error": "opp_id 是必填"}
    if status is not None:
        status = status.strip().lower()
        if status not in VALID_STATUS:
            return {
                "ok": False,
                "error": f"status 必须是 {sorted(VALID_STATUS)} 之一·收到 {status!r}",
            }

    existing = load_outcome(opp_id)
    if existing:
        # 在已有基础上更新
        out = dict(existing)
    else:
        # 新建·从 opportunities.json 拿标题快照
        snap = _opp_lookup(opp_id)
        out = {
            "opp_id": opp_id,
            "opp_title": snap.get("title"),
            "opp_domain": snap.get("domain"),
            "status": "not_started",
            "decision_reason": "",
            "actual_revenue_cny": None,
            "actual_cost_cny": None,
            "efficiency_gain": "",
            "lessons_learned": "",
            "updates": [],
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }

    prev_status = out.get("status", "not_started")
    changed_fields: list[str] = []

    if status is not None and status != prev_status:
        out["status"] = status
        changed_fields.append(f"status: {prev_status} → {status}")
    # 标题快照兜底·机会轮替后再补一次·只在当前为空时写·不覆盖已有快照
    if opp_title is not None:
        t = opp_title.strip()
        if t and not (out.get("opp_title") or "").strip():
            out["opp_title"] = t[:120]
            changed_fields.append("opp_title")
    if decision_reason is not None:
        d = decision_reason.strip()
        if d and d != out.get("decision_reason"):
            out["decision_reason"] = d[:600]
            changed_fields.append("decision_reason")
    if actual_revenue_cny is not None:
        try:
            v = float(actual_revenue_cny)
            out["actual_revenue_cny"] = v
            changed_fields.append(f"actual_revenue_cny={v}")
        except (TypeError, ValueError):
            pass
    if actual_cost_cny is not None:
        try:
            v = float(actual_cost_cny)
            out["actual_cost_cny"] = v
            changed_fields.append(f"actual_cost_cny={v}")
        except (TypeError, ValueError):
            pass
    if efficiency_gain is not None:
        e = efficiency_gain.strip()
        if e:
            out["efficiency_gain"] = e[:400]
            changed_fields.append("efficiency_gain")
    if lessons_learned is not None:
        ll = lessons_learned.strip()
        if ll:
            out["lessons_learned"] = ll[:600]
            changed_fields.append("lessons_learned")

    if not changed_fields and not note:
        # 什么都没动·不写
        return {"ok": True, "no_op": True, "outcome": out}

    out["updated_at"] = _now_iso()
    if "updates" not in out or not isinstance(out["updates"], list):
        out["updates"] = []
    out["updates"].append({
        "at": _now_iso(),
        "status": out["status"],
        "fields": changed_fields,
        "note": (note or "").strip()[:400],
    })
    # 历史最多保留 50 条
    out["updates"] = out["updates"][-50:]

    out_file = OUTCOMES_DIR / f"{opp_id}.json"
    _atomic_write(out_file, json.dumps(out, ensure_ascii=False, indent=2))
    logger.info(
        "outcome %s · status=%s · changed=%s",
        opp_id, out["status"], changed_fields,
    )
    return {"ok": True, "outcome": out}


def list_outcomes(*, max_items: int = 50) -> dict:
    """列出所有 outcomes · 按 updated_at 倒序"""
    items: list[dict] = []
    for f in OUTCOMES_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            items.append({
                "opp_id": data.get("opp_id", f.stem),
                "opp_title": _display_title(data),
                "opp_domain": data.get("opp_domain") or "?",
                "status": data.get("status", "not_started"),
                "status_label": _STATUS_LABEL.get(
                    data.get("status", "not_started"), "?"
                ),
                "decision_reason": data.get("decision_reason", ""),
                "actual_revenue_cny": data.get("actual_revenue_cny"),
                "actual_cost_cny": data.get("actual_cost_cny"),
                "efficiency_gain": data.get("efficiency_gain", ""),
                "updated_at": data.get("updated_at", ""),
                "updates_count": len(data.get("updates") or []),
            })
        except Exception as e:
            logger.warning("outcome file %s corrupt: %s", f.name, e)
    items.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    counters = {k: 0 for k in VALID_STATUS}
    for it in items:
        counters[it["status"]] = counters.get(it["status"], 0) + 1
    return {
        "generated_at": _now_iso(),
        "total": len(items),
        "by_status": counters,
        "items": items[:max_items],
    }


def load_outcomes_for_prompt(*, max_chars: int = 1200) -> str:
    """
    给 mine_opportunities / analyze_feasibility 的 LLM prompt 用·
    把所有 outcomes 渲染成纯文本块·让 LLM 知道 BRO 历史决策。

    重点突出"放弃 / 拒做"原因——这是 BRO 能力边界的真正信号。
    """
    summary = list_outcomes(max_items=30)
    items = summary.get("items") or []
    if not items:
        return "（暂无历史反馈 · 这是第一次跟 BRO 走完整闭环）"
    lines: list[str] = []
    by_st = summary.get("by_status") or {}
    lines.append(
        f"BRO 至今对 {summary['total']} 个机会有反馈："
        f"放弃 {by_st.get('abandoned', 0)} / 完成 {by_st.get('completed', 0)} / "
        f"进行 {by_st.get('in_progress', 0)} / 未启动 {by_st.get('not_started', 0)}"
    )
    lines.append("")
    # 优先放 abandoned · 这是最关键的负反馈信号
    items_sorted = sorted(
        items,
        key=lambda x: {"abandoned": 0, "completed": 1, "in_progress": 2, "not_started": 3}.get(
            x.get("status", "not_started"), 9,
        ),
    )
    for it in items_sorted[:12]:
        st = it.get("status", "?")
        label = _STATUS_LABEL.get(st, st)
        title = it.get("opp_title") or "?"
        domain = it.get("opp_domain") or "?"
        reason = it.get("decision_reason") or ""
        line = f"- [{label}·{domain}] 《{title}》"
        if reason:
            line += f" — BRO 说：{reason[:120]}"
        if st == "completed":
            rev = it.get("actual_revenue_cny")
            if rev is not None:
                line += f"（实际收入 ¥{rev}）"
            ef = it.get("efficiency_gain")
            if ef:
                line += f"（增效：{ef[:60]}）"
        lines.append(line)
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n…（已截断）"
    return text


# ───────────────────────────────────────────────────────────────────
# 卷三十三 · 同类执行反馈合并分析
#
# BRO 卷三十三原话：
#   「我们执行了 A·已有结果·现在出现了新的机遇 C·可研报告生成时会抓取过去我们
#    的同类执行反馈·做合并分析·这样评估才更有深度·并且让人机范式形成闭环。」
#
# 实装思路：
#   - 给定一个正在评估的 opp · 从所有 outcomes 里找"同类"
#   - 同类判定：相同 domain 加分 + 标题 / decision_reason 关键词重叠加分
#   - 渲染为"经验萃取"块 · 让 LLM 直接引用
# ───────────────────────────────────────────────────────────────────

def _extract_kw(text: str) -> set[str]:
    """简陋关键词抽取·跟 feasibility_analyzer 同款·避免循环 import"""
    import re as _re
    s = (text or "").lower()
    cn = _re.findall(r"[\u4e00-\u9fff]{2,}", s)
    en = [w for w in _re.findall(r"[a-zA-Z]{4,}", s)]
    stop = {
        "opus", "bro", "工具", "可以", "需要", "这个", "我们", "已经", "做一",
        "what", "with", "that", "have", "from", "this", "they", "your", "into",
        "report", "model", "doing", "than", "more",
    }
    return (set(cn) | set(en)) - stop


def find_similar_outcomes(
    opp: dict,
    *,
    top_n: int = 5,
    min_score: int = 1,
) -> list[dict]:
    """
    根据当前 opp · 在所有历史 outcomes 里挑"同类"·返回带 similarity_score 的列表。

    评分规则：
      - 相同 domain → +2
      - 标题关键词重叠每个 → +1
      - decision_reason 关键词重叠每个 → +1
      - 状态 abandoned/completed → +0.5 优先（说明 BRO 真有结论）
    """
    all_outcomes = list_outcomes(max_items=200).get("items") or []
    if not all_outcomes:
        return []

    target_kw = _extract_kw(f"{opp.get('title','')} {opp.get('summary','')}")
    target_domain = (opp.get("domain") or "").lower()

    scored: list[tuple[float, dict]] = []
    for o in all_outcomes:
        score = 0.0
        # 跳过自己
        if o.get("opp_id") and o.get("opp_id") == opp.get("id"):
            continue
        if target_domain and (o.get("opp_domain") or "").lower() == target_domain:
            score += 2
        o_kw = _extract_kw(
            f"{o.get('opp_title','')} {o.get('decision_reason','')} "
            f"{o.get('lessons_learned','')}"
        )
        overlap = target_kw & o_kw
        score += len(overlap)
        st = o.get("status") or ""
        if st in ("abandoned", "completed"):
            score += 0.5
        if score >= min_score:
            scored.append((score, o))

    scored.sort(key=lambda x: x[0], reverse=True)
    out: list[dict] = []
    for score, o in scored[:top_n]:
        item = dict(o)
        item["similarity_score"] = round(score, 2)
        out.append(item)
    return out


def render_similar_outcomes_prompt(opp: dict, *, top_n: int = 5) -> str:
    """
    渲染"同类执行反馈"prompt 块 · 给 feasibility_analyzer 调用。

    设计：明确告诉 LLM "这些是 BRO 过去做过 / 没做的同类事·**用它们做合并分析**"。
    """
    similar = find_similar_outcomes(opp, top_n=top_n)
    if not similar:
        return (
            "（BRO 还没有同类执行反馈 · 这是第一次走「机会 → 执行 → 复盘」全闭环 · "
            "你的分析将成为未来的参考样本）"
        )

    lines: list[str] = []
    lines.append(
        f"BRO 过去做过 / 评估过 {len(similar)} 个**同类**项目·"
        f"以下是按相似度排序的真实结果——**请基于这些经验·而不是通用模板·做合并分析**："
    )
    lines.append("")
    for i, o in enumerate(similar, 1):
        st = o.get("status", "?")
        label = _STATUS_LABEL.get(st, st)
        title = o.get("opp_title") or "?"
        dom = o.get("opp_domain") or "?"
        sim = o.get("similarity_score", 0)
        lines.append(f"### [{i}] {label} · [{dom}] 《{title}》 (相似度 {sim})")
        if o.get("decision_reason"):
            lines.append(f"  - **决策理由**：{o['decision_reason'][:200]}")
        if st == "completed":
            rev = o.get("actual_revenue_cny")
            cost = o.get("actual_cost_cny")
            if rev is not None or cost is not None:
                lines.append(
                    f"  - **实际收益**：收入 ¥{rev or 0} · 成本 ¥{cost or 0}"
                )
            if o.get("efficiency_gain"):
                lines.append(f"  - **增效**：{o['efficiency_gain'][:120]}")
        if o.get("lessons_learned"):
            lines.append(f"  - **经验教训**：{o['lessons_learned'][:200]}")
        lines.append("")

    lines.append("**LLM 你要做的事**：")
    lines.append("1. 在 verdict_reason 里**明确引用**至少 1 条同类经验（用方括号 [1] / [2] 编号）")
    lines.append("2. 如果 abandoned 的同类事跟当前机会很像 · 在 risks / threats 里复用它的失败原因")
    lines.append("3. 如果 completed 的同类事说明 BRO 真能跑通某类 · 在 strengths / capability_match 里反映")
    lines.append("4. **不要无视这些反馈说通用话** · 这是 BRO 这个具体人的真实历史")
    return "\n".join(lines)


if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO)
    print(json.dumps(list_outcomes(), ensure_ascii=False, indent=2))
