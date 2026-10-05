"""
Build DÙNG CHUNG 1 commit cho FindSecBugs/Sonar (CodeQL tự build có-trace riêng — xem codeql.py).

Chỉ build MODULE BỊ ĐỤNG + dependency (`-pl <mods> -am`) thay vì cả 43 module — PoC xác nhận
service+dep ~13s cache ấm (vs build full nhiều phút). Cache .m2 dùng chung (commit đầu tải deps,
sau nhanh). Build FAIL là DỮ LIỆU (ctx.ok=False + error), KHÔNG raise.
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

from .. import config, enumerate_commits as enm
from ..tools.base import classify_failure, docker_run
from .base import BuildContext, run_as_user

# JDK khai trong pom: <java.version>17</>, <maven.compiler.release|target|source>1.8</>
_JAVA_VER_RE = re.compile(
    r"<(?:java\.version|maven\.compiler\.(?:release|target|source))>\s*(?:1\.)?(\d+)\s*<",
    re.IGNORECASE)
_JDK_AVAILABLE = (8, 11, 17, 21)   # tag temurin có sẵn trên Docker Hub


M2_VOLUME_NAME = "secjit-m2"          # tên Docker named volume khi ORCH_M2_VOLUME=1
_M2_VOLUME_READY: set[str] = set()      # volume đã `docker volume create/inspect` trong tiến trình này


def _m2_cache() -> "Path | str":
    """Nguồn mount cho `/m2` (dùng chung build/CodeQL/Sonar: `-v {_m2_cache()}:/m2`).

    - `ORCH_M2_VOLUME` rỗng hoặc `0` (mặc định): bind mount thư mục `WORK_DIR/.m2cache` (hành vi cũ).
    - `ORCH_M2_VOLUME=1`: Docker **named volume** `secjit-m2` (`docker volume create` nếu chưa có) — nhanh hơn
      bind mount trên Windows/WSL2 và không lệ thuộc file-sharing ổ đĩa. Giá trị khác `0/1` = tên volume tuỳ ý.
    - Không tạo được volume (daemon tắt…) -> cảnh báo và quay về bind mount để build vẫn chạy.
    """
    v = (config.M2_VOLUME or "").strip()
    if v in ("", "0"):
        d = config.WORK_DIR / ".m2cache"
        d.mkdir(parents=True, exist_ok=True)
        return d
    name = M2_VOLUME_NAME if v == "1" else v
    if name not in _M2_VOLUME_READY:
        try:
            ins = docker_run(["volume", "inspect", name], timeout=30)
            if ins.returncode != 0:
                cr = docker_run(["volume", "create", "--label", "orch.m2=1", name], timeout=60)
                if cr.returncode != 0:
                    raise RuntimeError((cr.stderr or cr.stdout or "").strip()[:200])
        except (OSError, subprocess.SubprocessError, RuntimeError) as e:
            print(f"[m2] CẢNH BÁO: không tạo được volume {name} ({e}) -> dùng bind mount .m2cache", file=sys.stderr)
            d = config.WORK_DIR / ".m2cache"
            d.mkdir(parents=True, exist_ok=True)
            return d
        _M2_VOLUME_READY.add(name)
    return name


def changed_modules(clone_dir: Path, commit_id: str) -> list[str]:
    """Module Maven mà commit chạm tới -> để `-pl` (đường dẫn tương đối, mvn chấp nhận).

    Leo từ file bị đổi lên POM GẦN NHẤT (không phải thư mục cấp 1): monorepo lồng nhau
    kiểu skywalking có cấp 1 (`oap-server`) chỉ là pom aggregator — `-pl` aggregator
    KHÔNG build con -> mvn rc=0 nhưng 0 classes, FindSecBugs/Sonar trắng tay.
    Repo phẳng (train-ticket/giraph): pom gần nhất = thư mục cấp 1, y hệt logic cũ."""
    ci = enm.get_commit_info(clone_dir, commit_id)
    mods = set()
    for f in ci.changed_files:
        p = Path(f).parent
        while p != Path("."):
            if (clone_dir / p / "pom.xml").exists():
                mods.add(p.as_posix())
                break
            p = p.parent
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
    """Build 1 commit. KHÔNG raise: kết quả nằm ở ctx.status (CONTRACTS §1):
      ok           build xong, có classes.
      skipped      0 module Java bị đụng (docs/yml) -> KHÔNG build, tool đắt KHÔNG chạy, KHÔNG verified.
      build_failed mvn rc≠0 vì dữ liệu (dependency mất, compile lỗi).
      infra_error  Docker không kết nối / đĩa đầy (rc 125/127, stderr khớp INFRA_PATTERNS).
      tool_timeout mvn vượt BUILD_TIMEOUT.
    """
    ctx = BuildContext(commit_id=commit_id, repo=repo, clone_dir=clone_dir)
    mods = changed_modules(clone_dir, commit_id)
    ctx.modules = mods
    if not mods:
        # commit KHÔNG đụng module Java nào (vd chỉ docs/yml) -> không có gì để build/analyze.
        # KHÔNG full-build cả 43 module (rất chậm). status=skipped: tool đắt KHÔNG chạy và commit
        # KHÔNG được tính verified-clean (REVIEW D1 / TC-16).
        ctx.ok = False
        ctx.status = "skipped"
        ctx.error = "0 module Java bị đụng (không build, không phân tích)"
        return ctx
    pl = ["-pl", ",".join(mods), "-am"]
    image = maven_image_for(clone_dir, commit_id)
    ctx.image = image

    t0 = time.time()
    # Chạy maven AS CURRENT UID (không sinh file root mà orchestrator non-root xoá không được
    # -> tránh kẹt clone-pool). HOME=/tmp + repo.local trong cache uid-owned.
    try:
        proc = docker_run([
            "run", "--rm",
            *run_as_user(),
            "-e", "HOME=/tmp",
            "-v", f"{clone_dir}:/work",
            "-v", f"{_m2_cache()}:/m2",
            "-w", "/work",
            image,
            "mvn", *config.MAVEN_GOALS.split(), "-Dmaven.repo.local=/m2/repository", *pl,
        ], timeout=config.BUILD_TIMEOUT)
    except subprocess.TimeoutExpired:
        ctx.duration_sec = round(time.time() - t0, 1)
        ctx.ok = False
        ctx.status = "tool_timeout"
        ctx.error = f"mvn quá {config.BUILD_TIMEOUT}s (mods={mods}, image={image})"
        return ctx
    except FileNotFoundError as e:      # không có binary docker
        ctx.ok = False
        ctx.status = "infra_error"
        ctx.error = f"không chạy được docker: {e}"
        return ctx
    ctx.duration_sec = round(time.time() - t0, 1)

    if proc.returncode != 0:
        # lỗi thật của mvn nằm ở STDOUT ([ERROR]...); stderr thường chỉ có nhiễu entrypoint
        # (vd "mkdir /root: Permission denied") -> ưu tiên dòng [ERROR] stdout, kèm stderr ngắn.
        err_lines = [l for l in (proc.stdout or "").splitlines()
                     if "[ERROR]" in l or "[FATAL]" in l]
        tail = ("\n".join(err_lines)[-500:] if err_lines
                else ((proc.stdout or "")[-300:] + (proc.stderr or "")[-200:]))
        ctx.ok = False
        # Docker tắt / đĩa đầy -> infra_error (KHÔNG phải dữ liệu, commit về pending — REVIEW D2/TC-10)
        ctx.status = classify_failure(proc.returncode, proc.stderr, proc.stdout) or "build_failed"
        ctx.error = f"mvn rc={proc.returncode} (mods={mods or 'full'}, image={image}): {tail}"
        return ctx

    # gom target/classes của module vừa build (đầu vào cho FindSecBugs/Sonar)
    ctx.classes_dirs = sorted(p for p in clone_dir.glob("**/target/classes") if p.is_dir())
    ctx.ok = True
    ctx.status = "ok"
    return ctx
