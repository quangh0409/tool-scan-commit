"""
CodeQL (THẬT). Dataflow liên-thủ-tục/liên-file — nguồn `vuln` code tin cậy nhất.

Luồng (1 container orch-codeql = maven+JDK8+codeql bundle):
  1. codeql database create  (TRACE `mvn compile` của module bị đụng -> DB)
  2. codeql database analyze  java-security-extended.qls -> SARIF
  3. parse SARIF -> RawFinding (CWE lấy từ rule.properties.tags 'external/cwe/cwe-089').

Chạy AS-UID + HOME=/tmp + repo.local trong cache (không sinh file root kẹt clone-pool).
CodeQL tự build-trace riêng (không dùng ctx.classes_dirs); build_commit lo cho FindSecBugs/Sonar.
"""
from __future__ import annotations

import json
import re

from .. import config
from ..schema import RawFinding, normalize_cwe
from ..tools.base import canon_path, docker_run
from .base import BuildContext, ExpensiveTool, ToolError, run_as_user
from .build import changed_modules, _m2_cache

IMAGE = "orch-codeql:2.25.6"
_CWE_RE = re.compile(r"cwe[-/](\d+)", re.I)

# SARIF level -> severity thô
_LEVEL = {"error": "HIGH", "warning": "MEDIUM", "note": "LOW", "none": "LOW"}


def _cwes(tags) -> list[str]:
    out = []
    for t in tags or []:
        m = _CWE_RE.search(str(t))
        if m:
            out.append(normalize_cwe(m.group(1)))
    return out


class CodeQLTool(ExpensiveTool):
    name = "codeql"
    image = IMAGE

    def scan(self, ctx: BuildContext, raw_out: list | None = None) -> list[RawFinding]:
        mods = changed_modules(ctx.clone_dir, ctx.commit_id)
        pl = f" -pl {','.join(mods)} -am" if mods else ""
        sarif_name = f"codeql_{ctx.commit_id[:12]}.sarif"
        build = (f"mvn -B clean compile -DskipTests{pl} "
                 f"-Dmaven.repo.local=/m2/repository")
        sh = (
            f"codeql database create /tmp/cqdb --language=java --overwrite "
            f"--source-root=/work --command=\"{build}\" "
            f"&& codeql database analyze /tmp/cqdb {config.CODEQL_SUITE} "
            f"--format=sarif-latest --output=/work/{sarif_name} "
            f"--ram={config.CODEQL_RAM_MB} --threads={config.CODEQL_THREADS}"
        )
        proc = docker_run([
            "run", "--rm", *run_as_user(), "-e", "HOME=/tmp",
            "-v", f"{ctx.clone_dir}:/work",
            "-v", f"{_m2_cache()}:/m2",
            "-w", "/work", IMAGE,
            "bash", "-lc", sh,
        ], timeout=config.BUILD_TIMEOUT)

        sarif = ctx.clone_dir / sarif_name
        if not sarif.exists():
            tail = (proc.stderr or proc.stdout or "")[-400:]
            raise ToolError(f"codeql không ra SARIF (rc={proc.returncode}): {tail}")
        sarif_text = sarif.read_text(encoding="utf-8", errors="replace") or "{}"
        if raw_out is not None:
            raw_out.append(("sarif", sarif_text))
        try:
            data = json.loads(sarif_text)
        except ValueError as e:
            raise ToolError(f"codeql SARIF hỏng: {e}") from e
        finally:
            sarif.unlink(missing_ok=True)

        findings: list[RawFinding] = []
        for run in data.get("runs", []):
            rules = {r.get("id"): r for r in
                     run.get("tool", {}).get("driver", {}).get("rules", [])}
            for res in run.get("results", []):
                rid = res.get("ruleId", "")
                rule = rules.get(rid, {})
                cwe = _cwes(rule.get("properties", {}).get("tags", []))
                if not cwe:
                    continue  # bắt buộc có CWE
                locs = res.get("locations") or []
                if not locs:
                    continue
                phys = locs[0].get("physicalLocation", {})
                region = phys.get("region", {})
                line = region.get("startLine")
                if not line:
                    continue
                findings.append(RawFinding(
                    repo=ctx.repo, commit_id=ctx.commit_id,
                    file_path=canon_path(phys.get("artifactLocation", {}).get("uri", "")),
                    s_line=int(line),
                    e_line=region.get("endLine"),
                    cwe=cwe,
                    tool=self.name,
                    rule_id=rid,
                    severity=_LEVEL.get(res.get("level", "warning"), "MEDIUM"),
                    message=(res.get("message", {}) or {}).get("text"),
                ))
        return self._finalize(findings)
