"""
tools/ilink_login.py · iLink/ClawBot 微信登录 · 裸 HTTP 扫码取 bot_token (卷六十一 · phase 2)

不依赖 openclaw 网关 / Node —— iLink 底层就是 HTTP/JSON。走官方 bot_type=3 个人号扫码流程：
get_bot_qrcode → 渲染二维码 PNG → 用户微信扫 → 轮询 get_qrcode_status → 落 bot_token。
token 是密钥，落在 gitignored 的 data/runtime/ilink_token.json，绝不进 git。
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import qrcode
import requests

BASE = "https://ilinkai.weixin.qq.com"
HEADERS = {"Content-Type": "application/json", "AuthorizationType": "ilink_bot_token"}
ROOT = Path(__file__).resolve().parent.parent
QR_PNG = ROOT / "data" / "runtime" / "ilink_qr.png"
TOKEN_FILE = ROOT / "data" / "runtime" / "ilink_token.json"
POLL_TIMEOUT = 240
POLL_INTERVAL = 2.5


def _say(msg: str) -> None:
    print(msg, flush=True)


def get_qrcode(retries: int = 4) -> tuple[str, str]:
    last_err = None
    for _ in range(retries):  # iLink 服务器时不时抽风，取码也要扛
        try:
            r = requests.get(
                f"{BASE}/ilink/bot/get_bot_qrcode?bot_type=3", headers=HEADERS, timeout=12
            )
            r.raise_for_status()
            data = r.json()
            if data.get("ret") != 0:
                raise RuntimeError(f"get_bot_qrcode ret={data.get('ret')}: {data}")
            return data["qrcode"], data["qrcode_img_content"]
        except Exception as e:
            last_err = e
            _say(f"[get_qr retry] {e}")
            time.sleep(2)
    raise RuntimeError(f"get_bot_qrcode failed after {retries}: {last_err}")


def render_qr(content: str) -> Path:
    QR_PNG.parent.mkdir(parents=True, exist_ok=True)
    qr = qrcode.QRCode(border=2, box_size=10)
    qr.add_data(content)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(QR_PNG)
    return QR_PNG


class QrExpired(Exception):
    pass


def poll(qrcode_id: str) -> dict:
    deadline = time.time() + POLL_TIMEOUT
    last = None
    while time.time() < deadline:
        try:
            r = requests.get(
                f"{BASE}/ilink/bot/get_qrcode_status?qrcode={qrcode_id}",
                headers=HEADERS,
                timeout=12,
            )
            data = r.json()
        except Exception as e:  # 网络抖动不该中断扫码窗口
            _say(f"[poll err] {e}")
            time.sleep(POLL_INTERVAL)
            continue
        status = str(data.get("status", data.get("ret"))).lower()
        if status != last:
            _say(f"[status] {json.dumps(data, ensure_ascii=False)}")
            last = status
        if data.get("bot_token"):
            return data
        if status in ("confirmed", "success", "ok"):
            return data
        if status == "expired":  # 立刻收手，让上层重生一张，别傻等
            raise QrExpired()
        time.sleep(POLL_INTERVAL)
    raise TimeoutError("scan timeout")


def main() -> int:
    _say("[1/3] 取二维码 ...")
    qrcode_id, img_content = get_qrcode()
    _say(f"[ok] qrcode_id={qrcode_id}")
    _say(f"[ok] scan_url={img_content}")
    png = render_qr(img_content)
    _say(f"[2/3] 二维码已存: {png}")
    _say("[3/3] 等待微信扫码确认 (<=240s) ...")
    try:
        data = poll(qrcode_id)
    except QrExpired:
        _say("[EXPIRED] 二维码过期，未在窗口内完成扫码确认。重新跑本脚本再扫一次。")
        return 2
    payload = {
        "bot_token": data.get("bot_token"),
        "baseurl": data.get("baseurl") or BASE,
        "raw": data,
        "obtained_at": datetime.now(timezone.utc).isoformat(),
    }
    TOKEN_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _say(f"[DONE] bot_token 已落: {TOKEN_FILE}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        _say(f"[FATAL] {e}")
        sys.exit(1)
