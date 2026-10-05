// results_findings.js — #/results/:id/findings (A5). Lọc + phân trang server-side; bấm dòng -> panel Bằng chứng.
// GET /api/results/:id/findings?label=&cwe_group=&min_tools=&tier=&in_diff=&q=&page=&size=
// GET /api/results/:id/finding/:cluster_key ; GET /api/results/:id/raw?path= (404 -> toast)
import { h, clear, makeT, fmt, partialNote, banner, tryApi, errStatus, errText, qs, debounce, select, field, resultsHeader, findRun, getComponents, rescanCommits, toolErrorsTag } from './_util.js';

let tr = (k, fb) => (fb === undefined ? k : fb);

const SIZE = 20;
const CWE_GROUPS = ['csrf', 'sensitive_exposure', 'crypto', 'hardcoded_secret', 'injection', 'xss', 'path_traversal', 'other'];
let S = null;

export async function render(root, ctx) {
  tr = makeT(ctx);
  const C = getComponents(ctx); const t = makeT(ctx);
  const id = ctx.params.id;
  S = { dead: false, ctx, C, t, id, filters: { label: '', cwe_group: '', min_tools: '', tier: '', in_diff: '', q: '' }, page: 1, data: null, loading: true, err: null, selected: ctx.params.cluster_key || null, detail: null, detailErr: null, detailLoading: false, run: null, missing: new Set() };
  clear(root);
  root.append(resultsHeader(ctx, id, 'findings', null), C.skeleton(8));
  S.run = await findRun(ctx, id);
  if (S.dead) return;
  S.root = root;
  await load();
  if (S.selected) openDetail(S.selected);
}

export function destroy() { if (S) S.dead = true; S = null; }

async function load() {
  S.loading = true; S.err = null; draw();
  const r = await tryApi(S.ctx, `/api/results/${encodeURIComponent(S.id)}/findings${qs({ ...S.filters, page: S.page, size: SIZE })}`);
  if (!S || S.dead) return;
  S.loading = false;
  if (!r.ok) S.err = r.err; else {
    S.data = r.data;
    S.missing = new Set();
    for (const row of (r.data.rows || [])) for (const k of ['tools', 'evidence', 'tier', 'label']) if (row[k] === undefined) S.missing.add(k);
  }
  draw();
}

function draw() {
  if (!S || S.dead) return;
  const { root, C, t, ctx, id } = S;
  clear(root);
  root.append(resultsHeader(ctx, id, 'findings', S.run));
  if (S.run && (S.run.status === 'running' || S.run.status === 'interrupted')) root.append(banner('warn', tr('fd.banner.ket_qua_tam_thieu_tang_dat', 'Kết quả tạm — thiếu tầng đắt'), tr('fd.banner_body.run_chua_xong_chua_relabel_n', 'Run chưa xong/chưa relabel: nhãn hiện tại chỉ từ tool đã chạy và sẽ đổi sau relabel cuối.')));
  const pn = partialNote([...S.missing]); if (pn) root.append(pn);

  // filters
  const F = S.filters;
  const upd = (k) => (v) => { F[k] = v; S.page = 1; load(); };
  const qIn = h('input', { type: 'search', class: 's-input', placeholder: 'file, commit, rule, CWE…', value: F.q, 'aria-label': 'Tìm' });
  qIn.addEventListener('input', debounce(() => { F.q = qIn.value.trim(); S.page = 1; load(); }, 300));
  const filters = h('div', { class: 's-filters' },
    field('Nhãn', select([{ value: '', label: tr('fd.btn.tat_ca', 'tất cả') }, { value: 'gold', label: tr('fd.btn.gold', 'gold') }, { value: 'silver', label: tr('fd.btn.silver', 'silver') }, { value: 'candidate', label: tr('fd.btn.candidate', 'candidate') }], F.label, upd('label'), 'Nhãn')),
    field('CWE-group', select([{ value: '', label: tr('fd.btn.tat_ca', 'tất cả') }, ...CWE_GROUPS.map((g) => ({ value: g, label: g }))], F.cwe_group, upd('cwe_group'), 'CWE-group')),
    field('Số tool đồng ý', select([{ value: '', label: tr('fd.btn.bat_ky', 'bất kỳ') }, { value: '2', label: tr('fd.btn.2', '≥ 2') }, { value: '3', label: tr('fd.btn.3', '≥ 3') }], F.min_tools, upd('min_tools'), 'Số tool')),
    field('Tier', select([{ value: '', label: tr('fd.btn.tat_ca', 'tất cả') }, { value: 'cheap', label: tr('fd.btn.cheap', 'cheap') }, { value: 'expensive', label: tr('fd.btn.expensive', 'expensive') }, { value: 'mixed', label: tr('fd.btn.mixed', 'mixed') }], F.tier, upd('tier'), 'Tier')),
    field('in_diff', select([{ value: '', label: tr('fd.btn.tat_ca', 'tất cả') }, { value: '1', label: tr('fd.btn.chi_trong_diff', 'chỉ trong diff') }, { value: '0', label: tr('fd.btn.ngoai_diff', 'ngoài diff') }], F.in_diff, upd('in_diff'), 'in_diff')),
    h('div', { class: 's-field grow' }, h('label', { for: 'f-q', text: 'Tìm' }), qIn));
  qIn.id = 'f-q';
  root.append(filters);

  const split = h('div', { class: 's-split' });
  const main = h('div', { class: 'main' });
  if (S.loading) main.append(C.card(C.skeleton(8)));
  else if (S.err) main.append(C.errorBox(S.err, () => load()));
  else {
    const d = S.data || {}; const rows = d.rows || [];
    if (!rows.length) main.append(C.empty(t('fd.empty', d.total === 0 && !Object.values(F).some(Boolean) ? 'Chưa có finding nào — run chưa quét hoặc chưa relabel.' : 'Không có finding khớp bộ lọc.')));
    else {
      main.append(C.card(C.table({
        columns: [
          { key: 'commit', label: tr('fd.btn.commit', 'commit'), render: (r) => h('span', { class: 's-mono', text: fmt.sha(r.commit) }) },
          { key: 'file_path', label: tr('fd.btn.file_dong', 'file : dòng'), render: (r) => h('span', { class: 's-mono s-ellipsis', title: r.file_path, text: `${shortPath(r.file_path)} : ${r.s_line ?? '—'}` }) },
          { key: 'cwe', label: tr('fd.btn.cwe', 'CWE'), render: (r) => h('span', {}, (r.cwe || []).join(', ') || '—', r.cwe_group ? h('span', { class: 's-muted s-small', text: ` · ${r.cwe_group}` }) : null) },
          { key: 'tools', label: tr('fd.btn.tool', 'tool'), render: (r) => r.tools ? h('span', { class: 's-tools' }, r.tools.map((x) => h('span', { class: 's-tag', text: x }))) : null },
          { key: 'label', label: tr('fd.btn.nhan', 'nhãn'), render: (r) => r.label ? C.badgeLabel(r.label, r.evidence) : null },
        ],
        rows, page: d.page || S.page, size: d.size || SIZE, total: d.total, onPage: (p) => { S.page = p; load(); },
        onRow: (r) => openDetail(r.cluster_key), rowKey: (r) => r.cluster_key, selected: S.selected,
      }), { extraClass: 's-table-card' }));
    }
  }
  split.append(main);

  // side panel
  const side = h('aside', { class: 'side', 'aria-label': 'Bằng chứng' });
  if (!S.selected) side.append(C.card(h('div', { class: 's-muted', text: 'Bấm một dòng để xem bằng chứng: diff tô dòng, tool/rule/message, raw, provenance.' }), { title: tr('fd.title.bang_chung', 'Bằng chứng') }));
  else if (S.detailLoading) side.append(C.card(C.skeleton(6), { title: tr('fd.title.bang_chung', 'Bằng chứng') }));
  else if (S.detailErr) side.append(C.card(C.errorBox(S.detailErr, () => openDetail(S.selected)), { title: tr('fd.title.bang_chung', 'Bằng chứng') }));
  else if (S.detail) side.append(detailCard(S.detail));
  split.append(side);
  root.append(split);
}

function shortPath(p) {
  if (!p) return '—';
  const parts = String(p).split('/');
  return parts.length > 3 ? `${parts[0]}/…/${parts[parts.length - 1]}` : p;
}

async function openDetail(key) {
  S.selected = key; S.detailLoading = true; S.detailErr = null; S.detail = null; draw();
  const r = await tryApi(S.ctx, `/api/results/${encodeURIComponent(S.id)}/finding/${encodeURIComponent(key)}`);
  if (!S || S.dead || S.selected !== key) return;
  S.detailLoading = false;
  if (!r.ok) S.detailErr = r.err; else S.detail = r.data;
  draw();
}

function detailCard(d) {
  const { C, ctx, id } = S;
  const row = d.row || {};
  const miss = ['diff_lines', 'tool_messages', 'provenance', 'eligible'].filter((k) => d[k] === undefined);
  const el = h('div', { class: 's-stack' });
  el.append(h('div', { class: 's-row' }, h('strong', { class: 's-mono', text: fmt.sha(row.commit) }), row.label ? C.badgeLabel(row.label, row.evidence) : null, row.tier ? h('span', { class: 's-tag', text: row.tier }) : null, h('span', { class: 's-tag', text: row.in_diff ? 'in_diff = 1' : 'in_diff = 0' })));
  el.append(h('div', { class: 's-small s-muted' }, h('span', { class: 's-mono', text: `${row.file_path || '—'} : ${row.s_line ?? '—'}` }), ` · ${(row.cwe || []).join(', ')} (${row.cwe_group || '—'}) · ${fmt.int(row.n_agree)} tool đồng ý`));
  const pn = partialNote(miss); if (pn) el.append(pn);

  // diff
  if (d.diff_lines) {
    const diff = h('div', { class: 's-diff', role: 'region', 'aria-label': 'Diff' });
    const mark = { ctx: ' ', add: '+', del: '-', flag: '!' };
    for (const l of d.diff_lines) diff.append(h('div', { class: `ln ${l.kind || 'ctx'}` }, h('span', { class: 'n', text: l.n ?? '' }), h('span', { class: 'k', text: mark[l.kind] || ' ' }), h('span', { text: l.text || '' })));
    el.append(diff);
    el.append(h('div', { class: 's-small s-muted', text: 'Tô vàng (!) = dòng tool báo (s_line); xanh (+) = dòng thêm trong commit; đỏ (−) = dòng xoá.' }));
  }
  // eligible
  if (d.eligible) el.append(h('div', { class: 's-small' }, h('strong', { text: tr('fd.text.eligible', 'Eligible: ') }), `${(d.eligible.tools || []).join(', ') || '—'} · mẫu số ${fmt.int(d.eligible.denominator)} tool — ${fmt.int(row.n_agree)}/${fmt.int(d.eligible.denominator)} đồng ý`));
  // tool messages
  if (d.tool_messages) {
    const box = h('div', { class: 's-stack', style: { gap: '0' } });
    for (const m of d.tool_messages) {
      box.append(h('div', { class: 's-toolmsg' },
        h('div', { class: 'hd' }, h('strong', { text: m.tool || '—' }), h('span', { class: 's-mono', text: m.rule_id || '' }), m.severity ? h('span', { class: 's-tag', text: m.severity }) : null, h('span', { class: 's-spacer' }),
          C.btn({ label: tr('fd.btn.mo_raw', 'Mở raw'), small: true, disabled: !m.raw_path, title: m.raw_path || 'không có raw_path', onClick: () => openRaw(m) })),
        h('div', { class: 's-small', text: m.message || '' })));
    }
    el.append(box);
  }
  // provenance
  if (d.provenance) {
    const p = d.provenance;
    el.append(h('div', { class: 's-provenance' },
      h('div', {}, h('strong', { text: tr('fd.text.provenance', 'Provenance · ') }), `run ${p.run_id || '—'} · W=${p.line_window ?? '—'} · luật gold: ${p.gold_rule || '—'}`),
      h('div', { class: 's-mono' }, (p.tools_json || []).map((tj) => h('div', { text: `${tj.name}: ${tj.image || '—'}${tj.digest ? ' @ ' + tj.digest : ''}` })))));
  }
  const ste = row.scan_tool_errors || d.scan_tool_errors || [];
  if (ste.length) el.append(h('div', { class: 's-note warn' }, toolErrorsTag(ste), ' ', h('span', { class: 's-small', text: 'Tool rẻ lỗi trên commit này — mẫu số eligible của cụm thiếu tool đó (TC-15).' })));
  el.append(h('div', { class: 's-row' },
    C.btn({ label: tr('fd.btn.kiem_tay_cum_nay', 'Kiểm tay cụm này'), small: true, onClick: () => ctx.navigate(`#/review/${id}`) }),
    ste.length ? C.btn({ label: tr('fd.btn.quet_lai_commit_nay', 'Quét lại commit này'), small: true, onClick: () => rescanCommits(ctx, C, id, [row.commit], { onDone: () => openDetail(row.cluster_key) }) }) : null,
    C.btn({ label: tr('fd.btn.dong', 'Đóng'), small: true, onClick: () => { S.selected = null; S.detail = null; draw(); } })));
  return C.card(el, { title: tr('fd.title.bang_chung', 'Bằng chứng') });
}

async function openRaw(m) {
  const { C, ctx, id } = S;
  const path = `/api/results/${encodeURIComponent(id)}/raw?path=${encodeURIComponent(m.raw_path)}`;
  const r = await tryApi(ctx, path, { raw: true });
  if (!S || S.dead) return;
  if (!r.ok) { C.toast(errStatus(r.err) === 404 ? `Chưa có raw ${m.raw_path} (backend chưa phục vụ /raw hoặc file đã bị dọn)` : errText(r.err), 'warn'); return; }
  const txt = typeof r.data === 'string' ? r.data : JSON.stringify(r.data, null, 2);
  C.dialog({ title: `Raw · ${m.tool} · ${m.raw_path}`, body: h('pre', { class: 's-mono', style: { maxHeight: '60vh', overflow: 'auto', whiteSpace: 'pre-wrap' }, text: txt.slice(0, 20000) }), confirmText: tr('fd.btn.dong', 'Đóng'), onConfirm: () => {} });
}
