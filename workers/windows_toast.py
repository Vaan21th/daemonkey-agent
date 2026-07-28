"""workers/windows_toast.py
Windows 系统 toast 通知 · 事项 B (wish-fb6b7427 · 2026-07-28)

依赖 winotify (pip install winotify · 纯 ctypes · 零额外依赖)。
调用前先读 notification_config 的 windows_toast 开关——关了直接 noop。

用法:
    from workers.windows_toast import send_toast
    send_toast("OPUS", "干完了 · 通知体系上线")
"""

from __future__ import annotations

import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICON_PATH = ROOT / "static" / "favicon.ico"

logger = logging.getLogger(__name__)


def _is_enabled() -> bool:
    """读通知配置 · 看 windows_toast 是否开启。任何异常 → False (保守关)。"""
    try:
        from workers.notification_config import load_notification_config
        cfg = load_notification_config()
        return bool(cfg.get("windows_toast", False))
    except Exception:
        return False


def send_toast(title: str, body: str, duration: str = "short") -> None:
    """弹 Windows 系统通知。开关关了 / 库没装 / 任何异常 → 静默吞掉。

    通知是装饰 · 不能拖累主流程——daemon_api 里调用方也包了 try/except，
    所以这里即使抛异常也不影响 turn——但自己吞更干净。
    """
    if not _is_enabled():
        return

    try:
        import winotify
    except ImportError:
        logger.debug("winotify not installed, toast skipped")
        return

    try:
        # app_id 写 Daemonkey · Windows 通知中心按此分组
        app_id = "Daemonkey"
        title = (title or "OPUS").strip()[:120]
        body = (body or "").strip()[:200]

        icon = str(ICON_PATH) if ICON_PATH.exists() else ""

        toast = winotify.Notification(
            app_id=app_id,
            title=title,
            msg=body,
            icon=icon,
            duration=duration,
        )
        toast.show()
    except Exception:
        # toast 失败不抛——最差情况就是没弹通知 · 主流程不受影响
        pass
