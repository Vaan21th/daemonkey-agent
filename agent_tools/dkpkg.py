"""agent_tools/dkpkg.py
===================================

0.9.7 · .dkpkg 导入/导出 (母本 9.2 一阶段 · 文件级流通)

一句话: 把工坊 app / flow / 皮肤打成一个 .dkpkg (zip) 文件 · 别人导入即装 ——
群/论坛流通的最小闭环 · 官方精选站和用户市场都建立在这个格式上。

包结构 (zip):
  manifest.json   {dkpkg_version, kind, name, version, description, author, exported_at, files[]}
  + 资产文件 (app→app.json · flow→flow.json · skin→skin.json+style.css+图)

落位规则:
  app  → data/workshop/apps/<id>.json
  flow → data/workshop/flows/<id>.json
  skin → static/user/skins/<name>/   (装修区 · 官方升级永不覆盖)

安全边界:
  - manifest 缺失/kind 非法 → 拒装
  - 同名冲突 → 默认拒装 · 显式 overwrite=true 才覆盖 (import 是 CONFIRM 级)
  - zip 内路径必须全部落在包内 (防 zip slip 穿越)
"""

from __future__ import annotations

import json
import re
import time
import zipfile
from pathlib import Path

from . import REGISTRY, TIER_AUTO, TIER_CONFIRM, ToolResult, ToolSpec, register_tool

_DKPKG_VERSION = 1


def _sanitize_asset_name(s) -> str:
    """防路径穿越: 去路径分隔符 / .. 段 · 保留中文/字母/数字/._- · 空回 'asset'。"""
    s = str(s or "").strip().replace("\\", "/")
    s = re.sub(r"[^A-Za-z0-9_\u4e00-\u9fff.\-]", "_", s)
    s = re.sub(r"\.{2,}", ".", s)
    s = s.strip(".")
    return s or "asset"


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _exports_dir() -> Path:
    d = _root() / "data" / "workshop" / "exports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _find_asset(kind: str, name: str) -> tuple:
    """按 kind+name 找资产。 返回 (files: list[(arcname, abs_path)], meta: dict) 或 (None, error)。"""
    root = _root()
    if kind == "app":
        from workers.workshop_assets import list_apps
        for a in list_apps():
            if a.get("id") == name or a.get("name") == name:
                p = root / "data" / "workshop" / "apps" / f"{a['id']}.json"
                if p.exists():
                    return [("app.json", p)], {"name": a.get("name") or a["id"], "desc": a.get("description") or ""}
                return None, f"app {name} 的定义文件不存在: {p.name}"
        return None, f"找不到 app: {name} (用 list_apps 看现有 id)"
    if kind == "flow":
        from workers.workshop_assets import list_flows
        for f in list_flows():
            if f.get("id") == name or f.get("name") == name:
                p = root / "data" / "workshop" / "flows" / f"{f['id']}.json"
                if p.exists():
                    return [("flow.json", p)], {"name": f.get("name") or f["id"], "desc": f.get("description") or ""}
                return None, f"flow {name} 的定义文件不存在: {p.name}"
        return None, f"找不到 flow: {name} (用 list_flows 看现有 id)"
    if kind == "skin":
        name = _sanitize_asset_name(name)
        d = root / "static" / "user" / "skins" / name
        if not d.is_dir():
            return None, f"找不到皮肤: static/user/skins/{name}/ (每皮肤一个文件夹: skin.json + style.css + 图)"
        files = []
        for f in sorted(d.rglob("*")):
            if f.is_file():
                files.append((str(f.relative_to(d)).replace("\\", "/"), f))
        if not any(a == "skin.json" for a, _ in files):
            return None, f"皮肤 {name} 缺 skin.json 清单 (名称/作者/预览/日夜变体)"
        return files, {"name": name, "desc": ""}
    return None, f"kind 必须是 app / flow / skin (你给的: {kind})"


def _export(args: dict) -> ToolResult:
    kind = str(args.get("kind") or "").strip().lower()
    name = str(args.get("name") or "").strip()
    if not kind or not name:
        return ToolResult(ok=False, output="", error="kind (app/flow/skin) + name 都必填")

    files, meta_or_err = _find_asset(kind, name)
    if files is None:
        return ToolResult(ok=False, output="", error=meta_or_err)

    manifest = {
        "dkpkg_version": _DKPKG_VERSION,
        "kind": kind,
        "name": meta_or_err.get("name") or name,
        "version": str(args.get("version") or "1.0.0"),
        "description": str(args.get("description") or meta_or_err.get("desc") or ""),
        "author": str(args.get("author") or ""),
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "files": [a for a, _ in files],
    }
    safe_name = "".join(c if (c.isalnum() or c in "-_") else "_" for c in (manifest["name"] or name))
    out = _exports_dir() / f"{safe_name}-{manifest['version']}.dkpkg"
    try:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for arc, p in files:
                z.write(p, arc)
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"打包失败: {type(e).__name__}: {e}")

    size_kb = out.stat().st_size // 1024
    return ToolResult(
        ok=True,
        output=(f"已打包: `{out.relative_to(_root())}` ({size_kb} KB · {len(files)} 个文件)\n"
                f"manifest: {kind} 「{manifest['name']}」 v{manifest['version']}\n"
                f"分享方式: 把这个文件发给对方 → 对方说「导入 dkpkg <路径>」即装"),
    )


def _safe_extract(z: zipfile.ZipFile, dest: Path) -> None:
    """防 zip slip: 包内每个成员路径必须落在 dest 内。"""
    dest_real = dest.resolve()
    for member in z.namelist():
        target = (dest_real / member).resolve()
        try:
            target.relative_to(dest_real)
        except ValueError:
            raise ValueError(f"包内路径越界 (zip slip): {member}")
    z.extractall(dest_real)


def _import(args: dict) -> ToolResult:
    raw_path = str(args.get("path") or "").strip()
    overwrite = bool(args.get("overwrite"))
    if not raw_path:
        return ToolResult(ok=False, output="", error="path 必填 (.dkpkg 文件路径)")
    p = (_root() / raw_path).resolve() if not Path(raw_path).is_absolute() else Path(raw_path)
    if not p.exists():
        return ToolResult(ok=False, output="", error=f"文件不存在: {raw_path}")

    try:
        with zipfile.ZipFile(p) as z:
            if "manifest.json" not in z.namelist():
                return ToolResult(ok=False, output="", error="不是合法 .dkpkg: 缺 manifest.json")
            manifest = json.loads(z.read("manifest.json").decode("utf-8"))
            kind = str(manifest.get("kind") or "").lower()
            name = str(manifest.get("name") or "").strip()
            if kind not in ("app", "flow", "skin") or not name:
                return ToolResult(ok=False, output="", error=f"manifest 非法: kind={kind} name={name}")
            name = _sanitize_asset_name(name)

            root = _root()
            if kind == "skin":
                dest = root / "static" / "user" / "skins" / name
            else:
                dest = root / "data" / "workshop" / (kind + "s")
            # app/flow: 落位文件名用包内定义的 id (不是显示名) · 防同 app 两份文件
            asset_id = name
            if kind in ("app", "flow"):
                src_name0 = "app.json" if kind == "app" else "flow.json"
                if src_name0 not in z.namelist():
                    return ToolResult(ok=False, output="", error=f"包内缺 {src_name0}")
                try:
                    _body0 = json.loads(z.read(src_name0).decode("utf-8"))
                    asset_id = _sanitize_asset_name(str(_body0.get("id") or name))
                except Exception:
                    asset_id = name
            target_file = dest / (f"{asset_id}.json" if kind in ("app", "flow") else "skin.json")
            if target_file.exists() and not overwrite:
                return ToolResult(
                    ok=False, output="",
                    error=f"已存在同名 {kind} 「{name}」· 确认覆盖请 overwrite=true (会备份原文件)",
                )

            # 覆盖前备份
            if target_file.exists():
                bak = target_file.with_suffix(target_file.suffix + f".bak-{int(time.time())}")
                try:
                    target_file.rename(bak)
                except Exception as e:
                    return ToolResult(
                        ok=False, output="",
                        error=f"覆盖前备份失败，已中止导入（原文件未动）: {type(e).__name__}: {e}",
                    )

            dest.mkdir(parents=True, exist_ok=True)
            if kind == "skin":
                _safe_extract(z, dest)
            else:
                # app/flow: 包内 app.json/flow.json → 落位 <name>.json
                src_name = "app.json" if kind == "app" else "flow.json"
                if src_name not in z.namelist():
                    return ToolResult(ok=False, output="", error=f"包内缺 {src_name}")
                data = z.read(src_name)
                # 校验是合法 json 且 id 与 name 对齐
                try:
                    body = json.loads(data.decode("utf-8"))
                    body.setdefault("id", name)
                    data = json.dumps(body, ensure_ascii=False, indent=2).encode("utf-8")
                except Exception:
                    pass
                target_file.write_bytes(data)

    except zipfile.BadZipFile:
        return ToolResult(ok=False, output="", error="文件损坏: 不是合法 zip")
    except ValueError as e:
        return ToolResult(ok=False, output="", error=str(e))
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"导入失败: {type(e).__name__}: {e}")

    ver = manifest.get("version") or "?"
    author = manifest.get("author") or "佚名"
    where = target_file.parent.relative_to(_root())
    extra = ""
    if kind == "skin":
        extra = "\n皮肤已注册到装修区 · 说「换上 XXX 皮肤」或到设置页选 (官方升级永不覆盖)"
    return ToolResult(
        ok=True,
        output=(f"已安装 {kind} 「{name}」 v{ver} (作者: {author}) → `{where}/`{extra}"),
    )


def _list(args: dict) -> ToolResult:
    d = _exports_dir()
    pkgs = sorted(d.glob("*.dkpkg"), key=lambda f: -f.stat().st_mtime)
    if not pkgs:
        return ToolResult(ok=True, output="还没有导出过 .dkpkg 包 (用 export_dkpkg 打包 app/flow/皮肤)")
    lines = ["# 已导出的 .dkpkg 包", ""]
    for f in pkgs:
        lines.append(f"- `{f.name}` · {f.stat().st_size // 1024} KB · "
                     f"{time.strftime('%m-%d %H:%M', time.localtime(f.stat().st_mtime))}")
    lines.append(f"\n目录: `data/workshop/exports/` · 直接发文件给别人即可")
    return ToolResult(ok=True, output="\n".join(lines))


register_tool(ToolSpec(
    name="export_dkpkg",
    description=(
        "把一个工坊 app / flow / 皮肤打包成 .dkpkg 文件 (zip · 可分享 · 别人导入即装)。\n\n"
        "**用法**: kind=app/flow/skin + name (app/flow 的 id 或名称 · 皮肤的文件夹名)\n"
        "可选: version (默认 1.0.0) / description / author\n"
        "产物在 data/workshop/exports/<名>-<版本>.dkpkg · 直接发文件即可流通。\n\n"
        "**tier**: AUTO · 只读资产+写导出目录"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "kind": {"type": "string", "description": "app / flow / skin"},
            "name": {"type": "string", "description": "app/flow 的 id 或名称 · 皮肤的文件夹名 (static/user/skins/<名>/)"},
            "version": {"type": "string", "description": "可选 · 版本号 · 默认 1.0.0"},
            "description": {"type": "string", "description": "可选 · 一句话介绍"},
            "author": {"type": "string", "description": "可选 · 作者署名"},
        },
        "required": ["kind", "name"],
    },
    run=_export,
    summarize=lambda args: f"导出 {args.get('kind')}/{args.get('name')} 为 .dkpkg",
))

register_tool(ToolSpec(
    name="import_dkpkg",
    description=(
        "导入一个 .dkpkg 包 (别人分享的 app/flow/皮肤) · 校验 manifest → 落位 → 可用。\n\n"
        "**用法**: path=.dkpkg 文件路径 (相对工程根或绝对路径)\n"
        "同名冲突默认拒装 · overwrite=true 才覆盖 (自动备份原文件)。\n"
        "皮肤装进 static/user/skins/<名>/ (装修区 · 官方升级永不覆盖)。\n\n"
        "**tier**: CONFIRM · 往工程里装东西要你拍一下"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": ".dkpkg 文件路径"},
            "overwrite": {"type": "boolean", "description": "同名冲突时是否覆盖 (默认否 · 覆盖前自动备份)"},
        },
        "required": ["path"],
    },
    run=_import,
    summarize=lambda args: f"导入 .dkpkg: {args.get('path')}",
))

register_tool(ToolSpec(
    name="list_dkpkg",
    description="列出已导出的 .dkpkg 包 (data/workshop/exports/)。 **tier**: AUTO · 只读",
    tier=TIER_AUTO,
    input_schema={"type": "object", "properties": {}, "required": []},
    run=_list,
    summarize=lambda args: "列出已导出的 .dkpkg 包",
))
