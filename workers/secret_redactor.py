"""workers/secret_redactor.py
=================================

卷四十六 III 补丁 5 · Y3 · scripted app secret 输出脱敏 · 2026-05-26

为什么需要这个
----------------
scripted app 跑完 HTTP 请求后 · output 会回流 LLM 上下文。 但如果:

  - 上游 API 在错误响应里**回显**了我们传去的 secret (debug API 经常干这事)
  - URL 里含 query string secret (例: `?api_key=sk-xxx`)
  - response body 里含 secret 真值 (echo back / debug info)
  - server 在 error 信息里包含 Authorization header

→ secret 真值会跟 outputs 一起进 LLM context · 一起落 session jsonl ·
  跟铁律 7 (LLM context 永远只看 placeholder) 直接冲突。

http_executor 之前没这一层 · output 是裸的 · 这是个 gap。 Y3 补这一层。

设计
------
1. 收集本 app 的所有 secret 真值 (一次性 · workshop_assets.load_app + app_secrets.list_secrets)
2. 用一个**最长优先**的字符串替换 (避免 'sk-xx' 是 'sk-xxxxx' 前缀时漏替换)
3. 替换成 `${secret:<app_id>:<name>}` placeholder · 跟 OPUS 写 app 时用的引用一致
4. 递归 walk dict/list/str · 不动 int/float/bool/None

不做的事
----------
- **不**改 redact 后的 secret 长度伪装 (例: `***`)·placeholder 是 single source of truth
- **不**做 entropy 检测 (识别"看起来像 key 的串") — 误报多 · 真要做下个 wish
- **不**改 progress() SSE 流 (那一层 url 已 interpolate · 我们也 redact 那一层)

用法 (caller):
    from workers.secret_redactor import build_redactor
    redact = build_redactor("app-gpt-image-2")
    safe_output = redact(raw_output)  # 任意 obj · 返回同结构但 secret 已替换
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional


_log = logging.getLogger("opus.secret_redactor")


def _collect_secrets(app_id: str) -> dict[str, str]:
    """读所有 secret 真值 · {name: value}

    失败 (没 app / 没 secret) 返 {} · 不 raise · 不阻塞主流程
    """
    try:
        from workers.app_secrets import list_secrets, get_secret
        names = list_secrets(app_id)
        out = {}
        for n in names:
            v = get_secret(app_id, n)
            if v and isinstance(v, str) and len(v) >= 4:  # 太短的 secret 容易误伤
                out[n] = v
        return out
    except Exception as e:
        _log.warning("collect_secrets failed app=%s: %s", app_id, e)
        return {}


def build_redactor(app_id: str) -> Callable[[Any], Any]:
    """构造一个 redact 函数 · 针对此 app 的所有 secret

    Returns:
        callable · 接 Any · 返同结构 obj · str 里所有 secret 真值替换为
        `${secret:<app_id>:<name>}` placeholder

    Special cases:
        - app_id 空 → 透传 (不动)
        - 此 app 没 secret → 透传
        - 不 raise · 出错只 log warn
    """
    if not app_id:
        return lambda x: x

    secrets = _collect_secrets(app_id)
    if not secrets:
        return lambda x: x

    # 长度倒序 · 避免 short prefix 提前匹配 (例: 'sk-1' 在 'sk-12345' 之前)
    pairs = sorted(secrets.items(), key=lambda kv: -len(kv[1]))

    def _redact_str(s: str) -> str:
        if not isinstance(s, str) or not s:
            return s
        for name, value in pairs:
            if value in s:
                s = s.replace(value, f"${{secret:{app_id}:{name}}}")
        return s

    def _redact_obj(obj: Any) -> Any:
        if isinstance(obj, str):
            return _redact_str(obj)
        if isinstance(obj, dict):
            return {k: _redact_obj(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            t = type(obj)
            return t(_redact_obj(v) for v in obj)
        return obj  # int / float / bool / None 等不动

    return _redact_obj


def redact(app_id: str, obj: Any) -> Any:
    """one-shot 便利 · 内部 build + apply

    适合一次性 / 小数据 · 多次调用同 app_id 时用 build_redactor 复用
    """
    return build_redactor(app_id)(obj)


__all__ = ["build_redactor", "redact"]
