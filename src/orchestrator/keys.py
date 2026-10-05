"""Khoá ổn định cho cụm finding — dùng cho gold_review, compare A/B, map lại sau relabel.

Hợp đồng: CONTRACTS.md §cluster_key.
  cluster_key = sha256("repo|commit|file_path|cwe_group|s_line // LINE_WINDOW")[:32]

Vì sao chia nguyên theo LINE_WINDOW: relabel làm DELETE+INSERT đổi row id, và s_line của cụm
có thể trôi ±W tuỳ finding nào đứng đầu; bucket theo W giữ khoá ổn định trong cùng cấu hình.
"""
from __future__ import annotations

import hashlib

from . import config


def canon_repo(url: str) -> str:
    """Chuẩn hoá URL repo để mọi nơi dùng cùng một chuỗi: bỏ .git, bỏ /, lowercase host."""
    u = (url or "").strip().rstrip("/")
    if u.endswith(".git"):
        u = u[:-4]
    if u.startswith("git@github.com:"):
        u = "https://github.com/" + u[len("git@github.com:"):]
    if u.startswith("http://"):
        u = "https://" + u[len("http://"):]
    # github.com/o/r/tree|commit|pull|blob/... -> github.com/o/r
    parts = u.split("/")
    if len(parts) >= 6 and parts[2].lower().endswith("github.com") and parts[5] in (
            "tree", "commit", "pull", "blob", "commits", "compare", "issues"):
        u = "/".join(parts[:5])
    if len(parts) >= 3:
        parts = u.split("/")
        parts[2] = parts[2].lower()
        u = "/".join(parts)
    return u


def repo_slug(url: str) -> str:
    """owner__repo (tên thư mục clone, tránh trùng tên khác org)."""
    u = canon_repo(url)
    parts = [p for p in u.split("/") if p]
    if len(parts) >= 2:
        return f"{parts[-2]}__{parts[-1]}"
    return parts[-1] if parts else "repo"


def cluster_key(repo: str, commit_id: str, file_path: str, cwe_group: str,
                s_line: int, line_window: int | None = None) -> str:
    w = line_window or config.LINE_WINDOW or 1
    bucket = int(s_line or 0) // w
    raw = f"{canon_repo(repo)}|{commit_id}|{file_path}|{cwe_group or ''}|{bucket}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
