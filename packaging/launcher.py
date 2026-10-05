"""Entry của exe PyInstaller (secjit-scan.exe console / secjit-scan-gui.exe noconsole).

Cách gọi:
  secjit-scan.exe                      -> GUI (gui.__main__: pywebview, fallback trình duyệt); không có gui -> hướng dẫn
  secjit-scan.exe --version            -> in phiên bản (SECJIT_APP_VERSION / git describe lúc build)
  secjit-scan.exe --preflight [--json] [--fix id] ... -> preflight.__main__ (exit 0 nếu ready)
  secjit-scan.exe --profile F [--work-dir D] [--run-id ID] -> chạy pipeline HEADLESS: runner.start rồi chờ, in progress
  secjit-scan.exe --cli <lệnh orchestrator.cli ...>        -> orchestrator.cli.main(...)
  secjit-scan.exe -m orchestrator.cli ...                   -> runpy (runner.start dùng chính exe làm "python")
  Mọi arg khác được chuyển cho gui.__main__ (--dev --mock --port --no-browser).
  GUI: giữ mutex single-instance `secjit-gui`; khi server lên ghi %SECJIT_HOME%/gui.json {url, port, token, pid,
  started} (exe noconsole không có stdout), xoá khi tắt. Chạy lần 2 → mở trình duyệt tới URL trong gui.json.

Set PYTHONUTF8=1 + PYTHONIOENCODING=utf-8 + SECJIT_APP_VERSION trước khi import orchestrator.
"""
from __future__ import annotations

import json
import os
import runpy
import sys
import time
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

FROZEN = bool(getattr(sys, "frozen", False))
BASE = Path(getattr(sys, "_MEIPASS", None) or Path(__file__).resolve().parents[1])

# gói top-level (runner, registry, preflight, gui) + src/orchestrator
for p in (BASE, BASE / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

def _load_version_module():
    """Nạp packaging/version.py THEO ĐƯỜNG DẪN (thư mục `packaging` trùng tên thư viện PyPI `packaging`
    mà pytest/pip/PyInstaller dùng → không được import theo tên gói)."""
    import importlib.util
    for cand in (Path(__file__).resolve().parent / "version.py", BASE / "packaging" / "version.py"):
        if cand.exists():
            spec = importlib.util.spec_from_file_location("secjit_version", cand)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            return mod
    return None


version = _load_version_module()


def get_version() -> str:
    if version is not None:
        return version.get_version()
    return os.environ.get("SECJIT_APP_VERSION") or "dev"


APP_VERSION = get_version()

EXIT_OK, EXIT_ARGS, EXIT_RUNTIME, EXIT_STOPPED = 0, 1, 2, 3


def _utf8_stdio() -> None:
    """UTF-8 + line-buffered cho stdout/stderr.

    Exe PyInstaller khởi tạo interpreter ở chế độ isolated → BỎ QUA PYTHONUTF8/PYTHONUNBUFFERED trong env; khi
    runner.start trỏ stdout của `secjit-scan.exe -m orchestrator.cli pipeline` vào run.log thì file bị block-buffer
    (Run B 2026-10-05: run.log dừng ở 673 byte trong khi progress.jsonl vẫn ghi). line_buffering=True + write_through
    để Dashboard tab Log cập nhật sống. Chạy từ nguồn: build_env đặt PYTHONUNBUFFERED=1 nên đã đủ.
    """
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace", line_buffering=True, write_through=True)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 — noconsole exe: stdout có thể là None
            pass


def _pop_opt(argv: list[str], name: str, default: str | None = None) -> tuple[list[str], str | None]:
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            val = argv[i + 1]
            return argv[:i] + argv[i + 2:], val
        return argv[:i] + argv[i + 1:], default
    return argv, default


# ---------------------------------------------------------------- chế độ

def run_module(argv: list[str]) -> int:
    """`-m orchestrator.cli ...` giống python -m (frozen: exe tự làm interpreter cho runner.start)."""
    if not argv:
        print("thiếu tên module sau -m", file=sys.stderr)
        return EXIT_ARGS
    mod, rest = argv[0], argv[1:]
    sys.argv = [mod, *rest]
    try:
        runpy.run_module(mod, run_name="__main__", alter_sys=True)
        return EXIT_OK
    except SystemExit as e:
        return int(e.code or 0) if not isinstance(e.code, str) else EXIT_RUNTIME


def run_preflight(argv: list[str]) -> int:
    from preflight.__main__ import main as pf_main
    return int(pf_main(argv) or 0)


def run_cli(argv: list[str]) -> int:
    from orchestrator.cli import main as cli_main
    return int(cli_main(argv) or 0)


def run_headless(argv: list[str]) -> int:
    """--profile F [--work-dir D] [--run-id ID] [--quiet]: chạy pipeline tách rời và theo dõi tới khi xong."""
    import runner
    from runner import process as rp

    argv, profile_path = _pop_opt(argv, "--profile")
    argv, work_dir = _pop_opt(argv, "--work-dir")
    argv, run_id = _pop_opt(argv, "--run-id")
    quiet = "--quiet" in argv
    if not profile_path:
        print("cần --profile <file>", file=sys.stderr)
        return EXIT_ARGS
    try:
        from orchestrator import profile as prof
        p = prof.load(profile_path)
    except Exception as e:  # noqa: BLE001
        print(f"LỖI profile: {e}", file=sys.stderr)
        return EXIT_ARGS
    work_dir = work_dir or (p.get("paths") or {}).get("work") or str(Path.cwd() / "work")
    run_id = run_id or time.strftime("run-%Y%m%d-%H%M%S")

    try:
        import registry
        registry.locks.acquire_db_lock(p["paths"]["db"], run_id, pid=os.getpid())
    except Exception as e:  # noqa: BLE001 — DbLocked hoặc không ghi được
        print(f"LỖI: {e}", file=sys.stderr)
        return EXIT_RUNTIME

    res = runner.start(profile_path, run_id, work_dir, python_exe=sys.executable)
    try:
        registry.locks.acquire_db_lock(p["paths"]["db"], run_id, pid=res["pid"], force=True)
        registry.upsert({"run_id": run_id, "repo": p["repo"], "branch": p.get("branch"), "db": p["paths"]["db"],
                         "export": p["paths"].get("export"), "work": str(work_dir), "profile": str(profile_path),
                         "pid": res["pid"], "status": "running"})
    except Exception as e:  # noqa: BLE001
        print(f"CẢNH BÁO registry: {e}", file=sys.stderr)
    print(f"RUN_ID={run_id} PID={res['pid']} LOG={res['log']}", flush=True)

    seen = 0
    status = "running"
    try:
        while True:
            from orchestrator import progress as _progress
            lines = _progress.read(res["progress"], since_line=seen)
            for ln in lines:
                seen += 1
                if not quiet:
                    print(f"[{ln.get('ts', '')}] {ln.get('phase')}.{ln.get('event')} "
                          f"{ln.get('done', '')}/{ln.get('total', '')} {ln.get('sha', '') or ''} "
                          f"{ln.get('status', '') or ''} {ln.get('msg', '') or ''}".rstrip(), flush=True)
            if not rp.alive(res["pid"]):
                lines = _progress.read(res["progress"], since_line=seen)
                seen += len(lines)
                status = rp.derive_status(rp.last_progress(Path(res["run_dir"])), False)
                break
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nCtrl+C: tạo stop-file (run kết thúc commit hiện tại rồi dừng). Ctrl+C lần nữa để cưỡng bức.",
              flush=True)
        runner.stop(run_id, work_dir)
        try:
            while rp.alive(res["pid"]):
                time.sleep(1.0)
        except KeyboardInterrupt:
            runner.stop(run_id, work_dir, force=True, python_exe=sys.executable)
        status = rp.derive_status(rp.last_progress(Path(res["run_dir"])), False)
    finally:
        try:
            import registry
            registry.set_status(run_id, status if status in registry.STATUSES else "interrupted")
            registry.locks.release_db_lock(p["paths"]["db"], run_id)
        except Exception:  # noqa: BLE001
            pass
        try:
            from runner.notify import toast
            toast("SecJIT Scan", f"Run {run_id}: {status}")
        except Exception:  # noqa: BLE001
            pass
    print(f"STATUS={status}", flush=True)
    return {"done": EXIT_OK, "stopped": EXIT_STOPPED}.get(status, EXIT_RUNTIME)


# ---------------------------------------------------------------- gui.json (exe noconsole không có stdout)

def gui_info_path() -> Path:
    import registry
    return registry.home() / "gui.json"


def write_gui_info(url: str, port: int, token: str, pid: int | None = None) -> Path:
    import registry
    p = gui_info_path()
    registry.atomic_write_json(p, {"url": url, "port": int(port), "token": token, "pid": int(pid or os.getpid()),
                                   "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "version": APP_VERSION})
    return p


def read_gui_info() -> dict | None:
    try:
        with open(gui_info_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and d.get("url") else None
    except (OSError, ValueError):
        return None


def clear_gui_info(only_pid: int | None = None) -> None:
    info = read_gui_info()
    if info is None:
        return
    if only_pid is not None and info.get("pid") not in (None, only_pid):
        return
    try:
        gui_info_path().unlink()
    except OSError:
        pass


def _reachable(url: str, timeout: float = 2.0) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 500
    except Exception:  # noqa: BLE001
        return False


def _patch_server_for_gui_info(server_mod) -> None:
    """Bọc GuiServer.serve_in_thread/stop để ghi/xoá gui.json (A4 chưa có hook on_ready — xem YÊU CẦU LIÊN AGENT)."""
    cls = server_mod.GuiServer
    if getattr(cls, "_secjit_gui_info", False):
        return
    orig_serve, orig_stop = cls.serve_in_thread, cls.stop

    def serve_in_thread(self, *a, **k):
        t = orig_serve(self, *a, **k)
        try:
            write_gui_info(self.url, self.port, self.token)
        except Exception as e:  # noqa: BLE001
            print(f"CẢNH BÁO: không ghi được gui.json: {e}", file=sys.stderr)
        return t

    def stop(self, *a, **k):
        try:
            return orig_stop(self, *a, **k)
        finally:
            clear_gui_info(only_pid=os.getpid())

    cls.serve_in_thread, cls.stop, cls._secjit_gui_info = serve_in_thread, stop, True


def open_existing_instance(open_browser=None) -> int:
    """Instance khác đang giữ mutex: đọc gui.json → pid sống + URL trả lời → mở trình duyệt tới đó."""
    import webbrowser
    from runner import process as rp
    info = read_gui_info()
    if info and rp.alive(info.get("pid")) and _reachable(info["url"]):
        print(f"SECJIT_GUI_URL={info['url']}", flush=True)
        print("SecJIT Scan đang chạy (pid %s) — mở lại cửa sổ trong trình duyệt." % info["pid"], flush=True)
        (open_browser or webbrowser.open)(info["url"])
        return EXIT_OK
    clear_gui_info()
    print("SecJIT Scan có vẻ đang chạy (mutex secjit-gui bị giữ) nhưng không tìm thấy URL hoạt động trong gui.json. "
          "Đóng cửa sổ cũ (hoặc kết thúc tiến trình) rồi thử lại.", file=sys.stderr)
    return EXIT_RUNTIME


def run_gui(argv: list[str], open_browser=None) -> int:
    try:
        from gui import server as gui_server
        from gui.__main__ import main as gui_main
    except Exception as e:  # noqa: BLE001 — bản build chưa có gui
        print(f"SecJIT Scan {APP_VERSION}: GUI chưa có trong bản build này ({type(e).__name__}: {e}).", file=sys.stderr)
        print(__doc__, file=sys.stderr)
        return EXIT_ARGS
    import registry
    # --allow-multi / --mock (QA): không giữ mutex, không ghi gui.json (gui.__main__ cũng bỏ khoá ở 2 cờ này)
    if "--allow-multi" in argv or "--mock" in argv:
        return int(gui_main(argv) or 0)
    lock = registry.locks.single_instance("secjit-gui")
    if not lock.acquired:
        return open_existing_instance(open_browser)
    _patch_server_for_gui_info(gui_server)
    try:
        return int(gui_main(argv) or 0)
    finally:
        clear_gui_info(only_pid=os.getpid())
        lock.release()


def main(argv: list[str] | None = None) -> int:
    _utf8_stdio()
    os.environ.setdefault("SECJIT_APP_VERSION", APP_VERSION)   # orchestrator ghi vào run_meta.app_version
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] in (["--version"], ["-V"]):
        print(f"secjit-scan {APP_VERSION} (python {sys.version.split()[0]}, frozen={FROZEN})")
        return EXIT_OK
    if argv[:1] == ["-m"]:
        return run_module(argv[1:])
    if argv[:1] == ["--preflight"]:
        return run_preflight(argv[1:])
    if argv[:1] == ["--cli"]:
        return run_cli(argv[1:])
    if "--profile" in argv and not any(a in argv for a in ("--dev", "--mock", "--port", "--no-browser")):
        return run_headless(argv)
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__)
        return EXIT_OK
    return run_gui(argv)


if __name__ == "__main__":
    sys.exit(main())
