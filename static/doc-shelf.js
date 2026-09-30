/* ============================================================================
 * doc-shelf.js  ·  产物面板独立模块  (工作台 / 专注版 / 未来陪伴 三处共用)
 * ----------------------------------------------------------------------------
 * 立项: 用户 2026-09-15 · wish-54d21d68 —— 从 chat.js 整块搬出, 单独可维护。
 *
 * 为什么这么搬: 跨文件零改动 —— 顶层 function 进全局作用域, 所有调用点
 *   (含 HTML onclick="xxx()") 原样工作。依赖的 token / sessionId / $detailPane /
 *   addSys / escHtml / mdRender / openStage 等全在函数体内运行时解析, 所以
 *   本文件【必须排在 chat.js 之后】加载 (见 chat.html 里的 <script> 顺序)。
 *
 * 组成:
 *   [1] 专注版右栏 —— 两个视图 (当前产物 / 产物库) + 宽度拖拽 + 退出专注版还中栏
 *   [2] 产物列表与预览 —— 收集 → 分类 → 卡片 → 预览弹框 → 另存为 / 本机打开 / 不挂本话题
 *   分工 (用户 拍板): 预览 = 弹框 (看) · 产物库 = 查看 & 批注 (改)
 * ============================================================================ */

// ══════════════════ [1] 专注版右栏 (当前产物 / 产物库) ══════════════════

// 列表尾部: 归档 toggle + 有更多才显示"加载更早" · 按钮统一 btn-ghost (铁律 10) · 居中
function _renderCompactFoot(list, sessions) {
  const foot = document.getElementById('compactSessionsFoot');
  if (!foot) return;
  const hasMore = sessions && sessions.length >= _COMPACT_PAGE;
  const archBtn = _compactShowArchived
    ? '<button class="compact-foot-more" onclick="toggleCompactArchived()"><i class="ri-arrow-left-line"></i> 返回话题列表</button>'
    : '<button class="compact-foot-more" onclick="toggleCompactArchived()"><i class="ri-archive-line"></i> 查看已归档</button>';
  const moreBtn = hasMore ? '<button class="compact-foot-more" onclick="loadMoreCompactSessions()">加载更早的话题</button>' : '';
  foot.innerHTML = `<div class="compact-foot-row">${archBtn}</div>` + (moreBtn ? `<div class="compact-foot-row">${moreBtn}</div>` : '');
}

// 右侧产物面板 (复用 collectSessionDocs + _docCardHtml · 与 docsView 同源)
async function renderCompactArtifacts() {
  const body = document.getElementById('compactArtBody');
  const sub = document.getElementById('compactArtSub');
  if (!body) return;
  if (!token) { body.innerHTML = '<div class="docs-view-empty">还没填 token</div>'; return; }
  body.innerHTML = '<div class="docs-view-loading">扫描产物…</div>';
  try {
    const docs = await collectSessionDocs();
    await _loadDocFavSet();          // ⭐ 同上 · 右侧产物面板也看收藏态
    if (sub) sub.textContent = docs.length ? `${docs.length} 项` : '';
    if (!docs.length) {
      body.innerHTML = `<div class="docs-view-empty">
        <i class="ri-file-list-3-line"></i>
        <div>本话题还没有产出</div>
      </div>`;
      return;
    }
    let html = _docSortBar();
    for (const cat of _DOC_CATS) {
      const group = _docSortApply(docs.filter(d => _docCategory(d.ext).key === cat.key));
      if (!group.length) continue;
      html += `<div class="docs-sec-title"><i class="${cat.icon}"></i> ${cat.label} <span style="opacity:.6;font-weight:400">(${group.length})</span></div>`;
      html += group.map(d => _docCardHtml(d)).join('');
    }
    body.innerHTML = html;
  } catch (e) {
    body.innerHTML = '<div class="docs-view-empty">扫描出错: ' + e.message + '</div>';
  }
}

// 产物折叠条: 点击展开/收起 (用户 要"产物列表"文字 + 向左展开图标)
function toggleCompactArtifacts() {
  const a = document.getElementById('compactArtifacts');
  const t = document.getElementById('compactArtToggle');
  if (!a) return;
  const open = a.classList.toggle('open');
  if (t) t.classList.toggle('opened', open);
  if (open) renderCompactArtifacts();  // 每次展开刷新 (产物可能刚生成)
  if (!open) toggleCompactLibrary(false);   // 面板都收了 · 产物库也不能把中栏留在外面
  _syncCompactArtTabs();
}

// ── 专注版右栏 · 产物库 (用户 2026-09-15) ────────────────────────────
//   打开 = 把中栏容器 #detailPane 整个挪进 .cl-slot → 工作台那套 (dashboard 面板 /
//   stage 画布 / 批注 / HTML 原型) 原样在右栏工作 · 一行都不用改 (元素对象与监听器不变).
//   关 = 挪回原位。一份代码两个挂载点 · 不分叉。
let _compactLibHome = null;   // { parent, next } 记住中栏原来的位置
let _compactSlotDomain = '';  // 槽里当前是哪个域: 'reports' 产物库 / 'projects' 我的项目 (BRO 2026-09-21)

function toggleCompactLibrary(force, opts) {
  const wrap = document.getElementById('compactArtifacts');
  const slot = document.getElementById('compactLibSlot');
  const pane = document.getElementById('detailPane');
  const btn = document.getElementById('compactLibOpen');
  if (!wrap || !slot || !pane) return false;
  const was = wrap.classList.contains('ca-lib-open');
  const open = (typeof force === 'boolean') ? force : !was;
  if (open === was) {
    // 已在开态：如果只是【域】要换（产物库 ↔ 我的项目），允许换域刷新，不算重复操作
    if (open && opts && opts.domain && opts.domain !== _compactSlotDomain) {
      try { loadDashboard(opts.domain); } catch (e) { console.warn('compact lib swap:', e); }
      _compactSlotDomain = opts.domain;
      wrap.dataset.slotDomain = _compactSlotDomain;
      _syncCompactArtTabs();
    }
    return open;
  }

  if (open) {
    if (!_compactLibHome) _compactLibHome = { parent: pane.parentNode, next: pane.nextSibling };
    slot.hidden = false;
    slot.appendChild(pane);                       // ← 只换挂载点
    wrap.classList.add('ca-lib-open');
    if (btn) btn.classList.add('on');
    // 用户 2026-09-15: 点开产物库 = 直接进「产物库」域 (reports) · 不能停在 BI 看板首页。
    // 两个坑都踩过: ① 想省一次加载加 if(!pane.children.length) 短路 —— 容器里装着上次的域(如 BI 看板)
    //              就永远不切; ② 不能传 {silent:true} —— loadDashboard 开头对 silent 有 guard
    //              (画布/货架预览态下直接 return) · 会静默什么都不做。
    // 用户主动点开 = 明确意图 · 走非 silent 正常切域 + 渲染。
    if (!(opts && opts.skipDomain)) {
      try { loadDashboard((opts && opts.domain) || 'reports'); } catch (e) { console.warn('compact lib:', e); }
    }
    _compactSlotDomain = (opts && opts.domain) || 'reports';
    wrap.dataset.slotDomain = _compactSlotDomain;   // 给 CSS 用: 哪个 seg 该转 180°
  } else {
    wrap.classList.remove('ca-lib-open');
    _compactSlotDomain = '';
    wrap.dataset.slotDomain = '';
    if (btn) btn.classList.remove('on');
    // BRO 2026-09-15: 收槽 = 带着画布一起收。不清的话 #detailPane 会带着画布挪回中栏 = "收起没把产物收起来"
    if (typeof stageClearQuiet === 'function') stageClearQuiet();
    if (_compactLibHome && _compactLibHome.parent) {
      try { _compactLibHome.parent.insertBefore(pane, _compactLibHome.next); }
      catch (e) { try { _compactLibHome.parent.appendChild(pane); } catch (e2) {} }
    }
    _compactLibHome = null;
    slot.hidden = true;
  }
  _syncCompactArtTabs();
  _followRail();   // ② 对话轨道跟着对话栏走 (用户: 产物库开合后轨道要落到对的位置)
  return open;
}

// 提问轨道 (.msg-rail) 是 fixed 定位 · 只在 window resize 时重算 → 右栏开合后必须手动喊一声
// 立即一次 + 340ms 后一次 (等右栏宽度过渡跑完 · 位置才算得准)
function _followRail() {
  const hit = function () { try { if (typeof _repositionRail === 'function') _repositionRail(); } catch (e) {} };
  hit();
  setTimeout(hit, 340);
}

// ── head 两个 tab (用户: 当前产物 / 产物库 「这俩应该是都有的 · 展开不同的抽屉」)
//   不是谁把谁挤没 —— 切 tab = 切视图, 两个入口永远都在。
function compactArtTab(view) {
  const a = document.getElementById('compactArtifacts');
  if (!a) return;
  if (view === 'lib') {
    toggleCompactLibrary(true, { domain: 'reports' });
    if (!a.classList.contains('open')) toggleCompactArtifacts();
  } else {
    toggleCompactLibrary(false);
    if (!a.classList.contains('open')) toggleCompactArtifacts();
  }
  _syncCompactArtTabs();
}
function _syncCompactArtTabs() {
  const a = document.getElementById('compactArtifacts');
  if (!a) return;
  const lib = a.classList.contains('ca-lib-open');
  const open = a.classList.contains('open');
  const proj = lib && _compactSlotDomain === 'projects';   // 槽里是「我的项目」不是产物库
  document.querySelectorAll('#compactArtTabs .ca-tab').forEach(function (t) {
    t.classList.toggle('is-on', (t.dataset.caview === 'lib') === (lib && !proj));
  });
  const title = document.getElementById('compactArtTitle');
  if (title) title.innerHTML = proj
    ? '<i class="ri-folders-fill"></i> 我的项目'
    : (lib
      ? '<i class="ri-archive-2-line"></i> 产物库'
      : '<i class="ri-archive-fill"></i> 当前产物');
  const segLib = document.querySelector('#compactArtToggle .cat-lib');
  const segArt = document.querySelector('#compactArtToggle .cat-art');
  const segProj = document.querySelector('#compactArtToggle .cat-proj');
  if (segLib) segLib.classList.toggle('is-on', lib && !proj);
  if (segArt) segArt.classList.toggle('is-on', open && !lib);
  if (segProj) segProj.classList.toggle('is-on', proj);
}

// 竖条上的「产物库」图标 (用户: 产物库入口放那个竖条上 · 不要藏在产物列表底下没人看得到)
// 开关同键: 第二次点 = 收起整个右栏 (用户 2026-09-15: 以前是跳回「当前产物」· 别扭)
function openCompactLibrary() {
  const a = document.getElementById('compactArtifacts');
  if (a && a.classList.contains('ca-lib-open') && _compactSlotDomain !== 'projects') { toggleCompactArtifacts(); return; }
  compactArtTab('lib');
}

// ── ③ 我的项目抽屉 (BRO 2026-09-21 「做第三个拉开抽屉的按钮」) ──
//   和产物库【同一条链同一样壳】：都是把 #detailPane 整个挪进 .cl-slot，
//   唯一区别是落位后切的域 (reports ↔ projects)。
//   ⚠ 不在竖条另起分栏/浮层 —— 那两套都被实测废弃过 (#6列分栏点开关即崩 / absolute
//     浮层 <1900 宽屏盖对话栏) · 此为 playbook 硬约束。
function openCompactProjects() {
  const a = document.getElementById('compactArtifacts');
  if (!a) return;
  // 开关同键: 已经开着项目槽 → 第二次点 = 收起整个右栏 (跟产物库同手感)
  if (a.classList.contains('ca-lib-open') && _compactSlotDomain === 'projects') {
    toggleCompactArtifacts();
    return;
  }
  if (!a.classList.contains('open')) toggleCompactArtifacts();   // 面板没撑开先撑开
  toggleCompactLibrary(true, { domain: 'projects' });
  _syncCompactArtTabs();
}

// ── ④ 产物库宽度拖拽 (用户: 拿不准就给用户 · 左缘一拖 · 双击复位自适应) ──
(function initCompactLibResize() {
  function wrapEl() { return document.getElementById('compactArtifacts'); }
  var _drag = null;
  function _restore() {
    var w = '';
    try { w = localStorage.getItem('opus_ca_lib_w') || ''; } catch (e) {}
    var a = wrapEl();
    if (a && w) { a.style.setProperty('--ca-lib-w', w); a.classList.add('ca-w-set'); }
  }
  if (document.body) _restore(); else document.addEventListener('DOMContentLoaded', _restore);
  document.addEventListener('mousedown', function (e) {
    var h = e.target && e.target.closest ? e.target.closest('#compactArtResize') : null;
    if (!h) return;
    var a = wrapEl(); if (!a) return;
    _drag = { startX: e.clientX, startW: a.getBoundingClientRect().width, h: h };
    a.classList.add('ca-resizing'); h.classList.add('dragging');
    document.body.style.userSelect = 'none';
    e.preventDefault();
  });
  document.addEventListener('mousemove', function (e) {
    if (!_drag) return;
    var a = wrapEl(); if (!a) return;
    var w = Math.round(_drag.startW + (_drag.startX - e.clientX));   // 往左拖 = 变宽
    var min = 360, max = Math.max(min, window.innerWidth - 700);   // 上限留够: 会话轨 240 + 竖条 44 + 对话栏 ≥416
    w = Math.max(min, Math.min(w, max));
    a.style.setProperty('--ca-lib-w', w + 'px');
    a.classList.add('ca-w-set');
  });
  document.addEventListener('mouseup', function () {
    if (!_drag) return;
    var a = wrapEl();
    if (a) {
      a.classList.remove('ca-resizing');
      try { localStorage.setItem('opus_ca_lib_w', a.style.getPropertyValue('--ca-lib-w') || ''); } catch (e) {}
      _followRail();
    }
    if (_drag.h) _drag.h.classList.remove('dragging');
    document.body.style.userSelect = '';
    _drag = null;
  });
  document.addEventListener('dblclick', function (e) {
    var h = e.target && e.target.closest ? e.target.closest('#compactArtResize') : null;
    if (!h) return;
    var a = wrapEl(); if (!a) return;
    a.classList.remove('ca-w-set');
    a.style.removeProperty('--ca-lib-w');
    try { localStorage.removeItem('opus_ca_lib_w'); } catch (e) {}
    _followRail();
  });
})();

// 退出专注版 → 产物库必须把中栏还回原位 (否则工作台没中栏)
if (document.body) {
  new MutationObserver(function () {
    if (!document.body.classList.contains('compact')) {
      const w = document.getElementById('compactArtifacts');
      if (w && w.classList.contains('ca-lib-open')) toggleCompactLibrary(false);
    }
  }).observe(document.body, { attributes: true, attributeFilter: ['class'] });
}


// ══════════════════ [2] 产物列表与预览 (工作台 / 专注版共用) ══════════════════

// ─── 卷八十一 · A 方案 · 本会话文档聚合视图 (聊天头 📄 按钮) ───
let _docsViewActive = false;

function toggleDocsView() {
  if (_docsViewActive) {
    closeDocsView();
  } else {
    openDocsView();
  }
}

function openDocsView() {
  if (!token) {
    addSys('⚠ 还没填 token —— 点右上角 ⚙ 设置');
    openSettings();
    return;
  }
  _docsViewActive = true;
  document.getElementById('chatDocsBtn').classList.add('active');
  const msgs = document.getElementById('messages');
  // 新会话无消息时 onboarding 引导卡是显示的 · 一并隐藏避免叠屏 (卷八十一 K3 施工单②)
  const ob = document.getElementById('onboardingPanel');
  if (ob && !ob.hidden) { ob.dataset.dvHidden = '1'; ob.hidden = true; }
  let dv = document.getElementById('docsView');
  if (!dv) {
    dv = document.createElement('div');
    dv.id = 'docsView';
    dv.className = 'docs-view';
    msgs.insertAdjacentElement('afterend', dv);
  }
  msgs.style.display = 'none';
  dv.style.display = 'flex';
  renderDocsView();
}

function closeDocsView() {
  _docsViewActive = false;
  document.getElementById('chatDocsBtn').classList.remove('active');
  const msgs = document.getElementById('messages');
  const dv = document.getElementById('docsView');
  if (msgs) msgs.style.display = '';
  if (dv) dv.style.display = 'none';
  const ob = document.getElementById('onboardingPanel');
  if (ob && ob.dataset.dvHidden === '1') { ob.hidden = false; delete ob.dataset.dvHidden; }
}

// 聚合本会话产物: 主数据源 = /sessions/{sid}/artifacts (后端扫主文件+归档 · 过滤占位符 · 验证存在)
// 同一条稿后端可能回多种 url 写法 (data/xxx 裸相对路径 · /presentations/xxx · /workshop/file/xxx)
// 打分: 高分 = 能直接给预览/下载端点用的形态 · 裸相对路径解析不出 domain/filename
function _urlScore(u) {
  u = String(u || '');
  if (u.startsWith('/workshop/file/') || u.startsWith('/workshop/preview/') || u.startsWith('/workshop/outputs/')) return 3;
  if (u.startsWith('/')) return 2;
  return 1;
}

// 从产物 url 反推工程内相对路径 (给 openStage 铺画布用) · 覆盖后端各种 url 写法
function _docRelFromUrl(url, domain, filename) {
  const u = String(url || '');
  if (u.startsWith('data/')) return u.split('?')[0];
  if (u.startsWith('/workshop/outputs/')) return 'data/workshop/outputs/' + u.slice('/workshop/outputs/'.length).split('?')[0];
  let m = u.match(/^\/workshop\/(?:file|preview)\/([^/]+)\/(.+?)(?:\?|$)/);
  if (m) return 'data/' + m[1] + '/' + m[2];
  m = u.match(/^\/([^/]+)\/(.+?)(?:\?|$)/);
  if (m && m[1] === 'attachments') return 'data/runtime/attachments/' + m[2];
  if (m && m[1] !== 'stage') return 'data/' + m[1] + '/' + m[2];
  if (domain && filename) return 'data/' + domain + '/' + filename;
  return '';
}

async function collectSessionDocs() {
  const docs = [];       // [{name, url, ext, kind}]
  const seen = new Set();
  const _keyMap = new Map();   // name::ext → docs 下标 (同稿多 url 写法时优选)

  // 1. 主数据源: 后端 artifacts 端点 (扫 session 主 jsonl + 归档 compact/prune 文件 · 压缩也不丢)
  try {
    if (sessionId) {
      const r = await fetch(`/sessions/${encodeURIComponent(sessionId)}/artifacts`, {
        headers: { 'Authorization': 'Bearer ' + token },
      });
      if (r.ok) {
        const data = await r.json();
        for (const a of (data.artifacts || [])) {
          if (!a || !a.url) continue;
          // 同一条稿可能以两种 url 写法回来 (/presentations/x.pptx 与
          // /workshop/preview/presentations/x.pptx) → 只按 url 去重会漏 → 面板里同名卡片两条。
          // 再按「文件名::扩展名」去一道(合并后保留先到的那条)。
          const _k = (a.name || a.url.split('/').pop() || '') + '::' + (a.ext || '');
          if (seen.has(a.url)) continue;
          const _sc = _urlScore(a.url);
          const _idx = _keyMap.get(_k);
          if (_idx === undefined) {
            _keyMap.set(_k, docs.length);
            seen.add(a.url);
            docs.push({ name: a.name || '产物', url: a.url, ext: a.ext || '', kind: 'workshop', _sc, mtime: a.mtime || 0 });
          } else if (_sc > (docs[_idx]._sc || 0)) {
            docs[_idx].url = a.url; docs[_idx]._sc = _sc;   // 高分 url 顶替 (治预览按钮传空)
          }
        }
      }
    }
  } catch (e) { console.warn('collectSessionDocs artifacts api:', e); }

  // 2. 兜底: DOM 扫描 (仅后端 artifacts 失败时才做 · 后端已扫主 jsonl+归档 · 正常不重复劳动)
  //    卷八十一续二: 原每次全扫 DOM 500+ turns 的 innerHTML 同步正则 → 阻塞主线程几秒
  //    (用户: 会话列表/产物都慢的隐藏根因) · 现仅在后端异常时兜底
  if (!docs.length) {
    try {
      const msgs = document.querySelectorAll('#messages .md-body, #messages .msg-text, #messages .assistant');
      msgs.forEach(m => {
        const html = m.innerHTML || '';
        const reDoc = /(?:href|src)="([^"]+\.(?:docx?|md|pdf|xlsx?|pptx?|txt|zip)(?:\?[^"]*)?)"/gi;
        let mm;
        while ((mm = reDoc.exec(html)) !== null) {
          const u = mm[1];
          if (seen.has(u)) continue;
          seen.add(u);
          docs.push({ name: _safeDecode(u.split('/').pop() || '产物'), url: u, ext: (u.match(/\.([a-z0-9]+)$/i) || [,''])[1].toLowerCase(), kind: 'workshop' });
        }
        const reMedia = /(?:href|src)="([^"]+\.(?:png|jpe?g|gif|webp|mp4|webm|wav|mp3)(?:\?[^"]*)?)"/gi;
        let mm2;
        while ((mm2 = reMedia.exec(html)) !== null) {
          const url = mm2[1];
          if (!url.includes('/workshop/') && !url.includes('/reports/')) continue;
          if (seen.has(url)) continue;
          seen.add(url);
          docs.push({ name: _safeDecode(url.split('/').pop() || '产物'), url, ext: (url.match(/\.([a-z0-9]+)$/i) || [,''])[1].toLowerCase(), kind: 'workshop' });
        }
      });
    } catch (e) { console.warn('collectSessionDocs dom scan:', e); }
  }

  return docs;
}

// Remix 图标映射 (卷八十一 · 铁律10: 不用 emoji 当图标)
const _DOC_ICON_MAP = {
  docx:'ri-file-word-2-fill', doc:'ri-file-word-2-fill',
  xlsx:'ri-file-excel-2-fill', xls:'ri-file-excel-2-fill',
  pptx:'ri-file-ppt-2-fill', ppt:'ri-file-ppt-2-fill',
  pdf:'ri-file-pdf-2-fill', md:'ri-markdown-fill',
  png:'ri-image-fill', jpg:'ri-image-fill', jpeg:'ri-image-fill', gif:'ri-image-fill', webp:'ri-image-fill',
  mp3:'ri-file-music-fill', wav:'ri-file-music-fill',
  mp4:'ri-file-video-fill', webm:'ri-file-video-fill',
};
function _docIcon(ext) { return `<i class="${_DOC_ICON_MAP[ext] || 'ri-file-fill'}"></i>`; }

// 分类组: 办公文档 / 文本·报告 / 图片 / 音频 / 视频
const _DOC_CATS = [
  { key:'office', label:'办公文档',   icon:'ri-briefcase-4-fill', exts:['docx','doc','xlsx','xls','pptx','ppt'] },
  { key:'text',   label:'文本 · 报告', icon:'ri-file-text-fill',   exts:['md','pdf'] },
  { key:'image',  label:'图片',       icon:'ri-image-fill',       exts:['png','jpg','jpeg','gif','webp'] },
  { key:'audio',  label:'音频',       icon:'ri-music-2-fill',     exts:['mp3','wav'] },
  { key:'video',  label:'视频',       icon:'ri-movie-fill',       exts:['mp4','webm'] },
];
// ── 排序 (BRO 2026-09-28「本话题产物要有排序功能」) ─────────────────────
//   排序状态放全局 · 「本话题产物」整页 (renderDocsView) 和专注版右栏面板
//   (renderCompactArtifacts) 共用同一个值 —— 一处切、两处一致（同一套代码）。
//   分类仍按 _DOC_CATS 分组展示 · 排序管的是**组内**顺序。
let _docSort = 'new';   // new(默认·新→旧) | old(旧→新) | name(名称)
const _DOC_SORTS = [
  { key: 'new',  label: '最新在前' },
  { key: 'old',  label: '最早在前' },
  { key: 'name', label: '按名称' },
];

function _docSortApply(list) {
  const arr = list.slice();
  if (_docSort === 'name') {
    arr.sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''), 'zh'));
  } else if (_docSort === 'old') {
    arr.sort((a, b) => (a.mtime || 0) - (b.mtime || 0));
  } else {
    arr.sort((a, b) => (b.mtime || 0) - (a.mtime || 0));
  }
  return arr;
}

// 排序控件 (两处渲染共用同一份 HTML · 不各写一套)
function _docSortBar() {
  const cur = _DOC_SORTS.find(s => s.key === _docSort) || _DOC_SORTS[0];
  return `<button class="doc-sort-btn" onclick="_docSortNext(event)" title="切换排序 · 现在：${cur.label}">`
       + `<i class="ri-sort-desc"></i> ${cur.label}</button>`;
}

// 循环切换 (一颗按钮转一圈 · 不占地方)
function _docSortNext(ev) {
  if (ev) { ev.stopPropagation(); ev.preventDefault(); }
  const i = _DOC_SORTS.findIndex(s => s.key === _docSort);
  _docSort = _DOC_SORTS[(i + 1) % _DOC_SORTS.length].key;
  // 两个视图谁开着刷谁 —— 都轻量 · 同时开也各自刷一次
  if (document.getElementById('docsViewBody')) { try { renderDocsView(); } catch (e) {} }
  if (document.getElementById('compactArtBody')) { try { renderCompactArtifacts(); } catch (e) {} }
}

function _docCategory(ext) {
  for (const c of _DOC_CATS) if (c.exts.includes(ext)) return c;
  return _DOC_CATS[1]; // 兜底进文本组
}

async function renderDocsView() {
  const dv = document.getElementById('docsView');
  if (!dv) return;
  dv.innerHTML = `
    <div class="docs-view-head">
      <span class="docs-view-title"><i class="ri-file-list-3-fill"></i> 本话题产物</span>
      <span class="docs-view-sub" id="docsViewSub">收集…</span>
      ${_docSortBar()}
      <button class="docs-view-close" onclick="closeDocsView()" title="返回对话"><i class="ri-arrow-left-line"></i> 返回对话</button>
    </div>
    <div class="docs-view-body" id="docsViewBody"><div class="docs-view-loading">扫描会话中的文档…</div></div>
  `;
  const docs = await collectSessionDocs();
  await _loadDocFavSet();          // ⭐ 先拿收藏集合 · 卡片才能一次渲对 (免得先渲未收藏再刷)
  const body = document.getElementById('docsViewBody');
  const sub = document.getElementById('docsViewSub');
  if (sub) sub.textContent = `${docs.length} 个文档`;
  if (!docs.length) {
    body.innerHTML = `<div class="docs-view-empty">
      <i class="ri-file-list-3-line" style="font-size:34px;opacity:.3"></i>
      <div>本话题还没有产出</div>
      <div class="docs-view-hint">生成报告 / 口播稿 / 周报后 · 文档会自动出现在这里</div>
    </div>`;
    return;
  }
  // 按类型分类: 办公文档 / 文本·报告 / 图片 / 音频 / 视频 · 组内按当前排序
  let html = '';
  for (const cat of _DOC_CATS) {
    const group = _docSortApply(docs.filter(d => _docCategory(d.ext).key === cat.key));
    if (!group.length) continue;
    html += `<div class="docs-sec-title"><i class="${cat.icon}"></i> ${cat.label} <span style="opacity:.6;font-weight:400">(${group.length})</span></div>`;
    html += group.map(d => _docCardHtml(d)).join('');
  }
  body.innerHTML = html;
  // 流式生成中打开可能扫不全 · 提示重开刷新
  if (typeof _streaming !== 'undefined' && _streaming && sub) {
    sub.textContent += ' · 生成中 · 完成后重开刷新';
  }
}

// 2026-08-11 F4 (墨言审查): decodeURIComponent 遇畸形 % 序列抛 URIError ·
// 统一安全包裹 (解码失败就返回原文) · 治"产物名含畸形 %"不崩页面
function _safeDecode(s) {
  try { return decodeURIComponent(s); } catch (e) { return s; }
}

// ── ⭐ 收藏 (wish-e16b1f52 · BRO 2026-09-18) ──
// 本话题产物 / 右侧产物面板 跟【产物库】共用一套收藏：
//   ref_id = _docRelFromUrl() 算出来的 data/<domain>/<file> —— 跟产物库的 open_path 同源。
//   同一份稿在两处点星 = 同一条收藏，不会变成两条。数据层还是那个 favorites.json。
let _docFavSet = null;   // Set<rel> · 只装 kind=output

async function _loadDocFavSet(force) {
  if (_docFavSet && !force) return _docFavSet;
  try {
    const r = await fetch('/dashboard/favorites', {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (r.ok) {
      const data = await r.json();
      _docFavSet = new Set(
        (data.items || []).filter(i => i.kind === 'output').map(i => i.ref_id)
      );
    }
  } catch (e) { console.warn('doc fav set:', e); }
  if (!_docFavSet) _docFavSet = new Set();
  return _docFavSet;
}

async function _docToggleFav(rel, name, btn) {
  if (!rel) return;
  const r = await _toggleFavorite('output', rel, name || '', '', 'toggle');
  if (!r) { if (typeof addSys === 'function') addSys('⚠ 收藏没存上 · 检查一下 token'); return; }
  const on = !!r.now_starred;
  _docFavSet = _docFavSet || new Set();
  if (on) _docFavSet.add(rel); else _docFavSet.delete(rel);
  if (btn) {
    btn.classList.toggle('on', on);
    btn.innerHTML = `<i class="ri-star-${on ? 'fill' : 'line'}"></i>`;
    btn.title = on
      ? '已收藏 · 再点取消（收藏夹里按分类找得到）'
      : '收藏这份 · 之后能在「收藏夹 → 我的产物」里按分类找回来';
  }
  // ⚠ 不写 addSys: 收藏是原地操作 · 星变色就够了。
  //   这条原是「怕你没看到反馈」加的 · 实际是刷屏 (BRO 2026-09-18 拍板去掉)
  // ── wish-1dc9c39d (2026-09-19): 但「列表不刷新」是另一码事 ──
  // BRO 原话:「这个很好很重要的文档,我关掉后又要很麻烦的去找」。实测: 点星当场
  // 变色、收藏夹页却还挂着旧列表 —— 因为这里只改了内存 set 与按钮, 没人通知那页。
  // 收口: 收藏夹页正开着 → 立刻重拉; 否则下次打开本来就会重新拉, 不用动。
  try {
    const dv = (typeof $dashView !== 'undefined') ? $dashView : document.getElementById('dashView');
    if (dv && dv.querySelector('.zone-seg') && typeof loadDashboard === 'function') {
      loadDashboard('favorites');
    }
  } catch (e) {}
}

function _docCardHtml(d) {
  const safeUrl = String(d.url || '#').replace(/"/g, '%22');
  // 从 URL 解析 domain/filename (给 preview/reveal 端点用)
  // 卷八十一 · outputs 产物是 /workshop/outputs/app_id/子路径/文件名 · 无 domain 语义 · 特判直链
  const isOutputs = safeUrl.startsWith('/workshop/outputs/');
  let domain = '', filename = '';
  if (isOutputs) {
    domain = 'outputs';
    filename = _safeDecode(safeUrl.slice('/workshop/outputs/'.length));
  } else {
    const m = safeUrl.match(/^\/(?:workshop\/(?:preview|file)\/|reports\/)?([^/]+)\/([^/?]+)/);
    domain = m ? m[1] : '';
    filename = m ? m[2] : '';
  }
  const rel = _docRelFromUrl(safeUrl, domain, filename);
  // ⭐ 收藏开关 · 只在能归一出相对路径时给 (归不出就不给星 · 不假装能收)
  const _isFav = !!(rel && _docFavSet && _docFavSet.has(rel));
  const favBtn = rel
    ? `<button class="dvi-btn dvi-fav${_isFav ? ' on' : ''}" onclick="event.stopPropagation();_docToggleFav('${jsStr(rel)}','${jsStr(d.name)}',this)" title="${_isFav ? '已收藏 · 再点取消（收藏夹里按分类找得到）' : '收藏这份 · 之后能在「收藏夹 → 我的产物」里按分类找回来'}"><i class="ri-star-${_isFav ? 'fill' : 'line'}"></i></button>`
    : '';
  const isPreviewable = ['md','txt','png','jpg','jpeg','gif','webp','mp3','wav','mp4','webm','pdf','html','htm','pptx','ppt','xlsx','xls','docx','doc'].includes(d.ext);
  // 能进画布批注的: 去掉音频 (画布不吃) · BRO 2026-09-15 拍板卡片加「查看 & 批注」
  const isAnnotatable = ['md','txt','png','jpg','jpeg','gif','webp','mp4','webm','pdf','html','htm','pptx','ppt','xlsx','xls','docx','doc'].includes(d.ext);
  const btn = (ic, label, fn, cls) => `<button class="dvi-btn ${cls}" onclick="event.stopPropagation();${fn}('${jsStr(domain)}','${jsStr(filename)}','${jsStr(d.ext)}','${jsStr(rel)}')" title="${escHtml(label)}"><i class="${ic}"></i><span>${label}</span></button>`;
  // 低频按钮 · 只留图标 (BRO 2026-09-18: 6 个带文字的按钮把标题挤没了)
  //   —— 「预览 / 查看&批注」是高频 · 留文字；其余三个收起来，title 悬停可看
  const icoBtn = (ic, label, fn) => btn(ic, label, fn, 'dvi-ico');
  return `<div class="docs-view-item" data-ext="${d.ext}" data-url="${safeUrl}" data-domain="${domain}" data-filename="${filename}">
    <span class="dvi-ic">${_docIcon(d.ext)}</span>
    <span class="dvi-body">
      <span class="dvi-name">${escHtml(d.name)}</span>
      <span class="dvi-meta">${String(d.ext).toUpperCase()} · ${_docCategory(d.ext).label}</span>
    </span>
    <span class="dvi-actions">
      ${favBtn}
      ${isPreviewable ? btn('ri-eye-line','预览','_docOpenInBrowser') : ''}
      ${isAnnotatable ? btn('ri-quill-pen-line','查看 & 批注','_docAnnotateFromCard') : ''}
      ${icoBtn('ri-mac-line','应用打开','_docOpenLocal')}
      ${icoBtn('ri-save-3-line','另存为','_docSaveAs')}
      ${icoBtn('ri-link-unlink','不挂本话题','_docUnbind')}
    </span>
  </div>`;
}

// 浏览器打开 → 统一弹框预览 (卷八十一续 · 用户 拍板: 复用知识库弹框骨架 · 不再新标签)
// md/txt → fetch preview 渲染 markdown; 图片/音频/视频/pdf → 弹框内嵌; docx/xlsx/pptx → 下载
async function _docOpenInBrowser(domain, filename, ext, relIn) {
  try {
    const rel = relIn || (domain === 'outputs'
      ? ('data/workshop/outputs/' + filename)
      : (domain === 'reports'
        ? ('data/reports/' + filename)
        : (domain === 'presentations'
          ? ('data/presentations/' + filename)
          : (domain === 'spreadsheets'
            ? ('data/spreadsheets/' + filename)
            : ''))));
    // 用户 2026-09-15: 专注版下不进画布 —— 中栏在专注版是 0 宽，画布抽屉又踩过 opacity 坑
    //   (打开后全透明 + 还在吃点击 = 「什么都不显示还点不了」)。专注版统一走中间弹框。
    const _inCompact = document.body.classList.contains('compact');
    if (!_inCompact && rel && typeof openStage === 'function' && openStage({ path: rel })) return;
    const t = token ? `?token=${encodeURIComponent(token)}` : '';
    const dispName = _safeDecode(filename.split('/').pop() || filename);
    if (domain === 'outputs') {
      // outputs 产物直链 (后端 /workshop/outputs/{path} 带 MIME)
      const url = `/workshop/outputs/${encodeURIComponent(filename)}${t}`;
      if (['md','txt'].includes(ext)) {
        const r = await fetch(url, { headers: { 'Authorization': 'Bearer ' + token } });
        if (!r.ok) throw new Error('预览拉取失败 ' + r.status);
        const text = await r.text();
        const bodyHtml = (typeof mdRender === 'function') ? mdRender(text) : ('<pre style="white-space:pre-wrap">' + escHtml(text) + '</pre>');
        _showPreviewModal({ title: dispName, metaLine: ext.toUpperCase() + ' · 工坊产物', bodyHtml });
      } else if (['png','jpg','jpeg','gif','webp'].includes(ext)) {
        _showPreviewModal({ title: dispName, metaLine: '图片', raw: true, openPath: rel, bodyHtml: `<img src="${url}" alt="${escHtml(dispName)}" class="pv-img">` });
      } else if (['mp3','wav'].includes(ext)) {
        _showPreviewModal({ title: dispName, metaLine: '音频', raw: true, bodyHtml: `<audio controls preload="metadata" src="${url}" class="pv-media" style="width:100%"></audio>` });
      } else if (['mp4','webm'].includes(ext)) {
        _showPreviewModal({ title: dispName, metaLine: '视频', raw: true, openPath: rel, bodyHtml: `<video controls preload="metadata" src="${url}" class="pv-media"></video>` });
      } else if (ext === 'pdf') {
        _showPreviewModal({ title: dispName, metaLine: 'PDF', raw: true, openPath: rel, bodyHtml: `<iframe src="${url}" class="pv-pdf"></iframe>` });
      } else if (ext === 'html') {
        // html 预览用 sandbox iframe · 禁脚本/弹窗 · 防恶意 html (卷八十一 产物 html 支持)
        _showPreviewModal({ title: dispName, metaLine: 'HTML · 工坊产物', raw: true, openPath: rel, bodyHtml: `<iframe src="${url}" class="pv-html" sandbox="allow-same-origin" loading="lazy"></iframe>` });
      } else {
        // docx/xlsx/pptx 浏览器不能内嵌 → 下载
        await _docSaveAs(domain, filename);
      }
      return;
    }
    if (['md','txt'].includes(ext)) {
      // reports 目录的 md 走 /reports/preview/{filename} · 其余走 /workshop/preview
      const previewUrl = domain === 'reports'
        ? `/reports/preview/${encodeURIComponent(filename)}${t}`
        : `/workshop/preview/${encodeURIComponent(domain)}/${encodeURIComponent(filename)}${t}`;
      const r = await fetch(previewUrl, { headers: { 'Authorization': 'Bearer ' + token } });
      if (!r.ok) throw new Error('预览拉取失败 ' + r.status);
      const data = await r.json();
      const text = data.markdown || '';
      const bodyHtml = (typeof mdRender === 'function') ? mdRender(text) : ('<pre style="white-space:pre-wrap">' + escHtml(text) + '</pre>');
      _showPreviewModal({ title: dispName, metaLine: ext.toUpperCase() + ' · ' + domain, bodyHtml, openPath: rel });
    } else if (['png','jpg','jpeg','gif','webp'].includes(ext)) {
      const url = domain === 'reports'
        ? `/reports/${encodeURIComponent(filename)}${t}`
        : `/workshop/file/${encodeURIComponent(domain)}/${encodeURIComponent(filename)}${t}`;
      _showPreviewModal({ title: dispName, metaLine: '图片', raw: true, bodyHtml: `<img src="${url}" alt="${escHtml(dispName)}" class="pv-img">` });
    } else if (['mp3','wav'].includes(ext)) {
      const url = domain === 'reports'
        ? `/reports/${encodeURIComponent(filename)}${t}`
        : `/workshop/file/${encodeURIComponent(domain)}/${encodeURIComponent(filename)}${t}`;
      _showPreviewModal({ title: dispName, metaLine: '音频', raw: true, bodyHtml: `<audio controls preload="metadata" src="${url}" class="pv-media" style="width:100%"></audio>` });
    } else if (['mp4','webm'].includes(ext)) {
      const url = domain === 'reports'
        ? `/reports/${encodeURIComponent(filename)}${t}`
        : `/workshop/file/${encodeURIComponent(domain)}/${encodeURIComponent(filename)}${t}`;
      _showPreviewModal({ title: dispName, metaLine: '视频', raw: true, bodyHtml: `<video controls preload="metadata" src="${url}" class="pv-media"></video>` });
    } else if (ext === 'pdf') {
      const url = domain === 'reports'
        ? `/reports/${encodeURIComponent(filename)}${t}`
        : `/workshop/file/${encodeURIComponent(domain)}/${encodeURIComponent(filename)}${t}`;
      _showPreviewModal({ title: dispName, metaLine: 'PDF', raw: true, bodyHtml: `<iframe src="${url}" class="pv-pdf"></iframe>` });
    } else if (ext === 'html') {
      // html 走 /stage/file/{rel} (inline) —— /workshop/file 带 Content-Disposition: attachment · iframe 里必空白 (BRO 2026-09-15)
      const url = rel
        ? ('/stage/file/' + rel.split('/').map(encodeURIComponent).join('/'))
        : (`/workshop/file/${encodeURIComponent(domain)}/${encodeURIComponent(filename)}${t}`);
      _showPreviewModal({ title: dispName, metaLine: 'HTML · ' + domain, raw: true, openPath: rel, bodyHtml: `<iframe src="${url}" class="pv-html" sandbox="allow-scripts" loading="lazy"></iframe>` });
    } else if (await _docOfficePreview(domain, filename, ext, rel)) {
      // docx/xlsx/pptx → 中间弹框 (用户 2026-09-15: 当前产物预览用回中间弹框 · 不进画布)
    } else {
      // 兜底: 预览不了就下载
      await _docSaveAs(domain, filename);
    }
  } catch (e) {
    alert('打开失败: ' + e.message);
  }
}

// office (pptx/xlsx/docx) 预览 → 中间弹框 (用户 2026-09-15: 当前产物用回中间弹框 · 不进画布)
//   pptx/xlsx → /shelf/preview/{kind}/ 的 HTML 塞 iframe (跟产物库同一套渲染)
//   docx → /reports/preview/ 的 markdown 源 (跟 md 一条路)
//   返回 false = 没弹框 · 调用方回退下载
// 用户 2026-09-15 · 弹框里的「查看 & 批注」: 关弹框 → 开产物库 → 该稿送进画布 (能圈字批注 / 加图)
//   专注版: 产物库在右栏浮出; 工作台: openStage 直接铺中栏
// 卡片按钮走 btn() 传 4 参 · 这里取回 rel 转发 (BRO 2026-09-15: 卡片上也要这个入口)
function _docAnnotateFromCard(domain, filename, ext, rel) {
  let r = rel || '';
  if (!r) {
    if (domain === 'outputs') r = 'data/workshop/outputs/' + filename;
    else if (domain === 'reports') r = 'data/reports/' + filename;
    else if (domain === 'presentations') r = 'data/presentations/' + filename;
    else if (domain === 'spreadsheets') r = 'data/spreadsheets/' + filename;
    else if (domain === 'design') r = 'data/design/' + filename;
  }
  if (r) _docOpenForAnnotate(r);
}
function _docOpenForAnnotate(rel) {
  try {
    // BRO 2026-09-15: 先垫「打开中」。不垫的话右栏/中栏会先露出旧域(常是 BI 看板) · 等 goOfficeHome
    //   一次 fetch 往返回来才换成预览 = "先跳 dashboard 再才产物栏"
    const pane0 = document.getElementById('detailPane');
    if (pane0) pane0.innerHTML = '<div class="dash-empty dk-ld dk-ld-sm"><div class="dk-ld-mark"><img src="/static/img/logo-mark.png" alt=""><i></i><i></i></div><div class="dk-ld-txt">打开中…</div></div>';
    // BRO 2026-09-15: ✕ 关画布 → 回产物库列表 (点批注的语境永远是"在挑稿")
    window._stageHomeHint = 'reports';
    if (document.body.classList.contains('compact') && typeof toggleCompactLibrary === 'function') {
      // skipDomain: 只把中栏挪进右栏槽 · 不切「产物库」域 —— 否则 loadDashboard('reports') 回来会盖掉刚铺好的画布
      toggleCompactLibrary(true, { skipDomain: true });
    }
    if (rel && typeof openStage === 'function') openStage({ path: rel, bind: true });
  } catch (e) { console.warn('annotate:', e); }
}

async function _docOfficePreview(domain, filename, ext, rel) {
  if (!['pptx', 'ppt', 'xlsx', 'xls', 'docx', 'doc'].includes(ext)) return false;
  const dispName = _safeDecode(String(filename).split('/').pop() || filename);
  const t = token ? `?token=${encodeURIComponent(token)}` : '';
  try {
    if (ext === 'docx' || ext === 'doc') {
      const r = await fetch(`/reports/preview/${encodeURIComponent(filename)}${t}`, {
        headers: { 'Authorization': 'Bearer ' + token },
      });
      if (!r.ok) return false;
      const data = await r.json();
      const text = data.markdown || '';
      const bodyHtml = (typeof mdRender === 'function') ? mdRender(text) : ('<pre style="white-space:pre-wrap">' + escHtml(text) + '</pre>');
      _showPreviewModal({ title: dispName, metaLine: ext.toUpperCase() + ' · ' + domain, openPath: rel, bodyHtml });
      return true;
    }
    const kind = (ext === 'xlsx' || ext === 'xls') ? 'sheets' : 'decks';
    // ① 本机 Office 渲成品 (跟产物库「成品预览」同一条链)
    try {
      const vr = await fetch(`/shelf/visual/${kind}/${encodeURIComponent(filename)}`, {
        headers: { 'Authorization': 'Bearer ' + token },
      });
      const vj = vr.ok ? await vr.json().catch(function () { return {}; }) : {};
      if (vj && vj.ok) {
        if ((vj.mode === 'pdf' || vj.mode === 'html') && (vj.pdf_url || vj.html_url)) {
          const u = (typeof withAuthToken === 'function') ? withAuthToken(vj.pdf_url || vj.html_url) : (vj.pdf_url || vj.html_url);
          _showPreviewModal({ title: dispName, metaLine: ext.toUpperCase() + ' · 成品预览', raw: true, openPath: rel, bodyHtml: `<iframe class="pv-pdf" src="${escHtml(u)}" title="成品预览"></iframe>` });
          return true;
        }
        const assets = vj.assets || [];
        if (assets.length) {
          const imgs = assets.map(function (a, n) {
            const au = (typeof withAuthToken === 'function') ? withAuthToken(a.url) : a.url;
            return `<div class="rp-thumb"><img alt="第 ${n + 1} 页" src="${escHtml(au)}"><span class="rp-thumb-n">${n + 1}</span></div>`;
          }).join('');
          _showPreviewModal({ title: dispName, metaLine: ext.toUpperCase() + ' · 成品预览 · ' + assets.length + ' 页', raw: true, openPath: rel, bodyHtml: `<div class="rp-slide-deck">${imgs}</div>` });
          return true;
        }
      }
    } catch (e) { console.warn('office visual:', e); }
    // ② 退文稿源 (markdown · 跟产物库同源)
    const mr = await fetch(`/shelf/preview/${kind}/${encodeURIComponent(filename)}${t}`, {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!mr.ok) return false;
    const md2 = await mr.json();
    if (!md2 || !md2.markdown) return false;
    _showPreviewModal({ title: dispName, metaLine: ext.toUpperCase() + ' · ' + domain + ' · 文稿源', openPath: rel, bodyHtml: (typeof mdRender === 'function') ? mdRender(md2.markdown) : ('<pre style="white-space:pre-wrap">' + escHtml(md2.markdown) + '</pre>') });
    return true;
  } catch (e) { console.warn('office preview:', e); return false; }
}

// 下载原始文件
// 另存为: 优先系统保存对话框 (showSaveFilePicker · 让用户选目录) · 不支持时回退浏览器下载
async function _docSaveAs(domain, filename) {
  try {
    const t = token ? `?token=${encodeURIComponent(token)}` : '';
    // outputs 产物直链下载 (后端 /workshop/outputs/{path} 已带全类型 MIME)
    let url;
    if (domain === 'outputs') {
      url = `/workshop/outputs/${encodeURIComponent(filename)}${t}`;
    } else if (domain === 'reports') {
      // reports 目录产物走 /reports/{filename} (download_report 端点)
      url = `/reports/${encodeURIComponent(filename)}${t}`;
    } else {
      url = `/workshop/file/${encodeURIComponent(domain)}/${encodeURIComponent(filename)}${t}`;
    }
    const r = await fetch(url, { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) throw new Error('获取失败 ' + r.status);
    const blob = await r.blob();
    const name = filename.split('/').pop() || filename;

    // 优先: 系统另存为对话框 (Chromium 系 Edge/Chrome 支持 · 本地 daemon 场景)
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
        // 用户取消 (AbortError) 静默返回 · 其它错误回退浏览器下载
        if (e && e.name === 'AbortError') return;
        console.warn('showSaveFilePicker fallback:', e);
      }
    }
    // 回退: 浏览器默认下载
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  } catch (e) {
    alert('另存为失败: ' + e.message);
  }
}

// wish-1518b97f · 「不挂本话题」——挂错的稿要能手动摘掉
async function _docUnbind(domain, filename, ext) {
  const rel = domain === 'outputs' ? ('data/workshop/outputs/' + filename) : ('data/' + domain + '/' + filename);
  const sid = (typeof sessionId !== 'undefined' && sessionId) || '';
  if (!sid) return;
  try {
    const r = await fetch('/sessions/' + encodeURIComponent(sid) + '/working-docs?path=' + encodeURIComponent(rel), {
      method: 'DELETE',
      headers: { 'Authorization': 'Bearer ' + token },
    });
    const d = await r.json().catch(function () { return {}; });
    if (!r.ok) throw new Error(d.detail || ('失败 ' + r.status));
    await renderDocsView();
  } catch (e) {
    alert('摘掉失败: ' + e.message);
  }
}

// 本机软件打开: 调 reveal 端点 → os.startfile
async function _docOpenLocal(domain, filename, ext) {
  try {
    const t = token ? `?token=${encodeURIComponent(token)}` : '';
    const r = await fetch(`/workshop/reveal/${encodeURIComponent(domain)}/${encodeURIComponent(filename)}${t}`, {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token },
    });
    const data = await r.json();
    if (!data.ok) throw new Error(data.error || '本机打开失败');
    addSys(`📄 已用本机软件打开 ${filename}`);
  } catch (e) {
    alert('本机打开失败: ' + e.message + ' · 仅本机可用');
  }
}
