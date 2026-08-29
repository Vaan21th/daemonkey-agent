from workers.compact_flush import (
    accept_fact,
    parse_facts,
    recent_transcript,
    flush_before_compact,
)
from workers.notebook_tiers import route_write_section


def test_accept_fact_rejects_dump_and_unknown_section():
    assert accept_fact("rules", "不劝睡，除非他撑不住。")
    assert not accept_fact("rules", "x" * 200)
    assert not accept_fact("nope", "不劝睡")
    assert not accept_fact("rules", "a\n" * 8)


def test_parse_facts_keeps_three_short_bars():
    raw = (
        '{"facts":['
        '{"section":"rules","content":"不劝睡除非撑不住"},'
        '{"section":"events","content":"2026-08-29 猫叫白给"},'
        '{"section":"dialogue","content":"你来定是真释权"},'
        '{"section":"rules","content":"第四条不该进"}'
        "]}"
    )
    facts = parse_facts(raw)
    assert len(facts) == 3
    assert facts[0]["section"] == "rules"


def test_dated_story_routes_to_events():
    assert route_write_section("dialogue", "append", "2026-08-29 · 还在省钱期") == "events"


def test_recent_transcript_skips_compaction_and_tools():
    msgs = [
        {"role": "user", "content": "记住别劝睡"},
        {"role": "assistant", "content": "<compaction-summary>old</compaction-summary>"},
        {"role": "tool", "content": "huge"},
        {"role": "assistant", "content": "好"},
    ]
    text = recent_transcript(msgs)
    assert "别劝睡" in text
    assert "compaction-summary" not in text
    assert "huge" not in text


def test_flush_failure_does_not_raise():
    out = flush_before_compact(
        [{"role": "user", "content": "他现在还在省钱期，别劝我换模型。"}],
        client=None,
        model="x",
        provider="openai",
    )
    assert out["ok"] is False or out.get("skipped")
    assert "wrote" in out
