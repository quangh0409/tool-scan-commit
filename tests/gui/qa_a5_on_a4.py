"""QA chéo của A5 trên khung A4 (TASKS §5, Mô hình C): màn 0–5 × state mock + luồng click thật + tích hợp màn 6–10.

Chạy:  python tests/gui/qa_a5_on_a4.py [--out DIR] [--keep-server]
- Khởi động `python -m gui --dev --mock --no-browser`, đọc SECJIT_GUI_URL.
- Playwright chromium 1280×900; mỗi bước chụp PNG + ghi console.error/pageerror vào report.json.
- Không fail toàn bộ khi một bước lỗi: ghi lại rồi đi tiếp (đây là QA, không phải test gate).
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
DEFAULT_OUT = Path(os.environ.get("SECJIT_QA_DIR") or (
    r"C:\Users\ADMIN\AppData\Local\Temp\claude\D--Master-s-thesis-tool-scan-commit"
    r"\636db7ca-5b28-4835-9b65-2eb2f9cf4dff\scratchpad\shots\qa-a5-on-a4"))
STATES_A4 = ["", "empty", "error", "loading", "partial"]
PROFILE = {
    "schema": 1, "repo": "https://github.com/FudanSELab/train-ticket", "branch": "master",
    "scope": {"mode": "count", "since": None, "until": None, "max": 30, "from_sha": None, "to_sha": None},
    "include_clean": True, "cheap_tools": ["gitleaks", "trufflehog", "semgrep", "bearer", "horusec"],
    "expensive_tools": ["findsecbugs", "sonar"], "codeql": False, "workers": {"scan": 4, "expensive": 1},
    "paths": {"db": "D:\\secjit\\results\\dataset_FudanSELab__train-ticket_master_20261005.sqlite",
              "export": "D:\\secjit\\results\\export_FudanSELab__train-ticket_master_20261005", "work": "D:\\secjit\\work"},
    "sonar_port": 9100, "experiment": None,
    "params_v1": {"line_window": 3, "gold_min_expensive": 2, "gold_allow_1exp_1cheap": 1, "silver_min_cheap": 2, "noise_cwe": ["CWE-117"]},
}


def start_server() -> tuple[subprocess.Popen, str]:
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    p = subprocess.Popen([sys.executable, "-m", "gui", "--dev", "--mock", "--no-browser"], cwd=str(ROOT),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=env)
    url = None
    t0 = time.time()
    while time.time() - t0 < 30:
        line = p.stdout.readline()
        if not line:
            if p.poll() is not None:
                break
            continue
        m = re.search(r"SECJIT_GUI_URL=(\S+)", line)
        if m:
            url = m.group(1)
            break
    if not url:
        raise SystemExit("Không đọc được SECJIT_GUI_URL từ `python -m gui --dev --mock --no-browser`")
    return p, url


class QA:
    def __init__(self, browser, base: str, token: str, out: Path):
        self.browser, self.base, self.token, self.out = browser, base, token, out
        self.report: list[dict] = []
        self.page = None
        self.errs: list[str] = []

    # ---- trang ----
    def new_page(self, seed_profile: bool = True, seed_ready: bool = True):
        if self.page:
            self.page.close()
        ctx = self.browser.new_context(viewport={"width": 1280, "height": 900})
        items = {"secjit.token": self.token}
        if seed_ready:
            pf = json.loads((ROOT / "gui/fixtures/preflight_fixed.json").read_text(encoding="utf-8"))
            pf["at"] = int(time.time() * 1000); pf["ready"] = True
            items["secjit.preflight"] = json.dumps(pf)
        if seed_profile:
            items["secjit.wizard.profile"] = json.dumps(PROFILE)
            items["secjit.wizard.meta"] = json.dumps({"out_dir": "D:\\secjit\\results", "work_dir": "D:\\secjit\\work", "formats": ["jsonl"]})
        js = "try{" + "".join(f"sessionStorage.setItem({json.dumps(k)}, {json.dumps(v)});" for k, v in items.items()) + "}catch(e){}"
        ctx.add_init_script(js)
        self.page = ctx.new_page()
        self.errs = []
        self.page.on("console", lambda m: self.errs.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
        self.page.on("pageerror", lambda e: self.errs.append(f"pageerror: {e}"))
        return self.page

    def goto(self, route: str, wait_ready: bool = True, wait_ms: int = 300):
        self.page.goto(f"{self.base}#/{route}")
        if wait_ready:
            try:
                self.page.wait_for_selector("body[data-ready]", timeout=8000)
            except Exception:  # noqa: BLE001
                pass
        self.page.wait_for_timeout(wait_ms)

    def shot(self, name: str, note: str = "", expect_err: bool = False):
        path = self.out / f"{name}.png"
        try:
            self.page.screenshot(path=str(path))
        except Exception as e:  # noqa: BLE001
            self.report.append({"step": name, "note": note, "errors": [f"screenshot: {e}"]}); return
        errs = [e for e in self.errs if not (expect_err and ("Failed to load resource" in e or "500" in e))]
        try:
            probe = self.page.evaluate("""() => ({
              msgs: [...document.querySelectorAll('.err, .warnmsg, .notice, .errorbox, .toast, .help.invalid, .invalid + .err')].map(e => e.innerText.trim()).filter(Boolean).slice(0, 12),
              invalid: [...document.querySelectorAll('.invalid')].map(e => e.id || e.name || e.tagName),
              next_disabled: (() => { const b = [...document.querySelectorAll('.wiz-foot .btn.primary, .row.end .btn.primary')].pop(); return b ? !!b.disabled : null; })(),
              hash: location.hash, dialog: !!document.querySelector('.dlg'),
            })""")
        except Exception as e:  # noqa: BLE001
            probe = {"probe_error": str(e)[:200]}
        self.report.append({"step": name, "note": note, "png": path.name, "errors": errs, "probe": probe, "text": self.text()[:300]})
        self.errs = []

    def text(self) -> str:
        try:
            return self.page.inner_text("#main")
        except Exception:  # noqa: BLE001
            return ""

    def click(self, sel: str, timeout: int = 4000) -> bool:
        try:
            self.page.click(sel, timeout=timeout); self.page.wait_for_timeout(350); return True
        except Exception as e:  # noqa: BLE001
            self.errs.append(f"click({sel}): {str(e).splitlines()[0]}"); return False

    def fill(self, sel: str, value: str) -> bool:
        try:
            self.page.fill(sel, value, timeout=3000); self.page.wait_for_timeout(250); return True
        except Exception as e:  # noqa: BLE001
            self.errs.append(f"fill({sel}): {str(e).splitlines()[0]}"); return False

    def has(self, text: str) -> bool:
        return text in self.text()


def run(out: Path) -> int:
    from playwright.sync_api import sync_playwright
    out.mkdir(parents=True, exist_ok=True)
    srv, url = start_server()
    base = url.split("?")[0]
    token = re.search(r"t=([^&]+)", url).group(1)
    print("server:", base)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            q = QA(browser, base, token, out)
            # ================= 1. màn 0–5 × state =================
            for route in ("preflight", "home", "wizard/1", "wizard/2", "wizard/3", "wizard/4", "wizard/5"):
                for st in STATES_A4 + (["fixed", "docker_down"] if route in ("preflight", "home") else []):
                    q.new_page(seed_profile=True, seed_ready=(route != "preflight"))
                    q.goto(f"{route}?state={st}" if st else route, wait_ready=(st != "loading"), wait_ms=700 if st == "loading" else 300)
                    q.shot(f"{route.replace('/', '-')}--{st or 'default'}", f"{route} state={st or 'mặc định'}", expect_err=(st == "error"))
            # ================= 2. luồng click =================
            # 2.1 Preflight: Sửa tất cả -> Tiếp tục -> Home
            q.new_page(seed_profile=False, seed_ready=False)
            q.goto("preflight")
            q.click("button:has-text('Sửa tất cả')")
            q.page.wait_for_timeout(2500)
            q.shot("flow-01-preflight-fix-all", "Preflight: sau 'Sửa tất cả tự động' (mock: pull_images 3 lượt tiến độ)")
            # nút tiếp tục: nhãn 'Tiếp' hoặc 'Tiếp tục'
            cont_disabled = q.page.evaluate("(() => { const b = [...document.querySelectorAll('.btn.primary')].find(x => x.textContent.includes('Tiếp tục')); return b ? b.disabled : null; })()")
            if cont_disabled:
                ok = q.click("button:has-text('Bỏ qua kiểm tra')")
            else:
                ok = q.click("button:has-text('Tiếp tục')")
            q.page.wait_for_timeout(500)
            q.shot("flow-02a-preflight-continue-dialog", f"Preflight: nút Tiếp tục disabled={cont_disabled} (Git=chặn, không tự sửa) → bấm 'Bỏ qua kiểm tra' → dialog xác nhận")
            if q.page.query_selector(".dlg"):
                q.click(".dlg button:has-text('Tiếp tục dù')")
                q.page.wait_for_timeout(600)
            q.shot("flow-02-preflight-continue", f"Preflight → Tiếp tục (click ok={ok}); mong đợi #/home; hash={q.page.evaluate('location.hash')}")
            # 2.2 Home -> Scan mới
            q.goto("home")
            q.click("#main a.btn:has-text('Scan mới')")
            q.shot("flow-03-home-new-scan", f"Home → Scan mới; hash={q.page.evaluate('location.hash')}")
            # 2.3 W1: nhập URL các dạng
            for i, (u, note) in enumerate([
                ("https://github.com/FudanSELab/train-ticket/tree/master/ts-common", "URL tree/ -> chuẩn hoá + gợi ý nhánh master"),
                ("https://github.com/FudanSELab/train-ticket/pull/123", "URL pull/ -> chuẩn hoá"),
                ("https://github.com/FudanSELab/train-ticket.git", "URL .git"),
                ("git@github.com:FudanSELab/train-ticket.git", "SSH -> HTTPS (mong đợi: cảnh báo + vẫn kiểm tra được)"),
                ("https://gitlab.com/x/y", "gitlab -> chặn (MVP chỉ github)"),
                ("https://github.com/x/notfound", "repo không tồn tại -> 404 errorBox"),
                ("https://github.com/x/private-repo", "repo private không PAT -> 401 + gợi ý PAT"),
            ], start=1):
                q.new_page(seed_profile=False)
                q.goto("wizard/1")
                q.fill("#w1-url", u)
                q.page.wait_for_timeout(300)
                q.click("button:has-text('Kiểm tra')")
                q.page.wait_for_timeout(900)
                q.shot(f"flow-10-w1-url-{i}", f"W1 URL={u} · {note}", expect_err=("notfound" in u or "private" in u))
            # W1 hợp lệ -> Tiếp
            q.new_page(seed_profile=False)
            q.goto("wizard/1")
            q.fill("#w1-url", "https://github.com/FudanSELab/train-ticket/tree/master")
            q.click("button:has-text('Kiểm tra')")
            q.page.wait_for_timeout(900)
            q.click("button:has-text('Tiếp')")
            q.shot("flow-11-w1-next", f"W1 hợp lệ → Tiếp; hash={q.page.evaluate('location.hash')}")
            # 2.4 W2: từng mode + validate
            q.new_page()
            q.goto("wizard/2")
            q.click("#w2-mode-time"); q.fill("#w2-since", "2024-06-30"); q.fill("#w2-until", "2024-01-01")
            q.page.wait_for_timeout(400)
            q.shot("flow-20-w2-time-order", "W2 mode=time từ>đến → mong đợi lỗi '“Từ” phải ≤ “đến”' + Tiếp bị khoá")
            q.click("#w2-mode-count"); q.fill("#w2-max", "0")
            q.page.wait_for_timeout(400)
            q.shot("flow-21-w2-count-zero", "W2 mode=count N=0 → mong đợi lỗi 'Số commit phải > 0' + Tiếp khoá")
            q.fill("#w2-max", "-5"); q.page.wait_for_timeout(300)
            q.shot("flow-22-w2-count-neg", "W2 N=-5 → lỗi")
            q.click("#w2-mode-sha"); q.fill("#w2-from", "xyz"); q.page.wait_for_timeout(400)
            q.shot("flow-23-w2-sha-bad", "W2 mode=sha SHA 'xyz' → mong đợi lỗi hex 7–40")
            q.fill("#w2-from", "abc1234"); q.fill("#w2-to", ""); q.page.wait_for_timeout(700)
            q.shot("flow-24-w2-sha-ok", "W2 SHA hợp lệ → ước tính")
            q.click("#w2-mode-all"); q.page.wait_for_timeout(900)
            q.shot("flow-25-w2-all", "W2 mode=all → ước tính 187 commit (mock)")
            # 2.5 W3: bỏ tool / CodeQL / Nâng cao / Thí nghiệm
            q.new_page()
            q.goto("wizard/3")
            q.click("#w3-c-semgrep"); q.click("#w3-c-bearer"); q.click("#w3-c-horusec"); q.click("#w3-c-gitleaks")
            q.shot("flow-30-w3-fewer-cheap", "W3 bỏ 4 tool rẻ → cảnh báo còn 1 tool / silver không đạt")
            q.click("#w3-e-findsecbugs"); q.click("#w3-e-sonar")
            q.shot("flow-31-w3-no-expensive", "W3 bỏ cả 2 tool đắt → cảnh báo gold không đạt + include_clean")
            q.click("#w3-e-codeql")
            q.shot("flow-32-w3-codeql-dialog", "W3 bật CodeQL → dialog xác nhận + cảnh báo RAM 7 GB < 16 GB")
            q.click(".dlg button:has-text('Bật CodeQL')")
            q.page.wait_for_timeout(400)
            q.shot("flow-32b-w3-codeql-on", "W3 sau khi xác nhận CodeQL → cảnh báo trong warnBox + checkbox bật")
            q.click("details summary:has-text('Nâng cao')")
            q.page.wait_for_timeout(300)
            q.shot("flow-33-w3-advanced-readonly", "W3 Nâng cao mở: tham số v1 chỉ đọc (khoá)")
            q.click("button:has-text('Chế độ thí nghiệm')")
            q.page.wait_for_timeout(400)
            q.fill("#dlg-f-reason", "ngắn")
            q.page.wait_for_timeout(200)
            q.shot("flow-34-w3-exp-short-reason", "W3 dialog thí nghiệm, lý do 'ngắn' (<10) → nút Bật phải bị khoá")
            q.fill("#dlg-f-reason", "sensitivity LINE_WINDOW=5 cho RQ2")
            q.page.wait_for_timeout(200)
            q.click("button:has-text('Bật và cho sửa')")
            q.page.wait_for_timeout(400)
            q.shot("flow-35-w3-exp-on", "W3 thí nghiệm bật → tham số sửa được + notice lý do")
            q.fill("#w3-p-line_window", "5"); q.page.wait_for_timeout(200)
            q.goto("wizard/5")
            q.shot("flow-36-w5-after-exp", "W5 sau khi đổi W=5 có thí nghiệm → không lỗi validate, có notice thí nghiệm")
            # 2.6 W4: đường dẫn
            q.new_page()
            q.goto("wizard/4")
            q.fill("#w4-out", "\\\\server\\share\\results"); q.page.wait_for_timeout(300)
            q.shot("flow-40-w4-unc", "W4 UNC → mong đợi lỗi chặn")
            q.fill("#w4-out", "C:\\Users\\x\\OneDrive\\secjit"); q.page.wait_for_timeout(300)
            q.shot("flow-41-w4-onedrive", "W4 OneDrive → mong đợi cảnh báo (không chặn)")
            q.fill("#w4-out", "D:\\secjit\\work"); q.fill("#w4-work", "D:\\secjit\\work"); q.page.wait_for_timeout(300)
            q.shot("flow-42-w4-same-dir", "W4 OUT = WORK → mong đợi lỗi chặn")
            q.fill("#w4-out", "D:\\secjit\\results"); q.fill("#w4-work", "D:\\secjit\\results\\work"); q.page.wait_for_timeout(300)
            q.shot("flow-43-w4-work-in-out", "W4 WORK nằm trong OUT → lỗi")
            q.fill("#w4-work", "D:\\secjit\\work"); q.fill("#w4-db", "dataset_exists.sqlite"); q.page.wait_for_timeout(1200)
            q.shot("flow-44-w4-db-exists", "W4 DB tên chứa 'exists' → mock db_exists → Resume/Đổi tên/Ghi đè")
            q.click("button:has-text('Đổi tên')"); q.page.wait_for_timeout(600)
            q.shot("flow-45-w4-rename", "W4 Đổi tên → _2")
            # 2.7 W5: CLI, lưu profile, chạy thử
            q.new_page()
            q.goto("wizard/5")
            q.page.wait_for_timeout(800)
            q.shot("flow-50-w5-powershell", "W5 CLI PowerShell")
            q.click("button[role=tab]:has-text('bash')"); q.page.wait_for_timeout(600)
            q.shot("flow-51-w5-bash", "W5 CLI bash")
            q.click("button:has-text('Lưu profile')"); q.page.wait_for_timeout(400)
            q.shot("flow-52-w5-save-dialog", "W5 dialog Lưu profile")
            q.click(".dlg button:has-text('Lưu')"); q.page.wait_for_timeout(600)
            q.shot("flow-53-w5-saved", "W5 sau Lưu → toast đường dẫn")
            q.click("button:has-text('Chạy thử')"); q.page.wait_for_timeout(2500)
            q.shot("flow-54-w5-smoke", f"W5 Chạy thử → mong đợi #/run/<id>?smoke=1; hash={q.page.evaluate('location.hash')}")
            # Chạy thật (mock) -> dashboard run mới
            q.new_page(); q.goto("wizard/5"); q.page.wait_for_timeout(600)
            q.click("button:has-text('Chạy')"); q.page.wait_for_timeout(2500)
            q.shot("flow-55-w5-run", f"W5 Chạy (mock) → #/run/<id>; dashboard run mới không có progress; hash={q.page.evaluate('location.hash')}")
            # ================= 3. màn A5 trong khung A4 =================
            for route in ("run/r-20261005-A", "run/r-20261005-int", "run/r-20261004-scratch", "results/r-20261005-A", "results/r-20261005-A/findings",
                          "results/r-20261005-A/commits", "results/r-20261005-A/export", "review/r-20261005-A",
                          "settings", "settings/storage", "settings/profiles", "settings/language", "settings/mode"):
                q.new_page()
                q.goto(route)
                q.page.wait_for_timeout(1200 if route.startswith("run/") else 400)
                q.shot("a5-" + route.replace("/", "-"), f"màn A5 trong khung A4: #/{route}")
            # tương tác: bấm dòng finding, chấm mù, dọn dẹp xem trước
            q.new_page(); q.goto("results/r-20261005-A/findings"); q.page.wait_for_timeout(500)
            q.click("table tbody tr >> nth=0"); q.page.wait_for_timeout(600)
            q.shot("a5-findings-detail", "A5 Finding: bấm dòng → panel Bằng chứng (adapter onRow)")
            q.new_page(); q.goto("review/r-20261005-A"); q.page.wait_for_timeout(400)
            q.click("button:has-text('Tạo mẫu')"); q.page.wait_for_timeout(500)
            q.click("button:has-text('Bắt đầu chấm mù')"); q.fill("input[aria-label='Người chấm']", "rater1"); q.page.press("input[aria-label='Người chấm']", "Enter"); q.page.wait_for_timeout(600)
            q.shot("a5-review-blind", "A5 Kiểm tay: chấm mù trong khung A4")
            q.new_page(); q.goto("settings/storage"); q.page.wait_for_timeout(400)
            q.click("button:has-text('Xoá…') >> nth=0"); q.page.wait_for_timeout(500)
            q.shot("a5-settings-clean-preview", "A5 Dung lượng: xem trước dry_run")
            q.new_page(); q.goto("run/r-20261005-A"); q.page.wait_for_timeout(1200)
            q.click("button:has-text('Dừng cưỡng bức')"); q.page.wait_for_timeout(400)
            q.shot("a5-dashboard-force-dialog", "A5 Dashboard: dialog typed-confirm của app.js")
            # tích hợp: kiểm tra css/i18n/sse
            q.new_page(); q.goto("run/r-20261005-A"); q.page.wait_for_timeout(1000)
            integ = q.page.evaluate("""() => ({
              screens_css_links: [...document.querySelectorAll('link[rel=stylesheet]')].map(l => l.getAttribute('href')),
              has_components_in_ctx: false,
              secjit_keys: Object.keys(window.SecJIT || {}),
              t_dash_key: window.SecJIT ? window.SecJIT.t('dash.stop_safe') : null,
              t_vi_key: window.SecJIT ? window.SecJIT.t('route.run') : null,
              progress_lines: document.querySelectorAll('.s-log > div').length,
              body_screen: document.body.dataset.screen,
            })""")
            q.report.append({"step": "integration-probe", "note": "kiểm tra tích hợp qua JS", "errors": q.errs, "data": integ})
            browser.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:  # noqa: BLE001
            srv.kill()
    (out / "report.json").write_text(json.dumps(q.report, ensure_ascii=False, indent=2), encoding="utf-8")
    n_err = sum(1 for r in q.report if r.get("errors"))
    print(f"{len(q.report)} bước, {n_err} bước có lỗi console/click → {out / 'report.json'}")
    for r in q.report:
        if r.get("errors"):
            print(f"  [{r['step']}]")
            for e in r["errors"][:4]:
                print("     ", e[:220])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    a = ap.parse_args()
    return run(Path(a.out))


if __name__ == "__main__":
    sys.exit(main())
