"""
api_routes/core.py · 核心路由 (wish-413999da · phase 1)
======================================================

6 路由 · 都是 daemon 最基础的入口·都 noauth (HTML/JS 内 token 由 JS 注):

  GET  /                              · health probe (PlainText "alive")
  GET  /api/ping-test                 · 详细 health probe (JSON ts)
  GET  /ui                            · 静态 chat.html 入口
  GET  /static/{path:path}            · 白名单静态资源 (chat.css/js etc.)
  GET  /workshop/outputs/{filename}   · daemon 工坊产物 (image/audio/video)
  GET  /api/logs/tail                 · daemon.log tail (内网可见即可)

不依赖 closure helpers · 跟 build_app() 解耦。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from api_routes._deps import check_auth


ROOT = Path(__file__).resolve().parent.parent


router = APIRouter()


# ────────────────────────────────────────────────────────────────
# 静态资源白名单 · 不 mount StaticFiles · 防日后误把敏感东西放进 static/
# ────────────────────────────────────────────────────────────────
_STATIC_WHITELIST = {
    "chat.css": "text/css; charset=utf-8",
    "chat.js": "application/javascript; charset=utf-8",
    "workshop.css": "text/css; charset=utf-8",
    "workshop.js": "application/javascript; charset=utf-8",
    # 卷四十四 K · LiteGraph 单文件 (~1MB) · ComfyUI 同款 node editor
    "lib/litegraph.core.js": "application/javascript; charset=utf-8",
    "lib/litegraph.core.css": "text/css; charset=utf-8",
    # 卷五十六 · Chart.js 4.4.7 本地化 (BI 看板图表) · 漏加白名单 = 404 = 雷达/环形图永久空白 (BRO 实测)
    "lib/chart.umd.min.js": "application/javascript; charset=utf-8",
    # 卷四十六 · Remix Icon 4.6.0 字体本地化 (替代 jsdelivr CDN · BRO 网络下 CDN 容易卡)
    "lib/remixicon/remixicon.css": "text/css; charset=utf-8",
    "lib/remixicon/remixicon.woff2": "font/woff2",
    "lib/remixicon/remixicon.woff": "font/woff",
    "lib/remixicon/remixicon.ttf": "font/ttf",
    # 浏览器标签页图标 · 替掉浏览器缓存的陌生默认 favicon
    "favicon.ico": "image/x-icon",
    # 形态 Z · 相遇页 (index.html) 的样式与脚本 · index.html 本身走 /ui 分流返回
    "style.css": "text/css; charset=utf-8",
    "app.js": "application/javascript; charset=utf-8",
}

# 二进制 mime (字体 / 图片) · serve_static 看到这些走 FileResponse · 不 read_text
_BINARY_MIMES = {"font/woff2", "font/woff", "font/ttf", "font/otf", "image/png", "image/jpeg", "image/gif", "image/webp", "image/x-icon"}


def _ai_name() -> str:
    """读用户在『相遇』里给这只 Daemonkey 起的名字 (soul/IDENTITY.json)。没有就空。"""
    try:
        import json
        p = ROOT / "soul" / "IDENTITY.json"
        if p.exists():
            return (json.loads(p.read_text(encoding="utf-8-sig")).get("name") or "").strip()
    except Exception:
        pass
    return ""


def _owner_name() -> str:
    """读用户在『相遇』里给的称呼 (soul/IDENTITY.json owner_name)。没有/还没问到就空。"""
    try:
        import json
        p = ROOT / "soul" / "IDENTITY.json"
        if p.exists():
            return (json.loads(p.read_text(encoding="utf-8-sig")).get("owner_name") or "").strip()
    except Exception:
        pass
    return ""


def _inject_ai_name(html: str) -> str:
    """把 AI 名字 / 主人称呼注成 window.__AI_NAME__ / __OWNER_NAME__ ·
    前端据此把界面里写死的 "OPUS"/"BRO" 换成用户取的名。母体两者都空 → 不注入 → 行为不变。"""
    import json
    tags = []
    name = _ai_name()
    if name:
        tags.append(f"window.__AI_NAME__={json.dumps(name, ensure_ascii=False)};")
    owner = _owner_name()
    if owner:
        tags.append(f"window.__OWNER_NAME__={json.dumps(owner, ensure_ascii=False)};")
    if not tags:
        return html
    # JSON 编码防止名字里有引号 / 特殊字符破坏 <script>
    tag = "<script>" + "".join(tags) + "</script>"
    if "</head>" in html:
        return html.replace("</head>", tag + "</head>", 1)
    return tag + html

# ────────────────────────────────────────────────────────────────
# 工坊产物 MIME (wish-f3b4958e · 卷四十四 K stage 2c++)
# daemon OPUS 装的应用 (GPT Image / SOVITS / Whisper) 生成的媒体落 outputs/
# chat 通过 ![alt](/workshop/outputs/x.png) 直接显示 · BRO 不用翻文件夹
# ────────────────────────────────────────────────────────────────
_OUTPUT_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
    ".bmp": "image/bmp", ".ico": "image/x-icon",
    ".wav": "audio/wav", ".mp3": "audio/mpeg", ".ogg": "audio/ogg",
    ".flac": "audio/flac", ".m4a": "audio/mp4", ".aac": "audio/aac",
    ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
    ".pdf": "application/pdf",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}


@router.get("/", response_class=PlainTextResponse)
async def root():
    # 不验证 · 给 cloudflared / 监控的 health probe 用
    # 不暴露任何 daemon 内部状态
    return "OPUS daemon · alive"


@router.get("/api/ping-test")
async def ping_test():
    """超简单 health probe · 返回 JSON · 不鉴权"""
    from datetime import datetime, timezone
    return {
        "ok": True,
        "msg": "pong round 4 · fourth time still smooth",
        "ts": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/api/core/version")
async def core_version_endpoint():
    """内核语义版本号 · 不鉴权(版本号不敏感·手机浏览器也要能拿) · 卷七十四续二十。

    版本号唯一真相源 = core_manifest.json 的 core_version。WebUI 顶部品牌区开页拉它显示 ·
    launcher 优先直接读文件(daemon 没起也能显示) · 这个端点是 daemon 在跑时的统一出口。
    """
    try:
        from workers import core_update as cu
        m = cu.load_manifest()
        return {
            "core_version": str(m.get("core_version") or ""),
            "manifest_version": m.get("manifest_version"),
            "updated": m.get("updated"),
            "log_ref": m.get("log_ref"),
        }
    except Exception:
        return {"core_version": ""}


@router.get("/ui", response_class=HTMLResponse)
async def web_ui():
    # 不鉴权: HTML 本身不含敏感信息, token 由 JS 让用户手动填进 localStorage
    # 真正鉴权在每个 /chat 调用 · 这样手机浏览器才能 GET 拿到页面
    #
    # 形态 Z 分流 (卷六十三续五): 还没完成『相遇』→ 返回相遇页 index.html;
    # 相遇完成后 → 返回正式 chat.html。判断在 api_routes.onboarding.needs_onboarding()。
    try:
        from api_routes.onboarding import needs_onboarding
        first_meet = needs_onboarding()
    except Exception:
        first_meet = False
    fname = "index.html" if first_meet else "chat.html"
    path = ROOT / "static" / fname
    if not path.exists():
        return HTMLResponse(
            f"<h1>{fname} missing</h1><p>static/{fname} not deployed</p>",
            status_code=500,
        )
    html = path.read_text(encoding="utf-8")
    # 把用户在『相遇』里给这只 Daemonkey 起的名字注进页面 · 前端用它替换写死的 "OPUS"
    # (race-free: 服务端注入·不必等前端再 fetch /status·避免先闪一下 "OPUS")
    return HTMLResponse(_inject_ai_name(html))


@router.get("/static/{path:path}")
async def serve_static(path: str):
    if path not in _STATIC_WHITELIST:
        raise HTTPException(404, f"static asset not allowed: {path}")
    if ".." in path or path.startswith("/") or path.startswith("\\"):
        raise HTTPException(400, "invalid path")
    full = ROOT / "static" / path
    if not full.exists():
        raise HTTPException(404, f"static asset not found: {path}")

    media = _STATIC_WHITELIST[path]
    if media in _BINARY_MIMES:
        # 字体 / 图片等二进制 · 走 FileResponse · 不 read_text 防 UTF-8 decode 崩
        # 字体加长 cache · 内容固定不变 (文件名含版本)
        return FileResponse(
            full,
            media_type=media,
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )
    try:
        content = full.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(500, f"failed to read {path}: {e}")
    return PlainTextResponse(
        content,
        media_type=media,
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@router.get("/workshop/outputs/{filename:path}")
async def serve_workshop_output(filename: str):
    if ".." in filename or filename.startswith("/") or filename.startswith("\\"):
        raise HTTPException(400, "invalid filename")
    if "\x00" in filename:
        raise HTTPException(400, "null byte in filename")

    from pathlib import PurePosixPath
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix not in _OUTPUT_MIME:
        raise HTTPException(415, f"unsupported file type: {suffix}")

    full = (ROOT / "data" / "workshop" / "outputs" / filename).resolve()
    outputs_root = (ROOT / "data" / "workshop" / "outputs").resolve()
    try:
        full.relative_to(outputs_root)
    except ValueError:
        raise HTTPException(400, "path escape blocked")

    if not full.exists() or not full.is_file():
        raise HTTPException(404, f"workshop output not found: {filename}")

    return FileResponse(
        path=str(full),
        media_type=_OUTPUT_MIME[suffix],
        headers={"Cache-Control": "public, max-age=60"},
    )


@router.get("/api/logs/tail")
async def logs_tail(
    lines: int = 200,
    trace_id: Optional[str] = None,
    since: Optional[str] = None,
    level_min: Optional[str] = None,
    module_prefix: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """卷四十六 III 补丁 5 · R1 · 拉 data/runtime/daemon.log 的最近 N 行

    Args (query string):
        lines: 默认 200 · 上限 5000
        trace_id: 过滤 trace_id (8 字符短码 · 支持前缀)
        since: ISO ts 'YYYY-MM-DDTHH:MM:SS' · 只返此后的
        level_min: DEBUG/INFO/WARNING/ERROR/CRITICAL
        module_prefix: 'opus.scheduler' / 'opus.chat' / ...

    无 auth · 内网可见即可 · 跟 /api/lifecycle_status 同安全模型
    (远程暴露走 cloudflared · 那一层有自己的 access control)
    """
    try:
        from workers.opus_logging import tail_log
        return tail_log(
            lines=lines,
            trace_id=trace_id,
            since=since,
            level_min=level_min,
            module_prefix=module_prefix,
        )
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "lines": [], "count": 0}


# ─── wish-ccd2fc5f · 屏幕录制内部端点 ───

@router.post("/_internal/screen-record")
async def screen_record(
    request: Request,
    authorization: Optional[str] = Header(None),
):
    """FFmpeg gdigrab 录屏 · 给 scripted app '屏幕录制' 用"""
    check_auth(authorization)
    import subprocess, time as _time

    try:
        body = await request.json()
    except Exception:
        body = {}

    duration = int(body.get("duration_sec", 5))
    if duration < 1 or duration > 120:
        raise HTTPException(400, "duration_sec must be 1-120")

    region = str(body.get("region", "desktop") or "desktop")
    raw_name = str(body.get("output_name", "") or "")
    output_name = raw_name if raw_name and raw_name != "screen" else f"screen-{int(_time.time())}"

    OUTPUT_DIR = ROOT / "data" / "workshop" / "outputs" / "app-8538a4d1"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    outfile = OUTPUT_DIR / f"{output_name}.mp4"

    if region == "desktop" or not region:
        ffmpeg_args = [
            "ffmpeg", "-y", "-f", "gdigrab", "-framerate", "30",
            "-i", "desktop", "-t", str(duration),
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            str(outfile)
        ]
    else:
        parts = region.replace(":", " ").replace("x", " ").split()
        if len(parts) != 4:
            raise HTTPException(400, f"invalid region format: {region}")
        x, y, w, h = parts
        ffmpeg_args = [
            "ffmpeg", "-y", "-f", "gdigrab", "-framerate", "30",
            "-offset_x", str(x), "-offset_y", str(y),
            "-video_size", f"{w}x{h}", "-i", "desktop",
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            str(outfile)
        ]

    t0 = _time.time()
    try:
        result = subprocess.run(ffmpeg_args, capture_output=True, text=True,
            timeout=duration + 30)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "FFmpeg timed out"}

    elapsed = _time.time() - t0
    if outfile.exists() and outfile.stat().st_size > 1000:
        return {
            "ok": True,
            "video_path": str(outfile.relative_to(ROOT)).replace("\\", "/"),
            "video_url": f"/workshop/outputs/app-8538a4d1/{outfile.name}",
            "duration_sec": round(elapsed, 1),
            "size_kb": round(outfile.stat().st_size / 1024, 1),
        }
    else:
        return {
            "ok": False,
            "error": "FFmpeg 完成但输出文件无效",
            "stderr": result.stderr[-500:] if result.stderr else "",
        }
