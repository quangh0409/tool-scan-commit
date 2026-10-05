"""Backend thật — KHUNG. Phần nối A3 (runner/registry/preflight) và A5 (results/review) trả 501.

Đã làm được bằng stdlib ngay tại đây (không phụ thuộc A3/A5):
  * settings (file %LOCALAPPDATA%/secjit/settings.json)
  * profiles (thư mục %LOCALAPPDATA%/secjit/profiles/<name>.json)
  * shell (profile.to_shell), profile_validate (profile.validate + kiểm DB tồn tại)
  * settings_pick_dir (tkinter.filedialog nếu có GUI; không có -> 501 để client dùng ô nhập tay)
  * run_progress (tail <work>/<run_id>/progress.jsonl nếu registry A3 có; nếu không -> 501)

Các hàm A3/A5 cần nối được đánh dấu ``# A3:`` / ``# A5:`` kèm chữ ký kỳ vọng.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

from .api_mock import _shell_from_request
from .server import ApiError, Request, SseFile

try:
    from orchestrator import profile as prof  # type: ignore
except Exception:  # pragma: no cover
    prof = None


def app_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "secjit"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "secjit"


def _not_impl(what: str, owner: str, sig: str) -> ApiError:
    return ApiError(501, "not_implemented", f"Chưa nối backend thật cho {what}",
                    f"{owner} cung cấp {sig}")


def _try_import(mod: str):
    try:
        return __import__(mod)
    except Exception:
        return None


_SAFE_NAME = re.compile(r"^[A-Za-z0-9._\- ]{1,64}$")


class RealApi:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or app_data_dir()
        self.profiles_dir = self.data_dir / "profiles"
        self.settings_path = self.data_dir / "settings.json"

    # ---------- A3: preflight ----------
    def preflight(self, req: Request):
        pf = _try_import("preflight")
        if pf is None or not hasattr(pf, "run"):
            raise _not_impl("preflight", "A3", "preflight.run(fix=False) -> dict §8")
        return pf.run(fix=False)

    def preflight_fix(self, req: Request):
        pf = _try_import("preflight")
        fix_id = (req.body or {}).get("fix_id")
        if not fix_id:
            raise ApiError(400, "bad_request", "Thiếu fix_id", "")
        if pf is None or not hasattr(pf, "fix"):
            raise _not_impl("preflight/fix", "A3", "preflight.fix(fix_id) -> {ok, detail, progress?, done?}")
        return pf.fix(fix_id)

    # ---------- A3/A2: repo check & estimate ----------
    def repo_check(self, req: Request):
        # A3: repo_probe.check(url, pat=None, timeout=60) -> dict §9 (git ls-remote + pom HEAD, GIT_TERMINAL_PROMPT=0)
        raise _not_impl("repo/check", "A3", "repo_probe.check(url, pat=None) -> dict §9 repo_check")

    def estimate(self, req: Request):
        # A2: `orchestrator.cli estimate --profile F --json` hoặc estimate.estimate(profile, speed) -> dict §9
        raise _not_impl("estimate", "A2", "estimate.estimate(profile: dict, speed: dict|None) -> dict §9")

    def profile_validate(self, req: Request):
        if prof is None:
            raise ApiError(501, "not_implemented", "Thiếu orchestrator.profile", "")
        p = (req.body or {}).get("profile") or {}
        errs = prof.validate(p)
        db = (p.get("paths") or {}).get("db") or ""
        exp = (p.get("paths") or {}).get("export") or ""
        db_exists = bool(db) and Path(db).exists()
        uv = None
        if db_exists:
            try:
                import sqlite3
                con = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)
                uv = con.execute("PRAGMA user_version").fetchone()[0]
                con.close()
            except Exception:
                uv = None
        return {"errors": errs, "warnings": [], "db_exists": db_exists,
                "export_exists": bool(exp) and Path(exp).exists(), "db_user_version": uv}

    # ---------- A3: runner / registry ----------
    def run_start(self, req: Request):
        # A3: runner.start(profile_path, run_id) -> pid ; registry.add(record)
        raise _not_impl("run/start", "A3", "runner.start(profile_path, run_id) -> pid; registry.add(rec)")

    def run_stop(self, req: Request):
        # A3: runner.stop(run_id, force=False) -> {ok, cleaned[]}
        raise _not_impl("run/stop", "A3", "runner.stop(run_id, force) -> {ok, cleaned}")

    def run_resume(self, req: Request):
        # A3: runner.resume(run_id) -> {run_id, pid, from_phase}
        raise _not_impl("run/resume", "A3", "runner.resume(run_id) -> {run_id, pid, from_phase}")

    def runs(self, req: Request):
        reg = _try_import("registry")
        if reg is None or not hasattr(reg, "load"):
            raise _not_impl("runs", "A3", "registry.load() -> {runs:[...]} (§7, kèm summary)")
        return reg.load()

    def run_progress(self, req: Request):
        reg = _try_import("registry")
        rid = req.params["id"]
        if reg is None or not hasattr(reg, "get"):
            raise _not_impl("run/progress", "A3", "registry.get(run_id) -> rec có 'work'; file <work>/<run_id>/progress.jsonl")
        rec = reg.get(rid)
        if not rec:
            raise ApiError(404, "not_found", f"Không có run {rid}", "")
        path = Path(rec["work"]) / rid / "progress.jsonl"
        return SseFile(path, follow=rec.get("status") == "running")

    def run_profile(self, req: Request):
        reg = _try_import("registry")
        rid = req.params["id"]
        if reg is None or not hasattr(reg, "get"):
            raise _not_impl("run/profile", "A3", "registry.get(run_id)['profile'] -> đường dẫn profile.json")
        rec = reg.get(rid)
        if not rec or not rec.get("profile") or not Path(rec["profile"]).exists():
            raise ApiError(404, "not_found", f"Run {rid} không có profile.json", "Run cũ trước v2 không lưu profile")
        with open(rec["profile"], encoding="utf-8") as f:
            return {"profile": json.load(f)}

    # ---------- A5: results / review ----------
    def results_overview(self, req: Request):
        raise _not_impl("results/overview", "A5", "stats.overview(db, run_id) -> dict §9")

    def results_findings(self, req: Request):
        raise _not_impl("results/findings", "A5", "results.findings(db, filters, page, size)")

    def results_finding(self, req: Request):
        raise _not_impl("results/finding", "A5", "results.finding(db, cluster_key)")

    def results_commits(self, req: Request):
        raise _not_impl("results/commits", "A5", "results.commits(db, page, size)")

    def results_export(self, req: Request):
        raise _not_impl("results/export", "A5/A1", "export_dataset.export_all(db, out, formats)")

    def review_sample(self, req: Request):
        raise _not_impl("review/sample", "A5", "review.sample(db, seed, n_pos, n_neg)")

    def review_next(self, req: Request):
        raise _not_impl("review/next", "A5", "review.next(db, sample_id, rater)")

    def review_verdict(self, req: Request):
        raise _not_impl("review/verdict", "A5", "review.verdict(db, …)")

    def review_close(self, req: Request):
        raise _not_impl("review/close", "A5", "review.close(db, sample_id)")

    # ---------- settings / profiles / shell (stdlib, làm ngay) ----------
    def _default_settings(self) -> dict:
        base = Path(os.environ.get("USERPROFILE") or Path.home())
        return {"language": "vi", "out_dir": str(base / "secjit" / "results"),
                "work_dir": str(base / "secjit" / "work"), "sonar_port": int(os.environ.get("ORCH_SONAR_PORT", "9000")),
                "codeql_ram_mb": 5000, "m2_volume": True}

    def settings_get(self, req: Request):
        s = self._default_settings()
        if self.settings_path.exists():
            try:
                with open(self.settings_path, encoding="utf-8") as f:
                    s.update(json.load(f))
            except (OSError, json.JSONDecodeError):
                pass
        return s

    def settings_set(self, req: Request):
        s = self.settings_get(req)
        s.update(req.body or {})
        self.data_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.settings_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.settings_path)
        return s

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
        raise _not_impl("storage", "A3/A5", "storage.scan(settings) -> {items, total_bytes, free_bytes}")

    def clean(self, req: Request):
        raise _not_impl("clean", "A2/A5", "`orchestrator.cli clean --items … --dry-run --json`")

    def profiles_list(self, req: Request):
        out = []
        if self.profiles_dir.exists():
            for fp in sorted(self.profiles_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
                try:
                    with open(fp, encoding="utf-8") as f:
                        p = json.load(f)
                    out.append({"name": fp.stem, "repo": p.get("repo"),
                                "saved": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(fp.stat().st_mtime))})
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
        # A3: diagnostics.bundle() -> bytes zip (log, run_meta, docker info, profile, preflight.json)
        raise _not_impl("diagnostics", "A3", "diagnostics.bundle() -> bytes (zip)")
