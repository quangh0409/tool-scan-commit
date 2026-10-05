"""preflight — kiểm tra môi trường 13 mục + auto-fix (CONTRACTS §8).

API public (A4 gọi):
  run(fix=False, targets=None, checks=None, work_dir=None, need_gb=5.0, sonar_port=None,
      progress_cb=None, docker_timeout=15) -> dict
      {"items":[{id,title,level,detail,fix_available,fix_id,...}], "ready": bool,
       "docker_mem_gb": float|None, "cpu": int|None, "codeql_ram_mb": int|None,
       "sonar_port": int|None, "fixed": [{fix_id, ok, detail}], "os": str, "ts": str, "elapsed_s": float}
  fix(fix_id, ctx=None, progress_cb=None) -> {"ok","detail",...}   (gọi 1 fix rồi GUI gọi run() lại)
  CLI: python -m preflight --json [--fix <id>|all] [--work-dir D] [--need-gb N] [--sonar-port P] [--out F]
       exit 0 nếu ready, 1 nếu không.

ready = không còn mục level `bad` hoặc `fix` (warn không chặn).
"""
from __future__ import annotations

import platform
import time

from . import checks as _checks
from . import fixes as _fixes

LEVELS = ("ok", "fix", "warn", "bad")
BLOCKING = ("bad", "fix")


def _ready(items: list[dict]) -> bool:
    return all(it.get("level") not in BLOCKING for it in items)


def run(fix: bool = False, targets: list[str] | None = None, checks: list[str] | None = None,
        work_dir: str | None = None, need_gb: float = _checks.DEFAULT_NEED_GB, sonar_port: int | None = None,
        progress_cb=None, docker_timeout: float = _checks.DOCKER_TIMEOUT, include_codeql: bool = False) -> dict:
    """Chạy các check (mặc định cả 13, đúng thứ tự CHECK_ORDER).

    fix=True → với mỗi mục có fix_available (và id ∈ targets nếu targets cho) gọi fixes.apply rồi
    kiểm lại mục đó. progress_cb(info) nhận {"check": id} khi bắt đầu mỗi check và tiến độ fix.
    """
    t0 = time.monotonic()
    ctx: dict = {"work_dir": work_dir, "need_gb": need_gb, "sonar_port": sonar_port,
                 "docker_timeout": docker_timeout, "include_codeql": include_codeql}
    order = [c for c in _checks.CHECK_ORDER if (checks is None or c in checks)]
    items: list[dict] = []
    fixed: list[dict] = []
    for cid in order:
        if progress_cb:
            try:
                progress_cb({"check": cid})
            except Exception:  # noqa: BLE001
                pass
        it = _checks.run_check(cid, ctx)
        if fix and it.get("fix_available") and it.get("fix_id") and (targets is None or it["fix_id"] in targets
                                                                        or cid in targets):
            res = _fixes.apply(it["fix_id"], ctx, progress_cb)
            fixed.append({"fix_id": it["fix_id"], "check": cid, "ok": bool(res.get("ok")),
                          "detail": res.get("detail", "")})
            it = _checks.run_check(cid, ctx)
            if not res.get("ok"):
                it["detail"] = f"{it['detail']} [Sửa thất bại: {res.get('detail', '')}]"
            else:
                it["fixed"] = True
        items.append(it)
    return {
        "items": items,
        "ready": _ready(items),
        "docker_mem_gb": ctx.get("docker_mem_gb"),
        "cpu": ctx.get("cpu"),
        "codeql_ram_mb": ctx.get("codeql_ram_mb"),
        "sonar_port": ctx.get("sonar_port_free") or ctx.get("sonar_port"),
        "fixed": fixed,
        "os": f"{platform.system()} {platform.release()}",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_s": round(time.monotonic() - t0, 2),
    }


def fix(fix_id: str, ctx: dict | None = None, progress_cb=None) -> dict:
    return _fixes.apply(fix_id, ctx, progress_cb)


__all__ = ["run", "fix", "LEVELS", "BLOCKING"]
