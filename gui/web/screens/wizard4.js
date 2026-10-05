/* Wizard 4/5 — Nơi lưu: thư mục kết quả/làm việc, tên DB/export tự sinh, validate đường dẫn, DB đã tồn tại, định dạng xuất. */
import { api, t, h, btn, card, dialog, toast, notice, clear, debounce, busy, wiz, fmt } from '../app.js';

let alive = true;
let frame = null;
let els = {};
let pickDirSupported = true;

export async function render(root, ctx) {
  alive = true;
  const p = wiz.ensure();
  let meta = wiz.meta();
  frame = wiz.frame(root, { step: 4, title: t('w4.title'), lead: t('w4.lead'), backHref: '#/wizard/3', nextHref: '#/wizard/5',
    headerRight: p.repo ? h('span', { class: 'tag mono' }, `${fmt.repoShort(p.repo)} · ${p.branch || 'HEAD'}`) : null });

  // settings mặc định (out_dir/work_dir/sonar_port) — lấy 1 lần
  if (!meta.settings) {
    try { const s = await api('/api/settings'); meta = wiz.setMeta({ settings: s }); } catch (_) { meta = wiz.setMeta({ settings: {} }); }
    if (!alive) return;
  }
  const s = meta.settings || {};
  let outDir = meta.out_dir || s.out_dir || '';
  let workDir = meta.work_dir || s.work_dir || (outDir ? wiz.defaultPaths(p.repo, p.branch, outDir).work : '');
  if (!p.sonar_port || p.sonar_port === 9000) wiz.patch(x => { x.sonar_port = s.sonar_port || x.sonar_port || 9000; });
  const auto = wiz.defaultPaths(p.repo, p.branch, outDir, workDir);
  let dbName = meta.db_name || (p.paths && p.paths.db && meta.names_edited ? baseName(p.paths.db) : auto.dbName);
  let exportName = meta.export_name || (p.paths && p.paths.export && meta.names_edited ? baseName(p.paths.export) : auto.exportName);

  const out = h('input', { class: 'input mono', id: 'w4-out', value: outDir, placeholder: 'D:\\secjit\\results', spellcheck: 'false' });
  const work = h('input', { class: 'input mono', id: 'w4-work', value: workDir, placeholder: 'D:\\secjit\\work', spellcheck: 'false' });
  const db = h('input', { class: 'input mono', id: 'w4-db', value: dbName, spellcheck: 'false' });
  const exp = h('input', { class: 'input mono', id: 'w4-exp', value: exportName, spellcheck: 'false' });
  const msgs = { out: h('div'), work: h('div'), db: h('div'), exp: h('div') };
  const dbExistsBox = h('div');
  const pickOut = btn(t('w4.pick') + '…', { onClick: () => pick(out, 'out') });
  const pickWork = btn(t('w4.pick') + '…', { onClick: () => pick(work, 'work') });
  els = { out, work, db, exp, msgs, dbExistsBox, pickOut, pickWork };

  const regen = () => {
    if (wiz.meta().names_edited) return;
    const a = wiz.defaultPaths(p.repo, p.branch, out.value, work.value);
    db.value = a.dbName; exp.value = a.exportName;
  };
  out.addEventListener('input', () => { regen(); save(); });
  work.addEventListener('input', () => { save(); });
  db.addEventListener('input', () => { wiz.setMeta({ names_edited: true }); save(); });
  exp.addEventListener('input', () => { wiz.setMeta({ names_edited: true }); save(); });
  const resetNames = btn(t('w4.reset_names'), { small: true, kind: 'ghost', onClick: () => { wiz.setMeta({ names_edited: false }); regen(); save(); } });

  // định dạng xuất + thông báo
  const csv = h('input', { type: 'checkbox', id: 'w4-csv', checked: !!(meta.formats || []).includes('csv') });
  csv.addEventListener('change', () => wiz.setMeta({ formats: csv.checked ? ['jsonl', 'csv'] : ['jsonl'] }));
  if (!meta.formats) wiz.setMeta({ formats: ['jsonl'] });
  const notify = h('input', { type: 'checkbox', id: 'w4-notify', checked: meta.notify !== false });
  notify.addEventListener('change', () => wiz.setMeta({ notify: notify.checked }));
  if (meta.notify === undefined) wiz.setMeta({ notify: true });

  frame.body.append(
    card({ title: t('w4.out_dir'), body: h('div', {},
      h('label', { class: 'field', for: 'w4-out' }, h('span', { class: 'sr-only' }, t('w4.out_dir')), h('div', { class: 'inline' }, out, pickOut), msgs.out),
      h('div', { class: 'kv', style: { gridTemplateColumns: '28px 1fr', alignItems: 'center' } },
        h('span', { class: 'muted', 'aria-hidden': 'true' }, '└'), h('label', { class: 'field', for: 'w4-db', style: { margin: 0 } }, h('span', { class: 'small' }, t('w4.db_name')), db, msgs.db),
        h('span', { class: 'muted', 'aria-hidden': 'true' }, '└'), h('label', { class: 'field', for: 'w4-exp', style: { margin: 0 } }, h('span', { class: 'small' }, t('w4.export_name')), exp, msgs.exp)),
      h('div', { class: 'row between', style: { marginTop: '8px' } }, h('span', { class: 'help' }, t('w4.names_hint')), resetNames),
      dbExistsBox) }),
    card({ title: t('w4.work_dir'), body: h('div', {},
      h('label', { class: 'field', for: 'w4-work' }, h('span', { class: 'sr-only' }, t('w4.work_dir')), h('div', { class: 'inline' }, work, pickWork), msgs.work),
      h('p', { class: 'help' }, t('w4.work_hint'))) }),
    card({ title: t('w4.export'), body: h('div', {},
      h('div', { class: 'check' }, h('input', { type: 'checkbox', checked: true, disabled: true, 'aria-label': 'jsonl' }), h('span', {}, h('strong', {}, 'dataset.jsonl + commits.jsonl'), ' ', h('span', { class: 'muted small' }, t('w4.required')))),
      h('label', { class: 'check', for: 'w4-csv' }, csv, h('span', {}, 'CSV ', h('span', { class: 'muted small' }, t('w4.csv_hint')))),
      h('div', { class: 'check' }, h('input', { type: 'checkbox', checked: true, disabled: true, 'aria-label': t('w4.raw') }), h('span', {}, t('w4.raw'), ' ', h('span', { class: 'muted small' }, t('w4.raw_fixed')))),
      h('label', { class: 'check', for: 'w4-notify' }, notify, h('span', {}, t('w4.notify')))) }));

  function save() {
    outDir = out.value.trim(); workDir = work.value.trim();
    const a = wiz.defaultPaths(p.repo, p.branch, outDir, workDir);
    const sep = a.db.includes('\\') ? '\\' : '/';
    const base = outDir.replace(/[\\/]+$/, '');
    let dbn = db.value.trim(); if (dbn && !/\.sqlite$/i.test(dbn)) dbn += '.sqlite';
    wiz.patch(x => { x.paths = { db: base && dbn ? `${base}${sep}${dbn}` : '', export: base && exp.value.trim() ? `${base}${sep}${exp.value.trim()}` : '', work: workDir }; });
    wiz.setMeta({ out_dir: outDir, work_dir: workDir, db_name: db.value.trim(), export_name: exp.value.trim(), resume: false, overwrite: false });
    const bad = validate();
    frame.next.disabled = bad;
    clear(dbExistsBox);
    if (!bad) checkExistsDebounced();
  }
  const checkExistsDebounced = debounce(() => checkExists(), 500);
  save();
}

export function destroy() { alive = false; frame = null; els = {}; }

function baseName(pth) { const i = Math.max(pth.lastIndexOf('\\'), pth.lastIndexOf('/')); return i >= 0 ? pth.slice(i + 1) : pth; }
function norm(pth) { return (pth || '').trim().replace(/[\\/]+$/, '').replace(/\//g, '\\').toLowerCase(); }

/** Trả true nếu có lỗi chặn. */
function validate() {
  const { out, work, db, exp, msgs } = els;
  let bad = false;
  const setMsg = (el, inp, errMsg, warnMsg) => { clear(el); inp.classList.toggle('invalid', !!errMsg); if (errMsg) { el.append(h('div', { class: 'err' }, errMsg)); bad = true; } else if (warnMsg) el.append(h('div', { class: 'warnmsg' }, warnMsg)); };
  const pathCheck = (v) => {
    if (!v) return [t('w4.err_empty'), null];
    if (/^\\\\/.test(v) || /^\/\//.test(v)) return [t('w4.err_unc'), null];
    if (!/^[A-Za-z]:[\\/]/.test(v) && !/^\//.test(v)) return [t('w4.err_abs'), null];
    if (/[<>"|?*]/.test(v.slice(2))) return [t('w4.err_chars'), null];
    let warn = null;
    if (/onedrive|dropbox|google drive|icloud/i.test(v)) warn = t('w4.warn_cloud');
    else if (v.length > 240) warn = t('w4.warn_long', { n: v.length });
    else if (/\s$/.test(v)) warn = t('w4.warn_trailing_space');
    return [null, warn];
  };
  const [oe, ow] = pathCheck(out.value.trim()); setMsg(msgs.out, out, oe, ow);
  const [we, ww] = pathCheck(work.value.trim());
  let wErr = we;
  if (!we && !oe) {
    const o = norm(out.value); const w = norm(work.value);
    if (o === w) wErr = t('w4.err_same');
    else if (w.startsWith(o + '\\')) wErr = t('w4.err_work_in_out');
    else if (o.startsWith(w + '\\')) wErr = t('w4.err_out_in_work');
  }
  setMsg(msgs.work, work, wErr, ww);
  const dbv = db.value.trim();
  setMsg(msgs.db, db, !dbv ? t('w4.err_empty') : /[\\/<>"|?*:]/.test(dbv) ? t('w4.err_name_chars') : null, null);
  const ev = exp.value.trim();
  setMsg(msgs.exp, exp, !ev ? t('w4.err_empty') : /[\\/<>"|?*:]/.test(ev) ? t('w4.err_name_chars') : null, ev && dbv && ev.toLowerCase() === dbv.toLowerCase().replace(/\.sqlite$/, '') ? t('w4.warn_same_name') : null);
  return bad;
}

let seq = 0;
async function checkExists() {
  if (!alive) return;
  const my = ++seq;
  const p = wiz.ensure();
  try {
    const r = await api('/api/profile/validate', { method: 'POST', body: { profile: p } });
    if (!alive || my !== seq) return;
    clear(els.dbExistsBox);
    const serverErrs = (r.errors || []).filter(e => !/paths\.db|repo trống|scope/.test(e));
    if (serverErrs.length) els.dbExistsBox.append(notice('warn', h('div', {}, h('strong', {}, t('w4.server_errors')), h('ul', { class: 'dot-list' }, serverErrs.map(e => h('li', {}, e))))));
    if (r.db_exists) drawDbExists(r);
  } catch (e) {
    if (!alive || my !== seq) return;
    clear(els.dbExistsBox).append(h('p', { class: 'help' }, t('w4.exists_unknown') + (e.message ? ` (${e.message})` : '')));
  }
}

function drawDbExists(r) {
  const p = wiz.ensure();
  const name = baseName(p.paths.db);
  const box = h('div', { class: 'stack' });
  const resume = btn('▶ ' + t('w4.resume'), { small: true, kind: 'primary', onClick: () => { wiz.setMeta({ resume: true, overwrite: false }); toast(t('w4.resume_set'), 'ok'); mark(resume); } });
  const rename = btn(t('w4.rename'), { small: true, onClick: () => {
    const m = /^(.*?)(?:_(\d+))?\.sqlite$/i.exec(els.db.value.trim()) || [null, els.db.value.trim().replace(/\.sqlite$/i, ''), null];
    const n = (parseInt(m[2] || '1', 10) + 1);
    els.db.value = `${m[1]}_${n}.sqlite`; els.exp.value = `${els.exp.value.replace(/_\d+$/, '')}_${n}`;
    wiz.setMeta({ names_edited: true }); els.db.dispatchEvent(new Event('input'));
  } });
  const overwrite = btn(t('w4.overwrite'), { small: true, kind: 'danger', onClick: async () => {
    const ok = await dialog({ title: t('w4.overwrite_title'), body: h('div', {}, h('p', {}, t('w4.overwrite_body', { name })), h('p', { class: 'muted small' }, t('w4.overwrite_note'))), confirmText: t('w4.overwrite'), typedConfirm: name, danger: true });
    if (!ok) return;
    wiz.setMeta({ overwrite: true, resume: false }); toast(t('w4.overwrite_set'), 'warn'); mark(overwrite);
  } });
  const mark = (b) => { for (const x of [resume, rename, overwrite]) x.classList.remove('primary'); b.classList.add('primary'); };
  box.append(notice('fix', h('div', {}, h('strong', {}, t('w4.exists_title', { name })), h('div', { class: 'small' }, t('w4.exists_body') + (r.db_user_version !== null && r.db_user_version !== undefined ? ` · schema v${r.db_user_version}` : '')),
    h('div', { class: 'row gap-s', style: { marginTop: '10px' } }, resume, rename, overwrite))));
  els.dbExistsBox.append(box);
  const m = wiz.meta(); if (m.resume) mark(resume); else if (m.overwrite) mark(overwrite);
}

async function pick(input, which) {
  const b = which === 'out' ? els.pickOut : els.pickWork;
  if (!pickDirSupported) { input.focus(); return; }
  busy(b, true);
  try {
    const r = await api('/api/settings/pick_dir', { method: 'POST', body: { initial: input.value, title: t(which === 'out' ? 'w4.out_dir' : 'w4.work_dir') }, timeout: 300000 });
    if (!alive) return;
    if (r && r.path) { input.value = r.path; input.dispatchEvent(new Event('input')); }
  } catch (e) {
    if (!alive) return;
    if (e.status === 501) { pickDirSupported = false; els.pickOut.disabled = true; els.pickWork.disabled = true; toast(t('w4.pick_unsupported'), 'warn'); input.focus(); }
    else toast(e.message, 'bad');
  } finally { if (alive) busy(b, false); }
}
