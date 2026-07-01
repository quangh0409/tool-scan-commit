"""
Tầng ① — git enumerate + lọc thô.

clone (hoặc dùng repo có sẵn) -> liệt kê commit (mới->cũ) ->
lọc bỏ: merge commit, commit chỉ đụng docs/non-code.
Chỉ dùng `git` qua subprocess (stdlib).
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import config

_HUNK_RE = re.compile(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def is_excluded_path(path: str) -> bool:
    """True nếu path thuộc vendored/generated (node_modules, vendor, .min.js…) -> loại."""
    p = "/" + str(path)
    return any(pat in p for pat in config.EXCLUDE_PATH_PATTERNS)


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
    # MỨC THAY ĐỔI LỚN NHẤT trên 1 file (để lọc commit "khổng lồ" theo diff)
    max_file_add: int = 0     # add nhiều nhất trên 1 file
    max_file_del: int = 0     # del nhiều nhất trên 1 file
    max_file_churn: int = 0   # (add+del) lớn nhất trên 1 file

    @property
    def code_files(self) -> list[str]:
        return [f for f in self.changed_files
                if Path(f).suffix.lower() in config.CODE_EXTENSIONS
                and not is_excluded_path(f)]

    @property
    def scannable_files(self) -> list[str]:
        """File đáng quét secret = mọi file KHÔNG nhị phân & KHÔNG vendored (gồm docs/config text)."""
        return [f for f in self.changed_files
                if Path(f).suffix.lower() not in config.BINARY_EXTENSIONS
                and not is_excluded_path(f)]


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

    # numstat -> tổng add/del + mức thay đổi lớn nhất trên 1 file
    add = dele = 0
    max_add = max_del = max_churn = 0
    numstat = _git(repo_dir, "show", "--numstat", "--pretty=format:", commit_id)
    for ln in numstat.splitlines():
        cols = ln.split("\t")
        if len(cols) == 3 and cols[0].isdigit() and cols[1].isdigit():
            a, d = int(cols[0]), int(cols[1])
            add += a; dele += d
            max_add = max(max_add, a)
            max_del = max(max_del, d)
            max_churn = max(max_churn, a + d)

    return CommitInfo(
        commit_id=commit_id,
        parent_commit=parents[0] if parents else None,
        author_date=date_line.strip(),
        message="\n".join(msg_lines).strip(),
        is_merge=is_merge,
        changed_files=changed,
        lines_added=add,
        lines_deleted=dele,
        max_file_add=max_add,
        max_file_del=max_del,
        max_file_churn=max_churn,
    )


@dataclass
class ParsedDiff:
    """Diff của 1 file trong 1 commit: mỗi mục = [số_dòng, nội_dung]."""
    added: list[list] = field(default_factory=list)    # đánh số theo file MỚI
    deleted: list[list] = field(default_factory=list)  # đánh số theo file CŨ

    def as_dict(self) -> dict:
        return {"added": self.added, "deleted": self.deleted}


def get_file_diffs(repo_dir: Path, commit_id: str) -> dict[str, ParsedDiff]:
    """Parse `git show --unified=0` -> {file_path: ParsedDiff}. Bỏ qua file binary."""
    raw = _git(repo_dir, "show", "--unified=0", "--no-color",
               "--pretty=format:", commit_id)
    diffs: dict[str, ParsedDiff] = {}
    cur: ParsedDiff | None = None
    old_ln = new_ln = 0
    old_path = ""
    for line in raw.splitlines():
        if line.startswith("diff --git"):
            cur = None
        elif line.startswith("--- "):
            p = line[4:]
            old_path = p[2:] if p.startswith("a/") else p
        elif line.startswith("+++ "):
            p = line[4:]
            path = old_path if p == "/dev/null" else (p[2:] if p.startswith("b/") else p)
            cur = ParsedDiff()
            diffs[path] = cur
        elif line.startswith("@@"):
            m = _HUNK_RE.search(line)
            if m:
                old_ln, new_ln = int(m.group(1)), int(m.group(2))
        elif cur is not None:
            if line.startswith("+"):
                cur.added.append([new_ln, line[1:]]); new_ln += 1
            elif line.startswith("-"):
                cur.deleted.append([old_ln, line[1:]]); old_ln += 1
    return diffs


def blob_url(repo: str, sha: str | None, path: str) -> str | None:
    """Permalink GitHub: https://github.com/owner/repo/blob/<sha>/<path>."""
    if not sha:
        return None
    base = repo.rstrip("/").removesuffix(".git")
    return f"{base}/blob/{sha}/{path}"


def file_content_at(repo_dir: Path, sha: str | None, path: str) -> str | None:
    """Toàn văn file tại 1 commit (None nếu không tồn tại — file mới/đã xoá)."""
    if not sha:
        return None
    try:
        return _git(repo_dir, "show", f"{sha}:{path}")
    except subprocess.CalledProcessError:
        return None


def coarse_filter(ci: CommitInfo) -> tuple[bool, str]:
    """True = GIỮ để quét. Trả (keep, lý do)."""
    if config.SKIP_MERGE_COMMITS and ci.is_merge:
        return False, "merge commit"
    if not ci.changed_files:
        return False, "không có file thay đổi"
    # Bỏ commit CHỈ khi toàn file nhị phân. Docs/config text VẪN giữ: secret (key/token) có thể
    # nằm trong .md/.json/.env/Dockerfile -> gitleaks/trufflehog quét toàn diff bắt được.
    if not ci.scannable_files:
        return False, "chỉ đụng file nhị phân"
    # Ngưỡng commit "khổng lồ" — CHỈ áp dụng khi FLAG_LIMIT=1 (mặc định 0 = bỏ qua ngưỡng)
    if config.FLAG_LIMIT:
        # theo SỐ FILE
        if len(ci.changed_files) > config.MAX_FILES_PER_COMMIT:
            return False, f">{config.MAX_FILES_PER_COMMIT} file ({len(ci.changed_files)})"
        # theo MỨC THAY ĐỔI 1 file (diff): add/del/churn
        # (numstat tính sẵn ở get_commit_info -> không tốn thêm; HEAD-independent, không checkout)
        if (ci.max_file_add > config.MAX_FILE_ADD_LINES
                or ci.max_file_del > config.MAX_FILE_DEL_LINES
                or ci.max_file_churn > config.MAX_FILE_CHURN_LINES):
            return False, (f"diff file lớn (+{ci.max_file_add}/-{ci.max_file_del}, "
                           f"churn {ci.max_file_churn})")
    return True, "ok"


def enumerate_repo(repo_url: str, max_count: int | None = None):
    """Yield (CommitInfo, keep, reason) — mới->cũ."""
    repo_dir = clone_or_update(repo_url)
    for cid in list_commits(repo_dir, max_count):
        ci = get_commit_info(repo_dir, cid)
        keep, reason = coarse_filter(ci)
        yield ci, keep, reason
