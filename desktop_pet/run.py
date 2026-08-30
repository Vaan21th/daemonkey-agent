"""桌宠入口 · 默认小房间 · --cat 开旧橙猫（启动器连点三次）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cat", action="store_true", help="彩蛋：旧橙猫")
    args = p.parse_args()
    if args.cat:
        from desktop_pet.pet import main as cat_main

        return cat_main()
    from desktop_pet.room_pet import main as room_main

    return room_main()


if __name__ == "__main__":
    sys.exit(main())
