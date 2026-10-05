# tool-scan-commit

Orchestrator xây **ground-truth dataset lỗ hổng bảo mật** từ lịch sử Git: 1 link GitHub →
duyệt từng commit → chạy nhiều tool SAST (Docker) → chuẩn hoá về finding `(file, dòng, CWE, tool)`
→ gom cụm + bỏ phiếu theo tầng → xuất dataset có nhãn **gold / silver / candidate** + mẫu âm
**verified-clean / cheap-clean**. Nhãn = **CWE-class** (không phải CVE).

> **Đọc trước khi làm (bắt buộc cho Claude/AI mới):**
> - `CLAUDE.md` — quy ước làm việc + môi trường VM + gotcha (đọc ĐẦU mỗi phiên).
> - `TOOL_OUTLINE.md` — toàn cảnh pipeline cho người mới (input/output từng bước, quy tắc nhãn, giới hạn).
> - `SESSION_CONTEXT.md` — tiến độ hiện tại / việc đang dở (phiên mới nhất ở TRÊN CÙNG).
> - `TOOL_IDEA_CONTEXT.md` — quyết định kiến trúc.

---

## 1. Yêu cầu môi trường
- **Python 3.10+** — orchestrator chỉ dùng **stdlib**, KHÔNG cần pip install.
- **Docker** (daemon active) — mọi tool SAST chạy trong container.
- **Chạy CLI:** từ gốc repo với `PYTHONPATH=src` (mọi lệnh dưới đây theo mẫu này).
- **Docker image cần có** (build/pull trước; tầng đắt cần chúng):
  - `orch-findsecbugs:1.14.0` — build từ `docker/findsecbugs/` (SpotBugs + Find Security Bugs).
  - `orch-codeql:2.25.6` — build từ `docker/codeql/` (chỉ cần nếu bật `--codeql 1`).
  - `sonarqube:lts-community` + `sonarsource/sonar-scanner-cli` — pull sẵn.
  - `maven:3.9-eclipse-temurin-{8,11,17,21}` — pull sẵn (auto-detect JDK theo pom mỗi commit).
- **Gotcha (xem CLAUDE.md để đầy đủ):**
  - Nếu `id` không thấy nhóm `docker` → bọc lệnh qua `sg docker -c "..."` HOẶC đặt `ORCH_DOCKER_SG=1`.
  - SonarQube cần `sysctl vm.max_map_count>=262144` (cần sudo, reset khi reboot).
  - `sudo` trên VM đòi mật khẩu → nhờ người dùng gõ `! <lệnh>` trong chat.

---

## 2. Chạy TRỌN pipeline (1 lệnh, 6 tầng)

### 2.0 Chạy bằng GUI / exe (desktop) hoặc profile
- **GUI (dev):** `python -m gui` (thêm `--mock` để xem màn với fixture, `--dev` cổng cố định) — pywebview + web UI tĩnh.
- **exe (PyInstaller, build `./build_exe.ps1 -Clean` → `dist/`):**
  - `dist/secjit-scan.exe` (console): `--version` · `--preflight --json` · `--profile F` (chạy pipeline headless)
    · `--cli <subcommand …>` (= `python -m orchestrator.cli …`) · `-m <module> …` (runpy) · `--dev` (GUI cổng cố định).
  - `dist/secjit-scan-gui.exe` (noconsole, không stdout): `--port N` cố định; fallback mở trình duyệt nếu pywebview lỗi.
  Mọi hành động GUI = 1 lệnh CLI `pipeline --profile <profile.json>` chạy nền (`runner.start`), tiến độ qua `progress.jsonl`.
- **Profile:** `profile.json` (CONTRACTS.md §2) = repo + nhánh + phạm vi + tool + đường dẫn + `params_v1`.
  ```bash
  PYTHONPATH=src python -m orchestrator.cli pipeline --profile D:/secjit/profiles/train-ticket.json
  PYTHONPATH=src python -m orchestrator.cli estimate --profile D:/secjit/profiles/train-ticket.json --json
  ```
  `--profile` nhận ở mọi subcommand; áp env `ORCH_*` từ profile **trước** khi đọc config và **bỏ qua mọi arg khác**
  (cảnh báo). Lệnh PowerShell/bash tương đương: `profile.to_shell()` (GUI hiện ở Wizard 5).
- **Gotcha Git Bash (Windows):** MSYS tự đổi `/m2`, `/work` trong `-v …:/m2` thành `C:/Program Files/Git/m2` →
  đặt `MSYS_NO_PATHCONV=1` hoặc dùng PowerShell. Đường dẫn repo có dấu `'` → luôn quote (`cd "D:/Master's thesis"`).

### 2.1 CLI thuần (VM/Linux)

```bash
cd /home/scanner/tool-scan-commit
ORCH_SQLITE=data/dataset_<tên>.sqlite \
ORCH_EXPENSIVE_WORKERS=4 \
PYTHONPATH=src python3 -m orchestrator.cli pipeline <github_url> \
    --max 0 --branch <nhánh> --codeql 0 --include-clean --out data/export_<tên>
```

- `--max 0` = quét TOÀN BỘ lịch sử (số dương = N commit mới nhất).
- `--branch` = nhánh cần quét (xác minh bằng `git ls-remote` trước — nhiều repo dùng `master` chứ không `main`).
- `--codeql 0` = tắt CodeQL (nhanh; mặc định bật, ~6-7'/commit). `--include-clean` = quét cả commit sạch ở tầng đắt để tạo **verified-clean GOLD negative**.
- Phạm vi khác: `--since 2024-01-01 --until 2024-06-30` (committer-date) hoặc `--from-sha A --to-sha B` — có chúng mà bỏ trống `--max` → tự ép `--max 0`.
- Chọn tool: `--tools semgrep,bearer` (rẻ) · `--expensive-tools findsecbugs,sonar` (đắt) — bỏ tool đổi mẫu số `eligible`/κ (CLI cảnh báo).
- **QUAN TRỌNG — mỗi repo 1 DB + 1 export RIÊNG** (`ORCH_SQLITE` + `--out`). KHÔNG trộn repo trong 1 DB (relabel/select sẽ trộn commit).

6 tầng chạy tuần tự: **① SCAN** (tool rẻ, toàn lịch sử) → **② SELECT** (chọn commit vào tầng đắt) →
**③ ANALYZE** (build Maven + FindSecBugs + Sonar) → **④ RELABEL** (gộp cụm + gán nhãn) →
**⑤ KAPPA** (Fleiss' kappa) → **⑥ EXPORT** (jsonl + audit).

### Chạy nền độc lập phiên (khuyến nghị cho repo lớn — chạy nhiều giờ/ngày)
```bash
setsid nohup env ORCH_SQLITE=data/dataset_<tên>.sqlite ORCH_EXPENSIVE_WORKERS=4 PYTHONPATH=src \
  python3 -m orchestrator.cli pipeline <url> --max 0 --branch <nhánh> --codeql 0 --include-clean \
  --out data/export_<tên> >> data/pipeline_<tên>.log 2>&1 < /dev/null &
```
Theo dõi: `tail -f data/pipeline_<tên>.log` · kiểm tiến trình: `ps -ef | grep orchestrator.cli`.

---

### 2.2 Nghiệm thu tái lập (Run A ↔ Run B, train-ticket `--max 30`)
```bash
# Run A: CLI với profile
PYTHONPATH=src python -m orchestrator.cli pipeline --profile D:/secjit/profiles/train-ticket.json
# Run B: cùng profile từ exe (hoặc GUI "Chạy lại cùng profile")
dist/secjit-scan.exe --profile D:/secjit/profiles/train-ticket.json
# Kiểm từng run đúng CONTRACTS (DB chỉ-đọc + export): user_version, run_meta, enum status, n_expensive_ok,
# nhãn tính lại theo luật v1, manifest/SHA256SUMS/cluster_key/evidence
PYTHONPATH=src python -m orchestrator.cli verify --db <dbA> --export <exportA>
PYTHONPATH=src python scripts/verify_run.py --db <dbB> --export <exportB> --json
# So A/B theo cluster_key — exit 0 khi khớp hoặc lệch chỉ ở commit tool_timeout/infra_error/skipped của manifest
PYTHONPATH=src python -m orchestrator.cli compare --a <exportA> --b <exportB> --format md
```
Tiêu chí: cùng số cụm theo nhãn; lệch chỉ ở commit được liệt kê trong `run_manifest.json`. Chi tiết: `METHODOLOGY.md` §6.

## 3. Resume khi pipeline dừng/chết (KHÔNG mất công cũ)

Thiết kế bền: **scan** có mốc `scan_done` (env `ORCH_SCAN_RESUME=1` mặc định) bỏ qua commit đã quét;
**analyze** dùng claim nguyên tử + `reset_stale_claims` → chạy lại chỉ vét phần còn thiếu. Nếu tiến trình
`pipeline` chết giữa chừng, KHÔNG chạy lại `pipeline` (tránh scan lại) mà chạy tiếp bằng lệnh con:

```bash
# ví dụ resume từ tầng đắt trở đi:
ORCH_SQLITE=data/dataset_<tên>.sqlite ORCH_EXPENSIVE_WORKERS=4 PYTHONPATH=src \
  python3 -m orchestrator.cli analyze <url> --workers 4 --codeql 0
ORCH_SQLITE=... PYTHONPATH=src python3 -m orchestrator.cli relabel <url>
ORCH_SQLITE=... PYTHONPATH=src python3 -m orchestrator.cli kappa
ORCH_SQLITE=... PYTHONPATH=src python3 -m orchestrator.cli export --out data/export_<tên>
```
Có sẵn `scripts/resume_skywalking.sh` làm mẫu (nối analyze→relabel→kappa→export).

**Dừng an toàn / dọn mồ côi (CLI mới):** `stop --run <id>` tạo stop-file → orchestrator kết thúc commit hiện tại,
không claim mới, exit **3**; `stop --run <id> --force` kill cây tiến trình rồi `stop-cleanup` (rm container
`label=orch.run=<id>`, gỡ network, `reset-claims`). Commit kẹt `building/analyzing` sau crash:
`reset-claims --run <id>` (hoặc `--all-stale`). Exit code: `0` ok · `1` tham số · `2` runtime · `3` stop-file.

---

## 4. Các lệnh con (chạy lẻ từng tầng)
| Lệnh | Việc |
|---|---|
| `enumerate <url> --max N` | Liệt kê + lọc thô commit (KHÔNG cần Docker) |
| `scan <url> --max N --branch B` | Tầng rẻ → consensus → SQLite (có resume) |
| `select [--include-clean]` | Chọn commit buggy + clean vào hàng đợi đắt |
| `analyze <url> --workers K --codeql 0/1` | Tầng đắt: build + FindSecBugs + Sonar (+CodeQL) |
| `relabel <url>` | Gán nhãn LẠI từ raw (đổi ngưỡng/lọc nhiễu, ~vài phút, KHÔNG quét lại) |
| `kappa` | Fleiss' kappa (độ đồng thuận tool) |
| `features <url> --branch B` | Backfill 14 đặc trưng Kamei cho DB cũ |
| `export --out DIR` | Xuất jsonl + thư mục audit mỗi commit + `run_manifest.json` + `SHA256SUMS` (đích không rỗng → `_2`, `_3`…) |
| `estimate --profile F` | Ước tính phút/GB từ `speed.json` đo được (hoặc mặc định) |
| `stats [--db] [--run-id] [--format json\|csv\|latex] [--out DIR]` | Overview (funnel, nhãn, κ tổng/nhóm/cặp, coverage, precision, giới hạn) — DB chỉ-đọc |
| `sensitivity --db DB --out DIR [--grid …]` | Lưới tham số gán nhãn trên **bản sao** DB (W∈{3,5,7}, 1E+1C, noise) |
| `compare --a X --b Y [--format md]` | So 2 run theo `cluster_key`; lệch phải giải thích được bằng manifest (tool_timeout/infra_error/skipped) |
| `stop --run ID [--force]` · `stop-cleanup --run ID` · `reset-claims --run ID` | Dừng an toàn / cưỡng bức, dọn container + network, nhả claim |
| `clean <url> [--items clone,pool,m2,m2volume,export:<dir>,db:<path>] [--dry-run]` | Dọn theo mục; **không còn `--all`**; `m2volume` = `docker volume rm secjit-m2` (dry-run hiện size từ `docker system df -v`); export/db bắt buộc đường dẫn; từ chối khi DB/pool đang dùng |
| `verify --db DB [--export DIR]` | Nghiệm thu run theo CONTRACTS (= `scripts/verify_run.py`); exit 1 nếu có FAIL |
| `review sample\|next\|verdict\|close --db DB …` | Kiểm tay GOLD mù (mẫu phân tầng, 2 rater, Cohen κ, Wilson CI) — METHODOLOGY.md §4 |
| `batch --queue Q.json` | Chạy tuần tự nhiều profile (1 Sonar), `batch_state.json`, dừng theo `<Q>.stop` |
| `diagnostics --run ID --out Z.zip` | Gói chẩn đoán (log, progress, run_meta, docker info/ps, preflight; che token/PAT) |

Mọi lệnh nhận `--json` và `--profile F`. Chi tiết: `GUIDE.md` §2.

---

## 5. Biến môi trường hay dùng
| Env | Mặc định | Ý nghĩa |
|---|---|---|
| `ORCH_SQLITE` | `data/dataset.sqlite` | Đường dẫn DB (đặt RIÊNG mỗi repo) |
| `ORCH_EXPENSIVE_WORKERS` | 2 | Số commit song song ở tầng đắt (~½ vCPU; 4 hợp cho e2-standard-8) |
| `ORCH_SCAN_WORKERS` | 4 | Số commit song song ở tầng rẻ |
| `ORCH_SCAN_RESUME` | 1 | Bỏ qua commit đã quét ở run trước |
| `ORCH_SUBMODULES` | 1 | Init git submodule sau checkout (repo kiểu skywalking cần) |
| `ORCH_JDK_AUTODETECT` | 1 | Chọn image Maven theo `<java.version>` của pom mỗi commit |
| `ORCH_MAVEN_IMAGE` | temurin-8 | Image Maven fallback khi pom không khai JDK |
| `ORCH_SONAR_ADMIN_PW` | `Orch_2026!` | Mật khẩu admin Sonar (đổi từ admin/admin lần đầu qua API) |
| `ORCH_DOCKER_SG` | 0 | =1 để bọc mọi lệnh docker qua `sg docker -c` (gotcha nhóm) |
| `ORCH_DOCKER_BIN` | `docker` | Binary Docker (vd `podman`, hoặc đường dẫn đầy đủ khi `docker` không trong PATH của exe) |
| `ORCH_CHEAP_TOOLS` / `ORCH_EXPENSIVE_TOOLS` | 5 tool rẻ / `codeql,findsecbugs,sonar` | Tool bật theo tầng (CLI `--tools` / `--expensive-tools`) |
| `ORCH_RUN_ID` · `ORCH_PROGRESS_FILE` · `ORCH_STOP_FILE` | `local` · (rỗng) · (rỗng) | Định danh run, `progress.jsonl`, stop-file (runner nền đặt; CONTRACTS §3) |
| `ORCH_EXPERIMENT` · `ORCH_EXPERIMENT_REASON` · `ORCH_LINE_WINDOW` | 0 · (rỗng) · 3 | Chế độ thí nghiệm; `ORCH_LINE_WINDOW` **chỉ** hiệu lực khi `ORCH_EXPERIMENT=1` (METHODOLOGY §3) |
| `ORCH_M2_VOLUME` | 0 | `1` = cache Maven trong Docker named volume `secjit-m2` thay bind mount `.m2cache` |
| `ORCH_INFRA_STOP_AFTER` | 3 | Số `infra_error` liên tiếp trước khi run tự dừng |
| `SECJIT_APP_VERSION` | `dev` | Phiên bản app ghi vào `run_meta`/manifest |

Bảng đầy đủ mọi `ORCH_*`: `GUIDE.md` §3 (khớp `src/orchestrator/config.py`, nạp lại được bằng `config.reload()`).

---

## 6. Output
```
data/
├── dataset_<tên>.sqlite       # DB: raw + findings + commit_features + selected + expensive_runs
└── export_<tên>/
    ├── run_manifest.json      # profile, run_meta 2 tier, kappa, counts, build_failed/infra_error/tool_timeout/skipped, params_v1
    ├── dataset.jsonl          # 1 dòng = 1 CỤM finding (gold/silver/candidate) + cluster_key + evidence{consensus, validation}
    ├── commits.jsonl          # 1 dòng = 1 COMMIT (đủ cả 0-finding; kamei + n_expensive_ok + negative_level) — cho JIT
    ├── SHA256SUMS             # dataset.jsonl, commits.jsonl, run_manifest.json
    └── <commit_sha>/          # audit: <tool>.raw.* + <tool>.findings.json + label.json + summary.json
```
`export` giờ sinh thẳng `dataset.jsonl`/`commits.jsonl`/manifest (không cần `scripts/merge_export.py` nữa — giữ cho DB cũ).
Thuật ngữ nhãn, trường `evidence`, giao thức kiểm tay và tiêu chí tái lập: **`METHODOLOGY.md`**.

### Scripts phụ trợ (`scripts/`)
- `merge_export.py` — gộp thư mục export → `dataset.jsonl` + `commits.jsonl`.
- `build_gold_set.py` — tạo `gold_set/` (positive_gold.jsonl + negative_gold.jsonl + README) cho mỗi repo + `gold_set_all/` gộp toàn dự án.
- `relabel_gold_w7.py` — relabel positive gold ở `LINE_WINDOW=7` (trên bản sao DB, không đụng dataset gốc W=3) — dùng cho repo Java (thân method dài, ±3 quá chặt).
- `resume_skywalking.sh` — mẫu resume tầng đắt (nối analyze→relabel→kappa→export).

---

## 7. Chọn repo pilot (bài học thực nghiệm)
- **Ưu tiên APP Java/Maven thuần** (có SecurityConfig, Docker/k8s) — build được nhiều → tầng đắt phủ rộng → nhiều gold. Ví dụ đã chạy: train-ticket (gold 208), mall-swarm, skywalking.
- **Tránh library kiểu Spring** — dependency `*-SNAPSHOT` biến mất khỏi registry → phần lớn commit build-fail, tầng đắt chỉ phủ được đoạn gần đây.
- **FindSecBugs chậm trên monorepo lớn** (skywalking: có commit tốn tới ~3h FindSecBugs) — cân nhắc `-effort:default` nếu cần tăng tốc (xem SESSION_CONTEXT).

---

## 8. Kết quả đã có (tham khảo quy mô)
5 repo full-history đã xong (dataset trên Persistent Disk VM): train-ticket · mall-swarm ·
spring-cloud-stream · spring-cloud-kubernetes · apache/giraph. Tổng gold ~277 (W=3), verified-clean
~2.081. skywalking (repo #6, ~8.570 commit) đang chạy. Chi tiết số liệu: `SESSION_CONTEXT.md`.
</content>
