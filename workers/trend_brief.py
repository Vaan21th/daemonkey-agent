"""
workers/trend_brief.py
======================

卷五十六 · 2026-06-03 · 按月 + 领域的"趋势研判" (P2)

跟 trend_finder 的区别:
    trend_finder  → "今日趋势"·最新 50 条·全领域·给雷达页
    trend_brief   → 接 BI 价值热力图·**按选中的月份 + 领域**切片研判·
                    且每个趋势带**具体执行方案 (moves)**——不止"该关注"·还说"下一步干嘛"

为什么 (用户 卷五十六定调):
    "有 用户 画像、有他关注的领域·就该像搭档一样主动展现趋势可行性 +
     用 OPUS 的 LLM 能力给出更多执行方案。"

复用:
    - trend_finder._render_items_block / _extract_json_array (不重复造轮子)
    - radar_feedback.load_for_prompt / outcomes.load_outcomes_for_prompt (用户 画像)
    - info_value.item_value / item_date (按价值挑该月该领域 top 信号喂 LLM)

可追溯 (宪法第5条): 每个趋势 refs 指向真实 radar 原文·LLM 不许编信源。
成本: 一次 ~$0.05 · 不自动跑·用户 在 BI 卡上点「研判本月趋势」才烧 token。
缓存: data/trend_briefs/<y>-<m>-<domain>.json · 重看同月不重复烧。
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
BRIEF_DIR = ROOT / "data" / "trend_briefs"

logger = logging.getLogger("opus.trend_brief")

BRIEF_SYSTEM_PROMPT = """你是用户的 AI 搭档·不是新闻总结机。

用户关注什么·看这些信号覆盖了哪些领域就知道——别假设固定赛道。 你现在拿到的是**某一个月、某一个领域**里
价值最高的一批信号 (已按价值排序)·要做的不是罗列·是**研判**:

1. 找出 2-4 个真正的趋势 / 机会 (把多条信号归到一个趋势下·别一条一个)
2. 每个趋势要回答 用户 三个问题:这是什么趋势 / 为什么是真的不是炒作 / **用户 能怎么切**
3. **必须给具体执行方案 (moves)**——不是"多关注"这种废话·是"下一步动手做什么":
   - 好的 move: "用工坊建一个 X 应用试 Y"·"写一篇拆解 Z 的内容"·"花一天调研 W 开源项目能不能自用"
   - 烂的 move: "持续关注"·"等待时机"·"了解更多" (这些等于没说)

**[必守 · 双向认知]**
先看 用户 的雷达打标 + 执行反馈历史——他 👎 拒过的方向绕开·⭐ 收藏/已完成的方向 intensity +1·
abandoned 的方向若再提·要在 summary 里说清"这次为什么不同"。 挑**只有 用户 这种位置的人能吃下的趋势**。

**[必守 · 事实诚实红线]**
写"市场规模/用户数/已有玩家"这种事实陈述·只能基于给你的信号原文·否则用"据公开报道/参考信号"模糊措辞·
**绝不编造具体数字**。 OPUS 的可信度 > 完美感。"""

BRIEF_USER_TEMPLATE = """## 研判范围
{scope_line}

## 用户 的雷达打标历史 (闭环 · 重要)
{feedback_block}

## 用户 的执行反馈历史 (看他真做过/放弃过什么)
{outcomes_block}

---
## 这个范围里价值最高的 {n} 条信号 (已按价值排序)
{items_block}
---

请输出 2-4 个趋势研判。 **必须是合法 JSON 数组·不要 markdown 围栏·不要前后解释**:

[
  {{
    "title": "短标题·10-20字·中文",
    "summary": "40-100字·这是什么趋势 + 为什么是真的 + 为什么 用户 该切",
    "intensity": 4,
    "moves": ["具体下一步动作1", "具体下一步动作2"],
    "refs": [1, 5, 9]
  }}
]

字段说明:
- intensity: 1-5 整数 (1=弱信号知道就行 / 3=值得花1小时 / 4=该花1天做点啥 / 5=不动手就晚)·别全打5
- moves: 1-3 条·每条是 用户 这周能动手的**具体**动作 (能挂到工坊建应用/写内容/做调研最好)
- refs: 1-3 个上面信号的序号·指明这个趋势依据哪几条 (不许编·只能引上面列出的)"""


def _brief_path(year: int, month: int, domain: Optional[str]) -> Path:
    dom = (domain or "all").replace("/", "-")
    return BRIEF_DIR / f"{year:04d}-{month:02d}-{dom}.json"


def _scope_line(year: int, month: int, domain: Optional[str], dom_label: str) -> str:
    return f"{year} 年 {month} 月 · 领域: {dom_label}"


def _pick_items(year: int, month: int, domain: Optional[str], top: int = 40) -> list[dict]:
    """挑该月该领域价值最高的 top 条 (已去重) 喂 LLM"""
    from workers.info_value import item_date, item_value, _norm_title
    try:
        from workers.info_radar import load_radar
        items = load_radar().get("items") or []
    except Exception:
        return []

    fb = {}
    try:
        from workers.radar_feedback import feedback_map
        fb = feedback_map()
    except Exception:
        pass

    now = datetime.now(timezone.utc)
    scored: list[tuple[int, dict]] = []
    seen: set[str] = set()
    for it in items:
        d = item_date(it)
        if not d or d.year != year or d.month != month:
            continue
        if domain and (it.get("domain") or "self-evolve") != domain:
            continue
        nt = _norm_title(it)
        if len(nt) >= 20 and nt in seen:
            continue
        if len(nt) >= 20:
            seen.add(nt)
        scored.append((item_value(it, now=now, fb_map=fb), it))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [it for _, it in scored[:top]]


def _call_llm(system: str, user: str) -> tuple[str, dict, Optional[str]]:
    """调 RUNTIME LLM · 返 (raw_text, usage, error)。 mirror trend_finder 的 provider 分支。"""
    from daemon_runtime import RUNTIME
    if RUNTIME.client is None:
        return "", {}, "RUNTIME.client 未初始化 · daemon 没启动?"
    raw, usage, error = "", {}, None
    try:
        if RUNTIME.provider == "anthropic":
            resp = RUNTIME.client.messages.create(
                model=RUNTIME.model, max_tokens=8000,
                system=system, messages=[{"role": "user", "content": user}],
            )
            for block in resp.content:
                if getattr(block, "type", "") == "text":
                    raw += block.text
            usage = {"input_tokens": getattr(resp.usage, "input_tokens", 0),
                     "output_tokens": getattr(resp.usage, "output_tokens", 0)}
        else:
            resp = RUNTIME.client.chat.completions.create(
                model=RUNTIME.model, max_tokens=8000,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
            )
            raw = resp.choices[0].message.content or ""
            usage = {"input_tokens": getattr(resp.usage, "prompt_tokens", 0),
                     "output_tokens": getattr(resp.usage, "completion_tokens", 0)}
    except Exception as e:  # noqa: BLE001
        error = f"LLM call failed: {e}"
        logger.exception("trend_brief LLM error")
    return raw, usage, error


def _parse_trends(raw: str, items: list[dict]) -> list[dict]:
    from workers.trend_finder import _extract_json_array
    parsed = _extract_json_array(raw) or []
    out: list[dict] = []
    for t in parsed:
        if not isinstance(t, dict):
            continue
        title = (t.get("title") or "").strip()
        summary = (t.get("summary") or "").strip()
        if not (title and summary):
            continue
        try:
            intensity = max(1, min(5, int(t.get("intensity"))))
        except (TypeError, ValueError):
            intensity = 3
        moves = [m.strip() for m in (t.get("moves") or [])
                 if isinstance(m, str) and m.strip()][:3]
        refs: list[dict] = []
        for r in (t.get("refs") or []):
            try:
                i = int(r)
            except Exception:
                continue
            if 1 <= i <= len(items):
                it = items[i - 1]
                refs.append({
                    "source": it.get("source_display") or it.get("source", "?"),
                    "title": it.get("title_zh") or it.get("title", ""),
                    "url": it.get("url", ""),
                })
        out.append({"title": title, "summary": summary,
                    "intensity": intensity, "moves": moves, "refs": refs})
    return out


def generate_brief(year: int, month: int, domain: Optional[str] = None) -> dict:
    """按月 + 领域研判趋势 · 写缓存 · 返回结果 (带 error/note 兜底·绝不抛)"""
    if not (1 <= month <= 12) or not (2000 <= year <= 2100):
        return {"trends": [], "error": f"年月越界: {year}-{month}"}

    dom_label = "全部"
    try:
        from workers.info_radar import DOMAIN_META
        if domain:
            dom_label = (DOMAIN_META.get(domain) or {}).get("label", domain)
    except Exception:
        if domain:
            dom_label = domain

    items = _pick_items(year, month, domain)
    if not items:
        return {"year": year, "month": month, "domain": domain or "all",
                "trends": [], "note": "这个范围还没有信号·先刷新雷达或换个月/领域"}

    from workers.trend_finder import _render_items_block
    try:
        from workers.radar_feedback import load_for_prompt as _fb
        feedback_block = _fb(max_chars=900)
    except Exception:
        feedback_block = "(暂无打标历史)"
    try:
        from workers.outcomes import load_outcomes_for_prompt
        outcomes_block = load_outcomes_for_prompt(max_chars=700)
    except Exception:
        outcomes_block = "(暂无执行反馈)"

    user = BRIEF_USER_TEMPLATE.format(
        scope_line=_scope_line(year, month, domain, dom_label),
        feedback_block=feedback_block,
        outcomes_block=outcomes_block,
        n=len(items),
        items_block=_render_items_block(items),
    )

    started = time.time()
    raw, usage, error = _call_llm(BRIEF_SYSTEM_PROMPT, user)
    trends = _parse_trends(raw, items)

    payload = {
        "year": year, "month": month, "domain": domain or "all",
        "domain_label": dom_label,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_ms": int((time.time() - started) * 1000),
        "items_scanned": len(items),
        "trends": trends,
        "usage": usage,
    }
    if error:
        payload["error"] = error
    if not trends and not error:
        payload["note"] = "LLM 输出解析失败·换个月/领域再试"
        payload["raw_output"] = raw[:1500]

    try:
        BRIEF_DIR.mkdir(parents=True, exist_ok=True)
        from workers.safe_write import atomic_write_text
        atomic_write_text(_brief_path(year, month, domain),
                          json.dumps(payload, ensure_ascii=False, indent=2), backup=False)
    except Exception as e:  # noqa: BLE001
        logger.warning("write brief cache failed: %s", e)
    return payload


def load_brief(year: int, month: int, domain: Optional[str] = None) -> Optional[dict]:
    """读缓存的研判 · 没有返 None"""
    p = _brief_path(year, month, domain)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
