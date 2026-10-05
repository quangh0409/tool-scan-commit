"""Fixture chung cho pytest. KHÔNG Docker: subprocess được mock bằng fixture `fake_docker`."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "src", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

FIXTURES = ROOT / "tests" / "fixtures"


@pytest.fixture
def scratch_db(tmp_path):
    """Bản sao DB train-ticket 3 commit (schema hiện tại) — mỗi test một bản."""
    dst = tmp_path / "scratch.sqlite"
    shutil.copy(FIXTURES / "scratch.db", dst)
    return dst


@pytest.fixture
def orch_env(monkeypatch, tmp_path, scratch_db):
    """Env ORCH_* trỏ vào tmp để import orchestrator.config sạch."""
    monkeypatch.setenv("ORCH_SQLITE", str(scratch_db))
    monkeypatch.setenv("ORCH_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("ORCH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ORCH_EXPORT_DIR", str(tmp_path / "export"))
    monkeypatch.setenv("ORCH_PROGRESS_FILE", str(tmp_path / "progress.jsonl"))
    monkeypatch.setenv("ORCH_STOP_FILE", str(tmp_path / "stop"))
    monkeypatch.setenv("ORCH_RUN_ID", "test-run")
    monkeypatch.setenv("PYTHONUTF8", "1")
    # config đọc env lúc import -> xoá module để nạp lại
    for m in [k for k in sys.modules if k.startswith("orchestrator")]:
        sys.modules.pop(m, None)
    return tmp_path


@pytest.fixture
def fake_docker(monkeypatch):
    """Thay subprocess.run: ghi lại lệnh, trả CompletedProcess theo bảng `responses`.

    Dùng: fake_docker.responses.append((lambda cmd: "docker" in cmd[0], (rc, stdout, stderr)))
    """
    import subprocess

    class _Rec:
        def __init__(self):
            self.calls: list[list[str]] = []
            self.responses: list[tuple] = []

        def run(self, cmd, *a, **kw):
            self.calls.append(list(cmd))
            for pred, (rc, out, err) in self.responses:
                if pred(cmd):
                    return subprocess.CompletedProcess(cmd, rc, out, err)
            return subprocess.CompletedProcess(cmd, 0, "", "")

    rec = _Rec()
    monkeypatch.setattr(subprocess, "run", rec.run)
    return rec


@pytest.fixture(autouse=True)
def _no_real_docker(monkeypatch):
    """Lưới an toàn: nếu test nào gọi docker thật mà quên mock -> fail rõ ràng."""
    if os.environ.get("ORCH_TEST_ALLOW_DOCKER") == "1":
        return
    import shutil as _sh
    real_which = _sh.which

    def _which(name, *a, **kw):
        if name == "docker":
            return None
        return real_which(name, *a, **kw)

    monkeypatch.setattr(_sh, "which", _which)
