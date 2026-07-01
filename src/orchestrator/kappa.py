"""
Fleiss' kappa — đo mức các tool đồng thuận VƯỢT NGẪU NHIÊN (RULE_GAN_NHAN.md §7).

Item = 1 cụm `(file, nhóm-CWE, line±W)`. Rater = tool ĐỦ NĂNG LỰC & ĐÃ CHẠY trên commit đó
(secret item -> tool secret; code item -> tool code). Mỗi ô: tool CÓ báo (yes) / KHÔNG (no).

Đọc từ raw_findings (đã lọc nhiễu) + raw_output (biết tool nào ĐÃ CHẠY). Không quét lại.
Tính κ TỔNG + THEO nhóm-CWE (vì tool phủ rời -> per-nhóm mới đúng). κ là tín hiệu SỨC KHOẺ,
không phải con số tuyệt đối.
"""
from __future__ import annotations

from collections import defaultdict

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


def collect(store) -> tuple[list, dict, dict]:
    """-> (items tổng, items theo nhóm-CWE, items theo category)."""
    ran = defaultdict(set)
    for cid, tool in store.conn.execute("SELECT commit_id, tool FROM raw_output"):
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
            n_yes = len({f.tool for f in cluster} & elig)
            item = (n_yes, len(elig))
            allit.append(item)
            by_group[grp].append(item)
            by_cat[cat].append(item)
    return allit, by_group, by_cat


def _label(k: float | None) -> str:
    if k is None:
        return "(thiếu item ≥2 rater)"
    if k < 0:   return "cãi nhau (dưới ngẫu nhiên)"
    if k < 0.2: return "rất thấp"
    if k < 0.4: return "thấp"
    if k < 0.6: return "vừa"
    if k < 0.8: return "khá"
    return "cao"
