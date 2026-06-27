"""
Tầng ⑥ — gộp cụm + bỏ phiếu.

Gộp 2 finding vào CÙNG cụm nếu:
  - cùng file (đã chuẩn hoá path), VÀ
  - giao nhau ít nhất 1 CWE, VÀ
  - |s_line_a - s_line_b| <= LINE_WINDOW.

Mỗi cụm -> 1 DatasetRow: đếm số tool đồng thuận, agreement_ratio, confidence,
silver_label. confidence = n_tools_agree / n_tools_ran (đơn giản cho skeleton;
Fleiss' kappa tính ở mức toàn-dataset trong bước sau).
"""
from __future__ import annotations

from pathlib import PurePosixPath

from .. import config
from ..schema import RawFinding, DatasetRow


def _norm_path(p: str) -> str:
    return str(PurePosixPath(p)).lstrip("/")


def _same_cluster(a: RawFinding, b: RawFinding, window: int) -> bool:
    if _norm_path(a.file_path) != _norm_path(b.file_path):
        return False
    if not (set(a.cwe) & set(b.cwe)):
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


def vote(cluster: list[RawFinding], n_tools_ran: int,
         commit_meta: dict | None = None) -> DatasetRow:
    commit_meta = commit_meta or {}
    tools = sorted({f.tool for f in cluster})
    cwes = sorted({c for f in cluster for c in f.cwe})
    rep = cluster[0]  # đại diện
    n_agree = len(tools)
    ratio = (n_agree / n_tools_ran) if n_tools_ran else 0.0

    return DatasetRow(
        repo=rep.repo,
        commit_id=rep.commit_id,
        parent_commit=commit_meta.get("parent_commit"),
        commit_message=commit_meta.get("commit_message"),
        author_date=commit_meta.get("author_date"),
        file_path=_norm_path(rep.file_path),
        s_line=min(f.s_line for f in cluster),
        e_line=max((f.e_line or f.s_line) for f in cluster),
        function=rep.function,
        tool="+".join(tools),
        rule_id=rep.rule_id,
        severity=rep.severity,
        cwe=cwes,
        owasp=rep.owasp,
        cve=None,
        lines_added=commit_meta.get("lines_added"),
        lines_deleted=commit_meta.get("lines_deleted"),
        code_snippet=rep.code_snippet,
        n_tools_ran=n_tools_ran,
        n_tools_agree=n_agree,
        agreeing_tools=tools,
        agreement_ratio=round(ratio, 3),
        confidence=round(ratio, 3),
        silver_label="VULN" if n_agree >= 1 else "CLEAN",
    ).validate()


def consensus(findings: list[RawFinding], n_tools_ran: int,
              commit_meta: dict | None = None, window: int | None = None) -> list[DatasetRow]:
    return [vote(cl, n_tools_ran, commit_meta)
            for cl in cluster_findings(findings, window)]
