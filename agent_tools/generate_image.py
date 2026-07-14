"""
agent_tools/generate_image.py
=============================

文生图 · "daemonkey 的生图"那一档。 给一段画面描述 → 生成 PNG 落盘 → 返回相对路径,
可直接被 generate_presentation 用 `<!-- image: 路径 -->` 引进 PPT / 报告封面。

配图优先级链(BRO 2026-07-14 钉死 · 07-14 晚重排):
  ① 用户在工坊搭的【生图应用】(app)→ 直接调它(scripted 秒级/agentic)· **第一优先 · 支持并发**
  ② 配了生图模型(DAEMONKEY_IMAGE_MODEL)→ 走 OpenAI 兼容 /images/generations
  ③ 都没有 → 本工具返回"未配置" → 改用豆包网页版(browser_act 走 playbook)薅免费图
  ④ 还不行 → 保留 <!-- prompt: 画面描述 --> 占位卡 · 交回复里给 BRO

为什么 app 排第一(卷七十九续 · 脑科学 PPT 实测复盘):
  豆包网页版薅图链路极脆(弹窗挡、ProseMirror selector 超时、每轮切回聊天模式、
  收 4 张变体要 look_at 挑、harvest 目录名和 PPT embed 目录对不上)——20 张图跑了 90+ 次
  工具调用只嵌进去 2 张。 用户自建生图 app(有 key、返回真实文件路径)一步到位且可并发。

设计:
  - OpenAI 兼容 /images/generations · 覆盖绝大多数中转(OpenAI / 智谱 CogView /
    SiliconFlow / 通义 等都提供近似端点)· 用独立 env 开关避免误打到 chat 网关
  - env(未设则回退主 provider · 但 model 必须显式配 · 当"开关"):
      DAEMONKEY_IMAGE_MODEL     生图模型名(空=未配置·触发降级)· 兼容旧名 OPUS_IMAGE_MODEL
      DAEMONKEY_IMAGE_API_KEY   (回退 DAEMONKEY_API_KEY / OPUS_API_KEY)
      DAEMONKEY_IMAGE_BASE_URL  (回退 DAEMONKEY_BASE_URL / OPUS_BASE_URL)
  - 返回体同时认 b64_json 和 url 两种响应(不同家不一样)
  - TIER_CONFIRM · 真花钱 · 让 BRO 拍板(信任 flow 内自动放行)
"""
from __future__ import annotations

import base64
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from . import TIER_CONFIRM, ToolResult, ToolSpec, push_tool_progress, register_tool

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "data" / "presentations" / "generated"
HARD_MAX_N = 4


def _serve_url(p) -> str | None:
    """把落盘 Path 映射成 daemon 可服务的 URL(让聊天内联显示生成的图)· 映射不到返回 None。
    /presentations/  ← data/presentations/**   /workshop/outputs/  ← data/workshop/outputs/**"""
    try:
        rel = Path(p).resolve().relative_to(ROOT).as_posix()
    except Exception:
        return None
    if rel.startswith("data/workshop/outputs/"):
        return "/" + rel[len("data/"):]
    if rel.startswith("data/presentations/"):
        return "/presentations/" + rel[len("data/presentations/"):]
    return None
HARD_MAX_BATCH = 16          # prompts=[] 一次批量并发上限
_IMG_CONCURRENCY = 4         # 批量生图并发线程数

# agentic 生图 app(app_runner·多半驱动浏览器/豆包网页)不是并发安全的:多个同时跑会抢同一个
# 浏览器窗口 → 串味/失败。 用进程级锁把 agentic 生图串行化(跨会话·跨批次都串)· scripted/ENV
# 走 HTTP 无状态·不受此锁影响·照样满并发。 (卷七十九续二十二 · BRO 问"两实例同时生图会不会出事")
_AGENTIC_IMG_LOCK = threading.Lock()


def _env(*names: str) -> str:
    for n in names:
        v = (os.getenv(n) or "").strip()
        if v:
            return v
    return ""


def _cfg() -> dict:
    # 优先 DAEMONKEY_*(面向用户的新前缀)· 兼容 OPUS_*(历史)· 回退主 provider 的 key/base
    model = _env("DAEMONKEY_IMAGE_MODEL", "OPUS_IMAGE_MODEL")
    key = _env("DAEMONKEY_IMAGE_API_KEY", "OPUS_IMAGE_API_KEY", "DAEMONKEY_API_KEY", "OPUS_API_KEY")
    base = _env("DAEMONKEY_IMAGE_BASE_URL", "OPUS_IMAGE_BASE_URL",
                "DAEMONKEY_BASE_URL", "OPUS_BASE_URL") or None
    return {"model": model, "key": key, "base": base}


def is_configured() -> bool:
    """生图是否可用(配了模型 + key)。 供 generate_presentation 判断走 ① 还是降级。"""
    c = _cfg()
    return bool(c["model"] and c["key"])


class ImageGenUnavailable(RuntimeError):
    """生图未配置 / 依赖缺失 —— 调用方据此降级到豆包 / 占位。"""


# ─────────────────────────── ① 生图应用(工坊 app)后端 ───────────────────────────
# 优先级链第一档:用户在出品工坊自建的"生图 app"。 检测靠启发式(没有专用 tag),
# 拿回真实图片文件路径后复制进目标目录 —— 不碰浏览器、可并发、目录不会对不上。

_IMG_OUT_KEYS = ("image_url", "image_path", "image", "img_url", "img", "url")


# 视频/音频 app 也常用 b64_save/binary_save 落盘 · 名称命中这些就明确排除(别把视频 app 当生图用)
_NON_IMAGE_KW = (
    "视频", "video", "wan2", "wan ", "可灵", "kling", "vidu", "runway", "sora", "gen-3",
    "mp4", "动画", "animate", "语音", "音频", "配音", "tts", "voice", "audio",
    "mp3", "wav", "音乐", "作曲", "song", "music",
)
_IMAGE_KW = (
    "生图", "文生图", "图像生成", "出图", "配图", "画图", "绘图", "海报", "插画", "封面图",
    "text2image", "text-to-image", "txt2img", "image gen", "gpt image", "gpt-image",
    "stable diffusion", "sdxl", "flux", "midjourney", "dall", "文生图",
)
_IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def _is_image_app(app: dict) -> bool:
    """启发式判断一个 app 是否"能生图"。 先排视频/音频 app · 再看图像端口/图片关键词/落图扩展名。"""
    if not isinstance(app, dict):
        return False
    blob = ((app.get("name") or "") + " " + (app.get("description") or "")).lower()
    if any(k in blob for k in _NON_IMAGE_KW):   # 视频/音频 app 明确排除
        return False
    if any(k in blob for k in _IMAGE_KW):        # 图片关键词命中
        return True
    outs = {(o.get("name") or "").strip().lower() for o in (app.get("output_schema") or [])}
    if outs & {"image_url", "image_path", "image", "img_url"}:
        return True
    # 落图响应 + 保存文件名是图片扩展名 → 认(单看 b64_save 太宽·会误吞视频/音频)
    resp = ((app.get("exec_template") or {}).get("response") or {})
    if resp.get("kind") in ("b64_save", "binary_save"):
        fn = ((resp.get("save") or {}).get("filename") or "").lower()
        if fn.endswith(_IMG_EXTS):
            return True
    return False


def _list_image_apps() -> list:
    try:
        from workers.workshop_assets import list_apps
    except Exception:
        return []
    try:
        return [a for a in (list_apps() or []) if _is_image_app(a)]
    except Exception:
        return []


def resolve_image_app():
    """挑一个默认生图 app。 DAEMONKEY_IMAGE_APP_ID 显式指定优先;否则 scripted 优先、runs 多优先。
    没有任何生图 app 返回 None。"""
    explicit = _env("DAEMONKEY_IMAGE_APP_ID", "OPUS_IMAGE_APP_ID")
    if explicit:
        try:
            from workers.workshop_assets import load_app
            a = load_app(explicit)
            if a:
                return a
        except Exception:
            pass
    apps = _list_image_apps()
    if not apps:
        return None
    apps.sort(key=lambda a: (0 if (a.get("exec_kind") == "scripted") else 1,
                             -int(a.get("runs") or 0)))
    return apps[0]


def _app_inputs(app: dict, prompt: str, size: str) -> dict:
    """按 app 的 ui_form_schema 组装文生图输入(只填它认的字段)。"""
    fields = {(f.get("name") or "") for f in (app.get("ui_form_schema") or [])}
    inp = {"prompt": prompt}
    if "mode" in fields:
        inp["mode"] = "generations"      # 文生图(不走 edits · 那需要原图)
    if "size" in fields and size:
        inp["size"] = size
    if "n" in fields:
        inp["n"] = 1
    return inp


def _url_or_path_to_local(v: str):
    """把 app 回的图片引用(/workshop/outputs/... URL / data/... 相对 / 绝对)归一成本地 Path。"""
    v = (v or "").strip()
    if not v:
        return None
    if v.startswith("/workshop/outputs/"):
        return ROOT / "data" / "workshop" / "outputs" / v[len("/workshop/outputs/"):]
    if v.startswith("workshop/outputs/"):
        return ROOT / "data" / v
    p = Path(v)
    return p if p.is_absolute() else (ROOT / v)


_APP_IMG_RE = re.compile(
    r'/?(?:data/)?workshop/outputs/[^\s\)\]\"\'<>]+\.(?:png|jpe?g|webp)', re.IGNORECASE)


def _extract_app_image_path(res: dict):
    """从 app 运行结果里扒出图片本地路径。 scripted 用 __saved_path__;否则认 image_url;
    agentic 从回答 markdown 里 regex 抓 /workshop/outputs/*.png。"""
    outs = (res or {}).get("outputs") or {}
    cand = outs.get("__saved_path__")
    if cand:
        p = _url_or_path_to_local(cand)
        if p and p.exists():
            return p
    for k in _IMG_OUT_KEYS:
        v = outs.get(k)
        if isinstance(v, str) and v:
            p = _url_or_path_to_local(v)
            if p and p.exists():
                return p
    text = (res or {}).get("text") or ""
    m = _APP_IMG_RE.search(text)
    if m:
        p = _url_or_path_to_local(m.group(0))
        if p and p.exists():
            return p
    return None


def _copy_into(src: Path, out_dir, tag: str = "app") -> Path:
    """把生成图复制进目标目录(唯一命名·防并发覆盖)· 返回落到 out_dir 的 Path。"""
    out = Path(out_dir) if out_dir else DEFAULT_OUT
    if not out.is_absolute():
        out = ROOT / out
    out.mkdir(parents=True, exist_ok=True)
    ext = src.suffix or ".png"
    # uuid 保证并发下文件名唯一(ms+pid 在同进程同毫秒会撞·卷七十九续实测)
    dst = out / f"{tag}_{uuid.uuid4().hex[:10]}{ext}"
    shutil.copy2(src, dst)
    return dst


def generate_via_app(app: dict, prompt: str, out_dir=None, size: str = "1792x1024",
                     art_boost: bool = True):
    """用工坊生图 app 出一张图 → 复制进 out_dir → 返回 Path。 失败/没配 key/没拿到图 返回 None。
    在 worker 线程里"跑完立即复制",复制窗口在同线程内微秒级 · 并发下不会拿错别人的图。"""
    prompt = _enhance_prompt(prompt, art_boost)
    if not prompt or not isinstance(app, dict):
        return None
    try:
        from daemon_runtime import RUNTIME
    except Exception:
        RUNTIME = None
    inputs = _app_inputs(app, prompt, size)
    exec_kind = app.get("exec_kind") or "agentic"
    try:
        if exec_kind == "scripted":
            from workers.http_executor import run_scripted_app
            res = run_scripted_app(app=app, inputs=inputs, runtime=RUNTIME)   # 无状态·满并发
        else:
            from workers.app_runner import run_app as _run_app
            # agentic 多半驱动浏览器·非并发安全 → 进程级锁串行化(防两实例/多线程抢同一浏览器)
            with _AGENTIC_IMG_LOCK:
                res = _run_app(app=app, inputs=inputs, runtime=RUNTIME, max_iterations=6)
    except Exception:
        return None
    if not res or not res.get("ok"):
        return None
    src = _extract_app_image_path(res)
    if not src:
        return None
    try:
        return _copy_into(src, out_dir, tag="app")
    except Exception:
        return None


def image_available() -> bool:
    """有没有可用的生图后端(app 或 ENV 模型)。 供自动配图判断走①/②还是降级。"""
    if resolve_image_app() is not None:
        return True
    return is_configured()


# 艺术方向增强:提示词没写光影/构图/风格时,补一段"电影级布光 + 明暗对比 + 讲究构图"的高级方向。
# 命中任一关键词(说明 LLM 已自带艺术方向)→ 原样尊重,不叠加。
_ART_KEYWORDS = (
    "光", "影", "对比", "contrast", "chiaroscuro", "cinematic", "lighting", "景深", "bokeh",
    "构图", "composition", "质感", "风格", "style", "色调", "grade", "8k", "photoreal",
    "rim light", "backlit", "氛围",
)
_ART_SUFFIX = (
    "电影级布光,强烈明暗对比(chiaroscuro),边缘轮廓光/逆光氛围,高级克制配色与统一色调,"
    "构图讲究、遵循三分法并留出干净负空间以便叠加标题文字,浅景深、细腻质感,专业摄影/精修水准,"
    "画面内不出现任何文字、水印或 logo"
)


def _enhance_prompt(prompt: str, boost: bool = True) -> str:
    """给"白开水"提示词补艺术方向 · 已自带光影/构图/风格的原样尊重。"""
    p = (prompt or "").strip()
    if not boost or not p:
        return p
    low = p.lower()
    if any(k.lower() in low for k in _ART_KEYWORDS):
        return p
    return f"{p}。 画面要求:{_ART_SUFFIX}"


def generate_images(prompt: str, out_dir=None, size: str = "1024x1024", n: int = 1,
                    art_boost: bool = True):
    """核心:生成 n 张图落盘 · 返回 [Path,...]。 未配置抛 ImageGenUnavailable · API/落盘失败抛 RuntimeError。"""
    prompt = _enhance_prompt(prompt, art_boost)
    if not prompt:
        raise RuntimeError("empty prompt")
    cfg = _cfg()
    if not cfg["model"]:
        raise ImageGenUnavailable(_NOT_CONFIGURED)
    if not cfg["key"]:
        raise ImageGenUnavailable("生图缺 API key(OPUS_IMAGE_API_KEY / OPUS_API_KEY 都空)。")
    try:
        from openai import OpenAI
    except ImportError as e:
        raise ImageGenUnavailable("openai 包未安装·先装依赖。") from e

    n = max(1, min(int(n or 1), HARD_MAX_N))
    out = Path(out_dir) if out_dir else DEFAULT_OUT
    if not out.is_absolute():
        out = ROOT / out
    out.mkdir(parents=True, exist_ok=True)

    client = OpenAI(api_key=cfg["key"], base_url=cfg["base"], timeout=120.0)
    push_tool_progress("生成配图", f"{cfg['model']} · {size}")

    def _call(with_size: bool):
        kw = {"model": cfg["model"], "prompt": prompt, "n": n}
        if with_size and size:
            kw["size"] = size
        return client.images.generate(**kw)

    try:
        resp = _call(with_size=True)
    except Exception as e:                       # size 不被支持等 → 去 size 再试
        try:
            resp = _call(with_size=False)
        except Exception as e2:
            raise RuntimeError(f"生图失败: {type(e2).__name__}: {str(e2)[:200]}"
                               f"(首次带 size 也失败: {type(e).__name__})") from e2

    data = getattr(resp, "data", None) or []
    if not data:
        raise RuntimeError("生图返回为空(检查模型名 / 额度)。")

    stamp = uuid.uuid4().hex[:8]          # 并发唯一(旧的 int(time.time()) 秒级会撞)
    base_name = _slug(prompt)
    saved = []
    for i, item in enumerate(data, 1):
        dst = out / f"{base_name}_{stamp}_{i}.png"
        try:
            if _save_item(item, dst, client):
                saved.append(dst)
        except Exception:
            pass
    if not saved:
        raise RuntimeError("生图成功但落盘失败(响应既无 b64_json 也无可下载 url)。")
    return saved


def generate_one(prompt: str, out_dir=None, size: str = "1024x1024", art_boost: bool = True):
    """便捷:生成 1 张 · 成功返回 Path · 未配置/失败返回 None(不抛·给自动配图静默降级)。"""
    try:
        paths = generate_images(prompt, out_dir=out_dir, size=size, n=1, art_boost=art_boost)
        return paths[0] if paths else None
    except Exception:
        return None


_NOT_CONFIGURED = (
    "生图没有可用后端(没找到生图应用 · 也没配 DAEMONKEY_IMAGE_MODEL)。 按配图优先级链降级:\n"
    "  ① 最推荐:在出品工坊搭一个【生图应用】(填好 API key)· 之后本工具/PPT 自动配图会优先调它;\n"
    "  ③ 用 browser_act 走豆包网页版 playbook 薅免费生图,落到 embed_image_dir 再引;\n"
    "  ④ 或直接在页里写 <!-- layout: image --><!-- prompt: 画面描述 --> 保留提示词占位卡。\n"
    "(或在 .env 配 DAEMONKEY_IMAGE_MODEL / DAEMONKEY_IMAGE_API_KEY / DAEMONKEY_IMAGE_BASE_URL 开②。)"
)


def _slug(text: str) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "_", (text or "img").strip())[:24].strip("_")
    return s or "img"


def _save_item(item, dst: Path, client) -> bool:
    """一个 image item 落盘 · 认 b64_json / url 两种。"""
    b64 = getattr(item, "b64_json", None) or (item.get("b64_json") if isinstance(item, dict) else None)
    if b64:
        dst.write_bytes(base64.b64decode(b64))
        return True
    url = getattr(item, "url", None) or (item.get("url") if isinstance(item, dict) else None)
    if url:
        import httpx
        r = httpx.get(url, timeout=60.0, follow_redirects=True)
        if r.status_code == 200 and r.content:
            dst.write_bytes(r.content)
            return True
    return False


def _summarize(args: dict) -> str:
    raw = args.get("prompts")
    if isinstance(raw, list) and any(str(x or "").strip() for x in raw):
        k = len([x for x in raw if str(x or "").strip()])
        first = next((str(x).strip() for x in raw if str(x or "").strip()), "")
        return f"generate_image  批量并发 {k} 张  首张={first[:44]!r}"
    p = (args.get("prompt") or "").strip()
    n = args.get("n") or 1
    return f"generate_image  n={n}  prompt={p[:60]!r}"


def _gen_one_backend(prompt: str, app, env_ok: bool, out_dir, size: str, art_boost: bool):
    """单张:生图应用优先 → ENV 模型兜底 · 返回 Path 或 None(不抛)。 给批量并发用。"""
    prompt = (prompt or "").strip()
    if not prompt:
        return None
    if app is not None:
        p = generate_via_app(app, prompt, out_dir=out_dir, size=size, art_boost=art_boost)
        if p is not None:
            return p
    if env_ok:
        try:
            return generate_one(prompt, out_dir=out_dir, size=size, art_boost=art_boost)
        except Exception:
            return None
    return None


def _run_batch(prompts: list, size: str, art_boost: bool, out_dir) -> ToolResult:
    """一次并发出多张【不同】图 · 治"LLM 发多个 generate_image 被 tool loop 串行跑"(卷七十九续二十)。"""
    prompts = prompts[:HARD_MAX_BATCH]
    app = resolve_image_app()
    env_ok = False
    try:
        env_ok = is_configured()
    except Exception:
        env_ok = False
    if app is None and not env_ok:
        return ToolResult(ok=False, output="", error=(
            "没找到生图后端:工坊没【生图应用】、也没配 DAEMONKEY_IMAGE_MODEL。\n"
            "去工坊搭个生图应用(填好 key · 最推荐 · 之后自动优先用),或配 .env 的 "
            "DAEMONKEY_IMAGE_MODEL,或用 browser_act 跑豆包网页版 playbook 补图。"))
    used = (f"生图应用「{app.get('name')}」" if app is not None else f"模型 {_cfg()['model']}")
    try:
        from . import push_tool_progress as _pp
    except Exception:
        def _pp(step, msg=""):
            return None

    total = len(prompts)
    _pp("🖼 批量生图", f"0/{total} · {used} · 并发中…")
    results: dict[int, object] = {}
    done = 0
    workers = max(1, min(total, _IMG_CONCURRENCY))
    if workers == 1:
        for i, pr in enumerate(prompts):
            results[i] = _gen_one_backend(pr, app, env_ok, out_dir, size, art_boost)
            done += 1
            _pp("🖼 批量生图", f"{done}/{total} 完成")
    else:
        import concurrent.futures as _cf
        with _cf.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="gi-batch") as pool:
            fut2i = {pool.submit(_gen_one_backend, prompts[i], app, env_ok, out_dir, size, art_boost): i
                     for i in range(total)}
            for fut in _cf.as_completed(fut2i):
                i = fut2i[fut]
                try:
                    results[i] = fut.result()
                except Exception:
                    results[i] = None
                done += 1
                _pp("🖼 批量生图", f"{done}/{total} 完成")

    ok_ct = 0
    lines = [f"generate_image(批量) · 请求 {total} 张 · 并发 · {used}", ""]
    for i, pr in enumerate(prompts):
        p = results.get(i)
        if p is None:
            lines.append(f"  [{i + 1}] ✗ 失败 · {pr[:26]}…")
            continue
        ok_ct += 1
        try:
            rel = p.relative_to(ROOT).as_posix()
        except ValueError:
            rel = p.as_posix()
        lines.append(f"  [{i + 1}] {rel}")
    lines += ["",
              f"成功 {ok_ct}/{total} · 路径按你给的 prompts 顺序一一对应。",
              "用法:每页 <!-- image: 对应相对路径 --> 引入。"]
    # 让聊天内联显示这些图(marker 由 tool_loop 抽走 · 不进 LLM 上下文/preview)
    for i in sorted(results):
        p = results.get(i)
        if p is not None:
            u = _serve_url(p)
            if u:
                lines.append(f"[[DK-IMG]]{u}")
    return ToolResult(ok=ok_ct > 0, output="\n".join(lines),
                      error=None if ok_ct > 0 else "批量生图全部失败(见上)")


def _run(args: dict) -> ToolResult:
    # 批量:prompts=[...] 多张不同图一次【并发】出(别再一条条单独调 generate_image · 那会被串行跑)
    raw = args.get("prompts")
    if isinstance(raw, list):
        batch = [str(x).strip() for x in raw if str(x or "").strip()]
        if batch:
            size = (args.get("size") or "1024x1024").strip()
            art_boost = bool(args.get("art_boost", True))
            return _run_batch(batch, size, art_boost, args.get("out_dir"))

    prompt = (args.get("prompt") or "").strip()
    if not prompt:
        return ToolResult(ok=False, output="", error="empty prompt: 需要 prompt(单张)或 prompts[](批量并发)")

    n = max(1, min(int(args.get("n") or 1), HARD_MAX_N))
    size = (args.get("size") or "1024x1024").strip()
    art_boost = bool(args.get("art_boost", True))
    out_dir = args.get("out_dir")

    saved = []
    used = ""
    # ① 生图应用优先(用户在工坊自建的 · 支持 · 一步到位)
    app = resolve_image_app()
    if app is not None:
        for _ in range(n):
            p = generate_via_app(app, prompt, out_dir=out_dir, size=size, art_boost=art_boost)
            if p is not None:
                saved.append(p)
        if saved:
            used = f"生图应用「{app.get('name')}」"
    # ② ENV 生图模型兜底
    if not saved:
        try:
            saved = generate_images(prompt, out_dir=out_dir, size=size, n=n, art_boost=art_boost)
            used = f"模型 {_cfg()['model']}"
        except ImageGenUnavailable as e:
            extra = (f"(试了生图应用「{app.get('name')}」没成功 · 多半没配 key 或返回失败)\n"
                     if app is not None else "")
            return ToolResult(ok=False, output="", error=extra + str(e))
        except Exception as e:
            return ToolResult(ok=False, output="", error=f"{type(e).__name__}: {str(e)[:220]}")

    lines = [f"generate_image OK · {len(saved)} 张 · {used}", ""]
    for p in saved:
        try:
            rel = p.relative_to(ROOT).as_posix()
        except ValueError:
            rel = p.as_posix()
        lines.append(f"  {rel}")
    lines += [
        "",
        "用法:在 PPT 页里用 <!-- image: 上面的相对路径 --> 引入,或 ![](相对路径)。",
        "封面主视觉建议单独生成一张 16:9(size=1792x1024)。",
    ]
    # 让聊天内联显示这些图(marker 由 tool_loop 抽走 · 不进 LLM 上下文/preview)
    for p in saved:
        u = _serve_url(p)
        if u:
            lines.append(f"[[DK-IMG]]{u}")
    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="generate_image",
    description=(
        "文生图 · 给画面描述生成 PNG 落盘 · 用于 PPT / 报告的配图与封面。\n"
        "⚡ **要出多张图,务必一次调用、用 `prompts:[...]` 批量传**(内部并发出图·数倍快)。\n"
        "   ❌ 别为每张图各发一个 generate_image 调用——多个工具调用会被【串行】执行,慢到爆(BRO 实测第二轮补图卡了很久)。\n"
        "本工具会**自动按优先级选后端**,你只管给好提示词即可:\n"
        "  ① 用户在工坊搭的【生图应用】——有就自动优先调它(一步到位·可并发·最推荐);\n"
        "  ② 配了 DAEMONKEY_IMAGE_MODEL 的生图模型 —— 次选;\n"
        "  ③ 都没有(本工具报'未配置')→ 用 browser_act 走豆包网页版 playbook 薅免费生图;\n"
        "  ④ 还不行 → 页里写 <!-- layout: image --><!-- prompt: 画面描述 --> 留提示词占位卡。\n\n"
        "**怎么接进 PPT**:\n"
        "  - out_dir 传 generate_presentation 的 embed_image_dir(或默认 data/presentations/generated);\n"
        "  - 拿到相对路径后,在页里 <!-- image: 路径 --> 引入;封面单独生 16:9(size=1792x1024)。\n\n"
        "**提示词写法(要有艺术感 · 按这个配方写)**:\n"
        "  主体 + 场景 + 【光线】 + 【明暗对比】 + 【构图】 + 【镜头/景深】 + 【色调/风格】 + 情绪。\n"
        "  - 光线/明暗:电影级布光、强烈明暗对比(chiaroscuro)、逆光/轮廓光、黄金时刻、体积光;\n"
        "  - 构图:三分法、非对称、大量负空间(**给标题留干净落字区**)、引导线、前景框景;\n"
        "  - 镜头:浅景深虚化、广角张力、微距质感;色调:统一色调/高级灰/克制配色;\n"
        "  - ⛔ **铁律:画面里绝不要放任何文字/标签/标题/数字/数据/logo**(生图模型写字会糊,"
        "而且排版填充/裁切会把边缘的字砍掉——PPT 里必翻车)。 提示词里别写\"标注XX/写字XX/带文字\"。\n"
        "    文字一律交给 PPT 层叠;需要带标签的示意(三角定位/象限/流程)→ 改用 flow/chart/pillars 版式,别让生图画带字的图;\n"
        "  例:'深夜暖光工作室,一位创作者侧影在剪辑,强烈明暗对比、逆光勾边,浅景深,画面右侧大面积暗部留白放标题,电影感冷暖对比色调'。\n"
        "  本工具会对'白开水'描述自动补一段艺术方向(art_boost,默认开);你已写光影/构图/风格就原样尊重。"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "单张画面描述(配图提示词)· 按上面配方写:光影/明暗对比/构图/镜头/色调"},
            "prompts": {"type": "array", "items": {"type": "string"},
                        "description": f"【批量·首选】多张【不同】图的提示词数组(≤{HARD_MAX_BATCH})· 一次并发出图 · 结果按顺序一一对应。要多张图时用它,别发多个调用"},
            "n": {"type": "integer", "description": f"同一 prompt 出几张变体 1-{HARD_MAX_N}(默认 1)· 仅对单个 prompt 生效"},
            "size": {"type": "string", "description": "尺寸,如 1024x1024 / 1792x1024(16:9 封面)。默认 1024x1024"},
            "out_dir": {"type": "string", "description": "落盘目录(相对工程根即可)。默认 data/presentations/generated"},
            "art_boost": {"type": "boolean", "description": "自动补艺术方向(电影布光/明暗对比/讲究构图)· 默认 True · 已自带光影描述则不叠加"},
        },
        "required": [],
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
