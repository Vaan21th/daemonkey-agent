"""
workers/softness_score.py
=========================

卷三十二 · 雷达条目"软文嫌疑度"评估（规则版 · 卷三十三可加 LLM 版）

为什么需要这玩意：
  雷达里抓回来的资讯·有真新闻·也有"震惊·这个 AI 工具吊打 ChatGPT"这种营销稿。
  用户时间宝贵·要让"硬信号"排在前面·把软文压到底部。

评分维度：
  1. 标题特征（最强信号·中英文双侧）
     - 中文: "震惊/必看/最强/吊打/秒杀/万人/疯狂/重磅/逆天/惊艳/暴击/赢麻"
     - 英文: "you won't believe / shocked / amazing / mind-blown / game-changing / revolutionary / ultimate"
     - 数字钓鱼: "10x / 100x / N 倍" + 形容词组合
     - 反问钓鱼: "为什么 X 这么 Y / how X is destroying Y"

  2. 信源历史（BRO 反馈反哺）
     - workers.radar_feedback.source_negative_score(source) > 0 → 加分

  3. 内容长度（极短摘要 + 标题党 = 高软文嫌疑）

  4. 链接形态（utm_source / utm_campaign / 短链跳转）

输出三档：low / medium / high
  - low (默认 · 0-2 分) · 真新闻 / 技术文章
  - medium (3-5 分)     · 标题略夸张·内容仍有信号
  - high (6+ 分)        · 大概率软文·UI 上压到底部

排序使用：
  workers.radar_sort.sort_items() 会把 high 排到最后·low 排到最前
  （但 starred / thumbs_up 永远不被压到 high 后面）

红线：
  - 这是规则版 · 不调 LLM · 不消耗 token
  - 评分函数是纯函数·不读盘（除了 source_negative_score 间接读 radar_feedback）
"""
from __future__ import annotations

import logging
import re
from typing import Iterable

logger = logging.getLogger("opus.softness")

# 中文标题党词汇（高强度信号）
_CN_HARD = [
    "震惊", "必看", "最强", "最牛", "吊打", "秒杀", "万人", "疯狂",
    "重磅", "逆天", "惊艳", "暴击", "赢麻", "封神", "屠榜", "炸裂",
    "颠覆", "王炸", "硬刚", "全网", "神操作", "天花板", "yyds",
]

# 英文标题党
_EN_HARD = [
    r"\byou won['’]t believe\b",
    r"\bshocked\b", r"\bshocking\b",
    r"\bmind[- ]?blow", r"\bmind[- ]?blown\b",
    r"\bgame[- ]changing\b", r"\brevolutionary\b",
    r"\bultimate\b", r"\bjaw[- ]?drop",
    r"\bthis is why\b.*\bso\b",
    r"\bhow .* is (?:destroying|killing|breaking)\b",
]

_EN_HARD_RE = re.compile("|".join(_EN_HARD), re.IGNORECASE)

# "10x / 100 倍 / 7 fold" 等夸张数字
_HYPE_NUM_RE = re.compile(
    r"(?:\b\d{2,}\s*[xX×倍倍数]\b|\b(?:十|百|千|万|百万)倍\b|\b\d+\s*-?\s*fold\b)"
)

# UTM / 营销链接
_AD_URL_RE = re.compile(
    r"utm_source|utm_campaign|utm_medium|fbclid|gclid|wechat_redirect",
    re.IGNORECASE,
)


def score_text(text: str) -> int:
    """对一段文本（标题或标题+摘要）打软文分·0-N 整数"""
    if not text:
        return 0
    t = text.strip()
    score = 0
    # 中文 hard 词
    for w in _CN_HARD:
        if w in t:
            score += 2
            break  # 一个就够 · 不重复加
    # 多个中文 hard 词 → 再加
    cn_hits = sum(1 for w in _CN_HARD if w in t)
    if cn_hits >= 2:
        score += 2
    # 英文 hard 词
    if _EN_HARD_RE.search(t):
        score += 2
    # 夸张数字
    if _HYPE_NUM_RE.search(t):
        score += 1
    # 标点：!! / ！！ / ？？ 多重感叹疑问
    if re.search(r"[!！?？]{2,}", t):
        score += 1
    # 过度大写英文（>=4 个连续大写词）
    if re.search(r"\b[A-Z]{4,}\b.*\b[A-Z]{4,}\b", t):
        score += 1
    return score


def score_url(url: str) -> int:
    if not url:
        return 0
    if _AD_URL_RE.search(url):
        return 2
    return 0


def softness_score(item: dict) -> dict:
    """
    给一条 radar item 算软文分·返回:
      {
        "score": int,
        "level": "low|medium|high",
        "signals": [触发了哪些规则]
      }
    """
    title = (item.get("title_zh") or "") + " " + (item.get("title") or "")
    summary = (item.get("summary_zh") or "") + " " + (item.get("summary") or "")
    url = item.get("url") or ""
    source = item.get("source") or ""

    signals: list[str] = []
    score = 0

    title_score = score_text(title)
    if title_score:
        score += title_score
        if title_score >= 2:
            signals.append("clickbait_title")

    summary_score = score_text(summary)
    if summary_score:
        score += summary_score
        if summary_score >= 2:
            signals.append("clickbait_summary")

    if _HYPE_NUM_RE.search(title + " " + summary):
        if "clickbait_title" not in signals and "clickbait_summary" not in signals:
            signals.append("hype_number")

    url_score = score_url(url)
    if url_score:
        score += url_score
        signals.append("tracking_url")

    # 信源负面历史（BRO 已经踩过的源）
    try:
        from workers.radar_feedback import source_negative_score
        neg = source_negative_score(source)
        if neg >= 1:
            extra = min(neg, 3)
            score += extra
            signals.append(f"source_thumbs_down_x{neg}")
    except Exception:
        pass

    # 极短摘要 + 强标题党 = 加重
    if "clickbait_title" in signals and len((item.get("summary") or "").strip()) < 30:
        score += 1
        signals.append("empty_body_clickbait_title")

    if score >= 6:
        level = "high"
    elif score >= 3:
        level = "medium"
    else:
        level = "low"

    return {"score": score, "level": level, "signals": signals}


def annotate_items(items: Iterable[dict]) -> list[dict]:
    """批量给 items 加 softness 字段·返回新列表（不破坏原数据·只 shallow copy）"""
    out: list[dict] = []
    for it in items:
        new = dict(it)
        new["softness"] = softness_score(it)
        out.append(new)
    return out


def sort_items(items: Iterable[dict]) -> list[dict]:
    """
    雷达排序规则（卷三十二）：
      1. starred 永远第一
      2. thumbs_up 第二档
      3. low 软文 第三档
      4. medium 软文 第四档
      5. high 软文 最后（除非 starred/thumbs_up）
      6. hidden 不进列表（调用方应该已经过滤）

    同档内按 fetched_at 倒序。
    """
    from workers.radar_feedback import feedback_map
    fb = feedback_map()
    from workers.radar_feedback import item_id_for_url

    def rank(it: dict) -> tuple:
        iid = item_id_for_url(it.get("url") or "")
        fb_entry = fb.get(iid) or {}
        f = fb_entry.get("feedback")
        soft = it.get("softness") or softness_score(it)

        if f == "starred":
            tier = 0
        elif f == "thumbs_up":
            tier = 1
        elif soft["level"] == "low":
            tier = 2
        elif soft["level"] == "medium":
            tier = 3
        else:
            tier = 4

        # fetched_at 越新越靠前 (用负值 · tuple 升序)
        fetched = it.get("fetched_at") or ""
        return (tier, _neg_str(fetched))

    return sorted(items, key=rank)


def _neg_str(s: str) -> tuple:
    """ISO 时间字符串 → 可作为排序 key 的负向元组（越新值越小）"""
    return tuple(-ord(c) for c in (s or ""))
