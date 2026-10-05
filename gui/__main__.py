"""Điểm vào: ``python -m gui [--dev] [--mock] [--port N] [--no-browser] [--verbose]``.

* Mặc định: mở cửa sổ pywebview "SecJIT Scan" 1280×900 (nếu có pywebview); lỗi -> mở trình duyệt.
* ``--dev``: không dùng pywebview, mở trình duyệt mặc định (trừ ``--no-browser``), chạy đến Ctrl+C.
* ``--mock``: backend giả lập từ ``gui/fixtures``.
In ra stdout ``SECJIT_GUI_URL=http://127.0.0.1:<port>/?t=<token>`` để script/test đọc.
"""
from __future__ import annotations

import argparse
import sys
import time
import webbrowser

from .server import GuiServer


def build_api(mock: bool):
    if mock:
        from .api_mock import MockApi
        return MockApi()
    from .api_real import RealApi
    return RealApi()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m gui", description="SecJIT Scan GUI")
    ap.add_argument("--dev", action="store_true", help="Chạy trong trình duyệt (không pywebview)")
    ap.add_argument("--mock", action="store_true", help="Backend giả lập từ gui/fixtures")
    ap.add_argument("--port", type=int, default=0, help="Cổng (mặc định: ngẫu nhiên)")
    ap.add_argument("--no-browser", action="store_true", help="Không tự mở trình duyệt/cửa sổ")
    ap.add_argument("--verbose", action="store_true", help="In log HTTP")
    ap.add_argument("--allow-multi", action="store_true", help="Bỏ qua khoá single-instance (QA)")
    a = ap.parse_args(argv)

    # Single-instance (CONTRACTS §7, TC-13): mutex `secjit-gui` qua registry.locks; mock/QA bỏ qua.
    instance = None
    if not a.mock and not a.allow_multi:
        try:
            from registry import locks as _locks  # A3
            instance = _locks.single_instance("secjit-gui")
            if not getattr(instance, "acquired", True):
                print("SecJIT Scan đang mở ở cửa sổ khác. Đóng cửa sổ đó hoặc chạy với --allow-multi.",
                      file=sys.stderr, flush=True)
                return 2
        except ImportError:
            instance = None

    server = GuiServer(build_api(a.mock), port=a.port, verbose=a.verbose)
    server.serve_in_thread()
    url = server.url
    print(f"SECJIT_GUI_URL={url}", flush=True)
    if a.mock:
        print("MODE=mock", flush=True)

    try:
        if not a.dev and not a.no_browser:
            try:
                import webview  # pywebview
                webview.create_window("SecJIT Scan", url, width=1280, height=900, min_size=(960, 640))
                webview.start()
                return 0
            except Exception as e:  # noqa: BLE001
                print(f"CẢNH BÁO: không mở được pywebview ({type(e).__name__}: {e}); mở trình duyệt thay thế.",
                      file=sys.stderr, flush=True)
                webbrowser.open(url)
        elif a.dev and not a.no_browser:
            webbrowser.open(url)
        # chạy đến khi Ctrl+C
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        if instance is not None:
            try:
                instance.release()
            except Exception:  # noqa: BLE001
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
