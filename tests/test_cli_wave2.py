"""Test A2 đợt 2: review subcommand (module giả), batch tuần tự + stop-file (runner mock),
diagnostics zip + redact, `_m2_cache` theo ORCH_M2_VOLUME (docker mock)."""
from __future__ import annotations

import json
import os
import sys
import types
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


# ----------------------------------------------------------------------------- review
@pytest.fixture
def fake_review(monkeypatch):
    calls: list[tuple] = []
    mod = types.ModuleType("orchestrator.review")

    def sample(store, seed, n_pos, n_neg):
        calls.append(("sample", seed, n_pos, n_neg))
        return {"sample_id": "s42", "n_pos": min(n_pos, 3), "n_neg": 0, "strata": ["csrf|cheap"]}

    def next_item(store, sample_id, rater):
        calls.append(("next", sample_id, rater))
        return {"cluster_key": "k" * 32, "cwe_claim": "CWE-352", "remaining": 2,
                "code_lines": [{"n": 10, "kind": "flag", "text": "http.csrf().disable();"}]}

    def verdict(store, sample_id, rater, cluster_key, verdict, note):
        calls.append(("verdict", sample_id, rater, cluster_key, verdict, note))
        return {"ok": True, "remaining": 1}

    def close(store, sample_id, raters=None):
        calls.append(("close", sample_id, raters))
        return {"precision": {"tp": 2, "fp": 1, "unclear": 0, "n": 3, "point": 0.667, "ci_low": 0.21, "ci_high": 0.94},
                "kappa_raters": 0.5, "disagreements": [{"cluster_key": "k" * 32}]}

    mod.sample, mod.next_item, mod.verdict, mod.close = sample, next_item, verdict, close
    monkeypatch.setitem(sys.modules, "orchestrator.review", mod)
    return calls


def test_review_subcommands_call_module(orch_env, scratch_db, fake_review, capsys):
    from orchestrator import cli
    db = str(scratch_db)
    assert cli.main(["review", "--db", db, "sample", "--seed", "7", "--n-pos", "5", "--n-neg", "2", "--json"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["sample_id"] == "s42" and fake_review[-1] == ("sample", 7, 5, 2)
    assert cli.main(["review", "--db", db, "next", "--sample-id", "s42", "--rater", "a"]) == 0
    txt = capsys.readouterr().out
    assert "CWE-352" in txt and "csrf().disable" in txt and fake_review[-1] == ("next", "s42", "a")
    assert cli.main(["review", "--db", db, "verdict", "--sample-id", "s42", "--rater", "a",
                     "--cluster-key", "k" * 32, "--verdict", "TP", "--note", "rõ"]) == 0
    assert fake_review[-1] == ("verdict", "s42", "a", "k" * 32, "TP", "rõ")
    assert cli.main(["review", "--db", db, "close", "--sample-id", "s42", "--raters", "a,b", "--json"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["precision"]["n"] == 3 and fake_review[-1] == ("close", "s42", ["a", "b"])
    # verdict sai -> argparse -> exit 1 ; DB không tồn tại -> exit 1
    assert cli.main(["review", "--db", db, "verdict", "--sample-id", "s", "--rater", "a",
                     "--cluster-key", "k", "--verdict", "MAYBE"]) == 1
    assert cli.main(["review", "--db", str(scratch_db.parent / "nope.sqlite"), "sample"]) == 1
    # progress review start/done
    from orchestrator import progress
    ev = progress.read(os.environ["ORCH_PROGRESS_FILE"])
    assert [e["event"] for e in ev if e["phase"] == "review"][:2] == ["start", "done"]


def test_review_missing_module_is_arg_error(orch_env, scratch_db, monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 1 and fromlist and "review" in fromlist and (globals or {}).get("__name__") == "orchestrator.cli":
            raise ImportError("no review")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setitem(sys.modules, "orchestrator.review", None)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    from orchestrator import cli
    assert cli.main(["review", "--db", str(scratch_db), "sample"]) == 1


# ----------------------------------------------------------------------------- batch
def _mk_profiles(tmp_path, n):
    from orchestrator import profile as prof
    paths = []
    for i in range(n):
        p = prof.default_profile("https://github.com/o/r", "main")
        p["paths"] = {"db": str(tmp_path / f"d{i}.sqlite"), "export": str(tmp_path / f"e{i}"), "work": str(tmp_path / "w")}
        f = tmp_path / f"p{i}.json"
        prof.save(p, f)
        paths.append(f)
    return paths


def test_batch_runs_sequentially_and_honors_stop_file(orch_env, tmp_path):
    from orchestrator import batch
    paths = _mk_profiles(tmp_path, 4)
    q = tmp_path / "Q.json"
    q.write_text(json.dumps([p.name for p in paths]), encoding="utf-8")       # đường dẫn tương đối
    seen: list[tuple] = []
    stop = batch.default_stop_file(q)

    def runner(argv, env, log_path):
        seen.append((argv[-1], env["ORCH_RUN_ID"]))
        assert argv[1:5] == ["-m", "orchestrator.cli", "pipeline", "--profile"]
        assert "src" in env["PYTHONPATH"] and env["PYTHONIOENCODING"] == "utf-8"
        if len(seen) == 1:
            return 2                                   # profile 0 lỗi -> failed, vẫn chạy tiếp
        if len(seen) == 2:
            stop.write_text("stop", encoding="utf-8")  # stop-file xuất hiện sau profile 1
        return 0

    st = batch.run(q, runner=runner, batch_id="b1")
    assert [s[0] for s in seen] == [str(p) for p in paths[:2]]                 # tuần tự, dừng sau cái thứ 2
    assert [s[1] for s in seen] == ["b1-0", "b1-1"]
    assert [i["status"] for i in st["items"]] == ["failed", "done", "stopped", "stopped"]
    assert st["status"] == "stopped" and st["exit_code"] == 3
    state = json.loads(batch.default_state_path(q).read_text(encoding="utf-8"))
    assert state["batch_id"] == "b1" and state["items"][0]["rc"] == 2 and state["counts"]["done"] == 1


def test_batch_run_child_stop_code_and_stop_on_error(orch_env, tmp_path):
    from orchestrator import batch, cli
    paths = _mk_profiles(tmp_path, 3)
    q = tmp_path / "Q.json"
    q.write_text(json.dumps({"profiles": [str(p) for p in paths], "stop_on_error": True}), encoding="utf-8")
    st = batch.run(q, runner=lambda a, e, l: 2, batch_id="b2")
    assert [i["status"] for i in st["items"]] == ["failed", "skipped", "skipped"] and st["exit_code"] == 3
    st = batch.run(q, runner=lambda a, e, l: 3, batch_id="b3")               # run con trả 3 -> dừng hàng đợi
    assert st["items"][0]["status"] == "stopped" and st["items"][1]["status"] == "skipped"
    st = batch.run(q, runner=lambda a, e, l: 0, batch_id="b4")
    assert st["status"] == "done" and st["exit_code"] == 0 and st["counts"]["done"] == 3
    # CLI: queue hỏng -> exit 1 ; thiếu profile -> exit 1
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    assert cli.main(["batch", "--queue", str(bad)]) == 1
    bad.write_text(json.dumps(["khong_co.json"]), encoding="utf-8")
    assert cli.main(["batch", "--queue", str(bad)]) == 1
    assert cli.main(["batch", "--queue", str(tmp_path / "none.json")]) == 1


# ----------------------------------------------------------------------------- diagnostics
def test_diagnostics_zip_contents_and_redaction(orch_env, scratch_db, tmp_path, fake_docker, monkeypatch):
    from orchestrator import diagnostics, profile as prof
    work = tmp_path / "work"
    rdir = work / "run-9"
    rdir.mkdir(parents=True)
    tok = "ghp_SECRETTOKEN123456"
    monkeypatch.setenv("GITHUB_TOKEN", tok)
    monkeypatch.setenv("MY_PAT", "patvalue999")
    monkeypatch.setenv("ORCH_SONAR_ADMIN_PW", "Orch_2026!")
    (rdir / "run.log").write_text(f"start\ncloning https://x:{tok}@github.com/o/r\nmật khẩu Orch_2026! đã đặt\n", encoding="utf-8")
    (rdir / "progress.jsonl").write_text('{"phase":"scan","event":"start"}\n', encoding="utf-8")
    p = prof.default_profile("https://github.com/o/r", "main")
    p["paths"] = {"db": str(scratch_db), "export": str(tmp_path / "e"), "work": str(work)}
    pf = tmp_path / "prof.json"
    prof.save(p, pf)
    (rdir / "meta.json").write_text(json.dumps({"run_id": "run-9", "profile": str(pf), "pid": 1}), encoding="utf-8")
    (rdir / "preflight.json").write_text('{"ready": true}', encoding="utf-8")
    fake_docker.responses.append((lambda c: "version" in c, (0, "Docker version 27.0", "")))
    fake_docker.responses.append((lambda c: "info" in c, (0, "MemTotal: 8GB", "")))
    fake_docker.responses.append((lambda c: "ps" in c, (0, "CONTAINER ID\nabc orch-sonar", "")))

    out = tmp_path / "diag" / "run-9.zip"
    m = diagnostics.collect("run-9", out, work=work)
    assert out.exists() and m["bytes"] > 0 and not m["missing"] or set(m["missing"]) <= {"pid", "stop"}
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        assert {"run.log", "progress.jsonl", "meta.json", "profile.json", "run_meta.json", "kappa.json",
                "docker_info.txt", "docker_version.txt", "docker_ps.txt", "preflight.json", "env.json",
                "system.json", "manifest.json"} <= names
        log = zf.read("run.log").decode("utf-8")
        assert tok not in log and "***@github.com" in log and "Orch_2026!" not in log
        env = json.loads(zf.read("env.json"))
        assert env["ORCH_SONAR_ADMIN_PW"] == "***" and env["ORCH_RUN_ID"] == "test-run"
        assert "GITHUB_TOKEN" not in env or env["GITHUB_TOKEN"] == "***"
        rm = json.loads(zf.read("run_meta.json"))
        assert rm["rows"] and rm["rows"][0]["repo"].startswith("https://github.com/FudanSELab")
        ps = zf.read("docker_ps.txt").decode("utf-8")
        assert "label=orch.run=run-9" in ps and "orch-sonar" in ps
        man = json.loads(zf.read("manifest.json"))
        assert {"GITHUB_TOKEN", "MY_PAT", "ORCH_SONAR_ADMIN_PW"} <= set(man["redacted_keys"])
    assert any("--filter" in c and "label=orch.run=run-9" in c for c in fake_docker.calls)

    from orchestrator import cli
    out2 = tmp_path / "d2.zip"
    assert cli.main(["diagnostics", "--run", "run-9", "--out", str(out2), "--work", str(work), "--json"]) == 0
    assert out2.exists()
    assert cli.main(["diagnostics", "--run", "run-9", "--out", str(tmp_path / "x.txt")]) == 1
    # run không tồn tại vẫn gói được (thiếu ghi vào manifest), docker tắt vẫn ok
    m2 = diagnostics.collect("no-run", tmp_path / "d3.zip", work=work)
    assert "run.log" in m2["missing"] and (tmp_path / "d3.zip").exists()


def test_redact_helpers():
    from orchestrator import diagnostics as d
    assert d.is_secret_key("GITHUB_TOKEN") and d.is_secret_key("PAT") and d.is_secret_key("ORCH_SONAR_ADMIN_PW")
    assert d.is_secret_key("npm_config_authToken") and not d.is_secret_key("ORCH_SQLITE") and not d.is_secret_key("PATH")
    env = {"GITHUB_TOKEN": "abcdefgh", "SHORT_TOKEN": "ab", "ORCH_SQLITE": "x.sqlite"}
    assert d.secret_values(env) == ["abcdefgh"]                       # giá trị quá ngắn không che (tránh che nhầm)
    assert d.redact_text("tok=abcdefgh ok", ["abcdefgh"]) == "tok=*** ok"
    r = d.redact_env(env)
    assert r == {"ORCH_SQLITE": "x.sqlite"}                            # GITHUB_TOKEN không thuộc prefix giữ


# ----------------------------------------------------------------------------- _m2_cache / ORCH_M2_VOLUME
def test_m2_cache_bind_mount_default(orch_env, tmp_path, monkeypatch):
    from orchestrator import config
    from orchestrator.tools_expensive import build
    monkeypatch.delenv("ORCH_M2_VOLUME", raising=False)
    config.reload()
    m = build._m2_cache()
    assert isinstance(m, Path) and m == config.WORK_DIR / ".m2cache" and m.exists()
    monkeypatch.setenv("ORCH_M2_VOLUME", "0")
    config.reload()
    assert build._m2_cache() == config.WORK_DIR / ".m2cache"


def test_m2_cache_named_volume(orch_env, fake_docker, monkeypatch):
    from orchestrator import config
    from orchestrator.tools_expensive import build
    build._M2_VOLUME_READY.clear()
    monkeypatch.setenv("ORCH_M2_VOLUME", "1")
    config.reload()
    fake_docker.responses.append((lambda c: "inspect" in c, (1, "", "Error: No such volume")))
    assert build._m2_cache() == "secjit-m2"
    cmds = [" ".join(c) for c in fake_docker.calls]
    assert any("volume inspect secjit-m2" in c for c in cmds) and any("volume create" in c and "secjit-m2" in c for c in cmds)
    n = len(fake_docker.calls)
    assert build._m2_cache() == "secjit-m2" and len(fake_docker.calls) == n          # cache: không gọi docker lại
    assert f"{build._m2_cache()}:/m2" == "secjit-m2:/m2"
    # tên tuỳ ý
    build._M2_VOLUME_READY.clear()
    monkeypatch.setenv("ORCH_M2_VOLUME", "my-m2")
    config.reload()
    assert build._m2_cache() == "my-m2"
    # tạo volume thất bại -> cảnh báo + fallback bind mount
    build._M2_VOLUME_READY.clear()
    fake_docker.responses.insert(0, (lambda c: "create" in c, (1, "", "daemon down")))
    monkeypatch.setenv("ORCH_M2_VOLUME", "1")
    config.reload()
    assert build._m2_cache() == config.WORK_DIR / ".m2cache"


# ----------------------------------------------------------------------------- ORCH_DOCKER_BIN
def test_docker_run_uses_orch_docker_bin(orch_env, fake_docker, monkeypatch):
    from orchestrator.tools import base
    monkeypatch.delenv("ORCH_DOCKER_BIN", raising=False)
    base.docker_run(["version"])
    assert fake_docker.calls[-1][0] == "docker"
    monkeypatch.setenv("ORCH_DOCKER_BIN", "C:/Tools/podman.exe")
    base.docker_run(["run", "--rm", "alpine", "true"])
    assert fake_docker.calls[-1][0] == "C:/Tools/podman.exe" and "orch.run=test-run" in " ".join(fake_docker.calls[-1])
    from orchestrator import config
    config.reload()
    assert config.DOCKER_BIN == "C:/Tools/podman.exe" and "ORCH_DOCKER_BIN" in config.effective_env()


# ----------------------------------------------------------------------------- clean --items m2volume
def test_clean_m2volume_dry_run_and_rm(orch_env, fake_docker, tmp_path):
    from orchestrator import cli, control
    fake_docker.responses.append((lambda c: c[1:3] == ["volume", "inspect"], (0, "[{}]", "")))
    fake_docker.responses.append((lambda c: c[1:3] == ["system", "df"],
                                  (0, "VOLUME NAME   LINKS   SIZE\nother-vol     1       10MB\nsecjit-m2     0       1.5GB\n", "")))
    assert control.parse_docker_size("1.5GB") == 1_500_000_000 and control.parse_docker_size("2MiB") == 2 * 2**20
    assert control.parse_docker_size("n/a") is None
    items = control.parse_items("m2volume")
    plan = control.clean_plan("https://github.com/o/r", items, work=tmp_path)
    assert plan["would_delete"] == [{"path": "docker volume secjit-m2", "bytes": 1_500_000_000,
                                     "item": "m2volume", "volume": "secjit-m2"}]
    n = len(fake_docker.calls)
    res = control.clean_apply(plan)
    assert res["deleted"] == plan["would_delete"] and not res["errors"]
    assert fake_docker.calls[n] == ["docker", "volume", "rm", "secjit-m2"]
    # volume không tồn tại -> không có gì để xoá, không lỗi
    fake_docker.responses.insert(0, (lambda c: c[1:3] == ["volume", "inspect"], (1, "", "no such volume")))
    assert control.clean_plan("https://github.com/o/r", items, work=tmp_path)["would_delete"] == []
    # rm thất bại (đang được dùng) -> errors, exit 2
    fake_docker.responses.pop(0)
    fake_docker.responses.insert(0, (lambda c: c[1:3] == ["volume", "rm"], (1, "", "volume is in use")))
    assert cli.main(["clean", "https://github.com/o/r", "--items", "m2volume", "--json"]) == 2
    assert cli.main(["clean", "https://github.com/o/r", "--items", "m2volume", "--dry-run", "--json"]) == 0
    with pytest.raises(ValueError):
        control.parse_items("m2volume:x")


# ----------------------------------------------------------------------------- verify subcommand
def test_verify_subcommand_runs_verify_run(orch_env, scratch_db, tmp_path, capsys):
    from orchestrator import cli
    rc = cli.main(["verify", "--db", str(scratch_db), "--json"])
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert {"db", "checks", "n_fail", "pass"} <= set(out) and out["checks"]
    assert rc == (0 if out["pass"] else 1)
    assert cli.main(["verify", "--db", str(tmp_path / "nope.sqlite")]) == 1
    assert cli.main(["verify", "--db", str(scratch_db), "--export", str(tmp_path / "no_export")]) == 1


# ----------------------------------------------------------------------------- stats precision từ review.summary
def test_stats_precision_prefers_review_summary(orch_env, scratch_db, monkeypatch):
    from orchestrator import review, stats
    monkeypatch.setattr(review, "summary", lambda store: [
        {"sample_id": "s1", "precision": {"tp": 5, "fp": 5, "unclear": 0, "n": 10, "point": 0.5, "ci_low": 0.2, "ci_high": 0.8},
         "neg_precision": None, "kappa_raters": 0.4},
        {"sample_id": "s2", "precision": {"tp": 9, "fp": 1, "unclear": 1, "point": 0.9, "ci_low": 0.6, "ci_high": 0.98},
         "neg_precision": {"point": 1.0}, "kappa_raters": 0.7}])
    ov = stats.overview(scratch_db)
    p = ov["precision"]
    assert p["sample_id"] == "s2" and p["n"] == 10 and p["tp"] == 9 and p["kappa_raters"] == 0.7
    assert p["source"] == "review.summary" and any("kiểm tay" in s for s in ov["limits"])
    monkeypatch.setattr(review, "summary", lambda store: [])
    assert stats.overview(scratch_db)["precision"] is None          # không mẫu -> fallback gold_review (không có) -> None


# ----------------------------------------------------------------------------- rescan
class _RescanTool:
    name = "semgrep"
    calls: list = []

    def scan(self, clone, cid, repo, changed, raw_out=None):
        _RescanTool.calls.append((self.name, cid))
        raw_out.append(("json", "[]"))
        return []


def _tool(name):
    return type(f"T_{name}", (_RescanTool,), {"name": name})


def _patch_rescan(monkeypatch, tmp_path, cid):
    from orchestrator import cli, enumerate_commits as enm
    import orchestrator.repo_pool as rp
    from orchestrator.enumerate_commits import CommitInfo
    _RescanTool.calls.clear()
    monkeypatch.setattr(cli, "cheap_tool_classes", lambda: {n: _tool(n) for n in cli.config.CHEAP_TOOLS_ALL})
    monkeypatch.setattr(enm, "clone_or_update", lambda repo, dest=None, fetch=True: tmp_path)
    monkeypatch.setattr(enm, "verify_sha", lambda repo_dir, sha, what="sha": cid if cid.startswith(sha) else (_ for _ in ()).throw(enm.ScopeError(f"{what}={sha} không tồn tại")))
    monkeypatch.setattr(enm, "get_commit_info", lambda repo_dir, c: CommitInfo(
        commit_id=c, parent_commit=None, author_date="2022-11-01", message="m", is_merge=False, changed_files=["A.java"]))
    monkeypatch.setattr(rp, "RepoPool", _FakePoolW2)
    (tmp_path / "A.java").write_text("class A {}", encoding="utf-8")   # file đổi phải tồn tại trong clone
    _FakePoolW2.root = tmp_path
    return cli


class _FakePoolW2:
    root = Path(".")

    def __init__(self, main_repo, size, **kw):
        pass

    def acquire(self):
        return _FakePoolW2.root

    def checkout(self, clone, sha):
        pass

    def release(self, clone):
        pass

    def cleanup(self):
        pass


def test_rescan_defaults_to_failed_tools_and_clears_errors(orch_env, scratch_db, fake_docker, monkeypatch, tmp_path, capsys):
    import sqlite3
    cid = "313886e99befb94be6cd45f085c98e0019f59829"
    cli = _patch_rescan(monkeypatch, tmp_path, cid)
    from orchestrator.storage.sqlite_store import SQLiteStore
    SQLiteStore(scratch_db).close()
    conn = sqlite3.connect(scratch_db)
    n_raw_before = conn.execute("SELECT COUNT(*) FROM raw_findings WHERE commit_id=? AND tier='cheap'", [cid]).fetchone()[0]
    conn.execute("INSERT INTO scan_tool_errors (commit_id,tool,tier,kind,msg,at) VALUES (?,?,?,?,?,'')",
                 [cid, "semgrep", "cheap", "tool_timeout", "x"])
    conn.execute("INSERT INTO scan_tool_errors (commit_id,tool,tier,kind,msg,at) VALUES (?,?,?,?,?,'')",
                 [cid, "horusec", "cheap", "tool_error", "y"])
    conn.execute("INSERT INTO raw_output (commit_id,tool,tier,fmt,content,created_at) VALUES (?,?,?,?,?,'')",
                 [cid, "semgrep", "cheap", "error", '{"kind":"tool_timeout"}'])
    conn.commit(); conn.close()
    rc = cli.main(["rescan", "--db", str(scratch_db), "--commit", cid[:10], "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    r = out["results"][0]
    assert r["commit"] == cid and r["tools"] == ["horusec", "semgrep"] and r["reason"] == "tool_errors"
    assert r["errors_cleared"] == 2 and sorted(c[0] for c in _RescanTool.calls) == ["horusec", "semgrep"]
    assert out["repo"].startswith("https://github.com/FudanSELab")
    conn = sqlite3.connect(scratch_db)
    assert conn.execute("SELECT COUNT(*) FROM scan_tool_errors WHERE commit_id=?", [cid]).fetchone()[0] == 0
    # raw của tool KHÁC (bearer) giữ nguyên; raw error semgrep đã xoá
    assert conn.execute("SELECT COUNT(*) FROM raw_findings WHERE commit_id=? AND tool='bearer'", [cid]).fetchone()[0] \
        == n_raw_before
    assert conn.execute("SELECT COUNT(*) FROM raw_output WHERE commit_id=? AND fmt='error'", [cid]).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM scanned_files WHERE commit_id=?", [cid]).fetchone()[0] == 1
    assert conn.execute("SELECT 1 FROM scan_done WHERE commit_id=?", [cid]).fetchone()
    conn.close()


def test_rescan_explicit_tools_and_errors(orch_env, scratch_db, fake_docker, monkeypatch, tmp_path, capsys):
    cid = "313886e99befb94be6cd45f085c98e0019f59829"
    cli = _patch_rescan(monkeypatch, tmp_path, cid)
    assert cli.main(["rescan", "--db", str(scratch_db), "--commit", cid, "--tools", "gitleaks", "--json"]) == 0
    r = json.loads(capsys.readouterr().out.strip().splitlines()[-1])["results"][0]
    assert r["tools"] == ["gitleaks"] and r["reason"] == "explicit" and [c[0] for c in _RescanTool.calls] == ["gitleaks"]
    assert cli.main(["rescan", "--db", str(scratch_db), "--commit", "deadbeef"]) == 1          # SHA sai -> 1
    assert cli.main(["rescan", "--db", str(scratch_db), "--commit", cid, "--tools", "codeql"]) == 1
    assert cli.main(["rescan", "--db", str(tmp_path / "no.sqlite"), "--commit", cid]) == 1
    # không lỗi tool nào -> đủ 5 tool (reason=all); progress scan start/item/done
    _RescanTool.calls.clear()
    from orchestrator import progress
    assert cli.main(["rescan", "--db", str(scratch_db), "--commit", cid, "--json"]) == 0
    r = json.loads(capsys.readouterr().out.strip().splitlines()[-1])["results"][0]
    assert r["reason"] == "all" and len(r["tools"]) == 5
    ev = [e for e in progress.read(os.environ["ORCH_PROGRESS_FILE"]) if e.get("msg", "").startswith("rescan")]
    assert [e["event"] for e in ev][-3:] == ["start", "item", "done"]


# ----------------------------------------------------------------------------- batch: ủy quyền runner.batch_runner
def test_batch_delegates_to_runner_when_available(orch_env, tmp_path, monkeypatch, capsys):
    from orchestrator import cli
    paths = _mk_profiles(tmp_path, 1)
    q = tmp_path / "Q.json"
    q.write_text(json.dumps([str(paths[0])]), encoding="utf-8")
    seen = {}
    fake = types.ModuleType("runner.batch_runner")

    def run_queue(queue_path, work_dir, python_exe=None, batch_id=None, stop_file=None, state_path=None, **kw):
        seen.update(queue=str(queue_path), work=str(work_dir), stop=stop_file, state=state_path)
        return {"batch_id": "b", "status": "done", "exit_code": 0, "counts": {"done": 1}, "items": [], "stop_file": "s"}

    fake.run_queue = run_queue
    monkeypatch.setitem(sys.modules, "runner.batch_runner", fake)
    assert cli.main(["batch", "--queue", str(q), "--work", str(tmp_path / "w"), "--json"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["mode"] == "runner" and seen["queue"] == str(q) and seen["work"] == str(tmp_path / "w")
    # --local -> đường cũ (subprocess) — mock runner cục bộ của batch.py
    from orchestrator import batch
    monkeypatch.setattr(batch, "_default_runner", lambda argv, env, log: 0)
    assert cli.main(["batch", "--queue", str(q), "--local", "--json"]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["mode"] == "local"
    # không import được runner -> fallback local
    monkeypatch.setitem(sys.modules, "runner.batch_runner", None)
    monkeypatch.setitem(sys.modules, "runner", None)
    assert cli.main(["batch", "--queue", str(q), "--json"]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["mode"] == "local"


# ----------------------------------------------------------------------------- compare --format md: bảng RESULTS.md
def test_compare_markdown_table_for_results(orch_env, tmp_path):
    from orchestrator import compare
    repo = "https://github.com/o/r"
    rows_a, rows_b = [], []
    for i in range(30):                                     # 30 cụm chỉ ở A -> bảng cắt 20 + dòng "còn 10"
        rows_a.append({"repo": repo, "commit_id": f"{i:040x}", "file_path": f"F{i}.java", "cwe_group": "csrf",
                       "s_line": 10 + i, "label": "silver"})
    common = {"repo": repo, "commit_id": "c" * 40, "file_path": "Common.java", "cwe_group": "crypto", "s_line": 5}
    rows_a.append({**common, "label": "gold"})
    rows_b.append({**common, "label": "silver"})
    da, dbb = tmp_path / "A", tmp_path / "B"
    da.mkdir(); dbb.mkdir()
    (da / "dataset.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows_a), encoding="utf-8")
    (dbb / "dataset.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows_b), encoding="utf-8")
    (da / "run_manifest.json").write_text(json.dumps({"tool_timeout": [f"{i:040x}" for i in range(5)],
                                                      "params_v1": {"line_window": 3}}), encoding="utf-8")
    (dbb / "run_manifest.json").write_text(json.dumps({"params_v1": {"line_window": 3}}), encoding="utf-8")
    res = compare.compare(da, dbb)
    assert len(res["diffs"]) == 31 and res["explained_by"]["tool_timeout"] == 5 and not res["ok"]
    assert res["diffs"][0]["reason"] == "unexplained"       # chưa giải thích xếp trước
    md = compare.to_markdown(res)
    lines = md.splitlines()
    assert lines[0].startswith("### Tái lập A ↔ B — **LỆCH**")
    assert "| same (cùng khoá, cùng nhãn) | 0 |" in md and "| only_a | 30 |" in md and "| label_changed | 1 |" in md
    assert "| lệch giải thích được (manifest) | 5 |" in md and "| lệch KHÔNG giải thích | **26** |" in md
    assert "| tool_timeout | 5 |" in md
    table = [l for l in lines if l.startswith("| ") and l.split("|")[1].strip().isdigit()]
    assert len(table) == 20 and "còn 11 cụm" in md
    assert any("label_changed" in l and "gold" in l and "silver" in l and "Common.java" in l for l in table)
    assert md.count("**KHÔNG giải thích**") == 20 and "CHƯA đạt" in md
    # khớp hoàn toàn -> kết luận ĐẠT, không có bảng cụm lệch
    ok = compare.compare(dbb, dbb)
    md2 = compare.to_markdown(ok)
    assert "**KHỚP**" in md2 and "ĐẠT tiêu chí" in md2 and "Cụm lệch" not in md2
    from orchestrator import cli
    assert cli.main(["compare", "--a", str(da), "--b", str(dbb), "--format", "md"]) == 1
