"""
Tầng ⑤ (cầu nối rẻ→đắt): chọn commit cho TẦNG ĐẮT quét.

Quy tắc (yêu cầu người dùng):
  - 5 tool rẻ ĐÁNH DẤU commit "đáng nghi" (buggy) = có finding thuộc SUSPECT_CATEGORIES
    (mặc định code/crypto/secret; bỏ infra/info vốn là nhiễu). MỌI buggy -> tầng đắt quét.
  - Commit "clean" = 0 finding (negative thật) -> lấy MẪU ngẫu nhiên theo tỉ lệ
    1 buggy : CLEAN_PER_BUGGY clean (mặc định 1:20). Mẫu có seed -> tái lập.
  - Commit "xám" = có finding nhưng chỉ ngoài SUSPECT_CATEGORIES (vd chỉ infra) -> BỎ
    (không đủ đáng nghi để tốn build đắt, cũng không phải negative sạch).

Phân loại đọc từ DB tầng rẻ (findings + scanned_files); ghi ra bảng selected_commits
= hàng đợi cho Bước 2.
"""
from __future__ import annotations

import datetime
import random

from . import config
from .storage.sqlite_store import SQLiteStore


def classify(store: SQLiteStore):
    """-> (universe, buggy{cid:{cats,n}}, clean set, gray set)."""
    universe = set(store.scanned_commit_ids())
    has_any: set[str] = set()
    buggy: dict[str, dict] = {}
    for cid, cat, in_diff in store.finding_class_rows():
        has_any.add(cid)
        if cat in config.SUSPECT_CATEGORIES:
            if config.SUSPECT_REQUIRE_IN_DIFF and not in_diff:
                continue
            d = buggy.setdefault(cid, {"cats": set(), "n": 0})
            d["cats"].add(cat)
            d["n"] += 1
    clean = universe - has_any          # 0 finding = negative thật
    gray = has_any - set(buggy)         # có finding nhưng không đáng nghi
    return universe, buggy, clean, gray


def select(store: SQLiteStore, ratio: int | None = None, seed: int | None = None) -> dict:
    ratio = config.CLEAN_PER_BUGGY if ratio is None else ratio
    seed = config.SELECT_SEED if seed is None else seed
    universe, buggy, clean, gray = classify(store)

    # số clean lấy = ratio * #buggy (chặn theo pool sẵn có). Nếu 0 buggy -> lấy 'ratio' làm nền.
    want = ratio * len(buggy) if buggy else ratio
    n_take = min(len(clean), want)
    clean_sample = random.Random(seed).sample(sorted(clean), n_take) if n_take else []

    now = datetime.datetime.now().isoformat(timespec="seconds")
    rows: list[dict] = []
    for cid in sorted(buggy):
        cats = sorted(buggy[cid]["cats"])
        rows.append({
            "commit_id": cid, "role": "buggy",
            "selection_reason": "suspect:" + "+".join(cats),
            "suspect_categories": cats, "n_suspect_findings": buggy[cid]["n"],
            "created_at": now,
        })
    for cid in clean_sample:
        rows.append({
            "commit_id": cid, "role": "clean",
            "selection_reason": f"negative-sample(1:{ratio})",
            "suspect_categories": [], "n_suspect_findings": 0,
            "created_at": now,
        })
    store.replace_selected(rows)
    return {
        "universe": len(universe), "buggy": len(buggy),
        "clean_pool": len(clean), "clean_taken": len(clean_sample),
        "gray_excluded": len(gray), "ratio": ratio,
        "total_selected": len(rows),
    }
