# REVIEW — Desktop app `.exe` (plan `DESKTOP_APP_PLAN.md` + wireframe 10 màn)

> Ngày 2026-10-04. Ba agent review độc lập theo vai **BA** (truy vết chức năng), **TEST** (luồng lỗi, edge case), **PO** (giá trị, phạm vi, học thuật). Phần I là tổng hợp của Claude; phần II–IV là ba báo cáo gốc, giữ nguyên.
> Wireframe click được: https://claude.ai/artifact/RHSeNaHneNzgfSvhDbvyMx

---

# PHẦN I — TỔNG HỢP

## 1. Câu trả lời ngắn: đã đủ chức năng chưa?

**Chưa.** Wireframe phủ tốt *luồng vận hành* (preflight → cấu hình → chạy → xem), nhưng còn 3 lớp thiếu:

| Lớp | Thiếu gì | Ai chỉ ra |
|---|---|---|
| **Backend chưa có** để GUI gọi | `--since/--until`, khoảng SHA, chọn tool rẻ, `estimate`, registry run, resume từ GUI, Dừng an toàn (không có signal handler, Windows không có SIGTERM), kiểm tay GOLD, merge export vào `export`, structured progress log, Docker volume cache Maven, profile | BA §B, TEST F1–F2 |
| **Trạng thái màn hình chưa vẽ** | Loading / rỗng / lỗi / partial / Docker tắt giữa chừng / run nền đã chết / 2 cửa sổ / DB đã tồn tại… 9/10 màn hiện tĩnh, chỉ Preflight có 2 trạng thái | TEST §A |
| **Yêu cầu học thuật chưa thể hiện** | Provenance đầy đủ (run_meta tầng đắt, git-sha, config snapshot), manifest tái lập, hiển thị nhãn "gold = đồng thuận máy", κ theo nhóm CWE/pairwise, threats to validity tự sinh, kiểm tay GOLD **mù + mẫu phân tầng có seed**, sensitivity trên bản sao DB, chặn tinh chỉnh tham số theo kết quả | PO §C |

## 2. Điểm cả ba agent cùng chỉ ra (độ tin cậy cao)

1. **Run chết theo cửa sổ GUI.** Plan §1 đặt backend cùng tiến trình với GUI, mâu thuẫn với lời hứa "đóng cửa sổ vẫn chạy". Phải tách tiến trình nền (pid-file, log-file, GUI attach lại). Đây là chính lỗi skywalking đã mất 6,5 giờ.
2. **"Dừng an toàn" chưa có nền tảng.** Orchestrator không có signal handler; container maven/sonar-scanner/tool rẻ không có `--name`/`--label` nên không tìm được mồ côi; `reset_stale_claims` chờ 7200 s; `stop_server` không chạy khi bị kill. Cần lệnh CLI `stop`/`reset-claims --force` làm đúng 4 bước đã làm tay ngày 2026-07-08.
3. **Panel "Nâng cao" sai nửa.** `VOTE_THRESHOLD` là tham số chết (chỉ ghi run_meta); `LINE_WINDOW` là hằng số, W=7 chỉ cho gold trên bản copy DB; thiếu `GOLD_ALLOW_1EXP_1CHEAP`, `SILVER_MIN_CHEAP`, `NOISE_RULES`. Cho sửa tự do ngay trước khi chạy = mời cherry-pick (vi phạm §12.7/§12.9 CLAUDE.md gốc).
4. **`run_meta` không đủ để tái lập.** Chỉ 6 trường, chỉ 5 tool rẻ; không có nhánh, phạm vi, tham số nhãn, codeql, include_clean, JDK image, git-sha orchestrator. κ chỉ `print`. Export không có manifest. Lệnh CLI "tương đương" ở Wizard 5 dùng cờ chưa tồn tại, cú pháp bash, thiếu `--max 0` và `ORCH_WORK_DIR`.
5. **Ước tính thời gian là số bịa.** 12 s/commit rẻ, 2,5 phút/commit đắt, 33 % buggy — trong khi Windows đo được 881 s/commit build cold. Cần `estimate` từ tốc độ đo thật và nhãn cold/warm.
6. **Preflight đo sai đại lượng.** RAM vật lý thay vì RAM Docker/WSL2 (mặc định 50 %); image FindSecBugs/CodeQL phải **build** từ `docker/`, không pull; thiếu `vm.max_map_count`; `CODEQL_RAM_MB=20000` vượt máy 16 GB.
7. **Registry run không tồn tại.** Home, Results dropdown, Resume đều cần `runs.json` + DB per run; hiện chỉ có `run_meta` rải trong từng DB.
8. **`export` không sinh `dataset.jsonl`/`commits.jsonl`.** Phải gộp `scripts/merge_export.py` vào `cmd_export`.
9. **Smoke "Chạy thử 3 commit" chưa chứng minh gì.** `--max 3` = 3 commit mới nhất, có thể toàn merge/docs → 0 commit Java; phải chọn 3 commit qua lọc có đụng Java và ghi vào DB scratch.
10. **Kiểm tay GOLD vẽ sai phương pháp.** Hiện precision tạm khi đang chấm (anchoring), không mù (thấy nhãn + tên tool), chấm theo thứ tự bảng thay vì mẫu phân tầng có seed, chưa có rater 2, khoá review không ổn định sau relabel (DELETE+INSERT), chỉ chấm positive không chấm verified-clean.

## 3. Lỗi dữ liệu nghiêm trọng TEST phát hiện trong code (độc lập với GUI, nên sửa trước)

| # | Lỗi | Vị trí | Hậu quả |
|---|---|---|---|
| D1 | **Verified-clean GOLD giả**: `negative_level` chỉ cần 1 tool `analyze ok`, kể cả khi `classes_dirs=[]` (commit yml-only, repo không Java) → tool trả `[]` status ok | `sqlite_store.py:482–485`, `build.py:78–82`, `expensive_runner.py:70–71` | Nhãn vàng âm mà không tool nào phân tích; cần `status='skipped'` khi 0 module Java và cột `n_expensive_ok` |
| D2 | **Docker tắt giữa run → `build_failed` hàng loạt ghi như dữ liệu** (mọi rc≠0 là dữ liệu) | `build.py:101–110` | DB ô nhiễm; cần phân biệt lỗi hạ tầng (rc 125/127, "Cannot connect to the Docker daemon") và tự dừng |
| D3 | **Không có khoá chống 2 run**: Sonar container/network tên hằng + `rm -f` lúc start; 2 scan cùng DB xoá raw của nhau | `sonar.py:31–32, 69–73`, `cli.py:60` | Run B giết Sonar của run A |
| D4 | **Clone cũ không fetch + trùng tên repo khác org** | `enumerate_commits.py:68–71` | Quét clone cũ/nhầm repo im lặng |
| D5 | **Export trộn**: `export_all` không dọn thư mục cũ | `export_dataset.py:39–44` | Relabel rồi export cùng `--out` → commit cũ còn sót |
| D6 | **Đĩa đầy bị nuốt** trong `_loop` try/except, đếm `error` rồi chạy tiếp | `expensive_runner.py:128–133` | Run chạy tiếp vô ích |
| D7 | **`cmd_clean._rm` không chmod read-only**, fallback cần Docker | `cli.py:270–278` | Dọn thất bại im lặng khi Docker tắt (dùng `repo_pool._rmtree`) |
| D8 | **SQLite không WAL** → GUI poll làm "database is locked" | `sqlite_store.py:164–177` | Cần `PRAGMA journal_mode=WAL`, GUI mở `mode=ro` |

## 4. Mâu thuẫn plan/wireframe ↔ code cần sửa trong wireframe (nhanh)

- Results mock `application.yml CWE-798 gitleaks+bearer → GOLD` vi phạm luật nhãn (E=0, C=2 → silver).
- Results mock `350f6200 CodeQL+FSB+Sonar` không khớp dataset train-ticket (run `--codeql 0`).
- Home mock skywalking "162/1519 · 28 %" lệch (162/1519 = 10,7 %).
- Dashboard "cheap-clean 35" sai khái niệm khi đã `--include-clean`.
- Wizard 1 "323 commit" không lấy được từ `ls-remote`; "build ~92 % ok" không dự báo được.
- Wizard 2 "Bỏ merge commit" là checkbox nhưng `SKIP_MERGE_COMMITS=True` là hằng.
- Wizard 4 "Giữ output thô" là checkbox nhưng raw luôn lưu; Parquet mâu thuẫn stdlib-only.
- Wizard 3 / Settings vẽ "Docker volume secjit-m2" như đã có.
- TOOL_IDEA §8–9 nói "máy Windows chỉ điều khiển VM" — phải cập nhật quyết định kiến trúc trước khi code P1.

## 5. Khuyến nghị PO (khác biệt lớn nhất, cần bạn quyết)

PO lập luận: 3 persona thật của luận văn là **tác giả**, **hội đồng demo 10 phút**, **nhà nghiên cứu tái lập** (gần chắc chạy Linux). Persona "người không biết Python muốn quét repo" **không có trong luận văn**. Giá trị học thuật nằm ở **2 màn**: Results/Tổng quan/Bằng chứng và Kiểm tay GOLD, cả hai chỉ cần đọc SQLite, không cần Docker/preflight/wizard.

| Phương án | Nội dung | Công | Rủi ro |
|---|---|---|---|
| **(1) PO đề xuất** | Tuần 1–2: CLI `--profile`, `run_manifest.json`, `stats`, `sensitivity`, đóng băng tham số. Tuần 3–4: **viewer 2 màn** (Results + GOLD review mù) mở file `.sqlite`. Demo = viewer + 1 lệnh `scan --max 3` trong terminal. Quyết định exe/wizard sau khi có precision kiểm tay | ~12–15 ngày | Không có "exe cho người ngoài" |
| **(2) Plan hiện tại, MVP thu gọn** | Must M1–M10 trong PO §D: wizard 2 màn, preflight 5 mục, run nền + Dừng an toàn, Results + Tổng quan + GOLD review, exe | ~28 ngày (plan ghi 2–3 tuần là lạc quan 2×) | Docker Desktop, Windows path/perf, bảo trì exe sau bảo vệ |
| **(3) Plan đầy đủ như wireframe** | 10 màn + batch + VM SSH | &gt; 40 ngày | Phình phạm vi luận văn |

Cả BA và TEST đều không phản đối hướng (1): các blocker F1–F2 (run nền, Dừng an toàn) chỉ cần khi GUI *điều khiển run*; viewer đọc SQLite không chạm tới chúng.

## 6. Câu hỏi cần bạn chốt (gộp từ ba agent)

1. **Phương án (1), (2) hay (3)?** Mục tiêu "người không biết Python chạy được" có nằm trong luận văn không?
2. **Tiêu chí tái lập của MVP**: train-ticket `--max 30` trên laptop, hay full-history trên VM (khi đó chế độ SSH quan trọng hơn exe)?
3. **Chính sách tham số**: khoá W=3, 1E+1C, SILVER=2, NOISE=CWE-117 làm mặc định công bố; thay đổi chỉ qua `sensitivity` trên bản sao DB và tag `experiment=true`? Cần Claude #1 (thư ký phương pháp luận) xác nhận vì là "bất biến mềm" §10.7.
4. **Thuật ngữ "GOLD"**: giữ và ép mọi chỗ hiển thị kèm "(đồng thuận máy, precision kiểm tay = x, n = y)", hay đổi tên `consensus-high/-mid/-low` trong dataset công bố?
5. **Rater thứ 2** cho kiểm tay ~100–200 mẫu có kiếm được không? Nếu không, tối thiểu chế độ mù + seed + công bố file chấm.
6. **Docker Desktop**: chấp nhận là điều kiện ngoài ("yêu cầu hệ thống") hay cố auto-fix?
7. **Ràng buộc stdlib-only**: lớp GUI được có dependency (pywebview) còn orchestrator giữ stdlib? Parquet bỏ?
8. **Sửa 8 lỗi dữ liệu ở §3 trước** (độc lập GUI, ảnh hưởng dataset đang có) — đồng ý làm ngay?

## 7. Việc làm được ngay, không cần quyết định

- Sửa 8 lỗi dữ liệu §3 (D1 và D2 ảnh hưởng trực tiếp tính đúng của nhãn verified-clean trong 5 dataset đã có — cần kiểm lại `negative_level` trên các DB cũ).
- Mở rộng `run_meta` (config snapshot, git-sha, nhánh, 2 tầng), lưu κ vào DB, `export` sinh `run_manifest.json` + gộp `merge_export`.
- Thêm `--label orch.run=<id>` cho mọi `docker run`; `PRAGMA journal_mode=WAL`.
- Sửa wireframe theo §4 (mock số liệu, checkbox không tắt được, nhãn hiển thị).

---

# PHẦN II — BÁO CÁO BA (Business Analyst)

Nguồn đối chiếu: `src/orchestrator/cli.py` (argparse dòng 345–436), `src/orchestrator/config.py`, `GUIDE.md` §3, `README.md`, `scripts/*`, `RULE_GAN_NHAN.md`, `TOOL_IDEA_CONTEXT.md`, `SESSION_CONTEXT.md` (bullet 2026-10-04 → 2026-07-04), `DESKTOP_APP_PLAN.md` + 10 wireframe.

Ký hiệu mức: **MVP** = bắt buộc P1 · **NC** = nên có (P2/P3) · **NA** = nâng cao.

## A. Ma trận CLI / env → màn hình

### A1. Subcommand & argument (`cli.py:345–436`)

| Subcommand / arg | Màn / control cover | Mức | Ghi chú |
|---|---|---|---|
| `enumerate <repo> --max --branch --flag-limit` | Wizard2 (preview "187 commit sau lọc thô") — **ngầm** | MVP | GUI cần gọi `enumerate` nền để đếm; chưa có nút/trạng thái "đang đếm" trên wireframe. |
| `scan <repo> --max --branch --flag-limit --no-meta` | Wizard2 (`--max` = "N commit gần nhất", "Toàn lịch sử"=`--max 0`; "Bỏ commit khổng lồ"=`--flag-limit 1`), Wizard1 (`--branch`) | MVP | `--no-meta`: THIẾU (debug, chấp nhận được). |
| `select --include-clean` | Wizard2 checkbox "Đưa cả commit sạch vào tầng đắt" | MVP | OK. |
| `select --require-in-diff 0/1` | **THIẾU** | NC | Ảnh hưởng định nghĩa "buggy" (`select_commits.py:48`); nên vào "Nâng cao" Wizard3. Lưu ý `pipeline` hardcode `require_in_diff=None` (`cli.py:301`) → chỉ qua env `ORCH_SUSPECT_REQUIRE_IN_DIFF`. |
| `analyze <repo> --workers` | Wizard3 "Luồng tầng đắt" | MVP | OK. |
| `analyze --tools codeql,findsecbugs,sonar` | Wizard3 checkbox FindSecBugs/Sonar/CodeQL — **nửa cover** | MVP | `pipeline` truyền `tools=None` (`cli.py:302`) → GUI bỏ tick FindSecBugs/Sonar **không có đường** qua `pipeline`; phải set env `ORCH_EXPENSIVE_TOOLS` hoặc sửa `pipeline` nhận `--tools`. |
| `analyze --codeql 0/1` | Wizard3 checkbox CodeQL | MVP | OK. |
| `analyze --dry-run` | **THIẾU** | NC | Hữu ích cho "Chạy thử" khung hàng đợi không build; Wizard5 "Chạy thử 3 commit" nên là `--max 3` thật chứ không phải dry-run — cần nói rõ. |
| `relabel <repo>` | **THIẾU** (chỉ chạy ngầm trong pipeline) | NC | Kịch bản thật: đổi `NOISE_CWE`/ngưỡng gold → relabel ~30s không quét lại (TOOL_IDEA §7b). Results cần nút "Gán nhãn lại với tham số…". |
| `kappa` | Results header "κ Fleiss −0,36" — **chỉ κ tổng** | NC | `cmd_kappa` in theo CATEGORY và NHÓM-CWE n≥5 (`cli.py:323–331`): THIẾU trên GUI (plan P3 có ghi "κ theo nhóm"). |
| `features <repo> --branch` | **THIẾU** | NC | Backfill Kamei cho DB cũ (DB từ VM tải về). Nên có trong Results → tab Commit → "Tính lại đặc trưng Kamei". |
| `pipeline <repo> --max --branch --flag-limit --codeql --include-clean --workers --no-meta --out` | Wizard1–5 + Wizard5 CLI line | MVP | Đây là lệnh GUI dùng chính. Thiếu `--no-meta` (ok). |
| `clean <repo> [--export --cache --db --all]` | Settings/Dung lượng (Pool rác, Clone, Cache Maven) | NC | GUI đúng khi KHÔNG expose `--export/--db/--all` (bẫy xoá nhầm `data/export`, CLAUDE.md). Nhưng `clean` bắt buộc `repo` positional (`cli.py:423`) và xoá pool theo `WORK_DIR/pool_*` không phân biệt run đang chạy (`cli.py:282`) → **nguy hiểm nếu bấm khi có run sống**. |
| `export --out` | Wizard4 (thư mục export), Results "Xuất…" | MVP | `export` **KHÔNG sinh** `dataset.jsonl/commits.jsonl` (`export_dataset.py:37–83` chỉ ghi thư mục commit + `negatives.json`) — xem B. |

### A2. Env `ORCH_*` (`config.py`, GUIDE §3)

| Env | Màn / control | Mức | Ghi chú |
|---|---|---|---|
| `ORCH_WORK_DIR` | Wizard4 "Thư mục làm việc" | MVP | Wizard5 CLI line **không in** `ORCH_WORK_DIR` → lệnh "tương đương" không tái lập đúng. |
| `ORCH_DATA_DIR` | — (thay bằng `ORCH_SQLITE`+`--out`) | — | OK bỏ. |
| `ORCH_SQLITE` | Wizard4 tên DB tự sinh | MVP | OK. |
| `ORCH_EXPORT_DIR` | Wizard4 (`--out`) | MVP | OK; chú ý `clean --export` xoá theo env này, không theo `--out`. |
| `ORCH_STORE_FULL_FILE` | **THIẾU** | NA | Nặng; để "Nâng cao". |
| `ORCH_DOCKER_SG` | **THIẾU** | NA | Chỉ VM Linux (P4). |
| `ORCH_KAMEI`, `ORCH_FIX_KEYWORDS` | **THIẾU** | NA | Nâng cao; mặc định 1 là đủ MVP. |
| `ORCH_FLAG_LIMIT` | Wizard2 "Bỏ commit khổng lồ" | MVP | OK. |
| `ORCH_MAX_FILES_PER_COMMIT`, `ORCH_MAX_FILE_ADD/DEL/CHURN_LINES` | Wizard2 hiển thị text cố định ">100 file hoặc >1 000 dòng / file" — **không sửa được** | NC | Text cũng thiếu ngưỡng churn 2000 (`config.py:47`). |
| `ORCH_EXCLUDE_PATHS` | **THIẾU** | NA | |
| `ORCH_SCAN_WORKERS` | Wizard3 "Luồng tầng rẻ" | MVP | OK. |
| `ORCH_SCAN_RESUME` | Home "Tiếp tục" (ngầm =1) | MVP | Không có nút "Quét lại từ đầu" (=0) → Home "Chạy lại" sẽ **skip toàn bộ** commit đã `scan_done` (`cli.py:154–159`) chứ không chạy lại như tên nút gợi ý. |
| `ORCH_SUBMODULES` | **THIẾU** | NA | |
| `ORCH_CHEAP_INTRA_PARALLEL`, `ORCH_EXPENSIVE_INTRA_PARALLEL` | Wizard3 text "Mỗi luồng chạy 5 tool song song" (cố định) | NA | Đủ cho MVP. |
| `ORCH_SUSPECT_REQUIRE_IN_DIFF` | **THIẾU** | NC | Xem `select --require-in-diff`. |
| `ORCH_EXPENSIVE_WORKERS` | Wizard3 "Luồng tầng đắt" | MVP | Wizard5 in **cả** `ORCH_EXPENSIVE_WORKERS=2` lẫn `--workers 2` (trùng, không sai). |
| `ORCH_EXPENSIVE_TOOLS` | Wizard3 checkbox FSB/Sonar | MVP | Cách duy nhất để `pipeline` bỏ 1 tool đắt (xem A1). |
| `ORCH_USE_CODEQL` | Wizard3 CodeQL | MVP | OK (`--codeql`). |
| `ORCH_MAVEN_IMAGE`, `ORCH_JDK_AUTODETECT`, `ORCH_JDK_IMAGE_TEMPLATE` | Wizard1 chỉ **hiển thị** "JDK 8 (tự chọn image…)" | NC | Không có override khi autodetect sai (lý do backlog JDK trong SESSION). |
| `ORCH_MAVEN_GOALS`, `ORCH_BUILD_TIMEOUT` | **THIẾU** | NC | `BUILD_TIMEOUT=1800` quan trọng trên Windows (build cold 881 s, SESSION 2026-10-04) — nên cho chỉnh. |
| `ORCH_CODEQL_SUITE` | Wizard3 "Suite CodeQL" | NC | OK. |
| `ORCH_CODEQL_RAM_MB`, `ORCH_CODEQL_THREADS` | Preflight nói "tự hạ" (plan §2 #5) nhưng **không có control** | NC | Mặc định 20 000 MB (`config.py:125`) > RAM máy 16 GB → OOM chắc chắn nếu bật CodeQL mà không hạ. |
| `ORCH_SONAR_ADMIN_PW` | **THIẾU** | NA | OK giấu. |
| `ORCH_SONAR_PORT` | Preflight "Dùng 9100" | MVP | OK. |
| `ORCH_STALE_CLAIM_SEC` | **THIẾU** | NC | 7200 s: sau "Dừng an toàn" mà không reset tay, resume phải chờ 2 h mới nhả commit `building` (`expensive_runner.py:106`). |
| `ORCH_VOTE_THRESHOLD` | Wizard3 Nâng cao "VOTE_THRESHOLD 2" | — | **Tham số chết**: chỉ ghi vào `run_meta` (`cli.py:123`), không dùng trong labeler (grep chỉ ra 1 chỗ); `config.py:55` ghi "legacy". GUI hiển thị như núm có tác dụng → sai. |
| `ORCH_GOLD_MIN_EXPENSIVE` | Wizard3 Nâng cao | NC | OK. |
| `ORCH_GOLD_ALLOW_1EXP_1CHEAP`, `ORCH_SILVER_MIN_CHEAP` | **THIẾU** | NC | Là 2/3 tham số còn lại của thang nhãn (RULE_GAN_NHAN §9) — thiếu thì "Nâng cao" chưa trọn. |
| `ORCH_NOISE_CWE` | Wizard3 Nâng cao | NC | OK. |
| `ORCH_NOISE_RULES` | **THIẾU** | NC | |
| `LINE_WINDOW` (hằng, `config.py:54`) | Wizard3 Nâng cao "LINE_WINDOW 3" **sửa được** | — | **Mâu thuẫn**: không phải env; CLAUDE.md nói W=7 chỉ dùng qua `scripts/relabel_gold_w7.py` trên bản copy DB. Plan §5 không liệt kê việc thêm `ORCH_LINE_WINDOW`. |

## B. Ma trận ngược GUI → backend

| Màn | Control | Backend thực hiện | Trạng thái |
|---|---|---|---|
| **Preflight** | Mọi mục (WSL2, Docker cài/daemon, port, RAM, đĩa, image, Git, longpaths) + "Bật Docker", "Dùng 9100", "Tải 2,5 GB", "Sửa tất cả", "Kiểm tra lại" | không có | **MỚI toàn bộ** (module preflight). "Tải image": FSB (`orch-findsecbugs:1.14.0`) và CodeQL (`orch-codeql:2.25.6`) **phải build từ `docker/`** (README §1), không pull được → nút "Tải" sai bản chất, cần "Build (~X phút)". |
| Preflight | "Xem lại trạng thái cũ" | `preflight.json` | MỚI. |
| **Home** | "Run gần đây" (tên, số commit, thời lượng, gold/silver/κ, % dở) | không có registry; `run_meta` chỉ có started_at/repo/max/tools (`sqlite_store.py:80–85`) — không có branch, finished_at, κ, out dir | **MỚI**: `runs.json` registry + mở từng DB đếm nhãn. |
| Home | "Chạy lại" | `pipeline` với `ORCH_SCAN_RESUME` | Mơ hồ: resume hay quét lại? (A2). |
| Home | "Tiếp tục ▶" | `analyze → relabel → kappa → export` (README §3; mẫu `resume_skywalking.sh`) **không phải** `pipeline` | MỚI: logic chọn điểm resume theo trạng thái DB (có `scan_done`? có `selected_commits`? còn pending?). |
| Home | "Hàng đợi batch (2)" | không có | MỚI (P3). |
| Home | "Dung lượng … Dọn dẹp" | `clean` (một phần) + `docker system df` | MỚI phần đo. |
| **Wizard1** | "Kiểm tra" → Public/Java/Maven/**323 commit**/nhánh mặc định/12 nhánh 8 tag | `git ls-remote` (chưa có trong code; `resolve_rev` cần clone) | MỚI. **Số commit không lấy được từ ls-remote** — cần clone (nền) hoặc GitHub API; wireframe hứa trước khi clone. |
| Wizard1 | "Phát hiện từ pom.xml: Spring Boot, JDK 8, 43 module, **build ~92 % ok**" | JDK: có `build.py` autodetect; module count/dự báo build%: không có | MỚI; "build ~92% ok" là số đo sau khi chạy train-ticket, **không dự báo được** trước run → bỏ hoặc ghi rõ "tham chiếu repo đã chạy". |
| Wizard1 | "Repo private (PAT)" | `clone_or_update` = `git clone <url>` thường (`enumerate_commits.py:65`) | MỚI (credential helper + Credential Manager). |
| **Wizard2** | "Khoảng thời gian từ/đến" | không có `--since/--until` | MỚI (plan §5 có). Phải kết hợp với `--max`: `list_commits` mặc định `-n50` (`config.py:140`, `enumerate_commits.py:93`) → nếu thêm since/until mà quên `--max 0` thì chỉ 50 commit mới nhất. Wizard5 CLI line **không có `--max 0`** → sai. |
| Wizard2 | "Khoảng SHA" | không có | MỚI. |
| Wizard2 | "Bỏ merge commit" (checkbox) | `SKIP_MERGE_COMMITS = True` hằng (`config.py:19`), Kamei cũng bỏ merge | **Không tắt được** → nên hiển thị cố định, không phải checkbox. |
| Wizard2 | Biểu đồ mật độ tháng + kéo chọn | `git log --date=short` sau clone | MỚI. |
| Wizard2 | "187 commit sau lọc thô · ~61 buggy (33%) · ~2 h 10 m · ~1,8 GB" | `enumerate` cho số commit; buggy%/thời gian/đĩa: không có | MỚI `estimate` (plan §5). Tỉ lệ buggy 33% lấy từ đâu? (train-ticket universe 274: buggy ~? ; mall-swarm 60/279=21%; skywalking 1519/5554=27%). |
| **Wizard3** | Checkbox 5 tool rẻ | `CHEAP_TOOLS` hardcode (`cli.py:33`) | MỚI `--tools`/`ORCH_CHEAP_TOOLS`. Lưu ý: bỏ tool rẻ làm đổi `eligible`/κ (RULE §3) → cần cảnh báo. |
| Wizard3 | Badge "giây/commit", "image có · MB" | không có | MỚI (đo từ `expensive_runs.duration_sec` + `docker images`). Tầng rẻ **không có telemetry thời gian/commit** trong DB (`scan_done.finished_at` chỉ mốc kết thúc). |
| Wizard3 | "Giữ cache Maven trong Docker volume" | bind mount `WORK_DIR/.m2cache` (`build.py:27`) | MỚI (plan §5 `ORCH_M2_VOLUME`); Settings đã vẽ "docker volume secjit-m2" như đã tồn tại. |
| Wizard3 | Nâng cao: LINE_WINDOW / VOTE_THRESHOLD / GOLD_MIN_EXP / NOISE_CWE / Suite CodeQL | xem A2 | LINE_WINDOW: MỚI env; VOTE_THRESHOLD: **xoá**; thiếu GOLD_ALLOW_1EXP_1CHEAP, SILVER_MIN_CHEAP, NOISE_RULES. Chú thích "được ghi vào run_meta" **sai**: `run_meta` không lưu GOLD_MIN_EXPENSIVE/NOISE_CWE/branch/suite/workers/sonar port (`sqlite_store.py:326–336`). |
| **Wizard4** | Thư mục kết quả/làm việc, tên DB tự sinh | `ORCH_SQLITE`, `ORCH_WORK_DIR`, `--out` | OK. |
| Wizard4 | "dataset.jsonl + commits.jsonl" | `scripts/merge_export.py <export> <db>` — **script rời, không trong CLI** | MỚI: gọi script sau `export` (plan/wireframe không nhắc). |
| Wizard4 | "CSV", "Parquet" | không có | MỚI (P3). |
| Wizard4 | "Giữ output thô (+60%)" checkbox | raw luôn lưu `raw_output` + luôn export (`export_dataset.py:4`) | **Không tắt được** hiện tại → MỚI nếu muốn; hoặc bỏ checkbox. |
| Wizard4 | "Tự xoá clone và pool sau khi xong" | `clean <repo>` (mặc định) | OK, cần nối vào cuối pipeline. |
| Wizard4 | "Thông báo Windows" | không có | MỚI. |
| **Wizard5** | Bảng ước tính tầng đắt "61 buggy + 91 sạch × 2,5 m" | không có | MỚI. 2,5 phút/commit mâu thuẫn số đo: VM cache ấm ~30 s (`config.py:109`), Windows cold 881 s. |
| Wizard5 | "Lệnh CLI tương đương" | sinh chuỗi từ cấu hình | MỚI; nội dung hiện tại dùng `--since/--until` chưa tồn tại, thiếu `--max 0`, thiếu `ORCH_WORK_DIR`, thiếu `ORCH_EXPENSIVE_TOOLS` nếu bỏ tool, thiếu `PYTHONUTF8=1`. |
| Wizard5 | "Lưu profile…" | không có | MỚI. |
| Wizard5 | "Chạy thử 3 commit" | `pipeline --max 3` + scratch `ORCH_SQLITE` | OK về CLI, nhưng Sonar container tên cố định `orch-sonar` + network `orch-sonar-net` (`sonar.py:31–32`) → **không thể chạy thử khi đang có run khác**. |
| **Dashboard** | ① "152/187 · ~12 s/commit" | `scan_done` đếm done; tổng 187 không lưu trong DB; tốc độ: không có timestamp bắt đầu/commit | MỚI: ghi tổng todo + per-commit duration (plan §5 "JSON lines"). |
| Dashboard | ② "61 buggy · 91 sạch" | `selected_commits` role | OK. |
| Dashboard | ③ "18/152 · done/build_failed", "w0 · 9bdd9a28 · đang build (02:14)" | `selected_status_counts()`, `claimed_by/claimed_at/status` (`sqlite_store.py:92–106`) | OK — trạng thái `building` vs `analyzing` phân biệt được; "Sonar đang phân tích" chi tiết tool đang chạy: KHÔNG (status chỉ `analyzing`). |
| Dashboard | "Finding thô theo tool" | `raw_findings GROUP BY tool` | OK. |
| Dashboard | "Nhãn tạm gold/silver/candidate", "verified-clean 9 / cheap-clean 35" | `findings.label`; `negative_level()` (`sqlite_store.py:474`) tính được per commit | OK nhưng tốn: negative_level duyệt từng commit. |
| Dashboard | Log tail, lọc "Chỉ lỗi"/"Tầng đắt" | pipeline `print()` stdout, không có level/worker tag chuẩn | MỚI: structured log. |
| Dashboard | "Dừng an toàn" | **không có handler SIGTERM** (grep `signal` = 0 kết quả); `analyze()` chỉ `stop_server()` trong `finally` | **MỚI, phức tạp**: SIGTERM → chờ/giết container `maven`/`sonar-scanner`/`orch-sonar` + network → reset `building/analyzing`→`pending` + xoá raw đắt bán phần (`raw_output/raw_findings tier=expensive`, `expensive_runs`) — đúng quy trình tay SESSION 2026-07-08. Chưa có CLI nào làm bước reset này (chỉ `reset_stale_claims` theo tuổi 7200 s). |
| Dashboard | "Thu nhỏ xuống tray", "Xuất gói chẩn đoán", "Docker · 3 container" | không có | MỚI. |
| Dashboard | Run sống độc lập cửa sổ GUI (plan §0 #1) | không có | MỚI: tiến trình nền/service + "attach" lại. |
| **Results** | Dropdown chọn dataset (3 repo) | cần registry | MỚI. |
| Results | Lọc nhãn/CWE/≥N tool/tier/tìm | `findings` có `label, cwe, cwe_group, n_agree, tier, file_path` | OK (SQL). |
| Results | Chi tiết: diff, đoạn code, message từng tool, in_diff | `findings.diff_parsed`, `raw_findings.message/rule_id/severity`, `finding_in_diff` | OK. |
| Results | Tab "Commit" (role, negative_level, Kamei) | `selected_commits`, `commit_features`, `negative_level()` | OK. |
| Results | "Kiểm tay GOLD": TP/FP/Không rõ + ghi chú → `gold_review.json`, "precision tạm" | không có bảng/field nào | **MỚI** (P3); nên lưu trong DB (bảng `gold_review`) để `export`/`build_gold_set` tận dụng. |
| Results | "Xuất…" | `export --out` + `merge_export.py` | nửa có. |
| Results | "Mở thư mục" | OS | OK. |
| **Settings** | Dung lượng từng mục; "Xoá" pool/clone/cache; xem trước | `clean <repo>` gộp cả 3 vào một lệnh (`cli.py:281–287`), không có xem trước, cần `repo` | MỚI: tách hàm `clean` thành hàm riêng từng mục + dry-run liệt kê. |
| Settings | "Image Docker · Chọn… xoá" | không có | MỚI (`docker image rm`). |
| Settings | "docker volume secjit-m2" | không tồn tại | MỚI (xem Wizard3). |
| Settings | Tab "Docker & tài nguyên", "Profile", "Chế độ chạy (Local/VM)", "Ngôn ngữ" | không có | MỚI; Local/VM = SSH tunnel P4. |

## C. Thao tác vận hành thật (SESSION_CONTEXT) chưa được GUI hoá

| # | Thao tác đã làm thật | Nguồn | GUI hiện có? |
|---|---|---|---|
| 1 | **Kill run → dọn 3 container mồ côi (sonar-scanner, maven, orch-sonar) + gỡ network `orch-sonar-net` → reset commit `building/analyzing` về pending → xoá raw đắt bán phần** → phóng lại | SESSION 2026-07-08 | Chỉ có nút "Dừng an toàn" — không có mục nào về "reset commit mồ côi" / "dọn container" khi phát hiện DB có `building` mà không có tiến trình. |
| 2 | **Nâng số worker giữa chừng** (3→4) = kill + resume với `--workers` khác | SESSION 2026-07-08 | Không. Dashboard nên cho "Đổi số luồng (dừng an toàn + tiếp tục)". |
| 3 | **Resume bằng chuỗi `analyze → relabel → kappa → export`**, KHÔNG dùng `pipeline` | README §3, `resume_skywalking.sh` | Home "Tiếp tục" chỉ là nút; logic chọn tầng resume chưa mô tả. |
| 4 | `scripts/merge_export.py` sau `export` để có `dataset.jsonl/commits.jsonl` | README §6, SESSION 07-04/07-06 | Wizard4 hứa 2 file này như output mặc định — cần gọi script. |
| 5 | `scripts/build_gold_set.py` → `gold_set/{positive,negative}_gold.jsonl + README` per repo + `gold_set_all/` | README §6 | Không có màn nào. Hardcode `/home/scanner/...` (`build_gold_set.py:14`) → phải sửa trước khi GUI dùng. |
| 6 | `scripts/relabel_gold_w7.py` — relabel gold ở W=7 **trên bản sao DB**, chỉ ghi `positive_gold.jsonl` | README §6 | Wizard3 cho sửa LINE_WINDOW thẳng → **ngược quy trình đã chốt** (W=3 cho dataset, W=7 chỉ cho gold_set). Hardcode đường dẫn + TARGETS (`relabel_gold_w7.py:16–30`). |
| 7 | `features <repo> --branch` backfill Kamei cho DB cũ | SESSION 2026-07 (Kamei) | Không. |
| 8 | `kappa` theo category + nhóm CWE (n≥5) | `cli.py:323–331` | Chỉ κ tổng. |
| 9 | Kiểm tay 26 gold + verified-clean đo precision ("việc kế tiếp" nợ từ 2026-07) | SESSION dòng 391, 101 | Có mock trong Results nhưng không backend; không có kiểm tay **negative** (verified-clean) — SESSION yêu cầu cả hai. |
| 10 | Xác minh nhánh bằng `git ls-remote` trước (giraph `trunk`) | CLAUDE.md, SESSION 07-06 | Wizard1 có — OK. |
| 11 | Smoke test `scan --max 3` trên **scratch DB** | CLAUDE.md, SESSION 10-04 | Wizard5 "Chạy thử 3 commit" — cần nói rõ DB tạm, không ghi vào DB thật. |
| 12 | `sysctl vm.max_map_count=262144` cho Sonar (reset sau reboot) | SESSION dòng 27/153, CLAUDE.md | Preflight không có mục này. |
| 13 | Docker Desktop **tắt khi máy treo** vì build Maven + Sonar cùng lúc (RAM) | SESSION 10-04 | Preflight đo RAM host; chưa đo **giới hạn RAM WSL2 (`.wslconfig`, mặc định 50% RAM)** — đây mới là trần thật của container. |
| 14 | Horusec image `:latest` chưa pin | CLAUDE.md | Preflight "9/9 image có sẵn" không cảnh báo image trôi phiên bản → ảnh hưởng tái lập. |
| 15 | Chạy nền `setsid nohup … < /dev/null &` để sống độc lập phiên | README §2, SESSION 07-07 | Plan có yêu cầu (§0 #1) nhưng kiến trúc §1 (backend cùng tiến trình GUI) **mâu thuẫn**: đóng GUI = chết run. |
| 16 | Sonar bắt buộc `sonar.java.libraries=/m2 jar` (thiếu → 0 finding) | CLAUDE.md | Dashboard nên cảnh báo "Sonar 0 finding liên tiếp" như tín hiệu lỗi. |
| 17 | Chọn repo theo tiêu chí: app thuần, không SNAPSHOT nội bộ, có `SecurityConfig` | TOOL_IDEA §11 | Wizard1 "Maven app thuần, build ~92% ok" là mock; cần check thật: `git show <sha-cũ>:pom.xml` có SNAPSHOT? grep `SecurityConfig`. |

## D. Mâu thuẫn plan/wireframe ↔ code/tài liệu

| # | Plan / wireframe | Code / tài liệu | Hậu quả |
|---|---|---|---|
| 1 | Wizard3 "VOTE_THRESHOLD 2" chỉnh được | `config.py:55` "legacy", chỉ ghi `run_meta` (`cli.py:123`), không dùng gán nhãn | Núm giả. |
| 2 | Wizard3 "LINE_WINDOW 3" chỉnh được; "ảnh hưởng tái lập, ghi vào run_meta" | `LINE_WINDOW` là hằng (`config.py:54`, CLAUDE.md); W=7 chỉ cho gold_set trên bản sao | Phá quy ước dataset W=3; cần env mới + cảnh báo. |
| 3 | Wizard3 chú thích "tham số đồng thuận được ghi vào run_meta" | `run_meta` chỉ lưu vote_threshold, line_window, tools (`sqlite_store.py:80–85`) | GOLD_MIN_EXPENSIVE/NOISE_CWE/branch/suite/sonar port/workers **không** được ghi → không tái lập. |
| 4 | Wizard5 CLI line: `--since/--until`, không có `--max 0` | Không có since/until; mặc định `--max 50` (`config.py:140`) | Lệnh "tương đương" không chạy được / chỉ 50 commit. |
| 5 | Results mock: `application.yml CWE-798 gitleaks + bearer → GOLD` | RULE_GAN_NHAN §4: E=0,C=2 → **silver**; §10 "secret trần ở silver" | Mock vi phạm luật nhãn; cần sửa để demo đúng. |
| 6 | Results mock: `350f6200 CodeQL + FSB + Sonar GOLD` trong dataset train-ticket 2026-07-04 | Run đó `--codeql 0` (SESSION 07-04) — CodeQL chỉ có ở PoC | Số liệu mock không khớp dataset được trích. |
| 7 | Home mock skywalking "162/1519 buggy · 28%" | 162/1519 = 10,7%; 28% là % scan của run 06/07; hàng đợi thật = 5554 (buggy+clean) | Mock lệch. |
| 8 | Dashboard mock: 187 scan = 61 buggy + 91 clean (152) + "cheap-clean 35" | Với `--include-clean` mọi clean vào hàng đợi; 35 còn lại chỉ có thể là "gray" (có finding không CWE) — không phải cheap-clean | Khái niệm negative_level dùng sai. |
| 9 | Wizard1 "323 commit" ngay sau `ls-remote`, "không cần clone" | `ls-remote` không đếm commit; plan §4.4 nói clone nền từ bước 1 | Phải clone hoặc gọi GitHub API. |
| 10 | Preflight "Tải 2,5 GB" / "9/9 image" | FSB + CodeQL phải **build** từ `docker/` (README §1); bộ image thật: 5 rẻ + maven ×4 (temurin 8/11/17/21) + FSB + sonarqube + sonar-scanner-cli + codeql + alpine (clean) = ~13 | Thiếu bước build (phút), đếm sai. |
| 11 | Plan §4.8 "lấy từ SQLite, không cần sửa orchestrator" vs plan §5 "ghi tiến độ JSON lines" | Tầng rẻ không có tổng todo, không có duration/commit → ETA/tốc độ không tính được từ SQLite | §4.8 không đứng vững; cần §5. |
| 12 | Plan §1 backend "cùng tiến trình" với GUI; §0 #1 "run sống độc lập cửa sổ" | — | Tự mâu thuẫn; chọn 1 (tiến trình nền + IPC). |
| 13 | Wizard3 "Giữ cache Maven trong Docker volume" + Settings "docker volume secjit-m2" | `build.py:27` bind mount `.m2cache`; plan §5 ghi là việc *cần làm* | Wireframe vẽ như đã có. |
| 14 | Wizard5 ước tính tầng đắt "2,5 m/commit" | VM ~30 s/commit cache ấm; Windows cold 881 s (SESSION 10-04); skywalking 15–30′/commit | Con số không có nguồn; cần "đo thật trên máy này" như plan nói. |
| 15 | Wizard2 "Bỏ merge commit" là checkbox | `SKIP_MERGE_COMMITS=True` hằng; Kamei bỏ merge | Không tắt được. |
| 16 | Wizard4 "Giữ output thô (+60%)" là checkbox | raw luôn lưu & luôn export | Không tắt được (hoặc cần code). |
| 17 | Settings "Kết quả quét không bao giờ nằm trong danh sách xoá" | `clean --export/--db/--all` xoá export/DB (`cli.py:284–291`) | GUI phải chắc chắn không gọi các cờ này. |
| 18 | TOOL_IDEA §8–9 "toàn bộ trên cloud, local KHÔNG chạy tool" | Plan P1 local-first | Plan tự nhận (§0 #9) nhưng chưa có hành động cập nhật TOOL_IDEA. |
| 19 | Wizard1 "Repo private (PAT)" | `git clone <url>` thuần (`enumerate_commits.py:65`) | Chưa có. |
| 20 | Plan §2 #5 "tự hạ CODEQL_RAM_MB & worker" | Không có control; RAM thật của container = giới hạn WSL2, không phải RAM host | Preflight đo sai đại lượng. |

## E. Top 10 thiếu sót quan trọng nhất (theo ảnh hưởng)

1. **"Dừng an toàn" + reset mồ côi không có backend.** Không có handler SIGTERM; sau kill còn container `maven/sonar-scanner/orch-sonar` + network, commit `building` kẹt 7200 s, raw đắt bán phần nhân đôi audit. → Thêm lệnh `orchestrator stop`/`reset-claims --force` làm đúng 4 bước SESSION 2026-07-08; Dashboard nút "Dừng an toàn" gọi lệnh này; Home phát hiện DB có `building/analyzing` không tiến trình → nút "Dọn & tiếp tục".
2. **Run chết theo cửa sổ GUI** (plan §1 cùng tiến trình vs §0 #1). → Tách backend thành tiến trình nền (Windows service/tray daemon), GUI attach qua localhost; ghi PID + log path vào `runs.json`.
3. **Không có registry run** → Home "Run gần đây", Results dropdown, Resume đều không có nguồn. → `runs.json` (repo, branch, DB, export, work, env đầy đủ, started/finished, trạng thái) + ghi thêm branch/env vào `run_meta`.
4. **`dataset.jsonl/commits.jsonl` không do `export` sinh** → Wizard4 hứa sai. → Gộp `scripts/merge_export.py` vào `cmd_export`, rồi GUI chỉ gọi `export`.
5. **Chọn tool rẻ / tool đắt qua `pipeline` không có đường** (`CHEAP_TOOLS` hardcode, `pipeline` truyền `tools=None`). → Thêm `--tools`/`--expensive-tools` cho `pipeline`; Wizard3 cảnh báo khi bỏ tool (đổi `eligible`/κ).
6. **`--since/--until`/SHA range chưa có và tương tác với `--max 50`.** → Thêm vào `list_commits`, ép `--max 0` khi dùng; sửa Wizard5 CLI line.
7. **Panel "Nâng cao" sai nửa:** VOTE_THRESHOLD chết, LINE_WINDOW là hằng, thiếu GOLD_ALLOW_1EXP_1CHEAP/SILVER_MIN_CHEAP/NOISE_RULES, `run_meta` không lưu. → Bỏ VOTE_THRESHOLD; thêm `ORCH_LINE_WINDOW` kèm cảnh báo; thêm 3 env; mở rộng `run_meta` lưu toàn bộ `ORCH_*` hiệu lực + branch + lệnh CLI.
8. **Preflight: image FSB/CodeQL phải build, RAM đo sai (WSL2 cap), thiếu `vm.max_map_count`, horusec `:latest`.** → Mục "Build image orch-findsecbugs (~N phút)"; đọc `docker info` MemTotal thay RAM host; tự hạ `ORCH_CODEQL_RAM_MB`; cảnh báo image chưa pin.
9. **Kiểm tay GOLD không có backend và chỉ có positive.** → Bảng `gold_review(cluster_key, verdict, note, reviewer, at)` trong DB, tab thứ hai cho verified-clean; `build_gold_set.py` đọc bảng này; bỏ hardcode `/home/scanner`.
10. **Resume/"Chạy lại" mơ hồ và không theo quy trình chốt.** → Một nút "Tiếp tục" tự chọn tầng theo trạng thái DB; "Chạy lại từ đầu" tách riêng, bắt xác nhận, set `ORCH_SCAN_RESUME=0` hoặc DB mới.

Ngoài top 10: κ theo category/nhóm-CWE, `features` backfill, `relabel` độc lập là 3 năng lực rẻ mà GUI đang bỏ phí — đều đặt được vào tab "Tổng quan" của Results với 1 nút mỗi cái.

---

# PHẦN III — BÁO CÁO TEST (QA/Test Lead)

Kết luận ngắn: wireframe mới vẽ **happy path + 1 trạng thái "pending/fixed" ở Preflight**. 9 màn còn lại là tĩnh, không có trạng thái lỗi/rỗng/partial nào. Plan có **3 mâu thuẫn kiến trúc** với code khiến các lời hứa "chạy nền", "Dừng an toàn", "không trộn DB" chưa thể giữ được (xem F).

## A. Bảng trạng thái × màn hình — những gì wireframe CHƯA vẽ

| Màn | Trạng thái thiếu | Căn cứ / lỗi thật liên quan |
|---|---|---|
| **0 Preflight** | *Đang kiểm tra* (spinner từng dòng — `docker info` treo 10–30 s khi daemon khởi động). *Sửa thất bại* (bật Docker 90 s không lên; pull rớt mạng → % + Thử lại). *Docker RAM limit ≠ RAM vật lý* (WSL2 mặc định ~50 %) — nguyên nhân Docker Desktop tắt khi máy treo. *User chưa trong nhóm docker*. *Ổ WORK_DIR chưa được Docker file-sharing* → mount rỗng. *`vm.max_map_count`* → Sonar không UP sau 6' (`sonar.py:86`). *Proxy/mạng rớt*. *Tiếp tục mặc dù còn ⚠️* không có xác nhận. | Plan §2 #3, #5, #9 |
| **1 Home** | *Rỗng* (chưa có run). *DB đã bị xoá/di chuyển* (cần registry riêng). *Docker tắt* (header hard-code "đang chạy"). *Run "đang chạy" nhưng tiến trình nền đã chết* → phải hiện "Bị ngắt, có thể Tiếp tục". *2 cửa sổ app*. *Thẻ κ* — `cmd_kappa` chỉ `print`, không lưu DB. | |
| **2 Wizard 1** | *Đang kiểm tra* (ls-remote 5–30 s). *Lỗi* 404/401/403 rate-limit GitHub API (nếu dùng API đếm commit). *Repo không có pom.xml / không Java / rỗng*. *Clone đã có nhưng CŨ*: `clone_or_update()` không fetch (`enumerate_commits.py:70–71`). *Git bật Credential Manager* treo sau cửa sổ pywebview; `git clone` không timeout. *Hai repo trùng tên khác org* vào cùng `WORK_DIR/foo` → quét nhầm im lặng. | SESSION 07-06 |
| **3 Wizard 2** | Header "Đang clone nền… 82 %" nhưng số "187 commit / ~61 buggy" cần clone xong → trạng thái "chưa ước tính được". *Clone thất bại*. *Lọc = 0 commit*. *Ước tính "đo trên máy này"* khi lần đầu chưa có số. *Từ > Đến* không validate. `--since/--until` chưa tồn tại. | `cli.py:351–352` |
| **4 Wizard 3** | *Image chưa có → tải* (tiến độ/hủy). *Bỏ chọn tool phá consensus*: bỏ semgrep/bearer → "code" còn 1 tool, `VOTE_THRESHOLD=2` không đạt; bỏ FSB/Sonar → `GOLD_MIN_EXPENSIVE=2` không đạt. `--tools` tầng rẻ không tồn tại. Slider đắt max 4 không khoá theo RAM Docker. LINE_WINDOW editable mâu thuẫn. CodeQL trên máy <20 GB → OOM. | |
| **5 Wizard 4** | *Thư mục không ghi được / UNC / OneDrive* (SQLite corrupt). *DB cùng tên đã tồn tại* → Resume/Đổi tên/Ghi đè. *Đĩa thấp hơn ước tính*. *WORK_DIR = kết quả* (dọn xoá nhầm). *Parquet* cần pyarrow. | |
| **6 Wizard 5** | Ước tính 2,5 m vs 881 s thật → cần cold/warm + dải. Lệnh CLI cú pháp bash không chạy trên PowerShell; `--since/--until` chưa có. "Chạy thử 3 commit" = 3 mới nhất có thể toàn merge/docs → chứng minh 0 điều; không vẽ trạng thái đang thử/kết quả thử. DB đích đang bị run khác mở. | |
| **7 Dashboard** | *Tiến trình nền đã chết*. *Docker tắt giữa chừng* → mọi commit sau thành `build_failed` ghi như DỮ LIỆU (`build.py:101–110`) → DB ô nhiễm; cần phát hiện N fail liên tiếp → tự dừng. *Đĩa đầy* bị nuốt (`expensive_runner.py:128–133`). *Dừng an toàn đang chạy / cưỡng bức / còn mồ côi*. *Mất kết nối GUI↔backend*. Thanh ① mẫu số 187 không lưu DB. Poll SQLite 2 s không WAL → "database is locked". Tray: đóng cửa sổ → hỏi. | SESSION 07-07/07-08 |
| **8 Results** | *Rỗng / chưa relabel*. *Run dở*. *DB đang bị ghi*. *20 k dòng* loading. *Kiểm tay GOLD khoá theo gì?* `replace_findings_for_commit` DELETE+INSERT → row id đổi sau relabel → review mất liên kết; cần khoá `(commit, file, nhóm-CWE, dòng)`. *Diff GBK*. *Export thất bại / thư mục đã có dữ liệu cũ* (`export_dataset.py:37–44` không dọn). | |
| **9 Settings** | *Đang tính dung lượng*. *Xoá thất bại* (read-only; `cmd_clean._rm` không chmod). *Xoá khi run đang chạy* (pool đang dùng!). *Xoá image đang dùng*. *Docker volume `secjit-m2`* chưa tồn tại. Tab Local/VM, Profile, Ngôn ngữ chỉ là tên. | |

## B. Test case luồng chính (Given / When / Then)

**TC-01 Happy path (train-ticket `--max 20`)** — Then: 3 thanh tăng, log `[wN] <sha> -> done`, toast + "Mở kết quả"; BE: exit 0, `run_meta` 1 hàng, không còn pending/building, export có `dataset.jsonl`+`commits.jsonl` (hiện phải gọi `merge_export.py`).

**TC-02 Docker daemon chưa chạy** — spinner + đếm ngược 90 s; quá hạn → ❌ hướng dẫn; BE poll `docker info` 3 s/lần, không treo UI.

**TC-03 Port 9000 bị chiếm** — đề xuất 9100 **ghi vào profile**; BE phải set `ORCH_SONAR_PORT` **trước khi import orchestrator** (HOST_API tính lúc import, `sonar.py:34`).

**TC-04 RAM Docker thấp hơn RAM vật lý** — tính theo `docker info MemTotal`, đề xuất 1 luồng, cảnh báo >80 %; từ chối Run nếu CodeQL và `CODEQL_RAM_MB` > MemTotal×0.8.

**TC-05 Chọn sai nhánh (giraph `trunk`)** — chỉ chọn từ ls-remote; `resolve_rev` trả chuỗi sai → `CalledProcessError` phải được dịch.

**TC-06 Clone cũ, repo có commit mới** — GUI "clone cũ, cập nhật?"; BE thêm `git fetch --all --prune`.

**TC-07 Hai repo trùng tên** — phát hiện `origin` khác → bắt đổi; đặt tên clone `owner__repo`.

**TC-08 Resume ngay sau Dừng an toàn** — `reset_stale_claims(7200)` bỏ qua commit `building` 2 giờ → Dừng phải reset `older_than_sec=0` theo `claimed_by` + xoá raw đắt bán phần.

**TC-09 Dừng an toàn trên Windows** — không có SIGTERM; orchestrator không có signal handler; container không `--name`/`--label` → không dọn được; cần `--label orch.run=<id>`, `stop_server` trong `finally` cả khi kill.

**TC-10 Docker tắt giữa tầng đắt** — ≥3 `build_failed` <10 s → tự tạm dừng; không ghi `build_failed` khi rc=125/127 hoặc "Cannot connect to the Docker daemon".

**TC-11 Đĩa đầy** — bắt `OperationalError disk is full` → dừng; `shutil.disk_usage` mỗi 30 s.

**TC-12 Đóng cửa sổ khi đang chạy** — hộp "Chạy nền / Dừng / Huỷ"; run phải là tiến trình `DETACHED_PROCESS` + pid-file. Plan §1 cùng tiến trình → chết run.

**TC-13 2 cửa sổ / 2 run** — mutex app + lock theo DB + lock Sonar; hiện `start_server` `rm -f orch-sonar` giết Sonar của run A; 2 scan cùng DB `reset_cheap_scan` xoá raw của nhau.

**TC-14 Repo private, PAT sai** — 401 rõ, không hiện Credential Manager; `GIT_TERMINAL_PROMPT=0`, timeout 60 s; PAT qua `http.extraheader`, không vào `run_meta`/CLI.

**TC-15 Semgrep timeout flaky** — cột "tool lỗi"; ghi raw rỗng + lý do; kappa loại tool khỏi rater commit đó; nút "Quét lại commit này".

**TC-16 Commit chỉ đụng yml vào tầng đắt** — `build_commit` ok với `classes_dirs=[]` → tool `[]` status ok → `negative_level` = **verified-clean GOLD** dù không phân tích gì. Cần `status='skipped'`.

**TC-17 Sonar fail, FSB ok trên clean** — `negative_level` chỉ cần 1 `analyze ok` → GOLD negative 1 tool trái "GOLD = ≥2 tool". Cần cột `n_expensive_ok`.

**TC-18 Chạy thử rồi chạy thật cùng DB** — `run_meta` 2 hàng; smoke phải dùng scratch DB.

**TC-19 Pool rác read-only** — `cmd_clean._rm` không chmod, fallback cần Docker → thất bại im lặng; dùng `repo_pool._rmtree`.

**TC-20 Export lại sau đổi NOISE_CWE** — `export_all` chỉ `mkdir(exist_ok)` → commit cũ còn sót → dataset trộn.

**TC-21 `vm.max_map_count` thấp trong WSL2** — đọc `docker logs orch-sonar` tìm `max virtual memory areas`, đề xuất `wsl -d docker-desktop sysctl -w vm.max_map_count=262144`.

## C. Edge case nhập liệu

**URL**: `/tree/main` → name=`main` clone fail (chuẩn hoá + điền nhánh); `/commit/<sha>`, `/pull/123`, `/blob/` → tách repo; `git@github.com:` → SSH prompt treo vô hạn (chuyển HTTPS hoặc từ chối); khoảng trắng/hoa/`http://` → normalize; GitLab/Bitbucket → chỉ github.com ở MVP; repo không Java → tắt tầng đắt (tránh verified-clean giả); repo rỗng → chặn ở Wizard 2; monorepo lồng → hiện submodule tốn mạng; >10 k commit → ước tính clone riêng.

**Ngày**: Từ > Đến chặn ngay; quyết `author-date` vs `committer-date` ghi `run_meta`; Đến tương lai = HEAD; ngoài lịch sử → 0 commit chặn mềm; múi giờ ISO/UTC.

**N commit**: `N=0` hiện là "quét hết" → cấm trong radio "N gần nhất"; N<0/1e9/chữ validate; N tính **trước** lọc merge (50 → 29 thực quét) → phải nói rõ.

**Khoảng SHA**: không tồn tại / mơ hồ / nhánh khác / ngược chiều / tag → `git rev-parse --verify` trước Tiếp.

**Đường dẫn**: dấu nháy đơn (chính repo này), unicode, khoảng trắng, >260 ký tự (`core.longpaths` chỉ sửa git, không sửa Python → cần `\\?\` hoặc WORK_DIR ngắn), UNC cấm, OneDrive cảnh báo, không quyền ghi test `os.access`, đĩa đầy so ước tính ×1.5, kết quả trùng/con của WORK_DIR, ổ không được Docker share.

**Số luồng**: rẻ > CPU → 8 luồng = 40 container (clamp `cpu_count`); đắt > RAM Docker/3 GB chặn; `--workers` = số clone pool → đĩa thêm; analyze không clamp theo todo.

## D. Rủi ro dữ liệu & cách GUI phải chặn

| Rủi ro | Bằng chứng | GUI/BE phải làm |
|---|---|---|
| Trộn 2 repo 1 DB | không kiểm tra; `cmd_relabel` dùng `args.repo` cho mọi commit | `SELECT DISTINCT repo FROM run_meta` phải = URL chuẩn hoá; khác → chặn cứng |
| Ghi đè DB cũ | tên theo ngày → cùng ngày trùng; không migrate schema | Resume / Đổi tên / Ghi đè (gõ tên + `.bak`); kiểm `PRAGMA user_version` |
| Resume vào DB khác cấu hình | `run_meta` chỉ 6 trường | `config_snapshot` JSON + `app_version`; diff khi Resume; mục ảnh hưởng nhãn → chặn, chỉ cho "Relabel toàn bộ" |
| `LINE_WINDOW` editable | hằng số | bỏ khỏi UI hoặc bắt DB mới |
| Verified-clean giả | TC-16/17 | hiện `n_expensive_ok`, sửa BE trước |
| Xoá nhầm kết quả | `clean --export` xoá `EXPORT_DIR` không phải `--out`; `--db` không hỏi | GUI không gọi 3 cờ này; xoá đúng path đã liệt kê; khoá khi run sống |
| Mất `run_meta` | `--no-meta` | GUI không bao giờ truyền; lưu `profile.json` + `preflight.json` + digest cạnh DB |
| Lệnh CLI không chạy được | cú pháp bash; cờ chưa có | sinh PowerShell + bash hoặc `--profile`; test parse bằng argparse thật |
| Kiểm tay mất liên kết | DELETE+INSERT | khoá hash(`repo, commit, file, cwe_group, s_line//W`) |
| Export trộn | không dọn dir | export vào `export_<repo>_<run_id>` |
| PAT lọt DB | `run_meta.repo` = URL thô | token qua env, redact |
| Poll hỏng ghi | không WAL | `PRAGMA journal_mode=WAL`, GUI `mode=ro` |

## E. Chiến lược kiểm thử đề xuất (6 tầng)

1. **Unit** (không Docker, windows+ubuntu): `as_posix()` mọi path vào `docker run` (có `'`, khoảng trắng, unicode); đặt tên clone theo bảng URL; `negative_level` với `classes_dirs=[]`/1 tool/2 tool; `reset_stale_claims(0)` theo `claimed_by`; `run_meta` round-trip; `_rmtree` read-only; `errors="replace"` GBK.
2. **Contract CLI↔GUI**: profile → argparse parse; env → config (`ORCH_SONAR_PORT` trước import); `--dry-run` cho scan/pipeline (cần thêm); schema JSON-lines progress; golden DB 3 commit → Results đúng số.
3. **Smoke "Chạy thử 3 commit"**: 3 commit đầu qua lọc có đụng Java; scratch DB; kiểm `expensive_runs` có `analyze ok n_findings>0`; đo tốc độ thật nạp vào estimate; sau smoke `docker ps --filter label=orch.run` = 0, `pool_*` = 0.
4. **Máy sạch** (VM Win11 không Docker/Git): đúng 2 ❌, không traceback, không admin, SmartScreen hướng dẫn; 8 GB RAM → đề xuất "chỉ rẻ + FSB".
5. **Chaos**: kill python giữa build → Resume không nhân đôi row; `docker stop` Sonar; `wsl --shutdown`; rút mạng khi pull; `fsutil` đổ đầy đĩa.
6. **CI**: `windows-latest` lint+unit+contract+PyInstaller+`--preflight --json`; `ubuntu-latest` smoke rẻ+FSB; nightly self-hosted Windows smoke đầy đủ + chaos; hồi quy train-ticket `--max 20` ± dung sai.

## F. Top 10 lỗ hổng nghiêm trọng nhất

1. **Run chết theo cửa sổ GUI** (plan §1 vs §0.1). Chặn phát hành.
2. **"Dừng an toàn" chưa có nền tảng**: không signal handler, Windows không SIGTERM, container không `--name`/`--label`, `stop_server` không chạy khi kill, `reset_stale_claims` 7200 s. Chặn P2.
3. **Verified-clean GOLD giả** (`negative_level` 1 tool ok, `classes_dirs=[]`). Sai dữ liệu luận văn.
4. **Docker tắt → DB ô nhiễm `build_failed`** (mọi rc≠0 là dữ liệu).
5. **Không khoá chống 2 run** (Sonar tên hằng + `rm -f`; 2 scan cùng DB).
6. **`run_meta` không đủ tái lập**; CLI tương đương cú pháp bash + cờ chưa có. Vi phạm §12.3.
7. **Preflight đo RAM vật lý thay RAM Docker**; `CODEQL_RAM_MB=20000`.
8. **Clone cũ không fetch + trùng tên khác org**.
9. **Dọn dẹp tựa trên `cmd_clean` nguy hiểm** (`--export` xoá `EXPORT_DIR`, `--db` không hỏi, `_rm` không chmod).
10. **Ước tính bịa và smoke không chứng minh gì** (12 s/2,5 m vs 881 s; `--max 3` có thể 0 Java; Sonar vẫn khởi động 2 phút cho hàng đợi rỗng).

Quyết ngay ở P0: (a) LINE_WINDOW không editable; (b) bỏ Parquet, CSV stdlib.

---

# PHẦN IV — BÁO CÁO PO (Product Owner)

**Ba sự thật trong code làm nền:** (1) `run_meta` chỉ ghi ở tầng `scan`, 6 trường, chỉ 5 tool rẻ; tầng đắt không ghi version/digest; κ chỉ print; export không kèm run_meta. (2) CLI chưa có `--since/--until`, SHA range, `--tools` rẻ, `estimate`. (3) `LINE_WINDOW=3` là hằng số.

## A. Persona & job-to-be-done

| Persona | Job | GUI cần gì | Wireframe phục vụ |
|---|---|---|---|
| **P1 Tác giả luận văn** | trả nợ kiểm tay gold + precision; chạy repo không chết theo phiên; bảng per-CWE/per-repo + sensitivity; đóng gói dataset | Kiểm tay GOLD đúng phương pháp, so sánh 2 run, thống kê, resume/dừng an toàn. Wizard/preflight gần như không cần | **Trung bình**: 6/10 màn là vỏ vận hành P1 không cần; 2 màn giá trị (Results, Dashboard) thiếu phần quan trọng |
| **P2 Hội đồng demo 10 phút** | hiểu phễu → nhãn 3+2 mức → bằng chứng 1 gold → κ âm nghĩa gì → tin được bao nhiêu → tái lập thế nào | 1 màn Tổng quan kể chuyện; 1 màn Bằng chứng; 1 nút "Chạy thử 3 commit" sống | **Kém nhất**: tab Tổng quan rỗng; không giải thích thang nhãn, `eligible`, κ nhóm CWE, threats; chữ "GOLD" không chú thích |
| **P3 Nhà nghiên cứu tái lập** (Linux) | `dataset.jsonl` + `commits.jsonl` + manifest → chạy lại ra cùng số | `profile.json` + `run_manifest.json` (digest mọi image, tham số, git-sha, seed), **không phải** `.exe` | **Sai artefact**: exe Windows + Docker Desktop + WebView2 là tổ hợp khó tái lập nhất |

Wireframe đang tối ưu cho persona thứ tư ("người không biết Python") — **không có trong luận văn**.

## B. Đánh giá 10 màn hình

| # | Màn | Giá trị P1/P2/P3 | Thừa (bỏ MVP) | Thiếu / sai | Cỡ |
|---|---|---|---|---|---|
| 0 | Preflight | thấp / **âm** / thấp | WSL2, Git/winget, WebView2, AV, longpaths → README | không kiểm digest image đúng dataset công bố; tải 2,5 GB không hỏi mạng | M |
| 1 | Home | TB / thấp / 0 | batch, dung lượng lặp Settings | badge mức bằng chứng (gold đã kiểm x/y); "Chạy lại" mở wizard mới = mất tái lập | S–M |
| 2 | Wizard 1 | thấp / thấp / thấp | PAT | check tiêu chí chọn repo (SNAPSHOT pom cũ, `SecurityConfig`); "92 %" không suy ra được | M |
| 3 | Wizard 2 | thấp / 0 / thấp | biểu đồ kéo chọn, SHA, "33 %" | `--since/--until` chưa có; "Bỏ merge" không nên tùy chọn; thiếu `CLEAN_PER_BUGGY`, `--require-in-diff` | M/S |
| 4 | Wizard 3 | TB / cao nếu demo phễu / thấp | suite CodeQL, slider rẻ | **vi phạm §12.7/§12.9**: sửa LINE_WINDOW/VOTE/GOLD_MIN trước chạy; ẩn `GOLD_ALLOW_1EXP_1CHEAP` (109/208 gold csrf train-ticket là 1 đắt + 1 rẻ); bỏ tool đổi `eligible` không cảnh báo | M |
| 5 | Wizard 4 | thấp / 0 / thấp | **Parquet** (phá stdlib), toast, tự xoá clone | kèm `run_manifest.json` + checksum; raw bắt buộc, không checkbox | S |
| 6 | Wizard 5 | **cao** / TB / **cao nhất wizard** | — | CLI dùng cờ chưa có; thiếu git-sha, digest, hash profile; smoke phải DB scratch; 2,5 m là số VM | S–M |
| 7 | Dashboard | **cao** / cao / thấp | tray, bộ đếm finding theo tool | detached process; chuỗi Dừng an toàn thật; **ẩn nhãn tạm khi chạy** (mời dừng để chỉnh) | L |
| 8 | Results | **cao nhất** / **cao nhất** / TB | tab Commit/Xuất chưa định nghĩa | **Tổng quan trống**; Kiểm tay GOLD 3 lỗi: precision tạm (anchoring), không mù, chấm theo thứ tự bảng thay vì mẫu phân tầng; không rater 2; thiếu link raw SARIF/XML; thiếu filter `finding_in_diff` | L |
| 9 | Settings | TB / 0 / 0 | tab Local/VM, Ngôn ngữ, Profile rỗng | "Đóng băng phương pháp luận"; dọn → CLI `clean --out --dry-run` trước | M |

Tổng ~22–30 ngày-dev cho đúng những gì vẽ, chưa tính plan §5 và packaging.

## C. Yêu cầu học thuật chưa thể hiện

| # | Yêu cầu | Cần làm |
|---|---|---|
| C1 | Provenance mỗi nhãn (§12.3) | `analyze` ghi `run_meta` tầng đắt (image FSB/Sonar/CodeQL/maven per-commit); cột `orchestrator_git_sha`, `config_json`, `branch`, `include_clean`, `clean_per_buggy`; export `run_manifest.json` + sha256; panel finding hiện "sinh bởi run #k, FSB 1.14.0@sha256:…, W=3, rule 1E+1C" |
| C2 | Mức ground truth trung thực (§11.7, §12.8) | UI: `gold` → "gold · đồng thuận máy (chưa kiểm tay)" / "gold ✓ kiểm tay TP"; `verified-clean` → "(2 tool đắt sạch, không có nghĩa không có lỗi)"; mỗi bảng 1 dòng "precision đo trên mẫu kiểm tay n=…" |
| C3 | Threats to validity viết trước (§12.4) | Tab Tổng quan: khối "Giới hạn dataset" **tự sinh** từ run: % build_failed, secret trần ở silver, FP CWE-117 lọc, tool correlated, flakiness semgrep, bias CWE cheap-tier |
| C4 | Không tinh chỉnh theo kết quả (§12.7, §12.9) | **Phương pháp luận đóng băng**: mặc định khoá (W=3, 1E+1C, SILVER=2, NOISE=CWE-117); đổi → "Chế độ thí nghiệm", bắt lý do, tag `experiment=true`, export `_exp_<tên>`, không gộp `gold_set_all` |
| C5 | κ âm giải thích cho hội đồng | lưu κ DB + export; κ theo nhóm CWE + pairwise/Jaccard; biểu đồ coverage 1/2/≥3 tool; đoạn giải thích chuẩn; hiện κ ở W=3 và W=7 cạnh nhau |
| C6 | Sensitivity (§12.9) | CLI `sensitivity --param LINE_WINDOW=3,5,7 --param GOLD_ALLOW_1EXP_1CHEAP=0,1` trên **bản sao** DB → bảng; GUI chỉ hiển thị |
| C7 | Export kèm metadata | `run_manifest.json`: profile, run_meta 2 tầng, κ, đếm nhãn, git-sha, OS/Docker, **danh sách build_failed**; "Sao chép lệnh CLI" sinh từ profile |
| C8 | Thống kê per-CWE/per-repo | `stats` subcommand: CWE-group × nhãn × tier × in_diff; per-repo; xuất CSV/LaTeX |
| C9 | Kiểm tay đúng giao thức | mẫu ngẫu nhiên phân tầng CWE-group × tier (seed ghi file); **mù** (ẩn nhãn/tool); không hiện precision tới khi đóng phiên; 2 rater (`gold_review_<rater>.json`) + Cohen κ + adjudication; chấm cả verified-clean |
| C10 | Flakiness | manifest ghi timeout/tool lỗi per-commit; Tổng quan "n commit có tool timeout" |

## D. MoSCoW

**Định nghĩa MVP xong:** demo 10 phút trên laptop với dataset có + 1 run `--max 3` sống; người khác từ `profile.json` + manifest chạy lại train-ticket **cùng phạm vi** ra cùng số. Lưu ý: 881 s/commit → tiêu chí tái lập laptop nên là **`--max 30`**, full-history trên VM.

**MUST (~28 ngày):** M1 provenance đầy đủ + manifest (2) · M2 profile + `--profile` + since/until (2) · M3 đóng băng phương pháp luận (1) · M4 preflight 5 mục (2) · M5 wizard thu gọn 2 màn + preset tool (3) · M6 run nền detached + Dashboard tối thiểu + Dừng an toàn + Resume (5) · M7 Results Finding + Bằng chứng + raw + provenance (4) · M8 Tổng quan (phễu, nhãn, per-CWE, κ, giới hạn) từ `stats` (3) · M9 Kiểm tay GOLD đúng giao thức (3) · M10 đóng gói + test máy sạch (3). Cắt M10 → chạy `python -m secjit_gui` tiết kiệm 3 ngày, loại rủi ro SmartScreen/AV.

**SHOULD:** `estimate` từ tốc độ đo; dọn dẹp qua CLI `clean --out --dry-run`; `sensitivity` CLI; gói chẩn đoán; check tiêu chí repo; CSV stdlib; EN cho Tổng quan/Results.

**COULD:** biểu đồ mật độ; SHA range; toast; Docker volume cache (3–5×); toggle CodeQL/suite; batch; chấm verified-clean.

**WON'T (MVP):** VM SSH (P4) — nếu làm P4 thì gần như không cần P1–P3; PAT; Parquet; auto-update, ký code, tray, VI/EN toàn app; sửa LINE_WINDOW/VOTE trong wizard; bật/tắt bỏ merge; nhãn tạm khi đang chạy.

## E. 8 user story (tóm tắt AC)

- **US-1 Tái lập từ profile** (P3): `pipeline --profile` kiểm digest mọi image khớp manifest; chênh lệch liệt kê theo commit kèm lý do; manifest có git-sha, tham số resolved, branch, include_clean, κ, sha256.
- **US-2 Preflight tự sửa** (P1/P2): Docker lên ≤90 s hoặc lỗi cụ thể; port trống ghi vào profile; pull có % và huỷ được.
- **US-3 Chạy nền, mở lại gắn vào** (P1): đóng GUI run vẫn chạy; Home liệt kê "đang chạy"; reboot → "dở" + Tiếp tục = `analyze → relabel → kappa → export`, đã reset claim mồ côi.
- **US-4 Dừng an toàn** (P1): ≤60 s không còn container/network của run, commit về pending, raw bán phần xoá, không row lặp; liệt kê đã dọn.
- **US-5 Bằng chứng 1 gold** (P2): diff tô dòng, `in_diff`, tool + rule + severity, `eligible`, nút mở raw từng tool, provenance; nhãn luôn "gold · đồng thuận máy" hoặc "gold ✓ kiểm tay".
- **US-6 Kiểm tay mù có seed** (P1): mẫu phân tầng lưu `gold_sample_<seed>.json` tái lập; ẩn nhãn/tool/precision khi chấm; đóng phiên → precision + Wilson CI; 2 rater → Cohen κ + bất đồng.
- **US-7 Tổng quan hội đồng** (P2): phễu số, nhãn 3+2 mức, CWE-group × nhãn, κ tổng/nhóm/pairwise, precision kiểm tay hoặc "n=0"; khối Giới hạn tự sinh; xuất CSV/LaTeX.
- **US-8 Export manifest, không trộn repo** (P1/P3): từ chối ghi DB đã có repo khác; export có manifest, jsonl, `SHA256SUMS`, raw; `build_gold_set.py` đọc được.

## F. Rủi ro & câu hỏi mở

1. **GUI `.exe` hay CLI tốt + viewer local?** Giá trị thật ở 2 màn đọc SQLite. Phương án rẻ hơn ~60 %: `secjit-review` viewer + CLI `--profile/stats/sensitivity/manifest`. Mục tiêu "người không biết Python" có trong luận văn không?
2. **Docker Desktop**: license, WSL2, Defender, tự tắt khi treo — ngoài tầm kiểm soát app. Chấp nhận là điều kiện ngoài?
3. **Hiệu năng Windows**: tiêu chí tái lập `--max 30` laptop hay full VM (→ P4 quan trọng hơn P1)?
4. **Phạm vi luận văn phình**: hội đồng chất vấn chất lượng nhãn D1, không chất vấn exe. 28 ngày GUI = 28 ngày không kiểm tay/sensitivity/Threats.
5. **Stdlib-only bị phá**: lớp GUI có dependency, orchestrator stdlib; bỏ Parquet.
6. **"GOLD" va với §11.7**: đổi `consensus-high/-mid/-low` hay giữ + chú thích bắt buộc?
7. **Chính sách tham số**: khoá mặc định, đổi chỉ qua `sensitivity`; cần Claude #1 xác nhận (§10.7 bất biến mềm).
8. **Kiểm tay 1 người** = self-labeled; kiếm rater 2 (~100–200 mẫu)? Tối thiểu mù + seed + công bố file chấm.
9. **Bảo trì sau luận văn**: exe vỡ theo Docker/WebView2/Windows update; artefact công bố nên là Docker image + CLI + manifest.
10. **Dọn mâu thuẫn tài liệu**: cập nhật `TOOL_IDEA_CONTEXT.md` §8–9 trước khi mở P1.

**Khuyến nghị PO:** chốt phương án (1): tuần 1–2 M1/M2/M3 + `stats`/`sensitivity` ở CLI; tuần 3–4 viewer 2 màn (M7/M8/M9) đọc SQLite; chỉ sau khi có precision kiểm tay và bảng per-CWE mới quyết có bọc thêm Preflight/Wizard/exe hay không.
