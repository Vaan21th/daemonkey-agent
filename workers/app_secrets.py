"""
workers/app_secrets.py
======================

卷四十四 K stage 2c++ · wish-96ee1b52 · App secret 安全存储

为什么有这个模块
------------------
daemon OPUS 装 API 应用时需要 KEY (例如 GPT Image 走 aipg.work · 需要 sk-xxx)。
之前没有这个机制·daemon OPUS 唯一选择是把 KEY 明文写进 data/workshop/apps/<app>.json·
KEY 直接进 git history / session jsonl / system_prompt = 三重暴露。

这是规则 gap · 不是 OPUS 偷懒 (BRO 2026-05-25 18:42 一句话点中):
  - .env 是 GUARD tier · daemon OPUS 不能直接写
  - 没 secret store 工具 · 他只能把 KEY 写 app json
  - 给他工具 · 而不是骂他 · 这才是教练应该做的

落点
----
- 文件: data/workshop/secrets/<app_id>.json (gitignored · 不 commit)
- 数据: {"app_id": "...", "secrets": {"name": "value", ...}}
- daemon OPUS 通过 app_set_secret / app_list_secrets 工具操作
- daemon OPUS **不能直接读 secret 真值** — 真值用 ${secret:app-xxx:name} placeholder
  在 shell_exec 里走 env 注入 · 子进程才能 resolve 拿到 · LLM context 永远只看 placeholder

跟 provider_configs.py 的关系
-------------------------------
- provider_configs 管 daemon 自己的 LLM client config (含 LLM API key)
- app_secrets 管 daemon OPUS 造的 app 用的第三方 KEY
- 两者隔离: daemon 自己的 KEY 通过 .env (受 GUARD 锁保护) · app 的 KEY 走这里
- 共用 _atomic_write 模式 · 但不互相 import (避免循环 + 概念隔离)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parent.parent
SECRETS_DIR = ROOT / "data" / "workshop" / "secrets"


# ── 内部 atomic write ────────────────────────────────────────

def _atomic_write(path: Path, content: str) -> None:
    """卷四十六 III · wish-badd4 收编到 safe_write
    app_secrets.json 是 BRO 自建 app 的 API key·丢了找不回·backup=True"""
    from .safe_write import atomic_write_text
    atomic_write_text(path, content, backup=True)


def _validate_app_id(app_id: str) -> str:
    app_id = (app_id or "").strip()
    if not app_id:
        raise ValueError("app_id 必填")
    # 跟 workshop_assets.py 同款 · 防 path traversal
    if any(c in app_id for c in ("/", "\\", "..", "\x00")):
        raise ValueError(f"app_id 不允许特殊字符: {app_id!r}")
    if len(app_id) > 64:
        raise ValueError(f"app_id 太长 (>64): {app_id!r}")
    return app_id


def _validate_secret_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ValueError("secret_name 必填")
    if any(c in name for c in ("/", "\\", "..", "\x00", ":", "$", "{", "}")):
        # ":" 跟 "$" "{" "}" 排除是因为我们的 placeholder 语法是 ${secret:app:name}
        # name 里有 ":" 就 ambiguous 了 · 早点 reject
        raise ValueError(f"secret_name 不允许特殊字符 (/ \\ : $ {{ }}): {name!r}")
    if len(name) > 64:
        raise ValueError(f"secret_name 太长 (>64): {name!r}")
    return name


def _secrets_path(app_id: str) -> Path:
    return SECRETS_DIR / f"{_validate_app_id(app_id)}.json"


def _load(app_id: str) -> dict:
    """读 secrets file · 不存在返空容器."""
    fp = _secrets_path(app_id)
    if not fp.exists():
        return {"app_id": app_id, "secrets": {}}
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # 文件坏了 · 重置 (BRO 重要 KEY 丢了至少能看到清空 · 而不是静默错值)
        return {"app_id": app_id, "secrets": {}}
    if not isinstance(data, dict) or "secrets" not in data:
        return {"app_id": app_id, "secrets": {}}
    return data


def _save(data: dict) -> None:
    fp = _secrets_path(data["app_id"])
    _atomic_write(fp, json.dumps(data, ensure_ascii=False, indent=2))
    # POSIX 上限制 owner only · Windows 上 chmod 不严格但是 best effort
    try:
        os.chmod(fp, 0o600)
    except OSError:
        pass


# ── 公开 API ────────────────────────────────────────

def set_secret(app_id: str, secret_name: str, value: str) -> dict:
    """写一个 secret · 已存在则覆盖.

    Args:
        app_id: 哪个 app (data/workshop/apps/<app_id>.json 里的 id)
        secret_name: 字段名 · 例如 "api_key" / "access_token" / "client_secret"
        value: 真值 · 直接写到磁盘 (gitignored · 不进 git)

    Returns:
        {"ok": True, "app_id": "...", "secret_name": "...", "placeholder": "${secret:app:name}"}
        placeholder 字段 = 给 LLM 写 system_prompt / shell_exec 用的引用形式
    """
    app_id = _validate_app_id(app_id)
    secret_name = _validate_secret_name(secret_name)
    if not isinstance(value, str):
        raise ValueError("value 必须是 str")
    if not value:
        raise ValueError("value 不能为空")

    data = _load(app_id)
    data["secrets"][secret_name] = value
    _save(data)

    return {
        "ok": True,
        "app_id": app_id,
        "secret_name": secret_name,
        "placeholder": f"${{secret:{app_id}:{secret_name}}}",
    }


def get_secret(app_id: str, secret_name: str) -> Optional[str]:
    """读 secret 真值 · daemon 内部 resolve 用.

    !! 重要 !! 这个函数返回真值 · 调用方必须确保:
      - 不把返回值塞进 LLM 的 messages / context / system_prompt
      - 不把返回值 echo 进 shell_exec 的 stdout (用 redact 兜底)
      - 不把返回值 commit 进 git
      - 不写到 session jsonl

    daemon OPUS 通过 agent_tools 调用时**不会**直接拿到 value · 只会拿到 placeholder。
    真 resolve 发生在 daemon 内部 (shell_exec 的 env 注入路径)。
    """
    app_id = _validate_app_id(app_id)
    secret_name = _validate_secret_name(secret_name)
    data = _load(app_id)
    return data["secrets"].get(secret_name)


def list_secrets(app_id: str) -> list[str]:
    """只列 secret_name · 不返 value (LLM 安全调用)."""
    app_id = _validate_app_id(app_id)
    data = _load(app_id)
    return sorted(data["secrets"].keys())


def delete_secret(app_id: str, secret_name: str) -> bool:
    """删一个 secret · 返 True 表示真删了 · False 表示本来就没有."""
    app_id = _validate_app_id(app_id)
    secret_name = _validate_secret_name(secret_name)
    data = _load(app_id)
    if secret_name not in data["secrets"]:
        return False
    del data["secrets"][secret_name]
    if data["secrets"]:
        _save(data)
    else:
        # 没 secret 了 · 删整个文件 (干净)
        fp = _secrets_path(app_id)
        try:
            fp.unlink()
        except OSError:
            pass
    return True


# ── placeholder 语法 ────────────────────────────────────────

import re

# ${secret:app-xxx:secret_name} 严格 · 只匹配合法字符
_PLACEHOLDER_RE = re.compile(r"\$\{secret:([a-zA-Z0-9_\-]+):([a-zA-Z0-9_\-]+)\}")


def resolve_placeholders(text: str) -> tuple[str, dict[str, str]]:
    """把 text 里所有 ${secret:app:name} 替换成真值.

    Returns:
        (resolved_text, used_secrets)
        used_secrets: {真值: placeholder 原文} · 用于 stdout redact 反向替换

    daemon 在 shell_exec 启动子进程前调一次 · 给子进程 env 注入真值 ·
    子进程退出后调 redact_in_text(stdout, used_secrets) 把真值替换回 placeholder ·
    再返 LLM。
    """
    if not text:
        return text, {}

    used: dict[str, str] = {}

    def _sub(m: re.Match) -> str:
        app_id, name = m.group(1), m.group(2)
        try:
            val = get_secret(app_id, name)
        except ValueError:
            return m.group(0)  # 非法 app_id/name · 保留原样
        if val is None:
            return m.group(0)  # secret 不存在 · 保留原样 (子进程会报错 · 比静默好)
        # 用真值替换 · 同时记录映射
        used[val] = m.group(0)
        return val

    resolved = _PLACEHOLDER_RE.sub(_sub, text)
    return resolved, used


def redact_in_text(text: str, used_secrets: dict[str, str]) -> str:
    """把 text 里所有真值替换回 placeholder.

    用于 stdout redact · 防 secret 真值意外 echo 进 LLM context。
    """
    if not text or not used_secrets:
        return text
    result = text
    # 长 value 优先替换 · 避免短 value 是长 value 子串的覆盖问题
    for value in sorted(used_secrets.keys(), key=len, reverse=True):
        result = result.replace(value, used_secrets[value])
    return result
