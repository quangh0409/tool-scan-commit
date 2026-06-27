# CLAUDE.md

> Hướng dẫn cho Claude Code khi làm việc trong repo này. Đọc file này + `TOOL_IDEA_CONTEXT.md` + `SESSION_CONTEXT.md` đầu mỗi phiên để bootstrap.

## Dự án là gì (1 dòng)
Orchestrator: input = 1 link GitHub → duyệt từng commit → chạy nhiều tool SAST → chuẩn hoá về SARIF → bỏ phiếu đồng thuận (consensus) → xuất **ground-truth dataset** (mỗi dòng = 1 finding / 1 cụm đồng thuận). Nhãn = **CWE-class**, không phải CVE.

→ Chi tiết mục tiêu / quyết định kiến trúc: đọc **`TOOL_IDEA_CONTEXT.md`** (đừng lặp lại nội dung đó ở đây).
→ Tiến độ hiện tại / việc đang làm: đọc **`SESSION_CONTEXT.md`**.

## Ngôn ngữ
- **Trả lời người dùng bằng TIẾNG VIỆT.**

## Nguyên tắc cốt lõi phải nhớ (đừng vi phạm)
1. **Consensus = nhãn BẠC (silver label), KHÔNG phải chân lý.** Luôn kèm confidence + Fleiss' kappa + GOLD set validate tay.
2. **Kiến trúc PHỄU là điều kiện sống còn** (ngân sách GCP $300 hữu hạn): tool rẻ (source-only, trên diff) lọc trước → chỉ thả tool đắt (CodeQL/FindSecBugs/Sonar, cần build) vào số commit ít ỏi được chọn. Núm chi phí = top-K ở Tầng ③.
3. **Cột CVE gần như luôn null** — SAST không sinh CVE. Chỉ là cột enrichment tuỳ chọn (mine từ fix-commit).
4. **Dataset lưu THẲNG trên Persistent Disk của VM — KHÔNG dùng GCS bucket.** Chỉ STOP VM (đừng DELETE) để khỏi mất dữ liệu; muốn an toàn thì tải bản sao về HDD local.

## Môi trường (VM cloud GCP — Ubuntu 22.04, x86_64)
- Toàn bộ pipeline chạy trên **1 VM GCP** (`e2-standard-8`), on-demand: bật khi cần, **STOP** khi xong.
- Đã cài: **Git 2.34.1**, **Docker Engine 29.6.1** (daemon active), **Docker Compose v5.2.0**.
- `scanner` đã thuộc nhóm `docker`.

### ⚠️ GOTCHA Docker + nhóm
Nếu phiên Claude Code này khởi động *trước* khi `scanner` được thêm vào nhóm `docker`, tiến trình vẫn giữ nhóm cũ → gọi `docker` trực tiếp bị `permission denied`.
- **Cách kiểm tra:** chạy `id`; nếu **không** thấy `docker` trong groups → đang dính gotcha.
- **Workaround ngay:** bọc lệnh qua `sg docker -c "docker ..."`.
- **Sửa triệt để:** thoát hẳn Claude Code → đăng nhập SSH mới → chạy lại `claude`. Sau đó `id` có `docker`, gọi `docker` thẳng được.

### Sudo
- `scanner` ở nhóm `sudo` nhưng sudo **đòi mật khẩu** và phiên không có terminal → Claude **không tự chạy sudo được**.
- Khi cần sudo: yêu cầu người dùng tự gõ vào ô chat dạng `! <lệnh>` (chạy trong phiên, nhập mật khẩu tại terminal của họ).

## Stack kỹ thuật (dự kiến)
- Python orchestrator · mỗi tool 1 Docker · lưu SQLite/Parquet.
- Chuẩn hoá về **SARIF 2.1.0**; adapter riêng cho FindSecBugs (SpotBugs XML), Bearer, Horusec (JSON).
- Matcher/consensus: cụm finding theo `(file chuẩn hoá, CWE, line ±W)` → đếm vote.

## Tool theo tầng
- **Tầng rẻ (source-only, trên diff, không build):** gitleaks, trufflehog, Semgrep, Bearer, Horusec.
- **Tầng đắt (cần build):** CodeQL, FindSecBugs (SpotBugs), SonarQube (`sonarqube:lts-community` ephemeral).

## Repo pilot
`https://github.com/FudanSELab/train-ticket` — Spring Boot microservices, Maven đa-module. Pilot chạy ~50–100 commit đầu để kiểm thử pipeline trước khi mở rộng (Jenkins/Spring Cloud).

## Quy ước làm việc
- Cập nhật **`SESSION_CONTEXT.md`** cuối mỗi phiên (hoặc khi đạt mốc): việc đã xong, việc đang dở, việc kế tiếp.
- `TOOL_IDEA_CONTEXT.md` = ý tưởng/quyết định kiến trúc (chỉ sửa khi có quyết định mới). `SESSION_CONTEXT.md` = tiến độ. **Không trộn lẫn.**
