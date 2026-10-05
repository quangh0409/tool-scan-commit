"""Lưu dataset (SQLite) — thẳng trên Persistent Disk VM, KHÔNG GCS."""
from __future__ import annotations


class InfraError(RuntimeError):
    """Lỗi HẠ TẦNG khi ghi DB (đĩa đầy / disk I/O) — runner phải dừng, KHÔNG coi là dữ liệu.

    CONTRACTS §1 (`infra_error`) + REVIEW D6. Raise từ SQLiteStore khi sqlite3.OperationalError
    chứa "disk" hoặc OSError ENOSPC.
    """
