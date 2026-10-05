"""Tiến độ có cấu trúc (JSON lines) cho GUI/Dashboard + kiểm stop-file hợp tác.

Hợp đồng: CONTRACTS.md §progress.jsonl. Stdlib-only, thread-safe, no-op nếu không bật.

Env:
  ORCH_PROGRESS_FILE  đường dẫn progress.jsonl (không set -> emit() không làm gì)
  ORCH_RUN_ID         run_id gắn vào mọi dòng (mặc định "local")
  ORCH_STOP_FILE      đường dẫn stop-file; tồn tại -> should_stop() True

Dùng:
  from . import progress
  progress.emit(phase="scan", event="start", total=187)
  progress.emit(phase="scan", event="item", done=12, total=187, sha=cid, status="ok")
  if progress.should_stop(): ...  # kiểm GIỮA mỗi commit, không kiểm giữa tool
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

PHASES = ("scan", "select", "analyze", "relabel", "kappa", "export", "review", "stats")
EVENTS = ("start", "item", "done", "error", "stop")

_lock = threading.Lock()


def run_id() -> str:
    return os.environ.get("ORCH_RUN_ID", "local")


def enabled() -> bool:
    return bool(os.environ.get("ORCH_PROGRESS_FILE"))


def emit(phase: str, event: str, *, done: int | None = None, total: int | None = None,
         worker: str | None = None, sha: str | None = None, status: str | None = None,
         msg: str | None = None, **extra) -> None:
    """Ghi 1 dòng JSON. Không bao giờ raise (lỗi ghi tiến độ không được làm hỏng run)."""
    path = os.environ.get("ORCH_PROGRESS_FILE")
    if not path:
        return
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "run_id": run_id(),
           "phase": phase, "event": event}
    for k, v in (("done", done), ("total", total), ("worker", worker),
                 ("sha", sha), ("status", status), ("msg", msg)):
        if v is not None:
            rec[k] = v
    rec.update(extra)
    line = json.dumps(rec, ensure_ascii=False)
    try:
        with _lock:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except OSError:
        pass


def should_stop() -> bool:
    """True nếu stop-file tồn tại. Gọi giữa mỗi commit (tầng rẻ + tầng đắt)."""
    p = os.environ.get("ORCH_STOP_FILE")
    return bool(p) and Path(p).exists()


def read(path: str | Path, since_line: int = 0) -> list[dict]:
    """Đọc progress.jsonl từ dòng since_line (GUI poll/SSE). Bỏ dòng hỏng."""
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i < since_line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return out
