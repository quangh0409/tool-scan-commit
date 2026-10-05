"""Tầng rẻ: argv semgrep không phụ thuộc số file (WinError 206); lỗi tool được ghi DB + manifest."""
from __future__ import annotations

import importlib
import json
import subprocess
from pathlib import Path

CID = "fa8d9efb" + "0" * 32
REPO = "https://github.com/FudanSELab/train-ticket"


def _m(name):
    return importlib.import_module(name)


def test_semgrep_argv_short_with_2000_long_paths(orch_env, fake_docker, tmp_path):
    sg = _m("orchestrator.tools.semgrep")
    repo = tmp_path / "repo"
    # mỗi path ~70 ký tự (dưới MAX_PATH 260 của Windows khi tạo file test), tổng > 32 k ký tự
    long_dir = "ts-" + "x" * 12 + "/src/main/java/" + "y" * 8
    changed = [f"{long_dir}/File{i:04d}WithAVeryLongJavaClassName.java" for i in range(2000)]
    for rel in changed[:50]:                      # 50 file tồn tại, 1950 đã bị xoá/không có
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("class A {}", encoding="utf-8")
    assert sum(len(c) for c in changed) > 32_000     # argv cũ chắc chắn vượt giới hạn Windows

    seen = {}

    def _pred(cmd):
        if "semgrep" in cmd and "scan" in cmd:
            mount = Path(cmd[cmd.index("-v") + 1].rsplit(":", 1)[0])
            seen["files"] = sorted(str(p.relative_to(mount)).replace("\\", "/")
                                   for p in mount.rglob("*") if p.is_file())
            return True
        return False
    fake_docker.responses.append((_pred, (0, json.dumps({"results": [
        {"check_id": "java.lang.security.sqli", "path": f"/src/{changed[0]}",
         "start": {"line": 3}, "end": {"line": 3},
         "extra": {"severity": "ERROR", "message": "SQLi", "metadata": {"cwe": ["CWE-89"]}}}]}), "")))

    out = sg.SemgrepWrapper().scan(repo, CID, REPO, changed, raw_out=[])
    cmd = fake_docker.calls[-1]
    assert len(" ".join(cmd)) < 8000
    assert not any("WithAVeryLongJavaClassName" in c for c in cmd)      # không còn file nào trong argv
    assert cmd[-1] == "/src" and "--config" in cmd and "--json" in cmd
    assert len(seen["files"]) == 51 and ".semgrepignore" in seen["files"]   # 50 file + .semgrepignore
    assert changed[0] in seen["files"]
    assert len(out) == 1 and out[0].file_path == changed[0] and out[0].cwe == ["CWE-89"]


def test_other_cheap_wrappers_do_not_pass_file_list(orch_env, fake_docker, tmp_path):
    changed = [f"d{i}/f{i}.java" for i in range(3000)]
    repo = tmp_path / "r"
    repo.mkdir()
    for mod, cls in (("bearer", "BearerWrapper"), ("horusec", "HorusecWrapper"),
                     ("gitleaks", "GitleaksWrapper"), ("trufflehog", "TrufflehogWrapper")):
        getattr(_m(f"orchestrator.tools.{mod}"), cls)().scan(repo, CID, REPO, changed, raw_out=[])
        for cmd in fake_docker.calls:
            assert len(" ".join(cmd)) < 8000, mod
        fake_docker.calls.clear()


def test_tool_error_recorded_in_db_and_manifest(orch_env, fake_docker):
    base = _m("orchestrator.tools.base")
    exp = _m("orchestrator.export_dataset")
    sq = _m("orchestrator.storage.sqlite_store")

    class Boom(base.ToolWrapper):
        name, tier, image = "semgrep", "cheap", "x"

        def scan(self, repo_dir, commit_id, repo, changed_files, raw_out=None):
            raise OSError(206, "The filename or extension is too long")

    class Slow(base.ToolWrapper):
        name, tier, image = "bearer", "cheap", "x"

        def scan(self, repo_dir, commit_id, repo, changed_files, raw_out=None):
            raw_out.append(("json", "{}"))
            raise subprocess.TimeoutExpired(["docker"], 900)

    raw = []
    assert Boom().scan(Path("."), CID, REPO, ["a"], raw_out=raw) == []     # không nổ ra ngoài
    assert raw[0][0] == "error" and json.loads(raw[0][1])["kind"] == "tool_error"
    raw2 = []
    assert Slow().scan(Path("."), CID, REPO, ["a"], raw_out=raw2) == []
    assert raw2[0][0] == "error" and json.loads(raw2[0][1])["kind"] == "tool_timeout"   # chèn ĐẦU

    st = sq.SQLiteStore()
    st.insert_raw_output(CID, "semgrep", raw[0][0], raw[0][1])          # đúng như cli._safe làm
    st.insert_raw_output(CID, "bearer", raw2[0][0], raw2[0][1])
    errs = st.scan_tool_errors_rows(CID)
    assert [(e["tool"], e["kind"], e["tier"]) for e in errs] == [("semgrep", "tool_error", "cheap"),
                                                                 ("bearer", "tool_timeout", "cheap")]
    assert "too long" in errs[0]["msg"]
    assert st.conn.execute("SELECT COUNT(*) FROM raw_output WHERE fmt='error'").fetchone()[0] == 2
    st.save_kappa("test-run", "total", "", 0.0, 1)
    out = Path(exp.export_all(st, orch_env / "exp")["out"])
    st.close()

    man = json.loads((out / "run_manifest.json").read_text(encoding="utf-8"))
    assert man["tool_error"] == [{"commit": CID, "tool": "semgrep", "tier": "cheap"}]
    assert man["tool_timeout"] == [{"commit": CID, "tool": "bearer", "tier": "cheap"}]
    assert (out / CID[:12] / "semgrep.raw.error").exists()

    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    try:
        vr = importlib.reload(importlib.import_module("verify_run"))
    finally:
        sys.path.pop(0)
    res = vr.run(st.path, out)
    assert res["pass"] is True, [c for c in res["checks"] if c["status"] == "FAIL"]
