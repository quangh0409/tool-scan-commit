"""Test server GUI (mock in-process): token bắt buộc, JSON lỗi, ?state=error, SSE replay, tĩnh, shell."""
from __future__ import annotations

import json
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
    assert set(body["error"]) == {"code", "message", "hint"}


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
    with urllib.request.urlopen(url, timeout=10) as r:
        assert r.headers["Content-Type"].startswith("text/event-stream")
        text = r.read().decode("utf-8")        # mock follow=False -> gửi `event: end` rồi đóng
    datas = [ln[6:] for ln in text.split("\n") if ln.startswith("data: ") and ln != "data: {}"]
    assert len(datas) == 8
    first = json.loads(datas[0])
    assert first["phase"] == "scan" and first["event"] == "start" and first["total"] == 27
    assert "event: end" in text


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
