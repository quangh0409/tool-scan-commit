"""
Entrypoint orchestrator — nối phễu source-only end-to-end. Chữ ký lệnh: CONTRACTS.md §11.

Dùng:
  python -m orchestrator.cli enumerate <repo_url> [--max N | --since D --until D | --from-sha S --to-sha S]
  python -m orchestrator.cli scan <repo_url> [...] [--tools a,b]
  python -m orchestrator.cli pipeline <repo_url> [...] | pipeline --profile F
  python -m orchestrator.cli estimate|stats|sensitivity|compare|stop|stop-cleanup|reset-claims|clean ...
  python -m orchestrator.cli review sample|next|verdict|close ... | batch --queue Q.json | diagnostics --run ID --out Z.zip

`--profile F` (mọi subcommand): nạp profile.json, áp `profile.to_env()` vào os.environ,
`config.reload()`, rồi dựng lại argv từ profile — mọi arg khác bị BỎ QUA (có cảnh báo).

Exit code: 0 ok · 1 lỗi tham số · 2 lỗi runtime · 3 dừng theo stop-file.
Đặt ORCH_DOCKER_SG=1 nếu tiến trình chưa thuộc nhóm docker (xem CLAUDE.md).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from . import config, enumerate_commits as enm, profile as prof, progress

EXIT_OK, EXIT_ARGS, EXIT_RUNTIME, EXIT_STOP = 0, 1, 2, 3

# Lệnh mà `--profile` DỰNG LẠI argv (các arg khác bị bỏ qua).
PROFILE_DRIVEN = ("pipeline", "scan", "enumerate", "select", "analyze",
                  "relabel", "kappa", "features", "export")


class CliError(Exception):
    """Lỗi tham số -> exit 1."""


class _Parser(argparse.ArgumentParser):
    def error(self, message):            # argparse mặc định exit 2; hợp đồng: lỗi tham số = 1
        self.print_usage(sys.stderr)
        raise CliError(message)


def _warn(msg: str) -> None:
    print(f"CẢNH BÁO: {msg}", file=sys.stderr)


def _out(args, obj: dict, text: str | None = None) -> None:
    """In JSON khi --json, ngược lại in text (hoặc JSON đẹp nếu không có text)."""
    if getattr(args, "json", False):
        print(json.dumps(obj, ensure_ascii=False, default=str))
    elif text is not None:
        print(text)
    else:
        print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


# --------------------------------------------------------------------------------------
# Tool tầng rẻ
# --------------------------------------------------------------------------------------
def cheap_tool_classes() -> dict:
    """name -> wrapper class (import trễ: tools/ kéo subprocess/docker — không cần cho stats/compare)."""
    from .tools.bearer import BearerWrapper
    from .tools.gitleaks import GitleaksWrapper
    from .tools.horusec import HorusecWrapper
    from .tools.semgrep import SemgrepWrapper
    from .tools.trufflehog import TrufflehogWrapper
    # 2 nhánh chồng phủ để consensus có nghĩa: secret = gitleaks+trufflehog(+horusec Leaks);
    # code = semgrep+bearer(+horusec)
    return {"gitleaks": GitleaksWrapper, "trufflehog": TrufflehogWrapper, "semgrep": SemgrepWrapper,
            "bearer": BearerWrapper, "horusec": HorusecWrapper}


def parse_tools(spec, allowed: list[str], label: str) -> list[str] | None:
    """'a,b' -> [a,b] đã validate (giữ thứ tự, bỏ trùng). None -> None. Bỏ tool -> cảnh báo mẫu số."""
    if spec is None:
        return None
    names = spec if isinstance(spec, list) else [t.strip() for t in str(spec).split(",") if t.strip()]
    if not names:
        raise CliError(f"{label}: danh sách tool trống")
    bad = [n for n in names if n not in allowed]
    if bad:
        raise CliError(f"{label}: tool lạ {bad}; hợp lệ: {allowed}")
    seen: list[str] = []
    for n in names:
        if n not in seen:
            seen.append(n)
    dropped = [t for t in allowed if t not in seen]
    if dropped:
        _warn(f"{label}: bỏ tool {dropped} -> đổi MẪU SỐ eligible/κ (RULE_GAN_NHAN §3); "
              "kết quả không so trực tiếp với run đủ tool.")
    return seen


def _cheap_tool_names(args) -> list[str]:
    spec = getattr(args, "tools", None)
    names = parse_tools(spec, config.CHEAP_TOOLS_ALL, "--tools")
    if names is None:
        names = parse_tools(",".join(config.CHEAP_TOOLS), config.CHEAP_TOOLS_ALL, "ORCH_CHEAP_TOOLS")
    return names


# --------------------------------------------------------------------------------------
# Phạm vi commit
# --------------------------------------------------------------------------------------
def _check_date(v: str | None, what: str) -> str | None:
    if v is None:
        return None
    v = str(v).strip()
    try:
        datetime.date.fromisoformat(v[:10])
    except ValueError:
        raise CliError(f"{what}={v!r} không phải ISO YYYY-MM-DD") from None
    return v


def resolve_scope(args) -> dict:
    """Chuẩn hoá since/until/from_sha/to_sha + --max. --max mặc định (None) khi có scope -> ép 0 (cảnh báo).
    Gán lại vào args và trả scope dict (ghi run_meta.scope_json)."""
    since = _check_date(getattr(args, "since", None), "--since")
    until = _check_date(getattr(args, "until", None), "--until")
    if since and until and since > until:
        raise CliError(f"--since {since} > --until {until}")
    from_sha = getattr(args, "from_sha", None) or None
    to_sha = getattr(args, "to_sha", None) or None
    has_scope = bool(since or until or from_sha or to_sha)
    mx = getattr(args, "max", None)
    if mx is None:
        if has_scope:
            _warn("có --since/--until/--from-sha/--to-sha mà --max để mặc định -> ép --max 0 (không giới hạn)")
            mx = 0
        else:
            mx = config.PILOT_MAX_COMMITS
    elif mx < 0:
        raise CliError(f"--max {mx} < 0")
    args.max, args.since, args.until, args.from_sha, args.to_sha = mx, since, until, from_sha, to_sha
    return enm.scope_dict(mx, since, until, from_sha, to_sha)


def _enumerate(args):
    scope = resolve_scope(args)
    try:
        yield from enm.enumerate_repo(args.repo, args.max, args.branch, since=scope["since"],
                                      until=scope["until"], from_sha=scope["from_sha"],
                                      to_sha=scope["to_sha"])
    except enm.ScopeError as e:
        raise CliError(str(e)) from None


def _git_sha_self() -> str | None:
    try:
        return subprocess.run(["git", "-C", str(config.ROOT), "rev-parse", "HEAD"], capture_output=True,
                              text=True, errors="replace", timeout=10).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _run_meta(args, tier: str, scope: dict, tools: list) -> dict:
    """run_meta v2 (CONTRACTS §4). Store cũ bỏ qua khoá lạ; A1 store mới đọc đủ. KHÔNG có vote_threshold."""
    snap = {"env": config.effective_env(), "params_v1": config.params_v1(),
            "argv": sys.argv[1:], "profile": getattr(args, "profile_data", None)}
    return {
        "run_id": config.RUN_ID, "tier": tier,
        "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "repo": args.repo, "branch": getattr(args, "branch", None),
        "max_commits": args.max, "line_window": config.LINE_WINDOW,
        "scope": scope, "scope_json": json.dumps(scope, ensure_ascii=False),
        "config_snapshot_json": json.dumps(snap, ensure_ascii=False, default=str),
        "tools": tools, "tools_json": json.dumps(tools, ensure_ascii=False),
        "orchestrator_git_sha": _git_sha_self(), "app_version": config.APP_VERSION,
        "experiment": config.EXPERIMENT, "reason": config.EXPERIMENT_REASON,
    }


def _insert_run_meta(store, meta: dict):
    """A1 store mới: insert_run_meta(tier, **fields); store cũ: insert_run_meta(dict). Thử mới trước."""
    fields = {k: v for k, v in meta.items() if k not in ("tier", "scope", "tools", "max_commits", "line_window")}
    try:
        return store.insert_run_meta(meta["tier"], **fields)
    except TypeError:
        return store.insert_run_meta(meta)


# --------------------------------------------------------------------------------------
# enumerate / scan
# --------------------------------------------------------------------------------------
def cmd_enumerate(args):
    config.FLAG_LIMIT = args.flag_limit
    kept = total = 0
    rows = []
    for ci, keep, reason in _enumerate(args):
        total += 1
        kept += int(keep)
        if args.json:
            rows.append({"sha": ci.commit_id, "keep": keep, "reason": reason, "date": ci.author_date,
                         "files": len(ci.code_files), "added": ci.lines_added, "deleted": ci.lines_deleted})
        else:
            print(f"[{'KEEP' if keep else 'skip'}] {ci.commit_id[:8]} (+{ci.lines_added}/-{ci.lines_deleted}) "
                  f"{len(ci.code_files)} code files — {reason} — {ci.message[:50]}")
    _out(args, {"total": total, "kept": kept, "scope": enm.scope_dict(args.max, args.since, args.until,
                                                                      args.from_sha, args.to_sha),
                "commits": rows}, f"\nTổng: {total} commit | giữ để quét: {kept}")
    return EXIT_OK


def _scan_one_commit(ci, clone: Path, tools, tool_names, args, store):
    """Quét TRỌN 1 commit trên 1 clone đã checkout sẵn. Trả (status_line, n_scanned, n_wrote, n_clean).
    5 tool trong 1 worker; song song nằm ở CẤP COMMIT."""
    from .consensus.labeler import relabel_commit
    n_tools = len(tools)
    store.reset_cheap_scan(ci.commit_id)          # re-scan idempotent: xoá row lửng nếu từng bị kill
    changed = [f for f in ci.code_files if (clone / f).exists()]

    def _safe(t):
        raw = []
        try:
            fs = t.scan(clone, ci.commit_id, args.repo, changed, raw_out=raw)
        except Exception as e:  # noqa: BLE001 — 1 tool lỗi không dừng cả phễu
            print(f"[{t.name}] lỗi @ {ci.commit_id[:8]}: {e}")
            fs = []
        if raw:
            store.insert_raw_output(ci.commit_id, t.name, raw[0][0], raw[0][1])
        return fs

    all_findings = []
    if config.CHEAP_INTRA_PARALLEL:
        with ThreadPoolExecutor(max_workers=len(tools)) as ex:
            for res in ex.map(_safe, tools):
                all_findings += res
    else:
        for t in tools:
            all_findings += _safe(t)

    all_findings = [f for f in all_findings if not enm.is_excluded_path(f.file_path)]
    # LƯU RAW từng-tool -> RELABEL (gộp cụm + vote tier-aware + enrich). Nhãn dẫn xuất từ raw.
    store.insert_raw(all_findings)
    rows = relabel_commit(store, ci.commit_id, clone, args.repo)

    files_with_finding = {r.file_path for r in rows}
    store.insert_scanned_files([{
        "repo": args.repo, "commit_id": ci.commit_id,
        "parent_commit": ci.parent_commit, "author_date": ci.author_date,
        "file_path": f, "n_tools_ran": n_tools, "tools": tool_names,
        "n_findings": sum(1 for r in rows if r.file_path == f),
    } for f in changed])
    clean = sum(1 for f in changed if f not in files_with_finding)
    store.mark_scan_done(ci.commit_id)            # mốc resume — ghi CUỐI CÙNG
    status = f"[{ci.commit_id[:8]}] {len(changed)} file đổi | {len(all_findings)} findings -> {len(rows)} cụm"
    return status, 1, len(rows), clean


def cmd_scan(args):
    from .repo_pool import RepoPool
    from .storage.sqlite_store import SQLiteStore
    config.FLAG_LIMIT = args.flag_limit
    scope = resolve_scope(args)
    tool_names = _cheap_tool_names(args)
    registry = cheap_tool_classes()
    tools = [registry[n]() for n in tool_names]
    repo_dir = enm.clone_or_update(args.repo)
    store = SQLiteStore()
    scanned = wrote = clean = 0

    if not args.no_meta:
        print("Thu thập version/digest tool...")
        _insert_run_meta(store, _run_meta(args, "scan", scope, [
            {"name": t.name, "version": t.version(), "digest": t.digest()} for t in tools]))

    todo, skipped_big = [], []
    for ci, keep, reason in _enumerate(args):
        if keep:
            todo.append(ci)
        elif reason.startswith((">", "diff file lớn")):
            skipped_big.append((ci.commit_id, reason))
    for sha, reason in skipped_big:
        print(f"[{sha[:8]}] BỎ QUA: {reason}")

    if config.KAMEI_ENABLED and todo:
        from . import kamei
        t0 = time.time()
        rev = enm.resolve_rev(repo_dir, args.branch)
        feats = kamei.compute_features(repo_dir, {ci.commit_id for ci in todo}, rev)
        store.upsert_commit_features(args.repo, feats)
        print(f"Kamei: 14 đặc trưng cho {len(feats)}/{len(todo)} commit ({time.time() - t0:.1f}s)")

    if config.SCAN_RESUME:
        done_ids = store.scan_done_ids()
        n_skip = sum(1 for ci in todo if ci.commit_id in done_ids)
        if n_skip:
            todo = [ci for ci in todo if ci.commit_id not in done_ids]
            print(f"RESUME: bỏ qua {n_skip} commit đã quét xong ở run trước")

    workers = max(1, min(config.SCAN_WORKERS, len(todo) or 1))
    print(f"Song song CẤP COMMIT: {workers} worker (clone pool) | {len(todo)} commit cần quét "
          f"| bỏ qua khổng lồ: {len(skipped_big)} | tool: {tool_names}")
    progress.emit(phase="scan", event="start", total=len(todo), msg=f"tools={','.join(tool_names)}")
    if not todo:
        progress.emit(phase="scan", event="done", done=0, total=0)
        store.close()
        return EXIT_OK

    pool = RepoPool(repo_dir, workers, repo=args.repo)

    def _process(ci):
        clone = pool.acquire()
        try:
            pool.checkout(clone, ci.commit_id)
            st, ns, nw, nc = _scan_one_commit(ci, clone, tools, tool_names, args, store)
            return ci.commit_id, "ok", st, ns, nw, nc
        except Exception as e:  # noqa: BLE001 — 1 commit lỗi không dừng cả run
            return ci.commit_id, "tool_error", f"[{ci.commit_id[:8]}] LỖI: {e}", 0, 0, 0
        finally:
            pool.release(clone)

    stopped = False
    done = 0
    it = iter(todo)
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            pending = set()

            def _submit_next() -> bool:
                ci = next(it, None)
                if ci is None:
                    return False
                pending.add(ex.submit(_process, ci))
                return True

            for _ in range(workers):
                if not _submit_next():
                    break
            while pending:
                finished, pending = wait(pending, return_when=FIRST_COMPLETED)
                for fut in finished:
                    sha, status, st, ns, nw, nc = fut.result()
                    done += 1
                    scanned += ns; wrote += nw; clean += nc
                    print(st, flush=True)
                    progress.emit(phase="scan", event="item", done=done, total=len(todo), sha=sha,
                                  status=status, msg=st.split("] ", 1)[-1][:120])
                # Stop-file: kiểm GIỮA commit — không claim commit mới, chờ commit đang chạy xong.
                if not stopped and progress.should_stop():
                    stopped = True
                    print("STOP-FILE phát hiện: không nhận commit mới, chờ commit đang quét xong...", flush=True)
                if not stopped:
                    while len(pending) < workers and _submit_next():
                        pass
    finally:
        pool.cleanup()

    print(f"\nĐã quét {scanned} commit | bỏ qua khổng lồ {len(skipped_big)} | "
          f"findings(cụm): {wrote} | file clean(negative): {clean}")
    print(f"DB: {store.count()} findings, {store.count_clean()} clean files")
    store.close()
    if stopped:
        progress.emit(phase="scan", event="stop", done=done, total=len(todo), status="stopped",
                      msg="dừng theo stop-file")
        return EXIT_STOP
    progress.emit(phase="scan", event="done", done=done, total=len(todo))
    return EXIT_OK


# --------------------------------------------------------------------------------------
# select / analyze / relabel / kappa / features / export
# --------------------------------------------------------------------------------------
def cmd_select(args):
    from . import select_commits
    from .storage.sqlite_store import SQLiteStore
    config.SUSPECT_REQUIRE_IN_DIFF = (args.require_in_diff == 1 if args.require_in_diff is not None
                                      else config.SUSPECT_REQUIRE_IN_DIFF)
    progress.emit(phase="select", event="start")
    store = SQLiteStore()
    res = select_commits.select(store, include_clean=args.include_clean)
    store.close()
    lines = [f"Universe (commit đã quét tầng rẻ): {res['universe']}",
             f"  buggy (có mã CWE/CVE{', in_diff' if config.SUSPECT_REQUIRE_IN_DIFF else ''}) "
             f"-> TẦNG ĐẮT (positive): {res['buggy']}"]
    if args.include_clean:
        lines += [f"  clean -> CŨNG đưa vào tầng đắt để VERIFY (→ verified-clean GOLD): {res['negative_clean']}",
                  f"=> đã thêm (incremental) {res['total_selected']} commit vào hàng đợi."]
    else:
        lines += [f"  clean (0 CWE/CVE) -> NEGATIVE (không quét đắt): {res['negative_clean']}",
                  f"=> selected_commits (hàng đợi đắt) = {res['total_selected']} commit buggy."]
    _out(args, res, "\n".join(lines))
    progress.emit(phase="select", event="done", done=res["total_selected"], total=res["universe"])
    return EXIT_OK


def _expensive_tool_names(args) -> list[str] | None:
    spec = getattr(args, "expensive_tools", None)
    legacy = getattr(args, "tools", None)
    if spec is None and legacy is not None:
        _warn("analyze --tools là alias cũ của --expensive-tools (tầng đắt); hãy dùng --expensive-tools")
        spec = legacy
    return parse_tools(spec, config.EXPENSIVE_TOOLS_ALL, "--expensive-tools")


def cmd_analyze(args):
    from . import expensive_runner
    if args.codeql is not None:
        config.USE_CODEQL = args.codeql
    tools = _expensive_tool_names(args)
    res = expensive_runner.analyze(args.repo, workers=args.workers, dry_run=bool(args.dry_run), tools=tools,
                                   branch=getattr(args, "branch", None))
    _out(args, res, f"\nXong: done={res.get('done', 0)} build_failed={res.get('build_failed', 0)} "
                    f"skipped={res.get('skipped', 0)} infra_error={res.get('infra_error', 0)} "
                    f"tool_timeout={res.get('tool_timeout', 0)} | {res.get('workers')} worker, tool {res.get('tools')}\n"
                    f"selected_commits status: {res.get('status_counts')}")
    if res.get("stopped"):
        print(f"⏹ analyze DỪNG: {res.get('stop_reason') or 'stop-file'}", file=sys.stderr)
        return EXIT_STOP
    return EXIT_OK


def cmd_relabel(args):
    """Gán nhãn LẠI mọi commit từ raw_findings (áp filter nhiễu hiện tại). KHÔNG quét lại."""
    from .consensus.labeler import relabel_commit
    from .storage.sqlite_store import SQLiteStore
    repo_dir = enm.clone_or_update(args.repo)   # dùng git show (sha-scoped) — không checkout
    store = SQLiteStore()
    ids = store.all_commit_ids()
    progress.emit(phase="relabel", event="start", total=len(ids))
    for i, cid in enumerate(ids, 1):
        relabel_commit(store, cid, repo_dir, args.repo)
        if i % 50 == 0 or i == len(ids):
            progress.emit(phase="relabel", event="item", done=i, total=len(ids), sha=cid, status="ok")
    labels = dict(store.conn.execute("SELECT label,COUNT(*) FROM findings GROUP BY label"))
    _out(args, {"relabeled": len(ids), "noise_cwe": sorted(config.NOISE_CWE),
                "noise_rules": sorted(config.NOISE_RULES), "findings": store.count(), "labels": labels},
         f"Relabel {len(ids)} commit | lọc nhiễu CWE={sorted(config.NOISE_CWE)} "
         f"rules={sorted(config.NOISE_RULES) or '-'}\nDB: {store.count()} findings | label: {labels}")
    store.close()
    progress.emit(phase="relabel", event="done", done=len(ids), total=len(ids))
    return EXIT_OK


def _fmt_k(v) -> str:
    return f"{v:.3f}" if isinstance(v, (int, float)) else "-"


def cmd_kappa(args):
    from . import kappa as kp
    from .storage.sqlite_store import SQLiteStore
    progress.emit(phase="kappa", event="start")
    store = SQLiteStore()
    res = kp.compute_all(store)
    n_saved = kp.save_all(store, res, progress.run_id())
    store.close()
    lines = [f"Fleiss' kappa TỔNG: {_fmt_k(res['total'])}  ({kp._label(res['total'])}) | {res['n']} item ≥2 rater",
             "theo CATEGORY:"]
    lines += [f"  {r['group']:8} κ={_fmt_k(r['value']):>7}  ({kp._label(r['value'])}) n={r['n']}"
              for r in res["by_category"]]
    lines.append("theo NHÓM-CWE (n≥5):")
    lines += [f"  {r['group']:18} κ={_fmt_k(r['value']):>7}  n={r['n']}" for r in res["by_group"]]
    lines.append("theo CẶP TOOL:")
    lines += [f"  {r['group']:22} κ={_fmt_k(r['value']):>7}  n={r['n']}" for r in res["pairs"]]
    lines.append(f"(đã lưu {n_saved} dòng vào bảng kappa, run_id={progress.run_id()})" if n_saved
                 else "(bảng kappa chưa có — chỉ in; A1 tạo bảng ở schema v2)")
    _out(args, {**res, "saved": n_saved, "run_id": progress.run_id()}, "\n".join(lines))
    progress.emit(phase="kappa", event="done", done=res["n"], total=res["n"])
    return EXIT_OK


def cmd_features(args):
    """Backfill 14 đặc trưng Kamei cho MỌI commit đã có trong DB (không quét lại), rồi relabel."""
    from . import kamei
    from .consensus.labeler import relabel_commit
    from .storage.sqlite_store import SQLiteStore
    repo_dir = enm.clone_or_update(args.repo)
    rev = enm.resolve_rev(repo_dir, args.branch)
    store = SQLiteStore()
    targets = set(store.all_commit_ids())
    t0 = time.time()
    feats = kamei.compute_features(repo_dir, targets, rev)
    store.upsert_commit_features(args.repo, feats)
    missing = targets - feats.keys()
    print(f"Kamei: tính {len(feats)}/{len(targets)} commit ({time.time() - t0:.1f}s)"
          + (f" | thiếu {len(missing)} (merge/ngoài nhánh {rev})" if missing else ""))
    for cid in feats:
        relabel_commit(store, cid, repo_dir, args.repo)
    print(f"Đã nhúng vào label rows (relabel {len(feats)} commit).")
    for col in ("nf", "entropy", "lt", "exp", "ndev", "fix"):
        r = store.conn.execute(f"SELECT MIN({col}), ROUND(AVG({col}),3), MAX({col}) FROM commit_features").fetchone()
        print(f"  {col:8} min={r[0]} avg={r[1]} max={r[2]}")
    store.close()
    return EXIT_OK


def cmd_export(args):
    from . import export_dataset
    from .storage.sqlite_store import SQLiteStore
    progress.emit(phase="export", event="start")
    store = SQLiteStore()
    out_dir = Path(args.out or config.EXPORT_DIR)
    try:
        res = export_dataset.export_all(store, out_dir, profile=getattr(args, "profile_data", None),
                                        run_id=progress.run_id())
    except TypeError:                       # export cũ chưa nhận profile/run_id
        res = export_dataset.export_all(store, out_dir)
    store.close()
    if str(res.get("out", out_dir)) != str(out_dir):
        _warn(f"export: đích {out_dir} không rỗng -> ghi sang thư mục mới {res['out']}")
    _out(args, res, f"Export {res.get('commits')} commit | {res.get('raw_files')} file raw -> {res.get('out')}\n"
                    f"negatives: {res.get('negatives', {})} (verified-clean = qua tầng đắt; cheap-clean = chỉ rẻ)")
    progress.emit(phase="export", event="done", done=res.get("commits"), total=res.get("commits"))
    return EXIT_OK


# --------------------------------------------------------------------------------------
# pipeline
# --------------------------------------------------------------------------------------
def cmd_pipeline(args):
    """Chạy TRỌN pipeline: scan -> select -> analyze -> relabel -> kappa -> export. Dừng khi 1 bước != 0."""
    scope = resolve_scope(args)
    cheap = parse_tools(args.tools, config.CHEAP_TOOLS_ALL, "--tools")
    expensive = parse_tools(args.expensive_tools, config.EXPENSIVE_TOOLS_ALL, "--expensive-tools")
    ns = argparse.Namespace(
        repo=args.repo, max=args.max, branch=args.branch, since=args.since, until=args.until,
        from_sha=args.from_sha, to_sha=args.to_sha, flag_limit=args.flag_limit, no_meta=args.no_meta,
        require_in_diff=None, include_clean=args.include_clean, workers=args.workers,
        tools=",".join(cheap) if cheap else None,
        expensive_tools=",".join(expensive) if expensive else None,
        dry_run=False, codeql=args.codeql, out=args.out, json=False,
        profile_data=getattr(args, "profile_data", None),
    )
    steps = [("① SCAN (tầng rẻ)", cmd_scan), ("② SELECT", cmd_select),
             ("③ ANALYZE (tầng đắt)", cmd_analyze), ("④ RELABEL", cmd_relabel),
             ("⑤ KAPPA", cmd_kappa), ("⑥ EXPORT", cmd_export)]
    t0 = time.time()
    print(f"scope={scope} | cheap={cheap or 'mặc định'} | expensive={expensive or 'mặc định'}")
    for i, (name, fn) in enumerate(steps, 1):
        print(f"\n{'=' * 60}\n>>> {name}  ({i}/{len(steps)})\n{'=' * 60}", flush=True)
        if fn is cmd_analyze:
            ns.tools = None                  # cmd_analyze: --tools là alias đắt; cheap đã dùng xong ở scan
        code = fn(ns) or EXIT_OK
        if code == EXIT_STOP:
            print(f"\n⏹ PIPELINE DỪNG theo stop-file tại bước {name} sau {int(time.time() - t0)}s")
            return EXIT_STOP
        if code != EXIT_OK:
            print(f"\n✖ PIPELINE LỖI tại bước {name} (exit {code})")
            return code
    print(f"\n{'=' * 60}\n✅ PIPELINE XONG sau {int(time.time() - t0)}s "
          f"| DB: {config.SQLITE_PATH} | export: {ns.out or config.EXPORT_DIR}\n{'=' * 60}")
    return EXIT_OK


# --------------------------------------------------------------------------------------
# Lệnh mới (CONTRACTS §11): estimate / stats / sensitivity / compare / stop / clean
# --------------------------------------------------------------------------------------
def cmd_estimate(args):
    from . import estimate
    p = getattr(args, "profile_data", None)
    if p is None:
        raise CliError("estimate cần --profile F")
    res = estimate.estimate(p)
    _out(args, res, estimate.format_text(res))
    return EXIT_OK


def cmd_stats(args):
    from . import stats
    db = Path(args.db or config.SQLITE_PATH)
    if not db.exists():
        raise CliError(f"DB không tồn tại: {db}")
    progress.emit(phase="stats", event="start")
    ov = stats.overview(db, run_id=args.run_id)
    if args.out:
        files = stats.write(ov, Path(args.out), args.format)
        _out(args, {"out": str(args.out), "files": files, "overview": ov},
             f"stats {args.format} -> {args.out}: {len(files)} file")
    elif args.format == "json" or args.json:
        print(json.dumps(ov, ensure_ascii=False, indent=None if args.json else 2, default=str))
    else:
        print(stats.render(ov, args.format))
    progress.emit(phase="stats", event="done")
    return EXIT_OK


def cmd_sensitivity(args):
    from . import sensitivity
    db = Path(args.db)
    if not db.exists():
        raise CliError(f"DB không tồn tại: {db}")
    try:
        grid = sensitivity.parse_grid(args.grid)
    except ValueError as e:
        raise CliError(str(e)) from None
    res = sensitivity.run(db, Path(args.out), grid, repo=args.repo)
    _out(args, res, sensitivity.to_markdown(res))
    return EXIT_OK


def cmd_compare(args):
    from . import compare
    res = compare.compare(args.a, args.b)
    if args.format == "md" and not args.json:
        print(compare.to_markdown(res))
    else:
        print(json.dumps(res, ensure_ascii=False, indent=None if args.json else 2, default=str))
    return EXIT_OK if res["ok"] else 1


def cmd_stop(args):
    from . import control
    res = control.stop(args.run, force=args.force)
    _out(args, res, f"stop run={args.run}: stop-file={res['stop_file']} | killed={res.get('killed')} "
                    f"| cleaned={res.get('cleaned')}")
    return EXIT_OK if not res.get("errors") else EXIT_RUNTIME


def cmd_stop_cleanup(args):
    from . import control
    res = control.stop_cleanup(args.run)
    _out(args, res, f"stop-cleanup run={args.run}: containers={res['containers']} networks={res['networks']} "
                    f"| reset-claims={res.get('reset_claims')} | errors={res['errors']}")
    return EXIT_OK if not res["errors"] else EXIT_RUNTIME


def cmd_reset_claims(args):
    from . import control
    db = Path(args.db or config.SQLITE_PATH)
    if not db.exists():
        raise CliError(f"DB không tồn tại: {db}")
    res = control.reset_claims(db, run_id=args.run, all_stale=args.all_stale)
    _out(args, res, f"reset-claims: {res['reset']} commit building/analyzing -> pending "
                    f"(run={res['run_id'] or 'TẤT CẢ'}) | xoá raw đắt bán phần của {len(res['commits'])} commit "
                    f"(expensive_runs giữ làm telemetry — A1 store.reset_claims)")
    return EXIT_OK


def cmd_clean(args):
    """Dọn artifact theo TỪNG MỤC; --dry-run liệt kê {path, bytes}; export/db bắt buộc chỉ đường dẫn."""
    from . import control
    try:
        items = control.parse_items(args.items)
    except ValueError as e:
        raise CliError(str(e)) from None
    plan = control.clean_plan(args.repo, items)
    if args.dry_run:
        res = {"would_delete": plan["would_delete"], "deleted": [], "errors": plan["errors"]}
    else:
        res = control.clean_apply(plan)
    text = "\n".join([f"[{'DRY' if args.dry_run else 'XOÁ'}] {d['path']} ({d['bytes']:,} B)"
                      for d in (res["would_delete"] if args.dry_run else res["deleted"])]
                     + [f"[LỖI] {e}" for e in res["errors"]]) or "(không có gì)"
    _out(args, res, text)
    return EXIT_OK if not res["errors"] else EXIT_RUNTIME


# --------------------------------------------------------------------------------------
# Đợt 2: review (A1 module `orchestrator.review`) / batch / diagnostics
# --------------------------------------------------------------------------------------
def _open_store(db_arg, readonly: bool = False):
    from .storage.sqlite_store import SQLiteStore
    db = Path(db_arg or config.SQLITE_PATH)
    if not db.exists():
        raise CliError(f"DB không tồn tại: {db}")
    try:
        return SQLiteStore(db, readonly=readonly)
    except TypeError:                                   # store cũ không có readonly
        return SQLiteStore(db)


def cmd_review(args):
    """review sample|next|verdict|close -> orchestrator.review (A1). Import trễ: module có thể chưa tồn tại."""
    try:
        from . import review
    except ImportError:
        raise CliError("orchestrator.review chưa có (A1 đợt 2) — lệnh review chưa dùng được") from None
    progress.emit(phase="review", event="start", msg=args.review_cmd)
    store = _open_store(args.db, readonly=(args.review_cmd == "next"))
    try:
        if args.review_cmd == "sample":
            res = review.sample(store, seed=args.seed, n_pos=args.n_pos, n_neg=args.n_neg)
            text = (f"sample {res.get('sample_id')}: pos={res.get('n_pos')} neg={res.get('n_neg')} "
                    f"| strata={res.get('strata')}")
        elif args.review_cmd == "next":
            res = review.next_item(store, sample_id=args.sample_id, rater=args.rater)
            if not res:
                res, text = {"done": True, "remaining": 0}, "hết mẫu cần chấm"
            else:
                text = (f"cluster {res.get('cluster_key')} | CWE claim: {res.get('cwe_claim')} "
                        f"| còn {res.get('remaining')}\n" + "\n".join(
                            f"  {d.get('n', ''):>5} {d.get('kind', ''):4} {d.get('text', '')}"
                            for d in (res.get("code_lines") or res.get("diff_lines") or [])[:60]))
        elif args.review_cmd == "verdict":
            res = review.verdict(store, sample_id=args.sample_id, rater=args.rater, cluster_key=args.cluster_key,
                                 verdict=args.verdict, note=args.note or "")
            text = f"đã ghi {args.verdict} cho {args.cluster_key[:12]} | còn {res.get('remaining')}"
        else:
            raters = [r.strip() for r in args.raters.split(",")] if args.raters else None
            res = review.close(store, sample_id=args.sample_id, raters=raters)
            pr = res.get("precision") or {}
            text = (f"close {args.sample_id}: precision={pr.get('point')} (n={pr.get('n')}, TP={pr.get('tp')}, "
                    f"FP={pr.get('fp')}, unclear={pr.get('unclear')}) CI95=[{pr.get('ci_low')}, {pr.get('ci_high')}] "
                    f"| κ rater={res.get('kappa_raters')} | bất đồng={len(res.get('disagreements') or [])}")
    finally:
        store.close()
    _out(args, res, text)
    progress.emit(phase="review", event="done", msg=args.review_cmd)
    return EXIT_OK


def cmd_batch(args):
    from . import batch
    q = Path(args.queue)
    if not q.exists():
        raise CliError(f"queue không tồn tại: {q}")
    try:
        state = batch.run(q, state_path=args.state, stop_file=args.stop_file)
    except (ValueError, FileNotFoundError) as e:
        raise CliError(str(e)) from None
    _out(args, state, batch.format_text(state))
    return int(state.get("exit_code", EXIT_OK))


def cmd_diagnostics(args):
    from . import diagnostics
    out = Path(args.out)
    if out.suffix.lower() != ".zip":
        raise CliError(f"--out phải là file .zip: {out}")
    m = diagnostics.collect(args.run, out, profile_path=args.profile, work=args.work)
    _out(args, m, diagnostics.format_text(m))
    return EXIT_OK


# --------------------------------------------------------------------------------------
# argparse
# --------------------------------------------------------------------------------------
def _add_scope(p, with_max_default_none=True):
    p.add_argument("--max", type=int, default=None,
                   help=f"số commit mới nhất (mặc định {config.PILOT_MAX_COMMITS}; 0 = KHÔNG giới hạn; "
                        "có since/until/sha mà bỏ trống -> ép 0)")
    p.add_argument("--branch", default=None, help="nhánh cần quét (mặc định: nhánh mặc định repo)")
    p.add_argument("--since", default=None, help="committer-date từ (ISO YYYY-MM-DD)")
    p.add_argument("--until", default=None, help="committer-date đến (ISO YYYY-MM-DD)")
    p.add_argument("--from-sha", dest="from_sha", default=None, help="SHA đầu (loại), from..to")
    p.add_argument("--to-sha", dest="to_sha", default=None, help="SHA cuối (gồm)")


def build_parser() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--profile", default=None, help="profile.json: áp env + dựng argv (bỏ qua arg khác)")
    parent.add_argument("--json", action="store_true", help="in JSON ra stdout")

    p = _Parser(prog="orchestrator", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("enumerate", parents=[parent], help="liệt kê + lọc thô commit")
    pe.add_argument("repo")
    _add_scope(pe)
    pe.add_argument("--flag-limit", type=int, choices=(0, 1), default=config.FLAG_LIMIT,
                    help="1=áp ngưỡng bỏ commit khổng lồ; 0=không (mặc định 0)")
    pe.set_defaults(func=cmd_enumerate)

    ps = sub.add_parser("scan", parents=[parent], help="chạy tool tầng rẻ -> consensus -> SQLite")
    ps.add_argument("repo")
    _add_scope(ps)
    ps.add_argument("--tools", default=None, help=f"tool tầng rẻ a,b (mặc định ORCH_CHEAP_TOOLS={config.CHEAP_TOOLS})")
    ps.add_argument("--no-meta", action="store_true", help="bỏ qua thu version/digest tool (debug)")
    ps.add_argument("--flag-limit", type=int, choices=(0, 1), default=config.FLAG_LIMIT)
    ps.set_defaults(func=cmd_scan)

    psel = sub.add_parser("select", parents=[parent], help="chọn commit buggy (có CWE/CVE) cho tầng đắt")
    psel.add_argument("--require-in-diff", type=int, choices=(0, 1), default=None)
    psel.add_argument("--include-clean", action="store_true",
                      help="THÊM clean commit vào hàng đợi đắt để verify -> verified-clean GOLD negative")
    psel.set_defaults(func=cmd_select)

    pa = sub.add_parser("analyze", parents=[parent], help="TẦNG ĐẮT: selected_commits -> build + CodeQL/FSB/Sonar")
    pa.add_argument("repo")
    pa.add_argument("--workers", type=int, default=config.EXPENSIVE_WORKERS)
    pa.add_argument("--branch", default=None, help="nhánh (truyền cho runner để fetch/verify)")
    pa.add_argument("--expensive-tools", dest="expensive_tools", default=None,
                    help=f"tool đắt a,b (mặc định ORCH_EXPENSIVE_TOOLS={config.EXPENSIVE_TOOLS})")
    pa.add_argument("--tools", default=None, help="(alias cũ của --expensive-tools)")
    pa.add_argument("--dry-run", action="store_true", help="đi hết vòng đời hàng đợi mà KHÔNG build/scan")
    pa.add_argument("--codeql", type=int, choices=(0, 1), default=None, help="1=bật CodeQL, 0=tắt")
    pa.set_defaults(func=cmd_analyze)

    prl = sub.add_parser("relabel", parents=[parent], help="gán nhãn LẠI từ raw — KHÔNG quét lại")
    prl.add_argument("repo")
    prl.set_defaults(func=cmd_relabel)

    pk = sub.add_parser("kappa", parents=[parent], help="Fleiss' kappa tổng/category/nhóm-CWE/cặp tool -> bảng kappa")
    pk.set_defaults(func=cmd_kappa)

    pf = sub.add_parser("features", parents=[parent], help="backfill 14 đặc trưng Kamei + nhúng vào label")
    pf.add_argument("repo")
    pf.add_argument("--branch", default=None)
    pf.set_defaults(func=cmd_features)

    pp = sub.add_parser("pipeline", parents=[parent], help="CHẠY TRỌN: scan->select->analyze->relabel->kappa->export")
    pp.add_argument("repo")
    _add_scope(pp)
    pp.add_argument("--tools", default=None, help="tool tầng rẻ a,b")
    pp.add_argument("--expensive-tools", dest="expensive_tools", default=None, help="tool tầng đắt a,b")
    pp.add_argument("--flag-limit", type=int, choices=(0, 1), default=config.FLAG_LIMIT)
    pp.add_argument("--codeql", type=int, choices=(0, 1), default=None)
    pp.add_argument("--include-clean", action="store_true")
    pp.add_argument("--workers", type=int, default=config.EXPENSIVE_WORKERS, help="số commit song song tầng đắt")
    pp.add_argument("--no-meta", action="store_true")
    pp.add_argument("--out", default=None, help="thư mục export")
    pp.set_defaults(func=cmd_pipeline)

    pex = sub.add_parser("export", parents=[parent], help="xuất export dir (per-commit + jsonl + manifest)")
    pex.add_argument("--out", default=None, help=f"thư mục xuất (mặc định {config.EXPORT_DIR})")
    pex.set_defaults(func=cmd_export)

    pes = sub.add_parser("estimate", parents=[parent], help="ước tính thời gian/đĩa từ profile + speed.json")
    pes.set_defaults(func=cmd_estimate)

    pst = sub.add_parser("stats", parents=[parent], help="overview (CONTRACTS §9) từ DB: json|csv|latex")
    pst.add_argument("--db", default=None)
    pst.add_argument("--run-id", dest="run_id", default=None)
    pst.add_argument("--format", choices=("json", "csv", "latex"), default="json")
    pst.add_argument("--out", default=None, help="thư mục ghi file (csv: 1 file/bảng)")
    pst.set_defaults(func=cmd_stats)

    pse = sub.add_parser("sensitivity", parents=[parent], help="lưới tham số trên BẢN SAO DB -> sensitivity.json/.md")
    pse.add_argument("--db", required=True)
    pse.add_argument("--out", required=True)
    pse.add_argument("--grid", nargs="*", default=None,
                     help="vd line_window=3,5,7 gold_allow_1exp_1cheap=0,1 noise=on,off")
    pse.add_argument("--repo", default=None, help="URL repo (mặc định đọc từ DB) — cần clone để relabel")
    pse.set_defaults(func=cmd_sensitivity)

    pcm = sub.add_parser("compare", parents=[parent], help="so A/B theo cluster_key (export dir hoặc DB)")
    pcm.add_argument("--a", required=True)
    pcm.add_argument("--b", required=True)
    pcm.add_argument("--format", choices=("json", "md"), default="json")
    pcm.set_defaults(func=cmd_compare)

    pstop = sub.add_parser("stop", parents=[parent], help="tạo stop-file <work>/<run>/stop; --force kill + cleanup")
    pstop.add_argument("--run", required=True)
    pstop.add_argument("--force", action="store_true")
    pstop.set_defaults(func=cmd_stop)

    pcl = sub.add_parser("stop-cleanup", parents=[parent], help="rm container label orch.run=<id> + network")
    pcl.add_argument("--run", required=True)
    pcl.set_defaults(func=cmd_stop_cleanup)

    prc = sub.add_parser("reset-claims", parents=[parent], help="building/analyzing -> pending + xoá raw đắt bán phần")
    prc.add_argument("--run", default=None, help="run_id (lọc theo expensive_runs.run_id nếu DB có cột)")
    prc.add_argument("--all-stale", dest="all_stale", action="store_true", help="mọi hàng building/analyzing")
    prc.add_argument("--db", default=None)
    prc.set_defaults(func=cmd_reset_claims)

    pc = sub.add_parser("clean", parents=[parent], help="dọn theo mục: clone,pool,m2,export:<dir>,db:<path>")
    pc.add_argument("repo")
    pc.add_argument("--items", default="clone,pool", help="mặc định clone,pool")
    pc.add_argument("--dry-run", dest="dry_run", action="store_true")
    pc.set_defaults(func=cmd_clean)

    prv = sub.add_parser("review", parents=[parent], help="kiểm tay GOLD (mù): sample | next | verdict | close")
    prv.add_argument("--db", default=None)
    rsub = prv.add_subparsers(dest="review_cmd", required=True)
    # `--json` sau sub-subcommand: SUPPRESS để không ghi đè giá trị đã parse ở cấp `review --json`
    rj = argparse.ArgumentParser(add_help=False)
    rj.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    r1 = rsub.add_parser("sample", parents=[rj], help="tạo mẫu phân tầng (CWE-group × tier), seed cố định")
    r1.add_argument("--seed", type=int, default=42)
    r1.add_argument("--n-pos", dest="n_pos", type=int, default=200)
    r1.add_argument("--n-neg", dest="n_neg", type=int, default=100)
    r2 = rsub.add_parser("next", parents=[rj], help="lấy mục kế tiếp cho rater (ẩn nhãn/tool)")
    r2.add_argument("--sample-id", dest="sample_id", required=True)
    r2.add_argument("--rater", required=True)
    r3 = rsub.add_parser("verdict", parents=[rj], help="ghi phán quyết TP|FP|unclear")
    r3.add_argument("--sample-id", dest="sample_id", required=True)
    r3.add_argument("--rater", required=True)
    r3.add_argument("--cluster-key", dest="cluster_key", required=True)
    r3.add_argument("--verdict", choices=("TP", "FP", "unclear"), required=True)
    r3.add_argument("--note", default="")
    r4 = rsub.add_parser("close", parents=[rj], help="đóng mẫu: precision + Wilson + Cohen κ + bất đồng")
    r4.add_argument("--sample-id", dest="sample_id", required=True)
    r4.add_argument("--raters", default=None, help="a,b (mặc định: mọi rater đã chấm)")
    prv.set_defaults(func=cmd_review)

    pb = sub.add_parser("batch", parents=[parent], help="chạy TUẦN TỰ nhiều profile: pipeline --profile từng cái")
    pb.add_argument("--queue", required=True, help="Q.json: [\"a.json\", ...] hoặc {profiles:[...], stop_on_error}")
    pb.add_argument("--state", default=None, help="batch_state.json (mặc định cạnh Q.json)")
    pb.add_argument("--stop-file", dest="stop_file", default=None, help="mặc định <Q.json>.stop")
    pb.set_defaults(func=cmd_batch)

    pdg = sub.add_parser("diagnostics", parents=[parent], help="gói chẩn đoán ZIP cho 1 run (log, progress, run_meta, docker…)")
    pdg.add_argument("--run", required=True)
    pdg.add_argument("--out", required=True, help="đường dẫn file .zip")
    pdg.add_argument("--work", default=None, help="thư mục work chứa <run_id>/ (mặc định ORCH_WORK_DIR)")
    pdg.set_defaults(func=cmd_diagnostics)

    return p


# --------------------------------------------------------------------------------------
# --profile: áp env TRƯỚC, dựng argv
# --------------------------------------------------------------------------------------
def _find_profile(argv: list[str]) -> str | None:
    for i, a in enumerate(argv):
        if a == "--profile" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--profile="):
            return a.split("=", 1)[1]
    return None


def profile_argv(p: dict, cmd: str) -> list[str]:
    """argv cho subcommand `cmd` từ profile (pipeline = profile.to_cli_args)."""
    if cmd == "pipeline":
        return prof.to_cli_args(p)
    full = prof.to_cli_args(p)[2:]           # bỏ 'pipeline <repo>'

    def pick(*names):
        out = []
        i = 0
        while i < len(full):
            a = full[i]
            if a in names:
                out.append(a)
                if i + 1 < len(full) and not full[i + 1].startswith("--"):
                    out.append(full[i + 1]); i += 1
            i += 1
        return out

    scope = ("--branch", "--max", "--since", "--until", "--from-sha", "--to-sha")
    if cmd == "enumerate":
        return [cmd, p["repo"], *pick(*scope)]
    if cmd == "scan":
        return [cmd, p["repo"], *pick(*scope, "--tools")]
    if cmd == "select":
        return [cmd, *pick("--include-clean")]
    if cmd == "analyze":
        return [cmd, p["repo"], *pick("--workers", "--expensive-tools", "--codeql")]
    if cmd in ("relabel",):
        return [cmd, p["repo"]]
    if cmd == "features":
        return [cmd, p["repo"], *pick("--branch")]
    if cmd == "export":
        return [cmd, *pick("--out")]
    return [cmd]


def apply_profile(argv: list[str]) -> tuple[dict | None, list[str]]:
    """Nạp --profile (nếu có): áp env, config.reload(), dựng lại argv cho lệnh PROFILE_DRIVEN."""
    path = _find_profile(argv)
    if not path:
        return None, argv
    p = prof.load(path)                      # ProfileError -> exit 1 ở main
    os.environ.update(prof.to_env(p))
    config.reload()
    cmd = next((a for a in argv if not a.startswith("-") and a != path), None)
    if cmd in PROFILE_DRIVEN:
        others = [a for a in argv if a not in ("--profile", path, cmd) and not a.startswith("--profile=")
                  and a != "--json"]
        if others:
            _warn(f"--profile: bỏ qua arg khác {others} (profile là nguồn duy nhất)")
        new = profile_argv(p, cmd) + ["--profile", path] + (["--json"] if "--json" in argv else [])
        return p, new
    return p, argv


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        pdata, argv = apply_profile(argv)
        parser = build_parser()
        args = parser.parse_args(argv)
        args.profile_data = pdata
        code = args.func(args)
        return int(code or EXIT_OK)
    except CliError as e:
        print(f"LỖI tham số: {e}", file=sys.stderr)
        return EXIT_ARGS
    except (prof.ProfileError, enm.ScopeError) as e:
        print(f"LỖI tham số: {e}", file=sys.stderr)
        return EXIT_ARGS
    except FileNotFoundError as e:
        print(f"LỖI tham số: không tìm thấy {e.filename or e}", file=sys.stderr)
        return EXIT_ARGS
    except KeyboardInterrupt:
        print("Ngắt bởi người dùng (Ctrl+C)", file=sys.stderr)
        return EXIT_RUNTIME
    except Exception as e:  # noqa: BLE001 — mọi lỗi runtime -> exit 2, có traceback khi ORCH_DEBUG=1
        if os.environ.get("ORCH_DEBUG") == "1":
            raise
        print(f"LỖI runtime: {type(e).__name__}: {e}", file=sys.stderr)
        return EXIT_RUNTIME


if __name__ == "__main__":
    sys.exit(main())
