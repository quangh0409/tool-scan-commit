"""Lỗi API dùng chung cho mọi module backend GUI (A4 server, A5 api_results/api_review/api_settings/api_runs).

Raise ``ApiError(status, code, message, hint)`` ở bất kỳ handler nào → server trả
``{"error": {"code", "message", "hint"}}`` với mã HTTP ``status``.
"""
from __future__ import annotations


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, hint: str = ""):
        super().__init__(message)
        self.status = int(status)
        self.code = code
        self.message = message
        self.hint = hint or ""

    def to_json(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "hint": self.hint}}


def not_implemented(what: str, owner: str, sig: str) -> ApiError:
    return ApiError(501, "not_implemented", f"Chưa nối backend thật cho {what}", f"{owner} cung cấp {sig}")


__all__ = ["ApiError", "not_implemented"]
