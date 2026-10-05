# GUIDE.md — Hướng dẫn dùng & CẤU HÌNH orchestrator SAST

> Pipeline: **1 link GitHub → duyệt commit → nhiều tool SAST → chuẩn hoá → đồng thuận đa-tool →
> dataset (mỗi dòng = 1 cụm finding, nhãn gold/silver/candidate + negative)**.
> Tài liệu này giúp bạn **chạy được ngay** và **tinh chỉnh từng núm**. 🚀

Đọc thêm: `RULE_GAN_NHAN.md` (quy tắc nhãn), `EXECUTION_FLOW.md` (luồng + thời gian đo),
`EXPENSIVE_TIER_REPORT.md` (tầng đắt), `SCAN_MECHANISM.md` (cơ chế từng tool).

---

## 1. Chuẩn bị môi trường (1 lần)

**Cần:** Docker + Git + Python 3.10 (stdlib, KHÔNG cần pip). Chạy mọi lệnh từ thư mục `src/`.

```bash
cd /home/scanner/tool-scan-commit/src        # mọi lệnh chạy ở đây (module orchestrator)
```

**Image tool đắt** (build 1 lần — tool rẻ tự pull khi chạy):
```bash
# CodeQL (maven+JDK8+bundle, ~3GB)
docker build -t orch-codeql:2.25.6      -f ../docker/codeql/Dockerfile      ../docker/codeql
# FindSecBugs (SpotBugs + plugin)
docker build -t orch-findsecbugs:1.14.0 -f ../docker/findsecbugs/Dockerfile ../docker/findsecbugs
# Sonar + scanner (pull)
docker pull sonarqube:lts-community
docker pull sonarsource/sonar-scanner-cli
```

**Cho SonarQube** (Elasticsearch nhúng cần) — chạy 1 lần mỗi khi VM khởi động lại:
```bash
sudo sysctl -w vm.max_map_count=262144
```

> ⚠️ **Gotcha Docker nhóm:** nếu `id` KHÔNG thấy `docker` → đặt `export ORCH_DOCKER_SG=1`
> (tự bọc lệnh qua `sg docker -c`). Sửa triệt để: SSH login mới rồi chạy lại.

---

## 2. Quy trình chuẩn

### Cách NHANH NHẤT — 1 lệnh chạy TRỌN pipeline 🎯
```bash
REPO=https://github.com/FudanSELab/train-ticket
python3 -m orchestrator.cli pipeline $REPO --max 50 --include-clean
#   nhanh (bỏ CodeQL):        pipeline $REPO --codeql 0
#   nhánh + quét hết:         pipeline $REPO --branch master --max 0
```
`pipeline` = **scan → select → analyze → relabel → kappa → export** tuần tự, in tiến độ từng bước.
Tuỳ chọn: `--max --branch --since --until --from-sha --to-sha --tools a,b --expensive-tools a,b --codeql 0/1
--include-clean --workers --flag-limit --no-meta --out --json`.

**Phạm vi commit** (chọn 1): `--max N` (N mới nhất; `0` = hết) · `--since/--until YYYY-MM-DD` (committer-date)
· `--from-sha A --to-sha B` (= `A..B`, verify bằng `git rev-parse`). Có since/until/sha mà bỏ trống `--max`
→ tự ép `--max 0` (có cảnh báo).

**Chọn tool:** `--tools semgrep,bearer` (tầng rẻ, env `ORCH_CHEAP_TOOLS`), `--expensive-tools findsecbugs,sonar`
(env `ORCH_EXPENSIVE_TOOLS`). Bỏ tool → CLI cảnh báo vì đổi **mẫu số `eligible`/κ** (RULE_GAN_NHAN §3) —
không so trực tiếp với run đủ tool.

### Chạy bằng profile (cách GUI/exe dùng — tái lập 1 lệnh) 📄
```bash
python3 -m orchestrator.cli pipeline --profile D:/secjit/profiles/train-ticket.json
python3 -m orchestrator.cli estimate --profile P.json --json     # ước tính phút/GB trước khi chạy
```
`--profile F` nhận ở **mọi** subcommand: áp `profile.to_env()` vào env **trước** khi đọc config, rồi dựng lại
argv từ profile — **mọi arg khác bị bỏ qua** (có cảnh báo). Cấu trúc `profile.json`: CONTRACTS.md §2;
`params_v1` khác v1 bắt buộc `experiment={"enabled":true,"reason":"…"}` (METHODOLOGY.md §3).

### DỌN sau khi xong 1 project 🧹
Sau khi đã tải dataset/export về, dọn clone + export để **giải phóng đĩa** trước project kế:
```bash
python3 -m orchestrator.cli clean $REPO --dry-run                         # liệt kê {path, bytes} — không xoá
python3 -m orchestrator.cli clean $REPO                                   # mặc định: clone + pool
python3 -m orchestrator.cli clean $REPO --items clone,pool,m2             # + cache Maven .m2cache
python3 -m orchestrator.cli clean $REPO --items export:data/export_x,db:data/dataset_x.sqlite
```
`--items` tách từng mục: `clone`, `pool`, `m2`, `export:<dir>`, `db:<path>` — **export/db bắt buộc chỉ rõ đường dẫn**
(không còn `--all`/`--export`/`--db` xoá theo env mặc định — tránh xoá nhầm `data/export`). `clean` **từ chối** khi
`<db>.lock` còn pid sống hoặc `pool_<pid>` thuộc tiến trình đang chạy. Dọn bằng `repo_pool.rmtree_force`
(chịu file read-only Windows). `--json` in `{would_delete, deleted, errors}`.

**Quy trình nhiều project:** `pipeline repoA` → tải export/DB về → `clean repoA --items clone,pool,export:<dir>`
→ `pipeline repoB` …

### Lệnh vận hành & phân tích (mới) 🧰
| Lệnh | Việc |
|---|---|
| `estimate --profile F [--json]` | Ước tính commit sau lọc, buggy, phút tầng rẻ/đắt (cache lạnh/ấm), GB — từ `%LOCALAPPDATA%/secjit/speed.json` (đo) hoặc mặc định |
| `stats [--db DB] [--run-id ID] [--format json\|csv\|latex] [--out DIR]` | Overview: funnel, labels, by_cwe_group, κ (tổng/category/nhóm/cặp tool), coverage, precision (nếu đã kiểm tay), **limits** ≥5 câu — DB mở chỉ-đọc |
| `sensitivity --db DB --out DIR [--grid line_window=3,5,7 gold_allow_1exp_1cheap=0,1 noise=on,off]` | Lưới tham số trên **BẢN SAO** DB → `sensitivity.json/.md` (METHODOLOGY §3) |
| `compare --a X --b Y [--format json\|md]` | So A/B theo `cluster_key` (export dir hoặc DB): same/only_a/only_b/label_changed, lệch giải thích bởi manifest; exit 1 nếu lệch không giải thích |
| `stop --run ID [--force]` | Tạo stop-file `<work>/<run>/stop` (dừng sau commit hiện tại, exit 3); `--force` kill cây tiến trình + `stop-cleanup` |
| `stop-cleanup --run ID` | `docker rm -f` container `label=orch.run=<id>`, gỡ network `orch-sonar-net-<id>`, rồi `reset-claims` theo run; exit 0 kể cả khi không có gì dọn |
| `reset-claims [--run ID] [--all-stale] [--db DB]` | `building/analyzing` → `pending` + xoá raw đắt bán phần (`claimed_by '<run_id>:wN'`; `--all-stale` = mọi hàng) |
| `review sample\|next\|verdict\|close --db DB …` | Kiểm tay GOLD mù: mẫu phân tầng seed cố định → chấm TP/FP/unclear → precision + Wilson + Cohen κ (METHODOLOGY §4) |
| `batch --queue Q.json [--state F] [--stop-file F]` | Chạy **tuần tự** nhiều profile (`pipeline --profile` từng cái, 1 Sonar), `batch_state.json`, dừng theo `<Q>.stop` |
| `diagnostics --run ID --out Z.zip [--profile F] [--work DIR]` | Gói chẩn đoán: run.log, progress.jsonl, meta, profile, run_meta/kappa (DB ro), `docker info/version/ps`, preflight.json, env (che token/PAT/mật khẩu) |

**Exit code chuẩn (CONTRACTS §11):** `0` ok · `1` lỗi tham số (profile/scope/tool lạ/argparse) · `2` lỗi runtime
· `3` dừng theo stop-file (scan/analyze/pipeline/batch). Mọi lệnh có `--json` in JSON ra stdout (cảnh báo ra stderr).

### Hoặc chạy TỪNG BƯỚC (kiểm soát / debug)
```bash
REPO=https://github.com/FudanSELab/train-ticket

# ① QUÉT tầng rẻ (5 tool, song song) -> raw + nhãn cheap-only
python3 -m orchestrator.cli scan $REPO --max 50
#   chọn NHÁNH + quét HẾT (không giới hạn):
python3 -m orchestrator.cli scan $REPO --branch master --max 0
#   (--branch: mặc định nhánh mặc định repo; nhận cả 'origin/<nhánh>'. --max 0 = mọi commit)

# ② CHỌN commit cho tầng đắt: buggy (có CWE/CVE) -> positive; clean -> negative
python3 -m orchestrator.cli select
#   (tuỳ chọn) thêm clean vào tầng đắt để verify -> verified-clean GOLD:
python3 -m orchestrator.cli select --include-clean

# ③ TẦNG ĐẮT: build + CodeQL/FindSecBugs/Sonar -> cross-tier gold/silver
python3 -m orchestrator.cli analyze $REPO --workers 2            # đầy đủ (chậm, gold đậm)
python3 -m orchestrator.cli analyze $REPO --workers 2 --codeql 0 # nhanh (bỏ CodeQL)

# ④ GÁN NHÃN LẠI từ raw (lọc nhiễu / đổi ngưỡng) — KHÔNG quét lại, ~giây
python3 -m orchestrator.cli relabel $REPO

# ⑤ KAPPA: độ tin đồng thuận tool
python3 -m orchestrator.cli kappa

# ⑥ EXPORT: file trực quan mỗi commit
python3 -m orchestrator.cli export

# (tuỳ chọn) BACKFILL 14 đặc trưng Kamei cho DB CŨ (scan mới tự tính rồi — không cần)
python3 -m orchestrator.cli features $REPO   # [--branch <nhánh đã scan>] ~giây, không quét lại
```

**Mẹo tốc độ:** `analyze --codeql 0` (~30s/commit) trước để có dữ liệu nhanh; chạy đầy đủ (`--codeql 1`,
~7'/commit) sau khi hài lòng. `relabel`/`kappa`/`export` **rất rẻ** (đọc từ raw) → chạy lại thoải mái.

---

## 3. CẤU HÌNH — mọi núm qua biến môi trường `ORCH_*`

Đặt trước lệnh, vd: `ORCH_SCAN_WORKERS=8 ORCH_USE_CODEQL=0 python3 -m orchestrator.cli scan ...`

### 3.1 Đường dẫn & lưu trữ
| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `ORCH_WORK_DIR` | `./work` | clone repo + pool + cache .m2 (đĩa VM) |
| `ORCH_DATA_DIR` | `./data` | nơi lưu dataset |
| `ORCH_SQLITE` | `data/dataset.sqlite` | file DB (đổi để chạy nhiều dataset song song) |
| `ORCH_EXPORT_DIR` | `data/export` | thư mục export |
| `ORCH_STORE_FULL_FILE` | `0` | `1` = lưu TOÀN VĂN code_before/after (nặng); mặc định chỉ permalink |
| `ORCH_DOCKER_SG` | (tắt) | `1` = bọc docker qua `sg docker -c` (khi chưa vào nhóm docker) |
| `ORCH_M2_VOLUME` | (rỗng = `0`) | Cache Maven `/m2` cho build/CodeQL/Sonar: `0` = bind mount `WORK_DIR/.m2cache`; **`1` = Docker named volume `secjit-m2`** (tự `docker volume create`; nhanh hơn bind mount trên Windows/WSL2, không cần file-sharing ổ đĩa); tên khác = volume tên đó. Không tạo được volume → cảnh báo + quay về bind mount. Dọn: `docker volume rm secjit-m2` (`clean --items m2` chỉ xoá bind mount) |

### 3.1b — 14 đặc trưng Kamei (JIT defect prediction)

Tính CHỈ từ git history (Kamei et al. 2013), tự chạy trong `scan` (1 lượt duyệt, ~giây); nằm ở
bảng `commit_features`, nhúng vào mỗi row `label.json` (key `kamei`) và block `kamei` trong
`summary.json` (kể cả commit NEGATIVE). Backfill DB cũ: lệnh `features` (mục 2).

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `ORCH_KAMEI` | `1` | `0` = tắt tính đặc trưng khi scan |
| `ORCH_FIX_KEYWORDS` | `fix,bug,defect,patch,fault,repair` | từ khoá nhận diện commit FIX (khớp đầu-từ, không phân hoa/thường) |

14 đặc trưng: **NS/ND/NF/Entropy** (diffusion) · **LA/LD/LT** (size) · **FIX** (purpose) ·
**NDEV/AGE/NUC** (history) · **EXP/REXP/SEXP** (experience). Lưu RAW value (không normalize).
Merge commit bỏ qua; rename được theo dõi; file nhị phân tính NF/ND/NS nhưng loại khỏi Entropy/LA/LD/LT;
KHÔNG áp `ORCH_EXCLUDE_PATHS` (trung thành định nghĩa gốc).

### 3.2 Lọc commit / file (tầng ①)
| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `ORCH_FLAG_LIMIT` | `0` | `1` = BẬT ngưỡng bỏ commit khổng lồ; `0` = quét mọi commit hợp lệ |
| `ORCH_MAX_FILES_PER_COMMIT` | `100` | (khi FLAG_LIMIT=1) commit >N file → bỏ |
| `ORCH_MAX_FILE_ADD_LINES` | `1000` | (FLAG_LIMIT=1) 1 file add >N dòng → bỏ |
| `ORCH_MAX_FILE_DEL_LINES` | `1000` | (FLAG_LIMIT=1) 1 file del >N dòng → bỏ |
| `ORCH_MAX_FILE_CHURN_LINES` | `2000` | (FLAG_LIMIT=1) 1 file (add+del) >N → bỏ |
| `ORCH_EXCLUDE_PATHS` | `node_modules/,/vendor/,bower_components/,/dist/,/build/,/third_party/,/generated/,.min.js,.min.css,.pb.go,_pb2.py` | đường dẫn vendored/generated → loại khỏi scan + finding |

> `SKIP_MERGE_COMMITS`, `CODE_EXTENSIONS`, `BINARY_EXTENSIONS` là hằng trong `config.py` (sửa file nếu cần).
> Commit chỉ đụng file **text non-code** (README/.env/.sh) VẪN được giữ để secret-tool quét.

### 3.3 Song song (tốc độ)
| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `ORCH_SCAN_WORKERS` | `4` | số commit song song ở tầng RẺ (VM 8 vCPU → 4-6 ổn) |
| `ORCH_CHEAP_INTRA_PARALLEL` | `1` | tầng rẻ: `1`=5 tool song song/commit (Model B, nhanh ~14%), `0`=tuần tự |
| `ORCH_EXPENSIVE_WORKERS` | `2` | số commit song song ở tầng ĐẮT (nặng RAM → 2-3) |
| `ORCH_EXPENSIVE_INTRA_PARALLEL` | `0` | tầng đắt: `0`=3 tool tuần tự (khuyến nghị), `1`=song song |

### 3.4 Chọn commit lên tầng đắt (tầng ⑤)
| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `ORCH_SUSPECT_REQUIRE_IN_DIFF` | (tắt) | `1` = chỉ coi buggy khi finding nằm TRONG diff commit (không tính nợ cũ) |

CLI: `select --include-clean` (thêm clean để verify), `select --require-in-diff 0/1`.

### 3.5 Tầng đắt: build + tool
| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `ORCH_EXPENSIVE_TOOLS` | `codeql,findsecbugs,sonar` | tool đắt bật (thứ tự chạy) — CLI `--expensive-tools` |
| `ORCH_CHEAP_TOOLS` | `gitleaks,trufflehog,semgrep,bearer,horusec` | tool **rẻ** bật — CLI `--tools`; bỏ tool đổi mẫu số eligible/κ (cảnh báo) |
| `ORCH_INFRA_STOP_AFTER` | `3` | số `infra_error` LIÊN TIẾP (Docker tắt, đĩa đầy) trước khi run tự dừng (`event=stop`, exit 3) |
| `ORCH_SONAR_PORT` | `9000` | port host map vào SonarQube (đổi `9100` khi 9000 bị chiếm — preflight tự dò) |
| `ORCH_USE_CODEQL` | `1` | công tắc riêng CodeQL (nút thắt ~95% time). `0`=chỉ FindSecBugs+Sonar (~30s/commit) |
| `ORCH_MAVEN_IMAGE` | `maven:3.9-eclipse-temurin-8` | image build FALLBACK (khi không dò được JDK / tắt autodetect) |
| `ORCH_JDK_AUTODETECT` | `1` | dò JDK TỪNG COMMIT từ pom.xml (`java.version`/`maven.compiler.*`) → image temurin 8/11/17/21. `0`=luôn dùng MAVEN_IMAGE |
| `ORCH_JDK_IMAGE_TEMPLATE` | `maven:3.9-eclipse-temurin-{jdk}` | template image khi autodetect trúng |
| `ORCH_MAVEN_GOALS` | `-B clean package -DskipTests` | goal build (module bị đụng tự chèn `-pl <mods> -am`) |
| `ORCH_BUILD_TIMEOUT` | `1800` | timeout build (giây) |
| `ORCH_CODEQL_SUITE` | `codeql/java-queries:codeql-suites/java-code-scanning.qls` | bộ query CodeQL. Dùng `/opt/minimal-java.qls` (bake sẵn, 10 query) để **nhanh 3×** (~6.7' thay vì 20') |
| `ORCH_CODEQL_RAM_MB` | `20000` | RAM cho CodeQL analyze (tránh OOM) |
| `ORCH_CODEQL_THREADS` | `0` | `0`=hết core |
| `ORCH_SONAR_ADMIN_PW` | `Orch_2026!` | mật khẩu admin Sonar đặt QUA API (không mở web) |
| `ORCH_STALE_CLAIM_SEC` | `7200` | commit treo >N giây → reset về pending (resume sau STOP VM) |

CLI: `analyze --workers N --tools codeql,sonar --codeql 0/1 --dry-run`.

### 3.6 Gán nhãn & đồng thuận (tầng ⑥)
| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `ORCH_GOLD_MIN_EXPENSIVE` | `2` | ≥N tool ĐẮT đồng thuận → **gold** |
| `ORCH_GOLD_ALLOW_1EXP_1CHEAP` | `1` | `1` = (1 đắt + ≥1 rẻ) cũng = gold |
| `ORCH_SILVER_MIN_CHEAP` | `2` | ≥N tool RẺ → **silver** |
| `ORCH_NOISE_CWE` | `CWE-117` | CWE FP-cao → bỏ khi gán nhãn (raw giữ nguyên). Thêm: `CWE-117,CWE-807` |
| `ORCH_NOISE_RULES` | (rỗng) | rule_id FP-cao cần bỏ (vd `CRLF_INJECTION_LOGS`) |

> `LINE_WINDOW=3` là **cấu hình v1 đăng ký trước** (METHODOLOGY.md §1). `ORCH_LINE_WINDOW` **chỉ có hiệu lực khi
> `ORCH_EXPERIMENT=1`** (xem §3.7); không bật → giữ 3 và in cảnh báo. Muốn xem ảnh hưởng W → dùng `sensitivity`
> trên bản sao DB. Đổi nhãn/lọc nhiễu → `relabel` (không quét lại). `ORCH_VOTE_THRESHOLD` là tham số **chết**
> (legacy single-tier) — không ghi run_meta, không hiển thị.

### 3.7 Run, tiến độ, thí nghiệm (GUI/runner đặt; CLI đọc)
| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `ORCH_RUN_ID` | `local` | định danh run; gắn vào mọi dòng progress, `run_meta.run_id`, `kappa.run_id`, label container `orch.run=<id>`, `claimed_by='<id>:wN'` |
| `ORCH_PROGRESS_FILE` | (rỗng = không ghi) | `progress.jsonl` — 1 dòng JSON/sự kiện `{ts,run_id,phase,event,done,total,worker,sha,status,msg}` (CONTRACTS §3); GUI đọc SSE |
| `ORCH_STOP_FILE` | (rỗng) | đường dẫn stop-file; tồn tại → orchestrator kết thúc commit hiện tại, **không claim mới**, `event=stop`, exit **3** (kiểm giữa mỗi commit ở scan và analyze) |
| `ORCH_EXPERIMENT` | `0` | `1` = chế độ thí nghiệm: `run_meta.experiment=1`, export hậu tố `_exp`, **không gộp** gold_set_all |
| `ORCH_EXPERIMENT_REASON` | (rỗng) | lý do bắt buộc (≥10 ký tự qua profile) — ghi `run_meta.reason` |
| `ORCH_LINE_WINDOW` | `3` | ±dòng gộp cụm — **chỉ khi `ORCH_EXPERIMENT=1`**, ngược lại bị bỏ qua + cảnh báo |
| `SECJIT_APP_VERSION` | `dev` | phiên bản app/exe → `run_meta.app_version`, manifest, `diagnostics/system.json` |

Runner nền (`runner.start`) đặt: `ORCH_RUN_ID`, `ORCH_PROGRESS_FILE=<work>/<run_id>/progress.jsonl`,
`ORCH_STOP_FILE=<work>/<run_id>/stop`, `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8` + toàn bộ `profile.to_env()`.
Mọi biến hiệu lực được chụp vào `run_meta.config_snapshot_json` (bỏ `ORCH_SONAR_ADMIN_PW`).

---

## 4. Đầu ra

### 4.1 Bảng trong `dataset.sqlite`
| Bảng | Nội dung |
|---|---|
| **`raw_findings`** | mỗi finding TỪNG-tool (nguồn recompute + kappa) |
| **`raw_output`** | output THÔ nguyên bản mỗi tool (sarif/xml/json — audit) |
| **`findings`** | cụm đã gộp + NHÃN (`label` gold/silver/candidate, `tier`, `n_cheap/n_expensive`, `finding_in_diff`, `agreeing_tools`, `cwe`, `s_line`…) |
| `scanned_files` | mọi file đã quét (negative/mẫu số) |
| `selected_commits` | hàng đợi tầng đắt + trạng thái |
| `expensive_runs` | telemetry build/analyze (thời gian, lỗi) |

### 4.2 Export (`data/export/`)
```
<commit12>/
  <tool>.raw.<ext>        output thô mỗi tool
  <tool>.findings.json    finding parsed từng tool
  label.json              cụm + nhãn gold/silver/candidate
  summary.json            tools_reported + đếm nhãn + negative_level
negatives.json            danh sách verified-clean vs cheap-clean
```

---

## 5. Công thức thường dùng

```bash
# Nhanh nhất (không CodeQL) — ra dataset trong ~30 phút
python3 -m orchestrator.cli scan $REPO --max 50
python3 -m orchestrator.cli select --include-clean
ORCH_USE_CODEQL=0 python3 -m orchestrator.cli analyze $REPO --workers 3
python3 -m orchestrator.cli export

# CodeQL nhanh (suite tối giản, gold đậm hơn mà không quá chậm)
ORCH_CODEQL_SUITE=/opt/minimal-java.qls python3 -m orchestrator.cli analyze $REPO

# Thử ngưỡng gold khác + xem kappa — KHÔNG quét lại
ORCH_GOLD_MIN_EXPENSIVE=1 python3 -m orchestrator.cli relabel $REPO
python3 -m orchestrator.cli kappa

# Lọc thêm nhiễu FindSecBugs rồi relabel
ORCH_NOISE_CWE=CWE-117,CWE-807 python3 -m orchestrator.cli relabel $REPO

# Chạy nhiều dataset độc lập (DB riêng)
ORCH_SQLITE=data/repoX.sqlite python3 -m orchestrator.cli scan <repoX>

# Chỉ quét 1 khoảng thời gian / 1 dải commit (ép --max 0 tự động)
python3 -m orchestrator.cli pipeline $REPO --since 2024-01-01 --until 2024-06-30 --codeql 0
python3 -m orchestrator.cli enumerate $REPO --from-sha v1.0.0 --to-sha v1.1.0 --json

# Tái lập Run A ↔ Run B (train-ticket --max 30) rồi so
python3 -m orchestrator.cli pipeline --profile P.json
python3 -m orchestrator.cli compare --a data/export_A --b data/export_B --format md

# Độ nhạy tham số trên bản sao DB (không đụng DB gốc) + thống kê cho paper
python3 -m orchestrator.cli sensitivity --db data/dataset_x.sqlite --out data/sens_x
python3 -m orchestrator.cli stats --db data/dataset_x.sqlite --format latex --out data/stats_x

# Dừng an toàn run nền rồi dọn
python3 -m orchestrator.cli stop --run 20261005-1 --profile P.json          # chờ commit hiện tại xong, exit 3
python3 -m orchestrator.cli stop --run 20261005-1 --profile P.json --force  # kill + rm container + reset-claims

# Hàng đợi nhiều repo (tuần tự, 1 Sonar) + gói chẩn đoán khi có sự cố
python3 -m orchestrator.cli batch --queue D:/secjit/queue.json
python3 -m orchestrator.cli diagnostics --run 20261005-1 --out D:/secjit/diag_20261005-1.zip --profile P.json
```

---

## 6. Xử lý sự cố

| Triệu chứng | Nguyên nhân / cách sửa |
|---|---|
| `permission denied` docker | chưa vào nhóm docker → `export ORCH_DOCKER_SG=1` |
| Sonar không UP / analyze treo | `sudo sysctl -w vm.max_map_count=262144` (reset khi reboot) |
| CodeQL OOM | tăng `ORCH_CODEQL_RAM_MB`, hoặc suite tối giản, hoặc `--codeql 0` |
| analyze quá chậm | `--codeql 0` hoặc `ORCH_CODEQL_SUITE=/opt/minimal-java.qls`; tăng `ORCH_EXPENSIVE_WORKERS` |
| build_failed nhiều | sai JDK → đổi `ORCH_MAVEN_IMAGE`; hoặc commit lịch sử không build được (đã ghi lại, không crash) |
| gold quá ít | bật CodeQL (trùng semgrep/sonar), hoặc nới ngưỡng `ORCH_GOLD_ALLOW_1EXP_1CHEAP=1` |
| dataset nhiễu | thêm `ORCH_NOISE_CWE` rồi `relabel` |
| kẹt clone-pool | `clean $REPO --items pool` (từ chối pool của tiến trình còn sống; dùng `rmtree_force`) |
| run chết giữa chừng, commit kẹt `building/analyzing` | `stop-cleanup --run <id>` (dọn container + `reset-claims`) rồi `analyze` tiếp; hoặc `reset-claims --all-stale --db <db>` |
| `DB đang được run khác dùng (pid=…)` | `<db>.lock` còn pid sống → dừng run đó (`stop --run`) hoặc dùng DB khác; lock mồ côi tự được thay khi pid chết |
| exit 3 bất ngờ | có stop-file (`ORCH_STOP_FILE`) hoặc ≥`ORCH_INFRA_STOP_AFTER` infra_error liên tiếp → xem `progress.jsonl` dòng `event=stop` |
| `ORCH_LINE_WINDOW … bị BỎ QUA` | chỉ hiệu lực khi `ORCH_EXPERIMENT=1` (METHODOLOGY §3) — hoặc dùng `sensitivity` |
| Git Bash đổi `/m2`, `/work` thành `C:/Program Files/Git/m2` | cygpath tự dịch đường dẫn container → đặt `MSYS_NO_PATHCONV=1` (xem CLAUDE.md) hoặc chạy PowerShell |
| bind mount `.m2cache` chậm trên Windows | `ORCH_M2_VOLUME=1` (named volume `secjit-m2`) |

> **Nguyên tắc VM:** dataset lưu THẲNG trên đĩa VM (không GCS). Chỉ **STOP** VM (đừng DELETE) để khỏi mất.
> `relabel`/`kappa`/`export` đọc từ raw → tinh chỉnh nhãn **không tốn tiền scan lại**. 💪
