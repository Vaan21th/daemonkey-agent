"""
agent_tools/_browser_actions.py
===============================

browser_act 的动作分发——把网页动作（点/填/等/读/下载/收/截图/上传）从工具壳里拆出来，
让 browser_act.py 保持精简（单文件 ≤300 行红线）。

每个动作失败都走 _fallback：截图 + 如实报卡点，**绝不假装成功**。
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from . import ToolResult
from ._browser import peeking, pick_page

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_TIMEOUT_MS = 10000
SHOT_DIR = PROJECT_ROOT / "sessions" / "screenshots"
DOWNLOAD_ROOT = PROJECT_ROOT / "sessions" / "downloads"

READONLY_ACTIONS = {"read", "wait", "screenshot", "inspect", "eval"}

_MEDIA_EXTS = (".png", ".jpeg", ".jpg", ".webp", ".gif", ".mp4", ".webm")


def _clamp_timeout_ms(raw) -> int:
    try:
        n = int(raw if raw is not None else DEFAULT_TIMEOUT_MS)
    except (TypeError, ValueError):
        raise ValueError("timeout_ms 必须是整数毫秒")
    return max(1000, min(n, 600_000))


def _sandbox_dir(raw, default: Path) -> Path:
    """下载目录必须落在工程根内。"""
    if raw:
        p = Path(str(raw))
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        p = p.resolve()
    else:
        p = default.resolve()
    try:
        p.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        raise ValueError(f"路径越界: {p}")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_prefix(raw: str) -> str:
    name = Path(str(raw or "img").strip() or "img").name
    name = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]", "_", name)[:40]
    return name or "img"


def _save_shot(page, tag: str) -> str:
    """给当前页截图（兜底取证用）。返回相对路径或空串。

    2026-09-20 · 专属浏览器常态是「收着的」，而最小化窗口没有合成帧 —— 直接截会
    超时（原生 30s）甚至挂死（CDP）。peeking 把窗口临时展开到屏幕外（不激活、
    看不见）截完就收回，截图可靠且不打扰 用户。
    """
    try:
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        out = SHOT_DIR / f"act_{tag}_{ts}.png"
        with peeking():
            page.screenshot(path=str(out), timeout=12000)
        return str(out.relative_to(PROJECT_ROOT))
    except Exception:
        return ""


def _fallback(page, action: str, detail: str) -> ToolResult:
    """统一兜底：截图 + 如实报卡点，不假装成功。"""
    shot = _save_shot(page, action) if page else ""
    msg = (
        f"[{action}] 没做成：{detail}\n"
        f"当前页: {getattr(page, 'url', '?')}\n"
        + (f"截图已存: {shot}\n" if shot else "")
        + "→ 这一步请你手动做，或把准确的 selector / 按钮文字告诉我再来。我不会假装成功。"
    )
    return ToolResult(ok=False, output="", error=msg)


def dispatch(browser, args: dict) -> ToolResult:
    action = (args.get("action") or "").strip()
    url_contains = (args.get("url_contains") or "").strip()
    selector = (args.get("selector") or "").strip()
    text = (args.get("text") or "").strip()
    value = args.get("value")
    key = (args.get("key") or "").strip()
    timeout_raw = args.get("timeout_ms")
    try:
        timeout = _clamp_timeout_ms(timeout_raw)
    except ValueError as e:
        return ToolResult(ok=False, output="", error=str(e))

    need_new = action == "goto"
    page = pick_page(browser, url_contains, create_if_missing=need_new)
    if page is None:
        return ToolResult(
            ok=False, output="",
            error="Edge 里没有可操作的标签页。先用 action=goto 开一个，或在 Edge 里手动打开目标网站。",
        )
    # 2026-09-20 · 不再 bring_to_front：Playwright 全程走 CDP，点击/填表/截图都不依赖
    # OS 前台焦点；而它会 activateTarget → 把最小化的专属窗口还原并抢 用户 的前台
    # （实测坐实）。要看窗口时 用户 自己点任务栏即可。

    if action == "goto":
        url = (args.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            return ToolResult(ok=False, output="", error="goto 需要 http(s) 的 url")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=max(timeout, 30000))
            page.wait_for_timeout(1500)
        except Exception as e:
            return _fallback(page, action, f"打开失败: {type(e).__name__}: {e}")
        return ToolResult(ok=True, output=f"已打开 {page.url}\ntitle: {page.title()!r}")

    if action == "click":
        try:
            if selector:
                page.click(selector, timeout=timeout)
            elif text:
                page.get_by_text(text, exact=False).first.click(timeout=timeout)
            else:
                return ToolResult(ok=False, output="", error="click 需要 selector 或 text")
            page.wait_for_timeout(800)
        except Exception as e:
            return _fallback(page, action, f"点不到 {selector or text!r}: {type(e).__name__}")
        return ToolResult(ok=True, output=f"已点击 {selector or text!r} · 当前页 {page.url}")

    if action == "fill":
        if not selector:
            return ToolResult(ok=False, output="", error="fill 需要 selector（目标输入框）")
        try:
            page.fill(selector, str(value if value is not None else ""), timeout=timeout)
        except Exception as e:
            return _fallback(page, action, f"填不进 {selector!r}: {type(e).__name__}")
        return ToolResult(ok=True, output=f"已在 {selector!r} 填入 {str(value)[:60]!r}")

    if action == "upload":
        if not selector:
            return ToolResult(ok=False, output="", error="upload 需要 selector（<input type=file> 或上传输入框）")
        files = args.get("files")
        if files is None:
            files = value  # 兼容用 value 传单个路径
        if isinstance(files, str):
            files = [files]
        if not files:
            return ToolResult(ok=False, output="", error="upload 需要 files（本地文件路径，单个字符串或数组）")
        paths = []
        for f in files:
            p = Path(str(f))
            if not p.exists():
                return ToolResult(ok=False, output="", error=f"文件不存在: {f}")
            paths.append(str(p))
        try:
            page.set_input_files(selector, paths, timeout=timeout)
            page.wait_for_timeout(1200)
        except Exception as e:
            return _fallback(
                page, action,
                f"上传到 {selector!r} 失败: {type(e).__name__}"
                "（该站可能要先点开上传入口才出现 <input type=file>，或用拖拽；先 click 上传按钮再 upload）",
            )
        names = ", ".join(Path(p).name for p in paths)
        return ToolResult(ok=True, output=f"已上传 {len(paths)} 个文件到 {selector!r}: {names}")

    if action == "press":
        if not key:
            return ToolResult(ok=False, output="", error="press 需要 key（如 Enter / Control+A）")
        try:
            if selector:
                page.press(selector, key, timeout=timeout)
            else:
                page.keyboard.press(key)
            page.wait_for_timeout(500)
        except Exception as e:
            return _fallback(page, action, f"按键 {key!r} 失败: {type(e).__name__}")
        return ToolResult(ok=True, output=f"已按键 {key!r}")

    if action == "wait":
        try:
            if selector:
                page.wait_for_selector(selector, timeout=timeout)
                return ToolResult(ok=True, output=f"元素 {selector!r} 已出现")
            page.wait_for_timeout(timeout)
            return ToolResult(ok=True, output=f"已等待 {timeout}ms")
        except Exception as e:
            return _fallback(page, action, f"等不到 {selector!r}: {type(e).__name__}")

    if action == "eval":
        # 2026-10-01 (wish-94b2546b) · 执行自定义 JS 并回传结果。
        # 补上这个能力之前，验 UI 拿计算样式只能自己上 playwright + 猜 CDP 端口，
        # 结果连到了 用户 的主浏览器(9222)弹标签抢他前台。能力长在工具上，就不必自己找路。
        js = str(value or "").strip()
        if not js:
            return ToolResult(
                ok=False, output="",
                error=(
                    'eval 需要把 JS 放进 value 字段。例：value="document.title" · '
                    'value="() => getComputedStyle(document.body).color" · '
                    '多行要写成 IIFE：value="() => { const a=1; return a; }"'
                ),
            )
        try:
            raw = page.evaluate(js)
        except Exception as e:
            return _fallback(page, action, f"JS 执行失败: {type(e).__name__}: {e}")
        try:
            out = json.dumps(raw, ensure_ascii=False, default=str)
        except Exception:
            out = repr(raw)
        if len(out) > 8192:
            out = out[:8192] + f"...[截断·原长 {len(out)} 字符]"
        return ToolResult(ok=True, output=out)

    if action == "read":
        try:
            if selector:
                txt = page.inner_text(selector, timeout=timeout)
            else:
                txt = page.inner_text("body")
        except Exception as e:
            return _fallback(page, action, f"读不到内容: {type(e).__name__}")
        if len(txt) > 6000:
            txt = txt[:6000] + "\n…[truncated]"
        return ToolResult(ok=True, output=f"page: {page.url}\n---\n{txt}")

    if action == "inspect":
        try:
            controls = page.evaluate(_INSPECT_JS)
        except Exception as e:
            return _fallback(page, action, f"扫不到控件: {type(e).__name__}")
        if not controls:
            return ToolResult(ok=True, output=f"page: {page.url}\n（没扫到可见的可交互控件）")
        import json as _json
        body = _json.dumps(controls[:80], ensure_ascii=False, indent=1)
        return ToolResult(ok=True, output=f"page: {page.url}\n可交互控件（最多 80 个）:\n{body}")

    if action == "screenshot":
        shot = _save_shot(page, "view")
        if not shot:
            return _fallback(page, action, "截图失败")
        return ToolResult(ok=True, output=f"截图已存: {shot}\npage: {page.url}")

    if action == "download":
        try:
            dl_dir = _sandbox_dir(
                args.get("download_dir"),
                DOWNLOAD_ROOT / dt.date.today().isoformat(),
            )
        except ValueError as e:
            return ToolResult(ok=False, output="", error=str(e))
        try:
            with page.expect_download(timeout=max(timeout, 30000)) as info:
                if selector:
                    page.click(selector, timeout=timeout)
                elif text:
                    page.get_by_text(text, exact=False).first.click(timeout=timeout)
                else:
                    return ToolResult(ok=False, output="", error="download 需要触发下载的 selector 或 text")
            dl = info.value
            fname = Path(dl.suggested_filename or "download.bin").name
            out = (dl_dir / fname).resolve()
            out.relative_to(dl_dir.resolve())
            dl.save_as(str(out))
        except ValueError as e:
            return ToolResult(ok=False, output="", error=f"下载路径越界: {e}")
        except Exception as e:
            return _fallback(page, action, f"下载没触发/超时: {type(e).__name__}")
        return ToolResult(ok=True, output=f"已下载: {out}\n文件夹: {dl_dir}（可直接打开）")

    if action == "harvest":
        sel = selector or "img"
        prefix = _safe_prefix(args.get("name_prefix") or "img")
        try:
            srcs = page.eval_on_selector_all(
                sel, "els => els.map(e => e.currentSrc || e.src || '').filter(Boolean)"
            )
        except Exception as e:
            return _fallback(page, action, f"读不到 {sel!r} 的 src: {type(e).__name__}")
        seen: set[str] = set()
        urls = [s for s in srcs if s.startswith("http") and not (s in seen or seen.add(s))]
        if not urls:
            return _fallback(page, action, f"{sel!r} 没匹配到可下载的图/视频(src)")
        try:
            dl_dir = _sandbox_dir(
                args.get("download_dir"),
                DOWNLOAD_ROOT / dt.date.today().isoformat(),
            )
        except ValueError as e:
            return ToolResult(ok=False, output="", error=str(e))
        saved, failed = [], 0
        for u in urls:
            try:
                resp = page.request.get(u, timeout=max(timeout, 30000))
                if not resp.ok:
                    failed += 1
                    continue
                clean = u.split("?")[0].split("~")[0].lower()
                ext = next((e for e in _MEDIA_EXTS if clean.endswith(e)),
                           next((e for e in _MEDIA_EXTS if e in clean), ".jpg"))
                ts = dt.datetime.now().strftime("%H%M%S%f")
                out = dl_dir / f"{prefix}_{ts}{ext}"
                out.write_bytes(resp.body())
                saved.append(out.name)
            except Exception:
                failed += 1
        if not saved:
            return _fallback(page, action, f"匹配到 {len(urls)} 个 src 但全部下载失败")
        lines = [f"已收 {len(saved)} 个到 {dl_dir}（可直接打开）:"] + [f"  - {n}" for n in saved]
        if failed:
            lines.append(f"（另有 {failed} 个失败）")
        return ToolResult(ok=True, output="\n".join(lines))

    return ToolResult(ok=False, output="", error=f"未知 action: {action!r}")


# inspect 用：dump 页面上所有可见的可交互控件（纯文字结构，给文本模型探路用，不需视觉）
_INSPECT_JS = r"""
() => {
  const vis = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'
           && el.getAttribute('aria-hidden')!=='true';
  };
  const sels = 'a,button,input,textarea,select,[contenteditable="true"],[role="button"],[role="textbox"],[role="tab"],[type="file"]';
  const out = [];
  document.querySelectorAll(sels).forEach(el => {
    if (!vis(el)) return;
    const a = (n) => el.getAttribute(n) || '';
    out.push({
      tag: el.tagName.toLowerCase(),
      type: a('type'),
      text: (el.innerText || el.value || '').trim().slice(0, 40),
      placeholder: a('placeholder') || a('data-placeholder'),
      aria: a('aria-label'),
      id: el.id || '',
      cls: (el.className && el.className.toString) ? el.className.toString().slice(0, 70) : '',
      editable: a('contenteditable'),
    });
  });
  return out;
}
"""
