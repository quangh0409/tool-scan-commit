"""
Chuẩn hoá CWE -> NHÓM ĐỒNG THUẬN (coarse) + CATEGORY.

Lý do: các tool gắn CWE anh-em cho cùng 1 lỗi (vd SQLi: CWE-89 vs CWE-943 vs CWE-564)
-> set-intersection CWE thô làm VỠ đồng thuận. Cluster theo NHÓM thay vì CWE chính xác.

CATEGORY để tách "rừng" CWE hạ-tầng (perm/privilege) khỏi code-vuln (SQLi/XSS) khi
phân tích/lọc dataset.
"""
from __future__ import annotations

from .. import schema

# nhóm -> (danh sách CWE thành viên, category)
_GROUPS: dict[str, tuple[list[str], str]] = {
    # --- injection / code-vuln ---
    "sql_injection":      (["CWE-89", "CWE-564", "CWE-943"], "code"),
    "xss":                (["CWE-79", "CWE-80", "CWE-83", "CWE-87"], "code"),
    "command_injection":  (["CWE-77", "CWE-78"], "code"),
    "code_injection":     (["CWE-94", "CWE-95", "CWE-96"], "code"),
    "path_traversal":     (["CWE-22", "CWE-23", "CWE-36", "CWE-73"], "code"),
    "ssrf":               (["CWE-918"], "code"),
    "xxe":                (["CWE-611", "CWE-776", "CWE-827"], "code"),
    "ldap_injection":     (["CWE-90"], "code"),
    "deserialization":    (["CWE-502"], "code"),
    "csrf":               (["CWE-352"], "code"),
    "open_redirect":      (["CWE-601"], "code"),
    "improper_validation": (["CWE-20", "CWE-1284", "CWE-129"], "code"),
    # --- secret ---
    "hardcoded_secret":   (["CWE-798", "CWE-259", "CWE-321", "CWE-322", "CWE-256",
                            "CWE-257", "CWE-260", "CWE-312", "CWE-522", "CWE-540"], "secret"),
    # --- crypto / random ---
    "weak_crypto":        (["CWE-327", "CWE-328", "CWE-326", "CWE-916", "CWE-780"], "crypto"),
    "weak_random":        (["CWE-330", "CWE-338", "CWE-335", "CWE-336", "CWE-337"], "crypto"),
    # --- hạ tầng / quyền ---
    "permissions":        (["CWE-732", "CWE-276", "CWE-277", "CWE-279", "CWE-281"], "infra"),
    "privilege":          (["CWE-250", "CWE-266", "CWE-269", "CWE-271", "CWE-272"], "infra"),
    # --- lộ thông tin / log ---
    "sensitive_exposure": (["CWE-532", "CWE-209", "CWE-200", "CWE-215", "CWE-208",
                            "CWE-359", "CWE-497"], "info"),
    # --- misconfig khác ---
    "improper_cert":      (["CWE-295", "CWE-297"], "code"),
}

# bảng tra ngược: CWE -> (group, category)
_LOOKUP: dict[str, tuple[str, str]] = {}
for _g, (_cwes, _cat) in _GROUPS.items():
    for _c in _cwes:
        _LOOKUP[_c] = (_g, _cat)


def cwe_group(cwe: str) -> tuple[str, str]:
    """CWE -> (group, category). CWE lạ -> (chính nó, 'other')."""
    c = schema.normalize_cwe(cwe)
    return _LOOKUP.get(c, (c, "other"))


def primary_group(cwes: list[str]) -> tuple[str, str]:
    """Chọn nhóm đại diện cho 1 finding (nhiều CWE): ưu tiên CWE đầu có nhóm biết."""
    for c in cwes:
        g, cat = cwe_group(c)
        if cat != "other":
            return g, cat
    # không CWE nào biết nhóm -> dùng CWE đầu
    return cwe_group(cwes[0]) if cwes else ("CWE-UNKNOWN", "other")
