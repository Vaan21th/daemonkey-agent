"""workers/html_shot.py

把本地 HTML 原型渲成整页长图 —— 给「通道分发」用。

为什么需要它：微信 / 飞书里发 .html 文件等于没发（手机上只提示"用其他应用打开"，
微信下载目录浏览器还读不到）。发一张图，点开就能看。所以通道侧一律走图。

为什么不注册成工具：分发是 **daemon 层按通道自动做**的事，
不该变成「每次要记得调一下」——那就会漏。这里只提供函数。

自适应缩放：页面越长缩放越小，免得 1800×9000 的长图在手机上糊成一片。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _pick_scale(height: int) -> float:
    """页面越高，缩放越小（长图在手机上会被压，虚高没意义）"""
    if height <= 2200:
        return 2.0
    if height <= 5000:
        return 1.5
    return 1.0


def shot_html(
    path: str | Path,
    *,
    out_name: str = "",
    width: int = 900,
    scale: float | None = None,
    timeout_ms: int = 30000,
) -> str:
    """整页截图 · 返回 PNG 相对 ROOT 的路径（正斜杠）

    失败抛异常，由调用方兜（截图是增强，不该拖垮主业）。
    """
    from playwright.sync_api import sync_playwright

    from workers.host_bins import playwright_channels

    src = Path(path)
    if not src.is_absolute():
        src = ROOT / src
    if not src.is_file():
        raise FileNotFoundError(f"html not found: {src}")

    target = (src.parent / out_name).with_suffix(".png") if out_name else src.with_suffix(".png")
    uri = src.as_uri()

    with sync_playwright() as p:
        browser = None
        last_err = ""
        for ch in playwright_channels():
            kw: dict = {
                "headless": True,
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            if ch:
                kw["channel"] = ch
            try:
                browser = p.chromium.launch(**kw)
                break
            except Exception as e:  # 换下一个 channel 再试
                last_err = f"{type(e).__name__}: {e}"
        if browser is None:
            raise RuntimeError(f"launch browser failed: {last_err}")

        try:
            page = browser.new_page(
                viewport={"width": width, "height": 1200},
                device_scale_factor=scale or 1.5,
            )
            page.goto(uri, wait_until="load", timeout=timeout_ms)
            page.wait_for_timeout(250)  # 等字体/布局落定
            height = int(page.evaluate("() => document.documentElement.scrollHeight") or 0)
            if scale is None:
                page.close()
                page = browser.new_page(
                    viewport={"width": width, "height": 1200},
                    device_scale_factor=_pick_scale(height),
                )
                page.goto(uri, wait_until="load", timeout=timeout_ms)
                page.wait_for_timeout(250)
            page.screenshot(path=str(target), full_page=True)
        finally:
            try:
                browser.close()
            except Exception:
                pass

    return str(target.relative_to(ROOT)).replace("\\", "/")
