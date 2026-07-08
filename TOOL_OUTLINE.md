# TOOL OUTLINE — Bộ công cụ xây dựng Dataset lỗ hổng bảo mật từ lịch sử Git

> **Đối tượng đọc:** người chưa biết gì về dự án — kể cả không chuyên bảo mật.
> **Quy ước học thuật:** mọi khẳng định có tính học thuật đều kèm tham chiếu ở [§11](#11-tài-liệu-tham-chiếu);
> chỗ nào là *lựa chọn thiết kế của dự án* (không phải chân lý đã chứng minh) sẽ ghi rõ **[quy ước dự án]**;
> chỗ nào chưa có nguồn kiểm chứng sẽ ghi **[chưa kiểm chứng]**.

---

## 1. Tool này làm gì? (giải thích cho người không chuyên)

Hãy tưởng tượng một dự án phần mềm giống một cuốn nhật ký: mỗi lần lập trình viên sửa code và lưu lại,
Git tạo ra một **commit** (một "trang nhật ký" ghi chính xác dòng nào được thêm/xoá). Một dự án lớn có
hàng nghìn commit như vậy.

Tool của chúng tôi là một **orchestrator** (nhạc trưởng): nhận vào **1 đường link GitHub**, tự động:

1. Đọc lại **từng trang nhật ký** (từng commit) của dự án;
2. Cho **nhiều phần mềm dò lỗi bảo mật khác nhau** (gọi là tool SAST — xem hộp bên dưới) cùng "khám" mỗi commit;
3. **Đối chiếu kết quả giữa các tool**: chỗ nào nhiều tool cùng chỉ vào thì đáng tin hơn chỗ chỉ 1 tool nói;
4. Xuất ra một **bộ dữ liệu (dataset)** trong đó mỗi dòng là một "chỗ nghi có lỗi bảo mật", kèm nhãn
   độ tin cậy (**gold / silver / candidate**) và đầy đủ bằng chứng để ai cũng kiểm tra lại được.

> **SAST là gì?** Static Application Security Testing — phần mềm đọc code (không cần chạy chương trình)
> để tìm các mẫu lỗi bảo mật đã biết, ví dụ: để lộ mật khẩu trong code, ghép chuỗi SQL dễ bị tấn công
> (SQL Injection)… Mỗi loại lỗi có một mã chuẩn quốc tế gọi là **CWE** (Common Weakness Enumeration,
> do MITRE quản lý [T1]). Ví dụ CWE-89 = SQL Injection, CWE-798 = hardcoded credentials.

**Vì sao cần dataset này?** Ba mục đích: (a) **huấn luyện model AI** phát hiện lỗ hổng (cần cả mẫu
dương — có lỗi — lẫn mẫu âm — sạch); (b) **benchmark** so sánh các tool SAST với nhau; (c) **nghiên cứu**
(cần tính tái lập + chỉ số đo độ tin của nhãn).

**Triết lý trung thực của dự án:** nhãn do máy đồng thuận là **nhãn bạc/vàng có kèm bằng chứng**,
KHÔNG phải chân lý tuyệt đối — vì các tool có thể sai giống nhau (correlated errors) **[quy ước dự án,
xem giới hạn §10]**. Do đó dataset luôn công bố kèm: tool nào xác nhận, chỉ số đồng thuận Fleiss' kappa
[T2], và một GOLD set kiểm tay để đo độ chính xác thật.

---

## 2. Input tổng quan → Output tổng quan

### 2.1. INPUT (chỉ cần 1 thứ)

| Input | Ví dụ | Bắt buộc? |
|---|---|---|
| Link GitHub repo | `https://github.com/apache/giraph` | ✅ |
| Branch | `--branch trunk` (mặc định theo repo) | tuỳ chọn |
| Số commit tối đa | `--max 0` (0 = toàn bộ lịch sử) | tuỳ chọn |
| Công tắc CodeQL | `--codeql 0/1` (tool sâu nhất nhưng chậm nhất) | tuỳ chọn |
| Quét cả commit sạch | `--include-clean` (để tạo mẫu âm chất lượng cao) | tuỳ chọn |

Lệnh đầy đủ ví dụ:
```bash
ORCH_SQLITE=data/dataset_giraph.sqlite \
python3 -m orchestrator.cli pipeline https://github.com/apache/giraph \
    --max 0 --branch trunk --codeql 0 --include-clean --out data/export_giraph
```

### 2.2. OUTPUT (3 tầng sản phẩm)

```
data/
├── dataset_<repo>.sqlite          ← ① DATABASE: toàn bộ dữ liệu gốc + trung gian
└── export_<repo>/                 ← ② EXPORT: dạng dễ dùng cho ML/nghiên cứu
    ├── dataset.jsonl              ←    1 dòng = 1 CỤM finding đồng thuận (mức finding)
    ├── commits.jsonl              ←    1 dòng = 1 COMMIT (mức commit, đủ mọi commit)
    └── <commit_sha>/              ← ③ AUDIT: mỗi commit 1 thư mục bằng chứng
        ├── <tool>.raw.<ext>       ←    output thô nguyên bản từng tool (SARIF/XML/JSON)
        ├── <tool>.findings.json   ←    finding đã chuẩn hoá của từng tool
        ├── label.json             ←    các cụm + nhãn cuối của commit này
        └── summary.json           ←    tóm tắt: nhãn, vai trò, đặc trưng Kamei
```

- **`dataset.jsonl`** — trả lời câu hỏi *"chỗ nào trong code nghi có lỗi, tin được tới đâu?"*
  (dùng để train model phát hiện lỗ hổng mức dòng/hàm).
- **`commits.jsonl`** — trả lời câu hỏi *"commit nào có khả năng đưa lỗi vào?"* (dùng cho bài toán
  Just-In-Time defect prediction mức commit [T3], có đủ 14 đặc trưng Kamei — xem §7).
- **Thư mục audit** — đảm bảo **tái lập 100%**: ai nghi ngờ nhãn nào có thể mở raw output của đúng
  tool, đúng commit ra đối chiếu.

---

## 3. Kiến trúc PHỄU — vì sao không quét mọi commit bằng mọi tool?

Các tool dò lỗi chia 2 hạng:

- **Tầng RẺ** (giây/commit, không cần biên dịch): gitleaks, trufflehog (chuyên tìm secret/khoá lộ),
  semgrep, bearer, horusec (tìm lỗi code theo mẫu). Chạy trực tiếp trên phần code thay đổi (diff).
- **Tầng ĐẮT** (chục giây → phút/commit, **phải build được project**): FindSecBugs (phân tích bytecode),
  SonarQube (phân tích ngữ nghĩa), CodeQL (phân tích dataflow — sâu nhất, chậm nhất ~6,7 phút/commit
  với suite tối giản, nên có công tắc riêng).

Quét mọi commit bằng tool đắt là bất khả thi về chi phí (hàng nghìn giờ CPU cho một repo lớn). Giải
pháp là **mô hình phễu**: *tool rẻ sàng lọc toàn bộ lịch sử → chỉ thả tool đắt vào những commit đáng
ngờ (+ mẫu commit sạch để đối chứng)* **[quy ước dự án — đánh đổi được ghi rõ ở §10]**.

```
   ~hàng nghìn commit
        │
  ①  SCAN (tầng rẻ)      quét TOÀN BỘ commit bằng 5 tool rẻ, trên diff
        │
  ②  SELECT              chọn: commit "buggy" (tool rẻ có bắt CWE) + commit "clean"
        │                 → hàng đợi tầng đắt (vài trăm ~ 1 nghìn)
  ③  ANALYZE (tầng đắt)  build Maven + FindSecBugs + SonarQube (+CodeQL nếu bật)
        │
  ④  RELABEL             gộp finding rẻ + đắt thành CỤM, bỏ phiếu → gold/silver/candidate
        │
  ⑤  KAPPA               tính Fleiss' kappa — "sức khoẻ đồng thuận" của dataset
        │
  ⑥  EXPORT              xuất dataset.jsonl + commits.jsonl + thư mục audit
```

---

## 4. Input → Output TỪNG BƯỚC (chi tiết)

> **Khung trình bày (áp dụng thống nhất cho cả 6 bước):** mỗi bước ghi rõ **Ý tưởng** (vì sao cần
> bước này) → **Input** → **Xử lý** → **Output** — theo đúng quy chuẩn mô tả quy trình trích xuất.

### Bước ① SCAN — tầng rẻ, quét toàn bộ lịch sử

| | |
|---|---|
| **Ý tưởng** | Dùng tool nhanh-rẻ (không cần build) phủ 100% lịch sử để không bỏ sót ứng viên; độ chính xác thấp chấp nhận được vì sẽ có tầng sau kiểm chứng. |
| **Input** | URL repo + branch; toàn bộ danh sách commit |
| **Xử lý** | (1) Clone repo; lọc thô: bỏ merge-commit, bỏ commit toàn file nhị phân; bỏ commit "khổng lồ" nếu bật ngưỡng. (2) Với từng commit (song song 4 worker, mỗi worker 1 bản clone riêng): checkout, chạy 5 tool rẻ **trên diff** (chỉ phần code thay đổi), chuẩn hoá mọi output về finding thống nhất `(file, dòng, CWE, tool)`. (3) Tính sẵn 14 đặc trưng Kamei cho mọi commit (§7). |
| **Output** | Bảng `raw_findings` (mỗi finding thô 1 dòng), `findings` (cụm sơ bộ tầng rẻ), `scanned_files` (danh sách file đã quét sạch — mẫu số cho negative), `commit_features` (Kamei), `raw_output` (output nguyên bản để audit) |
| **Chi phí đo thật** | ~500–700 commit/giờ trên VM 8 vCPU |

Ghi chú đúng đắn quan trọng: mỗi tool được "đóng khung" để chỉ báo lỗi của ĐÚNG commit đang xét
(ví dụ trufflehog phải giới hạn `--branch <SHA> --since-commit <SHA>~1`, nếu không sẽ gán nhầm lỗi
của commit khác — bug thật đã phát hiện và vá trong dự án, xem `SCAN_MECHANISM.md`).

### Bước ② SELECT — chọn commit vào tầng đắt

| | |
|---|---|
| **Ý tưởng** | Ngân sách tính toán hữu hạn → chỉ commit "đáng tiền" (nghi có lỗi, hoặc sạch cần xác minh làm mẫu âm) mới được vào tầng đắt. Đây là van điều tiết chi phí của toàn hệ thống. |
| **Input** | Kết quả bước ① |
| **Xử lý** | Commit có ≥1 finding mang mã CWE từ tầng rẻ → nhóm **buggy** (cần tầng đắt xác thực). Commit 0 finding → nhóm **clean**; với `--include-clean`, clean cũng vào tầng đắt để *xác minh sạch thật* (tạo mẫu âm chất lượng cao). |
| **Output** | Bảng `selected_commits` (hàng đợi, có trạng thái pending/building/done/build_failed — claim nguyên tử, crash giữa chừng có thể resume không mất dữ liệu) |
| **Núm chi phí** | Đây là van điều tiết ngân sách: chọn nhiều/ít commit quyết định tổng giờ CPU tầng đắt |

### Bước ③ ANALYZE — tầng đắt, xác thực sâu

| | |
|---|---|
| **Ý tưởng** | Tool phân tích sâu (bytecode/ngữ nghĩa/dataflow) có precision cao hơn pattern-match, nhưng đòi build được project → chỉ chạy trên tập đã chọn lọc; kết quả dùng làm "nguồn xác nhận thứ hai" nâng cấp nhãn. |
| **Input** | Hàng đợi `selected_commits` |
| **Xử lý** | Với từng commit: (1) tự phát hiện phiên bản JDK từ `pom.xml` của đúng commit đó → chọn image Maven phù hợp (repo lâu năm đổi JDK nhiều lần); (2) build **chỉ những module bị commit đụng tới** (`mvn -pl <modules> -am`) — tiết kiệm lớn; (3) chạy FindSecBugs trên bytecode + SonarQube scan (+ CodeQL nếu bật); (4) mọi finding đắt ghi thêm vào `raw_findings`. Build hỏng → đánh dấu `build_failed`, đi tiếp (không chết run). |
| **Output** | `raw_findings` bổ sung finding tầng đắt; `expensive_runs` (nhật ký từng lần chạy tool); trạng thái done/build_failed |
| **Chi phí đo thật** | FindSecBugs ~7s + Sonar ~22s + build ~14s–vài phút/commit; CodeQL ~6,7 phút/commit (nên mặc định tắt khi chạy full-history) |

### Bước ④ RELABEL — gộp cụm & gán nhãn (trái tim của dataset — chi tiết ở §5)

| | |
|---|---|
| **Ý tưởng** | Một chỗ lỗi được nhiều tool ĐỘC LẬP cùng chỉ ra thì đáng tin hơn một tool đơn lẻ → gom finding về "cụm vị trí" rồi bỏ phiếu theo tầng; nhãn tách khỏi bước quét (lưu raw) để đổi công thức không phải quét lại. |
| **Input** | TOÀN BỘ `raw_findings` (rẻ + đắt) của từng commit |
| **Xử lý** | Lọc nhiễu đã biết (mặc định loại CWE-117 của FindSecBugs khỏi vote — rule log-injection cho FP hàng loạt; raw vẫn giữ) → gộp finding thành CỤM theo `(file, nhóm-CWE, dòng ±3)` → đếm phiếu theo tầng → gán nhãn gold/silver/candidate; xác định `finding_in_diff`; gán mức negative cho commit sạch. |
| **Output** | Bảng `findings` hoàn chỉnh (mỗi cụm 1 dòng + nhãn); nhãn commit-level |
| **Tính chất then chốt** | Vì lưu RAW từng tool, bước này chạy lại chỉ mất ~30 giây cho cả repo — đổi công thức vote/ngưỡng KHÔNG cần quét lại. Tool đắt chạy xong tới đâu, nhãn tự nâng cấp tới đó (candidate → gold). |

### Bước ⑤ KAPPA — đo sức khoẻ đồng thuận

| | |
|---|---|
| **Ý tưởng** | Nhãn đồng thuận chỉ đáng tin khi biết các "giám khảo" đồng thuận tới đâu trên toàn cục → đo một chỉ số thống kê chuẩn (kappa) công bố kèm dataset thay vì chỉ khẳng định suông. |
| **Input** | `raw_findings` + danh sách tool đã chạy per-commit |
| **Xử lý** | Lập ma trận *item × giám khảo*: item = 1 cụm ứng viên; giám khảo = mỗi tool **đủ năng lực với loại lỗi đó và đã thực chạy**; phiếu = có báo/không báo. Tính **Fleiss' kappa** [T2] toàn cục + theo nhóm CWE. |
| **Output** | Báo cáo κ kèm dataset |
| **Diễn giải** | κ đo mức đồng thuận *vượt trên ngẫu nhiên*. Kết quả thực nghiệm của dự án: κ **âm** (−0,26 → −0,47 trên 5 repo) = các tool SAST **phủ bổ sung nhau** chứ không trùng nhau — vì thế cụm được ≥2 tool cùng chỉ (gold) mới quý hiếm và giá trị. Đây là *đặc điểm hệ thống*, không phải lỗi. **[Kết quả thực nghiệm nội bộ của dự án — nhất quán với văn liệu về độ vênh giữa các tool SAST, vd. các nghiên cứu benchmark cho thấy overlap giữa SAST tools thấp; xem [T6] — mức độ tổng quát hoá: chưa kiểm chứng ngoài 5 repo đã chạy]** |

### Bước ⑥ EXPORT — đóng gói

| | |
|---|---|
| **Ý tưởng** | Người dùng dataset không nên phải đọc DB nội bộ → xuất 2 file JSONL chuẩn (mức cụm + mức commit) kèm thư mục bằng chứng thô để bất kỳ ai cũng tái lập/kiểm toán được từng nhãn. |
| **Input** | Toàn bộ DB |
| **Xử lý** | Ghi `dataset.jsonl` (mức cụm) + `commits.jsonl` (mức commit) + mỗi commit 1 thư mục audit (raw + findings chuẩn hoá + label + summary). |
| **Output** | Thư mục `export_<repo>/` hoàn chỉnh (xem §2.2) |

---

## 5. QUY TẮC GÁN NHÃN (giải thích đầy đủ — nguồn: `RULE_GAN_NHAN.md`)

### 5.1. Đơn vị gán nhãn = CỤM, không phải commit

Mỗi tool báo nhiều finding ở nhiều vị trí. Ta không hỏi "commit này lỗi không?" mà hỏi **"tại vị trí
X có lỗi loại Y không?"**. Finding của các tool được gom thành **cụm** — mỗi cụm là *một chỗ nghi lỗi* —
và bỏ phiếu **riêng từng cụm**. Một commit vì thế có thể sinh nhiều dòng dataset.

### 5.2. Điều kiện gộp 2 finding vào cùng cụm (phải thoả CẢ 3)

| Điều kiện | Giải thích |
|---|---|
| **Cùng file** | sau khi chuẩn hoá đường dẫn (các tool ghi path khác nhau) |
| **Cùng NHÓM-CWE** | CWE "anh em" được quy về một nhóm (vd CWE-89/564/943 → `sql_injection`) — tránh 2 tool cùng chỉ SQL Injection nhưng khác mã bị tách cụm oan |
| **Dòng gần nhau** | chênh lệch ≤ 3 dòng (`LINE_WINDOW=3`) — tha thứ việc tool này trỏ dòng khai báo, tool kia trỏ dòng gán giá trị |

*Ví dụ thật:* CodeQL báo CSRF tại dòng 65, Sonar báo dòng 67, cùng file `SecurityConfig.java`
→ |65−67| = 2 ≤ 3, cùng nhóm `csrf` → **một cụm, 2 phiếu**.

### 5.3. "Mẫu số" công bằng — khái niệm tool ĐỦ NĂNG LỰC (eligible)

Không tool nào bắt được mọi loại lỗi: tool secret (gitleaks/trufflehog) không hiểu SQL Injection;
tool code không chuyên tìm khoá lộ. Vì vậy **không chia phiếu cho tổng 8 tool** mà chia cho **số tool
đủ năng lực với loại lỗi đó VÀ đã thực chạy trên commit đó**. Một cụm secret được 3/3 tool secret
đồng thuận là tín hiệu rất mạnh dù "chỉ có 3 phiếu".

### 5.4. Thang nhãn (label ladder) — kết hợp SỐ TOOL × TẦNG

Gọi **E** = số tool ĐẮT đồng thuận trong cụm, **C** = số tool RẺ đồng thuận:

| E (đắt) | C (rẻ) | Nhãn | Ý nghĩa |
|:---:|:---:|:---|:---|
| ≥ 2 | bất kỳ | 🥇 **gold** | ≥2 tool đắt độc lập cùng xác nhận — tin cậy cao nhất |
| 1 | ≥ 1 | 🥇 **gold** | 1 tool đắt + ít nhất 1 nguồn rẻ độc lập thứ hai |
| 1 | 0 | 🥈 **silver** | 1 tool đắt đơn lẻ — precision khá nhưng thiếu nguồn 2 |
| 0 | ≥ 2 | 🥈 **silver** | ≥2 tool rẻ đồng thuận — mạnh vừa, chưa có tầng đắt kiểm |
| 0 | 1 | 🟡 **candidate** | đúng 1 tool rẻ — tỷ lệ báo động giả cao, chỉ nên coi là "đáng soi" |

Logic nền: tool đắt (phân tích dataflow/bytecode/ngữ nghĩa) có precision cao hơn tool rẻ
(pattern-match trên text) **[quy ước dự án dựa trên đặc tính kỹ thuật của từng lớp tool; phù hợp
với phân loại SAST trong văn liệu [T6], nhưng trọng số cụ thể là lựa chọn thiết kế]** — nên sự ưu
tiên tầng đắt được "nướng" thẳng vào thang nhãn thay vì công thức trọng số phức tạp. Mọi ngưỡng đều
là **tham số cấu hình** (`GOLD_MIN_EXPENSIVE`, `GOLD_ALLOW_1EXP_1CHEAP`, `SILVER_MIN_CHEAP`) — vì
raw được lưu đầy đủ, đổi ngưỡng chỉ cần relabel ~30 giây, không quét lại.

### 5.5. Mẫu ÂM (negative) — 2 cấp chất lượng

| Mức | Điều kiện | Vai trò |
|---|---|---|
| **verified-clean** | tầng rẻ sạch **VÀ** đã qua tầng đắt (build + FindSecBugs + Sonar) vẫn sạch | **GOLD negative** — mẫu âm chất lượng cao, điểm khác biệt của dataset này so với các bộ JIT công khai **[so sánh định tính; chưa kiểm chứng bằng khảo sát hệ thống]** |
| **cheap-clean** | chỉ tầng rẻ xác nhận sạch (không build được hoặc không được chọn) | mẫu âm mức bạc |

### 5.6. Trục `finding_in_diff` — "commit TẠO lỗi" vs "nợ cũ"

Tool đắt quét **cả file**, nên có thể phơi ra lỗi đã tồn tại từ trước (nợ kỹ thuật cũ) chứ không phải
do commit đang xét gây ra. Mỗi cụm vì thế mang cờ:

- `finding_in_diff = 1`: vị trí lỗi nằm trên **dòng commit này thêm vào** → commit này TẠO lỗi;
- `finding_in_diff = 0`: lỗi có sẵn, commit chỉ "đi ngang qua".

Trục này **trực giao với nhãn** (một cụm gold vẫn có thể là nợ cũ). Ai cần dataset "commit đưa lỗi
vào" (bài toán JIT) chỉ việc lọc `finding_in_diff=1`. Mức negative của commit cũng xét theo trục này.

### 5.7. Lọc nhiễu trước khi bỏ phiếu

Rule nhiễu đã biết bị loại khỏi vote (mặc định: CWE-117 log-injection của FindSecBugs — thực nghiệm
cho thấy flag hàng loạt mọi lệnh `log(userInput)`, phần lớn là báo động giả trong ngữ cảnh này
**[quan sát thực nghiệm nội bộ trên các repo đã chạy; tỷ lệ FP chính xác chưa kiểm định tay]**).
Finding nhiễu **vẫn nằm trong raw** — chỉ không được tính phiếu; danh sách nhiễu là config (`NOISE_CWE`).

---

## 6. TỪ ĐIỂN các trường output chính (`dataset.jsonl` — mỗi dòng 1 cụm)

| Nhóm | Trường | Ý nghĩa |
|---|---|---|
| Định danh | `repo`, `commit_id`, `parent_commit`, `commit_message`, `author_date` | commit nào, của repo nào |
| Vị trí | `file_path`, `s_line`, `e_line`, `s_detail_line[]`, `function` | file + dòng bắt đầu/kết thúc + các dòng cụ thể gây lỗi |
| Phân loại lỗi | `cwe[]`, `cwe_group`, `category`, `owasp` | mã CWE thô, nhóm đồng thuận, miền (code/secret/crypto/infra/info), ánh xạ OWASP |
| **Nhãn** | `label` | **gold / silver / candidate** (§5.4) |
| Bằng chứng | `agreeing_tools[]`, `n_cheap`, `n_expensive`, `eligible[]`, `agreement_ratio`, `confidence`, `tier` | tool nào xác nhận, bao nhiêu phiếu mỗi tầng, mẫu số năng lực, cụm thuần rẻ/thuần đắt/hỗn hợp (`mixed`) |
| Ngữ cảnh | `finding_in_diff`, `diff_parsed{added,deleted}`, `code_before_url`, `code_after_url`, `lines_added`, `lines_deleted` | lỗi do commit tạo hay nợ cũ; diff đã parse; link GitHub xem code trước/sau |
| Đặc trưng | `kamei{…}` | 14 đặc trưng Kamei của commit chứa cụm (§7) |
| Enrichment | `cve` | gần như luôn **null** — SAST không sinh CVE (CVE thuộc địa hạt SCA); chỉ có giá trị nếu mine từ fix-commit kiểu CVEfixes [T4] |

`commits.jsonl` (mỗi dòng 1 commit, đủ cả commit 0-finding): `commit_id, repo, author, author_date,
kamei{14}, labels{đếm gold/silver/candidate}, role(buggy/clean), negative_level(verified-clean |
cheap-clean | null)`.

### 6.1. Quy trình dẫn xuất từng trường (input → xử lý → output)

Các trường không lấy thẳng từ tool mà được **dẫn xuất** — quy trình từng trường:

| Trường (output) | Input | Bước xử lý |
|---|---|---|
| `cwe_group` | `cwe[]` thô của các tool trong cụm | tra bảng nhóm CWE anh-em (`consensus/cwe_groups.py`; vd 89/564/943 → `sql_injection`) — chuẩn hoá trước khi gộp cụm & bỏ phiếu |
| `category` | `cwe_group` | ánh xạ nhóm → miền: code / secret / crypto / infra / info / other (dùng tách nhiễu hạ tầng và chọn mẫu số eligible) |
| `s_detail_line[]` | dòng cụ thể từng tool báo | hợp (union) các dòng của mọi tool trong cụm; mặc định = dải `s_line..e_line` nếu tool không chỉ đích danh |
| `diff_parsed` | `git show --unified=0 <sha> -- <file>` | parse hunk → `{added:[[dòng,text]], deleted:[[dòng,text]]}` (added đánh số theo file MỚI, deleted theo file CŨ) |
| `finding_in_diff` | `s_detail_line[]` + `diff_parsed.added` | giao hai tập dòng: có phần tử chung → 1 (commit TẠO lỗi), rỗng → 0 (nợ cũ) |
| `n_cheap`, `n_expensive`, `tier` | `agreeing_tools[]` + bảng phân tầng tool | đếm tool đồng thuận theo tầng; tier = cheap/expensive/mixed theo nguồn phiếu |
| `eligible[]` | `category` + danh sách tool ĐÃ chạy trên commit (bảng `raw_output`) | lọc tool đủ năng lực với miền lỗi đó VÀ có chạy thật → làm mẫu số |
| `agreement_ratio`, `confidence` | `n_agree` / `eligible` | chia trực tiếp (confidence mặc định = ratio; nâng cấp trọng số là việc tương lai, không cần quét lại nhờ raw) |
| `label` | (n_expensive, n_cheap) | tra thang nhãn §5.4 |
| `negative_level` (commit) | vai trò commit + kết quả tầng đắt + `finding_in_diff` | commit clean qua đắt vẫn sạch (xét theo in_diff=1) → verified-clean; chỉ qua rẻ → cheap-clean |
| `code_before_url` / `code_after_url` | repo + sha cha / sha + path | ghép permalink GitHub dạng `blob/<sha>/<path>` |

---

## 7. 14 đặc trưng Kamei (cho bài toán JIT defect prediction) — cách tính từng đặc trưng

Bộ đặc trưng chuẩn từ Kamei et al. 2013 [T3]. Nguồn code: `src/orchestrator/kamei.py`.

### 7.1. QUY TRÌNH TRÍCH XUẤT (ý tưởng → input → các bước xử lý → output)

**Ý tưởng tổng quát:** rủi ro của một commit có thể ước lượng từ *metadata lịch sử* mà không cần
hiểu ngữ nghĩa code — commit càng to/càng dàn trải, chạm vào file càng "nóng" (nhiều người sửa,
sửa gần đây), tác giả càng ít kinh nghiệm → xác suất mang lỗi càng cao [T3]. 14 đặc trưng lượng hoá
đúng các trục đó, và phải tính **chỉ từ quá khứ** của từng commit (không rò rỉ tương lai) thì mới
dùng được cho bài toán dự đoán.

**INPUT:** thư mục repo đã clone + tên nhánh (`rev`). Toàn bộ dữ liệu lấy từ **một lệnh Git duy
nhất**: `git log --reverse -M --numstat --pretty=<sentinel>` — stream các commit từ CŨ → MỚI, mỗi
commit gồm (sha, tác giả, timestamp, message, danh sách file với số dòng thêm/xoá, thông tin rename).

**CÁC BƯỚC XỬ LÝ (một lượt duyệt, trạng thái tăng dần):**

| Bước | Vào | Làm gì | Ra |
|---|---|---|---|
| **B1. Parse stream** | dòng text từ `git log` | tách theo sentinel thành từng bản ghi commit; parse numstat (`add`, `del`, `path`, rename `{old => new}`) | dãy bản ghi commit theo thứ tự thời gian |
| **B2. Lọc** | bản ghi commit | **merge-commit bị loại hoàn toàn** (không tính đặc trưng, không cập nhật trạng thái) [T5] | dãy commit non-merge |
| **B3. Tính đặc trưng** | commit thứ *n* + **TRẠNG THÁI tích luỹ từ commit 1..n−1** (LOC từng file, tập tác giả/commit từng file, thời điểm sửa cuối, bộ đếm kinh nghiệm tác giả…) | tính đủ 14 giá trị theo công thức §7.3–§7.7 — **trước khi** đụng vào trạng thái | 1 vector 14 đặc trưng cho commit *n* |
| **B4. Cập nhật trạng thái** | chính commit *n* | cộng LOC (thêm−xoá) vào từng file; ghi nhận tác giả/commit/timestamp cho file; chuyển toàn bộ lịch sử sang path mới nếu rename; tăng bộ đếm kinh nghiệm tác giả | trạng thái sẵn sàng cho commit *n+1* |

**OUTPUT:** bảng SQLite `commit_features` (1 hàng/commit: `commit_id, repo, author, author_date`
+ 14 cột đặc trưng, ghi kiểu INSERT OR REPLACE — chạy lại cho kết quả y hệt/idempotent). Từ bảng này
đặc trưng được **nhúng tự động** vào: trường `kamei` của mỗi dòng `dataset.jsonl` (mức cụm), block
`kamei` trong `summary.json` từng commit, và `commits.jsonl` (mức commit — kể cả commit 0-finding).

### 7.2. Bốn nguyên tắc đúng đắn áp dụng cho MỌI đặc trưng

1. **Chỉ nhìn quá khứ:** đặc trưng của commit thứ *n* được tính **trước khi** cập nhật trạng thái
   bằng chính commit đó — tức chỉ dựa trên commit 1..n−1, không rò rỉ tương lai.
2. **Merge-commit bị loại hoàn toàn** (không xuất đặc trưng, không cập nhật trạng thái) — theo chuẩn
   Commit Guru [T5].
3. **Rename được theo dấu** (cờ `-M`): khi file đổi tên, toàn bộ lịch sử (LOC, tác giả, lần sửa cuối)
   được chuyển sang đường dẫn mới — không bị "reset" thành file mới tinh.
4. **File nhị phân** (numstat báo `-`): vẫn đếm vào NF/ND/NS nhưng không có số dòng nên bị loại khỏi
   LA/LD/LT/Entropy.

Giá trị lưu là **RAW** (không log-transform/chuẩn hoá) — việc tiền xử lý dành cho người dùng dataset.
Định danh tác giả = **email** (fallback tên nếu email rỗng). "Subsystem" = thành phần đầu tiên của
đường dẫn (`src/main/App.java` → `src`; file ở gốc → `root`); "directory" = đường dẫn bỏ tên file.

### 7.3. Nhóm PHÂN TÁN (diffusion) — commit trải rộng tới đâu?

**Ý tưởng:** thay đổi càng dàn trải qua nhiều subsystem/thư mục/file thì càng khó review trọn vẹn →
rủi ro lọt lỗi cao hơn [T3]. **Input:** danh sách file + churn của commit hiện tại. **Output:** 4 số.

| Đặc trưng | Cách tính (bước xử lý) |
|---|---|
| **NS** | Số **subsystem** khác nhau mà commit đụng tới = đếm distinct thành phần đầu của path các file. |
| **ND** | Số **thư mục** khác nhau = đếm distinct directory (path bỏ tên file) của các file bị sửa. |
| **NF** | Số **file** bị sửa trong commit (đếm cả file nhị phân). |
| **Entropy** | Độ "dàn trải" của thay đổi giữa các file. Với mỗi file lấy churn = (dòng thêm + dòng xoá); đặt pᵢ = churnᵢ / tổng-churn; tính Shannon entropy H = −Σ pᵢ·log₂ pᵢ rồi **chuẩn hoá chia log₂(số file có churn)** → giá trị ∈ [0, 1]. Sửa đều nhau nhiều file → gần 1; dồn hết vào 1 file → 0. Commit chỉ có ≤1 file có churn → 0. |

### 7.4. Nhóm KÍCH THƯỚC (size) — commit to cỡ nào?

**Ý tưởng:** commit càng lớn càng nhiều chỗ để sai; sửa file vốn đã đồ sộ rủi ro hơn sửa file nhỏ
[T3]. **Input:** numstat của commit hiện tại + trạng thái LOC từng file (tích luỹ quá khứ, B4 §7.1).
**Output:** 3 số.

| Đặc trưng | Cách tính (bước xử lý) |
|---|---|
| **LA** | Tổng số **dòng thêm** trên mọi file (cột 1 của `--numstat`). |
| **LD** | Tổng số **dòng xoá** trên mọi file (cột 2 của `--numstat`). |
| **LT** | **LOC trung bình của các file bị sửa NGAY TRƯỚC commit**. LOC từng file không đọc từ disk mà được nuôi tăng dần: mỗi commit quá khứ cộng (thêm − xoá) vào bộ đếm của file. Lấy trung bình trên các file đã có lịch sử; file mới tinh chưa có lịch sử bị bỏ qua; nếu không file nào có lịch sử → 0. |

### 7.5. Nhóm MỤC ĐÍCH (purpose)

**Ý tưởng:** commit sửa lỗi (bug-fix) có xu hướng chạm vào vùng code vốn đã dễ lỗi → bản thân việc
"là fix" là một tín hiệu rủi ro [T3]. **Input:** commit message (cả subject + body). **Output:** 1 bit.

| Đặc trưng | Cách tính (bước xử lý) |
|---|---|
| **FIX** | = 1 nếu commit message khớp một trong các từ khoá `fix, bug, defect, patch, fault, repair` (cấu hình `ORCH_FIX_KEYWORDS`), **khớp đầu-từ, không phân biệt hoa thường**: "Fixes NPE" hay "bugfix" → 1, nhưng "prefix" → 0 (không có từ nào *bắt đầu* bằng keyword). Ngược lại = 0. |

### 7.6. Nhóm LỊCH SỬ FILE (history) — chỗ code này "nóng" tới đâu?

**Ý tưởng:** file có nhiều người sửa, sửa thường xuyên và sửa gần đây là "điểm nóng" hay sinh lỗi
[T3]. **Input:** tập file commit đụng tới + trạng thái lịch sử từng file (tập tác giả, tập commit,
thời điểm sửa cuối — tích luỹ ở B4 §7.1). **Output:** 3 số.

Cả 3 đặc trưng lấy **hợp (union) trên tập file mà commit đụng tới**, chỉ tính quá khứ; với file bị
rename trong chính commit này thì tra cứu lịch sử theo **đường dẫn cũ**.

| Đặc trưng | Cách tính (bước xử lý) |
|---|---|
| **NDEV** | Số **tác giả khác nhau** đã từng sửa các file này trước đây (union tập tác giả của từng file). |
| **AGE** | **Tuổi trung bình (ngày)** kể từ lần sửa gần nhất: với mỗi file lấy (thời điểm commit − thời điểm file được sửa lần cuối) / 86 400 giây, rồi trung bình. File chưa từng được sửa không tham gia; không file nào có lịch sử → 0. |
| **NUC** | Số **commit quá khứ khác nhau** đã từng sửa ít nhất một trong các file này (union tập commit của từng file — 1 commit cũ sửa 2 file trong nhóm chỉ đếm 1 lần). |

### 7.7. Nhóm KINH NGHIỆM TÁC GIẢ (experience)

**Ý tưởng:** tác giả càng ít kinh nghiệm (toàn repo, gần đây, hoặc trong đúng subsystem đang sửa)
thì commit càng rủi ro [T3]. **Input:** danh tính tác giả + bộ đếm kinh nghiệm tích luỹ (B4 §7.1).
**Output:** 3 số.

| Đặc trưng | Cách tính (bước xử lý) |
|---|---|
| **EXP** | Số **commit trước đó của chính tác giả** trên toàn repo (merge không tính). |
| **REXP** | Kinh nghiệm **có trọng số thời gian gần**: Σ trên các commit quá khứ của tác giả của 1 / (tuổi-commit-tính-theo-năm + 1), với tuổi = (thời điểm hiện tại − thời điểm commit cũ) / 365,25 ngày. Commit vừa mới đóng góp ≈ 1 điểm, commit cách đây 1 năm ≈ 0,5 điểm, càng xưa càng nhẹ. |
| **SEXP** | Kinh nghiệm **trong đúng subsystem**: tổng số commit quá khứ của tác giả trên từng subsystem mà commit hiện tại đụng tới (cộng dồn qua các subsystem). |

Bộ tính này đã kiểm định bằng **84 assert** trên repo tổng hợp (dựng bằng script, biết trước đáp án)
và đối chiếu tay với `git show --numstat` trên repo thật.

---

## 8. Chỉ số chất lượng công bố kèm mỗi dataset

1. **Fleiss' kappa** [T2] — tổng + theo nhóm CWE (§4 bước ⑤).
2. **Bảng đóng góp từng tool** — raw findings per tool, minh bạch tool nào "nói nhiều".
3. **Tỷ lệ build thành công tầng đắt** — cho biết độ phủ của xác thực đắt (đo thật: app thuần
   54–92%, library kiểu Spring 13–30% do dependency SNAPSHOT biến mất khỏi registry — giới hạn
   *data-availability của hệ sinh thái*, không phải lỗi pipeline).
4. **GOLD set kiểm tay** (kế hoạch giai đoạn kiểm định): lấy mẫu cụm gold + verified-clean, người
   thẩm định thủ công → đo precision thật của từng mức nhãn. **[chưa thực hiện — mục tiêu ~200–500 mẫu]**

---

## 9. Kết quả thực nghiệm đã có (5 repo, để hình dung quy mô)

| Repo | Kiểu | Commit | Build OK | Gold | Silver | Verified-clean | κ |
|---|---|---:|---:|---:|---:|---:|---:|
| train-ticket | app microservices | 274 | **92%** | **208** | 11.974 | 70 | −0,36 |
| mall-swarm | app microservices | 464 | 54% | 23 | 2.924 | 108 | −0,26 |
| spring-cloud-stream | library | 4.364 | ~30% | 26 | 5.764 | 1.004 | −0,39 |
| spring-cloud-kubernetes | library | 2.666 | ~13% | 0 | 585 | 264 | −0,47 |
| apache/giraph | framework Java | 1.128 | **67%** | 20 | 5.885 | **635** | −0,33 |
| apache/skywalking | app APM (monorepo) | 8.570 | đang chạy* | * | * | * | * |

\* skywalking đang chạy tại thời điểm viết (run #6, lớn nhất dự án) — cập nhật khi xong.

Bài học lớn đã kiểm chứng chéo: **chọn repo APP thuần thay vì library** (build được nhiều →
tầng đắt phủ rộng → nhiều gold); nguồn gold chủ đạo thực nghiệm: CSRF/CWE-352 tại SecurityConfig,
sensitive exposure (CWE-209/215/489), crypto/random yếu (CWE-326/330/338).

---

## 10. Giới hạn — nói thẳng (bắt buộc đọc trước khi dùng dataset)

1. **Consensus ≠ chân lý.** Các tool có thể cùng gốc rule → sai giống nhau (correlated errors).
   Nhãn gold là "nhiều nguồn độc lập nhất có thể", không phải "đã chứng minh có lỗ hổng".
2. **Thiên lệch lớp lỗi (coverage bias).** Phễu ưu ái lỗi mà tầng rẻ bắt tốt (secret, SQLi, XSS,
   misconfig); lỗi hiếm/sâu (race condition, logic flaw) gần như vắng mặt. Cần đo & công bố recall
   của bộ lọc rẻ. **[chưa đo — trong kế hoạch]**
3. **Tầng đắt chỉ phủ commit build được.** Repo có dependency đã biến mất khỏi registry thì phần
   lịch sử đó vĩnh viễn không có xác thực đắt (chỉ còn nhãn từ tầng rẻ).
4. **Secret không có tầng đắt** (CodeQL/FindSecBugs/Sonar không chuyên secret) → cụm secret trần
   ở mức silver.
5. **Ngưỡng là lựa chọn, không phải chân lý toán học** — mọi tham số (cửa sổ ±3 dòng, ngưỡng gold…)
   đều chỉnh được và ảnh hưởng kết quả; dự án bù đắp bằng việc lưu raw để tái tính và (kế hoạch)
   GOLD set kiểm tay.
6. **κ âm nghĩa là đồng thuận hiếm** — người dùng dataset nên hiểu gold là tập nhỏ nhưng quý, còn
   silver/candidate cần xử lý như nhãn yếu (weak supervision).

---

## 11. Tài liệu tham chiếu

| Mã | Nguồn | Dùng cho |
|---|---|---|
| [T1] | MITRE, **Common Weakness Enumeration (CWE)** — https://cwe.mitre.org | hệ mã phân loại lỗi (§1) |
| [T2] | Fleiss, J.L. (1971). *"Measuring nominal scale agreement among many raters."* Psychological Bulletin 76(5) | chỉ số kappa đa giám khảo (§4⑤, §8) |
| [T3] | Kamei, Y. et al. (2013). *"A Large-Scale Empirical Study of Just-in-Time Quality Assurance."* IEEE Transactions on Software Engineering 39(6) | 14 đặc trưng commit (§7) |
| [T4] | Bhandari, G., Naseer, A., Moonen, L. (2021). *"CVEfixes: Automated Collection of Vulnerabilities and Their Fixes from Open-Source Software."* PROMISE 2021 | ý tưởng mine CVE từ fix-commit (cột enrichment, §6) |
| [T5] | Rosen, C., Grawi, B., Shihab, E. (2015). *"Commit Guru: Analytics and Risk Prediction of Software Commits."* ESEC/FSE 2015 | quy ước xử lý merge/rename khi tính đặc trưng (§7) |
| [T6] | OASIS, **SARIF v2.1.0** (Static Analysis Results Interchange Format) — chuẩn OASIS, 2020 — https://docs.oasis-open.org/sarif/sarif/v2.1.0/ | định dạng chuẩn hoá output tool (§2.2, §5.4) |

> Lưu ý trích dẫn: các khẳng định *"tool SAST phủ bổ sung nhau / overlap thấp"* và *"tool đắt precision
> cao hơn tool rẻ"* trong tài liệu này dựa trên **số liệu thực nghiệm nội bộ của dự án (5 repo)** và
> đặc tính kỹ thuật của từng lớp tool; đây là quan sát nhất quán nhưng **chưa được kiểm chứng bằng một
> nghiên cứu benchmark độc lập trong khuôn khổ dự án** — người đọc học thuật nên đối chiếu thêm các
> nghiên cứu benchmark SAST công khai trước khi trích dẫn lại.

---

## 12. Tóm tắt 1 đoạn (elevator pitch)

> **Đưa vào 1 link GitHub — nhận về một dataset lỗ hổng bảo mật có bằng chứng.** Tool duyệt toàn bộ
> lịch sử commit, cho 5 tool rẻ sàng lọc rồi thả 2–3 tool đắt (build thật, phân tích sâu) vào các
> commit đáng ngờ và mẫu sạch đối chứng. Finding của mọi tool được gom cụm theo (file, nhóm-CWE,
> dòng ±3) và bỏ phiếu theo tầng: **gold** (tầng đắt xác nhận + nguồn thứ hai), **silver** (tín hiệu
> mạnh đơn nguồn), **candidate** (tín hiệu yếu), cùng mẫu âm 2 cấp (**verified-clean** / cheap-clean).
> Mỗi nhãn ghi rõ tool nào xác nhận; output thô từng tool được lưu 100% để tái lập; chất lượng
> dataset công bố kèm Fleiss' kappa và (kế hoạch) GOLD set kiểm tay. Mỗi dòng dữ liệu còn mang diff
> đã parse, cờ "commit tạo lỗi hay nợ cũ", và 14 đặc trưng Kamei — dùng được ngay cho cả bài toán
> phát hiện lỗ hổng mức dòng lẫn JIT defect prediction mức commit.
