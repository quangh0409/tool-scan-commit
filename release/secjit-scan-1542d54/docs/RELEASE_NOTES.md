# RELEASE NOTES — `secjit-scan` bản desktop 2026-10-05

> Phiên bản: `git describe --tags --always --dirty` lúc build (ghi trong `RELEASE_NOTES.txt` cạnh exe và `run_meta.app_version`).
> So với bản chạy trên VM GCP 2026-07 (5 repo full-history). Hợp đồng giao diện: `CONTRACTS.md`; phương pháp luận: `METHODOLOGY.md`.

## 1. Tóm tắt theo khu vực

### Dữ liệu & nhãn (A1)
- **8 lỗi dữ liệu đã sửa** (REVIEW §I.3): `skipped` (commit 0 module Java) tách khỏi `ok`; `verified-clean` **chỉ khi
  `n_expensive_ok ≥ 2`**; `infra_error` (Docker tắt/đĩa đầy) không còn biến thành `build_failed`, commit về `pending`,
  3 lần liên tiếp → run tự dừng; Sonar container/network theo `run_id` + lock DB `<db>.lock`; fetch clone + tên thư mục
  `owner__repo` + kiểm origin; export **luôn sang thư mục mới**; phát hiện đĩa đầy; `rmtree_force` cho file read-only
  Windows; WAL.
- **`run_meta` v2** (`user_version=2`): `run_id`, `tier` (scan/analyze), `scope_json`, `config_snapshot_json` (env hiệu lực
  + argv + profile), `tools_json` (image digest), `orchestrator_git_sha`, `app_version`, `experiment`, `reason`;
  bảng `kappa` (total/category/cwe_group/**pair**), `gold_review`, `gold_sample`, `scan_tool_errors`.
- **Export**: `run_manifest.json` (profile, run_meta 2 tier, kappa, counts, `build_failed[] infra_error[] tool_timeout[]
  tool_error[] cheap_infra_error[] skipped[]`, digest, OS/Docker/Python), `dataset.jsonl` có `cluster_key` +
  `evidence{consensus, validation}`, `commits.jsonl` có `n_expensive_ok`/`negative_level`, `SHA256SUMS`;
  không cần `scripts/merge_export.py` nữa.
- **Kiểm tay GOLD** (`review`): mẫu phân tầng CWE-group × tier, seed cố định, chấm mù, 2 rater, precision + Wilson CI,
  Cohen κ, adjudication; `evidence.validation ∈ unreviewed|TP|FP|unclear`.

### CLI mới / đổi (A2)
- Phạm vi commit: `--since/--until` (committer-date), `--from-sha/--to-sha` (`A..B`, verify `rev-parse`); có scope mà bỏ
  `--max` → ép `0`. Chọn tool: `--tools` (rẻ) / `--expensive-tools` (đắt), cảnh báo "đổi mẫu số" chỉ khi bỏ tool
  **hiệu lực** (findsecbugs/sonar; codeql chỉ khi `--codeql 1`).
- `--profile F` ở mọi subcommand (áp env trước config, dựng lại argv, bỏ qua arg khác); `config.reload()`.
- Lệnh mới: `estimate`, `stats` (json/csv/latex, `limits` tự sinh, `cross_tool.anchor_gap`), `sensitivity` (lưới trên
  bản sao DB), `compare` (A/B theo `cluster_key`, bảng md dán RESULTS), `verify` (nghiệm thu CONTRACTS), `stop` /
  `stop-cleanup` / `reset-claims`, `clean --items …` (`--dry-run`, `m2volume`), `rescan --commit`, `review …`,
  `batch --queue`, `diagnostics --run --out Z.zip` (che token/PAT).
- Exit code chuẩn: `0` ok · `1` tham số · `2` runtime · `3` dừng theo stop-file / infra_error liên tiếp. `--json` mọi lệnh.
- Env mới: `ORCH_CHEAP_TOOLS, ORCH_RUN_ID, ORCH_PROGRESS_FILE, ORCH_STOP_FILE, ORCH_EXPERIMENT(_REASON),
  ORCH_LINE_WINDOW` (chỉ khi experiment), `ORCH_M2_VOLUME, ORCH_INFRA_STOP_AFTER, ORCH_DOCKER_BIN, ORCH_CLEAN_PER_BUGGY,
  SECJIT_APP_VERSION` (bảng đủ: GUIDE §3).

### Runner / registry / preflight (A3)
- Run chạy **tiến trình nền tách rời** (`DETACHED_PROCESS` / `start_new_session`), `pid`, `run.log`, `progress.jsonl`,
  stop-file hợp tác; `runs.json` registry (`%LOCALAPPDATA%\secjit`, `SECJIT_HOME`), `speed.json` đo tốc độ thật;
  `status=interrupted` khi pid chết mà DB còn `building/analyzing`.
- Preflight 13 mục + 6 auto-fix (Docker daemon, RAM Docker `MemTotal`, port Sonar dò 9000→9100…, image pull/build,
  `vm.max_map_count`, hạ `CODEQL_RAM_MB`, `core.longpaths`…); `--preflight --json`.
- `runner/batch_runner`: hàng đợi profile tuần tự, mỗi profile 1 run nền + registry + lock DB.

### GUI 10 màn + kiểm tay (A4/A5)
- pywebview + web UI tĩnh (không framework/CDN), i18n vi/en, server localhost + token, SSE progress.
- Preflight → Home → Wizard 1–5 (profile, ước tính, lệnh CLI tương đương PowerShell/bash) → Dashboard (Dừng an toàn /
  cưỡng bức, banner infra_error/Docker/đĩa) → Results 5 tab (Tổng quan phễu/nhãn/κ/giới hạn, Finding, Bằng chứng raw +
  provenance, Commit, Xuất) → Kiểm tay mù → Settings 4 tab (Dung lượng + `clean` dry-run). Nhãn hiện "gold · đồng thuận
  máy" cho tới khi kiểm tay.

### Đóng gói (A3)
- `./build_exe.ps1 -Clean` → `dist/secjit-scan.exe` (console: `--version`, `--preflight --json`, `--profile F`, `--cli …`,
  `-m <module>`, `--dev`) (nhấp đúp = GUI + console log server; đã bỏ `secjit-scan-gui.exe` vì bản noconsole làm bật nhiều cửa sổ cmd); `scripts/release.ps1` gom exe + SHA256SUMS
  + README + docs (kể cả file này). Fallback trình duyệt nếu WebView2/pywebview lỗi. `pick_dir` có nhập tay (không tkinter).

### Docs
- `METHODOLOGY.md` (v1 đăng ký trước, thuật ngữ nhãn/evidence, chính sách đổi tham số, giao thức kiểm tay, trạng thái §1,
  tiêu chí tái lập, threats, **§8 giới hạn gộp cụm theo dòng**), `HUONG_DAN_GUI.md`, `CODE_MAP.md`, `GUIDE.md` §2/§3 đầy đủ
  lệnh + env, `README.md` (GUI/exe, profile, nghiệm thu tái lập), `EXECUTION_FLOW.md` (runner → progress → GUI),
  `scripts/demo_10min.md`.

## 2. Thay đổi HÀNH VI so với bản VM 2026-07 (đọc trước khi chạy script cũ)

| Trước (VM 2026-07) | Nay | Lý do |
|---|---|---|
| `clean <repo> --export/--cache/--db/--all` xoá theo env mặc định | `clean <repo> --items clone,pool,m2,m2volume,export:<dir>,db:<path> [--dry-run]`; **không còn `--all`**; export/db bắt buộc đường dẫn; từ chối khi DB/pool đang dùng | từng xoá nhầm `data/export` (CLAUDE.md gotcha) |
| `export --out D` ghi đè vào D | export **luôn sang thư mục mới** (`D`, `D_2`, `D_3`…) nếu đích không rỗng; `res['out']` cho biết đích thật | run A/B không ghi đè nhau; manifest + SHA256SUMS bất biến |
| `verified-clean` = qua tầng đắt có ≥1 tool ok (kể cả commit 0 module Java) | **≥2 tool đắt `status=ok`** trên commit, `skipped` không tính | REVIEW §I.3: verified-clean giả |
| `select` (không `--include-clean`) `replace_selected` → mất `done` | `select` **idempotent**: thêm mới `pending`, giữ status/n_expensive_ok, chỉ bỏ hàng ngoài universe; `ORCH_CLEAN_PER_BUGGY` cap clean | resume không làm lại tầng đắt |
| semgrep quét thẳng clone | semgrep copy file đổi vào **thư mục tạm giữ cấu trúc** + `.semgrepignore` rỗng, `scan /src` | không bỏ sót `tests/`, không bị `.semgrepignore` của repo |
| bỏ tool nào cũng cảnh báo / không cảnh báo | cảnh báo "đổi mẫu số eligible/κ" **chỉ khi thiếu tool hiệu lực** (findsecbugs/sonar/5 tool rẻ; codeql chỉ khi `--codeql 1`) | `--codeql 0` là chuẩn, không phải "bỏ tool" |
| `run_meta` v1 (`vote_threshold`, `max_commits`) | v2 (`run_id`, `tier`, `scope_json`, `config_snapshot_json`, `tools_json`…); `VOTE_THRESHOLD` không ghi/hiển thị | tham số chết; tái lập |
| `--max` mặc định 50 kể cả khi có phạm vi khác | có `--since/--until/--from-sha/--to-sha` mà bỏ trống `--max` → ép `0` (cảnh báo) | tránh cắt nhầm 50 commit |
| `analyze --tools a,b` | `--expensive-tools` (alias `--tools` còn, cảnh báo, sẽ bỏ) | tránh nhầm với `--tools` rẻ của scan/pipeline |
| clone `work/<repo>`, không fetch | `work/<owner__repo>` (giữ tên cũ nếu origin khớp), `git fetch --all --prune` mỗi lần | trùng tên repo khác org; nhánh mới |
| tool lỗi im lặng (coi như "không báo") | `scan_tool_errors` / `expensive_runs.status`; **không** tính là rater "không báo" trong κ; `rescan` chạy lại đúng tool lỗi | κ/mẫu số đúng |
| `kappa` chỉ in | lưu bảng `kappa` theo `run_id` (tổng/category/nhóm/**cặp tool**) | GUI/stats đọc |
| `datetime('now')` UTC lẫn local | `run_meta.started_at/finished_at` ISO local có `T` (verify kiểm) | so với progress.ts |

Script cũ cần đổi: `clean … --export` → `clean … --items export:<dir>`; đọc đích export từ dòng `Export … -> <out>`;
`analyze --tools` → `--expensive-tools`; không `scripts/merge_export.py` sau `export`.

## 3. Lỗi đã biết / giới hạn

- **FSB–Sonar lệch điểm neo → gold thấp trên app Spring**: FindSecBugs báo tại khai báo method/field, Sonar tại statement;
  trên smoke train-ticket cặp cùng (file, nhóm CWE) gần nhất lệch 18–43 dòng (`stats.cross_tool.anchor_gap` đo thật) →
  W∈{3,5,7} không gộp được, gold = 0 ở 12 cấu hình sensitivity. Không nới W; method-level clustering chỉ qua experiment +
  kiểm tay (METHODOLOGY §8).
- **pywebview**: đã test server/API/Playwright trên trình duyệt và exe smoke; **cửa sổ WebView2 thật chưa test tự động**
  (fallback trình duyệt khi lỗi).
- **Linux**: chưa chạy CI trên Linux (CI hiện Windows); đường dẫn/`os.killpg`/`sg docker` đã viết nhưng chưa xác minh lại
  trong bản này; VM GCP vẫn dùng được CLI.
- **batch 2 đường**: `batch` ủy quyền `runner.batch_runner` (nền + registry) khi có `runner/`; môi trường chỉ có `src/`
  rơi về subprocess tuần tự (`--local`) — không ghi registry.
- `ORCH_M2_VOLUME=1` (named volume) chưa test với build chạy `-u <uid>` trên Linux (volume root-owned).
- κ Fleiss tổng **âm** là bình thường (tool phủ miền rời) — đọc κ theo nhóm/cặp.
- Nhãn `gold` là **đồng thuận máy** tới khi kiểm tay (`evidence.validation`); `verified-clean` ≠ chứng minh sạch.
- CodeQL tắt mặc định trong mọi run thật (~20'/commit suite full); bật bằng `--codeql 1` + `ORCH_CODEQL_RAM_MB` phù hợp RAM Docker.

## 4. Nâng cấp DB cũ (bản VM 2026-07, `user_version` 0/1)

1. **Sao lưu** file `.sqlite` (và `-wal/-shm` nếu có).
2. Mở bằng bất kỳ lệnh ghi (`relabel`, `kappa`, `select`, `analyze`, `export`) → `SQLiteStore` **migrate tự động** lên
   `user_version=2`: thêm bảng `kappa`, `gold_review`, `gold_sample`, `scan_tool_errors`; cột `selected_commits.n_expensive_ok`,
   `expensive_runs.run_id`; `run_meta` cũ → `tier='scan'`, `run_id='legacy'`; `journal_mode=WAL`. Dữ liệu cũ giữ nguyên.
   Lệnh chỉ-đọc (`stats`, `compare`, `verify`, GUI) **không** migrate (mode=ro).
3. Chạy `relabel <repo>` để nhãn/`negative_level` theo định nghĩa mới (`n_expensive_ok ≥ 2`), rồi `kappa` (lưu bảng),
   `export --out <dir mới>` (manifest + jsonl mới), `verify --db --export`.
4. Lưu ý: `n_expensive_ok` của commit cũ được tính lại từ `expensive_runs` (`status='ok'`); commit từng được coi
   verified-clean với 1 tool ok sẽ **hạ xuống cheap-clean** — đây là sửa lỗi, không phải mất dữ liệu (ghi delta vào RESULTS).
5. Thư mục clone cũ `work/<repo>` vẫn dùng được nếu origin khớp URL; `.m2cache` giữ nguyên (hoặc `ORCH_M2_VOLUME=1`).
