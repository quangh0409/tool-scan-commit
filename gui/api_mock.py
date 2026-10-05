"""Backend giả lập: trả fixture `gui/fixtures/*.json`, tôn trọng `?state=empty|error|loading|partial`.

Dùng cho QA chụp ảnh (tests/gui/shoot.py) và test server. Không Docker, không pipeline.
Trạng thái:
  * (mặc định)  -> fixture đầy đủ
  * state=empty   -> danh sách rỗng / chưa có dữ liệu
  * state=error   -> HTTP 500 {"error":{...}} cho mọi endpoint
  * state=loading -> ngủ MOCK_LOADING_SEC rồi mới trả (để chụp skeleton)
  * state=partial -> thiếu trường (summary null, không histogram, repo không Java…)
  * state=fixed   -> preflight trả `preflight_fixed.json` (ready=true)
  * state=docker_down -> preflight: docker_daemon=bad, ready=false
"""
from __future__ import annotations

import copy
import json
import threading
import time
from pathlib import Path

from . import FIXTURES_DIR
from .errors import ApiError
from .server import Binary, Request, SseFile, Text

MOCK_LOADING_SEC = 20.0

try:
    from orchestrator import profile as prof  # type: ignore
    from orchestrator import keys  # type: ignore
except Exception:  # pragma: no cover - chỉ khi chạy ngoài repo
    prof = None
    keys = None


_FIX_DETAIL = {"start_docker": "Docker Desktop đã chạy", "pick_port": "Dùng port 9100",
               "git_longpaths": "core.longpaths=true", "pull_images": "Đã tải/build đủ image"}


def _fx(name: str):
    with open(FIXTURES_DIR / name, encoding="utf-8") as f:
        return json.load(f)


class MockApi:
    def __init__(self, loading_sec: float = MOCK_LOADING_SEC):
        self.loading_sec = loading_sec
        self._lock = threading.Lock()
        self._fixed: set[str] = set()
        self._fix_progress: dict[str, int] = {}
        self._profiles: list[dict] = _fx("profiles.json")["profiles"]
        self._profiles_full: dict[str, dict] = {}
        self._settings: dict = _fx("settings.json")
        self._runs: list[dict] = _fx("runs.json")["runs"]
        self._started: list[dict] = []

    # ---- tiện ích trạng thái ----
    def _gate(self, req: Request) -> str:
        st = req.state
        if st == "error":
            raise ApiError(500, "mock_error", "Lỗi giả lập từ mock backend",
                           "Đây là trạng thái ?state=error dùng để QA giao diện")
        if st == "loading":
            time.sleep(self.loading_sec)
        return st

    # ---- preflight ----
    def preflight(self, req: Request):
        st = self._gate(req)
        if st == "fixed":
            return _fx("preflight_fixed.json")
        data = _fx("preflight.json")
        if st == "docker_down":
            for it in data["items"]:
                if it["id"] == "docker_daemon":
                    it["level"] = "bad"
                    it["detail"] = "Docker Desktop không phản hồi sau 90 giây."
                    it["fix_available"] = False
            data["ready"] = False
            return data
        if st == "partial":
            data.pop("docker_mem_gb", None)
            data.pop("cpu", None)
            data["items"] = data["items"][:6]
            return data
        if st == "empty":
            data["items"] = []
            data["ready"] = False
            return data
        with self._lock:
            for it in data["items"]:
                if it.get("fix_id") in self._fixed:
                    it["level"] = "ok"
                    it["fix_available"] = False
                    it["detail"] = _FIX_DETAIL.get(it["fix_id"], "Đã sửa") + " (đã sửa tự động)"   # PF-3
            data["ready"] = all(it["level"] in ("ok", "warn") for it in data["items"])
        if (req.query.get("light") or "0") in ("1", "true"):          # HM-2: chỉ docker_daemon
            data["items"] = [it for it in data["items"] if it["id"] == "docker_daemon"]
            data["light"] = True
        return data

    def preflight_fix(self, req: Request):
        self._gate(req)
        fix_id = (req.body or {}).get("fix_id")
        if not fix_id:
            raise ApiError(400, "bad_request", "Thiếu fix_id", "")
        with self._lock:
            if fix_id == "pull_images":
                p = self._fix_progress.get(fix_id, 0) + 34
                if p < 100:
                    self._fix_progress[fix_id] = p
                    return {"ok": False, "done": False, "progress": p,
                            "detail": f"Đang tải semgrep… {p} %"}
                self._fix_progress.pop(fix_id, None)
            time.sleep(0.2)
            self._fixed.add(fix_id)
        return {"ok": True, "done": True, "progress": 100, "detail": _FIX_DETAIL.get(fix_id, "Đã sửa")}

    # ---- wizard ----
    def repo_check(self, req: Request):
        st = self._gate(req)
        url = (req.body or {}).get("url") or ""
        data = _fx("repo_check.json")
        if keys is not None and url:
            data["canon"] = keys.canon_repo(url)
            data["slug"] = keys.repo_slug(url)
        if "notfound" in url:
            raise ApiError(404, "repo_not_found", "Repo không tồn tại hoặc private",
                           "Kiểm tra lại link; repo private cần PAT")
        if "private" in url and not (req.body or {}).get("pat"):
            raise ApiError(401, "auth_required", "Repo yêu cầu xác thực", "Bật 'Repo private' và nhập PAT")
        if st == "partial":
            data.update({"java_maven": False, "jdk": None, "modules": 0, "security_config_count": 0,
                         "snapshot_risk": True, "branches": ["trunk"], "default_branch": "trunk",
                         "warnings": ["Không tìm thấy pom.xml ở HEAD — tầng đắt sẽ không build được"]})
        if st == "empty":
            data.update({"branches": [], "tags": [], "default_branch": None,
                         "warnings": ["Repo rỗng (không có nhánh)"]})
        return data

    def estimate(self, req: Request):
        st = self._gate(req)
        data = _fx("estimate.json")
        p = (req.body or {}).get("profile") or {}
        sc = p.get("scope") or {}
        if sc.get("mode") == "all":
            data.update({"commits_after_filter": 187, "buggy_est": 61, "cheap_minutes": 130,
                         "expensive_minutes_cold": 900, "expensive_minutes_warm": 380, "disk_gb": 1.8})
        elif sc.get("mode") == "count":
            try:
                n = max(1, int(sc.get("max") or 50))
            except (TypeError, ValueError):
                n = 50
            k = n / 50.0
            data.update({"commits_after_filter": round(27 * k), "buggy_est": round(9 * k),
                         "cheap_minutes": round(8 * k), "expensive_minutes_cold": round(210 * k),
                         "expensive_minutes_warm": round(95 * k), "disk_gb": round(1.4 * k, 1)})
        if st == "partial":
            data["speed_source"] = "default"
            data.pop("expensive_minutes_warm", None)
            return data
        if st == "empty":
            return {"commits_after_filter": 0, "buggy_est": 0, "cheap_minutes": 0,
                    "expensive_minutes_cold": 0, "expensive_minutes_warm": 0, "disk_gb": 0.1,
                    "speed_source": "default"}
        data["speed_source"] = "measured"
        data["speed"] = {"cheap_s_per_commit": 12, "gitleaks": 2, "trufflehog": 3, "semgrep": 15,
                         "bearer": 10, "horusec": 20, "findsecbugs": 7, "sonar": 30, "codeql": 900,
                         "build_cold_s": 420, "build_warm_s": 150}
        data["histogram"] = [{"month": f"2019-{m:02d}", "n": n} for m, n in
                             enumerate([3, 5, 9, 14, 22, 18, 11, 7, 4, 6, 9, 12], start=1)]
        data["db_exists"] = False
        return data

    def profile_validate(self, req: Request):
        st = self._gate(req)
        p = (req.body or {}).get("profile") or {}
        errs = prof.validate(p) if prof is not None else []
        db = (p.get("paths") or {}).get("db") or ""
        # W4-2: không dò substring — "đã tồn tại" khi file thật có, hoặc trùng tên DB của một run trong fixture runs.json
        # (QA: đặt tên DB = dataset_FudanSELab__train-ticket_master_20261005.sqlite để kích hoạt Resume/Đổi tên/Ghi đè)
        known = {Path(r.get("db") or "").name.lower() for r in self._runs + self._started if r.get("db")}
        exists = st == "partial" or (bool(db) and (Path(db).exists() or Path(db).name.lower() in known))
        return {"errors": errs, "warnings": [], "db_exists": exists, "export_exists": exists,
                "db_user_version": 2 if exists else None}

    # ---- run ----
    def run_start(self, req: Request):
        self._gate(req)
        body = req.body or {}
        p = body.get("profile") or {}
        if prof is not None:
            errs = prof.validate(p)
            if errs:
                raise ApiError(400, "invalid_profile", "; ".join(errs), "Sửa các mục báo lỗi ở Wizard")
        run_id = ("smoke-" if body.get("smoke") else "r-") + time.strftime("%Y%m%d-%H%M%S")
        rec = {"run_id": run_id, "repo": p.get("repo"), "branch": p.get("branch"),
               "db": (p.get("paths") or {}).get("db"), "export": (p.get("paths") or {}).get("export"),
               "work": (p.get("paths") or {}).get("work"), "profile": "", "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "finished": None, "status": "running", "pid": 4242, "smoke": bool(body.get("smoke")),
               "summary": {"commits": 3 if body.get("smoke") else None}}
        with self._lock:
            self._started.insert(0, rec)
        return {"run_id": run_id, "pid": 4242, "smoke": bool(body.get("smoke"))}

    def run_stop(self, req: Request):
        self._gate(req)
        force = bool((req.body or {}).get("force"))
        return {"ok": True, "cleaned": ["orch-sonar", "orch-sonar-net"] if force else []}

    def run_resume(self, req: Request):
        self._gate(req)
        return {"run_id": req.params["id"], "pid": 4343, "from_phase": "analyze"}

    def run_progress(self, req: Request):
        st = self._gate(req)
        return SseFile(FIXTURES_DIR / "progress.jsonl", follow=(st == "follow"), max_follow_sec=5)

    def run_profile(self, req: Request):
        self._gate(req)
        rid = req.params["id"]
        run = next((r for r in self._runs + self._started if r["run_id"] == rid), None)
        if run is None:
            raise ApiError(404, "not_found", f"Không có run {rid}", "")
        if prof is None:
            raise ApiError(501, "not_implemented", "Thiếu orchestrator.profile", "")
        p = prof.from_env_defaults(run["repo"], run["branch"], "D:\\secjit\\results")
        p["paths"]["db"] = run["db"] or p["paths"]["db"]
        p["scope"] = {"mode": "count", "since": None, "until": None, "max": 30, "from_sha": None, "to_sha": None}
        p["sonar_port"] = 9100
        return {"profile": p}

    def runs(self, req: Request):
        st = self._gate(req)
        if st == "empty":
            return {"runs": []}
        runs = copy.deepcopy(self._started + self._runs)
        if st == "partial":
            for r in runs:
                r["summary"] = None
            runs[0]["status"] = "failed"
        return {"runs": runs}

    # ---- results / review (A5) — fixture thẳng ----
    def results_overview(self, req: Request):
        st = self._gate(req)
        if st == "empty":
            d = _fx("overview.json")
            d["labels"] = {k: 0 for k in d.get("labels", {})}
            return d
        return _fx("overview.json")

    def results_findings(self, req: Request):
        st = self._gate(req)
        d = _fx("findings.json")
        if st == "empty":
            d["rows"] = []
            d["total"] = 0
        return d

    def results_finding(self, req: Request):
        self._gate(req)
        return _fx("finding.json")

    def results_commits(self, req: Request):
        st = self._gate(req)
        d = _fx("commits.json")
        if st == "empty":
            d["rows"] = []
            d["total"] = 0
        return d

    def results_export(self, req: Request):
        self._gate(req)
        fmts = (req.body or {}).get("formats") or ["jsonl"]
        files = ["dataset.jsonl", "commits.jsonl", "run_manifest.json", "SHA256SUMS"]
        if "csv" in fmts:
            files += ["dataset.csv", "commits.csv"]
        return {"export_dir": "D:\\secjit\\results\\export_FudanSELab__train-ticket_master_20261005", "files": files}

    def results_raw(self, req: Request):
        self._gate(req)
        path = req.query.get("path") or ""
        if not path or "missing" in path:
            raise ApiError(404, "not_found", f"Không có raw {path}", "File đã bị dọn hoặc backend chưa phục vụ /raw")
        return Text(f"# raw giả lập cho {path}\n" + json.dumps(_fx("finding.json").get("tool_messages", []), ensure_ascii=False, indent=2))

    def results_features(self, req: Request):
        self._gate(req)
        return {"ok": True, "computed": 27, "detail": "Kamei 14 đặc trưng (mock)"}

    def results_relabel(self, req: Request):
        self._gate(req)
        return {"ok": True, "relabeled": 27, "gold": 2, "silver": 11, "candidate": 17}

    def open_path(self, req: Request):
        self._gate(req)
        p = (req.body or {}).get("path") or req.query.get("path") or ""
        if not p:
            raise ApiError(404, "not_found", "Thiếu path", "")
        return {"ok": True, "path": p}

    def review_sample(self, req: Request):
        self._gate(req)
        return _fx("review_sample.json")

    def review_next(self, req: Request):
        self._gate(req)
        return _fx("review_item.json")

    def review_verdict(self, req: Request):
        self._gate(req)
        return {"ok": True, "remaining": 41}

    def review_close(self, req: Request):
        self._gate(req)
        return _fx("review_close.json")

    # ---- settings / storage / clean / profiles ----
    def settings_get(self, req: Request):
        self._gate(req)
        return dict(self._settings)

    def settings_set(self, req: Request):
        self._gate(req)
        with self._lock:
            self._settings.update(req.body or {})
            return dict(self._settings)

    def settings_pick_dir(self, req: Request):
        self._gate(req)
        return {"path": "D:\\secjit\\results"}

    def storage(self, req: Request):
        st = self._gate(req)
        d = _fx("storage.json")
        if st == "empty":
            d["items"] = []
            d["total_bytes"] = 0
        return d

    def clean(self, req: Request):
        self._gate(req)
        body = req.body or {}
        d = _fx("clean_dry.json")
        if not body.get("dry_run"):
            d["deleted"] = [x["path"] for x in d.get("would_delete", [])]
        return d

    def profiles_list(self, req: Request):
        st = self._gate(req)
        if st == "empty":
            return {"profiles": []}
        return {"profiles": list(self._profiles)}

    def profiles_save(self, req: Request):
        self._gate(req)
        body = req.body or {}
        name = (body.get("name") or "").strip()
        p = body.get("profile") or {}
        if not name:
            raise ApiError(400, "bad_request", "Thiếu tên profile", "")
        if prof is not None:
            errs = prof.validate(p)
            if errs:
                raise ApiError(400, "invalid_profile", "; ".join(errs), "")
        with self._lock:
            self._profiles = [x for x in self._profiles if x["name"] != name]
            self._profiles.insert(0, {"name": name, "repo": p.get("repo"), "saved": time.strftime("%Y-%m-%dT%H:%M:%S")})
            self._profiles_full[name] = p
        return {"ok": True, "name": name, "path": f"%LOCALAPPDATA%\\secjit\\profiles\\{name}.json"}

    def profiles_get(self, req: Request):
        self._gate(req)
        name = req.params["name"]
        p = self._profiles_full.get(name)
        if p is None:
            if prof is None:
                raise ApiError(404, "not_found", f"Không có profile {name}", "")
            p = prof.from_env_defaults("https://github.com/FudanSELab/train-ticket", "master", "D:\\secjit\\results")
            p["scope"]["max"] = 30
        return {"name": name, "profile": p}

    def profiles_delete(self, req: Request):
        self._gate(req)
        name = req.params["name"]
        with self._lock:
            self._profiles = [x for x in self._profiles if x["name"] != name]
            self._profiles_full.pop(name, None)
        return {"ok": True}

    def shell(self, req: Request):
        self._gate(req)
        return _shell_from_request(req)

    def diagnostics(self, req: Request):
        self._gate(req)
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("preflight.json", json.dumps(_fx("preflight.json"), ensure_ascii=False, indent=2))
            z.writestr("settings.json", json.dumps(self._settings, ensure_ascii=False, indent=2))
            z.writestr("README.txt", "Gói chẩn đoán giả lập (mock).")
        return Binary(buf.getvalue(), "application/zip", "secjit-diagnostics-mock.zip")


def _shell_from_request(req: Request) -> dict:
    """Dùng chung mock/real: profile từ body {profile} hoặc query ?profile=<json>; shell=powershell|bash."""
    if prof is None:
        raise ApiError(501, "not_implemented", "Thiếu orchestrator.profile", "Chạy từ gốc repo")
    p = None
    if req.body and isinstance(req.body.get("profile"), dict):
        p = req.body["profile"]
    elif req.query.get("profile"):
        try:
            p = json.loads(req.query["profile"])
        except json.JSONDecodeError as e:
            raise ApiError(400, "bad_json", f"profile không phải JSON: {e}", "")
    if not isinstance(p, dict):
        raise ApiError(400, "bad_request", "Thiếu profile", "GET ?profile=<json>&shell=… hoặc POST {profile, shell}")
    shell = (req.query.get("shell") or (req.body or {}).get("shell") or "powershell").lower()
    if shell not in ("powershell", "bash"):
        raise ApiError(400, "bad_request", "shell phải là powershell|bash", "")
    errs = prof.validate(p)
    return {"command": prof.to_shell(p, shell), "shell": shell, "errors": errs}
