"""
Runner TẦNG ĐẮT (Model A): song song CẤP COMMIT, 3 tool TUẦN TỰ / commit, build dùng chung.

Hợp đồng = bảng selected_commits (pull + CLAIM nguyên tử). Bền + resume sau STOP VM:
  - đầu run: reset hàng 'building/analyzing' treo -> 'pending'.
  - mỗi worker: claim_next -> checkout(clone-pool) -> build 1 lần -> CodeQL/FindSecBugs/Sonar
    -> ghi expensive_runs -> set status.
Sonar server = 1 singleton bật/tắt 1 lần cả run (tên theo run_id).

Phân loại trạng thái (CONTRACTS §1) — ghi `expensive_runs.status`:
  ok | skipped (0 module Java: tool KHÔNG chạy, KHÔNG verified) | build_failed (dữ liệu)
  | infra_error (Docker/đĩa: commit về `pending`, KHÔNG đếm là dữ liệu; 3 lần liên tiếp -> dừng run)
  | tool_timeout | tool_error.
Sau mỗi commit: cập nhật selected_commits.n_expensive_ok (D1).

progress.jsonl (CONTRACTS §3): analyze.start(total=pending) / item(worker, sha, status, msg) / done | stop.
Stop-file: kiểm progress.should_stop() TRƯỚC khi claim commit mới -> event=stop, trả {'stopped': True}
(cli set exit code 3).
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import config, enumerate_commits as enm, keys, progress
from .consensus.labeler import relabel_commit
from .repo_pool import RepoPool
from .storage import InfraError
from .storage.sqlite_store import SQLiteStore
from .tools.base import app_version, image_digest, is_infra_text, orchestrator_git_sha
from .tools_expensive.base import ToolError
from .tools_expensive.build import build_commit
from .tools_expensive.codeql import CodeQLTool
from .tools_expensive.findsecbugs import FindSecBugsTool
from .tools_expensive.sonar import SonarTool

_REGISTRY = {"codeql": CodeQLTool, "findsecbugs": FindSecBugsTool, "sonar": SonarTool}

# Số infra_error LIÊN TIẾP (toàn run, reset khi có ok) trước khi tự dừng (CONTRACTS §1).
INFRA_STOP_AFTER = int(os.environ.get("ORCH_INFRA_STOP_AFTER", "3"))


def _make_tools(names):
    return [_REGISTRY[n]() for n in names if n in _REGISTRY]


class _RunGuard:
    """Đếm infra_error liên tiếp + cờ dừng dùng chung giữa các worker (thread-safe)."""

    def __init__(self, stop_after: int = INFRA_STOP_AFTER):
        self.stop_after = max(1, stop_after)
        self._n_infra = 0
        self._lock = threading.Lock()
        self.stop_reason: str | None = None       # 'infra_error' | 'stop_file'
        self.images_used: set[str] = set()

    def record(self, outcome: str) -> None:
        with self._lock:
            if outcome == "infra_error":
                self._n_infra += 1
                if self._n_infra >= self.stop_after and not self.stop_reason:
                    self.stop_reason = "infra_error"
            elif outcome in ("done", "skipped", "build_failed"):
                self._n_infra = 0        # có kết quả thật -> hạ tầng còn sống

    def trip(self, reason: str) -> None:
        with self._lock:
            if not self.stop_reason:
                self.stop_reason = reason

    @property
    def tripped(self) -> bool:
        return self.stop_reason is not None

    @property
    def n_infra(self) -> int:
        return self._n_infra


def _store_expensive(store, all_findings, clone, cid, repo) -> int:
    """Ghi raw ĐẮT rồi RELABEL toàn commit (gộp raw rẻ+đắt -> nhãn cross-tier gold/silver)."""
    all_findings = [f for f in all_findings if not enm.is_excluded_path(f.file_path)]
    store.insert_raw(all_findings)
    rows = relabel_commit(store, cid, clone, repo)
    return len(rows)


def _classify_tool_exc(e: BaseException) -> tuple[str, str]:
    """Exception của 1 tool -> (status, msg) theo CONTRACTS §1."""
    msg = str(e)[:1000]
    if isinstance(e, subprocess.TimeoutExpired):
        return "tool_timeout", f"timeout {getattr(e, 'timeout', '?')}s"
    if isinstance(e, FileNotFoundError) or is_infra_text(msg):
        return "infra_error", msg
    if isinstance(e, ToolError):
        return "tool_error", msg
    return "tool_error", msg


def _process(cid, worker, store, pool, tools, repo, dry_run, guard: _RunGuard | None = None):
    """Xử lý 1 commit. Trả (outcome, cid, msg) với outcome ∈
    done | skipped | build_failed | infra_error | tool_timeout."""
    clone = pool.acquire()
    try:
        pool.checkout(clone, cid)
        if dry_run:  # đi hết vòng đời mà KHÔNG build/scan — kiểm khung hàng đợi
            store.insert_expensive_run({"commit_id": cid, "tool": "-", "phase": "build",
                                        "status": "skipped", "n_findings": 0,
                                        "duration_sec": 0.0, "error": "dry-run"})
            store.set_commit_status(cid, "done", build_status="dry-run", finished=True)
            return ("done", cid, "dry-run")

        ctx = build_commit(clone, cid, repo)
        if guard is not None and ctx.image:
            guard.images_used.add(ctx.image)
        store.insert_expensive_run({"commit_id": cid, "tool": "maven", "phase": "build",
                                    "status": ctx.status, "n_findings": 0,
                                    "duration_sec": ctx.duration_sec, "error": ctx.error})
        if ctx.status == "skipped":
            # 0 module Java: KHÔNG chạy tool đắt, KHÔNG ghi 'ok' -> n_expensive_ok=0 -> cheap-clean (D1)
            store.set_commit_status(cid, "done", build_status="skipped", finished=True)
            store.update_n_expensive_ok(cid)
            return ("skipped", cid, "0 module Java")
        if ctx.status == "infra_error":
            # Docker tắt / đĩa đầy: trả commit về pending, không phải dữ liệu (D2)
            store.reset_expensive_raw(cid)
            store.set_commit_status(cid, "pending", build_status="infra_error")
            return ("infra_error", cid, (ctx.error or "")[:200])
        if ctx.status == "tool_timeout":
            store.set_commit_status(cid, "build_failed", build_status="timeout", finished=True)
            store.update_n_expensive_ok(cid)
            return ("build_failed", cid, f"build timeout {ctx.duration_sec}s")
        if not ctx.ok:
            store.set_commit_status(cid, "build_failed", build_status="failed", finished=True)
            store.update_n_expensive_ok(cid)
            return ("build_failed", cid, f"build {ctx.duration_sec}s failed")

        store.set_commit_status(cid, "analyzing", build_status="ok")

        all_findings = []
        parts = [f"build {int(ctx.duration_sec)}s"]
        statuses: dict[str, str] = {}
        flock = threading.Lock()

        def _run_tool(t):
            t0 = time.time()
            raw = []
            try:
                findings = t.scan(ctx, raw_out=raw)
                err, status = None, "ok"
            except Exception as e:  # noqa: BLE001 — 1 tool lỗi không hỏng cả commit
                findings = []
                status, err = _classify_tool_exc(e)
            if raw:  # (B) lưu output thô
                store.insert_raw_output(cid, t.name, raw[0][0], raw[0][1])
            store.insert_expensive_run({"commit_id": cid, "tool": t.name, "phase": "analyze",
                                        "status": status, "n_findings": len(findings),
                                        "duration_sec": round(time.time() - t0, 1), "error": err})
            with flock:
                all_findings.extend(findings)
                statuses[t.name] = status
                parts.append(f"{t.name} {len(findings) if status == 'ok' else status}")

        if config.EXPENSIVE_INTRA_PARALLEL and len(tools) > 1:   # Model B: 3 tool song song sau build
            with ThreadPoolExecutor(max_workers=len(tools)) as ex:
                list(ex.map(_run_tool, tools))
        else:                                          # Model A: tuần tự
            for t in tools:
                _run_tool(t)

        if "infra_error" in statuses.values():
            # hạ tầng chết giữa chừng -> KHÔNG ghi nhận kết quả bán phần, commit về pending
            store.reset_expensive_raw(cid)
            store.set_commit_status(cid, "pending", build_status="infra_error")
            store.update_n_expensive_ok(cid)
            return ("infra_error", cid, " · ".join(parts))

        # write-back: consensus (trong nhóm tool đắt) + enrich + tier=expensive -> bảng findings
        _store_expensive(store, all_findings, clone, cid, repo)
        store.set_commit_status(cid, "done", finished=True)
        store.update_n_expensive_ok(cid)
        return ("done", cid, " · ".join(parts))
    finally:
        pool.release(clone)


def _tools_json(tool_objs, images_used: set[str]) -> list[dict]:
    """[{name,image,version,digest}] cho run_meta.tools_json (image đắt + maven dùng thật)."""
    out = []
    for t in tool_objs:
        out.append({"name": t.name, "image": t.image, "version": None,
                    "digest": image_digest(t.image) if t.image else None})
    for img in sorted(images_used):
        out.append({"name": "maven", "image": img, "version": None, "digest": image_digest(img)})
    return out


def _config_snapshot(names, workers) -> dict:
    return {
        "expensive_workers": workers, "expensive_tools": list(names),
        "use_codeql": config.USE_CODEQL, "intra_parallel": config.EXPENSIVE_INTRA_PARALLEL,
        "maven_image": config.MAVEN_IMAGE, "jdk_autodetect": config.JDK_AUTODETECT,
        "maven_goals": config.MAVEN_GOALS, "build_timeout": config.BUILD_TIMEOUT,
        "codeql_suite": config.CODEQL_SUITE, "codeql_ram_mb": config.CODEQL_RAM_MB,
        "sonar_port": config.SONAR_HOST_PORT, "stale_claim_sec": config.STALE_CLAIM_SEC,
        "line_window": config.LINE_WINDOW, "gold_min_expensive": config.GOLD_MIN_EXPENSIVE,
        "gold_allow_1exp_1cheap": config.GOLD_ALLOW_1EXP_1CHEAP,
        "silver_min_cheap": config.SILVER_MIN_CHEAP, "noise_cwe": sorted(config.NOISE_CWE),
        "env": {k: v for k, v in os.environ.items() if k.startswith("ORCH_")},
    }


def analyze(repo: str, workers: int | None = None, dry_run: bool = False,
            tools: list[str] | None = None, branch: str | None = None) -> dict:
    """Chạy tầng đắt. Trả dict: counts theo outcome, status_counts, 'stopped' (bool),
    'stop_reason' ('stop_file'|'infra_error'|None), 'run_meta_id'."""
    workers = workers or config.EXPENSIVE_WORKERS
    names = tools if tools else config.EXPENSIVE_TOOLS
    if not config.USE_CODEQL:                       # công tắc riêng tắt CodeQL (nút thắt)
        names = [n for n in names if n != "codeql"]
    repo_dir = enm.clone_or_update(repo)
    store = SQLiteStore()
    run_id = progress.run_id()
    guard = _RunGuard()

    reset = store.reset_stale_claims(config.STALE_CLAIM_SEC)
    if reset:
        print(f"Reset {reset} commit treo -> pending (resume).")

    tool_objs = _make_tools(names)
    n_pending = store.count_pending()
    rm_id = store.insert_run_meta(
        "analyze", repo=keys.canon_repo(repo), branch=branch,
        scope_json={"pending": n_pending, "dry_run": dry_run},
        config_snapshot_json=_config_snapshot(names, workers),
        tools_json=_tools_json(tool_objs, set()),
        orchestrator_git_sha=orchestrator_git_sha(), app_version=app_version())
    progress.emit(phase="analyze", event="start", total=n_pending, done=0,
                  msg=f"{workers} worker · tool {[t.name for t in tool_objs]}")

    sonar = next((t for t in tool_objs if isinstance(t, SonarTool)), None)
    pool = None
    counts: dict[str, int] = {"done": 0, "skipped": 0, "build_failed": 0, "infra_error": 0, "error": 0}
    done_n = [0]
    print(f"TẦNG ĐẮT (Model A): {workers} worker | tool: {[t.name for t in tool_objs]} "
          f"| {'DRY-RUN' if dry_run else 'thật'} | pending={n_pending} | run_id={run_id}")

    def _loop(wid):
        worker = f"{run_id}:w{wid}"
        while True:
            # kiểm stop-file / cờ infra TRƯỚC khi claim -> không claim commit mới (CONTRACTS §3)
            if progress.should_stop():
                guard.trip("stop_file")
            if guard.tripped:
                return
            cid = store.claim_next_commit(worker)
            if cid is None:
                return
            msg = ""
            try:
                outcome, _, msg = _process(cid, worker, store, pool, tool_objs, repo, dry_run, guard)
            except InfraError as e:                       # đĩa đầy khi ghi DB (D6)
                outcome, msg = "infra_error", str(e)[:300]
                try:
                    store.set_commit_status(cid, "pending", build_status="infra_error")
                except Exception:  # noqa: BLE001 — DB có thể không ghi được nữa
                    pass
                guard.trip("infra_error")
            except Exception as e:  # noqa: BLE001 — 1 commit lỗi không được giết worker/cả run
                st, msg = _classify_tool_exc(e)
                if st == "infra_error":
                    outcome = "infra_error"
                    store.set_commit_status(cid, "pending", build_status="infra_error")
                else:
                    outcome = "error"
                    store.set_commit_status(cid, "error", finished=True)
                store.insert_expensive_run({"commit_id": cid, "tool": "-", "phase": "process",
                                            "status": st if st != "tool_timeout" else "tool_timeout",
                                            "n_findings": 0, "duration_sec": 0.0, "error": msg})
            counts[outcome] = counts.get(outcome, 0) + 1
            guard.record(outcome)
            with guard._lock:
                done_n[0] += 1
                dn = done_n[0]
            progress.emit(phase="analyze", event="item", done=dn, total=n_pending,
                          worker=f"w{wid}", sha=cid, status=outcome, msg=msg[:200])
            print(f"[w{wid}] {cid[:8]} -> {outcome}" + (f" ({msg[:80]})" if msg else ""))
            if guard.stop_reason == "infra_error":
                print(f"!! {guard.n_infra} infra_error liên tiếp -> dừng run (Docker/đĩa?).")
                return

    try:
        if sonar and not dry_run:
            print(f"Bật SonarQube server ({sonar.server})...")
            try:
                sonar.start_server()
            except Exception as e:  # noqa: BLE001
                st, msg = _classify_tool_exc(e)
                if st == "infra_error":
                    guard.trip("infra_error")
                    progress.emit(phase="analyze", event="error", status="infra_error",
                                  msg=f"sonar start: {msg[:200]}")
                    print(f"!! Không bật được Sonar (hạ tầng): {msg[:200]}")
                else:
                    raise
        if not guard.tripped:
            pool = RepoPool(repo_dir, workers, repo=repo)
            with ThreadPoolExecutor(max_workers=workers) as ex:
                list(ex.map(_loop, range(workers)))
    finally:
        if pool is not None:
            pool.cleanup()
        if sonar and not dry_run:
            sonar.stop_server()           # luôn dọn container của run này (TC-09)
        try:
            store.finish_run_meta(rm_id, tools_json=_tools_json(tool_objs, guard.images_used))
        except Exception:  # noqa: BLE001 — không để lỗi ghi meta che lỗi gốc
            pass

    stopped = guard.tripped
    status_counts = store.selected_status_counts()
    if stopped:
        progress.emit(phase="analyze", event="stop", status=guard.stop_reason,
                      done=done_n[0], total=n_pending,
                      msg=("stop-file" if guard.stop_reason == "stop_file"
                           else f"{guard.n_infra} infra_error liên tiếp"))
    else:
        progress.emit(phase="analyze", event="done", done=done_n[0], total=n_pending,
                      msg=" ".join(f"{k}={v}" for k, v in counts.items() if v))
    res = {"workers": workers, "tools": [t.name for t in tool_objs], "run_id": run_id,
           "run_meta_id": rm_id, "status_counts": status_counts,
           "stopped": stopped, "stop_reason": guard.stop_reason, **counts}
    store.close()
    return res
