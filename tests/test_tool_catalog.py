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


def test_catalog_on_by_default():
    assert catalog_enabled()
    vis = visible_names(None)
    assert CATALOG_SEARCH in vis
    assert CATALOG_CALL in vis
    assert "read_file" in vis
    assert "create_app" not in vis
    assert "generate_presentation" not in vis
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
    name, args = _rewrite_tool_use("read_file", {"path": "a"})
    assert name == "read_file"


def test_catalog_call_still_hits_scenario_gate():
    begin_turn()
    spec = REGISTRY[CATALOG_CALL]
    r = spec.run({"name": "create_app", "args": {"name": "x", "description": "yyyy"}})
    assert not r.ok
    assert "read_scenario" in (r.error or "")


def test_search_finds_presentation():
    hits = search("PPT", limit=8)
    names = [h["name"] for h in hits]
    assert "generate_presentation" in names


def test_directory_lists_deferred_not_core():
    block = directory_block()
    assert "create_app" in block
    assert "catalog_call" in block
    assert "- read_file:" not in block
    assert len(block) <= 18000


def test_visible_specs_are_registered():
    for spec in visible_specs(None):
        assert spec.name in CORE or spec.name in {CATALOG_SEARCH, CATALOG_CALL}
