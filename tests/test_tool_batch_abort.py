"""点停后同一批剩余手只补桩，不再 run。"""
from agent_tools import ToolResult
import tool_loop


def test_batch_abort_helpers_and_remaining_do_not_run():
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
