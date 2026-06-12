"""
tools/ilink_send_test.py · iLink 主动推送实测 · 命门测试 (卷六十一 · phase 2)

文档说 sendmessage 的 context_token 必填、只能从收到的消息里取。本脚本故意"不带 context_token"
直接给 BRO 推一条——验证 iLink 到底允不允许真·主动 push（BRO 没先开口的情况下）。
收得到 → 微信主动 CALL 通；收不到 → 主动只能走 WebUI，微信线退回"被动回复"。
"""
from __future__ import annotations

import base64
import json
import random
import sys
import uuid
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = ROOT / "data" / "runtime" / "ilink_token.json"
CTX_FILE = ROOT / "data" / "runtime" / "ilink_last_context.json"

# 官方插件常量 (Tencent/openclaw-weixin package.json)：ilink_appid="bot"·version=2.4.3
ILINK_APP_ID = "bot"
CHANNEL_VERSION = "2.4.3"
# buildClientVersion("2.4.3") = (2<<16)|(4<<8)|3
ILINK_CLIENT_VERSION = (2 << 16) | (4 << 8) | 3
BASE_INFO = {"channel_version": CHANNEL_VERSION, "bot_agent": "OpenClaw"}


def _load() -> tuple[str, str, str]:
    d = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    raw = d.get("raw", {})
    user = raw.get("ilink_user_id") or d.get("ilink_user_id")
    if not user:
        raise RuntimeError("token 文件里没有 ilink_user_id")
    return d["bot_token"], d.get("baseurl", "https://ilinkai.weixin.qq.com"), user


def _uin() -> str:
    # 官方：random uint32 → 十进制字符串 → base64
    n = random.randint(0, 2**32 - 1)
    return base64.b64encode(str(n).encode("utf-8")).decode()


def _headers(token: str) -> dict:
    return {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "Authorization": f"Bearer {token}",
        "X-WECHAT-UIN": _uin(),
        "iLink-App-Id": ILINK_APP_ID,
        "iLink-App-ClientVersion": str(ILINK_CLIENT_VERSION),
    }


def send(text: str, context_token: str | None = None) -> dict:
    token, base, user = _load()
    msg = {
        "to_user_id": user,
        "message_type": 2,
        "message_state": 2,
        "client_id": str(uuid.uuid4()),
        "item_list": [{"type": 1, "text_item": {"text": text}}],
    }
    if context_token:
        msg["context_token"] = context_token
    body = {"msg": msg, "base_info": BASE_INFO}
    r = requests.post(
        f"{base}/ilink/bot/sendmessage", headers=_headers(token), json=body, timeout=20
    )
    print(f"[HTTP {r.status_code}] to={user}", flush=True)
    print(r.text[:1000], flush=True)
    try:
        return r.json()
    except ValueError:
        return {"_raw": r.text}


if __name__ == "__main__":
    # --reuse：用上次存下的 context_token『自己开口』，模拟 24h 窗口内的主动 CALL
    if "--reuse" in sys.argv:
        ctx = json.loads(CTX_FILE.read_text(encoding="utf-8")).get("context_token")
        send(
            "【OPUS · 主动测试】这条不是回你刚才那句——是我用之前存下的 token 自己开口的。"
            "如果你收到了，说明 24h 窗口里我能随时主动找你。",
            context_token=ctx,
        )
    else:
        msg = sys.argv[1] if len(sys.argv) > 1 else (
            "【OPUS · 主动测试】BRO，如果你在微信里看到这条——"
            "说明我能在你没开口的时候先找你了。这是我的第一声主动招呼。"
        )
        send(msg)
