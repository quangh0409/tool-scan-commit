"""Khởi chạy tiến trình orchestrator tách rời + kiểm pid + attach lại run cũ.

Windows: CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW (đóng GUI không giết run; lệnh con không bật cửa sổ cmd).
Linux  : start_new_session=True (nhóm tiến trình riêng để killpg).
Mọi file ghi utf-8. Không raise ra ngoài trừ lỗi profile / không tạo được tiến trình.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

IS_WIN = os.name == "nt"

# Gốc repo: runner/ nằm ngay dưới gốc. Khi đóng gói PyInstaller dùng sys._MEIPASS.
REPO_ROOT = Path(getattr(sys, "_MEIPASS", None) or Path(__file__).resolve().parents[1])

_STILL_ACTIVE = 259
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

TERMINAL_EVENTS = ("done", "stop", "error")


def src_dir() -> Path:
    """Thư mục chứa gói `orchestrator` (repo/src; trong bundle có thể là gốc bundle)."""
    cand = REPO_ROOT / "src"
    if (cand / "orchestrator").is_dir():
        return cand
    if (REPO_ROOT / "orchestrator").is_dir():
        return REPO_ROOT
    return cand


def _ensure_src_on_path() -> None:
    s = str(src_dir())
    if s not in sys.path:
        sys.path.insert(0, s)


def run_dir(work_dir: str | Path, run_id: str) -> Path:
    return Path(work_dir) / str(run_id)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------- env/argv

def build_env(profile: dict, run_id: str, rdir: Path, extra_env: dict | None = None) -> dict[str, str]:
    """os.environ + profile.to_env() + biến runner (CONTRACTS §3)."""
    _ensure_src_on_path()
    from orchestrator import profile as _profile  # noqa: PLC0415 — import sau khi chỉnh sys.path

    env = dict(os.environ)
    env.update(_profile.to_env(profile))
    src = str(src_dir())
    old_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src if not old_pp else src + os.pathsep + old_pp
    env.update({
        "ORCH_RUN_ID": str(run_id),
        "ORCH_PROGRESS_FILE": str(rdir / "progress.jsonl"),
        "ORCH_STOP_FILE": str(rdir / "stop"),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
    })
    if extra_env:
        env.update({str(k): str(v) for k, v in extra_env.items()})
    return env


def build_argv(profile_path: str | Path, python_exe: str | None = None) -> list[str]:
    return [python_exe or sys.executable, "-m", "orchestrator.cli", "pipeline",
            "--profile", str(profile_path)]


# ---------------------------------------------------------------- start

def start(profile_path: str | Path, run_id: str, work_dir: str | Path,
          python_exe: str | None = None, extra_env: dict | None = None) -> dict:
    """Khởi chạy `python -m orchestrator.cli pipeline --profile <file>` tách rời.

    Trả {"pid","log","progress","stop","run_dir","meta","argv"}. Raise ProfileError nếu profile
    không hợp lệ, OSError nếu không tạo được tiến trình.
    """
    _ensure_src_on_path()
    from orchestrator import profile as _profile  # noqa: PLC0415

    profile_path = Path(profile_path)
    prof = _profile.load(profile_path)          # validate — lỗi thì raise sớm, chưa tạo gì
    rdir = run_dir(work_dir, run_id)
    rdir.mkdir(parents=True, exist_ok=True)

    stop_file = rdir / "stop"
    if stop_file.exists():                      # resume: stop-file cũ sẽ làm run dừng ngay
        try:
            stop_file.unlink()
        except OSError:
            pass

    env = build_env(prof, run_id, rdir, extra_env)
    argv = build_argv(profile_path, python_exe)
    log_path = rdir / "run.log"

    popen_kw: dict = {
        "stdin": subprocess.DEVNULL,
        "close_fds": True,
        "cwd": str(REPO_ROOT),
        "env": env,
    }
    if IS_WIN:
        # CREATE_NO_WINDOW thay DETACHED_PROCESS (lỗi thật 2026-10-05): tiến trình DETACHED không có console
        # -> MỌI lệnh console con (docker, git, mvn…) tự bật 1 cửa sổ cmd. NO_WINDOW = console ẩn riêng,
        # con thừa hưởng console ẩn đó -> không bật cửa sổ; vẫn sống độc lập khi đóng GUI.
        popen_kw["creationflags"] = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
                                     | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
    else:
        popen_kw["start_new_session"] = True

    with open(log_path, "a", encoding="utf-8") as logf:
        logf.write(f"\n===== runner start {_now()} run_id={run_id} =====\n")
        logf.write("argv: " + json.dumps(argv, ensure_ascii=False) + "\n")
        logf.flush()
        proc = subprocess.Popen(argv, stdout=logf, stderr=subprocess.STDOUT, **popen_kw)

    pid = int(proc.pid)
    (rdir / "pid").write_text(str(pid), encoding="utf-8")
    meta = {
        "run_id": str(run_id),
        "pid": pid,
        "profile": str(profile_path),
        "repo": prof.get("repo"),
        "branch": prof.get("branch"),
        "db": (prof.get("paths") or {}).get("db"),
        "export": (prof.get("paths") or {}).get("export"),
        "started": _now(),
        "argv": argv,
        "python": argv[0],
        "cwd": str(REPO_ROOT),
        "log": str(log_path),
        "progress": env["ORCH_PROGRESS_FILE"],
        "stop": env["ORCH_STOP_FILE"],
        "host_os": sys.platform,
    }
    with open(rdir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return {"pid": pid, "log": str(log_path), "progress": meta["progress"], "stop": meta["stop"],
            "run_dir": str(rdir), "meta": str(rdir / "meta.json"), "argv": argv}


# ---------------------------------------------------------------- alive

def _alive_windows(pid: int) -> bool:
    try:
        import ctypes  # noqa: PLC0415
        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        h = k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return False
            return code.value == _STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    except Exception:  # noqa: BLE001 — fallback tasklist
        try:
            r = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH", "/FO", "CSV"],
                               capture_output=True, text=True, errors="replace", timeout=10)
            return f'"{int(pid)}"' in (r.stdout or "")
        except Exception:  # noqa: BLE001
            return False


def alive(pid: int | None) -> bool:
    """True nếu tiến trình pid còn sống. pid None/<=0 → False. Không raise."""
    try:
        pid = int(pid or 0)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if IS_WIN:
        return _alive_windows(pid)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- attach

def read_pid(rdir: Path) -> int | None:
    try:
        return int((rdir / "pid").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def read_meta(rdir: Path) -> dict | None:
    try:
        with open(rdir / "meta.json", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def last_progress(rdir: Path) -> dict | None:
    """Dòng progress hợp lệ cuối cùng (None nếu chưa có)."""
    _ensure_src_on_path()
    try:
        from orchestrator import progress as _progress  # noqa: PLC0415
        lines = _progress.read(rdir / "progress.jsonl")
    except Exception:  # noqa: BLE001
        lines = []
    return lines[-1] if lines else None


def derive_status(last: dict | None, is_alive: bool) -> str:
    """Trạng thái registry từ dòng progress cuối + pid: running|done|stopped|failed|interrupted."""
    if is_alive:
        return "running"
    if not last:
        return "interrupted"
    ev = last.get("event")
    ph = last.get("phase")
    if ev == "stop":
        return "stopped"
    if ev == "error":
        return "failed"
    if ev == "done" and ph in ("export", "stats", "review"):
        return "done"
    return "interrupted"


def attach(run_id: str, work_dir: str | Path) -> dict:
    """Gắn lại vào run đã khởi chạy trước đó (GUI mở lại / Home liệt kê).

    interrupted = pid chết mà progress chưa có sự kiện kết thúc (done export / stop / error).
    """
    rdir = run_dir(work_dir, run_id)
    pid = read_pid(rdir)
    is_alive = alive(pid) if pid else False
    last = last_progress(rdir)
    status = derive_status(last, is_alive)
    return {
        "run_id": str(run_id),
        "pid": pid,
        "alive": is_alive,
        "last_progress_line": last,
        "interrupted": status == "interrupted",
        "status": status,
        "meta": read_meta(rdir),
        "log": str(rdir / "run.log"),
        "run_dir": str(rdir),
        "exists": rdir.exists(),
    }
