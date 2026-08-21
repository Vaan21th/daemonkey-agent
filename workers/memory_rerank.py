"""workers/memory_rerank.py
========================
召回重排序 (2026-08-20 · 0.9.6 知识体系三件套之一)。

why: 记忆体检实测召回 top-5 的 LLM 判分只有 1.32/5 —— 瓶颈不是垃圾多 (卫生闸已清 38%)
而是排序不行: 答案躺在库里但被 bm25 词频挤出 top-5。 工程里已有的 hybrid_rerank 名不副实
—— 它是向量融合, 依赖 embedding 列, 而对话原文向量覆盖率 0% → 对 96% 的库完全无效。
LLM 重排直接读文本, 天然覆盖全库, 不需要任何向量基础设施。

设计:
  - FTS5 捞大池 (默认 30) → LLM 一次性批量判 → 按模型给出的相关度顺序重排 → 留 top-k
  - 保险丝: LLM 挂 / 输出解析失败 / 判全不相关 → 一律退回 FTS5 原序。
    重排只许锦上添花, 不许把召回搞挂。
  - 成本: 每次召回 +1 次 LLM 往返 (候选截断 400 字 · 输出只要编号列表 · 输出极短)。
    模型复用 daemon RUNTIME.client (当前主模型) —— 主模型是 flash 时这就是 flash 成本;
    主模型切旗舰后每次召回会变贵, 到时再考虑独立 flash 通道 (env 可关: OPUS_RECALL_RERANK=0)。
"""

from __future__ import annotations

import json
import logging
import os
import re

logger = logging.getLogger(__name__)

_POOL_DEFAULT = 30
_SNIPPET_CHARS = 400


def rerank_enabled() -> bool:
    return os.environ.get("OPUS_RECALL_RERANK", "1").strip().lower() not in ("0", "false", "no")


def pool_size() -> int:
    try:
        return max(5, int(os.environ.get("OPUS_RECALL_RERANK_POOL", str(_POOL_DEFAULT))))
    except ValueError:
        return _POOL_DEFAULT


def _judge_call(prompt: str) -> str:
    """调一次 LLM 判分。 两条通道按优先级:

    1. env 独立通道 (OPUS_RERANK_BASE_URL / OPUS_RERANK_API_KEY / OPUS_RERANK_MODEL) ——
       台架 (不在 daemon 里) 或主模型是旗舰时, 给重排配一条固定的便宜通道。
    2. daemon RUNTIME.client (双 provider 分支跟 _llm_mini_call 同款)。

    都没有 → 抛异常 → 调用方退回原序。
    """
    base_url = (os.environ.get("OPUS_RERANK_BASE_URL") or "").strip()
    api_key = (os.environ.get("OPUS_RERANK_API_KEY") or "").strip()
    model = (os.environ.get("OPUS_RERANK_MODEL") or "").strip()
    if base_url and api_key and model:
        import requests

        resp = requests.post(
            base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "max_tokens": 1000,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=60,
        )
        resp.raise_for_status()
        return (resp.json()["choices"][0]["message"]["content"] or "").strip()

    from daemon_runtime import RUNTIME

    if RUNTIME.client is None:
        raise RuntimeError("RUNTIME.client 未初始化")
    if RUNTIME.provider == "anthropic":
        resp = RUNTIME.client.messages.create(
            model=RUNTIME.model, max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    resp = RUNTIME.client.chat.completions.create(
        model=RUNTIME.model, max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    return (resp.choices[0].message.content or "").strip()


def _build_prompt(query: str, candidates: list) -> str:
    lines = [
        "你在给记忆检索的结果判相关性。",
        f"问题: {query}",
        "",
        f"下面是 {len(candidates)} 条候选记忆。挑出跟问题真正相关的，按相关度从高到低给出编号。",
        "标准: 能直接回答问题的排最前; 只是词面沾边/同名不同事的不要; 一条都不要硬凑。",
        "",
    ]
    for i, c in enumerate(candidates, 1):
        snippet = re.sub(r"\s+", " ", (getattr(c, "content", "") or ""))[:_SNIPPET_CHARS]
        src = getattr(c, "source", "") or ""
        lines.append(f"[#{i}] ({src}) {snippet}")
    lines += [
        "",
        '只输出 JSON (不要任何别的文字): {"relevant": [编号...按相关度从高到低]}',
        '全部不相关就输出 {"relevant": []}',
    ]
    return "\n".join(lines)


def _parse_order(text: str, n: int) -> list[int] | None:
    """从模型输出抠 relevant 编号列表 (越界/重复过滤)。 解析失败返回 None。"""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    rel = data.get("relevant")
    if not isinstance(rel, list):
        return None
    out: list[int] = []
    for x in rel:
        if isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= n and x not in out:
            out.append(x)
    return out


def _dedup(candidates: list) -> list:
    """候选池去重: 同一句话在不同会话的复制 (e2e/测试会话转存) 会让重复簇集体被判相关
    霸榜 top-k —— 真机实测「BRO 喜欢什么回复风格」top-5 被同一句的 5 份复制占满。
    前 200 字符归一化后相同的只留第一条 (FTS5 序最前的 · 即 bm25 最强的那个副本)。
    """
    seen: set[str] = set()
    out = []
    for c in candidates:
        key = re.sub(r"\s+", "", (getattr(c, "content", "") or ""))[:200]
        if key and key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def rerank(query: str, candidates: list, *, top_k: int = 5, judge=None) -> list:
    """LLM 重排 · 任何一步失败都退回 FTS5 原序的前 top_k 条。

    judge: 测试注入的假判分函数 (prompt) -> str; 默认走 daemon RUNTIME。
    """
    if not candidates:
        return candidates
    if len(candidates) <= 1:
        return candidates[:top_k]
    if not rerank_enabled():
        return candidates[:top_k]
    candidates = _dedup(candidates)
    if len(candidates) <= 1:
        return candidates[:top_k]
    try:
        call = judge or _judge_call
        text = call(_build_prompt(query, candidates))
        order = _parse_order(text, len(candidates))
        if not order:
            # 解析失败 · 或模型判全不相关 (bm25 至少保证词面相关 · 原序更可信)
            return candidates[:top_k]
        picked = [candidates[i - 1] for i in order]
        picked_ids = {id(c) for c in picked}
        rest = [c for c in candidates if id(c) not in picked_ids]
        return (picked + rest)[:top_k]
    except Exception as e:
        logger.warning("memory_rerank: %s · 退回原序", e)
        return candidates[:top_k]
