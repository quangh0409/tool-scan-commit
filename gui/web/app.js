/* SecJIT Scan — khung ứng dụng (CONTRACTS §10). Vanilla ES2020, không framework, không CDN.
 *
 * Mỗi màn là một module `screens/<tên>.js` export `render(root, ctx)` (có thể async) và `destroy()`.
 * Đăng ký route: thêm MỘT dòng vào bảng ROUTES bên dưới (A5 chỉ cần thêm dòng + file screens/<tên>.js).
 * ctx = { params, query, state, navigate, api, t, route }.
 * Mọi component dùng chung export từ đây và cũng gắn vào window.SecJIT để debug.
 */

// ====================================================================================
// ROUTES — mỗi route một dòng. path: 'a/:id/b'; screen: tên file trong screens/; chrome: app|wizard|bare
// ====================================================================================
export const ROUTES = [
  { path: 'preflight',                 screen: 'preflight',          chrome: 'bare',   title: 'route.preflight' },
  { path: 'home',                      screen: 'home',               chrome: 'app',    title: 'route.home',     nav: 'home' },
  { path: 'wizard/1',                  screen: 'wizard1',            chrome: 'wizard', title: 'route.wizard',   step: 1 },
  { path: 'wizard/2',                  screen: 'wizard2',            chrome: 'wizard', title: 'route.wizard',   step: 2 },
  { path: 'wizard/3',                  screen: 'wizard3',            chrome: 'wizard', title: 'route.wizard',   step: 3 },
  { path: 'wizard/4',                  screen: 'wizard4',            chrome: 'wizard', title: 'route.wizard',   step: 4 },
  { path: 'wizard/5',                  screen: 'wizard5',            chrome: 'wizard', title: 'route.wizard',   step: 5 },
  // ---- A5 (màn 6–10): thêm dòng ở đây, file screens/<screen>.js ----
  { path: 'run/:id',                   screen: 'dashboard',          chrome: 'app',    title: 'route.run',      nav: 'home' },
  { path: 'results/:id',               redirect: 'results/:id/overview' },
  { path: 'results/:id/overview',      screen: 'results_overview',   chrome: 'app',    title: 'route.results',  nav: 'home' },
  { path: 'results/:id/findings',      screen: 'results_findings',   chrome: 'app',    title: 'route.results',  nav: 'home' },
  { path: 'results/:id/commits',       screen: 'results_commits',    chrome: 'app',    title: 'route.results',  nav: 'home' },
  { path: 'results/:id/export',        screen: 'results_export',     chrome: 'app',    title: 'route.results',  nav: 'home' },
  { path: 'review/:id',                screen: 'review',             chrome: 'app',    title: 'route.review',   nav: 'home' },
  { path: 'settings',                  redirect: 'settings/docker' },
  { path: 'settings/:tab',             screen: 'settings',           chrome: 'app',    title: 'route.settings', nav: 'settings' },
];

export const NAV = [
  { id: 'home',      href: '#/home',             label: 'nav.home',      icon: '⌂' },
  { id: 'new',       href: '#/wizard/1',         label: 'nav.new',       icon: '＋' },
  { id: 'settings',  href: '#/settings/docker',  label: 'nav.settings',  icon: '⚙' },
  { id: 'preflight', href: '#/preflight',        label: 'nav.preflight', icon: '✓' },
];

export const WIZARD_STEPS = ['wiz.step1', 'wiz.step2', 'wiz.step3', 'wiz.step4', 'wiz.step5'];

// ====================================================================================
// Token & API
// ====================================================================================
const TOKEN_KEY = 'secjit.token';
let TOKEN = '';

function initToken() {
  const u = new URL(location.href);
  const t = u.searchParams.get('t');
  if (t) {
    try { sessionStorage.setItem(TOKEN_KEY, t); } catch (_) { /* private mode */ }
    TOKEN = t;
    u.searchParams.delete('t');
    history.replaceState(null, '', u.pathname + (u.search || '') + u.hash);
  } else {
    try { TOKEN = sessionStorage.getItem(TOKEN_KEY) || ''; } catch (_) { TOKEN = ''; }
  }
}
export function token() { return TOKEN; }

export class ApiError extends Error {
  constructor(status, code, message, hint) {
    super(message || code || `HTTP ${status}`);
    this.status = status; this.code = code || 'error'; this.hint = hint || '';
    // §12 (A5): lỗi reject dạng {status, error:{code,message,hint}} — giữ cả hai hình dạng
    this.error = { code: this.code, message: this.message, hint: this.hint, status };
  }
}

/** URL tuyệt đối kèm token (cho <a download>, EventSource…). */
export function apiUrl(path) {
  const u = new URL(path, location.origin);
  u.searchParams.set('t', TOKEN);
  const st = currentRoute && currentRoute.query && currentRoute.query.state;
  if (st && !u.searchParams.has('state')) u.searchParams.set('state', st);
  return u.toString();
}

/** Gọi API JSON. Tự gắn X-Token, chuyển tiếp ?state= của route (mock QA), parse lỗi {error:{...}}.
 *  opts.raw=true -> trả text thô (vd /raw?path=). */
export async function api(path, opts = {}) {
  const { method = 'GET', body, query, timeout = 60000, signal, raw = false } = opts;
  const url = new URL(path, location.origin);
  if (query) for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v);
  const st = currentRoute && currentRoute.query && currentRoute.query.state;
  if (st && !url.searchParams.has('state')) url.searchParams.set('state', st);
  const headers = { 'X-Token': TOKEN };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeout);
  if (signal) signal.addEventListener('abort', () => ctl.abort());
  let res;
  try {
    res = await fetch(url, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined, signal: ctl.signal });
  } catch (e) {
    clearTimeout(timer);
    if (e.name === 'AbortError') throw new ApiError(0, 'timeout', t('err.timeout'), t('err.timeout_hint'));
    throw new ApiError(0, 'network', t('err.network'), t('err.network_hint'));
  }
  clearTimeout(timer);
  const ctype = res.headers.get('Content-Type') || '';
  if (!ctype.includes('json')) {
    if (!res.ok) throw new ApiError(res.status, 'http_' + res.status, res.statusText, '');
    return raw ? await res.text() : res;
  }
  if (raw) return await res.text();
  let data = null;
  try { data = await res.json(); } catch (_) { data = null; }
  if (!res.ok) {
    const e = (data && data.error) || {};
    if (res.status === 401) { try { sessionStorage.removeItem(TOKEN_KEY); } catch (_) { /* ignore */ } }
    throw new ApiError(res.status, e.code || 'http_' + res.status, e.message || res.statusText, e.hint || '');
  }
  return data;
}

/** SSE: EventSource không gửi header -> dùng ?t=. Trả closer() (gọi được như hàm, có .close() và .source). */
export function sse(path, onMessage, { onEnd, onError } = {}) {
  const es = new EventSource(apiUrl(path));
  es.onmessage = (ev) => { try { onMessage(JSON.parse(ev.data)); } catch (_) { onMessage({ raw: ev.data }); } };
  es.addEventListener('end', () => { es.close(); if (onEnd) onEnd(); });
  es.onerror = (ev) => { if (onError) onError(ev); };
  const closer = () => es.close();
  closer.close = closer;
  closer.source = es;
  return closer;
}

// ====================================================================================
// i18n
// ====================================================================================
const LANG_KEY = 'secjit.lang';
let LANG = 'vi';
const DICT = { vi: {}, en: {} };

export function lang() { return LANG; }
export async function loadI18n() {
  for (const l of ['vi', 'en']) {
    try { DICT[l] = await (await fetch(`i18n/${l}.json`, { cache: 'no-cache' })).json(); } catch (_) { DICT[l] = {}; }
  }
  // chuỗi màn 6–10 (A5): khoá phẳng, gộp vào VI (EN rơi về VI)
  try { Object.assign(DICT.vi, await (await fetch('i18n/vi_screens.json', { cache: 'no-cache' })).json()); } catch (_) { /* không có */ }
  try { LANG = localStorage.getItem(LANG_KEY) || 'vi'; } catch (_) { LANG = 'vi'; }
}
export function setLang(l) {
  LANG = l;
  try { localStorage.setItem(LANG_KEY, l); } catch (_) { /* ignore */ }
  document.documentElement.lang = l;
  route();
}
/** t(key, vars): thiếu khoá -> trả chính key (để QA bắt). EN rỗng -> rơi về VI. */
export function t(key, vars) {
  let s = DICT[LANG] && DICT[LANG][key];
  if (s === undefined || s === '') s = DICT.vi[key];
  if (s === undefined) return key;
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.split('{' + k + '}').join(String(v));
  return s;
}

// ====================================================================================
// DOM helpers
// ====================================================================================
export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k === 'html') el.innerHTML = v;
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, v);
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
export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
export function debounce(fn, ms) { let id; return (...a) => { clearTimeout(id); id = setTimeout(() => fn(...a), ms); }; }
export const fmt = {
  bytes(b) { if (b === null || b === undefined) return '—'; const u = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0; let v = Number(b); while (v >= 1000 && i < u.length - 1) { v /= 1000; i++; } return `${v < 10 && i > 0 ? v.toFixed(1) : Math.round(v)} ${u[i]}`; },
  minutes(m) { if (m === null || m === undefined || isNaN(m)) return '—'; m = Math.round(m); if (m < 60) return `${m} ${t('unit.min')}`; const hh = Math.floor(m / 60); const mm = m % 60; return mm ? `${hh} ${t('unit.h')} ${mm} ${t('unit.min')}` : `${hh} ${t('unit.h')}`; },
  num(n) { if (n === null || n === undefined) return '—'; return Number(n).toLocaleString(LANG === 'vi' ? 'vi-VN' : 'en-US'); },
  date(s) { if (!s) return '—'; return String(s).replace('T', ' ').slice(0, 16); },
  repoShort(url) { const m = /github\.com\/([^/]+)\/([^/]+)/i.exec(url || ''); return m ? `${m[1]}/${m[2]}` : (url || '—'); },
};

// ====================================================================================
// Components
// ====================================================================================
export function btn(label, o = {}) {
  const cls = ['btn', o.kind || '', o.small ? 'small' : '', o.icon ? 'icon' : '', o.cls || ''].filter(Boolean).join(' ');
  const el = o.href
    ? h('a', { class: cls, href: o.href, 'aria-label': o.ariaLabel, 'aria-disabled': o.disabled ? 'true' : undefined, title: o.title })
    : h('button', { class: cls, type: o.type || 'button', disabled: !!o.disabled, 'aria-label': o.ariaLabel, title: o.title });
  if (o.spinner) el.append(h('span', { class: 'spin', 'aria-hidden': 'true' }));
  if (label !== undefined && label !== null) el.append(typeof label === 'string' ? document.createTextNode(label) : label);
  if (o.onClick) el.addEventListener('click', (ev) => { if (o.href && o.disabled) { ev.preventDefault(); return; } o.onClick(ev, el); });
  return el;
}
/** Nút async: khoá + spinner trong lúc chờ promise. */
export function busy(el, on) {
  if (on) { el.disabled = true; el.dataset.busy = '1'; el.prepend(h('span', { class: 'spin', 'aria-hidden': 'true' })); }
  else { el.disabled = false; delete el.dataset.busy; const s = el.querySelector('.spin'); if (s) s.remove(); }
}

export function card({ title, subtitle, actions, body, footer, cls, list } = {}) {
  const el = h('section', { class: ['card', cls || '', list ? 'card-list' : ''].filter(Boolean).join(' ') });
  if (title || actions) {
    const hd = h('div', { class: 'card-h' }, typeof title === 'string' ? h('h2', {}, title) : title);
    if (subtitle) hd.append(h('span', { class: 'muted small' }, subtitle));
    if (actions) hd.append(...[].concat(actions));
    el.append(hd);
  }
  if (body !== undefined) el.append(list ? h('div', { class: 'card-list-b' }, body) : h('div', { class: 'card-b' }, body));
  if (footer) el.append(h('div', { class: 'card-f' }, footer));
  return el;
}

/** table: thêm onRow/rowKey/selected/emptyMsg theo §12 (A5). Bấm/Enter dòng -> onRow(row). */
export function table({ columns, rows, page = 1, size = 20, total, onPage, onRow, rowKey, selected, emptyMsg, cls }) {
  const wrap = h('div', { class: ['tbl-wrap', cls || ''].join(' ') });
  const tbl = h('table', { class: 'tbl' });
  tbl.append(h('thead', {}, h('tr', {}, columns.map(c => h('th', { scope: 'col', class: c.num ? 'num' : '', style: c.width ? { width: c.width } : undefined }, t(c.label))))));
  const tb = h('tbody');
  if (!rows || !rows.length) {
    tb.append(h('tr', {}, h('td', { colspan: columns.length }, empty(emptyMsg || t('empty.rows')))));
  } else {
    for (const r of rows) {
      const key = rowKey ? rowKey(r) : undefined;
      const tr = h('tr', { 'data-key': key, class: [onRow ? 'clickable' : '', selected !== undefined && key === selected ? 'sel' : ''].join(' ').trim() || undefined });
      if (onRow) {
        tr.tabIndex = 0; tr.setAttribute('role', 'button');
        tr.addEventListener('click', () => onRow(r));
        tr.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onRow(r); } });
      }
      for (const c of columns) {
        const v = c.render ? c.render(r) : r[c.key];
        tr.append(h('td', { class: [c.num ? 'num' : '', c.cls || ''].join(' ') }, v === undefined || v === null ? '—' : v));
      }
      tb.append(tr);
    }
  }
  tbl.append(tb);
  wrap.append(tbl);
  if (total !== undefined && total > size) {
    const pages = Math.max(1, Math.ceil(total / size));
    wrap.append(h('div', { class: 'pager' },
      h('span', {}, t('pager.of', { from: (page - 1) * size + 1, to: Math.min(total, page * size), total: fmt.num(total) })),
      btn('‹', { small: true, ariaLabel: t('pager.prev'), disabled: page <= 1, onClick: () => onPage && onPage(page - 1) }),
      h('span', {}, `${page} / ${pages}`),
      btn('›', { small: true, ariaLabel: t('pager.next'), disabled: page >= pages, onClick: () => onPage && onPage(page + 1) })));
  }
  return wrap;
}

export function stepper(steps, current, { linkTo } = {}) {
  const ol = h('ol');
  steps.forEach((s, i) => {
    const n = i + 1;
    const cls = n < current ? 'done' : n === current ? 'current' : '';
    const inner = [h('span', { class: 'num', 'aria-hidden': 'true' }, n < current ? '✓' : String(n)), h('span', {}, t(s))];
    const li = h('li', { class: cls, 'aria-current': n === current ? 'step' : undefined });
    if (linkTo && n < current) li.append(h('a', { href: linkTo(n) }, inner)); else li.append(...inner);
    ol.append(li);
  });
  return h('nav', { class: 'stepper', 'aria-label': t('wiz.steps') }, ol);
}

export function toast(msg, kind = 'info', ms = 4500) {
  const host = document.getElementById('toasts');
  const el = h('div', { class: `toast ${kind}`, role: 'status' }, h('span', { class: 'grow' }, msg),
    btn('✕', { ariaLabel: t('close'), cls: 'ghost', onClick: () => el.remove() }));
  el.querySelector('.btn').style.color = '#fff';
  host.append(el);
  if (ms > 0) setTimeout(() => el.remove(), ms);
  return el;
}

/** dialog({title, body, confirmText, cancelText, typedConfirm, danger, fields}) -> Promise<false|true|{values}> */
export function dialog({ title, body, confirmText, cancelText, typedConfirm, danger, hideCancel, fields } = {}) {
  return new Promise((resolve) => {
    const host = document.getElementById('dialogs');
    const back = h('div', { class: 'dlg-back', role: 'presentation' });
    const dlg = h('div', { class: 'dlg card', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'dlg-title' });
    const bodyEl = h('div', { class: 'card-b' });
    if (body) bodyEl.append(typeof body === 'string' ? h('p', {}, body) : body);
    const inputs = {};
    if (fields) for (const f of fields) {
      const inp = h(f.textarea ? 'textarea' : 'input', { class: 'input', id: 'dlg-f-' + f.name, type: f.type || 'text', value: f.textarea ? undefined : (f.value || ''), placeholder: f.placeholder || '' });
      if (f.textarea && f.value) inp.value = f.value;
      inputs[f.name] = inp;
      bodyEl.append(h('label', { class: 'field', for: 'dlg-f-' + f.name }, h('span', {}, f.label), inp, f.help ? h('div', { class: 'help' }, f.help) : null));
    }
    let typed = null;
    if (typedConfirm) {
      typed = h('input', { class: 'input mono', id: 'dlg-typed', autocomplete: 'off', spellcheck: 'false' });
      bodyEl.append(h('label', { class: 'field', for: 'dlg-typed' },
        h('span', {}, t('dialog.type_to_confirm', { text: typedConfirm })), typed));
    }
    const ok = btn(confirmText || t('ok'), { kind: danger ? 'danger' : 'primary', disabled: !!typedConfirm });
    const cancel = btn(cancelText || t('cancel'));
    const close = (v) => { back.remove(); document.removeEventListener('keydown', onKey); resolve(v); };
    const onKey = (e) => { if (e.key === 'Escape') close(false); };
    const validate = () => {
      let good = true;
      if (typed) good = typed.value.trim() === typedConfirm;
      if (fields) for (const f of fields) if (f.required && !inputs[f.name].value.trim()) good = false;
      if (fields) for (const f of fields) if (f.minLen && inputs[f.name].value.trim().length < f.minLen) good = false;
      ok.disabled = !good;
    };
    if (typed) typed.addEventListener('input', validate);
    if (fields) for (const f of fields) inputs[f.name].addEventListener('input', validate);
    if (fields) validate();
    ok.addEventListener('click', () => {
      if (fields) { const values = {}; for (const [k, inp] of Object.entries(inputs)) values[k] = inp.value.trim(); close({ values }); }
      else close(true);
    });
    cancel.addEventListener('click', () => close(false));
    back.addEventListener('click', (e) => { if (e.target === back) close(false); });
    document.addEventListener('keydown', onKey);
    dlg.append(h('div', { class: 'card-h' }, h('h2', { id: 'dlg-title' }, title || '')), bodyEl,
      h('div', { class: 'card-f' }, hideCancel ? null : cancel, ok));
    back.append(dlg);
    host.append(back);
    setTimeout(() => { const f = typed || (fields && inputs[fields[0].name]) || ok; f.focus(); }, 0);
  });
}

/** dialogEl — chữ ký A5/_shim (§12): {title, body, confirmText, typedConfirm, onConfirm, cancelText, kind} -> <dialog> native.
 *  returnValue 'ok' | 'cancel'; onConfirm throw -> toast lỗi, dialog mở lại nút. */
export function dialogEl({ title, body, confirmText, typedConfirm, onConfirm, cancelText, kind = 'primary' } = {}) {
  const dlg = h('dialog', { class: 'dlg-native' });
  const inner = h('div', { class: 'dlg card' }, h('div', { class: 'card-h' }, h('h2', {}, title || '')));
  const bodyEl = h('div', { class: 'card-b' });
  if (body) bodyEl.append(typeof body === 'string' ? h('p', {}, body) : body);
  let input = null;
  if (typedConfirm) {
    input = h('input', { class: 'input mono', id: 'dlg-typed-' + Math.random().toString(36).slice(2, 8), autocomplete: 'off', spellcheck: 'false' });
    bodyEl.append(h('label', { class: 'field', for: input.id }, h('span', {}, t('dialog.type_to_confirm', { text: typedConfirm })), input));
  }
  const ok = btn(confirmText || t('ok'), { kind: kind === 'danger' ? 'danger' : 'primary', disabled: !!typedConfirm });
  const cancel = btn(cancelText || t('cancel'), { onClick: () => dlg.close('cancel') });
  if (input) input.addEventListener('input', () => { ok.disabled = input.value.trim() !== typedConfirm; });
  ok.addEventListener('click', async () => {
    ok.disabled = true;
    try { await (onConfirm && onConfirm(input ? input.value : undefined)); dlg.close('ok'); }
    catch (e) { ok.disabled = false; toast((e && (e.message || (e.error && e.error.message))) || String(e), 'bad'); }
  });
  inner.append(bodyEl, h('div', { class: 'card-f' }, cancel, ok));
  dlg.append(inner);
  dlg.addEventListener('close', () => dlg.remove());
  dlg.addEventListener('cancel', (e) => { e.preventDefault(); dlg.close('cancel'); });
  document.body.append(dlg);
  dlg.showModal();
  setTimeout(() => (input || ok).focus(), 0);
  return dlg;
}

/** ctx.components — chữ ký A5 (_shim.js / CONTRACTS §12) bọc component của khung này. */
export const components = {
  btn({ label, kind = 'default', onClick, disabled = false, small = false, title, ariaLabel, href } = {}) {
    return btn(label, { kind: kind === 'default' ? '' : kind, onClick, disabled, small, title, ariaLabel, href });
  },
  card(children, { title, extraClass, subtitle, actions } = {}) {
    const kids = [].concat(children === undefined || children === null ? [] : children).flat(Infinity).filter(x => x !== null && x !== undefined && x !== false);
    return card({ title, subtitle, actions, body: kids.length ? h('div', { class: 'stack' }, kids) : undefined, cls: extraClass });
  },
  table(opts) { return table(Object.assign({}, opts, { columns: (opts.columns || []).map(c => Object.assign({}, c, { label: c.label })) })); },
  toast(msg, kind = 'info') { return toast(msg, kind === 'error' ? 'bad' : kind); },
  dialog: dialogEl,
  empty(msg) { return empty(msg || t('empty.rows')); },
  errorBox, skeleton, badgeLabel, notice, progress, h,
};

export function empty(msg, { action, icon } = {}) {
  return h('div', { class: 'empty' }, h('div', { class: 'ico', 'aria-hidden': 'true' }, icon || '○'), h('p', {}, msg), action || null);
}

export function errorBox(err, onRetry, { retryLabel } = {}) {
  const e = err || {};
  const code = e.code ? `[${e.code}${e.status ? ' · HTTP ' + e.status : ''}] ` : '';
  return h('div', { class: 'errorbox', role: 'alert' },
    h('span', { class: 'mark bad', 'aria-hidden': 'true' }, '!'),
    h('div', { class: 'grow' },
      h('div', {}, h('strong', {}, code), e.message || String(err || t('err.unknown'))),
      e.hint ? h('div', { class: 'hint' }, e.hint) : null),
    onRetry ? btn(retryLabel || t('retry'), { small: true, onClick: onRetry }) : null);
}

export function skeleton(n = 3, { lines = false } = {}) {
  const wrap = h('div', { class: 'skel-rows', 'aria-busy': 'true', 'aria-label': t('loading') });
  for (let i = 0; i < n; i++) {
    if (lines) wrap.append(h('div', { class: 'skel', style: { margin: '10px 0', width: `${60 + ((i * 17) % 40)}%` } }));
    else wrap.append(h('div', { class: 'item' }, h('span', { class: 'skel circle' }),
      h('div', { class: 'grow' }, h('div', { class: 'skel', style: { width: `${45 + ((i * 23) % 40)}%` } }),
        h('div', { class: 'skel', style: { width: '30%', marginTop: '8px' } }))));
  }
  return wrap;
}

/** badgeLabel(label, evidence): evidence = {consensus, validation} hoặc chuỗi validation. */
export function badgeLabel(label, evidence) {
  const lab = (label || (evidence && evidence.consensus) || 'candidate').toLowerCase();
  const val = typeof evidence === 'string' ? evidence : (evidence && evidence.validation) || 'unreviewed';
  let suffix;
  if (val === 'TP') suffix = '✓ TP';
  else if (val === 'FP') suffix = '✗ FP';
  else if (val === 'unclear') suffix = '? ' + t('badge.unclear');
  else suffix = '· ' + t('badge.machine');
  const title = t('badge.title.' + (val === 'TP' || val === 'FP' || val === 'unclear' ? val : 'unreviewed'));
  return h('span', { class: `badge ${lab}`, title }, `${lab} ${suffix}`);
}
export function badgeStatus(status) {
  const s = (status || 'unknown').toLowerCase();
  return h('span', { class: `badge ${s}` }, t('status.' + s));
}
export function notice(kind, content, { action } = {}) {
  const icon = { ok: '✓', warn: '⚠', bad: '✕', fix: '🔧', info: 'i' }[kind] || 'i';
  return h('div', { class: `notice ${kind}`, role: kind === 'bad' ? 'alert' : undefined },
    h('span', { class: `mark ${kind === 'info' ? 'pending' : kind}`, 'aria-hidden': 'true' }, icon),
    h('div', { class: 'grow' }, content), action || null);
}
export function progress(pct, kind = '') {
  const p = Math.max(0, Math.min(100, Number(pct) || 0));
  return h('div', { class: `prog ${kind}`, role: 'progressbar', 'aria-valuenow': String(Math.round(p)), 'aria-valuemin': '0', 'aria-valuemax': '100' },
    h('i', { style: { width: p + '%' } }));
}
export async function copyText(text) {
  try { await navigator.clipboard.writeText(text); toast(t('copied'), 'ok', 2000); return true; } catch (_) {
    const ta = h('textarea', { style: { position: 'fixed', left: '-9999px' } }); ta.value = text; document.body.append(ta); ta.select();
    try { document.execCommand('copy'); toast(t('copied'), 'ok', 2000); } catch (e) { toast(t('copy_failed'), 'bad'); } ta.remove(); return false;
  }
}

// ====================================================================================
// Wizard store (sessionStorage) + port JS của orchestrator/profile.py & keys.py
// ====================================================================================
export const PARAMS_V1 = { line_window: 3, gold_min_expensive: 2, gold_allow_1exp_1cheap: 1, silver_min_cheap: 2, noise_cwe: ['CWE-117'] };
export const CHEAP_TOOLS_ALL = ['gitleaks', 'trufflehog', 'semgrep', 'bearer', 'horusec'];
export const EXPENSIVE_TOOLS_ALL = ['findsecbugs', 'sonar', 'codeql'];
const WKEY = 'secjit.wizard.profile';
const MKEY = 'secjit.wizard.meta';
function sget(k) { try { const v = sessionStorage.getItem(k); return v ? JSON.parse(v) : null; } catch (_) { return null; } }
function sset(k, v) { try { if (v === null) sessionStorage.removeItem(k); else sessionStorage.setItem(k, JSON.stringify(v)); } catch (_) { /* ignore */ } }

export const wiz = {
  canonRepo(url) {
    let u = (url || '').trim().replace(/\/+$/, '');
    if (u.endsWith('.git')) u = u.slice(0, -4);
    if (u.startsWith('git@github.com:')) u = 'https://github.com/' + u.slice('git@github.com:'.length);
    if (/^ssh:\/\/git@github\.com\//i.test(u)) u = 'https://github.com/' + u.replace(/^ssh:\/\/git@github\.com\//i, '');
    if (u.startsWith('http://')) u = 'https://' + u.slice(7);
    if (/^(www\.)?github\.com\//i.test(u)) u = 'https://' + u.replace(/^www\./i, '');
    let parts = u.split('/');
    if (parts.length >= 6 && /github\.com$/i.test(parts[2]) && ['tree', 'commit', 'pull', 'blob', 'commits', 'compare', 'issues', 'releases', 'actions'].includes(parts[5])) u = parts.slice(0, 5).join('/');
    parts = u.split('/');
    if (parts.length >= 3) { parts[2] = parts[2].toLowerCase(); u = parts.join('/'); }
    return u;
  },
  isGithub(url) { return /^https:\/\/github\.com\/[^/\s]+\/[^/\s]+$/.test(this.canonRepo(url)); },
  branchHint(url) { const m = /github\.com\/[^/]+\/[^/]+\/(?:tree|commits)\/([^/?#]+)/.exec((url || '').trim()); return m ? decodeURIComponent(m[1]) : null; },
  slug(url) { const p = this.canonRepo(url).split('/').filter(Boolean); return p.length >= 2 ? `${p[p.length - 2]}__${p[p.length - 1]}` : (p[p.length - 1] || 'repo'); },
  stamp() { const d = new Date(); return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`; },
  defaultProfile(repo = '', branch = '') {
    return { schema: 1, repo, branch, scope: { mode: 'count', since: null, until: null, max: 50, from_sha: null, to_sha: null },
      include_clean: true, cheap_tools: [...CHEAP_TOOLS_ALL], expensive_tools: ['findsecbugs', 'sonar'], codeql: false,
      workers: { scan: 4, expensive: 1 }, paths: { db: '', export: '', work: '' }, sonar_port: 9000, experiment: null,
      params_v1: JSON.parse(JSON.stringify(PARAMS_V1)) };
  },
  /** = profile.from_env_defaults: dataset_<slug>_<branch>_<yyyymmdd>.sqlite / export_… / work */
  defaultPaths(repo, branch, outDir, workDir) {
    const sep = (outDir || '').includes('\\') || /^[A-Za-z]:/.test(outDir || '') ? '\\' : '/';
    const base = (outDir || '').replace(/[\\/]+$/, '');
    const name = `${this.slug(repo)}_${(branch || 'HEAD').replace(/[\\/:*?"<>|]/g, '-')}_${this.stamp()}`;
    return { db: `${base}${sep}dataset_${name}.sqlite`, export: `${base}${sep}export_${name}`, work: workDir || `${base}${sep}work`, dbName: `dataset_${name}.sqlite`, exportName: `export_${name}` };
  },
  get() { return sget(WKEY); },
  ensure() { let p = sget(WKEY); if (!p) { p = this.defaultProfile(); sset(WKEY, p); } return p; },
  set(p) { sset(WKEY, p); return p; },
  patch(fn) { const p = this.ensure(); fn(p); sset(WKEY, p); return p; },
  meta() { return sget(MKEY) || {}; },
  setMeta(patch) { const m = Object.assign(this.meta(), patch); sset(MKEY, m); return m; },
  reset() { sset(WKEY, null); sset(MKEY, null); },
  /** Port của profile.validate (cùng thông điệp, thêm key để i18n). */
  validate(p) {
    const errs = [];
    if (!p || p.schema !== 1) errs.push(t('v.schema'));
    if (!p || !p.repo) errs.push(t('v.repo_empty'));
    const sc = (p && p.scope) || {};
    if (!['time', 'count', 'sha', 'all'].includes(sc.mode)) errs.push(t('v.mode'));
    if (sc.mode === 'count') { const n = Number(sc.max); if (!Number.isInteger(n)) errs.push(t('v.max_nan')); else if (n <= 0) errs.push(t('v.max_zero')); }
    if (sc.mode === 'time') {
      if (!sc.since && !sc.until) errs.push(t('v.time_empty'));
      if (sc.since && sc.until && sc.since > sc.until) errs.push(t('v.time_order'));
      for (const k of ['since', 'until']) if (sc[k] && !/^\d{4}-\d{2}-\d{2}$/.test(sc[k])) errs.push(t('v.date_fmt', { k }));
    }
    if (sc.mode === 'sha') {
      if (!sc.from_sha && !sc.to_sha) errs.push(t('v.sha_empty'));
      for (const k of ['from_sha', 'to_sha']) if (sc[k] && !/^[0-9a-fA-F]{7,40}$/.test(sc[k])) errs.push(t('v.sha_fmt', { k }));
    }
    const badC = ((p && p.cheap_tools) || []).filter(x => !CHEAP_TOOLS_ALL.includes(x)); if (badC.length) errs.push(t('v.cheap_bad', { x: badC.join(',') }));
    const badE = ((p && p.expensive_tools) || []).filter(x => !EXPENSIVE_TOOLS_ALL.includes(x)); if (badE.length) errs.push(t('v.exp_bad', { x: badE.join(',') }));
    const w = (p && p.workers) || {};
    for (const k of ['scan', 'expensive']) { const n = Number(w[k]); if (!Number.isInteger(n)) errs.push(t('v.workers_nan', { k })); else if (n < 1) errs.push(t('v.workers_min', { k })); }
    if (!p || !p.paths || !p.paths.db) errs.push(t('v.db_empty'));
    const params = (p && p.params_v1) || {};
    if (JSON.stringify(normParams(params)) !== JSON.stringify(normParams(PARAMS_V1))) {
      const ex = p.experiment;
      if (!(ex && ex.enabled && String(ex.reason || '').trim().length >= 10)) errs.push(t('v.experiment'));
    }
    return errs;
  },
  /** Khung chung màn wizard: tiêu đề + nội dung + footer Quay lại/Tiếp. Trả {body, next, back}. */
  frame(root, { step, title, lead, nextLabel, backHref, nextHref, onNext, onBack, nextDisabled, extraFooter, headerRight }) {
    clear(root);
    const page = h('div', { class: 'page-narrow' });
    const head = h('div', { class: 'row between', style: { flexWrap: 'nowrap', alignItems: 'flex-start' } },
      h('div', { style: { flex: '1 1 auto', minWidth: 0 } }, h('h1', {}, title), lead ? h('p', { class: 'lead' }, lead) : null),
      headerRight ? h('div', { style: { flex: '0 0 auto', paddingTop: '6px' } }, headerRight) : null);
    const body = h('div', { class: 'stack' });
    const back = btn(t('back'), { href: backHref, onClick: onBack });
    // luôn là <button> (không phải <a>) để `.disabled` có hiệu lực; điều hướng qua navigate()
    const next = btn(nextLabel || t('next') + ' ▸', { kind: 'primary', disabled: !!nextDisabled, onClick: onNext || (() => { if (nextHref) navigate(nextHref); }) });
    const foot = h('div', { class: 'wiz-foot' }, h('div', { class: 'row gap-s' }, step > 1 ? back : btn(t('cancel'), { href: '#/home', kind: 'ghost' }), extraFooter || null), next);
    page.append(head, body, foot);
    root.append(page);
    return { body, next, back, page };
  },
};
function normParams(p) { return { line_window: Number(p.line_window), gold_min_expensive: Number(p.gold_min_expensive), gold_allow_1exp_1cheap: Number(p.gold_allow_1exp_1cheap), silver_min_cheap: Number(p.silver_min_cheap), noise_cwe: [...(p.noise_cwe || [])].sort() }; }

// ====================================================================================
// Preflight cache (header chip + banner Docker)
// ====================================================================================
const PF_KEY = 'secjit.preflight';
export const preflightCache = {
  get() { return sget(PF_KEY); },
  set(v) { sset(PF_KEY, Object.assign({ at: Date.now() }, v)); renderDockerChip(); },
  dockerLevel() { const pf = sget(PF_KEY); if (!pf || !pf.items) return null; const it = pf.items.find(x => x.id === 'docker_daemon'); return it ? it.level : null; },
};
function renderDockerChip() {
  const el = document.getElementById('hdr-docker');
  if (!el) return;
  clear(el);
  const lvl = preflightCache.dockerLevel();
  const pf = preflightCache.get();
  const port = pf && pf.items && (pf.items.find(x => x.id === 'sonar_port') || {}).detail;
  const dot = lvl === 'ok' ? 'ok' : lvl === 'warn' || lvl === 'fix' ? 'warn' : lvl === 'bad' ? 'bad' : '';
  el.append(h('span', { class: `dot ${dot}`, 'aria-hidden': 'true' }), lvl === 'ok' ? t('docker.running') : lvl === 'bad' ? t('docker.down') : lvl ? t('docker.fix') : t('docker.unknown'));
  el.title = port ? String(port) : t('docker.recheck');
}
export async function refreshPreflight({ force = false } = {}) {
  const pf = preflightCache.get();
  if (!force && pf && Date.now() - (pf.at || 0) < 60000) return pf;
  try { const d = await api('/api/preflight'); preflightCache.set(d); return d; } catch (e) { return pf; }
}

// ====================================================================================
// Router
// ====================================================================================
export let currentRoute = { path: '', params: {}, query: {} };
let currentScreen = null;
let renderSeq = 0;

export function parseHash(hash) {
  let hsh = (hash || location.hash || '').replace(/^#\/?/, '');
  const qi = hsh.indexOf('?');
  const query = {};
  if (qi >= 0) {
    for (const [k, v] of new URLSearchParams(hsh.slice(qi + 1))) query[k] = v;
    hsh = hsh.slice(0, qi);
  }
  return { path: hsh.replace(/\/+$/, ''), query };
}
export function matchRoute(path) {
  const segs = path.split('/').filter(Boolean);
  for (const r of ROUTES) {
    const ps = r.path.split('/');
    if (ps.length !== segs.length) continue;
    const params = {};
    let ok = true;
    for (let i = 0; i < ps.length; i++) {
      if (ps[i].startsWith(':')) params[ps[i].slice(1)] = decodeURIComponent(segs[i]);
      else if (ps[i] !== segs[i]) { ok = false; break; }
    }
    if (ok) return { route: r, params };
  }
  return null;
}
export function navigate(to) { location.hash = to.startsWith('#') ? to : '#/' + to.replace(/^\/+/, ''); }

function renderNav(active) {
  const nav = document.getElementById('nav');
  clear(nav);
  for (const n of NAV) nav.append(h('a', { href: n.href, class: n.id === active ? 'active' : '', 'aria-current': n.id === active ? 'page' : undefined }, h('span', { 'aria-hidden': 'true' }, n.icon), t(n.label)));
  nav.append(h('div', { class: 'nav-foot' }, 'v0.1 · ', h('a', { href: '#/preflight', style: { color: 'inherit' } }, t('nav.preflight'))));
}

export async function route() {
  const seq = ++renderSeq;
  const { path, query } = parseHash();
  if (!path) { location.replace('#/' + (preflightCache.get() && preflightCache.get().ready ? 'home' : 'preflight')); return; }
  const m = matchRoute(path);
  const main = document.getElementById('main');
  if (currentScreen) {
    // Hoãn destroy() sang SAU lượt dispatch hashchange hiện tại: màn (vd dashboard A5) có thể đăng ký
    // listener hashchange riêng để hỏi "Chạy nền / Huỷ" — gỡ listener ngay sẽ nuốt mất hộp thoại đó.
    await new Promise(r => setTimeout(r, 0));
    if (seq !== renderSeq) return;
    if (currentScreen.destroy) { try { currentScreen.destroy(); } catch (_) { /* ignore */ } }
  }
  currentScreen = null;
  if (!m) {
    currentRoute = { path, params: {}, query };
    clear(main).append(h('div', { class: 'page' }, errorBox({ code: 'no_route', message: t('err.no_route', { path }) }, () => navigate('home'), { retryLabel: t('nav.home') })));
    document.body.dataset.ready = '1';
    return;
  }
  if (m.route.redirect) {
    let to = m.route.redirect; for (const [k, v] of Object.entries(m.params)) to = to.replace(':' + k, encodeURIComponent(v));
    location.replace('#/' + to + (location.hash.includes('?') ? location.hash.slice(location.hash.indexOf('?')) : ''));
    return;
  }
  currentRoute = { path, params: m.params, query, route: m.route };
  document.body.dataset.chrome = m.route.chrome || 'app';
  document.body.dataset.screen = m.route.screen;
  document.getElementById('hdr-sub').textContent = t(m.route.title || '');
  const slot = document.getElementById('stepper-slot');
  clear(slot);
  if (m.route.chrome === 'wizard') slot.append(stepper(WIZARD_STEPS, m.route.step || 1, { linkTo: (n) => `#/wizard/${n}` }));
  renderNav(m.route.nav || '');
  delete document.body.dataset.ready;
  clear(main);
  const loadingEl = h('div', { class: 'page' }, skeleton(4));
  main.append(loadingEl);
  let mod;
  try {
    mod = await import(`./screens/${m.route.screen}.js`);
  } catch (e) {
    if (seq !== renderSeq) return;
    clear(main).append(h('div', { class: 'page' }, errorBox({ code: 'screen_missing', message: t('err.screen_missing', { screen: m.route.screen }), hint: String(e && e.message || '') }, () => navigate('home'), { retryLabel: t('nav.home') })));
    document.body.dataset.ready = '1';
    return;
  }
  if (seq !== renderSeq) return;
  clear(main);
  currentScreen = mod;
  const ctx = { params: m.params, query, state: query.state || '', navigate, api, t, route: m.route,
    sse, url: apiUrl, components, lang: LANG };
  try {
    await mod.render(main, ctx);
  } catch (e) {
    if (seq !== renderSeq) return;
    console.error(e);
    clear(main).append(h('div', { class: 'page' }, errorBox({ code: 'render_failed', message: String(e && e.message || e) }, () => route())));
  }
  if (seq === renderSeq) document.body.dataset.ready = '1';
  main.focus({ preventScroll: true });
}

// ====================================================================================
// Boot
// ====================================================================================
async function boot() {
  initToken();
  await loadI18n();
  document.documentElement.lang = LANG;
  const sel = document.getElementById('hdr-lang');
  sel.value = LANG;
  sel.addEventListener('change', () => setLang(sel.value));
  renderDockerChip();
  window.addEventListener('hashchange', route);
  await route();
  refreshPreflight().catch(() => {});
}
window.SecJIT = { api, apiUrl, sse, t, h, btn, card, table, stepper, toast, dialog, dialogEl, components, empty, errorBox, skeleton, badgeLabel, badgeStatus, notice, progress, wiz, fmt, navigate, ROUTES, preflightCache, refreshPreflight, copyText };
boot();
