// results_export.js — #/results/:id/export (A5). POST /api/results/:id/export {formats} -> {export_dir, files[]}
// "Mở thư mục" -> POST /api/open?path= (501 -> toast). Manifest tóm tắt từ overview (hoặc từ response nếu backend trả `manifest`).
import { h, clear, makeT, fmt, kv, banner, tryApi, errStatus, errText, resultsHeader, findRun } from './_util.js';

let tr = (k, fb) => (fb === undefined ? k : fb);

let S = null;

export async function render(root, ctx) {
  tr = makeT(ctx);
  const C = ctx.components; const t = makeT(ctx);
  const id = ctx.params.id;
  S = { dead: false, ctx, C, t, id, root, run: null, ov: null, formats: { jsonl: true, csv: false }, busy: false, result: null };
  clear(root);
  root.append(resultsHeader(ctx, id, 'export', null), C.skeleton(6));
  const [run, ov] = await Promise.all([findRun(ctx, id), tryApi(ctx, `/api/results/${encodeURIComponent(id)}/overview`)]);
  if (S.dead) return;
  S.run = run; S.ov = ov;
  draw();
}

export function destroy() { if (S) S.dead = true; S = null; }

function draw() {
  if (!S || S.dead) return;
  const { root, C, t, ctx, id, run } = S;
  clear(root);
  root.append(resultsHeader(ctx, id, 'export', run));
  if (!S.ov.ok) { root.append(C.errorBox(S.ov.err, () => render(root, ctx))); return; }
  const d = S.ov.data || {};
  const L = d.labels || {};
  const nothing = !d.funnel || !d.funnel.commits;
  if (nothing) { root.append(C.empty(t('ex.empty', 'Chưa có gì để xuất — run chưa có commit/nhãn.'))); return; }
  if (run && (run.status === 'running' || run.status === 'interrupted')) root.append(banner('warn', tr('ex.banner.run_chua_xong', 'Run chưa xong'), tr('ex.banner_body.xuat_luc_nay_cho_dataset_tam', 'Xuất lúc này cho dataset tạm (thiếu tầng đắt); manifest sẽ ghi trạng thái run.')));
  if (run && run.export) root.append(banner('warn', tr('ex.banner.thu_muc_export_da_ton_tai', 'Thư mục export đã tồn tại'), `${run.export} — backend sẽ tạo thư mục mới (không ghi đè, CONTRACTS §6).`));
  if (d.experiment && d.experiment.enabled) root.append(banner('warn', tr('ex.banner.run_thi_nghiem', 'Run thí nghiệm'), tr('ex.banner_body.export_se_co_hau_to_exp_khon', 'Export sẽ có hậu tố _exp; không gộp vào gold_set_all.')));

  // form
  const cb = (key, label, hint) => {
    const inp = h('input', { type: 'checkbox', id: `ex-${key}`, checked: S.formats[key] ? true : null });
    inp.addEventListener('change', () => { S.formats[key] = inp.checked; });
    return h('label', { class: 's-check', for: `ex-${key}` }, inp, h('span', {}, label, h('span', { class: 's-muted s-small', text: ` · ${hint}` })));
  };
  const form = h('div', { class: 's-stack' },
    h('div', { class: 's-stack' }, cb('jsonl', 'JSONL', 'dataset.jsonl + commits.jsonl + run_manifest.json + SHA256SUMS + raw/<sha12>/'), cb('csv', 'CSV', 'dataset.csv + commits.csv (phẳng, cho R/pandas)')),
    h('div', { class: 's-row' }, C.btn({ label: S.busy ? 'Đang xuất…' : 'Xuất', kind: 'primary', disabled: S.busy, onClick: doExport }),
      run && run.export ? C.btn({ label: tr('ex.btn.mo_thu_muc_cu', 'Mở thư mục cũ'), onClick: () => openDir(run.export) }) : null));
  root.append(C.card(form, { title: tr('ex.title.dinh_dang', 'Định dạng') }));

  // kết quả
  if (S.result) {
    const r = S.result;
    const res = h('div', { class: 's-stack' },
      r.exists ? banner('warn', tr('ex.banner.thu_muc_da_co_du_lieu_cu', 'Thư mục đã có dữ liệu cũ'), tr('ex.banner_body.backend_da_ghi_vao_thu_muc_m', 'Backend đã ghi vào thư mục mới có hậu tố thời gian.')) : null,
      kv('export_dir', h('span', { class: 's-mono', text: r.export_dir || '—' })),
      h('div', {}, h('strong', { class: 's-small', text: `${(r.files || []).length} file` }), h('ul', { class: 's-list s-mono' }, (r.files || []).map((f) => h('li', { text: f })))),
      h('div', { class: 's-row' }, C.btn({ label: tr('ex.btn.mo_thu_muc', 'Mở thư mục'), onClick: () => openDir(r.export_dir) })));
    root.append(C.card(res, { title: tr('ex.title.da_xuat', 'Đã xuất') }));
  }

  // manifest tóm tắt
  const man = (S.result && S.result.manifest) || null;
  const f = d.funnel || {};
  const sum = h('div', { class: 's-stack' },
    h('p', { class: 's-small s-muted', text: man ? 'Từ run_manifest.json vừa xuất.' : 'Tóm tắt dự kiến (từ overview); run_manifest.json đầy đủ gồm profile, run_meta 2 tầng, κ, counts, build_failed[], infra_error[], tool_timeout[], skipped[], git-sha, OS/Docker.' }),
    kv('counts', h('span', { class: 's-mono', text: `gold ${fmt.int(L.gold)} · silver ${fmt.int(L.silver)} · candidate ${fmt.int(L.candidate)} · verified_clean ${fmt.int(L.verified_clean)} · cheap_clean ${fmt.int(L.cheap_clean)}` })),
    kv('commits', h('span', { class: 's-mono', text: `${fmt.int(f.commits)} → after_filter ${fmt.int(f.after_filter)} · built ${fmt.int(f.built)} · build_failed ${fmt.int(f.build_failed)} · skipped ${fmt.int(f.skipped)} · infra_error ${fmt.int(f.infra_error)}` })),
    kv('κ tổng', h('span', { class: 's-mono', text: d.kappa ? fmt.num(d.kappa.total) : '—' })),
    kv('params_v1', h('span', { class: 's-mono', text: d.params_v1 ? Object.entries(d.params_v1).map(([k, v]) => `${k}=${Array.isArray(v) ? v.join('|') : v}`).join(' ') : '—' })),
    kv('experiment', h('span', { class: 's-mono', text: d.experiment && d.experiment.enabled ? `có · ${d.experiment.reason || ''}` : 'không' })),
    kv('evidence mỗi dòng', h('span', { class: 's-mono', text: '{consensus: gold|silver|candidate, validation: unreviewed|TP|FP|unclear}' })));
  root.append(C.card(sum, { title: tr('ex.title.manifest_tom_tat', 'Manifest tóm tắt') }));
}

async function doExport() {
  const { C, ctx, id } = S;
  const formats = Object.entries(S.formats).filter(([, v]) => v).map(([k]) => k);
  if (!formats.length) { C.toast(tr('ex.toast.chon_it_nhat_mot_dinh_dang', 'Chọn ít nhất một định dạng.'), 'warn'); return; }
  S.busy = true; draw();
  const r = await tryApi(ctx, `/api/results/${encodeURIComponent(id)}/export`, { method: 'POST', body: { formats } });
  if (!S || S.dead) return;
  S.busy = false;
  if (!r.ok) { C.toast(errText(r.err), 'error'); draw(); return; }
  S.result = r.data; C.toast(tr('ex.toast.xuat_xong', 'Xuất xong.'), 'ok'); draw();
}

async function openDir(path) {
  const { C, ctx } = S;
  const r = await tryApi(ctx, `/api/open?path=${encodeURIComponent(path || '')}`, { method: 'POST', body: { path } });
  if (!S || S.dead) return;
  if (!r.ok) C.toast(errStatus(r.err) === 501 || errStatus(r.err) === 404 ? `Chưa hỗ trợ mở thư mục — đường dẫn: ${path}` : errText(r.err), 'warn');
}
