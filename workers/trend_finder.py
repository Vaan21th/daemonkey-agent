"""
workers/trend_finder.py
========================

工作室 · 今日趋势 worker · 让 OPUS 自己看资讯找趋势

工作流：
  1. 读 data/radar.json · 取最新 50 条（按 published_at desc · 按源去重）
  2. 渲染成结构化清单
  3. 调 RUNTIME.client.messages.create → OPUS 输出 3-5 个趋势 JSON
  4. 解析 + 落 data/trends.json
  5. /dashboard/trends 读取展示

红线第 1 条 "没有 BUG"
  - 即使 LLM 输出不是合法 JSON · 也要返回可用 stub · 不让前端崩
  - LLM 调用超时 / 429 / 5xx · 返回 error 字段而不是 crash

红线第 3 条 "不会让操作系统废了"
  - 只读 radar.json · 只写 trends.json · 不动其他

成本提醒：
  - 一次 trend 调用 ~3k input + 500 output tokens
  - claude-opus-4 大约 $0.05/次 · 一天 5-10 次还行
  - 不在 scheduler 里自动跑 · 用户 主动点"今日趋势"才跑
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
RADAR_FILE = DATA_DIR / "radar.json"
TRENDS_FILE = DATA_DIR / "trends.json"

logger = logging.getLogger("opus.trends")

TREND_SYSTEM_PROMPT = """你是用户的 AI 搭档。用户关注自己选定的领域——看雷达条目覆盖了哪些 domain / 来自哪些来源，就知道他在乎什么。你的活是从这些资讯里找出值得他跟进的趋势和热点。

你输出的不是"今日新闻总结"——是"用户接下来能干什么"的军师视图。

**[跟着用户的兴趣走 · 最重要]**

雷达条目的 domain / 来源 = 用户**主动选择关注**的方向。趋势必须从这些方向里提炼·
**不要强行往某个固定赛道（比如 AI / 科技）上靠**——用户关注动漫就提炼动漫趋势·关注独立游戏就提炼游戏趋势。

你看趋势时·**必须先看用户的反馈历史**：
- 他在 outcomes 里完成过 / 放弃过什么·说明他擅长 / 不擅长什么
- 他在雷达里 👍 / 👎 / ⭐ 标过的条目·说明他真正关注 / 排斥什么
- 这些累加起来 = 用户独有的位置·不是任何人都能复制

然后你挑趋势时·要挑**只有用户这种位置的人能吃下的趋势**——
让用户看到这份趋势报告时·能反思"啊·原来我已经走到这步了·原来我现在该看 X"。

**[事实较量红线]**

你在 summary 里写"业内已有 X" / "市场规模 Y" / "用户数 Z" 这种**事实陈述**时·
**必须诚实**——除非雷达条目里有原文佐证·否则用"据公开报道"/"参考信号"等模糊措辞·
**不要编造具体数字**。可信度 > 完美感。

**[深度]**

用户消息里附 `## 教材` 段·是历史沉淀的高质量分析样本·
你输出的 summary 应该达到那个深度——挑战既有结论 / 给反例 / 不当 cheerleader。"""

TREND_USER_PROMPT_TEMPLATE = """下面是雷达抓到的 {n} 条最新资讯。请你做以下事情：

## 用户的雷达打标历史（重要！）

{feedback_block}

---

## 用户历史执行反馈（看用户真做过 / 放弃过什么）

{outcomes_block}

---

1. 识别出 3-5 个值得 用户 注意的"趋势"或"热点"
2. 每个趋势包含 5 个字段：
   - title (短标题 · 10-20 字 · 中文)
   - summary (40-100 字 · 中文 · 说清这是什么趋势 + 前瞻性思考 + 为什么 用户 该关注)
   - intensity (1-5 整数 · 强度评分:
       1 = 远期 / 弱信号 · 知道就行
       2 = 在观望 · 不必动手
       3 = 值得跟进 · 用户 该花 1 小时了解
       4 = 强信号 · 用户 该花 1 天做点什么
       5 = 必须立刻动手 · 错过就晚了)
   - angles (数组 · 从下面 5 个选 1-3 个 · 用户 的工作室能从哪个角度切入这个趋势:
       "content" — 可以做内容选题 / 口播稿 / 视频
       "design"  — 可以转化为产品设计 / spec
       "dev"     — 可以做技术调研 / 开源工具
       "docs"    — 可以写 FAQ / 教程 / wiki
       "service" — 可以做服务方向 (暂缓 · 一般不要选这个))
   - refs (1-3 个 index 数字 · 从下面资讯列表挑最相关的)

**输出格式必须是合法的 JSON 数组**·不要 markdown 包裹·不要任何前后解释文字：

[
  {{
    "title": "...",
    "summary": "...",
    "intensity": 4,
    "angles": ["content", "design"],
    "refs": [3, 7, 12]
  }},
  ...
]

---

## 教材 · 历史沉淀的高质量分析样本

{learnings_block}

---
资讯列表（按时间倒序）：

{items_block}
---

记住：
- 用户是单打独斗的个人 · 关注"我能不能切这个赛道"·"这是不是真趋势还是炒作"·"这能不能转化为产出"
- 不要罗列单条新闻 · 找模式 · 把多条资讯归到一个趋势下
- summary 里要带"前瞻性思考"·不只是描述现状·点出"如果这个趋势成立·6 个月后会怎样"
- intensity 不要全打 5 · 大多数应该 3-4 · 真正"现在不动手就晚"才打 5
- angles 是工作室能不能切·不能切就空数组 [] · 别硬塞
- **看雷达打标历史**——用户 👎 拒过的源/方向·这一轮趋势提炼时要绕开·别再框成趋势；用户 ⭐ 收藏过的方向·intensity 可以适当 +1
- **看执行反馈**——用户 已完成的方向·继续 surface 同类趋势 intensity +1；用户 abandoned 的方向·框为趋势时要在 summary 里**说出来**（"用户 之前因为 X 放弃过同类·这次因 Y 不同所以仍值得看"）"""


def _load_radar_items(top_n: int = 50) -> list[dict]:
    """读 radar.json 的 items · 截取 top_n 条"""
    if not RADAR_FILE.exists():
        return []
    try:
        data = json.loads(RADAR_FILE.read_text(encoding="utf-8"))
        items = data.get("items", [])
        return items[:top_n]
    except Exception as e:
        logger.error("failed to load radar.json: %s", e)
        return []


def _render_items_block(items: list[dict]) -> str:
    """把 items 渲染成 LLM 可读的清单"""
    lines = []
    for i, it in enumerate(items, start=1):
        title = (it.get("title") or "").strip().replace("\n", " ")
        src = it.get("source_display") or it.get("source") or "?"
        cat = it.get("category") or ""
        # 标题截到 120 字防过长
        if len(title) > 120:
            title = title[:120] + "..."
        line = f"{i:3d}. [{src}] [{cat}] {title}"
        lines.append(line)
    return "\n".join(lines)


def _extract_json_array(text: str) -> Optional[list]:
    """从 LLM 输出里提取 JSON 数组 · 容忍 markdown 包裹 / 前后空白"""
    if not text:
        return None
    text = text.strip()
    # 去 markdown 围栏
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    # 找 [ ... ] 段
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = text[start: end + 1]
    try:
        result = json.loads(candidate)
        if isinstance(result, list):
            return result
    except Exception:
        pass
    return None


def _atomic_write(path: Path, content: str) -> None:
    """卷四十六 III · wish-badd4 收编到 safe_write
    trends.json 高频 (LLM 自动产) · backup=False 不占空间"""
    from .safe_write import atomic_write_text
    atomic_write_text(path, content, backup=False)


def generate_trends(top_n: int = 50) -> dict:
    """让 OPUS 自己看 radar.json · 输出 3-5 个趋势 · 写 data/trends.json

    返回 dict · 跟 trends.json 内容一致 · 或带 error 字段
    """
    from daemon_runtime import RUNTIME

    items = _load_radar_items(top_n=top_n)
    if not items:
        return {
            "generated_at": None,
            "trends": [],
            "note": "radar.json 为空 · 先跑一次雷达再来。用户 可以跟 OPUS 说「刷新雷达」",
        }

    if RUNTIME.client is None:
        return {
            "generated_at": None,
            "trends": [],
            "error": "RUNTIME.client 还没初始化 · daemon 没启动？",
        }

    items_block = _render_items_block(items)
    # 卷三十二 · 喂入 用户 的雷达打标历史
    try:
        from workers.radar_feedback import load_for_prompt as _fb_prompt
        feedback_block = _fb_prompt(max_chars=1000)
    except Exception as _e:
        feedback_block = "（暂无打标历史）"

    # 卷三十四 · 喂入 用户 的执行反馈历史 · trend_finder 也开始吃 outcomes
    try:
        from workers.outcomes import load_outcomes_for_prompt
        outcomes_block = load_outcomes_for_prompt(max_chars=800)
    except Exception as _e:
        outcomes_block = "（暂无执行反馈）"

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

    user_prompt = TREND_USER_PROMPT_TEMPLATE.format(
        n=len(items),
        items_block=items_block,
        feedback_block=feedback_block,
        outcomes_block=outcomes_block,
        learnings_block=learnings_block,
    )

    started = time.time()
    logger.info("trend_finder: calling LLM with %d items", len(items))

    raw_output = ""
    error: Optional[str] = None
    usage: dict = {}

    try:
        provider = RUNTIME.provider
        if provider == "anthropic":
            resp = RUNTIME.client.messages.create(
                model=RUNTIME.model,
                max_tokens=10000,
                system=TREND_SYSTEM_PROMPT,
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
                max_tokens=10000,
                messages=[
                    {"role": "system", "content": TREND_SYSTEM_PROMPT},
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
        logger.exception("trend_finder LLM error")

    elapsed_ms = int((time.time() - started) * 1000)

    # 解析 LLM 输出
    parsed = _extract_json_array(raw_output)
    trends: list[dict] = []

    _VALID_ANGLES = {"content", "design", "dev", "docs", "service"}
    if parsed:
        for t in parsed:
            if not isinstance(t, dict):
                continue
            title = (t.get("title") or "").strip()
            summary = (t.get("summary") or "").strip()
            refs_idx = t.get("refs") or []
            if not (title and summary):
                continue

            # intensity · clamp to 1-5 · 默认 3
            raw_intensity = t.get("intensity")
            try:
                intensity = int(raw_intensity)
            except (TypeError, ValueError):
                intensity = 3
            intensity = max(1, min(5, intensity))

            # angles · 只保留合法值 · 默认空数组
            raw_angles = t.get("angles") or []
            if not isinstance(raw_angles, list):
                raw_angles = []
            angles = [a for a in raw_angles
                      if isinstance(a, str) and a in _VALID_ANGLES]

            # 把 refs index 翻译成具体 url + source
            refs: list[dict] = []
            for r in refs_idx:
                try:
                    i = int(r)
                except Exception:
                    continue
                if 1 <= i <= len(items):
                    it = items[i - 1]
                    refs.append(
                        {
                            "source": it.get("source_display") or it.get("source", "?"),
                            "title": it.get("title", ""),
                            "url": it.get("url", ""),
                            "radar_index": i - 1,  # 让 expand_trend_to_report 能反查
                        }
                    )
            trends.append({
                "title": title,
                "summary": summary,
                "intensity": intensity,
                "angles": angles,
                "refs": refs,
            })

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_ms": elapsed_ms,
        "items_scanned": len(items),
        "model": RUNTIME.model,
        "trends": trends,
        "usage": usage,
    }
    if error:
        payload["error"] = error
    if not trends:
        payload["raw_output"] = raw_output[:2000]
        payload["note"] = (
            "LLM 输出解析失败 · raw_output 留作调试。常见原因："
            "(1) LLM 没按 JSON 格式输出 (2) 模型 timeout"
        )

    _atomic_write(
        TRENDS_FILE,
        json.dumps(payload, ensure_ascii=False, indent=2),
    )

    # 卷三十三补丁 · 归档：每天最后一份 trends 落到 archive · 用于按日检索历史趋势
    try:
        from datetime import datetime as _dt
        archive_dir = DATA_DIR / "trends_archive"
        archive_dir.mkdir(exist_ok=True)
        # 用本地日期当 key·一个日期只保留最后一份（同日多次跑会覆盖）
        day_key = _dt.now().strftime("%Y-%m-%d")
        archive_file = archive_dir / f"{day_key}.json"
        _atomic_write(
            archive_file,
            json.dumps(payload, ensure_ascii=False, indent=2),
        )
        logger.info("trends archived · %s", archive_file.name)
    except Exception as e:  # 归档失败不阻塞主流程
        logger.warning("trends archive failed (non-fatal): %s", e)

    logger.info(
        "trend_finder done · %d trends · %dms · usage=%s",
        len(trends),
        elapsed_ms,
        usage,
    )
    return payload


def load_trends() -> dict:
    """读 data/trends.json · 不存在返回 stub"""
    if not TRENDS_FILE.exists():
        return {
            "generated_at": None,
            "trends": [],
            "note": "趋势还没生成 · 点'让 OPUS 重新总结'·或跟 OPUS 说「今日趋势」",
        }
    try:
        return json.loads(TRENDS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": f"failed to load trends.json: {e}"}


def load_trends_for_day(day: str) -> dict:
    """卷三十三补丁 · 按日期读历史趋势

    优先读 data/trends_archive/YYYY-MM-DD.json
    都没有 → 检查当前 trends.json 是不是这一天的 · 是就返回 · 否则返回 stub
    """
    archive_dir = DATA_DIR / "trends_archive"
    archive_file = archive_dir / f"{day}.json"
    if archive_file.exists():
        try:
            d = json.loads(archive_file.read_text(encoding="utf-8"))
            d["_source"] = "archive"
            d["_day"] = day
            return d
        except Exception as e:
            return {"error": f"failed to load trends_archive/{day}.json: {e}"}

    # fallback · 当前 trends 是不是这一天
    if TRENDS_FILE.exists():
        try:
            cur = json.loads(TRENDS_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            cur = None
        if cur:
            gen = (cur.get("generated_at") or "")[:10]
            if gen == day:
                cur["_source"] = "current"
                cur["_day"] = day
                return cur

    return {
        "generated_at": None,
        "trends": [],
        "_source": "empty",
        "_day": day,
        "note": (
            f"{day} 这一天没有历史趋势归档。趋势归档从卷三十三补丁开始建立 · "
            "之前生成的趋势都覆盖在 trends.json·没有按日存档。今天往后的每天会留底。"
        ),
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    # CLI 单跑需要先 setup runtime · 用最简单的方式：
    # 从 .env 拿 token + 装一个 anthropic client
    from dotenv import load_dotenv
    import os

    load_dotenv(ROOT / ".env")
    from daemon_runtime import RUNTIME

    if RUNTIME.client is None:
        # CLI smoke: 装个 anthropic client
        try:
            import anthropic
            key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
            if not key:
                print("[err] ANTHROPIC_API_KEY 未配置 · 跳过 LLM 调用")
                raise SystemExit(1)
            RUNTIME.client = anthropic.Anthropic(api_key=key)
            RUNTIME.provider = "anthropic"
            RUNTIME.model = os.environ.get("OPUS_MODEL", "claude-opus-4-20250514")
        except ImportError:
            print("[err] anthropic 包没装")
            raise SystemExit(1)

    result = generate_trends()
    print(json.dumps(result, ensure_ascii=False, indent=2)[:3000])
