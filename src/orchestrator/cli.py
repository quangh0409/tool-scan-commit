"""
Entrypoint orchestrator — nối phễu source-only end-to-end.

Dùng:
  python -m orchestrator.cli enumerate <repo_url> [--max N]
      -> liệt kê commit + lọc thô (không cần Docker).
  python -m orchestrator.cli scan <repo_url> [--max N]
      -> chạy tool tầng rẻ (Docker) -> consensus -> ghi SQLite.

Đặt ORCH_DOCKER_SG=1 nếu tiến trình chưa thuộc nhóm docker (xem CLAUDE.md).
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from . import config, enumerate_commits as enm
from .consensus.matcher import consensus
from .storage.sqlite_store import SQLiteStore
from .tools.gitleaks import GitleaksWrapper
from .tools.semgrep import SemgrepWrapper

CHEAP_TOOLS = [GitleaksWrapper, SemgrepWrapper]


def cmd_enumerate(args):
    kept = total = 0
    for ci, keep, reason in enm.enumerate_repo(args.repo, args.max):
        total += 1
        flag = "KEEP" if keep else "skip"
        if keep:
            kept += 1
        print(f"[{flag}] {ci.commit_id[:8]} (+{ci.lines_added}/-{ci.lines_deleted}) "
              f"{len(ci.code_files)} code files — {reason} — {ci.message[:50]}")
    print(f"\nTổng: {total} commit | giữ để quét: {kept}")


def cmd_scan(args):
    repo_dir = enm.clone_or_update(args.repo)
    tools = [T() for T in CHEAP_TOOLS]
    store = SQLiteStore()
    n_tools = len(tools)
    scanned = wrote = 0

    for ci, keep, reason in enm.enumerate_repo(args.repo, args.max):
        if not keep:
            continue
        # checkout commit
        subprocess.run(["git", "-C", str(repo_dir), "checkout", "-q", ci.commit_id], check=True)
        all_findings = []
        for t in tools:
            try:
                all_findings += t.scan(repo_dir, ci.commit_id, args.repo)
            except Exception as e:  # noqa: BLE001 — 1 tool lỗi không nên dừng cả phễu
                print(f"[{t.name}] lỗi @ {ci.commit_id[:8]}: {e}")
        meta = {
            "parent_commit": ci.parent_commit,
            "commit_message": ci.message,
            "author_date": ci.author_date,
            "lines_added": ci.lines_added,
            "lines_deleted": ci.lines_deleted,
        }
        rows = consensus(all_findings, n_tools, meta)
        wrote += store.insert_rows(rows)
        scanned += 1
        print(f"[{ci.commit_id[:8]}] {len(all_findings)} findings -> {len(rows)} cụm")

    # trả HEAD về nhánh mặc định
    subprocess.run(["git", "-C", str(repo_dir), "checkout", "-q", "-"], check=False)
    print(f"\nĐã quét {scanned} commit | ghi {wrote} dòng | tổng DB: {store.count()}")
    store.close()


def main(argv=None):
    p = argparse.ArgumentParser(prog="orchestrator")
    sub = p.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("enumerate", help="liệt kê + lọc thô commit")
    pe.add_argument("repo")
    pe.add_argument("--max", type=int, default=config.PILOT_MAX_COMMITS)
    pe.set_defaults(func=cmd_enumerate)

    ps = sub.add_parser("scan", help="chạy tool tầng rẻ -> consensus -> SQLite")
    ps.add_argument("repo")
    ps.add_argument("--max", type=int, default=config.PILOT_MAX_COMMITS)
    ps.set_defaults(func=cmd_scan)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
