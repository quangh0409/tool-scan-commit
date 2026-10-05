// _harness.js — harness tối thiểu của A5: router hash + API giả đọc fixture `gui/fixtures/*`.
// Mở qua server tĩnh tại gui/:  python -m http.server 8765  ->  http://127.0.0.1:8765/web/screens/_harness.html#/run/r-20261005-A?state=normal
// `?state=normal|loading|empty|error|partial` (+ dashboard: interrupted|infra|scratch|done) mô phỏng backend.
// Trưởng sẽ bỏ harness khi nối vào router thật của A4 (ctx có cùng chữ ký).
import { components, h } from './_shim.js';
import { clear, qs } from './_util.js';

const FIX = '../../fixtures/';
const cache = new Map();

async function fixture(name) {
  if (cache.has(name)) return structuredClone(cache.get(name));
  const r = await fetch(FIX + name);
  if (!r.ok) throw apiErr(500, 'EFIXTURE', `Không đọc được fixture ${name} (${r.status})`);
  const txt = await r.text();
  const data = name.endsWith('.jsonl') ? txt.split(/\r?\n/).filter(Boolean).map((l) => JSON.parse(l)) : JSON.parse(txt);
  cache.set(name, data);
  return structuredClone(data);
}

function apiErr(status, code, message, hint) { return { status, error: { code, message, hint, status } }; }
function never() { return new Promise(() => {}); }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------- trạng thái từ hash ----------
function parseHash() {
  const raw = (location.hash || '#/run/r-20261005-A').slice(1);
  const [path, query = ''] = raw.split('?');
  const params = Object.fromEntries(new URLSearchParams(query));
  return { path, params, state: params.state || 'normal' };
}

// ---------- API giả ----------
let pollCount = 0; // mô phỏng SSE: mỗi lần poll lộ thêm 1 dòng progress
let reviewRemaining = null;
const verdicts = [];

async function api(path, opts = {}) {
  const { state } = parseHash();
  const method = (opts.method || 'GET').toUpperCase();
  const body = opts.body || {};
  const [p, q = ''] = path.split('?');
  const query = Object.fromEntries(new URLSearchParams(q));
  if (state === 'loading') return never();
  if (state === 'error') { await sleep(80); throw apiErr(500, 'EHARNESS', 'Harness: backend trả lỗi mô phỏng', 'Đổi ?state= để xem dữ liệu thật từ fixture'); }
  await sleep(60);
  const partial = state === 'partial';
  const empty = state === 'empty';
  let m;

  if (p === '/api/runs') {
    const d = await fixture('runs.json');
    if (state === 'infra') { const r = d.runs.find((x) => x.run_id === 'r-20261005-A'); r.status = 'stopped'; }
    if (state === 'done') { const r = d.runs.find((x) => x.run_id === 'r-20261005-A'); r.status = 'done'; r.finished = '2026-10-05T13:40:00'; r.summary = { ...r.summary, gold: 4, silver: 61, candidate: 38, verified_clean: 14, cheap_clean: 4, kappa: -0.36 }; }
    return d;
  }
  if ((m = p.match(/^\/api\/run\/([^/]+)\/progress$/))) {
    if (empty) return [];
    let lines = await fixture('progress.jsonl');
    lines = lines.filter((l) => l.run_id === m[1] || m[1] === 'r-20261005-A' || m[1] === 'r-20261005-int' || m[1] === 'r-20261004-scratch');
    if (partial) lines = lines.map((l) => { const c = { ...l }; delete c.worker; if (c.phase === 'analyze') delete c.total; return c; });
    if (state === 'infra') {
      lines.push({ ts: '2026-10-05T11:29:00', run_id: m[1], phase: 'analyze', event: 'item', done: 4, total: 27, worker: 'w0', sha: '0e8a77c1', status: 'infra_error', msg: 'rc 125: Cannot connect to the Docker daemon' });
      lines.push({ ts: '2026-10-05T11:29:40', run_id: m[1], phase: 'analyze', event: 'item', done: 5, total: 27, worker: 'w0', sha: '9bdd9a28', status: 'infra_error', msg: 'rc 125: error during connect' });
      lines.push({ ts: '2026-10-05T11:30:10', run_id: m[1], phase: 'analyze', event: 'item', done: 6, total: 27, worker: 'w0', sha: '350f6200', status: 'infra_error', msg: 'rc 125: dockerDesktopLinuxEngine' });
      lines.push({ ts: '2026-10-05T11:30:11', run_id: m[1], phase: 'analyze', event: 'stop', status: 'infra_error', msg: '3 infra_error liên tiếp → run tự dừng' });
    }
    if (state === 'done') lines.push({ ts: '2026-10-05T13:40:00', run_id: m[1], phase: 'export', event: 'done', msg: 'export xong' });
    // mô phỏng live: lộ dần dòng cuối
    const hide = state === 'normal' ? 2 : 0;
    const reveal = Math.min(lines.length, Math.max(5, lines.length - hide + pollCount));
    pollCount += 1;
    return lines.slice(0, reveal);
  }
  if ((m = p.match(/^\/api\/run\/([^/]+)\/stop$/)) && method === 'POST') {
    return { ok: true, cleaned: body.force ? [`container orch-sonar-${m[1]}`, `container maven-${m[1]}-w0`, `network orch-sonar-net-${m[1]}`, 'reset-claims: 1 commit → pending'] : [] };
  }
  if ((m = p.match(/^\/api\/run\/([^/]+)\/resume$/)) && method === 'POST') {
    if (body.workers !== undefined) throw apiErr(501, 'ENOTSUP', 'Đổi số luồng khi resume chưa được hỗ trợ', 'A3/A2: resume nhận workers');
    return { run_id: m[1], pid: 4242, from_phase: 'analyze' };
  }
  if (p === '/api/diagnostics') throw apiErr(501, 'ENOTSUP', 'Gói chẩn đoán chưa có trong harness');

  if ((m = p.match(/^\/api\/results\/([^/]+)\/overview$/))) {
    const d = await fixture('overview.json');
    if (empty) return { ...d, funnel: Object.fromEntries(Object.keys(d.funnel).map((k) => [k, 0])), labels: Object.fromEntries(Object.keys(d.labels).map((k) => [k, 0])), by_cwe_group: [], kappa: null, coverage: null, precision: null, limits: [] };
    if (partial) { delete d.kappa; delete d.precision; delete d.limits; delete d.coverage; }
    if (query.exp === '1' || m[1].endsWith('_exp')) d.experiment = { enabled: true, reason: 'thử W=5 để xem độ nhạy cụm' };
    return d;
  }
  if ((m = p.match(/^\/api\/results\/([^/]+)\/findings$/))) {
    const d = await fixture('findings.json');
    if (empty) return { total: 0, page: 1, size: Number(query.size || 20), rows: [] };
    let rows = d.rows;
    if (query.label) rows = rows.filter((r) => r.label === query.label);
    if (query.cwe_group) rows = rows.filter((r) => r.cwe_group === query.cwe_group);
    if (query.min_tools) rows = rows.filter((r) => (r.n_agree || 0) >= Number(query.min_tools));
    if (query.tier) rows = rows.filter((r) => r.tier === query.tier);
    if (query.in_diff !== undefined && query.in_diff !== '') rows = rows.filter((r) => String(r.in_diff) === query.in_diff);
    if (query.q) { const s = query.q.toLowerCase(); rows = rows.filter((r) => JSON.stringify(r).toLowerCase().includes(s)); }
    if (partial) rows = rows.map((r) => { const c = { ...r }; delete c.tools; delete c.evidence; delete c.tier; return c; });
    const size = Number(query.size || 20); const page = Number(query.page || 1);
    const total = rows.length === d.rows.length && !query.label && !query.q ? d.total : rows.length;
    return { total, page, size, rows: rows.slice((page - 1) * size, page * size) };
  }
  if ((m = p.match(/^\/api\/results\/([^/]+)\/finding\/([^/]+)$/))) {
    const d = await fixture('finding.json');
    const list = await fixture('findings.json');
    const row = list.rows.find((r) => r.cluster_key === m[2]);
    if (!row && m[2] !== d.row.cluster_key) throw apiErr(404, 'ENOTFOUND', `Không có cụm ${m[2]}`);
    if (row) d.row = row;
    if (partial) { delete d.diff_lines; delete d.provenance; }
    return d;
  }
  if ((m = p.match(/^\/api\/results\/([^/]+)\/raw$/))) throw apiErr(404, 'ENORAW', `Chưa có raw ${query.path || ''}`, 'A1/A2: thêm GET /api/results/{id}/raw?path=');
  if ((m = p.match(/^\/api\/results\/([^/]+)\/commits$/))) {
    const d = await fixture('commits.json');
    if (empty) return { total: 0, rows: [] };
    if (partial) d.rows = d.rows.map((r) => { const c = { ...r }; delete c.kamei; delete c.n_expensive_ok; return c; });
    return d;
  }
  if ((m = p.match(/^\/api\/results\/([^/]+)\/export$/)) && method === 'POST') {
    const fmts = body.formats || ['jsonl'];
    const dir = 'D:\\secjit\\results\\export_FudanSELab__train-ticket_master_20261005';
    const files = ['run_manifest.json', 'SHA256SUMS', 'negatives.json'];
    if (fmts.includes('jsonl')) files.unshift('dataset.jsonl', 'commits.jsonl');
    if (fmts.includes('csv')) files.push('dataset.csv', 'commits.csv');
    if (fmts.includes('latex')) files.push('stats.tex');
    return { export_dir: dir, files, exists: query.exists === '1' };
  }
  if ((m = p.match(/^\/api\/results\/([^/]+)\/(features|relabel)$/))) throw apiErr(501, 'ENOTSUP', `${m[2]} chưa được hỗ trợ qua GUI`, 'A2: thêm endpoint');
  if (p === '/api/open') throw apiErr(501, 'ENOTSUP', 'Mở thư mục chưa được hỗ trợ trong harness', 'A4: POST /api/open?path=');

  if ((m = p.match(/^\/api\/review\/([^/]+)\/sample$/)) && method === 'POST') {
    const d = await fixture('review_sample.json');
    d.sample_id = `s-${body.seed}-20261005`;
    reviewRemaining = (d.n_pos || 0) + (d.n_neg || 0);
    if (partial) delete d.strata;
    return d;
  }
  if ((m = p.match(/^\/api\/review\/([^/]+)\/next$/))) {
    const d = await fixture('review_item.json');
    if (reviewRemaining === null) reviewRemaining = d.remaining;
    if (reviewRemaining <= 0) return { cluster_key: null, remaining: 0 };
    d.remaining = reviewRemaining;
    if (partial) delete d.code_lines;
    return d;
  }
  if ((m = p.match(/^\/api\/review\/([^/]+)\/verdict$/)) && method === 'POST') {
    verdicts.push(body);
    if (body.rater !== 'adjudicated') reviewRemaining = Math.max(0, (reviewRemaining ?? 1) - 1);
    return { ok: true, remaining: reviewRemaining ?? 0 };
  }
  if ((m = p.match(/^\/api\/review\/([^/]+)\/close$/)) && method === 'POST') {
    const d = await fixture('review_close.json');
    if (partial) { delete d.kappa_raters; delete d.disagreements; }
    return d;
  }

  if (p === '/api/settings') { const d = await fixture('settings.json'); if (method === 'POST') return { ...d, ...body }; return d; }
  if (p === '/api/preflight') {
    const d = await fixture('preflight.json');
    if (empty) return { ...d, items: [] };
    if (partial) { delete d.docker_mem_gb; delete d.cpu; }
    return d;
  }
  if (p === '/api/storage') {
    const d = await fixture('storage.json');
    if (empty) return { items: [], total_bytes: 0, free_bytes: d.free_bytes };
    if (partial) { delete d.free_bytes; d.items = d.items.map((it) => { const c = { ...it }; if (c.id === 'm2') delete c.safety; return c; }); }
    return d;
  }
  if (p === '/api/clean' && method === 'POST') {
    if ((body.items || []).includes('clone')) throw apiErr(409, 'ERUNNING', 'Run r-20261005-A đang chạy và dùng đường dẫn này', 'Dừng run trước khi xoá');
    const d = await fixture('clean_dry.json');
    if (body.dry_run) return d;
    return { would_delete: [], deleted: d.would_delete, errors: [] };
  }
  if (p === '/api/profiles') { const d = await fixture('profiles.json'); if (empty) return { profiles: [] }; return d; }
  if ((m = p.match(/^\/api\/profiles\/([^/]+)$/)) && method === 'DELETE') return { ok: true, name: decodeURIComponent(m[1]) };

  throw apiErr(404, 'ENOROUTE', `Harness không có route ${method} ${path}`);
}

// ---------- router ----------
const ROUTES = [
  { re: /^\/run\/([^/]+)$/, mod: 'dashboard', params: (m) => ({ id: m[1] }) },
  { re: /^\/results\/([^/]+)\/(overview|findings|commits|export)$/, mod: (m) => `results_${m[2]}`, params: (m) => ({ id: m[1], tab: m[2] }) },
  { re: /^\/results\/([^/]+)$/, mod: 'results_overview', params: (m) => ({ id: m[1], tab: 'overview' }) },
  { re: /^\/settings\/?([^/]*)$/, mod: 'settings', params: (m) => ({ tab: m[1] || 'docker' }) },
  { re: /^\/review\/([^/]+)$/, mod: 'review', params: (m) => ({ id: m[1] }) },
];

const SCREENS = [
  ['#/run/r-20261005-A', 'Dashboard'], ['#/results/r-20261005-A/overview', 'Tổng quan'], ['#/results/r-20261005-A/findings', 'Finding'],
  ['#/results/r-20261005-A/commits', 'Commit'], ['#/results/r-20261005-A/export', 'Xuất'], ['#/settings/docker', 'Cài đặt'], ['#/review/r-20261005-A', 'Kiểm tay'],
];
const STATES = ['normal', 'loading', 'empty', 'error', 'partial', 'interrupted', 'infra', 'scratch', 'done'];

let current = null;
const root = document.getElementById('screen');

function navigate(hash) { location.hash = hash.startsWith('#') ? hash : `#${hash}`; }

function ctxFor(params) {
  return {
    api,
    t: (key) => key, // thiếu i18n -> trả khoá, màn dùng fallback tiếng Việt
    params,
    navigate,
    components,
    url: (path) => `harness-download:${path}`,
  };
}

async function route() {
  const { path, params, state } = parseHash();
  document.getElementById('state-pick').value = STATES.includes(state) ? state : 'normal';
  for (const a of document.querySelectorAll('#nav a')) a.classList.toggle('on', path.startsWith(a.dataset.path));
  if (current && current.destroy) { try { await current.destroy(); } catch (e) { console.warn('destroy lỗi', e); } }
  current = null;
  clear(root);
  const r = ROUTES.find((x) => x.re.test(path));
  if (!r) { root.append(components.empty(`Harness: không có route ${path}`)); return; }
  const m = path.match(r.re);
  const modName = typeof r.mod === 'function' ? r.mod(m) : r.mod;
  const mod = await import(`./${modName}.js`);
  current = mod;
  pollCount = 0;
  const ctx = ctxFor({ ...params, ...r.params(m), state });
  root.dataset.screen = modName;
  await mod.render(root, ctx);
}

function buildChrome() {
  const nav = document.getElementById('nav');
  for (const [hash, label] of SCREENS) {
    const a = h('a', { href: hash, text: label, dataset: { path: hash.slice(1).split('?')[0].replace(/\/(overview|findings|commits|export|docker)$/, (s) => s) } });
    a.addEventListener('click', (e) => { e.preventDefault(); const { state } = parseHash(); navigate(`${hash}?state=${state}`); });
    nav.append(a);
  }
  const pick = document.getElementById('state-pick');
  for (const s of STATES) pick.append(h('option', { value: s, text: s }));
  pick.addEventListener('change', () => { const { path, params } = parseHash(); navigate(`#${path}${qs({ ...params, state: pick.value })}`); });
}

buildChrome();
window.addEventListener('hashchange', () => { route().catch((e) => { console.error(e); clear(root); root.append(components.errorBox(e)); }); });
route().catch((e) => { console.error(e); clear(root); root.append(components.errorBox(e)); });
