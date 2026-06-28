"""
Find Security Bugs / SpotBugs (SKELETON — cắm thật sau PoC). Phân tích BYTECODE.

Dùng ctx.classes_dirs (target/classes từ build dùng chung). Lệnh DỰ KIẾN:
    spotbugs -textui -effort:max -low -pluginList find-sec-bugs.jar \
             -xml:withMessages -output out.xml  <classes/jars>
Output: SpotBugs XML -> adapter. <BugInstance type=SQL_INJECTION_JDBC ...> + bảng pattern->CWE.
Vị trí: <SourceLine> (class -> file .java). Chỉ JVM (không phủ JS/Python).
"""
from __future__ import annotations

from ..schema import RawFinding
from .base import BuildContext, ExpensiveTool


class FindSecBugsTool(ExpensiveTool):
    name = "findsecbugs"
    image = "mythic/findsecbugs"   # PoC: chốt image/digest

    def scan(self, ctx: BuildContext) -> list[RawFinding]:
        if not ctx.classes_dirs:
            return []
        # TODO(PoC): chạy spotbugs+findsecbugs trên ctx.classes_dirs -> parse XML -> map pattern->CWE.
        return self._finalize([])
