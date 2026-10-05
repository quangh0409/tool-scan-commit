"""
Fleiss' kappa — đo mức các tool đồng thuận VƯỢT NGẪU NHIÊN (RULE_GAN_NHAN.md §7).

Item = 1 cụm `(file, nhóm-CWE, line±W)`. Rater = tool ĐỦ NĂNG LỰC & ĐÃ CHẠY trên commit đó
(secret item -> tool secret; code item -> tool code). Mỗi ô: tool CÓ báo (yes) / KHÔNG (no).

Đọc từ raw_findings (đã lọc nhiễu) + raw_output (biết tool nào ĐÃ CHẠY). Không quét lại.
Tính κ TỔNG + THEO nhóm-CWE (vì tool phủ rời -> per-nhóm mới đúng). κ là tín hiệu SỨC KHOẺ,
không phải con số tuyệt đối.
"""
from __future__ import annotations

import datetime
from collections import defaultdict
from itertools import combinations

from .consensus.cwe_groups import primary_group
from .consensus.matcher import cluster_findings
from .consensus.labeler import _is_noise
from .consensus.tiers import eligible_tools


def fleiss(items: list[tuple[int, int]]) -> tuple[float | None, int]:
    """items = list (n_yes, n_rater). Trả (kappa, số item hợp lệ). Binary yes/no."""
    items = [(y, n) for y, n in items if n >= 2]
    if not items:
        return None, 0
    n_item = len(items)
    tot_yes = tot = 0
    p_sum = 0.0
    for y, n in items:
        no = n - y
        p_sum += (y * (y - 1) + no * (no - 1)) / (n * (n - 1))   # agreement item i
        tot_yes += y
        tot += n
    p_bar = p_sum / n_item
    p_yes = tot_yes / tot
    p_e = p_yes ** 2 + (1 - p_yes) ** 2                          # agreement kỳ vọng ngẫu nhiên
    if p_e >= 1.0:
        return 1.0, n_item
    return (p_bar - p_e) / (1 - p_e), n_item


def collect(store, pairs: dict | None = None) -> tuple[list, dict, dict]:
    """-> (items tổng, items theo nhóm-CWE, items theo category).

    pairs (tuỳ chọn, dict rỗng truyền vào): được điền items theo CẶP tool 'a|b' (2 rater:
    cả hai đủ năng lực & đã chạy trên commit; n_yes = số tool trong cặp báo cụm)."""
    ran = defaultdict(set)
    # fmt='error' = tool KHÔNG chạy được (timeout/infra/crash) -> không phải rater "không báo" (A1, CONTRACTS §1)
    for cid, tool in store.conn.execute(
            "SELECT commit_id, tool FROM raw_output WHERE COALESCE(fmt,'') != 'error'"):
        ran[cid].add(tool)

    allit: list = []
    by_group: dict = defaultdict(list)
    by_cat: dict = defaultdict(list)
    commits = [r[0] for r in store.conn.execute("SELECT DISTINCT commit_id FROM raw_findings")]
    for cid in commits:
        raws = [f for f in store.raw_for_commit(cid) if not _is_noise(f)]
        if not raws:
            continue
        toolran = ran.get(cid, set())
        for cluster in cluster_findings(raws):
            grp, cat = primary_group(cluster[0].cwe)
            elig = eligible_tools(cat) & toolran
            if len(elig) < 2:               # cần ≥2 rater mới tính được agreement
                continue
            said = {f.tool for f in cluster} & elig
            item = (len(said), len(elig))
            allit.append(item)
            by_group[grp].append(item)
            by_cat[cat].append(item)
            if pairs is not None:
                for a, b in combinations(sorted(elig), 2):
                    pairs.setdefault(f"{a}|{b}", []).append((len({a, b} & said), 2))
    return allit, by_group, by_cat


def compute_all(store, min_group_n: int = 5) -> dict:
    """κ tổng + theo category + theo nhóm-CWE (n>=min_group_n) + theo cặp tool.
    Cấu trúc khớp CONTRACTS §9 overview.kappa: {total, by_category[], by_group[], pairs[], n}."""
    pairs: dict = {}
    allit, by_group, by_cat = collect(store, pairs)
    k, n = fleiss(allit)

    def _rows(d, min_n=2):
        out = []
        for grp, items in d.items():
            kg, ng = fleiss(items)
            if ng >= min_n:
                out.append({"group": grp, "value": None if kg is None else round(kg, 4), "n": ng})
        return sorted(out, key=lambda r: (-r["n"], r["group"]))

    return {"total": None if k is None else round(k, 4), "n": n,
            "by_category": _rows(by_cat),
            "by_group": _rows(by_group, min_group_n),
            "pairs": _rows(pairs)}


def save_all(store, result: dict, run_id: str) -> int:
    """Ghi κ vào bảng `kappa` qua store.save_kappa(run_id, scope, grp, value, n) (A1).
    Store chưa có hàm đó -> ghi thẳng nếu bảng tồn tại; không có bảng -> 0 (chỉ print)."""
    rows = [("total", "", result.get("total"), result.get("n", 0))]
    for scope, key in (("category", "by_category"), ("cwe_group", "by_group"), ("pair", "pairs")):
        rows += [(scope, r["group"], r["value"], r["n"]) for r in result.get(key, [])]
    save = getattr(store, "save_kappa", None)
    if save is not None:
        for scope, grp, value, n in rows:
            save(run_id, scope, grp, value, n)
        return len(rows)
    conn = getattr(store, "conn", None)
    if conn is None:
        return 0
    have = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='kappa'").fetchone()
    if not have:
        return 0
    now = datetime.datetime.now().isoformat(timespec="seconds")
    conn.execute("DELETE FROM kappa WHERE run_id=?", [run_id])
    conn.executemany("INSERT INTO kappa (run_id,scope,grp,value,n,computed_at) VALUES (?,?,?,?,?,?)",
                     [(run_id, sc, g, v, n, now) for sc, g, v, n in rows])
    conn.commit()
    return len(rows)


def _label(k: float | None) -> str:
    if k is None:
        return "(thiếu item ≥2 rater)"
    if k < 0:   return "cãi nhau (dưới ngẫu nhiên)"
    if k < 0.2: return "rất thấp"
    if k < 0.4: return "thấp"
    if k < 0.6: return "vừa"
    if k < 0.8: return "khá"
    return "cao"
