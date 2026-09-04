"""
agent_tools/generate_presentation.py
=====================================

Daemonkey 用自然语言产出【原生可编辑、有高级感、可切换设计风格】的 .pptx 演示稿。

镜像 generate_report(docx)的定位与用法:分页 markdown → 精排 PPTX · 落 data/presentations/ ·
BRO 在 WebUI 下载或直接开 PowerPoint/WPS/Keynote,每个元素都能改(不是一页一张图)。

设计取向(研究 anthropics/skills·pptx / ppt-master / slide-kit 后定):原生 DrawingML 形状 +
多"设计风格"(art direction · 不只是换配色)+ CRAP 排版纪律 + 出片前 QA 关。

档位:CONFIRM —— 产物类 · BRO 应看见"Daemonkey 要给我做一份《X》演示稿"这一步。误生成也只是
多个落盘文件,不破坏任何东西。

配图:先用 web_search_image 把图搜进 embed_image_dir,再在页里用相对路径 ![](x.png) 引用。
"""
from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool

_ROOT = Path(__file__).resolve().parent.parent
_DECK_DIR = _ROOT / "data" / "presentations"
_UNSAFE = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def _safe_filename(title: str) -> str:
    cleaned = _UNSAFE.sub("_", (title or "").strip())
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = cleaned.strip("._-")
    return cleaned[:80] or "deck"


def _summarize(args: dict) -> str:
    title = (args.get("title") or "未命名演示稿").strip()
    style = (args.get("style") or "light_studio").lower()
    accent = (args.get("accent") or "").strip()
    mood = (args.get("mood") or "").strip()
    tail = style + (f"/{accent}" if accent else "") + (f"/{mood}" if mood else "")
    body = args.get("body") or ""
    pages = body.count("\n---") + (1 if body.strip() else 0)
    return f"生成演示稿《{title}》 · {tail} · 约 {pages} 页"


# 自动配图并发上限 · 生图 app(gpt-image 类)单张 2-5 分钟 · 并发能把 20 张从"逐张串行"提到数倍
_IMG_CONCURRENCY = 4


def _autofill_images(slides, here_dir, auto_image: bool, cover: dict | None = None) -> str:
    """给"有配图提示词、还没图"的页(含封面)自动补图。
    后端优先级 ①用户生图应用(app) → ②ENV 生图模型 · 都没有则留占位(交回复处理豆包/占位卡)。
    多处配图【并发】出图(ThreadPoolExecutor)· 就地写 slide.image / cover['image']。
    返回一段状态说明(进 tool 输出)。"""
    cover_needs = bool(cover and cover.get("prompt") and not cover.get("image"))
    targets = [s for s in slides
               if getattr(s, "image_prompt", None) and not getattr(s, "image", None)]
    total = len(targets) + (1 if cover_needs else 0)
    if total == 0:
        return ""
    if not auto_image:
        return f"  · {total} 处配图(含封面)保留了提示词占位(auto_image=false)"
    try:
        from . import generate_image as gi
    except Exception:
        gi = None
    if gi is None:
        return f"  · {total} 处配图待补:生图后端不可用(generate_image 导入失败)"

    # 择一后端:生图应用优先 → ENV 模型兜底
    app = None
    try:
        app = gi.resolve_image_app()
    except Exception:
        app = None
    env_ok = False
    try:
        env_ok = gi.is_configured()
    except Exception:
        env_ok = False
    if app is None and not env_ok:
        return (f"  · {total} 处配图待补(含封面):① 没找到生图应用、也没配 DAEMONKEY_IMAGE_MODEL"
                f" → 封面退回渐变款、内页渲「配图提示词」占位卡。\n"
                f"    要自动出图:在工坊搭个【生图应用】(填好 key · 最推荐 · 之后自动优先用),"
                f"或配 .env 的 DAEMONKEY_IMAGE_MODEL,或用 browser_act 跑豆包 playbook 补图后重生成。")

    backend = (f"生图应用「{app.get('name')}」" if app is not None
               else f"生图模型 {gi._cfg().get('model')}")
    here = Path(here_dir)
    here.mkdir(parents=True, exist_ok=True)

    # 任务列表:(kind, obj, prompt) · 封面用 16:9
    jobs = []
    if cover_needs:
        jobs.append(("cover", cover, cover["prompt"]))
    for s in targets:
        jobs.append(("slide", s, s.image_prompt))

    def _gen_one(prompt: str):
        """单张出图:app 优先 · app 失败且 ENV 可用则兜底。 返回 Path 或 None。"""
        if app is not None:
            p = gi.generate_via_app(app, prompt, out_dir=here, size="1792x1024")
            if p is not None:
                return p
        if env_ok:
            try:
                return gi.generate_one(prompt, out_dir=here, size="1792x1024")
            except Exception:
                return None
        return None

    # 卷七十九续十八 · 批生图进度推到 SSE(治"卡很久·不知在干嘛")· 从主线程推
    # (push_tool_progress 用 ContextVar · 进不了 ThreadPoolExecutor 工作线程 · 只能主线程按完成数推)
    try:
        from . import push_tool_progress as _pp
    except Exception:
        def _pp(step, msg=""):
            return None
    _pp("🖼 配图", f"0/{total} · {backend} · 并发出图中…")

    results: dict[int, object] = {}
    done = 0
    workers = max(1, min(len(jobs), _IMG_CONCURRENCY))
    if workers == 1:
        for i, (_k, _o, prompt) in enumerate(jobs):
            results[i] = _gen_one(prompt)
            done += 1
            _pp("🖼 配图", f"{done}/{total} 完成")
    else:
        import concurrent.futures as _cf
        with _cf.ThreadPoolExecutor(max_workers=workers,
                                    thread_name_prefix="ppt-img") as pool:
            fut2i = {pool.submit(_gen_one, jobs[i][2]): i for i in range(len(jobs))}
            for fut in _cf.as_completed(fut2i):
                i = fut2i[fut]
                try:
                    results[i] = fut.result()
                except Exception:
                    results[i] = None
                done += 1
                _pp("🖼 配图", f"{done}/{total} 完成")

    filled = 0
    for i, (kind, obj, _prompt) in enumerate(jobs):
        p = results.get(i)
        if p is None:
            continue
        if kind == "cover":
            obj["image"] = p.name
        else:
            obj.image = p.name                  # 相对 here_dir 解析
        filled += 1

    left = total - filled
    msg = f"  · 自动配图({backend} · 并发 {workers}):{filled}/{total} 处已出图(含封面)"
    if left:
        msg += f" · {left} 处没成 → 留占位(检查 app 的 key/额度 · 或跑豆包 playbook 补)"
    return msg


def _run(args: dict) -> ToolResult:
    from ._hotpath_guard import require_scenario
    blocked = require_scenario("presentation")
    if blocked:
        return ToolResult(ok=False, output="", error=blocked)

    title = (args.get("title") or "").strip()
    if not title:
        return ToolResult(ok=False, output="", error="title 必填 · 演示稿标题 + 落盘文件名来源")

    body = args.get("body") or ""
    grabbed = False
    if not body.strip():
        try:
            from . import current_turn_text
            t = (current_turn_text() or "").strip()
        except Exception:
            t = ""
        if t:
            body, grabbed = t, True
    if not body.strip():
        return ToolResult(
            ok=False, output="",
            error=(
                "没拿到分页 markdown · 两种给法二选一:\n"
                "  ① 把完整分页 markdown 放进 body(一步到位);\n"
                "  ② 先在本条回复正文里写完整分页 markdown · 再调本工具【不带 body】· 自动抓。\n"
                "格式:一行 `---` 分页 · 每页可带 <!-- layout: cover|section|bullets|image|"
                "statement|two_col|metrics|sources|closing -->。"
            ),
        )
    # 卷七十九续十七 · 两步法兜底加固:current_turn_text 抓到的是"这轮回复文字"·
    # 若里面根本没有分页结构(没 --- 分页、没 <!-- layout、没多个 #),几乎肯定是
    # 状态汇报(如"4 张图全到手·现在出 PPT!")而非幻灯正文 → 别静默出个 1 页废稿·直接挡回去。
    if grabbed:
        structured = ("<!-- layout" in body) or ("\n---" in body) or (body.count("#") >= 2)
        if not structured:
            return ToolResult(
                ok=False, output="",
                error=(
                    "两步法(不带 body)只抓到了你这轮回复的文字,里面没有分页 markdown"
                    "(没 `---` 分页、没 `<!-- layout: ... -->`、也没多个 `#`)。\n"
                    "多半是你还没把幻灯正文写进这条回复就调了我(比如刚汇报完'图生成好了')。\n"
                    "两种给法二选一:\n"
                    "  ① 直接把完整分页 markdown 传进 body 参数(推荐 · 最稳 · 别再靠自动抓);\n"
                    "  ② 先在这条回复正文里写完整分页 markdown(用 `---` 分页 + <!-- layout -->),再调我【不带 body】。"
                ),
            )

    style = (args.get("style") or "light_studio").lower().strip()
    accent = (args.get("accent") or "").strip() or None
    mood = (args.get("mood") or "").strip() or None
    spec = args.get("style_spec")
    if isinstance(spec, str):
        try:
            spec = json.loads(spec)
        except Exception:
            spec = None
    if not isinstance(spec, dict):
        spec = None
    include_cover = bool(args.get("include_cover", True))
    auto_image = bool(args.get("auto_image", True))

    cover = None
    if include_cover:
        cover = {"title": title}
        for k in ("subtitle", "audience", "note", "footer"):
            v = args.get(k)
            if v:
                cover[k] = str(v).strip()
        if args.get("cover_image"):
            cover["image"] = str(args["cover_image"]).strip()
        if args.get("cover_prompt"):
            cover["prompt"] = str(args["cover_prompt"]).strip()
        cl = (args.get("cover_layout") or "auto").strip().lower()
        if cl in ("auto", "full", "hero"):
            cover["cover_layout"] = cl

    safe = _safe_filename(title)
    from workers.output_versions import publish, safe_family, staged_path
    family = safe_family(safe)
    out_path = staged_path(_DECK_DIR, family, ".pptx")

    embed_arg = args.get("embed_image_dir")
    from workers.output_sinks import coerce_out_dir
    here_dir = coerce_out_dir(embed_arg, _DECK_DIR / "_assets" / safe, _ROOT)

    try:
        from slides_engine import audit_deck, list_styles, parse_deck, render_deck, resolve_style
    except ImportError as e:
        return ToolResult(ok=False, output="", error=f"slides_engine / python-pptx 缺失: {e}")

    # 一套设计标准 + 自然语言调参:基底 + accent(主色)+ mood(气质)+ style_spec(LLM 作曲的 token)
    deck_style = resolve_style(style, accent=accent, mood=mood, spec=spec)

    try:
        slides = parse_deck(body)
        img_note = _autofill_images(slides, here_dir, auto_image, cover=cover)   # 自动配图(先于渲染)
        warnings = audit_deck(slides, here_dir, cover=cover)
        try:
            from . import push_tool_progress as _pp
            _pp("📝 排版渲染", f"{len(slides)} 页 · 生成 PPTX 中…")
        except Exception:
            pass
        wip = render_deck(slides, out_path, cover=cover, style=deck_style, here_dir=here_dir)
        final_path, ver = publish(wip, _DECK_DIR, family, ".pptx")
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"渲染失败: {type(e).__name__}: {e}")

    if not final_path.exists():
        return ToolResult(ok=False, output="", error=f"渲染器称写入 {final_path} · 但磁盘上找不到")

    style_label = (style + (f" · 主色 {accent}" if accent else "") + (f" · {mood}" if mood else "")
                   + (" · 自定义 token" if spec else ""))

    # 同步 markdown 源(可追溯 + 重渲染 · 宪法第 5 条)
    md_path = final_path.with_suffix(".md")
    try:
        fm = ["---", f"title: {title}", f"style: {style}"]
        if accent:
            fm.append(f"accent: {accent}")
        if mood:
            fm.append(f"mood: {mood}")
        fm += [f"generated_at: {datetime.datetime.now().isoformat(timespec='seconds')}",
               f"pptx: {final_path.name}", "---"]
        md_path.write_text("\n".join(fm) + "\n\n" + body, encoding="utf-8")
    except Exception:
        pass

    size_kb = final_path.stat().st_size / 1024
    rel = final_path.relative_to(_ROOT) if _ROOT in final_path.parents else final_path
    lines = [
        f"已生成演示稿 · {final_path.name} · V{ver}",
        f"  路径: {rel}",
        f"  页数: {len(slides)} · 风格: {style_label} · 大小: {size_kb:.1f} KB",
    ]
    if grabbed:
        lines.append("  (正文来自本轮回复 · 两步法兜底)")
    if img_note:
        lines.append(img_note)
    try:
        lines.append(f"  可选风格: {', '.join(list_styles())}")
    except Exception:
        pass
    if warnings:
        lines.append("  ⚠ QA 提醒(可改进 · 不阻断):")
        for w in warnings[:6]:
            lines.append(f"    - {w}")
    lines.append("")
    lines.append("原生可编辑 · 点结果里的「用对应软件打开」直接进 PowerPoint/WPS · 也可直接开文件改。")
    # 可打开产物 marker → 前端渲"用本机软件打开"按钮 (tool_loop 抽走·不进 LLM 内容)
    try:
        lines.append(f"[[DK-OPEN]]{final_path.relative_to(_ROOT).as_posix()}")
    except ValueError:
        lines.append(f"[[DK-OPEN]]{final_path.as_posix()}")
    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="generate_presentation",
    description=(
        "从零新建可编辑 .pptx，落 data/presentations/。六套风格只在新建时用。"
        "已有稿加页走 extend_office，圈字 revise_office，加图 illustrate_office。禁止对用户上传的成品整份重出。"
        "除非他说「直接做」或只有三五页，先出施工单再调本工具。"
        "版式写法 → read_scenario(name='presentation')。CONFIRM：产物要他点头。"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "演示稿标题 · 封面 + 文件名 · 必填"},
            "body": {
                "type": "string",
                "description": "分页 markdown。`---` 分页。不传则抓本条回复。版式见 read_scenario('presentation')。",
            },
            "style": {
                "type": "string",
                "enum": ["light_studio", "dark_keynote", "editorial", "glass", "neon_glitch", "sketch"],
                "description": "基底风格，见 enum。含义见 read_scenario('presentation')。",
            },
            "accent": {
                "type": "string",
                "description": "主色：俗名或 hex。不传用基底色。",
            },
            "mood": {
                "type": "string",
                "enum": ["calm", "vivid", "sharp"],
                "description": "气质，见 enum。也认中文沉稳/活泼/锐利。",
            },
            "style_spec": {
                "type": "object",
                "description": (
                    "高级：现成 style/accent/mood 盖不住时自己产一组设计 token 叠加。"
                    "可用字段与示例 → read_scenario(name='presentation')。"
                ),
            },
            "subtitle": {"type": "string", "description": "封面副标题 · 可选"},
            "audience": {"type": "string", "description": "封面眉标/面向 · 可选"},
            "note": {"type": "string", "description": "封面备注 · 可选"},
            "footer": {"type": "string", "description": "页脚文字 · 默认按风格 · 可选"},
            "include_cover": {"type": "boolean", "description": "是否生成 meta 封面页 · 默认 True"},
            "cover_image": {
                "type": "string",
                "description": "封面大图路径(相对 embed_image_dir)· 传了做满版/分栏封面 · 不传走渐变封面",
            },
            "cover_prompt": {
                "type": "string",
                "description": "封面配图提示词。画面里不要有字。细则见 read_scenario('presentation')。",
            },
            "cover_layout": {
                "type": "string",
                "enum": ["auto", "full", "hero"],
                "description": "封面版式(有封面图时)· full=满版大图铺底+遮罩+白字(默认·最有冲击力)/ hero=左字右图分栏 / auto",
            },
            "embed_image_dir": {
                "type": "string",
                "description": "解析页内相对图片路径的基准目录 · 默认 data/presentations/_assets/<safe_title>/",
            },
            "auto_image": {
                "type": "boolean",
                "description": "有 prompt 无图时是否自动生图。默认 True；False 只留占位卡。",
            },
        },
        "required": ["title"],
        "additionalProperties": False,
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
