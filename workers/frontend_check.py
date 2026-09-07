# -*- coding: utf-8 -*-
"""前端 JS 语法闸 + 功能哨兵。node --check；没 node 时用尾部截断启发式。
只扫 static/ 顶层自己的 JS，跳过 lib/。哨兵防整文件覆盖把功能删了语法还绿。
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# node 缺失时的兜底: 文件正文末尾停在这些 token 上 = 明显未完成 (被截断)。
#   只挑最确凿的截断信号·宁可漏报也不误拦: 开括号 / 逗号 / 箭头 / 二元运算符结尾·
#   或最后一行是 `function ...(...) {` 这种刚开函数头就没了的形态。
_DANGLING_TAIL = re.compile(r"(?:[{(\[,]|=>|&&|\|\||[-+*/%=<>])\s*$")
_DANGLING_FUNC_HEAD = re.compile(r"\bfunction\b[^\n{};]*\([^\n)]*\)\s*\{\s*$")


def _own_js_files(root: Path) -> list[Path]:
    """static/ 顶层自己维护的 .js · 不含 lib/ 下三方库。"""
    static = root / "static"
    if not static.is_dir():
        return []
    return sorted(static.glob("*.js"))


# ── 卷五十八 · 功能哨兵 · 防"整文件覆盖悄悄删功能"回归 ──────────────────
#   888e0ec 把 chat.js/html/css 三个文件整体打回旧版·语法全绿·但语音/文档/视觉功能没了。
#   语法闸抓不到 (删了功能·语法照样合法)。 哨兵补这一环: 关键功能的"指纹标记"必须仍在·
#   缺了就当语法错一样拦 (request_restart / merge 出口硬闸自动生效)。
#   ★ 有意删除某功能 → 从这份清单移除对应标记 (git diff 看得见·等于一次明示)·
#     不要靠"绕过哨兵"·那等于自废武功。
_FEATURE_SENTINELS: dict[str, list[tuple[str, str]]] = {
    "chat.js": [
        ("initVoice(", "语音输入挂载"),
        ("initModelSwitch(", "顶栏切模型挂载"),
        ("_DOC_MIMES", "文档附件"),
        ("openSettings(", "设置入口仍在工作台"),
        ("拆出去的脚本没到位", "READY 等三块都在才置 true"),
        ("function bindWorkingDoc", "稿挂进这场对话"),
        ("function refreshWorkingDocs", "输入框上的稿芯片"),
        ("function goOfficeHome", "点办公产物先回它的家话题"),
        ("function syncOfficeStageHome", "切走话题就收起别人的稿"),
        ("working-docs/home", "查稿的家话题"),
        ("data.claimed", "认领过的对话不拽回旧家"),
        ("确认卡放在重画之后", "F5 续场确认卡不被历史重画擦掉"),
        ("state._pollBusy", "续场轮询不重叠双挂确认卡"),
        ("Daemonkey.emit('message:render'", "气泡渲染走事件总线"),
        ("Daemonkey.emit('sse:event'", "SSE 走事件总线"),
        ("Daemonkey.emit('view:switch'", "切视图走事件总线"),
    ],
    "daemonkey-bus.js": [
        ("DK.emit = function", "事件总线 emit"),
        ("view:switch", "承诺 view:switch"),
        ("message:render", "承诺 message:render"),
        ("sse:event", "承诺 sse:event"),
    ],
    "settings-pane.js": [
        ("function renderSettingsView", "设置页外壳"),
        ("function renderSettingsVision", "视觉模型设置 UI"),
        ("function renderSettingsLLM", "LLM 多配置"),
        ("llmEditCtxWindow", "上下文窗户可填"),
        ("/stt/enabled", "语音识别启用开关真接线"),
        ("storedKey.includes('****')", "视觉已配好不逼着重贴 key"),
        ("/media-defaults", "多模态默认生图/语音合成"),
        ("function startMediaGuide", "带去接入生图或配音"),
        ("function _currentTopicHasTalk", "接入引导空场就地聊、有内容才另开"),
    ],
    "voice-mic.js": [
        ("SpeechRecognition", "语音输入"),
        ("function initVoice", "语音初始化入口"),
        ("dispatchEvent(new Event('input'", "语音填框会通知排队"),
        ("function _holdForSpeech", "她说话时不把外放当作用户话"),
        ("window.__interruptSpeech", "点她或音量可打断语音合成"),
    ],
    "chat-lightbox.js": [
        ("_renderBroAttachments", "历史附件重建"),
        ("_showLightbox", "点图看大图"),
        (".bro-attach-img", "用户气泡图可点"),
    ],
    "chat-md.js": [
        ("function mdRender", "对话 Markdown 渲染"),
        ("window.opusMdRender", "给工坊复用的 md 入口"),
    ],
    "chat-timeline.js": [
        ("const TL_T2C", "工具时间线分类表"),
        ("function renderToolTimeline", "历史回放时间线"),
    ],
    "chat-rail.js": [
        ("function _ensureMsgRail", "提问轨道"),
        ("_applyRailMagnet", "轨道磁性拉伸"),
    ],
    "market.js": [
        ("dk_plugin_hub", "插件库中间栏切换"),
        ("/market", "货架 API"),
        ("/market/rate", "货架打分"),
        ("/market/inbox", "仓主待审"),
        ("mkt-star", "装过才能点星"),
        ("data-kind", "导出不靠冒号拆 id"),
        ("上架到货架", "导出并提合并申请"),
        ("我的叠层", "插件库叠层页"),
        ("/api/overlays", "叠层清单 API"),
        ("paintPluginAlert", "插件库叠层红点"),
    ],
    "model-switch.js": [
        ("function initModelSwitch", "顶栏切模型入口"),
        ("function modelBehaviorPayload", "思考/强度/输出上限"),
        ("/models/switch", "切模型 API"),
    ],
    "chat.html": [
        ('id="micBtn"', "语音输入按钮"),
        ("model-switch.js", "顶栏切模型共用脚本"),
        ("settings-pane.js", "设置页共用脚本"),
        ("chat-lightbox.js", "历史图灯箱"),
        ("chat-md.js", "Markdown 抽出"),
        ("chat-timeline.js", "工具时间线抽出"),
        ("chat-rail.js", "提问轨道抽出"),
        ("daemonkey-bus.js", "事件总线"),
        ("market.js", "扩展市场中间栏"),
        ("stage.js", "中栏舞台"),
        ("stage_notes.js", "画布批注"),
        ("脚本没加载到", "拆出脚本 404 记进 boot-guard"),
        ("/static/user/", "装修区脚本 404 不当核心失败"),
        (".docx", "文档附件 accept 类型"),
        ('id="workingDocsBar"', "本话题稿芯片条"),
    ],
    "companion/companion.js": [
        ("function interruptSpeak", "点她或音量打断房间语音合成"),
        ("window.__speakNow", "房间出声走半双工"),
        ("say-cut", "气泡上能打断她"),
        ("Daemonkey.emit('message:render'", "房间气泡走事件总线"),
        ("Daemonkey.emit('sse:event'", "房间 SSE 走事件总线"),
        ("Daemonkey.emit('view:switch'", "房间切门走事件总线"),
    ],
    "chat.css": [
        ("#micBtn.listening", "语音按钮聆听态样式"),
        (".attach-doc-card", "文档附件卡片样式"),
        (".mkt-card", "扩展市场卡片不被 flex 压扁"),
        (".mkt-star", "扩展市场打分星星"),
        (".mkt-verdict", "市集待审红绿灯"),
        (".badge.overlay-alert", "插件库叠层红点"),
        (".mkt-card.overlay-bad", "坏叠层卡片描边"),
        (".stage-root", "中栏舞台铺满"),
        (".stage-x", "画布关闭钮"),
        (".stage-tag", "画布类型徽章"),
        (".stage-pin", "画布批注钉子"),
        (".rp-slide-thumbs", "翻页预览左侧缩略图"),
        (".stage-note-send", "按批注改"),
        (".working-docs-bar", "本话题稿芯片条"),
        (".wd-chip", "稿芯片"),
    ],
    "stage.js": [
        ("function openStage", "中栏打开产物"),
        ("function openStageLast", "本轮产出自动铺中栏"),
        ("function stageClose", "关掉画布"),
        ('mode === "plan"', "计划书铺中栏"),
        ("stageNotesBind", "画布批注接线"),
        ("bindWorkingDoc", "中栏打开就把稿挂进对话"),
        ("goOfficeHome", "打开办公稿先回它的家话题"),
        ("styleOfficePreviewFrame", "成品预览滚动条跟画布走"),
        ("/stage/file/", "HTML 原型中栏地址"),
        ("histFile", "打开历史稿不切家话题"),
    ],
    "dashboard-panels.js": [
        ("function loadReportPreview", "产物中栏预览"),
        ("function restoreShelfVersion", "历史版抄回当前"),
        ("function shelfStageBits", "中栏标题分当前/历史"),
        ("function shelfPreviewUrl", "预览地址跟点的文件走"),
        ("data.requested = filename", "点哪份就渲哪份"),
        ("rp-slide-thumbs", "翻页预览左侧缩略图"),
        ("rpStageMeta", "中栏标当前/历史和体积"),
        ("!/^_hist_/i.test(filename)", "打开历史稿不切家话题"),
    ],
    "stage_notes.js": [
        ("function notesSend", "按批注改塞进对话"),
        ("function notesOnClick", "点画布钉批注"),
        ("stageNotesBusy", "计划刷新不冲未记下的批注"),
        ("injectAndSend", "批注走现成对话入口"),
        ("STAGE_NOTES_KEY", "批注本地记住"),
        ("notesSave([])", "按批注改发出去就清钉子"),
        ("notesRegion", "钉子带页码和左上/中下区域"),
        ("revise_office", "批注改稿走局部改，不整份重写"),
        ("illustrate_office", "批注可在页上加图"),
        ("notesIntent", "批注按加图/插页/版式分手"),
        ("notesLiveSel", "成品 iframe 里划的字也能圈"),
        ("notesMaybeFromSel", "划字松手就开批注卡"),
        ("notesPinOnPage", "钉子只留在钉过的那一页"),
        ("function notesSlideImg", "翻页预览钉子钉在当前页图上"),
        ("圈出的成品原文", "批注提示 excerpt 用成品上的字"),
        ("成品里划中", "段落改在成品上圈，不切文稿"),
        ("bindWorkingDoc", "按批注改把稿挂进这场对话"),
        ("working_docs", "这场已经挂过这份稿就留在这场"),
        ("home_sid", "没认领才回最早那场"),
        ("switchToSession", "认领过的对话按批注改不拽走"),
    ],
}


def check_sentinels(root: Path | None = None) -> list[str]:
    """检查关键功能指纹是否还在 · 返回缺失项列表 (空 = 全在)。"""
    root = root or ROOT
    static = root / "static"
    problems: list[str] = []
    for fname, markers in _FEATURE_SENTINELS.items():
        fp = static / fname
        if not fp.exists():
            problems.append(f"{fname}: 文件不存在 (整个文件丢了?)")
            continue
        try:
            text = fp.read_text(encoding="utf-8")
        except Exception as e:
            problems.append(f"{fname}: 读不了 ({type(e).__name__})")
            continue
        for marker, feature in markers:
            if marker not in text:
                problems.append(
                    f"{fname}: 功能哨兵缺失 →「{feature}」的标记 {marker!r} 不见了 "
                    f"(疑似被整文件覆盖抹掉 · 这正是 888e0ec 的事故)"
                )
    return problems


def _node_check(node: str, path: Path) -> tuple[bool, str]:
    # 卷五十六 · 2026-06-06 · 补 no_window_kwargs() 消除黑框闪窗。
    #   病根: daemon 跑在 detached/pythonw 无 console 下·node.exe 是 console subsystem·
    #   不带 CREATE_NO_WINDOW+SW_HIDE 时 Windows 会给每个 node 进程新分配一个控制台窗口。
    #   而本模块逐个 static/*.js 跑一次 node --check (chat.js + workshop.js = 2 个) ·
    #   于是每次 request_restart 的前端语法闸都闪 2 个黑框 (BRO 复盘「突然出现两个闪窗」)。
    try:
        from agent_tools._subprocess_helper import no_window_kwargs
        _kw = no_window_kwargs()
    except Exception:
        _kw = {}
    try:
        r = subprocess.run(
            [node, "--check", str(path)],
            capture_output=True, timeout=20,
            **_kw,
        )
    except Exception as e:
        # node 自身跑不起来 (超时/权限) 不阻塞·当跳过
        return True, f"(node --check 跑不起来·跳过 {path.name}: {type(e).__name__})"
    if r.returncode == 0:
        return True, ""
    err = (r.stderr or b"").decode("utf-8", "replace").strip()
    return False, err[:600]


def _tail_heuristic(text: str) -> tuple[bool, str]:
    """node 缺失时的兜底·看文件正文末尾是否停在未闭合 token 上。"""
    stripped = text.rstrip()
    if not stripped:
        return True, ""
    last_line = stripped.splitlines()[-1].strip()
    if _DANGLING_FUNC_HEAD.search(stripped) or _DANGLING_TAIL.search(stripped):
        return False, f"文件结尾疑似被截断·最后一行: {last_line[:120]!r}"
    return True, ""


def check_static_js(root: Path | None = None) -> dict:
    """前端静态资源健康检查 = 语法闸 + 功能哨兵。

    返回 {ok, method, checked, problems}。problems 非空 = JS 语法坏了 或 关键功能被抹掉。
    """
    root = root or ROOT
    files = _own_js_files(root)
    node = shutil.which("node")
    method = "node --check" if node else "tail-heuristic (node 缺失)"
    problems: list[str] = []
    checked: list[str] = []

    for p in files:
        if node:
            ok, msg = _node_check(node, p)
        else:
            try:
                ok, msg = _tail_heuristic(p.read_text(encoding="utf-8"))
            except Exception as e:
                problems.append(f"{p.name}: 读不了 ({type(e).__name__})")
                continue
        checked.append(p.name)
        if not ok:
            problems.append(f"{p.name}: {msg}")

    # 卷五十八 · 功能哨兵 (语法绿但功能被删的回归·只有这一环抓得到)
    problems += check_sentinels(root)

    return {
        "ok": len(problems) == 0,
        "method": method + " + 功能哨兵",
        "checked": checked,
        "problems": problems,
    }


def format_report(result: dict) -> str:
    if result.get("ok"):
        names = ", ".join(result.get("checked") or []) or "(无)"
        return f"✅ 前端 JS 语法 + 功能哨兵 OK ({result['method']})·已校验: {names}"
    lines = [f"❌ 前端校验失败 ({result['method']})"]
    for prob in result.get("problems", []):
        lines.append(f"  • {prob}")
    return "\n".join(lines)
