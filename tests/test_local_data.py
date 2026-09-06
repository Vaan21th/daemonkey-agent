"""本地占用扫描 + 可选清理。"""
from __future__ import annotations

from pathlib import Path

from workers.local_data import human_bytes, purge, usage


def _seed(root: Path):
    (root / "data" / "workshop" / "outputs").mkdir(parents=True)
    (root / "data" / "workshop" / "apps").mkdir(parents=True)
    (root / "data" / "runtime" / "scratch").mkdir(parents=True)
    (root / "sessions").mkdir()
    (root / "soul").mkdir()
    (root / "data" / "workshop" / "outputs" / "clip.mp4").write_bytes(b"x" * 2048)
    (root / "data" / "workshop" / "apps" / "keep.json").write_text("{}", encoding="utf-8")
    (root / "data" / "runtime" / "scratch" / "tmp.bin").write_bytes(b"y" * 512)
    (root / "sessions" / "chat.jsonl").write_text("hi\n", encoding="utf-8")
    (root / "soul" / "SKILL.md").write_text("keep", encoding="utf-8")


def test_human_bytes():
    assert human_bytes(0) == "0 B"
    assert human_bytes(2048) == "2.0 KB"
    assert "MB" in human_bytes(2 * 1024 * 1024)


def test_usage_counts_only_buckets(tmp_path: Path):
    _seed(tmp_path)
    data = usage(root=tmp_path)
    by_id = {b["id"]: b for b in data["buckets"]}
    assert by_id["workshop_outputs"]["files"] == 1
    assert by_id["workshop_outputs"]["bytes"] == 2048
    assert by_id["scratch"]["bytes"] == 512
    assert by_id["sessions"]["files"] == 1
    assert by_id["sessions"]["danger"] is True
    assert by_id["scratch"]["suggest"] is True
    sess = (tmp_path / "sessions" / "chat.jsonl").stat().st_size
    assert data["total_bytes"] == 2048 + 512 + sess


def test_purge_selected_leaves_others(tmp_path: Path):
    _seed(tmp_path)
    out = purge(["scratch"], root=tmp_path)
    assert out["deleted"] == 1
    assert out["freed"] == 512
    assert (tmp_path / "data" / "workshop" / "outputs" / "clip.mp4").exists()
    assert (tmp_path / "data" / "workshop" / "apps" / "keep.json").exists()
    assert (tmp_path / "sessions" / "chat.jsonl").exists()
    assert (tmp_path / "soul" / "SKILL.md").exists()
    assert not (tmp_path / "data" / "runtime" / "scratch" / "tmp.bin").exists()
    assert (tmp_path / "data" / "runtime" / "scratch").is_dir()


def test_purge_unknown_refused(tmp_path: Path):
    _seed(tmp_path)
    try:
        purge(["soul"], root=tmp_path)
        assert False, "should refuse"
    except ValueError as e:
        assert "unknown" in str(e)
    assert (tmp_path / "soul" / "SKILL.md").exists()


def test_purge_empty_refused(tmp_path: Path):
    try:
        purge([], root=tmp_path)
        assert False, "should refuse"
    except ValueError:
        pass
