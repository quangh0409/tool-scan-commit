# SESSION_CONTEXT

> Nhật ký tiến độ — cập nhật MỖI phiên (hoặc khi đạt mốc). Ghi: đã xong / đang dở / kế tiếp.
> File này KHÔNG ghi mục tiêu hay quyết định kiến trúc (cái đó ở `TOOL_IDEA_CONTEXT.md`).
> Phiên mới nhất ở TRÊN CÙNG.

---

## Trạng thái tổng quan (cập nhật nhanh)

- **Giai đoạn:** Bước 0 — dựng VM + môi trường.
- **Việc kế tiếp:** Bước 1 — skeleton + pipeline source-only (git enumerate → tool tầng rẻ qua Docker → normalize → consensus → SQLite), test ~50 commit train-ticket.
- **Repo này đã là git repo?** Chưa (`git init` khi bắt đầu Bước 1).

---

## Phiên 2026-06-27

### Đã xong
- Đọc & nắm `TOOL_IDEA_CONTEXT.md`.
- **Quyết định mới:** dataset lưu THẲNG trên Persistent Disk VM, **bỏ GCS bucket** (đã cập nhật vào `TOOL_IDEA_CONTEXT.md`, mục §8/§9/§12).
- **Setup môi trường VM (Ubuntu 22.04, x86_64):**
  - Git 2.34.1 (có sẵn).
  - Cài Docker Engine 29.6.1 qua `get.docker.com` (daemon active).
  - Docker Compose plugin v5.2.0.
  - Thêm `scanner` vào nhóm `docker` (`usermod -aG docker`); xác nhận chạy được qua `docker run hello-world`.
- Viết `CLAUDE.md` + tạo `SESSION_CONTEXT.md` (file này).

### Đang dở / lưu ý
- ⚠️ Tiến trình Claude Code hiện tại vẫn giữ nhóm cũ (chưa có `docker` trong `id`) → tạm thời gọi docker qua `sg docker -c "..."`. Sửa triệt để: thoát claude → SSH login mới → chạy lại `claude`.

### Kế tiếp (Bước 1)
1. `git init` repo này + cấu trúc thư mục Python orchestrator.
2. Module git enumerate (clone repo target → liệt kê commit, lọc thô merge/docs/non-Java).
3. Wrapper Docker cho tool tầng rẻ (bắt đầu gitleaks + Semgrep) chạy trên diff.
4. Normalize → SARIF → consensus đơn giản → ghi SQLite.
5. Chạy thử ~50 commit đầu của train-ticket. Chứng minh end-to-end.
