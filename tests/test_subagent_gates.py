"""分身闸：工坊不被 L3-C 误伤 · DENY · 后台共用线程池 · 分类失败改拒。"""
from workers.subagent_runner import _auto_confirm, _should_strict_expand
from agent_tools.dispatch_subagent import _ALWAYS_DENY, _resolve_whitelist, _run_pool


class _Spec:
    def __init__(self, tier):
        self._tier = tier

    def effective_tier(self, args):
        return self._tier


class _Boom:
    def effective_tier(self, args):
        raise RuntimeError("classify boom")


def test_strict_expand_only_when_dispatch_asks():
    writes = {"read_file", "write_file"}
    assert _should_strict_expand(writes, False) is False
    assert _should_strict_expand(writes, True) is True
    assert _should_strict_expand({"read_file", "grep_files"}, True) is False
    assert _should_strict_expand(None, True) is False


def test_classify_failure_rejects():
    out = _auto_confirm(_Boom(), {})
    assert out.startswith("reject:")


def test_deny_strips_writes_even_when_named():
    assert "write_file" in _ALWAYS_DENY
    assert "python_exec" in _ALWAYS_DENY
    assert "mcp_call_tool" in _ALWAYS_DENY
    assert "dispatch_subagent_cancel" in _ALWAYS_DENY
    wl = _resolve_whitelist(["write_file", "read_file", "mcp_call_tool"])
    assert "write_file" not in wl
    assert "mcp_call_tool" not in wl
    assert "read_file" in wl


def test_run_pool_keeps_order(monkeypatch):
    def fake_run_one(idx, task, runtime, parent_sid, cancel_check=None, preset_id=None):
        return {"idx": idx, "ok": True, "goal": task["goal"], "subagent_id": preset_id}

    monkeypatch.setattr("agent_tools.dispatch_subagent._run_one", fake_run_one)
    out = _run_pool(
        [{"goal": "a"}, {"goal": "b"}],
        runtime=None,
        parent_sid="",
        preset_ids=["sub-aaa", "sub-bbb"],
    )
    assert [r["goal"] for r in out] == ["a", "b"]
    assert [r["subagent_id"] for r in out] == ["sub-aaa", "sub-bbb"]


def test_readonly_confirm_still_yes_when_not_expanded():
    assert _auto_confirm(_Spec("confirm"), {}) == "yes"
