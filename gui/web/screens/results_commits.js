// results_commits.js — #/results/:id/commits (A5). GET /api/results/:id/commits?page=&size=
// Nút "Tính lại Kamei" -> POST /api/results/:id/features (501 -> toast); "Gán nhãn lại" chỉ khi experiment.
import { h, clear, makeT, fmt, statusTag, partialNote, banner, tryApi, errStatus, errText, qs, resultsHeader, findRun } from './_util.js';

const SIZE = 25;
let S = null;

export async function render(root, ctx) {
  const C = ctx.components; const t = makeT(ctx);
  const id = ctx.params.id;
  S = { dead: false, ctx, C, t, id, root, page: 1, data: null, run: null, experiment: null, loading: true, err: null, missing: new Set() };
  clear(root);
  root.append(resultsHeader(ctx, id, 'commits', null), C.skeleton(8));
  const [run, ov] = await Promise.all([findRun(ctx, id), tryApi(ctx, `/api/results/${encodeURIComponent(id)}/overview`)]);
  if (S.dead) return;
  S.run = run; S.experiment = ov.ok && ov.data ? ov.data.experiment : null;
  await load();
}

export function destroy() { if (S) S.dead = true; S = null; }

async function load() {
  S.loading = true; S.err = null; draw();
  const r = await tryApi(S.ctx, `/api/results/${encodeURIComponent(S.id)}/commits${qs({ page: S.page, size: SIZE })}`);
  if (!S || S.dead) return;
  S.loading = false;
  if (!r.ok) S.err = r.err; else {
    S.data = r.data; S.missing = new Set();
    for (const row of (r.data.rows || [])) for (const k of ['kamei', 'n_expensive_ok', 'negative_level', 'status']) if (row[k] === undefined) S.missing.add(k);
  }
  draw();
}

function draw() {
  if (!S || S.dead) return;
  const { root, C, t, ctx, id } = S;
  clear(root);
  root.append(resultsHeader(ctx, id, 'commits', S.run));
  const actions = h('div', { class: 's-row' },
    h('span', { class: 's-sub', text: 'Mỗi dòng = 1 commit đã chọn; status theo CONTRACTS §1; negative_level chỉ có với commit clean.' }),
    h('span', { class: 's-spacer' }),
    C.btn({ label: 'Tính lại Kamei', small: true, onClick: recomputeKamei }));
  if (S.experiment && S.experiment.enabled) actions.append(C.btn({ label: 'Gán nhãn lại (thí nghiệm)', small: true, kind: 'danger', onClick: relabel }));
  root.append(actions);
  if (S.experiment && S.experiment.enabled) root.append(banner('warn', 'Run thí nghiệm', `params_v1 khác mặc định — lý do: ${S.experiment.reason || '—'}. Không gộp vào gold_set_all.`));
  const pn = partialNote([...S.missing]); if (pn) root.append(pn);

  if (S.loading) { root.append(C.card(C.skeleton(8))); return; }
  if (S.err) { root.append(C.errorBox(S.err, () => load())); return; }
  const d = S.data || {}; const rows = d.rows || [];
  if (!rows.length) { root.append(C.empty(t('cm.empty', 'Chưa có commit nào được chọn cho run này.'))); return; }
  root.append(C.card(C.table({
    columns: [
      { key: 'date', label: 'ngày', render: (r) => h('span', { class: 's-mono', style: { whiteSpace: 'nowrap' }, text: r.date || '—' }) },
      { key: 'commit', label: 'commit', render: (r) => h('span', { class: 's-mono', text: fmt.sha(r.commit) }) },
      { key: 'role', label: 'vai', render: (r) => h('span', { class: `s-tag ${r.role === 'buggy' ? 'st-warn' : 'st-muted'}`, text: r.role || '—' }) },
      { key: 'status', label: 'status', render: (r) => r.status ? statusTag(r.status) : null },
      { key: 'n_expensive_ok', label: 'tool đắt ok', render: (r) => r.n_expensive_ok === undefined ? null : h('span', { class: 's-mono', text: String(r.n_expensive_ok) }) },
      { key: 'negative_level', label: 'mức âm', render: (r) => r.negative_level ? C.badgeLabel(r.negative_level) : (r.role === 'clean' ? h('span', { class: 's-muted', text: 'chưa xác định' }) : h('span', { class: 's-muted', text: '—' })) },
      { key: 'kamei', label: 'Kamei', render: (r) => kamei(r.kamei) },
      { key: 'build_error', label: 'lỗi build', render: (r) => r.build_error ? h('span', { class: 's-mono', style: { display: 'inline-block', maxWidth: '150px', whiteSpace: 'normal', wordBreak: 'break-word' }, title: r.build_error, text: r.build_error }) : null },
    ],
    rows, page: S.page, size: SIZE, total: d.total, onPage: (p) => { S.page = p; load(); },
  })));
}

function kamei(k) {
  if (!k) return null;
  const keys = Object.keys(k);
  const sum = `la ${k.la ?? '—'} · ld ${k.ld ?? '—'} ▸`;
  return h('details', { class: 's-kamei' }, h('summary', { text: sum }), h('div', { class: 's-mono' }, keys.map((x) => `${x}=${k[x]}`).join(' · ')));
}

async function recomputeKamei() {
  const { C, ctx, id } = S;
  const r = await tryApi(ctx, `/api/results/${encodeURIComponent(id)}/features`, { method: 'POST', body: {} });
  if (!S || S.dead) return;
  if (!r.ok) { C.toast(errStatus(r.err) === 501 || errStatus(r.err) === 404 ? 'Chưa hỗ trợ tính lại Kamei qua GUI — dùng CLI `features`.' : errText(r.err), 'warn'); return; }
  C.toast('Đã tính lại Kamei.', 'ok'); load();
}

function relabel() {
  const { C, ctx, id } = S;
  C.dialog({
    title: 'Gán nhãn lại (chế độ thí nghiệm)',
    body: 'Chạy relabel với params_v1 của run thí nghiệm này. Không ảnh hưởng gold_set_all; export sẽ có hậu tố _exp.',
    confirmText: 'Gán nhãn lại', typedConfirm: 'RELABEL', kind: 'danger',
    onConfirm: async () => {
      const r = await tryApi(ctx, `/api/results/${encodeURIComponent(id)}/relabel`, { method: 'POST', body: {} });
      if (!r.ok) { if (errStatus(r.err) === 501 || errStatus(r.err) === 404) { C.toast('Chưa hỗ trợ relabel qua GUI — dùng CLI `relabel`.', 'warn'); return; } throw r.err; }
      C.toast('Đã gán nhãn lại.', 'ok'); load();
    },
  });
}
