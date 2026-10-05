#!/usr/bin/env python3
"""Kiểm một run có đúng CONTRACTS không (nghiệm thu Run A/B). Stdlib-only, DB mở CHỈ ĐỌC.

  PYTHONPATH=src python scripts/verify_run.py --db DB [--export DIR] [--json]

Mỗi mục in PASS/FAIL/SKIP + chi tiết. Exit 0 nếu không có FAIL, 1 nếu có FAIL.
Mục kiểm (CONTRACTS §1/§4/§6, RULE_GAN_NHAN §4):
  user_version=2 · run_meta scan/analyze (tools_json có digest mọi tool đắt đã dùng, orchestrator_git_sha)
  · expensive_runs.status ∈ enum §1 · selected_commits không còn building/analyzing · n_expensive_ok khớp đếm lại
  · verified-clean ⇔ n_expensive_ok>=2 · findings có cwe_group, label ∈ gold/silver/candidate, label tính lại từ
  agreeing_tools theo luật v1 · kappa có total · export: manifest đủ khoá + counts khớp DB, dataset.jsonl có
  cluster_key/evidence và số dòng = số cụm, commits.jsonl có n_expensive_ok/negative_level khớp DB, SHA256SUMS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

STATUS_ENUM = {"ok", "skipped", "build_failed", "infra_error", "tool_timeout", "tool_error"}
LABELS = {"gold", "silver", "candidate"}
EXPENSIVE_TOOLS = {"codeql", "findsecbugs", "sonar"}
MANIFEST_KEYS = ["profile", "run_meta", "kappa", "counts", "build_failed", "infra_error", "tool_timeout",
                 "skipped", "orchestrator_git_sha", "app_version", "os", "docker_version", "started", "finished",
                 "params_v1", "experiment", "tool_error", "python", "db", "export_dir", "run_id"]
COUNT_KEYS = ["gold", "silver", "candidate", "verified_clean", "cheap_clean"]
V1 = {"gold_min_expensive": 2, "gold_allow_1exp_1cheap": 1, "silver_min_cheap": 2}


class Report:
    def __init__(self):
        self.checks: list[dict] = []

    def add(self, cid: str, ok: bool | None, detail: str = "") -> None:
        self.checks.append({"id": cid, "status": "SKIP" if ok is None else ("PASS" if ok else "FAIL"),
                            "detail": detail})

    @property
    def failed(self) -> list[dict]:
        return [c for c in self.checks if c["status"] == "FAIL"]


def _cols(con, table: str) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def _tables(con) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _loads(v, default):
    try:
        return json.loads(v) if isinstance(v, str) else (v if v is not None else default)
    except ValueError:
        return default


def label_v1(E: int, C: int, p: dict) -> str:
    if E >= p["gold_min_expensive"]:
        return "gold"
    if p["gold_allow_1exp_1cheap"] and E >= 1 and C >= 1:
        return "gold"
    if E >= 1 or C >= p["silver_min_cheap"]:
        return "silver"
    return "candidate"


def _n_ok(con, cid: str) -> int:
    return con.execute(
        "SELECT COUNT(DISTINCT tool) FROM expensive_runs WHERE commit_id=? AND phase='analyze' "
        "AND status='ok' AND tool NOT IN ('-','maven')", [cid]).fetchone()[0]


def _has_in_diff(con, cid: str) -> bool:
    return con.execute("SELECT 1 FROM findings WHERE commit_id=? AND finding_in_diff=1 LIMIT 1",
                       [cid]).fetchone() is not None


def _negative_level(con, cid: str) -> str | None:
    if _has_in_diff(con, cid):
        return None
    return "verified-clean" if _n_ok(con, cid) >= 2 else "cheap-clean"


def _all_commit_ids(con) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT commit_id FROM raw_findings UNION SELECT commit_id FROM findings "
        "UNION SELECT commit_id FROM raw_output") if r[0]]


def verify_db(con, rep: Report, params: dict) -> None:
    tables = _tables(con)
    ver = con.execute("PRAGMA user_version").fetchone()[0]
    rep.add("user_version", ver == 2, f"PRAGMA user_version={ver} (cần 2)")

    # --- run_meta ---
    rm_cols = _cols(con, "run_meta") if "run_meta" in tables else set()
    if "tier" not in rm_cols:
        rep.add("run_meta_scan", False, "run_meta chưa ở schema v2 (thiếu cột tier/run_id)")
        rep.add("run_meta_analyze", False, "run_meta chưa ở schema v2")
    else:
        n_scan = con.execute("SELECT COUNT(*) FROM run_meta WHERE tier='scan'").fetchone()[0]
        rep.add("run_meta_scan", n_scan >= 1, f"{n_scan} hàng tier=scan")
        used = {r[0] for r in con.execute(
            "SELECT DISTINCT tool FROM expensive_runs WHERE phase='analyze' AND status='ok'")} & EXPENSIVE_TOOLS
        rows = con.execute("SELECT tools_json, orchestrator_git_sha FROM run_meta WHERE tier='analyze' "
                           "ORDER BY id DESC").fetchall()
        if not used and not rows:
            rep.add("run_meta_analyze", None, "chưa chạy tầng đắt")
        elif not rows:
            rep.add("run_meta_analyze", False, f"tool đắt đã chạy {sorted(used)} nhưng không có run_meta tier=analyze")
        else:
            tools = _loads(rows[0][0], []) or []
            with_digest = {t.get("name") for t in tools if t.get("digest")}
            missing = sorted(used - with_digest)
            sha_ok = bool(rows[0][1]) and re.fullmatch(r"[0-9a-f]{7,40}", str(rows[0][1])) is not None
            rep.add("run_meta_analyze", not missing and sha_ok,
                    f"{len(rows)} hàng analyze; thiếu digest: {missing or 'không'}; "
                    f"orchestrator_git_sha={'ok' if sha_ok else rows[0][1]!r}")

    # --- expensive_runs.status ---
    bad = [r for r in con.execute("SELECT status, COUNT(*) FROM expensive_runs GROUP BY status")
           if r[0] not in STATUS_ENUM]
    rep.add("expensive_status_enum", not bad,
            f"status ngoài enum §1: {dict(bad)}" if bad else "mọi status ∈ enum §1")

    # --- selected_commits ---
    stuck = dict(con.execute("SELECT status, COUNT(*) FROM selected_commits "
                             "WHERE status IN ('building','analyzing') GROUP BY status").fetchall())
    rep.add("selected_no_stuck", not stuck, f"còn claim treo: {stuck}" if stuck else "không còn building/analyzing")
    sel_cols = _cols(con, "selected_commits")
    if "n_expensive_ok" not in sel_cols:
        rep.add("n_expensive_ok_recount", False, "thiếu cột selected_commits.n_expensive_ok (user_version<2)")
        sel = {r[0]: None for r in con.execute("SELECT commit_id FROM selected_commits")}
    else:
        sel = dict(con.execute("SELECT commit_id, n_expensive_ok FROM selected_commits").fetchall())
        mism = [(c, v, _n_ok(con, c)) for c, v in sel.items() if (v or 0) != _n_ok(con, c)]
        rep.add("n_expensive_ok_recount", not mism,
                f"{len(mism)} commit lệch (commit, cột, đếm lại): {mism[:5]}" if mism else
                f"{len(sel)} commit khớp đếm lại từ expensive_runs")
    bad_neg = []
    for c in sel:
        n = _n_ok(con, c)
        lvl = _negative_level(con, c)
        if lvl is not None and (lvl == "verified-clean") != (n >= 2):
            bad_neg.append((c[:12], lvl, n))
    rep.add("verified_clean_rule", not bad_neg,
            f"vi phạm verified-clean ⇔ n_expensive_ok>=2: {bad_neg[:5]}" if bad_neg else
            "verified-clean ⇔ n_expensive_ok>=2 trên mọi commit đã chọn")

    # --- findings ---
    n_find = con.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
    no_grp = con.execute("SELECT COUNT(*) FROM findings WHERE cwe_group IS NULL OR cwe_group=''").fetchone()[0]
    rep.add("findings_cwe_group", no_grp == 0, f"{no_grp}/{n_find} cụm thiếu cwe_group")
    bad_lbl = dict(con.execute("SELECT COALESCE(label,'NULL'), COUNT(*) FROM findings "
                               "WHERE label IS NULL OR label NOT IN ('gold','silver','candidate') GROUP BY 1"))
    rep.add("findings_label_enum", not bad_lbl, f"label lạ: {bad_lbl}" if bad_lbl else f"{n_find} cụm, label hợp lệ")
    try:
        from orchestrator.consensus.tiers import tier_of
    except Exception:  # noqa: BLE001 — chạy không có src
        def tier_of(t):
            return "expensive" if t in EXPENSIVE_TOOLS else "cheap"
    mism_gold, mism_all = [], []
    for cid, fp, sl, lbl, tools in con.execute(
            "SELECT commit_id, file_path, s_line, label, agreeing_tools FROM findings"):
        ts = _loads(tools, []) or []
        E = sum(1 for t in set(ts) if tier_of(t) == "expensive")
        C = sum(1 for t in set(ts) if tier_of(t) != "expensive")
        exp = label_v1(E, C, params)
        if exp != lbl:
            mism_all.append((cid[:8], fp, sl, lbl, exp, ts))
            if lbl == "gold" or exp == "gold":
                mism_gold.append((cid[:8], fp, sl, lbl, exp, ts))
    rep.add("gold_rule_v1", not mism_gold,
            f"{len(mism_gold)} cụm gold sai luật v1 {params}: {mism_gold[:3]}" if mism_gold else
            f"mọi cụm gold thoả luật v1 {params}")
    rep.add("label_rule_v1", not mism_all,
            f"{len(mism_all)} cụm lệch nhãn tính lại: {mism_all[:3]}" if mism_all else "mọi nhãn khớp tính lại")

    # --- kappa ---
    if "kappa" not in tables:
        rep.add("kappa_total", False, "không có bảng kappa")
    else:
        n = con.execute("SELECT COUNT(*) FROM kappa WHERE scope='total'").fetchone()[0]
        rep.add("kappa_total", n >= 1, f"{n} hàng scope=total" if n else "chưa lưu κ total (chạy `kappa`)")


def verify_export(con, export: Path, rep: Report) -> None:
    man_p = export / "run_manifest.json"
    if not man_p.exists():
        rep.add("manifest_keys", False, f"thiếu {man_p}")
        return
    man = json.loads(man_p.read_text(encoding="utf-8"))
    missing = [k for k in MANIFEST_KEYS if k not in man]
    rep.add("manifest_keys", not missing, f"thiếu khoá: {missing}" if missing else f"{len(MANIFEST_KEYS)} khoá đủ")

    labels = dict(con.execute("SELECT label, COUNT(*) FROM findings GROUP BY label").fetchall())
    neg = {"verified-clean": 0, "cheap-clean": 0}
    for cid in _all_commit_ids(con):
        lvl = _negative_level(con, cid)
        if lvl:
            neg[lvl] += 1
    want = {"gold": labels.get("gold", 0), "silver": labels.get("silver", 0),
            "candidate": labels.get("candidate", 0),
            "verified_clean": neg["verified-clean"], "cheap_clean": neg["cheap-clean"]}
    got = {k: (man.get("counts") or {}).get(k) for k in COUNT_KEYS}
    rep.add("manifest_counts", got == want, f"manifest={got} db={want}")

    ds = export / "dataset.jsonl"
    if not ds.exists():
        rep.add("dataset_rows", False, "thiếu dataset.jsonl")
    else:
        rows = [json.loads(l) for l in ds.read_text(encoding="utf-8").splitlines() if l.strip()]
        n_find = con.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
        bad = [i for i, r in enumerate(rows)
               if not re.fullmatch(r"[0-9a-f]{32}", str(r.get("cluster_key") or ""))
               or not isinstance(r.get("evidence"), dict)
               or r["evidence"].get("consensus") not in LABELS
               or r["evidence"].get("validation") not in ("unreviewed", "TP", "FP", "unclear")]
        rep.add("dataset_rows", len(rows) == n_find and not bad,
                f"{len(rows)} dòng vs {n_find} cụm findings; dòng thiếu cluster_key/evidence: {len(bad)}")

    cm = export / "commits.jsonl"
    if not cm.exists():
        rep.add("commits_rows", False, "thiếu commits.jsonl")
    else:
        rows = [json.loads(l) for l in cm.read_text(encoding="utf-8").splitlines() if l.strip()]
        bad_key = [r.get("commit_id") for r in rows if "n_expensive_ok" not in r or "negative_level" not in r]
        bad_val = [r["commit_id"][:8] for r in rows if "commit_id" in r and "n_expensive_ok" in r
                   and (r["n_expensive_ok"] != _n_ok(con, r["commit_id"])
                        or r["negative_level"] != _negative_level(con, r["commit_id"]))]
        rep.add("commits_rows", not bad_key and not bad_val and rows,
                f"{len(rows)} dòng; thiếu khoá: {len(bad_key)}; lệch DB: {bad_val[:5]}")

    sums = export / "SHA256SUMS"
    if not sums.exists():
        rep.add("sha256sums", False, "thiếu SHA256SUMS")
    else:
        bad = []
        n = 0
        for line in sums.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            h, name = line.split("  ", 1)
            n += 1
            f = export / name.strip()
            if not f.exists() or hashlib.sha256(f.read_bytes()).hexdigest() != h.strip():
                bad.append(name.strip())
        rep.add("sha256sums", n >= 3 and not bad, f"{n} mục; sai/thiếu: {bad}" if bad else f"{n} mục khớp")


def run(db: Path, export: Path | None = None, params: dict | None = None) -> dict:
    rep = Report()
    uri = f"{Path(db).resolve().as_uri()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        p = dict(V1)
        if export and (export / "run_manifest.json").exists():
            try:
                pv = json.loads((export / "run_manifest.json").read_text(encoding="utf-8")).get("params_v1") or {}
                p.update({k: pv[k] for k in V1 if k in pv})
            except ValueError:
                pass
        if params:
            p.update(params)
        verify_db(con, rep, p)
        if export:
            verify_export(con, Path(export), rep)
    finally:
        con.close()
    return {"db": str(db), "export": str(export) if export else None, "checks": rep.checks,
            "n_fail": len(rep.failed), "pass": not rep.failed}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--export", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not Path(a.db).exists():
        print(f"không thấy DB {a.db}", file=sys.stderr)
        return 1
    res = run(Path(a.db), Path(a.export) if a.export else None)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        for c in res["checks"]:
            print(f"[{c['status']}] {c['id']:24} {c['detail']}")
        print(f"\n{'PASS' if res['pass'] else 'FAIL'}: {res['n_fail']} mục lỗi / {len(res['checks'])} mục")
    return 0 if res["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
