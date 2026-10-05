"""Đường Run B từ exe, thao tác GUI thật bằng Playwright (click/điền), registry THẬT (SECJIT_HOME mặc định).

python tests/gui/run_b_from_exe.py --exe dist/secjit-scan.exe [--dry|--go] --out-dir DIR --work-dir DIR
       --source-run runA2-20261005 --shots DIR [--port 48801]

Luồng: khởi động `<exe> --dev --no-browser --allow-multi --port N` → đọc SECJIT_GUI_URL →
 (1) POST /api/settings {out_dir, work_dir}  (API, theo yêu cầu trưởng)
 (2) Home → thẻ run --source-run → "Chạy lại cùng profile" → W5 prefilled → Quay lại W4: kiểm paths.work = work-dir,
     DB `..._B.sqlite` (khác DB run nguồn) → Tiếp → W5: POST /api/profile/validate errors=[] → chụp ảnh từng bước.
 --dry : dừng ở W5, lưu profile JSON (sessionStorage) ra <shots>/profile_runB.json, exit 0.
 --go  : bấm Chạy → chờ #/run/<id> + registry có run mới `running` + <work>/<run_id>/pid → in run_id, pid, exit 0.
Exit 1 khi bất kỳ kiểm tra nào sai (in rõ bước nào). Không gọi /api/run/start trực tiếp.
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


def registry_path() -> Path:
    env = os.environ.get("SECJIT_HOME")
    base = Path(env) if env else Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "secjit"
    return base / "runs.json"


def load_registry() -> list[dict]:
    try:
        return json.loads(registry_path().read_text(encoding="utf-8")).get("runs", [])
    except (OSError, ValueError):
        return []


def start_exe(exe: Path, port: int) -> tuple[subprocess.Popen, str]:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    argv = [str(exe), "--dev", "--no-browser", "--allow-multi", "--port", str(port)]
    proc = subprocess.Popen(argv, cwd=str(exe.parent), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    deadline = time.time() + 60
    url = ""
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        print("  exe:", line.rstrip()[:160])
        m = re.search(r"SECJIT_GUI_URL=(\S+)", line)
        if m:
            url = m.group(1)
            break
    if not url:
        proc.kill()
        raise SystemExit("Không đọc được SECJIT_GUI_URL từ exe")
    return proc, url


def kill_tree(proc: subprocess.Popen) -> None:
    """Exe PyInstaller onefile = bootloader + tiến trình con giữ cổng: phải giết cả cây (taskkill /T)."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def norm(p: str) -> str:
    return (p or "").strip().rstrip("\\/").replace("/", "\\").lower()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", required=True)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry", action="store_true", help="dừng ở W5 (mặc định)")
    mode.add_argument("--go", action="store_true", help="bấm Chạy thật")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--source-run", required=True)
    ap.add_argument("--shots", required=True)
    ap.add_argument("--port", type=int, default=48801)
    ap.add_argument("--suffix", default="_B", help="hậu tố DB/export mong đợi (mặc định _B)")
    a = ap.parse_args(argv)
    shots = Path(a.shots)
    shots.mkdir(parents=True, exist_ok=True)
    exe = Path(a.exe).resolve()
    if not exe.exists():
        print(f"Không thấy exe: {exe}")
        return 1

    from playwright.sync_api import sync_playwright

    before_ids = {r.get("run_id") for r in load_registry()}
    src_rec = next((r for r in load_registry() if r.get("run_id") == a.source_run), None)
    if not src_rec:
        print(f"Registry không có run nguồn {a.source_run}: {registry_path()}")
        return 1
    src_db = norm(src_rec.get("db") or "")

    proc, url = start_exe(exe, a.port)
    base, _, token = url.partition("?t=")
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = ""):
        checks.append((name, ok, detail))
        print(("OK   " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))

    cons: list[str] = []
    rc = 1
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            ctx = browser.new_context(viewport={"width": 1280, "height": 1100})
            page = ctx.new_page()
            page.on("console", lambda m: cons.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
            page.on("pageerror", lambda e: cons.append(f"pageerror: {e}"))

            def ready(ms=1200):
                page.wait_for_selector("body[data-ready='1']", timeout=90000)
                page.wait_for_timeout(ms)

            def shot(name):
                page.screenshot(path=str(shots / name), full_page=True)

            # (0) nạp app để có token/ứng dụng
            page.goto(f"{base}?t={token}#/home")
            ready(1500)
            # (1) settings qua API (trưởng cho phép) — để W4 đề xuất trong out_dir và tái dùng work_dir
            st = page.evaluate("async (b) => window.SecJIT.api('/api/settings', {method:'POST', body:b})",
                               {"out_dir": a.out_dir, "work_dir": a.work_dir})
            check("settings out_dir/work_dir", norm(st.get("out_dir")) == norm(a.out_dir) and norm(st.get("work_dir")) == norm(a.work_dir), json.dumps(st, ensure_ascii=False)[:160])
            # (2) Home -> thẻ run nguồn -> Chạy lại cùng profile
            page.goto(f"{base}?t={token}#/home")
            ready(2000)
            shot("01-home.png")
            row = page.locator(f'.run-card[data-run="{a.source_run}"]')
            check("Home có thẻ run nguồn", row.count() == 1, a.source_run)
            btn = row.get_by_role("button", name="Chạy lại cùng profile")
            check("thẻ có nút 'Chạy lại cùng profile'", btn.count() == 1)
            btn.first.click()
            page.wait_for_function("location.hash.startsWith('#/wizard/5')", timeout=30000)
            ready(3000)
            shot("02-wizard5-prefilled.png")
            check("đến W5 prefilled", "nạp từ run " + a.source_run in page.locator("#main").inner_text())
            # (3) Quay lại W4 bằng nút
            page.locator(".wiz-foot .btn").filter(has_text="Quay lại").first.click()   # <a class=btn> (role link)
            page.wait_for_function("location.hash.startsWith('#/wizard/4')", timeout=30000)
            ready(2500)
            shot("03-wizard4.png")
            w4_out = page.locator("#w4-out").input_value()
            w4_work = page.locator("#w4-work").input_value()
            w4_db = page.locator("#w4-db").input_value()
            w4_exp = page.locator("#w4-exp").input_value()
            check("W4 thư mục kết quả = out-dir", norm(w4_out) == norm(a.out_dir), w4_out)
            check("W4 thư mục làm việc = work-dir", norm(w4_work) == norm(a.work_dir), w4_work)
            check(f"W4 DB có hậu tố {a.suffix}.sqlite", w4_db.lower().endswith(f"{a.suffix}.sqlite".lower()), w4_db)
            check(f"W4 export có hậu tố {a.suffix}", w4_exp.lower().endswith(a.suffix.lower()), w4_exp)
            prof = page.evaluate("JSON.parse(sessionStorage.getItem('secjit.wizard.profile'))")
            check("profile.paths.db khác DB run nguồn", norm(prof["paths"]["db"]) != src_db and norm(prof["paths"]["db"]).endswith(f"{a.suffix}.sqlite".lower()), prof["paths"]["db"])
            check("profile.paths.work = work-dir", norm(prof["paths"]["work"]) == norm(a.work_dir), prof["paths"]["work"])
            check("W4 không báo lỗi đường dẫn", page.locator("#main .err").count() == 0, " | ".join(e.inner_text() for e in page.locator("#main .err").all()))
            check("W4 không có hộp 'DB đã tồn tại'", "đã tồn tại" not in page.locator("#main").inner_text())
            # (4) Tiếp -> W5
            page.get_by_role("button", name=re.compile(r"^Tiếp")).click()
            page.wait_for_function("location.hash.startsWith('#/wizard/5')", timeout=30000)
            ready(3000)
            shot("04-wizard5-final.png")
            prof = page.evaluate("JSON.parse(sessionStorage.getItem('secjit.wizard.profile'))")
            val = page.evaluate("async (p) => window.SecJIT.api('/api/profile/validate', {method:'POST', body:{profile:p}})", prof)
            check("profile/validate errors=[]", val.get("errors") == [], json.dumps(val, ensure_ascii=False)[:200])
            check("validate db_exists=false, không lock", not val.get("db_exists") and not (val.get("db_locked") or {}).get("held"))
            run_btn = page.get_by_role("button", name=re.compile(r"Chạy$"))
            check("W5 nút Chạy enabled", run_btn.count() >= 1 and run_btn.first.is_enabled())
            check("W5 không có 'Cấu hình chưa hợp lệ'", "Cấu hình chưa hợp lệ" not in page.locator("#main").inner_text())
            (shots / "profile_runB.json").write_text(json.dumps(prof, ensure_ascii=False, indent=2), encoding="utf-8")
            print("profile:", shots / "profile_runB.json")
            if not a.go:
                rc = 0 if all(ok for _, ok, _ in checks) else 1
            else:
                if not all(ok for _, ok, _ in checks):
                    print("Có kiểm tra FAIL trước khi Chạy — KHÔNG bấm Chạy.")
                    rc = 1
                else:
                    run_btn.first.click()
                    page.wait_for_function("location.hash.startsWith('#/run/')", timeout=120000)
                    rid = re.sub(r"\?.*$", "", page.evaluate("location.hash").split("#/run/")[1])
                    rid = __import__("urllib.parse").parse.unquote(rid)
                    page.wait_for_timeout(2500)
                    shot("05-dashboard.png")
                    rec = None
                    for _ in range(60):
                        rec = next((r for r in load_registry() if r.get("run_id") == rid), None)
                        if rec and rec.get("status") == "running" and rec.get("pid"):
                            break
                        time.sleep(1)
                    pid_file = Path(a.work_dir) / rid / "pid"
                    check("registry có run mới running", bool(rec) and rid not in before_ids and rec.get("status") == "running", json.dumps(rec, ensure_ascii=False)[:200] if rec else "không có")
                    check("work/<run_id>/pid tồn tại", pid_file.exists(), str(pid_file))
                    pid = pid_file.read_text(encoding="utf-8").strip() if pid_file.exists() else (rec or {}).get("pid")
                    print(f"RUN_ID={rid} PID={pid}")
                    rc = 0 if all(ok for _, ok, _ in checks) else 1
            browser.close()
    finally:
        kill_tree(proc)
    if cons:
        print("CONSOLE ERRORS:", cons)
    print("TÓM TẮT:", sum(1 for _, ok, _ in checks if ok), "ok /", sum(1 for _, ok, _ in checks if not ok), "fail", "→ exit", rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
