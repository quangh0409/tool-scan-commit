# TASKS — Kế hoạch triển khai desktop app `secjit-scan.exe` (đủ 10 màn)

> Chốt 2026-10-04 với user. **Claude code toàn bộ**; user chỉ duyệt UI theo mốc, cung cấp máy, và chấm tay GOLD. Thời gian ước tính là **giờ làm việc của Claude** + **giờ máy chờ** (Docker build/scan) + **điểm dừng cần user**.
> Trạng thái cập nhật vào `SESSION_CONTEXT.md`; quyết định phương pháp luận đã ghi `TOOL_IDEA_CONTEXT.md` §13. Review gốc: `REVIEW.md`.

---

## 0. Sáu quyết định đã chốt

| # | Câu hỏi | Quyết định | Ai |
|---|---|---|---|
| 1 | Phạm vi | **Phương án 3 — đủ 10 màn** như wireframe, bổ sung đủ trạng thái lỗi/rỗng/partial (REVIEW §III.A) | user |
| 2 | Tiêu chí tái lập MVP | **train-ticket `--max 30` trên laptop Windows**: chạy từ exe → ra `profile.json` + `run_manifest.json`; chạy lại bằng CLI `--profile` → cùng số cụm gold/silver/candidate (lệch chỉ ở commit có `tool_timeout`, được liệt kê trong manifest). Full-history vẫn trên VM | user |
| 3 | Chính sách tham số | **Cấu hình v1 "đăng ký trước" và khoá**: `LINE_WINDOW=3`, `GOLD_MIN_EXPENSIVE=2`, `GOLD_ALLOW_1EXP_1CHEAP=1`, `SILVER_MIN_CHEAP=2`, `NOISE_CWE={CWE-117}`; `VOTE_THRESHOLD` loại khỏi UI (legacy). Đổi tham số chỉ qua lệnh `sensitivity` chạy trên **bản sao** DB, hoặc "Chế độ thí nghiệm" bắt nhập lý do, gắn `experiment=true`, export sang `_exp_<tên>`, không bao giờ gộp vào `gold_set_all`. Báo cáo sensitivity (W∈{3,5,7}, 1E+1C∈{0,1}, NOISE on/off) là một mục bắt buộc của luận văn. *Cơ sở:* "researcher degrees of freedom" (Simmons, Nelson & Simonsohn 2011), HARKing (Kerr 1998), hướng dẫn thực nghiệm SE (Kitchenham et al. 2002), sensitivity analysis thay cho dò tay (Saltelli et al. 2008); khớp CLAUDE.md gốc §12.7, §12.9 | Claude |
| 4 | Thuật ngữ "GOLD" | **Giữ tên cột nội bộ** `gold/silver/candidate` (tương thích 5 dataset + script), **thêm trường `evidence`** trong export và UI: `consensus` (mức máy) + `validation ∈ {unreviewed, TP, FP, unclear}`. Hiển thị luôn là "gold · đồng thuận máy" cho tới khi kiểm tay, "gold ✓ TP" sau kiểm. Trong paper: "consensus-gold" là **silver standard** theo nghĩa Rebholz-Schuhmann et al. 2010 (CALBC); chỉ "human-validated gold" được gọi gold standard. `verified-clean` hiển thị kèm "2 tool đắt không báo — không phải chứng minh sạch" (absence of evidence ≠ evidence of absence, CLAUDE.md gốc §12.2). *Cơ sở:* nhiễu nhãn tự động trong SE dataset (Herzig, Just & Zeller 2013; Herbold et al. 2022 về SZZ) | Claude |
| 5 | Kiểm tay | **Có**, theo giao thức: mẫu **ngẫu nhiên phân tầng** theo CWE-group × tier, seed cố định ghi file; **n = 200 gold positive** (Wilson CI ≈ ±5,5 % tại p≈0,8) + **n = 100 verified-clean**; **chế độ mù** (ẩn nhãn, tên tool, số tool, precision); **2 rater** (user + 1 người cùng lab; nếu không có rater 2 → user chấm lần 2 cách ≥ 1 tuần làm intra-rater); Cohen κ (diễn giải Landis & Koch 1977; McHugh 2012); adjudication cho bất đồng; precision + Wilson CI (Brown, Cai & DasGupta 2001). File chấm công bố cùng dataset | user + Claude |
| 6 | Sửa 8 lỗi dữ liệu trước | **Có, làm đầu tiên (P0)**, vì D1 (verified-clean giả) và D2 (`build_failed` do Docker tắt) ảnh hưởng tính đúng của 5 dataset đã có → phải **đối soát lại `negative_level` trên 5 DB cũ** và ghi delta vào `RESULTS.md` trước khi xây GUI | Claude |

---

## 1. Kiến trúc chốt cho code

```
secjit-scan.exe (PyInstaller onefile)
 ├─ gui/            pywebview (WebView2) + web UI tĩnh (HTML/CSS/JS thuần, không framework)
 ├─ gui/server.py   stdlib http.server + SSE (progress) · chỉ localhost, port ngẫu nhiên, token phiên
 ├─ runner/         tiến trình NỀN tách rời (CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS),
 │                  pid-file + stop-file + progress.jsonl; GUI đóng/mở lại vẫn attach
 ├─ registry        %LOCALAPPDATA%\secjit\runs.json (danh sách run, DB, export, profile, trạng thái)
 └─ src/orchestrator  (stdlib-only, GIỮ) + các CLI mới ở P0
```

- **GUI được có dependency** (pywebview, PyInstaller); **orchestrator vẫn stdlib-only**. Parquet **bỏ**, CSV bằng `csv` stdlib.
- Mọi hành động GUI = 1 lệnh CLI có thật (`--profile`). Không fork logic nhãn vào GUI.
- Mọi `docker run` gắn `--label orch.run=<run_id>` để tìm/dọn mồ côi.
- SQLite bật `journal_mode=WAL`; GUI mở `mode=ro`.

---

## 2. Các pha, task, ước tính

Ký hiệu: **C** = giờ Claude làm việc thật (viết + tự test) · **M** = giờ máy chờ (Docker, build) · **U** = điểm dừng cần user (số lần, ~15–30 phút mỗi lần, trừ khi ghi khác).

### P0 — Nền dữ liệu & CLI (điều kiện để GUI không hứa suông)

| Task | Nội dung | C | M | U |
|---|---|---|---|---|
| P0.1 | Sửa 8 lỗi dữ liệu (REVIEW §I.3): D1 `status='skipped'` khi 0 module Java + cột `n_expensive_ok`, `negative_level` đòi ≥2 tool đắt ok; D2 phân biệt lỗi hạ tầng Docker (rc 125/127, "Cannot connect") → `status='infra_error'`, không ghi `build_failed`, dừng run sau 3 lỗi liên tiếp; D3 lock theo DB + Sonar container/network theo `run_id`; D4 `clone_or_update` fetch + tên clone `owner__repo` + kiểm `origin`; D5 export vào thư mục mới hoặc dọn có xác nhận; D6 bắt disk-full → dừng; D7 `cmd_clean` dùng `_rmtree`; D8 WAL | 4 | 0,5 | — |
| P0.2 | **Đối soát 5 DB cũ** (train-ticket, mall-swarm, spring-cloud-stream, spring-cloud-kubernetes, giraph): chạy lại `negative_level` mới, ghi delta verified-clean → `RESULTS.md`. *Phụ thuộc:* user tải 5 DB từ VM về hoặc bật VM | 1 | 0,5 | 1 (lấy DB) |
| P0.3 | `run_meta` v2: `config_snapshot` JSON toàn bộ `ORCH_*` hiệu lực, `branch`, `scope`, `include_clean`, `orchestrator_git_sha`, `app_version`, ghi riêng cho tầng `analyze` (image + digest FSB/Sonar/CodeQL/maven); κ lưu bảng `kappa`; `PRAGMA user_version` + migrate | 2 | — | — |
| P0.4 | `export` sinh `dataset.jsonl` + `commits.jsonl` (gộp `merge_export.py`), `run_manifest.json` (profile, run_meta 2 tầng, κ, đếm nhãn, build_failed list, tool_timeout list), `SHA256SUMS`, trường `evidence` (QĐ 4) | 2 | — | — |
| P0.5 | Phạm vi: `--since/--until` (committer-date, ghi run_meta), `--from-sha/--to-sha`, ép `--max 0` khi dùng; `estimate` subcommand (số commit sau lọc, ước tính từ bảng tốc độ đo trên máy `speed.json`) | 2 | — | — |
| P0.6 | Chọn tool: `--tools` (rẻ) + `--expensive-tools` cho `pipeline`; cảnh báo đổi `eligible`/κ khi bỏ tool | 1 | — | — |
| P0.7 | `--profile profile.json` cho mọi subcommand; `profile` schema + validate; `stop` subcommand (stop-file + CTRL_BREAK trên Windows / SIGTERM Linux) + `reset-claims --run <id>` (reset `building/analyzing` → pending, xoá raw đắt bán phần, dọn container theo label, gỡ network) | 3 | 1 | — |
| P0.8 | `stats` subcommand (phễu, nhãn 3+2 mức, CWE-group × nhãn × tier × in_diff, per-repo, κ nhóm + pairwise, "giới hạn" tự sinh) → JSON + CSV + LaTeX; `sensitivity` subcommand (relabel trên bản sao DB theo lưới tham số) | 3 | 0,5 | — |
| P0.9 | `clean` tách từng mục + `--dry-run` liệt kê; `ORCH_LINE_WINDOW` chỉ nhận trong experiment mode; bỏ `VOTE_THRESHOLD` khỏi run_meta hiển thị; progress `progress.jsonl` có schema (`phase, done, total, worker, sha, status, ts`) | 2 | — | — |
| P0.10 | Smoke lại trên Windows `--max 5` train-ticket với toàn bộ P0 (scratch DB) + ruff + compile; cập nhật README/GUIDE | 1 | 1,5 | 1 (duyệt RESULTS P0.2) |
| **Tổng P0** | | **21 h** | **4 h** | **2** |

### P1 — Runner nền, registry, preflight engine

| Task | Nội dung | C | M | U |
|---|---|---|---|---|
| P1.1 | `runner/`: spawn tiến trình tách rời, pid-file, stop-file, log-file, heartbeat; attach lại; phát hiện "pid chết nhưng DB còn building" → đề xuất `reset-claims` | 3 | 1 | — |
| P1.2 | `registry`: `runs.json` (run_id, repo, branch, DB, export, work, profile, started/finished, status, pid, tóm tắt nhãn/κ cache) + single-instance mutex app + lock theo DB | 2 | — | — |
| P1.3 | `preflight/`: 13 kiểm tra (REVIEW §II plan §2 + sửa: RAM Docker `docker info MemTotal` thay RAM host, image FSB/CodeQL = **build** từ `docker/`, `vm.max_map_count` trong WSL2, image `:latest` chưa pin, ổ chưa Docker file-sharing, proxy); 5 auto-fix (bật Docker + poll 90 s, chọn port trống, pull/build image có %, `core.longpaths`, hạ `CODEQL_RAM_MB`); `preflight --json` headless; `preflight.json` | 3 | 1 | — |
| P1.4 | `speed.json`: đo tốc độ thật (s/commit rẻ, s/build cold/warm) từ mỗi run → nạp `estimate` | 1 | — | — |
| **Tổng P1** | | **9 h** | **2 h** | **0** |

### P2 — GUI khung + Preflight + Home + Wizard 1–5

| Task | Nội dung | C | M | U |
|---|---|---|---|---|
| P2.1 | `gui/server.py` (stdlib http.server, SSE, API: preflight, repo-check, estimate, run start/stop/resume, registry, results query, settings), token phiên, chỉ localhost; `gui/main.py` pywebview; dev-mode mở trình duyệt thường để Claude test bằng Playwright/urllib | 3 | — | — |
| P2.2 | Design system web UI (token màu/kiểu như wireframe, component: btn/card/table/stepper/toast/dialog/empty/error/loading) + i18n VI/EN khung | 2 | — | — |
| P2.3 | **Preflight** đủ trạng thái: đang kiểm (spinner từng dòng), 3 mức, sửa thất bại + thử lại, tải có %/huỷ, "Tiếp tục dù ⚠️" xác nhận, log chẩn đoán | 1,5 | — | — |
| P2.4 | **Home**: rỗng, Docker tắt, run nền chết → "Bị ngắt", DB mất, badge mức bằng chứng (gold đã kiểm x/y), "Tiếp tục" tự chọn tầng, "Chạy lại từ đầu" tách riêng có xác nhận, "Chạy lại cùng profile" | 1,5 | — | — |
| P2.5 | **Wizard 1 Repo**: chuẩn hoá URL (tree/commit/pull/blob/.git/SSH→HTTPS), `ls-remote` có timeout, 401/403/404, clone nền + fetch, phát hiện pom/JDK/module + **check tiêu chí chọn repo** (SNAPSHOT pom cũ, đếm `SecurityConfig`), cảnh báo repo không Java → tắt tầng đắt, PAT qua env (không vào run_meta) | 2 | — | — |
| P2.6 | **Wizard 2 Phạm vi**: 4 chế độ (thời gian / N / SHA / full), validate (từ>đến, N=0 cấm, SHA verify), biểu đồ mật độ tháng kéo-chọn, "chưa ước tính được" khi clone chưa xong, 0 commit chặn; bỏ checkbox "merge" (hiển thị cố định); thêm `CLEAN_PER_BUGGY`, `--require-in-diff` | 2 | — | — |
| P2.7 | **Wizard 3 Tool**: badge tốc độ thật từ `speed.json`, image có/build/pull, cảnh báo bỏ tool phá consensus, luồng khoá theo CPU và RAM Docker, CodeQL tự hạ RAM; "Nâng cao" **chỉ đọc** cấu hình v1 + nút "Chế độ thí nghiệm" (lý do bắt buộc) | 1,5 | — | — |
| P2.8 | **Wizard 4 Lưu**: validate đường dẫn (UNC cấm, OneDrive cảnh báo, quyền ghi, dài >260, trùng WORK/OUT), DB tồn tại → Resume/Đổi tên/Ghi đè(gõ tên + .bak), đĩa so ước tính ×1,5; bỏ Parquet; raw bắt buộc | 1,5 | — | — |
| P2.9 | **Wizard 5 Xem lại**: ước tính cold/warm từ speed.json, lệnh CLI **PowerShell + bash** sinh từ profile và được `argparse` thật parse-check, lưu profile, "Chạy thử 3 commit" = 3 commit qua lọc có đụng Java vào **DB scratch** + màn kết quả thử | 1,5 | — | — |
| P2.10 | Test GUI tự động (Playwright nếu có, else urllib + kiểm HTML) cho các trạng thái; sửa theo phản hồi user | 2 | — | **2** (duyệt Preflight+Home; duyệt Wizard) |
| **Tổng P2** | | **18,5 h** | **0** | **2** |

### P3 — Dashboard, Results (5 tab), Settings

| Task | Nội dung | C | M | U |
|---|---|---|---|---|
| P3.1 | **Dashboard**: 3 thanh từ `progress.jsonl` + SQLite ro, worker + tool đang chạy, ETA từ speed thật, log lọc (structured), **ẩn nhãn tạm khi chạy** (chỉ đếm raw), Dừng an toàn/cưỡng bức + liệt kê đã dọn, phát hiện Docker tắt / disk đầy / ≥3 infra_error → tự tạm dừng + banner, đóng cửa sổ → hộp "Chạy nền/Dừng/Huỷ", đổi số luồng (dừng + tiếp tục), gói chẩn đoán | 3 | 1 | — |
| P3.2 | **Results · Finding**: lọc nhãn/CWE-group/≥N tool/tier/`in_diff`/tìm, phân trang server-side, loading/rỗng/chưa relabel/run dở/DB đang ghi | 2 | — | — |
| P3.3 | **Results · Bằng chứng** (panel): diff tô dòng, `eligible` + mẫu số, tool + rule + severity + message, **mở raw SARIF/XML**, dòng provenance (run, digest, W, luật gold), hiển thị "gold · đồng thuận máy / ✓ TP" (QĐ 4) | 2 | — | — |
| P3.4 | **Results · Tổng quan**: phễu, nhãn 3+2 mức, CWE-group × nhãn, κ tổng/nhóm/pairwise + coverage 1/2/≥3 tool + đoạn giải thích chuẩn + κ W=3 vs W=7, precision kiểm tay (hoặc "n=0"), khối "Giới hạn dataset" tự sinh, xuất CSV/LaTeX (từ `stats`) | 2,5 | — | — |
| P3.5 | **Results · Commit**: role, negative_level với `n_expensive_ok`, Kamei, build_failed lý do, nút `features` backfill, `relabel` lại (chỉ experiment mode) | 1,5 | — | — |
| P3.6 | **Results · Xuất**: export mới (thư mục theo run_id), CSV, manifest, "Mở thư mục", cảnh báo thư mục cũ; chọn run từ registry | 1 | — | — |
| P3.7 | **Settings**: Docker & tài nguyên (MemTotal, port, image digest, pin), Dung lượng (du nền + xem trước xoá qua `clean --dry-run`, khoá khi run sống, vùng cấm kết quả), Profile (lưu/tải/xoá), Ngôn ngữ, tab "Chế độ chạy" chỉ hiển thị Local (VM = sau MVP) | 2 | — | — |
| P3.8 | Test + sửa theo phản hồi | 2 | 1 | **2** (Dashboard trên run thật; Results) |
| **Tổng P3** | | **16 h** | **2 h** | **2** |

### P4 — Kiểm tay GOLD (QĐ 5)

| Task | Nội dung | C | M | U |
|---|---|---|---|---|
| P4.1 | Bảng `gold_review(cluster_key, sample_id, rater, verdict, note, at)` với khoá ổn định `hash(repo, commit, file, cwe_group, s_line//W)`; lệnh `review sample --seed --n-pos 200 --n-neg 100` phân tầng → `gold_sample_<seed>.json`; map lại sau relabel + cảnh báo lệch | 2 | — | — |
| P4.2 | Màn **Kiểm tay** mù: ẩn nhãn/tool/số tool/precision; hiện code + diff + CWE claim + message đã ẩn tên tool; phím tắt TP/FP/?; tiến độ; tạm dừng/tiếp; chấm cả verified-clean (có lỗi bảo mật không?) | 2 | — | — |
| P4.3 | Đóng phiên: precision + Wilson CI, Cohen κ 2 rater, danh sách bất đồng → màn adjudication; xuất `gold_review_<rater>.json`; `build_gold_set.py` đọc bảng, ghi precision vào README gold_set, bỏ hardcode `/home/scanner` | 2 | — | — |
| P4.4 | **User chấm**: 200 + 100 mẫu ≈ 1–2 phút/mẫu → **5–8 giờ user** (rater 1) + rater 2 tương tự | 0,5 | — | **1 dài** (5–8 h/rater) |
| **Tổng P4** | | **6,5 h** | **0** | **1 dài** |

### P5 — Hoàn thiện 10 màn

| Task | Nội dung | C | M | U |
|---|---|---|---|---|
| P5.1 | Hàng đợi batch (tuần tự tuyệt đối, 1 Sonar), màn hàng đợi | 2 | — | — |
| P5.2 | Toast Windows (winotify hoặc PowerShell), tray thu nhỏ | 1 | — | — |
| P5.3 | Cache Maven Docker volume `ORCH_M2_VOLUME` + đo lại speed | 1 | 1 | — |
| P5.4 | i18n VI/EN đủ chuỗi; gói chẩn đoán zip (log, run_meta, docker info, profile, preflight.json) | 1,5 | — | — |
| P5.5 | Cập nhật TOOL_IDEA §8–9 (đã làm §13), README (hướng dẫn exe), GUIDE (env mới), METHODOLOGY (QĐ 3–5) | 1,5 | — | — |
| **Tổng P5** | | **7 h** | **1 h** | **0** |

### P6 — Đóng gói & CI

| Task | Nội dung | C | M | U |
|---|---|---|---|---|
| P6.1 | PyInstaller onefile + pywebview + nhúng `src/orchestrator`, `docker/`, web UI; `--version`, `--preflight --json`, `--profile` headless; self-signed sign; checksum | 2 | 0,5 | — |
| P6.2 | Test **máy sạch** (VM Windows 11 không Docker/Git): đúng 2 ❌, không traceback, SmartScreen hướng dẫn. *Phụ thuộc:* user cấp VM hoặc máy sạch | 1 | 1 | **1** |
| P6.3 | CI GitHub Actions `windows-latest`: ruff + unit (path posix, URL normalize, negative_level, reset-claims, run_meta round-trip, `_rmtree` read-only, GBK) + contract (profile→argparse, env→config) + build exe + `--preflight --json`; `ubuntu-latest` smoke rẻ + FSB | 2,5 | 0,5 | — |
| **Tổng P6** | | **5,5 h** | **2 h** | **1** |

### P7 — Nghiệm thu tái lập (QĐ 2)

| Task | Nội dung | C | M | U |
|---|---|---|---|---|
| P7.1 | Run A: exe → train-ticket `master` `--max 30` `--include-clean`, 5 rẻ + FSB + Sonar, 2 luồng, trên laptop. Lần đầu cache lạnh | 0,5 | **3–4** | — |
| P7.2 | Run B: `cli pipeline --profile <A>/profile.json` vào DB mới; so `dataset.jsonl` A/B theo cluster_key; lệch phải nằm trong `tool_timeout`/`infra_error` của manifest | 0,5 | **1,5–2** (cache ấm) | — |
| P7.3 | Báo cáo nghiệm thu `RESULTS.md` (số nhãn A/B, κ, thời gian, lệch + lý do) + demo 10 phút kịch bản cho hội đồng | 1 | — | **1** (chạy demo cùng user) |
| **Tổng P7** | | **2 h** | **5–6 h** | **1** |

---

## 3. Tổng hợp thời gian

| | Giờ Claude (C) | Giờ máy chờ (M) | Điểm dừng user (U) |
|---|---|---|---|
| P0 Nền dữ liệu & CLI | 21 | 4 | 2 |
| P1 Runner, registry, preflight | 9 | 2 | 0 |
| P2 GUI khung + 7 màn đầu | 18,5 | 0 | 2 |
| P3 Dashboard, Results, Settings | 16 | 2 | 2 |
| P4 Kiểm tay GOLD | 6,5 | 0 | 1 (5–8 h/rater) |
| P5 Hoàn thiện | 7 | 1 | 0 |
| P6 Đóng gói, CI | 5,5 | 2 | 1 |
| P7 Nghiệm thu | 2 | 5–6 | 1 |
| **Tổng** | **≈ 85 h** | **≈ 17 h** | **9 điểm dừng + 1–2 phiên chấm dài** |

**Quy ra lịch** (giả định mỗi phiên Claude ~4 giờ làm việc hiệu quả, máy chờ chạy nền song song với việc khác):

- **≈ 21 phiên Claude.** 1 phiên/ngày → **4–5 tuần**; 2 phiên/ngày → **2,5–3 tuần**.
- Đường tới hạn không phải code mà là: (a) P0.2 cần 5 DB từ VM, (b) 9 điểm duyệt UI của user, (c) 5–8 giờ chấm tay mỗi rater, (d) P6.2 cần máy sạch, (e) P7 ≈ 6 giờ máy.
- Mốc có thể demo sớm: **sau P3** (≈ 11 phiên) đã có đủ Preflight → Wizard → Run → Results trên máy user; P4–P7 hoàn thiện phần học thuật và đóng gói.

**Độ tin cậy ước tính:** ±30 %. Rủi ro làm trượt: pywebview/WebView2 trên máy user (chưa test), hành vi dừng tiến trình trên Windows (CTRL_BREAK qua process group), Docker Desktop tự tắt khi quá tải (đã gặp), và việc Claude không nhìn được GUI trực tiếp nên mỗi vòng sửa UI phụ thuộc ảnh chụp/phản hồi của user (vì vậy P2.1 có dev-mode mở trình duyệt để Claude tự test bằng Playwright nếu cài được).

---

## 4. Thứ tự làm & mốc duyệt

```
P0 ──► [U1: duyệt RESULTS đối soát 5 DB] ──► P1 ──► P2 ──► [U2 Preflight+Home] [U3 Wizard]
   ──► P3 ──► [U4 Dashboard trên run thật] [U5 Results] ──► P4 ──► [U6 chấm tay 5–8 h × rater]
   ──► P5 ──► P6 ──► [U7 máy sạch] ──► P7 ──► [U8 demo 10 phút] ──► bàn giao
```

Mỗi pha kết thúc bằng commit riêng trên `dev`, cập nhật `SESSION_CONTEXT.md`, và chạy ruff + smoke. Không mở pha sau khi pha trước còn lỗi chặn.

## 5. Phụ thuộc cần user chuẩn bị (có thể làm ngay, song song P0)

1. Tải 5 file `data/dataset_*.sqlite` từ VM về laptop (hoặc cho tôi biết đường dẫn) — cần cho P0.2.
2. Xác nhận có rater 2 không (tên vai, không cần tên thật) — ảnh hưởng P4.3.
3. Máy/VM Windows sạch cho P6.2 (có thể là Windows Sandbox).
4. Giữ Docker Desktop mở khi tôi chạy P0.10, P3.8, P7; tránh chạy build nặng khác cùng lúc (máy đã treo một lần).
