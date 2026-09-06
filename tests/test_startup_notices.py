"""升级胶囊取当前版本说明，不再误落到 0.9.9。"""
from workers.startup_notices import _read_changelog, _segment_for_version

NOTE = (
    "1.0.2(2026-09-06 · 手册写回) · 1.0.1(2026-09-04 · 落点闸) · "
    "0.9.9(2026-08-29 · 内核大更)"
)
LOG = (
    "1.0.0(2026-09-03 · Mac) · 0.9.5(旧) · 0.9.9(2026-08-29 · 内核大更)"
)


def test_note_picks_current_not_099():
    text = _read_changelog(LOG, version="1.0.2", note=NOTE)
    assert "手册写回" in text
    assert "0.9.9" not in text


def test_log_ref_version_wins_over_trailing_099():
    assert "内核大更" in _segment_for_version(LOG, "0.9.9")
    text = _read_changelog(LOG, version="1.0.0", note="")
    assert "Mac" in text
    assert "0.9.9" not in text
