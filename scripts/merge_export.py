#!/usr/bin/env python3
"""Gộp thư mục export per-commit thành dataset.jsonl + commits.jsonl.

Quy ước (chốt từ các run spring-cloud-kubernetes / train-ticket / mall-swarm):
- dataset.jsonl : concat mọi label.json (1 dòng = 1 CỤM finding; chỉ commit có finding).
- commits.jsonl : 1 dòng = 1 COMMIT (đủ mọi commit trong commit_features):
    commit_id, repo, author, author_date, kamei{14}, labels{}, role, negative_level.

Dùng:
    python3 scripts/merge_export.py <export_dir> <db.sqlite>
Ví dụ:
    python3 scripts/merge_export.py data/export_giraph data/dataset_giraph.sqlite
"""
import json
import sqlite3
import sys
from pathlib import Path

KAMEI = ["ns", "nd", "nf", "entropy", "la", "ld", "lt", "fix",
         "ndev", "age", "nuc", "exp", "rexp", "sexp"]


def main(export_dir: str, db_path: str) -> None:
    export = Path(export_dir)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    roles = {r["commit_id"]: r["role"]
             for r in con.execute("SELECT commit_id, role FROM selected_commits")}

    # ---- dataset.jsonl: concat label.json (thứ tự theo author_date để ổn định) ----
    order = [r["commit_id"] for r in con.execute(
        "SELECT commit_id FROM commit_features ORDER BY author_date, commit_id")]
    n_rows = 0
    with open(export / "dataset.jsonl", "w", encoding="utf-8") as out:
        for sha in order:
            f = export / sha[:12] / "label.json"
            if not f.exists():
                continue
            for row in json.loads(f.read_text(encoding="utf-8")):
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                n_rows += 1

    # ---- commits.jsonl: mọi commit, kamei + labels + role + negative_level ----
    n_commits = 0
    with open(export / "commits.jsonl", "w", encoding="utf-8") as out:
        for r in con.execute(
                "SELECT * FROM commit_features ORDER BY author_date, commit_id"):
            sha = r["commit_id"]
            summary = export / sha[:12] / "summary.json"
            labels, neg = {}, None
            if summary.exists():
                s = json.loads(summary.read_text(encoding="utf-8"))
                labels = s.get("labels") or {}
                neg = s.get("negative_level")
            out.write(json.dumps({
                "commit_id": sha,
                "repo": r["repo"],
                "author": r["author"],
                "author_date": r["author_date"],
                "kamei": {k: r[k] for k in KAMEI},
                "labels": labels,
                "role": roles.get(sha),
                "negative_level": neg,
            }, ensure_ascii=False) + "\n")
            n_commits += 1

    print(f"dataset.jsonl : {n_rows} dòng (cụm finding)")
    print(f"commits.jsonl : {n_commits} dòng (commit)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
