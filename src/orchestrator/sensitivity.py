"""Phân tích độ nhạy tham số gán nhãn trên BẢN SAO DB (TOOL_IDEA §13, CLAUDE.md §12.9). Stdlib-only.

Lưới mặc định: line_window=3,5,7 × gold_allow_1exp_1cheap=0,1 × noise=on,off.
Mỗi cấu hình: copy DB -> <out>/<tên>.sqlite, set config tương ứng (CHỈ trong tiến trình này,
khôi phục sau), relabel mọi commit có raw, đếm gold/silver/candidate + κ -> sensitivity.json + .md.
KHÔNG đụng DB gốc. Cấu hình v1 (3,1,on) luôn được thêm làm mốc.
"""
from __future__ import annotations

import itertools
import json
import shutil
from pathlib import Path

from . import config, enumerate_commits as enm
from . import kappa as kp

DEFAULT_GRID = {"line_window": [3, 5, 7], "gold_allow_1exp_1cheap": [0, 1], "noise": ["on", "off"]}
KNOWN = {"line_window", "gold_allow_1exp_1cheap", "gold_min_expensive", "silver_min_cheap", "noise"}
V1 = {"line_window": 3, "gold_allow_1exp_1cheap": 1, "gold_min_expensive": 2, "silver_min_cheap": 2, "noise": "on"}


def parse_grid(items: list[str] | None) -> dict[str, list]:
    """['line_window=3,5,7', 'noise=on,off'] -> {'line_window':[3,5,7], 'noise':['on','off']}."""
    if not items:
        return {k: list(v) for k, v in DEFAULT_GRID.items()}
    grid: dict[str, list] = {}
    for it in items:
        if "=" not in it:
            raise ValueError(f"grid sai dạng (cần key=v1,v2): {it!r}")
        k, v = it.split("=", 1)
        k = k.strip()
        if k not in KNOWN:
            raise ValueError(f"grid: tham số lạ {k!r}; hợp lệ {sorted(KNOWN)}")
        vals = []
        for x in v.split(","):
            x = x.strip()
            if not x:
                continue
            if k == "noise":
                if x not in ("on", "off"):
                    raise ValueError("noise chỉ nhận on|off")
                vals.append(x)
            else:
                n = int(x)
                if n < 0 or (k == "line_window" and n < 1):
                    raise ValueError(f"{k}={x} không hợp lệ")
                vals.append(n)
        if not vals:
            raise ValueError(f"grid: {k} rỗng")
        grid[k] = vals
    return grid


def configs(grid: dict[str, list]) -> list[dict]:
    keys = sorted(grid)
    out = [dict(zip(keys, combo)) for combo in itertools.product(*(grid[k] for k in keys))]
    base = {k: V1[k] for k in keys}
    if base not in out:
        out.insert(0, base)
    return out


def config_name(c: dict) -> str:
    return "_".join(f"{k}-{c[k]}" for k in sorted(c))


def _apply(c: dict) -> dict:
    """Set config.* theo cấu hình; trả snapshot để khôi phục."""
    snap = {k: getattr(config, k) for k in ("LINE_WINDOW", "GOLD_ALLOW_1EXP_1CHEAP", "GOLD_MIN_EXPENSIVE",
                                            "SILVER_MIN_CHEAP", "NOISE_CWE", "NOISE_RULES")}
    if "line_window" in c:
        config.LINE_WINDOW = int(c["line_window"])
    if "gold_allow_1exp_1cheap" in c:
        config.GOLD_ALLOW_1EXP_1CHEAP = int(c["gold_allow_1exp_1cheap"])
    if "gold_min_expensive" in c:
        config.GOLD_MIN_EXPENSIVE = int(c["gold_min_expensive"])
    if "silver_min_cheap" in c:
        config.SILVER_MIN_CHEAP = int(c["silver_min_cheap"])
    if c.get("noise") == "off":
        config.NOISE_CWE = set()
        config.NOISE_RULES = set()
    return snap


def _restore(snap: dict) -> None:
    for k, v in snap.items():
        setattr(config, k, v)


def _default_relabel(store, cids: list[str], repo: str, clone_dir: Path) -> None:
    from .consensus.labeler import relabel_commit
    for cid in cids:
        relabel_commit(store, cid, clone_dir, repo)


def run(db: Path, out: Path, grid: dict[str, list], repo: str | None = None,
        relabel_fn=None, clone_dir: Path | None = None) -> dict:
    """Chạy lưới. relabel_fn(store, cids, repo, clone_dir) tiêm được (test không cần git)."""
    from .storage.sqlite_store import SQLiteStore
    db = Path(db)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if out.resolve() == db.parent.resolve() and (out / db.name).exists():
        raise ValueError("--out trùng thư mục DB gốc: từ chối để không ghi đè")

    import sqlite3
    src = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        if not repo:
            r = src.execute("SELECT repo FROM findings WHERE repo IS NOT NULL LIMIT 1").fetchone() \
                or src.execute("SELECT repo FROM raw_findings WHERE repo IS NOT NULL LIMIT 1").fetchone()
            repo = r[0] if r else None
        cids = [r[0] for r in src.execute("SELECT DISTINCT commit_id FROM raw_findings")]
    finally:
        src.close()
    if not repo:
        raise ValueError("không xác định được repo từ DB; truyền --repo")
    relabel_fn = relabel_fn or _default_relabel
    if relabel_fn is _default_relabel and clone_dir is None:
        clone_dir = enm.clone_or_update(repo)

    results = []
    for c in configs(grid):
        name = config_name(c)
        dst = out / f"{name}.sqlite"
        shutil.copy(db, dst)
        snap = _apply(c)
        try:
            store = SQLiteStore(dst)
            relabel_fn(store, cids, repo, clone_dir)
            labels = dict(store.conn.execute("SELECT COALESCE(label,'candidate'), COUNT(*) FROM findings GROUP BY 1"))
            kres = kp.compute_all(store)
            store.close()
        finally:
            _restore(snap)
        results.append({"name": name, "params": c, "db": str(dst),
                        "gold": int(labels.get("gold", 0)), "silver": int(labels.get("silver", 0)),
                        "candidate": int(labels.get("candidate", 0)),
                        "clusters": int(sum(labels.values())), "kappa": kres["total"], "kappa_n": kres["n"]})
    res = {"source_db": str(db), "repo": repo, "n_commits_relabeled": len(cids), "grid": grid,
           "v1": V1, "results": results}
    (out / "sensitivity.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "sensitivity.md").write_text(to_markdown(res), encoding="utf-8")
    return res


def to_markdown(res: dict) -> str:
    keys = sorted(res["grid"])
    hdr = "| " + " | ".join(keys) + " | gold | silver | candidate | cụm | κ | n |"
    sep = "|" + "---|" * (len(keys) + 6)
    lines = [f"# Độ nhạy tham số gán nhãn — {res['repo']}", "",
             f"Nguồn: `{res['source_db']}` · {res['n_commits_relabeled']} commit có raw · "
             f"mốc v1 = {json.dumps({k: res['v1'][k] for k in keys})}", "", hdr, sep]
    for r in res["results"]:
        k = f"{r['kappa']:.3f}" if isinstance(r["kappa"], (int, float)) else "-"
        mark = " **(v1)**" if all(r["params"].get(x) == res["v1"][x] for x in keys) else ""
        lines.append("| " + " | ".join(str(r["params"][x]) for x in keys)
                     + f" | {r['gold']}{mark} | {r['silver']} | {r['candidate']} | {r['clusters']} | {k} | {r['kappa_n']} |")
    lines += ["", "Giới hạn: relabel trên bản sao, cùng raw; thay đổi gold phản ánh độ nhạy của *quy tắc gộp/vote*, "
                  "không phải độ đúng — cần kiểm tay gold mới sinh khi nới window (RULE_GAN_NHAN §9)."]
    return "\n".join(lines) + "\n"
