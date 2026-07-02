"""
Lưu DatasetRow vào SQLite (stdlib). list[str]/cwe -> JSON text.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from .. import config
from ..schema import DatasetRow

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

-- TÁI LẬP: ghi 1 lần/run — version + digest tool, config, ngưỡng, thời điểm.
CREATE TABLE IF NOT EXISTS run_meta (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT, repo TEXT, max_commits INTEGER,
    vote_threshold INTEGER, line_window INTEGER,
    tools TEXT      -- JSON [{name,version,digest}]
);

-- HÀNG ĐỢI TẦNG ĐẮT (hợp đồng rẻ->đắt): commit được chọn để tool đắt quét.
--   role=buggy  : tầng rẻ đánh dấu đáng nghi (có mã CWE/CVE) -> bắt buộc quét.
--   role=clean  : commit 0-finding, lấy MẪU theo tỉ lệ 1 buggy : N clean (negative cân bằng).
-- Vòng đời status: pending -> building -> built -> analyzing -> done
--                                    \-> build_failed (terminal) ; analyzing -> error (retry)
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
    attempts INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sel_role ON selected_commits(role);
-- idx_sel_status tạo SAU migration (DB cũ chưa có cột status khi chạy _SCHEMA).

-- TELEMETRY tầng đắt: 1 dòng / (commit, tool, phase) — đo chi phí + chẩn lỗi build.
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

CREATE TABLE IF NOT EXISTS expensive_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    commit_id TEXT, tool TEXT, phase TEXT,    -- build | analyze
    status TEXT,                              -- ok | failed | skipped
    n_findings INTEGER, duration_sec REAL,
    error TEXT, created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_exp_commit ON expensive_runs(commit_id);
"""

# Cột mới của selected_commits cần ALTER khi DB cũ đã tạo bảng (CREATE IF NOT EXISTS không thêm cột).
_SELECTED_NEW_COLS = {
    "status": "TEXT NOT NULL DEFAULT 'pending'",
    "claimed_by": "TEXT", "claimed_at": "TEXT", "finished_at": "TEXT",
    "build_status": "TEXT", "attempts": "INTEGER NOT NULL DEFAULT 0",
}

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


class SQLiteStore:
    def __init__(self, path: Path | None = None):
        config.ensure_dirs()
        self.path = path or config.SQLITE_PATH
        # check_same_thread=False: worker song song (cấp commit) cùng ghi 1 connection;
        # mọi ghi được bọc trong self._lock -> SQLite tự serialize, an toàn.
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = threading.Lock()
        self.conn.executescript(_SCHEMA)
        self._migrate_selected()
        self._migrate_findings()
        # index trên cột status: tạo SAU migration (đảm bảo cột tồn tại)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sel_status ON selected_commits(status)")
        self.conn.commit()

    def _migrate_selected(self) -> None:
        """Thêm cột lifecycle nếu DB cũ đã có selected_commits dạng thiếu cột."""
        have = {r[1] for r in self.conn.execute("PRAGMA table_info(selected_commits)")}
        for col, decl in _SELECTED_NEW_COLS.items():
            if col not in have:
                self.conn.execute(f"ALTER TABLE selected_commits ADD COLUMN {col} {decl}")

    def _migrate_findings(self) -> None:
        """Thêm cột mới nếu DB cũ đã có findings thiếu cột."""
        have = {r[1] for r in self.conn.execute("PRAGMA table_info(findings)")}
        for col, decl in {"tier": "TEXT DEFAULT 'cheap'", "label": "TEXT",
                          "n_cheap": "INTEGER", "n_expensive": "INTEGER",
                          "eligible": "INTEGER", "kamei": "TEXT"}.items():
            if col not in have:
                self.conn.execute(f"ALTER TABLE findings ADD COLUMN {col} {decl}")

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
        with self._lock:
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
        with self._lock:
            self.conn.executemany(sql, payload)
            self.conn.commit()
        return len(payload)

    def insert_raw_output(self, commit_id: str, tool: str, fmt: str, content: str) -> None:
        """(B) Lưu output THÔ 1 tool/commit."""
        if content is None:
            return
        from ..consensus.tiers import tier_of
        with self._lock:
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
        with self._lock:
            self.conn.executemany(sql, payload)
            self.conn.commit()
        return len(payload)

    def features_for_commit(self, commit_id: str) -> dict | None:
        """-> dict 14 đặc trưng Kamei (None nếu chưa tính)."""
        r = self.conn.execute(
            f"SELECT {','.join(_KAMEI_COLS)} FROM commit_features WHERE commit_id=?",
            [commit_id]).fetchone()
        return dict(zip(_KAMEI_COLS, r)) if r else None

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
        with self._lock:
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
        with self._lock:
            self.conn.executemany(sql, payload)
            self.conn.commit()
        return len(payload)

    def insert_run_meta(self, meta: dict) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO run_meta (started_at,repo,max_commits,vote_threshold,"
                "line_window,tools) VALUES (?,?,?,?,?,?)",
                [meta.get("started_at"), meta.get("repo"), meta.get("max_commits"),
                 meta.get("vote_threshold"), meta.get("line_window"),
                 json.dumps(meta.get("tools", []))],
            )
            self.conn.commit()

    # --- chọn commit cho tầng đắt ---
    def scanned_commit_ids(self) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT commit_id FROM scanned_files")]

    def finding_class_rows(self) -> list[tuple]:
        """(commit_id, cwe, cve, finding_in_diff) mọi finding — để phân loại buggy/clean.
        buggy = có mã CWE/CVE (cwe là JSON list, cve là text/NULL)."""
        return self.conn.execute(
            "SELECT commit_id, cwe, cve, finding_in_diff FROM findings").fetchall()

    def replace_selected(self, rows: list[dict]) -> int:
        """Ghi ĐÈ bảng selected_commits (idempotent: chạy lại = chọn lại)."""
        cols = ["commit_id", "role", "selection_reason",
                "suspect_categories", "n_suspect_findings", "created_at"]
        with self._lock:
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
        with self._lock:
            cur = self.conn.execute(
                "UPDATE selected_commits SET status='pending', claimed_by=NULL "
                "WHERE status IN ('building','analyzing') "
                "AND (claimed_at IS NULL OR (julianday('now')-julianday(claimed_at))*86400 > ?)",
                [older_than_sec])
            self.conn.commit()
            return cur.rowcount

    def claim_next_commit(self, worker: str) -> str | None:
        """Chiếm 1 commit pending (buggy trước clean) NGUYÊN TỬ. None nếu hết."""
        with self._lock:
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
        with self._lock:
            sets = ["status=?"]
            vals: list = [status]
            if build_status is not None:
                sets.append("build_status=?"); vals.append(build_status)
            if finished:
                sets.append("finished_at=datetime('now')")
            vals.append(commit_id)
            self.conn.execute(
                f"UPDATE selected_commits SET {','.join(sets)} WHERE commit_id=?", vals)
            self.conn.commit()

    def insert_expensive_run(self, rec: dict) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO expensive_runs (commit_id,tool,phase,status,n_findings,"
                "duration_sec,error,created_at) VALUES (?,?,?,?,?,?,?,datetime('now'))",
                [rec.get("commit_id"), rec.get("tool"), rec.get("phase"), rec.get("status"),
                 rec.get("n_findings"), rec.get("duration_sec"), rec.get("error")])
            self.conn.commit()

    def selected_status_counts(self) -> dict:
        return dict(self.conn.execute(
            "SELECT status, COUNT(*) FROM selected_commits GROUP BY status").fetchall())

    def selected_role(self, commit_id: str) -> str | None:
        r = self.conn.execute(
            "SELECT role FROM selected_commits WHERE commit_id=?", [commit_id]).fetchone()
        return r[0] if r else None

    def add_selected(self, rows: list[dict]) -> int:
        """Thêm commit vào hàng đợi KHÔNG đụng row đã có (INSERT OR IGNORE) — enqueue tăng dần
        (vd thêm clean commit để verify mà không reset trạng thái buggy đã done)."""
        if not rows:
            return 0
        cols = ["commit_id", "role", "selection_reason",
                "suspect_categories", "n_suspect_findings", "created_at"]
        with self._lock:
            self.conn.executemany(
                f"INSERT OR IGNORE INTO selected_commits ({','.join(cols)}) "
                f"VALUES ({','.join('?'*len(cols))})",
                [[r["commit_id"], r["role"], r["selection_reason"],
                  json.dumps(r["suspect_categories"]), r["n_suspect_findings"],
                  r["created_at"]] for r in rows])
            self.conn.commit()
        return len(rows)

    def negative_level(self, commit_id: str) -> str | None:
        """Mức nhãn ÂM của commit: verified-clean (qua tầng đắt, 0 lỗi TẠO) | cheap-clean.
        None nếu commit TẠO lỗi (finding_in_diff=1) -> POSITIVE. Nợ cũ (in_diff=0) KHÔNG tính
        (tool đắt quét cả file nên phơi lỗi có sẵn — không phải commit này gây ra)."""
        if self.conn.execute(
                "SELECT 1 FROM findings WHERE commit_id=? AND finding_in_diff=1 LIMIT 1",
                [commit_id]).fetchone():
            return None
        exp = self.conn.execute(
            "SELECT 1 FROM expensive_runs WHERE commit_id=? AND phase='analyze' "
            "AND status='ok' LIMIT 1", [commit_id]).fetchone()
        return "verified-clean" if exp else "cheap-clean"

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0]

    def count_clean(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM scanned_files WHERE label='clean'").fetchone()[0]

    def close(self):
        self.conn.close()
