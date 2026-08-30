"""
api_routes/companion.py · DAIMON 陪伴模式静态路由
=====================================================

GET /companion/{path} → static/companion/ 目录级静态服务

为什么不进 core.py 的 _STATIC_WHITELIST:
  陪伴模式有 40+ 素材文件(日夜家具/IP 状态机帧), 文件级白名单每加一张图
  都要改代码+重启 daemon。目录级白名单把信任边界定在 static/companion/
  这个文件夹上——里面只放陪伴模式前端资产, 和 vtuber/ 目录同级待遇。

安全: 拒绝 .. 越界 · 只允许白名单后缀 · 目录外文件一律 404。
"""
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from api_routes._deps import check_auth

router = APIRouter()


def companion_she_fields() -> dict:
    """点她弹的卡：当天覆盖压过 SHE-STATE 当下。"""
    out: dict = {
        "she_mood_live": False,
        "she_mood_key": "",
        "she_face": "",
    }
    try:
        from identity import she_state
        snap = she_state()
        out["she_mood"] = snap.get("mood") or ""
        out["she_mood_as_of"] = snap.get("mood_as_of") or ""
        out["she_dims"] = snap.get("dims")
        try:
            from workers.style_shift import live_dims
            out["she_dims"] = live_dims()
        except Exception:
            pass
        try:
            from workers.bond_ledger import snapshot
            out.update(snapshot())
        except Exception:
            pass
        out["she_note"] = snap.get("note") or ""
    except Exception:
        pass
    try:
        from workers.mood_shift import room_mood_view
        overlay = room_mood_view()
    except Exception:
        overlay = {}
    if overlay.get("live"):
        out["she_mood"] = overlay.get("human") or overlay.get("mood") or ""
        out["she_mood_as_of"] = "today"
        out["she_mood_live"] = True
        out["she_mood_key"] = overlay.get("mood") or ""
        out["she_face"] = overlay.get("face") or ""
    return out


@router.get("/api/companion/weather")
def companion_weather(authorization: Optional[str] = Header(None)):
    """房间天气 · 事实现算。工作台不要走这条。"""
    check_auth(authorization)
    try:
        from workers.weather import refresh
        return refresh()
    except ImportError:
        return {"ok": False, "error": "weather unavailable"}


@router.get("/api/companion/state")
def companion_state(authorization: Optional[str] = Header(None)):
    """全局状态卡 · 只读 `## 〇、状态卡` 段 · 陪伴问候决策用（不调 load_cognition 全量）。
    也带回她的脸：当天覆盖压过 SHE-STATE 当下，本子不改。"""
    check_auth(authorization)
    from workers.cognition_loader import (
        BRO_NOTEBOOK,
        _parse_state_card,
        _parse_state_card_history,
    )
    out = {"state_card": {}, "state_card_history": {}}
    if BRO_NOTEBOOK.exists():
        text = BRO_NOTEBOOK.read_text(encoding="utf-8")
        out["state_card"] = _parse_state_card(text)
        out["state_card_history"] = _parse_state_card_history(text)
    # 她 · 状态：覆盖在时压过 SHE-STATE 当下，本子不改
    out.update(companion_she_fields())
    try:
        from workers.she_play import maybe_invite
        maybe_invite()
    except Exception:
        pass
    try:
        from workers.she_gallery_feedback import card_is_low, history, inbox, public_image
        card = inbox()
        if card:
            out["gallery_inbox"] = {
                **card,
                "image_url": public_image(card.get("image") or ""),
                "low": card_is_low(card),
            }
        out["gallery_history"] = history()
    except Exception:
        out.setdefault("gallery_history", [])
    return out


@router.post("/api/companion/gallery/respond")
async def companion_gallery_respond(request: Request, authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    body = await request.json()
    from workers.she_gallery_feedback import respond
    return respond(str(body.get("action") or ""))


@router.post("/api/companion/weather/veto")
async def companion_weather_veto(request: Request, authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    body = await request.json()
    try:
        from workers.weather import veto
    except ImportError:
        return {"ok": False, "error": "weather unavailable"}
    return veto(str(body.get("key") or ""))


@router.post("/api/companion/play/start")
async def companion_play_start(authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    from workers.she_play import start
    return start()


@router.post("/api/companion/play/finish")
async def companion_play_finish(request: Request, authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    body = await request.json()
    from workers.she_play import finish
    return finish(
        pairs=body.get("pairs"),
        moves=body.get("moves"),
        result=body.get("result"),
        done=body.get("done"),
    )


@router.post("/api/companion/play/ignore")
async def companion_play_ignore(authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    from workers.she_play import ignore
    return ignore()


ROOT = Path(__file__).resolve().parent.parent
_COMPANION_DIR = ROOT / "static" / "companion"
_GAMES_DIR = ROOT / "static" / "games"

_MIMES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".webp": "image/webp",
    ".jpg": "image/jpeg",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


def _file_under(root: Path, path: str) -> Path:
    if ".." in path or path.startswith("/") or path.startswith("\\"):
        raise HTTPException(400, "invalid path")
    full = (root / path).resolve()
    try:
        full.relative_to(root.resolve())
    except ValueError:
        raise HTTPException(400, "invalid path")
    if not full.is_file():
        raise HTTPException(404, "not found")
    return full


@router.get("/games/{path:path}")
async def serve_games(path: str):
    full = _file_under(_GAMES_DIR, path)
    media = _MIMES.get(full.suffix.lower())
    if media is None:
        raise HTTPException(404, f"game asset type not allowed: {full.suffix}")
    return FileResponse(full, media_type=media, headers={"Cache-Control": "no-cache, must-revalidate"})


@router.get("/companion/{path:path}")
async def serve_companion(path: str):
    full = _file_under(_COMPANION_DIR, path)
    media = _MIMES.get(full.suffix.lower())
    if media is None:
        raise HTTPException(404, f"companion asset type not allowed: {full.suffix}")
    # 初见起的 AI 名 · 和工作台 /ui 同一套注入, 家具才能叫「她给你泡的茶」
    if full.name == "index.html":
        from api_routes.core import _bust_static_cache, _inject_ai_name
        html = _inject_ai_name(_bust_static_cache(full.read_text(encoding="utf-8")))
        return HTMLResponse(html, headers={"Cache-Control": "no-cache, must-revalidate"})
    return FileResponse(full, media_type=media, headers={"Cache-Control": "no-cache, must-revalidate"})
