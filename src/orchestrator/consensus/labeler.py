"""
Recompute nhãn 1 commit từ raw_findings (cross-tier). Gọi sau khi ghi raw:
  - tầng rẻ: raw = 5 tool rẻ -> nhãn silver/candidate.
  - tầng đắt: raw = rẻ + đắt -> nhãn nâng cấp (gold khi đắt xác nhận).
Idempotent: xoá findings cũ của commit rồi ghi lại (RULE_GAN_NHAN.md §0.3, §6).
"""
from __future__ import annotations

from pathlib import Path

from .. import config, enumerate_commits as enm
from .matcher import consensus


def _added_lines(pd) -> set[int]:
    return {ln for ln, _ in (pd.added if pd else [])}


def relabel_commit(store, commit_id: str, clone_dir: Path, repo: str) -> list:
    """Đọc raw của commit -> gộp cụm + vote tier-aware -> enrich -> ghi đè findings. Trả rows."""
    raws = store.raw_for_commit(commit_id)
    if not raws:
        store.replace_findings_for_commit(commit_id, [])
        return []

    ci = enm.get_commit_info(clone_dir, commit_id)
    meta = {"parent_commit": ci.parent_commit, "commit_message": ci.message,
            "author_date": ci.author_date, "lines_added": ci.lines_added,
            "lines_deleted": ci.lines_deleted}
    rows = consensus(raws, meta)

    file_diffs = enm.get_file_diffs(clone_dir, commit_id)
    for r in rows:
        pd = file_diffs.get(r.file_path)
        r.diff_parsed = pd.as_dict() if pd else {"added": [], "deleted": []}
        r.finding_in_diff = bool(set(r.s_detail_line) & _added_lines(pd))
        r.code_after_url = enm.blob_url(repo, r.commit_id, r.file_path)
        r.code_before_url = enm.blob_url(repo, r.parent_commit, r.file_path)
        if config.STORE_FULL_FILE:
            r.code_after = enm.file_content_at(clone_dir, r.commit_id, r.file_path)
            r.code_before = enm.file_content_at(clone_dir, r.parent_commit, r.file_path)
    store.replace_findings_for_commit(commit_id, rows)
    return rows
