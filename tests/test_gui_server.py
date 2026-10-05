"""Test server GUI (mock in-process): token bắt buộc, JSON lỗi, ?state=error, SSE replay, tĩnh, shell."""
from __future__ import annotations

import json
import os
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui.api_mock import MockApi  # noqa: E402
from gui.server import GuiServer  # noqa: E402

PROFILE = {
    "schema": 1, "repo": "https://github.com/FudanSELab/train-ticket", "branch": "master",
    "scope": {"mode": "count", "since": None, "until": None, "max": 30, "from_sha": None, "to_sha": None},
    "include_clean": True, "cheap_tools": ["gitleaks", "semgrep"], "expensive_tools": ["findsecbugs", "sonar"],
    "codeql": False, "workers": {"scan": 4, "expensive": 1},
    "paths": {"db": "D:\\x\\it's here\\d.sqlite", "export": "D:\\x\\exp", "work": "D:\\x\\work"},
    "sonar_port": 9100, "experiment": None,
    "params_v1": {"line_window": 3, "gold_min_expensive": 2, "gold_allow_1exp_1cheap": 1, "silver_min_cheap": 2,
                  "noise_cwe": ["CWE-117"]},
}


@pytest.fixture(scope="module")
def server():
    srv = GuiServer(MockApi(loading_sec=0.3), port=0)
    srv.serve_in_thread()
    yield srv
    srv.stop()


def call(srv, path, method="GET", body=None, token=True, raw=False):
    url = f"http://127.0.0.1:{srv.port}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if token:
        req.add_header("X-Token", srv.token)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            payload = r.read()
            return r.status, (payload if raw else json.loads(payload.decode("utf-8"))), dict(r.headers)
    except urllib.error.HTTPError as e:
        payload = e.read()
        try:
            return e.code, json.loads(payload.decode("utf-8")), dict(e.headers)
        except json.JSONDecodeError:
            return e.code, payload, dict(e.headers)


def test_url_has_token(server):
    assert server.url.startswith(f"http://127.0.0.1:{server.port}/?t=")
    assert server.token in server.url and len(server.token) >= 24


def test_api_requires_token(server):
    st, body, _ = call(server, "/api/runs", token=False)
    assert st == 401
    assert body["error"]["code"] == "unauthorized"
    assert {"code", "message", "hint"} <= set(body["error"])


def test_token_via_query_param(server):
    st, body, _ = call(server, f"/api/runs?t={server.token}", token=False)
    assert st == 200 and "runs" in body


def test_runs_fixture(server):
    st, body, hdr = call(server, "/api/runs")
    assert st == 200
    assert hdr["Content-Type"].startswith("application/json")
    ids = {r["run_id"] for r in body["runs"]}
    assert {"r-20261004-scratch", "r-20261005-A", "r-20261005-int"} <= ids


def test_state_error_returns_json_error(server):
    st, body, _ = call(server, "/api/runs?state=error")
    assert st == 500
    assert body["error"]["code"] == "mock_error"
    assert body["error"]["hint"]


def test_state_empty_and_partial(server):
    st, body, _ = call(server, "/api/runs?state=empty")
    assert st == 200 and body["runs"] == []
    st, body, _ = call(server, "/api/runs?state=partial")
    assert st == 200 and all(r["summary"] is None for r in body["runs"])


def test_state_loading_delays(server):
    import time
    t0 = time.monotonic()
    st, _, _ = call(server, "/api/preflight?state=loading")
    assert st == 200 and time.monotonic() - t0 >= 0.25


def test_unknown_endpoint_404_and_405(server):
    st, body, _ = call(server, "/api/nope")
    assert st == 404 and body["error"]["code"] == "not_found"
    st, body, _ = call(server, "/api/runs", method="POST", body={})
    assert st == 405 and body["error"]["code"] == "method_not_allowed"


def test_bad_json_body(server):
    url = f"http://127.0.0.1:{server.port}/api/estimate"
    req = urllib.request.Request(url, data=b"{bad", method="POST")
    req.add_header("X-Token", server.token)
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(req, timeout=10)
    assert ei.value.code == 400
    assert json.loads(ei.value.read())["error"]["code"] == "bad_json"


def test_preflight_fix_progress_then_done(server):
    seen = []
    for _ in range(6):
        st, body, _ = call(server, "/api/preflight/fix", method="POST", body={"fix_id": "pull_images"})
        assert st == 200
        seen.append(body)
        if body.get("done"):
            break
    assert seen[-1]["ok"] is True and seen[-1]["done"] is True
    assert any(not b.get("done") and 0 < b.get("progress", 0) < 100 for b in seen[:-1])
    st, pf, _ = call(server, "/api/preflight")
    images = next(i for i in pf["items"] if i["id"] == "images")
    assert images["level"] == "ok"


def test_preflight_fixed_state(server):
    st, pf, _ = call(server, "/api/preflight?state=fixed")
    assert st == 200 and pf["ready"] is True


def test_shell_post_quotes_paths(server):
    st, body, _ = call(server, "/api/shell", method="POST", body={"profile": PROFILE, "shell": "powershell"})
    assert st == 200
    cmd = body["command"]
    assert "python -m orchestrator.cli 'pipeline'" in cmd
    assert "it''s here" in cmd            # PowerShell quote '' cho dấu nháy đơn
    assert "'--tools' 'gitleaks,semgrep'" in cmd
    st, body, _ = call(server, "/api/shell", method="POST", body={"profile": PROFILE, "shell": "bash"})
    assert st == 200 and "PYTHONPATH=src" in body["command"]
    st, body, _ = call(server, "/api/shell", method="POST", body={"profile": PROFILE, "shell": "zsh"})
    assert st == 400


def test_shell_get_query(server):
    from urllib.parse import quote
    st, body, _ = call(server, f"/api/shell?shell=bash&profile={quote(json.dumps(PROFILE))}")
    assert st == 200 and "ORCH_SQLITE=" in body["command"]


def test_profile_validate_and_run_start(server):
    st, body, _ = call(server, "/api/profile/validate", method="POST", body={"profile": PROFILE})
    assert st == 200 and body["errors"] == [] and body["db_exists"] is False
    bad = dict(PROFILE, scope={"mode": "count", "max": 0})
    st, body, _ = call(server, "/api/run/start", method="POST", body={"profile": bad})
    assert st == 400 and body["error"]["code"] == "invalid_profile"
    st, body, _ = call(server, "/api/run/start", method="POST", body={"profile": PROFILE, "smoke": True})
    assert st == 200 and body["run_id"].startswith("smoke-") and body["smoke"] is True
    st, runs, _ = call(server, "/api/runs")
    assert runs["runs"][0]["run_id"] == body["run_id"] and runs["runs"][0]["status"] == "running"


def test_profiles_crud(server):
    st, body, _ = call(server, "/api/profiles", method="POST", body={"name": "tt-30", "profile": PROFILE})
    assert st == 200 and body["ok"]
    st, body, _ = call(server, "/api/profiles")
    assert any(p["name"] == "tt-30" for p in body["profiles"])
    st, body, _ = call(server, "/api/profiles/tt-30")
    assert st == 200 and body["profile"]["repo"] == PROFILE["repo"]
    st, body, _ = call(server, "/api/profiles/tt-30", method="DELETE")
    assert st == 200
    st, body, _ = call(server, "/api/profiles")
    assert not any(p["name"] == "tt-30" for p in body["profiles"])


def test_sse_replays_lines_and_ends(server):
    url = f"http://127.0.0.1:{server.port}/api/run/r-20261005-A/progress?t={server.token}"
    req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})   # như EventSource
    with urllib.request.urlopen(req, timeout=10) as r:
        assert r.headers["Content-Type"].startswith("text/event-stream")
        text = r.read().decode("utf-8")        # mock follow=False -> gửi `event: end` rồi đóng
    datas = [ln[6:] for ln in text.split("\n") if ln.startswith("data: ") and ln != "data: {}"]
    assert len(datas) == 8
    first = json.loads(datas[0])
    assert first["phase"] == "scan" and first["event"] == "start" and first["total"] == 27
    assert "event: end" in text


def test_progress_json_fallback_for_fetch(server):
    """fetch() thường (dashboard A5 lần đầu) -> JSON {lines:[...]} thay vì stream."""
    st, body, hdr = call(server, "/api/run/r-20261005-A/progress")
    assert st == 200 and hdr["Content-Type"].startswith("application/json")
    assert len(body["lines"]) == 8 and body["lines"][0]["phase"] == "scan" and body["follow"] is False


def test_a5_extra_routes_mock(server):
    st, body, hdr = call(server, "/api/results/r-20261005-A/raw?path=313886e9/semgrep.json", raw=True)
    assert st == 200 and hdr["Content-Type"].startswith("text/plain") and b"raw" in body
    st, body, _ = call(server, "/api/results/r-20261005-A/raw?path=missing.json")
    assert st == 404
    st, body, _ = call(server, "/api/open", method="POST", body={"path": "D:\\x"})
    assert st == 200 and body["ok"]
    st, body, _ = call(server, "/api/results/r-20261005-A/features", method="POST", body={})
    assert st == 200
    st, body, _ = call(server, "/api/results/r-20261005-A/relabel", method="POST", body={})
    assert st == 200


# ---------------------------------------------------------------- api_real (A3 thật, runner giả)

@pytest.fixture
def real_env(monkeypatch, tmp_path):
    # registry.home() đọc env mỗi lần gọi -> chỉ cần set env, KHÔNG pop module (làm hỏng monkeypatch của test khác)
    monkeypatch.setenv("SECJIT_HOME", str(tmp_path / "home"))
    return tmp_path


def test_real_delegate_501_when_a5_module_missing(real_env, monkeypatch):
    import gui.api_real as ar
    from gui.api_real import RealApi
    from gui.server import Request
    api = RealApi()
    # có A5: run lạ -> 404 từ api_results.overview
    with pytest.raises(Exception) as ei:
        api.results_overview(Request("GET", "/api/results/x/overview", {"id": "x"}, {}, None))
    assert getattr(ei.value, "status", None) == 404
    # giả lập thiếu module A5 -> 501 kèm chữ ký hàm cần cung cấp
    monkeypatch.setattr(ar, "_try_import", lambda mod: None)
    with pytest.raises(Exception) as ei:
        api.results_overview(Request("GET", "/api/results/x/overview", {"id": "x"}, {}, None))
    assert ei.value.status == 501 and "gui.api_results.overview" in ei.value.hint


def test_real_run_start_smoke_and_registry(real_env, monkeypatch, scratch_db):
    """run/start: smoke -> scope count 3 + DB scratch trong SECJIT_HOME; registry có bản ghi running; stop tạo stop-file."""
    import runner
    from gui.api_real import RealApi
    from gui.server import Request
    started = {}

    def fake_start(profile_path, run_id, work_dir, python_exe=None, extra_env=None):
        started.update(profile_path=str(profile_path), run_id=run_id, work=str(work_dir), extra_env=extra_env)
        rdir = runner.run_dir(work_dir, run_id)
        rdir.mkdir(parents=True, exist_ok=True)
        (rdir / "pid").write_text("99999999", encoding="utf-8")
        return {"pid": 99999999, "log": str(rdir / "run.log"), "progress": str(rdir / "progress.jsonl"),
                "stop": str(rdir / "stop"), "run_dir": str(rdir), "meta": "", "argv": []}
    monkeypatch.setattr(runner, "start", fake_start)
    monkeypatch.setattr(runner, "alive", lambda pid: False)

    api = RealApi()
    work = real_env / "work"
    prof = dict(PROFILE, paths={"db": str(scratch_db), "export": str(real_env / "exp"), "work": str(work)})
    # wrapper -> gui.api_runs.run_start (A5): run_id r-<ts>-smoke, DB scratch trong SECJIT_HOME; wrapper ghi formats/notify
    res = api.run_start(Request("POST", "/api/run/start", {}, {}, {"profile": prof, "smoke": True, "formats": ["jsonl", "csv"]}))
    assert "smoke" in res["run_id"] and res["pid"] == 99999999
    saved = json.loads(Path(started["profile_path"]).read_text(encoding="utf-8"))
    assert saved["scope"]["max"] == 3 and saved["scope"]["mode"] == "count"
    assert str(real_env / "home" / "scratch") in saved["paths"]["db"]
    import registry
    rec = registry.get(res["run_id"])
    assert rec and rec["status"] == "running" and rec["smoke"] is True and rec["summary"]["formats"] == ["jsonl", "csv"]
    # bản local (fallback khi thiếu A5): tiền tố smoke-, _smoke_ trong tên DB, extra_env sonar port
    res2 = api.run_start_local(Request("POST", "/api/run/start", {}, {}, {"profile": prof, "smoke": True}))
    assert res2["run_id"].startswith("smoke-") and "_smoke_" in json.loads(Path(started["profile_path"]).read_text(encoding="utf-8"))["paths"]["db"]
    assert started["extra_env"]["ORCH_SONAR_PORT"] == "9100"
    res = res2
    # GET /api/run/{id}/profile đọc đúng file đã ghi
    got = api.run_profile(Request("GET", "", {"id": res["run_id"]}, {}, None))
    assert got["profile"]["scope"]["max"] == 3
    # progress: file chưa có -> SseFile trỏ đúng đường dẫn
    sse = api.run_progress(Request("GET", "", {"id": res["run_id"]}, {}, None))
    assert str(sse.path).endswith(os.path.join(res["run_id"], "progress.jsonl"))
    # stop local (pid giả đã chết) -> stop-file + registry stopped (bản A5 có test riêng trong test_api_results)
    out = api.run_stop_local(Request("POST", "", {"id": res["run_id"]}, {}, {"force": False}))
    assert out["ok"] and (work / res["run_id"] / "stop").exists()
    assert registry.get(res["run_id"])["status"] == "stopped"


def test_real_run_start_rejects_invalid_and_locked(real_env, monkeypatch, scratch_db):
    from gui.api_real import RealApi
    from gui.server import Request
    api = RealApi()
    bad = dict(PROFILE, scope={"mode": "count", "max": 0}, paths={"db": str(scratch_db), "export": "", "work": str(real_env)})
    with pytest.raises(Exception) as ei:
        api.run_start(Request("POST", "", {}, {}, {"profile": bad}))
    assert ei.value.status == 400
    # DB bị pid sống (chính pytest) giữ -> 409
    import registry
    registry.locks.acquire_db_lock(scratch_db, "other-run", pid=os.getpid())
    ok = dict(PROFILE, paths={"db": str(scratch_db), "export": "", "work": str(real_env)})
    with pytest.raises(Exception) as ei:
        api.run_start(Request("POST", "", {}, {}, {"profile": ok}))
    assert ei.value.status == 409 and ei.value.code in ("db_locked", "ECONFLICT")
    with pytest.raises(Exception) as ei:
        api.run_start_local(Request("POST", "", {}, {}, {"profile": ok}))
    assert ei.value.status == 409 and ei.value.code == "db_locked"


def test_real_preflight_fix_polls_until_done(real_env, monkeypatch):
    import preflight
    from gui.api_real import RealApi
    from gui.server import Request
    import time as _t

    def slow_fix(fix_id, ctx=None, progress_cb=None):
        for i in range(1, 4):
            progress_cb({"fix_id": fix_id, "step": i, "total": 3, "msg": f"bước {i}"})
            _t.sleep(0.3)
        return {"ok": True, "detail": "xong", "port": 9100}
    monkeypatch.setattr(preflight, "fix", slow_fix)
    api = RealApi()
    seen = []
    for _ in range(20):
        r = api.preflight_fix(Request("POST", "", {}, {}, {"fix_id": "pick_port"}))
        seen.append(r)
        if r["done"]:
            break
        _t.sleep(0.2)
    assert seen[-1]["ok"] and seen[-1]["done"] and seen[-1]["progress"] == 100
    assert any(not s["done"] for s in seen)
    assert api._settings()["sonar_port"] == 9100     # pick_port ok -> lưu settings


# ---------------------------------------------------------------- repo_probe

def test_repo_probe_parse_and_pom():
    from gui import repo_probe
    out = ("ref: refs/heads/trunk\tHEAD\n"
           "abc\tHEAD\n"
           "abc\trefs/heads/trunk\n"
           "def\trefs/heads/dev\n"
           "123\trefs/tags/v1.0\n"
           "456\trefs/tags/v1.0^{}\n")
    d, b, tg = repo_probe.parse_ls_remote(out)
    assert d == "trunk" and b == ["trunk", "dev"] and tg == ["v1.0"]
    pom = ("<project><parent><artifactId>spring-boot-starter-parent</artifactId><version>2.3.12.RELEASE</version></parent>"
           "<properties><java.version>1.8</java.version></properties>"
           "<modules><module>a</module><module>b</module></modules>"
           "<dependencies><dependency><artifactId>x</artifactId><version>1.0-SNAPSHOT</version></dependency></dependencies></project>")
    info = repo_probe.parse_pom(pom)
    assert info["jdk"] == 8 and info["modules"] == 2 and info["snapshot_risk"] is True and info["spring_boot"] == "2.3.12.RELEASE"


def test_repo_probe_check_uses_git_env_and_pat(monkeypatch):
    import subprocess as sp
    from gui import repo_probe
    calls = []

    def fake_run(args, **kw):
        calls.append((args, kw))
        return sp.CompletedProcess(args, 0, "ref: refs/heads/master\tHEAD\nabc\trefs/heads/master\n", "")
    monkeypatch.setattr(sp, "run", fake_run)
    r = repo_probe.check("https://github.com/FudanSELab/train-ticket/tree/master", pat="ghp_secret", work_dir=None)
    assert r["canon"] == "https://github.com/FudanSELab/train-ticket" and r["slug"] == "FudanSELab__train-ticket"
    assert r["default_branch"] == "master" and r["java_maven"] is None and r["warnings"]
    args, kw = calls[0]
    assert kw["env"]["GIT_TERMINAL_PROMPT"] == "0" and "--symref" in args
    assert "ghp_secret" not in " ".join(args) and any(a.startswith("http.extraheader=AUTHORIZATION: basic ") for a in args)
    # 404 -> ApiError 404
    monkeypatch.setattr(sp, "run", lambda args, **kw: sp.CompletedProcess(args, 128, "", "remote: Repository not found."))
    with pytest.raises(Exception) as ei:
        repo_probe.check("https://github.com/x/y")
    assert ei.value.status == 404


def test_static_index_and_assets(server):
    st, body, hdr = call(server, "/", raw=True, token=False)
    assert st == 200 and hdr["Content-Type"].startswith("text/html") and b"app.js" in body
    st, body, hdr = call(server, "/app.js", raw=True, token=False)
    assert st == 200 and hdr["Content-Type"].startswith("text/javascript") and b"ROUTES" in body
    st, body, hdr = call(server, "/i18n/vi.json", token=False)
    assert st == 200 and body["pf.title"]
    for name in ("preflight", "home", "wizard1", "wizard2", "wizard3", "wizard4", "wizard5"):
        st, body, _ = call(server, f"/screens/{name}.js", raw=True, token=False)
        assert st == 200 and b"export" in body and b"render" in body and b"destroy" in body


def test_static_traversal_blocked(server):
    st, body, _ = call(server, "/..%2F..%2Fgui%2Fserver.py", raw=True, token=False)
    assert st in (403, 404)
    st, body, _ = call(server, "/screens/../../server.py", raw=True, token=False)
    assert st in (403, 404)


def test_i18n_same_keys():
    vi = json.loads((ROOT / "gui/web/i18n/vi.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "gui/web/i18n/en.json").read_text(encoding="utf-8"))
    assert set(vi) == set(en)
    assert all(v for v in vi.values()), "vi.json không được có giá trị rỗng"


def test_diagnostics_zip(server):
    st, body, hdr = call(server, "/api/diagnostics", raw=True)
    assert st == 200 and hdr["Content-Type"] == "application/zip" and body[:2] == b"PK"


def test_free_port_helper():
    from gui.server import free_port
    p = free_port()
    assert 1024 < p < 65536
    with socket.socket() as s:
        s.bind(("127.0.0.1", p))
