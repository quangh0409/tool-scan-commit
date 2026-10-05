"""Helper dùng chung cho gui/api_*.py: tìm run trong registry, mở DB chỉ-đọc, áp env profile, gọi CLI.

Quy ước: mọi hàm API có chữ ký `fn(params: dict, body: dict | None) -> dict`; lỗi → `gui.errors.ApiError`.
`params` gộp path-param (`id`, `cluster_key`, `name`, `tab`) + query-string; `body` là JSON POST (hoặc None).
Import orchestrator LƯỜI (trong hàm) để test có thể đặt env ORCH_* trước khi config nạp.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .errors import ApiError, bad_request, conflict, not_found

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
_env_lock = threading.RLock()


def ensure_src_on_path() -> None:
    for p in (SRC, ROOT):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def home() -> Path:
    ensure_src_on_path()
    import registry
    return registry.home()


def to_int(v, default: int | None = None, lo: int | None = None, hi: int | None = None, name: str = "") -> int | None:
    if v is None or v == "":
        return default
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise bad_request(f"{name or 'tham số'} phải là số nguyên, nhận {v!r}") from None
    if lo is not None and n < lo:
        raise bad_request(f"{name or 'tham số'} phải >= {lo}")
    if hi is not None and n > hi:
        raise bad_request(f"{name or 'tham số'} phải <= {hi}")
    return n


def to_bool(v, default: bool = False) -> bool:
    if v is None or v == "":
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


# ----------------------------------------------------------------------------- run / registry
def require_run_id(params: dict) -> str:
    rid = str((params or {}).get("id") or (params or {}).get("run_id") or "").strip()
    if not rid or not RUN_ID_RE.match(rid):
        raise bad_request(f"run_id không hợp lệ: {rid!r}")
    return rid


def find_run(run_id: str) -> dict:
    """Bản ghi registry của run (404 nếu không có)."""
    ensure_src_on_path()
    import registry
    r = registry.get(run_id)
    if not r:
        raise not_found(f"run {run_id!r} trong runs.json", "Run chưa đăng ký hoặc đã bị xoá khỏi registry")
    return r


def run_db(run: dict) -> Path:
    db = run.get("db")
    if not db:
        raise not_found(f"DB của run {run.get('run_id')!r}", "registry không ghi đường dẫn db")
    p = Path(db)
    if not p.is_absolute():
        p = ROOT / p
    if not p.exists():
        raise not_found(f"DB {p}", "File SQLite đã bị xoá/di chuyển — sửa đường dẫn trong runs.json")
    return p


def run_work(run: dict) -> Path:
    w = run.get("work")
    if w:
        return Path(w)
    prof = load_run_profile(run)
    pw = ((prof or {}).get("paths") or {}).get("work")
    return Path(pw) if pw else home() / "work"


def load_run_profile(run: dict) -> dict | None:
    """profile.json của run (None nếu không có/hỏng — không raise)."""
    p = run.get("profile")
    if not p:
        return None
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def line_window_of(run: dict | None, conn: sqlite3.Connection | None = None) -> int:
    """W hiệu lực: profile.params_v1.line_window → run_meta.config_snapshot → 3."""
    prof = load_run_profile(run) if run else None
    try:
        w = int(((prof or {}).get("params_v1") or {}).get("line_window") or 0)
        if w > 0:
            return w
    except (TypeError, ValueError):
        pass
    if conn is not None and "run_meta" in tables(conn):
        cols = columns(conn, "run_meta")
        try:
            if "config_snapshot_json" in cols:
                for (snap,) in conn.execute("SELECT config_snapshot_json FROM run_meta ORDER BY id DESC"):
                    try:
                        d = json.loads(snap or "{}")
                    except ValueError:
                        continue
                    for k in ("ORCH_LINE_WINDOW", "line_window"):
                        if d.get(k):
                            return int(d[k])
            elif "line_window" in cols:
                r = conn.execute("SELECT line_window FROM run_meta ORDER BY id DESC LIMIT 1").fetchone()
                if r and r[0]:
                    return int(r[0])
        except (sqlite3.Error, TypeError, ValueError):
            pass
    return 3


# ----------------------------------------------------------------------------- DB chỉ-đọc
def open_ro(db: str | Path) -> sqlite3.Connection:
    """Kết nối `file:…?mode=ro` (không lock, không migrate). 404 nếu thiếu file, 503 nếu không mở được."""
    p = Path(db)
    if not p.exists():
        raise not_found(f"DB {p}")
    try:
        conn = sqlite3.connect(p.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("SELECT name FROM sqlite_master LIMIT 1")
        return conn
    except sqlite3.Error as e:
        raise ApiError(503, "EDB", f"Không mở được DB {p}: {e}", "DB đang bị ghi hoặc file hỏng") from e


@contextmanager
def ro_conn(db: str | Path):
    conn = open_ro(db)
    try:
        yield conn
    finally:
        conn.close()


def tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def jload(s, default=None):
    if s is None:
        return default
    if not isinstance(s, str):
        return s
    try:
        return json.loads(s)
    except ValueError:
        return default


def db_lock_holder(db: str | Path) -> dict | None:
    """Thông tin `<db>.lock` nếu pid còn sống (run đang ghi DB), ngược lại None."""
    ensure_src_on_path()
    from registry import locks
    held, info = locks.lock_status(db)
    return info if held else None


def require_db_free(db: str | Path) -> None:
    info = db_lock_holder(db)
    if info:
        raise conflict(f"Run {info.get('run_id')!r} (pid {info.get('pid')}) đang ghi DB này",
                       "Dừng run trước (Dừng an toàn) rồi thử lại")


def open_rw(db: str | Path):
    """SQLiteStore ghi (migrate + WAL + lock). 409 nếu run khác đang giữ lock."""
    ensure_src_on_path()
    require_db_free(db)
    from orchestrator.storage.sqlite_store import SQLiteStore
    try:
        return SQLiteStore(Path(db))
    except RuntimeError as e:
        raise conflict(str(e)) from e


# ----------------------------------------------------------------------------- env profile
@contextmanager
def profile_env(prof: dict | None, extra: dict | None = None):
    """Áp `profile.to_env()` (+extra) vào os.environ + config.reload() trong khối; khôi phục sau.

    Dùng cho thao tác in-process cần params_v1/đường dẫn đúng của run (export, relabel…).
    """
    ensure_src_on_path()
    from orchestrator import config
    from orchestrator import profile as _profile
    env: dict[str, str] = {}
    if prof:
        try:
            env.update(_profile.to_env(prof))
        except (KeyError, TypeError):
            pass
    env.update({str(k): str(v) for k, v in (extra or {}).items()})
    with _env_lock:
        saved = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        config.reload()
        try:
            yield
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            config.reload()


# ----------------------------------------------------------------------------- CLI con
def cli_env(prof: dict | None = None, run_id: str | None = None, run_dir: Path | None = None) -> dict:
    ensure_src_on_path()
    env = dict(os.environ)
    if prof:
        from orchestrator import profile as _profile
        try:
            env.update(_profile.to_env(prof))
        except (KeyError, TypeError):
            pass
    env["PYTHONPATH"] = str(SRC) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
    if run_id:
        env["ORCH_RUN_ID"] = str(run_id)
    if run_dir:
        env["ORCH_PROGRESS_FILE"] = str(Path(run_dir) / "progress.jsonl")
        env["ORCH_STOP_FILE"] = str(Path(run_dir) / "stop")
    return env


def run_cli(args: list[str], env: dict | None = None, timeout: float = 600, ok_codes: tuple = (0,)) -> dict:
    """`python -m orchestrator.cli <args> --json` đồng bộ → JSON stdout. Lệnh chưa có → 501."""
    argv = [sys.executable, "-m", "orchestrator.cli", *args]
    if "--json" not in argv:
        argv.append("--json")
    try:
        r = subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=timeout,
                           env=env or cli_env(), cwd=str(ROOT))
    except subprocess.TimeoutExpired as e:
        raise ApiError(504, "ETIMEOUT", f"Lệnh {' '.join(args[:2])} quá {timeout}s") from e
    except OSError as e:
        raise ApiError(500, "ESPAWN", f"Không chạy được python: {e}") from e
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    if r.returncode != 0 and ("invalid choice" in err or "unrecognized arguments" in err):
        raise ApiError(501, "ENOTSUP", f"orchestrator.cli chưa có lệnh {args[0]!r}", err[-300:])
    if r.returncode != 0 and r.returncode not in ok_codes:
        raise ApiError(500 if r.returncode == 2 else 400, "ECLI", f"{args[0]} exit {r.returncode}", (err or out)[-500:])
    last = out.splitlines()[-1] if out else ""
    try:
        d = json.loads(last)
    except ValueError:
        return {"stdout": out[-2000:], "stderr": err[-500:], "rc": r.returncode}
    if isinstance(d, dict):
        d.setdefault("rc", r.returncode)
    return d


def spawn_cli(args: list[str], log_path: Path, env: dict | None = None) -> int:
    """Chạy nền tách rời (features/relabel dài). Trả pid; stdout/err → log_path."""
    argv = [sys.executable, "-m", "orchestrator.cli", *args]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    kw: dict = {"stdin": subprocess.DEVNULL, "close_fds": True, "cwd": str(ROOT), "env": env or cli_env()}
    if os.name == "nt":
        # CREATE_NO_WINDOW (không DETACHED_PROCESS): tránh mỗi lệnh docker/git con bật 1 cửa sổ cmd
        kw["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200) | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    else:
        kw["start_new_session"] = True
    with open(log_path, "a", encoding="utf-8") as logf:
        logf.write(f"\n===== {now_iso()} {' '.join(argv)}\n")
        logf.flush()
        try:
            proc = subprocess.Popen(argv, stdout=logf, stderr=subprocess.STDOUT, **kw)
        except OSError as e:
            raise ApiError(500, "ESPAWN", f"Không chạy được: {e}") from e
    return int(proc.pid)


def safe_name(name: str, what: str = "tên") -> str:
    n = str(name or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.\- ]{1,64}", n) or n in (".", ".."):
        raise bad_request(f"{what} không hợp lệ: {name!r}", "Chỉ chữ, số, _ . - và khoảng trắng; ≤64 ký tự")
    return n
