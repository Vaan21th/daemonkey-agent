"""api_routes/picker.py · 系统文件 / 目录选择器（就是 Windows 资源管理器那个对话框）

为什么单独一个模块
------------------
2026-09-30 BRO 做了知识库的「添加文件/文件夹」需求，明确要求
「知识库不要代码分叉，能复用直接复用」。
而「拉系统选择器」这件事 projects.py 里已经有一份了（/api/projects/pick-folder）——
与其再抄第二份，不如把它抽到这里：**一个实现，多处引用**。
projects.py 现在转发到本模块；以后谁还要选目录/选文件，也走这里。

两个铁律（从 projects.py 原文搬来，别丢）
-----------------------------------------
⚠ 只在【本机】访问时可用：对话框开在 daemon 那台机器的桌面上，
  远程（手机 / 隧道）请求根本看不见它，会挂在那里干等到超时。
  所以远程直接返回 {ok: False, remote: True}，让前端退回手输路径。
⚠ 必须子进程跑：不只是阻塞问题 —— tkinter 必须占主线程。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, Request

router = APIRouter(include_in_schema=False)

# 两个脚本共用一个模板：只是最后调 filedialog 的方法不同。
# 中文目录名不能靠 cp936 赌 → 显式 reconfigure utf-8。
_PICK_TMPL = (
    "import sys, tkinter as tk\n"
    "from tkinter import filedialog\n"
    "try:\n"
    "    sys.stdout.reconfigure(encoding='utf-8')\n"
    "except Exception:\n"
    "    pass\n"
    "r = tk.Tk()\n"
    "r.withdraw()\n"
    "try:\n"
    "    r.attributes('-topmost', True)\n"
    "except Exception:\n"
    "    pass\n"
    "init = sys.argv[1] if len(sys.argv) > 1 else ''\n"
    "res = {CALL}\n"
    "print('\\n'.join(res) if isinstance(res, (tuple, list)) else (res or ''))\n"
)

_FOLDER_CALL = "filedialog.askdirectory(title='选一个目录 · OPUS', initialdir=(init or None))"
_FILES_CALL = (
    "filedialog.askopenfilenames(title='选要加进去的文件 · OPUS（可多选）', initialdir=(init or None))"
)

# 兼容老引用：projects.py 以前把这段叫 _PICK_SCRIPT
_PICK_SCRIPT = _PICK_TMPL.format(CALL=_FOLDER_CALL)


def _is_local(request: Request) -> bool:
    from api_routes._deps import _client_is_local_machine
    return _client_is_local_machine(request)


async def _run_picker(call: str, initial: str = "", timeout: int = 240) -> dict:
    """拉一次系统选择器。返回 {ok, path} / {ok, paths} · 取消 → cancelled。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", _PICK_TMPL.format(CALL=call), initial,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"拉不起选择器：{e}"}

    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "error": f"等了 {timeout // 60} 分钟没人选 · 再试一次或直接手输路径"}

    if proc.returncode != 0:
        return {
            "ok": False,
            "error": "选择器没起来（这台机器没有桌面会话？）· 请手输路径",
            "detail": (err or b"").decode("utf-8", "replace").strip()[-300:],
        }
    lines = [ln.strip() for ln in (out or b"").decode("utf-8", "replace").splitlines() if ln.strip()]
    return {"ok": True, "lines": lines}


@router.post("/api/pick/folder")
async def pick_folder(request: Request, initial: str = "", authorization: Optional[str] = Header(None)):
    """拉系统目录选择器 · 返回 {ok, path}"""
    from api_routes._deps import check_auth
    check_auth(authorization)
    if not _is_local(request):
        return {"ok": False, "remote": True, "error": "远程接入弹不出这台机器的选择器 · 请直接手输路径"}

    r = await _run_picker(_FOLDER_CALL, initial)
    if not r.get("ok"):
        return r
    path = (r.get("lines") or [""])[-1]
    if not path:
        return {"ok": False, "cancelled": True, "error": "没选（取消了）"}
    return {"ok": True, "path": path}


@router.post("/api/pick/files")
async def pick_files(request: Request, initial: str = "", authorization: Optional[str] = Header(None)):
    """拉系统文件选择器（可多选）· 返回 {ok, paths: [...]}

    BRO 2026-09-30：「我想让他能用类似我得项目 - 添加一个项目，那个逻辑，
    来选择文件夹或者选择文件」—— 这是那个「选文件」的一半，跟 pick/folder 同源。
    """
    from api_routes._deps import check_auth
    check_auth(authorization)
    if not _is_local(request):
        return {"ok": False, "remote": True, "error": "远程接入弹不出这台机器的选择器 · 请直接手输路径"}

    r = await _run_picker(_FILES_CALL, initial)
    if not r.get("ok"):
        return r
    paths = [p for p in (r.get("lines") or []) if p]
    if not paths:
        return {"ok": False, "cancelled": True, "error": "没选（取消了）"}
    return {"ok": True, "paths": paths}


def scan_importable(path: Path, *, recursive: bool = True, limit: int = 800) -> dict:
    """把一个目录扫成「可灌进知识库的文件清单」。

    为什么放这儿而不是 knowledge.py：它跟「用户选了个文件夹」是同一条链路的下半段，
    前端选完文件夹直接拿这个结果预览「将加入 N 篇」，再决定灌不灌。
    只认 doc_ingest.SUPPORTED_EXT，别的后缀（图/视频/压缩包）直接跳过、不报错。
    """
    from workers.doc_ingest import SUPPORTED_EXT

    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": f"路径不存在: {p}"}
    if p.is_file():
        return {"ok": True, "files": [str(p)] if p.suffix.lower() in SUPPORTED_EXT else [],
                "skipped": 0 if p.suffix.lower() in SUPPORTED_EXT else 1}

    it = p.rglob("*") if recursive else p.glob("*")
    files, skipped, truncated = [], 0, False
    for f in it:
        try:
            if not f.is_file():
                continue
        except OSError:
            continue
        if f.suffix.lower() in SUPPORTED_EXT:
            if len(files) >= limit:
                truncated = True
                break
            files.append(str(f))
        else:
            skipped += 1
    return {"ok": True, "files": files, "skipped": skipped, "truncated": truncated}
