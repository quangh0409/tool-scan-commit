"""Gallery HTML tĩnh cho ảnh chụp GUI (thumbnail + tên, nhóm theo màn, lọc theo trạng thái/nguồn).

  python tests/gui/gallery.py --in DIR [DIR ...] --out index.html [--title T]

Hiểu 3 kiểu tên file:
  shoot.py   : <route>[--<state>].png        vd wizard-1--loading.png, preflight.png
  shoot_a5.py: <screen>[__<state>].png       vd dashboard__interrupted.png
  flow_mock  : NN_<step>[_FAIL].png          vd 07_wizard2_scope.png (nhóm "flow", trạng thái pass/fail)
Không phụ thuộc thư viện ngoài (không PIL): thumbnail = <img loading=lazy> thu bằng CSS; bấm → xem ảnh gốc.
Đường dẫn ảnh ghi tương đối so với file --out (có thể copy cả cây sang máy khác).
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
from pathlib import Path

RE_FLOW = re.compile(r"^(\d{2})_(.+?)(_FAIL)?\.png$", re.I)
RE_A4 = re.compile(r"^([a-z0-9]+(?:-[a-z0-9]+)*?)(?:--([a-z0-9_]+))?\.png$", re.I)
RE_A5 = re.compile(r"^([a-z0-9_]+?)(?:__([a-z0-9_]+))?\.png$", re.I)

SCREEN_ORDER = ["preflight", "home", "wizard-1", "wizard-2", "wizard-3", "wizard-4", "wizard-5", "dashboard",
                "results_overview", "results_findings", "results_commits", "results_export", "review", "settings", "flow"]


def classify(name: str) -> tuple[str, str]:
    """-> (screen, state)."""
    m = RE_FLOW.match(name)
    if m:
        return "flow", "fail" if m.group(3) else "pass"
    if "__" in name:
        m = RE_A5.match(name)
        if m:
            return m.group(1), m.group(2) or "normal"
    m = RE_A4.match(name)
    if m:
        return m.group(1), m.group(2) or "normal"
    return Path(name).stem, "normal"


def collect(dirs: list[Path], out_dir: Path) -> list[dict]:
    items = []
    for d in dirs:
        if not d.is_dir():
            print(f"CẢNH BÁO: bỏ qua {d} (không phải thư mục)", file=sys.stderr)
            continue
        for p in sorted(d.rglob("*.png")):
            screen, state = classify(p.name)
            rel = os.path.relpath(p, out_dir).replace(os.sep, "/")
            st = p.stat()
            sub = os.path.relpath(p.parent, d).replace(os.sep, "/")
            src = d.name if sub == "." else f"{d.name}/{sub}"
            items.append({"src": src, "file": p.name, "rel": rel, "screen": screen, "state": state,
                          "kb": round(st.st_size / 1024), "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))})
    return items


CSS = """
:root{--bg:#E9ECF0;--hdr:#142233;--acc:#1F5F8B;--ok:#1B7F4D;--bad:#B42318;--warn:#7A5B00;--card:#fff;--mut:#5a6572}
*{box-sizing:border-box}body{margin:0;font:14px/1.45 "IBM Plex Sans",system-ui,sans-serif;background:var(--bg);color:#1b2533}
header{background:var(--hdr);color:#fff;padding:14px 20px;display:flex;gap:16px;align-items:center;flex-wrap:wrap;position:sticky;top:0;z-index:5}
header h1{font-size:18px;margin:0 12px 0 0}header .f{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.chip{border:1px solid #ffffff66;border-radius:14px;padding:2px 10px;cursor:pointer;background:transparent;color:#fff;font-size:12px}
.chip.on{background:#fff;color:var(--hdr)}header input{border:0;border-radius:6px;padding:5px 8px;min-width:200px}
main{padding:16px 20px}section{margin-bottom:22px}section h2{font-size:15px;margin:0 0 8px;color:var(--acc);display:flex;gap:8px;align-items:baseline}
section h2 small{color:var(--mut);font-weight:400}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.card{background:var(--card);border-radius:8px;box-shadow:0 1px 2px #0002;overflow:hidden;display:flex;flex-direction:column}
.card .th{height:170px;overflow:hidden;background:#dde2e8;cursor:zoom-in;display:flex;align-items:flex-start;justify-content:center}
.card img{width:100%;height:auto;display:block}.card .cap{padding:8px 10px;font-size:12px;display:flex;justify-content:space-between;gap:6px}
.card .cap b{font-weight:600;word-break:break-all}.tag{border-radius:10px;padding:0 8px;font-size:11px;background:#E3E7EC;color:#3B4654;white-space:nowrap}
.tag.pass,.tag.normal,.tag.fixed{background:#d9efe3;color:var(--ok)}.tag.fail,.tag.error,.tag.bad,.tag.docker_down,.tag.infra,.tag.infra_stop{background:#f9dcd8;color:var(--bad)}
.tag.loading,.tag.partial,.tag.empty,.tag.interrupted,.tag.blank{background:#f6ecc8;color:var(--warn)}
.src{color:var(--mut);font-size:11px}.hide{display:none}
#lb{position:fixed;inset:0;background:#000c;display:none;align-items:flex-start;justify-content:center;overflow:auto;padding:24px;z-index:9}
#lb img{max-width:100%;box-shadow:0 0 30px #000}#lb .cap{position:fixed;left:16px;bottom:12px;color:#fff;font-size:13px;background:#0008;padding:4px 10px;border-radius:6px}
footer{padding:10px 20px;color:var(--mut);font-size:12px}
"""

JS = """
const S={state:new Set(),src:new Set(),q:''};
function apply(){const cards=[...document.querySelectorAll('.card')];let shown=0;
 for(const c of cards){const ok=(!S.state.size||S.state.has(c.dataset.state))&&(!S.src.size||S.src.has(c.dataset.src))&&(!S.q||c.dataset.file.toLowerCase().includes(S.q));
  c.classList.toggle('hide',!ok); if(ok) shown++;}
 for(const s of document.querySelectorAll('section')){const n=[...s.querySelectorAll('.card:not(.hide)')].length;s.classList.toggle('hide',!n);s.querySelector('h2 small').textContent=n+' ảnh';}
 document.getElementById('count').textContent=shown;}
function toggle(set,v,el){set.has(v)?set.delete(v):set.add(v);el.classList.toggle('on');apply();}
document.getElementById('q').addEventListener('input',e=>{S.q=e.target.value.toLowerCase();apply();});
for(const el of document.querySelectorAll('[data-fstate]')) el.onclick=()=>toggle(S.state,el.dataset.fstate,el);
for(const el of document.querySelectorAll('[data-fsrc]')) el.onclick=()=>toggle(S.src,el.dataset.fsrc,el);
const lb=document.getElementById('lb'),lbi=lb.querySelector('img'),lbc=lb.querySelector('.cap');
for(const th of document.querySelectorAll('.th')) th.onclick=()=>{lbi.src=th.dataset.full;lbc.textContent=th.dataset.cap;lb.style.display='flex';};
lb.onclick=()=>{lb.style.display='none';lbi.src='';};
document.addEventListener('keydown',e=>{if(e.key==='Escape')lb.onclick();});
apply();
"""


def render(items: list[dict], title: str) -> str:
    screens = sorted({i["screen"] for i in items}, key=lambda s: (SCREEN_ORDER.index(s) if s in SCREEN_ORDER else 99, s))
    states = sorted({i["state"] for i in items})
    srcs = sorted({i["src"] for i in items})
    e = html.escape
    parts = [f"<!doctype html><html lang='vi'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>{e(title)}</title><style>{CSS}</style></head><body><header><h1>{e(title)}</h1>"
             f"<div class='f'><span>Trạng thái:</span>" + "".join(f"<button class='chip' data-fstate='{e(s)}'>{e(s)}</button>" for s in states) + "</div>"
             "<div class='f'><span>Nguồn:</span>" + "".join(f"<button class='chip' data-fsrc='{e(s)}'>{e(s)}</button>" for s in srcs) + "</div>"
             f"<input id='q' placeholder='lọc theo tên file…'><span><b id='count'>{len(items)}</b>/{len(items)} ảnh</span></header><main>"]
    for sc in screens:
        rows = [i for i in items if i["screen"] == sc]
        parts.append(f"<section data-screen='{e(sc)}'><h2>{e(sc)} <small>{len(rows)} ảnh</small></h2><div class='grid'>")
        for i in rows:
            cap = f"{i['src']}/{i['file']} · {i['kb']} KB · {i['mtime']}"
            parts.append(
                f"<div class='card' data-state='{e(i['state'])}' data-src='{e(i['src'])}' data-file='{e(i['file'])}'>"
                f"<div class='th' data-full='{e(i['rel'])}' data-cap='{e(cap)}'><img loading='lazy' src='{e(i['rel'])}' alt='{e(i['file'])}'></div>"
                f"<div class='cap'><b>{e(i['file'])}</b><span class='tag {e(i['state'])}'>{e(i['state'])}</span></div>"
                f"<div class='cap src'><span>{e(i['src'])}</span><span>{i['kb']} KB</span></div></div>")
        parts.append("</div></section>")
    parts.append(f"</main><div id='lb'><img alt=''><div class='cap'></div></div>"
                 f"<footer>Sinh lúc {time.strftime('%Y-%m-%d %H:%M')} · {len(items)} ảnh · {len(screens)} màn · bấm ảnh để xem gốc, Esc để đóng.</footer>"
                 f"<script>{JS}</script></body></html>")
    return "".join(parts)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="dirs", nargs="+", required=True, help="thư mục ảnh (nhiều)")
    ap.add_argument("--out", required=True, help="file index.html")
    ap.add_argument("--title", default="SecJIT GUI — ảnh chụp màn hình")
    ap.add_argument("--json", action="store_true", help="in danh sách ảnh dạng JSON ra stdout")
    a = ap.parse_args(argv)
    out = Path(a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    items = collect([Path(d).resolve() for d in a.dirs], out.parent)
    out.write_text(render(items, a.title), encoding="utf-8")
    if a.json:
        print(json.dumps(items, ensure_ascii=False, indent=1))
    by = {}
    for i in items:
        by.setdefault(i["src"], 0)
        by[i["src"]] += 1
    print(f"Gallery: {out}  ({len(items)} ảnh: " + ", ".join(f"{k}={v}" for k, v in sorted(by.items())) + ")")
    return 0 if items else 1


if __name__ == "__main__":
    sys.exit(main())
