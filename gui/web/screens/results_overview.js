// results_overview.js — #/results/:id/overview (A5). GET /api/results/:id/overview.
// Phễu · bảng nhãn 3 mức + 2 mức âm (wording bắt buộc) · CWE-group × nhãn · κ + giải thích · precision kiểm tay · giới hạn · params_v1/experiment · xuất CSV/LaTeX.
import { h, clear, makeT, fmt, partialNote, banner, kv, segBar, tryApi, errText, resultsHeader, findRun } from './_util.js';

let tr = (k, fb) => (fb === undefined ? k : fb);

let S = null;

export async function render(root, ctx) {
  tr = makeT(ctx);
  const C = ctx.components; const t = makeT(ctx);
  S = { dead: false };
  const id = ctx.params.id;
  clear(root);
  root.append(resultsHeader(ctx, id, 'overview', null), C.skeleton(8));
  const [ov, run] = await Promise.all([tryApi(ctx, `/api/results/${encodeURIComponent(id)}/overview`), findRun(ctx, id)]);
  if (S.dead) return;
  clear(root);
  root.append(resultsHeader(ctx, id, 'overview', run));
  if (!ov.ok) { root.append(C.errorBox(ov.err, () => render(root, ctx))); return; }
  const d = ov.data || {};
  const f = d.funnel || {};
  if (!f.commits) { root.append(C.empty(t('ov.empty', 'Chưa có kết quả cho run này — chưa chạy tới relabel/kappa, hoặc DB rỗng.'))); return; }

  const missing = ['kappa', 'coverage', 'precision', 'limits', 'labels', 'by_cwe_group', 'params_v1'].filter((k) => d[k] === undefined);
  const pn = partialNote(missing); if (pn) root.append(pn);
  if (run && (run.status === 'running' || run.status === 'interrupted')) root.append(banner('warn', tr('ov.banner.ket_qua_tam_run_chua_xong', 'Kết quả tạm — run chưa xong'), tr('ov.banner_body.thieu_tang_dat_tren_mot_phan', 'Thiếu tầng đắt trên một phần commit; nhãn/κ sẽ đổi sau relabel cuối.')));
  if (d.experiment && d.experiment.enabled) root.append(banner('warn', tr('ov.banner.run_thi_nghiem_khong_gop_vao', 'Run thí nghiệm — không gộp vào gold_set_all'), `Lý do: ${d.experiment.reason || '—'} · params_v1 khác mặc định.`));

  // phễu
  const funnel = h('div', { class: 's-funnel' });
  const row = (label, val, max, cls, sub = false) => h('div', { class: `s-funnel-row ${sub ? 'sub' : ''}` },
    h('span', { class: 'lbl', text: label }),
    h('div', { class: 's-bar', role: 'img', 'aria-label': `${label} ${val}` }, h('span', { class: `seg-${cls}`, style: { width: `${max ? Math.min(100, (val / max) * 100) : 0}%` } })),
    h('span', { class: 'val s-mono', text: `${fmt.int(val)}${max && max !== val ? ` · ${fmt.pct(val, max)}` : ''}` }));
  const base = f.commits || 1;
  funnel.append(row('Commit trong phạm vi', f.commits, base, 'accent'));
  funnel.append(row('Sau lọc (bỏ merge/docs)', f.after_filter, base, 'accent2'));
  funnel.append(row('buggy (tầng rẻ có finding)', f.buggy, base, 'accent3', true));
  funnel.append(row('clean (tầng rẻ không báo)', f.clean, base, 'muted', true));
  funnel.append(row('Tầng đắt: built', f.built, base, 'ok', true));
  funnel.append(row('build_failed (lỗi dữ liệu)', f.build_failed, base, 'bad', true));
  funnel.append(row('skipped (không module Java)', f.skipped, base, 'skipped', true));
  funnel.append(row('infra_error (về pending)', f.infra_error, base, 'infra', true));
  root.append(C.card(funnel, { title: tr('ov.title.pheu_commit', 'Phễu commit') }));

  const grid = h('div', { class: 's-grid-2' });
  // nhãn
  const L = d.labels || {};
  const lab = h('div', { class: 's-stack' },
    h('div', { class: 's-kv' }, C.badgeLabel('gold'), h('span', {}, h('b', { class: 's-mono', text: fmt.int(L.gold) }), h('span', { class: 's-muted s-small', text: ' · gold · đồng thuận máy (chưa kiểm tay)' }))),
    h('div', { class: 's-kv' }, C.badgeLabel('silver'), h('span', {}, h('b', { class: 's-mono', text: fmt.int(L.silver) }), h('span', { class: 's-muted s-small', text: ' · ≥2 tool rẻ hoặc 1 tool đắt' }))),
    h('div', { class: 's-kv' }, C.badgeLabel('candidate'), h('span', {}, h('b', { class: 's-mono', text: fmt.int(L.candidate) }), h('span', { class: 's-muted s-small', text: ' · 1 tool rẻ' }))),
    h('div', { class: 's-kv' }, C.badgeLabel('verified-clean'), h('span', {}, h('b', { class: 's-mono', text: fmt.int(L.verified_clean) }), h('span', { class: 's-muted s-small', text: ' · verified-clean · 2 tool đắt không báo — không phải chứng minh sạch' }))),
    h('div', { class: 's-kv' }, C.badgeLabel('cheap-clean'), h('span', {}, h('b', { class: 's-mono', text: fmt.int(L.cheap_clean) }), h('span', { class: 's-muted s-small', text: ' · chỉ tool rẻ không báo' }))),
    precisionLine(d.precision));
  grid.append(C.card(lab, { title: tr('ov.title.nhan_3_muc_duong_2_muc_am', 'Nhãn (3 mức dương · 2 mức âm)') }));
  // CWE-group × nhãn
  const groups = d.by_cwe_group || [];
  grid.append(C.card(groups.length ? C.table({
    columns: [{ key: 'group', label: tr('ov.btn.cwe_group', 'CWE-group') }, { key: 'gold', label: tr('ov.btn.gold', 'gold'), render: (r) => fmt.int(r.gold) }, { key: 'silver', label: tr('ov.btn.silver', 'silver'), render: (r) => fmt.int(r.silver) }, { key: 'candidate', label: tr('ov.btn.candidate', 'candidate'), render: (r) => fmt.int(r.candidate) }],
    rows: groups,
  }) : C.empty(tr('ov.empty.chua_co_thong_ke_theo_cwe_gr', 'Chưa có thống kê theo CWE-group.')), { title: tr('ov.title.cwe_group_nhan', 'CWE-group × nhãn') }));
  root.append(grid);

  // kappa
  const K = d.kappa; const cov = d.coverage;
  const kap = h('div', { class: 's-stack' });
  if (!K) kap.append(h('div', { class: 's-note warn', text: tr('ov.note.backend_chua_tra_chay_kappa', 'Backend chưa trả κ (chạy `kappa` hoặc stats).') }));
  else {
    kap.append(h('div', { class: 's-row' }, h('span', { class: 's-big s-mono', text: fmt.num(K.total) }), h('span', { class: 's-muted', text: 'κ Fleiss tổng (W=3)' })));
    const grid2 = h('div', { class: 's-grid-2' });
    const mk = (title, arr) => C.table({ columns: [{ key: 'group', label: title }, { key: 'value', label: 'κ', render: (r) => h('span', { class: 's-mono', text: fmt.num(r.value) }) }, { key: 'n', label: 'n', render: (r) => fmt.int(r.n) }], rows: arr || [], emptyMsg: 'không có' });
    grid2.append(h('div', {}, mk('Theo category', K.by_category)), h('div', {}, mk('Theo CWE-group', K.by_group)), h('div', {}, mk('Pairwise (cặp tool)', K.pairs)));
    kap.append(grid2);
  }
  if (cov) {
    const tot = (cov.one || 0) + (cov.two || 0) + (cov.three_plus || 0);
    kap.append(h('div', { class: 's-stack' }, h('strong', { class: 's-small', text: `Độ phủ: số tool báo cùng một cụm (n=${fmt.int(tot)})` }),
      segBar([{ label: tr('ov.btn.1_tool', '1 tool'), value: cov.one || 0, cls: 'candidate' }, { label: tr('ov.btn.2_tool', '2 tool'), value: cov.two || 0, cls: 'silver' }, { label: tr('ov.btn.3_tool', '≥3 tool'), value: cov.three_plus || 0, cls: 'gold' }], tot, { height: 14 })));
  }
  kap.append(h('div', { class: 's-note' },
    h('strong', { text: tr('ov.text.cach_doc', 'Cách đọc κ: ') }),
    'κ Fleiss âm hoặc gần 0 là bình thường ở mọi repo đã chạy (−0,26 … −0,47): các tool SAST bắt ',
    h('em', { text: 'lớp lỗi khác nhau' }), ' (phủ bổ sung) chứ không cùng chấm một tập — bất đồng có hệ thống nên κ < 0. ',
    'Mẫu số là các cụm ', h('em', { text: 'eligible' }), ' (tool có khả năng phát hiện CWE-group đó, không phải mọi tool), nên κ không so sánh được giữa run có bộ tool khác nhau. ',
    'Hệ quả: gold (≥2 tool đắt đồng ý) hiếm — đó là đặc tính của giao thức đồng thuận, không phải lỗi; precision thật của gold chỉ biết sau kiểm tay mù.'));
  root.append(C.card(kap, { title: tr('ov.title.dong_thuan_giua_tool', 'Đồng thuận giữa tool (κ)') }));

  // giới hạn
  const lim = d.limits;
  root.append(C.card(lim === undefined ? h('div', { class: 's-note warn', text: tr('ov.note.backend_chua_tra_limits', 'Backend chưa trả limits[].') }) : (lim.length ? h('ul', { class: 's-list' }, lim.map((s) => h('li', { text: s }))) : C.empty(tr('ov.empty.khong_co_gioi_han_tu_sinh', 'Không có giới hạn tự sinh.'))), { title: tr('ov.title.gioi_han_cua_dataset_nay_thr', 'Giới hạn của dataset này (threats to validity, tự sinh từ run)') }));

  // params + export
  const P = d.params_v1 || {};
  const pr = h('div', { class: 's-stack' },
    kv('line_window (W)', h('span', { class: 's-mono', text: P.line_window ?? '—' })),
    kv('gold_min_expensive', h('span', { class: 's-mono', text: P.gold_min_expensive ?? '—' })),
    kv('gold_allow_1exp_1cheap', h('span', { class: 's-mono', text: P.gold_allow_1exp_1cheap ?? '—' })),
    kv('silver_min_cheap', h('span', { class: 's-mono', text: P.silver_min_cheap ?? '—' })),
    kv('noise_cwe', h('span', { class: 's-mono', text: (P.noise_cwe || []).join(', ') || '—' })),
    kv('experiment', h('span', { class: 's-mono', text: d.experiment && d.experiment.enabled ? `có · ${d.experiment.reason || ''}` : 'không (phương pháp luận đóng băng v1)' })));
  const ex = h('div', { class: 's-stack' },
    h('p', { class: 's-small s-muted', text: tr('ov.text.xuat_bang_thong_ke_pheu_nhan', 'Xuất bảng thống kê (phễu, nhãn, CWE-group, κ, giới hạn) để đưa vào luận văn. Dataset đầy đủ: tab Xuất.') }),
    h('div', { class: 's-row' },
      C.btn({ label: tr('ov.btn.xuat_csv', 'Xuất CSV'), onClick: () => doExport(ctx, id, 'csv') }),
      C.btn({ label: tr('ov.btn.xuat_latex', 'Xuất LaTeX'), onClick: () => doExport(ctx, id, 'latex') })));
  root.append(h('div', { class: 's-grid-2' }, C.card(pr, { title: tr('ov.title.tham_so_gan_nhan_params_v1', 'Tham số gán nhãn (params_v1)') }), C.card(ex, { title: tr('ov.title.xuat_thong_ke', 'Xuất thống kê') })));
}

export function destroy() { if (S) S.dead = true; S = null; }

function precisionLine(p) {
  if (p === undefined) return h('div', { class: 's-note warn s-small', text: tr('ov.note.backend_chua_tra_precision_k', 'Backend chưa trả precision kiểm tay.') });
  if (!p || !p.n) return h('div', { class: 's-note s-small', text: tr('ov.note.precision_gold_chua_kiem_tay', 'Precision gold: chưa kiểm tay (n=0). Dùng tab "Kiểm tay" để lấy mẫu phân tầng và chấm mù.') });
  const point = p.point !== undefined ? p.point : (p.tp !== undefined ? p.tp / p.n : null);
  return h('div', { class: 's-note s-small' }, h('strong', { text: `Precision gold đo trên mẫu kiểm tay n=${p.n}: ` }), h('span', { class: 's-mono', text: `${fmt.num(point)} [${fmt.num(p.ci_low)}, ${fmt.num(p.ci_high)}]` }), ` · TP ${fmt.int(p.tp)} · FP ${fmt.int(p.fp)} (Wilson 95 %)`);
}

async function doExport(ctx, id, format) {
  const C = ctx.components;
  const r = await tryApi(ctx, `/api/results/${encodeURIComponent(id)}/export`, { method: 'POST', body: { formats: [format] } });
  if (!r.ok) { C.toast(errText(r.err), 'error'); return; }
  C.toast(`Đã xuất ${format.toUpperCase()}: ${r.data.export_dir || ''} (${(r.data.files || []).length} file)`, 'ok');
}
