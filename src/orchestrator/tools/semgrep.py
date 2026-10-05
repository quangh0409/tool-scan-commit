"""
Wrapper Semgrep (Tầng ② — source-only, ra SARIF/CWE sẵn).
Dùng ruleset 'p/default' + 'p/secrets'.
Docker image: semgrep/semgrep:latest

Diff-scoped NHƯNG KHÔNG truyền từng file vào argv: Windows giới hạn dòng lệnh ~32 k ký tự → commit
nhiều file nổ `[WinError 206] The filename or extension is too long` (Run A 2026-10-05). Thay vào đó
copy các file đổi vào thư mục tạm GIỮ CẤU TRÚC (như bearer/horusec) rồi `semgrep scan /src`.
Ghi `.semgrepignore` rỗng vào thư mục tạm để semgrep KHÔNG áp bộ ignore mặc định (tests/, *_test…)
— giữ đúng ngữ nghĩa cũ khi truyền file tường minh. Path output `/src/<rel>` → canon_path → path repo.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from ..schema import RawFinding, normalize_cwe
from .base import ToolWrapper, canon_path, docker_run

IMAGE = "semgrep/semgrep:latest"
# p/default phủ rộng (đã verify bắt CWE-89, hỗ trợ Java/Python/JS); p/secrets cho secret
CONFIGS = ["p/default", "p/secrets"]


def _extract_cwe(meta: dict) -> list[str]:
    """Semgrep để CWE trong extra.metadata.cwe (str | list)."""
    raw = meta.get("cwe") or meta.get("CWE") or []
    if isinstance(raw, str):
        raw = [raw]
    return [normalize_cwe(c) for c in raw] if raw else []


def stage_changed_files(repo_dir: Path, changed_files: list[str], prefix: str) -> tuple[Path, int]:
    """Copy các file đổi (còn tồn tại) vào temp dir giữ cấu trúc; mở quyền đọc cho user non-root
    trong container. Trả (temp_dir, số file đã copy). Người gọi phải rmtree."""
    proj = Path(tempfile.mkdtemp(prefix=prefix))
    n = 0
    for rel in changed_files:
        src = repo_dir / rel
        if not src.is_file():
            continue
        dst = proj / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        n += 1
    for root, _dirs, files in os.walk(proj):
        try:
            os.chmod(root, 0o755)
            for f in files:
                os.chmod(os.path.join(root, f), 0o644)
        except OSError:
            pass
    return proj, n


class SemgrepWrapper(ToolWrapper):
    name = "semgrep"
    tier = "cheap"
    image = IMAGE

    def version(self) -> str | None:
        proc = docker_run(["run", "--rm", IMAGE, "semgrep", "--version"], timeout=60)
        return (proc.stdout or "").strip().splitlines()[0] if proc.stdout.strip() else None

    def scan(self, repo_dir: Path, commit_id: str, repo: str,
             changed_files: list[str], raw_out: list | None = None) -> list[RawFinding]:
        if not changed_files:
            return []
        proj, n = stage_changed_files(repo_dir, changed_files, "semgrep_proj_")
        try:
            if n == 0:
                return []
            # .semgrepignore rỗng -> không áp ignore mặc định (giữ ngữ nghĩa "quét đúng các file đã đổi")
            (proj / ".semgrepignore").write_text("", encoding="utf-8")
            cfg_args = []
            for c in CONFIGS:
                cfg_args += ["--config", c]
            # argv NGẮN, không phụ thuộc số file (WinError 206); quét cả thư mục tạm = đúng tập file đổi
            proc = docker_run([
                "run", "--rm", "-v", f"{proj}:/src", IMAGE,
                "semgrep", "scan", *cfg_args, "--json", "--quiet", "/src",
            ], timeout=900)
        finally:
            shutil.rmtree(proj, ignore_errors=True)
        if raw_out is not None:
            raw_out.append(("json", proc.stdout or ""))
        try:
            data = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            print(f"[semgrep] parse JSON lỗi @ {commit_id[:8]}")
            return []

        findings: list[RawFinding] = []
        for r in data.get("results", []):
            meta = r.get("extra", {}).get("metadata", {})
            cwe = _extract_cwe(meta)
            if not cwe:
                continue  # không CWE -> bỏ (yêu cầu bắt buộc)
            start = r.get("start", {}).get("line", 0)
            if not start:
                continue
            findings.append(RawFinding(
                repo=repo, commit_id=commit_id,
                file_path=canon_path(r.get("path", "")),
                s_line=int(start),
                e_line=r.get("end", {}).get("line"),
                cwe=cwe,
                tool=self.name,
                rule_id=r.get("check_id", ""),
                severity=(r.get("extra", {}).get("severity") or "").upper() or None,
                owasp=(meta.get("owasp") or [None])[0] if isinstance(meta.get("owasp"), list) else meta.get("owasp"),
                message=r.get("extra", {}).get("message"),
                code_snippet=r.get("extra", {}).get("lines"),
            ))
        return self._finalize(findings)
