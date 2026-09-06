"""工坊应用钉成 Daemonkey 默认生图 / 语音合成 / 语音识别。

启发式只预填。人在设置里选定之后写入 data/runtime/media_defaults.json，
generate_image / /api/tts / 整句转写 先认这只，不再每次猜。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "data" / "runtime" / "media_defaults.json"
LEGACY_TTS_APP = "app-6f439831"

_TTS_KW = (
    "tts", "配音", "语音合成", "speech", "t2a", "minimax", "海螺",
    "火山语音", "openspeech", "voice clone", "声音克隆",
)
_TTS_OUT = {"audio_url", "audio_path", "audio", "mp3_url", "wav_url"}
_TTS_EXTS = (".mp3", ".wav", ".ogg", ".m4a")
_NON_TTS_KW = (
    "视频", "video", "wan2", "kling", "vidu", "runway", "sora",
    "生图", "文生图", "出图", "flux", "midjourney",
)
_STT_KW = (
    "stt", "asr", "转写", "语音识别", "speech to text", "speech-to-text",
    "whisper-api", "sensevoice", "听写", "transcription",
)
_NON_STT_KW = (
    "视频", "video", "clip", "剪辑", "funclip", "字幕", "srt",
)


def load() -> dict:
    try:
        if CONFIG.is_file():
            data = json.loads(CONFIG.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {
                    "image_app_id": str(data.get("image_app_id") or "").strip(),
                    "tts_app_id": str(data.get("tts_app_id") or "").strip(),
                    "stt_app_id": str(data.get("stt_app_id") or "").strip(),
                }
    except Exception:
        pass
    return {"image_app_id": "", "tts_app_id": "", "stt_app_id": ""}


def save(
    image_app_id: Optional[str] = None,
    tts_app_id: Optional[str] = None,
    stt_app_id: Optional[str] = None,
) -> dict:
    cur = load()
    if image_app_id is not None:
        cur["image_app_id"] = (image_app_id or "").strip()
    if tts_app_id is not None:
        cur["tts_app_id"] = (tts_app_id or "").strip()
    if stt_app_id is not None:
        cur["stt_app_id"] = (stt_app_id or "").strip()
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    from workers.safe_write import atomic_write_text
    atomic_write_text(CONFIG, json.dumps(cur, ensure_ascii=False, indent=2), backup=False)
    return cur


def pinned_app_id(kind: str) -> str:
    cur = load()
    if kind == "image":
        return cur.get("image_app_id") or ""
    if kind == "tts":
        return cur.get("tts_app_id") or ""
    if kind == "stt":
        return cur.get("stt_app_id") or ""
    return ""


def is_tts_app(app: dict) -> bool:
    if not isinstance(app, dict):
        return False
    blob = ((app.get("name") or "") + " " + (app.get("description") or "")).lower()
    if any(k in blob for k in _NON_TTS_KW):
        return False
    if any(k in blob for k in _TTS_KW):
        return True
    outs = {(o.get("name") or "").strip().lower() for o in (app.get("output_schema") or [])}
    if outs & _TTS_OUT:
        return True
    resp = ((app.get("exec_template") or {}).get("response") or {})
    if resp.get("kind") in ("b64_save", "binary_save"):
        fn = ((resp.get("save") or {}).get("filename") or "").lower()
        if fn.endswith(_TTS_EXTS):
            return True
    return False


def is_stt_app(app: dict) -> bool:
    if not isinstance(app, dict):
        return False
    blob = ((app.get("name") or "") + " " + (app.get("description") or "")).lower()
    if any(k in blob for k in _NON_STT_KW):
        return False
    return any(k in blob for k in _STT_KW)


def classify_app(app: dict) -> str:
    if is_stt_app(app):
        return "stt"
    if is_tts_app(app):
        return "tts"
    from agent_tools.generate_image import _is_image_app
    if _is_image_app(app):
        return "image"
    return "other"


def _apps() -> list:
    try:
        from workers.workshop_assets import list_apps
        return list_apps() or []
    except Exception:
        return []


def picker_rows() -> list[dict]:
    rows = []
    for a in _apps():
        aid = a.get("id") or ""
        if not aid:
            continue
        rows.append({
            "id": aid,
            "name": a.get("name") or aid,
            "kind": classify_app(a),
            "guess": classify_app(a) in ("image", "tts", "stt"),
        })
    return rows


def resolve_tts_app_id() -> str:
    import os
    env = (os.environ.get("DAEMONKEY_TTS_APP_ID") or os.environ.get("OPUS_TTS_APP_ID") or "").strip()
    if env:
        return env
    pin = pinned_app_id("tts")
    if pin:
        return pin
    guessed = [a for a in _apps() if is_tts_app(a)]
    if guessed:
        guessed.sort(key=lambda a: (0 if (a.get("exec_kind") == "scripted") else 1,
                                    -int(a.get("runs") or 0)))
        return guessed[0].get("id") or LEGACY_TTS_APP
    return LEGACY_TTS_APP


def resolve_stt_app_id() -> str:
    import os
    env = (os.environ.get("DAEMONKEY_STT_APP_ID") or os.environ.get("OPUS_STT_APP_ID") or "").strip()
    if env:
        return env
    pin = pinned_app_id("stt")
    if pin:
        return pin
    guessed = [a for a in _apps() if is_stt_app(a)]
    if guessed:
        guessed.sort(key=lambda a: (0 if (a.get("exec_kind") == "scripted") else 1,
                                    -int(a.get("runs") or 0)))
        return guessed[0].get("id") or ""
    return ""


def _has_key(app_id: str) -> bool:
    if not app_id:
        return False
    try:
        from workers.app_secrets import get_secret
        return bool(get_secret(app_id, "api_key"))
    except Exception:
        return False


def _has_companion() -> bool:
    return (ROOT / "static" / "companion" / "index.html").is_file()


def _has_gallery() -> bool:
    return (ROOT / "workers" / "she_gallery.py").is_file()


def _app_name(app_id: str) -> str:
    if not app_id:
        return ""
    try:
        from workers.workshop_assets import load_app
        a = load_app(app_id)
        return (a or {}).get("name") or app_id
    except Exception:
        return app_id


def status() -> dict:
    from agent_tools.generate_image import resolve_image_app, is_configured

    img_app = None
    try:
        img_app = resolve_image_app()
    except Exception:
        img_app = None
    img_id = (img_app or {}).get("id") or pinned_app_id("image")
    tts_id = resolve_tts_app_id()
    stt_id = resolve_stt_app_id()
    env_image = False
    try:
        env_image = bool(is_configured())
    except Exception:
        env_image = False

    tts_unlock = ["工作台「语音对话」里她能出声", "工坊配音流水线能出 mp3"]
    if _has_companion():
        tts_unlock.append("房间里她能说话")
    img_unlock = ["对话里画图", "PPT / 报告自动配图"]
    if _has_gallery():
        img_unlock.append("明信片（她给你寄图）")

    return {
        "apps": picker_rows(),
        "image": {
            "app_id": img_id,
            "name": (img_app or {}).get("name") or _app_name(img_id),
            "ready": bool(img_id and _has_key(img_id)) or env_image,
            "env_model": env_image,
            "unlocks": img_unlock,
        },
        "tts": {
            "app_id": tts_id,
            "name": _app_name(tts_id),
            "ready": _has_key(tts_id),
            "unlocks": tts_unlock,
        },
        "stt": {
            "app_id": stt_id,
            "name": _app_name(stt_id),
            "ready": bool(stt_id and _has_key(stt_id)),
            "unlocks": [
                "桌宠叫到之后的整句更准",
                "微信语音转写更准",
                "没接就继续用你选的本地 whisper",
            ],
        },
        "guides": {
            "image": GUIDE_IMAGE,
            "tts": GUIDE_TTS,
            "stt": GUIDE_STT,
        },
    }


GUIDE_TTS = (
    "帮我接上配音。先看工坊有没有现成的；没有就建一个应用。"
    "带我去官网拿 Key，不要登录、不要编造。"
    "官网：海螺 MiniMax https://platform.minimaxi.com/ 语音合成 T2A；"
    "字节火山 https://console.volcengine.com/speech/service/8 。"
    "Key 写进应用后，告诉我回设置里把它选成默认。"
    "不要跑题。有现成的先用；没有就 create_app（输入 text，输出音频），"
    "Key 用 app_set_secret 写入 api_key。"
)

GUIDE_IMAGE = (
    "帮我接上生图。先看工坊有没有现成的；没有就建一个应用。"
    "带我去官网拿 Key，不要登录、不要编造。"
    "官网：海螺 MiniMax https://platform.minimaxi.com/ ；"
    "硅基流动 https://cloud.siliconflow.cn/ ；通义万相也可以。"
    "Key 写进应用后，告诉我回设置里把它选成默认。"
    "不要跑题。有现成的先用；没有就 create_app（输入 prompt，输出图片），"
    "Key 用 app_set_secret 写入 api_key。"
)

GUIDE_STT = (
    "帮我接上云端语音识别。先看工坊有没有现成的转写应用；没有就建一个。"
    "带我去官网拿 Key，不要登录、不要编造。"
    "要 OpenAI 兼容的 /v1/audio/transcriptions："
    "OpenAI https://platform.openai.com/ ；"
    "Groq https://console.groq.com/ ；"
    "硅基流动 https://cloud.siliconflow.cn/ 。"
    "Key 用 app_set_secret 写入 api_key。"
    "可选再写 base_url（默认 https://api.openai.com/v1）和 model（默认 whisper-1）。"
    "接好后告诉我回设置→多模态，把这个应用选成默认语音识别。"
    "没接就继续用本机 whisper。不要跑题。"
)
