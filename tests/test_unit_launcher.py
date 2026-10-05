"""packaging.launcher: điều phối argv (--version, --preflight, -m, --cli, --profile headless, GUI fallback)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    """`packaging/` trùng tên thư viện PyPI `packaging` (pytest dùng) → nạp theo đường dẫn file."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


launcher = _load("secjit_launcher", ROOT / "packaging" / "launcher.py")
version = launcher.version


@pytest.fixture(autouse=True)
def _restore_env():
    """launcher.main() đặt SECJIT_APP_VERSION — không để lọt sang test khác (test_data_core mong 'dev')."""
    import os
    snap = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(snap)


def test_version_prints(capsys):
    assert launcher.main(["--version"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("secjit-scan ") and launcher.APP_VERSION in out


def test_stdio_line_buffered_for_run_log(tmp_path, monkeypatch):
    """-m orchestrator.cli trong exe: stdout trỏ vào run.log phải line-buffered (exe bỏ qua PYTHONUNBUFFERED env)."""
    import io
    import runpy
    log = open(tmp_path / "run.log", "w", encoding="utf-8")       # noqa: SIM115 — giả stdout của tiến trình con
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(log.buffer, encoding="utf-8"))
    assert sys.stdout.line_buffering is False
    seen = {}

    def fake_run_module(mod, run_name=None, alter_sys=False):
        print("dòng 1 trước khi tiến trình chết")       # không flush thủ công
        seen["line_buffering"] = sys.stdout.line_buffering
        seen["on_disk"] = (tmp_path / "run.log").read_text(encoding="utf-8")
        raise SystemExit(0)
    monkeypatch.setattr(runpy, "run_module", fake_run_module)
    assert launcher.main(["-m", "orchestrator.cli", "pipeline"]) == 0
    assert seen["line_buffering"] is True and sys.stdout.write_through is True
    assert "dòng 1" in seen["on_disk"], "stdout chưa xuống file ngay sau print() → run.log sẽ 'đứng' trong exe"


def test_get_version_sources(monkeypatch, tmp_path):
    monkeypatch.setenv("SECJIT_APP_VERSION", "v9.9")
    assert version.get_version() == "v9.9"
    monkeypatch.delenv("SECJIT_APP_VERSION")
    p = version.write_build_file("v1.2.3-test", dest=tmp_path / "_version_build.txt")
    monkeypatch.setattr(version, "_candidates", lambda: [p])
    assert version.get_version() == "v1.2.3-test"
    monkeypatch.setattr(version, "_candidates", lambda: [tmp_path / "khong-co"])
    monkeypatch.setattr(version, "from_git", lambda *a, **k: None)
    assert version.get_version() == "dev"


def test_preflight_dispatch(monkeypatch, capsys):
    import preflight.__main__ as pm
    monkeypatch.setattr(pm, "run", lambda **kw: {"items": [], "ready": True, "docker_mem_gb": None, "cpu": None,
                                                 "codeql_ram_mb": None, "sonar_port": None, "fixed": [],
                                                 "os": "x", "ts": "t", "elapsed_s": 0})
    assert launcher.main(["--preflight", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ready"] is True


def test_cli_dispatch(monkeypatch):
    import orchestrator.cli as cli
    seen = {}
    monkeypatch.setattr(cli, "main", lambda argv: seen.setdefault("argv", argv) and 7)
    assert launcher.main(["--cli", "stats", "--json"]) == 7
    assert seen["argv"] == ["stats", "--json"]


def test_module_dispatch_sets_argv(monkeypatch):
    import runpy
    rec = {}

    def fake_run_module(mod, run_name=None, alter_sys=False):
        rec["mod"], rec["argv"] = mod, list(sys.argv)
        raise SystemExit(3)
    monkeypatch.setattr(runpy, "run_module", fake_run_module)
    assert launcher.main(["-m", "orchestrator.cli", "pipeline", "--profile", "p.json"]) == 3
    assert rec["mod"] == "orchestrator.cli" and rec["argv"] == ["orchestrator.cli", "pipeline", "--profile", "p.json"]
    assert launcher.main(["-m"]) == 1


def test_gui_default_and_fallback(monkeypatch, capsys):
    import gui.__main__ as gm
    import registry

    class _Held:  # GUI thật đang chạy trên máy (QA) giữ mutex -> test phải mock
        acquired = True

        def release(self):
            pass
    monkeypatch.setattr(registry.locks, "single_instance", lambda name="secjit-gui": _Held())
    monkeypatch.setattr(gm, "main", lambda argv: 0 if argv[:2] == ["--dev", "--no-browser"] else 9)
    assert launcher.main(["--dev", "--no-browser"]) == 0
    assert launcher.main([]) == 9
    # bản build không có gui → hướng dẫn, exit 1
    import builtins
    real_import = builtins.__import__

    def no_gui(name, *a, **k):
        if name.startswith("gui"):
            raise ImportError("no gui")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_gui)
    assert launcher.main(["--mock"]) == 1
    assert "GUI chưa có" in capsys.readouterr().err


def test_headless_requires_valid_profile(tmp_path, capsys):
    assert launcher.main(["--profile"]) == 1
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    assert launcher.main(["--profile", str(bad)]) == 1
    assert "profile" in capsys.readouterr().err.lower()


def test_headless_runs_and_waits(tmp_path, scratch_db, monkeypatch, capsys):
    """runner.start giả → tiến trình 'chết' ngay với progress export.done → exit 0, registry done."""
    from orchestrator import profile
    import registry
    import runner
    from runner import process as rp
    monkeypatch.setenv("SECJIT_HOME", str(tmp_path / "home"))
    p = profile.default_profile("https://github.com/x/y", "main")
    p["paths"] = {"db": str(scratch_db), "export": str(tmp_path / "exp"), "work": str(tmp_path / "work")}
    pf = tmp_path / "p.json"
    profile.save(p, pf)
    rdir = tmp_path / "work" / "r-test"
    rdir.mkdir(parents=True)
    (rdir / "progress.jsonl").write_text(json.dumps({"ts": "t", "phase": "export", "event": "done"}) + "\n",
                                         encoding="utf-8")

    def fake_start(profile_path, run_id, work_dir, python_exe=None, extra_env=None):
        return {"pid": 4242, "log": str(rdir / "run.log"), "progress": str(rdir / "progress.jsonl"),
                "stop": str(rdir / "stop"), "run_dir": str(rdir), "meta": "", "argv": []}
    monkeypatch.setattr(runner, "start", fake_start)
    monkeypatch.setattr(rp, "alive", lambda pid: False)
    monkeypatch.setattr("runner.notify.toast", lambda *a, **k: {"ok": True})
    rc = launcher.main(["--profile", str(pf), "--run-id", "r-test"])
    out = capsys.readouterr().out
    assert rc == 0 and "RUN_ID=r-test PID=4242" in out and "STATUS=done" in out and "export.done" in out
    assert registry.get("r-test")["status"] == "done"
    assert registry.locks.read_lock(scratch_db) is None


@pytest.mark.skipif(sys.platform != "win32", reason="spec/ps1 chỉ build trên Windows")
def test_spec_and_ps1_exist():
    assert (ROOT / "secjit.spec").exists() and (ROOT / "build_exe.ps1").exists()
    assert "secjit-scan-gui" in (ROOT / "secjit.spec").read_text(encoding="utf-8")
    assert not (ROOT / "packaging" / "__init__.py").exists(), "packaging/ không được là gói (trùng PyPI packaging)"
