"""workers/workshop_registry.py
================================

沉淀闭环 v2 · 刀① · app 资产登记 (asset registry) · 2026-06-10

为什么有这个模块
------------------
2026-06-09 真实事故: 用户花一下午打磨了三版声音克隆 (只有第三版才能用) ·
但"选定哪版"只活在对话上下文里 · app json 钉死的还是废掉的第一版 ·
换个对话 AI 就会拿废版配音。用户原话: "每次做事都没有沉淀 · 还不如自己做"。

解法 = 把"用户的个性资产"从对话记忆变成工程层登记表:
  - app json 里 asset_slots 字段【声明】需要哪些资产 (app_spec_guard 校验)
  - 本模块【存取】真值 · data/workshop/assets/<app_id>.json
  - 带版本历史 · 覆盖旧值自动留痕 · 永不静默丢失
  - WebUI 配置页 = 这张表的 UI 表面 (后续接)

跟 app_secrets.py 的关系 (刻意镜像它的结构):
  - secrets = 凭证 · 敏感 · LLM 只见 placeholder 不见真值
  - assets  = 业务资产 (voice_id / IP 图路径 / 风格参考) · 不敏感 · LLM 可直接读写
  - 两者目录互不相干: secrets/ vs assets/ · 不互相 import

落点
----
- 文件: data/workshop/assets/<app_id>.json (进 git 由 .gitignore 现行策略决定)
- app_id 可用 "_shared" · 跨 app 共享资产 (IP 形象 / 品牌色这种不属于单一 app 的)
- 数据: {"app_id": "...", "assets": {name: {type, label, value, updated_at, note, history: [...]}}}
- history: 每次覆盖把旧值压栈 · 最多留 10 条 · 治"打磨三版只剩第一版"的根
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT / "data" / "workshop" / "assets"

SHARED_ID = "_shared"
_HISTORY_MAX = 10
_VALUE_MAX_BYTES = 64 * 1024  # 资产存"值/路径/小JSON" · 不存大文件本体 (图/音落 outputs · 这里存路径)

_VALID_ASSET_TYPES = {"text", "json", "images", "file"}


def _atomic_write(path: Path, content: str) -> None:
    from .safe_write import atomic_write_text
    atomic_write_text(path, content, backup=True)


def _validate_app_id(app_id: str) -> str:
    app_id = (app_id or "").strip()
    if not app_id:
        raise ValueError("app_id 必填 (app-xxxxxxxx 或 '_shared')")
    if app_id != SHARED_ID and not app_id.startswith("app-"):
        raise ValueError(f"app_id 必须以 'app-' 开头或为 '{SHARED_ID}': {app_id!r}")
    if any(c in app_id for c in ("/", "\\", "..", "\x00")):
        raise ValueError(f"app_id 不允许特殊字符: {app_id!r}")
    if len(app_id) > 64:
        raise ValueError(f"app_id 太长 (>64): {app_id!r}")
    return app_id


def _validate_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ValueError("asset name 必填")
    if not name.replace("_", "").isalnum() or name[0].isdigit():
        raise ValueError(f"asset name 必须是 [a-zA-Z_][a-zA-Z0-9_]*: {name!r}")
    if len(name) > 64:
        raise ValueError(f"asset name 太长 (>64): {name!r}")
    return name


def _path(app_id: str) -> Path:
    return ASSETS_DIR / f"{_validate_app_id(app_id)}.json"


def _iso_now() -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _load(app_id: str) -> dict:
    fp = _path(app_id)
    if not fp.exists():
        return {"app_id": app_id, "assets": {}}
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"app_id": app_id, "assets": {}}
    if not isinstance(data, dict) or not isinstance(data.get("assets"), dict):
        return {"app_id": app_id, "assets": {}}
    return data


def _save(data: dict) -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write(_path(data["app_id"]), json.dumps(data, ensure_ascii=False, indent=2))


# ── 公开 API ────────────────────────────────────────

def set_asset(
    app_id: str,
    name: str,
    value: object,
    *,
    asset_type: str = "text",
    label: str = "",
    note: str = "",
) -> dict:
    """写一个资产 · 已存在则覆盖 · 旧值自动压进 history (永不静默丢失)

    value: str 或可 JSON 序列化的 dict/list。大文件 (图/音) 不存这里 · 存其路径。
    note:  这次写入的一句话说明 (例 "第三版克隆·用户试听满意") · 强烈建议填。
    """
    app_id = _validate_app_id(app_id)
    name = _validate_name(name)
    asset_type = (asset_type or "text").strip().lower()
    if asset_type not in _VALID_ASSET_TYPES:
        raise ValueError(f"asset_type 必须是 {sorted(_VALID_ASSET_TYPES)}: {asset_type!r}")
    try:
        serialized = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        raise ValueError("value 必须是 str 或可 JSON 序列化的 dict/list")
    if len(serialized.encode("utf-8")) > _VALUE_MAX_BYTES:
        raise ValueError(
            f"value 太大 (>{_VALUE_MAX_BYTES // 1024}KB) · 大文件落 outputs/ · 这里只存路径/小JSON"
        )

    data = _load(app_id)
    now = _iso_now()
    entry = data["assets"].get(name)

    if entry and isinstance(entry, dict):
        history = list(entry.get("history") or [])
        history.append({
            "value": entry.get("value"),
            "note": entry.get("note") or "",
            "replaced_at": now,
            "was_set_at": entry.get("updated_at") or "",
        })
        history = history[-_HISTORY_MAX:]
    else:
        history = []

    data["assets"][name] = {
        "type": asset_type,
        "label": (label or (entry or {}).get("label") or name) if isinstance(entry, dict) else (label or name),
        "value": value,
        "note": (note or "").strip(),
        "updated_at": now,
        "history": history,
    }
    _save(data)
    return {
        "ok": True,
        "app_id": app_id,
        "name": name,
        "updated_at": now,
        "history_count": len(history),
    }


def get_asset(app_id: str, name: str) -> Optional[dict]:
    """读单个资产完整条目 (含 value/note/updated_at/history) · 不存在返 None"""
    app_id = _validate_app_id(app_id)
    name = _validate_name(name)
    entry = _load(app_id)["assets"].get(name)
    return dict(entry) if isinstance(entry, dict) else None


def get_asset_value(app_id: str, name: str) -> object:
    """只取 value · 给 daemon 内部 resolve / 拼 prompt 用 · 不存在返 None"""
    entry = get_asset(app_id, name)
    return entry.get("value") if entry else None


def list_assets(app_id: str) -> list[dict]:
    """列一个 app 的全部资产 (含 value 摘要 · 不含 history)"""
    app_id = _validate_app_id(app_id)
    out: list[dict] = []
    for name, entry in sorted(_load(app_id)["assets"].items()):
        if not isinstance(entry, dict):
            continue
        preview = json.dumps(entry.get("value"), ensure_ascii=False)
        if len(preview) > 200:
            preview = preview[:200] + "…"
        out.append({
            "name": name,
            "type": entry.get("type") or "text",
            "label": entry.get("label") or name,
            "note": entry.get("note") or "",
            "updated_at": entry.get("updated_at") or "",
            "value_preview": preview,
            "history_count": len(entry.get("history") or []),
        })
    return out


def delete_asset(app_id: str, name: str) -> bool:
    """删一个资产 · 真删 (history 一起) · 返 True 表示删了"""
    app_id = _validate_app_id(app_id)
    name = _validate_name(name)
    data = _load(app_id)
    if name not in data["assets"]:
        return False
    del data["assets"][name]
    if data["assets"]:
        _save(data)
    else:
        try:
            _path(app_id).unlink()
        except OSError:
            pass
    return True
