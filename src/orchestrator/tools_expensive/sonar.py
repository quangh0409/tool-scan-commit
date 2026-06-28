"""
SonarQube (SKELETON — cắm thật sau PoC). Khác 2 tool kia: SERVER + scanner.

Server = 1 SINGLETON dùng chung cả run (không bật/tắt mỗi commit). Lệnh DỰ KIẾN:
  server: docker run -d --name orch-sonar -p 9000:9000 sonarqube:lts-community
          chờ GET /api/system/status == UP (~1 phút).
  scan  : sonar-scanner -Dsonar.host.url=... -Dsonar.login=<token> \
                        -Dsonar.java.binaries=<ctx.classes_dirs> \
                        -Dsonar.projectKey=<repo>@<sha>
  lấy KQ: GET /api/issues/search?projectKeys=...&types=VULNERABILITY -> JSON -> adapter (CWE qua security-standards).
"""
from __future__ import annotations

from ..schema import RawFinding
from .base import BuildContext, ExpensiveTool


class SonarTool(ExpensiveTool):
    name = "sonar"
    image = "sonarqube:lts-community"

    def start_server(self) -> None:
        # TODO(PoC): docker run -d server + chờ /api/system/status=UP + tạo token.
        pass

    def stop_server(self) -> None:
        # TODO(PoC): docker rm -f orch-sonar.
        pass

    def scan(self, ctx: BuildContext) -> list[RawFinding]:
        if not ctx.classes_dirs:
            return []
        # TODO(PoC): sonar-scanner (projectKey=repo@sha) -> chờ task -> GET /api/issues/search -> RawFinding.
        return self._finalize([])
