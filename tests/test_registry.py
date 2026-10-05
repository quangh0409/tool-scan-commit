"""Registry: upsert/set_status/refresh atomic; db_lock stale; single_instance; speed.json."""
from __future__ import annotations

import json
import os
import sqlite3
import threading

import pytest

import registry
from registry import locks, speed
from runner import process as rp


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.setenv("SECJIT_HOME", str(tmp_path / "secjit"))
    return tmp_path / "secjit"


def test_path_under_home(home):
    assert registry.path() == home / "runs.json"
    assert registry.load() == {"runs": []}


def test_conftest_isolates_real_registry(tmp_path):
    """Lưới an toàn: KHÔNG có fixture nào khác, registry.home() vẫn phải nằm trong tmp (conftest `_isolate_secjit_home`)."""
    import os
    h = registry.home()
    assert str(h).startswith(str(tmp_path)), f"registry.home()={h} không nằm trong tmp — test sẽ ghi registry THẬT"
    real = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    assert not str(h).startswith(os.path.join(real, "secjit")), h
    registry.upsert({"run_id": "isolated-check", "status": "done"})
    assert (h / "runs.json").exists()


def test_upsert_merge_and_atomic(home):
    r = registry.upsert({"run_id": "r1", "repo": "https://github.com/a/b", "db": "x.sqlite",
                         "work": "w", "pid": 123, "summary": {"a": 1}})
    assert r["status"] == "running" and r["started"]
    registry.upsert({"run_id": "r1", "summary": {"b": 2}, "pid": 124})
    got = registry.get("r1")
    assert got["summary"] == {"a": 1, "b": 2} and got["pid"] == 124 and got["repo"] == "https://github.com/a/b"
    assert not list(home.glob("runs.json.tmp*")), "file tạm phải được replace"
    with pytest.raises(ValueError):
        registry.upsert({"repo": "x"})
    with pytest.raises(ValueError):
        registry.upsert({"run_id": "r2", "status": "weird"})


def test_set_status_sets_finished(home):
    registry.upsert({"run_id": "r1"})
    r = registry.set_status("r1", "done", summary={"gold": 3})
    assert r["status"] == "done" and r["finished"] and r["summary"]["gold"] == 3
    assert registry.remove("r1") is True and registry.get("r1") is None


def test_load_corrupt_file_recovers(home):
    home.mkdir(parents=True)
    (home / "runs.json").write_text("{not json", encoding="utf-8")
    assert registry.load() == {"runs": []}
    assert (home / "runs.json.corrupt").exists()


def test_concurrent_upserts_no_loss(home):
    def work(i):
        registry.upsert({"run_id": f"r{i}", "pid": i})
    ts = [threading.Thread(target=work, args=(i,)) for i in range(20)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(registry.load()["runs"]) == 20
    json.loads(registry.path().read_text(encoding="utf-8"))


def _progress(rdir, lines):
    rdir.mkdir(parents=True, exist_ok=True)
    with open(rdir / "progress.jsonl", "w", encoding="utf-8") as f:
        for ln in lines:
            f.write(json.dumps(ln) + "\n")


def test_refresh_status_interrupted_vs_done(home, tmp_path, monkeypatch, scratch_db):
    work = tmp_path / "work"
    for rid, lines in (("dead-mid", [{"phase": "analyze", "event": "item", "done": 2}]),
                       ("dead-done", [{"phase": "export", "event": "done"}]),
                       ("dead-stop", [{"phase": "analyze", "event": "stop"}]),
                       ("alive", [{"phase": "scan", "event": "item"}])):
        _progress(work / rid, lines)
        (work / rid / "pid").write_text("99999", encoding="utf-8")
        registry.upsert({"run_id": rid, "work": str(work), "pid": 99999, "db": str(scratch_db)})
    # đánh dấu DB còn commit building để kiểm stale_claims
    con = sqlite3.connect(scratch_db)
    con.execute("UPDATE selected_commits SET status='building'")
    con.commit()
    con.close()
    monkeypatch.setattr(rp, "alive", lambda pid: False)
    # 'alive' giả lập: alive() True chỉ cho run đó bằng cách đổi pid
    registry.upsert({"run_id": "alive", "pid": 4242})
    monkeypatch.setattr(rp, "alive", lambda pid: pid == 4242)
    changed = {r["run_id"]: r["status"] for r in registry.refresh_status()}
    assert changed == {"dead-mid": "interrupted", "dead-done": "done", "dead-stop": "stopped"}
    runs = {r["run_id"]: r for r in registry.load()["runs"]}
    assert runs["alive"]["status"] == "running"
    assert runs["dead-mid"]["summary"]["stale_claims"] == 1 and "reset-claims" in runs["dead-mid"]["summary"]["hint"]
    assert runs["dead-done"]["finished"]


# ---------------------------------------------------------------- locks

def test_db_lock_stale_overwritten(tmp_path, monkeypatch):
    db = tmp_path / "d.sqlite"
    lp = locks.lock_path(db)
    lp.write_text(json.dumps({"pid": 999999, "run_id": "old"}), encoding="utf-8")
    monkeypatch.setattr(rp, "alive", lambda pid: False)
    with locks.db_lock(db, "new", pid=os.getpid()) as p:
        info = json.loads(p.read_text(encoding="utf-8"))
        assert info["run_id"] == "new" and info["pid"] == os.getpid()
    assert not lp.exists()


def test_db_lock_held_raises(tmp_path, monkeypatch):
    db = tmp_path / "d.sqlite"
    locks.lock_path(db).write_text(json.dumps({"pid": 4242, "run_id": "other"}), encoding="utf-8")
    monkeypatch.setattr(rp, "alive", lambda pid: pid == 4242)
    with pytest.raises(locks.DbLocked) as ei:
        locks.acquire_db_lock(db, "me", pid=1)
    assert ei.value.info["run_id"] == "other"
    assert locks.lock_status(db) == (True, {"pid": 4242, "run_id": "other"})
    # force ghi đè; release của run khác không xoá
    locks.acquire_db_lock(db, "me", pid=1, force=True)
    assert locks.release_db_lock(db, "other") is False
    assert locks.release_db_lock(db, "me") is True


def test_db_lock_corrupt_treated_stale(tmp_path):
    db = tmp_path / "d.sqlite"
    locks.lock_path(db).write_text("garbage", encoding="utf-8")
    held, info = locks.lock_status(db)
    assert held is False and info == {"corrupt": True}
    locks.acquire_db_lock(db, "me")


def test_single_instance(home):
    a = locks.single_instance("secjit-test-" + str(os.getpid()))
    try:
        assert a.acquired is True
        b = locks.single_instance("secjit-test-" + str(os.getpid()))
        assert b.acquired is False
        b.release()
    finally:
        a.release()
    c = locks.single_instance("secjit-test-" + str(os.getpid()))
    assert c.acquired is True
    c.release()


# ---------------------------------------------------------------- speed

def test_speed_default_then_update_from_db(home, scratch_db):
    s = speed.load()
    assert s["samples"] == 0 and s["source"] == "default" and s["cheap_s_per_commit"] == 12
    con = sqlite3.connect(scratch_db)
    rows = [("c1", "maven", "build", "ok", 800.0, "2026-10-04T10:00:00"),
            ("c2", "maven", "build", "ok", 100.0, "2026-10-04T10:20:00"),
            ("c3", "maven", "build", "ok", 140.0, "2026-10-04T10:30:00"),
            ("c1", "findsecbugs", "analyze", "ok", 30.0, "2026-10-04T10:15:00"),
            ("c1", "sonar", "analyze", "ok", 60.0, "2026-10-04T10:16:00"),
            ("c4", "maven", "build", "build_failed", 50.0, "2026-10-04T10:40:00")]
    con.executemany("INSERT INTO expensive_runs (commit_id,tool,phase,status,duration_sec,created_at) "
                    "VALUES (?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    m = speed.measure_db(scratch_db)
    assert m["build_cold_s"] == [800.0] and m["build_warm_s"] == [100.0, 140.0]
    assert m["fsb_s"] == [30.0] and m["sonar_s"] == [60.0]
    assert m["buggy_ratio"] == [pytest.approx(1 / 3)]
    s = speed.update_from_db(scratch_db)
    assert s["source"] == "measured" and s["samples"] == 6
    assert s["build_cold_s"] == 800.0 and s["build_warm_s"] == 120.0 and s["sonar_s"] == 60.0
    # lần 2: EMA alpha 0.3
    s2 = speed.update_from_db(scratch_db, alpha=0.5)
    assert s2["build_warm_s"] == 120.0 and s2["samples"] == 12
    assert speed.path().exists()


def test_speed_update_from_progress(home, tmp_path):
    p = tmp_path / "progress.jsonl"
    lines = [{"ts": "2026-10-05T10:00:00", "phase": "scan", "event": "start", "total": 10},
             {"ts": "2026-10-05T10:00:30", "phase": "scan", "event": "item", "done": 3},
             {"ts": "2026-10-05T10:01:40", "phase": "scan", "event": "item", "done": 10},
             {"ts": "2026-10-05T10:02:00", "phase": "scan", "event": "done"}]
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\nhỏng\n", encoding="utf-8")
    assert speed.measure_progress(p)["cheap_s_per_commit"] == [10.0]
    s = speed.update_from_progress(p)
    assert s["cheap_s_per_commit"] == 10.0 and s["samples"] == 1
    est = speed.estimate(100, workers_expensive=2, speed=s)
    assert est["cheap_minutes"] == pytest.approx(16.7, abs=0.1) and est["buggy_est"] == 30
    assert est["speed_source"] == "measured"
