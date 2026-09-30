import pytest

from agent_tools import REGISTRY
from agent_tools._hotpath_guard import begin_turn
from agent_tools._tool_catalog import (
    CATALOG_CALL,
    CATALOG_SEARCH,
    CORE,
    catalog_enabled,
    deferred_names,
    directory_block,
    resolve_call,
    search,
    visible_names,
    visible_specs,
)
from tool_loop import _rewrite_tool_use, _specs_for_llm, to_openai_tools


@pytest.fixture(autouse=True)
def _isolate_catalog_allowed():
    """2026-09-19 修红：上游测试若调 set_catalog_allowed({...})，contextvars 会在同一个
    pytest 进程里残留 → _bound_allowed(None) 拿到旧集合 → deferred_names(None) 被那个
    集合过滤成空表，本文件断言就假红（单跑绿、全量红）。每个 case 前后都清回 None。
    """
    from agent_tools._tool_catalog import set_catalog_allowed
    set_catalog_allowed(None)
    yield
    set_catalog_allowed(None)


def test_catalog_on_by_default():
    assert catalog_enabled()
    vis = visible_names(None)
    assert CATALOG_SEARCH in vis
    assert CATALOG_CALL in vis
    assert "read_file" in vis
    assert "create_app" not in vis
    # B1（2026-09-16）：7 个生成类移出 CORE → 进延迟目录（不再在手边）
    for _n in ("generate_presentation", "generate_report", "generate_spreadsheet",
               "revise_office", "extend_office", "illustrate_office"):
        assert _n not in vis
        assert _n in deferred_names(None)
    assert "inspect_office" in vis
    assert len(vis) < 40
    assert len(vis) < len(REGISTRY)


def test_tools_json_stable_and_smaller():
    a = to_openai_tools(_specs_for_llm(None))
    b = to_openai_tools(_specs_for_llm(None))
    assert a == b
    names = {x["function"]["name"] for x in a}
    assert "create_app" not in names
    assert "catalog_call" in names
    full = to_openai_tools(list(REGISTRY.values()))
    import json
    assert len(json.dumps(a, ensure_ascii=False)) < len(json.dumps(full, ensure_ascii=False)) * 0.55


def test_taste_tight_whitelist_stays_native():
    vis = visible_names({"commit_taste"})
    assert vis == {"commit_taste"}


def test_wechat_drops_clipboard_keeps_catalog():
    allowed = {n for n in REGISTRY if n != "write_clipboard"}
    vis = visible_names(allowed)
    assert "write_clipboard" not in vis
    assert "catalog_call" in vis
    assert "create_app" not in vis
    assert "write_clipboard" not in deferred_names(allowed)


def test_resolve_catalog_call():
    name, args = resolve_call(CATALOG_CALL, {"name": "create_app", "args": {"x": 1}})
    assert name == "create_app"
    assert args == {"x": 1}
    name, args = resolve_call(CATALOG_CALL, {"name": "draft_studio", "args": '{"domain":"x"}'})
    assert name == "draft_studio"
    assert args == {"domain": "x"}
    name, args = resolve_call(CATALOG_CALL, {"name": "run_flow", "args": "", "action": "start", "flow_id": "f1"})
    assert name == "run_flow"
    assert args == {"action": "start", "flow_id": "f1"}
    name, args = _rewrite_tool_use("read_file", {"path": "a"})
    assert name == "read_file"


def test_catalog_call_still_hits_scenario_gate():
    begin_turn()
    spec = REGISTRY[CATALOG_CALL]
    r = spec.run({"name": "create_app", "args": {"name": "x", "description": "yyyy"}})
    assert not r.ok
    assert "read_scenario" in (r.error or "")


def test_search_finds_deferred_office_tools():
    """B1（2026-09-16）后：生成类在延迟目录里 → search 应能搜到（以前它们在 core，搜不到）。"""
    assert "generate_presentation" in [h["name"] for h in search("PPT", limit=8)]
    assert "generate_spreadsheet" in [h["name"] for h in search("Excel 出表", limit=8)]
    assert "create_app" in [h["name"] for h in search("create_app", limit=8)]


def test_directory_lists_deferred_not_core():
    block = directory_block()
    assert "create_app" in block
    assert "catalog_call" in block
    assert "- read_file:" not in block
    assert len(block) <= 18000


def test_directory_exclude_drops_full_tools():
    """wish-9de9bce3 · 精准磨：exclude = 已全量进 tools[] 的 → 目录不重复列出它们。"""
    blk = directory_block(exclude={"generate_presentation"})
    assert "- generate_presentation:" not in blk
    assert "create_app" in blk
    dn_all = deferred_names(None)
    dn_ex = deferred_names(None, exclude={"generate_presentation", "generate_report"})
    assert len(dn_ex) == len(dn_all) - 2
    assert "generate_presentation" not in dn_ex and "generate_report" not in dn_ex


def test_visible_specs_are_registered():
    for spec in visible_specs(None):
        assert spec.name in CORE or spec.name in {CATALOG_SEARCH, CATALOG_CALL}
