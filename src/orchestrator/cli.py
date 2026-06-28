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
from pathlib import Path

import datetime
from concurrent.futures import ThreadPoolExecutor

from . import config, enumerate_commits as enm, select_commits, expensive_runner
from .consensus.matcher import consensus
from .repo_pool import RepoPool
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
    config.FLAG_LIMIT = args.flag_limit
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


def _scan_one_commit(ci, clone: Path, tools, tool_names, args, store):
    """Quét TRỌN 1 commit trên 1 clone đã checkout sẵn. Trả (status_line, n_scanned,
    n_wrote, n_clean). Chạy trong 1 worker — 5 tool TUẦN TỰ ở đây; song song nằm ở
    CẤP COMMIT (nhiều worker). (Commit khổng lồ đã bị lọc ở coarse_filter trước khi tới đây.)"""
    n_tools = len(tools)
    changed = [f for f in ci.code_files if (clone / f).exists()]

    def _safe(t):
        try:
            return t.scan(clone, ci.commit_id, args.repo, changed)
        except Exception as e:  # noqa: BLE001 — 1 tool lỗi không dừng cả phễu
            print(f"[{t.name}] lỗi @ {ci.commit_id[:8]}: {e}")
            return []

    all_findings = []
    if config.CHEAP_INTRA_PARALLEL:                 # Model B: tool song song trong 1 commit
        with ThreadPoolExecutor(max_workers=len(tools)) as ex:
            for res in ex.map(_safe, tools):
                all_findings += res
    else:                                           # Model A: tool tuần tự
        for t in tools:
            all_findings += _safe(t)

    meta = {
        "parent_commit": ci.parent_commit,
        "commit_message": ci.message,
        "author_date": ci.author_date,
        "lines_added": ci.lines_added,
        "lines_deleted": ci.lines_deleted,
    }
    rows = consensus(all_findings, n_tools, meta)

    # enrich: diff_parsed + finding_in_diff + permalink + (tuỳ chọn) toàn văn
    file_diffs = enm.get_file_diffs(clone, ci.commit_id)
    for r in rows:
        pd = file_diffs.get(r.file_path)
        r.diff_parsed = pd.as_dict() if pd else {"added": [], "deleted": []}
        r.finding_in_diff = bool(set(r.s_detail_line) & _added_lines(pd))
        r.code_after_url = enm.blob_url(args.repo, r.commit_id, r.file_path)
        r.code_before_url = enm.blob_url(args.repo, r.parent_commit, r.file_path)
        if config.STORE_FULL_FILE:
            r.code_after = enm.file_content_at(clone, r.commit_id, r.file_path)
            r.code_before = enm.file_content_at(clone, r.parent_commit, r.file_path)
    wrote = store.insert_rows(rows)

    # MẪU SỐ: ghi mọi file đã quét (kể cả 0 finding = negative/clean)
    files_with_finding = {r.file_path for r in rows}
    scanned_records = [{
        "repo": args.repo, "commit_id": ci.commit_id,
        "parent_commit": ci.parent_commit, "author_date": ci.author_date,
        "file_path": f, "n_tools_ran": n_tools, "tools": tool_names,
        "n_findings": sum(1 for r in rows if r.file_path == f),
    } for f in changed]
    store.insert_scanned_files(scanned_records)
    clean = sum(1 for f in changed if f not in files_with_finding)

    status = (f"[{ci.commit_id[:8]}] {len(changed)} file đổi | "
              f"{len(all_findings)} findings -> {len(rows)} cụm")
    return status, 1, wrote, clean


def cmd_scan(args):
    config.FLAG_LIMIT = args.flag_limit
    repo_dir = enm.clone_or_update(args.repo)
    tools = [T() for T in CHEAP_TOOLS]
    tool_names = [t.name for t in tools]
    store = SQLiteStore()
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

    # lọc thô: bỏ merge/docs; bỏ commit khổng lồ (>MAX_FILES file hoặc diff 1-file quá lớn)
    todo, skipped_big = [], []
    for ci, keep, reason in enm.enumerate_repo(args.repo, args.max):
        if keep:
            todo.append(ci)
        elif reason.startswith((">", "diff file lớn")):  # khổng lồ (số file / churn)
            skipped_big.append((ci.commit_id, reason))
    for sha, reason in skipped_big:
        print(f"[{sha[:8]}] BỎ QUA: {reason}")

    workers = max(1, min(config.SCAN_WORKERS, len(todo) or 1))
    pool = RepoPool(repo_dir, workers)
    print(f"Song song CẤP COMMIT: {workers} worker (clone pool) | {len(todo)} commit cần quét "
          f"| bỏ qua khổng lồ: {len(skipped_big)}")

    def _process(ci):
        clone = pool.acquire()
        try:
            pool.checkout(clone, ci.commit_id)
            return _scan_one_commit(ci, clone, tools, tool_names, args, store)
        except Exception as e:  # noqa: BLE001 — 1 commit lỗi không dừng cả run
            return f"[{ci.commit_id[:8]}] LỖI: {e}", 0, 0, 0
        finally:
            pool.release(clone)

    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for status, ns, nw, nc in ex.map(_process, todo):
                print(status)
                scanned += ns
                wrote += nw
                clean += nc
    finally:
        pool.cleanup()

    print(f"\nĐã quét {scanned} commit | bỏ qua khổng lồ {len(skipped_big)} | "
          f"findings(cụm): {wrote} | file clean(negative): {clean}")
    print(f"DB: {store.count()} findings, {store.count_clean()} clean files")
    store.close()


def cmd_select(args):
    config.SUSPECT_REQUIRE_IN_DIFF = (args.require_in_diff == 1
                                      if args.require_in_diff is not None
                                      else config.SUSPECT_REQUIRE_IN_DIFF)
    store = SQLiteStore()
    res = select_commits.select(store)
    print(f"Universe (commit đã quét tầng rẻ): {res['universe']}")
    print(f"  buggy (có mã CWE/CVE"
          f"{', in_diff' if config.SUSPECT_REQUIRE_IN_DIFF else ''}) -> TẦNG ĐẮT (positive): {res['buggy']}")
    print(f"  clean (0 CWE/CVE) -> NEGATIVE (không quét đắt): {res['negative_clean']}")
    print(f"  xám (có finding nhưng không CWE/CVE, BỎ): {res['gray_excluded']}")
    print(f"=> selected_commits (hàng đợi đắt) = {res['total_selected']} commit buggy.")
    store.close()


def cmd_analyze(args):
    tools = [t.strip() for t in args.tools.split(",")] if args.tools else None
    res = expensive_runner.analyze(args.repo, workers=args.workers,
                                   dry_run=bool(args.dry_run), tools=tools)
    print(f"\nXong: done={res.get('done',0)} build_failed={res.get('build_failed',0)} "
          f"| {res['workers']} worker, tool {res['tools']}")
    print(f"selected_commits status: {res['status_counts']}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="orchestrator")
    sub = p.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("enumerate", help="liệt kê + lọc thô commit")
    pe.add_argument("repo")
    pe.add_argument("--max", type=int, default=config.PILOT_MAX_COMMITS)
    pe.add_argument("--flag-limit", type=int, choices=(0, 1), default=config.FLAG_LIMIT,
                    help="1=áp ngưỡng bỏ commit khổng lồ; 0=không (mặc định 0)")
    pe.set_defaults(func=cmd_enumerate)

    ps = sub.add_parser("scan", help="chạy tool tầng rẻ -> consensus -> SQLite")
    ps.add_argument("repo")
    ps.add_argument("--max", type=int, default=config.PILOT_MAX_COMMITS)
    ps.add_argument("--no-meta", action="store_true",
                    help="bỏ qua thu version/digest tool (chạy nhanh khi debug)")
    ps.add_argument("--flag-limit", type=int, choices=(0, 1), default=config.FLAG_LIMIT,
                    help="1=áp ngưỡng bỏ commit khổng lồ; 0=không (mặc định 0)")
    ps.set_defaults(func=cmd_scan)

    psel = sub.add_parser("select",
                          help="chọn commit buggy (có CWE/CVE) cho tầng đắt; clean = negative")
    psel.add_argument("--require-in-diff", type=int, choices=(0, 1), default=None,
                      help="1=chỉ tính đáng nghi khi finding nằm trong diff commit")
    psel.set_defaults(func=cmd_select)

    pa = sub.add_parser("analyze",
                        help="TẦNG ĐẮT (Model A): rút selected_commits -> build + CodeQL/FindSecBugs/Sonar")
    pa.add_argument("repo")
    pa.add_argument("--workers", type=int, default=config.EXPENSIVE_WORKERS,
                    help=f"số commit song song (mặc định {config.EXPENSIVE_WORKERS})")
    pa.add_argument("--tools", default=None,
                    help="danh sách tool (vd codeql,findsecbugs); mặc định theo config")
    pa.add_argument("--dry-run", action="store_true",
                    help="đi hết vòng đời hàng đợi mà KHÔNG build/scan (kiểm khung)")
    pa.set_defaults(func=cmd_analyze)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
