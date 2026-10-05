"""Hotfix sau Run B trong exe (2026-10-05): tên Sonar hợp lệ hostname, horusec utf-8, git sha fallback."""
from __future__ import annotations

import json
import subprocess


def test_sonar_names_are_valid_hostnames(orch_env):
    from orchestrator.tools_expensive import sonar
    rid = "r-20261005-120433-FudanSELab__train-ticket"
    s, n = sonar.server_name(rid), sonar.network_name(rid)
    assert s == "orch-sonar-r-20261005-120433-fudanselab-train-ticket"
    assert n.startswith("orch-sonar-net-") and "__" not in n and n == n.lower()
    assert sonar.server_name("runA2-20261005") == "orch-sonar-runa2-20261005"
    assert sonar._host_slug("") == "local" and sonar._host_slug("___") == "local"
    assert len(sonar.server_name("x" * 200)) <= len("orch-sonar-") + 48


def test_horusec_report_read_utf8(orch_env, fake_docker, tmp_path, monkeypatch):
    from orchestrator.tools import horusec
    clone = tmp_path / "clone"
    (clone / "a").mkdir(parents=True)
    (clone / "a" / "x.java").write_text("class X{}", encoding="utf-8")
    # docker_run giả: ghi báo cáo có byte ngoài cp1252 (0x81 trong UTF-8 hợp lệ: 'ü' = C3 BC, dùng ký tự lạ hơn)
    payload = {"analysisVulnerabilities": [], "note": "ký tự \u0081ü中"}

    def run(cmd, *a, **kw):
        if "horusec" in " ".join(cmd):
            out_dir = next(c.rsplit(":", 1)[0] for c in cmd if c.endswith(":/out"))  # rsplit: "C:\\x:/out"
            (tmp_path / "dummy").mkdir(exist_ok=True)
            import pathlib
            pathlib.Path(out_dir, "h.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(subprocess, "run", run)
    raw: list = []
    res = horusec.HorusecWrapper().scan(clone, "abc123", "https://github.com/x/y", ["a/x.java"], raw_out=raw)
    assert res == [] and raw and raw[0][0] == "json" and "中" in raw[0][1]


def test_git_sha_fallback_to_app_version(monkeypatch):
    from orchestrator.tools import base
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("no git")))
    monkeypatch.setenv("SECJIT_APP_VERSION", "733576d-dirty")
    assert base.orchestrator_git_sha() == "733576d"
    monkeypatch.setenv("SECJIT_APP_VERSION", "dev")
    assert base.orchestrator_git_sha() is None


def test_killed_container_is_infra_error():
    from orchestrator.tools import base
    assert base.classify_failure(137, "") == "infra_error"
    assert base.classify_failure(143, "") == "infra_error"
    assert base.classify_failure(1, "[ERROR] Failed to execute goal ... compilation failure") is None


def test_launcher_does_not_block_itself_with_real_mutex(monkeypatch):
    """Lỗi thật: launcher giữ mutex rồi gui.__main__ xin lại -> exit 2, GUI không mở. Dùng mutex THẬT."""
    import importlib.util
    import sys
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "secjit_launcher_t", Path(__file__).resolve().parents[1] / "packaging" / "launcher.py")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    import gui.__main__ as gm
    seen = {}

    def fake_gui_main(argv):
        # mô phỏng đúng đoạn khoá của gui.__main__ với registry.locks thật
        from registry import locks
        if "--allow-multi" not in argv:
            inst = locks.single_instance("secjit-gui")
            if not getattr(inst, "acquired", True):
                return 2
        seen["argv"] = argv
        return 0
    monkeypatch.setattr(gm, "main", fake_gui_main)
    monkeypatch.setattr(sys, "argv", ["secjit-scan.exe"])
    assert launcher.run_gui([]) == 0
    assert "--allow-multi" in seen["argv"]


def test_estimate_fast_count_excludes_merges_and_is_fast(orch_env, tmp_path, monkeypatch):
    """Ước lượng không còn đọc diff từng commit (46 s -> <1 s trên train-ticket): đếm git log trừ merge."""
    import subprocess as sp
    repo = tmp_path / "work" / "o__r"
    repo.mkdir(parents=True)
    g = lambda *a: sp.check_output(["git", "-C", str(repo), *a], text=True)  # noqa: E731
    g("init", "-q", "-b", "main"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
    for i in range(5):
        (repo / f"f{i}.txt").write_text(str(i), encoding="utf-8"); g("add", "."); g("commit", "-qm", f"c{i}")
    g("checkout", "-qb", "side"); (repo / "s.txt").write_text("s", encoding="utf-8"); g("add", "."); g("commit", "-qm", "side")
    g("checkout", "-q", "main"); g("merge", "-q", "--no-ff", "side", "-m", "merge")
    g("remote", "add", "origin", "https://github.com/o/r")
    from orchestrator import estimate, enumerate_commits as enm
    called = []
    monkeypatch.setattr(enm, "get_commit_info", lambda *a, **k: called.append(1))
    p = {"repo": "https://github.com/o/r", "branch": "main",
         "scope": {"mode": "all", "max": None}, "workers": {"scan": 1, "expensive": 1},
         "expensive_tools": ["findsecbugs", "sonar"], "include_clean": True}
    res = estimate.estimate(p, speed=dict(estimate.DEFAULT_SPEED), speed_source="default")
    assert res["commits_after_filter"] == 6 and res["approx"] is True   # 5 + side, trừ 1 merge
    assert called == []                                                   # không đọc diff từng commit


def test_server_silences_client_disconnect(capsys):
    """Client đóng kết nối giữa chừng không được in traceback ra console (WinError 10053)."""
    from gui.server import GuiServer
    from gui.api_mock import MockApi
    s = GuiServer(MockApi(), port=0)
    try:
        for exc in (ConnectionAbortedError(10053, "aborted"), ConnectionResetError(), BrokenPipeError()):
            try:
                raise exc
            except OSError:
                s.handle_error(None, ("127.0.0.1", 1))
        assert "Traceback" not in capsys.readouterr().err
        try:
            raise ValueError("lỗi thật")
        except ValueError:
            s.handle_error(None, ("127.0.0.1", 1))
        assert "ValueError" in capsys.readouterr().err   # lỗi thật vẫn được in
    finally:
        s.server_close()


def test_storage_not_blocked_by_slow_docker(monkeypatch, tmp_path):
    """Docker bận (mỗi lệnh treo tới timeout) không được làm /api/storage vượt giới hạn GUI."""
    import time as _t
    from gui import api_settings as S
    monkeypatch.setattr(S, "get_settings", lambda: {"work_dir": str(tmp_path / "w"), "out_dir": str(tmp_path / "o"), "m2_volume": True})
    monkeypatch.setattr(S, "_running_works", lambda: set())

    def slow(*a, **k):
        _t.sleep(1.0)
        return None
    monkeypatch.setattr(S, "_docker_volume_bytes", slow)
    monkeypatch.setattr(S, "_docker_images", lambda *a, **k: (_t.sleep(1.0), [])[1])
    S._STORAGE_CACHE["data"] = None
    t0 = _t.time()
    r = S.storage({}, None)
    assert _t.time() - t0 < 1.8          # 2 lệnh docker chạy song song, không cộng dồn
    assert r["cached"] is False
    t0 = _t.time()
    assert S.storage({}, None)["cached"] is True and _t.time() - t0 < 0.2
    assert S.storage({"refresh": "1"}, None)["cached"] is False
    img = next(i for i in r["items"] if i["id"] == "images")
    assert "chưa đo được" in img["detail"]
