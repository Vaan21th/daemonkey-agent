"""workers/workshop_app_versions.py
====================================

沉淀闭环 v2 · 刀④ · app 版本快照 (2026-06-10)

为什么需要这个
----------------
刀①已经给 app 加了 version / updated_at / changelog 三个字段(meta 层)·
但 app 内容本身被覆盖后就没了。 用户真要回到 "v2 的 prompt 是什么样" 没办法 ·
update_app 改坏了也不能 rollback。 这一刀补上"内容层"的留痕。

落点
----
`data/workshop/apps/_versions/<app_id>/v<N>.json` (gitignored · 跟 outputs/runs 同语义)

约束 (跟 registry history 思路一致):
- 仅在 update 路径快照 (prev 存在才快照新覆盖前的状态)
- 创建新 app 不快照 (没东西可快照)
- 保留最近 30 版 (打磨型 app 一周翻几十版很正常 · 远超 registry 的 10)
- 失败永不阻塞 save_app 主路径 (沉默吞异常 · 跟 _increment_runs 同语义)

为什么不重用 changelog 字段
---------------------------
changelog 只存 {v, at, note} 元数据 (人话日志) · 不存内容。
内容快照走文件 · 跟 changelog 通过 version 数字串起来。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
APPS_DIR = ROOT / "data" / "workshop" / "apps"
VERSIONS_DIR = APPS_DIR / "_versions"

_MAX_VERSIONS = 30


def _aid_dir(aid: str) -> Path:
    return VERSIONS_DIR / aid


def snapshot(prev: dict) -> Optional[str]:
    """把 prev (覆盖前的状态) 快照成 v<N>.json · 返回快照路径相对 ROOT (失败返 None)

    N 取自 prev.version (刀①已经保证 update_app 进来时 version 已经+1 · 这里存的是
    *之前那一版* 的版本号——即 prev.version 减 1 的版本号。 等等 · 重读 save_app 逻辑:

    save_app 里:
        version = prev.version + 1  # 写进 payload
        snapshot(prev)              # 此时 prev.version 还是旧值
    所以 N = prev.version (旧 version 号 · 这正是这份内容对应的版本号)。
    """
    aid = prev.get("id") if isinstance(prev, dict) else None
    if not aid or not isinstance(aid, str) or not aid.startswith("app-"):
        return None

    try:
        version = int(prev.get("version") or 1)
    except Exception:
        version = 1

    target_dir = _aid_dir(aid)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"v{version}.json"

    if target.exists():
        # 同 version 已快照过 · 不重复 (理论上不会发生 · 兜底防 race)
        return None

    try:
        target.write_text(json.dumps(prev, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return None

    _prune(target_dir)
    return f"data/workshop/apps/_versions/{aid}/v{version}.json"


def _prune(target_dir: Path) -> None:
    """超过 _MAX_VERSIONS 时删最老的几版 (按数字而非 mtime · 防时间戳错位)"""
    try:
        files = sorted(
            target_dir.glob("v*.json"),
            key=lambda p: int(p.stem[1:]) if p.stem[1:].isdigit() else 0,
        )
        excess = len(files) - _MAX_VERSIONS
        for f in files[:excess]:
            f.unlink(missing_ok=True)
    except Exception:
        pass  # 清理失败不影响主路径


def list_versions(aid: str) -> list[dict]:
    """列某个 app 的所有历史版本 · 倒序 (最新在前) · 摘要 (不含 prompt 全文)"""
    if not aid or not aid.startswith("app-"):
        return []
    d = _aid_dir(aid)
    if not d.exists():
        return []
    out: list[dict] = []
    files = sorted(
        d.glob("v*.json"),
        key=lambda p: int(p.stem[1:]) if p.stem[1:].isdigit() else 0,
        reverse=True,
    )
    for p in files:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            out.append({
                "version": data.get("version"),
                "updated_at": data.get("updated_at") or data.get("created_at") or "",
                "spec_version": data.get("spec_version"),
                "name": data.get("name"),
                "prompt_len": len(data.get("system_prompt") or ""),
                "tools_count": len(data.get("tools") or []),
                "path": str(p.relative_to(ROOT)).replace("\\", "/"),
            })
        except Exception:
            continue
    return out


def load_version(aid: str, version: int) -> Optional[dict]:
    """读某个历史版本的完整内容 (用于 diff / rollback 预览)"""
    if not aid or not aid.startswith("app-"):
        return None
    p = _aid_dir(aid) / f"v{int(version)}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def diff_summary(aid: str, va: int, vb: int) -> dict:
    """两版关键字段的 diff 摘要 (字段级 · 不做行级 unified diff · LLM 自己读全文)"""
    a = load_version(aid, va) or {}
    b = load_version(aid, vb) or {}
    out: dict[str, Any] = {"a": va, "b": vb, "changes": []}
    keys = (
        "name", "description", "icon", "model_hint", "exec_kind",
        "system_prompt", "tools", "ui_form_schema", "output_schema",
        "asset_slots", "exec_template",
    )
    for k in keys:
        av, bv = a.get(k), b.get(k)
        if av != bv:
            if isinstance(av, str) and isinstance(bv, str):
                out["changes"].append({
                    "field": k,
                    "a_len": len(av), "b_len": len(bv),
                    "preview_a": av[:120] + ("…" if len(av) > 120 else ""),
                    "preview_b": bv[:120] + ("…" if len(bv) > 120 else ""),
                })
            else:
                out["changes"].append({"field": k, "a": av, "b": bv})
    return out
