"""可灵房间片 → 透明序列帧。先 --bench 对照体积，再无参抽出全套。"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from desktop_pet.clip_map import CLIP_FILES, SHIP_CLIPS  # noqa: E402
from desktop_pet.room_key import apply_key_crop, build_key_mask  # noqa: E402

FFMPEG = Path(r"E:\ffmpeg-2025-05-15-git-12b853530a-essentials_build\bin\ffmpeg.exe")
CLIPS = ROOT / "desktop_pet" / "clips"
FRAMES = ROOT / "desktop_pet" / "frames"
SRC_W, SRC_H = 1764, 1176
# 原片完整房间约 1253×1130 · 宽 520 按比例取高
MASTER = (520, 469)
FPS = 12
FRAME_STEP = 2
QUALITY = 80
FRAME_MS = 83


def _ffmpeg() -> str:
    if FFMPEG.exists():
        return str(FFMPEG)
    return "ffmpeg"


def _read_png_stream(stdout):
    sig = stdout.read(8)
    if sig != b"\x89PNG\r\n\x1a\n":
        return
    while True:
        parts = [sig]
        while True:
            hdr = stdout.read(8)
            if len(hdr) < 8:
                return
            n = int.from_bytes(hdr[:4], "big")
            parts.append(hdr)
            parts.append(stdout.read(n + 4))
            if hdr[4:] == b"IEND":
                break
        yield b"".join(parts)
        sig = stdout.read(8)
        if sig != b"\x89PNG\r\n\x1a\n":
            return


def iter_rgb(mp4: Path, tmp: Path, limit: int = 0):
    cmd = [_ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(mp4)]
    if limit > 0:
        cmd += ["-vframes", str(limit)]
    cmd += ["-f", "image2pipe", "-vcodec", "png", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert proc.stdout is not None
    n = 0
    try:
        for blob in _read_png_stream(proc.stdout):
            im = Image.open(io.BytesIO(blob)).convert("RGB")
            if im.size != (SRC_W, SRC_H):
                raise RuntimeError(f"{mp4.name} size {im.size} != {SRC_W}x{SRC_H}")
            yield np.asarray(im)
            n += 1
            if limit and n >= limit:
                break
    finally:
        proc.kill()
        proc.wait()


def save_rgba(arr: np.ndarray, dest: Path, kind: str, quality: int) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    im = Image.fromarray(arr, "RGBA")
    if kind == "png":
        im.save(dest, "PNG", optimize=True)
    elif kind == "webp_lossless":
        im.save(dest, "WEBP", lossless=True, quality=100, method=4)
    else:
        im.save(dest, "WEBP", quality=quality, method=4, exact=True)
    return dest.stat().st_size


def resize_rgba(arr: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    im = Image.fromarray(arr, "RGBA")
    out = im.resize(size, Image.Resampling.LANCZOS)
    return np.asarray(out)


def first_mask(mp4: Path, tmp: Path):
    rgb = next(iter_rgb(mp4, tmp, limit=1))
    return build_key_mask(rgb)


def bench() -> None:
    mp4 = CLIPS / "idle_blink.mp4"
    tmp = ROOT / "data" / "_tmp_sysprompt" / "_pet_png"
    alpha, crop = first_mask(mp4, tmp)
    print("crop", crop)
    variants = [
        ("native", None, "png", 0),
        ("native", None, "webp_lossless", 0),
        ("native", None, "webp", 90),
        ("780", MASTER, "webp_lossless", 0),
        ("780", MASTER, "webp", 95),
        ("780", MASTER, "webp", 90),
        ("780", MASTER, "webp", 85),
        ("640", (640, 549), "webp", 90),
    ]
    n = 0
    totals = {v[0] + "/" + v[2] + str(v[3]): 0 for v in variants}
    out = ROOT / "data" / "_tmp_sysprompt" / "_pet_bench"
    out.mkdir(parents=True, exist_ok=True)
    for rgb in iter_rgb(mp4, tmp, limit=8):
        keyed = apply_key_crop(rgb, alpha, crop)
        for name, size, kind, q in variants:
            arr = resize_rgba(keyed, size) if size else keyed
            key = f"{name}/{kind}{q}"
            ext = "png" if kind == "png" else "webp"
            dest = out / f"{n:03d}_{name}_{kind}{q}.{ext}"
            totals[key] += save_rgba(arr, dest, kind, q)
        n += 1
        if n >= 8:
            break
    print(f"sampled {n} frames · idle_blink")
    for k, b in totals.items():
        print(f"  {k:28s}  {b/n/1024:7.1f} KB/frame  ×1210 ≈ {b/n*1210/1024/1024:5.1f} MB")


def extract_all(only: list[str] | None = None) -> None:
    tmp = ROOT / "data" / "_tmp_sysprompt" / "_pet_png"
    probe = CLIPS / "idle_blink.mp4"
    alpha, crop = first_mask(probe, tmp)
    print("mask crop", crop, "master", MASTER, flush=True)
    wanted = only or list(SHIP_CLIPS)
    manifest = {
        "fps": FPS,
        "master": list(MASTER),
        "crop": list(crop),
        "src": [SRC_W, SRC_H],
        "format": "webp_anim",
        "quality": QUALITY,
        "clips": {},
    }
    FRAMES.mkdir(parents=True, exist_ok=True)
    for cid in wanted:
        fname = CLIP_FILES[cid]
        mp4 = CLIPS / fname
        if not mp4.exists():
            print("skip missing", fname)
            continue
        imgs = []
        for i, rgb in enumerate(iter_rgb(mp4, tmp)):
            if i % FRAME_STEP:
                continue
            keyed = apply_key_crop(rgb, alpha, crop)
            arr = resize_rgba(keyed, MASTER)
            imgs.append(Image.fromarray(arr, "RGBA"))
        dest = FRAMES / f"{cid}.webp"
        loop = 1 if cid in ("work_done",) else 0
        imgs[0].save(
            dest,
            save_all=True,
            append_images=imgs[1:],
            duration=FRAME_MS,
            loop=loop,
            format="WEBP",
            quality=QUALITY,
            method=4,
            exact=True,
        )
        bytes_ = dest.stat().st_size
        manifest["clips"][cid] = {"frames": len(imgs), "bytes": bytes_, "loop": loop}
        print(f"  {cid:12s} {len(imgs):3d} frames  {bytes_/1024/1024:.2f} MB", flush=True)
    manifest["clips"] = list(SHIP_CLIPS)
    (FRAMES / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("wrote", FRAMES / "manifest.json")


def slim() -> None:
    """已有 780/24 动画再压一档 · 12fps + 520 宽 + 丢掉未出厂段。"""
    kept = set(SHIP_CLIPS)
    total = 0
    for cid in SHIP_CLIPS:
        src = FRAMES / f"{cid}.webp"
        if not src.exists():
            print("missing", cid, flush=True)
            continue
        im = Image.open(src)
        n = getattr(im, "n_frames", 1)
        frames = []
        for i in range(0, n, FRAME_STEP):
            im.seek(i)
            fr = im.convert("RGBA").resize(MASTER, Image.Resampling.LANCZOS)
            frames.append(fr)
        dest = FRAMES / f"_{cid}.webp"
        loop = 1 if cid == "work_done" else 0
        frames[0].save(
            dest,
            save_all=True,
            append_images=frames[1:],
            duration=FRAME_MS,
            loop=loop,
            format="WEBP",
            quality=QUALITY,
            method=4,
            exact=True,
        )
        dest.replace(src)
        total += src.stat().st_size
        print(f"  {cid:12s} {len(frames):3d}f  {src.stat().st_size/1024/1024:.2f} MB", flush=True)
    for extra in FRAMES.glob("*.webp"):
        if extra.stem not in kept:
            extra.unlink()
            print("drop", extra.name, flush=True)
    (FRAMES / "manifest.json").write_text(
        json.dumps(
            {
                "fps": FPS,
                "master": list(MASTER),
                "format": "webp_anim",
                "quality": QUALITY,
                "clips": list(SHIP_CLIPS),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"total {total/1024/1024:.1f} MB", flush=True)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--bench", action="store_true")
    p.add_argument("--slim", action="store_true")
    p.add_argument("--only", default="", help="comma clip ids")
    args = p.parse_args()
    if args.bench:
        bench()
        return 0
    if args.slim:
        slim()
        return 0
    only = [x.strip() for x in args.only.split(",") if x.strip()] or None
    extract_all(only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
