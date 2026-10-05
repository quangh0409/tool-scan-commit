# CODE_MAP — Bản đồ mã nguồn `tool-scan-commit` (cho phiên sau + phụ lục luận văn)

> Cập nhật 2026-10-05 (dev `73401ee`). Mỗi file một dòng: **vai trò · hàm/lớp public chính · ai gọi**.
> Hợp đồng giao diện: `CONTRACTS.md` (§1 trạng thái, §2 profile, §3 progress, §4 schema, §6 export, §7 runner/registry,
> §8 preflight, §9 API GUI, §11 CLI, §12 hiệu chỉnh). Quy tắc làm việc: `CLAUDE.md`. Người dùng cuối: `HUONG_DAN_GUI.md`.

---

## 0. Sơ đồ luồng (chữ)

```
                 GUI (pywebview / trình duyệt)                       CLI thuần
  Wizard 5 bước ──► profile.json (CONTRACTS §2) ◄──────────── `--profile F` / argv
        │  POST /api/run/start
        ▼
  gui/api_runs.run_start ──► runner.start(profile, run_id, work)   [tiến trình TÁCH RỜI, env ORCH_*/SECJIT_*]
        │                        │  python -m orchestrator.cli pipeline --profile F
        │                        ▼
        │              cli.cmd_pipeline:  scan ─► select ─► analyze ─► relabel ─► kappa ─► export
        │                 (tầng rẻ)     (rẻ→đắt)  (expensive_runner)  (labeler)  (kappa)  (export_dataset)
        │                        │ progress.emit()            │ SQLiteStore (WAL + <db>.lock)
        │                        ▼                             ▼
        │              <work>/<run_id>/progress.jsonl        dataset_<slug>_<branch>_<date>.sqlite
        │  GET /api/run/{id}/progress (SSE, gui/server.py) ◄──┘
        ▼
  Dashboard (screens/dashboard.js)  ── Dừng an toàn = stop-file (progress.should_stop) · cưỡng bức = runner.stop(force)
                                        ──► cli stop-cleanup (control.py: container theo label orch.run, reset-claims)
  registry (runs.json) ◄── runner/api_runs cập nhật status running|stopped|done|failed|interrupted

  export_dataset.export_all ─► export_<slug>_<branch>_<date>/ {dataset.jsonl, commits.jsonl, run_manifest.json,
                                 negatives.json, SHA256SUMS, <sha12>/raw}
        │                       │                              │
        ▼                       ▼                              ▼
  compare.compare(A,B)   scripts/verify_run.py(db,export)   scripts/results_report.py(A,B) ─► RESULTS.md
  (cluster_key, explained_by)   (17 mục PASS/FAIL)            (cấu hình/digest · phễu · compare · verify · κ · kết luận)
  review.sample/next_item/verdict/close ─► gold_review/gold_sample ─► evidence.validation trong export
```

---

## 1. `src/orchestrator/` — lõi pipeline (stdlib-only, KHÔNG pip)

| File | Vai trò | Hàm/lớp public chính | Ai gọi |
|---|---|---|---|
| `cli.py` | Entrypoint mọi subcommand (§11); mỗi `cmd_*` = 1 tầng; `--profile` áp env trước argparse | `main`, `build_parser`, `cmd_enumerate/scan/select/analyze/relabel/kappa/features/export/pipeline/estimate/stats/verify/sensitivity/compare/stop/stop_cleanup/reset_claims/clean/review/batch/rescan/diagnostics`, `apply_profile`, `profile_argv`, `_scan_one_commit`, `rescan_commit` | `python -m orchestrator.cli`, `packaging/launcher`, `runner.process`, GUI (`api_common.run_cli/spawn_cli`) |
| `config.py` | Mọi núm `ORCH_*` đọc lúc import; `reload()` khi profile đặt env muộn | `reload`, `params_v1`, `experiment_info`, `effective_env`, `ensure_dirs`; hằng `LINE_WINDOW`, `GOLD_*`, `NOISE_CWE`, `EXPENSIVE_TOOLS`, `USE_CODEQL`, `SONAR_HOST_PORT`, `BUILD_TIMEOUT`… | mọi module |
| `profile.py` | `profile.json` = 1 run tái lập; v1 khoá, experiment cần lý do | `default_profile`, `validate`, `load`, `save`, `to_env`, `to_cli_args`, `to_shell`, `from_env_defaults`, `ProfileError` | cli, GUI wizard/api_settings, runner, estimate |
| `progress.py` | `progress.jsonl` + stop-file hợp tác (§3) | `emit`, `should_stop`, `run_id`, `read`, `enabled` | cli (scan/relabel), expensive_runner, batch, server SSE, runner.attach |
| `keys.py` | `canon_repo`, `repo_slug`, **`cluster_key`** = sha256(repo\|commit\|file\|cwe_group\|s_line//W)[:32] | `canon_repo`, `repo_slug`, `cluster_key` | export, review, compare, api_results, repo_pool, repo_probe |
| `schema.py` | Dataclass `RawFinding` (1 tool/1 chỗ, `validate()` ép CWE + s_line) và `DatasetRow` (1 cụm) | `RawFinding`, `DatasetRow`, `normalize_cwe` | tools/*, consensus, storage |
| `enumerate_commits.py` | Tầng ①: clone/fetch (`owner__repo`, kiểm origin), liệt kê commit theo scope, lọc thô, diff parse | `clone_or_update`, `resolve_rev`, `verify_sha`, `scope_dict`, `list_commits`, `get_commit_info`, `get_file_diffs`, `coarse_filter`, `enumerate_repo`, `blob_url`, `is_excluded_path`, `ScopeError` | cli, expensive_runner, labeler, kamei, sensitivity |
| `select_commits.py` | Tầng ⑤: buggy (có CWE) → hàng đợi đắt; clean mẫu 1:N (`CLEAN_PER_BUGGY`) | `classify`, `select` | cli.cmd_select |
| `expensive_runner.py` | Tầng đắt: claim nguyên tử → checkout pool → build 1 lần → FSB/Sonar/CodeQL → relabel; trạng thái §1; 3 `infra_error` liên tiếp → dừng; `run_meta` tier=analyze | `analyze(repo, workers, dry_run, tools, branch) -> {counts, stopped, stop_reason, run_meta_id}` | cli.cmd_analyze |
| `repo_pool.py` | K clone `--local --no-checkout` dùng chung object; checkout theo SHA; kiểm origin (D4) | `RepoPool(main, size, repo)`, `.acquire/.release/.checkout/.cleanup`, `rmtree_force`, `verify_origin`, `OriginMismatch` | cli.cmd_scan, expensive_runner, control.clean |
| `kamei.py` | 14 đặc trưng JIT (Kamei 2013) từ 1 lượt `git log --numstat`, chỉ nhìn quá khứ | `compute_features(repo_dir, commit_ids, rev)` | cli.cmd_scan/cmd_features |
| `kappa.py` | Fleiss' κ tổng / category / cwe_group / cặp tool (rater = tool đủ năng lực đã chạy; bỏ `raw_output.fmt='error'`) | `fleiss`, `collect`, `compute_all`, `save_all` | cli.cmd_kappa, stats, sensitivity |
| `export_dataset.py` | Export mỗi run 1 thư mục (`_2`, `_3` nếu đích không rỗng); `cluster_key` + `evidence`; manifest §6; `SHA256SUMS` | `export_all(store, out, profile, run_id)`, `write_merged`, `build_manifest`, `write_sums`, `enrich_row`, `resolve_out_dir`, `params_v1_from_config` | cli.cmd_export, api_results.export, scripts/merge_export, relabel_gold_w7 |
| `review.py` | Kiểm tay MÙ gold: mẫu phân tầng theo seed, mục mù, verdict, đóng phiên (Wilson 95 %, Cohen κ, adjudicated) | `sample`, `next_item`, `verdict`, `close`, `summary`, `validation_of`, `wilson`, `cohen_kappa`, `allocate`, `main` (CLI độc lập) | cli.cmd_review, api_review, export (validation), build_gold_set |
| `stats.py` | Overview 1 DB (§9): phễu, nhãn, by_cwe_group, κ, coverage, precision kiểm tay, **limits** tự sinh; xuất json/csv/latex | `overview(db, run_id)`, `build_limits`, `render`, `write`, `open_ro` | cli.cmd_stats, api_results.overview/export, results_report |
| `compare.py` | So A/B theo `cluster_key` (export dir hoặc DB); lệch "giải thích được" nếu commit ∈ manifest `tool_timeout/infra_error/skipped/build_failed` | `compare(a, b)`, `load_side`, `to_markdown` | cli.cmd_compare, results_report |
| `sensitivity.py` | Lưới tham số (W × 1E+1C × noise) relabel trên **bản sao** DB → `sensitivity.json/.md` | `parse_grid`, `configs`, `run(db, out, grid, repo, relabel_fn)`, `to_markdown` | cli.cmd_sensitivity, scripts/relabel_gold_w7 |
| `estimate.py` | Ước tính thời gian/đĩa từ profile + `speed.json` | `estimate(profile)`, `load_speed`, `count_commits`, `format_text` | cli.cmd_estimate, api_real.estimate |
| `control.py` | stop (stop-file) · stop-cleanup (container theo label `orch.run`, network, reset-claims) · clean (plan/apply, từ chối khi run đang dùng) | `stop`, `stop_cleanup`, `reset_claims`, `clean_plan`, `clean_apply`, `parse_items`, `pid_alive`, `kill_pid` | cli, runner.stopper, api_settings.clean |
| `batch.py` | Hàng đợi batch tuần tự nhiều profile (không registry) | `load_queue`, `run`, `format_text` | cli.cmd_batch |
| `diagnostics.py` | Gói chẩn đoán ZIP (log, run_meta, docker info, profile, preflight) — redact secret | `collect`, `redact_env`, `redact_text`, `format_text` | cli.cmd_diagnostics, api_runs.diagnostics |

### `src/orchestrator/storage/`
| File | Vai trò | Hàm public chính | Ai gọi |
|---|---|---|---|
| `__init__.py` | `InfraError` (đĩa đầy / disk I/O → runner dừng) | `InfraError` | sqlite_store, expensive_runner |
| `sqlite_store.py` | Toàn bộ truy cập SQLite; schema `user_version=2` + migrate 0/1→2; WAL + `busy_timeout` + lock-file `<db>.lock` {pid, run_id}; `readonly=True` → `mode=ro` không lock | `SQLiteStore(path, readonly)`; findings: `insert_rows`, `replace_findings_for_commit`, `findings_for_commit`, `findings_rows`; raw: `insert_raw`, `insert_raw_output` (fmt=`error` → `scan_tool_errors`), `raw_for_commit`, `raw_output_for_commit`; hàng đợi: `claim_next_commit`, `set_commit_status`, `reset_stale_claims`, `reset_claims(run_id)`, `reset_expensive_raw`, `add_selected`, `replace_selected`, `selected_rows`; đắt: `insert_expensive_run`, `n_expensive_ok`, `update_n_expensive_ok`, `negative_level`, `commits_by_expensive_status`, `tool_errors_all`; meta: `insert_run_meta(tier, **f)`, `finish_run_meta`, `run_meta_rows`, `save_kappa`, `kappa_rows`; review: `replace_gold_sample`, `gold_sample_rows/ids`, `gold_review_rows`, `upsert_gold_review`, `gold_review_verdicts`, `verified_clean_commits`; Kamei: `upsert_commit_features`, `features_for_commit`, `commit_features_rows`; module: `pid_alive`, `read_lock`, `lock_path_for` | mọi tầng; GUI mở `readonly=True` |

### `src/orchestrator/tools/` — tầng rẻ (quét diff, không build; mỗi tool 1 container)
| File | Vai trò | Public | Ai gọi |
|---|---|---|---|
| `base.py` | `docker_run` (tự gắn `--label orch.run=<run_id>`, `sg docker` khi `ORCH_DOCKER_SG`), `canon_path`, phân loại lỗi hạ tầng, **`_guard_scan`** bọc mọi `ToolWrapper.scan` (lỗi → `raw_out[0]=("error", json)` → `scan_tool_errors`), digest/version/git sha | `ToolWrapper`, `docker_run`, `canon_path`, `classify_failure`, `classify_exception`, `is_infra_text`, `image_digest`, `docker_version`, `orchestrator_git_sha`, `app_version`, `error_record` | tools/*, tools_expensive/*, build, export, expensive_runner, cli |
| `gitleaks.py` | git-mode `-1 <sha>` → secret (CWE-798) | `GitleaksWrapper` | cli (`cheap_tool_classes`) |
| `trufflehog.py` | git-mode `--branch <sha> --since-commit <sha>~1` (đúng 1 commit) → CWE-798 (+verified) | `TrufflehogWrapper` | cli |
| `semgrep.py` | copy file đổi vào temp dir (giữ cấu trúc, `.semgrepignore` rỗng) → `semgrep scan /src` (`p/default`, `p/secrets`) — không truyền file vào argv (WinError 206) | `SemgrepWrapper`, `stage_changed_files` | cli |
| `bearer.py` | temp dir → `bearer scan` JSON (cwe_ids) | `BearerWrapper` | cli |
| `horusec.py` | temp dir → `horusec start -D` (chỉ engine nội bộ); CWE map từ từ khoá | `HorusecWrapper` | cli |

### `src/orchestrator/tools_expensive/` — tầng đắt (cần build Maven)
| File | Vai trò | Public | Ai gọi |
|---|---|---|---|
| `base.py` | `BuildContext` (status `ok|skipped|build_failed|infra_error|tool_timeout`, `classes_dirs`, `image`), `ExpensiveTool`, `ToolError`, `run_as_user` | như tên | build, codeql, findsecbugs, sonar, expensive_runner |
| `build.py` | `changed_modules` (leo tới pom gần nhất), `detect_jdk` → image temurin 8/11/17/21, `build_commit` (`-pl <mods> -am`, cache `.m2cache`; 0 module → `skipped`; rc 125/127 → `infra_error`) | `build_commit`, `changed_modules`, `maven_image_for`, `detect_jdk` | expensive_runner |
| `findsecbugs.py` | SpotBugs+FSB trên `target/classes` → XML → CWE từ `BugPattern.cweid`; XML 0 byte → `ToolError` | `FindSecBugsTool` | expensive_runner |
| `sonar.py` | Server `orch-sonar-<run_id>` + network theo run; scanner cùng network; `sonar.java.libraries=/m2` bắt buộc; CWE từ mô tả rule | `SonarTool(run_id)`, `.start_server/.stop_server/.scan`, `server_name`, `network_name` | expensive_runner |
| `codeql.py` | `codeql database create` (trace mvn compile) → analyze suite → SARIF → CWE từ tags; tắt mặc định (`USE_CODEQL`) | `CodeQLTool` | expensive_runner |

### `src/orchestrator/consensus/` — gộp cụm + bỏ phiếu (tầng ⑥)
| File | Vai trò | Public | Ai gọi |
|---|---|---|---|
| `cwe_groups.py` | CWE → nhóm đồng thuận (`sql_injection`, `xss`, `csrf`…) + category (`code/secret/crypto/infra/info/other`) | `cwe_group`, `primary_group` | matcher, kappa, review |
| `tiers.py` | tool → tier; tool đủ năng lực theo category (mẫu số) | `tier_of`, `eligible_tools` | storage, matcher, kappa, api_results |
| `matcher.py` | cụm = (file, nhóm-CWE, dòng ±W); vote → `gold/silver/candidate` theo E/C (luật v1) | `cluster_findings`, `vote`, `consensus` | labeler, kappa |
| `labeler.py` | Relabel 1 commit từ raw (lọc nhiễu `NOISE_CWE/RULES`) → enrich diff/in_diff/kamei → ghi đè `findings` | `relabel_commit(store, cid, clone, repo)` | cli (scan/relabel/features/rescan), expensive_runner, sensitivity |
| `normalize/` | stub (chuẩn hoá SARIF) — chưa dùng | — | — |

---

## 2. `gui/` — server HTTP stdlib + web tĩnh (vanilla JS, không CDN)

| File | Vai trò | Public | Ai gọi |
|---|---|---|---|
| `__main__.py` | `python -m gui [--dev] [--mock] [--port] [--no-browser]` | `build_api`, `main` | launcher, tests/gui |
| `server.py` | `ThreadingHTTPServer`, token `X-Token`/`?t=`, tĩnh `web/`, bảng `ROUTES` (36 route) → phương thức API cùng tên, SSE `/api/run/{id}/progress` | `GuiServer`, `GuiHandler`, `ROUTES`, `free_port` | `__main__`, launcher |
| `api_real.py` | Backend thật: gom preflight/runner/registry/estimate/repo_probe + ủy quyền `api_runs/api_results/api_review/api_settings` | `RealApi` | server |
| `api_mock.py` | Backend fixture `gui/fixtures/*.json`, tôn trọng `?state=empty|error|loading|partial` | `MockApi` | server (`--mock`), tests/gui |
| `api_common.py` | Helper: tìm run trong registry, `open_ro`/`open_rw` (readonly không lock), `profile_env`, `run_cli/spawn_cli`, `line_window_of`, `require_db_free` | như tên | api_* |
| `api_runs.py` | `GET /api/runs`, progress, start/stop/resume, diagnostics | `list_runs`, `get_progress_lines`, `run_start`, `run_stop`, `run_resume`, `diagnostics` | api_real |
| `api_results.py` | overview/findings/finding (bằng chứng: diff_lines, tool_messages ±2W, provenance)/commits/export/raw/open/features/relabel | như tên | api_real |
| `api_review.py` | Wrapper `orchestrator.review` (501 nếu thiếu module) | `sample`, `next_item`, `verdict`, `close` | api_real |
| `api_settings.py` | settings.json, dung lượng + dọn (từ chối khi run đang dùng), profile CRUD, lệnh shell | `get_settings`, `set_settings`, `storage`, `clean`, `list/get/save/delete_profile`, `shell` | api_real |
| `repo_probe.py` | `POST /api/repo/check`: ls-remote (không clone), pom.xml, SNAPSHOT, module | `check`, `ls_remote`, `parse_pom`, `histogram` | api_real |
| `errors.py` | `ApiError` → `{error:{code,message,hint}}` | `ApiError`, `not_found`, `bad_request`, `not_supported`, `conflict` | api_* |
| `web/index.html`, `app.css`, `app.js` | Router hash `#/preflight|home|wizard/1..5|run/<id>|results/<id>/<tab>|review/<id>|settings/<tab>`; component `btn, card, table, stepper, toast, dialog, empty, errorBox, skeleton, badgeLabel`; `t()` i18n (`web/i18n/vi.json`, `en.json`) | — | trình duyệt |
| `web/screens/*.js` | Mỗi màn `render(root, ctx)`/`destroy()`: `preflight`, `home`, `wizard1..5`, `dashboard`, `results_overview/findings/commits/export`, `review`, `settings`; `_harness.*` = chạy màn 6–10 với fixture không backend | — | app.js |
| `fixtures/*.json` | Fixture mỗi endpoint (§9) cho mock/Playwright | — | api_mock, tests/gui |

## 3. `runner/`, `registry/`, `preflight/`, `packaging/`

| File | Vai trò | Public | Ai gọi |
|---|---|---|---|
| `runner/process.py` | Tiến trình tách rời (`DETACHED_PROCESS` / `start_new_session`), env §3, `<work>/<run_id>/{pid,meta,run.log,progress.jsonl}`; `attach` phân biệt `interrupted` | `start`, `alive`, `attach`, `build_env`, `build_argv`, `read_pid`, `last_progress`, `derive_status` | api_runs, batch_runner, launcher headless |
| `runner/stopper.py` | stop-file (mềm) hoặc kill cây tiến trình + `cli stop-cleanup` | `stop`, `stop_cleanup` | api_runs.run_stop |
| `runner/batch_runner.py` | Batch có registry: mỗi profile → `runner.start`, chờ pid, cập nhật status | `run_queue`, `main` | cli.cmd_batch (qua `_batch_runner`) |
| `runner/notify.py` | Toast Windows/notify-send, không raise | `toast` | runner, launcher |
| `registry/store.py` | `runs.json` (`SECJIT_HOME` → `%LOCALAPPDATA%\secjit`), ghi atomic, `refresh_status` (pid chết + DB còn `building` → `interrupted`) | `load`, `save`, `get`, `upsert`, `set_status`, `remove`, `refresh_status`, `home`, `path` | api_runs, runner, api_results.export |
| `registry/locks.py` | `<db>.lock` (cùng định dạng với storage) + single-instance GUI (mutex/lock-file) | `db_lock`, `acquire_db_lock`, `release_db_lock`, `lock_status`, `single_instance`, `DbLocked` | api_common, launcher |
| `registry/speed.py` | `speed.json` (cheap s/commit, build cold/warm, fsb, sonar, buggy_ratio) đo từ DB/progress, EMA | `load`, `save`, `update_from_db`, `update_from_progress`, `estimate` | estimate, api_runs, results_report |
| `preflight/__init__.py`, `checks.py`, `fixes.py`, `__main__.py` | 13 kiểm tra (`check_<id>`), 3 mức `ok|fix|warn|bad`, 6 auto-fix (`start_docker`, `pick_port`, `pull_images`, `git_longpaths`, `max_map_count`, `lower_codeql_ram`); `python -m preflight --json` | `run(fix)`, `fix(fix_id)`, `run_check`, `apply` | api_real, launcher `--preflight` |
| `packaging/launcher.py` | Entry exe: `--version`, `--preflight --json`, `--profile F` (headless), `--cli …`, `-m module`, GUI (fallback trình duyệt, `gui.json` single-instance) | `main`, `run_headless`, `run_gui`, `get_version` | `secjit-scan.exe` |
| `packaging/version.py` | Phiên bản: `SECJIT_APP_VERSION` → `_version_build.txt` → `git describe` → `dev` | `get_version`, `write_build_file` | launcher, build_exe.ps1, run_meta.app_version |

## 4. `scripts/` và `tests/`

| File | Vai trò | Ai gọi |
|---|---|---|
| `scripts/verify_run.py` | Nghiệm thu 1 run theo CONTRACTS: 12 mục DB + 5 mục export, exit 0/1; `run(db, export, params)` | cli `verify`, results_report, tests |
| `scripts/results_report.py` | `RESULTS.md` A/B: cấu hình + digest, phễu/nhãn/thời gian, compare, verify, κ, kết luận ĐẠT/CHƯA ĐẠT, giới hạn | trưởng (nghiệm thu), tests |
| `scripts/merge_export.py` | Sinh `dataset.jsonl/commits.jsonl` từ DB readonly cho export cũ (gọi `export_dataset.write_merged`) | runbook VM |
| `scripts/build_gold_set.py` | `gold_set/` mỗi export + `gold_set_all` (precision kiểm tay vào README) | runbook |
| `scripts/relabel_gold_w7.py` | Preset `sensitivity` W=7 trên bản sao DB + `positive_gold_w7.jsonl` | runbook |
| `scripts/release.ps1`, `build_exe.ps1` | Build 2 exe PyInstaller (`secjit.spec`), ghi `_version_build.txt` | CI/tay |
| `scripts/demo_10min.md`, `resume_skywalking.sh` | Kịch bản demo hội đồng; resume run VM cũ | người |
| `tests/conftest.py` | Fixture: `scratch_db` (3 commit, v0), `smoke_db` (v2 thật đã analyze), `orch_env` (ORCH_* → tmp, nạp lại config), `fake_docker` (mock `subprocess.run`), `_no_real_docker` (autouse) | pytest |
| `tests/fixtures/` | `scratch.db`, `smoke_v2.db`, `export_smoke/` (manifest, dataset, commits, SHA256SUMS; `.gitattributes -text`) | tests |
| `tests/test_data_core.py` | A1: D1–D8, migrate v2, lock, infra_error, stop-file, export, timestamp | |
| `tests/test_review.py`, `test_verify_run.py`, `test_results_report.py`, `test_cheap_tools.py`, `test_on_smoke_db.py` | review mù; verify; report A/B; semgrep argv + scan_tool_errors; backend trên DB thật (1 xfail strict: `stats` universe) | |
| `tests/test_cli_scope.py`, `test_cli_wave2.py`, `test_contract_profile.py`, `test_batch_runner.py` | A2: scope/profile/estimate/stats/sensitivity/compare/stop/clean/review/batch/rescan | |
| `tests/test_runner.py`, `test_runner_cleanup.py`, `test_registry.py`, `test_preflight.py`, `test_notify.py`, `test_unit_*.py`, `test_launcher_gui_info.py` | A3: runner/registry/preflight/launcher/encoding/paths/rmtree/keys | |
| `tests/test_gui_server.py`, `test_api_results.py` | A4/A5: server mock, backend thật màn 6–10 | |
| `tests/gui/shoot.py`, `shoot_a5.py`, `flow_mock.py`, `qa_a5_on_a4.py`, `run_b_from_exe.py`, `gallery.py` | Playwright: chụp màn × trạng thái, luồng click end-to-end, QA chéo, Run B từ exe, gallery ảnh | người/CI (cần Chromium) |

Chạy: `python -m ruff check src scripts gui runner registry preflight tests` · `PYTHONIOENCODING=utf-8 python -m pytest -q`
(≈ 257 test, không Docker; `fake_docker` chặn `subprocess.run`, `_no_real_docker` chặn `shutil.which("docker")`).

---

## 5. Biến môi trường

- **`ORCH_*`** (đọc bởi `config.py`, đặt bởi `profile.to_env()` / runner): bảng đầy đủ **`GUIDE.md` §3** (3.1 đường dẫn
  `ORCH_SQLITE/EXPORT_DIR/WORK_DIR/DATA_DIR` · 3.2 lọc · 3.3 song song `ORCH_SCAN_WORKERS/EXPENSIVE_WORKERS` · 3.4 chọn
  commit `ORCH_CLEAN_PER_BUGGY` · 3.5 tầng đắt `ORCH_EXPENSIVE_TOOLS/USE_CODEQL/MAVEN_IMAGE/BUILD_TIMEOUT/SONAR_PORT/
  M2_VOLUME/DOCKER_BIN` · 3.6 nhãn `ORCH_LINE_WINDOW/GOLD_MIN_EXPENSIVE/GOLD_ALLOW_1EXP_1CHEAP/SILVER_MIN_CHEAP/NOISE_CWE`
  · 3.7 run `ORCH_RUN_ID/PROGRESS_FILE/STOP_FILE/EXPERIMENT/EXPERIMENT_REASON/INFRA_STOP_AFTER`).
- **`SECJIT_HOME`** (thư mục app: `runs.json`, `speed.json`, `settings.json`, `profiles/`; mặc định `%LOCALAPPDATA%\secjit`),
  **`SECJIT_APP_VERSION`** (ghi `run_meta.app_version`), **`SECJIT_GUI_URL`** (launcher mở instance có sẵn).
- Luôn đặt `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`, `PYTHONPATH=src` khi chạy CLI từ mã nguồn.

## 6. Lệnh CLI (`python -m orchestrator.cli …` hoặc `secjit-scan.exe --cli …`; mọi lệnh nhận `--json`, `--profile F`)

| Lệnh | Làm gì | Module |
|---|---|---|
| `pipeline <repo> [--max N|--since|--until|--from-sha|--to-sha] [--tools] [--expensive-tools] [--codeql 0|1] [--include-clean] [--workers K] [--out DIR]` | scan→select→analyze→relabel→kappa→export | cli.cmd_pipeline |
| `enumerate` · `scan` · `select` · `analyze` · `relabel` · `kappa` · `features` · `export` | từng tầng | cli |
| `rescan --commit SHA [--tools a,b]` | quét lại commit/tool lỗi, giữ raw tool khác | cli.rescan_commit |
| `estimate --profile F` | ước tính thời gian/đĩa | estimate |
| `stats [--db] [--format json|csv|latex] [--out]` | overview + limits | stats |
| `verify --db DB [--export DIR]` | nghiệm thu CONTRACTS | scripts/verify_run |
| `sensitivity --db DB --out DIR [--grid k=v,…]` | lưới tham số trên bản sao | sensitivity |
| `compare --a X --b Y [--format md]` | A/B theo cluster_key; exit 1 nếu lệch không giải thích | compare |
| `review sample|next|verdict|close --db DB …` | kiểm tay mù | review |
| `stop --run ID [--force]` · `stop-cleanup --run ID` · `reset-claims --run ID [--all-stale]` | điều khiển run | control |
| `clean <repo> [--items clone,pool,m2,export:<dir>,db:<path>] [--dry-run]` | dọn có kế hoạch | control |
| `batch --queue Q.json [--state] [--stop-file] [--work] [--local]` · `diagnostics --run ID --out X.zip` | hàng đợi tuần tự (qua runner nền, `--local` = trong tiến trình); gói chẩn đoán | batch/batch_runner, diagnostics |
Exit code: 0 ok · 1 lỗi tham số · 2 lỗi runtime · 3 dừng theo stop-file.

## 7. Bảng SQLite (`PRAGMA user_version = 2`, WAL)

| Bảng | Vai trò | Cột quan trọng |
|---|---|---|
| `findings` | 1 dòng = 1 **cụm** đã vote (ghi đè mỗi relabel) | `repo, commit_id, file_path, s_line, s_detail_line(JSON), finding_in_diff, cwe(JSON), cwe_group, category, agreeing_tools(JSON), n_tools_agree, n_cheap, n_expensive, eligible, tier(cheap|expensive|mixed), label(gold|silver|candidate), kamei(JSON), diff_parsed(JSON), code_*_url` |
| `raw_findings` | 1 dòng = 1 finding **từng tool** (nguồn relabel/κ) | `commit_id, tool, tier, file_path, s_line, cwe, rule_id, severity, message` |
| `raw_output` | output thô mỗi tool/commit (audit) | `commit_id, tool, tier, fmt(json|jsonl|sarif|xml|**error**), content` |
| `scan_tool_errors` | lỗi tool tầng rẻ | `commit_id, tool, tier, kind(tool_error|tool_timeout|infra_error), msg, at` |
| `scanned_files` | mẫu số (commit, file) đã quét rẻ | `commit_id, file_path, n_findings, tools, label(clean|has_finding)` |
| `scan_done` | mốc resume tầng rẻ | `commit_id, finished_at` |
| `commit_features` | 14 đặc trưng Kamei | `commit_id, repo, author, author_date, ns…sexp` |
| `selected_commits` | hàng đợi tầng đắt (claim nguyên tử) | `commit_id, role(buggy|clean), status(pending|building|analyzing|done|build_failed|error), claimed_by(<run_id>:wN), claimed_at, build_status(ok|skipped|failed|timeout|infra_error), attempts, **n_expensive_ok**` |
| `expensive_runs` | telemetry tầng đắt 1 dòng/(commit, tool, phase) | `commit_id, tool(maven|findsecbugs|sonar|codeql|-), phase(build|analyze|process), status(**ok|skipped|build_failed|infra_error|tool_timeout|tool_error**), n_findings, duration_sec, error, run_id` |
| `run_meta` | 1 hàng/(run, tier) để tái lập | `run_id, tier(scan|analyze), started_at, finished_at (local ISO), repo, branch, scope_json, config_snapshot_json, tools_json([{name,image,version,digest}]), orchestrator_git_sha, app_version, experiment, reason` |
| `kappa` | κ đã tính | `run_id, scope(total|category|cwe_group|pair), grp, value, n` |
| `gold_sample` / `gold_review` | mẫu kiểm tay / verdict từng rater | `sample_id, cluster_key, stratum, kind(pos|neg), seed` / `cluster_key, sample_id, rater, verdict(TP|FP|unclear), note, at` |

`negative_level` **không** lưu — tính: có `finding_in_diff=1` → positive; else `verified-clean` nếu `n_expensive_ok ≥ 2`, ngược lại `cheap-clean`.

## 8. Quy ước bắt buộc

1. **`src/orchestrator/**` stdlib-only** (GUI/runner/registry/preflight được dùng pywebview/playwright trong test). Mọi `open()` text có `encoding="utf-8"`, subprocess text `errors="replace"`; file JSON/JSONL ghi `newline="\n"`.
2. **Đường dẫn vào container luôn `.as_posix()`**; đường dẫn host có thể chứa `'`, khoảng trắng, unicode → luôn quote. Mọi `docker run` qua `tools.base.docker_run` (tự gắn `--label orch.run=<run_id>`).
3. **Trạng thái thống nhất (CONTRACTS §1)**: `ok | skipped | build_failed | infra_error | tool_timeout | tool_error`; `infra_error` KHÔNG phải dữ liệu (commit về `pending`, 3 lần liên tiếp → dừng run). `verified-clean ⇔ n_expensive_ok ≥ 2`.
4. **`cluster_key`** là khoá duy nhất xuyên relabel/compare/review (bucket `s_line // LINE_WINDOW`); đổi `LINE_WINDOW` = khoá không tương thích.
5. **Nhãn v1 khoá** (`line_window=3, gold_min_expensive=2, gold_allow_1exp_1cheap=1, silver_min_cheap=2, noise=[CWE-117]`); đổi → `experiment` + lý do, export `_exp`, không gộp. `evidence.consensus` (máy) tách `evidence.validation` (người: adjudicated > đa số > hoà=unclear).
6. **Lock & WAL**: mở ghi = `SQLiteStore(path)` → WAL + `<db>.lock` (pid, run_id; pid sống → `RuntimeError`); GUI/stats/compare mở `readonly=True`/`mode=ro` (không lock, không migrate). Mở `mode=ro` trên DB WAL vẫn tạo `-shm/-wal` 0 byte (vô hại, đã gitignore).
7. **Timestamp**: `run_meta`, `kappa`, `gold_*`, lock = local ISO `%Y-%m-%dT%H:%M:%S` (như `progress.ts`); các bảng cũ (`expensive_runs.created_at`, `claimed_at`…) vẫn `datetime('now')` UTC (phụ thuộc `julianday('now')` trong `reset_stale_claims`).
8. **Export không ghi đè**: đích không rỗng → `<out>_2`, `_3`…; `SHA256SUMS` băm byte trên đĩa; fixture test `-text` để không bị CRLF.
9. Vùng file theo agent (TASKS §4) và **hợp đồng không tự đổi** — đề xuất ghi vào báo cáo/§12.

## 9. Chỗ hay sai (gotcha tổng hợp)

| # | Gotcha | Xử lý |
|---|---|---|
| 1 | Đường dẫn repo có `'` (`D:\Master's thesis`) → lệnh shell gãy | luôn quote; trong Git Bash đặt `MSYS_NO_PATHCONV=1` để `-v …:/m2` không bị đổi thành `C:/Program Files/Git/m2` |
| 2 | Console Windows cp1252 nổ `UnicodeEncodeError` khi in tiếng Việt | mọi lệnh Python: `PYTHONIOENCODING=utf-8` (`PYTHONUTF8=1`) |
| 3 | `os.kill(pid, 0)` trên Windows **giết** tiến trình (TerminateProcess) | dùng `sqlite_store.pid_alive` / `control.pid_alive` (OpenProcess) |
| 4 | Semgrep argv > 32 k ký tự → `WinError 206` ở commit nhiều file | đã vá: copy file đổi vào temp dir rồi `scan /src` (không truyền file) |
| 5 | Docker tắt giữa run → trước đây ghi `build_failed` hàng loạt | nay `infra_error` (rc 125/127, stderr `Cannot connect…/error during connect/dockerDesktopLinuxEngine/No space left`) → commit về pending, 3 lần → stop |
| 6 | Port 9000 bị container khác chiếm (minio) → Sonar không lên | `ORCH_SONAR_PORT=9100`; `sonar._host_api()` đọc lúc gọi, Preflight có auto-fix |
| 7 | Path backslash lọt vào container (`relative_to()` trên Windows) → FSB "No files to analyze", Sonar "Invalid binaries" | `.as_posix()`; XML 0 byte = `ToolError` |
| 8 | Pool clone không xoá được `.git/objects/pack` read-only → rác `pool_*` | `repo_pool.rmtree_force` (chmod rồi xoá), dùng cho `clean` |
| 9 | Sonar: admin/admin chỉ dùng được lần đầu; thiếu `sonar.java.libraries` → 0 finding; `vm.max_map_count` < 262144 → không UP | code đổi pw qua API + token; luôn mount `/m2`; Preflight `max_map_count` (WSL2 reset sau reboot) |
| 10 | `datetime('now')` SQLite là UTC, `started_at` local → lệch múi giờ trong `run_meta` | dùng `_now()` local ISO cho bảng mới |
| 11 | `core.autocrlf=true` đổi LF→CRLF lúc checkout → `SHA256SUMS` fixture lệch | `.gitattributes`: `tests/fixtures/** -text`, `*.db binary`; export ghi `newline="\n"` |
| 12 | 2 run cùng DB / cùng Sonar: run B `rm -f orch-sonar` giết Sonar run A; `reset_cheap_scan` xoá raw của nhau | tên container/network theo `run_id`; lock `<db>.lock`; chỉ 1 run tầng đắt/máy |
| 13 | Clone cũ trùng tên repo khác org → quét nhầm im lặng | `clone_or_update` đặt tên `owner__repo` + kiểm `git remote get-url origin` (`OriginMismatch`) |
| 14 | `reset_stale_claims(7200)` bỏ qua commit `building` < 2 h sau Dừng an toàn | `reset_claims(run_id)` theo `claimed_by '<run_id>:wN'` (stop-cleanup) |
| 15 | Export vào thư mục cũ sau đổi `NOISE_CWE` → trộn commit cũ | luôn thư mục mới `_2…`; dùng `res['out']` |
| 16 | `kappa.collect` đếm tool có `raw_output` là "đã chạy" → tool lỗi thành "không báo" | bỏ `fmt='error'`; lỗi nằm ở `scan_tool_errors` |
| 17 | FSB báo dòng **khai báo** method/field, Sonar báo dòng **statement** → lệch 18–43 dòng, W ≤ 7 không gộp (gold = 0 trên smoke) | giới hạn phương pháp; ý tưởng method-level clustering sau MVP (xem RESULTS/METHODOLOGY) |
| 18 | `stats._funnel/_negatives` lấy universe từ `scanned_files` → commit clean 0 file-code bị bỏ (`cheap_clean=0`) | A2 đã sửa universe (test `test_on_smoke_db` xfail strict sẽ XPASS → bỏ marker) |
| 19 | Run dài chết theo phiên SSH/Claude | runner tách rời (`DETACHED_PROCESS`/`setsid nohup`), pid-file, `attach` |
| 20 | Library Spring: dependency `*-SNAPSHOT` biến mất → `build_failed` ~87 % | là dữ liệu (ghi phễu/manifest); chọn repo pilot là **app thuần** |
| 21 | Thư mục OneDrive/UNC/đường dẫn > 260 ký tự | wizard bước 4 cảnh báo; `core.longpaths` auto-fix; test tạo path ngắn |
| 22 | Fixture DB mở trực tiếp tạo `-shm/-wal` cạnh file trong repo | test luôn copy fixture ra tmp; `.gitignore` `*.db-wal/-shm` |
