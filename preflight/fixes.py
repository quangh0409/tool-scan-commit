"""Auto-fix cho preflight. Mỗi fix trả {"ok": bool, "detail": str, ...}; không raise ra ngoài.

fix_id: start_docker · pick_port · pull_images · git_longpaths · lower_codeql_ram · max_map_count
progress_cb(info: dict) với info = {"fix_id", "step", "total", "percent", "msg"} (GUI hiện tiến độ).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import checks as _c

REPO_ROOT = Path(__file__).resolve().parents[1]

_PROGRESS_RE = re.compile(
    r"^(?P<layer>[0-9a-f]{6,}):\s+(?P<st>\w[\w ]*?)\s*(?:\[(?P<bar>[=> ]*)\])?\s*"
    r"(?P<num>[\d.]+\s*[kMG]?B/[\d.]+\s*[kMG]?B)?\s*$")
_SIZE_RE = re.compile(r"([\d.]+)\s*([kMG]?B)")
_UNIT = {"B": 1, "kB": 1e3, "MB": 1e6, "GB": 1e9}


def _cb(progress_cb, **info) -> None:
    if progress_cb:
        try:
            progress_cb(info)
        except Exception:  # noqa: BLE001 — callback GUI lỗi không được làm hỏng fix
            pass


# ---------------------------------------------------------------- start_docker

def _find_docker_desktop() -> str | None:
    cands = [
        _c.DOCKER_DESKTOP_EXE,
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Docker", "Docker", "Docker Desktop.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Docker", "Docker", "Docker Desktop.exe"),
    ]
    for c in cands:
        if c and Path(c).exists():
            return c
    return None


def start_docker(progress_cb=None, timeout_s: float = 90.0, poll_s: float = 3.0, _sleep=time.sleep) -> dict:
    """Bật Docker Desktop (Windows) rồi poll `docker info` mỗi poll_s tới khi lên hoặc hết timeout_s."""
    ctx: dict = {"docker_timeout": 10}
    if _c.docker_up(ctx):
        return {"ok": True, "detail": "Docker daemon đã chạy sẵn.", "elapsed": 0}
    if not _c.IS_WIN:
        rc, out, err = _c.run_cmd(["systemctl", "start", "docker"], timeout=30)
        if rc == 0:
            _c.invalidate(ctx)
            if _c.docker_up(ctx):
                return {"ok": True, "detail": "systemctl start docker OK.", "elapsed": 0}
        return {"ok": False, "detail": f"Không tự bật được daemon (rc={rc}: {err or out}). "
                                       "Chạy `sudo systemctl start docker`.", "elapsed": 0}
    exe = _find_docker_desktop()
    if not exe:
        return {"ok": False, "detail": "Không tìm thấy Docker Desktop.exe — mở Docker Desktop thủ công.", "elapsed": 0}
    try:
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen([exe], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         close_fds=True, creationflags=flags)
    except OSError as e:
        return {"ok": False, "detail": f"Không khởi chạy được Docker Desktop: {e}", "elapsed": 0}
    t0 = time.monotonic()
    elapsed = 0.0
    while elapsed <= timeout_s:
        _cb(progress_cb, fix_id="start_docker", step=int(elapsed), total=int(timeout_s),
            percent=min(99, int(100 * elapsed / timeout_s)), msg=f"Đang chờ Docker daemon… {int(elapsed)}/{int(timeout_s)} s")
        _c.invalidate(ctx)
        if _c.docker_up(ctx):
            _cb(progress_cb, fix_id="start_docker", step=int(elapsed), total=int(timeout_s), percent=100, msg="Docker đã lên.")
            return {"ok": True, "detail": f"Docker daemon lên sau {int(elapsed)} s.", "elapsed": int(elapsed)}
        _sleep(poll_s)
        elapsed = time.monotonic() - t0 if _sleep is time.sleep else elapsed + poll_s
    return {"ok": False, "detail": f"Docker Desktop không lên sau {int(timeout_s)} s. Mở Docker Desktop, xem "
                                   "Settings → General (WSL2 engine) và thử lại.", "elapsed": int(elapsed)}


# ---------------------------------------------------------------- pick_port

def pick_port(start: int = 9000, step: int = 100, max_tries: int = 10, owners: dict | None = None) -> int | None:
    """Port trống đầu tiên trong start, start+step, … (bỏ port bận theo socket và theo docker ps)."""
    owners = owners or {}
    for i in range(max_tries):
        p = start + i * step
        if p > 65535:
            break
        if p in owners or _c.port_busy(p):
            continue
        return p
    return None


# ---------------------------------------------------------------- pull_images

def _to_bytes(s: str) -> float:
    m = _SIZE_RE.search(s or "")
    if not m:
        return 0.0
    return float(m.group(1)) * _UNIT.get(m.group(2), 1)


def parse_pull_line(line: str, layers: dict) -> float | None:
    """Cập nhật tiến độ layer từ 1 dòng `docker pull`; trả % tổng (0–100) hoặc None nếu không phải dòng tiến độ."""
    m = _PROGRESS_RE.match(line.strip())
    if not m:
        return None
    layer, st = m.group("layer"), (m.group("st") or "").strip().lower()
    if st in ("pull complete", "already exists", "download complete"):
        layers[layer] = 1.0
    elif st in ("downloading", "extracting") and m.group("num"):
        cur, _, tot = m.group("num").partition("/")
        tb = _to_bytes(tot)
        frac = (_to_bytes(cur) / tb) if tb else 0.0
        if st == "extracting":
            frac = 0.5 + frac / 2
        else:
            frac = frac / 2
        layers[layer] = max(layers.get(layer, 0.0), min(frac, 0.999))
    elif st in ("waiting", "pulling fs layer", "verifying checksum"):
        layers.setdefault(layer, 0.0)
    if not layers:
        return None
    return round(100.0 * sum(layers.values()) / len(layers), 1)


def _stream(cmd: list[str], on_line, timeout_s: float, cwd: str | None = None) -> tuple[int, str]:
    """Chạy lệnh, gọi on_line(line) từng dòng stdout+stderr; trả (rc, tail)."""
    tail: list[str] = []
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                text=True, encoding="utf-8", errors="replace", cwd=cwd, close_fds=True)
    except OSError as e:
        return 127, str(e)
    t0 = time.monotonic()
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\r\n")
            tail.append(line)
            if len(tail) > 30:
                tail.pop(0)
            on_line(line)
            if time.monotonic() - t0 > timeout_s:
                proc.kill()
                return 124, "\n".join(tail) + f"\n(quá {timeout_s}s)"
        rc = proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        rc = 124
    return rc, "\n".join(tail)


def pull_images(progress_cb=None, images: list[dict] | None = None, include_optional: bool = False,
                repo_root: Path | None = None, timeout_pull_s: float = 1800, timeout_build_s: float = 2400) -> dict:
    """Pull các image thiếu; image kind=build → `docker build -t <name> -f <dir>/Dockerfile <dir>`."""
    root = Path(repo_root or REPO_ROOT)
    ctx: dict = {}
    todo = images if images is not None else _c.missing_images(ctx, include_optional=include_optional)
    done, failed = [], []
    total = len(todo)
    for i, im in enumerate(todo, 1):
        name = im["name"]
        layers: dict = {}

        def on_line(line, _name=name, _i=i, _layers=layers):
            pct = parse_pull_line(line, _layers)
            _cb(progress_cb, fix_id="pull_images", step=_i, total=total, image=_name,
                percent=pct if pct is not None else None, msg=line[-120:])

        if im.get("kind") == "build":
            d = root / im["dir"]
            cmd = ["docker", "build", "-t", name, "-f", str(d / "Dockerfile"), str(d)]
            _cb(progress_cb, fix_id="pull_images", step=i, total=total, image=name, percent=None,
                msg=f"Build {name} từ {im['dir']} (5–10 phút)…")
            rc, tail = _stream(cmd, on_line, timeout_build_s, cwd=str(root))
        else:
            _cb(progress_cb, fix_id="pull_images", step=i, total=total, image=name, percent=0, msg=f"Pull {name}…")
            rc, tail = _stream(["docker", "pull", name], on_line, timeout_pull_s)
        if rc == 0:
            done.append(name)
            _cb(progress_cb, fix_id="pull_images", step=i, total=total, image=name, percent=100, msg=f"{name} xong.")
        else:
            failed.append({"image": name, "rc": rc, "error": tail[-600:]})
    ok = not failed
    detail = f"Xong {len(done)}/{total}." + ("" if ok else " Lỗi: " + ", ".join(f["image"] for f in failed))
    return {"ok": ok, "detail": detail, "done": done, "failed": failed}


# ---------------------------------------------------------------- git_longpaths

def git_longpaths() -> dict:
    if not shutil.which("git"):
        return {"ok": False, "detail": "Chưa có git."}
    rc, out, err = _c.run_cmd(["git", "config", "--global", "core.longpaths", "true"], timeout=15)
    if rc == 0:
        return {"ok": True, "detail": "Đã đặt core.longpaths=true (global)."}
    return {"ok": False, "detail": f"git config rc={rc}: {err or out}"}


# ---------------------------------------------------------------- lower_codeql_ram

def lower_codeql_ram(mem_gb: float, ratio: float = 0.6, floor_mb: int = 2048, step_mb: int = 256) -> int:
    """MB đề xuất cho ORCH_CODEQL_RAM_MB = 60 % RAM Docker, làm tròn xuống bội 256, tối thiểu 2048."""
    try:
        mb = int(float(mem_gb) * 1024 * ratio)
    except (TypeError, ValueError):
        return floor_mb
    mb = (mb // step_mb) * step_mb
    return max(floor_mb, mb)


# ---------------------------------------------------------------- max_map_count

def max_map_count(value: int = _c.MIN_MAX_MAP_COUNT) -> dict:
    if _c.IS_WIN:
        rc, out, err = _c.run_cmd(["wsl", "-d", "docker-desktop", "sysctl", "-w", f"vm.max_map_count={value}"],
                                  timeout=20)
    else:
        rc, out, err = _c.run_cmd(["sysctl", "-w", f"vm.max_map_count={value}"], timeout=20)
    if rc == 0:
        return {"ok": True, "detail": f"vm.max_map_count={value} (reset sau reboot)."}
    return {"ok": False, "detail": f"rc={rc}: {err or out}"}


# ---------------------------------------------------------------- dispatcher

FIX_IDS = ("start_docker", "pick_port", "pull_images", "git_longpaths", "lower_codeql_ram", "max_map_count")


def apply(fix_id: str, ctx: dict | None = None, progress_cb=None) -> dict:
    """Chạy 1 fix theo id; luôn trả dict {"ok","detail",...}, không raise."""
    ctx = ctx if ctx is not None else {}
    try:
        if fix_id == "start_docker":
            r = start_docker(progress_cb)
            _c.invalidate(ctx)
            return r
        if fix_id == "pick_port":
            want = int(ctx.get("sonar_port") or os.environ.get("ORCH_SONAR_PORT") or 9000)
            owners = _c.docker_published_ports(ctx)
            p = pick_port(start=want, owners=owners)
            if p is None:
                return {"ok": False, "detail": "Không tìm được port trống."}
            ctx["sonar_port"] = p
            return {"ok": True, "detail": f"Dùng port {p}.", "port": p}
        if fix_id == "pull_images":
            r = pull_images(progress_cb, include_optional=bool(ctx.get("include_codeql")))
            _c.invalidate(ctx, "local_images")
            return r
        if fix_id == "git_longpaths":
            return git_longpaths()
        if fix_id == "lower_codeql_ram":
            mb = lower_codeql_ram(ctx.get("docker_mem_gb") or 0)
            ctx["codeql_ram_mb"] = mb
            return {"ok": True, "detail": f"Đề xuất ORCH_CODEQL_RAM_MB={mb}; workers.expensive=1.", "codeql_ram_mb": mb}
        if fix_id == "max_map_count":
            return max_map_count()
        return {"ok": False, "detail": f"fix_id lạ: {fix_id!r}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": f"Lỗi khi sửa {fix_id}: {type(e).__name__}: {e}"}
