"""Hàng đợi batch: chạy TUẦN TỰ nhiều profile qua `pipeline --profile` (CONTRACTS §11, TASKS §5 A2). Stdlib-only.

- Q.json = `["a.json", "b.json"]` hoặc `{"profiles": [...], "stop_on_error": false}`.
- Mỗi profile = 1 tiến trình con `python -m orchestrator.cli pipeline --profile <p>` (cùng python), có
  `ORCH_RUN_ID=<batch_id>-<i>`; tuần tự nên chỉ 1 SonarQube server tại một thời điểm.
- `batch_state.json` (cạnh Q.json) ghi trạng thái từng mục: pending|running|done|failed|stopped|skipped.
- Stop-file batch (`<Q>.stop` cạnh Q.json, hoặc --stop-file): tồn tại -> không khởi động profile kế, kết thúc
  hàng đợi với exit 3. Run con trả 3 (stop-file của run) cũng dừng cả hàng đợi.
Exit: 0 mọi mục done · 2 có mục failed · 3 dừng theo stop-file.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from . import config

EXIT_OK, EXIT_RUNTIME, EXIT_STOP = 0, 2, 3


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def load_queue(path: str | Path) -> dict:
    """-> {"profiles": [abs paths], "stop_on_error": bool}. Đường dẫn tương đối tính từ thư mục Q.json."""
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, list):
        data = {"profiles": data}
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), list) or not data["profiles"]:
        raise ValueError(f"{p}: cần danh sách profile (list hoặc {{'profiles': [...]}}) không rỗng")
    profiles = []
    for item in data["profiles"]:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{p}: mục profile không phải chuỗi: {item!r}")
        q = Path(item)
        if not q.is_absolute():
            q = (p.parent / q).resolve()
        if not q.exists():
            raise FileNotFoundError(f"profile không tồn tại: {q}")
        profiles.append(str(q))
    return {"profiles": profiles, "stop_on_error": bool(data.get("stop_on_error", False))}


def default_state_path(queue_path: Path) -> Path:
    return queue_path.with_name("batch_state.json")


def default_stop_file(queue_path: Path) -> Path:
    return queue_path.with_name(queue_path.name + ".stop")


def _write_state(path: Path, state: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _default_runner(argv: list[str], env: dict, log_path: Path) -> int:
    with open(log_path, "a", encoding="utf-8") as logf:
        logf.write(f"\n===== batch start {_now()} =====\nargv: {json.dumps(argv, ensure_ascii=False)}\n")
        logf.flush()
        proc = subprocess.run(argv, stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                              env=env, cwd=str(config.ROOT))
    return int(proc.returncode)


def run(queue_path: str | Path, state_path: str | Path | None = None, stop_file: str | Path | None = None,
        python_exe: str | None = None, runner=None, batch_id: str | None = None) -> dict:
    """Chạy hàng đợi. runner(argv, env, log_path) -> rc (tiêm được để test, mặc định subprocess)."""
    qp = Path(queue_path)
    q = load_queue(qp)
    state_path = Path(state_path) if state_path else default_state_path(qp)
    stop_file = Path(stop_file) if stop_file else default_stop_file(qp)
    runner = runner or _default_runner
    batch_id = batch_id or f"batch-{time.strftime('%Y%m%d-%H%M%S')}"
    py = python_exe or sys.executable

    items = [{"i": i, "profile": p, "run_id": f"{batch_id}-{i}", "status": "pending", "rc": None,
              "started": None, "finished": None, "log": str(qp.with_name(f"{batch_id}-{i}.log"))}
             for i, p in enumerate(q["profiles"])]
    state = {"batch_id": batch_id, "queue": str(qp), "stop_file": str(stop_file), "started": _now(),
             "finished": None, "status": "running", "items": items}
    _write_state(state_path, state)

    outcome = EXIT_OK
    stopped = False
    for it in items:
        if stop_file.exists():
            stopped = True
            it["status"] = "stopped"
            continue
        if stopped:
            it["status"] = "skipped"
            continue
        it["status"], it["started"] = "running", _now()
        _write_state(state_path, state)
        env = dict(os.environ)
        env.update({"ORCH_RUN_ID": it["run_id"], "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
        src = str(config.ROOT / "src")
        env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        argv = [py, "-m", "orchestrator.cli", "pipeline", "--profile", it["profile"]]
        try:
            rc = runner(argv, env, Path(it["log"]))
        except (OSError, subprocess.SubprocessError) as e:
            rc = 2
            it["error"] = str(e)[:300]
        it["rc"], it["finished"] = rc, _now()
        if rc == EXIT_STOP:
            it["status"] = "stopped"
            stopped = True
        elif rc == 0:
            it["status"] = "done"
        else:
            it["status"] = "failed"
            outcome = EXIT_RUNTIME
            if q["stop_on_error"]:
                stopped = True
        _write_state(state_path, state)

    state["finished"] = _now()
    if stopped:
        state["status"] = "stopped"
        outcome = EXIT_STOP
    else:
        state["status"] = "done" if outcome == EXIT_OK else "failed"
    state["exit_code"] = outcome
    state["counts"] = {k: sum(1 for i in items if i["status"] == k)
                       for k in ("done", "failed", "stopped", "skipped", "pending")}
    _write_state(state_path, state)
    state["state_path"] = str(state_path)
    return state


def format_text(state: dict) -> str:
    lines = [f"batch {state['batch_id']}: {state['status']} (exit {state.get('exit_code')}) | {state['counts']}"]
    for it in state["items"]:
        lines.append(f"  [{it['status']:7}] rc={it['rc']} {Path(it['profile']).name}  run_id={it['run_id']}")
    lines.append(f"state: {state.get('state_path')} | stop-file: {state['stop_file']}")
    return "\n".join(lines)
