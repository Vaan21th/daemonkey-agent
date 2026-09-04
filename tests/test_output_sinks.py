"""产物落点闸 + 升级拒拉用户数据。"""
from __future__ import annotations

from pathlib import Path

from workers.core_update import kernel_files
from workers.output_sinks import (
    coerce_out_dir,
    drop_user_data_paths,
    is_user_data_path,
    refuse_new_path,
)


def test_user_data_paths():
    assert is_user_data_path("data/presentations/a.pptx")
    assert is_user_data_path("data/reports/x.docx")
    assert is_user_data_path("soul/SKILL.md")
    assert is_user_data_path("sessions/a.jsonl")
    assert is_user_data_path("static/user/user.js")
    assert is_user_data_path(".env")
    assert not is_user_data_path("workers/output_sinks.py")
    assert not is_user_data_path("static/chat.js")


def test_kernel_files_strips_user_data():
    files = kernel_files({
        "kernel": {
            "x": [
                "workers/foo.py",
                "data/presentations/a.pptx",
                "soul/SKILL.md",
                "sessions/x.jsonl",
                "static/user/user.css",
                ".env",
            ]
        }
    })
    assert files == ["workers/foo.py"]


def test_drop_keeps_order():
    keep, drop = drop_user_data_paths([
        "agent_tools/write_file.py",
        "data/runtime/x.json",
        "workers/core_update.py",
    ])
    assert keep == ["agent_tools/write_file.py", "workers/core_update.py"]
    assert drop == ["data/runtime/x.json"]


def test_refuse_new_unknown_data_dir(tmp_path: Path):
    (tmp_path / "data" / "design").mkdir(parents=True)
    err = refuse_new_path(tmp_path / "data" / "brand_new" / "x.html", tmp_path)
    assert err and "不要新建 data/brand_new/" in err
    assert refuse_new_path(tmp_path / "data" / "design" / "a.html", tmp_path) is None


def test_refuse_scratch_and_new_top(tmp_path: Path):
    (tmp_path / "workers").mkdir()
    err = refuse_new_path(tmp_path / "data" / "_tmp_probe" / "a.py", tmp_path)
    assert err and "scratch" in err
    err2 = refuse_new_path(tmp_path / "outputs" / "x.html", tmp_path)
    assert err2 and "不要在工程根下新开"
    assert refuse_new_path(tmp_path / "workers" / "new_mod.py", tmp_path) is None


def test_coerce_out_dir_falls_back(tmp_path: Path):
    default = tmp_path / "data" / "presentations" / "generated"
    default.mkdir(parents=True)
    got = coerce_out_dir("data/random_pics", default, tmp_path)
    assert got == default.resolve()
    ok = coerce_out_dir("data/presentations/generated", default, tmp_path)
    assert ok == default.resolve()


def test_coerce_keeps_workshop_outputs(tmp_path: Path):
    default = tmp_path / "data" / "workshop" / "outputs"
    default.mkdir(parents=True)
    dest = tmp_path / "data" / "workshop" / "outputs" / "app-x"
    dest.mkdir(parents=True)
    got = coerce_out_dir("data/workshop/outputs/app-x", default, tmp_path)
    assert got == dest.resolve()
