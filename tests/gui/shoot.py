"""Chụp ảnh từng màn × trạng thái bằng Playwright trên server mock.

Dùng: python tests/gui/shoot.py [--out DIR] [--routes preflight,home,...] [--keep-going]
  * Khởi động `python -m gui --mock --no-browser --dev` ở cổng ngẫu nhiên (subprocess), đọc SECJIT_GUI_URL.
  * Với mỗi (route, state) mở `<url>#/<route>?state=<state>` ở 1280×900, chờ body[data-ready] (hoặc 700 ms cho
    state=loading) rồi chụp PNG vào --out.
  * Thu console.error / pageerror; thoát mã 1 nếu có (bỏ qua "Failed to load resource" khi state=error vì
    đó là HTTP 500 có chủ ý của mock).
Yêu cầu: `pip install playwright && playwright install chromium` (đã có trên máy dev).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = Path(os.environ.get("SECJIT_SHOTS_DIR") or
                   r"C:/Users/ADMIN/AppData/Local/Temp/claude/D--Master-s-thesis-tool-scan-commit/"
                   r"636db7ca-5b28-4835-9b65-2eb2f9cf4dff/scratchpad/shots/a4/")

# route -> các state cần chụp ("" = mặc định)
PLAN: dict[str, list[str]] = {
    "preflight": ["", "loading", "error", "fixed", "partial", "empty", "docker_down"],
    "home": ["", "loading", "error", "empty", "partial", "docker_down"],
    "wizard/1": ["", "loading", "error", "partial", "empty", "blank"],
    "wizard/2": ["", "loading", "error", "partial", "empty"],
    "wizard/3": ["", "partial"],
    "wizard/4": ["", "error", "partial"],
    "wizard/5": ["", "loading", "error", "partial"],
}

# Profile mẫu seed vào sessionStorage để wizard 2–5 có dữ liệu (CONTRACTS §2)
PROFILE = {
    "schema": 1, "repo": "https://github.com/FudanSELab/train-ticket", "branch": "master",
    "scope": {"mode": "time", "since": "2019-01-01", "until": "2019-12-31", "max": 50, "from_sha": None, "to_sha": None},
    "include_clean": True, "cheap_tools": ["gitleaks", "trufflehog", "semgrep", "bearer", "horusec"],
    "expensive_tools": ["findsecbugs", "sonar"], "codeql": False, "workers": {"scan": 4, "expensive": 1},
    "paths": {"db": "D:\\secjit\\results\\dataset_FudanSELab__train-ticket_master_20261005.sqlite",
              "export": "D:\\secjit\\results\\export_FudanSELab__train-ticket_master_20261005", "work": "D:\\secjit\\work"},
    "sonar_port": 9100, "experiment": None,
    "params_v1": {"line_window": 3, "gold_min_expensive": 2, "gold_allow_1exp_1cheap": 1, "silver_min_cheap": 2, "noise_cwe": ["CWE-117"]},
}
REPO_CHECK = json.loads((ROOT / "gui/fixtures/repo_check.json").read_text(encoding="utf-8"))
PREFLIGHT = json.loads((ROOT / "gui/fixtures/preflight.json").read_text(encoding="utf-8"))
ESTIMATE = json.loads((ROOT / "gui/fixtures/estimate.json").read_text(encoding="utf-8"))
ESTIMATE["speed"] = {"cheap_s_per_commit": 12, "gitleaks": 2, "trufflehog": 3, "semgrep": 15, "bearer": 10, "horusec": 20,
                     "findsecbugs": 7, "sonar": 30, "build_cold_s": 420, "build_warm_s": 150}


def seed_script(route: str, state: str) -> str:
    """sessionStorage seed: wizard 2–5 cần profile; wizard/1 'blank' = form trống; state=empty ở wizard = chưa có repo."""
    meta = {"repo_check": REPO_CHECK, "estimate": ESTIMATE, "out_dir": "D:\\secjit\\results", "work_dir": "D:\\secjit\\work",
            "settings": {"out_dir": "D:\\secjit\\results", "work_dir": "D:\\secjit\\work", "sonar_port": 9100},
            "formats": ["jsonl"], "notify": True}
    prof = dict(PROFILE)
    if route.startswith("wizard"):
        if state == "blank" or (state == "empty" and route == "wizard/1"):
            prof, meta = None, {}
        elif state == "empty":
            prof = dict(PROFILE, repo="", branch="")
            meta = {}
        elif route == "wizard/1":
            meta = {"repo_check": None}      # ép tự gọi /api/repo/check để thấy loading/error
    items = [("secjit.preflight", dict(PREFLIGHT, at=int(time.time() * 1000), ready=True))]
    if prof is not None:
        items.append(("secjit.wizard.profile", prof))
    items.append(("secjit.wizard.meta", meta))
    lines = ["try {"]
    for k, v in items:
        lines.append(f"  sessionStorage.setItem({json.dumps(k)}, {json.dumps(json.dumps(v, ensure_ascii=False))});")
    lines.append("} catch (e) {}")
    return "\n".join(lines)


def start_server() -> tuple[subprocess.Popen, str]:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    proc = subprocess.Popen([sys.executable, "-m", "gui", "--mock", "--no-browser", "--dev"], cwd=str(ROOT), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    url = ""
    deadline = time.time() + 20
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        m = re.match(r"SECJIT_GUI_URL=(\S+)", line.strip())
        if m:
            url = m.group(1)
            break
    if not url:
        proc.kill()
        raise SystemExit("Không đọc được SECJIT_GUI_URL từ server mock")
    return proc, url


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--routes", default="", help="lọc route, phẩy: preflight,home,wizard/1")
    ap.add_argument("--mock", action="store_true", help="(luôn mock; cờ giữ cho tương thích CONTRACTS §10)")
    ap.add_argument("--keep-going", action="store_true", help="không dừng ở lỗi console")
    ap.add_argument("--height", type=int, default=900, help="chiều cao viewport (mặc định 900; tăng để thấy phần dưới)")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    only = [r for r in a.routes.split(",") if r] or list(PLAN)

    from playwright.sync_api import sync_playwright

    proc, url = start_server()
    base, _, token = url.partition("?t=")
    shots: list[str] = []
    errors: list[str] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for route in only:
                for state in PLAN.get(route, [""]):
                    ctx = browser.new_context(viewport={"width": 1280, "height": a.height}, locale="vi-VN", device_scale_factor=1)
                    page = ctx.new_page()
                    page.add_init_script(seed_script(route, state))
                    cons: list[str] = []
                    page.on("console", lambda m, c=cons: c.append(f"{m.type}: {m.text}") if m.type == "error" else None)
                    page.on("pageerror", lambda e, c=cons: c.append(f"pageerror: {e}"))
                    q = "" if state in ("", "blank") else f"?state={state}"
                    page.goto(f"{base}?t={token}#/{route}{q}", wait_until="domcontentloaded")
                    if state == "loading":
                        page.wait_for_timeout(900)
                    else:
                        try:
                            page.wait_for_selector("body[data-ready='1']", timeout=15000)
                            page.wait_for_timeout(500)   # chờ các request phụ (estimate/shell debounce)
                            page.wait_for_load_state("networkidle", timeout=5000)
                        except Exception as e:  # noqa: BLE001
                            cons.append(f"timeout: không thấy data-ready ({type(e).__name__})")
                    name = f"{route.replace('/', '-')}{'--' + state if state else ''}.png"
                    page.screenshot(path=str(out / name), full_page=True)
                    shots.append(name)
                    bad = [c for c in cons if not (state == "error" and "Failed to load resource" in c)]
                    if bad:
                        errors.append(f"{name}: " + " | ".join(bad))
                    ctx.close()
            browser.close()
    finally:
        proc.kill()
    print("ẢNH ĐÃ CHỤP:")
    for s in shots:
        print(" ", out / s)
    if errors:
        print("LỖI CONSOLE JS:")
        for e in errors:
            print(" ", e)
        return 0 if a.keep_going else 1
    print("Không có console.error / pageerror.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
