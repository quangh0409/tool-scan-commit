"""scripts/results_report.py trên 2 export giả: A = fixture export_smoke; B = bản copy đổi 1 nhãn + 1 digest."""
from __future__ import annotations

import hashlib
import importlib
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXPORT_SRC = ROOT / "tests" / "fixtures" / "export_smoke"


@pytest.fixture
def rr():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        return importlib.reload(importlib.import_module("results_report"))
    finally:
        sys.path.pop(0)


def _resum(d: Path) -> None:
    lines = [f"{hashlib.sha256((d / n).read_bytes()).hexdigest()}  {n}"
             for n in ("dataset.jsonl", "commits.jsonl", "run_manifest.json")]
    (d / "SHA256SUMS").write_bytes(("\n".join(lines) + "\n").encode())


@pytest.fixture
def ab(tmp_path):
    a = tmp_path / "export_A"
    b = tmp_path / "export_B"
    shutil.copytree(EXPORT_SRC, a)
    shutil.copytree(EXPORT_SRC, b)
    # B: đổi nhãn 1 cụm silver -> candidate, đổi run_id + digest sonar, SHA tính lại (B vẫn hợp lệ nội tại)
    rows = [json.loads(l) for l in (b / "dataset.jsonl").read_text(encoding="utf-8").splitlines()]
    i = next(i for i, r in enumerate(rows) if r["label"] == "silver")
    rows[i]["label"] = "candidate"
    rows[i]["evidence"]["consensus"] = "candidate"
    changed = rows[i]
    with open(b / "dataset.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    man = json.loads((b / "run_manifest.json").read_text(encoding="utf-8"))
    man["run_id"] = "smoke2"
    man["counts"]["silver"] -= 1
    man["counts"]["candidate"] += 1
    for rm in man["run_meta"]:
        for t in rm.get("tools_json") or []:
            if t["name"] == "sonar":
                t["digest"] = "sonarqube@sha256:deadbeef"
    with open(b / "run_manifest.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(man, f, ensure_ascii=False, indent=2)
    _resum(b)
    return a, b, changed


def test_report_flags_unexplained_diff_and_digest(rr, orch_env, smoke_db, ab, tmp_path, capsys):
    a, b, changed = ab
    out = tmp_path / "RESULTS.md"
    rc = rr.main(["--a", str(a), "--b", str(b), "--db-a", str(smoke_db), "--db-b", str(smoke_db), "--out", str(out), "--json"])
    assert rc == 1
    rep = json.loads(capsys.readouterr().out)
    c = rep["compare"]
    assert c["same"] == 113 and len(c["label_changed"]) == 1 and c["only_a"] == [] and c["only_b"] == []
    assert len(c["unexplained"]) == 1 and c["unexplained"][0]["cluster_key"] == changed["cluster_key"]
    assert rep["diff_rows"][0]["reason"] == "KHÔNG giải thích" and rep["diff_rows"][0]["label"] == "silver→candidate"
    assert rep["digest_mismatch"] == ["sonar"]
    assert rep["conclusion"]["ok"] is False
    assert any("KHÔNG giải thích" in r for r in rep["conclusion"]["reasons"])
    assert any("digest" in w for w in rep["conclusion"]["warnings"])
    # verify: A PASS (DB + export thật); B: dataset đổi nhãn -> label_rule? không — verify chỉ đếm dòng; counts manifest B khớp? gold/silver lệch DB -> FAIL manifest_counts
    assert rep["verify"]["a"]["pass"] is True
    vb = {x["id"]: x["status"] for x in rep["verify"]["b"]["checks"]}
    assert vb["manifest_counts"] == "FAIL" and vb["sha256sums"] == "PASS"
    # κ A vs B có total
    tot = next(r for r in rep["kappa"] if r["scope"] == "total")
    assert tot["a"] == -0.244 and tot["delta"] == 0.0
    # thời gian + giới hạn
    assert rep["times"]["a"]["started"] == "2026-10-05T07:39:28" and rep["times"]["a"]["commits"] == 3
    assert rep["limits"] and rep["limits_source"].startswith("stats.overview")
    md = out.read_text(encoding="utf-8")
    for h in ("# RESULTS", "## Kết luận", "CHƯA ĐẠT", "## 1. Cấu hình", "🔴 **LỆCH**", "## 2. Phễu", "## 3. So sánh",
              "silver→candidate", "## 4. verify_run", "## 5. Fleiss", "## 6. Tiêu chí", "## 7. Giới hạn"):
        assert h in md, h
    assert "\r\n" not in md


def test_report_passes_for_identical_runs(rr, orch_env, smoke_db, tmp_path, capsys):
    a = tmp_path / "A"
    b = tmp_path / "B"
    shutil.copytree(EXPORT_SRC, a)
    shutil.copytree(EXPORT_SRC, b)
    out = tmp_path / "r" / "RESULTS.md"
    rc = rr.main(["--a", str(a), "--b", str(b), "--db-a", str(smoke_db), "--db-b", str(smoke_db), "--out", str(out)])
    assert rc == 0 and "ĐẠT" in capsys.readouterr().out
    md = out.read_text(encoding="utf-8")
    assert "✅ **ĐẠT tiêu chí tái lập** `--max 3`" in md and "🔴" not in md
    assert "| same | only_a |" in md and "| 114 | 0 | 0 | 0 |" in md


def test_report_without_db_is_not_passing(rr, orch_env, tmp_path):
    a = tmp_path / "A"
    shutil.copytree(EXPORT_SRC, a)
    man = json.loads((a / "run_manifest.json").read_text(encoding="utf-8"))
    man["db"] = str(tmp_path / "khong_ton_tai.sqlite")          # manifest.db trỏ máy khác -> không có DB
    (a / "run_manifest.json").write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    rep = rr.build(a, a)
    assert rep["verify"] == {"a": None, "b": None}
    assert rep["conclusion"]["ok"] is False and any("không có DB" in r for r in rep["conclusion"]["reasons"])
    assert rep["limits"] and rep["limits_source"].startswith("manifest")
    md = rr.to_markdown(rep)
    assert "bỏ qua (không có DB)" in md
    assert rr.main(["--a", str(a), "--b", str(tmp_path / "khong_co"), "--out", str(tmp_path / "x.md")]) == 2
