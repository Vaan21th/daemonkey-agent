"""tests/test_memory_compression.py

测 workers/memory_compression 的 token 估算 + 压缩触发逻辑。

wish-83fe7c7b · 卷五十四 加:
  - tiktoken 可选路径（有则精确 · 无则 fallback）
  - 动态窗口阈值（按模型 context_window × ratio）
  - 自适应 keep_last_n
  - 退化路径（model_id=None 时行为不变）
"""

from __future__ import annotations

from pathlib import Path

import pytest

from workers import memory_compression as mc


@pytest.fixture(autouse=True)
def _reset_cooldown(monkeypatch, tmp_path):
    """每个 case 隔离 cooldown 状态 · 环境变量也隔离 · 前缀估算不真 load 灵魂"""
    st = {
        "current_sid": "",
        "last_compression_turn": -mc.COOLDOWN_TURNS,
        "compression_count": 0,
        "consecutive_compacts": 0,
        "last_prune_turn": -mc.COOLDOWN_TURNS,
    }
    mc._SESSION_STATE.set(st)
    monkeypatch.setattr(mc, "estimate_prefix_tokens", lambda: 0)
    monkeypatch.setattr("workers.provider_configs.window_for_model", lambda mid: 0)
    monkeypatch.delenv("OPUS_AUTO_COMPACT_THRESHOLD", raising=False)
    monkeypatch.delenv("OPUS_AUTO_COMPACT_RATIO", raising=False)
    # 0.9.x · 隔离 WebUI 的压缩绝对线 (data/runtime/compact_cap.json)
    # 本机用户把 CAP 改过(如 512K) 会抬高绝对线 · 测试造的数据就不够触发 → 假失败
    monkeypatch.setattr(mc, "read_cap_override", lambda: 0)
    # wish-accd038a · 埋点隔离: 压缩测试不许往真实 compress_events.jsonl 写
    # 否则单测产生的事件会混进用户的对照窗口 → 污染真实数据 (测试目的就是让数据可信)
    monkeypatch.setattr(mc, "_COMPRESS_EVENTS_PATH", Path(tmp_path) / "compress_events.jsonl")
    yield


def _make_msg(role: str, content: str) -> dict:
    return {"role": role, "content": content}


# ═══════════════  token 估算  ═══════════════

def test_estimate_tokens_empty():
    assert mc._estimate_tokens([]) == 0


def test_estimate_tokens_basic():
    msgs = [_make_msg("user", "你好" * 30)]  # 60 字符 CJK
    est = mc._estimate_tokens(msgs)
    # v2 (卷七十三): 60 CJK × 1.0 × 1.25 + 6×1.25 ≈ 81
    assert 70 <= est <= 95


def test_estimate_tokens_english():
    msgs = [_make_msg("user", "hello world " * 20)]  # 240 ASCII 字符
    est = mc._estimate_tokens(msgs)
    # 240 ASCII * 0.25 + 5 = 60 + 5 = 65
    assert 55 <= est <= 75


def test_estimate_tokens_mixed():
    msgs = [_make_msg("user", "你好hello世界world" * 10)]  # 混合
    est = mc._estimate_tokens(msgs)
    assert est >= 30


def test_estimate_tokens_tool_calls():
    msgs = [
        {
            "role": "assistant",
            "content": "thinking",
            "tool_calls": [{"function": {"arguments": "x" * 300}}],
        }
    ]
    est = mc._estimate_tokens(msgs)
    # v2: cl100k BPE 对重复 x 合并 (300 x ≈ 38 tok) × 1.25 + overhead ≈ 55
    assert est >= 40


# ═══════════════  token_budget_check (老行为 · 退化路径)  ═══════════════

def test_budget_check_default_off():
    """没设 env · 短消息远低于 25.6 万绝对线 · 不触发"""
    msgs = [_make_msg("user", "hi") for _ in range(5)]
    assert mc.token_budget_check(msgs) is False


def test_budget_check_short_msgs_no_longer_count_thirty():
    """认不出窗户也不再数 30 条 · 35 条短消息不压"""
    msgs = [_make_msg("user", "hi") for _ in range(35)]
    assert mc.token_budget_check(msgs) is False
    assert mc.token_budget_check(msgs, model_id="nonexistent-model-xyz") is False


def test_budget_check_token_trigger_with_env(monkeypatch):
    """env OPUS_AUTO_COMPACT_THRESHOLD 显式设了 · 应token触发"""
    monkeypatch.setenv("OPUS_AUTO_COMPACT_THRESHOLD", "50")
    msgs = [_make_msg("user", "x" * 500)]  # cl100k BPE: 63 tok × 1.25 ≈ 85 ≥ 50
    assert mc.token_budget_check(msgs) is True


def test_budget_check_token_under_threshold(monkeypatch):
    """env token 阈值过高 · 不触发"""
    monkeypatch.setenv("OPUS_AUTO_COMPACT_THRESHOLD", "10000")
    msgs = [_make_msg("user", "x" * 500)]
    assert mc.token_budget_check(msgs) is False


def test_budget_check_invalid_env(monkeypatch):
    """env 设了非法值 · 走 token 绝对线 · 短消息不压"""
    monkeypatch.setenv("OPUS_AUTO_COMPACT_THRESHOLD", "not-a-number")
    msgs = [_make_msg("user", "hi") for _ in range(5)]
    assert mc.token_budget_check(msgs) is False


def test_budget_check_zero_means_disabled(monkeypatch):
    """env=0 等同于没设 · 走绝对线 · 一条远不够 25.6 万"""
    monkeypatch.setenv("OPUS_AUTO_COMPACT_THRESHOLD", "0")
    msgs = [_make_msg("user", "x" * 100000)]
    assert mc.token_budget_check(msgs) is False


def test_budget_check_cooldown_blocks(monkeypatch):
    """刚压缩过 · cooldown 内即使过阈值也不再触发"""
    monkeypatch.setenv("OPUS_AUTO_COMPACT_THRESHOLD", "50")
    msgs = [_make_msg("user", "x" * 500) for _ in range(31)]
    mc._state()["last_compression_turn"] = 30
    assert mc.token_budget_check(msgs) is False


# ═══════════════  token_budget_check (新行为 · 动态窗口)  ═══════════════

def test_budget_check_dynamic_window_triggers(monkeypatch):
    """model_id=deepseek (1M window) · 大量消息应触发 (0.8.8 绝对线 256K)

    老设计: 1M*0.7=700K 阈值 → 60条×375K 不触发 (测试断言 False)
    0.8.8: 绝对线 256K → 375K ≥ 256K 触发 (治大窗口普通会话永不压缩)
    """
    monkeypatch.setattr(mc, "_last_compression_turn", -mc.COOLDOWN_TURNS, raising=False)
    msgs = [_make_msg("user", "你好世界" * 1000) for _ in range(60)]
    # tiktoken 精确估算 60 条 ≈ 375K ≥ 绝对线 256K → 触发
    assert mc.token_budget_check(msgs, model_id="deepseek-v4-pro") is True


def test_budget_check_small_window_triggers_sooner(monkeypatch):
    """model_id=haiku (200K window) · 同样消息更容易触发"""
    monkeypatch.setattr(mc, "_last_compression_turn", -mc.COOLDOWN_TURNS, raising=False)
    # 200K * 0.6 = 120K · 60条 * 3600 = 216K → 应触发
    msgs = [_make_msg("user", "你好世界" * 1000) for _ in range(60)]
    assert mc.token_budget_check(msgs, model_id="claude-haiku-4-5-20251022") is True


def test_budget_check_unknown_model_uses_abs_cap(monkeypatch):
    """认不出窗户 · 肥历史过 25.6 万绝对线才压 · 不数条数"""
    msgs = [_make_msg("user", "你好世界" * 1000) for _ in range(60)]
    assert mc._estimate_tokens(msgs) >= 256_000
    assert mc.token_budget_check(msgs, model_id="nonexistent-model-xyz") is True


def test_user_config_window_overrides_catalog(monkeypatch):
    """配置里填了窗户 · 压过目录"""
    monkeypatch.setattr("workers.provider_configs.window_for_model",
                        lambda mid: 32_000 if mid == "custom-new-xyz" else 0)
    assert mc._get_context_window("custom-new-xyz") == 32_000
    assert mc._get_context_window("deepseek-v4-flash") == 1_000_000
    msgs = [_make_msg("user", "你好世界" * 1000) for _ in range(60)]
    assert mc.token_budget_check(msgs, model_id="custom-new-xyz") is True


def test_budget_check_custom_ratio(monkeypatch):
    """OPUS_AUTO_COMPACT_RATIO=0.3 · 更难触发"""
    monkeypatch.setenv("OPUS_AUTO_COMPACT_RATIO", "0.3")
    monkeypatch.setattr(mc, "_last_compression_turn", -mc.COOLDOWN_TURNS, raising=False)
    # 200K * 0.3 = 60K · 60条 * 3600 = 216K → 仍触发
    msgs = [_make_msg("user", "你好世界" * 1000) for _ in range(60)]
    assert mc.token_budget_check(msgs, model_id="claude-haiku-4-5-20251022") is True


# ═══════════════  自适应 keep_last_n  ═══════════════

def test_adaptive_keep_last_n_fallback():
    """model_id=None → 退化为 DEFAULT_KEEP_LAST_N=8"""
    msgs = [_make_msg("user", "hi") for _ in range(40)]
    n = mc._adaptive_keep_last_n(msgs, model_id=None, caller_keep_last_n=None)
    assert n == mc.DEFAULT_KEEP_LAST_N


def test_adaptive_keep_last_n_explicit_wins():
    """caller 显式传了 → 用它"""
    msgs = [_make_msg("user", "hi") for _ in range(40)]
    n = mc._adaptive_keep_last_n(msgs, model_id="deepseek-v4-pro", caller_keep_last_n=15)
    assert n == 15


def test_adaptive_keep_last_n_within_bounds():
    """自适应值应在 [4, 20] 范围内"""
    msgs = [_make_msg("user", "hi") for _ in range(100)]
    n = mc._adaptive_keep_last_n(msgs, model_id="claude-haiku-4-5-20251022", caller_keep_last_n=None)
    assert mc.MIN_KEEP_LAST_N <= n <= mc.MAX_KEEP_LAST_N


def test_adaptive_keep_last_n_large_window_yields_more():
    """大窗口 → 更多保留条数"""
    msgs = [_make_msg("user", "短消息") for _ in range(40)]
    n_deepseek = mc._adaptive_keep_last_n(msgs, model_id="deepseek-v4-pro", caller_keep_last_n=None)
    n_haiku = mc._adaptive_keep_last_n(msgs, model_id="claude-haiku-4-5-20251022", caller_keep_last_n=None)
    # deepseek 1M 窗口 → 应 >= haiku 200K 窗口
    assert n_deepseek >= n_haiku


# ═══════════════  退化路径 · 行为不变  ═══════════════

def test_no_model_id_short_history_does_not_compact():
    """不传 model_id · 短历史走绝对线 · 不再满 30 条就压"""
    msgs = [_make_msg("user", "hi") for _ in range(5)]
    assert mc.token_budget_check(msgs) is False
    msgs35 = [_make_msg("user", "hi") for _ in range(35)]
    assert mc.token_budget_check(msgs35) is False


# ═══════════════  v2 · Reasonix 移植 (wish-7f0adf2c)  ═══════════════

def _mk_tool_heavy_msgs():
    """构造: 早段 user + 10 组大工具结果 + 中场 user + 3 组近段工具 + 尾 user

    最近 2 个 user 回合保活 · 早段 10 组可 prune / diet。
    """
    import json as _json
    msgs = [_make_msg("user", "开始任务")]
    for i in range(10):
        msgs.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": f"call_{i}", "type": "function",
             "function": {"name": "read_file", "arguments": _json.dumps({"path": f"f{i}.py"})}}]})
        msgs.append({"role": "tool", "tool_call_id": f"call_{i}", "content": "x" * 3000})
        msgs.append(_make_msg("assistant", f"已读 f{i}.py"))
    msgs.append(_make_msg("user", "中场"))
    for i in range(10, 13):
        msgs.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": f"call_{i}", "type": "function",
             "function": {"name": "read_file", "arguments": _json.dumps({"path": f"f{i}.py"})}}]})
        msgs.append({"role": "tool", "tool_call_id": f"call_{i}", "content": "x" * 3000})
        msgs.append(_make_msg("assistant", f"已读 f{i}.py"))
    msgs.append(_make_msg("user", "继续下一步"))
    return msgs


def test_pinnable_user_turn_small_ok():
    m = _make_msg("user", "hi")
    assert mc._pinnable_user_turn(m, 1_000_000) is True


def test_pinnable_user_turn_huge_rejected():
    m = _make_msg("user", "x" * 100_000)
    assert mc._pinnable_user_turn(m, 1_000_000) is False


def test_partition_fold_keeps_user_turns():
    """用户 turn 进 kept · 工具往返进 fold"""
    msgs = _mk_tool_heavy_msgs()
    kept, fold = mc._partition_fold(msgs, 1_000_000)
    assert any(m.get("role") == "user" for m in kept)
    assert any(m.get("role") == "tool" for m in fold)


def test_tail_start_aligns_tool_boundary():
    """tail 起点不能是孤儿 tool 消息"""
    msgs = _mk_tool_heavy_msgs()
    head = mc._pinned_prefix_len(msgs, 1_000_000)
    start = mc._tail_start(msgs, head, 5000)
    if start < len(msgs):
        assert msgs[start].get("role") != "tool"


def test_prune_stale_tool_results_basic(tmp_path, monkeypatch):
    """大工具结果被修剪 → placeholder + 归档 + 幂等

    2026-09-19 修红：wish-a5f77893 刀2 加了「最近 PRUNE_PROTECT_TOKENS(30k) tok 不剪」。
    本测试样本总量远小于 30k → 保护起点被压到 0 → 全保护 → 不剪。
    这是**对的**行为（小会话本来就不该剪）· 要验剪枝逻辑本身就得先关掉这个保护
    （budget<=0 = 不启用保护）。
    """
    monkeypatch.setattr(mc, "PRUNE_PROTECT_TOKENS", 0)
    mc._state()["current_sid"] = "test-prune"
    monkeypatch.setattr(mc, "_ARCHIVE_DIR", tmp_path)
    msgs = _mk_tool_heavy_msgs()
    new_msgs, stats = mc.prune_stale_tool_results(msgs)
    assert stats["pruned"] > 0
    assert stats["archive"] is not None
    pruned_content = [m["content"] for m in new_msgs
                      if m.get("role") == "tool" and mc.PRUNED_MARKER in m["content"]]
    assert len(pruned_content) == stats["pruned"]
    # 幂等
    new2, stats2 = mc.prune_stale_tool_results(new_msgs)
    assert stats2["pruned"] == 0


def test_prune_keeps_error_results():
    """错误结果保命 (排障线索)"""
    msgs = _mk_tool_heavy_msgs()
    msgs[2]["content"] = "error: 权限不足"
    new_msgs, _ = mc.prune_stale_tool_results(msgs)
    assert any(m.get("content") == "error: 权限不足" for m in new_msgs)


def test_mechanical_fold_fallback(tmp_path, monkeypatch):
    """摘要失败 → 机械折叠兜底 (归档仍存在 · 不崩)"""
    mc._state()["current_sid"] = "test-mech"
    monkeypatch.setattr(mc, "_ARCHIVE_DIR", tmp_path)
    # v3 · _persist_rewrite 多了 full_messages 参数 → mock 要能吃可变参数
    monkeypatch.setattr(mc, "_persist_rewrite", lambda m, *a, **k: None)  # 避免真写 sessions/
    # 2026-09-19 (wish-98d77aaf 顺带) · 本测试造的消息量(160 条 / ~17k tok)在真实模型
    # 窗口下已【不再触发压缩】—— deepseek-v4-flash 被认成 1M 窗口, 触发线高达 281k。
    # 但本测试验的是「摘要失败会不会机械折叠兜底」, 前提是【压缩真的走到摘要步】。
    # 钉一个人为小窗(8K)让前提重新成立 —— 测的是兜底逻辑, 不是真实模型容量。
    monkeypatch.setattr(mc, "_get_context_window", lambda *a, **k: 8_000)

    # 构造: 工具结果 1000 字符 (< PRUNE_MIN_CHARS 1024 · 不触发 prune 提前清警报)
    # 但累积体积足够 → 折叠区有内容 → 压缩走到摘要步
    def _mk_foldable():
        msgs = [_make_msg("user", "开始任务")]
        for i in range(10):
            msgs.append({"role": "assistant", "content": None, "tool_calls": [
                {"id": f"c{i}", "type": "function",
                 "function": {"name": "read_file", "arguments": '{"path":"f"}'}}]})
            msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": "y" * 1000})
            msgs.append(_make_msg("assistant", "ok"))
        msgs.append(_make_msg("user", "继续"))
        return msgs

    def _boom(*a, **k):
        raise RuntimeError("summary llm down")
    monkeypatch.setattr(mc, "_generate_summary", _boom)

    msgs = _mk_foldable() * 5
    new_msgs = mc.auto_compress(msgs, object(), "deepseek-v4-flash", "openai",
                                model_id="deepseek-v4-flash", force=True)
    assert new_msgs is not msgs
    assert any(mc.SUMMARY_TAG_OPEN in (m.get("content") or "") for m in new_msgs)


def test_economics_skips_small_fold(monkeypatch):
    """折叠区太小 → 0 次 LLM 调用"""
    calls = {"n": 0}

    def _counting(*a, **k):
        calls["n"] += 1
        return "摘要"
    monkeypatch.setattr(mc, "_generate_summary", _counting)

    msgs = [_make_msg("user", "a"), _make_msg("assistant", "b"), _make_msg("user", "c")] * 6
    new_msgs = mc.auto_compress(msgs, object(), "deepseek-v4-flash", "openai",
                                model_id="deepseek-v4-flash", force=False)
    assert calls["n"] == 0
    assert new_msgs is msgs


def test_note_real_usage_clamp():
    """荒谬比例拒收 · 正常比例接收"""
    mc.note_real_usage(prompt_tokens=10, messages=[_make_msg("user", "x")])  # 10/1=10 → 拒收
    mc.note_real_usage(prompt_tokens=100, messages=[_make_msg("user", "x" * 100)])  # 1.0 → 收
    r = mc._tok_per_char()
    assert 0.05 < r < 2


# ═══════════════  2026-08-28 三刀  ═══════════════

def test_flash_vision_exp_has_1m_window():
    from provider_presets import context_window_for
    assert context_window_for("deepseek-v4-flash-vision-exp") == 1_000_000
    assert context_window_for("deepseek-v4-flash") == 1_000_000
    assert context_window_for("deepseek-v4-pro") == 1_000_000


def test_flash_vision_exp_does_not_compact_on_30_short_msgs():
    """旧洞: id 对不上 → 窗口 0 → 满 30 条就压。修好后短消息不压。"""
    msgs = [_make_msg("user", "hi") for _ in range(35)]
    assert mc.token_budget_check(msgs, model_id="deepseek-v4-flash-vision-exp") is False


def test_prefix_counts_toward_small_window(monkeypatch):
    """小窗口: 历史单独不够线 · 加上前缀就该压

    v3 · 断言跟随当前触发线(不再硬编码 0.7 时代的 140K) —— 调 ratio 不该让本测试误红。
    """
    monkeypatch.setattr(mc, "estimate_prefix_tokens", lambda: 80_000)
    _win = mc._get_context_window("claude-haiku-4-5-20251022")
    _line = int(_win * mc._get_ratio())
    msgs = [_make_msg("user", "你好世界" * 400) for _ in range(40)]
    hist = mc._estimate_tokens(msgs)
    assert hist < _line, f"历史 {hist} 应小于线 {_line} (样本量需调)"
    assert hist + 80_000 >= _line, f"历史+前缀 {hist + 80_000} 应 >= 线 {_line} (样本量需调)"
    assert mc.token_budget_check(msgs, model_id="claude-haiku-4-5-20251022") is True


def test_compact_threshold_prefix_eats_tiny_window():
    """视觉 16K：前缀已经大于窗×0.7 · 开火线改走前缀+25.6 万，不拿 11K 当永久过线。"""
    cap = mc._get_abs_cap()
    assert mc._compact_threshold(16_384, 80_000) == 80_000 + cap
    assert mc._compact_threshold(200_000, 80_000) == int(200_000 * mc._get_ratio())  # v3 · 随触发线
    assert mc._compact_threshold(0, 80_000) == 80_000 + cap


def test_tiny_window_fat_prefix_short_history_no_compact(monkeypatch):
    """glm-5v-turbo 16K + 肥前缀 + 短历史：旧口径每轮空转摘要。"""
    monkeypatch.setattr(mc, "estimate_prefix_tokens", lambda: 80_000)
    msgs = [_make_msg("user", "hi") for _ in range(35)]
    assert mc.token_budget_check(msgs, model_id="glm-5v-turbo") is False


def test_tiny_window_fat_history_still_compacts(monkeypatch):
    """前缀撑满小窗之后，历史自己过绝对线仍该压。"""
    monkeypatch.setattr(mc, "estimate_prefix_tokens", lambda: 80_000)
    monkeypatch.setattr(mc, "_estimate_tokens", lambda _msgs: 256_000)
    msgs = [_make_msg("user", "x") for _ in range(10)]
    assert mc.token_budget_check(msgs, model_id="glm-5v-turbo") is True


def test_tail_protect_index_last_two_users():
    msgs = [
        _make_msg("user", "u1"),
        {"role": "tool", "content": "old"},
        _make_msg("user", "u2"),
        {"role": "tool", "content": "mid"},
        _make_msg("user", "u3"),
        {"role": "tool", "content": "new"},
    ]
    assert mc.tail_protect_index(msgs) == 2


def test_diet_spares_last_two_user_turns():
    from tool_loop import _diet_messages_for_send
    old = "Z" * 20000
    live = "N" * 20000
    msgs = [
        _make_msg("user", "u1"),
        {"role": "tool", "tool_call_id": "a", "content": old},
        _make_msg("user", "u2"),
        {"role": "tool", "tool_call_id": "b", "content": live},
        _make_msg("user", "u3"),
        {"role": "tool", "tool_call_id": "c", "content": live},
    ]
    out = _diet_messages_for_send(msgs)
    assert "省略" in (out[1].get("content") or "")
    assert out[3]["content"] == live
    assert out[5]["content"] == live


def test_diet_keeps_head_drops_middle():
    """变笨边界: 旧工具头还在 · 中间没有 · 当轮全文还在"""
    from tool_loop import _diet_messages_for_send
    head = "UNIQUE_HEAD_9f3a"
    mid = "UNIQUE_MID_7c21"
    old = head + ("Z" * 12000) + mid + ("Z" * 12000)
    live = "UNIQUE_LIVE_4e08" + ("N" * 20000)
    msgs = [
        _make_msg("user", "u1"),
        {"role": "tool", "tool_call_id": "a", "content": old},
        _make_msg("user", "u2"),
        {"role": "tool", "tool_call_id": "b", "content": live},
        _make_msg("user", "u3"),
        {"role": "tool", "tool_call_id": "c", "content": live},
    ]
    out = _diet_messages_for_send(msgs)
    dieted = out[1]["content"]
    assert head in dieted
    assert mid not in dieted
    assert "UNIQUE_LIVE_4e08" in out[5]["content"]


def test_diet_saves_vs_old_eight_message_tail():
    """对照旧 KEEP_TAIL=8: 早段 15 个大工具时新口径省得更多 · 近两回合仍全文"""
    from tool_loop import _diet_messages_for_send, _diet_tool_text
    blob = "Q" * 20000
    msgs = [_make_msg("user", "start")]
    for i in range(15):
        msgs.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": f"c{i}", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": blob})
    msgs.append(_make_msg("user", "mid"))
    msgs.append({"role": "tool", "tool_call_id": "mid", "content": blob})
    msgs.append(_make_msg("user", "now"))
    msgs.append({"role": "tool", "tool_call_id": "now", "content": blob})

    new_out = _diet_messages_for_send(msgs)
    cap = 8000
    old_out = []
    cutoff = len(msgs) - 8
    for i, m in enumerate(msgs):
        if i >= cutoff or m.get("role") != "tool":
            old_out.append(m)
            continue
        c2, ch = _diet_tool_text(m.get("content"), cap)
        nm = dict(m)
        if ch:
            nm["content"] = c2
        old_out.append(nm)

    def _chars(ms):
        return sum(len(m.get("content") or "") for m in ms if isinstance(m, dict))

    assert _chars(new_out) < _chars(old_out)
    assert new_out[-1]["content"] == blob
    assert "省略" in (new_out[2].get("content") or "")


def test_prune_if_needed_skips_tiny_save(monkeypatch, tmp_path):
    monkeypatch.setattr(mc, "_ARCHIVE_DIR", tmp_path)
    mc._state()["current_sid"] = "t"
    monkeypatch.setattr(mc, "MIN_PRUNE_SAVED_CHARS", 10 ** 9)
    monkeypatch.setattr(mc, "PRUNE_HISTORY_PRESSURE", 1)
    msgs = _mk_tool_heavy_msgs()
    out = mc.prune_if_needed(msgs, model_id="deepseek-v4-flash")
    assert out is msgs


def test_prune_if_needed_persists_when_worth_it(monkeypatch, tmp_path):
    monkeypatch.setattr(mc, "PRUNE_PROTECT_TOKENS", 0)  # 同 basic · 关掉 30k 保护才验得到剪枝
    monkeypatch.setattr(mc, "_ARCHIVE_DIR", tmp_path)
    monkeypatch.setattr(mc, "_persist_rewrite", lambda m: None)
    mc._state()["current_sid"] = "t"
    monkeypatch.setattr(mc, "MIN_PRUNE_SAVED_CHARS", 100)
    monkeypatch.setattr(mc, "PRUNE_HISTORY_PRESSURE", 1)
    msgs = _mk_tool_heavy_msgs()
    out = mc.prune_if_needed(msgs, model_id="deepseek-v4-flash")
    assert out is not msgs
    assert any(mc.PRUNED_MARKER in (m.get("content") or "") for m in out)


# ---- wish-220071ea · 锚点对齐：content 空串/None 形态折叠 ----
# 病: 磁盘原文 content="" / 内存经 load_session 归一成 None
#     → str() 后 "" ≠ "None" → _find_tail_anchor 永远返 None
#     → 「全量版尾部对齐失败 · 本次不写盘」→ 磁盘水位只涨不落
#     → 实测 b05418 8 次 compact 只成功 1 次，顶穿 102.6%
# 这一段是硬约束: 折叠过头也要防（把不同消息折成同一条会找错锚点）。


def test_msg_key_folds_empty_content_and_none():
    """比对键必须把 "" / None / 纯空白 折叠成同一形态。"""
    a = {"role": "assistant", "content": ""}
    b = {"role": "assistant", "content": None}
    c = {"role": "assistant", "content": "   "}
    assert mc._msg_key(a) == mc._msg_key(b) == mc._msg_key(c)


def test_msg_key_still_distinguishes_real_content():
    """折叠不能过头: 有内容的仍要区分（否则把不同消息判成同一条 → 锚点找错）。"""
    a = {"role": "assistant", "content": "A"}
    b = {"role": "assistant", "content": "B"}
    assert mc._msg_key(a) != mc._msg_key(b)
    # 空 vs 有内容 也必须不同
    assert mc._msg_key({"role": "assistant", "content": ""}) != mc._msg_key(a)


def test_find_tail_anchor_disk_emptystring_vs_memory_none():
    """磁盘 "" ↔ 内存 None: 锚点必须找得到（修复前 100% 返 None）。"""
    tc = [{"id": "t1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]
    disk = [
        _make_msg("user", "问题"),
        {"role": "assistant", "content": "", "tool_calls": tc},
        {"role": "tool", "content": "结果", "tool_call_id": "t1"},
        _make_msg("user", "后续"),
    ]
    mem = [
        _make_msg("user", "问题"),
        {"role": "assistant", "content": None, "tool_calls": tc},
        {"role": "tool", "content": "结果", "tool_call_id": "t1"},
        _make_msg("user", "后续"),
    ]
    # 整段对齐
    assert mc._find_tail_anchor(disk, mem) == 0
    # 只对齐尾部（模拟 messages2[start:]）也要成立
    assert mc._find_tail_anchor(disk, mem[2:]) == 2
    # 锚点确实落在含空 content 那条上 —— 证明折的不是别的地方
    assert mc._find_tail_anchor(disk, mem[1:]) == 1


# ---------------------------------------------------------------------------
# wish-e3c3e379 · 压缩写盘丢历史（磁盘全量版被折叠版顶掉）
#
# 事故链 (2026-09-20 定位):
#   ① daemon_session.load_session 重建消息时不带 compacted 字段
#   ② → _assemble_full_from_disk 里 `if m.get("compacted")` 恒为假
#   ③ → 每次压缩写盘都拿"折叠版"重建磁盘 → 历史(尤其 assistant)被系统性抹掉
#   实测: b05418 磁盘 user:assistant 失衡到 189:65, 发给模型的失衡到 185:18;
#         UI 上表现为「一片我的话、一片你的话」。
# ---------------------------------------------------------------------------


def test_load_session_storage_keeps_compacted_flag(tmp_path, monkeypatch):
    """存储形态必须带回 compacted 标记 · 发给 LLM 的折叠版必须不带。"""
    import json as _json

    import daemon_session

    p = tmp_path / "s.jsonl"
    p.write_text(
        _json.dumps({"role": "user", "content": "活着的问题", "ts": "1"}) + "\n"
        + _json.dumps({"role": "assistant", "content": "已被折走的话", "ts": "2",
                       "compacted": True}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(daemon_session, "session_path", lambda sid: p)

    llm = daemon_session.load_session("s")
    stor = daemon_session.load_session_for_storage("s")

    assert len(llm) == 1, "折叠版应跳过 compacted 行"
    assert all("compacted" not in m for m in llm), "发给 LLM 的消息不许带 compacted 字段"
    assert len(stor) == 2, "存储形态必须连已折走的一起回放"
    assert stor[1].get("compacted") is True, "存储形态丢了 compacted 标记 → 写盘必丢历史"


def test_assemble_full_from_disk_keeps_unmarked_history(monkeypatch):
    """磁盘全量版不许丢【没有 compacted 标记】的历史消息（本次 bug 的正题）。

    旧实现只保留 m.get("compacted") 为真的 → 无标记的老 assistant 被当垃圾丢。
    """
    import daemon_session

    digest = {"role": "user",
              "content": mc.SUMMARY_TAG_OPEN + "\n摘要\n" + mc.SUMMARY_TAG_CLOSE}
    disk = [
        {"role": "user", "content": "问题一", "ts": "1"},
        {"role": "assistant", "content": "回答一·无标记", "ts": "2"},        # ← 关键
        {"role": "user", "content": "问题二", "ts": "3"},
        {"role": "assistant", "content": "回答二·已折走", "ts": "4", "compacted": True},
        {"role": "user", "content": "尾部问题", "ts": "5"},
    ]
    monkeypatch.setattr(daemon_session, "load_session_for_storage", lambda sid: list(disk))
    monkeypatch.setitem(mc._SESSION_STATE.get(), "current_sid", "fake-sid")

    messages2 = [dict(m) for m in disk if not m.get("compacted")]   # 折叠版
    out = mc._assemble_full_from_disk(messages2, 0, 3, dict(digest))

    assert out is not None, "对齐必须成功（不该退回 None）"
    contents = [m.get("content") for m in out]
    assert "回答一·无标记" in contents, "🔴 无标记的历史 assistant 被丢了（本次 bug 复发）"
    assert "回答二·已折走" in contents, "已折走的历史也要留在磁盘"
    assert "尾部问题" in contents, "尾部不能被吞"
    # 顺序：历史在前 · 摘要居中 · 尾部在后
    assert contents.index("回答一·无标记") < contents.index("回答二·已折走")
    assert [m.get("content") for m in out][-1] == "尾部问题"


def test_assemble_marks_this_round_folded(monkeypatch):
    """本轮被折叠的消息必须补 compacted 标记。

    漏了它 → 下次 load_session 把它们当"活着的"重新回放 → 同一段历史既在
    摘要里又在原文里 → 压缩白做、窗口白占。
    """
    import daemon_session

    digest = {"role": "user",
              "content": mc.SUMMARY_TAG_OPEN + "\n摘要\n" + mc.SUMMARY_TAG_CLOSE}
    disk = [
        {"role": "user", "content": "老问题", "ts": "1"},
        {"role": "assistant", "content": "老回答·本轮折走", "ts": "2"},
        {"role": "user", "content": "尾部问题", "ts": "3"},
    ]
    monkeypatch.setattr(daemon_session, "load_session_for_storage", lambda sid: list(disk))
    monkeypatch.setitem(mc._SESSION_STATE.get(), "current_sid", "fake-sid")

    messages2 = [dict(m) for m in disk]
    fold = [messages2[1]]                      # 本轮折叠的只有那条 assistant
    out = mc._assemble_full_from_disk(messages2, 0, 2, dict(digest), fold)

    marked = [m for m in out if m.get("compacted")]
    assert len(marked) == 1, f"应当恰好 1 条被标 · 实得 {len(marked)}"
    assert marked[0].get("content") == "老回答·本轮折走"
    assert not [m for m in out if m.get("compacted")
                and m.get("content") != "老回答·本轮折走"], "不许误标没折的消息"
