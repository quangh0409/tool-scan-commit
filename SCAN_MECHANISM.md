# Cơ chế SCAN của tầng rẻ — và vì sao đảm bảo ĐÚNG ĐẮN

> Mô tả chính xác cách 5 tool tầng rẻ quét 1 commit, các bất biến (invariant) đúng
> đắn được dựa vào, **bằng chứng kiểm thử**, và các giới hạn còn lại (trung thực).
> Đọc kèm `cli.py` (`_scan_one_commit`), `repo_pool.py`, và từng wrapper trong `tools/`.

---

## 0. Mục tiêu đúng đắn (định nghĩa)

Một dòng dataset chỉ có giá trị ground-truth nếu finding được gán **đúng**:

| Bất biến | Phát biểu |
|---|---|
| **I1 — Phạm vi (scope)** | Mỗi commit chỉ quét trên **các file/diff của ĐÚNG commit đó**, không lẫn commit khác, không quét lại toàn cây. |
| **I2 — Gán commit (attribution)** | Finding gán cho `commit_id` phải thực sự nằm ở phiên bản nội dung của commit đó. |
| **I3 — Khớp path** | `file_path` tool báo phải KHỚP key của `get_file_diffs()` (để enrich diff/permalink/consensus đúng). |
| **I4 — Đánh số dòng nhất quán** | `s_line`/`s_detail_line` đánh theo **file MỚI** (sau commit), trùng hệ quy chiếu với dòng `added` của diff → `finding_in_diff` so sánh được. |
| **I5 — Cô lập song song** | Quét K commit song song cho kết quả **y hệt** quét tuần tự (không phụ thuộc số worker/thứ tự). |
| **I6 — Bắt buộc nhãn** | Mọi finding có `cwe` (≠ rỗng) và `s_line > 0` (ép ở `validate()`). |

Tài liệu này chỉ ra từng tool thoả I1–I6 ở đâu, và **chỗ nào KHÔNG thoả** (đã đánh dấu ⚠️).

---

## 1. Hai chế độ quét

Tầng rẻ trộn 2 cơ chế khác bản chất — phải hiểu để biết finding nghĩa là gì:

| Nhóm | Tool | Đầu vào thực | "Quét" cái gì |
|---|---|---|---|
| **A. Git-mode** | gitleaks, trufflehog | Lịch sử git (`.git`) | **DIFF của commit** (nội dung commit THÊM/SỬA) |
| **B. Filesystem-mode** | semgrep, bearer, horusec | File trên đĩa tại commit | **Toàn bộ nội dung các file-đã-đổi** (kể cả dòng không sửa) |

Hệ quả quan trọng:
- Nhóm A gắn finding vào **dòng trong diff** → gần như luôn "lỗi do commit này đưa vào".
- Nhóm B quét **cả file** → finding có thể là **nợ cũ** (dòng không thuộc diff). Ta KHÔNG vứt
  nó đi mà gắn cờ `finding_in_diff` = (giao `s_detail_line` với các dòng `added`). Nhờ I4,
  phép giao này hợp lệ.

---

## 2. Từng tool — lệnh thật, phạm vi, vì sao đúng

### 2.1 gitleaks (git-mode, secret → CWE-798)
```
gitleaks detect --source /repo \
        --log-opts "-1 --no-merges <SHA>" \
        --report-format json --report-path /dev/stdout --exit-code 0
```
- **Phạm vi (I1):** `--log-opts "-1 <SHA>"` truyền thẳng cho `git log`. `git log -1 <SHA>` trả về
  **đúng 1 commit** nêu tên tường minh — KHÔNG phụ thuộc HEAD hay ref nào. ⇒ gitleaks chỉ quét
  patch của đúng SHA. **Đúng theo cấu tạo (by construction).**
- **`--no-merges`:** thừa-an-toàn (ta đã lọc merge ở `coarse_filter`); nếu lỡ là merge thì trả 0.
- **Path (I3):** trường `File` là path tương đối gốc repo → `canon_path` khớp key diff.
- **Dòng (I4):** `StartLine/EndLine` theo file mới.
- **Giới hạn:** gitleaks allowlist khoá ví dụ + regex thuần → **FN cao** (pilot: gitleaks=0).
  Đây là tính chất recall, KHÔNG vi phạm I1–I4.

### 2.2 trufflehog (git-mode, secret → CWE-798) — ⚠️ ĐÃ TỪNG SAI, ĐÃ SỬA
```
trufflehog git file:///repo \
        --branch <SHA> --since-commit <SHA>~1 \
        --json --no-update
```
- **Bug gốc (vi phạm I1+I2):** trufflehog git-mode quét theo **MỌI REF (nhánh)**, KHÔNG theo HEAD.
  Chỉ dùng `--since-commit <SHA>~1` thì nó quét cả dải `<SHA>..<tip-master>` rồi code gán **tất cả**
  về `commit_id` đang xét → secret của commit **hậu duệ** bị gán nhầm cho commit tổ tiên, lặp lại
  ở MỌI commit tổ tiên trong cửa sổ `--max`.
- **Bằng chứng (kiểm thực nghiệm trên train-ticket):**
  - Detach tại `OLD=5f79ac16` rồi `--since-commit OLD~1` → trufflehog báo secret ở `fa8d9efb`
    (commit **newer**, KHÔNG reachable từ OLD) ⇒ chứng minh quét vượt HEAD theo ref.
  - `--branch OLD --since-commit OLD~1` → `{}` (loại đúng fa8d9efb).
  - `--branch fa8d9efb --since-commit fa8d9efb~1` → bắt đúng 5 secret CỦA fa8d9efb.
- **Vì sao bản sửa đúng (I1+I2):** `--branch <SHA>` giới hạn tập quét = lịch sử **reachable từ chính SHA**
  (loại mọi hậu duệ); `--since-commit <SHA>~1` chặn dưới ở cha ⇒ tập còn lại = **đúng diff của SHA**.
  Kiểm qua wrapper: scan tại fa8d9efb → 5 finding đều ∈ changed_files; scan tại OLD → 0 (hết gán nhầm).
- **Path/Dòng (I3/I4):** lấy từ `SourceMetadata.Data.Git.{file,line}` (đánh theo commit) → khớp.
- **Giới hạn còn lại:** (a) commit gốc-repo không có `<SHA>~1` → trufflehog báo lỗi, trả 0 (hiếm, ngoài
  cửa sổ pilot). (b) Quét cả `node_modules`/vendored → nhiễu FP (xem §5).

### 2.3 semgrep (filesystem-mode, code+secret, CWE từ rule)
```
semgrep scan --config p/default --config p/secrets \
        --json --quiet  /src/<file1> /src/<file2> ...
```
- Mount clone làm `/src` nhưng **target chỉ là các file đã đổi** (`changed`). semgrep chỉ phân tích
  file được liệt kê (rule cộng đồng chủ yếu intra-file) ⇒ **diff-scoped ở mức file (I1)**, không quét toàn repo.
- **CWE (I6):** lấy từ `extra.metadata.cwe`; **không có CWE thì BỎ** finding.
- **Path (I3):** target `/src/<file>` → báo `path=/src/<file>` → `canon_path` bóc `/src/` → khớp key diff.
- **Dòng (I4):** `start.line`/`end.line` theo file hiện trạng (= file tại commit) → khớp.

### 2.4 bearer (filesystem-mode, code, CWE từ cwe_ids)
```
# copy CHỈ các file đổi sang temp (giữ cấu trúc), chmod 0755/0644 (bearer chạy non-root)
bearer scan /src --format json --quiet --exit-code 0
```
- **Vì sao copy ra temp:** quét cả thư mục trong **1 container** (tránh khởi động container mỗi-file);
  vì temp chỉ chứa file đổi ⇒ vẫn **diff-scoped (I1)**.
- **Path (I3):** giữ path tương đối khi copy ⇒ `filename` bearer báo = path gốc → khớp.
- **CWE (I6):** `cwe_ids`; rỗng thì BỎ.

### 2.5 horusec (filesystem-mode, meta, CWE map best-effort)
```
horusec start -p /src -D -o json -O /out/h.json      # -D: CHỈ HorusecEngine
```
- **`-D` (disable-docker):** không bật lại semgrep/gitleaks bên trong ⇒ **tránh correlated-error**
  (nếu không, horusec "đồng thuận" với semgrep/gitleaks một cách giả tạo, phá ý nghĩa consensus).
- Copy file đổi sang temp (như bearer) ⇒ diff-scoped (I1). Path có prefix `.horusec/<uuid>/` → **bóc bằng regex**
  để khớp (I3).
- **CWE (I6):** HorusecEngine không gán CWE → map theo `language=="Leaks"`→CWE-798 hoặc từ khoá thận trọng;
  **không suy ra được CWE thì BỎ** (giữ I6, đổi lấy recall thấp hơn — chấp nhận).

---

## 3. Vì sao SONG SONG vẫn đúng (I5)

`cli.py` chạy `ThreadPoolExecutor(SCAN_WORKERS)`; mỗi worker xử trọn 1 commit trên 1 **clone riêng**
(`repo_pool.RepoPool`):

- **Clone độc lập:** `git clone --local --no-checkout` tạo K repo riêng, **object hardlink** từ repo gốc
  (gần như 0 đĩa/0.3s). Mỗi clone có `.git` **thư mục THẬT** ⇒ tool git-mode chạy y nguyên trong container.
  (Không dùng `git worktree` vì worktree để `.git` là *file* `gitdir:` → mount thư mục lẻ vào container thì
  git-mode gãy.)
- **Không chia sẻ trạng thái ghi:** mỗi worker `checkout --detach <SHA>` trong clone của mình; chỉ ghi vào
  index/working-tree riêng. Object store hardlink chỉ **đọc** (ta không bao giờ `gc`/`repack` lúc quét).
  ⇒ commit A ở clone w0 không ảnh hưởng commit B ở clone w1.
- **Ghi DB:** SQLite mở `check_same_thread=False` + `threading.Lock` bọc mọi ghi ⇒ tuần tự hoá an toàn.
- **Tất định (determinism):** kết quả mỗi commit chỉ phụ thuộc nội dung commit đó (qua clone), KHÔNG phụ thuộc
  worker nào chạy hay thứ tự. Các dòng DB là append độc lập, không phụ thuộc thứ tự chèn ⇒ **nội dung dataset
  bất biến theo `SCAN_WORKERS`**. Thoả I5.
- **Chặn trên tài nguyên:** mỗi worker chạy 5 tool **tuần tự** ⇒ tối đa `SCAN_WORKERS` container cùng lúc
  (≈ vCPU, không thrash). Đây là lý do KHÔNG cần "200 virtual thread": nghẽn ở CPU/container chứ không ở số luồng.

---

## 4. Ngưỡng BỎ QUA commit (đánh đổi phủ-sóng ↔ chi phí)

**Công tắc `FLAG_LIMIT` (0/1) — mặc định 0 = TẮT toàn bộ ngưỡng (quét mọi commit hợp lệ).** Đặt
`FLAG_LIMIT=1` (env `ORCH_FLAG_LIMIT` hoặc CLI `--flag-limit 1`) để áp các ngưỡng dưới đây; các tham số
ngưỡng vẫn giữ nguyên dù bật/tắt. Lọc merge/docs/no-code KHÔNG phụ thuộc cờ này (luôn áp dụng).

Khi BẬT, xét theo **MỨC THAY ĐỔI của commit lên từng file** (add/del trong diff), KHÔNG phải kích thước file —
vì một sửa 2 dòng trong file 2000 dòng vẫn rẻ & đáng quét, còn một diff +1500 dòng vào 1 file mới là
bulk/generated, tốn & loãng. Tất cả tính từ `git show --numstat` (đã có sẵn trong `get_commit_info`,
HEAD-independent) nên check nằm ở **`coarse_filter` (lúc enumerate)** — không cần checkout/đọc nội dung:

- `> MAX_FILES_PER_COMMIT` (mặc định **100**) file → bỏ.
- BẤT KỲ file nào trong commit có **add > MAX_FILE_ADD_LINES** (1000), **HOẶC del > MAX_FILE_DEL_LINES**
  (1000), **HOẶC (add+del) > MAX_FILE_CHURN_LINES** (2000) → bỏ.
- Env: `ORCH_MAX_FILES_PER_COMMIT`, `ORCH_MAX_FILE_ADD_LINES`, `ORCH_MAX_FILE_DEL_LINES`,
  `ORCH_MAX_FILE_CHURN_LINES`, `ORCH_SCAN_WORKERS`.
- **Kiểm thực nghiệm:** trên train-ticket, commit sửa 2 dòng của file k8s yml 2248 dòng → **KEEP**
  (đúng, không bỏ oan); commit `570a522e (+1962/-0)`, `c01a86cc (-1343)` → **bỏ** đúng theo luật.
- **Trung thực:** vuln nằm trong commit-khổng-lồ/diff-khổng-lồ sẽ **không** vào dataset — đánh đổi chấp nhận
  trong kiến trúc phễu.

---

## 5. Giới hạn ĐÚNG ĐẮN còn lại (phải nhớ)

1. **Filesystem-mode quét cả file, không chỉ diff** → finding có thể là nợ cũ. Đã giảm thiểu bằng
   `finding_in_diff`; muốn dataset "chỉ lỗi commit này tạo" thì lọc `finding_in_diff=1`.
2. **Diff-scoping làm mất ngữ cảnh liên-file:** bearer/horusec copy *chỉ* file đổi ra temp; SAST cần luồng
   dữ liệu xuyên file (taint qua file khác, sanitizer ở file khác) có thể **FN/FP**. Đổi lấy chi phí rẻ.
   (semgrep ít ảnh hưởng vì rule chủ yếu intra-file.)
3. **node_modules / vendored / generated** vẫn bị quét (vd trufflehog báo secret trong `@types/node/*.d.ts`)
   → nhiễu FP. *Backlog:* loại trừ thư mục vendored trước khi quét.
4. **gitleaks allowlist** → FN secret ví dụ; **horusec map CWE từ khoá** → có thể sai/thiếu CWE.
5. **consensus = nhãn BẠC:** ≥2 tool đồng thuận chỉ là silver-label, cần Fleiss' kappa + GOLD tay xác thực.
6. **CWE của tool không đồng nhất** → ta gộp theo NHÓM CWE (`cwe_groups.py`) trước khi vote; sai map CWE
   ở một tool có thể phá/ghép cụm sai.

---

## 6. Tóm tắt 1 dòng

**Secret (gitleaks/trufflehog) quét DIFF qua git theo đúng 1 SHA; code (semgrep/bearer/horusec) quét NỘI DUNG
các file-đã-đổi tại commit.** Cả hai giới hạn ở phạm vi commit chạm tới; song song an toàn nhờ clone độc lập;
điểm tinh tế nhất — trufflehog quét-theo-ref — đã được chốt bằng `--branch <SHA>` và kiểm thực nghiệm.
