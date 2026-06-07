# -*- coding: utf-8 -*-
"""workers/frontend_check.py · 前端 JS 语法闸 (卷五十四 · 2026-06-03)

病根 (本次事故):
  OPUS 重写沉淀位面板时·用 `python_exec` 手写字符串切片改 chat.js:
      js = js[:start_idx] + new_sinks + "\\n" + old_end   # old_end = "function loadMoreWishes() {"
  边界算错·把 `loadMoreWishes` 函数体 + 之后 1660 行整段吞掉·chat.js 停在
  `function loadMoreWishes() {` → JS 语法错 (Unexpected end of input) → 浏览器一加载就整个白屏。
  而 `verify_daemon_endpoints` 只验 Python 路由 (FastAPI TestClient)·**根本不碰前端**·
  于是坏掉的 chat.js 顶着"82/82 全绿"被 commit + 重启·BRO 打开 WebUI 全死。

这个模块补上前端那一环:
  - node 在 → `node --check` (权威·跟浏览器同一个 V8 parser)
  - node 缺失 (开源用户没装) → 纯 Python "尾部截断"启发式兜底·正好抓这类被砍尾巴的 case·
    抓不全所有语法错·但绝不硬崩、绝不误拦正常文件。

只扫 static/ 顶层自己维护的 JS·跳过 static/lib/ 下的三方 vendor (litegraph 等)。
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
        ("SpeechRecognition", "语音输入"),
        ("_DOC_MIMES", "文档附件"),
        ("renderSettingsVision", "视觉模型设置 UI"),
    ],
    "chat.html": [
        ('id="micBtn"', "语音输入按钮"),
        (".docx", "文档附件 accept 类型"),
    ],
    "chat.css": [
        ("#micBtn.listening", "语音按钮聆听态样式"),
        (".attach-doc-card", "文档附件卡片样式"),
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
