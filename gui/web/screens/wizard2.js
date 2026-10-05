/* Wizard 2/5 — Phạm vi commit: time/count/sha/all, validate, include_clean, lọc, ước tính (debounce) + histogram. */
import { api, t, h, card, notice, skeleton, clear, debounce, wiz, fmt } from '../app.js';

let alive = true;
let frame = null;
let estBox = null;
let lastEstimate = null;
let scopeBad = false;

export async function render(root, ctx) {
  alive = true;
  const p = wiz.ensure();
  const meta = wiz.meta();
  if (!p.scope) p.scope = { mode: 'count', since: null, until: null, max: 50, from_sha: null, to_sha: null };
  frame = wiz.frame(root, { step: 2, title: t('w2.title'), lead: t('w2.lead'), backHref: '#/wizard/1', nextHref: '#/wizard/3',
    headerRight: p.repo ? h('span', { class: 'tag mono' }, `${fmt.repoShort(p.repo)} · ${p.branch || 'HEAD'}`) : null });
  if (!p.repo) frame.body.append(notice('warn', t('w2.no_repo'), { action: h('a', { class: 'btn small', href: '#/wizard/1' }, t('w1.title')) }));

  const rc = meta.repo_check || {};
  const total = rc.commit_count;

  // ---- radio ----
  const since = h('input', { class: 'input mono', type: 'date', id: 'w2-since', value: p.scope.since || '', 'aria-label': t('w2.from') });
  const until = h('input', { class: 'input mono', type: 'date', id: 'w2-until', value: p.scope.until || '', 'aria-label': t('w2.to') });
  const max = h('input', { class: 'input mono', type: 'number', id: 'w2-max', min: '1', step: '1', value: p.scope.max || 50, 'aria-label': t('w2.count_n') });
  const fromSha = h('input', { class: 'input mono', id: 'w2-from', placeholder: 'abc1234', maxlength: '40', value: p.scope.from_sha || '', 'aria-label': t('w2.sha_from') });
  const toSha = h('input', { class: 'input mono', id: 'w2-to', placeholder: 'def5678', maxlength: '40', value: p.scope.to_sha || '', 'aria-label': t('w2.sha_to') });
  const errs = { time: h('div', { class: 'err' }), count: h('div', { class: 'err' }), sha: h('div', { class: 'err' }) };
  const rows = {};
  const mk = (mode, label, opts, err) => {
    const r = h('input', { type: 'radio', name: 'w2-mode', id: 'w2-mode-' + mode, value: mode, checked: p.scope.mode === mode });
    r.addEventListener('change', () => { wiz.patch(x => { x.scope.mode = mode; }); refresh(); });
    const row = h('div', { class: 'radio-row' + (p.scope.mode === mode ? ' active' : '') }, r, h('label', { for: 'w2-mode-' + mode, style: { fontWeight: 600, minHeight: '44px', display: 'flex', alignItems: 'center' } }, label),
      h('div', {}, h('div', { class: 'opts' }, opts), err || null));
    rows[mode] = row;
    return row;
  };
  const list = h('div', { class: 'radio-list' },
    mk('time', t('w2.time'), [h('span', { class: 'muted' }, t('w2.from')), since, h('span', { class: 'muted' }, t('w2.to')), until], errs.time),
    mk('count', t('w2.count'), [max, h('span', { class: 'muted small' }, t('w2.count_hint'))], errs.count),
    mk('sha', t('w2.sha'), [fromSha, h('span', { class: 'muted' }, '→'), toSha, h('span', { class: 'muted small' }, t('w2.sha_hint'))], errs.sha),
    mk('all', t('w2.all'), [h('span', { class: 'muted small' }, total !== null && total !== undefined ? t('w2.all_n', { n: fmt.num(total) }) : t('w2.all_unknown'))]));
  for (const inp of [since, until, max, fromSha, toSha]) inp.addEventListener('input', () => { save(); refresh(); });

  // ---- lọc ----
  const inc = h('input', { type: 'checkbox', id: 'w2-clean', checked: !!p.include_clean });
  inc.addEventListener('change', () => { wiz.patch(x => { x.include_clean = inc.checked; }); refresh(); });
  const filters = p.filters || {};
  const cpb = h('input', { class: 'input mono', type: 'number', id: 'w2-cpb', min: '0', step: '1', value: filters.clean_per_buggy !== undefined ? filters.clean_per_buggy : '', placeholder: t('w2.all_clean') });
  const rid = h('input', { type: 'checkbox', id: 'w2-rid', checked: filters.require_in_diff !== false });
  const saveFilters = () => wiz.patch(x => { x.filters = { clean_per_buggy: cpb.value === '' ? null : Math.max(0, parseInt(cpb.value, 10) || 0), require_in_diff: rid.checked }; });
  cpb.addEventListener('input', () => { saveFilters(); refresh(); });
  rid.addEventListener('change', () => { saveFilters(); refresh(); });
  const filterCard = card({ body: h('div', {},
    h('div', { class: 'check', 'aria-disabled': 'true' }, h('input', { type: 'checkbox', checked: true, disabled: true, 'aria-label': t('w2.skip_merge') }), h('span', {}, h('strong', {}, t('w2.skip_merge')), ' ', h('span', { class: 'muted small' }, t('w2.skip_merge_fixed')))),
    h('label', { class: 'check', for: 'w2-clean' }, inc, h('span', {}, h('strong', {}, t('w2.include_clean')), ' ', h('span', { class: 'muted small' }, t('w2.include_clean_hint')))),
    h('details', { class: 'fold', style: { marginTop: '10px' } }, h('summary', {}, t('w2.filters')), h('div', { class: 'fold-b' },
      h('label', { class: 'field', for: 'w2-cpb' }, h('span', {}, t('w2.clean_per_buggy')), cpb, h('div', { class: 'help' }, t('w2.clean_per_buggy_hint'))),
      h('label', { class: 'check', for: 'w2-rid' }, rid, h('span', {}, t('w2.require_in_diff'), ' ', h('span', { class: 'muted small' }, t('w2.require_in_diff_hint'))))))) });

  // ---- ước tính ----
  estBox = h('div');
  const estCard = card({ title: t('w2.estimate'), body: estBox });

  frame.body.append(card({ body: list }), filterCard, estCard);

  function save() {
    wiz.patch(x => {
      x.scope.since = since.value || null; x.scope.until = until.value || null;
      x.scope.max = max.value === '' ? null : parseInt(max.value, 10);
      x.scope.from_sha = fromSha.value.trim() || null; x.scope.to_sha = toSha.value.trim() || null;
    });
  }
  function refresh() {
    const x = wiz.ensure();
    for (const [m, row] of Object.entries(rows)) row.classList.toggle('active', x.scope.mode === m);
    const e = validateScope(x.scope);
    for (const k of Object.keys(errs)) { errs[k].textContent = e[k] || ''; }
    for (const [inp, bad] of [[since, e.time && !since.value && !until.value], [until, e.time && since.value && until.value && since.value > until.value], [max, !!e.count], [fromSha, e.sha && fromSha.value && !shaOk(fromSha.value)], [toSha, e.sha && toSha.value && !shaOk(toSha.value)]]) inp.classList.toggle('invalid', !!bad);
    // W2-3: "đến" ở tương lai không phải lỗi — nghĩa là HEAD
    const today = new Date().toISOString().slice(0, 10);
    if (x.scope.mode === 'time' && !e.time && until.value && until.value > today) { errs.time.textContent = t('w2.until_future'); errs.time.className = 'warnmsg'; } else errs.time.className = 'err';
    const bad = e[x.scope.mode];
    scopeBad = !!bad || !x.repo;
    frame.next.disabled = scopeBad;
    if (!bad && x.repo) estimateDebounced(); else drawEstimate(null, bad ? { message: t('w2.fix_first') } : null);
  }
  const estimateDebounced = debounce(() => runEstimate(), 450);
  refresh();
}

export function destroy() { alive = false; frame = null; }

function shaOk(s) { return /^[0-9a-fA-F]{7,40}$/.test((s || '').trim()); }
function validateScope(sc) {
  const e = {};
  if (sc.mode === 'time') {
    if (!sc.since && !sc.until) e.time = t('v.time_empty');
    else if (sc.since && sc.until && sc.since > sc.until) e.time = t('v.time_order');
    else if (sc.until && sc.until > new Date().toISOString().slice(0, 10)) e.time = '';
  }
  if (sc.mode === 'count') {
    const n = Number(sc.max);
    if (sc.max === null || sc.max === undefined || !Number.isInteger(n)) e.count = t('v.max_nan');
    else if (n === 0) e.count = t('v.max_zero');
    else if (n < 0) e.count = t('v.max_neg');
    else if (n > 1000000) e.count = t('v.max_huge');
  }
  if (sc.mode === 'sha') {
    if (!sc.from_sha && !sc.to_sha) e.sha = t('v.sha_empty');
    else if ((sc.from_sha && !shaOk(sc.from_sha)) || (sc.to_sha && !shaOk(sc.to_sha))) e.sha = t('v.sha_fmt_short');
  }
  return e;
}

let estSeq = 0;
async function runEstimate() {
  if (!alive) return;
  const seq = ++estSeq;
  const p = wiz.ensure();
  drawEstimate(lastEstimate, null, true);
  try {
    const d = await api('/api/estimate', { method: 'POST', body: { profile: p } });
    if (!alive || seq !== estSeq) return;
    lastEstimate = d;
    wiz.setMeta({ estimate: d });
    drawEstimate(d, null);
  } catch (e) {
    if (!alive || seq !== estSeq) return;
    drawEstimate(null, e);
    // backend đang clone nền -> thử lại sau 5 s (đến khi rời màn)
    if (e.code === 'clone_pending') setTimeout(() => { if (alive && seq === estSeq) runEstimate(); }, 5000);
  }
}

function drawEstimate(d, err, loading) {
  if (!estBox) return;
  clear(estBox);
  if (loading) estBox.setAttribute('aria-busy', 'true'); else estBox.removeAttribute('aria-busy');
  if (!d && err) { estBox.append(notice('warn', h('div', {}, h('strong', {}, t('w2.est_unavailable')), ' ', err.message || '', err.hint ? h('div', { class: 'small' }, err.hint) : null))); return; }
  if (!d) { estBox.append(loading ? skeleton(2, { lines: true }) : h('p', { class: 'muted' }, t('w2.est_unavailable'))); return; }   // W2-2: skeleton lần đầu
  const p = wiz.ensure();
  // W2-1: 0 commit sau lọc -> khoá Tiếp (mở lại khi ước tính mới > 0 và phạm vi hợp lệ)
  if (frame) frame.next.disabled = scopeBad || (!loading && d.commits_after_filter === 0);
  const tiles = h('div', { class: 'tiles' },
    tile(fmt.num(d.commits_after_filter), t('w2.after_filter')),
    tile(d.buggy_est !== undefined ? '~' + fmt.num(d.buggy_est) : '—', t('w2.buggy_est')),
    tile(fmt.minutes(d.cheap_minutes), t('w2.cheap_time')),
    tile(d.disk_gb !== undefined ? `+${Number(d.disk_gb).toFixed(1)} GB` : '—', t('w2.disk')));
  estBox.append(tiles);
  if (d.commits_after_filter === 0) estBox.append(h('div', { style: { marginTop: '10px' } }, notice('warn', t('w2.zero_commits'))));
  const src = d.speed_source === 'measured' ? t('w2.speed_measured', { s: d.speed && d.speed.cheap_s_per_commit ? d.speed.cheap_s_per_commit : '?' }) : t('w2.speed_default');
  estBox.append(h('p', { class: 'help', style: { marginTop: '10px' } }, src + (loading ? ' · ' + t('w2.est_loading') : '')));
  if (Array.isArray(d.histogram) && d.histogram.length) {
    const maxN = Math.max(1, ...d.histogram.map(b => b.n || 0));
    const bars = h('div', { class: 'hist', role: 'img', 'aria-label': t('w2.hist') });
    for (const b of d.histogram) {
      const inRange = p.scope.mode !== 'time' || ((!p.scope.since || b.month >= p.scope.since.slice(0, 7)) && (!p.scope.until || b.month <= p.scope.until.slice(0, 7)));
      bars.append(h('i', { class: inRange ? 'sel' : '', style: { height: `${Math.max(3, (b.n / maxN) * 100)}%` }, title: `${b.month}: ${b.n}` }));
    }
    estBox.append(h('div', { style: { marginTop: '12px' } }, h('div', { class: 'small muted' }, t('w2.hist')), bars,
      h('div', { class: 'hist-axis' }, h('span', {}, d.histogram[0].month), h('span', {}, d.histogram[d.histogram.length - 1].month))));
  }
}
function tile(v, k) { return h('div', { class: 'tile' }, h('div', { class: 'v' }, v), h('div', { class: 'k' }, k)); }
