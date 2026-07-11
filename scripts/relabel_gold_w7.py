#!/usr/bin/env python3
"""Cập nhật positive_gold.jsonl sang LINE_WINDOW=7 mà KHÔNG đụng dataset gốc (W=3).

Relabel trên BẢN SAO DB tạm (nguồn giữ nguyên), chỉ lấy các cụm nhãn gold ở W=7,
ghi đè export_<repo>/gold_set/positive_gold.jsonl. negative_gold.jsonl KHÔNG đổi
(window chỉ ảnh hưởng positive). Cuối cùng dựng lại gold_set_all.

Chỉ xử lý repo APP có gold tăng khi nới window (mall-swarm/train-ticket/
spring-cloud-stream). giraph & spring-cloud-kubernetes: W=7 == W=3 -> giữ nguyên.
"""
import json, shutil, sys, tempfile, os
from pathlib import Path

BASE = Path("/home/scanner/tool-scan-commit")
sys.path.insert(0, str(BASE / "src"))
from orchestrator import config
config.LINE_WINDOW = 7                       # <<< áp W=7
from orchestrator.storage.sqlite_store import SQLiteStore
from orchestrator.consensus.labeler import relabel_commit
from orchestrator.export_dataset import _decode
from orchestrator import enumerate_commits as enm  # noqa

DATA = BASE / "data"
# export dir : (db file, clone dir, repo url)
TARGETS = {
    "export_mall-swarm": ("dataset_mall-swarm.sqlite", "mall-swarm",
                          "https://github.com/macrozheng/mall-swarm"),
    "export_train-ticket": ("dataset_train-ticket.sqlite", "train-ticket",
                            "https://github.com/FudanSELab/train-ticket"),
    "export": ("dataset_spring-cloud-stream.sqlite", "spring-cloud-stream",
               "https://github.com/spring-cloud/spring-cloud-stream"),
}


def relabel_gold(exp_name, db_file, clone_name, repo_url) -> int:
    src = DATA / db_file
    clone = BASE / "work" / clone_name
    tmp = Path(tempfile.mkdtemp(prefix="w7_")) / "copy.sqlite"
    shutil.copy(src, tmp)
    try:
        store = SQLiteStore(tmp)
        exp_cids = [r[0] for r in store.conn.execute(
            "SELECT DISTINCT commit_id FROM raw_findings WHERE tier='expensive'")]
        gold_rows = []
        for cid in exp_cids:
            relabel_commit(store, cid, clone, repo_url)   # ghi findings@W7 vào bản sao
            for r in store.findings_for_commit(cid):
                d = _decode(r)
                if d.get("label") == "gold":
                    gold_rows.append(d)
        store.close()
        out = DATA / exp_name / "gold_set" / "positive_gold.jsonl"
        out.write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n"
                               for r in gold_rows))
        return len(gold_rows)
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)


def rebuild_aggregate():
    """Gộp lại gold_set_all từ các file per-repo hiện tại (positive đã cập nhật W7)."""
    exports = sorted(p for p in DATA.glob("export*")
                     if p.is_dir() and (p / "gold_set").exists() and p.name != "export_skywalking")
    pos_all, neg_all, rows = [], [], []
    for exp in exports:
        gs = exp / "gold_set"
        p = (gs / "positive_gold.jsonl").read_text().strip()
        n = (gs / "negative_gold.jsonl").read_text().strip()
        np_ = len([l for l in p.splitlines() if l]) if p else 0
        nn = len([l for l in n.splitlines() if l]) if n else 0
        repo = ""
        if p:
            repo = json.loads(p.splitlines()[0]).get("repo", exp.name)
        elif n:
            repo = json.loads(n.splitlines()[0]).get("repo", exp.name)
        if p:
            pos_all.append(p)
        if n:
            neg_all.append(n)
        w = "W7" if exp.name in TARGETS else "W3=W7"
        rows.append(f"| {repo.split('/')[-1]} | {np_} | {nn} | {w} |")
    out = DATA / "gold_set_all"
    out.mkdir(exist_ok=True)
    (out / "positive_gold.jsonl").write_text("\n".join(pos_all) + ("\n" if pos_all else ""))
    (out / "negative_gold.jsonl").write_text("\n".join(neg_all) + ("\n" if neg_all else ""))
    n_pos = sum(len([l for l in x.splitlines() if l]) for x in pos_all)
    n_neg = sum(len([l for l in x.splitlines() if l]) for x in neg_all)
    (out / "README.md").write_text(f"""# gold_set_all — Tập nhãn tin cậy cao GỘP TOÀN DỰ ÁN (positive @ LINE_WINDOW=7)

> Gom `gold_set/` mọi repo đã scan xong. positive_gold gán nhãn ở **LINE_WINDOW=7**
> (nới từ mặc định 3 để vớt cặp FindSecBugs+Sonar cùng nhóm-CWE lệch dòng trong app
> Java; xem TOOL_OUTLINE.md). Mỗi dòng giữ trường `repo` để biết nguồn.

## Hai file
- **positive_gold.jsonl** — {n_pos} dòng, mỗi dòng 1 CỤM gold (E≥2, hoặc E=1&C≥1) ở W=7.
- **negative_gold.jsonl** — {n_neg} dòng, mỗi dòng 1 COMMIT verified-clean (window KHÔNG
  ảnh hưởng negative — giữ nguyên).

## Phân rã theo repo
| Repo | positive gold | negative gold | window |
|---|---:|---:|:--:|
{chr(10).join(rows)}
| **TỔNG** | **{n_pos}** | **{n_neg}** | |

## Vì sao W=7
±3 dòng quá chặt cho Java (thân method dài): FindSecBugs trỏ dòng khai báo, Sonar trỏ
dòng gọi — cùng lỗi nhưng lệch 5-10 dòng nên bị tách cụm. W=7 gộp chúng -> nhiều gold
2-tool-đắt hơn. Chỉ app Spring hưởng lợi (mall-swarm +85, train-ticket +24); library
(giraph/kubernetes) không đổi vì 2 tool đắt phủ CWE rời nhau. dataset.jsonl gốc VẪN ở
W=3 — chỉ gold_set dùng W=7.

## Giới hạn (đọc trước khi dùng)
1. Consensus ≠ chân lý (correlated errors). 2. Thiên lệch lớp lỗi (ưu ái lỗi tầng rẻ).
3. Tầng đắt chỉ phủ commit build được. 4. W=7 gộp rộng hơn -> cần kiểm precision tay
   với gold mới (nguy cơ gộp 2 lỗi khác method cùng nhóm-CWE). 5. κ (Fleiss) thường âm.
""")
    print(f"[AGG] gold_set_all @W7: positive={n_pos} negative={n_neg}")


def main():
    print("Relabel gold @ LINE_WINDOW=7 (bản sao DB tạm, nguồn giữ nguyên):")
    for exp, (db, clone, url) in TARGETS.items():
        n = relabel_gold(exp, db, clone, url)
        print(f"  [OK] {exp:22} -> positive_gold @W7 = {n}")
    rebuild_aggregate()


if __name__ == "__main__":
    main()
