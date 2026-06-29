"""
agent_tools/browser_act.py
==========================

浏览器的"手"——在 daemon 专属 Edge 上真的点/填/传/等/读/收/截图（browser_fetch 是只读的眼睛）。

机制（共享 _browser 同款 CDP）：自动拉起一个 daemon **专属 Edge**（独立 profile + 独立端口，
不碰用户日常浏览器），connect_over_cdp 接管它。每次 attach→操作→断开，**不关页**，状态留在
专属 Edge 标签页里，实现"开站→上传参考图→填提示词→点生成→等→收图"跨多次调用接力。
首次用某需登录站点（豆包等），在这个专属窗口登一次即可。

动作逻辑在 _browser_actions.dispatch；本文件只管 CDP 连接 + 工具登记，守住单文件 ≤300 行。

兜底铁律：找不到元素/动作失败 → 自动截图 + 如实报卡在哪一步，**绝不假装成功**。

档位：read/wait/screenshot/inspect=AUTO（只看不改）；其余有实际动作=CONFIRM。
"""

from __future__ import annotations

from . import TIER_AUTO, TIER_CONFIRM, ToolResult, ToolSpec, register_tool
from ._browser import CDP_URL, ensure_cdp
from ._browser_actions import READONLY_ACTIONS, dispatch


def _run(args: dict) -> ToolResult:
    if not ensure_cdp():
        return ToolResult(
            ok=False, output="",
            error=(
                "起不来 daemon 专属浏览器（独立 profile 那个）。\n"
                "通常是没装 Edge / Chrome（任一 Chromium 内核浏览器），或装在非标准路径。\n"
                "→ 装个 Edge 或 Chrome 即可；绿色版/非标准路径可设环境变量 DAEMONKEY_BROWSER_PATH "
                "指向浏览器 exe 后重启 daemon。"
            ),
        )
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return ToolResult(ok=False, output="", error="playwright 未安装：pip install playwright")

    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(CDP_URL)
            return dispatch(browser, args)
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"CDP 操作失败: {type(e).__name__}: {e}")


def _classify(args: dict) -> str:
    return TIER_AUTO if (args.get("action") or "").strip() in READONLY_ACTIONS else TIER_CONFIRM


def _summarize(args: dict) -> str:
    action = args.get("action") or "?"
    tgt = (
        args.get("url") or args.get("selector") or args.get("text")
        or args.get("files") or args.get("key") or ""
    )
    return f"browser_act · {action}{(' · ' + str(tgt)[:50]) if tgt else ''}"


SPEC = ToolSpec(
    name="browser_act",
    description=(
        "在 daemon 专属 Edge 上【真的操作网页】——点击/填写/上传/等待/读取/下载/收图/截图/探查。"
        "这是浏览器的'手'，配合 browser_fetch（只读抓文字）使用。\n\n"
        "**前置**：无需手动开浏览器——会自动拉起 daemon 专属 Edge（独立 profile，与用户日常浏览器隔离）；"
        "首次在该窗口登录一次目标站点即可，登录态持久化复用。\n\n"
        "**多步接力**：动作不关标签页，状态留在专属 Edge 里。典型链路（带参考图的生图站）：\n"
        "  goto(url) → click(text='图像生成') → upload(selector='input[type=file]', files=[参考图]) → "
        "fill(selector=输入框, value=提示词) → press(key='Enter') → wait(selector=出图容器) → "
        "harvest(selector='img[src*=...]')\n\n"
        "**新站不认识？先 inspect** 把页面可交互控件 dump 成文字（纯文本模型即可据此挑选择器，不需视觉）。\n"
        "**fill 支持 contenteditable 富文本框**（ProseMirror/TipTap）。**用 url_contains 锁定标签页**。\n\n"
        "**action**：\n"
        "  - goto       · url（开/跳到页面）\n"
        "  - inspect    · dump 当前页所有可见可交互控件（tag/文字/placeholder/aria/class），探路首选\n"
        "  - click      · selector 或 text\n"
        "  - fill       · selector + value（普通输入框/富文本框）\n"
        "  - upload     · selector(<input type=file>) + files（上传本地文件，如参考图）\n"
        "  - press      · key（如 Enter / Control+A；可带 selector 先聚焦）\n"
        "  - wait       · selector（等元素出现）或仅 timeout_ms\n"
        "  - read       · selector（读某元素文字）或整页正文\n"
        "  - download   · selector/text（点按钮触发的文件下载）\n"
        "  - harvest    · selector（收页面已渲染的图/视频：读 src 直接拉到文件夹，比点'下载'稳）\n"
        "  - screenshot · 给当前页截图\n\n"
        "**兜底**：找不到元素绝不假装成功——自动截图并如实报卡在哪一步。"
    ),
    tier=TIER_CONFIRM,
    classify=_classify,
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "goto", "inspect", "click", "fill", "upload", "press",
                    "wait", "read", "download", "harvest", "screenshot",
                ],
            },
            "url": {"type": "string", "description": "goto 用：要打开的 http(s) 地址"},
            "url_contains": {"type": "string", "description": "锁定标签页：选 url 含此串的那个 tab"},
            "selector": {"type": "string", "description": "CSS 选择器（click/fill/upload/press/wait/read/download/harvest）"},
            "text": {"type": "string", "description": "按可见文字定位（click/download，selector 的替代）"},
            "value": {"type": "string", "description": "fill 用：要填入的内容"},
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "upload 用：要上传的本地文件绝对路径（单个也用数组；如参考图）",
            },
            "key": {"type": "string", "description": "press 用：键名，如 Enter、Control+A"},
            "timeout_ms": {"type": "integer", "description": "动作超时毫秒，默认 10000"},
            "download_dir": {"type": "string", "description": "download/harvest 用：保存目录（默认按日期建在 sessions/downloads 下）"},
            "name_prefix": {"type": "string", "description": "harvest 用：保存文件名前缀（默认 img）"},
        },
        "required": ["action"],
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
