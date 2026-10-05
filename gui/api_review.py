"""API Kiểm tay mù (CONTRACTS §9): wrapper `orchestrator.review` (A1 đợt 2).

Bảng route → hàm (A4 map):
  POST /api/review/{id}/sample {seed, n_pos, n_neg}              sample
  GET  /api/review/{id}/next?sample_id=&rater=                   next_item   (hết mẫu → {cluster_key:null, remaining:0})
  POST /api/review/{id}/verdict {sample_id, rater, cluster_key, verdict, note}   verdict
  POST /api/review/{id}/close {sample_id, raters?}               close

`orchestrator.review` chưa có → 501 ENOTSUP (import lười). Chữ ký giả định của A1:
  sample(store, seed, n_pos, n_neg) -> {sample_id, n_pos, n_neg, strata[]}
  next_item(store, sample_id, rater) -> {cluster_key|None, code_lines[], diff_lines[], cwe_claim, messages_anon[], remaining}
  verdict(store, sample_id, rater, cluster_key, verdict, note) -> {ok, remaining}
  close(store, sample_id, raters=None) -> {precision{}, kappa_raters|None, disagreements[]}
DB mở GHI (SQLiteStore: migrate + lock) → 409 nếu run đang chạy trên DB đó.
"""
from __future__ import annotations

from . import api_common as C
from .errors import ApiError, bad_request, not_supported

VERDICTS = ("TP", "FP", "unclear")
BLIND_FORBIDDEN = ("label", "tools", "n_agree", "n_tools_agree", "agreeing_tools", "tier", "precision", "evidence", "tool")


def _mod():
    C.ensure_src_on_path()
    try:
        from orchestrator import review  # noqa: PLC0415
    except ImportError as e:
        raise not_supported("Backend kiểm tay (orchestrator.review) chưa có", f"A1 đợt 2: {e}") from e
    return review


def _store(params: dict):
    rid = C.require_run_id(params)
    try:
        run = C.find_run(rid)
    except ApiError:
        if params.get("db"):
            run = {"run_id": rid, "db": params["db"]}
        else:
            raise
    db = C.run_db(run)
    return rid, C.open_rw(db)


def _call(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except ApiError:
        raise
    except (ValueError, KeyError, LookupError) as e:
        raise bad_request(f"kiểm tay: {e}") from e


def sample(params: dict, body: dict | None = None) -> dict:
    body = body or {}
    seed = C.to_int(body.get("seed"), 42, lo=0, name="seed")
    n_pos = C.to_int(body.get("n_pos"), 200, lo=1, hi=100000, name="n_pos")
    n_neg = C.to_int(body.get("n_neg"), 100, lo=0, hi=100000, name="n_neg")
    rv = _mod()
    rid, store = _store(params)
    try:
        res = _call(rv.sample, store, seed, n_pos, n_neg)
    finally:
        store.close()
    res = dict(res or {})
    res.setdefault("seed", seed)
    res["run_id"] = rid
    return res


def next_item(params: dict, body: dict | None = None) -> dict:
    sid = str(params.get("sample_id") or (body or {}).get("sample_id") or "").strip()
    rater = str(params.get("rater") or (body or {}).get("rater") or "").strip()
    if not sid or not rater:
        raise bad_request("cần sample_id và rater")
    rv = _mod()
    rid, store = _store(params)
    try:
        res = _call(rv.next_item, store, sid, rater)
    finally:
        store.close()
    if not res or not res.get("cluster_key"):
        return {"cluster_key": None, "remaining": 0, "sample_id": sid, "rater": rater}
    # giao thức MÙ: lọc mọi trường lộ nhãn/tool nếu backend lỡ trả
    out = {k: v for k, v in dict(res).items() if k not in BLIND_FORBIDDEN}
    out.setdefault("code_lines", [])
    out.setdefault("diff_lines", [])
    out.setdefault("messages_anon", [])
    out.setdefault("remaining", 0)
    out["sample_id"] = sid
    return out


def verdict(params: dict, body: dict | None = None) -> dict:
    body = body or {}
    sid = str(body.get("sample_id") or "").strip()
    rater = str(body.get("rater") or "").strip()
    ck = str(body.get("cluster_key") or "").strip()
    v = str(body.get("verdict") or "").strip()
    note = str(body.get("note") or "")
    if not (sid and rater and ck):
        raise bad_request("cần sample_id, rater, cluster_key")
    if v not in VERDICTS:
        raise bad_request(f"verdict phải thuộc {VERDICTS}")
    rv = _mod()
    rid, store = _store(params)
    try:
        res = _call(rv.verdict, store, sid, rater, ck, v, note)
    finally:
        store.close()
    res = dict(res or {})
    res.setdefault("ok", True)
    res.setdefault("remaining", 0)
    return res


def close(params: dict, body: dict | None = None) -> dict:
    body = body or {}
    sid = str(body.get("sample_id") or params.get("sample_id") or "").strip()
    if not sid:
        raise bad_request("cần sample_id")
    raters = body.get("raters")
    if raters is not None and not isinstance(raters, list):
        raise bad_request("raters phải là danh sách")
    rv = _mod()
    rid, store = _store(params)
    try:
        try:
            res = _call(rv.close, store, sid, raters)
        except TypeError:
            res = _call(rv.close, store, sid)
    finally:
        store.close()
    res = dict(res or {})
    res.setdefault("kappa_raters", None)
    res.setdefault("disagreements", [])
    for d in res["disagreements"]:
        if isinstance(d, dict):
            d.setdefault("adjudicated", (d.get("verdicts") or {}).get("adjudicated"))
    res["sample_id"] = sid
    res["run_id"] = rid
    return res
