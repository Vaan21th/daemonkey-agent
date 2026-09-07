"""叠层 MOD 运行时 · data/mods + agent_tools_user + api_routes_user。

官方内核文件不当魔改面。用户/社区改动写在这些目录里，update_core 白名单
不含它们 → 升级原样保留。后加载遮蔽官方同名工具。
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
MODS_DIR = ROOT / "data" / "mods"
USER_TOOLS = ROOT / "agent_tools_user"
USER_ROUTES = ROOT / "api_routes_user"
_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}$")
_loaded_tools = False

_README_MODS = """\
# data/mods · 叠层 MOD（官方升级永不覆盖）

每个子目录一个 MOD：
  mod.json     {id,name,version,author,description,enabled}
  tools/*.py   工具（from agent_tools import register_tool, ToolSpec …）
  routes/*.py  FastAPI router（export router = APIRouter()）
  ui/mod.js    前端（Daemonkey.addDomain / 官方钩子）
  ui/mod.css

打包装给别人：对话里说「导出 MOD <id>」。装别人的：导入那个 .dkpkg。
"""

_README_TOOLS = """\
# agent_tools_user · 本机工具叠层

官方升级不碰这里。同名工具会盖住官方那个。
写法：from agent_tools import register_tool, ToolSpec, ToolResult, TIER_AUTO
想分享到市集 → 挪进 data/mods/<id>/tools/ 再导出 MOD。
"""

_README_ROUTES = """\
# api_routes_user · 本机路由叠层

官方升级不碰这里。模块 export router = APIRouter() 即挂上。
不要占用 /dashboard/{任意}，那条会被官方通配吞掉。用 /mod/<你的id>/…
"""


def sanitize_id(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]+", "_", str(s or "").strip())
    s = s.strip("._-")[:40]
    return s or "mod"


def ensure_overlay_dirs(root: Optional[Path] = None) -> list[str]:
    """缺目录/说明才写，有字不碰。"""
    base = root or ROOT
    created: list[str] = []
    pairs = (
        (base / "data" / "mods" / "README.md", _README_MODS),
        (base / "agent_tools_user" / "README.md", _README_TOOLS),
        (base / "api_routes_user" / "README.md", _README_ROUTES),
    )
    for path, text in pairs:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(text, encoding="utf-8")
                created.append(str(path.relative_to(base)).replace("\\", "/"))
        except Exception:
            pass
    return created


def _mod_json(folder: Path) -> dict:
    p = folder / "mod.json"
    meta = {}
    if p.is_file():
        try:
            meta = json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception:
            meta = {}
    if not isinstance(meta, dict):
        meta = {}
    mid = sanitize_id(str(meta.get("id") or folder.name))
    meta.setdefault("id", mid)
    meta.setdefault("name", mid)
    meta.setdefault("version", "1.0.0")
    meta.setdefault("enabled", True)
    return meta


def list_mods(root: Optional[Path] = None) -> list[dict]:
    base = (root or ROOT) / "data" / "mods"
    if not base.is_dir():
        return []
    out = []
    for folder in sorted(base.iterdir()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        if folder.name == "__pycache__":
            continue
        meta = _mod_json(folder)
        if meta.get("enabled") is False:
            meta["enabled"] = False
        else:
            meta["enabled"] = True
        ui = folder / "ui"
        js = ui / "mod.js"
        css = ui / "mod.css"
        meta["path"] = str(folder)
        meta["js"] = f"/mod-assets/{meta['id']}/mod.js" if js.is_file() else ""
        meta["css"] = f"/mod-assets/{meta['id']}/mod.css" if css.is_file() else ""
        out.append(meta)
    return out


def enabled_names(root: Optional[Path] = None) -> list[str]:
    return [m["id"] for m in list_mods(root) if m.get("enabled")]


def set_enabled(mod_id: str, enabled: bool, *, root: Optional[Path] = None
                ) -> tuple[bool, str]:
    mid = sanitize_id(mod_id)
    folder = (root or ROOT) / "data" / "mods" / mid
    if not folder.is_dir():
        return False, f"找不到 MOD: {mid}"
    meta = _mod_json(folder)
    meta["enabled"] = bool(enabled)
    (folder / "mod.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if enabled:
        return True, f"已启用 MOD `{mid}`。刷新页面加载 UI；重启 daemon 后工具/路由才挂上。"
    return True, (
        f"已停用 MOD `{mid}`。刷新页面后 UI 不再加载；"
        f"重启 daemon 后工具/路由不再叠，官方行为回来。"
    )


def _iter_py(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("*.py") if not p.name.startswith("_"))


def iter_tool_files(root: Optional[Path] = None) -> list[tuple[str, Path]]:
    """官方之后加载：先 MOD（id 序），再本机 agent_tools_user（最后赢）。"""
    base = root or ROOT
    out: list[tuple[str, Path]] = []
    for m in list_mods(base):
        if not m.get("enabled"):
            continue
        mid = m["id"]
        for p in _iter_py(Path(m["path"]) / "tools"):
            out.append((f"dk_mod_{mid}_{p.stem}", p))
    for p in _iter_py(base / "agent_tools_user"):
        out.append((f"dk_user_tool_{p.stem}", p))
    return out


def iter_route_files(root: Optional[Path] = None) -> list[tuple[str, Path]]:
    base = root or ROOT
    out: list[tuple[str, Path]] = []
    for p in _iter_py(base / "api_routes_user"):
        out.append((f"dk_user_route_{p.stem}", p))
    for m in list_mods(base):
        if not m.get("enabled"):
            continue
        mid = m["id"]
        for p in _iter_py(Path(m["path"]) / "routes"):
            out.append((f"dk_mod_{mid}_route_{p.stem}", p))
    return out


def _exec_py(qualname: str, path: Path):
    spec = importlib.util.spec_from_file_location(qualname, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[qualname] = mod
    spec.loader.exec_module(mod)
    return mod


def load_tool_overlays(root: Optional[Path] = None) -> list[str]:
    """幂等。遮蔽官方同名工具。"""
    global _loaded_tools
    if _loaded_tools and root is None:
        return []
    import agent_tools as at
    from agent_tools._desc_budget import assert_description_budget, assert_schema_budget

    shadowed: list[str] = []

    def _overlay_register(spec):
        if spec.tier not in (at.TIER_AUTO, at.TIER_CONFIRM, at.TIER_GUARD):
            raise ValueError(f"invalid tier: {spec.tier}")
        assert_description_budget(spec.name, spec.description)
        assert_schema_budget(spec.name, spec.input_schema)
        if spec.name in at.REGISTRY:
            shadowed.append(spec.name)
        at.REGISTRY[spec.name] = spec
        return spec

    orig = at.register_tool
    at.register_tool = _overlay_register
    failures = []
    try:
        for qual, path in iter_tool_files(root):
            try:
                _exec_py(qual, path)
            except Exception as e:
                failures.append(f"{path.name}: {type(e).__name__}: {e}")
    finally:
        at.register_tool = orig
    if root is None:
        _loaded_tools = True
    if failures:
        print("[mod_runtime] tool overlay skip: " + " | ".join(failures[:4]),
              file=sys.stderr, flush=True)
    return shadowed
