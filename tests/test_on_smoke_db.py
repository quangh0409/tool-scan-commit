"""Backend trên DB v2 THẬT (tests/fixtures/smoke_v2.db: train-ticket 3 commit đã analyze FSB+Sonar) + export thật.

Số liệu mốc (từ smoke run 2026-10-05): findings 114 = silver 97 + candidate 17, gold 0; raw_findings 324;
1 commit selected (buggy, done, n_expensive_ok=2); verified_clean 0 (commit đó có finding in_diff -> positive);
cheap_clean 2; κ total −0.244 (n=114); run_meta 2 tier (smoke1) với digest FSB/Sonar + git sha.
"""
from __future__ import annotations

import importlib
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from gui import api_results, api_review  # noqa: E402

RUN = "smoke1"
BUGGY = "313886e99befb94be6cd45f085c98e0019f59829"
CLEAN = "4a9599f4a5b38ce56ae7b7f29a7da9beec87ed11"
EXPORT_SRC = ROOT / "tests" / "fixtures" / "export_smoke"


def _m(name):
    return importlib.import_module(name)


@pytest.fixture
def smoke_export(tmp_path):
    """Bản sao export thật (manifest/dataset/commits/SHA256SUMS) — thư mục riêng để export lần 2 ra _2."""
    dst = tmp_path / "export_smoke"
    shutil.copytree(EXPORT_SRC, dst)
    return dst


@pytest.fixture
def smoke_run(orch_env, smoke_db, smoke_export, monkeypatch, tmp_path):
    monkeypatch.setenv("SECJIT_HOME", str(tmp_path / "secjit"))
    import registry
    registry.upsert({"run_id": RUN, "repo": "https://github.com/FudanSELab/train-ticket", "branch": "master",
                     "db": str(smoke_db), "export": str(smoke_export), "work": str(tmp_path / "work"), "profile": "",
                     "started": "2026-10-05T07:39:28", "finished": "2026-10-05T08:00:02", "status": "done", "pid": None})
    return {"run_id": RUN, "db": smoke_db, "export": smoke_export}


# ----------------------------------------------------------------------------- verify_run 17/17
def test_verify_run_passes_on_real_smoke(orch_env, smoke_db, smoke_export):
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        vr = importlib.reload(importlib.import_module("verify_run"))
    finally:
        sys.path.pop(0)
    res = vr.run(smoke_db, smoke_export)
    assert res["pass"] is True, [c for c in res["checks"] if c["status"] == "FAIL"]
    st = {c["id"]: c["status"] for c in res["checks"]}
    assert len(st) == 17 and set(st.values()) == {"PASS"}
    assert "digest" in {c["id"]: c for c in res["checks"]}["run_meta_analyze"]["detail"]


# ----------------------------------------------------------------------------- stats.overview
def test_stats_overview_numbers(orch_env, smoke_db):
    stats = _m("orchestrator.stats")
    ov = stats.overview(smoke_db, run_id=RUN)
    assert {k: ov["labels"][k] for k in ("gold", "silver", "candidate", "verified_clean")} \
        == {"gold": 0, "silver": 97, "candidate": 17, "verified_clean": 0}
    f = ov["funnel"]
    assert (f["commits"], f["after_filter"], f["buggy"], f["built"], f["build_failed"], f["skipped"], f["infra_error"]) \
        == (3, 3, 1, 1, 0, 0, 0)
    assert ov["coverage"] == {"one": 114, "two": 0, "three_plus": 0}   # FSB và Sonar không gặp nhau cụm nào
    k = ov["kappa"]
    assert k["run_id"] == RUN and k["total"] == -0.244 and k["n"] == 114
    assert len(k["by_category"]) == 3 and len(k["by_group"]) == 5 and len(k["pairs"]) == 10
    assert {g["group"]: g["silver"] for g in ov["by_cwe_group"]}["CWE-346"] > 0
    assert sum(ov["coverage"].values()) == 114
    assert ov["precision"] is None and ov["experiment"] is None
    assert ov["params_v1"]["line_window"] == 3
    assert any("κ" in s for s in ov["limits"]) and any("gold" in s for s in ov["limits"])


@pytest.mark.xfail(strict=True, reason="LỆCH A2 stats.py:63-99 (_funnel/_negatives): universe = scanned_files chỉ có "
                   "commit buggy (clean commit 0 file-code không có row) -> cheap_clean=0, clean=0; export/negative_level/"
                   "manifest dùng raw_output∪findings∪raw_findings -> cheap_clean=2 (verify_run PASS). Sửa stats rồi bỏ xfail.")
def test_stats_cheap_clean_matches_export(orch_env, smoke_db):
    stats = _m("orchestrator.stats")
    ov = stats.overview(smoke_db, run_id=RUN)
    man = json.loads((EXPORT_SRC / "run_manifest.json").read_text(encoding="utf-8"))
    assert ov["labels"]["cheap_clean"] == man["counts"]["cheap_clean"] == 2
    assert ov["funnel"]["clean"] == 2


# ----------------------------------------------------------------------------- api_results trên DB thật
def test_api_overview_findings_finding_commits(smoke_run):
    ov = api_results.overview({"id": RUN}, None)
    assert ov["labels"]["silver"] == 97 and ov["relabeled"] is True and ov["run_id"] == RUN
    assert ov["raw_by_tool"]["findsecbugs"] > 0 and ov["raw_by_tool"]["sonar"] > 0 and sum(ov["raw_by_tool"].values()) == 324

    fs = api_results.findings({"id": RUN, "label": "silver", "tier": "expensive", "size": 500}, None)
    assert fs["total"] == 97 and all(r["label"] == "silver" and r["tier"] == "expensive" for r in fs["rows"])
    assert all(r["evidence"] == {"consensus": "silver", "validation": "unreviewed"} for r in fs["rows"])
    # không cụm nào ≥2 tool trên DB này (29 FSB-only, 68 Sonar-only, 17 bearer-only)
    assert api_results.findings({"id": RUN, "min_tools": 2}, None)["total"] == 0
    # finding panel: cụm FSB và cụm Sonar đều có tool_messages từ raw_findings của tool đắt + raw_path
    for tool in ("findsecbugs", "sonar"):
        pick = next(r for r in fs["rows"] if r["tools"] == [tool])
        fd = api_results.finding({"id": RUN, "cluster_key": pick["cluster_key"]}, None)
        assert fd["row"]["cluster_key"] == pick["cluster_key"] and fd["row"]["label"] == "silver"
        # _tool_messages gom raw trong ±2W cùng file -> cụm Sonar CORS (S5122) còn thấy FSB PERMISSIVE_CORS cách >3 dòng
        # (bằng chứng lân cận; cũng là ca W=7 sẽ gộp — xem sensitivity)
        tools_msg = {m["tool"] for m in fd["tool_messages"]}
        assert tool in tools_msg and tools_msg <= {"findsecbugs", "sonar"}, fd["tool_messages"]
        assert all(m["message"] and m["raw_path"] == f"{BUGGY[:12]}/{m['tool']}.raw."
                   f"{'xml' if m['tool'] == 'findsecbugs' else 'json'}" for m in fd["tool_messages"])
        assert fd["diff_lines"] and fd["eligible"]["denominator"] >= 2
    prov = fd["provenance"]
    assert prov["analyze_run_id"] == RUN and prov["scan_run_id"] == RUN
    assert prov["orchestrator_git_sha"] and prov["line_window"] == 3 and "E>=2" in prov["gold_rule"]
    digests = {t["name"]: t.get("digest") for t in prov["tools_json"]}
    assert digests["findsecbugs"] and digests["sonar"] and digests["gitleaks"]
    assert len(prov["tools_json"]) == 8 and "maven" in digests   # 5 rẻ + FSB + Sonar + maven image dùng thật

    cm = api_results.commits({"id": RUN}, None)
    assert cm["total"] == 1
    row = cm["rows"][0]
    assert row["commit"] == BUGGY and row["status"] == "done" and row["n_expensive_ok"] == 2
    assert row["negative_level"] is None and row["build_status"] == "ok" and row["kamei"]["nf"] is not None


def test_api_export_does_not_overwrite(smoke_run):
    res = api_results.export({"id": RUN}, {"formats": ["jsonl", "csv"]})
    real = Path(res["export_dir"])
    assert real.name == "export_smoke_2" and res["exists"] is True
    assert {"dataset.jsonl", "commits.jsonl", "run_manifest.json", "SHA256SUMS", "dataset.csv"} <= set(res["files"])
    assert res["counts"]["silver"] == 97 and res["manifest"]["counts"]["candidate"] == 17
    # export gốc không bị đụng
    assert (smoke_run["export"] / "SHA256SUMS").read_text(encoding="utf-8") == \
        (EXPORT_SRC / "SHA256SUMS").read_text(encoding="utf-8")
    import registry
    assert registry.get(RUN)["export"] == str(real)


# ----------------------------------------------------------------------------- review trên DB không gold
def test_review_sample_empty_on_smoke(smoke_run):
    rv = _m("orchestrator.review")
    st = _m("orchestrator.storage.sqlite_store").SQLiteStore(smoke_run["db"])
    try:
        res = rv.sample(st, seed=1, n_pos=200, n_neg=100)
        assert res["n_pos"] == 0 and res["n_neg"] == 0
        assert res["available"] == {"gold_clusters": 0, "verified_clean": 0}
        assert rv.next_item(st, res["sample_id"], "r1") is None
    finally:
        st.close()
    out = api_review.sample({"id": RUN}, {"seed": 1, "n_pos": 200, "n_neg": 100})
    assert out["n_pos"] == 0 and out["n_neg"] == 0
    assert out.get("empty") is True and "gold" in (out.get("message") or out.get("hint") or "").lower()
    nxt = api_review.next_item({"id": RUN, "sample_id": out["sample_id"], "rater": "r1"}, None)
    assert nxt.get("cluster_key") is None and nxt["remaining"] == 0


def test_fixture_export_matches_fixture_db(orch_env, smoke_db):
    """dataset.jsonl/commits.jsonl fixture khớp DB fixture (đề phòng cập nhật lệch)."""
    man = json.loads((EXPORT_SRC / "run_manifest.json").read_text(encoding="utf-8"))
    assert man["run_id"] == RUN and man["counts"]["clusters"] == 114
    rows = [json.loads(l) for l in (EXPORT_SRC / "dataset.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 114 and all(len(r["cluster_key"]) == 32 for r in rows)
    commits = {json.loads(l)["commit_id"]: json.loads(l) for l in
               (EXPORT_SRC / "commits.jsonl").read_text(encoding="utf-8").splitlines()}
    assert commits[BUGGY]["n_expensive_ok"] == 2 and commits[BUGGY]["negative_level"] is None
    assert commits[CLEAN]["negative_level"] == "cheap-clean" and commits[CLEAN]["n_expensive_ok"] == 0
