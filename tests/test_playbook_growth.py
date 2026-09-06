"""1.0.2 手册自成长四道闸 · 夹具 + 假向量，不靠模型发挥。"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def pb_home(tmp_path, monkeypatch):
    home = tmp_path / "playbooks"
    home.mkdir()
    monkeypatch.setattr("workers.playbooks.PLAYBOOK_DIR", home)
    monkeypatch.setattr("workers.playbooks.INDEX_PATH", home / "_index.json")
    monkeypatch.setattr(
        "workers.memory_index.incremental_update",
        lambda *a, **k: None,
    )
    return home


def _case(i: str, title: str, problem: str, trials: str = "尚无失败路径"):
    from workers.playbook_case import save_case
    return save_case(
        title=title,
        task_type="debug",
        steps=f"1. 复现 {i}\n2. 按手册做",
        problem=problem,
        trials=trials,
        session_id=f"sess-{i}",
        quote=f"原话 {i}",
        tags=["growth-fixture"],
    )


def test_gate1_case_integrity(pb_home: Path):
    from workers.playbook_case import extract_action, validate_integrity
    bad = extract_action({"title": "缺问题", "steps": "1. 做", "trials": "尚无失败路径"})
    assert not bad["ok"]
    got = extract_action({
        "title": "Windows 换行保真",
        "steps": "1. 复现\n2. 指定 newline",
        "problem": "open 不指定 newline 会把 LF 吃成 CRLF",
        "trials": "尚无失败路径",
    })
    assert got["ok"] and got.get("id"), got
    pb = _case("g1", "Windows 换行保真", "open 不指定 newline 会把 LF 吃成 CRLF")
    raw = (pb_home / f"{pb['slug']}.md").read_text(encoding="utf-8")
    gate = validate_integrity(raw)
    assert gate["ok"], gate
    assert "问题" in raw and "试错过" in raw and "出处" in raw
    assert "sess-g1" in raw


def test_gate2_peers_not_flood(pb_home: Path):
    from workers.playbook_cluster import rank_by_vectors
    gold = [1.0, 0.0, 0.0, 0.0]
    near = [0.96, 0.2, 0.0, 0.0]
    mid = [0.92, 0.3, 0.1, 0.0]
    decoy = [0.0, 0.0, 1.0, 0.0]
    items = [
        {"id": "gold", "slug": "win-eol", "title": "Windows 换行保真", "vec": gold},
        {"id": "peer-a", "slug": "win-open", "title": "open newline 还原", "vec": near},
        {"id": "peer-b", "slug": "py-eol", "title": "Python 写文件换行", "vec": mid},
        {"id": "decoy", "slug": "win-wallpaper", "title": "Windows 壁纸设置", "vec": decoy},
    ]
    for n in range(6):
        items.append({
            "id": f"noise-{n}", "slug": f"noise-{n}",
            "title": f"无关手册 {n}", "vec": [0.0, 1.0, 0.0, float(n) * 0.01],
        })
    ranked = rank_by_vectors(gold, items, k=3)
    ids = [r["id"] for r in ranked]
    assert "gold" in ids[:2]
    assert "peer-a" in ids or "peer-b" in ids
    assert "decoy" not in ids


def test_gate3_writeback_seen_next_recall(pb_home: Path):
    from workers.playbook_case import append_trial
    from workers.playbook_cluster import format_injection
    from workers.playbooks import record_playbook_result
    pb = _case("g3", "重启后立刻跑工具", "重启窗口会撞 self_heal")
    before = format_injection([{"id": pb["id"], "slug": pb["slug"], "title": "重启后立刻跑工具"}])
    assert "假 result" not in before
    record_playbook_result(pb["id"], False, "把 self_heal 假 result 当成真失败又排了一遍")
    after = format_injection([{"id": pb["id"], "slug": pb["slug"], "title": "重启后立刻跑工具"}])
    assert "假 result" in after
    raw = (pb_home / f"{pb['slug']}.md").read_text(encoding="utf-8")
    assert "试错过" in raw and "假 result" in raw
    # append_trial 再写一条也不另开文件
    n_md = len(list(pb_home.glob("*.md")))
    append_trial(pb["id"], "第二次还是窗口太短")
    assert len(list(pb_home.glob("*.md"))) == n_md


def test_gate4_no_bloat_no_lost_leaves(pb_home: Path):
    from workers.playbook_cluster import PEER_CHAR_CAP, format_injection
    from workers.playbook_distill import confirm_draft, draft_cluster
    a = _case("d1", "换行事故甲", "CRLF 吃掉 LF")
    b = _case("d2", "换行事故乙", "open 默认 text 模式")
    c = _case("d3", "换行事故丙", "正则按 \\n 切会漏 \\r")
    leaves_before = {p.name for p in pb_home.glob("*.md")}
    inject = format_injection(
        [{"id": a["id"], "slug": a["slug"], "title": "换行事故甲"}],
        "windows 换行",
    )
    peer_part = "\n".join(ln for ln in inject.splitlines() if "同簇对照" in ln or ln.startswith("    ·"))
    assert len(peer_part) <= PEER_CHAR_CAP + 20
    draft = draft_cluster(
        [a["id"], b["id"], c["id"]],
        title="现在怎么处理 Windows 换行",
        how_now="写文件一律 open(..., newline='\\n')，读完再按原 EOL 写回。不要用正则硬切。",
    )
    assert draft["ok"], draft
    assert (pb_home / "_drafts" / f"{draft['draft_id']}.md").exists()
    assert {p.name for p in pb_home.glob("*.md")} == leaves_before
    confirmed = confirm_draft(draft["draft_id"])
    assert confirmed["ok"], confirmed
    assert {p.name for p in pb_home.glob("*.md")} >= leaves_before
    for name in leaves_before:
        assert (pb_home / name).exists()
    new_md = (pb_home / Path(confirmed["playbook"]["path"]).name).read_text(encoding="utf-8")
    assert "data/playbooks/" in new_md
    assert a["slug"] in new_md or a["id"] in new_md
    from workers.playbooks import delete_playbook
    orphan = draft_cluster(
        [a["id"], b["id"]],
        title="缺叶子应拒绝",
        how_now="写文件一律指定 newline，读完按原 EOL 写回，不要用正则硬切。",
    )
    delete_playbook(b["id"])
    denied = confirm_draft(orphan["draft_id"])
    assert not denied["ok"]
    assert "叶子" in (denied.get("error") or "")


class _Hit:
    def __init__(self, slug: str, score: float = -5.0):
        self.section = f"{slug}:debug"
        self.score = score
        self.content = slug


def _fake_fts(monkeypatch):
    """走 relevant_playbooks 的 FTS 分支，命中当前夹具库的 slug。"""
    def _search(*_a, **_k):
        from workers.playbooks import list_playbooks
        return [_Hit(pb.get("slug") or "") for pb in list_playbooks() if pb.get("slug")]
    monkeypatch.setattr("workers.memory_index.search", _search)


def test_knife1_auto_writeback_through_relevant_playbooks(pb_home: Path, monkeypatch):
    """load 之后关键工具失败，不调 feedback，真召回入口也必须看见。"""
    from types import SimpleNamespace
    from workers.closure_check import relevant_playbooks
    from workers.playbook_observe import begin, note_loaded, observe_tool
    _fake_fts(monkeypatch)
    pb = _case("k1", "重启后立刻跑工具验证", "重启窗口会撞 self_heal")
    q = "重启后立刻跑工具验证会撞初始化"
    before = relevant_playbooks(q, session_id="")
    assert pb["id"] in before
    assert "假 result" not in before
    begin()
    note_loaded(pb["id"])
    observe_tool(
        SimpleNamespace(name="python_exec"),
        {},
        SimpleNamespace(ok=False, error="self_heal 假 result 丢掉了验证", output=""),
    )
    after = relevant_playbooks(q, session_id="")
    assert "假 result" in after
    raw = (pb_home / f"{pb['slug']}.md").read_text(encoding="utf-8")
    assert "自动 · python_exec 失败" in raw
    observe_tool(
        SimpleNamespace(name="python_exec"),
        {},
        SimpleNamespace(ok=False, error="self_heal 假 result 丢掉了验证", output=""),
    )
    assert raw == (pb_home / f"{pb['slug']}.md").read_text(encoding="utf-8")
    begin()
    note_loaded(pb["id"])
    observe_tool(
        SimpleNamespace(name="catalog_call"),
        {"name": "python_exec", "args": {"code": "raise RuntimeError('x')"}},
        SimpleNamespace(
            ok=False,
            error="exit code 1",
            output='Traceback:\nRuntimeError: canary_fake_result_20260906\n',
        ),
    )
    raw2 = (pb_home / f"{pb['slug']}.md").read_text(encoding="utf-8")
    assert "RuntimeError: canary_fake_result_20260906" in raw2
    assert raw2.count("exit code 1") == 0 or "RuntimeError" in raw2


def test_knife2_empty_experience_loses_the_slot(pb_home: Path, monkeypatch):
    from workers.closure_check import relevant_playbooks
    _fake_fts(monkeypatch)
    hollow = _case("e1", "换行保真空经验册", "CRLF 吃掉 LF", "尚无失败路径")
    real = _case("e2", "换行保真有试错册", "CRLF 吃掉 LF", "- 已试 · open 没写 newline")
    text = relevant_playbooks("换行保真怎么处理 CRLF", limit=1, session_id="")
    assert real["id"] in text
    assert hollow["id"] not in text


def test_knife3_cluster_proposes_not_confirms(pb_home: Path, monkeypatch):
    from workers.closure_check import relevant_playbooks
    from workers.playbook_distill import confirm_draft
    _fake_fts(monkeypatch)
    a = _case("p1", "换行事故甲手册", "CRLF 吃掉 LF")
    _case("p2", "换行事故乙手册", "open 默认 text")
    _case("p3", "换行事故丙手册", "正则切行漏 CR")
    before = {p.name for p in pb_home.glob("*.md")}
    text = relevant_playbooks("换行事故手册怎么写文件", session_id="")
    assert "proposal_id=pp-" in text
    assert "确认前不入库" in text
    denied = confirm_draft("pp-not-a-draft")
    assert not denied["ok"]
    assert {p.name for p in pb_home.glob("*.md")} == before
    assert (pb_home / f"{a['slug']}.md").exists()


def test_refuse_loose_folder(pb_home: Path, tmp_path: Path):
    from workers.playbook_case import refuse_loose_playbook
    from workers.playbooks import ROOT
    loose = ROOT / "data" / "learnings" / "随便一篇手册.md"
    err = refuse_loose_playbook(loose, "## 步骤\n\n1. 做\n\n## 常见坑\n\n无")
    assert err and "data/playbooks" in err
    inside = pb_home / "x.md"
    assert refuse_loose_playbook(inside, "# hi")
