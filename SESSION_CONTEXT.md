# SESSION_CONTEXT

> Nhật ký tiến độ — cập nhật MỖI phiên (hoặc khi đạt mốc). Ghi: đã xong / đang dở / kế tiếp.
> File này KHÔNG ghi mục tiêu hay quyết định kiến trúc (cái đó ở `TOOL_IDEA_CONTEXT.md`).
> Phiên mới nhất ở TRÊN CÙNG.

---

## Trạng thái tổng quan (cập nhật nhanh)

- **Giai đoạn:** Bước 1 XONG — tầng rẻ 5 tool + CWE-grouping + category + song song. **Pilot train-ticket đã chạy xong** (29 commit giữ/50, 2951 cụm, ~9 phút).
- **Việc kế tiếp:** Bước 2 (tool tầng đắt: CodeQL/FindSecBugs/Sonar) — đây mới là nguồn consensus code-vuln thật. Tầng rẻ đã xác nhận chỉ là candidate-generator.
- **Repo này đã là git repo?** Rồi.
- **5 tool tầng rẻ:** secret = gitleaks+trufflehog(+horusec Leaks); code = semgrep(p/default)+bearer(+horusec). VOTE_THRESHOLD=2.

---

## Phiên 2026-06-28 (b) — Song song CẤP COMMIT + ngưỡng bỏ commit khổng lồ

**Vì sao:** quét tuần tự từng commit là nút thắt khi scale nghìn commit. (Đã bàn & loại phương án Java virtual-thread: workload CPU/container-bound, chặn ở số core chứ không số thread — vthread vô ích. Mô hình đúng = worker-pool *bounded* ≈ vCPU, song song ở CẤP COMMIT.)

### Đã làm
- **`repo_pool.py` (RepoPool):** pool K clone độc lập qua `git clone --local --no-checkout` (object hardlink → ~0 đĩa/0.3s/clone). KHÔNG dùng `git worktree` vì worktree để `.git` là *file* `gitdir:` → mount thư mục lẻ vào container thì tool git-mode (gitleaks/trufflehog) gãy; clone cho `.git` *thư mục thật* → mọi wrapper chạy y nguyên. Mỗi clone tái sử dụng qua nhiều commit (`checkout --detach`).
- **`cli.py` cmd_scan viết lại:** `ThreadPoolExecutor(SCAN_WORKERS)` xử commit SONG SONG; mỗi worker chiếm 1 clone, checkout, chạy **5 tool TUẦN TỰ** bên trong → tối đa SCAN_WORKERS container cùng lúc (bounded, không thrash). Bỏ checkout/khôi-phục HEAD trên main repo (không còn đụng main).
- **`sqlite_store.py` thread-safe:** `check_same_thread=False` + `threading.Lock` bọc mọi ghi.
- **Ngưỡng bỏ commit khổng lồ (yêu cầu người dùng — theo DIFF, không theo kích thước file):**
  - `> MAX_FILES_PER_COMMIT` (mặc định 100) file → bỏ.
  - BẤT KỲ file nào có add>1000 HOẶC del>1000 HOẶC (add+del)>2000 → bỏ.
  - Cả 2 check ở `coarse_filter` (lúc enumerate, dùng numstat có sẵn — HEAD-independent, không checkout).
  - Env: `ORCH_MAX_FILES_PER_COMMIT`, `ORCH_MAX_FILE_ADD_LINES`, `ORCH_MAX_FILE_DEL_LINES`, `ORCH_MAX_FILE_CHURN_LINES`, `ORCH_SCAN_WORKERS`.

### Smoke-test (train-ticket --max 12, 4 worker) — PASS
- 8 commit giữ (commit 983-file `fa8d9efb` bị lọc do >100 file), **3 BỎ QUA** vì đụng file k8s yml >1000 dòng (2248/2012), 5 commit quét thật.
- 161 finding đều hợp lệ (s_line>0, cwe đủ). trufflehog git-mode chạy OK trên clone ⇒ rủi ro `.git`-trong-container đã xử lý. Không lỗi giữa chừng.

### ⚠️ BUG ĐÚNG ĐẮN đã phát hiện & SỬA — trufflehog over-scan
- **Bug:** trufflehog git-mode quét theo MỌI REF (master), KHÔNG theo HEAD. Chỉ dùng `--since-commit <SHA>~1` → quét cả dải `<SHA>..master` rồi gán nhầm hết về `commit_id`. Đã kiểm: detach tại OLD vẫn báo secret của hậu duệ `fa8d9efb`. **Tồn tại từ thiết kế cũ** → dữ liệu trufflehog pilot trước (145) bị nhân bản/gán sai.
- **Sửa:** thêm `--branch <SHA>` (giới hạn reachable-từ-SHA) kèm `--since-commit <SHA>~1` → quét ĐÚNG 1 commit. Kiểm qua wrapper: scan FA→5 finding đều ∈ changed; scan OLD→0 (hết gán nhầm).
- **Tài liệu mới:** `SCAN_MECHANISM.md` — cơ chế scan từng tool + 6 bất biến đúng đắn (I1–I6) + bằng chứng + giới hạn.

### Kế tiếp (chưa làm)
- **Chạy lại pilot** (số liệu trufflehog cũ KHÔNG còn tin được sau fix) + đo throughput vs ~9' tuần tự.
- Loại trừ `node_modules`/vendored trước khi quét (trufflehog FP trong `@types/node/*.d.ts`).
- Đòn bẩy tiếp: **container ấm** (docker exec) + **cache theo blob-sha**.

---

## Phiên 2026-06-28 — Kết quả pilot tầng rẻ (sau CWE-grouping + category + song song)

**Pilot:** `train-ticket --max 50` → 29 commit giữ lại, 2951 cụm, chạy ~9 phút (19:20→19:29). Song song hoá 5 tool/commit OK, không lỗi giữa chừng, HEAD khôi phục đúng.

### Số liệu chính
- **Nhãn:** vuln=3, candidate=2948, clean(negative file)=1452 (trên 1626 file quét).
- **3 vuln (≥2 tool đồng thuận):**
  - `ts-ui-dashboard/.../index.js:18` — CWE-798 hardcoded_secret — **bearer+horusec**.
  - 2× `old-docs/.../*.java` — CWE-330 weak_random — **bearer+semgrep** ← *thắng nhờ CWE-grouping* (bearer+semgrep cùng quy về nhóm `weak_random`).
- **Category (tách nhiễu infra):** infra=2558 (**86.7%** — toàn permissions CWE-732 + privilege CWE-250 từ Dockerfile/k8s), secret=161, info=130, code=36, crypto=36, other=30.
  - → **Bỏ infra-noise** thì chỉ còn **233** candidate code/secret/crypto đáng xét. code thật: sql_injection=11, xss=12, csrf=6, code_injection=3, path_traversal=2.
- **finding_in_diff:** chỉ 360/2951 (12%) là do commit này tạo; 2591 là nợ cũ. Lọc `finding_in_diff=1` cắt còn 360.
- **secret verified:** **0/145 verified** (toàn unverified — train-ticket dùng cred test/example, tín hiệu secret yếu).
- **Đóng góp tool:** semgrep=2590, bearer=179, trufflehog=145, horusec=40, **gitleaks=0** (đúng kỳ vọng: gitleaks chặt hơn, loại key example).

### Kết luận
- 3 cải tiến hoạt động: **song song** (~9'), **CWE-grouping** (tạo ra 2 vuln weak_random bearer+semgrep), **category** (tách sạch 86.7% infra noise → còn 233 candidate thật).
- **Tầng rẻ vẫn chỉ ra 3 vuln** → RE-XÁC NHẬN thiết kế phễu: cheap-tier = candidate generator, consensus code-vuln thật phải nhờ **tầng đắt**. Giá trị tầng rẻ là khả năng *cắt nhiễu* (category + finding_in_diff + verified) trước khi thả tool đắt.

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

### Đã xong (Bước 1 — skeleton)
- `git init` + commit "init". Cấu trúc `src/orchestrator/` (stdlib-only, không cần pip).
- `schema.py`: `RawFinding` + `DatasetRow`, hàm `validate()` ÉP `cwe` không rỗng + `s_line>0` (yêu cầu người dùng). `normalize_cwe()`.
- `enumerate_commits.py` (Tầng ①): clone/update, list commit, `get_commit_info`, `coarse_filter` (bỏ merge/docs/non-code). Test trên repo local OK.
- `tools/`: `base.ToolWrapper` + `docker_run` (tự bọc `sg docker -c` khi ORCH_DOCKER_SG=1); `gitleaks.py` (map cứng CWE-798), `semgrep.py` (p/security-audit + p/secrets, lấy CWE từ metadata).
- `consensus/matcher.py` (Tầng ⑥): gộp cụm `(file, CWE giao nhau, |s_line|≤W)`, vote → confidence = n_agree/n_ran, silver_label. Test 2-tool-1-cụm OK.
- `storage/sqlite_store.py`: ghi SQLite, cwe/agreeing_tools → JSON. Round-trip OK.
- `cli.py`: lệnh `enumerate` (không cần Docker) + `scan` (full phễu). `README.md`.
- **Unit test (không Docker) PASS:** normalize_cwe, validate ép cwe/s_line, consensus, enumerate local, storage.

### Bổ sung schema (yêu cầu người dùng — cùng phiên)
- `s_detail_line: list[int]` — các dòng cụ thể gây lỗi (BẮT BUỘC; default = dải s_line..e_line; consensus gộp union các tool).
- `diff_parsed: {"added":[[ln,txt]],"deleted":[[ln,txt]]}` — parser `git show --unified=0` trong `enumerate_commits.get_file_diffs()`.
- `code_before_url`/`code_after_url` — permalink GitHub theo SHA (`blob_url()`), luôn lưu (rẻ).
- `code_before`/`code_after` — toàn văn file, TUỲ CHỌN (mặc định TẮT; bật `ORCH_STORE_FULL_FILE=1`) để khỏi nặng DB.
- Đã thêm cột tương ứng vào SQLite + test pass (diff parser, s_detail_line, urls, round-trip).
- ⚠️ Schema SQLite đổi → xoá `data/dataset.sqlite` cũ trước khi chạy lại (CREATE IF NOT EXISTS không tự migrate).

### Red-team + hướng A (cùng phiên) — ĐÃ XONG
- Red-team output: nêu các lỗ hổng (gán nợ cũ cho commit, thiếu negative, quét toàn cây, leakage commit_message, overclaim "ground truth", thiếu version pin, correlated errors, CWE-intersection làm vỡ consensus, dedup...).
- **Hướng A (3 fix):** (1) quét diff-scoped (semgrep file đổi, gitleaks git-mode); (2) `finding_in_diff`; (3) nhãn `vuln/candidate/clean` theo `VOTE_THRESHOLD` + bảng `scanned_files` (mẫu số/negative).

### Hoàn thiện tầng rẻ 5 tool (theo plan đã duyệt) — ĐÃ XONG
- Semgrep `p/default`+`p/secrets` (p/security-audit bỏ sót CWE-89).
- Wrapper mới: `trufflehog` (git-mode `--since-commit`, JSONL, CWE-798), `bearer` (quét từng file đổi, lấy cwe_ids; Bearer trả filename='.' nên gán path đã truyền), `horusec` (`-D` chỉ HorusecEngine → độc lập semgrep/gitleaks; map CWE thận trọng theo language=Leaks→798 + từ khoá; bóc path tạm `.horusec/<uuid>/`; copy file đổi vào temp để diff-scope).
- `canon_path` (base.py) khớp path tool ↔ key diff. `image_digest()`+`version()` → bảng `run_meta` (tái lập).
- **Smoke-test Java PASS:** SQLi→vuln 3-tool (bearer/horusec/semgrep), secret→vuln 3-tool (horusec/semgrep/trufflehog), Hello.java→clean, docs lọc thô. `finding_in_diff=1`.
- Commit `bc7148e`.

### Tối ưu Bearer (perf) — ĐÃ XONG
- Pilot lần 1 chậm: Bearer chạy mỗi-file-một-container (commit 14 file = 14 container, ~10 phút/commit).
- Sửa: Bearer copy file đổi vào 1 temp dir + chmod 0755 (container non-root) → quét cả thư mục 1 lần/commit. ~35s/commit. Commit perf fix.

### KẾT QUẢ PILOT train-ticket --max 50 (DB `data/dataset.sqlite`)
- 50 yêu cầu → **29 commit thực quét** (còn lại merge thật/docs bị lọc; lưu ý: squash-merge "(#xxx)" có 1 parent nên KHÔNG bị lọc, vẫn quét).
- **2951 findings(cụm) | clean files 1452.**
- **Nhãn: candidate 2948 / vuln 3** (n_tools_agree: 1→2948, 2→3). Consensus ~0.1%.
- finding_in_diff: 0→2591 (88% là nợ cũ, không trên dòng commit sửa), 1→360 (12%).
- Đóng góp tool: semgrep 2590 (88%), bearer 179, trufflehog 145, horusec 40, **gitleaks 0**.
- Top CWE: CWE-732 (1692) + CWE-250 (865) = **86% là CWE hạ tầng** (Dockerfile/k8s perm) từ semgrep p/default. CWE-798 161, CWE-89 chỉ 9, CWE-79 12.
- Secret CWE-798: trufflehog 145 (đứng MỘT MÌNH hết), horusec 14 (một mình), bearer+horusec 1. → các tool secret KHÔNG chồng nhau.
- 3 vuln đều in_diff=0, giá trị thấp (1 JS asset, 2 CWE-330 trong old-docs).

### CHẨN ĐOÁN (vì sao consensus ~0)
1. Coverage gần như rời nhau: semgrep ngập CWE hạ-tầng (732/250) không tool nào khác sinh; trufflehog ngập secret chưa-verify không ai chứng thực.
2. gitleaks=0 KHÔNG phải bug — quét OK ("no leaks found"), chỉ chặt hơn trufflehog (loại noise/test-cred). Tức consensus filter ĐANG làm đúng việc (không tin mù 145 hit của trufflehog).
3. → **Khẳng định triết lý PHỄU: tầng rẻ là BỘ SINH CANDIDATE (recall cao, precision thấp), KHÔNG phải bộ gán nhãn cuối.** `vuln` thật phải đến từ tầng đắt (CodeQL/FindSecBugs dataflow) chứng thực semgrep/bearer.

### Kế tiếp (đề xuất — chờ user chốt ưu tiên)
1. **Giảm noise để candidate set dùng được:** trufflehog gắn cờ `verified` (lọc unverified); semgrep gắn `category` (infra/code/secret) để SQLi/XSS không bị 732/250 nhấn chìm.
2. **Chuẩn hoá CWE theo cây MITRE** trước khi cluster (gộp CWE anh-em) — tăng đồng thuận ít ỏi đang có.
3. **Song song hoá intra-commit** (ThreadPoolExecutor 5 tool) — user đề xuất; tối ưu throughput, đặc biệt cho tầng đắt.
4. **Bước 2 — tầng đắt** (CodeQL/FindSecBugs/Sonar, build Maven): nguồn consensus thật cho code-vuln.
5. Backlog red-team: commit_role, selection_reason, finding_uid+dedup, gold_verified, redact secret, lọc finding_in_diff=1 cho dataset "commit introduced".
2. Tinh chỉnh: per-commit checkout có thể chậm; cân nhắc quét trên diff thay vì cả cây.
3. Bước 2: thêm tool tầng đắt (CodeQL/FindSecBugs/Sonar) + adapter SARIF.
