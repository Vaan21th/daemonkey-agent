"""可选云端语音转写。接了工坊应用就走 OpenAI 兼容接口，没接返回空、回本机 whisper。"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("opus.stt")


def resolve_app_id() -> str:
    try:
        from workers.media_defaults import resolve_stt_app_id
        return resolve_stt_app_id()
    except Exception:
        return ""


def ready() -> bool:
    app_id = resolve_app_id()
    if not app_id:
        return False
    try:
        from workers.app_secrets import get_secret
        return bool(get_secret(app_id, "api_key"))
    except Exception:
        return False


def status() -> dict:
    app_id = resolve_app_id()
    name = ""
    if app_id:
        try:
            from workers.workshop_assets import load_app
            name = ((load_app(app_id) or {}).get("name") or app_id)
        except Exception:
            name = app_id
    return {"ready": ready(), "app_id": app_id, "name": name}


def _secret(app_id: str, name: str, default: str = "") -> str:
    try:
        from workers.app_secrets import get_secret
        return (get_secret(app_id, name) or "").strip() or default
    except Exception:
        return default


def _base_url(raw: str) -> str:
    u = (raw or "https://api.openai.com/v1").strip().rstrip("/")
    if u.endswith("/audio/transcriptions"):
        return u[: -len("/audio/transcriptions")]
    if not u.endswith("/v1") and "/v1/" not in u:
        u = u + "/v1"
    return u


def transcribe_cloud(wav_path: str, timeout: float = 20, prompt: str = "") -> str:
    """wav → 云端转写。没接 Key / 失败返回空，调用方回本机。"""
    wav = Path(wav_path)
    if not wav.is_file() or wav.stat().st_size == 0:
        return ""
    app_id = resolve_app_id()
    key = _secret(app_id, "api_key")
    if not key:
        return ""
    base = _base_url(_secret(app_id, "base_url", "https://api.openai.com/v1"))
    model = _secret(app_id, "model", "whisper-1")
    url = base + "/audio/transcriptions"
    try:
        import requests
        with wav.open("rb") as fh:
            data = {"model": model, "language": "zh", "response_format": "json"}
            hint = (prompt or "").strip()
            if hint:
                data["prompt"] = hint
            r = requests.post(
                url,
                headers={"Authorization": "Bearer " + key},
                data=data,
                files={"file": (wav.name, fh, "audio/wav")},
                timeout=timeout,
            )
    except Exception as e:
        logger.warning("云端转写失败: %s", type(e).__name__)
        return ""
    if r.status_code != 200:
        logger.warning("云端转写 HTTP %s", r.status_code)
        return ""
    try:
        body = r.json()
    except Exception:
        return (r.text or "").strip()
    return str(body.get("text") or "").strip()
