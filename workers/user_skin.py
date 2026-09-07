# -*- coding: utf-8 -*-
"""装修区空默认 · 缺了才补，有字绝不碰。

0.9.6 把 user.js / user.css 标 never_sync，升级物理不拉。页面却写死要加载它们。
官方包只带 EXAMPLES.js → 老用户升级、官方新装都会 404。
boot-guard 还把这次 404 记成核心失败。

本模块只做一件事：启动时磁盘没有才落下官方空壳。用户已经写过的文件原样留着。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USER_DIR = ROOT / "static" / "user"

DEFAULT_JS = """\
/* static/user/user.js · 这文件归你 · 官方升级永不覆盖
 * 想加面板 / 改侧栏 · 抄同目录 EXAMPLES.js，或直接跟 Daemonkey 说。
 */
"""

DEFAULT_CSS = """\
/* static/user/user.css · 这文件归你 · 官方升级永不覆盖
 * 写覆盖层即可。空着也不影响官方默认样式。
 */
"""

_DEFAULTS = (
    ("user.js", DEFAULT_JS),
    ("user.css", DEFAULT_CSS),
)


def ensure_user_skin_defaults(root: Path | None = None) -> list[str]:
    """缺才写。返回本次新建的文件名。失败不抛，不挡启动。"""
    created: list[str] = []
    base = (root or ROOT) / "static" / "user"
    try:
        base.mkdir(parents=True, exist_ok=True)
        for name, body in _DEFAULTS:
            path = base / name
            if path.exists():
                continue
            path.write_text(body, encoding="utf-8")
            created.append(name)
    except Exception as e:
        print(f"[user_skin] WARN · 补空默认跳过 (不阻塞启动): {type(e).__name__}: {e}", flush=True)
        return []
    if created:
        print("[user_skin] 装修区缺文件 · 已补空默认: " + " · ".join(created), flush=True)
    return created
