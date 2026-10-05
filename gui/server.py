"""Server HTTP cho GUI: stdlib ThreadingHTTPServer, token, tĩnh, JSON API, SSE.

Hợp đồng: CONTRACTS.md §9. Backend là một đối tượng ``api`` (``api_mock.MockApi`` hoặc
``api_real.RealApi``) có các phương thức tên theo bảng ``ROUTES`` bên dưới; mỗi phương thức
nhận ``Request`` và trả:
  * ``dict``                      -> 200 JSON
  * ``(status:int, dict)``        -> JSON với mã HTTP tuỳ ý
  * ``SseFile(path, follow)``     -> text/event-stream: phát lại 200 dòng cuối rồi tail
  * ``Binary(data, ctype, name)`` -> tải file (zip chẩn đoán)
  * raise ``ApiError``            -> ``{"error":{"code","message","hint"}}``
"""
from __future__ import annotations

import json
import mimetypes
import re
import secrets
import socket
import threading
import time
import traceback
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import WEB_DIR
from .errors import ApiError  # noqa: F401 — re-export: `from gui.server import ApiError` vẫn dùng được

SSE_REPLAY_LINES = 200
SSE_POLL_SEC = 0.5


@dataclass
class Request:
    method: str
    path: str
    params: dict = field(default_factory=dict)   # nhóm bắt được từ regex route ({id}, {name}…)
    query: dict = field(default_factory=dict)    # ?k=v (giá trị đầu)
    body: dict | None = None                     # JSON body (POST/DELETE), None nếu rỗng

    @property
    def state(self) -> str:
        """Trạng thái QA giả lập (?state=empty|error|loading|partial) — chỉ mock dùng."""
        return (self.query.get("state") or "").strip()


@dataclass
class SseFile:
    path: str | Path
    follow: bool = True          # False: phát lại rồi gửi `event: end` và đóng
    max_follow_sec: float = 0    # 0 = không giới hạn (đến khi client ngắt)


@dataclass
class Binary:
    data: bytes
    content_type: str = "application/octet-stream"
    filename: str = "download.bin"


@dataclass
class Text:
    """Trả văn bản thô (vd raw SARIF/XML) — client gọi api(path, {raw:true})."""
    text: str
    content_type: str = "text/plain; charset=utf-8"


# Mỗi route một dòng: (method, regex, tên phương thức trên api). Nhóm có tên -> Request.params.
ROUTES: list[tuple[str, str, str]] = [
    ("GET", r"/api/preflight", "preflight"),
    ("POST", r"/api/preflight/fix", "preflight_fix"),
    ("POST", r"/api/repo/check", "repo_check"),
    ("POST", r"/api/estimate", "estimate"),
    ("POST", r"/api/profile/validate", "profile_validate"),
    ("POST", r"/api/run/start", "run_start"),
    ("POST", r"/api/run/(?P<id>[^/]+)/stop", "run_stop"),
    ("POST", r"/api/run/(?P<id>[^/]+)/resume", "run_resume"),
    ("GET", r"/api/run/(?P<id>[^/]+)/progress", "run_progress"),
    ("GET", r"/api/run/(?P<id>[^/]+)/profile", "run_profile"),
    ("GET", r"/api/runs", "runs"),
    ("GET", r"/api/results/(?P<id>[^/]+)/overview", "results_overview"),
    ("GET", r"/api/results/(?P<id>[^/]+)/findings", "results_findings"),
    ("GET", r"/api/results/(?P<id>[^/]+)/finding/(?P<cluster_key>[^/]+)", "results_finding"),
    ("GET", r"/api/results/(?P<id>[^/]+)/commits", "results_commits"),
    ("POST", r"/api/results/(?P<id>[^/]+)/export", "results_export"),
    ("GET", r"/api/results/(?P<id>[^/]+)/raw", "results_raw"),           # §12 A5: ?path= -> text thô
    ("POST", r"/api/results/(?P<id>[^/]+)/features", "results_features"),
    ("POST", r"/api/results/(?P<id>[^/]+)/relabel", "results_relabel"),
    ("POST", r"/api/open", "open_path"),                                   # §12 A5: mở thư mục
    ("POST", r"/api/review/(?P<id>[^/]+)/sample", "review_sample"),
    ("GET", r"/api/review/(?P<id>[^/]+)/next", "review_next"),
    ("POST", r"/api/review/(?P<id>[^/]+)/verdict", "review_verdict"),
    ("POST", r"/api/review/(?P<id>[^/]+)/close", "review_close"),
    ("GET", r"/api/settings", "settings_get"),
    ("POST", r"/api/settings", "settings_set"),
    ("POST", r"/api/settings/pick_dir", "settings_pick_dir"),
    ("GET", r"/api/storage", "storage"),
    ("POST", r"/api/clean", "clean"),
    ("GET", r"/api/profiles", "profiles_list"),
    ("POST", r"/api/profiles", "profiles_save"),
    ("GET", r"/api/profiles/(?P<name>[^/]+)", "profiles_get"),
    ("DELETE", r"/api/profiles/(?P<name>[^/]+)", "profiles_delete"),
    ("GET", r"/api/shell", "shell"),
    ("POST", r"/api/shell", "shell"),
    ("GET", r"/api/diagnostics", "diagnostics"),
]
_COMPILED = [(m, re.compile("^" + rx + "/?$"), name) for m, rx, name in ROUTES]

_MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
}


def _tail_lines(path: Path, n: int) -> tuple[list[str], int]:
    """Trả (n dòng cuối, offset byte cuối file). Đọc toàn file (progress.jsonl nhỏ)."""
    try:
        data = path.read_bytes()
    except OSError:
        return [], 0
    text = data.decode("utf-8", errors="replace")
    lines = [ln for ln in text.split("\n") if ln.strip()]
    return lines[-n:], len(data)


class GuiHandler(BaseHTTPRequestHandler):
    server: "GuiServer"
    protocol_version = "HTTP/1.1"

    # --- tiện ích ---
    def log_message(self, fmt, *args):  # im lặng trừ khi --verbose
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)

    def _send_json(self, status: int, obj) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _send_error(self, err: ApiError) -> None:
        self._send_json(err.status, err.to_json())

    def _read_body(self) -> dict | None:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return None
        raw = self.rfile.read(n)
        if not raw.strip():
            return None
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ApiError(400, "bad_json", f"Body không phải JSON hợp lệ: {e}", "Gửi Content-Type: application/json")
        if not isinstance(obj, dict):
            raise ApiError(400, "bad_json", "Body phải là JSON object", "")
        return obj

    def _check_token(self, query: dict) -> bool:
        tok = self.headers.get("X-Token") or query.get("t") or ""
        return secrets.compare_digest(tok, self.server.token)

    # --- phân phối ---
    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_HEAD(self):
        self._dispatch("HEAD")

    def _dispatch(self, method: str) -> None:
        parts = urlsplit(self.path)
        path = parts.path
        query = {k: v[0] for k, v in parse_qs(parts.query, keep_blank_values=True).items()}
        try:
            if path.startswith("/api/"):
                self._handle_api(method, path, query)
            else:
                self._handle_static(path)
        except ApiError as e:
            self._send_error(e)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as e:  # noqa: BLE001 — mọi lỗi bất ngờ đều phải thành JSON
            tb = traceback.format_exc()
            if getattr(self.server, "verbose", False):
                print(tb)
            try:
                self._send_error(ApiError(500, "internal", f"{type(e).__name__}: {e}", "Xem log server"))
            except OSError:
                pass

    def _handle_api(self, method: str, path: str, query: dict) -> None:
        if not self._check_token(query):
            raise ApiError(401, "unauthorized", "Thiếu hoặc sai token",
                           "Gửi header X-Token hoặc mở lại URL có ?t=<token> in ra lúc khởi động")
        want = "GET" if method == "HEAD" else method
        matched_path = False
        for m, rx, name in _COMPILED:
            mo = rx.match(path)
            if not mo:
                continue
            matched_path = True
            if m != want:
                continue
            fn = getattr(self.server.api, name, None)
            if fn is None:
                raise ApiError(501, "not_implemented", f"Backend chưa có {name}()", "Chờ A3/A5 nối")
            body = self._read_body() if want in ("POST", "DELETE") else None
            req = Request(method=want, path=path, params=mo.groupdict(), query=query, body=body)
            self._last_req = req
            result = fn(req)
            self._send_result(result)
            return
        if matched_path:
            raise ApiError(405, "method_not_allowed", f"{method} không hỗ trợ cho {path}", "")
        raise ApiError(404, "not_found", f"Không có endpoint {path}", "Xem CONTRACTS.md §9")

    def _send_result(self, result) -> None:
        if isinstance(result, SseFile):
            accept = self.headers.get("Accept") or ""
            if "text/event-stream" in accept:
                self._send_sse(result)
            elif getattr(self.server.api, "run_progress_json", None) is not None and hasattr(self, "_last_req"):
                # poll ?since=N -> {lines, next} (A5 api_runs.get_progress_lines)
                self._send_json(200, self.server.api.run_progress_json(self._last_req))
            else:
                # fetch() thường (mock) -> JSON {lines:[...]} 200 dòng cuối
                lines, _ = _tail_lines(Path(result.path), SSE_REPLAY_LINES)
                parsed = []
                for ln in lines:
                    try:
                        parsed.append(json.loads(ln))
                    except json.JSONDecodeError:
                        continue
                self._send_json(200, {"lines": parsed, "follow": bool(result.follow)})
        elif isinstance(result, Text):
            data = result.text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", result.content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        elif isinstance(result, Binary):
            self.send_response(200)
            self.send_header("Content-Type", result.content_type)
            self.send_header("Content-Disposition", f'attachment; filename="{result.filename}"')
            self.send_header("Content-Length", str(len(result.data)))
            self.end_headers()
            self.wfile.write(result.data)
        elif isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], int):
            self._send_json(result[0], result[1])
        elif result is None:
            self._send_json(200, {"ok": True})
        else:
            self._send_json(200, result)

    def _send_sse(self, sse: SseFile) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        path = Path(sse.path)
        lines, offset = _tail_lines(path, SSE_REPLAY_LINES)
        # §12: ?replay=0 -> không phát lại (client đã fetch JSON trước), chỉ tail dòng mới
        replay = (getattr(self, "_last_req", None) and self._last_req.query.get("replay", "1")) != "0"
        if replay:
            for ln in lines:
                self.wfile.write(f"data: {ln}\n\n".encode("utf-8"))
        self.wfile.flush()
        if not sse.follow:
            self.wfile.write(b"event: end\ndata: {}\n\n")
            self.wfile.flush()
            return
        t0 = time.monotonic()
        buf = ""
        while not self.server.stopping.is_set():
            if sse.max_follow_sec and time.monotonic() - t0 > sse.max_follow_sec:
                self.wfile.write(b"event: end\ndata: {}\n\n")
                self.wfile.flush()
                return
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            if size > offset:
                with open(path, "rb") as f:
                    f.seek(offset)
                    chunk = f.read(size - offset)
                offset = size
                buf += chunk.decode("utf-8", errors="replace")
                while "\n" in buf:
                    ln, buf = buf.split("\n", 1)
                    if ln.strip():
                        self.wfile.write(f"data: {ln}\n\n".encode("utf-8"))
                self.wfile.flush()
            else:
                # heartbeat để phát hiện client ngắt
                self.wfile.write(b": ping\n\n")
                self.wfile.flush()
                time.sleep(SSE_POLL_SEC)

    def _handle_static(self, path: str) -> None:
        if path in ("", "/"):
            path = "/index.html"
        rel = path.lstrip("/")
        target = (WEB_DIR / rel).resolve()
        try:
            target.relative_to(WEB_DIR.resolve())
        except ValueError:
            raise ApiError(403, "forbidden", "Đường dẫn ngoài thư mục web", "")
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            # SPA: đường dẫn lạ -> index.html để router hash xử lý
            if "." not in target.name:
                target = WEB_DIR / "index.html"
            else:
                raise ApiError(404, "not_found", f"Không có file {rel}", "")
        data = target.read_bytes()
        ctype = _MIME.get(target.suffix.lower()) or mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)


class GuiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, api, port: int = 0, token: str | None = None, host: str = "127.0.0.1",
                 verbose: bool = False):
        self.api = api
        self.token = token or secrets.token_urlsafe(24)
        self.verbose = verbose
        self.stopping = threading.Event()
        super().__init__((host, port), GuiHandler)

    @property
    def port(self) -> int:
        return self.server_address[1]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?t={self.token}"

    def serve_in_thread(self) -> threading.Thread:
        th = threading.Thread(target=self.serve_forever, kwargs={"poll_interval": 0.25}, daemon=True)
        th.start()
        return th

    def stop(self) -> None:
        self.stopping.set()
        self.shutdown()
        self.server_close()


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
