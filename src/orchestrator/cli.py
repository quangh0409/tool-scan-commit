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

import datetime

from . import config, enumerate_commits as enm
from .consensus.matcher import consensus
from .storage.sqlite_store import SQLiteStore
from .tools.bearer import BearerWrapper
from .tools.gitleaks import GitleaksWrapper
from .tools.horusec import HorusecWrapper
from .tools.semgrep import SemgrepWrapper
from .tools.trufflehog import TrufflehogWrapper

# 2 nhánh chồng phủ để consensus có nghĩa:
#   secret: gitleaks + trufflehog (+ horusec Leaks)
#   code  : semgrep + bearer
CHEAP_TOOLS = [GitleaksWrapper, TrufflehogWrapper, SemgrepWrapper,
               BearerWrapper, HorusecWrapper]


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


def _added_lines(pd) -> set[int]:
    return {ln for ln, _ in (pd.added if pd else [])}


def cmd_scan(args):
    repo_dir = enm.clone_or_update(args.repo)
    # lưu ref gốc để khôi phục đúng (không dùng 'checkout -' vốn về ref-trước-đó)
    orig_ref = subprocess.run(
        ["git", "-C", str(repo_dir), "symbolic-ref", "--quiet", "--short", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip() or subprocess.run(
        ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()

    tools = [T() for T in CHEAP_TOOLS]
    tool_names = [t.name for t in tools]
    store = SQLiteStore()
    n_tools = len(tools)
    scanned = wrote = clean = 0

    # run_meta: version + digest tool + config (tái lập). Lấy version 1 lần/run.
    if not args.no_meta:
        print("Thu thập version/digest tool...")
        store.insert_run_meta({
            "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "repo": args.repo, "max_commits": args.max,
            "vote_threshold": config.VOTE_THRESHOLD, "line_window": config.LINE_WINDOW,
            "tools": [{"name": t.name, "version": t.version(), "digest": t.digest()}
                      for t in tools],
        })

    for ci, keep, reason in enm.enumerate_repo(args.repo, args.max):
        if not keep:
            continue
        subprocess.run(["git", "-C", str(repo_dir), "checkout", "-q", ci.commit_id], check=True)

        # chỉ các file code đã đổi & còn tồn tại trên đĩa (diff-scoped)
        changed = [f for f in ci.code_files if (repo_dir / f).exists()]

        all_findings = []
        for t in tools:
            try:
                all_findings += t.scan(repo_dir, ci.commit_id, args.repo, changed)
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

        # enrich: diff_parsed + finding_in_diff + permalink + (tuỳ chọn) toàn văn
        file_diffs = enm.get_file_diffs(repo_dir, ci.commit_id)
        for r in rows:
            pd = file_diffs.get(r.file_path)
            r.diff_parsed = pd.as_dict() if pd else {"added": [], "deleted": []}
            r.finding_in_diff = bool(set(r.s_detail_line) & _added_lines(pd))
            r.code_after_url = enm.blob_url(args.repo, r.commit_id, r.file_path)
            r.code_before_url = enm.blob_url(args.repo, r.parent_commit, r.file_path)
            if config.STORE_FULL_FILE:
                r.code_after = enm.file_content_at(repo_dir, r.commit_id, r.file_path)
                r.code_before = enm.file_content_at(repo_dir, r.parent_commit, r.file_path)
        wrote += store.insert_rows(rows)

        # MẪU SỐ: ghi mọi file đã quét (kể cả 0 finding = negative/clean)
        files_with_finding = {r.file_path for r in rows}
        scanned_records = [{
            "repo": args.repo, "commit_id": ci.commit_id,
            "parent_commit": ci.parent_commit, "author_date": ci.author_date,
            "file_path": f, "n_tools_ran": n_tools, "tools": tool_names,
            "n_findings": sum(1 for r in rows if r.file_path == f),
        } for f in changed]
        store.insert_scanned_files(scanned_records)
        clean += sum(1 for f in changed if f not in files_with_finding)

        scanned += 1
        print(f"[{ci.commit_id[:8]}] {len(changed)} file đổi | "
              f"{len(all_findings)} findings -> {len(rows)} cụm")

    # khôi phục ref gốc
    subprocess.run(["git", "-C", str(repo_dir), "checkout", "-q", orig_ref], check=False)
    print(f"\nĐã quét {scanned} commit | findings(cụm): {wrote} | file clean(negative): {clean}")
    print(f"DB: {store.count()} findings, {store.count_clean()} clean files")
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
    ps.add_argument("--no-meta", action="store_true",
                    help="bỏ qua thu version/digest tool (chạy nhanh khi debug)")
    ps.set_defaults(func=cmd_scan)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
