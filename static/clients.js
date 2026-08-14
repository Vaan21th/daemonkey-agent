/*
 * clients.js · 客户档案(CRM) + 用户运营(占位) 前端 (2026-07-12 从 chat.js 拆出)
 *
 * 装载顺序 / 零构建全局约定同 depot.js(必须在 chat.js 之前)。
 * 引用的 escHtml / $dashView / mdRender / loadDashboard / renderListFilter /
 * _applyListFilter / _kbPreview / confirm 都在 chat.js·运行时解析。
 */

// ── 客户档案 · 合伙人记得每个客户 (标签页分组 + 两栏详情:需求/时间线/交付) ──
const CLIENT_STATUS_CN = { lead: '线索', active: '在合作', paused: '暂停', done: '已结束' };
const CLIENT_STATUS_ORDER = ['active', 'lead', 'paused', 'done'];
// 每个 pipeline 阶段一个 RemixIcon(全站只用内置图标·不用 emoji)
const CLIENT_STATUS_ICON = {
  lead: 'ri-seedling-line', active: 'ri-shake-hands-line',
  paused: 'ri-pause-circle-line', done: 'ri-checkbox-circle-line',
};
// 时间线条目类型 → 图标 + 标签(会议记录/交付过程都靠 kind 归类·全站只用 RemixIcon)
const CLIENT_KIND = {
  need:     { label: '需求', ic: 'ri-focus-3-line' },
  meeting:  { label: '会议', ic: 'ri-team-line' },
  progress: { label: '进展', ic: 'ri-flashlight-line' },
  deliver:  { label: '交付', ic: 'ri-send-plane-fill' },
  note:     { label: '备注', ic: 'ri-sticky-note-line' },
};
const CLIENT_KIND_FILTERS = ['all', 'meeting', 'progress', 'deliver', 'need', 'note'];

// 视图状态 · 跨 silent 刷新保留 tab/搜索/选中(改阶段/记一条后不跳回顶)
const _clState = { items: [], stats: {}, tab: 'all', q: '', sel: null, filter: 'all', detail: null };

function _clSnip(t, n) {
  t = (t || '').replace(/\s+/g, ' ').trim();
  return t.length > n ? t.slice(0, n) + '…' : t;
}

function renderClients(data) {
  if (data && data.error) {
    $dashView.innerHTML = `
      <div class="dash-head"><h2><i class="ri-contacts-book-2-fill"></i> 客户档案</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }
  _clState.items = (data && data.items) || [];
  _clState.stats = (data && data.stats) || {};
  // 选中的客户若还在 → 保留;否则清空(silent 刷新后不乱跳)
  if (_clState.sel && !_clState.items.some(c => c.id === _clState.sel)) _clState.sel = null;
  const total = _clState.items.length;
  const by = _clState.stats.by_status || {};

  const tabs = [`<div class="stage-tab all${_clState.tab === 'all' ? ' active' : ''}" data-s="all">全部 <span class="n">${total}</span></div>`]
    .concat(CLIENT_STATUS_ORDER.filter(s => by[s]).map(s =>
      `<div class="stage-tab ${s}${_clState.tab === s ? ' active' : ''}" data-s="${s}"><i class="${CLIENT_STATUS_ICON[s]}"></i> ${CLIENT_STATUS_CN[s]} <span class="n">${by[s]}</span></div>`)).join('');

  $dashView.innerHTML = `
    <div class="dash-head">
      <h2><i class="ri-contacts-book-2-fill"></i> 客户档案</h2>
      <span class="meta">${total} 个</span>
      <span class="dash-sp"></span>
      <button class="primary" onclick="_clientImportPick()"><i class="ri-file-excel-2-line"></i> 导入 Excel/CSV</button>
      <button onclick="loadDashboard('clients')"><i class="ri-refresh-line"></i> 刷新</button>
      <button onclick="backToChat()"><i class="ri-close-line"></i> 收起</button>
    </div>` + (total === 0 ? `
    <div class="dash-stub">
      <h3>还没有客户档案</h3>
      <div>跟 Daemonkey 说「新客户 张三，星途科技 CTO，微信 zs123，想做数字人」建第一个 ·<br>
           之后每次沟通/会议/交付说「给张三记一条会议记录：…」· 它会自动归类进时间线。<br>
           或点右上角 <b>导入 Excel/CSV</b> 把现成名单灌进来。</div>
    </div>` : `
    <input class="cl-search" id="clSearch" placeholder="搜客户名 / 公司 / 标签 / 需求 / 动态关键词…" value="${escHtml(_clState.q)}">
    <div class="stage-tabs">${tabs}</div>
    <div class="cl-wrap"><div class="cl-list" id="clList"></div><div class="cl-detail" id="clDetail"></div></div>`);

  if (total === 0) return;
  $dashView.querySelectorAll('.stage-tab').forEach(el => el.onclick = () => {
    _clState.tab = el.getAttribute('data-s');
    _clRenderList();
  });
  const $s = document.getElementById('clSearch');
  if ($s) $s.oninput = () => { _clState.q = $s.value.trim(); _clRenderList(); };
  _clRenderList();
}

// 跨客户检索(第二大脑·跨客户面板)+ 阶段过滤 · 名字/公司/角色/需求/标签/时间线全文命中
function _clFilteredItems() {
  const q = (_clState.q || '').toLowerCase();
  return _clState.items.filter(c => {
    if (_clState.tab !== 'all' && (c.status || 'lead') !== _clState.tab) return false;
    if (!q) return true;
    const blob = [c.name, c.company, c.role, c.need, (c.tags || []).join(' ')]
      .concat((c.log || []).map(e => e.text)).filter(Boolean).join('\n').toLowerCase();
    return blob.includes(q);
  });
}

function _clRenderList() {
  const $list = document.getElementById('clList');
  if (!$list) return;
  const arr = _clFilteredItems();
  if (arr.length && (!_clState.sel || !arr.some(c => c.id === _clState.sel))) _clState.sel = arr[0].id;
  $list.innerHTML = arr.map(c => {
    const st = c.status || 'lead';
    const log = c.log || [];
    const latest = log.length ? log[log.length - 1] : null;
    const k = latest ? (CLIENT_KIND[latest.kind] || CLIENT_KIND.note) : null;
    const latestHtml = latest
      ? `<div class="cc-latest"><i class="${k.ic}"></i><span><span class="d">${escHtml(latest.date || '')}</span> ${escHtml(_clSnip(latest.text, 44))}</span></div>`
      : '';
    const tags = (c.tags || []).slice(0, 4).map(t => `<span class="cl-tag">#${escHtml(t)}</span>`).join('');
    return `
      <div class="ccard st-${st}${c.id === _clState.sel ? ' sel' : ''}" data-id="${escHtml(c.id)}">
        <div class="cc-r1"><span class="cc-name"><i class="ri-user-heart-line"></i>${escHtml(c.name || '?')}</span>${c.company ? `<span class="cc-co">${escHtml(c.company)}</span>` : ''}</div>
        <div class="cc-r2">${c.role ? `<span><i class="ri-briefcase-line"></i> ${escHtml(c.role)}</span>` : ''}${c.contact ? `<span><i class="ri-phone-line"></i> ${escHtml(c.contact)}</span>` : ''}</div>
        ${latestHtml}
        <div class="cc-r3">${tags}<span class="cc-mini"><i class="ri-chat-history-line"></i> ${log.length} 条</span></div>
      </div>`;
  }).join('') || '<div class="cl-empty">这个阶段没有客户</div>';
  $list.querySelectorAll('.ccard').forEach(el => el.onclick = () => _clSelect(el.getAttribute('data-id')));
  _clRenderDetail();
}

// 选中一个客户 → 先用列表数据渲染(秒开)· 再拉详情补上名下资料(docs)
async function _clSelect(cid) {
  _clState.sel = cid;
  _clState.filter = 'all';
  const $list = document.getElementById('clList');
  if ($list) $list.querySelectorAll('.ccard').forEach(el => el.classList.toggle('sel', el.getAttribute('data-id') === cid));
  if (!(_clState.detail && _clState.detail.client && _clState.detail.client.id === cid)) _clState.detail = null;
  _clRenderDetail();
  if (!token) return;
  try {
    const r = await fetch('/dashboard/clients/detail?client_id=' + encodeURIComponent(cid), {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (r.ok) { _clState.detail = await r.json(); if (_clState.sel === cid) _clRenderDetail(); }
  } catch (e) { /* 详情拉不到就用列表数据顶着 */ }
}

function _clRenderDetail() {
  const $d = document.getElementById('clDetail');
  if (!$d) return;
  const cid = _clState.sel;
  if (!cid) { $d.innerHTML = '<div class="cl-detail-empty"><i class="ri-arrow-left-line"></i> 选左边一个客户看档案</div>'; return; }
  const item = _clState.items.find(c => c.id === cid) || {};
  const det = (_clState.detail && _clState.detail.client && _clState.detail.client.id === cid) ? _clState.detail : null;
  const c = det ? det.client : item;
  const docs = det ? (det.docs || []) : null;  // null = 名下资料加载中
  const st = c.status || 'lead';

  const stOpts = CLIENT_STATUS_ORDER.map(s =>
    `<option value="${s}"${s === st ? ' selected' : ''}>${CLIENT_STATUS_CN[s]}</option>`).join('');
  const sub = [
    c.company ? `<span><i class="ri-building-line"></i> ${escHtml(c.company)}</span>` : '',
    c.role ? `<span><i class="ri-briefcase-line"></i> ${escHtml(c.role)}</span>` : '',
    c.contact ? `<span><i class="ri-phone-line"></i> ${escHtml(c.contact)}</span>` : '',
  ].filter(Boolean).join('');
  const tags = (c.tags || []).map(t => `<span class="cl-tag">#${escHtml(t)}</span>`).join('');

  const since = (c.created_at || '').slice(0, 10);
  const pills = [
    c.intent ? `<div class="cl-pill"><div class="k"><i class="ri-fire-line"></i> 意向</div><div class="v hl">${escHtml(c.intent)}</div></div>` : '',
    c.quote ? `<div class="cl-pill"><div class="k"><i class="ri-money-cny-circle-line"></i> 报价</div><div class="v">${escHtml(c.quote)}</div></div>` : '',
    c.next ? `<div class="cl-pill"><div class="k"><i class="ri-calendar-todo-line"></i> 下一步</div><div class="v">${escHtml(c.next)}</div></div>` : '',
    since ? `<div class="cl-pill"><div class="k"><i class="ri-flag-line"></i> 起始</div><div class="v">${escHtml(since)}</div></div>` : '',
  ].filter(Boolean).join('');

  const needHtml = (c.need || '').trim()
    ? `<div class="cl-need">${escHtml(c.need)}</div>`
    : `<div class="cl-need cl-need-empty">还没记需求 · 跟 Daemonkey 说「${escHtml(c.name || '这个客户')}的需求是…」就补上了</div>`;

  const log = (c.log || []).slice().reverse();  // 新 → 旧
  const chips = CLIENT_KIND_FILTERS.map(kf => {
    const lbl = kf === 'all' ? '全部' : CLIENT_KIND[kf].label;
    return `<span class="cl-chip${_clState.filter === kf ? ' on' : ''}" data-k="${kf}">${lbl}</span>`;
  }).join('');
  const shown = log.filter(e => _clState.filter === 'all' || (e.kind || 'note') === _clState.filter);
  const tlHtml = shown.map((e, i) => {
    const k = CLIENT_KIND[e.kind] || CLIENT_KIND.note;
    const txt = e.text || '';
    const isLong = txt.length > 110 || txt.includes('\n');
    const head = isLong ? escHtml(_clSnip(txt.split('\n')[0], 90)) : escHtml(txt);
    const more = isLong
      ? `<span class="cl-tl-more" data-i="${i}"><i class="ri-arrow-down-s-line"></i> 展开全文</span><div class="cl-tl-full" id="clFull${i}">${escHtml(txt)}</div>`
      : '';
    return `
      <div class="cl-tl-item">
        <div class="cl-tl-d">${escHtml(e.date || '')}</div>
        <div class="cl-tl-ic k-${e.kind || 'note'}"><i class="${k.ic}"></i></div>
        <div class="cl-tl-body"><div class="cl-tl-txt"><span class="cl-tl-kind k-${e.kind || 'note'}">${k.label}</span>${head}</div>${more}</div>
      </div>`;
  }).join('') || '<div class="cl-empty">这个类别下暂无记录</div>';

  let dlHtml;
  if (docs === null) {
    dlHtml = '<div class="cl-empty">加载名下资料…</div>';
  } else if (docs.length) {
    dlHtml = `<div class="cl-dl-grid">` + docs.map(d => {
      const isReport = /report|报告/i.test(d.doc_type || d.kind || d.source || '');
      const meta = escHtml((d.doc_type || d.kind || '资料') + (d.created_at ? ' · ' + String(d.created_at).slice(0, 10) : ''));
      return `<div class="cl-dl-card cl-open-doc" data-id="${escHtml(d.id)}">
        <div class="cl-dl-ic"><i class="${isReport ? 'ri-file-chart-line' : 'ri-file-text-line'}"></i></div>
        <div class="cl-dl-info"><div class="t">${escHtml(d.title || d.id)}</div><div class="m">${meta}</div></div>
      </div>`;
    }).join('') + `</div>`;
  } else {
    dlHtml = `<div class="cl-empty">还没有挂交付物 · 生成报告或灌资料时跟 Daemonkey 说「挂到${escHtml(c.name || '')}名下」</div>`;
  }

  $d.innerHTML = `
    <div class="cl-d-head">
      <div class="cl-d-title">
        <span class="cl-d-name">${escHtml(c.name || '客户')}</span>
        <span class="cl-badge ${st}">${CLIENT_STATUS_CN[st] || ''}</span>
        <span class="cl-d-sp"></span>
        <select class="cl-d-status" title="改 pipeline 阶段">${stOpts}</select>
        <button class="cl-d-del" title="删除档案"><i class="ri-delete-bin-line"></i></button>
      </div>
      ${sub ? `<div class="cl-d-sub">${sub}</div>` : ''}
      ${tags ? `<div class="cl-d-tags">${tags}</div>` : ''}
    </div>
    ${pills ? `<div class="cl-pills">${pills}</div>` : ''}
    <div class="cl-sec">
      <div class="cl-sec-t"><i class="ri-focus-3-line"></i> 客户需求</div>
      ${needHtml}
    </div>
    <div class="cl-sec">
      <div class="cl-sec-t"><i class="ri-history-line"></i> 跟进时间线 <span class="hint">会议 / 进展 / 交付都在这·新在前</span></div>
      <div class="cl-chips">${chips}</div>
      <div class="cl-tl">${tlHtml}</div>
      <div class="cl-note-add">
        <button class="cl-note-toggle"><i class="ri-add-line"></i> 记一条</button>
        <div class="cl-note-form" hidden>
          <select class="cl-note-kind">
            <option value="meeting">会议记录</option>
            <option value="progress">进展</option>
            <option value="deliver">交付</option>
            <option value="need">需求</option>
            <option value="note" selected>备注</option>
          </select>
          <textarea class="cl-note-text" rows="2" placeholder="记点什么(会议纪要 / 进展 / 交付…)· 也能直接在对话里跟 Daemonkey 说"></textarea>
          <div class="cl-note-foot"><button class="cl-note-save"><i class="ri-check-line"></i> 存进时间线</button></div>
        </div>
        <div class="cl-note-hint"><i class="ri-mic-line"></i> 也可对话记录:「给${escHtml(c.name || '')}记一条会议记录:…」/「${escHtml(c.name || '')}这单交付了」——Daemonkey 自动归类。会议纪要模式整理出的纪要也能一键存这里。</div>
      </div>
    </div>
    <div class="cl-sec">
      <div class="cl-sec-t"><i class="ri-folder-3-line"></i> 交付与过程 <span class="hint">为这个客户产出的报告 / 资料</span></div>
      ${dlHtml}
    </div>`;

  const stSel = $d.querySelector('.cl-d-status');
  if (stSel) stSel.onchange = () => _clMutate('/dashboard/clients/status', { client_id: cid, status: stSel.value });
  const del = $d.querySelector('.cl-d-del');
  if (del) del.onclick = () => {
    if (confirm(`删除「${c.name || '这个客户'}」的档案？(挂在他名下的知识库文档不会被删)`)) {
      _clMutate('/dashboard/clients/delete', { client_id: cid }, { clearSel: true });
    }
  };
  $d.querySelectorAll('.cl-chip').forEach(el => el.onclick = () => { _clState.filter = el.getAttribute('data-k'); _clRenderDetail(); });
  $d.querySelectorAll('.cl-tl-more').forEach(el => el.onclick = () => {
    const f = document.getElementById('clFull' + el.getAttribute('data-i'));
    if (f) f.classList.toggle('open');
  });
  $d.querySelectorAll('.cl-open-doc').forEach(el => el.onclick = () => {
    if (typeof _kbPreview === 'function') _kbPreview(el.getAttribute('data-id'));
  });
  const tog = $d.querySelector('.cl-note-toggle');
  const form = $d.querySelector('.cl-note-form');
  if (tog && form) tog.onclick = () => { form.hidden = !form.hidden; if (!form.hidden) $d.querySelector('.cl-note-text').focus(); };
  const save = $d.querySelector('.cl-note-save');
  if (save) save.onclick = () => {
    const text = ($d.querySelector('.cl-note-text').value || '').trim();
    if (!text) { alert('写点内容再存'); return; }
    const kind = $d.querySelector('.cl-note-kind').value || 'note';
    save.disabled = true;
    _clMutate('/dashboard/clients/note', { client_id: cid, text, kind });
  };
}

// 统一的写操作 · 成功后刷新列表(保留 tab/搜索)并重拉当前详情
async function _clMutate(url, body, opts) {
  if (!token) return;
  try {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      let m = '操作失败 [' + r.status + ']';
      try { const j = await r.json(); if (j.detail) m = j.detail; } catch (_) {}
      alert(m);
      return;
    }
    if (opts && opts.clearSel) _clState.sel = null;
    _clState.detail = null;
    const lr = await fetch('/dashboard/clients', { headers: { 'Authorization': 'Bearer ' + token } });
    if (lr.ok) {
      renderClients(await lr.json());
      if (_clState.sel) _clSelect(_clState.sel);
    }
  } catch (e) { alert('网络出错: ' + e.message); }
}

// 客户选择器 · 给「会议纪要一键存成客户会议记录」等场景复用(chat.js 调) · onPick(id, name)
async function pickClient(onPick) {
  if (!token) { alert('未登录'); return; }
  let items = [];
  try {
    const r = await fetch('/dashboard/clients', { headers: { 'Authorization': 'Bearer ' + token } });
    if (r.ok) items = (await r.json()).items || [];
  } catch (e) { /* 拉不到就给空列表提示 */ }
  if (typeof _closeAllKbModals === 'function') _closeAllKbModals();  // 2026-08-14 · 单例互斥 (墨言094-2)
  let host = document.getElementById('kbModalHost');
  if (!host) { host = document.createElement('div'); host.id = 'kbModalHost'; host.className = 'kb-modal-host'; document.body.appendChild(host); }
  const list = items.length
    ? items.map(c => `<div class="cl-pick-item" data-id="${escHtml(c.id)}" data-name="${escHtml(c.name || '')}"><i class="ri-user-heart-line"></i> <span class="cl-pick-n">${escHtml(c.name || '?')}</span>${c.company ? ` <span class="cl-pick-co">${escHtml(c.company)}</span>` : ''}<span class="cl-pick-badge cl-badge ${c.status || 'lead'}">${CLIENT_STATUS_CN[c.status] || ''}</span></div>`).join('')
    : '<div class="cl-empty">还没有客户档案 · 先建一个客户再来存</div>';
  host.innerHTML = `
    <div class="kb-modal-mask"></div>
    <div class="kb-modal cl-pick-modal" role="dialog" aria-modal="true">
      <div class="kb-modal-head"><span class="kb-modal-title"><i class="ri-contacts-book-2-line"></i> 存到哪个客户</span><button class="kb-modal-close" title="关闭 (Esc)">✕</button></div>
      <input class="cl-search" id="clPickSearch" placeholder="搜客户名 / 公司…">
      <div class="kb-modal-body cl-pick-list">${list}</div>
    </div>`;
  host.classList.add('show');
  const close = () => { host.classList.remove('show'); document.removeEventListener('keydown', onKey); };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  document.addEventListener('keydown', onKey);
  host.querySelector('.kb-modal-close').onclick = close;
  host.querySelector('.kb-modal-mask').onclick = close;
  const $ps = host.querySelector('#clPickSearch');
  if ($ps) $ps.oninput = () => {
    const q = $ps.value.trim().toLowerCase();
    host.querySelectorAll('.cl-pick-item').forEach(el => {
      const t = ((el.getAttribute('data-name') || '') + ' ' + (el.textContent || '')).toLowerCase();
      el.style.display = (!q || t.includes(q)) ? '' : 'none';
    });
  };
  host.querySelectorAll('.cl-pick-item').forEach(el => el.onclick = () => {
    const id = el.getAttribute('data-id'), name = el.getAttribute('data-name');
    close();
    if (typeof onPick === 'function') onPick(id, name);
  });
}


// ── B-P0 · Excel/CSV 批量导入 (合伙人接手现成客户名单) ────────────
//   两步: 选文件 → 上传拆表(import-preview) → 映射弹窗确认 → 批量建档(import)。
//   建档只新增·默认按客户名去重·不覆盖已有档案。
const _CL_IMPORT_FIELDS = [
  { k: 'name', label: '客户名', required: true },
  { k: 'company', label: '公司' },
  { k: 'role', label: '角色 / 职位' },
  { k: 'contact', label: '联系方式' },
  { k: 'status', label: 'pipeline 阶段' },
  { k: 'tags', label: '标签' },
  { k: 'notes', label: '备注 / 需求' },
];
let _clImportData = null;

function _clientImportPick() {
  let input = document.getElementById('clImportFile');
  if (!input) {
    input = document.createElement('input');
    input.type = 'file';
    input.id = 'clImportFile';
    input.accept = '.csv,.tsv,.txt,.xlsx,.xlsm';
    input.style.display = 'none';
    document.body.appendChild(input);
    input.addEventListener('change', _clientImportUpload);
  }
  input.value = '';
  input.click();
}

async function _clientImportUpload(e) {
  const file = e.target.files && e.target.files[0];
  if (!file || !token) return;
  const fd = new FormData();
  fd.append('file', file);
  try {
    // 不手动设 Content-Type · 让浏览器带 multipart boundary
    const r = await fetch('/dashboard/clients/import-preview', {
      method: 'POST', headers: { 'Authorization': 'Bearer ' + token }, body: fd,
    });
    if (!r.ok) {
      let msg = '解析失败 [' + r.status + ']';
      try { const j = await r.json(); if (j.detail) msg = j.detail; } catch (_) {}
      alert(msg); return;
    }
    _showClientImportModal(await r.json());
  } catch (err) { alert('上传出错: ' + err.message); }
}

function _showClientImportModal(data) {
  _clImportData = data;
  if (typeof _closeAllKbModals === 'function') _closeAllKbModals();  // 2026-08-14 · 单例互斥 (墨言094-2)
  const headers = data.headers || [];
  const rows = data.rows || [];
  const sugg = data.suggested_mapping || {};
  let host = document.getElementById('kbModalHost');
  if (!host) { host = document.createElement('div'); host.id = 'kbModalHost'; host.className = 'kb-modal-host'; document.body.appendChild(host); }

  const colOpts = (selIdx) => ['<option value="-1">（不导入）</option>'].concat(
    headers.map((h, i) => `<option value="${i}"${i === selIdx ? ' selected' : ''}>${escHtml(h || ('第 ' + (i + 1) + ' 列'))}</option>`)
  ).join('');
  const mapRows = _CL_IMPORT_FIELDS.map(f => {
    const sel = (sugg[f.k] !== undefined && sugg[f.k] !== null) ? sugg[f.k] : -1;
    return `<div class="cl-map-row">
      <label class="cl-map-label">${f.label}${f.required ? ' <span class="cl-req">*</span>' : ''}</label>
      <select class="cl-map-sel" data-field="${f.k}">${colOpts(sel)}</select>
    </div>`;
  }).join('');

  const sample = rows.slice(0, 5);
  const thead = '<tr>' + headers.map(h => `<th>${escHtml(h || '')}</th>`).join('') + '</tr>';
  const tbody = sample.map(r => '<tr>' + headers.map((_, i) => `<td>${escHtml(String((r && r[i] != null) ? r[i] : ''))}</td>`).join('') + '</tr>').join('');
  const trunc = data.truncated ? `<div class="cl-import-warn"><i class="ri-error-warning-line"></i> 表太大 · 只取了前 ${rows.length} 行</div>` : '';

  host.innerHTML = `
    <div class="kb-modal-mask"></div>
    <div class="kb-modal cl-import-modal" role="dialog" aria-modal="true">
      <div class="kb-modal-head">
        <span class="kb-modal-title"><i class="ri-file-excel-2-line"></i> 导入客户名单</span>
        <span class="kb-modal-meta">${escHtml(data.filename || '')}${data.filename ? ' · ' : ''}${rows.length} 行</span>
        <button class="kb-modal-close" title="关闭 (Esc)">✕</button>
      </div>
      <div class="kb-modal-body">
        ${trunc}
        <div class="cl-import-hint">把表格的列对到档案字段(带 <span class="cl-req">*</span> 的必填)· 选「不导入」跳过该列:</div>
        <div class="cl-map-grid">${mapRows}</div>
        <label class="cl-import-dedupe"><input type="checkbox" id="clImportDedupe" checked> 按客户名去重(跳过已存在的·只新增不覆盖)</label>
        <div class="cl-import-sample-title">预览前 ${sample.length} 行</div>
        <div class="cl-import-sample"><table><thead>${thead}</thead><tbody>${tbody}</tbody></table></div>
      </div>
      <div class="cl-import-foot">
        <button class="cl-import-cancel">取消</button>
        <button class="cl-import-go"><i class="ri-check-line"></i> 导入 ${rows.length} 行</button>
      </div>
    </div>`;
  host.classList.add('show');
  const close = () => { host.classList.remove('show'); document.removeEventListener('keydown', onKey); };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  document.addEventListener('keydown', onKey);
  host.querySelector('.kb-modal-close').onclick = close;
  host.querySelector('.kb-modal-mask').onclick = close;
  host.querySelector('.cl-import-cancel').onclick = close;
  host.querySelector('.cl-import-go').onclick = () => _clientImportRun(close);
}

async function _clientImportRun(close) {
  if (!_clImportData || !token) return;
  const mapping = {};
  document.querySelectorAll('.cl-map-sel').forEach(sel => {
    const v = parseInt(sel.value, 10);
    if (v >= 0) mapping[sel.getAttribute('data-field')] = v;
  });
  if (mapping.name === undefined) { alert('请先指定「客户名」对应哪一列'); return; }
  const dedupeEl = document.getElementById('clImportDedupe');
  const dedupe = dedupeEl ? dedupeEl.checked : true;
  const btn = document.querySelector('.cl-import-go');
  if (btn) { btn.disabled = true; btn.innerHTML = '<i class="ri-loader-4-line"></i> 导入中…'; }
  try {
    const r = await fetch('/dashboard/clients/import', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ rows: _clImportData.rows || [], mapping, dedupe }),
    });
    if (!r.ok) {
      let msg = '导入失败 [' + r.status + ']';
      try { const j = await r.json(); if (j.detail) msg = j.detail; } catch (_) {}
      alert(msg);
      if (btn) { btn.disabled = false; btn.innerHTML = '<i class="ri-check-line"></i> 重试'; }
      return;
    }
    const res = await r.json();
    if (typeof close === 'function') close();
    let m = `导入完成 · 新增 ${res.created} · 跳过 ${res.skipped}`;
    if (res.errors && res.errors.length) m += `\n有 ${res.errors.length} 行出错:\n` + res.errors.slice(0, 5).join('\n');
    alert(m);
    loadDashboard('clients', { silent: true });
  } catch (err) {
    alert('网络出错: ' + err.message);
    if (btn) { btn.disabled = false; btn.innerHTML = '<i class="ri-check-line"></i> 重试'; }
  }
}


// ── 用户运营 (占位符 · 未来维度) ──────────────────────────────
// 规划:跟客户档案配套的"运营侧" —— 触达节律 / 跟进提醒 / 转化漏斗。
// 目前仅占位 · 待 NLP 工具 + 后端 worker 落地后再接 loadDashboard 分发 + 导航项。
// function renderOps(data) { /* TODO */ }
