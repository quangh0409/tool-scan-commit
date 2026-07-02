"""
14 đặc trưng Kamei (JIT defect prediction — Kamei et al. 2013, TSE).

Tính CHỈ từ git history (1 lệnh `git log --reverse -M --numstat`), không Docker/build:
  Diffusion : NS, ND, NF, Entropy
  Size      : LA, LD, LT
  Purpose   : FIX
  History   : NDEV, AGE, NUC
  Experience: EXP, REXP, SEXP

Nguyên tắc: duyệt lịch sử CŨ->MỚI một lượt, giữ state tăng dần; đặc trưng của 1 commit
chỉ nhìn QUÁ KHỨ (tính trước khi cập nhật state). Merge commit bỏ qua hoàn toàn
(không emit, không cập nhật state — chuẩn Kamei/Commit Guru). Lưu RAW value,
không normalize/log-transform (preprocessing để cho consumer).
"""
from __future__ import annotations

import datetime
import math
import re
import subprocess
from pathlib import Path

from . import config

# numstat rename: "dir/{old => new}/file" hoặc "old => new" (path nguyên)
_BRACE_RENAME_RE = re.compile(r"^(.*)\{(.*) => (.*)\}(.*)$")


def _fix_regex() -> re.Pattern:
    """Regex FIX từ config.FIX_KEYWORDS — khớp đầu-từ (fix -> fixes/fixed/bugfix? không:
    chỉ khi từ BẮT ĐẦU bằng keyword: 'fixes' có, 'prefix' không)."""
    kws = [re.escape(k.strip()) for k in config.FIX_KEYWORDS.split(",") if k.strip()]
    return re.compile(r"\b(?:" + "|".join(kws) + r")", re.IGNORECASE)


def _split_rename(path: str) -> tuple[str | None, str]:
    """Path numstat -> (old_path | None, new_path)."""
    if "=>" in path:
        m = _BRACE_RENAME_RE.match(path)
        if m:
            pre, old, new, post = m.groups()
            return ((pre + old + post).replace("//", "/"),
                    (pre + new + post).replace("//", "/"))
        if " => " in path:
            old, new = path.split(" => ", 1)
            return old, new
    return None, path


def _subsystem(path: str) -> str:
    return path.split("/", 1)[0] if "/" in path else "root"


def _directory(path: str) -> str:
    i = path.rfind("/")
    return path[:i] if i > 0 else "root"


def _iter_commits(repo_dir: Path, rev: str):
    """Yield dict {sha, parents, author, ts, message, files:[(add|None, del|None, old, new)]}
    theo thứ tự CŨ->MỚI. add/del=None với file nhị phân (numstat '-')."""
    fmt = "%x01%H%x02%P%x02%ae%x02%an%x02%at%x02%B%x03"
    proc = subprocess.Popen(
        ["git", "-C", str(repo_dir), "log", "--reverse", "-M", "--numstat",
         f"--pretty=format:{fmt}", rev],
        stdout=subprocess.PIPE, text=True, errors="replace")

    def _finish(rec):
        hdr = rec.pop("_hdr").split("\x03", 1)[0]
        sha, parents, email, name, ts, body = hdr.split("\x02", 5)
        rec.update(sha=sha, parents=parents.split(),
                   author=(email.strip() or name.strip()),
                   ts=int(ts), message=body)

    cur = None
    in_header = False
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip("\n")
        if line.startswith("\x01"):
            if cur is not None:
                yield cur
            cur = {"_hdr": line[1:], "files": []}
            in_header = "\x03" not in line
            if not in_header:
                _finish(cur)
        elif in_header:
            cur["_hdr"] += "\n" + line
            if "\x03" in line:
                in_header = False
                _finish(cur)
        elif cur is not None and line.strip():
            cols = line.split("\t")
            if len(cols) == 3:
                add = int(cols[0]) if cols[0].isdigit() else None
                dele = int(cols[1]) if cols[1].isdigit() else None
                old, new = _split_rename(cols[2])
                cur["files"].append((add, dele, old, new))
    if cur is not None:
        yield cur
    proc.wait()
    if proc.returncode:
        raise subprocess.CalledProcessError(proc.returncode, "git log --numstat")


def compute_features(repo_dir: Path, target_commits: set[str],
                     rev: str = "HEAD") -> dict[str, dict]:
    """Duyệt lịch sử `rev` CŨ->MỚI, trả {sha: {14 đặc trưng + author + author_date}}
    cho các sha thuộc target_commits (merge/unreachable sẽ vắng mặt)."""
    fix_re = _fix_regex()
    # state tăng dần (key = path hiện hành; rename chuyển state cũ sang path mới)
    file_loc: dict[str, int] = {}
    file_last_ts: dict[str, int] = {}
    file_authors: dict[str, set] = {}
    file_commits: dict[str, set] = {}
    author_nprev: dict[str, int] = {}
    author_prev_ts: dict[str, list] = {}
    subsys_nprev: dict[tuple, int] = {}

    out: dict[str, dict] = {}
    for idx, c in enumerate(_iter_commits(repo_dir, rev)):
        if len(c["parents"]) > 1:      # merge: bỏ qua hoàn toàn
            continue
        author, ts, files = c["author"], c["ts"], c["files"]
        # key tra cứu QUÁ KHỨ = old path (nếu rename) else path
        lookups = [(old or new) for _, _, old, new in files]
        subsystems = {_subsystem(new) for *_, new in files}

        if c["sha"] in target_commits:
            churns = [(a + d) for a, d, *_ in files if a is not None and d is not None]
            churns = [x for x in churns if x > 0]
            total = sum(churns)
            if len(churns) > 1 and total > 0:
                h = -sum((x / total) * math.log2(x / total) for x in churns)
                entropy = h / math.log2(len(churns))
            else:
                entropy = 0.0
            lts = [file_loc[p] for p in lookups if p in file_loc]
            ages = [(ts - file_last_ts[p]) / 86400.0
                    for p in lookups if p in file_last_ts]
            devs, prev_commits = set(), set()
            for p in lookups:
                devs |= file_authors.get(p, set())
                prev_commits |= file_commits.get(p, set())
            rexp = sum(1.0 / (max(ts - t, 0) / (86400.0 * 365.25) + 1.0)
                       for t in author_prev_ts.get(author, []))
            out[c["sha"]] = {
                "author": author,
                "author_date": datetime.datetime.fromtimestamp(
                    ts, tz=datetime.timezone.utc).isoformat(),
                "ns": len(subsystems),
                "nd": len({_directory(new) for *_, new in files}),
                "nf": len(files),
                "entropy": round(entropy, 6),
                "la": sum(a for a, *_ in files if a is not None),
                "ld": sum(d for _, d, *_ in files if d is not None),
                "lt": round(sum(lts) / len(lts), 3) if lts else 0.0,
                "fix": int(bool(fix_re.search(c["message"] or ""))),
                "ndev": len(devs),
                "age": round(sum(ages) / len(ages), 3) if ages else 0.0,
                "nuc": len(prev_commits),
                "exp": author_nprev.get(author, 0),
                "rexp": round(rexp, 6),
                "sexp": sum(subsys_nprev.get((author, s), 0) for s in subsystems),
            }

        # --- cập nhật state (SAU khi tính) ---
        for add, dele, old, new in files:
            if old is not None and old != new:   # rename: chuyển state sang path mới
                for st in (file_loc, file_last_ts, file_authors, file_commits):
                    if old in st:
                        st[new] = st.pop(old)
            if add is not None and dele is not None:
                file_loc[new] = file_loc.get(new, 0) + add - dele
            file_last_ts[new] = ts
            file_authors.setdefault(new, set()).add(author)
            file_commits.setdefault(new, set()).add(idx)
        author_nprev[author] = author_nprev.get(author, 0) + 1
        author_prev_ts.setdefault(author, []).append(ts)
        for s in subsystems:
            subsys_nprev[(author, s)] = subsys_nprev.get((author, s), 0) + 1
    return out
