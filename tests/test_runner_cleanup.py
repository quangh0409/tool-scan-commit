"""Tích hợp nhỏ runner.stop(force) ↔ `python -m orchestrator.cli stop-cleanup --run X --json` THẬT (A2).

Tiến trình con gọi docker thật (chỉ `docker ps`/`network ls` — chỉ đọc). Không có docker / daemon tắt → skip.
A2 chưa có ORCH_DOCKER_BIN để shim → không mock được docker trong subprocess (xem YÊU CẦU LIÊN AGENT).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

import runner
from runner import process as rp


def _docker_ready() -> bool:
    if os.environ.get("CI"):
        return False
    try:
        r = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True,
                           errors="replace", timeout=15)
        return r.returncode == 0 and bool(r.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return False


@pytest.fixture
def profile_file(tmp_path, scratch_db):
    from orchestrator import profile
    p = profile.default_profile("https://github.com/FudanSELab/train-ticket", "master")
    p["paths"] = {"db": str(scratch_db), "export": str(tmp_path / "export"), "work": str(tmp_path / "work")}
    path = tmp_path / "profile.json"
    profile.save(p, path)
    return path


def _real_run(monkeypatch):
    """Khôi phục subprocess.run thật cho test này (các fixture khác không mock, nhưng phòng xa)."""
    monkeypatch.setattr(subprocess, "run", subprocess.run.__wrapped__ if hasattr(subprocess.run, "__wrapped__")
                        else subprocess.run)


def test_stop_cleanup_cli_exists_and_parses(tmp_path, profile_file, monkeypatch):
    """Không cần docker: lệnh stop-cleanup tồn tại trong argparse thật, `--json` được nhận."""
    from orchestrator import cli
    ns = cli.build_parser().parse_args(["stop-cleanup", "--run", "r1", "--json"])
    assert ns.run == "r1" and ns.json is True and ns.func is cli.cmd_stop_cleanup


@pytest.mark.skipif(not _docker_ready(), reason="cần docker thật đang chạy (chỉ đọc)")
def test_stop_force_dead_pid_runs_real_stop_cleanup(tmp_path, profile_file, monkeypatch, scratch_db):
    work = tmp_path / "work"
    rdir = work / "it-1"
    rdir.mkdir(parents=True)
    (rdir / "pid").write_text("999999", encoding="utf-8")        # pid chết → không kill, chỉ cleanup
    (rdir / "meta.json").write_text(json.dumps({"profile": str(profile_file), "run_id": "it-1"}), encoding="utf-8")
    monkeypatch.setattr(rp, "alive", lambda pid: False)

    res = runner.stop("it-1", work, force=True, timeout_s=1, python_exe=sys.executable)
    cl = res["cleanup"]
    assert cl is not None and cl["available"] is True, cl
    assert cl["rc"] == 0, cl["out"]
    assert cl["result"] is not None, cl["out"]
    assert cl["result"]["containers"] == [] and cl["result"]["errors"] == []
    assert "stop-cleanup rc=0" in (rdir / "run.log").read_text(encoding="utf-8")
    assert scratch_db.exists()
