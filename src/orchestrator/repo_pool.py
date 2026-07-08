"""
Pool clone độc lập để SONG SONG CẤP COMMIT (mỗi worker checkout 1 commit riêng).

Vì sao là CLONE chứ không phải `git worktree`:
  - Mục tiêu của worktree: cho K commit checkout đồng thời mà KHÔNG tranh HEAD trên
    1 working-tree (nút thắt tuần tự hiện tại).
  - NHƯNG worktree để `.git` là 1 FILE `gitdir: <main>/.git/worktrees/..`; khi mount
    riêng thư mục worktree vào container, đường dẫn đó KHÔNG tồn tại trong container
    -> tool git-mode (gitleaks/trufflehog) gãy.
  - `git clone --local --no-checkout` cho mỗi worker 1 repo ĐỘC LẬP, `.git` là thư mục
    THẬT (object hardlink từ main -> gần như tức thì, ~0 đĩa cho objects). Mọi wrapper
    chạy y nguyên, không sửa. Đây là cách lấy đúng sự cô lập mà worktree hướng tới.

Mỗi clone tái sử dụng qua nhiều commit (checkout --detach <SHA> mỗi lần) -> không
phải clone lại; "tool xong trước thì nhả clone cho commit kế" = hàng đợi blocking.
"""
from __future__ import annotations

import os
import queue
import shutil
import subprocess
from pathlib import Path

from . import config


class RepoPool:
    def __init__(self, main_repo: Path, size: int):
        self.main = Path(main_repo)
        self.size = max(1, size)
        # base RIÊNG theo PID -> 2 tiến trình orchestrator chạy đồng thời không clobber nhau.
        self.base = config.WORK_DIR / f"pool_{os.getpid()}"
        self._q: "queue.Queue[Path]" = queue.Queue()
        self._all: list[Path] = []
        self._setup()

    def _setup(self) -> None:
        # dọn pool cũ rồi tạo K clone hardlink (rẻ) — sẵn sàng tái sử dụng.
        shutil.rmtree(self.base, ignore_errors=True)
        self.base.mkdir(parents=True, exist_ok=True)
        for i in range(self.size):
            dst = self.base / f"w{i}"
            subprocess.run(
                ["git", "clone", "--local", "--no-checkout",
                 str(self.main), str(dst)],
                check=True, capture_output=True, text=True,
            )
            self._all.append(dst)
            self._q.put(dst)

    def acquire(self) -> Path:
        """Chờ tới khi có 1 clone rảnh (blocking) rồi chiếm nó."""
        return self._q.get()

    def release(self, clone: Path) -> None:
        self._q.put(clone)

    def checkout(self, clone: Path, sha: str) -> None:
        # -f: artefact build sót lại (untracked) trong clone tái sử dụng có thể
        # đụng độ file của commit đích -> checkout trần bị git từ chối.
        cmd = ["git", "-C", str(clone), "checkout", "-qf", "--detach", sha]
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        if r.returncode != 0:
            # còn kẹt (vd file untracked chắn thư mục) -> dọn sạch rồi thử lại lần cuối
            subprocess.run(["git", "-C", str(clone), "clean", "-fdxq"],
                           capture_output=True, text=True)
            subprocess.run(cmd, check=True, capture_output=True, text=True, errors="replace")
        self._init_submodules(clone)

    def _init_submodules(self, clone: Path) -> None:
        # Repo kiểu skywalking để protocol/UI trong submodule; thiếu nó thì build tầng
        # đắt fail hàng loạt. Store submodule nằm ở .git/modules/ và clone được TÁI SỬ
        # DỤNG qua nhiều commit -> chỉ tốn mạng lần đầu mỗi clone, sau đó gần như free.
        # Lỗi ở đây KHÔNG chặn checkout: thiếu submodule thì để build tự quyết sống/chết.
        if not config.SUBMODULES or not (clone / ".gitmodules").exists():
            return
        subprocess.run(["git", "-C", str(clone), "submodule", "sync", "--recursive"],
                       capture_output=True, text=True, errors="replace")
        subprocess.run(["git", "-C", str(clone), "submodule", "update", "--init",
                        "--recursive", "--jobs", "4"],
                       capture_output=True, text=True, errors="replace")

    def cleanup(self) -> None:
        shutil.rmtree(self.base, ignore_errors=True)
