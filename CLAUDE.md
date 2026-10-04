# CLAUDE.md

> Hướng dẫn cho Claude Code khi làm việc trong repo này. Đọc file này + `TOOL_IDEA_CONTEXT.md` + `SESSION_CONTEXT.md` đầu mỗi phiên để bootstrap.

## Dự án là gì (1 dòng)
Orchestrator: input = 1 link GitHub → duyệt từng commit → chạy nhiều tool SAST → bỏ phiếu đồng thuận (consensus) → xuất **ground-truth dataset** (mỗi dòng = 1 finding / 1 cụm đồng thuận). Nhãn = **CWE-class**, không phải CVE.

| Cần gì | Đọc file |
|---|---|
| Mục tiêu / quyết định kiến trúc | `TOOL_IDEA_CONTEXT.md` (đừng lặp lại nội dung đó ở đây) |
| Tiến độ, việc đang dở, repo đã chạy | `SESSION_CONTEXT.md` |
| Runbook lệnh chạy đầy đủ | `README.md` |
| Bảng đủ mọi env `ORCH_*` | `GUIDE.md` §3 (khớp `src/orchestrator/config.py`) |
| Luật gán nhãn gold/silver/candidate | `RULE_GAN_NHAN.md` |
| Tầng đắt (build, CodeQL, FindSecBugs, Sonar) | `EXPENSIVE_TIER_REPORT.md` |
| Sơ đồ luồng, outline tool | `EXECUTION_FLOW.md`, `TOOL_OUTLINE.md`, `SCAN_MECHANISM.md` |

## Ngôn ngữ
- **Trả lời người dùng bằng TIẾNG VIỆT.** Commit message cũng tiếng Việt.

## Hai môi trường — đừng nhầm
- **Checkout này (Windows, `D:\Master's thesis\tool-scan-commit`):** chỉ sửa code/docs, commit, push. **Chạy thử local được** (từ 2026-10-04, Docker Desktop) nhưng chỉ để smoke-test vài commit: build Maven cold ~15 phút/commit (bind mount chậm), máy dễ treo khi build + Sonar cùng lúc. Bắt buộc `ORCH_SONAR_PORT=9100` (port 9000 bị container `giapha-minio` chiếm), `PYTHONIOENCODING=utf-8`, trỏ `ORCH_WORK_DIR`/`ORCH_DATA_DIR` ra ngoài repo. `scripts/*` vẫn hardcode `/home/scanner/...` (chỉ chạy trên VM). Đường dẫn có dấu `'` → luôn quote.
- **VM GCP (Ubuntu 22.04, `e2-standard-8`, user `scanner`):** nơi duy nhất chạy pipeline + Docker. On-demand: bật khi cần, **STOP** khi xong. Các gotcha `sg docker`/sudo bên dưới chỉ áp cho VM.

## Nguyên tắc cốt lõi phải nhớ (đừng vi phạm)
1. **Consensus = nhãn BẠC (silver label), KHÔNG phải chân lý.** Luôn kèm confidence + Fleiss' kappa + GOLD set validate tay.
2. **Kiến trúc PHỄU là điều kiện sống còn** (ngân sách GCP $300 hữu hạn): tool rẻ (source-only, trên diff) lọc trước → chỉ thả tool đắt (CodeQL/FindSecBugs/Sonar, cần build) vào commit buggy được chọn. **Không có top-K trong code** — `select` lấy toàn bộ buggy (+ clean qua `--include-clean`). Núm chi phí thật: `--codeql 0/1` (mọi run thật đều dùng `--codeql 0`), `ORCH_EXPENSIVE_WORKERS`, `ORCH_CODEQL_SUITE` (mặc định suite full `java-code-scanning.qls` ~20'/commit; suite tối giản `/opt/minimal-java.qls` ~6.7').
3. **Cột CVE gần như luôn null** — SAST không sinh CVE. Chỉ là cột enrichment tuỳ chọn (mine từ fix-commit).
4. **Dataset lưu THẲNG trên Persistent Disk của VM — KHÔNG dùng GCS bucket.** Chỉ STOP VM (đừng DELETE) để khỏi mất dữ liệu; muốn an toàn thì tải bản sao về HDD local.

## Chạy & kiểm thử
- Python **stdlib-only** (3.10+), KHÔNG có pip install, KHÔNG có test. Xác minh = chạy smoke trên scratch DB (`ORCH_SQLITE=/tmp/x.sqlite ... scan <url> --max 3`).
- Lint: `python -m ruff check src scripts` (config `pyproject.toml`, chỉ bật lỗi thật F/E9 — không ép style). Chạy sau khi sửa code Python.
- Chạy CLI từ gốc repo: `PYTHONPATH=src python3 -m orchestrator.cli <enumerate|scan|select|analyze|relabel|kappa|features|export|pipeline|clean>`.
- Mỗi tool wrapper parse thẳng output của nó → `RawFinding`; `normalize/` chỉ là stub. Raw SARIF/XML/JSON lưu bảng `raw_output` để audit. Lưu SQLite (không Parquet).
- `LINE_WINDOW=3` là **hằng số** trong `config.py` (không phải env). W=7 chỉ dùng cho gold qua `scripts/relabel_gold_w7.py` trên bản copy DB, không đụng DB chính.
- `relabel`, `kappa`, `export` rẻ và idempotent — chạy lại thoải mái.

## Gotcha vận hành (VM)
- **1 repo = 1 DB + 1 export:** luôn set `ORCH_SQLITE=data/dataset_<tên>.sqlite` và `--out data/export_<tên>`. Kiểm tra nhánh bằng `git ls-remote` trước (giraph dùng `trunk`, nhiều repo dùng `master`).
- `--max` mặc định **50** → full history phải `--max 0`.
- `export` **KHÔNG sinh** `dataset.jsonl`/`commits.jsonl` — phải chạy `scripts/merge_export.py <export_dir> <db>` sau.
- `clean --export` xoá `ORCH_EXPORT_DIR` (mặc định `data/export` — là export spring-cloud-stream, KHÔNG phải `--out`); `clean --db` xoá DB theo `ORCH_SQLITE` (mặc định `data/dataset.sqlite` = pilot train-ticket). **Set env đúng trước khi gọi `clean`.**
- Run chết giữa chừng: **KHÔNG chạy lại `pipeline`**; chạy `analyze → relabel → kappa → export` (mẫu: `scripts/resume_skywalking.sh`). Trước khi kết luận xong, kiểm `selected_commits` còn `building`/`analyzing` mồ côi; kill tay thì dọn container sonar-scanner/maven/`orch-sonar` + network `orch-sonar-net`.
- Run dài phải `setsid nohup ... < /dev/null &` — run skywalking đã chết một lần theo phiên SSH/Claude.
- Sonar bắt buộc `sonar.java.libraries=/m2 jar` (thiếu → 0 finding); `sysctl vm.max_map_count=262144` reset sau reboot (cần user sudo).
- κ Fleiss **âm** (−0.26 … −0.47) là bình thường trên mọi repo, không phải bug.

### ⚠️ GOTCHA Docker + nhóm (VM)
Nếu phiên Claude Code khởi động *trước* khi `scanner` được thêm vào nhóm `docker`, tiến trình vẫn giữ nhóm cũ → gọi `docker` trực tiếp bị `permission denied`.
- **Kiểm tra:** chạy `id`; nếu **không** thấy `docker` → đang dính gotcha.
- **Workaround:** bọc lệnh qua `sg docker -c "docker ..."` hoặc set `ORCH_DOCKER_SG=1`.
- **Sửa triệt để:** thoát hẳn Claude Code → đăng nhập SSH mới → chạy lại `claude`.

### Sudo (VM)
- `scanner` ở nhóm `sudo` nhưng sudo **đòi mật khẩu** và phiên không có terminal → Claude **không tự chạy sudo được**.
- Khi cần sudo: yêu cầu người dùng tự gõ vào ô chat dạng `! <lệnh>`.

## Tool theo tầng
- **Tầng rẻ (source-only, trên diff, không build):** gitleaks, trufflehog, Semgrep, Bearer, Horusec (image `:latest`, chưa pin).
- **Tầng đắt (cần build Maven, chỉ module bị đụng `-pl <mods> -am`):** CodeQL (`orch-codeql:2.25.6`), FindSecBugs (`orch-findsecbugs:1.14.0`), SonarQube (`sonarqube:lts-community` ephemeral). Dockerfile ở `docker/`.

## Repo đã chạy & chọn repo tiếp
Đã chạy full-history 5 repo: train-ticket, mall-swarm, spring-cloud-stream, spring-cloud-kubernetes, giraph; skywalking đang chạy (xem `SESSION_CONTEXT.md`). Chọn repo tiếp theo ưu tiên **app thuần Java/Maven**, tránh library Spring (dependency `*-SNAPSHOT` biến mất → build fail ~87%).

## Quy ước làm việc
- Làm trên branch **`dev`** (`main` chỉ có initial commit). **Commit ngay sau mỗi fix** thay vì để dồn — nhật ký phiên cho thấy nhiều fix bị quên commit.
- Cập nhật **`SESSION_CONTEXT.md`** cuối mỗi phiên (hoặc khi đạt mốc): việc đã xong, việc đang dở, việc kế tiếp. Phiên mới nhất ở trên cùng.
- `TOOL_IDEA_CONTEXT.md` = ý tưởng/quyết định kiến trúc (chỉ sửa khi có quyết định mới). `SESSION_CONTEXT.md` = tiến độ. **Không trộn lẫn.**
