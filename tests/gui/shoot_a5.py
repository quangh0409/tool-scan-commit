"""Chụp ảnh màn 6–10 (A5) qua harness fixture — không cần backend.

Chạy:  python tests/gui/shoot_a5.py [--out DIR] [--only dashboard,review] [--states normal,empty]
Khởi động `python -m http.server` tại gui/ (cổng ngẫu nhiên), mở Playwright chromium 1280×900 tới
web/screens/_harness.html#<route>?state=<s> cho mọi màn × {normal, loading, empty, error, partial} (+ trạng thái riêng
của Dashboard và 2 kịch bản tương tác), lưu PNG. Exit 1 nếu có console.error / pageerror.
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "gui"
DEFAULT_OUT = Path(os.environ.get("SHOTS_DIR") or (
    r"C:\Users\ADMIN\AppData\Local\Temp\claude\D--Master-s-thesis-tool-scan-commit"
    r"\636db7ca-5b28-4835-9b65-2eb2f9cf4dff\scratchpad\shots\a5"
))
RUN = "r-20261005-A"
SCREENS = {
    "dashboard": f"/run/{RUN}",
    "results_overview": f"/results/{RUN}/overview",
    "results_findings": f"/results/{RUN}/findings",
    "results_commits": f"/results/{RUN}/commits",
    "results_export": f"/results/{RUN}/export",
    "settings_docker": "/settings/docker",
    "settings_storage": "/settings/storage",
    "settings_profiles": "/settings/profiles",
    "settings_mode": "/settings/mode",
    "settings_language": "/settings/language",
    "review": f"/review/{RUN}",
}
STATES = ["normal", "loading", "empty", "error", "partial"]
EXTRA = [  # (tên, route) — trạng thái riêng
    ("dashboard__interrupted", "/run/r-20261005-int?state=interrupted"),
    ("dashboard__infra_stop", f"/run/{RUN}?state=infra"),
    ("dashboard__scratch", "/run/r-20261004-scratch?state=scratch"),
    ("dashboard__done", f"/run/{RUN}?state=done"),
    ("results_overview__experiment", f"/results/{RUN}/overview?state=normal&exp=1"),
]
WAIT_MS = {"dashboard": 2600, "default": 900}


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--only", default="", help="danh sách màn, phẩy")
    ap.add_argument("--states", default=",".join(STATES))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    only = {s for s in args.only.split(",") if s}
    states = [s for s in args.states.split(",") if s]

    from playwright.sync_api import sync_playwright  # noqa: E402  (import muộn để --help không cần playwright)

    port = free_port()
    srv = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=str(GUI), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}/web/screens/_harness.html#"
    time.sleep(0.8)
    shots: list[str] = []
    failures: list[tuple[str, list[str]]] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()

            def shoot(name: str, route: str, action=None) -> None:
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                errs: list[str] = []
                page.on("console", lambda m: errs.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
                page.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
                page.goto(base + route)
                page.wait_for_timeout(WAIT_MS["dashboard"] if name.startswith("dashboard") else WAIT_MS["default"])
                if action:
                    action(page)
                path = out / f"{name}.png"
                page.screenshot(path=str(path), full_page=False)
                shots.append(str(path))
                if errs:
                    failures.append((name, errs))
                page.close()

            for screen, route in SCREENS.items():
                if only and screen not in only:
                    continue
                for st in states:
                    shoot(f"{screen}__{st}", f"{route}?state={st}")
            for name, route in EXTRA:
                if only and name.split("__")[0] not in only:
                    continue
                shoot(name, route)

            # kịch bản tương tác
            if not only or "results_findings" in only:
                def open_detail(page):
                    page.click("table.sh-table tbody tr >> nth=0")
                    page.wait_for_timeout(500)
                shoot("results_findings__detail", f"{SCREENS['results_findings']}?state=normal", open_detail)

                def open_raw(page):
                    page.click("table.sh-table tbody tr >> nth=0")
                    page.wait_for_timeout(500)
                    page.click("button:has-text('Mở raw') >> nth=0")
                    page.wait_for_timeout(400)
                shoot("results_findings__raw_404_toast", f"{SCREENS['results_findings']}?state=normal", open_raw)
            if not only or "review" in only:
                def rate(page):
                    page.click("button:has-text('Tạo mẫu')")
                    page.wait_for_timeout(500)
                    page.click("button:has-text('Bắt đầu chấm mù')")
                    page.fill("input[aria-label='Người chấm']", "rater1")
                    page.press("input[aria-label='Người chấm']", "Enter")
                    page.wait_for_timeout(600)
                shoot("review__blind_rating", f"{SCREENS['review']}?state=normal", rate)

                def close_(page):
                    rate(page)
                    page.click("button:has-text('Đóng phiên')")
                    page.wait_for_timeout(600)
                shoot("review__close_precision", f"{SCREENS['review']}?state=normal", close_)
            if not only or "settings_storage" in only:
                def preview(page):
                    page.click("button:has-text('Xoá…') >> nth=0")
                    page.wait_for_timeout(500)
                shoot("settings_storage__clean_preview", f"{SCREENS['settings_storage']}?state=normal", preview)
            if not only or "dashboard" in only:
                def force(page):
                    page.click("button:has-text('Dừng cưỡng bức')")
                    page.wait_for_timeout(300)
                shoot("dashboard__force_dialog", f"{SCREENS['dashboard']}?state=normal", force)
            browser.close()
    finally:
        srv.terminate()

    print(f"Đã chụp {len(shots)} ảnh vào {out}")
    for s in shots:
        print("  ", Path(s).name)
    if failures:
        print("\nLỖI CONSOLE:")
        for name, errs in failures:
            print(f"  [{name}]")
            for e in errs:
                print("     ", e)
        return 1
    print("Không có console.error / pageerror.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
