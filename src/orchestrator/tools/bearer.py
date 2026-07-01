"""
Wrapper Bearer (Tầng ② — SAST source, CHỒNG PHỦ semgrep để có consensus code-vuln).
Bearer có gán CWE (cwe_ids). Diff-scoped: copy các file đổi vào 1 temp dir (giữ cấu
trúc) rồi quét CẢ THƯ MỤC trong 1 container (tránh khởi động container mỗi-file).
Khi quét thư mục, Bearer trả `filename` là path tương đối -> khớp key diff.
Output JSON: {severity: [ {id, cwe_ids, filename, line_number, title,...} ]}.
Docker image: bearer/bearer:latest
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from ..schema import RawFinding, normalize_cwe
from .base import ToolWrapper, canon_path, docker_run

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

    def scan(self, repo_dir: Path, commit_id: str, repo: str,
             changed_files: list[str], raw_out: list | None = None) -> list[RawFinding]:
        if not changed_files:
            return []
        proj = Path(tempfile.mkdtemp(prefix="bearer_proj_"))
        try:
            for rel in changed_files:
                src = repo_dir / rel
                if not src.exists():
                    continue
                dst = proj / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

            # bearer chạy non-root trong container -> temp dir (mkdtemp=0700) phải mở đọc
            for root, dirs, files in os.walk(proj):
                os.chmod(root, 0o755)
                for f in files:
                    os.chmod(os.path.join(root, f), 0o644)

            proc = docker_run([
                "run", "--rm", "-v", f"{proj}:/src", IMAGE,
                "scan", "/src", "--format", "json", "--quiet", "--exit-code", "0",
            ], timeout=1800)
            if raw_out is not None:
                raw_out.append(("json", proc.stdout or ""))
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
                        file_path=canon_path(item.get("filename", "")),
                        s_line=int(line),
                        e_line=item.get("sink", {}).get("end"),
                        cwe=cwe,
                        tool=self.name,
                        rule_id=item.get("id", ""),
                        severity=sev.upper(),
                        message=item.get("title"),
                        code_snippet=item.get("code_extract"),
                    ))
            return self._finalize(findings)
        finally:
            shutil.rmtree(proj, ignore_errors=True)
