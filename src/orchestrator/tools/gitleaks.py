"""
Wrapper gitleaks (Tầng ② — bắt secret). Output JSON -> RawFinding.
gitleaks không tự gán CWE -> ta map cứng về CWE-798 (hardcoded credentials).
Docker image: zricethezav/gitleaks:latest
"""
from __future__ import annotations

import json
from pathlib import Path

from ..schema import RawFinding
from .base import ToolWrapper, canon_path, docker_run

IMAGE = "zricethezav/gitleaks:latest"
SECRET_CWE = ["CWE-798"]  # Use of Hard-coded Credentials


class GitleaksWrapper(ToolWrapper):
    name = "gitleaks"
    tier = "cheap"
    image = IMAGE

    def version(self) -> str | None:
        proc = docker_run(["run", "--rm", IMAGE, "version"], timeout=60)
        return (proc.stdout or "").strip() or None

    def scan(self, repo_dir: Path, commit_id: str, repo: str,
             changed_files: list[str]) -> list[RawFinding]:
        # git-mode: chỉ quét DIFF của đúng commit này (secret được THÊM vào),
        # không quét lại toàn cây mỗi commit -> rẻ + đúng ngữ nghĩa.
        proc = docker_run([
            "run", "--rm", "-v", f"{repo_dir}:/repo", IMAGE,
            "detect", "--source", "/repo",
            "--log-opts", f"-1 --no-merges {commit_id}",
            "--report-format", "json", "--report-path", "/dev/stdout",
            "--exit-code", "0",
        ])
        findings: list[RawFinding] = []
        try:
            data = json.loads(proc.stdout or "[]")
        except json.JSONDecodeError:
            print(f"[gitleaks] parse JSON lỗi @ {commit_id[:8]}")
            return []
        for item in data:
            line = item.get("StartLine") or item.get("Line") or 0
            if not line:
                continue
            findings.append(RawFinding(
                repo=repo, commit_id=commit_id,
                file_path=canon_path(item.get("File", "")),
                s_line=int(line),
                e_line=item.get("EndLine"),
                cwe=list(SECRET_CWE),
                tool=self.name,
                rule_id=item.get("RuleID", "secret"),
                severity="HIGH",
                message=item.get("Description"),
                code_snippet=item.get("Match"),
            ))
        return self._finalize(findings)
