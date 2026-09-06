"""手册自成长金丝雀：三刀分项过/不过。不打自嗨总分。"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_KNIVES = (
    ("auto_writeback", "test_knife1_auto_writeback_through_relevant_playbooks"),
    ("empty_downrank", "test_knife2_empty_experience_loses_the_slot"),
    ("propose_not_confirm", "test_knife3_cluster_proposes_not_confirms"),
)


def main() -> int:
    import pytest
    test = str(ROOT / "tests" / "test_playbook_growth.py")
    knives = {}
    for key, node in _KNIVES:
        knives[key] = pytest.main(["-q", test, "-k", node]) == 0
    passed = sum(1 for v in knives.values() if v)
    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "standard": "三刀：自动写回 / 空经验降权 / 同簇提出不入库",
        "knives": knives,
        "passed": passed,
        "total": 3,
        "verdict": "三刀都过，管道可合入" if passed == 3 else "三刀未齐，不称能力升级",
        "slogan": "未宣称只为你而成长已落地",
    }
    out = ROOT / "data" / "runtime" / "playbook_growth_canary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed == 3 else 1


if __name__ == "__main__":
    raise SystemExit(main())
