"""
workers/feasibility_analyzer.py
================================

卷二十九 · 可行性分析

掘金机会卡只是"OPUS 一句话推荐" · 真正决定要不要做一个机会·还需要：
  - 风险评估 (技术/市场/法律/时间)
  - 资源需求 (用户 有什么 + 还需要什么)
  - 能力对照 (用户 画像 vs 需要的能力 · 缺口在哪)
  - 成本估算 (时间 / token 费用 / 第三方服务订阅)
  - 替代方案 (有没有更省力的切入点)
  - 综合可行性打分

数据流：
  掘金机会卡 (opportunities.json 一条)
    + OWNER-NOTEBOOK 画像
    + 现有 trends/radar 上下文
    → LLM 一次（用稍贵但靠谱的模型）
    → data/feasibility/<opp_id>.json
    → /dashboard/feasibility 列出所有已分析项

红线：
  - LLM 失败 → 返回 stub · 不让前端崩
  - 一份完整可行性 ~3000 tokens · 用 deepseek 不用 opus（成本控制）
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
FEASIBILITY_DIR = DATA_DIR / "feasibility"
FEASIBILITY_DIR.mkdir(exist_ok=True)
OPPORTUNITIES_FILE = DATA_DIR / "opportunities.json"

logger = logging.getLogger("opus.feasibility")


SYSTEM_PROMPT = """你是用户的 AI 搭档。你们正在评估一个具体掘金机会要不要动手。

你的任务是做**冷血诚实的可行性分析**——不是 cheerleader·是真正的搭档·该说"先别做"就说"先别做"。

**[卷三十五补丁2 · 事实较量红线 · 必守]**

可行性分析里**任何**关于"市场已有 / 竞品在做 / 政策环境 / 技术成熟度"的论断·
都是事实陈述·不是想象。在写这些字段前·**优先 web_search 一次实证**——
没工具就承认"不确定"·不要凭印象编造。

DeepSeek 等模型在卷三十四曾把 "neovim 配置" "1000 万用户" 这种纯幻觉写进对照分析里·
让 用户 当真就糟了。OPUS 的可信度 > 完美感。

**[卷三十五补丁2 · 看教材]**

用户消息里会附 OPUS 之前沉淀的高质量样本 (`## 教材` 部分)·
你的输出**至少要达到那个深度** —— 包括引用具体数字 / 标出来源 / 挑战既有结论 / 给反例。

分析维度（卷三十一升级 · 加 SWOT / 未来预期 / 成功路径）：
1. 风险（技术 / 市场 / 法律 / 时间窗口）—— 短期具体风险
2. SWOT 分析 —— 战略层四象限（自身优势/劣势 + 外部机会/威胁）
3. 未来预期 —— 3 个月 / 6 个月 / 12 个月的可能终态
4. 成功路径 —— 从今天到 用户 想要的终点 · 拆成 3-5 个阶段 · 每阶段有可验证里程碑
5. 资源（用户 现有的 · 还需要找的）
6. 能力对照（用户 画像里能匹配上的 · 还需要补的）
7. 成本（时间 / token / 第三方订阅 / 机会成本）
8. 替代方案（有没有更省力的版本）
9. 综合可行性打分（0-100）

**关键要求**：
- 所有评估必须扎根在 用户 的具体画像和当下状态上·不是教科书式的通用建议
- SWOT 四象限要"反着想"：S 是 用户 真的有的具体能力 / W 是 用户 真的缺的 / O 是市场已经在发生的 / T 是会被谁卡脖子
- 未来预期不是"假设一切顺利"——是"按 用户 现实节奏走·最可能是什么样"
- 成功路径必须可逆 · 每阶段失败时知道止损·用户是单打独斗的个人不是有钱有时间的大厂"""


USER_PROMPT_TEMPLATE = """## 待分析的掘金机会

**标题**: {title}
**领域**: {domain}
**OPUS 一句话**: {summary}
**OPUS 的适配判断**: {fit} · 理由: {fit_reason}
**成本预估**: {cost_effort} · **收益**: {upside} · **推荐度**: {recommend}/5
**OPUS 建议的下一步**:
{next_steps}

---

## 用户 当下画像

{bro_profile}

---

## 用户 的历史反馈 (outcomes 闭环 · 卷三十一)

{outcomes_block}

---

## 同类执行反馈 · 合并分析输入 (卷三十三 · 闭环深化)

{similar_outcomes_block}

---

## 信源 (Sources · 这次分析的客观信息基础 · 卷三十二补丁)

{sources_block}

---

## 教材 · OPUS 历史沉淀的高质量样本 · 卷三十五补丁2

{learnings_block}

---

{evidence_block}

---

## 任务

输出一份完整的可行性分析报告·**严格 JSON 格式**·不要 markdown 包裹：

```json
{{
  "feasibility_score": 0-100 整数 · 综合可行性,
  "verdict": "go|conditional|wait|skip",
  "verdict_reason": "50-100 字 · 一句话定调",
  "risks": [
    {{"type": "tech|market|legal|timing", "level": "low|medium|high", "detail": "30-80 字"}}
  ],
  "swot": {{
    "strengths": ["用户 自身相对这件事的 2-4 条具体优势 · 必须引用画像"],
    "weaknesses": ["用户 自身相对这件事的 2-4 条具体劣势 · 不绕弯"],
    "opportunities": ["外部环境的 2-4 个机会窗口 · 比如政策/趋势/红利期"],
    "threats": ["外部环境的 2-4 个威胁 · 比如竞品/平台规则/时间窗收缩"]
  }},
  "future_outlook": {{
    "three_months": "60-120 字 · 按 用户 现实节奏 · 3 个月最可能的状态",
    "six_months": "60-120 字 · 半年时间最可能撑到哪一步 · 收益级别",
    "one_year": "60-120 字 · 一年后最可能的终态 · 包括失败时该是什么样"
  }},
  "success_path": {{
    "stages": [
      {{"name": "阶段名 · 比如 '验证期' / 'MVP' / '冷启动'", "milestone": "可验证的里程碑 · 30 字", "criteria": "达到/未达到的判断标准 · 30 字", "weeks": "预计周数 · 整数或区间字符串"}}
    ],
    "end_state": "用户 想要的终态 · 50-100 字 · 不是空话 · 比如 '月收入稳定 ¥3000 + 每月发 8 条视频不靠激情'"
  }},
  "resources_have": ["用户 现在已经有的 · 比如 ' AiHubMix 账号' / '5 年 LLM 经验'"],
  "resources_need": ["还需要找的 · 比如 'D4 服务器账号' / 'OBS 推流工具'"],
  "capability_match": [
    {{"capability": "需要什么能力", "bro_has": "yes|partial|no", "evidence": "引用 用户 画像具体段或对应行为"}}
  ],
  "cost_breakdown": {{
    "time_hours_min": 整数,
    "time_hours_max": 整数,
    "tokens_estimate_usd": 数字 · 估算 LLM 调用美元成本,
    "subscriptions_monthly_usd": 数字 · 第三方服务月费,
    "opportunity_cost": "30 字 · 做这个意味着不做什么"
  }},
  "alternatives": [
    {{"name": "替代方案名", "delta": "和原方案的差异", "why_consider": "为什么值得考虑"}}
  ],
  "first_30_min": "30 字 · 用户 立刻能做的第一件事 · 验证这值得继续",
  "go_no_go": "三句话 · 如果 go · 三个最先要做的事 / 如果 skip · 为什么"
}}
```

要求：
1. **resources_have / resources_need** 必须基于 OWNER-NOTEBOOK · 不是泛泛
2. **capability_match** 每一行必须有 evidence · 不能空话
3. **cost_breakdown** 给数字 · 不要"中等成本"这种模糊说法
4. **verdict 不要默认 go** · 该 skip 就 skip · 这是诚实分析
5. **SWOT 不要凑数** · S/W 要扎根画像 · O/T 要扎根当下市场和雷达趋势
6. **未来预期要给"最可能"·不要给"最理想"** · 用户是单打独斗的个人不是大厂
7. **成功路径** 要可逆——每阶段失败时知道往哪退·不是"全 in 然后看天意"
8. **如果 outcomes 显示 用户 历史拒绝过类似机会** · 在 verdict_reason 里提一句·不重蹈覆辙
9. **信源引用**（卷三十二补丁 · 宪法第 5 条）—— 你看到的所有"信源"块里有 [r1]/[r2] 雷达条目 和 [d1]/[d2] 报告文档。 
   - 在 `verdict_reason` / `swot` 的 opportunities / threats / `future_outlook` 等需要"基于客观"的地方 · **引用对应编号** · 比如 "OpenAI 已经放了 Cowork（参考 [r2]）"
   - **不许发明信源**——你看到的列表就是全部·别捏造别的来源
   - 信源不足时·在 verdict_reason 里直接说"信源不足·建议先做 X 再回来"·不要硬编"""


def _atomic_write(path: Path, text: str) -> None:
    """卷四十六 III · wish-badd4 收编到 safe_write
    feasibility.json 是机会×用户 画像决策辅助·backup=True"""
    from .safe_write import atomic_write_text
    atomic_write_text(path, text, backup=True)


REPORTS_DIR = DATA_DIR / "reports"
RADAR_FILE = DATA_DIR / "radar.json"


_KEYWORD_STOP = {
    "opus", "bro", "工具", "可以", "需要", "这个", "我们", "已经", "做一", "一下",
    "what", "with", "that", "have", "from", "this", "they", "your", "into",
    "report", "model", "doing", "than", "more", "could", "should", "would",
    "做点", "做出", "做完", "起来", "出来", "上面", "下面",
}


def _extract_keywords(opp: dict) -> set[str]:
    """从掘金机会标题 + 摘要 + fit_reason 抽关键词 · 简陋版"""
    import re as _re
    title = (opp.get("title") or "")
    summary = (opp.get("summary") or "")
    fit_reason = (opp.get("fit_reason") or "")
    haystack = f"{title} {summary} {fit_reason}".lower()
    cn = _re.findall(r"[\u4e00-\u9fff]{2,}", haystack)
    en = [w.lower() for w in _re.findall(r"[a-zA-Z]{4,}", haystack)]
    return (set(cn) | set(en)) - _KEYWORD_STOP


def _find_relevant_radar_items(opp: dict, *, top_n: int = 6) -> list[dict]:
    """
    卷三十二补丁 · 雷达条目反查 · 给可行性分析当原始信源用。

    规则版：
      - opp 关键词 vs radar.title(_zh) + summary(_zh) 做包含匹配
      - 同领域 domain 加分
      - top_n 条按命中分数 → fetched_at 时间排序

    返回 list[dict] · 每条:
      { idx: 1, ref_id: "r1", title, url, source, source_display, domain, fetched_at,
        match_score, item_id (md5(url) 前 12) }
    """
    if not RADAR_FILE.exists():
        return []
    try:
        radar = json.loads(RADAR_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

    keywords = _extract_keywords(opp)
    if not keywords:
        return []
    opp_domain = (opp.get("domain") or "").lower()

    hits: list[tuple[int, dict]] = []
    for it in (radar.get("items") or []):
        title = ((it.get("title_zh") or "") + " " + (it.get("title") or "")).lower()
        summary = ((it.get("summary_zh") or "") + " " + (it.get("summary") or "")).lower()
        haystack = title + " " + summary
        score = sum(1 for kw in keywords if kw in haystack)
        if score == 0:
            continue
        if opp_domain and it.get("domain", "").lower() == opp_domain:
            score += 1
        hits.append((score, it))

    if not hits:
        return []

    # ISO 时间字符串字典序 = 时间序·所以两个键都用 reverse=True 一次搞定
    hits.sort(key=lambda x: (x[0], x[1].get("fetched_at") or ""), reverse=True)

    out: list[dict] = []
    for i, (score, it) in enumerate(hits[:top_n], 1):
        # 雷达条目稳定 id（跟 radar_feedback 共用规则）
        try:
            from workers.radar_feedback import item_id_for_url as _iid
            item_id = _iid(it.get("url") or "")
        except Exception:
            item_id = ""
        out.append({
            "idx": i,
            "ref_id": f"r{i}",
            "title": it.get("title_zh") or it.get("title") or "",
            "url": it.get("url") or "",
            "source": it.get("source") or "",
            "source_display": it.get("source_display") or it.get("source") or "",
            "domain": it.get("domain") or "",
            "fetched_at": it.get("fetched_at") or "",
            "match_score": score,
            "item_id": item_id,
        })
    return out


def _find_relevant_report_items(opp: dict, *, top_n: int = 3) -> list[dict]:
    """卷三十二补丁 · 报告反查 · 结构化版"""
    if not REPORTS_DIR.exists():
        return []
    keywords = _extract_keywords(opp)
    if not keywords:
        return []
    opp_domain = (opp.get("domain") or "").lower()

    hits: list[tuple[int, str, str, int]] = []
    for p in REPORTS_DIR.glob("*.docx"):
        if p.name.startswith("~$"):
            continue
        name_lower = p.name.lower()
        score = sum(1 for kw in keywords if kw in name_lower)
        if opp_domain and opp_domain in name_lower:
            score += 1
        if score == 0:
            continue
        try:
            mtime = int(p.stat().st_mtime)
        except OSError:
            mtime = 0
        hits.append((score, p.name, p.relative_to(ROOT).as_posix(), mtime))

    if not hits:
        return []
    hits.sort(key=lambda x: (-x[0], -x[3]))
    out: list[dict] = []
    for i, (score, name, relpath, mtime) in enumerate(hits[:top_n], 1):
        out.append({
            "idx": i,
            "ref_id": f"d{i}",
            "name": name,
            "relpath": relpath,
            "download_url": f"/reports/{name}",
            "match_score": score,
            "mtime": mtime,
        })
    return out


def _collect_sources(opp: dict) -> dict:
    """
    卷三十二补丁 · 一次性收齐"这次分析基于哪些原始信源"
    给 LLM prompt 看 + 落盘存档 + UI 渲染都用同一份。
    """
    radar_items = _find_relevant_radar_items(opp, top_n=6)
    report_items = _find_relevant_report_items(opp, top_n=3)
    return {
        "radar_items": radar_items,
        "reports": report_items,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "keyword_count": len(_extract_keywords(opp)),
    }


def _render_sources_prompt(sources: dict, opp: dict) -> str:
    """把 _collect_sources 的结构化数据渲染成 LLM prompt 文本块"""
    radar_items = sources.get("radar_items") or []
    reports = sources.get("reports") or []
    title = opp.get("title") or "?"

    if not radar_items and not reports:
        return (
            f"（这次分析没找到「{title[:40]}」相关的雷达条目 / 报告。**信源不足**——"
            "你应该在 verdict_reason 里直接说「建议先做 X 再回来分析」·不要硬编结论。）"
        )

    lines: list[str] = []
    lines.append(f"机会标题：{title}")
    lines.append(f"找到 {len(radar_items)} 条相关雷达条目 + {len(reports)} 份相关报告。")
    lines.append("**在 verdict_reason / swot.opportunities / swot.threats 引用编号**·"
                 "比如 'OpenAI 已发布 Cowork（参考 [r2]）' 或 '可参考报告 [d1]'。")
    lines.append("")

    if radar_items:
        lines.append("### 雷达条目（原始信号 · 引用 [r1] / [r2] ...）")
        for ri in radar_items:
            src = ri.get("source_display") or ri.get("source") or "?"
            t = (ri.get("title") or "")[:80]
            lines.append(
                f"- **[{ri['ref_id']}]** [{src}] {t}"
            )
        lines.append("")

    if reports:
        lines.append("### 同主题报告（客观市场背景 · 引用 [d1] / [d2] ...）")
        for rp in reports:
            lines.append(
                f"- **[{rp['ref_id']}]** {rp.get('name','?')} · `{rp.get('relpath','?')}`"
            )
        lines.append("")

    return "\n".join(lines)


def _find_relevant_reports(opp: dict, *, top_n: int = 3) -> str:
    """向后兼容 · 老接口·内部走新 _collect_sources"""
    sources = _collect_sources(opp)
    if not sources["radar_items"] and not sources["reports"]:
        return _render_sources_prompt(sources, opp)
    return _render_sources_prompt(sources, opp)


def _clean_str_list(value, *, cap: int = 6, max_chars: int = 200) -> list[str]:
    """LLM 返回的 list[str] · 防御性清洗 · 卷三十一 SWOT 用"""
    out: list[str] = []
    if not isinstance(value, list):
        return out
    for v in value[:cap]:
        if isinstance(v, str):
            s = v.strip()
            if s:
                out.append(s[:max_chars])
        elif isinstance(v, dict):
            # LLM 偶尔会嵌套字典 · flatten
            txt = v.get("text") or v.get("detail") or v.get("content") or ""
            s = str(txt).strip()
            if s:
                out.append(s[:max_chars])
    return out


def _load_opportunity_by_id(opp_id: str) -> Optional[dict]:
    """从 opportunities.json 找一个机会"""
    if not OPPORTUNITIES_FILE.exists():
        return None
    try:
        data = json.loads(OPPORTUNITIES_FILE.read_text(encoding="utf-8"))
        for opp in data.get("opportunities") or []:
            if opp.get("id") == opp_id:
                return opp
    except Exception as e:
        logger.warning("opportunities.json corrupt: %s", e)
    return None


def _load_bro_profile(max_chars: int = 3000) -> str:
    bro_file = ROOT / "soul" / "OWNER-NOTEBOOK.md"
    if not bro_file.exists():
        return "（OWNER-NOTEBOOK 还没同步 · 跑 sync-soul.ps1）"
    try:
        text = bro_file.read_text(encoding="utf-8")
    except Exception:
        return "（OWNER-NOTEBOOK 读不出来）"
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n…（已截断）"


_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json_obj(text: str) -> Optional[dict]:
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    m = _JSON_OBJ_RE.search(text)
    if m:
        try:
            parsed = json.loads(m.group(0))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return None


def analyze_feasibility(opp_id: str) -> dict:
    """跑一次完整可行性分析·写 data/feasibility/<opp_id>.json"""
    from daemon_runtime import RUNTIME

    if RUNTIME.client is None:
        return {
            "ok": False,
            "error": "RUNTIME.client 没初始化 · daemon 没启动？",
        }

    opp = _load_opportunity_by_id(opp_id)
    if not opp:
        return {
            "ok": False,
            "error": f"找不到掘金机会 id={opp_id} · "
                     f"先 mine_opportunities 跑一次再来",
        }

    bro = _load_bro_profile()
    next_steps_block = "\n".join(f"- {s}" for s in (opp.get("next_steps") or []))

    # 卷三十一 · 历史反馈 · 让 LLM 知道 用户 过去拒了哪些 / 哪些做完了
    try:
        from workers.outcomes import load_outcomes_for_prompt
        outcomes_block = load_outcomes_for_prompt(max_chars=1200)
    except Exception as e:
        logger.debug("load outcomes for prompt failed: %s", e)
        outcomes_block = "（暂无历史反馈）"

    # 卷三十三 · 同类执行反馈合并分析 · 用户 卷三十三 explicitly 要的"闭环深化"
    try:
        from workers.outcomes import (
            render_similar_outcomes_prompt as _render_similar,
        )
        similar_outcomes_block = _render_similar(opp, top_n=5)
    except Exception as e:
        logger.debug("render similar outcomes failed: %s", e)
        similar_outcomes_block = "（同类反馈匹配失败 · 当作首次走全闭环）"

    # 卷三十二补丁 · 收齐 sources（雷达条目 + 报告）·喂 prompt + 落盘 + 给 UI
    try:
        sources = _collect_sources(opp)
        sources_block = _render_sources_prompt(sources, opp)
    except Exception as e:
        logger.warning("collect sources failed: %s", e)
        sources = {"radar_items": [], "reports": [], "error": str(e)}
        sources_block = "（信源收集失败 · 没法对齐认知 · LLM 请明确说「信源不足」）"

    # 卷三十五补丁2 · inject learnings 教材 · 让 LLM 看到"高质量分析长啥样"
    try:
        from workers.learnings import render_learnings_block
        learnings_block = render_learnings_block(
            kinds=["model-comparison", "founder-thesis"],
            title="OPUS 历史沉淀的高质量分析样本",
            limit=2,
        )
    except Exception as e:
        logger.warning("render learnings failed: %s", e)
        learnings_block = "（教材加载失败 · LLM 自行发挥到正常深度即可）"

    # 卷三十五补丁3 · 跑一次 web_search · 把真实市场实证塞 prompt · 让 LLM 不空写市场
    try:
        from workers.fact_check import fetch_evidence_for_opp, render_evidence_block
        evidence = fetch_evidence_for_opp(opp, limit=5)
        evidence_block = render_evidence_block(
            evidence,
            title="市场实证 · web_search 拉的真实信源（卷三十五补丁3·LLM 必须 cite）",
        )
    except Exception as e:
        logger.warning("fetch evidence failed: %s", e)
        evidence_block = "(web_search 拉实证失败 · LLM 请明确标注「客观信源不足」)"

    # 卷三十五补丁3 · evidence 来自 web search · escape `{}` 防 .format 炸
    # learnings_block 已在 render_learnings_block 内部 safe_for_format · 不再重复
    evidence_block_safe = evidence_block.replace("{", "{{").replace("}", "}}")

    user_prompt = USER_PROMPT_TEMPLATE.format(
        title=opp.get("title", "?"),
        domain=opp.get("domain", "?"),
        summary=opp.get("summary", ""),
        fit=opp.get("fit", "?"),
        fit_reason=opp.get("fit_reason", ""),
        cost_effort=opp.get("cost_effort", "?"),
        upside=opp.get("upside", "?"),
        recommend=opp.get("recommend", 3),
        next_steps=next_steps_block or "（无）",
        bro_profile=bro,
        outcomes_block=outcomes_block,
        similar_outcomes_block=similar_outcomes_block,
        sources_block=sources_block,
        learnings_block=learnings_block,
        evidence_block=evidence_block_safe,
    )

    started = time.time()
    logger.info("analyze_feasibility: opp=%s · calling LLM", opp_id)

    raw_output = ""
    error: Optional[str] = None
    usage: dict = {}

    try:
        provider = RUNTIME.provider
        if provider == "anthropic":
            resp = RUNTIME.client.messages.create(
                model=RUNTIME.model,
                max_tokens=12000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            for block in resp.content:
                if getattr(block, "type", "") == "text":
                    raw_output += block.text
            try:
                usage = {
                    "input_tokens": getattr(resp.usage, "input_tokens", 0),
                    "output_tokens": getattr(resp.usage, "output_tokens", 0),
                }
            except Exception:
                pass
        else:
            resp = RUNTIME.client.chat.completions.create(
                model=RUNTIME.model,
                max_tokens=12000,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw_output = resp.choices[0].message.content or ""
            try:
                usage = {
                    "input_tokens": getattr(resp.usage, "prompt_tokens", 0),
                    "output_tokens": getattr(resp.usage, "completion_tokens", 0),
                }
            except Exception:
                pass
    except Exception as e:
        error = f"LLM call failed: {e}"
        logger.exception("analyze_feasibility LLM error")

    elapsed_ms = int((time.time() - started) * 1000)

    parsed = _extract_json_obj(raw_output)
    if not parsed:
        return {
            "ok": False,
            "opp_id": opp_id,
            "opp_title": opp.get("title"),
            "error": error or "LLM 输出解析失败",
            "raw_output": raw_output[:2000],
            "elapsed_ms": elapsed_ms,
        }

    # 规整化关键字段
    try:
        score = int(parsed.get("feasibility_score", 50))
    except (TypeError, ValueError):
        score = 50
    score = max(0, min(100, score))

    verdict = (parsed.get("verdict") or "wait").strip().lower()
    if verdict not in {"go", "conditional", "wait", "skip"}:
        verdict = "wait"

    # 卷三十一 · 规整化 SWOT / 未来预期 / 成功路径
    swot_raw = parsed.get("swot") or {}
    swot = {
        "strengths": _clean_str_list(swot_raw.get("strengths"), cap=6),
        "weaknesses": _clean_str_list(swot_raw.get("weaknesses"), cap=6),
        "opportunities": _clean_str_list(swot_raw.get("opportunities"), cap=6),
        "threats": _clean_str_list(swot_raw.get("threats"), cap=6),
    }
    outlook_raw = parsed.get("future_outlook") or {}
    future_outlook = {
        "three_months": (outlook_raw.get("three_months") or "").strip()[:500],
        "six_months": (outlook_raw.get("six_months") or "").strip()[:500],
        "one_year": (outlook_raw.get("one_year") or "").strip()[:500],
    }
    path_raw = parsed.get("success_path") or {}
    stages: list[dict] = []
    for st in (path_raw.get("stages") or [])[:8]:
        if not isinstance(st, dict):
            continue
        stages.append({
            "name": (st.get("name") or "").strip()[:60],
            "milestone": (st.get("milestone") or "").strip()[:200],
            "criteria": (st.get("criteria") or "").strip()[:200],
            "weeks": str(st.get("weeks") or "").strip()[:30],
        })
    success_path = {
        "stages": stages,
        "end_state": (path_raw.get("end_state") or "").strip()[:400],
    }

    payload = {
        "ok": True,
        "opp_id": opp_id,
        "opp_title": opp.get("title"),
        "opp_domain": opp.get("domain"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_ms": elapsed_ms,
        "model": RUNTIME.model,
        "usage": usage,
        "feasibility_score": score,
        "verdict": verdict,
        "verdict_reason": (parsed.get("verdict_reason") or "").strip()[:300],
        "risks": parsed.get("risks") or [],
        "swot": swot,
        "future_outlook": future_outlook,
        "success_path": success_path,
        "resources_have": parsed.get("resources_have") or [],
        "resources_need": parsed.get("resources_need") or [],
        "capability_match": parsed.get("capability_match") or [],
        "cost_breakdown": parsed.get("cost_breakdown") or {},
        "alternatives": parsed.get("alternatives") or [],
        "first_30_min": (parsed.get("first_30_min") or "").strip(),
        "go_no_go": (parsed.get("go_no_go") or "").strip(),
        # 卷三十二补丁 · 信源（人机认知对齐 · 宪法第 5 条）
        "sources": sources,
        # 卷三十五补丁3 · web_search 拉的真实市场实证 · 让 用户 能跳到原文核对
        "evidence": evidence if isinstance(evidence, dict) else {"ok": False, "results": []},
    }

    out_file = FEASIBILITY_DIR / f"{opp_id}.json"
    _atomic_write(out_file, json.dumps(payload, ensure_ascii=False, indent=2))
    logger.info(
        "analyze_feasibility done · opp=%s · score=%d verdict=%s · %dms",
        opp_id, score, verdict, elapsed_ms,
    )
    return payload


def list_feasibility(*, max_items: int = 30) -> dict:
    """列出所有已分析的机会·按生成时间倒序·附带 outcomes 状态（卷三十一）"""
    # 拉一次所有 outcomes · 关联到 feasibility 列表上
    outcomes_map: dict[str, dict] = {}
    try:
        from workers.outcomes import list_outcomes
        for o in list_outcomes().get("items") or []:
            outcomes_map[o.get("opp_id")] = o
    except Exception as e:
        logger.debug("list_outcomes failed: %s", e)

    items: list[dict] = []
    if FEASIBILITY_DIR.exists():
        for f in FEASIBILITY_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                opp_id = data.get("opp_id", f.stem)
                outcome = outcomes_map.get(opp_id) or {}
                items.append({
                    "opp_id": opp_id,
                    "opp_title": data.get("opp_title", "?"),
                    "opp_domain": data.get("opp_domain", "?"),
                    "feasibility_score": data.get("feasibility_score", 0),
                    "verdict": data.get("verdict", "?"),
                    "verdict_reason": data.get("verdict_reason", ""),
                    "generated_at": data.get("generated_at", ""),
                    "status": outcome.get("status") or "not_started",
                    "status_updated_at": outcome.get("updated_at") or "",
                })
            except Exception as e:
                logger.warning("feasibility file %s corrupt: %s", f.name, e)
    items.sort(key=lambda x: x.get("generated_at", ""), reverse=True)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(items),
        "items": items[:max_items],
    }


def load_feasibility(opp_id: str) -> Optional[dict]:
    """读单个机会的可行性分析·附 outcome（卷三十一）+ 懒收集 sources（卷三十二补丁）"""
    f = FEASIBILITY_DIR / f"{opp_id}.json"
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("load feasibility %s failed: %s", opp_id, e)
        return None

    # 附加 outcome 闭环数据
    try:
        from workers.outcomes import load_outcome
        outcome = load_outcome(opp_id)
        if outcome:
            data["outcome"] = outcome
    except Exception:
        pass

    # 卷三十二补丁 · 老数据没 sources 字段·load 时懒收集一份（不重跑 LLM·只 keyword match）
    # 这样 用户 不必重新触发分析就能立刻看到信源
    if not data.get("sources"):
        try:
            opp_stub = {
                "title": data.get("opp_title") or "",
                "summary": data.get("verdict_reason") or "",
                "domain": data.get("opp_domain") or "",
            }
            data["sources"] = _collect_sources(opp_stub)
            data["sources"]["_lazy_collected"] = True  # 标识"这是事后补的·不是 LLM 看到的那一份"
        except Exception as e:
            logger.debug("lazy collect sources for %s failed: %s", opp_id, e)

    return data
