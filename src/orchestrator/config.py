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

# --- Lọc thô (Tầng ①) ---
SKIP_MERGE_COMMITS = True
# đuôi file coi là "code đáng quét" cho pilot (Java là chính)
CODE_EXTENSIONS = {".java", ".xml", ".properties", ".yml", ".yaml", ".py", ".ts", ".js", ".sql"}
# coi là docs/non-code -> bỏ qua khi xét commit
DOC_EXTENSIONS = {".md", ".txt", ".rst", ".adoc", ".png", ".jpg", ".gif", ".svg", ".pdf"}

# Ngưỡng BỎ QUA commit "khổng lồ" (diff quá lớn = bulk/generated, quét tốn & loãng tín hiệu).
# Xét theo MỨC THAY ĐỔI của commit LÊN TỪNG FILE (add/del trong diff), KHÔNG phải kích thước file:
#   - commit đụng > MAX_FILES_PER_COMMIT file (mọi loại) -> bỏ.
#   - BẤT KỲ file nào có add > MAX_FILE_ADD_LINES, HOẶC del > MAX_FILE_DEL_LINES,
#     HOẶC (add + del) > MAX_FILE_CHURN_LINES -> bỏ.
MAX_FILES_PER_COMMIT = int(os.environ.get("ORCH_MAX_FILES_PER_COMMIT", "100"))
MAX_FILE_ADD_LINES = int(os.environ.get("ORCH_MAX_FILE_ADD_LINES", "1000"))
MAX_FILE_DEL_LINES = int(os.environ.get("ORCH_MAX_FILE_DEL_LINES", "1000"))
MAX_FILE_CHURN_LINES = int(os.environ.get("ORCH_MAX_FILE_CHURN_LINES", "2000"))

# --- Consensus (Tầng ⑥) ---
LINE_WINDOW = 3  # ±W dòng để gộp 2 finding cùng (file, CWE)
# ngưỡng số tool đồng thuận để gán nhãn "vuln"; 1..K-1 => "candidate"; 0 => "clean"
VOTE_THRESHOLD = int(os.environ.get("ORCH_VOTE_THRESHOLD", "2"))

# --- Ngữ cảnh file ---
# Mặc định CHỈ lưu permalink (rẻ). Bật để lưu thêm toàn văn code_before/code_after (nặng).
STORE_FULL_FILE = os.environ.get("ORCH_STORE_FULL_FILE") == "1"

# --- Song song CẤP COMMIT (Tầng ②) ---
# Số clone-pool xử lý commit ĐỒNG THỜI. Mỗi worker xử trọn 1 commit (5 tool tuần tự
# bên trong) -> tối đa SCAN_WORKERS container chạy cùng lúc. Đặt ~ số vCPU, chừa RAM.
SCAN_WORKERS = int(os.environ.get("ORCH_SCAN_WORKERS", "4"))

# --- Repo pilot ---
PILOT_REPO = "https://github.com/FudanSELab/train-ticket"
PILOT_MAX_COMMITS = 50


def ensure_dirs() -> None:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
