"""Cấu hình tập trung cho orchestrator. Stdlib-only."""
from __future__ import annotations

import os
from pathlib import Path

# Gốc dự án (thư mục chứa src/)
ROOT = Path(__file__).resolve().parents[2]

# Nơi clone repo target + file tạm (Persistent Disk VM)
WORK_DIR = Path(os.environ.get("ORCH_WORK_DIR", ROOT / "work"))

# Nơi lưu dataset cuối (SQLite/Parquet) — THẲNG trên VM, KHÔNG GCS
DATA_DIR = Path(os.environ.get("ORCH_DATA_DIR", ROOT / "data"))
SQLITE_PATH = Path(os.environ.get("ORCH_SQLITE", DATA_DIR / "dataset.sqlite"))
EXPORT_DIR = Path(os.environ.get("ORCH_EXPORT_DIR", DATA_DIR / "export"))

# --- Lọc thô (Tầng ①) ---
SKIP_MERGE_COMMITS = True
# đuôi file coi là "code đáng quét" cho pilot (Java là chính)
CODE_EXTENSIONS = {".java", ".xml", ".properties", ".yml", ".yaml", ".py", ".ts", ".js", ".sql"}
# coi là docs/non-code -> bỏ qua khi xét commit
DOC_EXTENSIONS = {".md", ".txt", ".rst", ".adoc", ".png", ".jpg", ".gif", ".svg", ".pdf"}
# File NHỊ PHÂN: secret scanner bỏ qua được. Commit CHỈ đụng các đuôi này -> không đáng quét.
# (Mọi file TEXT khác — kể cả docs/config .md/.json/.env/Dockerfile — VẪN quét: secret có thể
#  nằm trong đó; gitleaks/trufflehog quét toàn diff bất kể đuôi.)
BINARY_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".bmp", ".webp",
                     ".pdf", ".zip", ".gz", ".tar", ".tgz", ".rar", ".7z",
                     ".jar", ".war", ".ear", ".class", ".so", ".dll", ".exe", ".bin",
                     ".woff", ".woff2", ".ttf", ".eot", ".otf",
                     ".mp4", ".mp3", ".avi", ".mov", ".wav", ".ogg"}
# Đường dẫn VENDORED/GENERATED — finding trong đó KHÔNG phải của dự án (nhiễu). Loại khỏi scan + finding.
# (vd secret trong node_modules/@types/*.d.ts của thư viện, không phải secret dự án.)
EXCLUDE_PATH_PATTERNS = [p for p in os.environ.get(
    "ORCH_EXCLUDE_PATHS",
    "node_modules/,/vendor/,bower_components/,/dist/,/build/,/third_party/,"
    "/generated/,.min.js,.min.css,.pb.go,_pb2.py").split(",") if p]

# Ngưỡng BỎ QUA commit "khổng lồ" (diff quá lớn = bulk/generated, quét tốn & loãng tín hiệu).
# Xét theo MỨC THAY ĐỔI của commit LÊN TỪNG FILE (add/del trong diff), KHÔNG phải kích thước file:
#   - commit đụng > MAX_FILES_PER_COMMIT file (mọi loại) -> bỏ.
#   - BẤT KỲ file nào có add > MAX_FILE_ADD_LINES, HOẶC del > MAX_FILE_DEL_LINES,
#     HOẶC (add + del) > MAX_FILE_CHURN_LINES -> bỏ.
MAX_FILES_PER_COMMIT = int(os.environ.get("ORCH_MAX_FILES_PER_COMMIT", "100"))
MAX_FILE_ADD_LINES = int(os.environ.get("ORCH_MAX_FILE_ADD_LINES", "1000"))
MAX_FILE_DEL_LINES = int(os.environ.get("ORCH_MAX_FILE_DEL_LINES", "1000"))
MAX_FILE_CHURN_LINES = int(os.environ.get("ORCH_MAX_FILE_CHURN_LINES", "2000"))
# Công tắc BẬT/TẮT toàn bộ ngưỡng skip ở trên (các tham số vẫn giữ nguyên):
#   0 = KHÔNG dùng ngưỡng (quét MỌI commit hợp lệ), 1 = áp dụng ngưỡng số-file/add/del/churn.
# Tạm thời mặc định 0. Override: env ORCH_FLAG_LIMIT hoặc CLI --flag-limit.
FLAG_LIMIT = int(os.environ.get("ORCH_FLAG_LIMIT", "0"))

# --- Consensus (Tầng ⑥) ---
LINE_WINDOW = 3  # ±W dòng để gộp 2 finding cùng (file, CWE)
# ngưỡng số tool đồng thuận để gán nhãn "vuln"; 1..K-1 => "candidate"; 0 => "clean" (legacy)
VOTE_THRESHOLD = int(os.environ.get("ORCH_VOTE_THRESHOLD", "2"))
# Thang nhãn cross-tier (RULE_GAN_NHAN.md §4/§9). E=#tool đắt, C=#tool rẻ trong cụm.
#   gold  : E>=GOLD_MIN_EXPENSIVE  HOẶC (GOLD_ALLOW_1EXP_1CHEAP và E>=1 và C>=1)
#   silver: E>=1  HOẶC  C>=SILVER_MIN_CHEAP
#   candidate: còn lại (1 tool rẻ)
GOLD_MIN_EXPENSIVE = int(os.environ.get("ORCH_GOLD_MIN_EXPENSIVE", "2"))
GOLD_ALLOW_1EXP_1CHEAP = int(os.environ.get("ORCH_GOLD_ALLOW_1EXP_1CHEAP", "1"))
SILVER_MIN_CHEAP = int(os.environ.get("ORCH_SILVER_MIN_CHEAP", "2"))
# LỌC NHIỄU khi GÁN NHÃN (raw giữ nguyên — chỉ bỏ khỏi consensus). CWE/rule FP cao.
# CWE-117 (CRLF log-injection): FindSecBugs flag mọi log(userInput) -> FP nặng, phá verified-clean.
NOISE_CWE = {c.strip() for c in os.environ.get("ORCH_NOISE_CWE", "CWE-117").split(",") if c.strip()}
NOISE_RULES = {r.strip() for r in os.environ.get("ORCH_NOISE_RULES", "").split(",") if r.strip()}

# --- 14 đặc trưng Kamei (JIT defect prediction) — tính từ git history, xem kamei.py ---
KAMEI_ENABLED = int(os.environ.get("ORCH_KAMEI", "1"))          # 1=tính khi scan, 0=tắt
# Từ khoá nhận diện commit FIX (khớp ĐẦU-từ, case-insensitive: 'fixes'/'bugfix' đều trúng)
FIX_KEYWORDS = os.environ.get("ORCH_FIX_KEYWORDS",
                              "fix,bug,defect,patch,fault,repair")

# --- Ngữ cảnh file ---
# Mặc định CHỈ lưu permalink (rẻ). Bật để lưu thêm toàn văn code_before/code_after (nặng).
STORE_FULL_FILE = os.environ.get("ORCH_STORE_FULL_FILE") == "1"

# --- Song song CẤP COMMIT (Tầng ②) ---
# Số clone-pool xử lý commit ĐỒNG THỜI. Mỗi worker xử trọn 1 commit -> tối đa SCAN_WORKERS
# (hoặc SCAN_WORKERS×#tool nếu INTRA_PARALLEL) container cùng lúc. Đặt ~ số vCPU, chừa RAM.
SCAN_WORKERS = int(os.environ.get("ORCH_SCAN_WORKERS", "4"))
# Tool trong 1 commit: A(0)=TUẦN TỰ, B(1)=SONG SONG. Tách theo tầng.
# Tầng RẺ mặc định B (đo được nhanh hơn ~14%, tool nhẹ). Tầng ĐẮT mặc định A (tool còn nặng/skeleton).
CHEAP_INTRA_PARALLEL = int(os.environ.get("ORCH_CHEAP_INTRA_PARALLEL", "1"))
EXPENSIVE_INTRA_PARALLEL = int(os.environ.get("ORCH_EXPENSIVE_INTRA_PARALLEL", "0"))

# --- Chọn commit lên TẦNG ĐẮT (Bước 2) ---
# Commit "ĐÁNG NGHI" (buggy) = có BẤT KỲ finding tầng rẻ nào mang mã CWE/CVE (chỉ cần 1 tool/1 finding).
# (Mọi finding đều đã ép có CWE ở validate() -> thực chất: commit có ≥1 finding bất kỳ.)
# 1 = chỉ tính đáng nghi khi finding rơi vào dòng commit THÊM/SỬA; 0 = mọi finding (mặc định 0).
# Buggy (có CWE/CVE) -> tầng đắt (positive). Clean (0 CWE/CVE) -> negative, KHÔNG quét đắt (lấy hết).
SUSPECT_REQUIRE_IN_DIFF = os.environ.get("ORCH_SUSPECT_REQUIRE_IN_DIFF") == "1"

# --- TẦNG ĐẮT (Bước 2 — Model A: song song CẤP COMMIT, 3 tool tuần tự, build dùng chung) ---
# Số commit xử song song ở tầng đắt (nặng RAM/build -> ÍT hơn tầng rẻ nhiều). PoC = 2.
EXPENSIVE_WORKERS = int(os.environ.get("ORCH_EXPENSIVE_WORKERS", "2"))
# Tool đắt bật (theo thứ tự chạy trong 1 commit). Tách dấu phẩy.
EXPENSIVE_TOOLS = [t.strip() for t in
                   os.environ.get("ORCH_EXPENSIVE_TOOLS", "codeql,findsecbugs,sonar").split(",")
                   if t.strip()]
# Công tắc RIÊNG cho CodeQL (nút thắt ~95% thời gian tầng đắt): 1=bật, 0=TẮT.
# Tắt -> tầng đắt chỉ FindSecBugs+Sonar (~30s/commit, hợp cho GOLD-negative / chạy nhanh).
USE_CODEQL = int(os.environ.get("ORCH_USE_CODEQL", "1"))
# Build dùng chung cho 3 tool. Image Maven + JDK đúng thời kỳ (train-ticket: Java 8, Spring Boot 2.3).
# PoC xác nhận: maven:3.9-eclipse-temurin-8 build OK; service+dep ~13s cache ấm.
MAVEN_IMAGE = os.environ.get("ORCH_MAVEN_IMAGE", "maven:3.9-eclipse-temurin-8")
# AUTO-DETECT JDK theo TỪNG COMMIT (repo lịch sử dài đổi JDK: Boot 1.x/2.x cần 8, mới cần 17):
# đọc pom.xml tại commit (<java.version>/<maven.compiler.release|target|source>) -> map image
# temurin 8/11/17/21. Không dò được -> fallback MAVEN_IMAGE. 0 = luôn dùng MAVEN_IMAGE.
JDK_AUTODETECT = int(os.environ.get("ORCH_JDK_AUTODETECT", "1"))
JDK_IMAGE_TEMPLATE = os.environ.get("ORCH_JDK_IMAGE_TEMPLATE",
                                    "maven:3.9-eclipse-temurin-{jdk}")
# Goal build (KHÔNG kèm -pl; module bị đụng được chèn động: `-pl <mods> -am`).
MAVEN_GOALS = os.environ.get("ORCH_MAVEN_GOALS", "-B clean package -DskipTests")
BUILD_TIMEOUT = int(os.environ.get("ORCH_BUILD_TIMEOUT", "1800"))
# CodeQL analyze: chặn RAM/threads tường minh (mặc định ước lượng SAI trong container -> OOM).
# threads=0 = dùng hết core. Suite mặc định nhẹ (code-scanning); extended quá chậm (>20'/commit).
CODEQL_RAM_MB = int(os.environ.get("ORCH_CODEQL_RAM_MB", "20000"))
CODEQL_THREADS = int(os.environ.get("ORCH_CODEQL_THREADS", "0"))
# Mặc định code-scanning đầy đủ (~80 query, ~20'/commit — người dùng chấp nhận để phủ rộng).
# Suite tối giản /opt/minimal-java.qls (bake sẵn, ~6.7') vẫn dùng được qua ORCH_CODEQL_SUITE.
CODEQL_SUITE = os.environ.get(
    "ORCH_CODEQL_SUITE", "codeql/java-queries:codeql-suites/java-code-scanning.qls")
# SonarQube: mật khẩu admin đặt QUA API lúc start_server (admin/admin chỉ dùng được lần đầu).
SONAR_ADMIN_PW = os.environ.get("ORCH_SONAR_ADMIN_PW", "Orch_2026!")
# Hàng 'building'/'analyzing' cũ hơn ngần này giây coi là chết -> reset 'pending' (resume sau STOP VM).
STALE_CLAIM_SEC = int(os.environ.get("ORCH_STALE_CLAIM_SEC", "7200"))

# --- Repo pilot ---
PILOT_REPO = "https://github.com/FudanSELab/train-ticket"
PILOT_MAX_COMMITS = 50


def ensure_dirs() -> None:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
