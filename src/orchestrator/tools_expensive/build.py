"""
Build DÙNG CHUNG 1 commit cho FindSecBugs/Sonar (CodeQL tự build có-trace riêng — xem codeql.py).

Chỉ build MODULE BỊ ĐỤNG + dependency (`-pl <mods> -am`) thay vì cả 43 module — PoC xác nhận
service+dep ~13s cache ấm (vs build full nhiều phút). Cache .m2 dùng chung (commit đầu tải deps,
sau nhanh). Build FAIL là DỮ LIỆU (ctx.ok=False + error), KHÔNG raise.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from .. import config, enumerate_commits as enm
from ..tools.base import docker_run
from .base import BuildContext


def _m2_cache() -> Path:
    d = config.WORK_DIR / ".m2cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def changed_modules(clone_dir: Path, commit_id: str) -> list[str]:
    """Module top-level (thư mục có pom.xml) mà commit chạm tới -> để `-pl`."""
    ci = enm.get_commit_info(clone_dir, commit_id)
    mods = set()
    for f in ci.changed_files:
        top = f.split("/", 1)[0]
        if top and (clone_dir / top / "pom.xml").exists():
            mods.add(top)
    return sorted(mods)


def build_commit(clone_dir: Path, commit_id: str, repo: str) -> BuildContext:
    ctx = BuildContext(commit_id=commit_id, repo=repo, clone_dir=clone_dir)
    mods = changed_modules(clone_dir, commit_id)
    pl = ["-pl", ",".join(mods), "-am"] if mods else []   # rỗng -> build full (fallback)

    t0 = time.time()
    # Chạy maven AS CURRENT UID (không sinh file root mà orchestrator non-root xoá không được
    # -> tránh kẹt clone-pool). HOME=/tmp + repo.local trong cache uid-owned.
    proc = docker_run([
        "run", "--rm",
        "-u", f"{os.getuid()}:{os.getgid()}",
        "-e", "HOME=/tmp",
        "-v", f"{clone_dir}:/work",
        "-v", f"{_m2_cache()}:/m2",
        "-w", "/work",
        config.MAVEN_IMAGE,
        "mvn", *config.MAVEN_GOALS.split(), "-Dmaven.repo.local=/m2/repository", *pl,
    ], timeout=config.BUILD_TIMEOUT)
    ctx.duration_sec = round(time.time() - t0, 1)

    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-500:]
        ctx.ok = False
        ctx.error = f"mvn rc={proc.returncode} (mods={mods or 'full'}): {tail}"
        return ctx

    # gom target/classes của module vừa build (đầu vào cho FindSecBugs/Sonar)
    ctx.classes_dirs = sorted(p for p in clone_dir.glob("**/target/classes") if p.is_dir())
    ctx.ok = True
    return ctx
