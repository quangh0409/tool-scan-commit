"""CLI: python -m preflight --json [--fix <id>|all] … → JSON ra stdout; exit 0 nếu ready, 1 nếu không."""
from __future__ import annotations

import argparse
import json
import sys

from . import run
from .fixes import FIX_IDS

_ICON = {"ok": "[OK]  ", "fix": "[FIX] ", "warn": "[WARN]", "bad": "[BAD] "}


def _text(res: dict) -> str:
    lines = []
    for it in res["items"]:
        lines.append(f"{_ICON.get(it['level'], '[?]  ')} {it['id']:<17} {it['title']}")
        lines.append(f"        {it['detail']}")
    lines.append("")
    lines.append(f"ready={res['ready']}  docker_mem_gb={res['docker_mem_gb']}  cpu={res['cpu']}  "
                 f"sonar_port={res['sonar_port']}  codeql_ram_mb={res['codeql_ram_mb']}  ({res['elapsed_s']}s)")
    for f in res.get("fixed", []):
        lines.append(f"fix {f['fix_id']}: {'OK' if f['ok'] else 'FAIL'} — {f['detail']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m preflight", description="Kiểm tra môi trường chạy SecJIT.")
    ap.add_argument("--json", action="store_true", help="in JSON (mặc định in dạng text)")
    ap.add_argument("--fix", action="append", default=None, metavar="ID",
                    help=f"tự sửa mục (lặp được; 'all' = mọi mục sửa được). ID ∈ {', '.join(FIX_IDS)}")
    ap.add_argument("--work-dir", default=None, help="thư mục làm việc để đo đĩa trống")
    ap.add_argument("--need-gb", type=float, default=5.0, help="GB ước tính cần (mặc định 5)")
    ap.add_argument("--sonar-port", type=int, default=None, help="port Sonar mong muốn (mặc định ORCH_SONAR_PORT|9000)")
    ap.add_argument("--only", default=None, help="chỉ chạy các check này, phân cách bằng dấu phẩy")
    ap.add_argument("--include-codeql", action="store_true", help="coi orch-codeql là bắt buộc khi pull/build")
    ap.add_argument("--out", default=None, help="ghi JSON kết quả ra file (preflight.json)")
    a = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass

    do_fix = bool(a.fix)
    targets = None if (not a.fix or "all" in a.fix) else list(a.fix)
    checks = [c.strip() for c in a.only.split(",") if c.strip()] if a.only else None

    def cb(info):
        if not a.json and sys.stderr:
            msg = info.get("msg") or (f"… {info['check']}" if "check" in info else "")
            if msg:
                print(msg, file=sys.stderr, flush=True)

    res = run(fix=do_fix, targets=targets, checks=checks, work_dir=a.work_dir, need_gb=a.need_gb,
              sonar_port=a.sonar_port, progress_cb=cb, include_codeql=a.include_codeql)
    text = json.dumps(res, ensure_ascii=False, indent=2)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    print(text if a.json else _text(res))
    return 0 if res["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
