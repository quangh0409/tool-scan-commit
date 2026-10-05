// review.js — #/review/:id (A5). Kiểm tay MÙ theo giao thức REVIEW §IV.C C9.
// B1 POST /api/review/:id/sample {seed,n_pos,n_neg} -> {sample_id, strata[]}
// B2 GET  /api/review/:id/next?sample_id=&rater= -> chỉ code_lines/diff flag/cwe_claim/messages_anon (KHÔNG nhãn, tool, precision)
//    POST /api/review/:id/verdict {sample_id, rater, cluster_key, verdict, note}
// B3 POST /api/review/:id/close {sample_id} -> precision + CI, Cohen κ 2 rater, bất đồng -> adjudication (rater "adjudicated").
import { h, clear, makeT, fmt, banner, tryApi, errText, qs, field, resultsHeader, findRun } from './_util.js';

let S = null;
const SS_KEY = (id) => `secjit.review.${id}`;

export async function render(root, ctx) {
  const C = ctx.components; const t = makeT(ctx);
  const id = ctx.params.id;
  let saved = {};
  try { saved = JSON.parse(sessionStorage.getItem(SS_KEY(id)) || '{}'); } catch (_) { saved = {}; }
  S = { dead: false, ctx, C, t, id, root, run: null, gold: null, step: saved.sample_id ? 2 : 1, sample: saved.sample || null, sampleId: saved.sample_id || null, rater: saved.rater || '', item: null, itemErr: null, itemLoading: false, note: '', closeRes: null, onKey: null, busy: false, submitting: false };
  clear(root);
  root.append(resultsHeader(ctx, id, 'review', null), C.skeleton(6));
  const [run, ov] = await Promise.all([findRun(ctx, id), tryApi(ctx, `/api/results/${encodeURIComponent(id)}/overview`)]);
  if (S.dead) return;
  S.run = run;
  if (!ov.ok) { clear(root); root.append(resultsHeader(ctx, id, 'review', run), C.errorBox(ov.err, () => render(root, ctx))); return; }
  S.gold = ov.data && ov.data.labels ? ov.data.labels.gold : null;
  S.verifiedClean = ov.data && ov.data.labels ? ov.data.labels.verified_clean : null;
  S.onKey = onKey; window.addEventListener('keydown', S.onKey);
  draw();
  if (S.step === 2 && S.rater) nextItem();
}

export function destroy() { if (S) { S.dead = true; if (S.onKey) window.removeEventListener('keydown', S.onKey); } S = null; }

function persist() { try { sessionStorage.setItem(SS_KEY(S.id), JSON.stringify({ sample_id: S.sampleId, sample: S.sample, rater: S.rater })); } catch (_) { /* bỏ qua */ } }

function draw() {
  if (!S || S.dead) return;
  const { root, C, t, ctx, id } = S;
  clear(root);
  root.append(resultsHeader(ctx, id, 'review', S.run));
  if (!S.gold) { root.append(C.empty(t('rv.empty', 'Chưa có cụm gold để kiểm — chạy relabel trước, hoặc run này không có cụm ≥2 tool đắt đồng ý.'))); return; }
  root.append(h('div', { class: 's-steps' },
    stepPill(1, 'Tạo mẫu phân tầng'), '→', stepPill(2, 'Chấm mù'), '→', stepPill(3, 'Đóng phiên · precision')));
  root.append(h('div', { class: 's-blind', text: 'Giao thức mù: trong lúc chấm, giao diện KHÔNG hiện nhãn, tên tool, số tool đồng ý hay precision tạm — tránh anchoring. Precision chỉ hiện sau khi đóng phiên.' }));
  if (S.step === 1) root.append(stepSample());
  else if (S.step === 2) root.append(stepRate());
  else root.append(stepClose());
}

function stepPill(n, label) { return h('span', { class: `step ${S.step === n ? 'on' : (S.step > n ? 'done' : '')}`.trim(), text: `${n}. ${label}` }); }

// ---------- B1 ----------
function stepSample() {
  const { C, ctx, id } = S;
  const seed = h('input', { type: 'number', class: 's-input', value: 42, min: 0, 'aria-label': 'seed' });
  const npos = h('input', { type: 'number', class: 's-input', value: Math.min(200, S.gold || 200), min: 1, 'aria-label': 'n_pos' });
  const nneg = h('input', { type: 'number', class: 's-input', value: Math.min(100, S.verifiedClean || 100), min: 0, 'aria-label': 'n_neg' });
  const form = h('div', { class: 's-stack' },
    h('p', { class: 's-small s-muted', text: `Mẫu ngẫu nhiên phân tầng CWE-group × tier (seed ghi vào gold_sample). Có ${fmt.int(S.gold)} cụm gold · ${fmt.int(S.verifiedClean)} commit verified-clean.` }),
    h('div', { class: 's-grid-2' }, field('Seed', seed, 'ghi vào DB để tái lập'), field('Số cụm gold (n_pos)', npos, 'clamp theo số cụm có'), field('Số verified-clean (n_neg)', nneg, 'chấm cả âm để đo FN của tầng đắt')),
    h('div', { class: 's-row' }, C.btn({ label: S.busy ? 'Đang tạo…' : 'Tạo mẫu', kind: 'primary', disabled: S.busy, onClick: async () => {
      S.busy = true; draw();
      const r = await tryApi(ctx, `/api/review/${encodeURIComponent(id)}/sample`, { method: 'POST', body: { seed: Number(seed.value) || 0, n_pos: Number(npos.value) || 0, n_neg: Number(nneg.value) || 0 } });
      if (!S || S.dead) return;
      S.busy = false;
      if (!r.ok) { C.toast(errText(r.err), 'error'); draw(); return; }
      S.sample = r.data; S.sampleId = r.data.sample_id; persist(); draw();
    } })));
  const parts = [C.card(form, { title: 'Bước 1 · Tạo mẫu' })];
  if (S.sample) {
    const st = S.sample.strata;
    parts.push(C.card(h('div', { class: 's-stack' },
      h('div', { class: 's-row' }, h('strong', { class: 's-mono', text: S.sample.sample_id }), h('span', { class: 's-tag', text: `n_pos ${fmt.int(S.sample.n_pos)}` }), h('span', { class: 's-tag', text: `n_neg ${fmt.int(S.sample.n_neg)}` })),
      st === undefined ? h('div', { class: 's-note warn', text: 'Backend chưa trả strata[].' }) : C.table({ columns: [{ key: 'stratum', label: 'Tầng (CWE-group|tier hoặc neg|mức)' }, { key: 'n', label: 'n', render: (r) => fmt.int(r.n) }], rows: st }),
      h('div', { class: 's-row' }, C.btn({ label: 'Bắt đầu chấm mù →', kind: 'primary', onClick: () => { S.step = 2; draw(); } }))), { title: 'Mẫu đã tạo' }));
  }
  return h('div', { class: 's-stack' }, parts);
}

// ---------- B2 ----------
function stepRate() {
  const { C } = S;
  const raterIn = h('input', { type: 'text', class: 's-input', value: S.rater, placeholder: 'vd. rater1 (tác giả), rater2 (đồng nghiệp)', 'aria-label': 'Người chấm' });
  raterIn.addEventListener('change', () => { S.rater = raterIn.value.trim(); persist(); if (S.rater) nextItem(); else draw(); });
  const head = h('div', { class: 's-row' },
    h('span', { class: 's-tag s-mono', text: S.sampleId || '—' }),
    field('Người chấm (rater)', raterIn, 'lưu trong phiên; mỗi rater chấm độc lập'),
    h('span', { class: 's-spacer' }),
    S.item && S.item.remaining !== undefined ? h('span', { class: 's-sub', text: `còn ${fmt.int(S.item.remaining)} mục` }) : null,
    C.btn({ label: 'Đóng phiên →', small: true, onClick: () => { S.step = 3; draw(); closeSession(); } }),
    C.btn({ label: 'Tạo mẫu khác', small: true, onClick: () => { S.step = 1; S.sample = null; S.sampleId = null; S.item = null; persist(); draw(); } }));
  const parts = [C.card(head)];
  if (!S.rater) { parts.push(C.empty('Nhập tên rater để bắt đầu.')); return h('div', { class: 's-stack' }, parts); }
  if (S.itemLoading) { parts.push(C.card(C.skeleton(8), { title: 'Mục đang chấm' })); return h('div', { class: 's-stack' }, parts); }
  if (S.itemErr) { parts.push(C.errorBox(S.itemErr, nextItem)); return h('div', { class: 's-stack' }, parts); }
  const it = S.item;
  if (!it || !it.cluster_key) { parts.push(C.card(h('div', { class: 's-stack' }, h('p', { text: 'Rater này đã chấm hết mẫu.' }), h('div', { class: 's-row' }, C.btn({ label: 'Đóng phiên · xem precision', kind: 'primary', onClick: () => { S.step = 3; draw(); closeSession(); } }))), { title: 'Xong' })); return h('div', { class: 's-stack' }, parts); }

  const flagged = new Set((it.diff_lines || []).filter((d) => d.kind === 'flag').map((d) => d.n));
  const code = h('div', { class: 's-review-code', role: 'region', 'aria-label': 'Mã nguồn' });
  if (it.code_lines === undefined) code.append(h('div', { class: 'ln', text: 'Backend chưa trả code_lines — chỉ có diff:' }));
  for (const l of (it.code_lines || it.diff_lines || [])) code.append(h('div', { class: `ln ${flagged.has(l.n) || l.kind === 'flag' ? 'flag' : ''}`.trim() }, h('span', { class: 'n', text: l.n ?? '' }), h('span', { text: l.text || '' })));
  const noteIn = h('textarea', { class: 's-textarea', placeholder: 'Ghi chú (tuỳ chọn): vì sao TP/FP, dòng nào…', 'aria-label': 'Ghi chú' });
  noteIn.addEventListener('input', () => { S.note = noteIn.value; });
  S.noteEl = noteIn;
  const body = h('div', { class: 's-stack' },
    h('div', { class: 's-row' }, h('strong', { text: 'Tuyên bố: ' }), h('span', { class: 's-tag', text: it.cwe_claim || '—' }), h('span', { class: 's-sub s-mono', text: `cụm ${String(it.cluster_key).slice(0, 8)}…` })),
    code,
    h('div', { class: 's-small', text: 'Dòng tô vàng = vị trí tool báo. Câu hỏi: tại dòng đó có thật lỗi thuộc CWE nêu trên không?' }),
    it.messages_anon && it.messages_anon.length ? h('div', { class: 's-stack', style: { gap: '4px' } }, h('strong', { class: 's-small', text: 'Thông điệp (ẩn danh tool):' }), h('ul', { class: 's-list s-small' }, it.messages_anon.map((m) => h('li', { text: m })))) : null,
    field('Ghi chú', noteIn),
    h('div', { class: 's-verdicts' },
      C.btn({ label: 'Đúng (TP) · phím T', kind: 'primary', disabled: S.submitting, onClick: () => verdict('TP') }),
      C.btn({ label: 'Sai (FP) · phím F', kind: 'danger', disabled: S.submitting, onClick: () => verdict('FP') }),
      C.btn({ label: 'Không rõ · phím U', disabled: S.submitting, onClick: () => verdict('unclear') })));
  parts.push(C.card(body, { title: 'Mục đang chấm (mù)' }));
  return h('div', { class: 's-stack' }, parts);
}

async function nextItem() {
  if (!S || !S.rater) return;
  S.itemLoading = true; S.itemErr = null; S.note = ''; draw();
  const r = await tryApi(S.ctx, `/api/review/${encodeURIComponent(S.id)}/next${qs({ sample_id: S.sampleId, rater: S.rater })}`);
  if (!S || S.dead) return;
  S.itemLoading = false;
  if (!r.ok) S.itemErr = r.err; else S.item = r.data;
  draw();
}

async function verdict(v) {
  if (!S || !S.item || !S.item.cluster_key || S.submitting) return;
  const { C, ctx, id } = S;
  S.submitting = true;
  const r = await tryApi(ctx, `/api/review/${encodeURIComponent(id)}/verdict`, { method: 'POST', body: { sample_id: S.sampleId, rater: S.rater, cluster_key: S.item.cluster_key, verdict: v, note: S.note || '' } });
  if (!S || S.dead) return;
  S.submitting = false;
  if (!r.ok) { C.toast(errText(r.err), 'error'); draw(); return; }
  C.toast(`Đã ghi ${v} · còn ${fmt.int(r.data.remaining)}`, 'ok');
  nextItem();
}

function onKey(e) {
  if (!S || S.step !== 2 || !S.item) return;
  const tag = (e.target && e.target.tagName) || '';
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || e.ctrlKey || e.metaKey || e.altKey) return;
  const k = e.key.toLowerCase();
  if (k === 't') { e.preventDefault(); verdict('TP'); } else if (k === 'f') { e.preventDefault(); verdict('FP'); } else if (k === 'u') { e.preventDefault(); verdict('unclear'); }
}

// ---------- B3 ----------
async function closeSession() {
  const { ctx, id } = S;
  S.closeRes = null; S.closeErr = null; draw();
  const r = await tryApi(ctx, `/api/review/${encodeURIComponent(id)}/close`, { method: 'POST', body: { sample_id: S.sampleId } });
  if (!S || S.dead) return;
  if (!r.ok) S.closeErr = r.err; else S.closeRes = r.data;
  draw();
}

function stepClose() {
  const { C } = S;
  if (S.closeErr) return h('div', { class: 's-stack' }, C.errorBox(S.closeErr, closeSession), C.btn({ label: '← Quay lại chấm', onClick: () => { S.step = 2; draw(); } }));
  if (!S.closeRes) return C.card(C.skeleton(6), { title: 'Đang đóng phiên…' });
  const d = S.closeRes; const p = d.precision || {};
  const prec = h('div', { class: 's-stack' },
    h('div', { class: 's-row' }, h('span', { class: 's-big s-mono', text: fmt.num(p.point) }), h('span', { class: 's-muted', text: `precision gold · CI 95 % Wilson [${fmt.num(p.ci_low)}, ${fmt.num(p.ci_high)}] · n=${fmt.int(p.n)}` })),
    h('div', { class: 's-row' }, h('span', { class: 's-tag st-ok', text: `TP ${fmt.int(p.tp)}` }), h('span', { class: 's-tag st-bad', text: `FP ${fmt.int(p.fp)}` }), h('span', { class: 's-tag', text: `không rõ ${fmt.int(p.unclear)}` })),
    h('p', { class: 's-small s-muted', text: 'Con số này là precision của nhãn gold (đồng thuận máy) đo trên mẫu phân tầng; ghi vào luận văn kèm n và CI, không gộp với silver.' }));
  const parts = [C.card(prec, { title: 'Bước 3 · Precision kiểm tay' })];
  if (d.kappa_raters === undefined) parts.push(h('div', { class: 's-note warn', text: 'Backend chưa trả kappa_raters/disagreements.' }));
  else if (d.kappa_raters) {
    const k = d.kappa_raters;
    parts.push(C.card(h('div', { class: 's-row' }, h('span', { class: 's-big s-mono', text: fmt.num(k.value) }), h('span', { class: 's-muted', text: `Cohen κ giữa ${(k.raters || []).join(' và ')} · n=${fmt.int(k.n)}` })), { title: 'Đồng thuận giữa 2 rater' }));
  } else parts.push(banner('info', 'Chỉ có 1 rater', 'Thêm rater thứ hai (cùng sample_id) để tính Cohen κ và bảng bất đồng.'));
  const dis = d.disagreements || [];
  if (dis.length) {
    const raters = Object.keys(dis[0].verdicts || {});
    const rows = C.table({
      columns: [
        { key: 'cluster_key', label: 'cụm', render: (r) => h('span', { class: 's-mono', text: String(r.cluster_key).slice(0, 12) + '…' }) },
        ...raters.map((rt) => ({ key: rt, label: rt, render: (r) => h('span', { class: `s-tag ${{ TP: 'st-ok', FP: 'st-bad' }[r.verdicts[rt]] || ''}`, text: r.verdicts[rt] || '—' }) })),
        { key: 'adj', label: 'Phán quyết cuối (adjudicated)', render: (r) => adjRow(r) },
      ],
      rows: dis,
    });
    parts.push(C.card(h('div', { class: 's-stack' }, h('p', { class: 's-small s-muted', text: 'Hai rater cùng xem lại, thống nhất một phán quyết; ghi với rater = "adjudicated". Precision cuối tính trên phán quyết này.' }), rows), { title: `Bất đồng (${dis.length})` }));
  }
  parts.push(h('div', { class: 's-row' }, C.btn({ label: '← Quay lại chấm', onClick: () => { S.step = 2; draw(); nextItem(); } }), C.btn({ label: 'Tính lại sau adjudication', kind: 'primary', onClick: closeSession })));
  return h('div', { class: 's-stack' }, parts);
}

function adjRow(r) {
  const { C, ctx, id } = S;
  const sel = h('select', { class: 's-select', 'aria-label': 'Phán quyết cuối' }, h('option', { value: '', text: '— chọn —' }), h('option', { value: 'TP', text: 'TP' }), h('option', { value: 'FP', text: 'FP' }), h('option', { value: 'unclear', text: 'không rõ' }));
  if (r.adjudicated) sel.value = r.adjudicated;
  const b = C.btn({ label: 'Ghi', small: true, onClick: async () => {
    if (!sel.value) { C.toast('Chọn phán quyết trước.', 'warn'); return; }
    const x = await tryApi(ctx, `/api/review/${encodeURIComponent(id)}/verdict`, { method: 'POST', body: { sample_id: S.sampleId, rater: 'adjudicated', cluster_key: r.cluster_key, verdict: sel.value, note: 'adjudication' } });
    if (!x.ok) { C.toast(errText(x.err), 'error'); return; }
    r.adjudicated = sel.value; C.toast('Đã ghi phán quyết cuối.', 'ok');
  } });
  return h('div', { class: 's-row' }, sel, b);
}
