"""
Wrapper Semgrep (Tầng ② — source-only, ra SARIF/CWE sẵn).
Dùng ruleset 'p/security-audit' + 'p/secrets' cho pilot.
Docker image: semgrep/semgrep:latest
"""
from __future__ import annotations

import json
from pathlib import Path

from ..schema import RawFinding, normalize_cwe
from .base import ToolWrapper, docker_run

IMAGE = "semgrep/semgrep:latest"
CONFIGS = ["p/security-audit", "p/secrets"]


def _extract_cwe(meta: dict) -> list[str]:
    """Semgrep để CWE trong extra.metadata.cwe (str | list)."""
    raw = meta.get("cwe") or meta.get("CWE") or []
    if isinstance(raw, str):
        raw = [raw]
    return [normalize_cwe(c) for c in raw] if raw else []


class SemgrepWrapper(ToolWrapper):
    name = "semgrep"
    tier = "cheap"

    def scan(self, repo_dir: Path, commit_id: str, repo: str) -> list[RawFinding]:
        cfg_args = []
        for c in CONFIGS:
            cfg_args += ["--config", c]
        proc = docker_run([
            "run", "--rm", "-v", f"{repo_dir}:/src", IMAGE,
            "semgrep", "scan", *cfg_args, "--json", "--quiet", "/src",
        ], timeout=900)
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
                file_path=r.get("path", "").removeprefix("/src/"),
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
