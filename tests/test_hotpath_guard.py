from agent_tools._hotpath_guard import (
    begin_turn,
    block_clipboard_write,
    block_shell,
    fetch_precheck,
    mark_scenario_read,
    note_fetch_status,
    require_scenario,
    set_channel,
)


def test_block_python_c():
    begin_turn()
    assert block_shell('python -c "print(1)"')
    assert block_shell('py -3 -c "print(1)"')


def test_allow_python_version():
    begin_turn()
    assert block_shell("python --version") is None


def test_block_get_content_dump():
    begin_turn()
    assert block_shell("Get-Content foo.py")
    assert block_shell("Get-Content foo.py | Measure-Object -Line") is None


def test_block_taskkill_python():
    begin_turn()
    assert block_shell("taskkill /F /IM python.exe")
    assert block_shell("Stop-Process -Name python")


def test_clipboard_wechat_only():
    begin_turn()
    assert block_clipboard_write() is None
    set_channel("wechat")
    assert block_clipboard_write()


def test_fetch_stops_after_two():
    begin_turn()
    assert fetch_precheck() is None
    assert note_fetch_status(403, "", "https://a.example") is None
    assert note_fetch_status(401, "", "https://b.example")
    assert fetch_precheck()


def test_require_scenario_this_turn_only():
    begin_turn()
    assert require_scenario("app_creation")
    mark_scenario_read("app_creation")
    assert require_scenario("app_creation") is None
    begin_turn()
    assert require_scenario("app_creation")


def test_mark_from_copied_context_reaches_parent():
    """并行 AUTO 用 copy_context 进线程；闸必须是同一份 set，不能 frozenset+set。"""
    import concurrent.futures
    import contextvars

    begin_turn()

    def _mark():
        mark_scenario_read("app_creation")

    ctx = contextvars.copy_context()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        ex.submit(ctx.run, _mark).result()
    assert require_scenario("app_creation") is None


def test_parallel_read_scenario_unblocks_sibling_and_parent():
    """同批 read_scenario + 闸工具：先落地再并行，主线程随后也能看见。"""
    from agent_tools import TIER_AUTO, ToolResult, ToolSpec
    from agent_tools.read_scenario import SPEC as READ
    import tool_loop

    begin_turn()

    def _req(_args):
        err = require_scenario("app_creation")
        if err:
            return ToolResult(ok=False, output="", error=err)
        return ToolResult(ok=True, output="ok")

    probe = ToolSpec(
        name="probe_gate",
        description="gate probe",
        tier=TIER_AUTO,
        input_schema={"type": "object", "properties": {}},
        run=_req,
        summarize=lambda _a: "probe_gate",
    )
    dummy = ToolSpec(
        name="probe_dummy",
        description="batch filler",
        tier=TIER_AUTO,
        input_schema={"type": "object", "properties": {}},
        run=lambda _a: ToolResult(ok=True, output="d"),
        summarize=lambda _a: "probe_dummy",
    )
    res = tool_loop._maybe_parallel_auto(
        [
            (READ, {"name": "app_creation"}, "read_scenario"),
            (probe, {}, "probe_gate"),
            (dummy, {}, "probe_dummy"),
        ],
        None,
    )
    assert res[0].ok, res[0].error
    assert res[1].ok, res[1].error
    assert require_scenario("app_creation") is None


def test_read_scenario_in_worker_unblocks_parent():
    """模拟旧并行路：read_scenario 整只在 copy_context worker 里跑，主线程闸仍开。"""
    import concurrent.futures
    import contextvars

    from agent_tools.read_scenario import SPEC as READ

    begin_turn()
    ctx = contextvars.copy_context()

    def _run():
        return READ.run({"name": "app_creation"})

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        r = ex.submit(ctx.run, _run).result()
    assert r.ok, r.error
    assert require_scenario("app_creation") is None
