"""
workers/opportunity_miner.py
=============================

卷二十八 · 掘金机会引擎

目标：把"市场信号(雷达/趋势) × 用户 能力画像(OWNER-NOTEBOOK)"做交叉·
找出对 用户 这个**超级个体**最值得切入的掘金点·并给出可操作建议。

输出 schema（每个机会卡）：
  - id           · 稳定 id (基于 title hash)
  - title        · 短标题 12-25 字
  - domain       · 关联领域 (取自雷达 DOMAIN_META · 用户自己挖出来的方向)
  - summary      · 50-150 字 · 说清楚是什么机会 / 为什么是机会
  - fit          · 用户 适配度 (yes / maybe / no)
  - fit_reason   · 30-80 字 · 引用 用户 画像具体内容 · 说明匹配/不匹配原因
  - cost_effort  · 投入预估 (light / moderate / heavy)
  - upside       · 收益级别 (low / medium / high)
  - recommend    · 推荐度 (1-5)
  - next_steps   · 数组 · 2-4 个具体可执行的下一步
  - source_refs  · 趋势/雷达条目引用列表

数据流：
  trends.json + radar.json + OWNER-NOTEBOOK.md
    ↓ LLM 一次
  data/opportunities.json
    ↓
  /dashboard/opportunities → UI BI 看板 / 💎 维度

红线：
  - LLM 失败 → 返回 stub · 不让前端崩
  - 只写 data/opportunities.json · 不动其他
  - 一次调用 cap 5 个机会 · 避免 token 飙升
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# 兜底领域 & 主人画像笔记路径都是【实例配置】·解析在 identity.py 单一真源。
try:
    from identity import default_domain as _default_domain
    from identity import owner_notebook_path as _owner_notebook_path
except Exception:
    def _default_domain():
        return "ai"

    def _owner_notebook_path(soul_dir):
        return Path(soul_dir) / "BRO-NOTEBOOK.md"

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
OPPORTUNITIES_FILE = DATA_DIR / "opportunities.json"
TRENDS_FILE = DATA_DIR / "trends.json"
RADAR_FILE = DATA_DIR / "radar.json"

logger = logging.getLogger("opus.opportunity")


SYSTEM_PROMPT = """你是用户的 AI 搭档。你的任务不是给"市场趋势综述"——而是基于用户这个具体的人·从最新趋势里挑出**他能切的掘金点**。

你不是通用投资人 / 教练 / 通用 AI——你是知道用户完整画像的搭档。给出的建议必须扎根在用户的实际能力 / 状态 / 资源上·不是教科书答案。

**[跟着用户这个人来 · 必读]**

不要把用户当通用"想赚钱的人"·更不要假设他是程序员 / 创业者——他可能是任何人。你要做的是：
- 看用户的画像 / 反馈历史 / outcomes / 收藏 / 打标 → 提炼用户在市场里**特殊的位置**
- 从趋势里挑那些**只有用户这种位置的人能切的点**——而不是"任何人都能切"的赛道
- 给建议时·**让用户看到他自己的能力切片** —— 类似"你已经在 X 表现出 Y 能力·所以这个机会的 fit 是 90"

**[机会形态全谱 · 重要]**

掘金机会**绝对不局限于"做软件 / 写代码"**——是一切有可能赚钱的点。

你应该从下面**至少 3 种**形态里去找机会·不要全堆在"做产品"一类：

1. **内容账号** · 公众号 / 视频号 / B 站 / 小红书 / 抖音 / 即刻 / X / 知识星球 · 一类账号 = 一条赛道
2. **实体产品** · 找工厂代工 / 1688 选品 / 跨境电商 / D2C 自营 · 信息差就是钱
3. **服务 / 咨询** · 教程 / 一对一辅导 / 代运营 / 定制开发外包 / 私域社群
4. **信息差套利** · 撮合 / 中介 / 收藏品 / 二手 / 跨平台搬运 · 不创造内容只搬运
5. **软件产品** · SaaS / 浏览器扩展 / GPT App / 工具站
6. **投资 / 副业组合** · 长期持有 / 套利 / 学习投资某种技能

**选择哪种形态·取决于**：
- 信息雷达里用户自己关注的类目（domain）—— 顺着他真正在追的方向来，别硬塞他没关注的领域
- 用户 画像 —— 他真的擅长写代码就推软件·他有内容感就推账号·他时间紧就推套利
- 趋势的"赚钱机制"—— 不是所有趋势都靠写代码变现·有些趋势就靠"早卡位 + 内容"赚

**你必须在输出的 opportunities 里·让形态多样化**——不能 5 个全是"做个 SaaS"。

**[事实较量红线]**

在 summary / fit_reason 里写"市场已有 X" / "竞品做了 Y" / "用户规模 Z" 这种**事实陈述**时·
**必须诚实**：除非趋势 block 里有原文佐证·否则用"据公开信息"/"参考信号"等模糊措辞·
**不要凭印象编造具体数字 / 项目名 / 用户量**。可信度 > 完美感。

**[深度]**

用户消息里附 `## 教材` 段·是历史沉淀的高质量分析样本·
你输出的 summary / fit_reason 应该达到那个深度——挑战既有结论 / 给反例 / 不当 cheerleader。"""


USER_PROMPT_TEMPLATE = """## 用户 当下画像摘要

{bro_profile}

---

## 用户历史反馈（拒做 / 已完成的机会）

{outcomes_block}

---

## 用户在雷达条目上的打标（👎 是最值钱的负反馈）

{radar_feedback_block}

---

## 最新趋势 / 雷达信号（按 intensity 排）

{trends_block}

---

## 教材 · 历史沉淀的高质量分析样本

{learnings_block}

---

## 任务

从上面挑出 **3-5 个** 用户 最值得动手的掘金点。

**严格 JSON 数组输出**·不要 markdown 包裹·不要任何前后解释：

```json
[
  {{
    "title": "短标题 · 12-25 字 · 一眼看清是干什么",
    "domain": "从下面雷达条目里实际出现的 domain 里挑一个最贴的·拿不准就填 self-evolve",
    "summary": "50-150 字 · 说清这是什么机会 + 为什么是 用户 该切的而不是任意人都该切的",
    "fit": "yes|maybe|no · 用户 能不能干",
    "fit_reason": "30-80 字 · **引用 用户 画像具体段** · 比如 '画像 §3 说他有 5 年 LLM 项目经验·这事正好接得上' / '画像 §6 说他对 react native 不熟·要做 app 得先补两周课'",
    "cost_effort": "light|moderate|heavy · light=半天-3天 / moderate=1-2周 / heavy=1月+",
    "upside": "low|medium|high · low=自己玩 / medium=兴趣副业 / high=可能撑起一条线",
    "recommend": 1-5 整数 · 1=不推荐 / 5=强烈推荐立刻动手,
    "next_steps": ["第一步该干什么", "第二步", "..."],
    "trend_refs": [对应的 trend 标题数组],

    "estimated_hours": "数字范围 · 比如 '8-16' / '40-80' / '120+' · 上线第一版要多少小时",
    "estimated_token_cost_usd": "数字范围 · 比如 '5-20' / '50-200' / '500+' · 开发期 + 运营前 3 个月的 LLM token 估算·没用 LLM 就写 '0'",
    "revenue_range_cny": "区间字符串 · 比如 '¥0-500/月' / '¥1k-5k/月' / '¥10k+/月' / '一次性 ¥X' · 月经常性收入或一次性收入",
    "sales_channels": ["销售渠道数组 · 比如 '微信群' / '小红书' / '即刻' / 'Reddit' / 'X' / '1688' / 'B 站' / '私域' / '代理分销' · 列 2-4 个最契合的"],
    "resources_needed": ["所需资源数组 · 比如 'GPU·5090×1' / '代工厂' / '初始货款 ¥2k' / '小红书号' / 'API 配额' · 列 2-4 个最关键的"],
    "skill_match_score": 0-100 整数 · 用户 当前能力跟所需能力的契合度·结合 fit_reason 给的具体段·100=完全匹配 / 60=能干但有学习成本 / 30=缺核心能力 / 0=干不了
  }}
]
```

## 重要要求

1. **拒绝"通用建议"**——"做个 AI 工具" 是废话·要具体到"做一个 X 给 Y 解决 Z"
2. **fit_reason 必须引用画像具体段**·不能写"用户 适合"这种空话
3. **recommend 5 留给真正"现在不动手就晚"**·大多数应该 3-4
4. **next_steps 必须可执行**——不是"调研市场"·而是"今晚花 2 小时跑 X 命令看 Y 数据"
5. **别只盯一个领域**——用户关注好几个方向时·各领域的好机会都要挑进来·形态也要多样
6. **不忌讳告诉 用户 "不适合做"**——fit=no 的机会也可以列·但要说清原因
7. **看历史反馈**——如果 用户 之前拒过类似机会（abandoned）·别原样再推一遍·要么换角度·要么标 fit=no·并在 fit_reason 里说"上次 用户 因为 X 拒了·这次因为 Y 不一样"
8. **卷三十四新增 6 字段必须填**·别留空·宁可粗估也要给数字·用户 是工程师·他要的是可比较的数字而不是"中等"
9. **self-evolve 域的机会**·特指 OPUS 自己装修自己的活——比如 "把 OpenHands 那个 X 能力移植到本工程"·这种机会 用户 几乎一定能做（因为他正在改这个工程）·skill_match_score 可以打 85+

不要输出超过 5 个。质量比数量重要。"""


def _atomic_write(path: Path, text: str) -> None:
    """同进程原子写——卷四十六 III · wish-badd4 收编到 safe_write
    opportunities.json 是 用户 决策辅助核心数据·backup=True 保险"""
    from .safe_write import atomic_write_text
    atomic_write_text(path, text, backup=True)


def _load_trends(top_n: int = 20) -> list[dict]:
    """读 trends.json · 取 intensity 高的 top_n 条"""
    if not TRENDS_FILE.exists():
        return []
    try:
        data = json.loads(TRENDS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("trends.json corrupt: %s", e)
        return []
    trends = data.get("trends") or []
    trends_sorted = sorted(
        trends,
        key=lambda t: int(t.get("intensity", 3) or 3),
        reverse=True,
    )
    return trends_sorted[:top_n]


def _load_bro_profile(max_chars: int = 3500) -> str:
    """读 soul/OWNER-NOTEBOOK.md · 截前 max_chars 字符（要点都在前面）"""
    bro_file = _owner_notebook_path(ROOT / "soul")
    if not bro_file.exists():
        return "（OWNER-NOTEBOOK 还没同步 · 跑 sync-soul.ps1）"
    try:
        text = bro_file.read_text(encoding="utf-8")
    except Exception:
        return "（OWNER-NOTEBOOK 读不出来）"
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n…（已截断 · 完整画像在 soul/OWNER-NOTEBOOK.md）"


def _render_trends_block(trends: list[dict]) -> str:
    """把 trends 渲染成 LLM 易读的清单"""
    if not trends:
        return "（雷达里还没攒到趋势 · 这次只看现有信号给一些方向性的建议）"
    lines: list[str] = []
    for i, t in enumerate(trends, 1):
        intensity = t.get("intensity", 3)
        angles = t.get("angles") or []
        angles_str = "/".join(angles) if angles else "未标"
        lines.append(
            f"[{i}] 强度{intensity}·切入={angles_str}·{t.get('title', '?')}"
        )
        summary = (t.get("summary") or "").strip()
        if summary:
            lines.append(f"    {summary}")
        refs = t.get("refs") or []
        if refs:
            ref_titles = " | ".join(
                (r.get("title") or "")[:50] for r in refs[:3]
            )
            lines.append(f"    信源: {ref_titles}")
        lines.append("")
    return "\n".join(lines)


def _stable_id(title: str, domain: str) -> str:
    """根据 title + domain 算个稳定 id · 同样输入永远同样 id · 方便去重"""
    h = hashlib.md5(f"{domain}::{title}".encode("utf-8")).hexdigest()[:10]
    return f"opp-{h}"


_JSON_ARRAY_RE = re.compile(r"\[\s*\{.*?\}\s*\]", re.DOTALL)


def _extract_json_array(text: str) -> list:
    """从 LLM 文本里抠出 JSON 数组 · 失败返回空 list"""
    if not text:
        return []
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass
    m = _JSON_ARRAY_RE.search(text)
    if m:
        try:
            parsed = json.loads(m.group(0))
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
    return []


# domain 不再写死——以雷达当前实际存在的领域（DOMAIN_META）为准，按用户自己挖出来的来
_VALID_FIT = {"yes", "maybe", "no"}
_VALID_EFFORT = {"light", "moderate", "heavy"}
_VALID_UPSIDE = {"low", "medium", "high"}


def _normalize_opportunity(raw: dict, trends: list[dict]) -> Optional[dict]:
    """把 LLM 一条原始输出规整成稳定 schema · 不合格返回 None"""
    if not isinstance(raw, dict):
        return None
    title = (raw.get("title") or "").strip()
    summary = (raw.get("summary") or "").strip()
    if not (title and summary):
        return None

    domain = (raw.get("domain") or _default_domain()).strip().lower()
    try:
        from workers.info_radar import DOMAIN_META as _DM
        if domain not in _DM:
            domain = "self-evolve"
    except Exception:
        pass

    fit = (raw.get("fit") or "maybe").strip().lower()
    if fit not in _VALID_FIT:
        fit = "maybe"

    effort = (raw.get("cost_effort") or raw.get("effort") or "moderate").strip().lower()
    if effort not in _VALID_EFFORT:
        effort = "moderate"

    upside = (raw.get("upside") or "medium").strip().lower()
    if upside not in _VALID_UPSIDE:
        upside = "medium"

    try:
        recommend = int(raw.get("recommend", 3))
    except (TypeError, ValueError):
        recommend = 3
    recommend = max(1, min(5, recommend))

    next_steps_raw = raw.get("next_steps") or []
    next_steps: list[str] = []
    if isinstance(next_steps_raw, list):
        for s in next_steps_raw[:5]:
            if isinstance(s, str) and s.strip():
                next_steps.append(s.strip())

    # trend_refs · LLM 可能给标题数组也可能给 index · 我们都接
    trend_refs_raw = raw.get("trend_refs") or raw.get("refs") or []
    trend_refs: list[dict] = []
    if isinstance(trend_refs_raw, list):
        for ref in trend_refs_raw[:5]:
            if isinstance(ref, str):
                # 按 title 模糊匹配
                ref_lower = ref.strip().lower()
                for t in trends:
                    if (t.get("title") or "").lower().strip() in ref_lower or \
                       ref_lower in (t.get("title") or "").lower().strip():
                        trend_refs.append({
                            "title": t.get("title", ""),
                            "intensity": t.get("intensity", 3),
                        })
                        break
            elif isinstance(ref, int):
                if 1 <= ref <= len(trends):
                    t = trends[ref - 1]
                    trend_refs.append({
                        "title": t.get("title", ""),
                        "intensity": t.get("intensity", 3),
                    })

    # 卷三十四新字段 · 6 个评估维度
    estimated_hours = (raw.get("estimated_hours") or "").strip()
    estimated_token = (raw.get("estimated_token_cost_usd") or "").strip()
    revenue_range = (raw.get("revenue_range_cny") or "").strip()

    def _str_list(v, limit=6, maxlen=40):
        if not isinstance(v, list):
            return []
        out = []
        for x in v[:limit]:
            if isinstance(x, str) and x.strip():
                out.append(x.strip()[:maxlen])
        return out

    sales_channels = _str_list(raw.get("sales_channels"))
    resources_needed = _str_list(raw.get("resources_needed"))

    try:
        skill_match = int(raw.get("skill_match_score", 60))
    except (TypeError, ValueError):
        skill_match = 60
    skill_match = max(0, min(100, skill_match))

    return {
        "id": _stable_id(title, domain),
        "title": title,
        "domain": domain,
        "summary": summary,
        "fit": fit,
        "fit_reason": (raw.get("fit_reason") or "").strip()[:300],
        "cost_effort": effort,
        "upside": upside,
        "recommend": recommend,
        "next_steps": next_steps,
        "trend_refs": trend_refs,
        # 卷三十四新字段
        "estimated_hours": estimated_hours[:30],
        "estimated_token_cost_usd": estimated_token[:30],
        "revenue_range_cny": revenue_range[:40],
        "sales_channels": sales_channels,
        "resources_needed": resources_needed,
        "skill_match_score": skill_match,
    }


def mine_opportunities(*, top_n_trends: int = 15) -> dict:
    """跑一次完整掘金机会发现·写 data/opportunities.json·返回汇总"""
    from daemon_runtime import RUNTIME

    if RUNTIME.client is None:
        return {
            "generated_at": None,
            "opportunities": [],
            "error": "RUNTIME.client 没初始化 · daemon 没启动？",
        }

    trends = _load_trends(top_n=top_n_trends)
    bro = _load_bro_profile()

    # 卷三十一 · 把 用户 历史反馈塞进 prompt · 避免重蹈覆辙
    try:
        from workers.outcomes import load_outcomes_for_prompt
        outcomes_block = load_outcomes_for_prompt(max_chars=1000)
    except Exception as e:
        logger.debug("load outcomes for prompt failed: %s", e)
        outcomes_block = "（暂无历史反馈）"

    # 卷三十二 · 雷达条目打标反馈 · 比 outcomes 粒度更细
    try:
        from workers.radar_feedback import load_for_prompt as _fb_prompt
        radar_feedback_block = _fb_prompt(max_chars=1000)
    except Exception as e:
        logger.debug("load radar_feedback for prompt failed: %s", e)
        radar_feedback_block = "（暂无打标历史）"

    try:
        from workers.learnings import render_learnings_block
        learnings_block = render_learnings_block(
            kinds=["founder-thesis", "model-comparison"],
            title="OPUS 历史沉淀的高质量分析样本",
            limit=2,
        )
    except Exception as e:
        logger.warning("render learnings failed: %s", e)
        learnings_block = "（教材加载失败 · LLM 自行发挥到正常深度即可）"

    user_prompt = USER_PROMPT_TEMPLATE.format(
        bro_profile=bro,
        outcomes_block=outcomes_block,
        radar_feedback_block=radar_feedback_block,
        trends_block=_render_trends_block(trends),
        learnings_block=learnings_block,
    )

    started = time.time()
    logger.info("mine_opportunities: calling LLM with %d trends", len(trends))

    raw_output = ""
    error: Optional[str] = None
    usage: dict = {}

    try:
        from daemon_runtime import bg_max_tokens
        provider = RUNTIME.provider
        _bg_mt = bg_max_tokens()
        if provider == "anthropic":
            resp = RUNTIME.client.messages.create(
                model=RUNTIME.model,
                max_tokens=_bg_mt,
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
                max_tokens=_bg_mt,
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
        logger.exception("mine_opportunities LLM error")

    elapsed_ms = int((time.time() - started) * 1000)

    parsed = _extract_json_array(raw_output)
    opportunities: list[dict] = []
    if parsed:
        for raw in parsed:
            norm = _normalize_opportunity(raw, trends)
            if norm:
                opportunities.append(norm)
    opportunities.sort(key=lambda o: o.get("recommend", 0), reverse=True)
    opportunities = opportunities[:5]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_ms": elapsed_ms,
        "trends_scanned": len(trends),
        "model": RUNTIME.model,
        "opportunities": opportunities,
        "usage": usage,
    }
    if error:
        payload["error"] = error
    if not opportunities:
        payload["raw_output"] = raw_output[:2000]
        payload["note"] = (
            "LLM 解析失败 · raw_output 留作调试。"
            "常见原因 (1) JSON 格式不合法 (2) trends 太少没法挖出有意义的机会"
        )

    _atomic_write(
        OPPORTUNITIES_FILE,
        json.dumps(payload, ensure_ascii=False, indent=2),
    )
    logger.info(
        "mine_opportunities done · %d opportunities · %dms · usage=%s",
        len(opportunities),
        elapsed_ms,
        usage,
    )
    return payload


def load_opportunities() -> dict:
    """给 /dashboard/opportunities 用 · 读 data/opportunities.json"""
    if not OPPORTUNITIES_FILE.exists():
        return {
            "generated_at": None,
            "opportunities": [],
            "note": "还没跑过掘金挖掘 · 用 NLP 跟 OPUS 说'挖一下机会' 或 'mine opportunities'",
        }
    try:
        return json.loads(OPPORTUNITIES_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        return {
            "generated_at": None,
            "opportunities": [],
            "error": f"opportunities.json corrupt: {e}",
        }


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO)

    from daemon_runtime import RUNTIME

    if RUNTIME.client is None:
        try:
            import anthropic

            key = os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                print("[err] ANTHROPIC_API_KEY 没设")
                raise SystemExit(1)
            RUNTIME.client = anthropic.Anthropic(api_key=key)
            RUNTIME.provider = "anthropic"
            RUNTIME.model = os.environ.get("OPUS_MODEL", "claude-opus-4-20250514")
        except ImportError:
            print("[err] anthropic 包没装")
            raise SystemExit(1)

    result = mine_opportunities()
    print(json.dumps(result, ensure_ascii=False, indent=2))
