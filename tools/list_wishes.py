"""临时脚本 · 列出 wishlist 的状态分布和可测试候选。"""
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path

p = Path(__file__).resolve().parent.parent / "data" / "opus_wishlist.json"
data = json.loads(p.read_text(encoding="utf-8"))
items = data.get("wishes", [])
print(f"wishlist 共 {len(items)} 条")
print()
print("=== 状态分布 (phase / status) ===")
ph = Counter(
    f"{w.get('daemon_phase') or 'none':<12} / {w.get('status') or '?':<12}"
    for w in items
)
for k, v in ph.most_common():
    print(f"  {k}: {v}")
print()
print("=== 候选 (status open/approved/queued + phase 非 done) ===")
found = 0
for w in items:
    phase = w.get("daemon_phase")
    status = w.get("status") or "?"
    title = (w.get("title") or "?")[:60]
    wid = w.get("id", "?")
    if phase != "done" and status in ("open", "approved", "in_progress", "queued"):
        ph_disp = phase or "none"
        print(f"  {wid}  status={status:<12} phase={ph_disp:<12} title={title}")
        found += 1
if found == 0:
    print("  (无 · 所有 wish 都是 done 或 rejected)")
