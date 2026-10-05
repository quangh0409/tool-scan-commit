"""Khoá: `<db>.lock` theo DB (chống 2 run cùng ghi 1 SQLite) + single-instance GUI.

- db_lock: file JSON {pid, run_id, host, at}. pid chết → stale → ghi đè. pid sống (≠ mình) → DbLocked.
  Có 2 dạng: context manager `db_lock(...)` (giữ trong khối) và `acquire_db_lock`/`release_db_lock`
  (GUI giữ khoá suốt đời run nền — pid ghi vào lock là pid tiến trình orchestrator con).
- single_instance: Windows mutex CreateMutexW (ERROR_ALREADY_EXISTS=183); Linux fcntl.flock lock-file.
"""
from __future__ import annotations

import json
import os
import socket
import time
from contextlib import contextmanager
from pathlib import Path

from . import store as _store

ERROR_ALREADY_EXISTS = 183


class DbLocked(RuntimeError):
    def __init__(self, info: dict, lock_path: Path):
        self.info = info
        self.lock_path = lock_path
        super().__init__(f"DB đang bị run {info.get('run_id')!r} (pid {info.get('pid')}) giữ: {lock_path}")


def lock_path(db_path: str | Path) -> Path:
    return Path(str(db_path) + ".lock")


def read_lock(db_path: str | Path) -> dict | None:
    try:
        with open(lock_path(db_path), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {"raw": d}
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {"corrupt": True}


def _pid_alive(pid) -> bool:
    from runner import process as _rp  # noqa: PLC0415
    return _rp.alive(pid)


def lock_status(db_path: str | Path) -> tuple[bool, dict | None]:
    """(đang bị giữ bởi pid sống?, info). Khoá stale/hỏng → (False, info)."""
    info = read_lock(db_path)
    if not info:
        return False, None
    return _pid_alive(info.get("pid")), info


def acquire_db_lock(db_path: str | Path, run_id: str, pid: int | None = None, force: bool = False) -> Path:
    """Tạo `<db>.lock`. Stale → ghi đè. Đang giữ bởi pid sống khác → DbLocked (trừ force)."""
    lp = lock_path(db_path)
    held, info = lock_status(db_path)
    me = int(pid or os.getpid())
    if held and not force and info and int(info.get("pid") or -1) != me:
        raise DbLocked(info, lp)
    lp.parent.mkdir(parents=True, exist_ok=True)
    data = {"pid": me, "run_id": str(run_id), "host": socket.gethostname(),
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "owner_pid": os.getpid()}
    _store.atomic_write_json(lp, data)
    return lp


def release_db_lock(db_path: str | Path, run_id: str | None = None) -> bool:
    """Xoá lock nếu là của run_id (None = xoá bất kể). Trả True nếu đã xoá."""
    lp = lock_path(db_path)
    info = read_lock(db_path)
    if info is None:
        return False
    if run_id is not None and info.get("run_id") not in (None, str(run_id)) and not info.get("corrupt"):
        return False
    try:
        lp.unlink()
        return True
    except OSError:
        return False


@contextmanager
def db_lock(db_path: str | Path, run_id: str, pid: int | None = None, force: bool = False):
    lp = acquire_db_lock(db_path, run_id, pid, force)
    try:
        yield lp
    finally:
        release_db_lock(db_path, run_id)


# ---------------------------------------------------------------- single instance

class InstanceLock:
    """Kết quả single_instance(): .acquired, .release(); dùng được làm context manager."""

    def __init__(self, name: str):
        self.name = name
        self.acquired = False
        self._handle = None
        self._fh = None
        self.path: Path | None = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()

    def release(self) -> None:
        if os.name == "nt":
            if self._handle:
                try:
                    import ctypes  # noqa: PLC0415
                    ctypes.windll.kernel32.CloseHandle(self._handle)  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    pass
                self._handle = None
        else:
            if self._fh:
                try:
                    import fcntl  # noqa: PLC0415
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
                except Exception:  # noqa: BLE001
                    pass
                try:
                    self._fh.close()
                except OSError:
                    pass
                self._fh = None
        self.acquired = False


def single_instance(name: str = "secjit-gui") -> InstanceLock:
    """Thử lấy khoá "một cửa sổ app". `.acquired=False` → đã có instance khác đang chạy."""
    lk = InstanceLock(name)
    if os.name == "nt":
        try:
            import ctypes  # noqa: PLC0415
            k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            k32.SetLastError(0)
            h = k32.CreateMutexW(None, False, f"Local\\{name}")
            err = k32.GetLastError()
            lk._handle = h or None
            lk.acquired = bool(h) and err != ERROR_ALREADY_EXISTS
            if not lk.acquired and h:
                k32.CloseHandle(h)
                lk._handle = None
        except Exception:  # noqa: BLE001 — không có ctypes/windll → coi như lấy được
            lk.acquired = True
        return lk
    try:
        import fcntl  # noqa: PLC0415
        lk.path = _store.home() / f"{name}.lock"
        lk.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(lk.path, "a+", encoding="utf-8")  # noqa: SIM115 — giữ mở suốt đời khoá
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fh.seek(0)
            fh.truncate()
            fh.write(str(os.getpid()))
            fh.flush()
            lk._fh = fh
            lk.acquired = True
        except OSError:
            fh.close()
            lk.acquired = False
    except Exception:  # noqa: BLE001
        lk.acquired = True
    return lk
