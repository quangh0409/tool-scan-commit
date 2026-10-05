"""So sánh A/B hai run theo cluster_key (CONTRACTS §11 `compare`). Stdlib-only.

Mỗi phía = export dir (đọc dataset.jsonl, có `cluster_key` hoặc tính bằng keys.cluster_key)
hoặc file DB SQLite (tính cluster_key từ bảng findings). Lệch được "giải thích" khi commit của cụm
nằm trong run_manifest.json {tool_timeout, infra_error, skipped, build_failed} của A hoặc B
(DB: suy từ expensive_runs.status). Exit 0 nếu khớp hoặc mọi lệch đều được giải thích, 1 nếu không.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import keys

EXPLAIN_KEYS = ("tool_timeout", "infra_error", "skipped")
# manifest A1 có thêm tool_error[] và cheap_infra_error[] ({commit, tool, tier}); build_failed[] từ selected_commits
_ALL_EXPLAIN = EXPLAIN_KEYS + ("build_failed", "tool_error", "cheap_infra_error")


def _row_key(row: dict, line_window: int | None = None) -> str:
    ck = row.get("cluster_key")
    if ck:
        return ck
    return keys.cluster_key(row.get("repo", ""), row.get("commit_id", ""), row.get("file_path", ""),
                            row.get("cwe_group") or "", int(row.get("s_line") or 0), line_window)


def load_side(path: str | Path) -> dict:
    """-> {"kind": "export|db", "path", "rows": {cluster_key: {commit, label, file_path, cwe_group, s_line}},
            "explain": {reason: set(commit_id)}, "line_window": int|None}"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    if p.is_dir():
        return _load_export(p)
    return _load_db(p)


def _load_export(d: Path) -> dict:
    ds = d / "dataset.jsonl"
    if not ds.exists():
        raise FileNotFoundError(f"{ds} không có (export chưa gộp jsonl?)")
    manifest: dict = {}
    mf = d / "run_manifest.json"
    if mf.exists():
        try:
            manifest = json.loads(mf.read_text(encoding="utf-8"))
        except ValueError:
            manifest = {}
    lw = None
    try:
        lw = int((manifest.get("params_v1") or {}).get("line_window") or 0) or None
    except (TypeError, ValueError):
        lw = None
    rows: dict[str, dict] = {}
    with open(ds, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            rows[_row_key(r, lw)] = {"commit": r.get("commit_id"), "label": r.get("label"),
                                     "file_path": r.get("file_path"), "cwe_group": r.get("cwe_group"),
                                     "s_line": r.get("s_line")}
    explain = {k: set(_shas(manifest.get(k))) for k in _ALL_EXPLAIN}
    return {"kind": "export", "path": str(d), "rows": rows, "explain": explain, "line_window": lw,
            "manifest": bool(manifest)}


def _shas(v) -> list[str]:
    if not v:
        return []
    out = []
    for x in v:
        if isinstance(x, dict):
            x = x.get("commit") or x.get("commit_id") or x.get("sha")
        if x:
            out.append(str(x))
    return out


def _load_db(db: Path) -> dict:
    conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        tabs = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        lw = None
        if "run_meta" in tabs:
            r = conn.execute("SELECT line_window FROM run_meta ORDER BY id DESC LIMIT 1").fetchone()
            lw = int(r[0]) if r and r[0] else None
        rows: dict[str, dict] = {}
        for repo, cid, fp, grp, s_line, label in conn.execute(
                "SELECT repo, commit_id, file_path, cwe_group, s_line, label FROM findings"):
            ck = keys.cluster_key(repo or "", cid, fp, grp or "", int(s_line or 0), lw)
            rows[ck] = {"commit": cid, "label": label, "file_path": fp, "cwe_group": grp, "s_line": s_line}
        explain = {k: set() for k in _ALL_EXPLAIN}
        if "expensive_runs" in tabs:
            for cid, st in conn.execute("SELECT DISTINCT commit_id, status FROM expensive_runs"):
                if st in explain:
                    explain[st].add(cid)
        if "scan_tool_errors" in tabs:
            for cid, kind in conn.execute("SELECT DISTINCT commit_id, kind FROM scan_tool_errors"):
                key = "cheap_infra_error" if kind == "infra_error" else ("tool_error" if kind == "tool_error" else kind)
                if key in explain:
                    explain[key].add(cid)
        if "selected_commits" in tabs:
            for (cid,) in conn.execute("SELECT commit_id FROM selected_commits WHERE status='build_failed'"):
                explain["build_failed"].add(cid)
        return {"kind": "db", "path": str(db), "rows": rows, "explain": explain, "line_window": lw,
                "manifest": "expensive_runs" in tabs}
    finally:
        conn.close()


def compare(a: str | Path, b: str | Path) -> dict:
    A, B = load_side(a), load_side(b)
    ka, kb = set(A["rows"]), set(B["rows"])
    same = sorted(k for k in ka & kb if A["rows"][k]["label"] == B["rows"][k]["label"])
    changed = sorted(k for k in ka & kb if A["rows"][k]["label"] != B["rows"][k]["label"])
    only_a, only_b = sorted(ka - kb), sorted(kb - ka)

    def _reason(commit: str) -> str | None:
        for r in _ALL_EXPLAIN:
            if commit in A["explain"][r] or commit in B["explain"][r]:
                return r
        return None

    explained = {k: 0 for k in _ALL_EXPLAIN}
    unexplained: list[dict] = []
    diff_rows: list[dict] = []
    diffs = ([("only_a", k, A["rows"][k]) for k in only_a] + [("only_b", k, B["rows"][k]) for k in only_b]
             + [("label_changed", k, A["rows"][k]) for k in changed])
    for kind, k, row in diffs:
        r = _reason(row["commit"])
        la = A["rows"][k]["label"] if k in A["rows"] else None
        lb = B["rows"][k]["label"] if k in B["rows"] else None
        diff_rows.append({"kind": kind, "cluster_key": k, "commit": row["commit"], "file_path": row["file_path"],
                          "cwe_group": row["cwe_group"], "s_line": row.get("s_line"), "a": la, "b": lb,
                          "reason": r or "unexplained"})
        if r:
            explained[r] += 1
        else:
            unexplained.append({"kind": kind, "cluster_key": k, "commit": row["commit"],
                                "file_path": row["file_path"], "cwe_group": row["cwe_group"]})
    diff_rows.sort(key=lambda d: (d["reason"] != "unexplained", d["kind"], str(d["commit"]), str(d["file_path"])))
    res = {
        "a": {"path": A["path"], "kind": A["kind"], "n": len(ka), "line_window": A["line_window"]},
        "b": {"path": B["path"], "kind": B["kind"], "n": len(kb), "line_window": B["line_window"]},
        "same": len(same),
        "only_a": [{"cluster_key": k, **A["rows"][k]} for k in only_a],
        "only_b": [{"cluster_key": k, **B["rows"][k]} for k in only_b],
        "label_changed": [{"cluster_key": k, "a": A["rows"][k]["label"], "b": B["rows"][k]["label"],
                           "commit": A["rows"][k]["commit"], "file_path": A["rows"][k]["file_path"]}
                          for k in changed],
        "explained_by": {k: explained[k] for k in _ALL_EXPLAIN},
        "unexplained": unexplained,
        "diffs": diff_rows,
        "ok": not unexplained,
    }
    if A["line_window"] and B["line_window"] and A["line_window"] != B["line_window"]:
        res["warning"] = (f"line_window khác nhau ({A['line_window']} vs {B['line_window']}) -> cluster_key "
                          "không tương thích; so sánh chỉ mang tính tham khảo")
        res["ok"] = False
    return res


MD_MAX_DIFFS = 20


def _md_cell(v) -> str:
    return str("" if v is None else v).replace("|", "\\|").replace("\n", " ")


def to_markdown(res: dict, max_diffs: int = MD_MAX_DIFFS) -> str:
    """Bảng Markdown dán thẳng vào RESULTS.md (§ tái lập Run A ↔ Run B)."""
    ex = res["explained_by"]
    n_ex = sum(ex.values())
    n_un = len(res["unexplained"])
    verdict = "KHỚP" if res["ok"] else "LỆCH"
    L = [f"### Tái lập A ↔ B — **{verdict}** (compare theo `cluster_key`)", "",
         f"- A: `{res['a']['path']}` ({res['a']['kind']}, {res['a']['n']} cụm, LINE_WINDOW={res['a']['line_window']})",
         f"- B: `{res['b']['path']}` ({res['b']['kind']}, {res['b']['n']} cụm, LINE_WINDOW={res['b']['line_window']})"]
    if res.get("warning"):
        L.append(f"- ⚠ {res['warning']}")
    L += ["", "| Chỉ số | Số cụm |", "|---|---:|",
          f"| same (cùng khoá, cùng nhãn) | {res['same']} |",
          f"| only_a | {len(res['only_a'])} |",
          f"| only_b | {len(res['only_b'])} |",
          f"| label_changed | {len(res['label_changed'])} |",
          f"| lệch giải thích được (manifest) | {n_ex} |",
          f"| lệch KHÔNG giải thích | **{n_un}** |",
          "", "| Lý do (manifest) | Số cụm lệch |", "|---|---:|"]
    L += [f"| {k} | {v} |" for k, v in ex.items()]
    diffs = res.get("diffs") or []
    if diffs:
        shown = diffs[:max_diffs]
        L += ["", f"**Cụm lệch** ({len(shown)}/{len(diffs)} dòng; chưa giải thích xếp trước):", "",
              "| # | Loại | Commit | File | Nhóm CWE | Dòng | Nhãn A | Nhãn B | Lý do |",
              "|--:|---|---|---|---|--:|---|---|---|"]
        for i, d in enumerate(shown, 1):
            reason = "**KHÔNG giải thích**" if d["reason"] == "unexplained" else d["reason"]
            L.append(f"| {i} | {d['kind']} | `{str(d['commit'])[:8]}` | `{_md_cell(d['file_path'])}` | "
                     f"{_md_cell(d['cwe_group'])} | {_md_cell(d.get('s_line'))} | {_md_cell(d['a'])} | "
                     f"{_md_cell(d['b'])} | {reason} |")
        if len(diffs) > max_diffs:
            L.append(f"| … | | | *còn {len(diffs) - max_diffs} cụm — xem `--format json`* | | | | | |")
    L += ["", f"Kết luận: {'cùng số cụm theo nhãn hoặc lệch chỉ ở commit tool_timeout/infra_error/skipped/build_failed của manifest — ĐẠT tiêu chí tái lập (METHODOLOGY §6).' if res['ok'] else f'{n_un} cụm lệch không nằm trong manifest — CHƯA đạt; cần xem lại tool/raw của các commit trên.'}"]
    return "\n".join(L) + "\n"
