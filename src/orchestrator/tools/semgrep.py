"""
Wrapper Semgrep (Tầng ② — source-only, ra SARIF/CWE sẵn).
Dùng ruleset 'p/security-audit' + 'p/secrets' cho pilot.
Docker image: semgrep/semgrep:latest
"""
from __future__ import annotations

import json
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


class SemgrepWrapper(ToolWrapper):
    name = "semgrep"
    tier = "cheap"
    image = IMAGE

    def version(self) -> str | None:
        proc = docker_run(["run", "--rm", IMAGE, "semgrep", "--version"], timeout=60)
        return (proc.stdout or "").strip().splitlines()[0] if proc.stdout.strip() else None

    def scan(self, repo_dir: Path, commit_id: str, repo: str,
             changed_files: list[str]) -> list[RawFinding]:
        if not changed_files:
            return []
        cfg_args = []
        for c in CONFIGS:
            cfg_args += ["--config", c]
        # chỉ quét các file thay đổi (diff-scoped), không quét toàn cây
        targets = [f"/src/{f}" for f in changed_files]
        proc = docker_run([
            "run", "--rm", "-v", f"{repo_dir}:/src", IMAGE,
            "semgrep", "scan", *cfg_args, "--json", "--quiet", *targets,
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
