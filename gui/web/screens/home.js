/* Màn 1 — Home: danh sách run (registry), CTA Scan mới, banner Docker, dung lượng. */
import { api, t, h, btn, card, toast, dialog, empty, errorBox, skeleton, notice, badgeStatus, clear, busy, wiz, fmt, navigate, refreshPreflight, preflightCache } from '../app.js';

let alive = true;

export async function render(root, ctx) {
  alive = true;
  const page = h('div', { class: 'page stack' });
  root.append(page);
  await load(page, ctx);
}
export function destroy() { alive = false; }

async function load(page, ctx) {
  clear(page);
  // Banner Docker tắt — KHÔNG chặn Home chờ preflight thật (docker/network ~1 phút): dùng cache, làm mới nền
  const bannerSlot = h('div');
  page.append(bannerSlot);
  const drawBanner = () => {
    clear(bannerSlot);
    const dl = preflightCache.dockerLevel();
    if (dl === 'bad' || dl === 'fix') bannerSlot.append(notice(dl === 'bad' ? 'bad' : 'fix', h('div', {}, h('strong', {}, t('home.docker_down')), ' ', t('home.docker_down_hint')), { action: btn(t('home.open_preflight'), { small: true, href: '#/preflight' }) }));
  };
  drawBanner();
  refreshPreflight().then(() => { if (alive) drawBanner(); }).catch(() => {});

  const grid = h('div', { class: 'grid-2' });
  const left = h('div', { class: 'stack' });
  const right = h('div', { class: 'stack' });
  grid.append(left, right);
  page.append(grid);

  left.append(card({ body: h('div', { class: 'stack' },
    btn('＋ ' + t('home.new_scan'), { kind: 'primary', href: '#/wizard/1', onClick: () => { wiz.reset(); } }),
    h('p', { class: 'muted small', style: { margin: 0 } }, t('home.new_scan_hint')),
    btn('⚙ ' + t('nav.settings'), { href: '#/settings/docker' })) }));
  const storageCard = card({ title: t('home.storage'), body: skeleton(3, { lines: true }) });
  left.append(storageCard);

  const runsCard = card({ title: t('home.recent_runs'), body: skeleton(3) });
  right.append(runsCard);

  // tải song song
  loadStorage(storageCard);
  await loadRuns(runsCard, ctx);
}

async function loadStorage(cardEl) {
  const body = cardEl.querySelector('.card-b');
  try {
    const s = await api('/api/storage');
    if (!alive) return;
    clear(body);
    const items = (s.items || []).slice().sort((a, b) => (b.bytes || 0) - (a.bytes || 0)).slice(0, 4);
    body.append(h('div', { class: 'tiles' },
      h('div', { class: 'tile' }, h('div', { class: 'v' }, fmt.bytes(s.total_bytes)), h('div', { class: 'k' }, t('home.storage_used'))),
      h('div', { class: 'tile' }, h('div', { class: 'v' }, fmt.bytes(s.free_bytes)), h('div', { class: 'k' }, t('home.storage_free')))));
    if (items.length) {
      const dl = h('dl', { class: 'kv', style: { marginTop: '12px', gridTemplateColumns: '1fr auto' } });
      for (const it of items) dl.append(h('dt', {}, it.title), h('dd', { class: 'mono' }, fmt.bytes(it.bytes)));
      body.append(dl);
    } else body.append(h('p', { class: 'muted small' }, t('home.storage_empty')));
    body.append(h('div', { style: { marginTop: '12px' } }, btn(t('home.cleanup') + '…', { small: true, href: '#/settings/storage' })));
  } catch (e) {
    if (!alive) return;
    clear(body).append(errorBox(e, () => loadStorage(cardEl)));
  }
}

async function loadRuns(cardEl, ctx) {
  const body = cardEl.querySelector('.card-b');
  let d;
  try {
    d = await api('/api/runs');
  } catch (e) {
    if (!alive) return;
    clear(body).append(errorBox(e, () => loadRuns(cardEl, ctx)));
    return;
  }
  if (!alive) return;
  clear(body);
  const runs = (d && d.runs) || [];
  if (!runs.length) {
    body.append(empty(t('home.empty'), { icon: '▶', action: btn('＋ ' + t('home.new_scan'), { kind: 'primary', href: '#/wizard/1', onClick: () => wiz.reset() }) }));
    return;
  }
  body.classList.remove('card-b'); body.classList.add('card-list-b');
  const missingSummary = runs.some(r => !r.summary);
  if (missingSummary) body.append(h('div', { style: { padding: '12px 18px' } }, notice('warn', t('home.partial'))));
  for (const r of runs) body.append(runRow(r, cardEl, ctx));
}

function runRow(r, cardEl, ctx) {
  const s = r.summary || {};
  const st = (r.status || 'unknown').toLowerCase();
  const row = h('div', { class: 'run-card', 'data-run': r.run_id });
  const title = h('div', { class: 'title' }, h('span', {}, fmt.repoShort(r.repo)), h('span', { class: 'tag mono' }, r.branch || 'HEAD'), badgeStatus(st), r.smoke ? h('span', { class: 'badge warn' }, t('home.smoke')) : null);
  const metaBits = [];
  if (s.commits !== undefined && s.commits !== null) metaBits.push(t('home.n_commits', { n: fmt.num(s.commits) }));
  metaBits.push(st === 'running' ? t('home.started_at', { d: fmt.date(r.started) }) : t('home.finished_at', { d: fmt.date(r.finished || r.started) }));
  const meta = h('div', { class: 'meta' }, metaBits.join(' · '));
  const right = h('div', { class: 'badges' });
  // badge mức bằng chứng (chỉ khi run không chạy — không hiện nhãn tạm)
  if (st !== 'running' && r.summary) {
    const goldTxt = s.gold_reviewed !== undefined && s.gold_reviewed !== null ? `gold ${fmt.num(s.gold)} · ${t('home.reviewed', { x: s.gold_reviewed, y: s.gold })}` : `gold ${fmt.num(s.gold)} · ${t('badge.machine')}`;
    right.append(h('span', { class: 'badge gold' }, goldTxt), h('span', { class: 'badge silver' }, `silver ${fmt.num(s.silver)}`), h('span', { class: 'badge candidate' }, `candidate ${fmt.num(s.candidate)}`));
    if (s.verified_clean !== undefined && s.verified_clean !== null) right.append(h('span', { class: 'badge verified-clean' }, `verified-clean ${fmt.num(s.verified_clean)}`));
    if (s.kappa !== undefined && s.kappa !== null) right.append(h('span', { class: 'tag' }, `κ ${Number(s.kappa).toFixed(2)}`));
  } else if (st === 'running') right.append(h('span', { class: 'tag' }, t('home.running_no_labels')));
  const actions = h('div', { class: 'actions' });
  if (st === 'running') actions.append(btn(t('home.open_dashboard'), { kind: 'primary', small: true, href: `#/run/${encodeURIComponent(r.run_id)}` }));
  if (st === 'interrupted' || st === 'stopped') {
    const b = btn('▶ ' + t('home.resume'), { kind: 'primary', small: true, onClick: async () => {
      busy(b, true);
      try { const res = await api(`/api/run/${encodeURIComponent(r.run_id)}/resume`, { method: 'POST', body: {} }); toast(t('home.resumed', { phase: res.from_phase || '?' }), 'ok'); navigate(`run/${encodeURIComponent(res.run_id || r.run_id)}`); }
      catch (e) { busy(b, false); toast(`${e.message}${e.hint ? ' — ' + e.hint : ''}`, 'bad', 8000); }
    } });
    actions.append(b, btn(t('home.open_results_partial'), { small: true, href: `#/results/${encodeURIComponent(r.run_id)}/overview` }));
  }
  if (st === 'done') actions.append(btn(t('home.open_results'), { kind: 'primary', small: true, href: `#/results/${encodeURIComponent(r.run_id)}/overview` }));
  if (st === 'failed') actions.append(btn(t('home.view_log'), { small: true, href: `#/run/${encodeURIComponent(r.run_id)}` }));
  // "Chạy lại cùng profile" chỉ nạp profile (chỉ đọc) -> cho phép cả khi run đang chạy (đường Run B song song A)
  actions.append(btn(t('home.rerun_same'), { small: true, onClick: (ev, el) => rerunSame(r, el) }));
  if (st !== 'running') actions.append(btn(t('home.rerun_fresh'), { small: true, kind: 'ghost', onClick: () => rerunFresh(r) }));
  row.append(h('div', {}, title, meta), right, actions);
  return row;
}

/** Nạp profile cũ của run -> wizard 5 (đường cho Run B / so sánh A/B). */
async function rerunSame(r, el) {
  busy(el, true);
  try {
    const d = await api(`/api/run/${encodeURIComponent(r.run_id)}/profile`);
    const p = d.profile;
    const settings = await api('/api/settings').catch(() => null);
    wiz.reset();
    // DB/export mới theo ngày hôm nay — không ghi đè run cũ
    const outDir = (settings && settings.out_dir) || dirOf(p.paths && p.paths.db) || '';
    const paths = wiz.defaultPaths(p.repo, p.branch, outDir, (settings && settings.work_dir) || (p.paths && p.paths.work));
    // Run B: hậu tố _B (so sánh A/B) — tăng _C, _D… nếu đã trùng tên run cũ; W4 còn kiểm db_exists qua backend
    let suffix = 'B';
    const oldDb = ((p.paths && p.paths.db) || '').toLowerCase();
    while (paths.db.replace(/\.sqlite$/i, `_${suffix}.sqlite`).toLowerCase() === oldDb && suffix < 'Z') suffix = String.fromCharCode(suffix.charCodeAt(0) + 1);
    p.paths = { db: paths.db.replace(/\.sqlite$/i, `_${suffix}.sqlite`), export: `${paths.export}_${suffix}`, work: paths.work };
    wiz.set(p);
    wiz.setMeta({ prefilled_from: r.run_id, out_dir: outDir, work_dir: paths.work, settings, names_edited: true,
      db_name: p.paths.db.split(/[\\/]/).pop(), export_name: p.paths.export.split(/[\\/]/).pop(), repo_check: null });
    toast(t('home.prefilled', { id: r.run_id }), 'ok');
    navigate('wizard/5');
  } catch (e) {
    busy(el, false);
    if (e.status === 404 || e.status === 501) {
      // không có profile.json -> dựng từ bản ghi registry, bắt đầu ở bước 1
      wiz.reset();
      const p = wiz.defaultProfile(r.repo, r.branch);
      wiz.set(p);
      toast(t('home.no_profile_fallback'), 'warn', 6000);
      navigate('wizard/1');
    } else toast(`${e.message}${e.hint ? ' — ' + e.hint : ''}`, 'bad', 8000);
  }
}

async function rerunFresh(r) {
  const slug = wiz.slug(r.repo);
  const ok = await dialog({ title: t('home.rerun_fresh_title'), body: h('div', {}, h('p', {}, t('home.rerun_fresh_body', { repo: fmt.repoShort(r.repo), branch: r.branch || 'HEAD' })), h('p', { class: 'muted small' }, t('home.rerun_fresh_note'))),
    confirmText: t('home.rerun_fresh'), typedConfirm: slug, danger: true });
  if (!ok) return;
  wiz.reset();
  wiz.set(wiz.defaultProfile(r.repo, r.branch));
  wiz.setMeta({ fresh_from: r.run_id });
  navigate('wizard/1');
}

function dirOf(p) { if (!p) return ''; const i = Math.max(p.lastIndexOf('\\'), p.lastIndexOf('/')); return i > 0 ? p.slice(0, i) : ''; }
