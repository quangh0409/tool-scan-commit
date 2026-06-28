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
    confidence REAL, silver_label TEXT  -- vuln | candidate | clean
);
CREATE INDEX IF NOT EXISTS idx_commit ON findings(commit_id);
CREATE INDEX IF NOT EXISTS idx_cwe ON findings(cwe);
CREATE INDEX IF NOT EXISTS idx_cat ON findings(category);
CREATE INDEX IF NOT EXISTS idx_label ON findings(silver_label);

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
"""

_COLS = [
    "repo", "commit_id", "parent_commit", "commit_message", "author_date",
    "file_path", "s_line", "e_line", "function", "s_detail_line", "finding_in_diff",
    "tool", "rule_id", "severity", "cwe", "cwe_group", "category", "verified",
    "owasp", "cve",
    "lines_added", "lines_deleted", "code_snippet",
    "diff_parsed", "code_before_url", "code_after_url", "code_before", "code_after",
    "n_tools_ran", "n_tools_agree", "agreeing_tools", "agreement_ratio",
    "confidence", "silver_label",
]
_JSON_COLS = {"cwe", "agreeing_tools", "s_detail_line", "diff_parsed"}


class SQLiteStore:
    def __init__(self, path: Path | None = None):
        config.ensure_dirs()
        self.path = path or config.SQLITE_PATH
        # check_same_thread=False: worker song song (cấp commit) cùng ghi 1 connection;
        # mọi ghi được bọc trong self._lock -> SQLite tự serialize, an toàn.
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = threading.Lock()
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

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

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0]

    def count_clean(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM scanned_files WHERE label='clean'").fetchone()[0]

    def close(self):
        self.conn.close()
