"""
CodeQL (SKELETON — cắm thật sau PoC). Mạnh nhất: dataflow liên-thủ-tục/liên-file.

Lệnh DỰ KIẾN (CodeQL tự build có-trace -> DB; có thể để lại target/classes dùng chung):
    codeql database create <db> --language=java \
           --command="mvn -B clean compile -DskipTests"
    codeql database analyze <db> \
           codeql/java-queries:codeql-suites/java-security-extended.qls \
           --format=sarif-latest --output=out.sarif
Output: SARIF native, CWE ở rule.properties.tags ('external/cwe/cwe-089') -> parse trực tiếp.
"""
from __future__ import annotations

from ..schema import RawFinding
from .base import BuildContext, ExpensiveTool


class CodeQLTool(ExpensiveTool):
    name = "codeql"
    image = "ghcr.io/github/codeql-cli"   # PoC: chốt bundle/digest

    def scan(self, ctx: BuildContext) -> list[RawFinding]:
        # TODO(PoC): tạo DB (trace mvn) -> analyze suite security-extended -> parse SARIF -> RawFinding.
        return self._finalize([])
