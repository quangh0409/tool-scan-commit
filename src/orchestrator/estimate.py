"""Ước tính thời gian/đĩa cho 1 profile (CONTRACTS §9 `/api/estimate`, §7 speed.json). Stdlib-only.

Đầu ra: {commits_after_filter, buggy_est, cheap_minutes, expensive_minutes_cold,
         expensive_minutes_warm, disk_gb, speed_source:"measured|default"}.

speed.json (`%LOCALAPPDATA%/secjit/speed.json`, Linux `~/.local/share/secjit/speed.json`):
  {"cheap_s_per_commit","build_cold_s","build_warm_s","fsb_s","sonar_s","samples"[, "buggy_ratio"]}
Thiếu file / thiếu khoá -> dùng DEFAULT_SPEED (đo từ các run thật trong SESSION_CONTEXT).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import config, enumerate_commits as enm

DEFAULT_SPEED = {
    "cheap_s_per_commit": 12.0,   # 5 tool rẻ song song / commit
    "build_cold_s": 900.0,        # Maven cache lạnh (Windows đo 881 s, SESSION 2026-10-04)
    "build_warm_s": 180.0,
    "fsb_s": 10.0,
    "sonar_s": 40.0,
    "codeql_s": 400.0,            # suite tối giản ~6.7'; suite full ~20'
    "samples": 0,
}
DEFAULT_BUGGY_RATIO = 0.3
# Đĩa (GB) — heuristic từ các export thật: train-ticket 274 commit = 516 MB export; clone ~0.3 GB;
# pool = workers × clone (hardlink -> ~0.1 GB mỗi cái); .m2 ấm ~2 GB; Sonar data ~1 GB.
DISK_BASE_GB = 0.5
DISK_PER_COMMIT_GB = 0.002
DISK_PER_EXPENSIVE_COMMIT_GB = 0.01
DISK_M2_GB = 2.0
DISK_SONAR_GB = 1.0


def speed_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "secjit" / "speed.json"
    return Path.home() / ".local" / "share" / "secjit" / "speed.json"


def load_speed(path: str | Path | None = None) -> tuple[dict, str]:
    """-> (speed dict đủ khoá, 'measured'|'default'). File hỏng/thiếu -> default."""
    p = Path(path) if path else speed_path()
    sp = dict(DEFAULT_SPEED)
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return sp, "default"
    if not isinstance(data, dict):
        return sp, "default"
    measured = False
    for k in DEFAULT_SPEED:
        v = data.get(k)
        if isinstance(v, (int, float)) and v >= 0:
            sp[k] = float(v)
            if k != "samples":
                measured = True
    if isinstance(data.get("buggy_ratio"), (int, float)) and 0 <= data["buggy_ratio"] <= 1:
        sp["buggy_ratio"] = float(data["buggy_ratio"])
    return sp, ("measured" if measured and sp.get("samples", 0) > 0 else "default")


def count_commits_fast(p: dict) -> int:
    """Đếm NHANH (2 lệnh git, không đọc diff từng commit, không fetch): commit trong phạm vi trừ merge.

    Lỗi thật 2026-10-05: `count_commits` đầy đủ chạy `get_commit_info` cho MỌI commit (3 lệnh git/commit)
    + `git fetch` mỗi lần -> toàn lịch sử train-ticket 46 s, repo lớn > 60 s -> GUI báo "Backend không trả lời".
    Sai số so với lọc thô đầy đủ: chưa trừ commit chỉ đụng file nhị phân / commit khổng lồ (khi FLAG_LIMIT=1)
    -> ước tính hơi cao (an toàn cho ước lượng thời gian/đĩa).
    """
    sc = p["scope"]
    mx = sc.get("max") if sc.get("mode") == "count" else 0
    repo_dir = enm.clone_or_update(p["repo"], fetch=False)
    rev = enm.resolve_rev(repo_dir, p.get("branch") or None)
    ids = enm.list_commits(repo_dir, mx, rev, since=sc.get("since"), until=sc.get("until"),
                           from_sha=sc.get("from_sha"), to_sha=sc.get("to_sha"))
    merges = set(enm._git(repo_dir, "log", "--merges", "--pretty=%H", rev).split()) if ids else set()
    return sum(1 for c in ids if c not in merges)


def count_commits(p: dict) -> int:
    """Số commit sau lọc thô ĐẦY ĐỦ theo scope profile (clone nếu cần). Chậm: dùng cho CLI `--exact`."""
    sc = p["scope"]
    mx = sc.get("max") if sc.get("mode") == "count" else 0
    n = 0
    for _ci, keep, _reason in enm.enumerate_repo(p["repo"], mx, p.get("branch") or None,
                                                 since=sc.get("since"), until=sc.get("until"),
                                                 from_sha=sc.get("from_sha"), to_sha=sc.get("to_sha")):
        n += int(keep)
    return n


def estimate(p: dict, n_commits: int | None = None, speed: dict | None = None,
             speed_source: str | None = None) -> dict:
    """Ước tính cho profile p. n_commits/speed truyền sẵn -> không enumerate/đọc file (test)."""
    if speed is None:
        speed, speed_source = load_speed()
    speed_source = speed_source or "default"
    approx = False
    if n_commits is None:
        n_commits = count_commits_fast(p)
        approx = True

    ratio = speed.get("buggy_ratio", DEFAULT_BUGGY_RATIO)
    buggy = int(round(n_commits * ratio))
    w_scan = max(1, int(p.get("workers", {}).get("scan", config.SCAN_WORKERS)))
    w_exp = max(1, int(p.get("workers", {}).get("expensive", config.EXPENSIVE_WORKERS)))

    exp_tools = list(p.get("expensive_tools") or [])
    if p.get("codeql") and "codeql" not in exp_tools:
        exp_tools.append("codeql")
    if not p.get("codeql"):
        exp_tools = [t for t in exp_tools if t != "codeql"]
    tool_s = sum({"findsecbugs": speed["fsb_s"], "sonar": speed["sonar_s"],
                  "codeql": speed["codeql_s"]}.get(t, 0.0) for t in exp_tools)
    n_expensive = buggy + (n_commits - buggy if p.get("include_clean") else 0)
    n_expensive = n_expensive if exp_tools else 0

    cheap_min = n_commits * speed["cheap_s_per_commit"] / w_scan / 60.0
    cold_min = n_expensive * (speed["build_cold_s"] + tool_s) / w_exp / 60.0
    warm_min = n_expensive * (speed["build_warm_s"] + tool_s) / w_exp / 60.0
    disk = (DISK_BASE_GB + n_commits * DISK_PER_COMMIT_GB + n_expensive * DISK_PER_EXPENSIVE_COMMIT_GB
            + (DISK_M2_GB if n_expensive else 0) + (DISK_SONAR_GB if "sonar" in exp_tools else 0)
            + 0.1 * w_scan)
    return {
        "commits_after_filter": n_commits,
        "buggy_est": buggy,
        "cheap_minutes": int(round(cheap_min)),
        "expensive_minutes_cold": int(round(cold_min)),
        "expensive_minutes_warm": int(round(warm_min)),
        "disk_gb": round(disk, 1),
        "speed_source": speed_source,
        # approx=True: đếm nhanh (trừ merge, CHƯA trừ commit nhị phân/khổng lồ) -> số thật có thể thấp hơn chút
        "approx": approx,
        "detail": {"n_expensive": n_expensive, "expensive_tools": exp_tools, "buggy_ratio": ratio,
                   "workers": {"scan": w_scan, "expensive": w_exp}, "speed": speed},
    }


def format_text(r: dict) -> str:
    return (f"commit sau lọc: {r['commits_after_filter']} | buggy ước: {r['buggy_est']}\n"
            f"tầng rẻ ≈ {r['cheap_minutes']} phút | tầng đắt ≈ {r['expensive_minutes_cold']} phút (cache lạnh) "
            f"/ {r['expensive_minutes_warm']} phút (ấm)\n"
            f"đĩa ≈ {r['disk_gb']} GB | nguồn tốc độ: {r['speed_source']}")
