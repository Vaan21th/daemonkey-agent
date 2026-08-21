"""官方基线指纹 —— 判断内核文件"用户改过没有"的唯一可靠依据。

为什么需要它 (git status 的死角):
    升级保护原本靠 `git status --porcelain` 认用户魔改。 但 git status 只看
    【工作区 vs 最后一次 commit】· 而 commit 随时会发生 —— daemon 自己的
    checkpoint、用户手动 commit、别的工具落袋 —— 任何一次都会让 status 变干净。
    于是:

        用户改了 chat.js  →  某次 commit 把它落盘  →  工作区干净
        →  下次 update_core 认为「他没改过」 →  不备份·直接覆盖
        →  用户的改动只剩在 git 历史里·而他不一定懂 git

    指纹免疫这件事: 官方发布时把每个内核文件的内容 hash 钉进 core_fingerprints.json ·
    用户机器上拿实际内容比对 —— 【跟官方不一样就是用户改过】· 跟 commit 了几次无关。

基线怎么前进:
    core_fingerprints.json 自己也在白名单里。 update_core 覆盖内核文件的同时
    也把它换成新版 → 新内容对新基线·自动归零。 用户之后再改·又能被认出来。

归一化换行是必须的:
    git 在 Windows 上可能按 autocrlf 把 LF 转成 CRLF。 不归一化·用户 clone 完
    什么都没动·173 个文件会全部被误判成「改过」——保护层瞬间变噪音。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
FINGERPRINT_PATH = ROOT / "core_fingerprints.json"

ALGO = "sha256/lf/16"

# 这些按字节算 · 其余按归一化文本算 (文本才有换行符差异问题)
BINARY_SUFFIXES = {".exe", ".dll", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp",
                   ".zip", ".mp3", ".wav", ".mp4", ".ttf", ".woff", ".woff2"}

# 自引用悖论: 它的 hash 写进它自己会改变它自己 → 永远对不上
SELF_EXCLUDE = {"core_fingerprints.json"}


def file_hash(path: Path) -> Optional[str]:
    """单文件指纹 · 文件不存在返 None。"""
    if not path.is_file():
        return None
    try:
        if path.suffix.lower() in BINARY_SUFFIXES:
            data = path.read_bytes()
        else:
            text = path.read_text(encoding="utf-8", errors="replace")
            data = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
        return hashlib.sha256(data).hexdigest()[:16]
    except Exception:
        return None


def compute(files: list[str], root: Optional[Path] = None) -> dict[str, str]:
    """算一批文件的指纹 · 返 {相对路径: hash} · 算不出的跳过。"""
    base = root or ROOT
    out: dict[str, str] = {}
    for rel in files:
        rel = str(rel).strip().replace("\\", "/")
        if not rel or rel in SELF_EXCLUDE:
            continue
        h = file_hash(base / rel)
        if h:
            out[rel] = h
    return out


def load(root: Optional[Path] = None) -> dict:
    """读基线 · 缺失/坏掉返空壳 (不抛)。"""
    p = (root / "core_fingerprints.json") if root else FINGERPRINT_PATH
    try:
        # utf-8-sig: 发布链的 PowerShell 写回可能带 BOM (core_manifest.json 踩过这个坑)
        data = json.loads(p.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def has_baseline(root: Optional[Path] = None) -> bool:
    """这台机器有没有官方基线 (0.9.5 及更早升上来的第一次没有)。"""
    return bool((load(root).get("files") or {}))


def baseline_version(root: Optional[Path] = None) -> str:
    return str(load(root).get("core_version") or "").strip()


def modified_files(files: list[str], root: Optional[Path] = None) -> list[str]:
    """这些文件里·内容跟官方基线不一致的 (= 用户改过的)。

    基线里没记的文件【不算改过】—— 可能是刚扩进白名单、基线还没覆盖到 ·
    宁可漏报也不能虚报: 虚报会让升级报告变成一片"你改过"的噪音·用户就不看了。
    """
    baseline = (load(root).get("files") or {})
    if not baseline:
        return []
    base = root or ROOT
    out: list[str] = []
    for rel in files:
        rel = str(rel).strip().replace("\\", "/")
        want = baseline.get(rel)
        if not want or rel in SELF_EXCLUDE:
            continue
        actual = file_hash(base / rel)
        if actual is None:  # 用户把内核文件删了 —— 那是另一类事·不算魔改
            continue
        if actual != want:
            out.append(rel)
    return out


def drift_report(files: list[str], root: Optional[Path] = None) -> dict:
    """这台机器跟官方基线差多少 —— 用户报 bug 时先问这个。

    返 {"has_baseline", "baseline_version", "modified", "absent",
        "not_in_baseline", "clean_count"}
    """
    data = load(root)
    baseline = (data.get("files") or {})
    base = root or ROOT
    modified: list[str] = []
    absent: list[str] = []
    not_in_baseline: list[str] = []
    clean = 0
    for rel in files:
        rel = str(rel).strip().replace("\\", "/")
        if not rel or rel in SELF_EXCLUDE:
            continue
        want = baseline.get(rel)
        actual = file_hash(base / rel)
        if want is None:
            not_in_baseline.append(rel)
        elif actual is None:
            absent.append(rel)
        elif actual != want:
            modified.append(rel)
        else:
            clean += 1
    return {
        "has_baseline": bool(baseline),
        "baseline_version": str(data.get("core_version") or ""),
        "modified": modified,
        "absent": absent,
        "not_in_baseline": not_in_baseline,
        "clean_count": clean,
    }


def write_baseline(files: list[str], core_version: str, root: Optional[Path] = None,
                   generated: str = "") -> dict:
    """生成基线文件 —— 【只在官方发布链上跑】。

    必须对【用户实际拿到的那份内容】算 (纯净版·且在去母体化 transform 之后) ·
    否则用户一装上就满屏"你改过"。
    """
    base = root or ROOT
    fp = compute(files, base)
    payload = {
        "_comment": (
            "官方基线指纹 · 内核文件的官方内容 hash。 update_core 用它认「哪些内核文件你改过」——"
            "比 git status 可靠: commit 过也认得出。 这个文件由官方发布链生成·随内核一起更新。"
            "手改它只会让升级保护失准 (改动被当成官方原版·下次升级静默覆盖)。"
        ),
        "algo": ALGO,
        "algo_note": "文本: CRLF/CR 归一成 LF 后 utf-8 sha256 取前 16 位 (防 git autocrlf 误判) · 二进制: 原字节 sha256",
        "core_version": core_version,
        "generated": generated,
        "file_count": len(fp),
        "files": dict(sorted(fp.items())),
    }
    (base / "core_fingerprints.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload
