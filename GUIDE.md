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

## 2. Quy trình chuẩn (6 lệnh)

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
| `ORCH_EXPENSIVE_TOOLS` | `codeql,findsecbugs,sonar` | tool đắt bật (thứ tự chạy) |
| `ORCH_USE_CODEQL` | `1` | công tắc riêng CodeQL (nút thắt ~95% time). `0`=chỉ FindSecBugs+Sonar (~30s/commit) |
| `ORCH_MAVEN_IMAGE` | `maven:3.9-eclipse-temurin-8` | image build (đổi JDK theo repo) |
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

> `LINE_WINDOW=3` (±dòng gộp cụm) là hằng trong `config.py`. Đổi nhãn/lọc nhiễu → chạy `relabel` (không quét lại).

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
| kẹt clone-pool | dọn: `docker run --rm -v $PWD/../work:/w alpine rm -rf /w/pool_*` |

> **Nguyên tắc VM:** dataset lưu THẲNG trên đĩa VM (không GCS). Chỉ **STOP** VM (đừng DELETE) để khỏi mất.
> `relabel`/`kappa`/`export` đọc từ raw → tinh chỉnh nhãn **không tốn tiền scan lại**. 💪
