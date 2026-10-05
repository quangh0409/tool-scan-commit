// _shim.js — bản component TỐI GIẢN dùng riêng cho harness của A5.
// Chữ ký giống hệt `components` trong gui/web/app.js (A4) để merge không vỡ:
//   btn({label, kind:'primary'|'default'|'danger', onClick, disabled, small}) -> HTMLElement
//   card(children, {title})            table({columns:[{key,label,render?}], rows, page, size, total, onPage})
//   toast(msg, kind)                    dialog({title, body, confirmText, typedConfirm, onConfirm})
//   empty(msg)                          errorBox(err, onRetry)
//   skeleton(n)                         badgeLabel(label, evidence)
// Mở rộng (tuỳ chọn, A4 có thể bỏ qua): table nhận thêm {onRow, rowKey, selected, emptyMsg};
// dialog nhận thêm {cancelText, kind}; mọi hàm trả về HTMLElement.

const CSS = `
.sh-btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:44px;padding:0 18px;border-radius:8px;
  border:1px solid #C9CFD6;background:#fff;color:#1C2430;font:600 14px 'IBM Plex Sans',system-ui,sans-serif;cursor:pointer}
.sh-btn:hover{background:#F2F5F8}.sh-btn:focus-visible{outline:3px solid #1F5F8B;outline-offset:2px}
.sh-btn.primary{background:#1F5F8B;border-color:#1F5F8B;color:#fff}.sh-btn.primary:hover{background:#174868}
.sh-btn.danger{border-color:#B42318;color:#B42318}.sh-btn.danger:hover{background:#FBE0DD}
.sh-btn.small{padding:0 12px;font-size:13px}
.sh-btn[disabled]{opacity:.5;cursor:not-allowed}
.sh-card{background:#fff;border:1px solid #D9DEE4;border-radius:12px;padding:18px 22px;display:flex;flex-direction:column;gap:12px;min-width:0}
.sh-card>h3{margin:0;font-size:15px}
.sh-table-wrap{overflow-x:auto}
.sh-table{border-collapse:collapse;width:100%}
.sh-table th{text-align:left;font-size:12px;color:#5A6673;font-weight:600;padding:10px 12px;border-bottom:1px solid #D9DEE4;white-space:nowrap}
.sh-table td{padding:10px 12px;border-bottom:1px solid #EEF1F4;vertical-align:top;font-size:13.5px}
.sh-table tr.clickable{cursor:pointer}.sh-table tr.clickable:hover td{background:#F7F9FB}
.sh-table tr.sel td{background:#E8F1F8}
.sh-pager{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:8px 12px;color:#5A6673;font-size:13px;flex-wrap:wrap}
.sh-pager .pages{display:flex;gap:6px}
#sh-toast-host{position:fixed;right:20px;bottom:20px;display:flex;flex-direction:column;gap:8px;z-index:9999}
.sh-toast{background:#142233;color:#fff;padding:12px 16px;border-radius:10px;font-size:14px;max-width:420px;box-shadow:0 6px 20px rgba(0,0,0,.25)}
.sh-toast.ok{background:#1B7F4D}.sh-toast.error{background:#B42318}.sh-toast.warn{background:#7A5B00}
dialog.sh-dialog{border:0;border-radius:12px;padding:0;max-width:560px;width:calc(100% - 32px);box-shadow:0 20px 60px rgba(0,0,0,.35)}
dialog.sh-dialog::backdrop{background:rgba(20,34,51,.55)}
.sh-dialog-inner{padding:22px 24px;display:flex;flex-direction:column;gap:14px;font-family:'IBM Plex Sans',system-ui,sans-serif;color:#1C2430}
.sh-dialog-inner h2{margin:0;font-size:18px}
.sh-dialog-inner .actions{display:flex;gap:10px;justify-content:flex-end;flex-wrap:wrap}
.sh-dialog-inner input[type=text]{min-height:44px;border:1px solid #C9CFD6;border-radius:8px;padding:0 12px;font:14px 'IBM Plex Mono',monospace}
.sh-empty{padding:40px 24px;text-align:center;color:#5A6673;background:#fff;border:1px dashed #C9CFD6;border-radius:12px}
.sh-error{padding:18px 22px;background:#FBE0DD;border:1px solid #B42318;border-radius:12px;color:#7A1A12;display:flex;flex-direction:column;gap:10px}
.sh-error code{font-family:'IBM Plex Mono',monospace;font-size:12.5px}
.sh-skel{display:flex;flex-direction:column;gap:10px}
.sh-skel span{display:block;height:16px;border-radius:6px;background:linear-gradient(90deg,#E3E7EC 25%,#F2F5F8 50%,#E3E7EC 75%);background-size:200% 100%;animation:sh-shimmer 1.4s infinite}
@keyframes sh-shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}
.sh-badge{display:inline-flex;align-items:center;gap:4px;font-size:12px;font-weight:600;padding:3px 9px;border-radius:999px;white-space:nowrap}
.sh-badge.gold{background:#FBE7B2;color:#6B4E00}.sh-badge.silver{background:#E3E7EC;color:#3B4654}.sh-badge.candidate{background:#EEF1F4;color:#4A5663}
.sh-badge.verified-clean{background:#DDF3E6;color:#14603A}.sh-badge.cheap-clean{background:#EEF1F4;color:#4A5663}.sh-badge.unknown{background:#EEF1F4;color:#4A5663}
`;

let injected = false;
function injectCss() {
  if (injected || typeof document === 'undefined') return;
  injected = true;
  const s = document.createElement('style');
  s.id = 'sh-shim-css';
  s.textContent = CSS;
  document.head.appendChild(s);
}

import { h, append } from './_util.js';
export { h };

export function btn({ label, kind = 'default', onClick, disabled = false, small = false, title, ariaLabel } = {}) {
  injectCss();
  const b = h('button', {
    type: 'button',
    class: `sh-btn ${kind !== 'default' ? kind : ''} ${small ? 'small' : ''}`.trim(),
    disabled: !!disabled,
    title,
    'aria-label': ariaLabel,
  }, label);
  if (onClick) b.addEventListener('click', onClick);
  return b;
}

export function card(children, { title, extraClass } = {}) {
  injectCss();
  const c = h('section', { class: `sh-card ${extraClass || ''}`.trim() });
  if (title) c.append(h('h3', { text: title }));
  append(c, [children]);
  return c;
}

export function table({ columns, rows, page = 1, size, total, onPage, onRow, rowKey, selected, emptyMsg } = {}) {
  injectCss();
  const wrap = h('div', { class: 'sh-table-wrap' });
  const t = h('table', { class: 'sh-table' });
  t.append(h('thead', {}, h('tr', {}, columns.map((c) => h('th', { scope: 'col', text: c.label })))));
  const tb = h('tbody');
  for (const r of rows || []) {
    const key = rowKey ? rowKey(r) : undefined;
    const tr = h('tr', { class: `${onRow ? 'clickable' : ''} ${selected !== undefined && key === selected ? 'sel' : ''}`.trim() });
    if (onRow) {
      tr.tabIndex = 0;
      tr.setAttribute('role', 'button');
      tr.addEventListener('click', () => onRow(r));
      tr.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onRow(r); } });
    }
    for (const c of columns) {
      const v = c.render ? c.render(r) : r[c.key];
      const td = h('td');
      append(td, [v === undefined || v === null || v === '' ? '—' : v]);
      tr.append(td);
    }
    tb.append(tr);
  }
  t.append(tb);
  wrap.append(t);
  if (!rows || rows.length === 0) wrap.append(h('div', { class: 'sh-pager', text: emptyMsg || 'Không có dòng nào.' }));
  if (size && total !== undefined && total > size) {
    const pages = Math.max(1, Math.ceil(total / size));
    const pager = h('div', { class: 'sh-pager' },
      h('span', { text: `Hiện ${Math.min(size, rows.length)} / ${total} · trang ${page} / ${pages}` }),
      h('div', { class: 'pages' },
        btn({ label: '‹ Trước', small: true, disabled: page <= 1, onClick: () => onPage && onPage(page - 1) }),
        btn({ label: 'Sau ›', small: true, disabled: page >= pages, onClick: () => onPage && onPage(page + 1) })));
    wrap.append(pager);
  }
  return wrap;
}

export function toast(msg, kind = 'info') {
  injectCss();
  let host = document.getElementById('sh-toast-host');
  if (!host) { host = h('div', { id: 'sh-toast-host', role: 'status', 'aria-live': 'polite' }); document.body.append(host); }
  const t = h('div', { class: `sh-toast ${kind}`, text: msg });
  host.append(t);
  setTimeout(() => t.remove(), 4500);
  return t;
}

export function dialog({ title, body, confirmText = 'Xác nhận', typedConfirm, onConfirm, cancelText = 'Huỷ', kind = 'primary' } = {}) {
  injectCss();
  const dlg = h('dialog', { class: 'sh-dialog' });
  const inner = h('div', { class: 'sh-dialog-inner' }, h('h2', { text: title || '' }));
  if (body) append(inner, [typeof body === 'string' ? h('p', { text: body }) : body]);
  let input = null;
  if (typedConfirm) {
    const id = `sh-typed-${Math.random().toString(36).slice(2, 8)}`;
    inner.append(h('label', { for: id, text: `Gõ "${typedConfirm}" để xác nhận:` }));
    input = h('input', { type: 'text', id, autocomplete: 'off', 'aria-describedby': id + '-hint' });
    inner.append(input);
  }
  const ok = btn({ label: confirmText, kind, disabled: !!typedConfirm });
  const cancel = btn({ label: cancelText, onClick: () => dlg.close('cancel') });
  if (input) input.addEventListener('input', () => { ok.disabled = input.value.trim() !== typedConfirm; });
  ok.addEventListener('click', async () => {
    ok.disabled = true;
    try { await (onConfirm && onConfirm(input ? input.value : undefined)); dlg.close('ok'); } catch (e) { ok.disabled = false; toast(errMsg(e), 'error'); }
  });
  inner.append(h('div', { class: 'actions' }, cancel, ok));
  dlg.append(inner);
  dlg.addEventListener('close', () => dlg.remove());
  document.body.append(dlg);
  dlg.showModal();
  return dlg;
}

export function empty(msg) {
  injectCss();
  return h('div', { class: 'sh-empty', role: 'status', text: msg || 'Chưa có dữ liệu.' });
}

export function errMsg(err) {
  if (!err) return 'Lỗi không rõ';
  if (typeof err === 'string') return err;
  const e = err.error || err;
  return [e.code, e.message || err.message].filter(Boolean).join(' · ') || String(err);
}

export function errorBox(err, onRetry) {
  injectCss();
  const e = (err && err.error) || err || {};
  const box = h('div', { class: 'sh-error', role: 'alert' },
    h('strong', { text: 'Không tải được dữ liệu' }),
    h('div', {}, h('code', { text: errMsg(err) })),
    e.hint ? h('div', { text: e.hint }) : null);
  if (onRetry) box.append(h('div', {}, btn({ label: 'Thử lại', onClick: onRetry })));
  return box;
}

export function skeleton(n = 4) {
  injectCss();
  const s = h('div', { class: 'sh-skel', 'aria-busy': 'true', 'aria-label': 'Đang tải' });
  for (let i = 0; i < n; i++) s.append(h('span', { style: { width: `${90 - (i * 13) % 50}%` } }));
  return s;
}

/** Nhãn + mức bằng chứng. gold+unreviewed -> "gold · đồng thuận máy"; gold+TP -> "gold ✓ TP"; gold+FP -> "gold ✗ FP". */
export function badgeLabel(label, evidence) {
  injectCss();
  const lv = label || 'unknown';
  const val = (evidence && evidence.validation) || 'unreviewed';
  let text; let title;
  if (lv === 'gold' || lv === 'silver' || lv === 'candidate') {
    if (val === 'TP') { text = `${lv} ✓ TP`; title = `${lv} — kiểm tay: đúng (TP)`; }
    else if (val === 'FP') { text = `${lv} ✗ FP`; title = `${lv} — kiểm tay: sai (FP)`; }
    else if (val === 'unclear') { text = `${lv} ? chưa rõ`; title = `${lv} — kiểm tay: không rõ`; }
    else { text = `${lv} · đồng thuận máy`; title = `${lv} · đồng thuận máy (chưa kiểm tay)`; }
  } else if (lv === 'verified-clean') {
    text = 'verified-clean · 2 tool đắt không báo';
    title = 'verified-clean · 2 tool đắt không báo — không phải chứng minh sạch';
  } else if (lv === 'cheap-clean') {
    text = 'cheap-clean · chỉ tool rẻ';
    title = 'cheap-clean · chỉ tool rẻ không báo, chưa qua tầng đắt';
  } else { text = lv; title = lv; }
  return h('span', { class: `sh-badge ${lv}`, title, text });
}

export const components = { btn, card, table, toast, dialog, empty, errorBox, skeleton, badgeLabel };
export default components;
