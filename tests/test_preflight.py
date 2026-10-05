"""Preflight: parse docker info / ports / images → level đúng; pick_port; fix dispatcher; CLI JSON."""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

import preflight
from preflight import checks, fixes

GB = 1024 ** 3


@pytest.fixture
def docker_present(monkeypatch):
    """Giả có docker/git/wsl trong PATH (ghi đè lưới an toàn _no_real_docker)."""
    def _which(name, *a, **kw):
        return {"docker": r"C:\fake\docker.exe", "git": r"C:\fake\git.exe", "wsl": r"C:\fake\wsl.exe"}.get(name)
    monkeypatch.setattr(shutil, "which", _which)


def _resp(fake, pred, rc=0, out="", err=""):
    fake.responses.insert(0, (pred, (rc, out, err)))


def _is(sub):
    return lambda cmd: sub in " ".join(map(str, cmd))


# ---------------------------------------------------------------- docker_mem

def test_docker_mem_low_is_warn(fake_docker, docker_present):
    _resp(fake_docker, _is("docker info"), 0, f"{int(4.5 * GB)} 4 29.1.3 linux")
    ctx = {}
    it = checks.run_check("docker_mem", ctx)
    assert it["level"] == "warn"
    assert it["mem_gb"] == 4.5 and it["cpu"] == 4
    assert ".wslconfig" in it["detail"] or "RAM" in it["detail"]
    assert ctx["codeql_ram_mb"] == 2560  # 4.5*1024*0.6 = 2764.8 → bội 256 → 2560


def test_docker_mem_ok(fake_docker, docker_present):
    _resp(fake_docker, _is("docker info"), 0, f"{7237505024} 8 29.1.3 linux")
    it = checks.run_check("docker_mem", {})
    assert it["level"] == "ok" and it["mem_gb"] == 6.74 and it["cpu"] == 8


def test_docker_mem_needs_daemon(fake_docker, docker_present):
    _resp(fake_docker, _is("docker info"), 1, "", "error during connect: dockerDesktopLinuxEngine")
    it = checks.run_check("docker_mem", {})
    assert it["level"] == "bad"
    d = checks.run_check("docker_daemon", {})
    assert d["level"] in ("fix", "bad")
    assert d["fix_id"] in ("start_docker", None)


def test_docker_daemon_windows_mode_bad(fake_docker, docker_present):
    _resp(fake_docker, _is("docker info"), 0, f"{8 * GB} 8 29.1.3 windows")
    assert checks.run_check("docker_daemon", {})["level"] == "bad"


# ---------------------------------------------------------------- images

def test_images_missing_fsb_is_fix_with_build_hint(fake_docker, docker_present):
    _resp(fake_docker, _is("docker info"), 0, f"{8 * GB} 8 29 linux")
    present = [im["name"] for im in checks.REQUIRED_IMAGES if im["name"] not in ("orch-findsecbugs:1.14.0", "bearer/bearer:latest")]
    present = [p if ":" in p.rsplit("/", 1)[-1] else p + ":latest" for p in present]
    _resp(fake_docker, _is("docker images"), 0, "\n".join(f"{p}\tsha256:abc" for p in present))
    it = checks.run_check("images", {})
    assert it["level"] == "fix" and it["fix_id"] == "pull_images"
    assert set(it["missing"]) == {"orch-findsecbugs:1.14.0", "bearer/bearer:latest"}
    assert "BUILD" in it["detail"] and "docker/findsecbugs" in it["detail"]
    assert "orch-codeql" not in it["missing"]  # codeql tuỳ chọn


def test_images_all_present_scanner_any_tag(fake_docker, docker_present):
    _resp(fake_docker, _is("docker info"), 0, f"{8 * GB} 8 29 linux")
    names = [im["name"] for im in checks.REQUIRED_IMAGES if not im.get("optional")]
    names = [n if ":" in n.rsplit("/", 1)[-1] else n + ":5.0.1" for n in names]  # sonar-scanner-cli:5.0.1
    _resp(fake_docker, _is("docker images"), 0, "\n".join(f"{n}\tsha256:{i}" for i, n in enumerate(names)))
    ctx = {}
    it = checks.run_check("images", ctx)
    assert it["level"] == "ok" and it["present"] == it["required"]
    pin = checks.run_check("images_pinned", ctx)
    assert pin["level"] == "warn" and "horuszup/horusec-cli:latest" in pin["latest"]


# ---------------------------------------------------------------- sonar_port / pick_port

def test_sonar_port_busy_suggests_next(fake_docker, docker_present, monkeypatch):
    _resp(fake_docker, _is("docker info"), 0, f"{8 * GB} 8 29 linux")
    _resp(fake_docker, _is("docker ps"), 0, "giapha-minio\t0.0.0.0:9000->9000/tcp, 0.0.0.0:9001->9001/tcp")
    busy = {9000, 9100}
    monkeypatch.setattr(checks, "port_busy", lambda p, host="0.0.0.0": p in busy)
    it = checks.run_check("sonar_port", {"sonar_port": 9000})
    assert it["level"] == "fix" and it["fix_id"] == "pick_port"
    assert it["suggested"] == 9200 and "giapha-minio" in it["detail"]


def test_sonar_port_free_ok(fake_docker, docker_present, monkeypatch):
    _resp(fake_docker, _is("docker info"), 0, f"{8 * GB} 8 29 linux")
    monkeypatch.setattr(checks, "port_busy", lambda p, host="0.0.0.0": False)
    it = checks.run_check("sonar_port", {"sonar_port": 9100})
    assert it["level"] == "ok" and it["port"] == 9100


def test_pick_port_skips_busy(monkeypatch):
    busy = {9000, 9100, 9200}
    monkeypatch.setattr(checks, "port_busy", lambda p, host="0.0.0.0": p in busy)
    assert fixes.pick_port(9000) == 9300
    assert fixes.pick_port(9000, owners={9300: "x"}) == 9400
    monkeypatch.setattr(checks, "port_busy", lambda p, host="0.0.0.0": True)
    assert fixes.pick_port(9000, max_tries=3) is None


def test_port_busy_real_socket():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    try:
        assert checks.port_busy(port) is True
    finally:
        s.close()


# ---------------------------------------------------------------- misc checks

def test_git_longpaths_levels(fake_docker, docker_present):
    _resp(fake_docker, _is("core.longpaths"), 0, "true")
    assert checks.run_check("git_longpaths", {})["level"] == "ok"
    _resp(fake_docker, _is("core.longpaths"), 1, "", "")
    lvl = checks.run_check("git_longpaths", {})["level"]
    assert lvl == ("fix" if checks.IS_WIN else "ok")


def test_max_map_count_parses_wsl_utf16(fake_docker, docker_present):
    if not checks.IS_WIN:
        pytest.skip("wsl chỉ Windows")
    _resp(fake_docker, _is("docker info"), 0, f"{8 * GB} 8 29 linux")
    _resp(fake_docker, _is("sysctl"), 0, "65530\n".encode("utf-16-le"))
    it = checks.run_check("max_map_count", {})
    assert it["level"] == "warn" and it["value"] == 65530 and it["fix_id"] == "max_map_count"
    _resp(fake_docker, _is("sysctl"), 0, "262144")
    assert checks.run_check("max_map_count", {})["level"] == "ok"


def test_disk_free_levels(tmp_path, monkeypatch):
    Du = type("Du", (), {})
    def _du(free):
        d = Du()
        d.total, d.used, d.free = 100 * GB, 1, free
        return d
    monkeypatch.setattr(shutil, "disk_usage", lambda p: _du(2 * GB))
    it = checks.run_check("disk_free", {"work_dir": str(tmp_path), "need_gb": 5})
    assert it["level"] == "warn"
    monkeypatch.setattr(shutil, "disk_usage", lambda p: _du(0.5 * GB))
    assert checks.run_check("disk_free", {"work_dir": str(tmp_path)})["level"] == "bad"
    monkeypatch.setattr(shutil, "disk_usage", lambda p: _du(50 * GB))
    assert checks.run_check("disk_free", {"work_dir": str(tmp_path / "chưa có" / "x")})["level"] == "ok"


def test_network_levels(monkeypatch):
    monkeypatch.setattr(checks, "_tcp_ok", lambda h, p=443, timeout=3: (h == "github.com", "refused"))
    it = checks.run_check("network", {})
    assert it["level"] == "warn" and it["unreachable"] == ["registry-1.docker.io"]
    monkeypatch.setattr(checks, "_tcp_ok", lambda h, p=443, timeout=3: (False, "timeout"))
    assert checks.run_check("network", {})["level"] == "bad"


def test_check_never_raises(monkeypatch):
    def boom(ctx):
        raise RuntimeError("nổ")
    monkeypatch.setitem(checks.CHECKS, "git", boom)
    it = checks.run_check("git", {})
    assert it["level"] == "bad" and "nổ" in it["detail"]


def test_run_cmd_missing_and_timeout(monkeypatch):
    rc, _, err = checks.run_cmd(["khong-ton-tai-xyz", "--v"], timeout=2)
    assert rc == 127 and err

    def _to(*a, **kw):
        raise subprocess.TimeoutExpired(a[0], kw.get("timeout", 1))
    monkeypatch.setattr(subprocess, "run", _to)
    assert checks.run_cmd(["x"], timeout=1)[0] == 124


# ---------------------------------------------------------------- run() + fix

def test_run_all_items_and_ready(fake_docker, docker_present, monkeypatch):
    _resp(fake_docker, _is("docker info"), 0, f"{8 * GB} 8 29 linux")
    names = [im["name"] for im in checks.REQUIRED_IMAGES]
    names = [n if ":" in n.rsplit("/", 1)[-1] else n + ":latest" for n in names]
    _resp(fake_docker, _is("docker images"), 0, "\n".join(f"{n}\tsha256:x" for n in names))
    _resp(fake_docker, _is("core.longpaths"), 0, "true")
    _resp(fake_docker, _is("sysctl"), 0, "262144")
    _resp(fake_docker, _is("wsl --status"), 0, "Default Version: 2")
    _resp(fake_docker, _is("git --version"), 0, "git version 2.47.0")
    _resp(fake_docker, _is("docker --version"), 0, "Docker version 29.1.3")
    monkeypatch.setattr(checks, "port_busy", lambda p, host="0.0.0.0": False)
    monkeypatch.setattr(checks, "_tcp_ok", lambda h, p=443, timeout=3: (True, ""))
    res = preflight.run()
    ids = [it["id"] for it in res["items"]]
    assert ids == list(checks.CHECK_ORDER) and len(ids) == 13
    assert all(it["level"] in preflight.LEVELS for it in res["items"])
    assert res["docker_mem_gb"] == 8.0 and res["cpu"] == 8 and res["sonar_port"] == 9000
    blocking = [it["id"] for it in res["items"] if it["level"] in ("bad", "fix")]
    assert blocking == [], blocking
    assert res["ready"] is True


def test_run_fix_pick_port_then_recheck(fake_docker, docker_present, monkeypatch):
    _resp(fake_docker, _is("docker info"), 0, f"{8 * GB} 8 29 linux")
    busy = {9000}
    monkeypatch.setattr(checks, "port_busy", lambda p, host="0.0.0.0": p in busy)
    res = preflight.run(fix=True, targets=["pick_port"], checks=["sonar_port"], sonar_port=9000)
    assert res["fixed"] == [{"fix_id": "pick_port", "check": "sonar_port", "ok": True, "detail": "Dùng port 9100."}]
    assert res["items"][0]["level"] == "ok" and res["items"][0]["port"] == 9100 and res["sonar_port"] == 9100
    assert res["ready"] is True


def test_lower_codeql_ram():
    assert fixes.lower_codeql_ram(16) == 9728     # 16*1024*0.6=9830 → 9728
    assert fixes.lower_codeql_ram(2) == 2048      # sàn
    assert fixes.lower_codeql_ram("x") == 2048


def test_parse_pull_line_progress():
    layers = {}
    assert fixes.parse_pull_line("latest: Pulling from semgrep/semgrep", layers) is None
    fixes.parse_pull_line("a1b2c3d4: Pulling fs layer", layers)
    fixes.parse_pull_line("e5f6a7b8: Downloading [=====>    ]  10MB/100MB", layers)
    pct = fixes.parse_pull_line("a1b2c3d4: Pull complete", layers)
    assert pct == 52.5   # (1.0 + 0.05) / 2
    assert fixes.parse_pull_line("e5f6a7b8: Extracting [====>  ]  50MB/100MB", layers) == 87.5


def test_apply_unknown_and_git_longpaths(fake_docker, docker_present):
    assert fixes.apply("khong-co")["ok"] is False
    _resp(fake_docker, _is("core.longpaths true"), 0, "")
    r = fixes.apply("git_longpaths")
    assert r["ok"] is True
    assert ["git", "config", "--global", "core.longpaths", "true"] in fake_docker.calls


def test_start_docker_polls_until_up(fake_docker, docker_present, monkeypatch):
    if not checks.IS_WIN:
        pytest.skip("Docker Desktop chỉ Windows")
    monkeypatch.setattr(fixes, "_find_docker_desktop", lambda: r"C:\fake\Docker Desktop.exe")
    popen_calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: popen_calls.append((a, kw)))
    state = {"n": 0}

    def info(cmd):
        return "docker info" in " ".join(cmd)
    def run(cmd, *a, **kw):
        fake_docker.calls.append(list(cmd))
        if info(cmd):
            state["n"] += 1
            if state["n"] >= 3:
                return subprocess.CompletedProcess(cmd, 0, f"{8 * GB} 8 29 linux", "")
            return subprocess.CompletedProcess(cmd, 1, "", "error during connect")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(subprocess, "run", run)
    events = []
    r = fixes.start_docker(progress_cb=events.append, timeout_s=90, poll_s=3, _sleep=lambda s: None)
    assert r["ok"] is True and popen_calls and popen_calls[0][0][0][0].endswith("Docker Desktop.exe")
    assert events and events[-1]["percent"] == 100


def test_start_docker_timeout(fake_docker, docker_present, monkeypatch):
    if not checks.IS_WIN:
        pytest.skip("Docker Desktop chỉ Windows")
    monkeypatch.setattr(fixes, "_find_docker_desktop", lambda: r"C:\fake\Docker Desktop.exe")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: None)
    _resp(fake_docker, _is("docker info"), 1, "", "error during connect")
    r = fixes.start_docker(timeout_s=9, poll_s=3, _sleep=lambda s: None)
    assert r["ok"] is False and "9 s" in r["detail"]


# ---------------------------------------------------------------- CLI

def test_cli_json_exit_code(fake_docker, docker_present, monkeypatch, capsys, tmp_path):
    from preflight.__main__ import main
    _resp(fake_docker, _is("docker info"), 1, "", "error during connect")
    out_file = tmp_path / "preflight.json"
    rc = main(["--json", "--out", str(out_file), "--only", "docker_installed,docker_daemon"])
    assert rc == 1
    data = json.loads(capsys.readouterr().out)
    assert [it["id"] for it in data["items"]] == ["docker_installed", "docker_daemon"]
    assert data["ready"] is False
    assert json.loads(out_file.read_text(encoding="utf-8"))["ready"] is False
