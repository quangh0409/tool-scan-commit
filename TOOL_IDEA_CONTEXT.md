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

## 4. Schema dataset (đã chốt 2026-07 — CẤU TRÚC 2 MỨC)

Dataset xuất ra **2 file/repo**, phục vụ 2 granularity khác nhau:

**(a) `dataset.jsonl` — 1 dòng = 1 CỤM finding đồng thuận** (chỉ commit có finding):

```
repo, commit_id, parent_commit, commit_message, author_date,
file_path, s_line, e_line, function, s_detail_line[],
cwe[], owasp, cve(null | enrichment), category(code/secret/crypto/infra/info/other),
label(gold|silver|candidate), tier(cheap|expensive|mixed),
n_tools_ran, n_tools_agree, n_cheap, n_expensive, agreeing_tools[], eligible[],
confidence, finding_in_diff(0/1),
diff_parsed{added,deleted}, code_before_url, code_after_url,
lines_added, lines_deleted, kamei{14 đặc trưng}
```

**(b) `commits.jsonl` — 1 dòng = 1 COMMIT** (đủ MỌI commit, kể cả 0-finding):
`commit_id, repo, author, author_date, 14 đặc trưng Kamei, labels{}, role, negative_level(verified-clean|cheap-clean|null)` — dùng trực tiếp cho JIT defect prediction commit-level.

Kèm theo mỗi commit 1 thư mục export: raw output từng tool (SARIF/XML/JSON) + `<tool>.findings.json` + `label.json` + `summary.json` — audit/tái lập 100%.

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

**Bộ tool THỰC TẾ đã chốt (sau khi cắm & đo):** tầng rẻ = gitleaks, trufflehog, semgrep, bearer, horusec (5 tool); tầng đắt = FindSecBugs (~7s/commit), SonarQube (~22s/commit), CodeQL (~6.7'/commit, suite tối giản, công tắc `USE_CODEQL` — mặc định TẮT khi chạy full-history, bật chọn lọc để tăng gold). Snyk Code/Insider KHÔNG dùng (Snyk cần account/tier; Insider trùng vai Horusec).

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

### 7b. Quyết định nhãn & chất lượng (đã chốt qua 4 run thật, 2026-07 — chi tiết ở `RULE_GAN_NHAN.md`)

- **Nhãn 3 mức cross-tier:** `gold` (≥2 tool độc lập đồng thuận, có tầng đắt tham gia — GOLD KHÔNG bắt buộc CodeQL, FindSecBugs+Sonar đủ) · `silver` (1 tool đắt) · `candidate` (chỉ tầng rẻ). Kiến trúc **lưu RAW từng-tool → recompute**: `relabel` gán nhãn lại từ `raw_findings` trong ~30s, không quét lại; analyze thêm tool → nhãn TỰ nâng cấp.
- **Negative 2 cấp:** `verified-clean` (qua tầng đắt vẫn sạch = GOLD negative — chạy `--include-clean`) · `cheap-clean` (chỉ qua tầng rẻ = silver negative). Đây là điểm khác biệt của dataset so với các bộ JIT công khai.
- **`finding_in_diff` là trục phân positive/negative:** tool đắt quét whole-file nên phơi cả NỢ CŨ; chỉ finding nằm trên dòng commit thêm (in_diff=1) mới tính là "commit TẠO lỗi". Negative_level cũng xét theo trục này.
- **Lọc nhiễu trước consensus:** `NOISE_CWE` (mặc định CWE-117 — FindSecBugs log-injection FP hàng loạt) loại khỏi vote, raw vẫn giữ.
- **κ Fleiss ÂM là ĐẶC ĐIỂM hệ thống, không phải lỗi:** 4 repo đều κ ∈ [−0.26, −0.47] — các tool SAST phủ BỔ SUNG nhau (co-location dưới ngẫu nhiên). Hệ quả: đồng thuận hiếm nên gold quý; tăng recall = tăng SỐ tool, không phải tinh chỉnh 1 tool. κ được tính & công bố kèm mỗi dataset.
- **1 repo = 1 DB riêng (`ORCH_SQLITE`) + 1 thư mục export riêng.** KHÔNG trộn repo trong 1 DB (relabel/select sẽ trộn commit).

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

## 11. Chọn repo — TIÊU CHÍ ĐÃ KIỂM CHỨNG CHÉO (chốt 2026-07, thay kế hoạch "mở rộng Jenkins/Spring Cloud" cũ)

Bài học từ 4 repo full-history (train-ticket, mall-swarm, spring-cloud-stream, spring-cloud-kubernetes):

- **CHỌN APP THUẦN, KHÔNG chọn library.** App (train-ticket 92%, mall-swarm 54% build ok → gold 208/23) thắng áp đảo library Spring (30%/13% build ok → gold 26/0). Library kiểu Spring neo parent/dep `*-SNAPSHOT` nội bộ đã bị xoá khỏi registry → phần lớn lịch sử **không thể build lại bất kể JDK** — giới hạn *data-availability của hệ sinh thái*, không phải bug pipeline.
- **Tiêu chí thẩm định TRƯỚC khi chạy (chi phí ~0):**
  1. App Java/Maven tự chứa; `git show <sha-cũ>:pom.xml` KHÔNG neo SNAPSHOT nội bộ.
  2. Nhiều service có `SecurityConfig` (grep đếm được) — nguồn gold chủ đạo thực nghiệm là CSRF/CWE-352 + sensitive_exposure + crypto yếu.
  3. Đang phát triển gần đây (dependency closure còn sống trên Maven Central).
- **Thời lượng tham chiếu:** repo app ~300–500 commit ≈ 3–4h end-to-end trên e2-standard-8 (CodeQL tắt).
- Repo library vẫn CÓ giá trị phụ: nguồn verified-clean lớn (stream: 1004) — nhưng không phải nơi lấy gold positive.

## 12. Lộ trình build (tăng dần — TẤT CẢ trên VM cloud)

> Toàn bộ làm trên VM cloud (§8). Local chỉ bật/tắt VM + xem kết quả.

0. ✅ **Dựng VM + môi trường:** tạo `e2-standard-8`, cài Docker, clone repo dự án (chứa 2 file context này) lên VM, chạy Claude Code trên VM.
1. ✅ **Skeleton + source-only pipeline** (git enumerate → gitleaks/trufflehog/Semgrep/Bearer/Horusec qua Docker → normalize → consensus → SQLite). *Đã chứng minh end-to-end.*
2. ✅ **CodeQL/FindSecBugs/Sonar dạng Docker job** trên cùng VM (Maven build + auto-detect JDK per-commit).
3. ✅ **Quét full-history 4 repo** (xem `SESSION_CONTEXT.md`). Hướng mở rộng ĐÃ ĐỔI: theo tiêu chí app thuần §11, KHÔNG theo kế hoạch Jenkins/Spring Cloud cũ.
4. **Kế tiếp (giai đoạn kiểm định):** kiểm tay GOLD set (§6.3) đo precision → công bố; CodeQL chọn lọc trên buggy app để tăng gold; repo app #5.

## 13. DESKTOP APP `.exe` + CHÍNH SÁCH PHƯƠNG PHÁP LUẬN (chốt 2026-10-04 — SỬA §8–9)

> **ĐỔI so với §8–9:** máy local Windows **được chạy pipeline** (Docker Desktop) cho mục đích smoke-test, demo và nghiệm thu tái lập `--max 30`; full-history vẫn trên VM. Lý do: cần bản `.exe` cho người dùng cuối + demo hội đồng; đã vá 4 lỗi portability Windows (SESSION 2026-10-04). Kế hoạch: `TASKS.md`; thiết kế: `DESKTOP_APP_PLAN.md`; review: `REVIEW.md`.

- **Phạm vi:** đủ 10 màn (Preflight, Home, Wizard 5 bước, Dashboard, Results, Settings) + Kiểm tay GOLD. GUI = pywebview + web UI tĩnh + runner nền tách rời; orchestrator giữ stdlib-only; mọi hành động GUI = 1 lệnh CLI `--profile`.
- **Tiêu chí tái lập MVP:** train-ticket `--max 30` trên laptop: chạy từ exe → `profile.json` + `run_manifest.json`; chạy lại bằng CLI `--profile` → cùng số cụm theo nhãn; lệch chỉ ở commit `tool_timeout`/`infra_error` được liệt kê trong manifest.
- **Cấu hình v1 "đăng ký trước", KHOÁ:** `LINE_WINDOW=3`, `GOLD_MIN_EXPENSIVE=2`, `GOLD_ALLOW_1EXP_1CHEAP=1`, `SILVER_MIN_CHEAP=2`, `NOISE_CWE={CWE-117}`; `VOTE_THRESHOLD` legacy, bỏ khỏi UI. Đổi tham số **chỉ** qua `sensitivity` trên bản sao DB (lưới W∈{3,5,7}, 1E+1C∈{0,1}, NOISE on/off — mục bắt buộc của luận văn) hoặc "Chế độ thí nghiệm" (lý do bắt buộc, tag `experiment=true`, export `_exp_<tên>`, không gộp `gold_set_all`). Cơ sở: Simmons et al. 2011 (researcher degrees of freedom), Kerr 1998 (HARKing), Kitchenham et al. 2002, Saltelli et al. 2008; CLAUDE.md gốc §12.7/§12.9.
- **Thuật ngữ:** giữ cột nội bộ `gold/silver/candidate`; thêm trường `evidence = {consensus, validation ∈ {unreviewed, TP, FP, unclear}}`. UI/paper: "gold · đồng thuận máy" (= silver standard, Rebholz-Schuhmann et al. 2010) cho tới khi kiểm tay; chỉ "gold ✓ TP" là gold standard. `verified-clean` luôn kèm "2 tool đắt không báo — không phải chứng minh sạch".
- **Kiểm tay:** mẫu ngẫu nhiên phân tầng CWE-group × tier, seed cố định; n=200 gold positive + n=100 verified-clean; chế độ mù; 2 rater (fallback intra-rater cách ≥1 tuần); Cohen κ (Landis & Koch 1977; McHugh 2012); adjudication; precision + Wilson CI (Brown, Cai & DasGupta 2001). File chấm công bố cùng dataset.
- **Sửa dữ liệu trước GUI (P0):** 8 lỗi ở `REVIEW.md` §I.3, đặc biệt verified-clean giả (commit 0 module Java, 1 tool ok) và `build_failed` giả khi Docker tắt → đối soát lại `negative_level` trên 5 DB đã có, ghi delta `RESULTS.md`.
