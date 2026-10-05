"""runs.json — sổ đăng ký run (CONTRACTS §7). Ghi atomic (tmp + os.replace), utf-8.

Vị trí: %LOCALAPPDATA%\\secjit\\runs.json (Windows) · $XDG_DATA_HOME/secjit (Linux, mặc định
~/.local/share/secjit). Override bằng env SECJIT_HOME (test / portable).

Bản ghi run:
  {"run_id","repo","branch","db","export","work","profile","started","finished",
   "status": "running|stopped|done|failed|interrupted", "pid", "summary": {...}}
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

STATUSES = ("running", "stopped", "done", "failed", "interrupted")
_lock = threading.Lock()


def home() -> Path:
    env = os.environ.get("SECJIT_HOME")
    if env:
        return Path(env)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "secjit"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "secjit"


def path() -> Path:
    return home() / "runs.json"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def load() -> dict:
    """Đọc runs.json; thiếu/hỏng → {"runs": []} (file hỏng được giữ lại dưới tên .corrupt)."""
    p = path()
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("runs"), list):
            raise ValueError("cấu trúc sai")
        return data
    except FileNotFoundError:
        return {"runs": []}
    except (OSError, ValueError):
        try:
            os.replace(p, p.with_suffix(".json.corrupt"))
        except OSError:
            pass
        return {"runs": []}


def atomic_write_json(p: Path, data: dict) -> None:
    """Ghi JSON atomic: file tạm cùng thư mục rồi os.replace. Thử lại vài lần (Windows: file đang mở)."""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.tmp.{os.getpid()}.{threading.get_ident()}")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    last: Exception | None = None
    for _ in range(10):
        try:
            os.replace(tmp, p)
            return
        except PermissionError as e:  # Windows: tiến trình khác đang đọc
            last = e
            time.sleep(0.05)
    try:
        tmp.unlink()
    except OSError:
        pass
    if last:
        raise last


def save(data: dict) -> None:
    data.setdefault("runs", [])
    data["updated"] = _now()
    atomic_write_json(path(), data)


def get(run_id: str) -> dict | None:
    for r in load()["runs"]:
        if r.get("run_id") == run_id:
            return r
    return None


def upsert(run: dict) -> dict:
    """Thêm/cập nhật theo run_id (gộp field, giữ field cũ không nêu). Trả bản ghi sau khi ghi."""
    rid = run.get("run_id")
    if not rid:
        raise ValueError("run_id trống")
    with _lock:
        data = load()
        cur = None
        for r in data["runs"]:
            if r.get("run_id") == rid:
                cur = r
                break
        if cur is None:
            cur = {"run_id": rid, "status": "running", "started": _now(), "summary": {}}
            data["runs"].append(cur)
        for k, v in run.items():
            if k == "summary" and isinstance(v, dict) and isinstance(cur.get("summary"), dict):
                cur["summary"].update(v)
            else:
                cur[k] = v
        if cur.get("status") not in STATUSES:
            raise ValueError(f"status không hợp lệ: {cur.get('status')!r} (∈ {STATUSES})")
        save(data)
        return dict(cur)


def set_status(run_id: str, status: str, **fields) -> dict:
    if status not in STATUSES:
        raise ValueError(f"status không hợp lệ: {status!r}")
    rec = {"run_id": run_id, "status": status}
    if status != "running" and "finished" not in fields:
        rec["finished"] = _now()
    rec.update(fields)
    return upsert(rec)


def remove(run_id: str) -> bool:
    with _lock:
        data = load()
        n = len(data["runs"])
        data["runs"] = [r for r in data["runs"] if r.get("run_id") != run_id]
        if len(data["runs"]) != n:
            save(data)
            return True
        return False


def _stale_claims(db: str | None) -> int | None:
    """Số commit còn `building|analyzing` trong DB (đọc read-only). None nếu không đọc được."""
    if not db or not Path(db).exists():
        return None
    import sqlite3  # noqa: PLC0415
    try:
        uri = Path(db).resolve().as_uri() + "?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=2)
        try:
            row = con.execute("SELECT COUNT(*) FROM selected_commits "
                              "WHERE status IN ('building','analyzing')").fetchone()
            return int(row[0]) if row else 0
        finally:
            con.close()
    except sqlite3.Error:
        return None


def refresh_status() -> list[dict]:
    """Duyệt run `running`: pid chết → done/stopped/failed theo progress cuối, hoặc `interrupted`.

    Trả danh sách run đã đổi trạng thái. Luôn cập nhật summary.last_progress cho run còn sống.
    """
    from runner import process as _rp  # noqa: PLC0415 — tránh import vòng khi runner nạp registry

    changed: list[dict] = []
    with _lock:
        data = load()
        dirty = False
        for r in data["runs"]:
            if r.get("status") != "running":
                continue
            work = r.get("work")
            rid = r.get("run_id")
            if not work or not rid:
                continue
            rdir = _rp.run_dir(work, rid)
            pid = r.get("pid") or _rp.read_pid(rdir)
            is_alive = _rp.alive(pid)
            last = _rp.last_progress(rdir)
            summ = r.setdefault("summary", {})
            if last:
                summ["last_progress"] = last
            if is_alive:
                r["pid"] = pid
                dirty = True
                continue
            new_status = _rp.derive_status(last, False)
            stale = _stale_claims(r.get("db"))
            if stale:
                summ["stale_claims"] = stale
                if new_status in ("interrupted", "failed"):
                    summ["hint"] = ("Tiến trình đã chết, DB còn commit đang building/analyzing — "
                                    "chạy `reset-claims --run <id>` rồi Resume")
            r["status"] = new_status
            r["finished"] = r.get("finished") or _now()
            dirty = True
            changed.append(dict(r))
        if dirty:
            save(data)
    return changed
