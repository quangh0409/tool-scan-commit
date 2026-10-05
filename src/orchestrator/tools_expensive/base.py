"""
Khung tool TẦNG ĐẮT. Khác tầng rẻ: tool nhận 1 BuildContext (đã build sẵn) thay vì
quét source thuần. Build chạy 1 LẦN/commit rồi 3 tool dùng chung (Model A).

Trạng thái (CONTRACTS §1): BuildContext.status ∈ ok | skipped | build_failed | infra_error | tool_timeout.
Tool raise ToolError (crash/parse lỗi/XML 0 byte) -> runner ghi `tool_error`; message chứa dấu hiệu
Docker/đĩa -> runner nâng thành `infra_error`.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from ..schema import RawFinding


class ToolError(RuntimeError):
    """Tool đắt crash / không ra output / parse lỗi (status `tool_error`)."""


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
    status: str = "ok"                     # ok | skipped | build_failed | infra_error | tool_timeout
    image: str | None = None               # image maven đã dùng thật (run_meta.tools_json)
    modules: list[str] = field(default_factory=list)

    @property
    def skipped(self) -> bool:
        return self.status == "skipped"


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
