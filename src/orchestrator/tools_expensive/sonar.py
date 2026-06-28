"""
SonarQube (THẬT). Khác 2 tool kia: SERVER (singleton) + scanner + Web API.

Luồng đã PoC-xác minh:
  start_server: docker network + run sonarqube -> chờ /api/system/status=UP -> tạo token (admin/admin).
  scan: sonar-scanner (cùng network) với sources + sonar.java.binaries (classes) + sonar.java.libraries
        (jar .m2 — BẮT BUỘC, thiếu thì Sonar bỏ sót semantic security) -> poll CE task ->
        query issues(VULNERABILITY) + hotspots -> CWE regex từ mô tả rule (cache) -> RawFinding.
  stop_server: rm container + network.

API gọi từ HOST qua http://localhost:9000 (server -p 9000:9000); scanner trong container qua
http://orch-sonar:9000 (cùng docker network). Auth: token làm basic-user (token:).
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.request
import urllib.error

from .. import config
from ..schema import RawFinding, normalize_cwe
from ..tools.base import docker_run
from .base import BuildContext, ExpensiveTool
from .build import changed_modules, _m2_cache

IMAGE_SERVER = "sonarqube:lts-community"
IMAGE_SCANNER = "sonarsource/sonar-scanner-cli"
NETWORK = "orch-sonar-net"
SERVER = "orch-sonar"
HOST_API = "http://localhost:9000"
_CWE_RE = re.compile(r"CWE-(\d+)")
_SEV = {"HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW"}


def _sh(args, timeout=120):
    return docker_run(args, timeout=timeout)


class SonarTool(ExpensiveTool):
    name = "sonar"
    image = IMAGE_SERVER

    def __init__(self):
        self._token = None
        self._rule_cwe: dict[str, list[str]] = {}

    # ---- HTTP (host -> server) ----
    def _get(self, path: str) -> dict:
        req = urllib.request.Request(HOST_API + path)
        if self._token:
            tok = base64.b64encode(f"{self._token}:".encode()).decode()
            req.add_header("Authorization", f"Basic {tok}")
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())

    def _post(self, path: str, auth: bytes) -> dict:
        req = urllib.request.Request(HOST_API + path, method="POST")
        req.add_header("Authorization", "Basic " + base64.b64encode(auth).decode())
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode()
            return json.loads(body) if body.strip() else {}

    # ---- server lifecycle (singleton) ----
    def start_server(self) -> None:
        _sh(["network", "create", NETWORK], timeout=30)
        _sh(["rm", "-f", SERVER], timeout=30)
        _sh(["run", "-d", "--name", SERVER, "--network", NETWORK, "-p", "9000:9000",
             "-e", "SONAR_ES_BOOTSTRAP_CHECKS_DISABLE=true", IMAGE_SERVER], timeout=120)
        # chờ UP (~1-2')
        for _ in range(120):
            try:
                if self._get("/api/system/status").get("status") == "UP":
                    break
            except Exception:  # noqa: BLE001 — server chưa sẵn sàng
                pass
            time.sleep(3)
        else:
            raise RuntimeError("SonarQube không UP sau 6 phút")
        # đổi mật khẩu admin (admin/admin chỉ dùng được lần đầu) rồi tạo token với pw mới
        pw = config.SONAR_ADMIN_PW
        self._post(f"/api/users/change_password?login=admin&previousPassword=admin"
                   f"&password={pw}", auth=b"admin:admin")
        r = self._post(f"/api/user_tokens/generate?name=orch-{int(time.time())}",
                       auth=f"admin:{pw}".encode())
        self._token = r["token"]

    def stop_server(self) -> None:
        _sh(["rm", "-f", SERVER], timeout=60)
        _sh(["network", "rm", NETWORK], timeout=30)

    # ---- CWE từ mô tả rule (cache) ----
    def _cwe_of_rule(self, rule_key: str) -> list[str]:
        if rule_key in self._rule_cwe:
            return self._rule_cwe[rule_key]
        cwes: list[str] = []
        try:
            r = self._get(f"/api/rules/show?key={rule_key}").get("rule", {})
            txt = r.get("htmlDesc", "") + " ".join(
                s.get("content", "") for s in r.get("descriptionSections", []))
            cwes = [normalize_cwe(c) for c in dict.fromkeys(_CWE_RE.findall(txt))]
        except Exception:  # noqa: BLE001
            pass
        self._rule_cwe[rule_key] = cwes
        return cwes

    # ---- scan 1 commit ----
    def scan(self, ctx: BuildContext) -> list[RawFinding]:
        if not ctx.classes_dirs:
            return []
        mods = changed_modules(ctx.clone_dir, ctx.commit_id)
        srcs = [f"{m}/src/main/java" for m in mods
                if (ctx.clone_dir / m / "src/main/java").is_dir()]
        if not srcs:
            return []
        bins = ",".join(str(d.relative_to(ctx.clone_dir)) for d in ctx.classes_dirs)
        key = f"tt-{ctx.commit_id[:12]}"

        proc = docker_run([
            "run", "--rm", "--network", NETWORK,
            "-u", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp",
            "-e", "SONAR_USER_HOME=/tmp/.sonar", "-w", "/usr/src",
            "-v", f"{ctx.clone_dir}:/usr/src", "-v", f"{_m2_cache()}:/m2:ro",
            IMAGE_SCANNER,
            f"-Dsonar.host.url=http://{SERVER}:9000", f"-Dsonar.login={self._token}",
            f"-Dsonar.projectKey={key}", f"-Dsonar.sources={','.join(srcs)}",
            f"-Dsonar.java.binaries={bins}", "-Dsonar.java.libraries=/m2/repository/**/*.jar",
            "-Dsonar.working.directory=/tmp/sw", "-Dsonar.scm.disabled=true",
        ], timeout=config.BUILD_TIMEOUT)

        m = re.search(r"ce/task\?id=([\w-]+)", proc.stdout or "")
        if not m:
            tail = (proc.stderr or proc.stdout or "")[-400:]
            raise RuntimeError(f"sonar-scanner không ra task id: {tail}")
        task = m.group(1)
        for _ in range(150):  # chờ Compute Engine xử lý
            st = self._get(f"/api/ce/task?id={task}").get("task", {}).get("status")
            if st in ("SUCCESS", "FAILED", "CANCELED"):
                break
            time.sleep(2)

        findings: list[RawFinding] = []
        # (a) VULNERABILITY issues + (b) SECURITY_HOTSPOT
        raw = []
        d = self._get(f"/api/issues/search?componentKeys={key}&types=VULNERABILITY&ps=500")
        for i in d.get("issues", []):
            raw.append((i.get("rule"), i.get("component", ""), i.get("line"),
                        i.get("message"), i.get("severity")))
        h = self._get(f"/api/hotspots/search?projectKey={key}&ps=500")
        for hs in h.get("hotspots", []):
            raw.append((hs.get("ruleKey"), hs.get("component", ""), hs.get("line"),
                        hs.get("message"), hs.get("vulnerabilityProbability")))

        for rule_key, component, line, msg, sev in raw:
            if not rule_key or not line:
                continue
            cwes = self._cwe_of_rule(rule_key)
            if not cwes:
                continue  # bắt buộc có CWE
            fp = component.split(":", 1)[1] if ":" in component else component
            findings.append(RawFinding(
                repo=ctx.repo, commit_id=ctx.commit_id,
                file_path=fp, s_line=int(line), cwe=cwes,
                tool=self.name, rule_id=rule_key,
                severity=_SEV.get((sev or "").upper(), "MEDIUM"),
                message=(msg or "")[:200],
            ))
        return self._finalize(findings)
