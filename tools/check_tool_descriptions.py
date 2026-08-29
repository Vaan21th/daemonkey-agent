"""简介 + schema 字段预算闸。超线 exit 1。

用法:  python tools/check_tool_descriptions.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent_tools import REGISTRY  # noqa: E402
from agent_tools._desc_budget import (  # noqa: E402
    MAX_DESC_TOKENS,
    MAX_FIELD_TOKENS,
    audit_registry,
    audit_schema_registry,
    audit_tools_dir,
    count_desc_tokens,
    iter_schema_fields,
)


def main() -> int:
    over_desc = audit_registry(REGISTRY)
    over_field = audit_schema_registry(REGISTRY)
    over_disk = audit_tools_dir()
    rows = sorted(
        ((s.name, count_desc_tokens(s.description or "")) for s in REGISTRY.values()),
        key=lambda x: -x[1],
    )
    print(
        f"tools={len(REGISTRY)} desc_cap={MAX_DESC_TOKENS} "
        f"field_cap={MAX_FIELD_TOKENS} "
        f"over_desc={len(over_desc)} over_field={len(over_field)} "
        f"over_disk={len(over_disk)}"
    )
    for name, n in rows[:8]:
        flag = " *" if n > MAX_DESC_TOKENS else ""
        print(f"  desc {n:4d}  {name}{flag}")
    fat_fields = []
    for spec in REGISTRY.values():
        for path, text in iter_schema_fields(spec.input_schema or {}, spec.name):
            fat_fields.append((count_desc_tokens(text), path))
    for n, path in sorted(fat_fields, reverse=True)[:8]:
        flag = " *" if n > MAX_FIELD_TOKENS else ""
        print(f"  field {n:4d}  {path}{flag}")
    if over_desc or over_field or over_disk:
        print("FAIL")
        for o in over_desc:
            print(f"  desc {o['name']} {o['tok']} (+{o['over']})")
        for o in over_field:
            print(f"  field {o['path']} {o['tok']} (+{o['over']})")
        for o in over_disk:
            print(f"  disk {o.get('file')} {o.get('path')} {o['tok']} (+{o['over']})")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
