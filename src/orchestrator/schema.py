"""
Schema trung tâm của dataset.

Hai cấp:
  - RawFinding   : 1 tool báo cáo 1 vấn đề trên 1 commit (trước consensus).
  - DatasetRow   : 1 dòng output cuối (sau bỏ phiếu) — theo §4 TOOL_IDEA_CONTEXT.md.

YÊU CẦU BẮT BUỘC (người dùng chốt): mỗi finding PHẢI có
  - `cwe`     : danh sách CWE-class (không rỗng).
  - `s_line`  : số dòng bắt đầu gây lỗi/rủi ro bảo mật (> 0, không null).
Hàm validate() ép 2 ràng buộc này; vi phạm -> raise.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class RawFinding:
    """Một phát hiện thô từ MỘT tool, trên MỘT commit (chưa qua consensus)."""

    # --- định danh commit ---
    repo: str
    commit_id: str

    # --- vị trí lỗi (BẮT BUỘC: file + s_line + cwe) ---
    file_path: str            # đã chuẩn hoá tương đối từ gốc repo
    s_line: int               # dòng bắt đầu gây rủi ro — BẮT BUỘC > 0
    cwe: list[str]            # CWE-class — BẮT BUỘC không rỗng
    e_line: Optional[int] = None
    function: Optional[str] = None
    # các dòng cụ thể gây lỗi/rủi ro (BẮT BUỘC không rỗng; default = dải s_line..e_line)
    s_detail_line: list[int] = field(default_factory=list)

    # --- nhãn của tool ---
    tool: str = ""            # "gitleaks" | "semgrep" | ...
    rule_id: str = ""
    severity: Optional[str] = None
    owasp: Optional[str] = None
    message: Optional[str] = None
    code_snippet: Optional[str] = None

    def validate(self) -> "RawFinding":
        if not self.cwe:
            raise ValueError(
                f"[schema] finding thiếu CWE (BẮT BUỘC): {self.tool} {self.rule_id} "
                f"@ {self.file_path}:{self.s_line}"
            )
        if self.s_line is None or self.s_line <= 0:
            raise ValueError(
                f"[schema] finding thiếu/sai s_line (BẮT BUỘC > 0): {self.tool} "
                f"{self.rule_id} @ {self.file_path}"
            )
        # chuẩn hoá CWE về dạng 'CWE-89'
        self.cwe = [normalize_cwe(c) for c in self.cwe]
        # s_detail_line: nếu tool không cung cấp -> suy ra dải s_line..e_line
        if not self.s_detail_line:
            end = self.e_line if (self.e_line and self.e_line >= self.s_line) else self.s_line
            self.s_detail_line = list(range(self.s_line, end + 1))
        return self

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class DatasetRow:
    """Một dòng output cuối — §4 TOOL_IDEA_CONTEXT.md (sau consensus)."""

    # commit-level
    repo: str
    commit_id: str
    parent_commit: Optional[str] = None
    commit_message: Optional[str] = None
    author_date: Optional[str] = None

    # vị trí (BẮT BUỘC: file + s_line + cwe)
    file_path: str = ""
    s_line: int = 0
    e_line: Optional[int] = None
    function: Optional[str] = None
    s_detail_line: list[int] = field(default_factory=list)  # các dòng cụ thể gây lỗi

    # ngữ cảnh diff + file
    diff_parsed: dict = field(default_factory=dict)  # {"added":[[ln,txt]],"deleted":[[ln,txt]]}
    code_before_url: Optional[str] = None            # permalink GitHub @ parent_commit
    code_after_url: Optional[str] = None             # permalink GitHub @ commit_id
    code_before: Optional[str] = None                # toàn văn file trước (tuỳ chọn, có thể nặng)
    code_after: Optional[str] = None                 # toàn văn file sau (tuỳ chọn, có thể nặng)

    # nhãn cụm
    tool: Optional[str] = None          # tool đại diện (hoặc gộp)
    rule_id: Optional[str] = None
    severity: Optional[str] = None
    cwe: list[str] = field(default_factory=list)
    owasp: Optional[str] = None
    cve: Optional[str] = None           # enrichment, gần như luôn null

    # diff metadata
    lines_added: Optional[int] = None
    lines_deleted: Optional[int] = None
    code_snippet: Optional[str] = None

    # consensus
    n_tools_ran: int = 0
    n_tools_agree: int = 0
    agreeing_tools: list[str] = field(default_factory=list)
    agreement_ratio: float = 0.0

    confidence: float = 0.0
    silver_label: Optional[str] = None  # nhãn bạc: vd "VULN" / "CLEAN"

    def validate(self) -> "DatasetRow":
        if not self.cwe:
            raise ValueError(f"[schema] DatasetRow thiếu CWE @ {self.file_path}:{self.s_line}")
        if self.s_line is None or self.s_line <= 0:
            raise ValueError(f"[schema] DatasetRow thiếu s_line @ {self.file_path}")
        return self

    def as_dict(self) -> dict:
        return asdict(self)


def normalize_cwe(raw: str | int) -> str:
    """'89' | 89 | 'CWE-89' | 'cwe89' -> 'CWE-89'."""
    s = str(raw).strip().upper().replace("CWE", "").lstrip("-_ ")
    digits = "".join(ch for ch in s if ch.isdigit())
    return f"CWE-{digits}" if digits else "CWE-UNKNOWN"
