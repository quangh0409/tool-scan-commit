#!/usr/bin/env python3
"""Preset `sensitivity` với LINE_WINDOW=7 (giữ tên file cũ để tương thích runbook).

Trước đây script này relabel tay trên bản sao DB với W=7 cho 3 repo hardcode. Nay là wrapper của
`orchestrator.sensitivity.run` (A2): copy DB -> <out>/line_window-7.sqlite (và mốc v1 line_window-3),
relabel, ghi sensitivity.json/.md; thêm `positive_gold_w7.jsonl` (cụm gold @W7, có cluster_key/evidence)
để so với gold_set @W3. DB gốc KHÔNG bị đụng.

Dùng:
  PYTHONPATH=src python scripts/relabel_gold_w7.py --db data/dataset_x.sqlite --out data/sens_x [--repo URL]
Tương đương CLI: python -m orchestrator.cli sensitivity --db <db> --out <out> --grid line_window=7
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

WINDOW = 7


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", required=True, help="DB nguồn (chỉ đọc; relabel trên bản sao)")
    p.add_argument("--out", required=True, help="thư mục kết quả sensitivity")
    p.add_argument("--repo", default=None, help="URL repo (mặc định suy từ DB)")
    p.add_argument("--window", type=int, default=WINDOW)
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)

    from orchestrator import sensitivity, export_dataset
    from orchestrator.storage.sqlite_store import SQLiteStore

    res = sensitivity.run(Path(a.db), Path(a.out), {"line_window": [a.window]}, repo=a.repo)
    w7 = next((r for r in res["results"] if r["params"].get("line_window") == a.window), None)
    gold_out = None
    if w7:
        store = SQLiteStore(Path(w7["db"]), readonly=True)
        try:
            reviews = store.gold_review_verdicts()
            rows = [export_dataset.enrich_row(export_dataset._decode(r), reviews)
                    for r in store.findings_rows(label="gold")]
        finally:
            store.close()
        gold_out = Path(a.out) / f"positive_gold_w{a.window}.jsonl"
        with open(gold_out, "w", encoding="utf-8", newline="\n") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    summary = {"out": a.out, "results": [{k: r[k] for k in ("name", "gold", "silver", "candidate", "kappa")}
                                         for r in res["results"]],
               "positive_gold_w7": str(gold_out) if gold_out else None}
    if a.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        for r in summary["results"]:
            print(f"  {r['name']:28} gold={r['gold']:5} silver={r['silver']:5} candidate={r['candidate']:5}")
        print(f"-> {a.out}/sensitivity.md" + (f" | {gold_out}" if gold_out else ""))
        print("Lưu ý: gold mới sinh khi nới window cần kiểm tay (review sample) trước khi dùng.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
