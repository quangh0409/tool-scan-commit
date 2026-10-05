"""Test backend GUI màn 6–10 (gui/api_*.py) — không Docker, không chạy pipeline thật.

DB: bản sao tests/fixtures/scratch.db (train-ticket 3 commit). Registry giả qua SECJIT_HOME=tmp.
runner.start/stop được monkeypatch (không spawn tiến trình nền thật).
"""
from __future__ import annotations

import json
import sys
import types
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from gui import api_results, api_review, api_runs, api_settings  # noqa: E402
from gui.errors import ApiError  # noqa: E402

RUN = "r-test-A"
BUGGY = "313886e99befb94be6cd45f085c98e0019f59829"


@pytest.fixture
def secjit_home(monkeypatch, tmp_path):
    home = tmp_path / "secjit"
    monkeypatch.setenv("SECJIT_HOME", str(home))
    return home


@pytest.fixture
def run_a(orch_env, secjit_home, scratch_db, tmp_path):
    """Run `r-test-A` trong registry trỏ vào bản sao scratch.db; work dir tmp có progress.jsonl."""
    import registry
    work = tmp_path / "work"
    (work / RUN).mkdir(parents=True)
    (work / RUN / "progress.jsonl").write_text(
        '{"ts":"2026-10-05T11:00:01","run_id":"%s","phase":"scan","event":"start","total":3}\n'
        '{"ts":"2026-10-05T11:02:10","run_id":"%s","phase":"scan","event":"item","done":1,"total":3,"sha":"%s","status":"ok"}\n'
        '{"ts":"2026-10-05T11:08:00","run_id":"%s","phase":"scan","event":"done","done":3,"total":3}\n'
        % (RUN, RUN, BUGGY[:8], RUN), encoding="utf-8")
    registry.upsert({"run_id": RUN, "repo": "https://github.com/FudanSELab/train-ticket", "branch": "master",
                     "db": str(scratch_db), "export": "", "work": str(work), "profile": "",
                     "started": "2026-10-05T11:00:00", "finished": "2026-10-05T11:10:00", "status": "done", "pid": None})
    return {"run_id": RUN, "db": scratch_db, "work": work}


# ----------------------------------------------------------------------------- overview / findings / finding
def test_overview_has_contract_keys_and_raw_by_tool(run_a):
    ov = api_results.overview({"id": RUN}, None)
    fixture = json.loads((ROOT / "gui" / "fixtures" / "overview.json").read_text(encoding="utf-8"))
    assert set(fixture) <= set(ov)
    assert ov["labels"]["candidate"] == 17 and ov["funnel"]["buggy"] == 1
    assert ov["raw_by_tool"] == {"bearer": 18}
    assert ov["relabeled"] is False and ov["run_id"] == RUN and len(ov["limits"]) >= 5


def test_overview_unknown_run_404(secjit_home, orch_env):
    with pytest.raises(ApiError) as e:
        api_results.overview({"id": "r-khong-co"}, None)
    assert e.value.status == 404 and e.value.to_dict()["error"]["code"] == "ENOTFOUND"


def test_findings_filter_and_paging(run_a):
    page1 = api_results.findings({"id": RUN, "size": "5"}, None)
    assert page1["total"] == 17 and len(page1["rows"]) == 5 and page1["page"] == 1
    r0 = page1["rows"][0]
    for k in ("cluster_key", "commit", "file_path", "s_line", "cwe_group", "cwe", "tools", "n_agree", "tier", "label",
              "evidence", "in_diff"):
        assert k in r0, k
    assert len(r0["cluster_key"]) == 32 and r0["evidence"] == {"consensus": "candidate", "validation": "unreviewed"}
    assert r0["tools"] == ["bearer"] and r0["label"] == "candidate"
    page2 = api_results.findings({"id": RUN, "size": "5", "page": "2"}, None)
    assert len(page2["rows"]) == 5 and page2["rows"][0]["cluster_key"] != r0["cluster_key"]
    assert api_results.findings({"id": RUN, "label": "gold"}, None)["total"] == 0
    assert api_results.findings({"id": RUN, "label": "candidate"}, None)["total"] == 17
    assert api_results.findings({"id": RUN, "min_tools": "2"}, None)["total"] == 0
    assert api_results.findings({"id": RUN, "cwe_group": "xss"}, None)["total"] >= 1
    qres = api_results.findings({"id": RUN, "q": "admin_user"}, None)
    assert 1 <= qres["total"] < 17 and all("admin_user" in r["file_path"] for r in qres["rows"])
    n0 = api_results.findings({"id": RUN, "in_diff": "0"}, None)["total"]
    n1 = api_results.findings({"id": RUN, "in_diff": "1"}, None)["total"]
    assert n0 + n1 == 17 and n1 >= 1
    assert api_results.findings({"id": RUN, "tier": "cheap"}, None)["total"] == 17
    with pytest.raises(ApiError) as e:
        api_results.findings({"id": RUN, "label": "platinum"}, None)
    assert e.value.status == 400


def test_finding_evidence_panel(run_a):
    ck = api_results.findings({"id": RUN, "q": "admin_user"}, None)["rows"][0]["cluster_key"]
    d = api_results.finding({"id": RUN, "cluster_key": ck}, None)
    assert d["row"]["cluster_key"] == ck and d["row"]["file_path"].endswith("admin_user.js")
    kinds = {x["kind"] for x in d["diff_lines"]}
    assert d["diff_lines"] and kinds <= {"ctx", "add", "del", "flag"} and "flag" in kinds
    assert all({"n", "kind", "text"} <= set(x) for x in d["diff_lines"])
    assert d["tool_messages"] and d["tool_messages"][0]["tool"] == "bearer"
    assert d["tool_messages"][0]["raw_path"] == f"{BUGGY[:12]}/bearer.raw.json"
    assert len(d["provenance"]["tools_json"]) == 5 and d["provenance"]["line_window"] == 3
    assert "E>=2" in d["provenance"]["gold_rule"]
    assert d["eligible"]["denominator"] == 6 and "bearer" in d["eligible"]["tools"]
    with pytest.raises(ApiError) as e:
        api_results.finding({"id": RUN, "cluster_key": "xyz"}, None)
    assert e.value.status == 400
    with pytest.raises(ApiError) as e:
        api_results.finding({"id": RUN, "cluster_key": "0" * 32}, None)
    assert e.value.status == 404


def test_commits_table(run_a):
    d = api_results.commits({"id": RUN}, None)
    assert d["total"] == 1 and len(d["rows"]) == 1
    r = d["rows"][0]
    assert r["commit"] == BUGGY and r["role"] == "buggy" and r["status"] == "pending"
    assert r["n_expensive_ok"] == 0 and r["negative_level"] is None   # buggy có finding in_diff=1 -> positive
    assert isinstance(r["kamei"], dict) and "nf" in r["kamei"] and r["build_error"] is None
    assert r["date"] and len(r["date"]) == 10


# ----------------------------------------------------------------------------- export / raw / open
def test_export_creates_files_and_no_overwrite(run_a, tmp_path):
    import registry
    registry.upsert({"run_id": RUN, "export": str(tmp_path / "it's export" / "out")})
    res = api_results.export({"id": RUN}, {"formats": ["jsonl", "csv", "latex"]})
    out = Path(res["export_dir"])
    assert out.name == "out" and res["exists"] is False
    for n in ("dataset.jsonl", "commits.jsonl", "run_manifest.json", "SHA256SUMS", "dataset.csv", "commits.csv", "overview.tex"):
        assert n in res["files"], n
    assert (out / "stats" / "funnel.csv").exists()
    assert res["manifest"]["counts"]["candidate"] == 17 and res["manifest"]["run_id"] == RUN
    head = (out / "dataset.csv").read_text(encoding="utf-8").splitlines()[0]
    assert "cluster_key" in head and "evidence" in head
    assert registry.get(RUN)["export"] == str(out)
    # lần 2 -> thư mục mới _2, exists=True
    res2 = api_results.export({"id": RUN}, {"formats": ["jsonl"]})
    assert res2["exists"] is True and Path(res2["export_dir"]).name == "out_2"
    with pytest.raises(ApiError) as e:
        api_results.export({"id": RUN}, {"formats": ["parquet"]})
    assert e.value.status == 400


def test_raw_from_db_then_file_and_traversal_blocked(run_a, tmp_path):
    r = api_results.raw({"id": RUN, "path": f"{BUGGY[:12]}/bearer.raw.json"}, None)
    assert r["source"].startswith("db:") and r["bytes"] == 25713 and r["content_type"] == "application/json"
    for bad in ("../secret", "a/../../b", "C:/x", "/etc/passwd", "x\\..\\y"):
        with pytest.raises(ApiError) as e:
            api_results.raw({"id": RUN, "path": bad}, None)
        assert e.value.status == 400, bad
    with pytest.raises(ApiError) as e:
        api_results.raw({"id": RUN, "path": "deadbeef0000/semgrep.raw.json"}, None)
    assert e.value.status == 404
    # sau export -> đọc file trong export dir
    import registry
    registry.upsert({"run_id": RUN, "export": str(tmp_path / "exp")})
    api_results.export({"id": RUN}, {"formats": ["jsonl"]})
    r2 = api_results.raw({"id": RUN, "path": "run_manifest.json"}, None)
    assert r2["source"].endswith("run_manifest.json") and json.loads(r2["content"])["run_id"] == RUN


def test_open_path_404_and_features_relabel_rules(run_a, monkeypatch, tmp_path):
    with pytest.raises(ApiError) as e:
        api_results.open_path({}, {"path": str(tmp_path / "khong-co")})
    assert e.value.status == 404
    with pytest.raises(ApiError) as e:
        api_results.relabel({"id": RUN}, None)          # không experiment -> 501
    assert e.value.status == 501
    spawned = {}
    monkeypatch.setattr(api_results.C, "spawn_cli", lambda argv, log, env=None: spawned.update(argv=argv, log=str(log)) or 4242)
    res = api_results.features({"id": RUN}, None)
    assert res["pid"] == 4242 and spawned["argv"][:2] == ["features", "https://github.com/FudanSELab/train-ticket"]
    assert spawned["log"].endswith("features.log")


# ----------------------------------------------------------------------------- runs
def test_list_runs_summary_and_progress(run_a):
    d = api_runs.list_runs({}, None)
    r = [x for x in d["runs"] if x["run_id"] == RUN][0]
    assert r["summary"]["candidate"] == 17 and r["summary"]["commits"] == 3 and r["summary"]["relabeled"] is False
    assert r["db_exists"] is True and r["summary"]["verified_clean"] == 0 and r["summary"]["kappa"] is None
    p = api_runs.get_progress_lines({"id": RUN}, None)
    assert len(p["lines"]) == 3 and p["next"] == 3 and p["lines"][-1]["event"] == "done"
    p2 = api_runs.get_progress_lines({"id": RUN, "since": "2"}, None)
    assert len(p2["lines"]) == 1 and p2["next"] == 3


def test_run_stop_and_resume_without_profile(run_a, monkeypatch):
    import registry
    import runner
    calls = {}

    def fake_stop(run_id, work, force=False, **kw):
        calls.update(run_id=run_id, force=force)
        return {"ok": True, "stop_file": "x", "pid": 1, "alive_before": True, "killed": None, "alive_after": not force,
                "cleanup": {"rc": 0, "available": True, "out": json.dumps(
                    {"containers": ["abc"], "networks": ["orch-sonar-net-r"], "reset_claims": 1, "errors": []})} if force else None}
    monkeypatch.setattr(runner, "stop", fake_stop)
    registry.set_status(RUN, "running", pid=1)
    r = api_runs.run_stop({"id": RUN}, {"force": False})
    assert r["ok"] and calls["force"] is False and r["cleaned"] == []
    r = api_runs.run_stop({"id": RUN}, {"force": True})
    assert r["cleaned"] == ["container abc", "network orch-sonar-net-r", "reset-claims: 1 commit → pending"]
    assert registry.get(RUN)["status"] == "stopped"
    with pytest.raises(ApiError) as e:
        api_runs.run_resume({"id": RUN}, {})
    assert e.value.status == 404                        # không có profile -> không resume


def test_run_start_smoke_uses_scratch_db(run_a, monkeypatch, secjit_home):
    import registry
    import runner
    from orchestrator import profile as prof
    started = {}
    monkeypatch.setattr(runner, "start", lambda path, rid, work, **kw: started.update(path=str(path), rid=rid, work=str(work))
                        or {"pid": 777, "log": "l", "progress": "p", "stop": "s", "run_dir": "d", "meta": "m", "argv": []})
    p = prof.default_profile("https://github.com/FudanSELab/train-ticket", "master")
    p["paths"] = {"db": "D:/x/dataset.sqlite", "export": "D:/x/exp", "work": ""}
    p["scope"]["max"] = 50
    res = api_runs.run_start({}, {"profile": p, "smoke": True})
    assert res["pid"] == 777 and res["run_id"].endswith("-smoke") and "scratch" in res["db"]
    saved = json.loads(Path(started["path"]).read_text(encoding="utf-8"))
    assert saved["scope"]["max"] == 3 and Path(started["work"]) == secjit_home / "work"
    rec = registry.get(res["run_id"])
    assert rec["status"] == "running" and rec["pid"] == 777 and rec["summary"]["smoke"] is True
    with pytest.raises(ApiError) as e:
        api_runs.run_start({}, {"profile": {"schema": 1}})
    assert e.value.status == 400


def test_diagnostics_zip_fallback(run_a):
    res = api_runs.diagnostics({"id": RUN}, None)
    z = zipfile.ZipFile(res["path"])
    names = set(z.namelist())
    assert {"system.json", "run.json", "run/progress.jsonl", "runs.json"} <= names
    assert json.loads(z.read("run.json"))["run_id"] == RUN


# ----------------------------------------------------------------------------- review (module giả)
@pytest.fixture
def fake_review(monkeypatch):
    mod = types.ModuleType("orchestrator.review")
    state = {"remaining": 2, "verdicts": []}

    def sample(store, seed, n_pos, n_neg):
        return {"sample_id": f"s-{seed}", "n_pos": 1, "n_neg": 1, "strata": [{"stratum": "xss|cheap", "n": 1}, {"stratum": "neg|cheap-clean", "n": 1}]}

    def next_item(store, sample_id, rater):
        if state["remaining"] <= 0:
            return None
        return {"cluster_key": "a" * 32, "code_lines": [{"n": 1, "text": "x"}], "diff_lines": [], "cwe_claim": "CWE-79",
                "messages_anon": ["m"], "remaining": state["remaining"], "label": "gold", "tools": ["bearer"]}

    def verdict(store, sample_id, rater, cluster_key, verdict, note):
        state["verdicts"].append((rater, cluster_key, verdict))
        state["remaining"] -= 1
        return {"ok": True, "remaining": state["remaining"]}

    def close(store, sample_id, raters=None):
        return {"precision": {"tp": 1, "fp": 0, "unclear": 0, "n": 1, "point": 1.0, "ci_low": 0.2, "ci_high": 1.0},
                "kappa_raters": None, "disagreements": [{"cluster_key": "a" * 32, "verdicts": {"r1": "TP", "r2": "FP"}}]}
    mod.sample, mod.next_item, mod.verdict, mod.close = sample, next_item, verdict, close
    monkeypatch.setitem(sys.modules, "orchestrator.review", mod)
    return state


def test_review_flow_blind_and_501_when_missing(run_a, fake_review):
    s = api_review.sample({"id": RUN}, {"seed": 7, "n_pos": 1, "n_neg": 1})
    assert s["sample_id"] == "s-7" and len(s["strata"]) == 2
    it = api_review.next_item({"id": RUN, "sample_id": "s-7", "rater": "r1"}, None)
    assert it["cluster_key"] == "a" * 32 and "label" not in it and "tools" not in it   # mù
    v = api_review.verdict({"id": RUN}, {"sample_id": "s-7", "rater": "r1", "cluster_key": "a" * 32, "verdict": "TP", "note": ""})
    assert v["ok"] and v["remaining"] == 1
    with pytest.raises(ApiError) as e:
        api_review.verdict({"id": RUN}, {"sample_id": "s-7", "rater": "r1", "cluster_key": "a" * 32, "verdict": "MAYBE"})
    assert e.value.status == 400
    api_review.verdict({"id": RUN}, {"sample_id": "s-7", "rater": "r1", "cluster_key": "a" * 32, "verdict": "FP", "note": "n"})
    assert api_review.next_item({"id": RUN, "sample_id": "s-7", "rater": "r1"}, None) == {"cluster_key": None, "remaining": 0, "sample_id": "s-7", "rater": "r1"}
    c = api_review.close({"id": RUN}, {"sample_id": "s-7"})
    assert c["precision"]["point"] == 1.0 and c["disagreements"][0]["adjudicated"] is None


def test_review_501_without_backend(run_a, monkeypatch):
    monkeypatch.delitem(sys.modules, "orchestrator.review", raising=False)
    with pytest.raises(ApiError) as e:
        api_review.sample({"id": RUN}, {"seed": 1})
    assert e.value.status == 501


# ----------------------------------------------------------------------------- settings / storage / clean / profiles
def test_settings_roundtrip_and_validation(secjit_home, orch_env, tmp_path):
    d = api_settings.get_settings({}, None)
    assert d["language"] == "vi" and set(api_settings.SETTINGS_KEYS) <= set(d)
    s = api_settings.set_settings({}, {"out_dir": str(tmp_path / "res"), "work_dir": str(tmp_path / "wk"), "sonar_port": "9100",
                                       "language": "en", "m2_volume": False})
    assert s["ok"] and s["sonar_port"] == 9100 and s["language"] == "en" and s["m2_volume"] is False
    again = api_settings.get_settings({}, None)
    assert again["out_dir"] == str(tmp_path / "res") and again["sonar_port"] == 9100
    with pytest.raises(ApiError):
        api_settings.set_settings({}, {"out_dir": str(tmp_path / "same"), "work_dir": str(tmp_path / "same")})
    with pytest.raises(ApiError):
        api_settings.set_settings({}, {"sonar_port": "80"})


def test_storage_without_docker_and_clean_dry_then_apply(secjit_home, orch_env, tmp_path):
    work = tmp_path / "wk"
    (work / "pool_12188" / "w0").mkdir(parents=True)
    (work / "pool_12188" / "w0" / "f.txt").write_text("x" * 100, encoding="utf-8")
    (work / "FudanSELab__train-ticket").mkdir()
    api_settings.set_settings({}, {"out_dir": str(tmp_path / "res"), "work_dir": str(work)})
    st = api_settings.storage({}, None)
    ids = [i["id"] for i in st["items"]]
    assert ids == ["pool", "clone", "m2", "images", "runs", "results"]
    pool = st["items"][0]
    assert pool["bytes"] == 100 and pool["safety"] == "safe" and st["free_bytes"] > 0 and st["docker"] is False
    assert [i for i in st["items"] if i["id"] == "results"][0]["safety"] == "forbidden"
    dry = api_settings.clean({}, {"items": ["pool"], "dry_run": True})
    assert dry["dry_run"] and [Path(d["path"]).name for d in dry["would_delete"]] == ["pool_12188"] and dry["deleted"] == []
    assert (work / "pool_12188").exists()
    res = api_settings.clean({}, {"items": ["pool"], "dry_run": False})
    assert [Path(d["path"]).name for d in res["deleted"]] == ["pool_12188"] and not (work / "pool_12188").exists()
    with pytest.raises(ApiError) as e:
        api_settings.clean({}, {"items": ["results"], "dry_run": True})
    assert e.value.status == 400
    with pytest.raises(ApiError):
        api_settings.clean({}, {"items": ["bogus"], "dry_run": True})


def test_clean_refuses_when_run_running(secjit_home, orch_env, tmp_path):
    import registry
    work = tmp_path / "wk"
    (work / "pool_1").mkdir(parents=True)
    api_settings.set_settings({}, {"out_dir": str(tmp_path / "res"), "work_dir": str(work)})
    import os
    (work / "r-live").mkdir()
    (work / "r-live" / "pid").write_text(str(os.getpid()), encoding="utf-8")   # pid sống = tiến trình test
    registry.upsert({"run_id": "r-live", "work": str(work), "status": "running", "pid": os.getpid()})
    with pytest.raises(ApiError) as e:
        api_settings.clean({}, {"items": ["pool"], "dry_run": True})
    assert e.value.status == 409


def test_profiles_crud_and_shell(secjit_home, orch_env, tmp_path):
    from orchestrator import profile as prof
    p = prof.default_profile("https://github.com/FudanSELab/train-ticket", "master")
    p["paths"] = {"db": str(tmp_path / "it's db" / "d.sqlite"), "export": "", "work": ""}
    assert api_settings.list_profiles({}, None)["profiles"] == []
    r = api_settings.save_profile({}, {"name": "train-ticket-30", "profile": p})
    assert r["ok"] and Path(r["path"]).exists() and r["overwritten"] is False
    lst = api_settings.list_profiles({}, None)["profiles"]
    assert lst[0]["name"] == "train-ticket-30" and lst[0]["repo"] == p["repo"] and lst[0]["saved"]
    got = api_settings.get_profile({"name": "train-ticket-30"}, None)
    assert got["profile"]["scope"]["max"] == 50
    sh = api_settings.shell({"profile": "train-ticket-30", "shell": "powershell"}, None)
    assert "orchestrator.cli" in sh["command"] and "it''s db" in sh["command"]
    sh2 = api_settings.shell({"shell": "bash"}, {"profile": p})
    assert sh2["command"].startswith("ORCH_SQLITE=")
    with pytest.raises(ApiError):
        api_settings.save_profile({}, {"name": "../x", "profile": p})
    with pytest.raises(ApiError):
        api_settings.save_profile({}, {"name": "bad", "profile": {"schema": 1}})
    assert api_settings.delete_profile({"name": "train-ticket-30"}, None)["ok"]
    with pytest.raises(ApiError) as e:
        api_settings.delete_profile({"name": "train-ticket-30"}, None)
    assert e.value.status == 404
