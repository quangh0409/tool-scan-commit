"""Runner: start dựng đúng argv/env/creationflags (mock Popen); alive; attach phân biệt interrupted; stop."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

import runner
from runner import process as rp


@pytest.fixture
def profile_file(tmp_path, scratch_db):
    from orchestrator import profile
    p = profile.default_profile("https://github.com/FudanSELab/train-ticket", "master")
    p["paths"] = {"db": str(scratch_db), "export": str(tmp_path / "export"), "work": str(tmp_path / "work")}
    p["sonar_port"] = 9100
    path = tmp_path / "profile.json"
    profile.save(p, path)
    return path


class FakePopen:
    calls: list = []

    def __init__(self, argv, **kw):
        self.argv, self.kw, self.pid = argv, kw, 4242
        FakePopen.calls.append(self)


def test_start_builds_argv_env_and_files(profile_file, tmp_path, monkeypatch):
    FakePopen.calls.clear()
    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setenv("PYTHONPATH", "C:\\khac")
    work = tmp_path / "work"
    (work / "run-1").mkdir(parents=True)
    (work / "run-1" / "stop").write_text("cũ", encoding="utf-8")   # stop-file cũ phải bị xoá

    res = runner.start(profile_file, "run-1", work, python_exe="py.exe", extra_env={"X_TEST": "1"})

    assert res["pid"] == 4242
    fp = FakePopen.calls[0]
    assert fp.argv == ["py.exe", "-m", "orchestrator.cli", "pipeline", "--profile", str(profile_file)]
    env = fp.kw["env"]
    assert env["ORCH_RUN_ID"] == "run-1"
    assert env["ORCH_PROGRESS_FILE"] == str(work / "run-1" / "progress.jsonl")
    assert env["ORCH_STOP_FILE"] == str(work / "run-1" / "stop")
    assert env["ORCH_SQLITE"] == str(profile_file.parent / "scratch.sqlite")
    assert env["ORCH_SONAR_PORT"] == "9100" and env["ORCH_USE_CODEQL"] == "0"
    assert env["PYTHONUTF8"] == "1" and env["PYTHONIOENCODING"] == "utf-8" and env["X_TEST"] == "1"
    assert env["PYTHONUNBUFFERED"] == "1"      # run.log phải cập nhật sống (Dashboard tab Log); exe xử lý thêm ở launcher
    assert env["PYTHONPATH"].split(os.pathsep)[0] == str(rp.src_dir()) and "C:\\khac" in env["PYTHONPATH"]
    assert (rp.src_dir() / "orchestrator" / "cli.py").exists()
    assert fp.kw["stdin"] is subprocess.DEVNULL and fp.kw["close_fds"] is True
    assert fp.kw["stderr"] is subprocess.STDOUT
    if os.name == "nt":
        assert fp.kw["creationflags"] == (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW)
        assert "start_new_session" not in fp.kw
    else:
        assert fp.kw["start_new_session"] is True
    # file sinh ra
    rdir = work / "run-1"
    assert (rdir / "pid").read_text(encoding="utf-8") == "4242"
    meta = json.loads((rdir / "meta.json").read_text(encoding="utf-8"))
    assert meta["argv"] == fp.argv and meta["profile"] == str(profile_file) and meta["started"]
    assert meta["repo"] == "https://github.com/FudanSELab/train-ticket"
    assert not (rdir / "stop").exists()
    assert "runner start" in (rdir / "run.log").read_text(encoding="utf-8")
    assert res["log"] == str(rdir / "run.log") and res["stop"] == str(rdir / "stop")


def test_start_invalid_profile_raises_before_popen(tmp_path, monkeypatch):
    from orchestrator.profile import ProfileError
    FakePopen.calls.clear()
    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": 1, "repo": "", "scope": {"mode": "count", "max": 0}}), encoding="utf-8")
    with pytest.raises(ProfileError):
        runner.start(bad, "r", tmp_path / "w")
    assert not FakePopen.calls and not (tmp_path / "w" / "r").exists()


def test_alive_self_and_dead():
    assert runner.alive(os.getpid()) is True
    assert runner.alive(None) is False and runner.alive(0) is False and runner.alive("x") is False
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait(timeout=30)
    assert runner.alive(p.pid) is False


def _write_progress(rdir, lines):
    rdir.mkdir(parents=True, exist_ok=True)
    with open(rdir / "progress.jsonl", "w", encoding="utf-8") as f:
        for ln in lines:
            f.write(json.dumps(ln) + "\n")


def test_attach_distinguishes_interrupted(tmp_path, monkeypatch):
    work = tmp_path / "work"
    cases = {
        "mid": ([{"phase": "analyze", "event": "item", "sha": "abc", "status": "ok"}], "interrupted"),
        "done": ([{"phase": "export", "event": "done"}], "done"),
        "stop": ([{"phase": "scan", "event": "stop"}], "stopped"),
        "err": ([{"phase": "scan", "event": "error", "msg": "x"}], "failed"),
        "empty": ([], "interrupted"),
    }
    for rid, (lines, _) in cases.items():
        _write_progress(work / rid, lines)
        (work / rid / "pid").write_text("777", encoding="utf-8")
    monkeypatch.setattr(rp, "alive", lambda pid: False)
    for rid, (lines, expected) in cases.items():
        a = runner.attach(rid, work)
        assert a["status"] == expected, rid
        assert a["interrupted"] is (expected == "interrupted")
        assert a["pid"] == 777 and a["alive"] is False
        assert (a["last_progress_line"] or None) == (lines[-1] if lines else None)
    monkeypatch.setattr(rp, "alive", lambda pid: True)
    a = runner.attach("mid", work)
    assert a["status"] == "running" and a["interrupted"] is False
    missing = runner.attach("khong-co", work)
    assert missing["exists"] is False and missing["pid"] is None and missing["interrupted"] is True


def test_derive_status_table():
    assert rp.derive_status(None, True) == "running"
    assert rp.derive_status({"phase": "scan", "event": "done"}, False) == "interrupted"  # done giữa chừng ≠ xong
    assert rp.derive_status({"phase": "export", "event": "done"}, False) == "done"


def test_stop_soft_creates_stop_file(tmp_path, monkeypatch, fake_docker):
    work = tmp_path / "work"
    (work / "r1").mkdir(parents=True)
    (work / "r1" / "pid").write_text("4242", encoding="utf-8")
    monkeypatch.setattr(rp, "alive", lambda pid: True)
    res = runner.stop("r1", work)
    assert res["ok"] is True and res["alive_before"] is True and res["killed"] is None
    assert json.loads((work / "r1" / "stop").read_text(encoding="utf-8"))["force"] is False
    assert res["cleanup"] is None and not fake_docker.calls      # không gọi taskkill / stop-cleanup


def test_stop_force_kills_and_calls_cleanup(tmp_path, monkeypatch, fake_docker, profile_file):
    work = tmp_path / "work"
    rdir = work / "r1"
    rdir.mkdir(parents=True)
    (rdir / "pid").write_text("4242", encoding="utf-8")
    (rdir / "meta.json").write_text(json.dumps({"profile": str(profile_file)}), encoding="utf-8")
    state = {"alive": True}

    def _alive(pid):
        return state["alive"]
    monkeypatch.setattr(rp, "alive", _alive)

    def _run(cmd, *a, **kw):
        fake_docker.calls.append(list(cmd))
        if cmd[0] == "taskkill" or "stop-cleanup" in cmd:
            if cmd[0] == "taskkill":
                state["alive"] = False
            if "stop-cleanup" in cmd:
                assert kw["env"]["ORCH_RUN_ID"] == "r1" and kw["env"]["ORCH_SONAR_PORT"] == "9100"
                return subprocess.CompletedProcess(cmd, 2, "", "argument cmd: invalid choice: 'stop-cleanup'")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(subprocess, "run", _run)
    if os.name != "nt":
        monkeypatch.setattr(rp.os, "killpg", lambda pg, sig: state.__setitem__("alive", False))
        monkeypatch.setattr(rp.os, "getpgid", lambda pid: pid)

    res = runner.stop("r1", work, force=True, timeout_s=1, python_exe="py.exe")
    assert res["ok"] is True and res["alive_after"] is False
    if os.name == "nt":
        assert ["taskkill", "/T", "/F", "/PID", "4242"] in fake_docker.calls
        assert res["killed"]["method"] == "taskkill"
    cleanup = res["cleanup"]
    assert cleanup["argv"] == ["py.exe", "-m", "orchestrator.cli", "stop-cleanup", "--run", "r1", "--json"]
    assert cleanup["available"] is False          # lệnh A2 chưa có → ghi log, không crash
    log = (rdir / "run.log").read_text(encoding="utf-8")
    assert "stop-cleanup chưa có" in log and "stop requested force=True" in log


def test_stop_dead_pid_runs_cleanup_without_kill(tmp_path, monkeypatch, fake_docker):
    work = tmp_path / "work"
    (work / "r2").mkdir(parents=True)
    (work / "r2" / "pid").write_text("4242", encoding="utf-8")
    monkeypatch.setattr(rp, "alive", lambda pid: False)
    res = runner.stop("r2", work)
    assert res["killed"] is None and res["cleanup"] is not None
    assert any("stop-cleanup" in c for c in fake_docker.calls)
