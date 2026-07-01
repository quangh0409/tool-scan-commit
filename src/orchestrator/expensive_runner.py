"""
Runner TẦNG ĐẮT (Model A): song song CẤP COMMIT, 3 tool TUẦN TỰ / commit, build dùng chung.

Hợp đồng = bảng selected_commits (pull + CLAIM nguyên tử). Bền + resume sau STOP VM:
  - đầu run: reset hàng 'building/analyzing' treo -> 'pending'.
  - mỗi worker: claim_next -> checkout(clone-pool) -> build 1 lần -> CodeQL/FindSecBugs/Sonar
    -> ghi expensive_runs -> set status. build fail = dữ liệu (build_failed), không crash.
Sonar server = 1 singleton bật/tắt 1 lần cả run.

SKELETON: tool trả [] tới khi PoC xong; phần ghi findings + consensus rẻ+đắt là TODO(§6).
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config, enumerate_commits as enm
from .consensus.labeler import relabel_commit
from .repo_pool import RepoPool
from .storage.sqlite_store import SQLiteStore
from .tools_expensive.build import build_commit
from .tools_expensive.codeql import CodeQLTool
from .tools_expensive.findsecbugs import FindSecBugsTool
from .tools_expensive.sonar import SonarTool

_REGISTRY = {"codeql": CodeQLTool, "findsecbugs": FindSecBugsTool, "sonar": SonarTool}


def _make_tools(names):
    return [_REGISTRY[n]() for n in names if n in _REGISTRY]


def _store_expensive(store, all_findings, clone, cid, repo) -> int:
    """Ghi raw ĐẮT rồi RELABEL toàn commit (gộp raw rẻ+đắt -> nhãn cross-tier gold/silver)."""
    store.insert_raw(all_findings)
    rows = relabel_commit(store, cid, clone, repo)
    return len(rows)


def _process(cid, worker, store, pool, tools, repo, dry_run):
    clone = pool.acquire()
    try:
        pool.checkout(clone, cid)
        if dry_run:  # đi hết vòng đời mà KHÔNG build/scan — kiểm khung hàng đợi
            store.insert_expensive_run({"commit_id": cid, "tool": "-", "phase": "build",
                                        "status": "skipped", "n_findings": 0,
                                        "duration_sec": 0.0, "error": "dry-run"})
            store.set_commit_status(cid, "done", build_status="dry-run", finished=True)
            return ("done", cid)

        ctx = build_commit(clone, cid, repo)
        store.insert_expensive_run({"commit_id": cid, "tool": "maven", "phase": "build",
                                    "status": "ok" if ctx.ok else "failed", "n_findings": 0,
                                    "duration_sec": ctx.duration_sec, "error": ctx.error})
        if not ctx.ok:
            store.set_commit_status(cid, "build_failed", build_status="failed", finished=True)
            return ("build_failed", cid)

        store.set_commit_status(cid, "analyzing", build_status="ok")

        all_findings = []
        flock = threading.Lock()

        def _run_tool(t):
            t0 = time.time()
            raw = []
            try:
                findings = t.scan(ctx, raw_out=raw)
                err, status = None, "ok"
            except Exception as e:  # noqa: BLE001 — 1 tool lỗi không hỏng cả commit
                findings, err, status = [], str(e), "failed"
            if raw:  # (B) lưu output thô
                store.insert_raw_output(cid, t.name, raw[0][0], raw[0][1])
            store.insert_expensive_run({"commit_id": cid, "tool": t.name, "phase": "analyze",
                                        "status": status, "n_findings": len(findings),
                                        "duration_sec": round(time.time() - t0, 1), "error": err})
            with flock:
                all_findings.extend(findings)

        if config.EXPENSIVE_INTRA_PARALLEL and len(tools) > 1:   # Model B: 3 tool song song sau build
            with ThreadPoolExecutor(max_workers=len(tools)) as ex:
                list(ex.map(_run_tool, tools))
        else:                                          # Model A: tuần tự
            for t in tools:
                _run_tool(t)

        # write-back: consensus (trong nhóm tool đắt) + enrich + tier=expensive -> bảng findings
        _store_expensive(store, all_findings, clone, cid, repo)
        store.set_commit_status(cid, "done", finished=True)
        return ("done", cid)
    finally:
        pool.release(clone)


def analyze(repo: str, workers: int | None = None, dry_run: bool = False,
            tools: list[str] | None = None) -> dict:
    workers = workers or config.EXPENSIVE_WORKERS
    names = tools if tools else config.EXPENSIVE_TOOLS
    if not config.USE_CODEQL:                       # công tắc riêng tắt CodeQL (nút thắt)
        names = [n for n in names if n != "codeql"]
    repo_dir = enm.clone_or_update(repo)
    store = SQLiteStore()

    reset = store.reset_stale_claims(config.STALE_CLAIM_SEC)
    if reset:
        print(f"Reset {reset} commit treo -> pending (resume).")

    tool_objs = _make_tools(names)
    sonar = next((t for t in tool_objs if isinstance(t, SonarTool)), None)
    if sonar and not dry_run:
        print("Bật SonarQube server (singleton)...")
        sonar.start_server()

    pool = RepoPool(repo_dir, workers)
    counts = {"done": 0, "build_failed": 0}
    print(f"TẦNG ĐẮT (Model A): {workers} worker | tool: {[t.name for t in tool_objs]} "
          f"| {'DRY-RUN' if dry_run else 'thật'}")

    def _loop(wid):
        while True:
            cid = store.claim_next_commit(f"w{wid}")
            if cid is None:
                return
            outcome, _ = _process(cid, f"w{wid}", store, pool, tool_objs, repo, dry_run)
            counts[outcome] = counts.get(outcome, 0) + 1
            print(f"[w{wid}] {cid[:8]} -> {outcome}")

    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(_loop, range(workers)))
    finally:
        pool.cleanup()
        if sonar and not dry_run:
            sonar.stop_server()

    res = {"workers": workers, "tools": [t.name for t in tool_objs],
           "status_counts": store.selected_status_counts(), **counts}
    store.close()
    return res
