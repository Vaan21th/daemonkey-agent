"""
workers/rate_limiter.py
=======================

API 限流 · token-bucket 算法 · 卷四十六 III 补丁 5 · Y7

设计 (wish-beb3e):
  - per-IP + per-token-hash 两套 bucket · 任一超限就拒
  - 内存里维护 · 单进程一份 · 不跨进程同步 (daemon 单实例足够)
  - default 全部禁用 (env=0)

env:
  OPUS_RATELIMIT_PER_MIN  每分钟最多请求数 (default 0 = off)
  OPUS_RATELIMIT_BURST    瞬时突发容量 (default = per_min · 即 1 分钟全用满也能瞬发)

算法:
  - 每个 key (ip 或 token hash) 一个 bucket
  - 容量 burst · 每秒补 rate/60 个 token
  - 每个请求消耗 1 个 token · 没了拒绝
  - 拒绝时返回 retry_after_s (粗略估算)

性能:
  - check() 是 O(1) · 不扫历史
  - GC: bucket 30 分钟未使用就清掉
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass, field

# ---------- 配置 ----------

def _env_int(name: str, default: int = 0) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
        return v if v >= 0 else default
    except (ValueError, TypeError):
        return default


def get_config() -> dict:
    """当前生效的限流配置 · 0 = 禁用"""
    per_min = _env_int("OPUS_RATELIMIT_PER_MIN")
    burst = _env_int("OPUS_RATELIMIT_BURST", per_min)
    return {
        "per_min": per_min,
        "burst": max(burst, per_min) if per_min > 0 else 0,
        "enabled": per_min > 0,
    }


# ---------- bucket ----------

@dataclass
class _Bucket:
    tokens: float = 0.0
    last_refill: float = field(default_factory=time.monotonic)
    last_seen: float = field(default_factory=time.monotonic)


_BUCKETS: dict[str, _Bucket] = {}
_LOCK = threading.Lock()
_GC_INTERVAL_S = 300.0  # 每 5 分钟 GC 一次
_GC_IDLE_S = 1800.0     # 30 分钟不用就清
_last_gc = time.monotonic()


def _gc_locked() -> None:
    global _last_gc
    now = time.monotonic()
    if now - _last_gc < _GC_INTERVAL_S:
        return
    _last_gc = now
    stale = [k for k, b in _BUCKETS.items() if now - b.last_seen > _GC_IDLE_S]
    for k in stale:
        _BUCKETS.pop(k, None)


def _refill(bucket: _Bucket, rate_per_s: float, capacity: float, now: float) -> None:
    elapsed = max(0.0, now - bucket.last_refill)
    bucket.tokens = min(capacity, bucket.tokens + elapsed * rate_per_s)
    bucket.last_refill = now


def _hash_token(token: str) -> str:
    """token 不能落硬盘 / 不能日志 · 只存 hash 前 12 位"""
    if not token:
        return "anon"
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


# ---------- 主入口 ----------

def check(ip: str | None, token: str | None) -> dict:
    """检查 (ip, token) 是否允许通过

    Returns:
        {
            "ok": bool,           # True 通过 · False 拒
            "retry_after_s": float,  # 0 表示无限制 · >0 表示拒后多久重试
            "remaining_ip": float,
            "remaining_token": float,
            "enabled": bool,
        }
    """
    cfg = get_config()
    if not cfg["enabled"]:
        return {
            "ok": True,
            "retry_after_s": 0.0,
            "remaining_ip": -1.0,
            "remaining_token": -1.0,
            "enabled": False,
        }

    per_min = cfg["per_min"]
    burst = float(cfg["burst"])
    rate_per_s = per_min / 60.0

    now = time.monotonic()
    keys = [
        ("ip:" + (ip or "unknown")),
        ("tk:" + _hash_token(token or "")),
    ]
    result_ok = True
    remaining = {"ip": -1.0, "token": -1.0}
    retry_after = 0.0

    with _LOCK:
        _gc_locked()
        for k, kind in zip(keys, ["ip", "token"]):
            bucket = _BUCKETS.get(k)
            if bucket is None:
                bucket = _Bucket(tokens=burst, last_refill=now)
                _BUCKETS[k] = bucket
            _refill(bucket, rate_per_s, burst, now)
            bucket.last_seen = now
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                remaining[kind] = bucket.tokens
            else:
                # 拒了 · 但不能因为 ip 拒就忽略 token 的扣减——保持简单只在第一个拒的地方算 retry
                if result_ok:
                    needed = 1.0 - bucket.tokens
                    retry_after = needed / rate_per_s if rate_per_s > 0 else 60.0
                result_ok = False
                remaining[kind] = bucket.tokens

    return {
        "ok": result_ok,
        "retry_after_s": round(retry_after, 2),
        "remaining_ip": round(remaining["ip"], 2),
        "remaining_token": round(remaining["token"], 2),
        "enabled": True,
    }


def reset_all() -> None:
    """测试 / 排障用 · 清掉所有 bucket"""
    with _LOCK:
        _BUCKETS.clear()


def snapshot() -> dict:
    """状态查看 · 给 /api/ratelimit/status endpoint 用 (含 ip/token hash · 不含 token 明文)"""
    cfg = get_config()
    with _LOCK:
        active = []
        for k, b in list(_BUCKETS.items()):
            active.append({
                "key": k,
                "tokens": round(b.tokens, 2),
                "idle_s": round(time.monotonic() - b.last_seen, 1),
            })
    return {
        "config": cfg,
        "active_buckets": len(active),
        "samples": active[:20],
    }
