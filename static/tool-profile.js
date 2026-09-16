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

var TP_ICON = { standard: 'ri-stack-line', chat: 'ri-chat-smile-2-line', dev3d: 'ri-box-3-line', image: 'ri-image-line', writing: 'ri-quill-pen-line' };
var TP_TONE = { standard: '#35c9a0', chat: '#8b93a1', dev3d: '#6ea8ff', image: '#e07bff', writing: '#ffb454' };

var TP_SHORT = { standard: '标准', chat: '闲聊', dev3d: '3D', image: '生图', writing: '写作' };
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
      tpPaintTitleBadge();
      tpOnboardSuggest();
    })
    .catch(function () {});
}

/* 按当前模型预选（原型缺口③ · wish-92b6d4c0）：本机模型 → 建议闲聊档。
   用户点一下就覆盖 · 只影响还没开跑的新对话，不写 meta、不改已跑对话。 */
var _tpSuggest = null;
function tpOnboardSuggest() {
  if (!_tpSuggest || !_tpSuggest.id || _tpOnboardPick) return;
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

function tpOnboardPaint() {
  var gal = document.getElementById('tpOnboardGal');
  if (!gal) return;
  var sc = document.getElementById('tpOnboardSc');
  var pickScene = ['dev3d', 'image', 'writing'].indexOf(_tpOnboardPick) >= 0;
  var kids = gal.querySelectorAll('.tp-gcard');
  var eff = _tpOnboardPick || 'standard';   // 未选 = 默认标准亮着（HTML 里的默认不能被 paint 抹掉）
  for (var i = 0; i < kids.length; i++) {
    var p = kids[i].dataset.p;
    kids[i].classList.toggle('on', p === eff || (p === 'scene' && pickScene));
  }
  if (sc) {
    sc.hidden = !(pickScene || sc.dataset.open === '1');
    var ss = sc.querySelectorAll('.s');
    for (var j = 0; j < ss.length; j++) ss[j].classList.toggle('on', ss[j].dataset.p === _tpOnboardPick);
  }
}

function tpOnboardInit() {
  var gal = document.getElementById('tpOnboardGal');
  if (!gal) return false;
  if (gal.dataset.tpBound) return true;
  gal.dataset.tpBound = '1';
  var sc = document.getElementById('tpOnboardSc');
  gal.addEventListener('click', function (e) {
    var card = e.target && e.target.closest ? e.target.closest('.tp-gcard') : null;
    if (!card) return;
    var p = card.dataset.p;
    if (p === 'scene') {
      if (sc) sc.dataset.open = '1';
      tpOnboardPaint();
      return;
    }
    if (sc) delete sc.dataset.open;
    _tpOnboardPick = p;
    tpOnboardPaint();
    _tpCur = p;
    tpPaintTitleBadge();
  });
  if (sc) {
    sc.addEventListener('click', function (e) {
      var s = e.target && e.target.closest ? e.target.closest('.s') : null;
      if (!s || !s.dataset.p) return;
      _tpOnboardPick = s.dataset.p;
      tpOnboardPaint();
      _tpCur = s.dataset.p;
      tpPaintTitleBadge();
    });
  }
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
