# TOOL_IDEA_CONTEXT

> Ý tưởng gốc của dự án. File này KHÔNG ghi tiến độ — chỉ ghi *mục tiêu, bối cảnh, quyết định kiến trúc*. Tiến độ nằm ở `SESSION_CONTEXT.md`.

---

## 1. Một câu mô tả

Một **orchestrator**: input = **1 link GitHub** → duyệt từng commit → chạy **nhiều tool SAST** → chuẩn hoá output → **so khớp & bỏ phiếu (consensus)** giữa các tool → xuất ra một **GROUND TRUTH dataset** (mỗi dòng = 1 finding / 1 cụm đồng thuận).

## 2. Mục tiêu sử dụng dataset (cả 3)

- **Train model** phát hiện lỗ hổng (cần cả positive lẫn negative, granularity hàm + dòng).
- **Benchmark** các tool SAST với nhau (cần ground truth để đo precision/recall).
- **Nghiên cứu** (cần reproducibility + chỉ số đo độ tin của nhãn).

## 3. Loại lỗi quan tâm

"Commit này có lỗi bảo mật gì" — ví dụ: **lộ key/secret, SQL Injection, XSS, path traversal, SSRF…**
→ Nhãn thật của dự án là **CWE-class**, KHÔNG phải CVE.

| Loại lỗi | Nhãn | Tool bắt tốt |
|---|---|---|
| Lộ key/secret | CWE-798 / CWE-259 | gitleaks, trufflehog, Semgrep |
| SQL Injection | CWE-89 | CodeQL, Semgrep, FindSecBugs |
| XSS / Path traversal / SSRF | CWE-79 / 22 / 918 | CodeQL, Semgrep, Sonar |

## 4. Schema dataset (output mỗi dòng)

Field người dùng yêu cầu + bổ sung để dataset dùng được:

```
repo, commit_id, parent_commit, commit_message, author_date,
file_path, s_line, e_line, function,
tool, rule_id, severity,
cwe[], owasp, cve(null | enrichment),
lines_added, lines_deleted,
code_snippet,
n_tools_ran, n_tools_agree, agreeing_tools[], agreement_ratio,
confidence, silver_label
```

## 5. Bộ tool (BẮT BUỘC đủ — để đảm bảo chất lượng)

| Tool | Mức | CWE | Diff/PR | Java | Free | Cần build? |
|---|---|---|---|---|---|---|
| **Semgrep** | source | ✅ | ✅ `--baseline-commit` | ✅ | ✅ | Không |
| **CodeQL** (GitHub) | semantic dataflow | ✅ | ✅ code scanning | ✅ | ✅ OSS | **Có (build DB)** |
| **FindSecBugs** (SpotBugs) | bytecode | ✅ ~140 pattern→CWE | qua CI | ✅ | ✅ | **Có (compile)** |
| **SonarQube/Cloud** | source | ✅ vuln + hotspot | ✅ PR decoration | ✅ | community free | **Có (build Java)** |
| **Snyk Code** (DeepCode AI) | ML-SAST | ✅ | ✅ PR | ✅ | tier free | Không |
| **Bearer / Insider / Horusec** | source | ✅ | ✅ | ✅ | ✅ | Không |

Bổ sung Tầng rẻ: **gitleaks, trufflehog** (bắt secret).

## 6. BA ĐÍNH CHÍNH QUAN TRỌNG (đã thống nhất)

1. **SAST không sinh ra CVE.** CWE = *loại điểm yếu* (SAST tag được). CVE = *lỗ hổng cụ thể đã công bố trong sản phẩm/phiên bản* = địa hạt **SCA** (Snyk Open Source, Dependency-Check, Trivy). ⇒ Cột `CVE` gần như luôn null; chỉ có giá trị nếu **mine từ fix-commit** (CVEfixes-style: commit "fixes CVE-xxxx" → commit cha = phiên bản dính lỗi) hoặc thêm bước SCA. Để CVE là **cột enrichment tuỳ chọn**.

2. **Không thể quét-mọi-commit-bằng-mọi-tool.** CodeQL/FindSecBugs/Sonar cần build; nhiều commit lịch sử không build nổi; chi phí ×chục nghìn commit = hàng nghìn giờ CPU → cháy $300. ⇒ Dùng **mô hình phễu** (xem mục 7).

3. **"Đồng thuận nhiều tool = chuẩn" chỉ là NHÃN BẠC (silver label), không phải chân lý.** Các tool dùng chung gốc rule → sai giống nhau (correlated errors). ⇒ Coi consensus là **confidence score + nhãn yếu**, kèm: ngưỡng vote, đo **Fleiss' kappa** (độ đồng thuận liên-tool), và **validate tay 1 GOLD set (~200–500 mẫu)**.

## 7. KIẾN TRÚC PHỄU (đã chốt — điều kiện sống còn của dự án)

Nguyên tắc 1 dòng: **dùng tool RẺ lọc ra chỗ đáng nghi, chỉ thả tool ĐẮT vào đó.**

```
Chục nghìn commit
 ① LỌC THÔ      : bỏ merge / docs / non-Java        (chỉ metadata, ~free)
 ② SÀNG RẺ      : gitleaks + trufflehog + Semgrep + Bearer/Horusec
                  trên DIFF, KHÔNG build → candidate + lines_add/del   (vài giây/commit)
 ③ CHỌN MẪU     : commit vào tầng đắt nếu:
                  (a) bị tầng ② flag, HOẶC
                  (b) là fix-commit mine từ CVE/issue (van an toàn recall), HOẶC
                  (c) sample ngẫu nhiên (để có NEGATIVE + hiệu chuẩn)
                  → từ vài nghìn còn VÀI TRĂM commit
 ④ ĐÀO SÂU ĐẮT  : CodeQL + FindSecBugs + SonarQube (có build) — chỉ vài trăm commit
 ⑤ CHUẨN HOÁ    : mọi output → SARIF 2.1.0 (adapter riêng cho FindSecBugs/Bearer/Horusec)
 ⑥ BỎ PHIẾU     : đồng thuận K/N tool → nhãn bạc + confidence + Fleiss' kappa
```

**Núm điều khiển chi phí = top-K/ngưỡng ở Tầng ③.**

**Vì sao không mất chất lượng:** chất lượng *nhãn* đến từ nhiều tool đồng thuận trên CÙNG đoạn code, không phải từ việc quét hết mọi commit. Cái bị bỏ là commit "chắc chắn sạch". Rủi ro "lỗi chỉ CodeQL bắt được" được vá bằng nhánh ③(b) fix-commit.

**Cái giá phải trả (ghi rõ trong tài liệu dataset):** dataset thiên về lớp lỗi tầng-rẻ + đồng-thuận bắt tốt (secret/SQLi/XSS), ít lỗi hiếm (race condition, logic flaw). Phải đo & công bố **recall của bộ lọc** (so sánh sample ngẫu nhiên tầng rẻ vs tầng đắt).

## 8. TRIỂN KHAI — TẤT CẢ TRÊN CLOUD, CHẠY ON-DEMAND (đã chốt — Phiên 2)

> **ĐỔI so với Phiên 1.** Trước đây chia local/cloud. Nay **bỏ chia — toàn bộ pipeline chạy trên 1 môi trường cloud (GCP).** Tool dùng cá nhân: khi cần thì **bật VM lên chạy, xong thì tắt** để khỏi tốn tiền.

**Lý do đổi:** đơn giản hoá vận hành (1 môi trường duy nhất), bỏ được toàn bộ phần bàn giao async local↔cloud, không treo máy dev local. Mô hình phễu (§7) **vẫn giữ nguyên** vì $300 vẫn hữu hạn.

```
GCP VM (bật khi cần) — chạy TOÀN BỘ funnel tuần tự trên cùng 1 máy:
  ① git clone + enumerate + lọc thô
  ② source-only: gitleaks/trufflehog/Semgrep/Bearer/Horusec
  ③ chọn mẫu top-K
  ④ build-tools: Maven build + CodeQL + FindSecBugs + SonarQube
  ⑤⑥ normalize → consensus → dataset
Lưu: dataset (SQLite/Parquet) → THẲNG trên Persistent Disk của VM (KHÔNG dùng GCS)
```

- **Claude Code chạy NGAY TRÊN VM cloud** — đọc 2 file context này (`TOOL_IDEA_CONTEXT.md` + `SESSION_CONTEXT.md`) để bootstrap khi sang môi trường mới.
- **Không còn manifest/bucket-handoff async** (đã bỏ) — mọi tầng cùng 1 máy nên gọi trực tiếp.
- **Máy local** chỉ còn vai trò: bật/tắt VM (`gcloud`), ssh vào, và tải dataset về xem (tuỳ chọn).

### Cấu hình cloud
- **VM:** `e2-standard-8` (8 vCPU / 32GB) — đủ build service train-ticket + chạy source-only tools. On-demand thủ công (tự tắt khi xong); Spot tuỳ chọn để rẻ hơn.
- **Disk:** persistent SSD 100–200GB (repo clone + CodeQL DB tạm + dataset).
- **Lưu dài hạn:** dataset cuối lưu **thẳng trên Persistent Disk của VM** (KHÔNG dùng GCS bucket); tải về HDD local khi cần. ⚠️ Persistent Disk sống sót khi **STOP** VM, nhưng sẽ mất nếu **DELETE** VM/disk — chỉ stop, đừng delete; muốn an toàn thì tải bản sao về HDD local.
- **Tiết kiệm:** nhớ **TẮT/STOP VM** sau mỗi lần chạy — đây là cơ chế kiểm soát chi phí $300 chính.

## 9. Tài nguyên hiện có

- **GCP:** $300 free credit — **chạy TẤT CẢ pipeline ở đây** (xem §8).
- **Local:** Windows 11, 16GB RAM, Docker đã cài — chỉ dùng để điều khiển VM (`gcloud`/ssh) và xem dataset. KHÔNG còn chạy tool.
- **HDD ngoài:** 60GB trống — nơi tải dataset cuối về lưu (tuỳ chọn).
- **SSH box:** 40GB — không còn vai trò bắt buộc (trước là máy cày phụ; nay mọi thứ trên cloud).

### Trên VM cloud chạy gì
- Toàn bộ tool dưới dạng Docker (source-only + build-tools).
- SonarQube: container `sonarqube:lts-community` ephemeral mỗi lần chạy.
- CodeQL DB: để trên disk VM, quét xong xoá ngay.
- Dataset: SQLite/Parquet → lưu thẳng trên Persistent Disk của VM (KHÔNG GCS).

## 10. Stack kỹ thuật

- **Python orchestrator** + **mỗi tool 1 Docker** + **SQLite/Parquet**.
- Chuẩn hoá về **SARIF 2.1.0**; adapter riêng cho FindSecBugs (SpotBugs XML), Bearer, Horusec (JSON).
- **Matcher/Consensus:** cụm finding theo `(file chuẩn hoá, CWE, line ±W)` → đếm vote.

## 11. Repo test (pilot)

`https://github.com/FudanSELab/train-ticket` — ~40+ microservice Spring Boot, Maven đa-module, + chút TS/Python. **KHÔNG nhỏ.** Pilot chỉ chạy ~50–100 commit đầu để kiểm thử pipeline, rồi mới mở rộng sang Jenkins/Spring Cloud.

## 12. Lộ trình build (tăng dần — TẤT CẢ trên VM cloud)

> Toàn bộ làm trên VM cloud (§8). Local chỉ bật/tắt VM + xem kết quả.

0. **Dựng VM + môi trường:** tạo `e2-standard-8`, cài Docker, clone repo dự án (chứa 2 file context này) lên VM, chạy Claude Code trên VM.
1. **Skeleton + source-only pipeline** (git enumerate → gitleaks/trufflehog/Semgrep/Bearer/Horusec qua Docker → normalize → consensus → SQLite). Test trên ~50 commit train-ticket. *Chứng minh end-to-end.*
2. Thêm **CodeQL/FindSecBugs/Sonar dạng Docker job** ngay trên cùng VM (Maven build + tạo DB) để chỉnh adapter SARIF.
3. **Quét full + mở rộng repo** (Jenkins/Spring Cloud). Dataset lưu thẳng trên Persistent Disk VM, STOP VM khi xong (đừng delete).
