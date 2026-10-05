"""repo_probe — kiểm tra repo GitHub KHÔNG clone (CONTRACTS §9 `POST /api/repo/check`).

check(url, pat=None, work_dir=None, timeout=30) -> {canon, slug, public, default_branch, branches[], tags[],
    java_maven, jdk, modules, snapshot_risk, security_config_count, commit_count|null, warnings[]}

- `git ls-remote --symref --heads --tags` với GIT_TERMINAL_PROMPT=0 (không treo Credential Manager), timeout.
- PAT qua `-c http.extraheader=AUTHORIZATION: basic <b64("x-access-token:PAT")>` — KHÔNG log, không vào URL.
- Nếu clone đã có trong work_dir/<repo_slug> (và origin khớp): đọc `git show HEAD:pom.xml` → jdk/modules,
  đếm SecurityConfig, SNAPSHOT, số commit `git rev-list --count`. Chưa có clone → java_maven=None + warning.
Stdlib-only; mọi subprocess text có errors="replace".
"""
from __future__ import annotations

import base64
import os
import re
import subprocess
from pathlib import Path

from .errors import ApiError

try:
    from orchestrator import keys as _keys  # type: ignore
except Exception:  # pragma: no cover
    _keys = None

LS_REMOTE_TIMEOUT = 30


def canon(url: str) -> str:
    if _keys is not None:
        return _keys.canon_repo(url)
    return (url or "").strip().rstrip("/")


def slug(url: str) -> str:
    if _keys is not None:
        return _keys.repo_slug(url)
    parts = [p for p in canon(url).split("/") if p]
    return f"{parts[-2]}__{parts[-1]}" if len(parts) >= 2 else "repo"


def _git_env() -> dict:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "Never"
    env["LC_ALL"] = "C"
    return env


def _auth_args(pat: str | None) -> list[str]:
    if not pat:
        return []
    tok = base64.b64encode(f"x-access-token:{pat}".encode("utf-8")).decode("ascii")
    return ["-c", f"http.extraheader=AUTHORIZATION: basic {tok}"]


def _run(args: list[str], timeout: float, cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=timeout,
                          env=_git_env(), cwd=cwd)


def parse_ls_remote(text: str) -> tuple[str | None, list[str], list[str]]:
    """-> (default_branch, branches, tags) từ output `git ls-remote --symref --heads --tags`."""
    default = None
    branches: list[str] = []
    tags: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("ref: "):
            m = re.match(r"ref:\s+refs/heads/(\S+)\s+HEAD", line)
            if m:
                default = m.group(1)
            continue
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        ref = parts[1]
        if ref.endswith("^{}"):
            continue
        if ref.startswith("refs/heads/"):
            branches.append(ref[len("refs/heads/"):])
        elif ref.startswith("refs/tags/"):
            tags.append(ref[len("refs/tags/"):])
    return default, branches, tags


def ls_remote(url: str, pat: str | None = None, timeout: float = LS_REMOTE_TIMEOUT) -> tuple[str | None, list[str], list[str]]:
    args = ["git"] + _auth_args(pat) + ["ls-remote", "--symref", "--heads", "--tags", url]
    try:
        r = _run(args, timeout)
    except FileNotFoundError:
        raise ApiError(500, "git_missing", "Không tìm thấy git", "Cài Git (winget install Git.Git) rồi chạy Preflight")
    except subprocess.TimeoutExpired:
        raise ApiError(504, "timeout", f"git ls-remote quá {int(timeout)} s", "Mạng chậm/proxy. Thử lại hoặc kiểm tra kết nối github.com")
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        low = err.lower()
        if "authentication failed" in low or "could not read username" in low or "401" in low or "403" in low:
            raise ApiError(401, "auth_required", "Repo yêu cầu xác thực hoặc PAT sai",
                           "Bật 'Repo private' và nhập PAT có quyền repo:read")
        if "not found" in low or "repository not found" in low or "404" in low:
            raise ApiError(404, "repo_not_found", "Repo không tồn tại hoặc private", "Kiểm tra lại link; repo private cần PAT")
        if "could not resolve host" in low or "unable to access" in low:
            raise ApiError(502, "network", "Không kết nối được github.com", err[-300:])
        raise ApiError(500, "git_error", f"git ls-remote rc={r.returncode}", err[-300:])
    return parse_ls_remote(r.stdout or "")


# ---------------------------------------------------------------- clone cục bộ (nếu có)

def find_clone(url: str, work_dir: str | Path | None) -> Path | None:
    if not work_dir:
        return None
    cands = [Path(work_dir) / slug(url), Path(work_dir) / canon(url).rstrip("/").split("/")[-1]]
    for d in cands:
        if (d / ".git").exists() and _origin_matches(d, url):
            return d
    return None


def _origin_matches(repo_dir: Path, url: str) -> bool:
    try:
        r = _run(["git", "config", "--get", "remote.origin.url"], 10, cwd=str(repo_dir))
        return r.returncode == 0 and canon(r.stdout.strip()).lower() == canon(url).lower()
    except (OSError, subprocess.TimeoutExpired):
        return False


def _git_out(repo_dir: Path, *args: str, timeout: float = 20) -> str | None:
    try:
        r = _run(["git", *args], timeout, cwd=str(repo_dir))
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def parse_pom(pom: str) -> dict:
    """jdk (int|None), modules (số <module>), snapshot_risk (dependency *-SNAPSHOT), spring_boot (version|None)."""
    jdk = None
    for pat in (r"<maven\.compiler\.(?:source|release|target)>\s*(?:1\.)?(\d+)\s*<",
                r"<java\.version>\s*(?:1\.)?(\d+)\s*<", r"<release>\s*(\d+)\s*<", r"<source>\s*(?:1\.)?(\d+)\s*<"):
        m = re.search(pat, pom)
        if m:
            jdk = int(m.group(1))
            break
    modules = len(re.findall(r"<module>\s*[^<]+\s*</module>", pom))
    # SNAPSHOT trong <dependency>/<parent> (không tính <version> của chính project ở đầu file)
    snapshot = bool(re.search(r"<(?:dependency|parent)>.*?<version>[^<]*-SNAPSHOT</version>.*?</(?:dependency|parent)>", pom, re.S))
    sb = re.search(r"<artifactId>spring-boot(?:-starter-parent|-dependencies)</artifactId>\s*<version>([^<]+)</version>", pom)
    return {"jdk": jdk, "modules": modules, "snapshot_risk": snapshot, "spring_boot": sb.group(1).strip() if sb else None}


def inspect_clone(repo_dir: Path, rev: str = "HEAD") -> dict:
    out: dict = {"java_maven": False, "jdk": None, "modules": 0, "snapshot_risk": False,
                 "security_config_count": 0, "commit_count": None, "spring_boot": None}
    pom = _git_out(repo_dir, "show", f"{rev}:pom.xml")
    if pom is not None:
        out["java_maven"] = True
        out.update(parse_pom(pom))
    tree = _git_out(repo_dir, "ls-tree", "-r", "--name-only", rev, timeout=60) or ""
    names = tree.splitlines()
    if not out["java_maven"] and any(n.endswith("pom.xml") for n in names):
        out["java_maven"] = True          # pom ở module con (monorepo lồng)
    if not out["modules"]:
        out["modules"] = sum(1 for n in names if n.endswith("pom.xml") and n != "pom.xml")
    out["security_config_count"] = sum(1 for n in names if n.endswith(".java") and "SecurityConfig" in n.rsplit("/", 1)[-1])
    cnt = _git_out(repo_dir, "rev-list", "--count", rev, timeout=60)
    if cnt and cnt.strip().isdigit():
        out["commit_count"] = int(cnt.strip())
    return out


# ---------------------------------------------------------------- API chính

def check(url: str, pat: str | None = None, work_dir: str | Path | None = None, timeout: float = LS_REMOTE_TIMEOUT) -> dict:
    c = canon(url)
    if not re.match(r"^https://github\.com/[^/\s]+/[^/\s]+$", c):
        raise ApiError(400, "bad_url", "Link phải có dạng https://github.com/owner/repo", "Chỉ hỗ trợ github.com ở MVP")
    warnings: list[str] = []
    default, branches, tags = ls_remote(c, pat, timeout)
    if not branches:
        raise ApiError(422, "empty_repo", "Repo rỗng (không có nhánh)", "Không thể quét repo không có commit")
    if default is None:
        default = "master" if "master" in branches else ("main" if "main" in branches else branches[0])
        warnings.append(f"Không đọc được nhánh mặc định từ HEAD — tạm dùng {default}")
    res = {"canon": c, "slug": slug(c), "public": not bool(pat), "default_branch": default,
           "branches": branches, "tags": tags, "java_maven": None, "jdk": None, "modules": None,
           "snapshot_risk": None, "security_config_count": None, "commit_count": None, "warnings": warnings}
    clone = find_clone(c, work_dir)
    if clone is None:
        warnings.append("Chưa có clone cục bộ — pom.xml/JDK/số commit sẽ biết sau khi clone nền (bước 2).")
        return res
    info = inspect_clone(clone, f"origin/{default}" if _git_out(clone, "rev-parse", "--verify", f"origin/{default}") else "HEAD")
    res.update(info)
    res["clone_dir"] = str(clone)
    if not info["java_maven"]:
        warnings.append("Không tìm thấy pom.xml — tầng đắt (FindSecBugs/Sonar/CodeQL) sẽ không build được.")
    if info["snapshot_risk"]:
        warnings.append("Có dependency *-SNAPSHOT — build tầng đắt có thể thất bại nhiều (xem EXPENSIVE_TIER_REPORT).")
    return res


def histogram(repo_dir: Path, branch: str | None = None, since: str | None = None, until: str | None = None,
              timeout: float = 60) -> list[dict]:
    """[{month:'YYYY-MM', n}] từ `git log --date=short --format=%cd` (committer-date) trên clone."""
    args = ["log", "--date=short", "--format=%cd", "--no-merges"]
    if since:
        args.append(f"--since={since}")
    if until:
        args.append(f"--until={until}")
    args.append(branch or "HEAD")
    out = _git_out(repo_dir, *args, timeout=timeout)
    if out is None and branch:
        out = _git_out(repo_dir, *args[:-1], f"origin/{branch}", timeout=timeout)
    if not out:
        return []
    counts: dict[str, int] = {}
    for line in out.splitlines():
        if len(line) >= 7:
            counts[line[:7]] = counts.get(line[:7], 0) + 1
    if not counts:
        return []
    months = sorted(counts)
    # lấp tháng trống để biểu đồ liên tục
    y, m = map(int, months[0].split("-"))
    ye, me = map(int, months[-1].split("-"))
    out_list = []
    while (y, m) <= (ye, me):
        k = f"{y:04d}-{m:02d}"
        out_list.append({"month": k, "n": counts.get(k, 0)})
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out_list
