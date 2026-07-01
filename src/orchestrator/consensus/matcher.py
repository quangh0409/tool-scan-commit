"""
Tầng ⑥ — gộp cụm + bỏ phiếu.

Gộp 2 finding vào CÙNG cụm nếu:
  - cùng file (đã chuẩn hoá path), VÀ
  - cùng NHÓM CWE (gộp anh-em, vd CWE-89/943 -> sql_injection), VÀ
  - |s_line_a - s_line_b| <= LINE_WINDOW.

Mỗi cụm -> 1 DatasetRow: đếm số tool đồng thuận, agreement_ratio, confidence,
silver_label. confidence = n_tools_agree / n_tools_ran (đơn giản cho skeleton;
Fleiss' kappa tính ở mức toàn-dataset trong bước sau).
"""
from __future__ import annotations

from pathlib import PurePosixPath

from .. import config
from ..schema import RawFinding, DatasetRow
from .cwe_groups import primary_group
from .tiers import tier_of, eligible_tools


def _label(E: int, C: int) -> str:
    """Thang nhãn cross-tier (RULE_GAN_NHAN.md §4). E=#đắt, C=#rẻ."""
    if E >= config.GOLD_MIN_EXPENSIVE:
        return "gold"
    if config.GOLD_ALLOW_1EXP_1CHEAP and E >= 1 and C >= 1:
        return "gold"
    if E >= 1 or C >= config.SILVER_MIN_CHEAP:
        return "silver"
    return "candidate"


def _norm_path(p: str) -> str:
    return str(PurePosixPath(p)).lstrip("/")


def _group(f: RawFinding) -> str:
    return primary_group(f.cwe)[0]


def _same_cluster(a: RawFinding, b: RawFinding, window: int) -> bool:
    if _norm_path(a.file_path) != _norm_path(b.file_path):
        return False
    if _group(a) != _group(b):           # gộp theo NHÓM CWE (không phải CWE thô)
        return False
    return abs(a.s_line - b.s_line) <= window


def cluster_findings(findings: list[RawFinding], window: int | None = None) -> list[list[RawFinding]]:
    window = config.LINE_WINDOW if window is None else window
    clusters: list[list[RawFinding]] = []
    for f in findings:
        for cl in clusters:
            if any(_same_cluster(f, g, window) for g in cl):
                cl.append(f)
                break
        else:
            clusters.append([f])
    return clusters


def vote(cluster: list[RawFinding], commit_meta: dict | None = None) -> DatasetRow:
    commit_meta = commit_meta or {}
    tools = sorted({f.tool for f in cluster})
    cwes = sorted({c for f in cluster for c in f.cwe})
    rep = cluster[0]  # đại diện
    grp, cat = primary_group(rep.cwe)
    # verified = True nếu BẤT KỲ tool nào trong cụm xác nhận (cho secret)
    vts = [f.verified for f in cluster if f.verified is not None]
    verified = (True in vts) if vts else None

    E = sum(1 for t in tools if tier_of(t) == "expensive")  # số tool ĐẮT
    C = len(tools) - E                                       # số tool RẺ
    eligible = len(eligible_tools(cat))                      # mẫu số theo NĂNG LỰC
    ratio = (len(tools) / eligible) if eligible else 0.0
    label = _label(E, C)
    tier = "mixed" if (E and C) else ("expensive" if E else "cheap")

    return DatasetRow(
        repo=rep.repo,
        commit_id=rep.commit_id,
        parent_commit=commit_meta.get("parent_commit"),
        commit_message=commit_meta.get("commit_message"),
        author_date=commit_meta.get("author_date"),
        file_path=_norm_path(rep.file_path),
        s_line=min(f.s_line for f in cluster),
        e_line=max((f.e_line or f.s_line) for f in cluster),
        s_detail_line=sorted({ln for f in cluster for ln in f.s_detail_line}),
        function=rep.function,
        tool="+".join(tools),
        rule_id=rep.rule_id,
        severity=rep.severity,
        cwe=cwes,
        cwe_group=grp,
        category=cat,
        owasp=rep.owasp,
        cve=None,
        verified=verified,
        lines_added=commit_meta.get("lines_added"),
        lines_deleted=commit_meta.get("lines_deleted"),
        code_snippet=rep.code_snippet,
        n_tools_ran=eligible,
        n_tools_agree=len(tools),
        agreeing_tools=tools,
        agreement_ratio=round(ratio, 3),
        confidence=round(ratio, 3),
        silver_label=label,          # alias legacy (giữ cột cũ đọc được)
        label=label,
        n_cheap=C, n_expensive=E, eligible=eligible, tier=tier,
    ).validate()


def consensus(findings: list[RawFinding], commit_meta: dict | None = None,
              window: int | None = None) -> list[DatasetRow]:
    return [vote(cl, commit_meta) for cl in cluster_findings(findings, window)]
