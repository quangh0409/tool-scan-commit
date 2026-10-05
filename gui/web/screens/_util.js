// _util.js — helper DOM/format dùng chung cho các màn 6–10 (A5). Không phụ thuộc app.js.

/** Tạo element nhanh: h('div', {class:'x', text:'…', onclick}, child1, child2) */
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k === 'html') el.innerHTML = v;
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, String(v));
  }
  append(el, children);
  return el;
}

export function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function clear(el) {
  // replaceChildren() xoá nguyên tử — tránh 'removeChild: node is no longer a child' khi blur/change handler
  // tái render giữa chừng (REV-3). Fallback: kiểm parentNode trước khi gỡ.
  if (typeof el.replaceChildren === 'function') { el.replaceChildren(); return el; }
  let c = el.firstChild;
  while (c) { const nx = c.nextSibling; if (c.parentNode === el) el.removeChild(c); c = nx; }
  return el;
}

// ----------------------------------------------------------------------------- tích hợp khung A4
/** Bảo đảm screens.css được nạp khi index.html của A4 chưa import. */
export function ensureScreensCss() {
  if (typeof document === 'undefined') return;
  if (document.querySelector('link[href*="screens.css"]')) return;
  const base = (document.currentScript && document.currentScript.src) || '';
  const link = h('link', { rel: 'stylesheet', href: base ? new URL('screens.css', base).href : 'screens/screens.css' });
  link.dataset.a5 = '1';
  document.head.append(link);
}

function normErr(err) {
  if (!err) return { message: 'Lỗi không rõ' };
  if (err.error && typeof err.error === 'object') return { status: err.status || err.error.status, ...err.error };
  return err;
}

/** Bọc component của app.js (A4, `window.SecJIT`) về chữ ký A5 (CONTRACTS §10/§12). */
export function adaptSecJIT(S) {
  const kindMap = { default: '', primary: 'primary', danger: 'danger', ghost: 'ghost' };
  const toastKind = { ok: 'ok', error: 'bad', bad: 'bad', warn: 'warn', info: 'info' };
  return {
    btn({ label, kind = 'default', onClick, disabled = false, small = false, title, ariaLabel } = {}) {
      return S.btn(label, { kind: kindMap[kind] || kind, onClick: onClick ? (ev) => onClick(ev) : undefined, disabled, small, title, ariaLabel });
    },
    card(children, { title, extraClass } = {}) {
      const body = h('div', { class: `s-stack ${extraClass || ''}`.trim() });
      append(body, [children]);
      return S.card({ title, body, cls: extraClass });
    },
    table({ columns, rows, page = 1, size, total, onPage, onRow, rowKey, selected, emptyMsg } = {}) {
      const keyOf = rowKey || ((r) => r.cluster_key || r.commit || r.id || r.name || JSON.stringify(r));
      const wrap = S.table({ columns: columns.map((c) => ({ key: c.key, label: c.label, render: c.render })), rows: rows || [],
        page, size: size || 20, total, onPage, rowKey: keyOf, emptyMsg });
      if (onRow && rows && rows.length) {
        const byKey = new Map(rows.map((r) => [String(keyOf(r)), r]));
        for (const tr of wrap.querySelectorAll('tbody tr[data-key]')) {
          const r = byKey.get(tr.dataset.key);
          if (!r) continue;
          tr.classList.add('s-row-click');
          if (selected !== undefined && String(selected) === tr.dataset.key) tr.classList.add('s-row-sel');
          tr.tabIndex = 0; tr.setAttribute('role', 'button');
          tr.addEventListener('click', () => onRow(r));
          tr.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onRow(r); } });
        }
      }
      return wrap;
    },
    toast(msg, kind = 'info') { return S.toast(msg, toastKind[kind] || 'info'); },
    dialog({ title, body, confirmText, typedConfirm, onConfirm, cancelText, kind } = {}) {
      const listeners = [];
      const fake = { returnValue: '', addEventListener(type, fn) { if (type === 'close') listeners.push(fn); }, querySelector() { return null; }, close() {} };
      const fire = () => { for (const fn of listeners) { try { fn({ target: fake }); } catch (_) { /* bỏ qua */ } } };
      S.dialog({ title, body, confirmText, cancelText, typedConfirm, danger: kind === 'danger' }).then(async (ok) => {
        if (ok) {
          try { await (onConfirm && onConfirm(undefined)); fake.returnValue = 'ok'; } catch (e) { S.toast(errText(e), 'bad'); fake.returnValue = 'cancel'; }
        } else fake.returnValue = 'cancel';
        fire();
      });
      return fake;
    },
    empty(msg) { return S.empty(msg); },
    errorBox(err, onRetry) { return S.errorBox(normErr(err), onRetry); },
    skeleton(n = 4) { return S.skeleton(n, { lines: true }); },
    badgeLabel(label, evidence) {
      // Nhãn ÂM: wording bắt buộc (CONTRACTS §10) — badgeLabel của app.js chỉ biết gold/silver/candidate
      if (label === 'verified-clean') return h('span', { class: 'badge verified-clean', title: 'verified-clean · 2 tool đắt không báo — không phải chứng minh sạch', text: 'verified-clean · 2 tool đắt không báo' });
      if (label === 'cheap-clean') return h('span', { class: 'badge cheap-clean', title: 'cheap-clean · chỉ tool rẻ không báo, chưa qua tầng đắt', text: 'cheap-clean · chỉ tool rẻ' });
      return S.badgeLabel(label, evidence);
    },
  };
}

/** Component cho màn: ctx.components (harness/hợp đồng §12) → window.SecJIT (app.js A4) → lỗi rõ ràng. */
export function getComponents(ctx) {
  ensureScreensCss();
  if (ctx && ctx.components) return ctx.components;
  const S = typeof window !== 'undefined' ? window.SecJIT : null;
  if (S && typeof S.btn === 'function') {
    if (!S.__a5) S.__a5 = adaptSecJIT(S);
    return S.__a5;
  }
  throw new Error('Thiếu components: ctx.components (CONTRACTS §12) hoặc window.SecJIT (app.js)');
}

/** SSE: ctx.sse → window.SecJIT.sse → null. Trả hàm closer hoặc null. */
export function openSse(ctx, path, onLine, onEnd) {
  const fn = (ctx && typeof ctx.sse === 'function') ? ctx.sse : (typeof window !== 'undefined' && window.SecJIT && window.SecJIT.sse);
  if (typeof fn !== 'function') return null;
  const r = fn(path, onLine, { onEnd });
  if (typeof r === 'function') return r;
  if (r && typeof r.close === 'function') return () => r.close();
  return () => {};
}

/** t() có fallback: A4 trả về khoá khi thiếu -> dùng chuỗi tiếng Việt cục bộ. */
export function makeT(ctx) {
  return (key, fallback) => {
    try {
      const v = ctx && typeof ctx.t === 'function' ? ctx.t(key) : null;
      if (v && v !== key) return v;
    } catch (_) { /* bỏ qua */ }
    return fallback !== undefined ? fallback : key;
  };
}

export const fmt = {
  int(n) { return n === null || n === undefined ? '—' : Number(n).toLocaleString('vi-VN'); },
  num(n, d = 2) { return n === null || n === undefined || Number.isNaN(Number(n)) ? '—' : Number(n).toLocaleString('vi-VN', { maximumFractionDigits: d, minimumFractionDigits: d }); },
  pct(a, b) { if (!b) return '—'; return `${Math.round((a / b) * 100)} %`; },
  bytes(b) {
    if (b === null || b === undefined) return '—';
    const u = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0; let v = Number(b);
    while (v >= 1000 && i < u.length - 1) { v /= 1000; i++; }
    return `${v.toLocaleString('vi-VN', { maximumFractionDigits: v < 10 ? 1 : 0 })} ${u[i]}`;
  },
  dur(sec) {
    if (sec === null || sec === undefined || !Number.isFinite(sec)) return '—';
    sec = Math.max(0, Math.round(sec));
    const hh = Math.floor(sec / 3600); const mm = Math.floor((sec % 3600) / 60); const ss = sec % 60;
    if (hh) return `${hh} h ${String(mm).padStart(2, '0')} m`;
    if (mm) return `${mm} m ${String(ss).padStart(2, '0')} s`;
    return `${ss} s`;
  },
  time(iso) { if (!iso) return '—'; const d = new Date(iso); return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleString('vi-VN'); },
  hhmmss(iso) { if (!iso) return ''; const d = new Date(iso); return Number.isNaN(d.getTime()) ? '' : d.toTimeString().slice(0, 8); },
  sha(s) { return s ? String(s).slice(0, 8) : '—'; },
};

/** Tên hiển thị của repo: owner/repo từ URL. */
export function repoName(url) {
  if (!url) return '—';
  const m = String(url).replace(/\.git$/, '').match(/([^/:]+)\/([^/]+)$/);
  return m ? `${m[1]}/${m[2]}` : url;
}

/** Màu trạng thái commit/tool theo CONTRACTS §1. */
export const STATUS_CLASS = {
  ok: 'ok', done: 'ok', skipped: 'skipped', build_failed: 'bad', infra_error: 'infra',
  tool_timeout: 'warn', tool_error: 'warn', pending: 'muted', building: 'accent', analyzing: 'accent',
  running: 'accent', stopped: 'muted', failed: 'bad', interrupted: 'warn',
};
export const STATUS_LABEL = {
  ok: 'ok', done: 'xong', skipped: 'skipped', build_failed: 'build_failed', infra_error: 'infra_error',
  tool_timeout: 'tool_timeout', tool_error: 'tool_error',
  pending: 'chờ', building: 'đang build', analyzing: 'đang phân tích', running: 'đang chạy', stopped: 'đã dừng',
  failed: 'thất bại', interrupted: 'bị ngắt',
};
export const STATUS_HINT = {
  skipped: 'không có module Java → không build; không tính verified-clean', build_failed: 'Maven rc≠0 vì dữ liệu (dependency mất, compile lỗi)',
  infra_error: 'lỗi hạ tầng (Docker/đĩa/mạng) — commit về pending, không đếm là dữ liệu', tool_timeout: 'một tool vượt timeout',
  tool_error: 'tool crash/parse lỗi', interrupted: 'tiến trình nền chết khi DB còn building/analyzing',
};
export function statusTag(status) {
  const s = status || 'unknown';
  return h('span', { class: `s-tag st-${STATUS_CLASS[s] || 'muted'}`, title: STATUS_HINT[s] || s, text: STATUS_LABEL[s] || s });
}

/** Ghi chú "partial": backend trả thiếu trường. */
export function partialNote(fields) {
  if (!fields || fields.length === 0) return null;
  return h('div', { class: 's-banner warn', role: 'status' },
    h('strong', { text: 'Dữ liệu chưa đầy đủ' }), ' — backend chưa trả: ',
    h('code', { text: fields.join(', ') }), '. Các khối liên quan hiện "—".');
}

export function banner(kind, title, body, actions) {
  const b = h('div', { class: `s-banner ${kind}`, role: kind === 'bad' ? 'alert' : 'status' },
    h('div', { class: 's-banner-text' }, h('strong', { text: title }), body ? h('div', { text: body }) : null));
  if (actions && actions.length) b.append(h('div', { class: 's-banner-actions' }, actions));
  return b;
}

export function kv(label, value, { mono = false } = {}) {
  return h('div', { class: 's-kv' }, h('span', { class: 's-kv-k', text: label }), h('span', { class: `s-kv-v ${mono ? 's-mono' : ''}`.trim() }, value));
}

/** Thanh ngang phân đoạn: segs=[{label, value, cls}] — nhãn trực tiếp + legend để không dựa màu đơn thuần. */
export function segBar(segs, total, { height = 12, legend = true, fmtVal = fmt.int } = {}) {
  const t = total || segs.reduce((a, s) => a + (s.value || 0), 0) || 1;
  const bar = h('div', { class: 's-segbar', style: { height: `${height}px` }, role: 'img', 'aria-label': segs.map((s) => `${s.label} ${s.value}`).join(', ') });
  for (const s of segs) {
    if (!s.value) continue;
    bar.append(h('span', { class: `seg-${s.cls || 'accent'}`, style: { width: `${(s.value / t) * 100}%` }, title: `${s.label}: ${s.value}` }));
  }
  if (!legend) return bar;
  const lg = h('div', { class: 's-legend' }, segs.map((s) => h('span', {}, h('i', { class: `seg-${s.cls || 'accent'}` }), `${s.label} `, h('b', { class: 's-mono', text: fmtVal(s.value) }))));
  return h('div', { class: 's-segbar-wrap' }, bar, lg);
}

/** Debounce đơn giản. */
export function debounce(fn, ms = 300) {
  let id = null;
  return (...a) => { clearTimeout(id); id = setTimeout(() => fn(...a), ms); };
}

/** Gọi API, trả {ok, data} | {ok:false, err}; nhận diện 501/404 để toast "chưa hỗ trợ". */
export async function tryApi(ctx, path, opts) {
  try { return { ok: true, data: await ctx.api(path, opts) }; } catch (err) { return { ok: false, err, status: errStatus(err) }; }
}
export function errStatus(err) { return (err && (err.status || (err.error && err.error.status))) || 0; }
export function errText(err) {
  if (!err) return 'Lỗi không rõ';
  if (typeof err === 'string') return err;
  const e = err.error || err;
  return [e.code, e.message || err.message].filter(Boolean).join(' · ') || String(err);
}

/** TC-15: POST /api/results/:id/rescan {commits[]} — 1 commit đồng bộ, nhiều → nền (202). Trả true nếu đã gửi. */
export async function rescanCommits(ctx, C, id, shas, { tools, onDone } = {}) {
  const list = [].concat(shas).filter(Boolean);
  if (!list.length) return false;
  C.toast(`Đang quét lại ${list.length} commit (tầng rẻ)…`, 'info');
  const r = await tryApi(ctx, `/api/results/${encodeURIComponent(id)}/rescan`, { method: 'POST', body: tools ? { commits: list, tools } : { commits: list } });
  if (!r.ok) {
    const st = errStatus(r.err);
    C.toast(st === 501 || st === 404 ? 'Backend chưa hỗ trợ quét lại (cần CLI `rescan` của A2)' : st === 409 ? `Không quét lại được: ${errText(r.err)}` : errText(r.err), st === 409 ? 'error' : 'warn');
    return false;
  }
  const d = r.data || {};
  if (d.mode === 'background') C.toast(`Quét lại ${list.length} commit chạy nền (pid ${d.pid || '?'}) — xem ${d.log || 'log'}`, 'ok');
  else if (d.infra) C.toast(`Quét lại gặp infra_error (Docker/đĩa) — ${d.note || ''}`, 'error');
  else {
    const res = (d.results || [])[0] || {};
    C.toast(`Đã quét lại ${fmt.sha(list[0])}: ${fmt.int(res.findings)} finding → ${fmt.int(res.clusters)} cụm · xoá ${fmt.int(res.errors_cleared)} lỗi tool`, 'ok');
  }
  if (onDone) onDone(d);
  return true;
}

export function toolErrorsTag(errs) {
  if (!errs || !errs.length) return null;
  const txt = errs.map((e) => `${e.tool}: ${e.kind}${e.msg ? ' — ' + String(e.msg).slice(0, 120) : ''}`).join('\n');
  return h('span', { class: 's-tag st-warn', style: { whiteSpace: 'normal' }, title: txt, text: [...new Set(errs.map((e) => e.tool))].join(', ') });
}

export function qs(obj) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(obj)) if (v !== undefined && v !== null && v !== '') p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : '';
}

/** Tab bar (button, ≥44px). */
export function tabs(items, active, onPick) {
  return h('div', { class: 's-tabs', role: 'tablist' }, items.map((it) => h('button', {
    type: 'button', role: 'tab', class: `s-tab ${it.id === active ? 'on' : ''}`.trim(), 'aria-selected': it.id === active ? 'true' : 'false',
    onclick: () => onPick(it.id),
  }, it.label, it.count !== undefined ? h('span', { class: 's-tag', text: String(it.count) }) : null)));
}

export function field(labelText, input, hint) {
  const id = input.id || `f-${Math.random().toString(36).slice(2, 8)}`;
  input.id = id;
  return h('div', { class: 's-field' }, h('label', { for: id, text: labelText }), input, hint ? h('small', { text: hint }) : null);
}

/** Đầu trang Results dùng chung cho 4 tab + Kiểm tay. */
export function resultsHeader(ctx, id, active, run) {
  const name = run ? `${repoName(run.repo)} / ${run.branch || '—'}` : id;
  const items = [
    { id: 'overview', label: 'Tổng quan' }, { id: 'findings', label: 'Finding' }, { id: 'commits', label: 'Commit' },
    { id: 'review', label: 'Kiểm tay' }, { id: 'export', label: 'Xuất' },
  ];
  const head = h('div', { class: 's-row s-head' },
    h('h1', {}, 'Kết quả · ', h('span', { class: 's-branch', text: name })),
    run ? statusTag(run.status) : null,
    h('span', { class: 's-sub s-mono', text: id }));
  const bar = tabs(items, active, (tab) => ctx.navigate(tab === 'review' ? `#/review/${id}` : `#/results/${id}/${tab}`));
  return h('div', { class: 's-stack' }, head, bar);
}

/** Lấy run từ registry (không bắt buộc). */
export async function findRun(ctx, id) {
  const r = await tryApi(ctx, '/api/runs');
  if (!r.ok) return null;
  return ((r.data && r.data.runs) || []).find((x) => x.run_id === id) || null;
}

export function select(options, value, onChange, ariaLabel) {
  const s = h('select', { class: 's-select', 'aria-label': ariaLabel });
  for (const o of options) s.append(h('option', { value: o.value, selected: o.value === value ? true : null, text: o.label }));
  if (onChange) s.addEventListener('change', () => onChange(s.value));
  return s;
}
