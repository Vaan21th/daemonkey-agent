"""workers/pricing.py · 计价引擎 + 官方查价 (wish-bec4f3b9 · LLM 可配置价格表)

数据流: provider_configs.pricing(配价) → 本模块 calc_cost(计价) →
        /llm-pricing[/lookup] 路由 (查价) → dashboard/billing 聚合 × 价格 → 前端计费卡

口径对齐 tool_loop.py:583-584 (UsageStats.billable_input_tokens):
    non_cache = input - cache_read - cache_creation
    billable  = non_cache + cache_creation×1.25 + cache_read×0.10
但这里用**用户配置的真实价格**算钱 (不是 Anthropic 系数):
    cost = non_cache·input价 + cache_read·cache_read价
         + cache_creation·cache_creation价(缺省 input×1.25) + output·output价
"""
from __future__ import annotations

import time

# 简易 mtime 缓存: {provider_id: (mtime, pricing_dict)}
_PRICING_CACHE: dict[str, tuple[float, dict | None]] = {}


def load_pricing(provider_id: str | None = None, model: str = "") -> dict | None:
    """从 provider_configs 读一条 config 的 pricing.

    provider_id 为空时按 model 名模糊匹配 (找 model 相同且配了价的 config)。
    mtime 缓存避免每次读盘。
    """
    try:
        from workers.provider_configs import load_configs

        data = load_configs()
        cfg = None
        if provider_id:
            for c in data.get("configs") or []:
                if c.get("id") == provider_id:
                    cfg = c
                    break
        elif model:
            # 模糊匹配: model 相同且配了价的最优先
            priced = [c for c in data.get("configs") or [] if c.get("model") == model and c.get("pricing")]
            if priced:
                cfg = priced[0]
        if not cfg:
            return None
        p = cfg.get("pricing") or {}
        return p if p else None
    except Exception:
        return None


def calc_cost(usage: dict, pricing: dict | None) -> dict:
    """按 usage × pricing 算钱.

    usage 字段: input_tokens / output_tokens / cache_read_tokens / cache_creation_tokens
    pricing 字段 (每 1M tokens): currency / input / output / cache_read / cache_creation
    缺项按 0 计并标 unpriced 子项 · pricing 整体缺失 → 返回 None-equivalent {"total": None}
    """
    if not pricing:
        return {"total": None, "currency": None, "breakdown": {}, "unpriced": True}

    inp = usage.get("input_tokens") or 0
    out = usage.get("output_tokens") or 0
    cre = usage.get("cache_creation_tokens") or 0
    crd = usage.get("cache_read_tokens") or 0
    non_cache = max(0, inp - crd - cre)

    p_in = pricing.get("input")
    p_out = pricing.get("output")
    p_cr = pricing.get("cache_read")
    p_cc = pricing.get("cache_creation") or (p_in * 1.25 if p_in is not None else None)

    # 关键价缺项 → 整体算不出钱
    if p_in is None and p_out is None:
        return {"total": None, "currency": pricing.get("currency"), "breakdown": {}, "unpriced": True}

    cost_in = non_cache * (p_in or 0) / 1_000_000
    cost_cr = crd * (p_cr or 0) / 1_000_000
    cost_cc = cre * (p_cc or 0) / 1_000_000
    cost_out = out * (p_out or 0) / 1_000_000
    total = cost_in + cost_cr + cost_cc + cost_out

    return {
        "total": round(total, 6),
        "currency": pricing.get("currency") or "USD",
        "breakdown": {
            "non_cache": round(cost_in, 6),
            "cache_read": round(cost_cr, 6),
            "cache_creation": round(cost_cc, 6),
            "output": round(cost_out, 6),
        },
        "unpriced": False,
    }


# ---------- 官方查价 ----------

def preset_model_price(preset_id: str, model: str) -> dict | None:
    """从 preset.recommended_models 的 label 解析官方价 (wish-bec4f3b9 · 查价优先走这条).

    label 约定: "DeepSeek V4 Flash · $0.14/M in · $0.28/M out · cache hit $0.0028/M"
    解析出 {currency, input, output, cache_read} (每 1M tokens · USD)。
    解析失败返 None (调用方落网页抓取兜底)。
    """
    import re

    try:
        from provider_presets import PRESETS
    except Exception:
        return None
    for p in PRESETS:
        if p.id != preset_id:
            continue
        for m in getattr(p, "recommended_models", None) or []:
            if m.get("id") != model:
                continue
            label = m.get("label") or ""
            # 匹配 "$x.xx/M in" "$x.xx/M out" "cache hit $x.xx/M"
            def _find_price(pattern: str) -> float | None:
                mm = re.search(pattern, label, re.IGNORECASE)
                return float(mm.group(1)) if mm else None
            price_in = _find_price(r"\$\s*(\d+(?:\.\d+)?)\s*/M\s*(?:in|input|prompt)")
            price_out = _find_price(r"\$\s*(\d+(?:\.\d+)?)\s*/M\s*(?:out|output|completion)")
            price_cr = _find_price(r"(?:cache\s*(?:hit|read)|缓存命中)\s*\$\s*(\d+(?:\.\d+)?)\s*/M")
            if price_in is None and price_out is None:
                return None
            return {
                "currency": "USD",
                "input": price_in,
                "output": price_out,
                "cache_read": price_cr,
            }
    return None


def fetch_official_pricing(url: str, model: str = "") -> dict:
    """抓官方定价页 → 提取 {currency, input, output, cache_read} (每 1M tokens).

    纯文本关键词提取 (不调 LLM · 快且省):
      - 找 "$x.xx / 1M tokens" 或 "¥x.xx / 百万 tokens" 模式的价
      - input/output/cache 用上下文词 (input/输入/输入价 vs output/输出 vs cache/缓存) 分档
    解析失败 raise ValueError(带原文片段 · 路由转 422 让用户手填)。
    """
    import re

    try:
        import httpx
    except Exception:
        raise ValueError("httpx 不可用")

    try:
        r = httpx.get(url, timeout=8, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        r.raise_for_status()
        text = r.text
    except Exception as e:
        raise ValueError(f"抓取失败: {e}")

    # 找价格模式: $x.xx 或 ¥x.xx (带小数 · 可能是每 1M/每百万)
    currency = "USD" if "$" in text[:5000] else ("CNY" if "¥" in text[:5000] else "USD")
    pat = re.compile(r"[\$¥]\s*(\d+(?:\.\d+)?)")
    nums = [float(m) for m in pat.findall(text)]
    if not nums:
        raise ValueError("未在页面找到 $x.xx 价格模式")

    # 按上下文词分档: 取每组第一个数 (页面通常按 input/output/cache 顺序排)
    lower = text.lower()
    def _section_price(keywords):
        # 从关键词第一次出现位置往后找第一个价格
        for kw in keywords:
            idx = lower.find(kw)
            if idx >= 0:
                m = pat.search(text[idx:idx + 3000])
                if m:
                    return float(m.group(1))
        return None

    price_in = _section_price(["input", "输入价", "输入", "prompt"])
    price_out = _section_price(["output", "输出价", "输出", "completion"])
    price_cr = _section_price(["cache read", "缓存命中", "cache_hit", "缓存读取"])

    if price_in is None and price_out is None:
        # 兜底: 顺序取前两个数当 input/output (很多页就按这个排)
        if len(nums) >= 2:
            price_in, price_out = nums[0], nums[1]
        elif len(nums) == 1:
            price_in = nums[0]

    out = {"currency": currency, "input": price_in, "output": price_out, "cache_read": price_cr}
    if price_in is None and price_out is None:
        raise ValueError("提取不到输入/输出价")
    return out


# 会话级缓存 · 防频繁查价
_LOOKUP_CACHE: dict[str, tuple[float, dict]] = {}
_LOOKUP_TTL = 3600  # 1h


def cached_lookup(url: str, model: str = "") -> dict:
    """带 1h TTL 的查价封装 · 路由层调用这个. 失败不缓存."""
    key = f"{url}|{model}"
    now = time.time()
    hit = _LOOKUP_CACHE.get(key)
    if hit and now - hit[0] < _LOOKUP_TTL:
        return hit[1]
    out = fetch_official_pricing(url, model)
    _LOOKUP_CACHE[key] = (now, out)
    return out
