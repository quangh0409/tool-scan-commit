#!/usr/bin/env python3
"""Tạo thư mục gold_set/ trong mỗi export repo (trừ repo đang scan).

Mỗi gold_set/ gồm:
  - positive_gold.jsonl : các CỤM finding nhãn gold (từ dataset.jsonl)
  - negative_gold.jsonl : các COMMIT verified-clean (từ commits.jsonl)
  - README.md           : mô tả context cho AI khác đọc hiểu dataset

Chạy: python3 scripts/build_gold_set.py
"""
import json
import sys
from pathlib import Path

DATA = Path("/home/scanner/tool-scan-commit/data")
SKIP = {"export_skywalking"}   # repo đang scan -> bỏ qua

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
- `label` = "gold" (mọi dòng ở đây).
- `file_path`, `s_line`/`e_line`, `s_detail_line[]` — vị trí lỗi.
- `cwe[]`, `cwe_group`, `category` — loại lỗi (mã CWE thô, nhóm đồng thuận, miền).
- `agreeing_tools[]`, `n_expensive`, `n_cheap`, `tier` — BẰNG CHỨNG: tool nào xác nhận.
- `finding_in_diff` — **1 = commit này TẠO lỗi** (nằm trên dòng vừa thêm); **0 = nợ cũ**
  (tool đắt quét cả file nên phơi lỗi có sẵn). Trục này TRỰC GIAO với nhãn.
- `diff_parsed`, `code_before_url`/`code_after_url` — diff đã parse + permalink GitHub.
- `kamei{{14}}` — 14 đặc trưng JIT (Kamei 2013) của commit chứa cụm.

### `negative_gold.jsonl` — {n_neg} dòng (mỗi dòng = 1 COMMIT verified-clean)
VERIFIED-CLEAN = mẫu ÂM chất lượng cao: commit sạch ở tầng rẻ **VÀ** đã qua tầng đắt
(build + FindSecBugs + Sonar) mà **vẫn sạch** (xét theo `finding_in_diff` — commit không
tạo lỗi mới). Mạnh hơn "cheap-clean" (chỉ tầng rẻ xác nhận).

Trường: `commit_id`, `repo`, `author`, `author_date`, `kamei{{14}}`,
`labels` (đếm gold/silver/candidate của commit), `role`="clean",
`negative_level`="verified-clean".

## 3. Thang nhãn đầy đủ (để hiểu vì sao gold hiếm)
Gọi E=#tool đắt đồng thuận, C=#tool rẻ đồng thuận trong cụm:
| E | C | nhãn |
|---|---|---|
| ≥2 | bất kỳ | **gold** |
| 1 | ≥1 | **gold** |
| 1 | 0 | silver |
| 0 | ≥2 | silver |
| 0 | 1 | candidate |

## 4. Số liệu repo `{repo}`
- positive gold (cụm): **{n_pos}**  |  trong đó `finding_in_diff=1` (commit tạo lỗi): {n_pos_indiff}
- negative gold (commit verified-clean): **{n_neg}**
- phân bố nhóm-CWE của gold: {cwe_dist}
- tổng cụm trong dataset.jsonl: {n_total_clusters} | tổng commit trong commits.jsonl: {n_total_commits}

## 5. GIỚI HẠN — đọc trước khi dùng
1. **Consensus ≠ chân lý.** Tool có thể sai giống nhau (correlated errors). Gold = "nhiều
   nguồn độc lập nhất có thể", KHÔNG phải "đã chứng minh có lỗ hổng".
2. **Thiên lệch lớp lỗi.** Phễu ưu ái lỗi tầng rẻ bắt tốt (secret/SQLi/XSS/misconfig/crypto/
   csrf); lỗi sâu (race, logic flaw) gần như vắng.
3. **Tầng đắt chỉ phủ commit build được** — phần lịch sử không build được chỉ có nhãn rẻ.
4. **κ (Fleiss' kappa) thường ÂM** giữa các tool = chúng phủ RỜI NHAU → gold quý & hiếm;
   silver/candidate nên xử như nhãn yếu (weak supervision).
5. Ngưỡng (cửa sổ ±3 dòng, điều kiện gold) là **lựa chọn thiết kế**, chỉnh được; raw được
   lưu để tái tính.

## 6. Muốn dữ liệu đầy đủ hơn
- `../dataset.jsonl` — mọi cụm (gold + silver + candidate).
- `../commits.jsonl` — mọi commit (đủ cả 0-finding, cho JIT mức commit).
- `../<commit_sha>/` — thư mục audit: raw từng tool + label + summary.
- Gốc dự án: `TOOL_OUTLINE.md` (toàn cảnh), `RULE_GAN_NHAN.md` (quy tắc nhãn).
"""


def build_one(exp: Path) -> dict:
    ds = exp / "dataset.jsonl"
    cm = exp / "commits.jsonl"
    if not ds.exists() or not cm.exists():
        return {"skip": f"thiếu dataset/commits.jsonl"}

    out = exp / "gold_set"
    out.mkdir(exist_ok=True)

    # positive gold từ dataset.jsonl
    pos, cwe_dist, n_indiff, n_clusters = [], {}, 0, 0
    repo = ""
    for line in ds.open():
        line = line.strip()
        if not line:
            continue
        n_clusters += 1
        j = json.loads(line)
        repo = j.get("repo") or repo
        if j.get("label") == "gold":
            pos.append(line)
            g = j.get("cwe_group") or "?"
            cwe_dist[g] = cwe_dist.get(g, 0) + 1
            if j.get("finding_in_diff") in (1, True):
                n_indiff += 1
    (out / "positive_gold.jsonl").write_text("\n".join(pos) + ("\n" if pos else ""))

    # negative gold (verified-clean) từ commits.jsonl
    neg, n_commits = [], 0
    for line in cm.open():
        line = line.strip()
        if not line:
            continue
        n_commits += 1
        j = json.loads(line)
        if j.get("negative_level") == "verified-clean":
            neg.append(line)
    (out / "negative_gold.jsonl").write_text("\n".join(neg) + ("\n" if neg else ""))

    cwe_str = ", ".join(f"{k}={v}" for k, v in sorted(cwe_dist.items(), key=lambda x: -x[1])) or "(không có)"
    (out / "README.md").write_text(README_TMPL.format(
        repo=repo or exp.name, n_pos=len(pos), n_neg=len(neg),
        n_pos_indiff=n_indiff, cwe_dist=cwe_str,
        n_total_clusters=n_clusters, n_total_commits=n_commits))
    return {"repo": repo, "pos": len(pos), "neg": len(neg), "out": str(out)}


AGG_README = """# gold_set_all — Tập nhãn tin cậy cao GỘP TOÀN DỰ ÁN

> Gom `gold_set/` của MỌI repo đã scan xong vào một chỗ. Mỗi dòng vẫn giữ trường
> `repo` nên biết được nguồn. Context chi tiết: xem `README.md` trong từng
> `data/export_*/gold_set/` hoặc `TOOL_OUTLINE.md` ở gốc dự án.

## Hai file
- **`positive_gold.jsonl`** — {n_pos} dòng, mỗi dòng 1 CỤM finding nhãn `gold`
  (≥2 tool đắt, hoặc 1 đắt + ≥1 rẻ đồng thuận). Gộp từ tất cả repo.
- **`negative_gold.jsonl`** — {n_neg} dòng, mỗi dòng 1 COMMIT verified-clean
  (sạch cả tầng rẻ lẫn tầng đắt). Gộp từ tất cả repo.

## Phân rã theo repo
| Repo | positive gold | negative gold (verified-clean) |
|---|---:|---:|
{table}
| **TỔNG** | **{n_pos}** | **{n_neg}** |

## Ý nghĩa nhãn (tóm tắt)
E=#tool đắt, C=#tool rẻ đồng thuận trong 1 cụm:
gold = (E≥2) hoặc (E=1 và C≥1); silver = (E=1) hoặc (C≥2); candidate = (C=1).
verified-clean = commit clean qua CẢ tầng đắt (build+FindSecBugs+Sonar) vẫn sạch.

## Trường quan trọng của positive_gold
`repo, commit_id, file_path, s_line, cwe[], cwe_group, category, label=gold,
agreeing_tools[], n_expensive, n_cheap, tier, finding_in_diff (1=commit tạo lỗi,
0=nợ cũ), diff_parsed, code_before_url/code_after_url, kamei{{14 đặc trưng JIT}}`.

## Trường của negative_gold
`repo, commit_id, author, author_date, kamei{{14}}, labels, role=clean,
negative_level=verified-clean`.

## GIỚI HẠN (bắt buộc đọc)
1. Consensus ≠ chân lý — tool có thể sai giống nhau; gold = "nhiều nguồn độc lập nhất".
2. Thiên lệch lớp lỗi — phễu ưu ái lỗi tầng rẻ bắt tốt (secret/SQLi/XSS/csrf/crypto).
3. Tầng đắt chỉ phủ commit build được.
4. κ (Fleiss) thường ÂM = tool phủ RỜI NHAU → gold quý & hiếm; silver/candidate = nhãn yếu.

## Nguồn đầy đủ
Mỗi repo: `data/export_<repo>/dataset.jsonl` (mọi cụm), `commits.jsonl` (mọi commit),
`<sha>/` (audit raw từng tool). Repo đang scan ({skip}) chưa có mặt ở đây.
"""


def build_aggregate(results: list) -> None:
    out = DATA / "gold_set_all"
    out.mkdir(exist_ok=True)
    pos_all, neg_all, rows = [], [], []
    for r in results:
        exp = Path(r["out"])   # .../export_x/gold_set
        p = (exp / "positive_gold.jsonl").read_text().strip()
        n = (exp / "negative_gold.jsonl").read_text().strip()
        if p:
            pos_all.append(p)
        if n:
            neg_all.append(n)
        rows.append(f"| {r['repo'].split('/')[-1]} | {r['pos']} | {r['neg']} |")
    (out / "positive_gold.jsonl").write_text("\n".join(pos_all) + ("\n" if pos_all else ""))
    (out / "negative_gold.jsonl").write_text("\n".join(neg_all) + ("\n" if neg_all else ""))
    n_pos = sum(r["pos"] for r in results)
    n_neg = sum(r["neg"] for r in results)
    (out / "README.md").write_text(AGG_README.format(
        n_pos=n_pos, n_neg=n_neg, table="\n".join(rows), skip=", ".join(sorted(SKIP))))
    print(f"\n[AGG] gold_set_all: positive={n_pos} negative={n_neg} -> {out}")


def main():
    exports = sorted(p for p in DATA.glob("export*") if p.is_dir() and p.name not in SKIP)
    print(f"Xử lý {len(exports)} export (bỏ {SKIP}):")
    results = []
    for exp in exports:
        r = build_one(exp)
        if r.get("skip"):
            print(f"  [BỎ] {exp.name}: {r['skip']}")
        else:
            results.append(r)
            print(f"  [OK] {exp.name:34} repo={r['repo']:45} gold+={r['pos']:4} neg={r['neg']:5}")
    build_aggregate(results)


if __name__ == "__main__":
    main()
