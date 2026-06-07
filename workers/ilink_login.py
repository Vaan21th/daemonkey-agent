"""
workers/ilink_login.py · iLink 扫码登录核心 · 给 WebUI 设置面板的二维码登录用 (卷六十一)

登录这步不需要 bot_token (还没有)·走 GET get_bot_qrcode / get_qrcode_status。这层把二维码
渲染成 base64 data URI 直接塞进网页 (前端 <img> 即显·不依赖任何 JS 二维码库)·并在 confirmed
时把 bot_token 落到 ilink_client 那份 gitignored 的 token 文件。CLI 版在 tools/ilink_login.py。
"""
from __future__ import annotations

import base64
import io
import json
from datetime import datetime, timezone

import requests

_BASE = "https://ilinkai.weixin.qq.com"
_HEADERS = {"Content-Type": "application/json", "AuthorizationType": "ilink_bot_token"}


def _render_data_uri(content: str) -> str:
    import qrcode

    qr = qrcode.QRCode(border=2, box_size=8)
    qr.add_data(content)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def fetch_qr() -> dict:
    """取登录二维码 · 返回 {qrcode_id, scan_url, qr_data_uri}。"""
    r = requests.get(f"{_BASE}/ilink/bot/get_bot_qrcode?bot_type=3", headers=_HEADERS, timeout=12)
    r.raise_for_status()
    d = r.json()
    if d.get("ret") != 0:
        raise RuntimeError(f"get_bot_qrcode ret={d.get('ret')}")
    qid, url = d["qrcode"], d["qrcode_img_content"]
    return {"qrcode_id": qid, "scan_url": url, "qr_data_uri": _render_data_uri(url)}


def _save_token(d: dict) -> None:
    from workers.ilink_client import _TOKEN_FILE

    payload = {
        "bot_token": d.get("bot_token"),
        "baseurl": d.get("baseurl") or _BASE,
        "raw": d,
        "obtained_at": datetime.now(timezone.utc).isoformat(),
    }
    _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    _TOKEN_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def poll_status(qrcode_id: str) -> dict:
    """查一次扫码状态。confirmed 时落 token 并拉起监听·返回 {status, logged_in}。
    状态机: wait (没扫) → confirmed (扫了授权·带 bot_token) / expired (过期)。"""
    r = requests.get(
        f"{_BASE}/ilink/bot/get_qrcode_status?qrcode={qrcode_id}", headers=_HEADERS, timeout=12
    )
    try:
        d = r.json()
    except ValueError:
        return {"status": "error", "logged_in": False}
    status = str(d.get("status", d.get("ret"))).lower()
    if d.get("bot_token"):
        _save_token(d)
        try:  # 首次登录时监听还没起·扫完即拉起·不用重启 daemon
            from workers.wechat_listener import start_listener_in_background

            start_listener_in_background()
        except Exception:
            pass
        return {"status": "confirmed", "logged_in": True}
    return {"status": status, "logged_in": False}
