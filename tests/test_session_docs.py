"""本话题稿：挂进 session、摘要进上下文、附件入库、产物列表能看见。"""
from __future__ import annotations

from pathlib import Path

import workers.session_docs as sd


def _session_fs(tmp_path: Path, monkeypatch):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    monkeypatch.setattr(sd, "_ROOT", tmp_path)
    monkeypatch.setattr("daemon_session.SESSIONS_DIR", sessions)
    monkeypatch.setattr("daemon_session._META_PATH", sessions / "_index.json")
    monkeypatch.setattr("workers.output_versions.Path", Path)
    return sessions


def _deck(tmp_path: Path, name: str = "提案.pptx") -> Path:
    folder = tmp_path / "data" / "presentations"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"PK")
    (path.with_suffix(".md")).write_text(
        "---\ntitle: 提案\n---\n\n# 封面\n先把分页稿贴出来\n",
        encoding="utf-8",
    )
    return path


def test_extract_paths_from_notes():
    text = (
        "【中栏批注】第一条就 revise_office。\n"
        "1. revise_office path=data/presentations/提案.pptx excerpt=旧 body=新\n"
    )
    assert sd.extract_paths(text) == ["data/presentations/提案.pptx"]


def test_resolve_rejects_escape(tmp_path, monkeypatch):
    _session_fs(tmp_path, monkeypatch)
    assert sd.resolve_rel("../secret.pptx", root=tmp_path) is None
    assert sd.resolve_rel("data/presentations/nope.pptx", root=tmp_path) is None


def test_bind_accepts_url_style_path(tmp_path, monkeypatch):
    _session_fs(tmp_path, monkeypatch)
    _deck(tmp_path)
    rec = sd.bind("api-ut", "/presentations/提案.pptx", root=tmp_path)
    assert rec["path"] == "data/presentations/提案.pptx"


def test_bind_and_system_note(tmp_path, monkeypatch):
    _session_fs(tmp_path, monkeypatch)
    _deck(tmp_path)
    rec = sd.bind("api-ut", "data/presentations/提案.pptx", root=tmp_path)
    assert rec["path"] == "data/presentations/提案.pptx"
    assert sd.list_bound("api-ut")[0]["name"] == "提案.pptx"
    note = sd.system_note("api-ut", root=tmp_path)
    assert "本话题正在做的稿" in note
    assert "data/presentations/提案.pptx" in note
    assert "先把分页稿贴出来" in note
    assert "revise_office" in note


def test_bind_from_text(tmp_path, monkeypatch):
    _session_fs(tmp_path, monkeypatch)
    _deck(tmp_path)
    got = sd.bind_from_text(
        "api-ut",
        "文件：data/presentations/提案.pptx\n1. revise_office path=data/presentations/提案.pptx",
        root=tmp_path,
    )
    assert len(got) == 1
    assert got[0]["path"] == "data/presentations/提案.pptx"


def test_bind_dedupes_to_front(tmp_path, monkeypatch):
    _session_fs(tmp_path, monkeypatch)
    _deck(tmp_path)
    other = _deck(tmp_path, "另一份.pptx")
    other.with_suffix(".md").write_text("# 另一份", encoding="utf-8")
    sd.bind("api-ut", "data/presentations/提案.pptx", root=tmp_path)
    sd.bind("api-ut", "data/presentations/另一份.pptx", root=tmp_path)
    sd.bind("api-ut", "data/presentations/提案.pptx", root=tmp_path)
    names = [d["name"] for d in sd.list_bound("api-ut")]
    assert names[0] == "提案.pptx"
    assert names.count("提案.pptx") == 1


def test_ingest_file_publishes_to_shelf(tmp_path, monkeypatch):
    _session_fs(tmp_path, monkeypatch)
    src = tmp_path / "inbox.pptx"
    src.write_bytes(b"PK-office")
    rec = sd.ingest_file("api-ut", src, "客户结构.pptx", root=tmp_path)
    dest = tmp_path / "data" / "presentations" / "客户结构.pptx"
    assert rec["path"] == "data/presentations/客户结构.pptx"
    assert dest.read_bytes() == b"PK-office"
    assert "客户结构.pptx" in sd.system_note("api-ut", root=tmp_path)


def test_describe_office_no_pdf_read(tmp_path, monkeypatch):
    _session_fs(tmp_path, monkeypatch)
    _deck(tmp_path)
    text = sd.describe_office("data/presentations/提案.pptx", root=tmp_path)
    assert "pdf_read" not in text
    assert "revise_office path=data/presentations/提案.pptx" in text
    assert "先把分页稿贴出来" in text


def test_bind_does_not_steal_home(tmp_path, monkeypatch):
    _session_fs(tmp_path, monkeypatch)
    _deck(tmp_path)
    sd.bind("talk-2", "data/presentations/提案.pptx", root=tmp_path)
    stolen = sd.bind("talk-1", "data/presentations/提案.pptx", root=tmp_path)
    assert stolen["home_sid"] == "talk-2"
    assert sd.home_of("data/presentations/提案.pptx") == "talk-2"
    assert sd.list_bound("talk-1") == []
    assert sd.list_bound("talk-2")[0]["path"] == "data/presentations/提案.pptx"


def test_claim_writes_current_keeps_home(tmp_path, monkeypatch):
    _session_fs(tmp_path, monkeypatch)
    _deck(tmp_path)
    sd.bind("talk-2", "data/presentations/提案.pptx", root=tmp_path)
    rec = sd.bind("talk-1", "data/presentations/提案.pptx", root=tmp_path, claim=True)
    assert rec["path"] == "data/presentations/提案.pptx"
    assert rec["home_sid"] == "talk-2"
    assert sd.home_of("data/presentations/提案.pptx") == "talk-2"
    assert sd.list_bound("talk-1")[0]["path"] == "data/presentations/提案.pptx"
    assert sd.list_bound("talk-2")[0]["path"] == "data/presentations/提案.pptx"


def test_ingest_existing_does_not_overwrite(tmp_path, monkeypatch):
    _session_fs(tmp_path, monkeypatch)
    dest = _deck(tmp_path, "客户结构.pptx")
    dest.write_bytes(b"PK-keep")
    src = tmp_path / "inbox.pptx"
    src.write_bytes(b"PK-new")
    rec = sd.ingest_file("talk-new", src, "客户结构.pptx", root=tmp_path)
    assert rec["path"] == "data/presentations/客户结构.pptx"
    assert dest.read_bytes() == b"PK-keep"
    assert sd.list_bound("talk-new")[0]["path"] == rec["path"]


def test_accept_upload_attachments_to_shelf(tmp_path, monkeypatch):
    _session_fs(tmp_path, monkeypatch)
    dest = _deck(tmp_path, "AI_AGENT_新增页.pptx")
    dest.write_bytes(b"PK-shelf")
    inbox = tmp_path / "data" / "runtime" / "attachments"
    inbox.mkdir(parents=True)
    raw = inbox / "api-2026-09-01_074725_f269b4_1788220045_0_AI_AGENT_新增页.pptx"
    raw.write_bytes(b"PK-upload")
    path, err = sd.accept_upload(
        "talk-new",
        str(raw).replace("\\", "/"),
        root=tmp_path,
    )
    assert err == ""
    assert path == dest
    assert dest.read_bytes() == b"PK-shelf"
    assert sd.home_of("data/presentations/AI_AGENT_新增页.pptx") == "talk-new"
    assert sd.list_bound("talk-new")[0]["path"] == "data/presentations/AI_AGENT_新增页.pptx"


def test_canon_abs_path(tmp_path, monkeypatch):
    _session_fs(tmp_path, monkeypatch)
    dest = _deck(tmp_path)
    rel = sd._canon_rel(str(dest).replace("\\", "/"), root=tmp_path)
    assert rel == "data/presentations/提案.pptx"
    assert sd.resolve_rel(str(dest), root=tmp_path) == dest.resolve()


def test_merge_into_artifacts(tmp_path, monkeypatch):
    _session_fs(tmp_path, monkeypatch)
    _deck(tmp_path)
    sd.bind("api-ut", "data/presentations/提案.pptx", root=tmp_path)
    arts = sd.merge_into_artifacts([], "api-ut")
    assert arts[0]["url"] == "/presentations/提案.pptx"
    assert arts[0]["ext"] == "pptx"
    again = sd.merge_into_artifacts(arts, "api-ut")
    assert len(again) == 1
