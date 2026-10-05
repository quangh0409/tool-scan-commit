"""
Lưu DatasetRow vào SQLite (stdlib). list[str]/cwe -> JSON text.

Schema user_version=2 (CONTRACTS §4): run_meta v2 (run_id, tier), kappa, gold_review, gold_sample,
selected_commits.n_expensive_ok, expensive_runs.run_id. Migrate từ 0/1 giữ dữ liệu.

Mở GHI: PRAGMA journal_mode=WAL + busy_timeout=5000 + lock-file `<db>.lock` (pid + run_id) chống
2 run cùng DB (REVIEW D3/D8). Mở ĐỌC (GUI): `SQLiteStore(path, readonly=True)` -> `file:…?mode=ro`,
không lock, không migrate.

Lỗi hạ tầng khi ghi (đĩa đầy: OperationalError "disk…", OSError ENOSPC) -> raise InfraError (D6).
"""
from __future__ import annotations

import errno
import json
import os
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .. import config, progress
from ..schema import DatasetRow
from . import InfraError

USER_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT, commit_id TEXT, parent_commit TEXT,
    commit_message TEXT, author_date TEXT,
    file_path TEXT NOT NULL,
    s_line INTEGER NOT NULL,          -- BẮT BUỘC
    e_line INTEGER, function TEXT,
    s_detail_line TEXT NOT NULL,      -- JSON list các dòng cụ thể, BẮT BUỘC
    finding_in_diff INTEGER,          -- 1=lỗi commit này tạo, 0=nợ cũ, NULL=?
    tool TEXT, rule_id TEXT, severity TEXT,
    cwe TEXT NOT NULL,                -- JSON list, BẮT BUỘC
    cwe_group TEXT, category TEXT,    -- nhóm đồng thuận + secret/code/infra/crypto/info/other
    verified INTEGER,                 -- secret verified? (1/0/NULL)
    owasp TEXT, cve TEXT,
    lines_added INTEGER, lines_deleted INTEGER,
    code_snippet TEXT,
    diff_parsed TEXT,                 -- JSON {added:[[ln,txt]],deleted:[[ln,txt]]}
    code_before_url TEXT, code_after_url TEXT,
    code_before TEXT, code_after TEXT,
    n_tools_ran INTEGER, n_tools_agree INTEGER,
    agreeing_tools TEXT, agreement_ratio REAL,
    confidence REAL, silver_label TEXT,  -- alias legacy của label
    tier TEXT DEFAULT 'cheap',           -- cheap | expensive | mixed
    label TEXT,                          -- gold | silver | candidate (cross-tier)
    n_cheap INTEGER, n_expensive INTEGER, eligible INTEGER,
    kamei TEXT                           -- JSON 14 đặc trưng Kamei cấp commit
);
CREATE INDEX IF NOT EXISTS idx_commit ON findings(commit_id);
CREATE INDEX IF NOT EXISTS idx_cwe ON findings(cwe);
CREATE INDEX IF NOT EXISTS idx_cat ON findings(category);
CREATE INDEX IF NOT EXISTS idx_label ON findings(label);

-- RAW: mỗi finding TỪNG-TOOL (trước gộp cụm) — nguồn để recompute nhãn + Fleiss' kappa.
CREATE TABLE IF NOT EXISTS raw_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT, commit_id TEXT, tool TEXT, tier TEXT,
    file_path TEXT, s_line INTEGER, e_line INTEGER,
    cwe TEXT,                            -- JSON list
    rule_id TEXT, severity TEXT, message TEXT, verified INTEGER,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_raw_commit ON raw_findings(commit_id);

-- (B) OUTPUT THÔ nguyên bản mỗi tool/commit (SARIF/XML/JSON…) — audit + tái lập 100%.
CREATE TABLE IF NOT EXISTS raw_output (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    commit_id TEXT, tool TEXT, tier TEXT, fmt TEXT,   -- json|jsonl|sarif|xml
    content TEXT, created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_rawout_commit ON raw_output(commit_id);

-- MẪU SỐ: mọi (commit, file) đã quét + số finding. n_findings=0 => negative/clean.
-- Cần để dựng confusion matrix (benchmark) và có NEGATIVE thật cho train.
CREATE TABLE IF NOT EXISTS scanned_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT, commit_id TEXT, parent_commit TEXT, author_date TEXT,
    file_path TEXT NOT NULL,
    n_findings INTEGER NOT NULL,
    n_tools_ran INTEGER, tools TEXT,   -- JSON list tool đã chạy
    label TEXT NOT NULL                -- clean (0 finding) | has_finding
);
CREATE INDEX IF NOT EXISTS idx_sf_commit ON scanned_files(commit_id);
CREATE INDEX IF NOT EXISTS idx_sf_label ON scanned_files(label);

-- TÁI LẬP (v2, CONTRACTS §4): 1 hàng / (run, tier). tools_json = [{name,image,version,digest}].
CREATE TABLE IF NOT EXISTS run_meta (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT, tier TEXT CHECK(tier IN ('scan','analyze')),
    started_at TEXT, finished_at TEXT, repo TEXT, branch TEXT, scope_json TEXT,
    config_snapshot_json TEXT, tools_json TEXT,
    orchestrator_git_sha TEXT, app_version TEXT, experiment INTEGER DEFAULT 0, reason TEXT
);

-- Fleiss' kappa đã tính (scope: total | category | cwe_group | pair ; grp: '' | 'code' | 'semgrep|sonar').
CREATE TABLE IF NOT EXISTS kappa (
    run_id TEXT, scope TEXT, grp TEXT, value REAL, n INTEGER, computed_at TEXT
);

-- Kiểm tay mù (đợt 2): verdict từng rater trên 1 cụm (cluster_key, keys.py).
CREATE TABLE IF NOT EXISTS gold_review (
    cluster_key TEXT, sample_id TEXT, rater TEXT,
    verdict TEXT CHECK(verdict IN ('TP','FP','unclear')),
    note TEXT, at TEXT,
    PRIMARY KEY (cluster_key, sample_id, rater)
);
CREATE TABLE IF NOT EXISTS gold_sample (
    sample_id TEXT, cluster_key TEXT, stratum TEXT,
    kind TEXT CHECK(kind IN ('pos','neg')),
    seed INTEGER, created_at TEXT,
    PRIMARY KEY (sample_id, cluster_key)
);

-- HÀNG ĐỢI TẦNG ĐẮT (hợp đồng rẻ->đắt): commit được chọn để tool đắt quét.
--   role=buggy  : tầng rẻ đánh dấu đáng nghi (có mã CWE/CVE) -> bắt buộc quét.
--   role=clean  : commit 0-finding, lấy MẪU theo tỉ lệ 1 buggy : N clean (negative cân bằng).
-- Vòng đời status: pending -> building -> built -> analyzing -> done
--                                    \\-> build_failed (terminal) ; analyzing -> error (retry)
--   infra_error (Docker/đĩa) -> quay về pending, KHÔNG phải dữ liệu.
CREATE TABLE IF NOT EXISTS selected_commits (
    commit_id TEXT PRIMARY KEY,
    role TEXT NOT NULL,             -- buggy | clean
    selection_reason TEXT,
    suspect_categories TEXT,        -- JSON list
    n_suspect_findings INTEGER,
    created_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    claimed_by TEXT, claimed_at TEXT, finished_at TEXT,
    build_status TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    n_expensive_ok INTEGER DEFAULT 0  -- số tool đắt phase=analyze status=ok (loại skipped)
);
CREATE INDEX IF NOT EXISTS idx_sel_role ON selected_commits(role);
-- idx_sel_status tạo SAU migration (DB cũ chưa có cột status khi chạy _SCHEMA).

-- 14 ĐẶC TRƯNG KAMEI (JIT defect prediction) cấp COMMIT — tính từ git history (kamei.py).
-- Độc lập findings: commit NEGATIVE (0 finding) vẫn có đặc trưng.
CREATE TABLE IF NOT EXISTS commit_features (
    commit_id TEXT PRIMARY KEY,
    repo TEXT, author TEXT, author_date TEXT,
    ns INTEGER, nd INTEGER, nf INTEGER, entropy REAL,   -- diffusion
    la INTEGER, ld INTEGER, lt REAL,                    -- size
    fix INTEGER,                                        -- purpose
    ndev INTEGER, age REAL, nuc INTEGER,                -- history
    exp INTEGER, rexp REAL, sexp INTEGER,               -- experience
    created_at TEXT
);

-- Mốc RESUME tầng rẻ: commit đã quét TRỌN (ghi CUỐI _scan_one_commit).
-- KHÔNG dùng scanned_files làm mốc: commit 0-file-code không có row nào ở đó.
CREATE TABLE IF NOT EXISTS scan_done (
    commit_id TEXT PRIMARY KEY,
    finished_at TEXT
);

-- TELEMETRY tầng đắt: 1 dòng / (commit, tool, phase). status theo CONTRACTS §1:
--   ok | skipped | build_failed | infra_error | tool_timeout | tool_error
CREATE TABLE IF NOT EXISTS expensive_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    commit_id TEXT, tool TEXT, phase TEXT,    -- build | analyze | process
    status TEXT,
    n_findings INTEGER, duration_sec REAL,
    error TEXT, created_at TEXT,
    run_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_exp_commit ON expensive_runs(commit_id);
"""

# Cột mới của selected_commits cần ALTER khi DB cũ đã tạo bảng (CREATE IF NOT EXISTS không thêm cột).
_SELECTED_NEW_COLS = {
    "status": "TEXT NOT NULL DEFAULT 'pending'",
    "claimed_by": "TEXT", "claimed_at": "TEXT", "finished_at": "TEXT",
    "build_status": "TEXT", "attempts": "INTEGER NOT NULL DEFAULT 0",
    "n_expensive_ok": "INTEGER DEFAULT 0",
}

_RUN_META_V2_COLS = ["run_id", "tier", "started_at", "finished_at", "repo", "branch", "scope_json",
                     "config_snapshot_json", "tools_json", "orchestrator_git_sha", "app_version",
                     "experiment", "reason"]

_COLS = [
    "repo", "commit_id", "parent_commit", "commit_message", "author_date",
    "file_path", "s_line", "e_line", "function", "s_detail_line", "finding_in_diff",
    "tool", "rule_id", "severity", "cwe", "cwe_group", "category", "verified",
    "owasp", "cve",
    "lines_added", "lines_deleted", "code_snippet",
    "diff_parsed", "code_before_url", "code_after_url", "code_before", "code_after",
    "n_tools_ran", "n_tools_agree", "agreeing_tools", "agreement_ratio",
    "confidence", "silver_label", "tier",
    "label", "n_cheap", "n_expensive", "eligible", "kamei",
]
_JSON_COLS = {"cwe", "agreeing_tools", "s_detail_line", "diff_parsed", "kamei"}

# 14 đặc trưng Kamei — thứ tự cột trong commit_features
_KAMEI_COLS = ["ns", "nd", "nf", "entropy", "la", "ld", "lt", "fix",
               "ndev", "age", "nuc", "exp", "rexp", "sexp"]

_DISK_ERR_MARKERS = ("disk", "database or disk is full", "no space left")


def _now() -> str:
    """Thời điểm local ISO `%Y-%m-%dT%H:%M:%S` — thống nhất với progress.ts (datetime('now') của SQLite là UTC)."""
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _is_disk_error(msg: str) -> bool:
    m = (msg or "").lower()
    return any(k in m for k in _DISK_ERR_MARKERS)


# ---------------------------------------------------------------------------
# pid alive (cross-platform). KHÔNG dùng os.kill(pid, 0) trên Windows: signal 0 không phải
# CTRL_*_EVENT nên CPython gọi TerminateProcess -> GIẾT tiến trình kia.
# ---------------------------------------------------------------------------
def pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lock_path_for(db_path: Path) -> Path:
    return Path(str(db_path) + ".lock")


def read_lock(db_path: Path) -> dict | None:
    """Nội dung lock-file {pid, run_id, at} hoặc None nếu không có/hỏng."""
    lp = lock_path_for(db_path)
    try:
        with open(lp, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


class SQLiteStore:
    def __init__(self, path: Path | None = None, readonly: bool = False):
        self.readonly = readonly
        self.path = Path(path or config.SQLITE_PATH)
        self._lock = threading.Lock()
        self._lock_file: Path | None = None
        if readonly:
            # GUI/so sánh: không tạo lock, không migrate, không WAL-switch (mode=ro).
            uri = self.path.resolve().as_uri() + "?mode=ro"
            self.conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
            self.conn.execute("PRAGMA busy_timeout=5000")
            return
        config.ensure_dirs()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._acquire_lock()
        # check_same_thread=False: worker song song (cấp commit) cùng ghi 1 connection;
        # mọi ghi được bọc trong self._lock -> SQLite tự serialize, an toàn.
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        with self._guard():
            self.conn.execute("PRAGMA busy_timeout=5000")
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.executescript(_SCHEMA)
            self._migrate_selected()
            self._migrate_findings()
            self._migrate_v2()
            # index trên cột status: tạo SAU migration (đảm bảo cột tồn tại)
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sel_status ON selected_commits(status)")
            self.conn.commit()

    # ---------------- lock-file (D3) ----------------
    def _acquire_lock(self) -> None:
        lp = lock_path_for(self.path)
        cur = read_lock(self.path)
        if cur:
            pid = int(cur.get("pid") or 0)
            if pid_alive(pid):
                raise RuntimeError(
                    f"DB đang được run khác dùng: {self.path} (pid={pid}, "
                    f"run_id={cur.get('run_id')}). Dừng run đó hoặc dùng DB khác.")
        tmp = Path(str(lp) + f".{os.getpid()}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"pid": os.getpid(), "run_id": progress.run_id(),
                           "at": _now()}, f)
            os.replace(tmp, lp)
        except OSError as e:
            if e.errno == errno.ENOSPC:
                raise InfraError(f"đĩa đầy khi tạo lock {lp}") from e
            raise
        self._lock_file = lp

    def _release_lock(self) -> None:
        if not self._lock_file:
            return
        cur = read_lock(self.path)
        if cur and int(cur.get("pid") or 0) == os.getpid():
            try:
                self._lock_file.unlink()
            except OSError:
                pass
        self._lock_file = None

    # ---------------- lỗi hạ tầng (D6) ----------------
    @contextmanager
    def _guard(self):
        try:
            yield
        except sqlite3.OperationalError as e:
            if _is_disk_error(str(e)):
                raise InfraError(f"SQLite lỗi đĩa: {e}") from e
            raise
        except OSError as e:
            if e.errno == errno.ENOSPC or _is_disk_error(str(e)):
                raise InfraError(f"đĩa đầy: {e}") from e
            raise

    @contextmanager
    def _write(self):
        """Khoá + bắt lỗi hạ tầng cho mọi thao tác ghi."""
        with self._lock:
            with self._guard():
                yield

    # ---------------- migration ----------------
    def _cols(self, table: str) -> set[str]:
        return {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}

    def _migrate_selected(self) -> None:
        """Thêm cột lifecycle nếu DB cũ đã có selected_commits dạng thiếu cột."""
        have = self._cols("selected_commits")
        for col, decl in _SELECTED_NEW_COLS.items():
            if col not in have:
                self.conn.execute(f"ALTER TABLE selected_commits ADD COLUMN {col} {decl}")

    def _migrate_findings(self) -> None:
        """Thêm cột mới nếu DB cũ đã có findings thiếu cột."""
        have = self._cols("findings")
        for col, decl in {"tier": "TEXT DEFAULT 'cheap'", "label": "TEXT",
                          "n_cheap": "INTEGER", "n_expensive": "INTEGER",
                          "eligible": "INTEGER", "kamei": "TEXT"}.items():
            if col not in have:
                self.conn.execute(f"ALTER TABLE findings ADD COLUMN {col} {decl}")

    def _migrate_v2(self) -> None:
        """user_version 0/1 -> 2 (CONTRACTS §4). Idempotent, giữ dữ liệu cũ."""
        ver = self.conn.execute("PRAGMA user_version").fetchone()[0]
        # expensive_runs.run_id
        if "run_id" not in self._cols("expensive_runs"):
            self.conn.execute("ALTER TABLE expensive_runs ADD COLUMN run_id TEXT")
        # run_meta cũ (started_at, repo, max_commits, vote_threshold, line_window, tools) -> v2
        rm_cols = self._cols("run_meta")
        if "run_id" not in rm_cols:
            self.conn.execute("ALTER TABLE run_meta RENAME TO run_meta_v1")
            self.conn.execute(
                "CREATE TABLE run_meta (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, "
                "tier TEXT CHECK(tier IN ('scan','analyze')), started_at TEXT, finished_at TEXT, "
                "repo TEXT, branch TEXT, scope_json TEXT, config_snapshot_json TEXT, tools_json TEXT, "
                "orchestrator_git_sha TEXT, app_version TEXT, experiment INTEGER DEFAULT 0, reason TEXT)")
            for r in self.conn.execute(
                    "SELECT id, started_at, repo, max_commits, vote_threshold, line_window, tools "
                    "FROM run_meta_v1 ORDER BY id"):
                scope = {"mode": "all" if not r[3] else "count", "max": r[3]}
                snap = {"max_commits": r[3], "vote_threshold": r[4], "line_window": r[5],
                        "migrated_from": "run_meta_v1"}
                self.conn.execute(
                    "INSERT INTO run_meta (id, run_id, tier, started_at, repo, scope_json, "
                    "config_snapshot_json, tools_json, experiment) VALUES (?,?,?,?,?,?,?,?,0)",
                    [r[0], "legacy", "scan", r[1], r[2], json.dumps(scope),
                     json.dumps(snap), r[6]])
            self.conn.execute("DROP TABLE run_meta_v1")
        else:
            for col, decl in {"finished_at": "TEXT", "branch": "TEXT", "scope_json": "TEXT",
                              "config_snapshot_json": "TEXT", "tools_json": "TEXT",
                              "orchestrator_git_sha": "TEXT", "app_version": "TEXT",
                              "experiment": "INTEGER DEFAULT 0", "reason": "TEXT"}.items():
                if col not in rm_cols:
                    self.conn.execute(f"ALTER TABLE run_meta ADD COLUMN {col} {decl}")
        # backfill n_expensive_ok cho DB cũ (verified-clean cũ có thể bị tính sai — REVIEW D1)
        if ver < USER_VERSION:
            self.conn.execute(
                "UPDATE selected_commits SET n_expensive_ok = ("
                " SELECT COUNT(DISTINCT tool) FROM expensive_runs e WHERE e.commit_id=selected_commits.commit_id"
                " AND e.phase='analyze' AND e.status='ok' AND e.tool NOT IN ('-','maven'))")
            self.conn.execute(f"PRAGMA user_version={USER_VERSION}")

    # ---------------- findings ----------------
    def insert_rows(self, rows: list[DatasetRow]) -> int:
        if not rows:
            return 0
        placeholders = ",".join("?" * len(_COLS))
        sql = f"INSERT INTO findings ({','.join(_COLS)}) VALUES ({placeholders})"
        payload = []
        for r in rows:
            d = r.as_dict()
            payload.append([
                json.dumps(d[c]) if c in _JSON_COLS else d[c]
                for c in _COLS
            ])
        with self._write():
            self.conn.executemany(sql, payload)
            self.conn.commit()
        return len(payload)

    # --- RAW findings (nguồn recompute nhãn) ---
    def insert_raw(self, findings) -> int:
        """Ghi từng finding per-tool vào raw_findings (tier suy từ tên tool)."""
        from ..consensus.tiers import tier_of
        if not findings:
            return 0
        sql = ("INSERT INTO raw_findings (repo,commit_id,tool,tier,file_path,s_line,"
               "e_line,cwe,rule_id,severity,message,verified,created_at) "
               "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))")
        payload = [[f.repo, f.commit_id, f.tool, tier_of(f.tool), f.file_path, f.s_line,
                    f.e_line, json.dumps(f.cwe), f.rule_id, f.severity, f.message,
                    (1 if f.verified else 0) if f.verified is not None else None]
                   for f in findings]
        with self._write():
            self.conn.executemany(sql, payload)
            self.conn.commit()
        return len(payload)

    def insert_raw_output(self, commit_id: str, tool: str, fmt: str, content: str) -> None:
        """(B) Lưu output THÔ 1 tool/commit."""
        if content is None:
            return
        from ..consensus.tiers import tier_of
        with self._write():
            self.conn.execute(
                "INSERT INTO raw_output (commit_id,tool,tier,fmt,content,created_at) "
                "VALUES (?,?,?,?,?,datetime('now'))",
                [commit_id, tool, tier_of(tool), fmt, content])
            self.conn.commit()

    def raw_output_for_commit(self, commit_id: str) -> list[tuple]:
        """-> [(tool, fmt, content)] để export."""
        return self.conn.execute(
            "SELECT tool, fmt, content FROM raw_output WHERE commit_id=?",
            [commit_id]).fetchall()

    # --- 14 đặc trưng Kamei (cấp commit) ---
    def upsert_commit_features(self, repo: str, feats: dict[str, dict]) -> int:
        """feats: {commit_id: {author, author_date, ns..sexp}} (từ kamei.compute_features).
        INSERT OR REPLACE -> idempotent."""
        if not feats:
            return 0
        cols = ["commit_id", "repo", "author", "author_date", *_KAMEI_COLS]
        sql = (f"INSERT OR REPLACE INTO commit_features ({','.join(cols)},created_at) "
               f"VALUES ({','.join('?' * len(cols))},datetime('now'))")
        payload = [[cid, repo, f.get("author"), f.get("author_date"),
                    *[f.get(k) for k in _KAMEI_COLS]] for cid, f in feats.items()]
        with self._write():
            self.conn.executemany(sql, payload)
            self.conn.commit()
        return len(payload)

    def features_for_commit(self, commit_id: str) -> dict | None:
        """-> dict 14 đặc trưng Kamei (None nếu chưa tính)."""
        r = self.conn.execute(
            f"SELECT {','.join(_KAMEI_COLS)} FROM commit_features WHERE commit_id=?",
            [commit_id]).fetchone()
        return dict(zip(_KAMEI_COLS, r)) if r else None

    def commit_features_rows(self) -> list[dict]:
        """Mọi dòng commit_features (ORDER BY author_date, commit_id) dạng dict — cho export."""
        cur = self.conn.execute(
            "SELECT * FROM commit_features ORDER BY author_date, commit_id")
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def all_commit_ids(self) -> list[str]:
        """Mọi commit có dữ liệu (raw_findings ∪ findings ∪ raw_output)."""
        q = ("SELECT commit_id FROM raw_findings UNION SELECT commit_id FROM findings "
             "UNION SELECT commit_id FROM raw_output")
        return [r[0] for r in self.conn.execute(q) if r[0]]

    def findings_for_commit(self, commit_id: str) -> list[dict]:
        cur = self.conn.execute("SELECT * FROM findings WHERE commit_id=?", [commit_id])
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def raw_for_commit(self, commit_id: str):
        """Dựng lại list[RawFinding] từ raw_findings của 1 commit."""
        from ..schema import RawFinding
        rows = self.conn.execute(
            "SELECT repo,commit_id,file_path,s_line,cwe,e_line,tool,rule_id,severity,"
            "message,verified FROM raw_findings WHERE commit_id=?", [commit_id]).fetchall()
        out = []
        for r in rows:
            out.append(RawFinding(
                repo=r[0], commit_id=r[1], file_path=r[2], s_line=r[3],
                cwe=json.loads(r[4]) if r[4] else [], e_line=r[5], tool=r[6],
                rule_id=r[7] or "", severity=r[8], message=r[9],
                verified=(bool(r[10]) if r[10] is not None else None),
            ).validate())
        return out

    def replace_findings_for_commit(self, commit_id: str, rows: list[DatasetRow]) -> int:
        """Xoá findings cũ của commit rồi ghi nhãn mới (idempotent — recompute an toàn)."""
        with self._write():
            self.conn.execute("DELETE FROM findings WHERE commit_id=?", [commit_id])
            self.conn.commit()
        return self.insert_rows(rows)

    def insert_scanned_files(self, records: list[dict]) -> int:
        """records: {repo, commit_id, parent_commit, author_date, file_path,
        n_findings, n_tools_ran, tools(list)} -> ghi bảng mẫu số."""
        if not records:
            return 0
        cols = ["repo", "commit_id", "parent_commit", "author_date", "file_path",
                "n_findings", "n_tools_ran", "tools", "label"]
        sql = f"INSERT INTO scanned_files ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})"
        payload = []
        for r in records:
            payload.append([
                r["repo"], r["commit_id"], r.get("parent_commit"), r.get("author_date"),
                r["file_path"], r["n_findings"], r.get("n_tools_ran"),
                json.dumps(r.get("tools", [])),
                "clean" if r["n_findings"] == 0 else "has_finding",
            ])
        with self._write():
            self.conn.executemany(sql, payload)
            self.conn.commit()
        return len(payload)

    # ---------------- run_meta v2 / kappa ----------------
    def insert_run_meta(self, tier=None, **fields) -> int:
        """Ghi 1 hàng run_meta v2, trả id.

        Mới: insert_run_meta('analyze', repo=..., tools_json=[...], ...).
        Tương thích cũ (cli.cmd_scan): insert_run_meta({"started_at", "repo", "max_commits",
        "vote_threshold", "line_window", "tools"}) -> tier='scan'.
        Giá trị dict/list ở scope_json/config_snapshot_json/tools_json được json.dumps tự động.
        """
        if isinstance(tier, dict):
            meta = tier
            fields = {
                "started_at": meta.get("started_at"), "repo": meta.get("repo"),
                "scope_json": {"mode": "all" if not meta.get("max_commits") else "count",
                               "max": meta.get("max_commits")},
                "config_snapshot_json": {"max_commits": meta.get("max_commits"),
                                         "vote_threshold": meta.get("vote_threshold"),
                                         "line_window": meta.get("line_window")},
                "tools_json": meta.get("tools", []),
                **{k: v for k, v in meta.items()
                   if k in _RUN_META_V2_COLS and k not in ("tools_json",)},
            }
            tier = meta.get("tier", "scan")
        if tier not in ("scan", "analyze"):
            raise ValueError(f"tier phải là scan|analyze, nhận {tier!r}")
        row = {"run_id": progress.run_id(), "tier": tier,
               "started_at": _now(),
               "app_version": os.environ.get("SECJIT_APP_VERSION", "dev"),
               "experiment": 1 if os.environ.get("ORCH_EXPERIMENT") == "1" else 0,
               "reason": os.environ.get("ORCH_EXPERIMENT_REASON") or None}
        row.update({k: v for k, v in fields.items() if k in _RUN_META_V2_COLS})
        for k in ("scope_json", "config_snapshot_json", "tools_json"):
            if row.get(k) is not None and not isinstance(row[k], str):
                row[k] = json.dumps(row[k], ensure_ascii=False, default=str)
        cols = [c for c in _RUN_META_V2_COLS if c in row]
        with self._write():
            cur = self.conn.execute(
                f"INSERT INTO run_meta ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})",
                [row[c] for c in cols])
            self.conn.commit()
            return int(cur.lastrowid)

    def finish_run_meta(self, run_meta_id: int, **fields) -> None:
        """Đặt finished_at (+ cập nhật tools_json… nếu truyền)."""
        # local ISO có 'T' — cùng định dạng/múi giờ với started_at và progress.ts (không dùng datetime('now') = UTC)
        sets, vals = ["finished_at=?"], [_now()]
        for k, v in fields.items():
            if k in _RUN_META_V2_COLS:
                if k in ("scope_json", "config_snapshot_json", "tools_json") and not isinstance(v, str):
                    v = json.dumps(v, ensure_ascii=False, default=str)
                sets.append(f"{k}=?"); vals.append(v)
        vals.append(run_meta_id)
        with self._write():
            self.conn.execute(f"UPDATE run_meta SET {','.join(sets)} WHERE id=?", vals)
            self.conn.commit()

    def run_meta_rows(self, run_id: str | None = None) -> list[dict]:
        """Mọi hàng run_meta (JSON đã parse). run_id=None -> tất cả."""
        q, args = "SELECT * FROM run_meta", []
        if run_id:
            q += " WHERE run_id=?"; args = [run_id]
        cur = self.conn.execute(q + " ORDER BY id", args)
        cols = [c[0] for c in cur.description]
        out = []
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            for k in ("scope_json", "config_snapshot_json", "tools_json"):
                if isinstance(d.get(k), str):
                    try:
                        d[k] = json.loads(d[k])
                    except ValueError:
                        pass
            out.append(d)
        return out

    def save_kappa(self, run_id: str, scope: str, grp: str, value, n: int) -> None:
        """Lưu 1 giá trị Fleiss' kappa (scope: total|category|cwe_group|pair; grp '' cho total)."""
        with self._write():
            self.conn.execute(
                "DELETE FROM kappa WHERE run_id=? AND scope=? AND grp=?", [run_id, scope, grp or ""])
            self.conn.execute(
                "INSERT INTO kappa (run_id,scope,grp,value,n,computed_at) VALUES (?,?,?,?,?,?)",
                [run_id, scope, grp or "", value, n, _now()])
            self.conn.commit()

    def kappa_rows(self, run_id: str | None = None) -> list[dict]:
        q, args = "SELECT run_id,scope,grp,value,n,computed_at FROM kappa", []
        if run_id:
            q += " WHERE run_id=?"; args = [run_id]
        return [dict(zip(("run_id", "scope", "grp", "value", "n", "computed_at"), r))
                for r in self.conn.execute(q + " ORDER BY scope, grp", args)]

    # ---------------- gold_review / gold_sample (review.py; export đọc) ----------------
    def gold_review_verdicts(self) -> dict[str, list[tuple[str, str]]]:
        """{cluster_key: [(rater, verdict)…]} — export dùng để điền evidence.validation
        (ưu tiên rater 'adjudicated' > đa số > hoà = unclear)."""
        out: dict[str, list[tuple[str, str]]] = {}
        for ck, rater, v in self.conn.execute("SELECT cluster_key, rater, verdict FROM gold_review"):
            out.setdefault(ck, []).append((rater, v))
        return out

    def findings_rows(self, label: str | None = None) -> list[dict]:
        """Mọi dòng findings (tuỳ chọn lọc label) dạng dict (JSON còn là text)."""
        q, args = "SELECT * FROM findings", []
        if label:
            q += " WHERE label=?"; args = [label]
        cur = self.conn.execute(q + " ORDER BY commit_id, file_path, s_line, id", args)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def verified_clean_commits(self) -> list[str]:
        """Commit negative_level='verified-clean' (n_expensive_ok>=2, không finding in_diff)."""
        cands = [r[0] for r in self.conn.execute(
            "SELECT DISTINCT commit_id FROM expensive_runs WHERE phase='analyze' AND status='ok' "
            "ORDER BY commit_id")]
        return [c for c in cands if self.negative_level(c) == "verified-clean"]

    def scanned_files_for_commit(self, commit_id: str) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT file_path FROM scanned_files WHERE commit_id=? ORDER BY file_path",
            [commit_id])]

    def replace_gold_sample(self, sample_id: str, rows: list[dict]) -> int:
        """Ghi đè mẫu kiểm tay: rows = [{cluster_key, stratum, kind, seed}]."""
        with self._write():
            self.conn.execute("DELETE FROM gold_sample WHERE sample_id=?", [sample_id])
            self.conn.executemany(
                "INSERT INTO gold_sample (sample_id,cluster_key,stratum,kind,seed,created_at) "
                "VALUES (?,?,?,?,?,?)",
                [[sample_id, r["cluster_key"], r["stratum"], r["kind"], r.get("seed"), _now()] for r in rows])
            self.conn.commit()
        return len(rows)

    def gold_sample_rows(self, sample_id: str) -> list[dict]:
        cur = self.conn.execute(
            "SELECT sample_id, cluster_key, stratum, kind, seed, created_at FROM gold_sample "
            "WHERE sample_id=? ORDER BY CASE kind WHEN 'pos' THEN 0 ELSE 1 END, stratum, cluster_key",
            [sample_id])
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def gold_sample_ids(self) -> list[dict]:
        """[{sample_id, seed, n_pos, n_neg, created_at}] mọi mẫu đã tạo."""
        cur = self.conn.execute(
            "SELECT sample_id, MIN(seed), SUM(kind='pos'), SUM(kind='neg'), MIN(created_at) "
            "FROM gold_sample GROUP BY sample_id ORDER BY MIN(created_at), sample_id")
        return [dict(zip(("sample_id", "seed", "n_pos", "n_neg", "created_at"), r)) for r in cur.fetchall()]

    def gold_review_rows(self, sample_id: str) -> list[dict]:
        cur = self.conn.execute(
            "SELECT cluster_key, rater, verdict, note, at FROM gold_review WHERE sample_id=? "
            "ORDER BY cluster_key, rater", [sample_id])
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def upsert_gold_review(self, sample_id: str, rater: str, cluster_key: str,
                           verdict: str, note: str | None = None) -> None:
        if verdict not in ("TP", "FP", "unclear"):
            raise ValueError(f"verdict phải là TP|FP|unclear, nhận {verdict!r}")
        with self._write():
            self.conn.execute(
                "INSERT OR REPLACE INTO gold_review (cluster_key,sample_id,rater,verdict,note,at) "
                "VALUES (?,?,?,?,?,?)", [cluster_key, sample_id, rater, verdict, note, _now()])
            self.conn.commit()

    # --- chọn commit cho tầng đắt ---
    def scanned_commit_ids(self) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT commit_id FROM scanned_files")]

    def mark_scan_done(self, commit_id: str) -> None:
        """Đánh dấu commit đã quét TRỌN tầng rẻ (mốc resume)."""
        with self._write():
            self.conn.execute(
                "INSERT OR REPLACE INTO scan_done (commit_id, finished_at) "
                "VALUES (?, datetime('now'))", [commit_id])
            self.conn.commit()

    def scan_done_ids(self) -> set[str]:
        """Commit đã quét xong tầng rẻ. Union scanned_files để phủ DB tạo TRƯỚC khi có
        bảng scan_done (run cũ bị kill: commit có row file = chắc chắn đã xong —
        scanned_files là ghi CUỐI của _scan_one_commit thời đó)."""
        done = {r[0] for r in self.conn.execute("SELECT commit_id FROM scan_done")}
        done |= {r[0] for r in self.conn.execute(
            "SELECT DISTINCT commit_id FROM scanned_files")}
        return done

    def reset_cheap_scan(self, commit_id: str) -> None:
        """Xoá dấu vết tầng RẺ của 1 commit trước khi quét lại (row lửng do kill giữa
        chừng) -> re-scan idempotent, không nhân đôi. Không đụng raw tier=expensive;
        findings do relabel_commit ghi đè nên không cần xoá ở đây."""
        with self._write():
            self.conn.execute(
                "DELETE FROM raw_findings WHERE commit_id=? AND tier='cheap'", [commit_id])
            self.conn.execute(
                "DELETE FROM raw_output WHERE commit_id=? AND tier='cheap'", [commit_id])
            self.conn.execute(
                "DELETE FROM scanned_files WHERE commit_id=?", [commit_id])
            self.conn.commit()

    def reset_expensive_raw(self, commit_id: str) -> None:
        """Xoá raw ĐẮT bán phần của 1 commit (infra_error / dừng giữa chừng) để chạy lại sạch.
        Giữ expensive_runs (telemetry) — không xoá lịch sử lỗi."""
        with self._write():
            self.conn.execute(
                "DELETE FROM raw_findings WHERE commit_id=? AND tier='expensive'", [commit_id])
            self.conn.execute(
                "DELETE FROM raw_output WHERE commit_id=? AND tier='expensive'", [commit_id])
            self.conn.commit()

    def finding_class_rows(self) -> list[tuple]:
        """(commit_id, cwe, cve, finding_in_diff) mọi finding — để phân loại buggy/clean.
        buggy = có mã CWE/CVE (cwe là JSON list, cve là text/NULL)."""
        return self.conn.execute(
            "SELECT commit_id, cwe, cve, finding_in_diff FROM findings").fetchall()

    def replace_selected(self, rows: list[dict]) -> int:
        """Ghi ĐÈ bảng selected_commits (idempotent: chạy lại = chọn lại)."""
        cols = ["commit_id", "role", "selection_reason",
                "suspect_categories", "n_suspect_findings", "created_at"]
        with self._write():
            self.conn.execute("DELETE FROM selected_commits")
            if rows:
                sql = (f"INSERT INTO selected_commits ({','.join(cols)}) "
                       f"VALUES ({','.join('?'*len(cols))})")
                self.conn.executemany(sql, [
                    [r["commit_id"], r["role"], r["selection_reason"],
                     json.dumps(r["suspect_categories"]), r["n_suspect_findings"],
                     r["created_at"]] for r in rows])
            self.conn.commit()
        return len(rows)

    # --- hàng đợi tầng đắt (pull + claim nguyên tử) ---
    def reset_stale_claims(self, older_than_sec: int) -> int:
        """Đưa hàng 'building'/'analyzing' bị treo (claim quá hạn) về 'pending' để resume."""
        with self._write():
            cur = self.conn.execute(
                "UPDATE selected_commits SET status='pending', claimed_by=NULL "
                "WHERE status IN ('building','analyzing') "
                "AND (claimed_at IS NULL OR (julianday('now')-julianday(claimed_at))*86400 > ?)",
                [older_than_sec])
            self.conn.commit()
            return cur.rowcount

    def reset_claims(self, run_id: str | None = None) -> int:
        """Reset MỌI claim 'building'/'analyzing' về 'pending' bất kể tuổi (TC-08: ngay sau Dừng
        an toàn). run_id -> chỉ claim của run đó (claimed_by = '<run_id>:wN'); None -> tất cả.
        Xoá raw đắt bán phần của các commit đó."""
        with self._write():
            q = "SELECT commit_id FROM selected_commits WHERE status IN ('building','analyzing')"
            args: list = []
            if run_id:
                q += " AND claimed_by LIKE ?"; args = [f"{run_id}:%"]
            ids = [r[0] for r in self.conn.execute(q, args)]
            for cid in ids:
                self.conn.execute(
                    "DELETE FROM raw_findings WHERE commit_id=? AND tier='expensive'", [cid])
                self.conn.execute(
                    "DELETE FROM raw_output WHERE commit_id=? AND tier='expensive'", [cid])
                self.conn.execute(
                    "UPDATE selected_commits SET status='pending', claimed_by=NULL WHERE commit_id=?", [cid])
            self.conn.commit()
            return len(ids)

    def count_pending(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM selected_commits WHERE status='pending'").fetchone()[0]

    def claim_next_commit(self, worker: str) -> str | None:
        """Chiếm 1 commit pending (buggy trước clean) NGUYÊN TỬ. None nếu hết."""
        with self._write():
            self.conn.execute("BEGIN IMMEDIATE")
            row = self.conn.execute(
                "SELECT commit_id FROM selected_commits WHERE status='pending' "
                "ORDER BY CASE role WHEN 'buggy' THEN 0 ELSE 1 END, commit_id LIMIT 1"
            ).fetchone()
            if not row:
                self.conn.commit()
                return None
            cid = row[0]
            self.conn.execute(
                "UPDATE selected_commits SET status='building', claimed_by=?, "
                "claimed_at=datetime('now'), attempts=attempts+1 WHERE commit_id=?",
                [worker, cid])
            self.conn.commit()
            return cid

    def set_commit_status(self, commit_id: str, status: str,
                          build_status: str | None = None, finished: bool = False) -> None:
        with self._write():
            sets = ["status=?"]
            vals: list = [status]
            if build_status is not None:
                sets.append("build_status=?"); vals.append(build_status)
            if finished:
                sets.append("finished_at=datetime('now')")
            if status == "pending":            # trả về hàng đợi (infra_error) -> bỏ claim
                sets.append("claimed_by=NULL")
            vals.append(commit_id)
            self.conn.execute(
                f"UPDATE selected_commits SET {','.join(sets)} WHERE commit_id=?", vals)
            self.conn.commit()

    def insert_expensive_run(self, rec: dict) -> None:
        with self._write():
            self.conn.execute(
                "INSERT INTO expensive_runs (commit_id,tool,phase,status,n_findings,"
                "duration_sec,error,created_at,run_id) VALUES (?,?,?,?,?,?,?,datetime('now'),?)",
                [rec.get("commit_id"), rec.get("tool"), rec.get("phase"), rec.get("status"),
                 rec.get("n_findings"), rec.get("duration_sec"), rec.get("error"),
                 rec.get("run_id") or progress.run_id()])
            self.conn.commit()

    def expensive_runs_for_commit(self, commit_id: str) -> list[dict]:
        cur = self.conn.execute(
            "SELECT tool,phase,status,n_findings,duration_sec,error,created_at,run_id "
            "FROM expensive_runs WHERE commit_id=? ORDER BY id", [commit_id])
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def commits_by_expensive_status(self) -> dict[str, list[str]]:
        """{status: [commit_id…]} cho các status KHÔNG-ok (build_failed, infra_error, tool_timeout,
        tool_error, skipped) — manifest §6."""
        out: dict[str, list[str]] = {}
        for st, cid in self.conn.execute(
                "SELECT DISTINCT status, commit_id FROM expensive_runs "
                "WHERE status IS NOT NULL AND status NOT IN ('ok') ORDER BY commit_id"):
            out.setdefault(st, []).append(cid)
        return out

    def n_expensive_ok(self, commit_id: str) -> int:
        """Số tool đắt phase=analyze status=ok trên commit (DISTINCT tool, loại skipped/maven)."""
        return self.conn.execute(
            "SELECT COUNT(DISTINCT tool) FROM expensive_runs WHERE commit_id=? "
            "AND phase='analyze' AND status='ok' AND tool NOT IN ('-','maven')",
            [commit_id]).fetchone()[0]

    def update_n_expensive_ok(self, commit_id: str) -> int:
        """Tính lại và ghi selected_commits.n_expensive_ok sau mỗi commit (D1)."""
        n = self.n_expensive_ok(commit_id)
        with self._write():
            self.conn.execute(
                "UPDATE selected_commits SET n_expensive_ok=? WHERE commit_id=?", [n, commit_id])
            self.conn.commit()
        return n

    def selected_status_counts(self) -> dict:
        return dict(self.conn.execute(
            "SELECT status, COUNT(*) FROM selected_commits GROUP BY status").fetchall())

    def selected_role(self, commit_id: str) -> str | None:
        r = self.conn.execute(
            "SELECT role FROM selected_commits WHERE commit_id=?", [commit_id]).fetchone()
        return r[0] if r else None

    def selected_rows(self) -> dict[str, dict]:
        """{commit_id: {role, status, build_status, n_expensive_ok, attempts, claimed_by}}."""
        cur = self.conn.execute(
            "SELECT commit_id, role, status, build_status, n_expensive_ok, attempts, claimed_by "
            "FROM selected_commits")
        cols = [c[0] for c in cur.description]
        return {r[0]: dict(zip(cols, r)) for r in cur.fetchall()}

    def add_selected(self, rows: list[dict]) -> int:
        """Thêm commit vào hàng đợi KHÔNG đụng row đã có (INSERT OR IGNORE) — enqueue tăng dần
        (vd thêm clean commit để verify mà không reset trạng thái buggy đã done)."""
        if not rows:
            return 0
        cols = ["commit_id", "role", "selection_reason",
                "suspect_categories", "n_suspect_findings", "created_at"]
        with self._write():
            self.conn.executemany(
                f"INSERT OR IGNORE INTO selected_commits ({','.join(cols)}) "
                f"VALUES ({','.join('?'*len(cols))})",
                [[r["commit_id"], r["role"], r["selection_reason"],
                  json.dumps(r["suspect_categories"]), r["n_suspect_findings"],
                  r["created_at"]] for r in rows])
            self.conn.commit()
        return len(rows)

    def negative_level(self, commit_id: str) -> str | None:
        """Mức nhãn ÂM của commit: verified-clean | cheap-clean | None.

        None nếu commit TẠO lỗi (finding_in_diff=1) -> POSITIVE. Nợ cũ (in_diff=0) KHÔNG tính
        (tool đắt quét cả file nên phơi lỗi có sẵn — không phải commit này gây ra).
        verified-clean CHỈ KHI n_expensive_ok >= 2 (CONTRACTS §1; REVIEW D1/TC-16/TC-17):
        commit 0-module-Java (status=skipped) hay chỉ 1 tool ok -> cheap-clean."""
        if self.conn.execute(
                "SELECT 1 FROM findings WHERE commit_id=? AND finding_in_diff=1 LIMIT 1",
                [commit_id]).fetchone():
            return None
        return "verified-clean" if self.n_expensive_ok(commit_id) >= 2 else "cheap-clean"

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0]

    def count_clean(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM scanned_files WHERE label='clean'").fetchone()[0]

    def close(self):
        try:
            self.conn.close()
        finally:
            self._release_lock()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
