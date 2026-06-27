# tool-scan-commit

Orchestrator: 1 link GitHub → duyệt commit → nhiều tool SAST (Docker) → chuẩn hoá SARIF → bỏ phiếu đồng thuận → **ground-truth dataset** (mỗi dòng có `cwe` + `s_line` bắt buộc). Nhãn = CWE-class.

📄 Ý tưởng/kiến trúc: `TOOL_IDEA_CONTEXT.md` · Tiến độ: `SESSION_CONTEXT.md` · Cách làm việc: `CLAUDE.md`.

## Yêu cầu
- Python 3.10+ (orchestrator chỉ dùng **stdlib**, không cần pip).
- Docker (các tool SAST chạy trong container).

## Chạy thử (pilot — train-ticket)

```bash
cd src

# 1) Liệt kê + lọc thô commit (KHÔNG cần Docker)
python -m orchestrator.cli enumerate https://github.com/FudanSELab/train-ticket --max 50

# 2) Quét tool tầng rẻ -> consensus -> SQLite
#    (thêm ORCH_DOCKER_SG=1 nếu tiến trình chưa thuộc nhóm docker)
ORCH_DOCKER_SG=1 python -m orchestrator.cli scan https://github.com/FudanSELab/train-ticket --max 50
```

Output: `data/dataset.sqlite` (lưu thẳng trên VM, không GCS).

## Cấu trúc

```
src/orchestrator/
  schema.py            # RawFinding + DatasetRow (ép cwe + s_line bắt buộc)
  config.py            # đường dẫn, ngưỡng, repo pilot
  enumerate_commits.py # Tầng ① git enumerate + lọc thô
  tools/               # Tầng ②/④ wrapper Docker: base, gitleaks, semgrep
  normalize/           # Tầng ⑤ adapter SARIF (FindSecBugs/Bearer/Horusec — Bước 2)
  consensus/matcher.py # Tầng ⑥ gộp cụm + bỏ phiếu + confidence
  storage/sqlite_store.py
  cli.py               # entrypoint nối phễu
```

## Trạng thái
Bước 1 — skeleton + pipeline source-only (gitleaks + semgrep). Xem `SESSION_CONTEXT.md`.
