"""
Wrapper trufflehog (Tầng ② — bắt secret, CHỒNG PHỦ gitleaks để có consensus).

⚠️ ĐÚNG ĐẮN — quét ĐÚNG 1 commit:
  trufflehog git-mode quét theo MỌI REF (nhánh), KHÔNG theo HEAD. Nếu chỉ dùng
  `--since-commit <SHA>~1`, nó quét cả dải <SHA>..<tip-nhánh> rồi ta gán nhầm hết
  về commit đang xét (đã kiểm thực nghiệm: thấy secret của commit HẬU DUỆ lọt vào).
  Cách đúng = `--branch <SHA>` (giới hạn lịch sử reachable từ chính SHA) KÈM
  `--since-commit <SHA>~1` (chặn dưới) => quét đúng DIFF của 1 commit SHA.

Output JSON-Lines (mỗi dòng 1 object), KHÔNG phải 1 mảng.
trufflehog không gán CWE -> map cứng CWE-798 (giống gitleaks).
Docker image: trufflesecurity/trufflehog:latest
"""
from __future__ import annotations

import json
from pathlib import Path

from ..schema import RawFinding
from .base import ToolWrapper, canon_path, docker_run

IMAGE = "trufflesecurity/trufflehog:latest"
SECRET_CWE = ["CWE-798"]  # Use of Hard-coded Credentials


class TrufflehogWrapper(ToolWrapper):
    name = "trufflehog"
    tier = "cheap"
    image = IMAGE

    def version(self) -> str | None:
        proc = docker_run(["run", "--rm", IMAGE, "--version"], timeout=60)
        # trufflehog in version ra stderr ("trufflehog 3.95.6")
        out = (proc.stdout or "") + (proc.stderr or "")
        return out.strip().splitlines()[0] if out.strip() else None

    def scan(self, repo_dir: Path, commit_id: str, repo: str,
             changed_files: list[str]) -> list[RawFinding]:
        # quét ĐÚNG 1 commit: --branch <SHA> giới hạn reachable-từ-SHA (loại hậu duệ),
        # --since-commit <SHA>~1 chặn dưới -> chỉ còn DIFF của chính SHA.
        proc = docker_run([
            "run", "--rm", "-v", f"{repo_dir}:/repo", IMAGE,
            "git", "file:///repo",
            "--branch", commit_id,
            "--since-commit", f"{commit_id}~1",
            "--json", "--no-update",
        ], timeout=600)

        findings: list[RawFinding] = []
        for ln in (proc.stdout or "").splitlines():
            ln = ln.strip()
            if not ln or not ln.startswith("{"):
                continue
            try:
                d = json.loads(ln)
            except json.JSONDecodeError:
                continue
            git = d.get("SourceMetadata", {}).get("Data", {}).get("Git", {})
            line = git.get("line") or 0
            if not line:
                continue
            findings.append(RawFinding(
                repo=repo, commit_id=commit_id,
                file_path=canon_path(git.get("file", "")),
                s_line=int(line),
                cwe=list(SECRET_CWE),
                tool=self.name,
                rule_id=d.get("DetectorName", "secret"),
                severity="HIGH" if d.get("Verified") else "MEDIUM",
                verified=bool(d.get("Verified")),
                message=f"{d.get('DetectorName')} (verified={d.get('Verified')})",
                code_snippet=d.get("Raw"),
            ))
        return self._finalize(findings)
