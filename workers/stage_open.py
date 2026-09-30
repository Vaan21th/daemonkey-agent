"""HTML 原型铺中栏：哪些路径算成品、打 DK-OPEN、拼可服务地址。"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_PREFIXES = (
    "data/workshop/outputs/",
    "data/design/",
    "data/docs/",
    "data/dev/",
    "data/content/",
    "data/presentations/",
)

# ── 中栏展示判据（唯一真相源）────────────────────────────────────
# 「要不要上中栏」看目录 —— 目录名本身说明了用途（格子的名字要窄到，
#   不该进来的东西自己就不想来）。
# 「能不能渲染」看格式 —— 前端 static/stage.js 是这份判据的渲染侧镜像：
#   改这里时同步看一眼 stageClassify / stageMdApi / stageFileUrl。
SHOW_DIRS = (
    "data/design/",            # 画布区：原型 · 看板 · 演示
    "data/workshop/outputs/",  # 工坊产物
    "data/docs/",              # 对外文档
    "data/content/",           # 内容稿
    "data/dev/",               # 研发过程文档（执行报告 · 定案）
    "data/presentations/",     # PPT
    "data/spreadsheets/",      # 表
    "data/reports/",           # 报告
)

RENDER = {
    ".html": "html", ".htm": "html",
    ".md": "md", ".txt": "md",
    ".pptx": "office", ".ppt": "office",
    ".docx": "office", ".doc": "office",
    ".xlsx": "office", ".xls": "office",
    ".pdf": "pdf",
    ".png": "image", ".jpg": "image", ".jpeg": "image",
    ".gif": "image", ".webp": "image",
    ".mp4": "video", ".webm": "video", ".mov": "video",
}

# md / txt 另有一层目录限制（前端 stageMdApi 的镜像：不是每个目录的 md 都能渲染）
_MD_DIRS = (
    "data/docs/", "data/content/", "data/design/", "data/dev/",
    "data/reports/", "data/workshop/outputs/",
)

# 下面这份是「能被 /stage/file 服务」的白名单 —— 服务能力，不是展示判据，两者别混
_HTML = {".html", ".htm"}
_ASSETS = _HTML | {
    ".css", ".js",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    # wish-1dc9c39d: 工坊产物的媒体大头。原来只有图 —— mp4 / 音频一律 415 打不开。
    #   实测 data/workshop/outputs：mp4 1103 个（比图的 1411 还接近）· 不改就是「视频全打不开」。
    #   PDF 同理（档案类里有 pdf）。
    ".mp4", ".webm", ".mov",
    ".mp3", ".wav", ".m4a", ".ogg",
    ".pdf",
    ".woff", ".woff2", ".ttf",
}

_MIME = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".pdf": "application/pdf",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
}


def rel_posix(path: Path | str, root: Path | None = None) -> str:
    base = (root or ROOT).resolve()
    p = Path(path)
    if not p.is_absolute():
        p = base / p
    try:
        return p.resolve().relative_to(base).as_posix()
    except ValueError:
        return ""


def stage_mode(path: Path | str, root: Path | None = None) -> str:
    """这个文件在中栏能不能展示？返回 mode（html/md/office/pdf/image/video），不能则 ''。

    判据只此一份：目录决定要不要上，格式决定能不能渲染。
    前端 static/stage.js 是它的渲染侧（stageClassify），改这里要看一眼那边。
    """
    rel = rel_posix(path, root)
    if not rel or not any(rel.startswith(d) for d in SHOW_DIRS):
        return ""
    mode = RENDER.get(Path(rel).suffix.lower(), "")
    if mode == "md" and not any(rel.startswith(d) for d in _MD_DIRS):
        return ""
    return mode


def is_stage_html(path: Path | str, root: Path | None = None) -> bool:
    """专指「能上中栏的 HTML」—— 留给老调用点（render_png 等）的老语义。"""
    return stage_mode(path, root) == "html"


def append_open_mark(output: str, path: Path | str, root: Path | None = None) -> str:
    """给前端打标记（tool_loop 抽成 open_path → 前端铺中栏）。

    凡是「能上中栏的」（stage_mode 非空）都打 —— 不再只管 html。
    """
    if not stage_mode(path, root):
        return output
    rel = rel_posix(path, root)
    mark = f"[[DK-OPEN]]{rel}"
    if not rel or mark in (output or ""):
        return output
    return (output or "").rstrip() + "\n" + mark + "\n"


def attach_stage(output: str, path: Path | str, root: Path | None = None) -> str:
    """产文件工具的统一出口：一次挂上「能不能上中栏」的两件事。

    ① 给前端的 [[DK-OPEN]] 标记（tool_loop 抽成 open_path 后剥掉·不进 LLM 内容）
    ② 给模型看的一句人话（stage_notice）—— 标记会被剥掉，所以必须单独说

    所有产文件的工具都走这个，别再各自手写标记 —— 各写各的就是两份判据的源头。
    """
    out = append_open_mark(output, path, root)
    notice = stage_notice(path, root)
    if notice:
        out = f"{out.rstrip()}\n{notice}\n"
    return out


def stage_notice(path: Path | str, root: Path | None = None) -> str:
    """给模型看的一句人话：这次写的东西会不会铺上中栏、没铺是为什么。

    上面那个标记只给前端读 —— 在给模型看之前会被剥掉。所以必须单独说一句人话，
    否则模型只能猜「我写进目录了，应该铺了吧」，BRO 那边却什么都没有。
    无关文件（.py / .json 等）返回空串，不给噪音。
    """
    rel = rel_posix(path, root)
    if not rel:
        return ""
    ext = Path(rel).suffix.lower()
    mode = stage_mode(path, root)
    if mode:
        return f"✓ 已铺中栏（中栏会以 {mode} 打开它）"
    if ext not in RENDER:
        return ""          # 本来就不上中栏的东西（.py / .json …），不给噪音
    if not any(rel.startswith(d) for d in SHOW_DIRS):
        return (
            "✗ 不会铺中栏 —— 不在「能给 BRO 看」的目录里。会铺的只有："
            + " · ".join(SHOW_DIRS)
        )
    return (
        "✗ 不会铺中栏 —— 这个目录的 .md / .txt 前端渲染不了。"
        "能渲染 md 的目录：data/design/ · data/docs/ · data/content/ · "
        "data/dev/ · data/reports/ · data/workshop/outputs/"
    )


def mime_for(path: Path | str) -> str:
    return _MIME.get(Path(str(path)).suffix.lower(), "")


def resolve_served(rel: str, root: Path | None = None) -> Path | None:
    """只放行工坊成品树里的 HTML/样式/配图，挡住路径穿越。"""
    p = str(rel or "").replace("\\", "/").lstrip("/")
    if not p or ".." in p or p.startswith("/") or "\x00" in p:
        return None
    if not any(p.startswith(pref) for pref in _PREFIXES):
        return None
    if Path(p).suffix.lower() not in _ASSETS:
        return None
    base = (root or ROOT).resolve()
    full = (base / p).resolve()
    try:
        full.relative_to(base)
    except ValueError:
        return None
    if not full.is_file():
        return None
    return full


# ── 落盘侦测（2026-09-20 第3刀 · 给「绕过工具直接写文件」的通道兜底）──────────
# 病：python_exec / shell_exec 能直接往白名单目录写文件 —— 它们没有「声明」这一步，
#     于是产出的东西既不铺中栏、也不出声（BRO 那边看着就是「什么都没发生」）。
# 治法不用提示词（要模型知道约定 = 又往工具描述里加话），用工程：执行前后各扫一遍
# 「能给 BRO 看」的目录，**差集**就是本次新落的产物。
# 两条硬边界：① 只认新出现的路径 —— 「顺手改了个旧文件」不算，免得把 BRO 正看的画布顶掉；
#            ② 判据全部复用上面那份 SHOW_DIRS / RENDER，不另写白名单。

def snapshot_stage_dirs(root: Path | None = None) -> set[str]:
    """扫一遍「能给 BRO 看」的目录 · 返回可上中栏产物的相对路径集合。

    实测：循环里调 Path.resolve() / stage_mode() 会变成 3500 次系统调用 —— 2.5 秒。
    这条路径挂在 python_exec / shell_exec 的每次调用上，所以只走纯字符串判据
    （目录本来就从 SHOW_DIRS walk 出来，格式查 RENDER，md 另查 _MD_DIRS）。
    """
    base = (root or ROOT).resolve()
    base_s = str(base)
    out: set[str] = set()
    for d in SHOW_DIRS:
        top = base / d.rstrip("/")
        if not top.is_dir():
            continue
        try:
            for dirpath, _dirs, files in os.walk(top):
                rel_dir = os.path.relpath(dirpath, base_s).replace("\\", "/")
                md_ok = any((rel_dir + "/").startswith(x) for x in _MD_DIRS)
                for fn in files:
                    mode = RENDER.get(os.path.splitext(fn)[1].lower(), "")
                    if not mode or (mode == "md" and not md_ok):
                        continue
                    out.add(rel_dir + "/" + fn)
        except OSError:
            continue
    return out


def detect_new_stage_files(before: set[str] | None, root: Path | None = None) -> list[str]:
    """与快照比对 · 返回本次**新出现**的可上中栏产物（排序稳定）。"""
    if before is None:
        return []
    return sorted(snapshot_stage_dirs(root) - set(before))


def attach_detected(result, before: set[str] | None, root: Path | None = None):
    """落盘侦测的收口：把本次新落的产物挂成 result.stage_path + 说一句人话。

    只挂**最后一份**；多份时在输出里列全，模型自己看得见还剩谁没铺。
    """
    if before is None or result is None or not getattr(result, "ok", False):
        return result
    try:
        news = detect_new_stage_files(before, root)
    except Exception:
        return result
    if not news:
        return result
    result.stage_path = news[-1]
    lines = [
        "[落盘侦测] 这次执行新落了 %d 份能上中栏的产物（没走工具的声明通道，是扫目录发现的）："
        % len(news)
    ]
    for p in news[:6]:
        lines.append("  · " + p)
    if len(news) > 6:
        lines.append("  · …还有 %d 份" % (len(news) - 6))
    result.output = (result.output or "").rstrip() + "\n" + "\n".join(lines) + "\n"
    return result
