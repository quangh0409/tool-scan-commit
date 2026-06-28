"""
Tầng ⑤ (cầu nối rẻ→đắt): chọn commit cho TẦNG ĐẮT quét.

Quy tắc (yêu cầu người dùng — mô hình positive/negative):
  - Commit "buggy" = có BẤT KỲ finding nào mang **mã CWE/CVE** (chỉ cần 1 tool/1 finding)
    -> CHỈ những commit này vào hàng đợi TẦNG ĐẮT (selected_commits) -> dataset POSITIVE.
  - Commit "clean" = 0 finding CWE/CVE từ tool rẻ -> **KHÔNG quét tầng đắt** -> dataset NEGATIVE
    lấy thẳng từ dữ liệu tầng rẻ (scanned_files/findings). TẤT CẢ clean commit đều là negative.
  - Commit "xám" = có finding nhưng KHÔNG suy ra được CWE/CVE -> BỎ (hiếm; thường rỗng).

LƯU Ý: negative = "cheap-clean" (silver), KHÔNG phải verified-clean — tool rẻ recall thấp nên
một commit clean vẫn có thể có vuln mà chỉ CodeQL bắt được. Đánh đổi cost↔độ-sạch (người dùng chốt).

Phân loại đọc từ DB tầng rẻ (findings + scanned_files); ghi buggy ra bảng selected_commits.
"""
from __future__ import annotations

import datetime
import json

from . import config
from .storage.sqlite_store import SQLiteStore


def _has_cve(cve) -> bool:
    return cve not in (None, "", "null", "[]")


def _has_cwe(cwe_json) -> bool:
    if not cwe_json:
        return False
    try:
        return bool(json.loads(cwe_json))      # cwe lưu dạng JSON list
    except (TypeError, ValueError):
        return cwe_json not in ("[]", '""', "null")


def classify(store: SQLiteStore):
    """-> (universe, buggy{cid:{n,has_cve}}, clean set, gray set)."""
    universe = set(store.scanned_commit_ids())
    has_any: set[str] = set()
    buggy: dict[str, dict] = {}
    for cid, cwe, cve, in_diff in store.finding_class_rows():
        has_any.add(cid)
        if not (_has_cwe(cwe) or _has_cve(cve)):
            continue                            # không có mã CWE/CVE -> không tính
        if config.SUSPECT_REQUIRE_IN_DIFF and not in_diff:
            continue
        d = buggy.setdefault(cid, {"n": 0, "has_cve": False})
        d["n"] += 1
        if _has_cve(cve):
            d["has_cve"] = True
    clean = universe - has_any                  # 0 finding = negative thật
    gray = has_any - set(buggy)                 # có finding nhưng không có CWE/CVE
    return universe, buggy, clean, gray


def select(store: SQLiteStore) -> dict:
    """Đẩy CHỈ commit buggy (có CWE/CVE) vào hàng đợi tầng đắt. Clean = negative (không quét đắt)."""
    universe, buggy, clean, gray = classify(store)

    now = datetime.datetime.now().isoformat(timespec="seconds")
    rows: list[dict] = []
    for cid in sorted(buggy):
        b = buggy[cid]
        signal = ["cwe"] + (["cve"] if b["has_cve"] else [])
        rows.append({
            "commit_id": cid, "role": "buggy",
            "selection_reason": f"suspect:{'/'.join(signal)} x{b['n']}",
            "suspect_categories": signal, "n_suspect_findings": b["n"],
            "created_at": now,
        })
    store.replace_selected(rows)
    return {
        "universe": len(universe), "buggy": len(buggy),
        "negative_clean": len(clean), "gray_excluded": len(gray),
        "total_selected": len(rows),
    }
