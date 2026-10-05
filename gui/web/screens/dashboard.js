// dashboard.js — màn #/run/:id (A5). export render(root, ctx), destroy().
// Dữ liệu: GET /api/runs (tìm run) + SSE GET /api/run/:id/progress (ctx.sse nếu A4 cung cấp; không có -> poll ctx.api 2 s).
// Quy tắc: KHÔNG hiện nhãn gold/silver khi status=running; chỉ đếm raw.
import { h, clear, makeT, fmt, repoName, statusTag, partialNote, banner, kv, segBar, tryApi, errStatus, errText } from './_util.js';

const POLL_MS = 2000;
let S = null; // state của màn hiện tại

export async function render(root, ctx) {
  const C = ctx.components;
  const t = makeT(ctx);
  S = { root, ctx, C, t, id: ctx.params.id, run: null, lines: [], overview: null, logFilter: 'all', stopping: false, cleaned: null, timer: null, closer: null, dead: false, partialFields: new Set(), onHash: null, onUnload: null };
  clear(root);
  root.append(C.skeleton(6));

  const runs = await tryApi(ctx, '/api/runs');
  if (S.dead) return;
  if (!runs.ok) { clear(root); root.append(C.errorBox(runs.err, () => render(root, ctx))); return; }
  const list = (runs.data && runs.data.runs) || [];
  S.run = list.find((r) => r.run_id === S.id) || null;
  if (!S.run) { clear(root); root.append(C.empty(t('dash.no_run', `Không tìm thấy run "${S.id}" trong registry (runs.json).`))); return; }

  // overview (tuỳ chọn, để lấy raw_by_tool) — không chặn màn
  tryApi(ctx, `/api/results/${encodeURIComponent(S.id)}/overview`).then((r) => { if (!S.dead && r.ok) { S.overview = r.data; draw(); } });

  // progress: lần đầu đợi 1 lượt rồi vẽ
  const first = await tryApi(ctx, `/api/run/${encodeURIComponent(S.id)}/progress`);
  if (S.dead) return;
  if (!first.ok) { clear(root); root.append(C.errorBox(first.err, () => render(root, ctx))); return; }
  ingest(first.data);
  draw();
  startStream();
  guardLeave();
}

export function destroy() {
  if (!S) return;
  S.dead = true;
  if (S.timer) clearInterval(S.timer);
  if (S.closer) { try { S.closer(); } catch (_) { /* bỏ qua */ } }
  if (S.onHash) window.removeEventListener('hashchange', S.onHash);
  if (S.onUnload) window.removeEventListener('beforeunload', S.onUnload);
  S = null;
}

// ---------- stream ----------
function startStream() {
  const { ctx, id } = S;
  const path = `/api/run/${encodeURIComponent(id)}/progress`;
  if (typeof ctx.sse === 'function') {
    try {
      S.closer = ctx.sse(path, (line) => { if (S && !S.dead) { ingest([typeof line === 'string' ? JSON.parse(line) : line], true); draw(); } });
      return;
    } catch (_) { /* rơi về poll */ }
  }
  S.timer = setInterval(async () => {
    if (!S || S.dead) return;
    if (status() !== 'running' && !S.stopping) return; // không poll khi run đã kết thúc
    const r = await tryApi(ctx, path);
    if (S && !S.dead && r.ok) { ingest(r.data); draw(); }
  }, POLL_MS);
}

function ingest(data, appendMode = false) {
  const arr = Array.isArray(data) ? data : (data && Array.isArray(data.lines) ? data.lines : []);
  if (appendMode) S.lines.push(...arr); else if (arr.length >= S.lines.length) S.lines = arr;
  for (const l of S.lines) {
    if (l.phase === 'analyze' && l.event === 'item' && l.worker === undefined) S.partialFields.add('worker');
    if (l.phase === 'analyze' && l.event === 'start' && l.total === undefined) S.partialFields.add('analyze.total');
  }
}

// ---------- mô hình từ progress ----------
function model() {
  const L = S.lines;
  const m = { scan: { total: null, done: 0, finished: false }, select: { msg: null, done: false }, analyze: { total: null, done: 0, by: {}, workers: {}, items: [], started: false, finished: false }, stop: null, first: null, last: null, phases: new Set() };
  for (const l of L) {
    m.phases.add(l.phase);
    if (!m.first) m.first = l.ts; m.last = l.ts;
    if (l.phase === 'scan') {
      if (l.total !== undefined) m.scan.total = l.total;
      if (l.done !== undefined) m.scan.done = l.done;
      if (l.event === 'done') m.scan.finished = true;
    } else if (l.phase === 'select') {
      if (l.msg) m.select.msg = l.msg; if (l.event === 'done') m.select.done = true;
    } else if (l.phase === 'analyze') {
      if (l.event === 'start') { m.analyze.started = true; if (l.total !== undefined) m.analyze.total = l.total; }
      if (l.total !== undefined) m.analyze.total = l.total;
      if (l.event === 'item') {
        m.analyze.done = Math.max(m.analyze.done, l.done || 0);
        const st = l.status || 'ok';
        m.analyze.by[st] = (m.analyze.by[st] || 0) + 1;
        if (l.worker) m.analyze.workers[l.worker] = l;
        m.analyze.items.push(l);
      }
      if (l.event === 'done') m.analyze.finished = true;
    }
    if (l.event === 'stop') m.stop = l;
  }
  // ETA từ nhịp thật: trung bình khoảng cách ts giữa các analyze.item
  const its = m.analyze.items.map((x) => Date.parse(x.ts)).filter((x) => !Number.isNaN(x));
  let avg = null;
  if (its.length >= 2) avg = (its[its.length - 1] - its[0]) / (its.length - 1) / 1000;
  else if (m.scan.total && !m.analyze.started) { // ước lượng từ tầng rẻ
    const sc = L.filter((x) => x.phase === 'scan').map((x) => Date.parse(x.ts));
    if (sc.length >= 2 && m.scan.done) avg = (sc[sc.length - 1] - sc[0]) / 1000 / Math.max(1, m.scan.done);
  }
  const remain = m.analyze.started ? (m.analyze.total !== null ? m.analyze.total - m.analyze.done : null) : (m.scan.total !== null ? m.scan.total - m.scan.done : null);
  m.eta = avg !== null && remain !== null ? Math.max(0, remain * avg) : null;
  m.avg = avg;
  m.elapsed = m.first && m.last ? (Date.parse(m.last) - Date.parse(m.first)) / 1000 : null;
  return m;
}

function status() {
  const m = model();
  if (m.stop && m.stop.status === 'infra_error') return 'infra_stop';
  if (m.stop && S.run.status !== 'done') return 'stopped';
  return S.run.status || 'unknown';
}

function isScratch() { const r = S.run; return /scratch/i.test(r.run_id || '') || /scratch/i.test(r.db || ''); }

// ---------- vẽ ----------
function draw() {
  if (!S || S.dead) return;
  const { root, C, t, run } = S;
  const m = model();
  const st = status();
  const running = st === 'running';
  clear(root);

  // head
  const head = h('div', { class: 's-row s-head' },
    h('h1', {}, repoName(run.repo), ' ', h('span', { class: 's-branch', text: `/ ${run.branch || '—'}` })),
    statusTag(st === 'infra_stop' ? 'infra_error' : st),
    h('span', { class: 's-sub', text: `${t('dash.elapsed', 'đã chạy')} ${fmt.dur(m.elapsed)}${running && m.eta !== null ? ` · ${t('dash.eta', 'còn khoảng')} ${fmt.dur(m.eta)}` : ''}${m.avg ? ` · ~${fmt.dur(m.avg)}/commit` : (running ? ' · ETA: cần ≥ 2 commit tầng đắt để đo nhịp' : '')}` }),
    h('span', { class: 's-spacer' }));
  if (running) {
    head.append(C.btn({ label: t('dash.workers', 'Đổi số luồng'), small: true, onClick: changeWorkers }));
    head.append(C.btn({ label: t('dash.stop_safe', 'Dừng an toàn'), small: true, kind: 'danger', disabled: S.stopping, onClick: stopSafe }));
    head.append(C.btn({ label: t('dash.stop_force', 'Dừng cưỡng bức'), small: true, kind: 'danger', onClick: stopForce }));
  }
  if (st === 'done' || st === 'stopped') head.append(C.btn({ label: t('dash.results', 'Xem kết quả'), small: true, kind: 'primary', onClick: () => S.ctx.navigate(`#/results/${run.run_id}/overview`) }));
  head.append(C.btn({ label: t('dash.diag', 'Gói chẩn đoán'), small: true, onClick: diagnostics }));
  root.append(head);

  // banners
  if (isScratch()) root.append(banner('ok', t('dash.scratch', 'Chạy thử trên DB scratch'), 'Kết quả không ghi vào kết quả thật; dùng để kiểm tra Docker/build trước run chính.'));
  if (st === 'interrupted') root.append(banner('warn', t('dash.interrupted', 'Run bị ngắt — tiến trình nền đã chết'), 'DB còn commit ở trạng thái building/analyzing. "Dọn & Tiếp tục" sẽ reset-claims rồi chạy lại từ pha đang dở.', [C.btn({ label: 'Dọn & Tiếp tục', kind: 'primary', small: true, onClick: () => resume() })]));
  if (st === 'infra_stop') root.append(banner('bad', 'Docker/đĩa có vấn đề, run đã tự dừng', `${m.stop.msg || '3 infra_error liên tiếp'} · các commit lỗi hạ tầng đã trả về pending, không tính là dữ liệu.`, [C.btn({ label: 'Dọn & Tiếp tục', kind: 'primary', small: true, onClick: () => resume() })]));
  if (S.stopping) root.append(banner('info', t('dash.stopping', 'Đang dừng an toàn'), 'Đang chờ commit hiện tại xong (không nhận commit mới). Có thể mất tới một chu kỳ build.'));
  if (S.cleaned) root.append(banner('info', 'Đã dừng cưỡng bức · đã dọn', null, [h('ul', { class: 's-list s-mono' }, S.cleaned.length ? S.cleaned.map((c) => h('li', { text: c })) : h('li', { text: 'không có gì cần dọn' }))]));
  const pn = partialNote([...S.partialFields]); if (pn) root.append(pn);
  if (S.lines.length === 0) root.append(C.empty(t('dash.no_progress', 'Chưa có dòng tiến độ nào — run chưa ghi progress.jsonl (có thể đang clone/khởi động).')));

  // 3 thanh
  const phases = h('div', { class: 's-stack', style: { gap: '18px' } });
  // ① scan
  const scanPct = m.scan.total ? Math.min(100, (m.scan.done / m.scan.total) * 100) : 0;
  phases.append(h('div', { class: 's-phase' },
    h('div', { class: 's-phase-head' }, h('strong', { text: '① Tầng rẻ · tool source-only trên diff' }), h('span', { class: 's-mono', text: m.scan.total !== null ? `${fmt.int(m.scan.done)} / ${fmt.int(m.scan.total)}${m.scan.finished ? ' · xong' : ''}` : (m.phases.has('scan') ? `${fmt.int(m.scan.done)} / —` : 'chưa bắt đầu') })),
    h('div', { class: 's-bar', role: 'progressbar', 'aria-valuenow': Math.round(scanPct), 'aria-valuemin': 0, 'aria-valuemax': 100, 'aria-label': 'Tầng rẻ' }, h('span', { class: m.scan.finished ? 'seg-ok' : 'seg-accent', style: { width: `${scanPct}%` } }))));
  // ② select
  phases.append(h('div', { class: 's-phase' },
    h('div', { class: 's-phase-head' }, h('strong', { text: '② Chọn commit cho tầng đắt' }), h('span', { class: 's-mono', text: m.select.msg ? `${m.select.msg} → hàng đợi tầng đắt` : (m.select.done ? 'xong' : 'chờ tầng rẻ') })),
    h('div', { class: 's-bar', 'aria-label': 'Chọn commit' }, h('span', { class: 'seg-ok', style: { width: m.select.done ? '100%' : '0%' } }))));
  // ③ analyze — phân màu theo status
  const by = m.analyze.by; const tot = m.analyze.total;
  const segs = [
    { label: 'ok', value: by.ok || 0, cls: 'accent' }, { label: 'build_failed', value: by.build_failed || 0, cls: 'bad' },
    { label: 'skipped', value: by.skipped || 0, cls: 'skipped' }, { label: 'infra_error', value: by.infra_error || 0, cls: 'infra' },
    { label: 'tool_timeout/error', value: (by.tool_timeout || 0) + (by.tool_error || 0), cls: 'warn' },
  ];
  const an = h('div', { class: 's-phase' },
    h('div', { class: 's-phase-head' }, h('strong', { text: '③ Tầng đắt · build Maven → FindSecBugs → Sonar' }),
      h('span', { class: 's-mono', text: m.analyze.started ? `${fmt.int(m.analyze.done)} / ${tot !== null ? fmt.int(tot) : '—'}` : 'chưa bắt đầu' })));
  an.append(segBar(segs, tot || m.analyze.done || 1, { height: 12, legend: m.analyze.started }));
  if (m.analyze.started) {
    const ws = Object.values(m.analyze.workers).sort((a, b) => String(a.worker).localeCompare(String(b.worker)));
    an.append(h('div', { class: 's-workers' }, ws.length ? ws.map((w) => h('span', {}, h('span', { class: 's-mono', text: w.worker }), ` · ${fmt.sha(w.sha)} · `, statusTag(w.status), running ? ' · đang nhận commit kế tiếp' : '', w.msg ? h('span', { class: 's-muted', text: ` (${w.msg})` }) : null)) : h('span', { class: 's-muted', text: S.partialFields.has('worker') ? 'backend chưa gửi trường worker' : 'chưa có worker báo cáo' })));
  }
  phases.append(an);
  root.append(C.card(phases));

  // raw theo tool + nhãn
  const grid = h('div', { class: 's-grid-2' });
  const raw = S.overview && S.overview.raw_by_tool;
  if (raw && typeof raw === 'object' && Object.keys(raw).length) {
    grid.append(C.card(Object.entries(raw).map(([k, v]) => kv(k, h('span', { class: 's-mono', text: fmt.int(v) }))), { title: 'Finding thô theo tool' }));
  }
  const labelsCard = C.card([], { title: running ? 'Nhãn' : 'Nhãn (sau relabel)' });
  if (running || st === 'interrupted' || st === 'infra_stop') {
    labelsCard.append(h('div', { class: 's-note', text: t('dash.labels_hidden', 'Nhãn hiện sau khi relabel. Khi run đang chạy chỉ đếm finding thô — không hiện gold/silver tạm để tránh neo kỳ vọng và tinh chỉnh theo kết quả.') }));
  } else if (!run.summary || run.summary.gold === null || run.summary.gold === undefined) {
    labelsCard.append(h('div', { class: 's-note', text: 'Chưa có nhãn — run dừng trước pha relabel/kappa. Chạy "analyze → relabel → kappa → export" (resume) để có nhãn.' }));
  } else {
    const s = run.summary || {};
    labelsCard.append(h('div', { class: 's-row' }, C.badgeLabel('gold'), h('b', { class: 's-mono', text: fmt.int(s.gold) }), C.badgeLabel('silver'), h('b', { class: 's-mono', text: fmt.int(s.silver) }), C.badgeLabel('candidate'), h('b', { class: 's-mono', text: fmt.int(s.candidate) })));
    labelsCard.append(kv('verified-clean · 2 tool đắt không báo — không phải chứng minh sạch', h('span', { class: 's-mono', text: fmt.int(s.verified_clean) })));
    labelsCard.append(kv('cheap-clean · chỉ tool rẻ', h('span', { class: 's-mono', text: fmt.int(s.cheap_clean) })));
    labelsCard.append(kv('κ Fleiss', h('span', { class: 's-mono', text: fmt.num(s.kappa) })));
    labelsCard.append(h('a', { href: `#/results/${run.run_id}/overview`, class: 's-small', text: 'Xem kết quả →', onclick: (e) => { e.preventDefault(); S.ctx.navigate(`#/results/${run.run_id}/overview`); } }));
  }
  grid.append(labelsCard);
  root.append(grid);

  // log
  const sel = h('select', { class: 's-select', 'aria-label': 'Lọc log', style: { minHeight: '40px' } },
    h('option', { value: 'all', text: 'Tất cả' }), h('option', { value: 'err', text: 'Chỉ lỗi' }), h('option', { value: 'exp', text: 'Tầng đắt' }));
  sel.value = S.logFilter;
  sel.addEventListener('change', () => { S.logFilter = sel.value; draw(); });
  const logBox = h('div', { class: 's-log', role: 'log', 'aria-live': 'polite' });
  const lines = S.lines.filter((l) => {
    if (S.logFilter === 'err') return l.event === 'error' || l.event === 'stop' || ['build_failed', 'infra_error', 'tool_timeout', 'tool_error'].includes(l.status);
    if (S.logFilter === 'exp') return l.phase === 'analyze';
    return true;
  });
  if (!lines.length) logBox.append(h('span', { class: 'dim', text: 'không có dòng nào khớp bộ lọc' }));
  for (const l of lines.slice(-200)) {
    const cls = l.event === 'stop' || l.event === 'error' || ['build_failed', 'infra_error'].includes(l.status) ? 'err' : (['skipped', 'tool_timeout', 'tool_error'].includes(l.status) ? 'warn' : (l.status === 'ok' || l.event === 'done' ? 'ok' : ''));
    logBox.append(h('div', { class: cls }, h('span', { class: 'dim', text: `${fmt.hhmmss(l.ts)} ` }), `[${l.phase}${l.worker ? ' ' + l.worker : ''}] `, l.sha ? `${fmt.sha(l.sha)} ` : '', l.event === 'item' ? '' : `${l.event} `, l.status ? `-> ${l.status} ` : '', l.done !== undefined && l.event !== 'item' ? `${l.done}/${l.total ?? '—'} ` : '', l.msg ? h('span', { class: 'dim', text: ` ${l.msg}` }) : ''));
  }
  root.append(C.card([h('div', { class: 's-row' }, h('strong', { text: 'Log' }), sel, h('span', { class: 's-spacer' }), h('span', { class: 's-sub', text: `${S.lines.length} sự kiện · progress.jsonl` })), logBox]));
  logBox.scrollTop = logBox.scrollHeight;
}

// ---------- hành động ----------
async function stopSafe() {
  const { ctx, C } = S;
  S.stopping = true; draw();
  const r = await tryApi(ctx, `/api/run/${encodeURIComponent(S.id)}/stop`, { method: 'POST', body: { force: false } });
  if (!S || S.dead) return;
  if (!r.ok) { S.stopping = false; C.toast(errText(r.err), 'error'); draw(); return; }
  C.toast('Đã tạo stop-file — run sẽ dừng sau commit hiện tại.', 'ok');
}

function stopForce() {
  const { ctx, C } = S;
  C.dialog({
    title: 'Dừng cưỡng bức',
    body: h('div', { class: 's-stack' }, h('p', { text: 'Kill tiến trình + dọn container/network theo label orch.run và reset-claims. Commit đang build sẽ về pending (không mất dữ liệu đã ghi).' })),
    confirmText: 'Dừng cưỡng bức', typedConfirm: 'DỪNG', kind: 'danger',
    onConfirm: async () => {
      const r = await tryApi(ctx, `/api/run/${encodeURIComponent(S.id)}/stop`, { method: 'POST', body: { force: true } });
      if (!r.ok) throw r.err;
      S.cleaned = (r.data && r.data.cleaned) || []; S.stopping = false; S.run.status = 'stopped';
      draw();
    },
  });
}

async function resume(extra = {}) {
  const { ctx, C } = S;
  const r = await tryApi(ctx, `/api/run/${encodeURIComponent(S.id)}/resume`, { method: 'POST', body: extra });
  if (!S || S.dead) return false;
  if (!r.ok) { C.toast(errStatus(r.err) === 501 ? 'Chưa hỗ trợ: ' + errText(r.err) : errText(r.err), errStatus(r.err) === 501 ? 'warn' : 'error'); return false; }
  C.toast(`Đã tiếp tục từ pha ${r.data.from_phase || '?'} (pid ${r.data.pid || '?'})`, 'ok');
  S.run.status = 'running'; S.cleaned = null; S.stopping = false; S.lines = S.lines.filter((l) => l.event !== 'stop'); draw();
  if (!S.timer && !S.closer) startStream();
  return true;
}

function changeWorkers() {
  const { C } = S;
  const inp = h('input', { type: 'number', min: 1, max: 8, value: 1, class: 's-input', id: 'dash-workers', 'aria-label': 'Số luồng tầng đắt' });
  C.dialog({
    title: 'Đổi số luồng tầng đắt',
    body: h('div', { class: 's-stack' }, h('p', { text: 'Sẽ dừng an toàn (chờ commit hiện tại xong) rồi resume với số luồng mới. Mỗi luồng cần ~2–3 GB RAM Docker.' }), h('label', { for: 'dash-workers', text: 'Số luồng' }), inp),
    confirmText: 'Dừng & chạy lại',
    onConfirm: async () => {
      const n = Number(inp.value) || 1;
      const s = await tryApi(S.ctx, `/api/run/${encodeURIComponent(S.id)}/stop`, { method: 'POST', body: { force: false } });
      if (!s.ok) throw s.err;
      await resume({ workers: n });
    },
  });
}

async function diagnostics() {
  const { ctx, C } = S;
  const r = await tryApi(ctx, '/api/diagnostics');
  if (!S || S.dead) return;
  if (!r.ok) { C.toast(errStatus(r.err) === 501 || errStatus(r.err) === 404 ? 'Gói chẩn đoán chưa được backend hỗ trợ' : errText(r.err), 'warn'); return; }
  const url = typeof ctx.url === 'function' ? ctx.url('/api/diagnostics') : '/api/diagnostics';
  C.toast(`Đang tải gói chẩn đoán: ${url}`, 'ok');
  if (!String(url).startsWith('harness-')) window.open(url, '_blank');
}

// Rời màn khi run đang chạy: chỉ cảnh báo (không chặn) — Chạy nền / Dừng / Huỷ (quay lại)
function guardLeave() {
  const back = `#/run/${S.run.run_id}`;
  const snapshot = S; // S bị destroy() xoá trước khi handler chạy
  S.onHash = () => {
    if (!snapshot.run || snapshot.run.status !== 'running' || snapshot.stopping) return;
    const stateQ = location.hash.includes('state=') ? '?' + location.hash.split('?')[1] : '';
    const dlg = snapshot.C.dialog({
      title: 'Run vẫn đang chạy nền',
      body: 'Tiến trình quét là tiến trình tách rời — đóng màn này không dừng nó. Bạn muốn làm gì?',
      confirmText: 'Chạy nền', cancelText: 'Huỷ (quay lại)',
      onConfirm: () => {},
    });
    dlg.addEventListener('close', () => { if (dlg.returnValue === 'cancel') snapshot.ctx.navigate(back + stateQ); });
    const actions = dlg.querySelector('.actions') || dlg.querySelector('.sh-dialog-inner');
    if (actions) actions.prepend(snapshot.C.btn({ label: 'Dừng an toàn', kind: 'danger', onClick: async () => { await tryApi(snapshot.ctx, `/api/run/${encodeURIComponent(snapshot.id)}/stop`, { method: 'POST', body: { force: false } }); snapshot.C.toast('Đã yêu cầu dừng an toàn.', 'ok'); dlg.close('ok'); } }));
  };
  window.addEventListener('hashchange', S.onHash, { once: true });
  S.onUnload = (e) => { if (snapshot.run && snapshot.run.status === 'running') { e.preventDefault(); e.returnValue = ''; } };
  window.addEventListener('beforeunload', S.onUnload);
}
