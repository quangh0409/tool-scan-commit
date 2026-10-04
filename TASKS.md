# TASKS — Kế hoạch 1 NGÀY (v3, sau ultrareview): desktop app `secjit-scan.exe` đủ 10 màn

> Chốt 2026-10-04. **Claude code toàn bộ, user full quyền, máy bật liên tục, hạn 1 ngày, ≤ 5 agent.** Quyết định phương pháp luận: `TOOL_IDEA_CONTEXT.md` §13. Review gốc: `REVIEW.md`. Bản v3 sửa 6 điểm của v2 (xem §9).

---

## 0. Đầu vào đã chốt với user

| Mục | Chốt | Hệ quả |
|---|---|---|
| Phạm vi | Đủ 10 màn + Kiểm tay GOLD | Không cắt màn; cắt tính năng phụ theo §6 nếu trượt |
| Tái lập | train-ticket `--max 30` trên laptop: Run A (CLI `--profile`) ↔ Run B (từ exe, cùng profile) | Cần lệnh `compare` |
| 5 DB cũ | Đã mất, **không sinh lại** | Dữ liệu test = DB scratch 3 commit (đã có) + Run A + Run B |
| Kiểm tay | Có; 2 rater hoặc intra-rater | Hôm nay làm **tính năng**; việc chấm user làm sau. Trên dữ liệu test, mẫu = min(n, số gold có) |
| Máy sạch | Không; test trên laptop | `--preflight --json` để sau này chạy máy khác |
| Agent | ≤ 5 | **5 agent sống suốt ngày** (đợt 2 tiếp tục bằng SendMessage, giữ ngữ cảnh) → thoả cả "5 đồng thời" lẫn "5 tổng" |
| Docker | Chỉ trưởng chạy, tuần tự | Agent không bao giờ gọi Docker |

**Chờ user chốt trước T0:** (1) RAM Docker khi Run A/B: tạm dừng stack `giapha` (nhanh) hay giữ và chạy 1 worker (chậm gấp đôi) — mặc định (b); (2) chấp nhận fallback exe mở trình duyệt nếu pywebview đóng gói lỗi — mặc định có.

---

## 1. Định nghĩa "XONG" cuối ngày

1. **10 màn chạy thật** qua `secjit-scan.exe` (hoặc fallback browser) và `python -m gui --dev`: Preflight → Home → Wizard 1–5 → Dashboard → Results (Tổng quan / Finding / Commit / Kiểm tay / Xuất) → Settings; mỗi màn có trạng thái loading / rỗng / lỗi / partial theo `REVIEW.md` §III.A; **có ảnh chụp từng màn × trạng thái** (Playwright) trong gallery bàn giao.
2. **Nghiệm thu tái lập**: `compare` Run A/B theo `cluster_key`: khớp, hoặc lệch chỉ ở commit có `tool_timeout`/`infra_error` trong manifest. → `RESULTS.md`.
3. **Backend đủ**: 8 lỗi dữ liệu; `run_meta` v2 + `run_manifest.json` + `SHA256SUMS` + `evidence`; `--since/--until/--from-sha/--to-sha`, `--tools/--expensive-tools`, `--profile`, `estimate`, `stats`, `sensitivity`, `compare`, `stop`, `reset-claims`, `clean --dry-run`, `review sample/close`; runner nền tách rời + stop-file + `progress.jsonl`; preflight 13 mục + 5 auto-fix.
4. **Kiểm tay**: mẫu phân tầng có seed, màn chấm mù, đóng phiên → precision + Wilson CI + Cohen κ (2 file rater).
5. **Chất lượng**: `ruff` sạch; pytest unit + contract xanh; CI yml; `README`/`GUIDE`/`METHODOLOGY`/`SESSION_CONTEXT` cập nhật; commit trên `dev`.
6. **Dữ liệu test đủ**: registry có 3 run; `stats`, `sensitivity`, `review sample` chạy được trên DB Run A; mọi màn hiện dữ liệu thật.

**Không trong ngày:** chấm tay thật; sinh lại 5 dataset; máy sạch; VM qua SSH; ký code; CodeQL image.

---

## 2. Lịch 1 ngày (v3 — đường tới hạn là Docker + tích hợp, không phải agent)

```
T0 ─ T+1    TRƯỞNG · bật Docker, kiểm pywebview/PyInstaller/Playwright, viết CONTRACTS.md + 3 module dùng chung
              (progress.py, cluster_key, profile schema) + fixture mock + tests/conftest + 5 worktree
T+1 ─ T+2,5 ĐỢT 1 · 5 agent song song (mỗi agent ~45–90 phút)
T+2,5 ─ T+4 TRƯỞNG · merge 5 nhánh, ruff/compile/pytest, smoke --max 5 scratch (Docker ~40')
T+4         TRƯỞNG · phóng RUN A (CLI --profile --max 30, cache lạnh, ~3–4 h nền, worker theo §0)
T+4 ─ T+6   ĐỢT 2 · cùng 5 agent (SendMessage) · nối backend thật (đọc DB Run A đang chạy, mode=ro)
T+6 ─ T+8   TRƯỞNG · merge, build exe (fallback browser nếu lỗi), chụp ảnh 10 màn, QA chéo vòng 1 → sửa
T+8 ─ T+11  RUN B từ exe (profile A, cache ấm, ~2–3 h) · song song: QA chéo vòng 2, docs, CI
T+11 ─ T+13 TRƯỞNG · compare A/B, stats/sensitivity trên DB A, review sample, RESULTS.md, gallery ảnh, commit cuối
T+13 ─ T+24 DỰ PHÒNG 11 h (Docker sập, pywebview, lỗi tích hợp) · kịch bản demo 10 phút
```

**Điểm kiểm tra cứng:** T+4 (đợt 1 merge + smoke xanh) · T+8 (10 màn chạy, ảnh chụp đủ) · T+13 (RESULTS). Trượt → cắt theo §6.

---

## 3. T0 · Hợp đồng giao diện `CONTRACTS.md` (trưởng viết; agent tuân theo, không tự đổi)

- **`profile.json`** `{schema:1, repo, branch, scope:{mode: time|count|sha|all, since, until, max, from_sha, to_sha}, include_clean, cheap_tools[], expensive_tools[], codeql, workers:{scan, expensive}, paths:{db, export, work}, sonar_port, experiment:{enabled, reason}|null, params_v1:{line_window:3, gold_min_expensive:2, gold_allow_1exp_1cheap:1, silver_min_cheap:2, noise_cwe:["CWE-117"]}}`. Đường dẫn có thể chứa `'`, khoảng trắng, unicode → test.
- **`progress.jsonl`** `{ts, run_id, phase: scan|select|analyze|relabel|kappa|export, event: start|item|done|error, done, total, worker, sha, status, msg}`. Module `src/orchestrator/progress.py` (trưởng viết T0): `emit(**kw)` ghi append, thread-safe, no-op nếu không có `ORCH_PROGRESS_FILE`.
- **Phân loại trạng thái thống nhất** (manifest, GUI, compare, `expensive_runs.status`): `ok | skipped (0 module Java) | build_failed (lỗi dữ liệu) | infra_error (Docker/đĩa/mạng — KHÔNG phải dữ liệu) | tool_timeout | tool_error`. `negative_level = verified-clean` chỉ khi `n_expensive_ok ≥ 2`.
- **Dừng**: `stop-file` `<work>/<run_id>.stop` — orchestrator kiểm **giữa mỗi commit** ở tầng rẻ và tầng đắt (cooperative); `stop --force` = `taskkill /T /PID` (Windows) / SIGTERM (Linux) + dọn container theo label + `reset-claims --run`. **Không dùng CTRL_BREAK** (tiến trình detached không có console).
- **`cluster_key`** = sha256(`repo|commit|file_path|cwe_group|s_line//LINE_WINDOW`) — module `src/orchestrator/keys.py` (trưởng viết T0).
- **`run_meta` v2**: `run_meta(id, run_id, tier: scan|analyze, started_at, finished_at, repo, branch, scope_json, config_snapshot_json, tools_json[{name,image,version,digest}], orchestrator_git_sha, app_version, experiment)`; bảng `kappa(run_id, scope, group, value, n)`; `PRAGMA user_version=2` + migrate từ 1.
- **`runs.json`** `%LOCALAPPDATA%\secjit\runs.json`: `{runs:[{run_id, repo, branch, db, export, work, profile, started, finished, status: running|stopped|done|failed|interrupted, pid, summary}]}`.
- **Mọi `docker run`** gắn `--label orch.run=<run_id>`; Sonar container/network tên theo `run_id`.
- **API GUI** (`gui/server.py`, localhost, cổng ngẫu nhiên, header `X-Token`): `GET /api/preflight` · `POST /api/preflight/fix` · `POST /api/repo/check` · `POST /api/estimate` · `POST /api/run/start` · `POST /api/run/{id}/stop` · `POST /api/run/{id}/resume` · `GET /api/runs` · `GET /api/run/{id}/progress` (SSE) · `GET /api/results/{id}/overview|findings|commits|export` · `GET /api/results/{id}/finding/{cluster_key}` · `POST /api/review/{id}/sample|verdict|close` · `GET|POST /api/settings/*` · `GET /api/storage` · `POST /api/clean`. Mỗi endpoint có fixture `gui/fixtures/<tên>.json` (số từ run thật, nhãn mock đã sửa theo REVIEW §I.4).
- **Env chuẩn** cho runner/exe: `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`, `ORCH_SONAR_PORT` set **trước** import orchestrator.
- **Vùng file & merge**: mỗi agent 1 worktree `feat/a<n>-…`; `cli.py`/`config.py` chỉ A2 sửa; A1 không import gì của A2 ngoài `progress.py`/`keys.py` (của trưởng); không Docker; commit nhỏ, tiếng Việt; đầu đợt 2 `git merge dev`.
- **Design token** web UI lấy từ wireframe: `scratchpad/wire/project/*.dc.html` (màu, kiểu, component).

---

## 4. ĐỢT 1 (T+1 → T+2,5) — 5 agent, worktree riêng

| Agent | Vùng file | Việc | Nghiệm thu |
|---|---|---|---|
| **A1 data-core** | `storage/sqlite_store.py`, `export_dataset.py`, `tools_expensive/build.py`, `expensive_runner.py`, `tools_expensive/sonar.py`, `repo_pool.py`, `tools/base.py`, `scripts/merge_export.py` | 8 lỗi (D1 `skipped` + `n_expensive_ok` + verified-clean ≥2 ok; D2 `infra_error` + dừng sau 3; D3 Sonar theo `run_id` + lock DB; D4 fetch + `owner__repo` + kiểm origin; D5 export thư mục mới; D6 disk-full; D7 `_rmtree`; D8 WAL); `--label`; `run_meta` v2 + `kappa` + migrate; `export` gộp merge + manifest + SHA256SUMS + `evidence`; `progress.emit` + kiểm stop-file trong analyze | pytest (mock subprocess) negative_level / run_meta / manifest / stop-file |
| **A2 cli-scope** | `cli.py`, `config.py`, `enumerate_commits.py`, `select_commits.py`, mới `profile.py`, `estimate.py`, `stats.py`, `sensitivity.py`, `compare.py`, `control.py` | `--since/--until/--from-sha/--to-sha` (ép `--max 0`), `--tools/--expensive-tools` cho `pipeline`, `--profile` mọi subcommand + validate, `estimate` (từ `speed.json`), `stats` (JSON/CSV/LaTeX, κ nhóm + pairwise, "giới hạn"), `sensitivity` (copy DB → lưới), **`compare`** (A/B theo cluster_key, lệch phân loại theo manifest), `stop`/`stop --force`/`reset-claims --run`, `clean` tách mục + `--dry-run`, guard experiment mode, bỏ VOTE_THRESHOLD, `progress.emit` + stop-file trong scan | pytest contract: profile → argparse; env → config; `estimate`/`compare` trên fixture |
| **A3 runner-registry-preflight** | mới `runner/`, `registry/`, `preflight/`, `speed.py` | Detached process Windows/Linux, pid/stop/log, heartbeat, attach, phát hiện pid chết + DB `building` → gợi ý reset; `runs.json` + mutex + lock DB; 13 kiểm tra (RAM Docker `MemTotal`, build vs pull, `vm.max_map_count` WSL2, `:latest`, file-sharing, proxy…) + 5 auto-fix; `preflight --json`; `speed.json` | pytest mock; `preflight --json` thật (chỉ đọc) |
| **A4 gui-shell + màn 0–5** | `gui/server.py`, `gui/main.py`, `gui/web/{index.html, app.css, app.js, i18n/}`, `screens/{preflight,home,wizard1..5}.js` | Server stdlib + SSE + token, `--dev`, `--mock`; design system; 6 màn đủ trạng thái; validate đầu vào; "Nâng cao" chỉ đọc + Chế độ thí nghiệm; CLI PowerShell + bash từ profile; "Chạy lại cùng profile" (đường cho Run B) | Playwright chụp ảnh 6 màn × trạng thái vào `scratchpad/shots/` |
| **A5 màn 6–10** | `screens/{dashboard,results_overview,results_findings,results_commits,results_export,settings,review}.js` + CSS | Dashboard (ẩn nhãn tạm, Dừng an toàn/cưỡng bức, banner infra_error/Docker/đĩa, hộp đóng cửa sổ); Results 5 tab (+ Bằng chứng: raw, provenance, "gold · đồng thuận máy"); Settings 4 tab; Kiểm tay mù + adjudication | Playwright chụp ảnh như A4 |

**Trưởng trong đợt 1:** trả lời agent; `tests/fixtures/scratch.sqlite`; profile Run A; kiểm Playwright/pywebview.

---

## 5. ĐỢT 2 (T+4 → T+6) — cùng 5 agent, QA chéo

| Agent | Việc đợt 2 | Nghiệm thu |
|---|---|---|
| **A1** | Backend kiểm tay: bảng `gold_review`, `review sample --seed --n-pos --n-neg` phân tầng (clamp theo số có), map lại sau relabel, `review close` → precision + Wilson + Cohen κ + bất đồng; `build_gold_set.py` đọc bảng, bỏ hardcode; `relabel_gold_w7.py` → preset `sensitivity` | pytest; tạo mẫu từ DB scratch |
| **A2** | Batch queue (tuần tự, 1 Sonar), gói chẩn đoán zip, `ORCH_M2_VOLUME`; docs `README`/`GUIDE`/`METHODOLOGY` (QĐ 3–5, giao thức kiểm tay)/`EXECUTION_FLOW` | docs khớp code |
| **A3** | pytest unit (posix path, URL normalize, negative_level, reset-claims, run_meta, `_rmtree` read-only, GBK, cluster_key, đường dẫn có `'`) + contract; `.github/workflows/ci.yml`; `secjit.spec` PyInstaller + build exe + `--version`/`--preflight --json`/`--profile`; fallback browser nếu pywebview lỗi; toast Windows | exe chạy; pytest xanh |
| **A4** | Nối màn 0–5 vào backend thật; **QA chéo màn 6–10** theo REVIEW §III.A–C (Playwright + ảnh) → báo lỗi cho A5 | ảnh + báo cáo |
| **A5** | Nối màn 6–10 vào backend thật (DB Run A `mode=ro`, SSE progress); **QA chéo màn 0–5** → báo lỗi cho A4 | ảnh + báo cáo |

Vòng QA 2 (T+8 → T+11, trong lúc Run B): A4/A5 sửa theo báo cáo chéo; A3 chạy lại pytest + exe; trưởng xem ảnh.

---

## 6. Nếu trượt — thứ tự cắt

1. Batch queue, toast, tiếng Anh (giữ VI). 2. Biểu đồ mật độ kéo-chọn. 3. UI sensitivity (giữ CLI). 4. Exe → `run_gui.bat` (chỉ nếu T+8 exe chưa chạy). **Không cắt:** 8 lỗi dữ liệu, run_meta v2 + manifest, runner nền + Dừng an toàn, 10 màn, Run A/B + compare, tính năng kiểm tay, ảnh chụp.

---

## 7. Rủi ro & cách xử lý

| Rủi ro | Xử lý |
|---|---|
| **RAM Docker** (WSL2 mặc định 50 % = 8 GB; stack `giapha` ~2,5 GB thường trực + Sonar 2 GB + Maven 2–3 GB → OOM → Docker Desktop sập — nghi là nguyên nhân treo hôm nay) | T0 đọc `docker info MemTotal` + `.wslconfig`; theo chốt §0: tạm dừng `giapha` hoặc 1 worker; không build gì khác khi Run A/B; `infra_error` dừng sớm + `reset-claims` resume |
| pywebview + pythonnet + PyInstaller trên Windows | Kiểm ở T0; fallback exe mở trình duyệt mặc định |
| Merge 5 nhánh | Vùng file tách bạch §3; 3 module chung do trưởng viết T0; 1,5 h merge có chủ đích |
| Claude không thấy GUI | Playwright chụp PNG mọi màn × trạng thái; trưởng đọc ảnh; gallery cuối ngày cho user |
| Run A > 5 h | Run B `--max 15` cùng profile, ghi rõ RESULTS |
| Semgrep flaky / Sonar CE timeout | `tool_timeout` vào manifest; `compare` chấp nhận lệch ở commit đó |
| Agent cạn ngữ cảnh ở đợt 2 | Thay bằng agent mới cùng vùng (vẫn ≤ 5 đồng thời) |

---

## 8. Việc trưởng làm ngay (T0)

1. Bật Docker Desktop; `docker info` MemTotal; xử lý RAM theo chốt §0.
2. `pip install pywebview pyinstaller pytest playwright && playwright install chromium`; kiểm WebView2.
3. Viết `CONTRACTS.md`, `progress.py`, `keys.py`, `profile.py` schema (khung), `gui/fixtures/`, `tests/conftest.py` + `tests/fixtures/scratch.sqlite`.
4. Tạo 5 worktree; phóng 5 agent với prompt trỏ `CONTRACTS.md`, `REVIEW.md`, vùng file, tiêu chí, lệnh test, "không Docker".
5. Cập nhật `SESSION_CONTEXT.md` tại T+4 / T+8 / T+13.

---

## 9. Hiệu chỉnh so với v2 (kết quả ultrareview)

1. Lịch đợt 5 giờ/agent là sai bản chất (agent xong trong ≤ 1,5 h); đường tới hạn là Docker tuần tự (~6,5 h) + tích hợp → dự phòng thật 11 h.
2. "≤ 5 agent" → 5 agent sống suốt ngày, đợt 2 nối tiếp bằng SendMessage; QA chéo A4↔A5 (Mô hình C) thay tự kiểm.
3. CTRL_BREAK không dùng được với tiến trình detached → stop-file hợp tác + `taskkill /T`.
4. RAM Docker + stack `giapha` là rủi ro số 1 cho Run A/B → cần user chốt.
5. Thiếu `compare`, phân loại trạng thái thống nhất, 3 module chung ở T0, `PYTHONUTF8=1`.
6. Playwright chụp ảnh để trưởng và user **nhìn** được GUI.
