"""Lỗi API GUI (CONTRACTS §9): server trả HTTP `status` + body `{"error": {code, message, hint}}`.

Mọi hàm `gui/api_*.py` raise ApiError; A4 (`gui/server.py`) bắt và serialize bằng `to_dict()`.
"""
from __future__ import annotations


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, hint: str | None = None):
        super().__init__(message)
        self.status = int(status)
        self.code = code
        self.message = message
        self.hint = hint

    def to_dict(self) -> dict:
        err = {"code": self.code, "message": self.message, "status": self.status}
        if self.hint:
            err["hint"] = self.hint
        return {"error": err}

    def __repr__(self) -> str:  # pragma: no cover - tiện debug
        return f"ApiError({self.status}, {self.code!r}, {self.message!r})"


def not_found(what: str, hint: str | None = None) -> ApiError:
    return ApiError(404, "ENOTFOUND", f"Không tìm thấy {what}", hint)


def bad_request(message: str, hint: str | None = None) -> ApiError:
    return ApiError(400, "EBADREQ", message, hint)


def not_supported(message: str, hint: str | None = None) -> ApiError:
    return ApiError(501, "ENOTSUP", message, hint)


def conflict(message: str, hint: str | None = None) -> ApiError:
    return ApiError(409, "ECONFLICT", message, hint)
