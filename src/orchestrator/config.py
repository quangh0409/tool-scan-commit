"""Cấu hình tập trung cho orchestrator. Stdlib-only.

Mọi giá trị đọc từ env `ORCH_*` trong `reload()` — gọi lại hàm này sau khi đổi `os.environ`
(vd `cli --profile F` áp `profile.to_env()` rồi `config.reload()`). Module khác luôn truy cập
`config.X` lúc chạy (không `from .config import X`) nên reload có hiệu lực tức thì.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Gốc dự án (thư mục chứa src/)
ROOT = Path(__file__).resolve().parents[2]

# --- HẰNG (không đọc env) ---
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
# Tên tool hợp lệ theo tầng (validate `--tools` / `--expensive-tools`).
CHEAP_TOOLS_ALL = ["gitleaks", "trufflehog", "semgrep", "bearer", "horusec"]
EXPENSIVE_TOOLS_ALL = ["codeql", "findsecbugs", "sonar"]
# LINE_WINDOW cấu hình v1 (TOOL_IDEA §13). Chỉ đổi được khi ORCH_EXPERIMENT=1.
LINE_WINDOW_V1 = 3

# --- Repo pilot ---
PILOT_REPO = "https://github.com/FudanSELab/train-ticket"
PILOT_MAX_COMMITS = 50

# Tên env đã được "tiêu thụ" — dùng cho effective_env()/config_snapshot (A2 bảo trì bảng này).
ENV_KEYS = [
    "ORCH_WORK_DIR", "ORCH_DATA_DIR", "ORCH_SQLITE", "ORCH_EXPORT_DIR", "ORCH_EXCLUDE_PATHS",
    "ORCH_MAX_FILES_PER_COMMIT", "ORCH_MAX_FILE_ADD_LINES", "ORCH_MAX_FILE_DEL_LINES",
    "ORCH_MAX_FILE_CHURN_LINES", "ORCH_FLAG_LIMIT",
    "ORCH_VOTE_THRESHOLD", "ORCH_GOLD_MIN_EXPENSIVE", "ORCH_GOLD_ALLOW_1EXP_1CHEAP",
    "ORCH_SILVER_MIN_CHEAP", "ORCH_NOISE_CWE", "ORCH_NOISE_RULES",
    "ORCH_KAMEI", "ORCH_FIX_KEYWORDS", "ORCH_STORE_FULL_FILE",
    "ORCH_SCAN_WORKERS", "ORCH_SCAN_RESUME", "ORCH_SUBMODULES",
    "ORCH_CHEAP_INTRA_PARALLEL", "ORCH_EXPENSIVE_INTRA_PARALLEL", "ORCH_SUSPECT_REQUIRE_IN_DIFF",
    "ORCH_EXPENSIVE_WORKERS", "ORCH_EXPENSIVE_TOOLS", "ORCH_CHEAP_TOOLS", "ORCH_USE_CODEQL",
    "ORCH_MAVEN_IMAGE", "ORCH_JDK_AUTODETECT", "ORCH_JDK_IMAGE_TEMPLATE", "ORCH_MAVEN_GOALS",
    "ORCH_BUILD_TIMEOUT", "ORCH_CODEQL_RAM_MB", "ORCH_CODEQL_THREADS", "ORCH_CODEQL_SUITE",
    "ORCH_SONAR_PORT", "ORCH_STALE_CLAIM_SEC", "ORCH_M2_VOLUME", "ORCH_INFRA_STOP_AFTER",
    "ORCH_RUN_ID", "ORCH_PROGRESS_FILE", "ORCH_STOP_FILE",
    "ORCH_EXPERIMENT", "ORCH_EXPERIMENT_REASON", "ORCH_LINE_WINDOW",
    "SECJIT_APP_VERSION", "ORCH_DOCKER_SG",
]
# KHÔNG đưa vào snapshot (bí mật).
SECRET_ENV_KEYS = {"ORCH_SONAR_ADMIN_PW"}

_WARNED: set[str] = set()


def _warn(key: str, msg: str) -> None:
    """In cảnh báo 1 lần / tiến trình / khoá (stderr, không làm hỏng --json trên stdout)."""
    if key in _WARNED:
        return
    _WARNED.add(key)
    print(f"[config] CẢNH BÁO: {msg}", file=sys.stderr)


def _int(name: str, default: str) -> int:
    return int(os.environ.get(name, default))


def _csv(name: str, default: str) -> list[str]:
    return [t.strip() for t in os.environ.get(name, default).split(",") if t.strip()]


def reload() -> None:
    """Đọc LẠI mọi biến từ os.environ và gán vào module (gọi sau khi áp profile.to_env())."""
    global INFRA_STOP_AFTER
    global APP_VERSION, BUILD_TIMEOUT, CHEAP_INTRA_PARALLEL, CHEAP_TOOLS, CODEQL_RAM_MB, CODEQL_SUITE, CODEQL_THREADS, DATA_DIR
    global EXCLUDE_PATH_PATTERNS, EXPENSIVE_INTRA_PARALLEL, EXPENSIVE_TOOLS, EXPENSIVE_WORKERS, EXPERIMENT, EXPERIMENT_REASON, EXPORT_DIR, FIX_KEYWORDS
    global FLAG_LIMIT, GOLD_ALLOW_1EXP_1CHEAP, GOLD_MIN_EXPENSIVE, JDK_AUTODETECT, JDK_IMAGE_TEMPLATE, KAMEI_ENABLED, LINE_WINDOW, M2_VOLUME
    global MAVEN_GOALS, MAVEN_IMAGE, MAX_FILES_PER_COMMIT, MAX_FILE_ADD_LINES, MAX_FILE_CHURN_LINES, MAX_FILE_DEL_LINES, NOISE_CWE, NOISE_RULES
    global PROGRESS_FILE, RUN_ID, SCAN_RESUME, SCAN_WORKERS, SILVER_MIN_CHEAP, SONAR_ADMIN_PW, SONAR_HOST_PORT, SQLITE_PATH
    global STALE_CLAIM_SEC, STOP_FILE, STORE_FULL_FILE, SUBMODULES, SUSPECT_REQUIRE_IN_DIFF, USE_CODEQL, VOTE_THRESHOLD, WORK_DIR

    # Nơi clone repo target + file tạm (Persistent Disk VM)
    WORK_DIR = Path(os.environ.get("ORCH_WORK_DIR") or (ROOT / "work"))
    # Nơi lưu dataset cuối (SQLite) — THẲNG trên VM, KHÔNG GCS
    data_dir = Path(os.environ.get("ORCH_DATA_DIR") or (ROOT / "data"))
    DATA_DIR = data_dir
    SQLITE_PATH = Path(os.environ.get("ORCH_SQLITE") or (data_dir / "dataset.sqlite"))
    EXPORT_DIR = Path(os.environ.get("ORCH_EXPORT_DIR") or (data_dir / "export"))

    # --- Lọc thô (Tầng ①) ---
    # Đường dẫn VENDORED/GENERATED — finding trong đó KHÔNG phải của dự án (nhiễu).
    EXCLUDE_PATH_PATTERNS = [p for p in os.environ.get(
        "ORCH_EXCLUDE_PATHS",
        "node_modules/,/vendor/,bower_components/,/dist/,/build/,/third_party/,"
        "/generated/,.min.js,.min.css,.pb.go,_pb2.py").split(",") if p]
    # Ngưỡng BỎ QUA commit "khổng lồ" (chỉ áp khi FLAG_LIMIT=1).
    MAX_FILES_PER_COMMIT = _int("ORCH_MAX_FILES_PER_COMMIT", "100")
    MAX_FILE_ADD_LINES = _int("ORCH_MAX_FILE_ADD_LINES", "1000")
    MAX_FILE_DEL_LINES = _int("ORCH_MAX_FILE_DEL_LINES", "1000")
    MAX_FILE_CHURN_LINES = _int("ORCH_MAX_FILE_CHURN_LINES", "2000")
    FLAG_LIMIT = _int("ORCH_FLAG_LIMIT", "0")

    # --- Thí nghiệm (TOOL_IDEA §13): tham số v1 KHOÁ trừ khi ORCH_EXPERIMENT=1 kèm lý do ---
    EXPERIMENT = _int("ORCH_EXPERIMENT", "0")
    EXPERIMENT_REASON = os.environ.get("ORCH_EXPERIMENT_REASON", "")

    # --- Consensus (Tầng ⑥) ---
    # ±W dòng để gộp 2 finding cùng (file, CWE). v1 = 3; ORCH_LINE_WINDOW CHỈ có hiệu lực khi experiment.
    lw = LINE_WINDOW_V1
    raw_lw = os.environ.get("ORCH_LINE_WINDOW")
    if raw_lw:
        try:
            want = int(raw_lw)
        except ValueError:
            want = None
        if want is None or want < 1:
            _warn("lw_bad", f"ORCH_LINE_WINDOW={raw_lw!r} không hợp lệ -> giữ {LINE_WINDOW_V1}")
        elif EXPERIMENT:
            lw = want
        elif want != LINE_WINDOW_V1:
            _warn("lw_noexp", f"ORCH_LINE_WINDOW={want} bị BỎ QUA (giữ {LINE_WINDOW_V1}) — "
                              "chỉ có hiệu lực khi ORCH_EXPERIMENT=1 kèm ORCH_EXPERIMENT_REASON")
    LINE_WINDOW = lw
    # legacy: giữ biến cho tương thích import; KHÔNG dùng trong labeler, KHÔNG ghi run_meta/hiển thị.
    VOTE_THRESHOLD = _int("ORCH_VOTE_THRESHOLD", "2")
    # Thang nhãn cross-tier (RULE_GAN_NHAN.md §4/§9). E=#tool đắt, C=#tool rẻ trong cụm.
    GOLD_MIN_EXPENSIVE = _int("ORCH_GOLD_MIN_EXPENSIVE", "2")
    GOLD_ALLOW_1EXP_1CHEAP = _int("ORCH_GOLD_ALLOW_1EXP_1CHEAP", "1")
    SILVER_MIN_CHEAP = _int("ORCH_SILVER_MIN_CHEAP", "2")
    # LỌC NHIỄU khi GÁN NHÃN (raw giữ nguyên — chỉ bỏ khỏi consensus).
    NOISE_CWE = set(_csv("ORCH_NOISE_CWE", "CWE-117"))
    NOISE_RULES = set(_csv("ORCH_NOISE_RULES", ""))

    # --- 14 đặc trưng Kamei ---
    KAMEI_ENABLED = _int("ORCH_KAMEI", "1")
    FIX_KEYWORDS = os.environ.get("ORCH_FIX_KEYWORDS", "fix,bug,defect,patch,fault,repair")

    # --- Ngữ cảnh file ---
    STORE_FULL_FILE = os.environ.get("ORCH_STORE_FULL_FILE") == "1"

    # --- Song song CẤP COMMIT (Tầng ②) ---
    SCAN_WORKERS = _int("ORCH_SCAN_WORKERS", "4")
    SCAN_RESUME = _int("ORCH_SCAN_RESUME", "1")
    SUBMODULES = _int("ORCH_SUBMODULES", "1")
    CHEAP_INTRA_PARALLEL = _int("ORCH_CHEAP_INTRA_PARALLEL", "1")
    EXPENSIVE_INTRA_PARALLEL = _int("ORCH_EXPENSIVE_INTRA_PARALLEL", "0")
    # Tool tầng RẺ bật (thứ tự chạy). Bỏ tool -> đổi mẫu số eligible/κ (cảnh báo ở CLI).
    CHEAP_TOOLS = _csv("ORCH_CHEAP_TOOLS", ",".join(CHEAP_TOOLS_ALL))

    # --- Chọn commit lên TẦNG ĐẮT ---
    SUSPECT_REQUIRE_IN_DIFF = os.environ.get("ORCH_SUSPECT_REQUIRE_IN_DIFF") == "1"

    # --- TẦNG ĐẮT ---
    EXPENSIVE_WORKERS = _int("ORCH_EXPENSIVE_WORKERS", "2")
    EXPENSIVE_TOOLS = _csv("ORCH_EXPENSIVE_TOOLS", "codeql,findsecbugs,sonar")
    USE_CODEQL = _int("ORCH_USE_CODEQL", "1")
    MAVEN_IMAGE = os.environ.get("ORCH_MAVEN_IMAGE", "maven:3.9-eclipse-temurin-8")
    JDK_AUTODETECT = _int("ORCH_JDK_AUTODETECT", "1")
    JDK_IMAGE_TEMPLATE = os.environ.get("ORCH_JDK_IMAGE_TEMPLATE", "maven:3.9-eclipse-temurin-{jdk}")
    MAVEN_GOALS = os.environ.get("ORCH_MAVEN_GOALS", "-B clean package -DskipTests")
    BUILD_TIMEOUT = _int("ORCH_BUILD_TIMEOUT", "1800")
    CODEQL_RAM_MB = _int("ORCH_CODEQL_RAM_MB", "20000")
    CODEQL_THREADS = _int("ORCH_CODEQL_THREADS", "0")
    CODEQL_SUITE = os.environ.get(
        "ORCH_CODEQL_SUITE", "codeql/java-queries:codeql-suites/java-code-scanning.qls")
    SONAR_ADMIN_PW = os.environ.get("ORCH_SONAR_ADMIN_PW", "Orch_2026!")
    SONAR_HOST_PORT = _int("ORCH_SONAR_PORT", "9000")
    STALE_CLAIM_SEC = _int("ORCH_STALE_CLAIM_SEC", "7200")
    # Số infra_error LIÊN TIẾP trước khi run tự dừng (CONTRACTS §1; expensive_runner đọc env trực tiếp).
    INFRA_STOP_AFTER = _int("ORCH_INFRA_STOP_AFTER", "3")
    # Volume Docker đặt tên cho cache Maven (placeholder — A1/build.py quyết cách dùng; rỗng = bind .m2cache).
    M2_VOLUME = os.environ.get("ORCH_M2_VOLUME", "")

    # --- Run / tiến độ (CONTRACTS §3) ---
    RUN_ID = os.environ.get("ORCH_RUN_ID", "local")
    PROGRESS_FILE = os.environ.get("ORCH_PROGRESS_FILE", "")
    STOP_FILE = os.environ.get("ORCH_STOP_FILE", "")
    APP_VERSION = os.environ.get("SECJIT_APP_VERSION", "dev")


def params_v1() -> dict:
    """Tham số gán nhãn hiệu lực (cùng khoá với profile.params_v1)."""
    return {
        "line_window": LINE_WINDOW,
        "gold_min_expensive": GOLD_MIN_EXPENSIVE,
        "gold_allow_1exp_1cheap": GOLD_ALLOW_1EXP_1CHEAP,
        "silver_min_cheap": SILVER_MIN_CHEAP,
        "noise_cwe": sorted(NOISE_CWE),
    }


def experiment_info() -> dict | None:
    """None khi chạy cấu hình v1; {"enabled":True,"reason":...} khi ORCH_EXPERIMENT=1."""
    if not EXPERIMENT:
        return None
    return {"enabled": True, "reason": EXPERIMENT_REASON}


def effective_env() -> dict[str, str]:
    """Các ORCH_* đang có trong env (bỏ bí mật) — ghi vào run_meta.config_snapshot_json."""
    return {k: os.environ[k] for k in ENV_KEYS if k in os.environ and k not in SECRET_ENV_KEYS}


def ensure_dirs() -> None:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)


# Khai báo kiểu cho linter/IDE — giá trị thật gán trong reload().
APP_VERSION = None
BUILD_TIMEOUT = None
CHEAP_INTRA_PARALLEL = None
CHEAP_TOOLS = None
CODEQL_RAM_MB = None
CODEQL_SUITE = None
CODEQL_THREADS = None
DATA_DIR = None
EXCLUDE_PATH_PATTERNS = None
EXPENSIVE_INTRA_PARALLEL = None
EXPENSIVE_TOOLS = None
EXPENSIVE_WORKERS = None
EXPERIMENT = None
EXPERIMENT_REASON = None
EXPORT_DIR = None
FIX_KEYWORDS = None
FLAG_LIMIT = None
GOLD_ALLOW_1EXP_1CHEAP = None
GOLD_MIN_EXPENSIVE = None
JDK_AUTODETECT = None
JDK_IMAGE_TEMPLATE = None
KAMEI_ENABLED = None
LINE_WINDOW = None
M2_VOLUME = None
MAVEN_GOALS = None
MAVEN_IMAGE = None
MAX_FILES_PER_COMMIT = None
MAX_FILE_ADD_LINES = None
MAX_FILE_CHURN_LINES = None
MAX_FILE_DEL_LINES = None
NOISE_CWE = None
NOISE_RULES = None
PROGRESS_FILE = None
RUN_ID = None
SCAN_RESUME = None
SCAN_WORKERS = None
SILVER_MIN_CHEAP = None
SONAR_ADMIN_PW = None
SONAR_HOST_PORT = None
SQLITE_PATH = None
STALE_CLAIM_SEC = None
STOP_FILE = None
STORE_FULL_FILE = None
SUBMODULES = None
SUSPECT_REQUIRE_IN_DIFF = None
USE_CODEQL = None
VOTE_THRESHOLD = None
WORK_DIR = None
INFRA_STOP_AFTER = None

reload()
