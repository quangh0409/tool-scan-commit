"""
Wrapper Bearer (Tầng ② — SAST source, CHỒNG PHỦ semgrep để có consensus code-vuln).
Bearer có gán CWE (cwe_ids). Quét TỪNG file đổi (diff-scoped); khi quét 1 file lẻ
Bearer trả filename='.', nên ta gán path = chính file đã truyền.
Output JSON: {severity: [ {id, cwe_ids, filename, line_number, title,...} ]}.
Docker image: bearer/bearer:latest
"""
from __future__ import annotations

import json
from pathlib import Path

from ..schema import RawFinding, normalize_cwe
from .base import ToolWrapper, docker_run

IMAGE = "bearer/bearer:latest"
_SEVERITIES = ("critical", "high", "medium", "low", "warning")


class BearerWrapper(ToolWrapper):
    name = "bearer"
    tier = "cheap"
    image = IMAGE

    def version(self) -> str | None:
        proc = docker_run(["run", "--rm", IMAGE, "version"], timeout=60)
        out = (proc.stdout or "") + (proc.stderr or "")
        return out.strip().splitlines()[0] if out.strip() else None

    def _scan_one(self, repo_dir: Path, commit_id: str, repo: str,
                  rel_path: str) -> list[RawFinding]:
        proc = docker_run([
            "run", "--rm", "-v", f"{repo_dir}:/src", IMAGE,
            "scan", f"/src/{rel_path}", "--format", "json", "--quiet",
            "--exit-code", "0",
        ], timeout=600)
        try:
            data = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            return []

        findings: list[RawFinding] = []
        for sev in _SEVERITIES:
            for item in data.get(sev, []):
                cwe = [normalize_cwe(c) for c in (item.get("cwe_ids") or [])]
                if not cwe:
                    continue  # bắt buộc có CWE
                line = item.get("line_number") or item.get("sink", {}).get("start") or 0
                if not line:
                    continue
                findings.append(RawFinding(
                    repo=repo, commit_id=commit_id,
                    file_path=rel_path,                 # gán path đã truyền (Bearer trả '.')
                    s_line=int(line),
                    e_line=item.get("sink", {}).get("end"),
                    cwe=cwe,
                    tool=self.name,
                    rule_id=item.get("id", ""),
                    severity=sev.upper(),
                    message=item.get("title"),
                    code_snippet=item.get("code_extract"),
                ))
        return findings

    def scan(self, repo_dir: Path, commit_id: str, repo: str,
             changed_files: list[str]) -> list[RawFinding]:
        out: list[RawFinding] = []
        for rel in changed_files:
            out += self._scan_one(repo_dir, commit_id, repo, rel)
        return self._finalize(out)
