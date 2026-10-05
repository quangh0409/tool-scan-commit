"""Test kiểm tay mù (review.py) — scratch DB + cụm gold/verified-clean chèn thẳng. Không Docker/git."""
from __future__ import annotations

import importlib
import json

import pytest

REPO = "https://github.com/FudanSELab/train-ticket"
CLEAN = "4a9599f4a5b38ce56ae7b7f29a7da9beec87ed11"
CLEAN2 = "9bdd9a28f0033e91dec4595d257da81cc7016e47"
NEG3 = "b" * 40
GOLD_COMMIT = "a" * 40


def _m(name):
    return importlib.import_module(name)


def _store(**kw):
    return _m("orchestrator.storage.sqlite_store").SQLiteStore(**kw)


def _gold_row(st, file_path, s_line, cwe, group, tier, tools):
    st.conn.execute(
        "INSERT INTO findings (repo,commit_id,file_path,s_line,e_line,s_detail_line,finding_in_diff,"
        "tool,rule_id,cwe,cwe_group,category,tier,label,agreeing_tools,n_tools_agree,n_tools_ran,"
        "n_expensive,n_cheap,diff_parsed,code_snippet,code_after_url) VALUES (?,?,?,?,?,?,1,?,?,?,?,'code',?,"
        "'gold',?,?,3,?,?,?,?,?)",
        [REPO, GOLD_COMMIT, file_path, s_line, s_line, json.dumps([s_line]), tools[0], "java:S2077",
         json.dumps([cwe]), group, tier, json.dumps(tools), len(tools),
         sum(t in ("findsecbugs", "sonar", "codeql") for t in tools),
         sum(t not in ("findsecbugs", "sonar", "codeql") for t in tools),
         json.dumps({"added": [[s_line - 10, "int a = 0;"], [s_line, "stmt.execute(\"SELECT \" + q);"],
                               [s_line + 2, "return a;"], [s_line + 30, "far();"]],
                     "deleted": [[s_line, "// old"]]}),
         None, f"{REPO}/blob/{GOLD_COMMIT}/{file_path}"])


def _seed_db(st):
    """10 cụm gold: xss|expensive ×6, sql_injection|mixed ×3, csrf|expensive ×1; 3 commit verified-clean."""
    for i in range(6):
        _gold_row(st, f"svc/X{i}.java", 100 + 20 * i, "CWE-79", "xss", "expensive", ["findsecbugs", "sonar"])
    for i in range(3):
        _gold_row(st, f"svc/S{i}.java", 50 + 20 * i, "CWE-89", "sql_injection", "mixed", ["sonar", "semgrep"])
    _gold_row(st, "svc/C.java", 7, "CWE-352", "csrf", "expensive", ["codeql", "findsecbugs"])
    st.conn.execute(
        "INSERT INTO raw_findings (repo,commit_id,tool,tier,file_path,s_line,cwe,rule_id,severity,message) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        [REPO, GOLD_COMMIT, "sonar", "expensive", "svc/C.java", 8, '["CWE-352"]', "java:S4502",
         "HIGH", "SonarQube rule java:S4502: Disabling CSRF protections is security-sensitive (FindSecBugs agrees)"])
    st.conn.commit()
    sel = [{"commit_id": c, "role": "clean", "selection_reason": "t", "suspect_categories": [],
            "n_suspect_findings": 0, "created_at": "2026-10-05"} for c in (CLEAN, CLEAN2, NEG3)]
    st.add_selected(sel)
    for c in (CLEAN, CLEAN2, NEG3):
        for t in ("findsecbugs", "sonar"):
            st.insert_expensive_run({"commit_id": c, "tool": t, "phase": "analyze", "status": "ok",
                                     "n_findings": 0, "duration_sec": 1})
        st.update_n_expensive_ok(c)


@pytest.fixture
def rv(orch_env):
    return _m("orchestrator.review")


# ---------------------------------------------------------------- hàm thống kê
def test_wilson_and_kappa_hand_values(rv):
    p, lo, hi = rv.wilson(3, 4)
    assert p == 0.75 and abs(lo - 0.3006) < 1e-3 and abs(hi - 0.9544) < 1e-3
    assert rv.wilson(0, 0) == (None, None, None)
    p, lo, hi = rv.wilson(10, 10)
    assert p == 1.0 and abs(lo - 0.7225) < 1e-3 and abs(hi - 1.0) < 1e-9
    pairs = [("TP", "TP"), ("TP", "TP"), ("TP", "FP"), ("FP", "FP"), ("unclear", "unclear")]
    assert abs(rv.cohen_kappa(pairs) - 0.6875) < 1e-9          # po=.8, pe=.36
    assert rv.cohen_kappa([]) is None
    assert rv.cohen_kappa([("TP", "TP")] * 3) == 1.0


def test_allocate(rv):
    assert rv.allocate({"a": 6, "b": 3, "c": 1}, 5) == {"a": 3, "b": 1, "c": 1}
    assert rv.allocate({"a": 6, "b": 3, "c": 1}, 100) == {"a": 6, "b": 3, "c": 1}   # clamp
    assert sum(rv.allocate({"a": 10, "b": 10, "c": 10}, 1).values()) == 1
    assert rv.allocate({"a": 4, "b": 0}, 2) == {"a": 2, "b": 0}
    assert rv.allocate({}, 5) == {}


def test_validation_of_priority(rv):
    assert rv.validation_of(None) == "unreviewed"
    assert rv.validation_of([("r1", "TP")]) == "TP"
    assert rv.validation_of([("r1", "TP"), ("r2", "FP")]) == "unclear"                 # hoà
    assert rv.validation_of([("r1", "TP"), ("r2", "TP"), ("r3", "FP")]) == "TP"        # đa số
    assert rv.validation_of([("r1", "TP"), ("r2", "TP"), ("adjudicated", "FP")]) == "FP"


# ---------------------------------------------------------------- sample
def test_sample_empty_on_scratch(rv, orch_env):
    st = _store()
    try:
        res = rv.sample(st, seed=1, n_pos=200, n_neg=100)
        assert res["n_pos"] == 0 and res["n_neg"] == 0
        assert res["strata"] == [{"stratum": "verified-clean", "kind": "neg", "n": 0, "total": 0}]
        assert res["sample_id"].startswith("s-1-")
        assert rv.next_item(st, res["sample_id"], "r1") is None
    finally:
        st.close()


def test_sample_stratified_and_reproducible(rv, orch_env):
    st = _store()
    try:
        _seed_db(st)
        assert len(st.verified_clean_commits()) == 3
        r1 = rv.sample(st, seed=42, n_pos=5, n_neg=2, sample_id="s1")
        assert r1["n_pos"] == 5 and r1["n_neg"] == 2
        strata = {s["stratum"]: s for s in r1["strata"]}
        assert strata["xss|expensive"]["n"] == 3 and strata["xss|expensive"]["total"] == 6
        assert strata["sql_injection|mixed"]["n"] == 1
        assert strata["csrf|expensive"]["n"] == 1                      # tầng nhỏ vẫn ≥1
        assert strata["verified-clean"] == {"stratum": "verified-clean", "kind": "neg", "n": 2, "total": 3}
        rows1 = st.gold_sample_rows("s1")
        assert len(rows1) == 7 and all(len(r["cluster_key"]) == 32 for r in rows1 if r["kind"] == "pos")
        assert all(r["cluster_key"].startswith("neg:") for r in rows1 if r["kind"] == "neg")
        # cùng seed -> cùng mẫu (ghi đè idempotent); seed khác -> khác
        rv.sample(st, seed=42, n_pos=5, n_neg=2, sample_id="s1")
        assert [r["cluster_key"] for r in st.gold_sample_rows("s1")] == [r["cluster_key"] for r in rows1]
        rv.sample(st, seed=7, n_pos=5, n_neg=2, sample_id="s2")
        assert {r["cluster_key"] for r in st.gold_sample_rows("s2")} != {r["cluster_key"] for r in rows1}
        # clamp: xin nhiều hơn số có
        r3 = rv.sample(st, seed=1, n_pos=999, n_neg=999, sample_id="s3")
        assert r3["n_pos"] == 10 and r3["n_neg"] == 3
        assert [s["sample_id"] for s in st.gold_sample_ids()] == ["s1", "s2", "s3"]
    finally:
        st.close()


# ---------------------------------------------------------------- next_item mù + verdict
def test_next_item_is_blind_and_verdict_flow(rv, orch_env):
    st = _store()
    try:
        _seed_db(st)
        rv.sample(st, seed=42, n_pos=10, n_neg=1, sample_id="s")
        it = rv.next_item(st, "s", "alice")
        assert it["kind"] == "pos" and it["remaining"] == 11 and it["sample_id"] == "s"
        for forbidden in ("label", "tools", "agreeing_tools", "n_tools_agree", "n_expensive", "n_cheap",
                          "tier", "tool", "rule_id", "silver_label", "evidence"):
            assert forbidden not in it, forbidden
        assert set(it["cwe_claim"]) == {"cwe", "group", "category"} and it["cwe_claim"]["group"]
        assert it["code_lines"] and all(set(c) == {"n", "text", "flag"} for c in it["code_lines"])
        assert all(abs(c["n"] - it["s_line"]) <= 8 for c in it["code_lines"])        # ±8 dòng
        assert any(c["flag"] for c in it["code_lines"])
        kinds = {d["kind"] for d in it["diff_lines"]}
        assert kinds <= {"ctx", "add", "del", "flag"} and "del" in kinds and "flag" in kinds
        # mục csrf có message: tên tool + rule id đã xoá
        pend = [r for r in st.gold_sample_rows("s") if r["stratum"] == "csrf|expensive"][0]
        idx = rv._index(st)
        row = idx[pend["cluster_key"]]
        item_c = rv._item_pos(st, row, 3)
        assert item_c["messages_anon"], item_c
        m = item_c["messages_anon"][0].lower()
        assert "sonar" not in m and "findsecbugs" not in m and "s4502" not in m and "[tool]" in m

        # verdict + remaining; rater khác không bị ảnh hưởng
        r = rv.verdict(st, "s", "alice", it["cluster_key"], "TP", "ok")
        assert r == {"ok": True, "remaining": 10}
        assert rv.next_item(st, "bob", "bob") is None                   # mẫu không tồn tại -> None
        assert rv.next_item(st, "s", "bob")["remaining"] == 11
        assert rv.next_item(st, "s", "alice")["cluster_key"] != it["cluster_key"]
        # upsert ghi đè
        rv.verdict(st, "s", "alice", it["cluster_key"], "FP")
        rows = [x for x in st.gold_review_rows("s") if x["rater"] == "alice"]
        assert len(rows) == 1 and rows[0]["verdict"] == "FP"
        with pytest.raises(ValueError):
            rv.verdict(st, "s", "alice", it["cluster_key"], "maybe")
        with pytest.raises(ValueError):
            rv.verdict(st, "s", "alice", "deadbeef", "TP")
        # neg item cuối: mù, có danh sách file + url
        for _ in range(10):
            nx = rv.next_item(st, "s", "carol")
            rv.verdict(st, "s", "carol", nx["cluster_key"], "TP")
        neg = rv.next_item(st, "s", "carol")
        assert neg["kind"] == "neg" and neg["cluster_key"].startswith("neg:") and neg["remaining"] == 1
        assert "files" in neg and neg["cwe_claim"]["cwe"] == []
        # map lại sau relabel: xoá + chèn lại findings (id đổi) -> cluster_key vẫn tìm thấy
        st.conn.execute("DELETE FROM findings WHERE commit_id=?", [GOLD_COMMIT])
        st.conn.commit()
        for i in range(6):
            _gold_row(st, f"svc/X{i}.java", 100 + 20 * i, "CWE-79", "xss", "expensive", ["findsecbugs", "sonar"])
        for i in range(3):
            _gold_row(st, f"svc/S{i}.java", 50 + 20 * i, "CWE-89", "sql_injection", "mixed", ["sonar", "semgrep"])
        _gold_row(st, "svc/C.java", 7, "CWE-352", "csrf", "expensive", ["codeql", "findsecbugs"])
        st.conn.commit()
        assert rv.next_item(st, "s", "dave")["kind"] == "pos"
    finally:
        st.close()


# ---------------------------------------------------------------- close
def test_close_two_raters_kappa_wilson_adjudicated(rv, orch_env):
    st = _store()
    try:
        _seed_db(st)
        rv.sample(st, seed=42, n_pos=5, n_neg=2, sample_id="s")
        pos = [r["cluster_key"] for r in st.gold_sample_rows("s") if r["kind"] == "pos"]
        neg = [r["cluster_key"] for r in st.gold_sample_rows("s") if r["kind"] == "neg"]
        a = ["TP", "TP", "TP", "FP", "unclear"]
        b = ["TP", "TP", "FP", "FP", "unclear"]
        for ck, va, vb in zip(pos, a, b):
            rv.verdict(st, "s", "ann", ck, va)
            rv.verdict(st, "s", "ben", ck, vb)
        rv.verdict(st, "s", "ann", neg[0], "TP")
        rv.verdict(st, "s", "ann", neg[1], "FP", "commit này thực ra có SQLi")

        res = rv.close(st, "s")
        pr = res["precision"]
        assert (pr["tp"], pr["fp"], pr["unclear"], pr["n"], pr["n_reviewed"]) == (3, 1, 1, 4, 5)
        assert pr["point"] == 0.75 and abs(pr["ci_low"] - 0.3006) < 1e-3 and abs(pr["ci_high"] - 0.9544) < 1e-3
        assert res["neg_precision"]["point"] == 0.5 and res["neg_precision"]["n"] == 2
        assert res["kappa_raters"] == {"value": 0.6875, "n": 5, "raters": ["ann", "ben"]}
        assert len(res["disagreements"]) == 1 and res["disagreements"][0]["cluster_key"] == pos[2]
        assert res["disagreements"][0]["verdicts"] == {"ann": "TP", "ben": "FP"}
        assert res["primary_rater"] == "ann" and res["raters"] == ["ann", "ben"]
        assert {s["stratum"] for s in res["by_stratum"]} == {"xss|expensive", "sql_injection|mixed",
                                                             "csrf|expensive", "verified-clean"}
        assert sum(s["n_sample"] for s in res["by_stratum"]) == 7
        assert res["unreviewed"] == 0
        # --raters đảo thứ tự -> precision theo ben
        res_b = rv.close(st, "s", raters=["ben", "ann"])
        assert res_b["precision"]["tp"] == 2 and res_b["precision"]["point"] == 0.5
        # adjudicated thắng trên mục bất đồng, không tính vào κ
        rv.verdict(st, "s", "adjudicated", pos[2], "FP", "hoà giải")
        res2 = rv.close(st, "s")
        assert res2["n_adjudicated"] == 1
        assert (res2["precision"]["tp"], res2["precision"]["fp"]) == (2, 2)
        assert res2["kappa_raters"]["raters"] == ["ann", "ben"] and res2["kappa_raters"]["n"] == 5
        # export: evidence.validation ưu tiên adjudicated
        exp = _m("orchestrator.export_dataset")
        out = exp.export_all(st, orch_env / "exp")
        rows = [json.loads(l) for l in (orch_env / "exp" / "dataset.jsonl").read_text(encoding="utf-8").splitlines()]
        v = {r["cluster_key"]: r["evidence"]["validation"] for r in rows}
        assert v[pos[2]] == "FP" and v[pos[0]] == "TP" and v[pos[4]] == "unclear"
        assert out["counts"]["gold"] == 10
        # summary cho README/stats
        sm = rv.summary(st)
        assert len(sm) == 1 and sm[0]["sample_id"] == "s" and sm[0]["precision"]["n"] == 4
        with pytest.raises(ValueError):
            rv.close(st, "khong-co")
    finally:
        st.close()


def test_cli_main(rv, orch_env, scratch_db, capsys):
    st = _store()
    _seed_db(st)
    st.close()
    db = str(scratch_db)
    assert rv.main(["sample", "--db", db, "--seed", "3", "--n-pos", "4", "--n-neg", "1",
                    "--sample-id", "cli", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["n_pos"] == 4 and out["n_neg"] == 1
    assert rv.main(["next", "--db", db, "--sample-id", "cli", "--rater", "r"]) == 0
    item = json.loads(capsys.readouterr().out)
    assert item["remaining"] == 5 and "label" not in item
    assert rv.main(["verdict", "--db", db, "--sample-id", "cli", "--rater", "r",
                    "--cluster-key", item["cluster_key"], "--verdict", "TP"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True, "remaining": 4}
    assert rv.main(["verdict", "--db", db, "--sample-id", "cli", "--rater", "r",
                    "--cluster-key", "xx", "--verdict", "TP", "--json"]) == 1
    assert "bad_request" in capsys.readouterr().err
    assert rv.main(["close", "--db", db, "--sample-id", "cli"]) == 0
    assert json.loads(capsys.readouterr().out)["precision"]["tp"] == 1
    assert rv.main(["list", "--db", db]) == 0
    assert json.loads(capsys.readouterr().out)["samples"][0]["sample_id"] == "cli"
