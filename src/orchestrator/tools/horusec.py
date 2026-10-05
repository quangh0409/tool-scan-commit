"""
Wrapper Horusec (Tầng ② — meta SAST). CHẠY -D (disable-docker) => chỉ HorusecEngine
built-in: (a) KHÔNG cần docker-in-docker, (b) KHÔNG chạy lại semgrep/gitleaks
=> tránh correlated-errors với 2 tool standalone.

Hạn chế: HorusecEngine KHÔNG gán CWE (chỉ UUID + details text). Theo ràng buộc bắt buộc
CWE: language=="Leaks" -> CWE-798; code-vuln map theo từ khoá thận trọng; không suy ra
được CWE thì BỎ.

Diff-scoped: copy các file đổi vào temp dir (giữ cấu trúc) rồi quét temp đó.
Docker image: horuszup/horusec-cli:latest
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

from ..schema import RawFinding, normalize_cwe
from .base import ToolWrapper, canon_path, docker_run

IMAGE = "horuszup/horusec-cli:latest"
# Horusec copy code vào .horusec/<uuid>/ rồi báo path kèm prefix đó -> cần bóc
_HORUSEC_TMP = re.compile(r"\.horusec/[0-9a-fA-F-]{36}/")

# map từ khoá trong `details` -> CWE (thận trọng, chỉ ca rõ ràng; sai CWE làm hỏng cluster)
_KEYWORD_CWE = [
    ("sql injection", "CWE-89"),
    ("cross-site script", "CWE-79"), ("xss", "CWE-79"),
    ("path traversal", "CWE-22"),
    ("command injection", "CWE-78"), ("os command", "CWE-78"),
    ("ssrf", "CWE-918"),
    ("xml external", "CWE-611"), ("xxe", "CWE-611"),
    ("ldap injection", "CWE-90"),
    ("deserial", "CWE-502"),
    ("md5", "CWE-327"), ("sha1", "CWE-327"), ("weak cipher", "CWE-327"),
    ("insecure random", "CWE-330"),
    ("hard-cod", "CWE-798"), ("hardcod", "CWE-798"), ("password", "CWE-798"),
]


def _map_cwe(language: str, details: str) -> list[str]:
    if (language or "").lower() == "leaks":
        return ["CWE-798"]
    d = (details or "").lower()
    for kw, cwe in _KEYWORD_CWE:
        if kw in d:
            return [normalize_cwe(cwe)]
    return []  # không suy ra được -> bỏ


class HorusecWrapper(ToolWrapper):
    name = "horusec"
    tier = "cheap"
    image = IMAGE

    def version(self) -> str | None:
        proc = docker_run(["run", "--rm", IMAGE, "version"], timeout=60)
        out = (proc.stdout or "") + (proc.stderr or "")
        for ln in out.splitlines():
            if "version" in ln.lower():
                return ln.strip()
        return None

    def scan(self, repo_dir: Path, commit_id: str, repo: str,
             changed_files: list[str], raw_out: list | None = None) -> list[RawFinding]:
        if not changed_files:
            return []
        # copy file đổi vào temp dir (diff-scoped) + dir output riêng
        proj = Path(tempfile.mkdtemp(prefix="horusec_proj_"))
        out = Path(tempfile.mkdtemp(prefix="horusec_out_"))
        try:
            for rel in changed_files:
                src = repo_dir / rel
                if not src.exists():
                    continue
                dst = proj / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

            docker_run([
                "run", "--rm", "-v", f"{proj}:/src", "-v", f"{out}:/out", IMAGE,
                "horusec", "start", "-p", "/src", "-D",
                "-o", "json", "-O", "/out/h.json",
            ], timeout=900)

            report = out / "h.json"
            if not report.exists():
                return []
            # encoding tường minh: trong exe đóng gói không có PYTHONUTF8 -> mặc định cp1252 vỡ ('charmap')
            report_text = report.read_text(encoding="utf-8", errors="replace") or "{}"
            if raw_out is not None:
                raw_out.append(("json", report_text))
            try:
                data = json.loads(report_text)
            except json.JSONDecodeError:
                return []

            findings: list[RawFinding] = []
            for av in (data.get("analysisVulnerabilities") or []):
                v = av.get("vulnerabilities", {})
                cwe = _map_cwe(v.get("language", ""), v.get("details", ""))
                if not cwe:
                    continue
                try:
                    line = int(v.get("line") or 0)
                except (ValueError, TypeError):
                    line = 0
                if not line:
                    continue
                findings.append(RawFinding(
                    repo=repo, commit_id=commit_id,
                    file_path=canon_path(_HORUSEC_TMP.sub("", v.get("file", ""))),
                    s_line=line,
                    cwe=cwe,
                    tool=self.name,
                    rule_id=v.get("vulnerabilityID", "") or v.get("ruleID", ""),
                    severity=(v.get("severity") or "").upper() or None,
                    message=(v.get("details") or "").split("\n")[0][:200],
                    code_snippet=v.get("code"),
                ))
            return self._finalize(findings)
        finally:
            shutil.rmtree(proj, ignore_errors=True)
            shutil.rmtree(out, ignore_errors=True)
