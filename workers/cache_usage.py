"""缓存 usage 归一化 · 唯一真源 (single source of truth)

tool_loop 的 _extract_openai_cache_usage 曾是本地复制逻辑 (wish-5c2f40fa 对比时发现
"改一处忘一处 → 口径分裂"隐患)。2026-08-14 从墨言 094 移植本模块：
  - tool_loop.py → from workers.cache_usage import extract_openai_cache_usage

以后改 cache 字段探测只改这里 · 调用处自动同步。纯函数无副作用 · 不 import daemon 任何模块。
"""
from typing import Any


def normalize_usage_object(usage: Any):
    """LiteLLM 等 SDK 可能把 usage 返回成 dict · 归一成属性访问对象（唯一真源 · model_io 同用）。

    dict 输入 → 轻量对象 (含 prompt_tokens_details 嵌套归一)；非 dict 原样返回。
    """
    if not isinstance(usage, dict):
        return usage

    class _U:
        pass
    u = _U()
    for k, v in usage.items():
        if k == "prompt_tokens_details" and isinstance(v, dict):
            setattr(u, k, _U())
            for kk, vv in v.items():
                setattr(getattr(u, k), kk, vv)
        else:
            setattr(u, k, v)
    return u


def extract_openai_cache_usage(usage: Any) -> tuple[int, int, int | None]:
    """OpenAI 协议各家把 cache 命中挂在 usage 上·字段名三套都见过：
       - cache_creation_input_tokens / cache_read_input_tokens   (Anthropic 原生 · AiHubMix)
       - prompt_tokens_details.cached_tokens                     (OpenAI / LiteLLM 归一风格)
       - prompt_cache_hit_tokens / prompt_cache_miss_tokens      (DeepSeek 自动 disk cache)
    按优先级摸一遍，返回 (creation, read, miss)。read 走计费估算 10% 那档。
    miss=None 表示该 provider 没有可用的 miss 信号（显示层回退旧口径）。
    miss 口径 (wish-5c2f40fa · 真口径 hit/(hit+miss) 的分母部分)：
       - Anthropic flat: miss = input - read（真 miss 含 non_cache · prompt 拿不到回退 creation）
       - DeepSeek:      官方 prompt_cache_miss_tokens
       - OpenAI nested: prompt_tokens - cached_tokens（算得出来就算）
    """
    # LiteLLM 等 SDK 可能把 usage 返回成 dict · 先归一成属性访问
    usage = normalize_usage_object(usage)

    def _g(*names: str) -> int:
        for name in names:
            try:
                v = getattr(usage, name)
                if v is not None:
                    return int(v)
            except Exception:
                pass
        return 0

    # ① Anthropic-style flat fields (AiHubMix 经常用这套 · 兼容 cache_creation_tokens/cache_hit_tokens 别名)
    creation = _g("cache_creation_input_tokens", "cache_creation_tokens")
    read = _g("cache_read_input_tokens", "cache_hit_tokens")
    if creation or read:
        prompt = _g("prompt_tokens", "input_tokens")
        miss = (prompt - read) if prompt > read else (creation if creation else None)
        return creation, read, miss

    # ② DeepSeek 自动 disk cache · 命中即按 hit 价 (~1/50 miss 价)·映射成 read 这档。
    #    字段可能直接挂 usage·也可能被 openai SDK 收进 model_extra·两处都摸。
    ds_hit = getattr(usage, "prompt_cache_hit_tokens", None)
    ds_miss = getattr(usage, "prompt_cache_miss_tokens", None)
    if ds_hit is None or ds_miss is None:
        extra = getattr(usage, "model_extra", None) or {}
        if isinstance(extra, dict):
            if ds_hit is None:
                ds_hit = extra.get("prompt_cache_hit_tokens")
            if ds_miss is None:
                ds_miss = extra.get("prompt_cache_miss_tokens")
    if ds_hit:
        return 0, int(ds_hit), int(ds_miss) if ds_miss is not None else None

    # ③ OpenAI-style nested cached_tokens (no creation distinction here)
    details = getattr(usage, "prompt_tokens_details", None)
    if details is not None:
        cached = getattr(details, "cached_tokens", 0) or 0
        if cached:
            prompt = _g("prompt_tokens", "input_tokens")
            miss = (prompt - cached) if prompt > cached else None
            return 0, int(cached), miss

    return 0, 0, None
