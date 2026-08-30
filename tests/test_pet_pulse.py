"""桌宠脉搏：工具结束不等于待机。"""


def _boot(tmp_path, monkeypatch):
    import desktop_pet.activities as act

    monkeypatch.setattr(act, "_ACTIVITY_JSONL", tmp_path / "activity.jsonl")
    monkeypatch.setattr(act, "_ACTIVITY_TXT", tmp_path / "activity.txt")
    monkeypatch.setattr(act, "_STATE_FILE", tmp_path / "state.txt")
    return act


def test_turn_start_is_working(tmp_path, monkeypatch):
    act = _boot(tmp_path, monkeypatch)
    act.write_turn_start()
    assert act._STATE_FILE.read_text(encoding="utf-8") == "working"
    assert act._ACTIVITY_TXT.read_text(encoding="utf-8") == "working"
    assert act.pulse_is_busy()
    assert act.should_stay_working("idle")


def test_tool_end_keeps_working(tmp_path, monkeypatch):
    act = _boot(tmp_path, monkeypatch)
    act.write_turn_start()
    act.write_activity("read_file")
    act.write_pulse_end("read_file", True, "ok")
    assert act._STATE_FILE.read_text(encoding="utf-8") == "working"
    assert act.pulse_is_busy()
    assert act.should_stay_working("")


def test_idle_only_on_turn_end(tmp_path, monkeypatch):
    act = _boot(tmp_path, monkeypatch)
    act.write_turn_start()
    act.write_pulse_end("read_file", True, "ok")
    act.write_state_idle()
    assert act._STATE_FILE.read_text(encoding="utf-8") == "idle"
    assert not act.pulse_is_busy()
    assert not act.should_stay_working("idle")
