"""
(C) Export dataset ra FILE trực quan (CONTRACTS §6) — MỖI RUN MỘT THƯ MỤC, không ghi đè/trộn:
  <out>/
    run_manifest.json   profile, run_meta (2 tier), kappa, counts, build_failed[], infra_error[],
                        tool_timeout[], skipped[], orchestrator_git_sha, app_version, os, docker_version,
                        started, finished, params_v1, experiment
    dataset.jsonl       1 dòng = 1 CỤM finding (+ cluster_key, evidence{consensus, validation})
    commits.jsonl       1 dòng = 1 COMMIT (+ n_expensive_ok, negative_level)
    negatives.json      danh sách NEGATIVE (verified-clean / cheap-clean)
    SHA256SUMS          dataset.jsonl, commits.jsonl, run_manifest.json
    <commit12>/
      <tool>.raw.<ext>       (B) output THÔ nguyên bản MỖI tool (sarif/xml/json/jsonl)
      <tool>.findings.json   parsed finding của TỪNG tool (từ raw_findings)
      label.json             cụm đã gộp + nhãn gold/silver/candidate
      summary.json           meta commit + đếm nhãn
Số tool = 5 rẻ + (2 hoặc 3 đắt tuỳ CodeQL bật/tắt) = 7 hoặc 8; KHÔNG cố định.

D5: thư mục đích đã có dữ liệu -> ghi vào `<out>_2`, `_3`… và cảnh báo (không trộn run cũ/mới).
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import time
from collections import Counter
from pathlib import Path

from . import config, keys, progress
from .storage.sqlite_store import SQLiteStore
from .tools.base import app_version, docker_version, orchestrator_git_sha

_JSON_COLS = ("cwe", "agreeing_tools", "s_detail_line", "diff_parsed", "kamei")
KAMEI = ["ns", "nd", "nf", "entropy", "la", "ld", "lt", "fix",
         "ndev", "age", "nuc", "exp", "rexp", "sexp"]
MANIFEST = "run_manifest.json"
SUMS_FILES = ("dataset.jsonl", "commits.jsonl", MANIFEST)


def _decode(row: dict) -> dict:
    """Parse các cột JSON-text về object cho dễ đọc."""
    out = dict(row)
    for c in _JSON_COLS:
        if isinstance(out.get(c), str):
            try:
                out[c] = json.loads(out[c])
            except (ValueError, TypeError):
                pass
    return out


def _w(path: Path, obj) -> None:
    # newline="\n": byte giống nhau trên Windows/Linux -> SHA256SUMS của run_manifest.json tái lập được
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)


def _wt(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def params_v1_from_config() -> dict:
    return {"line_window": config.LINE_WINDOW, "gold_min_expensive": config.GOLD_MIN_EXPENSIVE,
            "gold_allow_1exp_1cheap": config.GOLD_ALLOW_1EXP_1CHEAP,
            "silver_min_cheap": config.SILVER_MIN_CHEAP, "noise_cwe": sorted(config.NOISE_CWE)}


def _experiment() -> dict | None:
    if os.environ.get("ORCH_EXPERIMENT") == "1":
        return {"enabled": True, "reason": os.environ.get("ORCH_EXPERIMENT_REASON", "")}
    return None


EXP_SUFFIX = "_exp"


def resolve_out_dir(out_dir: Path) -> Path:
    """D5: nếu thư mục đích đã có dữ liệu -> trả thư mục mới hậu tố _2, _3… (không trộn).
    Chế độ thí nghiệm (ORCH_EXPERIMENT=1, CONTRACTS §2): gắn hậu tố `_exp` TRƯỚC khi xét `_2/_3`
    -> export thí nghiệm không bao giờ nằm chung tên với export v1."""
    out_dir = Path(out_dir)
    if os.environ.get("ORCH_EXPERIMENT") == "1" and not out_dir.name.endswith(EXP_SUFFIX):
        out_dir = out_dir.with_name(out_dir.name + EXP_SUFFIX)
    if not out_dir.exists() or not any(out_dir.iterdir()):
        return out_dir
    base = str(out_dir).rstrip("/\\")
    for i in range(2, 1000):
        cand = Path(f"{base}_{i}")
        if not cand.exists() or not any(cand.iterdir()):
            print(f"!! CẢNH BÁO: {out_dir} đã có dữ liệu (run khác) -> export sang {cand} (không trộn).")
            return cand
    raise RuntimeError(f"quá nhiều thư mục export cạnh {out_dir}")


def _validation(pairs) -> str:
    """Gộp verdict nhiều rater -> TP|FP|unclear; không có -> unreviewed.
    Ưu tiên rater 'adjudicated' > đa số > hoà = unclear (review.validation_of)."""
    from .review import validation_of
    return validation_of(pairs)


def enrich_row(row: dict, reviews: dict[str, list[str]] | None = None) -> dict:
    """Thêm cluster_key + evidence vào 1 dòng findings (đã _decode)."""
    r = dict(row)
    ck = keys.cluster_key(r.get("repo") or "", r.get("commit_id") or "", r.get("file_path") or "",
                          r.get("cwe_group") or "", int(r.get("s_line") or 0))
    r["cluster_key"] = ck
    r["evidence"] = {"consensus": r.get("label") or r.get("silver_label") or "candidate",
                     "validation": _validation((reviews or {}).get(ck))}
    return r


def _commit_order(store: SQLiteStore, commit_ids: list[str]) -> list[str]:
    """Thứ tự ổn định: theo author_date (commit_features) rồi commit_id; commit thiếu feature ở cuối."""
    feats = store.commit_features_rows()
    pos = {r["commit_id"]: i for i, r in enumerate(feats)}
    return sorted(commit_ids, key=lambda c: (pos.get(c, 10**9), c))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_sums(out_dir: Path) -> Path:
    lines = [f"{_sha256(out_dir / n)}  {n}" for n in SUMS_FILES if (out_dir / n).exists()]
    p = out_dir / "SHA256SUMS"
    _wt(p, "\n".join(lines) + "\n")
    return p


def write_merged(store: SQLiteStore, out_dir: Path) -> dict:
    """dataset.jsonl + commits.jsonl THẲNG từ DB (thay scripts/merge_export.py cũ).
    - dataset.jsonl: mọi cụm findings, thứ tự author_date, + cluster_key + evidence.
    - commits.jsonl: mọi commit trong commit_features (+ commit có finding nhưng thiếu feature),
      kamei + labels + role + status + n_expensive_ok + negative_level."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    reviews = store.gold_review_verdicts()
    selected = store.selected_rows()
    ids = store.all_commit_ids()
    order = _commit_order(store, ids)

    n_rows = 0
    labels_by_commit: dict[str, dict] = {}
    with open(out_dir / "dataset.jsonl", "w", encoding="utf-8", newline="\n") as out:
        for cid in order:
            rows = [enrich_row(_decode(r), reviews) for r in store.findings_for_commit(cid)]
            labels_by_commit[cid] = dict(Counter(r.get("label") for r in rows))
            for r in rows:
                out.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
                n_rows += 1

    feats = store.commit_features_rows()
    feat_ids = {r["commit_id"] for r in feats}
    extra = [{"commit_id": c, "repo": None, "author": None, "author_date": None}
             for c in order if c not in feat_ids]
    n_commits = 0
    with open(out_dir / "commits.jsonl", "w", encoding="utf-8", newline="\n") as out:
        for r in [*feats, *extra]:
            sha = r["commit_id"]
            sel = selected.get(sha) or {}
            out.write(json.dumps({
                "commit_id": sha,
                "repo": r.get("repo"),
                "author": r.get("author"),
                "author_date": r.get("author_date"),
                "kamei": {k: r.get(k) for k in KAMEI} if sha in feat_ids else None,
                "labels": labels_by_commit.get(sha, {}),
                "role": sel.get("role"),
                "status": sel.get("status"),
                "build_status": sel.get("build_status"),
                "n_expensive_ok": store.n_expensive_ok(sha),
                "negative_level": store.negative_level(sha),
            }, ensure_ascii=False, default=str) + "\n")
            n_commits += 1
    return {"dataset_rows": n_rows, "commits_rows": n_commits}


def build_manifest(store: SQLiteStore, out_dir: Path, counts: dict, profile: dict | None,
                   started: str | None, run_id: str | None = None) -> dict:
    by_status = store.commits_by_expensive_status()
    errs = store.tool_errors_all()          # cả tầng rẻ (scan_tool_errors) + đắt (expensive_runs)

    def _errs(kind):
        return [{"commit": e["commit"], "tool": e["tool"], "tier": e["tier"]} for e in errs if e["kind"] == kind]
    return {
        "schema": 1,
        "run_id": run_id or progress.run_id(),
        "db": str(store.path),
        "export_dir": str(out_dir),
        "profile": profile,
        "run_meta": store.run_meta_rows(),
        "kappa": store.kappa_rows(),
        "counts": counts,
        "build_failed": by_status.get("build_failed", []),
        "infra_error": by_status.get("infra_error", []),
        # {commit, tool, tier} — gồm cả tầng rẻ; compare._shas đọc được cả dạng này
        "tool_timeout": _errs("tool_timeout"),
        "tool_error": _errs("tool_error"),
        "cheap_infra_error": _errs("infra_error"),
        "skipped": by_status.get("skipped", []),
        "orchestrator_git_sha": orchestrator_git_sha(),
        "app_version": app_version(),
        "os": platform.platform(),
        "python": platform.python_version(),
        "docker_version": docker_version(),
        "started": started,
        "finished": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "params_v1": params_v1_from_config(),
        "experiment": _experiment(),
    }


def export_all(store: SQLiteStore, out_dir: Path, profile: dict | None = None,
               run_id: str | None = None) -> dict:
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    out_dir = resolve_out_dir(Path(out_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    reviews = store.gold_review_verdicts()
    n_commit = n_raw = 0
    negatives = []
    label_counter: Counter = Counter()
    for cid in store.all_commit_ids():
        d = out_dir / cid[:12]
        d.mkdir(parents=True, exist_ok=True)

        # (B) output thô mỗi tool
        for tool, fmt, content in store.raw_output_for_commit(cid):
            _wt(d / f"{tool}.raw.{fmt}", content or "")
            n_raw += 1

        # (C) parsed finding theo từng tool
        by_tool: dict[str, list] = {}
        for f in store.raw_for_commit(cid):
            by_tool.setdefault(f.tool, []).append(f.as_dict())
        for tool, items in by_tool.items():
            _w(d / f"{tool}.findings.json", items)

        # (C) nhãn tổng hợp (+ cluster_key, evidence)
        rows = [enrich_row(_decode(r), reviews) for r in store.findings_for_commit(cid)]
        _w(d / "label.json", rows)
        label_counter.update(r.get("label") for r in rows if r.get("label"))

        neg = store.negative_level(cid)   # verified-clean | cheap-clean | None
        n_ok = store.n_expensive_ok(cid)
        if neg:
            negatives.append({"commit_id": cid, "level": neg, "n_expensive_ok": n_ok,
                              "tools": sorted(by_tool)})
        _w(d / "summary.json", {
            "commit_id": cid,
            "tools_reported": sorted(by_tool),
            "n_cluster_labeled": len(rows),
            "labels": dict(Counter(r.get("label") for r in rows)),
            "negative_level": neg,
            "n_expensive_ok": n_ok,
            "expensive_runs": store.expensive_runs_for_commit(cid),
            # 14 đặc trưng Kamei cấp commit — có cả với commit NEGATIVE (label.json rỗng)
            "kamei": store.features_for_commit(cid),
        })
        n_commit += 1

    # danh sách NEGATIVE mức toàn dataset (cheap-clean vs verified-clean GOLD)
    neg_counts = dict(Counter(x["level"] for x in negatives))
    _w(out_dir / "negatives.json", {"counts": neg_counts, "commits": negatives})

    merged = write_merged(store, out_dir)
    counts = {"gold": label_counter.get("gold", 0), "silver": label_counter.get("silver", 0),
              "candidate": label_counter.get("candidate", 0),
              "verified_clean": neg_counts.get("verified-clean", 0),
              "cheap_clean": neg_counts.get("cheap-clean", 0),
              "commits": n_commit, "clusters": merged["dataset_rows"]}
    _w(out_dir / MANIFEST, build_manifest(store, out_dir, counts, profile, started, run_id))
    write_sums(out_dir)
    return {"commits": n_commit, "raw_files": n_raw, "out": str(out_dir),
            "negatives": neg_counts, "counts": counts, **merged,
            "files": ["dataset.jsonl", "commits.jsonl", MANIFEST, "negatives.json", "SHA256SUMS"]}
