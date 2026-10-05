"""API Runs (CONTRACTS §9/§12): registry + progress + start/stop/resume + gói chẩn đoán.

Bảng route → hàm (A4 map):
  GET  /api/runs                       list_runs
  GET  /api/run/{id}/progress          get_progress_lines   (params.since=<số dòng đã có>; SSE: A4 lặp gọi)
  POST /api/run/{id}/stop {force}      run_stop
  POST /api/run/{id}/resume {workers?} run_resume
  POST /api/run/start {profile, smoke} run_start
  GET  /api/diagnostics?run_id=        diagnostics          (trả {path} zip; A4 stream file)
"""
from __future__ import annotations

import copy
import json
import platform
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from . import api_common as C
from .errors import ApiError, bad_request, conflict, not_found


# ----------------------------------------------------------------------------- summary từ DB
def _summary_from_db(db: str | None, run_id: str) -> dict:
    """Đếm nhãn/κ/commit từ DB chỉ-đọc; không mở được → {}. Không bao giờ raise."""
    if not db or not Path(db).exists():
        return {}
    try:
        with C.ro_conn(db) as conn:
            tabs = C.tables(conn)
            s: dict = {}
            if "findings" in tabs:
                have = C.columns(conn, "findings")
                col = "label" if "label" in have else "silver_label"
                lab = dict(conn.execute(f"SELECT COALESCE({col},'candidate'), COUNT(*) FROM findings GROUP BY 1"))
                s.update({"gold": int(lab.get("gold", 0)), "silver": int(lab.get("silver", 0)),
                          "candidate": int(lab.get("candidate", 0)), "clusters": sum(int(v) for v in lab.values())})
                positive = {r[0] for r in conn.execute("SELECT DISTINCT commit_id FROM findings WHERE finding_in_diff=1")}
            else:
                positive = set()
            universe = {r[0] for r in conn.execute("SELECT DISTINCT commit_id FROM scanned_files")} if "scanned_files" in tabs else set()
            ok: dict[str, int] = {}
            if "selected_commits" in tabs and "n_expensive_ok" in C.columns(conn, "selected_commits"):
                ok = dict(conn.execute("SELECT commit_id, COALESCE(n_expensive_ok,0) FROM selected_commits"))
            elif "expensive_runs" in tabs:
                ok = dict(conn.execute("SELECT commit_id, COUNT(DISTINCT tool) FROM expensive_runs "
                                       "WHERE phase='analyze' AND status='ok' GROUP BY commit_id"))
            neg = universe - positive
            s["verified_clean"] = sum(1 for c in neg if ok.get(c, 0) >= 2)
            s["cheap_clean"] = len(neg) - s["verified_clean"]
            s["commits"] = conn.execute("SELECT COUNT(*) FROM scan_done").fetchone()[0] if "scan_done" in tabs else len(universe)
            if "selected_commits" in tabs:
                s["selected"] = dict(conn.execute("SELECT COALESCE(status,'pending'), COUNT(*) FROM selected_commits GROUP BY 1"))
            s["kappa"] = None
            if "kappa" in tabs:
                r = conn.execute("SELECT value FROM kappa WHERE scope='total' AND run_id=? ORDER BY computed_at DESC LIMIT 1",
                                 [run_id]).fetchone() or conn.execute(
                    "SELECT value FROM kappa WHERE scope='total' ORDER BY computed_at DESC LIMIT 1").fetchone()
                s["kappa"] = r[0] if r else None
            from .api_results import _relabeled
            s["relabeled"] = _relabeled(conn, tabs)
            return s
    except (ApiError, sqlite3.Error, OSError):
        return {}


def list_runs(params: dict | None = None, body: dict | None = None) -> dict:
    C.ensure_src_on_path()
    import registry
    try:
        changed = registry.refresh_status()
    except Exception:  # noqa: BLE001 — registry hỏng không được làm sập Home
        changed = []
    data = registry.load()
    out = []
    for r in data.get("runs", []):
        rec = dict(r)
        summ = dict(rec.get("summary") or {})
        if C.to_bool((params or {}).get("light")):
            rec["summary"] = summ
        else:
            summ.update(_summary_from_db(rec.get("db"), rec.get("run_id", "")))
            summ.setdefault("relabeled", False)
            rec["summary"] = summ
        rec["db_exists"] = bool(rec.get("db")) and Path(rec["db"]).exists()
        out.append(rec)
    out.sort(key=lambda x: x.get("started") or "", reverse=True)
    return {"runs": out, "changed": [c.get("run_id") for c in changed], "home": str(registry.home())}


# ----------------------------------------------------------------------------- progress
def get_progress_lines(params: dict, body: dict | None = None) -> dict:
    rid = C.require_run_id(params)
    run = C.find_run(rid)
    since = C.to_int(params.get("since"), 0, lo=0, name="since")
    C.ensure_src_on_path()
    from orchestrator import progress
    path = C.run_work(run) / rid / "progress.jsonl"
    lines = progress.read(path, since_line=since) if path.exists() else []
    return {"lines": lines, "next": since + len(lines), "path": str(path), "exists": path.exists(),
            "status": run.get("status")}


# ----------------------------------------------------------------------------- stop
def run_stop(params: dict, body: dict | None = None) -> dict:
    rid = C.require_run_id(params)
    run = C.find_run(rid)
    force = C.to_bool((body or {}).get("force"), False)
    C.ensure_src_on_path()
    import registry
    import runner
    work = C.run_work(run)
    res = runner.stop(rid, work, force=force)
    cleaned: list[str] = []
    cl = res.get("cleanup")
    if cl:
        parsed = None
        for line in reversed((cl.get("out") or "").splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    parsed = json.loads(line)
                    break
                except ValueError:
                    continue
        if parsed:
            cleaned += [f"container {c}" for c in parsed.get("containers") or []]
            cleaned += [f"network {n}" for n in parsed.get("networks") or []]
            if parsed.get("reset_claims"):
                cleaned.append(f"reset-claims: {parsed['reset_claims']} commit → pending")
            cleaned += [f"lỗi: {e}" for e in parsed.get("errors") or []]
        elif cl.get("available"):
            cleaned.append(f"stop-cleanup rc={cl.get('rc')}")
        else:
            cleaned.append("stop-cleanup chưa có — chưa dọn container")
    if force and not res.get("alive_after"):
        registry.set_status(rid, "stopped", pid=None)
    elif not res.get("alive_before"):
        registry.refresh_status()
    return {"ok": bool(res.get("ok")), "cleaned": cleaned, "force": force, "pid": res.get("pid"),
            "alive_before": res.get("alive_before"), "alive_after": res.get("alive_after"),
            "stop_file": res.get("stop_file"),
            "message": "Đã kill + dọn" if force else "Đã tạo stop-file — run dừng sau commit hiện tại"}


# ----------------------------------------------------------------------------- resume
def _resume_phase(db: Path | None, last: dict | None) -> str:
    """Pha pipeline sẽ thực sự làm việc khi chạy lại (pipeline tự bỏ qua phần đã xong)."""
    if not db or not db.exists():
        return "scan"
    try:
        with C.ro_conn(db) as conn:
            tabs = C.tables(conn)
            if last and last.get("phase") == "scan" and last.get("event") != "done":
                return "scan"
            if "selected_commits" not in tabs or conn.execute("SELECT COUNT(*) FROM selected_commits").fetchone()[0] == 0:
                return "scan" if "scan_done" not in tabs else "select"
            pend = conn.execute("SELECT COUNT(*) FROM selected_commits WHERE COALESCE(status,'pending') "
                                "IN ('pending','building','analyzing')").fetchone()[0]
            if pend:
                return "analyze"
            from .api_results import _relabeled
            return "relabel" if not _relabeled(conn, tabs) else "export"
    except (ApiError, sqlite3.Error):
        return "scan"


def run_resume(params: dict, body: dict | None = None) -> dict:
    rid = C.require_run_id(params)
    run = C.find_run(rid)
    body = body or {}
    C.ensure_src_on_path()
    import registry
    import runner
    from orchestrator import profile as _profile
    work = C.run_work(run)
    att = runner.attach(rid, work)
    if att.get("alive"):
        raise conflict(f"Run {rid} vẫn đang chạy (pid {att.get('pid')})", "Dừng trước rồi mới resume")
    prof_path = run.get("profile")
    if not prof_path or not Path(prof_path).exists():
        raise not_found(f"profile của run {rid}", "Run không có profile.json — không resume được; tạo run mới cùng cấu hình")
    try:
        prof = _profile.load(prof_path)
    except (_profile.ProfileError, OSError, ValueError) as e:
        raise bad_request(f"profile hỏng: {e}") from e
    db = Path(prof["paths"]["db"]) if prof.get("paths", {}).get("db") else None
    if db:
        C.require_db_free(db)
    workers = body.get("workers")
    if workers is not None:
        n = C.to_int(workers, None, lo=1, hi=16, name="workers")
        prof = copy.deepcopy(prof)
        prof.setdefault("workers", {})["expensive"] = n
        rdir = work / rid
        rdir.mkdir(parents=True, exist_ok=True)
        prof_path = str(rdir / "profile.resume.json")
        _profile.save(prof, prof_path)
    phase = _resume_phase(db, att.get("last_progress_line"))
    # claim mồ côi → pending (xoá raw đắt bán phần) trước khi chạy lại
    reset = None
    if db and db.exists():
        try:
            from orchestrator import control
            reset = control.reset_claims(db, run_id=rid)["reset"]
        except Exception as e:  # noqa: BLE001 — không chặn resume
            reset = f"lỗi: {e}"
    try:
        st = runner.start(prof_path, rid, work)
    except _profile.ProfileError as e:
        raise bad_request(f"profile không hợp lệ: {e}") from e
    except OSError as e:
        raise ApiError(500, "ESPAWN", f"Không khởi chạy được: {e}") from e
    registry.upsert({"run_id": rid, "status": "running", "pid": st["pid"], "finished": None, "profile": prof_path,
                     "work": str(work), "summary": {"resumed_at": C.now_iso(), "from_phase": phase}})
    return {"run_id": rid, "pid": st["pid"], "from_phase": phase, "reset_claims": reset, "log": st["log"],
            "workers": prof.get("workers"),
            "note": "pipeline chạy lại từ đầu nhưng bỏ qua commit đã scan_done / selected đã done (idempotent)"}


# ----------------------------------------------------------------------------- start
def run_start(params: dict, body: dict | None = None) -> dict:
    body = body or {}
    prof = body.get("profile")
    if not isinstance(prof, dict):
        raise bad_request("thiếu body.profile (object)")
    smoke = C.to_bool(body.get("smoke"), False)
    C.ensure_src_on_path()
    import registry
    import runner
    from orchestrator import keys
    from orchestrator import profile as _profile
    prof = copy.deepcopy(prof)
    ts = time.strftime("%Y%m%d-%H%M%S")
    slug = keys.repo_slug(prof.get("repo") or "repo")
    home = registry.home()
    if smoke:
        rid = f"r-{ts}-smoke"
        scratch = home / "scratch"
        prof["scope"] = {"mode": "count", "since": None, "until": None, "max": 3, "from_sha": None, "to_sha": None}
        prof.setdefault("paths", {})
        prof["paths"]["db"] = str(scratch / f"{slug}_{ts}.sqlite")
        prof["paths"]["export"] = str(scratch / f"export_{slug}_{ts}")
        prof["paths"]["work"] = prof["paths"].get("work") or str(home / "work")
    else:
        rid = f"r-{ts}-{slug}"[:80]
    errs = _profile.validate(prof)
    if errs:
        raise bad_request("profile không hợp lệ: " + "; ".join(errs))
    work = Path(prof["paths"].get("work") or (home / "work"))
    prof["paths"]["work"] = str(work)
    rdir = work / rid
    rdir.mkdir(parents=True, exist_ok=True)
    prof_path = rdir / "profile.json"
    _profile.save(prof, prof_path)
    db = Path(prof["paths"]["db"])
    C.require_db_free(db)
    db.parent.mkdir(parents=True, exist_ok=True)
    registry.upsert({"run_id": rid, "repo": prof.get("repo"), "branch": prof.get("branch"), "db": str(db),
                     "export": prof["paths"].get("export") or "", "work": str(work), "profile": str(prof_path),
                     "started": C.now_iso(), "finished": None, "status": "running", "pid": None,
                     "summary": {"smoke": smoke, "scope": prof.get("scope")}})
    try:
        st = runner.start(prof_path, rid, work)
    except _profile.ProfileError as e:
        registry.set_status(rid, "failed", summary={"error": str(e)})
        raise bad_request(f"profile không hợp lệ: {e}") from e
    except OSError as e:
        registry.set_status(rid, "failed", summary={"error": str(e)})
        raise ApiError(500, "ESPAWN", f"Không khởi chạy được tiến trình: {e}") from e
    registry.upsert({"run_id": rid, "pid": st["pid"]})
    return {"run_id": rid, "pid": st["pid"], "smoke": smoke, "db": str(db), "work": str(work), "log": st["log"],
            "profile": str(prof_path)}


# ----------------------------------------------------------------------------- diagnostics
def diagnostics(params: dict | None = None, body: dict | None = None) -> dict:
    params = params or {}
    rid = str(params.get("id") or params.get("run_id") or (body or {}).get("run_id") or "").strip() or None
    C.ensure_src_on_path()
    import registry
    home = registry.home()
    out_dir = home / "diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"diag_{rid or 'app'}_{time.strftime('%Y%m%d-%H%M%S')}.zip"
    if rid:
        try:
            res = C.run_cli(["diagnostics", "--run", rid, "--out", str(out)], timeout=120)
            if out.exists():
                return {"path": str(out), "bytes": out.stat().st_size, "source": "cli", "detail": res}
        except ApiError as e:
            if e.status != 501:
                raise
    files: list[str] = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        def add_text(name: str, text: str):
            z.writestr(name, text)
            files.append(name)

        def add_file(p: Path, name: str | None = None, limit: int = 20_000_000):
            try:
                if p.is_file() and p.stat().st_size <= limit:
                    z.write(p, name or p.name)
                    files.append(name or p.name)
            except OSError:
                pass
        add_text("system.json", json.dumps({"os": platform.platform(), "python": sys.version, "ts": C.now_iso(),
                                            "home": str(home), "argv0": sys.argv[:1]}, ensure_ascii=False, indent=2))
        add_file(home / "settings.json")
        add_file(home / "speed.json")
        add_file(home / "runs.json")
        if rid:
            run = registry.get(rid)
            if run:
                add_text("run.json", json.dumps(run, ensure_ascii=False, indent=2))
                rdir = C.run_work(run) / rid
                for n in ("run.log", "progress.jsonl", "meta.json", "profile.json", "profile.resume.json", "features.log", "relabel.log", "pid", "stop"):
                    add_file(rdir / n, f"run/{n}")
                if run.get("profile"):
                    add_file(Path(run["profile"]), "profile.json")
                if run.get("db"):
                    add_text("db_lock.json", json.dumps(C.db_lock_holder(run["db"]) or {}, ensure_ascii=False))
            else:
                add_text("run.json", json.dumps({"error": f"run {rid} không có trong registry"}))
        if shutil.which("docker"):
            try:
                r = subprocess.run(["docker", "info"], capture_output=True, text=True, errors="replace", timeout=15)
                add_text("docker_info.txt", (r.stdout or "") + "\n" + (r.stderr or ""))
            except (OSError, subprocess.SubprocessError) as e:
                add_text("docker_info.txt", f"lỗi: {e}")
        else:
            add_text("docker_info.txt", "docker không có trong PATH")
    return {"path": str(out), "bytes": out.stat().st_size, "source": "gui", "files": files}
