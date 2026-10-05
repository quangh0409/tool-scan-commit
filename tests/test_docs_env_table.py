"""Docs khớp code: GUIDE.md §3 phải liệt kê MỌI khoá trong config.ENV_KEYS (parse bảng markdown, so tập hợp);
README/HUONG_DAN_GUI/RELEASE_NOTES không còn 'TODO'/'placeholder'; RELEASE_NOTES.md có đủ mục và được release.ps1 gom."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

ENV_RE = re.compile(r"`((?:ORCH_|SECJIT_)[A-Z0-9_]+)`")


def _section3(text: str) -> str:
    i = text.index("\n## 3.")
    j = text.index("\n## 4.", i)
    return text[i:j]


def _table_env_keys(md: str) -> set[str]:
    """Khoá env xuất hiện trong Ô ĐẦU của các dòng bảng markdown (| `ORCH_X` | ... |), kể cả ô gộp nhiều khoá."""
    keys: set[str] = set()
    for line in md.splitlines():
        if not line.startswith("|") or line.startswith("|---") or line.startswith("| Biến"):
            continue
        first = line.split("|")[1]
        keys |= set(ENV_RE.findall(first))
    return keys


def test_guide_section3_lists_every_env_key():
    from orchestrator import config
    guide = (ROOT / "GUIDE.md").read_text(encoding="utf-8")
    sec = _section3(guide)
    in_table = _table_env_keys(sec)
    expected = set(config.ENV_KEYS)
    missing = sorted(expected - in_table)
    assert not missing, f"GUIDE.md §3 thiếu env (có trong config.ENV_KEYS): {missing}"
    extra = sorted(in_table - expected - set(config.SECRET_ENV_KEYS))
    assert not extra, f"GUIDE.md §3 có env không tồn tại trong config.ENV_KEYS (gõ sai/đã bỏ?): {extra}"


def test_env_keys_are_all_read_by_config():
    """Mỗi khoá trong ENV_KEYS phải được đọc ở đâu đó trong src/ (tránh bảng docs 'treo')."""
    from orchestrator import config
    src = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "src").rglob("*.py"))
    unread = [k for k in config.ENV_KEYS if f'"{k}"' not in src and f"'{k}'" not in src]
    assert not unread, f"ENV_KEYS không được đọc trong src/: {unread}"


def test_user_docs_have_no_todo_or_placeholder():
    bad = {}
    for name in ("README.md", "HUONG_DAN_GUI.md", "RELEASE_NOTES.md", "GUIDE.md", "METHODOLOGY.md"):
        p = ROOT / name
        if not p.exists():
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\bTODO\b|placeholder", line, re.IGNORECASE):
                bad.setdefault(name, []).append(n)
    assert not bad, f"còn TODO/placeholder trong docs người dùng: {bad}"


def test_release_notes_sections_and_packaging():
    rn = (ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8")
    for h in ("## 1. Tóm tắt theo khu vực", "## 2. Thay đổi HÀNH VI", "## 3. Lỗi đã biết", "## 4. Nâng cấp DB cũ"):
        assert h in rn, f"RELEASE_NOTES.md thiếu mục {h!r}"
    for must in ("--all", "n_expensive_ok", "idempotent", "user_version", "anchor_gap", "pywebview", "batch"):
        assert must in rn, f"RELEASE_NOTES.md thiếu từ khoá {must!r}"
    ps1 = (ROOT / "scripts" / "release.ps1").read_text(encoding="utf-8")
    assert "RELEASE_NOTES.md" in ps1, "scripts/release.ps1 chưa gom RELEASE_NOTES.md"
