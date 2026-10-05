/* Wizard 5/5 — Xem lại: tóm tắt profile, ước tính cold/warm, lệnh CLI PowerShell/bash, Lưu profile, Chạy thử 3 commit, Chạy. */
import { api, t, h, btn, card, dialog, toast, errorBox, notice, skeleton, clear, busy, wiz, fmt, copyText, navigate } from '../app.js';

let alive = true;
let frame = null;

export async function render(root, ctx) {
  alive = true;
  const p = wiz.ensure();
  const meta = wiz.meta();
  frame = wiz.frame(root, { step: 5, title: t('w5.title'), lead: t('w5.lead'), backHref: '#/wizard/4', nextLabel: '▶ ' + t('w5.run'), onNext: () => start(false) });
  frame.next.dataset.test = 'run';   // W5-1
  if (meta.preflight_skipped) frame.body.append(notice('warn', t('w5.preflight_skipped')));
  const errs = wiz.validate(p);
  if (meta.prefilled_from) frame.body.append(notice('info', t('w5.prefilled', { id: meta.prefilled_from })));
  if (errs.length) frame.body.append(notice('bad', h('div', {}, h('strong', {}, t('w5.invalid')), h('ul', { class: 'dot-list' }, errs.map(e => h('li', {}, e))))));
  if (meta.resume) frame.body.append(notice('fix', t('w5.resume_note')));
  if (meta.overwrite) frame.body.append(notice('bad', t('w5.overwrite_note')));
  if (p.experiment && p.experiment.enabled) frame.body.append(notice('fix', h('div', {}, h('strong', {}, t('w3.exp_on')), ' · ', p.experiment.reason)));

  // ---- tóm tắt ----
  const sc = p.scope || {};
  const scopeTxt = sc.mode === 'time' ? `${sc.since || '…'} → ${sc.until || t('w5.head')}` : sc.mode === 'count' ? t('w2.count') + ` · ${fmt.num(sc.max)}` : sc.mode === 'sha' ? `${sc.from_sha || '…'} → ${sc.to_sha || 'HEAD'}` : t('w2.all');
  const kv = h('dl', { class: 'kv' });
  const row = (k, v, href) => kv.append(h('dt', {}, k), h('dd', { class: 'row between' }, h('span', {}, v), href ? h('a', { class: 'small', href }, t('edit')) : null));
  row(t('w5.repo'), h('span', { class: 'mono' }, fmt.repoShort(p.repo) + ' · ' + (p.branch || 'HEAD')), '#/wizard/1');
  row(t('w5.scope'), scopeTxt, '#/wizard/2');
  row(t('w5.cheap'), `${(p.cheap_tools || []).length} ${t('w5.tools')} · ${p.workers.scan} ${t('w5.threads')}`, '#/wizard/3');
  row(t('w5.expensive'), `${(p.expensive_tools || []).map(x => ({ findsecbugs: 'FindSecBugs', sonar: 'Sonar' }[x] || x)).join(' + ') || t('w5.none')} · ${p.workers.expensive} ${t('w5.threads')} · CodeQL ${p.codeql ? t('on') : t('off')}`, '#/wizard/3');
  row(t('w5.clean'), p.include_clean ? t('w5.clean_on') : t('w5.clean_off'), '#/wizard/2');
  row(t('w5.db'), h('span', { class: 'mono small' }, p.paths.db || '—'), '#/wizard/4');
  row(t('w5.export'), h('span', { class: 'mono small' }, p.paths.export || '—'), '#/wizard/4');
  row(t('w5.formats'), (meta.formats || ['jsonl']).join(', ') + ' · raw', '#/wizard/4');
  frame.body.append(card({ title: t('w5.config'), body: kv }));

  // ---- ước tính ----
  const estBody = h('div', {}, skeleton(2, { lines: true }));
  frame.body.append(card({ title: t('w2.estimate'), body: estBody }));
  loadEstimate(estBody, p);

  // ---- CLI ----
  const cliBody = h('div', {}, skeleton(2, { lines: true }));
  frame.body.append(card({ title: t('w5.cli'), subtitle: t('w5.cli_hint'), body: cliBody }));
  loadShell(cliBody, p, 'powershell');

  // ---- footer phụ ----
  const saveBtn = btn(t('w5.save_profile') + '…', { onClick: () => saveProfile(p), test: 'save' });
  const smokeBtn = btn(t('w5.smoke'), { onClick: () => start(true), disabled: errs.length > 0, test: 'smoke' });
  frame.page.querySelector('.wiz-foot .row').append(saveBtn, smokeBtn);
  frame.next.disabled = errs.length > 0;
}

export function destroy() { alive = false; frame = null; }

async function loadEstimate(body, p) {
  try {
    const d = await api('/api/estimate', { method: 'POST', body: { profile: p } });
    if (!alive) return;
    wiz.setMeta({ estimate: d });
    clear(body);
    const cold = d.expensive_minutes_cold, warm = d.expensive_minutes_warm;
    const total = (d.cheap_minutes || 0) + (cold || 0);
    body.append(h('div', { class: 'tiles' },
      tile(fmt.num(d.commits_after_filter), t('w2.after_filter')),
      tile(fmt.minutes(d.cheap_minutes), t('w2.cheap_time')),
      tile(cold !== undefined ? fmt.minutes(cold) : '—', t('w5.exp_cold')),
      tile(warm !== undefined ? fmt.minutes(warm) : '—', t('w5.exp_warm')),
      tile(d.disk_gb !== undefined ? `+${Number(d.disk_gb).toFixed(1)} GB` : '—', t('w2.disk')),
      tile('≈ ' + fmt.minutes(total), t('w5.total'))),
      h('p', { class: 'help', style: { marginTop: '10px' } }, (d.speed_source === 'measured' ? t('w2.speed_measured', { s: d.speed && d.speed.cheap_s_per_commit || '?' }) : t('w2.speed_default')) + ' · ' + t('w5.bg_ok')),
      h('div', {}, warm === undefined ? notice('warn', t('w5.partial_estimate')) : null));
  } catch (e) {
    if (!alive) return;
    clear(body).append(notice('warn', h('div', {}, h('strong', {}, t('w2.est_unavailable')), ' ', e.message || '', e.hint ? h('div', { class: 'small' }, e.hint) : null)));
    if (e.code === 'clone_pending') setTimeout(() => { if (alive) loadEstimate(body, p); }, 5000);   // clone nền -> thử lại
  }
}

async function loadShell(body, p, shell) {
  clear(body);
  const tabs = h('div', { class: 'tabs', role: 'tablist' });
  for (const s of ['powershell', 'bash']) tabs.append(h('button', { type: 'button', role: 'tab', 'aria-selected': s === shell ? 'true' : 'false', onClick: () => loadShell(body, p, s) }, s === 'powershell' ? 'PowerShell' : 'bash'));
  const pre = h('pre', { class: 'code', tabindex: '0' }, t('loading'));
  const copy = btn(t('copy'), { small: true, disabled: true, onClick: () => copyText(pre.textContent) });
  body.append(tabs, h('div', { class: 'copy-wrap' }, pre, copy));
  try {
    const d = await api('/api/shell', { method: 'POST', body: { profile: p, shell } });
    if (!alive) return;
    pre.textContent = d.command || '';
    copy.disabled = !d.command;
    if (d.errors && d.errors.length) body.append(notice('warn', h('div', {}, h('strong', {}, t('w5.server_errors')), h('ul', { class: 'dot-list' }, d.errors.map(e => h('li', {}, e))))));
  } catch (e) {
    if (!alive) return;
    pre.replaceWith(errorBox(e, () => loadShell(body, p, shell)));
    copy.remove();
  }
}

async function saveProfile(p) {
  const def = `${wiz.slug(p.repo).replace(/^.*__/, '')}-${p.scope.mode === 'count' ? p.scope.max : p.scope.mode}`;
  const r = await dialog({ title: t('w5.save_profile'), body: t('w5.save_body'), confirmText: t('save'),
    fields: [{ name: 'name', label: t('w5.profile_name'), value: def, required: true, help: t('w5.profile_name_help') }] });
  if (!r || !r.values) return;
  try {
    const d = await api('/api/profiles', { method: 'POST', body: { name: r.values.name, profile: p } });
    toast(t('w5.saved', { path: d.path || r.values.name }), 'ok', 6000);
  } catch (e) { toast(`${e.message}${e.hint ? ' — ' + e.hint : ''}`, 'bad', 8000); }
}

async function start(smoke) {
  if (!frame) return;
  const p = wiz.ensure();
  const meta = wiz.meta();
  const errs = wiz.validate(p);
  if (errs.length) { toast(errs[0], 'bad'); return; }
  if (!smoke && meta.overwrite) {
    const ok = await dialog({ title: t('w4.overwrite_title'), body: t('w5.overwrite_confirm', { db: p.paths.db }), confirmText: t('w4.overwrite'), danger: true });
    if (!ok) return;
  }
  const b = frame.next;
  busy(b, true);
  try {
    if (meta.preflight_skipped) p.preflight_skipped = true;   // PF-2: ghi vào profile -> run_meta.config_snapshot
    const body = { profile: p, smoke: !!smoke, formats: meta.formats || ['jsonl'], notify: meta.notify !== false, resume: !!meta.resume && !smoke, overwrite: !!meta.overwrite && !smoke, preflight_skipped: !!meta.preflight_skipped };
    const d = await api('/api/run/start', { method: 'POST', body, timeout: 120000 });
    if (!alive) return;
    toast(smoke ? t('w5.smoke_started', { id: d.run_id }) : t('w5.started', { id: d.run_id }), 'ok');
    navigate(`run/${encodeURIComponent(d.run_id)}${smoke ? '?smoke=1' : ''}`);
  } catch (e) {
    if (!alive) return;
    busy(b, false);
    const box = errorBox(e, () => { box.remove(); start(smoke); });
    frame.body.prepend(box);
    box.scrollIntoView({ block: 'nearest' });
  }
}
function tile(v, k) { return h('div', { class: 'tile' }, h('div', { class: 'v' }, v), h('div', { class: 'k' }, k)); }
