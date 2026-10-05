#!/usr/bin/env python3
"""Báo cáo nghiệm thu TÁI LẬP A/B (RESULTS.md) — stdlib-only, đọc export (+ DB readonly nếu có).

  PYTHONPATH=src python scripts/results_report.py --a <export_A> --b <export_B> [--db-a DB --db-b DB]
                                                   --out RESULTS.md [--json]

Nội dung: (1) cấu hình (params_v1, orchestrator_git_sha A/B, digest image A/B — lệch -> cảnh báo đỏ);
(2) phễu + nhãn A vs B, thời gian chạy (run_meta started/finished, commit/giờ), build cold/warm từ speed.json;
(3) orchestrator.compare (same/only_a/only_b/label_changed/explained_by/unexplained) + ≤20 cụm lệch kèm lý do;
(4) verify_run cho A và B; (5) κ A vs B; (6) kết luận tự động ĐẠT/CHƯA ĐẠT; (7) Giới hạn (stats.limits của A).
Exit 0 nếu ĐẠT, 1 nếu CHƯA ĐẠT, 2 nếu lỗi tham số.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "src", ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

EXPLAIN = ("tool_timeout", "infra_error", "skipped", "build_failed", "tool_error")
MAX_DIFF_ROWS = 20


# ----------------------------------------------------------------------------- đọc dữ liệu
def load_manifest(export_dir: Path) -> dict:
    p = Path(export_dir) / "run_manifest.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def digest_map(man: dict) -> dict[str, dict]:
    """{tool: {image, digest, version}} từ run_meta[*].tools_json (hàng sau ghi đè hàng trước)."""
    out: dict[str, dict] = {}
    for rm in man.get("run_meta") or []:
        tj = rm.get("tools_json")
        if isinstance(tj, str):
            try:
                tj = json.loads(tj)
            except ValueError:
                tj = []
        for t in tj or []:
            if isinstance(t, dict) and t.get("name"):
                out[t["name"]] = {"image": t.get("image"), "digest": t.get("digest"), "version": t.get("version")}
    return out


def compare_tools(ma: dict, mb: dict) -> list[dict]:
    da, db = digest_map(ma), digest_map(mb)
    rows = []
    for name in sorted(set(da) | set(db)):
        a, b = da.get(name, {}), db.get(name, {})
        match = bool(a.get("digest")) and a.get("digest") == b.get("digest")
        rows.append({"tool": name, "image_a": a.get("image") or a.get("version"), "digest_a": a.get("digest"),
                     "image_b": b.get("image") or b.get("version"), "digest_b": b.get("digest"), "match": match})
    return rows


def _parse_ts(s) -> float | None:
    if not s:
        return None
    s = str(s).replace(" ", "T")[:19]
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return time.mktime(time.strptime(s, fmt))
        except ValueError:
            continue
    return None


def run_times(man: dict) -> dict:
    """started = min run_meta.started_at; finished = max(finished_at) (fallback manifest.finished)."""
    starts, ends = [], []
    for rm in man.get("run_meta") or []:
        if rm.get("started_at"):
            starts.append(str(rm["started_at"]))
        if rm.get("finished_at"):
            ends.append(str(rm["finished_at"]))
    started = min(starts) if starts else man.get("started")
    finished = max(ends) if ends else man.get("finished")
    t0, t1 = _parse_ts(started), _parse_ts(finished)
    hours = round((t1 - t0) / 3600, 3) if (t0 and t1 and t1 >= t0) else None
    n = (man.get("counts") or {}).get("commits")
    per_h = round(n / hours, 1) if (hours and n) else None
    tiers = sorted({rm.get("tier") for rm in man.get("run_meta") or [] if rm.get("tier")})
    note = None
    if ends and any("T" not in e for e in ends):
        note = "finished_at có hàng dạng UTC không 'T' (DB tạo trước bản sửa timestamp) — thời lượng chỉ tham khảo"
    return {"started": started, "finished": finished, "hours": hours, "commits": n, "commits_per_hour": per_h,
            "tiers": tiers, "note": note}


def speed_info() -> dict | None:
    try:
        from registry import speed
        d = speed.load()
        return {k: d.get(k) for k in ("build_cold_s", "build_warm_s", "fsb_s", "sonar_s", "cheap_s_per_commit",
                                      "samples", "source", "updated")}
    except Exception:  # noqa: BLE001 — registry không bắt buộc
        return None


def _explain_sets(man: dict) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {k: set() for k in EXPLAIN}
    for k in EXPLAIN:
        for x in man.get(k) or []:
            c = x.get("commit") if isinstance(x, dict) else x
            if c:
                out[k].add(str(c))
    return out


def diff_rows(cmp: dict, ma: dict, mb: dict, limit: int = MAX_DIFF_ROWS) -> list[dict]:
    """Danh sách cụm lệch (unexplained trước) kèm lý do từ manifest A/B."""
    ea, eb = _explain_sets(ma), _explain_sets(mb)

    def reason(commit: str) -> str:
        for k in EXPLAIN:
            if commit in ea[k]:
                return f"{k} (A)"
            if commit in eb[k]:
                return f"{k} (B)"
        return "KHÔNG giải thích"
    rows = []
    for kind, key in (("only_a", "only_a"), ("only_b", "only_b"), ("label_changed", "label_changed")):
        for r in cmp.get(key) or []:
            lab = f"{r.get('a')}→{r.get('b')}" if kind == "label_changed" else (r.get("label") or "")
            rows.append({"kind": kind, "cluster_key": r.get("cluster_key"), "commit": str(r.get("commit") or ""),
                         "file_path": r.get("file_path"), "cwe_group": r.get("cwe_group"), "label": lab,
                         "reason": reason(str(r.get("commit") or ""))})
    rows.sort(key=lambda r: (0 if r["reason"].startswith("KHÔNG") else 1, r["kind"], r["commit"], r["file_path"] or ""))
    return rows[:limit]


def kappa_table(ma: dict, mb: dict) -> list[dict]:
    def _idx(man):
        return {(k.get("scope"), k.get("grp") or ""): (k.get("value"), k.get("n")) for k in man.get("kappa") or []}
    ka, kb = _idx(ma), _idx(mb)
    rows = []
    for key in sorted(set(ka) | set(kb), key=lambda k: ({"total": 0, "category": 1, "cwe_group": 2, "pair": 3}.get(k[0], 9), k[1])):
        va, na = ka.get(key, (None, None))
        vb, nb = kb.get(key, (None, None))
        delta = round(vb - va, 4) if isinstance(va, (int, float)) and isinstance(vb, (int, float)) else None
        rows.append({"scope": key[0], "grp": key[1], "a": va, "n_a": na, "b": vb, "n_b": nb, "delta": delta})
    return rows


def _resolve_db(arg: str | None, man: dict) -> Path | None:
    for cand in (arg, man.get("db")):
        if cand and Path(cand).exists():
            return Path(cand)
    return None


def verify(db: Path | None, export: Path) -> dict | None:
    if db is None:
        return None
    try:
        import verify_run
    except ModuleNotFoundError:                      # scripts/ chưa có trong sys.path (gọi từ nơi khác)
        sys.path.insert(0, str(ROOT / "scripts"))
        import verify_run
    return verify_run.run(db, export)


def limits_for(db: Path | None, man: dict) -> tuple[list[str], str]:
    """(limits, nguồn): stats.overview(db) nếu có DB; else stats.build_limits trên overview tổng hợp từ manifest."""
    from orchestrator import stats
    if db is not None:
        try:
            ov = stats.overview(db, run_id=man.get("run_id"))
            return list(ov.get("limits") or []), "stats.overview(DB A)"
        except Exception as e:  # noqa: BLE001
            src = f"manifest (stats.overview lỗi: {e})"
    else:
        src = "manifest (không có DB)"
    c = man.get("counts") or {}
    kt = next((k.get("value") for k in man.get("kappa") or [] if k.get("scope") == "total"), None)
    ov = {"funnel": {"commits": c.get("commits", 0), "after_filter": c.get("commits", 0), "buggy": 0, "clean": 0,
                     "built": 0, "build_failed": len(man.get("build_failed") or []),
                     "skipped": len(man.get("skipped") or []), "infra_error": len(man.get("infra_error") or [])},
          "labels": {k: c.get(k, 0) for k in ("gold", "silver", "candidate", "verified_clean", "cheap_clean")},
          "kappa": {"total": kt}, "precision": None, "params_v1": man.get("params_v1") or {},
          "experiment": man.get("experiment")}
    try:
        return stats.build_limits(ov), src
    except Exception as e:  # noqa: BLE001
        return [f"(không sinh được giới hạn: {e})"], src


# ----------------------------------------------------------------------------- tổng hợp
def build(a: Path, b: Path, db_a: str | None = None, db_b: str | None = None) -> dict:
    from orchestrator import compare as cmpmod
    a, b = Path(a), Path(b)
    ma, mb = load_manifest(a), load_manifest(b)
    cmp = cmpmod.compare(a, b)
    dba, dbb = _resolve_db(db_a, ma), _resolve_db(db_b, mb)
    va, vb = verify(dba, a), verify(dbb, b)
    tools = compare_tools(ma, mb)
    mismatch = [t for t in tools if not t["match"]]
    lim, lim_src = limits_for(dba, ma)

    reasons: list[str] = []
    if cmp.get("warning"):
        reasons.append(cmp["warning"])
    if cmp.get("unexplained"):
        reasons.append(f"{len(cmp['unexplained'])} cụm lệch KHÔNG giải thích được (compare)")
    for name, v in (("A", va), ("B", vb)):
        if v is None:
            reasons.append(f"không có DB {name} để verify_run (truyền --db-{name.lower()})")
        elif not v["pass"]:
            reasons.append(f"verify_run {name} FAIL: " + ", ".join(c["id"] for c in v["checks"] if c["status"] == "FAIL"))
    ok = not reasons
    warn = [f"digest lệch/thiếu: {', '.join(t['tool'] for t in mismatch)}"] if mismatch else []
    if ma.get("orchestrator_git_sha") != mb.get("orchestrator_git_sha"):
        warn.append(f"orchestrator_git_sha khác: {ma.get('orchestrator_git_sha')} vs {mb.get('orchestrator_git_sha')}")
    if (ma.get("params_v1") or {}) != (mb.get("params_v1") or {}):
        warn.append("params_v1 khác giữa A và B")
    n_max = None
    for rm in ma.get("run_meta") or []:
        sc = rm.get("scope_json") or {}
        if isinstance(sc, dict) and sc.get("max"):
            n_max = sc["max"]
    return {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "a": {"export": str(a), "db": str(dba) if dba else None, "manifest": ma},
        "b": {"export": str(b), "db": str(dbb) if dbb else None, "manifest": mb},
        "tools": tools, "digest_mismatch": [t["tool"] for t in mismatch],
        "times": {"a": run_times(ma), "b": run_times(mb)},
        "speed": speed_info(),
        "compare": cmp, "diff_rows": diff_rows(cmp, ma, mb),
        "verify": {"a": va, "b": vb},
        "kappa": kappa_table(ma, mb),
        "limits": lim, "limits_source": lim_src,
        "conclusion": {"ok": ok, "reasons": reasons, "warnings": warn, "scope_max": n_max},
    }


# ----------------------------------------------------------------------------- markdown
def _f(v, nd=3):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def _short(d: str | None) -> str:
    if not d:
        return "—"
    d = str(d)
    return d.split("@")[-1][:19] if "@" in d or ":" in d else d[:19]


def to_markdown(rep: dict) -> str:
    ma, mb = rep["a"]["manifest"], rep["b"]["manifest"]
    ca, cb = ma.get("counts") or {}, mb.get("counts") or {}
    conc = rep["conclusion"]
    scope = f" `--max {conc['scope_max']}`" if conc.get("scope_max") else ""
    L = [f"# RESULTS — Nghiệm thu tái lập A/B{scope}", "",
         f"_Sinh lúc {rep['generated']} bởi `scripts/results_report.py`. Nhãn là ĐỒNG THUẬN MÁY (gold/silver/candidate), "
         f"không phải chân lý; xem §7._", "",
         f"- **A**: `{rep['a']['export']}` (run_id `{ma.get('run_id')}`, DB: `{rep['a']['db'] or 'không có'}`)",
         f"- **B**: `{rep['b']['export']}` (run_id `{mb.get('run_id')}`, DB: `{rep['b']['db'] or 'không có'}`)", ""]

    # 6 (đưa lên đầu để đọc nhanh)
    verdict = "✅ **ĐẠT tiêu chí tái lập**" if conc["ok"] else "❌ **CHƯA ĐẠT tiêu chí tái lập**"
    L += ["## Kết luận", "", verdict + (scope if conc["ok"] else "")]
    for r in conc["reasons"]:
        L.append(f"- lý do: {r}")
    for w in conc["warnings"]:
        L.append(f"- ⚠️ **{w}**")
    L.append("")

    # 1
    L += ["## 1. Cấu hình", "", "| | A | B | khớp |", "|---|---|---|:--:|"]
    pa, pb = ma.get("params_v1") or {}, mb.get("params_v1") or {}
    for k in sorted(set(pa) | set(pb)):
        L.append(f"| params_v1.{k} | {pa.get(k)} | {pb.get(k)} | {'✓' if pa.get(k) == pb.get(k) else '✗'} |")
    for k, lab in (("orchestrator_git_sha", "orchestrator_git_sha"), ("app_version", "app_version"),
                   ("docker_version", "docker_version"), ("os", "os"), ("experiment", "experiment")):
        L.append(f"| {lab} | {ma.get(k)} | {mb.get(k)} | {'✓' if ma.get(k) == mb.get(k) else '✗'} |")
    L += ["", "### Image digest", "", "| tool | image A | digest A | digest B | khớp |", "|---|---|---|---|:--:|"]
    for t in rep["tools"]:
        mark = "✓" if t["match"] else "🔴 **LỆCH**"
        L.append(f"| {t['tool']} | {t['image_a'] or '—'} | `{_short(t['digest_a'])}` | `{_short(t['digest_b'])}` | {mark} |")
    if rep["digest_mismatch"]:
        L.append("")
        L.append(f"🔴 **Cảnh báo:** digest lệch/thiếu ở {', '.join(rep['digest_mismatch'])} — A và B không chạy cùng "
                 f"bản tool; lệch nhãn có thể do tool, không phải do pipeline.")
    L.append("")

    # 2
    L += ["## 2. Phễu, nhãn và thời gian", "", "| chỉ số | A | B | Δ (B−A) |", "|---|---:|---:|---:|"]
    for k in ("commits", "clusters", "gold", "silver", "candidate", "verified_clean", "cheap_clean"):
        va, vb = ca.get(k), cb.get(k)
        d = (vb - va) if isinstance(va, int) and isinstance(vb, int) else None
        L.append(f"| {k} | {_f(va)} | {_f(vb)} | {_f(d)} |")
    for k in ("build_failed", "infra_error", "skipped", "tool_timeout", "tool_error"):
        L.append(f"| {k} | {len(ma.get(k) or [])} | {len(mb.get(k) or [])} | "
                 f"{len(mb.get(k) or []) - len(ma.get(k) or [])} |")
    ta, tb = rep["times"]["a"], rep["times"]["b"]
    L += ["", "| thời gian | A | B |", "|---|---|---|",
          f"| started (run_meta) | {ta['started']} | {tb['started']} |",
          f"| finished | {ta['finished']} | {tb['finished']} |",
          f"| thời lượng (giờ) | {_f(ta['hours'])} | {_f(tb['hours'])} |",
          f"| commit/giờ | {_f(ta['commits_per_hour'], 1)} | {_f(tb['commits_per_hour'], 1)} |",
          f"| tier có run_meta | {', '.join(ta['tiers']) or '—'} | {', '.join(tb['tiers']) or '—'} |"]
    for t, name in ((ta, "A"), (tb, "B")):
        if t.get("note"):
            L.append(f"\n> {name}: {t['note']}")
    sp = rep.get("speed")
    if sp:
        L += ["", f"Build (speed.json, nguồn **{sp.get('source')}**, samples={sp.get('samples')}): "
                  f"cold {_f(sp.get('build_cold_s'), 0)} s · warm {_f(sp.get('build_warm_s'), 0)} s · "
                  f"FSB {_f(sp.get('fsb_s'), 0)} s · Sonar {_f(sp.get('sonar_s'), 0)} s · "
                  f"rẻ {_f(sp.get('cheap_s_per_commit'), 0)} s/commit."]
    L.append("")

    # 3
    c = rep["compare"]
    L += ["## 3. So sánh cụm A/B (`orchestrator.compare`, theo cluster_key)", "",
          "| same | only_a | only_b | label_changed | giải thích được | KHÔNG giải thích |", "|---:|---:|---:|---:|---|---:|",
          f"| {c['same']} | {len(c['only_a'])} | {len(c['only_b'])} | {len(c['label_changed'])} | "
          f"{', '.join(f'{k}={v}' for k, v in (c.get('explained_by') or {}).items() if v) or '—'} | "
          f"**{len(c['unexplained'])}** |"]
    if c.get("warning"):
        L.append(f"\n⚠️ {c['warning']}")
    if rep["diff_rows"]:
        L += ["", f"Cụm lệch (tối đa {MAX_DIFF_ROWS}, chưa giải thích xếp trước):", "",
              "| loại | commit | file | nhóm | nhãn | lý do |", "|---|---|---|---|---|---|"]
        for r in rep["diff_rows"]:
            L.append(f"| {r['kind']} | {r['commit'][:8]} | {r['file_path']} | {r['cwe_group']} | {r['label']} | {r['reason']} |")
    L.append("")

    # 4
    L += ["## 4. verify_run (CONTRACTS §1/§4/§6)", ""]
    for name in ("a", "b"):
        v = rep["verify"][name]
        if v is None:
            L.append(f"- **{name.upper()}**: bỏ qua (không có DB).")
            continue
        n_fail = v["n_fail"]
        L.append(f"- **{name.upper()}**: {'PASS' if v['pass'] else 'FAIL'} ({len(v['checks']) - n_fail}/{len(v['checks'])} mục)")
    ids = []
    for name in ("a", "b"):
        for ch in (rep["verify"][name] or {}).get("checks", []):
            if ch["id"] not in ids:
                ids.append(ch["id"])
    if ids:
        L += ["", "| mục | A | B |", "|---|---|---|"]
        for cid in ids:
            cells = []
            for name in ("a", "b"):
                v = rep["verify"][name]
                ch = next((x for x in (v or {}).get("checks", []) if x["id"] == cid), None)
                cells.append("—" if ch is None else ("✓" if ch["status"] == "PASS" else
                                                     ("skip" if ch["status"] == "SKIP" else f"✗ {ch['detail'][:80]}")))
            L.append(f"| {cid} | {cells[0]} | {cells[1]} |")
    L.append("")

    # 5
    L += ["## 5. Fleiss' κ A vs B", "", "| scope | nhóm | κ A (n) | κ B (n) | Δ |", "|---|---|---:|---:|---:|"]
    for r in rep["kappa"]:
        if r["scope"] == "pair" and len(rep["kappa"]) > 25:
            continue
        L.append(f"| {r['scope']} | {r['grp'] or '—'} | {_f(r['a'])} ({_f(r['n_a'])}) | {_f(r['b'])} ({_f(r['n_b'])}) | {_f(r['delta'])} |")
    L += ["", "κ âm = tool phủ miền rời nhau (bình thường trên mọi repo); so Δ giữa A/B, không so giá trị tuyệt đối.", ""]

    # 6 chi tiết tiêu chí
    L += ["## 6. Tiêu chí tái lập", "",
          "ĐẠT khi: `compare.unexplained = 0` (mọi lệch được giải thích bởi tool_timeout/infra_error/skipped/build_failed) "
          "**và** `verify_run` PASS cho cả A và B. Digest/params/git sha lệch là cảnh báo (làm lệch nhãn không quy được "
          "cho pipeline).", ""]

    # 7
    L += ["## 7. Giới hạn (từ `stats.limits`, nguồn: " + rep["limits_source"] + ")", ""]
    L += [f"- {s}" for s in rep["limits"]] or ["- (không có)"]
    L.append("")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", required=True, help="thư mục export A")
    ap.add_argument("--b", required=True, help="thư mục export B")
    ap.add_argument("--db-a", default=None)
    ap.add_argument("--db-b", default=None)
    ap.add_argument("--out", default="RESULTS.md")
    ap.add_argument("--json", action="store_true", help="in JSON dữ liệu báo cáo ra stdout")
    a = ap.parse_args(argv)
    for p in (a.a, a.b):
        if not Path(p).is_dir():
            print(f"không thấy thư mục export {p}", file=sys.stderr)
            return 2
    rep = build(Path(a.a), Path(a.b), a.db_a, a.db_b)
    md = to_markdown(rep)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(md)
    if a.json:
        slim = {k: v for k, v in rep.items() if k not in ("a", "b")}
        slim["a"] = {k: rep["a"][k] for k in ("export", "db")}
        slim["b"] = {k: rep["b"][k] for k in ("export", "db")}
        print(json.dumps(slim, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"{'ĐẠT' if rep['conclusion']['ok'] else 'CHƯA ĐẠT'} -> {out}")
        for r in rep["conclusion"]["reasons"]:
            print(f"  - {r}")
    return 0 if rep["conclusion"]["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
