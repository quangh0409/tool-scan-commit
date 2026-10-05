"""API Settings (CONTRACTS §9): settings.json, dung lượng + dọn dẹp, profile, lệnh shell.

Bảng route → hàm (A4 map):
  GET  /api/settings                      get_settings
  POST /api/settings {…}                  set_settings
  GET  /api/storage                       storage
  POST /api/clean {items[], dry_run}      clean          (409 khi run đang chạy dùng path; forbidden → 400)
  GET  /api/profiles                      list_profiles
  POST /api/profiles {name, profile}      save_profile
  GET  /api/profiles/{name}               get_profile
  DELETE /api/profiles/{name}             delete_profile
  GET  /api/shell?profile=&shell=         shell
Vị trí: `%SECJIT_HOME%` (= registry.home()): settings.json, profiles/<name>.json.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import api_common as C
from .errors import ApiError, bad_request, conflict, not_found

SETTINGS_KEYS = ("language", "out_dir", "work_dir", "sonar_port", "codeql_ram_mb", "m2_volume")
LANGS = ("vi", "en")
SAFETY = {"pool": "safe", "clone": "safe", "m2": "slow", "images": "rebuild", "results": "forbidden", "runs": "safe"}
IMAGE_KEYS = ("gitleaks", "trufflehog", "semgrep", "bearer", "horusec", "maven", "sonarqube", "sonar-scanner",
              "findsecbugs", "codeql")
_SIZE_RE = re.compile(r"^\s*([0-9.]+)\s*([KMGT]?i?B)\s*$", re.I)
_MULT = {"B": 1, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12, "KIB": 1024, "MIB": 1024 ** 2, "GIB": 1024 ** 3, "TIB": 1024 ** 4}


# ----------------------------------------------------------------------------- settings.json
def _settings_path() -> Path:
    return C.home() / "settings.json"


def defaults() -> dict:
    home = C.home()
    return {"language": "vi", "out_dir": str(home / "results"), "work_dir": str(home / "work"),
            "sonar_port": int(os.environ.get("ORCH_SONAR_PORT") or 9000), "codeql_ram_mb": 5000, "m2_volume": True}


def get_settings(params: dict | None = None, body: dict | None = None) -> dict:
    d = defaults()
    try:
        with open(_settings_path(), encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            d.update({k: raw[k] for k in SETTINGS_KEYS if k in raw})
    except (OSError, ValueError):
        pass
    d["path"] = str(_settings_path())
    return d


def _validate_settings(d: dict) -> dict:
    out = {}
    lang = str(d.get("language") or "vi")
    if lang not in LANGS:
        raise bad_request(f"language phải thuộc {LANGS}")
    out["language"] = lang
    for k in ("out_dir", "work_dir"):
        v = str(d.get(k) or "").strip()
        if not v:
            raise bad_request(f"{k} trống")
        out[k] = v
    if Path(out["out_dir"]).resolve() == Path(out["work_dir"]).resolve():
        raise bad_request("out_dir không được trùng work_dir", "dọn dẹp work sẽ xoá nhầm kết quả")
    out["sonar_port"] = C.to_int(d.get("sonar_port"), 9000, lo=1024, hi=65535, name="sonar_port")
    out["codeql_ram_mb"] = C.to_int(d.get("codeql_ram_mb"), 5000, lo=1024, hi=262144, name="codeql_ram_mb")
    out["m2_volume"] = C.to_bool(d.get("m2_volume"), True)
    return out


def set_settings(params: dict | None = None, body: dict | None = None) -> dict:
    cur = get_settings()
    cur.pop("path", None)
    merged = {**cur, **{k: v for k, v in (body or {}).items() if k in SETTINGS_KEYS}}
    val = _validate_settings(merged)
    C.ensure_src_on_path()
    import registry
    registry.atomic_write_json(_settings_path(), val)
    val["path"] = str(_settings_path())
    val["ok"] = True
    return val


# ----------------------------------------------------------------------------- storage
def _dir_size(p: Path) -> int:
    C.ensure_src_on_path()
    from orchestrator import control
    return control.dir_size(p)


def _parse_size(s: str) -> int:
    m = _SIZE_RE.match(s or "")
    if not m:
        return 0
    return int(float(m.group(1)) * _MULT.get(m.group(2).upper(), 1))


def _docker_images(timeout: float = 8) -> list[dict]:
    """[{repo_tag, id, bytes}] của image tool (docker có trong PATH); lỗi/không có → []."""
    if not shutil.which("docker"):
        return []
    try:
        r = subprocess.run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}|{{.ID}}|{{.Size}}"],
                           capture_output=True, text=True, errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode != 0:
        return []
    out = []
    for line in (r.stdout or "").splitlines():
        parts = line.strip().split("|")
        if len(parts) != 3:
            continue
        name = parts[0]
        if any(k in name.lower() for k in IMAGE_KEYS):
            out.append({"repo_tag": name, "id": parts[1], "bytes": _parse_size(parts[2])})
    return out


def _docker_volume_bytes(name: str, timeout: float = 8) -> int | None:
    if not shutil.which("docker"):
        return None
    try:
        r = subprocess.run(["docker", "system", "df", "-v", "--format", "{{json .}}"], capture_output=True,
                           text=True, errors="replace", timeout=timeout)
        if r.returncode != 0:
            return None
        for line in (r.stdout or "").splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            for v in d.get("Volumes") or []:
                if v.get("Name") == name:
                    return _parse_size(v.get("Size", "0B"))
    except (OSError, subprocess.SubprocessError, AttributeError):
        return None
    return None


def _running_works() -> set[str]:
    C.ensure_src_on_path()
    import registry
    try:
        registry.refresh_status()
    except Exception:  # noqa: BLE001
        pass
    return {str(Path(r["work"]).resolve()) for r in registry.load().get("runs", [])
            if r.get("status") == "running" and r.get("work")}


_STORAGE_CACHE: dict = {"at": 0.0, "data": None}
_STORAGE_LOCK = threading.Lock()
STORAGE_TTL_S = 30


def storage(params: dict | None = None, body: dict | None = None) -> dict:
    """Dung lượng theo mục. Lỗi thật 2026-10-05: khi Docker đang build, `docker system df -v` + `docker images`
    chạy NỐI TIẾP (15 s timeout mỗi lệnh) + duyệt thư mục -> vượt 60 s của GUI ("Hết thời gian chờ").
    Nay: 2 lệnh docker chạy SONG SONG với nhau và với việc duyệt thư mục, mỗi lệnh ≤ 8 s; Docker bận -> mục
    đó ghi "Docker đang bận" chứ không chặn cả màn; kết quả nhớ 30 s (`?refresh=1` để tính lại)."""
    refresh = str((params or {}).get("refresh") or "") in ("1", "true")
    with _STORAGE_LOCK:
        c = _STORAGE_CACHE
        if not refresh and c["data"] is not None and time.time() - c["at"] < STORAGE_TTL_S:
            return dict(c["data"], cached=True)
        data = _storage_compute()
        c["data"], c["at"] = data, time.time()
        return dict(data, cached=False)


def _storage_compute() -> dict:
    s = get_settings()
    pool = ThreadPoolExecutor(max_workers=2)
    f_vol = pool.submit(_docker_volume_bytes, "secjit-m2") if s.get("m2_volume") else None
    f_img = pool.submit(_docker_images)
    pool.shutdown(wait=False)
    work = Path(s["work_dir"])
    out_dir = Path(s["out_dir"])
    items: list[dict] = []
    pool_dirs = sorted(work.glob("pool_*")) if work.exists() else []
    items.append({"id": "pool", "title": "Pool clone rác", "path": str(work / "pool_*"), "safety": "safe",
                  "bytes": sum(_dir_size(p) for p in pool_dirs), "count": len(pool_dirs), "detail": "còn lại từ run bị ngắt"})
    clones = [p for p in work.iterdir() if p.is_dir() and "__" in p.name and not p.name.startswith("pool_")] if work.exists() else []
    items.append({"id": "clone", "title": "Clone repo", "path": str(work / "<owner__repo>"), "safety": "safe",
                  "bytes": sum(_dir_size(p) for p in clones), "count": len(clones),
                  "detail": ", ".join(p.name for p in clones[:5]) + (" …" if len(clones) > 5 else "") or "clone lại khi cần"})
    m2_dir = work / ".m2cache"
    vol = f_vol.result() if f_vol is not None else None
    items.append({"id": "m2", "title": "Cache Maven", "path": "docker volume secjit-m2" if vol is not None else str(m2_dir),
                  "safety": "slow", "bytes": (vol or 0) + (_dir_size(m2_dir) if m2_dir.exists() else 0),
                  "detail": "xoá sẽ làm build chậm 3–5 lần"})
    imgs = f_img.result()
    items.append({"id": "images", "title": "Image Docker", "path": ", ".join(i["repo_tag"] for i in imgs[:6]) + (" …" if len(imgs) > 6 else ""),
                  "safety": "rebuild", "bytes": sum(i["bytes"] for i in imgs), "count": len(imgs),
                  "detail": "tải/build lại khi dùng" if imgs else "Docker đang bận/không chạy — chưa đo được (thử lại sau)"})
    run_dirs = [p for p in work.iterdir() if p.is_dir() and p.name.startswith("r-")] if work.exists() else []
    items.append({"id": "runs", "title": "Log/progress các run", "path": str(work / "r-*"), "safety": "safe",
                  "bytes": sum(_dir_size(p) for p in run_dirs), "count": len(run_dirs),
                  "detail": "run.log, progress.jsonl, profile — xoá thì không resume được run đó"})
    res_info = _results_info(out_dir)
    items.append({"id": "results", "title": "Kết quả đã xuất (DB + export)", "path": str(out_dir), "safety": "forbidden",
                  "bytes": _dir_size(out_dir) if out_dir.exists() else 0, "detail": res_info["detail"], **res_info["counts"]})
    total = sum(i["bytes"] for i in items)
    free = None
    for probe in (work, out_dir, C.home(), Path.cwd()):
        try:
            free = shutil.disk_usage(probe if probe.exists() else probe.anchor or Path.cwd()).free
            break
        except OSError:
            continue
    return {"items": items, "total_bytes": total, "free_bytes": free, "work_dir": str(work), "out_dir": str(out_dir),
            "docker": bool(shutil.which("docker"))}


def _results_info(out_dir: Path) -> dict:
    """Đếm DB/export/mục khác trong thư mục kết quả. `-wal`/`-shm` (file phụ SQLite, thường 0 byte), `.lock`, `.bak`
    KHÔNG tính là 'dữ liệu lạ'."""
    dbs = exports = 0
    stray: list[str] = []
    if out_dir.exists():
        for p in out_dir.iterdir():
            n = p.name.lower()
            if p.is_dir():
                if n.startswith("export") or (p / "run_manifest.json").exists():
                    exports += 1
                elif n in ("work", "scratch", "diagnostics", "profiles"):
                    continue
                else:
                    stray.append(p.name)
            elif n.endswith((".sqlite", ".db")):
                dbs += 1
            elif n.endswith(("-wal", "-shm", ".lock", ".bak", ".json", ".log", ".txt", ".md")):
                continue
            else:
                stray.append(p.name)
    detail = f"{dbs} DB · {exports} export — không bao giờ tự xoá" + (f" · {len(stray)} mục khác: {', '.join(stray[:3])}" if stray else "")
    return {"detail": detail if out_dir.exists() else "chưa có thư mục kết quả",
            "counts": {"dbs": dbs, "exports": exports, "stray": stray[:20]}}


# ----------------------------------------------------------------------------- clean
def _repos_known() -> list[str]:
    C.ensure_src_on_path()
    import registry
    seen = []
    for r in registry.load().get("runs", []):
        if r.get("repo") and r["repo"] not in seen:
            seen.append(r["repo"])
    return seen


def clean(params: dict | None = None, body: dict | None = None) -> dict:
    body = body or {}
    items = body.get("items")
    dry = C.to_bool(body.get("dry_run"), True)
    if not isinstance(items, list) or not items:
        raise bad_request("items phải là danh sách không rỗng")
    bad = [i for i in items if i not in SAFETY]
    if bad:
        raise bad_request(f"mục lạ: {bad}", f"hợp lệ: {sorted(SAFETY)}")
    if "results" in items:
        raise bad_request("'results' là mục forbidden — GUI không bao giờ xoá kết quả", "xoá tay nếu thật sự muốn")
    s = get_settings()
    work = Path(s["work_dir"])
    if items and {"pool", "clone", "m2", "runs"} & set(items):
        running = _running_works()
        if running and (str(work.resolve()) in running or "runs" in items or "clone" in items):
            raise conflict("Có run đang chạy dùng thư mục làm việc này", "Dừng run (Dừng an toàn) trước khi dọn")
    C.ensure_src_on_path()
    from orchestrator import control
    if not dry:
        _STORAGE_CACHE["data"] = None   # xoá thật -> màn Dung lượng phải đo lại
    plan = {"would_delete": [], "errors": [], "items": list(items)}
    ctl_items = [(k, None) for k in items if k in ("pool", "m2")]
    if ctl_items:
        p = control.clean_plan(_repos_known()[0] if _repos_known() else "https://github.com/x/y", ctl_items, work=work)
        plan["would_delete"] += p["would_delete"]
        plan["errors"] += p["errors"]
    if "clone" in items:
        repos = _repos_known()
        if repos:
            for repo in repos:
                p = control.clean_plan(repo, [("clone", None)], work=work)
                plan["would_delete"] += p["would_delete"]
                plan["errors"] += p["errors"]
        elif work.exists():
            for d in work.iterdir():
                if d.is_dir() and "__" in d.name and not d.name.startswith("pool_"):
                    plan["would_delete"].append({"path": str(d), "bytes": _dir_size(d), "item": "clone"})
    if "runs" in items and work.exists():
        for d in work.iterdir():
            if d.is_dir() and d.name.startswith("r-"):
                plan["would_delete"].append({"path": str(d), "bytes": _dir_size(d), "item": "runs"})
    images = _docker_images() if "images" in items else []
    for i in images:
        plan["would_delete"].append({"path": f"docker image {i['repo_tag']}", "bytes": i["bytes"], "item": "images", "image_id": i["id"]})
    if dry:
        return {"would_delete": plan["would_delete"], "deleted": [], "errors": plan["errors"], "dry_run": True}
    fs_plan = {"would_delete": [d for d in plan["would_delete"] if d.get("item") != "images"], "errors": plan["errors"]}
    res = control.clean_apply(fs_plan)
    for i in images:
        try:
            r = subprocess.run(["docker", "rmi", "-f", i["id"]], capture_output=True, text=True, errors="replace", timeout=120)
            if r.returncode == 0:
                res["deleted"].append({"path": f"docker image {i['repo_tag']}", "bytes": i["bytes"], "item": "images"})
            else:
                res["errors"].append(f"docker rmi {i['repo_tag']}: {(r.stderr or '').strip()[:200]}")
        except (OSError, subprocess.SubprocessError) as e:
            res["errors"].append(f"docker rmi {i['repo_tag']}: {e}")
    return {"would_delete": plan["would_delete"], "deleted": res["deleted"], "errors": res["errors"], "dry_run": False}


# ----------------------------------------------------------------------------- profiles
def _profiles_dir() -> Path:
    return C.home() / "profiles"


def _profile_path(name: str) -> Path:
    return _profiles_dir() / f"{C.safe_name(name, 'tên profile')}.json"


def list_profiles(params: dict | None = None, body: dict | None = None) -> dict:
    d = _profiles_dir()
    out = []
    if d.exists():
        for p in sorted(d.glob("*.json")):
            try:
                with open(p, encoding="utf-8") as f:
                    prof = json.load(f)
            except (OSError, ValueError):
                prof = {}
            out.append({"name": p.stem, "repo": prof.get("repo"), "branch": prof.get("branch"),
                        "scope": prof.get("scope"), "experiment": bool((prof.get("experiment") or {}).get("enabled")),
                        "saved": _mtime_iso(p), "path": str(p)})
    out.sort(key=lambda x: x["saved"] or "", reverse=True)
    return {"profiles": out, "dir": str(d)}


def _mtime_iso(p: Path) -> str | None:
    try:
        import time
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(p.stat().st_mtime))
    except OSError:
        return None


def get_profile(params: dict, body: dict | None = None) -> dict:
    p = _profile_path(str(params.get("name") or ""))
    if not p.exists():
        raise not_found(f"profile {p.stem!r}")
    try:
        with open(p, encoding="utf-8") as f:
            return {"name": p.stem, "profile": json.load(f), "path": str(p)}
    except (OSError, ValueError) as e:
        raise ApiError(500, "EPROFILE", f"profile hỏng: {e}") from e


def save_profile(params: dict | None = None, body: dict | None = None) -> dict:
    body = body or {}
    name = str(body.get("name") or (params or {}).get("name") or "").strip()
    prof = body.get("profile")
    if not isinstance(prof, dict):
        raise bad_request("thiếu body.profile")
    p = _profile_path(name)
    C.ensure_src_on_path()
    from orchestrator import profile as _profile
    errs = _profile.validate(prof)
    if errs:
        raise bad_request("profile không hợp lệ: " + "; ".join(errs))
    overwritten = p.exists()
    _profile.save(prof, p)
    return {"ok": True, "name": p.stem, "path": str(p), "overwritten": overwritten}


def delete_profile(params: dict, body: dict | None = None) -> dict:
    p = _profile_path(str(params.get("name") or ""))
    if not p.exists():
        raise not_found(f"profile {p.stem!r}")
    try:
        p.unlink()
    except OSError as e:
        raise ApiError(500, "EIO", f"không xoá được: {e}") from e
    return {"ok": True, "name": p.stem}


# ----------------------------------------------------------------------------- shell
def shell(params: dict, body: dict | None = None) -> dict:
    sh = str(params.get("shell") or (body or {}).get("shell") or "powershell").lower()
    if sh not in ("powershell", "bash"):
        raise bad_request("shell phải là powershell|bash")
    prof = (body or {}).get("profile")
    if not isinstance(prof, dict):
        ref = str(params.get("profile") or (body or {}).get("profile") or "").strip()
        if not ref:
            raise bad_request("cần profile (tên đã lưu, đường dẫn file, hoặc object trong body)")
        p = Path(ref)
        if not p.exists():
            p = _profile_path(ref)
        if not p.exists():
            raise not_found(f"profile {ref!r}")
        try:
            with open(p, encoding="utf-8") as f:
                prof = json.load(f)
        except (OSError, ValueError) as e:
            raise bad_request(f"profile hỏng: {e}") from e
    C.ensure_src_on_path()
    from orchestrator import profile as _profile
    errs = _profile.validate(prof)
    if errs:
        raise bad_request("profile không hợp lệ: " + "; ".join(errs))
    return {"shell": sh, "command": _profile.to_shell(prof, sh)}
