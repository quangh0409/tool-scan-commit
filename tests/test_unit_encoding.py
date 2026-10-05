"""Encoding: _git / docker_run không nổ UnicodeDecodeError với byte GBK (errors="replace")."""
from __future__ import annotations

import shutil
import subprocess

import pytest

GBK_BYTES = "中文注释：数据库连接".encode("gbk") + b"\xff\xfe\x81"   # không phải UTF-8 hợp lệ


def _emulate_run(record: dict):
    """Giả subprocess.run: ép decode stdout bytes theo text/encoding/errors mà caller truyền (như CPython làm)."""
    def run(cmd, *a, **kw):
        record["cmd"], record["kw"] = list(cmd), kw
        assert kw.get("text") is True, "phải mở text mode"
        assert kw.get("errors") == "replace", "thiếu errors='replace' -> GBK sẽ nổ"
        out = GBK_BYTES.decode(kw.get("encoding") or "utf-8", errors=kw["errors"])
        return subprocess.CompletedProcess(cmd, 0, out, "")
    return run


def test_git_wrapper_decodes_gbk_with_replace(monkeypatch, tmp_path):
    from orchestrator import enumerate_commits as enm
    rec = {}
    monkeypatch.setattr(subprocess, "run", _emulate_run(rec))
    out = enm._git(tmp_path, "show", "HEAD")
    assert "�" in out and rec["cmd"][:3] == ["git", "-C", str(tmp_path)]


def test_docker_run_decodes_gbk_and_labels(monkeypatch):
    from orchestrator.tools import base
    rec = {}
    monkeypatch.setattr(subprocess, "run", _emulate_run(rec))
    monkeypatch.setenv("ORCH_RUN_ID", "r-gbk")
    monkeypatch.delenv("ORCH_DOCKER_SG", raising=False)
    proc = base.docker_run(["run", "--rm", "img", "cmd"], timeout=5)
    assert "�" in proc.stdout
    assert rec["cmd"][:4] == ["docker", "run", "--label", "orch.run=r-gbk"]
    assert rec["kw"]["timeout"] == 5


def test_decode_without_replace_would_fail():
    """Khẳng định dữ liệu test thật sự không phải UTF-8 (nếu không test trên vô nghĩa)."""
    with pytest.raises(UnicodeDecodeError):
        GBK_BYTES.decode("utf-8")


@pytest.mark.skipif(shutil.which("git") is None, reason="cần git thật")
def test_real_git_show_gbk_file(tmp_path):
    """git thật: file GBK commit vào repo tạm -> _git(... show) trả str, có ký tự thay thế, không raise."""
    from orchestrator import enumerate_commits as enm
    repo = tmp_path / "repo gbk's"
    repo.mkdir()
    (repo / "Readme中.txt").write_bytes(GBK_BYTES)
    g = lambda *a: enm._git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false", *a)  # noqa: E731
    g("init", "-q")
    g("add", "-A")
    g("commit", "-q", "-m", "gbk")
    out = g("show", "HEAD", "--format=", "--no-color")
    assert isinstance(out, str) and "�" in out
    files = g("show", "--name-only", "--format=", "HEAD").strip()
    assert "Readme" in files
