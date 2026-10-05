/* Wizard 3/5 — Tool & tài nguyên: 5 rẻ + 3 đắt, giây/commit, image, slider luồng, Nâng cao chỉ đọc + Chế độ thí nghiệm. */
import { t, h, card, dialog, toast, notice, clear, wiz, fmt, preflightCache, PARAMS_V1, CHEAP_TOOLS_ALL } from '../app.js';

let alive = true;
let frame = null;
let warnBox = null;

const CHEAP = [
  { id: 'gitleaks', what: 'w3.what.gitleaks', img: 'zricethezav/gitleaks' },
  { id: 'trufflehog', what: 'w3.what.trufflehog', img: 'trufflesecurity/trufflehog' },
  { id: 'semgrep', what: 'w3.what.semgrep', img: 'semgrep/semgrep' },
  { id: 'bearer', what: 'w3.what.bearer', img: 'bearer/bearer' },
  { id: 'horusec', what: 'w3.what.horusec', img: 'horuszup/horusec-cli' },
];
const EXP = [
  { id: 'findsecbugs', name: 'FindSecBugs', what: 'w3.what.findsecbugs', img: 'orch-findsecbugs' },
  { id: 'sonar', name: 'SonarQube', what: 'w3.what.sonar', img: 'sonarqube' },
  { id: 'codeql', name: 'CodeQL', what: 'w3.what.codeql', img: 'orch-codeql' },
];

export async function render(root, ctx) {
  alive = true;
  const p = wiz.ensure();
  const meta = wiz.meta();
  const pf = preflightCache.get() || {};
  const est = meta.estimate || {};
  const speed = est.speed || {};
  const cpu = Number(pf.cpu) || (navigator.hardwareConcurrency || 8);
  const memGb = Number(pf.docker_mem_gb) || 0;
  const expMax = Math.max(1, memGb ? Math.floor(memGb / 3) : 1);
  const imagesItem = (pf.items || []).find(x => x.id === 'images') || {};
  const imgDetail = (imagesItem.detail || '').toLowerCase();

  frame = wiz.frame(root, { step: 3, title: t('w3.title'), lead: t('w3.lead'), backHref: '#/wizard/2', nextHref: '#/wizard/4',
    headerRight: h('span', { class: 'tag' }, `CPU ${cpu} · ${t('pf.docker_ram')} ${memGb ? memGb + ' GB' : '—'}`) });

  const imgStatus = (tool) => {
    if (!pf.items) return h('span', { class: 'muted' }, '—');
    const missing = imgDetail.includes(tool.id) || (tool.id === 'findsecbugs' && imgDetail.includes('orch-findsecbugs'));
    if (imagesItem.level === 'ok' || !missing) return h('span', { class: 'badge ok' }, t('w3.img_ok'));
    return h('span', { class: 'badge warn' }, imgDetail.includes('build') && tool.id === 'findsecbugs' ? t('w3.img_build') : t('w3.img_missing'));
  };
  const secs = (id) => speed[id] !== undefined ? `~${speed[id]} s` : t('w3.sec_unknown');

  // ---- bảng rẻ ----
  const cheapTbl = h('table', { class: 'tbl' }, h('thead', {}, h('tr', {}, h('th', {}, ''), h('th', {}, t('w3.tool')), h('th', {}, t('w3.catches')), h('th', { class: 'num' }, t('w3.sec_per_commit')), h('th', {}, t('w3.image')))));
  const cb = h('tbody');
  for (const tl of CHEAP) {
    const chk = h('input', { type: 'checkbox', id: 'w3-c-' + tl.id, checked: (p.cheap_tools || []).includes(tl.id), 'aria-label': tl.id });
    chk.addEventListener('change', () => { wiz.patch(x => { const s = new Set(x.cheap_tools || []); if (chk.checked) s.add(tl.id); else s.delete(tl.id); x.cheap_tools = CHEAP_TOOLS_ALL.filter(c => s.has(c)); }); refreshWarnings(); });
    cb.append(h('tr', { class: 'tool-row' }, h('td', {}, chk), h('td', {}, h('label', { for: 'w3-c-' + tl.id, class: 'mono', style: { fontWeight: 600 } }, tl.id)), h('td', { class: 'muted' }, t(tl.what)), h('td', { class: 'num mono' }, secs(tl.id)), h('td', {}, imgStatus(tl))));
  }
  cheapTbl.append(cb);

  // ---- bảng đắt ----
  const expTbl = h('table', { class: 'tbl' }, h('thead', {}, h('tr', {}, h('th', {}, ''), h('th', {}, t('w3.tool')), h('th', {}, t('w3.catches')), h('th', { class: 'num' }, t('w3.sec_per_commit')), h('th', {}, t('w3.image')))));
  const eb = h('tbody');
  for (const tl of EXP) {
    const on = tl.id === 'codeql' ? !!p.codeql : (p.expensive_tools || []).includes(tl.id);
    const chk = h('input', { type: 'checkbox', id: 'w3-e-' + tl.id, checked: on, 'aria-label': tl.name });
    chk.addEventListener('change', async () => {
      if (tl.id === 'codeql') {
        if (chk.checked) {
          const ok = await dialog({ title: t('w3.codeql_title'), body: h('div', {}, h('p', {}, t('w3.codeql_body')), memGb && memGb < 16 ? notice('warn', t('w3.codeql_ram', { gb: memGb })) : null), confirmText: t('w3.codeql_enable') });
          if (!ok) { chk.checked = false; return; }
        }
        wiz.patch(x => { x.codeql = chk.checked; });
      } else wiz.patch(x => { const s = new Set(x.expensive_tools || []); if (chk.checked) s.add(tl.id); else s.delete(tl.id); x.expensive_tools = ['findsecbugs', 'sonar'].filter(c => s.has(c)); });
      refreshWarnings();
    });
    const sec = tl.id === 'codeql' ? t('w3.codeql_time') : secs(tl.id);
    eb.append(h('tr', { class: 'tool-row' }, h('td', {}, chk), h('td', {}, h('label', { for: 'w3-e-' + tl.id, style: { fontWeight: 600 } }, tl.name), tl.id === 'sonar' ? h('div', { class: 'small muted' }, t('w3.sonar_port', { port: p.sonar_port || 9000 })) : null), h('td', { class: 'muted' }, t(tl.what)), h('td', { class: 'num mono' }, sec), h('td', {}, imgStatus(tl))));
  }
  expTbl.append(eb);
  const buildHint = speed.build_cold_s ? t('w3.build_time', { cold: fmt.minutes(speed.build_cold_s / 60), warm: fmt.minutes(speed.build_warm_s / 60) }) : t('w3.build_time_default');

  warnBox = h('div', { class: 'stack' });

  // ---- slider ----
  const scanRange = h('input', { type: 'range', id: 'w3-scan', min: '1', max: String(cpu), step: '1', value: String(Math.min(cpu, p.workers.scan || 4)) });
  const scanVal = h('span', { class: 'range-val', 'aria-live': 'polite' }, scanRange.value);
  scanRange.addEventListener('input', () => { scanVal.textContent = scanRange.value; wiz.patch(x => { x.workers.scan = parseInt(scanRange.value, 10); }); });
  const expRange = h('input', { type: 'range', id: 'w3-exp', min: '1', max: String(expMax), step: '1', value: String(Math.min(expMax, p.workers.expensive || 1)) });
  const expVal = h('span', { class: 'range-val', 'aria-live': 'polite' }, expRange.value);
  expRange.addEventListener('input', () => { expVal.textContent = expRange.value; wiz.patch(x => { x.workers.expensive = parseInt(expRange.value, 10); }); });
  wiz.patch(x => { x.workers.scan = parseInt(scanRange.value, 10); x.workers.expensive = parseInt(expRange.value, 10); });
  const resCard = card({ title: t('w3.resources'), body: h('div', {},
    h('label', { class: 'field', for: 'w3-scan' }, h('span', {}, t('w3.scan_workers')), h('div', { class: 'range-row' }, scanRange, scanVal), h('div', { class: 'help' }, t('w3.scan_workers_hint', { n: Math.max(1, Math.floor(cpu / 2)), cpu }))),
    h('label', { class: 'field', for: 'w3-exp' }, h('span', {}, t('w3.exp_workers')), h('div', { class: 'range-row' }, expRange, expVal), h('div', { class: 'help' }, memGb ? t('w3.exp_workers_hint', { max: expMax, gb: memGb }) : t('w3.exp_workers_hint_nomem'))),
    h('div', { class: 'check' }, h('input', { type: 'checkbox', checked: true, disabled: true, 'aria-label': t('w3.m2_cache') }), h('span', {}, t('w3.m2_cache'), ' ', h('span', { class: 'muted small' }, t('w3.m2_cache_hint'))))) });

  // ---- Nâng cao (chỉ đọc) + Chế độ thí nghiệm ----
  const adv = h('details', { class: 'fold', open: !!(p.experiment && p.experiment.enabled) });
  const advBody = h('div', { class: 'fold-b' });
  adv.append(h('summary', {}, t('w3.advanced'), h('span', { class: 'tag' }, t('w3.v1_locked'))), advBody);
  drawAdvanced(advBody);

  frame.body.append(
    card({ title: t('w3.cheap_tier'), subtitle: t('w3.cheap_sub'), body: h('div', { class: 'tbl-wrap' }, cheapTbl) }),
    card({ title: t('w3.exp_tier'), subtitle: buildHint, body: h('div', { class: 'tbl-wrap' }, expTbl) }),
    warnBox, resCard, adv);
  refreshWarnings();
}

export function destroy() { alive = false; frame = null; warnBox = null; }

function refreshWarnings() {
  if (!warnBox) return;
  const p = wiz.ensure();
  clear(warnBox);
  const nCheap = (p.cheap_tools || []).length;
  const exp = p.expensive_tools || [];
  if (nCheap === 0) warnBox.append(notice('bad', t('w3.warn_no_cheap')));
  else if (nCheap < CHEAP_TOOLS_ALL.length) warnBox.append(notice('warn', t('w3.warn_fewer_cheap', { n: nCheap, all: CHEAP_TOOLS_ALL.length })));
  if (nCheap > 0 && nCheap < 2) warnBox.append(notice('warn', t('w3.warn_silver')));
  if (exp.length < 2) warnBox.append(notice('warn', h('div', {}, h('strong', {}, t('w3.warn_gold_title')), ' ', t('w3.warn_gold', { n: exp.length }))));
  if (exp.length === 0 && p.include_clean) warnBox.append(notice('warn', t('w3.warn_no_exp_clean')));
  if (p.codeql) warnBox.append(notice('warn', t('w3.warn_codeql')));
  if (frame) frame.next.disabled = nCheap === 0 && exp.length === 0 && !p.codeql;
}

function drawAdvanced(body) {
  const p = wiz.ensure();
  clear(body);
  const on = !!(p.experiment && p.experiment.enabled);
  const params = p.params_v1 || PARAMS_V1;
  const KEYS = [['line_window', 'LINE_WINDOW'], ['gold_min_expensive', 'GOLD_MIN_EXPENSIVE'], ['gold_allow_1exp_1cheap', 'GOLD_ALLOW_1EXP_1CHEAP'], ['silver_min_cheap', 'SILVER_MIN_CHEAP'], ['noise_cwe', 'NOISE_CWE']];
  body.append(h('p', { class: 'help', style: { marginTop: '10px' } }, t('w3.advanced_hint')));
  const dl = h('dl', { class: 'kv' });
  for (const [k, label] of KEYS) {
    const v = params[k];
    if (!on) dl.append(h('dt', { class: 'mono' }, label), h('dd', { class: 'mono' }, Array.isArray(v) ? v.join(', ') : String(v), v !== PARAMS_V1[k] && JSON.stringify(v) !== JSON.stringify(PARAMS_V1[k]) ? h('span', { class: 'badge warn', style: { marginLeft: '8px' } }, t('w3.changed')) : null));
    else {
      const inp = h('input', { class: 'input mono', id: 'w3-p-' + k, value: Array.isArray(v) ? v.join(',') : String(v), 'aria-label': label, type: Array.isArray(v) ? 'text' : 'number', min: Array.isArray(v) ? undefined : '0' });
      inp.addEventListener('input', () => wiz.patch(x => { x.params_v1[k] = Array.isArray(PARAMS_V1[k]) ? inp.value.split(',').map(s => s.trim()).filter(Boolean) : parseInt(inp.value, 10) || 0; }));
      dl.append(h('dt', { class: 'mono' }, h('label', { for: 'w3-p-' + k }, label)), h('dd', {}, inp, h('div', { class: 'help' }, t('w3.default_is', { v: Array.isArray(PARAMS_V1[k]) ? PARAMS_V1[k].join(',') : PARAMS_V1[k] }))));
    }
  }
  body.append(dl);
  if (on) {
    body.append(notice('fix', h('div', {}, h('strong', {}, t('w3.exp_on')), h('div', { class: 'small' }, t('w3.exp_reason', { r: p.experiment.reason }))),
      { action: h('button', { class: 'btn small', type: 'button', onClick: () => { wiz.patch(x => { x.experiment = null; x.params_v1 = JSON.parse(JSON.stringify(PARAMS_V1)); }); drawAdvanced(body); toast(t('w3.exp_off_done'), 'ok'); } }, t('w3.exp_off')) }));
  } else {
    body.append(h('div', { style: { marginTop: '12px' } }, h('button', { class: 'btn small', type: 'button', onClick: async () => {
      const r = await dialog({ title: t('w3.exp_title'), body: t('w3.exp_body'), confirmText: t('w3.exp_enable'), danger: true,
        fields: [{ name: 'reason', label: t('w3.exp_reason_label'), textarea: true, required: true, minLen: 10, help: t('w3.exp_reason_help') }] });
      if (!r || !r.values) return;
      wiz.patch(x => { x.experiment = { enabled: true, reason: r.values.reason }; });
      drawAdvanced(body);
      toast(t('w3.exp_on_done'), 'warn');
    } }, '⚗ ' + t('w3.exp_mode'))));
  }
}
