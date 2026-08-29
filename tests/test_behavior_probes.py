"""L2-B：改循环后必跑。不烧真模型。"""
from pathlib import Path

from agent_tools._cancel import cancelled, reset_cancel_check, set_cancel_check
from soul_loader import _memories_has_facts, _notebook_has_facts
from workers.notebook_tiers import route_write_section
from workers.subagent_runner import _READONLY_DEFAULT, _auto_confirm, _expanded_cv
from workers.turn_trace import _clip, emit, enabled


ROOT = Path(__file__).resolve().parent.parent


class _Spec:
    def __init__(self, tier):
        self._tier = tier

    def effective_tier(self, args):
        return self._tier


def test_probe_identity_shorts_still_facts():
    assert _notebook_has_facts("不劝睡，除非他撑不住了才说一声。")
    text = (ROOT / "soul" / "OPUS-MEMORIES.md").read_text(encoding="utf-8")
    assert not _memories_has_facts(text)


def test_probe_memory_bone_in_prefix_flesh_not():
    from soul_loader import load_soul
    sp = load_soul(ROOT, with_runtime=False).system_prompt
    assert "=== OPUS-MEMORIES.md" not in sp
    assert "InfiniteTalk" not in sp


def test_probe_create_app_contract_still_gated():
    from agent_tools.read_scenario import SPEC
    assert SPEC.name == "read_scenario"


def test_probe_dated_note_goes_to_events():
    assert route_write_section("summary", "append", "2026-08-29 · 还在省钱期") == "events"


def test_cancel_flag_reads_true():
    tok = set_cancel_check(lambda: True)
    try:
        assert cancelled() is True
    finally:
        reset_cancel_check(tok)
    assert cancelled() is False


def test_subagent_confirm_rejects_when_expanded():
    tok = _expanded_cv.set(True)
    try:
        out = _auto_confirm(_Spec("confirm"), {"path": "a.py"})
        assert out.startswith("reject:")
        guard = _auto_confirm(_Spec("guard"), {})
        assert guard.startswith("reject:")
    finally:
        _expanded_cv.reset(tok)
    tok2 = _expanded_cv.set(False)
    try:
        assert _auto_confirm(_Spec("confirm"), {}) == "yes"
    finally:
        _expanded_cv.reset(tok2)
    assert "write_file" not in _READONLY_DEFAULT


def test_subagent_classify_boom_rejects():
    class _Boom:
        def effective_tier(self, args):
            raise RuntimeError("boom")

    assert _auto_confirm(_Boom(), {}).startswith("reject:")


def test_trace_clips_and_can_emit(tmp_path, monkeypatch):
    assert enabled()
    assert _clip("a" * 2000).endswith("…")
    emit("probe", note="ok")


def test_batch_abort_helpers_and_remaining_do_not_run():
    """点停后同一批剩余手只补桩，不再 run。"""
    from agent_tools import ToolResult
    import tool_loop

    assert tool_loop._cancel_requested(None) is False
    assert tool_loop._cancel_requested(lambda: False) is False
    assert tool_loop._cancel_requested(lambda: True) is True
    assert tool_loop._cancel_requested(lambda: 1 / 0) is False
    assert tool_loop._should_stub_remaining(True, None) is True
    assert tool_loop._should_stub_remaining(False, lambda: True) is True
    assert tool_loop._is_user_abort(ToolResult(ok=False, output="", error="aborted by user（已杀进程树）"))
    assert tool_loop._is_user_abort(ToolResult(ok=False, output="", error="aborted"))
    assert not tool_loop._is_user_abort(ToolResult(ok=False, output="", error="timeout"))
    stub = tool_loop._abort_stub()
    assert stub.ok is False
    assert tool_loop._is_user_abort(stub)

    ran = []

    def _run_a(_args):
        ran.append("a")
        return ToolResult(ok=False, output="", error="aborted by user（已杀进程树）")

    def _run_b(_args):
        ran.append("b")
        return ToolResult(ok=True, output="should-not-run")

    aborted = False
    cancel_check = lambda: False
    results = []
    for run in (_run_a, _run_b):
        if tool_loop._should_stub_remaining(aborted, cancel_check):
            results.append(tool_loop._abort_stub())
            continue
        result = run({})
        if (not aborted) and (tool_loop._is_user_abort(result) or tool_loop._cancel_requested(cancel_check)):
            aborted = True
        results.append(result)

    assert ran == ["a"]
    assert tool_loop._is_user_abort(results[0])
    assert tool_loop._is_user_abort(results[1])
    assert aborted is True


def test_batch_cancel_flag_stubs_unstarted():
    """cancel_check 在第一只之后变 True · 第二只不进 run。"""
    from agent_tools import ToolResult
    import tool_loop

    ran = []

    def _run_a(_args):
        ran.append("a")
        return ToolResult(ok=True, output="ok")

    def _run_b(_args):
        ran.append("b")
        return ToolResult(ok=True, output="nope")

    aborted = False
    results = []
    for run in (_run_a, _run_b):
        cancel_check = lambda: "a" in ran
        if tool_loop._should_stub_remaining(aborted, cancel_check):
            if not aborted:
                aborted = True
            results.append(tool_loop._abort_stub())
            continue
        result = run({})
        if tool_loop._is_user_abort(result) or tool_loop._cancel_requested(cancel_check):
            aborted = True
        results.append(result)

    assert ran == ["a"]
    assert results[0].ok is True
    assert tool_loop._is_user_abort(results[1])
    assert aborted is True
