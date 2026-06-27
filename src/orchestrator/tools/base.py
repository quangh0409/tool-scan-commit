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
from pathlib import Path

from ..schema import RawFinding


def docker_run(args: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    """Chạy `docker <args>`, tự bọc `sg docker -c` nếu ORCH_DOCKER_SG=1."""
    cmd = ["docker", *args]
    if os.environ.get("ORCH_DOCKER_SG") == "1":
        cmd = ["sg", "docker", "-c", " ".join(shlex.quote(c) for c in cmd)]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


class ToolWrapper(ABC):
    name: str = "base"
    tier: str = "cheap"  # "cheap" (source-only) | "expensive" (cần build)

    @abstractmethod
    def scan(self, repo_dir: Path, commit_id: str, repo: str) -> list[RawFinding]:
        """Quét 1 commit (đã checkout) -> findings đã validate."""
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
