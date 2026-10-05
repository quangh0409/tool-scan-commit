// settings.js — #/settings/:tab (A5). Tab: docker | storage | profiles | language | mode.
// docker: GET /api/preflight + GET/POST /api/settings · storage: GET /api/storage, POST /api/clean {items, dry_run}
// profiles: GET /api/profiles, DELETE /api/profiles/:name · language: POST /api/settings {language} · mode: chỉ Local.
import { h, clear, makeT, fmt, kv, banner, tryApi, errStatus, errText, tabs, field, segBar, partialNote, getComponents } from './_util.js';

let tr = (k, fb) => (fb === undefined ? k : fb);

const TABS = [
  { id: 'docker', label: tr('set.btn.docker_tai_nguyen', 'Docker & tài nguyên') }, { id: 'storage', label: tr('set.btn.dung_luong', 'Dung lượng') }, { id: 'profiles', label: tr('set.btn.profile', 'Profile') },
  { id: 'mode', label: tr('set.btn.che_do_chay', 'Chế độ chạy') }, { id: 'language', label: tr('set.btn.ngon_ngu', 'Ngôn ngữ') },
];
const SAFETY = { safe: 'an toàn', slow: 'xoá sẽ làm chậm', rebuild: 'tải/build lại khi dùng', forbidden: 'KHÔNG tự xoá' };
let S = null;

export async function render(root, ctx) {
  tr = makeT(ctx);
  const C = getComponents(ctx); const t = makeT(ctx);
  const alias = { general: 'docker', resources: 'docker', disk: 'storage', lang: 'language' };
  const want = alias[ctx.params.tab] || ctx.params.tab;
  const tab = TABS.some((x) => x.id === want) ? want : 'docker';
  S = { dead: false, ctx, C, t, root, tab, body: null, preview: null };
  clear(root);
  root.append(h('div', { class: 's-head' }, h('h1', { text: t('set.title', 'Cài đặt') })));
  root.append(tabs(TABS, tab, (id) => ctx.navigate(`#/settings/${id}`)));
  S.body = h('div', { class: 's-stack', role: 'tabpanel' });
  root.append(S.body);
  await ({ docker: tabDocker, storage: tabStorage, profiles: tabProfiles, language: tabLanguage, mode: tabMode })[tab]();
}

export function destroy() { if (S) S.dead = true; S = null; }

function setBody(...nodes) { if (!S || S.dead) return; clear(S.body); S.body.append(...nodes.filter(Boolean)); }

// ---------- Docker & tài nguyên ----------
async function tabDocker() {
  const { C, ctx } = S;
  setBody(C.skeleton(8));
  const [pf, st] = await Promise.all([tryApi(ctx, '/api/preflight', { timeout: 180000 }), tryApi(ctx, '/api/settings')]);
  if (!S || S.dead) return;
  if (!pf.ok) { setBody(C.errorBox(pf.err, tabDocker)); return; }
  const d = pf.data || {}; const items = d.items || [];
  if (!items.length) { setBody(C.empty(tr('set.empty.preflight_chua_co_ket_qua_ba', 'Preflight chưa có kết quả — bấm "Kiểm lại".')), h('div', {}, C.btn({ label: tr('set.btn.kiem_lai_preflight', 'Kiểm lại preflight'), kind: 'primary', onClick: tabDocker }))); return; }
  const miss = ['docker_mem_gb', 'cpu'].filter((k) => d[k] === undefined);
  const byId = Object.fromEntries(items.map((i) => [i.id, i]));
  const lvl = (i) => h('span', { class: `s-tag st-${{ ok: 'ok', fix: 'infra', warn: 'warn', bad: 'bad' }[i.level] || 'muted'}`, text: i.level });
  const res = h('div', { class: 's-stack' },
    kv('RAM cấp cho Docker (MemTotal)', h('span', { class: 's-mono', text: d.docker_mem_gb !== undefined ? `${fmt.num(d.docker_mem_gb, 1)} GB` : '—' })),
    kv('CPU', h('span', { class: 's-mono', text: d.cpu !== undefined ? String(d.cpu) : '—' })),
    kv('Port SonarQube', h('span', {}, byId.sonar_port ? [lvl(byId.sonar_port), ' ', h('span', { class: 's-small', text: byId.sonar_port.detail || '' })] : '—')),
    kv('Image tool', h('span', {}, byId.images ? [lvl(byId.images), ' ', h('span', { class: 's-small', text: byId.images.detail || '' })] : '—')),
    kv('Image đã pin (digest)', h('span', {}, byId.images_pinned ? [lvl(byId.images_pinned), ' ', h('span', { class: 's-small', text: byId.images_pinned.detail || '' })] : '—')),
    kv('Docker daemon', h('span', {}, byId.docker_daemon ? [lvl(byId.docker_daemon), ' ', h('span', { class: 's-small', text: byId.docker_daemon.detail || '' })] : '—')),
    h('div', { class: 's-row' }, C.btn({ label: tr('set.btn.kiem_lai_preflight', 'Kiểm lại preflight'), kind: 'primary', onClick: tabDocker }), h('span', { class: 's-sub', text: `${items.length} mục · sẵn sàng: ${d.ready ? 'có' : 'chưa'}` })));
  const full = C.table({ columns: [{ key: 'title', label: tr('set.btn.muc', 'Mục') }, { key: 'level', label: tr('set.btn.muc_2', 'Mức'), render: lvl }, { key: 'detail', label: tr('set.btn.chi_tiet', 'Chi tiết') }], rows: items });

  // settings form
  let form = null;
  if (st.ok) {
    const s = st.data || {};
    const inp = (k, type = 'text') => h('input', { type, class: 's-input', value: s[k] ?? '', name: k, 'aria-label': k });
    const out = inp('out_dir'); const work = inp('work_dir'); const port = inp('sonar_port', 'number'); const ram = inp('codeql_ram_mb', 'number');
    const m2 = h('input', { type: 'checkbox', id: 'set-m2', checked: s.m2_volume ? true : null });
    form = h('div', { class: 's-stack' },
      h('div', { class: 's-grid-2' }, field('Thư mục kết quả (out_dir)', out), field('Thư mục làm việc (work_dir)', work, 'không đặt trùng out_dir — dọn dẹp sẽ xoá nhầm'), field('Port SonarQube', port), field('RAM CodeQL (MB)', ram)),
      h('label', { class: 's-check', for: 'set-m2' }, m2, 'Dùng Docker volume secjit-m2 cho cache Maven (build warm nhanh 3–5 lần)'),
      h('div', { class: 's-row' }, C.btn({ label: tr('set.btn.luu', 'Lưu'), kind: 'primary', onClick: async () => {
        const body = { ...s, out_dir: out.value, work_dir: work.value, sonar_port: Number(port.value) || s.sonar_port, codeql_ram_mb: Number(ram.value) || s.codeql_ram_mb, m2_volume: m2.checked };
        if (body.out_dir && body.out_dir === body.work_dir) { C.toast(tr('set.toast.out_dir_khong_duoc_trung_wor', 'out_dir không được trùng work_dir.'), 'error'); return; }
        const r = await tryApi(ctx, '/api/settings', { method: 'POST', body });
        C.toast(r.ok ? 'Đã lưu cài đặt.' : errText(r.err), r.ok ? 'ok' : 'error');
      } })));
  } else form = C.errorBox(st.err, tabDocker);
  setBody(partialNote(miss), h('div', { class: 's-grid-2' }, C.card(res, { title: tr('set.title.tai_nguyen_docker', 'Tài nguyên Docker') }), C.card(form, { title: tr('set.title.duong_dan_tham_so', 'Đường dẫn & tham số') })), C.card(full, { title: tr('set.title.preflight_day_du_13_muc', 'Preflight đầy đủ (13 mục)') }));
}

// ---------- Dung lượng ----------
async function tabStorage() {
  const { C, ctx } = S;
  setBody(C.skeleton(8));
  const r = await tryApi(ctx, '/api/storage', { timeout: 120000 });  // Docker bận có thể chậm
  if (!S || S.dead) return;
  if (!r.ok) { setBody(C.errorBox(r.err, tabStorage)); return; }
  const d = r.data || {}; const items = d.items || [];
  if (!items.length) { setBody(C.empty(tr('set.empty.chua_co_gi_de_don_chua_chay', 'Chưa có gì để dọn — chưa chạy run nào hoặc thư mục làm việc trống.'))); return; }
  const miss = []; if (d.free_bytes === undefined) miss.push('free_bytes'); if (items.some((i) => i.safety === undefined)) miss.push('items[].safety');
  const total = d.total_bytes || items.reduce((a, i) => a + (i.bytes || 0), 0);
  const CLS = { pool: 'bad', clone: 'accent2', m2: 'accent3', images: 'accent', results: 'ok' };
  const segs = items.map((i) => ({ label: i.title, value: i.bytes || 0, cls: CLS[i.id] || 'muted' }));
  const head = h('div', { class: 's-stack' },
    h('div', { class: 's-row' }, h('strong', { text: `Tool đang chiếm ${fmt.bytes(total)}` }), h('span', { class: 's-sub', text: d.free_bytes !== undefined ? `còn trống ${fmt.bytes(d.free_bytes)}` : 'còn trống: —' })),
    segBar(segs, total, { height: 14, fmtVal: fmt.bytes }));
  const rows = C.table({
    columns: [
      { key: 'title', label: tr('set.btn.muc', 'Mục'), render: (i) => h('div', {}, h('strong', { text: i.title }), h('div', { class: 's-muted s-small', text: i.detail || '' })) },
      { key: 'path', label: tr('set.btn.duong_dan', 'Đường dẫn'), render: (i) => h('span', { class: 's-mono', text: i.path || '—' }) },
      { key: 'bytes', label: tr('set.btn.dung_luong', 'Dung lượng'), render: (i) => h('span', { class: 's-mono', text: fmt.bytes(i.bytes) }) },
      { key: 'safety', label: tr('set.btn.an_toan_xoa', 'An toàn xoá?'), render: (i) => i.safety ? h('span', { class: `s-tag ${{ safe: 'st-ok', slow: 'st-warn', rebuild: 'st-warn', forbidden: 'st-bad' }[i.safety] || ''}`, text: SAFETY[i.safety] || i.safety }) : h('span', { class: 's-muted', text: 'chưa rõ — không xoá' }) },
      { key: 'act', label: '', render: (i) => (i.safety && i.safety !== 'forbidden') ? C.btn({ label: tr('set.btn.xoa', 'Xoá…'), small: true, onClick: () => previewClean(i) }) : (i.safety === 'forbidden' ? C.btn({ label: tr('set.btn.mo_thu_muc', 'Mở thư mục'), small: true, onClick: () => openDir(i.path) }) : '') },
    ],
    rows: items,
  });
  for (const tr of rows.querySelectorAll('tbody tr')) { const idx = [...tr.parentNode.children].indexOf(tr); if (items[idx] && items[idx].safety === 'forbidden') tr.classList.add('s-forbidden'); }
  S.previewHost = h('div');
  setBody(partialNote(miss), C.card(head), C.card(rows), S.previewHost, h('p', { class: 's-sub', text: tr('set.text.tool_luon_liet_ke_dung_nhung', 'Tool luôn liệt kê đúng những gì sẽ xoá (dry_run) trước khi bạn xác nhận. Kết quả đã xuất không bao giờ nằm trong danh sách này.') }));
}

async function previewClean(item) {
  const { C, ctx } = S;
  clear(S.previewHost); S.previewHost.append(C.card(C.skeleton(3), { title: `Xem trước khi xoá · ${item.title}` }));
  const r = await tryApi(ctx, '/api/clean', { method: 'POST', body: { items: [item.id], dry_run: true } });
  if (!S || S.dead) return;
  clear(S.previewHost);
  if (!r.ok) { C.toast(errStatus(r.err) === 409 ? `Không xoá được: ${errText(r.err)}` : errText(r.err), 'error'); return; }
  const wd = r.data.would_delete || [];
  const sum = wd.reduce((a, x) => a + (x.bytes || 0), 0);
  const body = h('div', { class: 's-stack' },
    wd.length ? h('div', { class: 's-mono', style: { lineHeight: '1.7' } }, wd.map((x) => h('div', { text: `${x.path} · ${fmt.bytes(x.bytes)}` }))) : h('div', { class: 's-muted', text: 'Không có gì để xoá.' }),
    (r.data.errors || []).length ? h('div', { class: 's-note warn', text: `Lỗi: ${r.data.errors.join('; ')}` }) : null,
    h('div', { class: 's-row' },
      C.btn({ label: `Xoá ${wd.length} mục · ${fmt.bytes(sum)}`, kind: 'danger', disabled: !wd.length, onClick: () => confirmClean(item, wd, sum) }),
      C.btn({ label: tr('set.btn.huy', 'Huỷ'), onClick: () => clear(S.previewHost) })),
    item.safety === 'slow' ? h('div', { class: 's-note warn', text: tr('set.note.xoa_cache_maven_lam_build_la', 'Xoá cache Maven làm build lần sau chậm 3–5 lần.') }) : null,
    item.safety === 'rebuild' ? h('div', { class: 's-note warn', text: tr('set.note.image_se_phai_tai_build_lai', 'Image sẽ phải tải/build lại (~6 GB, orch-findsecbugs build ~5 phút).') }) : null);
  S.previewHost.append(C.card(body, { title: `Xem trước khi xoá · ${item.title}`, extraClass: 's-preview' }));
}

function confirmClean(item, wd, sum) {
  const { C, ctx } = S;
  C.dialog({
    title: `Xoá ${item.title}?`, body: `${wd.length} mục · ${fmt.bytes(sum)}. Không khôi phục được.`,
    confirmText: tr('set.btn.xoa_2', 'Xoá'), kind: 'danger', typedConfirm: item.safety === 'safe' ? undefined : 'XOA',
    onConfirm: async () => {
      const r = await tryApi(ctx, '/api/clean', { method: 'POST', body: { items: [item.id], dry_run: false } });
      if (!r.ok) throw r.err;
      const del = r.data.deleted || [];
      C.toast(`Đã xoá ${del.length} mục${(r.data.errors || []).length ? ` · ${r.data.errors.length} lỗi` : ''}.`, (r.data.errors || []).length ? 'warn' : 'ok');
      tabStorage();
    },
  });
}

async function openDir(path) {
  const { C, ctx } = S;
  const r = await tryApi(ctx, `/api/open?path=${encodeURIComponent(path || '')}`, { method: 'POST', body: { path } });
  if (!S || S.dead) return;
  if (!r.ok) C.toast(errStatus(r.err) === 501 || errStatus(r.err) === 404 ? `Chưa hỗ trợ mở thư mục — ${path}` : errText(r.err), 'warn');
}

// ---------- Profile ----------
async function tabProfiles() {
  const { C, ctx } = S;
  setBody(C.skeleton(4));
  const r = await tryApi(ctx, '/api/profiles');
  if (!S || S.dead) return;
  if (!r.ok) { setBody(C.errorBox(r.err, tabProfiles)); return; }
  const list = (r.data && r.data.profiles) || [];
  if (!list.length) { setBody(C.empty(tr('set.empty.chua_co_profile_nao_luu_tu_w', 'Chưa có profile nào — lưu từ Wizard bước 5 ("Lưu profile").'))); return; }
  setBody(C.card(C.table({
    columns: [
      { key: 'name', label: tr('set.btn.ten', 'Tên'), render: (p) => h('strong', { text: p.name }) },
      { key: 'repo', label: tr('set.btn.repo', 'Repo'), render: (p) => h('span', { class: 's-mono', text: p.repo || '—' }) },
      { key: 'saved', label: tr('set.btn.luu_luc', 'Lưu lúc'), render: (p) => fmt.time(p.saved) },
      { key: 'act', label: '', render: (p) => h('div', { class: 's-row' },
        C.btn({ label: tr('set.btn.nap_vao_wizard', 'Nạp vào wizard'), small: true, kind: 'primary', onClick: () => ctx.navigate(`#/wizard/1?profile=${encodeURIComponent(p.name)}`) }),
        C.btn({ label: tr('set.btn.xoa_2', 'Xoá'), small: true, kind: 'danger', onClick: () => C.dialog({ title: `Xoá profile "${p.name}"?`, body: 'Chỉ xoá file profile, không đụng DB/export.', confirmText: tr('set.btn.xoa_2', 'Xoá'), kind: 'danger', onConfirm: async () => { const d = await tryApi(ctx, `/api/profiles/${encodeURIComponent(p.name)}`, { method: 'DELETE' }); if (!d.ok) throw d.err; C.toast(tr('set.toast.da_xoa_profile', 'Đã xoá profile.'), 'ok'); tabProfiles(); } }) })) },
    ],
    rows: list,
  }), { title: `Profile đã lưu (${list.length}) · %LOCALAPPDATA%\\secjit\\profiles\\` }));
}

// ---------- Ngôn ngữ ----------
async function tabLanguage() {
  const { C, ctx } = S;
  setBody(C.skeleton(2));
  const r = await tryApi(ctx, '/api/settings');
  if (!S || S.dead) return;
  if (!r.ok) { setBody(C.errorBox(r.err, tabLanguage)); return; }
  const cur = (r.data && r.data.language) || 'vi';
  const mk = (v, label) => { const i = h('input', { type: 'radio', name: 'lang', value: v, id: `lang-${v}`, checked: cur === v ? true : null }); return h('label', { class: 's-check', for: `lang-${v}` }, i, label); };
  const grp = h('div', { class: 's-radio-group' }, mk('vi', 'Tiếng Việt'), mk('en', 'English'));
  setBody(C.card(h('div', { class: 's-stack' }, grp,
    h('div', { class: 's-row' }, C.btn({ label: tr('set.btn.luu', 'Lưu'), kind: 'primary', onClick: async () => {
      const v = grp.querySelector('input:checked').value;
      const s = await tryApi(ctx, '/api/settings', { method: 'POST', body: { ...r.data, language: v } });
      C.toast(s.ok ? 'Đã lưu ngôn ngữ — tải lại giao diện để áp dụng.' : errText(s.err), s.ok ? 'ok' : 'error');
    } })),
    h('p', { class: 's-sub', text: tr('set.text.chuoi_i18n_o_gui_web_i18n_vi', 'Chuỗi i18n ở gui/web/i18n/vi.json, en.json; khoá thiếu sẽ hiện nguyên khoá để QA bắt.') })), { title: tr('set.title.ngon_ngu_giao_dien', 'Ngôn ngữ giao diện') }));
}

// ---------- Chế độ chạy ----------
async function tabMode() {
  const { C } = S;
  setBody(C.card(h('div', { class: 's-stack' },
    h('div', { class: 's-row' }, h('span', { class: 's-tag st-ok', text: 'Local' }), h('span', { text: 'Chạy pipeline + Docker trên máy này (tiến trình tách rời, sống khi đóng cửa sổ).' })),
    h('div', { class: 's-note', text: tr('set.note.vm_tu_xa_ssh_toi_gcp_nhu_run', 'VM từ xa (SSH tới GCP, như runbook skywalking): sau MVP. Hiện tại chỉ hỗ trợ Local.') })), { title: tr('set.title.che_do_chay', 'Chế độ chạy') }),
  banner('info', tr('set.banner.phuong_phap_luan_dong_bang', 'Phương pháp luận đóng băng'), tr('set.banner_body.w_3_gold_2_tool_dat_hoac_1_d', 'W=3, gold ≥2 tool đắt (hoặc 1 đắt + 1 rẻ), silver ≥2 rẻ, nhiễu CWE-117 — đổi tham số chỉ qua "Chế độ thí nghiệm" ở Wizard bước 3 (bắt lý do, export _exp).')));
}
