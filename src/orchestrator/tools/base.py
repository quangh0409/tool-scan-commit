"""
Interface chung cho tool wrapper (Tầng ②/④).

Mỗi tool chạy trong Docker. Wrapper chịu trách nhiệm:
  1. dựng lệnh docker,
  2. chạy trên checkout của 1 commit (hoặc trên diff),
  3. parse output thô -> list[RawFinding] (đã validate: có cwe + s_line).

Lưu ý môi trường: nếu tiến trình chưa thuộc nhóm `docker` (xem CLAUDE.md gotcha),
đặt ORCH_DOCKER_SG=1 để tự bọc lệnh qua `sg docker -c "..."`.

MỌI `docker run` tự gắn `--label orch.run=<run_id>` (CONTRACTS §3/§7) để `stop-cleanup` dọn được
container của đúng run (TC-09). Phân loại lỗi hạ tầng (CONTRACTS §1 `infra_error`): rc 125/127 hoặc
stderr/stdout khớp INFRA_PATTERNS.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import PurePosixPath, Path

from .. import progress
from ..schema import RawFinding

# tiền tố mount container thường gặp, cần bóc để khớp path git của diff
_MOUNT_PREFIXES = ("/src/", "/repo/", "/code/", "/path/")

# Dấu hiệu lỗi HẠ TẦNG (không phải dữ liệu) trong output docker — CONTRACTS §1.
INFRA_PATTERNS = (
    "cannot connect to the docker daemon",
    "error during connect",
    "dockerdesktoplinuxengine",
    "no space left",
    "disk is full",
    "database or disk is full",
    "is the docker daemon running",
    "docker: command not found",
    "executable file not found",   # 127 từ shell khi thiếu `docker`
)
INFRA_RCS = (125, 127)
_INFRA_RE = re.compile("|".join(re.escape(p) for p in INFRA_PATTERNS), re.IGNORECASE)


def is_infra_text(text: str | None) -> bool:
    """True nếu đoạn text (stderr/stdout/message exception) chứa dấu hiệu lỗi hạ tầng."""
    return bool(text) and bool(_INFRA_RE.search(text))


def classify_failure(returncode: int | None, stderr: str | None = None,
                     stdout: str | None = None) -> str | None:
    """-> 'infra_error' nếu rc 125/127 hoặc output khớp INFRA_PATTERNS; None nếu không phải infra.
    (Gọi KHI đã biết lệnh thất bại; rc=0 vẫn có thể là infra nếu stderr báo đĩa đầy.)"""
    if returncode in INFRA_RCS:
        return "infra_error"
    if is_infra_text(stderr) or is_infra_text(stdout):
        return "infra_error"
    return None


def canon_path(p: str) -> str:
    """Chuẩn hoá path từ output tool về path git (khớp key của get_file_diffs).

    Bóc tiền tố mount (/src/, /repo/...), './' và '/' đầu. VD '/src/svc/A.java' -> 'svc/A.java'.
    """
    if not p:
        return ""
    p = p.replace("\\", "/")
    for pref in _MOUNT_PREFIXES:
        if p.startswith(pref):
            p = p[len(pref):]
            break
    p = p.lstrip("/")
    if p.startswith("./"):
        p = p[2:]
    return str(PurePosixPath(p))


def run_label_args() -> list[str]:
    """`--label orch.run=<run_id>` cho docker run (run_id từ progress/ORCH_RUN_ID)."""
    return ["--label", f"orch.run={progress.run_id()}"]


def docker_run(args: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    """Chạy `docker <args>` (binary từ env ORCH_DOCKER_BIN, mặc định `docker`; vd podman / đường dẫn đầy đủ),
    tự bọc `sg docker -c` nếu ORCH_DOCKER_SG=1.
    args bắt đầu bằng "run" -> tự chèn `--label orch.run=<run_id>` ngay sau "run"."""
    args = list(args)
    if args and args[0] == "run" and "orch.run=" not in " ".join(args):
        args = [args[0], *run_label_args(), *args[1:]]
    cmd = [os.environ.get("ORCH_DOCKER_BIN") or "docker", *args]
    if os.environ.get("ORCH_DOCKER_SG") == "1":
        cmd = ["sg", "docker", "-c", " ".join(shlex.quote(c) for c in cmd)]
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout)


def docker_available() -> bool:
    return shutil.which("docker") is not None


def image_digest(image: str) -> str | None:
    """RepoDigest của image (để ghi run_meta tái lập). None nếu chưa pull / không có docker."""
    if not image or not docker_available():
        return None
    try:
        proc = docker_run(["image", "inspect", image,
                           "--format", "{{index .RepoDigests 0}}"], timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    out = (proc.stdout or "").strip()
    return out or None


def docker_version() -> str | None:
    """Phiên bản Docker Engine (server) cho run_manifest; None nếu không có docker/daemon."""
    if not docker_available():
        return None
    try:
        proc = docker_run(["version", "--format", "{{.Server.Version}}"], timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    out = (proc.stdout or "").strip()
    return out if proc.returncode == 0 and out else None


def orchestrator_git_sha() -> str | None:
    """`git rev-parse HEAD` của repo tool (tái lập); None nếu không phải git checkout."""
    root = Path(__file__).resolve().parents[3]
    try:
        proc = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                              capture_output=True, text=True, errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    out = (proc.stdout or "").strip()
    return out if proc.returncode == 0 and re.fullmatch(r"[0-9a-f]{7,40}", out) else None


def app_version() -> str:
    return os.environ.get("SECJIT_APP_VERSION", "dev")


class ToolWrapper(ABC):
    name: str = "base"
    tier: str = "cheap"  # "cheap" (source-only) | "expensive" (cần build)
    image: str = ""      # Docker image (để lấy digest + version cho run_meta)

    def version(self) -> str | None:
        """Phiên bản tool (ghi run_meta). Mặc định None; wrapper override nếu lấy được."""
        return None

    def digest(self) -> str | None:
        return image_digest(self.image) if self.image else None

    @abstractmethod
    def scan(self, repo_dir: Path, commit_id: str, repo: str,
             changed_files: list[str]) -> list[RawFinding]:
        """Quét DIFF/các file thay đổi của 1 commit (đã checkout) -> findings đã validate.

        changed_files: đường dẫn (theo git) các file code đã đổi & còn tồn tại trên đĩa.
        Quét trên diff thay vì toàn cây: vừa rẻ (phễu), vừa đúng ngữ nghĩa
        (lỗi gắn với commit này, không phải nợ cũ).
        """
        ...

    def _finalize(self, findings: list[RawFinding]) -> list[RawFinding]:
        """Validate đồng loạt (ép cwe + s_line). Bỏ finding không hợp lệ kèm cảnh báo."""
        ok: list[RawFinding] = []
        for f in findings:
            try:
                ok.append(f.validate())
            except ValueError as e:
                # finding không gán được CWE/s_line thì không đưa vào dataset
                print(f"[{self.name}] bỏ finding không hợp lệ: {e}")
        return ok
