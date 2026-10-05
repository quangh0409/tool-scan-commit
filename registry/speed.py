"""speed.json — tốc độ đo được trên máy này để ước tính thời gian run (CONTRACTS §7).

{"cheap_s_per_commit","build_cold_s","build_warm_s","fsb_s","sonar_s","buggy_ratio","samples"}
- Mặc định (chưa đo) = số đo trên máy dev 2026-10-04; `samples=0` → GUI ghi speed_source="default".
- update_from_db(db): expensive_runs.duration_sec theo tool/phase; build cold = lần build ok ĐẦU của
  mỗi run (có cột run_id thì theo run_id, không thì cả DB là 1 run), warm = còn lại.
  buggy_ratio = selected_commits(role=buggy) / scan_done.
- update_from_progress(path): wall-time/commit tầng rẻ = (ts item cuối − ts scan.start) / done.
- Trung bình trượt EMA alpha (mặc định 0.3) với giá trị cũ; lần đầu (samples=0) lấy thẳng trung bình.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from statistics import mean

from . import store as _store

DEFAULT = {
    "cheap_s_per_commit": 12.0,
    "build_cold_s": 900.0,
    "build_warm_s": 180.0,
    "fsb_s": 10.0,
    "sonar_s": 40.0,
    "buggy_ratio": 0.3,
    "samples": 0,
}
_KEYS = tuple(k for k in DEFAULT if k != "samples")


def path() -> Path:
    return _store.home() / "speed.json"


def load() -> dict:
    d = dict(DEFAULT)
    try:
        with open(path(), encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            for k in DEFAULT:
                if k in raw and isinstance(raw[k], (int, float)):
                    d[k] = raw[k]
            d["updated"] = raw.get("updated")
    except (OSError, ValueError):
        pass
    d["source"] = "measured" if d.get("samples", 0) > 0 else "default"
    return d


def save(d: dict) -> None:
    out = {k: d.get(k, DEFAULT[k]) for k in DEFAULT}
    out["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _store.atomic_write_json(path(), out)


def _ema(old: float, new_mean: float, had_samples: bool, alpha: float) -> float:
    if not had_samples:
        return float(new_mean)
    return (1.0 - alpha) * float(old) + alpha * float(new_mean)


def _merge(cur: dict, measured: dict[str, list[float]], alpha: float) -> dict:
    had = cur.get("samples", 0) > 0
    n_new = 0
    for k, vals in measured.items():
        vals = [float(v) for v in vals if v is not None and float(v) >= 0]
        if not vals or k not in _KEYS:
            continue
        cur[k] = round(_ema(cur[k], mean(vals), had, alpha), 3)
        n_new += len(vals)
    cur["samples"] = int(cur.get("samples", 0)) + n_new
    return cur


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def measure_db(db_path: str | Path) -> dict[str, list[float]]:
    """Trích mẫu thời lượng từ DB (read-only). Trả {key: [giây,...]} — không ghi speed.json."""
    out: dict[str, list[float]] = {"build_cold_s": [], "build_warm_s": [], "fsb_s": [], "sonar_s": [],
                                   "buggy_ratio": []}
    p = Path(db_path)
    if not p.exists():
        return out
    try:
        con = sqlite3.connect(p.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    except sqlite3.Error:
        return out
    try:
        cols = _columns(con, "expensive_runs")
        if not cols:
            return out
        has_run = "run_id" in cols
        sel = "commit_id, tool, phase, status, duration_sec, created_at, id" + (", run_id" if has_run else "")
        rows = con.execute(f"SELECT {sel} FROM expensive_runs WHERE duration_sec IS NOT NULL "
                           "ORDER BY created_at, id").fetchall()
        seen_cold: set[str] = set()
        for r in rows:
            tool, phase, status, dur = r[1], r[2], r[3], r[4]
            run_key = str(r[7]) if has_run and r[7] else "_all_"
            if status != "ok" or dur is None:
                continue
            if phase == "build":
                if run_key not in seen_cold:
                    seen_cold.add(run_key)
                    out["build_cold_s"].append(float(dur))
                else:
                    out["build_warm_s"].append(float(dur))
            elif tool == "findsecbugs":
                out["fsb_s"].append(float(dur))
            elif tool == "sonar":
                out["sonar_s"].append(float(dur))
        try:
            n_scanned = con.execute("SELECT COUNT(*) FROM scan_done").fetchone()[0]
            n_buggy = con.execute("SELECT COUNT(*) FROM selected_commits WHERE role='buggy'").fetchone()[0]
            if n_scanned and n_scanned > 0:
                out["buggy_ratio"].append(min(1.0, n_buggy / n_scanned))
        except sqlite3.Error:
            pass
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return out


def _parse_ts(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return time.mktime(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, OverflowError):
        return None


def measure_progress(progress_path: str | Path) -> dict[str, list[float]]:
    """Wall-time/commit của tầng rẻ từ progress.jsonl: (ts item cuối − ts scan.start) / done."""
    out: dict[str, list[float]] = {"cheap_s_per_commit": []}
    lines: list[dict] = []
    try:
        with open(progress_path, encoding="utf-8") as f:
            for line in f:
                try:
                    lines.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return out
    t0 = None
    last_t = None
    last_done = 0
    for rec in lines:
        if rec.get("phase") != "scan":
            continue
        ts = _parse_ts(rec.get("ts"))
        if rec.get("event") == "start":
            t0, last_t, last_done = ts, None, 0
        elif rec.get("event") == "item" and ts is not None:
            last_t = ts
            try:
                last_done = max(last_done, int(rec.get("done") or 0))
            except (TypeError, ValueError):
                pass
    if t0 is not None and last_t is not None and last_done > 0 and last_t >= t0:
        per = (last_t - t0) / last_done
        if per > 0:
            out["cheap_s_per_commit"].append(per)
    return out


def update_from_db(db_path: str | Path, alpha: float = 0.3) -> dict:
    cur = load()
    cur = _merge(cur, measure_db(db_path), alpha)
    save(cur)
    return load()


def update_from_progress(progress_path: str | Path, alpha: float = 0.3) -> dict:
    cur = load()
    cur = _merge(cur, measure_progress(progress_path), alpha)
    save(cur)
    return load()


def estimate(n_commits: int, workers_expensive: int = 1, tools: tuple[str, ...] = ("findsecbugs", "sonar"),
             speed: dict | None = None) -> dict:
    """Ước tính thô cho GUI (`/api/estimate`): phút tầng rẻ + đắt (cold/warm), speed_source."""
    s = speed or load()
    n = max(0, int(n_commits))
    buggy = int(round(n * float(s["buggy_ratio"])))
    per_tool = (float(s["fsb_s"]) if "findsecbugs" in tools else 0.0) + \
               (float(s["sonar_s"]) if "sonar" in tools else 0.0)
    w = max(1, int(workers_expensive))
    cold = (buggy * (float(s["build_cold_s"]) + per_tool)) / w
    warm = (buggy * (float(s["build_warm_s"]) + per_tool)) / w
    return {
        "commits": n,
        "buggy_est": buggy,
        "cheap_minutes": round(n * float(s["cheap_s_per_commit"]) / 60.0, 1),
        "expensive_minutes_cold": round(cold / 60.0, 1),
        "expensive_minutes_warm": round(warm / 60.0, 1),
        "speed_source": s.get("source", "default"),
    }
