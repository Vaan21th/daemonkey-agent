"""对话内 checkpoint：回到某一句 + 撤其后的工具改文件。"""
from __future__ import annotations

import json
import time
from pathlib import Path


def _boot(tmp_path, monkeypatch):
    import workers.turn_checkpoint as tc

    monkeypatch.setattr(tc, "ROOT", tmp_path)
    monkeypatch.setattr(tc, "SNAP_ROOT", tmp_path / "snaps")
    sess = tmp_path / "sessions"
    sess.mkdir()

    def fake_path(sid: str) -> Path:
        return sess / f"{sid}.jsonl"

    monkeypatch.setattr("daemon_session.session_path", fake_path)
    return tc, fake_path


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )


def test_edit_two_turns_restore_first(tmp_path, monkeypatch):
    tc, sp = _boot(tmp_path, monkeypatch)
    sid = "api-ckpt1"
    f = tmp_path / "foo.txt"
    f.write_text("v1", encoding="utf-8")
    tc.snapshot_before("foo.txt", sid=sid, turn_id="turn-aaa")
    f.write_text("v2", encoding="utf-8")
    tc.snapshot_before("foo.txt", sid=sid, turn_id="turn-bbb")
    f.write_text("v3", encoding="utf-8")
    _write_jsonl(sp(sid), [
        {"role": "user", "content": "a", "meta": {"turn_id": "turn-aaa"}},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "b", "meta": {"turn_id": "turn-bbb"}},
        {"role": "assistant", "content": "ok2"},
    ])
    out = tc.restore(sid, "turn-aaa")
    assert out["ok"]
    assert f.read_text(encoding="utf-8") == "v1"
    assert "foo.txt" in out["restored"]
    lines = [json.loads(x) for x in sp(sid).read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == 1
    assert lines[0]["meta"]["turn_id"] == "turn-aaa"


def test_create_then_restore_deletes(tmp_path, monkeypatch):
    tc, sp = _boot(tmp_path, monkeypatch)
    sid = "api-ckpt2"
    f = tmp_path / "new.txt"
    assert not f.exists()
    tc.snapshot_before("new.txt", sid=sid, turn_id="turn-c")
    f.write_text("born", encoding="utf-8")
    _write_jsonl(sp(sid), [
        {"role": "user", "content": "make", "meta": {"turn_id": "turn-c"}},
        {"role": "assistant", "content": "done"},
    ])
    out = tc.restore(sid, "turn-c")
    assert out["ok"]
    assert not f.exists()
    assert "new.txt" in out["deleted"]


def test_same_turn_only_first_snapshot(tmp_path, monkeypatch):
    tc, _ = _boot(tmp_path, monkeypatch)
    sid = "api-ckpt3"
    f = tmp_path / "x.txt"
    f.write_text("a", encoding="utf-8")
    tc.snapshot_before("x.txt", sid=sid, turn_id="turn-1")
    f.write_text("b", encoding="utf-8")
    tc.snapshot_before("x.txt", sid=sid, turn_id="turn-1")
    ledger = tc._read_ledger(sid)
    assert len([e for e in ledger if e.get("path") == "x.txt"]) == 1


def test_blocked_env_no_snapshot(tmp_path, monkeypatch):
    tc, _ = _boot(tmp_path, monkeypatch)
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")
    tc.snapshot_before(".env", sid="api-ckpt4", turn_id="turn-1")
    assert tc._read_ledger("api-ckpt4") == []


def test_foreign_session_skipped(tmp_path, monkeypatch):
    tc, sp = _boot(tmp_path, monkeypatch)
    sid = "api-ckpt5"
    f = tmp_path / "shared.txt"
    f.write_text("old", encoding="utf-8")
    tc.snapshot_before("shared.txt", sid=sid, turn_id="turn-1")
    f.write_text("new", encoding="utf-8")
    monkeypatch.setattr(
        "workers.edit_attribution.lookup",
        lambda p: {"session": "api-other", "ts": time.time()},
    )
    plan = tc.preview(sid, "turn-1")
    assert plan["skip"]
    _write_jsonl(sp(sid), [
        {"role": "user", "content": "x", "meta": {"turn_id": "turn-1"}},
        {"role": "assistant", "content": "y"},
    ])
    out = tc.restore(sid, "turn-1")
    assert f.read_text(encoding="utf-8") == "new"
    assert out["restored"] == []
    assert out["truncated"] is True


def test_truncate_by_line_old_session(tmp_path, monkeypatch):
    tc, sp = _boot(tmp_path, monkeypatch)
    sid = "api-ckpt6"
    _write_jsonl(sp(sid), [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "a"},
        {"role": "user", "content": "two"},
        {"role": "assistant", "content": "b"},
    ])
    assert tc.truncate_session(sid, keep_line=0)
    lines = [json.loads(x) for x in sp(sid).read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == 1
    assert lines[0]["content"] == "one"
    plan = tc.preview(sid, "")
    assert plan["has_snaps"] is False


def test_drop_keep_cuts_the_edited_user_line(tmp_path, monkeypatch):
    tc, sp = _boot(tmp_path, monkeypatch)
    sid = "api-ckpt7"
    _write_jsonl(sp(sid), [
        {"role": "user", "content": "one", "meta": {"turn_id": "turn-a"}},
        {"role": "assistant", "content": "a"},
        {"role": "user", "content": "two", "meta": {"turn_id": "turn-b"}},
        {"role": "assistant", "content": "b"},
    ])
    assert tc.truncate_session(sid, keep_turn_id="turn-b", drop_keep=True)
    lines = [json.loads(x) for x in sp(sid).read_text(encoding="utf-8").splitlines() if x.strip()]
    assert [x["content"] for x in lines] == ["one", "a"]
