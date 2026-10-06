# METHODOLOGY.md — Phương pháp luận gán nhãn & kiểm chứng (chốt cho luận văn)

> Nguồn quyết định: `TOOL_IDEA_CONTEXT.md` §13 (chốt 2026-10-04), `TASKS.md` §0, `CONTRACTS.md` §1–§2, `RULE_GAN_NHAN.md`.
> File này là **bản viết cho hội đồng/reviewer**: mọi tham số, thuật ngữ, giao thức kiểm tay và tiêu chí tái lập.
> Thay đổi ở đây là thay đổi phương pháp luận → chỉ sau khi ghi lý do (xem §3) — không sửa "cho đẹp số".

## 0. Bài toán & khung học thuật

- **Đầu vào:** 1 repo GitHub (Java/Maven) → từng commit → nhiều tool SAST (tầng rẻ: gitleaks, trufflehog, semgrep,
  bearer, horusec; tầng đắt: FindSecBugs, SonarQube, CodeQL tuỳ chọn).
- **Đầu ra:** dataset **cụm finding** `(repo, commit, file, nhóm-CWE, dòng ±W)` với nhãn đồng thuận
  `gold / silver / candidate`, cùng **mẫu âm cấp commit** `verified-clean / cheap-clean`.
- **Khung:** nhãn sinh bằng **đồng thuận đa-tool (multi-rater agreement)** → về bản chất là *silver standard*
  (Rebholz-Schuhmann et al. 2010): tool có lỗi tương quan (correlated errors), nên **đồng thuận ≠ chân lý**.
  Mẫu âm là *reliable negative* theo nghĩa PU-learning (Liu et al. 2003): "2 tool đắt không báo" ≠ "chứng minh sạch".
- Hệ quả bắt buộc: luôn đi kèm (i) κ Fleiss/Cohen làm tín hiệu sức khoẻ đồng thuận, (ii) kiểm tay mẫu phân tầng
  đo precision + CI, (iii) bảng "giới hạn" sinh tự động (`stats.limits`).

## 1. Cấu hình v1 "đăng ký trước" (pre-registered) — KHOÁ

| Tham số | Giá trị v1 | Vai trò | Lý do chốt |
|---|---|---|---|
| `LINE_WINDOW` | 3 | ±dòng để gộp 2 finding cùng (file, nhóm-CWE) thành 1 cụm | Cân bằng precision gộp (W nhỏ) ↔ recall ghép cặp FSB/Sonar lệch dòng (W lớn); W=7 chỉ dùng trong `sensitivity`, không đổi dataset gốc |
| `GOLD_MIN_EXPENSIVE` | 2 | ≥2 tool đắt đồng thuận → gold | Hai công cụ dòng khác nhau (bytecode pattern vs rule engine) cùng báo = bằng chứng mạnh nhất có được không cần người |
| `GOLD_ALLOW_1EXP_1CHEAP` | 1 | 1 đắt + ≥1 rẻ cũng = gold | Tool rẻ và đắt độc lập về kỹ thuật (source-only vs build); bật để không mất gold ở repo chỉ 1 tool đắt build được — và vì thế là mục **bắt buộc** của sensitivity |
| `SILVER_MIN_CHEAP` | 2 | ≥2 tool rẻ → silver | 1 tool rẻ đơn lẻ (candidate) FP cao (semgrep p/default, horusec) |
| `NOISE_CWE` | {CWE-117} | bỏ khỏi đồng thuận (raw vẫn giữ) | CWE-117 (CRLF log injection) FindSecBugs báo trên mọi `log(userInput)` → FP nặng, phá verified-clean (đo trên train-ticket/giraph) |
| `VOTE_THRESHOLD` | legacy | **không dùng** | Tham số chết của phiên bản single-tier; bỏ khỏi UI/run_meta, giữ biến để tương thích import |

Các giá trị này được ghi vào `profile.params_v1` và `run_manifest.params_v1`; `profile.validate()` **từ chối**
profile có `params_v1` khác v1 nếu không bật `experiment` kèm lý do ≥10 ký tự (CONTRACTS §2).

**Cơ sở lý luận "đăng ký trước":** Simmons, Nelson & Simonsohn (2011) — *researcher degrees of freedom*;
Kerr (1998) — HARKing; Kitchenham et al. (2002) — preliminary guidelines for empirical SE; Saltelli et al. (2008) —
sensitivity analysis thay cho dò tham số tay. Mục tiêu: tham số không được chọn *sau khi nhìn số*.

## 2. Thuật ngữ nhãn & trường `evidence`

| Cột nội bộ | Cách gọi trên UI/paper | Nghĩa chính xác |
|---|---|---|
| `gold` | **"gold · đồng thuận máy"** (silver standard) | E≥2, hoặc (1E+1C khi bật) — *chưa* người kiểm |
| `gold` + `evidence.validation=TP` | **"gold ✓ TP"** (gold standard) | đã kiểm tay, đúng |
| `gold` + `validation=FP` | "gold ✗ FP" | đã kiểm tay, sai → loại khỏi gold_set công bố |
| `silver` | silver | E=1 hoặc C≥2 |
| `candidate` | candidate | 1 tool rẻ |
| `verified-clean` | "verified-clean — 2 tool đắt không báo, không phải chứng minh sạch" | commit 0 finding `in_diff`, **`n_expensive_ok ≥ 2`** (tool `status=ok`, không tính `skipped`) |
| `cheap-clean` | cheap-clean | commit 0 finding tầng rẻ, chưa qua ≥2 tool đắt |

`evidence = {"consensus": gold|silver|candidate, "validation": unreviewed|TP|FP|unclear}` có trong mọi dòng
`dataset.jsonl` (CONTRACTS §6). `cluster_key = sha256(canon_repo|commit|file|cwe_group|s_line//LINE_WINDOW)[:32]`
là khoá ổn định để map phán quyết kiểm tay qua các lần `relabel` (CONTRACTS §5).

## 3. Chính sách đổi tham số

1. **Dataset chính luôn ở v1.** Mọi con số công bố (gold/silver/candidate, κ, precision) đi kèm `params_v1` và
   `experiment=null` trong `run_manifest.json`.
2. **Sensitivity (bắt buộc trong luận văn):** `sensitivity --db DB --out DIR` chạy lưới
   `LINE_WINDOW∈{3,5,7} × GOLD_ALLOW_1EXP_1CHEAP∈{0,1} × NOISE∈{on,off}` trên **bản sao** DB
   (`<out>/<cấu hình>.sqlite`), cùng raw, chỉ relabel → bảng gold/silver/candidate/κ theo cấu hình
   (`sensitivity.json/.md`). Báo cáo độ ổn định; **không** dùng kết quả này để đổi v1 giữa chừng.
3. **Chế độ thí nghiệm:** profile `experiment={"enabled":true,"reason":"…"}` → env `ORCH_EXPERIMENT=1`,
   `ORCH_EXPERIMENT_REASON`, khi đó (và chỉ khi đó) `ORCH_LINE_WINDOW` có hiệu lực; run gắn `run_meta.experiment=1`,
   export sang thư mục hậu tố `_exp`, **không gộp** vào `gold_set_all`. Không bật experiment mà đặt
   `ORCH_LINE_WINDOW` → bị bỏ qua, in cảnh báo (`config.reload()`).
4. Đổi v1 thật sự (phiên bản v2) = quyết định phương pháp luận: ghi lý do + ngày vào file này và
   `TOOL_IDEA_CONTEXT.md`, tăng `profile.schema`, chạy lại toàn bộ.

## 4. Giao thức kiểm tay GOLD (blind review)

- **Mẫu:** ngẫu nhiên **phân tầng** theo `cwe_group × tier` (`review sample --seed N --n-pos 200 --n-neg 100`);
  n_pos = 200 cụm gold, n_neg = 100 commit verified-clean; trên dữ liệu nhỏ lấy `min(n, số có)`
  (TASKS §0). Seed cố định → tái lập mẫu; `gold_sample` lưu `(sample_id, cluster_key, stratum, kind, seed)`.
- **Mù:** `review next` chỉ hiện code/diff + CWE claim, **ẩn** nhãn, tool, số tool đồng thuận.
- **Rater:** 2 người độc lập; fallback *intra-rater* (cùng người, cách ≥1 tuần). Phán quyết `TP | FP | unclear`
  + ghi chú → bảng `gold_review(cluster_key, sample_id, rater, verdict, note, at)`.
- **Thống kê (`review close`):** precision điểm = TP/(TP+FP) (unclear báo riêng), **Wilson 95% CI**
  (Brown, Cai & DasGupta 2001 — ưu tiên hơn Wald với n nhỏ/p gần 1); đồng thuận rater **Cohen κ**
  (Landis & Koch 1977 thang diễn giải; McHugh 2012 cảnh báo); danh sách bất đồng → **adjudication** (người thứ 3
  hoặc thảo luận), phán quyết cuối ghi `rater=adjudicated`.
- **Công bố:** file chấm (`gold_review` export) đi cùng dataset; gold công bố = `gold ✓ TP`; precision
  + CI nêu rõ cỡ mẫu và tầng.

## 5. Phân loại trạng thái (CONTRACTS §1) — vì sao quan trọng cho nhãn âm

| Trạng thái | Nghĩa | Ảnh hưởng nhãn |
|---|---|---|
| `ok` | tool chạy xong (kể cả 0 finding) | đếm vào `n_expensive_ok` |
| `skipped` | commit không có module Java → không build/không phân tích | **không** là verified |
| `build_failed` | Maven rc≠0 vì dữ liệu (dependency mất, compile lỗi) | commit chỉ còn nhãn tầng rẻ |
| `infra_error` | Docker/đĩa/mạng | commit về `pending`, **không** là dữ liệu; 3 lần liên tiếp → run dừng |
| `tool_timeout` / `tool_error` | 1 tool quá hạn / crash | tool đó không đếm `ok` |

Hai lỗi lịch sử đã sửa (REVIEW §I.3): *verified-clean giả* (commit 0 module Java, hoặc chỉ 1 tool ok) và
*build_failed giả* khi Docker tắt — cả hai được loại bằng định nghĩa `n_expensive_ok ≥ 2` và tách `infra_error`.

## 6. Tiêu chí tái lập (MVP)

- **Kịch bản:** train-ticket `--max 30` trên laptop. **Run A** = CLI `pipeline --profile P.json`;
  **Run B** = cùng profile chạy từ GUI/exe. Cả hai sinh `run_manifest.json` (profile, run_meta 2 tier, kappa,
  counts, danh sách `build_failed/infra_error/tool_timeout/skipped`, `orchestrator_git_sha`, `app_version`).
- **Kiểm:** `compare --a <export A> --b <export B> --format md` → `same / only_a / only_b / label_changed`
  theo `cluster_key`; lệch chỉ được chấp nhận khi commit nằm trong `tool_timeout | infra_error | skipped`
  (`explained_by`), ngược lại exit 1.
- **Điều kiện đi kèm:** cùng `params_v1`, cùng danh sách tool (bỏ tool → đổi mẫu số `eligible`/κ — CLI cảnh báo),
  cùng `LINE_WINDOW` (khác → `cluster_key` không tương thích, `compare` báo).
- **Provenance mỗi dòng:** `run_meta` (scope_json với `date_field=committer`, config_snapshot_json = env hiệu lực
  + argv + profile, tools_json với image digest, orchestrator_git_sha, app_version), `raw_output` nguyên bản.

## 7. Threats to validity (viết trước)

- *Internal:* correlated errors giữa tool cùng dòng (Sonar/FindSecBugs cùng pattern); lọc `NOISE_CWE` là lựa chọn
  của người thiết kế (có sensitivity); `in_diff` phụ thuộc chất lượng diff.
- *Construct:* "gold" = đồng thuận máy cho tới khi kiểm tay; `verified-clean` chỉ là "không bị 2 tool đắt báo".
- *External:* tầng đắt chỉ phủ commit build được (library Spring ~13% build-ok vs app ~54–92%) → thiên lệch
  theo thời kỳ/loại repo; chỉ Java/Maven.
- *Conclusion:* κ Fleiss thường âm vì tool phủ miền rời nhau → đọc κ theo nhóm-CWE/cặp tool, không κ tổng;
  precision kiểm tay có CI rộng khi n nhỏ.

## 8. Giới hạn của gộp cụm theo dòng (phát hiện trên smoke train-ticket, 2026-10-05)

Cụm = `(file, nhóm-CWE, dòng ±W)`. Phân tích của A1 trên DB smoke train-ticket (`sensitivity` 12 cấu hình
W∈{3,5,7} × 1E+1C∈{0,1} × noise on/off) cho **gold = 0 ở cả 12 cấu hình**; W=7 chỉ gộp thêm finding *cùng tool*.

Các tool đắt neo cùng một lỗi vào mức cú pháp khác nhau: FindSecBugs báo tại **khai báo** (method `configure(...)`,
field/class của controller), SonarQube báo tại **statement** (`.csrf().disable()`, tham số `@RequestBody`). Trên smoke
train-ticket, cặp cùng nhóm CWE gần nhất lệch **18–43 dòng**, nên mọi W ∈ {3,5,7} đều không tạo được cụm liên-tool
(gold = 0 ở 12 cấu hình; W=7 chỉ gộp thêm finding cùng tool). Nới W lớn hơn sẽ gộp nhầm các lỗi khác nhau cùng nhóm
CWE trong một file dài. **Hệ quả:** gold trên app Spring bị **ước lượng thiếu có hệ thống**, và κ âm giữa FSB–Sonar
phần lớn phản ánh **khác điểm neo**, không phải bất đồng về lỗi.

Cách xử lý trong luận văn:
- Báo cáo con số này như *giới hạn phương pháp* (câu tự sinh trong `stats.limits` khi DB có cả FSB và Sonar nhưng
  0 cụm liên-tool; trường `overview.cross_tool{expensive_tools_seen, fsb_sonar_clusters, multi_tool_clusters}`).
- **Không** nới W để "có gold": v1 giữ W=3; sensitivity đã chứng minh W∈{3,5,7} không đổi kết luận.
- Hướng sau MVP: **method-level clustering** (neo cụm theo method/class thay vì dòng) — là **thay đổi phương pháp luận**,
  chỉ được thử qua *experiment mode* (cờ `experiment`, export `_exp`, không gộp gold_set) và phải **kiểm tay** vì gộp
  theo method làm tăng nguy cơ ghép hai lỗi khác nhau cùng nhóm CWE.
- Threats (bổ sung §7): construct — "cùng lỗi" được định nghĩa bằng khoảng cách dòng; conclusion — số gold trên app
  Spring là cận dưới.

## Tham khảo

Brown, Cai & DasGupta (2001) *Interval estimation for a binomial proportion*. Statistical Science. ·
Kerr (1998) *HARKing: Hypothesizing After the Results are Known*. · Kitchenham et al. (2002) *Preliminary guidelines
for empirical research in software engineering*. TSE. · Landis & Koch (1977) *The measurement of observer agreement
for categorical data*. Biometrics. · Liu, Dai, Li, Lee & Yu (2003) *Building text classifiers using positive and
unlabeled examples*. ICDM. · McHugh (2012) *Interrater reliability: the kappa statistic*. Biochemia Medica. ·
Rebholz-Schuhmann et al. (2010) *CALBC silver standard corpus*. J. Bioinformatics & Comp. Biology. ·
Saltelli et al. (2008) *Global Sensitivity Analysis: The Primer*. Wiley. · Simmons, Nelson & Simonsohn (2011)
*False-positive psychology*. Psychological Science. · Kamei et al. (2013) *A large-scale empirical study of
just-in-time quality assurance*. TSE.
