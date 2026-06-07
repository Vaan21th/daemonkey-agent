"""
tools/pet_smoke.py
==================

测 pet/sprite.py 的非 UI 部分。
UI 需要显示器 · OPUS 没有显示器 · 让 BRO 自己跑 start-pet.ps1 看实际窗口。

跑法:
    .\\.venv\\Scripts\\python.exe -m tools.pet_smoke
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def hr(label):
    print(f"\n--- {label} ---")


def main() -> int:
    failures = 0

    hr("[1] import pet.sprite")
    try:
        import pet.sprite as ps
        print("  [OK] import OK")
    except Exception as e:
        print(f"  [FAIL] import 崩了: {e}")
        return 1

    hr("[2] 配置项有合理默认值")
    print(f"  DAEMON_HEALTH_URL: {ps.DAEMON_HEALTH_URL}")
    print(f"  DAEMON_UI_URL:     {ps.DAEMON_UI_URL}")
    print(f"  DAEMON_API_BASE:   {ps.DAEMON_API_BASE}")
    print(f"  WINDOW_SIZE:       {ps.WINDOW_SIZE}")
    print(f"  POS_FILE:          {ps.POS_FILE}")
    if not (ps.WINDOW_SIZE >= 64 and ps.WINDOW_SIZE <= 200):
        print(f"  [FAIL] WINDOW_SIZE 不合理")
        failures += 1
    else:
        print("  [OK] 配置合理")

    hr("[3] _load_pos / _save_pos 往返")
    import tempfile, os
    real_pos_file = ps.POS_FILE
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        tmp_path = Path(f.name)
    try:
        ps.POS_FILE = tmp_path
        # 不存在时返回默认
        if tmp_path.exists():
            tmp_path.unlink()
        pos = ps._load_pos()
        assert "x" in pos and "y" in pos
        print(f"  [OK] 不存在时返回 {pos}")
        # save then load
        ps._save_pos(200, 300)
        pos = ps._load_pos()
        if pos.get("x") == 200 and pos.get("y") == 300:
            print(f"  [OK] save/load 往返成功: {pos}")
        else:
            print(f"  [FAIL] 往返失败: {pos}")
            failures += 1
    finally:
        ps.POS_FILE = real_pos_file
        if tmp_path.exists():
            tmp_path.unlink()

    hr("[4] COLORS 三档完整")
    for state in ("online", "offline", "error"):
        c = ps.COLORS.get(state)
        if not (c and "fill" in c and "stroke" in c and "text" in c):
            print(f"  [FAIL] {state} 配色不全: {c}")
            failures += 1
        else:
            print(f"  [OK] {state}: fill={c['fill']}")

    hr("[5] 健康检查类签名 (不实际起 UI)")
    # 验证 OpusSprite 类存在且有关键方法
    cls = ps.OpusSprite
    for method in ("_check_health", "_open_ui", "_trigger_radar_refresh",
                   "_trigger_trends_refresh", "_show_menu", "_quit", "run"):
        if not hasattr(cls, method):
            print(f"  [FAIL] OpusSprite 缺少 {method}")
            failures += 1
        else:
            print(f"  [OK] OpusSprite.{method} ✓")

    print("\n" + "=" * 50)
    if failures == 0:
        print("[smoke] ALL PASS · 实际 UI 显示请 BRO 跑 start-pet.ps1")
        return 0
    print(f"[smoke] {failures} FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
