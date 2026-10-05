"""Gói chẩn đoán (CONTRACTS §9 `GET /api/diagnostics`, TASKS §5 A2): 1 file ZIP cho 1 run. Stdlib-only.

Nội dung (có gì gói nấy, thiếu ghi vào `manifest.json`):
  run.log · progress.jsonl · meta.json · pid · stop   (từ `<work>/<run_id>/`)
  profile.json                                      (--profile hoặc meta.profile)
  run_meta.json · kappa.json                        (DB mở CHỈ-ĐỌC, DB từ profile.paths.db / ORCH_SQLITE)
  docker_info.txt · docker_version.txt · docker_ps.txt (`--filter label=orch.run=<id>`; mock được)
  preflight.json                                    (`<work>/<run_id>/`, `%LOCALAPPDATA%/secjit/`, cwd)
  env.json · system.json · manifest.json
Che bí mật: biến env tên khớp TOKEN|PAT|SECRET|PASSW|API_KEY|CREDENTIAL|GITHUB_TOKEN (giá trị thay bằng ***)
và mọi file text được thay giá trị bí mật đó (nếu lọt vào log) bằng ***. `pip freeze` KHÔNG cần (stdlib-only).
"""
from __future__ import annotations

import json
import os
import platform
import re
import sqlite3
import sys
import time
import zipfile
from pathlib import Path

from . import config

SECRET_KEY_RE = re.compile(r"(TOKEN|_PAT$|^PAT$|SECRET|PASSW|_PW$|PWD|API_KEY|CREDENTIAL|AUTH)", re.IGNORECASE)
MIN_SECRET_LEN = 6
MAX_LOG_BYTES = 20 * 1024 * 1024       # chỉ lấy 20 MB cuối của run.log


def is_secret_key(key: str) -> bool:
    return bool(SECRET_KEY_RE.search(key or ""))


def secret_values(env: dict | None = None) -> list[str]:
    env = os.environ if env is None else env
    vals = [v for k, v in env.items() if is_secret_key(k) and v and len(v) >= MIN_SECRET_LEN]
    return sorted(set(vals), key=len, reverse=True)       # dài trước để không che nửa chuỗi


def redact_env(env: dict | None = None, keep_prefixes=("ORCH_", "SECJIT_", "PYTHON", "LOCALAPPDATA", "PATH",
                                                        "DOCKER_", "WSL", "JAVA_HOME", "TEMP", "TMP")) -> dict:
    """Chỉ giữ biến liên quan; giá trị bí mật -> '***'."""
    env = os.environ if env is None else env
    out = {}
    for k, v in sorted(env.items()):
        if not any(k.upper().startswith(p) for p in keep_prefixes):
            continue
        out[k] = "***" if is_secret_key(k) else v
    return out


def redact_text(text: str, secrets: list[str]) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text


def _docker(args: list[str]):
    from .tools.base import docker_run
    try:
        p = docker_run(args, timeout=60)
        return (p.stdout or "") + (("\n[stderr]\n" + p.stderr) if p.stderr else ""), p.returncode
    except Exception as e:  # noqa: BLE001 — docker tắt/không có vẫn gói được phần còn lại
        return f"(docker không chạy được: {e})", 127


def _run_meta_json(db: Path) -> tuple[list[dict], list[dict], str | None]:
    """(run_meta rows, kappa rows, error). Mở mode=ro, không migrate, không lock."""
    try:
        conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as e:
        return [], [], str(e)
    try:
        tabs = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        rm, kp = [], []
        if "run_meta" in tabs:
            cur = conn.execute("SELECT * FROM run_meta ORDER BY id")
            cols = [c[0] for c in cur.description]
            rm = [dict(zip(cols, r)) for r in cur.fetchall()]
        if "kappa" in tabs:
            cur = conn.execute("SELECT * FROM kappa")
            cols = [c[0] for c in cur.description]
            kp = [dict(zip(cols, r)) for r in cur.fetchall()]
        return rm, kp, None
    except sqlite3.Error as e:
        return [], [], str(e)
    finally:
        conn.close()


def _tail_bytes(p: Path, limit: int) -> bytes:
    size = p.stat().st_size
    with open(p, "rb") as f:
        if size > limit:
            f.seek(size - limit)
            return b"...(cat " + str(size - limit).encode() + b" byte dau)...\n" + f.read()
        return f.read()


def collect(run_id: str, out_zip: str | Path, profile_path: str | Path | None = None,
            work: str | Path | None = None, env: dict | None = None) -> dict:
    """Gói chẩn đoán -> ZIP. Trả manifest {run_id, zip, files[], missing[], redacted_keys[]}."""
    env = os.environ if env is None else env
    secrets = secret_values(env)
    work = Path(work or config.WORK_DIR)
    rdir = work / str(run_id)
    out_zip = Path(out_zip)
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    files: list[str] = []
    missing: list[str] = []
    notes: dict = {}

    def _put(zf: zipfile.ZipFile, arc: str, data: bytes | str):
        if isinstance(data, str):
            data = redact_text(data, secrets).encode("utf-8")
        else:
            try:
                data = redact_text(data.decode("utf-8", errors="replace"), secrets).encode("utf-8")
            except Exception:  # noqa: BLE001
                pass
        zf.writestr(arc, data)
        files.append(arc)

    def _put_file(zf, src: Path, arc: str, tail: int | None = None):
        if src.exists() and src.is_file():
            _put(zf, arc, _tail_bytes(src, tail) if tail else src.read_bytes())
        else:
            missing.append(arc)

    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 1) thư mục run
        _put_file(zf, rdir / "run.log", "run.log", tail=MAX_LOG_BYTES)
        _put_file(zf, rdir / "progress.jsonl", "progress.jsonl")
        _put_file(zf, rdir / "meta.json", "meta.json")
        _put_file(zf, rdir / "pid", "pid")
        _put_file(zf, rdir / "stop", "stop")
        meta: dict = {}
        if (rdir / "meta.json").exists():
            try:
                meta = json.loads((rdir / "meta.json").read_text(encoding="utf-8"))
            except ValueError:
                notes["meta_json"] = "hỏng"
        # 2) profile
        pp = Path(profile_path) if profile_path else (Path(meta["profile"]) if meta.get("profile") else None)
        profile: dict = {}
        if pp is not None:
            _put_file(zf, pp, "profile.json")
            if pp.exists():
                try:
                    profile = json.loads(pp.read_text(encoding="utf-8"))
                except ValueError:
                    notes["profile"] = "hỏng"
        else:
            missing.append("profile.json")
        # 3) DB -> run_meta/kappa
        db = (profile.get("paths") or {}).get("db") or meta.get("db") or env.get("ORCH_SQLITE") or str(config.SQLITE_PATH)
        dbp = Path(db)
        if dbp.exists():
            rm, kp, err = _run_meta_json(dbp)
            _put(zf, "run_meta.json", json.dumps({"db": str(dbp), "error": err, "rows": rm}, ensure_ascii=False,
                                                 indent=2, default=str))
            _put(zf, "kappa.json", json.dumps(kp, ensure_ascii=False, indent=2, default=str))
        else:
            missing += ["run_meta.json", "kappa.json"]
            notes["db"] = f"không tồn tại: {dbp}"
        # 4) docker
        for arc, args in (("docker_version.txt", ["version"]), ("docker_info.txt", ["info"]),
                          ("docker_ps.txt", ["ps", "-a", "--filter", f"label=orch.run={run_id}", "--no-trunc"])):
            out, rc = _docker(args)
            _put(zf, arc, f"$ docker {' '.join(args)}\n(rc={rc})\n{out}")
        # 5) preflight.json
        cands = [rdir / "preflight.json", Path.cwd() / "preflight.json"]
        if env.get("LOCALAPPDATA"):
            cands.append(Path(env["LOCALAPPDATA"]) / "secjit" / "preflight.json")
        if env.get("SECJIT_HOME"):
            cands.append(Path(env["SECJIT_HOME"]) / "preflight.json")
        pf = next((c for c in cands if c.exists()), None)
        if pf:
            _put_file(zf, pf, "preflight.json")
        else:
            missing.append("preflight.json")
        # 6) env + system + manifest
        _put(zf, "env.json", json.dumps(redact_env(env), ensure_ascii=False, indent=2))
        _put(zf, "system.json", json.dumps({
            "platform": platform.platform(), "python": sys.version, "app_version": config.APP_VERSION,
            "orchestrator_root": str(config.ROOT), "work_dir": str(work), "run_dir": str(rdir),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "line_window": config.LINE_WINDOW,
            "params_v1": config.params_v1(), "experiment": config.experiment_info(),
        }, ensure_ascii=False, indent=2, default=str))
        manifest = {"run_id": str(run_id), "zip": str(out_zip), "files": list(files) + ["manifest.json"],
                    "missing": missing, "notes": notes,
                    "redacted_keys": sorted(k for k in env if is_secret_key(k))}
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    manifest["bytes"] = out_zip.stat().st_size
    return manifest


def format_text(m: dict) -> str:
    return (f"diagnostics run={m['run_id']} -> {m['zip']} ({m['bytes']:,} B)\n"
            f"  có: {', '.join(m['files'])}\n  thiếu: {', '.join(m['missing']) or '-'}\n"
            f"  che bí mật: {', '.join(m['redacted_keys']) or '-'}")
