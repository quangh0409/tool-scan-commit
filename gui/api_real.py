"""Backend thật cho GUI — nối A3 (preflight/runner/registry), A2 (estimate), A5 (api_results/review/settings/runs).

Quy ước uỷ quyền cho module A5 (import lười, 501 nếu chưa có — merge A5 không cần sửa file này):
  gui.api_results.<fn>(params, body) · gui.api_review.<fn> · gui.api_settings.<fn> · gui.api_runs.<fn>
  với params = route params + query (dict), body = JSON body (dict, rỗng nếu không có);
  raise gui.errors.ApiError(status, code, message, hint) khi lỗi.

Luồng run/start (A3 §7 + A1 lock): validate profile → (smoke: scope count 3 + DB scratch %SECJIT_HOME%/scratch)
→ kiểm <db>.lock không bị pid sống giữ (409) → ghi <work>/<run_id>/profile.json → runner.start()
→ registry.upsert(status=running). Pipeline (A1) tự tạo lock bằng pid của nó, GUI KHÔNG tự ghi lock.
"""
from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path

from .api_mock import _shell_from_request
from .errors import ApiError, not_implemented
from .server import Binary, Request, SseFile, Text

try:
    from orchestrator import profile as prof  # type: ignore
except Exception:  # pragma: no cover
    prof = None

_SAFE_NAME = re.compile(r"^[A-Za-z0-9._\- ]{1,64}$")
A5_RESULTS, A5_REVIEW, A5_SETTINGS, A5_RUNS = "gui.api_results", "gui.api_review", "gui.api_settings", "gui.api_runs"


def _try_import(mod: str):
    try:
        return importlib.import_module(mod)
    except ModuleNotFoundError as e:
        # thiếu chính module đó (hoặc gói cha) -> None; thiếu dependency bên trong -> lỗi thật, raise
        if e.name and (mod == e.name or mod.startswith(e.name + ".")):
            return None
        raise


def _registry():
    reg = _try_import("registry")
    if reg is None or not hasattr(reg, "load"):
        raise not_implemented("registry", "A3", "registry.load()/upsert()/get()/refresh_status()")
    return reg


def _runner():
    rn = _try_import("runner")
    if rn is None or not hasattr(rn, "start"):
        raise not_implemented("runner", "A3", "runner.start(profile_path, run_id, work_dir)")
    return rn


def app_data_dir() -> Path:
    reg = _try_import("registry")
    if reg is not None and hasattr(reg, "home"):
        return reg.home()
    env = os.environ.get("SECJIT_HOME")
    if env:
        return Path(env)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "secjit"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "secjit"


class RealApi:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or app_data_dir()
        self.profiles_dir = self.data_dir / "profiles"
        self.settings_path = self.data_dir / "settings.json"
        self._fix_jobs: dict[str, dict] = {}
        self._fix_lock = threading.Lock()
        self._clone_jobs: dict[str, dict] = {}
        self._last_preflight: dict | None = None

    # ------------------------------------------------------------------ uỷ quyền A5
    def _delegate(self, module: str, fn: str, req: Request, fallback=None, owner: str = "A5"):
        mod = _try_import(module)
        f = getattr(mod, fn, None) if mod is not None else None
        if f is None:
            if fallback is not None:
                return fallback(req)
            raise not_implemented(f"{req.method} {req.path}", owner, f"{module}.{fn}(params, body) -> dict")
        params = dict(req.params)
        params.update(req.query)
        return f(params, req.body or {})

    # ------------------------------------------------------------------ settings (stdlib)
    def _default_settings(self) -> dict:
        base = Path(os.environ.get("USERPROFILE") or Path.home())
        return {"language": "vi", "out_dir": str(base / "secjit" / "results"),
                "work_dir": str(base / "secjit" / "work"), "sonar_port": int(os.environ.get("ORCH_SONAR_PORT", "9000")),
                "codeql_ram_mb": 5000, "m2_volume": True}

    def _settings(self) -> dict:
        s = self._default_settings()
        if self.settings_path.exists():
            try:
                with open(self.settings_path, encoding="utf-8") as f:
                    s.update(json.load(f))
            except (OSError, json.JSONDecodeError):
                pass
        return s

    def _save_settings(self, s: dict) -> dict:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.settings_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.settings_path)
        return s

    def settings_get(self, req: Request):
        return self._delegate(A5_SETTINGS, "settings_get", req, fallback=lambda r: self._settings())

    def settings_set(self, req: Request):
        def _fb(r: Request):
            s = self._settings()
            s.update(r.body or {})
            return self._save_settings(s)
        return self._delegate(A5_SETTINGS, "settings_set", req, fallback=_fb)

    def settings_pick_dir(self, req: Request):
        try:
            import tkinter
            from tkinter import filedialog
        except Exception:
            raise ApiError(501, "not_implemented", "Không có hộp chọn thư mục", "Nhập đường dẫn tay")
        try:
            root = tkinter.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            initial = (req.body or {}).get("initial") or ""
            path = filedialog.askdirectory(initialdir=initial or None, title=(req.body or {}).get("title") or "Chọn thư mục")
            root.destroy()
        except Exception as e:
            raise ApiError(500, "pick_failed", f"Không mở được hộp chọn: {e}", "Nhập đường dẫn tay")
        return {"path": path.replace("/", os.sep) if path else ""}

    def storage(self, req: Request):
        return self._delegate(A5_SETTINGS, "storage", req)

    def clean(self, req: Request):
        return self._delegate(A5_SETTINGS, "clean", req)

    def open_path(self, req: Request):
        def _fb(r: Request):
            p = (r.body or {}).get("path") or r.query.get("path") or ""
            if not p or not Path(p).exists():
                raise ApiError(404, "not_found", f"Không có đường dẫn {p}", "")
            try:
                if sys.platform == "win32":
                    os.startfile(p)  # noqa: S606 — mở Explorer theo yêu cầu người dùng
                else:
                    import subprocess
                    subprocess.Popen(["xdg-open", p])
            except OSError as e:
                raise ApiError(501, "not_implemented", f"Không mở được: {e}", "")
            return {"ok": True, "path": p}
        return self._delegate(A5_SETTINGS, "open_path", req, fallback=_fb)

    # ------------------------------------------------------------------ A3: preflight
    def preflight(self, req: Request):
        pf = _try_import("preflight")
        if pf is None or not hasattr(pf, "run"):
            raise not_implemented("preflight", "A3", "preflight.run(...) -> dict §8")
        s = self._settings()
        inc = (req.query.get("include_codeql") or "0") in ("1", "true")
        res = pf.run(work_dir=s.get("work_dir"), sonar_port=s.get("sonar_port"), include_codeql=inc)
        self._last_preflight = res
        return res

    def preflight_fix(self, req: Request):
        """Chạy fix trong thread; mỗi POST trả trạng thái hiện tại {ok, detail, progress, done}; client poll khi done=false."""
        pf = _try_import("preflight")
        fix_id = (req.body or {}).get("fix_id")
        if not fix_id:
            raise ApiError(400, "bad_request", "Thiếu fix_id", "")
        if pf is None or not hasattr(pf, "fix"):
            raise not_implemented("preflight/fix", "A3", "preflight.fix(fix_id, ctx, progress_cb)")
        with self._fix_lock:
            job = self._fix_jobs.get(fix_id)
            if job is not None:
                if job["done"]:
                    self._fix_jobs.pop(fix_id, None)
                    return {k: job[k] for k in ("ok", "detail", "progress", "done")}
                return {"ok": False, "done": False, "progress": job["progress"], "detail": job["detail"]}
            job = {"ok": False, "done": False, "progress": 0, "detail": "Đang sửa…", "started": time.time()}
            self._fix_jobs[fix_id] = job

        s = self._settings()
        ctx = {"work_dir": s.get("work_dir"), "sonar_port": s.get("sonar_port"),
               "docker_mem_gb": (self._last_preflight or {}).get("docker_mem_gb")}

        def cb(info: dict):
            pct = info.get("percent")
            if pct is None and info.get("total"):
                pct = 100.0 * float(info.get("step") or 0) / float(info["total"])
            if pct is not None:
                job["progress"] = max(job["progress"], min(99, int(pct))) if not job["done"] else 100
            if info.get("msg"):
                job["detail"] = str(info["msg"])

        def worker():
            try:
                r = pf.fix(fix_id, ctx, cb)
            except Exception as e:  # noqa: BLE001
                r = {"ok": False, "detail": f"{type(e).__name__}: {e}"}
            job["ok"] = bool(r.get("ok"))
            job["detail"] = r.get("detail") or ("Đã sửa" if job["ok"] else "Sửa thất bại")
            job["progress"] = 100 if job["ok"] else job["progress"]
            if job["ok"] and fix_id == "pick_port" and r.get("port"):
                try:
                    st = self._settings()
                    st["sonar_port"] = int(r["port"])
                    self._save_settings(st)
                except OSError:
                    pass
            job["done"] = True

        threading.Thread(target=worker, name=f"fix-{fix_id}", daemon=True).start()
        time.sleep(0.4)       # fix nhanh (longpaths/pick_port) xong ngay trong 1 lượt
        with self._fix_lock:
            if job["done"]:
                self._fix_jobs.pop(fix_id, None)
                return {k: job[k] for k in ("ok", "detail", "progress", "done")}
            return {"ok": False, "done": False, "progress": job["progress"], "detail": job["detail"]}

    # ------------------------------------------------------------------ repo / estimate
    def repo_check(self, req: Request):
        from . import repo_probe
        body = req.body or {}
        url = body.get("url") or ""
        if not url:
            raise ApiError(400, "bad_request", "Thiếu url", "")
        s = self._settings()
        return repo_probe.check(url, pat=body.get("pat") or None, work_dir=s.get("work_dir"))

    def _work_dir_for(self, p: dict) -> str:
        return (p.get("paths") or {}).get("work") or self._settings().get("work_dir") or ""

    def _apply_work_dir(self, work: str) -> None:
        """orchestrator.config đọc env lúc import -> đặt ORCH_WORK_DIR rồi reload để enumerate dùng đúng clone."""
        if work:
            os.environ["ORCH_WORK_DIR"] = str(work)
        cfg = _try_import("orchestrator.config")
        if cfg is not None and hasattr(cfg, "reload"):
            cfg.reload()

    def _clone_bg(self, url: str, work: str) -> dict:
        """Clone nền một lần cho mỗi repo; trả trạng thái job."""
        key = f"{work}|{url}"
        job = self._clone_jobs.get(key)
        if job and (not job["done"] or job["ok"]):
            return job
        job = {"done": False, "ok": False, "error": "", "started": time.time()}
        self._clone_jobs[key] = job

        def worker():
            try:
                self._apply_work_dir(work)
                enm = importlib.import_module("orchestrator.enumerate_commits")
                enm.clone_or_update(url)
                job["ok"] = True
            except Exception as e:  # noqa: BLE001
                job["error"] = f"{type(e).__name__}: {e}"
            job["done"] = True

        threading.Thread(target=worker, name="clone-bg", daemon=True).start()
        return job

    def estimate(self, req: Request):
        from . import repo_probe
        est = _try_import("orchestrator.estimate")
        if est is None:
            raise not_implemented("estimate", "A2", "orchestrator.estimate.estimate(profile)")
        p = (req.body or {}).get("profile") or {}
        if not p.get("repo"):
            raise ApiError(400, "bad_request", "profile.repo trống", "")
        work = self._work_dir_for(p)
        clone = repo_probe.find_clone(p["repo"], work)
        if clone is None:
            job = self._clone_bg(p["repo"], work)
            if job["done"] and not job["ok"]:
                raise ApiError(502, "clone_failed", f"Clone nền thất bại: {job['error']}", "Kiểm tra mạng/PAT rồi thử lại")
            raise ApiError(425, "clone_pending", "Đang clone nền repo để đếm commit…",
                           "Ước tính sẽ tự cập nhật khi clone xong (repo lớn có thể vài phút)")
        self._apply_work_dir(work)
        try:
            res = est.estimate(p)
        except Exception as e:  # noqa: BLE001
            raise ApiError(500, "estimate_failed", f"{type(e).__name__}: {e}", "Kiểm tra nhánh/SHA trong phạm vi")
        sc = p.get("scope") or {}
        try:
            res["histogram"] = repo_probe.histogram(clone, p.get("branch") or None,
                                                    sc.get("since") if sc.get("mode") == "time" else None,
                                                    sc.get("until") if sc.get("mode") == "time" else None)
        except Exception:  # noqa: BLE001
            res["histogram"] = []
        sp = (res.get("detail") or {}).get("speed") or {}
        if sp:
            res["speed"] = {"cheap_s_per_commit": sp.get("cheap_s_per_commit"), "findsecbugs": sp.get("fsb_s"),
                            "sonar": sp.get("sonar_s"), "codeql": sp.get("codeql_s"),
                            "build_cold_s": sp.get("build_cold_s"), "build_warm_s": sp.get("build_warm_s")}
        db = (p.get("paths") or {}).get("db")
        res["db_exists"] = bool(db) and Path(db).exists()
        return res

    def profile_validate(self, req: Request):
        if prof is None:
            raise ApiError(501, "not_implemented", "Thiếu orchestrator.profile", "")
        p = (req.body or {}).get("profile") or {}
        errs = prof.validate(p)
        db = (p.get("paths") or {}).get("db") or ""
        exp = (p.get("paths") or {}).get("export") or ""
        db_exists = bool(db) and Path(db).exists()
        uv = None
        locked = None
        if db_exists:
            try:
                import sqlite3
                con = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)
                uv = con.execute("PRAGMA user_version").fetchone()[0]
                con.close()
            except Exception:
                uv = None
            reg = _try_import("registry")
            if reg is not None:
                try:
                    held, info = reg.locks.lock_status(db)
                    locked = {"held": held, "run_id": (info or {}).get("run_id"), "pid": (info or {}).get("pid")} if info else None
                except Exception:  # noqa: BLE001
                    locked = None
        warnings = []
        if locked and locked.get("held"):
            warnings.append(f"DB đang bị run {locked.get('run_id')} (pid {locked.get('pid')}) sử dụng")
        return {"errors": errs, "warnings": warnings, "db_exists": db_exists,
                "export_exists": bool(exp) and Path(exp).exists(), "db_user_version": uv, "db_locked": locked}

    # ------------------------------------------------------------------ A3: run start/stop/resume/runs
    @staticmethod
    def _run_id(prefix: str, p: dict) -> str:
        from . import repo_probe
        s = repo_probe.slug(p.get("repo") or "repo").split("__")[-1][:16]
        return f"{prefix}{time.strftime('%Y%m%d-%H%M%S')}-{s}"

    def _smoke_profile(self, p: dict) -> dict:
        import copy
        from . import repo_probe
        q = copy.deepcopy(p)
        q["scope"] = {"mode": "count", "since": None, "until": None, "max": 3, "from_sha": None, "to_sha": None}
        scratch = self.data_dir / "scratch"
        stamp = time.strftime("%Y%m%d-%H%M%S")
        slug = repo_probe.slug(p.get("repo") or "repo")
        q["paths"] = {"db": str(scratch / f"dataset_{slug}_smoke_{stamp}.sqlite"),
                      "export": str(scratch / f"export_{slug}_smoke_{stamp}"),
                      "work": (p.get("paths") or {}).get("work") or self._settings().get("work_dir") or str(scratch / "work")}
        return q

    def run_start(self, req: Request):
        if prof is None:
            raise ApiError(501, "not_implemented", "Thiếu orchestrator.profile", "")
        reg = _registry()
        rn = _runner()
        body = req.body or {}
        p = body.get("profile") or {}
        smoke = bool(body.get("smoke"))
        if smoke:
            p = self._smoke_profile(p)
        errs = prof.validate(p)
        if errs:
            raise ApiError(400, "invalid_profile", "; ".join(errs), "Sửa các mục báo lỗi ở Wizard")
        db = p["paths"]["db"]
        work = p["paths"].get("work") or self._settings().get("work_dir")
        if not work:
            raise ApiError(400, "invalid_profile", "paths.work trống", "Chọn thư mục làm việc ở bước 4")
        p["paths"]["work"] = work
        # DB đang bị run sống khác giữ -> 409 (pipeline A1 cũng sẽ từ chối; chặn sớm để báo rõ)
        try:
            held, info = reg.locks.lock_status(db)
        except Exception:  # noqa: BLE001
            held, info = False, None
        if held:
            raise ApiError(409, "db_locked", f"DB đang bị run {info.get('run_id')} (pid {info.get('pid')}) sử dụng",
                           "Dừng run đó ở Bảng điều khiển hoặc đổi tên DB ở bước 4")
        if body.get("overwrite") and Path(db).exists():
            bak = Path(str(db) + f".{time.strftime('%Y%m%d-%H%M%S')}.bak")
            try:
                shutil.move(db, bak)
                for suf in ("-wal", "-shm"):
                    if Path(str(db) + suf).exists():
                        Path(str(db) + suf).unlink()
            except OSError as e:
                raise ApiError(500, "overwrite_failed", f"Không đổi tên DB cũ thành .bak: {e}", "")
        run_id = self._run_id("smoke-" if smoke else "r-", p)
        rdir = rn.run_dir(work, run_id)
        rdir.mkdir(parents=True, exist_ok=True)
        profile_path = rdir / "profile.json"
        try:
            prof.save(p, profile_path)
        except prof.ProfileError as e:
            raise ApiError(400, "invalid_profile", str(e), "")
        extra_env = {"ORCH_SONAR_PORT": str(p.get("sonar_port") or self._settings().get("sonar_port") or 9000)}
        try:
            res = rn.start(profile_path, run_id, work, extra_env=extra_env)
        except OSError as e:
            raise ApiError(500, "spawn_failed", f"Không khởi chạy được tiến trình: {e}", "Kiểm tra python/đường dẫn work")
        rec = {"run_id": run_id, "repo": p.get("repo"), "branch": p.get("branch"), "db": db,
               "export": p["paths"].get("export") or "", "work": work, "profile": str(profile_path),
               "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "finished": None, "status": "running",
               "pid": res["pid"], "smoke": smoke,
               "summary": {"formats": body.get("formats") or ["jsonl"], "notify": bool(body.get("notify", True)),
                           "resume": bool(body.get("resume")), "scope": p.get("scope")}}
        reg.upsert(rec)
        return {"run_id": run_id, "pid": res["pid"], "smoke": smoke, "log": res.get("log"), "run_dir": res.get("run_dir")}

    def run_stop(self, req: Request):
        reg = _registry()
        rn = _runner()
        rid = req.params["id"]
        rec = reg.get(rid)
        if not rec:
            raise ApiError(404, "not_found", f"Không có run {rid}", "")
        force = bool((req.body or {}).get("force"))
        res = rn.stop(rid, rec.get("work") or self._settings().get("work_dir"), force=force)
        cleaned: list[str] = []
        cu = res.get("cleanup") or {}
        if isinstance(cu, dict) and cu.get("out"):
            cleaned = [ln for ln in str(cu["out"]).splitlines() if ln.strip()][-20:]
        if force or not res.get("alive_after", True):
            try:
                reg.set_status(rid, "stopped", pid=None)
            except Exception:  # noqa: BLE001
                pass
        return {"ok": bool(res.get("ok", True)), "cleaned": cleaned, "detail": res}

    def run_resume(self, req: Request):
        return self._delegate(A5_RUNS, "run_resume", req, owner="A5")

    def runs(self, req: Request):
        reg = _registry()
        try:
            reg.refresh_status()
        except Exception:  # noqa: BLE001 — registry hỏng không được làm Home chết
            pass
        return self._delegate(A5_RUNS, "runs", req, fallback=lambda r: reg.load())

    def _run_record(self, rid: str) -> dict:
        rec = _registry().get(rid)
        if not rec:
            raise ApiError(404, "not_found", f"Không có run {rid} trong registry", "Run cũ chạy bằng CLI không có trong runs.json")
        return rec

    def run_progress(self, req: Request):
        rid = req.params["id"]
        rec = self._run_record(rid)
        work = rec.get("work") or self._settings().get("work_dir") or ""
        path = Path(work) / rid / "progress.jsonl"
        return SseFile(path, follow=rec.get("status") == "running", max_follow_sec=0)

    def run_profile(self, req: Request):
        rec = self._run_record(req.params["id"])
        pp = rec.get("profile")
        if not pp or not Path(pp).exists():
            raise ApiError(404, "not_found", f"Run {req.params['id']} không có profile.json", "Run cũ trước v2 không lưu profile")
        with open(pp, encoding="utf-8") as f:
            return {"profile": json.load(f)}

    # ------------------------------------------------------------------ A5: results / review
    def results_overview(self, req: Request):
        return self._delegate(A5_RESULTS, "results_overview", req)

    def results_findings(self, req: Request):
        return self._delegate(A5_RESULTS, "results_findings", req)

    def results_finding(self, req: Request):
        return self._delegate(A5_RESULTS, "results_finding", req)

    def results_commits(self, req: Request):
        return self._delegate(A5_RESULTS, "results_commits", req)

    def results_export(self, req: Request):
        return self._delegate(A5_RESULTS, "results_export", req)

    def results_raw(self, req: Request):
        r = self._delegate(A5_RESULTS, "results_raw", req)
        if isinstance(r, dict) and "text" in r:
            return Text(str(r["text"]), r.get("content_type") or "text/plain; charset=utf-8")
        if isinstance(r, str):
            return Text(r)
        return r

    def results_features(self, req: Request):
        return self._delegate(A5_RESULTS, "results_features", req)

    def results_relabel(self, req: Request):
        return self._delegate(A5_RESULTS, "results_relabel", req)

    def review_sample(self, req: Request):
        return self._delegate(A5_REVIEW, "review_sample", req)

    def review_next(self, req: Request):
        return self._delegate(A5_REVIEW, "review_next", req)

    def review_verdict(self, req: Request):
        return self._delegate(A5_REVIEW, "review_verdict", req)

    def review_close(self, req: Request):
        return self._delegate(A5_REVIEW, "review_close", req)

    # ------------------------------------------------------------------ profiles / shell / diagnostics
    def profiles_list(self, req: Request):
        out = []
        if self.profiles_dir.exists():
            for fp in sorted(self.profiles_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
                try:
                    with open(fp, encoding="utf-8") as f:
                        p = json.load(f)
                    out.append({"name": fp.stem, "repo": p.get("repo"), "branch": p.get("branch"),
                                "saved": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(fp.stat().st_mtime)),
                                "path": str(fp)})
                except (OSError, json.JSONDecodeError):
                    continue
        return {"profiles": out}

    def _profile_path(self, name: str) -> Path:
        if not _SAFE_NAME.match(name or ""):
            raise ApiError(400, "bad_name", "Tên profile chỉ gồm chữ, số, . _ - và khoảng trắng (≤64)", "")
        return self.profiles_dir / f"{name}.json"

    def profiles_save(self, req: Request):
        if prof is None:
            raise ApiError(501, "not_implemented", "Thiếu orchestrator.profile", "")
        body = req.body or {}
        name = (body.get("name") or "").strip()
        p = body.get("profile") or {}
        path = self._profile_path(name)
        try:
            prof.save(p, path)
        except prof.ProfileError as e:
            raise ApiError(400, "invalid_profile", str(e), "Sửa các mục báo lỗi ở Wizard")
        return {"ok": True, "name": name, "path": str(path)}

    def profiles_get(self, req: Request):
        path = self._profile_path(req.params["name"])
        if not path.exists():
            raise ApiError(404, "not_found", f"Không có profile {req.params['name']}", "")
        with open(path, encoding="utf-8") as f:
            return {"name": req.params["name"], "profile": json.load(f)}

    def profiles_delete(self, req: Request):
        path = self._profile_path(req.params["name"])
        if path.exists():
            path.unlink()
        return {"ok": True}

    def shell(self, req: Request):
        return _shell_from_request(req)

    def diagnostics(self, req: Request):
        """Zip: settings.json, runs.json, speed.json, preflight gần nhất, run.log + meta + profile của ≤5 run mới nhất."""
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("settings.json", json.dumps(self._settings(), ensure_ascii=False, indent=2))
            for name in ("runs.json", "speed.json"):
                fp = self.data_dir / name
                if fp.exists():
                    z.write(fp, name)
            if self._last_preflight is not None:
                z.writestr("preflight.json", json.dumps(self._last_preflight, ensure_ascii=False, indent=2, default=str))
            reg = _try_import("registry")
            runs = (reg.load().get("runs") if reg is not None else []) or []
            for rec in sorted(runs, key=lambda r: r.get("started") or "", reverse=True)[:5]:
                rid = rec.get("run_id") or "run"
                rdir = Path(rec.get("work") or "") / rid
                for fn in ("run.log", "meta.json", "profile.json", "progress.jsonl"):
                    fp = rdir / fn
                    if fp.exists():
                        try:
                            data = fp.read_bytes()
                            if fn == "run.log" and len(data) > 2_000_000:
                                data = data[-2_000_000:]
                            z.writestr(f"runs/{rid}/{fn}", data)
                        except OSError:
                            continue
            z.writestr("README.txt", f"SecJIT diagnostics {time.strftime('%Y-%m-%dT%H:%M:%S')} · python {sys.version}\n")
        return Binary(buf.getvalue(), "application/zip", f"secjit-diagnostics-{time.strftime('%Y%m%d-%H%M%S')}.zip")
