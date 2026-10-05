"""Phiên bản app: env SECJIT_APP_VERSION → file `_version_build.txt` (ghi lúc build) → `git describe` → 'dev'.

build_exe.ps1 ghi `packaging/_version_build.txt` = `git describe --tags --always --dirty` trước khi gọi PyInstaller;
secjit.spec đóng file đó vào bundle (packaging/_version_build.txt) để exe biết phiên bản mà không cần git.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BUILD_FILE = "_version_build.txt"


def _candidates() -> list[Path]:
    here = Path(__file__).resolve().parent
    out = [here / BUILD_FILE]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        out.append(Path(meipass) / "packaging" / BUILD_FILE)
        out.append(Path(meipass) / BUILD_FILE)
    return out


def from_build_file() -> str | None:
    for p in _candidates():
        try:
            v = p.read_text(encoding="utf-8").strip()
            if v:
                return v
        except OSError:
            continue
    return None


def from_git(repo_root: Path | None = None) -> str | None:
    if getattr(sys, "frozen", False):
        return None
    root = repo_root or Path(__file__).resolve().parents[1]
    try:
        r = subprocess.run(["git", "-C", str(root), "describe", "--tags", "--always", "--dirty"],
                           capture_output=True, text=True, errors="replace", timeout=10)
        v = (r.stdout or "").strip()
        return v if r.returncode == 0 and v else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def get_version() -> str:
    return os.environ.get("SECJIT_APP_VERSION") or from_build_file() or from_git() or "dev"


def write_build_file(version: str | None = None, dest: Path | None = None) -> Path:
    """Ghi _version_build.txt (dùng bởi build_exe.ps1 / CI khi không có PowerShell)."""
    v = version or from_git() or "dev"
    p = dest or (Path(__file__).resolve().parent / BUILD_FILE)
    p.write_text(v, encoding="utf-8")
    return p


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--write":
        print(write_build_file().read_text(encoding="utf-8"))
    else:
        print(get_version())
