"""
tools/process_sprites.py  v0.2
==============================

把 BRO 用 GPT-Image-2 / Gemini 3 跑出来的 sprite sheet 一键处理成桌宠能用的帧。

v0.2 升级（2026-05-16 04:10，应对 BRO 实测出的真实 sprite 形态）：
  - 支持 **任意网格布局**（1×N 水平 / N×M 网格 / 不规则都能）
  - 行扫描 → row_segs；每行内列扫描 → cell_bboxes
  - **底对齐居中** —— 走路/坐下/睡觉等地面动作猫脚永远在画布底
  - **jump 特殊**：保留猫在 cell 内的相对垂直位置 → 弹跳轨迹不丢
  - **同动作内全局 padding** —— 所有帧用同一画布尺寸，呼吸时大小变化保留

输入：
  fps/raw_<action>.png  或者  desktop_pet/sprites/raw/raw_<action>.png

输出：
  desktop_pet/sprites/<action>_NN.png  (同动作所有帧 same canvas size)
  desktop_pet/sprites/manifest.json    (pet.py 启动时读)

用法：
  .venv\\Scripts\\python.exe tools\\process_sprites.py            # 处理所有
  .venv\\Scripts\\python.exe tools\\process_sprites.py walk       # 单动作
  .venv\\Scripts\\python.exe tools\\process_sprites.py --force    # 覆盖
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIRS = [
    PROJECT_ROOT / "fps",
    PROJECT_ROOT / "desktop_pet" / "sprites" / "raw",
]
OUT_DIR = PROJECT_ROOT / "desktop_pet" / "sprites"
MANIFEST = OUT_DIR / "manifest.json"

TARGET_SIZE = 96
PAD = 4  # 画布周边的安全间距

# (期望帧数, rows × cols) —— rows=auto 表示 1×N 水平，rows=2 表示 2×4 网格等
# 这里写死帧数比 detection 更稳——AI 生成的 sprite 间距常常不规则
ACTION_LAYOUT: dict[str, tuple[int, int, int]] = {
    "walk":    (8, 2, 4),  # 2 行 4 列
    "run":     (6, 3, 2),  # 3 行 2 列
    "idle":    (4, 1, 4),  # 1 行 4 列
    "sleep":   (4, 2, 2),  # 2 行 2 列
    "meow":    (4, 1, 4),  # 1 行 4 列
    "jump":    (6, 1, 6),  # 1 行 6 列
    "paw":     (4, 2, 4),  # 实际是 4 上 + 3 下，下排错位严重，只用上排 4 帧
    "curious": (5, 2, 3),  # 2 行 3 列（最后一格空）
}
KNOWN_ACTIONS = tuple(ACTION_LAYOUT.keys())

# 这些动作做"底对齐居中"——猫脚永远在画布底
# 不在这里的动作（jump）保留相对垂直位置
GROUND_ALIGNED = {"walk", "idle", "sleep", "meow", "paw", "curious", "run"}


def is_magenta(px) -> bool:
    r, g, b = px[:3]
    return r > 200 and g < 100 and b > 200


def magenta_to_transparent(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    pixels = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            if is_magenta(pixels[x, y]):
                pixels[x, y] = (0, 0, 0, 0)
    return img


def find_segments(flags: list[bool], min_gap: int = 8) -> list[tuple[int, int]]:
    """
    flags: 每个位置是否含有非空像素
    min_gap: 至少连续这么多空白才算"段间隙"
    返回 [(start, end), ...]，半开区间
    """
    segs: list[tuple[int, int]] = []
    in_seg = False
    seg_start = 0
    gap_count = 0
    n = len(flags)

    for i in range(n):
        if flags[i]:
            if not in_seg:
                in_seg = True
                seg_start = i
            gap_count = 0
        else:
            if in_seg:
                gap_count += 1
                if gap_count >= min_gap:
                    segs.append((seg_start, i - gap_count + 1))
                    in_seg = False
                    gap_count = 0
    if in_seg:
        segs.append((seg_start, n))
    return segs


def scan_rows(img: Image.Image) -> list[bool]:
    w, h = img.size
    pixels = img.load()
    return [
        any(pixels[x, y][3] > 0 for x in range(w))
        for y in range(h)
    ]


def scan_cols_in_band(img: Image.Image, y0: int, y1: int) -> list[bool]:
    w, _ = img.size
    pixels = img.load()
    return [
        any(pixels[x, y][3] > 0 for y in range(y0, y1))
        for x in range(w)
    ]


def find_tight_bbox(img: Image.Image, x0: int, y0: int, x1: int, y1: int) -> tuple[int, int, int, int] | None:
    """在矩形 (x0,y0)~(x1,y1) 内找到 cat 的紧 bbox。返回 None 如果空。"""
    pixels = img.load()
    min_x, max_x = x1, x0
    min_y, max_y = y1, y0
    found = False
    for y in range(y0, y1):
        for x in range(x0, x1):
            if pixels[x, y][3] > 0:
                found = True
                if x < min_x: min_x = x
                if x > max_x: max_x = x
                if y < min_y: min_y = y
                if y > max_y: max_y = y
    if not found:
        return None
    return (min_x, min_y, max_x + 1, max_y + 1)


def detect_cells_by_layout(img: Image.Image, rows: int, cols: int) -> list[tuple[int, int, int, int]]:
    """
    按 rows×cols 等分整图。比 detection 稳——AI 生成的 sprite 帧间距常常不规则。

    先找出所有非透明像素的整图 bbox（去掉外围空白），然后在那个 bbox 里 N 等分。
    """
    w, h = img.size
    pixels = img.load()

    min_x, max_x, min_y, max_y = w, 0, h, 0
    found = False
    for y in range(h):
        for x in range(w):
            if pixels[x, y][3] > 0:
                found = True
                if x < min_x: min_x = x
                if x > max_x: max_x = x
                if y < min_y: min_y = y
                if y > max_y: max_y = y

    if not found:
        return []

    bbox_w = max_x + 1 - min_x
    bbox_h = max_y + 1 - min_y
    cell_w = bbox_w // cols
    cell_h = bbox_h // rows

    cells: list[tuple[int, int, int, int]] = []
    for r in range(rows):
        for c in range(cols):
            x0 = min_x + c * cell_w
            y0 = min_y + r * cell_h
            x1 = min_x + (c + 1) * cell_w if c < cols - 1 else max_x + 1
            y1 = min_y + (r + 1) * cell_h if r < rows - 1 else max_y + 1
            cells.append((x0, y0, x1, y1))
    return cells


def process_one(raw_path: Path, action: str, force: bool) -> dict | None:
    print(f"\n[{action}] processing {raw_path.relative_to(PROJECT_ROOT)}")
    img = Image.open(raw_path)
    print(f"  source: {img.size}")
    img = magenta_to_transparent(img)

    expected_n, rows, cols = ACTION_LAYOUT[action]
    print(f"  layout: {rows}x{cols} = {expected_n} frames (declared)")

    cells = detect_cells_by_layout(img, rows, cols)
    print(f"  cells: {len(cells)}  (sample 1st: {cells[0] if cells else 'none'})")
    if not cells:
        print(f"  warn: no non-transparent pixels found; skipping")
        return None

    cell_bbox_pairs: list[tuple[tuple[int, int, int, int], tuple[int, int, int, int]]] = []
    for cell in cells:
        cx0, cy0, cx1, cy1 = cell
        bbox = find_tight_bbox(img, cx0, cy0, cx1, cy1)
        if bbox is None:
            print(f"  empty cell at {cell} (declared layout has spare slot, ok)")
            continue
        cell_bbox_pairs.append((cell, bbox))

    if not cell_bbox_pairs:
        return None

    # 限制到声明帧数——避免边界泄漏（前格的胡须/尾巴落到下一格被当成新 cat）
    if len(cell_bbox_pairs) > expected_n:
        print(f"  trimming {len(cell_bbox_pairs)} -> {expected_n} (declared); discarding tail (likely overflow)")
        cell_bbox_pairs = cell_bbox_pairs[:expected_n]

    # 也过滤掉异常小的 bbox（极有可能是噪点：单根胡须等）
    max_w_initial = max(b[2] - b[0] for _, b in cell_bbox_pairs)
    max_h_initial = max(b[3] - b[1] for _, b in cell_bbox_pairs)
    min_area = (max_w_initial * max_h_initial) * 0.15
    cell_bbox_pairs = [
        (cell, bbox) for cell, bbox in cell_bbox_pairs
        if (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) >= min_area
    ]

    max_w = max(b[2] - b[0] for _, b in cell_bbox_pairs)
    max_h = max(b[3] - b[1] for _, b in cell_bbox_pairs)
    canvas_side = max(max_w, max_h) + 2 * PAD
    print(f"  cat bboxes: max_w={max_w}, max_h={max_h} -> canvas {canvas_side}x{canvas_side}")
    print(f"  alignment: {'ground' if action in GROUND_ALIGNED else 'preserve-y (jump-style)'}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for i, ((cx0, cy0, cx1, cy1), (bx0, by0, bx1, by1)) in enumerate(cell_bbox_pairs, start=1):
        out_name = f"{action}_{i:02d}.png"
        out_path = OUT_DIR / out_name
        if out_path.exists() and not force:
            print(f"  skip {out_name} (exists, --force to overwrite)")
            saved.append(out_name)
            continue

        cat_w = bx1 - bx0
        cat_h = by1 - by0
        cat = img.crop((bx0, by0, bx1, by1))

        canvas = Image.new("RGBA", (canvas_side, canvas_side), (0, 0, 0, 0))

        place_x = (canvas_side - cat_w) // 2

        if action in GROUND_ALIGNED:
            place_y = canvas_side - cat_h - PAD
        else:
            cell_h = cy1 - cy0
            cat_y_in_cell = by0 - cy0
            cell_scale = (canvas_side - 2 * PAD) / max(cell_h, 1)
            place_y = PAD + int(cat_y_in_cell * cell_scale)
            place_y = max(PAD, min(place_y, canvas_side - cat_h - PAD))

        canvas.paste(cat, (place_x, place_y), cat)

        final = canvas.resize((TARGET_SIZE, TARGET_SIZE), Image.NEAREST)
        final.save(out_path)
        print(f"  saved {out_name}  cat {cat_w}x{cat_h} → {TARGET_SIZE}x{TARGET_SIZE}")
        saved.append(out_name)

    return {
        "action": action,
        "frame_count": len(saved),
        "files": saved,
        "canvas_side": canvas_side,
        "alignment": "ground" if action in GROUND_ALIGNED else "preserve-y",
    }


def find_raw(action: str) -> Path | None:
    for d in RAW_DIRS:
        p = d / f"raw_{action}.png"
        if p.exists():
            return p
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Process raw sprite sheets into per-frame PNGs (v0.2 grid-aware)")
    parser.add_argument("action", nargs="?", help="Specific action to process (default: all)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing frames")
    args = parser.parse_args()

    if args.action:
        if args.action not in KNOWN_ACTIONS:
            print(f"unknown action: {args.action!r}; known: {', '.join(KNOWN_ACTIONS)}")
            return 1
        actions = [args.action]
    else:
        actions = list(KNOWN_ACTIONS)

    manifest: dict = {}
    if MANIFEST.exists():
        try:
            manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}

    processed = 0
    for action in actions:
        raw_path = find_raw(action)
        if not raw_path:
            print(f"[{action}] no raw_{action}.png found in {[str(d.relative_to(PROJECT_ROOT)) for d in RAW_DIRS]}")
            continue
        result = process_one(raw_path, action, args.force)
        if result:
            manifest[action] = result
            processed += 1

    if processed:
        MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n✓ processed {processed} action(s)")
        print(f"  manifest: {MANIFEST.relative_to(PROJECT_ROOT)}")
        print(f"  pet.py will load these on next launch")
    else:
        print(f"\n(nothing processed — drop raw_*.png into fps/ or desktop_pet/sprites/raw/)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
