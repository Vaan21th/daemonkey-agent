"""workers/translator.py

雷达英文条目翻译器（卷二十七）。

为什么独立成一个 worker：
  - 雷达抓 RSS 每次都会出现"上次翻过的"英文条目 · 反复翻浪费 token
  - 翻译模型应当是 cheap-and-fast (deepseek-chat / qwen-turbo) · 不一定跟主 OPUS 同一个模型
  - 翻译失败不应当让雷达抓取失败 · 隔离

------------------------------------------------------------
设计
------------------------------------------------------------

数据流:
  info_radar.refresh_radar() 抓完 RSS 后
    ↓
  translator.translate_items(items)
    - 检测每条是不是英文（中文占比 < 30% 视为英文）
    - 看 title hash 是不是已在 cache (data/translations.json)
    - 已翻 → 直接拼回 title_zh / summary_zh 字段
    - 未翻 → 加入 batch queue
  ↓
  batch_translate(batch)
    - 一次调 LLM 翻 N 条 (batch=10 · 控制 token + 控制粒度)
    - 输出 JSON 数组 · 每条 {title_zh, summary_zh}
    - 写入 cache
  ↓
  返回带 title_zh/summary_zh 的 items

Cache (data/translations.json):
  {
    "version": 1,
    "entries": {
      "<sha256 of original_title>": {
        "title_zh": "...",
        "summary_zh": "...",
        "translated_at": "ISO",
        "model": "deepseek-chat"
      },
      ...
    }
  }

环境变量:
  OPUS_TRANSLATOR_MODEL · 翻译用什么模型 · 默认 "deepseek-chat"
  OPUS_TRANSLATOR_BATCH · 一批翻几条 · 默认 10
  OPUS_BASE_URL / OPUS_API_KEY · 复用主 client 的 endpoint

错误处理（红线）:
  - LLM 出错 → 返回未翻的 items 原封不动 · 不让雷达页崩
  - LLM 返回非 JSON → 退回 · 这一批不翻
  - 超时 → 返回未翻
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
CACHE_FILE = DATA_DIR / "translations.json"

logger = logging.getLogger("opus.translator")


_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff]")


def _chinese_ratio(text: str) -> float:
    """估算文本中文字符比例"""
    if not text:
        return 0.0
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    cjk = sum(1 for c in chars if _CJK_RE.match(c))
    return cjk / len(chars)


def _is_mostly_english(text: str, threshold: float = 0.3) -> bool:
    """判断 text 是不是"英文为主" · 中文比例 < threshold 视为英文"""
    return _chinese_ratio(text) < threshold


def _hash_key(title: str) -> str:
    """title sha256[:16] · cache key"""
    return hashlib.sha256(title.encode("utf-8")).hexdigest()[:16]


def _strip_html(html: str) -> str:
    """简易 HTML 清洗 · summary 里常带 <a> <p> 等"""
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&[a-z#0-9]+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ──────────────────────────────────────────────────────────
# Cache I/O
# ──────────────────────────────────────────────────────────

def _load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {"version": 1, "entries": {}}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "entries": {}}


def _save_cache(cache: dict) -> None:
    tmp = CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(CACHE_FILE)


# ──────────────────────────────────────────────────────────
# LLM client (复用主 client 的 base_url + api_key · 但模型独立)
# ──────────────────────────────────────────────────────────

def _get_translator_client():
    """构造一个 OpenAI-compatible client · 用于翻译

    复用 OPUS_BASE_URL / OPUS_API_KEY (因为 aihubmix 走的就是 openai compat 协议)
    模型用 OPUS_TRANSLATOR_MODEL · 默认 deepseek-chat
    """
    try:
        import openai
    except ImportError:
        return None, None

    base_url = (os.environ.get("OPUS_BASE_URL") or "").strip()
    api_key = (os.environ.get("OPUS_API_KEY") or "").strip()
    model = (
        os.environ.get("OPUS_TRANSLATOR_MODEL") or "deepseek-chat"
    ).strip()

    if not base_url or not api_key:
        return None, None

    try:
        client = openai.OpenAI(base_url=base_url, api_key=api_key)
    except Exception as e:
        logger.error("failed to construct translator client: %s", e)
        return None, None

    return client, model


# ──────────────────────────────────────────────────────────
# 批量翻译
# ──────────────────────────────────────────────────────────

_BATCH_PROMPT = """请把下面 {n} 条英文 AI 资讯的标题和摘要翻译成中文。

要求：
- 标题翻译要简洁 · 保留专有名词原文（如 "ChatGPT" / "GPT-5"）· 不要意译过头
- 摘要翻译要忠实 · 但去掉冗余的 HTML 残留 / 评论链接等噪音
- 输出必须是合法 JSON 数组 · 不要 markdown 围栏 · 不要前后解释文字
- 数组长度必须严格等于输入的 {n}
- 每个元素的 index 必须严格对应输入的顺序

输出格式:

[
  {{"i": 0, "title_zh": "...", "summary_zh": "..."}},
  {{"i": 1, "title_zh": "...", "summary_zh": "..."}},
  ...
]

输入:

{items_block}"""


def _format_items_for_translation(items: list[dict]) -> str:
    """渲染待翻译条目"""
    lines = []
    for i, it in enumerate(items):
        title = (it.get("title") or "").strip().replace("\n", " ")
        if len(title) > 200:
            title = title[:200] + "..."
        summary = _strip_html(it.get("summary") or "")
        if len(summary) > 400:
            summary = summary[:400] + "..."
        lines.append(f"## {i}")
        lines.append(f"title: {title}")
        if summary:
            lines.append(f"summary: {summary}")
        lines.append("")
    return "\n".join(lines)


def _parse_translation_response(raw: str, expected_n: int) -> Optional[list[dict]]:
    """从 LLM 输出抽 JSON 数组"""
    if not raw:
        return None
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        return None
    try:
        arr = json.loads(text[start:end + 1])
    except Exception:
        return None
    if not isinstance(arr, list):
        return None
    return arr


def _batch_translate(client, model: str, batch: list[dict]) -> dict[int, dict]:
    """翻译一批 · 返回 {batch_index: {title_zh, summary_zh}}

    失败返回空 dict
    """
    if not batch:
        return {}

    items_block = _format_items_for_translation(batch)
    prompt = _BATCH_PROMPT.format(n=len(batch), items_block=items_block)

    started = time.time()
    raw = ""
    try:
        from daemon_runtime import bg_max_tokens
        resp = client.chat.completions.create(
            model=model,
            max_tokens=bg_max_tokens(),
            temperature=0.3,
            messages=[
                {"role": "system", "content": "你是专业的中英翻译 · 输出严格的 JSON。"},
                {"role": "user", "content": prompt},
            ],
        )
        raw = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        if usage:
            logger.info(
                "translator batch n=%d in=%s out=%s elapsed=%dms",
                len(batch),
                getattr(usage, "prompt_tokens", "?"),
                getattr(usage, "completion_tokens", "?"),
                int((time.time() - started) * 1000),
            )
    except Exception as e:
        logger.error("translator LLM call failed: %s", e)
        return {}

    arr = _parse_translation_response(raw, expected_n=len(batch))
    if arr is None:
        logger.warning(
            "translator response not parseable · raw[:200]=%r", raw[:200]
        )
        return {}

    out: dict[int, dict] = {}
    for entry in arr:
        if not isinstance(entry, dict):
            continue
        try:
            i = int(entry.get("i", -1))
        except (TypeError, ValueError):
            continue
        if i < 0 or i >= len(batch):
            continue
        title_zh = (entry.get("title_zh") or "").strip()
        summary_zh = (entry.get("summary_zh") or "").strip()
        if not title_zh:
            continue
        out[i] = {
            "title_zh": title_zh,
            "summary_zh": summary_zh,
        }
    return out


# ──────────────────────────────────────────────────────────
# 对外入口
# ──────────────────────────────────────────────────────────

def translate_items(
    items: list[dict],
    *,
    batch_size: Optional[int] = None,
    force: bool = False,
) -> list[dict]:
    """给 items 加 title_zh / summary_zh 字段。

    - 中文为主的条目自动跳过（已经是中文 · 不需要翻）
    - 已 cache 的条目直接拼接 · 不调 LLM
    - 未 cache 的英文条目分 batch 翻 · 失败的保持英文原样

    Args:
        items: list of dict · 每个有 title / summary 字段
        batch_size: 一批翻几条 · 默认 OPUS_TRANSLATOR_BATCH 或 10
        force: 忽略 cache 强制重翻

    Returns:
        新 list · 每个元素是 items 对应元素的浅 copy + 可能加 title_zh/summary_zh
    """
    if not items:
        return list(items)

    if batch_size is None:
        try:
            batch_size = int(os.environ.get("OPUS_TRANSLATOR_BATCH") or "10")
        except ValueError:
            batch_size = 10
    batch_size = max(1, min(batch_size, 30))

    cache = _load_cache()
    entries: dict = cache.get("entries") or {}

    # 第一遍：分类
    out_items: list[dict] = []
    to_translate: list[tuple[int, dict, str]] = []
    # (out_index, item_shallow_copy, hash_key)

    for it in items:
        copy = dict(it)
        title = (copy.get("title") or "").strip()
        if not title:
            out_items.append(copy)
            continue

        # 中文优先 · 跳过
        if not _is_mostly_english(title) and not force:
            out_items.append(copy)
            continue

        key = _hash_key(title)
        cached = entries.get(key)
        if cached and not force:
            copy["title_zh"] = cached.get("title_zh", "")
            copy["summary_zh"] = cached.get("summary_zh", "")
            copy["_translated"] = True
            out_items.append(copy)
            continue

        to_translate.append((len(out_items), copy, key))
        out_items.append(copy)

    if not to_translate:
        return out_items

    # 第二遍：调 LLM
    client, model = _get_translator_client()
    if client is None:
        logger.warning("translator client unavailable · skip translation")
        return out_items

    new_cache_entries: dict = {}
    total = len(to_translate)
    logger.info(
        "translator: %d items to translate · batch_size=%d · model=%s",
        total, batch_size, model,
    )

    for start in range(0, total, batch_size):
        batch_slice = to_translate[start: start + batch_size]
        batch_items_for_llm = [t[1] for t in batch_slice]
        result = _batch_translate(client, model, batch_items_for_llm)

        for batch_idx, (out_idx, copy, key) in enumerate(batch_slice):
            tr = result.get(batch_idx)
            if not tr:
                continue
            out_items[out_idx]["title_zh"] = tr["title_zh"]
            out_items[out_idx]["summary_zh"] = tr["summary_zh"]
            out_items[out_idx]["_translated"] = True
            new_cache_entries[key] = {
                "title_zh": tr["title_zh"],
                "summary_zh": tr["summary_zh"],
                "translated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "model": model,
            }

    if new_cache_entries:
        entries.update(new_cache_entries)
        cache["entries"] = entries
        cache.setdefault("version", 1)
        _save_cache(cache)
        logger.info("translator cache updated: +%d entries", len(new_cache_entries))

    return out_items


def cache_stats() -> dict:
    """给 UI / 调试用 · cache 当下规模"""
    cache = _load_cache()
    entries = cache.get("entries") or {}
    return {
        "total_cached": len(entries),
        "cache_file": str(CACHE_FILE.relative_to(ROOT)).replace("\\", "/"),
        "version": cache.get("version", 1),
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    sample = [
        {"title": "Anthropic releases new Claude model with better reasoning",
         "summary": "<p>Today Anthropic announced ...</p>"},
        {"title": "OpenAI's GPT-5 rumored to launch in Q3",
         "summary": "Insiders say the next major model will arrive soon."},
        {"title": "国内大模型最新格局 · 一篇看懂",
         "summary": "国内主要 LLM 厂商最近动作汇总"},
    ]
    translated = translate_items(sample)
    print(json.dumps(translated, ensure_ascii=False, indent=2))
    print(json.dumps(cache_stats(), ensure_ascii=False, indent=2))
