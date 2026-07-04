"""
Interface chung cho tool wrapper (Tầng ②/④).

Mỗi tool chạy trong Docker. Wrapper chịu trách nhiệm:
  1. dựng lệnh docker,
  2. chạy trên checkout của 1 commit (hoặc trên diff),
  3. parse output thô -> list[RawFinding] (đã validate: có cwe + s_line).

Lưu ý môi trường: nếu tiến trình chưa thuộc nhóm `docker` (xem CLAUDE.md gotcha),
đặt ORCH_DOCKER_SG=1 để tự bọc lệnh qua `sg docker -c "..."`.
"""
from __future__ import annotations

import os
import shlex
import subprocess
from abc import ABC, abstractmethod
from pathlib import PurePosixPath, Path

from ..schema import RawFinding

# tiền tố mount container thường gặp, cần bóc để khớp path git của diff
_MOUNT_PREFIXES = ("/src/", "/repo/", "/code/", "/path/")


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


def docker_run(args: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    """Chạy `docker <args>`, tự bọc `sg docker -c` nếu ORCH_DOCKER_SG=1."""
    cmd = ["docker", *args]
    if os.environ.get("ORCH_DOCKER_SG") == "1":
        cmd = ["sg", "docker", "-c", " ".join(shlex.quote(c) for c in cmd)]
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout)


def image_digest(image: str) -> str | None:
    """RepoDigest của image (để ghi run_meta tái lập). None nếu chưa pull."""
    proc = docker_run(["image", "inspect", image,
                       "--format", "{{index .RepoDigests 0}}"], timeout=60)
    out = (proc.stdout or "").strip()
    return out or None


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
