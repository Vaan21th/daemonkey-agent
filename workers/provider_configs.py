"""
workers/provider_configs.py
===========================

卷三十七 · 多 LLM Provider 配置管理

为什么这个文件存在：
  - 之前 .env 里只能存一个 OPUS_BASE_URL / OPUS_MODEL / OPUS_API_KEY
  - BRO 想"我要同时存 DeepSeek 官方 V4 Pro / V4 Flash / AiHubMix Claude Opus 4.7"
  - 然后右上角切换器从勾选 (pinned) 的几个里选 · 不重启 daemon

数据形态：
  data/provider_configs.json
  {
    "version": 1,
    "active_id": "cfg-xxx",       # 当前活动配置 (daemon 用它跑)
    "configs": [
      {
        "id": "cfg-xxx",
        "name": "DeepSeek V4 Pro · 官方",
        "provider_kind": "openai" | "anthropic",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-pro",
        "api_key": "sk-xxx",        # 明文 · 文件在 .gitignore 内
        "preset_id": "deepseek-official",  # 关联 provider_presets · 拿 icon / note
        "pinned": true,             # 右上角切换器是否显示
        "created_at": "2026-05-24T17:00:00",
        "updated_at": "2026-05-24T17:00:00"
      }
    ]
  }

安全：
  - api_key 是明文 · 但文件在 .gitignore 内 · 不 commit
  - 跟 .env 同样的"信任本机磁盘"假设
  - 如果以后要加密 · 在 load_configs / save_configs 中间加一层 fernet 即可

冷启动迁移 (首次跑这个文件)：
  - 没有 provider_configs.json → 从 .env 读 OPUS_BASE_URL / OPUS_MODEL / OPUS_API_KEY
  - 自动生成一条 config (pinned=True · 默认 active)
  - 这样老用户升级无缝
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CONFIGS_PATH = DATA_DIR / "provider_configs.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _new_id() -> str:
    return "cfg-" + uuid.uuid4().hex[:10]


def _migrate_from_env() -> dict:
    """首次跑·从 .env 读当前配置·生成第一条 cfg.

    .env 里没配 (新装机) · 也生成空骨架。
    """
    api_key = (os.environ.get("ANTHROPIC_API_KEY")
               or os.environ.get("OPUS_API_KEY") or "").strip()
    base_url = (os.environ.get("OPUS_BASE_URL") or "").strip()
    model = (os.environ.get("OPUS_MODEL") or "").strip()
    explicit_provider = (os.environ.get("OPUS_PROVIDER") or "").strip().lower()

    if explicit_provider in ("openai", "anthropic"):
        provider_kind = explicit_provider
    elif "anthropic.com" in (base_url or "").lower():
        provider_kind = "anthropic"
    elif base_url:
        provider_kind = "openai"
    else:
        provider_kind = "anthropic"

    # 没有任何配置·返回空骨架
    if not api_key and not model:
        return {"version": 1, "active_id": None, "configs": []}

    cfg_id = _new_id()
    preset_id = _guess_preset_id(base_url, provider_kind)
    name = _guess_name(preset_id, model)

    return {
        "version": 1,
        "active_id": cfg_id,
        "configs": [{
            "id": cfg_id,
            "name": name,
            "provider_kind": provider_kind,
            "base_url": base_url,
            "model": model,
            "api_key": api_key,
            "preset_id": preset_id,
            "pinned": True,
            "created_at": _now(),
            "updated_at": _now(),
        }],
    }


def _guess_preset_id(base_url: str, provider_kind: str) -> str:
    try:
        from provider_presets import guess_preset_id
        return guess_preset_id(base_url or "", provider_kind)
    except Exception:
        return "custom"


def _guess_name(preset_id: str, model: str) -> str:
    """给一条 config 取个人话名字 · BRO 在 UI 上能识别."""
    preset_label = {
        "deepseek-official": "DeepSeek 官方",
        "aihubmix": "AiHubMix",
        "anthropic": "Anthropic 官方",
        "openrouter": "OpenRouter",
        "dashscope": "DashScope",
        "custom": "自定义",
    }.get(preset_id, preset_id)
    return f"{preset_label} · {model}" if model else preset_label


def _atomic_write(path: Path, content: str) -> None:
    """卷四十六 III · wish-badd4 收编到 safe_write
    provider_configs.json 是 LLM 接口配置 (API key / base_url)·backup=True"""
    from .safe_write import atomic_write_text
    atomic_write_text(path, content, backup=True)


def load_configs() -> dict:
    """加载 provider configs · 文件不存在就从 .env 迁移.

    卷三十八 · 自动 backfill 老 config 没 max_tokens 字段的 · 按模型查推荐值.
    """
    if not CONFIGS_PATH.exists():
        data = _migrate_from_env()
        save_configs(data)
        return data
    try:
        data = json.loads(CONFIGS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = _migrate_from_env()
        save_configs(data)
        return data

    # backfill max_tokens · 老 config 没这个字段就按推荐值补
    changed = False
    try:
        from provider_presets import recommended_max_tokens
        for c in data.get("configs") or []:
            if not c.get("max_tokens"):
                c["max_tokens"] = recommended_max_tokens(c.get("model") or "")
                changed = True
    except Exception:
        pass
    if changed:
        save_configs(data)
    return data


def save_configs(data: dict) -> None:
    # 卷五十四 · B3 结构闸: configs 非 list / 缺 id / provider_kind 非法 → 拒写 (写坏了 daemon 起不来)
    from workers.schema_guard import validate_provider_configs
    validate_provider_configs(data)
    _atomic_write(CONFIGS_PATH, json.dumps(data, ensure_ascii=False, indent=2))


def mask_key(key: str) -> str:
    if not key:
        return ""
    # 卷三十八 · 占位符 key (来自 quickImport) · 友好提示
    if key == "___placeholder___":
        return "⚠ 待填 · 点编辑填上 key"
    if len(key) <= 12:
        return "***"
    return key[:6] + "****" + key[-4:]


def list_configs(include_keys: bool = False) -> dict:
    """给 UI 列表用 · 默认掩码 api_key.

    Returns:
      {
        "active_id": "cfg-xxx",
        "configs": [...]   # configs 排序: pinned 在前 · 同档按 updated_at desc
      }
    """
    data = load_configs()
    configs = data.get("configs") or []

    def _key_sort(c):
        return (
            0 if c.get("pinned") else 1,
            -(_parse_ts(c.get("updated_at") or c.get("created_at") or "")),
        )

    sorted_cfgs = sorted(configs, key=_key_sort)
    out = []
    for c in sorted_cfgs:
        c2 = dict(c)
        if not include_keys:
            c2["api_key"] = mask_key(c2.get("api_key") or "")
            c2["api_key_masked"] = True
        out.append(c2)
    return {
        "active_id": data.get("active_id"),
        "configs": out,
    }


def _parse_ts(ts: str) -> float:
    try:
        return datetime.fromisoformat(ts).timestamp()
    except (ValueError, TypeError):
        return 0.0


def get_config(cfg_id: str, include_key: bool = True) -> Optional[dict]:
    """按 id 取一条 config · 默认带真 api_key (服务端内部用)."""
    data = load_configs()
    for c in data.get("configs") or []:
        if c.get("id") == cfg_id:
            if not include_key:
                c = dict(c)
                c["api_key"] = mask_key(c.get("api_key") or "")
            return c
    return None


def get_active_config(include_key: bool = True) -> Optional[dict]:
    data = load_configs()
    active = data.get("active_id")
    if not active:
        return None
    return get_config(active, include_key=include_key)


def add_config(
    *,
    name: str,
    provider_kind: str,
    base_url: str,
    model: str,
    api_key: str,
    preset_id: str = "custom",
    pinned: bool = True,
    set_active: bool = False,
    max_tokens: int | None = None,
    vision: bool | None = None,
) -> dict:
    """新增一条 config.

    卷三十八 · max_tokens 没指定时·按 model 查推荐值 (provider_presets.recommended_max_tokens).
    """
    if not name or not provider_kind or not model or not api_key:
        raise ValueError("name / provider_kind / model / api_key are required")
    if provider_kind not in ("openai", "anthropic"):
        raise ValueError(f"unknown provider_kind: {provider_kind}")

    if max_tokens is None or max_tokens <= 0:
        try:
            from provider_presets import recommended_max_tokens
            max_tokens = recommended_max_tokens(model.strip())
        except Exception:
            max_tokens = 8192

    data = load_configs()
    cfg = {
        "id": _new_id(),
        "name": name.strip(),
        "provider_kind": provider_kind,
        "base_url": (base_url or "").strip(),
        "model": model.strip(),
        "api_key": api_key.strip(),
        "preset_id": preset_id or "custom",
        "pinned": bool(pinned),
        "max_tokens": int(max_tokens),
        "vision": vision,  # wish-4a6331b2 · None=自动按模型族判断 / True=多模态 / False=纯文本
        "created_at": _now(),
        "updated_at": _now(),
    }
    data.setdefault("configs", []).append(cfg)
    if set_active or not data.get("active_id"):
        data["active_id"] = cfg["id"]
    save_configs(data)
    return cfg


def update_config(cfg_id: str, patch: dict) -> dict:
    """局部更新一条 config · 只能改: name / base_url / model / api_key / pinned / preset_id / max_tokens."""
    ALLOWED = {"name", "base_url", "model", "api_key", "pinned", "preset_id", "max_tokens", "vision"}
    data = load_configs()
    for c in data.get("configs") or []:
        if c.get("id") == cfg_id:
            for k, v in (patch or {}).items():
                if k in ALLOWED:
                    # api_key 空字符串 = 不改 (避免误清空)
                    if k == "api_key" and not (v or "").strip():
                        continue
                    # max_tokens 必须正整数
                    if k == "max_tokens":
                        try:
                            v = int(v)
                            if v <= 0:
                                continue
                        except (ValueError, TypeError):
                            continue
                    c[k] = v.strip() if isinstance(v, str) else v
            c["updated_at"] = _now()
            save_configs(data)
            return c
    raise KeyError(f"config not found: {cfg_id}")


def delete_config(cfg_id: str) -> dict:
    data = load_configs()
    configs = data.get("configs") or []
    new_configs = [c for c in configs if c.get("id") != cfg_id]
    if len(new_configs) == len(configs):
        raise KeyError(f"config not found: {cfg_id}")
    data["configs"] = new_configs
    # 删了 active · 换一个 pinned 在前的
    if data.get("active_id") == cfg_id:
        pinned = [c for c in new_configs if c.get("pinned")]
        data["active_id"] = (pinned[0]["id"] if pinned
                             else (new_configs[0]["id"] if new_configs else None))
    save_configs(data)
    return {"deleted": cfg_id, "new_active": data.get("active_id")}


def set_active(cfg_id: str) -> dict:
    """切换 active config · 不重建 RUNTIME (那是 daemon_api 的事)."""
    data = load_configs()
    found = any(c.get("id") == cfg_id for c in (data.get("configs") or []))
    if not found:
        raise KeyError(f"config not found: {cfg_id}")
    data["active_id"] = cfg_id
    save_configs(data)
    return get_config(cfg_id, include_key=False)


def toggle_pin(cfg_id: str, pinned: bool) -> dict:
    return update_config(cfg_id, {"pinned": bool(pinned)})


def apply_config_to_env(cfg: dict) -> None:
    """把一条 config 的字段同步到 os.environ · 让 setup_client / detect_provider 沿用旧路径.

    daemon 启动 / 热切换都调这个 · 然后再 setup_client(provider_kind).
    """
    if not cfg:
        return
    pkind = cfg.get("provider_kind") or "openai"
    base = cfg.get("base_url") or ""
    model = cfg.get("model") or ""
    key = cfg.get("api_key") or ""
    os.environ["OPUS_PROVIDER"] = pkind
    if base:
        os.environ["OPUS_BASE_URL"] = base
    if model:
        os.environ["OPUS_MODEL"] = model
    if pkind == "anthropic":
        os.environ["ANTHROPIC_API_KEY"] = key
    else:
        os.environ["OPUS_API_KEY"] = key
