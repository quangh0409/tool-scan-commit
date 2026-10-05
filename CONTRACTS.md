# CONTRACTS — Hợp đồng giao diện giữa các phần (đóng băng T0 2026-10-05; hợp nhất đợt 8, dev `733576d`)

> Mọi agent tuân theo file này. **Không tự đổi hợp đồng**; cần đổi → ghi đề xuất vào báo cáo cuối, trưởng quyết.
> Kế hoạch: `TASKS.md`. Review nguồn: `REVIEW.md`. Quyết định phương pháp luận: `TOOL_IDEA_CONTEXT.md` §13.
> Bản đồ mã: `CODE_MAP.md`. Mọi khẳng định dưới đây đã **đối chiếu với mã thật** (grep) khi hợp nhất; chỗ mã khác
> hợp đồng được đánh dấu **`LỆCH:`** để trưởng quyết (không tự sửa mã). Hiệu chỉnh cũ (§12 bản trước) đã gộp vào mục gốc;
> §12 nay chỉ là nhật ký.

**Mục lục:** 0 Quy tắc · 1 Trạng thái · 2 profile.json · 3 progress.jsonl · 4 Schema SQLite · 5 cluster_key · 6 Export
· 7 Runner/registry/lock · 8 Preflight · 9 API GUI · 10 Web UI · 11 CLI · 12 Nhật ký hiệu chỉnh

---

## 0. Quy tắc chung cho agent

- **Không chạy Docker, không chạy pipeline thật** trong test. pytest với `subprocess` mock (`fake_docker`) và DB fixture
  `tests/fixtures/scratch.db` (train-ticket 3 commit, schema v0) / `tests/fixtures/smoke_v2.db` (v2 thật, đã analyze).
- Chỉ sửa file trong **vùng được giao** (TASKS.md §4). `cli.py`, `config.py` chỉ A2 sửa. Cần hook ở file của người khác →
  ghi vào báo cáo "YÊU CẦU LIÊN AGENT".
- Module dùng chung, **import, không viết lại**: `src/orchestrator/{progress,keys,profile}.py`.
- Orchestrator (`src/orchestrator/**`) **stdlib-only**. `gui/`, `runner/`, `registry/`, `preflight/` được dùng `pywebview`,
  `playwright` (test). Không pyarrow. `packaging/` KHÔNG phải gói Python (trùng tên PyPI `packaging`) — nạp `version.py` qua
  importlib.
- Chạy `python -m ruff check src scripts gui runner registry preflight tests` và `PYTHONIOENCODING=utf-8 python -m pytest -q`
  trước khi commit. Commit nhỏ, message tiếng Việt, kết bằng `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Encoding: mọi `open()` text có `encoding="utf-8"`; subprocess text có `errors="replace"`; JSON/JSONL ghi `newline="\n"`.
- Đường dẫn vào container luôn `.as_posix()`; đường dẫn host có thể chứa `'`, khoảng trắng, unicode → luôn quote.
- Mọi `docker run` đi qua `tools.base.docker_run` → tự gắn `--label orch.run=<run_id>`.
- Env chuẩn khi chạy từ mã nguồn/exe: `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`, `PYTHONPATH=src`; `ORCH_SONAR_PORT` đặt
  **trước** khi import orchestrator (hoặc `config.reload()`).
- Báo cáo cuối (bắt buộc): việc đã làm (file), test đã chạy + kết quả, YÊU CẦU LIÊN AGENT, điều chưa làm được, nhánh/worktree.

## 1. Phân loại trạng thái thống nhất (manifest, GUI, compare, DB)

| Giá trị | Nghĩa | Ghi ở đâu |
|---|---|---|
| `ok` | tool chạy xong, có kết quả (kể cả 0 finding) | `expensive_runs.status`; tầng rẻ: có `raw_output` fmt ≠ `error` |
| `skipped` | commit không có module Java → không build, **tool đắt không chạy**. Không tính verified | `expensive_runs` (tool=`maven`, phase=`build`); `selected_commits.build_status='skipped'`, status `done` |
| `build_failed` | Maven rc≠0 vì **dữ liệu** (dependency mất, compile lỗi) | `selected_commits.status`, `expensive_runs` (`build_status='failed'`) |
| `infra_error` | lỗi **hạ tầng**: Docker không kết nối (rc 125/127; stderr `Cannot connect to the Docker daemon` / `error during connect` / `dockerDesktopLinuxEngine` / `is the docker daemon running` / `executable file not found`), đĩa đầy (`disk is full`, `No space left`, `database or disk is full`). Commit **về `pending`** (xoá raw đắt bán phần), không đếm là dữ liệu. Sau **`ORCH_INFRA_STOP_AFTER`=3 lần liên tiếp** (reset khi có ok) → run tự dừng (`event=stop`, `status=infra_error`). Tầng rẻ: ghi `scan_tool_errors.kind='infra_error'`, `cli scan` dừng tương tự | `expensive_runs`, `scan_tool_errors`, progress |
| `tool_timeout` | `subprocess.TimeoutExpired` của 1 tool. **Build timeout**: `expensive_runs.status='tool_timeout'`, `tool='maven'`, commit → `build_failed`, `build_status='timeout'` | `expensive_runs`, `scan_tool_errors`, raw_output fmt=`error` |
| `tool_error` | tool crash/parse lỗi (XML 0 byte, SARIF hỏng, không có task id) — `tools_expensive.base.ToolError`; tầng rẻ: exception trong `scan` | `expensive_runs`, `scan_tool_errors` |

`negative_level` (**không lưu**, tính khi đọc): commit có `findings.finding_in_diff=1` → positive (`null`); còn lại
`verified-clean` **chỉ khi** `n_expensive_ok ≥ 2` (số tool đắt DISTINCT có `expensive_runs.phase='analyze' AND status='ok'`,
loại `maven`/`-`), ngược lại `cheap-clean`. `selected_commits.n_expensive_ok` được cập nhật sau mỗi commit.

Nhãn cụm: `gold | silver | candidate` theo luật v1 (`E ≥ gold_min_expensive` hoặc `gold_allow_1exp_1cheap ∧ E≥1 ∧ C≥1` → gold;
`E≥1 ∨ C ≥ silver_min_cheap` → silver; còn lại candidate). `evidence.consensus` (máy) tách `evidence.validation` (người):
`unreviewed | TP | FP | unclear`, gộp nhiều rater **`adjudicated` > đa số > hoà = `unclear`** (`review.validation_of`).

## 2. `profile.json` (`src/orchestrator/profile.py`)

```json
{"schema":1,"repo":"https://github.com/FudanSELab/train-ticket","branch":"master",
 "scope":{"mode":"count","since":null,"until":null,"max":30,"from_sha":null,"to_sha":null},
 "include_clean":true,"cheap_tools":["gitleaks","trufflehog","semgrep","bearer","horusec"],
 "expensive_tools":["findsecbugs","sonar"],"codeql":false,"workers":{"scan":4,"expensive":1},
 "paths":{"db":"D:\\secjit\\results\\dataset_FudanSELab__train-ticket_master_20261005.sqlite",
          "export":"D:\\secjit\\results\\export_FudanSELab__train-ticket_master_20261005","work":"D:\\secjit\\work"},
 "sonar_port":9100,"experiment":null,
 "filters":{"clean_per_buggy":null,"require_in_diff":true},
 "params_v1":{"line_window":3,"gold_min_expensive":2,"gold_allow_1exp_1cheap":1,"silver_min_cheap":2,"noise_cwe":["CWE-117"]}}
```

- `scope.mode`: `time` (committer-date, ISO `YYYY-MM-DD`, ép `--max 0`; `scope_json` ghi `date_field:"committer"`), `count`
  (`max` > 0; **0 bị cấm**), `sha` (`from_sha..to_sha`, verify bằng `git rev-parse`), `all`.
- `filters` (tuỳ chọn, Wizard 2): `clean_per_buggy` → `ORCH_CLEAN_PER_BUGGY`, `require_in_diff` → `ORCH_SUSPECT_REQUIRE_IN_DIFF`.
- `params_v1` khác mặc định ⇒ bắt buộc `experiment={"enabled":true,"reason":"≥10 ký tự"}`; run gắn `run_meta.experiment=1`
  + `reason`; manifest `experiment={enabled, reason}`; **không gộp** với dữ liệu v1. Export thí nghiệm
  (`ORCH_EXPERIMENT=1`) **gắn hậu tố `_exp`** vào tên thư mục (`export_dataset.resolve_out_dir`, trước khi xét `_2/_3`;
  không nhân đôi nếu tên đã có `_exp`) — quyết đợt 9, đã vào mã.
- `profile.to_env()` → env `ORCH_*` (+`PYTHONUTF8`, `PYTHONIOENCODING`; experiment → `ORCH_EXPERIMENT=1`,
  `ORCH_EXPERIMENT_REASON`, `ORCH_LINE_WINDOW`); `to_cli_args()` → argv `pipeline …`; `to_shell(p, "powershell"|"bash")` → lệnh
  tương đương (mọi giá trị quote). `from_env_defaults(repo, branch, out_dir)` sinh tên `dataset_<slug>_<branch>_<yyyymmdd>`.
- `--profile F` nhận ở **mọi** subcommand (parser cha): áp env + `config.reload()` **trước** argparse; với lệnh profile-driven
  (`pipeline` …) **bỏ qua mọi arg khác** (cảnh báo). `run_meta.config_snapshot_json` lưu profile + env hiệu lực.

## 3. `progress.jsonl` (`src/orchestrator/progress.py`)

Một dòng JSON mỗi sự kiện: `{"ts","run_id","phase","event","done","total","worker","sha","status","msg"}` (`ts` local ISO
`%Y-%m-%dT%H:%M:%S`). Không bao giờ raise; no-op nếu không có `ORCH_PROGRESS_FILE`.
- `phase ∈ scan|select|analyze|relabel|kappa|export|review|stats`; `event ∈ start|item|done|error|stop`.
  Mã đang emit: scan `start/item/done/stop`; select `start/done`; analyze `start/item/done/error/stop`; relabel `start/item/done`
  (item mỗi 50 commit); kappa, export, stats `start/done`; review `start/done` (`msg` = `sample|next|verdict|close`).
- `scan.start.total` = số commit sau lọc thô, sau RESUME; `scan.item.msg` ≤ 120 ký tự. `analyze.start.total` = số `pending`.
- `analyze.item`: `worker="wN"`, `sha`, `status` ∈ §1 ∪ {`done`, `error`}, `msg` ngắn (`build 145s · fsb 41 · sonar 12`).
  `selected_commits.claimed_by = "<run_id>:wN"` — GUI đối chiếu bằng `endswith(":"+worker)`.
- Stop-file: `ORCH_STOP_FILE` tồn tại → orchestrator kết thúc commit hiện tại, **không claim commit mới**, emit `event=stop`,
  exit code 3. Kiểm **giữa** mỗi commit ở scan và analyze (`progress.should_stop()`).
- Env runner đặt: `ORCH_RUN_ID`, `ORCH_PROGRESS_FILE=<work>/<run_id>/progress.jsonl`, `ORCH_STOP_FILE=<work>/<run_id>/stop`,
  `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`, cùng `profile.to_env()`.

## 4. Schema SQLite `user_version = 2` (`storage/sqlite_store.py`)

```sql
CREATE TABLE run_meta (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, tier TEXT CHECK(tier IN ('scan','analyze')),
  started_at TEXT, finished_at TEXT, repo TEXT, branch TEXT, scope_json TEXT, config_snapshot_json TEXT,
  tools_json TEXT,  -- [{name,image,version,digest}] (analyze: FSB/Sonar/CodeQL + maven image dùng thật)
  orchestrator_git_sha TEXT, app_version TEXT, experiment INTEGER DEFAULT 0, reason TEXT);
CREATE TABLE kappa (run_id TEXT, scope TEXT, grp TEXT, value REAL, n INTEGER, computed_at TEXT);
  -- scope: 'total' | 'category' | 'cwe_group' | 'pair' ; grp: '' | 'code' | 'csrf' | 'findsecbugs|sonar'
CREATE TABLE gold_review (cluster_key TEXT, sample_id TEXT, rater TEXT, verdict TEXT CHECK(verdict IN ('TP','FP','unclear')),
  note TEXT, at TEXT, PRIMARY KEY (cluster_key, sample_id, rater));
CREATE TABLE gold_sample (sample_id TEXT, cluster_key TEXT, stratum TEXT, kind TEXT CHECK(kind IN ('pos','neg')),
  seed INTEGER, created_at TEXT, PRIMARY KEY (sample_id, cluster_key));
CREATE TABLE scan_tool_errors (id INTEGER PRIMARY KEY AUTOINCREMENT, commit_id TEXT, tool TEXT, tier TEXT,
  kind TEXT CHECK(kind IN ('tool_error','tool_timeout','infra_error')), msg TEXT, at TEXT);   -- tầng rẻ (TC-15)
```
- Cột mới trên bảng cũ: `selected_commits.n_expensive_ok INTEGER DEFAULT 0`; `expensive_runs.run_id TEXT`.
  Bảng còn lại (findings, raw_findings, raw_output, scanned_files, scan_done, commit_features, selected_commits, expensive_runs):
  xem `CODE_MAP.md` §7.
- Migrate từ `user_version` 0/1: thêm bảng/cột nếu thiếu; giữ dữ liệu (run_meta cũ → `tier='scan'`, `run_id='legacy'`;
  backfill `n_expensive_ok`). `scan_tool_errors` tạo bằng `CREATE IF NOT EXISTS` (không bump version).
- Mở GHI: `SQLiteStore(path=None)` → `PRAGMA journal_mode=WAL`, `busy_timeout=5000`, lock-file **`<db>.lock`** JSON
  `{pid, run_id, at}`; pid còn sống → `RuntimeError("DB đang được run khác dùng…")`. Mở ĐỌC: `SQLiteStore(path, readonly=True)`
  → `file:…?mode=ro` (`uri=True`), không lock, không migrate (GUI/stats/compare/merge_export). Chỉ tiến trình orchestrator
  con tạo lock; GUI chỉ kiểm (`registry.locks.lock_status`, cùng định dạng).
- Lỗi đĩa khi ghi (`OperationalError` chứa "disk", `OSError ENOSPC`) → `storage.InfraError` → runner dừng.
- API: `insert_run_meta(tier, **fields) -> id` (vẫn nhận dict cũ), `finish_run_meta(id, **f)`, `run_meta_rows`, `save_kappa`,
  `kappa_rows`, `reset_claims(run_id|None)` (giữ `expensive_runs`, xoá raw đắt bán phần), `reset_expensive_raw`,
  `insert_raw_output(fmt='error')` → tự ghi `scan_tool_errors`, `tool_errors_all`, `n_expensive_ok`, `update_n_expensive_ok`,
  `negative_level`, review: `replace_gold_sample`, `gold_sample_rows/ids`, `gold_review_rows`, `upsert_gold_review`,
  `gold_review_verdicts -> {ck: [(rater, verdict)]}`, `verified_clean_commits`; module: `pid_alive` (không `os.kill(pid,0)`
  trên Windows), `read_lock(db)`, `lock_path_for`. `repo_pool.rmtree_force`, `repo_pool.verify_origin`.
- Timestamp bảng mới (`run_meta`, `kappa`, `gold_*`, lock, `scan_tool_errors`) = local ISO; bảng cũ vẫn `datetime('now')` UTC.

## 5. `cluster_key` (`src/orchestrator/keys.py`)

`cluster_key = sha256(canon_repo|commit|file_path|cwe_group|s_line//LINE_WINDOW)[:32]`. Dùng cho `gold_review`,
`gold_sample`, `compare`, GUI `finding/{cluster_key}`, map lại sau relabel. `keys.canon_repo()` = chuỗi repo chuẩn duy nhất
(run_meta.repo, registry, lock, kiểm origin clone); `keys.repo_slug()` = `owner__repo` cho tên clone/DB. Đổi `LINE_WINDOW` ⇒
khoá không tương thích (`compare` cảnh báo, `ok=false`).

## 6. Export & manifest (`export_dataset.export_all(store, out_dir, profile=None, run_id=None) -> res`, `res['out']`)

Mỗi run một thư mục; **đích không rỗng → luôn sang thư mục mới `<out>_2`, `_3`…** (cảnh báo, không trộn).
```
export_<slug>_<branch>_<yyyymmdd>/
  run_manifest.json   schema, run_id, db, export_dir, profile, run_meta[] (2 tier, JSON đã parse), kappa[],
                      counts{gold,silver,candidate,verified_clean,cheap_clean,commits,clusters},
                      build_failed[sha], infra_error[sha], skipped[sha],
                      tool_timeout[{commit,tool,tier}], tool_error[{commit,tool,tier}], cheap_infra_error[{commit,tool,tier}],
                      orchestrator_git_sha, app_version, os, python, docker_version, started, finished,
                      params_v1, experiment (null | {enabled, reason})
  dataset.jsonl       1 dòng = 1 cụm findings (+ "cluster_key", "evidence":{"consensus","validation"}); thứ tự author_date
  commits.jsonl       1 dòng = 1 commit commit_features (+ commit có finding thiếu feature): kamei{14}, labels{}, role, status,
                      build_status, n_expensive_ok, negative_level
  negatives.json · SHA256SUMS (dataset.jsonl, commits.jsonl, run_manifest.json; băm byte trên đĩa; mọi file ghi LF)
  <sha12>/            <tool>.raw.<fmt> (gồm *.raw.error), <tool>.findings.json, label.json, summary.json
```
`compare` giải thích lệch khi commit ∈ `tool_timeout | infra_error | skipped | build_failed | tool_error | cheap_infra_error`
của manifest A hoặc B (`explained_by{}` có đủ 6 khoá); từ DB suy từ `expensive_runs.status`.
`scripts/verify_run.py --db --export` (= `cli verify`): 12 mục DB + 5 mục export, exit 0/1. `scripts/results_report.py` →
`RESULTS.md` (ĐẠT khi `unexplained=0` ∧ verify PASS cả A và B).

## 7. Runner, registry, lock, speed (`runner/`, `registry/`)

- `runner.start(profile_path, run_id, work_dir, python_exe=None, extra_env=None) -> {pid, log, progress, stop, run_dir, meta,
  argv, env, db, export, profile, repo, branch, run_id, started, host_os, python, cwd, close_fds, stdin}`: tiến trình tách rời
  (`Popen(creationflags=CREATE_NEW_PROCESS_GROUP|DETACHED_PROCESS, close_fds=True, stdin=DEVNULL, stdout/stderr→<work>/<run_id>/run.log)`;
  Linux `start_new_session=True`). Lệnh `python -m orchestrator.cli pipeline --profile <file>` với env §3. Ghi
  `<work>/<run_id>/{pid, meta.json}`.
- `runner.alive(pid) -> bool`; `runner.attach(run_id, work_dir) -> {run_id, pid, alive, last_progress_line, interrupted, status,
  meta, log, run_dir, exists}` (`interrupted` = pid chết mà progress chưa có sự kiện kết thúc).
- `runner.stop(run_id, work_dir, force=False, timeout_s=10.0, python_exe=None, cleanup=None) -> {ok, stop_file, pid, by_pid,
  alive_before, killed, alive_after, force, cleanup, ts}`: mặc định tạo stop-file; `force` → `taskkill /T /F /PID` (Win) /
  `killpg SIGTERM` (Linux) rồi `orchestrator.cli stop-cleanup --run <id> --json` (`control.py`: rm container
  `--filter label=orch.run=<id>`, gỡ network `orch-sonar-net-<id>`, `reset-claims`); `cleanup.result` = JSON của stop-cleanup.
- `runner.batch_runner.run_queue(queue_path, work_dir, …)`: mỗi profile → `runner.start` + `registry.upsert`, chờ pid; stop-file batch.
- `registry` (`SECJIT_HOME` override; mặc định `%LOCALAPPDATA%\secjit`, Linux `$XDG_DATA_HOME/secjit`): `runs.json`
  `{"runs":[{run_id, repo, branch, db, export, work, profile, started, finished, status: running|stopped|done|failed|interrupted,
  pid, summary:{gold,silver,candidate,verified_clean,cheap_clean,commits,clusters,selected,kappa,relabeled,changed,smoke,scope,
  preflight_skipped,…}}]}`; ghi atomic (tmp + `os.replace`); `refresh_status()` → danh sách run đổi trạng thái
  (`interrupted` khi pid chết mà DB còn `building/analyzing`); `get/upsert/set_status/remove`.
  Cờ **`smoke`** ghi **cả hai nơi**: cấp bản ghi `run.smoke` (wrapper `api_real.run_start` đã ghi; A5 bổ sung ở
  `api_runs.run_start`) **và** `summary.smoke`; `run_id` chạy thử có hậu tố `-smoke`. Tương tự `preflight_skipped` (cấp bản ghi
  + summary). Người đọc ưu tiên cấp bản ghi, fallback `summary` (quyết đợt 9).
- Lock: `<db>.lock` (§4); single-instance GUI: `registry.locks.single_instance("secjit-gui")` (mutex Windows / lock-file);
  launcher ghi `gui.json` để lần chạy 2 mở URL cũ (`SECJIT_GUI_URL`).
- `speed.json` (`<SECJIT_HOME>/speed.json`): `{cheap_s_per_commit, build_cold_s, build_warm_s, fsb_s, sonar_s, buggy_ratio,
  samples, updated}`; `load()` thêm `source: measured|default`; cập nhật từ `expensive_runs.duration_sec` (cold = build ok đầu
  mỗi run_id) + `progress.jsonl` (EMA α=0,3).

## 8. Preflight (`preflight/`) — 13 mục, 3 mức + `bad`

`preflight.run(fix=False, targets=None, checks=None, work_dir=None, need_gb=…, sonar_port=None, progress_cb=None,
docker_timeout=…, include_codeql=False) -> {"items":[{id,title,level:"ok|fix|warn|bad",detail,fix_available,fix_id,fixed?}],
"ready", "docker_mem_gb", "cpu", "codeql_ram_mb", "sonar_port", "fixed":[{fix_id,ok,detail}], "os", "ts", "elapsed_s"}`.
`preflight.fix(fix_id, ctx=None, progress_cb=None) -> {ok, detail, …}`.
Mục (thứ tự `CHECK_ORDER`): `os_wsl2`, `docker_installed`, `docker_daemon` (fix `start_docker`: bật Docker Desktop + poll 90 s),
`docker_mem` (`docker info --format {{.MemTotal}}`; thấp → warn, gợi ý `.wslconfig`), `sonar_port` (fix `pick_port`:
9000→9100→9200…), `disk_free`, `git` (hướng dẫn winget), `git_longpaths` (fix `git_longpaths`), `images` (5 rẻ pull;
`orch-findsecbugs` **build** từ `docker/findsecbugs`; maven temurin; `sonarqube:lts-community`; `sonarsource/sonar-scanner-cli`;
codeql tuỳ chọn) (fix `pull_images` có tiến độ), `images_pinned` (warn `:latest`), `max_map_count` (fix `max_map_count` qua
`wsl -d docker-desktop sysctl`), `network` (github.com, registry-1.docker.io), `webview2` (warn). Fix thứ 6: `lower_codeql_ram`.
`python -m preflight --json [--fix <id>|all]` in JSON, exit 0 nếu ready. GUI cho **"Bỏ qua kiểm tra"** → run ghi
`summary.preflight_skipped=true`; `GET /api/preflight?light=1` chỉ kiểm `docker_daemon` (Home), không ghi đè kết quả đầy đủ.

## 9. API GUI (`gui/server.py` ROUTES; backend thuần `gui/api_{runs,results,review,settings}.py` `fn(params, body) -> dict`,
raise `gui.errors.ApiError`; `api_real.RealApi` ủy quyền bằng import lười, thiếu → `*_local` hoặc 501)

Server: `python -m gui [--dev] [--mock] [--port N] [--no-browser] [--verbose]`. Localhost, cổng ngẫu nhiên nếu không chỉ định,
header `X-Token: <token>` hoặc `?t=`. JSON UTF-8. Lỗi: HTTP 4xx/5xx + `{"error":{code,message,hint}}` (client reject
`{status, error}`; `hint` luôn chuỗi). `?state=empty|error|loading|partial` được mock tôn trọng.

| Method & path | Body → Trả về | Fixture |
|---|---|---|
| `GET /api/preflight[?light=1]` | → §8 (`light` → chỉ docker_daemon, thêm `light:true`) | `preflight.json`, `preflight_fixed.json` |
| `POST /api/preflight/fix` | `{fix_id}` → `{ok, detail, progress, done}` (`done=false` → client poll) | — |
| `POST /api/repo/check` | `{url, pat?}` → `{canon, slug, public, default_branch, branches[], tags[], java_maven, jdk, modules, snapshot_risk, security_config_count, commit_count|null, warnings[]}` | `repo_check.json` |
| `POST /api/estimate` | `{profile}` → `{commits_after_filter, buggy_est, cheap_minutes, expensive_minutes_cold, expensive_minutes_warm, disk_gb, speed_source, speed{}, detail{}, workers{}, histogram[{month,n}], db_exists}`; **425 `clone_pending`** khi chưa có clone (GUI retry 5 s) | `estimate.json` |
| `POST /api/profile/validate` | `{profile}` → `{errors[], warnings[], db_exists, export_exists, db_user_version, db_locked{held,pid,run_id}, …}` | — |
| `POST /api/run/start` | `{profile, smoke, workers?, formats?, notify?, overwrite?, preflight_skipped?}` → `{run_id, pid, smoke, db, work, log, …}`. **Backend thuần A5** (`api_runs.run_start`) đọc `profile, smoke, workers` (`smoke=true` → `--max 3` vào DB scratch, `run_id` hậu tố `-smoke`). **Wrapper A4** (`api_real.run_start`) xử lý phần còn lại trước/sau khi ủy quyền: `overwrite=true` → đổi tên DB cũ thành `<db>.<yyyymmdd-HHMMSS>.bak` (không áp cho smoke; lỗi → 500 `overwrite_failed`); `formats` (mặc định `["jsonl"]`) và `notify` (mặc định true) lưu vào `registry.summary` để `export`/toast dùng sau; `preflight_skipped` ghi cấp bản ghi + summary. **`resume` KHÔNG đi qua run/start** — dùng `POST /api/run/{id}/resume` (quyết đợt 9). | — |
| `POST /api/run/{id}/stop` | `{force}` → `{ok, cleaned[], force, stop_file, alive_before, alive_after, reset_claims, detail}` | — |
| `POST /api/run/{id}/resume` | `{workers?}` → `{run_id, pid, from_phase, workers, reset_claims, …}` | — |
| `GET /api/runs` | → `{runs:[registry §7 + summary], home}` (summary thêm `relabeled: bool`) | `runs.json` |
| `GET /api/run/{id}/progress` | SSE `data: <dòng progress>` (phát lại 200 dòng cuối; `?replay=0` chỉ tail); không SSE / `?since=N` → `{lines, next}` | `progress.jsonl` |
| `GET /api/run/{id}/profile` | → `{profile}` (404 nếu run không lưu profile) | — |
| `GET /api/results/{id}/overview` | → `{funnel{commits,after_filter,buggy,clean,built,build_failed,skipped,infra_error}, labels{gold,silver,candidate,verified_clean,cheap_clean}, by_cwe_group[{group,gold,silver,candidate}], kappa{total,n,by_category[],by_group[],pairs[],run_id}, coverage{one,two,three_plus}, cross_tool{anchor_gap…}, precision{n,tp,fp,unclear,point,ci_low,ci_high}|null, limits[], params_v1, experiment, db, run_id, raw_by_tool{}, relabeled, status}` | `overview.json` |
| `GET /api/results/{id}/findings?label=&cwe_group=&min_tools=&tier=&in_diff=&q=&page=&size=` | → `{total, page, size, line_window, rows[{cluster_key, commit, date, file_path, s_line, cwe_group, category, cwe[], tools[], n_agree, tier, label, evidence, in_diff, rule_id, severity, id}]}` | `findings.json` |
| `GET /api/results/{id}/finding/{cluster_key}` | → `{row(+kamei, code_*_url), diff_lines[{n, kind:add|del|flag, text}], tool_messages[{tool, rule_id, severity, message, s_line, cwe[], raw_path}] (raw trong ±2W cùng file — bằng chứng lân cận), provenance{run_id, tools_json[], line_window, gold_rule, scan_run_id, analyze_run_id, orchestrator_git_sha, app_version}, eligible{tools[], denominator}}` | `finding.json` |
| `GET /api/results/{id}/commits?page=&size=` | → `{total, page, size, rows[{commit, date, author, role, status, build_status, n_expensive_ok, negative_level, kamei{}, build_error, claimed_by}]}` | `commits.json` |
| `POST /api/results/{id}/export` | `{formats:["jsonl","csv","latex"]}` → `{export_dir, files[], exists, requested_dir, manifest{}, formats, counts, commits}` (409 nếu DB đang bị run ghi) | — |
| `GET /api/results/{id}/raw?path=<sha12>/<tool>.raw.<fmt>` | → `{path, source, content_type, bytes, content, truncated}` (404) | — |
| `POST /api/results/{id}/features` · `POST …/relabel` | → `{ok, pid, log, argv, note}` (chạy `cli features/relabel` nền); `relabel` 501 nếu run không ở chế độ thí nghiệm | — |
| `POST /api/open` | `{path}` → `{ok, path}` (501 nếu hệ không hỗ trợ) | — |
| `POST /api/review/{id}/sample` | `{seed=42, n_pos=200, n_neg=100}` → `{sample_id, seed, n_pos, n_neg, strata[{stratum,kind,n,total}], available{}, empty, message, run_id}` | `review_sample.json` |
| `GET /api/review/{id}/next?sample_id=&rater=` | → mục MÙ `{cluster_key, sample_id, stratum, kind, commit, repo, file_path, s_line, e_line, s_detail_line, cwe_claim{cwe[],group,category}, finding_in_diff, code_lines[{n,text,flag}], diff_lines[], messages_anon[], code_after_url, code_before_url, remaining}` (mục âm: `files[]`, `file_urls[]`); hết → `{cluster_key:null, remaining:0, sample_id, rater}`. `remaining` tính cả mục đang trả | `review_item.json` |
| `POST /api/review/{id}/verdict` | `{sample_id, rater, cluster_key, verdict: TP|FP|unclear, note}` → `{ok, remaining}` (TP = nhãn máy đúng; mục âm: TP = thật sự sạch; rater hoà giải `adjudicated`) | — |
| `POST /api/review/{id}/close` | `{sample_id, raters?}` → `{precision{tp,fp,unclear,n,n_reviewed,point,ci_low,ci_high,ci:"wilson95"}, neg_precision{}, kappa_raters{value,n,raters}|null (2 rater người), disagreements[{cluster_key,kind,stratum,verdicts{},adjudicated}], by_stratum[], primary_rater, n_adjudicated, unreviewed, raters[], …}` | `review_close.json` |
| `GET /api/settings` / `POST /api/settings` | `{language, out_dir, work_dir, sonar_port, codeql_ram_mb, m2_volume}` | `settings.json` |
| `POST /api/settings/pick_dir` | `{initial, title}` → `{path}` (501 nếu không có tkinter — exe exclude tkinter → nhập tay) | — |
| `GET /api/storage` | → `{items[{id, title, path, bytes, count, safety:safe|slow|rebuild|forbidden, detail}], total_bytes, free_bytes, docker, work_dir, out_dir}` | `storage.json` |
| `POST /api/clean` | `{items ⊂ pool,clone,m2,images,runs, dry_run}` → `{would_delete[{path,bytes}], deleted[], errors[]}`; `results` → 400; **409** khi run `running` dùng path | `clean_dry.json` |
| `GET /api/profiles` · `POST /api/profiles` · `GET|DELETE /api/profiles/{name}` | lưu `<SECJIT_HOME>/profiles/<name>.json` | `profiles.json` |
| `GET /api/shell?profile=&shell=` · `POST /api/shell {profile, shell}` | → `{command}` từ `profile.to_shell` | — |
| `GET /api/diagnostics` | → file zip (backend trả `{path, bytes}`, server stream; zip có `manifest.json{files, missing, redacted_keys}`) | — |

## 10. Web UI (`gui/web/`)

- Vanilla HTML/CSS/JS (ES2020), không framework, không CDN. `index.html` (import `screens/screens.css`) + `app.css` + `app.js`;
  `screens/<tên>.js` export `render(root, ctx)` và `destroy()`; `screens/_util.js`, `_shim.js`, `_harness.*` (chạy màn 6–10 với
  fixture không backend).
- Router hash (`app.js` `ROUTES`): `#/preflight`, `#/home`, `#/wizard/1..5` (`#/wizard/1?profile=<name>`), `#/run/<id>`
  (`?smoke=1`), `#/results/<id>[/overview|findings|commits|export]`, `#/review/<id>`, `#/settings[/<tab>]`.
- `ctx = {params, query, state, navigate, api, t, route, sse, url, components, lang}`: `ctx.api(path, {raw?})` chuyển tiếp
  `?state=`; `ctx.sse(path, onLine) -> closer()` (token qua `?t=`); `ctx.url(path)` URL kèm token; `ctx.components` = bộ
  component.
- Export của `app.js`: `ROUTES, NAV, WIZARD_STEPS, token, apiUrl, api, sse, lang, loadI, setLang, t, h, append, clear, debounce,
  fmt, btn, busy, card, table, stepper, toast, dialog, dialogEl, components, empty, errorBox, skeleton, badgeLabel, badgeStatus,
  notice, progress, copyText, PARAMS_V, CHEAP_TOOLS_ALL, EXPENSIVE_TOOLS_ALL, wiz, preflightCache, refreshPreflight, parseHash,
  matchRoute, navigate, route` (cũng gắn `window.SecJIT`). `table` nhận `onRow, rowKey, selected, emptyMsg`; `dialog` nhận
  `cancelText, kind` (`dialogEl` trả `<dialog>`); `card(children, {title, extraClass})`; `badgeLabel(label, evidence)` luôn hiện
  "gold · đồng thuận máy" / "gold ✓ TP" / "gold ✗ FP" / "gold ? chưa rõ".
- Design token (wireframe `scratchpad/wire/project/*.dc.html`): nền `#E9ECF0`, header `#142233`, nav `#1B2A3B`, nhấn `#1F5F8B`,
  ok `#1B7F4D`, fix `#A1540A`, bad `#B42318`, warn `#7A5B00`, gold `#FBE7B2/#6B4E00`, silver `#E3E7EC/#3B4654`; font
  `IBM Plex Sans` fallback `system-ui`, mono `IBM Plex Mono` (nhúng offline/fallback).
- i18n: `web/i18n/vi.json`, `en.json`, `vi_screens.json`; `t("key")`; thiếu khoá → hiện khoá.
- Mỗi màn có trạng thái `loading` (skeleton), `empty`, `error` (errorBox + Thử lại), `partial`. Dashboard thêm `interrupted`,
  `docker_down`, `disk_full`, `infra_stop`; **không hiển thị nhãn tạm khi run `running`** (chỉ đếm raw).
- Playwright: `tests/gui/shoot.py --mock --out <dir>`, `shoot_a5.py`, `flow_mock.py [--real --skip-run --seed-home --run-id]`
  (23 bước), `qa_a5_on_a4.py`, `run_b_from_exe.py`, `gallery.py` → PNG 1280×900.

## 11. CLI (`cli.build_parser`, 26 subcommand; parser cha: `--profile F`, `--json`)

```
enumerate  <repo> [scope] [--flag-limit 0|1]
scan       <repo> [scope] [--tools a,b] [--no-meta] [--flag-limit]
select     [--require-in-diff 0|1] [--include-clean]                 (idempotent: giữ status/n_expensive_ok hàng đã có)
analyze    <repo> [--workers K] [--branch B] [--expensive-tools a,b] [--tools (alias cũ, cảnh báo)] [--dry-run] [--codeql 0|1]
relabel    <repo> ; kappa ; features <repo> [--branch B]
pipeline   <repo> [scope] [--tools] [--expensive-tools] [--flag-limit] [--codeql 0|1] [--include-clean] [--workers K] [--no-meta] [--out DIR]
export     [--out DIR]
estimate   --profile F
stats      [--db DB] [--run-id ID] [--format json|csv|latex] [--out DIR]
verify     [--db DB] [--export DIR]
sensitivity --db DB --out DIR [--grid line_window=3,5,7 gold_allow_1exp_1cheap=0,1 noise=on,off] [--repo URL]   (BẢN SAO DB)
compare    --a <export_dir|db> --b <export_dir|db> [--format json|md]
stop       --run ID [--force] ; stop-cleanup --run ID (exit 0 kể cả không có gì dọn) ; reset-claims [--run ID] [--all-stale] [--db DB]
clean      <repo> [--items clone,pool,m2,m2volume,export:<dir>,db:<path>] [--dry-run]   (mặc định clone,pool; không --all)
review     [--db DB] sample [--seed 42] [--n-pos 200] [--n-neg 100] | next --sample-id --rater | verdict --sample-id --rater --cluster-key --verdict --note | close --sample-id [--raters a,b]
batch      --queue Q.json [--state F] [--stop-file F] [--work DIR] [--local]   (qua runner nền + registry; --local = tuần tự trong tiến trình, ORCH_RUN_ID=<batch>-<i>)
rescan     --commit SHA[,SHA…] [--tools a,b] [--db DB] [--repo URL]            (mặc định tool có lỗi trong scan_tool_errors)
diagnostics --run ID --out Z.zip [--work DIR]
scope = [--max N] [--branch B] [--since D] [--until D] [--from-sha S] [--to-sha S]   (time/sha ép --max 0)
```
Exit code: 0 ok · 1 lỗi tham số · 2 lỗi runtime · 3 dừng theo stop-file (cả `batch`). `ORCH_M2_VOLUME`: ""/0 bind mount
`.m2cache`; 1 → volume `secjit-m2`; tên khác → volume đó. `ORCH_DOCKER_BIN` đổi binary docker. `clone_or_update` fetch mỗi lần
(offline → cảnh báo), tên clone `owner__repo` (giữ tên cũ nếu origin khớp).
**Ghi chú:** `review sample` qua CLI **không** có `--sample-id` (module `review.sample(..., sample_id=None)` có; `python -m
orchestrator.review` có cả `list`).

## 12. Nhật ký hiệu chỉnh (đã gộp vào mục gốc ở trên)

- 2026-10-05 T+2: §7 chữ ký thật `runner.start/stop/attach`; `SECJIT_HOME`; `speed.buggy_ratio/updated`; §8 trả thêm
  `codeql_ram_mb/sonar_port/fixed/elapsed_s/os/ts`, 6 fix; §11 `stop-cleanup` exit 0, `--json`; §1 build timeout (A1); §3
  worker `wN` / `claimed_by <run_id>:wN`; §4 storage API A1 + lock JSON; §6 manifest thêm `tool_error/python/db/export_dir/run_id`,
  export luôn thư mục mới; env `ORCH_EXPERIMENT*`, `SECJIT_APP_VERSION`, `ORCH_INFRA_STOP_AFTER`; §11 `analyze --tools` alias,
  `reset-claims` theo run; §9 `estimate.detail`, `stats` superset; §3 `scan.item.msg ≤120`, `relabel.item`/50; §2 `date_field`;
  `config.reload()`, `--profile` trước argparse, clone `owner__repo`.
- 2026-10-05 đợt 2 (A5): route `raw/open/features/relabel/resume{workers}`; `overview.raw_by_tool`; `export.exists/manifest`;
  `runs.summary.relabeled`; `review/next` hết mẫu; `disagreements[].adjudicated`; `clean` 409. (A4): `profile/validate`,
  `settings/pick_dir`, `run/{id}/profile`, `POST /shell`; `preflight/fix.done`; `estimate.histogram/speed/db_exists`;
  profile `filters{}`; app.js component/ctx; `#/wizard/1?profile=`; `screens.css`. (A1): review `close/next` trường mở rộng,
  `adjudicated`, CLI `review … list`. (A2): `review --db`, `batch`, `diagnostics`, `phase=review`, `ORCH_M2_VOLUME`.
  (A3): `packaging/` không phải gói, 2 exe, `stop().cleanup.result`, tkinter exclude, `ORCH_DOCKER_BIN`. (A5 đợt 2): backend
  thuần `fn(params, body)`, progress poll `{lines,next}`, `clean` items, `diagnostics {path,bytes}`, lock chỉ do orchestrator
  tạo, `select` idempotent. (A4 đợt 2): `estimate` 425 `clone_pending`, `speed{}`, `preflight/fix {ok,detail,progress,done}`,
  SSE `?replay=0`, lỗi có `status`/`hint`, registry `smoke`, progress JSON.
- 2026-10-05 đợt 3–7: §4 `scan_tool_errors` + `raw_output.fmt='error'` (semgrep WinError 206); §6 `tool_error/tool_timeout`
  dạng `{commit,tool,tier}` + `cheap_infra_error`; `compare.explained_by` 6 khoá; `stats.cross_tool.anchor_gap`; timestamp local
  ISO; `.gitattributes` fixture; export ghi LF; `verify_run`, `results_report`; `review.sample.empty/message`.
- 2026-10-05 đợt 8 (hợp nhất): gộp §12 cũ vào §1–§11; đánh dấu **LỆCH** (§2 `_exp`, §7 `smoke`, §9 `run/start` body);
  thêm `?light=1`, `preflight_skipped`, route `finding/(?P<cluster_key>…)`.
- 2026-10-05 đợt 9 (trưởng quyết 3 LỆCH): (1) §2/§6 `_exp` **thêm vào mã** — `export_dataset.resolve_out_dir` gắn hậu tố khi
  `ORCH_EXPERIMENT=1`, trước `_2/_3`, manifest `experiment` giữ nguyên (test `test_export_experiment_gets_exp_suffix`);
  (2) §7 `smoke`/`preflight_skipped` ghi cả cấp bản ghi lẫn `summary`; (3) §9 `run/start` body: A5 đọc `profile, smoke,
  workers`; wrapper A4 xử lý `overwrite` (.bak), `formats`, `notify`, `preflight_skipped`; `resume` chỉ qua `/run/{id}/resume`.
