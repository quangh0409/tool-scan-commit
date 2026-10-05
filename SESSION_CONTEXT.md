# SESSION_CONTEXT

> Nhật ký tiến độ — cập nhật MỖI phiên (hoặc khi đạt mốc). Ghi: đã xong / đang dở / kế tiếp.
> File này KHÔNG ghi mục tiêu hay quyết định kiến trúc (cái đó ở `TOOL_IDEA_CONTEXT.md`).
> Phiên mới nhất ở TRÊN CÙNG.

---

## Trạng thái tổng quan (cập nhật nhanh)

- **ĐANG CHẠY (2026-10-05, kế hoạch 1 ngày `TASKS.md` v3): T0 XONG** — Docker Desktop lên (MemTotal 7,2 GB → 1 worker tầng đắt), pywebview/PyInstaller/pytest/Playwright+Chromium cài xong, WebView2 154 có; commit `cbd517a` = `CONTRACTS.md` (hợp đồng giao diện: profile/progress/trạng thái/run_meta v2/API GUI/CLI mới) + module chung `src/orchestrator/{progress,keys,profile}.py` + `tests/conftest.py` + `tests/fixtures/scratch.db` (train-ticket 3 commit) + `gui/fixtures/*.json` mock. **ĐỢT 1 XONG & ĐÃ MERGE (dev 32f07d2, 120 pytest xanh, ruff sạch)**: A1 (8 lỗi dữ liệu, run_meta v2, manifest, 25 test), A2 (scope/--tools/--profile/estimate/stats/sensitivity/compare/stop/clean, 30 test), A3 (runner nền/registry/preflight 13 mục, 44 test; preflight thật: ready, Docker 6,7 GB), A4 (server + khung + màn 0–5, 21 test, 33 ảnh), A5 (màn 6–10 + Kiểm tay, 66 ảnh). Hiệu chỉnh hợp đồng ghi `CONTRACTS.md` §12. **SMOKE 3 commit PASS toàn tuyến với code mới** (`data/smoke.sqlite`): build 666 s · FSB 238 · Sonar 68 · `n_expensive_ok=2` · run_meta v2 hai tầng có digest + git sha · κ lưu DB (total −0,244; pair findsecbugs|sonar −0,739) · export có `run_manifest.json`/`SHA256SUMS`/cluster_key/evidence. 0 gold vì FSB báo CSRF ở dòng khai báo method (26) còn Sonar ở `.csrf().disable()` (66) — lệch >W, semgrep không bắt commit này; không phải regression (gold csrf hôm trước = semgrep+sonar). Lỗi nhỏ: `finished_at` UTC vs `started_at` local → A1 sửa. **Run A lần 1 (`runA-20261005`) lộ lỗi Windows `semgrep WinError 206` (argv quá dài ở commit 504 file) → DỪNG AN TOÀN bằng stop-file thành công (pipeline chờ commit dở xong, exit 3, 0 container mồ côi, registry `stopped`); A1 vá semgrep (copy file đổi vào thư mục tạm) + ghi lỗi tool tầng rẻ vào `scan_tool_errors`/manifest (dev fccc24e). **RUN A LẦN 2 ĐÃ PHÓNG trên mã a8f396e (pid 22184, run_id `runA2-20261005`, registry `%LOCALAPPDATA%\secjit
uns.json`)**: train-ticket `--max 30`, 1 worker đắt, Sonar 9100, DB `data/dataset_FudanSELab__train-ticket_master_20261005_A.sqlite`, log/progress `work/runA-20261005/`. **MỐC T+8 ĐẠT (dev d5af5b0, 254 pytest + 1 xfail chờ A2 sửa stats): 10 màn + backend thật trên dev** — A4 nối preflight/runner/registry/estimate/repo_probe + server map backend thuần A5 (api_runs/results/review/settings) + QA chéo thật (ảnh `scratchpad/shots/qa-a4-on-a5/{mock,real,real2,interactive}`); A1 review backend + verify_run (17/17 PASS trên smoke) + fixture smoke_v2.db; A2 review CLI/batch/diagnostics/m2volume/verify/select idempotent/dừng scan khi infra_error + METHODOLOGY.md/GUIDE/README; A3 2 exe PyInstaller 16,7 MB (`secjit-scan.exe` console, `secjit-scan-gui.exe`), CI, release.ps1, gui.json single-instance, batch_runner; A5 backend thuần 25 route. Flow end-to-end mock 21/21 PASS trên dev (tests/gui/flow_mock.py); gallery 368 ảnh `scratchpad/shots/index.html`. A2 đợt 4 merge (rescan, batch qua runner, demo_10min.md, compare md, stats universe đã sửa). Lỗi đang sửa ở A5: DASH-1 (nhân đôi SSE), DASH-2 (banner scratch), REV-2 (cwe_claim [object Object]), pageerror removeChild. Run A2: scan 23 xong 08:36, select 15 (buggy+clean), analyze 1 worker từ 08:36. **dev 73401ee (267 test)**: A5 sửa hết lỗi QA (Dashboard 8 sự kiện, review cwe_claim, removeChild) + QA chéo màn 0–5 (10 lỗi gửi A4, PF-2 nặng: Preflight không có 'Bỏ qua' khi mục bad); A4 `tests/gui/run_b_from_exe.py` `--dry` 16/16 OK → profile B (`data/..._B.sqlite`, tái dùng work) sẵn sàng `--go` khi Run A xong; A2 METHODOLOGY §8 giới hạn matcher dòng (A1 đo: FSB neo khai báo, Sonar neo statement, lệch 18–43 dòng → gold=0 ở 12 cấu hình sensitivity) + `ORCH_CLEAN_PER_BUGGY`; A3 exe build từ dev (17 MB) + flow 21/21 trong exe + cô lập SECJIT_HOME cho test; A1 `HUONG_DAN_GUI.md` + 12 ảnh `docs/img/`, `scripts/results_report.py`, `scripts/verify_run.py`. **Đợt 2 đã giao** (A1 review backend, A2 review CLI/batch/diagnostics/m2 volume/docs, A3 unit test/CI/PyInstaller/toast, A4 nối backend thật + tích hợp màn A5 + QA chéo, A5 backend endpoint màn 6–10). Đợt 1 ban đầu: 5 agent A1–A5 chạy song song trong worktree riêng (A1 data-core 8 lỗi + run_meta v2 + manifest; A2 CLI since/until/--tools/--profile/estimate/stats/sensitivity/compare/stop/clean; A3 runner nền + registry + preflight 13 mục; A4 server + màn 0–5; A5 màn 6–10 + Kiểm tay). Run A chuẩn bị: `data/profile_runA.json` (train-ticket `--max 30`, 1 worker đắt, Sonar 9100, DB/export trong `data/`), clone sẵn `work/train-ticket`. Sandbox không ghi được `D:\secjit` → mọi đường dẫn test nằm trong repo (`data/`, `work/`, gitignore).
- **(2026-10-04, Claude local Windows): CHẠY THỬ PIPELINE TRÊN WINDOWS + VÁ 4 LỖI PORTABILITY + PLAN BẢN DESKTOP .EXE.** Smoke test train-ticket `scan --max 3` (scratch DB, Docker Desktop) → tầng rẻ chạy trọn (5 tool, 17 cụm bearer; select/relabel/kappa/export/merge_export OK). Tầng đắt lộ 4 lỗi, đã vá: (1) `os.getuid()` crash Windows → helper `run_as_user()` trong `tools_expensive/base.py` (Linux giữ `-u uid:gid`, Windows bỏ); (2) **port host 9000 bị container khác chiếm** → `ORCH_SONAR_PORT` (config + sonar.py), `docker run` sonar fail-fast thay vì chờ 6'; (3) **path backslash lọt vào container** (`relative_to()` ra `ts-common\target\classes`) → FindSecBugs "No files to analyze", Sonar "Invalid sonar.java.binaries" → `.as_posix()` trong findsecbugs.py/sonar.py, XML 0 byte coi là lỗi; (4) pool clone không xoá được file read-only `.git/objects/pack` → `_rmtree` chmod trong repo_pool.py. **Verify sau vá trên clone đã build (313886e9): FindSecBugs 238 finding (CWE-352 SecurityConfig:26 đúng như VM), Sonar 68 finding.** CHƯA verify end-to-end `analyze` lần 2 (Docker Desktop tắt khi máy treo do build Maven + Sonar chạy cùng lúc). Build cold cache trên Windows 881 s/commit. Thêm `pyproject.toml` ruff (chỉ F/E9), cài `gh` CLI, viết lại CLAUDE.md. **`DESKTOP_APP_PLAN.md` (MỚI)**: review ý tưởng exe + wireframe 10 màn (artifact click được). **Review 3 vai BA/TEST/PO → `REVIEW.md`** (8 lỗi dữ liệu trong code, 20 mâu thuẫn plan↔code, MoSCoW). **User CHỐT**: đủ 10 màn; tái lập `--max 30` laptop; có kiểm tay; Claude quyết 3 điểm phương pháp luận (khoá cấu hình v1 + sensitivity; "gold · đồng thuận máy" vs "gold ✓ TP"; sửa 8 lỗi dữ liệu trước) → `TOOL_IDEA_CONTEXT.md` §13. **User chốt tiếp: 5 DB cũ ĐÃ MẤT, KHÔNG sinh lại — dữ liệu test tool = DB scratch 3 commit + Run A/B `--max 30`; test local không máy sạch; hạn 1 NGÀY, ≤5 agent, Claude full quyền → `TASKS.md` viết lại thành kế hoạch 1 ngày** (T0 hợp đồng giao diện `CONTRACTS.md` → đợt 1 5 agent A1–A5 → merge + smoke → Run A `--max 30` CLI → đợt 2 5 agent B1–B5 → exe → Run B từ exe → so A/B → RESULTS). Điểm kiểm tra cứng T+8 / T+15 / T+20; thứ tự cắt §6.
- **(2026-07-07): SKYWALKING PHÓNG LẠI (detached) sau khi run cũ chết theo phiên + VÁ RESUME TẦNG SCAN**: run 06/07 chết ~23:53 (kill theo phiên SSH/Claude cũ — KHÔNG crash code, log sạch) tại **2144/7568 commit scan (~28%)**; chưa tới select/analyze. **Mối lo "code cũ trong RAM" (fix `changed_modules`) TỰ GIẢI QUYẾT**: tiến trình cũ chết → run mới nạp code mới từ đĩa (đã verify fix leo-pom-gần-nhất trong build.py). **Vá resume tầng scan (trước đây scan KHÔNG resume — chạy lại = mất 6.5h + nhân đôi row)**: (1) bảng mới `scan_done` (mốc commit quét TRỌN, ghi CUỐI `_scan_one_commit`; KHÔNG dùng scanned_files làm mốc vì commit 0-file không có row); (2) `scan_done_ids()` union scanned_files (phủ DB cũ trước khi có bảng — scanned_files là ghi áp-chót atomic nên có row = chắc chắn xong); (3) `reset_cheap_scan(commit)` xoá raw_findings/raw_output tier=cheap + scanned_files TRƯỚC khi quét lại → re-scan idempotent (findings vốn đã idempotent qua `replace_findings_for_commit` của relabel); (4) config `ORCH_SCAN_RESUME` (mặc định 1). **Test 3 ca pass** (scratch DB train-ticket --max 8): rerun → skip đủ 8; giả lập kill-giữa-chừng (raw lửng, không scanned_files) → quét lại đúng 1 commit, 0 nhân đôi. ⚠️ Phát hiện phụ khi test: commit 313886e9 flaky — **semgrep timeout per-rule** trên JS lớn ts-ui-dashboard (raw-html-format) → run được run mất 17 cụm; flakiness CÓ SẴN của tool (đối chứng DB-mới-không-patch tái lập), không do patch. **Run mới: 00:42 07/07, `setsid`+nohup (PPID=1, sống độc lập phiên), PID xem `ps -ef | grep orchestrator.cli`**, cùng lệnh/env cũ (`ORCH_SQLITE=data/dataset_skywalking.sqlite`, `ORCH_EXPENSIVE_WORKERS=3`, log append `data/pipeline_skywalking.log`). Patch resume + fix trước đó CHƯA commit. **① SCAN xong 100% (5904 commit, RESUME bỏ 1664 commit cũ đúng thiết kế), ② SELECT: universe 5554 = buggy 1519 + clean 4035.**
- **NÂNG WORKER 3→4 (2026-07-08 ~15:33, theo yêu cầu user "A")**: tầng ③ vào dải commit đa-module 2018-2019 build cực nặng (15-30'/commit) → nhịp rớt còn 1-5 c/h, ETA giãn 6-9 ngày. Flow: SIGTERM pipeline (python 1219652 + launcher) → xóa 3 container mồ côi theo ID (sonar-scanner+maven+orch-sonar) + gỡ network `orch-sonar-net` → reset 3 commit `building`/`analyzing` mồ côi về pending (đã xóa raw đắt bán phần: raw_output/raw_findings tier=expensive + expensive_runs của chúng để không nhân đôi audit; raw_findings đắt vốn ghi 1 lần ở cuối `_process` nên phần lớn chưa có) → phóng lại **`scripts/resume_skywalking.sh`** (MỚI): `analyze --workers 4 --codeql 0` → `relabel` → `kappa` → `export`, `setsid`+nohup, log append. Xác nhận 4 worker: building 2 + analyzing 2 đồng thời. `start_server()` tự `rm -f` container sonar cũ + tạo mới (gotcha đổi-mật-khẩu admin/admin tự xử lý) nên KHÔNG cần lo giữ orch-sonar khi restart. **Mốc khi analyze xong: script tự chạy tiếp relabel→kappa→export, KHÔNG cần can thiệp.** Trước nâng: done 162 · gold 28 · silver ~5392.
- **(2026-07-06): repo full-history THỨ NĂM xong — apache/giraph 1128 commit (14.0h, exit 0, 0 Traceback — RUN DÀI-SẠCH NHẤT DỰ ÁN)**: DB `data/dataset_giraph.sqlite`, export `data/export_giraph/` (1129 thư mục, 188MB, dataset.jsonl 8043 dòng + commits.jsonl 1128 dòng). Branch `trunk` (user yêu cầu main — đã xác minh ls-remote). Analyze: done **707** / build_failed 351 (**67%** ok — #2 sau train-ticket; giraph pin release nên dependency Hadoop cổ vẫn kéo được). Nhãn: **gold 20** (crypto CWE-326/330/338/1241 ×16 · sensitive_exposure CWE-209/215/489 ×4, toàn bearer+sonar cross-tier) · silver 5885 · candidate 2138; tier mixed 20; in_diff=1: 271. Negatives: **verified-clean 635 (GOLD)** + cheap-clean 378. κ=-0.332. Raw: findsecbugs 9750 · sonar 4869 · horusec 1557 · semgrep 801 · bearer 330. **`scripts/merge_export.py` ĐÃ CHỐT** (món nợ 2 phiên — dataset=concat label.json; commits=commit_features+summary.json). **Fix submodule XONG + test**: `repo_pool._init_submodules` (sync+update --init --recursive sau checkout, lỗi không chặn; store .git/modules tái sử dụng → chỉ tốn mạng lần đầu/clone; config `ORCH_SUBMODULES` mặc định 1) — test thật skywalking: 26 proto + 23 graphqls, checkout lần 2 = 0.6s. **Skywalking 8570 commit khởi chạy** (`--branch master`, 3 worker tầng đắt `ORCH_EXPENSIVE_WORKERS=3`, DB/export/log `*_skywalking`) — run này CHẾT theo phiên ~23:53, xem bullet 2026-07-07. **Fix `changed_modules` (monorepo lồng nhau)**: smoke-test build commit HEAD (ý user "test 1 commit trước") lộ bug — logic cũ lấy thư mục cấp 1 = pom aggregator (`oap-server`) → mvn rc=0 nhưng **0 classes** (tầng đắt trắng tay); fix = leo từ file đổi lên **pom.xml gần nhất** (`-pl oap-server/analyzer/log-analyzer` v.v.) → smoke v2: build ok 899s, **21 classes_dirs**; hồi quy giraph 30/30 commit y logic cũ. ~~⚠️ Tiến trình pipeline skywalking đang chạy giữ CODE CŨ trong RAM~~ → **ĐÃ GIẢI QUYẾT 2026-07-07**: tiến trình cũ chết, run mới nạp fix `changed_modules` từ đĩa ngay từ đầu — không cần kill trước analyze nữa.
- **(2026-07-04, phiên c): repo full-history THỨ TƯ xong — mall-swarm 464 commit (~3.7h, exit 0, KHÔNG crash)**: DB `data/dataset_mall-swarm.sqlite`, export `data/export_mall-swarm/` (465 thư mục, 132MB, dataset.jsonl 3151 dòng + commits.jsonl 464 dòng). Analyze: done **151** / build_failed 128 (**54%** ok — giữa train-ticket 92% và library Spring 13%; commit cũ kéo dependency biến mất). Nhãn: **gold 23** (csrf CWE-352 ×9 · sensitive_exposure CWE-209/215/489 ×8 · crypto CWE-326/330/338/1241 ×5 · CWE-942 CORS ×1) · silver 2924 · candidate 204; tier mixed 23; in_diff=1: 177. Negatives: **verified-clean 108 (GOLD)** + cheap-clean 294. κ=-0.260 (ít âm nhất 4 repo). Raw: findsecbugs 5554 · sonar 625 · semgrep 290 · bearer 44 · horusec 37. ⚠️ Script gộp jsonl KHÔNG được lưu từ phiên trước — phiên này viết lại inline (concat label.json; commits = commit_features + labels/role/negative_level từ summary.json); NÊN lưu thành `scripts/merge_export.py`.
- **(2026-07-04): repo full-history THỨ BA xong — train-ticket 274 commit (~2.5h) — RUN ĐẸP NHẤT DỰ ÁN**: DB `data/dataset_train-ticket.sqlite`, export `data/export_train-ticket/` (276 thư mục, 516MB, dataset.jsonl 19708 dòng + commits.jsonl 276 dòng). **App thuần build 92% ok (160 done/14 fail — vs 13% của library Spring)** → tầng đắt phủ gần trọn: nhãn **gold 208** (csrf 109 · weak_random 32 · sensitive_exposure 26 · CWE-1004 25 · hardcoded_secret 11 · CWE-614 5) · silver 11974 · candidate 7526; tier mixed 190; in_diff=1 2485. Negatives: verified-clean **70 GOLD** + cheap-clean 111. κ=-0.359. **Crash UnicodeDecodeError giữa relabel đã vá bền** (diff GBK 290MB — errors="replace" ở `_git`/repo_pool/tools.base; kamei vốn đã đúng). → Chốt chiến lược: **repo pilot nên là APP thuần**, không phải library.
- **(2026-07-03/04): repo full-history THỨ HAI xong — spring-cloud-kubernetes 2666 commit (~8.5h)**: DB `data/dataset_spring-cloud-kubernetes.sqlite`, export `data/export_spring-cloud-kubernetes/` (2666 thư mục, 135MB, dataset.jsonl 3273 dòng + commits.jsonl 2666 dòng). Nhãn: **gold 0 · silver 585 · candidate 2688** — repo này **KHÔNG có cụm nào ≥2 tool trùng** (n_tools_agree≥2 = 0, κ=-0.473); silver toàn 1-tool-đắt (findsecbugs 482 / sonar 103). Negatives: **verified-clean 264 (GOLD)** + cheap-clean 2250. Analyze: done 300 / build_failed 1955 (~87% — SNAPSHOT data-availability như spring-cloud-stream). **Crash giữa run đã vá 2 fix bền** (xem phiên 2026-07-03/04).
- **Giai đoạn:** Pipeline HOÀN CHỈNH đã chạy thật FULL-HISTORY repo lớn — **spring-cloud-stream 4364 commit, 16.5h, exit 0** (xem phiên 2026-07-02/03 (b)). Dataset: `data/dataset_spring-cloud-stream.sqlite` + `data/export/{dataset,commits}.jsonl`. Train-ticket pilot ở `data/dataset.sqlite`.
- **Cấu trúc dataset 2 mức (chốt, giải thích cho user 2026-07-03):** `dataset.jsonl` 1 dòng = 1 **CỤM finding** (gộp raw theo file + nhóm-CWE + dòng ±3 rồi vote) — 10061 cụm từ 1468 commit-có-finding, KHÔNG chứa negative; `commits.jsonl` 1 dòng = 1 **commit** (đủ 4364: kamei + labels + negative_level) — dùng cho JIT commit-level. Gold positive=26 cụm; gold negative=1004 commit verified-clean.
- **CodeQL THẬT xong ✅ (chạy được):** image `orch-codeql:2.25.6` (maven+codeql bundle). Wrapper: DB create trace `mvn compile` module-bị-đụng → analyze `java-code-scanning` → SARIF → RawFinding (CWE từ tags). PoC `350f6200`: ra CWE-352 spring-disabled-csrf @ SecurityConfig.java:65 (đúng path/line). Write-back: cột `tier`, `_store_expensive` (consensus+enrich+tier=expensive), verify OK. **⚠️ Chi phí ~21 phút/commit** (suite nhẹ, DB 84M) — query eval nặng → cần tối ưu hoặc K nhỏ. `--ram=20000 --threads=0`. Config: `CODEQL_SUITE/RAM_MB/THREADS`.
- **Tối ưu CodeQL XONG ✅:** chẩn đoán — DB create chỉ **29s**, toàn bộ ~20' là analyze (query dataflow). Suite tối giản 10 query (`docker/codeql/minimal-java.qls`, bake image, CWE-89/79/78/22/90/352/502/611/918) → analyze 376s, **tổng ~6.7'/commit** (từ 21'), vẫn ra đúng CWE-352. ~~Mặc định `CODEQL_SUITE=/opt/minimal-java.qls`~~ (ĐÃ ĐỔI: `config.py` hiện mặc định suite full `java-code-scanning.qls`; suite tối giản dùng qua `ORCH_CODEQL_SUITE=/opt/minimal-java.qls`). → 17 buggy ≈ 2h.
- **CẢ 3 TOOL ĐẮT XONG ✅** (đều validated trên commit 350f6200, build dùng chung ~14s):
  - **CodeQL** ~20'/commit (code-scanning) — dataflow sâu; ra CWE-352.
  - **FindSecBugs** analyze **7s** ⚡ — 43 finding (bytecode pattern, nhiễu hơn); ra CWE-352.
  - **SonarQube** scan **~22s** — server singleton headless (đổi pw+token QUA API, KHÔNG web); 11 finding; CWE-352+CORS. ⚠️ BẮT BUỘC `sonar.java.libraries=/m2 jar` (thiếu→0 finding).
  - **CWE-352 CSRF @ SecurityConfig** cả 3 tool cùng bắt (line 65/_/67, ≤window) → consensus 3-tool thật.
  - Gotcha đã xử: vm.max_map_count=262144 (user sudo); SonarQube admin/admin chỉ dùng lần đầu→đổi pw qua API (config SONAR_ADMIN_PW).
- **Công tắc `USE_CODEQL`** (CLI `--codeql 0/1`, mặc định 1): tắt → tầng đắt chỉ FindSecBugs+Sonar (~30s/commit).
- **GOLD không bắt buộc CodeQL (chốt):** GOLD = đồng thuận ĐA-TOOL; 2 tool đắt (FindSecBugs+Sonar) [+rẻ] đủ GOLD cho CẢ positive lẫn negative; CodeQL là bonus tùy ngân sách. Dataset ghi rõ tool nào xác nhận (agreeing_tools+tier). Xem `EXPENSIVE_TIER_REPORT.md` §5d.
- **CROSS-TIER CONSENSUS XONG ✅** (theo `RULE_GAN_NHAN.md`): lưu RAW từng-tool (bảng `raw_findings`) → `relabel_commit` gộp cụm rẻ+đắt → nhãn **gold/silver/candidate** (matcher tier-aware, config GOLD_MIN_EXPENSIVE...). Analyze đắt thêm raw đắt + relabel → nhãn tự nâng (candidate→gold). Verify: ladder 6 ca đúng; semgrep(candidate)→+codeql+findsecbugs=gold (mixed, 1 dòng). Trường mới: label/n_cheap/n_expensive/eligible/tier=mixed.
- **(B) lưu output THÔ + (C) export XONG ✅:** mọi wrapper trả `raw_out` → bảng `raw_output` (sarif/xml/json audit). Lệnh `export` → mỗi commit 1 thư mục: `<tool>.raw.<ext>` + `<tool>.findings.json` + `label.json` + `summary.json`. Số tool KHÔNG hardcode (5 rẻ + 2/3 đắt = 7/8 tuỳ CodeQL).
- **14 ĐẶC TRƯNG KAMEI XONG ✅** (JIT defect prediction, Kamei 2013): module `kamei.py` — 1 lượt `git log --reverse -M --numstat` (~3-4s/39 commit), state tăng dần, chỉ nhìn quá khứ. NS/ND/NF/Entropy · LA/LD/LT · FIX · NDEV/AGE/NUC · EXP/REXP/SEXP. Bảng `commit_features` + field `DatasetRow.kamei` (nhúng mọi row label.json qua relabel) + block `kamei` trong summary.json (CẢ commit negative). Tự chạy trong `scan` (`ORCH_KAMEI=1`); backfill DB cũ: lệnh `features <repo>`. Test synthetic 84/84 (gồm rename/merge-skip/binary); spot-check e5ae0c3a khớp git (NF=193/LA=3554/LD=2027/EXP=0). Merge bỏ qua; KHÔNG áp EXCLUDE_PATHS.
- **Việc kế tiếp:** kiểm tay 26 gold + mẫu verified-clean đo precision; cân nhắc bật CodeQL (`--codeql 1`) tăng gold; chọn repo pilot tiếp theo ưu tiên app thuần (ít phụ thuộc SNAPSHOT như library Spring — xem phát hiện data-availability phiên (b)).
- **Mô hình dataset (chốt):** buggy (có CWE/CVE tool rẻ) → tầng đắt → POSITIVE; clean (0 CWE/CVE) → NEGATIVE lấy hết, KHÔNG quét đắt. Negative = "cheap-clean" (silver).
- **BACKLOG (chốt với user 2026-07-02): AUTO-DETECT JDK cho build tầng đắt** — làm SAU khi pipeline spring-cloud-stream chạy xong. Ý tưởng: (1) đọc `pom.xml` tại từng commit (`git show <sha>:pom.xml`) → `<java.version>`/`<maven.compiler.release>` → map image `maven:3.9-eclipse-temurin-<8|11|17|21>`, fallback `ORCH_MAVEN_IMAGE`; (2) tuỳ chọn retry hạ cấp JDK khi build fail trước khi đánh `build_failed`. Bối cảnh: repo lịch sử dài đổi JDK (spring-cloud-stream: Boot 1.x/2.x cần 8, main cần 17) — image cố định kiểu gì cũng fail một khúc.
- **BACKLOG (ý tưởng user):** nếu FindSecBugs/Sonar đo ra NHANH lúc cắm → cho 2 tool đó quét luôn clean commit; clean vẫn-sạch → **verified-clean = GOLD negative**; clean mà ra finding → FN tool rẻ → đẩy sang positive. (KHÔNG dùng CodeQL cho clean — quá chậm ~phút/commit.) Cột nhãn phân biệt cheap-clean vs verified-clean. Xem `EXPENSIVE_TIER_REPORT.md` §5d.
- **Fix recall secret (yêu cầu user "doc có key cũng là lỗi"):** `coarse_filter` KHÔNG còn bỏ commit "chỉ docs/non-code"; chỉ bỏ khi **toàn file nhị phân** (`BINARY_EXTENSIONS`). Commit text-only (README/.env/.sh/Dockerfile) giờ giữ → gitleaks/trufflehog (quét toàn diff, bất kể đuôi) bắt được key. Verify: 34/150 commit text-only được giữ; commit README chạy secret tool OK.
- **A vs B (tầng rẻ, đo sạch 29 commit/4 worker):** A 264s; B (tool song song trong commit) **227s (~14% nhanh hơn)**, findings 2828≈2827. → **Tầng rẻ CHỐT dùng B** (`CHEAP_INTRA_PARALLEL=1` mặc định). Tầng đắt giữ A (`EXPENSIVE_INTRA_PARALLEL=0`) tới khi cắm tool thật mới đo. Toggle tách theo tầng.
- **Fix hạ tầng:** RepoPool base riêng theo PID (2 tiến trình không clobber); maven build chạy as-uid (`-u`, HOME=/tmp, repo.local trong cache) → không sinh file root kẹt clone-pool.
- **PoC build XONG ✅:** train-ticket Spring Boot 2.3.12/JDK8/43 module; image `maven:3.9-eclipse-temurin-8`. Build **chỉ module bị đụng** (`-pl <mods> -am`, auto-detect) → service+dep ~13s, commit 11-module ~32s (cache ấm). `build.changed_modules()` + `build_commit()` đã chạy thật ra 183 .class. → build KHÔNG phải nút thắt.
- **Cầu nối rẻ→đắt (XONG):** `orchestrator select` chọn buggy (**có mã CWE/CVE** — chỉ cần 1 tool/1 finding) + mẫu clean 1:N (N=`CLEAN_PER_BUGGY`, mặc định 20) → bảng `selected_commits`. `FLAG_LIMIT` (mặc định 0) bật/tắt ngưỡng bỏ commit khổng lồ.
- **Repo này đã là git repo?** Rồi.
- **5 tool tầng rẻ:** secret = gitleaks+trufflehog(+horusec Leaks); code = semgrep(p/default)+bearer(+horusec). VOTE_THRESHOLD=2.

---

## Phiên 2026-07-04 (c) — CHẠY THẬT mall-swarm FULL (464 commit) — run #4, SẠCH KHÔNG CRASH

### Run full-history repo #4 — XONG ✅ (13399s ≈ 3.7h, exit 0, không cần resume)
- Lệnh: `pipeline https://github.com/macrozheng/mall-swarm --max 0 --branch master --codeql 0 --include-clean` + `ORCH_SQLITE=data/dataset_mall-swarm.sqlite` + `--out data/export_mall-swarm` (branch mặc định `master` — xác minh ls-remote; repo còn dev-v2/dev-v3/teach không dùng).
- **① Scan:** 464 commit (~35', 4 worker), 234 cụm rẻ, 3053 file clean, 0 bỏ khổng lồ, 0 lỗi. Kamei 464/464 (1.2s).
- **② Select:** universe 279 = buggy 60 + clean 219.
- **③ Analyze (FindSecBugs+Sonar, 2 worker, ~3h):** done **151** / build_failed **128** (54% ok — mall-swarm pin release nên không SNAPSHOT-hole toàn cục, nhưng nửa cũ lịch sử kéo dependency đã biến mất khỏi registry). Tốc độ tăng dần 36→94 c/h khi cache Maven ấm.
- **Nhãn cuối:** **gold 23** · silver 2924 · candidate 204 (3151 cụm; tier mixed 23; in_diff=1: 177). Gold: csrf CWE-352 ×9 · sensitive_exposure CWE-209/215/489 ×8 · crypto CWE-326/330/338/1241 ×5 · CORS CWE-942 ×1 — cùng profile train-ticket (SecurityConfig/csrf là nguồn gold chính của app Spring).
- **Negatives:** verified-clean **108 (GOLD)** + cheap-clean 294. **Kappa:** κ=-0.260 (3151 item) — ÍT ÂM NHẤT trong 4 repo (-0.26/-0.32/-0.39/-0.47).
- Raw: findsecbugs 5554 · sonar 625 · semgrep 290 · bearer 44 · horusec 37.
- **Export:** 465 thư mục (132MB) + dataset.jsonl 3151 dòng + commits.jsonl 464 dòng.
- **Xác nhận cross-repo lần 2:** app thuần → build ≥54%, gold 2 chữ số; app càng "đang phát triển gần đây" (train-ticket) build càng cao. Tiêu chí chọn repo: app + dependency còn sống.
- ⚠️ **Script gộp dataset.jsonl/commits.jsonl chưa được lưu thành file** (2 phiên đều viết inline) → việc kế tiếp: chốt vào `scripts/merge_export.py` hoặc nhét vào lệnh `export`.

---

## Phiên 2026-07-04 (b) — CHẠY THẬT train-ticket FULL (274 commit) + vá UnicodeDecodeError

### Run full-history repo #3 — XONG ✅ (~2.5h kể cả 1 crash+resume) — GOLD BÙNG NỔ
- Lệnh: `pipeline https://github.com/FudanSELab/train-ticket --max 0 --branch master --codeql 0 --include-clean` + `ORCH_SQLITE=data/dataset_train-ticket.sqlite` + `--out data/export_train-ticket`. (User yêu cầu `--branch main` nhưng repo chỉ có `master` — đã xác minh `git ls-remote` trước khi chạy.)
- **① Scan:** 274 commit (~35'), 7070 cụm rẻ, 4209 file clean, 0 bỏ khổng lồ (FLAG_LIMIT=0 nên quét cả bulk-commit pilot cũ từng skip). Kamei 276/276 (3.4s).
- **② Select:** universe 174 = buggy 119 + clean 55.
- **③ Analyze:** done **160** / build_failed **14** (92% ok! — app thuần không SNAPSHOT-hole; JDK8 fallback + auto-detect chạy êm). ~2h/2 worker.
- **Nhãn cuối:** **gold 208** · silver 11974 · candidate 7526 (19708 cụm; tier mixed 190; in_diff=1: 2485). Gold: csrf 109 (semgrep+sonar @ SecurityConfig hàng loạt service) · weak_random 32 · sensitive_exposure 26 · CWE-1004 25 · hardcoded_secret 11 · CWE-614 5. Cơ chế candidate→gold nâng cấp qua relabel hoạt động đúng (thấy candidate giảm khi analyze chạy).
- **Negatives:** verified-clean **70 (GOLD)** + cheap-clean 111. **Kappa:** κ=-0.359 (19708 item) — nhất quán 3 repo (-0.32/-0.39/-0.47/-0.36).
- Raw: findsecbugs 24366 · semgrep 9243 · sonar 5371 · bearer 1096 · horusec 247 · trufflehog 2.
- **Export:** 276 thư mục (516MB) + dataset.jsonl **19708 dòng (103MB)** + commits.jsonl 276 dòng (kamei đủ 14 đặc trưng mọi commit).
- **KẾT LUẬN CROSS-REPO (3 repo):** app thuần (train-ticket) build 92% → gold 208 + mixed 190; library Spring build ~13% → gold 26/0. **Chốt: chọn repo pilot dạng APP** (web app Java/Maven có SecurityConfig, Docker/k8s) để tối đa gold.

### ⚠️ CRASH tầng ④ RELABEL + FIX BỀN (đã áp, CHƯA commit)
- **Sự cố:** commit diff ~290MB chứa byte ngoài UTF-8 (0xd5, file GBK) → `enumerate_commits._git` (`text=True` strict) nổ `UnicodeDecodeError` → pipeline exit 1 (analyze đã xong, không mất gì nhờ raw-trong-DB).
- **Fix:** `errors="replace"` tại `_git()` + `repo_pool.checkout` + `tools/base.docker_run`. (`kamei.py` vốn đã đúng từ đầu.) Resume relabel→kappa→export qua chính commit đó OK.

---

## Phiên 2026-07-03/04 — CHẠY THẬT spring-cloud-kubernetes FULL (2666 commit) + vá crash checkout pool

### Run full-history repo #2 — XONG ✅ (~8.5h kể cả 1 lần crash+resume)
- Lệnh: `pipeline https://github.com/spring-cloud/spring-cloud-kubernetes --max 0 --branch main --codeql 0 --include-clean` + `ORCH_SQLITE=data/dataset_spring-cloud-kubernetes.sqlite` + `--out data/export_spring-cloud-kubernetes` (DB + export RIÊNG theo repo, như quy ước).
- **① Scan:** 2666/2666 commit (~5h, ~480 c/h, 4 worker), 2688 cụm rẻ, 24375 file clean, 0 bỏ vì khổng lồ, 0 lỗi. Kamei 2666/2666.
- **② Select:** universe 2255 = buggy 487 + clean 1768 (include-clean).
- **③ Analyze (FindSecBugs+Sonar):** done **300** / build_failed **1955** (~87% — pom neo `*-SNAPSHOT` đã xoá khỏi repo.spring.io, cùng mô hình data-availability spring-cloud-stream; JDK auto-detect chạy tốt, thấy image temurin-8 được chọn tự động cho commit cũ).
- **Nhãn cuối:** gold **0** · silver 585 · candidate 2688 (3273 cụm; in_diff=1: 564). **Phát hiện:** repo này KHÔNG có cụm nào ≥2 tool trùng (n_tools_agree≥2 = 0) → silver toàn 1-tool-đắt (findsecbugs 482: weak_random/path_traversal/CWE-176; sonar 103); κ tổng **-0.473** (rời hơn cả stream -0.392). Raw: findsecbugs 4191 · semgrep 1669 · bearer 551 · horusec 536 · sonar 103 · trufflehog 1.
- **Negatives:** verified-clean **264 (GOLD)** + cheap-clean 2250.
- **Export:** 2666 thư mục (135MB) + `dataset.jsonl` (3273 dòng) + `commits.jsonl` (2666 dòng — script gộp: dataset = concat label.json; commits = commit_features + labels/role/negative_level từ summary.json).

### ⚠️ CRASH giữa analyze + 2 FIX BỀN (đã áp dụng, CHƯA commit)
- **Sự cố:** worker chết tại `git checkout --detach a06ebc9f` trong clone pool (artefact build untracked sót lại từ commit trước đụng độ file commit đích) → exception KHÔNG được bắt trong `expensive_runner._loop` → `ex.map` ném → SẬP cả pipeline (exit 1) sau ~1575/2255 commit.
- **Fix 1 `repo_pool.checkout`:** dùng `checkout -qf`; nếu vẫn fail → `git clean -fdxq` rồi retry lần cuối.
- **Fix 2 `expensive_runner._loop`:** try/except quanh từng commit → ghi `expensive_runs` (phase=process, status=failed) + `set_commit_status('error')` rồi đi tiếp — 1 commit hỏng KHÔNG giết worker/run nữa.
- **Resume chứng minh thiết kế bền:** claim nguyên tử + `reset_stale_claims` (7200s) → không mất dữ liệu; chạy tiếp `analyze→relabel→kappa→export` bằng lệnh con (KHÔNG chạy lại `pipeline` — tránh scan lại). Commit từng gây crash `a06ebc9f` sau fix → **done** sạch sẽ.
- **Bài học vận hành:** 2 commit bị claim đúng lúc crash kẹt `building` → lượt resume sau reset stale mới vét được; kiểm `selected_commits` status trước khi kết luận xong.

### Kế tiếp
- Kiểm tay mẫu silver 1-tool-đắt + 264 verified-clean của kubernetes; so sánh cross-repo với stream.
- Cân nhắc repo pilot #3 dạng APP thuần (không phải library Spring) để né SNAPSHOT-hole + tăng tỷ lệ build ok.
- Commit 2 fix (repo_pool + expensive_runner) — user chưa yêu cầu commit.

---

## Phiên 2026-07-02/03 (b) — CHẠY THẬT spring-cloud-stream FULL (4364 commit) + auto-detect JDK

### Pipeline full-history đầu tiên — XONG ✅ (16.5h, exit 0)
- `pipeline https://github.com/spring-cloud/spring-cloud-stream --max 0 --branch main --codeql 0 --include-clean` + **DB RIÊNG** `data/dataset_spring-cloud-stream.sqlite` (`ORCH_SQLITE` — KHÔNG trộn repo trong 1 DB: relabel/select sẽ crash/trộn commit) + `ORCH_MAVEN_IMAGE=maven:3.9-eclipse-temurin-17` (main cần JDK 17).
- **① Scan:** 4364 commit / 5.7h (~645 c/h, 4 worker), 4308 cụm rẻ, 18973 file clean, 0 lỗi. Kamei 4364/4364 trong 3.3s.
- **③ Analyze (FindSecBugs+Sonar, 2 worker, ~10h):** done **1110** / build_failed **2631**.
- **Nhãn cuối:** gold **26** (toàn sensitive_exposure CWE-209/215/489, bearer+sonar) · silver 5764 · candidate 4271 = 10061 cụm. in_diff=1: 444. Negatives: **verified-clean 1004 (GOLD)** + cheap-clean 3115; positive 245.
- **Kappa:** κ tổng **-0.392** (10061 item) — tool phủ rời nhau, giống train-ticket (-0.32).
- **Export:** 4364 thư mục (923MB) + **`dataset.jsonl`** (10061 dòng, 41MB) + **`commits.jsonl`** (4364 dòng, kamei+labels+negative_level) do phiên này gộp thêm.
- Raw theo tool: findsecbugs 57202 (nhiễu) · bearer 3545 · horusec 530 · semgrep 315 · sonar 201 · trufflehog 14.

### Auto-detect JDK (Task #1) — XONG ✅ + PHÁT HIỆN QUAN TRỌNG
- `build.detect_jdk()` (pom tại commit, sha-scoped) + `maven_image_for()` → temurin 8/11/17/21 (làm tròn LÊN), fallback `MAVEN_IMAGE`. Config `ORCH_JDK_AUTODETECT=1`, `ORCH_JDK_IMAGE_TEMPLATE`. Hồi quy train-ticket OK (không khai java.version → fallback 8 như cũ).
- **Fix bug che lỗi build:** error tail cũ lấy `stderr or stdout` — stderr toàn nhiễu entrypoint ("mkdir /root: Permission denied") CHE lỗi mvn thật (nằm stdout). Giờ ưu tiên dòng [ERROR]/[FATAL] stdout.
- **Giải thích cấu trúc cho user (Q&A cùng phiên):** `s_detail_line` = dòng cụ thể gây lỗi (union khi gộp cụm; nguồn tính `finding_in_diff` — so với `diff_parsed.added`); `diff_parsed` = diff của (commit, file) parse sẵn từ `git show --unified=0` (added đánh số file MỚI, deleted file CŨ), mọi row cùng (commit,file) mang cùng diff_parsed; 10061 row ≠ 4364 commit vì 1 commit nhiều cụm (max 54 cụm/commit; 2896 commit 0-finding chỉ nằm trong commits.jsonl); ví dụ gold điển hình: `1f9cc848` FunctionConfiguration.java:818 CWE-209/215/489 bearer+sonar (in_diff=0 — nợ cũ, tool đắt phơi ra).
- **⚠️ PHÁT HIỆN: 2631 build_failed KHÔNG phải do JDK.** Phân loại theo pom: **2406 commit neo parent/dep `*-SNAPSHOT` đã bị XOÁ khỏi repo.spring.io** (mô hình dev Spring: main luôn SNAPSHOT giữa các release) → **không thể build lại, bất kể JDK** — giới hạn data-availability của hệ sinh thái, không phải bug pipeline. 222 "release" còn lại phần lớn cũng kéo submodule SNAPSHOT (test 006a7205 v3.2.0 vẫn fail vì starter-parent 3.2.0-SNAPSHOT). → Tầng đắt chỉ phủ được commit mà dependency closure còn tồn tại (= 1110 commit gần đây). Auto-detect vẫn giá trị cho repo khác / lần chạy sau (khỏi cần ORCH_MAVEN_IMAGE tay).

---

## Phiên 2026-07-02 — 14 đặc trưng Kamei (JIT defect prediction)

Theo paper "Expert Features for Defect Prediction and Localization" (bộ 14 đặc trưng Kamei et al. 2013).

### Đã làm
- **`kamei.py` (MỚI):** `compute_features(repo_dir, targets, rev)` — 1 lệnh `git log --reverse -M --numstat --pretty=<sentinel>` duyệt CŨ→MỚI, state tăng dần (file_loc/last_ts/authors/commits, author_nprev/prev_ts, subsys_nprev); đặc trưng tính TRƯỚC khi cập nhật state (chỉ nhìn quá khứ). Biên: merge bỏ hoàn toàn (chuẩn Commit Guru); rename `{old => new}` chuyển state; binary (numstat `-`) tính NF/ND/NS nhưng loại khỏi Entropy/LA/LD/LT; Entropy chuẩn hoá /log2(n); LT/AGE = trung bình theo file; REXP=Σ1/(tuổi_năm+1); KHÔNG áp EXCLUDE_PATHS. FIX theo `ORCH_FIX_KEYWORDS` (khớp đầu-từ, quét cả body %B — bắt được squash-merge "Release 0.2.0" chứa dòng fix).
- **Schema/DB:** bảng `commit_features` (PK commit_id, độc lập findings → negative vẫn có); `DatasetRow.kamei: dict` + cột JSON `kamei` trong findings (migrate tự động); `upsert_commit_features` (INSERT OR REPLACE, idempotent) + `features_for_commit`.
- **Luồng:** `relabel_commit` join từ bảng (không tự tính) → mọi row của commit mang cùng block kamei. `cmd_scan` tính 1 lượt TRƯỚC pool worker. Lệnh mới **`features <repo> [--branch]`** backfill DB cũ + relabel nhúng + in sanity min/avg/max. `pipeline` không đổi bước. Export: label.json decode kamei; summary.json thêm block `kamei`.
- **Config:** `ORCH_KAMEI` (mặc định 1), `ORCH_FIX_KEYWORDS`.

### Verify
- Test synthetic (repo git tạm, 8 commit/2 author/2 subsystem/rename/merge/nhánh side): **84/84 assert** — mọi công thức khớp tính tay (kể cả LT cộng dồn qua rename, NUC/state nhặt cả commit nhánh side, merge không emit).
- Backfill thật train-ticket: 39/39 commit, 3-4s; idempotent (chạy 2 lần vẫn 39 hàng).
- Spot-check `e5ae0c3a` (Release 0.2.0): NF=193/LA=3554/LD=2027 khớp `git show --numstat`; EXP=0 khớp (author lần đầu); fix=1 đúng (body chứa nhiều dòng "fix").
- Smoke `scan --max 3` (DB tạm): kamei tự tính + nhúng sẵn vào findings ngay khi scan.
- Docs: GUIDE.md §2 (lệnh features) + §3.1b (bảng đặc trưng + env).

---

## Phiên 2026-07-01 — BƯỚC 2 (tầng đắt) + CROSS-TIER CONSENSUS + export

Phiên dài, hoàn tất phần lớn "não" của dataset. Tóm tắt việc đã làm (chi tiết ở overview trên):

### Tầng đắt — cả 3 tool THẬT (validated trên commit 350f6200, build dùng chung ~14s)
- **CodeQL** (`orch-codeql:2.25.6` = maven+JDK8+bundle): DB create trace `mvn compile` (29s) → analyze → SARIF → CWE. Chẩn đoán chi phí: analyze là nút thắt (~20' code-scanning). **Suite tối giản** `minimal-java.qls` (10 query, bake image) → 6.7'/commit. Công tắc `USE_CODEQL` (`--codeql 0/1`).
- **FindSecBugs** (`orch-findsecbugs:1.14.0`): bytecode → SpotBugs XML → CWE (BugPattern.cweid), path glob. **7s** ⚡.
- **SonarQube** (`sonarqube:lts-community` + scanner): server singleton, headless (đổi pw+token QUA API), scanner + `sonar.java.libraries=/m2 jar` (BẮT BUỘC), poll CE, issues+hotspots, CWE regex từ mô tả rule. **22s**.
- Gotcha: `vm.max_map_count>=262144` (user sudo, reset khi reboot); admin/admin chỉ dùng lần đầu → `SONAR_ADMIN_PW`.

### Cross-tier consensus (mảnh nhãn chất lượng) — theo `RULE_GAN_NHAN.md`
- **Kiến trúc lưu RAW → recompute**: bảng `raw_findings` (từng-tool); `consensus/labeler.relabel_commit` gộp cụm rẻ+đắt → nhãn. Analyze đắt thêm raw đắt + relabel → nhãn TỰ nâng cấp (candidate→gold).
- `consensus/tiers.py` (tier + eligible theo năng lực); `matcher.vote()` tier-aware → **gold/silver/candidate**; config `GOLD_MIN_EXPENSIVE/GOLD_ALLOW_1EXP_1CHEAP/SILVER_MIN_CHEAP`. Trường mới: label/n_cheap/n_expensive/eligible/tier=mixed.
- Verify: ladder 6 ca đúng; semgrep(candidate) → +codeql+findsecbugs = **gold** (1 dòng, không nhân đôi).

### (B) output THÔ + (C) export
- Mọi wrapper trả `raw_out` → bảng `raw_output` (sarif/xml/json audit 100%).
- Lệnh `export`: mỗi commit 1 thư mục — `<tool>.raw.<ext>` + `<tool>.findings.json` + `label.json` + `summary.json`. Số tool KHÔNG hardcode (7/8 tuỳ CodeQL).

### #1 Loại node_modules/vendored/generated
- `EXCLUDE_PATH_PATTERNS` + `is_excluded_path`; áp vào code_files/scannable_files + finding-level (secret tool quét whole-diff).

### #2 Chạy pipeline THẬT end-to-end — XONG ✅ (lần ráp tất cả đầu tiên)
- `scan --max 50`: 39 commit, 2815 cụm, **node_modules=0** (lọc chuẩn), 317s.
- `select`: 29 universe → **20 buggy** + 9 clean.
- `analyze --codeql 0` (FindSecBugs+Sonar, 2 worker): **26 phút**, 19 done + **1 build_failed** (fa8d9efb khổng lồ — xử đúng, không crash). FindSecBugs tb 64.7s (build đa-module), Sonar 14.6s.
- `export`: 39 thư mục (mỗi commit: <tool>.raw + <tool>.findings + label + summary).
- **DATASET (cross-tier THẬT):** candidate 2808 · silver **3571** · gold **4** · tier {cheap 2811, expensive 3568, mixed 4}.
  - gold (E1+C1): CWE-352 CSRF (semgrep+sonar) @ SecurityConfig; weak-crypto CWE-326/330 (bearer+sonar).
  - **Phát hiện thật:** gold ÍT vì FindSecBugs & Sonar phủ RỜI NHAU (FindSecBugs→CWE-117 CRLF nhiễu 1118; Sonar→CWE-352/942 CORS) → hiếm trùng cụm → ít E≥2. **CodeQL (dataflow) sẽ trùng nhiều hơn → tăng gold.** FindSecBugs nhiễu (CWE-117 = 1118 finding, phần lớn FP log-injection).
- DB backup: dataset_prev(run1)/dataset_run2/dataset_run3.sqlite.

### Tài liệu tạo/ cập nhật
`RULE_GAN_NHAN.md` (quy tắc gán nhãn), `EXECUTION_FLOW.md` (luồng + time đo), `EXPENSIVE_TIER_REPORT.md` §5b/§5c/§5d/§8, `docker/{codeql,findsecbugs}/Dockerfile` + `minimal-java.qls`.

### #3 GOLD-negative — CODE XONG ✅ nhưng lộ vấn đề phương pháp
- Code: `select --include-clean` (add_selected incremental), `negative_level` (verified/cheap-clean), export negatives.json, `build.py` skip build khi 0 module Java.
- Chạy 9 clean commit: **0 verified-clean, 9 "FN→positive"** — NHƯNG phần lớn là **nhiễu CWE-117 (CRLF log-injection) của FindSecBugs** (flag mọi `log(userInput)`). → **verified-clean BẤT KHẢ nếu chưa lọc nhiễu FindSecBugs.** Negative còn 10 cheap-clean (commit docs).
- ⚠️ **Chặn tiếp theo = LỌC NHIỄU FindSecBugs** (CWE-117/high-FP rule). Raw đã lưu → relabel không cần quét lại.

### Lọc nhiễu + verified-clean theo finding_in_diff — XONG ✅
- `config.NOISE_CWE` (mặc định CWE-117) + `labeler._is_noise`: lọc raw khỏi consensus (raw giữ nguyên).
- **Lệnh `relabel <repo>`**: gán nhãn LẠI từ raw (git show, KHÔNG quét lại) — **30s/39 commit**. CWE-117: silver 4566→3283.
- **`negative_level` theo `finding_in_diff=1`** (commit TẠO lỗi): nợ cũ (in_diff=0, tool đắt quét cả file phơi ra) KHÔNG tính not-clean. → negatives: **verified-clean 10 + cheap-clean 10**; 4 clean-commit thành POSITIVE (FN thật: mass-assignment CWE-915 / CORS commit tạo).
- **Bài học lớn:** tool đắt quét WHOLE-FILE → phơi nợ cũ; phải dùng `finding_in_diff` để phân "commit TẠO" vs "có sẵn". Đây là trục phân positive/negative đúng.

### Fleiss' kappa — XONG ✅ (lệnh `kappa`)
- `kappa.py` + cli `kappa`: item=cụm, rater=tool đủ-năng-lực-&-đã-chạy (từ raw_output), yes/no. Tính κ tổng+category+nhóm-CWE. Không quét lại.
- **KẾT QUẢ: κ TỔNG = -0.32 (ÂM)** = tool phủ **RỜI NHAU** (co-location dưới ngẫu nhiên). secret -0.11 (ít rời nhất, gitleaks+trufflehog trùng hơn); sql_injection/xss ~-0.45 (rời nhất). → tool BỔ SUNG nhau, đồng thuận hiếm → giải thích gold=4. Là tín hiệu sức khoẻ.
- Lưu ý: κ âm bị chi phối bởi cụm 1-tool (phần lớn); clustering ±3 dòng có thể hơi chặt (tool tìm cùng vuln nhưng lệch dòng/CWE → không gộp). Có thể tinh chỉnh sau.

### Việc kế tiếp
Chạy `--codeql 1` tăng gold (CodeQL trùng semgrep/sonar hơn → κ code bớt âm); GOLD set kiểm tay đo precision; (tuỳ) nới clustering / lọc thêm FP.

---

## Phiên 2026-06-28 (c) — Pilot LẠI sau fix trufflehog + skip-churn (DỮ LIỆU SẠCH HƠN NHIỀU)

`train-ticket --max 50`, 4 worker. **26 commit quét, 3 bỏ (>100 file), 1370 cụm, ~3–4 phút** (vs ~9' tuần tự). DB cũ giữ ở `data/dataset_prev.sqlite`.

| Chỉ số | CŨ (over-scan) | MỚI (đã fix) | Ý nghĩa |
|---|---|---|---|
| findings(cụm) | 2951 | 1370 | giảm do bỏ 3 commit khổng lồ + hết over-scan |
| commit có finding | 29 | 14 | nhiều commit nhỏ thực ra 0 finding |
| vuln | 3 | **0** | cả 3 vuln cũ NẰM TRONG commit khổng lồ bị skip (xem dưới) |
| secret total | 161 | **1** | **145/161 là node_modules `.d.ts` bị trufflehog over-scan gán nhầm** (url.d.ts 87×!) → fix xoá sạch |
| đóng góp trufflehog | 145 | **0** | 0 vì secret thật đều ở commit khổng lồ (skip); commit thường không thêm secret |
| infra noise | 2558 (86%) | 1334 (**97%**) | semgrep p/default vẫn spam CWE-732/250 ở Dockerfile/yml |
| finding_in_diff=1 | 360 | 29 | lỗi commit-này-tạo rất ít; còn lại là nợ cũ |

### Kết luận
- **Fix trufflehog đã được CHỨNG MINH bằng dữ liệu:** 161→1 secret; 145 "secret" cũ là cùng vài file node_modules nhân bản (url.d.ts 87×, http/https.d.ts 29× mỗi) — đúng dấu hiệu over-scan gán nhầm. Số liệu trufflehog cũ là rác.
- **3 vuln cũ mất là do skip commit khổng lồ** (KHÔNG phải do fix): index.js CWE-798 @ `fa8d9efb`; 2× weak_random CWE-330 @ `7009be65` (268 file). ⚠️ 2 weak_random có thể là lỗi THẬT (bearer+semgrep đồng thuận) → đánh đổi của ngưỡng skip: bulk-commit bị loại cả lỗi thật. Cân nhắc sau.
- **Tầng rẻ vẫn 0 vuln** trên commit thường → tái khẳng định cần TẦNG ĐẮT. 97% còn lại là infra noise.

### Kế tiếp
- **Loại node_modules/vendored/generated** trước khi quét (giảm cả nhiễu lẫn chi phí).
- Cân nhắc lại ngưỡng skip (đừng mất lỗi thật trong bulk-commit) — vd chỉ skip file vendored thay vì cả commit.
- Bước 2: tầng đắt (CodeQL/FindSecBugs/Sonar).

---

## Phiên 2026-06-28 (b) — Song song CẤP COMMIT + ngưỡng bỏ commit khổng lồ

**Vì sao:** quét tuần tự từng commit là nút thắt khi scale nghìn commit. (Đã bàn & loại phương án Java virtual-thread: workload CPU/container-bound, chặn ở số core chứ không số thread — vthread vô ích. Mô hình đúng = worker-pool *bounded* ≈ vCPU, song song ở CẤP COMMIT.)

### Đã làm
- **`repo_pool.py` (RepoPool):** pool K clone độc lập qua `git clone --local --no-checkout` (object hardlink → ~0 đĩa/0.3s/clone). KHÔNG dùng `git worktree` vì worktree để `.git` là *file* `gitdir:` → mount thư mục lẻ vào container thì tool git-mode (gitleaks/trufflehog) gãy; clone cho `.git` *thư mục thật* → mọi wrapper chạy y nguyên. Mỗi clone tái sử dụng qua nhiều commit (`checkout --detach`).
- **`cli.py` cmd_scan viết lại:** `ThreadPoolExecutor(SCAN_WORKERS)` xử commit SONG SONG; mỗi worker chiếm 1 clone, checkout, chạy **5 tool TUẦN TỰ** bên trong → tối đa SCAN_WORKERS container cùng lúc (bounded, không thrash). Bỏ checkout/khôi-phục HEAD trên main repo (không còn đụng main).
- **`sqlite_store.py` thread-safe:** `check_same_thread=False` + `threading.Lock` bọc mọi ghi.
- **Ngưỡng bỏ commit khổng lồ (yêu cầu người dùng — theo DIFF, không theo kích thước file):**
  - `> MAX_FILES_PER_COMMIT` (mặc định 100) file → bỏ.
  - BẤT KỲ file nào có add>1000 HOẶC del>1000 HOẶC (add+del)>2000 → bỏ.
  - Cả 2 check ở `coarse_filter` (lúc enumerate, dùng numstat có sẵn — HEAD-independent, không checkout).
  - Env: `ORCH_MAX_FILES_PER_COMMIT`, `ORCH_MAX_FILE_ADD_LINES`, `ORCH_MAX_FILE_DEL_LINES`, `ORCH_MAX_FILE_CHURN_LINES`, `ORCH_SCAN_WORKERS`.

### Smoke-test (train-ticket --max 12, 4 worker) — PASS
- 8 commit giữ (commit 983-file `fa8d9efb` bị lọc do >100 file), **3 BỎ QUA** vì đụng file k8s yml >1000 dòng (2248/2012), 5 commit quét thật.
- 161 finding đều hợp lệ (s_line>0, cwe đủ). trufflehog git-mode chạy OK trên clone ⇒ rủi ro `.git`-trong-container đã xử lý. Không lỗi giữa chừng.

### ⚠️ BUG ĐÚNG ĐẮN đã phát hiện & SỬA — trufflehog over-scan
- **Bug:** trufflehog git-mode quét theo MỌI REF (master), KHÔNG theo HEAD. Chỉ dùng `--since-commit <SHA>~1` → quét cả dải `<SHA>..master` rồi gán nhầm hết về `commit_id`. Đã kiểm: detach tại OLD vẫn báo secret của hậu duệ `fa8d9efb`. **Tồn tại từ thiết kế cũ** → dữ liệu trufflehog pilot trước (145) bị nhân bản/gán sai.
- **Sửa:** thêm `--branch <SHA>` (giới hạn reachable-từ-SHA) kèm `--since-commit <SHA>~1` → quét ĐÚNG 1 commit. Kiểm qua wrapper: scan FA→5 finding đều ∈ changed; scan OLD→0 (hết gán nhầm).
- **Tài liệu mới:** `SCAN_MECHANISM.md` — cơ chế scan từng tool + 6 bất biến đúng đắn (I1–I6) + bằng chứng + giới hạn.

### Kế tiếp (chưa làm)
- **Chạy lại pilot** (số liệu trufflehog cũ KHÔNG còn tin được sau fix) + đo throughput vs ~9' tuần tự.
- Loại trừ `node_modules`/vendored trước khi quét (trufflehog FP trong `@types/node/*.d.ts`).
- Đòn bẩy tiếp: **container ấm** (docker exec) + **cache theo blob-sha**.

---

## Phiên 2026-06-28 — Kết quả pilot tầng rẻ (sau CWE-grouping + category + song song)

**Pilot:** `train-ticket --max 50` → 29 commit giữ lại, 2951 cụm, chạy ~9 phút (19:20→19:29). Song song hoá 5 tool/commit OK, không lỗi giữa chừng, HEAD khôi phục đúng.

### Số liệu chính
- **Nhãn:** vuln=3, candidate=2948, clean(negative file)=1452 (trên 1626 file quét).
- **3 vuln (≥2 tool đồng thuận):**
  - `ts-ui-dashboard/.../index.js:18` — CWE-798 hardcoded_secret — **bearer+horusec**.
  - 2× `old-docs/.../*.java` — CWE-330 weak_random — **bearer+semgrep** ← *thắng nhờ CWE-grouping* (bearer+semgrep cùng quy về nhóm `weak_random`).
- **Category (tách nhiễu infra):** infra=2558 (**86.7%** — toàn permissions CWE-732 + privilege CWE-250 từ Dockerfile/k8s), secret=161, info=130, code=36, crypto=36, other=30.
  - → **Bỏ infra-noise** thì chỉ còn **233** candidate code/secret/crypto đáng xét. code thật: sql_injection=11, xss=12, csrf=6, code_injection=3, path_traversal=2.
- **finding_in_diff:** chỉ 360/2951 (12%) là do commit này tạo; 2591 là nợ cũ. Lọc `finding_in_diff=1` cắt còn 360.
- **secret verified:** **0/145 verified** (toàn unverified — train-ticket dùng cred test/example, tín hiệu secret yếu).
- **Đóng góp tool:** semgrep=2590, bearer=179, trufflehog=145, horusec=40, **gitleaks=0** (đúng kỳ vọng: gitleaks chặt hơn, loại key example).

### Kết luận
- 3 cải tiến hoạt động: **song song** (~9'), **CWE-grouping** (tạo ra 2 vuln weak_random bearer+semgrep), **category** (tách sạch 86.7% infra noise → còn 233 candidate thật).
- **Tầng rẻ vẫn chỉ ra 3 vuln** → RE-XÁC NHẬN thiết kế phễu: cheap-tier = candidate generator, consensus code-vuln thật phải nhờ **tầng đắt**. Giá trị tầng rẻ là khả năng *cắt nhiễu* (category + finding_in_diff + verified) trước khi thả tool đắt.

---

## Phiên 2026-06-27

### Đã xong
- Đọc & nắm `TOOL_IDEA_CONTEXT.md`.
- **Quyết định mới:** dataset lưu THẲNG trên Persistent Disk VM, **bỏ GCS bucket** (đã cập nhật vào `TOOL_IDEA_CONTEXT.md`, mục §8/§9/§12).
- **Setup môi trường VM (Ubuntu 22.04, x86_64):**
  - Git 2.34.1 (có sẵn).
  - Cài Docker Engine 29.6.1 qua `get.docker.com` (daemon active).
  - Docker Compose plugin v5.2.0.
  - Thêm `scanner` vào nhóm `docker` (`usermod -aG docker`); xác nhận chạy được qua `docker run hello-world`.
- Viết `CLAUDE.md` + tạo `SESSION_CONTEXT.md` (file này).

### Đang dở / lưu ý
- ⚠️ Tiến trình Claude Code hiện tại vẫn giữ nhóm cũ (chưa có `docker` trong `id`) → tạm thời gọi docker qua `sg docker -c "..."`. Sửa triệt để: thoát claude → SSH login mới → chạy lại `claude`.

### Đã xong (Bước 1 — skeleton)
- `git init` + commit "init". Cấu trúc `src/orchestrator/` (stdlib-only, không cần pip).
- `schema.py`: `RawFinding` + `DatasetRow`, hàm `validate()` ÉP `cwe` không rỗng + `s_line>0` (yêu cầu người dùng). `normalize_cwe()`.
- `enumerate_commits.py` (Tầng ①): clone/update, list commit, `get_commit_info`, `coarse_filter` (bỏ merge/docs/non-code). Test trên repo local OK.
- `tools/`: `base.ToolWrapper` + `docker_run` (tự bọc `sg docker -c` khi ORCH_DOCKER_SG=1); `gitleaks.py` (map cứng CWE-798), `semgrep.py` (p/security-audit + p/secrets, lấy CWE từ metadata).
- `consensus/matcher.py` (Tầng ⑥): gộp cụm `(file, CWE giao nhau, |s_line|≤W)`, vote → confidence = n_agree/n_ran, silver_label. Test 2-tool-1-cụm OK.
- `storage/sqlite_store.py`: ghi SQLite, cwe/agreeing_tools → JSON. Round-trip OK.
- `cli.py`: lệnh `enumerate` (không cần Docker) + `scan` (full phễu). `README.md`.
- **Unit test (không Docker) PASS:** normalize_cwe, validate ép cwe/s_line, consensus, enumerate local, storage.

### Bổ sung schema (yêu cầu người dùng — cùng phiên)
- `s_detail_line: list[int]` — các dòng cụ thể gây lỗi (BẮT BUỘC; default = dải s_line..e_line; consensus gộp union các tool).
- `diff_parsed: {"added":[[ln,txt]],"deleted":[[ln,txt]]}` — parser `git show --unified=0` trong `enumerate_commits.get_file_diffs()`.
- `code_before_url`/`code_after_url` — permalink GitHub theo SHA (`blob_url()`), luôn lưu (rẻ).
- `code_before`/`code_after` — toàn văn file, TUỲ CHỌN (mặc định TẮT; bật `ORCH_STORE_FULL_FILE=1`) để khỏi nặng DB.
- Đã thêm cột tương ứng vào SQLite + test pass (diff parser, s_detail_line, urls, round-trip).
- ⚠️ Schema SQLite đổi → xoá `data/dataset.sqlite` cũ trước khi chạy lại (CREATE IF NOT EXISTS không tự migrate).

### Red-team + hướng A (cùng phiên) — ĐÃ XONG
- Red-team output: nêu các lỗ hổng (gán nợ cũ cho commit, thiếu negative, quét toàn cây, leakage commit_message, overclaim "ground truth", thiếu version pin, correlated errors, CWE-intersection làm vỡ consensus, dedup...).
- **Hướng A (3 fix):** (1) quét diff-scoped (semgrep file đổi, gitleaks git-mode); (2) `finding_in_diff`; (3) nhãn `vuln/candidate/clean` theo `VOTE_THRESHOLD` + bảng `scanned_files` (mẫu số/negative).

### Hoàn thiện tầng rẻ 5 tool (theo plan đã duyệt) — ĐÃ XONG
- Semgrep `p/default`+`p/secrets` (p/security-audit bỏ sót CWE-89).
- Wrapper mới: `trufflehog` (git-mode `--since-commit`, JSONL, CWE-798), `bearer` (quét từng file đổi, lấy cwe_ids; Bearer trả filename='.' nên gán path đã truyền), `horusec` (`-D` chỉ HorusecEngine → độc lập semgrep/gitleaks; map CWE thận trọng theo language=Leaks→798 + từ khoá; bóc path tạm `.horusec/<uuid>/`; copy file đổi vào temp để diff-scope).
- `canon_path` (base.py) khớp path tool ↔ key diff. `image_digest()`+`version()` → bảng `run_meta` (tái lập).
- **Smoke-test Java PASS:** SQLi→vuln 3-tool (bearer/horusec/semgrep), secret→vuln 3-tool (horusec/semgrep/trufflehog), Hello.java→clean, docs lọc thô. `finding_in_diff=1`.
- Commit `bc7148e`.

### Tối ưu Bearer (perf) — ĐÃ XONG
- Pilot lần 1 chậm: Bearer chạy mỗi-file-một-container (commit 14 file = 14 container, ~10 phút/commit).
- Sửa: Bearer copy file đổi vào 1 temp dir + chmod 0755 (container non-root) → quét cả thư mục 1 lần/commit. ~35s/commit. Commit perf fix.

### KẾT QUẢ PILOT train-ticket --max 50 (DB `data/dataset.sqlite`)
- 50 yêu cầu → **29 commit thực quét** (còn lại merge thật/docs bị lọc; lưu ý: squash-merge "(#xxx)" có 1 parent nên KHÔNG bị lọc, vẫn quét).
- **2951 findings(cụm) | clean files 1452.**
- **Nhãn: candidate 2948 / vuln 3** (n_tools_agree: 1→2948, 2→3). Consensus ~0.1%.
- finding_in_diff: 0→2591 (88% là nợ cũ, không trên dòng commit sửa), 1→360 (12%).
- Đóng góp tool: semgrep 2590 (88%), bearer 179, trufflehog 145, horusec 40, **gitleaks 0**.
- Top CWE: CWE-732 (1692) + CWE-250 (865) = **86% là CWE hạ tầng** (Dockerfile/k8s perm) từ semgrep p/default. CWE-798 161, CWE-89 chỉ 9, CWE-79 12.
- Secret CWE-798: trufflehog 145 (đứng MỘT MÌNH hết), horusec 14 (một mình), bearer+horusec 1. → các tool secret KHÔNG chồng nhau.
- 3 vuln đều in_diff=0, giá trị thấp (1 JS asset, 2 CWE-330 trong old-docs).

### CHẨN ĐOÁN (vì sao consensus ~0)
1. Coverage gần như rời nhau: semgrep ngập CWE hạ-tầng (732/250) không tool nào khác sinh; trufflehog ngập secret chưa-verify không ai chứng thực.
2. gitleaks=0 KHÔNG phải bug — quét OK ("no leaks found"), chỉ chặt hơn trufflehog (loại noise/test-cred). Tức consensus filter ĐANG làm đúng việc (không tin mù 145 hit của trufflehog).
3. → **Khẳng định triết lý PHỄU: tầng rẻ là BỘ SINH CANDIDATE (recall cao, precision thấp), KHÔNG phải bộ gán nhãn cuối.** `vuln` thật phải đến từ tầng đắt (CodeQL/FindSecBugs dataflow) chứng thực semgrep/bearer.

### Kế tiếp (đề xuất — chờ user chốt ưu tiên)
1. **Giảm noise để candidate set dùng được:** trufflehog gắn cờ `verified` (lọc unverified); semgrep gắn `category` (infra/code/secret) để SQLi/XSS không bị 732/250 nhấn chìm.
2. **Chuẩn hoá CWE theo cây MITRE** trước khi cluster (gộp CWE anh-em) — tăng đồng thuận ít ỏi đang có.
3. **Song song hoá intra-commit** (ThreadPoolExecutor 5 tool) — user đề xuất; tối ưu throughput, đặc biệt cho tầng đắt.
4. **Bước 2 — tầng đắt** (CodeQL/FindSecBugs/Sonar, build Maven): nguồn consensus thật cho code-vuln.
5. Backlog red-team: commit_role, selection_reason, finding_uid+dedup, gold_verified, redact secret, lọc finding_in_diff=1 cho dataset "commit introduced".
2. Tinh chỉnh: per-commit checkout có thể chậm; cân nhắc quét trên diff thay vì cả cây.
3. Bước 2: thêm tool tầng đắt (CodeQL/FindSecBugs/Sonar) + adapter SARIF.
