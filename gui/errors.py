"""Lỗi API GUI (CONTRACTS §9): server trả HTTP `status` + body `{"error": {code, message, hint}}`.

Mọi hàm `gui/api_*.py` (A5) và `gui/api_real.py` (A4) raise ApiError; `gui/server.py` bắt và serialize
bằng `to_dict()` (alias `to_json()`).
"""
from __future__ import annotations


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, hint: str | None = None):
        super().__init__(message)
        self.status = int(status)
        self.code = code
        self.message = message
        self.hint = hint or ""

    def to_dict(self) -> dict:
        err = {"code": self.code, "message": self.message, "status": self.status, "hint": self.hint}
        return {"error": err}

    to_json = to_dict

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


def not_implemented(what: str, owner: str, sig: str) -> ApiError:
    return ApiError(501, "not_implemented", f"Chưa nối backend thật cho {what}", f"{owner} cung cấp {sig}")


__all__ = ["ApiError", "not_found", "bad_request", "not_supported", "conflict", "not_implemented"]
