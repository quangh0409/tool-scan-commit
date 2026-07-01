"""
(C) Export dataset ra FILE trực quan — mỗi commit 1 thư mục:
  <out>/<commit12>/
    <tool>.raw.<ext>       (B) output THÔ nguyên bản MỖI tool (sarif/xml/json/jsonl)
    <tool>.findings.json   parsed finding của TỪNG tool (từ raw_findings)  ← "N file scan"
    label.json             cụm đã gộp + nhãn gold/silver/candidate         ← "1 file gán nhãn"
    summary.json           meta commit + đếm nhãn
Số tool = 5 rẻ + (2 hoặc 3 đắt tuỳ CodeQL bật/tắt) = 7 hoặc 8; KHÔNG cố định.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from . import config
from .storage.sqlite_store import SQLiteStore

_JSON_COLS = ("cwe", "agreeing_tools", "s_detail_line", "diff_parsed")


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
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def export_all(store: SQLiteStore, out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    n_commit = n_raw = 0
    for cid in store.all_commit_ids():
        d = out_dir / cid[:12]
        d.mkdir(parents=True, exist_ok=True)

        # (B) output thô mỗi tool
        for tool, fmt, content in store.raw_output_for_commit(cid):
            (d / f"{tool}.raw.{fmt}").write_text(content or "")
            n_raw += 1

        # (C) parsed finding theo từng tool
        by_tool: dict[str, list] = {}
        for f in store.raw_for_commit(cid):
            by_tool.setdefault(f.tool, []).append(f.as_dict())
        for tool, items in by_tool.items():
            _w(d / f"{tool}.findings.json", items)

        # (C) nhãn tổng hợp
        rows = [_decode(r) for r in store.findings_for_commit(cid)]
        _w(d / "label.json", rows)

        _w(d / "summary.json", {
            "commit_id": cid,
            "tools_reported": sorted(by_tool),
            "n_cluster_labeled": len(rows),
            "labels": dict(Counter(r.get("label") for r in rows)),
        })
        n_commit += 1
    return {"commits": n_commit, "raw_files": n_raw, "out": str(out_dir)}
