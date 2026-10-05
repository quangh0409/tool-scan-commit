#!/usr/bin/env python3
"""Tạo thư mục gold_set/ trong mỗi export + gold_set_all gộp. Stdlib-only, không hardcode đường dẫn.

Mỗi gold_set/ gồm:
  - positive_gold.jsonl : các CỤM finding nhãn gold (từ dataset.jsonl)
  - negative_gold.jsonl : các COMMIT verified-clean (từ commits.jsonl; n_expensive_ok >= 2)
  - README.md           : context + số liệu + KẾT QUẢ KIỂM TAY (bảng gold_review: precision, n, CI Wilson)

Dùng:
  PYTHONPATH=src python scripts/build_gold_set.py --export <dir> --db <db.sqlite>        # 1 export
  PYTHONPATH=src python scripts/build_gold_set.py --data <DATA_DIR> [--skip export_x] [--out <agg_dir>]
    (quét DATA_DIR/export*; DB lấy từ run_manifest.json["db"] hoặc DATA_DIR/dataset_<tên>.sqlite)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

README_TMPL = """# gold_set — Tập nhãn tin cậy cao (repo: `{repo}`)

> File này để một AI/Claude khác đọc và **nắm ngay context của dataset** mà không cần
> mở toàn bộ pipeline. Chi tiết đầy đủ: xem `TOOL_OUTLINE.md` ở gốc dự án.

## 1. Dataset này là gì
Pipeline nhận 1 link GitHub → duyệt từng commit lịch sử → chạy nhiều tool SAST (rẻ:
gitleaks/trufflehog/semgrep/bearer/horusec; đắt: FindSecBugs/SonarQube, cần build) →
chuẩn hoá về finding `(file, dòng, CWE, tool)` → gom **cụm** theo `(file, nhóm-CWE,
dòng ±3)` → **bỏ phiếu theo tầng** → xuất dataset có nhãn tin cậy. Nhãn = **CWE-class**,
KHÔNG phải CVE (cột `cve` gần như luôn null — SAST không sinh CVE).

## 2. Hai file trong thư mục này
### `positive_gold.jsonl` — {n_pos} dòng (mỗi dòng = 1 CỤM finding nhãn `gold`)
GOLD = tín hiệu dương mạnh nhất, đạt MỘT trong hai:
- **≥2 tool ĐẮT** độc lập cùng chỉ 1 cụm (`tier=expensive`), hoặc
- **1 tool đắt + ≥1 tool rẻ** độc lập (`tier=mixed`).

Trường quan trọng:
- `label` = "gold" (mọi dòng ở đây); `cluster_key` = khoá ổn định của cụm (dùng cho kiểm tay/compare).
- `evidence.consensus` = gold (máy); `evidence.validation` = unreviewed | TP | FP | unclear (người chấm mù).
- `file_path`, `s_line`/`e_line`, `s_detail_line[]` — vị trí lỗi.
- `cwe[]`, `cwe_group`, `category` — loại lỗi (mã CWE thô, nhóm đồng thuận, miền).
- `agreeing_tools[]`, `n_expensive`, `n_cheap`, `tier` — BẰNG CHỨNG: tool nào xác nhận.
- `finding_in_diff` — **1 = commit này TẠO lỗi**; **0 = nợ cũ**. Trục này TRỰC GIAO với nhãn.
- `diff_parsed`, `code_before_url`/`code_after_url` — diff đã parse + permalink GitHub.
- `kamei{{14}}` — 14 đặc trưng JIT (Kamei 2013) của commit chứa cụm.

### `negative_gold.jsonl` — {n_neg} dòng (mỗi dòng = 1 COMMIT verified-clean)
VERIFIED-CLEAN = mẫu ÂM chất lượng cao: commit sạch ở tầng rẻ **VÀ** đã qua tầng đắt với
**≥2 tool đắt chạy xong (`n_expensive_ok >= 2`)** mà vẫn không tạo lỗi mới. Commit chỉ đụng
file không-Java (`skipped`) hoặc chỉ 1 tool đắt ok KHÔNG được tính (chỉ là cheap-clean).

Trường: `commit_id`, `repo`, `author`, `author_date`, `kamei{{14}}`, `labels`, `role`="clean",
`n_expensive_ok`, `negative_level`="verified-clean".

## 3. Thang nhãn đầy đủ
E=#tool đắt, C=#tool rẻ đồng thuận trong cụm:
| E | C | nhãn |
|---|---|---|
| ≥2 | bất kỳ | **gold** |
| 1 | ≥1 | **gold** |
| 1 | 0 | silver |
| 0 | ≥2 | silver |
| 0 | 1 | candidate |

## 4. Số liệu repo `{repo}`
- positive gold (cụm): **{n_pos}**  |  trong đó `finding_in_diff=1`: {n_pos_indiff}
- negative gold (commit verified-clean): **{n_neg}**
- phân bố nhóm-CWE của gold: {cwe_dist}
- tổng cụm trong dataset.jsonl: {n_total_clusters} | tổng commit trong commits.jsonl: {n_total_commits}

## 5. Kiểm tay mù (bảng `gold_review`) — precision thật của nhãn máy
{review_section}

## 6. GIỚI HẠN — đọc trước khi dùng
1. **Consensus ≠ chân lý.** Tool có thể sai giống nhau. Gold = "nhiều nguồn độc lập nhất có thể";
   precision thật chỉ biết qua §5 (kiểm tay mù), không tự suy từ số tool đồng thuận.
2. **Thiên lệch lớp lỗi.** Phễu ưu ái lỗi tầng rẻ bắt tốt (secret/SQLi/XSS/misconfig/crypto/csrf).
3. **Tầng đắt chỉ phủ commit build được.**
4. **κ (Fleiss) thường ÂM** giữa các tool = phủ RỜI NHAU → gold quý & hiếm; silver/candidate = nhãn yếu.
5. Ngưỡng (cửa sổ ±3 dòng, điều kiện gold) là **lựa chọn thiết kế** — xem `sensitivity`.

## 7. Nguồn đầy đủ
`../dataset.jsonl`, `../commits.jsonl`, `../run_manifest.json`, `../<commit_sha>/` (audit raw từng tool).
"""

AGG_README = """# gold_set_all — Tập nhãn tin cậy cao GỘP TOÀN DỰ ÁN

> Gom `gold_set/` của MỌI export được xử lý. Mỗi dòng giữ trường `repo` để biết nguồn.

## Hai file
- **`positive_gold.jsonl`** — {n_pos} dòng, mỗi dòng 1 CỤM finding nhãn `gold`.
- **`negative_gold.jsonl`** — {n_neg} dòng, mỗi dòng 1 COMMIT verified-clean (`n_expensive_ok >= 2`).

## Phân rã theo repo
| Repo | positive gold | negative gold | kiểm tay (precision, n, CI95) |
|---|---:|---:|---|
{table}
| **TỔNG** | **{n_pos}** | **{n_neg}** | |

## Ý nghĩa nhãn (tóm tắt)
gold = (E≥2) hoặc (E=1 và C≥1); silver = (E=1) hoặc (C≥2); candidate = (C=1).
verified-clean = commit clean qua tầng đắt với ≥2 tool đắt ok, không tạo lỗi mới.

## GIỚI HẠN
1. Consensus ≠ chân lý — precision thật xem cột kiểm tay (gold_review). 2. Thiên lệch lớp lỗi.
3. Tầng đắt chỉ phủ commit build được. 4. κ (Fleiss) giữa tool thường âm → gold hiếm.
{skip_note}
"""


def _fmt_prec(p: dict | None) -> str:
    if not p or p.get("point") is None:
        return "chưa có"
    return f"{p['point']:.3f} (n={p['n']}, CI95 {p['ci_low']:.3f}–{p['ci_high']:.3f}, unclear={p['unclear']})"


def review_summary(db_path: Path | None) -> tuple[list[dict], str]:
    """Đọc gold_review qua orchestrator.review.summary (DB readonly). -> (samples, đoạn markdown)."""
    if not db_path or not Path(db_path).exists():
        return [], "_Không tìm thấy DB → không đọc được gold_review._"
    from orchestrator import review
    from orchestrator.storage.sqlite_store import SQLiteStore
    store = SQLiteStore(Path(db_path), readonly=True)
    try:
        samples = review.summary(store)
    finally:
        store.close()
    if not samples:
        return [], ("_Chưa kiểm tay._ Tạo mẫu: `python -m orchestrator.review sample --db <db> --seed 1 "
                    "--n-pos 200 --n-neg 100`, chấm mù qua GUI/`review next|verdict`, rồi `review close`.")
    lines = ["| sample | seed | pos/neg | precision gold (TP/(TP+FP)) | verified-clean thật sạch | Cohen κ (2 rater) |",
             "|---|---:|---|---|---|---|"]
    for s in samples:
        k = s.get("kappa_raters") or {}
        kv = f"{k['value']:.3f} (n={k['n']}, {'/'.join(k['raters'])})" if k.get("value") is not None else "—"
        lines.append(f"| {s['sample_id']} | {s['seed']} | {s['n_pos']}/{s['n_neg']} | "
                     f"{_fmt_prec(s['precision'])} | {_fmt_prec(s['neg_precision'])} | {kv} |")
    lines.append("")
    lines.append("TP = nhãn máy đúng; precision = TP/(TP+FP), `unclear` báo riêng; CI = Wilson score 95 % "
                 "(Brown, Cai & DasGupta 2001). Rater `adjudicated` (sau hoà giải) được ưu tiên.")
    return samples, "\n".join(lines)


def _db_for_export(exp: Path, data: Path | None) -> Path | None:
    man = exp / "run_manifest.json"
    if man.exists():
        try:
            d = json.loads(man.read_text(encoding="utf-8")).get("db")
            if d and Path(d).exists():
                return Path(d)
        except (OSError, ValueError):
            pass
    if data:
        name = exp.name.removeprefix("export_") if exp.name != "export" else "spring-cloud-stream"
        cand = data / f"dataset_{name}.sqlite"
        if cand.exists():
            return cand
    return None


def _read_jsonl(path: Path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield line


def build_one(exp: Path, db: Path | None = None) -> dict:
    ds, cm = exp / "dataset.jsonl", exp / "commits.jsonl"
    if not ds.exists() or not cm.exists():
        return {"skip": "thiếu dataset/commits.jsonl (chạy `export` hoặc scripts/merge_export.py)"}
    out = exp / "gold_set"
    out.mkdir(exist_ok=True)

    pos, cwe_dist, n_indiff, n_clusters, repo = [], {}, 0, 0, ""
    for line in _read_jsonl(ds):
        n_clusters += 1
        j = json.loads(line)
        repo = j.get("repo") or repo
        if j.get("label") == "gold":
            pos.append(line)
            g = j.get("cwe_group") or "?"
            cwe_dist[g] = cwe_dist.get(g, 0) + 1
            if j.get("finding_in_diff") in (1, True):
                n_indiff += 1
    with open(out / "positive_gold.jsonl", "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(pos) + ("\n" if pos else ""))

    neg, n_commits = [], 0
    for line in _read_jsonl(cm):
        n_commits += 1
        j = json.loads(line)
        if j.get("negative_level") == "verified-clean" and (j.get("n_expensive_ok") is None
                                                            or j.get("n_expensive_ok", 0) >= 2):
            neg.append(line)
    with open(out / "negative_gold.jsonl", "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(neg) + ("\n" if neg else ""))

    samples, review_md = review_summary(db)
    cwe_str = ", ".join(f"{k}={v}" for k, v in sorted(cwe_dist.items(), key=lambda x: -x[1])) or "(không có)"
    with open(out / "README.md", "w", encoding="utf-8", newline="\n") as f:
        f.write(README_TMPL.format(
            repo=repo or exp.name, n_pos=len(pos), n_neg=len(neg), n_pos_indiff=n_indiff,
            cwe_dist=cwe_str, n_total_clusters=n_clusters, n_total_commits=n_commits,
            review_section=review_md))
    with open(out / "gold_review_summary.json", "w", encoding="utf-8") as f:
        json.dump({"db": str(db) if db else None, "samples": samples}, f, ensure_ascii=False, indent=2, default=str)
    return {"repo": repo or exp.name, "pos": len(pos), "neg": len(neg), "out": str(out),
            "db": str(db) if db else None,
            "review": _fmt_prec(samples[-1]["precision"]) if samples else "chưa kiểm tay"}


def build_aggregate(results: list[dict], out: Path, skipped: list[str]) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    pos_all, neg_all, rows = [], [], []
    for r in results:
        gs = Path(r["out"])
        p = (gs / "positive_gold.jsonl").read_text(encoding="utf-8").strip()
        n = (gs / "negative_gold.jsonl").read_text(encoding="utf-8").strip()
        if p:
            pos_all.append(p)
        if n:
            neg_all.append(n)
        rows.append(f"| {r['repo'].rstrip('/').split('/')[-1]} | {r['pos']} | {r['neg']} | {r['review']} |")
    with open(out / "positive_gold.jsonl", "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(pos_all) + ("\n" if pos_all else ""))
    with open(out / "negative_gold.jsonl", "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(neg_all) + ("\n" if neg_all else ""))
    n_pos, n_neg = sum(r["pos"] for r in results), sum(r["neg"] for r in results)
    with open(out / "README.md", "w", encoding="utf-8", newline="\n") as f:
        f.write(AGG_README.format(n_pos=n_pos, n_neg=n_neg, table="\n".join(rows),
                                  skip_note=(f"Bỏ qua: {', '.join(skipped)}." if skipped else "")))
    return {"out": str(out), "pos": n_pos, "neg": n_neg}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", default=os.environ.get("ORCH_DATA_DIR"),
                   help="thư mục chứa export*/ và dataset_*.sqlite (mặc định $ORCH_DATA_DIR)")
    p.add_argument("--export", action="append", default=[], help="thư mục export cụ thể (lặp được)")
    p.add_argument("--db", action="append", default=[], help="DB tương ứng từng --export (cùng thứ tự)")
    p.add_argument("--skip", action="append", default=[], help="tên export bỏ qua (vd đang scan)")
    p.add_argument("--out", default=None, help="thư mục gold_set_all (mặc định <data>/gold_set_all)")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)

    data = Path(a.data) if a.data else None
    if a.export:
        exports = [Path(e) for e in a.export]
        dbs = [Path(d) for d in a.db] + [None] * (len(exports) - len(a.db))
    elif data:
        exports = sorted(x for x in data.glob("export*") if x.is_dir() and x.name not in a.skip)
        dbs = [None] * len(exports)
    else:
        p.error("cần --export <dir> [--db <db>] hoặc --data <DATA_DIR>")
        return 1
    results, report = [], []
    for exp, db in zip(exports, dbs):
        db = db or _db_for_export(exp, data)
        r = build_one(exp, db)
        if r.get("skip"):
            report.append({"export": str(exp), "skip": r["skip"]})
            if not a.json:
                print(f"  [BỎ] {exp.name}: {r['skip']}")
        else:
            results.append(r)
            report.append({"export": str(exp), **r})
            if not a.json:
                print(f"  [OK] {exp.name:34} gold+={r['pos']:4} neg={r['neg']:5} kiểm tay: {r['review']}")
    agg = None
    if results:
        out = Path(a.out) if a.out else (data / "gold_set_all" if data else exports[0].parent / "gold_set_all")
        agg = build_aggregate(results, out, a.skip)
        if not a.json:
            print(f"\n[AGG] gold_set_all: positive={agg['pos']} negative={agg['neg']} -> {agg['out']}")
    if a.json:
        print(json.dumps({"exports": report, "aggregate": agg}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
