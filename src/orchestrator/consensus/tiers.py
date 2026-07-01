"""
Registry TẦNG + NĂNG LỰC tool — dùng cho cross-tier consensus (RULE_GAN_NHAN.md §3,§4).

- tier_of(tool): "cheap" | "expensive".
- eligible_tools(category): tập tool ĐỦ NĂNG LỰC báo miền đó (để tính mẫu số, KHÔNG chia /8).
"""
from __future__ import annotations

CHEAP = {"gitleaks", "trufflehog", "semgrep", "bearer", "horusec"}
EXPENSIVE = {"codeql", "findsecbugs", "sonar"}

# Miền năng lực: secret vs code. (category từ cwe_groups: secret/code/crypto/info/infra/other)
SECRET_TOOLS = {"gitleaks", "trufflehog", "horusec"}
CODE_TOOLS = {"semgrep", "bearer", "horusec", "codeql", "findsecbugs", "sonar"}


def tier_of(tool: str) -> str:
    return "expensive" if tool in EXPENSIVE else "cheap"


def eligible_tools(category: str | None) -> set[str]:
    """Tool đủ năng lực báo miền của cụm. secret -> tool secret; còn lại -> tool code."""
    return set(SECRET_TOOLS) if category == "secret" else set(CODE_TOOLS)
