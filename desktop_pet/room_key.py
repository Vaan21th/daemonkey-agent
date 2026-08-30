"""小房间去灰 · 只抠连到画框外的灰，屋里同色家具不动。"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

# 可灵出片的底 · 比 #808080 暖一档
KEY_RGB = np.array([168, 166, 167], dtype=np.int16)
KEY_SOFT = 36
FEATHER = 3
CROP_PAD = 12


def build_key_mask(rgb: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """rgb HxWx3 → 整帧 alpha + 裁切 (x,y,w,h)。只做一次。"""
    dist = np.sqrt(((rgb.astype(np.int16) - KEY_RGB) ** 2).sum(axis=2))
    near = dist < KEY_SOFT
    labeled, _n = ndimage.label(near, structure=np.ones((3, 3), dtype=np.int8))
    border = np.unique(
        np.concatenate(
            [labeled[0, :], labeled[-1, :], labeled[:, 0], labeled[:, -1]]
        )
    )
    border = border[border != 0]
    outside = np.isin(labeled, border)
    dt = ndimage.distance_transform_edt(~outside)
    alpha = np.clip(dt * (255.0 / max(FEATHER, 1)), 0, 255).astype(np.uint8)
    ys, xs = np.where(alpha > 8)
    if len(xs) == 0:
        h, w = alpha.shape
        return alpha, (0, 0, w, h)
    x0 = max(int(xs.min()) - CROP_PAD, 0)
    y0 = max(int(ys.min()) - CROP_PAD, 0)
    x1 = min(int(xs.max()) + CROP_PAD + 1, alpha.shape[1])
    y1 = min(int(ys.max()) + CROP_PAD + 1, alpha.shape[0])
    return alpha, (x0, y0, x1 - x0, y1 - y0)


def apply_key_crop(
    rgb: np.ndarray,
    alpha_full: np.ndarray,
    crop: tuple[int, int, int, int],
) -> np.ndarray:
    x, y, w, h = crop
    out = np.zeros((h, w, 4), dtype=np.uint8)
    out[:, :, :3] = rgb[y : y + h, x : x + w]
    out[:, :, 3] = alpha_full[y : y + h, x : x + w]
    return out
