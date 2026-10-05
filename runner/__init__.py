"""runner — khởi chạy / theo dõi / dừng tiến trình orchestrator tách rời khỏi GUI.

Hợp đồng: CONTRACTS.md §7 (runner) + §3 (env progress/stop-file).

API public (A4 gọi):
  start(profile_path, run_id, work_dir, python_exe=sys.executable, extra_env=None) -> dict
      {"pid", "log", "progress", "stop", "run_dir", "meta", "argv"}
  alive(pid) -> bool
  attach(run_id, work_dir) -> dict
      {"run_id", "pid", "alive", "last_progress_line", "interrupted", "status", "meta", "log"}
  stop(run_id, work_dir, force=False, timeout_s=10.0) -> dict
      {"ok", "stop_file", "pid", "alive_before", "killed", "alive_after", "cleanup"}
  run_dir(work_dir, run_id) -> Path

Mọi hàm không chạm Docker trực tiếp; stop-cleanup uỷ cho `orchestrator.cli stop-cleanup` (A2).
"""
from __future__ import annotations

from .process import (  # noqa: F401
    REPO_ROOT,
    alive,
    attach,
    build_env,
    derive_status,
    read_pid,
    run_dir,
    src_dir,
    start,
)
from .stopper import stop  # noqa: F401

__all__ = ["start", "alive", "attach", "stop", "run_dir", "read_pid", "derive_status",
           "build_env", "REPO_ROOT", "src_dir"]
