/* Wizard 1/5 — Repo & nhánh: chuẩn hoá URL, /api/repo/check, chọn nhánh từ danh sách, PAT (sessionStorage). */
import { api, t, h, btn, card, toast, errorBox, notice, clear, busy, wiz, fmt } from '../app.js';

let alive = true;
let els = {};

export async function render(root, ctx) {
  alive = true;
  const p = wiz.ensure();
  const meta = wiz.meta();
  const frame = wiz.frame(root, { step: 1, title: t('w1.title'), lead: t('w1.lead'), nextHref: '#/wizard/2', nextDisabled: true });
  els = { frame, p };

  // --- URL ---
  const url = h('input', { class: 'input mono', id: 'w1-url', type: 'url', placeholder: 'https://github.com/owner/repo', value: p.repo || '', autocomplete: 'off', spellcheck: 'false', 'aria-describedby': 'w1-canon' });
  const check = btn(t('w1.check'), { kind: 'primary', onClick: () => doCheck(ctx) });
  const canon = h('div', { class: 'help', id: 'w1-canon' });
  const urlErr = h('div', { class: 'err', id: 'w1-url-err' });
  url.addEventListener('input', () => { onUrlInput(); });
  url.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); doCheck(ctx); } });

  // --- PAT ---
  const patBox = h('input', { type: 'checkbox', id: 'w1-private' });
  const pat = h('input', { class: 'input mono', id: 'w1-pat', type: 'password', placeholder: 'ghp_…', autocomplete: 'off', disabled: true });
  patBox.addEventListener('change', () => { pat.disabled = !patBox.checked; if (!patBox.checked) { pat.value = ''; wiz.setMeta({ pat: null }); } else pat.focus(); });
  pat.addEventListener('input', () => wiz.setMeta({ pat: pat.value || null }));
  if (meta.pat) { patBox.checked = true; pat.disabled = false; pat.value = meta.pat; }

  const result = h('div', { class: 'stack', id: 'w1-result' });
  els = Object.assign(els, { url, check, canon, urlErr, patBox, pat, result });

  frame.body.append(card({ body: h('div', {},
    h('label', { class: 'field', for: 'w1-url' }, h('span', {}, t('w1.url')),
      h('div', { class: 'inline' }, url, check), canon, urlErr),
    h('label', { class: 'check', for: 'w1-private' }, patBox, h('span', {}, t('w1.private'))),
    h('label', { class: 'field', for: 'w1-pat' }, h('span', { class: 'sr-only' }, t('w1.pat')), pat, h('div', { class: 'help' }, t('w1.pat_hint'))),
  ) }), result);

  onUrlInput();
  // Có repo_check cũ cho đúng URL -> vẽ lại; có repo mà chưa check (prefill/QA) -> tự kiểm tra
  if (meta.repo_check && meta.repo_check.canon === wiz.canonRepo(p.repo)) drawResult(meta.repo_check, ctx);
  else if (p.repo) doCheck(ctx);
}

export function destroy() { alive = false; }

function onUrlInput() {
  const raw = els.url.value;
  const c = wiz.canonRepo(raw);
  els.urlErr.textContent = '';
  els.url.classList.remove('invalid');
  if (!raw.trim()) { els.canon.textContent = t('w1.canon_hint'); return; }
  if (!wiz.isGithub(raw)) {
    els.url.classList.add('invalid');
    els.urlErr.textContent = /^git@|^ssh:/.test(raw.trim()) ? t('w1.err_ssh') : /gitlab|bitbucket/i.test(raw) ? t('w1.err_not_github') : t('w1.err_url');
  }
  els.canon.textContent = c !== raw.trim() ? t('w1.canon', { c }) : t('w1.canon_ok');
  const hint = wiz.branchHint(raw);
  if (hint) els.canon.textContent += ' · ' + t('w1.branch_from_url', { b: hint });
}

async function doCheck(ctx) {
  const raw = els.url.value;
  if (!wiz.isGithub(raw)) { onUrlInput(); els.url.focus(); return; }
  const canon = wiz.canonRepo(raw);
  const hint = wiz.branchHint(raw);
  wiz.patch(p => { if (p.repo !== canon) { p.branch = hint || ''; } p.repo = canon; });
  if (hint) wiz.patch(p => { p.branch = hint; });
  wiz.setMeta({ repo_check: null });
  busy(els.check, true);
  clear(els.result).append(card({ body: h('div', { class: 'row' }, h('span', { class: 'spin', 'aria-hidden': 'true', style: { width: '16px', height: '16px', border: '2px solid #1F5F8B', borderRightColor: 'transparent', borderRadius: '50%', display: 'inline-block', animation: 'spin .8s linear infinite' } }), t('w1.checking')) }));
  els.frame.next.disabled = true;
  try {
    const body = { url: canon };
    const pat = wiz.meta().pat; if (els.patBox.checked && pat) body.pat = pat;
    const d = await api('/api/repo/check', { method: 'POST', body, timeout: 90000 });
    if (!alive) return;
    wiz.setMeta({ repo_check: d });
    drawResult(d, ctx);
  } catch (e) {
    if (!alive) return;
    let hint = e.hint;
    if (e.status === 401 || e.status === 403) hint = t('w1.err_auth_hint');
    else if (e.status === 404) hint = t('w1.err_404_hint');
    else if (e.code === 'timeout') hint = t('w1.err_timeout_hint');
    // Error.message không enumerable -> không dùng Object.assign
    clear(els.result).append(errorBox({ status: e.status, code: e.code, message: e.message, hint }, () => doCheck(ctx)));
  } finally { if (alive) busy(els.check, false); }
}

function drawResult(d, ctx) {
  const p = wiz.ensure();
  clear(els.result);
  const branches = d.branches || [];
  const tags = d.tags || [];
  if (!branches.length) {
    els.result.append(notice('bad', h('div', {}, h('strong', {}, t('w1.empty_repo')), ' ', (d.warnings || []).join(' · '))));
    els.frame.next.disabled = true;
    return;
  }
  // tóm tắt
  const bits = [d.public === false ? t('w1.private_repo') : t('w1.public'), d.java_maven ? 'Java / Maven' : t('w1.not_java'),
    d.commit_count !== null && d.commit_count !== undefined ? t('w1.n_commits', { n: fmt.num(d.commit_count) }) : t('w1.commits_unknown'),
    d.default_branch ? t('w1.default_branch', { b: d.default_branch }) : null].filter(Boolean);
  const okLine = notice(d.java_maven ? 'ok' : 'warn', h('div', {}, h('div', {}, h('strong', {}, d.canon || p.repo)), h('div', { class: 'small' }, bits.join(' · '))));

  // nhánh
  const sel = h('select', { class: 'input', id: 'w1-branch', 'aria-describedby': 'w1-branch-help' });
  const current = p.branch && branches.includes(p.branch) ? p.branch : (d.default_branch && branches.includes(d.default_branch) ? d.default_branch : branches[0]);
  for (const b of branches) sel.append(h('option', { value: b, selected: b === current }, b + (b === d.default_branch ? ` (${t('w1.default')})` : '')));
  if (tags.length) { const og = h('optgroup', { label: t('w1.tags') }); for (const tg of tags) og.append(h('option', { value: tg }, tg)); sel.append(og); }
  wiz.patch(x => { x.branch = current; });
  sel.addEventListener('change', () => { wiz.patch(x => { x.branch = sel.value; }); updateNext(d); });
  const noMain = !branches.includes('main') && !branches.includes('master');
  const branchCard = card({ title: t('w1.branch'), body: h('div', {},
    h('label', { class: 'field', for: 'w1-branch' }, h('span', { class: 'sr-only' }, t('w1.branch')), sel,
      h('div', { class: 'help', id: 'w1-branch-help' }, t('w1.branch_counts', { b: branches.length, t: tags.length }) + ' · ' + t('w1.branch_hint'))),
    noMain ? notice('warn', t('w1.branch_warn_nomain', { b: d.default_branch || branches[0] })) : null) });

  // phát hiện
  const det = h('dl', { class: 'kv' });
  const kv = (k, v) => det.append(h('dt', {}, k), h('dd', {}, v));
  kv('pom.xml', d.java_maven ? '✓ ' + t('w1.found') : '✗ ' + t('w1.not_found'));
  kv('JDK', d.jdk ? `${d.jdk} · ${t('w1.jdk_auto')}` : '—');
  kv(t('w1.modules'), d.modules !== undefined && d.modules !== null ? fmt.num(d.modules) : '—');
  kv('SecurityConfig', d.security_config_count !== undefined && d.security_config_count !== null ? fmt.num(d.security_config_count) : '—');
  kv('SNAPSHOT', d.snapshot_risk ? '⚠ ' + t('w1.snapshot_risk') : '✓ ' + t('w1.snapshot_ok'));
  const detCard = card({ title: t('w1.detected'), body: det });

  const warns = (d.warnings || []).map(w => notice('warn', w));
  els.result.append(okLine, branchCard, detCard, ...warns);

  if (!d.java_maven) {
    const off = btn(t('w1.disable_expensive'), { small: true, onClick: () => { wiz.patch(x => { x.expensive_tools = []; x.codeql = false; x.include_clean = false; }); toast(t('w1.disabled_expensive'), 'ok'); off.disabled = true; } });
    els.result.append(notice('warn', h('div', {}, h('strong', {}, t('w1.not_java_title')), h('div', { class: 'small' }, t('w1.not_java_body'))), { action: off }));
  }
  updateNext(d);
}

function updateNext(d) {
  const p = wiz.ensure();
  els.frame.next.disabled = !(p.repo && p.branch && (d.branches || []).length);
}
