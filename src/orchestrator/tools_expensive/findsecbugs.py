"""
Find Security Bugs (SpotBugs + plugin) — phân tích BYTECODE từ build dùng chung (ctx.classes_dirs).

Output SpotBugs XML -> RawFinding. CWE lấy từ <BugPattern cweid=...>; map BugInstance.type -> cweid.
Path: SourceLine.sourcepath là package-relative (vd travel/config/X.java) -> resolve về path repo
bằng glob trong clone (**/<sourcepath> có '/src/'). Chạy as-uid.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ..schema import RawFinding, normalize_cwe
from ..tools.base import docker_run
from .base import BuildContext, ExpensiveTool, ToolError, run_as_user
from .. import config

IMAGE = "orch-findsecbugs:1.14.0"
_PRIO = {"1": "HIGH", "2": "MEDIUM", "3": "LOW"}


class FindSecBugsTool(ExpensiveTool):
    name = "findsecbugs"
    image = IMAGE

    def _repo_path(self, clone, sourcepath: str) -> str:
        if not sourcepath:
            return ""
        for m in clone.glob(f"**/{sourcepath}"):
            s = m.as_posix()  # as_posix: Windows dùng "\\" -> "/src/" không khớp
            if "/src/" in s and m.is_file():
                return m.relative_to(clone).as_posix()
        return ""

    def scan(self, ctx: BuildContext, raw_out: list | None = None) -> list[RawFinding]:
        if not ctx.classes_dirs:
            return []
        # as_posix(): path trong container là Linux; str() trên Windows ra "a\b" -> tool không mở được
        rels = [d.relative_to(ctx.clone_dir).as_posix() for d in ctx.classes_dirs]
        targets = " ".join(f"/work/{r}" for r in rels)
        out_name = f"fsb_{ctx.commit_id[:12]}.xml"
        sh = (f"findsecbugs -nested:false -effort:max -low "
              f"-xml:withMessages -output /work/{out_name} {targets}")
        proc = docker_run([
            "run", "--rm", *run_as_user(), "-e", "HOME=/tmp",
            "-v", f"{ctx.clone_dir}:/work", "-w", "/work", IMAGE,
            "bash", "-lc", sh,
        ], timeout=config.BUILD_TIMEOUT)

        xml = ctx.clone_dir / out_name
        if not xml.exists() or xml.stat().st_size == 0:  # file 0 byte = tool crash (vd "No files to analyze")
            xml.unlink(missing_ok=True)
            tail = (proc.stderr or proc.stdout or "")[-400:]
            # ToolError -> runner ghi tool_error; message có dấu hiệu Docker/đĩa -> infra_error
            raise ToolError(f"findsecbugs không ra XML (rc={proc.returncode}): {tail}")
        if raw_out is not None:
            raw_out.append(("xml", xml.read_text(encoding="utf-8", errors="replace")))
        try:
            root = ET.parse(xml).getroot()
        except ET.ParseError as e:
            raise ToolError(f"findsecbugs XML hỏng: {e}") from e
        finally:
            xml.unlink(missing_ok=True)

        # type -> CWE (từ BugPattern cuối file)
        pat_cwe = {}
        for bp in root.findall("BugPattern"):
            cwe = bp.get("cweid")
            if cwe:
                pat_cwe[bp.get("type")] = normalize_cwe(cwe)

        findings: list[RawFinding] = []
        for bi in root.findall("BugInstance"):
            cwe = pat_cwe.get(bi.get("type"))
            if not cwe:
                continue  # bắt buộc có CWE
            sls = [s for s in bi.findall(".//SourceLine") if s.get("start")]
            if not sls:
                continue
            sl = sls[0]
            fp = self._repo_path(ctx.clone_dir, sl.get("sourcepath", ""))
            if not fp:
                continue
            start = int(sl.get("start"))
            findings.append(RawFinding(
                repo=ctx.repo, commit_id=ctx.commit_id,
                file_path=fp, s_line=start, e_line=int(sl.get("end") or start),
                cwe=[cwe], tool=self.name, rule_id=bi.get("type", ""),
                severity=_PRIO.get(bi.get("priority", ""), "MEDIUM"),
                message=(bi.findtext("ShortMessage") or bi.findtext("LongMessage") or "")[:200],
            ))
        return self._finalize(findings)
