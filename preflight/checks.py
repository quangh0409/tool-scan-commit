"""13 kiểm tra môi trường (CONTRACTS §8). Mỗi check = 1 hàm `check_<id>(ctx) -> item`.

item = {"id","title","level":"ok|fix|warn|bad","detail","fix_available","fix_id"}
- ok   : đạt
- fix  : chưa đạt nhưng app tự sửa được (fix_id)
- warn : nên sửa, không chặn run
- bad  : chặn run, user phải tự làm (detail có hướng dẫn)

Mọi subprocess: timeout + errors="replace"; KHÔNG raise ra ngoài (lỗi → bad + detail).
`ctx` là dict dùng chung giữa các check (cache `docker info`, work_dir, need_gb, sonar_port...).
"""
from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
from pathlib import Path

IS_WIN = os.name == "nt"
DOCKER_TIMEOUT = 15
WSL_TIMEOUT = 10
NET_TIMEOUT = 3
MIN_DOCKER_MEM_GB = 6.0
MIN_MAX_MAP_COUNT = 262144
DEFAULT_NEED_GB = 5.0
DOCKER_DESKTOP_EXE = r"C:\Program Files\Docker\Docker\Docker Desktop.exe"
WEBVIEW2_KEY = r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
WEBVIEW2_KEY_USER = r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"

# Image bắt buộc. kind: pull | build (từ docker/<dir>) ; optional=True → thiếu chỉ ghi chú.
REQUIRED_IMAGES: list[dict] = [
    {"name": "zricethezav/gitleaks:latest", "kind": "pull", "tier": "cheap"},
    {"name": "trufflesecurity/trufflehog:latest", "kind": "pull", "tier": "cheap"},
    {"name": "semgrep/semgrep:latest", "kind": "pull", "tier": "cheap"},
    {"name": "bearer/bearer:latest", "kind": "pull", "tier": "cheap"},
    {"name": "horuszup/horusec-cli:latest", "kind": "pull", "tier": "cheap"},
    {"name": "maven:3.9-eclipse-temurin-8", "kind": "pull", "tier": "expensive"},
    {"name": "sonarqube:lts-community", "kind": "pull", "tier": "expensive"},
    {"name": "sonarsource/sonar-scanner-cli", "kind": "pull", "tier": "expensive"},
    {"name": "orch-findsecbugs:1.14.0", "kind": "build", "dir": "docker/findsecbugs", "tier": "expensive"},
    {"name": "orch-codeql:2.25.6", "kind": "build", "dir": "docker/codeql", "tier": "expensive",
     "optional": True},
]

CHECK_ORDER = ("os_wsl2", "docker_installed", "docker_daemon", "docker_mem", "sonar_port", "disk_free",
               "git", "git_longpaths", "images", "images_pinned", "max_map_count", "network", "webview2")


def item(cid: str, title: str, level: str, detail: str = "", fix_id: str | None = None, **extra) -> dict:
    d = {"id": cid, "title": title, "level": level, "detail": detail,
         "fix_available": fix_id is not None, "fix_id": fix_id}
    d.update(extra)
    return d


# ---------------------------------------------------------------- subprocess helpers

def _decode(b: bytes | str | None) -> str:
    if b is None:
        return ""
    if isinstance(b, str):
        return b
    # wsl.exe in UTF-16LE trên Windows → có nhiều byte 0
    if b and b.count(b"\x00") > len(b) // 4:
        try:
            return b.decode("utf-16-le", errors="replace").replace("\x00", "")
        except Exception:  # noqa: BLE001
            pass
    return b.decode("utf-8", errors="replace")


def run_cmd(cmd: list[str], timeout: float = DOCKER_TIMEOUT, **kw) -> tuple[int, str, str]:
    """subprocess.run an toàn: (rc, stdout, stderr). Thiếu lệnh → 127, timeout → 124, lỗi khác → -1."""
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, **kw)
        out, err = r.stdout, r.stderr
        return int(r.returncode), _decode(out).strip(), _decode(err).strip()
    except FileNotFoundError:
        return 127, "", f"không tìm thấy lệnh {cmd[0]!r}"
    except subprocess.TimeoutExpired:
        return 124, "", f"quá {timeout}s"
    except Exception as e:  # noqa: BLE001
        return -1, "", str(e)


def docker_info(ctx: dict) -> tuple[int, str, str]:
    """`docker info` (cache trong ctx) → (rc, 'MemTotal NCPU ServerVersion OSType', err)."""
    if "docker_info" not in ctx:
        ctx["docker_info"] = run_cmd(
            ["docker", "info", "--format", "{{.MemTotal}} {{.NCPU}} {{.ServerVersion}} {{.OSType}}"],
            timeout=ctx.get("docker_timeout", DOCKER_TIMEOUT))
    return ctx["docker_info"]


def docker_up(ctx: dict) -> bool:
    rc, out, _ = docker_info(ctx)
    return rc == 0 and bool(out.strip())


def _need_docker(cid: str, title: str) -> dict:
    return item(cid, title, "bad", "Cần Docker daemon đang chạy mới kiểm được mục này.")


# ---------------------------------------------------------------- checks

def check_os_wsl2(ctx: dict) -> dict:
    t = "Hệ điều hành & WSL2"
    if not IS_WIN:
        return item("os_wsl2", t, "ok", f"{platform.system()} {platform.release()} — không cần WSL2.")
    arch = platform.machine()
    rel = platform.release()
    ver = platform.version()
    try:
        build = int(ver.split(".")[-1])
    except (ValueError, IndexError):
        build = 0
    if "64" not in arch and "ARM64" not in arch.upper():
        return item("os_wsl2", t, "bad", f"Windows {rel} {arch}: Docker Desktop cần 64-bit.")
    if build and build < 19044:
        return item("os_wsl2", t, "bad",
                    f"Windows build {build} < 19044 (10 21H2). Cần Windows 10 21H2+/11 cho Docker Desktop WSL2.")
    if not shutil.which("wsl"):
        return item("os_wsl2", t, "bad",
                    "Không thấy wsl.exe. Bật WSL2: PowerShell (Admin) `wsl --install` rồi khởi động lại.")
    rc, out, err = run_cmd(["wsl", "--status"], timeout=ctx.get("wsl_timeout", WSL_TIMEOUT))
    txt = (out + "\n" + err).lower()
    if rc == 0 and ("2" in txt or "wsl" in txt):
        return item("os_wsl2", t, "ok", f"Windows {rel} (build {build}) {arch}; wsl --status OK.")
    if rc == 124:
        return item("os_wsl2", t, "warn", f"Windows {rel} {arch}; `wsl --status` không trả lời ({err}).")
    return item("os_wsl2", t, "warn",
                f"Windows {rel} {arch}; wsl --status rc={rc}: {(out or err)[:200]}. "
                "Nếu Docker daemon vẫn chạy thì bỏ qua cảnh báo này.")


def check_docker_installed(ctx: dict) -> dict:
    t = "Docker đã cài"
    exe = shutil.which("docker")
    if not exe:
        hint = ("Tải Docker Desktop: https://www.docker.com/products/docker-desktop/ "
                "(license miễn phí cho cá nhân/công ty < 250 người)." if IS_WIN
                else "Cài docker engine: https://docs.docker.com/engine/install/")
        return item("docker_installed", t, "bad", "Không tìm thấy lệnh `docker` trong PATH. " + hint)
    rc, out, err = run_cmd(["docker", "--version"], timeout=ctx.get("docker_timeout", DOCKER_TIMEOUT))
    ctx["docker_exe"] = exe
    if rc == 0:
        return item("docker_installed", t, "ok", f"{out} ({exe})")
    return item("docker_installed", t, "bad", f"`docker --version` rc={rc}: {err or out}")


def check_docker_daemon(ctx: dict) -> dict:
    t = "Docker daemon đang chạy"
    if not shutil.which("docker"):
        return item("docker_daemon", t, "bad", "Chưa cài Docker.")
    rc, out, err = docker_info(ctx)
    if rc == 0 and out:
        parts = out.split()
        ver = parts[2] if len(parts) > 2 else "?"
        ost = parts[3] if len(parts) > 3 else "?"
        if ost and ost != "linux":
            return item("docker_daemon", t, "bad",
                        f"Docker engine ở chế độ {ost} containers — cần chuyển sang Linux containers.")
        return item("docker_daemon", t, "ok", f"Server {ver} ({ost}).")
    low = (err + " " + out).lower()
    if "permission denied" in low and not IS_WIN:
        return item("docker_daemon", t, "bad",
                    "User chưa trong nhóm docker: `sudo usermod -aG docker $USER` rồi đăng nhập lại "
                    "(hoặc chạy qua `sg docker`).")
    if IS_WIN:
        fix = "start_docker" if Path(ctx.get("docker_desktop_exe", DOCKER_DESKTOP_EXE)).exists() \
            or shutil.which("Docker Desktop") else None
        detail = ("Daemon chưa chạy" + (f" (rc={rc}: {(err or out)[:160]})" if (err or out) else "") +
                  ". Bật Docker Desktop" + (" — app sẽ bật và chờ ≤ 90 s." if fix else " thủ công."))
        return item("docker_daemon", t, "fix" if fix else "bad", detail, fix)
    return item("docker_daemon", t, "bad",
                f"Daemon chưa chạy (rc={rc}: {(err or out)[:160]}). `sudo systemctl start docker`.")


def check_docker_mem(ctx: dict) -> dict:
    t = "RAM cấp cho Docker"
    if not docker_up(ctx):
        return _need_docker("docker_mem", t)
    _, out, _ = docker_info(ctx)
    parts = out.split()
    try:
        mem_b = int(parts[0])
        cpu = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return item("docker_mem", t, "bad", f"Không đọc được MemTotal từ `docker info`: {out[:120]!r}")
    gb = mem_b / (1024 ** 3)
    ctx["docker_mem_gb"] = round(gb, 2)
    ctx["cpu"] = cpu
    from .fixes import lower_codeql_ram  # noqa: PLC0415
    ctx["codeql_ram_mb"] = lower_codeql_ram(gb)
    extra = {"mem_gb": round(gb, 2), "cpu": cpu, "codeql_ram_mb": ctx["codeql_ram_mb"]}
    if gb < MIN_DOCKER_MEM_GB:
        hint = (" Trên WSL2 mặc định Docker chỉ được ~50 % RAM máy. Tăng bằng %UserProfile%\\.wslconfig: "
                "[wsl2] memory=10GB rồi `wsl --shutdown`." if IS_WIN else "")
        return item("docker_mem", t, "warn",
                    f"Docker có {gb:.1f} GB RAM, {cpu} CPU (< {MIN_DOCKER_MEM_GB:.0f} GB). Sonar + Maven có thể OOM; "
                    f"nên dùng 1 worker đắt." + hint, "lower_codeql_ram", **extra)
    return item("docker_mem", t, "ok",
                f"Docker có {gb:.1f} GB RAM, {cpu} CPU. CodeQL nên dùng ≤ {ctx['codeql_ram_mb']} MB.", **extra)


def port_busy(port: int, host: str = "0.0.0.0") -> bool:
    """True nếu không bind được port (đang bị chiếm). Lỗi lạ → coi là bận để an toàn."""
    for h in {host, "127.0.0.1"}:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            s.bind((h, int(port)))
        except OSError:
            return True
        finally:
            s.close()
    return False


def docker_published_ports(ctx: dict) -> dict[int, str]:
    """{host_port: container_name} từ `docker ps` (cache). Rỗng nếu docker lỗi."""
    if "docker_ports" in ctx:
        return ctx["docker_ports"]
    res: dict[int, str] = {}
    if docker_up(ctx):
        rc, out, _ = run_cmd(["docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"],
                             timeout=ctx.get("docker_timeout", DOCKER_TIMEOUT))
        if rc == 0:
            for line in out.splitlines():
                if "\t" not in line:
                    continue
                name, ports = line.split("\t", 1)
                for seg in ports.split(","):
                    seg = seg.strip()
                    if "->" not in seg:
                        continue
                    hostpart = seg.split("->", 1)[0]
                    p = hostpart.rsplit(":", 1)[-1]
                    try:
                        res[int(p)] = name.strip()
                    except ValueError:
                        continue
    ctx["docker_ports"] = res
    return res


def check_sonar_port(ctx: dict) -> dict:
    t = "Port host cho SonarQube"
    want = int(ctx.get("sonar_port") or os.environ.get("ORCH_SONAR_PORT") or 9000)
    owners = docker_published_ports(ctx)
    busy = port_busy(want) or want in owners
    if not busy:
        ctx["sonar_port_free"] = want
        return item("sonar_port", t, "ok", f"Port {want} trống.", port=want)
    from .fixes import pick_port  # noqa: PLC0415
    free = pick_port(start=want, owners=owners)
    ctx["sonar_port_free"] = free
    who = f" (container `{owners[want]}`)" if want in owners else ""
    if free is None:
        return item("sonar_port", t, "bad", f"Port {want} bận{who}; không tìm được port trống 9000–9900.",
                    port=want)
    return item("sonar_port", t, "fix",
                f"Port {want} bận{who} → đề xuất {free} (ghi vào profile.sonar_port / ORCH_SONAR_PORT).",
                "pick_port", port=want, suggested=free)


def _existing_parent(p: Path) -> Path:
    p = Path(p).expanduser()
    while not p.exists() and p.parent != p:
        p = p.parent
    return p


def check_disk_free(ctx: dict) -> dict:
    t = "Đĩa trống tại thư mục làm việc"
    work = ctx.get("work_dir") or os.environ.get("ORCH_WORK_DIR") or os.getcwd()
    need = float(ctx.get("need_gb") or DEFAULT_NEED_GB)
    try:
        target = _existing_parent(Path(work))
        du = shutil.disk_usage(str(target))
    except OSError as e:
        return item("disk_free", t, "bad", f"Không đọc được dung lượng {work}: {e}")
    free_gb = du.free / (1024 ** 3)
    extra = {"free_gb": round(free_gb, 1), "need_gb": need, "path": str(work)}
    if free_gb < 1.0:
        return item("disk_free", t, "bad", f"Chỉ còn {free_gb:.1f} GB tại {work} — dưới 1 GB, không chạy được.",
                    **extra)
    if free_gb < need:
        return item("disk_free", t, "warn",
                    f"Còn {free_gb:.1f} GB tại {work}, ước tính cần ~{need:.0f} GB (image + clone + .m2 + export).",
                    **extra)
    return item("disk_free", t, "ok", f"Còn {free_gb:.0f} GB tại {work} (cần ~{need:.0f} GB).", **extra)


def check_git(ctx: dict) -> dict:
    t = "Git"
    exe = shutil.which("git")
    if not exe:
        hint = "Cài: `winget install --id Git.Git -e`" if IS_WIN else "Cài: `sudo apt install git`"
        return item("git", t, "bad", "Không tìm thấy `git`. " + hint)
    rc, out, err = run_cmd(["git", "--version"], timeout=10)
    if rc != 0:
        return item("git", t, "bad", f"`git --version` rc={rc}: {err or out}")
    ctx["git_ok"] = True
    return item("git", t, "ok", f"{out} ({exe})")


def check_git_longpaths(ctx: dict) -> dict:
    t = "git core.longpaths"
    if not shutil.which("git"):
        return item("git_longpaths", t, "bad", "Cần Git trước.")
    rc, out, err = run_cmd(["git", "config", "--global", "--get", "core.longpaths"], timeout=10)
    val = out.strip().lower()
    if val == "true":
        return item("git_longpaths", t, "ok", "core.longpaths=true.")
    if not IS_WIN:
        return item("git_longpaths", t, "ok", "Linux không giới hạn 260 ký tự — không cần.")
    return item("git_longpaths", t, "fix",
                f"core.longpaths={val or '(chưa đặt)'}. Repo Java path sâu > 260 ký tự sẽ checkout lỗi. "
                "Sửa: `git config --global core.longpaths true`.", "git_longpaths")


def local_images(ctx: dict) -> dict[str, str]:
    """{repo:tag: digest} (cache). `docker images --digests`."""
    if "local_images" in ctx:
        return ctx["local_images"]
    res: dict[str, str] = {}
    if docker_up(ctx):
        rc, out, _ = run_cmd(["docker", "images", "--digests", "--format", "{{.Repository}}:{{.Tag}}\t{{.Digest}}"],
                             timeout=ctx.get("docker_timeout", DOCKER_TIMEOUT))
        if rc == 0:
            for line in out.splitlines():
                name, _, dig = line.partition("\t")
                name = name.strip()
                if name and name != "<none>:<none>":
                    res[name] = dig.strip()
    ctx["local_images"] = res
    return res


def image_present(name: str, local: dict[str, str]) -> bool:
    if name in local:
        return True
    if ":" not in name.rsplit("/", 1)[-1]:          # không ghi tag → chấp nhận mọi tag
        return any(k.rsplit(":", 1)[0] == name for k in local)
    return False


def missing_images(ctx: dict, include_optional: bool = False) -> list[dict]:
    local = local_images(ctx)
    return [im for im in REQUIRED_IMAGES
            if (include_optional or not im.get("optional")) and not image_present(im["name"], local)]


def check_images(ctx: dict) -> dict:
    t = "Image Docker của các tool"
    if not docker_up(ctx):
        return _need_docker("images", t)
    local = local_images(ctx)
    missing = missing_images(ctx)
    opt_missing = [im["name"] for im in REQUIRED_IMAGES if im.get("optional") and not image_present(im["name"], local)]
    required_n = len([im for im in REQUIRED_IMAGES if not im.get("optional")])
    extra = {"missing": [im["name"] for im in missing], "optional_missing": opt_missing,
             "present": required_n - len(missing), "required": required_n}
    if not missing:
        note = f" CodeQL tuỳ chọn chưa build: {', '.join(opt_missing)}." if opt_missing else ""
        return item("images", t, "ok", f"{required_n}/{required_n} image bắt buộc có sẵn.{note}", **extra)
    pulls = [im["name"] for im in missing if im["kind"] == "pull"]
    builds = [f"{im['name']} (build từ {im['dir']}, ~5–10 phút)" for im in missing if im["kind"] == "build"]
    parts = []
    if pulls:
        parts.append("cần pull: " + ", ".join(pulls))
    if builds:
        parts.append("cần BUILD: " + ", ".join(builds))
    return item("images", t, "fix", f"Thiếu {len(missing)}/{required_n} image — " + "; ".join(parts) + ".",
                "pull_images", **extra)


def check_images_pinned(ctx: dict) -> dict:
    t = "Image ghim phiên bản (tái lập)"
    if not docker_up(ctx):
        return _need_docker("images_pinned", t)
    local = local_images(ctx)
    latest = [im["name"] for im in REQUIRED_IMAGES if im["name"].endswith(":latest") or ":" not in im["name"].rsplit("/", 1)[-1]]
    digests = {}
    for name in latest:
        if name in local and local[name] and local[name] != "<none>":
            digests[name] = local[name]
        else:
            for k, d in local.items():
                if k.rsplit(":", 1)[0] == name.rsplit(":", 1)[0] and d and d != "<none>":
                    digests[name] = d
    extra = {"latest": latest, "digests": digests}
    if latest:
        return item("images_pinned", t, "warn",
                    f"{len(latest)} image dùng tag trôi (:latest / không tag): {', '.join(latest)}. "
                    "Phiên bản thật được ghi vào run_meta.tools_json (digest) để tái lập; "
                    "đừng `docker pull` giữa hai run cần so sánh.", **extra)
    return item("images_pinned", t, "ok", "Mọi image đều ghim tag cố định.", **extra)


def check_max_map_count(ctx: dict) -> dict:
    t = "vm.max_map_count (SonarQube/Elasticsearch)"
    if IS_WIN:
        if not shutil.which("wsl"):
            return item("max_map_count", t, "warn", "Không có wsl.exe — không đọc được.")
        if not docker_up(ctx):
            return item("max_map_count", t, "warn", "Cần Docker Desktop chạy (distro docker-desktop) để đọc.")
        rc, out, err = run_cmd(["wsl", "-d", "docker-desktop", "sysctl", "-n", "vm.max_map_count"],
                               timeout=ctx.get("wsl_timeout", WSL_TIMEOUT))
        src = "wsl -d docker-desktop"
    else:
        try:
            out = Path("/proc/sys/vm/max_map_count").read_text(encoding="utf-8").strip()
            rc, err = 0, ""
        except OSError as e:
            rc, out, err = -1, "", str(e)
        src = "/proc/sys/vm/max_map_count"
    try:
        val = int(out.strip().split()[-1])
    except (ValueError, IndexError):
        return item("max_map_count", t, "warn",
                    f"Không đọc được ({src}, rc={rc}: {(err or out)[:120]}). Sonar vẫn chạy được vì "
                    "SONAR_ES_BOOTSTRAP_CHECKS_DISABLE=true; nếu Sonar không UP hãy đặt 262144.")
    if val >= MIN_MAX_MAP_COUNT:
        return item("max_map_count", t, "ok", f"{val} ≥ {MIN_MAX_MAP_COUNT}.", value=val)
    fix_cmd = ("wsl -d docker-desktop sysctl -w vm.max_map_count=262144" if IS_WIN
               else "sudo sysctl -w vm.max_map_count=262144")
    return item("max_map_count", t, "warn",
                f"{val} < {MIN_MAX_MAP_COUNT}: Elasticsearch của Sonar có thể không khởi động. Sửa: `{fix_cmd}` "
                "(reset sau reboot).", "max_map_count" if IS_WIN else None, value=val)


def _tcp_ok(host: str, port: int = 443, timeout: float = NET_TIMEOUT) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, ""
    except OSError as e:
        return False, str(e)


def check_network(ctx: dict) -> dict:
    t = "Mạng tới GitHub & Docker Hub"
    hosts = ctx.get("net_hosts") or ("github.com", "registry-1.docker.io")
    results = {h: _tcp_ok(h, 443, ctx.get("net_timeout", NET_TIMEOUT)) for h in hosts}
    bad = [h for h, (ok, _) in results.items() if not ok]
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""
    extra = {"reachable": [h for h in hosts if h not in bad], "unreachable": bad, "proxy": proxy}
    if not bad:
        return item("network", t, "ok", "Kết nối 443 tới " + ", ".join(hosts) + " OK." + (f" (proxy {proxy})" if proxy else ""),
                    **extra)
    detail = "Không kết nối được: " + "; ".join(f"{h} ({results[h][1][:60]})" for h in bad) + "."
    if proxy:
        detail += f" Proxy hiện tại: {proxy} — Docker Desktop cần cấu hình proxy riêng (Settings → Resources → Proxies)."
    else:
        detail += " Nếu dùng proxy công ty, đặt HTTPS_PROXY và cấu hình proxy cho Docker Desktop."
    level = "bad" if len(bad) == len(hosts) else "warn"
    return item("network", t, level, detail, **extra)


def check_webview2(ctx: dict) -> dict:
    t = "WebView2 runtime (giao diện)"
    if not IS_WIN:
        return item("webview2", t, "ok", "Không áp dụng ngoài Windows (pywebview dùng GTK/Qt hoặc fallback trình duyệt).")
    try:
        import winreg  # noqa: PLC0415
    except ImportError:
        return item("webview2", t, "warn", "Không đọc được registry (thiếu winreg).")
    for root, key in ((winreg.HKEY_LOCAL_MACHINE, WEBVIEW2_KEY), (winreg.HKEY_CURRENT_USER, WEBVIEW2_KEY_USER)):
        try:
            with winreg.OpenKey(root, key) as k:
                pv, _ = winreg.QueryValueEx(k, "pv")
                if pv and str(pv) not in ("0.0.0.0", ""):
                    return item("webview2", t, "ok", f"WebView2 Evergreen {pv}.", version=str(pv))
        except OSError:
            continue
    return item("webview2", t, "warn",
                "Chưa thấy WebView2 runtime. App sẽ mở bằng trình duyệt mặc định. Cài Evergreen: "
                "https://developer.microsoft.com/microsoft-edge/webview2/ (bootstrapper).")


CHECKS = {
    "os_wsl2": check_os_wsl2,
    "docker_installed": check_docker_installed,
    "docker_daemon": check_docker_daemon,
    "docker_mem": check_docker_mem,
    "sonar_port": check_sonar_port,
    "disk_free": check_disk_free,
    "git": check_git,
    "git_longpaths": check_git_longpaths,
    "images": check_images,
    "images_pinned": check_images_pinned,
    "max_map_count": check_max_map_count,
    "network": check_network,
    "webview2": check_webview2,
}

def run_check(cid: str, ctx: dict) -> dict:
    """Chạy 1 check; mọi exception → bad + detail (không bao giờ raise)."""
    fn = CHECKS[cid]
    try:
        return fn(ctx)
    except Exception as e:  # noqa: BLE001
        return item(cid, cid, "bad", f"Lỗi nội bộ khi kiểm tra: {type(e).__name__}: {e}")


def invalidate(ctx: dict, *keys: str) -> None:
    """Xoá cache trong ctx sau khi fix (vd docker_info sau start_docker)."""
    for k in keys or ("docker_info", "docker_ports", "local_images"):
        ctx.pop(k, None)


__all__ = ["CHECKS", "CHECK_ORDER", "REQUIRED_IMAGES", "run_check", "run_cmd", "docker_info", "docker_up",
           "port_busy", "docker_published_ports", "local_images", "missing_images", "invalidate", "item",
           "IS_WIN"]
