"""Kiểm tay MÙ nhãn GOLD (CONTRACTS §4 gold_review/gold_sample, §9 review API; TOOL_IDEA §13).

Vì sao: consensus máy = nhãn BẠC/VÀNG-máy, không phải chân lý. Precision thật của gold phải đo bằng
người chấm mù (không thấy nhãn/tool/số tool đồng thuận), kèm khoảng tin cậy Wilson và độ đồng thuận
giữa người chấm (Cohen κ). Mục âm (verified-clean) được kiểm riêng ("thật sự sạch").

Quy ước verdict: TP = nhãn máy ĐÚNG (cụm gold là lỗ hổng thật / commit verified-clean thật sự sạch);
FP = nhãn máy SAI; unclear = không kết luận được. Rater đặc biệt 'adjudicated' = phán quyết sau
hoà giải, được ưu tiên khi tính precision và evidence.validation.

API (A2 nối CLI `review …`, A5 nối GUI /api/review):
  sample(store, seed, n_pos=200, n_neg=100) -> {sample_id, n_pos, n_neg, strata[{stratum, kind, n, total}]}
  next_item(store, sample_id, rater) -> item | None     (MÙ: không label/tools/n_agree/tier)
  verdict(store, sample_id, rater, cluster_key, verdict, note="") -> {ok, remaining}
  close(store, sample_id, raters=None) -> {precision, neg_precision, kappa_raters, disagreements, by_stratum, …}
  validation_of(pairs) -> 'TP'|'FP'|'unclear'|'unreviewed'   (export dùng)
Chạy độc lập: python -m orchestrator.review sample|next|verdict|close --db DB [--json] …
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from . import keys
from .consensus.cwe_groups import cwe_group as _cwe_group

VERDICTS = ("TP", "FP", "unclear")
ADJUDICATED = "adjudicated"
CODE_CONTEXT = 8          # ±dòng quanh s_line
Z95 = 1.959963984540054   # z_{0.975}

_TOOL_WORDS = ("gitleaks", "trufflehog", "semgrep", "bearer", "horusec", "codeql",
               "findsecbugs", "find security bugs", "spotbugs", "sonarqube", "sonar", "snyk")
_TOOL_RE = re.compile("|".join(re.escape(w) for w in sorted(_TOOL_WORDS, key=len, reverse=True)), re.I)
_RULE_RE = re.compile(r"\b[a-z]+(?:[_\-:.][a-z0-9]+){2,}\b", re.I)   # kiểu javascript_lang_x_y, java:S2077


# ---------------------------------------------------------------- tiện ích
def _loads(v, default):
    if isinstance(v, (list, dict)):
        return v
    try:
        return json.loads(v) if v else default
    except (TypeError, ValueError):
        return default


def cluster_key_of(row: dict) -> str:
    return keys.cluster_key(row.get("repo") or "", row.get("commit_id") or "", row.get("file_path") or "",
                            row.get("cwe_group") or "", int(row.get("s_line") or 0))


def neg_key(commit_id: str) -> str:
    return f"neg:{commit_id}"


def stratum_of(row: dict) -> str:
    return f"{row.get('cwe_group') or '?'}|{row.get('tier') or '?'}"


def wilson(k: int, n: int, z: float = Z95) -> tuple[float | None, float | None, float | None]:
    """Khoảng tin cậy Wilson score (Brown, Cai & DasGupta 2001) cho tỉ lệ k/n -> (point, low, high)."""
    if n <= 0:
        return None, None, None
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return p, max(0.0, centre - half), min(1.0, centre + half)


def cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Cohen κ (3 lớp TP/FP/unclear) trên các mục cả 2 rater đã chấm. None nếu không tính được."""
    n = len(pairs)
    if n == 0:
        return None
    po = sum(1 for a, b in pairs if a == b) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[c] * cb[c] for c in VERDICTS) / (n * n)
    if pe >= 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def validation_of(pairs: list[tuple[str, str]] | None) -> str:
    """Gộp verdict nhiều rater -> TP|FP|unclear|unreviewed. 'adjudicated' thắng; else đa số; hoà -> unclear."""
    if not pairs:
        return "unreviewed"
    for rater, v in pairs:
        if rater == ADJUDICATED:
            return v
    c = Counter(v for _, v in pairs).most_common()
    if len(c) > 1 and c[0][1] == c[1][1]:
        return "unclear"
    return c[0][0]


def allocate(sizes: dict[str, int], n: int) -> dict[str, int]:
    """Phân bổ n theo tỉ lệ sizes (clamp theo số có; mỗi tầng có dữ liệu ≥1 nếu đủ chỗ; largest-remainder)."""
    total = sum(sizes.values())
    n = min(n, total)
    if n <= 0 or total <= 0:
        return {k: 0 for k in sizes}
    exact = {k: n * s / total for k, s in sizes.items()}
    alloc = {k: min(sizes[k], int(math.floor(exact[k]))) for k in sizes}
    for k in sizes:                                  # mỗi tầng có dữ liệu ≥ 1
        if sizes[k] > 0 and alloc[k] == 0:
            alloc[k] = 1
    order = sorted(sizes, key=lambda k: (-(exact[k] - math.floor(exact[k])), k))
    i = 0
    while sum(alloc.values()) < n and i < 10 * len(order) + 10:
        k = order[i % len(order)]
        if alloc[k] < sizes[k]:
            alloc[k] += 1
        i += 1
    while sum(alloc.values()) > n:                   # thừa vì ép ≥1 -> bớt tầng lớn nhất (>1 trước)
        pool = [k for k in alloc if alloc[k] > 1] or [k for k in alloc if alloc[k] > 0]
        k = max(pool, key=lambda k: (alloc[k], -sizes[k], k))   # n < số tầng: tầng nhỏ về 0 trước
        alloc[k] -= 1
    return alloc


# ---------------------------------------------------------------- 1. sample
def sample(store, seed: int, n_pos: int = 200, n_neg: int = 100, sample_id: str | None = None) -> dict:
    """Tạo mẫu kiểm tay: cụm gold phân tầng cwe_group×tier + commit verified-clean. Ghi gold_sample.
    sample_id mặc định `s-<seed>-<yyyymmdd>`; cùng seed + cùng DB -> cùng mẫu (random.Random(seed))."""
    seed = int(seed)
    rng = random.Random(seed)
    sample_id = sample_id or f"s-{seed}-{time.strftime('%Y%m%d')}"

    gold = store.findings_rows(label="gold")
    by_stratum: dict[str, dict[str, dict]] = {}
    for r in gold:
        by_stratum.setdefault(stratum_of(r), {})[cluster_key_of(r)] = r
    sizes = {s: len(d) for s, d in sorted(by_stratum.items())}
    alloc = allocate(sizes, max(0, int(n_pos)))
    rows, strata = [], []
    for s in sorted(sizes):
        pool = sorted(by_stratum[s])                              # thứ tự ổn định trước khi rút
        picked = sorted(rng.sample(pool, alloc[s])) if alloc[s] else []
        rows += [{"cluster_key": ck, "stratum": s, "kind": "pos", "seed": seed} for ck in picked]
        strata.append({"stratum": s, "kind": "pos", "n": len(picked), "total": sizes[s]})

    negs = sorted(store.verified_clean_commits())
    k_neg = min(max(0, int(n_neg)), len(negs))
    picked_neg = sorted(rng.sample(negs, k_neg)) if k_neg else []
    rows += [{"cluster_key": neg_key(c), "stratum": "verified-clean", "kind": "neg", "seed": seed}
             for c in picked_neg]
    strata.append({"stratum": "verified-clean", "kind": "neg", "n": len(picked_neg), "total": len(negs)})

    store.replace_gold_sample(sample_id, rows)
    n_pos_out = sum(1 for r in rows if r["kind"] == "pos")
    empty = n_pos_out == 0 and len(picked_neg) == 0
    return {"sample_id": sample_id, "seed": seed,
            "n_pos": n_pos_out, "n_neg": len(picked_neg), "strata": strata,
            "available": {"gold_clusters": len(gold), "verified_clean": len(negs)},
            # GUI hiện empty state thay vì màn chấm trống (DB chưa có gold / verified-clean)
            "empty": empty,
            "message": ("Chưa có cụm gold hay commit verified-clean để kiểm tay: cần chạy tầng đắt "
                        "(≥2 tool đắt đồng thuận → gold; ≥2 tool đắt ok trên commit sạch → verified-clean)."
                        if empty else None)}


# ---------------------------------------------------------------- 2. next_item (MÙ)
def _anon(msg: str | None, rule_id: str | None) -> str:
    s = (msg or "").strip()
    if rule_id:
        s = s.replace(rule_id, "[rule]")
    s = _TOOL_RE.sub("[tool]", s)
    s = _RULE_RE.sub("[rule]", s)
    return s[:300]


def _code_and_diff(row: dict) -> tuple[list[dict], list[dict], str]:
    """-> (code_lines ±CODE_CONTEXT quanh s_line, diff_lines, code_source ∈ diff|snippet|none)."""
    s_line = int(row.get("s_line") or 0)
    detail = set(_loads(row.get("s_detail_line"), []) or [])
    dp = _loads(row.get("diff_parsed"), {}) or {}
    added = [(int(n), t) for n, t in dp.get("added", []) if n is not None]
    deleted = [(int(n), t) for n, t in dp.get("deleted", []) if n is not None]
    lo, hi = s_line - CODE_CONTEXT, s_line + CODE_CONTEXT
    code = [{"n": n, "text": t, "flag": n in detail} for n, t in sorted(added) if lo <= n <= hi]
    source = "diff" if code else "none"
    if not code and row.get("code_snippet"):
        code = [{"n": s_line + i, "text": t, "flag": i == 0}
                for i, t in enumerate(str(row["code_snippet"]).splitlines()[:CODE_CONTEXT * 2 + 1])]
        source = "snippet"
    diff = ([{"n": n, "kind": "del", "text": t} for n, t in deleted]
            + [{"n": n, "kind": "flag" if n in detail else "add", "text": t} for n, t in added])
    diff.sort(key=lambda d: (d["n"], d["kind"] != "del"))
    return code, diff, source


# ---------------------------------------------------------------- RV-1: code ngoài diff (in_diff=0) -> git show
def find_clone(repo: str, work_dir: str | Path | None = None) -> Path | None:
    """Clone của `repo` trong work_dir (mặc định config.WORK_DIR): `<slug>` (keys.repo_slug) hoặc tên cũ `<repo>`;
    phải có .git và origin khớp keys.canon_repo (không đọc nhầm repo trùng tên). None nếu không có."""
    from . import config
    from .repo_pool import origin_url
    if not repo:
        return None
    base = Path(work_dir) if work_dir else config.WORK_DIR
    legacy = repo.rstrip("/").removesuffix(".git").split("/")[-1]
    want = keys.canon_repo(repo).lower()
    for name in (keys.repo_slug(repo), legacy):
        d = base / name
        if not (d / ".git").exists():
            continue
        org = origin_url(d)
        if org and keys.canon_repo(org).lower() == want:
            return d
    return None


def code_context(store, repo: str, commit: str, file_path: str, s_line: int,
                 context: int = CODE_CONTEXT, work_dir: str | Path | None = None) -> dict:
    """Code ±context dòng quanh s_line lấy từ `git show <commit>:<file_path>` trong clone local (không clone mới,
    không mạng). `store` không dùng (giữ chữ ký chung với GUI). Trả
    {"code_lines": [{n, text, flag}], "code_source": "git_show" | "none", "clone": str|None, "error": str|None}."""
    out = {"code_lines": [], "code_source": "none", "clone": None, "error": None}
    clone = find_clone(repo, work_dir)
    if clone is None:
        out["error"] = "không có clone trong ORCH_WORK_DIR"
        return out
    out["clone"] = str(clone)
    try:
        r = subprocess.run(["git", "-C", str(clone), "show", f"{commit}:{file_path}"],
                           capture_output=True, text=True, errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        out["error"] = f"git show lỗi: {e}"
        return out
    if r.returncode != 0:
        out["error"] = (r.stderr or "git show rc!=0").strip()[:200]
        return out
    lines = r.stdout.splitlines()
    s = int(s_line or 0)
    lo, hi = max(1, s - context), min(len(lines), s + context)
    if s < 1 or s > len(lines):
        out["error"] = f"s_line {s} ngoài file ({len(lines)} dòng)"
        return out
    out["code_lines"] = [{"n": n, "text": lines[n - 1], "flag": n == s} for n in range(lo, hi + 1)]
    out["code_source"] = "git_show"
    return out


def _index(store) -> dict[str, dict]:
    """{cluster_key: findings row} — tính lại từ findings hiện tại (map lại sau relabel)."""
    return {cluster_key_of(r): r for r in store.findings_rows()}


def _item_pos(store, row: dict, line_window: int) -> dict:
    code, diff, source = _code_and_diff(row)
    if not code:    # RV-1: dòng tool báo ngoài diff (in_diff=0) -> đọc file tại commit từ clone local
        cc = code_context(store, row.get("repo") or "", row["commit_id"], row.get("file_path") or "",
                          int(row.get("s_line") or 0))
        code, source = cc["code_lines"], cc["code_source"]
    cwes = _loads(row.get("cwe"), [])
    grp = row.get("cwe_group") or (_cwe_group(cwes[0])[0] if cwes else None)
    msgs = []
    for f in store.raw_for_commit(row["commit_id"]):
        if f.file_path != row.get("file_path"):
            continue
        if abs(int(f.s_line) - int(row.get("s_line") or 0)) > line_window:
            continue
        m = _anon(f.message, f.rule_id)
        if m and m not in msgs:
            msgs.append(m)
    return {
        "kind": "pos", "commit": row["commit_id"], "repo": row.get("repo"),
        "file_path": row.get("file_path"), "s_line": row.get("s_line"), "e_line": row.get("e_line"),
        "s_detail_line": _loads(row.get("s_detail_line"), []),
        "cwe_claim": {"cwe": cwes, "group": grp, "category": row.get("category")},
        "finding_in_diff": row.get("finding_in_diff"),
        "code_lines": code, "code_source": source, "diff_lines": diff, "messages_anon": msgs,
        "code_after_url": row.get("code_after_url"), "code_before_url": row.get("code_before_url"),
    }


def _item_neg(store, commit_id: str) -> dict:
    from . import enumerate_commits as enm
    repo = None
    r = store.conn.execute("SELECT repo, author_date FROM commit_features WHERE commit_id=?",
                           [commit_id]).fetchone()
    if r:
        repo = r[0]
    files = store.scanned_files_for_commit(commit_id)
    return {
        "kind": "neg", "commit": commit_id, "repo": repo, "author_date": r[1] if r else None,
        "file_path": None, "s_line": None,
        "cwe_claim": {"cwe": [], "group": None, "category": None,
                      "claim": "commit không tạo lỗ hổng mới (verified-clean)"},
        "files": files,
        "file_urls": [enm.blob_url(repo, commit_id, f) for f in files] if repo else [],
        "code_lines": [], "diff_lines": [], "messages_anon": [],
    }


def _pending(store, sample_id: str, rater: str) -> list[dict]:
    done = {r["cluster_key"] for r in store.gold_review_rows(sample_id) if r["rater"] == rater}
    return [r for r in store.gold_sample_rows(sample_id) if r["cluster_key"] not in done]


def next_item(store, sample_id: str, rater: str) -> dict | None:
    """Mục kế tiếp CHƯA có verdict của rater này (pos trước neg), trả MÙ. None nếu hết.
    remaining = số mục còn chưa chấm của rater (tính cả mục đang trả)."""
    from . import config
    pend = _pending(store, sample_id, rater)
    if not pend:
        return None
    idx = None
    for s in pend:
        ck = s["cluster_key"]
        if s["kind"] == "neg":
            item = _item_neg(store, ck.split(":", 1)[1])
        else:
            if idx is None:
                idx = _index(store)
            row = idx.get(ck)
            if row is None:            # cụm biến mất sau relabel -> không thể chấm, bỏ qua
                continue
            item = _item_pos(store, row, config.LINE_WINDOW)
        item.update({"cluster_key": ck, "sample_id": sample_id, "stratum": s["stratum"],
                     "remaining": len(pend)})
        return item
    return None


# ---------------------------------------------------------------- 3. verdict
def verdict(store, sample_id: str, rater: str, cluster_key: str, verdict: str, note: str = "") -> dict:
    """Upsert verdict (TP|FP|unclear). cluster_key phải thuộc mẫu. Mọi rater (kể cả 'adjudicated') ghi đè được."""
    if verdict not in VERDICTS:
        raise ValueError(f"verdict phải là {VERDICTS}, nhận {verdict!r}")
    if not rater or not rater.strip():
        raise ValueError("rater trống")
    if cluster_key not in {r["cluster_key"] for r in store.gold_sample_rows(sample_id)}:
        raise ValueError(f"cluster_key {cluster_key} không thuộc mẫu {sample_id}")
    store.upsert_gold_review(sample_id, rater.strip(), cluster_key, verdict, note or None)
    return {"ok": True, "remaining": len(_pending(store, sample_id, rater.strip()))}


# ---------------------------------------------------------------- 4. close
def _prec(vs: list[str]) -> dict:
    c = Counter(vs)
    tp, fp, un = c.get("TP", 0), c.get("FP", 0), c.get("unclear", 0)
    point, lo, hi = wilson(tp, tp + fp)
    return {"tp": tp, "fp": fp, "unclear": un, "n": tp + fp, "n_reviewed": tp + fp + un,
            "point": None if point is None else round(point, 4),
            "ci_low": None if lo is None else round(lo, 4),
            "ci_high": None if hi is None else round(hi, 4), "ci": "wilson95"}


def close(store, sample_id: str, raters: list[str] | None = None) -> dict:
    """Tổng kết mẫu. precision theo rater 'adjudicated' (từng mục, nếu có) else rater đầu;
    Wilson 95 %; Cohen κ giữa 2 rater đầu (không tính 'adjudicated') trên mục cả hai đã chấm."""
    items = store.gold_sample_rows(sample_id)
    if not items:
        raise ValueError(f"mẫu {sample_id} không tồn tại / rỗng")
    reviews = store.gold_review_rows(sample_id)
    by_item: dict[str, dict[str, str]] = {}
    seen: list[str] = []
    for r in reviews:
        by_item.setdefault(r["cluster_key"], {})[r["rater"]] = r["verdict"]
        if r["rater"] not in seen:
            seen.append(r["rater"])
    human = [r for r in (raters or seen) if r != ADJUDICATED]
    primary = human[0] if human else None

    def _final(ck: str) -> str | None:
        v = by_item.get(ck, {})
        if ADJUDICATED in v:
            return v[ADJUDICATED]
        return v.get(primary) if primary else None

    finals = {it["cluster_key"]: _final(it["cluster_key"]) for it in items}
    pos = [it for it in items if it["kind"] == "pos"]
    neg = [it for it in items if it["kind"] == "neg"]
    pos_v = [finals[i["cluster_key"]] for i in pos if finals[i["cluster_key"]]]
    neg_v = [finals[i["cluster_key"]] for i in neg if finals[i["cluster_key"]]]

    by_stratum = []
    for s in sorted({it["stratum"] for it in items}):
        its = [it for it in items if it["stratum"] == s]
        vs = [finals[i["cluster_key"]] for i in its if finals[i["cluster_key"]]]
        by_stratum.append({"stratum": s, "kind": its[0]["kind"], "n_sample": len(its), **_prec(vs)})

    kappa = None
    disagreements = []
    if len(human) >= 2:
        a, b = human[0], human[1]
        pairs = []
        for it in items:
            v = by_item.get(it["cluster_key"], {})
            if a in v and b in v:
                pairs.append((v[a], v[b]))
                if v[a] != v[b]:
                    disagreements.append({"cluster_key": it["cluster_key"], "kind": it["kind"],
                                          "stratum": it["stratum"], "verdicts": dict(v)})
        k = cohen_kappa(pairs)
        kappa = {"value": None if k is None else round(k, 4), "n": len(pairs), "raters": [a, b]}

    n_adj = sum(1 for v in by_item.values() if ADJUDICATED in v)
    return {
        "sample_id": sample_id, "n_items": len(items), "n_pos": len(pos), "n_neg": len(neg),
        "raters": seen, "primary_rater": primary, "n_adjudicated": n_adj,
        "precision": _prec(pos_v),
        "neg_precision": _prec(neg_v),
        "kappa_raters": kappa,
        "disagreements": disagreements,
        "by_stratum": by_stratum,
        "unreviewed": sum(1 for v in finals.values() if v is None),
        "note": "TP = nhãn máy đúng; precision = TP/(TP+FP), unclear báo riêng; CI Wilson 95%.",
    }


def summary(store) -> list[dict]:
    """Tóm tắt mọi mẫu (cho README gold_set / stats): [{sample_id, seed, n_pos, n_neg, precision, neg_precision, kappa}]."""
    out = []
    for s in store.gold_sample_ids():
        try:
            c = close(store, s["sample_id"])
        except ValueError:
            continue
        out.append({**s, "precision": c["precision"], "neg_precision": c["neg_precision"],
                    "kappa_raters": c["kappa_raters"], "raters": c["raters"]})
    return out


# ---------------------------------------------------------------- CLI độc lập
def _open(db: str, readonly: bool):
    from .storage.sqlite_store import SQLiteStore
    return SQLiteStore(Path(db), readonly=readonly)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="orchestrator.review", description="Kiểm tay mù nhãn gold")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("sample", "next", "verdict", "close", "list"):
        sp = sub.add_parser(name)
        sp.add_argument("--db", required=True)
        sp.add_argument("--json", action="store_true")
        if name == "sample":
            sp.add_argument("--seed", type=int, required=True)
            sp.add_argument("--n-pos", type=int, default=200)
            sp.add_argument("--n-neg", type=int, default=100)
            sp.add_argument("--sample-id", default=None)
        if name in ("next", "verdict", "close"):
            sp.add_argument("--sample-id", required=True)
        if name in ("next", "verdict"):
            sp.add_argument("--rater", required=True)
        if name == "verdict":
            sp.add_argument("--cluster-key", required=True)
            sp.add_argument("--verdict", choices=VERDICTS, required=True)
            sp.add_argument("--note", default="")
        if name == "close":
            sp.add_argument("--raters", default=None, help="a,b (mặc định: theo thứ tự xuất hiện)")
    a = p.parse_args(argv)
    ro = a.cmd in ("next", "close", "list")
    store = _open(a.db, readonly=ro)
    try:
        if a.cmd == "sample":
            res = sample(store, a.seed, a.n_pos, a.n_neg, a.sample_id)
        elif a.cmd == "next":
            res = next_item(store, a.sample_id, a.rater) or {"done": True, "remaining": 0}
        elif a.cmd == "verdict":
            res = verdict(store, a.sample_id, a.rater, a.cluster_key, a.verdict, a.note)
        elif a.cmd == "close":
            res = close(store, a.sample_id, a.raters.split(",") if a.raters else None)
        else:
            res = {"samples": summary(store)}
    except ValueError as e:
        print(json.dumps({"error": {"code": "bad_request", "message": str(e)}}, ensure_ascii=False)
              if a.json else f"Lỗi: {e}", file=sys.stderr)
        return 1
    finally:
        store.close()
    if a.json or a.cmd in ("next", "close", "list"):
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    else:
        print(json.dumps(res, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
