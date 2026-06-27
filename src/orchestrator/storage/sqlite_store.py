"""
Lưu DatasetRow vào SQLite (stdlib). list[str]/cwe -> JSON text.
"""
from __future__ import annotations

import json
import sqlite3
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
    tool TEXT, rule_id TEXT, severity TEXT,
    cwe TEXT NOT NULL,                -- JSON list, BẮT BUỘC
    owasp TEXT, cve TEXT,
    lines_added INTEGER, lines_deleted INTEGER,
    code_snippet TEXT,
    diff_parsed TEXT,                 -- JSON {added:[[ln,txt]],deleted:[[ln,txt]]}
    code_before_url TEXT, code_after_url TEXT,
    code_before TEXT, code_after TEXT,
    n_tools_ran INTEGER, n_tools_agree INTEGER,
    agreeing_tools TEXT, agreement_ratio REAL,
    confidence REAL, silver_label TEXT
);
CREATE INDEX IF NOT EXISTS idx_commit ON findings(commit_id);
CREATE INDEX IF NOT EXISTS idx_cwe ON findings(cwe);
"""

_COLS = [
    "repo", "commit_id", "parent_commit", "commit_message", "author_date",
    "file_path", "s_line", "e_line", "function", "s_detail_line",
    "tool", "rule_id", "severity", "cwe", "owasp", "cve",
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
        self.conn = sqlite3.connect(self.path)
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
        self.conn.executemany(sql, payload)
        self.conn.commit()
        return len(payload)

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0]

    def close(self):
        self.conn.close()
