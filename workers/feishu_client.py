"""
workers/feishu_client.py · 飞书开放平台客户端 (0.9.0 · wish-aac348a1)

企业自建应用: app_id + app_secret → tenant_access_token (2h 缓存) → im/v1/messages 发消息。
配置存 data/runtime/feishu_config.json (用户 WebUI 填 · 与微信 iLink 并列)。
对比微信 iLink: 官方 API + WebSocket 长连接 · 无 24h 窗口 · 无公网依赖。
"""
from __future__ import annotations

import json
import logging
import random
import threading
import time
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger("opus.feishu")

def _config_path() -> Path:
    """feishu 配置路径 · cwd 兜底 (fix-log 20260814-1 ②):
    从错误 cwd 启动时 `data/runtime/feishu_config.json` 相对路径读不到 → 静默判定未配置。
    先试 cwd 相对 · 失败回退到项目根 (daemon 所在目录) · 保证无论从哪启动都能读到。
    """
    p = Path("data/runtime/feishu_config.json")
    if p.exists():
        return p
    # 项目根兜底: 从当前文件位置向上找 (workers/feishu_client.py → 项目根)
    here = Path(__file__).resolve().parent.parent
    alt = here / "data" / "runtime" / "feishu_config.json"
    return alt if alt.exists() else p


_BASE = "https://open.feishu.cn"

_TOKEN_CACHE: dict = {"token": None, "exp": 0.0}  # tenant_access_token + 到期时间


# ── 配置 ──────────────────────────────────────────────────

def load_config() -> dict:
    cp = _config_path()
    if not cp.exists():
        return {}
    try:
        return json.loads(cp.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(app_id: str, app_secret: str, enabled: bool = True) -> None:
    cfg = load_config()
    cfg.update({"app_id": app_id.strip(), "app_secret": app_secret.strip(), "enabled": bool(enabled)})
    cp = _config_path()
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("feishu config saved · app_id=%s · enabled=%s", cfg["app_id"], cfg["enabled"])


def is_configured() -> bool:
    cfg = load_config()
    return bool(cfg.get("app_id") and cfg.get("app_secret"))


def enabled() -> bool:
    cfg = load_config()
    return is_configured() and bool(cfg.get("enabled", True))


def set_enabled(on: bool) -> None:
    cfg = load_config()
    cfg["enabled"] = bool(on)
    save_config(cfg.get("app_id", ""), cfg.get("app_secret", ""), bool(on))


# ── L1 · 群机器人 webhook (零门槛单向推送 · 0.9.1) ───────────────

def save_webhook(url: str) -> None:
    cfg = load_config()
    cfg["webhook_url"] = url.strip()
    cp = _config_path()
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("feishu webhook saved · %s", cfg["webhook_url"][:40] + "***" if cfg["webhook_url"] else "")


def get_webhook() -> Optional[str]:
    url = load_config().get("webhook_url") or ""
    return url.strip() or None


def send_webhook(text: str) -> dict:
    """L1 · 群机器人 webhook 推送 · 无需 App ID/Secret · 单向 (daemon → 群)。"""
    url = get_webhook()
    if not url:
        return {"ok": False, "error": "未配置 webhook URL"}
    try:
        status, d = _api_request("POST", url, token=None,
                                 json_body={"msg_type": "text", "content": {"text": text}}, timeout=15)
        ok = d.get("code") == 0
        if not ok:
            logger.warning("feishu webhook 失败: %s (http=%s)", d.get("msg"), status)
        return {"ok": ok, "msg": d.get("msg", "")}
    except Exception as e:
        logger.warning("feishu webhook 异常: %s", e)
        return {"ok": False, "error": str(e)}


# ── 认证 ──────────────────────────────────────────────────

# 2026-08-14 · 系统代理直连豁免 (同 info_radar 修复模式):
# 系统代理残留死端口 (Clash 没开但 ProxyEnable=1 → 127.0.0.1:7890 无监听) 会让 requests 全灭。
# trust_env=False → requests 忽略系统代理 · 飞书通道直连 (飞书国内可达·不需要代理)。
_session = requests.Session()
_session.trust_env = False


def get_tenant_token() -> Optional[str]:
    """app_id+app_secret → tenant_access_token · 缓存到到期前 5 分钟。"""
    if _TOKEN_CACHE["token"] and time.time() < _TOKEN_CACHE["exp"] - 300:
        return _TOKEN_CACHE["token"]
    cfg = load_config()
    if not is_configured():
        return None
    try:
        r = _session.post(
            f"{_BASE}/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": cfg["app_id"], "app_secret": cfg["app_secret"]},
            timeout=15,
        )
        d = r.json()
        if d.get("code") == 0:
            _TOKEN_CACHE["token"] = d["tenant_access_token"]
            _TOKEN_CACHE["exp"] = time.time() + int(d.get("expire", 7200))
            return _TOKEN_CACHE["token"]
        logger.warning("feishu token 失败: %s", d.get("msg"))
    except Exception as e:
        logger.warning("feishu token 异常: %s", e)
    return None


# ── 重试层 (块1 · 对标 cc-connect withTransientRetry + withFreshTenantAccessTokenRetry) ──────────

_MAX_TRANSIENT_RETRIES = 3          # 瞬时错误最多重试 3 次 (对标 cc maxTransientRetries)
_TRANSIENT_INITIAL = 0.5            # 秒 · 指数退避起点 (对标 cc transientRetryInitial)
_TRANSIENT_MAX_DELAY = 5.0          # 秒 · 退避上限 (对标 cc transientRetryMaxDelay)
_TOKEN_INVALID_CODES = {"99991663", "99991664", "99991668"}  # tenant access token 无效/过期


def _is_token_invalid(d: dict, status_code: int) -> bool:
    """响应是不是 token 失效 (对标 cc isTenantAccessTokenInvalid: 99991663 / invalid access token)。"""
    if status_code == 401:
        return True
    code = str(d.get("code") or "")
    if code in _TOKEN_INVALID_CODES:
        return True
    msg = str(d.get("msg") or "").lower()
    return "invalid access token" in msg


def _is_transient_error(exc: BaseException, status_code: int = 0) -> bool:
    """是不是瞬时错误 (对标 cc isTransientError: 连接重置/超时/EOF/5xx)。"""
    if status_code >= 500:
        return True
    if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return True
    msg = str(exc).lower()
    for substr in ("connection reset by peer", "broken pipe", "i/o timeout",
                   "tls handshake timeout", "server misbehaving", "connection refused"):
        if substr in msg:
            return True
    return False


def _rewind_files(files) -> None:
    """重试前把 multipart 文件指针拨回开头 (否则文件已读完 → 重发空文件)。"""
    if not files:
        return
    for v in files.values():
        fobj = v[1] if isinstance(v, (tuple, list)) and len(v) >= 2 else v
        if hasattr(fobj, "seek"):
            try:
                fobj.seek(0)
            except Exception:
                logger.warning("feishu_client 请求异常失败 (L162)", exc_info=True)


def _refresh_token_force() -> Optional[str]:
    """强制刷新 tenant_access_token (清缓存重拉 · 对标 cc fetchFreshTenantAccessToken)。"""
    _TOKEN_CACHE["token"] = None
    _TOKEN_CACHE["exp"] = 0.0
    return get_tenant_token()


def _api_request(method: str, url: str, *, token: Optional[str] = None, headers: Optional[dict] = None,
                 json_body: Optional[dict] = None, params: Optional[dict] = None,
                 files=None, data=None, timeout: int = 20):
    """飞书 API 统一请求入口 · 对标 cc-connect 双层重试。

    ① 瞬时错误 (网络异常 / HTTP 5xx) → 指数退避 + jitter 重试 ≤ _MAX_TRANSIENT_RETRIES 次
    ② token 失效 (错误码 99991663/99991664/401) → 强制刷新 token → 重试一次

    返回 (status_code, json_dict)。网络错误重试耗尽后 raise 最后一个异常。
    """
    hdrs = dict(headers or {})
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    last_exc: Optional[BaseException] = None
    delay = _TRANSIENT_INITIAL
    for attempt in range(_MAX_TRANSIENT_RETRIES + 1):
        try:
            resp = _session.request(method, url, headers=hdrs, json=json_body, params=params,
                                    files=files, data=data, timeout=timeout)
        except requests.exceptions.RequestException as e:
            if not _is_transient_error(e) or attempt >= _MAX_TRANSIENT_RETRIES:
                raise
            last_exc = e
        else:
            if resp.status_code >= 500 and attempt < _MAX_TRANSIENT_RETRIES:
                # HTTP 5xx → 按瞬时错误重试 (最后一次 5xx 原样返回给调用方)
                last_exc = requests.exceptions.ConnectionError(f"HTTP {resp.status_code}")
            else:
                try:
                    d = resp.json()
                except Exception:
                    d = {}
                # ② token 失效 → 刷新 → 重试一次
                if token and _is_token_invalid(d, resp.status_code):
                    fresh = _refresh_token_force()
                    if fresh:
                        hdrs["Authorization"] = f"Bearer {fresh}"
                        _rewind_files(files)
                        try:
                            resp2 = _session.request(method, url, headers=hdrs, json=json_body,
                                                     params=params, files=files, data=data, timeout=timeout)
                        except requests.exceptions.RequestException:
                            resp2 = None
                        if resp2 is not None:
                            try:
                                return resp2.status_code, resp2.json()
                            except Exception:
                                return resp2.status_code, {}
                return resp.status_code, d
        # 到这里 = 瞬时错误且还有重试额度 → 指数退避 + jitter (对标 cc)
        _rewind_files(files)
        jitter = random.uniform(0, delay * 0.25)
        time.sleep(delay + jitter)
        delay = min(delay * 2, _TRANSIENT_MAX_DELAY)
    # 循环耗尽 · 只有瞬时重试路径会走到这里 · last_exc 必非 None
    raise last_exc  # type: ignore[misc]


# ── 收发 ──────────────────────────────────────────────────

def get_message_items(message_id: str) -> dict:
    """拉消息 (GET /im/v1/messages/{id}) 返回全部 items · 合并转发展开用 (对标 cc parseMergeForward)。"""
    token = get_tenant_token()
    if not token:
        return {"ok": False, "error": "未配置"}
    try:
        status, d = _api_request("GET", f"{_BASE}/open-apis/im/v1/messages/{message_id}?card_msg_content_type=raw_card_content",
                                 token=token, timeout=10)
        if d.get("code") != 0:
            logger.warning("feishu get_message_items 失败: %s (http=%s)", d.get("msg"), status)
            return {"ok": False, "msg": d.get("msg", "")}
        return {"ok": True, "items": ((d.get("data") or {}).get("items") or [])}
    except Exception as e:
        logger.warning("feishu get_message_items 异常: %s", e)
        return {"ok": False, "error": str(e)}


def get_message(message_id: str) -> dict:
    """拉单条消息 (GET /im/v1/messages/{id} · 走重试层 · 引用回复链用)。

    对标 cc fetchSingleMessage · 返回 items 里第一条 (含 msg_type / body.content / parent_id / sender)。
    """
    gr = get_message_items(message_id)
    if not gr.get("ok"):
        return gr
    items = gr.get("items") or []
    return {"ok": True, "item": items[0] if items else None}

def send_text(text: str, receive_id: str, receive_id_type: str = "chat_id") -> dict:
    """给飞书会话/用户发一条文本消息。receive_id_type: chat_id / open_id / user_id。"""
    token = get_tenant_token()
    if not token:
        return {"ok": False, "error": "未配置或 token 获取失败"}
    try:
        status, d = _api_request("POST", f"{_BASE}/open-apis/im/v1/messages?receive_id_type={receive_id_type}",
                                 token=token, json_body={
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }, timeout=20)
        ok = d.get("code") == 0
        if not ok:
            logger.warning("feishu send_text 失败: %s (http=%s)", d.get("msg"), status)
        return {"ok": ok, "msg": d.get("msg", ""), "message_id": (d.get("data") or {}).get("message_id")}
    except Exception as e:
        logger.warning("feishu send_text 异常: %s", e)
        return {"ok": False, "error": str(e)}


def send_file(file_path: str, receive_id: str, receive_id_type: str = "open_id") -> dict:
    """给飞书会话/用户发一个文件 (先上传拿 file_key → 再发 file 消息)。

    上传: POST /open-apis/im/v1/files (file_type=stream 通用)
    发送: POST /open-apis/im/v1/messages?receive_id_type=xxx (msg_type=file)
    权限: im:resource (上传文件) · 上限 20MB。
    """
    import pathlib
    p = pathlib.Path(file_path)
    if not p.exists() or not p.is_file():
        return {"ok": False, "error": f"文件不存在: {file_path}"}
    if p.stat().st_size > 20 * 1024 * 1024:
        return {"ok": False, "error": f"文件 {p.stat().st_size//1024//1024}MB 超 20MB 上限"}
    token = get_tenant_token()
    if not token:
        return {"ok": False, "error": "未配置或 token 获取失败"}
    # ① 上传
    try:
        with open(p, "rb") as f:
            status, d = _api_request("POST", f"{_BASE}/open-apis/im/v1/files",
                                     token=token,
                                     data={"file_type": "stream", "file_name": p.name},
                                     files={"file": (p.name, f)},
                                     timeout=60)
        if d.get("code") != 0:
            logger.warning("feishu 上传文件失败: %s (http=%s)", d.get("msg"), status)
            return {"ok": False, "error": f"上传失败: {d.get('msg', '')}"}
        file_key = (d.get("data") or {}).get("file_key")
    except Exception as e:
        logger.warning("feishu 上传文件异常: %s", e)
        return {"ok": False, "error": f"上传异常: {e}"}
    if not file_key:
        return {"ok": False, "error": "上传成功但没拿到 file_key"}
    # ② 发文件消息
    try:
        status2, d2 = _api_request("POST", f"{_BASE}/open-apis/im/v1/messages?receive_id_type={receive_id_type}",
                                   token=token, json_body={
            "receive_id": receive_id,
            "msg_type": "file",
            "content": json.dumps({"file_key": file_key}, ensure_ascii=False),
        }, timeout=20)
        ok = d2.get("code") == 0
        if not ok:
            logger.warning("feishu 发文件消息失败: %s (http=%s)", d2.get("msg"), status2)
        return {"ok": ok, "msg": d2.get("msg", ""),
                "message_id": (d2.get("data") or {}).get("message_id"), "file_key": file_key}
    except Exception as e:
        logger.warning("feishu 发文件消息异常: %s", e)
        return {"ok": False, "error": f"发送异常: {e}"}


def send_post(content: str, receive_id: str, receive_id_type: str = "chat_id") -> dict:
    """给飞书会话/用户发一条 post 富文本消息 (md tag 渲染 markdown · 对标 cc buildPostMdJSON)。

    用于 markdown 表格超卡片上限 (>5) 时的降级 · 正常字号渲染 markdown。
    """
    token = get_tenant_token()
    if not token:
        return {"ok": False, "error": "未配置或 token 获取失败"}
    try:
        body = {"zh_cn": {"content": [[{"tag": "md", "text": content}]]}}
        status, d = _api_request("POST", f"{_BASE}/open-apis/im/v1/messages?receive_id_type={receive_id_type}",
                                 token=token, json_body={
            "receive_id": receive_id,
            "msg_type": "post",
            "content": json.dumps(body, ensure_ascii=False),
        }, timeout=20)
        ok = d.get("code") == 0
        if not ok:
            logger.warning("feishu send_post 失败: %s (http=%s)", d.get("msg"), status)
        return {"ok": ok, "msg": d.get("msg", ""), "message_id": (d.get("data") or {}).get("message_id")}
    except Exception as e:
        logger.warning("feishu send_post 异常: %s", e)
        return {"ok": False, "error": str(e)}


# ── 块 C · 卡片 (wish-a0e7301c) ─────────────────────────────

def send_card(card: dict, receive_id: str, receive_id_type: str = "chat_id") -> dict:
    """发一张飞书 interactive 卡片 (v2 schema)。card 是卡片 JSON dict。"""
    token = get_tenant_token()
    if not token:
        return {"ok": False, "error": "未配置或 token 获取失败"}
    try:
        status, d = _api_request("POST", f"{_BASE}/open-apis/im/v1/messages?receive_id_type={receive_id_type}",
                                 token=token, json_body={
            "receive_id": receive_id,
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
        }, timeout=20)
        ok = d.get("code") == 0
        if not ok:
            logger.warning("feishu send_card 失败: %s (http=%s)", d.get("msg"), status)
        return {"ok": ok, "msg": d.get("msg", ""), "message_id": (d.get("data") or {}).get("message_id")}
    except Exception as e:
        logger.warning("feishu send_card 异常: %s", e)
        return {"ok": False, "error": str(e)}


def update_card(message_id: str, card: dict) -> dict:
    """更新已发送的消息卡片 (PATCH /im/v1/messages/:message_id · 只传 content · 对标 cc-connect patchCardMessage)。

    ⚠️ 不要用 PUT 更新消息 —— 对 interactive 卡片不生效 (2026-08-06 线上教训)。
    """
    token = get_tenant_token()
    if not token:
        return {"ok": False, "error": "未配置"}
    try:
        status, d = _api_request("PATCH", f"{_BASE}/open-apis/im/v1/messages/{message_id}",
                                 token=token, json_body={"content": json.dumps(card, ensure_ascii=False)}, timeout=20)
        if d.get("code") != 0:
            logger.warning("feishu update_card 失败: %s (http=%s)", d.get("msg"), status)
        return {"ok": d.get("code") == 0, "msg": d.get("msg", "")}
    except Exception as e:
        logger.warning("feishu update_card 异常: %s", e)
        return {"ok": False, "error": str(e)}


def send_reaction(message_id: str, emoji_type: str = "OK") -> dict:
    """给消息加表情 reaction (im/v1/messages/{message_id}/reactions)。失败静默。"""
    token = get_tenant_token()
    if not token:
        return {"ok": False, "error": "未配置"}
    try:
        status, d = _api_request("POST", f"{_BASE}/open-apis/im/v1/messages/{message_id}/reactions",
                                 token=token, json_body={"reaction_type": {"emoji_type": emoji_type}}, timeout=10)
        reaction_id = ""
        if d.get("code") == 0:
            reaction_id = ((d.get("data") or {}).get("reaction_id") or "")
        if d.get("code") != 0:
            logger.warning("feishu reaction 失败: %s (http=%s)", d.get("msg"), status)
        return {"ok": d.get("code") == 0, "msg": d.get("msg", ""), "reaction_id": reaction_id}
    except Exception as e:
        logger.warning("feishu reaction 异常: %s", e)
        return {"ok": False, "error": str(e)}


def remove_reaction(message_id: str, reaction_id: str) -> dict:
    """移除消息上的 reaction (DELETE /im/v1/messages/{message_id}/reactions/{reaction_id})。失败静默。"""
    token = get_tenant_token()
    if not token or not reaction_id:
        return {"ok": False, "error": "未配置"}
    try:
        status, d = _api_request("DELETE", f"{_BASE}/open-apis/im/v1/messages/{message_id}/reactions/{reaction_id}",
                                 token=token, timeout=10)
        if d.get("code") != 0:
            logger.warning("feishu remove_reaction 失败: %s (http=%s)", d.get("msg"), status)
        return {"ok": d.get("code") == 0, "msg": d.get("msg", "")}
    except Exception as e:
        logger.warning("feishu remove_reaction 异常: %s", e)
        return {"ok": False, "error": str(e)}


# ── 块 D · 会话消息管理 (wish-b0e32866) ─────────────────────

def list_messages(
    chat_id: str,
    page_size: int = 20,
    sort_type: str = "ByCreateTimeDesc",
    page_token: Optional[str] = None,
) -> dict:
    """拉取会话消息列表 (GET /im/v1/messages)。

    sort_type: ByCreateTimeAsc / ByCreateTimeDesc。
    返回 items 含 message_id / msg_type / create_time / sender / body。
    需要权限: 获取会话历史消息 (im:message 或 im:message:readonly)。
    """
    token = get_tenant_token()
    if not token:
        return {"ok": False, "error": "未配置"}
    try:
        # page_size 防御式转换: int 直接用 · 数字字符串转 int · 其他回退默认 20
        try:
            page_size = int(page_size)
        except (TypeError, ValueError):
            page_size = 20
        if sort_type not in ("ByCreateTimeAsc", "ByCreateTimeDesc"):
            return {"ok": False, "error": f"sort_type 非法: {sort_type} (应为 ByCreateTimeAsc/ByCreateTimeDesc)"}
        params = {
            "container_id_type": "chat",
            "container_id": chat_id,
            "sort_type": sort_type,
            "page_size": max(1, min(page_size, 50)),
        }
        if page_token:
            params["page_token"] = page_token
        status, d = _api_request("GET", f"{_BASE}/open-apis/im/v1/messages",
                                 token=token, params=params, timeout=20)
        if d.get("code") != 0:
            logger.warning("feishu list_messages 失败: %s (http=%s)", d.get("msg"), status)
            return {"ok": False, "msg": d.get("msg", "")}
        data = d.get("data") or {}
        return {
            "ok": True,
            "items": data.get("items") or [],
            "has_more": bool(data.get("has_more")),
            "page_token": data.get("page_token", ""),
        }
    except Exception as e:
        logger.warning("feishu list_messages 异常: %s", e)
        return {"ok": False, "error": str(e)}


def batch_recall(message_ids: list) -> dict:
    """批量撤回消息 (循环 DELETE /im/v1/messages/{id} · 一次最多 100 条)。

    注意: 机器人默认只能撤回自己发送的消息 (撤回他人需 im:message 管理员权限)。
    飞书无通用批量撤回端点 (batch_message/delete 只对批量发送接口发的消息有效) ·
    所以这里循环单条撤回。对标 cc-connect 的 onMessageRecalled / IsMessageRecalled 撤回链路。
    """
    token = get_tenant_token()
    if not token:
        return {"ok": False, "error": "未配置"}
    # 防御: 调用方误传字符串时包成单元素列表 · 避免逐字符迭代
    if isinstance(message_ids, str):
        message_ids = [message_ids]
    ids = [m for m in (message_ids or []) if m]
    truncated = len(ids) > 100
    ids = ids[:100]
    if not ids:
        return {"ok": False, "error": "message_ids 不能为空"}
    results = []
    for mid in ids:
        try:
            status, d = _api_request("DELETE", f"{_BASE}/open-apis/im/v1/messages/{mid}",
                                     token=token, timeout=15)
            ok = d.get("code") == 0
            if not ok:
                logger.warning("feishu recall %s 失败: %s (http=%s)", mid, d.get("msg"), status)
            results.append({"message_id": mid, "ok": ok, "msg": d.get("msg", "")})
        except Exception as e:
            logger.warning("feishu recall %s 异常: %s", mid, e)
            results.append({"message_id": mid, "ok": False, "error": str(e)})
    failed = [x for x in results if not x["ok"]]
    return {"ok": not failed, "results": results, "failed": len(failed), "truncated": truncated}


# ── 名字解析 (对标 cc-connect resolveUserName / resolveChatName · 墨言 094 移植) ─────

_USER_NAME_CACHE: dict = {}
_CHAT_NAME_CACHE: dict = {}
_NAME_CACHE_MAX = 512  # LRU 上限 · 防无限涨
_NAME_FAIL_TTL = 3600  # 失败降级值缓存 1h · 防反复调 API 打爆限流 (R1) · 过期后重试
_NAME_CACHE_LOCK = threading.Lock()  # review B: 并发 miss 单飞 · 防惊群调 API + 失败值覆盖成功值


def _cache_get(cache: dict, key: str) -> Optional[str]:
    v = cache.get(key)
    if not isinstance(v, dict):
        return None
    val = v.get("name") or ""
    if not val:
        return None
    # 失败降级值带 expiry · 过期后重新解析 (成功值永不过期)
    if v.get("exp") and time.time() > v["exp"]:
        cache.pop(key, None)
        return None
    return val


def _cache_put(cache: dict, key: str, val: str, fail: bool = False) -> None:
    if len(cache) >= _NAME_CACHE_MAX:
        # 简单淘汰: 清掉一半最旧的 (dict 保持插入序)
        for k in list(cache.keys())[: len(cache) // 2]:
            cache.pop(k, None)
    cache[key] = {"name": val, "exp": (time.time() + _NAME_FAIL_TTL) if fail else 0}


def resolve_user_name(open_id: str) -> str:
    """open_id → 用户显示名 (Contact API · 带缓存 · 对标 cc resolveUserName)。

    失败/无权限 → 原样返回 open_id (cc 同构降级) · 不抛异常不阻塞主链路。
    review B: 锁内双重检查 · 并发 miss 只调一次 API · 失败值不覆盖已成功写入的真名。
    """
    if not open_id or len(open_id) > 64:
        return open_id
    cached = _cache_get(_USER_NAME_CACHE, open_id)
    if cached:
        return cached
    with _NAME_CACHE_LOCK:
        cached = _cache_get(_USER_NAME_CACHE, open_id)
        if cached:
            return cached
        token = get_tenant_token()
        if not token:
            return open_id
        try:
            import urllib.parse as _up
            url = f"{_BASE}/open-apis/contact/v3/users/{_up.quote(open_id)}"
            status, d = _api_request("GET", url, token=token, params={"user_id_type": "open_id"}, timeout=10)
            if status == 200:
                user = ((d.get("data") or {}).get("user")) or {}
                name = user.get("name") or ""
                if name:
                    _cache_put(_USER_NAME_CACHE, open_id, name)
                    return name
            logger.debug("feishu resolve_user_name 无数据: %s http=%s", open_id, status)
            _cache_put(_USER_NAME_CACHE, open_id, open_id, fail=True)  # R1: 失败也缓存防重复 API
        except Exception as e:
            logger.warning("feishu resolve_user_name 异常: %s", e)
            _cache_put(_USER_NAME_CACHE, open_id, open_id, fail=True)
        return open_id


def resolve_chat_name(chat_id: str) -> str:
    """chat_id → 群名 (IM API · 带缓存 · 对标 cc resolveChatName)。失败 → 原样返回。"""
    if not chat_id or len(chat_id) > 64:
        return chat_id
    cached = _cache_get(_CHAT_NAME_CACHE, chat_id)
    if cached:
        return cached
    with _NAME_CACHE_LOCK:  # review B: 锁内双重检查
        cached = _cache_get(_CHAT_NAME_CACHE, chat_id)
        if cached:
            return cached
        token = get_tenant_token()
        if not token:
            return chat_id
        try:
            import urllib.parse as _up
            url = f"{_BASE}/open-apis/im/v1/chats/{_up.quote(chat_id)}"
            status, d = _api_request("GET", url, token=token, timeout=10)
            if status == 200:
                name = ((d.get("data") or {}).get("chat") or {}).get("name") or ""
                if name:
                    _cache_put(_CHAT_NAME_CACHE, chat_id, name)
                    return name
            logger.debug("feishu resolve_chat_name 无数据: %s http=%s", chat_id, status)
            _cache_put(_CHAT_NAME_CACHE, chat_id, chat_id, fail=True)  # R1: 失败也缓存防重复 API
        except Exception as e:
            logger.warning("feishu resolve_chat_name 异常: %s", e)
            _cache_put(_CHAT_NAME_CACHE, chat_id, chat_id, fail=True)
        return chat_id


# ── 状态 ──────────────────────────────────────────────────

def status() -> dict:
    cfg = load_config()
    return {
        "configured": is_configured(),
        "enabled": enabled(),
        "app_id": (cfg.get("app_id") or "")[:8] + "***" if is_configured() else "",
        "token_ok": bool(get_tenant_token()),
        "has_secret": bool(cfg.get("app_secret")),
        "webhook": bool(cfg.get("webhook_url")),
    }
