"""Test A1 data-core (REVIEW §I.3 D1–D8, CONTRACTS §1/§3/§4/§6). KHÔNG Docker: subprocess mock.

Fixture (tests/conftest.py): scratch_db (bản sao train-ticket 3 commit, user_version 0),
orch_env (ORCH_* trỏ tmp + xoá module orchestrator để nạp lại config), fake_docker (mock subprocess.run).
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest

REPO = "https://github.com/FudanSELab/train-ticket"
BUGGY = "313886e99befb94be6cd45f085c98e0019f59829"   # có finding in_diff -> POSITIVE
CLEAN = "4a9599f4a5b38ce56ae7b7f29a7da9beec87ed11"   # 0 raw_findings -> NEGATIVE
CLEAN2 = "9bdd9a28f0033e91dec4595d257da81cc7016e47"


def _m(name: str):
    return importlib.import_module(name)


def _store(**kw):
    return _m("orchestrator.storage.sqlite_store").SQLiteStore(**kw)


def _sel(cid, role="clean"):
    return {"commit_id": cid, "role": role, "selection_reason": "test",
            "suspect_categories": [], "n_suspect_findings": 0, "created_at": "2026-10-05T00:00:00"}


def _exp(store, cid, tool, status, phase="analyze"):
    store.insert_expensive_run({"commit_id": cid, "tool": tool, "phase": phase, "status": status,
                                "n_findings": 0, "duration_sec": 1.0, "error": None})


def _progress(tmp_path) -> list[dict]:
    return _m("orchestrator.progress").read(tmp_path / "progress.jsonl")


# ---------------------------------------------------------------- D8 / §4: migrate + WAL
def test_migrate_v2_keeps_data(orch_env, scratch_db):
    raw = sqlite3.connect(scratch_db)
    assert raw.execute("PRAGMA user_version").fetchone()[0] == 0
    old_meta = raw.execute("SELECT started_at, repo, tools FROM run_meta").fetchone()
    n_find = raw.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
    raw.close()

    st = _store()
    try:
        c = st.conn
        assert c.execute("PRAGMA user_version").fetchone()[0] == 2
        assert c.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"run_meta", "kappa", "gold_review", "gold_sample"} <= tables
        assert "run_meta_v1" not in tables
        cols = {r[1] for r in c.execute("PRAGMA table_info(selected_commits)")}
        assert "n_expensive_ok" in cols
        assert "run_id" in {r[1] for r in c.execute("PRAGMA table_info(expensive_runs)")}
        # dữ liệu cũ còn nguyên
        assert c.execute("SELECT COUNT(*) FROM findings").fetchone()[0] == n_find
        rows = st.run_meta_rows()
        assert len(rows) == 1
        assert rows[0]["run_id"] == "legacy" and rows[0]["tier"] == "scan"
        assert rows[0]["started_at"] == old_meta[0] and rows[0]["repo"] == old_meta[1]
        assert rows[0]["tools_json"] == json.loads(old_meta[2])
    finally:
        st.close()
    # mở lại: idempotent
    st2 = _store()
    assert st2.conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert len(st2.run_meta_rows()) == 1
    st2.close()


def test_run_meta_v2_insert_and_kappa(orch_env, scratch_db, monkeypatch):
    monkeypatch.setenv("ORCH_EXPERIMENT", "1")
    monkeypatch.setenv("ORCH_EXPERIMENT_REASON", "thử nghiệm cửa sổ W=7")
    st = _store()
    try:
        rid = st.insert_run_meta("analyze", repo=REPO, tools_json=[{"name": "sonar"}],
                                 config_snapshot_json={"a": 1}, orchestrator_git_sha="abc1234")
        st.finish_run_meta(rid, tools_json=[{"name": "sonar"}, {"name": "maven"}])
        rows = [r for r in st.run_meta_rows() if r["id"] == rid]
        assert rows and rows[0]["tier"] == "analyze" and rows[0]["run_id"] == "test-run"
        assert rows[0]["experiment"] == 1 and rows[0]["reason"].startswith("thử")
        assert rows[0]["finished_at"] and len(rows[0]["tools_json"]) == 2
        assert rows[0]["app_version"] == "dev"
        # tương thích dict cũ (cli.cmd_scan)
        rid2 = st.insert_run_meta({"started_at": "x", "repo": REPO, "max_commits": 5,
                                   "vote_threshold": 2, "line_window": 3, "tools": []})
        r2 = [r for r in st.run_meta_rows() if r["id"] == rid2][0]
        assert r2["tier"] == "scan" and r2["scope_json"] == {"mode": "count", "max": 5}
        with pytest.raises(ValueError):
            st.insert_run_meta("export")
        st.save_kappa("test-run", "total", "", 0.12, 40)
        st.save_kappa("test-run", "total", "", 0.15, 41)      # ghi đè cùng (run,scope,grp)
        st.save_kappa("test-run", "category", "code", -0.3, 10)
        ks = st.kappa_rows("test-run")
        assert len(ks) == 2 and [k for k in ks if k["scope"] == "total"][0]["value"] == 0.15
    finally:
        st.close()


# ---------------------------------------------------------------- D1: negative_level
def test_negative_level_requires_two_expensive_ok(orch_env, scratch_db):
    st = _store()
    try:
        st.add_selected([_sel(CLEAN), _sel(CLEAN2)])
        assert st.negative_level(BUGGY) is None                  # positive
        # 0 tool ok (chỉ build skipped) -> cheap-clean
        _exp(st, CLEAN, "maven", "skipped", phase="build")
        assert st.update_n_expensive_ok(CLEAN) == 0
        assert st.negative_level(CLEAN) == "cheap-clean"
        # 1 tool ok + 1 tool lỗi -> vẫn cheap-clean (TC-17)
        _exp(st, CLEAN, "maven", "ok", phase="build")
        _exp(st, CLEAN, "findsecbugs", "ok")
        _exp(st, CLEAN, "sonar", "tool_error")
        assert st.update_n_expensive_ok(CLEAN) == 1
        assert st.negative_level(CLEAN) == "cheap-clean"
        # 2 tool ok -> verified-clean; chạy lại cùng tool không đếm đôi
        _exp(st, CLEAN, "sonar", "ok")
        _exp(st, CLEAN, "sonar", "ok")
        assert st.update_n_expensive_ok(CLEAN) == 2
        assert st.negative_level(CLEAN) == "verified-clean"
        assert st.selected_rows()[CLEAN]["n_expensive_ok"] == 2
        # skipped không bao giờ tính
        _exp(st, CLEAN2, "findsecbugs", "skipped")
        _exp(st, CLEAN2, "sonar", "skipped")
        assert st.negative_level(CLEAN2) == "cheap-clean"
    finally:
        st.close()


# ---------------------------------------------------------------- D3 / D8: lock + readonly
def test_db_lock_and_readonly(orch_env, scratch_db):
    sq = _m("orchestrator.storage.sqlite_store")
    lock = Path(str(scratch_db) + ".lock")
    a = _store()
    try:
        assert lock.exists()
        info = json.loads(lock.read_text(encoding="utf-8"))
        assert info["pid"] == os.getpid() and info["run_id"] == "test-run"
        with pytest.raises(RuntimeError, match="run khác"):
            _store()
        ro = _store(readonly=True)                               # GUI: không lock, không migrate
        assert ro.conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0] == 17
        with pytest.raises(sqlite3.OperationalError):
            ro.conn.execute("INSERT INTO scan_done VALUES ('x','y')")
        ro.close()
        assert lock.exists()                                     # readonly không xoá lock của run ghi
    finally:
        a.close()
    assert not lock.exists()
    # lock mồ côi (pid chết) -> chiếm lại được
    lock.write_text(json.dumps({"pid": 999999, "run_id": "dead"}), encoding="utf-8")
    assert not sq.pid_alive(999999)
    b = _store()
    assert json.loads(lock.read_text(encoding="utf-8"))["pid"] == os.getpid()
    b.close()


def test_disk_full_raises_infra_error(orch_env, scratch_db, monkeypatch):
    InfraError = _m("orchestrator.storage").InfraError
    st = _store()
    try:
        class _FullDisk:
            def execute(self, *a, **k):
                raise sqlite3.OperationalError("database or disk is full")

            def commit(self):
                pass
        real = st.conn
        st.conn = _FullDisk()                                   # sqlite3.Connection không patch được
        try:
            with pytest.raises(InfraError):
                st.mark_scan_done(CLEAN)
        finally:
            st.conn = real
    finally:
        st.close()


# ---------------------------------------------------------------- D2: phân loại infra_error
@pytest.mark.parametrize("rc,err,expect", [
    (125, "", "infra_error"),
    (127, "docker: command not found", "infra_error"),
    (1, "error during connect: this error may indicate that the docker daemon is not running", "infra_error"),
    (1, "Cannot connect to the Docker daemon at unix:///var/run/docker.sock", "infra_error"),
    (1, "open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified", "infra_error"),
    (1, "write /var/lib/docker/x: no space left on device", "infra_error"),
    (1, "Error: disk is full", "infra_error"),
    (1, "[ERROR] Failed to execute goal ... Could not resolve dependencies", None),
    (0, "", None),
])
def test_classify_failure(orch_env, rc, err, expect):
    base = _m("orchestrator.tools.base")
    assert base.classify_failure(rc, err, "") == expect


def test_build_commit_status_classification(orch_env, fake_docker, tmp_path, monkeypatch):
    build = _m("orchestrator.tools_expensive.build")
    clone = tmp_path / "clone"
    clone.mkdir()
    # 0 module Java -> skipped, không gọi docker
    monkeypatch.setattr(build, "changed_modules", lambda c, s: [])
    ctx = build.build_commit(clone, CLEAN, REPO)
    assert ctx.status == "skipped" and ctx.skipped and not ctx.ok
    assert not any("run" in c for c in fake_docker.calls)

    monkeypatch.setattr(build, "changed_modules", lambda c, s: ["ts-ui-dashboard"])
    monkeypatch.setattr(build, "maven_image_for", lambda c, s: "maven:3.9-eclipse-temurin-8")
    # Docker tắt -> infra_error (KHÔNG build_failed)
    fake_docker.responses.append((lambda cmd: "run" in cmd,
                                  (125, "", "error during connect: Docker Desktop is not running")))
    ctx = build.build_commit(clone, CLEAN, REPO)
    assert ctx.status == "infra_error" and not ctx.ok
    assert ctx.image == "maven:3.9-eclipse-temurin-8"
    assert "--label" in fake_docker.calls[-1] and "orch.run=test-run" in fake_docker.calls[-1]
    # lỗi mvn thật -> build_failed
    fake_docker.responses.clear()
    fake_docker.responses.append((lambda cmd: "run" in cmd,
                                  (1, "[ERROR] Failed to execute goal: Could not resolve dependencies", "")))
    ctx = build.build_commit(clone, CLEAN, REPO)
    assert ctx.status == "build_failed" and "Could not resolve" in ctx.error
    # timeout -> tool_timeout
    def _to(cmd, *a, **k):
        raise subprocess.TimeoutExpired(cmd, 5)
    monkeypatch.setattr(subprocess, "run", _to)
    ctx = build.build_commit(clone, CLEAN, REPO)
    assert ctx.status == "tool_timeout"


def test_classify_tool_exceptions(orch_env):
    er = _m("orchestrator.expensive_runner")
    ToolError = _m("orchestrator.tools_expensive.base").ToolError
    assert er._classify_tool_exc(subprocess.TimeoutExpired(["docker"], 9))[0] == "tool_timeout"
    assert er._classify_tool_exc(ToolError("findsecbugs không ra XML (rc=1): No files"))[0] == "tool_error"
    assert er._classify_tool_exc(ValueError("xml 0 byte"))[0] == "tool_error"
    assert er._classify_tool_exc(ToolError(
        "sonar rc=125: Cannot connect to the Docker daemon"))[0] == "infra_error"
    assert er._classify_tool_exc(FileNotFoundError("docker"))[0] == "infra_error"


# ---------------------------------------------------------------- --label cho mọi docker run
def test_docker_run_adds_label(orch_env, fake_docker):
    base = _m("orchestrator.tools.base")
    base.docker_run(["run", "--rm", "alpine", "true"])
    assert fake_docker.calls[-1][:4] == ["docker", "run", "--label", "orch.run=test-run"]
    base.docker_run(["image", "inspect", "x"])                      # không phải run -> không label
    assert "--label" not in fake_docker.calls[-1]
    base.docker_run(["run", "--label", "orch.run=test-run", "img"])  # đã có -> không nhân đôi
    assert fake_docker.calls[-1].count("--label") == 1


def test_sonar_names_follow_run_id(orch_env, fake_docker):
    sonar = _m("orchestrator.tools_expensive.sonar")
    t = sonar.SonarTool()
    assert t.server == "orch-sonar-test-run" and t.network == "orch-sonar-net-test-run"
    assert sonar.SonarTool(run_id="abc").server == "orch-sonar-abc"
    t.stop_server()
    rm = [c for c in fake_docker.calls if c[1] == "rm"]
    assert rm and rm[0][-1] == "orch-sonar-test-run"               # chỉ đụng container của run này


# ---------------------------------------------------------------- analyze: stop-file + infra stop
class _FakePool:
    def __init__(self, main, size, repo=None):
        self.main, self.size, self.repo = main, size, repo

    def acquire(self):
        return Path(self.main)

    def release(self, clone):
        pass

    def checkout(self, clone, sha):
        pass

    def cleanup(self):
        pass


def _patch_runner(monkeypatch, tmp_path):
    er = _m("orchestrator.expensive_runner")
    monkeypatch.setattr(er.enm, "clone_or_update", lambda repo: tmp_path / "main")
    monkeypatch.setattr(er, "RepoPool", _FakePool)
    return er


def test_stop_file_prevents_claim(orch_env, fake_docker, monkeypatch):
    tmp_path = orch_env
    er = _patch_runner(monkeypatch, tmp_path)
    (tmp_path / "stop").write_text("", encoding="utf-8")            # ORCH_STOP_FILE
    called = []
    monkeypatch.setattr(er, "build_commit", lambda *a: called.append(a))
    res = er.analyze(REPO, workers=1, tools=["findsecbugs"])
    assert res["stopped"] is True and res["stop_reason"] == "stop_file"
    assert not called
    st = _store()
    try:
        assert st.selected_rows()[BUGGY]["status"] == "pending"
        meta = [r for r in st.run_meta_rows() if r["tier"] == "analyze"]
        assert len(meta) == 1 and meta[0]["finished_at"] and meta[0]["run_id"] == "test-run"
    finally:
        st.close()
    ev = _progress(tmp_path)
    assert [e["event"] for e in ev if e["phase"] == "analyze"] == ["start", "stop"]
    assert ev[0]["total"] == 1 and ev[-1]["status"] == "stop_file"


def test_three_infra_errors_stop_run(orch_env, fake_docker, monkeypatch):
    tmp_path = orch_env
    er = _patch_runner(monkeypatch, tmp_path)
    BuildContext = _m("orchestrator.tools_expensive.base").BuildContext
    st = _store()
    st.add_selected([_sel(CLEAN), _sel(CLEAN2), _sel("c" * 40)])
    st.close()

    def _infra(clone, cid, repo):
        return BuildContext(commit_id=cid, repo=repo, clone_dir=clone, ok=False,
                            status="infra_error", error="mvn rc=125: error during connect",
                            image="maven:3.9-eclipse-temurin-8")
    monkeypatch.setattr(er, "build_commit", _infra)
    res = er.analyze(REPO, workers=1, tools=["findsecbugs"])
    assert res["stopped"] is True and res["stop_reason"] == "infra_error"
    assert res["infra_error"] == 3 and res.get("build_failed", 0) == 0
    st = _store()
    try:
        rows = st.selected_rows()
        assert all(r["status"] == "pending" for r in rows.values())       # không mất commit
        assert all(r["claimed_by"] is None for r in rows.values())
        runs = st.conn.execute(
            "SELECT status, COUNT(*) FROM expensive_runs GROUP BY status").fetchall()
        assert dict(runs) == {"infra_error": 3}
        assert st.negative_level(CLEAN) == "cheap-clean"
    finally:
        st.close()
    ev = [e for e in _progress(tmp_path) if e["phase"] == "analyze"]
    assert [e["event"] for e in ev] == ["start", "item", "item", "item", "stop"]
    assert ev[-1]["status"] == "infra_error" and all(e["status"] == "infra_error" for e in ev[1:4])


def test_skipped_and_done_flow_sets_n_expensive_ok(orch_env, fake_docker, monkeypatch):
    tmp_path = orch_env
    er = _patch_runner(monkeypatch, tmp_path)
    BuildContext = _m("orchestrator.tools_expensive.base").BuildContext
    st = _store()
    st.replace_selected([_sel(CLEAN), _sel(CLEAN2)])
    st.close()

    class _OkTool:
        name, image = "findsecbugs", "orch-findsecbugs:1.14.0"

        def scan(self, ctx, raw_out=None):
            raw_out.append(("xml", "<BugCollection/>"))
            return []

    class _OkTool2(_OkTool):
        name, image = "sonar", "sonarqube:lts-community"

    monkeypatch.setattr(er, "_make_tools", lambda names: [_OkTool(), _OkTool2()])

    def _build(clone, cid, repo):
        if cid == CLEAN2:
            return BuildContext(commit_id=cid, repo=repo, clone_dir=clone, status="skipped")
        return BuildContext(commit_id=cid, repo=repo, clone_dir=clone, ok=True, status="ok",
                            classes_dirs=[clone], image="maven:3.9-eclipse-temurin-8")
    monkeypatch.setattr(er, "build_commit", _build)
    res = er.analyze(REPO, workers=1, tools=["findsecbugs", "sonar"])
    assert res["stopped"] is False and res["done"] == 1 and res["skipped"] == 1
    st = _store()
    try:
        rows = st.selected_rows()
        assert rows[CLEAN]["status"] == "done" and rows[CLEAN]["n_expensive_ok"] == 2
        assert rows[CLEAN2]["status"] == "done" and rows[CLEAN2]["build_status"] == "skipped"
        assert rows[CLEAN2]["n_expensive_ok"] == 0
        assert st.negative_level(CLEAN) == "verified-clean"
        assert st.negative_level(CLEAN2) == "cheap-clean"               # TC-16: không phải GOLD
        skipped = st.conn.execute(
            "SELECT tool, status FROM expensive_runs WHERE commit_id=?", [CLEAN2]).fetchall()
        assert skipped == [("maven", "skipped")]                         # tool đắt KHÔNG chạy
        meta = [r for r in st.run_meta_rows() if r["tier"] == "analyze"][0]
        names = {t["name"]: t for t in meta["tools_json"]}
        assert {"findsecbugs", "sonar", "maven"} <= set(names)
        assert names["maven"]["image"] == "maven:3.9-eclipse-temurin-8"
    finally:
        st.close()
    ev = [e for e in _progress(tmp_path) if e["phase"] == "analyze"]
    assert ev[-1]["event"] == "done" and {e["status"] for e in ev[1:-1]} == {"done", "skipped"}


# ---------------------------------------------------------------- D5 / §6: export
def test_export_all_files_and_no_mixing(orch_env, fake_docker):
    exp = _m("orchestrator.export_dataset")
    st = _store()
    st.add_selected([_sel(CLEAN)])
    _exp(st, CLEAN, "maven", "ok", phase="build")
    _exp(st, CLEAN, "findsecbugs", "ok")
    _exp(st, CLEAN, "sonar", "ok")
    st.update_n_expensive_ok(CLEAN)
    _exp(st, CLEAN2, "maven", "skipped", phase="build")
    st.save_kappa("test-run", "total", "", 0.2, 12)
    out = orch_env / "export"
    res = exp.export_all(st, out, profile={"schema": 1, "repo": REPO})
    assert Path(res["out"]) == out
    for n in ("dataset.jsonl", "commits.jsonl", "run_manifest.json", "negatives.json", "SHA256SUMS"):
        assert (out / n).exists(), n
    assert (out / BUGGY[:12] / "label.json").exists()

    rows = [json.loads(l) for l in (out / "dataset.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 17
    keys = _m("orchestrator.keys")
    r0 = rows[0]
    assert len(r0["cluster_key"]) == 32
    assert r0["cluster_key"] == keys.cluster_key(r0["repo"], r0["commit_id"], r0["file_path"],
                                                 r0["cwe_group"], r0["s_line"])
    assert r0["evidence"] == {"consensus": "candidate", "validation": "unreviewed"}
    # gold_review -> validation
    st.conn.execute("INSERT INTO gold_review VALUES (?,?,?,?,?,datetime('now'))",
                    [r0["cluster_key"], "s1", "rater1", "TP", ""])
    st.conn.commit()

    commits = {json.loads(l)["commit_id"]: json.loads(l)
               for l in (out / "commits.jsonl").read_text(encoding="utf-8").splitlines()}
    assert set(commits) == {BUGGY, CLEAN, CLEAN2}
    assert commits[CLEAN]["n_expensive_ok"] == 2 and commits[CLEAN]["negative_level"] == "verified-clean"
    assert commits[CLEAN2]["n_expensive_ok"] == 0 and commits[CLEAN2]["negative_level"] == "cheap-clean"
    assert commits[BUGGY]["negative_level"] is None and commits[BUGGY]["labels"] == {"candidate": 17}
    assert commits[CLEAN]["kamei"]["nf"] is not None

    man = json.loads((out / "run_manifest.json").read_text(encoding="utf-8"))
    for k in ("profile", "run_meta", "kappa", "counts", "build_failed", "infra_error", "tool_timeout",
              "skipped", "orchestrator_git_sha", "app_version", "os", "docker_version", "started",
              "finished", "params_v1", "experiment", "run_id"):
        assert k in man, k
    assert man["skipped"] == [CLEAN2] and man["kappa"][0]["value"] == 0.2
    assert man["counts"]["verified_clean"] == 1 and man["counts"]["cheap_clean"] == 1
    assert man["counts"]["candidate"] == 17 and man["params_v1"]["line_window"] == 3
    assert man["docker_version"] is None and man["experiment"] is None
    assert man["run_id"] == "test-run" and man["run_meta"][0]["run_id"] == "legacy"

    sums = dict(reversed(l.split("  ")) for l in
                (out / "SHA256SUMS").read_text(encoding="utf-8").splitlines())
    assert set(sums) == {"dataset.jsonl", "commits.jsonl", "run_manifest.json"}
    for n, h in sums.items():
        assert hashlib.sha256((out / n).read_bytes()).hexdigest() == h

    # D5: export lần 2 vào thư mục đã có dữ liệu -> _2, không trộn
    res2 = exp.export_all(st, out)
    assert Path(res2["out"]) == Path(str(out) + "_2") and (Path(res2["out"]) / "dataset.jsonl").exists()
    rows2 = [json.loads(l) for l in (Path(res2["out"]) / "dataset.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows2[0]["evidence"]["validation"] == "TP"
    st.close()


def test_merge_export_script_readonly(orch_env, fake_docker, scratch_db):
    """scripts/merge_export.py gọi hàm mới, mở DB readonly (không đụng lock của run ghi)."""
    import sys
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "scripts"))
    try:
        merge = importlib.import_module("merge_export")
        importlib.reload(merge)
    finally:
        sys.path.pop(0)
    out = orch_env / "legacy_export"
    writer = _store()                      # run ghi đang giữ lock
    try:
        merge.main(str(out), str(scratch_db))
    finally:
        writer.close()
    assert (out / "dataset.jsonl").exists() and (out / "commits.jsonl").exists()
    assert len((out / "commits.jsonl").read_text(encoding="utf-8").splitlines()) == 3


# ---------------------------------------------------------------- D4 / D7: repo_pool
def test_verify_origin(orch_env, tmp_path):
    if not shutil.which("git"):
        pytest.skip("không có git")
    rp = _m("orchestrator.repo_pool")
    d = tmp_path / "clone"
    d.mkdir()
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    subprocess.run(["git", "-C", str(d), "remote", "add", "origin",
                    "https://github.com/OtherOrg/train-ticket.git"], check=True)
    assert rp.verify_origin(d, "https://github.com/otherorg/train-ticket") \
        == "https://github.com/OtherOrg/train-ticket"
    with pytest.raises(rp.OriginMismatch, match="trùng tên"):
        rp.verify_origin(d, REPO)
    with pytest.raises(rp.OriginMismatch):
        rp.verify_origin(tmp_path, REPO)                       # không phải git repo


def test_rmtree_force_readonly(orch_env, tmp_path):
    rp = _m("orchestrator.repo_pool")
    d = tmp_path / "pool_x" / "w0" / ".git" / "objects"
    d.mkdir(parents=True)
    f = d / "pack.idx"
    f.write_bytes(b"x")
    os.chmod(f, 0o444)
    rp.rmtree_force(tmp_path / "pool_x")
    assert not (tmp_path / "pool_x").exists()
    rp.rmtree_force(tmp_path / "khong_ton_tai")                # không raise


def test_run_meta_timestamps_same_local_iso_format(orch_env, scratch_db):
    """started_at và finished_at cùng local ISO có 'T' (không trộn datetime('now') UTC) — lỗi smoke 2026-10-05."""
    import re
    iso = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
    st = _store()
    try:
        rid = st.insert_run_meta("analyze", repo=REPO)
        st.finish_run_meta(rid)
        st.save_kappa("test-run", "total", "", 0.1, 3)
        row = [r for r in st.run_meta_rows() if r["id"] == rid][0]
        assert iso.match(row["started_at"]) and iso.match(row["finished_at"]), row
        assert row["finished_at"] >= row["started_at"]
        assert abs(int(row["finished_at"][11:13]) - int(time.strftime("%H"))) <= 1   # giờ local, không lệch UTC
        assert iso.match(st.kappa_rows("test-run")[0]["computed_at"])
    finally:
        st.close()
