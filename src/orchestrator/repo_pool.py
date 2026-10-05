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

Kiểm ORIGIN (REVIEW D4/TC-07): clone chính trong WORK_DIR có thể là repo KHÁC trùng tên
(vd 2 org cùng tên repo). RepoPool(repo=<url>) so `git remote get-url origin` của clone chính
với keys.canon_repo(repo); lệch -> raise OriginMismatch rõ ràng, không quét nhầm im lặng.
"""
from __future__ import annotations

import os
import queue
import shutil
import stat
import subprocess
from pathlib import Path

from . import config, keys


class OriginMismatch(RuntimeError):
    """Clone trong WORK_DIR trỏ tới repo khác với repo yêu cầu."""


def rmtree_force(path: Path) -> None:
    """rmtree chịu được file read-only (.git/objects/pack/* trên Windows có cờ R ->
    rmtree(ignore_errors=True) bỏ qua LẶNG LẼ, để rác pool_* tích dần).
    Dùng cho cmd_clean (REVIEW D7/TC-19) — không cần Docker."""
    path = Path(path)
    if not path.exists():
        return

    def _onerr(fn, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            fn(p)
        except OSError:
            pass
    shutil.rmtree(path, onerror=_onerr)


_rmtree = rmtree_force   # alias nội bộ (tên cũ)


def origin_url(repo_dir: Path) -> str | None:
    """`git remote get-url origin` của 1 clone; None nếu không có remote/không phải git."""
    try:
        r = subprocess.run(["git", "-C", str(repo_dir), "remote", "get-url", "origin"],
                           capture_output=True, text=True, errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    out = (r.stdout or "").strip()
    return out if r.returncode == 0 and out else None


def verify_origin(repo_dir: Path, repo: str) -> str:
    """Bảo đảm clone `repo_dir` thật sự là `repo` (so canon_repo). Trả origin canon.
    Raise OriginMismatch nếu lệch; nếu không đọc được origin -> cũng raise (không đoán)."""
    org = origin_url(repo_dir)
    if not org:
        raise OriginMismatch(f"không đọc được origin của clone {repo_dir}")
    want, have = keys.canon_repo(repo), keys.canon_repo(org)
    if want.lower() != have.lower():
        raise OriginMismatch(
            f"clone {repo_dir} trỏ tới {have} nhưng run yêu cầu {want} "
            f"(trùng tên repo khác org?). Đổi ORCH_WORK_DIR hoặc xoá clone cũ.")
    return have


class RepoPool:
    def __init__(self, main_repo: Path, size: int, repo: str | None = None):
        self.main = Path(main_repo)
        self.size = max(1, size)
        self.repo = repo
        self._origin_ok = False
        if repo:
            # kiểm 1 lần lúc dựng pool: fail sớm trước khi clone K bản
            verify_origin(self.main, repo)
            self._origin_ok = True
        # base RIÊNG theo PID -> 2 tiến trình orchestrator chạy đồng thời không clobber nhau.
        self.base = config.WORK_DIR / f"pool_{os.getpid()}"
        self._q: "queue.Queue[Path]" = queue.Queue()
        self._all: list[Path] = []
        self._setup()

    def _setup(self) -> None:
        # dọn pool cũ rồi tạo K clone hardlink (rẻ) — sẵn sàng tái sử dụng.
        rmtree_force(self.base)
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
        # Kiểm origin của clone CHÍNH (pool clone có origin = đường dẫn local của main, nên
        # phải so ở main). Chỉ kiểm 1 lần/pool (cache) — fail rõ ràng nếu lệch (D4).
        if self.repo and not self._origin_ok:
            verify_origin(self.main, self.repo)
            self._origin_ok = True
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
        rmtree_force(self.base)
