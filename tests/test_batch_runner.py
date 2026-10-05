"""runner.batch_runner.run_queue: mock Popen; tuần tự, registry, stop-file batch, stop_on_error, profile hỏng."""
from __future__ import annotations

import json
import subprocess

import pytest

import registry
from runner import batch_runner
from runner import process as rp


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.setenv("SECJIT_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def _profile(tmp_path, scratch_db, name):
    from orchestrator import profile
    import shutil
    db = tmp_path / f"{name}.sqlite"
    shutil.copy(scratch_db, db)
    p = profile.default_profile(f"https://github.com/x/{name}", "main")
    p["paths"] = {"db": str(db), "export": str(tmp_path / f"exp_{name}"), "work": str(tmp_path / "work")}
    path = tmp_path / f"{name}.json"
    profile.save(p, path)
    return path


class FakePopen:
    """Giả tiến trình: ghi progress theo kịch bản `script[run_id]` rồi 'chết' (alive() False sau 1 poll)."""
    script: dict = {}
    started: list = []

    def __init__(self, argv, **kw):
        self.argv, self.kw = argv, kw
        env = kw["env"]
        rid = env["ORCH_RUN_ID"]
        self.pid = 5000 + len(FakePopen.started)
        FakePopen.started.append(rid)
        assert env["ORCH_BATCH_ID"] and env["ORCH_PROGRESS_FILE"].endswith("progress.jsonl")
        lines = FakePopen.script.get(rid, [{"phase": "export", "event": "done"}])
        with open(env["ORCH_PROGRESS_FILE"], "w", encoding="utf-8") as f:
            for ln in lines:
                f.write(json.dumps(ln) + "\n")


@pytest.fixture
def fake_popen(monkeypatch):
    FakePopen.script, FakePopen.started = {}, []
    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    seen: set = set()

    def alive(pid):          # mỗi pid "sống" đúng ở lần hỏi đầu, sau đó chết (bền với số lần gọi phụ)
        if pid in seen:
            return False
        seen.add(pid)
        return True
    monkeypatch.setattr(rp, "alive", alive)
    return FakePopen


def test_queue_sequential_done_and_registry(tmp_path, scratch_db, home, fake_popen):
    q = tmp_path / "Q.json"
    q.write_text(json.dumps([str(_profile(tmp_path, scratch_db, "a")), "b.json"]), encoding="utf-8")
    _profile(tmp_path, scratch_db, "b")
    events = []
    st = batch_runner.run_queue(q, tmp_path / "work", batch_id="B1", poll_s=0, on_event=events.append)
    assert st["status"] == "done" and st["exit_code"] == 0
    assert [i["status"] for i in st["items"]] == ["done", "done"]
    assert fake_popen.started == ["B1-0", "B1-1"]
    runs = {r["run_id"]: r for r in registry.load()["runs"]}
    assert runs["B1-0"]["status"] == "done" and runs["B1-0"]["summary"]["batch_id"] == "B1"
    assert runs["B1-1"]["pid"] == 5001 and runs["B1-1"]["finished"]
    assert [e["event"] for e in events] == ["started", "finished", "started", "finished"]
    state = json.loads((tmp_path / "batch_state.json").read_text(encoding="utf-8"))
    assert state["registry"] is True and state["counts"]["done"] == 2
    assert not registry.locks.read_lock(tmp_path / "a.sqlite")      # lock đã nhả
    # run_dir có pid + meta
    assert (tmp_path / "work" / "B1-0" / "meta.json").exists()


def test_queue_stop_file_before_second(tmp_path, scratch_db, home, fake_popen, monkeypatch):
    pa, pb = _profile(tmp_path, scratch_db, "a"), _profile(tmp_path, scratch_db, "b")
    q = tmp_path / "Q.json"
    q.write_text(json.dumps({"profiles": [str(pa), str(pb)]}), encoding="utf-8")
    stop = tmp_path / "Q.json.stop"
    orig_start = rp.start

    def start_then_stop(*a, **k):      # stop-file xuất hiện trong khi run 0 chạy
        res = orig_start(*a, **k)
        stop.write_text("x", encoding="utf-8")
        return res
    monkeypatch.setattr(rp, "start", start_then_stop)
    st = batch_runner.run_queue(q, tmp_path / "work", batch_id="B2", poll_s=0)
    assert st["status"] == "stopped" and st["exit_code"] == 3
    assert [i["status"] for i in st["items"]] == ["done", "skipped"]      # run 0 kịp done, run 1 không khởi động
    assert fake_popen.started == ["B2-0"]
    assert (tmp_path / "work" / "B2-0" / "stop").exists()                 # đã yêu cầu dừng mềm run 0


def test_queue_run_stopped_or_failed(tmp_path, scratch_db, home, fake_popen):
    pa, pb, pc = (_profile(tmp_path, scratch_db, n) for n in ("a", "b", "c"))
    q = tmp_path / "Q.json"
    q.write_text(json.dumps([str(pa), str(pb), str(pc)]), encoding="utf-8")
    fake_popen.script = {"B3-0": [{"phase": "analyze", "event": "item"}],     # chết giữa chừng → interrupted
                         "B3-1": [{"phase": "scan", "event": "stop"}]}          # stop-file của run → dừng cả hàng đợi
    st = batch_runner.run_queue(q, tmp_path / "work", batch_id="B3", poll_s=0)
    assert [i["status"] for i in st["items"]] == ["interrupted", "stopped", "skipped"]
    assert [i["rc"] for i in st["items"]] == [2, 3, None]
    assert st["status"] == "stopped" and st["exit_code"] == 3
    assert registry.get("B3-0")["status"] == "interrupted"


def test_queue_stop_on_error_and_bad_profile(tmp_path, scratch_db, home, fake_popen):
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    pb = _profile(tmp_path, scratch_db, "b")
    q = tmp_path / "Q.json"
    q.write_text(json.dumps({"profiles": [str(bad), str(pb)], "stop_on_error": True}), encoding="utf-8")
    st = batch_runner.run_queue(q, tmp_path / "work", batch_id="B4", poll_s=0)
    assert st["items"][0]["status"] == "failed" and "ProfileError" in st["items"][0]["error"]
    assert st["items"][1]["status"] == "skipped" and st["exit_code"] == 3 and not fake_popen.started
    # không stop_on_error → vẫn chạy mục kế, kết quả failed/exit 2
    q.write_text(json.dumps([str(bad), str(pb)]), encoding="utf-8")
    st = batch_runner.run_queue(q, tmp_path / "work", batch_id="B5", poll_s=0)
    assert [i["status"] for i in st["items"]] == ["failed", "done"] and st["exit_code"] == 2


def test_queue_db_locked_by_live_run_fails_item(tmp_path, scratch_db, home, fake_popen, monkeypatch):
    pa = _profile(tmp_path, scratch_db, "a")
    registry.locks.lock_path(tmp_path / "a.sqlite").write_text(json.dumps({"pid": 1, "run_id": "khac"}), encoding="utf-8")
    monkeypatch.setattr(rp, "alive", lambda pid: pid == 1)
    q = tmp_path / "Q.json"
    q.write_text(json.dumps([str(pa)]), encoding="utf-8")
    st = batch_runner.run_queue(q, tmp_path / "work", batch_id="B6", poll_s=0)
    assert st["items"][0]["status"] == "failed" and "DbLocked" in st["items"][0]["error"]


def test_cli_main(tmp_path, scratch_db, home, fake_popen, capsys):
    pa = _profile(tmp_path, scratch_db, "a")
    q = tmp_path / "Q.json"
    q.write_text(json.dumps([str(pa)]), encoding="utf-8")
    rc = batch_runner.main([str(q), "--work-dir", str(tmp_path / "work"), "--batch-id", "B7", "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["batch_id"] == "B7"
