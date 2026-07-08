# Luồng TỔNG QUAN: input → output (song song/tuần tự + chi phí time đã ĐO)

> Số time là **đo thực** trên VM e2-standard-8 (8 vCPU / 32GB). "⏱" = đã đo; ước tính ghi rõ "(~)".
> Đã kiểm chứng ở quy mô **full-history 4 repo** (274 → 4364 commit/repo, tổng ~31h máy — bảng cuối file).
> Lệnh trọn gói: `pipeline <repo> --max 0 --codeql 0 --include-clean` (+ `ORCH_SQLITE`/`--out` riêng theo repo).

```
INPUT: 1 link GitHub repo
   │
   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ ① ENUMERATE + LỌC THÔ + KAMEI   (git thuần, KHÔNG Docker — TUẦN TỰ)           │
│   clone/update → list N commit (--max 0 = hết) → coarse_filter:              │
│     bỏ merge / no-file / toàn-nhị-phân; (FLAG_LIMIT=1) bỏ commit khổng lồ     │
│     (mặc định FLAG_LIMIT=0 khi chạy full — KHÔNG bỏ, quét cả bulk-commit).    │
│   + KAMEI: 14 đặc trưng JIT (1 lượt git log --numstat, TRƯỚC pool worker)     │
│   ⏱ enumerate vài giây; Kamei 464 commit = 1.2s · 4364 commit = 3.3s          │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                   ▼  danh sách commit "giữ" + commit_features
┌─────────────────────────────────────────────────────────────────────────────┐
│ ② TẦNG RẺ — SCAN (Model B)         SONG SONG 2 TRỤC, KHÔNG build              │
│                                                                               │
│   ThreadPoolExecutor(SCAN_WORKERS=4)  ── clone-pool (1 clone/worker, pid-riêng)│
│    ├ w1: commit A ─┐                                                          │
│    ├ w2: commit B ─┤  mỗi commit: 5 TOOL chạy SONG SONG (CHEAP_INTRA_PARALLEL=1)│
│    ├ w3: commit C ─┤    gitleaks ║ trufflehog ║ semgrep ║ bearer ║ horusec    │
│    └ w4: commit D ─┘    (secret quét git-diff; code quét file-đổi)            │
│                         → raw_findings + raw_output (LƯU THÔ từng tool)       │
│                         → relabel_commit → findings (label=candidate, kamei)  │
│                         → scanned_files (file 0-finding = mẫu negative)       │
│   ⏱ full-history: ~425–645 commit/h (4 worker). 464 commit = 35' · 4364 = 5.7h│
└─────────────────────────────────┬───────────────────────────────────────────┘
                                   ▼  raw + findings (rẻ) + scanned_files
┌─────────────────────────────────────────────────────────────────────────────┐
│ ③ SELECT — phân loại    (đọc DB, TUẦN TỰ, tức thì)                            │
│   buggy = commit có ≥1 finding mang CWE/CVE → selected_commits (positive)     │
│   clean = 0 CWE/CVE:                                                          │
│     --include-clean (CHUẨN hiện tại) → CŨNG vào tầng đắt để VERIFY            │
│         vẫn sạch → verified-clean (GOLD negative) · ra lỗi in_diff → positive │
│     không flag → chỉ làm cheap-clean (silver negative), miễn quét đắt         │
│   ⏱ <1s. Ví dụ mall-swarm: 279 = 60 buggy + 219 clean.                        │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                   ▼  hàng đợi selected_commits (status=pending)
┌─────────────────────────────────────────────────────────────────────────────┐
│ ④ TẦNG ĐẮT — ANALYZE (Model A)   SONG SONG CẤP COMMIT, TUẦN TỰ TOOL/commit    │
│                                                                               │
│   [1 lần/run] SonarQube SERVER singleton: start + đổi pw/token QUA API ⏱54s   │
│                                                                               │
│   ThreadPoolExecutor(EXPENSIVE_WORKERS=2) ── clone-pool · pull+CLAIM nguyên tử │
│    ├ w1: claim commit → ┌─ checkout -qf (fail → git clean -fdxq + retry)      │
│    │                    ├─ AUTO-DETECT JDK (pom tại sha → temurin 8/11/17/21) │
│    │                    ├─ BUILD 1 LẦN (mvn -pl <mod> -am, dùng chung) ⏱14–33s│
│    │                    │     fail → build_failed (ghi lý do, đi tiếp)        │
│    │                    ├─ [USE_CODEQL=1] CodeQL minimal-suite ──── ⏱~6.7'    │
│    │                    │   (mặc định TẮT khi chạy full-history: --codeql 0)  │
│    │                    ├─ FindSecBugs (đọc classes build) ───────── ⏱7s      │
│    │                    └─ SonarQube  (scanner+API, classes+/m2 jar) ⏱22s     │
│    │                    → raw đắt + relabel_commit (nhãn TỰ nâng cấp)         │
│    │                    → status=done → claim commit kế                        │
│    │   1 commit lỗi bất kỳ → try/except CÔ LẬP: ghi failed, KHÔNG giết worker │
│    └ w2: (song song commit khác, cùng khuôn)                                  │
│                                                                               │
│   ⏱ không CodeQL ≈ 30s–1'/commit build-ok; throughput ĐO 36→94 commit/h       │
│      (2 worker, tăng dần khi cache .m2 ấm). 279 commit ≈ 3h · 3741 ≈ 10h.     │
│   Crash-resume: claim nguyên tử + reset_stale_claims(7200s) → chạy lại        │
│   `analyze` là vét tiếp, KHÔNG mất dữ liệu, KHÔNG scan lại.                   │
│   [cuối run] stop SonarQube server.                                           │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                   ▼  raw_findings đủ 2 tầng
┌─────────────────────────────────────────────────────────────────────────────┐
│ ⑤ RELABEL — CROSS-TIER CONSENSUS   (đọc raw trong DB, KHÔNG quét lại)         │
│   gộp cụm rẻ+đắt (file + nhóm-CWE + dòng ±3) → vote tier-aware:               │
│     gold (≥2 tool có đắt) · silver (1 đắt) · candidate (chỉ rẻ)               │
│   lọc NOISE_CWE (CWE-117…) trước vote; negative_level theo finding_in_diff:   │
│     verified-clean (GOLD) / cheap-clean; kèm kamei vào mọi row                │
│   ⏱ ~30s / 39 commit; chịu được diff 290MB ngoài-UTF8 (errors="replace")      │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ ⑥ KAPPA + EXPORT                                                              │
│   kappa: Fleiss' κ từ raw (item=cụm, rater=tool đủ-năng-lực-đã-chạy)          │
│     → 4 repo ĐO: κ ∈ [−0.26, −0.47] = tool phủ BỔ SUNG (đặc điểm, không lỗi)  │
│   export: mỗi commit 1 thư mục (<tool>.raw + .findings + label + summary)     │
│     + dataset.jsonl (1 dòng=1 cụm) + commits.jsonl (1 dòng=1 commit, kamei)   │
│     ⚠️ 2 file jsonl hiện gộp bằng script inline — backlog: scripts/merge_export│
│   ⏱ export 464 commit ≈ 1–2'                                                  │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                   ▼
OUTPUT (MỖI REPO RIÊNG — không trộn DB):
   • data/dataset_<repo>.sqlite: findings (label/tier/kamei), raw_findings,
     raw_output, scanned_files, selected_commits, commit_features,
     expensive_runs (telemetry), run_meta (version+digest)
   • data/export_<repo>/: N thư mục commit + dataset.jsonl + commits.jsonl
```

---

## Bảng chi phí time (đã đo) theo bước

| Bước | Song song? | Chi phí ĐO | Ghi chú |
|---|---|---|---|
| ① enumerate + lọc + Kamei | tuần tự | vài giây + 1.2–3.3s Kamei | git thuần, cả full-history |
| ② scan tầng rẻ | **2 trục: 4 commit × 5 tool** | **~425–645 commit/h** | 464c=35' · 2666c=5h · 4364c=5.7h |
| ③ select | tuần tự | <1s | đọc DB |
| ④ build (dùng chung) | — | **14–33s** (cold 42s) | `-pl <mod> -am` + auto-detect JDK |
| ④ FindSecBugs | (tuần tự trong commit) | **7s** | bytecode, xài classes build |
| ④ SonarQube | (tuần tự) | scan **22s** + server **54s/run** | BẮT BUỘC `sonar.java.libraries=/m2` |
| ④ CodeQL (tuỳ chọn) | (tuần tự) | DB 29s + analyze **376s** (minimal) | code-scanning suite ~20'; mặc định TẮT |
| ④/commit (2 tool, không CodeQL) | — | **≈30s–1'** build-ok; 36→94 c/h/2-worker | tăng dần khi .m2 ấm |
| ⑤ relabel | tuần tự | **~30s / 39 commit** | từ raw, không quét lại |
| ⑥ kappa + export | tuần tự | ~giây + 1–2'/464 commit | |

## Chi phí TRỌN GÓI đã đo (full-history, --codeql 0 --include-clean)

| Repo | Commit | ② scan | ④ analyze (done/fail) | Tổng wall | Kết quả nhãn |
|---|---|---|---|---|---|
| train-ticket (app) | 274 | ~35' | 160/14 (92% ok) | **~2.5h** | gold 208 · vclean 70 |
| mall-swarm (app) | 464 | ~35' | 151/128 (54%) | **~3.7h** | gold 23 · vclean 108 |
| spring-cloud-kubernetes (lib) | 2666 | ~5h | 300/1955 (13%) | **~8.5h** | gold 0 · vclean 264 |
| spring-cloud-stream (lib) | 4364 | ~5.7h | 1110/2631 (30%) | **~16.5h** | gold 26 · vclean 1004 |

→ Quy tắc ngón tay cái: **repo app 300–500 commit ≈ 3–4h end-to-end**; build_failed của library
là SNAPSHOT data-availability (không sửa được bằng JDK/pipeline — xem `TOOL_IDEA_CONTEXT.md` §11).

---

## Song song vs Tuần tự — chốt ở đâu & vì sao

| Vị trí | Chế độ | Lý do |
|---|---|---|
| **Giữa các commit (cả 2 tầng)** | **SONG SONG** (clone-pool) | mở khoá throughput; clone pid-riêng, không clobber |
| **Tool trong 1 commit — TẦNG RẺ** | **SONG SONG** (Model B) | tool nhẹ → nhanh ~14%; đo thực |
| **Tool trong 1 commit — TẦNG ĐẮT** | **TUẦN TỰ** (Model A) | tool nặng RAM/CPU; build c2 đè analyze c1 (bù pha); tránh thrash |
| **Build/commit** | tuần tự (1 lần, dùng chung) | CodeQL tự build-trace riêng; FindSecBugs+Sonar xài lại classes |
| **SonarQube server** | singleton (1 lần/run) | server JVM ~2GB; bật/tắt mỗi commit phí |
| **Kamei** | tuần tự, 1 lượt TRƯỚC pool | state tăng dần phụ thuộc thứ tự CŨ→MỚI |

**Số worker:** rẻ `SCAN_WORKERS=4` (tool nhẹ, ~20 container đỉnh OK); đắt `EXPENSIVE_WORKERS=2`
(mỗi commit ăn build+JVM vài GB → giới hạn RAM 32GB).

---

## Độ bền (đã kiểm chứng bằng 2 sự cố thật + resume)

- **Cô lập lỗi từng commit** (`expensive_runner._loop` try/except): 1 commit hỏng ghi `failed` rồi đi tiếp — không giết worker/run.
- **Checkout chống artefact:** `checkout -qf`; vẫn fail → `git clean -fdxq` + retry.
- **Diff ngoài UTF-8** (file GBK 290MB): `errors="replace"` ở `_git`/repo_pool/tools.base.
- **Resume:** claim nguyên tử + `reset_stale_claims(7200s)`; chạy tiếp bằng LỆNH CON
  (`analyze`→`relabel`→`kappa`→`export`), KHÔNG chạy lại `pipeline` (tránh scan lại).
  Lưu ý vận hành: sau crash, commit kẹt `building` cần chờ stale-reset lượt sau mới vét được.

## Nút thắt & núm chỉnh

- **Không CodeQL:** nút thắt = build Maven (tỷ lệ build-ok quyết định độ phủ gold/verified-clean
  → chọn repo APP, xem tiêu chí §11 `TOOL_IDEA_CONTEXT.md`). Núm: `EXPENSIVE_WORKERS`, cache .m2.
- **Có CodeQL:** nút thắt = CodeQL analyze. Núm: `CODEQL_SUITE` (minimal 10-query → 6.7')
  / `CODEQL_THREADS` / `CODEQL_RAM_MB` / bật chọn lọc chỉ trên buggy đã build-ok.
- **Núm chi phí phễu** = `--include-clean` (x2–5 số commit lên tầng đắt, đổi lấy verified-clean GOLD)
  + `CLEAN_PER_BUGGY` + top-K ở select.
- Tăng tốc thêm (chưa làm): container ấm, cache theo blob-sha, scale ngang nhiều VM.
