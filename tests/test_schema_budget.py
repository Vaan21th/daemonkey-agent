from agent_tools import REGISTRY
from agent_tools._desc_budget import (
    MAX_FIELD_TOKENS,
    assert_schema_budget,
    audit_schema_registry,
)
from agent_tools._hotpath_guard import begin_turn
from agent_tools.create_app import SPEC as CREATE_APP


def test_registry_schema_under_cap():
    assert audit_schema_registry(REGISTRY) == []


def test_fat_field_refused():
    schema = {
        "type": "object",
        "properties": {
            "x": {
                "type": "string",
                "description": "word " * (MAX_FIELD_TOKENS + 20),
            }
        },
    }
    try:
        assert_schema_budget("dummy", schema)
    except ValueError as e:
        assert "over" in str(e)
        return
    raise AssertionError("expected ValueError")


def test_create_app_needs_scenario():
    begin_turn()
    r = CREATE_APP.run({"name": "x", "description": "yyyy"})
    assert not r.ok
    assert "read_scenario" in (r.error or "")
