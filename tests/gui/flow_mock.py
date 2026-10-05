"""Luồng click END-TO-END (Playwright) trên `python -m gui --dev --mock --no-browser` (hoặc backend thật với --real).

  python tests/gui/flow_mock.py [--out DIR] [--real] [--url URL] [--stop-on-fail] [--slow MS] [--headed]

Các bước: Preflight → Sửa tất cả → Tiếp tục → Home → Scan mới → W1 (URL + Kiểm tra + nhánh) → W2 (count 30) → W3
→ W4 → W5 (copy CLI, Lưu profile) → Chạy → Dashboard → Xem kết quả → Tổng quan → Finding → bấm 1 dòng → Bằng chứng
→ Kiểm tay (tạo mẫu, chấm 1, đóng) → Settings/Dung lượng (dry-run).
Mỗi bước: assert phần tử mong đợi, chụp `NN_<bước>.png`, gom console.error/pageerror. Bước fail → chụp `NN_<bước>_FAIL.png`,
ghi lý do, tiếp tục bằng điều hướng trực tiếp (trừ --stop-on-fail). Exit 1 nếu có bước FAIL hoặc console error.
"NOTE" = hạn chế của mock/fixture (không tính fail) — in riêng để trưởng đối chiếu khi chạy backend thật.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = Path(os.environ.get("SECJIT_SHOTS_DIR") or
                   r"C:/Users/ADMIN/AppData/Local/Temp/claude/D--Master-s-thesis-tool-scan-commit/"
                   r"636db7ca-5b28-4835-9b65-2eb2f9cf4dff/scratchpad/shots") / "flow-mock"
REPO_URL = "https://github.com/FudanSELab/train-ticket"
T = 15000  # ms


def start_server(real: bool) -> tuple[subprocess.Popen, str]:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    args = [sys.executable, "-m", "gui", "--no-browser", "--dev"] + ([] if real else ["--mock"])
    proc = subprocess.Popen(args, cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    url, deadline = "", time.time() + 30
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
        raise SystemExit("Không đọc được SECJIT_GUI_URL từ server")
    return proc, url


class Flow:
    def __init__(self, page, base: str, token: str, out: Path, stop_on_fail: bool):
        self.page, self.base, self.token, self.out, self.stop_on_fail = page, base, token, out, stop_on_fail
        self.n = 0
        self.results: list[dict] = []      # {step, status: PASS|FAIL|NOTE, detail, shot}
        self.console: list[str] = []
        self.notes: list[str] = []
        self.run_id: str | None = None
        self.cluster_key: str | None = None
        page.on("console", lambda m: self.console.append(f"[{self.n:02d}] {m.type}: {m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda e: self.console.append(f"[{self.n:02d}] pageerror: {e}"))

    # ------------------------------------------------------------ tiện ích
    def goto(self, route: str):
        self.page.goto(f"{self.base}?t={self.token}#/{route.lstrip('#/')}", wait_until="domcontentloaded")
        self.ready()

    def ready(self, timeout: int = T):
        self.page.wait_for_selector("body[data-ready='1']", timeout=timeout)
        self.page.wait_for_timeout(300)

    def hash(self) -> str:
        return self.page.evaluate("location.hash")

    def wait_hash(self, prefix: str, timeout: int = T):
        self.page.wait_for_function("p => location.hash.startsWith(p)", arg=prefix, timeout=timeout)
        self.ready()

    def btn(self, text: str, exact: bool = False):
        """Nút theo chữ (button hoặc a.btn), ưu tiên nút hiện và không disabled."""
        return self.page.locator("button, a.btn").filter(has_text=re.compile(rf"^\s*{re.escape(text)}" if exact else re.escape(text))).first

    def wiz_next(self):
        return self.page.locator(".wiz-foot button").last

    def dialog_ok(self):
        return self.page.locator(".dlg .btn.primary, .dlg .btn.danger").first

    def note(self, msg: str):
        self.notes.append(f"[{self.n:02d}] {msg}")
        print(f"   NOTE: {msg}")

    def shot(self, name: str, fail: bool = False) -> str:
        fn = f"{self.n:02d}_{name}{'_FAIL' if fail else ''}.png"
        try:
            self.page.screenshot(path=str(self.out / fn), full_page=True)
        except Exception as e:  # noqa: BLE001
            fn = f"{fn} (không chụp được: {e})"
        return fn

    def step(self, name: str, fn, fallback=None):
        self.n += 1
        print(f"{self.n:02d} {name} …", flush=True)
        try:
            fn()
            shot = self.shot(name)
            self.results.append({"step": name, "status": "PASS", "detail": "", "shot": shot})
            print(f"   PASS → {shot}")
        except Exception as e:  # noqa: BLE001
            shot = self.shot(name, fail=True)
            detail = f"{type(e).__name__}: {str(e).splitlines()[0][:300]}"
            self.results.append({"step": name, "status": "FAIL", "detail": detail, "shot": shot,
                                 "hash": self.hash(), "trace": traceback.format_exc()[-1500:]})
            print(f"   FAIL {detail} (hash={self.hash()}) → {shot}")
            if self.stop_on_fail:
                raise
            if fallback:
                try:
                    fallback()
                except Exception as e2:  # noqa: BLE001
                    print(f"   fallback cũng lỗi: {e2}")

    # ------------------------------------------------------------ các bước
    def s_preflight(self):
        self.goto("preflight")
        items = self.page.locator(".item[data-id]")
        items.first.wait_for(timeout=T)
        assert items.count() >= 13, f"chỉ {items.count()} mục preflight (mong 13)"
        assert self.btn("Sửa tất cả").is_visible(), "thiếu nút Sửa tất cả"

    def s_fix_all(self):
        b = self.btn("Sửa tất cả")
        if b.is_disabled():
            self.note("Sửa tất cả bị khoá — không có mục fix_available trong dữ liệu")
            return
        before = self.page.locator(".item[data-id][data-level='fix'], .item[data-id] .btn:not([disabled])").count()
        b.click()
        # chờ hoàn tất: notice fixall biến mất + mục được tải lại
        self.page.wait_for_function("() => !document.querySelector('.fixall-msg')", timeout=120000)
        self.ready()
        self.page.wait_for_timeout(500)
        fixed_ok = self.page.evaluate("""() => {
            const pf = JSON.parse(sessionStorage.getItem('secjit.preflight') || 'null');
            if (!pf || !pf.items) return null;
            return pf.items.filter(i => i.fix_available).length; }""")
        assert fixed_ok is not None, "không đọc được preflight cache sau fix-all"
        assert fixed_ok == 0, f"còn {fixed_ok} mục fix_available sau Sửa tất cả (trước: {before})"

    def s_continue(self):
        cont = self.btn("Tiếp tục")
        cont.wait_for(timeout=T)
        if cont.is_disabled():
            bad = self.page.evaluate("""() => { const pf = JSON.parse(sessionStorage.getItem('secjit.preflight') || 'null');
                return pf ? pf.items.filter(i => i.level === 'bad').map(i => i.id) : []; }""")
            self.note(f"Tiếp tục bị khoá vì mục level=bad {bad} (fixture mock: git=bad không có fix) — điều hướng #/home trực tiếp")
            self.goto("home")
            return
        cont.click()
        dlg = self.page.locator(".dlg")
        try:
            dlg.wait_for(timeout=2000)
            self.dialog_ok().click()          # "Tiếp tục dù còn ⚠️"
        except Exception:  # noqa: BLE001
            pass
        self.wait_hash("#/home")

    def s_home(self):
        assert self.hash().startswith("#/home"), f"hash={self.hash()}"
        assert self.btn("Scan mới").first.is_visible(), "thiếu nút Scan mới"
        assert self.page.get_by_text("Run gần đây").first.is_visible(), "thiếu thẻ Run gần đây"

    def s_new_scan(self):
        self.btn("Scan mới").first.click()
        self.wait_hash("#/wizard/1")
        self.page.wait_for_selector("#w1-url", timeout=T)

    def s_w1(self):
        self.page.fill("#w1-url", REPO_URL)
        self.btn("Kiểm tra", exact=True).click()
        self.page.wait_for_selector("#w1-branch", timeout=90000)
        opts = self.page.locator("#w1-branch option").all_text_contents()
        assert opts, "select nhánh rỗng"
        pick = "master" if any(o.strip() == "master" for o in opts) else opts[0].strip()
        self.page.select_option("#w1-branch", label=pick)
        self.page.wait_for_function("() => { const b = document.querySelector('.wiz-foot button:last-child'); return b && !b.disabled; }", timeout=T)
        self.wiz_next().click()
        self.wait_hash("#/wizard/2")

    def s_w2(self):
        self.page.wait_for_selector("#w2-mode-count", timeout=T)
        self.page.check("#w2-mode-count")
        self.page.fill("#w2-max", "30")
        self.page.dispatch_event("#w2-max", "change")
        self.page.wait_for_timeout(300)
        assert not self.wiz_next().is_disabled(), "Tiếp bị khoá ở W2"
        self.wiz_next().click()
        self.wait_hash("#/wizard/3")
        prof = self.page.evaluate("() => JSON.parse(sessionStorage.getItem('secjit.wizard.profile') || '{}')")
        assert prof.get("scope", {}).get("mode") == "count" and int(prof["scope"].get("max") or 0) == 30, f"scope={prof.get('scope')}"

    def s_w3(self):
        assert self.page.locator("#w3-c-semgrep, [id^='w3-c-']").first.is_visible(), "không thấy checkbox tool"
        assert not self.wiz_next().is_disabled(), "Tiếp bị khoá ở W3"
        self.wiz_next().click()
        self.wait_hash("#/wizard/4")

    def s_w4(self):
        self.page.wait_for_selector("#w4-out", timeout=T)
        self.page.wait_for_timeout(600)       # debounce validate đường dẫn
        if self.wiz_next().is_disabled():
            self.page.fill("#w4-out", "D:\\secjit\\results")
            self.page.wait_for_timeout(800)
        assert not self.wiz_next().is_disabled(), "Tiếp bị khoá ở W4 (đường dẫn không hợp lệ?)"
        self.wiz_next().click()
        self.wait_hash("#/wizard/5")

    def s_w5(self):
        pre = self.page.locator(".copy-wrap pre")
        pre.wait_for(timeout=T)
        self.page.wait_for_function("() => { const b = document.querySelector('.copy-wrap button'); return b && !b.disabled; }", timeout=T)
        cmd = pre.inner_text()
        assert "orchestrator.cli" in cmd and "pipeline" in cmd, f"lệnh CLI lạ: {cmd[:120]}"
        self.page.locator(".copy-wrap button").click()
        self.page.wait_for_timeout(300)
        # Lưu profile
        self.btn("Lưu profile").click()
        self.page.wait_for_selector("#dlg-f-name", timeout=T)
        self.page.fill("#dlg-f-name", "flow-e2e-30")
        self.dialog_ok().click()
        self.page.wait_for_selector(".dlg", state="detached", timeout=T)
        toast = self.page.locator(".toast, #sh-toast-host *").filter(has_text=re.compile("profile|flow-e2e", re.I)).first
        toast.wait_for(timeout=T)

    def s_run(self):
        nxt = self.wiz_next()
        assert "Chạy" in nxt.inner_text(), f"nút cuối W5 là {nxt.inner_text()!r}"
        assert not nxt.is_disabled(), "Chạy bị khoá (profile có lỗi?)"
        nxt.click()
        try:
            self.page.locator(".dlg").wait_for(timeout=1500)
            self.dialog_ok().click()
        except Exception:  # noqa: BLE001
            pass
        self.wait_hash("#/run/", timeout=130000)
        self.run_id = re.sub(r"[?#].*$", "", self.hash().split("#/run/", 1)[1])
        assert self.run_id, "không có run_id trên hash"

    def s_dashboard(self):
        assert self.run_id
        self.page.get_by_text(self.run_id, exact=False).first.wait_for(timeout=T)
        assert self.page.get_by_text(re.compile("Tầng rẻ")).first.is_visible(), "thiếu thanh ① Tầng rẻ"

    def s_view_results(self):
        b = self.btn("Xem kết quả")
        try:
            b.wait_for(timeout=4000)
        except Exception:  # noqa: BLE001
            self.note(f"Dashboard không có 'Xem kết quả' vì run {self.run_id} còn status=running (mock không bao giờ kết thúc run) — điều hướng #/results/{self.run_id}/overview")
            self.goto(f"results/{self.run_id}/overview")
            return
        b.click()
        self.wait_hash("#/results/")

    def s_overview(self):
        self.page.get_by_text("Phễu commit").first.wait_for(timeout=T)
        assert self.page.get_by_text(re.compile("Nhãn \\(3 mức")).first.is_visible(), "thiếu thẻ Nhãn"
        assert self.page.get_by_text("Đồng thuận giữa tool").first.is_visible(), "thiếu thẻ κ"

    def s_findings_tab(self):
        self.page.get_by_role("tab", name="Finding").or_(self.page.locator("button, a").filter(has_text=re.compile(r"^\s*Finding\s*$"))).first.click()
        self.wait_hash("#/results/")
        assert "/findings" in self.hash(), f"hash={self.hash()}"
        rows = self.page.locator("tr[data-key]")
        rows.first.wait_for(timeout=T)
        assert rows.count() >= 1, "bảng finding rỗng"

    def s_click_row(self):
        row = self.page.locator("tr[data-key]").first
        self.cluster_key = row.get_attribute("data-key")
        row.click()
        self.page.get_by_text(re.compile("Provenance")).first.wait_for(timeout=T)

    def s_evidence(self):
        side = self.page.locator("aside.side")
        assert side.get_by_text("Bằng chứng").first.is_visible(), "thiếu thẻ Bằng chứng"
        assert side.get_by_text(re.compile("Eligible")).first.is_visible(), "thiếu Eligible"
        assert self.btn("Kiểm tay cụm này").is_visible(), "thiếu nút Kiểm tay cụm này"

    def s_review_sample(self):
        self.btn("Kiểm tay cụm này").click()
        self.wait_hash("#/review/")
        self.btn("Tạo mẫu", exact=True).wait_for(timeout=T)
        self.btn("Tạo mẫu", exact=True).click()
        self.btn("Bắt đầu chấm mù").wait_for(timeout=T)
        assert self.page.get_by_text(re.compile("n_pos")).first.is_visible()

    def s_review_rate(self):
        self.btn("Bắt đầu chấm mù").click()
        rater = self.page.locator("input[aria-label*='rater' i], input[placeholder*='rater' i]")
        if rater.count():
            rater.first.fill("qa-a3")
            rater.first.dispatch_event("change")
            self.page.wait_for_timeout(300)
        tp = self.btn("Đúng (TP)")
        tp.wait_for(timeout=T)
        body = self.page.locator("main, body").first.inner_text()
        for leak in ("gold", "silver", "semgrep", "sonar", "findsecbugs"):
            assert not re.search(rf"\b{leak}\b", body.split("Mục đang chấm")[-1][:1500], re.I), f"màn chấm mù lộ '{leak}'"
        tp.click()
        self.page.wait_for_timeout(600)

    def s_review_close(self):
        self.btn("Đóng phiên").first.click()
        self.page.get_by_text(re.compile("Precision kiểm tay")).first.wait_for(timeout=T)
        self.page.get_by_text(re.compile(r"TP \d")).first.wait_for(timeout=T)

    def s_settings_storage(self):
        self.goto("settings/storage")
        self.page.get_by_text("Dung lượng").first.wait_for(timeout=T)
        rows = self.page.locator("tr[data-key], table tbody tr")
        rows.first.wait_for(timeout=T)
        del_btn = self.btn("Xoá…")
        assert del_btn.is_visible(), "không có nút Xoá… (mục safety safe/slow)"
        del_btn.click()
        confirm = self.page.locator("button").filter(has_text=re.compile(r"^Xoá \d+ mục"))
        confirm.first.wait_for(timeout=T)
        assert self.page.get_by_text(re.compile("dry_run|sẽ xoá", re.I)).first.is_visible()
        self.btn("Huỷ", exact=True).click()
        self.page.wait_for_timeout(300)
        assert confirm.count() == 0, "preview dry-run không đóng sau Huỷ"

    # ------------------------------------------------------------ chạy
    def run(self):
        rid = lambda: self.run_id or "r-20261004-scratch"  # noqa: E731
        self.step("preflight", self.s_preflight)
        self.step("preflight_fix_all", self.s_fix_all)
        self.step("preflight_continue", self.s_continue, fallback=lambda: self.goto("home"))
        self.step("home", self.s_home, fallback=lambda: self.goto("home"))
        self.step("home_new_scan", self.s_new_scan, fallback=lambda: self.goto("wizard/1"))
        self.step("wizard1_repo", self.s_w1, fallback=lambda: self.goto("wizard/2"))
        self.step("wizard2_scope", self.s_w2, fallback=lambda: self.goto("wizard/3"))
        self.step("wizard3_tools", self.s_w3, fallback=lambda: self.goto("wizard/4"))
        self.step("wizard4_paths", self.s_w4, fallback=lambda: self.goto("wizard/5"))
        self.step("wizard5_copy_save", self.s_w5)
        self.step("wizard5_run", self.s_run, fallback=lambda: self.goto("run/r-20261005-A"))
        self.step("dashboard", self.s_dashboard)
        self.step("dashboard_view_results", self.s_view_results, fallback=lambda: self.goto(f"results/{rid()}/overview"))
        self.step("results_overview", self.s_overview)
        self.step("results_findings", self.s_findings_tab, fallback=lambda: self.goto(f"results/{rid()}/findings"))
        self.step("findings_click_row", self.s_click_row)
        self.step("findings_evidence", self.s_evidence, fallback=lambda: self.goto(f"review/{rid()}"))
        self.step("review_sample", self.s_review_sample)
        self.step("review_rate_one", self.s_review_rate)
        self.step("review_close", self.s_review_close)
        self.step("settings_storage_dryrun", self.s_settings_storage)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--real", action="store_true", help="backend thật (`--dev` không `--mock`)")
    ap.add_argument("--url", default="", help="dùng server đang chạy (SECJIT_GUI_URL) thay vì tự khởi động")
    ap.add_argument("--stop-on-fail", action="store_true")
    ap.add_argument("--slow", type=int, default=0, help="slow_mo ms (xem bằng mắt)")
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()

    from playwright.sync_api import sync_playwright

    proc = None
    if a.url:
        url = a.url
    else:
        proc, url = start_server(a.real)
    base, _, token = url.partition("?t=")
    t0 = time.time()
    flow = None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=not a.headed, slow_mo=a.slow or None)
            ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="vi-VN",
                                      permissions=["clipboard-read", "clipboard-write"])
            page = ctx.new_page()
            flow = Flow(page, base, token, out, a.stop_on_fail)
            try:
                flow.run()
            except Exception:  # noqa: BLE001 — stop-on-fail
                pass
            ctx.close()
            browser.close()
    finally:
        if proc:
            proc.kill()

    assert flow is not None
    fails = [r for r in flow.results if r["status"] == "FAIL"]
    report = {"mode": "real" if a.real else "mock", "url": base, "elapsed_s": round(time.time() - t0, 1),
              "steps": flow.results, "notes": flow.notes, "console_errors": flow.console,
              "run_id": flow.run_id, "cluster_key": flow.cluster_key, "ok": not fails and not flow.console}
    (out / "flow_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n==== KẾT QUẢ ====")
    for r in flow.results:
        print(f"  {r['status']:4} {r['step']:<26} {r['detail']}")
    if flow.notes:
        print("GHI CHÚ (hạn chế mock/fixture, không tính fail):")
        for n in flow.notes:
            print("  ", n)
    if flow.console:
        print("CONSOLE ERROR:")
        for c in flow.console:
            print("  ", c)
    print(f"Ảnh + flow_report.json: {out}  ({len(flow.results)} bước, {len(fails)} fail, {report['elapsed_s']}s)")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
