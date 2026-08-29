"""Anthropic 循环：卡死检测 + 流式中止。不烧真模型。"""
import json

from tool_loop import (
    _STUCK_INJECT_CAP,
    _STUCK_REPEAT_THRESHOLD,
    _loop_anthropic,
    _stuck_action,
    _stuck_tail_count,
)


class _NS:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class _Stream:
    def __init__(self, events):
        self._events = list(events)
        self.closed = False

    def __iter__(self):
        return iter(self._events)

    def close(self):
        self.closed = True


class _Client:
    def __init__(self, batches):
        self.messages = self
        self.batches = [list(b) for b in batches]
        self.calls = 0

    def create(self, **kwargs):
        assert kwargs.get("stream") is True
        self.calls += 1
        return _Stream(self.batches.pop(0))


def _usage(**kw):
    return _NS(
        input_tokens=kw.get("input_tokens", 1),
        output_tokens=kw.get("output_tokens", 1),
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )


def _events_text(text, stop="end_turn"):
    return [
        _NS(type="message_start", message=_NS(usage=_usage())),
        _NS(type="content_block_start", index=0, content_block=_NS(type="text", text="")),
        _NS(type="content_block_delta", index=0, delta=_NS(type="text_delta", text=text)),
        _NS(type="content_block_stop", index=0),
        _NS(type="message_delta", delta=_NS(stop_reason=stop), usage=_usage()),
        _NS(type="message_stop"),
    ]


def _events_same_tool(n, name="list_apps"):
    ev = [_NS(type="message_start", message=_NS(usage=_usage()))]
    payload = json.dumps({})
    for i in range(n):
        ev.append(_NS(
            type="content_block_start",
            index=i,
            content_block=_NS(type="tool_use", id=f"tu{i}", name=name, input={}),
        ))
        ev.append(_NS(
            type="content_block_delta",
            index=i,
            delta=_NS(type="input_json_delta", partial_json=payload),
        ))
        ev.append(_NS(type="content_block_stop", index=i))
    ev.append(_NS(type="message_delta", delta=_NS(stop_reason="tool_use"), usage=_usage()))
    ev.append(_NS(type="message_stop"))
    return ev


def _run(batches, cancel_check=None, max_iterations=8):
    return _loop_anthropic(
        client=_Client(batches),
        model="claude-test",
        max_tokens=256,
        system="s",
        messages=[{"role": "user", "content": "hi"}],
        confirm=lambda *a, **k: "yes",
        observe=None,
        max_iterations=max_iterations,
        cancel_check=cancel_check,
        allowed_tool_names={"list_apps"},
    )


def test_stuck_helpers():
    assert _stuck_tail_count([]) == ("", 0)
    assert _stuck_tail_count(["a", "b", "b", "b"]) == ("b", 3)
    assert _stuck_action(2, 0) == ""
    assert _stuck_action(_STUCK_REPEAT_THRESHOLD, 0) == "nudge"
    assert _stuck_action(_STUCK_REPEAT_THRESHOLD, _STUCK_INJECT_CAP) == "break"


def test_anthropic_stuck_nudge_then_stop():
    final, msgs, _usage = _run([
        _events_same_tool(3),
        _events_text("换思路了"),
    ])
    blob = json.dumps(msgs, ensure_ascii=False)
    assert "这很像死循环" in blob
    assert "换思路了" in final


def test_anthropic_stream_cancel_stops_create():
    seen = {"n": 0}

    def cancel():
        return seen["n"] > 0

    class _Counting:
        def __init__(self, events):
            self._events = list(events)

        def __iter__(self):
            for ev in self._events:
                seen["n"] += 1
                yield ev

        def close(self):
            pass

    class _C:
        def __init__(self):
            self.messages = self
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            return _Counting(_events_text("partial-hello"))

    client = _C()
    final, _msgs, _u = _loop_anthropic(
        client=client,
        model="claude-test",
        max_tokens=256,
        system="s",
        messages=[{"role": "user", "content": "hi"}],
        confirm=lambda *a, **k: "yes",
        observe=None,
        max_iterations=4,
        cancel_check=cancel,
        allowed_tool_names=set(),
    )
    assert client.calls == 1
    assert "partial-hello" in (final or "") or "aborted" in (final or "").lower()
