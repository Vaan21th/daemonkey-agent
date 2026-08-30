"""把动画 WebP 解成 QPixmap · Windows 透明窗要 ARGB32。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from PyQt6.QtGui import QImage, QPixmap


_CACHE: dict[tuple, list[QPixmap]] = {}


def load_clip_pixmaps(
    path: Path, tw: int, th: int, take: tuple[int, ...] | None = None
) -> list[QPixmap]:
    key = (str(path), tw, th, take)
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    src = Image.open(path)
    n = getattr(src, "n_frames", 1)
    idxs = list(take) if take else list(range(n))
    out: list[QPixmap] = []
    for i in idxs:
        if i < 0 or i >= n:
            continue
        src.seek(i)
        im = src.convert("RGBA")
        if im.size != (tw, th):
            im = im.resize((tw, th), Image.Resampling.LANCZOS)
        arr = np.ascontiguousarray(np.asarray(im))
        q = QImage(arr.tobytes(), tw, th, tw * 4, QImage.Format.Format_RGBA8888)
        q = q.convertToFormat(QImage.Format.Format_ARGB32)
        out.append(QPixmap.fromImage(q))
    _CACHE[key] = out
    return out


def preload_scale(_scale: str | None = None) -> None:
    from desktop_pet.clip_map import (
        BASE_WH,
        BLINK_TAKE,
        IDLE_MAIN,
        REST_DOWN,
        REST_UP,
        frame_path,
    )

    tw, th = BASE_WH
    jobs = [
        (IDLE_MAIN, BLINK_TAKE),
        ("drag", None),
        ("work", None),
        ("idle_rest", REST_DOWN),
        ("idle_rest", REST_UP),
        ("idle_sing", None),
        ("work_done", None),
        ("guard", None),
    ]
    for cid, take in jobs:
        path = frame_path(cid)
        if path:
            load_clip_pixmaps(path, tw, th, take)
