"""Overview thống kê 1 DB (CONTRACTS §9 `GET /api/results/{id}/overview`) + xuất json|csv|latex.

Đọc DB CHỈ-ĐỌC (`file:…?mode=ro`), không migrate, không ghi. κ: lấy từ bảng `kappa` (A1, theo
run_id) nếu có, ngược lại tính sống bằng kappa.compute_all qua shim read-only.

Cấu trúc trả về (khớp fixture gui/fixtures/overview.json):
  funnel{commits,after_filter,buggy,clean,built,build_failed,skipped,infra_error}
  labels{gold,silver,candidate,verified_clean,cheap_clean}
  by_cwe_group[{group,gold,silver,candidate}]  kappa{total,by_category[],by_group[],pairs[]}
  coverage{one,two,three_plus}  precision{n,tp,fp,ci_low,ci_high}|null  limits[≥5 câu]
  params_v1  experiment
"""
from __future__ import annotations

import csv
import json
import math
import sqlite3
from pathlib import Path

from . import config
from . import kappa as kp
from .storage.sqlite_store import SQLiteStore


class _RoStore:
    """Shim chỉ-đọc đủ cho kappa.collect (cần .conn + .raw_for_commit)."""
    raw_for_commit = SQLiteStore.raw_for_commit

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn


def open_ro(db: str | Path) -> sqlite3.Connection:
    p = Path(db).resolve()
    return sqlite3.connect(f"{p.as_uri()}?mode=ro", uri=True)


def _tables(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _cols(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _n(conn, sql: str, params=()) -> int:
    r = conn.execute(sql, params).fetchone()
    return int(r[0] or 0) if r else 0


def wilson(tp: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Khoảng tin cậy Wilson 95% cho tỉ lệ tp/n."""
    if n <= 0:
        return 0.0, 0.0
    ph = tp / n
    den = 1 + z * z / n
    centre = ph + z * z / (2 * n)
    half = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n))
    return round((centre - half) / den, 4), round((centre + half) / den, 4)


def _universe(conn, tabs: set[str]) -> set[str]:
    """Commit đã qua tầng rẻ = scan_done ∪ scanned_files ∪ raw_output ∪ raw_findings ∪ findings
    (khớp store.all_commit_ids()/export_dataset: commit clean không có file code vẫn có raw_output)."""
    parts = []
    for tab, col in (("scan_done", "commit_id"), ("scanned_files", "commit_id"), ("raw_output", "commit_id"),
                     ("raw_findings", "commit_id"), ("findings", "commit_id")):
        if tab in tabs:
            parts.append(f"SELECT {col} FROM {tab}")
    if not parts:
        return set()
    return {r[0] for r in conn.execute(" UNION ".join(parts)) if r[0]}


def _funnel(conn, tabs: set[str]) -> dict:
    commits = _n(conn, "SELECT COUNT(*) FROM commit_features") if "commit_features" in tabs else 0
    after = _n(conn, "SELECT COUNT(*) FROM scan_done") if "scan_done" in tabs else 0
    if not commits:
        commits = after or _n(conn, "SELECT COUNT(DISTINCT commit_id) FROM scanned_files")
    if not after:
        after = _n(conn, "SELECT COUNT(DISTINCT commit_id) FROM scanned_files")
    buggy = clean = built = build_failed = skipped = infra = 0
    if "selected_commits" in tabs:
        buggy = _n(conn, "SELECT COUNT(*) FROM selected_commits WHERE role='buggy'")
        built = _n(conn, "SELECT COUNT(*) FROM selected_commits WHERE status='done'")
        build_failed = _n(conn, "SELECT COUNT(*) FROM selected_commits WHERE status='build_failed'")
    # clean = commit đã quét rẻ nhưng không có finding (universe - commit có finding)
    universe = _universe(conn, tabs)
    has_any = {r[0] for r in conn.execute("SELECT DISTINCT commit_id FROM findings")}
    clean = len(universe - has_any)
    after = max(after, len(universe))
    commits = max(commits, after)
    if "expensive_runs" in tabs:
        skipped = _n(conn, "SELECT COUNT(DISTINCT commit_id) FROM expensive_runs WHERE status='skipped'")
        infra = _n(conn, "SELECT COUNT(DISTINCT commit_id) FROM expensive_runs WHERE status='infra_error'")
    return {"commits": commits, "after_filter": after, "buggy": buggy, "clean": clean, "built": built,
            "build_failed": build_failed, "skipped": skipped, "infra_error": infra}


def _negatives(conn, tabs: set[str]) -> tuple[int, int]:
    """(verified_clean, cheap_clean) theo CONTRACTS §1: verified-clean CHỈ khi n_expensive_ok >= 2."""
    positive = {r[0] for r in conn.execute("SELECT DISTINCT commit_id FROM findings WHERE finding_in_diff=1")}
    negatives = _universe(conn, tabs) - positive
    ok_count: dict[str, int] = {}
    if "selected_commits" in tabs and "n_expensive_ok" in _cols(conn, "selected_commits"):
        ok_count = dict(conn.execute("SELECT commit_id, COALESCE(n_expensive_ok,0) FROM selected_commits"))
    elif "expensive_runs" in tabs:
        ok_count = dict(conn.execute(
            "SELECT commit_id, COUNT(DISTINCT tool) FROM expensive_runs "
            "WHERE phase='analyze' AND status='ok' GROUP BY commit_id"))
    verified = sum(1 for c in negatives if ok_count.get(c, 0) >= 2)
    return verified, len(negatives) - verified


def _kappa(conn, tabs: set[str], run_id: str | None) -> dict:
    if "kappa" in tabs:
        rows = conn.execute("SELECT run_id, scope, grp, value, n FROM kappa").fetchall()
        if rows:
            rids = [r[0] for r in rows]
            rid = run_id if run_id in rids else rids[-1]
            sel = [r for r in rows if r[0] == rid]
            out = {"total": None, "by_category": [], "by_group": [], "pairs": [], "run_id": rid}
            key = {"category": "by_category", "cwe_group": "by_group", "pair": "pairs"}
            for _rid, scope, grp, value, n in sel:
                if scope == "total":
                    out["total"] = value
                    out["n"] = n
                elif scope in key:
                    out[key[scope]].append({"group": grp, "value": value, "n": n})
            return out
    db_path = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    try:                                   # A1: SQLiteStore(path, readonly=True) — không lock, không migrate
        ro = SQLiteStore(db_path, readonly=True)
    except TypeError:
        ro = _RoStore(conn)
    res = kp.compute_all(ro)
    if isinstance(ro, SQLiteStore):
        ro.close()
    res["run_id"] = None
    return res


def _precision_from_review(db_path: Path) -> dict | None:
    """Ưu tiên review.summary(store)[-1] (A1): precision theo rater adjudicated, Wilson, kappa rater."""
    try:
        from . import review
    except ImportError:
        return None
    summary = getattr(review, "summary", None)
    if summary is None:
        return None
    try:
        store = SQLiteStore(db_path, readonly=True)
    except (TypeError, Exception):  # noqa: BLE001 — store cũ / DB khoá -> fallback gold_review thô
        return None
    try:
        rows = summary(store)
    except Exception:  # noqa: BLE001
        rows = []
    finally:
        store.close()
    if not rows:
        return None
    last = rows[-1]
    pr = dict(last.get("precision") or {})
    if not pr:
        return None
    pr.setdefault("n", (pr.get("tp") or 0) + (pr.get("fp") or 0))
    pr["sample_id"] = last.get("sample_id")
    pr["kappa_raters"] = last.get("kappa_raters")
    pr["neg_precision"] = last.get("neg_precision")
    pr["source"] = "review.summary"
    return pr


def _precision(conn, tabs: set[str]) -> dict | None:
    if "gold_review" not in tabs:
        return None
    rows = conn.execute("SELECT verdict, COUNT(*) FROM gold_review GROUP BY verdict").fetchall()
    if not rows:
        return None
    d = dict(rows)
    tp, fp, un = int(d.get("TP", 0)), int(d.get("FP", 0)), int(d.get("unclear", 0))
    n = tp + fp
    lo, hi = wilson(tp, n)
    return {"n": n, "tp": tp, "fp": fp, "unclear": un, "point": round(tp / n, 4) if n else None,
            "ci_low": lo, "ci_high": hi}


def _pct(sorted_vals: list[int], q: float) -> int | None:
    if not sorted_vals:
        return None
    k = max(0, min(len(sorted_vals) - 1, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


def anchor_gap(conn, tabs: set[str], tool_a: str = "findsecbugs", tool_b: str = "sonar") -> dict:
    """Khoảng cách dòng giữa raw finding FSB và Sonar cùng (commit, file, cwe_group) GẦN NHẤT — đo từ raw_findings
    (METHODOLOGY §8: khác điểm neo). Mỗi finding của tool_a ghép với finding tool_b gần nhất cùng nhóm/file.
    -> {pairs_same_file_group, min, median, p90, by_group[{group, n, min, median}]}; 0 cặp -> pairs=0, số = None."""
    from .consensus.cwe_groups import primary_group
    out = {"pairs_same_file_group": 0, "min": None, "median": None, "p90": None, "by_group": []}
    if "raw_findings" not in tabs:
        return out
    by_key: dict[tuple, dict[str, list[int]]] = {}
    for cid, tool, fp, s_line, cwe in conn.execute(
            "SELECT commit_id, tool, file_path, s_line, cwe FROM raw_findings WHERE tier='expensive' AND tool IN (?,?)",
            [tool_a, tool_b]):
        try:
            cwes = json.loads(cwe) if cwe else []
        except ValueError:
            cwes = []
        grp, _cat = primary_group(cwes if isinstance(cwes, list) else [str(cwes)])
        by_key.setdefault((cid, fp, grp), {tool_a: [], tool_b: []})[tool].append(int(s_line or 0))
    gaps_all: list[int] = []
    gaps_grp: dict[str, list[int]] = {}
    for (_cid, _fp, grp), d in by_key.items():
        if not d[tool_a] or not d[tool_b]:
            continue
        b_sorted = sorted(set(d[tool_b]))
        for a in set(d[tool_a]):
            g = min(abs(a - b) for b in b_sorted)
            gaps_all.append(g)
            gaps_grp.setdefault(grp, []).append(g)
    if not gaps_all:
        return out
    gaps_all.sort()
    out.update(pairs_same_file_group=len(gaps_all), min=gaps_all[0], median=_pct(gaps_all, 0.5), p90=_pct(gaps_all, 0.9))
    out["by_group"] = sorted(({"group": g, "n": len(v), "min": min(v), "median": _pct(sorted(v), 0.5),
                               "max": max(v)} for g, v in gaps_grp.items()),
                             key=lambda r: (-r["n"], r["group"]))
    return out


def build_limits(ov: dict) -> list[str]:
    """Sinh ≥5 câu 'giới hạn' từ số liệu (bắt buộc đi kèm mọi bảng — nhãn bạc ≠ chân lý)."""
    f, lab, kap, prec = ov["funnel"], ov["labels"], ov["kappa"], ov["precision"]
    out: list[str] = []
    sel = f["buggy"] + (f["built"] + f["build_failed"] - f["buggy"] if f["built"] + f["build_failed"] > f["buggy"] else 0)
    denom = max(1, f["built"] + f["build_failed"] + f["skipped"])
    if f["build_failed"]:
        out.append(f"Tầng đắt không phủ {f['build_failed']}/{denom} commit đã chọn (build_failed "
                   f"{round(100 * f['build_failed'] / denom)} %) — nhãn ở đó chỉ từ tool rẻ.")
    else:
        out.append("Tầng đắt chỉ phủ commit build được; commit chưa qua tầng đắt chỉ có nhãn từ tool rẻ.")
    if f["skipped"]:
        out.append(f"{f['skipped']} commit không có module Java (skipped) — không tính verified-clean.")
    else:
        out.append("Commit không có module Java (skipped) không được tính verified-clean.")
    if f["infra_error"]:
        out.append(f"{f['infra_error']} commit gặp lỗi hạ tầng (infra_error) — không đếm là dữ liệu.")
    out.append("Secret trần (gitleaks/trufflehog) chỉ tới silver vì không có tool đắt xác nhận.")
    noise = ov["params_v1"].get("noise_cwe") or []
    if noise:
        out.append(f"{', '.join(noise)} đã lọc như nhiễu theo cấu hình v1 (raw vẫn giữ).")
    if prec and prec["n"]:
        out.append(f"Precision gold kiểm tay: {prec['tp']}/{prec['n']} TP "
                   f"(CI95 {prec['ci_low']:.2f}–{prec['ci_high']:.2f}); nhãn còn lại là đồng thuận máy.")
    else:
        out.append("Nhãn là đồng thuận máy, chưa kiểm tay (n=0).")
    if isinstance(kap.get("total"), (int, float)) and kap["total"] < 0:
        out.append(f"κ Fleiss tổng {kap['total']:.2f} (âm) — tool phủ miền rời nhau; xem κ theo nhóm/cặp thay vì tổng.")
    if lab["gold"] == 0:
        out.append("Chưa có cụm gold (không cụm nào ≥2 tool đắt / 1 đắt + 1 rẻ đồng thuận).")
    ct = ov.get("cross_tool") or {}
    ag = ct.get("anchor_gap") or {}
    if ({"findsecbugs", "sonar"} <= set(ct.get("expensive_tools_seen") or []) and ct.get("fsb_sonar_clusters", 0) == 0
            and ag.get("pairs_same_file_group")):
        grp_txt = "; ".join(f"{g['group']} {g['min']}–{g['max']}" for g in (ag.get("by_group") or [])[:3])
        out.append(f"FindSecBugs và SonarQube cùng chạy nhưng 0 cụm liên-tool: hai tool neo cùng một lỗi vào mức cú pháp "
                   f"khác nhau (FSB tại khai báo method/field, Sonar tại statement). Đo trên DB này: "
                   f"{ag['pairs_same_file_group']} cặp cùng (file, nhóm CWE), khoảng cách dòng gần nhất min {ag['min']} · "
                   f"trung vị {ag['median']} · p90 {ag['p90']}" + (f" ({grp_txt})" if grp_txt else "") +
                   " — vượt mọi W∈{3,5,7} nên không gộp được; gold trên app Spring bị ước lượng thiếu có hệ thống và "
                   "κ âm FSB–Sonar phần lớn phản ánh khác điểm neo, không phải bất đồng về lỗi (METHODOLOGY §8).")
    if ov.get("experiment"):
        out.append("Run ở CHẾ ĐỘ THÍ NGHIỆM (params khác v1) — không so trực tiếp với run v1.")
    if sel and f["commits"] and f["after_filter"] < f["commits"]:
        out.append(f"Lọc thô bỏ {f['commits'] - f['after_filter']} commit (merge/nhị phân/khổng lồ).")
    return out


def overview(db: str | Path, run_id: str | None = None) -> dict:
    conn = open_ro(db)
    try:
        tabs = _tables(conn)
        if "findings" not in tabs:
            raise ValueError(f"DB không có bảng findings: {db}")
        labels = dict(conn.execute("SELECT COALESCE(label,'candidate'), COUNT(*) FROM findings GROUP BY 1"))
        verified, cheap = _negatives(conn, tabs)
        lab = {"gold": int(labels.get("gold", 0)), "silver": int(labels.get("silver", 0)),
               "candidate": int(labels.get("candidate", 0)), "verified_clean": verified, "cheap_clean": cheap}
        by_grp: dict[str, dict] = {}
        for grp, label, n in conn.execute(
                "SELECT COALESCE(cwe_group,'other'), COALESCE(label,'candidate'), COUNT(*) "
                "FROM findings GROUP BY 1,2"):
            d = by_grp.setdefault(grp, {"group": grp, "gold": 0, "silver": 0, "candidate": 0})
            if label in d:
                d[label] += n
        by_cwe = sorted(by_grp.values(), key=lambda d: (-d["gold"], -d["silver"], -d["candidate"], d["group"]))
        cov = {"one": 0, "two": 0, "three_plus": 0}
        for n_agree, cnt in conn.execute("SELECT COALESCE(n_tools_agree,1), COUNT(*) FROM findings GROUP BY 1"):
            cov["one" if n_agree <= 1 else "two" if n_agree == 2 else "three_plus"] += cnt
        # Liên-tool FSB–Sonar (METHODOLOGY §8): tool đắt đã có raw + số cụm có cả findsecbugs lẫn sonar
        seen = set()
        if "raw_findings" in tabs:
            seen |= {r[0] for r in conn.execute("SELECT DISTINCT tool FROM raw_findings WHERE tier='expensive'")}
        if "raw_output" in tabs:
            seen |= {r[0] for r in conn.execute(
                "SELECT DISTINCT tool FROM raw_output WHERE tier='expensive' AND COALESCE(fmt,'')!='error'")}
        fsb_sonar = _n(conn, "SELECT COUNT(*) FROM findings WHERE COALESCE(n_tools_agree,1) >= 2 "
                             "AND agreeing_tools LIKE '%findsecbugs%' AND agreeing_tools LIKE '%sonar%'")
        cross = {"expensive_tools_seen": sorted(seen), "fsb_sonar_clusters": fsb_sonar,
                 "multi_tool_clusters": _n(conn, "SELECT COUNT(*) FROM findings WHERE COALESCE(n_tools_agree,1) >= 2"),
                 "anchor_gap": anchor_gap(conn, tabs)}
        exp = None
        params = config.params_v1()
        if "run_meta" in tabs:
            rm_cols = _cols(conn, "run_meta")
            if {"experiment", "reason"} <= rm_cols:
                r = conn.execute("SELECT experiment, reason FROM run_meta ORDER BY id DESC LIMIT 1").fetchone()
                if r and r[0]:
                    exp = {"enabled": True, "reason": r[1]}
            if "line_window" in rm_cols:
                r = conn.execute("SELECT line_window FROM run_meta ORDER BY id DESC LIMIT 1").fetchone()
                if r and r[0]:
                    params["line_window"] = int(r[0])
        if exp is None and config.EXPERIMENT:
            exp = config.experiment_info()
        precision = _precision_from_review(Path(db)) or _precision(conn, tabs)
        ov = {"funnel": _funnel(conn, tabs), "labels": lab, "by_cwe_group": by_cwe,
              "kappa": _kappa(conn, tabs, run_id), "coverage": cov, "precision": precision,
              "limits": [], "params_v1": params, "experiment": exp, "db": str(db), "run_id": run_id,
              "cross_tool": cross}
        ov["limits"] = build_limits(ov)
        return ov
    finally:
        conn.close()


# ----------------------------------------------------------------------------- xuất
def _tables_of(ov: dict) -> dict[str, tuple[list[str], list[list]]]:
    """Tên bảng -> (header, rows) — dùng cho CSV (1 file/bảng) và LaTeX (1 tabular/bảng)."""
    t: dict[str, tuple[list[str], list[list]]] = {}
    t["funnel"] = (["stage", "count"], [[k, v] for k, v in ov["funnel"].items()])
    t["labels"] = (["label", "count"], [[k, v] for k, v in ov["labels"].items()])
    t["by_cwe_group"] = (["group", "gold", "silver", "candidate"],
                         [[d["group"], d["gold"], d["silver"], d["candidate"]] for d in ov["by_cwe_group"]])
    kr = [["total", "", ov["kappa"].get("total"), ov["kappa"].get("n", "")]]
    for scope, key in (("category", "by_category"), ("cwe_group", "by_group"), ("pair", "pairs")):
        kr += [[scope, d["group"], d["value"], d["n"]] for d in ov["kappa"].get(key, [])]
    t["kappa"] = (["scope", "group", "kappa", "n"], kr)
    t["coverage"] = (["n_tools", "count"], [[k, v] for k, v in ov["coverage"].items()])
    if ov.get("precision"):
        p = ov["precision"]
        t["precision"] = (["n", "tp", "fp", "unclear", "point", "ci_low", "ci_high"],
                          [[p["n"], p["tp"], p["fp"], p.get("unclear", 0), p["point"], p["ci_low"], p["ci_high"]]])
    t["limits"] = (["limit"], [[s] for s in ov["limits"]])
    t["params_v1"] = (["param", "value"], [[k, json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v]
                                            for k, v in ov["params_v1"].items()])
    return t


def _tex_escape(s) -> str:
    s = "" if s is None else str(s)
    for a, b in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("_", r"\_"), ("#", r"\#"),
                 ("{", r"\{"), ("}", r"\}"), ("$", r"\$")):
        s = s.replace(a, b)
    return s


def render(ov: dict, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(ov, ensure_ascii=False, indent=2, default=str)
    tabs = _tables_of(ov)
    if fmt == "csv":
        import io
        buf = io.StringIO()
        for name, (hdr, rows) in tabs.items():
            buf.write(f"# {name}\n")
            w = csv.writer(buf, lineterminator="\n")
            w.writerow(hdr)
            w.writerows(rows)
            buf.write("\n")
        return buf.getvalue()
    if fmt == "latex":
        parts = []
        for name, (hdr, rows) in tabs.items():
            col = "l" * len(hdr)
            nl = " \\\\\n"
            body = nl.join(" & ".join(_tex_escape(c) for c in r) for r in rows) + (" \\\\" if rows else "")
            head = " & ".join(_tex_escape(h) for h in hdr)
            parts.append("% " + name + "\n\\begin{table}[h]\\centering\n\\caption{" + _tex_escape(name) + "}\n"
                         + "\\begin{tabular}{" + col + "}\n\\hline\n" + head + nl
                         + "\\hline\n" + body + "\n\\hline\n\\end{tabular}\n\\end{table}\n")
        return "\n".join(parts)
    raise ValueError(f"format lạ: {fmt}")


def write(ov: dict, out_dir: Path, fmt: str) -> list[str]:
    """Ghi file: json -> overview.json; csv -> 1 file/bảng; latex -> overview.tex. Trả danh sách file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    files: list[str] = []
    if fmt == "json":
        p = out_dir / "overview.json"
        p.write_text(json.dumps(ov, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        files.append(str(p))
    elif fmt == "csv":
        for name, (hdr, rows) in _tables_of(ov).items():
            p = out_dir / f"{name}.csv"
            with open(p, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(hdr)
                w.writerows(rows)
            files.append(str(p))
    elif fmt == "latex":
        p = out_dir / "overview.tex"
        p.write_text(render(ov, "latex"), encoding="utf-8")
        files.append(str(p))
    else:
        raise ValueError(f"format lạ: {fmt}")
    return files
