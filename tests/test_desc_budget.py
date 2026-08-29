from agent_tools._desc_budget import (
    MAX_DESC_TOKENS,
    MAX_FIELD_TOKENS,
    _approx_tokens,
    audit_source,
    audit_tools_dir,
    boot_discovery_notice,
    extract_toolspecs,
    format_budget_hint,
    unknown_tool_error,
)


def _src(desc: str, field: str) -> str:
    return (
        "SPEC = ToolSpec(\n"
        '    name="demo_tool",\n'
        f'    description="{desc}",\n'
        "    input_schema={\n"
        '        "type": "object",\n'
        '        "properties": {\n'
        f'            "q": {{"type": "string", "description": "{field}"}},\n'
        "        },\n"
        "    },\n"
        ")\n"
    )


def test_extract_implicit_concat():
    src = (
        "SPEC = ToolSpec(\n"
        '    name="demo_tool",\n'
        '    description=("one "\n'
        '                 "two"),\n'
        "    input_schema={},\n"
        ")\n"
    )
    specs = extract_toolspecs(src)
    assert specs == [("demo_tool", "one two", {})]


def test_audit_source_flags_fat_copy():
    fat_desc = "word " * 200
    fat_field = "word " * 80
    overs = audit_source(_src(fat_desc, fat_field), label="demo.py")
    kinds = {o["kind"] for o in overs}
    assert "desc" in kinds
    assert "field" in kinds
    assert any(o["name"] == "demo_tool" and o["over"] > 0 for o in overs)


def test_audit_source_ok_short():
    assert audit_source(_src("When to stretch this hand.", "Query text."), label="x.py") == []


def test_hint_tells_how_to_fix():
    text = format_budget_hint([{
        "kind": "desc",
        "name": "demo_tool",
        "path": "demo_tool",
        "tok": MAX_DESC_TOKENS + 20,
        "over": 20,
    }], blocked_restart=True)
    assert "重启被拦下" in text
    assert "怎么改" in text
    assert str(MAX_DESC_TOKENS) in text
    assert str(MAX_FIELD_TOKENS) in text


def test_unknown_tool_plain():
    msg = unknown_tool_error("no_such_hand")
    assert msg.startswith("unknown tool: no_such_hand")
    assert "catalog_search" in msg


def test_boot_notice_empty_when_healthy():
    assert boot_discovery_notice() == ""


def test_disk_tools_within_budget():
    assert audit_tools_dir() == []


def test_approx_does_not_false_kill_english():
    text = (
        "Bypass the shrink-guard. Only set true when you INTENTIONALLY shrink a large file "
        ">40% (e.g. deleting a big dead-code block). For normal edits to big files, "
        "use edit_file (str_replace) instead — never overwrite."
    )
    assert _approx_tokens(text) <= MAX_FIELD_TOKENS


def test_approx_does_not_false_kill_mixed_old_string():
    text = (
        "Exact text to replace. Must uniquely identify ONE location "
        "(include enough surrounding context). Whitespace/indentation must match the file exactly. "
        "单次模式用; 批量同构修复请用 edits (原子·一次改多处)."
    )
    assert _approx_tokens(text) <= MAX_FIELD_TOKENS
