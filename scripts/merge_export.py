#!/usr/bin/env python3
"""Gộp dataset.jsonl + commits.jsonl (+ SHA256SUMS) cho 1 thư mục export — ĐỌC THẲNG TỪ DB.

Giữ lại để tương thích runbook cũ; logic đã gộp vào `orchestrator.export_dataset.write_merged`
(`export` giờ tự sinh 2 file này — CONTRACTS §6). Script chỉ gọi hàm mới, mở DB chế độ ĐỌC
(không tạo lock, không đụng run đang chạy).

Dùng:
    PYTHONPATH=src python3 scripts/merge_export.py <export_dir> <db.sqlite>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from orchestrator import export_dataset  # noqa: E402
from orchestrator.storage.sqlite_store import SQLiteStore  # noqa: E402


def main(export_dir: str, db_path: str) -> None:
    store = SQLiteStore(Path(db_path), readonly=True)
    try:
        res = export_dataset.write_merged(store, Path(export_dir))
        if (Path(export_dir) / export_dataset.MANIFEST).exists():
            export_dataset.write_sums(Path(export_dir))
    finally:
        store.close()
    print(f"dataset.jsonl : {res['dataset_rows']} dòng (cụm finding)")
    print(f"commits.jsonl : {res['commits_rows']} dòng (commit)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
