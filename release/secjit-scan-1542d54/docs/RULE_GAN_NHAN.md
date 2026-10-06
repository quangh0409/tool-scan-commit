# RULE_GAN_NHAN.md — Quy tắc gán nhãn đồng thuận (consensus labeling)

> Tài liệu này định nghĩa **cách biến 7–8 bản scan/commit thành nhãn dataset** (gold / silver /
> candidate / negative). Mục tiêu: nhãn **minh bạch, tái lập, có cơ sở** — mỗi nhãn nói rõ *tool nào
> xác nhận* và *mạnh tới đâu*. Đọc kèm `consensus/matcher.py`, `consensus/cwe_groups.py`,
> `EXPENSIVE_TIER_REPORT.md` §5d (định nghĩa GOLD), `EXECUTION_FLOW.md`.

---

## 0. Nguyên tắc nền (ghi nhớ)
1. **Consensus = nhãn BẠC/VÀNG do máy suy, KHÔNG phải chân lý.** Luôn kèm: tool xác nhận, mức đồng
   thuận, và (mức dataset) Fleiss' kappa + GOLD set kiểm tay.
2. **Đắt precision cao hơn rẻ.** Tool đắt (CodeQL dataflow, Sonar semantic, FindSecBugs bytecode) chắc
   hơn tool rẻ (pattern-match trên source). Nhãn phản ánh điều này qua **tầng**.
3. **Lưu RAW từng-tool, không chỉ lưu cụm đã gộp.** Đổi công thức vote / trọng số / tính kappa về sau
   mà **không phải quét lại** — cực kỳ quan trọng vì scan đắt tốn giờ.

---

## 1. ĐƠN VỊ GÁN NHÃN = CỤM (cluster), KHÔNG phải commit

Sai lầm thường gặp: coi "8 tool → 8 phiếu cho 1 commit". **Không.** Mỗi tool báo nhiều finding ở nhiều
**vị trí** khác nhau. Ta gom về **cụm**, mỗi cụm là **một chỗ nghi lỗi**, và **vote riêng từng cụm**.

```
commit X  (7–8 tool cùng quét)
   ├─ cụm 1: sql_injection @ OrderDao.java:50     → tool nào báo? → nhãn riêng
   ├─ cụm 2: csrf          @ SecurityConfig:65    → tool nào báo? → nhãn riêng
   └─ cụm 3: hardcoded_secret @ config.yml:12     → tool nào báo? → nhãn riêng
```

→ 1 commit sinh **nhiều dòng dataset** (nhiều cụm), mỗi dòng 1 nhãn.

---

## 2. GỘP CỤM (clustering) — xuyên tầng rẻ + đắt

Hai finding (bất kể tool rẻ hay đắt) vào **cùng cụm** khi thoả CẢ 3:

| Điều kiện | Chi tiết |
|---|---|
| **Cùng file** | path chuẩn hoá (bỏ `/src/`, `/repo/`… → khớp path git) |
| **Cùng NHÓM-CWE** | gộp CWE anh-em qua `cwe_groups.py` (vd CWE-89/564/943 → `sql_injection`) — tránh việc 2 tool cùng chỉ SQLi mà khác mã CWE lại bị tách |
| **Line gần nhau** | \|line_a − line_b\| ≤ `LINE_WINDOW` (mặc định **3**) — tha thứ lệch dòng nhỏ giữa các tool |

**Cách làm cross-tier:** đổ **cả 5 finding rẻ + 3 finding đắt** của commit vào cùng `cluster_findings()`
→ tự gộp. (Hiện đã có hàm này cho tầng rẻ; chỉ cần cấp thêm finding đắt.)

> Ví dụ có thật: CWE-352 CSRF được CodeQL báo line **65**, Sonar báo line **67** → \|65−67\|=2 ≤ 3,
> cùng nhóm `csrf`, cùng file → **gộp 1 cụm**.

---

## 3. NĂNG LỰC TOOL (capability) — vì sao KHÔNG chia cho 8

Không tool nào bắt được **mọi** loại lỗi. Chia "số tool đồng thuận / 8" là **sai** vì nhiều tool
*không có khả năng* báo loại đó ngay từ đầu.

| Miền (domain) | Nhóm CWE ví dụ | Tool ĐỦ năng lực |
|---|---|---|
| **secret** | hardcoded_secret (CWE-798) | gitleaks, trufflehog, horusec — **3 tool** |
| **code** | sql_injection, xss, csrf, path_traversal, deserialization… | semgrep, bearer, horusec, codeql, findsecbugs, sonar — **6 tool** |

→ **Mẫu số = số tool ĐỦ NĂNG LỰC & ĐÃ CHẠY** (gọi là `eligible`), không phải tổng 8 tool.
Ví dụ cụm secret: dù chỉ 3 tool báo cũng có thể là "toàn bộ tool đủ năng lực đồng thuận" = rất mạnh.

`agreement_ratio = n_đồng_thuận / eligible` — **chỉ để tham khảo**; nhãn chính dựa vào **số tool + tầng**
(mục 4), không dựa ratio thô.

---

## 4. THANG NHÃN (label ladder) — kết hợp SỐ tool × TẦNG

Gọi **E = số tool ĐẮT** đồng thuận trong cụm, **C = số tool RẺ** đồng thuận.

| E (đắt) | C (rẻ) | **Nhãn** | Ý nghĩa |
|:---:|:---:|:---|:---|
| ≥ 2 | bất kỳ | **🥇 gold** | ≥2 tool đắt xác nhận — độ tin cao nhất |
| 1 | ≥ 1 | **🥇 gold** | 1 đắt + ≥1 rẻ — có xác nhận đắt + nguồn thứ 2 |
| 1 | 0 | **🥈 silver** | 1 tool đắt đơn lẻ — precision khá, chờ nguồn 2 |
| 0 | ≥ 2 | **🥈 silver** | ≥2 tool rẻ đồng thuận — mạnh vừa, chưa có đắt kiểm |
| 0 | 1 | **🟡 candidate** | đúng 1 tool rẻ — FP cao, cần soi |
| — | — | **⚪ negative** | commit/file 0 finding CWE/CVE (từ `scanned_files`) |

**Diễn giải nhanh:**
- **gold** = "đã có tầng đắt xác nhận" → dùng làm **positive chất lượng cao** (khớp bạn chốt: *2 tool đắt
  đủ gold, CodeQL không bắt buộc*).
- **silver** = mạnh nhưng chưa đủ chuẩn vàng (2 tool rẻ, hoặc 1 tool đắt đơn).
- **candidate** = tín hiệu yếu (1 tool rẻ) — giữ để nghiên cứu, không nên coi là lỗi thật.
- **negative** = mẫu âm. Chia 2 mức: `cheap-clean` (chỉ tầng rẻ sạch) và `verified-clean` (FindSecBugs +
  Sonar cũng sạch) — mức sau là **GOLD negative** (xem `EXPENSIVE_TIER_REPORT.md` §5d).

> **Ngưỡng có thể chỉnh** (config): mặc định như bảng trên. Muốn *chặt hơn* → gold chỉ khi **E ≥ 2**
> (bỏ dòng "1 đắt + rẻ"). Muốn *lỏng hơn* → gold khi **E ≥ 1**. Không phải sửa code, chỉ đổi tham số.

---

## 5. TRỌNG SỐ phiếu

**Mặc định: đếm bằng nhau (1 tool = 1 phiếu)** — sự ưu tiên tầng-đắt đã nằm sẵn trong *thang nhãn*
(mục 4), nên công thức đơn giản, dễ giải thích, dễ kiểm toán.

Vì đã **lưu raw**, sau này có thể nâng cấp **không cần quét lại**:
- *Trọng số theo tầng*: rẻ=1, đắt=2 → tính điểm `score = Σ trọng_số`.
- *Trọng số theo precision từng tool*: calib bằng GOLD set tay (vd CodeQL cao, FindSecBugs thấp vì
  nhiều FP CWE-117). Chính xác nhất, để giai đoạn sau.

---

## 6. CÁC TRƯỜNG LƯU vào mỗi dòng dataset (cụm)

| Trường | Ý nghĩa |
|---|---|
| `file_path`, `s_line`, `s_detail_line` | vị trí (bắt buộc) |
| `cwe`, `cwe_group`, `category` | mã CWE thô + nhóm đồng thuận + miền (secret/code…) |
| `agreeing_tools` | **danh sách tool đã báo** (minh bạch cốt lõi) |
| `n_agree`, `n_cheap`, `n_expensive` | số tool đồng thuận theo tầng |
| `eligible_tools`, `agreement_ratio` | mẫu số theo năng lực + tỉ lệ tham khảo |
| `label` | **gold / silver / candidate** |
| `tier` | cụm này có finding đắt không (cheap/expensive/mixed) |
| `finding_in_diff` | lỗi commit này TẠO (1) hay nợ cũ (0) — trực giao với nhãn |
| `confidence` | điểm tin (mặc định = agreement_ratio; sau nâng lên weighted) |

Ngoài ra **giữ bảng RAW** (mỗi finding per-tool 1 dòng) để tái tính & Fleiss' kappa.

### 6.1 Trường `evidence` và kiểm tay (bổ sung 2026-10-05, CONTRACTS §4/§6)

Mỗi dòng `dataset.jsonl` có thêm `cluster_key` (sha256 của `repo|commit|file|cwe_group|s_line//W`, ổn định qua
relabel) và `evidence` tách **hai nguồn bằng chứng không được gộp**:

| Trường | Giá trị | Nguồn |
|---|---|---|
| `evidence.consensus` | `gold` / `silver` / `candidate` | MÁY: thang nhãn §4 từ `agreeing_tools` (luật v1) |
| `evidence.validation` | `unreviewed` / `TP` / `FP` / `unclear` | NGƯỜI: bảng `gold_review` (chấm mù, `orchestrator.review`) |

- `TP` = nhãn máy **đúng** (cụm là lỗ hổng thật; với mục âm: commit thật sự sạch); `FP` = nhãn máy sai;
  `unclear` = không kết luận được. Gộp nhiều rater: **`adjudicated` (sau hoà giải) > đa số > hoà = `unclear`**.
- Người chấm **không thấy** nhãn, tên tool, số tool đồng thuận, tier (`review next` chỉ trả code ±8 dòng,
  diff, CWE tuyên bố, message đã xoá tên tool/rule). Precision = TP/(TP+FP) kèm **Wilson 95 %**; đồng thuận
  giữa 2 rater = **Cohen κ**; mẫu phân tầng `cwe_group × tier`, tái lập theo `seed`.
- **Negative**: `negative_level = verified-clean` **chỉ khi `n_expensive_ok >= 2`** (≥2 tool đắt chạy xong
  `status=ok` trên commit, không tính `skipped`/`tool_error`); commit chỉ đụng file không-Java hoặc chỉ 1 tool
  đắt ok là `cheap-clean`. Mục âm trong kiểm tay có `cluster_key = neg:<commit>`.
- **Wording hiển thị** (GUI/README, không được viết "đã xác minh" khi chưa chấm): `gold · đồng thuận máy`
  (validation = unreviewed) · `gold ✓ TP` · `gold ✗ FP` · `gold ? unclear`; tương tự cho silver/candidate.
  Số "precision gold" chỉ được báo kèm `n` và CI của mẫu đã chấm — không suy từ số tool đồng thuận.

---

## 7. Fleiss' KAPPA — độ tin cậy liên-tool (mức DATASET)

Ngoài nhãn từng cụm, ta đo **mức đồng thuận thực sự vượt ngẫu nhiên** trên toàn dataset:
- Lập ma trận **item × tool**: item = 1 vị trí (cụm ứng viên); mỗi tool *đủ năng lực* = 1 "giám khảo"
  bỏ phiếu **báo / không báo**.
- Tính **Fleiss' kappa** cho toàn bộ + theo từng nhóm CWE.
- Ý nghĩa: kappa cao = các tool đồng thuận đáng tin; kappa thấp = tool "cãi nhau" → nhãn cụm loại đó cần
  thận trọng / hạ tin. Đây là **thước đo sức khoẻ** của dataset, báo cáo kèm mỗi lần build.

---

## 8. VÍ DỤ minh hoạ (số liệu thật đã đo)

**Cụm A — CSRF @ ts-travel-service/.../SecurityConfig.java:~65**
- CodeQL (đắt) line 65 · FindSecBugs (đắt) · Sonar (đắt) line 67 → cùng nhóm `csrf`, line ≤ window → 1 cụm.
- E=3, C=0 → **🥇 gold**. `agreeing_tools=[codeql,findsecbugs,sonar]`, `tier=expensive`.

**Cụm B — quyền file Dockerfile (CWE-732) do 1 tool rẻ (semgrep)**
- E=0, C=1 → **🟡 candidate** (nhiễu hạ tầng điển hình — đúng như pilot cho thấy 86% là loại này).

**Cụm C — secret trong `.env` do gitleaks + trufflehog**
- E=0, C=2, eligible(secret)=3 → **🥈 silver** (2/3 tool secret đồng thuận; chờ tầng đắt không áp dụng
  cho secret → có thể coi silver là mức trần cho secret).

---

## 9. THAM SỐ cấu hình (dự kiến)
| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `LINE_WINDOW` | 3 | cửa sổ gộp dòng |
| `GOLD_MIN_EXPENSIVE` | 2 | số tool đắt tối thiểu để gold (nhánh "chỉ đắt") |
| `GOLD_ALLOW_1EXP_1CHEAP` | true | cho phép (1 đắt + ≥1 rẻ) = gold |
| `SILVER_MIN_CHEAP` | 2 | số tool rẻ tối thiểu để silver |
| trọng số | equal | equal / tier / precision (mở rộng sau) |

---

## 10. GIỚI HẠN & lưu ý (trung thực)
- **Nhãn là bạc/vàng, không phải chân lý** — cần GOLD set kiểm tay để đo precision thật của từng mức.
- **Tool cùng gốc → correlated**: Horusec có thể trùng engine với semgrep/gitleaks → đã chạy Horusec ở
  chế độ `-D` (chỉ HorusecEngine) để giảm; vẫn nên coi Horusec là tín hiệu phụ, không "cộng phiếu" ngang.
- **finding_in_diff trực giao với nhãn**: một cụm gold vẫn có thể là *nợ cũ* (không do commit này tạo).
  Muốn dataset "lỗi commit này TẠO" thì lọc thêm `finding_in_diff=1`.
- **secret không có tầng đắt** (CodeQL/FindSecBugs/Sonar không chuyên secret) → cụm secret trần ở
  **silver**; muốn nâng cần tool secret chuyên sâu hoặc kiểm tay.
- **Ngưỡng là lựa chọn, không phải chân lý toán học** — mọi ngưỡng ở §4/§9 chỉnh được; ta lưu raw để
  "quay số" thoải mái và đo lại bằng GOLD set.

---

## 11. TÓM TẮT 1 dòng
**Gom finding rẻ+đắt của 1 commit thành các CỤM `(file, nhóm-CWE, line±3)`; mỗi cụm đếm tool đồng thuận
theo TẦNG → gold (đắt xác nhận) / silver (2 rẻ hoặc 1 đắt) / candidate (1 rẻ); commit sạch → negative.
Lưu RAW từng-tool để tái tính + Fleiss' kappa. Minh bạch: mỗi nhãn ghi rõ tool nào xác nhận.**
