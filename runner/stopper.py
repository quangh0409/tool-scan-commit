"""Dừng run: stop-file hợp tác (mặc định) hoặc cưỡng bức (taskkill /T /F | killpg SIGTERM).

Sau khi tiến trình chết (hoặc đã chết sẵn) gọi `python -m orchestrator.cli stop-cleanup --run <id>`
(A2 `control.py`: dọn container label orch.run=<id>, gỡ network, reset-claims). Lệnh chưa tồn tại
→ ghi run.log, không crash.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import process as _p


def _log(rdir: Path, msg: str) -> None:
    try:
        rdir.mkdir(parents=True, exist_ok=True)
        with open(rdir / "run.log", "a", encoding="utf-8") as f:
            f.write(f"[runner {_p._now()}] {msg}\n")
    except OSError:
        pass


def _kill_tree(pid: int) -> dict:
    """Giết tiến trình + con. Windows: taskkill /T /F. Linux: SIGTERM cả nhóm."""
    if _p.IS_WIN:
        try:
            r = subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                               capture_output=True, text=True, errors="replace", timeout=30)
            return {"method": "taskkill", "rc": r.returncode,
                    "out": ((r.stdout or "") + (r.stderr or "")).strip()[-500:]}
        except (OSError, subprocess.TimeoutExpired) as e:
            return {"method": "taskkill", "rc": -1, "out": str(e)}
    try:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
            return {"method": "killpg", "rc": 0, "out": ""}
        except (ProcessLookupError, PermissionError, OSError):
            os.kill(pid, signal.SIGTERM)
            return {"method": "kill", "rc": 0, "out": ""}
    except ProcessLookupError:
        return {"method": "kill", "rc": 0, "out": "đã chết"}
    except OSError as e:
        return {"method": "kill", "rc": -1, "out": str(e)}


def _wait_dead(pid: int, timeout_s: float, poll_s: float = 0.25) -> bool:
    end = time.monotonic() + max(0.0, timeout_s)
    while time.monotonic() < end:
        if not _p.alive(pid):
            return True
        time.sleep(poll_s)
    return not _p.alive(pid)


def stop_cleanup(run_id: str, rdir: Path, python_exe: str | None = None, timeout_s: float = 180) -> dict:
    """Gọi `orchestrator.cli stop-cleanup --run <id>` với env của profile (để biết DB/port)."""
    env: dict[str, str] = dict(os.environ)
    meta = _p.read_meta(rdir) or {}
    try:
        _p._ensure_src_on_path()
        from orchestrator import profile as _profile  # noqa: PLC0415
        if meta.get("profile"):
            env = _p.build_env(_profile.load(meta["profile"]), run_id, rdir)
    except Exception as e:  # noqa: BLE001 — profile hỏng vẫn cố dọn với env hiện tại
        _log(rdir, f"stop-cleanup: không nạp được profile ({e}); dùng env hiện tại")
        src = str(_p.src_dir())
        env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "ORCH_RUN_ID": str(run_id)})

    argv = [python_exe or sys.executable, "-m", "orchestrator.cli", "stop-cleanup", "--run", str(run_id), "--json"]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                           timeout=timeout_s, env=env, cwd=str(_p.REPO_ROOT))
        out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        available = not (r.returncode != 0 and ("invalid choice" in out or "unrecognized arguments" in out))
        result: dict | None = None
        if not available:
            _log(rdir, "stop-cleanup chưa có trong orchestrator.cli (A2) — bỏ qua dọn container")
        else:
            _log(rdir, f"stop-cleanup rc={r.returncode}: {out[-800:]}")
            for line in (r.stdout or "").splitlines():       # dòng JSON của --json
                line = line.strip()
                if line.startswith("{"):
                    try:
                        result = json.loads(line)
                    except ValueError:
                        pass
        return {"rc": r.returncode, "available": available, "out": out[-2000:], "argv": argv, "result": result}
    except subprocess.TimeoutExpired:
        _log(rdir, f"stop-cleanup quá {timeout_s}s")
        return {"rc": 124, "available": True, "out": "timeout", "argv": argv}
    except OSError as e:
        _log(rdir, f"stop-cleanup lỗi: {e}")
        return {"rc": 127, "available": False, "out": str(e), "argv": argv}


def stop(run_id: str, work_dir: str | Path, force: bool = False, timeout_s: float = 10.0,
         python_exe: str | None = None, cleanup: bool | None = None) -> dict:
    """Dừng run.

    - Luôn tạo stop-file (orchestrator kết thúc commit hiện tại rồi thoát code 3).
    - force=True: taskkill /T /F (Win) | killpg SIGTERM (Linux), chờ ≤ timeout_s.
    - cleanup (mặc định = force hoặc pid đã chết sẵn): gọi `orchestrator.cli stop-cleanup`.
    """
    rdir = _p.run_dir(work_dir, run_id)
    rdir.mkdir(parents=True, exist_ok=True)
    stop_file = rdir / "stop"
    try:
        with open(stop_file, "w", encoding="utf-8") as f:
            json.dump({"ts": _p._now(), "force": bool(force), "by_pid": os.getpid()}, f)
    except OSError as e:
        _log(rdir, f"không tạo được stop-file: {e}")

    pid = _p.read_pid(rdir)
    alive_before = _p.alive(pid)
    _log(rdir, f"stop requested force={force} pid={pid} alive={alive_before}")

    killed: dict | None = None
    alive_after = alive_before
    if force and alive_before and pid:
        killed = _kill_tree(pid)
        alive_after = not _wait_dead(pid, timeout_s)
        _log(rdir, f"kill {killed} → alive_after={alive_after}")

    if cleanup is None:
        cleanup = bool(force) or not alive_before
    cleanup_res = None
    if cleanup and not alive_after:
        cleanup_res = stop_cleanup(run_id, rdir, python_exe)

    return {
        "ok": not alive_after if force else True,
        "stop_file": str(stop_file),
        "pid": pid,
        "alive_before": alive_before,
        "killed": killed,
        "alive_after": alive_after,
        "cleanup": cleanup_res,
    }
