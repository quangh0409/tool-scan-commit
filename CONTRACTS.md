# CONTRACTS — Hợp đồng giao diện giữa các phần (đóng băng T0, 2026-10-05)

> Mọi agent tuân theo file này. **Không tự đổi hợp đồng**; cần đổi → ghi đề xuất vào báo cáo cuối, trưởng quyết. Kế hoạch: `TASKS.md`. Review nguồn: `REVIEW.md`. Quyết định phương pháp luận: `TOOL_IDEA_CONTEXT.md` §13.

## 0. Quy tắc chung cho agent

- **Không chạy Docker, không chạy pipeline thật.** Test bằng pytest với `subprocess` mock và DB fixture `tests/fixtures/scratch.db` (train-ticket 3 commit, schema hiện tại).
- Chỉ sửa file trong **vùng được giao** (TASKS.md §4). `cli.py`, `config.py` chỉ A2 sửa. Cần hook ở file của người khác → ghi vào báo cáo "YÊU CẦU LIÊN AGENT".
- Ba module dùng chung đã có, **import, không viết lại**: `src/orchestrator/progress.py`, `src/orchestrator/keys.py`, `src/orchestrator/profile.py`.
- Orchestrator (`src/orchestrator/**`) **stdlib-only**. `gui/`, `runner/`, `registry/`, `preflight/` được dùng `pywebview`, `playwright` (test). Không pyarrow.
- Chạy `python -m ruff check src scripts gui runner registry preflight tests` và `python -m pytest -q` trước khi commit. Commit nhỏ, message tiếng Việt, kết bằng dòng `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Encoding: mọi `open()` text có `encoding="utf-8"`; subprocess text có `errors="replace"`.
- Đường dẫn vào container luôn `.as_posix()`; đường dẫn host có thể chứa `'`, khoảng trắng, unicode.
- Báo cáo cuối (bắt buộc): việc đã làm (file), test đã chạy + kết quả, YÊU CẦU LIÊN AGENT, điều chưa làm được và vì sao, tên nhánh/worktree.

## 1. Phân loại trạng thái thống nhất (manifest, GUI, compare, DB)

| Giá trị | Nghĩa | Ghi ở đâu |
|---|---|---|
| `ok` | tool chạy xong, có kết quả (kể cả 0 finding) | `expensive_runs.status`, `scan_done` |
| `skipped` | commit không có module Java → không build/không phân tích. **Không** tính là verified | `expensive_runs.status` (tool=`maven`, phase=`build`) và các tool |
| `build_failed` | Maven rc≠0 vì **dữ liệu** (dependency mất, compile lỗi) | `selected_commits.status`, `expensive_runs` |
| `infra_error` | lỗi **hạ tầng**: Docker không kết nối (rc 125/127, stderr chứa `Cannot connect to the Docker daemon` / `error during connect` / `dockerDesktopLinuxEngine`), đĩa đầy (`disk is full`, `No space left`), mạng. Commit **về `pending`**, không đếm là dữ liệu. Sau **3 infra_error liên tiếp** → run tự dừng (`event=stop`, `status=infra_error`) | `expensive_runs`, progress |
| `tool_timeout` | `subprocess.TimeoutExpired` của 1 tool | `expensive_runs`, raw_output rỗng + lý do |
| `tool_error` | tool crash/parse lỗi (vd XML 0 byte) | `expensive_runs` |

`negative_level`: `verified-clean` **chỉ khi** `n_expensive_ok >= 2` (số tool đắt `status=ok` trên commit đó, loại `skipped`). Ngược lại `cheap-clean`.

## 2. `profile.json` (xem `src/orchestrator/profile.py`)

```json
{"schema":1,"repo":"https://github.com/FudanSELab/train-ticket","branch":"master",
 "scope":{"mode":"count","since":null,"until":null,"max":30,"from_sha":null,"to_sha":null},
 "include_clean":true,"cheap_tools":["gitleaks","trufflehog","semgrep","bearer","horusec"],
 "expensive_tools":["findsecbugs","sonar"],"codeql":false,"workers":{"scan":4,"expensive":1},
 "paths":{"db":"D:\\secjit\\results\\dataset_FudanSELab__train-ticket_master_20261005.sqlite",
          "export":"D:\\secjit\\results\\export_FudanSELab__train-ticket_master_20261005",
          "work":"D:\\secjit\\work"},
 "sonar_port":9100,"experiment":null,
 "params_v1":{"line_window":3,"gold_min_expensive":2,"gold_allow_1exp_1cheap":1,"silver_min_cheap":2,"noise_cwe":["CWE-117"]}}
```

- `scope.mode`: `time` (committer-date, ISO `YYYY-MM-DD`, ép `--max 0`), `count` (`max` > 0; **0 bị cấm** ở đây), `sha` (`from_sha..to_sha`, verify bằng `git rev-parse`), `all`.
- `params_v1` khác mặc định ⇒ bắt buộc `experiment={"enabled":true,"reason":"≥10 ký tự"}`; run gắn `experiment=1` trong `run_meta`, export sang thư mục có hậu tố `_exp`.
- `profile.to_env()` → env ORCH_*; `profile.to_cli_args()` → argv `pipeline …`; `profile.to_shell(p, "powershell"|"bash")` → lệnh tương đương. **A2** bảo đảm argparse nhận đủ `--since --until --from-sha --to-sha --tools --expensive-tools --profile`.
- Khi chạy từ profile: `pipeline --profile <file>` bỏ qua mọi arg khác; `run_meta.config_snapshot_json` lưu profile + env hiệu lực.

## 3. `progress.jsonl` (xem `src/orchestrator/progress.py`)

Một dòng JSON mỗi sự kiện: `{"ts","run_id","phase","event","done","total","worker","sha","status","msg"}`.
- `phase ∈ scan|select|analyze|relabel|kappa|export|review|stats`; `event ∈ start|item|done|error|stop`.
- `scan.start` phải có `total` (số commit sau lọc thô, sau RESUME). `analyze.start` có `total` = số `pending`.
- `analyze.item` có `worker`, `sha`, `status` (§1) và `msg` ngắn (vd `build 145s · fsb 41 · sonar 12`).
- Stop-file: `ORCH_STOP_FILE` tồn tại → orchestrator kết thúc commit hiện tại, **không claim commit mới**, emit `event=stop`, exit code 3. Kiểm **giữa** mỗi commit ở scan và analyze (`progress.should_stop()`).
- Env runner đặt: `ORCH_RUN_ID`, `ORCH_PROGRESS_FILE=<work>/<run_id>/progress.jsonl`, `ORCH_STOP_FILE=<work>/<run_id>/stop`, `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`, cùng `profile.to_env()`.

## 4. `run_meta` v2, `kappa`, `gold_review` (A1 tạo + migrate; A1 đợt 2 dùng gold_review)

```sql
-- user_version = 2
CREATE TABLE run_meta (
  id INTEGER PRIMARY KEY, run_id TEXT, tier TEXT CHECK(tier IN ('scan','analyze')),
  started_at TEXT, finished_at TEXT, repo TEXT, branch TEXT, scope_json TEXT,
  config_snapshot_json TEXT, tools_json TEXT,   -- [{name,image,version,digest}]
  orchestrator_git_sha TEXT, app_version TEXT, experiment INTEGER DEFAULT 0, reason TEXT);
CREATE TABLE kappa (run_id TEXT, scope TEXT, grp TEXT, value REAL, n INTEGER, computed_at TEXT);
  -- scope: 'total' | 'category' | 'cwe_group' | 'pair' ; grp: '' | 'code' | 'csrf' | 'semgrep|sonar'
CREATE TABLE gold_review (
  cluster_key TEXT, sample_id TEXT, rater TEXT, verdict TEXT CHECK(verdict IN ('TP','FP','unclear')),
  note TEXT, at TEXT, PRIMARY KEY (cluster_key, sample_id, rater));
CREATE TABLE gold_sample (sample_id TEXT, cluster_key TEXT, stratum TEXT, kind TEXT CHECK(kind IN ('pos','neg')),
  seed INTEGER, created_at TEXT, PRIMARY KEY (sample_id, cluster_key));
```
- Cột mới trên bảng cũ: `selected_commits.n_expensive_ok INTEGER DEFAULT 0`; `expensive_runs.run_id TEXT`.
- Migrate từ `user_version` 0/1: thêm bảng/cột nếu thiếu; giữ dữ liệu cũ (run_meta cũ → `tier='scan'`, `run_id='legacy'`).
- `PRAGMA journal_mode=WAL` khi mở để ghi; GUI mở `file:…?mode=ro` (`uri=True`).

## 5. `cluster_key` (xem `src/orchestrator/keys.py`)

`cluster_key = sha256(canon_repo|commit|file_path|cwe_group|s_line//LINE_WINDOW)[:32]`. Dùng cho `gold_review`, `gold_sample`, `compare`, map lại sau relabel. `keys.canon_repo()` là chuỗi repo chuẩn duy nhất dùng mọi nơi (run_meta.repo, registry, lock). `keys.repo_slug()` = `owner__repo` cho tên thư mục clone/DB.

## 6. Export & manifest (A1)

Thư mục export (mỗi run một thư mục, không ghi đè):
```
export_<slug>_<branch>_<yyyymmdd>/
  run_manifest.json   profile, run_meta (2 tier), kappa, counts{gold,silver,candidate,verified_clean,cheap_clean},
                      build_failed[], infra_error[], tool_timeout[], skipped[], orchestrator_git_sha, app_version,
                      os, docker_version, started, finished, params_v1, experiment
  dataset.jsonl       1 dòng = 1 cụm; thêm "cluster_key", "evidence":{"consensus":"gold|silver|candidate",
                      "validation":"unreviewed|TP|FP|unclear"}
  commits.jsonl       1 dòng = 1 commit; thêm "n_expensive_ok", "negative_level"
  negatives.json · SHA256SUMS (dataset.jsonl, commits.jsonl, run_manifest.json) · <sha12>/ (raw từng tool)
```

## 7. Runner, registry, lock (A3)

- `runner.start(profile_path, run_id) -> pid`: tiến trình tách rời (`subprocess.Popen(..., creationflags=CREATE_NEW_PROCESS_GROUP|DETACHED_PROCESS, close_fds=True, stdin=DEVNULL, stdout/stderr -> <work>/<run_id>/run.log)`; Linux `start_new_session=True`). Lệnh: `python -m orchestrator.cli pipeline --profile <file>` với env §3. Ghi `<work>/<run_id>/pid`.
- `runner.alive(pid)`, `runner.stop(run_id, force=False)`: tạo stop-file; `force` → `taskkill /T /F /PID` (Win) / SIGTERM nhóm (Linux) rồi gọi `orchestrator.cli stop-cleanup --run <id>` (A2 `control.py`: dọn container `--filter label=orch.run=<id>`, gỡ network, `reset-claims`).
- `registry` tại `%LOCALAPPDATA%\secjit\runs.json` (Linux `~/.local/share/secjit/runs.json`): `{"runs":[{"run_id","repo","branch","db","export","work","profile","started","finished","status":"running|stopped|done|failed|interrupted","pid","summary":{...}}]}`; ghi atomic (tmp + replace). `status=interrupted` khi pid chết mà DB còn `building/analyzing`.
- Lock: `<db>.lock` (file chứa pid + run_id); single-instance GUI: mutex tên `secjit-gui` (Windows) / lock-file.
- `speed.json` (`%LOCALAPPDATA%\secjit\speed.json`): `{"cheap_s_per_commit","build_cold_s","build_warm_s","fsb_s","sonar_s","samples"}` cập nhật từ `expensive_runs.duration_sec` + progress.

## 8. Preflight (A3) — 13 mục, 3 mức

`preflight.run(fix=False) -> {"items":[{"id","title","level":"ok|fix|warn|bad","detail","fix_available","fix_id"}],"ready":bool,"docker_mem_gb","cpu"}`.
Mục: `os_wsl2`, `docker_installed`, `docker_daemon` (fix: bật Docker Desktop + poll 90 s), `docker_mem` (từ `docker info --format {{.MemTotal}}`; < 6 GB → warn, gợi ý `.wslconfig`), `sonar_port` (fix: dò 9000→9100→9200…), `disk_free` (so ước tính), `git` (fix: hướng dẫn winget), `git_longpaths` (fix: `git config --global core.longpaths true`), `images` (5 rẻ pull; `orch-findsecbugs` **build** từ `docker/findsecbugs`; `maven:3.9-eclipse-temurin-8`; `sonarqube:lts-community`; `sonarsource/sonar-scanner-cli`; codeql tuỳ chọn) (fix: pull/build có tiến độ), `images_pinned` (warn `:latest`), `max_map_count` (đọc `wsl -d docker-desktop sysctl vm.max_map_count`; warn), `network` (github.com, registry-1.docker.io), `webview2` (warn). `preflight --json` in JSON ra stdout, exit 0/1.

## 9. API GUI (A4 server; A4/A5 màn; fixture `gui/fixtures/`)

Server: `python -m gui [--dev] [--mock] [--port N]`. Localhost, cổng ngẫu nhiên nếu không chỉ định, header `X-Token: <token>` (token in ra stdout và truyền vào URL `/?t=`). JSON UTF-8. Lỗi: `{"error":{"code","message","hint"}}` với HTTP 4xx/5xx.

| Method & path | Body → Trả về | Fixture |
|---|---|---|
| `GET /api/preflight` | → §8 | `preflight.json`, `preflight_fixed.json` |
| `POST /api/preflight/fix` | `{fix_id}` → `{ok, detail, progress?}` | — |
| `POST /api/repo/check` | `{url}` → `{canon, slug, public, default_branch, branches[], tags[], java_maven, jdk, modules, snapshot_risk, security_config_count, commit_count|null, warnings[]}` | `repo_check.json` |
| `POST /api/estimate` | `{profile}` → `{commits_after_filter, buggy_est, cheap_minutes, expensive_minutes_cold, expensive_minutes_warm, disk_gb, speed_source:"measured|default"}` | `estimate.json` |
| `POST /api/run/start` | `{profile, smoke:false}` → `{run_id, pid}`; `smoke=true` → `--max 3` vào DB scratch | — |
| `POST /api/run/{id}/stop` | `{force}` → `{ok, cleaned:[...]}` | — |
| `POST /api/run/{id}/resume` | → `{run_id, pid, from_phase}` | — |
| `GET /api/runs` | → `{runs:[registry §7 + summary]}` | `runs.json` |
| `GET /api/run/{id}/progress` | SSE `data: <progress line>`; lúc kết nối gửi lại 200 dòng cuối | `progress.jsonl` |
| `GET /api/results/{id}/overview` | → `{funnel:{commits,after_filter,buggy,clean,built,build_failed,skipped,infra_error}, labels:{gold,silver,candidate,verified_clean,cheap_clean}, by_cwe_group:[{group,gold,silver,candidate}], kappa:{total,by_category[],by_group[],pairs[]}, coverage:{one,two,three_plus}, precision:{n,tp,fp,ci_low,ci_high}|null, limits:[...câu], params_v1, experiment}` | `overview.json` |
| `GET /api/results/{id}/findings?label=&cwe_group=&min_tools=&tier=&in_diff=&q=&page=&size=` | → `{total, page, size, rows:[{cluster_key, commit, file_path, s_line, cwe_group, cwe[], tools[], n_agree, tier, label, evidence, in_diff}]}` | `findings.json` |
| `GET /api/results/{id}/finding/{cluster_key}` | → `{row, diff_lines:[{n, kind:"ctx|add|del|flag", text}], tool_messages:[{tool, rule_id, severity, message, raw_path}], provenance:{run_id, tools_json, line_window, gold_rule}, eligible:{tools[], denominator}}` | `finding.json` |
| `GET /api/results/{id}/commits?page=&size=` | → `{total, rows:[{commit, date, role, status, n_expensive_ok, negative_level, kamei{...}, build_error}]}` | `commits.json` |
| `POST /api/results/{id}/export` | `{formats:["jsonl","csv"]}` → `{export_dir, files[]}` | — |
| `POST /api/review/{id}/sample` | `{seed, n_pos, n_neg}` → `{sample_id, n_pos, n_neg, strata[]}` | `review_sample.json` |
| `GET /api/review/{id}/next?sample_id=&rater=` | → `{cluster_key, code_lines[], diff_lines[], cwe_claim, messages_anon[], remaining}` (ẨN nhãn/tool) | `review_item.json` |
| `POST /api/review/{id}/verdict` | `{sample_id, rater, cluster_key, verdict, note}` → `{ok, remaining}` | — |
| `POST /api/review/{id}/close` | `{sample_id}` → `{precision:{tp,fp,unclear,n,point,ci_low,ci_high}, kappa_raters|null, disagreements[]}` | `review_close.json` |
| `GET /api/settings` / `POST /api/settings` | `{language, out_dir, work_dir, sonar_port, codeql_ram_mb, m2_volume}` | `settings.json` |
| `GET /api/storage` | → `{items:[{id, title, path, bytes, safety:"safe|slow|rebuild|forbidden", detail}], total_bytes, free_bytes}` | `storage.json` |
| `POST /api/clean` | `{items[], dry_run}` → `{would_delete:[{path,bytes}], deleted[], errors[]}`; **từ chối** khi có run `running` dùng path đó | `clean_dry.json` |
| `GET /api/profiles` · `POST /api/profiles` · `DELETE /api/profiles/{name}` | lưu `%LOCALAPPDATA%\secjit\profiles\<name>.json` | `profiles.json` |
| `GET /api/shell?profile=&shell=powershell|bash` | → `{command}` từ `profile.to_shell` | — |
| `GET /api/diagnostics` | → zip (log, run_meta, docker info, profile, preflight.json) | — |

## 10. Web UI (A4 khung, A4 màn 0–5, A5 màn 6–10)

- Vanilla HTML/CSS/JS (ES2020), không framework, không CDN. `gui/web/index.html` + `app.css` + `app.js` (router hash `#/preflight`, `#/home`, `#/wizard/1..5`, `#/run/<id>`, `#/results/<id>/<tab>`, `#/review/<id>`, `#/settings/<tab>`), `screens/<tên>.js` export `render(root, ctx)` và `destroy()`.
- Design token lấy từ wireframe `scratchpad/wire/project/*.dc.html`: nền `#E9ECF0`, header `#142233`, nav `#1B2A3B`, nhấn `#1F5F8B`, ok `#1B7F4D`, fix `#A1540A`, bad `#B42318`, warn `#7A5B00`, gold `#FBE7B2/#6B4E00`, silver `#E3E7EC/#3B4654`; font `IBM Plex Sans` fallback `system-ui`, mono `IBM Plex Mono` (font nhúng offline hoặc fallback — không CDN).
- Component chung trong `app.js`: `btn, card, table (phân trang), stepper, toast, dialog(confirm/typed-confirm), empty, errorBox, skeleton, badgeLabel(label, evidence)` — `badgeLabel` luôn hiện "gold · đồng thuận máy" / "gold ✓ TP" / "gold ✗ FP".
- i18n: `gui/web/i18n/vi.json`, `en.json`; `t("key")`; thiếu khoá → hiện khoá (để QA bắt).
- Mỗi màn bắt buộc có trạng thái: `loading` (skeleton), `empty`, `error` (errorBox + Thử lại), `partial` khi backend trả thiếu. Dashboard thêm `interrupted`, `docker_down`, `disk_full`, `infra_stop`. Không hiển thị nhãn tạm khi run `running` (chỉ đếm raw).
- Playwright: `tests/gui/shoot.py --mock --out <dir>` chụp từng `#/route` × trạng thái (query `?state=empty|error|loading` được mock server tôn trọng) ra PNG 1280×900.

## 11. Lệnh CLI mới (A2) — chữ ký

```
pipeline <repo> [--profile F] [--branch B] [--max N] [--since D] [--until D] [--from-sha S] [--to-sha S]
                [--tools a,b] [--expensive-tools a,b] [--codeql 0|1] [--include-clean] [--workers K] [--out DIR]
estimate   --profile F                      -> JSON (§9 estimate)
stats      [--db DB] [--run-id ID] [--format json|csv|latex] [--out DIR]   -> overview §9
sensitivity --db DB --out DIR [--grid line_window=3,5,7 gold_allow_1exp_1cheap=0,1 noise=on,off]  (chạy trên BẢN SAO)
compare    --a <export_dir|db> --b <export_dir|db> [--format json|md]  -> {same, only_a, only_b, label_changed, explained_by:{tool_timeout,infra_error,skipped}}
stop       --run ID [--force]  ;  stop-cleanup --run ID  ;  reset-claims --run ID [--all-stale]
clean      <repo> [--items clone,pool,m2,export:<dir>,db:<path>] [--dry-run]   (không còn --all; export/db phải chỉ rõ đường dẫn)
review     sample --db DB --seed N --n-pos 200 --n-neg 100 | close --db DB --sample-id ID [--raters a,b]
```
Mọi lệnh in JSON khi `--json`. Exit code: 0 ok · 1 lỗi tham số · 2 lỗi runtime · 3 dừng theo stop-file.


## 12. Hiệu chỉnh hợp đồng đã chấp nhận (trưởng, T+2)

- §7 runner: chữ ký thật `runner.start(profile_path, run_id, work_dir, python_exe=sys.executable, extra_env=None) -> {pid, log, progress, stop, run_dir, meta, argv}`; `runner.stop(run_id, work_dir, force=False, timeout_s=10.0, python_exe=None, cleanup=None) -> {ok, stop_file, pid, alive_before, killed, alive_after, cleanup}`; `runner.attach(run_id, work_dir) -> {run_id, pid, alive, last_progress_line, interrupted, status, meta, log, run_dir, exists}`.
- §7 registry: env `SECJIT_HOME` override `%LOCALAPPDATA%\secjit`; `registry.refresh_status()` trả danh sách run đổi trạng thái; `speed.json` thêm `buggy_ratio`, `updated`.
- §8 preflight: `run()` trả thêm `codeql_ram_mb`, `sonar_port`, `fixed`, `elapsed_s`, `os`, `ts`; 6 auto-fix (thêm `max_map_count` và `lower_codeql_ram`).
- §11 `stop-cleanup`: exit 0 kể cả khi không có gì để dọn; `--json`; `reset-claims` theo `claimed_by` của run.
- §1 build timeout (A1): `expensive_runs.status='tool_timeout'` với `tool=maven`, commit → `build_failed`, `build_status='timeout'`.
- §3 `analyze.item.worker` = `wN`; `selected_commits.claimed_by` = `<run_id>:wN`. GUI đối chiếu bằng `endswith(":"+worker)`.
- §4 storage API (A1): `SQLiteStore(path=None, readonly=False)`; `insert_run_meta(tier, **fields)`, `finish_run_meta`, `save_kappa`, `kappa_rows`, `reset_claims(run_id|None)`, `reset_expensive_raw`, `pid_alive`, `read_lock(db)`; lock-file `<db>.lock` JSON `{pid, run_id, at}`; `storage.InfraError`; `repo_pool.rmtree_force`.
- §6 manifest thêm `tool_error[]`, `python`, `db`, `export_dir`, `run_id`; `experiment` = `null | {enabled, reason}`; export LUÔN sang thư mục mới (`_2`, `_3`…) nếu đích không rỗng. `export_all(store, out_dir, profile=None, run_id=None)` trả `res['out']`.
- Env đọc trực tiếp bởi A1 (A2 thêm vào config/GUIDE): `ORCH_EXPERIMENT`, `ORCH_EXPERIMENT_REASON`, `SECJIT_APP_VERSION` (mặc định `dev`), `ORCH_INFRA_STOP_AFTER` (3).
- §11 (A2): `analyze --tools` là alias cũ (cảnh báo), sẽ bỏ; `reset-claims --run ID` theo `claimed_by '<run_id>:wN'`, `--all-stale` bỏ lọc run; `reset_claims` giữ `expensive_runs` (telemetry) — khác quy trình tay 2026-07-08, chấp nhận.
- §9 `estimate` trả thêm `detail{}`; `stats` trả superset (`db`, `run_id`, `kappa.n`, `precision.unclear/point`).
- §3: `scan.item.msg` ≤120 ký tự; `relabel.item` mỗi 50 commit. §2: `scope_json` có `date_field:"committer"`.
- `config.reload()` tồn tại; `--profile` áp env TRƯỚC argparse; `clone_or_update` fetch mỗi lần (offline → cảnh báo), tên clone `owner__repo` (giữ tên cũ nếu origin khớp).
- §9 (A5): thêm `GET /api/results/{id}/raw?path=` (text thô; 404), `POST /api/open {path}` (mở thư mục; 501 nếu không hỗ trợ), `POST /api/results/{id}/features`, `POST /api/results/{id}/relabel` (chỉ experiment), `POST /api/run/{id}/resume {workers?}`; `overview.raw_by_tool{}`; `export.exists`, `export.manifest`; `/api/runs` summary thêm `relabeled: bool`; `review/next` hết mẫu → `{cluster_key:null, remaining:0}`; `review/close.disagreements[].adjudicated`; `POST /api/clean` → 409 khi run đang dùng path.
- §10 (A5): `ctx.sse(path, onLine) -> closer()` (token qua `?t=`), `ctx.url(path)` (URL kèm token); lỗi API reject `{status, error:{code,message,hint}}`; `table` nhận `onRow, rowKey, selected, emptyMsg`; `dialog` nhận `cancelText, kind` và trả `<dialog>`; `card(children, {title, extraClass})`; route `#/wizard/1?profile=<name>`; `index.html` import `screens/screens.css`; giữ `screens/_util.js`.
- §9 (A4): thêm `POST /api/profile/validate {profile} → {errors[], warnings[], db_exists, export_exists, db_user_version}`, `POST /api/settings/pick_dir {initial,title} → {path}` (501 nếu không có hộp thoại), `GET /api/run/{id}/profile → {profile}`, `POST /api/shell {profile, shell}`; `preflight/fix` trả thêm `done: bool` (client poll khi false); `estimate` thêm `histogram[{month,n}]`, `speed{}`, `db_exists`. `run/start` body `{profile, smoke, formats, notify, resume, overwrite}`. Profile có thể mang `filters:{clean_per_buggy, require_in_diff}` (A2 map sang env `ORCH_CLEAN_PER_BUGGY`/`ORCH_SUSPECT_REQUIRE_IN_DIFF` nếu kịp).
- §10 (A4): component có sẵn trong `app.js`: `h, btn, busy, card, table, stepper, toast, dialog, empty, errorBox, skeleton, badgeLabel, badgeStatus, notice, progress, api, sse, fmt, copyText, preflightCache, refreshPreflight`; `ROUTES` khai sẵn cho màn A5; `api()` chuyển tiếp `?state=`; Wizard 5 → `#/run/<id>?smoke=1`.
- §9/§11 review (A1): `close` trả thêm `neg_precision`, `by_stratum`, `primary_rater`, `n_adjudicated`, `unreviewed`, `precision.n_reviewed`, `precision.ci:"wilson95"`; `kappa_raters` chỉ 2 rater người; `next` có `kind`, `stratum`, `files[]/file_urls[]` (mục âm), `code_lines[].flag`, `remaining` tính cả mục đang trả; verdict "TP = nhãn máy đúng" (mục âm: TP = thật sự sạch); rater hoà giải = `adjudicated`; CLI `review sample|next|verdict|close|list`. Hàm public: `review.sample/next_item/verdict/close/summary/validation_of/wilson/cohen_kappa/allocate`.
