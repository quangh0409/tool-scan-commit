"""profile.json — một hồ sơ cấu hình = một run tái lập được. Stdlib-only.

Hợp đồng: CONTRACTS.md §profile.json. A2 mở rộng (to_cli, --profile cho argparse); GUI đọc/ghi.

Cấu hình v1 "đăng ký trước" (TOOL_IDEA §13) nằm trong PARAMS_V1 và KHOÁ: profile chỉ được
đổi params khi experiment.enabled=True kèm reason (>= 10 ký tự).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

SCHEMA = 1

PARAMS_V1 = {
    "line_window": 3,
    "gold_min_expensive": 2,
    "gold_allow_1exp_1cheap": 1,
    "silver_min_cheap": 2,
    "noise_cwe": ["CWE-117"],
}

CHEAP_TOOLS_ALL = ["gitleaks", "trufflehog", "semgrep", "bearer", "horusec"]
EXPENSIVE_TOOLS_ALL = ["findsecbugs", "sonar", "codeql"]
SCOPE_MODES = ("time", "count", "sha", "all")


def default_profile(repo: str = "", branch: str = "") -> dict:
    return {
        "schema": SCHEMA,
        "repo": repo,
        "branch": branch,
        "scope": {"mode": "count", "since": None, "until": None, "max": 50,
                  "from_sha": None, "to_sha": None},
        "include_clean": True,
        "cheap_tools": list(CHEAP_TOOLS_ALL),
        "expensive_tools": ["findsecbugs", "sonar"],
        "codeql": False,
        "workers": {"scan": 4, "expensive": 1},
        "paths": {"db": "", "export": "", "work": ""},
        "sonar_port": 9000,
        "experiment": None,            # hoặc {"enabled": true, "reason": "..."}
        "params_v1": dict(PARAMS_V1),
    }


class ProfileError(ValueError):
    pass


def validate(p: dict) -> list[str]:
    """Trả danh sách lỗi (rỗng = hợp lệ). Không raise để GUI hiện tất cả lỗi một lần."""
    errs: list[str] = []
    if p.get("schema") != SCHEMA:
        errs.append(f"schema phải = {SCHEMA}")
    if not p.get("repo"):
        errs.append("repo trống")
    sc = p.get("scope") or {}
    mode = sc.get("mode")
    if mode not in SCOPE_MODES:
        errs.append(f"scope.mode phải thuộc {SCOPE_MODES}")
    if mode == "count":
        try:
            if int(sc.get("max") or 0) <= 0:
                errs.append("scope.max phải > 0 (toàn lịch sử dùng mode=all)")
        except (TypeError, ValueError):
            errs.append("scope.max không phải số")
    if mode == "time":
        if not sc.get("since") and not sc.get("until"):
            errs.append("scope.time cần since hoặc until")
        if sc.get("since") and sc.get("until") and sc["since"] > sc["until"]:
            errs.append("scope.since > scope.until")
    if mode == "sha" and not (sc.get("from_sha") or sc.get("to_sha")):
        errs.append("scope.sha cần from_sha hoặc to_sha")
    bad = [t for t in p.get("cheap_tools", []) if t not in CHEAP_TOOLS_ALL]
    if bad:
        errs.append(f"cheap_tools lạ: {bad}")
    bad = [t for t in p.get("expensive_tools", []) if t not in EXPENSIVE_TOOLS_ALL]
    if bad:
        errs.append(f"expensive_tools lạ: {bad}")
    w = p.get("workers") or {}
    for k in ("scan", "expensive"):
        try:
            if int(w.get(k, 1)) < 1:
                errs.append(f"workers.{k} phải >= 1")
        except (TypeError, ValueError):
            errs.append(f"workers.{k} không phải số")
    paths = p.get("paths") or {}
    if not paths.get("db"):
        errs.append("paths.db trống")
    exp = p.get("experiment")
    params = p.get("params_v1") or {}
    if params != PARAMS_V1:
        if not (exp and exp.get("enabled") and len((exp.get("reason") or "").strip()) >= 10):
            errs.append("params_v1 khác cấu hình v1 nhưng không bật experiment kèm lý do (>=10 ký tự)")
    return errs


def load(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        p = json.load(f)
    errs = validate(p)
    if errs:
        raise ProfileError("; ".join(errs))
    return p


def save(p: dict, path: str | Path) -> None:
    errs = validate(p)
    if errs:
        raise ProfileError("; ".join(errs))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)


def to_env(p: dict) -> dict[str, str]:
    """Profile -> biến ORCH_* (đặt TRƯỚC khi import orchestrator.config ở tiến trình con)."""
    params = p.get("params_v1") or PARAMS_V1
    env = {
        "ORCH_SQLITE": p["paths"]["db"],
        "ORCH_EXPORT_DIR": p["paths"].get("export") or "",
        "ORCH_WORK_DIR": p["paths"].get("work") or "",
        "ORCH_SCAN_WORKERS": str(p["workers"]["scan"]),
        "ORCH_EXPENSIVE_WORKERS": str(p["workers"]["expensive"]),
        "ORCH_EXPENSIVE_TOOLS": ",".join(p.get("expensive_tools") or []),
        "ORCH_CHEAP_TOOLS": ",".join(p.get("cheap_tools") or []),
        "ORCH_USE_CODEQL": "1" if p.get("codeql") else "0",
        "ORCH_SONAR_PORT": str(p.get("sonar_port") or 9000),
        "ORCH_GOLD_MIN_EXPENSIVE": str(params["gold_min_expensive"]),
        "ORCH_GOLD_ALLOW_1EXP_1CHEAP": str(params["gold_allow_1exp_1cheap"]),
        "ORCH_SILVER_MIN_CHEAP": str(params["silver_min_cheap"]),
        "ORCH_NOISE_CWE": ",".join(params["noise_cwe"]),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    # CONTRACTS §12 (A4 sửa thay A2): filters{clean_per_buggy, require_in_diff} từ Wizard 2 -> env.
    # config.py hiện đọc ORCH_SUSPECT_REQUIRE_IN_DIFF; ORCH_CLEAN_PER_BUGGY chờ A2 nối vào select_commits.
    flt = p.get("filters") or {}
    if flt.get("clean_per_buggy") not in (None, ""):
        env["ORCH_CLEAN_PER_BUGGY"] = str(int(flt["clean_per_buggy"]))
    if "require_in_diff" in flt and flt["require_in_diff"] is not None:
        env["ORCH_SUSPECT_REQUIRE_IN_DIFF"] = "1" if flt["require_in_diff"] else "0"
    exp = p.get("experiment")
    if exp and exp.get("enabled"):
        env["ORCH_EXPERIMENT"] = "1"
        env["ORCH_EXPERIMENT_REASON"] = exp.get("reason", "")
        env["ORCH_LINE_WINDOW"] = str(params["line_window"])
    return {k: v for k, v in env.items() if v != ""}


def to_cli_args(p: dict) -> list[str]:
    """Profile -> argv cho `orchestrator.cli pipeline` (A2 bảo đảm argparse nhận đủ)."""
    sc = p["scope"]
    args = ["pipeline", p["repo"]]
    if p.get("branch"):
        args += ["--branch", p["branch"]]
    if sc["mode"] == "all":
        args += ["--max", "0"]
    elif sc["mode"] == "count":
        args += ["--max", str(sc["max"])]
    elif sc["mode"] == "time":
        args += ["--max", "0"]
        if sc.get("since"):
            args += ["--since", sc["since"]]
        if sc.get("until"):
            args += ["--until", sc["until"]]
    elif sc["mode"] == "sha":
        args += ["--max", "0"]
        if sc.get("from_sha"):
            args += ["--from-sha", sc["from_sha"]]
        if sc.get("to_sha"):
            args += ["--to-sha", sc["to_sha"]]
    args += ["--codeql", "1" if p.get("codeql") else "0"]
    if p.get("include_clean"):
        args += ["--include-clean"]
    args += ["--workers", str(p["workers"]["expensive"])]
    if p.get("cheap_tools") and set(p["cheap_tools"]) != set(CHEAP_TOOLS_ALL):
        args += ["--tools", ",".join(p["cheap_tools"])]
    if p.get("expensive_tools"):
        args += ["--expensive-tools", ",".join(p["expensive_tools"])]
    if p["paths"].get("export"):
        args += ["--out", p["paths"]["export"]]
    return args


def _q_ps(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _q_sh(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


def to_shell(p: dict, shell: str = "powershell") -> str:
    """Lệnh tương đương chạy được: 'powershell' hoặc 'bash'. Mọi giá trị đều được quote."""
    env = to_env(p)
    args = to_cli_args(p)
    if shell == "powershell":
        sets = "; ".join(f"$env:{k}={_q_ps(v)}" for k, v in env.items())
        cmd = "python -m orchestrator.cli " + " ".join(_q_ps(a) for a in args)
        return f"{sets}; $env:PYTHONPATH='src'; {cmd}"
    sets = " ".join(f"{k}={_q_sh(v)}" for k, v in env.items())
    cmd = "python -m orchestrator.cli " + " ".join(_q_sh(a) for a in args)
    return f"{sets} PYTHONPATH=src {cmd}"


def from_env_defaults(repo: str, branch: str, out_dir: str) -> dict:
    """Tiện ích GUI: profile mặc định với đường dẫn tự sinh (1 repo = 1 DB + 1 export)."""
    from .keys import repo_slug
    import time as _t
    slug = repo_slug(repo)
    stamp = _t.strftime("%Y%m%d")
    p = default_profile(repo, branch)
    base = Path(out_dir)
    p["paths"] = {
        "db": str(base / f"dataset_{slug}_{branch or 'HEAD'}_{stamp}.sqlite"),
        "export": str(base / f"export_{slug}_{branch or 'HEAD'}_{stamp}"),
        "work": str(base / "work"),
    }
    p["sonar_port"] = int(os.environ.get("ORCH_SONAR_PORT", "9000"))
    return p
