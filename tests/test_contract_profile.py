"""Hợp đồng profile ↔ CLI ↔ config: mọi profile sinh ra → to_cli_args parse được bởi argparse THẬT của
orchestrator.cli (build_parser) với đúng giá trị; to_env → config.reload() cho đúng giá trị; apply_profile
(`pipeline --profile F`) dựng lại argv parse được."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PROFILES = json.loads((ROOT / "gui" / "fixtures" / "profiles.json").read_text(encoding="utf-8"))["profiles"]


def _variants(tmp_path) -> list[tuple[str, dict]]:
    from orchestrator import profile
    base = tmp_path / "out ạ's"
    out = []

    def mk(name, **over):
        p = profile.default_profile("https://github.com/FudanSELab/train-ticket", "master")
        p["paths"] = {"db": str(base / f"{name}.sqlite"), "export": str(base / f"export_{name}"), "work": str(base / "work")}
        for k, v in over.items():
            if isinstance(v, dict) and isinstance(p.get(k), dict):
                p[k] = {**p[k], **v}
            else:
                p[k] = v
        out.append((name, p))

    mk("count30", scope={"mode": "count", "max": 30})
    mk("all", scope={"mode": "all", "max": 0})
    mk("time", scope={"mode": "time", "since": "2025-01-01", "until": "2025-06-30"})
    mk("time_since_only", scope={"mode": "time", "since": "2025-01-01"})
    mk("sha", scope={"mode": "sha", "from_sha": "abc123", "to_sha": "def456"})
    mk("tools_subset", cheap_tools=["semgrep", "bearer"], expensive_tools=["findsecbugs"])
    mk("codeql", codeql=True, expensive_tools=["findsecbugs", "sonar", "codeql"], workers={"scan": 2, "expensive": 2})
    mk("no_clean", include_clean=False, sonar_port=9100)
    mk("no_branch", branch="")
    mk("experiment", experiment={"enabled": True, "reason": "thử line_window=5 cho sensitivity"},
       params_v1={**profile.PARAMS_V1, "line_window": 5, "gold_min_expensive": 1})
    for fx in FIXTURE_PROFILES:                      # profile từ fixture GUI
        mk("fx_" + fx["name"], repo=fx["repo"], branch=fx.get("branch", "master"),
           scope={"mode": "count", "max": int(fx["name"].rsplit("-", 1)[-1]) if fx["name"][-1].isdigit() else 30})
    return out


@pytest.fixture(autouse=True)
def clean_config():
    """Khôi phục os.environ + config.reload() SAU test để không làm bẩn config toàn cục cho test khác."""
    import os
    from orchestrator import config
    snap = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(snap)
    config.reload()


@pytest.fixture
def variants(tmp_path):
    return _variants(tmp_path)


def test_every_variant_is_valid(variants):
    from orchestrator import profile
    for name, p in variants:
        assert profile.validate(p) == [], name


def test_to_cli_args_parse_by_real_parser(variants):
    from orchestrator import cli, profile
    parser = cli.build_parser()
    for name, p in variants:
        argv = profile.to_cli_args(p)
        ns = parser.parse_args(argv)                 # SystemExit nếu argparse không nhận
        sc = p["scope"]
        assert ns.repo == p["repo"], name
        assert (ns.branch or "") == (p.get("branch") or ""), name
        if sc["mode"] == "count":
            assert ns.max == sc["max"], name
        else:
            assert ns.max == 0, name
        assert (ns.since, ns.until) == ((sc.get("since") if sc["mode"] == "time" else None),
                                        (sc.get("until") if sc["mode"] == "time" else None)), name
        assert (ns.from_sha, ns.to_sha) == ((sc.get("from_sha") if sc["mode"] == "sha" else None),
                                            (sc.get("to_sha") if sc["mode"] == "sha" else None)), name
        assert ns.codeql == (1 if p["codeql"] else 0), name
        assert ns.include_clean is bool(p["include_clean"]), name
        assert ns.workers == p["workers"]["expensive"], name
        assert ns.out == p["paths"]["export"], name
        exp_tools = ",".join(p["cheap_tools"]) if set(p["cheap_tools"]) != set(profile.CHEAP_TOOLS_ALL) else None
        assert ns.tools == exp_tools, name
        assert ns.expensive_tools == ",".join(p["expensive_tools"]), name
        assert ns.func is cli.cmd_pipeline


def test_to_env_reload_config(variants, monkeypatch):
    from orchestrator import config, profile
    for name, p in variants:
        env = profile.to_env(p)
        for k in list(config.ENV_KEYS) + ["ORCH_LINE_WINDOW", "ORCH_EXPERIMENT", "ORCH_EXPERIMENT_REASON"]:
            monkeypatch.delenv(k, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        config.reload()
        params = p["params_v1"]
        assert str(config.SQLITE_PATH) == p["paths"]["db"], name
        assert str(config.EXPORT_DIR) == p["paths"]["export"], name
        assert str(config.WORK_DIR) == p["paths"]["work"], name
        assert config.SCAN_WORKERS == p["workers"]["scan"] and config.EXPENSIVE_WORKERS == p["workers"]["expensive"], name
        assert config.CHEAP_TOOLS == p["cheap_tools"] and config.EXPENSIVE_TOOLS == p["expensive_tools"], name
        assert config.USE_CODEQL == (1 if p["codeql"] else 0), name
        assert config.SONAR_HOST_PORT == p["sonar_port"], name
        assert config.GOLD_MIN_EXPENSIVE == params["gold_min_expensive"], name
        assert config.GOLD_ALLOW_1EXP_1CHEAP == params["gold_allow_1exp_1cheap"], name
        assert config.SILVER_MIN_CHEAP == params["silver_min_cheap"], name
        assert config.NOISE_CWE == set(params["noise_cwe"]), name
        exp = p.get("experiment")
        if exp and exp.get("enabled"):
            assert config.EXPERIMENT == 1 and config.LINE_WINDOW == params["line_window"], name
            assert config.experiment_info() == {"enabled": True, "reason": exp["reason"]}, name
        else:
            assert config.EXPERIMENT == 0 and config.LINE_WINDOW == config.LINE_WINDOW_V1, name
            assert config.experiment_info() is None
        assert config.params_v1() == {**params, "noise_cwe": sorted(params["noise_cwe"])}, name


def test_apply_profile_rebuilds_argv(variants, tmp_path, monkeypatch):
    from orchestrator import cli, profile
    parser = cli.build_parser()
    for name, p in variants:
        path = tmp_path / f"{name}.json"
        profile.save(p, path)
        for cmd in ("pipeline", "scan", "export", "estimate"):
            pdata, argv = cli.apply_profile([cmd, "--profile", str(path), "--json"])
            assert pdata == p, name
            ns = parser.parse_args(argv)
            assert ns.json is True and ns.profile == str(path), (name, cmd, argv)
            if cmd in cli.PROFILE_DRIVEN:
                assert argv[0] == cmd, (name, cmd)
                if cmd != "export":
                    assert argv[1] == p["repo"], (name, cmd, argv)
        assert str(__import__("orchestrator.config", fromlist=["x"]).SQLITE_PATH) == p["paths"]["db"]


def test_apply_profile_invalid_exit_1(tmp_path, capsys):
    from orchestrator import cli
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": 1, "repo": "", "scope": {"mode": "count", "max": 0}}), encoding="utf-8")
    assert cli.main(["pipeline", "--profile", str(bad)]) == 1
    assert "LỖI tham số" in capsys.readouterr().err
    assert cli.main(["pipeline", "--profile", str(tmp_path / "khong-co.json")]) == 1


def test_to_shell_tokens_match_cli_args(variants):
    """Lệnh to_shell(bash) tách ra đúng argv mà argparse chấp nhận."""
    import shlex
    from orchestrator import cli, profile
    parser = cli.build_parser()
    for name, p in variants:
        toks = shlex.split(profile.to_shell(p, "bash"))
        i = toks.index("orchestrator.cli")
        parser.parse_args(toks[i + 1:])
