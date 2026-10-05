"""API Results (CONTRACTS §9 + §12): overview / findings / finding / commits / export / raw / open / features / relabel.

Hàm thuần `fn(params, body) -> dict`, lỗi → ApiError. Đọc DB CHỈ-ĐỌC (`file:…?mode=ro`); chỉ `export`
mở ghi (SQLiteStore → migrate + lock; 409 nếu run đang ghi). run_id → registry → db/export/profile.

Bảng route → hàm (A4 map):
  GET  /api/results/{id}/overview                 overview
  GET  /api/results/{id}/findings?…               findings
  GET  /api/results/{id}/finding/{cluster_key}    finding
  GET  /api/results/{id}/commits?page=&size=      commits
  POST /api/results/{id}/export {formats}         export
  GET  /api/results/{id}/raw?path=                raw        (trả {content, content_type}; 404)
  POST /api/open {path}                           open_path  (501 nếu không hỗ trợ)
  POST /api/results/{id}/features                 features   (chạy nền `cli features`)
  POST /api/results/{id}/relabel                  relabel    (chỉ experiment; 501 nếu không)
"""
from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
import subprocess
import sys
from collections import Counter
from pathlib import Path

from . import api_common as C
from .errors import ApiError, bad_request, not_found, not_supported

LABELS = ("gold", "silver", "candidate")
TIERS = ("cheap", "expensive", "mixed")
FORMATS = ("jsonl", "csv", "latex")
RAW_RE = re.compile(r"^([0-9a-f]{7,40})/([A-Za-z0-9_-]+)\.raw\.([A-Za-z0-9]+)$")
CONTENT_TYPES = {"json": "application/json", "sarif": "application/json", "xml": "application/xml",
                 "jsonl": "application/x-ndjson", "txt": "text/plain", "log": "text/plain", "csv": "text/csv"}


# ----------------------------------------------------------------------------- helpers
def _ctx(params: dict) -> tuple[str, dict, Path]:
    """(run_id, run, db). `params.db` (đường dẫn) được chấp nhận khi run không có trong registry (test/CLI)."""
    rid = C.require_run_id(params)
    try:
        run = C.find_run(rid)
    except ApiError:
        if params.get("db"):
            run = {"run_id": rid, "db": params["db"], "export": params.get("export", ""), "work": params.get("work", ""),
                   "profile": params.get("profile", ""), "status": "done"}
        else:
            raise
    return rid, run, C.run_db(run)


def _validation(verdicts: list[str] | None) -> str:
    if not verdicts:
        return "unreviewed"
    c = Counter(verdicts).most_common()
    if len(c) > 1 and c[0][1] == c[1][1]:
        return "unclear"
    return c[0][0]


def _reviews(conn: sqlite3.Connection, tabs: set[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if "gold_review" in tabs:
        for ck, v in conn.execute("SELECT cluster_key, verdict FROM gold_review WHERE rater != 'adjudicated'"):
            out.setdefault(ck, []).append(v)
        # phán quyết cuối (adjudicated) ghi đè
        for ck, v in conn.execute("SELECT cluster_key, verdict FROM gold_review WHERE rater = 'adjudicated'"):
            out[ck] = [v]
    return out


def _key(row: sqlite3.Row | dict, w: int) -> str:
    C.ensure_src_on_path()
    from orchestrator import keys
    g = row["cwe_group"] if "cwe_group" in row.keys() else None
    return keys.cluster_key(row["repo"] or "", row["commit_id"] or "", row["file_path"] or "", g or "",
                            int(row["s_line"] or 0), line_window=w)


def _row_out(r: sqlite3.Row, w: int, reviews: dict) -> dict:
    ck = _key(r, w)
    keys_ = r.keys()
    label = (r["label"] if "label" in keys_ else None) or (r["silver_label"] if "silver_label" in keys_ else None) or "candidate"
    return {
        "cluster_key": ck,
        "commit": r["commit_id"],
        "date": r["author_date"] if "author_date" in keys_ else None,
        "file_path": r["file_path"],
        "s_line": r["s_line"],
        "cwe_group": r["cwe_group"] if "cwe_group" in keys_ else None,
        "category": r["category"] if "category" in keys_ else None,
        "cwe": C.jload(r["cwe"], []) or [],
        "tools": C.jload(r["agreeing_tools"], []) if "agreeing_tools" in keys_ else [],
        "n_agree": r["n_tools_agree"] if "n_tools_agree" in keys_ else None,
        "tier": r["tier"] if "tier" in keys_ else "cheap",
        "label": label,
        "evidence": {"consensus": label, "validation": _validation(reviews.get(ck))},
        "in_diff": r["finding_in_diff"] if "finding_in_diff" in keys_ else None,
        "rule_id": r["rule_id"] if "rule_id" in keys_ else None,
        "severity": r["severity"] if "severity" in keys_ else None,
        "id": r["id"],
    }


_LIGHT_COLS = ("id", "repo", "commit_id", "author_date", "file_path", "s_line", "cwe", "cwe_group", "category",
               "agreeing_tools", "n_tools_agree", "tier", "label", "silver_label", "finding_in_diff", "rule_id", "severity")


def _light_select(conn: sqlite3.Connection) -> str:
    have = C.columns(conn, "findings")
    cols = [c for c in _LIGHT_COLS if c in have]
    return "SELECT " + ", ".join(cols) + " FROM findings"


# ----------------------------------------------------------------------------- overview
def overview(params: dict, body: dict | None = None) -> dict:
    rid, run, db = _ctx(params)
    C.ensure_src_on_path()
    prof = C.load_run_profile(run)
    with C.profile_env(prof):
        from orchestrator import stats
        try:
            ov = stats.overview(db, run_id=rid)
        except ValueError as e:
            raise not_found(f"kết quả của run {rid!r}", str(e)) from e
        except sqlite3.Error as e:
            raise ApiError(503, "EDB", f"Lỗi đọc DB: {e}") from e
    with C.ro_conn(db) as conn:
        tabs = C.tables(conn)
        ov["raw_by_tool"] = dict(conn.execute("SELECT tool, COUNT(*) FROM raw_findings GROUP BY tool ORDER BY 2 DESC")) \
            if "raw_findings" in tabs else {}
        ov["relabeled"] = _relabeled(conn, tabs)
    ov["run_id"] = rid
    ov["status"] = run.get("status")
    return ov


def _relabeled(conn: sqlite3.Connection, tabs: set[str]) -> bool:
    """Có run_meta tier=analyze đã finished, hoặc có findings label khác candidate."""
    if "run_meta" in tabs and {"tier", "finished_at"} <= C.columns(conn, "run_meta"):
        r = conn.execute("SELECT 1 FROM run_meta WHERE tier='analyze' AND finished_at IS NOT NULL LIMIT 1").fetchone()
        if r:
            return True
    if "findings" in tabs and "label" in C.columns(conn, "findings"):
        r = conn.execute("SELECT 1 FROM findings WHERE label IN ('gold','silver') LIMIT 1").fetchone()
        if r:
            return True
    return False


# ----------------------------------------------------------------------------- findings
def findings(params: dict, body: dict | None = None) -> dict:
    rid, run, db = _ctx(params)
    page = C.to_int(params.get("page"), 1, lo=1, name="page")
    size = C.to_int(params.get("size"), 20, lo=1, hi=500, name="size")
    label = (params.get("label") or "").strip()
    if label and label not in LABELS:
        raise bad_request(f"label phải thuộc {LABELS}")
    tier = (params.get("tier") or "").strip()
    if tier and tier not in TIERS:
        raise bad_request(f"tier phải thuộc {TIERS}")
    cwe_group = (params.get("cwe_group") or "").strip()
    min_tools = C.to_int(params.get("min_tools"), None, lo=1, name="min_tools")
    in_diff = params.get("in_diff")
    q = (params.get("q") or "").strip()

    with C.ro_conn(db) as conn:
        tabs = C.tables(conn)
        if "findings" not in tabs:
            raise not_found(f"bảng findings trong DB của run {rid!r}")
        have = C.columns(conn, "findings")
        where, args = [], []
        if label:
            col = "label" if "label" in have else "silver_label"
            where.append(f"COALESCE({col},'candidate') = ?"); args.append(label)
        if cwe_group and "cwe_group" in have:
            where.append("cwe_group = ?"); args.append(cwe_group)
        if min_tools is not None and "n_tools_agree" in have:
            where.append("COALESCE(n_tools_agree,1) >= ?"); args.append(min_tools)
        if tier and "tier" in have:
            where.append("COALESCE(tier,'cheap') = ?"); args.append(tier)
        if in_diff not in (None, "") and "finding_in_diff" in have:
            where.append("finding_in_diff = ?"); args.append(1 if C.to_bool(in_diff) else 0)
        if q:
            like = f"%{q}%"
            parts = ["file_path LIKE ?", "commit_id LIKE ?", "cwe LIKE ?"]
            args += [like, like, like]
            for c in ("rule_id", "cwe_group", "tool"):
                if c in have:
                    parts.append(f"{c} LIKE ?"); args.append(like)
            where.append("(" + " OR ".join(parts) + ")")
        wsql = (" WHERE " + " AND ".join(where)) if where else ""
        total = conn.execute(f"SELECT COUNT(*) FROM findings{wsql}", args).fetchone()[0]
        order = " ORDER BY " + ("author_date DESC, " if "author_date" in have else "") + "commit_id, file_path, s_line, id"
        rows = conn.execute(f"{_light_select(conn)}{wsql}{order} LIMIT ? OFFSET ?",
                            [*args, size, (page - 1) * size]).fetchall()
        w = C.line_window_of(run, conn)
        reviews = _reviews(conn, tabs)
        out = [_row_out(r, w, reviews) for r in rows]
    return {"total": int(total), "page": page, "size": size, "rows": out, "line_window": w}


# ----------------------------------------------------------------------------- finding (bằng chứng)
def finding(params: dict, body: dict | None = None) -> dict:
    rid, run, db = _ctx(params)
    ck = str(params.get("cluster_key") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{32}", ck):
        raise bad_request(f"cluster_key không hợp lệ: {ck!r}")
    with C.ro_conn(db) as conn:
        tabs = C.tables(conn)
        if "findings" not in tabs:
            raise not_found("bảng findings")
        w = C.line_window_of(run, conn)
        reviews = _reviews(conn, tabs)
        hit = None
        for r in conn.execute(_light_select(conn)):
            if _key(r, w) == ck:
                hit = r["id"]
                break
        if hit is None:
            raise not_found(f"cụm {ck}", "cluster_key có thể đổi sau relabel với W khác")
        full = conn.execute("SELECT * FROM findings WHERE id = ?", [hit]).fetchone()
        row = _row_out(full, w, reviews)
        keys_ = full.keys()
        row["kamei"] = C.jload(full["kamei"], None) if "kamei" in keys_ else None
        row["scan_tool_errors"] = _scan_tool_errors(conn, full["commit_id"]) if "scan_tool_errors" in tabs else []
        row["code_before_url"] = full["code_before_url"] if "code_before_url" in keys_ else None
        row["code_after_url"] = full["code_after_url"] if "code_after_url" in keys_ else None
        diff_lines = _diff_lines(full)
        tool_messages = _tool_messages(conn, tabs, full, w)
        prov = _provenance(conn, tabs, run, w)
        from orchestrator.consensus.tiers import eligible_tools
        cat = full["category"] if "category" in keys_ else None
        elig = sorted(eligible_tools(cat))
        denom = full["eligible"] if "eligible" in keys_ and full["eligible"] else len(elig)
    return {"row": row, "diff_lines": diff_lines, "tool_messages": tool_messages, "provenance": prov,
            "eligible": {"tools": elig, "denominator": int(denom or 0)}}


def _diff_lines(full: sqlite3.Row) -> list[dict]:
    keys_ = full.keys()
    dp = C.jload(full["diff_parsed"], {}) if "diff_parsed" in keys_ else {}
    dp = dp if isinstance(dp, dict) else {}
    flagged = set()
    detail = C.jload(full["s_detail_line"], []) if "s_detail_line" in keys_ else []
    for x in detail if isinstance(detail, list) else []:
        try:
            flagged.add(int(x))
        except (TypeError, ValueError):
            pass
    s_line = int(full["s_line"] or 0)
    flagged.add(s_line)
    out: list[dict] = []
    for item in dp.get("deleted") or []:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            out.append({"n": item[0], "kind": "del", "text": str(item[1]), "_o": 0})
    covered = False
    for item in dp.get("added") or []:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            try:
                n = int(item[0])
            except (TypeError, ValueError):
                n = item[0]
            kind = "flag" if n in flagged else "add"
            covered = covered or kind == "flag"
            out.append({"n": n, "kind": kind, "text": str(item[1]), "_o": 1})
    if not covered:
        snippet = (full["code_snippet"] if "code_snippet" in keys_ else None) or ""
        txt = snippet.strip().splitlines()[0] if snippet.strip() else "(dòng tool báo không nằm trong diff — in_diff=0 / nợ cũ)"
        out.append({"n": s_line, "kind": "flag", "text": txt, "_o": 2})

    def _k(d):
        try:
            return (int(d["n"]), d["_o"])
        except (TypeError, ValueError):
            return (10 ** 9, d["_o"])
    out.sort(key=_k)
    for d in out:
        d.pop("_o", None)
    return out


def _tool_messages(conn: sqlite3.Connection, tabs: set[str], full: sqlite3.Row, w: int) -> list[dict]:
    if "raw_findings" not in tabs:
        return []
    fmts: dict[str, str] = {}
    if "raw_output" in tabs:
        for tool, fmt in conn.execute("SELECT tool, fmt FROM raw_output WHERE commit_id = ?", [full["commit_id"]]):
            fmts[tool] = fmt
    seen = set()
    out = []
    for r in conn.execute(
            "SELECT tool, rule_id, severity, message, s_line, cwe FROM raw_findings "
            "WHERE commit_id = ? AND file_path = ? AND ABS(COALESCE(s_line,0) - ?) <= ? ORDER BY tool, s_line",
            [full["commit_id"], full["file_path"], int(full["s_line"] or 0), max(w, 1) * 2]):
        k = (r["tool"], r["rule_id"], r["s_line"])
        if k in seen:
            continue
        seen.add(k)
        fmt = fmts.get(r["tool"])
        out.append({"tool": r["tool"], "rule_id": r["rule_id"], "severity": r["severity"], "message": r["message"],
                    "s_line": r["s_line"], "cwe": C.jload(r["cwe"], []),
                    "raw_path": f"{full['commit_id'][:12]}/{r['tool']}.raw.{fmt}" if fmt else None})
    return out


def _provenance(conn: sqlite3.Connection, tabs: set[str], run: dict, w: int) -> dict:
    C.ensure_src_on_path()
    from orchestrator import config
    prov: dict = {"run_id": run.get("run_id"), "tools_json": [], "line_window": w, "gold_rule": None,
                  "scan_run_id": None, "analyze_run_id": None, "orchestrator_git_sha": None, "app_version": None}
    if "run_meta" in tabs:
        cols = C.columns(conn, "run_meta")
        rows = [dict(r) for r in conn.execute("SELECT * FROM run_meta ORDER BY id")]
        tools: list = []
        for r in rows:
            tj = C.jload(r.get("tools_json") if "tools_json" in cols else r.get("tools"), [])
            if isinstance(tj, list):
                tools += [t for t in tj if isinstance(t, dict)]
            tier = r.get("tier") if "tier" in cols else "scan"
            if tier == "analyze":
                prov["analyze_run_id"] = r.get("run_id")
            else:
                prov["scan_run_id"] = r.get("run_id")
            if r.get("orchestrator_git_sha"):
                prov["orchestrator_git_sha"] = r["orchestrator_git_sha"]
            if r.get("app_version"):
                prov["app_version"] = r["app_version"]
        uniq: dict[str, dict] = {}
        for t in tools:
            uniq[t.get("name") or t.get("image") or str(len(uniq))] = t
        prov["tools_json"] = list(uniq.values())
    prof = C.load_run_profile(run)
    p = (prof or {}).get("params_v1") or {}
    gmin = p.get("gold_min_expensive", config.GOLD_MIN_EXPENSIVE)
    allow = p.get("gold_allow_1exp_1cheap", config.GOLD_ALLOW_1EXP_1CHEAP)
    smin = p.get("silver_min_cheap", config.SILVER_MIN_CHEAP)
    prov["gold_rule"] = f"E>={gmin}" + (" | 1E+1C" if allow else "") + f" · silver C>={smin}"
    return prov


# ----------------------------------------------------------------------------- commits
def commits(params: dict, body: dict | None = None) -> dict:
    rid, run, db = _ctx(params)
    page = C.to_int(params.get("page"), 1, lo=1, name="page")
    size = C.to_int(params.get("size"), 25, lo=1, hi=500, name="size")
    kamei_cols = ["ns", "nd", "nf", "entropy", "la", "ld", "lt", "fix", "ndev", "age", "nuc", "exp", "rexp", "sexp"]
    with C.ro_conn(db) as conn:
        tabs = C.tables(conn)
        if "selected_commits" not in tabs:
            return {"total": 0, "page": page, "size": size, "rows": []}
        scols = C.columns(conn, "selected_commits")
        has_cf = "commit_features" in tabs
        has_er = "expensive_runs" in tabs
        has_ste = "scan_tool_errors" in tabs
        total = conn.execute("SELECT COUNT(*) FROM selected_commits").fetchone()[0]
        sel = ["s.commit_id", "s.role", "s.status" if "status" in scols else "'pending' AS status",
               "s.build_status" if "build_status" in scols else "NULL AS build_status",
               "s.n_expensive_ok" if "n_expensive_ok" in scols else "NULL AS n_expensive_ok",
               "s.claimed_by" if "claimed_by" in scols else "NULL AS claimed_by"]
        if has_cf:
            sel += ["c.author_date", "c.author"] + [f"c.{k}" for k in kamei_cols]
            join = " LEFT JOIN commit_features c ON c.commit_id = s.commit_id"
            order = " ORDER BY c.author_date DESC, s.commit_id"
        else:
            join, order = "", " ORDER BY s.commit_id"
        rows = conn.execute(f"SELECT {', '.join(sel)} FROM selected_commits s{join}{order} LIMIT ? OFFSET ?",
                            [size, (page - 1) * size]).fetchall()
        out = []
        for r in rows:
            cid = r["commit_id"]
            n_ok = r["n_expensive_ok"]
            if n_ok is None and has_er:
                n_ok = conn.execute(
                    "SELECT COUNT(DISTINCT tool) FROM expensive_runs WHERE commit_id=? AND phase='analyze' "
                    "AND status='ok' AND tool NOT IN ('-','maven')", [cid]).fetchone()[0]
            n_ok = int(n_ok or 0)
            positive = conn.execute("SELECT 1 FROM findings WHERE commit_id=? AND finding_in_diff=1 LIMIT 1", [cid]).fetchone() \
                if "findings" in tabs else None
            neg = None if positive else ("verified-clean" if n_ok >= 2 else "cheap-clean")
            build_error = None
            if has_er:
                e = conn.execute("SELECT error, status FROM expensive_runs WHERE commit_id=? AND status NOT IN ('ok','skipped') "
                                 "AND error IS NOT NULL ORDER BY id DESC LIMIT 1", [cid]).fetchone()
                if e:
                    build_error = e["error"]
            kam = {k: r[k] for k in kamei_cols} if has_cf and r["nf"] is not None else None
            ste = _scan_tool_errors(conn, cid) if has_ste else []
            out.append({"commit": cid, "scan_tool_errors": ste, "date": (r["author_date"] or "")[:10] if has_cf and r["author_date"] else None,
                        "author": r["author"] if has_cf else None, "role": r["role"], "status": r["status"],
                        "build_status": r["build_status"], "n_expensive_ok": n_ok, "negative_level": neg,
                        "kamei": kam, "build_error": build_error, "claimed_by": r["claimed_by"]})
    return {"total": int(total), "page": page, "size": size, "rows": out}


def _scan_tool_errors(conn: sqlite3.Connection, cid: str) -> list[dict]:
    """Lỗi tool tầng rẻ của commit (TC-15): [{tool, tier, kind, msg, at}]."""
    try:
        return [{"tool": r["tool"], "tier": r["tier"], "kind": r["kind"], "msg": (r["msg"] or "")[:300], "at": r["at"]}
                for r in conn.execute("SELECT tool, tier, kind, msg, at FROM scan_tool_errors WHERE commit_id=? ORDER BY id", [cid])]
    except sqlite3.Error:
        return []


# ----------------------------------------------------------------------------- rescan (TC-15)
SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
RESCAN_SYNC_TIMEOUT = 900


def rescan(params: dict, body: dict | None = None) -> dict:
    """POST /api/results/{id}/rescan {commits[], tools?} -> `cli rescan --db ... --commit a,b [--tools ...] --json`.

    1 commit: đồng bộ (timeout 900 s) trả JSON của CLI (`results[]`; exit 3 = có infra_error -> `infra: true`).
    >1 commit: chạy nền, trả {pid, log, mode:'background'} (A4 trả HTTP 202).
    """
    rid, run, db = _ctx(params)
    body = body or {}
    commits_ = body.get("commits")
    if isinstance(commits_, str):
        commits_ = [commits_]
    if not isinstance(commits_, list) or not commits_:
        raise bad_request("commits phải là danh sách SHA không rỗng")
    shas = []
    for s in commits_:
        s = str(s or "").strip()
        if not SHA_RE.match(s):
            raise bad_request(f"SHA không hợp lệ: {s!r}", "7–40 ký tự hex")
        shas.append(s)
    tools = body.get("tools")
    if tools is not None:
        if not isinstance(tools, list) or any(not re.fullmatch(r"[a-z0-9_-]+", str(t)) for t in tools):
            raise bad_request("tools phải là danh sách tên tool rẻ")
    C.require_db_free(db)
    prof = C.load_run_profile(run)
    repo = run.get("repo") or (prof or {}).get("repo")
    rdir = C.run_work(run) / rid
    env = C.cli_env(prof, run_id=rid, run_dir=rdir)
    env["ORCH_SQLITE"] = str(db)
    argv = ["rescan", "--db", str(db), "--commit", ",".join(shas)]
    if repo:
        argv += ["--repo", repo]
    if tools:
        argv += ["--tools", ",".join(tools)]
    if len(shas) == 1:
        res = C.run_cli(argv, env, timeout=RESCAN_SYNC_TIMEOUT, ok_codes=(0, 3))
        results = res.get("results") or []
        infra = any(r.get("infra") for r in results if isinstance(r, dict)) or res.get("rc") == 3
        return {"ok": not infra, "mode": "sync", "commits": shas, "results": results, "infra": infra, "rc": res.get("rc", 0),
                "note": "infra_error — Docker/đĩa có vấn đề, chưa quét lại được" if infra else "đã quét lại tầng rẻ + relabel commit"}
    log = rdir / "rescan.log"
    pid = C.spawn_cli(argv, log, env)
    return {"ok": True, "mode": "background", "status": 202, "pid": pid, "log": str(log), "commits": shas,
            "note": f"rescan {len(shas)} commit chạy nền — xem log; kết quả cập nhật vào DB"}


# ----------------------------------------------------------------------------- export
def _jsonl_to_csv(src: Path, dst: Path) -> None:
    rows = []
    with open(src, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with open(dst, "w", encoding="utf-8", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(cols)
        for r in rows:
            wr.writerow([json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else ("" if v is None else v)
                         for v in (r.get(c) for c in cols)])


def export(params: dict, body: dict | None = None) -> dict:
    rid, run, db = _ctx(params)
    body = body or {}
    formats = body.get("formats") or ["jsonl"]
    if not isinstance(formats, list) or not formats or any(f not in FORMATS for f in formats):
        raise bad_request(f"formats phải là danh sách con của {FORMATS}")
    prof = C.load_run_profile(run)
    out = run.get("export") or ((prof or {}).get("paths") or {}).get("export") or str(C.home() / "exports" / f"export_{rid}")
    out_path = Path(out)
    C.ensure_src_on_path()
    with C.profile_env(prof, {"ORCH_RUN_ID": rid}):
        from orchestrator import export_dataset, stats
        store = C.open_rw(db)
        try:
            res = export_dataset.export_all(store, out_path, profile=prof, run_id=rid)
        except OSError as e:
            raise ApiError(500, "EEXPORT", f"Xuất thất bại: {e}") from e
        finally:
            store.close()
        real = Path(res["out"])
        extra: list[str] = []
        if "csv" in formats:
            for n in ("dataset", "commits"):
                src = real / f"{n}.jsonl"
                if src.exists():
                    _jsonl_to_csv(src, real / f"{n}.csv")
                    extra.append(f"{n}.csv")
        if "csv" in formats or "latex" in formats:
            try:
                ov = stats.overview(db, run_id=rid)
                if "csv" in formats:
                    extra += [Path(p).name for p in stats.write(ov, real / "stats", "csv")]
                if "latex" in formats:
                    extra += [Path(p).name for p in stats.write(ov, real, "latex")]
            except (ValueError, sqlite3.Error) as e:
                extra.append(f"(stats lỗi: {e})")
    files = sorted(p.name for p in real.iterdir() if p.is_file())
    manifest = {}
    try:
        man = json.loads((real / "run_manifest.json").read_text(encoding="utf-8"))
        manifest = {k: man.get(k) for k in ("run_id", "counts", "params_v1", "experiment", "started", "finished",
                                            "orchestrator_git_sha", "app_version", "docker_version", "db")}
        manifest["n_build_failed"] = len(man.get("build_failed") or [])
        manifest["n_infra_error"] = len(man.get("infra_error") or [])
        manifest["n_skipped"] = len(man.get("skipped") or [])
        manifest["n_tool_timeout"] = len(man.get("tool_timeout") or [])
    except (OSError, ValueError):
        pass
    try:
        import registry
        if registry.get(rid):
            registry.upsert({"run_id": rid, "export": str(real)})
    except Exception:  # noqa: BLE001 — registry không bắt buộc
        pass
    return {"export_dir": str(real), "files": files, "exists": real.resolve() != out_path.resolve(),
            "requested_dir": str(out_path), "manifest": manifest, "formats": formats,
            "counts": res.get("counts"), "commits": res.get("commits")}


# ----------------------------------------------------------------------------- raw
def _safe_rel(path: str) -> Path:
    p = str(path or "").replace("\\", "/").strip()
    if not p or p.startswith("/") or re.match(r"^[A-Za-z]:", p) or ".." in p.split("/") or "\x00" in p:
        raise bad_request(f"path không hợp lệ: {path!r}", "Chỉ đường dẫn tương đối trong thư mục export")
    if not re.fullmatch(r"[A-Za-z0-9_.\-/ ]+", p):
        raise bad_request(f"path chứa ký tự không cho phép: {path!r}")
    return Path(p)


def raw(params: dict, body: dict | None = None) -> dict:
    rid, run, db = _ctx(params)
    rel = _safe_rel(params.get("path"))
    max_bytes = C.to_int(params.get("max_bytes"), 2_000_000, lo=1024, name="max_bytes")
    ext = rel.suffix.lstrip(".").lower()
    ctype = CONTENT_TYPES.get(ext, "text/plain")
    exp = run.get("export")
    if exp:
        base = Path(exp).resolve()
        target = (base / rel).resolve()
        if base in target.parents and target.is_file():
            data = target.read_bytes()
            return {"path": str(rel), "source": str(target), "content_type": ctype, "bytes": len(data),
                    "truncated": len(data) > max_bytes, "content": data[:max_bytes].decode("utf-8", errors="replace")}
    m = RAW_RE.match(rel.as_posix())
    if m:
        sha, tool, fmt = m.groups()
        with C.ro_conn(db) as conn:
            if "raw_output" in C.tables(conn):
                r = conn.execute("SELECT content FROM raw_output WHERE commit_id LIKE ? AND tool = ? AND fmt = ? ORDER BY id DESC LIMIT 1",
                                 [sha + "%", tool, fmt]).fetchone()
                if r is not None:
                    content = r[0] or ""
                    return {"path": str(rel), "source": f"db:raw_output:{sha[:12]}/{tool}", "content_type": ctype,
                            "bytes": len(content.encode("utf-8")), "truncated": len(content) > max_bytes,
                            "content": content[:max_bytes]}
    raise not_found(f"raw {rel.as_posix()}", "Chưa export hoặc file đã bị dọn; raw_output trong DB cũng không có")


# ----------------------------------------------------------------------------- open / features / relabel
def open_path(params: dict, body: dict | None = None) -> dict:
    path = str(((body or {}).get("path") or (params or {}).get("path") or "")).strip()
    if not path:
        raise bad_request("thiếu path")
    p = Path(path)
    if not p.exists():
        raise not_found(f"đường dẫn {p}")
    target = p if p.is_dir() else p.parent
    try:
        if os.name == "nt":
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["xdg-open", str(target)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, AttributeError) as e:
        raise not_supported(f"Không mở được thư mục trên hệ này: {e}", str(target)) from e
    return {"ok": True, "path": str(target)}


def _spawn_for_run(rid: str, run: dict, cmd: str, args: list[str]) -> dict:
    db = C.run_db(run)
    C.require_db_free(db)
    prof = C.load_run_profile(run)
    work = C.run_work(run)
    rdir = work / rid
    env = C.cli_env(prof, run_id=rid, run_dir=rdir)
    env["ORCH_SQLITE"] = str(db)
    if run.get("profile") and Path(run["profile"]).exists():
        argv = [cmd, "--profile", str(run["profile"])]
    else:
        argv = [cmd, *args]
    log = rdir / f"{cmd}.log"
    pid = C.spawn_cli(argv, log, env)
    return {"ok": True, "pid": pid, "log": str(log), "argv": argv, "note": f"{cmd} chạy nền — xem log khi xong; kết quả cập nhật vào DB"}


def features(params: dict, body: dict | None = None) -> dict:
    rid, run, _db = _ctx(params)
    repo = run.get("repo") or ((C.load_run_profile(run) or {}).get("repo"))
    if not repo:
        raise bad_request("run không có repo để tính Kamei")
    args = [repo] + (["--branch", run["branch"]] if run.get("branch") else [])
    return _spawn_for_run(rid, run, "features", args)


def relabel(params: dict, body: dict | None = None) -> dict:
    rid, run, _db = _ctx(params)
    prof = C.load_run_profile(run)
    exp = (prof or {}).get("experiment") or {}
    if not (exp and exp.get("enabled")):
        raise not_supported("Gán nhãn lại qua GUI chỉ cho run ở chế độ thí nghiệm (profile.experiment.enabled)",
                            "Phương pháp luận v1 đóng băng — dùng Wizard bước 3 'Chế độ thí nghiệm' để tạo run _exp")
    repo = run.get("repo") or prof.get("repo")
    return _spawn_for_run(rid, run, "relabel", [repo])
