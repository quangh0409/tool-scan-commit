"""registry — sổ đăng ký run (`runs.json`), khoá DB / single-instance, tốc độ đo (`speed.json`).

Hợp đồng: CONTRACTS.md §7. Vị trí dữ liệu: `registry.home()` (= %LOCALAPPDATA%\\secjit hoặc
~/.local/share/secjit; override env SECJIT_HOME).

API public (A4 gọi):
  path() -> Path                      runs.json
  load() -> {"runs": [...]}
  get(run_id) -> dict | None
  upsert(run: dict) -> dict           (bắt buộc run_id; status ∈ STATUSES)
  set_status(run_id, status, **fields) -> dict
  remove(run_id) -> bool
  refresh_status() -> list[dict]      run `running` có pid chết → done/stopped/failed/interrupted
  locks.acquire_db_lock(db, run_id, pid) / release_db_lock(db, run_id) / db_lock(...) ctx / lock_status(db)
  locks.single_instance("secjit-gui") -> InstanceLock(.acquired, .release())
  speed.load() / speed.update_from_db(db) / speed.update_from_progress(path) / speed.estimate(...)
"""
from __future__ import annotations

from . import locks, speed  # noqa: F401
from .store import (  # noqa: F401
    STATUSES,
    atomic_write_json,
    get,
    home,
    load,
    path,
    refresh_status,
    remove,
    save,
    set_status,
    upsert,
)

__all__ = ["STATUSES", "atomic_write_json", "get", "home", "load", "path", "refresh_status",
           "remove", "save", "set_status", "upsert", "locks", "speed"]
