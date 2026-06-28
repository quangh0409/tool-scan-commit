"""
Build DÙNG CHUNG 1 commit cho FindSecBugs/Sonar (CodeQL tự build có-trace riêng — xem codeql.py).

Chạy Maven trong Docker, mount clone + cache .m2 dùng chung (tránh tải lại dependency mỗi commit).
⚠️ PoC: image/JDK/lệnh build sẽ tinh chỉnh theo train-ticket (Java 8). Build FAIL là DỮ LIỆU
(ctx.ok=False + error), KHÔNG raise — runner ghi 'build_failed' rồi bỏ commit.
"""
from __future__ import annotations

import shlex
import time
from pathlib import Path

from .. import config
from ..tools.base import docker_run
from .base import BuildContext


def _m2_cache() -> Path:
    d = config.WORK_DIR / ".m2cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_commit(clone_dir: Path, commit_id: str, repo: str) -> BuildContext:
    ctx = BuildContext(commit_id=commit_id, repo=repo, clone_dir=clone_dir)
    t0 = time.time()
    proc = docker_run([
        "run", "--rm",
        "-v", f"{clone_dir}:/work",
        "-v", f"{_m2_cache()}:/root/.m2",
        "-w", "/work",
        config.MAVEN_IMAGE,
        "sh", "-c", config.MAVEN_BUILD_CMD,
    ], timeout=config.BUILD_TIMEOUT)
    ctx.duration_sec = round(time.time() - t0, 1)

    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-500:]
        ctx.ok = False
        ctx.error = f"mvn rc={proc.returncode}: {tail}"
        return ctx

    # gom các thư mục target/classes (đầu vào cho FindSecBugs/Sonar)
    ctx.classes_dirs = sorted(p for p in clone_dir.glob("**/target/classes") if p.is_dir())
    ctx.ok = True
    return ctx
