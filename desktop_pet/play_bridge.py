"""陪玩走 daemon：转写 / 陪伴 /chat / TTS。不另起脑子。"""

from __future__ import annotations

import io
import json
import re
import wave
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

PET_DIR = Path(__file__).resolve().parent
ROOT = PET_DIR.parent
ACK_FILES = (PET_DIR / "play_ack.mp3", PET_DIR / "play_ack.wav")
BYE_FILES = (PET_DIR / "play_bye.mp3", PET_DIR / "play_bye.wav")
_FACE_RE = re.compile(r"\n?<face>\s*[^<]+?\s*</face>", re.I)
_DETAIL_RE = re.compile(r"<detail>.*?</detail>", re.I | re.S)
_LEFTOVER_RE = re.compile(r"</?(?:face|detail)[^>]*>", re.I)
_FACE_ONE = re.compile(r"<face>\s*([^<]+?)\s*</face>", re.I)
_FACE_ALIAS = {
    "care": "happy", "关心": "happy",
    "sad": "sleepy", "难过": "sleepy",
    "shy": "confused", "羞": "confused",
    "puff": "surprised", "鼓脸": "surprised",
    "happy": "happy", "高兴": "happy",
}


def _env() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    except Exception:
        pass
    return out


def _base() -> tuple[str, dict[str, str]]:
    env = _env()
    port = (env.get("OPUS_API_PORT") or env.get("PORT") or "7860").strip()
    token = (env.get("OPUS_API_TOKEN") or "").strip()
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    return f"http://127.0.0.1:{port}", headers


def pcm_wav(pcm: bytes, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(rate) or 16000)
        w.writeframes(pcm)
    return buf.getvalue()


def _call(path: str, *, data: bytes | None = None, headers: dict | None = None,
          timeout: float = 60, method: str = "POST") -> tuple[int, bytes]:
    root, auth = _base()
    h = dict(auth)
    if headers:
        h.update(headers)
    req = Request(root + path, data=data, headers=h, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except HTTPError as e:
        return e.code, e.read() if e.fp else b""
    except (URLError, TimeoutError, OSError):
        return 0, b""


def stt_ready() -> str:
    """空字符串 = 能转写。"""
    code, body = _call("/stt/status", method="GET", timeout=5)
    if code != 200:
        return "daemon 不在线，语音唤醒开不了"
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception:
        return "语音状态读不到"
    if data.get("enabled") is False:
        return "本地 whisper 关了 · 去设置页打开"
    if data.get("ready"):
        return ""
    return "语音识别还没装好 · 去设置页打开本地 whisper"


def transcribe(wav: bytes, timeout: float = 45, *, spot: bool = False, prompt: str = "") -> str:
    q = []
    if spot:
        q.append("spot=1")
    if prompt.strip():
        q.append("prompt=" + quote(prompt.strip()))
    path = "/stt/transcribe-wav" + (("?" + "&".join(q)) if q else "")
    code, body = _call(
        path,
        data=wav,
        headers={"Content-Type": "audio/wav"},
        timeout=timeout,
    )
    if code != 200:
        return ""
    try:
        return str(json.loads(body.decode("utf-8")).get("text") or "").strip()
    except Exception:
        return ""


def speakable(text: str) -> str:
    """房间表情/折叠标签是给画面的，不能拿去出声。"""
    s = _FACE_RE.sub("", text or "")
    s = _DETAIL_RE.sub("", s)
    s = _LEFTOVER_RE.sub("", s)
    return re.sub(r"[ \t]+\n", "\n", s).strip()


def face_of(text: str, hinted: str = "") -> str:
    raw = (hinted or "").strip()
    if not raw:
        m = _FACE_ONE.search(text or "")
        raw = (m.group(1).strip() if m else "")
    return _FACE_ALIAS.get(raw) or _FACE_ALIAS.get(raw.lower()) or ""


def chat(message: str, sid: str, *, think: bool = True) -> tuple[str, str, str, str]:
    """return (reply, sid, error, face)."""
    payload = {
        "message": message,
        "session_id": sid or None,
        "auto_confirm": True,
        "mode": "companion",
        "thinking": "on" if think else "off",
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    code, body = _call(
        "/chat",
        data=raw,
        headers={"Content-Type": "application/json"},
        timeout=180,
    )
    if code != 200:
        return "", sid, f"对话失败 ({code or 'offline'})", ""
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception:
        return "", sid, "对话返回坏了", ""
    raw = str(data.get("reply") or "").strip()
    new_sid = str(data.get("session_id") or "").strip() or sid
    face = face_of(raw, str(data.get("companion_face") or ""))
    return speakable(raw), new_sid, "", face


def label_session(sid: str) -> None:
    """工作台话题列表能认出这是桌宠语音，不跟房间聊混。"""
    s = (sid or "").strip()
    if not s.startswith("api-"):
        return
    name = "语音唤醒 " + datetime.now().strftime("%m-%d %H:%M")
    raw = json.dumps({"label": name}, ensure_ascii=False).encode("utf-8")
    _call(
        f"/sessions/{s}/meta",
        data=raw,
        headers={"Content-Type": "application/json"},
        timeout=8,
    )


def tts_to(text: str, dest: Path) -> str:
    raw = json.dumps({"text": text[:2000]}, ensure_ascii=False).encode("utf-8")
    code, body = _call(
        "/api/tts",
        data=raw,
        headers={"Content-Type": "application/json"},
        timeout=40,
    )
    if code != 200 or not body:
        return f"语音合成失败 ({code or 'offline'})"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return ""


def _first_sound(files) -> Path | None:
    for path in files:
        if path.is_file() and path.stat().st_size > 80:
            return path
    return None


def ack_mp3() -> Path | None:
    """随桌宠走的「我在」· 不打 TTS。"""
    return _first_sound(ACK_FILES)


def bye_mp3() -> Path | None:
    """听着没人说话时的退场 · 不打 TTS。"""
    return _first_sound(BYE_FILES)
