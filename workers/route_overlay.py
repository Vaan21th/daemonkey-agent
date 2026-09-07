"""官方清单外的 router + 用户/MOD 路由自动挂上。

官方 include 顺序仍由 daemon_api 手写（dashboard 通配必须靠后）。
这里只挂：漏登记的 api_routes 模块、api_routes_user、data/mods/*/routes。
"""
from __future__ import annotations

import importlib
from pathlib import Path

from workers.mod_runtime import _exec_py, iter_route_files

ROOT = Path(__file__).resolve().parent.parent


def include_overlay_routers(app, already: set[str]) -> list[str]:
    """返本次新挂上的模块名。单模块失败不拖垮启动。"""
    mounted: list[str] = []
    taken = set(already)
    routes_dir = ROOT / "api_routes"
    if routes_dir.is_dir():
        for p in sorted(routes_dir.glob("*.py")):
            name = p.stem
            if name.startswith("_") or name in taken:
                continue
            try:
                mod = importlib.import_module(f"api_routes.{name}")
                router = getattr(mod, "router", None)
                if router is None:
                    continue
                app.include_router(router)
                taken.add(name)
                mounted.append(name)
            except Exception:
                continue
    for qual, path in iter_route_files():
        try:
            mod = _exec_py(qual, path)
            router = getattr(mod, "router", None)
            if router is None:
                continue
            app.include_router(router)
            mounted.append(qual)
        except Exception:
            continue
    return mounted
