"""repo_pool.rmtree_force xoá được cây có file/thư mục read-only lồng sâu (.git/objects/pack trên Windows)."""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest


def _make_tree(root: Path, depth: int = 6) -> list[Path]:
    files = []
    d = root
    for i in range(depth):
        d = d / f"lv{i} ô'ng"
        d.mkdir(parents=True)
        f = d / f"pack-{i}.idx"
        f.write_bytes(b"x" * 10)
        os.chmod(f, stat.S_IREAD)                    # read-only
        files.append(f)
    # thư mục read-only ở giữa (POSIX: không xoá được con nếu không có w)
    if sys.platform != "win32":
        os.chmod(files[2].parent, stat.S_IREAD | stat.S_IEXEC)
    return files


def test_rmtree_force_removes_readonly_nested(tmp_path):
    from orchestrator.repo_pool import rmtree_force
    root = tmp_path / "pool_1"
    files = _make_tree(root)
    assert all(f.exists() for f in files)
    rmtree_force(root)
    assert not root.exists()


def test_rmtree_force_missing_path_noop(tmp_path):
    from orchestrator.repo_pool import rmtree_force
    rmtree_force(tmp_path / "khong-ton-tai")        # không raise


@pytest.mark.skipif(sys.platform != "win32", reason="chỉ Windows mới chặn unlink file read-only")
def test_plain_rmtree_fails_on_readonly_windows(tmp_path):
    """Chứng minh vì sao cần rmtree_force: shutil.rmtree thường thất bại trên Windows với file R."""
    import shutil
    root = tmp_path / "pool_2"
    _make_tree(root, depth=2)
    with pytest.raises(PermissionError):
        shutil.rmtree(root)
    assert root.exists()
    from orchestrator.repo_pool import rmtree_force
    rmtree_force(root)
    assert not root.exists()
