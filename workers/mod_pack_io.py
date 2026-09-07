"""MOD .dkpkg 打包/解包。路径约束与 zip slip 闸在这里。"""
from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path
from typing import Optional

from workers.mod_runtime import ROOT, _ID_RE, _mod_json, sanitize_id


def safe_members(z: zipfile.ZipFile) -> list[str]:
    allow_prefix = ("tools/", "routes/", "ui/")
    allow_exact = {"manifest.json", "mod.json", "README.md"}
    names = []
    for n in z.namelist():
        n = n.replace("\\", "/")
        if n.endswith("/"):
            continue
        if ".." in n.split("/") or n.startswith("/"):
            raise ValueError(f"包内路径非法: {n}")
        if n in allow_exact or n.startswith(allow_prefix):
            if Path(n).suffix.lower() in {".exe", ".dll", ".ps1", ".bat", ".cmd"}:
                raise ValueError(f"拒绝可执行文件: {n}")
            names.append(n)
            continue
        raise ValueError(f"MOD 包不允许这个路径: {n}")
    return names


def export_zip(mod_id: str, *, author: str = "", version: str = "",
               description: str = "", root: Optional[Path] = None) -> tuple[Optional[Path], str]:
    base = root or ROOT
    mid = sanitize_id(mod_id)
    folder = base / "data" / "mods" / mid
    if not folder.is_dir():
        return None, f"找不到 MOD: data/mods/{mid}"
    meta = _mod_json(folder)
    ver = version or str(meta.get("version") or "1.0.0")
    files: list[tuple[str, Path]] = []
    for p in folder.rglob("*"):
        if not p.is_file():
            continue
        rel = str(p.relative_to(folder)).replace("\\", "/")
        if rel.startswith(".") or "__pycache__" in rel.split("/"):
            continue
        files.append((rel, p))
    if not files:
        return None, f"MOD {mid} 是空目录"
    dest_dir = base / "data" / "workshop" / "exports"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{mid}-{ver}.dkpkg"
    manifest = {
        "dkpkg_version": 1,
        "kind": "mod",
        "id": mid,
        "name": meta.get("name") or mid,
        "version": ver,
        "description": description or str(meta.get("description") or ""),
        "author": author or str(meta.get("author") or ""),
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "files": [a for a, _ in files],
    }
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for arc, p in files:
            if arc == "manifest.json":
                continue
            z.write(p, arc)
    return dest, ""


def import_zip(path: Path, *, overwrite: bool = False, root: Optional[Path] = None
               ) -> tuple[bool, str]:
    base = root or ROOT
    mid = "mod"
    try:
        with zipfile.ZipFile(path) as z:
            if "manifest.json" not in z.namelist():
                return False, "不是合法 .dkpkg: 缺 manifest.json"
            manifest = json.loads(z.read("manifest.json").decode("utf-8"))
            if str(manifest.get("kind") or "").lower() != "mod":
                return False, "这不是 MOD 包（kind 必须是 mod）"
            names = safe_members(z)
            mid = sanitize_id(str(manifest.get("id") or manifest.get("name") or ""))
            if "mod.json" in z.namelist():
                try:
                    body = json.loads(z.read("mod.json").decode("utf-8"))
                    mid = sanitize_id(str(body.get("id") or mid))
                except Exception:
                    pass
            if not _ID_RE.match(mid):
                return False, f"非法 MOD id: {mid}"
            dest = base / "data" / "mods" / mid
            if dest.exists() and not overwrite:
                return False, f"已有 MOD `{mid}` · 确认覆盖请 overwrite=true"
            dest.mkdir(parents=True, exist_ok=True)
            dest_real = dest.resolve()
            for member in names:
                if member == "manifest.json":
                    continue
                target = (dest_real / member).resolve()
                target.relative_to(dest_real)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(member))
            mj = dest / "mod.json"
            if not mj.exists():
                mj.write_text(json.dumps({
                    "id": mid, "name": manifest.get("name") or mid,
                    "version": manifest.get("version") or "1.0.0",
                    "author": manifest.get("author") or "",
                    "description": manifest.get("description") or "",
                    "enabled": True,
                }, ensure_ascii=False, indent=2), encoding="utf-8")
    except zipfile.BadZipFile:
        return False, "文件损坏: 不是合法 zip"
    except ValueError as e:
        return False, str(e)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    return True, (
        f"已安装 MOD `{mid}` → data/mods/{mid}/ "
        "（重启 daemon 后工具/路由生效，前端刷新即可）"
    )
