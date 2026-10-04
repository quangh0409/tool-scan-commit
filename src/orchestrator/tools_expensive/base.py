"""
Khung tool TẦNG ĐẮT. Khác tầng rẻ: tool nhận 1 BuildContext (đã build sẵn) thay vì
quét source thuần. Build chạy 1 LẦN/commit rồi 3 tool dùng chung (Model A).
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from ..schema import RawFinding


def run_as_user() -> list[str]:
    """Flag `-u uid:gid` cho `docker run` để file sinh ra thuộc user hiện tại (tránh file
    root kẹt clone-pool trên VM Linux). Windows không có getuid và Docker Desktop đã map
    quyền file host -> trả [] (không truyền -u)."""
    if hasattr(os, "getuid"):
        return ["-u", f"{os.getuid()}:{os.getgid()}"]
    return []


@dataclass
class BuildContext:
    """Kết quả build 1 commit — đầu vào dùng chung cho các tool đắt."""
    commit_id: str
    repo: str
    clone_dir: Path
    ok: bool = False
    codeql_db: Path | None = None          # DB CodeQL (nếu đã tạo)
    classes_dirs: list[Path] = field(default_factory=list)  # target/classes (FindSecBugs/Sonar)
    duration_sec: float = 0.0
    error: str | None = None


class ExpensiveTool(ABC):
    name: str = "base"
    tier: str = "expensive"
    image: str = ""

    @abstractmethod
    def scan(self, ctx: BuildContext) -> list[RawFinding]:
        """Phân tích trên build đã có -> findings đã validate (cwe + s_line)."""
        ...

    def _finalize(self, findings: list[RawFinding]) -> list[RawFinding]:
        ok: list[RawFinding] = []
        for f in findings:
            try:
                ok.append(f.validate())
            except ValueError as e:
                print(f"[{self.name}] bỏ finding không hợp lệ: {e}")
        return ok
