"""
Build DÙNG CHUNG 1 commit cho FindSecBugs/Sonar (CodeQL tự build có-trace riêng — xem codeql.py).

Chỉ build MODULE BỊ ĐỤNG + dependency (`-pl <mods> -am`) thay vì cả 43 module — PoC xác nhận
service+dep ~13s cache ấm (vs build full nhiều phút). Cache .m2 dùng chung (commit đầu tải deps,
sau nhanh). Build FAIL là DỮ LIỆU (ctx.ok=False + error), KHÔNG raise.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

from .. import config, enumerate_commits as enm
from ..tools.base import docker_run
from .base import BuildContext

# JDK khai trong pom: <java.version>17</>, <maven.compiler.release|target|source>1.8</>
_JAVA_VER_RE = re.compile(
    r"<(?:java\.version|maven\.compiler\.(?:release|target|source))>\s*(?:1\.)?(\d+)\s*<",
    re.IGNORECASE)
_JDK_AVAILABLE = (8, 11, 17, 21)   # tag temurin có sẵn trên Docker Hub


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


def detect_jdk(clone_dir: Path, commit_id: str) -> int | None:
    """JDK khai báo trong pom.xml GỐC tại commit (sha-scoped, không checkout).
    '1.8'/'8' -> 8; làm tròn LÊN tag temurin gần nhất (9,10->11; 12-16->17; 18+->21).
    None nếu không có pom / không khai."""
    try:
        pom = enm._git(clone_dir, "show", f"{commit_id}:pom.xml")
    except subprocess.CalledProcessError:
        return None
    m = _JAVA_VER_RE.search(pom)
    if not m:
        return None
    v = int(m.group(1))
    return next((c for c in _JDK_AVAILABLE if v <= c), _JDK_AVAILABLE[-1])


def maven_image_for(clone_dir: Path, commit_id: str) -> str:
    """Image build cho commit: auto-detect JDK từ pom (bật mặc định) -> fallback MAVEN_IMAGE."""
    if config.JDK_AUTODETECT:
        jdk = detect_jdk(clone_dir, commit_id)
        if jdk:
            return config.JDK_IMAGE_TEMPLATE.format(jdk=jdk)
    return config.MAVEN_IMAGE


def build_commit(clone_dir: Path, commit_id: str, repo: str) -> BuildContext:
    ctx = BuildContext(commit_id=commit_id, repo=repo, clone_dir=clone_dir)
    mods = changed_modules(clone_dir, commit_id)
    if not mods:
        # commit KHÔNG đụng module Java nào (vd chỉ docs/yml) -> không có gì để build/analyze.
        # KHÔNG full-build cả 43 module (rất chậm). ok=True, classes rỗng -> FindSecBugs/Sonar bỏ qua.
        ctx.ok = True
        return ctx
    pl = ["-pl", ",".join(mods), "-am"]
    image = maven_image_for(clone_dir, commit_id)

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
        image,
        "mvn", *config.MAVEN_GOALS.split(), "-Dmaven.repo.local=/m2/repository", *pl,
    ], timeout=config.BUILD_TIMEOUT)
    ctx.duration_sec = round(time.time() - t0, 1)

    if proc.returncode != 0:
        # lỗi thật của mvn nằm ở STDOUT ([ERROR]...); stderr thường chỉ có nhiễu entrypoint
        # (vd "mkdir /root: Permission denied") -> ưu tiên dòng [ERROR] stdout, kèm stderr ngắn.
        err_lines = [l for l in (proc.stdout or "").splitlines()
                     if "[ERROR]" in l or "[FATAL]" in l]
        tail = ("\n".join(err_lines)[-500:] if err_lines
                else ((proc.stdout or "")[-300:] + (proc.stderr or "")[-200:]))
        ctx.ok = False
        ctx.error = f"mvn rc={proc.returncode} (mods={mods or 'full'}, image={image}): {tail}"
        return ctx

    # gom target/classes của module vừa build (đầu vào cho FindSecBugs/Sonar)
    ctx.classes_dirs = sorted(p for p in clone_dir.glob("**/target/classes") if p.is_dir())
    ctx.ok = True
    return ctx
