/* 陪伴房间 · 话题架
   右边是档案: 话题列表 → 这本的产物 → 回看整栏日记。不弹框盖住人。 */
'use strict';

const _ART_CATS = [
  { key: 'office', label: '办公文档', icon: 'ri-briefcase-4-line', exts: ['docx', 'doc', 'xlsx', 'xls', 'pptx', 'ppt'] },
  { key: 'text', label: '文本 · 报告', icon: 'ri-file-text-line', exts: ['md', 'pdf', 'txt', 'html', 'htm'] },
  { key: 'image', label: '图片', icon: 'ri-image-line', exts: ['png', 'jpg', 'jpeg', 'gif', 'webp'] },
  { key: 'audio', label: '音频', icon: 'ri-music-2-line', exts: ['mp3', 'wav'] },
  { key: 'video', label: '视频', icon: 'ri-movie-line', exts: ['mp4', 'webm'] },
  { key: 'other', label: '其他', icon: 'ri-file-3-line', exts: [] },
];
const _artCache = {};

function _artExt(a) {
  if (a && a.ext) return String(a.ext).toLowerCase();
  const n = String((a && (a.name || a.url)) || '').toLowerCase();
  const m = n.match(/\.([a-z0-9]+)$/);
  return (m && m[1]) || '';
}
function _artCat(a) {
  const ext = _artExt(a);
  for (const c of _ART_CATS) if (c.exts.includes(ext)) return c;
  return _ART_CATS[_ART_CATS.length - 1];
}
function _artName(a) { return a.name || a.filename || a.title || '产物'; }
function _artDecode(s) {
  try { return decodeURIComponent(s); } catch (e) { return s; }
}
function _artToken() { return (typeof token === 'string' && token) ? token : ''; }
function _artTokQ() {
  const t = _artToken();
  return t ? ('?token=' + encodeURIComponent(t)) : '';
}
function _artJs(s) {
  return String(s || '')
    .replace(/\\/g, '\\\\')
    .replace(/'/g, "\\'")
    .replace(/"/g, '\\"')
    .replace(/\r?\n/g, '\\n');
}
function _artParts(a) {
  const url = String((a && a.url) || '#');
  const ext = _artExt(a);
  if (url.startsWith('/workshop/outputs/')) {
    return { domain: 'outputs', filename: _artDecode(url.slice('/workshop/outputs/'.length)), ext, url };
  }
  if (url.startsWith('/reports/')) {
    return { domain: 'reports', filename: _artDecode(url.slice('/reports/'.length).split('?')[0]), ext, url };
  }
  const m = url.match(/^\/(?:workshop\/(?:preview|file)\/)?([^/]+)\/([^/?]+)/);
  if (m) return { domain: m[1], filename: _artDecode(m[2]), ext, url };
  return { domain: '', filename: _artName(a), ext, url };
}
function _artFileUrl(p) {
  const t = _artTokQ();
  if (p.domain === 'outputs') return '/workshop/outputs/' + encodeURIComponent(p.filename) + t;
  if (p.domain === 'reports') return '/reports/' + encodeURIComponent(p.filename) + t;
  if (p.domain) return '/workshop/file/' + encodeURIComponent(p.domain) + '/' + encodeURIComponent(p.filename) + t;
  return p.url;
}
const _ART_PREVIEW = ['md', 'txt', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'mp3', 'wav', 'mp4', 'webm', 'pdf', 'html', 'htm'];
function _whenOf(s) {
  const raw = String(s.mtime || s.updated_at || '').replace('T', ' ');
  return raw.slice(5, 16) || '以前';
}

let _reading = false;
let _journalSid = '';
let _rows = [];

function _rail() { return document.getElementById('chat'); }
function _stack() { return document.getElementById('topic-stack'); }

const DRAFT_SID = '__draft__';
let _draft = false;
function _isDraft(sid) { return sid === DRAFT_SID; }
function _isCurrent(sid) {
  const cur = (typeof getSid === 'function') ? getSid() : null;
  if (_isDraft(sid)) return _draft && !cur;
  return !!cur && sid === cur;
}
function _stamp(sid, s) {
  if (_isDraft(sid)) return { cls: 'talk', label: '等你开口', running: false };
  const cur = (typeof getSid === 'function') ? getSid() : null;
  const pending = !!(window.SessionRuntime && SessionRuntime.isPending(sid));
  const busy = !!(s && s.active) || pending;
  if (sid && sid === cur) return { cls: 'talk', label: '正在说', running: false };
  if (busy) return { cls: 'run', label: '执行中', running: true };
  return { cls: '', label: '', running: false };
}
function _stampHtml(st) {
  if (!st || !st.label) return '';
  const dot = st.running ? '<span class="topic-run-dot"></span>' : '';
  return '<span class="stamp ' + st.cls + '">' + dot + st.label + '</span>';
}

function _artsHtml(arts, sid) {
  if (!arts || !arts.length) return '<div class="art-empty">还没生出东西</div>';
  const groups = {};
  for (const a of arts) {
    const c = _artCat(a);
    (groups[c.key] || (groups[c.key] = [])).push(a);
  }
  return '<div class="art-chips">' + _ART_CATS.map(c => {
    const n = (groups[c.key] || []).length;
    if (!n) return '';
    return `<button type="button" class="art-chip" data-sid="${esc(sid)}" data-cat="${c.key}" title="${esc(c.label)}">
      <i class="${c.icon}"></i><em>${n}</em>
    </button>`;
  }).join('') + '</div>';
}

function closeArtPop() {
  const pop = document.getElementById('art-pop');
  if (!pop || pop.hidden) return false;
  pop.hidden = true;
  return true;
}

function openArtPop(sid, catKey) {
  const pop = document.getElementById('art-pop');
  const title = document.getElementById('art-pop-title');
  const list = document.getElementById('art-pop-list');
  if (!pop || !list) return;
  const cat = _ART_CATS.find(c => c.key === catKey) || _ART_CATS[_ART_CATS.length - 1];
  const items = (_artCache[sid] || []).filter(a => _artCat(a).key === catKey);
  if (title) title.textContent = cat.label + ' · ' + items.length;
  list.innerHTML = items.length
    ? items.map(a => {
        const p = _artParts(a);
        const canSee = _ART_PREVIEW.includes(p.ext);
        const canOpen = !!p.domain;
        const btn = (ic, label, fn) =>
          `<button type="button" class="art-act" onclick="event.stopPropagation();${fn}('${_artJs(p.domain)}','${_artJs(p.filename)}','${_artJs(p.ext)}')" title="${esc(label)}"><i class="${ic}"></i><span>${esc(label)}</span></button>`;
        return `<div class="art-item">
          <i class="${_artCat(a).icon}"></i>
          <div class="art-item-body">
            <span class="art-item-name">${esc(_artName(a))}</span>
            <span class="art-item-meta">${esc(String(p.ext).toUpperCase() || 'FILE')}</span>
          </div>
          <div class="art-item-acts">
            ${canSee ? btn('ri-eye-line', '预览', '_docOpenInBrowser') : ''}
            ${canOpen ? btn('ri-mac-line', '应用打开', '_docOpenLocal') : ''}
            ${btn('ri-save-3-line', '另存为', '_docSaveAs')}
          </div>
        </div>`;
      }).join('')
    : '<div class="art-empty">这一类还没有</div>';
  pop.hidden = false;
}

async function _docOpenInBrowser(domain, filename, ext) {
  try {
    const p = { domain: domain || '', filename: filename || '', ext: String(ext || '').toLowerCase(), url: '' };
    const disp = _artDecode((p.filename.split('/').pop() || p.filename));
    const show = (typeof _showPreviewModal === 'function') ? _showPreviewModal : null;
    if (!show) { window.open(_artFileUrl(p), '_blank'); return; }
    const hx = (typeof escHtml === 'function') ? escHtml : esc;
    if (['md', 'txt'].includes(p.ext)) {
      const previewUrl = p.domain === 'outputs'
        ? _artFileUrl(p)
        : (p.domain === 'reports'
          ? '/reports/preview/' + encodeURIComponent(p.filename) + _artTokQ()
          : '/workshop/preview/' + encodeURIComponent(p.domain) + '/' + encodeURIComponent(p.filename) + _artTokQ());
      const r = await fetch(previewUrl, { headers: { Authorization: 'Bearer ' + _artToken() } });
      if (!r.ok) throw new Error('预览拉取失败 ' + r.status);
      const ct = r.headers.get('content-type') || '';
      let text = '';
      if (ct.includes('json')) {
        const data = await r.json();
        text = data.markdown || data.text || '';
      } else {
        text = await r.text();
      }
      const bodyHtml = (typeof mdRender === 'function')
        ? mdRender(text)
        : ('<pre style="white-space:pre-wrap">' + hx(text) + '</pre>');
      show({ title: disp, metaLine: p.ext.toUpperCase(), bodyHtml });
      return;
    }
    const url = _artFileUrl(p);
    if (['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(p.ext)) {
      show({ title: disp, metaLine: '图片', raw: true, bodyHtml: `<img src="${url}" alt="${hx(disp)}" class="pv-img">` });
    } else if (['mp3', 'wav'].includes(p.ext)) {
      show({ title: disp, metaLine: '音频', raw: true, bodyHtml: `<audio controls preload="metadata" src="${url}" class="pv-media" style="width:100%"></audio>` });
    } else if (['mp4', 'webm'].includes(p.ext)) {
      show({ title: disp, metaLine: '视频', raw: true, bodyHtml: `<video controls preload="metadata" src="${url}" class="pv-media"></video>` });
    } else if (p.ext === 'pdf') {
      show({ title: disp, metaLine: 'PDF', raw: true, bodyHtml: `<iframe src="${url}" class="pv-pdf"></iframe>` });
    } else if (p.ext === 'html' || p.ext === 'htm') {
      show({ title: disp, metaLine: 'HTML', raw: true, bodyHtml: `<iframe src="${url}" class="pv-html" sandbox="allow-same-origin" loading="lazy"></iframe>` });
    } else {
      await _docSaveAs(domain, filename);
    }
  } catch (e) {
    alert('打开失败: ' + e.message);
  }
}

async function _docSaveAs(domain, filename) {
  try {
    const p = { domain: domain || '', filename: filename || '', ext: '', url: '' };
    const url = _artFileUrl(p);
    const r = await fetch(url, { headers: { Authorization: 'Bearer ' + _artToken() } });
    if (!r.ok) throw new Error('获取失败 ' + r.status);
    const blob = await r.blob();
    const name = (filename || 'file').split('/').pop() || filename;
    if (window.showSaveFilePicker) {
      try {
        const handle = await window.showSaveFilePicker({
          suggestedName: name,
          types: [{ description: '文件', accept: { 'application/octet-stream': ['.' + (name.split('.').pop() || '')] } }],
        });
        const writable = await handle.createWritable();
        await writable.write(blob);
        await writable.close();
        return;
      } catch (e) {
        if (e && e.name === 'AbortError') return;
      }
    }
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  } catch (e) {
    alert('另存为失败: ' + e.message);
  }
}

async function _docOpenLocal(domain, filename) {
  try {
    if (!domain || !filename) throw new Error('这条产物找不到本机路径');
    const r = await fetch('/workshop/reveal/' + encodeURIComponent(domain) + '/' + encodeURIComponent(filename) + _artTokQ(), {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + _artToken() },
    });
    const data = await r.json();
    if (!data.ok) throw new Error(data.error || '本机打开失败');
  } catch (e) {
    alert('本机打开失败: ' + e.message + ' · 仅本机可用');
  }
}

async function _fetchArts(sid) {
  if (!sid) return [];
  try {
    const data = await (await fetch('/sessions/' + encodeURIComponent(sid) + '/artifacts')).json();
    const arts = Array.isArray(data) ? data : (data.artifacts || []);
    _artCache[sid] = arts;
    return arts;
  } catch (e) { return []; }
}

function _bindArtChips(root) {
  if (!root) return;
  root.querySelectorAll('.art-chip').forEach(btn => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', e => {
      e.stopPropagation();
      openArtPop(btn.dataset.sid, btn.dataset.cat);
    });
  });
}
function _bindShelf(stack) {
  stack.querySelectorAll('.tcard').forEach(el => {
    if (el.dataset.bound) return;
    el.dataset.bound = '1';
    el.addEventListener('click', e => {
      if (e.target.closest('[data-read], .art-chip, .art-chips')) return;
      openTopicCard(el.dataset.sid);
    });
  });
  stack.querySelectorAll('[data-read]').forEach(btn => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', e => {
      e.stopPropagation();
      openJournal(btn.dataset.read);
    });
  });
  _bindArtChips(stack);
}
function _fillCard(el, s) {
  const st = _stamp(s.session_id, s);
  el.classList.toggle('open', _isCurrent(s.session_id));
  el.classList.toggle('draft', _isDraft(s.session_id));
  el.classList.toggle('running', !!st.running);
  el.classList.remove('live');
  const title = el.querySelector('.card-h b');
  if (title) title.textContent = s.label || '没起名的话题';
  const meta = el.querySelector('.card-h span');
  if (meta) meta.textContent = _whenOf(s) + ' · ' + (s.turns || 0) + ' 轮';
  const stamps = el.querySelector('.stamps');
  if (stamps) stamps.innerHTML = _stampHtml(st);
}
const SHELF_LIM = 20;
let _shelfMore = false;
function _cardHtml(s) {
  const st = _stamp(s.session_id, s);
  const on = _isCurrent(s.session_id);
  const draft = _isDraft(s.session_id);
  const when = draft ? '刚开的' : (_whenOf(s) + ' · ' + (s.turns || 0) + ' 轮');
  const arts = draft
    ? '<div class="art-empty">说一句，这本就开始记</div>'
    : '<div class="art-empty">点开看看</div>';
  const read = draft
    ? ''
    : `<button class="read-btn" type="button" data-read="${esc(s.session_id)}"><i class="ri-book-open-line"></i> 回看这篇</button>`;
  const moreBtn = draft
    ? ''
    : `<button type="button" class="tcard-more" title="更多" data-sid="${esc(s.session_id)}"><i class="ri-more-2-line"></i></button>`;
  return `<article class="tcard${on ? ' open' : ''}${draft ? ' draft' : ''}${st.running ? ' running' : ''}" data-sid="${esc(s.session_id)}">
      <div class="card-h">
        <div><b>${esc(s.label || '没起名的话题')}</b><span>${esc(when)}</span></div>
        <div class="stamps">${_stampHtml(st)}</div>
        ${moreBtn}
      </div>
      <div class="card-body"><div>
        <div class="layer">
          <div class="layer-k">这本的产物</div>
          <div class="arts" data-arts="${esc(s.session_id)}">${arts}</div>
          ${read}
        </div>
      </div></div>
    </article>`;
}
function _paintMore() {
  const stack = _stack();
  if (!stack) return;
  let btn = document.getElementById('topic-more');
  if (!_shelfMore) {
    if (btn) btn.remove();
    return;
  }
  if (!btn) {
    btn = document.createElement('button');
    btn.id = 'topic-more';
    btn.type = 'button';
    btn.className = 'topic-more';
    btn.addEventListener('click', loadMoreShelf);
    stack.appendChild(btn);
  }
  btn.disabled = false;
  btn.innerHTML = '<i class="ri-arrow-down-s-line"></i> 更早的话题';
}
function _appendCards(rows) {
  const stack = _stack();
  if (!stack || !rows.length) return;
  const more = document.getElementById('topic-more');
  const hold = document.createElement('div');
  hold.innerHTML = rows.map(_cardHtml).join('');
  while (hold.firstChild) stack.insertBefore(hold.firstChild, more);
  _bindShelf(stack);
}
function renderShelf() {
  const stack = _stack();
  if (!stack) return;
  if (!_rows.length) {
    stack.classList.remove('fresh');
    stack.innerHTML = '<div class="pane-empty"><i class="ri-book-open-line"></i>还没有说过话 · 第一句就开始有记忆</div>';
    return;
  }
  const els = [...stack.querySelectorAll('.tcard')];
  const same = els.length === _rows.length && els.every((el, i) => el.dataset.sid === _rows[i].session_id);
  if (same) {
    _rows.forEach((s, i) => _fillCard(els[i], s));
    _paintMore();
    return;
  }
  stack.classList.toggle('fresh', !els.length);
  stack.innerHTML = _rows.map(_cardHtml).join('');
  _bindShelf(stack);
  _paintMore();
}
async function _paintArts(sid) {
  const box = _stack() && _stack().querySelector('.tcard[data-sid="' + sid + '"] .arts');
  if (!box) return;
  box.innerHTML = _artsHtml(await _fetchArts(sid), sid);
  _bindArtChips(box);
}
async function openTopicCard(sid) {
  if (!sid || _isDraft(sid)) return;
  if (typeof switchTopic === 'function' && sid !== getSid()) switchTopic(sid);
  const stack = _stack();
  if (stack) {
    stack.querySelectorAll('.tcard').forEach(el => {
      const row = _rows.find(s => s.session_id === el.dataset.sid);
      if (row) _fillCard(el, row);
      else el.classList.toggle('open', el.dataset.sid === sid);
    });
  }
  await _paintArts(sid);
}

const _J_LIM = 280;
let _jFull = [];
function _jText(t) {
  return String(t.content || '')
    .replace(/<face>\s*[^<]+?\s*<\/face>/gi, '')
    .replace(/<detail>([\s\S]*?)<\/detail>/gi, '$1').trim();
}
function _jHtml(s) { return esc(s).replace(/\n/g, '<br>'); }
function _bubbleHtml(t, i) {
  const me = t.role === 'user';
  const text = _jText(t);
  const long = text.length > _J_LIM;
  const short = long ? text.slice(0, _J_LIM) + '…' : text;
  const id = _jFull.length;
  _jFull.push({ full: text, short });
  const more = long
    ? `<button type="button" class="j-more" data-i="${id}"><i class="ri-arrow-down-s-line"></i>展开</button>`
    : '';
  return `<div class="j-bubble ${me ? 'me' : 'her'}" style="animation-delay:${Math.min(i, 8) * .04}s"><div class="j-tx">${_jHtml(short)}</div>${more}<div class="tm">${fmtTime(t.ts)}</div></div>`;
}

async function fillJournal(sid) {
  const title = document.getElementById('j-title');
  const meta = document.getElementById('j-meta');
  const log = document.getElementById('j-log');
  const row = _rows.find(s => s.session_id === sid);
  if (title) title.textContent = (row && row.label) || '没起名的话题';
  if (meta) meta.textContent = (row ? _whenOf(row) + ' · ' + (row.turns || 0) + ' 轮' : '');
  const msg = await fetch('/sessions/' + encodeURIComponent(sid) + '/messages').then(r => r.json()).catch(() => ({}));
  const turns = (msg.turns || []).filter(t =>
    (t.role === 'user' || t.role === 'assistant') && String(t.content || '').trim()
  );
  if (log) {
    _jFull = [];
    log.innerHTML = turns.length
      ? turns.map(_bubbleHtml).join('')
      : '<div class="pane-empty">这本还是空的</div>';
    log.scrollTop = log.scrollHeight;
  }
}

async function openJournal(sid) {
  if (!sid) return;
  if (typeof switchTopic === 'function' && sid !== getSid()) switchTopic(sid);
  _journalSid = sid;
  _reading = true;
  await fillJournal(sid);
  const rail = _rail();
  if (rail) rail.classList.add('reading');
}

function closeJournal() {
  if (!_reading) return false;
  closeArtPop();
  _reading = false;
  _journalSid = '';
  const rail = _rail();
  if (rail) rail.classList.remove('reading');
  return true;
}

async function _fetchShelf(offset, limit) {
  const data = await (await fetch('/sessions?api_only=true&limit=' + limit + '&offset=' + offset)).json();
  const rows = data.sessions || [];
  return { rows, more: rows.length >= limit };
}
let _draftLabel = '新话题';
function _draftRow() {
  return { session_id: DRAFT_SID, label: _draftLabel, turns: 0, mtime: new Date().toISOString() };
}
function draftNew(label) {
  _draft = true;
  _draftLabel = label || '新话题';
  return refreshShelf();
}
function clearDraft() {
  if (!_draft) return;
  _draft = false;
  _draftLabel = '新话题';
  _rows = _rows.filter(s => !_isDraft(s.session_id));
  renderShelf();
}
async function refreshShelf() {
  try {
    const keep = Math.max(SHELF_LIM, _rows.length || 0);
    const pack = await _fetchShelf(0, keep);
    _rows = pack.rows;
    _shelfMore = pack.more;
  } catch (e) {
    _rows = [];
    _shelfMore = false;
  }
  const cur = (typeof getSid === 'function') ? getSid() : null;
  if (cur) _draft = false;
  if (_draft && !cur) {
    _rows = [_draftRow()].concat(_rows.filter(s => !_isDraft(s.session_id)));
  }
  renderShelf();
  if (cur) await _paintArts(cur);
  if (_reading && _journalSid) fillJournal(_journalSid);
}
async function loadMoreShelf() {
  const btn = document.getElementById('topic-more');
  if (btn) { btn.disabled = true; btn.textContent = '在翻…'; }
  try {
    const pack = await _fetchShelf(_rows.length, SHELF_LIM);
    _shelfMore = pack.more;
    if (pack.rows.length) {
      _rows = _rows.concat(pack.rows);
      _appendCards(pack.rows);
    }
  } catch (e) { _shelfMore = false; }
  _paintMore();
}

function bootTopicRail() {
  const neu = document.getElementById('topic-new');
  if (neu) neu.addEventListener('click', () => {
    closeJournal();
    if (typeof startNewTopic === 'function') startNewTopic();
    refreshShelf();
  });
  const hang = document.getElementById('topic-hangout');
  if (hang) hang.addEventListener('click', () => {
    closeJournal();
    if (typeof startHangout === 'function') startHangout();
  });
  if (typeof refreshHangoutDoor === 'function') refreshHangoutDoor();
  const log = document.getElementById('j-log');
  if (log) log.addEventListener('click', e => {
    const btn = e.target.closest('.j-more');
    if (!btn) return;
    const wrap = btn.closest('.j-bubble');
    const tx = wrap && wrap.querySelector('.j-tx');
    const rec = _jFull[+btn.dataset.i];
    if (!tx || !rec) return;
    const open = wrap.classList.toggle('open');
    tx.innerHTML = _jHtml(open ? rec.full : rec.short);
    btn.innerHTML = open
      ? '<i class="ri-arrow-up-s-line"></i>收起'
      : '<i class="ri-arrow-down-s-line"></i>展开';
  });
  const back = document.getElementById('journal-back');
  if (back) back.addEventListener('click', closeJournal);
  const pop = document.getElementById('art-pop');
  const closeBtn = document.getElementById('art-pop-close');
  if (closeBtn) closeBtn.addEventListener('click', closeArtPop);
  if (pop) pop.addEventListener('click', e => { if (e.target === pop) closeArtPop(); });
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    const kb = document.getElementById('kbModalHost');
    if (kb && kb.classList.contains('show')) return;
    if (closeArtPop()) { e.stopPropagation(); return; }
    if (_reading) {
      e.stopPropagation();
      closeJournal();
    }
  }, true);
  // 话题卡 ⋯ 菜单 · 复用 companion.js 的 openTopicMenu/renameTopic/deleteTopic
  const shelf = document.getElementById('topic-stack');
  if (shelf) shelf.addEventListener('click', e => {
    const btn = e.target.closest('.tcard-more');
    if (!btn) return;
    e.stopPropagation();
    if (typeof openTopicMenu === 'function') openTopicMenu(btn.dataset.sid, btn);
  });
  refreshShelf();
  if (typeof weather === 'object' && weather && weather.line) setWeatherLine(weather.line);
}

function setWeatherLine(line) {
  const el = document.querySelector('#topic-shelf .rail-head .sub');
  if (el) el.textContent = line || '没什么特别的。我就在这儿。';
}

window.TopicRail = {
  refresh: refreshShelf,
  paintStamps: function () {
    const stack = _stack();
    if (!stack) return;
    stack.querySelectorAll('.tcard').forEach(el => {
      const row = _rows.find(s => s.session_id === el.dataset.sid);
      if (row) _fillCard(el, row);
      else el.classList.toggle('open', _isCurrent(el.dataset.sid));
    });
  },
  draftNew: draftNew,
  clearDraft: clearDraft,
  openJournal: openJournal,
  closeJournal: closeJournal,
  isReading: function () { return _reading; },
  journalSid: function () { return _journalSid; },
  setWeatherLine: setWeatherLine,
};
window.bootTopicRail = bootTopicRail;
