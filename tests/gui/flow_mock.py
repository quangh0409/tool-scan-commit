"""Luồng click END-TO-END (Playwright) trên GUI: mock (`--mock`) hoặc backend thật (`--real`).

  python tests/gui/flow_mock.py [--out DIR] [--real] [--url URL] [--skip-run] [--run-id ID]
                                [--seed-home DIR] [--stop-on-fail] [--slow MS] [--headed]

Các bước (23): Preflight → Sửa tất cả → Tiếp tục → Home → Scan mới → W1 (URL + Kiểm tra + nhánh) → W2 (count 30) → W3
→ W4 → W5 (copy CLI, Lưu profile) → Chạy → Dashboard → Xem kết quả → Tổng quan → Finding → bấm 1 dòng → Bằng chứng
→ Commit → Xuất → Kiểm tay (tạo mẫu, chấm 1, đóng) → Settings/Dung lượng (dry-run).
Mỗi bước: assert phần tử mong đợi, chụp `NN_<bước>.png`, gom console.error/pageerror. Bước fail → chụp `NN_<bước>_FAIL.png`,
ghi lý do, tiếp tục bằng điều hướng trực tiếp (trừ --stop-on-fail). Exit 1 nếu có bước FAIL hoặc console error.
"NOTE" = hạn chế mock/fixture/môi trường (không tính fail).

Chế độ thật (`--real`): KHÔNG bấm "Sửa tất cả" (fix thật có thể pull image), KHÔNG bấm Chạy/Chạy thử/clean/stop.
  --skip-run       : không bấm "Chạy" ở W5; Dashboard/Kết quả/Kiểm tay dùng run có sẵn `--run-id` (mặc định smoke1).
  --seed-home DIR  : tạo SECJIT_HOME tạm = DIR: copy tests/fixtures/smoke_v2.db + export_smoke vào, registry 1 run `done`
                     (run_id = --run-id) trỏ tới chúng; server tự khởi động với SECJIT_HOME đó (không đụng registry thật).
                     Dùng với --url thì server bên ngoài phải chạy cùng SECJIT_HOME.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
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
SMOKE_RUN = "smoke1"
T = 15000  # ms


def start_server(real: bool, env: dict) -> tuple[subprocess.Popen, str]:
    args = [sys.executable, "-m", "gui", "--no-browser", "--dev", "--allow-multi"] + ([] if real else ["--mock"])
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


def seed_home(home: Path, run_id: str) -> dict:
    """SECJIT_HOME tạm: smoke_v2.db + export_smoke + registry 1 run done. Trả bản ghi registry."""
    home.mkdir(parents=True, exist_ok=True)
    db = home / "smoke_v2.db"
    exp = home / "export_smoke"
    work = home / "work"
    shutil.copy(ROOT / "tests" / "fixtures" / "smoke_v2.db", db)
    if exp.exists():
        shutil.rmtree(exp)
    shutil.copytree(ROOT / "tests" / "fixtures" / "export_smoke", exp)
    work.mkdir(exist_ok=True)
    os.environ["SECJIT_HOME"] = str(home)
    for p in (str(ROOT), str(ROOT / "src")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import registry
    rec = registry.upsert({"run_id": run_id, "repo": REPO_URL, "branch": "master", "db": str(db), "export": str(exp),
                           "work": str(work), "profile": "", "started": "2026-10-05T07:39:28",
                           "finished": "2026-10-05T08:00:02", "status": "done", "pid": None,
                           "summary": {"commits": 3, "seeded_by": "flow_mock --seed-home"}})
    assert registry.path().parent == home
    return rec


class Flow:
    def __init__(self, page, base: str, token: str, out: Path, *, stop_on_fail: bool, real: bool, skip_run: bool,
                 run_id: str | None, seeded: dict | None):
        self.page, self.base, self.token, self.out, self.stop_on_fail = page, base, token, out, stop_on_fail
        self.real, self.skip_run, self.seeded = real, skip_run, seeded
        self.n = 0
        self.results: list[dict] = []
        self.console: list[str] = []
        self.notes: list[str] = []
        self.run_id: str | None = run_id if skip_run else None
        self.run_id_default = run_id or ("r-20261004-scratch" if not real else SMOKE_RUN)
        self.cluster_key: str | None = None
        self.review_empty = False
        self.export_dir: str | None = None
        page.on("console", lambda m: self.console.append(f"[{self.n:02d}] {m.type}: {m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda e: self.console.append(f"[{self.n:02d}] pageerror: {e}"))

    # ------------------------------------------------------------ tiện ích
    def rid(self) -> str:
        return self.run_id or self.run_id_default

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
        return self.page.locator("button, a.btn").filter(has_text=re.compile(rf"^\s*{re.escape(text)}" if exact else re.escape(text))).first

    def wiz_next(self):
        return self.page.locator(".wiz-foot button").last

    def dialog_ok(self):
        return self.page.locator(".dlg .btn.primary, .dlg .btn.danger").first

    def tab(self, label: str):
        return self.page.get_by_role("tab", name=label).or_(
            self.page.locator("button, a").filter(has_text=re.compile(rf"^\s*{re.escape(label)}\s*$"))).first

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
        items.first.wait_for(timeout=60000)
        assert items.count() >= 13, f"chỉ {items.count()} mục preflight (mong 13)"
        assert self.btn("Sửa tất cả").is_visible(), "thiếu nút Sửa tất cả"

    def s_fix_all(self):
        b = self.btn("Sửa tất cả")
        if b.is_disabled():
            self.note("Sửa tất cả bị khoá — không có mục fix_available")
            return
        if self.real:
            self.note("Chế độ --real: KHÔNG bấm Sửa tất cả (fix thật có thể pull image / đổi cấu hình máy)")
            return
        before = self.page.locator(".item[data-id] .btn:not([disabled])").count()
        b.click()
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
                return pf ? pf.items.filter(i => i.level === 'bad' || i.level === 'fix').map(i => i.id + ':' + i.level) : []; }""")
            self.note(f"Tiếp tục bị khoá vì mục chặn {bad} — điều hướng #/home trực tiếp")
            self.goto("home")
            return
        cont.click()
        dlg = self.page.locator(".dlg")
        try:
            dlg.wait_for(timeout=2000)
            self.note("Dialog 'Tiếp tục dù còn ⚠️' hiện (còn mục warn) → xác nhận")
            self.dialog_ok().click()
        except Exception:  # noqa: BLE001
            pass
        self.wait_hash("#/home")

    def s_home(self):
        assert self.hash().startswith("#/home"), f"hash={self.hash()}"
        assert self.btn("Scan mới").first.is_visible(), "thiếu nút Scan mới"
        assert self.page.get_by_text("Run gần đây").first.is_visible(), "thiếu thẻ Run gần đây"
        if self.seeded:
            # Home hiện owner/repo + nhãn trạng thái (không hiện run_id) — kiểm theo repo + nút Mở kết quả
            self.page.get_by_text("FudanSELab/train-ticket").first.wait_for(timeout=T)
            self.btn("Mở kết quả").wait_for(timeout=T)
            assert self.btn("Mở kết quả").is_visible(), f"run seed {self.seeded['run_id']} (done) không có nút Mở kết quả"

    def s_new_scan(self):
        self.btn("Scan mới").first.click()
        self.wait_hash("#/wizard/1")
        self.page.wait_for_selector("#w1-url", timeout=T)

    def s_w1(self):
        self.page.fill("#w1-url", REPO_URL)
        self.btn("Kiểm tra", exact=True).click()
        self.page.wait_for_selector("#w1-branch", timeout=120000)
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
        self.page.wait_for_timeout(1500)       # debounce estimate 450 ms + request
        body = self.page.locator("main").inner_text()
        if re.search(r"clone_pending|đang clone|chưa ước tính", body, re.I):
            self.note("W2: ước tính trả clone_pending (425) / chưa clone xong — GUI tự thử lại sau 5 s; không chặn Tiếp")
        assert not self.wiz_next().is_disabled(), "Tiếp bị khoá ở W2"
        self.wiz_next().click()
        self.wait_hash("#/wizard/3")
        prof = self.page.evaluate("() => JSON.parse(sessionStorage.getItem('secjit.wizard.profile') || '{}')")
        assert prof.get("scope", {}).get("mode") == "count" and int(prof["scope"].get("max") or 0) == 30, f"scope={prof.get('scope')}"

    def s_w3(self):
        assert self.page.locator("[id^='w3-c-']").first.is_visible(), "không thấy checkbox tool"
        assert not self.wiz_next().is_disabled(), "Tiếp bị khoá ở W3"
        self.wiz_next().click()
        self.wait_hash("#/wizard/4")

    def s_w4(self):
        self.page.wait_for_selector("#w4-out", timeout=T)
        self.page.wait_for_timeout(800)
        if self.wiz_next().is_disabled():
            self.page.fill("#w4-out", os.environ.get("SECJIT_HOME", "D:\\secjit") + "\\results")
            self.page.wait_for_timeout(1000)
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
        if self.skip_run or self.real:
            self.note(f"--skip-run/--real: KHÔNG bấm Chạy; dùng run có sẵn {self.rid()} → #/run/{self.rid()}")
            self.run_id = self.rid()
            self.goto(f"run/{self.run_id}")
            return
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
        self.page.get_by_text(re.compile("Tầng rẻ")).first.wait_for(timeout=T)
        head = self.page.locator("h1").first.inner_text()
        assert "/" in head or self.run_id in self.page.locator("main").inner_text(), f"header dashboard lạ: {head!r}"
        if self.skip_run or self.real:
            self.btn("Xem kết quả").wait_for(timeout=T)        # run done → phải có nút

    def s_view_results(self):
        b = self.btn("Xem kết quả")
        try:
            b.wait_for(timeout=4000)
        except Exception:  # noqa: BLE001
            self.note(f"Dashboard không có 'Xem kết quả' (run {self.run_id} chưa done/stopped) — điều hướng #/results/{self.run_id}/overview")
            self.goto(f"results/{self.run_id}/overview")
            return
        b.click()
        self.wait_hash("#/results/")

    def s_overview(self):
        self.page.get_by_text("Phễu commit").first.wait_for(timeout=T)
        assert self.page.get_by_text(re.compile("Nhãn \\(3 mức")).first.is_visible(), "thiếu thẻ Nhãn"
        assert self.page.get_by_text("Đồng thuận giữa tool").first.is_visible(), "thiếu thẻ κ"

    def s_findings_tab(self):
        self.tab("Finding").click()
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

    def s_commits(self):
        self.tab("Commit").click()
        self.wait_hash("#/results/")
        assert "/commits" in self.hash(), f"hash={self.hash()}"
        rows = self.page.locator("tbody tr")
        try:
            rows.first.wait_for(timeout=T)
        except Exception:  # noqa: BLE001
            assert self.page.get_by_text(re.compile("Chưa có commit")).first.is_visible(), "không có bảng commit lẫn empty state"
            self.note("Tab Commit: empty state (run không có selected_commits)")
            return
        assert rows.count() >= 1

    def s_export(self):
        self.tab("Xuất").click()
        self.wait_hash("#/results/")
        assert "/export" in self.hash(), f"hash={self.hash()}"
        self.page.locator("#ex-jsonl").wait_for(timeout=T)
        # nút chính "Xuất" trong thẻ Định dạng (KHÔNG phải tab "Xuất" — tab đứng trước trong DOM)
        export_btn = self.page.locator("button.primary, button.btn.primary").filter(has_text=re.compile(r"^\s*Xuất\s*$")).first
        export_btn.wait_for(timeout=T)
        with self.page.expect_response(lambda r: "/export" in r.url and r.request.method == "POST", timeout=180000) as resp:
            export_btn.click()
        res = resp.value
        assert res.status == 200, f"POST export HTTP {res.status}: {res.text()[:300]}"
        data = res.json()
        self.export_dir = data.get("export_dir")
        assert self.export_dir and data.get("files"), f"export trả thiếu export_dir/files: {data}"
        self.page.get_by_text(re.compile("Đã xuất")).first.wait_for(timeout=T)
        if self.real:
            home = os.environ.get("SECJIT_HOME", "")
            assert self.export_dir and home and self.export_dir.lower().startswith(home.lower()), \
                f"export thật ghi ra NGOÀI SECJIT_HOME tạm: {self.export_dir!r} (home={home!r})"
            assert Path(self.export_dir).exists() and (Path(self.export_dir) / "dataset.jsonl").exists(), self.export_dir
            if "export_smoke_" in self.export_dir:
                self.note(f"Export thật ra thư mục mới có hậu tố (đích đã có dữ liệu cũ): {self.export_dir}")

    def s_review_sample(self):
        self.goto(f"review/{self.rid()}")
        empty = self.page.get_by_text(re.compile("Chưa có cụm gold"))
        try:
            empty.first.wait_for(timeout=4000)
            self.review_empty = True
            self.note("Kiểm tay: DB không có cụm gold → empty state hợp lệ (không tạo mẫu được)")
            return
        except Exception:  # noqa: BLE001
            pass
        self.btn("Tạo mẫu", exact=True).wait_for(timeout=T)
        self.btn("Tạo mẫu", exact=True).click()
        self.btn("Bắt đầu chấm mù").wait_for(timeout=T)
        assert self.page.get_by_text(re.compile("n_pos")).first.is_visible()

    def s_review_rate(self):
        if self.review_empty:
            self.note("bỏ qua chấm (không có mẫu)")
            return
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
        if self.review_empty:
            self.note("bỏ qua đóng phiên (không có mẫu)")
            return
        self.btn("Đóng phiên").first.click()
        self.page.get_by_text(re.compile("Precision kiểm tay")).first.wait_for(timeout=T)
        self.page.get_by_text(re.compile(r"TP \d")).first.wait_for(timeout=T)

    def s_settings_storage(self):
        self.goto("settings/storage")
        self.page.get_by_text("Dung lượng").first.wait_for(timeout=T)
        try:
            self.page.locator("tbody tr").first.wait_for(timeout=T)
        except Exception:  # noqa: BLE001
            assert self.page.get_by_text(re.compile("Chưa có gì để dọn")).first.is_visible(), "không có bảng lẫn empty state"
            self.note("Dung lượng: empty state (chưa có gì để dọn)")
            return
        del_btn = self.btn("Xoá…")
        if not del_btn.is_visible():
            self.note("Dung lượng: không mục nào xoá được (toàn forbidden) — bỏ qua dry-run")
            return
        del_btn.click()
        confirm = self.page.locator("button").filter(has_text=re.compile(r"^Xoá \d+ mục"))
        confirm.first.wait_for(timeout=T)
        self.btn("Huỷ", exact=True).click()
        self.page.wait_for_timeout(300)
        assert confirm.count() == 0, "preview dry-run không đóng sau Huỷ"

    # ------------------------------------------------------------ chạy
    def run(self):
        rid = self.rid
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
        self.step("wizard5_run", self.s_run, fallback=lambda: self.goto(f"run/{rid()}"))
        self.step("dashboard", self.s_dashboard)
        self.step("dashboard_view_results", self.s_view_results, fallback=lambda: self.goto(f"results/{rid()}/overview"))
        self.step("results_overview", self.s_overview)
        self.step("results_findings", self.s_findings_tab, fallback=lambda: self.goto(f"results/{rid()}/findings"))
        self.step("findings_click_row", self.s_click_row)
        self.step("findings_evidence", self.s_evidence)
        self.step("results_commits", self.s_commits, fallback=lambda: self.goto(f"results/{rid()}/commits"))
        self.step("results_export", self.s_export, fallback=lambda: self.goto(f"results/{rid()}/export"))
        self.step("review_sample", self.s_review_sample)
        self.step("review_rate_one", self.s_review_rate)
        self.step("review_close", self.s_review_close)
        self.step("settings_storage_dryrun", self.s_settings_storage)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=None, help="thư mục ảnh (mặc định shots/flow-mock | shots/flow-real)")
    ap.add_argument("--real", action="store_true", help="backend thật (`--dev` không `--mock`)")
    ap.add_argument("--url", default="", help="dùng server đang chạy (SECJIT_GUI_URL) thay vì tự khởi động")
    ap.add_argument("--skip-run", action="store_true", help="không bấm Chạy ở W5; dùng run có sẵn --run-id")
    ap.add_argument("--run-id", default=None, help=f"run có sẵn cho Dashboard/Kết quả (mặc định {SMOKE_RUN} khi --real)")
    ap.add_argument("--seed-home", default=None, metavar="DIR", help="SECJIT_HOME tạm với smoke_v2.db + export_smoke + registry 1 run done")
    ap.add_argument("--stop-on-fail", action="store_true")
    ap.add_argument("--slow", type=int, default=0, help="slow_mo ms (xem bằng mắt)")
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args(argv)
    out = Path(a.out) if a.out else (DEFAULT_OUT.parent / ("flow-real" if a.real else "flow-mock"))
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()

    seeded = None
    run_id = a.run_id or (SMOKE_RUN if a.real else None)
    if a.seed_home:
        seeded = seed_home(Path(a.seed_home).resolve(), run_id or SMOKE_RUN)
        run_id = run_id or SMOKE_RUN
        print(f"SECJIT_HOME tạm: {a.seed_home} (run {run_id} done → {seeded['db']})")

    from playwright.sync_api import sync_playwright

    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    proc = None
    if a.url:
        url = a.url
    else:
        proc, url = start_server(a.real, env)
    base, _, token = url.partition("?t=")
    t0 = time.time()
    flow = None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=not a.headed, slow_mo=a.slow or None)
            ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="vi-VN",
                                      permissions=["clipboard-read", "clipboard-write"])
            page = ctx.new_page()
            flow = Flow(page, base, token, out, stop_on_fail=a.stop_on_fail, real=a.real, skip_run=a.skip_run,
                        run_id=run_id, seeded=seeded)
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
              "skip_run": a.skip_run, "seed_home": a.seed_home, "steps": flow.results, "notes": flow.notes,
              "console_errors": flow.console, "run_id": flow.run_id, "cluster_key": flow.cluster_key,
              "export_dir": flow.export_dir, "ok": not fails and not flow.console}
    (out / "flow_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n==== KẾT QUẢ ====")
    for r in flow.results:
        print(f"  {r['status']:4} {r['step']:<26} {r['detail']}")
    if flow.notes:
        print("GHI CHÚ (hạn chế mock/fixture/môi trường, không tính fail):")
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
