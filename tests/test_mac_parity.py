"""Mac/Windows 宿主探测与工具分支。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch


def test_find_chromium_honors_env(tmp_path):
    exe = tmp_path / "Chrome"
    exe.write_text("x")
    from workers import host_bins
    with patch.dict("os.environ", {"DAEMONKEY_BROWSER_PATH": str(exe)}):
        assert host_bins.find_chromium() == str(exe)


def test_find_chromium_mac_applications():
    from workers import host_bins
    fake = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

    def exists(self):
        return str(self).replace("\\", "/") == fake

    with patch("workers.host_bins.sys.platform", "darwin"), \
         patch.dict("os.environ", {"DAEMONKEY_BROWSER_PATH": ""}), \
         patch("workers.host_bins.find_playwright_chromium", return_value=None), \
         patch.object(Path, "exists", exists):
        assert host_bins.find_chromium() == fake


def test_playwright_channels_mac_prefers_chrome():
    from workers import host_bins
    with patch("workers.host_bins.sys.platform", "darwin"):
        assert host_bins.playwright_channels()[0] == "chrome"
    with patch("workers.host_bins.sys.platform", "win32"):
        assert host_bins.playwright_channels()[0] == "msedge"


def test_ffmpeg_grab_args_mac_avfoundation():
    from workers.host_bins import ffmpeg_grab_args
    with patch("workers.host_bins.sys.platform", "darwin"):
        args = ffmpeg_grab_args("/tmp/a.mp4", 5, "desktop")
        assert "-f" in args and "avfoundation" in args
        assert "gdigrab" not in args
    with patch("workers.host_bins.sys.platform", "win32"):
        args = ffmpeg_grab_args(r"C:\t.mp4", 5, "desktop")
        assert "gdigrab" in args


def test_ffmpeg_grab_args_rejects_bad_region():
    from workers.host_bins import ffmpeg_grab_args
    with patch("workers.host_bins.sys.platform", "darwin"):
        try:
            ffmpeg_grab_args("/tmp/a.mp4", 3, "nope")
        except ValueError:
            return
        raise AssertionError("expected ValueError")


def test_is_foreign_venv_windows_tree_on_posix(tmp_path):
    from workers.host_bins import is_foreign_venv
    scripts = tmp_path / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "python.exe").write_text("x")
    with patch("workers.host_bins.sys.platform", "darwin"):
        assert is_foreign_venv(tmp_path) is True
    posix = tmp_path / ".venv" / "bin"
    posix.mkdir(parents=True)
    (posix / "python").write_text("x")
    with patch("workers.host_bins.sys.platform", "darwin"):
        assert is_foreign_venv(tmp_path) is False


def test_venv_python_prefers_posix(tmp_path):
    from workers.host_bins import venv_python
    bin_dir = tmp_path / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    py = bin_dir / "python"
    py.write_text("x")
    assert venv_python(tmp_path) == str(py)


def test_clipboard_cmds_mac():
    from agent_tools import clipboard as cb
    with patch.object(cb, "_IS_WIN", False), patch.object(cb, "_IS_MAC", True):
        assert cb._read_cmd() == ["pbpaste"]


def test_open_app_mac_alias_names():
    from agent_tools.open_app import MAC_OPEN_NAMES
    assert MAC_OPEN_NAMES["chrome"] == "Google Chrome"
    assert MAC_OPEN_NAMES["wechat"] == "WeChat"


def test_soffice_available_false_when_missing():
    from workers import soffice_preview
    with patch("workers.soffice_preview.find_soffice", return_value=None):
        assert soffice_preview.available() is False
