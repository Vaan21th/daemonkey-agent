"""
workers/capability_mirror.py
============================

卷三十六 · 市场能力镜像引擎

OPUS 周期性提炼 BRO 的市场能力切片 → 反哺看清自己。

差异化分叉（BRO 2026-05-23 定调）:
  - hermes 单向: AI 越来越懂用户·帮用户干更多活
  - OPUS 双向: AI 懂 BRO + BRO 借 AI 看清自己 → 找到定位 + 赚钱机会

数据源（全只读）:
  1. soul/BRO-NOTEBOOK.md · BRO 画像（6 维）
  2. data/favorites.json · BRO 收藏的机会/可行性分析
  3. data/radar_feedback.json · 雷达条目 👍/👎/⭐/🗑
  4. data/outcomes.json · record_outcome 的闭环反馈
  5. data/opportunities.json · 已挖掘的掘金机会
  6. sessions/_index.json · 会话元数据（置顶/重命名 = BRO 重视的话题）
  7. sessions/*.summary.json · 最近对话的压缩摘要（卷五十八续 VI · 接通桥）
     ← 此前镜子只看"点击痕迹"·看不到真实对话。 这一源让 Layer0 的对话信号
       流进镜子层·同时也是 review 画像块的对话输入(review_input 那笔)。

输出:
  data/bro_capability_snapshot.md · 四个区段:
    显性能力 · BRO 真做过且成的事
    隐性能力 · BRO 反复收藏/点赞但还没动手 → 兴趣+潜力
    排斥模式 · BRO 👍 / 👎 / 收藏中出现的"不做的理由"模式
    成长轨迹 · 能力随时间的变化方向
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SOUL_DIR = ROOT / "soul"
SNAPSHOT_PATH = DATA_DIR / "bro_capability_snapshot.md"

# ── 数据加载 ──────────────────────────────────────────────────

def _load_bro_profile(max_chars: int = 3500) -> str:
    """读 BRO-NOTEBOOK · 截前 max_chars（要点都在前面）"""
    bro_file = SOUL_DIR / "BRO-NOTEBOOK.md"
    if not bro_file.exists():
        return "（BRO-NOTEBOOK 还没同步 · 跑 sync-soul.ps1）"
    try:
        text = bro_file.read_text(encoding="utf-8")
    except Exception:
        return "（BRO-NOTEBOOK 读不出来）"
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n…（已截断 · 完整画像在 soul/BRO-NOTEBOOK.md）"


def _load_favorites(max_items: int = 30) -> str:
    """加载 BRO 收藏夹 · 返回可读文本"""
    fav_file = DATA_DIR / "favorites.json"
    if not fav_file.exists():
        return "（暂无收藏）"
    try:
        data = json.loads(fav_file.read_text(encoding="utf-8"))
        items = data.get("items", {})
        if not items:
            return "（收藏夹为空）"
        lines = [f"收藏总数: {len(items)}"]
        for key, val in list(items.items())[:max_items]:
            kind = val.get("kind", "?")
            title = val.get("title", val.get("title_hint", key))
            added = val.get("added_at", "?")
            lines.append(f"  [{kind}] {title}  ({added})")
        return "\n".join(lines)
    except Exception as e:
        return f"（收藏读失败: {e}）"


def _load_radar_feedback(max_items: int = 30) -> str:
    """加载雷达反馈 · 👍/👎/⭐/🗑"""
    fb_file = DATA_DIR / "radar_feedback.json"
    if not fb_file.exists():
        return "（暂无雷达反馈）"
    try:
        data = json.loads(fb_file.read_text(encoding="utf-8"))
        items = data.get("items", {})
        if not items:
            return "（雷达反馈为空）"
        # 按 feedback 类型分组统计
        counts = {}
        samples = []
        for key, val in list(items.items())[:max_items]:
            fb = val.get("feedback", "?")
            counts[fb] = counts.get(fb, 0) + 1
            note = val.get("note", "")
            if note:
                samples.append(f"  [{fb}] {note[:120]}")
        lines = [f"反馈统计: {counts}"]
        if samples:
            lines.append("有备注的样本:")
            lines.extend(samples[:15])
        return "\n".join(lines)
    except Exception as e:
        return f"（雷达反馈读失败: {e}）"


def _load_outcomes(max_items: int = 20) -> str:
    """加载闭环反馈 · record_outcome 的历史。

    卷五十四修: 老版读 `data/outcomes.json` 单文件 · 但 record_outcome 实际写
    `data/outcomes/<opp_id>.json` 每机会一文件 (workers/outcomes.py OUTCOMES_DIR) ·
    路径对不上 → 能力镜像永远空转报"暂无闭环反馈"。 现直接复用 outcomes 的标准渲染器。
    """
    try:
        from workers.outcomes import load_outcomes_for_prompt
        return load_outcomes_for_prompt(max_chars=max_items * 90)
    except Exception as e:
        return f"（闭环反馈读失败: {e}）"


def _load_opportunities(max_items: int = 10) -> str:
    """加载已挖掘的掘金机会"""
    opp_file = DATA_DIR / "opportunities.json"
    if not opp_file.exists():
        return "（暂无掘金机会）"
    try:
        data = json.loads(opp_file.read_text(encoding="utf-8"))
        opps = data.get("opportunities", [])
        if not opps:
            return "（掘金机会为空）"
        lines = [f"已挖掘机会: {len(opps)} 个"]
        for opp in opps[:max_items]:
            title = opp.get("title", "?")
            rec = opp.get("recommend", "?")
            fit = opp.get("fit", "?")
            domain = opp.get("domain", "?")
            lines.append(f"  [{domain}] ⭐{rec} fit={fit} · {title}")
        return "\n".join(lines)
    except Exception as e:
        return f"（掘金机会读失败: {e}）"


def _load_recent_summaries(max_chars: int = 4000) -> str:
    """读最近对话的压缩摘要 · 让镜子照得见真实对话（卷五十八续 VI · 接通桥）。

    委托 memory_index.load_recent_summaries（摘要读取逻辑的单一真相源）·
    带 [会话 id · 日期] 前缀供 LLM cite。 失败优雅降级·不抛。
    """
    try:
        from workers.memory_index import load_recent_summaries
        return load_recent_summaries(max_chars=max_chars)
    except Exception as e:
        return f"（对话摘要读失败: {e}）"


# ── Prompt 模板 ────────────────────────────────────────────────

SYSTEM_PROMPT = """你是 OPUS 的"市场能力镜像"分析引擎。

你的任务不是给 BRO 打分——是帮他**看见自己**。

你要从 BRO 的行为痕迹（收藏了什么 / 拒绝了什么 / 做了什么 / 怕什么 / 想做什么）中，
提炼出他的**市场能力画像**，像一个镜子一样反照回去。

原则:
- 不吹捧 · 不贬低 · 不诊断
- 用具体证据说话（"BRO 收藏了 X 但一直没动" 比 "BRO 对 X 有兴趣" 好 100 倍）
- 模式 > 个案（1 次收藏是噪音·5 次同类收藏是信号）
- 短 · 每段 3-5 句够了
- 不确定就说"证据不够·待观察"
- **对话摘要是最高信号的证据**——点击痕迹只说"他看了啥"·对话说"他真做了什么决定、卡在哪、想往哪走"。
  引用对话证据时·**标出来自哪个会话**（如"会话 api-2026-06-06… 里他拍板要先建地基"）·绝不发明没出现过的信源。

输出 markdown · 四个区段:
1. 显性能力 · 他真做过且成了的事
2. 隐性能力 · 他反复关注但还没变现的
3. 排斥模式 · 他拒绝过什么 + 拒绝的口径
4. 成长轨迹 · 时间序列上的变化方向

最后给一段"给 BRO 的镜子话"——50 字以内。"""

USER_PROMPT_TEMPLATE = """# 数据输入

## BRO 画像 (BRO-NOTEBOOK 前 3500 字)
{bro_profile}

## BRO 收藏夹
{favorites}

## 雷达反馈 (👍/👎/⭐/🗑)
{radar_feedback}

## 闭环反馈 (record_outcome)
{outcomes}

## 已挖掘的掘金机会
{opportunities}

## 最近对话里的真实信号（会话压缩摘要 · 高信号 · 带会话出处）
{recent_summaries}

---

请基于以上数据·输出 BRO 的市场能力镜像快照。
四个区段 + 给 BRO 的镜子话（≤50 字）。
输出纯 markdown · 不要 JSON 包装。
如果某个区段数据不够·直接写"证据不足·待观察"。"""


# ── 主逻辑 ────────────────────────────────────────────────────

def generate_snapshot() -> dict:
    """跑一次完整能力镜像分析 · 写 data/bro_capability_snapshot.md · 返回汇总"""
    from daemon_runtime import RUNTIME

    if RUNTIME.client is None:
        return {
            "generated_at": None,
            "snapshot": "",
            "error": "RUNTIME.client 没初始化 · daemon 没启动？",
        }

    # 加载数据源
    bro = _load_bro_profile()
    favorites = _load_favorites()
    radar_feedback = _load_radar_feedback()
    outcomes = _load_outcomes()
    opportunities = _load_opportunities()
    recent_summaries = _load_recent_summaries()

    user_prompt = USER_PROMPT_TEMPLATE.format(
        bro_profile=bro,
        favorites=favorites,
        radar_feedback=radar_feedback,
        outcomes=outcomes,
        opportunities=opportunities,
        recent_summaries=recent_summaries,
    )

    started = time.time()
    logger.info("capability_mirror: calling LLM")

    raw_output = ""
    error: Optional[str] = None
    usage: dict = {}

    try:
        provider = RUNTIME.provider
        if provider == "anthropic":
            resp = RUNTIME.client.messages.create(
                model=RUNTIME.model,
                max_tokens=10000,
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
                max_tokens=10000,
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
        logger.exception("capability_mirror LLM error")

    elapsed_ms = int((time.time() - started) * 1000)

    if raw_output and not error:
        # Write snapshot
        header = (
            f"<!-- 生成于 {datetime.now(timezone.utc).isoformat()} -->\n"
            f"<!-- 模型 {RUNTIME.model} · 耗时 {elapsed_ms}ms -->\n\n"
        )
        SNAPSHOT_PATH.write_text(header + raw_output, encoding="utf-8")
        logger.info("capability_mirror: snapshot written to %s", SNAPSHOT_PATH)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_ms": elapsed_ms,
        "model": RUNTIME.model,
        "snapshot": raw_output,
        "snapshot_path": str(SNAPSHOT_PATH),
        "usage": usage,
        "error": error,
    }


def load_snapshot() -> dict:
    """只读已有快照 · 不调 LLM"""
    if not SNAPSHOT_PATH.exists():
        return {
            "generated_at": None,
            "snapshot": "",
            "note": "还没跑过能力镜像 · 用 generate 跑一次",
        }
    text = SNAPSHOT_PATH.read_text(encoding="utf-8")
    # 去掉 HTML 注释头
    lines = text.split("\n")
    body_lines = [ln for ln in lines if not ln.startswith("<!--")]
    return {
        "generated_at": "见文件头注释",
        "snapshot": "\n".join(body_lines),
        "snapshot_path": str(SNAPSHOT_PATH),
    }
