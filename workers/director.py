"""workers/director.py
=========================

wish-8ffb9d65 · 顾问模型 (内部字段名 director · UI/用户视角 2026-07-28 BRO 拍板改称「顾问」) · 配置读取 + client 构建 + 唤醒纪律文案。

设计 (2026-07-27 BRO 拍板 · 动机: K3 全量跑日常+vibe coding 日烧 ~¥100 不可持续):
  执行层 (主对话 + 分身) 常驻便宜模型 (DeepSeek) · 贵模型 (如 K3) 降级为【顾问】·
  只在三个唤醒点进场: ① 蓝图(blueprint) ② 破局(unstick) ③ 验收(review)。

  总监标记跟着 provider 配置走 (provider_configs.json 的 director 字段 · 与 vision 标注同构):
  标记里自带 base_url + api_key · 召唤总监时现场建 client · 天然解决跨 provider ·
  无需常驻第二连接 (总监调用是低频事件 · 常驻是浪费)。

零回归红线: 没配 director → get_director_config() 返回 None → 调用方走老路
(主模型当顾问 · subagent_runner 的 used_model = model or runtime.model)。
"""

from __future__ import annotations

from typing import Any, Optional

# provider_configs.json 读取缓存 (与 model_aliases._VISION_CFG_CACHE 同构 · mtime 失效)
_CACHE: dict = {"mtime": 0.0, "cfg": None}


def get_director_config() -> Optional[dict]:
    """读 provider_configs.json · 返回 director=true 的那条配置 (含 api_key 真值 · 仅内部用)。

    多条都标了 director → 取列表里第一条 (UI 层引导只标一条 · 后端不强制互斥)。
    没配 / 读失败 → None (调用方走零回归老路)。 任何异常都吞掉返 None (不拖累主链路)。
    """
    try:
        from pathlib import Path
        cfg_path = Path(__file__).resolve().parent.parent / "data" / "provider_configs.json"
        mtime = cfg_path.stat().st_mtime
        if mtime != _CACHE["mtime"]:
            import json
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            found = None
            for c in (data.get("configs") or []):
                if c.get("director"):
                    found = c
                    break
            _CACHE["cfg"] = found
            _CACHE["mtime"] = mtime
        return _CACHE["cfg"]
    except Exception:
        return None


def build_director_client(cfg: dict) -> Any:
    """按总监配置现场建一个 OpenAI 兼容 client (base_url + api_key 都来自该配置)。

    provider_kind != openai 的配置 (如 anthropic 原生) subagent tool_loop 走不通 →
    抛 ValueError · 上层 (replan) 捕获后回退主模型顾问并注明原因。
    """
    if (cfg.get("provider_kind") or "openai") != "openai":
        raise ValueError(
            f"总监配置 provider_kind={cfg.get('provider_kind')!r} 不支持 (仅 openai 兼容)"
        )
    from daemon_provider import _create_robust_openai_client
    return _create_robust_openai_client(
        base_url=(cfg.get("base_url") or "").strip() or None,
        api_key=(cfg.get("api_key") or "").strip(),
    )


def director_wake_prompt() -> str:
    """soul_loader 注入用: 配了顾问 → 返回三唤醒点纪律文案; 没配 → 空串 (零污染)。"""
    cfg = get_director_config()
    if not cfg:
        return ""
    name = (cfg.get("name") or cfg.get("model") or "顾问模型").strip()
    model = (cfg.get("model") or "").strip()
    return (
        f"## 顾问模型 · 三唤醒点 (wish-8ffb9d65 · 当前顾问: {name})\n\n"
        f"你(主对话)是【执行者】· 贵模型({model})是【顾问】· 它只在三个时刻通过 `replan` 进场 "
        "(干净上下文 · 不装灵魂 · 每次召唤现场建独立 client):\n"
        "  ① 蓝图 · 复杂工程任务开工前 → `replan(mode='blueprint', goal=...)` · 拿回【结构化施工单】"
        "(改哪个文件/怎么改/别碰什么/验收标准) · 落 track_task 账本再动手\n"
        "  ② 破局 · 连续失败 2 次卡住 → `replan(blocker=...)` (默认 mode=unstick) · 带回破局方案\n"
        "  ③ 验收 · 有副作用的任务交付前 → `replan(mode='review', goal=原蓝图, blocker=交付说明+diff摘要)` · "
        "拿 pass/fail + 理由\n"
        "**成本纪律**: 顾问贵 · 只在三唤醒点召唤 · 别拿它闲聊/查资料/干活——执行是你(主对话)的活。 "
        "三唤醒点之间用 track_task 账本传状态 (蓝图与结论落账 · 召唤时自动带给顾问)。\n\n"
    )
