# TASKS — Kế hoạch 1 NGÀY: desktop app `secjit-scan.exe` đủ 10 màn

> Chốt 2026-10-04. **Claude code toàn bộ, user cho full quyền, máy bật liên tục, hạn 1 ngày, tối đa 5 agent chạy song song.** Ước tính gốc 85 giờ Claude (bản plan trước) được nén bằng 5 agent song song theo 2 đợt; Claude trưởng (phiên này) giữ vai tích hợp, chạy Docker, và nghiệm thu. Quyết định phương pháp luận: `TOOL_IDEA_CONTEXT.md` §13. Review gốc: `REVIEW.md`.

---

## 0. Thay đổi so với plan trước (theo trả lời user)

| Câu hỏi | Trả lời user | Hệ quả |
|---|---|---|
| 5 DB cũ | **Đã mất, KHÔNG sinh lại** | Bỏ P0.2 (đối soát). Số liệu 5 repo trong `SESSION_CONTEXT.md` giữ làm lịch sử. **Dữ liệu để test tool** = 3 run sinh hôm nay: (a) DB scratch train-ticket 3 commit (đã có, dùng làm fixture pytest + mock), (b) **Run A** train-ticket `--max 30` qua CLI, (c) **Run B** cùng profile từ exe. Ba run này đủ để test Home (danh sách, trạng thái dở/xong), dropdown Results, batch queue, so sánh A/B, `stats`, `sensitivity`, tạo mẫu kiểm tay. Không chạy thêm repo nào khác trong ngày. |
| Rater 2 | Hỏi lại | Hôm nay làm **tính năng** chấm 2 rater + fallback intra-rater. Việc chấm 300 mẫu (5–8 giờ/người) **không nằm trong 1 ngày**. |
| Máy sạch | **Chạy local trước** | Bỏ P6.2 máy sạch; test exe trên chính laptop user. Thêm `--preflight --json` để sau này chạy trên máy khác. |
| Thời hạn & tài nguyên | **1 ngày, ≤ 5 agent, full quyền** | Kế hoạch dưới. Chỉ **Claude trưởng** được chạy Docker (tránh 2 run giẫm nhau và treo máy). Agent làm trong **worktree riêng**, trưởng merge. |

---

## 1. Định nghĩa "XONG" cuối ngày

1. **10 màn chạy thật** trên laptop qua `secjit-scan.exe` (PyInstaller) **và** `python -m gui` (dev-mode): Preflight → Home → Wizard 1–5 → Dashboard → Results (Tổng quan / Finding / Commit / Kiểm tay / Xuất) → Settings. Mỗi màn có trạng thái loading / rỗng / lỗi theo `REVIEW.md` §III.A.
2. **Nghiệm thu tái lập**: Run A = CLI `pipeline --profile` train-ticket `--max 30` (chạy sớm, cache lạnh); Run B = **từ exe** cùng profile vào DB mới (cache ấm). So `dataset.jsonl` A/B theo `cluster_key`: khớp, hoặc lệch chỉ ở commit nằm trong `tool_timeout`/`infra_error` của manifest. Kết quả → `RESULTS.md`.
3. **Backend đủ**: 8 lỗi dữ liệu đã sửa; `run_meta` v2 + `run_manifest.json` + `SHA256SUMS`; `--since/--until/--from-sha/--to-sha`, `--tools/--expensive-tools`, `--profile`, `estimate`, `stats`, `sensitivity`, `stop`, `reset-claims`, `clean --dry-run`, `review sample/close`; runner nền tách rời + `progress.jsonl`; preflight 13 mục + 5 auto-fix.
4. **Kiểm tay**: tạo được mẫu phân tầng có seed (200 + 100), màn chấm mù, đóng phiên ra precision + Wilson CI + Cohen κ (khi có 2 file rater). Chưa có số precision thật (user chấm sau).
5. **Chất lượng**: `ruff` sạch; pytest unit + contract xanh; CI yml có; `README`/`GUIDE`/`METHODOLOGY`/`SESSION_CONTEXT` cập nhật; mọi thứ commit trên `dev`.

6. **Dữ liệu test đủ dùng**: registry có 3 run (scratch 3 commit · Run A · Run B); `stats`, `sensitivity`, `review sample` chạy được trên DB Run A; mọi màn có dữ liệu thật để xem, không còn mock.

**Không nằm trong ngày:** chấm tay thật; sinh lại 5 dataset cũ (không cần); máy sạch; chế độ VM qua SSH; ký code thương mại; CodeQL image (preflight có nút build nhưng không chạy hôm nay).

---

## 2. Lịch 1 ngày (giờ tính từ lúc bắt đầu, T0)

```
T0 ─ T+1   TRƯỞNG: đóng băng hợp đồng giao diện (CONTRACTS.md) + khung thư mục + fixture mock
T+1 ─ T+6  ĐỢT 1 · 5 agent song song (worktree riêng, KHÔNG chạy Docker)
T+6 ─ T+8  TRƯỞNG: merge 5 worktree, ruff/compile/pytest, smoke --max 5 (Docker ~40')
T+8        TRƯỞNG: phóng RUN A (CLI --profile, --max 30, cache lạnh, ~3–4 h nền)
T+8 ─ T+13 ĐỢT 2 · 5 agent song song (nối GUI↔backend thật, review GOLD, test+CI+exe, hoàn thiện, QA)
T+13 ─ T+15 TRƯỞNG: merge, build exe, chạy 10 màn trên dev-mode + exe, sửa lỗi chặn
T+15 ─ T+18 TRƯỞNG: RUN B từ exe (profile của A, cache ấm ~1,5–2 h nền) · song song: QA vòng 2 (1 agent)
T+18 ─ T+20 TRƯỞNG: so A/B, RESULTS.md, stats/sensitivity trên DB --max 30, docs, commit cuối
T+20 ─ T+24 Dự phòng (trượt ±30 %) · kịch bản demo 10 phút
```

**Điểm kiểm tra cứng** (nếu trượt → cắt theo §6): T+8 (đợt 1 merge xong), T+15 (exe chạy 10 màn), T+20 (RESULTS).

---

## 3. T0–T+1 · Hợp đồng giao diện (trưởng viết, agent tuân theo)

File `CONTRACTS.md` gồm:

- **`profile.json`**: `{schema:1, repo, branch, scope:{mode: time|count|sha|all, since, until, max, from_sha, to_sha}, include_clean, cheap_tools[], expensive_tools[], codeql, workers:{scan, expensive}, paths:{db, export, work}, sonar_port, experiment:{enabled, reason}|null, params_v1:{line_window:3, gold_min_expensive:2, gold_allow_1exp_1cheap:1, silver_min_cheap:2, noise_cwe:["CWE-117"]}}`.
- **`progress.jsonl`**: mỗi dòng `{ts, run_id, phase: scan|select|analyze|relabel|kappa|export, event: start|item|done|error, done, total, worker, sha, status, msg}`.
- **`runs.json`** (registry, `%LOCALAPPDATA%\secjit\runs.json`): `{runs:[{run_id, repo, branch, db, export, work, profile, started, finished, status: running|stopped|done|failed|interrupted, pid, summary:{gold, silver, candidate, verified_clean, cheap_clean, kappa}}]}`.
- **`cluster_key`** = sha256(`repo|commit|file_path|cwe_group|s_line//LINE_WINDOW`) — khoá cho `gold_review` và so A/B.
- **`run_meta` v2**: bảng `run_meta(id, tier: scan|analyze, started_at, finished_at, repo, branch, scope_json, config_snapshot_json, tools_json[{name, image, version, digest}], orchestrator_git_sha, app_version, experiment)`; bảng `kappa(run_id, scope, group, value, n)`.
- **API GUI** (`gui/server.py`, localhost, header `X-Token`): `GET /api/preflight` · `POST /api/preflight/fix {item}` · `POST /api/repo/check {url}` · `POST /api/estimate {profile}` · `POST /api/run/start {profile}` · `POST /api/run/{id}/stop {force}` · `POST /api/run/{id}/resume` · `GET /api/runs` · `GET /api/run/{id}/progress` (SSE) · `GET /api/results/{id}/overview|findings|commits|export` · `GET /api/results/{id}/finding/{cluster_key}` · `POST /api/review/{id}/sample|verdict|close` · `GET/POST /api/settings/*` · `GET /api/storage` · `POST /api/clean {items, dry_run}`.
- **Fixture mock**: `gui/fixtures/*.json` cho mọi endpoint (số liệu lấy từ run thật hôm 2026-10-04 + sửa sai nhãn mock theo REVIEW §I.4) để agent GUI làm độc lập backend.
- **Khung thư mục**: `src/orchestrator/` (A1, A2) · `runner/`, `registry/`, `preflight/` (A3) · `gui/server.py`, `gui/web/{index.html, app.css, app.js, screens/*.js}` (A4, A5) · `tests/` (B3).
- **Quy tắc merge**: mỗi agent 1 worktree `feat/<tên>`; chỉ sửa file trong vùng được giao; file chung (`cli.py`, `config.py`) chỉ A2 sửa, A1 gửi yêu cầu qua báo cáo; không chạy Docker; commit nhỏ, tiếng Việt.

---

## 4. ĐỢT 1 (T+1 → T+6) — 5 agent

| Agent | Vùng file | Việc | Tiêu chí nghiệm thu |
|---|---|---|---|
| **A1 data-core** | `storage/sqlite_store.py`, `export_dataset.py`, `tools_expensive/build.py`, `expensive_runner.py`, `tools_expensive/sonar.py`, `repo_pool.py`, `tools/base.py`, `scripts/merge_export.py` | 8 lỗi dữ liệu (D1 `skipped` khi 0 module + `n_expensive_ok`, `negative_level` ≥2 tool ok; D2 `infra_error` rc 125/127 + dừng sau 3 lỗi; D3 Sonar container/network theo `run_id` + lock DB; D4 fetch + tên clone `owner__repo` + kiểm origin; D5 export thư mục mới; D6 disk-full dừng; D7 `_rmtree`; D8 WAL); `--label orch.run=<id>` mọi `docker run`; `run_meta` v2 + bảng `kappa` + `user_version` migrate; `export` gộp merge + `run_manifest.json` + `SHA256SUMS` + trường `evidence`; gọi `progress.emit()` trong analyze | pytest cho negative_level/run_meta/manifest; `compileall`; không Docker |
| **A2 cli-scope** | `cli.py`, `config.py`, `enumerate_commits.py`, `select_commits.py`, mới: `progress.py`, `profile.py`, `estimate.py`, `stats.py`, `sensitivity.py`, `control.py` (stop/reset-claims) | `--since/--until/--from-sha/--to-sha` (ép `--max 0`), `--tools/--expensive-tools` cho `pipeline`, `--profile` mọi subcommand + validate schema, `estimate` (đọc `speed.json`), `stats` (JSON/CSV/LaTeX, κ nhóm + pairwise, khối "giới hạn"), `sensitivity` (copy DB → relabel lưới), `stop` (stop-file + CTRL_BREAK/SIGTERM) + `reset-claims --run`, `clean` tách mục + `--dry-run`, experiment mode guard cho `ORCH_LINE_WINDOW`, bỏ VOTE_THRESHOLD khỏi run_meta hiển thị, `progress.emit()` trong scan | pytest contract: profile → argparse parse; env → config; `estimate` trên fixture; không Docker |
| **A3 runner-registry-preflight** | mới: `runner/`, `registry/`, `preflight/`, `speed.py` | Tiến trình tách rời Windows (`CREATE_NEW_PROCESS_GROUP\|DETACHED_PROCESS`) + Linux, pid/stop/log-file, heartbeat, attach, phát hiện pid chết + DB `building` → gợi ý reset; `runs.json` + mutex single-instance + lock theo DB; 13 kiểm tra preflight (RAM Docker `MemTotal`, image build vs pull, `vm.max_map_count` WSL2, `:latest` chưa pin, file-sharing, proxy…) + 5 auto-fix (bật Docker + poll 90 s, port trống, pull/build có %, `core.longpaths`, hạ `CODEQL_RAM_MB`) + `preflight --json`; `speed.json` đo/đọc | pytest với docker giả (mock subprocess); chạy `preflight --json` thật trên laptop (chỉ đọc, không pull) |
| **A4 gui-shell + màn 0–5** | `gui/server.py`, `gui/main.py`, `gui/web/*`, màn Preflight, Home, Wizard 1–5 | Server stdlib http + SSE + token, `--dev` mở trình duyệt, `--mock` dùng fixture; design system (token màu/kiểu wireframe, component btn/card/table/stepper/toast/dialog/empty/error/skeleton); 6 màn với **đủ trạng thái** (REVIEW §III.A), validate đầu vào (URL/ngày/N/SHA/đường dẫn/luồng), "Nâng cao" chỉ đọc + nút Chế độ thí nghiệm, lệnh CLI PowerShell + bash sinh từ profile | mở `--dev --mock`, đi hết 6 màn bằng Playwright (nếu có) hoặc kiểm HTML + JS không lỗi console |
| **A5 màn 6–10 + Kiểm tay** | `gui/web/screens/{dashboard,results_*,settings,review}.js` + CSS riêng | Dashboard (3 thanh, worker, ETA, log lọc, ẩn nhãn tạm, Dừng an toàn/cưỡng bức, banner Docker tắt/đĩa đầy/infra_error, hộp đóng cửa sổ); Results 5 tab (Tổng quan với phễu/κ/giới hạn, Finding lọc + phân trang, Bằng chứng + raw + provenance + "gold · đồng thuận máy", Commit, Xuất); Settings 4 tab (Docker, Dung lượng + xem trước xoá, Profile, Ngôn ngữ); màn Kiểm tay mù + adjudication | như A4, trên fixture |

**Trưởng trong đợt 1:** trả lời câu hỏi agent, viết `tests/conftest.py` + fixture DB nhỏ (từ scratch DB hôm 2026-10-04), chuẩn bị profile Run A.

---

## 5. ĐỢT 2 (T+8 → T+13) — 5 agent

| Agent | Việc | Nghiệm thu |
|---|---|---|
| **B1 wire** | Nối `gui/server.py` vào backend thật (runner, registry, preflight, SQLite ro, `stats`, `estimate`, `clean --dry-run`); bỏ mock từng endpoint; test tích hợp bằng DB scratch + RUN A đang chạy (chỉ đọc) | Mọi endpoint trả dữ liệu thật; Dashboard hiện tiến độ RUN A đang chạy |
| **B2 review** | Bảng `gold_review`, `review sample --seed --n-pos 200 --n-neg 100` phân tầng, map lại sau relabel, `review close` → precision + Wilson CI + Cohen κ + bất đồng; nối màn Kiểm tay; `build_gold_set.py` đọc bảng + bỏ hardcode `/home/scanner`; `relabel_gold_w7.py` thành `sensitivity` preset | pytest trên fixture; tạo mẫu từ DB scratch |
| **B3 test-ci-exe** | pytest unit (posix path, URL normalize, negative_level, reset-claims, run_meta round-trip, `_rmtree` read-only, GBK, cluster_key) + contract; `.github/workflows/ci.yml` (windows + ubuntu); `secjit.spec` PyInstaller + build exe local + `--version`/`--preflight --json`/`--profile` headless | exe chạy được trên laptop, pytest xanh |
| **B4 polish-docs** | Batch queue (tuần tự, 1 Sonar), toast Windows, gói chẩn đoán zip, i18n VI/EN đủ chuỗi, `ORCH_M2_VOLUME`; `README` (exe + CLI mới), `GUIDE` (env mới), `METHODOLOGY.md` (QĐ 3–5 + giao thức kiểm tay), `EXECUTION_FLOW` cập nhật | docs khớp code; i18n không thiếu khoá |
| **B5 QA** | Đi checklist REVIEW §III.A–D trên `--dev` (backend thật): từng màn × trạng thái, 21 test case §III.B, edge case §III.C; báo lỗi theo mẫu (màn, bước, mong đợi, thực tế, file:dòng nghi ngờ) → trưởng phân cho B1/B4 sửa | Báo cáo QA vòng 1; vòng 2 ở T+15 |

---

## 6. Nếu trượt — thứ tự cắt (giữ "XONG" cốt lõi)

1. Bỏ batch queue, toast, tray, i18n EN (giữ VI).
2. Bỏ biểu đồ mật độ kéo-chọn (giữ 4 chế độ phạm vi).
3. Bỏ `sensitivity` UI (giữ CLI).
4. Bỏ exe PyInstaller → giao `run_gui.bat` chạy `python -m gui` (vẫn đủ 10 màn). **Chỉ cắt nếu T+15 exe chưa chạy.**
5. **Không cắt:** 8 lỗi dữ liệu, run_meta v2 + manifest, runner nền + Dừng an toàn, 10 màn, Run A/B, Kiểm tay (tính năng).

---

## 7. Rủi ro riêng của kế hoạch 1 ngày

- **Merge 5 worktree**: giảm bằng vùng file tách bạch (§4) và hợp đồng §3; trưởng dành 2 giờ merge có chủ đích.
- **Docker trên laptop**: chỉ trưởng chạy; tuần tự smoke → Run A → Run B; `ORCH_EXPENSIVE_WORKERS=2`; nếu Docker Desktop sập (đã gặp) → `infra_error` dừng, resume bằng `reset-claims`. Máy đã treo một lần khi build + Sonar + nhiều việc khác: trong lúc Run A/B, trưởng không chạy build khác.
- **Claude không nhìn được GUI**: dev-mode mở trình duyệt + Playwright (kiểm `python -c "import playwright"`; nếu không có, `pip install playwright` + `playwright install chromium`, ~200 MB); fallback kiểm DOM/console qua Chrome DevTools Protocol; cuối ngày user duyệt 1 lượt.
- **pywebview/WebView2 trên laptop**: kiểm `pip install pywebview` + WebView2 runtime ở T0; nếu lỗi → exe mở trình duyệt mặc định thay cửa sổ native (vẫn đủ 10 màn).
- **Thời gian máy**: Run A 3–4 h + Run B 1,5–2 h + smoke 0,7 h ≈ 6 h nền, nằm trong lịch; nếu Run A > 5 h → giảm Run B còn `--max 15` cùng profile (ghi rõ trong RESULTS).

---

## 8. Việc trưởng làm ngay (T0)

1. Kiểm môi trường: Docker daemon, `pip install pywebview pyinstaller pytest playwright`, WebView2.
2. Viết `CONTRACTS.md` + khung thư mục + `gui/fixtures/*.json` + `tests/fixtures/scratch.sqlite` (copy DB `tt_test.sqlite` hôm nay).
3. Tạo 5 worktree `feat/a1-data-core` … `feat/a5-gui-screens-6-10` từ `dev`.
4. Phóng 5 agent đợt 1 với prompt trỏ `CONTRACTS.md`, `REVIEW.md`, vùng file, tiêu chí nghiệm thu.
5. Cập nhật `SESSION_CONTEXT.md` mỗi điểm kiểm tra T+8 / T+15 / T+20.
