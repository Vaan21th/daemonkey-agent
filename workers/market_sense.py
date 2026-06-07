"""
workers/market_sense.py
=======================

卷三十二 · 市场感知 · 骨架（完整实现推卷三十三）

目标：抓取**其他超级个体 / 真实用户的市场反应**·喂给：
  - 报告 (`generate_report`)·当客观市场背景
  - 可行性分析 (`feasibility_analyzer`)·当 "实际用户怎么看" 维度

数据源（卷三十三规划·这里只留 docstring）：
  - 知乎评论
  - V2EX 帖子 + 评论
  - HN comments thread
  - 即刻 / 小红书 / 抖音 评论（需要 anti-bot 投入·先 defer）
  - Reddit comments

数据形态：
  data/market_sense/<topic_slug>__<YYYYMMDD>.json
    {
      "topic": "...",
      "captured_at": "...",
      "comments": [
        {"source": "zhihu|hn|v2ex|...", "url": "...", "author": "...",
         "content": "...", "upvote": 0, "sentiment": "positive|neutral|negative"}
      ]
    }

为什么先留骨架：
  评论爬取是 anti-bot 高危区·每个站都要单独适配·一次性塞进卷三十二 scope creep
  卷三十二的核心是"BRO 闭环反馈" + "报告/可行性边界"——市场感知作为下一卷主菜。

红线：
  - 不爬需要登录的内容
  - User-Agent 标识自己 (OPUS-DAEMON-MarketSense)
  - 单站请求间隔 ≥ 2s
  - 评论数据**只读**给 LLM 做背景·不做 BI 分析（那是 BRO 的事）
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "market_sense"
DATA_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("opus.market_sense")


def scan_topic(topic: str, *, sources: list[str] | None = None) -> dict:
    """卷三十三占位 · 未来实现真正的评论抓取"""
    return {
        "ok": False,
        "topic": topic,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "comments": [],
        "note": "market_sense 还没实现 · 卷三十三主菜 · 现在调没用",
    }


def list_topics() -> dict:
    """列已抓取的话题（暂时空）"""
    files = sorted(DATA_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return {
        "total": len(files),
        "items": [{"file": f.name, "size": f.stat().st_size} for f in files[:30]],
    }
