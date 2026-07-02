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
from .consensus.labeler import relabel_commit
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
    for ci, keep, reason in enm.enumerate_repo(args.repo, args.max, args.branch):
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
        raw = []
        try:
            fs = t.scan(clone, ci.commit_id, args.repo, changed, raw_out=raw)
        except Exception as e:  # noqa: BLE001 — 1 tool lỗi không dừng cả phễu
            print(f"[{t.name}] lỗi @ {ci.commit_id[:8]}: {e}")
            fs = []
        if raw:  # (B) lưu output thô
            store.insert_raw_output(ci.commit_id, t.name, raw[0][0], raw[0][1])
        return fs

    all_findings = []
    if config.CHEAP_INTRA_PARALLEL:                 # Model B: tool song song trong 1 commit
        with ThreadPoolExecutor(max_workers=len(tools)) as ex:
            for res in ex.map(_safe, tools):
                all_findings += res
    else:                                           # Model A: tool tuần tự
        for t in tools:
            all_findings += _safe(t)

    # loại finding trong vendored/generated (node_modules...) — nhiễu, không phải của dự án
    all_findings = [f for f in all_findings if not enm.is_excluded_path(f.file_path)]
    # LƯU RAW từng-tool -> RELABEL (gộp cụm + vote tier-aware + enrich). Nhãn dẫn xuất từ raw
    # -> khi tầng đắt chạy sau, chỉ thêm raw đắt rồi relabel là nhãn tự nâng cấp (RULE_GAN_NHAN.md).
    store.insert_raw(all_findings)
    rows = relabel_commit(store, ci.commit_id, clone, args.repo)
    wrote = len(rows)

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
    for ci, keep, reason in enm.enumerate_repo(args.repo, args.max, args.branch):
        if keep:
            todo.append(ci)
        elif reason.startswith((">", "diff file lớn")):  # khổng lồ (số file / churn)
            skipped_big.append((ci.commit_id, reason))
    for sha, reason in skipped_big:
        print(f"[{sha[:8]}] BỎ QUA: {reason}")

    # 14 đặc trưng Kamei: tính 1 lượt (single-thread) TRƯỚC khi quét -> relabel trong
    # scan tự nhặt từ bảng commit_features nhúng vào từng row.
    if config.KAMEI_ENABLED and todo:
        import time as _t
        from . import kamei
        t0 = _t.time()
        rev = enm.resolve_rev(repo_dir, args.branch)
        feats = kamei.compute_features(repo_dir, {ci.commit_id for ci in todo}, rev)
        store.upsert_commit_features(args.repo, feats)
        print(f"Kamei: 14 đặc trưng cho {len(feats)}/{len(todo)} commit "
              f"({_t.time() - t0:.1f}s)")

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
    res = select_commits.select(store, include_clean=args.include_clean)
    print(f"Universe (commit đã quét tầng rẻ): {res['universe']}")
    print(f"  buggy (có mã CWE/CVE"
          f"{', in_diff' if config.SUSPECT_REQUIRE_IN_DIFF else ''}) -> TẦNG ĐẮT (positive): {res['buggy']}")
    if args.include_clean:
        print(f"  clean -> CŨNG đưa vào tầng đắt để VERIFY (→ verified-clean GOLD): {res['negative_clean']}")
        print(f"=> đã thêm (incremental) {res['total_selected']} commit vào hàng đợi.")
    else:
        print(f"  clean (0 CWE/CVE) -> NEGATIVE (không quét đắt): {res['negative_clean']}")
        print(f"=> selected_commits (hàng đợi đắt) = {res['total_selected']} commit buggy.")
    store.close()


def cmd_analyze(args):
    if args.codeql is not None:
        config.USE_CODEQL = args.codeql
    tools = [t.strip() for t in args.tools.split(",")] if args.tools else None
    res = expensive_runner.analyze(args.repo, workers=args.workers,
                                   dry_run=bool(args.dry_run), tools=tools)
    print(f"\nXong: done={res.get('done',0)} build_failed={res.get('build_failed',0)} "
          f"| {res['workers']} worker, tool {res['tools']}")
    print(f"selected_commits status: {res['status_counts']}")


def cmd_relabel(args):
    """Gán nhãn LẠI mọi commit từ raw_findings (áp filter nhiễu hiện tại). KHÔNG quét lại."""
    from .consensus.labeler import relabel_commit
    repo_dir = enm.clone_or_update(args.repo)   # dùng git show (sha-scoped) — không checkout
    store = SQLiteStore()
    ids = store.all_commit_ids()
    for cid in ids:
        relabel_commit(store, cid, repo_dir, args.repo)
    print(f"Relabel {len(ids)} commit | lọc nhiễu CWE={sorted(config.NOISE_CWE)} "
          f"rules={sorted(config.NOISE_RULES) or '-'}")
    print(f"DB: {store.count()} findings | label: "
          f"{dict(store.conn.execute('SELECT label,COUNT(*) FROM findings GROUP BY label'))}")
    store.close()


def cmd_features(args):
    """Backfill 14 đặc trưng Kamei cho MỌI commit đã có trong DB (không quét lại),
    rồi relabel để nhúng vào label rows."""
    import time as _t
    from . import kamei
    repo_dir = enm.clone_or_update(args.repo)
    rev = enm.resolve_rev(repo_dir, args.branch)
    store = SQLiteStore()
    targets = set(store.all_commit_ids())
    t0 = _t.time()
    feats = kamei.compute_features(repo_dir, targets, rev)
    store.upsert_commit_features(args.repo, feats)
    missing = targets - feats.keys()
    print(f"Kamei: tính {len(feats)}/{len(targets)} commit ({_t.time() - t0:.1f}s)"
          + (f" | thiếu {len(missing)} (merge/ngoài nhánh {rev})" if missing else ""))
    for cid in feats:
        relabel_commit(store, cid, repo_dir, args.repo)
    print(f"Đã nhúng vào label rows (relabel {len(feats)} commit).")
    # sanity: min/mean/max vài đặc trưng
    for col in ("nf", "entropy", "lt", "exp", "ndev", "fix"):
        r = store.conn.execute(
            f"SELECT MIN({col}), ROUND(AVG({col}),3), MAX({col}) "
            f"FROM commit_features").fetchone()
        print(f"  {col:8} min={r[0]} avg={r[1]} max={r[2]}")
    store.close()


def cmd_clean(args):
    """Dọn artifact sau khi scan xong: clone + pool (mặc định); tuỳ chọn export/cache/DB."""
    import shutil
    from pathlib import Path as _P
    from .tools.base import docker_run
    removed = []

    def _rm(p, label):
        p = _P(p)
        if not p.exists():
            return
        shutil.rmtree(p, ignore_errors=True)
        if p.exists():   # còn (file root-owned từ build cũ) -> xoá bằng container root
            docker_run(["run", "--rm", "-v", f"{p.parent}:/w", "alpine",
                        "rm", "-rf", f"/w/{p.name}"], timeout=120)
        removed.append(label)

    name = args.repo.rstrip("/").split("/")[-1].removesuffix(".git")
    _rm(config.WORK_DIR / name, f"clone({name})")
    for pd in config.WORK_DIR.glob("pool_*"):
        _rm(pd, pd.name)
    if args.export or args.all:
        _rm(config.EXPORT_DIR, "export")
    if args.cache or args.all:
        _rm(config.WORK_DIR / ".m2cache", ".m2cache")
    if args.db or args.all:
        if config.SQLITE_PATH.exists():
            config.SQLITE_PATH.unlink()
            removed.append("dataset.sqlite")
    print(f"Đã dọn: {removed or '(không có gì)'}")


def cmd_pipeline(args):
    """Chạy TRỌN pipeline: scan -> select -> analyze -> relabel -> kappa -> export."""
    import time as _t
    ns = argparse.Namespace(
        repo=args.repo, max=args.max, branch=args.branch,
        flag_limit=args.flag_limit, no_meta=args.no_meta,
        require_in_diff=None, include_clean=args.include_clean,
        workers=args.workers, tools=None, dry_run=False, codeql=args.codeql,
        out=args.out,
    )
    steps = [("① SCAN (tầng rẻ)", cmd_scan), ("② SELECT", cmd_select),
             ("③ ANALYZE (tầng đắt)", cmd_analyze), ("④ RELABEL", cmd_relabel),
             ("⑤ KAPPA", cmd_kappa), ("⑥ EXPORT", cmd_export)]
    t0 = _t.time()
    for i, (name, fn) in enumerate(steps, 1):
        print(f"\n{'='*60}\n>>> {name}  ({i}/{len(steps)})\n{'='*60}", flush=True)
        fn(ns)
    print(f"\n{'='*60}\n✅ PIPELINE XONG sau {int(_t.time()-t0)}s "
          f"| DB: {config.SQLITE_PATH} | export: {ns.out or config.EXPORT_DIR}\n{'='*60}")


def cmd_kappa(args):
    from . import kappa as kp
    store = SQLiteStore()
    allit, by_group, by_cat = kp.collect(store)
    k, n = kp.fleiss(allit)
    ks = f"{k:.3f}" if k is not None else "-"
    print(f"Fleiss' kappa TỔNG: {ks}  ({kp._label(k)}) | {n} item ≥2 rater")
    print("theo CATEGORY:")
    for cat, items in sorted(by_cat.items()):
        kc, nc = kp.fleiss(items)
        print(f"  {cat:8} κ={f'{kc:.3f}' if kc is not None else '-':>7}  ({kp._label(kc)}) n={nc}")
    print("theo NHÓM-CWE (n≥5):")
    for grp, items in sorted(by_group.items(), key=lambda x: -len(x[1])):
        kg, ng = kp.fleiss(items)
        if ng >= 5:
            print(f"  {grp:18} κ={f'{kg:.3f}' if kg is not None else '-':>7}  n={ng}")
    store.close()


def cmd_export(args):
    from . import export_dataset
    store = SQLiteStore()
    res = export_dataset.export_all(store, args.out or config.EXPORT_DIR)
    store.close()
    print(f"Export {res['commits']} commit | {res['raw_files']} file raw -> {res['out']}")
    print(f"negatives: {res.get('negatives', {})} (verified-clean = qua tầng đắt; cheap-clean = chỉ rẻ)")
    print("Mỗi commit: <tool>.raw.* (thô) + <tool>.findings.json (parsed) + label.json + summary.json")


def main(argv=None):
    p = argparse.ArgumentParser(prog="orchestrator")
    sub = p.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("enumerate", help="liệt kê + lọc thô commit")
    pe.add_argument("repo")
    pe.add_argument("--max", type=int, default=config.PILOT_MAX_COMMITS,
                    help="số commit mới nhất (0 = KHÔNG giới hạn, quét hết)")
    pe.add_argument("--branch", default=None, help="nhánh cần quét (mặc định: nhánh mặc định repo)")
    pe.add_argument("--flag-limit", type=int, choices=(0, 1), default=config.FLAG_LIMIT,
                    help="1=áp ngưỡng bỏ commit khổng lồ; 0=không (mặc định 0)")
    pe.set_defaults(func=cmd_enumerate)

    ps = sub.add_parser("scan", help="chạy tool tầng rẻ -> consensus -> SQLite")
    ps.add_argument("repo")
    ps.add_argument("--max", type=int, default=config.PILOT_MAX_COMMITS,
                    help="số commit mới nhất (0 = KHÔNG giới hạn, quét hết)")
    ps.add_argument("--branch", default=None, help="nhánh cần quét (mặc định: nhánh mặc định repo)")
    ps.add_argument("--no-meta", action="store_true",
                    help="bỏ qua thu version/digest tool (chạy nhanh khi debug)")
    ps.add_argument("--flag-limit", type=int, choices=(0, 1), default=config.FLAG_LIMIT,
                    help="1=áp ngưỡng bỏ commit khổng lồ; 0=không (mặc định 0)")
    ps.set_defaults(func=cmd_scan)

    psel = sub.add_parser("select",
                          help="chọn commit buggy (có CWE/CVE) cho tầng đắt; clean = negative")
    psel.add_argument("--require-in-diff", type=int, choices=(0, 1), default=None,
                      help="1=chỉ tính đáng nghi khi finding nằm trong diff commit")
    psel.add_argument("--include-clean", action="store_true",
                      help="THÊM clean commit vào hàng đợi đắt để verify -> verified-clean GOLD negative")
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
    pa.add_argument("--codeql", type=int, choices=(0, 1), default=None,
                    help="1=bật CodeQL (mặc định), 0=TẮT (chỉ FindSecBugs+Sonar, nhanh)")
    pa.set_defaults(func=cmd_analyze)

    prl = sub.add_parser("relabel",
                         help="gán nhãn LẠI từ raw (áp filter nhiễu) — KHÔNG quét lại")
    prl.add_argument("repo")
    prl.set_defaults(func=cmd_relabel)

    pk = sub.add_parser("kappa", help="Fleiss' kappa: độ tin đồng thuận tool (từ raw)")
    pk.set_defaults(func=cmd_kappa)

    pf = sub.add_parser("features",
                        help="backfill 14 đặc trưng Kamei cho commit trong DB + nhúng vào label")
    pf.add_argument("repo")
    pf.add_argument("--branch", default=None,
                    help="nhánh duyệt lịch sử (mặc định: nhánh mặc định repo — PHẢI trùng nhánh đã scan)")
    pf.set_defaults(func=cmd_features)

    pp = sub.add_parser("pipeline",
                        help="CHẠY TRỌN: scan->select->analyze->relabel->kappa->export")
    pp.add_argument("repo")
    pp.add_argument("--max", type=int, default=config.PILOT_MAX_COMMITS,
                    help="số commit mới nhất (0 = hết)")
    pp.add_argument("--branch", default=None, help="nhánh (mặc định: nhánh mặc định repo)")
    pp.add_argument("--flag-limit", type=int, choices=(0, 1), default=config.FLAG_LIMIT)
    pp.add_argument("--codeql", type=int, choices=(0, 1), default=None,
                    help="0=tắt CodeQL (nhanh ~30s/commit); mặc định theo config (bật)")
    pp.add_argument("--include-clean", action="store_true",
                    help="quét cả clean commit ở tầng đắt -> verified-clean GOLD")
    pp.add_argument("--workers", type=int, default=config.EXPENSIVE_WORKERS,
                    help="số commit song song ở tầng đắt")
    pp.add_argument("--no-meta", action="store_true", help="bỏ thu version/digest tool")
    pp.add_argument("--out", default=None, help="thư mục export")
    pp.set_defaults(func=cmd_pipeline)

    pc = sub.add_parser("clean", help="dọn artifact sau scan: clone+pool (mặc định); +export/cache/DB")
    pc.add_argument("repo")
    pc.add_argument("--export", action="store_true", help="xoá luôn thư mục export")
    pc.add_argument("--cache", action="store_true", help="xoá cache Maven .m2 (sẽ tải lại lần sau)")
    pc.add_argument("--db", action="store_true", help="xoá luôn dataset.sqlite")
    pc.add_argument("--all", action="store_true", help="xoá HẾT: clone+pool+export+cache+DB")
    pc.set_defaults(func=cmd_clean)

    pex = sub.add_parser("export",
                         help="(C) xuất file trực quan mỗi commit: mỗi tool .raw/.findings + label.json")
    pex.add_argument("--out", default=None, help=f"thư mục xuất (mặc định {config.EXPORT_DIR})")
    pex.set_defaults(func=cmd_export)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
