"""
workers/ilink_media.py · 微信发媒体 (图片/视频/文件) · CDN 上传 + AES-128-ECB (卷六十二)

官方 openclaw-weixin 出站媒体链路的纯 Python 复刻：
  读文件 → md5 → 随机 aeskey/filekey → getuploadurl(no_need_thumb) → AES-128-ECB+PKCS7 加密
  → POST 密文到 upload_full_url (响应头 x-encrypted-param = 下载参数) → sendmessage 带 image/video/file_item。

跟官方一致：视频也走 no_need_thumb·不带缩略图 (所以零 ffmpeg 依赖)。
全部受 ilink 24h 窗口约束 —— 窗口关着直接拒发 (这是官方钉死的规则·不是我们的限制)。
"""
from __future__ import annotations

import base64
import hashlib
import logging
import math
import mimetypes
import os
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import requests
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from . import ilink_client

logger = logging.getLogger("opus.ilink.media")

_ROOT = Path(__file__).resolve().parent.parent

# 服务端通常直接返回 upload_full_url·这个只在它没返回时兜底拼接
_CDN_BASE = "https://novac2c.cdn.weixin.qq.com/c2c"

# UploadMediaType (getuploadurl) 与 MessageItemType (sendmessage) 编号不同·别搞混
_UPLOAD_IMAGE, _UPLOAD_VIDEO, _UPLOAD_FILE = 1, 2, 3
_ITEM_IMAGE, _ITEM_VIDEO, _ITEM_FILE = 2, 5, 4

_MAX_BYTES = 25 * 1024 * 1024  # 留个上限·别把 daemon 内存撑爆


def _padded_size(n: int) -> int:
    """AES-128-ECB + PKCS7 密文长度 (官方 aesEcbPaddedSize)。"""
    return math.ceil((n + 1) / 16) * 16


def _aes_ecb_encrypt(plaintext: bytes, key: bytes) -> bytes:
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    enc = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return enc.update(padded) + enc.finalize()


def _kind(path: Path) -> tuple[str, int, int]:
    """按 MIME 路由：video/* → 视频·image/* → 图片·其余 → 文件附件。
    返回 (kind, upload_media_type, message_item_type)。"""
    mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    if mime.startswith("video/"):
        return "video", _UPLOAD_VIDEO, _ITEM_VIDEO
    if mime.startswith("image/"):
        return "image", _UPLOAD_IMAGE, _ITEM_IMAGE
    return "file", _UPLOAD_FILE, _ITEM_FILE


def _upload(plaintext: bytes, media_type: int, to_user_id: str) -> dict:
    """加密上传一个文件到微信 CDN·返回 {download_param, aeskey_hex, file_size, cipher_size}。"""
    rawsize = len(plaintext)
    aeskey = os.urandom(16)
    filekey = os.urandom(16).hex()
    resp = ilink_client.get_upload_url(
        {
            "filekey": filekey,
            "media_type": media_type,
            "to_user_id": to_user_id,
            "rawsize": rawsize,
            "rawfilemd5": hashlib.md5(plaintext).hexdigest(),
            "filesize": _padded_size(rawsize),
            "no_need_thumb": True,
            "aeskey": aeskey.hex(),
        }
    )
    full_url = (resp.get("upload_full_url") or "").strip()
    upload_param = resp.get("upload_param")
    if not full_url and not upload_param:
        raise RuntimeError(f"getuploadurl 无上传地址: {resp}")
    cdn_url = full_url or (
        f"{_CDN_BASE}/upload?encrypted_query_param={quote(upload_param)}&filekey={quote(filekey)}"
    )
    ciphertext = _aes_ecb_encrypt(plaintext, aeskey)
    last = ""
    for _ in range(3):
        r = requests.post(
            cdn_url,
            data=ciphertext,
            headers={"Content-Type": "application/octet-stream"},
            timeout=120,
        )
        if 400 <= r.status_code < 500:
            raise RuntimeError(f"CDN 4xx: {r.status_code} {r.headers.get('x-error-message', '')}")
        if r.status_code == 200:
            dp = r.headers.get("x-encrypted-param")
            if dp:
                return {
                    "download_param": dp,
                    "aeskey_hex": aeskey.hex(),
                    "file_size": rawsize,
                    "cipher_size": _padded_size(rawsize),
                }
        last = f"{r.status_code} {r.headers.get('x-error-message', '')}"
    raise RuntimeError(f"CDN 上传失败 (重试 3 次): {last}")


def _media_block(info: dict) -> dict:
    # 官方：aes_key = base64(aeskey 的 hex 字符串)·不是 base64(原始字节)
    return {
        "encrypt_query_param": info["download_param"],
        "aes_key": base64.b64encode(info["aeskey_hex"].encode()).decode(),
        "encrypt_type": 1,
    }


def _build_item(kind: str, item_type: int, info: dict, file_name: str) -> dict:
    media = _media_block(info)
    if kind == "image":
        return {"type": item_type, "image_item": {"media": media, "mid_size": info["cipher_size"]}}
    if kind == "video":
        return {"type": item_type, "video_item": {"media": media, "video_size": info["cipher_size"]}}
    return {
        "type": item_type,
        "file_item": {"media": media, "file_name": file_name, "len": str(info["file_size"])},
    }


def send_media(path: str, caption: str = "", *, to_user_id: Optional[str] = None) -> dict:
    """给用户发一个本地文件 (图片/视频/其它=文件附件)·caption 作为前导文字。
    返回 {ok, kind, bytes} 或 {ok:False, error}。窗口关/未配置/文件问题都在这里挡掉。"""
    if not ilink_client.enabled():
        return {"ok": False, "error": "ilink_not_enabled"}
    if ilink_client.is_silent():
        return {"ok": False, "error": "silent_mode"}
    if not ilink_client.window_open():
        return {"ok": False, "error": "window_closed"}
    p = Path(path).expanduser()
    if not p.is_file():
        return {"ok": False, "error": f"file_not_found: {path}"}
    size = p.stat().st_size
    if size == 0:
        return {"ok": False, "error": "empty_file"}
    if size > _MAX_BYTES:
        return {"ok": False, "error": f"file_too_large: {size} bytes (limit {_MAX_BYTES})"}
    _, _, user = ilink_client.load_token()
    to = to_user_id or user
    kind, upload_type, item_type = _kind(p)
    try:
        info = _upload(p.read_bytes(), upload_type, to)
        item = _build_item(kind, item_type, info, p.name)
        r = ilink_client.send_media_item(item, caption=caption, to_user_id=to)
    except Exception as e:  # 上传 / 加密 / 网络 / sendmessage 任何一环挂了都收口在这
        logger.warning("send_media failed: %s", e)
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    if not r.get("ok"):
        return {"ok": False, "error": "sendmessage_rejected", "resp": r}
    return {"ok": True, "kind": kind, "bytes": size}


# ---------------------------------------------------------------- 收 (inbound)
_MAX_IN_BYTES = 50 * 1024 * 1024
_INBOUND_ITEM = {
    _ITEM_IMAGE: ("image", "image_item"),
    _ITEM_VIDEO: ("video", "video_item"),
    _ITEM_FILE: ("file", "file_item"),
}


def _aes_ecb_decrypt(ciphertext: bytes, key: bytes) -> bytes:
    dec = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    padded = dec.update(ciphertext) + dec.finalize()
    unpad = padding.PKCS7(128).unpadder()
    return unpad.update(padded) + unpad.finalize()


def _parse_aes_key(aes_key_b64: str) -> bytes:
    """CDNMedia.aes_key → 16 字节裸 key。两种编码：base64(裸 16 字节) 或 base64(32 位 hex 串)。"""
    decoded = base64.b64decode(aes_key_b64)
    if len(decoded) == 16:
        return decoded
    if len(decoded) == 32:
        try:
            return bytes.fromhex(decoded.decode("ascii"))
        except (UnicodeDecodeError, ValueError):
            pass
    raise ValueError(f"aes_key 无法解为 16 字节: 实际 {len(decoded)}")


def _download_cdn(encrypt_query_param: str, full_url: str = "") -> bytes:
    url = (full_url or "").strip() or (
        f"{_CDN_BASE}/download?encrypted_query_param={quote(encrypt_query_param)}"
    )
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    if len(r.content) > _MAX_IN_BYTES:
        raise RuntimeError(f"inbound 媒体过大: {len(r.content)} bytes")
    return r.content


def sniff_image_mime(data: bytes) -> str:
    """按文件头判图片类型 (inbound 图不带扩展名)。"""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"GIF8"):
        return "image/gif"
    if data.startswith(b"BM"):
        return "image/bmp"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"  # 兜底·微信图多为 jpg


def _resolve_in_key(sub: dict, media: dict) -> Optional[bytes]:
    hexk = sub.get("aeskey")
    if hexk:
        try:
            return bytes.fromhex(hexk)
        except ValueError:
            pass
    ak = media.get("aes_key")
    if ak:
        return _parse_aes_key(ak)
    return None  # 无 key = CDN 明文 (少见)


def download_media_item(item: dict) -> Optional[dict]:
    """下载+解密一个 inbound 媒体 item。返回 {kind, data, name} 或 None (非媒体/缺 CDN 引用)。"""
    spec = _INBOUND_ITEM.get(item.get("type"))
    if not spec:
        return None
    kind, key_name = spec
    sub = item.get(key_name) or {}
    media = sub.get("media") or {}
    eqp = media.get("encrypt_query_param")
    if not eqp:
        return None
    raw = _download_cdn(eqp, media.get("full_url") or "")
    key = _resolve_in_key(sub, media)
    data = _aes_ecb_decrypt(raw, key) if key else raw
    return {"kind": kind, "data": data, "name": sub.get("file_name") or ""}


def save_inbound(kind: str, data: bytes, name: str = "") -> str:
    """非图片媒体落地·返回相对路径 (喂给 OPUS 当线索)。"""
    d = _ROOT / "data" / "runtime" / "wechat_inbound"
    d.mkdir(parents=True, exist_ok=True)
    if not name:
        name = f"{kind}." + ("mp4" if kind == "video" else "bin")
    safe = "".join(c for c in name if c.isalnum() or c in "._-") or "file.bin"
    p = d / f"{int(time.time())}_{safe}"
    p.write_bytes(data)
    try:
        return str(p.relative_to(_ROOT))
    except ValueError:
        return str(p)
