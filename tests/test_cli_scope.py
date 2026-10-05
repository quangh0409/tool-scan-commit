"""Test hợp đồng A2 cli-scope: profile -> argparse, to_shell quote, config.reload() + experiment,
compare, stats, estimate, control.reset_claims/clean/stop, phạm vi commit (git thật, repo tạm)."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _profile(tmp_path, **over) -> dict:
    from orchestrator import profile as prof
    p = prof.default_profile("https://github.com/FudanSELab/train-ticket", "master")
    p["paths"] = {"db": str(tmp_path / "it's db" / "dataset.sqlite"),
                  "export": str(tmp_path / "it's db" / "export"), "work": str(tmp_path / "work")}
    for k, v in over.items():
        if k == "scope":
            p["scope"].update(v)
        else:
            p[k] = v
    return p


SCOPES = [
    {"mode": "count", "max": 30},
    {"mode": "all", "max": 0},
    {"mode": "time", "since": "2024-01-01", "until": "2024-06-30", "max": 0},
    {"mode": "time", "since": "2024-01-01", "until": None, "max": 0},
    {"mode": "sha", "from_sha": "abc1234", "to_sha": "def5678", "max": 0},
    {"mode": "sha", "from_sha": None, "to_sha": "def5678", "max": 0},
]


# ----------------------------------------------------------------------------- 1. profile -> argparse
@pytest.mark.parametrize("scope", SCOPES)
def test_profile_to_cli_args_parses_for_every_scope_mode(orch_env, tmp_path, scope):
    from orchestrator import cli, profile as prof
    p = _profile(tmp_path, scope=scope, cheap_tools=["semgrep", "bearer"], expensive_tools=["sonar"])
    assert prof.validate(p) == []
    parser = cli.build_parser()
    args = parser.parse_args(prof.to_cli_args(p))
    assert args.cmd == "pipeline" and args.repo == p["repo"]
    assert args.tools == "semgrep,bearer" and args.expensive_tools == "sonar"
    if scope["mode"] == "time":
        assert args.since == scope["since"] and args.max == 0
    if scope["mode"] == "sha":
        assert args.to_sha == scope["to_sha"] and args.max == 0
    if scope["mode"] == "count":
        assert args.max == 30
    # mọi subcommand PROFILE_DRIVEN cũng phải parse được từ profile
    for cmd in cli.PROFILE_DRIVEN:
        ns = parser.parse_args(cli.profile_argv(p, cmd))
        assert ns.cmd == cmd


def test_apply_profile_sets_env_reloads_config_and_rebuilds_argv(orch_env, tmp_path, capsys):
    from orchestrator import cli, config, profile as prof
    p = _profile(tmp_path, scope={"mode": "time", "since": "2024-01-01", "max": 0},
                 workers={"scan": 2, "expensive": 1}, sonar_port=9100)
    f = tmp_path / "p.json"
    prof.save(p, f)
    pdata, argv = cli.apply_profile(["pipeline", "https://other/repo", "--max", "5", "--profile", str(f)])
    assert pdata["repo"] == p["repo"]
    assert argv[:2] == ["pipeline", p["repo"]] and "--since" in argv and "--profile" in argv
    assert "https://other/repo" not in argv and "5" not in argv
    assert "bỏ qua" in capsys.readouterr().err
    assert os.environ["ORCH_SQLITE"] == p["paths"]["db"]
    assert config.SQLITE_PATH == Path(p["paths"]["db"])
    assert config.SCAN_WORKERS == 2 and config.SONAR_HOST_PORT == 9100
    args = cli.build_parser().parse_args(argv)
    assert args.since == "2024-01-01" and args.max == 0
    # lệnh không PROFILE_DRIVEN giữ argv, chỉ áp env
    pdata2, argv2 = cli.apply_profile(["estimate", "--profile", str(f), "--json"])
    assert pdata2 and argv2 == ["estimate", "--profile", str(f), "--json"]


def test_profile_error_exit_1(orch_env, tmp_path):
    from orchestrator import cli
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": 1, "repo": "", "scope": {"mode": "count", "max": 0}}), encoding="utf-8")
    assert cli.main(["pipeline", "--profile", str(bad)]) == 1
    assert cli.main(["pipeline", "https://x/y", "--max", "-3"]) == 1          # --max < 0
    assert cli.main(["pipeline", "https://x/y", "--since", "31/12/2024"]) == 1  # ngày sai ISO
    assert cli.main(["pipeline", "https://x/y", "--tools", "nmap"]) == 1       # tool lạ
    assert cli.main(["nosuchcmd"]) == 1                                       # argparse -> 1, không 2


# ----------------------------------------------------------------------------- 2. to_shell quote
@pytest.mark.parametrize("shell", ["powershell", "bash"])
def test_to_shell_quotes_single_quote_paths(orch_env, tmp_path, shell):
    from orchestrator import profile as prof
    p = _profile(tmp_path)
    cmd = prof.to_shell(p, shell)
    db = p["paths"]["db"]
    assert "it's" in db
    if shell == "powershell":
        assert "'" + db.replace("'", "''") + "'" in cmd
        assert "$env:ORCH_SQLITE=" in cmd and "python -m orchestrator.cli 'pipeline'" in cmd
    else:
        assert "'" + db.replace("'", "'\"'\"'") + "'" in cmd
        assert "ORCH_SQLITE=" in cmd and "PYTHONPATH=src python -m orchestrator.cli" in cmd
        # bash: lệnh phải tách lại đúng từng token
        import shlex
        toks = shlex.split(cmd)
        assert any(t == f"ORCH_SQLITE={db}" for t in toks)


# ----------------------------------------------------------------------------- 3. config.reload + experiment
def test_config_reload_line_window_only_when_experiment(orch_env, monkeypatch, capsys):
    from orchestrator import config
    monkeypatch.setenv("ORCH_LINE_WINDOW", "7")
    monkeypatch.delenv("ORCH_EXPERIMENT", raising=False)
    config._WARNED.clear()
    config.reload()
    assert config.LINE_WINDOW == 3 and config.EXPERIMENT == 0
    assert "ORCH_LINE_WINDOW=7 bị BỎ QUA" in capsys.readouterr().err
    monkeypatch.setenv("ORCH_EXPERIMENT", "1")
    monkeypatch.setenv("ORCH_EXPERIMENT_REASON", "thử nới window theo RULE §9")
    config.reload()
    assert config.LINE_WINDOW == 7 and config.experiment_info() == {"enabled": True,
                                                                   "reason": "thử nới window theo RULE §9"}
    assert config.params_v1()["line_window"] == 7
    # các env mới có mặt
    monkeypatch.setenv("ORCH_CHEAP_TOOLS", "semgrep, bearer")
    monkeypatch.setenv("SECJIT_APP_VERSION", "1.2.3")
    monkeypatch.setenv("ORCH_M2_VOLUME", "secjit-m2")
    config.reload()
    assert config.CHEAP_TOOLS == ["semgrep", "bearer"] and config.APP_VERSION == "1.2.3"
    assert config.M2_VOLUME == "secjit-m2" and config.RUN_ID == "test-run"
    assert str(config.PROGRESS_FILE).endswith("progress.jsonl") and str(config.STOP_FILE).endswith("stop")
    env = config.effective_env()
    assert "ORCH_CHEAP_TOOLS" in env and "ORCH_SONAR_ADMIN_PW" not in env


def test_parse_tools_validation_and_warning(orch_env, capsys):
    from orchestrator import cli
    assert cli.parse_tools(None, cli.config.CHEAP_TOOLS_ALL, "--tools") is None
    assert cli.parse_tools("semgrep,bearer,semgrep", cli.config.CHEAP_TOOLS_ALL, "--tools") == ["semgrep", "bearer"]
    assert "MẪU SỐ" in capsys.readouterr().err
    with pytest.raises(cli.CliError):
        cli.parse_tools("codeql", cli.config.CHEAP_TOOLS_ALL, "--tools")
    with pytest.raises(cli.CliError):
        cli.parse_tools(" , ", cli.config.CHEAP_TOOLS_ALL, "--tools")


def test_expensive_tools_warning_only_when_effective_tool_dropped(orch_env, capsys):
    """Run A thật: codeql:false + expensive_tools=[findsecbugs,sonar] KHÔNG được cảnh báo 'bỏ tool codeql'."""
    import argparse
    from orchestrator import cli
    ns = argparse.Namespace(expensive_tools="findsecbugs,sonar", tools=None, codeql=0)
    assert cli._expensive_tool_names(ns) == ["findsecbugs", "sonar"]
    assert capsys.readouterr().err == ""
    ns.codeql = None                                          # không nói gì về codeql -> vẫn không cảnh báo
    cli._expensive_tool_names(ns)
    assert capsys.readouterr().err == ""
    ns.codeql = 1                                             # bật codeql mà không liệt kê -> cảnh báo
    cli._expensive_tool_names(ns)
    assert "bỏ tool ['codeql']" in capsys.readouterr().err
    ns.codeql = 0
    ns.expensive_tools = "sonar"                              # thiếu findsecbugs -> cảnh báo đúng
    cli._expensive_tool_names(ns)
    assert "bỏ tool ['findsecbugs']" in capsys.readouterr().err
    # pipeline: profile mặc định (codeql False, 2 tool đắt) -> stderr sạch
    from orchestrator import profile as prof
    p = prof.default_profile("https://github.com/o/r", "main")
    p["paths"]["db"] = "x.sqlite"
    args = cli.build_parser().parse_args(prof.to_cli_args(p))
    cli.parse_tools(args.expensive_tools, cli.config.EXPENSIVE_TOOLS_ALL, "--expensive-tools",
                    baseline=cli.expensive_baseline(args.codeql))
    assert capsys.readouterr().err == ""
    assert cli.expensive_baseline(1) == ["findsecbugs", "sonar", "codeql"]


def test_resolve_scope_forces_max_zero_with_warning(orch_env, capsys):
    import argparse
    from orchestrator import cli
    ns = argparse.Namespace(max=None, since="2024-01-01", until=None, from_sha=None, to_sha=None)
    sc = cli.resolve_scope(ns)
    assert ns.max == 0 and sc["mode"] == "time" and sc["date_field"] == "committer"
    assert "ép --max 0" in capsys.readouterr().err
    ns2 = argparse.Namespace(max=None, since=None, until=None, from_sha=None, to_sha=None)
    assert cli.resolve_scope(ns2)["mode"] == "count" and ns2.max == cli.config.PILOT_MAX_COMMITS
    with pytest.raises(cli.CliError):
        cli.resolve_scope(argparse.Namespace(max=0, since="2024-06-01", until="2024-01-01", from_sha=None, to_sha=None))


# ----------------------------------------------------------------------------- phạm vi commit trên git thật
def _git(cwd, *a, env=None):
    e = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
         "GIT_COMMITTER_EMAIL": "t@x", **(env or {})}
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True, env=e).stdout.strip()


@pytest.fixture
def tiny_repo(tmp_path):
    if not __import__("shutil").which("git"):
        pytest.skip("không có git")
    r = tmp_path / "tiny"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    shas = []
    for i, date in enumerate(("2024-01-10T10:00:00", "2024-03-10T10:00:00", "2024-05-10T10:00:00")):
        (r / f"f{i}.java").write_text(f"class F{i} {{}}\n", encoding="utf-8")
        _git(r, "add", ".")
        _git(r, "commit", "-q", "-m", f"c{i}", env={"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date})
        shas.append(_git(r, "rev-parse", "HEAD"))
    return r, shas          # shas cũ -> mới


def test_list_commits_scope_time_and_sha(orch_env, tiny_repo):
    from orchestrator import enumerate_commits as enm
    r, (c0, c1, c2) = tiny_repo
    assert enm.list_commits(r) == [c2, c1, c0]
    assert enm.list_commits(r, 2) == [c2, c1]
    assert enm.list_commits(r, 0, since="2024-02-01", until="2024-04-01") == [c1]
    assert enm.list_commits(r, 0, since="2024-02-01") == [c2, c1]
    assert enm.list_commits(r, 0, from_sha=c0, to_sha=c2) == [c2, c1]        # from loại, to gồm
    assert enm.list_commits(r, 0, from_sha=c0[:7]) == [c2, c1]
    assert enm.list_commits(r, 0, to_sha=c1) == [c1, c0]
    with pytest.raises(enm.ScopeError, match="không tồn tại"):
        enm.list_commits(r, 0, from_sha="deadbeef")
    with pytest.raises(enm.ScopeError, match="tổ tiên"):
        enm.list_commits(r, 0, from_sha=c2, to_sha=c0)                       # ngược chiều
    with pytest.raises(enm.ScopeError, match="since"):
        enm.list_commits(r, 0, since="2024-06-01", until="2024-01-01")
    assert enm.scope_dict(0, None, None, c0, c2)["mode"] == "sha"


# ----------------------------------------------------------------------------- 4. compare
def _export(d: Path, rows: list[dict], manifest: dict | None = None):
    d.mkdir(parents=True)
    with open(d / "dataset.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    if manifest is not None:
        (d / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_compare_two_fake_exports(orch_env, tmp_path):
    from orchestrator import compare, keys
    repo = "https://github.com/o/r"
    base = {"repo": repo, "commit_id": "a" * 40, "file_path": "src/A.java", "cwe_group": "csrf", "s_line": 10}
    k1 = keys.cluster_key(repo, "a" * 40, "src/A.java", "csrf", 10)
    rows_a = [{**base, "cluster_key": k1, "label": "silver"},
              {**base, "commit_id": "b" * 40, "s_line": 40, "label": "gold"},                   # chỉ A, commit b
              {**base, "commit_id": "c" * 40, "s_line": 70, "label": "silver"}]                 # chỉ A, commit c
    rows_b = [{**base, "cluster_key": k1, "label": "gold"},                                     # label đổi
              {**base, "commit_id": "d" * 40, "s_line": 5, "label": "candidate"}]               # chỉ B, commit d
    _export(tmp_path / "A", rows_a, {"tool_timeout": ["b" * 40], "infra_error": [], "skipped": [],
                                     "params_v1": {"line_window": 3}})
    _export(tmp_path / "B", rows_b, {"tool_timeout": [], "infra_error": [{"commit": "d" * 40}],
                                     "skipped": ["a" * 40], "params_v1": {"line_window": 3}})
    res = compare.compare(tmp_path / "A", tmp_path / "B")
    assert res["same"] == 0 and len(res["only_a"]) == 2 and len(res["only_b"]) == 1
    assert len(res["label_changed"]) == 1 and res["label_changed"][0]["a"] == "silver"
    assert res["explained_by"] == {"tool_timeout": 1, "infra_error": 1, "skipped": 1, "build_failed": 0}
    assert [u["commit"] for u in res["unexplained"]] == ["c" * 40] and res["ok"] is False
    md = compare.to_markdown(res)
    assert "LỆCH" in md and "cccccccc" in md
    # B so với chính nó -> khớp, exit 0
    from orchestrator import cli
    assert cli.main(["compare", "--a", str(tmp_path / "B"), "--b", str(tmp_path / "B"), "--json"]) == 0
    assert cli.main(["compare", "--a", str(tmp_path / "A"), "--b", str(tmp_path / "B")]) == 1


def test_compare_db_vs_export_same_db(orch_env, scratch_db, tmp_path):
    from orchestrator import compare, keys
    conn = sqlite3.connect(scratch_db)
    rows = [{"repo": r[0], "commit_id": r[1], "file_path": r[2], "cwe_group": r[3], "s_line": r[4], "label": r[5]}
            for r in conn.execute("SELECT repo,commit_id,file_path,cwe_group,s_line,label FROM findings")]
    conn.close()
    for r in rows:
        r["cluster_key"] = keys.cluster_key(r["repo"], r["commit_id"], r["file_path"], r["cwe_group"], r["s_line"])
    _export(tmp_path / "E", rows)
    res = compare.compare(scratch_db, tmp_path / "E")
    assert res["ok"] and res["same"] == len({r["cluster_key"] for r in rows}) and res["a"]["kind"] == "db"


# ----------------------------------------------------------------------------- 5. stats
def test_stats_overview_has_all_keys(orch_env, scratch_db, tmp_path):
    from orchestrator import stats
    ov = stats.overview(scratch_db)
    fixture = json.loads((ROOT / "gui" / "fixtures" / "overview.json").read_text(encoding="utf-8"))
    assert set(fixture) <= set(ov)
    assert set(fixture["funnel"]) == set(ov["funnel"]) and set(fixture["labels"]) == set(ov["labels"])
    assert set(fixture["kappa"]) <= set(ov["kappa"]) and set(fixture["coverage"]) == set(ov["coverage"])
    assert ov["labels"]["candidate"] == 17 and ov["funnel"]["buggy"] == 1
    assert ov["coverage"]["one"] == 17
    assert len(ov["limits"]) >= 5 and all(isinstance(s, str) and s for s in ov["limits"])
    assert ov["params_v1"]["line_window"] == 3 and ov["experiment"] is None and ov["precision"] is None
    assert any(p["group"] == "horusec|semgrep" for p in ov["kappa"]["pairs"])
    # xuất 3 format
    files_csv = stats.write(ov, tmp_path / "csv", "csv")
    assert {Path(f).name for f in files_csv} >= {"funnel.csv", "labels.csv", "kappa.csv", "limits.csv"}
    tex = stats.render(ov, "latex")
    assert "\\begin{tabular}" in tex and "cwe\\_group" in tex
    files_json = stats.write(ov, tmp_path / "j", "json")
    assert json.loads(Path(files_json[0]).read_text(encoding="utf-8"))["labels"] == ov["labels"]
    # DB không bị ghi (mode=ro) — mtime giữ nguyên
    from orchestrator import cli
    m0 = scratch_db.stat().st_mtime_ns
    assert cli.main(["stats", "--db", str(scratch_db), "--format", "csv", "--out", str(tmp_path / "o"), "--json"]) == 0
    assert scratch_db.stat().st_mtime_ns == m0


def test_stats_precision_and_kappa_table(orch_env, scratch_db):
    from orchestrator import stats
    conn = sqlite3.connect(scratch_db)
    conn.executescript("""
    CREATE TABLE kappa (run_id TEXT, scope TEXT, grp TEXT, value REAL, n INTEGER, computed_at TEXT);
    INSERT INTO kappa VALUES ('r1','total','',-0.36,100,''),('r1','pair','semgrep|sonar',0.08,18,'');
    CREATE TABLE gold_review (cluster_key TEXT, sample_id TEXT, rater TEXT, verdict TEXT, note TEXT, at TEXT,
                              PRIMARY KEY (cluster_key, sample_id, rater));
    INSERT INTO gold_review VALUES ('k1','s','a','TP','',''),('k2','s','a','TP','',''),('k3','s','a','FP','',''),
                                   ('k4','s','a','unclear','','');
    """)
    conn.commit(); conn.close()
    ov = stats.overview(scratch_db, run_id="r1")
    assert ov["kappa"]["total"] == -0.36 and ov["kappa"]["pairs"][0]["group"] == "semgrep|sonar"
    assert ov["precision"]["n"] == 3 and ov["precision"]["tp"] == 2 and 0 < ov["precision"]["ci_low"] < 0.67
    assert any("kiểm tay" in s for s in ov["limits"])


# ----------------------------------------------------------------------------- 6. estimate
def test_estimate_with_fake_speed_json(orch_env, tmp_path):
    from orchestrator import estimate
    sp = tmp_path / "speed.json"
    sp.write_text(json.dumps({"cheap_s_per_commit": 6, "build_cold_s": 600, "build_warm_s": 60, "fsb_s": 10,
                              "sonar_s": 20, "samples": 12, "buggy_ratio": 0.5}), encoding="utf-8")
    speed, src = estimate.load_speed(sp)
    assert src == "measured" and speed["codeql_s"] == estimate.DEFAULT_SPEED["codeql_s"]
    p = _profile(tmp_path, include_clean=True, workers={"scan": 2, "expensive": 1}, expensive_tools=["findsecbugs", "sonar"])
    r = estimate.estimate(p, n_commits=100, speed=speed, speed_source=src)
    assert r["commits_after_filter"] == 100 and r["buggy_est"] == 50
    assert r["cheap_minutes"] == 5                                   # 100*6/2/60
    assert r["expensive_minutes_cold"] == 1050 and r["expensive_minutes_warm"] == 150   # 100*(600+30)/60
    assert r["speed_source"] == "measured" and r["disk_gb"] > 3
    fixture = json.loads((ROOT / "gui" / "fixtures" / "estimate.json").read_text(encoding="utf-8"))
    assert set(fixture) <= set(r)
    # không có file -> default; include_clean=False -> chỉ buggy lên tầng đắt
    speed_d, src_d = estimate.load_speed(tmp_path / "nope.json")
    r2 = estimate.estimate(_profile(tmp_path, include_clean=False), n_commits=10, speed=speed_d, speed_source=src_d)
    assert r2["speed_source"] == "default" and r2["buggy_est"] == 3 and r2["detail"]["n_expensive"] == 3


def test_estimate_cli_uses_profile(orch_env, tmp_path, monkeypatch, capsys):
    from orchestrator import cli, estimate, profile as prof
    f = tmp_path / "p.json"
    prof.save(_profile(tmp_path), f)
    monkeypatch.setattr(estimate, "count_commits", lambda p: 27)
    monkeypatch.setattr(estimate, "load_speed", lambda path=None: (dict(estimate.DEFAULT_SPEED), "default"))
    assert cli.main(["estimate", "--profile", str(f), "--json"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["commits_after_filter"] == 27 and out["speed_source"] == "default"
    assert cli.main(["estimate"]) == 1


# ----------------------------------------------------------------------------- 7. control
def test_reset_claims_on_scratch_db(orch_env, scratch_db):
    from orchestrator import control
    cid = "313886e99befb94be6cd45f085c98e0019f59829"
    conn = sqlite3.connect(scratch_db)
    conn.execute("UPDATE selected_commits SET status='building', claimed_by='run-x:w0', claimed_at=datetime('now') "
                 "WHERE commit_id=?", [cid])
    conn.execute("INSERT INTO raw_output (commit_id,tool,tier,fmt,content,created_at) VALUES (?,?,?,?,?,'')",
                 [cid, "findsecbugs", "expensive", "xml", "<x/>"])
    conn.execute("INSERT INTO raw_findings (repo,commit_id,tool,tier,file_path,s_line,cwe,rule_id,created_at) "
                 "VALUES ('r',?,?,?,?,?,?,?,'')", [cid, "sonar", "expensive", "A.java", 1, '["CWE-1"]', "x"])
    conn.execute("INSERT INTO expensive_runs (commit_id,tool,phase,status,n_findings,duration_sec,error,created_at) "
                 "VALUES (?,?,?,?,?,?,?,'')", [cid, "maven", "build", "ok", 0, 1.0, None])
    n_cheap_raw = conn.execute("SELECT COUNT(*) FROM raw_findings WHERE tier='cheap'").fetchone()[0]
    conn.commit(); conn.close()

    assert control.reset_claims(scratch_db, run_id="run-khac")["reset"] == 0   # claim của run khác: không đụng
    res = control.reset_claims(scratch_db, run_id="run-x")
    assert res["reset"] == 1 and res["commits"] == [cid] and res["run_id"] == "run-x"
    conn = sqlite3.connect(scratch_db)
    assert conn.execute("SELECT status, claimed_by FROM selected_commits").fetchone() == ("pending", None)
    assert conn.execute("SELECT COUNT(*) FROM raw_findings").fetchone()[0] == n_cheap_raw   # raw rẻ giữ nguyên
    assert conn.execute("SELECT COUNT(*) FROM raw_output WHERE tier='expensive'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM expensive_runs").fetchone()[0] == 1          # telemetry giữ (A1)
    conn.close()
    assert control.reset_claims(scratch_db, all_stale=True)["reset"] == 0

    from orchestrator import cli
    assert cli.main(["reset-claims", "--run", "r", "--db", str(scratch_db), "--json"]) == 0


def test_stop_creates_stop_file_and_cleanup_uses_docker(orch_env, tmp_path, fake_docker):
    from orchestrator import control, progress
    fake_docker.responses.append((lambda c: "ps" in c, (0, "abc123\ndef456\n", "")))
    fake_docker.responses.append((lambda c: "network" in c and "ls" in c, (0, "net1\n", "")))
    res = control.stop("run-1", work=tmp_path / "work")
    assert Path(res["stop_file"]).exists() and res["killed"] is None and not res["errors"]
    cl = control.stop_cleanup("run-1")
    assert cl["containers"] == ["abc123", "def456"] and cl["networks"] == ["net1"] and not cl["errors"]
    assert cl["reset_claims"] == 0                              # DB scratch (ORCH_SQLITE) không có claim của run-1
    from orchestrator import cli
    assert cli.main(["stop-cleanup", "--run", "run-1", "--json"]) == 0     # không có gì dọn vẫn exit 0
    cmds = [" ".join(c) for c in fake_docker.calls]
    assert any("--filter label=orch.run=run-1" in c for c in cmds)
    assert any(c.startswith("docker rm -f abc123 def456") for c in cmds)
    assert any("network rm net1" in c for c in cmds)
    with pytest.raises(ValueError):
        control.run_dir("../evil")
    # stop-file -> progress.should_stop() đúng với env của run
    os.environ["ORCH_STOP_FILE"] = res["stop_file"]
    assert progress.should_stop()


def test_clean_items_dry_run_and_refusals(orch_env, tmp_path, monkeypatch):
    from orchestrator import control
    work = tmp_path / "work"
    (work / "FudanSELab__train-ticket").mkdir(parents=True)
    (work / "FudanSELab__train-ticket" / "a.txt").write_text("x" * 100, encoding="utf-8")
    (work / "pool_99999").mkdir()
    (work / "pool_1").mkdir()
    (work / ".m2cache").mkdir()
    db = tmp_path / "d.sqlite"
    db.write_text("db", encoding="utf-8")
    Path(str(db) + ".lock").write_text(f"{os.getpid()} run-1", encoding="utf-8")
    monkeypatch.setattr(control, "pid_alive", lambda pid: pid in (1, os.getpid()))

    with pytest.raises(ValueError):
        control.parse_items("export")                       # export bắt buộc có đường dẫn
    with pytest.raises(ValueError):
        control.parse_items("all")
    items = control.parse_items(f"clone,pool,m2,export:{tmp_path / 'exp'},db:{db}")
    assert ("db", str(db)) in items and ("export", str(tmp_path / "exp")) in items
    plan = control.clean_plan("https://github.com/FudanSELab/train-ticket", items, work=work)
    paths = {d["path"] for d in plan["would_delete"]}
    assert str(work / "FudanSELab__train-ticket") in paths and str(work / "pool_99999") in paths
    assert str(work / "pool_1") not in paths and str(db) not in paths
    assert any("ĐANG CHẠY" in e for e in plan["errors"]) and any("khoá" in e for e in plan["errors"])
    sz = next(d for d in plan["would_delete"] if d["item"] == "clone")["bytes"]
    assert sz == 100
    assert (work / "pool_99999").exists()                   # dry-run không xoá
    res = control.clean_apply(plan)
    assert not (work / "pool_99999").exists() and (work / "pool_1").exists() and db.exists()
    assert len(res["deleted"]) == 3

    from orchestrator import cli, config
    config.WORK_DIR = work
    assert cli.main(["clean", "https://github.com/FudanSELab/train-ticket", "--items", "pool", "--dry-run", "--json"]) == 2
    assert cli.main(["clean", "https://github.com/FudanSELab/train-ticket", "--items", "bogus"]) == 1


# ----------------------------------------------------------------------------- kappa pairwise + save
def test_kappa_compute_all_and_save(orch_env, scratch_db):
    from orchestrator import kappa as kp
    from orchestrator.storage.sqlite_store import SQLiteStore
    store = SQLiteStore(scratch_db)
    res = kp.compute_all(store)
    assert res["n"] == 17 and {"total", "by_category", "by_group", "pairs"} <= set(res)
    assert all(set(r) == {"group", "value", "n"} for r in res["pairs"]) and res["pairs"]
    n = kp.save_all(store, res, "run-t")                   # A1: store.save_kappa + bảng kappa (schema v2)
    assert n == 1 + len(res["by_category"]) + len(res["by_group"]) + len(res["pairs"])
    assert store.conn.execute("SELECT COUNT(*) FROM kappa WHERE run_id='run-t' AND scope='pair'").fetchone()[0] \
        == len(res["pairs"])
    store.close()


# ----------------------------------------------------------------------------- sensitivity (relabel tiêm)
def test_sensitivity_runs_on_copies(orch_env, scratch_db, tmp_path):
    from orchestrator import config, sensitivity
    seen = []

    def fake_relabel(store, cids, repo, clone_dir):
        seen.append((config.LINE_WINDOW, config.GOLD_ALLOW_1EXP_1CHEAP, bool(config.NOISE_CWE)))

    grid = sensitivity.parse_grid(["line_window=3,7", "noise=on,off"])
    res = sensitivity.run(scratch_db, tmp_path / "sens", grid, relabel_fn=fake_relabel, clone_dir=tmp_path)
    assert len(res["results"]) == 4 and (3, 1, True) in seen and (7, 1, False) in seen
    assert config.LINE_WINDOW == 3 and config.NOISE_CWE == {"CWE-117"}       # khôi phục
    assert (tmp_path / "sens" / "sensitivity.json").exists() and (tmp_path / "sens" / "sensitivity.md").exists()
    assert all(Path(r["db"]).exists() for r in res["results"])
    assert scratch_db.stat().st_size > 0 and "(v1)" in sensitivity.to_markdown(res)
    with pytest.raises(ValueError):
        sensitivity.parse_grid(["vote_threshold=1"])


# ----------------------------------------------------------------------------- scan: progress + stop-file
class _FakeTool:
    name = "semgrep"

    def version(self):
        return "v"

    def digest(self):
        return "d"


class _FakePool:
    def __init__(self, main_repo, size, **kw):
        self.size = size

    def acquire(self):
        return Path(".")

    def checkout(self, clone, sha):
        pass

    def release(self, clone):
        pass

    def cleanup(self):
        pass


def _fake_commits(n):
    from orchestrator.enumerate_commits import CommitInfo
    return [CommitInfo(commit_id=f"{i:040x}", parent_commit=None, author_date="2024-01-01", message=f"c{i}",
                       is_merge=False, changed_files=[f"F{i}.java"]) for i in range(n)]


def _patch_scan(monkeypatch, tmp_path, n_commits, scan_hook=None):
    from orchestrator import cli, enumerate_commits as enm
    monkeypatch.setenv("ORCH_KAMEI", "0")
    monkeypatch.setenv("ORCH_SCAN_WORKERS", "2")
    cli.config.reload()
    monkeypatch.setattr(cli, "cheap_tool_classes", lambda: {"semgrep": _FakeTool, "bearer": _FakeTool,
                                                            "gitleaks": _FakeTool, "trufflehog": _FakeTool,
                                                            "horusec": _FakeTool})
    monkeypatch.setattr(enm, "clone_or_update", lambda repo, dest=None: tmp_path)
    monkeypatch.setattr(enm, "enumerate_repo", lambda *a, **k: ((ci, True, "ok") for ci in _fake_commits(n_commits)))
    import orchestrator.repo_pool as rp
    monkeypatch.setattr(rp, "RepoPool", _FakePool)

    def _one(ci, clone, tools, tool_names, args, store):
        if scan_hook:
            scan_hook(ci)
        store.mark_scan_done(ci.commit_id)
        return f"[{ci.commit_id[:8]}] 1 file đổi | 0 findings -> 0 cụm", 1, 0, 1

    monkeypatch.setattr(cli, "_scan_one_commit", _one)
    return cli


def test_scan_emits_progress_and_honors_stop_file(orch_env, monkeypatch, tmp_path):
    from orchestrator import progress
    stop_file = Path(os.environ["ORCH_STOP_FILE"])
    seen: list[str] = []

    def hook(ci):
        seen.append(ci.commit_id)
        stop_file.write_text("stop", encoding="utf-8")       # stop-file xuất hiện giữa run

    cli = _patch_scan(monkeypatch, tmp_path, 10, hook)
    rc = cli.main(["scan", "https://github.com/o/r", "--no-meta", "--max", "0", "--tools", "semgrep,bearer"])
    assert rc == 3
    assert 0 < len(seen) <= 4                                   # chỉ lô đang chạy (≤ 2 worker) hoàn tất, không claim thêm
    ev = progress.read(os.environ["ORCH_PROGRESS_FILE"])
    kinds = [(e["phase"], e["event"]) for e in ev]
    assert kinds[0] == ("scan", "start") and ev[0]["total"] == 10 and ev[0]["run_id"] == "test-run"
    assert ("scan", "item") in kinds and kinds[-1] == ("scan", "stop") and ("scan", "done") not in kinds
    item = next(e for e in ev if e["event"] == "item")
    assert {"done", "total", "sha", "status"} <= set(item) and item["status"] == "ok"


def test_scan_completes_with_done_event(orch_env, monkeypatch, tmp_path):
    from orchestrator import progress
    cli = _patch_scan(monkeypatch, tmp_path, 5)
    rc = cli.main(["scan", "https://github.com/o/r", "--no-meta", "--max", "0"])
    assert rc == 0
    ev = progress.read(os.environ["ORCH_PROGRESS_FILE"])
    assert ev[-1]["event"] == "done" and ev[-1]["done"] == 5
    assert sum(1 for e in ev if e["event"] == "item") == 5
    # resume: chạy lại -> 0 commit cần quét, vẫn start/done
    rc2 = cli.main(["scan", "https://github.com/o/r", "--no-meta", "--max", "0"])
    assert rc2 == 0 and progress.read(os.environ["ORCH_PROGRESS_FILE"])[-1]["total"] == 0


def test_scan_writes_run_meta_v2_without_vote_threshold(orch_env, monkeypatch, tmp_path, scratch_db):
    cli = _patch_scan(monkeypatch, tmp_path, 1)
    captured = {}
    from orchestrator.storage.sqlite_store import SQLiteStore
    monkeypatch.setattr(SQLiteStore, "insert_run_meta",
                        lambda self, tier=None, **fields: captured.update({"tier": tier, **fields}))
    rc = cli.main(["scan", "https://github.com/o/r", "--since", "2024-01-01", "--branch", "main"])
    assert rc == 0
    assert "vote_threshold" not in captured
    assert captured["tier"] == "scan" and captured["run_id"] == "test-run" and captured["branch"] == "main"
    assert json.loads(captured["scope_json"]) == {"mode": "time", "since": "2024-01-01", "until": None, "max": 0,
                                                  "from_sha": None, "to_sha": None, "date_field": "committer"}
    snap = json.loads(captured["config_snapshot_json"])
    assert snap["params_v1"]["line_window"] == 3 and "ORCH_SQLITE" in snap["env"]
    assert captured["experiment"] == 0 and json.loads(captured["tools_json"])[0]["name"] == "semgrep"


def test_pipeline_passes_tools_and_scope_down(orch_env, monkeypatch):
    from orchestrator import cli
    seen = []

    def rec(name):
        def f(ns):
            seen.append((name, ns.tools, getattr(ns, "expensive_tools", None), ns.since, ns.max))
            return 0
        return f

    for fn in ("cmd_scan", "cmd_select", "cmd_analyze", "cmd_relabel", "cmd_kappa", "cmd_export"):
        monkeypatch.setattr(cli, fn, rec(fn))
    rc = cli.main(["pipeline", "https://github.com/o/r", "--since", "2024-01-01", "--tools", "semgrep,bearer",
                   "--expensive-tools", "sonar", "--codeql", "0"])
    assert rc == 0 and [s[0] for s in seen] == ["cmd_scan", "cmd_select", "cmd_analyze", "cmd_relabel",
                                                 "cmd_kappa", "cmd_export"]
    assert seen[0][1] == "semgrep,bearer" and seen[0][3] == "2024-01-01" and seen[0][4] == 0
    assert seen[2][1] is None and seen[2][2] == "sonar"          # analyze: cheap None, expensive truyền xuống
    # 1 bước trả 3 (stop-file) -> pipeline dừng, exit 3
    seen.clear()
    monkeypatch.setattr(cli, "cmd_select", lambda ns: 3)
    assert cli.main(["pipeline", "https://github.com/o/r", "--max", "3"]) == 3
    assert [s[0] for s in seen] == ["cmd_scan"]


# ----------------------------------------------------------------------------- clone_or_update: slug + legacy + fetch
def test_clone_or_update_prefers_slug_then_legacy_with_matching_origin(orch_env, tiny_repo, tmp_path, capsys):
    from orchestrator import config, enumerate_commits as enm
    r, _ = tiny_repo
    work = tmp_path / "w"
    work.mkdir()
    config.WORK_DIR = work
    url = "https://github.com/o/r"
    legacy = work / "r"
    _git(tmp_path, "clone", "-q", str(r), str(legacy))
    _git(legacy, "remote", "set-url", "origin", url)
    assert enm._origin_matches(legacy, url) and enm._origin_matches(legacy, "https://github.com/O/R.git")
    assert not enm._origin_matches(legacy, "https://github.com/other/r")
    # chưa có slug dir, legacy khớp origin -> dùng legacy (fetch tới URL giả thất bại -> chỉ cảnh báo)
    assert enm.clone_or_update(url) == legacy
    assert "fetch thất bại" in capsys.readouterr().err
    # slug dir xuất hiện -> ưu tiên slug
    slug = work / "o__r"
    _git(tmp_path, "clone", "-q", str(r), str(slug))
    assert enm.clone_or_update(url, fetch=False) == slug


# ----------------------------------------------------------------------------- infra_error ở tầng rẻ (A1 yêu cầu)
def test_scan_stops_after_consecutive_infra_errors(orch_env, monkeypatch, tmp_path):
    from orchestrator import progress
    cli = _patch_scan(monkeypatch, tmp_path, 10)
    monkeypatch.setenv("ORCH_INFRA_STOP_AFTER", "3")
    cli.config.reload()
    monkeypatch.setenv("ORCH_SCAN_WORKERS", "1")
    cli.config.reload()
    calls = []

    def _infra(ci, clone, tools, tool_names, args, store):
        calls.append(ci.commit_id)
        return f"[{ci.commit_id[:8]}] INFRA_ERROR (semgrep)", 0, 0, 0, 1

    monkeypatch.setattr(cli, "_scan_one_commit", _infra)
    rc = cli.main(["scan", "https://github.com/o/r", "--no-meta", "--max", "0"])
    assert rc == 3 and len(calls) == 3                                  # dừng sau đúng 3 infra_error liên tiếp
    ev = progress.read(os.environ["ORCH_PROGRESS_FILE"])
    assert ev[-1]["event"] == "stop" and ev[-1]["status"] == "infra_error"
    assert all(e["status"] == "infra_error" for e in ev if e["event"] == "item")


def test_scan_infra_error_resets_counter_on_ok(orch_env, monkeypatch, tmp_path):
    cli = _patch_scan(monkeypatch, tmp_path, 6)
    monkeypatch.setenv("ORCH_SCAN_WORKERS", "1")
    cli.config.reload()
    seq = iter([1, 1, 0, 1, 1, 0])                                       # không bao giờ 3 liên tiếp

    def _mixed(ci, clone, tools, tool_names, args, store):
        inf = next(seq)
        if not inf:
            store.mark_scan_done(ci.commit_id)
        return f"[{ci.commit_id[:8]}] x", 0 if inf else 1, 0, 0, inf

    monkeypatch.setattr(cli, "_scan_one_commit", _mixed)
    assert cli.main(["scan", "https://github.com/o/r", "--no-meta", "--max", "0"]) == 0


def test_scan_one_commit_detects_infra_error_record(orch_env, scratch_db, tmp_path):
    """Tool ghi raw_out ("error", JSON kind=infra_error) -> commit KHÔNG scan_done, trả n_infra=1."""
    import argparse
    from orchestrator import cli
    from orchestrator.storage.sqlite_store import SQLiteStore
    from orchestrator.tools.base import error_record
    from orchestrator.enumerate_commits import CommitInfo

    class _InfraTool:
        name = "semgrep"

        def scan(self, clone, cid, repo, changed, raw_out=None):
            raw_out.insert(0, ("error", error_record("semgrep", "infra_error", "Cannot connect to the Docker daemon")))
            return []

    class _OkTool(_InfraTool):
        name = "bearer"

        def scan(self, clone, cid, repo, changed, raw_out=None):
            raw_out.append(("json", "[]"))
            return []

    ci = CommitInfo(commit_id="f" * 40, parent_commit=None, author_date="2024-01-01", message="m", is_merge=False,
                    changed_files=["A.java"])
    store = SQLiteStore(scratch_db)
    ns = argparse.Namespace(repo="https://github.com/o/r")
    cli.config.CHEAP_INTRA_PARALLEL = 0
    res = cli._scan_one_commit(ci, tmp_path, [_InfraTool(), _OkTool()], ["semgrep", "bearer"], ns, store)
    assert res[4] == 1 and "INFRA_ERROR" in res[0] and res[1] == 0
    assert ci.commit_id not in store.scan_done_ids()
    # tool ok không lỗi -> scan_done, n_infra=0
    res2 = cli._scan_one_commit(ci, tmp_path, [_OkTool()], ["bearer"], ns, store)
    assert res2[4] == 0 and ci.commit_id in store.scan_done_ids()
    store.close()


def test_kappa_ignores_raw_output_error_rows(orch_env, scratch_db):
    """raw_output fmt='error' (tool không chạy được) KHÔNG được tính là rater 'không báo'."""
    import sqlite3
    from orchestrator import kappa as kp
    from orchestrator.storage.sqlite_store import SQLiteStore
    store = SQLiteStore(scratch_db)
    before = kp.compute_all(store)
    store.close()
    conn = sqlite3.connect(scratch_db)
    cids = [r[0] for r in conn.execute("SELECT DISTINCT commit_id FROM raw_findings")]
    for cid in cids:                                            # thêm 'codeql' + 'semgrep' lỗi trên mọi commit
        for tool in ("codeql", "sonar"):
            conn.execute("INSERT INTO raw_output (commit_id,tool,tier,fmt,content,created_at) VALUES (?,?,?,?,?,'')",
                         [cid, tool, "expensive", "error", '{"tool":"%s","kind":"tool_timeout","msg":"x"}' % tool])
    conn.commit(); conn.close()
    store = SQLiteStore(scratch_db)
    after = kp.compute_all(store)
    store.close()
    assert after == before                                      # không đổi mẫu số / không thêm cặp codeql|…
    assert not any("codeql" in p["group"] or "sonar" in p["group"] for p in after["pairs"])


# ----------------------------------------------------------------------------- A5: select idempotent (resume), PROFILE_DRIVEN, stop-cleanup --json
def test_select_idempotent_keeps_done_status(orch_env, scratch_db):
    import sqlite3
    from orchestrator import select_commits
    from orchestrator.storage.sqlite_store import SQLiteStore
    cid = "313886e99befb94be6cd45f085c98e0019f59829"
    SQLiteStore(scratch_db).close()                                      # migrate v2 (cột n_expensive_ok)
    conn = sqlite3.connect(scratch_db)
    conn.execute("UPDATE selected_commits SET status='done', build_status='ok', n_expensive_ok=2 WHERE commit_id=?", [cid])
    conn.execute("INSERT INTO selected_commits (commit_id, role, status) VALUES ('0'||substr(?,2), 'buggy', 'done')", [cid])
    conn.commit(); conn.close()
    store = SQLiteStore(scratch_db)
    r1 = select_commits.select(store, include_clean=False)              # nhánh KHÔNG include_clean (trước đây replace)
    row = store.conn.execute("SELECT status, build_status, n_expensive_ok FROM selected_commits WHERE commit_id=?",
                             [cid]).fetchone()
    assert row == ("done", "ok", 2) and r1["added"] == 0 and r1["removed_stale"] == 1   # hàng giả ngoài universe bị bỏ
    assert store.conn.execute("SELECT COUNT(*) FROM selected_commits").fetchone()[0] == 1
    _u, _b, clean, _g = select_commits.classify(store)                  # số clean thật trong scratch (data-driven)
    r2 = select_commits.select(store, include_clean=True)               # thêm clean, buggy done vẫn giữ
    assert r2["added"] == len(clean) and r2["kept"] == 1 and r2["total_selected"] == 1 + len(clean)
    assert store.conn.execute("SELECT status FROM selected_commits WHERE commit_id=?", [cid]).fetchone() == ("done",)
    assert store.conn.execute("SELECT COUNT(*) FROM selected_commits WHERE status='pending' AND role='clean'").fetchone()[0]         == len(clean)
    r3 = select_commits.select(store, include_clean=False)              # chạy lại không include_clean: giữ clean đã có
    assert r3["added"] == 0 and r3["kept"] == 1 + len(clean) and r3["total_selected"] == 1 + len(clean)
    # role đổi (giả lập clean -> buggy): giữ status, đổi role
    store.conn.execute("UPDATE selected_commits SET role='clean', status='done' WHERE commit_id=?", [cid]); store.conn.commit()
    select_commits.select(store, include_clean=False)
    assert store.conn.execute("SELECT role, status FROM selected_commits WHERE commit_id=?", [cid]).fetchone() == ("buggy", "done")
    store.close()
    from orchestrator import cli
    assert cli.main(["select", "--json"]) == 0


def test_profile_driven_contains_every_stage_command():
    from orchestrator import cli
    assert {"pipeline", "scan", "enumerate", "select", "analyze", "relabel", "kappa", "features", "export"} \
        <= set(cli.PROFILE_DRIVEN)


def test_stop_cleanup_json_is_single_last_stdout_line(orch_env, fake_docker, capsys, tmp_path):
    from orchestrator import cli, profile as prof
    fake_docker.responses.append((lambda c: "ps" in c, (0, "c1\n", "")))
    assert cli.main(["stop-cleanup", "--run", "r1", "--json"]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    data = json.loads(out[-1])
    assert data["run_id"] == "r1" and data["containers"] == ["c1"] and "reset_claims" in data
    for line in out[:-1]:
        with pytest.raises(ValueError):
            json.loads(line)                                             # JSON chỉ ở dòng cuối
    # diagnostics chữ ký đủ: --run --out [--profile] [--work] --json
    p = prof.default_profile("https://github.com/o/r", "main")
    p["paths"] = {"db": str(tmp_path / "d.sqlite"), "export": str(tmp_path / "e"), "work": str(tmp_path / "w")}
    pf = tmp_path / "p.json"
    prof.save(p, pf)
    assert cli.main(["diagnostics", "--run", "r1", "--out", str(tmp_path / "z.zip"), "--profile", str(pf),
                     "--work", str(tmp_path / "w"), "--json"]) == 0
    last = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert last["run_id"] == "r1" and "profile.json" in last["files"]


# ----------------------------------------------------------------------------- ORCH_CLEAN_PER_BUGGY
def test_clean_per_buggy_caps_clean_commits(orch_env, scratch_db, monkeypatch, capsys):
    from orchestrator import config, select_commits
    from orchestrator.storage.sqlite_store import SQLiteStore
    monkeypatch.setenv("ORCH_CLEAN_PER_BUGGY", "1")
    config.reload()
    assert config.CLEAN_PER_BUGGY == 1
    store = SQLiteStore(scratch_db)
    store.insert_scanned_files([{"repo": "r", "commit_id": f"{i:040x}", "parent_commit": None, "author_date": "2024-01-01",
                                 "file_path": "X.java", "n_tools_ran": 5, "tools": [], "n_findings": 0} for i in (1, 2, 3)])
    _u, buggy, clean, _g = select_commits.classify(store)
    assert len(buggy) == 1 and len(clean) == 3
    r = select_commits.select(store, include_clean=True)
    assert r["clean_cap"] == 1 and r["clean_selected"] == 1 and r["total_selected"] == 2
    picked = store.conn.execute("SELECT commit_id FROM selected_commits WHERE role='clean'").fetchall()
    assert picked == [(sorted(clean)[0],)]                              # xác định: commit_id nhỏ nhất
    # chạy lại: idempotent, vẫn 1 clean (giữ cái đã có)
    r2 = select_commits.select(store, include_clean=True)
    assert r2["clean_selected"] == 1 and r2["added"] == 0 and r2["total_selected"] == 2
    # nới cap -> thêm clean mới, giữ clean cũ
    monkeypatch.setenv("ORCH_CLEAN_PER_BUGGY", "2"); config.reload()
    r3 = select_commits.select(store, include_clean=True)
    assert r3["clean_cap"] == 2 and r3["clean_selected"] == 2 and r3["added"] == 1
    # cap 0 -> không thêm clean mới nhưng KHÔNG xoá clean đã có (vẫn trong universe)
    monkeypatch.setenv("ORCH_CLEAN_PER_BUGGY", "0"); config.reload()
    r4 = select_commits.select(store, include_clean=True)
    assert r4["clean_cap"] == 0 and r4["clean_selected"] == 2 and r4["removed_stale"] == 0
    # không include_clean -> cap không áp
    assert select_commits.select(store, include_clean=False)["clean_cap"] is None
    store.close()
    # rỗng -> None (lấy hết); sai -> cảnh báo + None
    monkeypatch.setenv("ORCH_CLEAN_PER_BUGGY", ""); config.reload(); assert config.CLEAN_PER_BUGGY is None
    monkeypatch.setenv("ORCH_CLEAN_PER_BUGGY", "x"); config._WARNED.clear(); config.reload()
    assert config.CLEAN_PER_BUGGY is None and "ORCH_CLEAN_PER_BUGGY" in capsys.readouterr().err
    # profile.filters -> env
    from orchestrator import profile as prof
    p = prof.default_profile("https://github.com/o/r", "m"); p["paths"]["db"] = "x"; p["filters"] = {"clean_per_buggy": 3}
    assert prof.to_env(p)["ORCH_CLEAN_PER_BUGGY"] == "3" and "ORCH_CLEAN_PER_BUGGY" in config.ENV_KEYS


# ----------------------------------------------------------------------------- stats: giới hạn gộp cụm FSB–Sonar
def test_stats_limits_cross_tool_sentence_on_smoke(orch_env, tmp_path):
    import shutil
    from orchestrator import stats
    smoke = ROOT / "tests" / "fixtures" / "smoke_v2.db"
    db = tmp_path / "smoke.sqlite"
    shutil.copy(smoke, db)
    ov = stats.overview(db)
    ct = ov["cross_tool"]
    assert {"findsecbugs", "sonar"} <= set(ct["expensive_tools_seen"]) and ct["fsb_sonar_clusters"] == 0
    assert any("neo cùng một lỗi" in s and "18–43 dòng" in s and "METHODOLOGY §8" in s for s in ov["limits"])
    # DB scratch (chỉ tool rẻ) -> không có câu đó
    ov2 = stats.overview(ROOT / "tests" / "fixtures" / "scratch.db")
    assert ov2["cross_tool"]["expensive_tools_seen"] == [] and not any("neo cùng một lỗi" in s for s in ov2["limits"])
