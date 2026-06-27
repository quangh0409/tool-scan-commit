"""
Tầng ① — git enumerate + lọc thô.

clone (hoặc dùng repo có sẵn) -> liệt kê commit (mới->cũ) ->
lọc bỏ: merge commit, commit chỉ đụng docs/non-code.
Chỉ dùng `git` qua subprocess (stdlib).
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import config


@dataclass
class CommitInfo:
    commit_id: str
    parent_commit: str | None
    author_date: str
    message: str
    is_merge: bool
    changed_files: list[str] = field(default_factory=list)
    lines_added: int = 0
    lines_deleted: int = 0

    @property
    def code_files(self) -> list[str]:
        return [f for f in self.changed_files
                if Path(f).suffix.lower() in config.CODE_EXTENSIONS]


def _git(repo_dir: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        capture_output=True, text=True, check=True,
    )
    return out.stdout


def clone_or_update(repo_url: str, dest: Path | None = None) -> Path:
    """Clone repo target vào WORK_DIR (nếu chưa có)."""
    config.ensure_dirs()
    name = repo_url.rstrip("/").split("/")[-1].removesuffix(".git")
    dest = dest or (config.WORK_DIR / name)
    if (dest / ".git").exists():
        return dest
    subprocess.run(["git", "clone", repo_url, str(dest)], check=True)
    return dest


def list_commits(repo_dir: Path, max_count: int | None = None) -> list[str]:
    args = ["log", "--pretty=%H"]
    if max_count:
        args += [f"-n{max_count}"]
    return _git(repo_dir, *args).split()


def get_commit_info(repo_dir: Path, commit_id: str) -> CommitInfo:
    # %P = parents (cách nhau bởi space); >1 => merge
    raw = _git(repo_dir, "show", "-s", "--pretty=%P%n%ad%n%s",
               "--date=iso-strict", commit_id)
    parents_line, date_line, *msg_lines = raw.splitlines() or ["", "", ""]
    parents = parents_line.split()
    is_merge = len(parents) > 1

    # file thay đổi
    files = _git(repo_dir, "show", "--name-only", "--pretty=format:", commit_id)
    changed = [f for f in files.splitlines() if f.strip()]

    # numstat -> tổng add/del
    add = dele = 0
    numstat = _git(repo_dir, "show", "--numstat", "--pretty=format:", commit_id)
    for ln in numstat.splitlines():
        cols = ln.split("\t")
        if len(cols) == 3 and cols[0].isdigit() and cols[1].isdigit():
            add += int(cols[0]); dele += int(cols[1])

    return CommitInfo(
        commit_id=commit_id,
        parent_commit=parents[0] if parents else None,
        author_date=date_line.strip(),
        message="\n".join(msg_lines).strip(),
        is_merge=is_merge,
        changed_files=changed,
        lines_added=add,
        lines_deleted=dele,
    )


def coarse_filter(ci: CommitInfo) -> tuple[bool, str]:
    """True = GIỮ để quét. Trả (keep, lý do)."""
    if config.SKIP_MERGE_COMMITS and ci.is_merge:
        return False, "merge commit"
    if not ci.changed_files:
        return False, "không có file thay đổi"
    if not ci.code_files:
        return False, "chỉ đụng docs/non-code"
    return True, "ok"


def enumerate_repo(repo_url: str, max_count: int | None = None):
    """Yield (CommitInfo, keep, reason) — mới->cũ."""
    repo_dir = clone_or_update(repo_url)
    for cid in list_commits(repo_dir, max_count):
        ci = get_commit_info(repo_dir, cid)
        keep, reason = coarse_filter(ci)
        yield ci, keep, reason
