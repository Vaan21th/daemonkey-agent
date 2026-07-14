"""
agent_tools/generate_presentation.py
=====================================

OPUS 用自然语言产出【原生可编辑、有高级感、可切换设计风格】的 .pptx 演示稿。

镜像 generate_report(docx)的定位与用法:分页 markdown → 精排 PPTX · 落 data/presentations/ ·
BRO 在 WebUI 下载或直接开 PowerPoint/WPS/Keynote,每个元素都能改(不是一页一张图)。

设计取向(研究 anthropics/skills·pptx / ppt-master / slide-kit 后定):原生 DrawingML 形状 +
多"设计风格"(art direction · 不只是换配色)+ CRAP 排版纪律 + 出片前 QA 关。

档位:CONFIRM —— 产物类 · BRO 应看见"OPUS 要给我做一份《X》演示稿"这一步。误生成也只是
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
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    out_path = _DECK_DIR / f"{safe}__{ts}.pptx"

    embed_arg = args.get("embed_image_dir")
    here_dir = Path(str(embed_arg)).resolve() if embed_arg else (_DECK_DIR / "_assets" / safe)

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
        final_path = render_deck(slides, out_path, cover=cover, style=deck_style, here_dir=here_dir)
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
        f"已生成演示稿 · {final_path.name}",
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
        "把【分页 markdown】一键渲染成精排、原生可编辑的 .pptx 演示稿 · 多设计风格 · 落 data/presentations/。\n"
        "适合:提案 / 汇报 / 发布会 / 课件 / 短视频脚本配图稿 —— 任何要交付幻灯片的场景。\n\n"
        "**用法两步(除非用户明说'直接做'或就三五页的小稿,否则别跳第一步)**:\n"
        "  ① 施工单:先在回复里给一张【施工单】让用户过目 —— 含 标题 / 受众 / 风格 / **配图计划(哪几页配图·放哪·图哪来)** / 逐页(版式 + 要点)。\n"
        "     交付前**以'总监'视角自审一遍**(等于交付前的审稿关):配图够不够?版式选对没(时间线走了 flow 吗、数据走了 chart 吗)?"
        "受众/口吻合不合?哪页太平?—— 有问题当场在施工单里改好再给用户。 等用户说'就这样/做'或改完才进第二步。\n"
        "  ② 生成:确认后再调本工具(长稿可把最终分页 markdown 写进回复正文 · 再调本工具只给 title 自动抓)。\n\n"
        "**★ 配图是硬要求(你最常犯的病 = 交一份全文字白板稿 · 特别平)**:\n"
        "  · 封面几乎必给主视觉:传 cover_prompt(哪怕本机没配生图模型,也会渲成好看的「配图提示词」占位卡,用户能一键补图)。\n"
        "  · 正文别连续多页纯文字:每 3~4 页至少一个视觉承载 —— 配图页 image / 图表 chart / 图标磁贴 pillars 三选一。\n"
        "  · 图哪来(按序降级):① generate_image 生图 → <!-- image: 相对路径 -->;② 没配就 browser_act 跑豆包网页版薅图;"
        "③ 都不行 → <!-- layout: image --><!-- prompt: 画面描述 --> 渲成提示词占位卡(把图交给用户后补)。\n"
        "  · 提示词按'主体+光线+明暗对比+构图+镜头+色调'写 · 暗部/一侧留干净负空间给标题。\n"
        "  · ⛔ **生图里绝不要放文字/标签/标题/数字**(会糊 + 排版裁切会砍掉·必翻车)· 图只做纯视觉,文字全交给 PPT 层。\n"
        "  · **大图视觉页先想清楚文字怎么落**:\n"
        "     - 要在图上压标题/金句 → 用 cover(cover_layout=full/hero)或 statement,引擎自动叠真文字 + 压暗遮罩(可读);\n"
        "     - 图只是配图 → image 版式,图保持干净、标题在页眉、配 <!-- caption: 图注 -->;\n"
        "     - **带标签的概念(如'效率/成长/关系'三角、四象限、流程)→ 用 flow/chart/pillars 版式(标签是引擎画的真文字)**,别让生图画带字的图再被裁。\n\n"
        "**★ 每页先选版式(别一股脑全用 bullets · 那是最没设计感的偷懒做法)**:\n"
        "  · 有步骤/流程/时间线/路线图(如'关键节点 6/28→7/2→7/20')→ <!-- layout: flow -->,不要写成缩进要点。\n"
        "  · 有数据/占比/对比/趋势 → <!-- layout: chart -->(pie 看占比 · column/bar 看对比 · line 看趋势)。\n"
        "  · 讲能力/特性/优势/几个方向 → <!-- layout: pillars -->(图标磁贴)或 two_col(左右对照)。\n"
        "  · 报成绩/关键数字 → <!-- layout: metrics -->,**但 value 只能放短数字/百分比**(如 92% / 12万 / 3个),"
        "**绝不要把'市场定位'这类词组塞进 value**(会被迫缩小、排版难看)——词组请改用 pillars/two_col。\n"
        "  · 一句重话/主张 → statement;过渡 → section;纯观点罗列才用 bullets(且每页 ≤6 条)。\n"
        "  · 正文直接写文字即可,**不用写 markdown 的 ** 粗体、# 井号(引擎会处理,写了也只当普通强调)**。\n"
        "  · **图标 token(如 {rocket})只在 metrics/pillars 页的行首用**,别写进普通句子里(会被当字面量清掉)。\n\n"
        "**格式(教给你的写法)**:\n"
        "  · 一行 `---` 分隔每页;每页可带指令注释(各占一行):\n"
        "    <!-- layout: cover|section|bullets|image|statement|two_col|metrics|pillars|chart|flow|sources|closing -->\n"
        "    <!-- kicker: 小眉标 -->  <!-- image: 相对图片路径 -->  <!-- prompt: 配图提示词 -->  <!-- caption: 图注 -->  <!-- notes: 演讲备注 -->\n"
        "    (指令可多条写一行,也可各占一行,都认。)\n"
        "  · `# 标题`  `## 小标题/列头`  `> 金句`  `- 要点`(缩进=子级)  `![](图路径)`\n"
        "  · metrics 页:要点写成 `值 | 说明`(如 `92% | 用户满意度`);two_col 页:两个 `##` 各起一列;\n"
        "    sources 页:每条要点 = 一条信源(可追溯 · 宪法第5条)。\n"
        "  · **图标磁贴页**: <!-- layout: pillars -->(=能力/特性/支柱页,2~4 张卡)· 每条 `{图标} 标题 :: 描述`,\n"
        "    如 `- {rocket} 快速交付 :: 一周内上线`。 图标名(会自动配图标):rocket/gear/people/chart/money/\n"
        "    idea/target/star/doc/check/time/search/flag/link/growth(也认 team/revenue/insight/process 等近义词)。\n"
        "  · **图标可加在 metrics 上**: `- {money} 12万 | 累计营收` —— KPI 卡顶部会出现对应图标。\n"
        "  · **图表页(手绘设计款,圆角渐变柱/面积折线/环形图)**: <!-- layout: chart --> + <!-- chart: pie|doughnut|bar|column|line -->。\n"
        "    单序列直接写要点 `标签 | 数值`(如 `内容账号 | 42`);多序列用 markdown 表格(首列=横轴,表头=各序列)。\n"
        "  · **流程图页**: <!-- layout: flow -->,每条要点 = 一个步骤框(≤5 步,按箭头串起来)。\n"
        "  · **有数据就上图表 / 讲能力就上图标磁贴**(饼看占比 / 柱看对比 / 折线看趋势 / 流程看步骤 / pillars 讲特性)"
        "—— 比干巴巴的要点高级得多。\n"
        "  · **每页 ≤6 条要点 · 一句话讲不完就拆 —— 留白才高级(QA 会提醒溢出)。**\n\n"
        "**设计风格(一套标准 · 自然语言调参 · 不是堆模板)**:\n"
        "  · style(基底 art direction · 6 套): light_studio(浅商务) / dark_keynote(深色发布会) / editorial(杂志编辑) / "
        "glass(玻璃拟态·磨砂半透明) / neon_glitch(霓虹故障·扫描线等宽) / sketch(手绘涂鸦·方格纸手写)。\n"
        "  · accent(主色): 从用户话里理解 → 传俗名或 hex,如 蓝/科技蓝/green/#2563EB。 引擎自动派生 accent2/文字对比/标题深调,通篇自洽。\n"
        "  · mood(气质): calm(沉稳) / vivid(活泼·字更大上色块) / sharp(锐利·去色块更利落)。\n"
        "  · style_spec(高级·越界作曲): 现成基底/accent/mood 覆盖不了的方向,你**自己产一组设计 token**(见参数 style_spec)叠加。 "
        "引擎会校验+夹紧+兜对比度,你飞不出「能看」的底线 —— 真·让你按需求现场定义风格。\n"
        "  → 排版纪律(对齐/留白/字阶/章节头不压标题)始终由引擎钉死。 「科技蓝活泼」「玻璃拟态暖橙」「复古打字机」都是同一引擎的不同参数,不是不同模板。\n\n"
        "**配图(优先级链 · 按序走)**:\n"
        "  ① 先试 generate_image(out_dir 传本工具的 embed_image_dir)生成图 → 再用 <!-- image: 返回的相对路径 --> 引入;\n"
        "  ② generate_image 报'未配置' → 用 browser_act 走豆包网页版 playbook 薅免费生图,落到 embed_image_dir 再引;\n"
        "  ③ 都不行(或还没生)→ 页里写 <!-- layout: image --><!-- prompt: 想要的画面描述 --> 渲成「配图提示词」占位卡"
        "(图标 + 提示词),之后可补图。 封面主视觉同样走这条链。\n"
        "  别硬凑图凑满每页,但**一份稿至少封面 + 每隔几页要有视觉**(image/chart/pillars)· 全程纯文字会很平(QA 会拦)。\n"
        "  **封面配图**: 传 cover_prompt(配了生图模型自动生成大图)或 cover_image(现成图)。 cover_layout=full(默认·满版大图铺底 + 渐变遮罩 + 白字叠上,最有冲击力)/ hero(左字右图分栏)/ auto。 都不传走渐变封面。\n"
        "  **封面提示词要有艺术感**: 按'主体+光线+明暗对比+构图+镜头+色调'写,且**左侧/暗部留干净负空间给标题**,画面别带文字。 例 cover_prompt='城市夜景俯瞰,冷暖霓虹交织,强烈明暗对比,左下大面积暗部留白,电影感广角,高级色调'。\n\n"
        "**两种给法**: ① 正文直接放 body;② 长稿推荐——先把完整分页 markdown 写在你回复里 · 再调本工具只给 title(自动抓)。\n"
        "tier: CONFIRM(产物 · 让 BRO 拍一下)。"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "演示稿标题 · 封面 + 文件名 · 必填"},
            "body": {
                "type": "string",
                "description": (
                    "分页 markdown 正文 · 一行 `---` 分页 · 每页可带 <!-- layout: ... --> 等指令"
                    "(cover/section/bullets/image/statement/two_col/metrics/pillars/chart/flow/sources/closing)。"
                    "不传则自动抓你本条回复的正文(适合长稿 / 弱模型)。"
                ),
            },
            "style": {
                "type": "string",
                "enum": ["light_studio", "dark_keynote", "editorial", "glass", "neon_glitch", "sketch"],
                "description": (
                    "基底风格 · light_studio(浅商务)· dark_keynote(深色发布会)· editorial(杂志编辑)· "
                    "glass(玻璃拟态·磨砂半透明)· neon_glitch(霓虹故障·扫描线等宽字)· sketch(手绘涂鸦·方格纸手写体)"
                ),
            },
            "accent": {
                "type": "string",
                "description": (
                    "主色 · 从用户需求理解后传 · 俗名(蓝/科技蓝/紫/green/橙/黑…)或 hex(#2563EB / 2563EB)。"
                    "引擎自动派生配套色与对比,保证自洽 · 不传用基底色。"
                ),
            },
            "mood": {
                "type": "string",
                "enum": ["calm", "vivid", "sharp"],
                "description": "气质 · calm 沉稳(默认)/ vivid 活泼(字更大、上色块)/ sharp 锐利(去色块、更利落)· 也认中文沉稳/活泼/锐利",
            },
            "style_spec": {
                "type": "object",
                "description": (
                    "【高级 · LLM 直接作曲风格】当用户要的方向现成基底/accent/mood 覆盖不了时,你自己产一组设计 token(此对象)"
                    "叠加在基底上。 引擎会校验 + 夹紧 + 兜对比度(你飞不出'能看'的底线)。 可用 token:\n"
                    "  颜色(hex 或俗名): bg / bg_alt / ink_title / ink_body / ink_muted / accent / accent2 / on_accent / rule\n"
                    "  材质: surface_alpha(8-100·面板透明度,玻璃用低值) · corner_radius(0-0.5·0=硬边) · panel_gradient(bool)\n"
                    "  效果: shadow_style(none|soft|glow|hard) · texture(none|grid|dots|scanline|beams) · stroke_style(clean|hairline|hard|sketch)\n"
                    "  个性: font_role(sans|serif|mono|hand) · accent_shape(bar|underline|dot|slash|none) · decor(none|blob 装饰圆|corner 取景框) · is_dark(bool) · uppercase_kicker(bool)\n"
                    "  字阶: pt_cover_title/pt_title/pt_section/pt_heading/pt_body/pt_kpi/pt_statement(9-96)\n"
                    "例:磨砂玻璃暖橙 → style=glass + style_spec={\"accent\":\"橙\",\"surface_alpha\":20}；"
                    "复古打字机 → {\"font_role\":\"mono\",\"texture\":\"grid\",\"bg\":\"F4EFE3\",\"accent\":\"8A3B2E\",\"shadow_style\":\"none\"}。"
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
                "description": (
                    "封面配图提示词 · 配了生图模型(auto_image)会自动生成大图做封面;没配退回渐变封面。"
                    "要有艺术感:主体+光线+明暗对比+构图+镜头+色调,且左侧/暗部留干净负空间给标题,画面别带文字。"
                ),
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
                "description": (
                    "自动配图 · 默认 True。 对「有 <!-- prompt: 画面描述 --> 但没 <!-- image -->」"
                    "的页,若配了生图模型(DAEMONKEY_IMAGE_MODEL)就自动生成图填入;没配则留提示词占位卡。"
                    "设 False 则一律只留占位卡(自己后面用豆包/生图补)。"
                ),
            },
        },
        "required": ["title"],
        "additionalProperties": False,
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
