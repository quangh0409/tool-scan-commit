"""scripts/verify_run.py: FAIL hợp lý trên scratch DB thô; PASS trên DB tạm hợp lệ + export."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLEAN = "4a9599f4a5b38ce56ae7b7f29a7da9beec87ed11"
CLEAN2 = "9bdd9a28f0033e91dec4595d257da81cc7016e47"


@pytest.fixture
def vr():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        m = importlib.import_module("verify_run")
        return importlib.reload(m)
    finally:
        sys.path.pop(0)


def _by_id(res):
    return {c["id"]: c for c in res["checks"]}


def test_scratch_raw_fails_expected_items(vr, orch_env, scratch_db):
    res = vr.run(scratch_db)
    c = _by_id(res)
    assert res["pass"] is False
    assert c["user_version"]["status"] == "FAIL" and "user_version=0" in c["user_version"]["detail"]
    assert c["run_meta_scan"]["status"] == "FAIL" and "schema v2" in c["run_meta_scan"]["detail"]
    assert c["n_expensive_ok_recount"]["status"] == "FAIL" and "thiếu cột" in c["n_expensive_ok_recount"]["detail"]
    assert c["kappa_total"]["status"] == "FAIL"
    # phần dữ liệu thật của scratch vẫn đúng luật
    assert c["findings_cwe_group"]["status"] == "PASS"
    assert c["findings_label_enum"]["status"] == "PASS"
    assert c["gold_rule_v1"]["status"] == "PASS" and c["label_rule_v1"]["status"] == "PASS"
    assert c["selected_no_stuck"]["status"] == "PASS"
    assert c["expensive_status_enum"]["status"] == "PASS"
    fails = {x["id"] for x in res["checks"] if x["status"] == "FAIL"}
    assert fails == {"user_version", "run_meta_scan", "run_meta_analyze", "n_expensive_ok_recount", "kappa_total"}


def test_valid_db_and_export_pass(vr, orch_env, scratch_db, capsys):
    sq = importlib.import_module("orchestrator.storage.sqlite_store")
    exp = importlib.import_module("orchestrator.export_dataset")
    st = sq.SQLiteStore()                                 # migrate -> v2
    sel = [{"commit_id": c, "role": "clean", "selection_reason": "t", "suspect_categories": [],
            "n_suspect_findings": 0, "created_at": "x"} for c in (CLEAN, CLEAN2)]
    st.add_selected(sel)
    for t in ("findsecbugs", "sonar"):
        st.insert_expensive_run({"commit_id": CLEAN, "tool": t, "phase": "analyze", "status": "ok",
                                 "n_findings": 0, "duration_sec": 1})
    st.insert_expensive_run({"commit_id": CLEAN2, "tool": "maven", "phase": "build", "status": "skipped",
                             "n_findings": 0, "duration_sec": 0})
    for c in (CLEAN, CLEAN2):
        st.update_n_expensive_ok(c)
        st.set_commit_status(c, "done", finished=True)
    st.insert_run_meta("analyze", repo="r", orchestrator_git_sha="0123abcd",
                       tools_json=[{"name": "findsecbugs", "image": "i", "digest": "sha256:aa"},
                                   {"name": "sonar", "image": "j", "digest": "sha256:bb"}])
    st.save_kappa("test-run", "total", "", -0.3, 10)
    out = Path(exp.export_all(st, orch_env / "exp")["out"])
    st.close()

    res = vr.run(scratch_db, out)
    assert res["pass"] is True, [c for c in res["checks"] if c["status"] != "PASS"]
    c = _by_id(res)
    assert c["manifest_counts"]["status"] == "PASS" and c["sha256sums"]["status"] == "PASS"
    assert c["dataset_rows"]["detail"].startswith("17 dòng vs 17")
    assert c["verified_clean_rule"]["status"] == "PASS"

    # phá SHA256SUMS + thiếu digest -> FAIL đúng mục; CLI exit 1 / 0
    (out / "dataset.jsonl").write_text("{}\n", encoding="utf-8")
    res2 = vr.run(scratch_db, out)
    c2 = _by_id(res2)
    assert c2["sha256sums"]["status"] == "FAIL" and c2["dataset_rows"]["status"] == "FAIL"
    assert vr.main(["--db", str(scratch_db), "--export", str(out)]) == 1
    txt = capsys.readouterr().out
    assert "[FAIL] sha256sums" in txt and "FAIL:" in txt
    assert vr.main(["--db", str(scratch_db), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["pass"] is True


def test_gold_rule_detects_bad_gold(vr, orch_env, scratch_db):
    sq = importlib.import_module("orchestrator.storage.sqlite_store")
    st = sq.SQLiteStore()
    st.conn.execute("UPDATE findings SET label='gold' WHERE id=(SELECT MIN(id) FROM findings)")   # 1 tool rẻ -> gold sai
    st.conn.execute("INSERT INTO expensive_runs (commit_id,tool,phase,status) VALUES ('x','t','analyze','failed')")
    st.conn.commit()
    st.close()
    c = _by_id(vr.run(scratch_db))
    assert c["gold_rule_v1"]["status"] == "FAIL" and "1 cụm gold" in c["gold_rule_v1"]["detail"]
    assert c["expensive_status_enum"]["status"] == "FAIL" and "failed" in c["expensive_status_enum"]["detail"]
