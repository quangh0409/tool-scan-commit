"""keys.canon_repo (12 dạng URL), repo_slug, cluster_key ổn định theo bucket LINE_WINDOW."""
from __future__ import annotations

import re

import pytest

from orchestrator import keys

CANON = "https://github.com/FudanSELab/train-ticket"
URL_FORMS = [
    "https://github.com/FudanSELab/train-ticket",
    "https://github.com/FudanSELab/train-ticket.git",
    "https://github.com/FudanSELab/train-ticket/",
    "http://github.com/FudanSELab/train-ticket",
    "git@github.com:FudanSELab/train-ticket.git",
    "https://GitHub.COM/FudanSELab/train-ticket",
    "https://github.com/FudanSELab/train-ticket/tree/master",
    "https://github.com/FudanSELab/train-ticket/commit/0123abcd",
    "https://github.com/FudanSELab/train-ticket/pull/42",
    "https://github.com/FudanSELab/train-ticket/blob/master/pom.xml",
    "  https://github.com/FudanSELab/train-ticket  ",
    "https://github.com/FudanSELab/train-ticket/commits/master",
]


@pytest.mark.parametrize("url", URL_FORMS)
def test_canon_repo_12_forms(url):
    assert keys.canon_repo(url) == CANON


def test_canon_repo_keeps_owner_case_lowers_host():
    assert keys.canon_repo("https://GITHUB.com/Owner/Repo") == "https://github.com/Owner/Repo"
    assert keys.canon_repo("") == "" and keys.canon_repo(None) == ""


def test_repo_slug():
    for url in URL_FORMS:
        assert keys.repo_slug(url) == "FudanSELab__train-ticket"
    assert keys.repo_slug("https://github.com/Other/train-ticket") == "Other__train-ticket"   # khác org, khác slug
    assert keys.repo_slug("repo") == "repo"


def test_cluster_key_same_bucket_stable_and_differs_across_bucket():
    from orchestrator import config
    w = config.LINE_WINDOW or 3
    base = keys.cluster_key(CANON, "abc", "svc/A.java", "injection", 1 * w)
    assert re.fullmatch(r"[0-9a-f]{32}", base)
    for s in range(1 * w, 2 * w):                       # cùng bucket
        assert keys.cluster_key(CANON, "abc", "svc/A.java", "injection", s) == base
    assert keys.cluster_key(CANON, "abc", "svc/A.java", "injection", 2 * w) != base
    assert keys.cluster_key(CANON, "abc", "svc/A.java", "injection", 1 * w - 1) != base
    # mọi dạng URL -> cùng khoá
    assert {keys.cluster_key(u, "abc", "svc/A.java", "injection", w) for u in URL_FORMS} == {base}
    # đổi file / nhóm CWE / commit -> khác
    assert keys.cluster_key(CANON, "abc", "svc/B.java", "injection", w) != base
    assert keys.cluster_key(CANON, "abc", "svc/A.java", "xss", w) != base
    assert keys.cluster_key(CANON, "abd", "svc/A.java", "injection", w) != base
    # line_window tường minh
    assert keys.cluster_key(CANON, "abc", "svc/A.java", "injection", 10, line_window=5) == \
        keys.cluster_key(CANON, "abc", "svc/A.java", "injection", 14, line_window=5)
    assert keys.cluster_key(CANON, "abc", "svc/A.java", None, 0) == keys.cluster_key(CANON, "abc", "svc/A.java", "", None)
