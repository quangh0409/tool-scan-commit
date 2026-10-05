/* Màn 0 — Preflight: 13 mục, 3 mức ok/fix/warn/bad, sửa từng mục / sửa tất cả, JSON chẩn đoán. */
import { api, t, h, btn, card, toast, dialog, empty, errorBox, skeleton, notice, progress, clear, busy, preflightCache, navigate, fmt, wiz } from '../app.js';

let alive = true;
let data = null;

const ICON = { ok: '✓', fix: '🔧', warn: '⚠', bad: '✕', pending: '…' };

export async function render(root, ctx) {
  alive = true;
  data = null;
  const page = h('div', { class: 'page-narrow stack' });
  root.append(page);
  await load(page, ctx);
}

export function destroy() { alive = false; }

async function load(page, ctx) {
  clear(page);
  page.append(
    h('div', {}, h('h1', {}, t('pf.title')), h('p', { class: 'lead' }, t('pf.lead'))),
    card({ list: true, body: skeleton(8) }),
    h('div', { class: 'row end' }, btn(t('pf.fix_all'), { disabled: true }), btn(t('pf.recheck'), { disabled: true }), btn(t('continue'), { kind: 'primary', disabled: true })));
  try {
    data = await api('/api/preflight', { timeout: 180000 });  // Docker bận: ~10 lệnh docker nối tiếp
  } catch (e) {
    if (!alive) return;
    clear(page);
    page.append(h('div', {}, h('h1', {}, t('pf.title'))), errorBox(e, () => load(page, ctx)),
      h('div', { class: 'row end' }, skipButton()));
    return;
  }
  if (!alive) return;
  preflightCache.set(data);
  draw(page, ctx);
}

function summarize(items) {
  const c = { ok: 0, fix: 0, warn: 0, bad: 0 };
  for (const it of items) c[it.level] = (c[it.level] || 0) + 1;
  return c;
}

function draw(page, ctx) {
  clear(page);
  const items = (data && data.items) || [];
  const c = summarize(items);
  const partial = data && (data.docker_mem_gb === undefined || data.cpu === undefined || items.length < 13);
  page.append(h('div', {}, h('h1', {}, t('pf.title')), h('p', { class: 'lead' }, t('pf.lead'))));

  // PF-1: rỗng -> chỉ hiện empty (không kèm banner partial)
  if (!items.length) {
    page.append(card({ body: empty(t('pf.empty'), { action: btn(t('pf.recheck'), { onClick: () => load(page, ctx) }) }) }),
      h('div', { class: 'row end' }, skipButton()));
    return;
  }
  // tóm tắt tài nguyên
  page.append(h('div', { class: 'tiles' },
    tile(data.docker_mem_gb !== undefined ? `${fmt.num(data.docker_mem_gb)} GB` : '—', t('pf.docker_ram')),
    tile(data.cpu !== undefined ? `${data.cpu}` : '—', t('pf.cpu')),
    tile(String(c.ok), t('pf.n_ok')), tile(String(c.fix), t('pf.n_fix')), tile(String(c.warn), t('pf.n_warn')), tile(String(c.bad), t('pf.n_bad'))));
  if (partial) page.append(notice('warn', t('pf.partial')));
  const list = h('div');
  for (const it of items) list.append(itemRow(it, page, ctx));
  page.append(card({ list: true, body: list }));

  // footer
  const fixable = items.filter(x => x.fix_available && x.level !== 'ok');
  const fixAll = btn(t('pf.fix_all') + (fixable.length ? ` (${fixable.length})` : ''), { disabled: !fixable.length, onClick: () => runFixAll(page, ctx, fixable) });
  const recheck = btn(t('pf.recheck'), { onClick: () => load(page, ctx) });
  const json = btn(t('pf.view_json'), { kind: 'ghost', onClick: () => dialog({ title: t('pf.view_json'), body: h('pre', { class: 'code' }, JSON.stringify(data, null, 2)), confirmText: t('close'), hideCancel: true }) });
  const cont = btn(t('continue') + ' ▸', { kind: 'primary', disabled: c.bad > 0, onClick: () => confirmContinue(c.warn > 0 || c.fix > 0) });
  const foot = h('div', { class: 'row between' }, h('div', { class: 'row gap-s' }, fixAll, recheck, json), cont);
  // PF-2: mục ❌ không tự sửa (vd Git) -> vẫn có lối thoát: Bỏ qua kiểm tra (typed-confirm, ghi preflight_skipped)
  if (c.bad > 0) foot.append(h('div', { class: 'row end', style: { width: '100%' } }, h('span', { class: 'err' }, t('pf.blocked', { n: c.bad })), skipButton()));
  page.append(foot);
}

function skipButton() {
  return btn(t('pf.skip_anyway'), { kind: 'ghost', test: 'skip', onClick: async () => {
    const ok = await dialog({ title: t('pf.skip_title'), body: h('div', {}, h('p', {}, t('pf.skip_body')), h('p', { class: 'muted small' }, t('pf.skip_note'))),
      confirmText: t('pf.skip_confirm'), typedConfirm: 'BO QUA', danger: true });
    if (!ok) return;
    wiz.setMeta({ preflight_skipped: true });
    preflightCache.set(Object.assign({}, data || { items: [] }, { ready: true, skipped: true }));
    toast(t('pf.skipped_toast'), 'warn', 6000);
    navigate('home');
  } });
}

function tile(v, k) { return h('div', { class: 'tile' }, h('div', { class: 'v' }, v), h('div', { class: 'k' }, k)); }

function itemRow(it, page, ctx) {
  const lvl = it.level || 'pending';
  const row = h('div', { class: 'item', 'data-id': it.id });
  const mark = h('span', { class: `mark ${lvl}`, 'aria-label': t('level.' + lvl), title: t('level.' + lvl) }, ICON[lvl] || '?');
  const grow = h('div', { class: 'grow' }, h('div', {}, h('strong', {}, it.title || it.id), ' ', h('span', { class: 'tag' }, t('level.' + lvl))),
    it.detail ? h('div', { class: 'detail' }, it.detail) : null);
  row.append(mark, grow);
  if (it.fix_available && lvl !== 'ok') {
    const b = btn(fixLabel(it), { small: true, onClick: () => runFix(it, row, b, page, ctx) });
    row.append(b);
  }
  return row;
}

function fixLabel(it) {
  const m = { start_docker: 'pf.fix.start_docker', pick_port: 'pf.fix.pick_port', git_longpaths: 'pf.fix.git_longpaths', pull_images: 'pf.fix.pull_images' };
  return t(m[it.fix_id] || 'pf.fix.generic');
}

/** Gọi /api/preflight/fix lặp đến khi done (progress %). Trả true nếu ok. */
async function runFix(it, row, button, page, ctx, { silent = false } = {}) {
  const grow = row.querySelector('.grow');
  const old = grow.querySelector('.fixprog'); if (old) old.remove();
  const prog = h('div', { class: 'fixprog', style: { marginTop: '8px' } }, progress(0), h('div', { class: 'detail', 'aria-live': 'polite' }, t('pf.fixing')));
  grow.append(prog);
  if (button) busy(button, true);
  try {
    let guard = 0;
    for (;;) {
      const r = await api('/api/preflight/fix', { method: 'POST', body: { fix_id: it.fix_id }, timeout: 120000 });
      if (!alive) return false;
      const pct = r.progress !== undefined ? r.progress : (r.ok ? 100 : 0);
      prog.replaceChild(progress(pct, r.ok ? 'ok' : ''), prog.firstChild);
      prog.lastChild.textContent = r.detail || `${Math.round(pct)} %`;
      if (r.done === true || (r.ok && r.done === undefined)) break;
      if (r.ok === false && r.done !== false) throw { code: 'fix_failed', message: r.detail || t('pf.fix_failed') };
      if (++guard > 200) throw { code: 'fix_stuck', message: t('pf.fix_failed') };
      await new Promise(res => setTimeout(res, 300));
    }
    it.level = 'ok'; it.fix_available = false;
    row.querySelector('.mark').className = 'mark ok'; row.querySelector('.mark').textContent = ICON.ok;
    row.querySelector('.tag').textContent = t('level.ok');
    // PF-3: bỏ thanh tiến độ, ghi chi tiết mới vào dòng detail
    const det = row.querySelector('.detail');
    const finalDetail = prog.lastChild.textContent;
    prog.remove();
    if (det) det.textContent = finalDetail || det.textContent; else grow.append(h('div', { class: 'detail' }, finalDetail));
    if (button) button.remove();
    if (!silent) toast(t('pf.fixed', { title: it.title }), 'ok');
    return true;
  } catch (e) {
    if (!alive) return false;
    prog.remove();
    if (button) busy(button, false);
    const eb = errorBox(e, () => { eb.remove(); runFix(it, row, button, page, ctx); });
    eb.style.marginTop = '8px';
    grow.append(eb);
    return false;
  }
}

async function runFixAll(page, ctx, fixable) {
  const bar = notice('info', h('div', {}, h('div', { class: 'fixall-msg' }, t('pf.fix_all_running', { i: 0, n: fixable.length })), h('div', { style: { marginTop: '8px' } }, progress(0))));
  page.insertBefore(bar, page.children[2]);
  let okCount = 0;
  for (let i = 0; i < fixable.length; i++) {
    const it = fixable[i];
    if (!alive) return;
    bar.querySelector('.fixall-msg').textContent = t('pf.fix_all_running', { i: i + 1, n: fixable.length }) + ` · ${it.title}`;
    const row = page.querySelector(`.item[data-id="${it.id}"]`);
    const b = row && row.querySelector('.btn');
    const ok = await runFix(it, row, b, page, ctx, { silent: true });
    if (ok) okCount++;
    bar.querySelector('.prog').replaceWith(progress(((i + 1) / fixable.length) * 100));
  }
  bar.remove();
  toast(t('pf.fix_all_done', { ok: okCount, n: fixable.length }), okCount === fixable.length ? 'ok' : 'warn');
  await load(page, ctx);
}

async function confirmContinue(hasWarn) {
  if (hasWarn) {
    const ok = await dialog({ title: t('pf.continue_warn_title'), body: t('pf.continue_warn_body'), confirmText: t('pf.continue_anyway') });
    if (!ok) return;
  }
  if (data) preflightCache.set(Object.assign({}, data, { ready: true }));
  navigate('home');
}
