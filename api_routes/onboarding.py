"""
api_routes/onboarding.py · 相遇 onboarding 路由（形态 Z 分家整合）
================================================================
把 Daemonkey 原型 server.py 的『相遇』接进母体后端 daemon_api：

  GET  /api/onboarding/status   · {has_key, onboarded, name}
  POST /api/onboarding/save-key · 网页填 key → 写 .env + os.environ + 热建 RUNTIME.client
  POST /api/onboarding/open     · 打开相遇页 → AI 主动开口（第一幕）
  POST /api/onboarding/send     · 用户发言 → web_loop 跑一轮 → 回复
  POST /api/onboarding/reset    · 重新相遇（清身份 + 清对话）

相遇用自己的 OpenAI client（现读 .env），跟主 daemon 的 RUNTIME 解耦；
完成（complete_onboarding）时写 soul/IDENTITY.json + soul/OWNER-NOTEBOOK.md，
并 reload_soul_into_runtime() 让主 daemon 立刻装上用户定义的身份。

单用户本地：onboarding endpoints 只接受 loopback 请求，不走 token 鉴权
（相遇发生在配置 token 之前，必须免鉴权才能跑起来）。
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import threading
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Request

ROOT = Path(__file__).resolve().parent.parent
ONB_DIR = ROOT / "onboarding"
ENV_PATH = ROOT / ".env"
SESSION_PATH = ONB_DIR / "data" / "session.json"

if str(ONB_DIR) not in sys.path:
    sys.path.insert(0, str(ONB_DIR))

import proto_tools  # noqa: E402  (onboarding/proto_tools.py · 写 soul/)
import web_loop  # noqa: E402     (onboarding/web_loop.py)

router = APIRouter(prefix="/api/onboarding")

_KICKOFF = "[系统提示：用户刚第一次打开应用。请你主动开口，开始第一幕『相遇』。]"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_LOCK = threading.Lock()


def _require_loopback(request: Request) -> None:
    host = (request.client.host if request and request.client else "") or ""
    if host.strip().lower() not in _LOOPBACK_HOSTS:
        raise HTTPException(403, "onboarding 仅限本机访问")


# ──────────────────────────── .env 读写 ────────────────────────────

def _load_env() -> dict:
    env: dict[str, str] = {}
    if not ENV_PATH.exists():
        return env
    for line in ENV_PATH.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _has_key() -> bool:
    env = _load_env()
    return bool(env.get("OPUS_API_KEY") and env.get("OPUS_BASE_URL"))


def _max_tokens() -> int:
    try:
        return int(_load_env().get("OPUS_MAX_TOKENS") or 2000)
    except ValueError:
        return 2000


def _identity_name() -> str:
    try:
        if proto_tools.IDENTITY_PATH.exists():
            return json.loads(proto_tools.IDENTITY_PATH.read_text(encoding="utf-8-sig")).get("name", "")
    except Exception:
        pass
    return ""


# ─────────────────── 相遇专用 OpenAI client（读 .env · 跟 RUNTIME 解耦）───────────────────

_client = None
_model = None


def _get_client():
    global _client, _model
    if _client is not None:
        return _client, _model
    env = _load_env()
    api_key = env.get("OPUS_API_KEY")
    base_url = env.get("OPUS_BASE_URL")
    model = env.get("OPUS_MODEL") or "deepseek-chat"
    if not api_key or not base_url:
        return None, None
    from openai import OpenAI
    from daemon_provider import LLM_HTTP_TIMEOUT_SEC  # 单一真相源 · 别再写死短 timeout 坑 thinking 模型
    _client = OpenAI(api_key=api_key, base_url=base_url, timeout=LLM_HTTP_TIMEOUT_SEC)
    _model = model
    return _client, _model


def _reset_client() -> None:
    global _client, _model
    _client = None
    _model = None


# ──────────────────────────── 对话状态（落盘 · 重启不丢）────────────────────────────

def _load_convo() -> list:
    try:
        if SESSION_PATH.exists():
            raw = json.loads(SESSION_PATH.read_text(encoding="utf-8-sig"))
            return [
                m for m in raw
                if not (
                    m.get("role") == "assistant"
                    and not (m.get("content") or "").strip()
                    and not m.get("tool_calls")
                )
            ]
    except Exception:
        pass
    return []


def _save_convo() -> None:
    try:
        SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
        SESSION_PATH.write_text(json.dumps(_CONVO, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


_CONVO: list = _load_convo()


def _visible(messages: list) -> list[dict]:
    out = []
    for m in messages:
        if m.get("role") not in ("user", "assistant"):
            continue
        content = (m.get("content") or "").strip()
        if not content or content == _KICKOFF:
            continue
        out.append({"role": m["role"], "content": content})
    return out


def _run(messages: list):
    client, model = _get_client()
    if client is None:
        raise HTTPException(400, "还没配置 key")
    try:
        return web_loop.run_turn(client, model, _max_tokens(), messages)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"{type(e).__name__}: {e}")


def _maybe_finalize(tool_events: list) -> None:
    """相遇完成（complete_onboarding 调过）→ 热重载灵魂，让主 daemon 立刻装上新身份。"""
    if any(e.get("name") == "complete_onboarding" and e.get("ok") for e in (tool_events or [])):
        try:
            from daemon_runtime import reload_soul_into_runtime
            reload_soul_into_runtime()
        except Exception:
            pass
        # 相遇里新建的关注领域配了信源·但还没抓内容 (items=0)·进主界面雷达会是空的。
        # 后台跑一次 refresh_radar 把新源内容抓回来——非阻塞·用户进去就能边聊边等内容冒出来。
        try:
            def _warm():
                try:
                    from workers.info_radar import refresh_radar
                    # 首启只抓内容、不逐条翻译 (翻译走 LLM 最慢)·让用户的中文新频道尽快有内容·
                    # 英文条目(自我演化)留待之后正常 refresh 再补译。
                    refresh_radar(translate=False)
                except Exception:
                    pass
            threading.Thread(target=_warm, daemon=True).start()
        except Exception:
            pass


# ──────────────────────────── 给 /ui 分流用 ────────────────────────────

def needs_onboarding() -> bool:
    """还没完成相遇 → True（/ui 显示相遇页，否则进 chat.html）。"""
    return not proto_tools.is_onboarded()


# ──────────────────────────── 路由 ────────────────────────────

@router.get("/status")
async def status(request: Request):
    _require_loopback(request)
    return {"has_key": _has_key(), "onboarded": proto_tools.is_onboarded(), "name": _identity_name()}


@router.post("/save-key")
async def save_key(request: Request, payload: dict = Body(...)):
    _require_loopback(request)
    api_key = (payload.get("api_key") or "").strip()
    base_url = (payload.get("base_url") or "").strip()
    model = (payload.get("model") or "").strip()
    if not api_key or not base_url:
        raise HTTPException(400, "api_key 和 base_url 不能为空")

    from daemon_provider import write_env_kv, setup_client

    # 1. 写 .env + os.environ（让运行中 daemon 立刻拿到 · 不必重启）
    write_env_kv("OPUS_PROVIDER", "openai")
    write_env_kv("OPUS_BASE_URL", base_url)
    write_env_kv("OPUS_API_KEY", api_key)
    os.environ["OPUS_PROVIDER"] = "openai"
    os.environ["OPUS_BASE_URL"] = base_url
    os.environ["OPUS_API_KEY"] = api_key
    if model:
        write_env_kv("OPUS_MODEL", model)
        os.environ["OPUS_MODEL"] = model

    # 2. 确保有 API token（loopback 中间件 + chat 鉴权要它在 os.environ）
    if not (os.environ.get("OPUS_API_TOKEN") or "").strip():
        tok = secrets.token_urlsafe(32)
        write_env_kv("OPUS_API_TOKEN", tok)
        os.environ["OPUS_API_TOKEN"] = tok

    # 3. 同步成一条 provider_config（让 chat 设置页 LLM 模型栏能看到这把 key · 修图6）
    #    相遇填 key 走的是 .env·而设置页 LLM 栏读的是 data/provider_configs.json·
    #    两者不打通 → 配过 key 设置里却 0 条。这里补一条·去重避免重复填时建多条。
    try:
        from workers import provider_configs as pc
        the_model = model or os.environ.get("OPUS_MODEL", "") or "deepseek-chat"
        preset_id = pc._guess_preset_id(base_url, "openai")
        data = pc.load_configs()
        match = next(
            (c for c in data.get("configs", [])
             if (c.get("base_url") or "").rstrip("/") == base_url.rstrip("/")
             and c.get("model") == the_model),
            None,
        )
        if match:
            pc.update_config(match["id"], {"api_key": api_key})
            pc.set_active(match["id"])
        else:
            pc.add_config(
                name=pc._guess_name(preset_id, the_model),
                provider_kind="openai",
                base_url=base_url,
                model=the_model,
                api_key=api_key,
                preset_id=preset_id,
                pinned=True,
                set_active=True,
            )
    except Exception:
        pass  # 同步失败不致命·相遇 + chat 仍走 .env 那条路

    # 4. 热建主 daemon 的 RUNTIME.client（相遇完进 chat 不用重启）
    try:
        client, _dm, resolved_base = setup_client("openai")
        from daemon_runtime import RUNTIME
        try:
            from daemon_api import _API_LOCK
            lock = _API_LOCK
        except Exception:
            lock = _LOCK
        with lock:
            RUNTIME.client = client
            RUNTIME.provider = "openai"
            RUNTIME.model = model or os.environ.get("OPUS_MODEL", "")
            RUNTIME.base_url = resolved_base
    except Exception:
        pass  # 相遇本身用自己的 client·主 RUNTIME 热建失败不致命（重启即恢复）

    _reset_client()
    return {"ok": True}


@router.post("/open")
async def open_(request: Request):
    _require_loopback(request)
    if not _has_key():
        raise HTTPException(400, "还没配置 key")
    tool_events: list = []
    with _LOCK:
        if not _CONVO:
            _CONVO.append({"role": "user", "content": _KICKOFF})
            _, tool_events = _run(_CONVO)
            _save_convo()
        elif _CONVO[-1].get("role") == "user":
            # 上次发了话没拿到回复（比如模型返回空）· 补一轮
            _, tool_events = _run(_CONVO)
            _save_convo()
    _maybe_finalize(tool_events)
    return {
        "messages": _visible(_CONVO),
        "tool_events": tool_events,
        "onboarded": proto_tools.is_onboarded(),
        "name": _identity_name(),
    }


@router.post("/send")
async def send(request: Request, payload: dict = Body(...)):
    _require_loopback(request)
    msg = (payload.get("message") or "").strip()
    if not msg:
        raise HTTPException(400, "message 为空")
    with _LOCK:
        _CONVO.append({"role": "user", "content": msg})
        reply, tool_events = _run(_CONVO)
        _save_convo()
    _maybe_finalize(tool_events)
    return {
        "reply": reply,
        "tool_events": tool_events,
        "onboarded": proto_tools.is_onboarded(),
        "name": _identity_name(),
    }


@router.post("/reset")
async def reset(request: Request):
    _require_loopback(request)
    with _LOCK:
        _CONVO.clear()
        # 只清相遇产物 · 绝不动 SKILL / OPUS-MEMORIES / SELF-EVOLUTION 机制模板
        for p in (proto_tools.IDENTITY_PATH, proto_tools.ONBOARDING_PATH, SESSION_PATH):
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass
        # OWNER-NOTEBOOK 回到空模板
        try:
            proto_tools.NOTEBOOK_PATH.write_text(proto_tools._notebook_template(), encoding="utf-8")
        except Exception:
            pass
    return {"ok": True}
