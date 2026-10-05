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
    monkeypatch.setattr(sys, "argv", ["secjit-scan-gui.exe"])
    assert launcher.run_gui([]) == 0
    assert "--allow-multi" in seen["argv"]
