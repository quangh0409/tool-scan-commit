"""Đường dẫn: mọi mount `-v host:container` có phía container là POSIX; host có `'`, khoảng trắng, unicode.

- Tĩnh (AST): quét tools/*.py + tools_expensive/*.py — phần tử ngay sau "-v" trong list literal phải là
  f-string/chuỗi kết thúc bằng ":/<posix>[:ro]" (không backslash, không Path Windows ở phía container).
- Động: gọi scan() của tool rẻ/đắt với clone_dir kỳ dị (mock docker) → kiểm argv thật.
- profile.to_shell: quote PowerShell/bash giữ nguyên đường dẫn có `'`, khoảng trắng, unicode.
"""
from __future__ import annotations

import ast
import contextlib
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL_FILES = sorted((ROOT / "src" / "orchestrator" / "tools").glob("*.py")) + \
    sorted((ROOT / "src" / "orchestrator" / "tools_expensive").glob("*.py"))
CONTAINER_SIDE = re.compile(r":/[A-Za-z0-9_./-]+(:ro)?$")
WEIRD = "Luận văn's thesis — tool scan"      # có ' , khoảng trắng, unicode, gạch dài


def _mount_specs() -> list[tuple[str, int, str]]:
    """(file, line, tail-literal) cho mọi phần tử đứng sau "-v" trong list literal."""
    out = []
    for f in TOOL_FILES:
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.List, ast.Tuple)):
                continue
            elts = node.elts
            for i, e in enumerate(elts[:-1]):
                if isinstance(e, ast.Constant) and e.value == "-v":
                    spec = elts[i + 1]
                    if isinstance(spec, ast.JoinedStr):
                        last = spec.values[-1]
                        tail = last.value if isinstance(last, ast.Constant) else "<expr>"
                    elif isinstance(spec, ast.Constant):
                        tail = str(spec.value)
                    else:
                        tail = "<expr>"
                    out.append((f.name, spec.lineno, tail))
    return out


def test_static_every_mount_has_posix_container_side():
    specs = _mount_specs()
    assert len(specs) >= 10, specs      # gitleaks, trufflehog, semgrep, bearer, horusec×2, build×2, fsb, sonar×2, codeql×2
    bad = [s for s in specs if s[2] == "<expr>" or not CONTAINER_SIDE.search(s[2]) or "\\" in s[2]]
    assert not bad, f"mount có phía container không phải literal POSIX: {bad}"


def _container_sides(calls: list[list[str]]) -> list[str]:
    sides = []
    for cmd in calls:
        if len(cmd) < 2 or cmd[1] != "run":
            continue
        for i, a in enumerate(cmd[:-1]):
            if a == "-v":
                sides.append(cmd[i + 1].rsplit(":", 2)[-2] if cmd[i + 1].endswith(":ro") else cmd[i + 1].rsplit(":", 1)[-1])
    return sides


def _assert_posix(sides: list[str]):
    assert sides, "không thấy docker run -v nào"
    for s in sides:
        assert s.startswith("/") and "\\" not in s and "'" not in s, s


@pytest.fixture
def weird_repo(tmp_path):
    d = tmp_path / WEIRD / "clone"
    (d / "svc" / "src" / "main" / "java").mkdir(parents=True)
    (d / "svc" / "src" / "main" / "java" / "A.java").write_text("class A {}", encoding="utf-8")
    (d / "svc" / "target" / "classes").mkdir(parents=True)
    return d


@pytest.mark.parametrize("modname,stdout", [
    ("gitleaks", "[]"), ("trufflehog", ""), ("semgrep", '{"results": [], "errors": []}'),
    ("bearer", '{"high": []}'), ("horusec", ""),
])
def test_cheap_tools_mount_posix_with_weird_host_path(orch_env, fake_docker, weird_repo, modname, stdout):
    import importlib
    fake_docker.responses.append((lambda cmd: "docker" in cmd[0], (0, stdout, "")))
    mod = importlib.import_module(f"orchestrator.tools.{modname}")
    tool_cls = next(v for k, v in vars(mod).items()
                    if isinstance(v, type) and k.endswith("Wrapper") and k != "ToolWrapper")
    with contextlib.suppress(Exception):      # chỉ quan tâm argv; parse output rỗng có thể raise
        tool_cls().scan(weird_repo, "abcdef1234567890", "https://github.com/x/y", ["svc/src/main/java/A.java"])
    sides = _container_sides(fake_docker.calls)
    _assert_posix(sides)
    host_sides = [c[i + 1].rsplit(":", 1)[0] for c in fake_docker.calls for i, a in enumerate(c[:-1]) if a == "-v"]
    assert any(WEIRD in h or "horusec_proj_" in h or "bearer" in h.lower() or "tmp" in h.lower() for h in host_sides), host_sides


def test_findsecbugs_targets_posix(orch_env, fake_docker, weird_repo):
    from orchestrator.tools_expensive import findsecbugs
    from orchestrator.tools_expensive.base import BuildContext
    ctx = BuildContext(commit_id="abcdef123456789", repo="r", clone_dir=weird_repo, ok=True,
                       classes_dirs=[weird_repo / "svc" / "target" / "classes"])
    with contextlib.suppress(Exception):      # XML không tồn tại -> ToolError, chấp nhận
        findsecbugs.FindSecBugsTool().scan(ctx)
    _assert_posix(_container_sides(fake_docker.calls))
    sh = fake_docker.calls[0][-1]
    assert "/work/svc/target/classes" in sh and "\\" not in sh
    assert f"{weird_repo}:/work" in fake_docker.calls[0]


def test_build_commit_mounts_posix(orch_env, fake_docker, weird_repo, monkeypatch):
    from orchestrator.tools_expensive import build
    monkeypatch.setattr(build, "changed_modules", lambda clone, cid: ["svc"])
    monkeypatch.setattr(build, "maven_image_for", lambda clone, cid: "maven:3.9-eclipse-temurin-8")
    ctx = build.build_commit(weird_repo, "abcdef123456789", "r")
    assert ctx.status in ("ok", "build_failed"), ctx.error
    sides = _container_sides(fake_docker.calls)
    assert set(sides) == {"/work", "/m2"}
    cmd = fake_docker.calls[0]
    assert cmd[cmd.index("-w") + 1] == "/work"
    assert any(a == f"{weird_repo}:/work" for a in cmd)


# ---------------------------------------------------------------- profile.to_shell quoting

def _weird_profile(tmp_path):
    from orchestrator import profile
    base = tmp_path / WEIRD
    p = profile.default_profile("https://github.com/FudanSELab/train-ticket", "master")
    p["paths"] = {"db": str(base / "dataset's.sqlite"), "export": str(base / "export ạ"), "work": str(base / "work")}
    return p


def test_to_shell_bash_roundtrip(tmp_path):
    from orchestrator import profile
    p = _weird_profile(tmp_path)
    cmd = profile.to_shell(p, "bash")
    toks = shlex.split(cmd)
    env = dict(t.split("=", 1) for t in toks if "=" in t and t.split("=", 1)[0].isupper())
    assert env["ORCH_SQLITE"] == p["paths"]["db"] and env["ORCH_EXPORT_DIR"] == p["paths"]["export"]
    assert "--out" in toks and toks[toks.index("--out") + 1] == p["paths"]["export"]


def test_to_shell_powershell_quotes_single_quote(tmp_path):
    from orchestrator import profile
    p = _weird_profile(tmp_path)
    cmd = profile.to_shell(p, "powershell")
    db = p["paths"]["db"]
    assert f"$env:ORCH_SQLITE='{db.replace(chr(39), chr(39) * 2)}'" in cmd
    # không còn dấu ' đơn lẻ nào bên trong giá trị: mọi ' trong path đều đã nhân đôi
    inner = cmd.split("$env:ORCH_SQLITE='", 1)[1].split("'; ", 1)[0]
    assert inner.count("''") == db.count("'")


@pytest.mark.skipif(sys.platform != "win32", reason="cần powershell thật")
def test_to_shell_powershell_real_roundtrip(tmp_path):
    from orchestrator import profile
    p = _weird_profile(tmp_path)
    cmd = profile.to_shell(p, "powershell")
    sets = cmd.split("; $env:PYTHONPATH=", 1)[0]
    script = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + sets +
              "; Write-Output $env:ORCH_SQLITE; Write-Output $env:ORCH_EXPORT_DIR")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, timeout=60)
    out = r.stdout.decode("utf-8", errors="replace").splitlines()
    assert r.returncode == 0, r.stderr.decode("utf-8", errors="replace")
    assert out[0] == p["paths"]["db"] and out[1] == p["paths"]["export"]


def test_env_values_survive_os_environ_roundtrip(tmp_path):
    """Đường dẫn unicode/`'` đi qua os.environ -> config.reload() không vỡ (ORCH_SQLITE là Path)."""
    from orchestrator import config, profile
    p = _weird_profile(tmp_path)
    snap = dict(os.environ)
    try:
        os.environ.update(profile.to_env(p))
        config.reload()
        assert str(config.SQLITE_PATH) == p["paths"]["db"]
        assert os.fspath(config.EXPORT_DIR) == p["paths"]["export"]
    finally:
        os.environ.clear()
        os.environ.update(snap)
        config.reload()          # không để config bẩn cho test khác
