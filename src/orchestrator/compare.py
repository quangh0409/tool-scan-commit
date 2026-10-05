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
_ALL_EXPLAIN = EXPLAIN_KEYS + ("build_failed",)


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
    diffs = ([("only_a", k, A["rows"][k]) for k in only_a] + [("only_b", k, B["rows"][k]) for k in only_b]
             + [("label_changed", k, A["rows"][k]) for k in changed])
    for kind, k, row in diffs:
        r = _reason(row["commit"])
        if r:
            explained[r] += 1
        else:
            unexplained.append({"kind": kind, "cluster_key": k, "commit": row["commit"],
                                "file_path": row["file_path"], "cwe_group": row["cwe_group"]})
    res = {
        "a": {"path": A["path"], "kind": A["kind"], "n": len(ka), "line_window": A["line_window"]},
        "b": {"path": B["path"], "kind": B["kind"], "n": len(kb), "line_window": B["line_window"]},
        "same": len(same),
        "only_a": [{"cluster_key": k, **A["rows"][k]} for k in only_a],
        "only_b": [{"cluster_key": k, **B["rows"][k]} for k in only_b],
        "label_changed": [{"cluster_key": k, "a": A["rows"][k]["label"], "b": B["rows"][k]["label"],
                           "commit": A["rows"][k]["commit"], "file_path": A["rows"][k]["file_path"]}
                          for k in changed],
        "explained_by": {k: explained[k] for k in EXPLAIN_KEYS} | {"build_failed": explained["build_failed"]},
        "unexplained": unexplained,
        "ok": not unexplained,
    }
    if A["line_window"] and B["line_window"] and A["line_window"] != B["line_window"]:
        res["warning"] = (f"line_window khác nhau ({A['line_window']} vs {B['line_window']}) -> cluster_key "
                          "không tương thích; so sánh chỉ mang tính tham khảo")
        res["ok"] = False
    return res


def to_markdown(res: dict) -> str:
    L = [f"# compare A/B — {'KHỚP' if res['ok'] else 'LỆCH'}", "",
         f"- A: `{res['a']['path']}` ({res['a']['kind']}, {res['a']['n']} cụm)",
         f"- B: `{res['b']['path']}` ({res['b']['kind']}, {res['b']['n']} cụm)",
         f"- same: **{res['same']}** · only_a: {len(res['only_a'])} · only_b: {len(res['only_b'])} · "
         f"label_changed: {len(res['label_changed'])}",
         f"- giải thích được: {res['explained_by']} · KHÔNG giải thích: {len(res['unexplained'])}"]
    if res.get("warning"):
        L.append(f"- ⚠ {res['warning']}")
    if res["unexplained"]:
        L += ["", "| loại | commit | file | nhóm |", "|---|---|---|---|"]
        L += [f"| {u['kind']} | {str(u['commit'])[:8]} | {u['file_path']} | {u['cwe_group']} |"
              for u in res["unexplained"][:50]]
    if res["label_changed"]:
        L += ["", "| commit | file | A | B |", "|---|---|---|---|"]
        L += [f"| {str(c['commit'])[:8]} | {c['file_path']} | {c['a']} | {c['b']} |" for c in res["label_changed"][:50]]
    return "\n".join(L) + "\n"
