"""Hàng đợi batch CÓ registry: mỗi profile → runner.start (tiến trình tách rời) + registry.upsert, chờ pid, cập nhật
status; tuần tự (1 SonarQube tại một thời điểm). Khác `orchestrator.batch` (A2, subprocess.run blocking, không registry).

  run_queue(queue_path, work_dir, python_exe=None, batch_id=None, stop_file=None, state_path=None,
            poll_s=1.0, on_event=None) -> state (cùng dạng batch_state.json của A2 + "registry": True)

- Q.json như A2 (`["a.json", ...]` hoặc `{"profiles": [...], "stop_on_error": false}`), tái dùng batch.load_queue.
- Stop-file batch (`<Q>.stop` cạnh Q.json hoặc tham số): tồn tại → không khởi động profile kế; nếu đang chạy một
  run thì tạo stop-file của run đó (dừng mềm) rồi chờ nó kết thúc; kết quả `stopped`, exit 3.
- Mỗi item: run_id `<batch_id>-<i>`, status pending|running|done|failed|stopped|skipped|interrupted, rc suy ra từ
  trạng thái progress (done→0, stopped→3, failed/interrupted→2).
- CLI: `python -m runner.batch_runner Q.json --work-dir D [--batch-id ID] [--json]` (GUI có thể spawn tách rời).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import process as _rp
from . import stopper as _stopper

EXIT_OK, EXIT_RUNTIME, EXIT_STOP = 0, 2, 3
RC_OF = {"done": 0, "stopped": 3, "failed": 2, "interrupted": 2}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _batch_mod():
    _rp._ensure_src_on_path()
    from orchestrator import batch  # noqa: PLC0415
    return batch


def _emit(cb, **ev) -> None:
    if cb:
        try:
            cb(ev)
        except Exception:  # noqa: BLE001
            pass


def _registry():
    import registry  # noqa: PLC0415
    return registry


def _wait(pid: int, run_id: str, work_dir: Path, batch_stop: Path, poll_s: float, on_event) -> bool:
    """Chờ pid chết. Thấy stop-file batch giữa chừng → dừng mềm run (1 lần). Trả True nếu đã yêu cầu dừng."""
    asked = False
    while _rp.alive(pid):
        if not asked and batch_stop.exists():
            _stopper.stop(run_id, work_dir, cleanup=False)
            asked = True
            _emit(on_event, event="stop_requested", run_id=run_id)
        time.sleep(poll_s)
    return asked


def run_queue(queue_path: str | Path, work_dir: str | Path, python_exe: str | None = None,
              batch_id: str | None = None, stop_file: str | Path | None = None, state_path: str | Path | None = None,
              poll_s: float = 1.0, on_event=None) -> dict:
    batch = _batch_mod()
    reg = _registry()
    qp = Path(queue_path)
    q = batch.load_queue(qp)
    work_dir = Path(work_dir)
    state_path = Path(state_path) if state_path else batch.default_state_path(qp)
    batch_stop = Path(stop_file) if stop_file else batch.default_stop_file(qp)
    batch_id = batch_id or f"batch-{time.strftime('%Y%m%d-%H%M%S')}"

    items = [{"i": i, "profile": p, "run_id": f"{batch_id}-{i}", "status": "pending", "rc": None, "pid": None,
              "started": None, "finished": None, "log": str(_rp.run_dir(work_dir, f"{batch_id}-{i}") / "run.log")}
             for i, p in enumerate(q["profiles"])]
    state = {"batch_id": batch_id, "queue": str(qp), "stop_file": str(batch_stop), "work": str(work_dir),
             "started": _now(), "finished": None, "status": "running", "registry": True, "items": items}
    batch._write_state(state_path, state)

    outcome, stopped = EXIT_OK, False
    for it in items:
        if stopped or batch_stop.exists():
            it["status"] = "skipped" if stopped else "stopped"
            stopped = True
            continue
        it["status"], it["started"] = "running", _now()
        batch._write_state(state_path, state)
        rid = it["run_id"]
        try:
            prof = _load_profile(it["profile"])
            reg.locks.acquire_db_lock(prof["paths"]["db"], rid, pid=os.getpid())
            res = _rp.start(it["profile"], rid, work_dir, python_exe=python_exe,
                            extra_env={"ORCH_BATCH_ID": batch_id})
        except Exception as e:  # noqa: BLE001 — profile hỏng / DB bị khoá / không spawn được
            it.update(status="failed", rc=EXIT_RUNTIME, finished=_now(), error=f"{type(e).__name__}: {e}"[:300])
            outcome = EXIT_RUNTIME
            _emit(on_event, event="failed", run_id=rid, error=it["error"])
            if q["stop_on_error"]:
                stopped = True
            batch._write_state(state_path, state)
            continue
        it["pid"] = res["pid"]
        reg.locks.acquire_db_lock(prof["paths"]["db"], rid, pid=res["pid"], force=True)
        reg.upsert({"run_id": rid, "repo": prof.get("repo"), "branch": prof.get("branch"),
                    "db": prof["paths"]["db"], "export": prof["paths"].get("export"), "work": str(work_dir),
                    "profile": it["profile"], "pid": res["pid"], "status": "running",
                    "summary": {"batch_id": batch_id, "batch_index": it["i"]}})
        _emit(on_event, event="started", run_id=rid, pid=res["pid"], i=it["i"], n=len(items))
        batch._write_state(state_path, state)

        asked = _wait(res["pid"], rid, work_dir, batch_stop, poll_s, on_event)
        last = _rp.last_progress(_rp.run_dir(work_dir, rid))
        st = _rp.derive_status(last, False)      # pid đã chết: done|stopped|failed|interrupted
        it["status"], it["rc"], it["finished"] = st, RC_OF.get(st, EXIT_RUNTIME), _now()
        reg.set_status(rid, st if st in reg.STATUSES else "interrupted", summary={"last_progress": last})
        reg.locks.release_db_lock(prof["paths"]["db"], rid)
        _emit(on_event, event="finished", run_id=rid, status=st)
        if st == "stopped" or asked:
            stopped = True
        elif st != "done":
            outcome = EXIT_RUNTIME
            if q["stop_on_error"]:
                stopped = True
        batch._write_state(state_path, state)

    state["finished"] = _now()
    if stopped:
        state["status"], outcome = "stopped", EXIT_STOP
    else:
        state["status"] = "done" if outcome == EXIT_OK else "failed"
    state["exit_code"] = outcome
    state["counts"] = {k: sum(1 for i in items if i["status"] == k)
                       for k in ("done", "failed", "stopped", "skipped", "pending", "interrupted")}
    batch._write_state(state_path, state)
    state["state_path"] = str(state_path)
    return state


def _load_profile(path: str) -> dict:
    _rp._ensure_src_on_path()
    from orchestrator import profile  # noqa: PLC0415
    return profile.load(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m runner.batch_runner", description="Batch tuần tự có registry")
    ap.add_argument("queue")
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--batch-id", default=None)
    ap.add_argument("--stop-file", default=None)
    ap.add_argument("--state", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass

    def cb(ev):
        if not a.json:
            print(json.dumps(ev, ensure_ascii=False), flush=True)
    state = run_queue(a.queue, a.work_dir, batch_id=a.batch_id, stop_file=a.stop_file, state_path=a.state, on_event=cb)
    if a.json:
        print(json.dumps(state, ensure_ascii=False))
    else:
        print(_batch_mod().format_text(state))
    return int(state["exit_code"])


if __name__ == "__main__":
    sys.exit(main())
