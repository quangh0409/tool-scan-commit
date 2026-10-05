"""launcher: gui.json ghi khi GuiServer lên / xoá khi tắt; lần chạy 2 (mutex bị giữ) mở trình duyệt tới URL cũ."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


launcher = _load("secjit_launcher_gi", ROOT / "packaging" / "launcher.py")


@pytest.fixture(autouse=True)
def home(monkeypatch, tmp_path):
    monkeypatch.setenv("SECJIT_HOME", str(tmp_path / "home"))
    snap = dict(os.environ)
    yield tmp_path / "home"
    os.environ.clear()
    os.environ.update(snap)


def test_gui_json_written_and_cleared_with_real_server(monkeypatch):
    import gui.__main__ as gm
    from gui import server as gui_server
    from gui.api_mock import MockApi
    seen = {}

    def fake_main(argv):
        s = gui_server.GuiServer(MockApi(), port=0)
        s.serve_in_thread()
        info = launcher.read_gui_info()
        seen["info"], seen["url"] = info, s.url
        s.stop()
        seen["after_stop"] = launcher.read_gui_info()
        return 0
    monkeypatch.setattr(gm, "main", fake_main)
    assert launcher.run_gui(["--dev", "--no-browser"]) == 0
    info = seen["info"]
    assert info["url"] == seen["url"] and info["port"] == int(seen["url"].split(":")[2].split("/")[0])
    assert info["token"] and info["pid"] == os.getpid() and info["started"]
    assert seen["after_stop"] is None and not launcher.gui_info_path().exists()
    # bọc idempotent
    launcher._patch_server_for_gui_info(gui_server)
    assert gui_server.GuiServer._secjit_gui_info is True


def test_second_instance_opens_browser(monkeypatch):
    import registry
    from runner import process as rp

    class Held:
        acquired = False

        def release(self):
            pass
    monkeypatch.setattr(registry.locks, "single_instance", lambda name="x": Held())
    launcher.write_gui_info("http://127.0.0.1:5555/?t=abc", 5555, "abc", pid=4242)
    monkeypatch.setattr(rp, "alive", lambda pid: pid == 4242)
    monkeypatch.setattr(launcher, "_reachable", lambda url, timeout=2.0: True)
    opened = []
    assert launcher.run_gui([], open_browser=opened.append) == 0
    assert opened == ["http://127.0.0.1:5555/?t=abc"]
    assert launcher.gui_info_path().exists()           # không xoá file của instance đang sống


def test_second_instance_stale_info_errors(monkeypatch, capsys):
    import registry

    class Held:
        acquired = False

        def release(self):
            pass
    monkeypatch.setattr(registry.locks, "single_instance", lambda name="x": Held())
    launcher.write_gui_info("http://127.0.0.1:5555/?t=abc", 5555, "abc", pid=999999)
    monkeypatch.setattr(launcher, "_reachable", lambda url, timeout=2.0: False)
    opened = []
    assert launcher.run_gui([], open_browser=opened.append) == 2
    assert not opened and not launcher.gui_info_path().exists()
    assert "mutex secjit-gui" in capsys.readouterr().err


def test_clear_gui_info_respects_pid():
    launcher.write_gui_info("u", 1, "t", pid=4242)
    launcher.clear_gui_info(only_pid=1)
    assert launcher.read_gui_info()["pid"] == 4242
    launcher.clear_gui_info(only_pid=4242)
    assert launcher.read_gui_info() is None
    launcher.gui_info_path().write_text("hỏng", encoding="utf-8")
    assert launcher.read_gui_info() is None
    assert json.loads(launcher.write_gui_info("u", 1, "t").read_text(encoding="utf-8"))["port"] == 1
