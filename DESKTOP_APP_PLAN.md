# DESKTOP_APP_PLAN — Bản `.exe` cho người dùng cuối (plan + thiết kế UI/UX)

> Trạng thái: **BẢN NHÁP để user đánh giá** (2026-10-04). Chưa code. Sau khi chốt → chuyển quyết định sang `TOOL_IDEA_CONTEXT.md`, tiến độ sang `SESSION_CONTEXT.md`.
> Nguồn ý tưởng gốc (user): 1 file `.exe` → check cấu hình máy → báo thiếu gì / mở GUI → nhập link GitHub → tự liệt kê branch → chọn nhánh, khoảng thời gian commit, tool rẻ/đắt, số luồng, nơi lưu kết quả.

---

## 0. Review ý tưởng gốc — đúng gì, thiếu gì

| Ý tưởng gốc | Đánh giá | Bổ sung |
|---|---|---|
| 1 file `.exe` | ✅ Đúng hướng: người dùng không cần Python. **Nhưng Docker Desktop không thể nhúng vào exe** — vẫn là điều kiện ngoài. | Exe = *launcher + GUI + orchestrator đóng gói*. Preflight phải hướng dẫn cài Docker Desktop (link, yêu cầu WSL2, khởi động lại). |
| Check cấu hình máy, báo thiếu | ✅ Rất cần — phiên hôm nay cho thấy lỗi "ngầm" đều từ môi trường (port 9000 bị chiếm, path backslash, file read-only). | Preflight phải **sửa được** phần nó sửa được (tự bật Docker, tự chọn port trống, tự pull image) chứ không chỉ báo. Xem §2. |
| Nhập link → tự liệt kê branch | ✅ | Dùng `git ls-remote --heads --tags` (không cần clone). Hỗ trợ **repo private** (PAT, lưu Windows Credential Manager). Cho dán cả link commit/PR → tự tách repo. |
| Chọn khoảng thời gian commit | ✅ nhưng **chưa đủ** | Thêm 3 cách chọn khác: *N commit gần nhất* (`--max`), *khoảng SHA*, *toàn lịch sử* (`--max 0`). Phải **preview số commit + ước tính thời gian/đĩa** trước khi bấm Run (tránh user chọn 8000 commit rồi đợi 7 ngày như skywalking). |
| Chọn tool rẻ / đắt | ✅ | Mỗi tool kèm **badge chi phí đo thật** (giây/commit, RAM, dung lượng image) + trạng thái image (đã có / cần pull X MB). CodeQL mặc định **TẮT** + cảnh báo ~7–20 phút/commit. |
| Số luồng | ✅ | Tách **2 núm**: luồng tầng rẻ (`ORCH_SCAN_WORKERS`) và tầng đắt (`ORCH_EXPENSIVE_WORKERS`). GUI **đề xuất** từ CPU/RAM thật (tầng đắt: mỗi worker ≈ 1 build Maven ≈ 2–3 GB RAM + Sonar server 2 GB). |
| Nơi lưu kết quả | ✅ | Tự đặt tên theo repo + nhánh + ngày (`dataset_<repo>_<branch>_<yyyymmdd>.sqlite`) để **không bao giờ trộn 2 repo 1 DB** (lỗi đã ghi trong CLAUDE.md). Tách **thư mục làm việc** (clone, cache Maven — nên để ổ nhanh) và **thư mục kết quả**. |

### Thiếu hẳn trong ý tưởng gốc (đề xuất thêm)

1. **Resume** — phát hiện DB cũ cùng repo/nhánh → "Tiếp tục run dở?" (pipeline hiện đã có `scan_done`, atomic claim; chỉ cần UI). Run dài **phải sống độc lập cửa sổ GUI** (tiến trình nền, GUI đóng mở lại vẫn gắn vào được).
2. **Dashboard tiến độ sống** — 3 thanh: ① scan rẻ ② select ③ tầng đắt (done / build_failed / đang build), bộ đếm finding theo tool, log tail, ETA từ nhịp thật. Nút **Dừng an toàn** (SIGTERM → dọn container mồ côi → reset commit `building` → có thể resume).
3. **Màn hình kết quả** (hiện tại user phải mở sqlite tay) — bảng finding lọc theo nhãn gold/silver/candidate, CWE, tool, commit; xem diff + dòng bị flag; κ Fleiss; xuất CSV/JSONL/Parquet; nút "Mở thư mục".
4. **Chế độ kiểm tay GOLD** — đánh TP/FP từng cụm gold, lưu `gold_review.json`. Đây là đầu việc luận văn còn nợ ("kiểm tay 26 gold + đo precision"); đưa vào UI là đáng giá nhất về mặt nghiên cứu.
5. **Ước tính trước khi chạy (Dry-run / Estimate)** — số commit sau lọc thô, ước tính phút, GB đĩa, GB image cần pull; **không cho Run** nếu đĩa trống < ước tính × 1.5.
6. **Hồ sơ cấu hình (Profile)** — lưu/tải JSON; nút **"Sao chép lệnh CLI tương đương"** → mọi run GUI đều tái lập được bằng dòng lệnh (yêu cầu reproducibility của luận văn §12.3).
7. **Hàng đợi nhiều repo (Batch)** — danh sách repo chạy tuần tự, mỗi repo 1 DB.
8. **Quản lý dung lượng** — xem `work/`, `.m2cache`, image Docker, export chiếm bao nhiêu; dọn **có xem trước** (sửa luôn bẫy `clean --export` xoá nhầm thư mục mặc định).
9. **Chạy ở đâu?** — Local (Docker Desktop) **hoặc VM từ xa qua SSH** (GUI chỉ là frontend; orchestrator chạy trên VM như hiện nay). Tránh mâu thuẫn với quyết định cũ "máy Windows chỉ điều khiển VM" (TOOL_IDEA §9): GUI phục vụ *cả hai*, pha 1 làm local trước.
10. **Gói chẩn đoán** — nút "Xuất log chẩn đoán" (zip: log, run_meta, docker info, cấu hình) để báo lỗi.
11. **Thông báo** — Windows toast khi run xong / lỗi; âm báo tắt được.
12. **Song ngữ VI/EN** — luận văn tiếng Việt, paper tiếng Anh; chuỗi UI tách file.

---

## 1. Kiến trúc đề xuất

```
┌──────────────────────────── secjit-scan.exe (PyInstaller onefile) ─────────────────────────┐
│  Launcher ──► Preflight ──► GUI (pywebview: cửa sổ native nhúng web UI)                     │
│                                 │  HTTP/WebSocket localhost (cổng ngẫu nhiên)              │
│                                 ▼                                                           │
│                        Backend FastAPI/stdlib http.server (cùng tiến trình)                 │
│                                 │  gọi trực tiếp                                            │
│                                 ▼                                                           │
│                 src/orchestrator (code hiện có, stdlib-only, KHÔNG sửa logic)               │
│                                 │  subprocess                                               │
│                                 ▼                                                           │
│                    Docker Desktop (ngoài exe)  ──  5 tool rẻ · maven · FSB · Sonar · CodeQL │
└────────────────────────────────────────────────────────────────────────────────────────────┘
          Pha sau: Backend chạy trên VM (SSH tunnel) — GUI y nguyên, chỉ đổi địa chỉ.
```

**Vì sao web-UI-trong-cửa-sổ-native thay vì Qt/Tkinter thuần:**

| Tiêu chí | pywebview + web UI (đề xuất) | PySide6/Qt | Tkinter |
|---|---|---|---|
| Đẹp, bảng/biểu đồ, log sống | ✅ HTML/CSS, dễ | ✅ nhưng tốn công | ❌ thô |
| Tái dùng cho chế độ VM từ xa | ✅ cùng UI, đổi backend | ❌ phải viết lại | ❌ |
| Kích cỡ exe | ~25–40 MB | ~80–120 MB | ~15 MB |
| Rủi ro | WebView2 phải có (Win10/11 có sẵn) | License LGPL ok | — |
| Người có thể làm UI giúp | Dev web nào cũng được | Hiếm | — |

**Đóng gói:** PyInstaller `--onefile --noconsole`, nhúng `src/orchestrator` + `docker/` (Dockerfile FSB/CodeQL để build image tại chỗ) + web UI tĩnh. Ký code (self-signed cho nội bộ) để tránh SmartScreen chặn. Auto-update: so phiên bản với GitHub Release.

**Nguyên tắc không thương lượng:** GUI **chỉ gọi** orchestrator qua API nội bộ; **không fork logic** label/consensus vào GUI. Mọi thứ GUI làm được phải có lệnh CLI tương đương (reproducibility).

---

## 2. Preflight — kiểm tra & tự sửa

Chạy ngay khi mở exe, hiển thị checklist 3 trạng thái: ✅ đạt · 🔧 tự sửa được (nút Sửa) · ❌ user phải làm (hướng dẫn + link).

| # | Kiểm tra | Mức | Tự sửa? | Ghi chú (bài học phiên 2026-10-04) |
|---|---|---|---|---|
| 1 | Windows 10 21H2+/11 64-bit, WSL2 bật | ❌ | Không | Docker Desktop cần WSL2. |
| 2 | Docker Desktop đã cài | ❌ | Không | Link tải; nhắc license Docker Desktop với công ty >250 người. |
| 3 | Docker daemon đang chạy | 🔧 | **Có**: `Start-Process "Docker Desktop.exe"` rồi poll `docker info` ≤ 90s | Đã làm được hôm nay. |
| 4 | Port host trống cho SonarQube | 🔧 | **Có**: dò 9000→9100→… chọn trống, set `ORCH_SONAR_PORT` | Hôm nay 9000 bị `giapha-minio` chiếm → treo 6 phút. |
| 5 | RAM vật lý | ❌/⚠️ | Không, nhưng **tự hạ** `CODEQL_RAM_MB` & số worker | ≥ 8 GB cho rẻ+FSB+Sonar; ≥ 16 GB nếu CodeQL. Mặc định CodeQL đòi 20 GB → phải tự điều chỉnh. |
| 6 | Đĩa trống tại WORK_DIR | ⚠️ | Không | Ước tính: image 3–5 GB + clone + `.m2cache` (train-ticket ~1 GB) + export (train-ticket 274 commit = 516 MB). |
| 7 | Git for Windows | 🔧 | Có: `winget install Git.Git` | Pipeline gọi `git` host. |
| 8 | `core.longpaths=true` | 🔧 | Có | Repo Java path sâu > 260 ký tự → checkout fail. |
| 9 | Image tool đã có | 🔧 | Có: pull/build kèm % tiến độ, hiện dung lượng | 5 rẻ ≈ 2.5 GB, maven 0.5 GB, FSB 0.7 GB (build local), Sonar 1 GB, CodeQL ~3 GB. |
| 10 | Mạng tới github.com, registry Docker | ❌ | Không | Proxy công ty → cho nhập proxy. |
| 11 | WebView2 runtime | 🔧 | Có: cài Evergreen bootstrapper | Chỉ khi dùng pywebview. |
| 12 | Antivirus quét thư mục work | ⚠️ | Không | Gợi ý loại trừ thư mục work (build Maven chậm 3–5× nếu Defender quét). |
| 13 | Vị trí WORK_DIR | ⚠️ | Gợi ý | Bind mount Windows→WSL2 **chậm**: build cold 881 s hôm nay. Khuyến nghị dùng **Docker volume** cho `.m2cache` (tăng tốc lớn) — cần sửa `build.py` nhỏ. |

Kết quả preflight lưu `preflight.json` kèm vào gói chẩn đoán. Nếu tất cả ✅/⚠️ → tự chuyển sang Home.

---

## 3. Luồng UX tổng thể

```
 [Splash + Preflight] ──đủ──► [Home]
         │ thiếu                 ├─► Scan mới (Wizard 5 bước) ─► [Review & Estimate] ─► [Run Dashboard] ─► [Results]
         ▼                       ├─► Run gần đây (resume / mở kết quả)
 [Checklist thiếu gì]            ├─► Hàng đợi batch
   (Sửa tự động / Hướng dẫn)     └─► Cài đặt (Docker, dung lượng, profile, ngôn ngữ)
```

Nguyên tắc: **wizard tuyến tính** cho người mới (mỗi bước 1 câu hỏi lớn), nhưng có **"Chế độ nâng cao"** gom tất cả vào 1 trang cho người quen. Mọi lựa chọn hiện **hậu quả** ngay bên cạnh (số commit, phút, GB).

---

## 4. Wireframe từng màn hình

### 4.1 Preflight
```
┌──────────────────────────────────────────────────────────────────────┐
│  SecJIT Scan  ·  Kiểm tra môi trường                       [VI ▾]    │
├──────────────────────────────────────────────────────────────────────┤
│  ✅ Windows 11 64-bit · WSL2 bật                                      │
│  ✅ Docker Desktop 4.x đã cài                                          │
│  🔧 Docker daemon chưa chạy                       [ Bật Docker ]      │
│  🔧 Port 9000 đang bị dùng (giapha-minio)         [ Dùng 9100 ]       │
│  ⚠️ RAM 16 GB — đủ cho FindSecBugs+Sonar, CodeQL sẽ chạy chậm         │
│  ✅ Đĩa D: trống 212 GB                                                │
│  🔧 Thiếu image: semgrep (1.5 GB), sonarqube (1.0 GB)  [ Tải 2.5 GB ] │
│  ❌ Git chưa cài → winget install Git.Git            [ Hướng dẫn ]    │
├──────────────────────────────────────────────────────────────────────┤
│  [ Sửa tất cả tự động ]                 [ Kiểm tra lại ]  [ Tiếp tục ]│
└──────────────────────────────────────────────────────────────────────┘
```
"Tiếp tục" mờ khi còn ❌. ⚠️ không chặn.

### 4.2 Home
```
┌──────────────────────────────────────────────────────────────────────┐
│  SecJIT Scan                                    Docker ● running      │
├───────────────────────────┬──────────────────────────────────────────┤
│  [ + Scan mới ]           │  Run gần đây                              │
│  [ ▶ Hàng đợi batch (2) ] │  ● train-ticket/master  274 cm  xong 2.5h │
│  [ ⚙ Cài đặt ]            │     gold 208 · silver 11974 · κ −0.36     │
│                           │     [Mở kết quả] [Chạy lại] [Xuất]        │
│  Dung lượng               │  ◐ skywalking/master   5904 cm  dở 28%    │
│  work 3.1 GB  images 6 GB │     [Tiếp tục ▶] [Chi tiết]               │
│  [Dọn dẹp…]               │  ○ giraph/trunk        1128 cm  xong 14h  │
└───────────────────────────┴──────────────────────────────────────────┘
```

### 4.3 Wizard — Bước 1/5: Repo & nhánh
```
┌──────────────────────────────────────────────────────────────────────┐
│  Bước 1/5 · Repo                     ○──○──○──○──○                    │
├──────────────────────────────────────────────────────────────────────┤
│  Link GitHub                                                          │
│  [ https://github.com/FudanSELab/train-ticket          ] [Kiểm tra]  │
│  ✅ Public · Java/Maven · 323 commit · mặc định: master               │
│                                                                       │
│  Nhánh   [ master ▾ ]   (12 nhánh, 8 tag)      ☐ Repo private (PAT)  │
│          ⚠ giraph dùng "trunk", không phải main — chọn đúng nhánh.    │
│                                                                       │
│  Phát hiện: Spring Boot 2.3 · JDK 8 (auto-detect từ pom) · 43 module │
├──────────────────────────────────────────────────────────────────────┤
│                                               [ Quay lại ] [ Tiếp ▶ ]│
└──────────────────────────────────────────────────────────────────────┘
```
Kiểm tra = `git ls-remote` + đọc `pom.xml` HEAD (không clone). Nếu repo không có pom → cảnh báo "tầng đắt sẽ không build được".

### 4.4 Bước 2/5: Phạm vi commit
```
┌──────────────────────────────────────────────────────────────────────┐
│  Bước 2/5 · Phạm vi commit                                            │
├──────────────────────────────────────────────────────────────────────┤
│  (●) Khoảng thời gian   từ [2019-01-01] đến [2020-12-31]             │
│  ( ) N commit gần nhất  [ 50 ]                                        │
│  ( ) Khoảng SHA         [ abc123 ] → [ def456 ]                        │
│  ( ) Toàn lịch sử (323 commit)                                        │
│                                                                       │
│  Mật độ commit theo tháng   ▁▂▃▅▇▆▃▂▁▁▂▃   ◄ kéo chọn trên biểu đồ ►  │
│                                                                       │
│  ☑ Bỏ merge commit    ☐ Bỏ commit khổng lồ (>100 file / >1000 dòng)  │
│  ☑ Lấy cả commit "clean" cho tầng đắt (verified-clean = GOLD negative)│
│                                                                       │
│  → 187 commit sau lọc thô · ~61 buggy ước tính · ~2 h 10 min tầng rẻ  │
├──────────────────────────────────────────────────────────────────────┤
│                                               [ Quay lại ] [ Tiếp ▶ ]│
└──────────────────────────────────────────────────────────────────────┘
```
Biểu đồ mật độ lấy từ `git log --date=short` sau khi clone (clone chạy nền từ bước 1).

### 4.5 Bước 3/5: Tool & tài nguyên
```
┌──────────────────────────────────────────────────────────────────────┐
│  Bước 3/5 · Tool                                                      │
├──────────────────────────────────────────────────────────────────────┤
│  TẦNG RẺ (trên diff, không build)         giây/commit  image         │
│  ☑ gitleaks     secret                       ~2 s      ✅ 77 MB       │
│  ☑ trufflehog   secret                       ~3 s      ✅ 114 MB      │
│  ☑ semgrep      SAST đa ngôn ngữ             ~15 s     ✅ 1.5 GB      │
│  ☑ bearer       SAST + privacy               ~10 s     ✅ 456 MB      │
│  ☑ horusec      SAST tổng hợp                ~20 s     ✅ 343 MB      │
│                                                                       │
│  TẦNG ĐẮT (cần build Maven ~0.5–15 min/commit)                        │
│  ☑ FindSecBugs  bytecode                     ~7 s      ✅ 731 MB      │
│  ☑ SonarQube    server cục bộ, port 9100     ~30 s     ✅ 1.0 GB      │
│  ☐ CodeQL       dataflow sâu ⚠ 7–20 min/commit, RAM ≥16 GB  ⬇ 3 GB   │
│                                                                       │
│  Luồng tầng rẻ  [====●====] 4   (đề xuất 4 — CPU 8 nhân)              │
│  Luồng tầng đắt [==●======] 2   (đề xuất 2 — RAM 16 GB, mỗi build ~3GB)│
│  ☑ Giữ cache Maven giữa các run (Docker volume, nhanh hơn 3–5×)       │
├──────────────────────────────────────────────────────────────────────┤
│  [ Nâng cao ▸ ] LINE_WINDOW 3 · VOTE 2 · GOLD_MIN_EXP 2 · NOISE CWE-117│
│                                               [ Quay lại ] [ Tiếp ▶ ]│
└──────────────────────────────────────────────────────────────────────┘
```
Bật CodeQL → hộp xác nhận nêu rõ ước tính thêm X giờ. Nâng cao mặc định gập; đổi tham số consensus hiện cảnh báo "ảnh hưởng tái lập — ghi vào run_meta".

### 4.6 Bước 4/5: Nơi lưu
```
┌──────────────────────────────────────────────────────────────────────┐
│  Bước 4/5 · Lưu kết quả                                               │
├──────────────────────────────────────────────────────────────────────┤
│  Thư mục kết quả  [ D:\secjit\results\                 ] [Chọn…]     │
│    └ dataset_train-ticket_master_20261004.sqlite  (tự đặt, sửa được) │
│    └ export_train-ticket_master_20261004\  (raw + jsonl)              │
│  Thư mục làm việc [ D:\secjit\work\                    ] [Chọn…]     │
│    ⚠ nên để ổ SSD; sẽ chiếm ~2–4 GB (clone + cache)                   │
│                                                                       │
│  Định dạng xuất   ☑ dataset.jsonl + commits.jsonl  ☑ CSV  ☐ Parquet   │
│  ☑ Giữ output thô từng tool (SARIF/XML/JSON) để audit (+~60%)         │
│  ☐ Tự xoá clone/pool sau khi xong (giữ cache Maven)                   │
├──────────────────────────────────────────────────────────────────────┤
│                                               [ Quay lại ] [ Tiếp ▶ ]│
└──────────────────────────────────────────────────────────────────────┘
```

### 4.7 Bước 5/5: Xem lại & ước tính
```
┌──────────────────────────────────────────────────────────────────────┐
│  Bước 5/5 · Xem lại                                                   │
├──────────────────────────────────────────────────────────────────────┤
│  train-ticket · master · 2019-01-01→2020-12-31 · 187 commit           │
│  Tool: 5 rẻ + FindSecBugs + Sonar · luồng 4/2 · CodeQL tắt            │
│                                                                       │
│  Ước tính    tầng rẻ ~2 h 10 m  ·  tầng đắt ~61 × 2.5 m ≈ 2 h 30 m   │
│              đĩa +1.8 GB  ·  tổng ≈ 4 h 40 m (chạy nền được)          │
│                                                                       │
│  Lệnh CLI tương đương                                   [ Sao chép ] │
│  ┌──────────────────────────────────────────────────────────────────┐│
│  │ ORCH_SQLITE=... ORCH_SONAR_PORT=9100 PYTHONPATH=src python -m    ││
│  │ orchestrator.cli pipeline <url> --branch master --since ... \    ││
│  │ --codeql 0 --include-clean --workers 2 --out ...                 ││
│  └──────────────────────────────────────────────────────────────────┘│
│  [ Lưu profile… ]                                                     │
├──────────────────────────────────────────────────────────────────────┤
│                        [ Quay lại ]  [ Chạy thử 3 commit ]  [ ▶ Chạy ]│
└──────────────────────────────────────────────────────────────────────┘
```
"Chạy thử 3 commit" = smoke test nhanh để phát hiện lỗi môi trường trước khi cam kết 5 giờ (đúng cách tôi vừa kiểm tra hôm nay).

### 4.8 Run Dashboard
```
┌──────────────────────────────────────────────────────────────────────┐
│  train-ticket · master          Đang chạy 01:12:08 · ETA ~3 h 20 m    │
├──────────────────────────────────────────────────────────────────────┤
│  ① Tầng rẻ   ████████████████████░░░░  152/187   4 luồng   ~12 s/cm   │
│  ② Chọn      61 buggy · 91 clean → hàng đợi tầng đắt                  │
│  ③ Tầng đắt  ██████░░░░░░░░░░░░░░░░░░   18/152   done 15 · fail 3     │
│              w0: 9bdd9a28 building (mvn 02:14)   w1: 4a9599f4 sonar   │
│                                                                       │
│  Finding theo tool   bearer 812 · semgrep 290 · horusec 37 · FSB 1 204│
│  Nhãn tạm            gold 12 · silver 1 980 · candidate 2 110          │
│                                                                       │
│  Log  [tất cả ▾] [lỗi]                                     [Mở file] │
│  ┌──────────────────────────────────────────────────────────────────┐│
│  │ [w0] 313886e9 -> done (fsb 238, sonar 68)                        ││
│  │ [w1] 7c1d02aa build_failed: dependency ...-SNAPSHOT not found    ││
│  └──────────────────────────────────────────────────────────────────┘│
├──────────────────────────────────────────────────────────────────────┤
│  ☑ Thông báo khi xong     [ ⏸ Dừng an toàn ]   [ Thu nhỏ xuống tray ] │
└──────────────────────────────────────────────────────────────────────┘
```
Dữ liệu lấy từ SQLite (`scan_done`, `selected_commits`, `expensive_runs`) — **không cần sửa orchestrator**; chỉ cần poll 2 s.

### 4.9 Results
```
┌──────────────────────────────────────────────────────────────────────┐
│  Kết quả · train-ticket/master      κ Fleiss −0.36 (cãi nhau — bình thường)│
├──────────────────────────────────────────────────────────────────────┤
│  Tổng quan │ Finding │ Commit │ Kiểm tay GOLD │ Xuất                  │
├──────────────────────────────────────────────────────────────────────┤
│  Lọc: nhãn [gold ▾] CWE [tất cả ▾] tool [≥2 ▾] tier [mixed ▾] 🔍      │
│  ┌──────────┬────────────────────────────────┬──────┬────────┬───────┐│
│  │ commit   │ file:line                      │ CWE  │ tools  │ nhãn  ││
│  ├──────────┼────────────────────────────────┼──────┼────────┼───────┤│
│  │ 313886e9 │ adminorder/.../SecurityConfig:26│ 352  │ FSB+Son│ GOLD  ││
│  │ 350f6200 │ .../SecurityConfig.java:65      │ 352  │ 3 tool │ GOLD  ││
│  └──────────┴────────────────────────────────┴──────┴────────┴───────┘│
│  ▸ Chi tiết: diff commit, đoạn code, message từng tool, in_diff=1     │
│                                                                       │
│  Kiểm tay GOLD:  [✓ TP] [✗ FP] [? Không rõ]  ghi chú [________]       │
│  Đã kiểm 12/208 · precision tạm 0.83                                  │
└──────────────────────────────────────────────────────────────────────┘
```

### 4.10 Cài đặt → Dung lượng & dọn dẹp
```
│  work\train-ticket  1.2 GB   work\.m2cache  0.9 GB   pool_* (rác) 0.3 GB │
│  Image Docker 6.1 GB (5 rẻ · maven · FSB · Sonar)                        │
│  [ Dọn clone+pool ]  [ Dọn cache Maven ]  [ Xoá image… ]                 │
│  Mỗi nút hiện danh sách SẼ XOÁ + dung lượng trước khi xác nhận.          │
```

---

## 5. Thay đổi cần có ở orchestrator (nhỏ, không đổi logic nhãn)

| Việc | Lý do | Cỡ |
|---|---|---|
| `--since/--until` (lọc theo ngày) và `--from-sha/--to-sha` cho `enumerate/scan/pipeline` | UI bước 2 | nhỏ |
| `--tools gitleaks,semgrep,...` chọn tool rẻ; `--expensive-tools fsb,sonar` | UI bước 3 (hiện chỉ có `--codeql 0/1`) | nhỏ |
| `estimate` subcommand: số commit sau lọc + ước tính phút/GB từ bảng tốc độ đo được | UI bước 2/5 | vừa |
| Ghi tiến độ có cấu trúc (JSON lines) song song log text | Dashboard đọc ổn định | nhỏ |
| Cache Maven dùng **Docker named volume** thay bind mount (tuỳ chọn `ORCH_M2_VOLUME`) | Bind mount Windows chậm 3–5× | nhỏ |
| `clean` nhận `--out` rõ ràng, xoá có xác nhận | Bẫy xoá nhầm `data/export` | nhỏ |
| Đã làm hôm nay: `ORCH_SONAR_PORT`, `run_as_user()`, posix path cho container, rmtree read-only | Chạy được trên Windows | ✅ |

---

## 6. Lộ trình

| Pha | Nội dung | Tiêu chí xong |
|---|---|---|
| **P0 — Chốt thiết kế** | User duyệt tài liệu này; chọn stack (§1) | Quyết định ghi vào TOOL_IDEA_CONTEXT |
| **P1 — MVP (2–3 tuần)** | exe + Preflight (§2) + Wizard 5 bước + Run Dashboard tối thiểu (3 thanh + log) + mở thư mục kết quả | Người không biết Python chạy được train-ticket `--max 20` từ exe, 0 lệnh gõ tay |
| **P2 — Kết quả & resume** | Màn Results (lọc/diff), Resume, Dừng an toàn, Profile + lệnh CLI tương đương, Dọn dẹp | Resume run dở skywalking từ GUI |
| **P3 — Nghiên cứu** | Kiểm tay GOLD, κ theo nhóm, biểu đồ, xuất CSV/Parquet, Batch | Có `gold_review.json` cho ≥1 repo |
| **P4 — Từ xa** | Backend trên VM qua SSH; GUI chuyển đổi local/VM | Chạy giraph trên VM từ GUI Windows |

---

## 7. Rủi ro & cách giảm

- **Docker Desktop là điểm gãy lớn nhất** (license, WSL2, antivirus, cập nhật tự động). Giảm: preflight kỹ (§2), tài liệu cài 1 trang, fallback "chỉ tầng rẻ" nếu RAM thấp.
- **Hiệu năng bind mount Windows** (build 881 s vs ~13 s trên VM cache ấm). Giảm: Docker volume cho `.m2cache`, cảnh báo Defender, khuyến nghị SSD; hiển thị ước tính trung thực.
- **Lỗi đường dẫn/encoding Windows** (đã gặp 3 lỗi hôm nay). Giảm: test tự động trên Windows runner (GitHub Actions `windows-latest` + Docker không có → ít nhất test unit path/posix), `PYTHONUTF8=1` bật sẵn trong exe.
- **Antivirus/SmartScreen chặn exe lạ.** Giảm: ký code; phát hành qua GitHub Release có checksum.
- **User chọn phạm vi quá lớn.** Giảm: ước tính + chặn mềm + "Chạy thử 3 commit".
- **Phạm vi luận văn phình.** Giảm: P1 chỉ là lớp vỏ; không đổi phương pháp luận; mọi run GUI tái lập được bằng CLI.

---

## 8. Câu hỏi cần user chốt

1. Stack GUI: **pywebview + web UI** (đề xuất) hay PySide6?
2. Đối tượng người dùng chính: *chính bạn + hội đồng demo* hay *người dùng ngoài* (ảnh hưởng mức độ "chống ngu" của preflight)?
3. Có cần chế độ VM từ xa trong MVP không, hay để P4?
4. Màn "Kiểm tay GOLD" có ưu tiên lên P1 không (giá trị luận văn cao, nhưng tốn UI)?
5. Tên sản phẩm/exe: `secjit-scan.exe`? (đang dùng tạm)
