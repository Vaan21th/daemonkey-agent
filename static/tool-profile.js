/* static/tool-profile.js · 会话能力档位（wish-16fa5930 第一刀）
   跟对话实例走：meta.last_tool_profile。
   显示位置（BRO 2026-09-16 定稿）：① 标题栏小标（当前对话 · 纯显示不点击）② 话题列表每行徽标（含标准档 · 标准做淡）。
   底部 chip 已撤 —— 换档 = 开新对话（不再提供"点击升档"入口）。
   纪律：开跑即锁 · 降档=开新对话。 */
var _tpList = null, _tpCur = '', _tpMenu = null, _tpOwner = null, _tpRaf = 0;

function tpNow() { return _tpCur || 'standard'; }
window.tpNow = tpNow;

function tpById(id) {
  if (!_tpList) return null;
  for (var i = 0; i < _tpList.length; i++) if (_tpList[i].id === id) return _tpList[i];
  return null;
}
/* 等级：standard 全量 2 > 场景档 1 > 闲聊 0。只升不降 = rank 低于当前的一律灰。 */
var _tpRankMap = { standard: 2, chat: 0 };
function tpRank(id) { return _tpRankMap[id] !== undefined ? _tpRankMap[id] : 1; }
function tpLabel(id) {
  var p = tpById(id);
  if (p) return p.name + ' · ' + p.count + ' 个工具';
  return (!id || id === 'standard') ? '标准' : String(id);
}

var TP_ICON = { standard: 'ri-stack-line', chat: 'ri-chat-smile-2-line', work: 'ri-briefcase-4-line', code: 'ri-code-s-slash-line', dev3d: 'ri-box-3-line', image: 'ri-image-line', writing: 'ri-quill-pen-line' };
var TP_TONE = { standard: '#35c9a0', chat: '#8b93a1', work: '#5ad1c8', code: '#ffa657', dev3d: '#6ea8ff', image: '#e07bff', writing: '#ffb454' };

var TP_SHORT = { standard: '标准', chat: '闲聊', work: '工作', code: '编程', dev3d: '3D', image: '生图', writing: '写作' };
/* 档位 → 徽标数据（话题列表 + 标题栏共用；没记录 = 默认标准档）
   short=列表短名 · label=带件数（标题栏用）· dim=标准档做淡 */
function tpBadgeInfo(id) {
  var pid = id || 'standard';
  var p = tpById(pid);
  var short = TP_SHORT[pid] || (p ? p.name : pid);
  var count = p ? p.count : '';
  var cls = pid === 'standard' ? 'std' : (pid === 'chat' ? 'chat' : 'three');
  return {
    short: short,
    label: short + (count ? ' · ' + count + ' 个工具' : ''),   // 标题栏用（名词对齐：加载 N 个工具）
    cls: cls,
    dim: pid === 'standard',
    title: short + '档 · 已加载 ' + (count || '?') + ' 个工具'
  };
}
window.tpBadgeInfo = tpBadgeInfo;

function tpLoad() {
  var tok = (typeof token === 'string' && token) || localStorage.getItem('opus_ui_token') || '';
  fetch('/tool-profiles', { headers: tok ? { Authorization: 'Bearer ' + tok } : {} })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      _tpList = (d && d.profiles) || [];
      _tpSuggest = (d && d.suggested) || null;
      tpPaintMine();
      tpPaintTitleBadge();
      tpOnboardSuggest();
      tpPaintCounts();
    })
    .catch(function () {});
}

/* 按当前模型预选（原型缺口③ · wish-92b6d4c0）：本机模型 → 建议闲聊档。
   用户点一下就覆盖 · 只影响还没开跑的新对话，不写 meta、不改已跑对话。 */
var _tpSuggest = null;
function tpOnboardSuggest() {
  if (_tpOnboardPick) return;
  /* wish-0571fd96：用户钉过默认档 → 开局预选它（优先于模型建议；standard 不在此列 = 零回归） */
  var def = tpDefaultId();
  if (def && def !== 'standard') {
    _tpOnboardPick = def;
    _tpCur = def;
    tpOnboardPaint();
    tpPaintTitleBadge();
    return;
  }
  if (!_tpSuggest || !_tpSuggest.id) return;
  var id = _tpSuggest.id;
  var hint = document.getElementById('tpOnboardHint');
  if (!tpById(id)) { if (hint) hint.hidden = true; return; }
  _tpOnboardPick = id;
  _tpCur = id;
  tpOnboardPaint();
  tpPaintTitleBadge();
  if (hint) {
    hint.textContent = (_tpSuggest.why || '按当前模型建议') + '「' + tpLabel(id) + '」· 点卡片可改';
    hint.hidden = false;
  }
}
window.tpOnboardSuggest = tpOnboardSuggest;

/* 卡片上的数字取真值（BRO 2026-09-18）：原为写死的 12/36 —— CORE 从 36 变 30 后就错了。
   改由 /tool-profiles 的 count 填；没拿到就显示 —（宁可空着，也不显示错的数）。 */
function tpPaintCounts() {
  for (var i = 0; i < _tpList.length; i++) {
    var p = _tpList[i];
    var card = document.querySelector('.tp-gcard[data-p="' + p.id + '"]');
    if (!card) continue;
    var n = card.querySelector('.n');
    if (n && typeof p.count === 'number' && p.count > 0) {
      n.textContent = p.count;
      if (typeof p.tok === 'number' && p.tok > 0) {   /* BRO 2026-09-21：悬停看前缀数值（纯 CSS 气泡） */
        n.classList.add('tok');
        n.dataset.tip = '每轮前缀 ≈ ' + p.tok.toLocaleString() + ' tok（灵魂+工具）· 工具 ' + p.count + ' 件';
      }
    }
  }
}
window.tpPaintCounts = tpPaintCounts;

/* 我的预设（wish-6350cced ②③）→ 选档卡尾部。【常驻区】：空的时候也要在 ——
   不然用户根本不知道这个功能存在（BRO 2026-09-20 实测：“没有啊？我的预设？”= 空即隐藏 → 入口蒸发）。
   末尾恒有一张「＋ 装一套」卡 → 调 openPrefixViewer() 铺装修配台。
   真卡点击被 tpOnboardInit 的委托接住；「＋」卡靠自己的 onclick（pickCard 里 !p 已拦）。 */
function tpPaintMine() {
  var wrap = document.getElementById('tpMine');
  var mg = document.getElementById('tpMineGal');
  if (!wrap || !mg || !_tpList) return;
  var mine = _tpList.filter(function (p) { return p && p.user; });
  var html = mine.map(function (p) {
    return '<div class="tp-gcard" data-p="' + tpEsc(p.id) + '" title="' + tpEsc(p.desc || p.name) + '">'
      + '<div class="tp-acts">'
      + '<span class="tp-more" title="更多操作：设为默认 / 编辑 / 删除"><i class="ri-more-fill"></i></span>'
      + '</div>'
      + '<div class="tp-gr1"><span class="ic gg">◉</span>' + tpEsc(p.name)
      + '<span class="n">' + (p.count || '—') + '</span></div>'
      + '<div class="tp-gd">' + (tpEsc(p.desc || '') || '自己装配的一套') + '<br>我的 · 可编辑</div></div>';
  }).join('');
  html += '<div class="tp-gcard tp-gcard-add" onclick="if(typeof openPrefixViewer===\'function\')openPrefixViewer()" '
    + 'title="去装配台挑工具 → 存下来就成为自己的档">'
    + '<div class="tp-gr1"><span class="ic gg">＋</span>装一套</div>'
    + '<div class="tp-gd">' + (mine.length ? '再装一套不一样的' : '还没有自己的预设') + '<br>去装配台挑工具 · 存下来</div></div>';
  mg.innerHTML = html;
  wrap.hidden = false;
  tpOnboardPaint();
  tpPaintPins();
}
window.tpPaintMine = tpPaintMine;

/* ── 默认钉（wish-0571fd96）：点它 = 把这张卡钉为「新对话默认档」────────────
   选中（on）与默认（tp-isdef）互相独立：on = 这一场用什么；钉 = 新对话开局亮谁。
   钉由 JS 统一挂（静态卡 + 预设卡一视同仁）；「＋ 装一套」无 data-p → 不挂。 */
function tpDefaultId() {
  if (_tpList) for (var i = 0; i < _tpList.length; i++) if (_tpList[i].default) return _tpList[i].id;
  return '';
}

function tpPaintPins() {
  var all = document.querySelectorAll('#tpOnboardGal .tp-gcard[data-p], #tpMineGal .tp-gcard[data-p]');
  for (var i = 0; i < all.length; i++) {
    var card = all[i];
    /* BRO 2026-09-21：三个图标收进一个「⋯」→ 点开弹出功能选单（设为默认 / 编辑 / 删除 · tpMore） */
    var acts = card.querySelector('.tp-acts');
    if (!acts) { acts = document.createElement('div'); acts.className = 'tp-acts'; card.appendChild(acts); }
    card.querySelectorAll('.tp-pin, .tp-edit, .tp-del').forEach(function (x) { x.remove(); });   /* 旧版散图标 → 收掉 */
    if (!acts.querySelector('.tp-more')) {
      var mo = document.createElement('span');
      mo.className = 'tp-more';
      mo.title = '更多操作：设为默认 / 编辑 / 删除';
      mo.innerHTML = '<i class="ri-more-fill" aria-hidden="true"></i>';
      acts.appendChild(mo);
    }
    var isDef = false;
    if (_tpList) for (var j = 0; j < _tpList.length; j++) {
      if (_tpList[j].id === card.dataset.p) { isDef = !!_tpList[j].default; break; }
    }
    card.classList.toggle('tp-isdef', isDef);   /* 默认档 → ⋯ 亮紫点 */
  }
}

/* BRO 2026-09-21：⋯ 功能选单（钉/铅笔/垃圾桶 收成一个菜单）· 弹在卡上方 · 点别处关闭 */
var _tpMenuEl = null;
function tpMenuClose() { if (_tpMenuEl) { _tpMenuEl.remove(); _tpMenuEl = null; } }
function tpMore(card) {
  tpMenuClose();
  var pid = card && card.dataset.p;
  if (!pid) return;
  var isUser = pid.indexOf('u-') === 0;
  var isDef = false;
  if (_tpList) for (var j = 0; j < _tpList.length; j++) if (_tpList[j].id === pid) { isDef = !!_tpList[j].default; break; }
  var m = document.createElement('div');
  m.className = 'tp-menu';
  m.innerHTML = '<div class="tp-mi' + (isDef ? ' dis' : '') + '" data-a="def"><i class="ri-pushpin-2-line"></i>' + (isDef ? '已是默认档' : '设为默认档') + '</div>'
    + '<div class="tp-mi" data-a="edit"><i class="ri-edit-line"></i>编辑这一档</div>'
    + (isUser ? '<div class="tp-mi" data-a="meta"><i class="ri-text"></i>改名称和描述</div>' : '')
    + (isUser ? '<div class="tp-mi danger" data-a="del"><i class="ri-delete-bin-6-line"></i>删掉这个预设</div>' : '');
  m.addEventListener('click', function (e) {
    var it = e.target && e.target.closest ? e.target.closest('.tp-mi') : null;
    if (!it || it.classList.contains('dis')) return;
    var a = it.getAttribute('data-a');
    if (a === 'def') { tpSetDefault(card); }
    else if (a === 'edit') { if (typeof openPrefixViewer === 'function') openPrefixViewer(pid); }
    else if (a === 'meta') { tpEditMeta(pid); }
    else if (a === 'del') { tpDelPreset(card); }
    tpMenuClose();
  });
  document.body.appendChild(m);
  var bt = card.querySelector('.tp-more');
  if (bt) {
    var r = bt.getBoundingClientRect();
    m.style.left = Math.max(8, r.right - m.offsetWidth) + 'px';
    m.style.top = Math.max(8, r.top - m.offsetHeight - 6) + 'px';
  }
  _tpMenuEl = m;
  /* 关闭：全局只注册一次（懒）· 每次点击判断 · capture 阶段不受 stopPropagation 影响 · Esc 也能关 */
  if (!window._tpMenuCloseBound) {
    window._tpMenuCloseBound = 1;
    document.addEventListener('click', function (ev) {
      if (_tpMenuEl && !_tpMenuEl.contains(ev.target)) tpMenuClose();
    }, true);
    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') tpMenuClose();
    }, true);
  }
}
window.tpMore = tpMore;

function tpSetDefault(card) {
  var pid = card && card.dataset.p;
  if (!pid) return;
  var nm = (tpById(pid) || {}).name || pid;
  if (pid === tpDefaultId()) { tpTip('「' + nm + '」已经是默认档'); return; }
  var tok = (typeof token === 'string' && token) || localStorage.getItem('opus_ui_token') || '';
  var headers = { 'Content-Type': 'application/json' };
  if (tok) headers.Authorization = 'Bearer ' + tok;
  fetch('/profiles/default', { method: 'POST', headers: headers, body: JSON.stringify({ id: pid }) })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d || !d.ok) { tpTip('设默认失败：' + ((d && d.error) || '未知')); return; }
      for (var i = 0; i < _tpList.length; i++) _tpList[i].default = (_tpList[i].id === pid);
      tpPaintPins();
      tpTip('已把「' + nm + '」钉为默认 · 以后新对话开局自动亮它');
    })
    .catch(function () { tpTip('设默认失败 · 网络没通？'); });
}

/* 删预设（wish-379e5f5a · 2026-09-21 BRO：保存了预设可以删除吗？）——垃圾桶 + 二次确认，删掉走 /profiles/delete。
   删的是预设（勾选名单），工具本身不受影响；被删的如果是默认档，服务端自动回落 standard。 */
function tpDelPreset(card) {
  var pid = card && card.dataset.p;
  if (!pid || pid.indexOf('u-') !== 0) return;
  var nm = (tpById(pid) || {}).name || pid;
  if (!window.confirm('删掉「' + nm + '」？工具本身不受影响；这个预设的勾选名单会没。')) return;
  var tok = (typeof token === 'string' && token) || localStorage.getItem('opus_ui_token') || '';
  var headers = { 'Content-Type': 'application/json' };
  if (tok) headers.Authorization = 'Bearer ' + tok;
  fetch('/profiles/delete', { method: 'POST', headers: headers, body: JSON.stringify({ id: pid }) })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d || !d.ok) { tpTip('删失败：' + ((d && d.error) || '未知')); return; }
      if (_tpOnboardPick === pid) _tpOnboardPick = '';
      tpTip('已删掉「' + nm + '」');
      tpLoad();
    })
    .catch(function () { tpTip('删失败 · 网络没通？'); });
}

/* 改名称 / 描述（wish-4607fd37 · BRO 2026-09-28：「用户可以自己编辑描述和标题，弹窗出来就行」）。
   窄通道：只把 name + desc 发给 /profiles/meta · 工具与层一律不碰
   （走 /profiles/update 会在 tools 为空时被拒，且改名不该动「回到最初」快照）。
   弹窗复用现成的 kb-modal 体系（同 depot / clients 那批 · 同一单例 host）。 */
function tpEditMeta(pid) {
  if (!pid || pid.indexOf('u-') !== 0) return;
  var p = tpById(pid) || {};
  if (typeof _closeAllKbModals === 'function') _closeAllKbModals();
  var host = document.getElementById('kbModalHost');
  if (!host) { host = document.createElement('div'); host.id = 'kbModalHost'; host.className = 'kb-modal-host'; document.body.appendChild(host); }
  var curDesc = String(p.desc || '');
  host.innerHTML = '<div class="kb-modal-mask"></div>'
    + '<div class="kb-modal tp-meta-modal" role="dialog" aria-modal="true">'
    + '<div class="kb-modal-head"><span class="kb-modal-title"><i class="ri-text"></i> 改名称和描述</span>'
    + '<span class="kb-modal-meta">' + (p.count || 0) + ' 个工具 · 只改文字不动工具</span>'
    + '<button class="kb-modal-close" title="关闭 (Esc)">✕</button></div>'
    + '<div class="kb-modal-body tp-meta-body">'
    + '<label class="tp-mf"><span>名称</span>'
    + '<input class="tp-mf-in" id="tpMetaName" maxlength="30" value="' + tpEsc(p.name || '') + '" placeholder="给它起个名字"></label>'
    + '<label class="tp-mf"><span>描述</span>'
    + '<textarea class="tp-mf-in" id="tpMetaDesc" maxlength="80" rows="3" placeholder="这套档位是干嘛的（显示在卡片上）">' + tpEsc(curDesc) + '</textarea>'
    + '<em class="tp-mf-cnt" id="tpMetaCnt">' + curDesc.length + '/80</em></label>'
    + '<div class="tp-mf-foot">'
    + '<button class="btn-ghost" id="tpMetaCancel">取消</button>'
    + '<button class="btn-primary" id="tpMetaSave">保存</button>'
    + '</div></div></div>';
  host.classList.add('show');
  var inp = host.querySelector('#tpMetaName');
  var ta = host.querySelector('#tpMetaDesc');
  var cnt = host.querySelector('#tpMetaCnt');
  var onKey = function (e) { if (e.key === 'Escape') close(); };
  var close = function () { host.classList.remove('show'); document.removeEventListener('keydown', onKey); };
  host.querySelector('.kb-modal-close').onclick = close;
  host.querySelector('.kb-modal-mask').onclick = close;
  host.querySelector('#tpMetaCancel').onclick = close;
  document.addEventListener('keydown', onKey);
  if (ta && cnt) ta.addEventListener('input', function () { cnt.textContent = ta.value.length + '/80'; });
  host.querySelector('#tpMetaSave').onclick = function () {
    var nm = String(inp.value || '').trim();
    if (!nm) { tpTip('名字不能空着'); inp.focus(); return; }
    var tok = (typeof token === 'string' && token) || localStorage.getItem('opus_ui_token') || '';
    var headers = { 'Content-Type': 'application/json' };
    if (tok) headers.Authorization = 'Bearer ' + tok;
    fetch('/profiles/meta', { method: 'POST', headers: headers, body: JSON.stringify({ id: pid, name: nm, desc: String(ta.value || '') }) })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || !d.ok) { tpTip('没改成：' + ((d && d.error) || '未知')); return; }
        close();
        tpTip('已改好「' + nm + '」');
        tpLoad();
      })
      .catch(function () { tpTip('没改成 · 网络没通？'); });
  };
  if (inp) inp.focus();
}
window.tpEditMeta = tpEditMeta;

/* 标题栏档位标（BRO 2026-09-16：只显示 · 不点击 · 换档=开新对话） */
function tpPaintTitleBadge() {
  var b = document.getElementById('tpTitleBadge');
  if (!b) return;
  var id = tpNow();
  var bi = tpBadgeInfo(id);
  b.textContent = bi.label;
  b.className = 'sp-prof ' + bi.cls;   // 标题栏不做 dim —— 这是"当前对话"的主显示，列表才做淡
  b.title = bi.title + '（跟对话走 · 换档开新对话）';
  b.hidden = false;
}
window.tpPaintTitleBadge = tpPaintTitleBadge;

/* chat.js 切会话时调：meta.last_tool_profile → chip 跟上 */
function applySessionProfile(meta) {
  var prof = (meta && meta.last_tool_profile) || '';
  if (!prof && _tpOnboardPick) prof = _tpOnboardPick;   // 还没开跑的新对话 → chip 显示预选
  _tpCur = prof;
  tpPaintTitleBadge();
}
window.applySessionProfile = applySessionProfile;

function tpTip(msg) {
  try {
    var d = document.createElement('div');
    d.className = 'tp-tip';
    d.textContent = msg;
    document.body.appendChild(d);
    setTimeout(function () { if (d.parentNode) d.parentNode.removeChild(d); }, 2800);
  } catch (e) {}
}

/* ── 浮层菜单（模式抄 turn-knobs.js：fixed 挂 body · 点外部/ESC 关） ── */
function tpEsc(s) {
  return String(s || '').replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}
function tpCloseMenu() {
  if (_tpMenu && _tpMenu.parentNode) _tpMenu.parentNode.removeChild(_tpMenu);
  _tpMenu = null;
  if (_tpOwner) _tpOwner.classList.remove('tk-open');
  _tpOwner = null;
}
function tpPosition() {
  if (!_tpMenu || !_tpOwner) return;
  var r = _tpOwner.getBoundingClientRect();
  var mh = _tpMenu.offsetHeight || 0;
  var mw = _tpMenu.offsetWidth || 260;
  _tpMenu.style.left = Math.max(8, Math.min(r.left, window.innerWidth - mw - 8)) + 'px';
  if (mh && (r.top - 8) < mh) {
    _tpMenu.style.top = (r.bottom + 6) + 'px';
    _tpMenu.style.bottom = 'auto';
  } else {
    _tpMenu.style.top = 'auto';
    _tpMenu.style.bottom = (window.innerHeight - r.top + 6) + 'px';
  }
}
function tpReposition() {
  if (_tpRaf) return;
  _tpRaf = window.requestAnimationFrame(function () { _tpRaf = 0; tpPosition(); });
}

function tpItems() {
  var cur = tpNow();
  if (!_tpList || !_tpList.length) {
    return [{ label: '档位表还没加载', note: '点开重试（端点在 daemon 重启后才有）', icon: 'ri-loader-4-line', disabled: true }];
  }
  var arr = _tpList.slice().sort(function (a, b) { return tpRank(b.id) - tpRank(a.id); });
  var out = [];
  arr.forEach(function (p) {
    var locked = tpRank(p.id) < tpRank(cur);
    out.push({
      label: p.name + ' · ' + p.count + ' 个工具',
      note: locked ? '已在更高档 · 降档请开新对话' : (p.desc || ''),
      icon: TP_ICON[p.id] || 'ri-stack-line',
      tone: TP_TONE[p.id] || '',
      on: p.id === cur,
      disabled: locked,
      pick: (function (id) { return function () { tpPick(id); }; })(p.id),
    });
  });
  return out;
}

function tpOpenMenu() {
  var btn = document.getElementById('tpChip');
  if (!btn) return;
  var wasOpen = (_tpOwner === btn) && !!_tpMenu;
  /* 跟思考/强度菜单互斥：他们的 outside-click 不管我的菜单，打开前先主动关掉 */
  try { if (typeof window.closeTurnKnobMenu === 'function') window.closeTurnKnobMenu(); } catch (e) {}
  tpCloseMenu();
  if (wasOpen) return;
  if (!_tpList) tpLoad();
  _tpOwner = btn;
  btn.classList.add('tk-open');
  var box = document.createElement('div');
  box.className = 'turn-menu';
  box.setAttribute('role', 'menu');
  tpItems().forEach(function (it) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'turn-menu-item' + (it.on ? ' on' : '');
    if (it.disabled) { b.disabled = true; b.style.opacity = '0.45'; b.style.cursor = 'default'; }
    if (it.tone) b.style.setProperty('--tmi', it.tone);
    b.innerHTML = '<i class="tmi-ic ' + tpEsc(it.icon) + '" aria-hidden="true"></i>'
      + '<span class="tmi-body"><b>' + tpEsc(it.label) + '</b>'
      + (it.note ? '<small>' + tpEsc(it.note) + '</small>' : '')
      + '</span><i class="ri-check-line tmi-check"></i>';
    if (!it.disabled && it.pick) {
      b.onclick = function (ev) { ev.stopPropagation(); it.pick(); };
    }
    box.appendChild(b);
  });
  document.body.appendChild(box);
  _tpMenu = box;
  tpPosition();
}

function tpPick(id) {
  if (!id) return;
  tpCloseMenu();
  if (id === tpNow()) return;
  var sid = (typeof sessionId === 'string' && sessionId) || '';
  if (!sid || sid.indexOf('tmp-') === 0) {
    tpTip('这条对话还没开跑 · 档位在第一条消息发出时锁定');
    return;
  }
  _tpCur = id;
  tpPaintTitleBadge();
  tpTip('已切到「' + tpLabel(id) + '」· 从下一轮生效');
  if (typeof _patchSessionMeta === 'function') {
    _patchSessionMeta(sid, { last_tool_profile: id });
    return;
  }
  var tok = (typeof token === 'string' && token) || localStorage.getItem('opus_ui_token') || '';
  if (!tok) return;
  fetch('/sessions/' + encodeURIComponent(sid) + '/meta', {
    method: 'POST',
    headers: { Authorization: 'Bearer ' + tok, 'Content-Type': 'application/json' },
    body: JSON.stringify({ last_tool_profile: id }),
  }).catch(function () {});
}

/* ── 新对话选档（wish-16fa5930 第 6 步 · 方案 B 三卡展柜 · BRO 2026-09-15 拍板）────────
   选中的档存 _tpOnboardPick → 随首轮请求（chat.js 带 tool_profile）进 daemon →
   由服务端入口写进新会话 meta（开跑即锁）· 不选 = 不传（服务端默认 standard · 零回归）。 */
var _tpOnboardPick = '';

function tpPendingProfile() { return _tpOnboardPick || ''; }
window.tpPendingProfile = tpPendingProfile;

/* ── 外部预设本场档位（BRO 2026-09-21:「开新对话时候，要能把用户选的这个带上」）──
   外部项目管理点「开新对话」时调它 —— 等价于用户亲手点了那张卡：
   选档卡点亮 + 随首轮请求进 daemon。用户想改，点别的卡覆盖即可。
   不改 chat.js：那条链本来就认 _tpOnboardPick，这里只是给它一个程序化入口。 */
function tpPresetPick(pid) {
  _tpOnboardPick = String(pid || '');
  tpOnboardPaint();
}
window.tpPresetPick = tpPresetPick;

function tpOnboardPaint() {
  var gal = document.getElementById('tpOnboardGal');
  if (!gal) return;
  var all = [];
  gal.querySelectorAll('.tp-gcard').forEach(function (k) { all.push(k); });
  var mg = document.getElementById('tpMineGal');
  if (mg) mg.querySelectorAll('.tp-gcard').forEach(function (k) { all.push(k); });
  var eff = _tpOnboardPick || 'standard';   // 未选 = 默认标准亮着（HTML 里的默认不能被 paint 抹掉）
  for (var i = 0; i < all.length; i++) {
    all[i].classList.toggle('on', all[i].dataset.p === eff);
  }
}

function tpOnboardInit() {
  var gal = document.getElementById('tpOnboardGal');
  if (!gal) return false;
  if (gal.dataset.tpBound) return true;
  gal.dataset.tpBound = '1';
  function pickCard(e) {
    var mo = e.target && e.target.closest ? e.target.closest('.tp-more') : null;
    if (mo) {   // BRO 2026-09-21：点⋯ = 弹出功能选单（设为默认 / 编辑 / 删除 · 不算选档）
      var mc = mo.closest('.tp-gcard');
      if (mc) { e.stopPropagation(); tpMore(mc); }
      return;
    }
    var pin = e.target && e.target.closest ? e.target.closest('.tp-pin') : null;
    if (pin) {   // wish-0571fd96：点钉 = 设为默认（不算选档）· 旧 DOM 兜底
      tpSetDefault(pin.closest('.tp-gcard'));
      return;
    }
    var ed = e.target && e.target.closest ? e.target.closest('.tp-edit') : null;
    if (ed) {   // BRO 2026-09-21：点铅笔 = 去装配台编辑这套预设（不算选档）
      var ec = ed.closest('.tp-gcard');
      if (ec && ec.dataset.p && typeof openPrefixViewer === 'function') openPrefixViewer(ec.dataset.p);
      return;
    }
    var del = e.target && e.target.closest ? e.target.closest('.tp-del') : null;
    if (del) {   // wish-379e5f5a：点垃圾桶 = 删预设（不算选档）
      tpDelPreset(del.closest('.tp-gcard'));
      return;
    }
    var card = e.target && e.target.closest ? e.target.closest('.tp-gcard') : null;
    if (!card) return;
    var p = card.dataset.p;
    if (!p) return;   // 「＋ 装一套」入口卡（无档位）· 不参与选择
    _tpOnboardPick = p;
    tpOnboardPaint();
    _tpCur = p;
    tpPaintTitleBadge();
  }
  gal.addEventListener('click', pickCard);
  var mg = document.getElementById('tpMineGal');
  if (mg) mg.addEventListener('click', pickCard);
  tpOnboardPaint();
  return true;
}

/* chat.js commitSessionId（tmp → 真 sid）时调：消费掉预选（档已随首轮请求交给服务端） */
function tpOnCommitSession(sid) {
  if (!_tpOnboardPick) return;
  _tpOnboardPick = '';
  tpOnboardPaint();
}
window.tpOnCommitSession = tpOnCommitSession;

/* ── 绑定 ──────────────────────────────────────────── */
/* 注：底部 chip 的点击绑定（tpBind）已撤 —— BRO 2026-09-16：档位纯显示 · 换档走新对话。
   菜单相关（tpOpenMenu / tpPick / tpPosition …）暂留备复用：未来要给"升档"接新入口时直接挂。 */
if (!tpOnboardInit()) {
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', tpOnboardInit);
  var _tpM = 0, _tpMTimer = setInterval(function () { if (tpOnboardInit() || ++_tpM > 40) clearInterval(_tpMTimer); }, 250);
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', tpLoad);
} else {
  setTimeout(tpLoad, 0);
}
