"""Điều khiển run & dọn dẹp (CONTRACTS §7, §11): stop / stop-cleanup / reset-claims / clean. Stdlib-only.

- stop(run_id, force): tạo stop-file `<work>/<run_id>/stop` (orchestrator kết thúc commit hiện tại, không claim
  mới, exit 3). force -> đọc `<work>/<run_id>/pid`, Windows `taskkill /T /F /PID`, Linux SIGTERM nhóm, rồi
  stop_cleanup.
- stop_cleanup(run_id): `docker ps -aq --filter label=orch.run=<id>` -> rm -f; network `orch-sonar-net-<id>` -> rm.
- reset_claims(db, run_id, all_stale): selected_commits building/analyzing -> pending; xoá raw_output/raw_findings
  tier=expensive + expensive_runs của các commit đó (quy trình SESSION_CONTEXT 2026-07-08, tránh nhân đôi audit).
- clean_plan/clean_apply: dọn theo mục clone,pool,m2,export:<dir>,db:<path>; từ chối khi `<db>.lock` còn sống
  hoặc pool thuộc tiến trình đang chạy.

Mọi lệnh docker đi qua tools.base.docker_run (subprocess.run -> mock được bằng fixture fake_docker).
"""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from . import config, keys


# ----------------------------------------------------------------------------- pid
def pid_alive(pid: int) -> bool:
    """True nếu tiến trình còn sống. Windows: OpenProcess + GetExitCodeProcess (KHÔNG dùng os.kill(pid,0)
    — trên Windows nó TerminateProcess!). POSIX: os.kill(pid, 0)."""
    if not pid or pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return False
            return code.value == 259           # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _read_pid(path: Path) -> int | None:
    try:
        txt = path.read_text(encoding="utf-8").strip().split()[0]
        return int(txt)
    except (OSError, ValueError, IndexError):
        return None


def run_dir(run_id: str, work: Path | None = None) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", run_id or ""):
        raise ValueError(f"run_id không hợp lệ: {run_id!r}")
    return Path(work or config.WORK_DIR) / run_id


# ----------------------------------------------------------------------------- stop
def kill_pid(pid: int) -> dict:
    """Kết thúc cây tiến trình. Windows taskkill /T /F; POSIX SIGTERM nhóm (fallback SIGTERM pid)."""
    if sys.platform == "win32":
        proc = subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, text=True,
                              errors="replace", timeout=60)
        return {"pid": pid, "rc": proc.returncode, "out": (proc.stdout or proc.stderr or "").strip()[:300]}
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        return {"pid": pid, "rc": 0, "out": "SIGTERM group"}
    except (ProcessLookupError, PermissionError, OSError) as e:
        try:
            os.kill(pid, signal.SIGTERM)
            return {"pid": pid, "rc": 0, "out": f"SIGTERM pid ({e})"}
        except OSError as e2:
            return {"pid": pid, "rc": 1, "out": str(e2)}


def stop(run_id: str, force: bool = False, work: Path | None = None) -> dict:
    d = run_dir(run_id, work)
    d.mkdir(parents=True, exist_ok=True)
    stop_file = d / "stop"
    stop_file.write_text("stop\n", encoding="utf-8")
    res: dict = {"run_id": run_id, "stop_file": str(stop_file), "forced": force, "killed": None,
                 "cleaned": None, "errors": []}
    if force:
        pid = _read_pid(d / "pid")
        if pid is None:
            res["errors"].append(f"không đọc được pid từ {d / 'pid'}")
        elif not pid_alive(pid):
            res["killed"] = {"pid": pid, "rc": 0, "out": "đã chết trước đó"}
        else:
            res["killed"] = kill_pid(pid)
            if res["killed"]["rc"] != 0:
                res["errors"].append(f"kill pid {pid} thất bại: {res['killed']['out']}")
        res["cleaned"] = stop_cleanup(run_id)
        res["errors"] += res["cleaned"]["errors"]
    return res


def _docker(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    from .tools.base import docker_run
    return docker_run(args, timeout=timeout)


def stop_cleanup(run_id: str) -> dict:
    run_dir(run_id)                                    # validate run_id
    res = {"run_id": run_id, "containers": [], "networks": [], "errors": []}
    try:
        ps = _docker(["ps", "-aq", "--filter", f"label=orch.run={run_id}"])
        ids = [x for x in (ps.stdout or "").split() if x]
        if ps.returncode != 0:
            res["errors"].append(f"docker ps rc={ps.returncode}: {(ps.stderr or '').strip()[:200]}")
        if ids:
            rm = _docker(["rm", "-f", *ids])
            if rm.returncode != 0:
                res["errors"].append(f"docker rm rc={rm.returncode}: {(rm.stderr or '').strip()[:200]}")
            res["containers"] = ids
        nl = _docker(["network", "ls", "-q", "--filter", f"name=orch-sonar-net-{run_id}"])
        nets = [x for x in (nl.stdout or "").split() if x]
        if nets:
            rmn = _docker(["network", "rm", *nets])
            if rmn.returncode != 0:
                res["errors"].append(f"docker network rm rc={rmn.returncode}: {(rmn.stderr or '').strip()[:200]}")
            res["networks"] = nets
    except (OSError, subprocess.SubprocessError) as e:
        res["errors"].append(f"docker không chạy được: {e}")
    # reset-claims theo run (DB từ env ORCH_SQLITE — runner truyền env profile khi gọi stop-cleanup)
    db = Path(config.SQLITE_PATH)
    if db.exists():
        try:
            res["reset_claims"] = reset_claims(db, run_id=run_id)["reset"]
        except Exception as e:  # noqa: BLE001 — DB đang bị run sống giữ lock, v.v.
            res["errors"].append(f"reset-claims: {e}")
    else:
        res["reset_claims"] = None
    return res


# ----------------------------------------------------------------------------- reset-claims
def reset_claims(db: Path, run_id: str | None = None, all_stale: bool = False) -> dict:
    """building/analyzing -> pending + xoá raw đắt bán phần (raw_output/raw_findings tier=expensive) qua
    `store.reset_claims(run_id)` của A1 (claimed_by dạng `<run_id>:wN`; None/--all-stale = tất cả).
    expensive_runs GIỮ (telemetry — quyết định A1). Store giữ lock DB -> run đang sống trên DB đó -> RuntimeError."""
    from .storage.sqlite_store import SQLiteStore
    rid = None if all_stale else (run_id or None)
    store = SQLiteStore(Path(db))
    try:
        q = "SELECT commit_id FROM selected_commits WHERE status IN ('building','analyzing')"
        args: list = []
        if rid:
            q += " AND claimed_by LIKE ?"
            args = [f"{rid}:%"]
        cids = [r[0] for r in store.conn.execute(q, args)]
        fn = getattr(store, "reset_claims", None)
        if fn is not None:
            n = fn(rid)
        else:                                   # store cũ: tự làm 3 bước
            for cid in cids:
                store.reset_expensive_raw(cid)
                store.set_commit_status(cid, "pending")
            n = len(cids)
        return {"db": str(db), "run_id": rid, "all_stale": all_stale, "reset": n, "commits": cids}
    finally:
        store.close()


# ----------------------------------------------------------------------------- clean
def parse_items(spec: str | None) -> list[tuple[str, str | None]]:
    """'clone,pool,export:D:/x,db:D:/y.sqlite' -> [(kind, arg)]. export/db bắt buộc có đường dẫn."""
    out: list[tuple[str, str | None]] = []
    for raw in (spec or "clone,pool").split(","):
        raw = raw.strip()
        if not raw:
            continue
        kind, _, arg = raw.partition(":")
        # Windows: 'db:D:\x.sqlite' -> partition tại ':' đầu -> kind='db', arg='D:\x.sqlite' (đúng)
        kind = kind.strip().lower()
        if kind not in ("clone", "pool", "m2", "export", "db"):
            raise ValueError(f"clean: mục lạ {kind!r}; hợp lệ clone,pool,m2,export:<dir>,db:<path>")
        if kind in ("export", "db"):
            if not arg.strip():
                raise ValueError(f"clean: {kind} bắt buộc chỉ rõ đường dẫn ({kind}:<path>) — không xoá theo env mặc định")
            out.append((kind, arg.strip()))
        else:
            if arg.strip():
                raise ValueError(f"clean: {kind} không nhận đối số")
            out.append((kind, None))
    if not out:
        raise ValueError("clean: không có mục nào")
    return out


def dir_size(p: Path) -> int:
    total = 0
    try:
        if p.is_file():
            return p.stat().st_size
        for root, _dirs, files in os.walk(p):
            for f in files:
                try:
                    total += (Path(root) / f).stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _lock_alive(db: Path) -> int | None:
    """pid trong <db>.lock nếu còn sống, ngược lại None."""
    lock = Path(str(db) + ".lock")
    if not lock.exists():
        return None
    pid = _read_pid(lock)
    return pid if pid and pid_alive(pid) else None


def clean_plan(repo: str, items: list[tuple[str, str | None]], work: Path | None = None) -> dict:
    """Liệt kê {path, bytes} sẽ xoá + lỗi (từ chối). Không xoá gì."""
    work = Path(work or config.WORK_DIR)
    plan: dict = {"would_delete": [], "errors": [], "items": [f"{k}:{a}" if a else k for k, a in items]}

    def _add(p: Path, label: str):
        if p.exists():
            plan["would_delete"].append({"path": str(p), "bytes": dir_size(p), "item": label})

    for kind, arg in items:
        if kind == "clone":
            slug = keys.repo_slug(repo)
            legacy = repo.rstrip("/").split("/")[-1].removesuffix(".git")
            for name in {slug, legacy}:
                _add(work / name, "clone")
        elif kind == "pool":
            for pd in sorted(work.glob("pool_*")):
                m = re.fullmatch(r"pool_(\d+)", pd.name)
                pid = int(m.group(1)) if m else None
                if pid and pid_alive(pid):
                    plan["errors"].append(f"pool {pd} thuộc tiến trình {pid} ĐANG CHẠY — từ chối")
                    continue
                _add(pd, "pool")
        elif kind == "m2":
            _add(work / ".m2cache", "m2")
        elif kind == "export":
            _add(Path(arg), "export")
        elif kind == "db":
            dbp = Path(arg)
            pid = _lock_alive(dbp)
            if pid:
                plan["errors"].append(f"DB {dbp} đang bị khoá bởi pid {pid} (<db>.lock còn sống) — từ chối")
                continue
            for suffix in ("", "-wal", "-shm", ".lock"):
                _add(Path(str(dbp) + suffix), "db")
    return plan


def _rmtree(p: Path) -> None:
    from . import repo_pool
    fn = getattr(repo_pool, "rmtree_force", None) or getattr(repo_pool, "_rmtree", None)
    if fn is not None:
        fn(p)
    else:
        shutil.rmtree(p, ignore_errors=True)


def clean_apply(plan: dict) -> dict:
    """Xoá theo plan (bỏ qua nếu plan có errors từ-chối cho mục đó — các mục khác vẫn xoá)."""
    res = {"would_delete": plan["would_delete"], "deleted": [], "errors": list(plan["errors"])}
    for d in plan["would_delete"]:
        p = Path(d["path"])
        try:
            if p.is_dir():
                _rmtree(p)
            elif p.exists():
                p.unlink()
            if p.exists():
                res["errors"].append(f"không xoá hết {p} (file bị giữ/root-owned?)")
            else:
                res["deleted"].append(d)
        except OSError as e:
            res["errors"].append(f"{p}: {e}")
    return res
