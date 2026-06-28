# Luồng TỔNG QUAN: input → output (song song/tuần tự + chi phí time đã ĐO)

> Số time là **đo thực** trên VM e2-standard-8 (8 vCPU / 32GB), repo pilot train-ticket
> (Spring Boot 2.3, JDK8). "⏱" = đã đo; ước tính ghi rõ "(~)".

```
INPUT: 1 link GitHub repo
   │
   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ ① ENUMERATE + LỌC THÔ   (git thuần, KHÔNG Docker — TUẦN TỰ, rất nhanh)        │
│   clone/update repo → list N commit mới nhất (--max) → coarse_filter:         │
│     bỏ merge / no-file / toàn-nhị-phân; (FLAG_LIMIT=1) bỏ commit khổng lồ.    │
│   ⏱ vài giây cho ~50 commit. 50 commit train-ticket → 29 giữ.                 │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                   ▼  danh sách commit "giữ"
┌─────────────────────────────────────────────────────────────────────────────┐
│ ② TẦNG RẺ — SCAN (Model B)         SONG SONG 2 TRỤC, KHÔNG build              │
│                                                                               │
│   ThreadPoolExecutor(SCAN_WORKERS=4)  ── clone-pool (1 clone/worker, pid-riêng)│
│    ├ w1: commit A ─┐                                                          │
│    ├ w2: commit B ─┤  mỗi commit: 5 TOOL chạy SONG SONG (CHEAP_INTRA_PARALLEL=1)│
│    ├ w3: commit C ─┤    gitleaks ║ trufflehog ║ semgrep ║ bearer ║ horusec    │
│    └ w4: commit D ─┘    (secret quét git-diff; code quét file-đổi)            │
│                         → consensus (gộp cụm CWE) → ghi findings(tier=cheap)  │
│                         → scanned_files (file 0-finding = mẫu negative)       │
│   ⏱ 29 commit / 4 worker: Model B 227s (~3.8') · Model A (tuần tự tool) 264s  │
│      (B nhanh ~14%; commit khổng lồ fa8d9efb 983 file chi phối wall-clock)    │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                   ▼  bảng findings (rẻ) + scanned_files
┌─────────────────────────────────────────────────────────────────────────────┐
│ ③ SELECT — phân loại    (đọc DB, TUẦN TỰ, tức thì)                            │
│   buggy  = commit có ≥1 finding mang CWE/CVE → ĐẨY vào selected_commits  ┐    │
│   clean  = 0 CWE/CVE → NEGATIVE (lấy hết, KHÔNG quét đắt) ────────────┐  │    │
│   ⏱ <1s. train-ticket: 29 → 17 buggy + 12 clean.                     │  │    │
└──────────────────────────────────────────────────────────────────────┼──┼───┘
                              negative dataset ◄───────────────────────┘  │
                                   ┌──────────────────────────────────────┘
                                   ▼  hàng đợi selected_commits (status=pending)
┌─────────────────────────────────────────────────────────────────────────────┐
│ ④ TẦNG ĐẮT — ANALYZE (Model A)   SONG SONG CẤP COMMIT, TUẦN TỰ 3 TOOL/commit  │
│                                                                               │
│   [1 lần/run] SonarQube SERVER singleton: start + đổi pw/token QUA API ⏱54s   │
│                                                                               │
│   ThreadPoolExecutor(EXPENSIVE_WORKERS=2) ── clone-pool · pull+CLAIM nguyên tử │
│    ├ w1: claim commit → ┌─ checkout                                           │
│    │                    ├─ BUILD 1 LẦN (mvn -pl <mod> -am, dùng chung) ⏱14–33s│
│    │                    │     fail → build_failed (ghi), bỏ commit            │
│    │                    ├─ CodeQL    (tự build-trace 29s + analyze) ⏱~20'     │
│    │                    ├─ FindSecBugs (đọc classes build) ───────── ⏱7s      │
│    │                    └─ SonarQube  (scanner+API, classes+/m2 jar) ⏱22s     │
│    │                    → consensus(đắt) + enrich → findings(tier=expensive)  │
│    │                    → status=done → claim commit kế                        │
│    └ w2: (song song commit khác, cùng khuôn)                                  │
│                                                                               │
│   ⏱ 1 commit ≈ build 14s + CodeQL ~20' + FindSecBugs 7s + Sonar 22s ≈ ~21'   │
│      (CodeQL chi phối 95%; minimal-suite hạ còn ~6.7'). 17 buggy ≈ 2–6 giờ.   │
│   [cuối run] stop SonarQube server.                                           │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                   ▼
OUTPUT: SQLite dataset.sqlite
   • findings  tier=cheap|expensive  (POSITIVE: cụm CWE + s_line + finding_in_diff + url)
   • scanned_files (NEGATIVE: file/commit 0-CWE/CVE = cheap-clean)
   • selected_commits (hàng đợi + status), expensive_runs (telemetry build/analyze), run_meta
```

---

## Bảng chi phí time (đã đo) theo bước

| Bước | Song song? | Chi phí ĐO | Ghi chú |
|---|---|---|---|
| ① enumerate + lọc | tuần tự | vài giây / 50 commit | git thuần |
| ② scan tầng rẻ | **2 trục: 4 commit × 5 tool** | **227s / 29 commit** (Model B) | A=264s; ~3.8' tổng |
| ③ select | tuần tự | <1s | đọc DB |
| ④ build (dùng chung) | — | **14–33s** | `-pl <mod> -am`, cache .m2; cold lần đầu 42s |
| ④ CodeQL | (tuần tự trong commit) | DB create **29s** + analyze **~1223s** | code-scanning ~20'; minimal 376s |
| ④ FindSecBugs | (tuần tự) | **7s** | bytecode, dùng classes build |
| ④ SonarQube | (tuần tự) | scan **22s** + server **54s/run** | cần `sonar.java.libraries=/m2` |
| ④/commit (3 tool) | — | **≈ 21'** | CodeQL chiếm ~95% |

---

## Song song vs Tuần tự — chốt ở đâu & vì sao

| Vị trí | Chế độ | Lý do |
|---|---|---|
| **Giữa các commit (cả 2 tầng)** | **SONG SONG** (clone-pool) | mở khoá throughput; clone pid-riêng, không clobber |
| **Tool trong 1 commit — TẦNG RẺ** | **SONG SONG** (Model B) | tool nhẹ → nhanh ~14%; đo thực |
| **Tool trong 1 commit — TẦNG ĐẮT** | **TUẦN TỰ** (Model A) | tool nặng RAM/CPU; build c2 đè analyze c1 (bù pha); tránh thrash |
| **Build/commit** | tuần tự (1 lần, dùng chung) | CodeQL tự build-trace riêng; FindSecBugs+Sonar xài lại classes |
| **SonarQube server** | singleton (1 lần/run) | server JVM ~2GB; bật/tắt mỗi commit phí |

**Số worker:** rẻ `SCAN_WORKERS=4` (tool nhẹ, ~20 container đỉnh OK); đắt `EXPENSIVE_WORKERS=2`
(mỗi commit ăn build+JVM+CodeQL vài GB → giới hạn RAM 32GB).

---

## Nút thắt & núm chỉnh
- **Nút thắt = CodeQL analyze** (~20'/commit, 95% thời gian tầng đắt). Núm: `CODEQL_SUITE`
  (minimal 10-query → 6.7') / `CODEQL_THREADS` / `CODEQL_RAM_MB`.
- **Núm chi phí phễu** = số commit buggy lên tầng đắt (`select`: chỉ buggy; clean miễn đắt).
- Tăng tốc thêm (chưa làm): container ấm, cache theo blob-sha, scale ngang nhiều VM.
```
