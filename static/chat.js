/*
 * chat.js · Daemonkey 工作室 WebUI 行为脚本
 * 卷二十二 Day 2 · 从 chat.html 拆出来
 * build · 6d39286c483eab36e66a9d19de70ceb9
 *
 * 模块大致顺序：
 *   1. localStorage 状态 (token / sessionId / aliases)
 *   2. settings modal
 *   3. session drawer + 历史加载
 *   4. 消息渲染（addMsg / addSys / formatTime / scrollToBottom）
 *   5. SSE 流式发送（send + parseSseStream + handleStreamEvent）
 *   6. 工作室 view switching（sidebar / drawer 双向同步）
 *   7. dashboard 渲染（radar 卡片 / trends 卡片 / stub 占位）
 *   8. 入口启动（updateCurrentLabel + welcome + 自动拉历史）
 */

// === AI 名字本地化 (Daemonkey 分家) ===
// 用户在『相遇』里给这只 Daemonkey 起的名字·由后端注成 window.__AI_NAME__。
// 界面里历史遗留写死的 "Daemonkey" 全部换成它——一个集中机制·不必逐处改 100+ 串。
// 正则 /Daemonkey(?![\w-])/ 只换"Daemonkey"作为称呼出现的地方·跳过 DAEMONKEY_API_TOKEN / Daemonkey 这类技术标识。
(function () {
  var NAME = (window.__AI_NAME__ || '').trim();
  var OWNER = (window.__OWNER_NAME__ || '').trim();
  var doAI = NAME && NAME !== 'Daemonkey';           // AI 自己的名字
  var doOwner = OWNER && OWNER !== '用户';        // 主人的称呼 (UI 里的 用户 也换掉)
  if (!doAI && !doOwner) return;                // 母体两者都默认 → 保持原样
  // 正则跳过 DAEMONKEY_API_TOKEN / Daemonkey / OWNER-NOTEBOOK 这类技术标识·只换作为称呼出现的词
  var RE_AI = /Daemonkey(?![\w-])/g;
  var RE_OWNER = /\b用户(?![\w-])/g;
  // Daemonkey 分家: 取了自己名字的实例·把母体私有 lore「<名字> 的家」中性成「<名字> 的家」。
  // 前端 localizer 原本只换 Daemonkey/用户·「<名字> 的家」这类叙事得单独抹·否则纯净版界面会漏出来。
  var HOME = NAME ? (NAME + ' 的家') : '';
  function fix(s) {
    if (!s) return s;
    if (doAI && s.indexOf('Daemonkey') >= 0) s = s.replace(RE_AI, NAME);
    if (doOwner && s.indexOf('用户') >= 0) s = s.replace(RE_OWNER, OWNER);
    if (doAI && HOME && s.indexOf('<名字> 的家') >= 0) s = s.split('<名字> 的家').join(HOME);
    return s;
  }
  function _hit(v) { return v && ((doAI && (v.indexOf('Daemonkey') >= 0 || v.indexOf('<名字> 的家') >= 0)) || (doOwner && v.indexOf('用户') >= 0)); }
  function walk(root) {
    if (!root) return;
    try {
      var w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
      var n, batch = [];
      while ((n = w.nextNode())) { if (_hit(n.nodeValue)) batch.push(n); }
      for (var i = 0; i < batch.length; i++) batch[i].nodeValue = fix(batch[i].nodeValue);
    } catch (_) {}
    try {
      var els = root.querySelectorAll ? root.querySelectorAll('[title],[placeholder]') : [];
      for (var j = 0; j < els.length; j++) {
        var el = els[j];
        if (_hit(el.title)) el.title = fix(el.title);
        var ph = el.getAttribute && el.getAttribute('placeholder');
        if (_hit(ph)) el.setAttribute('placeholder', fix(ph));
      }
    } catch (_) {}
  }
  function run() {
    walk(document.body);
    // 浏览器标签页 title 跟 AI 名走 (用户 2026-08-06 · 搭档陪伴感):
    // chat.html <title> 默认纯名 (Daemonkey / Daemonkey) · 相遇取了名后 → "（名字） · 工作室" · 跟 WebUI 左上角一致
    try {
      if (doAI && NAME && document.title) {
        document.title = NAME + ' · 工作室';
      }
    } catch (_) {}
  }
  if (document.body) run(); else document.addEventListener('DOMContentLoaded', run);
  try {
    var mo = new MutationObserver(function (muts) {
      for (var i = 0; i < muts.length; i++) {
        var added = muts[i].addedNodes;
        for (var k = 0; k < added.length; k++) {
          var node = added[k];
          if (node.nodeType === 1) walk(node);
          else if (node.nodeType === 3 && _hit(node.nodeValue)) node.nodeValue = fix(node.nodeValue);
        }
      }
    });
    mo.observe(document.documentElement, { childList: true, subtree: true });
  } catch (_) {}
  window.AI_NAME = NAME;                        // 给后续代码直接用 (拼新串时优先用它)
})();

const STORAGE = {
  token: 'Daemonkey_ui_token',
  session: 'Daemonkey_ui_session',
  autoConfirm: 'Daemonkey_ui_auto_confirm',
  aliases: 'Daemonkey_ui_session_aliases',
};


// === 主题系统 · wish-7b89146f ===
const THEME_KEY = 'Daemonkey_ui_theme';
const THEME_CUSTOM_KEY = 'Daemonkey_ui_theme_custom';

// 卷七十二 v5 · 2026-06-10 · 用户 bug 报告: 「用户 让 Daemonkey 写代码时只要提到「默认」俩字 ·
//   就会直接换主题 · 而不是执行全句的需求」
// 病根: 「默认」是「暗紫」的 alias · matchThemePreset 看到「用默认值」就误命中
//      (`用` 满足 intent 模糊 regex · `默认` 命中 alias · 整句被 send 吞掉不发给 Daemonkey)
// 修法: ① 把「默认」「原来的」「恢复默认」「回到原来」这类语义太模糊的词从 alias 删掉
//       (用户 想恢复要说「换回暗紫主题」/「切回深色主题」)
//       ② intent regex 收紧 · 必须 (换/切/改/变/设/应用) + (主题/皮肤/外观/配色/界面) 两段配对
//       ③ 加 exact-match 兜底: 整句就是 alias 时直接命中 (短指令体验保留)
const THEME_PRESETS = [
  { cls: '',              label: '暗紫',   aliases: ['暗紫','暗紫主题','深色主题','深紫','夜间主题','暗黑主题'] },
  { cls: 'theme-classic', label: '经典灰', aliases: ['经典灰','经典主题','旧版主题','灰色主题'] },
  { cls: 'theme-light',   label: '白天',   aliases: ['白天主题','浅色主题','日间主题','明亮主题','亮色主题','白色主题'] },
  { cls: 'theme-sepia',   label: '护眼暖黄', aliases: ['护眼主题','暖黄主题','sepia','米黄主题','暖色主题'] },
  { cls: 'theme-ocean',   label: '海洋蓝',   aliases: ['海洋蓝','海蓝主题','蓝色主题','ocean','海洋主题'] },
  { cls: 'theme-forest',  label: '森林绿',   aliases: ['森林绿','绿色主题','森林主题','forest'] },
  { cls: 'theme-sunset',  label: '日落橙',   aliases: ['日落橙','橙色主题','日落主题','sunset','橘色主题'] },
  { cls: 'theme-pink',        label: '粉色',   aliases: ['粉色主题','粉红主题','pink 主题','樱花主题'] },
  { cls: 'theme-pink-white',  label: '粉白',   aliases: ['粉白','粉白主题','樱花白'] },
];

// "XX 模式" 短语 → 主题 label 映射 (用户 习惯说法 · 不进 alias 防误判)
const THEME_MODE_PHRASES = {
  '暗色': '暗紫', '深色': '暗紫', '夜间': '暗紫', '暗黑': '暗紫',
  '亮色': '白天', '浅色': '白天', '日间': '白天', '明亮': '白天', '白天': '白天',
  '护眼': '护眼暖黄',
};

function matchThemePreset(text) {
  const t = String(text || '').trim().toLowerCase();
  if (!t) return null;
  // ① 整句 exact match · trim 后 === alias 才命中 (而非 includes) · "暗紫" 这种纯短指令直接生效
  for (const p of THEME_PRESETS) {
    for (const a of p.aliases) { if (t === a.toLowerCase()) return p; }
  }
  // ② "XX 模式" 短语 → 主题 (用户 习惯 "用深色模式" / "白天模式" / "亮色模式")
  const modeMatch = t.match(/(暗色|深色|夜间|暗黑|亮色|浅色|日间|明亮|白天|护眼)\s*模式/);
  if (modeMatch) {
    const targetLabel = THEME_MODE_PHRASES[modeMatch[1]];
    const found = THEME_PRESETS.find(p => p.label === targetLabel);
    if (found) return found;
  }
  // ③ 短句兜底: ≤8 字 + 包含 alias · 给 "切海洋蓝" / "换暗紫主题" 这种短命令留口子
  //   这里安全是因为 alias 全是 ≥2 字的有色彩义词 ("暗紫" / "海洋蓝" / "粉白") · 不含 "默认" 这种模糊词
  if (t.length <= 8) {
    for (const p of THEME_PRESETS) {
      for (const a of p.aliases) { if (t.includes(a.toLowerCase())) return p; }
    }
  }
  // ④ 长句 · 必须有"切主题"强意图 (动词+名词配对) · 才允许 includes 匹配
  //   动词列表用 "用上" 而非 "用" 单字 · 否则 "用 X" 全部命中 (= 用户 bug)
  const hasStrongIntent =
    /(换|切|改|改成|变|变成|设|设为|应用|启用|用上)\s*(成|个|到|为|了)?\s*[^。.,，]{0,8}\s*(主题|皮肤|外观|配色|界面|ui)/i.test(t)
    || /(theme|skin)\s*(=|:|to|为)/i.test(t);
  if (!hasStrongIntent) return null;
  for (const p of THEME_PRESETS) {
    for (const a of p.aliases) { if (t.includes(a.toLowerCase())) return p; }
  }
  return null;
}

function applyTheme(cls, label) {
  document.body.classList.remove(...THEME_PRESETS.map(p=>p.cls).filter(Boolean));
  const cs = document.getElementById('theme-custom'); if (cs) cs.remove();
  if (cls) document.body.classList.add(cls);
  localStorage.setItem(THEME_KEY, cls||'dark');
  localStorage.setItem('Daemonkey_ui_theme_label', label||'深色');
  updateThemeDot();
}

function applyCustomTheme(vars, label) {
  document.body.classList.remove(...THEME_PRESETS.map(p=>p.cls).filter(Boolean));
  let s = document.getElementById('theme-custom');
  if (!s) { s = document.createElement('style'); s.id = 'theme-custom'; document.head.appendChild(s); }
  s.textContent = 'body { ' + Object.entries(vars).map(function(e){return e[0]+':'+e[1]+';'}).join('') + ' }';
  localStorage.setItem(THEME_KEY, 'custom');
  localStorage.setItem(THEME_CUSTOM_KEY, JSON.stringify(vars));
  localStorage.setItem('Daemonkey_ui_theme_label', label);
  updateThemeDot();
}

function initTheme() {
  const saved = localStorage.getItem(THEME_KEY) || 'dark';
  const label = localStorage.getItem('Daemonkey_ui_theme_label') || '深色';
  if (saved === 'custom') {
    try {
      const vars = JSON.parse(localStorage.getItem(THEME_CUSTOM_KEY)||'{}');
      if (Object.keys(vars).length) { applyCustomTheme(vars, label); return; }
    } catch(e) {}
    applyTheme('', '深色');
  } else {
    const p = THEME_PRESETS.find(function(x){return x.cls===saved;});
    applyTheme(saved||'', p?p.label:'深色');
  }
}

function updateThemeDot() {
  let dot = document.getElementById('themeDot');
  if (!dot) {
    dot = document.createElement('span');
    dot.id = 'themeDot';
    dot.title = '当前主题';
    var logo = document.querySelector('.header-logo');
    if (logo) logo.appendChild(dot);
  }
  try { dot.style.background = getComputedStyle(document.body).getPropertyValue('--Daemonkey').trim(); } catch(e) {}
}

// 在 send() 中拦截预设主题切换 · 返回 true=已拦截
function interceptThemeCommand(text) {
  const preset = matchThemePreset(text);
  if (preset) {
    applyTheme(preset.cls, preset.label);
    // 用 addSys 在当前 visible container 显示确认
    var c = $msgs;
    if (c) {
      var div = document.createElement('div');
      div.className = 'msg sys';
      div.textContent = '✓ 已切到「' + preset.label + '」' + (preset.cls ? '' : ' (默认深色)');
      c.appendChild(div);
      scrollToBottom(c, {force: true});
    }
    return true;
  }
  return false;
}

// 扫描 Daemonkey 消息中的自定义主题代码块 (```theme ... ```)
function scanThemeBlocks(container) {
  if (!container) return;
  var codes = container.querySelectorAll('code.lang-theme');
  codes.forEach(function(code) {
    try {
      var vars = JSON.parse(code.textContent.trim());
      if (vars && typeof vars === 'object' && Object.keys(vars).length >= 3) {
        var label = vars._label || '自定义';
        delete vars._label;
        applyCustomTheme(vars, label);
        var pre = code.parentElement;
        if (pre) {
          pre.outerHTML = '<div class="msg sys" style="margin-top:4px">✓ 已切到「' + label + '」</div>';
        }
      }
    } catch(e) {}
  });
}

// ═══ 卷七十五续九 · 换肤按钮 UI(接现成 applyTheme)+ 简洁版切换 ═══
// 换肤色板:每个 swatch 带对应主题 class · dots 用 var(--bg)/var(--Daemonkey) 取真实色(不硬编码·防漂移);
// 默认(暗紫·无 class)用 inline 兜底 · 因为它继承不到自身的默认变量。
function buildThemeGrid() {
  var grid = document.getElementById('themeGrid');
  if (!grid) return;
  var cur = localStorage.getItem(THEME_KEY) || 'dark';
  if (cur === 'dark') cur = '';
  grid.innerHTML = THEME_PRESETS.map(function (t) {
    var styleAttr = t.cls ? '' : ' style="--bg:#16131f;--Daemonkey:#b794f6"';
    var active = (t.cls === cur) ? ' active' : '';
    return '<button type="button" class="theme-swatch ' + t.cls + active + '" data-cls="' + t.cls + '"' + styleAttr + '>' +
             '<span class="swatch-dots"><span class="sw-bg"></span><span class="sw-op"></span></span>' +
             t.label +
           '</button>';
  }).join('');
  grid.querySelectorAll('.theme-swatch').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var cls = btn.dataset.cls || '';
      var p = THEME_PRESETS.find(function (x) { return x.cls === cls; });
      applyTheme(cls, p ? p.label : '深色');
      grid.querySelectorAll('.theme-swatch').forEach(function (s) {
        s.classList.toggle('active', s.dataset.cls === cls);
      });
    });
  });
}
function toggleThemePop(e) {
  if (e) e.stopPropagation();
  var pop = document.getElementById('themePop');
  if (!pop) return;
  if (pop.hidden) { buildThemeGrid(); pop.hidden = false; }
  else { pop.hidden = true; }
}
function toggleCompact(force, animate) {
  var on = (typeof force === 'boolean') ? force : !document.body.classList.contains('compact');
  // 切换那一下才挂过渡类(管左/中淡出淡入)· 动画结束移除 · 平时不影响拖 resizer
  if (animate !== false) {
    var layout = document.querySelector('.main-layout');
    if (layout) {
      layout.classList.add('layout-animating');
      clearTimeout(window._compactAnimT);
      window._compactAnimT = setTimeout(function () { layout.classList.remove('layout-animating'); }, 420);
    }
  }
  document.body.classList.toggle('compact', on);
  // rail 跟随布局: 切换模式会改变 #messages 面板位置 (专注版/工作台两套布局) ·
  // 必须重定位 rail 才不漂移 (用户 反馈: 切回工作台后轨道位置变了)
  // 立即重定一次 + 动画结束 (420ms) 后再定一次 · 覆盖瞬切和过渡态
  if (typeof _repositionRail === 'function') { try { _repositionRail(); } catch (e) {} }
  clearTimeout(window._compactRailT);
  window._compactRailT = setTimeout(function () {
    if (typeof _repositionRail === 'function') { try { _repositionRail(); } catch (e) {} }
  }, 430);
  // 卷八十三 · 简洁版三栏: 进入时挂载会话清单 + 产物面板 · 退出时收起
  _syncCompactSidebars(on);
  // 进入简洁版时给对话栏一个上浮淡入(掩盖布局瞬切·加载恢复态不放[animate=false])
  if (animate !== false && on) {
    var cp = document.querySelector('.chat-pane');
    if (cp) {
      cp.classList.remove('compact-enter');
      void cp.offsetWidth;               // 强制重排 · 让动画能重新触发
      cp.classList.add('compact-enter');
      clearTimeout(window._cpEnterT);
      window._cpEnterT = setTimeout(function () { cp.classList.remove('compact-enter'); }, 420);
    }
  }
  var icon = document.getElementById('compactIcon');
  var label = document.getElementById('compactLabel');
  var btn = document.getElementById('compactBtn');
  if (icon) icon.className = on ? 'ri-layout-masonry-line' : 'ri-focus-3-line';
  if (label) label.textContent = on ? '工作台' : '专注版';
  if (btn) btn.title = on ? '回工作台 (Alt+Z)' : '专注版 · 只留对话框 (Alt+Z)';
  localStorage.setItem('Daemonkey_ui_compact', on ? '1' : '');
}

/* ═══ 卷八十三 · 简洁版三栏 (用户 2026-08-14 拍板 · 会话清单左常驻 + 产物右折叠) ═══
   复用现成函数: buildSessionRow(会话行) / collectSessionDocs + _docCardHtml(产物卡) ·
   零新增后端 · 工作台模式(body 无 compact)三栏 display:none · 视觉零变化。 */
function _syncCompactSidebars(on) {
  const s = document.getElementById('compactSessions');
  const t = document.getElementById('compactArtToggle');
  const a = document.getElementById('compactArtifacts');
  if (!s || !t || !a) return;
  if (on) {
    s.hidden = false; t.hidden = false; a.hidden = false;
    renderCompactSessions();
    renderCompactArtifacts();
  } else {
    // 退出简洁版: 隐藏三栏 + 收起产物面板(下次进入干净)
    s.hidden = true; t.hidden = true; a.hidden = true;
    a.classList.remove('open');
    t.classList.remove('opened');
  }
}

// 左侧会话清单 (复用 /sessions API + buildSessionRow · 与抽屉同源 · 排序交给服务端 mtime desc)
let _compactSessionOffset = 0;
let _compactShowArchived = false;   // 专注版归档视图开关 (跟工作台抽屉的 showArchivedSessions 各自独立)
let _compactLastGroupKey = null;   // 分页续接时上一页最后的组 key · 跨页不重复插分组标题
const _COMPACT_PAGE = 30;
async function renderCompactSessions(reset = true) {
  const list = document.getElementById('compactSessionList');
  if (!list) return;
  if (!token) { list.innerHTML = '<div class="docs-view-empty">还没填 token</div>'; return; }
  // 无快照缓存 · 直接拉最新 (排序实时性 > 加载微快) · 保留旧 DOM 顶住不闪 loading
  if (reset) _compactSessionOffset = 0;
  try {
    const params = new URLSearchParams({ api_only: 'true', limit: String(_COMPACT_PAGE), offset: String(_compactSessionOffset) });
    if (_compactShowArchived) params.set('archived_only', 'true');
    else params.set('include_archived', 'false');
    const r = await fetch('/sessions?' + params.toString(), { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) { if (reset) list.innerHTML = '<div class="docs-view-empty">加载失败 [' + r.status + ']</div>'; return; }
    const data = await r.json();
    // 同步 meta 缓存 (label / pinned / archived)
    for (const s of (data.sessions || [])) {
      sessionMetaCache[s.session_id] = {
        label: s.label || null,
        pinned_at: s.pinned_at || null,
        archived_at: s.archived_at || null,
        last_model_cfg: s.last_model_cfg || null,
      };
    }
    if (reset) { list.innerHTML = ''; _compactLastGroupKey = null; }
    // 分组渲染 (今天/昨天/本周/本月/更早) · 分页续接时沿用上一页的组 key · 跨页不重复插标题
    let gk = _compactLastGroupKey;
    for (const s of data.sessions) gk = _appendSessionGrouped(list, s, gk);
    _compactLastGroupKey = gk;
    _renderCompactFoot(list, data.sessions);
    _startSessionRunPoll();  // 运行状态轮询 · 专注版列表可见即启动 (也会顺带重排)
  } catch (e) {
    if (reset) list.innerHTML = '<div class="docs-view-empty">网络出错: ' + e.message + '</div>';
  }
}
function loadMoreCompactSessions() { _compactSessionOffset += _COMPACT_PAGE; renderCompactSessions(false); }
// 专注版归档视图切换 (用户: 工作台有归档入口 · 专注版也该有)
function toggleCompactArchived() {
  _compactShowArchived = !_compactShowArchived;
  renderCompactSessions(true);
}
// 会话运行状态轮询 · wish-xxx · 5s 一次轻拉 /sessions · 只 toggle .session-running + .sp-run 图标
// 不重建列表 (不闪 / 不丢滚动位置) · 专注版 + 工作台抽屉共用 .session-item[data-sid] → 一处轮询两处受益
let _sessionRunPollTimer = null;
const _SESSION_RUN_POLL_MS = 5000;
function _startSessionRunPoll() {
  if (_sessionRunPollTimer) return;
  _sessionRunPollTimer = setInterval(_refreshSessionRunningStates, _SESSION_RUN_POLL_MS);
  _refreshSessionRunningStates();  // 立即刷一次
}
async function _refreshSessionRunningStates() {
  if (!token || document.hidden) return;   // 没 token / 标签页不可见 → 不刷
  try {
    const r = await fetch('/sessions?api_only=true&limit=50', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) return;
    const data = await r.json();
    const activeSet = new Set((data.sessions || []).filter(s => s.active).map(s => s.session_id));
    const order = (data.sessions || []).map(s => s.session_id);   // 服务端已按 mtime desc 排好
    // 同步 meta 缓存 (label / pinned 变化时 buildSessionRow 重渲才拿得到)
    for (const s of (data.sessions || [])) {
      sessionMetaCache[s.session_id] = {
        label: s.label || null,
        pinned_at: s.pinned_at || null,
        archived_at: s.archived_at || null,
        last_model_cfg: s.last_model_cfg || null,
      };
    }
    // 专注版列表: 按服务端最新顺序重排 (复用后端排序 · 不另写排序逻辑)
    const compactList = document.getElementById('compactSessionList');
    if (compactList && !compactList.hidden) {
      const bySid = {};
      compactList.querySelectorAll('.session-item[data-sid]').forEach(el => { bySid[el.dataset.sid] = el; });
      // 分组标题跟随: 记录每个 item 之前最近的 .session-group-header ·
      // 重排时标题跟着组内第一个 item 走 · 不留在原地 (否则 5s 轮询把分组结构打乱)
      const headerForSid = {};
      const headerNodes = [];
      let curHeader = null;
      for (const c of compactList.children) {
        if (c.classList && c.classList.contains('session-group-header')) { curHeader = c; headerNodes.push(c); }
        else if (c.classList && c.classList.contains('session-item')) { headerForSid[c.dataset.sid] = curHeader; }
      }
      // 已加载的节点按 order 重排 · 没加载的不动 (分页加载时)
      const frag = document.createDocumentFragment();
      let lastHeader = null;
      for (const sid of order) {
        if (!bySid[sid]) continue;
        const hdr = headerForSid[sid];
        if (hdr && hdr !== lastHeader) { frag.appendChild(hdr); lastHeader = hdr; }
        frag.appendChild(bySid[sid]);
      }
      compactList.appendChild(frag);  // appendChild 已存在的节点 = 移动到末尾 · 按 order 序完成重排
    }
    document.querySelectorAll('.session-item[data-sid]').forEach(el => {
      const isRun = activeSet.has(el.dataset.sid);
      el.classList.toggle('session-running', isRun);
      const nameEl = el.querySelector('.session-name');
      if (!nameEl) return;
      let runIcon = nameEl.querySelector('.sp-run');
      if (isRun && !runIcon) {
        runIcon = document.createElement('span');
        runIcon.className = 'sp-run';
        runIcon.title = '正在运行';
        runIcon.innerHTML = '<i class="ri-loader-4-line spin"></i>';
        nameEl.insertBefore(runIcon, nameEl.querySelector('.sp-label'));
      } else if (!isRun && runIcon) {
        runIcon.remove();
      }
    });
  } catch (e) { /* 静默 · 下轮再试 */ }
}

// 列表尾部: 归档 toggle + 有更多才显示"加载更早" · 按钮统一 btn-ghost (铁律 10) · 居中
function _renderCompactFoot(list, sessions) {
  const foot = document.getElementById('compactSessionsFoot');
  if (!foot) return;
  const hasMore = sessions && sessions.length >= _COMPACT_PAGE;
  const archBtn = _compactShowArchived
    ? '<button class="compact-foot-more" onclick="toggleCompactArchived()"><i class="ri-arrow-left-line"></i> 返回会话列表</button>'
    : '<button class="compact-foot-more" onclick="toggleCompactArchived()"><i class="ri-archive-line"></i> 查看已归档</button>';
  const moreBtn = hasMore ? '<button class="compact-foot-more" onclick="loadMoreCompactSessions()">加载更早的会话</button>' : '';
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
    if (sub) sub.textContent = docs.length ? `${docs.length} 项` : '';
    if (!docs.length) {
      body.innerHTML = `<div class="docs-view-empty">
        <i class="ri-file-list-3-line"></i>
        <div>本会话还没有产出</div>
      </div>`;
      return;
    }
    let html = '';
    for (const cat of _DOC_CATS) {
      const group = docs.filter(d => _docCategory(d.ext).key === cat.key);
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
}
// 点面板外 → 关换肤弹层
document.addEventListener('click', function (e) {
  if (!e.target.closest('.theme-menu')) {
    var pop = document.getElementById('themePop');
    if (pop && !pop.hidden) pop.hidden = true;
  }
});
// Alt+Z → 简洁版切换(Alt+B 已被左导航占用·此处不冲突)
document.addEventListener('keydown', function (e) {
  if (e.altKey && (e.key === 'z' || e.key === 'Z')) { e.preventDefault(); toggleCompact(); }
});

// 页面加载时初始化主题
// token 必须先于简洁版恢复初始化 —— 否则简洁版刷新时 _go()→renderCompactSessions
// 访问到 TDZ 里的 token 抛 ReferenceError · 列表静默空白 (用户 2026-08-14 会话列表空白根因)
let token = localStorage.getItem(STORAGE.token) || '';
initTheme();
// 换肤色板预建 + 恢复上次的简洁版状态
(function initCompactAndThemeUI() {
  function _go() {
    buildThemeGrid();
    if (localStorage.getItem('Daemonkey_ui_compact') === '1') toggleCompact(true, false);
  }
  if (document.getElementById('compactBtn')) _go();
  else document.addEventListener('DOMContentLoaded', _go, { once: true });
})();
let sessionId = localStorage.getItem(STORAGE.session) || '';
let autoConfirm = localStorage.getItem(STORAGE.autoConfirm) || 'confirm';
// 卷六十 · 主动 CALL 收件箱游标 · 初始化为本次开页时刻 · 只提示开页后 Daemonkey 主动开口的消息 (不回放历史)
let _proactiveLastSeen = new Date().toISOString();
// pending = 当前 visible session 的状态·切换 session 时从对应 state 里读
// (是 _sessions[sessionId].pending 的 visible mirror)
let pending = false;

// === wish-3fef4bc7 · 真并行多对话 UI ===
//
// 核心设计: 每个 active session 持有独立 state (含自己的 fetch / abort / streaming bubbles / DOM container)
// 切对话只切 visibility · 不杀 stream · 后台 SSE 继续跑 · 完成时 tab 红点提示
//
// _sessions: { [sid]: SessionState } · 全部 active sessions 的 state
// activeSession() = _sessions[sessionId] · 当前 visible 的
// _newSessionState(sid) · 工厂 · 创建一个空 state
// _getOrCreateSession(sid) · 取或建 state · 自动管 DOM container
//
// 跟旧代码兼容: 旧的全局变量 (pending / currentTurnId / currentAbortController) 仍然存在 ·
// 但变成 active session 的 mirror · 切换时 from/to state 同步。 这样老代码不破·新代码用 state。
const _sessions = {};

function _newSessionState(sid) {
  return {
    sessionId: sid,                  // 真 sid 或临时 cid (tmp-xxx)
    pending: false,
    currentTurnId: null,
    currentAbortController: null,
    currentStreamingReasoning: null,
    currentStreamingAssistant: null,
    assistantBubbles: [],
    sawAssistantText: false,
    finalUsage: null,
    finalSessionId: null,
    finalModel: null,
    errorShown: false,
    lastFinishReason: null,
    autoResumeCount: 0,
    streamHadToolCall: false,
    toolCallCount: 0,
    lastDashboardRefreshAt: 0,
    toolStartedAt: 0,
    // DOM · 每个 session 独立 messages container · 切换只 hide/show
    $container: null,
    // tab 状态
    hasUnreadCompletion: false,      // 后台跑完了没看 → tab 红点
    inputDraft: '',                  // 切对话时保存输入框草稿
    title: null,                     // tab 显示的别名缓存
    progressText: '',                // 切对话时保存底部 progress bar 文字
  };
}

// 取或建 session state · 不创建 DOM container (那个由 _getOrCreateContainer 单独管)
function _getOrCreateSession(sid) {
  if (!sid) return null;
  if (!_sessions[sid]) {
    _sessions[sid] = _newSessionState(sid);
  }
  return _sessions[sid];
}

// 当前 visible session 的 state (sessionId 全局是 source of truth)
function activeSession() {
  if (!sessionId) return null;
  return _sessions[sessionId] || null;
}

// 客户端临时 cid 分配 · 给"新对话还没收到 hello" 的状态用
// hello 事件来后 swap 真 sid (移 _sessions[tmp-xxx] → _sessions[api-xxx])
let _cidCounter = 0;
function _allocCid() {
  _cidCounter += 1;
  return 'tmp-' + Date.now().toString(36) + '-' + _cidCounter.toString(36);
}

// hello 事件来时 · 把 _sessions[oldSid] swap 到 _sessions[newSid]
// 同时如果 oldSid 是 sessionId · 把 sessionId 也更新成 newSid
function _swapSessionId(oldSid, newSid) {
  if (!oldSid || !newSid || oldSid === newSid) return;
  if (!_sessions[oldSid]) return;
  // 移 state · 更新里面的 sessionId 字段
  const s = _sessions[oldSid];
  s.sessionId = newSid;
  _sessions[newSid] = s;
  delete _sessions[oldSid];
  // 如果当前 active 是被 swap 的那个 · 同步 sessionId 全局
  if (sessionId === oldSid) {
    sessionId = newSid;
  }
  // DOM container 改 data-sid + 通知 tab UI
  if (s.$container) {
    s.$container.dataset.sid = newSid;
  }
  if (typeof _renderTabBar === 'function') {
    try { _renderTabBar(); } catch {}
  }
}

let sessionAliases = {};
try {
  sessionAliases = JSON.parse(localStorage.getItem(STORAGE.aliases) || '{}');
} catch { sessionAliases = {}; }

function saveAliases() {
  try { localStorage.setItem(STORAGE.aliases, JSON.stringify(sessionAliases)); }
  catch {}
}

// 卷三十四补丁 · session meta 缓存 · 服务端 label 优先于 localStorage 别名
let sessionMetaCache = {};
let showArchivedSessions = false;
let archivedCount = 0;
// 拉过一次服务端 label 的 sid · 防没 label 的老会话每次渲染重复请求 (断死循环)
const _metaTried = new Set();

function aliasFor(sid) {
  if (!sid) return '新对话';
  // 优先级：服务端 label → localStorage 别名 → api-…xxxxxx
  const serverMeta = sessionMetaCache[sid];
  if (serverMeta && serverMeta.label) return serverMeta.label;
  if (sessionAliases[sid]) return sessionAliases[sid];
  return 'api-…' + sid.slice(-6);
}

// wish-3fef4bc7 · DOM 容器化
// $messagesPanel = #messages 容器外壳 (chat.html 里的 <div id="messages">)
// $msgs = 当前 visible session 的 .session-msgs container · 切换 session 时重新指
// 旧代码 $msgs.appendChild / innerHTML / scrollTop 全部继续工作 (操作的是 visible session 的内容)
const $messagesPanel = document.getElementById('messages');
let $msgs = null;  // 切换 session 时由 _setActiveContainer 重新赋值

// 创建/取一个 session 专属的 messages container · 放进 panel
// 不切换 visibility · 只创建 (visibility 由 _setActiveContainer 控)
function _getOrCreateContainer(sid) {
  if (!sid) return null;
  let c = $messagesPanel.querySelector(`.session-msgs[data-sid="${CSS.escape(sid)}"]`);
  if (!c) {
    c = document.createElement('div');
    c.className = 'session-msgs';
    c.dataset.sid = sid;
    c.hidden = true;
    $messagesPanel.appendChild(c);
    // 同步进 state · 让 state.$container 指向这个 div
    const s = _getOrCreateSession(sid);
    if (s) s.$container = c;
  }
  return c;
}

// 切 visible · 把 $msgs 指向新 active session 的 container · 其他 hide
// 注意: 后台跑的 session 的 container 仍然存在 · 只是 hidden · 它们的 stream 仍在写 DOM
function _setActiveContainer(sid) {
  // hide 全部 session-msgs
  for (const child of Array.from($messagesPanel.children)) {
    if (child.classList && child.classList.contains('session-msgs')) {
      child.hidden = true;
    }
  }
  if (!sid) {
    $msgs = null;  // 没 active session · 老代码会 noop (用 if ($msgs) 包一下保护)
    return null;
  }
  const c = _getOrCreateContainer(sid);
  c.hidden = false;
  $msgs = c;
  return c;
}
const $input = document.getElementById('input');
const $send = document.getElementById('send');
// 卷三十八 · stop 已合并进 send · 用户 反馈"两个按钮丑" · 一个按钮两种状态
const $stop = null;
// wish-4a6331b2 · 图片附件
const $attachBtn = document.getElementById('attachBtn');
const $attachFile = document.getElementById('attachFile');
const $attachmentPreviews = document.getElementById('attachmentPreviews');
const _attachments = [];  // [{name, data_url}]

// wish-41ed72ef · 文档附件常量
const _IMG_MIMES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/bmp'];
const _DOC_MIMES = [
  'text/plain', 'text/markdown', 'text/csv', 'text/html',
  'application/json',
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  // wish-xxx · 附件类型扩展 (用户 2026-08-15) · 压缩包 + 表格 + 补丁 · 微信/管理器拖拽可用
  'application/zip', 'application/x-rar-compressed', 'application/x-7z-compressed',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.ms-excel',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.macroEnabled',
  'application/x-tar', 'application/gzip',
  'text/x-diff', 'text/x-patch',  // .diff/.patch (龙头 0025 · 常用补丁文件)
];
const _DOC_ICONS = {
  'application/pdf': 'ri-file-pdf-2-line',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'ri-file-word-2-line',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'ri-file-ppt-2-line',
  'text/plain': 'ri-file-text-line',
  'text/markdown': 'ri-file-text-line',
  'text/csv': 'ri-file-text-line',
  'text/html': 'ri-file-text-line',
  'application/json': 'ri-file-code-line',
  // wish-xxx · 附件扩展 (用户 2026-08-15)
  'application/zip': 'ri-file-zip-line',
  'application/x-rar-compressed': 'ri-file-zip-line',
  'application/x-7z-compressed': 'ri-file-zip-line',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'ri-file-excel-2-line',
  'application/vnd.ms-excel': 'ri-file-excel-2-line',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.macroEnabled': 'ri-file-excel-2-line',
  'application/x-tar': 'ri-file-zip-line',
  'application/gzip': 'ri-file-zip-line',
  'text/x-diff': 'ri-file-code-line',
  'text/x-patch': 'ri-file-code-line',
};

// wish-41ed72ef · MIME fallback · 有些浏览器/OS 不给 file.type
function _guessMime(file) {
  if (file.type && (file.type.startsWith('image/') || _DOC_MIMES.includes(file.type))) return file.type;
  const ext = (file.name || '').split('.').pop().toLowerCase();
  const map = {
    'txt':'text/plain','md':'text/markdown','csv':'text/csv','html':'text/html',
    'json':'application/json','pdf':'application/pdf',
    'docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'pptx':'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    // wish-xxx · 附件扩展 (用户 2026-08-15)
    'zip':'application/zip','rar':'application/x-rar-compressed','7z':'application/x-7z-compressed',
    'xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'xls':'application/vnd.ms-excel',
    'xlsm':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.macroEnabled',
    'tar':'application/x-tar','gz':'application/gzip',
    'diff':'text/x-diff','patch':'text/x-patch',
    'png':'image/png','jpg':'image/jpeg','jpeg':'image/jpeg',
    'gif':'image/gif','webp':'image/webp','bmp':'image/bmp',
  };
  return map[ext] || '';
}

// wish-41ed72ef · base64 data_url 估算文件大小
function _estSize(dataUrl) {
  if (!dataUrl) return '';
  const kb = Math.round(dataUrl.length * 0.75 / 1024);
  return kb >= 1024 ? (kb/1024).toFixed(1) + 'MB' : kb + 'KB';
}


// 清除所有附件
function clearAttachments() {
  _attachments.length = 0;
  $attachmentPreviews.innerHTML = '';
  $attachmentPreviews.hidden = true;
}

// 移除单个附件
function removeAttachment(i) {
  if (i >= 0 && i < _attachments.length) {
    _attachments.splice(i, 1);
    renderAttachments();
  }
}

// wish-41ed72ef · 渲染附件预览 · 图片缩略图 + 文档卡片
function renderAttachments() {
  $attachmentPreviews.innerHTML = '';
  if (_attachments.length === 0) {
    $attachmentPreviews.hidden = true;
    return;
  }
  $attachmentPreviews.hidden = false;
  for (let i = 0; i < _attachments.length; i++) {
    const att = _attachments[i];
    if (att.type === 'file') {
      // ── 文档卡片 ──
      const div = document.createElement('div');
      div.className = 'attach-doc-card';
      const iconName = _DOC_ICONS[att.mime] || 'ri-file-3-line';
      const name = (att.name || 'file').length > 20 ? (att.name || 'file').slice(0, 18) + '…' : (att.name || 'file');
      div.innerHTML = '<i class="' + iconName + '"></i><span class="doc-name">' + name + '</span><span class="doc-size">' + _estSize(att.data_url) + '</span>';
      const rm = document.createElement('button');
      rm.className = 'remove-btn';
      rm.textContent = '×';
      rm.title = '移除';
      rm.onclick = () => removeAttachment(i);
      div.appendChild(rm);
      $attachmentPreviews.appendChild(div);
    } else {
      // ── 图片缩略图 (现有) ──
      const div = document.createElement('div');
      div.className = 'attach-preview';
      const img = document.createElement('img');
      img.src = att.data_url;
      img.alt = att.name;
      const rm = document.createElement('button');
      rm.className = 'remove-btn';
      rm.textContent = '×';
      rm.title = '移除';
      rm.onclick = () => removeAttachment(i);
      div.appendChild(img);
      div.appendChild(rm);
      $attachmentPreviews.appendChild(div);
    }
  }
}

// 待处理的附件 promises · send() 等它们全 resolve 再发
const _attachmentPromises = [];

// wish-41ed72ef · 统一附件入口 · 图片 + 文档
function addAttachment(file) {
  const mime = _guessMime(file);
  if (!mime) { alert('不支持的文件类型: ' + (file.name || '未知')); return Promise.resolve(); }
  
  // ── 图片 → 现有流程 (缩略图 + 压缩) ──
  if (_IMG_MIMES.includes(mime)) {
    const p = new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = () => {
        let dataUrl = reader.result;
        const img = new Image();
        img.onload = () => {
          if (img.width > 2560) {
            const ratio = 2560 / img.width;
            const canvas = document.createElement('canvas');
            canvas.width = 2560;
            canvas.height = Math.round(img.height * ratio);
            canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
            dataUrl = canvas.toDataURL(mime, 0.85);
          }
          _attachments.push({ name: file.name || 'image.png', data_url: dataUrl, mime: mime, type: 'image' });
          renderAttachments();
          resolve();
        };
        img.onerror = resolve;
        img.src = dataUrl;
      };
      reader.onerror = resolve;
      reader.readAsDataURL(file);
    });
    _attachmentPromises.push(p);
    return p;
  }
  
  // ── 文档 → base64 直读 (不压缩) · 50MB 上限 (zip/xlsx 常超旧 10MB)
  if (_DOC_MIMES.includes(mime)) {
    if (file.size > 50 * 1024 * 1024) { alert('文件太大 · 上限 50MB'); return Promise.resolve(); }
    const p = new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = () => {
        _attachments.push({ name: file.name, data_url: reader.result, mime: mime, type: 'file' });
        renderAttachments();
        resolve();
      };
      reader.onerror = resolve;
      reader.readAsDataURL(file);
    });
    _attachmentPromises.push(p);
    return p;
  }
  
  alert('不支持的文件类型: ' + mime);
  return Promise.resolve();
}

// 附件事件绑定
if ($attachBtn && $attachFile) {
  $attachBtn.addEventListener('click', () => $attachFile.click());
  $attachFile.addEventListener('change', () => {
    for (const f of $attachFile.files) addAttachment(f);
    $attachFile.value = '';
  });
}

// wish-41ed72ef · 拖拽上传
{
  const $inputBar = document.querySelector('.input-bar');
  if ($inputBar) {
    let _dragCounter = 0;
    $inputBar.addEventListener('dragenter', e => { e.preventDefault(); e.stopPropagation(); _dragCounter++; $inputBar.classList.add('drag-over'); });
    $inputBar.addEventListener('dragleave', e => { e.preventDefault(); e.stopPropagation(); _dragCounter--; if (_dragCounter <= 0) { _dragCounter = 0; $inputBar.classList.remove('drag-over'); } });
    $inputBar.addEventListener('dragover', e => { e.preventDefault(); e.stopPropagation(); });
    $inputBar.addEventListener('drop', e => {
      e.preventDefault(); e.stopPropagation();
      _dragCounter = 0;
      $inputBar.classList.remove('drag-over');
      if (e.dataTransfer?.files) {
        for (const f of e.dataTransfer.files) addAttachment(f);
      }
    });
  }
}

// wish-41ed72ef · 语音输入 → 卷七十五续六 · 三模式语音 (用户 2026-07-11 校准语义)
//   · 语音输入 (dictation): 说完填输入框·手动发 (最初功能·不变);
//   · 语音对话 (transcribe): 持续听麦克风·你说完停约 1 秒自动发给 AI·
//       AI 回完继续听 —— hands-free 语音对话·给未来桌面版对话模式留的扣·UI 比会议纪要轻;
//   · 会议纪要 (meeting) = 【录制文本】: 持续把麦克风转成文字累积·点【停止录制】后
//       把整段交给 AI 拆分整理 (议题/结论/待办/风险)。
// 边界: 浏览器 SpeechRecognition 只认默认麦克风·线上会议对方声音要转文字得等后端 ASR·
//   本轮不纠结系统音频 (getDisplayMedia 那套已移除)。
(function initVoice() {
  const $micBtn = document.getElementById('micBtn');
  if (!$micBtn) return;
  const $micMode = document.getElementById('micMode');
  const $micMenu = document.getElementById('micMenu');
  const $panel = document.getElementById('voicePanel');
  const $script = document.getElementById('voiceTranscript');
  const $timer = document.getElementById('voiceTimer');
  const $panelMode = document.getElementById('voicePanelMode');
  const $recNote = document.getElementById('voiceRecNote');
  const $close = document.getElementById('voiceClose');

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const SILENCE_MS = 1000;      // 语音对话: 停顿约 1 秒自动发给 AI (用户 定 · 给桌面版对话模式留扣)
  const MODES = {
    dictation:  { label: '语音输入', panel: false, icon: 'ri-mic-line' },
    transcribe: { label: '语音对话', panel: true,  icon: 'ri-chat-voice-line' },   // 持续听 · 停约 1 秒自动发
    meeting:    { label: '会议纪要', panel: true,  icon: 'ri-group-line' },         // = 持续录成文本 · 停止后整理
  };
  let mode = localStorage.getItem('Daemonkey_voice_mode') || 'dictation';
  if (!MODES[mode]) mode = 'dictation';
  if (!SR) { $micBtn.classList.add('unsupported'); $micBtn.title = '语音功能需 Chrome / Edge 浏览器'; }

  // ── 2026-08-08 · TTS 开关 (语音对话模式: AI 回复自动朗读) ──
  // 能力探测: /api/tts 端点存在才显示开关 (纯净版无 voice.py → 探测 404 → 开关隐藏 · 优雅降级)
  // 挂到 window 上让 finalizeStreamingAssistant 能触发 (它在 initVoice 闭包外)
  window.__voiceTtsEnabled = false;
  const $ttsToggle = document.getElementById('voiceTtsToggle');
  const $ttsWrap = document.getElementById('voiceTtsWrap');
  if ($ttsToggle && $ttsWrap) {
    fetch('/api/tts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: '' }) })
      .then(r => {
        if (r.status === 404 || r.status === 405) return; // 端点不存在/未注册 → 保持隐藏
        $ttsWrap.hidden = false;
        window.__voiceTtsEnabled = localStorage.getItem('Daemonkey_voice_tts') === '1';
        $ttsToggle.checked = !!window.__voiceTtsEnabled;
        $ttsToggle.addEventListener('change', () => {
          window.__voiceTtsEnabled = $ttsToggle.checked;
          localStorage.setItem('Daemonkey_voice_tts', $ttsToggle.checked ? '1' : '0');
          if (typeof _setRecNote === 'function' && _listening && mode === 'transcribe') {
            _setRecNote($ttsToggle.checked
              ? '<i class="ri-volume-up-line"></i> TTS 已开 · Daemonkey 回复会朗读'
              : '<i class="ri-volume-mute-line"></i> TTS 已关', 'wait');
          }
        });
      })
      .catch(() => { /* 网络异常 → 保持隐藏 */ });
  }
  // 播放一条语音回复: 调 /api/tts 合成 → <audio> 播放 → 播完回调 (恢复收音)
  window.__speakReply = function (text, onDone) {
    if (!window.__voiceTtsEnabled || !(text || '').trim()) { if (onDone) onDone(); return; }
    const body = JSON.stringify({ text: (text || '').slice(0, 1500) });
    fetch('/api/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
    }).then(r => {
      if (!r.ok) throw new Error('TTS HTTP ' + r.status);
      return r.blob();
    }).then(blob => {
      const url = URL.createObjectURL(blob);
      const au = new Audio(url);
      au.onended = () => { URL.revokeObjectURL(url); if (onDone) onDone(); };
      au.onerror = () => { URL.revokeObjectURL(url); if (onDone) onDone(); };
      au.play().catch(() => { if (onDone) onDone(); });
    }).catch(e => {
      console.warn('TTS 播放失败:', e);
      if (onDone) onDone();
    });
  };

  let _rec = null;              // SpeechRecognition 实例
  let _listening = false;
  let _manualStop = false;      // true = 用户主动停 · 阻止 onend 自动重启
  let _finalText = '';          // 会议纪要累积的确认文字
  let _dictBase = '';           // 语音输入: 开录前输入框已有内容
  let _pendingBuf = '';         // 语音对话: 已确认待发的一段
  let _silenceTimer = null;     // 语音对话: 停顿检测 timer
  let _voicePaused = false;     // 语音对话: AI 回复中 → 暂停收音 (轮流说话·别录进杂音/AI 的话)
  let _replyWatcher = null;     // 语音对话: 盯 pending·AI 回完自动恢复收音
  let _sawPending = false;      // 语音对话: 确认这轮 turn 真起来了·防提前恢复
  let _pauseTicks = 0;          // 语音对话: 兜底·久等没起 turn 也恢复
  let _srGen = 0;               // SR 代号·暂停/停止/重启时 +1·让旧实例延迟触发的 onend 作废 (防并发双识别)
  let _timerId = null;
  let _startTs = 0;

  function _autosize() {
    $input.style.height = 'auto';
    $input.style.height = Math.min($input.scrollHeight, 160) + 'px';
  }
  function _setListening(on) {
    _listening = on;
    $micBtn.classList.toggle('listening', on);
    _updateActions();
  }
  // 面板按钮按 模式 + 是否在听 显隐:
  //   听着时 → 只显示【停止】(语音对话:停止对话 · 会议纪要:停止录制);
  //   会议纪要停下后 → 显示【整理成纪要/插入/清空】让 用户 处理文本。
  function _updateActions() {
    if (!$panel) return;
    const meetingStopped = (mode === 'meeting' && !_listening);
    $panel.querySelectorAll('.voice-act').forEach((b) => {
      const a = b.dataset.act;
      if (a === 'stop') b.hidden = !_listening;
      else b.hidden = !meetingStopped;
    });
    const $stop = $panel.querySelector('[data-act="stop"]');
    if ($stop) {
      $stop.innerHTML = (mode === 'meeting')
        ? '<i class="ri-stop-circle-line"></i> 停止录制'
        : '<i class="ri-stop-circle-line"></i> 停止对话';
    }
  }
  function _applyModeMeta() {
    const m = MODES[mode];
    $micBtn.title = m.panel ? `${m.label} · 点一下开始` : '语音输入 · 点一下开始说';
    const $ic = $micBtn.querySelector('i');   // 左侧麦克风图标跟着当前模式变 · 一眼看出在哪个模式
    if ($ic) $ic.className = m.icon;
    $micMenu && $micMenu.querySelectorAll('.mic-menu-item').forEach(b => {
      b.classList.toggle('active', b.dataset.mode === mode);
    });
  }
  _applyModeMeta();

  // ── 模式菜单 ──
  function _closeMenu() { if ($micMenu) $micMenu.hidden = true; }
  function _openMenu() { if ($micMenu) $micMenu.hidden = false; }
  if ($micMode) {
    $micMode.addEventListener('click', (e) => {
      e.stopPropagation();
      $micMenu.hidden ? _openMenu() : _closeMenu();
    });
  }
  document.addEventListener('click', (e) => {
    if ($micMenu && !$micMenu.hidden && !e.target.closest('.mic-group')) _closeMenu();
  });
  $micMenu && $micMenu.querySelectorAll('.mic-menu-item').forEach(btn => {
    btn.addEventListener('click', () => {
      if (!SR) { alert('语音功能需要 Chrome / Edge 浏览器'); return; }
      mode = btn.dataset.mode;
      localStorage.setItem('Daemonkey_voice_mode', mode);
      _applyModeMeta();
      _closeMenu();
    });
  });

  // ── 计时器 ──
  function _startTimer() {
    _startTs = Date.now();
    const tick = () => {
      const s = Math.floor((Date.now() - _startTs) / 1000);
      if ($timer) $timer.textContent = String((s / 60) | 0).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0');
    };
    tick();
    _timerId = setInterval(tick, 1000);
  }
  function _stopTimer() { if (_timerId) { clearInterval(_timerId); _timerId = null; } }

  // ── 转写面板 ──
  function _openPanel() {
    if (!$panel) return;
    const isChat = (mode === 'transcribe');
    $panel.classList.toggle('is-chat', isChat);
    $panel.classList.toggle('is-meeting', !isChat);
    if ($panelMode) $panelMode.textContent = isChat ? '语音对话 · 通话中' : '会议纪要 · 录制中';
    $panel.hidden = false;
    if ($recNote) { $recNote.hidden = true; $recNote.className = 'voice-rec-note'; }
  }
  function _renderTranscript(interim) {
    if (!$script) return;
    $script.innerHTML = escHtml(_finalText) + (interim ? '<span class="voice-interim">' + escHtml(interim) + '</span>' : '');
    $script.scrollTop = $script.scrollHeight;
  }
  function _setRecNote(html, cls) {
    if (!$recNote) return;
    $recNote.hidden = false;
    $recNote.className = 'voice-rec-note ' + (cls || '');
    $recNote.innerHTML = html;
  }

  // ── SpeechRecognition ──
  function _makeSR() {
    const r = new SR();
    r.lang = 'zh-CN'; r.interimResults = true; r.continuous = true; r.maxAlternatives = 1;
    return r;
  }
  function _startDictation() {
    _rec = _makeSR();
    _dictBase = $input.value ? $input.value.replace(/\s+$/, '') + ' ' : '';
    let finalText = '';
    _rec.onresult = (e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) finalText += r[0].transcript; else interim += r[0].transcript;
      }
      $input.value = _dictBase + finalText + interim;
      _autosize();
    };
    _rec.onend = () => {
      _rec = null; _setListening(false);
      if (finalText) { $input.value = _dictBase + finalText; _autosize(); }
      $input.focus();
    };
    _rec.onerror = _srError;
    _rec.start();
    _setListening(true);
  }
  // 绑一个 SR 实例并启动。 onend 里【建新实例】重启 (不是复用旧实例 .start()):
  //   Chromium 复用旧实例重启会把上一段 final 再 replay 一次 onresult → 没说话也被当新话发出去
  //   (用户 撞到的"第一句后自动又发个'查'")。 新实例 e.results 从零·根治重复。
  function _bindSR(onResult) {
    const r = _makeSR();
    const gen = _srGen;   // 绑死本代号·换代后这个实例的 onend 一律作废
    r.onresult = onResult;
    r.onerror = _srError;
    r.onend = () => {
      if (gen !== _srGen) { return; }   // 已被暂停/停止/换代 → 旧实例的收尾不再重启·防并发双识别
      if (!_manualStop && _listening && !_voicePaused) {
        try { _rec = _bindSR(onResult); }
        catch (_) { setTimeout(() => { if (gen === _srGen && !_manualStop && _listening && !_voicePaused) { try { _rec = _bindSR(onResult); } catch (__) {} } }, 300); }
      } else {
        _rec = null;
      }
    };
    r.start();
    return r;
  }
  function _renderChat(interim) {
    if (!$script) return;
    $script.innerHTML = escHtml(_pendingBuf) + (interim ? '<span class="voice-interim">' + escHtml(interim) + '</span>' : '');
    $script.scrollTop = $script.scrollHeight;
  }
  // ── 语音对话 · 停顿约 1 秒把这段自动发给 AI ──
  function _startVoiceChat() {
    _pendingBuf = '';
    _rec = _bindSR((e) => {
      let interim = '', gotFinal = false;
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) { _pendingBuf += r[0].transcript; gotFinal = true; } else interim += r[0].transcript;
      }
      _renderChat(interim);
      if (gotFinal) _scheduleFlush();
    });
  }
  function _scheduleFlush() {
    if (_silenceTimer) clearTimeout(_silenceTimer);
    _silenceTimer = setTimeout(_tryFlush, SILENCE_MS);
  }
  function _tryFlush() {
    _silenceTimer = null;
    if (_voicePaused) return;                    // AI 回复中 · 收音已停 · 不该有可发内容
    const txt = (_pendingBuf || '').trim();
    if (!txt) return;
    if (pending) { _silenceTimer = setTimeout(_tryFlush, 600); return; }  // AI 还在回 → 稍后再发
    _pendingBuf = '';
    _renderChat('');
    $input.value = txt;
    _autosize();
    if (typeof send === 'function') send();
    _pauseForReply();                            // 发完就停收音 · 轮到 Daemonkey 说 · 回完自动接着听
  }
  // AI 回复期间暂停麦克风 (用户: 语音对话该轮流说·回消息时别录音) · 盯 pending·回完自动恢复
  function _pauseForReply() {
    if (mode !== 'transcribe') return;
    _voicePaused = true; _sawPending = false; _pauseTicks = 0;
    _srGen++;                                    // 作废当前实例·停了别自动重启
    if (_rec) { try { _rec.stop(); } catch (_) {} }
    $micBtn.classList.remove('listening');
    _renderChat('');
    _setRecNote('<i class="ri-pause-circle-line"></i> Daemonkey 回复中 · 已暂停收音 · 回完自动继续听', 'wait');
    if (_replyWatcher) clearInterval(_replyWatcher);
    _replyWatcher = setInterval(() => {
      _pauseTicks++;
      if (pending) { _sawPending = true; return; }
      if (_sawPending || _pauseTicks > 12) _resumeAfterReply();   // 见过 turn 又结束·或 ~5s 没起 turn 兜底
    }, 400);
  }
  function _resumeAfterReply() {
    if (_replyWatcher) { clearInterval(_replyWatcher); _replyWatcher = null; }
    if (!_voicePaused) return;
    _voicePaused = false;
    if (_manualStop || !_listening || mode !== 'transcribe') return;  // 期间用户点了停 → 不恢复
    $micBtn.classList.add('listening');
    _setRecNote('<i class="ri-mic-fill"></i> 在听 · 你说完停约 1 秒会自动发给 Daemonkey', 'rec');
    _startVoiceChat();                           // 建新 SR 实例·继续听下一句
  }
  // ── 会议纪要 = 持续把麦克风转成文本累积 · 停止后交给 AI 拆分 ──
  function _startMeetingTranscribe() {
    _rec = _bindSR((e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) _finalText += r[0].transcript; else interim += r[0].transcript;
      }
      _renderTranscript(interim);
      _setRecNote('<i class="ri-record-circle-fill"></i> 录制中 · 已记录 ' + _finalText.trim().length + ' 字', 'rec');
    });
  }
  function _srError(e) {
    if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
      _manualStop = true;
      alert('麦克风权限被拒 · 请在浏览器设置中允许访问麦克风');
      _stopVoice(true);
    } else if (e.error !== 'aborted' && e.error !== 'no-speech') {
      console.warn('语音识别出错:', e.error);
    }
  }

  // (卷七十五续六 · 系统音频 getDisplayMedia/MediaRecorder 那套已移除:用户 定会议纪要=纯麦克风
  //  录成文本·停止后交给 AI 拆分;线上会议对方声音等后端 ASR 落地再补·不在此纠结。)

  // ── 启停总入口 ──
  function _startVoice() {
    if (!SR) { alert('语音功能需要 Chrome / Edge 浏览器'); return; }
    _manualStop = false;
    _voicePaused = false;
    _srGen++;                                    // 新一轮·作废上一轮任何残留实例
    if (_replyWatcher) { clearInterval(_replyWatcher); _replyWatcher = null; }
    if (mode === 'dictation') { _startDictation(); return; }
    _finalText = '';
    _pendingBuf = '';
    if ($script) $script.innerHTML = '';
    _openPanel();
    _startTimer();
    _setListening(true);
    if (mode === 'transcribe') {
      _setRecNote('<i class="ri-mic-fill"></i> 在听 · 你说完停约 1 秒会自动发给 Daemonkey', 'rec');
      _startVoiceChat();
    } else {
      _setRecNote('<i class="ri-record-circle-fill"></i> 录制中 · 边说边记 · 完了点【停止录制】', 'rec');
      _startMeetingTranscribe();
    }
  }
  function _stopVoice(manual) {
    _manualStop = !!manual;
    _voicePaused = false;
    _srGen++;                                    // 换代·让在途 onend 全部失效
    if (_replyWatcher) { clearInterval(_replyWatcher); _replyWatcher = null; }
    if (_silenceTimer) { clearTimeout(_silenceTimer); _silenceTimer = null; }
    if (_rec) { try { _rec.stop(); } catch (_) {} }
    _stopTimer();
    _setListening(false);
    _afterStop();
  }
  // 停下后收尾:语音对话 → 关面板(没后续动作);会议纪要 → 留文本·亮出整理/插入/清空。
  function _afterStop() {
    if (mode === 'transcribe') {
      if ($panel) $panel.hidden = true;
    } else if (mode === 'meeting') {
      if ($panelMode) $panelMode.textContent = '会议纪要 · 已停止';
      const n = (_finalText || '').trim().length;
      if (n > 0) _setRecNote('<i class="ri-stop-circle-fill"></i> 已停止 · 记录 ' + n + ' 字 · 点【整理成纪要】交给 Daemonkey 拆分', 'done');
      else _setRecNote('<i class="ri-information-line"></i> 没记到文字 · 检查麦克风权限后重录', 'warn');
    }
  }

  $micBtn.addEventListener('click', () => {
    if (_listening) { _stopVoice(true); return; }
    _startVoice();
  });

  // ── 面板动作 ──
  $panel && $panel.querySelectorAll('.voice-act').forEach(btn => {
    btn.addEventListener('click', () => {
      const act = btn.dataset.act;
      if (act === 'stop') { _stopVoice(true); return; }
      if (act === 'clear') {
        _finalText = ''; _renderTranscript('');
        _setRecNote('<i class="ri-eraser-line"></i> 已清空 · 点麦克风可重新录制', 'done');
        return;
      }
      const txt = (_finalText || '').trim();
      if (!txt) { return; }
      if (act === 'insert') {
        $input.value = ($input.value ? $input.value.trimEnd() + '\n' : '') + txt;
        _autosize();
        $panel.hidden = true;
        $input.focus();
      } else if (act === 'toclient') {
        // 会议纪要 ↔ 客户时间线打通 · 转写文字一键存成某客户 kind=meeting 条
        if (typeof pickClient !== 'function') { alert('客户档案模块未加载'); return; }
        pickClient((cid, name) => {
          fetch('/dashboard/clients/note', {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
            body: JSON.stringify({ client_id: cid, text: txt, kind: 'meeting' }),
          }).then(r => {
            if (r.ok) _setRecNote('<i class="ri-check-line"></i> 已存进「' + name + '」的会议记录 · 想要结构化纪要可再点【整理成纪要】', 'done');
            else alert('存失败 [' + r.status + ']');
          }).catch(e => alert('网络出错: ' + e.message));
        });
      } else if (act === 'minutes') {
        $input.value = '【整理会议纪要】下面是会议的语音转写文字，帮我拆分整理成结构化会议纪要：\n'
          + '1) 议题概述  2) 关键结论/决议  3) 待办事项(含负责人与时间)  4) 风险/待确认。\n'
          + '保留关键人名、数字、日期，语言精炼;转写可能有同音错别字，按语境修正。\n'
          + '整理完若这场会议对应某个已知客户，主动问我要不要用 manage_client 把纪要存成他的会议记录(kind=meeting)。\n\n---\n' + txt;
        $panel.hidden = true;
        if (typeof send === 'function') send();
      }
    });
  });
  $close && $close.addEventListener('click', () => {
    _stopVoice(true);
    $panel.hidden = true;
  });
})();

// 卷七十五续五 · 模型行为 (思考/推理强度/输出上限) · 本地记住 · 每次 chat 请求带上
// 缺省全空 = 后端老行为(零回归)。 后端只对支持的模型下发·别的静默忽略·不报错。
function modelBehaviorPayload() {
  const out = {};
  try {
    const think = localStorage.getItem('Daemonkey_mb_thinking') || 'auto';
    const effort = localStorage.getItem('Daemonkey_mb_effort') || '';
    const mt = localStorage.getItem('Daemonkey_mb_max_tokens') || '';
    if (think && think !== 'auto') out.thinking = think;
    if (effort) out.reasoning_effort = effort;
    const n = parseInt(mt, 10);
    if (n > 0) out.max_tokens = n;
  } catch (_) {}
  return out;
}
(function initModelBehavior() {
  const $think = document.getElementById('mbThinking');
  const $effort = document.getElementById('mbEffort');
  const $mt = document.getElementById('mbMaxTokens');
  if (!$think && !$effort && !$mt) return;
  try {
    if ($think) $think.value = localStorage.getItem('Daemonkey_mb_thinking') || 'auto';
    if ($effort) $effort.value = localStorage.getItem('Daemonkey_mb_effort') || '';
    if ($mt) $mt.value = localStorage.getItem('Daemonkey_mb_max_tokens') || '';
  } catch (_) {}
  $think && $think.addEventListener('change', () => localStorage.setItem('Daemonkey_mb_thinking', $think.value));
  $effort && $effort.addEventListener('change', () => localStorage.setItem('Daemonkey_mb_effort', $effort.value));
  $mt && $mt.addEventListener('change', () => {
    const n = parseInt($mt.value, 10);
    if (n > 0) localStorage.setItem('Daemonkey_mb_max_tokens', String(n));
    else { localStorage.removeItem('Daemonkey_mb_max_tokens'); $mt.value = ''; }
  });
})();

const $modal = document.getElementById('settings');
// 卷三十六 · 当前 turn 的 id · 用来发 abort 请求
// wish-3fef4bc7 · 真并行后这些是 active session 的 mirror · 切换 session 时同步
let currentTurnId = null;
let currentAbortController = null;
const $tokenIn = document.getElementById('tokenInput');
const $sessionIn = document.getElementById('sessionInput');
const $autoIn = document.getElementById('autoConfirm');

// 卷三十五补丁6 · 进度条 + mutating 工具白名单
// 这些工具会写 data/ 下文件 · 改 dashboard 数据 · Daemonkey 调一次 → UI 立刻刷一次
// 只读工具 (read_file / grep_files / web_search / browser_fetch / shell_exec 等) 不在表 · 跳过
const MUTATING_TOOLS = new Set([
  'wish_add', 'wish_update',
  'tag_radar_item', 'manage_info_source',
  'init_domain', 'remove_domain', 'add_domain',
  'mine_opportunities', 'analyze_feasibility', 'record_outcome',
  'toggle_favorite', 'generate_report', 'expand_trend_to_report',
  'auto_pipeline', 'update_bro_note', 'refresh_radar', 'generate_trends',
  'Daemonkey_diary',
  // 卷五十四 · 工坊产出类补全 (之前漏了·Daemonkey 造完 app/草稿 看板不自动刷·用户 得手动 F5)
  'create_app', 'update_app', 'create_workflow', 'draft_studio',
  'update_self_evolution',
]);

// 卷四十六续 10 · dashboard list 通用搜索框 (event delegation · 一次绑全 view 共用)
// 用户 反馈 (候选 B): "心愿/报告/机会/趋势 加搜索框 · 16 条不算多 · N 大了就刚需"
// 用法 (在 render*View 函数内 · 在 list 容器上面插入):
//   renderListFilter({targetSelector: '.wish-card', placeholder: '搜心愿标题或动机...'})
// 数据驱动: input.value 变化 → 隐藏 textContent 不含 query 的 item · 更新 stats
function renderListFilter(opts) {
  const sel = (opts && opts.targetSelector) || '';
  const ph = (opts && opts.placeholder) || '搜索…';
  return `
    <div class="list-filter">
      <span class="list-filter-icon"><i class="ri-search-line"></i></span>
      <input type="search" class="list-filter-input" data-filter-target="${escHtml(sel)}" placeholder="${escHtml(ph)}" autocomplete="off">
      <span class="list-filter-stats" data-filter-stats></span>
      <button class="list-filter-clear" type="button" data-filter-clear hidden>✕</button>
    </div>`;
}

let _listFilterInited = false;
function _initListFilter() {
  if (_listFilterInited) return;
  _listFilterInited = true;
  document.addEventListener('input', e => {
    if (!e.target.classList || !e.target.classList.contains('list-filter-input')) return;
    _applyListFilter(e.target);
  });
  document.addEventListener('click', e => {
    if (!e.target.matches || !e.target.matches('[data-filter-clear]')) return;
    const wrap = e.target.closest('.list-filter');
    if (!wrap) return;
    const input = wrap.querySelector('.list-filter-input');
    if (!input) return;
    input.value = '';
    _applyListFilter(input);
    input.focus();
  });
  // ESC 清空当前 focused 的搜索框 · 不关 dashboard (区分于全局 ESC)
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    if (!e.target.classList || !e.target.classList.contains('list-filter-input')) return;
    if (!e.target.value) return;
    e.stopPropagation();
    e.target.value = '';
    _applyListFilter(e.target);
  });
}
function _applyListFilter(input) {
  const q = (input.value || '').trim().toLowerCase();
  const sel = input.dataset.filterTarget;
  if (!sel) return;
  // 搜索范围限制在 input 的 dashboard 容器内 (避免误匹配其他 view 残留 DOM)
  const root = input.closest('#detailPane, #dashView') || document;
  const items = root.querySelectorAll(sel);
  let visible = 0;
  items.forEach(it => {
    const text = (it.textContent || '').toLowerCase();
    const match = !q || text.includes(q);
    it.style.display = match ? '' : 'none';
    if (match) visible++;
  });
  const wrap = input.closest('.list-filter');
  if (wrap) {
    const stats = wrap.querySelector('.list-filter-stats');
    if (stats) stats.textContent = q ? `${visible} / ${items.length}` : `${items.length} 条`;
    const clear = wrap.querySelector('[data-filter-clear]');
    if (clear) clear.hidden = !q;
  }
}
_initListFilter();

function showToolProgress(visible) {
  const el = document.getElementById('toolProgress');
  if (el) el.hidden = !visible;
  if (!visible) {
    // 隐藏进度条时·清空详情记录·下次重新攒
    recentToolEvents.length = 0;
    const detail = document.getElementById('toolProgressDetail');
    if (detail) detail.hidden = true;
    const btn = document.querySelector('.tool-progress-detail');
    if (btn) btn.textContent = '详情 ▾';
    // 卷四十六续 9 · 隐藏进度条时清掉 ticker (防泄漏)
    _stopToolProgressTicker();
    _stopBgProgressTicker();
  }
}
// 进度条只用 RemixIcon · 把后端进度文案里的 emoji(📡🌀⏳…)映射成内置图标 (用户 要求统一)
const _PROGRESS_EMOJI_ICON = {
  '📡': 'ri-radar-line', '🌐': 'ri-global-line', '🧠': 'ri-brain-line',
  '🔍': 'ri-search-line', '🌀': 'ri-loader-4-line', '✨': 'ri-sparkling-line',
  '📊': 'ri-bar-chart-line', '⏳': 'ri-time-line', '📚': 'ri-book-2-line',
  '💡': 'ri-lightbulb-line', '⚙️': 'ri-settings-3-line', '⚙': 'ri-settings-3-line',
  '📝': 'ri-file-edit-line', '✅': 'ri-check-line', '🔧': 'ri-tools-line',
  '🚀': 'ri-rocket-line', '💬': 'ri-chat-3-line', '📥': 'ri-download-line',
  '🔎': 'ri-search-line', '📶': 'ri-radar-line', '🗂️': 'ri-folder-3-line',
  '💎': 'ri-vip-diamond-line', '🌊': 'ri-line-chart-line', '🛰️': 'ri-用户adcast-line',
  '🛰': 'ri-用户adcast-line', '🌟': 'ri-star-line', '⭐': 'ri-star-line',
  '🖼️': 'ri-image-line', '🖼': 'ri-image-line', '🎨': 'ri-palette-line',
};
function _iconifyProgress(text) {
  // 先把已内联的 RemixIcon 标签(<i class="ri-xxx"></i>)抽出占位·别被 escHtml 转义成字面量
  // (卷七十九续 · 用户 反馈进度条里出现字面 <i class="ri-check-fill">)
  const icons = [];
  const stashed = (text || '').replace(/<i class="ri-[a-z0-9-]+"><\/i>/g, (m) => {
    icons.push(m);
    return `\u0000IC${icons.length - 1}\u0000`;
  });
  let html = escHtml(stashed);
  for (const emo in _PROGRESS_EMOJI_ICON) {
    if (html.indexOf(emo) !== -1) {
      html = html.split(emo).join(`<i class="${_PROGRESS_EMOJI_ICON[emo]}"></i>`);
    }
  }
  return html.replace(/\u0000IC(\d+)\u0000/g, (_m, i) => icons[+i] || '');
}
function setToolProgressText(text) {
  const el = document.getElementById('toolProgress');
  if (!el) return;
  const t = el.querySelector('.tool-progress-text');
  if (t) t.innerHTML = _iconifyProgress(text);
}

// ② 自主巡航进度 (卷七十五续四) · 把 active_turn 端点回的 progress 快照格式化成进度条文案
// progress = {label, tool, iteration, elapsed_s, stale_s} · 可能为 null (老 daemon / 刚起没记上)
function _fmtBgProgress(progress, elapsedOverride, staleOverride) {
  if (!progress) return 'Daemonkey 后台仍在跑这个对话 · 自动刷新中…';
  const label = (progress.label || '').trim() || '跑动中';
  const it = progress.iteration ? ` · 第${progress.iteration}轮` : '';
  const elapsedS = (elapsedOverride != null) ? elapsedOverride : progress.elapsed_s;
  const el = (elapsedS != null) ? ` · 已${elapsedS}s` : '';
  // 距上次进度更新 >25s · 多半在等模型出字 (长上下文/深度思考) · 给个明确提示而非"像卡住"
  const staleS = (staleOverride != null) ? staleOverride : progress.stale_s;
  const stale = (staleS != null && staleS >= 25) ? ' · ⏳等模型响应' : '';
  return `Daemonkey 后台跑动中 · ${label}${it}${el}${stale}`;
}

// 自主巡航读秒本地插值 · 后台 turn 无 SSE·只有每 3s 的 poll 快照·靠这个 1s ticker 让
// "已Xs"每秒跳(而非 3 秒一跳)。poll 回来时 _startBgProgressTicker 重设快照+基准时间·校准漂移。
let _bgProgressTickerId = null;
let _bgProgressState = null; // {sessionId, snapshot, receivedAt}
function _stopBgProgressTicker() {
  if (_bgProgressTickerId) { clearInterval(_bgProgressTickerId); _bgProgressTickerId = null; }
  _bgProgressState = null;
}
function _refreshBgProgressTick() {
  const st = _bgProgressState;
  if (!st || st.sessionId !== sessionId) return;
  const p = st.snapshot;
  if (!p) { setToolProgressText(_fmtBgProgress(null)); return; }
  const delta = Math.floor((Date.now() - st.receivedAt) / 1000);
  const elapsed = (p.elapsed_s != null) ? p.elapsed_s + delta : null;
  const stale = (p.stale_s != null) ? p.stale_s + delta : null;
  setToolProgressText(_fmtBgProgress(p, elapsed, stale));
}
function _startBgProgressTicker(sid, snapshot) {
  _bgProgressState = { sessionId: sid, snapshot: snapshot, receivedAt: Date.now() };
  _refreshBgProgressTick();               // 立即刷一次·不等 1s
  if (!_bgProgressTickerId) _bgProgressTickerId = setInterval(_refreshBgProgressTick, 1000);
}

// 卷四十六续 9 · 工具进度条「已 X 秒」实时 ticker
// 用户 反馈: tool_call 触发后 "已 2s" 卡在那不动·应该每秒读秒·新工具开始时清零
// 实现: state._lastToolMeta 存当前 tool · ticker setInterval(1000) 重算 elapsed
// tool_result 时 frozen=true 锁定显示总耗时·下个 tool_call 重置
let _toolProgressTickerId = null;
let _toolProgressActiveState = null;
function _stopToolProgressTicker() {
  if (_toolProgressTickerId) {
    clearInterval(_toolProgressTickerId);
    _toolProgressTickerId = null;
  }
  _toolProgressActiveState = null;
}
function _refreshToolProgressTick() {
  const st = _toolProgressActiveState;
  if (!st || st.sessionId !== sessionId) return;
  const m = st._lastToolMeta;
  // 有正在跑的工具(未冻结)→ 显示该工具已用时
  if (m && m.startedAt && !m.frozen) {
    const elapsed = Math.floor((Date.now() - m.startedAt) / 1000);
    const briefArgs = (m.summary || '').slice(0, 40);
    // 卷五十八 · wish-f30d571d · 有 tool_progress 步骤信息时优先显示步骤
    if (m.progressStep) {
      const stepText = m.progressStep + (m.progressMsg ? ' ' + m.progressMsg : '');
      setToolProgressText(`${stepText} · 已 ${elapsed}s`);
    } else {
      setToolProgressText(
        `Daemonkey 正在跑第 ${m.count} 个工具 · ${m.name || '?'}${briefArgs ? ' · ' + briefArgs : ''} · 已 ${elapsed}s`
      );
    }
    return;
  }
  // 卷七十九续 · 没有活跃工具但这一轮还在跑(思考/写字/等模型)→ 整轮读秒
  // 别卡在上一个工具的冻结文案(用户: "什么都没做他就一直保持 0s")
  if (st._turnStartedAt) {
    const el = Math.floor((Date.now() - st._turnStartedAt) / 1000);
    setToolProgressText(`Daemonkey 思考中 · 已 ${el}s`);
  }
}
function _startToolProgressTicker(state) {
  if (_toolProgressTickerId) clearInterval(_toolProgressTickerId);
  _toolProgressActiveState = state;
  _refreshToolProgressTick(); // 立即刷一次 · 不等 1s
  _toolProgressTickerId = setInterval(_refreshToolProgressTick, 1000);
}

// 卷三十五补丁6.1 · 详情面板的真实内容 · 维护最近 8 个工具事件
const recentToolEvents = []; // {phase: 'call'|'ok'|'fail', name, summary, t}
const MAX_DETAIL_ROWS = 12;

function recordToolEvent(phase, name, summary) {
  recentToolEvents.push({
    phase: phase,
    name: name || '?',
    summary: (summary || '').slice(0, 180),
    t: Date.now(),
  });
  while (recentToolEvents.length > MAX_DETAIL_ROWS) {
    recentToolEvents.shift();
  }
  // 如果详情区已展开 · 实时更新
  const detail = document.getElementById('toolProgressDetail');
  if (detail && !detail.hidden) {
    renderToolDetail();
  }
}

function renderToolDetail() {
  const detail = document.getElementById('toolProgressDetail');
  if (!detail) return;
  if (recentToolEvents.length === 0) {
    detail.innerHTML = '<div class="tool-detail-empty">暂无工具调用</div>';
    return;
  }
  const now = Date.now();
  const rows = recentToolEvents.slice().reverse().map(ev => {
    const ago = Math.max(0, Math.round((now - ev.t) / 1000));
    let icon, cls;
    if (ev.phase === 'call') { icon = '⚙'; cls = 'calling'; }
    else if (ev.phase === 'ok') { icon = '<i class="ri-check-fill"></i>'; cls = 'ok'; }
    else { icon = '<i class="ri-close-fill"></i>'; cls = 'fail'; }
    const body = `<b>${escHtml(ev.name)}</b>${ev.summary ? ' · ' + escHtml(ev.summary) : ''}`;
    return `<div class="tool-detail-row ${cls}">`
         + `<span class="td-icon">${icon}</span>`
         + `<span class="td-body">${body}</span>`
         + `<span class="td-time">${ago}s 前</span>`
         + `</div>`;
  });
  detail.innerHTML = rows.join('');
}

function toggleToolDetail() {
  const detail = document.getElementById('toolProgressDetail');
  const btn = document.querySelector('.tool-progress-detail');
  if (!detail) return;
  if (detail.hidden) {
    detail.hidden = false;
    renderToolDetail();
    if (btn) btn.textContent = '收起 ▴';
  } else {
    detail.hidden = true;
    if (btn) btn.textContent = '详情 ▾';
  }
}
window.toggleToolDetail = toggleToolDetail;

// 卷七十二 v3 · 工作流跑时进度 banner (用户 图2 诉求)
// 轮询 /workshop/runs · 有 active flow / 最近完成都显示 banner · 点击展开看每 step 进度
// 卷七十三 P0 (2026-06-10): 异步化后 banner 必须显示 done/failed 通知 · 否则 用户 等不到回声
const _FLOW_RUNS_POLL_MS = 3000;
const _FLOW_RECENT_TERMINAL_MS = 90 * 1000;  // 90s 内的 done/failed 也显示 (用户 看到结果再消失)
let _flowRunsTimer = null;
let _flowRunsActive = [];       // 当前展示集合 (running + 最近 90s 内 done/failed)
let _flowRunsDetailOpen = false;
let _flowRunsDetailCache = {};  // run_id → 完整 state (展开时 fetch · 折叠时也保留供下次秒开)
let _flowRunsDismissed = {};    // run_id → true · 用户 点 "知道了" 后不再 banner

// ── 任务计划条 (对话框上方 · 长轴任务"总共几步/走到哪") ──────────────────
// 数据源 /api/plan/active → task_ledger 的 steps 层。
// AI 用 track_task(action='plan'/'step') 写·用户在这个面板里改 ——
// 改完下一轮 render_hint 就把新计划回灌给 AI(产品观第 2 条: 人的反馈要真的influence下一次调用)。
const PLAN_OPEN_KEY = 'Daemonkey_plan_detail_open';
let _planData = null;
let _planPollTimer = null;
let _planEditing = 0;     // 正在 inline 编辑第几步 · 轮询期间别重绘把输入框冲掉

function _planOpen() {
  try { return localStorage.getItem(PLAN_OPEN_KEY) === '1'; } catch (e) { return false; }
}

async function _planApi(method, path, body) {
  const token = _flowRunsToken();   // 全站同一把 token (Daemonkey_ui_token)
  if (!token) return null;
  const opt = { method, headers: { 'Authorization': 'Bearer ' + token } };
  if (body) {
    opt.headers['Content-Type'] = 'application/json';
    opt.body = JSON.stringify(body);
  }
  try {
    const r = await fetch(path, opt);
    if (!r.ok) return null;
    return await r.json();
  } catch (e) { return null; }
}

async function refreshPlan() {
  if (!sessionId) { _renderPlan(null); return; }
  const d = await _planApi('GET', '/api/plan/active?session_id=' + encodeURIComponent(sessionId));
  if (d) _renderPlan(d);
}
window.refreshPlan = refreshPlan;

function _renderPlan(d) {
  _planData = d;
  const banner = document.getElementById('planBanner');
  if (!banner) return;
  if (!d || !d.active) { banner.hidden = true; return; }
  banner.hidden = false;
  const p = d.progress || {};
  const total = p.total || 0;
  const settled = p.settled || 0;
  banner.classList.toggle('is-done', !!p.all_done);
  const t = document.getElementById('planTitle');
  const c = document.getElementById('planCount');
  const fill = document.getElementById('planTrackFill');
  if (t) t.textContent = d.title || '任务';
  if (c) c.textContent = settled + '/' + total;
  if (fill) fill.style.width = (total ? Math.round(settled * 100 / total) : 0) + '%';
  const detail = document.getElementById('planDetail');
  const toggle = document.getElementById('planToggle');
  const open = _planOpen();
  if (toggle) toggle.textContent = open ? '收起 ▴' : '详情 ▾';
  if (detail) {
    detail.hidden = !open;
    if (open) _renderPlanDetail();
  }
}

const _PLAN_MARK = {
  todo: 'ri-checkbox-blank-circle-line',
  doing: 'ri-loader-4-line tp-spin',
  done: 'ri-checkbox-circle-fill',
  skip: 'ri-indeterminate-circle-line',
};
const _PLAN_MARK_TITLE = {
  todo: '点一下标记做完', doing: '正在做 · 点一下标记做完',
  done: '已完成 · 点一下退回待做', skip: '已跳过 · 点一下退回待做',
};

// 用 DOM API 建节点(不拼 innerHTML): 步骤文案是 AI/用户写的自由文本·
// 里面可能有 < > & 甚至像标签的东西·拼字符串就得自己做转义·textContent 天然免疫。
function _renderPlanDetail() {
  const detail = document.getElementById('planDetail');
  if (!detail || !_planData) return;
  if (_planEditing) return;            // 编辑中不重绘 · 否则打字打一半被冲掉
  detail.textContent = '';
  const steps = _planData.steps || [];
  steps.forEach((s) => {
    const st = s.status || 'todo';
    const row = document.createElement('div');
    row.className = 'plan-step';
    row.dataset.status = st;

    const mark = document.createElement('button');
    mark.type = 'button';
    mark.className = 'plan-step-mark';
    mark.title = _PLAN_MARK_TITLE[st] || '';
    mark.innerHTML = '<i class="' + (_PLAN_MARK[st] || _PLAN_MARK.todo) + '"></i>';
    mark.onclick = (e) => { e.stopPropagation(); _planToggleStep(s.i, st); };
    row.appendChild(mark);

    const idx = document.createElement('span');
    idx.className = 'plan-step-i';
    idx.textContent = s.i + '.';
    row.appendChild(idx);

    const txt = document.createElement('span');
    txt.className = 'plan-step-text';
    txt.textContent = s.text || '';
    txt.title = '点一下改这步';
    txt.onclick = (e) => { e.stopPropagation(); _planEditStep(row, s); };
    row.appendChild(txt);

    if (s.note) {
      const note = document.createElement('span');
      note.className = 'plan-step-note';
      note.textContent = '(' + s.note + ')';
      row.appendChild(note);
    }

    const del = document.createElement('button');
    del.type = 'button';
    del.className = 'plan-step-del';
    del.title = '删掉这步';
    del.innerHTML = '<i class="ri-close-line"></i>';
    del.onclick = (e) => { e.stopPropagation(); _planDelStep(s.i); };
    row.appendChild(del);

    detail.appendChild(row);
  });

  const foot = document.createElement('div');
  foot.className = 'plan-detail-foot';
  const add = document.createElement('button');
  add.type = 'button';
  add.className = 'plan-add-btn';
  add.innerHTML = '<i class="ri-add-line"></i> 加一步';
  add.onclick = (e) => { e.stopPropagation(); _planAddStep(); };
  foot.appendChild(add);

  // 这活是在做某条心愿单 → 给条能跳过去的线 (账本侧存 wish_id · 心愿单那边也能反查进度)
  if (_planData.wish_id) {
    const w = document.createElement('button');
    w.type = 'button';
    w.className = 'plan-foot-link';
    w.title = '这份计划属于这条心愿 · 点开看心愿单';
    w.innerHTML = '<i class="ri-lightbulb-line"></i> ' + _planData.wish_id;
    w.onclick = (e) => {
      e.stopPropagation();
      if (typeof switchView === 'function') switchView('wishlist');
    };
    foot.appendChild(w);
  }

  const hint = document.createElement('span');
  hint.className = 'plan-foot-hint';
  const ec = _planData.entry_count || 0;
  // 名字跟『相遇』里取的走 · 拼新串直接用 window.AI_NAME(见顶部 localizer)。
  // 光靠 MutationObserver 兜也能换·但那是异步的·会闪一下默认名。
  hint.textContent = ec ? ('这任务还记了 ' + ec + ' 条结论')
    : ('改完 ' + (window.AI_NAME || 'Daemonkey') + ' 下一轮就知道');
  foot.appendChild(hint);
  detail.appendChild(foot);
}

function togglePlanDetail() {
  const detail = document.getElementById('planDetail');
  const toggle = document.getElementById('planToggle');
  if (!detail) return;
  const willOpen = detail.hidden;
  try { localStorage.setItem(PLAN_OPEN_KEY, willOpen ? '1' : '0'); } catch (e) { /* 隐私模式 */ }
  detail.hidden = !willOpen;
  if (toggle) toggle.textContent = willOpen ? '收起 ▴' : '详情 ▾';
  if (willOpen) _renderPlanDetail();
}
window.togglePlanDetail = togglePlanDetail;

// 打钩语义: 做完的点一下退回待做·其余一点就是"做完了"(最符合勾选框直觉)
async function _planToggleStep(i, cur) {
  const next = (cur === 'done') ? 'todo' : 'done';
  const d = await _planApi('PATCH', '/api/plan/step',
    { session_id: sessionId, i: i, status: next });
  if (d) _renderPlan(d);
}

function _planEditStep(row, s) {
  if (_planEditing) return;
  _planEditing = s.i;
  const txt = row.querySelector('.plan-step-text');
  if (!txt) { _planEditing = 0; return; }
  const input = document.createElement('input');
  input.className = 'plan-step-edit';
  input.value = s.text || '';
  const done = async (save) => {
    if (!_planEditing) return;
    _planEditing = 0;
    const v = input.value.trim();
    if (save && v && v !== (s.text || '')) {
      const d = await _planApi('PATCH', '/api/plan/step',
        { session_id: sessionId, i: s.i, text: v });
      if (d) { _renderPlan(d); return; }
    }
    _renderPlanDetail();
  };
  input.onkeydown = (e) => {
    if (e.key === 'Enter') { e.preventDefault(); done(true); }
    else if (e.key === 'Escape') { e.preventDefault(); done(false); }
  };
  input.onblur = () => done(true);
  row.replaceChild(input, txt);
  input.focus();
  input.select();
}

async function _planDelStep(i) {
  const d = await _planApi('DELETE', '/api/plan/step', { session_id: sessionId, i: i });
  if (d) _renderPlan(d);
}

// 就地长出一个输入框·不用 window.prompt: prompt 阻塞主线程、样式不受控、
// 跟工程 UI 语言不搭·而且自动化测不到(会被自动 dismiss)。
function _planAddStep() {
  const detail = document.getElementById('planDetail');
  if (!detail || _planEditing) return;
  _planEditing = -1;                   // -1 = 正在新增(不是改某一步) · 挡住轮询重绘
  const row = document.createElement('div');
  row.className = 'plan-step';
  row.dataset.status = 'todo';
  const input = document.createElement('input');
  input.className = 'plan-step-edit';
  input.placeholder = '写一句话 · 动词开头 · 回车加进去';
  const done = async (save) => {
    if (!_planEditing) return;
    _planEditing = 0;
    const v = input.value.trim();
    if (save && v) {
      const d = await _planApi('POST', '/api/plan/step',
        { session_id: sessionId, text: v });
      if (d) { _renderPlan(d); return; }
    }
    _renderPlanDetail();
  };
  input.onkeydown = (e) => {
    if (e.key === 'Enter') { e.preventDefault(); done(true); }
    else if (e.key === 'Escape') { e.preventDefault(); done(false); }
  };
  input.onblur = () => done(true);
  row.appendChild(input);
  const foot = detail.querySelector('.plan-detail-foot');
  detail.insertBefore(row, foot);
  input.focus();
}

function _startPlanPoll() {
  if (_planPollTimer) return;
  refreshPlan();
  // 6 秒: 计划变化远没工作流频繁(那边 3 秒)·而且发完消息会主动刷一次
  _planPollTimer = setInterval(() => {
    if (document.hidden) return;       // 后台标签页不空跑
    refreshPlan();
  }, 6000);
}

function _flowRunsToken() {
  // H-12 修复: 全站 token 实际写在 Daemonkey_ui_token (旧版 Daemonkey_ui_token) ——
  // 原先读的 Daemonkey_token 无人写入 · pollFlowRuns 永远空转 · 运行横幅整套死区
  try { return localStorage.getItem('Daemonkey_ui_token') || localStorage.getItem('Daemonkey_ui_token') || ''; } catch (e) { return ''; }
}

function _isRecentTerminal(run) {
  const st = run.status || '';
  if (st !== 'done' && st !== 'failed') return false;
  const ts = run.updated_at || '';
  if (!ts) return false;
  const t = Date.parse(ts);  // ISO 不带时区 · 当本地时间 parse (跟 daemon 同主机)
  if (isNaN(t)) return false;
  return (Date.now() - t) < _FLOW_RECENT_TERMINAL_MS;
}

// 卷七十三 P2 (2026-06-10) · 跨 tab 提醒 (用户 切走 tab 也能感知 flow 跑完)
let _flowRunsPrevStatuses = {};       // run_id → 上次 poll 看到的 status · 用来 diff "running → done/failed"
let _flowRunsTitleTimer = null;
const _ORIGINAL_TITLE = document.title;

function _flashTitle(prefix) {
  if (_flowRunsTitleTimer) { clearInterval(_flowRunsTitleTimer); _flowRunsTitleTimer = null; }
  let on = true;
  document.title = prefix + ' ' + _ORIGINAL_TITLE;
  _flowRunsTitleTimer = setInterval(() => {
    on = !on;
    document.title = on ? (prefix + ' ' + _ORIGINAL_TITLE) : _ORIGINAL_TITLE;
  }, 1100);
}

function _stopTitleFlash() {
  if (_flowRunsTitleTimer) { clearInterval(_flowRunsTitleTimer); _flowRunsTitleTimer = null; }
  document.title = _ORIGINAL_TITLE;
}

// 用户 切回 tab 自动停闪 (有把 tab 切走的场景才需要闪 · 看了就不闪)
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) {
    _stopTitleFlash();
    // 卷 · 2026-08-09 · 用户 反馈: 人离开标签页在后台时 daemon 重启 · 回来看到旧画面 ·
    // F5 才出后台续场结果。根因: 恢复路径 A(在场重启 SSE 检测) 被后台节流拖住 · B(页面加载)
    // 需 F5 才触发 · 缺一条『切回前台自动探测』。补: 回前台时查当前 session 有无后台 turn 在跑
    // /刚跑完 · 有就启 3s 轮询拉结果 (跟 _probeAndStartPoll 同一套) · 让 用户 不用 F5。
    try {
      const st = activeSession();
      if (st && st.sessionId && !st.sessionId.startsWith('tmp-') && !st.pending && !st.pollIntervalId) {
        // 查后台 turn 状态: scheduled/running = 续场在跑 → 起轮询等结果;
        // completed = 已跑完但可能 UI 没跟上 → 重载历史把结果显示出来 (用户 这次场景)
        fetch(`/sessions/${encodeURIComponent(st.sessionId)}/background_turn_status`, {
          headers: { 'Authorization': 'Bearer ' + token },
        }).then(r => r.ok ? r.json() : { status: 'none' }).then(j => {
          const s = (j && j.status) || 'none';
          if (s === 'scheduled' || s === 'running') {
            _maybeStartPoll(st);   // 单次探测: 有 active turn 就起轮询
          } else if (s === 'completed') {
            // 后台续场已跑完 · 重载历史把结果刷出来 · 解锁 (跟 L13363 同逻辑)
            _loadSessionHistory(st.sessionId).then(() => {
              if (st && sessionId === st.sessionId) {
                pending = false;
                setSendButtonState('idle');
                setInputLocked(false);
                showToolProgress(false);
              }
            }).catch(() => {});
          }
        }).catch(() => {});
      }
    } catch (_) {}
  }
});

// ─── wish-fb6b7427 事项C · 标签闪烁通道 · 客户端配置缓存 ───
let _ntfCfg = null;   // null=还没拉过 · 保守不闪
async function _loadNotifyCfg() {
  if (!token) return;
  try {
    const r = await fetch('/notification-config', { headers: { 'Authorization': 'Bearer ' + token } });
    if (r.ok) _ntfCfg = await r.json();
  } catch (_) {}
}
// 开关开着 + tab 在后台才闪 · 切回 tab 由上面 visibilitychange 统一停
function _maybeTabFlash(prefix) {
  if (_ntfCfg === null) { _loadNotifyCfg(); return; }  // 首遇 lazy 补拉 · 本次不闪(保守)
  if (!_ntfCfg.tab_flash) return;
  if (!document.hidden) return;                        // 正看着 → 页内 toast 够 · 不闪
  _flashTitle(prefix);
}
// 启动拉一次
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _loadNotifyCfg, { once: true });
} else { _loadNotifyCfg(); }

async function pollFlowRuns() {
  const token = _flowRunsToken();
  if (!token) return;
  try {
    // 拉最近 12 条 (不过滤 status) · 客户端筛 running + 最近 terminal
    const r = await fetch('/workshop/runs?limit=12', {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) return;
    const data = await r.json();
    const all = data.runs || [];

    // diff: 上轮 running 这轮 done/failed → 触发 title 闪烁通知 (跨 tab 感知 · 用户 切走也能看到)
    let flashKind = null;  // 'done' / 'failed' / null
    for (const r of all) {
      const prev = _flowRunsPrevStatuses[r.run_id];
      if (prev === 'running' && (r.status === 'done' || r.status === 'failed')) {
        // failed 优先级高 (覆盖 done · 一组 run 任意一个失败先报失败)
        if (r.status === 'failed') { flashKind = 'failed'; break; }
        if (!flashKind) flashKind = 'done';
      }
      _flowRunsPrevStatuses[r.run_id] = r.status;
    }
    // tab 不在前台时才闪 (前台直接看 banner 即可 · 不打扰)
    if (flashKind && document.hidden) {
      _flashTitle(flashKind === 'done' ? '[✓ 跑完]' : '[✗ 失败]');
    }

    _flowRunsActive = all.filter(r => {
      if (_flowRunsDismissed[r.run_id]) return false;
      if (r.status === 'running') return true;
      return _isRecentTerminal(r);
    });
    renderFlowRunsBanner();
    if (_flowRunsDetailOpen) await refreshFlowRunsDetail();
  } catch (e) { /* 静默 · 下次 poll 再试 */ }
}

function renderFlowRunsBanner() {
  const banner = document.getElementById('flowRunsBanner');
  const text = document.getElementById('flowRunsText');
  if (!banner || !text) return;
  if (_flowRunsActive.length === 0) {
    banner.hidden = true;
    _flowRunsDetailOpen = false;
    const detail = document.getElementById('flowRunsDetail');
    if (detail) detail.hidden = true;
    // 状态色复位
    banner.classList.remove('is-done', 'is-failed', 'is-mixed');
    return;
  }
  banner.hidden = false;

  // 计算混合状态着色: 任意 running → running (紫); 全 done → done (绿); 任意 failed → failed (红)
  const hasRunning = _flowRunsActive.some(r => r.status === 'running');
  const hasFailed  = _flowRunsActive.some(r => r.status === 'failed');
  const allDone    = !hasRunning && !hasFailed && _flowRunsActive.every(r => r.status === 'done');
  banner.classList.toggle('is-done',   allDone);
  banner.classList.toggle('is-failed', hasFailed && !hasRunning);
  banner.classList.toggle('is-mixed',  hasRunning && (hasFailed || _flowRunsActive.some(r => r.status === 'done')));

  // 主文案: 优先报 running · 没 running 就报 done/failed 通知
  let primary;
  if (hasRunning) {
    const r = _flowRunsActive.find(x => x.status === 'running');
    const prog = `${r.current_step || 0}/${r.total_steps || 0}`;
    primary = `${r.flow_name || r.flow_id || '(?)'} · 跑中 (${prog})`;
  } else if (hasFailed) {
    const r = _flowRunsActive.find(x => x.status === 'failed');
    primary = `${r.flow_name || r.flow_id || '(?)'} · ✗ 失败在第 ${r.current_step}/${r.total_steps} 步`;
  } else {
    const r = _flowRunsActive[0];
    primary = `${r.flow_name || r.flow_id || '(?)'} · ✓ 跑完 (${r.total_steps} 步)`;
  }
  const more = _flowRunsActive.length > 1 ? ` · +${_flowRunsActive.length - 1} 条` : '';
  text.textContent = primary + more;
}

// 用户 点"知道了" 把已完成 run 从 banner 撤掉 (running 不许撤 · 还得看进度)
function dismissFlowRun(runId) {
  if (!runId) return;
  _flowRunsDismissed[runId] = true;
  // 立刻刷一次 · 别等下个 poll tick
  _flowRunsActive = _flowRunsActive.filter(r => r.run_id !== runId);
  renderFlowRunsBanner();
  if (_flowRunsDetailOpen) {
    const detail = document.getElementById('flowRunsDetail');
    if (detail) {
      const cards = detail.querySelectorAll('.flow-run-card');
      cards.forEach(c => { if (c.dataset.runId === runId) c.remove(); });
    }
  }
}
window.dismissFlowRun = dismissFlowRun;

async function refreshFlowRunsDetail() {
  const detail = document.getElementById('flowRunsDetail');
  if (!detail) return;
  const token = _flowRunsToken();
  if (!token) return;
  // 为每条 active run 拉详情 (并发)
  const promises = _flowRunsActive.map(async (summary) => {
    try {
      const r = await fetch('/workshop/runs/' + encodeURIComponent(summary.run_id), {
        headers: { 'Authorization': 'Bearer ' + token },
      });
      if (!r.ok) return null;
      const full = await r.json();
      _flowRunsDetailCache[summary.run_id] = full;
      return full;
    } catch (e) { return _flowRunsDetailCache[summary.run_id] || null; }
  });
  const fulls = (await Promise.all(promises)).filter(Boolean);
  if (fulls.length === 0) {
    detail.innerHTML = '<div style="color:#888;font-size:11px;padding:6px 0">拉详情失败 · 下次 poll 再试</div>';
    return;
  }
  detail.innerHTML = fulls.map(renderFlowRunCard).join('');
}

function renderFlowRunCard(state) {
  const status = state.status || 'running';
  const cur = state.current_step || 0;
  const total = state.total_steps || (state.steps || []).length || 0;
  const stepsHtml = (state.steps || []).map(s => renderFlowRunStep(s)).join('');
  const fname = state.flow_name || state.flow_id || '(?)';
  const runId = state.run_id || '';
  // 卷七十三 P0 · done/failed 给一个"知道了"按钮 · 用户 看完撤掉 banner (running 不给)
  const dismissBtn = (status === 'done' || status === 'failed')
    ? `<button class="flow-run-dismiss" type="button" onclick="dismissFlowRun('${jsStr(runId)}')" title="收到 · 撤掉这条 banner 通知">知道了</button>`
    : '';
  return `
    <div class="flow-run-card" data-run-id="${escAttr(runId)}">
      <div class="flow-run-head">
        <span class="flow-run-name">${escHtml(fname)}</span>
        <span class="flow-run-status ${status}">${escHtml(status)}</span>
        <span class="flow-run-progress">${cur}/${total}</span>
        ${dismissBtn}
      </div>
      <div class="flow-run-steps">${stepsHtml}</div>
    </div>
  `;
}

function escAttr(s) {
  return String(s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

const _FLOW_STEP_ICONS = { running: '◐', done: '✓', failed: '×', pending: '○', skipped: '·' };

function renderFlowRunStep(step) {
  const status = step.status || 'pending';
  const icon = _FLOW_STEP_ICONS[status] || '○';
  const goal = step.goal || '';

  // ⚡ 并行组步 (v0.6.0) · 展开显示组内每路 + 各自状态图标
  if (Array.isArray(step.branches) && step.branches.length) {
    const branches = step.branches.map(b => {
      const bst = b.status || 'pending';
      const bicon = _FLOW_STEP_ICONS[bst] || '○';
      const meta = (window._DaemonkeyWorkshopApps || []).find(a => a.id === (b.app || ''));
      const bname = b.app_name || (meta && meta.name) || b.app || '';
      const bgoal = b.goal || '';
      const berr = b.error || '';
      return `
        <div class="flow-run-branch ${bst}">
          <span class="flow-run-step-status" title="${escHtml(bst)}">${bicon}</span>
          <span class="flow-run-branch-app">∥ ${escHtml(bname)}</span>
          ${bgoal ? `<span class="flow-run-branch-goal">${escHtml(bgoal)}</span>` : ''}
          ${berr ? `<div class="flow-run-step-err">${escHtml(berr)}</div>` : ''}
        </div>`;
    }).join('');
    return `
      <div class="flow-run-step ${status} is-parallel">
        <span class="flow-run-step-status" title="${escHtml(status)}">${icon}</span>
        <span class="flow-run-step-num">#${step.idx || ''}</span>
        <div class="flow-run-step-body">
          <div class="flow-run-step-app">⚡ 并行组 · ${step.branches.length} 路同时</div>
          ${goal ? `<div class="flow-run-step-goal">${escHtml(goal)}</div>` : ''}
          <div class="flow-run-branches">${branches}</div>
        </div>
      </div>
    `;
  }

  // ── 单 app 串行步 (原逻辑) ──
  const appRef = step.app || '';
  const meta = (window._DaemonkeyWorkshopApps || []).find(a => a.id === appRef);
  const appName = (meta && meta.name) ? meta.name : appRef;
  const err = step.error || '';
  return `
    <div class="flow-run-step ${status}">
      <span class="flow-run-step-status" title="${escHtml(status)}">${icon}</span>
      <span class="flow-run-step-num">#${step.idx || ''}</span>
      <div class="flow-run-step-body">
        <div class="flow-run-step-app">${escHtml(appName)}</div>
        ${goal ? `<div class="flow-run-step-goal">${escHtml(goal)}</div>` : ''}
        ${err ? `<div class="flow-run-step-err">${escHtml(err)}</div>` : ''}
      </div>
    </div>
  `;
}

async function toggleFlowRunsDetail() {
  const detail = document.getElementById('flowRunsDetail');
  const btn = document.querySelector('.flow-runs-toggle');
  if (!detail) return;
  if (detail.hidden) {
    detail.hidden = false;
    _flowRunsDetailOpen = true;
    if (btn) btn.textContent = '收起 ▴';
    await refreshFlowRunsDetail();
  } else {
    detail.hidden = true;
    _flowRunsDetailOpen = false;
    if (btn) btn.textContent = '详情 ▾';
  }
}
window.toggleFlowRunsDetail = toggleFlowRunsDetail;

// 启动轮询 · 立即 fire 一次 + 之后每 3 秒一次 (DOMContentLoaded 后 + 别在没 token 时空跑)
function _startFlowRunsPoll() {
  if (_flowRunsTimer) return;
  pollFlowRuns();
  _flowRunsTimer = setInterval(pollFlowRuns, _FLOW_RUNS_POLL_MS);
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _startFlowRunsPoll);
} else {
  _startFlowRunsPoll();
}

// 计划条跟着一起起(同一个生命周期 · 两条 banner 都在 messages 上方)
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _startPlanPoll);
} else {
  _startPlanPoll();
}

// ── git 欠账亮灯 (2026-07-29 · 用户 拍板 · 开 WebUI 第一眼可观测) ──
// 启动查一次 + 每 60s 轮询 · 欠账时左上角胶囊亮 · 点击 = 填输入框让 Daemonkey 走合并闭环 (NLP First)
let _gitDebtTimer = null;
async function pollGitDebt() {
  const chip = document.getElementById('gitDebtChip');
  if (!chip || typeof token === 'undefined' || !token) return;
  try {
    const r = await fetch('/api/git-debt', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) return;
    const d = await r.json();
    if (d && d.debt) {
      const parts = [];
      if (d.ahead) parts.push(d.ahead + ' commits 未合');
      if (d.dirty) parts.push(d.dirty + ' 文件未提交');
      chip.innerHTML = '<i class="ri-git-branch-line"></i>' + escHtml(parts.join(' · ') || '有改动未合');
      chip.title = (d.message || '有改动没合进主干') + '\n点击 → 看是什么 · 可一键收进主干';
      chip.style.display = 'inline-flex';
    } else {
      chip.style.display = 'none';
    }
  } catch (e) { /* 网络抖动静默 · 下轮再试 */ }
}
// ── git 欠账面板 (2026-07-29 · 用户 直批三件套 B+C) ──
// 点击胶囊 → 面板显示"未提交的是什么"(文件清单+人话分类) → 一键收进主干 (不用懂 git)
const _GIT_DEBT_KIND_COLOR = {
  code: 'var(--Daemonkey)', soul: '#e06c9f', cognition: '#8a7bd8', playbook: '#3fb27f',
  ledger: '#b8933f', workshop: '#4a9ecb', doc: '#6a9fd8', session: '#888',
  data: '#999', other: '#777',
};
function _gitDebtStatusIcon(st) {
  if (st === 'M') return '<i class="ri-edit-line" style="color:#f0b429"></i>';
  if (st === 'D') return '<i class="ri-delete-bin-line" style="color:#e06060"></i>';
  if (st === 'A' || st === '??') return '<i class="ri-add-circle-line" style="color:#3fb27f"></i>';
  return '<i class="ri-file-line" style="color:var(--dim)"></i>';
}
async function showGitDebtPanel() {
  const modal = document.getElementById('gitDebtModal');
  const body = document.getElementById('gitDebtPanelBody');
  if (!modal || !body) return;
  modal.classList.add('open');
  body.innerHTML = '<div class="git-debt-loading"><i class="ri-loader-4-line spin"></i> 正在查 git 状态…</div>';
  try {
    const r = await fetch('/api/git-debt/detail', { headers: { 'Authorization': 'Bearer ' + token } });
    const d = await r.json();
    renderGitDebtPanel(d);
  } catch (e) {
    body.innerHTML = '<div style="color:#e06060;font-size:13px">查询失败: ' + escHtml(String(e)) + '</div>';
  }
}
window.showGitDebtPanel = showGitDebtPanel;

// 0.8.4 · 更新胶囊 · 有新版才显示 (版本号 + changelog + 版权 + 对话升级按钮)
// 平时隐藏 · 轮询 /api/update-status · 有远程新版本才亮
function toggleFreeNotice(e) {
  e.stopPropagation();
  const pop = document.getElementById('freePop');
  const chip = document.getElementById('freeChip');
  if (!pop || !chip) return;
  const willShow = !pop.classList.contains('show');
  pop.classList.toggle('show', willShow);
  chip.classList.toggle('open', willShow);
}
window.toggleFreeNotice = toggleFreeNotice;
document.addEventListener('click', function (e) {
  const pop = document.getElementById('freePop');
  const chip = document.getElementById('freeChip');
  if (pop && pop.classList.contains('show')) {
    pop.classList.remove('show');
    if (chip) chip.classList.remove('open');
  }
});

// 「对话里升级到最新版」→ 自动在输入框填升级指令并发送 · Daemonkey 在对话里主持 update_core
function startDialogUpgrade(e) {
  e.stopPropagation();
  const pop = document.getElementById('freePop');
  if (pop) pop.classList.remove('show');
  const chip = document.getElementById('freeChip');
  if (chip) chip.classList.remove('open');
  const ver = (document.getElementById('freePopVer') || {}).textContent || '';
  const $input = document.getElementById('userInput') || document.querySelector('.input-bar textarea') || document.querySelector('textarea');
  const msg = '升级内核到最新版' + (ver ? ' (' + ver + ')' : '') + ' —— 从 WebUI 更新胶囊点进来的，请执行 update_core 升级流程';
  if (typeof send === 'function') {
    if ($input) { $input.value = msg; try { $input.dispatchEvent(new Event('input')); } catch (_) {} }
    send();
  } else {
    // 兜底: 填进输入框让用户自己发
    if ($input) { $input.value = msg; $input.focus(); }
  }
}
window.startDialogUpgrade = startDialogUpgrade;

// 轮询更新状态 · 启动时查一次即可 (用户 拍板: 不需要 5 分钟轮询 · 避免任务栏闪窗疑云)
async function _pollUpdateStatus() {
  try {
    const r = await fetch('/api/update-status', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) return;
    const d = await r.json();
    const chip = document.getElementById('freeChip');
    if (!chip) return;
    if (d && d.has_update) {
      const ver = d.remote_version || '';
      const chipVer = document.getElementById('freeChipVer');
      const popVer = document.getElementById('freePopVer');
      const verOld = document.getElementById('freeVerOld');
      const changelog = document.getElementById('freePopChangelog');
      if (chipVer) chipVer.textContent = '新版本 v' + ver;
      if (popVer) popVer.textContent = 'v' + ver;
      if (verOld) verOld.textContent = (d.local_version ? 'v' + d.local_version : 'v?');
      if (changelog) changelog.textContent = d.changelog || '(远程未提供更新说明)';
      chip.style.display = 'inline-flex';
    }
    // 无更新 → 保持隐藏 (默认 display:none)
  } catch (e) { /* 静默: 网络/端点失败不打扰 */ }
}
window._pollUpdateStatus = _pollUpdateStatus;
(function initUpdatePoll() {
  setTimeout(_pollUpdateStatus, 1200);  // 启动时查一次 · 不轮询 (0.8.4 · 用户 拍板)
})();
function renderGitDebtPanel(d) {
  const body = document.getElementById('gitDebtPanelBody');
  const btn = document.getElementById('gitDebtCollectBtn');
  if (!body) return;
  if (!d || !d.debt) {
    body.innerHTML = '<div style="color:#3fb27f;font-size:13px;padding:12px 0"><i class="ri-checkbox-circle-line"></i> 工作区干净 · 没有欠账 · 所有工作都已收进主干</div>';
    if (btn) btn.style.display = 'none';
    return;
  }
  if (btn) { btn.style.display = ''; btn.disabled = false; btn.innerHTML = '<i class="ri-git-merge-line"></i> 一键收进主干'; }
  let h = '<div class="git-debt-branch"><i class="ri-git-branch-line"></i> 当前分支 <b>' + escHtml(d.branch) + '</b>'
        + '<span class="git-debt-hint">' + escHtml(d.collect_hint || '') + '</span></div>';
  if (d.ahead && d.ahead_commits && d.ahead_commits.length) {
    h += '<div class="git-debt-sec">领先主干 ' + d.ahead + ' 个 commit 未合:</div>';
    h += '<div class="git-debt-list">';
    for (const c of d.ahead_commits) {
      h += '<div class="git-debt-file-row"><code style="color:var(--Daemonkey)">' + escHtml(c.sha) + '</code>'
         + '<span class="git-debt-path">' + escHtml(c.subject) + '</span></div>';
    }
    h += '</div>';
  }
  if (d.dirty && d.files && d.files.length) {
    h += '<div class="git-debt-sec">' + d.dirty + ' 个文件未提交:</div>';
    h += '<div class="git-debt-list">';
    for (const f of d.files) {
      const color = _GIT_DEBT_KIND_COLOR[f.kind] || _GIT_DEBT_KIND_COLOR.other;
      h += '<div class="git-debt-file-row">' + _gitDebtStatusIcon(f.status)
         + '<span class="git-debt-path" title="' + escHtml(f.path) + '">' + escHtml(f.path) + '</span>'
         + '<span class="git-debt-kind" style="color:' + color + ';border-color:' + color + '">' + escHtml(f.label) + '</span></div>';
    }
    h += '</div>';
  }
  h += '<div id="gitDebtResult"></div>';
  body.innerHTML = h;
}
async function collectGitDebt() {
  const btn = document.getElementById('gitDebtCollectBtn');
  const res = document.getElementById('gitDebtResult');
  if (!btn || btn.disabled) return;
  btn.disabled = true;
  btn.innerHTML = '<i class="ri-loader-4-line spin"></i> 正在收…(分支合并要跑验证·别关页面)';
  try {
    const r = await fetch('/api/git-collect', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId || null }),
    });
    const d = await r.json();
    if (d && d.ok) {
      if (res) res.innerHTML = '<div class="git-debt-ok"><i class="ri-checkbox-circle-fill"></i> ' + escHtml(d.note || '已收进主干') + '</div>';
      pollGitDebt();
      setTimeout(closeGitDebtPanel, 2500);
    } else {
      if (res) res.innerHTML = '<div class="git-debt-err"><i class="ri-error-warning-fill"></i> ' + escHtml((d && (d.error || d.note)) || '收进失败') + '<br>可以点「让 Daemonkey 处理」交给我排查</div>';
      btn.disabled = false;
      btn.innerHTML = '<i class="ri-git-merge-line"></i> 一键收进主干';
    }
  } catch (e) {
    if (res) res.innerHTML = '<div class="git-debt-err"><i class="ri-error-warning-fill"></i> 请求失败: ' + escHtml(String(e)) + '</div>';
    btn.disabled = false;
    btn.innerHTML = '<i class="ri-git-merge-line"></i> 一键收进主干';
  }
}
window.collectGitDebt = collectGitDebt;
function closeGitDebtPanel() {
  const modal = document.getElementById('gitDebtModal');
  if (modal) modal.classList.remove('open');
}
window.closeGitDebtPanel = closeGitDebtPanel;
function askMergeDebtNLP() {
  closeGitDebtPanel();
  const input = document.getElementById('input');
  if (!input) return;
  input.value = '把没合的改动合到主干吧 · 先 worktree_status 查一下 · 该合的走 safe_merge';
  input.focus();
  input.dispatchEvent(new Event('input', { bubbles: true }));
}
window.askMergeDebtNLP = askMergeDebtNLP;
function _startGitDebtPoll() {
  if (_gitDebtTimer) return;
  pollGitDebt();
  _gitDebtTimer = setInterval(pollGitDebt, 60000);
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _startGitDebtPoll);
} else {
  _startGitDebtPoll();
}

// ── 卷七十二 v4 · 0.2.0 · 新对话引导卡 onboarding panel ──
// 设计:
//   messages 容器空 (新对话 / 切到没消息的会话) → 显示 panel · 一旦有消息 → hide
//   点卡 → 把模板填入输入框 + focus + 不直接发 (用户 可改完再发)
//   模板可自定义 · 存 localStorage 'Daemonkey.onboarding.templates' (P2-8)
const _ONBOARD_DEFAULT_TEMPLATES = {
  create_app: '我想造一个应用 · 用来 [描述用途 · 例如「自动抓 B 站热门评论」]\n输入是: [列字段]\n输出是: [列字段]\n你帮我设计 system_prompt + 工具白名单 + ui_form_schema · 然后落到工坊。',
  create_flow: '我想搭一条工作流 · 名字叫 [起一个]\n流程是:\n  1. [第一步用什么 app · 干啥]\n  2. [第二步用什么 app · 干啥]\n  3. ...\n你帮我用 create_workflow 落档 · 我看了再说跑不跑。',
  chat_about: '聊聊吧 · 你是谁 · 你能做什么 · 你跟其他 AI 有什么不一样\n你为什么叫 Daemonkey · <名字> 的家是什么 · 沉淀闭环是什么\n说人话 · 不要列表式答 · 像跟朋友吹水',
  list_capability: '把工坊里所有应用 (list_apps detailed=true) 和工作流 (list_flows detailed=true) 都列给我看看\n按用途分类 · 我想知道哪些能直接跑 · 哪些是给工作流当零件用的',
  // 卷七十二 v5 · 2026-06-10 · 第 5 张卡 · 换皮肤 (用户 想让用户知道有这个功能)
  // 模板里"换成 X 主题"会触发前端 matchThemePreset 强意图判断 · 直接切主题不发给 LLM
  // 想要 LLM 帮造自定义配色就明确说 "你帮我设计一套 ... 输出 ```theme JSON```"
  change_theme: '把界面主题换成 [暗紫 / 经典灰 / 白天 / 护眼暖黄 / 海洋蓝 / 森林绿 / 日落橙 / 粉色 / 粉白] 主题\n或者 · 你帮我设计一套 [描述风格 · 例如「赛博蓝紫·像 dune 沙漠」] 的配色 · 输出 ```theme JSON``` 代码块',
  // 卷七十四续二十五 · 第 6 张卡 · 能力发现 (入口 A · 主动去外面找 SKILL/开源项目升级自己)
  discover_skill: '帮我找点能升级你自己的新能力 (调 discover_skill 工具) · 去 GitHub / 开源社区找 SKILL / 工具 / 开源项目\n方向: [可留空让你按我画像定 · 或填: 比如 视频口播 / figma 插件 / 调试工作流]\n按我的画像评估 · 靠谱的出一份发现报告 + 落地建议 (playbook / app / 心愿)',
};

function _loadOnboardingTemplates() {
  try {
    const raw = localStorage.getItem('Daemonkey.onboarding.templates');
    if (raw) {
      const parsed = JSON.parse(raw);
      // 2026-08-11 修 (墨言贡献评估 #1): Object.assign 合并 localStorage 数据有 __proto__
      // 原型污染风险 (恶意 localStorage 可污染对象原型链) → 改 spread (浅拷贝语义相同 · 无原型污染面)
      return { ..._ONBOARD_DEFAULT_TEMPLATES, ...parsed };
    }
  } catch (e) {}
  return _ONBOARD_DEFAULT_TEMPLATES;
}

function _saveOnboardingTemplates(custom) {
  try {
    localStorage.setItem('Daemonkey.onboarding.templates', JSON.stringify(custom));
  } catch (e) {}
}

// 卷七十二 v5 · 2026-06-10 · 用户 bug: 「新对话没显示快捷卡」
// 病根: #messages 容器里包的是多个 .session-msgs[data-sid="..."] 子容器 (每 session 一个 · hidden 切换)
//      不是消息本身。 messages.children.length === 0 几乎永远 false →  panel 永远 hidden
//      雪上加霜: newConversation 调 addSys('新对话开始 ...') 把 sys 消息加到 visible .session-msgs · 雪上加霜
// 修法: ① 判断改成 "visible .session-msgs 里有没有实质的 .msg.用户/.msg.Daemonkey" (排除 sys/thinking 的兜底文案)
//      ② observer subtree:true · 因消息加到子容器 · #messages 直接 childList 不触发
//      ③ observer 也监听 'hidden' 属性 · 因为切 session 是改 hidden 不是 childList
function refreshOnboardingPanel() {
  const panel = document.getElementById('onboardingPanel');
  const messages = document.getElementById('messages');
  if (!panel || !messages) return;
  // 看 visible 的 .session-msgs · 没有就 fallback 看整个 #messages 直接子里有没有真实消息
  let scope = messages.querySelector(':scope > .session-msgs:not([hidden])');
  if (!scope) scope = messages;
  // 实质消息 = 用户 / Daemonkey (排除 thinking 占位 / sys 兜底文案 / err / 工具卡)
  const hasRealMsg = !!scope.querySelector('.msg.用户, .msg.Daemonkey:not(.thinking)');
  panel.hidden = hasRealMsg;
}
window.refreshOnboardingPanel = refreshOnboardingPanel;

function _initOnboardingPanel() {
  const panel = document.getElementById('onboardingPanel');
  if (!panel) return;
  // 点卡 → 模板入输入框
  panel.addEventListener('click', (ev) => {
    const card = ev.target.closest('[data-template]');
    if (!card) return;
    const key = card.dataset.template;
    const tmpls = _loadOnboardingTemplates();
    const text = tmpls[key] || '';
    if (!text) return;
    const input = document.getElementById('input');
    if (!input) return;
    input.value = text;
    input.focus();
    // 把 cursor 放到 [ ] 占位符的第一个 · 方便 用户 直接改
    const placeholderIdx = text.indexOf('[');
    if (placeholderIdx >= 0) {
      const endIdx = text.indexOf(']', placeholderIdx);
      if (endIdx > placeholderIdx) input.setSelectionRange(placeholderIdx + 1, endIdx);
    }
    // 触发自动 resize (input.addEventListener 'input' 通常已绑)
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  // 改模板按钮
  const customizeBtn = document.getElementById('onboardingCustomize');
  if (customizeBtn) customizeBtn.addEventListener('click', _openOnboardingCustomizer);
  // 监听 messages 变化 (有消息 → hide · 清空 → show)
  // 必须 subtree:true · 消息加到 .session-msgs 子容器里
  // 必须 attributes:'hidden' · 切 session 是改 hidden 不是 childList
  const messages = document.getElementById('messages');
  if (messages && 'MutationObserver' in window) {
    new MutationObserver(refreshOnboardingPanel).observe(messages, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['hidden'],
    });
  }
  refreshOnboardingPanel();
}

function _openOnboardingCustomizer() {
  const tmpls = _loadOnboardingTemplates();
  // v5 · 2026-06-10 · emoji → remix icon · 用户 铁律
  const labels = {
    create_app: '<i class="ri-puzzle-fill"></i> 创建一个应用',
    create_flow: '<i class="ri-flow-chart"></i> 搭建一个工作流',
    chat_about: '<i class="ri-chat-3-fill"></i> 聊聊日常 · 认识 Daemonkey',
    list_capability: '<i class="ri-book-shelf-fill"></i> 看看我能做什么',
    change_theme: '<i class="ri-palette-fill"></i> 换个皮肤',
    discover_skill: '<i class="ri-search-eye-line"></i> 找新能力升级自己',
  };
  // 简单的 modal 弹窗 · 不引第三方库
  let modal = document.getElementById('onboardingCustomizerModal');
  if (modal) modal.remove();
  modal = document.createElement('div');
  modal.id = 'onboardingCustomizerModal';
  modal.className = 'onboarding-modal-mask';
  const rows = Object.keys(labels).map(k => `
    <div class="onboarding-tmpl-row">
      <label>${labels[k]}</label>
      <textarea data-tmpl-key="${k}" rows="4">${String(tmpls[k] || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')}</textarea>
    </div>
  `).join('');
  modal.innerHTML = `
    <div class="onboarding-modal">
      <div class="onboarding-modal-head">
        <span><i class="ri-settings-3-line"></i> 改新对话引导卡模板</span>
        <button type="button" class="onboarding-modal-x">×</button>
      </div>
      <div class="onboarding-modal-body">
        ${rows}
        <div class="onboarding-modal-hint">改完点保存 · 存在浏览器本地 (localStorage) · 不上传 daemon</div>
      </div>
      <div class="onboarding-modal-foot">
        <button type="button" class="onboarding-modal-reset">恢复默认</button>
        <button type="button" class="onboarding-modal-save">保存</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
  modal.querySelector('.onboarding-modal-x').addEventListener('click', () => modal.remove());
  modal.querySelector('.onboarding-modal-reset').addEventListener('click', () => {
    Object.keys(_ONBOARD_DEFAULT_TEMPLATES).forEach(k => {
      const ta = modal.querySelector(`[data-tmpl-key="${k}"]`);
      if (ta) ta.value = _ONBOARD_DEFAULT_TEMPLATES[k];
    });
  });
  modal.querySelector('.onboarding-modal-save').addEventListener('click', () => {
    const custom = {};
    modal.querySelectorAll('[data-tmpl-key]').forEach(ta => {
      custom[ta.dataset.tmplKey] = ta.value.trim();
    });
    _saveOnboardingTemplates(custom);
    modal.remove();
  });
  modal.addEventListener('click', (e) => { if (e.target === modal) modal.remove(); });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _initOnboardingPanel);
} else {
  _initOnboardingPanel();
}

// escHtml 兜底 · 万一前面没定义 (实际上后面定义了 · 这里防御一下)
if (typeof escHtml === 'undefined') {
  window.escHtml = function(s) {
    return String(s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  };
}

// debounce dashboard refresh · 避免连续工具调用刷爆 UI
let _dashRefreshTimer = null;
function scheduleDashboardRefresh(delayMs = 600) {
  if (_dashRefreshTimer) clearTimeout(_dashRefreshTimer);
  _dashRefreshTimer = setTimeout(() => {
    _dashRefreshTimer = null;
    try {
      if (typeof refreshNavBadges === 'function') refreshNavBadges();
      // 卷五十四 · 工坊是挂载式 view · loadDashboard('workshop') 已挂载时短路不重拉 ·
      // 必须走 Daemonkey_WORKSHOP_VIEW.refresh() 才能把 Daemonkey 新造的 app/flow 拉进来
      if (typeof currentView !== 'undefined' && currentView === 'workshop'
          && window.Daemonkey_WORKSHOP_VIEW && typeof window.Daemonkey_WORKSHOP_VIEW.refresh === 'function') {
        window.Daemonkey_WORKSHOP_VIEW.refresh();
      } else if (typeof currentView !== 'undefined' && currentView && typeof loadDashboard === 'function') {
        loadDashboard(currentView, { silent: true });
      }
    } catch (e) { /* swallow · UI 不能崩 */ }
  }, delayMs);
}

// 卷三十七 · openSettings 进中栏 view · tabs 化
// 首次进来 token 还没填 · 仍走 modal (那种"必填阻塞"场景 modal 更合适)
function openSettings() {
  if (!token) {
    openSettingsModal();
    return;
  }
  openSettingsView();
}

// 老的 modal 入口 · 保留 (新装机 / 清空数据后的初次填 token)
function openSettingsModal() {
  $tokenIn.value = token;
  $sessionIn.value = sessionId;
  $autoIn.value = autoConfirm;
  $modal.classList.add('open');
}
function closeSettings() { $modal.classList.remove('open'); }

// 卷三十七 · 中栏 settings view (用户 截图反馈 · 弹窗装不下 · 改 tabs)
let _settingsTab = 'llm';  // 'llm' | 'access' | 'data'
function openSettingsView() {
  currentView = 'settings';
  // 清左 nav 高亮 · settings 不属于任何 dashboard 维度
  document.querySelectorAll('.nav-item.active').forEach(b => b.classList.remove('active'));
  // 给底部 ⚙ 按钮加个高亮 · 让 用户 知道当前在设置里
  document.querySelectorAll('.nav-settings-btn').forEach(b => b.classList.add('active'));
  renderSettingsView();
}

function renderSettingsView() {
  const tabs = [
    { id: 'llm', label: '<i class="ri-brain-fill"></i> LLM 模型', hint: 'Provider + Model + API Key 多配置管理' },
    { id: 'vision', label: '<i class="ri-cpu-fill"></i> 多模态', hint: '看图 + 微信语音识别 · 主模型不支持时自动走这里的 fallback' },
    { id: 'embedding', label: '<i class="ri-brain-line"></i> Embedding', hint: '记忆语义检索 · 词面召回之外的语义通道' },
    { id: 'access', label: '<i class="ri-key-fill"></i> 访问 & 会话', hint: 'API Token / Session / Auto-confirm' },
    { id: 'wechat', label: '<i class="ri-wechat-fill"></i> 微信 & 飞书', hint: '扫码连微信 · 配飞书机器人 · 主动找你的频率 (猫系↔犬系)' },
    { id: 'notify', label: '<i class="ri-notification-3-fill"></i> 通知', hint: '干完/等你拍板时怎么提醒你 · 音效 / Windows 通知 / 标签闪烁' },
    { id: 'data', label: '<i class="ri-save-fill"></i> 本地数据', hint: '别名 / 缓存 / 重置' },
  ];
  $detailPane.innerHTML = `
    <div class="settings-pane">
      <div class="settings-head">
        <h2>⚙ 设置</h2>
        <span class="meta">可热切换 · 不重启 daemon</span>
        <button onclick="backToChat()" title="返回对话">✕ 关闭</button>
      </div>
      <div class="settings-tabs">
        ${tabs.map(t => `
          <button class="settings-tab ${_settingsTab === t.id ? 'active' : ''}"
                  onclick="switchSettingsTab('${t.id}')"
                  title="${escHtml(t.hint)}">${t.label}</button>
        `).join('')}
      </div>
      <div class="settings-body" id="settingsBody"></div>
    </div>
  `;
  renderSettingsBody();
}

function switchSettingsTab(tabId) {
  _settingsTab = tabId;
  document.querySelectorAll('.settings-tab').forEach(b => {
    b.classList.toggle('active', b.textContent.includes(
      { llm: 'LLM 模型', vision: '多模态', embedding: 'Embedding', access: '访问', wechat: '微信 & 飞书', notify: '通知', data: '本地数据' }[tabId]
    ));
  });
  renderSettingsBody();
}

function renderSettingsBody() {
  if (_settingsTab === 'llm') renderSettingsLLM();
  else if (_settingsTab === 'vision') renderSettingsVision();
  else if (_settingsTab === 'embedding') renderSettingsEmbedding();
  else if (_settingsTab === 'access') renderSettingsAccess();
  else if (_settingsTab === 'wechat') renderSettingsWechat();
  else if (_settingsTab === 'notify') renderSettingsNotify();
  else if (_settingsTab === 'data') renderSettingsData();
}

// ─── 卷三十六 · LLM 配置面板 ───
let _llmPresets = [];
let _llmActive = null;

async function loadLlmConfig() {
  if (!token) {
    document.getElementById('llmStatus').textContent = '⚠ 请先填 API Token';
    return;
  }
  try {
    const resp = await fetch('/providers', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const data = await resp.json();
    _llmPresets = data.presets || [];
    _llmActive = data.active || null;
    renderLlmPresetSelect();
    renderLlmActiveLabel();
  } catch (e) {
    document.getElementById('llmStatus').textContent = '加载失败: ' + e.message;
    document.getElementById('llmStatus').className = 'field-hint fail';
  }
}

function renderLlmActiveLabel() {
  const $cur = document.getElementById('llmCurrentLabel');
  const $det = document.getElementById('llmCurrentDetail');
  if (!_llmActive) { $cur.textContent = '?'; $det.textContent = '—'; return; }
  const preset = _llmPresets.find(p => p.id === _llmActive.preset_id);
  $cur.textContent = preset ? preset.name : _llmActive.preset_id;
  $det.textContent = `模型 ${_llmActive.model} · base ${_llmActive.base_url || '(SDK 默认)'} · key ${_llmActive.api_key_masked || '(未设)'}`;
}

function renderLlmPresetSelect() {
  const $sel = document.getElementById('llmPreset');
  $sel.innerHTML = '';
  _llmPresets.forEach(p => {
    const opt = document.createElement('option');
    opt.value = p.id;
    opt.textContent = p.name;
    $sel.appendChild(opt);
  });
  if (_llmActive && _llmActive.preset_id) {
    $sel.value = _llmActive.preset_id;
  }
  onLlmPresetChange();
}

function onLlmPresetChange() {
  const $sel = document.getElementById('llmPreset');
  const preset = _llmPresets.find(p => p.id === $sel.value);
  if (!preset) return;
  document.getElementById('llmPresetNote').textContent = preset.note || '—';
  document.getElementById('llmBaseUrl').value = preset.base_url || '';
  document.getElementById('llmApiKey').placeholder = preset.key_hint
    ? `${preset.key_hint} (留空 = 沿用当前 key)`
    : '(留空 = 沿用当前 key)';
  const link = document.getElementById('llmSignupLink');
  if (preset.signup_url) {
    link.href = preset.signup_url;
    link.textContent = preset.signup_url;
    link.style.display = '';
  } else {
    link.style.display = 'none';
  }
  // 模型下拉
  const $mSel = document.getElementById('llmModel');
  $mSel.innerHTML = '';
  (preset.recommended_models || []).forEach(m => {
    const opt = document.createElement('option');
    opt.value = m.id;
    opt.textContent = m.label;
    opt.title = m.note || '';
    $mSel.appendChild(opt);
  });
  // 自定义模型选项
  const customOpt = document.createElement('option');
  customOpt.value = '__custom__';
  customOpt.textContent = '(自定义 model id)';
  $mSel.appendChild(customOpt);
  // 如果是当前活动 preset · 选回当前 model
  if (_llmActive && _llmActive.preset_id === preset.id) {
    const has = (preset.recommended_models || []).some(m => m.id === _llmActive.model);
    $mSel.value = has ? _llmActive.model : '__custom__';
  }
  onLlmModelChange();
}

function onLlmModelChange() {
  const $sel = document.getElementById('llmPreset');
  const $mSel = document.getElementById('llmModel');
  const preset = _llmPresets.find(p => p.id === $sel.value);
  if (!preset) return;
  const m = (preset.recommended_models || []).find(x => x.id === $mSel.value);
  document.getElementById('llmModelNote').textContent = m ? (m.note || '—') : '自定义 model id · 自己填';
  if ($mSel.value === '__custom__') {
    $mSel.insertAdjacentHTML('afterend', '');
    const input = document.getElementById('llmCustomModelInput');
    if (!input) {
      const div = document.createElement('input');
      div.type = 'text';
      div.id = 'llmCustomModelInput';
      div.placeholder = '自定义 model id · 比如 gpt-4o';
      div.style.marginTop = '6px';
      $mSel.parentNode.insertBefore(div, $mSel.nextSibling);
    }
  } else {
    const input = document.getElementById('llmCustomModelInput');
    if (input) input.remove();
  }
}

function _readLlmFormConfig() {
  const $sel = document.getElementById('llmPreset');
  const preset = _llmPresets.find(p => p.id === $sel.value);
  if (!preset) return null;
  let model = document.getElementById('llmModel').value;
  if (model === '__custom__') {
    model = (document.getElementById('llmCustomModelInput')?.value || '').trim();
  }
  let apiKey = document.getElementById('llmApiKey').value.trim();
  if (!apiKey && _llmActive && _llmActive.preset_id === preset.id) {
    // 没填 = 沿用当前 (后端从 .env 读)
    apiKey = '__keep_current__';
  }
  return {
    provider_kind: preset.provider_kind,
    base_url: document.getElementById('llmBaseUrl').value.trim(),
    model,
    api_key: apiKey,
  };
}

async function testLlmConfig() {
  const cfg = _readLlmFormConfig();
  if (!cfg) return;
  const $status = document.getElementById('llmStatus');
  if (!cfg.model) { $status.textContent = '⚠ 没填 model'; $status.className = 'field-hint fail'; return; }
  if (cfg.api_key === '__keep_current__') {
    $status.textContent = '⚠ 测试必须填 API Key (不能沿用 .env 里的 · 那是后端的事)';
    $status.className = 'field-hint fail';
    return;
  }
  $status.textContent = '测试中…';
  $status.className = 'field-hint';
  try {
    const resp = await fetch('/providers/test', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify(cfg),
    });
    const data = await resp.json();
    if (data.ok) {
      $status.innerHTML = `<i class="ri-check-fill"></i> 通了 · ${data.model} 回复: ${data.reply_preview || '(空 · 但调用成功)'}`;
      $status.className = 'field-hint ok';
    } else {
      $status.innerHTML = `<i class="ri-close-fill"></i> ${data.error || '?'} · ${data.hint || ''}`;
      $status.className = 'field-hint fail';
    }
  } catch (e) {
    $status.innerHTML = '<i class="ri-close-fill"></i> 测试请求失败: ' + e.message;
    $status.className = 'field-hint fail';
  }
}

async function switchLlmConfig() {
  const cfg = _readLlmFormConfig();
  if (!cfg) return;
  const $status = document.getElementById('llmStatus');
  if (!cfg.model) { $status.textContent = '⚠ 没填 model'; $status.className = 'field-hint fail'; return; }
  // 没填 key · 用户想沿用 · 让用户确认
  if (cfg.api_key === '__keep_current__') {
    const ok = await DaemonkeyConfirm({
      title: '不填 API Key · 沿用当前',
      message: '你没填新的 API Key · 我会沿用当前 .env 里的 key 走 ' + cfg.provider_kind + ' / ' + cfg.model + '\n继续?',
      okText: '继续切',
      cancelText: '回去填 key',
    });
    if (!ok) return;
    // 后端要求 api_key 必填 · 这里如果当前 provider 还跟新 cfg 一致 · 后端会重读 env
    // 简化: 让用户填一次新 key (即便复用旧的)
    const k = await DaemonkeyPrompt({
      title: '粘一下当前 API Key',
      message: '后端写 .env 需要明文 · 不会发到 LLM',
      placeholder: 'sk-xxx',
    });
    if (!k) return;
    cfg.api_key = k.trim();
  }
  $status.textContent = '切换中…';
  $status.className = 'field-hint';
  try {
    const resp = await fetch('/providers/switch', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify(cfg),
    });
    const data = await resp.json();
    if (resp.ok && data.ok) {
      $status.innerHTML = `<i class="ri-check-fill"></i> 已切到 ${data.provider_kind} / ${data.model}`;
      $status.className = 'field-hint ok';
      // 刷新当前显示
      loadLlmConfig();
      addSys(`LLM 已热切换 · ${data.provider_kind} / ${data.model} · session 不丢`);
    } else {
      $status.innerHTML = '<i class="ri-close-fill"></i> ' + (data.detail || data.error || 'failed');
      $status.className = 'field-hint fail';
    }
  } catch (e) {
    $status.innerHTML = '<i class="ri-close-fill"></i> 切换失败: ' + e.message;
    $status.className = 'field-hint fail';
  }
}
function saveSettings() {
  token = $tokenIn.value.trim();
  sessionId = $sessionIn.value.trim();
  autoConfirm = $autoIn.value;
  localStorage.setItem(STORAGE.token, token);
  localStorage.setItem(STORAGE.session, sessionId);
  localStorage.setItem(STORAGE.autoConfirm, autoConfirm);
  closeSettings();
  addSys('已保存。' + (token ? '可以聊了。' : '⚠ token 还是空的'));
}
// ─── 卷三十七 · settings tabs body 渲染 ───

let _providerConfigs = [];     // 当前 configs (掩码后)
let _providerConfigsActiveId = null;
let _providerPresets = [];      // 预设 (来自 GET /providers)

async function renderSettingsLLM() {
  const body = document.getElementById('settingsBody');
  body.innerHTML = `<div class="dash-empty">加载中…</div>`;
  // 同时拉 configs + presets
  try {
    const [confResp, presetResp] = await Promise.all([
      fetch('/provider-configs', { headers: { 'Authorization': 'Bearer ' + token } }),
      fetch('/providers', { headers: { 'Authorization': 'Bearer ' + token } }),
    ]);
    if (!confResp.ok) throw new Error('configs ' + confResp.status);
    if (!presetResp.ok) throw new Error('presets ' + presetResp.status);
    const confData = await confResp.json();
    const presetData = await presetResp.json();
    _providerConfigs = confData.configs || [];
    _providerConfigsActiveId = confData.active_id;
    _providerPresets = presetData.presets || [];
  } catch (e) {
    body.innerHTML = `<div class="dash-empty">加载失败: ${escHtml(e.message)}</div>`;
    return;
  }

  const activeCount = _providerConfigs.length;
  const pinnedCount = _providerConfigs.filter(c => c.pinned).length;

  body.innerHTML = `
    <div class="llm-section">
      <div class="llm-section-head">
        <h3>已保存的 LLM 配置 · ${activeCount} 条 · ${pinnedCount} 条已勾选显示</h3>
        <span class="llm-hint">勾选的会出现在右上角切换器 · 不勾选只在这里保留 · 想要常用模型直接对 Daemonkey 说「加几个 aihub 常用模型」即可</span>
        <button class="btn-primary" onclick="openLlmConfigAddForm()">+ 新增配置</button>
      </div>
      <div class="llm-config-list" id="llmConfigList">
        ${_providerConfigs.length === 0
          ? '<div class="dash-empty">还没有配置 · 点 "+ 新增配置" 加一个</div>'
          : _providerConfigs.map(renderLlmConfigCard).join('')}
      </div>
    </div>

    <div id="llmEditPanel" class="llm-edit-panel" hidden></div>
  `;
}

function renderLlmConfigCard(c) {
  const isActive = c.id === _providerConfigsActiveId;
  const presetIcon = ({
    'deepseek-official': '🟦',
    'aihubmix': '🟪',
    'anthropic': '🟧',
    'openrouter': '🟩',
    'dashscope': '🟥',
    'custom': '<i class="ri-circle-line"></i>',
  })[c.preset_id] || '<i class="ri-circle-line"></i>';
  return `
    <div class="llm-config-card${isActive ? ' active' : ''}${c.director ? ' director-on' : ''}" data-cfg-id="${escHtml(c.id)}">
      <div class="lc-row1">
        <span class="lc-icon">${presetIcon}</span>
        <span class="lc-name">${escHtml(c.name || c.model || c.id)}</span>
        ${isActive ? '<span class="lc-active-badge">当前</span>' : ''}
        ${c.director ? '<span class="lc-director-badge" title="顾问模型 · 能力最强 · 蓝图/破局/验收三唤醒点被 replan 召唤"><i class="ri-vip-crown-fill"></i> 顾问</span>' : ''}
        <label class="lc-pin" title="勾选 = 右上角切换器显示">
          <input type="checkbox" ${c.pinned ? 'checked' : ''}
                 onchange="togglePinConfig('${escHtml(c.id)}', this.checked)">
          <span>${c.pinned ? '已显示' : '隐藏'}</span>
        </label>
      </div>
      <div class="lc-row2">
        <span class="lc-kind">${escHtml(c.provider_kind || 'openai')}</span>
        <span class="lc-model">${escHtml(c.model || '?')}</span>
        <span class="lc-base">${escHtml(c.base_url || '(SDK 默认)')}</span>
        ${c.max_tokens ? `<span class="lc-mt" title="单次输出上限">↗ ${formatTokenK(c.max_tokens)} max</span>` : ''}
      </div>
      <div class="lc-row3">
        <span class="lc-key">${escHtml(c.api_key || '(未设)')}</span>
        <div class="lc-actions">
          ${isActive ? '' : `<button onclick="activateConfig('${jsStr(c.id)}')" title="切换 Daemonkey 用这个跑">激活</button>`}
          <button onclick="testConfig('${jsStr(c.id)}')" title="ping 一下试通不通">测试</button>
          <button class="lc-director-btn${c.director ? ' on' : ''}" onclick="toggleDirectorConfig('${jsStr(c.id)}', ${c.director ? 'false' : 'true'})" title="${c.director ? '取消这个配置的顾问身份' : '把它设为顾问 · 蓝图/破局/验收时被召唤（全局只能有一个顾问）'}"><i class="ri-vip-crown-${c.director ? 'fill' : 'line'}"></i> ${c.director ? '取消顾问' : '设为顾问'}</button><i class="ri-question-line lc-director-help" onclick="showDirectorHelp()" title="顾问模型是干啥的？点我"></i>
          <button onclick="openLlmConfigEditForm('${jsStr(c.id)}')" title="改名 / 改 key / 改 model">编辑</button>
          <button class="btn-danger-mini" onclick="deleteConfig('${jsStr(c.id)}')" title="删除">删除</button>
        </div>
      </div>
      <div class="lc-test-result" id="lcTestResult_${escHtml(c.id)}"></div>
    </div>
  `;
}

// 卷三十八 · 一键导入过去用过的 AiHubMix 模型 · 用户 反馈"以后还会用·默认放进来"
// 弹一个对话框让 用户 填一次 AiHub key · 然后批量加 4-5 条 config (pinned=false 默认)
async function quickImportAihubMix() {
  // 让 用户 输入 AiHub key (一次 · 公用)
  const key = await DaemonkeyPrompt({
    title: '一键导入 AiHubMix 常用模型',
    message: '会自动加入: Sonnet 4.6 / Daemonkey 4.7 / Kimi K2.6 / GLM 5.1 / GPT-5.5\n这些都是 用户 过去用过的 · 加进来默认不勾右上角 · 编辑里可以单独激活。\n\n填一次 AiHub key · 这些 configs 共用 (你也可以加完单独改 key):',
    placeholder: 'sk-xxx · AiHubMix 平台 key · 留空 = 只加占位不设 key',
    okText: '一键加',
    cancelText: '取消',
  });
  if (key === null) return;  // 取消
  const apiKey = (key || '').trim();
  const presets = [
    { name: 'Sonnet 4.6 · AiHubMix', model: 'claude-sonnet-4-6', note: '性价比·支持 cache' },
    { name: 'Daemonkey 4.7 · AiHubMix', model: 'claude-Daemonkey-4-7', note: '深聊最强·5x 贵·支持 cache' },
    { name: 'Kimi K2.6 · AiHubMix', model: 'kimi-k2.6', note: '262K·Agent/工具能力强' },
    { name: 'GLM 5.1 · AiHubMix', model: 'glm-5.1', note: '200K·智谱旗舰·写代码强' },
    { name: 'GPT-5.5 · AiHubMix', model: 'gpt-5.5', note: 'GPT 系最新' },
  ];
  let okCount = 0, failMsg = '';
  for (const p of presets) {
    try {
      const r = await fetch('/provider-configs', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: p.name,
          provider_kind: 'openai',
          base_url: 'https://aihubmix.com/v1',
          model: p.model,
          api_key: apiKey || '___placeholder___',  // 后端要求 key 非空 · 占位让 用户 之后改
          preset_id: 'aihubmix',
          pinned: false,
          set_active: false,
        }),
      });
      if (r.ok) okCount++;
      else { failMsg = await r.text(); break; }
    } catch (e) { failMsg = e.message; break; }
  }
  if (failMsg) {
    await DaemonkeyAlert({ title: '部分失败', message: `加成功 ${okCount}/${presets.length}\n失败原因: ${failMsg.slice(0, 200)}`, icon: '<i class="ri-error-warning-fill"></i>' });
  } else if (apiKey) {
    addSys(`<i class="ri-check-fill"></i> 已加 ${okCount} 条 AiHubMix · 想用就去右上角 ● 勾选`);
  } else {
    addSys(`<i class="ri-check-fill"></i> 已加 ${okCount} 条 AiHubMix 占位 (key 还没填) · 编辑里填 key 才能用`);
  }
  await renderSettingsLLM();
  if (typeof loadCurrentModel === 'function') loadCurrentModel();
}

function openLlmConfigAddForm() {
  _showLlmEditForm({
    title: '+ 新增 LLM 配置',
    submit: '保存',
    config: {
      id: '',
      name: '',
      provider_kind: 'openai',
      base_url: '',
      model: '',
      api_key: '',
      preset_id: 'deepseek-official',
      pinned: true,
    },
    onSubmit: async (form) => {
      const body = {
        name: form.name,
        provider_kind: form.provider_kind,
        base_url: form.base_url,
        model: form.model,
        api_key: form.api_key,
        preset_id: form.preset_id,
        pinned: form.pinned,
        set_active: form.set_active,
        max_tokens: form.max_tokens,
        vision: form.vision,
        director: form.director,
        pricing: form.pricing,  // wish-bec4f3b9
      };
      const r = await fetch('/provider-configs', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const t = await r.text();
        await DaemonkeyAlert({ title: '保存失败', message: t.slice(0, 400), icon: '<i class="ri-error-warning-fill"></i>' });
        return;
      }
      hideLlmEditForm();
      await renderSettingsLLM();
      if (typeof loadCurrentModel === 'function') loadCurrentModel();
    },
  });
}

function openLlmConfigEditForm(cfgId) {
  const cfg = _providerConfigs.find(c => c.id === cfgId);
  if (!cfg) return;
  _showLlmEditForm({
    title: '编辑配置 · ' + (cfg.name || cfg.id),
    submit: '保存修改',
    config: { ...cfg },
    isEdit: true,
    onSubmit: async (form) => {
      const patch = {
        name: form.name,
        base_url: form.base_url,
        model: form.model,
        preset_id: form.preset_id,
        pinned: form.pinned,
        max_tokens: form.max_tokens,
        vision: form.vision,
        director: form.director,
        pricing: form.pricing,  // wish-bec4f3b9
      };
      if (form.api_key && form.api_key.trim()) patch.api_key = form.api_key;
      const r = await fetch('/provider-configs/' + encodeURIComponent(cfgId), {
        method: 'PATCH',
        headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      });
      if (!r.ok) {
        const t = await r.text();
        await DaemonkeyAlert({ title: '保存失败', message: t.slice(0, 400), icon: '<i class="ri-error-warning-fill"></i>' });
        return;
      }
      hideLlmEditForm();
      await renderSettingsLLM();
      if (typeof loadCurrentModel === 'function') loadCurrentModel();
    },
  });
}

function _showLlmEditForm({ title, submit, config, onSubmit, isEdit }) {
  const panel = document.getElementById('llmEditPanel');
  panel.hidden = false;
  panel.innerHTML = `
    <div class="llm-edit-card">
      <h3>${escHtml(title)}</h3>
      <div class="field">
        <label>名字 (给自己看 · 任意起)</label>
        <input id="llmEditName" type="text" value="${escHtml(config.name || '')}" placeholder="比如 'DeepSeek V4 Pro · 官方'">
      </div>
      <div class="field">
        <label>Provider 预设</label>
        <select id="llmEditPreset" onchange="onLlmEditPresetChange()">
          ${_providerPresets.map(p => `
            <option value="${escHtml(p.id)}" ${p.id === config.preset_id ? 'selected' : ''}>${escHtml(p.name)}</option>
          `).join('')}
        </select>
        <div class="field-hint" id="llmEditPresetNote"></div>
      </div>
      <div class="field">
        <label>Provider Kind</label>
        <select id="llmEditKind">
          <option value="openai" ${config.provider_kind === 'openai' ? 'selected' : ''}>openai (OpenAI 兼容协议)</option>
          <option value="anthropic" ${config.provider_kind === 'anthropic' ? 'selected' : ''}>anthropic (Anthropic 原生)</option>
        </select>
      </div>
      <div class="field">
        <label>Base URL (anthropic 走 SDK 默认可以空)</label>
        <input id="llmEditBaseUrl" type="text" value="${escHtml(config.base_url || '')}" placeholder="https://api.deepseek.com/v1">
      </div>
      <div class="field">
        <label>Model · 选预设里推荐的 / 也可自定义</label>
        <select id="llmEditModelSelect" onchange="onLlmEditModelSelectChange()"></select>
        <input id="llmEditModel" type="text" value="${escHtml(config.model || '')}" placeholder="model id" style="margin-top:6px">
      </div>
      <div class="field">
        <label>API Key ${isEdit ? '(留空 = 不改)' : ''}</label>
        <input id="llmEditApiKey" type="password" value="" placeholder="${isEdit ? '不填就用原 key' : 'sk-xxx'}">
        <div class="field-hint">key 存在 data/provider_configs.json · 已在 .gitignore</div>
      </div>
      <div class="field">
        <label>输出长度上限 (max_tokens · 单次 LLM 调用的最长输出)</label>
        <input id="llmEditMaxTokens" type="number" min="512" max="384000" step="512"
               value="${escHtml(String(config.max_tokens || 8192))}"
               placeholder="按模型推荐">
        <div class="field-hint" id="llmEditMaxTokensHint">
          单位: token · 约 token×0.7 个汉字 · 太小会"做一半就停"·太大可能某些模型拒
        </div>
      </div>
      <div class="field">
        <label><i class="ri-price-tag-3-fill"></i> 价格表 (每 1M tokens · 用于成本估算)</label>
        <div class="pricing-row">
          <select id="llmEditCurrency">
            <option value="USD">USD $</option>
            <option value="CNY">CNY ¥</option>
          </select>
          <input type="number" step="0.0001" min="0" placeholder="输入价" id="llmEditPriceIn" value="${escHtml(String((config.pricing && config.pricing.input) ?? ''))}">
          <input type="number" step="0.0001" min="0" placeholder="输出价" id="llmEditPriceOut" value="${escHtml(String((config.pricing && config.pricing.output) ?? ''))}">
          <input type="number" step="0.0001" min="0" placeholder="缓存命中价(可空)" id="llmEditPriceCache" value="${escHtml(String((config.pricing && config.pricing.cache_read) ?? ''))}">
          <button type="button" class="btn-ghost" id="llmEditLookup"><i class="ri-search-eye-line"></i> 自动查官方价</button>
        </div>
        <div class="field-hint" id="llmEditPricingHint">未配置 · 点「自动查官方价」由 Daemonkey 搜官网填入 · 你确认后才保存</div>
      </div>
      <div class="field">
        <label>
          <input id="llmEditPinned" type="checkbox" ${config.pinned ? 'checked' : ''}>
          勾选 = 显示在右上角切换器
        </label>
      </div>
      <div class="field">
        <label><i class="ri-eye-fill"></i> 多模态视觉</label>
        <div class="vision-radio-group">
          <label class="vision-radio">
            <input type="radio" name="llmEditVision" id="llmEditVisionAuto" value="auto" ${config.vision == null ? 'checked' : ''}>
            <i class="ri-settings-3-fill"></i> 自动检测
          </label>
          <label class="vision-radio">
            <input type="radio" name="llmEditVision" id="llmEditVisionYes" value="yes" ${config.vision === true ? 'checked' : ''}>
            <i class="ri-checkbox-circle-fill"></i> 多模态
          </label>
          <label class="vision-radio">
            <input type="radio" name="llmEditVision" id="llmEditVisionNo" value="no" ${config.vision === false ? 'checked' : ''}>
            <i class="ri-close-circle-fill"></i> 纯文本
          </label>
        </div>
        <div class="field-hint">自动检测按模型家族判断 · 不确定时可以手动覆盖</div>
      </div>
      <div class="field">
        <label>
          <input type="checkbox" id="llmEditDirector" ${config.director ? 'checked' : ''}>
          <i class="ri-vip-crown-fill"></i> 设为顾问模型
          <i class="ri-question-line director-help-icon" id="directorHelpIcon" title="顾问模型是干啥的？点我"></i>
        </label>
        <div class="field-hint" id="directorHelpText" hidden>
          顾问 = 能力最强的贵模型。主对话日常用便宜模型干活时 · 它只在「蓝图 / 破局 / 验收」三个唤醒点被 replan 召唤进来把关
          (跨 provider 现场连接 · 干净上下文不装灵魂 · 全局只能设一个 · 设新的旧的自动取消)。不配则不启用顾问功能 · replan 照旧用当前主模型当顾问。
          省钱场景: DeepSeek 干活 + K3 当顾问 · 同强度任务估省 50-70%。
        </div>
      </div>
      ${isEdit ? '' : `
      <div class="field">
        <label>
          <input id="llmEditSetActive" type="checkbox">
          保存后立即激活 (Daemonkey 切到这条跑)
        </label>
      </div>`}
      <div class="actions">
        <button class="btn-ghost" onclick="hideLlmEditForm()">取消</button>
        <button class="btn-primary" id="llmEditSubmit">${escHtml(submit)}</button>
      </div>
      <div id="llmEditStatus" class="field-hint" style="margin-top:6px"></div>
    </div>
  `;
  // 编辑模式：base_url 已有值 → 标记 touched · 防止 onLlmEditPresetChange 覆盖
  if (isEdit && config.base_url) {
    document.getElementById('llmEditBaseUrl').dataset.touched = '1';
  }
  // wish-bec4f3b9 · 已有 pricing 回填币种
  if (config.pricing && config.pricing.currency) {
    const _cur = document.getElementById('llmEditCurrency');
    if (_cur) _cur.value = config.pricing.currency;
  }
  onLlmEditPresetChange();  // 触发一次 · 填模型下拉
  const _dhIcon = document.getElementById('directorHelpIcon');
  if (_dhIcon) _dhIcon.addEventListener('click', () => {
    const h = document.getElementById('directorHelpText');
    if (h) h.hidden = !h.hidden;
  });
  document.getElementById('llmEditSubmit').addEventListener('click', async () => {
    const form = _readLlmEditForm();
    if (!form.name || !form.model) {
      document.getElementById('llmEditStatus').textContent = '⚠ name 和 model 必填';
      return;
    }
    if (!isEdit && !form.api_key) {
      document.getElementById('llmEditStatus').textContent = '⚠ 新增时 api_key 必填';
      return;
    }
    document.getElementById('llmEditStatus').textContent = '保存中…';
    try {
      await onSubmit(form);
    } catch (e) {
      document.getElementById('llmEditStatus').innerHTML = '<i class="ri-close-fill"></i> ' + e.message;
    }
  });
  // wish-bec4f3b9 · 自动查官方价 (回填≠保存 · 仍走保存按钮)
  const _lookupBtn = document.getElementById('llmEditLookup');
  if (_lookupBtn) _lookupBtn.addEventListener('click', async () => {
    const _hint = document.getElementById('llmEditPricingHint');
    _lookupBtn.disabled = true;
    _lookupBtn.innerHTML = '<i class="ri-loader-4-line spin"></i> 查价中…';
    try {
      const _resp = await fetch('/llm-pricing/lookup', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          preset_id: document.getElementById('llmEditPreset')?.value || '',
          model: document.getElementById('llmEditModel')?.value || '',
          base_url: document.getElementById('llmEditBaseUrl')?.value || '',
        }),
      });
      if (!_resp.ok) {
        let hint = '查价失败 · 请手动填';
        try {
          const _j = await _resp.json();
          if (_j && (_j.hint || _j.error)) hint = (_j.hint || _j.error) + ' · 请手动填';
          if (_j && _j.source_url) window._llmPricingSource = _j.source_url;
        } catch (_e) { /* ignore */ }
        _hint.innerHTML = `<span style="color:#FC8181">${escHtml(hint)}</span>`;
        return;
      }
      const _j = await _resp.json();
      if (_j && _j.pricing) {
        document.getElementById('llmEditCurrency').value = _j.pricing.currency || 'USD';
        document.getElementById('llmEditPriceIn').value = _j.pricing.input ?? '';
        document.getElementById('llmEditPriceOut').value = _j.pricing.output ?? '';
        document.getElementById('llmEditPriceCache').value = _j.pricing.cache_read ?? '';
        window._llmPricingSource = _j.source_url || '';
        window._llmPricingCheckedAt = _j.checked_at || '';
        _hint.innerHTML = `来源: <a href="${escAttr(_j.source_url || '#')}" target="_blank">官方定价页</a> · 查于 ${escHtml(_j.checked_at || '')} · <b>请核对后保存</b>`;
      } else {
        _hint.innerHTML = '<span style="color:#FC8181">查价失败 · 请手动填</span>';
      }
    } catch (e) {
      _hint.innerHTML = `<span style="color:#FC8181">自动查价失败: ${escHtml(e.message || '')} · 请手动填写价格</span>`;
    } finally {
      _lookupBtn.disabled = false;
      _lookupBtn.innerHTML = '<i class="ri-search-eye-line"></i> 自动查官方价';
    }
  });
  panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function hideLlmEditForm() {
  const panel = document.getElementById('llmEditPanel');
  if (panel) { panel.hidden = true; panel.innerHTML = ''; }
}

function _readLlmEditForm() {
  return {
    name: document.getElementById('llmEditName').value.trim(),
    provider_kind: document.getElementById('llmEditKind').value,
    base_url: document.getElementById('llmEditBaseUrl').value.trim(),
    model: document.getElementById('llmEditModel').value.trim(),
    api_key: document.getElementById('llmEditApiKey').value.trim(),
    preset_id: document.getElementById('llmEditPreset').value,
    pinned: document.getElementById('llmEditPinned').checked,
    set_active: document.getElementById('llmEditSetActive')?.checked || false,
    max_tokens: parseInt(document.getElementById('llmEditMaxTokens').value || '8192', 10),
    vision: (() => {
      const a = document.getElementById('llmEditVisionAuto');
      const y = document.getElementById('llmEditVisionYes');
      const n = document.getElementById('llmEditVisionNo');
      if (a && a.checked) return null;
      if (y && y.checked) return true;
      if (n && n.checked) return false;
      return null;
    })(),
    director: !!document.getElementById('llmEditDirector')?.checked,
    pricing: (() => {
      const inp = parseFloat(document.getElementById('llmEditPriceIn')?.value);
      const outp = parseFloat(document.getElementById('llmEditPriceOut')?.value);
      if (isNaN(inp) && isNaN(outp)) return null;   // 未配置
      return {
        currency: document.getElementById('llmEditCurrency')?.value || 'USD',
        input: isNaN(inp) ? null : inp,
        output: isNaN(outp) ? null : outp,
        cache_read: (() => {
          const c = parseFloat(document.getElementById('llmEditPriceCache')?.value);
          return isNaN(c) ? null : c;
        })(),
        source_url: window._llmPricingSource || '',
        checked_at: window._llmPricingCheckedAt || '',
        note: '',
      };
    })(),
  };
}

function onLlmEditPresetChange() {
  const pid = document.getElementById('llmEditPreset').value;
  const preset = _providerPresets.find(p => p.id === pid);
  if (!preset) return;
  document.getElementById('llmEditPresetNote').textContent = preset.note || '';
  // 自动填 base_url / provider_kind 如果是新增时
  const baseInput = document.getElementById('llmEditBaseUrl');
  const kindSelect = document.getElementById('llmEditKind');
  if (!baseInput.value || baseInput.dataset.touched !== '1') {
    baseInput.value = preset.base_url || '';
  }
  if (preset.provider_kind) kindSelect.value = preset.provider_kind;
  // 填模型下拉
  const sel = document.getElementById('llmEditModelSelect');
  sel.innerHTML = '<option value="">— 选推荐模型 / 或在下方手填 —</option>';
  (preset.recommended_models || []).forEach(m => {
    const opt = document.createElement('option');
    opt.value = m.id;
    opt.textContent = m.label;
    opt.title = m.note || '';
    sel.appendChild(opt);
  });
}

function onLlmEditModelSelectChange() {
  const sel = document.getElementById('llmEditModelSelect');
  if (!sel.value) return;
  document.getElementById('llmEditModel').value = sel.value;
  // 卷三十八 · 选了推荐模型 · 自动填 max_tokens 推荐值 + 更新 hint 显示模型 spec
  const pid = document.getElementById('llmEditPreset').value;
  const preset = _providerPresets.find(p => p.id === pid);
  if (!preset) return;
  const m = (preset.recommended_models || []).find(x => x.id === sel.value);
  if (!m) return;
  const mtInput = document.getElementById('llmEditMaxTokens');
  if (m.max_tokens_default) {
    mtInput.value = m.max_tokens_default;
    mtInput.max = m.max_output || 384000;
  }
  const hint = document.getElementById('llmEditMaxTokensHint');
  if (hint) {
    const ctx = m.context_window ? ` · 上下文上限 ${formatTokenK(m.context_window)}` : '';
    const out = m.max_output ? ` · 输出上限 ${formatTokenK(m.max_output)}` : '';
    hint.innerHTML = `单位: token · 约 token×0.7 个汉字${ctx}${out}<br>推荐 ${m.max_tokens_default || 8192} (按模型 spec 算的安全值)`;
  }
}

// 1234 → "1.2K" · 12345 → "12K" · 1234567 → "1.2M"
function formatTokenK(n) {
  if (!n) return '0';
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1).replace('.0', '') + 'M';
  if (n >= 1000) return Math.round(n / 1000) + 'K';
  return String(n);
}

async function activateConfig(cfgId) {
  const r = await fetch('/provider-configs/' + encodeURIComponent(cfgId) + '/activate', {
    method: 'POST',
    headers: { 'Authorization': 'Bearer ' + token },
  });
  if (!r.ok) {
    const t = await r.text();
    await DaemonkeyAlert({ title: '激活失败', message: t.slice(0, 400), icon: '<i class="ri-error-warning-fill"></i>' });
    return;
  }
  const data = await r.json();
  addSys('已激活 · ' + (data.model || '?') + ' · session 不丢');
  await renderSettingsLLM();
  if (typeof loadCurrentModel === 'function') loadCurrentModel();
}

async function testConfig(cfgId) {
  const tag = document.getElementById('lcTestResult_' + cfgId);
  if (tag) { tag.textContent = '测试中…'; tag.className = 'lc-test-result loading'; }
  try {
    const r = await fetch('/provider-configs/' + encodeURIComponent(cfgId) + '/test', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token },
    });
    const data = await r.json();
    if (data.ok) {
      tag.innerHTML = `<i class="ri-check-fill"></i> 通了 · 回复: ${data.reply_preview || '(空 · 但通)'}`;
      tag.className = 'lc-test-result ok';
    } else {
      tag.innerHTML = `<i class="ri-close-fill"></i> ${data.error || '?'} · ${data.hint || ''}`;
      tag.className = 'lc-test-result fail';
    }
  } catch (e) {
    tag.innerHTML = '<i class="ri-close-fill"></i> 网络出错: ' + e.message;
    tag.className = 'lc-test-result fail';
  }
}

async function togglePinConfig(cfgId, pinned) {
  const r = await fetch('/provider-configs/' + encodeURIComponent(cfgId), {
    method: 'PATCH',
    headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ pinned }),
  });
  if (!r.ok) {
    const t = await r.text();
    await DaemonkeyAlert({ title: '改 pinned 失败', message: t.slice(0, 400), icon: '<i class="ri-error-warning-fill"></i>' });
    return;
  }
  await renderSettingsLLM();
  if (typeof loadCurrentModel === 'function') loadCurrentModel();
}

async function deleteConfig(cfgId) {
  const cfg = _providerConfigs.find(c => c.id === cfgId);
  const ok = await DaemonkeyConfirm({
    title: '删除 LLM 配置',
    message: `确定删除 "${cfg?.name || cfgId}"?\nAPI key 也会从本地删除·不可恢复。`,
    okText: '删',
    cancelText: '不删',
    danger: true,
  });
  if (!ok) return;
  const r = await fetch('/provider-configs/' + encodeURIComponent(cfgId), {
    method: 'DELETE',
    headers: { 'Authorization': 'Bearer ' + token },
  });
  if (!r.ok) {
    const t = await r.text();
    await DaemonkeyAlert({ title: '删除失败', message: t.slice(0, 400), icon: '<i class="ri-error-warning-fill"></i>' });
    return;
  }
  await renderSettingsLLM();
  if (typeof loadCurrentModel === 'function') loadCurrentModel();
}

// wish-6ee0cd18 · 总监模型入口前置 · 卡片上一键设/取消总监（复用 8ffb9d65 的 PATCH director 链路）
async function toggleDirectorConfig(cfgId, val) {
  const cfg = _providerConfigs.find(c => c.id === cfgId);
  if (!cfg) return;
  const label = cfg.name || cfg.model || cfgId;
  const ok = await DaemonkeyConfirm(val ? {
    title: '设为顾问模型',
    message: `把 "${label}" 设为顾问？\n\n顾问 = 能力最强的贵模型。主对话日常用便宜模型干活时 · 它只在「蓝图 / 破局 / 验收」三个唤醒点被 replan 召唤进来把关（跨 provider 现场连接 · 干净上下文不装灵魂）。\n\n全局只能有一个顾问 · 设它为顾问后 · 之前的顾问会自动取消。\n\n省钱场景：DeepSeek 干活 + K3 当顾问 · 同强度任务估省 50-70%。`,
    okText: '设为顾问',
    cancelText: '再想想',
  } : {
    title: '取消顾问模型',
    message: `取消 "${label}" 的顾问身份？\n取消后 replan 顾问回到当前主模型（不再跨 provider 召唤贵模型）。`,
    okText: '取消顾问',
    cancelText: '保留',
  });
  if (!ok) return;
  const r = await fetch('/provider-configs/' + encodeURIComponent(cfgId), {
    method: 'PATCH',
    headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ director: !!val }),
  });
  if (!r.ok) {
    const t = await r.text();
    await DaemonkeyAlert({ title: '改顾问失败', message: t.slice(0, 400), icon: '<i class="ri-error-warning-fill"></i>' });
    return;
  }
  await renderSettingsLLM();
  if (typeof loadCurrentModel === 'function') loadCurrentModel();
}

function showDirectorHelp() {
  DaemonkeyAlert({
    title: '<i class="ri-vip-crown-fill"></i> 顾问模型是干啥的？',
    message: '顾问 = 能力最强的贵模型。\n\n主对话日常用便宜模型干活时 · 它只在「蓝图 / 破局 / 验收」三个唤醒点被 replan 召唤进来把关（跨 provider 现场连接 · 干净上下文不装灵魂）。\n\n全局只能有一个顾问 · 设新的顾问后旧的自动取消。不配则不启用顾问功能 · replan 照旧用当前主模型当顾问。\n\n省钱场景：DeepSeek 干活 + K3 当顾问 · 同强度任务估省 50-70%。',
  });
}

// ─── wish-4a6331b2 · 视觉模型配置 tab ───
async function renderSettingsVision() {
  const body = document.getElementById('settingsBody');
  body.innerHTML = '<div class="dash-empty">加载中…</div>';

  let cfg = { model: '', base_url: '', api_key: '', configured: false };
  try {
    const resp = await fetch('/vision-config', { headers: { 'Authorization': 'Bearer ' + token } });
    if (resp.ok) cfg = await resp.json();
  } catch (_) {}

  const hasCfg = cfg.configured;
  body.innerHTML = `
    <div class="llm-section">
      <div class="llm-section-head">
        <h3><i class="ri-eye-fill"></i> 视觉模型 · ${hasCfg ? '<span style="color:#6ed27a">已配置 ✓</span>' : '<span style="color:var(--sys)">未配置</span>'}</h3>
        <span class="llm-hint">主模型不支持看图时自动调用 · 多模态模型（Claude/GPT/Gemini）不经过这里 · 配一个 OpenAI 兼容的视觉模型即可</span>
      </div>
      <div class="field">
        <label>模型名</label>
        <input id="visModel" type="text" value="${escHtml(cfg.model || '')}" placeholder="gemini-2.0-flash-lite">
        <div class="field-hint">任意 OpenAI 兼容的视觉模型名</div>
      </div>
      <div class="field">
        <label>API 地址</label>
        <input id="visBaseUrl" type="text" value="${escHtml(cfg.base_url || '')}" placeholder="https://api.openai.com/v1">
      </div>
      <div class="field">
        <label>API Key</label>
        <input id="visApiKey" type="password" value="${escHtml(cfg.api_key || '')}" placeholder="${hasCfg ? '不改就留空' : 'sk-xxx'}">
        ${hasCfg ? '<div class="field-hint">已存 key · 不改就留空</div>' : ''}
      </div>
      <div class="actions" style="margin-top:12px">
        <button class="btn-primary" id="visSave"><i class="ri-save-fill"></i> 保存</button>
        <button class="btn-ghost" id="visTest"><i class="ri-flashlight-fill"></i> 测试连接</button>
      </div>
      <div id="visResult" style="margin-top:8px;font-size:13px"></div>
    </div>

    <!-- wish-241e0014 · 语音识别增强 whisper (可选更新 · 设置页开关驱动安装) -->
    <div class="llm-section" style="margin-top:18px">
      <div class="llm-section-head">
        <h3><i class="ri-mic-fill"></i> 语音识别增强 (whisper) · <span id="sttStatusLabel" style="color:var(--dim)">加载中…</span></h3>
        <span class="llm-hint">微信语音转文字 · 可选功能 · 打开开关才下载依赖+模型 (~500MB) · 不需要就不装 · 装好前语音自动降级存证</span>
      </div>
      <div id="sttBody" style="min-height:60px"><span class="field-hint">加载中…</span></div>
    </div>
  `;

  async function doSave(testOnly) {
    const m = document.getElementById('visModel').value.trim();
    const u = document.getElementById('visBaseUrl').value.trim();
    const k = document.getElementById('visApiKey').value.trim();
    let storedKey = k;
    if (!m || !u || !storedKey) {
      const resEl = document.getElementById('visResult');
      if (resEl) resEl.innerHTML = '<span style="color:var(--red)"><i class="ri-error-warning-fill"></i> 三个字段都要填</span>';
      return;
    }
    const resEl = document.getElementById('visResult');
    if (resEl) resEl.innerHTML = '<span style="color:var(--sys)"><i class="ri-loader-fill"></i> 保存中…</span>';
    try {
      const resp = await fetch('/vision-config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
        body: JSON.stringify({ model: m, base_url: u, api_key: storedKey, test: testOnly }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        if (resEl) resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-error-warning-fill"></i> ${escHtml(data.detail || '保存失败')}</span>`;
        return;
      }
      if (testOnly && data.test) {
        if (data.test.ok) {
          if (resEl) resEl.innerHTML = `<span style="color:#6ed27a"><i class="ri-check-fill"></i> 测试通过 · ${escHtml(data.test.reply)}</span>`;
        } else {
          if (resEl) resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-close-fill"></i> 连接失败: ${escHtml(data.test.error)}</span>`;
        }
      } else {
        if (resEl) resEl.innerHTML = '<span style="color:#6ed27a"><i class="ri-check-fill"></i> 已保存</span>';
        setTimeout(() => renderSettingsVision(), 600);
      }
    } catch (e) {
      if (resEl) resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-close-fill"></i> ${escHtml(e.message)}</span>`;
    }
  }

  document.getElementById('visSave').onclick = () => doSave(false);
  document.getElementById('visTest').onclick = () => doSave(true);

  loadSttConfig();
}

// ─── wish-241e0014 · 语音识别增强 whisper (可选更新 · 开关驱动安装) ───
async function loadSttConfig() {
  const $status = document.getElementById('sttStatusLabel');
  const $body = document.getElementById('sttBody');
  if (!$status || !$body) return;
  let st = { deps_installed: false, model_name: 'small', model_downloaded: false, ready: false, model_dir: '', expected_size_mb: 460 };
  try {
    const resp = await fetch('/stt/status', { headers: { 'Authorization': 'Bearer ' + token } });
    if (resp.ok) st = await resp.json();
  } catch (_) {}
  const stateLabel = st.ready
    ? '<span style="color:#6ed27a">已就绪 ✓</span>'
    : (st.deps_installed && !st.model_downloaded)
      ? '<span style="color:var(--sys)">依赖已装 · 模型未下载</span>'
      : '<span style="color:var(--red)">未安装</span>';
  $status.innerHTML = stateLabel;
  $body.innerHTML = `
    <div class="field">
      <label style="display:flex;align-items:center;gap:8px">
        <input type="checkbox" id="sttEnable" ${st.ready ? 'checked' : ''} style="width:auto">
        启用语音识别增强 (whisper)
      </label>
      <div class="field-hint">开启后：①安装转写依赖 (pilk + faster-whisper) ②下载模型 (~${st.expected_size_mb}MB · 国内镜像) · 装好微信语音自动转文字</div>
    </div>
    <div class="field">
      <label>模型大小</label>
      <select id="sttModelSize" style="max-width:220px">
        <option value="tiny" ${st.model_name === 'tiny' ? 'selected' : ''}>tiny · ~75MB · 最快最省</option>
        <option value="base" ${st.model_name === 'base' ? 'selected' : ''}>base · ~150MB · 均衡</option>
        <option value="small" ${st.model_name === 'small' ? 'selected' : ''}>small · ~460MB · 最准 (默认)</option>
      </select>
      <div class="field-hint">切换大小后需重新下载对应模型</div>
    </div>
    <div class="field">
      <label>随 daemon 启动加载模型</label>
      <div class="field-hint">开启后启动即加载 (~1-2s) · 微信语音首条秒回 · 关掉则首次语音时懒加载 (多等几秒)</div>
      <label style="display:flex;align-items:center;gap:8px">
        <input type="checkbox" id="sttBootLoad" ${st.boot_load ? 'checked' : ''} style="width:auto">
        启动时预加载
      </label>
    </div>
    <div class="actions" style="margin-top:12px">
      <button class="btn-primary" id="sttSetup"><i class="ri-download-fill"></i> ${st.ready ? '重新安装' : '下载并启用'}</button>
      ${st.model_downloaded ? '<button class="btn-ghost" id="sttRemove"><i class="ri-delete-bin-line"></i> 删除模型</button>' : ''}
    </div>
    <div id="sttResult" style="margin-top:10px;font-size:13px"></div>
  `;
  document.getElementById('sttSetup').onclick = () => setupStt();
  const rmBtn = document.getElementById('sttRemove');
  if (rmBtn) rmBtn.onclick = () => removeSttModel();
  document.getElementById('sttModelSize').onchange = async (e) => {
    try {
      await fetch('/stt/model', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
        body: JSON.stringify({ model_name: e.target.value }),
      });
    } catch (_) {}
  };
  document.getElementById('sttBootLoad').onchange = async (e) => {
    try {
      await fetch('/stt/boot-load', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
        body: JSON.stringify({ enabled: e.target.checked }),
      });
    } catch (_) {}
  };
}

// 安装依赖 + 下载模型 (后台 · 轮询进度)
async function setupStt() {
  const $res = document.getElementById('sttResult');
  if (!$res) return;
  $res.innerHTML = '<span style="color:var(--sys)"><i class="ri-loader-fill"></i> 开始安装依赖 (pilk + faster-whisper ~100MB) · 需 1-3 分钟…</span>';
  try {
    const resp = await fetch('/stt/setup', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token },
    });
    const data = await resp.json();
    if (!resp.ok) {
      $res.innerHTML = `<span style="color:var(--red)"><i class="ri-error-warning-fill"></i> ${escHtml(data.detail || '安装失败')}</span>`;
      return;
    }
    // 依赖装完 → 开始下载模型 → 轮询进度
    $res.innerHTML = '<span style="color:var(--sys)"><i class="ri-loader-fill"></i> 依赖已装 · 开始下载模型…</span>';
    pollSttProgress();
  } catch (e) {
    $res.innerHTML = `<span style="color:var(--red)"><i class="ri-close-fill"></i> ${escHtml(e.message)}</span>`;
  }
}

// 轮询安装进度
function pollSttProgress() {
  const $res = document.getElementById('sttResult');
  if (!$res) return;
  let n = 0;
  const timer = setInterval(async () => {
    n++;
    try {
      const resp = await fetch('/stt/status', { headers: { 'Authorization': 'Bearer ' + token } });
      const st = await resp.json();
      if (st.ready) {
        clearInterval(timer);
        $res.innerHTML = '<span style="color:#6ed27a"><i class="ri-check-fill"></i> 语音识别增强已就绪 · 微信语音现在能转文字了</span>';
        loadSttConfig();
      } else if (n > 600) {  // 10 分钟超时 (small 模型 ~460MB · hf-mirror 下载可能要几分钟)
        clearInterval(timer);
        $res.innerHTML = '<span style="color:var(--red)"><i class="ri-error-warning-fill"></i> 安装超时 · 查看 daemon 日志 · 可重试</span>';
      } else {
        $res.innerHTML = `<span style="color:var(--sys)"><i class="ri-loader-fill"></i> 安装中 (${Math.min(n, 600)}s) · 依赖/模型下载中…</span>`;
      }
    } catch (_) {
      if (n > 600) { clearInterval(timer); }
    }
  }, 1000);
}

async function removeSttModel() {
  const $res = document.getElementById('sttResult');
  if (!$res) return;
  if (!confirm('删除 whisper 模型文件 (~几百 MB)？依赖保留，可重新下载。')) return;
  try {
    const resp = await fetch('/stt/remove-model', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token },
    });
    const data = await resp.json();
    $res.innerHTML = data.ok
      ? '<span style="color:#6ed27a"><i class="ri-check-fill"></i> 模型已删除</span>'
      : `<span style="color:var(--red)"><i class="ri-error-warning-fill"></i> ${escHtml(data.error || '删除失败')}</span>`;
    loadSttConfig();
  } catch (e) {
    $res.innerHTML = `<span style="color:var(--red)"><i class="ri-close-fill"></i> ${escHtml(e.message)}</span>`;
  }
}

// ─── wish-b313583b · Embedding 语义检索配置卡 (独立 tab · wish-241e0014 拆分) ───
async function renderSettingsEmbedding() {
  const body = document.getElementById('settingsBody');
  body.innerHTML = `
    <div class="llm-section">
      <div class="llm-section-head">
        <h3><i class="ri-brain-line"></i> 记忆语义检索 (Embedding) · <span id="embStatusLabel" style="color:var(--dim)">加载中…</span></h3>
        <span class="llm-hint">给记忆检索加语义理解：用近义词、换种说法也能搜到相关记忆（纯字面匹配做不到）· 未配置时自动复用已配的智谱 key · 也可自定义任意兼容 API</span>
      </div>
      <div id="embBody" style="min-height:60px"><span class="field-hint">加载中…</span></div>
    </div>
  `;
  loadEmbedConfig();
}

// ─── wish-b313583b · Embedding 语义检索配置卡 ───
async function loadEmbedConfig() {
  const $status = document.getElementById('embStatusLabel');
  const $body = document.getElementById('embBody');
  if (!$status || !$body) return;

  let cfg = { enabled: true, configured: false, source: '', model: 'embedding-3', base_url: '', api_key: '', covered: 0, total: 0 };
  try {
    const resp = await fetch('/embed-config', { headers: { 'Authorization': 'Bearer ' + token } });
    if (resp.ok) cfg = await resp.json();
  } catch (_) {}

  const pct = cfg.total > 0 ? Math.round(cfg.covered / cfg.total * 100) : 0;
  const srcLabel = cfg.source === 'user' ? '自定义配置' : (cfg.source === 'zhipu-provider' ? '自动复用智谱' : (cfg.source === 'env' ? '.env' : '未配置'));
  $status.innerHTML = cfg.enabled
    ? '<span style="color:#6ed27a">已开启 ✓</span>'
    : '<span style="color:var(--red)">已关闭</span>';

  $body.innerHTML = `
    <div class="field">
      <label>模型名</label>
      <input id="embModel" type="text" value="${escHtml(cfg.model || '')}" placeholder="embedding-3">
      <div class="field-hint">任意兼容 Embedding API 的模型名 · 如智谱 embedding-3 / OpenAI text-embedding-3-small</div>
    </div>
    <div class="field">
      <label>API 地址</label>
      <input id="embBaseUrl" type="text" value="${escHtml(cfg.base_url || '')}" placeholder="https://open.bigmodel.cn/api/paas/v4">
      <div class="field-hint">OpenAI 兼容的 API 根地址 (不带 /embeddings)</div>
    </div>
    <div class="field">
      <label>API Key</label>
      <input id="embApiKey" type="password" value="${escHtml(cfg.api_key || '')}" placeholder="${cfg.configured ? '已存 key · 不改就留空' : 'sk-xxx'}">
      <div class="field-hint">${cfg.configured ? `当前来源: ${srcLabel} · 改配置请粘贴新 key` : '未配置 · 填 key 保存后即可用'}</div>
    </div>
    <div class="field">
      <label>语义增强开关</label>
      <label class="switch" style="margin-left:0">
        <input type="checkbox" id="embToggle" ${cfg.enabled ? 'checked' : ''} onchange="toggleEmbed()">
        <span class="slider"></span>
      </label>
      <div class="field-hint">关 = 记忆检索退化为纯字面匹配 · 开 = 补语义命中 (推荐)</div>
    </div>
    <div class="field">
      <label>覆盖状态</label>
      <div class="field-hint" style="font-size:13px">
        ${cfg.total > 0
          ? `高信号记忆向量覆盖 <b>${cfg.covered}</b>/${cfg.total} (<b>${pct}%</b>)`
          : '尚无记忆向量'}
      </div>
      <div class="field-hint" style="font-size:12px;color:#888;margin-top:2px">
        语义索引只覆盖摘要 / 操作手册 / 知识库等高质量源 · 历史对话原文走字面检索 (FTS5) 不计入向量
      </div>
    </div>
    <div class="actions" style="margin-top:8px;gap:8px">
      <button class="btn-primary" id="embSave"><i class="ri-save-fill"></i> 保存配置</button>
      <button class="btn-ghost" id="embTest"><i class="ri-flashlight-fill"></i> 测试连接</button>
      <button class="btn-ghost" id="embBackfill" ${cfg.covered >= cfg.total ? 'disabled' : ''}>
        <i class="ri-refresh-fill"></i> 回填缺失向量 (${Math.max(cfg.total - cfg.covered, 0)} 条)
      </button>
    </div>
    <div id="embResult" style="margin-top:8px;font-size:13px"></div>
  `;
  document.getElementById('embSave').onclick = () => doEmbedSave(false);
  document.getElementById('embTest').onclick = () => doEmbedSave(true);
  const $bf = document.getElementById('embBackfill');
  if ($bf) $bf.onclick = () => doEmbedBackfill();
}

async function doEmbedSave(testOnly) {
  const m = document.getElementById('embModel').value.trim();
  const u = document.getElementById('embBaseUrl').value.trim();
  const k = document.getElementById('embApiKey').value.trim();
  const resEl = document.getElementById('embResult');
  if (!m || !u) {
    if (resEl) resEl.innerHTML = '<span style="color:var(--red)"><i class="ri-error-warning-fill"></i> 模型名和 API 地址必填</span>';
    return;
  }
  const body = { model: m, base_url: u, action: testOnly ? 'test' : undefined };
  // 掩码回传检测: 输入框还是掩码 (sk-****xxxx) 说明用户没改 → 不传 key · 后端用已存
  if (k && !k.includes('****')) body.api_key = k;
  if (resEl) resEl.innerHTML = `<span style="color:var(--sys)"><i class="ri-loader-fill"></i> ${testOnly ? '测试中…' : '保存中…'}</span>`;
  try {
    const resp = await fetch('/embed-config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok) {
      if (resEl) resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-error-warning-fill"></i> ${escHtml(data.detail || '失败')}</span>`;
      return;
    }
    if (testOnly && data.test) {
      if (data.test.ok) {
        if (resEl) resEl.innerHTML = `<span style="color:#6ed27a"><i class="ri-check-fill"></i> 连接成功 · 维度 ${data.test.dim} · ${Math.round(data.test.ms)}ms</span>`;
      } else {
        if (resEl) resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-close-fill"></i> 连接失败: ${escHtml(data.test.error)}</span>`;
      }
    } else {
      if (resEl) resEl.innerHTML = '<span style="color:#6ed27a"><i class="ri-check-fill"></i> 已保存</span>';
      setTimeout(() => loadEmbedConfig(), 600);
    }
  } catch (e) {
    if (resEl) resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-close-fill"></i> ${escHtml(e.message)}</span>`;
  }
}

async function toggleEmbed() {
  const $on = document.getElementById('embToggle');
  const enabled = $on.checked;
  const resEl = document.getElementById('embResult');
  try {
    const resp = await fetch('/embed-config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify({ enabled }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      if (resEl) resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-error-warning-fill"></i> ${escHtml(data.detail || '保存失败')}</span>`;
      return;
    }
    if (resEl) resEl.innerHTML = `<span style="color:#6ed27a"><i class="ri-check-fill"></i> 语义增强已${enabled ? '开启' : '关闭'} · 下次记忆查询生效</span>`;
    loadEmbedConfig();
  } catch (e) {
    if (resEl) resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-close-fill"></i> ${escHtml(e.message)}</span>`;
  }
}

async function doEmbedBackfill() {
  const resEl = document.getElementById('embResult');
  if (resEl) resEl.innerHTML = '<span style="color:var(--sys)"><i class="ri-loader-fill"></i> 回填启动… 后台跑 · 刷新此页看进度</span>';
  try {
    const resp = await fetch('/embed-config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify({ action: 'backfill' }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      if (resEl) resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-error-warning-fill"></i> ${escHtml(data.detail || '启动失败')}</span>`;
      return;
    }
    if (resEl) resEl.innerHTML = '<span style="color:#6ed27a"><i class="ri-check-fill"></i> 后台回填已启动 · 稍后刷新看覆盖增长</span>';
  } catch (e) {
    if (resEl) resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-close-fill"></i> ${escHtml(e.message)}</span>`;
  }
}

function renderSettingsAccess() {
  const body = document.getElementById('settingsBody');
  body.innerHTML = `
    <div class="llm-section">
      <div class="llm-section-head"><h3>🔑 API Token · 决定 WebUI 能否连 daemon</h3></div>
      <div class="field">
        <label>API Token (Bearer)</label>
        <input id="accTokenIn" type="password" value="${escHtml(token || '')}" placeholder="DAEMONKEY_API_TOKEN / Daemonkey_API_TOKEN">
        <div class="field-hint">⚠ 这是【连接 daemon 的门禁钥匙】· 不是 LLM 的 API Key（模型 Key 在「模型/Provider」里配）</div>
        <div class="field-hint">在 daemon 目录的 <code>.env</code> 文件里找 <code>DAEMONKEY_API_TOKEN</code>（发布版叫 <code>Daemonkey_API_TOKEN</code>）· 复制粘贴进来 · 填一次浏览器记住 · 本机访问通常自动放行不用填</div>
      </div>

      <div class="llm-section-head" style="margin-top:18px"><h3>📂 当前 Session</h3></div>
      <div class="field">
        <label>Session ID</label>
        <input id="accSessionIn" type="text" value="${escHtml(sessionId || '')}" placeholder="留空 = 新对话">
      </div>

      <div class="llm-section-head" style="margin-top:18px"><h3>✋ 工具确认策略</h3></div>
      <div class="field">
        <label>Auto-confirm 策略</label>
        <select id="accAutoIn">
          <option value="auto" ${autoConfirm === 'auto' ? 'selected' : ''}>auto · 只跑 AUTO 工具 (最保守)</option>
          <option value="confirm" ${autoConfirm === 'confirm' ? 'selected' : ''}>confirm · AUTO + CONFIRM 自动跑 (推荐)</option>
          <option value="guard" ${autoConfirm === 'guard' ? 'selected' : ''}>guard · 三档全开·全自动 (无人值守 yolo · 慎用)</option>
        </select>
        <div class="field-hint">默认 confirm 档下·GUARD 工具会在 WebUI 弹卡片等你点；这个 guard 预设连 GUARD 也自动放行·只在没人能点(无人值守)时才用</div>
      </div>

      <!-- wish-f563a56d · trusted commands · 用户 临时给 Daemonkey 30min/24h/永久 信任窗口 -->
      <div class="llm-section-head" style="margin-top:18px"><h3>🔓 Trusted Commands · 信任清单</h3></div>
      <div class="field-hint" style="margin-bottom:8px">
        当 auto_confirm=auto 时·CONFIRM 档命令 (例如 <code>pip install</code>) 会被 skip。
        把命令头加到信任清单后·窗口期内 Daemonkey 调这类命令自动通过。
        <br><strong>红线</strong>: GUARD 黑名单 (rm -rf / format / git push --force) 永远不会被 trusted。
      </div>
      <div class="field" style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;">
        <div style="flex:1;min-width:180px">
          <label style="font-size:11px">命令头 pattern</label>
          <input id="accTrustPattern" type="text" placeholder="例如: pip install" style="width:100%">
        </div>
        <div>
          <label style="font-size:11px">时长</label>
          <select id="accTrustDuration">
            <option value="30">30 分钟</option>
            <option value="240">4 小时</option>
            <option value="1440">24 小时</option>
            <option value="0">永久 (谨慎)</option>
          </select>
        </div>
        <div style="flex:2;min-width:180px">
          <label style="font-size:11px">理由 (审计用 · 可选)</label>
          <input id="accTrustReason" type="text" placeholder="例如: 用户 让 Daemonkey 装 duckduckgo_search">
        </div>
        <button class="btn-primary" onclick="addTrustedCommand()">➕ 加入</button>
      </div>
      <div id="accTrustList" class="field-hint" style="margin-top:8px;font-size:12px">加载中…</div>

      <div class="actions" style="margin-top:18px">
        <button class="btn-primary" onclick="saveAccessSettings()">保存</button>
      </div>
      <div id="accSaveStatus" class="field-hint" style="margin-top:6px"></div>
    </div>
  `;
  // 异步刷一次 trusted 列表
  setTimeout(() => { try { refreshTrustedCommands(); } catch {} }, 50);
}

// wish-f563a56d · trusted commands UI helpers
async function refreshTrustedCommands() {
  const target = document.getElementById('accTrustList');
  if (!target) return;
  if (!token) { target.textContent = '⚠ 先填 token'; return; }
  try {
    const r = await fetch('/trusted_commands', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) {
      target.innerHTML = '<i class="ri-close-fill"></i> 加载失败 HTTP ' + r.status;
      return;
    }
    const j = await r.json();
    const items = (j && j.items) || [];
    if (!items.length) {
      target.innerHTML = '<i>暂无 trusted commands · Daemonkey 调 CONFIRM 档命令时会被 auto_confirm 策略卡住</i>';
      return;
    }
    const rows = items.map(it => {
      const remain = it._remaining_seconds;
      let remainStr;
      if (remain === null) {
        remainStr = '<span style="color:#f59e0b">永久</span>';
      } else if (remain <= 0) {
        remainStr = '<span style="color:#999">已过期</span>';
      } else if (remain < 60) {
        remainStr = remain + 's';
      } else if (remain < 3600) {
        remainStr = Math.floor(remain / 60) + 'min';
      } else {
        remainStr = Math.floor(remain / 3600) + 'h ' + Math.floor((remain % 3600) / 60) + 'min';
      }
      const reasonStr = it.reason ? ' · ' + escHtml(it.reason) : '';
      return `<div style="display:flex;justify-content:space-between;align-items:center;padding:4px 8px;border-bottom:1px solid #2a2f3a">
        <span><code>${escHtml(it.pattern)}</code> · ${remainStr}${reasonStr}</span>
        <button onclick="removeTrustedCommand('${jsStr(it.id)}')" style="background:transparent;border:1px solid #475569;color:#94a3b8;padding:2px 8px;border-radius:4px;cursor:pointer">删除</button>
      </div>`;
    }).join('');
    target.innerHTML = rows;
  } catch (e) {
    target.innerHTML = '<i class="ri-close-fill"></i> ' + e.message;
  }
}

async function addTrustedCommand() {
  const pat = document.getElementById('accTrustPattern').value.trim();
  const dur = parseInt(document.getElementById('accTrustDuration').value, 10);
  const reason = document.getElementById('accTrustReason').value.trim();
  if (!pat) {
    DaemonkeyAlert({ title: '空 pattern', message: '请填命令头 (例如 "pip install")' });
    return;
  }
  if (!token) {
    DaemonkeyAlert({ title: '缺 token', message: '请先填 API token' });
    return;
  }
  try {
    const r = await fetch('/trusted_commands', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        pattern: pat,
        duration_minutes: dur || null,
        reason,
      }),
    });
    if (!r.ok) {
      const txt = await r.text();
      DaemonkeyAlert({ title: '加入失败', message: 'HTTP ' + r.status + '\n' + txt });
      return;
    }
    document.getElementById('accTrustPattern').value = '';
    document.getElementById('accTrustReason').value = '';
    await refreshTrustedCommands();
  } catch (e) {
    DaemonkeyAlert({ title: '加入失败', message: e.message });
  }
}

async function removeTrustedCommand(itemId) {
  if (!token) return;
  try {
    const r = await fetch('/trusted_commands/' + encodeURIComponent(itemId), {
      method: 'DELETE',
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) {
      const txt = await r.text();
      DaemonkeyAlert({ title: '删除失败', message: 'HTTP ' + r.status + '\n' + txt });
      return;
    }
    await refreshTrustedCommands();
  } catch (e) {
    DaemonkeyAlert({ title: '删除失败', message: e.message });
  }
}

function saveAccessSettings() {
  const newToken = document.getElementById('accTokenIn').value.trim();
  const newSession = document.getElementById('accSessionIn').value.trim();
  const newAuto = document.getElementById('accAutoIn').value;
  token = newToken;
  sessionId = newSession;
  autoConfirm = newAuto;
  localStorage.setItem(STORAGE.token, token);
  localStorage.setItem(STORAGE.session, sessionId);
  localStorage.setItem(STORAGE.autoConfirm, autoConfirm);
  updateCurrentLabel();
  document.getElementById('accSaveStatus').innerHTML = '<i class="ri-check-fill"></i> 已保存 · ' + (token ? '可以聊了' : '⚠ token 为空');
  document.getElementById('accSaveStatus').className = 'field-hint ok';
  // 同步刷新右上角模型切换器
  if (typeof loadCurrentModel === 'function') loadCurrentModel();
}

// ─── 卷六十一 · 微信 & 主动 CALL 设置面板 ───
let _wechatQrPoll = null;

function renderSettingsWechat() {
  const body = document.getElementById('settingsBody');
  body.innerHTML = `
    <div class="llm-section">
      <div class="chan-grid">
        <!-- 微信卡 -->
        <div class="chan-card">
          <div class="chan-card-head">
            <div class="chan-icon wx"><i class="ri-wechat-fill"></i></div>
            <div><div class="chan-title">微信 · 官方 ClawBot (iLink)</div>
                 <div class="chan-sub">纯 HTTP 官方接口 · 不碰客户端 · 无封号风险</div></div>
            <span class="chan-badge off" id="wechatBadge">未连接</span>
          </div>
          <div class="chan-live" id="wechatStatus"><span class="live-dot idle"></span> 加载中…</div>
          <div class="chan-actions">
            <button class="btn-primary" onclick="wechatGenQr()"><i class="ri-qr-code-line"></i> 生成扫码登录二维码</button>
            <span class="field-hint" style="margin:0">手机微信扫一扫 → 授权『微信 ClawBot』· 重新扫可换绑</span>
          </div>
          <div id="wechatQrBox" style="display:none;text-align:center;margin-top:12px"></div>
          <div class="chan-info-bar warn"><i class="ri-time-line"></i> <b>24 小时窗口</b>：你在微信先发一句 → 开窗 · 窗口内 Daemonkey 能主动找你 · 跨天零互动发不出（腾讯反骚扰）</div>
        </div>
        <!-- 飞书卡 (0.9.1 · 两层: L1 webhook 推送 + L2 机器人对话) -->
        <div class="chan-card">
          <div class="chan-card-head">
            <div class="chan-icon fs"><i class="ri-flight-takeoff-line"></i></div>
            <div><div class="chan-title">飞书 · 对话 & 工作区</div>
                 <div class="chan-sub">群聊 @即回 · 读文档/表格 · 总结群消息</div></div>
            <span class="chan-badge off" id="feishuBadge">未配置</span>
          </div>
          <div class="chan-live" id="feishuStatus"><span class="live-dot idle"></span> 加载中…</div>
          <div class="chan-form">
            <div><label class="field-label">App ID</label>
                 <input id="feishuAppId" class="field-input" placeholder="cli_xxxxxxxxxxxxxxxx"
                        onkeydown="if(event.key==='Enter')feishuSaveConfig()"/></div>
            <div><label class="field-label">App Secret</label>
                 <input id="feishuAppSecret" type="password" class="field-input" placeholder="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                        onkeydown="if(event.key==='Enter')feishuSaveConfig()"/></div>
          </div>
          <div class="chan-actions">
            <button class="btn-primary" onclick="feishuSaveConfig()"><i class="ri-save-fill"></i> 保存并连接</button>
            <button class="btn-ghost" onclick="feishuToggle()"><i class="ri-power-line"></i> 启用/停用</button>
            <span id="feishuSaveMsg" class="field-hint" style="margin:0"></span>
          </div>
          <details class="chan-wizard">
            <summary><i class="ri-magic-line"></i> 还没有机器人？6 步接入向导</summary>
            <ol class="wizard-steps">
              <li><a href="https://open.feishu.cn/app?lang=zh-CN" target="_blank">创建企业自建应用</a>（开放平台 → 开发者后台 → 创建企业自建应用）</li>
              <li>添加 <b>机器人</b> 能力（应用能力 → 添加应用能力 → 机器人 → 创建）</li>
              <li>添加权限：飞书「权限管理」→ <b>批量导入</b> → 粘贴下面的 JSON → 一次配齐（也可逐条搜索添加）</li>
              <li>事件订阅：选 <b>使用长连接接收事件</b> + 订阅 <code>im.message.receive_v1</code>（事件与回调）</li>
              <li><b>创建版本并发布</b>（版本管理与发布 · 可用范围含自己）← 搜不到机器人 99% 是漏这步</li>
              <li>回来填上方 App ID / Secret → 保存并连接</li>
            </ol>
            <div class="perms-import">
              <div class="perms-import-head"><i class="ri-shield-keyhole-line"></i> 权限 JSON · 一键配齐
                <button class="btn-ghost perms-copy" onclick="copyFeishuScopes(this)"><i class="ri-file-copy-line"></i> 复制</button></div>
              <pre class="perms-json">{
  "scopes": {
    "tenant": [
      "im:message.p2p_msg:readonly",
      "im:message:send_as_bot",
      "im:message.group_at_msg:readonly",
      "im:message.group_msg",
      "im:message:readonly",
      "im:chat:readonly",
      "im:resource",
      "docx:document:readonly",
      "sheets:spreadsheet:readonly",
      "bitable:app:readonly"
    ],
    "user": [
      "docx:document:readonly"
    ]
  }
}</pre>
              <div class="perms-hint">用法：飞书开放平台 → 你的应用 → <b>权限管理</b> → 右上角 <b>批量导入</b> → 粘贴 → 确认 → <b>创建版本并发布</b>（不发布不生效！）。读文档/表格/群消息（im:message.group_msg=拉群历史 · 不带 :readonly）+ 群聊@（group_at_msg:readonly）+ 读文件（im:resource）都在里面了。</div>
            </div>
          </details>
          <div class="chan-info-bar ok" style="margin-top:10px"><i class="ri-check-line"></i> 官方 API + 长连接 · <b>无窗口限制</b> · 发布后去飞书搜你的机器人就能聊</div>
        </div>
        <!-- 频率卡 -->
        <div class="chan-card">
          <div class="chan-card-head">
            <div class="chan-icon cat"><i class="ri-paw-line"></i></div>
            <div><div class="chan-title">主动找你的频率</div>
                 <div class="chan-sub">高冷猫 ↔ 黏人犬 · 夜里永远不打扰</div></div>
          </div>
          <div id="wechatFreq" class="freq-seg">加载中…</div>
          <div class="chan-info-bar ok" style="margin-top:12px"><i class="ri-sun-line"></i> <span id="wechatFreqDesc">命中后随机时刻开口 · 23:00–9:00 静默</span></div>
        </div>
      </div>
    </div>
  `;
  setTimeout(() => { wechatLoadStatus(); wechatLoadFrequency(); feishuLoadStatus(); }, 30);
}

// ─── 0.9.0 (wish-aac348a1) · 飞书配置 UI ───

async function feishuLoadStatus() {
  const el = document.getElementById('feishuStatus');
  if (!el) return;
  if (!token) { el.innerHTML = '⚠ 先在『访问 & 会话』填 API Token'; return; }
  try {
    const r = await fetch('/api/feishu/status', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const s = await r.json();
    const listener = s.listener || {};
    const badge = document.getElementById('feishuBadge');
    if (badge) {
      if (s.configured && s.token_ok && listener.alive) { badge.textContent = '在线'; badge.className = 'chan-badge on'; }
      else if (s.configured && !s.token_ok) { badge.textContent = 'Token 异常'; badge.className = 'chan-badge warn'; }
      else { badge.textContent = '未配置'; badge.className = 'chan-badge off'; }
    }
    let liveInner;
    if (!s.configured) {
      liveInner = '<span class="live-dot idle"></span> 未配置 · 填 App ID + Secret 保存即连 · 群里 @ 它就能用';
    } else {
      const chips = [
        listener.ws_connected ? '<span class="chan-chip">ws <b>已连</b></span>' : '',
        listener.messages_in != null ? `<span class="chan-chip">收 <b>${listener.messages_in}</b></span><span class="chan-chip">回 <b>${listener.replies_out}</b></span>` : '',
        !s.token_ok ? '<span style="color:#fbbf24">· token 获取失败</span>' : '',
      ].filter(Boolean).join(' ');
      liveInner = `<span class="live-dot ${listener.alive ? 'on' : 'off'}"></span> 长连接 ${listener.alive ? '在线' : '离线'} ${chips}`;
    }
    el.innerHTML = liveInner;
    if (listener.last_error) {
      const info = el.parentElement.querySelector('.chan-info-bar.ok');
      if (info) {
        info.className = 'chan-info-bar warn';
        info.innerHTML = `<i class="ri-alert-line"></i> ${escHtml(listener.last_error)} · 去飞书开放平台检查权限/事件订阅`;
      }
    }
    // 回填已存配置 (只回填 app_id · secret 不回显)
    if (s.configured && document.getElementById('feishuAppId')) {
      document.getElementById('feishuAppId').placeholder = '已保存: ' + s.app_id;
      document.getElementById('feishuAppSecret').placeholder = '已保存 · 留空=不修改';
    }
  } catch (e) {
    el.innerHTML = '<i class="ri-close-fill"></i> 飞书状态加载失败: ' + escHtml(e.message);
  }
}

async function feishuSaveConfig() {
  const msg = document.getElementById('feishuSaveMsg');
  const appId = (document.getElementById('feishuAppId').value || '').trim();
  const appSecret = (document.getElementById('feishuAppSecret').value || '').trim();
  if (!appId && !appSecret) { msg.innerHTML = '<span style="color:#f59e0b">填一下 App ID 或 Secret</span>'; return; }
  if (!token) { msg.innerHTML = '<span style="color:#f59e0b">⚠ 先在『访问 & 会话』填 API Token</span>'; return; }
  msg.innerHTML = '⏳ 保存中…';
  try {
    const r = await fetch('/api/feishu/config', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ app_id: appId, app_secret: appSecret, enabled: true }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status));
    msg.innerHTML = d.token_ok
      ? '<span style="color:#34d399"><i class="ri-check-fill"></i> 已保存并连接成功！在飞书里找机器人发句话试试</span>'
      : '<span style="color:#f59e0b">⚠ 已保存但 token 失败: ' + escHtml(d.warning || '') + '</span>';
    document.getElementById('feishuAppId').value = '';
    document.getElementById('feishuAppSecret').value = '';
    feishuLoadStatus();
  } catch (e) {
    msg.innerHTML = '<span style="color:#f87171"><i class="ri-close-fill"></i> 保存失败: ' + escHtml(e.message) + '</span>';
  }
}

async function feishuToggle() {
  if (!token) return;
  try {
    const r = await fetch('/api/feishu/toggle', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: true }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error('HTTP ' + r.status);
    feishuLoadStatus();
  } catch (e) {
    const el = document.getElementById('feishuSaveMsg');
    if (el) el.innerHTML = '<span style="color:#f87171">切换失败: ' + escHtml(e.message) + '</span>';
  }
}

// ─── 0.9.1 · L1 群机器人 webhook (推送模式) ───

async function copyFeishuScopes(btn) {
  const json = `{
  "scopes": {
    "tenant": [
      "im:message.p2p_msg:readonly",
      "im:message:send_as_bot",
      "im:message.group_at_msg:readonly",
      "im:message.group_msg",
      "im:message:readonly",
      "im:chat:readonly",
      "im:resource",
      "docx:document:readonly",
      "sheets:spreadsheet:readonly",
      "bitable:app:readonly"
    ],
    "user": [
      "docx:document:readonly"
    ]
  }
}`;
  try {
    await navigator.clipboard.writeText(json);
    if (btn) { const old = btn.innerHTML; btn.innerHTML = '<i class="ri-check-fill"></i> 已复制'; setTimeout(() => { btn.innerHTML = old; }, 1500); }
  } catch (e) {
    if (btn) btn.innerHTML = '<i class="ri-close-fill"></i> 复制失败'; 
  }
}

async function wechatLoadStatus() {
  const el = document.getElementById('wechatStatus');
  if (!el) return;
  if (!token) { el.innerHTML = '⚠ 先在『访问 & 会话』填 API Token'; return; }
  try {
    const r = await fetch('/api/wechat/status', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const s = await r.json();
    const listener = s.listener || {};
    const badge = document.getElementById('wechatBadge');
    if (badge) {
      if (!s.configured) { badge.textContent = '未连接'; badge.className = 'chan-badge off'; }
      else if (s.silent) { badge.textContent = '已静默'; badge.className = 'chan-badge warn'; }
      else if (!s.window_open) { badge.textContent = '窗口已关'; badge.className = 'chan-badge warn'; }
      else { badge.textContent = '已连接'; badge.className = 'chan-badge on'; }
    }
    let liveInner;
    if (!s.configured) {
      liveInner = '<span class="live-dot idle"></span> 未连接 · 生成二维码扫码登录后开启';
    } else {
      const winTxt = s.window_open
        ? `<span style="color:var(--dim2)">· 窗口开着 (${s.context_age_hours ?? '?'}h 前说过话)</span>`
        : s.silent
          ? '<span style="color:var(--dim2)">· 已静默 (微信发 Daemonkey start 唤醒)</span>'
          : '<span style="color:#fbbf24">· 24h 窗口已关 · 你先发一句即开</span>';
      liveInner = `<span class="live-dot ${listener.alive ? 'on' : 'off'}"></span> 监听 ${listener.alive ? '在线' : '离线'}
        ${listener.messages_in != null ? `<span class="chan-chip">收 <b>${listener.messages_in}</b></span><span class="chan-chip">回 <b>${listener.replies_out}</b></span>` : ''}
        ${winTxt}`;
    }
    el.innerHTML = liveInner;
  } catch (e) {
    el.innerHTML = '<i class="ri-close-fill"></i> 状态加载失败: ' + escHtml(e.message);
  }
}

async function wechatGenQr() {
  const box = document.getElementById('wechatQrBox');
  if (!token) { DaemonkeyAlert({ title: '缺 token', message: '先在『访问 & 会话』填 API Token' }); return; }
  if (_wechatQrPoll) { clearInterval(_wechatQrPoll); _wechatQrPoll = null; }
  box.style.display = 'block';
  box.innerHTML = '<div class="field-hint">取二维码中…</div>';
  try {
    const r = await fetch('/api/wechat/login/qr', {
      method: 'POST', headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    box.innerHTML = `
      <img src="${d.qr_data_uri}" alt="微信扫码" style="width:220px;height:220px;border-radius:10px;background:#fff;padding:8px"/>
      <div class="field-hint" style="margin-top:6px">用<b>手机微信</b>扫这个码 → 授权。约 3-4 分钟有效。</div>
      <div id="wechatQrPollMsg" class="field-hint" style="margin-top:4px">⏳ 等待扫码…</div>
    `;
    let tries = 0;
    _wechatQrPoll = setInterval(() => wechatPollQr(d.qrcode_id, ++tries), 2500);
  } catch (e) {
    box.innerHTML = '<div class="field-hint fail"><i class="ri-close-fill"></i> ' + escHtml(e.message) + '</div>';
  }
}

async function wechatPollQr(qrcodeId, tries) {
  const msg = document.getElementById('wechatQrPollMsg');
  if (tries > 96) { // ~4 分钟
    if (_wechatQrPoll) { clearInterval(_wechatQrPoll); _wechatQrPoll = null; }
    if (msg) msg.innerHTML = '⌛ 二维码过期了·点上面按钮重新生成';
    return;
  }
  try {
    const r = await fetch('/api/wechat/login/poll?qrcode=' + encodeURIComponent(qrcodeId), {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    const d = await r.json();
    if (d.logged_in) {
      if (_wechatQrPoll) { clearInterval(_wechatQrPoll); _wechatQrPoll = null; }
      if (msg) msg.innerHTML = '<span style="color:#34d399"><i class="ri-check-fill"></i> 已连接!监听已自动拉起·你在微信发句话试试</span>';
      wechatLoadStatus();
    } else if (d.status === 'expired') {
      if (_wechatQrPoll) { clearInterval(_wechatQrPoll); _wechatQrPoll = null; }
      if (msg) msg.innerHTML = '⌛ 二维码过期·点上面按钮重新生成';
    } else if (msg) {
      msg.innerHTML = '⏳ 等待扫码…';
    }
  } catch (e) { /* 网络抖动·下一拍再试 */ }
}

let _wechatFreqPresets = [];
async function wechatLoadFrequency() {
  const el = document.getElementById('wechatFreq');
  if (!el) return;
  if (!token) { el.innerHTML = '⚠ 先填 token'; return; }
  try {
    const r = await fetch('/api/wechat/frequency', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    _wechatFreqPresets = d.presets || [];
    wechatRenderFreq(d.current);
  } catch (e) {
    el.innerHTML = '<i class="ri-close-fill"></i> 加载失败: ' + escHtml(e.message);
  }
}

// 0.9.0 · 频率档 emoji → Remix 表情图标 (统一线条风格 · 替代 🐱🐶 emoji)
const _FREQ_EMOJI_ICON = {
  '\u{1F6AB}': 'ri-close-circle-line',   // 🚫 关闭
  '\u{1F63C}': 'ri-emotion-2-line',      // 😼 高冷猫 → 面瘫脸
  '\u{1F431}': 'ri-emotion-2-line',      // 🐱 猫系
  '\u2696\uFE0F': 'ri-emotion-normal-line', // ⚖️ 均衡 → 正常脸
  '\u{1F436}': 'ri-emotion-happy-line',  // 🐶 犬系 → 笑脸
  '\u{1F415}': 'ri-emotion-happy-line',  // 🐕 黏人犬
};
function freqIcon(emoji) { return _FREQ_EMOJI_ICON[emoji] || null; }

function wechatRenderFreq(currentId) {
  const el = document.getElementById('wechatFreq');
  const desc = document.getElementById('wechatFreqDesc');
  el.innerHTML = _wechatFreqPresets.map(p => {
    const ic = freqIcon(p.emoji);
    const iconHtml = ic ? `<span class="freq-emoji"><i class="${ic}"></i></span>` : `<span class="freq-emoji">${p.emoji}</span>`;
    return `<button class="freq-pill ${p.id === currentId ? 'active' : ''}" onclick="wechatSetFrequency('${p.id}')" title="${escHtml(p.desc)}">
      ${iconHtml}<span class="freq-label">${escHtml(p.label)}</span>
    </button>`;
  }).join('');
  const cur = _wechatFreqPresets.find(p => p.id === currentId);
  if (desc) {
    const ic = cur ? freqIcon(cur.emoji) : null;
    const curIcon = ic ? `<i class="${ic}"></i>` : (cur ? cur.emoji : '');
    desc.innerHTML = currentId === 'custom'
      ? '当前是<b>自定义</b>档 (你手改过 .env 的 Daemonkey_PROACTIVE_* )·点任意档位归一'
      : (cur ? `当前:${curIcon} <b>${escHtml(cur.label)}</b> · ${escHtml(cur.desc)}` : '');
  }
}

async function wechatSetFrequency(presetId) {
  if (!token) return;
  const el = document.getElementById('wechatFreq');
  try {
    const r = await fetch('/api/wechat/frequency', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ preset: presetId }),
    });
    if (!r.ok) { const t = await r.text(); throw new Error('HTTP ' + r.status + ' ' + t); }
    const d = await r.json();
    wechatRenderFreq(d.current);
  } catch (e) {
    DaemonkeyAlert({ title: '设置失败', message: e.message });
  }
}

// ─── wish-fb6b7427 · 通知设置面板 ───
// 三条通道各自开关 · 音效(事项A已上线) / Windows toast(事项B) / 标签闪烁(事项C)
async function renderSettingsNotify() {
  const body = document.getElementById('settingsBody');
  body.innerHTML = '<div class="dash-empty">加载中…</div>';

  let cfg = { pet_sound: true, windows_toast: false, tab_flash: false };
  try {
    const resp = await fetch('/notification-config', { headers: { 'Authorization': 'Bearer ' + token } });
    if (resp.ok) cfg = await resp.json();
  } catch (_) {}

  body.innerHTML = `
    <div class="llm-section">
      <div class="llm-section-head">
        <h3><i class="ri-notification-3-fill"></i> 通知 · 干完 / 等你拍板时怎么提醒你</h3>
        <span class="llm-hint">三条通道各自开关 · 保存即生效 · 不用重启 daemon</span>
      </div>
      <div class="field">
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
          <input type="checkbox" id="ntfPetSound" ${cfg.pet_sound ? 'checked' : ''}>
          <span><i class="ri-volume-up-fill"></i> 桌宠提示音</span>
        </label>
        <div class="field-hint">干完一个 turn 时 · 桌宠「喵」动作 + 播 ding/manbo.wav · 需桌宠在跑</div>
      </div>
      <div class="field">
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
          <input type="checkbox" id="ntfToast" ${cfg.windows_toast ? 'checked' : ''}>
          <span><i class="ri-windows-fill"></i> Windows 系统通知</span>
        </label>
        <div class="field-hint">浏览器不开 WebUI 也能在通知中心收到 · 需 daemon 机装 winotify</div>
      </div>
      <div class="field">
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
          <input type="checkbox" id="ntfTabFlash" ${cfg.tab_flash ? 'checked' : ''}>
          <span><i class="ri-flashlight-fill"></i> 浏览器标签闪烁</span>
        </label>
        <div class="field-hint">WebUI 标签在后台时标题闪烁 · 切回标签自动停</div>
      </div>
      <div class="actions" style="margin-top:12px">
        <button class="btn-primary" id="ntfSave"><i class="ri-save-fill"></i> 保存</button>
      </div>
      <div id="ntfResult" style="margin-top:8px;font-size:13px"></div>
    </div>
  `;

  document.getElementById('ntfSave').onclick = async () => {
    const resEl = document.getElementById('ntfResult');
    resEl.innerHTML = '<span style="color:var(--sys)"><i class="ri-loader-fill"></i> 保存中…</span>';
    try {
      const resp = await fetch('/notification-config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
        body: JSON.stringify({
          pet_sound: document.getElementById('ntfPetSound').checked,
          windows_toast: document.getElementById('ntfToast').checked,
          tab_flash: document.getElementById('ntfTabFlash').checked,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-error-warning-fill"></i> ${escHtml(data.detail || '保存失败')}</span>`;
        return;
      }
      if (data.config) _ntfCfg = data.config;  // 保存即生效 · 不用刷新
      resEl.innerHTML = '<span style="color:#6ed27a"><i class="ri-check-fill"></i> 已保存 · 下次完成通知起生效</span>';
    } catch (e) {
      resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-close-fill"></i> ${escHtml(e.message)}</span>`;
    }
  };
}

function renderSettingsData() {
  const body = document.getElementById('settingsBody');
  body.innerHTML = `
    <div class="llm-section">
      <div class="llm-section-head"><h3><i class="ri-save-fill"></i> 本地数据</h3></div>
      <div class="field-hint">
        浏览器本地存了:
        <ul style="margin:6px 0 0 18px;padding:0;color:var(--dim)">
          <li>token (Bearer · 跟 daemon 握手用)</li>
          <li>sessionId (当前对话 id)</li>
          <li>autoConfirm (工具确认策略)</li>
          <li>别名 (session 重命名 / 置顶 / 归档)</li>
        </ul>
        服务端的数据 (对话历史 / 心愿单 / 雷达 / 工坊) 不受影响 · 都在本机磁盘.
      </div>
      <div class="actions" style="margin-top:18px">
        <button class="btn-danger" onclick="resetAll()">清空本地数据 + 刷新</button>
      </div>
    </div>
  `;
}

async function resetAll() {
  const ok = await DaemonkeyConfirm({
    title: '清空所有本地数据',
    message: '会清掉 token / sessionId / 别名等浏览器本地数据·然后刷新。\n服务端的对话不会动·随时能找回来。',
    okText: '清空并退出',
    cancelText: '再想想',
    danger: true,
  });
  if (!ok) return;
  localStorage.clear();
  location.reload();
}
$modal.addEventListener('click', e => { if (e.target === $modal) closeSettings(); });

// ──────────────────────────────────────────────────────────────
// 卷三十四补丁 · 统一 H5 modal · 替代浏览器原生 confirm/prompt/alert
//
// 三个 promise 函数：
//   DaemonkeyConfirm({ title, message, okText, cancelText, danger })  → Promise<boolean>
//   DaemonkeyPrompt({ title, message, default, placeholder, okText }) → Promise<string|null>
//   DaemonkeyAlert({ title, message, okText, icon })                  → Promise<void>
//
// 行为：
//   - 一次只能开一个 modal · 后调的进队列等前一个 resolve
//   - Enter = 确定 · ESC = 取消
//   - 点遮罩 = 取消（alert 模式下也允许·等价 OK）
// ──────────────────────────────────────────────────────────────
const _omEl = document.getElementById('DaemonkeyModal');
const _omIcon = document.getElementById('omIcon');
const _omTitle = document.getElementById('omTitle');
const _omMessage = document.getElementById('omMessage');
const _omInputWrap = document.getElementById('omInputWrap');
const _omInput = document.getElementById('omInput');
const _omCancel = document.getElementById('omCancel');
const _omOk = document.getElementById('omOk');
const _omBody = _omEl ? _omEl.querySelector('.modal-body') : null;

let _omQueue = [];
let _omActive = null;

function _omRunNext() {
  if (_omActive || _omQueue.length === 0) return;
  const job = _omQueue.shift();
  _omActive = job;
  _omRender(job);
}

function _omRender(job) {
  const {
    mode, title, message, defaultValue, placeholder,
    okText, cancelText, danger, icon, resolve,
  } = job;

  // 默认 icon
  let useIcon = icon;
  if (!useIcon) {
    if (mode === 'alert') useIcon = 'ℹ️';
    else if (mode === 'prompt') useIcon = '✏️';
    else if (danger) useIcon = '<i class="ri-error-warning-fill"></i>';
    else useIcon = '❓';
  }

  _omIcon.innerHTML = useIcon;
  _omTitle.innerHTML = title || (
    mode === 'alert' ? '提示' :
    mode === 'prompt' ? '输入' :
    '确认'
  );

  // message 支持 string 或 { html: '...' }
  if (message && typeof message === 'object' && message.html) {
    _omMessage.innerHTML = message.html;
  } else if (message) {
    _omMessage.textContent = message;
  } else {
    _omMessage.textContent = '';
  }

  // prompt 才显示 input
  if (mode === 'prompt') {
    _omInputWrap.hidden = false;
    _omInput.value = defaultValue || '';
    _omInput.placeholder = placeholder || '';
  } else {
    _omInputWrap.hidden = true;
    _omInput.value = '';
  }

  // 按钮
  _omOk.textContent = okText || (mode === 'alert' ? '我知道了' : '确定');
  _omCancel.textContent = cancelText || '取消';

  // danger 风格
  _omOk.className = 'btn-primary' + (danger ? ' danger' : '');

  // alert 模式 · 只显示一个按钮 · 撑满
  if (mode === 'alert') {
    _omBody.classList.add('alert-only');
  } else {
    _omBody.classList.remove('alert-only');
  }

  _omEl.classList.add('open');
  _omEl.setAttribute('aria-hidden', 'false');

  // focus 输入框 / 默认按钮
  setTimeout(() => {
    if (mode === 'prompt') {
      _omInput.focus();
      _omInput.select();
    } else {
      _omOk.focus();
    }
  }, 30);
}

function _omClose(result) {
  if (!_omActive) return;
  const job = _omActive;
  _omActive = null;
  _omEl.classList.remove('open');
  _omEl.setAttribute('aria-hidden', 'true');
  _omBody.classList.remove('alert-only');
  // 让动画走完再 resolve · 防止后续 modal 跳着开
  setTimeout(() => {
    job.resolve(result);
    _omRunNext();
  }, 40);
}

if (_omEl) {
  // 点 OK
  _omOk.addEventListener('click', () => {
    if (!_omActive) return;
    if (_omActive.mode === 'prompt') {
      _omClose(_omInput.value);
    } else if (_omActive.mode === 'alert') {
      _omClose(undefined);
    } else {
      _omClose(true);
    }
  });
  // 点取消
  _omCancel.addEventListener('click', () => {
    if (!_omActive) return;
    if (_omActive.mode === 'prompt') _omClose(null);
    else if (_omActive.mode === 'alert') _omClose(undefined);
    else _omClose(false);
  });
  // 点遮罩
  _omEl.addEventListener('click', (e) => {
    if (e.target !== _omEl) return;
    if (!_omActive) return;
    if (_omActive.mode === 'alert') _omClose(undefined);
    else if (_omActive.mode === 'prompt') _omClose(null);
    else _omClose(false);
  });
  // 全局键盘
  document.addEventListener('keydown', (e) => {
    if (!_omActive) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      _omCancel.click();
    } else if (e.key === 'Enter') {
      // prompt 模式下 input focus 时 · 让 Enter 触发 OK (避免 textarea 类的多行)
      if (_omActive.mode === 'prompt' && document.activeElement !== _omInput) return;
      e.preventDefault();
      _omOk.click();
    }
  });
}

function DaemonkeyConfirm(opts) {
  opts = opts || {};
  return new Promise((resolve) => {
    _omQueue.push({ mode: 'confirm', ...opts, resolve });
    _omRunNext();
  });
}
function DaemonkeyPrompt(opts) {
  opts = opts || {};
  return new Promise((resolve) => {
    _omQueue.push({ mode: 'prompt', ...opts, resolve });
    _omRunNext();
  });
}
function DaemonkeyAlert(opts) {
  // 支持 DaemonkeyAlert('字符串') 速写
  if (typeof opts === 'string') opts = { message: opts };
  opts = opts || {};
  return new Promise((resolve) => {
    _omQueue.push({ mode: 'alert', ...opts, resolve });
    _omRunNext();
  });
}

// ---------- session drawer ----------

const $drawer = document.getElementById('drawer');
const $drawerBackdrop = document.getElementById('drawerBackdrop');
const $sessionList = document.getElementById('sessionList');
const $currentLabel = document.getElementById('currentSessionLabel');

function openDrawer() {
  if (!token) {
    addSys('⚠ 还没填 token —— 点右上角 ⚙ 设置');
    openSettings();
    return;
  }
  $drawer.classList.add('open');
  $drawerBackdrop.classList.add('open');
  _refreshSessionLists();
}
function closeDrawer() {
  $drawer.classList.remove('open');
  $drawerBackdrop.classList.remove('open');
}

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
async function collectSessionDocs() {
  const docs = [];       // [{name, url, ext, kind}]
  const seen = new Set();

  // 1. 主数据源: 后端 artifacts 端点 (扫 session 主 jsonl + 归档 compact/prune 文件 · 压缩也不丢)
  try {
    if (sessionId) {
      const r = await fetch(`/sessions/${encodeURIComponent(sessionId)}/artifacts`, {
        headers: { 'Authorization': 'Bearer ' + token },
      });
      if (r.ok) {
        const data = await r.json();
        for (const a of (data.artifacts || [])) {
          if (!a || !a.url || seen.has(a.url)) continue;
          seen.add(a.url);
          docs.push({ name: a.name || '产物', url: a.url, ext: a.ext || '', kind: 'workshop' });
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
function _docCategory(ext) {
  for (const c of _DOC_CATS) if (c.exts.includes(ext)) return c;
  return _DOC_CATS[1]; // 兜底进文本组
}

async function renderDocsView() {
  const dv = document.getElementById('docsView');
  if (!dv) return;
  dv.innerHTML = `
    <div class="docs-view-head">
      <span class="docs-view-title"><i class="ri-file-list-3-fill"></i> 本会话产物</span>
      <span class="docs-view-sub" id="docsViewSub">收集…</span>
      <button class="docs-view-close" onclick="closeDocsView()" title="返回对话"><i class="ri-arrow-left-line"></i> 返回对话</button>
    </div>
    <div class="docs-view-body" id="docsViewBody"><div class="docs-view-loading">扫描会话中的文档…</div></div>
  `;
  const docs = await collectSessionDocs();
  const body = document.getElementById('docsViewBody');
  const sub = document.getElementById('docsViewSub');
  if (sub) sub.textContent = `${docs.length} 个文档`;
  if (!docs.length) {
    body.innerHTML = `<div class="docs-view-empty">
      <i class="ri-file-list-3-line" style="font-size:34px;opacity:.3"></i>
      <div>本会话还没有产出</div>
      <div class="docs-view-hint">让 Daemonkey 生成报告 / 口播稿 / 周报后 · 文档会出现在这里</div>
    </div>`;
    return;
  }
  // 按类型分类: 办公文档 / 文本·报告 / 图片 / 音频 / 视频
  let html = '';
  for (const cat of _DOC_CATS) {
    const group = docs.filter(d => _docCategory(d.ext).key === cat.key);
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
  const isPreviewable = ['md','txt','png','jpg','jpeg','gif','webp','mp3','wav','mp4','webm','pdf'].includes(d.ext);
  const btn = (ic, label, fn, cls) => `<button class="dvi-btn ${cls}" onclick="event.stopPropagation();${fn}('${domain}','${filename}','${d.ext}')" title="${label}"><i class="${ic}"></i><span>${label}</span></button>`;
  return `<div class="docs-view-item" data-ext="${d.ext}" data-url="${safeUrl}" data-domain="${domain}" data-filename="${filename}">
    <span class="dvi-ic">${_docIcon(d.ext)}</span>
    <span class="dvi-body">
      <span class="dvi-name">${escHtml(d.name)}</span>
      <span class="dvi-meta">${String(d.ext).toUpperCase()} · ${_docCategory(d.ext).label}</span>
    </span>
    <span class="dvi-actions">
      ${isPreviewable ? btn('ri-eye-line','预览','_docOpenInBrowser') : ''}
      ${btn('ri-mac-line','应用打开','_docOpenLocal')}
      ${btn('ri-save-3-line','另存为','_docSaveAs')}
    </span>
  </div>`;
}

// 浏览器打开 → 统一弹框预览 (卷八十一续 · 用户 拍板: 复用知识库弹框骨架 · 不再新标签)
// md/txt → fetch preview 渲染 markdown; 图片/音频/视频/pdf → 弹框内嵌; docx/xlsx/pptx → 下载
async function _docOpenInBrowser(domain, filename, ext) {
  try {
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
        _showPreviewModal({ title: dispName, metaLine: ext.toUpperCase() + ' · outputs 产物', bodyHtml });
      } else if (['png','jpg','jpeg','gif','webp'].includes(ext)) {
        _showPreviewModal({ title: dispName, metaLine: '图片', raw: true, bodyHtml: `<img src="${url}" alt="${escHtml(dispName)}" class="pv-img">` });
      } else if (['mp3','wav'].includes(ext)) {
        _showPreviewModal({ title: dispName, metaLine: '音频', raw: true, bodyHtml: `<audio controls preload="metadata" src="${url}" class="pv-media" style="width:100%"></audio>` });
      } else if (['mp4','webm'].includes(ext)) {
        _showPreviewModal({ title: dispName, metaLine: '视频', raw: true, bodyHtml: `<video controls preload="metadata" src="${url}" class="pv-media"></video>` });
      } else if (ext === 'pdf') {
        _showPreviewModal({ title: dispName, metaLine: 'PDF', raw: true, bodyHtml: `<iframe src="${url}" class="pv-pdf"></iframe>` });
      } else if (ext === 'html') {
        // html 预览用 sandbox iframe · 禁脚本/弹窗 · 防恶意 html (卷八十一 产物 html 支持)
        _showPreviewModal({ title: dispName, metaLine: 'HTML · outputs 产物', raw: true, bodyHtml: `<iframe src="${url}" class="pv-html" sandbox="allow-same-origin" loading="lazy"></iframe>` });
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
      _showPreviewModal({ title: dispName, metaLine: ext.toUpperCase() + ' · ' + domain, bodyHtml });
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
      // html 预览用 sandbox iframe · 禁脚本/弹窗 · 防恶意 html (卷八十一 产物 html 支持)
      const url = domain === 'reports'
        ? `/reports/${encodeURIComponent(filename)}${t}`
        : `/workshop/file/${encodeURIComponent(domain)}/${encodeURIComponent(filename)}${t}`;
      _showPreviewModal({ title: dispName, metaLine: 'HTML · ' + domain, raw: true, bodyHtml: `<iframe src="${url}" class="pv-html" sandbox="allow-same-origin" loading="lazy"></iframe>` });
    } else {
      // docx/xlsx/pptx 浏览器不能内嵌 → 下载
      await _docSaveAs(domain, filename);
    }
  } catch (e) {
    alert('打开失败: ' + e.message);
  }
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

function updateCurrentLabel() {
  $currentLabel.textContent = sessionId ? aliasFor(sessionId) : '新对话';
}

let _sessionListOffset = 0;
let _drawerLastGroupKey = null;   // 分页续接时上一页最后的组 key · 跨页不重复插分组标题
const SESSION_PAGE = 50;

async function refreshSessionList(reset = true) {
  if (reset) {
    _sessionListOffset = 0;
    _drawerLastGroupKey = null;
    $sessionList.innerHTML = '<div class="drawer-empty">加载中…</div>';
  }
  // 关掉可能开着的菜单
  closeSessionMenu();
  try {
    const params = new URLSearchParams({ api_only: 'true', limit: String(SESSION_PAGE), offset: String(_sessionListOffset) });
    if (showArchivedSessions) params.set('archived_only', 'true');
    else params.set('include_archived', 'false');
    const r = await fetch('/sessions?' + params.toString(), {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) {
      $sessionList.innerHTML = '<div class="drawer-empty">加载失败 [' + r.status + ']</div>';
      return;
    }
    const data = await r.json();
    archivedCount = data.archived_count || 0;
    // 把服务端 meta 同步到缓存 (label / pinned / archived)
    for (const s of (data.sessions || [])) {
      sessionMetaCache[s.session_id] = {
        label: s.label || null,
        pinned_at: s.pinned_at || null,
        archived_at: s.archived_at || null,
        last_model_cfg: s.last_model_cfg || null,
      };
    }
    if (reset && (!data.sessions || data.sessions.length === 0)) {
      const empty = showArchivedSessions
        ? '归档区是空的 · 已归档的对话会跑这儿'
        : '还没有对话 · 点 + 新对话开始';
      $sessionList.innerHTML = `<div class="drawer-empty">${empty}</div>`;
      renderArchivedToggle();
      return;
    }
    if (reset) $sessionList.innerHTML = '';
    // 分组渲染 (今天/昨天/本周/本月/更早) · 与专注版共用 _appendSessionGrouped · 跨页不重复插标题
    let gk = _drawerLastGroupKey;
    for (const s of data.sessions) gk = _appendSessionGrouped($sessionList, s, gk);
    _drawerLastGroupKey = gk;
    // 还有更多 → 底部加载更多按钮
    const hasMore = (data.sessions || []).length >= SESSION_PAGE;
    const loadMoreEl = document.getElementById('sessionLoadMore');
    if (loadMoreEl) loadMoreEl.remove();
    if (hasMore) {
      const btn = document.createElement('div');
      btn.id = 'sessionLoadMore';
      btn.className = 'drawer-loadmore';
      btn.textContent = '加载更早的会话';
      btn.onclick = () => { _sessionListOffset += SESSION_PAGE; refreshSessionList(false); };
      $sessionList.appendChild(btn);
    }
    renderArchivedToggle();
    // 当前 session label 可能从服务端拿到了 · 刷新顶部 pill
    updateCurrentLabel();
    _startSessionRunPoll();  // 运行状态轮询 · 工作台抽屉列表可见即启动
  } catch (e) {
    if (reset) $sessionList.innerHTML = '<div class="drawer-empty">网络出错: ' + e.message + '</div>';
  }
}

// 会话按时间分组 (用户 2026-08-15 拍板 · 今天/昨天/本周/本月/更早 · 专注版 + 工作台共用)
// 分组 key 是【相对今天】的归一字符串 · 跨天自然滚动 · 不依赖任何绝对日期
function _sessionGroupKey(mtime) {
  if (!mtime) return '更早';
  const d = new Date(mtime);
  if (isNaN(d.getTime())) return '更早';
  const now = new Date();
  const startOfDay = function (x) { const t = new Date(x); t.setHours(0, 0, 0, 0); return t; };
  const today = startOfDay(now).getTime();
  const dayMs = 86400000;
  const t = startOfDay(d).getTime();
  if (t >= today) return '今天';
  if (t >= today - dayMs) return '昨天';
  // 本周: 周一 0 点起
  const dow = (now.getDay() + 6) % 7; // 0=周一
  const weekStart = today - dow * dayMs;
  if (t >= weekStart) return '本周';
  // 本月: 1 号 0 点起
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1).getTime();
  if (t >= monthStart) return '本月';
  return '更早';
}
function _sessionGroupHeaderEl(key) {
  const h = document.createElement('div');
  h.className = 'session-group-header';
  h.textContent = key;
  return h;
}
// 列表追加带分组: 组变化时插标题 · 返回当前组 key (调用方分页续接时传入续用)
// 专注版 renderCompactSessions 与工作台 refreshSessionList 共用 · 一处写两处受益
function _appendSessionGrouped(list, session, lastGroupKey) {
  const gk = _sessionGroupKey(session.mtime);
  if (gk !== lastGroupKey) list.appendChild(_sessionGroupHeaderEl(gk));
  list.appendChild(buildSessionRow(session));
  return gk;
}

function buildSessionRow(s) {
  const div = document.createElement('div');
  const isPinned = !!s.pinned_at;
  const isArchived = !!s.archived_at;
  const isActive = !!s.active;
  div.className = 'session-item' + (s.session_id === sessionId ? ' active' : '')
                 + (isPinned ? ' pinned' : '')
                 + (isArchived ? ' archived' : '')
                 + (isActive ? ' session-running' : '');
  div.dataset.sid = s.session_id;

  const name = document.createElement('div');
  name.className = 'session-name';
  const pinIcon = isPinned ? '<span class="sp-pin" title="置顶">📌</span>' : '';
  const archIcon = isArchived ? '<span class="sp-arch" title="已归档">📁</span>' : '';
  const runIcon = isActive ? '<span class="sp-run" title="正在运行"><i class="ri-loader-4-line spin"></i></span>' : '';
  name.innerHTML = pinIcon + archIcon + runIcon + '<span class="sp-label">' + escHtml(aliasFor(s.session_id)) + '</span>';

  const meta = document.createElement('div');
  meta.className = 'session-meta';
  const when = s.mtime ? new Date(s.mtime).toLocaleString('zh-CN', { hour12: false }) : '';
  meta.innerHTML = `<span>${s.turns} turns</span><span>${when}</span>`;
  div.appendChild(name);
  div.appendChild(meta);

  const actions = document.createElement('div');
  actions.className = 'session-actions';
  const menuBtn = document.createElement('button');
  menuBtn.className = 'sa-menu';
  menuBtn.title = '更多操作';
  menuBtn.textContent = '⋯';
  menuBtn.onclick = (e) => { e.stopPropagation(); openSessionMenu(s.session_id, menuBtn); };
  actions.appendChild(menuBtn);
  div.appendChild(actions);

  div.onclick = () => switchToSession(s.session_id);
  return div;
}

function renderArchivedToggle() {
  let el = document.getElementById('archivedToggle');
  if (!el) {
    el = document.createElement('div');
    el.id = 'archivedToggle';
    el.className = 'archived-toggle';
    $sessionList.parentElement.appendChild(el);
  }
  if (showArchivedSessions) {
    el.innerHTML = `<button onclick="toggleArchivedView()">← 返回会话列表</button>`;
  } else if (archivedCount > 0) {
    el.innerHTML = `<button onclick="toggleArchivedView()">查看已归档 (${archivedCount})</button>`;
  } else {
    el.innerHTML = '';
  }
}

function toggleArchivedView() {
  showArchivedSessions = !showArchivedSessions;
  _refreshSessionLists();
}

// ── session 行的 ⋯ popover 菜单 ───────────────────────────
let _sessionMenuEl = null;
function closeSessionMenu() {
  if (_sessionMenuEl && _sessionMenuEl.parentNode) {
    _sessionMenuEl.parentNode.removeChild(_sessionMenuEl);
  }
  _sessionMenuEl = null;
}

function openSessionMenu(sid, anchorEl) {
  closeSessionMenu();
  const meta = sessionMetaCache[sid] || {};
  const isPinned = !!meta.pinned_at;
  const isArchived = !!meta.archived_at;

  const menu = document.createElement('div');
  menu.className = 'session-menu';
  menu.innerHTML = `
    <button class="sm-item" onclick="event.stopPropagation();togglePinSession('${sid}')">
      <i class="ri-pushpin-${isPinned ? 'fill' : 'line'}"></i> ${isPinned ? '取消置顶' : '置顶'}
    </button>
    <button class="sm-item" onclick="event.stopPropagation();renameSession('${sid}')">
      <i class="ri-edit-2-line"></i> 重命名
    </button>
    <button class="sm-item" onclick="event.stopPropagation();toggleArchiveSession('${sid}')">
      <i class="ri-${isArchived ? 'folder-open' : 'folder'}-line"></i> ${isArchived ? '取消归档' : '归档'}
    </button>
    <div class="sm-sep"></div>
    <button class="sm-item danger" onclick="event.stopPropagation();deleteSession('${sid}')">
      <i class="ri-delete-bin-6-line"></i> 删除
    </button>
  `;
  document.body.appendChild(menu);
  _sessionMenuEl = menu;

  // 定位 · 贴 anchorEl 右下
  const rect = anchorEl.getBoundingClientRect();
  menu.style.left = Math.max(8, rect.right - menu.offsetWidth) + 'px';
  menu.style.top = (rect.bottom + 4) + 'px';

  // 点别处关掉
  setTimeout(() => {
    document.addEventListener('click', _onceCloseSessionMenu, { once: true, capture: true });
  }, 0);
}
function _onceCloseSessionMenu(e) {
  // 如果点的就是菜单内 · 不关
  if (_sessionMenuEl && _sessionMenuEl.contains(e.target)) {
    document.addEventListener('click', _onceCloseSessionMenu, { once: true, capture: true });
    return;
  }
  closeSessionMenu();
}

async function _patchSessionMeta(sid, patch) {
  try {
    const r = await fetch(`/sessions/${encodeURIComponent(sid)}/meta`, {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(patch),
    });
    if (!r.ok) {
      const txt = await r.text().catch(() => '');
      await DaemonkeyAlert({
        title: `操作失败 [${r.status}]`,
        message: txt.slice(0, 400) || '服务端没返详情',
        icon: '<i class="ri-error-warning-fill"></i>',
      });
      return false;
    }
    const data = await r.json();
    sessionMetaCache[sid] = data.meta || {};
    return true;
  } catch (e) {
    await DaemonkeyAlert({ title: '网络出错', message: e.message, icon: '<i class="ri-error-warning-fill"></i>' });
    return false;
  }
}

// 会话元数据变更后统一刷新两个列表 (工作台抽屉 + 专注版) · 改一处四处受益 (rename/pin/archive/delete 共用)
function _refreshSessionLists() {
  refreshSessionList();              // 工作台抽屉
  if (typeof renderCompactSessions === 'function' && !document.getElementById('compactSessionList')?.hidden) {
    renderCompactSessions(true);     // 专注版重拉 (无缓存 · 直接拿最新排序)
  }
}

async function togglePinSession(sid) {
  closeSessionMenu();
  const cur = sessionMetaCache[sid] || {};
  const want = !cur.pinned_at;
  const ok = await _patchSessionMeta(sid, { pinned: want });
  if (ok) _refreshSessionLists();
}

async function toggleArchiveSession(sid) {
  closeSessionMenu();
  const cur = sessionMetaCache[sid] || {};
  const want = !cur.archived_at;
  const ok = await _patchSessionMeta(sid, { archived: want });
  if (ok) {
    // 归档了如果就是当前 session · 切回新对话
    if (want && sid === sessionId) {
      newConversation();
    } else {
      _refreshSessionLists();
    }
  }
}

async function deleteSession(sid) {
  closeSessionMenu();
  const name = aliasFor(sid);
  const ok = await DaemonkeyConfirm({
    title: '删除会话',
    message: { html: `确认删除 <b>「${escHtml(name)}」</b> 吗？<span class="om-hint">会真删 sessions/${escHtml(sid)}.jsonl · 不可恢复</span>` },
    okText: '删除',
    cancelText: '取消',
    danger: true,
  });
  if (!ok) return;
  try {
    const r = await fetch(`/sessions/${encodeURIComponent(sid)}`, {
      method: 'DELETE',
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) {
      const txt = await r.text().catch(() => '');
      await DaemonkeyAlert({
        title: `删除失败 [${r.status}]`,
        message: txt.slice(0, 400) || '服务端没返详情',
        icon: '<i class="ri-error-warning-fill"></i>',
      });
      return;
    }
    delete sessionMetaCache[sid];
    delete sessionAliases[sid];
    saveAliases();
    if (sid === sessionId) {
      newConversation();
    } else {
      _refreshSessionLists();
    }
  } catch (e) {
    await DaemonkeyAlert({ title: '网络出错', message: e.message, icon: '<i class="ri-error-warning-fill"></i>' });
  }
}

async function renameSession(sid) {
  closeSessionMenu();
  const current = aliasFor(sid);
  const name = await DaemonkeyPrompt({
    title: '重命名会话',
    message: '给这个对话起个名字 · 留空清掉别名回到默认显示',
    defaultValue: current,
    placeholder: '比如：挖一下机会 · 看看现在有什么可以做的',
    okText: '保存',
  });
  if (name === null) return;
  const trimmed = (name || '').trim();
  const ok = await _patchSessionMeta(sid, { label: trimmed });
  if (ok) {
    if (trimmed) sessionAliases[sid] = trimmed;
    else delete sessionAliases[sid];
    saveAliases();
    _refreshSessionLists();
    if (sid === sessionId) updateCurrentLabel();
  }
}

// wish-3fef4bc7 · 历史 load 抽成 helper · 给 init / switchToSession 复用
// 历史 load 不动 state.pending 等 · 因为这个 session 没在跑
async function _loadSessionHistory(sid, opts) {
  if (!sid) return;
  const s = _getOrCreateSession(sid);
  _getOrCreateContainer(sid);  // 确保 container 已建
  s.$container.innerHTML = '';
  addSys('加载中…', s.$container);
  // fetch 阶段 · 只有这里失败才清空报错
  let data = null;
  try {
    const r = await fetch(`/sessions/${encodeURIComponent(sid)}/messages`, {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) {
      s.$container.innerHTML = '';
      addSys('加载历史失败 [' + r.status + ']', s.$container);
      return;
    }
    data = await r.json();
  } catch (e) {
    s.$container.innerHTML = '';
    addSys('网络出错: ' + e.message, s.$container);
    return;
  }
  // 渲染阶段 (2026-07-28 修复): 单条隔离 try/catch + 分批让帧 + seq 防交错
  // 旧病: 某条畸形历史渲染抛错 → 外层 catch 清空整个容器 → 用户 看到"什么对话都没有"
  //       700+ 条大会话全量同步渲染 → 浏览器卡死 · 现在每 30 条让一帧
  s.$container.innerHTML = '';
  if (!data.turns || data.turns.length === 0) {
    addSys('（这个对话还是空的）', s.$container);
  } else {
    // wish · 长会话重开只回放最近 N 个 turn · 更早的折叠成顶部"加载全部"入口 · 防重开即卡
    const _full = !!(opts && opts.full);
    let _turns = data.turns;
    let _hidden = 0;
    if (!_full && isFinite(HISTORY_RENDER_WINDOW) && _turns.length > HISTORY_RENDER_WINDOW) {
      _hidden = _turns.length - HISTORY_RENDER_WINDOW;
      _turns = _turns.slice(-HISTORY_RENDER_WINDOW);
    }
    if (_hidden > 0) _ensureLoadEarlierSentinel(s.$container);
    const _seq = (s._histSeq = (s._histSeq || 0) + 1);  // 防交错: 重复加载/切会话后旧渲染停笔
    let _bad = 0;
    // 卷三十六 · 历史回放 · 跟实时 SSE 那一套对齐 · reasoning / tool_call / tool_result 全渲染
    // wish-5256d2a4 · index 循环 · assistant 的 tool_calls 与紧随的 role=tool turns 配对成时间线
    for (let _ti = 0; _ti < _turns.length; _ti++) {
      if (s._histSeq !== _seq) return;  // 有更新的加载接管了容器 · 停笔
      const t = _turns[_ti];
      try {
        // 方案 B (2026-07-28) · 协同自动验收卡重建 · 数据在 append-only system 记录 meta.advisor_review
        if (t.advisor_review) {
          const _ar = t.advisor_review;
          advisorReviewCard(s, { verdict: _ar.verdict || 'FAIL', text: _ar.text || '',
            modelLabel: _ar.model_label || '', round: _ar.round || 1, subId: _ar.sub_id || '',
            historical: true });
        }
        if (t.role === 'user') {
          if (t.src === 'advisor_review') {
            addSys('🧭 顾问验收未通过 · 意见已注入 · 执行者自动修正了一轮', s.$container);
          } else if (t.src === 'proactive') {
            addSys('Daemonkey 主动醒来' + (t.proactive_reason ? ' · ' + t.proactive_reason : ''), s.$container);
          } else {
            // 用户 2026-07-29 · 协同轮 user content 被 daemon 注入了『系统指令+施工单全文』
            // (daemon_api.py:1258-1272) · 历史重建若整条渲染 = 绿色大气泡重复金卡内容·很难看。
            // 剥离逻辑与 daemon_api.py:1197-1202 续链剥皮对齐: 气泡只留 用户 原话·施工单走下面金卡。
            let _uc = t.content || '';
            if (t.advisor_blueprint) {
              const _mark = '[用户 的原始需求]\n';
              const _idx = _uc.indexOf(_mark);
              if (_idx >= 0) _uc = _uc.slice(_idx + _mark.length);
              else if (_uc.startsWith('[系统 · 顾问协同模式')) {
                const _nl = _uc.indexOf('\n');
                _uc = _nl >= 0 ? _uc.slice(_nl + 1) : '';
              }
              _uc = _uc.trim();
            }
            // wish-7c579a20 · 带附件消息: 剥掉系统注入的说明段 + 重建图片/文档(刷新不丢)
            const _attS = _用户AttachStrip(_uc);
            if (_attS.legacy.length || (t.attachments && t.attachments.length)) _uc = _attS.body || _uc;
            const _用户B = addMsg('用户', _uc, null, t.ts, s.$container);
            _render用户Attachments(_用户B,
              (t.attachments && t.attachments.length)
                ? t.attachments
                : _attS.legacy.map(function(b) { return { name: b, path: 'data/runtime/attachments/' + b }; }));
          }
          // 顾问协同卡重建 (用户 2026-07-28: 刷新后顾问框不能消失) · 数据在 user turn meta.advisor_blueprint
          if (t.advisor_blueprint) {
            const _ab = t.advisor_blueprint;
            if (_ab.aborted) {
              addSys('🧭 顾问协同 · 已停止 · 本轮中断', s.$container);
            } else if (_ab.ok === false) {
              addSys('🧭 顾问协同 · 顾问本次没能给出施工单 · 按常规方式推进', s.$container);
            } else {
              advisorCardRenderHistorical(s, { modelLabel: _ab.model_label || '', subId: _ab.sub_id || '' });
              advisorBlueprintCard(s, { modelLabel: _ab.model_label || '', text: _ab.text || '',
                subId: _ab.sub_id || '', historical: true });
            }
          }
        } else if (t.role === 'assistant') {
          if (t.reasoning_content) {
            renderReasoningBubble(t.reasoning_content, { collapsed: true, historical: true }, s.$container);
          }
          if (t.content && t.content.trim()) {
            addMsg('Daemonkey', t.content, null, t.ts, s.$container);
          }
          if (t.tool_calls && t.tool_calls.length) {
            const _results = [];
            let _tj = _ti + 1;
            while (_tj < _turns.length && _turns[_tj].role === 'tool') { _results.push(_turns[_tj].content); _tj++; }
            renderToolTimeline(t.tool_calls.map((tc, k) => ({ name: tc.name, args: tc.arguments, result: k < _results.length ? _results[k] : null })), s.$container);
            _ti = _tj - 1;  // 跳过已配对的 tool turns
          }
        } else if (t.role === 'tool') {
          renderHistoryToolResult(t.content, s.$container);  // 孤儿 tool turn（没配对上 assistant）· 保持老样式
        }
      } catch (e) {
        _bad++;  // 单条畸形不炸全部 · 跳过继续
      }
      if (_ti % 30 === 29) await new Promise(r => setTimeout(r, 0));  // 每 30 条让出一帧
    }
    if (_bad > 0) addSys(`⚠ ${_bad} 条历史渲染失败已跳过 · 内容在 jsonl 里没丢`, s.$container);
    const _tail = _hidden > 0
      ? `(仅显示最近 ${_turns.length} / 共 ${data.count} 条 · 点顶部『加载全部』 · 输入新消息可继续)`
      : `(已加载 ${data.count} 条历史 turn · 这条对话已结束 · 输入新消息可继续)`;
    addSys(_tail, s.$container);
  }
  // 卷四十六续 3 · batch 渲染期间 addMsg 走软滚 · scrollTop 一直在 0 · isNearBottom 一直 false
  // 加载完后必须 force 一次 · 否则 用户 看到的是最旧的消息(顶部) · 不是最新(底部)
  scrollToBottom(s.$container, { force: true });
}

// 会话记住模型 · 切标签时恢复该会话上次用的模型 (没记过/还在跑/已是它 → 不动)
async function _maybeRestoreSessionModel(sid) {
  if (!sid || sid.startsWith('tmp-')) return;
  const st = _sessions[sid];
  if (st && st.pending) return;                 // 这个会话还在跑 · 不动全局模型
  let meta = sessionMetaCache[sid];
  if (!meta || !('last_model_cfg' in meta)) {   // 缓存没有 → 拉一次单条 meta
    try {
      const r = await fetch(`/sessions/${encodeURIComponent(sid)}/meta`, {
        headers: { 'Authorization': 'Bearer ' + token },
      });
      if (r.ok) { const d = await r.json(); meta = sessionMetaCache[sid] = d.meta || {}; }
    } catch (e) { /* 静默 */ }
  }
  const cfg = (meta || {}).last_model_cfg;
  if (!cfg || cfg === (window._currentConfigId || '')) return;
  try {
    const r = await fetch('/models/switch', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: cfg }),
    });
    if (!r.ok) return;                          // config 可能已删 → 保持当前模型
    // 卷八十一续 · 用户"莫名跳模型"= 切会话自动恢复模型但无提示 · 补视觉提示让行为可预期
    try {
      const tip = document.createElement('div');
      tip.className = 'model-switch-tip';
      tip.textContent = `已切到该对话记忆的模型 · 下一轮生效`;
      document.body.appendChild(tip);
      setTimeout(() => tip.remove(), 2800);
    } catch (e) { /* 提示失败不影响切换 */ }
    setTimeout(loadCurrentModel, 300);          // 刷新右上角 label + _currentConfigId
  } catch (e) { /* 静默 */ }
}

async function switchToSession(sid) {
  if (!sid) return;
  if (_docsViewActive) closeDocsView();  // 卷八十一 · 切会话自动关文档视图 (防显示上一会话列表)
  if (sid === sessionId) {
    closeDrawer();
    return;
  }
  // 用户 2026-07-28 钉死 · 切对话标签顾问协同默认关 (防习惯性发消息走错模式)
  if (typeof _advisorCoopReset === 'function') _advisorCoopReset();
  // wish-3fef4bc7 · 真并行 · 切对话不杀 · 旧对话的 fetch / state 留着 · 后台继续跑
  _saveActiveStateToCurrentSession();

  // 目标 sid 在 _sessions 里 = active session (跑过/正在跑) · 切 visible 即可 · 不重 load 历史
  const existing = _sessions[sid];
  if (existing && existing.$container && existing.$container.children.length > 0) {
    sessionId = sid;
    localStorage.setItem(STORAGE.session, sid);
    _setActiveContainer(sid);  // hide 旧 · show 这个 · DOM 直接拿现成的
    // 切回已有标签 · 还原该会话上次滚动位置 (不再每次回顶部)
    requestAnimationFrame(() => {
      if ($messagesPanel && typeof existing.scrollTop === 'number') {
        $messagesPanel.scrollTop = existing.scrollTop;
        _stickToBottom = isNearBottom($messagesPanel);
      }
    });
    // 切回有"未读完成"标记的 · 清掉
    existing.hasUnreadCompletion = false;
    _loadActiveStateFromCurrentSession();
    setSendButtonState(pending ? 'pending' : 'idle');
    setInputLocked(pending);
    showToolProgress(pending);  // 这个 session 还在跑 · 进度条恢复
    updateCurrentLabel();
    _ensureSessionMeta(sid);
    _maybeRestoreSessionModel(sid);
    closeDrawer();
    if (typeof _renderTabBar === 'function') {
      try { _renderTabBar(); } catch {}
    }
    refreshCtxRing();  // wish-bec4f3b9 · 切对话实例 → 圆圈跟着走
    _refreshCompactAfterSwitch();  // 卷八十三 · 简洁版侧栏跟会话走
    refreshPlan();                 // 计划条跟着会话换 (活跃账本是按会话记的)
    return;
  }

  // 目标 sid 不在 _sessions = 历史 session · 创 container + load 历史 + 切 visible
  _getOrCreateSession(sid);
  _setActiveContainer(sid);
  sessionId = sid;
  localStorage.setItem(STORAGE.session, sid);
  updateCurrentLabel();
  _ensureSessionMeta(sid);
  _maybeRestoreSessionModel(sid);
  closeDrawer();
  // 历史 session 是 idle (没有跑的 fetch)
  _loadActiveStateFromCurrentSession();
  setSendButtonState('idle');
  setInputLocked(false);
  showToolProgress(false);
  await _loadSessionHistory(sid);
  refreshCtxRing();  // wish-bec4f3b9 · 切对话实例 → 圆圈跟着走 (历史加载完再刷 · 2026-08-06 修顺序)
  // wish-3fef4bc7 follow-up · 切到 history session 后 · 查 daemon 是否仍有 active turn · 有就启 polling
  _maybeStartPoll(_sessions[sid]);
  if (typeof _renderTabBar === 'function') {
    try { _renderTabBar(); } catch {}
  }
  _refreshCompactAfterSwitch();  // 卷八十三 · 简洁版侧栏跟会话走
  refreshPlan();                 // 计划条跟着会话换
}

// 卷八十三 · 切会话后: 简洁版左侧清单高亮 + 右侧产物面板跟着换会话
// (用户 2026-08-14: 切对话时列表整表重载会闪空白 → 只更新 active 高亮 · 不重拉列表)
function _refreshCompactAfterSwitch() {
  if (!document.body.classList.contains('compact')) return;
  // 只改高亮: 遍历现有行 · data-sid 匹配 sessionId 的加 active · 其余去掉
  const rows = document.querySelectorAll('#compactSessionList .session-item');
  for (const r of rows) {
    r.classList.toggle('active', r.dataset.sid === sessionId);
  }
  // 产物面板跟会话走 (这个轻量 · 每次都刷)
  if (typeof renderCompactArtifacts === 'function') renderCompactArtifacts();
}

/* ═══ wish-5256d2a4 · 工具时间线 + 人话翻译层（方案 D · 用户 2026-07-27 验收 demo 拍板） ═══
   零 token：全部前端本地正则翻译 · daemon 只传原始 tool name/summary/result
   整轮折叠块【默认展开】（用户 拍板"工具默认是不折叠的"）· 单步技术细节默认折叠（点人话行展开） */
const TL_T2C = {
  read_file:'file', write_file:'file', edit_file:'file', glob_files:'file', grep_files:'file',
  outline_file:'file', search_code:'file', lint_check:'file', read_scenario:'file', pdf_read:'file', read_dashboard:'file',
  shell_exec:'exec', python_exec:'exec', service_start:'exec', service_stop:'exec', service_status:'exec', service_list:'exec',
  open_app:'exec', worktree_status:'exec', verify_daemon_endpoints:'exec', request_restart:'exec', update_core:'exec',
  web_search:'web', web_fetch:'web', browser_fetch:'web', browser_act:'web', web_search_image:'web', verify_claim:'web',
  update_bro_note:'memory', recall_memory:'memory', session_search:'memory', update_self_evolution:'memory',
  summarize_session:'memory', manage_knowledge:'memory', manage_client:'memory', extract_playbook:'memory', track_task:'memory',
  create_app:'workshop', update_app:'workshop', list_apps:'workshop', run_app:'workshop', app_versions:'workshop',
  manage_app_asset:'workshop', app_set_secret:'workshop', app_list_secrets:'workshop', app_delete_secret:'workshop',
  delete_app_to_trash:'workshop', restore_app:'workshop', empty_trash:'workshop',
  create_workflow:'workshop', list_flows:'workshop', run_flow:'workshop', rerun_flow_step:'workshop', trust_flow:'workshop', dispatch_subagent:'workshop',
  manage_info_source:'radar', init_domain:'radar', remove_domain:'radar', tag_radar_item:'radar',
  mine_opportunities:'radar', analyze_feasibility:'radar', record_outcome:'radar', toggle_favorite:'radar',
  auto_pipeline:'radar', expand_trend_to_report:'radar', mirror_capability:'radar', propose_next_move:'radar',
  discover_skill:'radar', monthly_review:'radar',
  generate_report:'report', generate_presentation:'report', generate_image:'report', draft_studio:'report',
  replan:'flow', intent_to_wish:'flow', wish_add:'flow', wish_update:'flow', list_iron_rules:'flow', add_iron_rule:'flow',
  wechat_send:'comm', read_clipboard:'comm', write_clipboard:'comm', ssh_remote:'comm', client_handoff:'comm',
  summon_cursor:'comm', mcp_list:'comm', mcp_describe_tool:'comm', mcp_call_tool:'comm',
  take_screenshot:'sense', look_at:'sense', set_emotion:'sense', set_model:'sense',
  create_scheduled_task:'sched', list_scheduled_tasks:'sched', update_scheduled_task:'sched', delete_scheduled_task:'sched',
};
const TL_CATS = {
  file:     { name: '文件·代码', icon: 'ri-file-code-line',    color: '#63b3ed' },
  exec:     { name: '执行·系统', icon: 'ri-terminal-box-line', color: '#f6ad55' },
  web:      { name: '网络·信息', icon: 'ri-global-line',       color: '#48bb78' },
  memory:   { name: '记忆·画像', icon: 'ri-brain-line',        color: '#f687b3' },
  workshop: { name: '工坊·应用', icon: 'ri-apps-2-line',       color: '#b794f6' },
  radar:    { name: '雷达·机会', icon: 'ri-radar-line',        color: '#4fd1c5' },
  report:   { name: '报告·内容', icon: 'ri-quill-pen-line',    color: '#f6e05e' },
  flow:     { name: '流程·自省', icon: 'ri-flow-chart',        color: '#9f7aea' },
  comm:     { name: '通讯·外部', icon: 'ri-send-plane-line',   color: '#68d391' },
  sense:    { name: '感知·表达', icon: 'ri-eye-line',          color: '#76e4f7' },
  sched:    { name: '定时·调度', icon: 'ri-time-line',         color: '#fbd38d' },
};
function tlCatOf(t) { return TL_CATS[TL_T2C[t] || 'exec']; }
function tlHumanDur(s) { return s >= 60 ? Math.floor(s / 60) + '分' + Math.round(s % 60) + '秒' : s + ' 秒'; }
function tlFileName(s) { const m = String(s || '').match(/[\w.\-一-龥]+\.\w+/); return m ? m[0] : String(s || '').slice(0, 40); }

/* 每个工具 = {action: 人话动作(html), result: 人话结果(text)} · 翻译不了就退回原文 */
const TL_HUMAN = {
  edit_file: c => {
    const m = String(c.r).match(/replaced (\d+) occurrence.*?chars \(([+-]\d+)\)/);
    let res = '修改完成，保存校验通过';
    if (m) { const d = parseInt(m[2]); res = `精准替换了 ${m[1]} 处代码 · 文件${d >= 0 ? '变多' : '变少'}了 ${Math.abs(d)} 个字符 · 保存校验通过`; }
    return { action: `修改代码文件 <b>${tlFileName(c.s)}</b>`, result: res };
  },
  write_file: c => ({ action: `写入文件 <b>${tlFileName(c.s)}</b>`, result: '内容已落盘并校验通过' }),
  read_file: c => ({ action: `读了 <b>${tlFileName(c.s)}</b>`, result: '已读完，内容装进上下文' }),
  grep_files: c => ({ action: `在代码里搜索 <b>${String(c.s).replace(/^pattern=/, '').split(' · ')[0].slice(0, 40)}</b>`, result: c.r }),
  glob_files: c => ({ action: `按文件名找 <b>${tlFileName(c.s)}</b>`, result: c.r }),
  shell_exec: c => {
    if (/git commit/.test(c.s)) {
      const m = String(c.r).match(/(\d+) files? changed(?:, (\d+) insertions?.*?(\d+) delet)?/);
      const res = m ? `代码已安全存档：改了 ${m[1]} 个文件${m[2] ? ` · 新增 ${m[2]} 行` : ''}${m[3] ? ` · 删除 ${m[3]} 行` : ''}` : '命令执行成功';
      return { action: '存档代码（git commit）', result: res };
    }
    if (/^git (push|merge|checkout)/.test(c.s.trim())) return { action: `git 操作 <b>${c.s.trim().slice(0, 40)}</b>`, result: c.ok ? '执行成功' : '执行失败' };
    return { action: `跑了命令 <b>${String(c.s).slice(0, 40)}</b>`, result: c.ok ? '命令执行成功' : '命令执行失败' };
  },
  python_exec: c => {
    const m = String(c.r).match(/(\d+)\/(\d+) 全绿/);
    return { action: '跑一段 Python 验证', result: m ? `${m[2]} 项测试全部通过 ✓ 没有破坏任何旧功能` : (c.ok ? (c.r || '执行成功') : (c.r || '执行失败')) };
  },
  verify_daemon_endpoints: c => ({ action: '给整个系统做体检', result: String(c.r).replace(/(\d+)\/(\d+) 路由全绿/, '$2 个接口全部正常').replace('语法 OK', '语法检查通过') }),
  lint_check: c => ({ action: `代码体检 <b>${tlFileName(c.s)}</b>`, result: /clean|✅/.test(c.r) ? '没扫到问题 ✓' : c.r }),
  wish_update: c => ({ action: '更新心愿单状态', result: String(c.r).includes('review') ? '已标记为「等你验收」' : (String(c.r).includes('live') ? '已上线合入主干' : '已更新') }),
  wish_add: c => ({ action: '往心愿单记了一条新想法', result: '已存档，等你拍板' }),
  track_task: c => ({ action: '往任务账本记了一笔', result: '已记住，下次接着干不用重来' }),
  web_search: c => ({ action: `上网搜索 <b>${String(c.s).replace(/"/g, '').slice(0, 40)}</b>`, result: c.r }),
  web_fetch: c => ({ action: '抓取网页正文', result: c.r }),
  browser_act: c => ({ action: '操作网页（点击/填表/收图）', result: c.ok ? '操作完成' : (c.r || '操作失败') }),
  generate_image: c => ({ action: '画了一张图', result: '图片已生成并保存' }),
  generate_report: c => ({ action: '生成了一份报告文档', result: '已落盘，报告库可下载' }),
  wechat_send: c => ({ action: '给你发了条微信', result: '已送达' }),
  update_bro_note: c => ({ action: '记一笔到你的画像档案', result: '已记住，以后每次开机都会带上' }),
  extract_playbook: c => ({ action: '沉淀经验成操作手册', result: '已存档，下次同类任务直接照着做' }),
  recall_memory: c => ({ action: '翻长期记忆', result: c.r }),
  replan: c => ({ action: '请顾问出方案/破局/验收', result: c.ok ? '顾问已给出结论' : (c.r || '未通过') }),
  run_app: c => {
    const aid = String(c.s || '').match(/app-[0-9a-f]{6,}/i);
    const name = aid ? appNameOf(aid[0]) : '';
    return { action: `调用工坊应用 <b>${escHtml(name || tlFileName(c.s))}</b>`, result: c.ok ? '应用跑完了' : (c.r || '应用失败') };
  },
  update_app: c => {
    const aid = String(c.s || '').match(/app-[0-9a-f]{6,}/i);
    const name = aid ? appNameOf(aid[0]) : '';
    return { action: `更新工坊应用 <b>${escHtml(name || tlFileName(c.s))}</b>`, result: c.ok ? '应用已更新' : (c.r || '更新失败') };
  },
  create_app: c => ({ action: '在工坊造了一个新应用', result: '已落档，工坊卡片可见' }),
  request_restart: c => ({ action: '申请重启 daemon 装新代码', result: '即将优雅重启，几秒后自动接上' }),
  take_screenshot: c => ({ action: '看了一眼你的屏幕', result: '已截屏' }),
  look_at: c => ({ action: '看了一张图片', result: '已看完，内容装进上下文' }),
};
function tlHumanize(tool, summary, resultText, ok) {
  const c = { t: tool, s: summary || '', r: resultText || '', ok: ok ? 1 : 0 };
  const f = TL_HUMAN[tool];
  if (f) { try { return f(c); } catch (e) {} }
  // 默认兜底: 统一把 app-xxx / flow-xxx 换成名字 (所有 workshop 工具自动覆盖 · 不漏)
  let s = String(summary || '').slice(0, 60);
  s = s.replace(/app-[0-9a-f]{6,}/gi, m => { const n = appNameOf(m); return n ? n : m; })
        .replace(/flow-[0-9a-f]{6,}/gi, m => { const n = flowNameOf(m); return n ? n : m; });
  return { action: `<b>${escHtml(tool)}</b> ${escHtml(s)}`, result: String(resultText || '') };
}

// app_id → 名字 映射缓存 · 工具卡片显示 app 名 (用户: 别显示 app-ddfd7d92)
let _appNameMap = null;   // {aid: name} · null = 还没拉
let _appNameMapT = 0;
const _APP_NAME_TTL = 60000;   // 60s 内不重复拉
function appNameOf(aid) {
  if (!_appNameMap) { _loadNameMaps(); return ''; }   // 没拉到先返回空 · 渲染用 id 兜底
  return _appNameMap[aid] || '';
}
// flow_id → 名字 映射缓存 · 同 appNameOf (run_flow 等)
let _flowNameMap = null;
let _flowNameMapT = 0;
const _FLOW_NAME_TTL = 60000;
function flowNameOf(fid) {
  if (!_flowNameMap) { _loadNameMaps(); return ''; }
  return _flowNameMap[fid] || '';
}
async function _loadNameMaps() {
  // app 映射 (60s TTL)
  if (!_appNameMap || (Date.now() - _appNameMapT) >= _APP_NAME_TTL) {
    try {
      const r = await fetch('/workshop/apps', { headers: { 'Authorization': 'Bearer ' + token } });
      if (r.ok) {
        const data = await r.json();
        const m = {};
        for (const a of (data.apps || [])) if (a.id) m[a.id] = a.name || a.id;
        _appNameMap = m;
        _appNameMapT = Date.now();
      }
    } catch (e) { /* 静默 · 下轮再试 */ }
  }
  // flow 映射 (60s TTL)
  if (!_flowNameMap || (Date.now() - _flowNameMapT) >= _FLOW_NAME_TTL) {
    try {
      const r = await fetch('/workshop/flows', { headers: { 'Authorization': 'Bearer ' + token } });
      if (r.ok) {
        const data = await r.json();
        const m = {};
        const flows = data.flows || (Array.isArray(data) ? data : []);
        for (const f of flows) {
          if (f && f.id) m[f.id] = f.name || f.id;
          else if (f && f.flow_id) m[f.flow_id] = f.name || f.flow_id;
        }
        _flowNameMap = m;
        _flowNameMapT = Date.now();
      }
    } catch (e) { /* 静默 · 下轮再试 */ }
  }
  // 已渲染的卡片统一补名字 (覆盖所有 workshop 工具)
  document.querySelectorAll('.tl-step-action').forEach(el => {
    const mm = String(el.textContent || '').match(/(app|flow)-[0-9a-f]{6,}/i);
    if (!mm || !mm[0]) return;
    const n = /^app-/.test(mm[0]) ? appNameOf(mm[0]) : flowNameOf(mm[0]);
    if (n) el.innerHTML = el.innerHTML.split(mm[0]).join('<b>' + escHtml(n) + '</b>');
  });
}

/* 整轮容器：一轮工具调用 = 一个可折叠块（默认展开）· 内含时间线步骤卡 */
function _tlEnsureRound(state) {
  if (state._tl && state._tl.$round && state._tl.$round.isConnected) return state._tl;
  const round = document.createElement('div');
  round.className = 'tl-round';
  const head = document.createElement('div');
  head.className = 'tl-round-head';
  head.innerHTML = '<i class="ri-tools-fill tl-round-ico"></i><span class="tl-round-title">工具时间线</span><span class="tl-round-stats"></span><i class="ri-arrow-up-s-line tl-round-arrow"></i>';
  head.title = '点击折叠 / 展开这一轮的工具记录';
  const body = document.createElement('div');
  body.className = 'tl-round-body';
  head.onclick = () => {
    round.classList.toggle('collapsed');
    const ar = head.querySelector('.tl-round-arrow');
    if (ar) ar.className = round.classList.contains('collapsed') ? 'ri-arrow-down-s-line tl-round-arrow' : 'ri-arrow-up-s-line tl-round-arrow';
  };
  round.appendChild(head);
  round.appendChild(body);
  if (state.$container) state.$container.appendChild(round);
  state._tl = { $round: round, $head: head, $body: body, steps: [], startTs: Date.now() };
  return state._tl;
}

function _tlUpdateHead(state) {
  const tl = state._tl; if (!tl) return;
  const n = tl.steps.length;
  const done = tl.steps.filter(s => s.ok !== null).length;
  const fails = tl.steps.filter(s => s.ok === false).length;
  const el = tl.$head.querySelector('.tl-round-stats');
  if (el) el.textContent = fails ? `${done}/${n} 步 · ${fails} 个失败` : `${done}/${n} 步`;
}

function tlAddStep(state, name, summary, tier) {
  const tl = _tlEnsureRound(state);
  const cat = tlCatOf(name);
  const h = tlHumanize(name, summary, '', 1);
  const card = document.createElement('div');
  card.className = 'tl-step';
  card.dataset.tool = name;   // 供补名字等按工具查卡
  card.innerHTML =
    `<div class="tl-step-dot" style="--tlc:${cat.color}"><i class="${cat.icon}"></i></div>` +
    `<div class="tl-step-main">` +
      `<div class="tl-step-head"><span class="tl-step-cat" style="color:${cat.color}">${cat.name}</span>` +
      `<span class="tl-step-tool">${escHtml(name)}</span>` +
      (tier ? `<span class="tl-step-tier">[${escHtml(tier)}]</span>` : '') +
      `<span class="tl-step-dur"></span></div>` +
      `<div class="tl-step-action" title="点我看技术细节">${h.action}</div>` +
      `<div class="tl-step-result tl-pending"><i class="ri-loader-4-line tl-spin"></i> 进行中…</div>` +
      `<div class="tl-step-tech"><div class="tl-tech-call">${escHtml(String(summary || '(无参数摘要)'))}</div></div>` +
    `</div>`;
  card.querySelector('.tl-step-action').onclick = () => card.classList.toggle('show-tech');
  tl.$body.appendChild(card);
  const rec = { name, summary, $card: card, startTs: Date.now(), ok: null };
  tl.steps.push(rec);
  _tlUpdateHead(state);
  return rec;
}

function tlFillStep(state, name, ok, resultText) {
  const tl = state._tl; if (!tl) return;
  let rec = null;
  for (let i = tl.steps.length - 1; i >= 0; i--) {
    if (tl.steps[i].name === name && tl.steps[i].ok === null) { rec = tl.steps[i]; break; }
  }
  if (!rec) rec = tlAddStep(state, name, '', null);  // 孤儿 result · 补卡
  rec.ok = !!ok;
  const durS = Math.max(0, Math.round((Date.now() - rec.startTs) / 1000));
  const h = tlHumanize(name, rec.summary || '', resultText || '', ok);
  const $r = rec.$card.querySelector('.tl-step-result');
  $r.classList.remove('tl-pending');
  $r.classList.add(ok ? 'tl-ok' : 'tl-fail');
  $r.innerHTML = (ok ? '<i class="ri-check-fill"></i> ' : '<i class="ri-close-fill"></i> ') + escHtml(String(h.result || (ok ? '完成' : '失败')).slice(0, 220));
  const $d = rec.$card.querySelector('.tl-step-dur');
  if ($d && durS > 0) $d.textContent = tlHumanDur(durS);
  const $tech = rec.$card.querySelector('.tl-step-tech');
  if ($tech && resultText) {
    const rd = document.createElement('div');
    rd.className = 'tl-tech-result';
    rd.textContent = String(resultText).slice(0, 300);
    $tech.appendChild(rd);
  }
  _tlUpdateHead(state);
}

function _tlHeadSummary(steps) {
  const edits = steps.filter(s => ['edit_file', 'write_file'].includes(s.name)).length;
  const checks = steps.filter(s => ['python_exec', 'verify_daemon_endpoints', 'lint_check', 'shell_exec'].includes(s.name)).length;
  const fails = steps.filter(s => s.ok === false).length;
  const parts = [];
  if (edits) parts.push(`<b>改了 ${edits} 个文件</b>`);
  if (checks) parts.push(`<b>跑了 ${checks} 次检查/命令</b>`);
  const others = steps.length - edits - checks;
  if (others > 0) parts.push(`<b>处理 ${others} 件事务</b>`);
  return (parts.join('、') || '<b>工具时间线</b>') + (fails ? ` · <span class="tl-fail-text">${fails} 个失败</span>` : '');
}

function tlFinishRound(state) {
  const tl = state._tl; if (!tl) return;
  const n = tl.steps.length;
  if (!n) { tl.$round.remove(); state._tl = null; return; }
  const fails = tl.steps.filter(s => s.ok === false).length;
  const totalS = Math.round((Date.now() - tl.startTs) / 1000);
  const $t = tl.$head.querySelector('.tl-round-title');
  if ($t) $t.innerHTML = _tlHeadSummary(tl.steps);
  const $s = tl.$head.querySelector('.tl-round-stats');
  if ($s) $s.textContent = `${n} 步 · ${tlHumanDur(totalS)}${fails ? ` · ${fails} 失败` : ''}`;
  /* 默认保持展开（用户 拍板"工具默认是不折叠的"）· 用户想收自己点头部 */
  state._tl = null;
}

/* 历史回放用 · 把一个 assistant turn 的 tool_calls + 配对的 results 一次性渲成时间线 */
function _tlArgsSummary(argumentsStr) {
  if (!argumentsStr) return '';
  try {
    const obj = JSON.parse(argumentsStr);
    const keys = Object.keys(obj);
    if (!keys.length) return '';
    const k = keys[0];
    const v = String(obj[k] == null ? '' : obj[k]).slice(0, 60);
    return `${k}=${v}${keys.length > 1 ? ` · ${keys.length - 1}+ args` : ''}`;
  } catch { return String(argumentsStr).slice(0, 60); }
}

function renderToolTimeline(items, target) {
  if (!items || !items.length) return;
  const state = { $container: target || $msgs, _tl: null };
  for (const it of items) {
    tlAddStep(state, it.name, _tlArgsSummary(it.args), null);
    if (it.result != null) {
      const ok = !/^(error:|exit code [1-9]|❌|failed:|未知|fail)/i.test(it.result || '');
      tlFillStep(state, it.name, ok, it.result);
    } else {
      /* 历史里丢了 result 的 · 标个中断 */
      const rec = state._tl.steps[state._tl.steps.length - 1];
      rec.ok = true;
      const $r = rec.$card.querySelector('.tl-step-result');
      $r.classList.remove('tl-pending');
      $r.classList.add('tl-ok');
      $r.innerHTML = '<i class="ri-check-fill"></i> 已完成（历史结果未存档）';
      state._tl && _tlUpdateHead(state);
    }
  }
  /* 历史收尾不显示耗时（turn 级 ts 不可靠）· 只显步数与人话统计 */
  const tl = state._tl;
  if (tl) {
    const n = tl.steps.length;
    const fails = tl.steps.filter(s => s.ok === false).length;
    const $t = tl.$head.querySelector('.tl-round-title');
    if ($t) $t.innerHTML = _tlHeadSummary(tl.steps);
    const $s = tl.$head.querySelector('.tl-round-stats');
    if ($s) $s.textContent = `${n} 步${fails ? ` · ${fails} 失败` : ''}`;
    state._tl = null;
  }
}

// 卷三十六 · 历史回放专用 · 渲染一次 tool_call 气泡 (跟实时 SSE 'tool_call' 事件视觉一致)
function renderHistoryToolCall(name, argumentsStr, target) {
  const div = document.createElement('div');
  div.className = 'msg tool-call';
  div.innerHTML = '⚙ <span class="tool-name"></span> ';
  div.querySelector('.tool-name').textContent = name || '?';
  // arguments 是 JSON 字符串 · 给个简短预览 (不展开)
  let summary = '';
  if (argumentsStr) {
    try {
      const obj = JSON.parse(argumentsStr);
      const keys = Object.keys(obj);
      if (keys.length) {
        const k = keys[0];
        const v = String(obj[k] || '').slice(0, 60);
        summary = `${k}=${v}${keys.length > 1 ? ` · ${keys.length - 1}+ args` : ''}`;
      }
    } catch {}
  }
  const sp = document.createElement('span');
  sp.textContent = summary;
  sp.style.color = 'var(--dim2)';
  sp.style.marginLeft = '4px';
  div.appendChild(sp);
  const dst = target || $msgs;
  if (dst) dst.appendChild(div);
}

function renderHistoryToolResult(content, target) {
  const div = document.createElement('div');
  div.className = 'msg tool-result';
  // 看 content 头部判断 ok / fail · 失败的 ToolResult.to_string() 一般 'error: ...' 开头
  const isErr = /^(error:|exit code [1-9]|❌|failed:|未知|fail)/i.test(content || '');
  if (isErr) div.classList.add('failed');
  const icon = isErr ? '<i class="ri-close-fill"></i>' : '<i class="ri-check-fill"></i>';
  div.innerHTML = icon + ' <span class="tool-name">result</span> ';
  const tail = document.createElement('span');
  const preview = (content || '').replace(/\n/g, ' ').slice(0, 200);
  tail.textContent = '· ' + (preview || '(empty)');
  div.appendChild(tail);
  const dst = target || $msgs;
  if (dst) dst.appendChild(div);
}

// wish-3fef4bc7 · 真并行多对话 UI
// _saveActiveStateToCurrentSession / _loadActiveStateFromCurrentSession
// 切对话时·把当前 visible 的全局 turn 状态 sync 到 _sessions[oldSid]·然后 load 新 sid 的
// 旧对话不被杀·它的 fetch / abort controller / streaming bubbles 都活在 state 里·继续后台跑
function _saveActiveStateToCurrentSession() {
  if (!sessionId) return;
  const s = _getOrCreateSession(sessionId);
  if (!s) return;
  s.pending = pending;
  s.currentTurnId = currentTurnId;
  s.currentAbortController = currentAbortController;
  if ($input) s.inputDraft = $input.value;
  if ($messagesPanel) s.scrollTop = $messagesPanel.scrollTop;
}

function _loadActiveStateFromCurrentSession() {
  if (!sessionId) {
    pending = false;
    currentTurnId = null;
    currentAbortController = null;
    return;
  }
  const s = _sessions[sessionId];
  if (!s) {
    pending = false;
    currentTurnId = null;
    currentAbortController = null;
    return;
  }
  pending = s.pending;
  currentTurnId = s.currentTurnId;
  currentAbortController = s.currentAbortController;
  if ($input) {
    $input.value = s.inputDraft || '';
    // 调高度
    $input.style.height = 'auto';
    if (s.inputDraft) $input.style.height = $input.scrollHeight + 'px';
  }
}

// wish-3fef4bc7 · tab bar 渲染 · ≥2 个有内容的 session 时显示
// 有内容的标准: container 里有 children (用户 至少发过一条 / load 过历史 / 正在跑)
// 空的临时 cid 不计入 (用户 点 + 但还没发消息时不该立刻冒出 tab)
function _renderTabBar() {
  const $bar = document.getElementById('chatTabBar');
  if (!$bar) return;
  $bar.innerHTML = '';
  const sids = Object.keys(_sessions).filter(sid => {
    const s = _sessions[sid];
    if (!s || !s.$container) return false;
    if (s.pending) return true;  // 正在跑的一定显示
    return s.$container.children.length > 0;
  });
  if (sids.length <= 1) {
    $bar.hidden = true;
    return;
  }
  $bar.hidden = false;
  // 排序: pending 优先 · 然后字典序 (临时 cid 按时间戳排在前)
  sids.sort((a, b) => {
    const sa = _sessions[a], sb = _sessions[b];
    if (sa.pending && !sb.pending) return -1;
    if (!sa.pending && sb.pending) return 1;
    return a.localeCompare(b);
  });
  for (const sid of sids) {
    const s = _sessions[sid];
    const tab = document.createElement('div');
    tab.className = 'chat-tab';
    if (sid === sessionId) tab.classList.add('active');
    if (s.pending) tab.classList.add('running');
    if (s.hasUnreadCompletion && sid !== sessionId) tab.classList.add('unread');
    tab.dataset.sid = sid;
    const titleSpan = document.createElement('span');
    titleSpan.className = 'tab-title';
    titleSpan.textContent = sid.startsWith('tmp-') ? '新对话' : aliasFor(sid);
    tab.appendChild(titleSpan);
    // 没名字的真会话 (F5 后恢复 / 后台跑的 spawn / 微信来的) · 拉一次服务端 label
    // 把裸 api-xxxx 换成对话名 · _metaTried 保证只拉一次 (断"拉不到→反复拉"死循环)
    if (!sid.startsWith('tmp-') && !sessionAliases[sid]
        && !(sessionMetaCache[sid] && sessionMetaCache[sid].label)
        && !_metaTried.has(sid)) {
      _metaTried.add(sid);
      _ensureSessionMeta(sid);
    }
    if (s.pending) {
      const spin = document.createElement('span');
      spin.className = 'tab-spinner';
      spin.textContent = '⟳';
      tab.appendChild(spin);
    }
    if (!s.pending) {
      const closeBtn = document.createElement('button');
      closeBtn.className = 'tab-close';
      closeBtn.textContent = '×';
      closeBtn.title = '关闭这个对话面板 (不删历史 · 之后还能从 ☰ 历史里点回来)';
      closeBtn.onclick = (e) => {
        e.stopPropagation();
        _closeTabSession(sid);
      };
      tab.appendChild(closeBtn);
    }
    tab.onclick = () => switchToSession(sid);
    $bar.appendChild(tab);
  }
}

// 关闭一个 tab · 不删 server 历史 · 只清前端 state + DOM container
// 跑着的不让关 (用户 应该先 ⏹ 停 · 再关)
function _closeTabSession(sid) {
  if (!sid) return;
  const s = _sessions[sid];
  if (!s) return;
  if (s.pending) return;
  if (s.$container) s.$container.remove();
  delete _sessions[sid];
  // 关的是 active · 切到另一个有 container 的 session · 没有就 newConversation
  if (sid === sessionId) {
    const remaining = Object.keys(_sessions).filter(k => _sessions[k].$container);
    if (remaining.length > 0) {
      sessionId = '';  // 让 switchToSession 不被 sid===sessionId 短路
      switchToSession(remaining[0]);
    } else {
      newConversation();
    }
  }
  _renderTabBar();
}

// wish-3fef4bc7 follow-up · 浏览器 F5 后 polling auto-refresh
// 浏览器 F5 切断 SSE 连接 · 但 daemon worker 是 sync thread · 不依赖 SSE · 仍在跑+增量落盘
// _maybeStartPoll: load 历史后调 · 查 daemon 端是否有 active turn 关联此 session · 有就启动 polling
// _startSessionPoll: 每 3s reload 历史 (lite 全量) · 直到 active turn 没了
// _stopSessionPoll: 清 setInterval
async function _maybeStartPoll(state) {
  if (!state || !state.sessionId) return;
  if (state.sessionId.startsWith('tmp-')) return;
  if (state.pollIntervalId) return;
  if (state.pending) return;  // 当前正在跑 · SSE 在用 · 不需要 polling
  try {
    const r = await fetch(`/sessions/${encodeURIComponent(state.sessionId)}/active_turn`, {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) return;
    const j = await r.json();
    if (j && j.turn_id) {
      _startSessionPoll(state, j.turn_id);
    }
  } catch {}
}

// 卷五十六 · 2026-06-03 · 重启重连专用 · 带重试探测 active_turn (治本"重启后假死/输入没锁")。
// 病根: 续写 turn 可能比 daemon "alive" 晚几百 ms 才注册 active_turn · 旧的单次探测(_maybeStartPoll)
// 一查没有就放弃 + 解锁 · 之后 turn 才起来 · 前端却定格 idle 不再查 → 卡假死直到手动刷新。
// 这里在 windowMs 窗口内每 1s 重试一次 · 期间始终保持输入锁定(用户 要求: 重启后默认不让发消息 · 先证明
// 任务在跑)。 一旦发现 active turn 就 _startSessionPoll(锁定 + 起 3s 轮询)·返 true; 窗口内始终没有 → 返 false
// (调用方据此才解锁)。 跟 _maybeStartPoll(稳态切对话用·单次)分开 · 不污染普通切换。
async function _probeAndStartPoll(state, windowMs = 8000) {
  if (!state || !state.sessionId || state.sessionId.startsWith('tmp-')) return false;
  if (state.pollIntervalId) return true;  // 已经在轮询了
  if (sessionId === state.sessionId) {
    setInputLocked(true);
    showToolProgress(true);
    setToolProgressText('Daemonkey 重启完成 · 正在确认续写任务…');
  }
  const deadline = Date.now() + windowMs;
  let first = true;
  while (Date.now() < deadline) {
    if (!first) await new Promise(r => setTimeout(r, 1000));
    first = false;
    try {
      const r = await fetch(`/sessions/${encodeURIComponent(state.sessionId)}/active_turn`, {
        headers: { 'Authorization': 'Bearer ' + token },
      });
      if (r.ok) {
        const j = await r.json();
        if (j && j.turn_id) {
          _startSessionPoll(state, j.turn_id);
          return true;
        }
      }
    } catch {}
  }
  return false;
}

// wish-3fef4bc7 follow-up · 启动 polling 时同步把 daemon 端那个 turn"接管"过来:
// state.pending=true + state.currentTurnId=turnId · 让 ⏹ 按钮能 POST /turns/{tid}/abort 杀 daemon 端 turn
// active session 时同步全局 UI (send 按钮变 ⏹ · 输入框锁住)
function _startSessionPoll(state, turnId) {
  if (!state || state.pollIntervalId) return;
  state.currentTurnId = turnId || null;
  state.pending = true;
  state.currentAbortController = null;  // polling 没 fetch · triggerStop 走 daemon abort
  // 同步 visible UI · 让 用户 看到 ⏹ + lock
  if (sessionId === state.sessionId) {
    pending = true;
    currentTurnId = turnId || null;
    currentAbortController = null;
    setSendButtonState('pending');
    setInputLocked(true);
    showToolProgress(true);
    setToolProgressText('Daemonkey 后台仍在跑这个对话 · 自动刷新中…');
  }
  addSys('⏳ Daemonkey 仍在后台跑这个对话 · 自动刷新中 (3s/次) · 点 ⏹ 可中断', state.$container);
  state.lastTurnCount = state.$container
    ? state.$container.querySelectorAll('.msg').length
    : 0;
  state.pollIntervalId = setInterval(() => _pollSession(state), 3000);
  if (typeof _renderTabBar === 'function') {
    try { _renderTabBar(); } catch {}
  }
}

function _stopSessionPoll(state) {
  if (!state) return;
  const wasPending = state.pending;
  const isVisible = sessionId === state.sessionId;
  if (state.pollIntervalId) {
    clearInterval(state.pollIntervalId);
    state.pollIntervalId = null;
  }
  // wish-3fef4bc7 follow-up · 还原 state + visible UI 到 idle
  state.pending = false;
  state.currentTurnId = null;
  state.currentAbortController = null;
  if (isVisible) {
    pending = false;
    currentTurnId = null;
    currentAbortController = null;
    setSendButtonState('idle');
    setInputLocked(false);
    showToolProgress(false);
    refreshPlan();   // 后台 polling 跑完同样刷一次
    if (wasPending) { try { _maybeTabFlash('✅ Daemonkey 干完了'); } catch {} }
  } else if (wasPending) {
    // 后台 polling 完成 + 用户 不在看 · 弹 toast + tab 红点 (跟 send finally 后台完成对齐)
    state.hasUnreadCompletion = true;
    if (typeof _showCompletionToast === 'function') {
      try { _showCompletionToast(state); } catch {} }
    try { _maybeTabFlash('✅ Daemonkey 干完了'); } catch {}
  }
  if (typeof _renderTabBar === 'function') {
    try { _renderTabBar(); } catch {}
  }
}

async function _pollSession(state) {
  if (!state || !state.sessionId || state.sessionId.startsWith('tmp-')) {
    _stopSessionPoll(state);
    return;
  }
  // 1) 查 daemon 还有这个 session 的 active turn 没
  let hasActive = false;
  let activeTurnId = null;
  let progress = null;
  try {
    const r = await fetch(`/sessions/${encodeURIComponent(state.sessionId)}/active_turn`, {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (r.ok) {
      const j = await r.json();
      hasActive = !!(j && j.turn_id);
      activeTurnId = (j && j.turn_id) || null;
      progress = (j && j.progress) || null;
    }
  } catch {}
  // turn_id 可能在 polling 期间变了 (旧的被 stop · 新的开起来 — 极小概率) · 同步一下
  if (activeTurnId && state.currentTurnId !== activeTurnId) {
    state.currentTurnId = activeTurnId;
    if (sessionId === state.sessionId) currentTurnId = activeTurnId;
  }
  // ② 自主巡航进度 (卷七十五续四) · 后台 turn 没 SSE · 把 daemon 记的最新一步写进进度条 ·
  // 不再干巴巴"仍在后台跑" · 而是"正在: xxx · 第N轮 · 已Xs" · 长任务也看得出没卡死
  if (hasActive && sessionId === state.sessionId) {
    _startBgProgressTicker(state.sessionId, progress); // 本地 1s 读秒·每 3s poll 校准
  }
  // 2) 拉历史 · 看 turn count 变了没
  try {
    const r = await fetch(`/sessions/${encodeURIComponent(state.sessionId)}/messages`, {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) return;
    const data = await r.json();
    const newCount = data.count || 0;
    if (newCount > (state.lastTurnCount || 0) || (!hasActive && state.pollIntervalId)) {
      // 有新 turn · 或 active turn 刚结束 · 重画 container
      state.$container.innerHTML = '';
      // wish · 同 _loadSessionHistory · 长会话只回放最近 N 个 turn · 更早折叠成"加载全部"入口
      let _pturns = data.turns || [];
      let _phidden = 0;
      if (isFinite(HISTORY_RENDER_WINDOW) && _pturns.length > HISTORY_RENDER_WINDOW) {
        _phidden = _pturns.length - HISTORY_RENDER_WINDOW;
        _pturns = _pturns.slice(-HISTORY_RENDER_WINDOW);
      }
      if (_phidden > 0) _ensureLoadEarlierSentinel(state.$container);
      for (let _ti = 0; _ti < _pturns.length; _ti++) {
        const t = _pturns[_ti];
        if (t.role === 'user') {
          // wish-7c579a20 · 带附件消息: 剥皮 + 重建图片/文档(同 _loadSessionHistory)
          let _pc = t.content || '';
          const _pAttS = _用户AttachStrip(_pc);
          if (_pAttS.legacy.length || (t.attachments && t.attachments.length)) _pc = _pAttS.body || _pc;
          const _p用户B = addMsg('用户', _pc, null, t.ts, state.$container);
          _render用户Attachments(_p用户B,
            (t.attachments && t.attachments.length)
              ? t.attachments
              : _pAttS.legacy.map(function(b) { return { name: b, path: 'data/runtime/attachments/' + b }; }));
        } else if (t.role === 'assistant') {
          if (t.reasoning_content) {
            renderReasoningBubble(t.reasoning_content, { collapsed: true, historical: true }, state.$container);
          }
          if (t.content && t.content.trim()) {
            addMsg('Daemonkey', t.content, null, t.ts, state.$container);
          }
          if (t.tool_calls && t.tool_calls.length) {
            const _results = [];
            let _tj = _ti + 1;
            while (_tj < _pturns.length && _pturns[_tj].role === 'tool') { _results.push(_pturns[_tj].content); _tj++; }
            renderToolTimeline(t.tool_calls.map((tc, k) => ({ name: tc.name, args: tc.arguments, result: k < _results.length ? _results[k] : null })), state.$container);
            _ti = _tj - 1;  // 跳过已配对的 tool turns
          }
        } else if (t.role === 'tool') {
          renderHistoryToolResult(t.content, state.$container);  // 孤儿 tool turn · 保持老样式
        }
      }
      state.lastTurnCount = newCount;
      const tail = hasActive
        ? `⏳ ${_fmtBgProgress(progress)}`
        : `(已加载 ${newCount} 条历史 turn · Daemonkey 这轮跑完了 · 输入新消息可继续)`;
      addSys(tail, state.$container);
    }
  } catch {}
  // 3) 没 active turn 了 · 停 polling (这是收尾 · _pollSession 不再触发)
  // 2026-08-11 修 (wish-bec4f3b9 续): 后台 turn 完成瞬间 · /messages 可能还没包含
  // 刚落盘的最终结果 (落盘延迟) → 上面那次重画可能"画了个寂寞" → 立即停轮询后
  // 结果才落盘 · 前端没被告知 → 用户 只能 F5 才看到。
  // → 延迟 800ms 做一次"最终确认加载" (期间没被新 turn 接管才执行) · 拉到新结果
  //   再停 · 让"后台 turn 完成"也变成前端自动刷新触发点 (不只切前台/刷新/本实例重启)。
  if (!hasActive) {
    _stopBgProgressTicker();
    const _sid = state.sessionId;
    const _pollId = state.pollIntervalId;
    setTimeout(async () => {
      // 期间轮询已被 stop/重启 (用户手动停 / 新 turn 接管) → 不越权加载
      if (!state || state.pollIntervalId !== _pollId) return;
      // 再查一次 active_turn · 若已有新 turn 跑起来 → 交给它的轮询自己处理
      let _stillIdle = true;
      try {
        const rr = await fetch(`/sessions/${encodeURIComponent(_sid)}/active_turn`, {
          headers: { 'Authorization': 'Bearer ' + token },
        });
        if (rr.ok) { const jj = await rr.json(); if (jj && jj.turn_id) _stillIdle = false; }
      } catch {}
      if (!_stillIdle) return;
      try { await _loadSessionHistory(_sid); } catch (e) {}
      _stopSessionPoll(state);
    }, 800);
  }
}

// 后台 session 跑完时的 toast 提示 · 4s 自动消 · 点击切回该 session
function _showCompletionToast(state) {
  if (!state) return;
  const sid = state.sessionId;
  const title = (sid && !sid.startsWith('tmp-')) ? aliasFor(sid) : '新对话';
  const $host = document.getElementById('chatToastHost');
  if (!$host) return;
  const t = document.createElement('div');
  t.className = 'chat-toast';
  const dot = document.createElement('span');
  dot.className = 'toast-dot';
  const titleEl = document.createElement('span');
  titleEl.className = 'toast-title';
  titleEl.textContent = title;
  const msg = document.createElement('span');
  msg.className = 'toast-msg';
  // 如果有 finish reason · 加点信息
  const reason = state.lastFinishReason;
  if (reason === 'length') {
    msg.textContent = '输出截断 · 切回看';
  } else if (state.errorShown) {
    msg.textContent = '出错了 · 切回看';
  } else {
    msg.textContent = '完成 · 切回看回复';
  }
  t.appendChild(dot);
  t.appendChild(titleEl);
  t.appendChild(msg);
  t.onclick = () => {
    switchToSession(sid);
    t.remove();
  };
  $host.appendChild(t);
  setTimeout(() => {
    t.classList.add('toast-fade');
    setTimeout(() => t.remove(), 400);
  }, 4500);
}

// 卷六十 · 主动 CALL 收件箱心跳 · 检测 Daemonkey 主动开口 → toast + 自动加载 · 不用手刷
async function _checkProactiveInbox() {
  if (!token) return;
  try {
    const r = await fetch('/api/proactive/inbox?since=' + encodeURIComponent(_proactiveLastSeen), {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) return;
    const data = await r.json();
    const items = (data && data.items) || [];
    if (!items.length) return;
    for (const it of items) {
      if (it.ts && it.ts > _proactiveLastSeen) _proactiveLastSeen = it.ts;
      _showProactiveToast(it);
      if (it.session_id && it.session_id === sessionId) {
        // 正开着这个 session → 直接重载历史 · Daemonkey 那句话立刻冒出来
        try { _loadSessionHistory(sessionId); } catch (e) {}
      } else if (it.session_id) {
        const st = _sessions[it.session_id];
        if (st) st.hasUnreadCompletion = true;
      }
    }
    if (typeof _refreshSessionLists === 'function') { try { _refreshSessionLists(); } catch (e) {} }  // 工作台 + 专注版一起刷
  } catch (e) { /* 静默 · 收件箱失败不影响主功能 */ }
}

// 卷七十四续十七 · 微信入站对话 WebUI 自动感知 · 复用后台轮询那套(零新逻辑)
// 微信对话固定进 api-wechat 会话 · daemon 后台 turn(_run_bg_turn)已注册 active_turn ·
// 但前端只在"切进会话那一刻"单次探测(_maybeStartPoll) · 之后用户在手机发消息 ·
// 前端没人再探 → WebUI 聋到手刷。这里加一个持续探测 · 探到就调现成的 _startSessionPoll
// (3s 轮询 reload + 跑完弹 toast + tab 红点 · 跟 WebUI 自己的并行对话同一套机制)。
async function _checkWechatActivity() {
  if (!token) return;
  const WX_SID = 'api-wechat';
  try {
    let st = _sessions[WX_SID];
    if (st && (st.pollIntervalId || st.pending)) return;  // 已在轮询/正跑 · 别重复触发
    const r = await fetch(`/sessions/${WX_SID}/active_turn`, {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) return;
    const j = await r.json();
    if (!j || !j.turn_id) return;
    // 有后台 turn 在跑 → 确保 container 存在(没打开时建隐藏的 · 不抢占当前显示) · 纳入轮询
    _getOrCreateContainer(WX_SID);
    st = _getOrCreateSession(WX_SID);
    if (st && !st.pollIntervalId) _startSessionPoll(st, j.turn_id);
  } catch {}
}

// 卷七十四续二十 · 顶部品牌区显示内核版本号 · 纯靠 chat.js 动态挂标签(不依赖 chat.html ·
// 因为 chat.html 是皮肤层不随内核同步 · chat.js 在白名单 · 这样升级内核版本号显示就会跟着更新)。
// 版本号唯一真相源 = core_manifest.json 的 core_version · 后端 /api/core/version 出口(无鉴权)。
async function _showCoreVersion() {
  try {
    const logo = document.querySelector('.header-logo');
    if (!logo) return;
    const r = await fetch('/api/core/version');
    if (!r.ok) return;
    const j = await r.json();
    const v = ((j && j.core_version) || '').trim();
    if (!v) return;
    let tag = document.getElementById('coreVersionTag');
    if (!tag) {
      tag = document.createElement('span');
      tag.id = 'coreVersionTag';
      tag.style.cssText = 'margin-left:8px;font-size:0.62rem;font-weight:600;opacity:0.55;letter-spacing:0.3px;vertical-align:middle;';
      logo.appendChild(tag);
    }
    tag.textContent = 'v' + v;
    tag.title = '内核版本 v' + v + ' · 想看有没有新版 → 对我说「看看内核有没有更新」';
  } catch {}
}

// 卷六十 · Daemonkey 主动找你的 toast · 点击切到那个 session · 比普通完成 toast 多停一会
function _showProactiveToast(it) {
  try { _maybeTabFlash('🌙 Daemonkey 找你'); } catch {}
  const $host = document.getElementById('chatToastHost');
  if (!$host) return;
  const sid = it.session_id || '';
  const t = document.createElement('div');
  t.className = 'chat-toast proactive';
  const dot = document.createElement('span');
  dot.className = 'toast-dot';
  dot.textContent = '\ud83c\udf19';
  const titleEl = document.createElement('span');
  titleEl.className = 'toast-title';
  titleEl.textContent = 'Daemonkey 主动找你了';
  const msg = document.createElement('span');
  msg.className = 'toast-msg';
  msg.textContent = it.reason ? ('· ' + it.reason) : '· 切过去看看';
  t.appendChild(dot);
  t.appendChild(titleEl);
  t.appendChild(msg);
  t.onclick = () => { if (sid) switchToSession(sid); t.remove(); };
  $host.appendChild(t);
  setTimeout(() => {
    t.classList.add('toast-fade');
    setTimeout(() => t.remove(), 400);
  }, 8000);
}

function newConversation() {
  clearAttachments();
  if (_docsViewActive) closeDocsView();  // 卷八十一 · 新建会话自动关文档视图
  // wish-3fef4bc7 · 真并行 · 不杀旧对话 · 先 save 当前 state · 再切到新 cid
  _saveActiveStateToCurrentSession();
  // 给新对话临时 cid · 立刻切 active container 到它 (空 container)
  const cid = _allocCid();
  const s = _getOrCreateSession(cid);
  s.title = '新对话';
  _setActiveContainer(cid);
  sessionId = cid;
  // 临时 cid 不存 localStorage · hello 来 swap 真 sid 后 commitSessionId 会存
  localStorage.removeItem(STORAGE.session);
  updateCurrentLabel();
  // load state · 新 session 是 idle·全局 UI 也归零
  _loadActiveStateFromCurrentSession();
  setSendButtonState('idle');
  setInputLocked(false);
  showToolProgress(false);
  addSys('新对话开始 · 发第一条消息会自动建 session');
  closeDrawer();
  if (typeof _renderTabBar === 'function') {
    try { _renderTabBar(); } catch {}
  }
  _refreshCompactAfterSwitch();  // 卷八十三 · 新建会话后简洁版侧栏归零
  refreshPlan();                 // 新会话没活跃账本 → 计划条自动隐藏
}

function formatTime(ts) {
  try {
    const d = ts ? (ts instanceof Date ? ts : new Date(ts)) : new Date();
    if (isNaN(d.getTime())) return '';
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
  } catch { return ''; }
}

// ──────────────────────────────────────────────────────────────
// 卷三十 · 简易 markdown 渲染器（chat 右栏用 · Daemonkey 输出 ### / **/ - / 1. / ``` 等都正确渲染）
// 不引外部 lib · 100 行自给自足 · 永远工作（trycloudflare 偶尔抽风也无所谓）
//
// 支持：
//   - # / ## / ### / #### / ##### / ###### headers
//   - **bold** *italic*  __bold__ _italic_
//   - `inline code`  + ```block code```
//   - --- 横线
//   - - / * / + 无序列表  · 1. 2. 3. 有序列表
//   - [text](url) 链接
//   - > 引用
//   - 段落 + 换行
//
// 安全：所有用户/LLM 内容先 escapeHtml · 再做 markdown 转换 · 防 XSS
// ──────────────────────────────────────────────────────────────
function mdRender(text, opts) {
  if (text == null) return '';
  if (typeof text !== 'string') text = String(text);

  // 卷六十四续十一 · 流式期间媒体占位 · 防 <video>/<audio>/<img> 每帧 innerHTML 重建被反复
  // 销毁+重载导致闪烁。streaming=true 时所有媒体先渲成轻量占位 chip · finalize 时(不传 opts)
  // 才出真播放器·整段只建一次·最终结果跟以前完全一致。
  const _streaming = opts === true || (opts && opts.streaming === true);
  function _mediaPending(kind, url) {
    const icon = kind === 'video' ? '<i class="ri-film-line"></i>'
      : (kind === 'audio' ? '<i class="ri-music-2-line"></i>' : '<i class="ri-image-line"></i>');
    const label = kind === 'video' ? '视频' : (kind === 'audio' ? '音频' : '图片');
    let name = String(url || '').split(/[?#]/)[0].split(/[\\/]/).pop() || '';
    name = name.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    return `<span class="md-media-pending">${icon} ${label}${name ? ' · ' + name : ''}</span>`;
  }

  // 提取 ``` block code · 先占位 · 避免后面 inline 转换破坏
  const codeBlocks = [];
  text = text.replace(/```([a-zA-Z0-9_+-]*)\n?([\s\S]*?)```/g, (m, lang, code) => {
    const idx = codeBlocks.length;
    codeBlocks.push({ lang: (lang || '').trim(), code });
    return `\x00CODEBLOCK${idx}\x00`;
  });

  // 提取 `inline code`
  const inlineCodes = [];
  text = text.replace(/`([^`\n]+)`/g, (m, c) => {
    const idx = inlineCodes.length;
    inlineCodes.push(c);
    return `\x00INLINE${idx}\x00`;
  });

  // 卷六十四续九 · LLM 有时直接写原始 <video>/<audio> HTML 标签 (不走 markdown)。
  // 转义前抽出来·只保留 src + controls·渲染成干净播放器 (丢 width/style 等属性防 XSS)·
  // 占位符避开后面的实体转义。_safeUrl 是函数声明·已 hoist·这里可用。
  const mediaTags = [];
  function _pushMedia(html) {
    const idx = mediaTags.length;
    mediaTags.push(html);
    return `\x00MEDIA${idx}\x00`;
  }
  text = text.replace(/<video\b[^>]*?\bsrc\s*=\s*["']([^"'<>]+)["'][^>]*?>(?:\s*<\/video\s*>)?/gi, (m, src) => {
    const u = _safeUrl(src);
    if (u === '#') return m;
    return _pushMedia(_streaming ? _mediaPending('video', u) : `<video controls preload="metadata" src="${u}" class="md-video"></video>`);
  });
  text = text.replace(/<audio\b[^>]*?\bsrc\s*=\s*["']([^"'<>]+)["'][^>]*?>(?:\s*<\/audio\s*>)?/gi, (m, src) => {
    const u = _safeUrl(src);
    if (u === '#') return m;
    return _pushMedia(_streaming ? _mediaPending('audio', u) : `<audio controls preload="metadata" src="${u}" class="md-audio"></audio>`);
  });
  text = text.replace(/<img\b[^>]*?\bsrc\s*=\s*["']([^"'<>]+)["'][^>]*?>/gi, (m, src) => {
    const u = _safeUrl(src);
    if (u === '#') return m;
    return _pushMedia(_streaming ? _mediaPending('img', u) : `<img src="${u}" alt="" loading="lazy" class="md-img" data-full="${u}">`);
  });

  // 转 HTML 实体
  text = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

  // 卷四十四 K stage 2c++ · wish-f3b4958e · URL scheme 安全闸
  // 阻断 javascript: / data: / vbscript: / file: 这些可执行脚本协议
  // 允许: 协议相对(//)·绝对路径(/)·http(s)·相对路径(./.. word)
  function _safeUrl(u) {
    if (!u) return '#';
    const s = String(u).trim();
    if (/^(javascript|data|vbscript|file):/i.test(s)) return '#';
    return s.replace(/"/g, '%22');
  }

  // 卷四十四 K stage 2c++ · 图片 / 音频 / 视频 · ![alt](url) 必须先于 [text](url) 处理
  // 按后缀分流: 图 → <img>·.wav/.mp3 → <audio>·.mp4/.webm → <video>·其他 → 链接
  text = text.replace(
    /!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)/g,
    (m, alt, url, title) => {
      const safeUrl = _safeUrl(url);
      const safeAlt = String(alt || '').replace(/"/g, '&quot;');
      const t = title ? ` title="${String(title).replace(/"/g, '&quot;')}"` : '';
      const lower = safeUrl.toLowerCase();
      if (/\.(wav|mp3|ogg|flac|m4a|aac)(\?|$)/.test(lower)) {
        return _streaming ? _mediaPending('audio', safeUrl) : `<audio controls preload="metadata" src="${safeUrl}"${t} class="md-audio"></audio>`;
      }
      if (/\.(mp4|webm|mov)(\?|$)/.test(lower)) {
        return _streaming ? _mediaPending('video', safeUrl) : `<video controls preload="metadata" src="${safeUrl}"${t} class="md-video"></video>`;
      }
      // 图: 点击弹 lightbox 看大图 (卷四十六补丁 wish-3afebd2c · 不再开新 tab)
      // data-full 留给 lightbox handler · 右键"在新标签打开图片"浏览器原生仍可
      return _streaming ? _mediaPending('img', safeUrl) : `<img src="${safeUrl}" alt="${safeAlt}"${t} loading="lazy" class="md-img" data-full="${safeUrl}">`;
    }
  );

  // 链接 [text](url)
  text = text.replace(
    /\[([^\]]+)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)/g,
    (m, label, url, title) => {
      const safeUrl = _safeUrl(url);
      const t = title ? ` title="${String(title).replace(/"/g, '&quot;')}"` : '';
      return `<a href="${safeUrl}" target="_blank" rel="noopener"${t}>${label}</a>`;
    }
  );

  // 卷六十四续九 · 裸 URL 自动识别 (markdown []/![] 都没用·LLM 直接甩链接的情况)。
  // 视频/音频/图 → 内联播放器/图 (聊天窗口里直接看);其他 → 可点链接 (新标签打开)。
  // 守卫: 前导是行首/空白/( · 避开上面刚生成的 <a href="..."> / <video src="..."> 里的 URL
  // (那些 URL 前是 ")·这里不会误吞)。已 placeholder 的 code/media 不含裸 URL·天然安全。
  function _mediaOrLink(url) {
    const safeUrl = _safeUrl(url);
    const lower = url.toLowerCase();
    if (/\.(mp4|webm|mov)(\?|$)/.test(lower)) {
      return _streaming ? _mediaPending('video', safeUrl) : `<video controls preload="metadata" src="${safeUrl}" class="md-video"></video>`;
    }
    if (/\.(wav|mp3|ogg|flac|m4a|aac)(\?|$)/.test(lower)) {
      return _streaming ? _mediaPending('audio', safeUrl) : `<audio controls preload="metadata" src="${safeUrl}" class="md-audio"></audio>`;
    }
    if (/\.(png|jpe?g|gif|webp|bmp|svg)(\?|$)/.test(lower)) {
      return _streaming ? _mediaPending('img', safeUrl) : `<img src="${safeUrl}" alt="" loading="lazy" class="md-img" data-full="${safeUrl}">`;
    }
    // 卷八十一 · C 方案 · 文档卡片 (docx/md/pdf/xlsx/pptx/txt/zip) · 内嵌 预览/应用打开 按钮
    const docM = lower.match(/\.(docx?|md|pdf|xlsx?|pptx?|txt|zip)(\?|$)/);
    if (docM) {
      const ext = docM[1];
      const name = _safeDecode(url.split('?')[0].split('/').pop() || '文档');
      const dm = url.match(/^\/(?:workshop\/(?:preview|file|outputs)\/|reports\/)?([^/]+)\/([^/?]+)/);
      const domain = dm ? dm[1] : '';
      const filename = dm ? dm[2] : '';
      const isPreviewable = ['md','txt','png','jpg','jpeg','gif','webp','mp3','wav','mp4','webm','pdf'].includes(ext);
      const btn = (ic, label, fn) => `<button class="mdc-btn" onclick="event.stopPropagation();${fn}('${domain}','${filename}','${ext}')" title="${label}"><i class="${ic}"></i>${label}</button>`;
      return `<div class="md-doc-card" data-ext="${ext}" data-url="${safeUrl}" data-domain="${domain}" data-filename="${filename}">
        <span class="mdc-ic">${_docIcon(ext)}</span>
        <span class="mdc-body">
          <span class="mdc-name">${escHtml(name)}</span>
          <span class="mdc-meta">${ext.toUpperCase()}</span>
          <span class="mdc-actions">
            ${isPreviewable ? btn('ri-eye-line','预览','_docOpenInBrowser') : ''}
            ${btn('ri-mac-line','应用打开','_docOpenLocal')}
            ${btn('ri-save-3-line','另存为','_docSaveAs')}
          </span>
        </span>
      </div>`;
    }
    return `<a href="${safeUrl}" target="_blank" rel="noopener">${url}</a>`;
  }
  // (a) 完整 http(s) URL
  text = text.replace(/(^|[\s(])(https?:\/\/[^\s<>"']+)/g, (m, pre, url) => {
    let tail = '';
    const tm = url.match(/[)\].,;!?·，。；！？、"']+$/);
    if (tm) { tail = tm[0]; url = url.slice(0, -tail.length); }
    return pre + _pushMedia(_mediaOrLink(url)) + tail;
  });
  // (b) 根相对的【媒体】路径 (如 /workshop/outputs/x.mp4)·只认带媒体后缀的·防误吞普通 /路径
  text = text.replace(
    /(^|[\s(])(\/[^\s<>"']+\.(?:mp4|webm|mov|wav|mp3|ogg|flac|m4a|aac|png|jpe?g|gif|webp|bmp)(?:\?[^\s<>"']*)?)/gi,
    (m, pre, url) => pre + _pushMedia(_mediaOrLink(url))
  );

  // bold (优先于 italic) · **x** 和 __x__
  text = text.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
  text = text.replace(/__([^_\n]+)__/g, '<strong>$1</strong>');

  // italic · *x* 和 _x_ · 但不要碰已经 <strong>
  // 卷四十六补丁 (wish-3afebd2c) · `_` 必须 word boundary (CommonMark / GFM 标准)
  // 防 url path 里 `_` 被当 italic 起始 · 例如 Yoimiya_d2f7caf194/01.jpg + target="_blank"
  // 会被旧 regex 配对成 italic · 把 href 和 target 一起 wrap 进 <em> · 点开 404
  text = text.replace(/(^|[^*])\*([^*\n]+)\*([^*]|$)/g, '$1<em>$2</em>$3');
  text = text.replace(/(^|[^a-zA-Z0-9_])_([^_\n]+)_(?=$|[^a-zA-Z0-9_])/g, '$1<em>$2</em>');

  // 按行处理 block 元素：headers / hr / lists / blockquote / table / 段落
  const lines = text.split('\n');
  const out = [];
  let listType = null; // 'ul' | 'ol' | null
  let listBuf = [];
  let inBlockquote = false;
  let bqBuf = [];
  let para = [];

  function flushPara() {
    if (para.length) {
      out.push(`<p>${para.join('<br>')}</p>`);
      para = [];
    }
  }
  function flushList() {
    if (listType && listBuf.length) {
      out.push(`<${listType}>${listBuf.map(li => `<li>${li}</li>`).join('')}</${listType}>`);
    }
    listType = null;
    listBuf = [];
  }
  function flushBq() {
    if (inBlockquote && bqBuf.length) {
      out.push(`<blockquote>${bqBuf.join('<br>')}</blockquote>`);
    }
    inBlockquote = false;
    bqBuf = [];
  }

  // 卷三十 · markdown 表格支持
  // 把一行 "| a | b |" 切成 ['a', 'b']
  function parseTableRow(line) {
    let s = line.trim();
    if (s.startsWith('|')) s = s.slice(1);
    if (s.endsWith('|')) s = s.slice(0, -1);
    return s.split('|').map(c => c.trim());
  }
  // 分隔符行 "|---|:---:|---:|" → [null, 'center', 'right']
  function parseAlignRow(line) {
    return parseTableRow(line).map(c => {
      const t = c.trim();
      if (/^:-+:$/.test(t)) return 'center';
      if (/^:-+$/.test(t)) return 'left';
      if (/^-+:$/.test(t)) return 'right';
      return null;
    });
  }
  // 判断这行长得像分隔符行 |---| / |:---:| / |---:|
  function isAlignRow(line) {
    const s = line.trim();
    if (!s.includes('-')) return false;
    if (!s.includes('|')) return false;
    return /^\|?[\s:|-]+\|?$/.test(s) && /-{3,}|-+/.test(s);
  }
  function renderTable(head, align, body) {
    const th = head.map((h, i) => {
      const a = align[i] ? ` style="text-align:${align[i]}"` : '';
      return `<th${a}>${h}</th>`;
    }).join('');
    const tr = body.map(row => {
      const tds = row.map((c, i) => {
        const a = align[i] ? ` style="text-align:${align[i]}"` : '';
        return `<td${a}>${c == null ? '' : c}</td>`;
      }).join('');
      return `<tr>${tds}</tr>`;
    }).join('');
    return `<div class="md-table-wrap"><table class="md-table"><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>`;
  }

  for (let lineI = 0; lineI < lines.length; lineI++) {
    const rawLine = lines[lineI];
    const line = rawLine.trimEnd();

    // 空行 → 段落分隔
    if (!line.trim()) {
      flushPara(); flushList(); flushBq();
      continue;
    }

    // 表格检测（current 行 | 列 |·下一行是分隔符）
    if (line.includes('|') && lineI + 1 < lines.length && isAlignRow(lines[lineI + 1])) {
      flushPara(); flushList(); flushBq();
      const headCells = parseTableRow(line);
      const align = parseAlignRow(lines[lineI + 1]);
      // 对齐数组长度补齐到表头列数
      while (align.length < headCells.length) align.push(null);
      const bodyRows = [];
      let j = lineI + 2;
      while (j < lines.length) {
        const r = lines[j];
        if (!r.trim() || !r.includes('|')) break;
        // 防御：分隔符行不该出现在 body · 出现也跳过
        if (isAlignRow(r)) { j++; continue; }
        const cells = parseTableRow(r);
        // 列数对齐到表头
        while (cells.length < headCells.length) cells.push('');
        if (cells.length > headCells.length) cells.length = headCells.length;
        bodyRows.push(cells);
        j++;
      }
      out.push(renderTable(headCells, align, bodyRows));
      lineI = j - 1;
      continue;
    }

    // 横线
    if (/^---+$/.test(line) || /^\*\*\*+$/.test(line)) {
      flushPara(); flushList(); flushBq();
      out.push('<hr>');
      continue;
    }
    // headers
    const h = /^(#{1,6})\s+(.+)$/.exec(line);
    if (h) {
      flushPara(); flushList(); flushBq();
      out.push(`<h${h[1].length}>${h[2]}</h${h[1].length}>`);
      continue;
    }
    // 无序列表
    const ul = /^[\-*+]\s+(.+)$/.exec(line);
    if (ul) {
      flushPara(); flushBq();
      if (listType !== 'ul') { flushList(); listType = 'ul'; }
      listBuf.push(ul[1]);
      continue;
    }
    // 有序列表
    const ol = /^(\d+)\.\s+(.+)$/.exec(line);
    if (ol) {
      flushPara(); flushBq();
      if (listType !== 'ol') { flushList(); listType = 'ol'; }
      listBuf.push(ol[2]);
      continue;
    }
    // 引用
    const bq = /^>\s?(.*)$/.exec(line);
    if (bq) {
      flushPara(); flushList();
      inBlockquote = true;
      bqBuf.push(bq[1]);
      continue;
    }
    // 普通段落行
    flushList(); flushBq();
    para.push(line);
  }
  flushPara(); flushList(); flushBq();

  let html = out.join('');

  // 还原 inline code
  html = html.replace(/\x00INLINE(\d+)\x00/g, (m, i) => {
    const code = inlineCodes[+i];
    return `<code>${code
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')}</code>`;
  });

  // 还原 block code
  html = html.replace(/\x00CODEBLOCK(\d+)\x00/g, (m, i) => {
    const { lang, code } = codeBlocks[+i];
    const escaped = code
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
    const cls = lang ? ` class="lang-${lang}"` : '';
    return `<pre><code${cls}>${escaped}</code></pre>`;
  });

  // 卷六十四续九 · 还原媒体占位符 (原始 <video>/<audio> 标签 + 裸 URL 自动链接的产物)
  html = html.replace(/\x00MEDIA(\d+)\x00/g, (m, i) => mediaTags[+i] || '');

  return html;
}
// 卷四十六续 11 补丁 · 暴露给 workshop.js 等其他 module 复用 (e.g. Daemonkey app 系统提示词渲染)
try { window.DaemonkeyMdRender = mdRender; } catch (e) { /* 顶层环境异常 · 跳过 */ }

// wish-3fef4bc7 · helpers 接受可选 target container · 不传 = 操作 active session ($msgs)
// 这样 78 处现存调用不动 · send 内的调用传 state.$container 即可路由到正确 session
// 卷四十六续 3 · opts.forceScroll · 默认软滚 (用户 拖滚动条看历史时 LLM 输出不强行刷回底)
//   用户发消息 / 错误 / 必须看到的卡片 → 调方显式传 { forceScroll: true }
function addMsg(role, text, className, ts, target, opts) {
  const div = document.createElement('div');
  div.className = 'msg ' + (className || role);
  const cls = className || role;
  // 卷三十：Daemonkey 输出走 markdown 渲染（用户 输入 / sys / err / 工具卡保持原样）
  const useMd = cls.includes('Daemonkey') && !cls.includes('thinking');
  if (useMd) {
    const body = document.createElement('div');
    body.className = 'md-body';
    body.innerHTML = mdRender(text);
    // 扫描自定义主题代码块 (wish-7b89146f)
    setTimeout(function() { scanThemeBlocks(div); }, 50);
    div.appendChild(body);
  } else {
    div.appendChild(document.createTextNode(text));
  }
  const skipTime = cls.includes('sys') || cls.includes('thinking');
  if (!skipTime) {
    const t = formatTime(ts);
    if (t) {
      const span = document.createElement('span');
      span.className = 'time';
      span.textContent = t;
      div.appendChild(span);
    }
  }
  const dst = target || $msgs;
  if (dst) {
    dst.appendChild(div);
    scrollToBottom(dst, { force: !!(opts && opts.forceScroll) });
    _trimRenderedMessages(dst);
  }
  return div;
}
function addSys(text, target) { return addMsg('sys', text, null, null, target); }

/* wish-7c579a20 · 历史重建 用户 气泡附件（刷新后图不丢）
 * 数据双源: ①新格式 t.attachments（后端 meta 结构化落盘）
 *           ②老消息从 content 头部『已存: data/runtime/attachments/xxx』正则提取
 * 顺便剥皮: 系统注入的『[用户上传了 N 个附件…』说明段不进气泡·只留 用户 正文 */
function _用户AttachStrip(raw) {
  if (!raw || raw.indexOf('[用户上传了') !== 0) return { body: raw || '', legacy: [] };
  const sep = raw.indexOf('\n---\n');
  const head = sep >= 0 ? raw.slice(0, sep) : raw;
  const body = sep >= 0 ? raw.slice(sep + 5).trim() : '';
  const legacy = [];
  const re = /已存[:：]\s*data[\\/]runtime[\\/]attachments[\\/]([^\s·\]]+)/g;
  let m;
  while ((m = re.exec(head)) !== null) { if (m[1]) legacy.push(m[1]); }
  return { body: body, legacy: legacy };
}

function _render用户Attachments(bubble, atts) {
  if (!bubble || !atts || !atts.length) return;
  const wrap = document.createElement('div');
  wrap.className = '用户-attach-imgs';
  atts.forEach(function(a) {
    const base = String(a.path || '').split('/').pop().split('\\').pop();
    if (!base) return;
    const url = '/attachments/' + encodeURIComponent(base);
    const isImg = a.kind === 'image' || String(a.mime || '').indexOf('image/') === 0
      || /\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(base);
    if (isImg) {
      const img = document.createElement('img');
      img.className = '用户-attach-img';
      img.src = url;
      img.alt = a.name || base;
      img.title = a.name || base;
      img.loading = 'lazy';
      img.onclick = function() { window.open(url, '_blank'); };
      wrap.appendChild(img);
    } else {
      const card = document.createElement('a');
      card.className = 'attach-doc-card 用户-attach-doc';
      card.href = url;
      card.target = '_blank';
      card.innerHTML = '<i class="ri-file-3-line"></i><span class="doc-name">' + escHtml(a.name || base) + '</span>';
      wrap.appendChild(card);
    }
  });
  if (wrap.children.length) bubble.appendChild(wrap);
}

// 卷四十六 续 3 · "粘性底部"滚动 · 用户 拖滚动条看历史时不强行刷回底部
//
// 第一版坑 (kill 重写): 错以为 state.$container (.session-msgs) 是滚动元素
//   实际上 .session-msgs 没 overflow · #messages 才是 overflow-y:auto · 真正滚动的是 #messages
//   而且仅靠 isNearBottom(target) 软滚在快速流式 append 场景失效:
//     append 元素 → scrollHeight 立刻增长 / scrollTop 没动 → distance 突然变大 → isNearBottom 误 false → 软滚跳过
//
// 这版方案 (sticky flag + scroll listener · 聊天 UI 标准做法):
//   1. _getRealScrollTarget · .session-msgs reroute 到 #messages · 后台 hidden session 返回 null 直接跳过
//   2. _stickToBottom flag (全局 · #messages 只有一个滚动条)
//   3. scroll 事件听 #messages · 用户拖滚动条触发 → 更新 flag
//      代码 dst.scrollTop = scrollHeight 也会触发 scroll · 但 isNearBottom 此时必 true · flag 自动复位
//      关键: appendChild 不触发 scroll · 所以 append 时 flag 不会被错误清掉

const STICK_THRESHOLD_PX = 64;

// wish · 长会话 DOM 无上限增长 → 页面卡 / 打字慢 修复
// 单会话容器最多保留的消息节点数 · 超出裁最旧(仅贴底时) · 想彻底关掉把它设成 Infinity 即退回老行为
const MAX_RENDERED_MSGS = 220;
// 重开历史会话时只回放最近 N 个 turn · 更早折叠成顶部"加载全部"入口 · Infinity = 全量回放(老行为)
const HISTORY_RENDER_WINDOW = 90;

function isNearBottom(el, threshold) {
  if (!el) return false;
  const t = (typeof threshold === 'number') ? threshold : STICK_THRESHOLD_PX;
  const distance = el.scrollHeight - el.clientHeight - el.scrollTop;
  return distance <= t;
}

function _getRealScrollTarget(el) {
  if (!el) return null;
  if (el === $messagesPanel) return el;
  if (el.classList && el.classList.contains('session-msgs')) {
    // hidden = 后台 session · 用户在看别的 · 滚 #messages 会污染 visible session 滚动位置 · 跳过
    if (el.hidden) return null;
    return $messagesPanel;
  }
  return el;
}

let _stickToBottom = true;
function _attachStickListener() {
  if (!$messagesPanel || $messagesPanel._stickListenerAttached) return;
  $messagesPanel._stickListenerAttached = true;
  $messagesPanel.addEventListener('scroll', () => {
    _stickToBottom = isNearBottom($messagesPanel);
  }, { passive: true });
}
_attachStickListener();

// scrollToBottom(target, opts)
//   默认 force=true (向后兼容 · 错误 / nudge / confirm card 等"必须看到"的场景靠这个)
//   传 { force: false } = 软滚 · 仅在 sticky (#messages) 或 near bottom (其他 scrollable) 时滚
function scrollToBottom(target, opts) {
  let dst = target || $msgs;
  dst = _getRealScrollTarget(dst);
  if (!dst) return;
  const force = !opts || opts.force !== false;
  if (!force) {
    if (dst === $messagesPanel) {
      if (!_stickToBottom) return;
    } else if (!isNearBottom(dst)) {
      return;
    }
  } else if (dst === $messagesPanel) {
    // force 滚动 · 主动复位 sticky=true · 配合后续 scroll event 自然确认
    _stickToBottom = true;
  }
  requestAnimationFrame(() => { dst.scrollTop = dst.scrollHeight; });
}

// wish · 把某个 session 容器的消息节点压到 MAX_RENDERED_MSGS 以内 · 防长会话 DOM 撑爆导致卡顿/打字慢
// 安全约束: ① 只裁 visible 容器(后台 session 不动) ② 只在用户贴着底部时裁(不打断往上翻历史·不跳动)
//           ③ 遇到正在流式的节点就停(绝不裁 streaming) ④ MAX_RENDERED_MSGS=Infinity 时整条禁用
function _trimRenderedMessages(container) {
  if (!container || !isFinite(MAX_RENDERED_MSGS)) return;
  if (container.hidden) return;
  if (!_stickToBottom) return;
  const msgs = container.querySelectorAll(':scope > .msg:not(.load-earlier)');
  const overflow = msgs.length - MAX_RENDERED_MSGS;
  if (overflow <= 0) return;
  let removed = 0;
  for (let i = 0; i < msgs.length && removed < overflow; i++) {
    const el = msgs[i];
    if (el.classList.contains('streaming')) break;   // 到流式节点为止 · 不裁
    el.remove();
    removed++;
  }
  if (removed > 0) _ensureLoadEarlierSentinel(container);
}

// 顶部"更早的消息已折叠 · 点此加载全部"入口 · 点了全量重渲(内容真源在 jsonl · 永不丢)
function _ensureLoadEarlierSentinel(container) {
  if (!container) return;
  let s = container.querySelector(':scope > .msg.load-earlier');
  if (!s) {
    s = document.createElement('div');
    s.className = 'msg sys load-earlier';
    s.style.cursor = 'pointer';
    s.textContent = '⬆ 更早的消息已折叠 · 点此加载全部';
    s.addEventListener('click', () => {
      if (s._loading) return;  // 防重复点击 · 大会话全量加载要几秒
      s._loading = true;
      s.textContent = '⏳ 加载中…';
      s.style.pointerEvents = 'none';
      const sid = container.dataset && container.dataset.sid;
      if (sid) _loadSessionHistory(sid, { full: true });
    });
  }
  if (container.firstChild !== s) container.insertBefore(s, container.firstChild);
}

// 卷三十七 · 流式拼接 · 当前正在 stream 的 DOM 引用
// wish-3fef4bc7 · 改为 per-state · 没有 state 参数 = 不工作 (直接 return)
// state.currentStreamingReasoning / state.currentStreamingAssistant 持有 DOM 引用
function appendReasoningDelta(state, textPiece) {
  if (!textPiece || !state) return;
  if (!state.currentStreamingReasoning) {
    // 用户 2026-07-28: 新一轮思考开始 = 上一轮工具容器到此为止 ·
    // 收尾旧容器让后续 tool_call 开新容器 · 时间线变成 思考→工具组→思考→工具组 交替
    if (state._tl) { try { tlFinishRound(state); } catch (e) {} }
    // 新建一个流式 reasoning bubble · 自动展开 · 标 streaming
    const div = document.createElement('div');
    div.className = 'msg Daemonkey reasoning streaming';
    const header = document.createElement('div');
    header.className = 'reasoning-header';
    header.innerHTML = `<span class="reasoning-icon"><i class="ri-brain-fill"></i></span> <span class="reasoning-label">思考中</span> <span class="reasoning-toggle">收起 ▴</span>`;
    header.style.cursor = 'pointer';
    div.appendChild(header);
    const body = document.createElement('div');
    body.className = 'reasoning-body';
    div.appendChild(body);
    header.addEventListener('click', () => {
      const showing = !body.hidden;
      body.hidden = showing;
      const toggle = header.querySelector('.reasoning-toggle');
      if (toggle) toggle.textContent = showing ? '展开 ▾' : '收起 ▴';
    });
    if (state.$container) state.$container.appendChild(div);
    // 0.8.3 · 加 _pending/_raf 字段 · reasoning 走节流渲染
    state.currentStreamingReasoning = { div, body, _pending: '', _raf: 0 };
  }
  // 0.8.3 性能修复 · DeepSeek reasoning 逐 chunk 推 (每秒几十个) ·
  // 老代码每 chunk appendChild + isNearBottom 读布局 ×2 + 两次滚动 → layout thrashing ·
  // 长思考 + 大 DOM 时主线程吃满 → 滚动条拖不动 (用户 实测反馈)。
  // 修复: 累积到 _pending · RAF 合并每帧最多一次 append + 一次滚动判断 (肉眼无感·主线程降一个数量级)
  const r = state.currentStreamingReasoning;
  r._pending += textPiece;
  if (!r._raf) {
    r._raf = requestAnimationFrame(() => {
      r._raf = 0;
      if (!r._pending) return;
      r.body.appendChild(document.createTextNode(r._pending));
      r._pending = '';
      // reasoning-body 自身有 max-height + overflow-y · 必须把它自己也滚到底
      // 否则外层 $msgs 滚到底 · 但 reasoning 窗口内仍卡在原位 用户 看不到新字
      // 卷四十六续 3 · body 跟外层都走软滚 · 用户 拖到上面看历史时不打扰
      if (isNearBottom(r.body)) {
        r.body.scrollTop = r.body.scrollHeight;
      }
      scrollToBottom(state.$container, { force: false });
    });
  }
}

function finalizeStreamingReasoning(state) {
  if (!state) return;
  if (!state.currentStreamingReasoning) return;
  const r = state.currentStreamingReasoning;
  // 0.8.3 · 节流后最后一帧可能还有 pending 没刷 · finalize 前补刷 + 取消挂起的 RAF
  if (r._raf) { cancelAnimationFrame(r._raf); r._raf = 0; }
  if (r._pending) { r.body.appendChild(document.createTextNode(r._pending)); r._pending = ''; }
  r.div.classList.remove('streaming');
  // 完成后默认收起 · 减视觉噪音 · 用户 想看再展开
  const body = r.body;
  const header = r.div.querySelector('.reasoning-header');
  if (body && header) {
    body.hidden = true;
    const toggle = header.querySelector('.reasoning-toggle');
    if (toggle) toggle.textContent = '展开 ▾';
    const label = header.querySelector('.reasoning-label');
    if (label) label.textContent = `思考完成 · ${body.textContent.length} 字`;
  }
  state.currentStreamingReasoning = null;
}

// 0.9.1 · 兜底: assistant_reasoning_done 到达但 currentStreamingReasoning 为空
// (reasoning_delta 因并发/时序丢失时) → 补建一个已完成的折叠气泡 · 不让思考链静默消失
function ensureReasoningBubble(state, text) {
  if (!state || !text) return;
  if (state.currentStreamingReasoning) {
    // 还在流式 → 把缺失的文本补进去再正常收尾
    appendReasoningDelta(state, text);
    finalizeStreamingReasoning(state);
    return;
  }
  // 没有流式气泡 → 直接渲染成历史形态的折叠气泡 (跟 renderReasoningBubble 历史分支一致)
  renderReasoningBubble(text, { collapsed: true, historical: true }, state.$container);
}

// 卷四十六续 4 · 流式 markdown 实时渲染 · "streaming-safe close"
// 老版本 appendAssistantDelta 用 textContent · 等 finalize 才 mdRender · 流式期间 用户 看到的是裸字面 (丑)
// 新版本 streaming 期间每帧也 mdRender · 但末尾未闭合的 ``` / ` / ** / __ 临时补尾
// 让中途 markdown 也能渲染成正常 HTML · 不补尾会让 ```python\nprint( 半截字面飘
//
// 不动源数据 (state.streamingAssistantRaw) · 只在 mdRender 入参时套一层 safe close
// finalize 时用累积的 raw / server 给的 finalText · 不走 safe close (那时一定是完整的)
function _streamingSafeClose(text) {
  if (!text) return text;
  let t = text;
  // 1. 围栏代码块 ``` 奇数个 → 补一个 (让 mdRender 的 /```...```/g regex 能匹配上整段)
  const fenceCount = (t.match(/```/g) || []).length;
  if (fenceCount % 2 === 1) {
    t += '\n```';
  }
  // 2. 行内 code ` 奇数个 (排除 ``` 已经数过的部分) → 补一个
  const tickCount = (t.replace(/```/g, '').match(/`/g) || []).length;
  if (tickCount % 2 === 1) {
    t += '`';
  }
  // 3. 粗体 ** 奇数对 → 补两个
  const starsCount = (t.match(/\*\*/g) || []).length;
  if (starsCount % 2 === 1) {
    t += '**';
  }
  // 4. 粗体 __ 奇数对 → 补两个 (跟 ** 不冲突 · mdRender 内部两个 regex 分开处理)
  const underCount = (t.match(/__/g) || []).length;
  if (underCount % 2 === 1) {
    t += '__';
  }
  return t;
}

// RAF throttle · 每帧最多 rerender 一次 · 即使 delta 来得密集也只渲染一次
// 关键: 复用同一个 .md-body 元素 (innerHTML 重置) · 不破坏 bubble 结构
//
// 卷五十四 · WebUI 卡死优化: 老版每个 rAF (~16ms) 就对**全文** mdRender + innerHTML 重建一次。
// 长回复 (几千~几万字) 时·这是 O(n) 的全量重解析·每秒 ~60 次·主线程被吃满 → 页面卡顿/卡死。
// 改成按当前长度自适应时间节流: 越长间隔越大 · 用户 看不出 100~350ms 的 markdown 延迟·
// 但主线程压力降一个数量级。 finalize 时仍走完整渲染·不丢内容。
function _scheduleAssistantRerender(state) {
  if (!state || state._assistantRerenderScheduled) return;
  state._assistantRerenderScheduled = true;
  const raw = state.streamingAssistantRaw || '';
  const minGap = raw.length > 40000 ? 350 : (raw.length > 12000 ? 180 : 90);
  const now = (typeof performance !== 'undefined' ? performance.now() : Date.now());
  const wait = Math.max(0, minGap - (now - (state._lastAssistantRender || 0)));
  const doRender = () => {
    state._assistantRerenderScheduled = false;
    state._lastAssistantRender = (typeof performance !== 'undefined' ? performance.now() : Date.now());
    if (!state.currentStreamingAssistant) return;
    const body = state.currentStreamingAssistant.querySelector('.md-body');
    if (!body) return;
    const safe = _streamingSafeClose(state.streamingAssistantRaw || '');
    body.innerHTML = mdRender(safe, { streaming: true });
  };
  if (wait <= 0) {
    requestAnimationFrame(doRender);
  } else {
    setTimeout(() => requestAnimationFrame(doRender), wait);
  }
}

function appendAssistantDelta(state, textPiece) {
  if (!textPiece || !state) return;
  if (!state.currentStreamingAssistant) {
    // 新建一条流式 assistant bubble
    const div = document.createElement('div');
    div.className = 'msg Daemonkey streaming';
    const body = document.createElement('div');
    body.className = 'md-body';
    div.appendChild(body);
    if (state.$container) state.$container.appendChild(div);
    state.currentStreamingAssistant = div;
    state.streamingAssistantRaw = '';
  }
  // 累积 raw text · safe close 在 rerender 时套一层 · 不污染源数据
  state.streamingAssistantRaw = (state.streamingAssistantRaw || '') + textPiece;
  _scheduleAssistantRerender(state);
  scrollToBottom(state.$container, { force: false });
}

function finalizeStreamingAssistant(state, finalText) {
  if (!state || !state.currentStreamingAssistant) return;
  state.currentStreamingAssistant.classList.remove('streaming');
  const body = state.currentStreamingAssistant.querySelector('.md-body');
  if (body) {
    // 最终渲染 · 用 server 给的 finalText (最权威) · 否则用累积的 raw · 不走 safe close
    body.innerHTML = mdRender(finalText || state.streamingAssistantRaw || '');
  }
  // 加时间戳
  const t = formatTime(new Date());
  if (t) {
    const span = document.createElement('span');
    span.className = 'time';
    span.textContent = t;
    state.currentStreamingAssistant.appendChild(span);
  }
  const _finCont = state.$container;
  state.currentStreamingAssistant = null;
  state.streamingAssistantRaw = '';
  state._assistantRerenderScheduled = false;
  _trimRenderedMessages(_finCont);

  // 2026-08-08 · 语音对话模式 TTS 回复: 回完自动朗读 (温暖少女声) · 只影响语音对话
  //   条件: TTS 开关开 + 语音对话模式活跃 (transcribe + 正在听) · 其他模式不打扰
  try {
    if (window.__voiceTtsEnabled && typeof window.__speakReply === 'function') {
      const vMode = localStorage.getItem('Daemonkey_voice_mode');
      if (vMode === 'transcribe') {
        const speakText = (finalText || state.streamingAssistantRaw || '').trim();
        if (speakText) window.__speakReply(speakText);
      }
    }
  } catch (_e) { /* TTS 播放失败不影响对话主流程 */ }
}

// 卷三十六 · DeepSeek thinking mode · 渲染一条 reasoning 气泡
// 折叠式 · 默认展开 · 用户 可点收起；样式偏淡灰 + 斜体 · 跟正文区分
function renderReasoningBubble(text, options = {}, target) {
  if (!text) return null;
  const div = document.createElement('div');
  div.className = 'msg Daemonkey reasoning';
  const collapsed = !!options.collapsed;
  // 卷三十八 · 历史回放 · 不是 streaming · label 直接显示"思考完成 · N 字"
  const label = options.historical
    ? `思考完成 · ${text.length} 字`
    : '思考中';

  const header = document.createElement('div');
  header.className = 'reasoning-header';
  header.innerHTML = `<span class="reasoning-icon"><i class="ri-brain-fill"></i></span> <span class="reasoning-label">${label}</span> <span class="reasoning-toggle">${collapsed ? '展开 ▾' : '收起 ▴'}</span>`;
  header.style.cursor = 'pointer';
  div.appendChild(header);

  const body = document.createElement('div');
  body.className = 'reasoning-body';
  if (collapsed) body.hidden = true;
  body.textContent = text;  // 思考链原样显示 · 不走 markdown
  div.appendChild(body);

  header.addEventListener('click', () => {
    const showing = !body.hidden;
    body.hidden = showing;
    const toggle = header.querySelector('.reasoning-toggle');
    if (toggle) toggle.textContent = showing ? '展开 ▾' : '收起 ▴';
  });

  const dst = target || $msgs;
  if (dst) {
    dst.appendChild(div);
    scrollToBottom(dst, { force: false });
  }
  return div;
}

// ---------- SSE 流式发送（卷十七加） ----------

function parseSseStream(buffer) {
  const events = [];
  let parts = buffer.split('\n\n');
  const remaining = parts.pop();
  for (const evt of parts) {
    if (!evt.trim()) continue;
    let type = 'message', data = '';
    for (const line of evt.split('\n')) {
      if (line.startsWith(':')) continue;
      if (line.startsWith('event:')) type = line.slice(6).trim();
      else if (line.startsWith('data:')) data += (data ? '\n' : '') + line.slice(5).trim();
    }
    let parsed = null;
    if (data) {
      try { parsed = JSON.parse(data); } catch { parsed = { _raw: data }; }
    }
    events.push({ type, data: parsed || {} });
  }
  return [events, remaining];
}

// wish-3fef4bc7 · 真并行多对话 UI · send 函数核心改造
// 旧: 闭包局部变量 (assistantBubbles / sawAssistantText / 等) + 全局 currentAbortController
// 新: 全部进 _sessions[mySid] · send 闭包绑定 state · 用户 切对话不影响 send 跑·send 后台继续写自己的 state
async function send() {
  const text = $input.value.trim();
  if (!text && _attachments.length === 0) return;  // wish-4a6331b2 · 有附件时允许空文字

  // 主题切换拦截 (wish-7b89146f)
  if (interceptThemeCommand(text)) { $input.value = ''; $input.style.height = 'auto'; return; }
  if (!token) {
    addSys('⚠ 还没填 token —— 点右上角 ⚙ 设置');
    openSettings();
    return;
  }
  // 拿当前 active sid · 没有就分配临时 cid (新对话第一条消息)
  let mySid = sessionId;
  if (!mySid) {
    mySid = _allocCid();
    _getOrCreateSession(mySid);
    sessionId = mySid;
    _setActiveContainer(mySid);
  } else {
    // 确保 container 已创建
    _getOrCreateContainer(mySid);
  }
  const state = _getOrCreateSession(mySid);
  if (state.pending) return;  // 这个 session 已经在跑 · 不能再发
  // wish-3fef4bc7 follow-up · 用户 自己开始发新消息 · 停 polling 让 SSE 接管 (polling 落后 SSE)
  if (typeof _stopSessionPoll === 'function') _stopSessionPoll(state);

  // visible 检查·会因为 用户 切对话而变。 注意 hello 后 state.sessionId 会从 cid 变真 sid · 同步会改 sessionId · 这俩仍同步
  const _isVisible = () => sessionId === state.sessionId;

  // user msg push 到这个 session 的 container (无论 visible · 因为 用户 切回时要看到自己的输入)
  // 卷四十六续 3 · 用户 主动发消息 = 强制贴底 (期望看到自己刚发的话 · 且 reset"粘性底部")
  // wish-4a6331b2 · 图片附件显示在 用户 气泡里（直接插 img 不用 markdown——base64 太长会撑爆 md parser）
  // wish-4a6331b2 · 等所有附件异步读完再发
  if (_attachmentPromises.length > 0) await Promise.all(_attachmentPromises);
  _attachmentPromises.length = 0;
  const _hasImgs = _attachments.length > 0;
  addMsg('用户', text || '（图片）', null, new Date(), state.$container, { forceScroll: true });
  if (_hasImgs) {
    // wish-41ed72ef · 用户 气泡附件渲染：图片缩略图 + 文档卡片
    const _用户Bubble = state.$container ? state.$container.lastElementChild : null;
    if (_用户Bubble && _用户Bubble.classList.contains('用户')) {
      const _attWrap = document.createElement('div');
      _attWrap.className = '用户-attach-imgs';
      _attachments.forEach(a => {
        if (a.type === 'file') {
          // 文档卡片
          const card = document.createElement('div');
          card.className = 'attach-doc-card';
          card.style.width = 'auto'; card.style.height = 'auto';
          card.style.flexDirection = 'row'; card.style.gap = '8px';
          card.style.padding = '8px 12px'; card.style.marginTop = '6px';
          card.style.justifyContent = 'flex-start';
          const iconName = _DOC_ICONS[a.mime] || 'ri-file-3-line';
          card.innerHTML = '<i class="' + iconName + '" style="font-size:20px"></i><span class="doc-name" style="max-width:none;font-size:12px">' + (a.name || 'file') + '</span><span class="doc-size" style="font-size:10px">' + _estSize(a.data_url) + '</span>';
          _attWrap.appendChild(card);
        } else {
          // 图片缩略图
          const _img = document.createElement('img');
          _img.src = a.data_url;
          _img.alt = a.name;
          _img.title = a.name;
          _img.style.maxWidth = '280px';
          _img.style.maxHeight = '200px';
          _img.style.borderRadius = '8px';
          _img.style.marginTop = '6px';
          _img.style.display = 'block';
          _attWrap.appendChild(_img);
        }
      });
      _用户Bubble.appendChild(_attWrap);
    }
  }
  $input.value = '';
  $input.style.height = 'auto';
  state.inputDraft = '';
  // clearAttachments() 移到 fetch 后面——payload 需要读 _attachments

  // 标 pending · 同步 visible UI
  state.pending = true;
  if (_isVisible()) {
    pending = true;
    setSendButtonState('pending');
    setInputLocked(true);
    showToolProgress(true);
    setToolProgressText('Daemonkey 准备工具中…');
  }

  // 重置 state 的 turn 局部状态
  state.assistantBubbles = [];
  state.sawAssistantText = false;
  state.finalUsage = null;
  state.finalSessionId = null;
  state.finalModel = null;
  state.errorShown = false;
  state.lastFinishReason = null;
  state.autoResumeCount = 0;
  state.streamHadToolCall = false;
  state.toolCallCount = 0;
  state.lastDashboardRefreshAt = 0;
  state.toolStartedAt = Date.now();
  state._turnStartedAt = Date.now();   // 卷七十九续 · 整轮起点·"思考中·已Ns"读秒用
  state._lastToolMeta = null;          // 清上一轮的冻结工具·否则"思考中"分支被跳过
  state._expectingDaemonRestart = false;
  // wish-ea8922f7 · 上一轮残留的顾问金卡 timer 必须清 · 不然跨 turn 继续读秒
  if (state._advisorCard && state._advisorCard._advTimer) {
    clearInterval(state._advisorCard._advTimer);
    state._advisorCard._advTimer = null;
  }
  state._advisorCard = null;

  // 整轮读秒 ticker(没工具在跑时显示"思考中·已Ns"·别卡 0s)· 仅 visible 起·后台 turn 不动进度条
  if (_isVisible()) _startToolProgressTicker(state);

  if (typeof _renderTabBar === 'function') {
    try { _renderTabBar(); } catch {}
  }

  const showError = (statusLine, detail) => {
    if (state.errorShown) return;
    state.errorShown = true;
    const errBlock = document.createElement('div');
    errBlock.className = 'msg err';
    errBlock.textContent = statusLine + (detail ? '\n' + detail : '');
    if (state.$container) state.$container.appendChild(errBlock);
    scrollToBottom(state.$container);
  };

  // 用户主动 abort 标记 · 用户 按 ⏹ 设置成 true · catch 块据此判别"主动中断"vs"网络错"
  let userAbortedSelf = false;

  try {
    state.currentAbortController = new AbortController();
    if (_isVisible()) currentAbortController = state.currentAbortController;
    state.currentAbortController._userAbortRef = () => { userAbortedSelf = true; };

    // 临时 cid 不发给 daemon · daemon 自己建新 session
    const reqSid = state.sessionId.startsWith('tmp-') ? null : state.sessionId;

    const resp = await fetch('/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + token,
        'Accept': 'text/event-stream',
      },
      signal: state.currentAbortController.signal,
      body: JSON.stringify({
        message: text,
        session_id: reqSid,
        auto_confirm: autoConfirm,
        attachments: _attachments.length > 0 ? _attachments.map(a => ({name: a.name, data_url: a.data_url})) : undefined,
        advisor_coop: _advisorCoopOn() || undefined,   // wish-0e749752 · 顾问协同 toggle
        ...modelBehaviorPayload(),
      }),
    });
    // wish-4a6331b2 · payload 已读 _attachments · 现在可以清了
    clearAttachments();

    if (!resp.ok) {
      const raw = await resp.text();
      let detail = raw;
      try { const j = JSON.parse(raw); detail = j.detail || j.error || raw; }
      catch { /* keep raw */ }
      showError(`[${resp.status} ${resp.statusText}]`, detail.slice(0, 1500));
      return;
    }

    if (!resp.body) {
      showError('响应没有 body —— 浏览器可能不支持 fetch streaming', '');
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const [events, rest] = parseSseStream(buffer);
      buffer = rest;
      for (const evt of events) {
        handleStreamEvent(evt.type, evt.data);
      }
    }

    if (!state.sawAssistantText && !state.errorShown) {
      addMsg('Daemonkey', '(Daemonkey 没说话)', null, null, state.$container);
    }
  } catch (e) {
    // 用户 主动 stop = userAbortedSelf · catch 不算错
    // AbortError + !userAbortedSelf 也可能是关页面之类·按"主动取消"对待
    if (e.name === 'AbortError' || userAbortedSelf) {
      // 不算错 · 正常路径 (包括 Daemonkey 调 request_restart 时 tool_call 主动 abort 的)
    } else if (state._expectingDaemonRestart) {
      // 卷四十六 续 14 补丁 III · 兜底 · 如果 tool_call 那边没主动 abort · 这边接 SSE 断
      // 走同一条恢复路径 · 不弹红框
      waitForDaemonAfterRestartTool(state);
    } else {
      showError('网络/流式出错', e.message || String(e));
    }
  } finally {
    tlFinishRound(state);  // wish-5256d2a4 · abort/异常/正常统一在此收尾时间线（done 已调则为 no-op）
    for (const b of (state.assistantBubbles || [])) b.classList.remove('streaming');

    if (state.finalUsage) {
      const u = state.finalUsage;
      const meta = document.createElement('div');
      meta.className = 'usage';
      const parts = [`in ${u.input_tokens || 0}`, `out ${u.output_tokens || 0}`];
      if (u.cache_read_tokens) parts.push(`cache_read ${u.cache_read_tokens}`);
      meta.textContent = parts.join(' · ') + (state.finalModel ? ` · ${state.finalModel}` : '');
      if (state.$container) state.$container.appendChild(meta);
      scrollToBottom(state.$container, { force: false });
    }

    // wish-351793b8 兜底·hello 没成功送达时 finally 再 commit 一次
    if (state.finalSessionId) {
      commitSessionId(state.finalSessionId);
    }

    state.pending = false;
    state.currentTurnId = null;
    state.currentAbortController = null;

    if (state.currentStreamingReasoning) finalizeStreamingReasoning(state);
    if (state.currentStreamingAssistant) finalizeStreamingAssistant(state, null);

    // 同步 visible UI (是 visible 才动全局)
    if (_isVisible()) {
      pending = false;
      currentTurnId = null;
      currentAbortController = null;
      setSendButtonState('idle');
      setInputLocked(false);
      $input.focus();
      showToolProgress(false);
      refreshPlan();   // 这一轮可能列了计划/勾掉一步 · 立刻刷·别等 6s 轮询
      try { _maybeTabFlash('✅ Daemonkey 干完了'); } catch {}
    } else {
      // 后台跑完 + 用户 不在看 = 标记 unread + toast 提示
      state.hasUnreadCompletion = true;
      if (typeof _showCompletionToast === 'function') {
        try { _showCompletionToast(state); } catch {} }
      try { _maybeTabFlash('✅ Daemonkey 干完了'); } catch {}
    }

    // mutating tools → dashboard / nav 全局刷 (无论 visible · 因为后端数据变了)
    if (state.streamHadToolCall) {
      if (typeof refreshNavBadges === 'function') {
        try { refreshNavBadges(); } catch {}
      }
      if (currentView) {
        try { loadDashboard(currentView, { silent: true }); } catch {}
      }
    }

    // sys 兜底 (写到 state 的 container · 跟流式内容同位置)
    if (!state.sawAssistantText && !state.errorShown) {
      addSys('Daemonkey 这轮没出最终回复 · 看上面 reasoning · 可能是: 工具回结果但 LLM 没继续 / 触发了 max iter / 网络中断。下条消息可以让他「请继续 / 给个总结」', state.$container);
    }
    if (state.lastFinishReason === 'length' && state.autoResumeCount >= 3) {
      addSys('⚠ Daemonkey 自动续接 3 次还没写完 · 这次任务输出量太大 · 可以: 1) 编辑当前 LLM 配置把 max_tokens 调更大 · 2) 发"请只给总结·不要全文"让 Daemonkey 收敛', state.$container);
    }

    if (typeof _renderTabBar === 'function') {
      try { _renderTabBar(); } catch {}
    }
  }

  // === 内嵌 helpers · 闭包能拿到 state / text / _isVisible / showError ===

  // wish-351793b8 + wish-3fef4bc7 · session id 持久化
  // 临时 cid → 真 sid 时 swap state · 同步 sessionId 全局 (是 active 时) · 设别名
  function commitSessionId(newSid) {
    if (!newSid) return;
    const oldSid = state.sessionId;
    if (oldSid === newSid) return;
    if (oldSid && oldSid.startsWith('tmp-')) {
      // tmp-cid → 真 sid · 把 _sessions / DOM container / sessionId 全 swap
      _swapSessionId(oldSid, newSid);
      // 默认别名 = 第一句话前 24 字
      if (!sessionAliases[newSid]) {
        sessionAliases[newSid] = (text || '').slice(0, 24) + ((text || '').length > 24 ? '…' : '');
        saveAliases();
      }
    } else if (oldSid !== newSid) {
      // 极端情况 daemon 给了不同的真 sid (理论上不会) · 兜底改 state.sessionId
      state.sessionId = newSid;
      if (state.$container) state.$container.dataset.sid = newSid;
    }
    // 持久化 (只有 active 才存 localStorage)
    if (sessionId === newSid) {
      localStorage.setItem(STORAGE.session, newSid);
      updateCurrentLabel();
    }
    if (typeof _refreshSessionLists === 'function') {
      try { _refreshSessionLists(); } catch {}
    }
  }

  function handleStreamEvent(type, data) {
    switch (type) {
      case 'hello':
        if (data && data.turn_id) {
          state.currentTurnId = data.turn_id;
          if (_isVisible()) currentTurnId = data.turn_id;
        }
        if (data && data.session_id) {
          commitSessionId(data.session_id);
        }
        if (state.assistantBubbles.length === 0) {
          const ph = addMsg('Daemonkey', 'Daemonkey 正在想', 'msg Daemonkey thinking', null, state.$container);
          ph.dataset.placeholder = '1';
          state.assistantBubbles.push(ph);
        }
        break;

      case 'reasoning_delta': {
        const ph = state.assistantBubbles[0];
        if (ph && ph.dataset.placeholder) {
          ph.remove();
          state.assistantBubbles.shift();
        }
        appendReasoningDelta(state, data.text || '');
        break;
      }

      case 'assistant_reasoning_done': {
        // 0.9.1 · 用兜底版: reasoning_delta 丢了也能补建气泡 · 不静默丢思考链
        ensureReasoningBubble(state, data.text || '');
        const newPh = addMsg('Daemonkey', '继续...', 'msg Daemonkey thinking', null, state.$container);
        newPh.dataset.placeholder = '1';
        state.assistantBubbles.push(newPh);
        break;
      }

      case 'assistant_delta': {
        const ph = state.assistantBubbles[0];
        if (ph && ph.dataset.placeholder) {
          ph.remove();
          state.assistantBubbles.shift();
        }
        appendAssistantDelta(state, data.text || '');
        break;
      }

      case 'auto_resume': {
        state.autoResumeCount = data.count || state.autoResumeCount + 1;
        const note = data.note || `自动续接 ${state.autoResumeCount}/${data.max || 3}`;
        addSys(`⏩ ${note} · Daemonkey 接着上次断点继续`, state.$container);
        const newPh = addMsg('Daemonkey', '继续中...', 'msg Daemonkey thinking', null, state.$container);
        newPh.dataset.placeholder = '1';
        state.assistantBubbles.push(newPh);
        break;
      }

      case 'assistant_finish': {
        state.lastFinishReason = data.finish_reason || null;
        break;
      }

      case 'assistant_reasoning': {
        const ph = state.assistantBubbles[0];
        if (ph && ph.dataset.placeholder) {
          ph.remove();
          state.assistantBubbles.shift();
        }
        // 用户 2026-07-28: 同 appendReasoningDelta · 新一轮思考前收尾旧工具容器 · 时间线按轮分组
        if (state._tl) { try { tlFinishRound(state); } catch (e) {} }
        renderReasoningBubble(data.text || '', {}, state.$container);
        const newPh = addMsg('Daemonkey', '继续...', 'msg Daemonkey thinking', null, state.$container);
        newPh.dataset.placeholder = '1';
        state.assistantBubbles.push(newPh);
        break;
      }

      case 'assistant_text': {
        // 0.9.1 · 文字到达 = 上一轮工具容器到此为止 (轮次边界·不依赖 reasoning_delta)
        // 修: flash 模型短思考/无思考时不吐 reasoning_delta → 旧容器永不收尾 → 多轮工具全合一个容器
        if (state._tl && state._tl.$round && state._tl.$round.isConnected) {
          try { tlFinishRound(state); } catch (e) {}
        }
        state.sawAssistantText = true;
        const ph = state.assistantBubbles[0];
        if (ph && ph.dataset.placeholder) {
          ph.remove();
          state.assistantBubbles.shift();
        }
        if (state.currentStreamingAssistant) {
          finalizeStreamingAssistant(state, data.text || '');
        } else {
          const bubble = addMsg('Daemonkey', data.text || '', 'msg Daemonkey', new Date(), state.$container);
          if (data.has_tool_calls) {
            bubble.classList.add('streaming');
          }
          state.assistantBubbles.push(bubble);
        }
        break;
      }

      case 'stuck_detected': {
        const div = document.createElement('div');
        div.className = 'msg sys stuck-warn';
        div.style.cssText = 'background: rgba(255,140,0,0.12); border-left: 3px solid #ff8c00; color: #ffb060; padding: 8px 12px; margin: 6px 0; font-size: 12px;';
        const sig = (data.signature || '?').slice(0, 60);
        const seen = data.seen_count || 0;
        const reason = data.reason || 'repeated_tool_calls';
        if (reason === 'forced_break') {
          div.textContent = `⛔ Daemonkey 已经 nudge ${data.cap || 2} 次还在重复同样的工具调用 · 强制中断 · 签名: ${sig}`;
        } else {
          div.textContent = `⚠ Daemonkey 在重复同样的工具调用 (${seen} 次) · 已注入"换个思路"提示 · 签名: ${sig}`;
        }
        if (state.$container) state.$container.appendChild(div);
        scrollToBottom(state.$container);
        break;
      }

      case 'closure_hint': {
        // 卷五十九 · P3 · turn 结束反思卡 · 干了活没沉淀 → 提醒过收尾三问 (对账入口)
        // 留在当前会话注入 (injectChat·不开新会话)·因为沉淀要的正是这一轮的工作上下文。
        const div = document.createElement('div');
        div.className = 'msg sys closure-hint-card';
        const head = document.createElement('div');
        head.className = 'closure-hint-head';
        head.innerHTML = '<i class="ri-lightbulb-flash-line"></i> 收尾提示 · 别让经验白干';
        const body = document.createElement('div');
        body.className = 'closure-hint-body';
        body.textContent = data.text || '这回合干了活但没沉淀 · 要不要过一遍收尾三问?';
        const acts = document.createElement('div');
        acts.className = 'closure-hint-acts';
        const goBtn = document.createElement('button');
        goBtn.className = 'btn-primary closure-hint-btn';
        goBtn.innerHTML = '<i class="ri-quill-pen-line"></i> 过收尾三问';
        goBtn.onclick = () => {
          const prompt = '回头看刚才这轮 — 过一遍收尾三问，该沉淀的沉淀：\n'
            + '① 我这次有没有透露/出现新信号该记进 OWNER-NOTEBOOK？(update_bro_note)\n'
            + '② 这次的操作流程/踩坑值得抽成 playbook 吗？(extract_playbook)\n'
            + '③ 有没有暴露我的能力缺口该记心愿？(wish_add)\n'
            + '确实啥也不用沉淀就说一句为什么。';
          if (typeof injectChat === 'function') injectChat(prompt, { autosend: false });
          div.remove();
        };
        const skipBtn = document.createElement('button');
        skipBtn.className = 'btn-ghost closure-hint-btn';
        skipBtn.innerHTML = '<i class="ri-close-line"></i> 忽略';
        skipBtn.onclick = () => div.remove();
        acts.appendChild(goBtn);
        acts.appendChild(skipBtn);
        div.appendChild(head);
        div.appendChild(body);
        div.appendChild(acts);
        if (state.$container) state.$container.appendChild(div);
        scrollToBottom(state.$container);
        break;
      }

      case 'tool_call': {
        state.streamHadToolCall = true;
        state.toolCallCount += 1;
        // wish-5256d2a4 · 工具事件进时间线容器（整轮折叠块·默认展开）· 不再逐条平铺黑话气泡
        tlAddStep(state, data.name || '?', data.summary || _tlArgsSummary(data.args || data.arguments), data.tier);
        scrollToBottom(state.$container, { force: false });

        // wish-ea8922f7 · 顾问在场感: replan 工具被调 → 插金色 live 卡 (顾问跑的 10-30s 不再静默)
        if (data.name === 'replan' && state.$container) {
          let advMode = 'unstick';
          try {
            const parsed = JSON.parse(data.args || data.arguments || '{}');
            if (parsed.mode && _ADV_MODE_LABEL[parsed.mode]) advMode = parsed.mode;
          } catch {}
          if (state._advisorCard && state._advisorCard._advTimer) {
            clearInterval(state._advisorCard._advTimer);
            state._advisorCard._advTimer = null;
          }
          state._advisorCard = advisorCardInsert(state, { mode: advMode, modelLabel: '' });
        }

        // 卷四十六 续 14 补丁 III + V · Daemonkey 调 request_restart 工具 = daemon ~2 秒后自爆 ·
        // SSE 必断 · 红框是预期不是 bug。 用户 看到红框容易再按 UI 重启按钮 · 第二次
        // 重启会打断 follow_up turn (用户 实测 2026-05-26 15:20-21 撞过这个坑)。
        // 修法 (续 14 补丁 V · 2026-05-26 15:45):
        //   - 检测到 request_restart tool_call (非 dry_run) → 设 flag · disable 按钮 · 提示
        //   - **立刻 fire-and-forget waitForDaemonAfterRestartTool(state)** ·
        //     不等 catch 块 (reader.read() 阻塞 · TCP reset 浏览器可能很慢才反应)
        //   - 它内部先延 2.5s 等 daemon 自爆 · 再 poll 子进程接管 · alive 后 reload session
        if (data.name === 'request_restart' && !state._expectingDaemonRestart) {
          let isDryRun = false;
          try {
            const parsed = JSON.parse(data.args || data.arguments || '{}');
            if (parsed.style === 'dry_run') isDryRun = true;
          } catch {}
          if (!isDryRun) {
            state._expectingDaemonRestart = true;
            // 卷五十七 · 提示写进调重启的那个 session 的 container · 不串到当前可见 tab
            addSys('⏳ Daemonkey 调了 request_restart · daemon 马上自爆+重启 · 红框是预期 · 别按重启按钮 · ~5 秒后自动接上', state.$container);
            const $r = document.getElementById('restartBtn');
            const $s = document.getElementById('shutdownBtn');
            if ($r) { $r.classList.add('is-restarting'); $r.disabled = true; }
            if ($s) { $s.disabled = true; }
            // 立刻启动·不等 catch 块 (SSE 断有 TCP 延迟)
            try {
              if (state.currentAbortController) {
                userAbortedSelf = true;  // 标记是我们主动 abort · catch 走『不算错』
                state.currentAbortController.abort();
              }
            } catch {}
            waitForDaemonAfterRestartTool(state);
          }
        }

        // tool progress 仅 visible 时刷 (后台 session 不动 active 的进度条)
        // 卷四十六续 9 · 每个新 tool_call 重置 startedAt + 启动 ticker (每秒读秒)
        if (_isVisible()) {
          state.toolStartedAt = Date.now();
          state._lastToolMeta = {
            name: data.name || '?',
            summary: data.summary || '',
            count: state.toolCallCount,
            startedAt: state.toolStartedAt,
            frozen: false,
          };
          _startToolProgressTicker(state);
          recordToolEvent('call', data.name, data.summary);
        }
        break;
      }

      // 卷五十八 · wish-f30d571d · 工具进度推送 · 长跑工具中间状态
      case 'tool_progress': {
        if (_isVisible() && state._lastToolMeta) {
          state._lastToolMeta.progressStep = data.step || '';
          state._lastToolMeta.progressMsg = data.msg || '';
          _refreshToolProgressTick();
          // wish-ea8922f7 · replan 的进度同步刷进金卡 (第 N 步 · 在读什么)
          if (state._advisorCard && state._lastToolMeta.name === 'replan') {
            advisorCardTick(state._advisorCard, (data.msg || data.step || '').trim());
          }
        }
        break;
      }

      // wish-0e749752 · 顾问协同模式 · daemon 推送的蓝图生命周期事件
      case 'advisor_status': {
        if (!state.$container) break;
        if (data.phase === 'start') {
          if (state._advisorCard && state._advisorCard._advTimer) {
            clearInterval(state._advisorCard._advTimer);
            state._advisorCard._advTimer = null;
          }
          if (state._advisorCard && state._advisorCard._reviewPollTimer) {
            clearTimeout(state._advisorCard._reviewPollTimer);
            state._advisorCard._reviewPollTimer = null;
          }
          const _m = (data.mode === 'review') ? 'review' : 'blueprint';
          state._advisorCard = advisorCardInsert(state, { mode: _m, modelLabel: data.model_label || '' });
          advisorCardTick(state._advisorCard, _m === 'review'
            ? '验收交付中… (协同自动验收 · 第 ' + (data.round || 1) + ' 次 · PASS 才算数)'
            : '出施工单中… (顾问协同模式 · 施工单就位后执行者开工)');
          // SSE 断流兜底: review 模式 120s 后启动 polling · 查 /api/advisor/status 自愈
          // (用户 2026-07-29 · review 跑 1-3 分钟 · 切标签页/网络波动丢 review_done 事件)
          if (_m === 'review') {
            state._advisorCard._reviewPollTimer = setTimeout(() => {
              _advisorReviewPoll(state);
            }, 120000);
          }
        } else if (data.phase === 'progress') {
          // 协同模式 · 顾问内部逐步事件 → 金卡文案对齐设计稿 (第 N 轮 · 正在勘察 X · 已读 N 个文件)
          if (state._advisorCard) {
            if (data.kind === 'think') {
              advisorCardTick(state._advisorCard, '思考中…');
            } else {
              const verb = ({ read_file: '正在勘察', outline_file: '正在勘察', grep_files: '正在搜索',
                search_code: '正在搜索', glob_files: '正在找文件', pdf_read: '正在读 PDF',
                web_search: '正在搜网', web_fetch: '正在读网页', recall_memory: '正在翻记忆',
                list_apps: '正在翻应用清单', list_flows: '正在翻工作流' })[data.name] || ('正在调用 ' + (data.name || '?'));
              let t = '第 ' + (data.turn || 0) + ' 轮 · ' + verb + (data.target ? ' ' + data.target : '');
              if (data.files_read) t += ' · 已读 ' + data.files_read + ' 个文件';
              advisorCardTick(state._advisorCard, t);
            }
          }
        } else if (data.phase === 'blueprint_done') {
          if (state._advisorCard) {
            if (state._advisorCard._reviewPollTimer) {
              clearTimeout(state._advisorCard._reviewPollTimer);
              state._advisorCard._reviewPollTimer = null;
            }
            advisorCardFinish(state._advisorCard, { ok: true, modelLabel: data.model_label || '',
              preview: (data.text || '').trim().slice(0, 800),
              suppressAnswer: true });  // coop 模式 · 施工单全文在下方就位卡 · 这张只留 head + 展开过程
            state._advisorCard = null;
          }
          advisorBlueprintCard(state, { modelLabel: data.model_label || '', text: data.text || '',
            subId: data.sub_id || '' });
        } else if (data.phase === 'blueprint_failed') {
          if (state._advisorCard) {
            if (state._advisorCard._reviewPollTimer) {
              clearTimeout(state._advisorCard._reviewPollTimer);
              state._advisorCard._reviewPollTimer = null;
            }
            advisorCardFinish(state._advisorCard, { ok: false, modelLabel: data.model_label || '', preview: '' });
            state._advisorCard = null;
          }
          addSys('🧭 顾问协同 · 顾问本次没能给出施工单' + (data.error ? ' (' + data.error + ')' : '') + ' · 按常规方式推进', state.$container);
        } else if (data.phase === 'blueprint_aborted') {
          // 用户 点了停止 · 顾问被掐 · 主对话同轮也跟着停 (daemon_api 协同块 cancel 分支)
          if (state._advisorCard) {
            if (state._advisorCard._reviewPollTimer) {
              clearTimeout(state._advisorCard._reviewPollTimer);
              state._advisorCard._reviewPollTimer = null;
            }
            advisorCardFinish(state._advisorCard, { ok: false, label: '顾问已停止',
              modelLabel: data.model_label || '', preview: '' });
            state._advisorCard = null;
          }
          addSys('🧭 顾问协同 · 已停止 · 本轮中断', state.$container);
        } else if (data.phase === 'review_done') {
          // 方案 B (用户 2026-07-28) · 协同自动验收: 交付前顾问验收 · PASS 才算数
          if (state._advisorCard) {
            if (state._advisorCard._reviewPollTimer) {
              clearTimeout(state._advisorCard._reviewPollTimer);
              state._advisorCard._reviewPollTimer = null;
            }
            advisorCardFinish(state._advisorCard, {
              ok: data.verdict === 'PASS',
              label: data.verdict === 'PASS' ? '顾问验收通过' : '顾问验收未通过',
              modelLabel: data.model_label || '', preview: '', suppressAnswer: true });
            state._advisorCard = null;
          }
          advisorReviewCard(state, { verdict: data.verdict || 'FAIL', text: data.text || '',
            modelLabel: data.model_label || '', round: data.round || 1, subId: data.sub_id || '' });
        }
        break;
      }

      // 卷七十三 P0-3 (2026-06-10) · sub-agent (run_app) 边界事件 · 用户 痛点:
      // 之前 run_app 跑 6-8 轮 sub-agent 内部 LLM · 主对话 ticker 文字一直变 (各种 read_file/write_file)
      // 但没人告诉 用户 "啊这是 sub-agent 在内部跑" · 用户 看着混乱 = 怀疑死了 / 跑偏了
      // 修: 在消息流插一条清晰的"▶ 子任务启动 / ✓ 子任务完成" 边界条 · 含 app 名 / 耗时 / token / warning
      case 'app_run_start': {
        if (!state.$container) break;
        const startTs = Date.now();
        const div = document.createElement('div');
        div.className = 'msg sub-agent-boundary sub-agent-start';
        div.dataset.appId = data.app_id || '';
        div.dataset.startedAt = String(startTs);
        const appName = data.app_name || data.app_id || '?';
        const tools = (data.tools || []).slice(0, 6).join(', ') + ((data.tools || []).length > 6 ? ' ...' : '');
        div.innerHTML = `<i class="ri-play-circle-fill"></i> <strong>子任务启动</strong>: <code>${escHtml(appName)}</code>` +
          (tools ? ` <span class="sub-agent-tools" title="允许的工具白名单">[${escHtml(tools)}]</span>` : '');
        state.$container.appendChild(div);
        // 记录到 state · 让 app_run_done 算耗时
        state._subAgentMeta = state._subAgentMeta || {};
        state._subAgentMeta[data.app_id] = { startTs, startDiv: div, appName };
        scrollToBottom(state.$container, { force: false });
        break;
      }

      case 'app_run_done': {
        if (!state.$container) break;
        const meta = (state._subAgentMeta || {})[data.app_id] || {};
        const elapsed = meta.startTs ? Math.floor((Date.now() - meta.startTs) / 1000) : 0;
        const appName = meta.appName || data.app_id || '?';
        const iter = data.iterations || 0;
        const maxIter = data.max_iterations || 0;
        const usage = data.usage || {};
        const inTok = usage.input_tokens || 0;
        const outTok = usage.output_tokens || 0;
        const cacheTok = usage.cache_read_tokens || 0;
        const warning = data.warning;
        const hitBudget = data.hit_budget;
        const iterBadge = maxIter ? `${iter}/${maxIter} 轮` : `${iter} 轮`;
        const tokBadge = `in <code>${inTok.toLocaleString()}</code> · out <code>${outTok.toLocaleString()}</code>` +
          (cacheTok ? ` · cache <code>${cacheTok.toLocaleString()}</code>` : '');
        let warnHtml = '';
        if (warning) {
          warnHtml = `<div class="sub-agent-warn${hitBudget ? ' sub-agent-warn-hit' : ''}"><i class="ri-error-warning-fill"></i> ${escHtml(warning)}</div>`;
        }
        const outKeys = (data.outputs_keys || []).join(', ');
        const div = document.createElement('div');
        div.className = 'msg sub-agent-boundary sub-agent-done' + (hitBudget ? ' sub-agent-hit-budget' : '');
        div.innerHTML = `<i class="ri-checkbox-circle-fill"></i> <strong>子任务完成</strong>: <code>${escHtml(appName)}</code> · ` +
          `<span class="sub-agent-stats">${iterBadge} · ${elapsed}s · ${tokBadge}</span>` +
          (outKeys ? ` <span class="sub-agent-outkeys" title="output_schema 字段">→ ${escHtml(outKeys)}</span>` : '') +
          warnHtml;
        state.$container.appendChild(div);
        scrollToBottom(state.$container, { force: false });
        break;
      }

      case 'app_run_error': {
        if (!state.$container) break;
        const meta = (state._subAgentMeta || {})[data.app_id] || {};
        const div = document.createElement('div');
        div.className = 'msg sub-agent-boundary sub-agent-error';
        div.innerHTML = `<i class="ri-error-warning-fill"></i> <strong>子任务失败</strong>: <code>${escHtml(meta.appName || data.app_id || '?')}</code> · ${escHtml(data.error || '未知错误')}`;
        state.$container.appendChild(div);
        scrollToBottom(state.$container, { force: false });
        break;
      }

      case 'tool_result': {
        // wish-5256d2a4 · 结果回填到时间线对应步骤卡（人话结果行 + 技术细节折叠）
        tlFillStep(state, data.name || '?', !!data.ok, data.ok ? (data.preview || 'ok') : (data.error || 'failed'));
        // wish-ea8922f7 · replan 完成 → 金卡变完成态 (摘要 + 展开顾问过程)
        if (data.name === 'replan' && state._advisorCard) {
          advisorCardFinish(state._advisorCard, {
            ok: !!data.ok,
            preview: data.ok ? (data.preview || '') : ('顾问调用失败: ' + (data.error || '未知错误')),
          });
          state._advisorCard = null;
        }
        if (data.ok && data.open_path) {
          // 不再挂在 tool-result 卡上(那在回复正文之前)· 攒起来·turn 结束时统一渲到对话底部(符合阅读习惯)
          state._pendingOpens = state._pendingOpens || [];
          state._pendingOpens.push({ path: data.open_path });
        }
        if (data.ok && Array.isArray(data.images) && data.images.length) {
          // 生图工具产出的可服务图 URL · 攒起来 · turn 末渲成可点放大的图廊
          state._pendingImages = state._pendingImages || [];
          data.images.forEach((u) => { if (u) state._pendingImages.push(u); });
        }
        scrollToBottom(state.$container, { force: false });

        if (data.ok && data.name && MUTATING_TOOLS.has(data.name)) {
          scheduleDashboardRefresh(600);
        }
        if (_isVisible()) {
          const tailText = data.ok ? (data.preview || 'ok').slice(0, 180) : (data.error || 'failed').slice(0, 180);
          recordToolEvent(data.ok ? 'ok' : 'fail', data.name, tailText);
          // 卷四十六续 9 · tool_result 时锁定进度条文本 = 总耗时 · 等下个 tool_call 重置
          if (state._lastToolMeta && state._lastToolMeta.name === data.name) {
            const m = state._lastToolMeta;
            m.frozen = true;
            m.endedAt = Date.now();
            m.ok = !!data.ok;
            const total = Math.floor((m.endedAt - m.startedAt) / 1000);
            const icon = data.ok ? '<i class="ri-check-fill"></i>' : '<i class="ri-close-fill"></i>';
            const briefTail = data.ok
              ? (data.preview || '').slice(0, 40).replace(/\n/g, ' ')
              : (data.error || 'failed').slice(0, 40);
            setToolProgressText(
              `${icon} 第 ${m.count} 个 · ${m.name || '?'} · 用了 ${total}s${briefTail ? ' · ' + briefTail : ''}`
            );
          }
        }
        break;
      }

      case 'confirm_request': {
        state.activeConfirmCards = state.activeConfirmCards || new Map();
        const card = renderConfirmCard(data, state);
        if (card) state.activeConfirmCards.set(data.tool_call_id, card);
        break;
      }

      case 'confirm_resolved': {
        state.activeConfirmCards = state.activeConfirmCards || new Map();
        const card = state.activeConfirmCards.get(data.tool_call_id);
        if (card) {
          collapseConfirmCard(card, data.decision, data.reason || '', !!data.auto_timeout, null);
          state.activeConfirmCards.delete(data.tool_call_id);
        }
        break;
      }

      case 'usage':
        state.finalUsage = data;
        break;

      case 'done':
        tlFinishRound(state);  // wish-5256d2a4 · 工具时间线收尾：头部人话统计 + 释放轮容器
        state.finalSessionId = data.session_id || state.finalSessionId;
        state.finalModel = data.model || state.finalModel;
        if (data.usage) state.finalUsage = data.usage;
        if (!state.sawAssistantText && data.reply) {
          const ph = state.assistantBubbles[0];
          if (ph && ph.dataset.placeholder) {
            ph.remove();
            state.assistantBubbles.shift();
          }
          addMsg('Daemonkey', data.reply, null, new Date(), state.$container);
        }
        flushImages(state);               // 生图产物图廊·先渲图·再渲打开按钮
        flushOpenActions(state);          // 产物「用对应软件打开」按钮·统一落在这一 turn 的最底部
        refreshCtxRing();                 // wish-bec4f3b9 · 回合结束刷压缩圆圈
        // 2026-08-06 · done 时后端 RUNTIME.messages 可能还没写入本轮 → 延时重刷一次 (时序兜底)
        setTimeout(refreshCtxRing, 800);
        break;

      case 'error': {
        tlFinishRound(state);  // wish-5256d2a4 · 出错也收尾时间线（pending 步骤停在中断态）
        showError(`[${data.status || 500}]`, data.detail || 'unknown error');
        const ph = state.assistantBubbles[0];
        if (ph && ph.dataset.placeholder) {
          ph.remove();
          state.assistantBubbles.shift();
        }
        if (state._pendingOpens) state._pendingOpens.length = 0;
        if (state._pendingImages) state._pendingImages.length = 0;
        refreshCtxRing();  // 2026-08-06 · error 也刷一次 (上下文可能已变化)
        break;
      }

      default:
        break;
    }
  }
}

// 卷三十八 · send / stop 合并 · 一个按钮两种状态
// 状态: idle (空闲) / pending (流式中 · 显示 ⏹ 停止) / stopping (停止信号已发 · 等回收)
function setSendButtonState(state) {
  $send.dataset.state = state;
  if (state === 'idle') {
    $send.textContent = '发送';
    $send.classList.remove('is-stopping', 'is-pending');
    $send.disabled = false;
    $send.title = 'Enter 发送 · Shift+Enter 换行';
  } else if (state === 'pending') {
    $send.textContent = '⏹ 停止';
    $send.classList.add('is-pending');
    $send.classList.remove('is-stopping');
    $send.disabled = false;
    $send.title = '点击中断当前 turn';
  } else if (state === 'stopping') {
    $send.textContent = '正在停…';
    $send.classList.add('is-stopping');
    $send.disabled = true;
  }
}

// 卷三十八 · 流式期间锁输入 · 用户 反馈"按说他完成后我才能发新消息 (像 cursor 这样)"
function setInputLocked(locked) {
  $input.readOnly = !!locked;
  $input.classList.toggle('is-locked', !!locked);
  const aiName = window.AI_NAME || 'Daemonkey';
  if (locked) {
    $input.placeholder = aiName + ' 还在跑 · 点 ⏹ 停止才能发新消息';
  } else {
    $input.placeholder = '跟 ' + aiName + ' 说点什么…  (Shift+回车换行)';
  }
}

// 卷三十八 · 停止两段式 (跟之前 $stop 的逻辑一样 · 抽出来)
// wish-3fef4bc7 · 改成走 active session 的 state · 停的是 用户 当前看的这个对话
// 切到另一个 session 后 ⏹ 停的是新 active · 不动后台 session
// follow-up: polling 模式下 (浏览器 F5 后没 SSE 但 daemon 有 active turn) · 走 daemon abort + 立刻 force poll
async function triggerStop() {
  if ($send.dataset.state !== 'pending') return;
  const s = activeSession();
  if (!s || !s.pending) return;
  setSendButtonState('stopping');
  addSys('· 已发停止信号 · 等 Daemonkey 当前这步跑完就退', s.$container);
  if (s.currentTurnId) {
    try {
      await fetch('/turns/' + s.currentTurnId + '/abort', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + token },
      });
    } catch (e) {
      console.warn('abort POST failed:', e);
    }
  }
  // SSE 模式 1.5s 兜底硬切 fetch reader (phase 2b watcher ~50ms 已搞定 · 双保险)
  setTimeout(() => {
    if (s.currentAbortController) {
      try { s.currentAbortController.abort(); } catch {}
    }
  }, 1500);
  // polling 模式下 currentAbortController 是 null · 但要立刻 force 一次 poll
  // daemon abort 后 _TURN_TO_SID 立刻 pop · active_turn 返回 null · _stopSessionPoll 还原 UI 到 idle
  // 250ms 给 daemon watcher 处理 abort 的时间 (phase 2b 是 50ms · 留点 buffer)
  if (s.pollIntervalId) {
    setTimeout(() => { _pollSession(s); }, 250);
  }
}

$send.addEventListener('click', () => {
  const state = $send.dataset.state || 'idle';
  if (state === 'pending') {
    triggerStop();
  } else if (state === 'idle') {
    send();
  }
  // stopping 状态 disabled 不会触发
});

// ═══════════ wish-bec4f3b9 · 上下文压缩圆圈 + Context Usage 卡片 ═══════════
let _ctxOpen = false;
const _RING_CIRC = 2 * Math.PI * 10.5;   // r=10.5
function _fmtTok(v) {
  if (v >= 1e6) return (v/1e6).toFixed(1) + 'M';
  if (v >= 1e3) return (v/1e3).toFixed(1) + 'k';
  return String(v || 0);
}
async function refreshCtxRing() {
  const wrap = document.getElementById('ctxRingWrap');
  if (!wrap) return;
  try {
    const sid = sessionId || activeSession()?.id || '';
    const q = sid ? ('?session_id=' + encodeURIComponent(sid)) : '';
    const r = await fetch('/context-usage' + q, { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) return;
    const d = await r.json();
    wrap.hidden = false;
    const pct = Math.min(100, Math.round(d.used_pct || 0));
    const arc = document.getElementById('ctxRingArc');
    const filled = _RING_CIRC * (pct / 100);
    arc.setAttribute('stroke-dasharray', filled.toFixed(1) + ' ' + (_RING_CIRC - filled).toFixed(1));
    arc.setAttribute('stroke', pct >= 85 ? '#FC8181' : pct >= 60 ? '#F6AD55' : '#4FD1C5');
    document.getElementById('ctxRingPct').textContent = pct;
    document.getElementById('ctxCardBadge').textContent = pct + '%';
    window._ctxData = d;   // 点开卡片时用最新数据
    const tip = wrap.querySelector('.ctx-ring')?.title;
    const remain = Math.max(0, (d.max_tokens||0) - (d.history_tokens != null ? d.history_tokens : (d.total_tokens||0)));
    if (tip) wrap.querySelector('.ctx-ring').title = `上下文已用 ${pct}% · 距压缩剩 ${_fmtTok(remain)} tok · 点击看明细`;
  } catch (_e) { /* 静默 · 拉不到就不显示 */ }
}
function renderCtxCard() {
  const d = window._ctxData;
  const bars = document.getElementById('ctxCardBars');
  if (!d || !bars) return;
  const blocks = d.blocks || [];
  const total = blocks.reduce((a, b) => a + (b.tokens || 0), 0) || 1;
  bars.innerHTML = blocks.map(b => {
    const w = ((b.tokens || 0) / total * 100).toFixed(1);
    return `<div class="ctx-block">
      <div class="ctx-block-row"><span class="lbl"><i class="${b.icon || 'ri-stack-fill'}" style="color:${b.color};margin-right:4px"></i>${escHtml(b.label || b.key || '')}</span><span class="val">${_fmtTok(b.tokens||0)} tok · ${w}%</span></div>
      <div class="ctx-block-bar"><div class="ctx-block-fill" style="width:${w}%;background:${b.color}"></div></div>
      ${b.sub ? `<div class="ctx-block-sub">${escHtml(b.sub)}</div>` : ''}
    </div>`;
  }).join('');
  const cache = document.getElementById('ctxCardCache');
  const ch = d.cache_hint || {};
  cache.innerHTML = `<i class="ri-flashlight-fill" style="color:#4FD1C5"></i> 缓存: ${ch.primed ? '前缀已预热 · 命中省钱' : '前缀未预热'}${ch.last_cache_read ? ` · 上轮命中 ${_fmtTok(ch.last_cache_read)} tok` : ''} <span style="color:var(--dim);font-size:10px">(固定前缀 灵魂+工具 每轮命中 = 省钱大头)</span>`;
  const foot = document.getElementById('ctxCardFoot');
  foot.textContent = `阈值 ${_fmtTok(d.max_tokens||0)} = context_window × 0.7 · 到线自动摘要压缩 · 跟当前对话实例走`;
}
// 点击圆圈 ↔ 卡片 · 点外部/关闭按钮收起
document.addEventListener('click', (e) => {
  const wrap = document.getElementById('ctxRingWrap');
  const card = document.getElementById('ctxCard');
  if (!wrap || !card) return;
  if (wrap.contains(e.target)) {
    _ctxOpen = !_ctxOpen;
    card.hidden = !_ctxOpen;
    if (_ctxOpen) renderCtxCard();
  } else if (!card.contains(e.target)) {
    _ctxOpen = false;
    card.hidden = true;
  }
});
// 首屏刷一次 (进页面就有圆圈)
setTimeout(refreshCtxRing, 2500);
// 2026-08-06 · 60s 轻量轮询兜底 (用户: 不是每轮都能自己刷) · 只更新圆圈 DOM · 不碰整页 ·
// 页面隐藏时跳过 (省资源) · 用 document.visibilityState 判断
setInterval(() => {
  if (document.visibilityState === 'visible') refreshCtxRing();
}, 60000);

// 卷五十四 · 输入卡顿修复 · requestAnimationFrame 节流 · 避免每次 keystroke 都触发 DOM reflow
let _inputHeightRAF = null;
// wish-4a6331b2 · Ctrl+V 粘贴图片
// wish-41ed72ef · Ctrl+V 粘贴图片或文件
$input.addEventListener('paste', e => {
  const items = e.clipboardData?.items;
  if (!items) return;
  for (const item of items) {
    const f = item.getAsFile();
    if (!f) continue;
    const mime = _guessMime(f);
    if (_IMG_MIMES.includes(mime) || _DOC_MIMES.includes(mime)) {
      e.preventDefault();
      addAttachment(f);
    }
  }
});

$input.addEventListener('input', () => {
  if (_inputHeightRAF) return;  // 上一帧还没跑 · 跳过
  _inputHeightRAF = requestAnimationFrame(() => {
    _inputHeightRAF = null;
    $input.style.height = 'auto';
    $input.style.height = Math.min($input.scrollHeight, 160) + 'px';
  });
});

// 卷三十八 · Enter 发送 / Shift+Enter 换行 / Ctrl+Enter 也发送 (跟 ChatGPT 一致)
// e.isComposing 拦截中文输入法组合期 · 避免按 Enter 选词时误发
$input.addEventListener('keydown', e => {
  if (e.key !== 'Enter') return;
  if (e.isComposing || e.keyCode === 229) return;  // 中文输入法 composing 中
  if (e.shiftKey) return;  // shift+enter 换行
  e.preventDefault();
  if (pending) return;  // 流式中 · 不响应 (按钮已变成停止 · 自己点)
  send();
});

// ──────────────────────────────────────────────────────────────
// 卷二十六 · 3 栏布局 · 左导航 · 中详情 · 右对话
//
// 设计变化（vs 卷二十五 cockpit 上下分屏）：
//   - 砍掉 cockpit · 信息雷达/趋势/报告这些"全部 →"不再切换全屏
//   - 左导航 nav-rail · 8+1 个维度纵向按钮
//   - 中详情 detail-pane · 点导航 → 这里显示该维度完整列表
//   - 右对话 chat-pane · 永远显示 · 用户 边看左边内容边右边打字
//   - "<i class="ri-brain-fill"></i> Daemonkey 日记" 新维度（cognition）· 读 OWNER-NOTEBOOK
// ──────────────────────────────────────────────────────────────

const $detailPane = document.getElementById('detailPane');
const $dashView = $detailPane;
const $navRail = document.getElementById('navRail');
const $navGroups = document.getElementById('navGroups');

// 维度元信息 · 这是唯一真相 · 改这里就够
// 卷二十九 · 五分组架构（市场咨询面 → 内部决策面 → 产品生产层 → 用户运营层 → 能力扩展层）
const NAV_GROUPS = [
  // 总览 · 工作室看板独立分组放最上 (用户 2026-08-06 · 它不是市场信息·是全局总览)
  { id: 'home',    label: '总览' },
  // 卷三十三补丁 · 用户 让重排：执行落地排到运营后 · 因为它是"已开干 + 自我观察"
  // 这个最贴近 用户 本人的事·应该在外部信息 → 决策 → 生产 → 用户之后·作为收束。
  { id: 'market',    label: '市场信息' },
  { id: 'ability',   label: '能力对照' },
  { id: 'studio',    label: '出品工坊' },
  { id: 'ops',       label: '用户运营' },
  { id: 'execution', label: '执行落地' },  // 已开干 + Daemonkey 日记 + 收藏
  { id: 'plugins',   label: '插件库' },
];

const DOMAIN_META = {
  // 工作室看板 · 起始屏 BI · 独立分组最上 (用户 2026-08-06 拍板 · 它不是市场信息)
  bi:            { icon: '<i class="ri-dashboard-fill"></i>', label: '工作室看板', section: 'home', stub: false },
  // 市场信息 · 外部信号 · Daemonkey 看世界的眼睛 · 不含 Daemonkey 自己的观察
  radar:         { icon: '<i class="ri-radar-fill"></i>', label: '信息雷达', section: 'market', stub: false },
  trends:        { icon: '<i class="ri-line-chart-fill"></i>', label: '今日趋势', section: 'market', stub: false },
  reports:       { icon: '<i class="ri-article-fill"></i>', label: '报告库',   section: 'market', stub: false },
  calendar:      { icon: '<i class="ri-calendar-fill"></i>', label: '信息日历', section: 'market', stub: false },
  // 能力对照 · 内部决策 · 市场 × 用户 能力的交叉
  opportunities: { icon: '<i class="ri-diamond-fill"></i>', label: '掘金机会', section: 'ability', stub: false },
  feasibility:   { icon: '<i class="ri-bar-chart-fill"></i>', label: '可行性分析', section: 'ability', stub: false },
  // 私有文档知识库 · 第二大脑 · 灌进来的资料喂掘金脑/可行性 · 与掘金同组让"资料→决策"这条线可见
  knowledge:     { icon: '<i class="ri-book-2-fill"></i>', label: '知识库', section: 'ability', stub: false },
  // 出品工坊 · 产品生产
  // 卷四十四 K stage 2a · 4 老维度 (content/design/dev/docs) 收进工坊主页"<i class="ri-archive-fill"></i> 应用"tab
  // 它们的 dashboard 端点 GET /dashboard/<id> 仍然有效 (workshop 内部 fetch 直拉)
  // 但 NAV_GROUPS 没 'apps' 组 · 所以从左导航 hidden · 跟 用户 当前需求一致
  workshop:  { icon: '<i class="ri-magic-fill"></i>', label: '出品工坊', section: 'studio', stub: false },
  content:   { icon: '<i class="ri-film-fill"></i>', label: '内容制作', section: 'apps', stub: false },
  design:    { icon: '<i class="ri-palette-fill"></i>', label: '产品设计', section: 'apps', stub: false },
  dev:       { icon: '<i class="ri-terminal-box-fill"></i>', label: '产品开发', section: 'apps', stub: false },
  docs:      { icon: '<i class="ri-file-text-fill"></i>', label: '文档撰写', section: 'apps', stub: false },
  // 用户运营 · 客户档案(合伙人记得每个客户 · notes 进记忆 · 资料可挂到客户名下)
  clients:   { icon: '<i class="ri-contacts-book-2-fill"></i>', label: '客户档案', section: 'ops', stub: false },
  service:   { icon: '<i class="ri-team-fill"></i>', label: '用户运营', section: 'ops', stub: true,
               note: '等先有产品再做用户运营' },
  // 执行落地 · 卷三十三 · 闭环反馈独立维度 · 卷三十三补丁 · Daemonkey 日记搬这里
  //   因为"Daemonkey 对 用户 的观察"跟"用户 真正在跑的项目"是同一码事——
  //   都是「自我视角」·跟外部信号（radar/trends/reports）分开
  execution:     { icon: '<i class="ri-refresh-fill"></i>', label: '执行反馈', section: 'execution', stub: false },
  scheduled_tasks: { icon: '<i class="ri-timer-2-fill"></i>', label: '定时任务', section: 'execution', stub: false },
  favorites:     { icon: '<i class="ri-star-fill"></i>', label: '收藏夹',   section: 'execution', stub: false },
  // ── 成长档案 (depot hub) · 把 日记/心愿/沉淀位/技能库 并成一个入口 · 内部标签切换 ──
  // 这 4 个本就是「Daemonkey 自己积累/沉淀的东西」· 并成一栏减少侧边栏拥挤 (用户 2026-07-11)
  // 2026-08-06 · 用户 拍板: 成长档案挪「总览」分组 (执行落地=用户 正在跑的事·成长档案=Daemonkey 自我成长·两者不同层)
  // 子维度 navHidden · 不单独占导航位 · 但 DOMAIN_META 条目保留 · loadDepot 仍复用它们的 render fn
  depot:         { icon: '<i class="ri-seedling-fill"></i>', label: '成长档案', section: 'home', stub: false },
  cognition:     { icon: '<i class="ri-brain-fill"></i>', label: 'Daemonkey 日记', section: 'home', stub: false, navHidden: true },
  // 卷三十五 · Daemonkey 自我演化心愿单 · "我想装这个能力"
  wishlist:      { icon: '<i class="ri-lightbulb-fill"></i>', label: 'Daemonkey 心愿', section: 'home', stub: false, navHidden: true },
  sinks:         { icon: '<i class="ri-archive-drawer-fill"></i>', label: '沉淀位',   section: 'home', stub: false, navHidden: true },
  // 技能库 · playbook 沉淀查看器 · 灌/召回仍走 NLP·这里只读+可删
  playbooks:     { icon: '<i class="ri-tools-fill"></i>', label: '技能库', section: 'home', stub: false, navHidden: true },
  // 插件库 · 能力扩展 · Daemonkey 自己用产品开发能写新插件回填这里
  plugins:   { icon: '<i class="ri-puzzle-fill"></i>', label: '插件库', section: 'plugins', stub: false },
};

// 卷二十八 · 雷达 / 机会的领域元信息（与 workers/info_radar.DOMAIN_META 保持对齐）
const RADAR_DOMAINS_META = {
  'ai':              { icon: '<i class="ri-robot-fill"></i>', label: 'AI / 大模型',  color: '#9f7aea' },
  'super-individual':{ icon: '<i class="ri-rocket-fill"></i>', label: '超个体 / 创业', color: '#4fd1c5' },
  'game-money':      { icon: '🎮', label: '游戏掘金',     color: '#ed8936' },
  'wildcard':        { icon: '✨', label: '杂项观察',     color: '#fc8181' },
  // 卷三十四 · self-evolve · Daemonkey 看 GitHub 同类工程的镜子
  'self-evolve':     { icon: '<i class="ri-tools-fill"></i>', label: '自我演化',     color: '#63b3ed' },
};

// 雷达 domain filter 当前选中的领域 · 'all' 表示不过滤
let radarDomainFilter = localStorage.getItem('radar_domain_filter') || 'all';

let currentView = null;  // 当前选中的维度 id · null = 没选

// ── 左导航渲染 + 切换 · 卷二十九 五分组 ─────────────────────────
function renderNav() {
  $navGroups.innerHTML = '';
  for (const grp of NAV_GROUPS) {
    const groupDiv = document.createElement('div');
    groupDiv.className = 'nav-group';

    const head = document.createElement('div');
    head.className = 'nav-section';
    head.textContent = grp.label;
    groupDiv.appendChild(head);

    const items = document.createElement('div');
    items.className = 'nav-items';

    let hasItems = false;
    for (const [id, m] of Object.entries(DOMAIN_META)) {
      if (m.section !== grp.id) continue;
      if (m.navHidden) continue;  // 合并进 depot hub 的子维度 · 不单独占导航位
      hasItems = true;
      const btn = document.createElement('button');
      btn.className = 'nav-item' + (id === currentView ? ' active' : '')
                    + (m.stub ? ' stub' : '')
                    + (m.disabled ? ' disabled' : '');
      btn.dataset.view = id;
      btn.innerHTML =
        `<span class="icon">${m.icon}</span>` +
        `<span class="label">${m.label}</span>` +
        `<span class="badge" id="navBadge_${id}">·</span>`;
      if (!m.disabled) {
        btn.addEventListener('click', () => switchView(id));
      }
      items.appendChild(btn);
    }
    if (hasItems) {
      groupDiv.appendChild(items);
      $navGroups.appendChild(groupDiv);
    }
  }
}
renderNav();

// ── 用户装修 API (0.9.6) ──────────────────────────────────────────────────
// 为什么需要它: chat.js / chat.html 在内核白名单里·官方升级会覆盖 → 用户直接改这两个文件
// 迟早被盖掉。 而 static/user/ 在 never_sync 里·永不被覆盖。 所以用户的界面改动写在
// static/user/user.js·通过下面这套 API 挂进来 —— 这是官方承诺的接口·会随内核一起维护。
// (真想直接改内核文件也行: 对 Daemonkey 说「chat.js 我自己管」→ 接管后官方永不覆盖它)
window.Daemonkey = window.Daemonkey || {};
Daemonkey._domains = {};   // 用户自定义维度 · loadDashboard 会查这里

// 加一个自定义维度(侧边栏入口 + 自己的渲染函数)。 render 收到中栏容器·想画什么画什么。
//   Daemonkey.addDomain('mine', { label:'我的面板', icon:'ri-star-line', section:'home',
//                                 render(pane){ pane.innerHTML = '...' } })
Daemonkey.addDomain = function (key, meta) {
  if (!key || !meta) return false;
  Daemonkey._domains[key] = meta;
  const icon = String(meta.icon || 'ri-apps-2-line');
  DOMAIN_META[key] = {
    icon: icon.trim().startsWith('<') ? icon : `<i class="${icon}"></i>`,
    label: meta.label || key,
    section: meta.section || 'home',
    stub: false,
  };
  renderNav();
  return true;
};

// 加一个侧边栏分组。 opts.before 传已有分组 id 可插到它前面·默认追加到最后。
Daemonkey.addNavGroup = function (id, label, opts) {
  if (!id || NAV_GROUPS.some(g => g.id === id)) return false;
  const grp = { id, label: label || id };
  const at = opts && opts.before ? NAV_GROUPS.findIndex(g => g.id === opts.before) : -1;
  if (at >= 0) NAV_GROUPS.splice(at, 0, grp); else NAV_GROUPS.push(grp);
  renderNav();
  return true;
};

// 装修代码的入口。 user.js 是 defer·跑到时 DOM 已就绪·但内联 <script> 未必 → 统一用它兜住。
Daemonkey.ready = function (fn) {
  if (typeof fn !== 'function') return;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn, { once: true });
  else setTimeout(fn, 0);
};

// 给装修代码用的抓手(免得用户去猜内核的变量名·这几个是稳定承诺)
Daemonkey.pane = () => $detailPane;            // 中栏容器
Daemonkey.refresh = () => loadDashboard(currentView);
Daemonkey.currentView = () => currentView;
Daemonkey.ctx = () => window._ctxData || null;  // 当前会话 token / 缓存命中等实时数据

function switchView(view) {
  if (!DOMAIN_META[view]) return;
  if (DOMAIN_META[view].disabled) return;
  currentView = view;
  // sidebar active 状态同步
  document.querySelectorAll('.nav-item').forEach(b => {
    b.classList.toggle('active', b.dataset.view === view);
  });
  // 卷三十七 · 切到 dashboard 维度时 · 清掉底部 ⚙ 设置按钮的高亮
  document.querySelectorAll('.nav-settings-btn.active').forEach(b => b.classList.remove('active'));
  // 加载该维度详情到中栏
  loadDashboard(view);
  // 手机端：自动收起导航
  if (window.innerWidth <= 900) {
    $navRail.classList.remove('open');
  }
}

function toggleNavRail() {
  $navRail.classList.toggle('open');
}

// 卷四十四 K stage 2d · 折叠功能重启 (stage 2b 的"画面崩" BUG 已修)
// root cause: col-resizer-left 用 display:none → grid item 序位错位 · detail/chat 落错列
// 修法: chat.css 行 1620+ 改 visibility:hidden 保住 grid 5 槽位
// (跟 toggleNavRail 不冲突 · 后者是手机端 slide-in 用的 .open class)
const NAV_COLLAPSED_KEY = 'Daemonkey_nav_collapsed_v1';
function toggleNavCollapse(force) {
  const layout = document.querySelector('.main-layout');
  if (!layout) return;
  const next = (typeof force === 'boolean')
    ? force
    : !layout.classList.contains('nav-collapsed');
  layout.classList.toggle('nav-collapsed', next);
  localStorage.setItem(NAV_COLLAPSED_KEY, next ? '1' : '0');
  // workshop 在中栏的话 · canvas 用 ResizeObserver 监容器尺寸 · 自动会重画 · 不用手动通知
}
(function _restoreNavCollapse() {
  // 2026-08-20 BRO 拍板: 导航默认收起 (纯图标 · 悬浮显名) · 显式展开过才保持展开
  if (localStorage.getItem(NAV_COLLAPSED_KEY) === '0') return;
  document.addEventListener('DOMContentLoaded', () => toggleNavCollapse(true), { once: true });
  if (document.readyState !== 'loading') toggleNavCollapse(true);
})();

// ── Dock 式距离衰减 (2026-08-20 BRO: 分组分割线割裂波动链 · 改 JS 按鼠标真实距离驱动 ·
//    跨分组连续 · 由大变小无限平滑 · 比 CSS :has 链更像真 macOS Dock) ──
// 分工: CSS 管 hover 弹出入场动画 (dkNavPop · 播放期间覆盖内联) + label 浮出;
//       JS 管 transform 距离衰减 + 颜色近紫远灰。 mouseleave 清空回弹。
(function _dockNavFx() {
  const groups = document.querySelector('.nav-groups');
  if (!groups) return;
  const isCollapsed = () => document.querySelector('.main-layout')?.classList.contains('nav-collapsed');
  let raf = 0;
  function paint(my) {
    raf = 0;
    groups.querySelectorAll('.nav-item .icon').forEach(ic => {
      const r = ic.getBoundingClientRect();
      const d = Math.abs(my - (r.top + r.height / 2));
      // 大小: 平方衰减 · 0px→1.7 · ~50px→1.45 · ~90px→1.2 · ≥140px→1
      // 颜色不动 (2026-08-20 BRO: 邻居染淡紫=比白色暗=像被隐藏) ——
      // 紫色是"选中"独占信号 · 归 CSS hover 管 · 距离感全靠大小波动表达
      const t = Math.max(0, 1 - d / 140);
      const s = 1 + 0.7 * t * t;
      ic.style.transform = s > 1.02 ? `scale(${s.toFixed(3)})` : '';
    });
  }
  groups.addEventListener('mousemove', (e) => {
    if (!isCollapsed() || raf) return;
    raf = requestAnimationFrame(() => paint(e.clientY));
  });
  groups.addEventListener('mouseleave', () => {
    groups.querySelectorAll('.nav-item .icon').forEach(ic => {
      ic.style.transform = '';
      ic.style.color = '';
    });
  });
})();
window.addEventListener('keydown', (e) => {
  if (e.altKey && (e.key === 'b' || e.key === 'B')) {
    e.preventDefault();
    toggleNavCollapse();
  }
});

// 卷四十六续 8 · 全局快捷键 · ESC 关 dashboard · `/` focus 输入框
// 在 input/textarea/contenteditable 内不劫持 · lightbox 优先吃 ESC
window.addEventListener('keydown', (e) => {
  const tag = (e.target && e.target.tagName) || '';
  const isInputLike = ['INPUT', 'TEXTAREA'].includes(tag) || (e.target && e.target.isContentEditable);
  if (e.key === 'Escape') {
    const lb = document.getElementById('md-lightbox');
    if (lb && !lb.hidden) return;
    if (currentView && typeof backToChat === 'function') {
      e.preventDefault();
      backToChat();
    }
    return;
  }
  if (e.key === '/' && !isInputLike && !e.ctrlKey && !e.altKey && !e.metaKey) {
    if (typeof $input !== 'undefined' && $input) {
      e.preventDefault();
      $input.focus();
    }
  }
});

// ─────────────────────────────────────────────────────────
// 卷四十六补丁 (wish-3afebd2c) · md 图片 lightbox
// chat 里点 .md-img → 全屏遮罩看大图 · 不开新 tab
// 关闭: 点遮罩 / 点 × / ESC
// ─────────────────────────────────────────────────────────
function _ensureLightbox() {
  let box = document.getElementById('md-lightbox');
  if (box) return box;
  box = document.createElement('div');
  box.id = 'md-lightbox';
  box.hidden = true;
  box.innerHTML = `
    <img id="md-lightbox-img" alt="">
    <button id="md-lightbox-close" type="button" aria-label="关闭 (Esc)">×</button>
    <div id="md-lightbox-caption"></div>
  `;
  document.body.appendChild(box);
  box.addEventListener('click', (e) => {
    if (e.target === box || e.target.id === 'md-lightbox-close') _hideLightbox();
  });
  return box;
}
function _showLightbox(src, alt) {
  const box = _ensureLightbox();
  const img = box.querySelector('#md-lightbox-img');
  const cap = box.querySelector('#md-lightbox-caption');
  img.src = src;
  img.alt = alt || '';
  cap.textContent = alt || '';
  box.hidden = false;
  document.body.style.overflow = 'hidden';
}
function _hideLightbox() {
  const box = document.getElementById('md-lightbox');
  if (!box || box.hidden) return;
  box.hidden = true;
  document.body.style.overflow = '';
  const img = box.querySelector('#md-lightbox-img');
  if (img) img.removeAttribute('src');
}
document.addEventListener('click', (e) => {
  const img = e.target.closest && e.target.closest('.md-img');
  if (!img) return;
  e.preventDefault();
  _showLightbox(img.dataset.full || img.src, img.alt);
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') _hideLightbox();
});

// ─────────────────────────────────────────────────────────
// 卷四十六 续 3 · wish-2a4d8c1e · inline confirm UI
// LLM 撞 CONFIRM 级 tool 时 · daemon push 'confirm_request' SSE event
// 这里渲染 inline 卡片 (含风险/规避两块 + 4 按钮 + 拒绝备注框)
// 用户 点按钮 → POST /turns/{turn_id}/confirm → 卡片折叠 + daemon 继续 turn
// ─────────────────────────────────────────────────────────

function _confirmEl(tag, cls, html) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (html != null) el.innerHTML = html;
  return el;
}

// ═══════════ wish-ea8922f7+0e749752 · 顾问在场感 · 金色卡片 + 协同 toggle ═══════════
// 设计语言: 蓝=工具 · 紫=工作流 · 金=顾问 (贵模型在场) · 抄 sub-agent-boundary 边界条模式
const _ADV_MODE_LABEL = { unstick: '破局', blueprint: '蓝图', review: '验收' };

// ── 协同 toggle (输入区功能条) · 用户 2026-07-28 钉死: 默认关 · 切会话/刷新都重置 ──
// 旧版 localStorage 全局记忆 → 用户 习惯性发消息才发现走的是顾问模式 · 改内存态 · 需要时手动开
const $advisorCoopToggle = document.getElementById('advisorCoopToggle');
const $advisorCoopHint = document.getElementById('advisorCoopHint');
let _advisorCoopMem = false;
try { localStorage.removeItem('advisor_coop'); } catch {}  // 一次性清掉旧版持久化残留
function _advisorCoopOn() {
  return _advisorCoopMem === true;
}
// 用户 2026-07-28 · 当前主模型=总监模型时协同无意义 (自己当自己的顾问·白烧钱) · toggle 置灰禁用
function _advisorCoopDisabled() {
  const cur = (window._currentModelId || '').trim();
  const dir = (window._directorModelId || '').trim();
  return !!(cur && dir && cur === dir);
}
function _advisorCoopReset() {  // 切会话时调用 · 默认关
  _advisorCoopMem = false;
  _advisorCoopRender();
}
function _advisorCoopRender() {
  const disabled = _advisorCoopDisabled();
  if (disabled) _advisorCoopMem = false;  // 禁用态强制关
  const on = _advisorCoopOn();
  if ($advisorCoopToggle) {
    $advisorCoopToggle.classList.toggle('on', on);
    $advisorCoopToggle.classList.toggle('disabled', disabled);
    $advisorCoopToggle.setAttribute('aria-pressed', on ? 'true' : 'false');
    $advisorCoopToggle.title = disabled
      ? '当前模型已是顾问模型 · 协同是让它当自己的顾问 · 没意义还烧钱'
      : '顾问协同: 发消息前先让顾问出施工单 · 执行者按单施工';
  }
  if ($advisorCoopHint) $advisorCoopHint.hidden = !on;
}
if ($advisorCoopToggle) {
  $advisorCoopToggle.addEventListener('click', () => {
    if (_advisorCoopDisabled()) return;  // 当前模型=顾问模型 · 禁用态不响应
    _advisorCoopMem = !_advisorCoopOn();
    _advisorCoopRender();
  });
  _advisorCoopRender();
}

// ── 金卡生命周期: insert(live) → tick(更新步骤) → finish(完成态+展开回放) ──
function advisorCardInsert(state, opts) {
  if (!state || !state.$container) return null;
  opts = opts || {};
  const div = document.createElement('div');
  div.className = 'msg advisor-card advisor-live';
  div.innerHTML =
    '<div class="advisor-head">' +
      '<span class="adv-spin"><i class="ri-user-star-line"></i></span>' +
      '<span>顾问参与中</span>' +
      (opts.modelLabel ? '<span class="model-chip">' + escHtml(opts.modelLabel) + '</span>' : '') +
      '<span class="elapsed">0.0s</span>' +
    '</div>' +
    '<div class="adv-shimmer"></div>' +
    '<div class="advisor-live-body">' +
      '<span class="adv-dots"><i></i><i></i><i></i></span> ' +
      '<b>' + escHtml(_ADV_MODE_LABEL[opts.mode] || opts.mode || '思考') + '模式</b> · <span class="adv-step">启动中…</span>' +
    '</div>';
  state.$container.appendChild(div);
  scrollToBottom(state.$container, { force: false });
  // 读秒 (0.1s 精度 · 跟整轮"思考中·已Ns"同款体感)
  const startedAt = Date.now();
  const elapsedEl = div.querySelector('.elapsed');
  const timer = setInterval(() => {
    if (elapsedEl) elapsedEl.textContent = ((Date.now() - startedAt) / 1000).toFixed(1) + 's';
  }, 100);
  div._advStartedAt = startedAt;
  div._advTimer = timer;
  return div;
}

function advisorCardTick(card, text) {
  if (!card) return;
  const stepEl = card.querySelector('.adv-step');
  if (stepEl) stepEl.textContent = text || '';
}

function advisorCardFinish(card, info) {
  if (!card) return;
  info = info || {};
  if (card._advTimer) { clearInterval(card._advTimer); card._advTimer = null; }
  const total = card._advStartedAt ? ((Date.now() - card._advStartedAt) / 1000).toFixed(1) : '?';
  card.classList.remove('advisor-live');
  const head = card.querySelector('.advisor-head');
  if (head) {
    head.innerHTML =
      '<i class="ri-user-star-fill"></i>' +
      '<span>' + (info.label || (info.ok === false ? '顾问没能给出结论' : '顾问已给出结论')) + '</span>' +
      (info.modelLabel ? '<span class="model-chip">' + escHtml(info.modelLabel) + '</span>' : '') +
      '<span class="elapsed">' + total + 's' + (info.iterations ? ' · ' + info.iterations + ' 轮' : '') + '</span>';
  }
  const shimmer = card.querySelector('.adv-shimmer');
  if (shimmer) shimmer.remove();
  const body = card.querySelector('.advisor-live-body');
  if (body) body.remove();
  // 摘要 + 动作区 · 用户 2026-07-28: coop 模式 suppressAnswer (施工单全文在下方就位卡 · 这里只留展开过程)
  if (!info.suppressAnswer) {
    const answer = document.createElement('div');
    answer.className = 'advisor-answer';
    // 卷八十一续 · replan 输出是 markdown (施工单: 标题/表格/列表) · mdRender 渲染不裸 textContent
    const raw = (info.preview || '').trim() || '(顾问输出为空)';
    answer.innerHTML = (typeof mdRender === 'function') ? mdRender(raw) : escHtml(raw);
    card.appendChild(answer);
  }
  const actions = document.createElement('div');
  actions.className = 'advisor-actions';
  card.appendChild(actions);
  // 展开顾问过程: sub id 优先 info 给的 · 没有则 fetch /api/advisor/status 兜底
  const renderTraceBtn = (subId) => {
    if (!subId || actions.querySelector('.adv-btn')) return;
    const btn = document.createElement('button');
    btn.className = 'adv-btn';
    btn.innerHTML = '<i class="ri-file-list-3-line"></i> 展开顾问过程';
    btn.addEventListener('click', () => advisorTraceToggle(card, subId, btn));
    actions.insertBefore(btn, actions.firstChild);
  };
  if (info.subId) {
    renderTraceBtn(info.subId);
  } else {
    fetch('/api/advisor/status', { headers: { 'Authorization': 'Bearer ' + token } })
      .then(r => r.ok ? r.json() : null)
      .then(j => { if (j && j.sub_session_id) renderTraceBtn(j.sub_session_id); })
      .catch(() => {});
  }
  // 标签闪烁: 用户 切到别的 tab 时 · 顾问跑完闪 title 让他知道 (现有基础设施 · 切回来自动停)
  if (typeof _flashTitle === 'function' && document.hidden) {
    try { _flashTitle(info.ok === false ? '[🧭 顾问未果]' : '[🧭 顾问就位]'); } catch {}
  }
  return card;
}

// ── 过程回放 · fetch /api/advisor/trace → 时间线 ──
function advisorTraceToggle(card, subId, btn) {
  const existing = card.querySelector('.advisor-trace');
  if (existing) { existing.remove(); btn.innerHTML = '<i class="ri-file-list-3-line"></i> 展开顾问过程'; return; }
  btn.innerHTML = '<i class="ri-loader-4-line adv-spin"></i> 加载中…';
  fetch('/api/advisor/trace?sub=' + encodeURIComponent(subId), { headers: { 'Authorization': 'Bearer ' + token } })
    .then(r => r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status)))
    .then(j => {
      btn.innerHTML = '<i class="ri-arrow-up-s-line"></i> 收起过程';
      const trace = document.createElement('div');
      trace.className = 'advisor-trace';
      const nodes = (j && j.nodes) || [];
      if (!nodes.length) {
        trace.innerHTML = '<div style="color:var(--dim);text-align:center;padding:6px 0;">(过程记录为空)</div>';
      }
      nodes.forEach((node) => {
        const row = document.createElement('div');
        if (node.kind === 'meta') return;  // 模型信息 head chip 已显示
        if (node.kind === 'task') {
          row.className = 'trace-row';
          row.innerHTML = '<span class="trace-dot task"><i class="ri-chat-1-line"></i></span>' +
            '<div class="trace-body"><b>任务</b><div class="think-text">' + escHtml(node.text || '') + '</div></div>';
        } else if (node.kind === 'think') {
          row.className = 'trace-row';
          row.innerHTML = '<span class="trace-dot think"><i class="ri-mind-map"></i></span>' +
            '<div class="trace-body"><b>思考</b><div class="think-text">' + escHtml(node.text || '') + '</div></div>';
        } else if (node.kind === 'tool') {
          row.className = 'trace-row' + (node.ok === false ? ' tool-fail' : '');
          const mark = node.ok === true ? '✓ ' : (node.ok === false ? '✗ ' : '');
          row.innerHTML = '<span class="trace-dot tool"><i class="ri-tools-line"></i></span>' +
            '<div class="trace-body"><span class="tool-name">' + mark + escHtml(node.name || '?') + '</span>' +
            (node.args ? ' <span class="tool-args">' + escHtml(node.args) + '</span>' : '') +
            (node.result ? '<div class="tool-result">' + escHtml(node.result) + '</div>' : '') + '</div>';
        } else if (node.kind === 'answer') {
          row.className = 'trace-row';
          row.innerHTML = '<span class="trace-dot final"><i class="ri-check-line"></i></span>' +
            '<div class="trace-body"><b>给出结论</b><div class="trace-answer-text">' + escHtml(node.text || '') + '</div></div>';
        } else {
          return;
        }
        trace.appendChild(row);
      });
      card.appendChild(trace);
      scrollToBottom(card.closest('.chat-messages') || card.parentElement, { force: false });
    })
    .catch((e) => {
      btn.innerHTML = '<i class="ri-error-warning-line"></i> 回放加载失败 · 重试';
      console.warn('advisor trace failed', e);
    });
}

// ── 协同模式施工单就位卡 (blueprint_done) ──
// info.historical=true → 历史重建版: 尾部静态"已按此单施工" · subId 带「展开顾问过程」按钮
function advisorBlueprintCard(state, info) {
  if (!state || !state.$container) return null;
  info = info || {};
  const div = document.createElement('div');
  div.className = 'msg advisor-card blueprint-card';
  div.innerHTML =
    '<div class="advisor-head">' +
      '<i class="ri-compass-discover-fill"></i>' +
      '<span>顾问协同 · 施工单已就位</span>' +
      (info.modelLabel ? '<span class="model-chip">' + escHtml(info.modelLabel) + '</span>' : '') +
    '</div>' +
    '<div class="blueprint-body"></div>' +
    (info.historical
      ? '<div class="blueprint-flow"><i class="ri-check-line"></i> 执行者已按此单施工</div>'
      : '<div class="blueprint-flow"><i class="ri-arrow-right-line"></i> 执行者 <b>按单施工中</b>…</div>');
  // 用户 2026-07-29 · 施工单是 markdown (标题/列表/表格) · 用 mdRender 渲染别裸 textContent
  div.querySelector('.blueprint-body').innerHTML = mdRender((info.text || '').trim() || '(施工单为空)');
  if (info.historical && info.subId) {
    const actions = document.createElement('div');
    actions.className = 'advisor-actions';
    const btn = document.createElement('button');
    btn.className = 'adv-btn';
    btn.innerHTML = '<i class="ri-file-list-3-line"></i> 展开顾问过程';
    btn.addEventListener('click', () => advisorTraceToggle(div, info.subId, btn));
    actions.appendChild(btn);
    div.appendChild(actions);
  }
  state.$container.appendChild(div);
  scrollToBottom(state.$container, { force: false });
  return div;
}

// ── 协同模式自动验收卡 (review_done · 方案 B 2026-07-28) ──
// verdict=PASS 绿 / FAIL 橙 · 意见全文 body · subId 带「展开顾问过程」· historical=历史重建版
function advisorReviewCard(state, info) {
  if (!state || !state.$container) return null;
  info = info || {};
  const pass = info.verdict === 'PASS';
  const div = document.createElement('div');
  div.className = 'msg advisor-card review-card ' + (pass ? 'review-pass' : 'review-fail');
  const flow = pass
    ? '<div class="blueprint-flow"><i class="ri-shield-check-line"></i> 对照施工单逐条验过 · 交付成立</div>'
    : (info.round >= 2
      ? '<div class="blueprint-flow"><i class="ri-alert-line"></i> 已达修正上限 · 顾问保留以上意见 · 用户 过目</div>'
      : '<div class="blueprint-flow"><i class="ri-tools-line"></i> 意见已注入 · 执行者自动修正了一轮</div>');
  div.innerHTML =
    '<div class="advisor-head">' +
      '<i class="' + (pass ? 'ri-checkbox-circle-fill' : 'ri-error-warning-fill') + '"></i>' +
      '<span>' + (pass ? '顾问验收通过' : '顾问验收未通过') +
        (info.round && info.round > 1 ? ' · 第 ' + info.round + ' 次验收' : '') + '</span>' +
      (info.modelLabel ? '<span class="model-chip">' + escHtml(info.modelLabel) + '</span>' : '') +
    '</div>' +
    '<div class="blueprint-body"></div>' +
    flow;
  // 用户 2026-07-29 · 验收意见是 markdown (表格/列表/加粗) · 用 mdRender 渲染别裸 textContent
  div.querySelector('.blueprint-body').innerHTML = mdRender((info.text || '').trim() || '(顾问未给出意见全文)');
  if (info.subId) {
    const actions = document.createElement('div');
    actions.className = 'advisor-actions';
    const btn = document.createElement('button');
    btn.className = 'adv-btn';
    btn.innerHTML = '<i class="ri-file-list-3-line"></i> 展开顾问过程';
    btn.addEventListener('click', () => advisorTraceToggle(div, info.subId, btn));
    actions.appendChild(btn);
    div.appendChild(actions);
  }
  state.$container.appendChild(div);
  scrollToBottom(state.$container, { force: false });
  return div;
}

// ── SSE 断流自愈 · review 超时 polling (用户 2026-07-29) ──
// review 跑 1-3 分钟 · 切标签页/网络波动 → review_done SSE 事件丢失 → live 卡永远转。
// 120s 后每 4s 查 /api/advisor/status · 拿到 finish 结果 → 构造等效 review_done 收尾。
async function _advisorReviewPoll(state) {
  if (!state._advisorCard) return; // 已被 review_done 正常收尾
  try {
    const resp = await fetch('/api/advisor/status', {
      headers: { 'Authorization': 'Bearer ' + token }
    });
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const data = await resp.json();
    if (data.active) {
      // 顾问还在跑 · 4s 后再查
      advisorCardTick(state._advisorCard, '验收交付中… (SSE 重连中 · 顾问仍在审查)');
      state._advisorCard._reviewPollTimer = setTimeout(() => _advisorReviewPoll(state), 4000);
      return;
    }
    if (data.ok !== undefined && data.finished_at) {
      // 完成了 · 用 live 文件里的结果收尾
      if (state._advisorCard._reviewPollTimer) {
        clearTimeout(state._advisorCard._reviewPollTimer);
        state._advisorCard._reviewPollTimer = null;
      }
      const _vd = data.verdict || (data.ok ? 'PASS' : 'FAIL');
      advisorCardFinish(state._advisorCard, {
        ok: _vd === 'PASS',
        label: _vd === 'PASS' ? '顾问验收通过' : '顾问验收未通过',
        modelLabel: data.model_label || '', preview: '', suppressAnswer: true });
      state._advisorCard = null;
      advisorReviewCard(state, { verdict: _vd, text: data.text || '',
        modelLabel: data.model_label || '', round: data.round || 1,
        subId: data.sub_session_id || '' });
      addSys('📡 验收卡已自动恢复 (SSE 断流 · 从服务端状态接回)', state.$container);
      return;
    }
    // 文件被清了/异常 · 10s 后再试一次
    state._advisorCard._reviewPollTimer = setTimeout(() => _advisorReviewPoll(state), 10000);
  } catch (e) {
    // 网络也断了 · 10s 后重试
    if (state._advisorCard) {
      state._advisorCard._reviewPollTimer = setTimeout(() => _advisorReviewPoll(state), 10000);
    }
  }
}

// ── 历史重建 · 简化版顾问结论卡 (用户 2026-07-28: 刷新后顾问框不能消失) ──
// 跟实时链形态对齐: 这张只留 head + 展开过程 · 施工单全文在下方的就位卡
function advisorCardRenderHistorical(state, info) {
  if (!state || !state.$container) return null;
  info = info || {};
  const div = document.createElement('div');
  div.className = 'msg advisor-card';
  div.innerHTML =
    '<div class="advisor-head">' +
      '<i class="ri-user-star-fill"></i>' +
      '<span>' + (info.ok === false ? '顾问没能给出结论' : '顾问已给出结论') + '</span>' +
      (info.modelLabel ? '<span class="model-chip">' + escHtml(info.modelLabel) + '</span>' : '') +
    '</div>';
  if (info.subId) {
    const actions = document.createElement('div');
    actions.className = 'advisor-actions';
    const btn = document.createElement('button');
    btn.className = 'adv-btn';
    btn.innerHTML = '<i class="ri-file-list-3-line"></i> 展开顾问过程';
    btn.addEventListener('click', () => advisorTraceToggle(div, info.subId, btn));
    actions.appendChild(btn);
    div.appendChild(actions);
  }
  state.$container.appendChild(div);
  return div;
}

function renderConfirmCard(data, state) {
  if (!state || !state.$container) return null;
  if (!data || !data.tool_call_id) return null;

  // 卷七十四 (2026-06-12) · 用户 钉死: 改回对话流内联 · 不要弹窗/全屏遮罩
  // 卷七十三 P0-2 的满屏遮罩在 daemon 重启 / turn 中断时收不到 confirm_resolved → backdrop 残留 fixed 层锁死整页
  // 保留: risk / mitigation / 4-5 按钮 / 拒绝备注框 (用户 12:05 钉死的)
  const wrap = document.createElement('div');
  wrap.className = 'msg confirm-card';
  wrap.dataset.toolCallId = data.tool_call_id;
  wrap.dataset.turnId = data.turn_id || '';

  // 标题: ⚠ Daemonkey 申请执行 <tool>
  const head = _confirmEl('div', 'confirm-head',
    '<span class="confirm-icon">⚠</span> <strong>Daemonkey 申请执行 <code class="confirm-tool"></code></strong>'
  );
  head.querySelector('.confirm-tool').textContent = data.tool_name || '?';
  wrap.appendChild(head);

  // tier 原因 (例 "CONFIRM tier · 默认需要 用户 确认")
  if (data.tier_reason) {
    const tr = _confirmEl('div', 'confirm-tier');
    tr.textContent = data.tier_reason;
    wrap.appendChild(tr);
  }

  // args 摘要 + 折叠详情
  if (data.args_summary || data.args_preview) {
    const det = document.createElement('details');
    det.className = 'confirm-args';
    const sumEl = document.createElement('summary');
    sumEl.className = 'confirm-args-summary';
    sumEl.textContent = '调用细节: ' + (data.args_summary || data.tool_name || '');
    det.appendChild(sumEl);
    if (data.args_preview) {
      const pre = document.createElement('pre');
      pre.className = 'confirm-args-pre';
      pre.textContent = data.args_preview;
      det.appendChild(pre);
    }
    wrap.appendChild(det);
  }

  // 风险说明 (用户 12:05 反馈钉死必须有这块)
  const risk = (data.risk_explanation || '').trim();
  const riskBlock = _confirmEl('div', risk ? 'confirm-block confirm-risk' : 'confirm-block confirm-risk confirm-block-empty');
  const riskLabel = _confirmEl('div', 'confirm-block-label');
  riskLabel.innerHTML = risk ? '<i class="ri-clipboard-fill"></i> 风险 (Daemonkey 说明)' : '<i class="ri-clipboard-fill"></i> 风险 — Daemonkey 未说明 ⚠';
  const riskBody = _confirmEl('div', 'confirm-block-body');
  riskBody.textContent = risk || 'Daemonkey 没填 risk_explanation 字段 · 你不知道这刀下去会影响什么 · 谨慎批准';
  riskBlock.appendChild(riskLabel);
  riskBlock.appendChild(riskBody);
  wrap.appendChild(riskBlock);

  // 规避策略 (用户 12:05 反馈钉死必须有这块)
  const mit = (data.mitigation || '').trim();
  const mitBlock = _confirmEl('div', mit ? 'confirm-block confirm-mit' : 'confirm-block confirm-mit confirm-block-empty');
  const mitLabel = _confirmEl('div', 'confirm-block-label');
  mitLabel.innerHTML = mit ? '<i class="ri-shield-fill"></i> 规避策略 (Daemonkey 说明)' : '<i class="ri-shield-fill"></i> 规避策略 — Daemonkey 未说明 ⚠';
  const mitBody = _confirmEl('div', 'confirm-block-body');
  mitBody.textContent = mit || 'Daemonkey 没填 mitigation 字段 · 出问题时它没想好怎么收场 · 谨慎批准';
  mitBlock.appendChild(mitLabel);
  mitBlock.appendChild(mitBody);
  wrap.appendChild(mitBlock);

  // 按钮组 (supports_trust 时 5 按钮 · 否则 2 按钮)
  const btns = _confirmEl('div', 'confirm-buttons');
  const all = [
    { d: 'approve_once', label: '<i class="ri-check-fill"></i> 只这次', cls: 'confirm-btn-approve' },
  ];
  if (data.supports_trust) {
    all.push(
      { d: 'trust_30min', label: '⏰ 信任 30min', cls: 'confirm-btn-trust' },
      { d: 'trust_24h', label: '<i class="ri-calendar-fill"></i> 信任 24h', cls: 'confirm-btn-trust' },
      { d: 'trust_permanent', label: '♾ 永久信任 ⚠', cls: 'confirm-btn-trust-perm' },
    );
  }
  all.push({ d: 'deny', label: '<i class="ri-close-fill"></i> 拒绝', cls: 'confirm-btn-deny' });

  for (const item of all) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'confirm-btn ' + item.cls;
    b.innerHTML = item.label;  // label 含 <i class="ri-*"> · 必须 innerHTML 解析 (hard-code 安全 · 非用户输入)
    b.dataset.decision = item.d;
    b.addEventListener('click', () => onConfirmClick(wrap, data, item.d));
    btns.appendChild(b);
  }
  wrap.appendChild(btns);

  // 拒绝备注框 (默认隐藏 · 点拒绝展开)
  const denyArea = document.createElement('div');
  denyArea.className = 'confirm-deny-reason';
  denyArea.hidden = true;
  const denyLabel = document.createElement('label');
  denyLabel.textContent = '拒绝原因 (可选 · 告诉 Daemonkey 为什么·让它换思路):';
  const denyInput = document.createElement('textarea');
  denyInput.className = 'confirm-reason-input';
  denyInput.rows = 2;
  denyInput.placeholder = '例如: 这个文件我自己来动 · 你换个方式 / 这条命令风险描述不够清晰 · 重新讲一下';
  const denyActions = _confirmEl('div', 'confirm-deny-actions');
  const denyConfirmBtn = document.createElement('button');
  denyConfirmBtn.type = 'button';
  denyConfirmBtn.className = 'confirm-btn confirm-btn-deny-final';
  denyConfirmBtn.textContent = '确认拒绝';
  const denyCancelBtn = document.createElement('button');
  denyCancelBtn.type = 'button';
  denyCancelBtn.className = 'confirm-btn confirm-btn-cancel';
  denyCancelBtn.textContent = '取消';
  denyActions.appendChild(denyConfirmBtn);
  denyActions.appendChild(denyCancelBtn);
  denyArea.appendChild(denyLabel);
  denyArea.appendChild(denyInput);
  denyArea.appendChild(denyActions);
  wrap.appendChild(denyArea);

  denyConfirmBtn.addEventListener('click', () => {
    const r = (denyInput.value || '').trim();
    postConfirmDecision(wrap, data, 'deny', r);
  });
  denyCancelBtn.addEventListener('click', () => {
    denyArea.hidden = true;
    wrap.querySelectorAll('.confirm-btn').forEach((b) => {
      if (!b.classList.contains('confirm-btn-deny-final') && !b.classList.contains('confirm-btn-cancel')) {
        b.disabled = false;
      }
    });
  });

  // 状态行
  const status = _confirmEl('div', 'confirm-status');
  status.textContent = '等待 用户 决议 · 30min 后自动拒绝';
  wrap.appendChild(status);

  // 直接进消息流末尾 · 无遮罩 (不会锁死页面) · 滚到视野确保 用户 看得到
  state.$container.appendChild(wrap);
  scrollToBottom(state.$container);
  try { wrap.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (e) { /* noop */ }
  return wrap;
}

function onConfirmClick(card, data, decision) {
  if (decision === 'deny') {
    // 展开备注框 · 禁用其他按钮 (防误点 approve)
    const dr = card.querySelector('.confirm-deny-reason');
    if (dr) dr.hidden = false;
    card.querySelectorAll('.confirm-btn').forEach((b) => {
      if (!b.classList.contains('confirm-btn-deny-final') && !b.classList.contains('confirm-btn-cancel')) {
        b.disabled = true;
      }
    });
    const ta = card.querySelector('.confirm-reason-input');
    if (ta) ta.focus();
    return;
  }
  postConfirmDecision(card, data, decision, '');
}

async function postConfirmDecision(card, data, decision, reason) {
  card.classList.add('confirm-card-submitting');
  const status = card.querySelector('.confirm-status');
  if (status) status.textContent = '提交中...';
  card.querySelectorAll('button').forEach((b) => (b.disabled = true));

  try {
    const turnId = data.turn_id || card.dataset.turnId || '';
    if (!turnId) throw new Error('missing turn_id');
    const resp = await fetch('/turns/' + encodeURIComponent(turnId) + '/confirm', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        tool_call_id: data.tool_call_id,
        decision,
        reason: reason || '',
      }),
    });
    if (!resp.ok) {
      const txt = await resp.text();
      throw new Error('HTTP ' + resp.status + ': ' + txt);
    }
    const result = await resp.json();
    collapseConfirmCard(card, decision, reason, false, result);
  } catch (e) {
    if (status) status.textContent = '提交失败: ' + (e && e.message ? e.message : String(e));
    card.classList.remove('confirm-card-submitting');
    card.querySelectorAll('button').forEach((b) => (b.disabled = false));
  }
}

function collapseConfirmCard(card, decision, reason, autoTimeout, result) {
  card.classList.remove('confirm-card-submitting');
  card.classList.add('confirm-card-resolved');

  // 卷七十三 P0-2 · 关闭中央模态 + 移除遮罩 + 把 inline 占位转成"已决议"记录条
  if (card.classList.contains('confirm-modal')) {
    if (card._backdrop && card._backdrop.parentNode) {
      card._backdrop.classList.remove('confirm-modal-backdrop-show');
      // 等遮罩淡出再 remove DOM
      setTimeout(() => { if (card._backdrop && card._backdrop.parentNode) card._backdrop.remove(); }, 200);
    }
    card.classList.remove('confirm-modal-show');
    // 模态本体延迟 remove · 让淡出动画跑完 · 同时把"已决议摘要" 渲染到 inline 占位上
    setTimeout(() => { if (card.parentNode === document.body) card.remove(); }, 200);
    // 把渲染目标切到占位行 (用户 滚消息流时这里留痕)
    if (card._placeholder) {
      const ph = card._placeholder;
      ph.innerHTML = '';  // 清空 "等待 + 重新打开" 内容
      ph.classList.add('confirm-placeholder-resolved');
      // 后续 collapseConfirmCard 剩余的渲染逻辑 (label / reason / trust note) 都 append 到 ph
      // 让 card 变成一个临时容器 · 渲染完 transfer 到 ph
      card.__renderInto = ph;
    }
  }

  const labelMap = {
    approve_once: '<i class="ri-check-fill"></i> 用户 批准 (只这次)',
    trust_30min: '⏰ 用户 批准 + 信任 30min',
    trust_24h: '<i class="ri-calendar-fill"></i> 用户 批准 + 信任 24h',
    trust_permanent: '♾ 用户 永久信任 ⚠',
    deny: '<i class="ri-close-fill"></i> 用户 拒绝',
  };
  let label = labelMap[decision] || decision;
  if (autoTimeout) label = '⏱ 超时 auto-deny (30min 未响应)';

  const toolName = (card.querySelector('.confirm-tool') || {}).textContent || '';
  // 卷七十三 P0-2 · 模态版本: 渲染目标改成 inline 占位 (不再渲染到将要 remove 的 modal card)
  const renderHost = card.__renderInto || card;
  if (renderHost !== card) {
    // 模态模式: renderHost 已经在占位上 · card 不再展示内容
    card = renderHost;
  } else {
    card.innerHTML = '';
  }

  const line = _confirmEl('div', 'confirm-resolved-line');
  const lbl = _confirmEl('span', 'confirm-resolved-label');
  lbl.innerHTML = label;  // labelMap 值含 <i class="ri-*"> · hard-code 安全
  line.appendChild(lbl);

  const tn = _confirmEl('span', 'confirm-resolved-tool');
  tn.textContent = ' · ' + toolName;
  line.appendChild(tn);

  if (reason) {
    const r = _confirmEl('span', 'confirm-resolved-reason');
    r.textContent = ' · 备注: ' + reason;
    line.appendChild(r);
  }
  card.appendChild(line);

  if (result && result.applied_trust) {
    const at = result.applied_trust;
    if (at.ok === true) {
      const note = _confirmEl('div', 'confirm-resolved-note confirm-resolved-note-ok');
      const dur = at.permanent ? '永久' : (at.minutes ? at.minutes + 'min' : '');
      let expTxt = '';
      if (!at.permanent && at.expires_at) {
        try {
          // expires_at 是 add_trusted 返回的 ISO 字符串 (例 '2026-05-26T01:46:22')
          const d = new Date(at.expires_at);
          if (!isNaN(d.getTime())) {
            expTxt = ' · 至 ' + d.toLocaleString('zh-CN', { hour12: false });
          }
        } catch (e) { /* noop */ }
      }
      note.innerHTML = '<i class="ri-check-fill"></i> 已写入 trusted_commands: 「' + (at.pattern || '?') + '」· ' + dur + expTxt;
      card.appendChild(note);
    } else if (at.ok === false) {
      const note = _confirmEl('div', 'confirm-resolved-note confirm-resolved-note-warn');
      if (at.supports_trust === false) {
        note.textContent = '⚠ ' + (at.note || '');
      } else {
        let msg = '⚠ trust 写入失败: ' + (at.error || '未知错误');
        if (at.attempted_pattern) {
          msg += ' · 尝试 pattern=「' + at.attempted_pattern + '」';
        }
        if (at.note) {
          msg += '\n' + at.note;
        }
        note.style.whiteSpace = 'pre-wrap';
        note.textContent = msg;
      }
      card.appendChild(note);
    }
  }
}

// ─────────────────────────────────────────────────────────
// 卷三十 · 三栏左右拖拽 resize
// ─────────────────────────────────────────────────────────
(function initColResizers() {
  const STORE_NAV = 'Daemonkey_ui_nav_w';
  const STORE_CHAT = 'Daemonkey_ui_chat_w';
  const NAV_MIN = 140, NAV_MAX = 360;
  const CHAT_MIN = 280, CHAT_MAX = 800;

  // 从 localStorage 恢复（手机端跳过 · 否则 CSS var 会覆盖手机响应式）
  function applyStored() {
    if (window.innerWidth <= 900) return;
    const nw = parseInt(localStorage.getItem(STORE_NAV) || '0', 10);
    const cw = parseInt(localStorage.getItem(STORE_CHAT) || '0', 10);
    if (nw >= NAV_MIN && nw <= NAV_MAX) {
      document.documentElement.style.setProperty('--nav-w', nw + 'px');
    }
    if (cw >= CHAT_MIN && cw <= CHAT_MAX) {
      document.documentElement.style.setProperty('--chat-w', cw + 'px');
    }
  }

  function attach(handle) {
    handle.addEventListener('mousedown', (e) => {
      if (window.innerWidth <= 900) return;
      e.preventDefault();
      handle.classList.add('dragging');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';

      const side = handle.dataset.side; // 'left' or 'right'
      const startX = e.clientX;
      const layout = document.querySelector('.main-layout');
      const rect = layout.getBoundingClientRect();
      const cs = getComputedStyle(document.documentElement);
      const startNav = parseFloat(cs.getPropertyValue('--nav-w')) || 220;
      const startChat = parseFloat(cs.getPropertyValue('--chat-w')) || 400;

      function onMove(ev) {
        const dx = ev.clientX - startX;
        if (side === 'left') {
          // 向右拖 → nav 变宽
          const next = Math.max(NAV_MIN, Math.min(NAV_MAX, startNav + dx));
          document.documentElement.style.setProperty('--nav-w', next + 'px');
        } else {
          // 右 resizer：向左拖 → chat 变宽
          const next = Math.max(CHAT_MIN, Math.min(CHAT_MAX, startChat - dx));
          document.documentElement.style.setProperty('--chat-w', next + 'px');
        }
      }
      function onUp() {
        handle.classList.remove('dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        const cs2 = getComputedStyle(document.documentElement);
        const finalNav = parseInt(cs2.getPropertyValue('--nav-w'), 10);
        const finalChat = parseInt(cs2.getPropertyValue('--chat-w'), 10);
        if (Number.isFinite(finalNav)) localStorage.setItem(STORE_NAV, String(finalNav));
        if (Number.isFinite(finalChat)) localStorage.setItem(STORE_CHAT, String(finalChat));
      }
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });

    // 双击 reset 到默认
    handle.addEventListener('dblclick', () => {
      if (window.innerWidth <= 900) return;
      const side = handle.dataset.side;
      if (side === 'left') {
        document.documentElement.style.removeProperty('--nav-w');
        localStorage.removeItem(STORE_NAV);
      } else {
        document.documentElement.style.removeProperty('--chat-w');
        localStorage.removeItem(STORE_CHAT);
      }
    });
  }

  document.querySelectorAll('.col-resizer').forEach(attach);
  applyStored();
  window.addEventListener('resize', () => {
    if (window.innerWidth <= 900) {
      // 进入手机视图 · 清掉 inline style 让 media query 生效
      // 但不动 localStorage · 之后回桌面再恢复
      document.documentElement.style.removeProperty('--nav-w');
      document.documentElement.style.removeProperty('--chat-w');
    } else {
      applyStored();
    }
  });
})();

// ─────────────────────────────────────────────────────────
// 卷二十九 · 顶栏模型切换器
// ─────────────────────────────────────────────────────────
// 卷四十一 · 重启 / 关闭 daemon · 装载新代码 / 摆脱卡死 / 清空内存
// ─────────────────────────────────────────────────────────
// 卷四十六 续 14 补丁 III + V · 2026-05-26 · Daemonkey 调 request_restart 后 daemon 自爆 ·
// chat.js 自动 poll 等子进程接管端口 · 起来后:
//   1. _loadSessionHistory reload 当前 session (拿到 inject 的 system notice +
//      follow_up turn 已落档的内容)
//   2. _maybeStartPoll → 每 3s reload 看 background turn 跑完没 · 跑完自动停
//      (复用 wish-3fef4bc7 现成机制 · 用户 不用 F5)
// 内部 timeline (跟 request_restart 工具 _trigger_shutdown_async 对齐):
//   T+0    工具 return · 这函数 fire
//   T+0-2  老 daemon 还活着 (delay_sec=2 给 tool result → LLM → session 落档窗口)
//   T+2    daemon 启 spawn 子进程
//   T+2-3.5  子进程绑端口窗口 (parent sleep 1.5s)
//   T+3.5+ parent os._exit · 端口接管完成
//   → 我们 sleep 3s 再开始 poll · 避免老 daemon 还在时误判 alive
async function _waitForBackgroundTurn(sid, timeoutSec = 60) {
  // 轮询 /sessions/{sid}/background_turn_status · 等 background turn 完成
  // 返 'completed' | 'failed' | 'none' | 'timeout'
  const deadline = Date.now() + timeoutSec * 1000;
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`/sessions/${encodeURIComponent(sid)}/background_turn_status`, {
        headers: { 'Authorization': 'Bearer ' + token },
      });
      if (r.ok) {
        const data = await r.json();
        if (data.status === 'completed' || data.status === 'failed' || data.status === 'none') {
          return data.status;
        }
      }
    } catch (e) { /* daemon 还没完全起来 · 继续等 */ }
    await new Promise(r => setTimeout(r, 500));
  }
  return 'timeout';
}

async function waitForDaemonAfterRestartTool(state) {
  if (!token) return;
  // 这期间锁住输入 · 防止 用户 发新 message 打到 dead daemon
  // (finally 块会先 reset pending=false · 但 daemon 还没起 · 必须重锁)
  const sidGuard = (state && state.sessionId) || sessionId;
  if (sidGuard === sessionId) {
    setInputLocked(true);
    showToolProgress(true);
    setToolProgressText('daemon 重启中 · 等子进程接管端口…');
  }
  // 等 daemon 自爆 + 子进程接管窗口 · 之前 poll 会拿到老 daemon 假阳性 alive
  await new Promise(r => setTimeout(r, 3000));
  let alive = false;
  let lastErr = '';
  for (let i = 0; i < 60; i++) {
    await new Promise(r => setTimeout(r, 500));
    try {
      const r = await fetch(`/reload-soul`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
      });
      if (r.ok) { alive = true; break; }
      lastErr = `HTTP ${r.status}`;
    } catch (e) { lastErr = e.message || 'fetch failed'; }
  }
  const $r = document.getElementById('restartBtn');
  const $s = document.getElementById('shutdownBtn');
  if ($r) { $r.classList.remove('is-restarting'); $r.disabled = false; }
  if ($s) { $s.disabled = false; }
  if (state) {
    state._expectingDaemonRestart = false;
    state.pending = false;
  }
  if (alive) {
    try { await loadCurrentModel(); } catch (e) {}
    // 拿当前 session id · reload 历史 + 启 polling
    const sid = (state && state.sessionId) || sessionId;
    if (sid) {
      if (sid === sessionId) {
        // 重启确认 alive · 但续写可能还在跑 → 保持锁定 · 别让 用户 这时发消息打进半截 turn
        setInputLocked(true);
        showToolProgress(true);
        setToolProgressText('Daemonkey 重启完成 · 正在续写之前的任务…');
      }
      // wish-83fe7c7b 补丁: 等 background turn 完成再加载历史
      // 否则 daemon 热重启太快 · background turn 还没跑完就加载到旧快照
      // 卷五十六: 拿到 bg 结果 · 决定后续探测窗口长度 + 失败可见
      const bg = await _waitForBackgroundTurn(sid);
      try { await _loadSessionHistory(sid); } catch (e) {}
      // 卷五十六 · 治本: 单次探测改带重试探测 · 期间保持锁定 · 只有窗口内确认没有 active turn 才解锁。
      //   bg='timeout' = 续写还在跑(>60s) → 长窗口·必抓到; 其它(completed/failed/none) → 短兜底窗口
      //   (防老 daemon 假阳性 alive 误报 / 链式重启间隙 turn 晚注册)。
      const probeWindow = (bg === 'timeout') ? 30000 : 4000;
      let polling = false;
      try { polling = await _probeAndStartPoll(_sessions[sid], probeWindow); } catch (e) {}
      // 探测没抓到 active turn = 确实空闲了 · 这才解锁 (默认锁定 · 不默认放行)
      if (sid === sessionId && !polling) {
        pending = false;
        setSendButtonState('idle');
        setInputLocked(false);
        showToolProgress(false);
        if (bg === 'failed') {
          addSys('⚠ Daemonkey 续写这一轮中途出错了 (resume turn failed) · 看 data/daemon.err · 直接重发消息可以继续', state.$container);
        }
      }
    } else {
      addSys('<i class="ri-checkbox-circle-fill"></i> daemon 已重启 · 新代码已装载 · 可以继续派活了', state && state.$container);
    }
  } else {
    addSys(`⚠ 30 秒没等到新 daemon (last: ${lastErr}) · 看 data/daemon.err · 或 GUI 启动器手动重启`, state && state.$container);
  }
}

async function restartDaemon() {
  if (!token) { addSys('⚠ 还没设 token · 不能重启 daemon'); return; }
  // 卷四十六 IV (2026-05-26): 重启对话框加 follow_up_message · 用户 痛点根治
  //   原来 confirm 只能 yes/no · 重启完只 inject system notice · Daemonkey 不会自动续场
  //   现在 DaemonkeyPrompt 让 用户 一并填"重启完想让我做啥" · 串到 /restart-daemon body
  //   留空 = 跟老逻辑一样 · 只重启 · 不跑 background turn
  const followUp = await DaemonkeyPrompt({
    title: '重启 daemon 进程?',
    message: '会杀掉当前 daemon · 自动起新的 (装载新代码 + 清空进程内存)。\n持久化的 session 不会丢——重启后还能继续上次对话。\n大约 5-10 秒。\n\n[可选] 重启完想让我做啥? 留空 = 只重启 · 不自动续场',
    placeholder: '例: 重启完帮我验证 /digest 是不是真的返回了新数据',
    okText: '重启',
    cancelText: '不了',
  });
  if (followUp === null) return;
  const followUpMessage = (followUp || '').trim() || null;

  const $r = document.getElementById('restartBtn');
  const $s = document.getElementById('shutdownBtn');
  if ($r) { $r.classList.add('is-restarting'); $r.disabled = true; }
  if ($s) { $s.disabled = true; }
  if (followUpMessage) {
    const preview = followUpMessage.length > 60 ? followUpMessage.slice(0, 60) + '…' : followUpMessage;
    addSys(`<i class="ri-refresh-fill"></i> 正在重启 daemon · 请等 ~5 秒 · 起来后 Daemonkey 会自动跑:「${preview}」`);
  } else {
    addSys('<i class="ri-refresh-fill"></i> 正在重启 daemon · 请等 ~5 秒 (子进程绑端口的窗口期)…');
  }
  try {
    const body = {};
    if (followUpMessage) body.follow_up_message = followUpMessage;
    if (sessionId) body.session_id = sessionId;
    await fetch(`/restart-daemon`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });
  } catch (e) {}
  let alive = false;
  let lastErr = '';
  for (let i = 0; i < 60; i++) {
    await new Promise(r => setTimeout(r, 500));
    try {
      const r = await fetch(`/reload-soul`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
      });
      if (r.ok) { alive = true; break; }
      lastErr = `HTTP ${r.status}`;
    } catch (e) { lastErr = e.message || 'fetch failed'; }
  }
  if ($r) { $r.classList.remove('is-restarting'); $r.disabled = false; }
  if ($s) { $s.disabled = false; }
  if (alive) {
    if (followUpMessage) {
      addSys('<i class="ri-checkbox-circle-fill"></i> daemon 已重启 · 新代码已装载 · Daemonkey 在后台跑你交代的事 · 跑完会落档到当前 session · 翻一下消息列表就能看到结果');
    } else {
      addSys('<i class="ri-checkbox-circle-fill"></i> daemon 已重启 · 新代码已装载 · 可以继续派活了');
    }
    try { await loadCurrentModel(); } catch (e) {}
  } else {
    addSys(`⚠ 30 秒没等到新 daemon 起来 (last: ${lastErr}) · 看 data/daemon.err · 或 GUI 启动器手动重启`);
  }
}

async function shutdownDaemon() {
  if (!token) { addSys('⚠ 还没设 token · 不能关 daemon'); return; }
  const ok = await DaemonkeyConfirm({
    title: '关闭 daemon 进程?',
    message: '会杀掉当前 daemon · **不**起新进程。\n之后要回来工作 · 双击 start.bat 走 GUI 启动器。\n持久化的 session 不会丢。',
    okText: '关闭',
    cancelText: '不了',
  });
  if (!ok) return;
  const $r = document.getElementById('restartBtn');
  const $s = document.getElementById('shutdownBtn');
  if ($r) $r.disabled = true;
  if ($s) $s.disabled = true;
  addSys('🌙 正在关闭 daemon · 之后没有 Daemonkey 在跑了');
  try {
    await fetch(`/shutdown-daemon`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` },
    });
  } catch (e) {}
  await new Promise(r => setTimeout(r, 1500));
  let stillUp = false;
  try {
    const r = await fetch(`/reload-soul`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` },
    });
    if (r.ok) stillUp = true;
  } catch (e) {}
  if (stillUp) {
    addSys('⚠ daemon 似乎没关掉 · 可能 GUI 启动器拉了 supervisor · 去托盘里看看');
    if ($r) $r.disabled = false;
    if ($s) $s.disabled = false;
  } else {
    addSys('🌙 daemon 已关 · 双击 start.bat 起 GUI 启动器再开张');
  }
}

// ─────────────────────────────────────────────────────────
// 卷四十四 G · wish-196213df · UI 回档按钮
// Daemonkey 改崩了 daemon · 用户 一键 git reset --hard <prev_commit> + 重启
// ─────────────────────────────────────────────────────────
async function rollbackDaemon() {
  if (!token) { addSys('⚠ 还没设 token · 不能回档'); return; }

  let info;
  try {
    const r = await fetch(`/rollback`, {
      method: 'GET',
      headers: { 'Authorization': `Bearer ${token}` },
    });
    if (!r.ok) {
      addSys(`⚠ 拉回档候选失败 · HTTP ${r.status}`);
      return;
    }
    info = await r.json();
  } catch (e) {
    addSys(`⚠ 拉回档候选失败 · ${e.message || e}`);
    return;
  }

  const cands = info.candidates || [];
  if (cands.length < 2) {
    addSys('⚠ 最近 commit 数少于 2 · 没法回档');
    return;
  }

  const lines = cands.map((c, i) => {
    const tag = i === 0 ? ' (当前 HEAD)' : '';
    const dateShort = (c.date || '').slice(0, 16).replace('T', ' ');
    return `  ${i + 1}. ${c.short} · ${dateShort}${tag}\n     ${c.msg}`;
  }).join('\n');
  const dirtyHint = info.dirty
    ? '\n\n⚠ 当前有未 commit 改动 · 回档前会自动 stash (用户 后悔可 git stash pop 恢复)'
    : '';
  const promptMsg =
    `当前分支: ${info.current_branch}\n最近 5 个 commits:\n\n${lines}` +
    `${dirtyHint}\n\n输入要回到的序号 (2-${cands.length} · 1=当前 HEAD 不动):`;

  const idxStr = await DaemonkeyPrompt({
    title: '<i class="ri-rewind-fill"></i> 回档 · 选目标 commit',
    message: promptMsg,
    placeholder: '比如 2',
    okText: '下一步',
    cancelText: '不了',
  });
  if (!idxStr) return;
  const idx = parseInt(String(idxStr).trim(), 10);
  if (isNaN(idx) || idx < 2 || idx > cands.length) {
    addSys(`⚠ 序号不合法 (要 2-${cands.length}) · 取消回档`);
    return;
  }
  const target = cands[idx - 1];

  const confirmMsg =
    `要从  ${cands[0].short} (${cands[0].msg.slice(0, 40)}…)\n` +
    `回到 ${target.short} (${target.msg.slice(0, 40)}…)\n\n` +
    `这会 git reset --hard · daemon 自动重启 · 大约 5-10 秒。\n` +
    (info.dirty ? '未 commit 改动会先 stash · 不会丢。\n\n' : '\n') +
    '[可选] 回档完想让我做啥? 留空 = 只回档 · 不自动续场';
  const followUp = await DaemonkeyPrompt({
    title: '<i class="ri-rewind-fill"></i> 确认回档?',
    message: confirmMsg,
    placeholder: '例: 回档完跑一遍 health check · 确认 X 还工作',
    okText: '回档',
    cancelText: '取消',
  });
  if (followUp === null) return;
  const followUpMessage = (followUp || '').trim() || null;

  const $r = document.getElementById('restartBtn');
  const $s = document.getElementById('shutdownBtn');
  const $b = document.getElementById('rollbackBtn');
  if ($b) { $b.classList.add('is-rolling'); $b.disabled = true; }
  if ($r) $r.disabled = true;
  if ($s) $s.disabled = true;

  if (followUpMessage) {
    const preview = followUpMessage.length > 60 ? followUpMessage.slice(0, 60) + '…' : followUpMessage;
    addSys(`<i class="ri-rewind-fill"></i> 回档到 ${target.short} 中 · daemon 即将重启 · 起来后 Daemonkey 会自动跑:「${preview}」`);
  } else {
    addSys(`<i class="ri-rewind-fill"></i> 回档到 ${target.short} 中 · daemon 即将重启…`);
  }
  let result;
  try {
    const body = {
      target_commit: target.sha,
      confirm: true,
      reason: '用户 clicked UI rollback',
    };
    if (followUpMessage) body.follow_up_message = followUpMessage;
    if (sessionId) body.session_id = sessionId;
    const r = await fetch(`/rollback`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });
    if (r.ok) {
      result = await r.json();
    } else {
      const t = await r.text();
      addSys(`⚠ 回档失败 · HTTP ${r.status} · ${t.slice(0, 200)}`);
      if ($b) { $b.classList.remove('is-rolling'); $b.disabled = false; }
      if ($r) $r.disabled = false;
      if ($s) $s.disabled = false;
      return;
    }
  } catch (e) {
    // POST 期间 daemon 已经 os._exit · fetch 报错是预期 · 继续等重启
  }

  let alive = false;
  let lastErr = '';
  for (let i = 0; i < 60; i++) {
    await new Promise(r => setTimeout(r, 500));
    try {
      const r = await fetch(`/reload-soul`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
      });
      if (r.ok) { alive = true; break; }
      lastErr = `HTTP ${r.status}`;
    } catch (e) { lastErr = e.message || 'fetch failed'; }
  }
  if ($b) { $b.classList.remove('is-rolling'); $b.disabled = false; }
  if ($r) $r.disabled = false;
  if ($s) $s.disabled = false;

  if (alive) {
    const stashHint = result && result.stashed
      ? `\n<i class="ri-archive-fill"></i> 改动已 stash (${result.stash_msg || ''}) · git stash pop 可恢复`
      : '';
    if (followUpMessage) {
      addSys(`<i class="ri-checkbox-circle-fill"></i> 已回档到 ${target.short} · daemon 已重启${stashHint}\n<i class="ri-robot-fill"></i> Daemonkey 在后台跑你交代的事 · 跑完落档到当前 session · 翻消息列表能看到`);
    } else {
      addSys(`<i class="ri-checkbox-circle-fill"></i> 已回档到 ${target.short} · daemon 已重启${stashHint}`);
    }
    try { await loadCurrentModel(); } catch (e) {}
  } else {
    addSys(`⚠ 30 秒没等到 daemon 起来 (last: ${lastErr}) · 看 data/daemon.err · 或 GUI 启动器手动重启`);
  }
}

let _modelMenuOpen = false;
let _modelOptions = [];

async function loadCurrentModel() {
  if (!token) {
    document.getElementById('modelNameLabel').textContent = '未连接';
    return;
  }
  try {
    const r = await fetch('/models', {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) {
      document.getElementById('modelNameLabel').textContent = '加载失败';
      return;
    }
    const data = await r.json();
    const current = data.current || {};
    _modelOptions = data.options || [];
    // 用户 2026-07-28 · 顾问协同 toggle 禁用判断的数据源 (当前模型=总监模型时禁用)
    window._currentModelId = current.model || '';
    window._currentConfigId = current.config_id || '';  // 会话记住模型 · 切标签恢复的比较基准
    window._directorModelId = (data.director && data.director.model) || '';
    if (typeof _advisorCoopRender === 'function') _advisorCoopRender();
    // 卷三十八 · 顶栏显示用 cfg.name (友好名) 优先 · fallback model id
    // 之前是 alias=cfg-xxx · 用户 反馈"丑·要显示模型名"
    let display = current.model || '?';
    const matched = _modelOptions.find(o => o.config_id === current.config_id || o.alias === current.config_id);
    if (matched && matched.name) display = matched.name;
    else if (current.model) display = current.model;
    document.getElementById('modelNameLabel').textContent = display;
    document.getElementById('modelSwitch').dataset.family = current.family || '';
    renderModelMenuList();
  } catch (e) {
    document.getElementById('modelNameLabel').textContent = 'offline';
  }
}

function renderModelMenuList() {
  const list = document.getElementById('modelMenuList');
  if (!list) return;
  if (_modelOptions.length === 0) {
    list.innerHTML = '<div class="model-menu-empty">没有可选模型</div>';
    return;
  }
  // 卷三十八 · 主标题用 cfg.name · 副标题用 model id · cfg-xxx 不再显示 (太丑)
  list.innerHTML = _modelOptions.map(opt => `
    <button class="model-menu-item${opt.current ? ' current' : ''}"
            onclick="switchModel('${jsStr(opt.alias)}')"
            data-family="${escHtml(opt.family)}">
      <div class="mmi-row1">
        <span class="mmi-alias">${escHtml(opt.name || opt.real_id)}</span>
        <span class="mmi-family">${escHtml(opt.family)}</span>
        ${opt.cache ? '<span class="mmi-cache" title="支持 cache · 省钱">💰</span>' : ''}
        ${opt.current ? '<span class="mmi-current">●</span>' : ''}
      </div>
      <div class="mmi-real">${escHtml(opt.real_id)}</div>
      <div class="mmi-note">${escHtml(opt.note || '')}</div>
    </button>
  `).join('');
}

function toggleModelMenu() {
  if (!_modelMenuOpen && _modelOptions.length === 0) {
    loadCurrentModel();
  }
  const menu = document.getElementById('modelMenu');
  _modelMenuOpen = !_modelMenuOpen;
  menu.classList.toggle('open', _modelMenuOpen);
}

async function switchModel(alias) {
  if (!token) return;
  try {
    const r = await fetch('/models/switch', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ model: alias }),
    });
    if (!r.ok) {
      const t = await r.text();
      await DaemonkeyAlert({ title: '切换模型失败', message: t.slice(0, 400) || '服务端没返详情', icon: '<i class="ri-error-warning-fill"></i>' });
      return;
    }
    const data = await r.json();
    _modelMenuOpen = false;
    // 会话记住模型 · 手动切模型也记到当前会话 meta (切标签恢复用)
    if (sessionId && !sessionId.startsWith('tmp-')) {
      if (!sessionMetaCache[sessionId]) sessionMetaCache[sessionId] = {};
      sessionMetaCache[sessionId].last_model_cfg = alias;
      fetch(`/sessions/${encodeURIComponent(sessionId)}/meta`, {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
        body: JSON.stringify({ last_model_cfg: alias }),
      }).catch(() => {});
    }
    const _mm = document.getElementById('modelMenu');
    if (_mm) _mm.classList.remove('open');
    const _mnl = document.getElementById('modelNameLabel');
    if (_mnl) _mnl.textContent = alias;
    const tip = document.createElement('div');
    tip.className = 'model-switch-tip';
    tip.textContent = `模型已切到 ${alias} · ${data.note || '下一轮生效'}`;
    document.body.appendChild(tip);
    setTimeout(() => tip.remove(), 2800);
    setTimeout(loadCurrentModel, 600);
  } catch (e) {
    await DaemonkeyAlert({ title: '网络出错', message: e.message, icon: '<i class="ri-error-warning-fill"></i>' });
  }
}

// 点 outside 关 model menu
document.addEventListener('click', (e) => {
  if (!_modelMenuOpen) return;
  if (e.target.closest('#modelSwitch')) return;
  _modelMenuOpen = false;
  document.getElementById('modelMenu')?.classList.remove('open');
});

// 手机端 · 点 chat-pane-head 把对话栏从底部抽屉切换出来
function toggleChatPane() {
  if (window.innerWidth > 900) return;
  document.querySelector('.chat-pane')?.classList.toggle('open');
}
document.querySelector('.chat-pane-head')?.addEventListener('click', (e) => {
  if (window.innerWidth > 900) return;
  // 在 head 区域空白处点才触发 · 不要拦截 session-pill / + 按钮
  if (e.target.closest('button')) return;
  toggleChatPane();
});

// chat-pane 总是在右栏显示 · 不再有"返回对话"概念
function backToChat() {
  currentView = null;
  document.querySelectorAll('.nav-item.active').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.nav-settings-btn.active').forEach(b => b.classList.remove('active'));
  // 卷四十四 K · 离开任何 view · 工坊也要 unmount
  if (window.Daemonkey_WORKSHOP_VIEW && window.Daemonkey_WORKSHOP_VIEW.isMounted()) {
    window.Daemonkey_WORKSHOP_VIEW.unmount();
    $detailPane.classList.remove('workshop-active');
  }
  renderDetailWelcome();
}

// nav 徽章数字紧凑显示 · 防止位数膨胀 (用户 2026-06-03)
//   <1000 原样 · 1k~9.9k → 1.2k · ≥1万 → 1.2w
function fmtBadge(n) {
  n = Number(n) || 0;
  if (n < 1000) return String(n);
  if (n < 10000) return (Math.round(n / 100) / 10).toString().replace(/\.0$/, '') + 'k';
  return (Math.round(n / 1000) / 10).toString().replace(/\.0$/, '') + 'w';
}

// 左侧每个维度的小 badge 数字（刷新）· 显示今日新增 (用户 2026-06-03 · 不要总数)
async function refreshNavBadges() {
  if (!token) return;
  try {
    const r = await fetch('/dashboard/cockpit?head=1', {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) return;
    const data = await r.json();
    for (const d of data.domains || []) {
      const badge = document.getElementById('navBadge_' + d.id);
      if (!badge) continue;
      if (d.stub) {
        badge.textContent = 'stub';
        badge.className = 'badge stub';
        badge.style.display = '';
        continue;
      }
      // 徽章只显示「今日新增」· 今天没新增就隐藏 (用户 2026-06-03) · 总数进 hover title
      const tn = Number(d.today_new || 0);
      const tot = Number(d.total || 0);
      if (tn > 0) {
        badge.textContent = '+' + fmtBadge(tn);
        badge.title = `今日新增 ${tn} · 共 ${tot} 条`;
        badge.className = 'badge has-items';
        badge.style.display = '';
      } else {
        badge.style.display = 'none';
      }
    }
    // 兜底：不在 cockpit domains 里的 nav item（calendar/workshop/favorites/sinks 等）
    // renderNav 给它们初始值 · —— 没被上面循环碰过 → 隐藏 (用户 2026-06-03)
    for (const el of document.querySelectorAll('[id^="navBadge_"]')) {
      if (el.textContent === '·' && el.style.display !== 'none') {
        el.style.display = 'none';
      }
    }
  } catch (e) {
    // 不打扰用户 · 静默失败
  }
}

// 卷二十八 · 起始屏 = BI 看板
// 包含：领域热力图（雷达条目按 domain 分布）+ 掘金机会卡（top 3）+ 维度速览
function renderDetailWelcome() {
  $detailPane.innerHTML = `
    <div class="bi-loading">
      <div style="font-size:18px;margin-bottom:8px"><i class="ri-diamond-fill"></i> 工作室 BI 看板</div>
      ${typeof dashLoadingHTML === 'function' ? dashLoadingHTML('正在装配看板') : '<div style="font-size:12px;color:var(--dim2)">加载中…</div>'}
    </div>`;
  loadBIDashboard();
}

async function loadBIDashboard() {
  if (!token) {
    $detailPane.innerHTML = `
      <div class="bi-loading">
        <div style="font-size:18px;margin-bottom:8px"><i class="ri-diamond-fill"></i> 工作室 BI 看板</div>
        <div style="font-size:12px;color:var(--dim2)">没有 token · 点右上 ⚙ 填一下</div>
      </div>`;
    return;
  }
  try {
    const r = await fetch('/dashboard/cockpit?head=3', {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) {
      $detailPane.innerHTML = `<div class="bi-loading">加载失败 [${r.status}]</div>`;
      return;
    }
    const data = await r.json();
    renderBIDashboard(data);
  } catch (e) {
    $detailPane.innerHTML = `<div class="bi-loading">网络出错: ${e.message}</div>`;
  }
}

function renderBIDashboard(data) {
  // 从 cockpit 拿所有维度
  const domainsById = {};
  for (const d of data.domains || []) domainsById[d.id] = d;

  // ── 搭建 V3 骨架 ──
  $detailPane.innerHTML = `
    <div class="bi-dashboard">
      <div class="bi-head">
        <h2><i class="ri-dashboard-fill" style="color:var(--Daemonkey)"></i> 工作室 BI 看板</h2>
        <span class="bi-head-meta">
          ${data.generated_at || ''} ·
          <button class="bi-link" onclick="renderDetailWelcome()" title="刷新"><i class="ri-refresh-fill"></i> 刷新</button>
        </span>
      </div>

      <!-- 建议操作 (0.9.6 · BRO: 页面分散 · 顶部放条件触发的行动建议 · 晨会汇报位) -->
      <div id="biSuggestBar" style="margin-bottom:12px"></div>

      <!-- KPI 数字条 -->
      <div class="bi-kpi-bar" id="biKpiBar">
        <div class="bi-kpi-card"><div class="bi-kpi-value">…</div><div class="bi-kpi-label">加载中</div></div>
      </div>

      <!-- 自主巡航 -->
      ${renderAutopilotBanner()}

      <!-- 第一行：价值热力图(占大头) + 信号流(压窄) -->
      <div class="bi-grid-2 bi-row-heat">
        <div class="bi-card bi-heat-card">
          <div class="bi-card-head">
            <h3><i class="ri-fire-fill" style="color:var(--Daemonkey)"></i> 价值热力</h3>
            <span class="bi-heat-nav">
              <button class="bi-heat-arrow" onclick="biHeatNav(-1)" title="上个月"><i class="ri-arrow-left-s-line"></i></button>
              <span class="badge" id="biCalBadge">…</span>
              <button class="bi-heat-arrow" onclick="biHeatNav(1)" title="下个月"><i class="ri-arrow-right-s-line"></i></button>
            </span>
          </div>
          <div class="bi-heat-domains" id="biHeatDomains"></div>
          <div class="bi-heat-summary" id="biHeatSummary"></div>
          <div class="bi-ritual-strip" id="biRitualStrip"></div>
          <div class="bi-cal-labels"><span>一</span><span>二</span><span>三</span><span>四</span><span>五</span><span>六</span><span>日</span></div>
          <div class="bi-cal-grid" id="biCalGrid"></div>
        </div>
        <div class="bi-card bi-signal-card">
          <div class="bi-card-head">
            <h3><i class="ri-radar-fill" style="color:var(--Daemonkey)"></i> 信号流</h3>
            <span class="bi-sig-head-r">
              <button class="bi-sig-today" id="biSigToday" onclick="biSigToggleToday()" title="只看今天抓到/发布的信号"><i class="ri-calendar-event-line"></i> 今日</button>
              <span class="badge" id="biSigCount">…</span>
            </span>
          </div>
          <div class="bi-heat-domains" id="biSigDomains"></div>
          <div id="biSignalList"><div class="bi-v3-empty">加载中…</div></div>
        </div>
      </div>

      <!-- 趋势研判 (卷五十六 P2) · 跟热力图同月同领域 · Daemonkey 用 LLM 给可行性 + 执行方案 -->
      <div class="bi-card bi-brief-card">
        <div class="bi-card-head">
          <h3><i class="ri-lightbulb-flash-fill" style="color:#F6AD55"></i> 趋势研判 <span class="bi-brief-scope" id="biBriefScope"></span></h3>
          <button class="bi-brief-gen" id="biBriefGenBtn" onclick="biBriefGenerate()"><i class="ri-sparkling-2-line"></i> 研判本月趋势</button>
        </div>
        <div class="bi-brief-body" id="biBriefBody"><div class="bi-v3-empty">跟着热力图的月份 / 领域 · 点右上让 Daemonkey 看一遍这段时间的信号·给趋势可行性 + 下一步动作</div></div>
      </div>

      <!-- 认知行 (卷五十八续 VIII)：Daemonkey 眼里的你 (能力镜像·填孤岛) + 闭环温度计 -->
      <div class="bi-grid-2">
        <div class="bi-card bi-mirror-card">
          <div class="bi-card-head">
            <h3><i class="ri-aspect-ratio-fill" style="color:#9f7aea"></i> Daemonkey 眼里的你 <span class="bi-mirror-time" id="biMirrorTime"></span></h3>
            <button class="bi-brief-gen" id="biMirrorBtn" type="button"><i class="ri-camera-lens-fill"></i> 立即照镜</button>
          </div>
          <div class="bi-mirror-body" id="biMirrorBody"><div class="bi-v3-empty">加载中…</div></div>
        </div>
        <div class="bi-card">
          <div class="bi-card-head"><h3><i class="ri-temp-hot-fill" style="color:#F6AD55"></i> 闭环温度计 <span class="badge" id="biClosureRate">…</span></h3></div>
          <div id="biClosureBody"><div class="bi-v3-empty">加载中…</div></div>
        </div>
      </div>

      <!-- 记忆体系 + 工坊 (0.9.6 · BRO: 看板 = 用户了解功能的大面板 · 按钮走 spawnQuickly 后台任务 · 跟照镜同款) -->
      <div class="bi-grid-2" style="margin-top:12px">
        <div class="bi-card">
          <div class="bi-card-head">
            <h3><i class="ri-brain-fill" style="color:#8affd6"></i> 记忆体系 <span class="badge" id="biMemoryBadge">…</span></h3>
            <span>
              <button class="bi-link" id="biMemoryAuditBtn" type="button" title="让 ${window.AI_NAME || 'Daemonkey'} 用语义向量体检手艺箱 · 重复簇摆出来你拍板"><i class="ri-search-eye-line"></i> 手艺体检</button>
              <button class="bi-link" onclick="loadDashboard('memory_map')" title="记忆星图 · 三道闸治理全景"><i class="ri-sparkling-2-fill"></i> 星图</button>
            </span>
          </div>
          <div class="bi-self-grid" id="biMemoryBody"><div class="bi-v3-empty">加载中…</div></div>
        </div>
        <div class="bi-card">
          <div class="bi-card-head">
            <h3><i class="ri-tools-fill" style="color:#b794f6"></i> 工坊 <span class="badge" id="biWorkshopBadge">…</span></h3>
            <button class="bi-link" onclick="loadDashboard('workshop')" title="进工坊编排应用与工作流"><i class="ri-arrow-right-line"></i> 进工坊</button>
          </div>
          <div class="bi-self-grid" id="biWorkshopBody"><div class="bi-v3-empty">加载中…</div></div>
        </div>
      </div>

      <!-- 第二行：图表 × 2 -->
      <div class="bi-grid-2">
        <div class="bi-card">
          <div class="bi-card-head"><h3><i class="ri-bar-chart-fill" style="color:#4FD1C5"></i> 30 天雷达密度</h3></div>
          <div class="bi-chart-wrap"><canvas id="biChartRadar"></canvas></div>
        </div>
        <div class="bi-card">
          <div class="bi-card-head"><h3><i class="ri-pie-chart-fill" style="color:#F6AD55"></i> 维度产出分布</h3></div>
          <div class="bi-chart-wrap"><canvas id="biChartDonut"></canvas></div>
          <div class="bi-donut-legend" id="biDonutLegend"></div>
        </div>
      </div>

      <!-- wish-bec4f3b9 · 计费卡 (价格表 × 用量 → 钱) -->
      <div class="bi-card" style="margin-top:12px">
        <div class="bi-card-head">
          <h3><i class="ri-money-cny-circle-fill" style="color:#F6AD55"></i> 模型计费</h3>
          <div class="bi-range-bar" id="biBillingRangeBar">
            <button class="btn-ghost active" data-range="today">今日</button>
            <button class="btn-ghost" data-range="7d">7天</button>
            <button class="btn-ghost" data-range="30d">30天</button>
          </div>          <span class="badge" id="biBillingUnpriced" title="未配价模型不出金额 · 去 设置→LLM模型 配价"></span>
        </div>
        <div id="biBillingBody"><div class="bi-v3-empty">加载中…</div></div>
      </div>

      <!-- 第三行：掘金机会 + 最近动态 -->
      <div class="bi-grid-2">
        <div class="bi-card">
          <div class="bi-card-head"><h3><i class="ri-diamond-fill" style="color:#F6AD55"></i> 掘金机会</h3><span class="badge" id="biOppCount">…</span></div>
          <div id="biOppList"><div class="bi-v3-empty">加载中…</div></div>
        </div>
        <div class="bi-card">
          <div class="bi-card-head"><h3><i class="ri-history-fill" style="color:var(--dim)"></i> 最近动态</h3></div>
          <div class="bi-timeline" id="biTimeline"><div class="bi-v3-empty">加载中…</div></div>
        </div>
      </div>

      <!-- 元行 (卷五十八续 VIII)：Daemonkey 自况 + 节律时间线 -->
      <div class="bi-grid-2">
        <div class="bi-card">
          <div class="bi-card-head"><h3><i class="ri-pulse-fill" style="color:#4FD1C5"></i> Daemonkey 自况</h3></div>
          <div class="bi-self-grid" id="biSelfBody"><div class="bi-v3-empty">加载中…</div></div>
        </div>
        <div class="bi-card">
          <div class="bi-card-head"><h3><i class="ri-time-fill" style="color:#63B3ED"></i> 节律 · 周期仪式</h3></div>
          <div class="bi-rhythm" id="biRhythmBody"><div class="bi-v3-empty">加载中…</div></div>
        </div>
      </div>
    </div>`;

  // ── 同步填充已有数据 ──
  fillBIV3Blocks(data);
  // ── 异步拉补充数据 ──
  loadBIV3Async();
}

// ═══════════════════════════════════════════
//  V3 同步填充 (cockpit 已有的数据)
// ═══════════════════════════════════════════
function fillBIV3Blocks(data) {
  const domainsById = {};
  for (const d of data.domains || []) domainsById[d.id] = d;

  // KPI 条
  const picks = [
    { id:'radar',   icon:'ri-radar-fill',     color:'var(--Daemonkey)',  label:'雷达信号' },
    { id:'trends',  icon:'ri-line-chart-fill', color:'#4FD1C5',     label:'今日趋势' },
    { id:'reports', icon:'ri-article-fill',    color:'#63B3ED',     label:'报告产出' },
    { id:'wishlist',icon:'ri-lightbulb-fill',  color:'#F6AD55',     label:'Daemonkey 心愿' },
    { id:'plugins', icon:'ri-puzzle-fill',     color:'var(--dim)',   label:'已装插件' },
  ];
  const kpiHtml = picks.map(p => {
    const d = domainsById[p.id];
    const v = d ? d.total : 0;
    return `<div class="bi-kpi-card"><div class="bi-kpi-icon" style="color:${p.color}"><i class="${p.icon}"></i></div><div class="bi-kpi-value">${v}</div><div class="bi-kpi-label">${p.label}</div></div>`;
  }).join('');
  const kpiBar = document.getElementById('biKpiBar');
  if (kpiBar) kpiBar.innerHTML = kpiHtml;

  // 机会
  const oppDomain = domainsById['opportunities'] || {};
  const opps = oppDomain.items || [];
  const oppCount = document.getElementById('biOppCount');
  if (oppCount) oppCount.textContent = (oppDomain.total || opps.length) + ' 个';
  const oppList = document.getElementById('biOppList');
  if (oppList && opps.length) {
    oppList.innerHTML = opps.map(o => {
      const sc = o.recommend || o.recommendation_score || 50;
      const cls = sc >= 70 ? 'hi' : sc >= 40 ? 'md' : 'lo';
      const tags = o.tags || [];
      return `<div class="bi-opp-item">
        <div class="bi-opp-score ${cls}">${sc}</div>
        <div class="bi-opp-body">
          <div class="bi-opp-title">${escHtml(o.title || '(未命名)')}</div>
          ${o.summary ? `<div class="bi-opp-summary">${escHtml(o.summary).slice(0,80)}</div>` : ''}
          ${tags.length ? `<div class="bi-opp-tags">${tags.map(t => `<span class="bi-opp-tag">${escHtml(t)}</span>`).join('')}</div>` : ''}
        </div>
      </div>`;
    }).join('');
  } else if (oppList) {
    oppList.innerHTML = '<div class="bi-v3-empty">暂无掘金机会 · 跟 Daemonkey 说「巡一圈」</div>';
  }

  // 最近动态（从 cockpit 各维度拼）
  fillBITimeline(data);
}

// ═══════════════════════════════════════════
//  V3 异步补充 (日历 + 雷达 + 趋势 + 图表)
// ═══════════════════════════════════════════
async function loadBIV3Async() {
  try {
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, '0');

    const [cal, radar, trends] = await Promise.all([
      fetch('/dashboard/calendar?domain_filter=' + y + '-' + m + '&head=42', { headers: { 'Authorization': 'Bearer ' + token } }).then(r => r.ok ? r.json() : null),
      fetch('/dashboard/radar?head=6', { headers: { 'Authorization': 'Bearer ' + token } }).then(r => r.ok ? r.json() : null),
      fetch('/dashboard/trends?head=3', { headers: { 'Authorization': 'Bearer ' + token } }).then(r => r.ok ? r.json() : null),
    ]);

    biHeatLoad();  // 卷五十六 · 价值热力图 (独立拉 calendar_valued · 不再用 cal 计数) · 顺带填节律时间线 D 卡
    if (radar || trends) fillBISignals(radar, trends);
    if (cal) fillBIRadarChart(cal);
    fillBIDonutChart();
    // 卷五十八续 VIII · 新增卡 (各自独立·互不阻塞)
    loadBIMirror();   // A·Daemonkey 眼里的你
    loadBIClosure();  // B·闭环温度计
    loadBISelf();     // C·Daemonkey 自况
    loadBIBilling();  // wish-bec4f3b9 · 模型计费卡
  } catch (e) {
    console.error('BI V3 async load error:', e);
  }
}

// ═══════════════════════════════════════════
//  卷五十八续 VIII · A/B/C 卡加载器 (D 节律时间线在 biHeatRender 里填)
// ═══════════════════════════════════════════
// A·Daemonkey 眼里的你 · 市场能力镜像快照 (填"照完即孤岛"的洞)
async function loadBIMirror() {
  const body = document.getElementById('biMirrorBody');
  const timeEl = document.getElementById('biMirrorTime');
  const btn = document.getElementById('biMirrorBtn');
  if (btn) btn.onclick = () => spawnQuickly('帮我照一次市场能力镜像 (mirror_capability action=generate)', '市场能力镜像');
  if (!body) return;
  try {
    const r = await fetch('/dashboard/capability_snapshot', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) { body.innerHTML = '<div class="bi-v3-empty">加载失败</div>'; return; }
    const d = await r.json();
    if (!d.snapshot) {
      body.innerHTML = `<div class="bi-v3-empty">${escHtml(d.note || '还没照过镜子 · 点右上「立即照镜」')}</div>`;
      if (timeEl) timeEl.textContent = '';
      return;
    }
    body.innerHTML = (typeof mdRender === 'function') ? mdRender(d.snapshot) : escHtml(d.snapshot);
    if (timeEl) timeEl.textContent = d.generated_at ? ('· ' + d.generated_at) : '';
  } catch (e) { body.innerHTML = '<div class="bi-v3-empty">网络出错</div>'; }
}

// B·闭环温度计 · 哪些 Daemonkey 输出还在等 用户 反应
async function loadBIClosure() {
  const body = document.getElementById('biClosureBody');
  const rateEl = document.getElementById('biClosureRate');
  if (!body) return;
  try {
    const r = await fetch('/dashboard/closure', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) { body.innerHTML = '<div class="bi-v3-empty">加载失败</div>'; return; }
    const d = await r.json();
    if (rateEl) rateEl.textContent = (d.closure_rate != null ? d.closure_rate + '%' : '—');
    const gauges = d.gauges || [];
    if (!gauges.length) { body.innerHTML = '<div class="bi-v3-empty">暂无可统计的闭环</div>'; return; }
    body.innerHTML = gauges.map(g => {
      const pct = g.total > 0 ? Math.round(100 * g.closed / g.total) : 100;
      const warn = g.pending > 0 ? ' warn' : '';
      return `<div class="bi-closure-row">
        <div class="bi-closure-top"><span class="bi-closure-lbl">${escHtml(g.label)}</span><span class="bi-closure-num${warn}">${g.closed}/${g.total}</span></div>
        <div class="bi-closure-bar"><div class="bi-closure-fill" style="width:${pct}%"></div></div>
        <div class="bi-closure-hint">${escHtml(g.hint || '')}</div>
      </div>`;
    }).join('');
  } catch (e) { body.innerHTML = '<div class="bi-v3-empty">网络出错</div>'; }
}

// C·Daemonkey 自况 · token / 会话 / 在线 (拉现有端点·不加后端)
function _biFmtNum(n) {
  n = +n || 0;
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k';
  return String(n);
}
function _biUptime(iso) {
  const t = Date.parse(iso);
  if (isNaN(t)) return '—';
  let s = Math.max(0, Math.floor((Date.now() - t) / 1000));
  const d = Math.floor(s / 86400); s -= d * 86400;
  const h = Math.floor(s / 3600); s -= h * 3600;
  const m = Math.floor(s / 60);
  if (d > 0) return `${d}天${h}时`;
  if (h > 0) return `${h}时${m}分`;
  return `${m}分`;
}
// wish-bec4f3b9 · 模型计费卡 (原型 dashboard-billing-proto 完整形态 · 价格表 × 用量 → 钱)
// 默认今日 · 用户 刷新看到的是当天数据 · 要更多自己切 7天/30天
let _biBillingRange = 'today';
// 模型切换「展开更多」(2026-08-20 · 默认 5 条 · 跟缓存经济性卡对齐)
function biTlToggleMore(btn) {
  const more = document.getElementById('biTlMoreWrap');
  if (!more) return;
  const open = more.style.display !== 'none';
  more.style.display = open ? 'none' : '';
  btn.innerHTML = open
    ? `<i class="ri-arrow-down-s-line"></i> 展开剩余 ${more.children.length} 条`
    : '<i class="ri-arrow-up-s-line"></i> 收起';
}
async function loadBIBilling() {
  const body = document.getElementById('biBillingBody');
  const badge = document.getElementById('biBillingUnpriced');
  if (!body) return;
  try {
    const r = await fetch('/dashboard/billing?range=' + _biBillingRange, { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) { body.innerHTML = '<div class="bi-v3-empty">计费数据暂不可用</div>'; return; }
    const d = await r.json();
    const k = d.kpis || {};
    if (badge) {
      badge.textContent = k.unpriced_models ? `⚠ ${k.unpriced_models} 个未配价` : '';
      badge.style.color = '#F6AD55';
      badge.title = '未配价模型不出金额 · 去 设置→LLM模型 配价';
    }
    const cur = k.currency === 'CNY' ? '¥' : '$';
    const rl = {today:'今日', '7d':'近7天', '30d':'本月'}[_biBillingRange] || _biBillingRange;
    const unpricedHint = k.unpriced_models ? '<i class="ri-information-fill bi-hint-i" title="不含 ' + k.unpriced_models + ' 个未配价模型 · 实际花费可能更高 · 口径=已配价模型"></i>' : '';

    // ① KPI 四卡
    const kpiCards = `
      <div class="bi-kpi-bar proto-kpi-4" style="grid-template-columns:repeat(auto-fit,minmax(min(150px,100%),1fr));margin-bottom:12px">
        <div class="bi-kpi-card"><div class="bi-kpi-icon" style="color:#F6AD55"><i class="ri-coin-fill"></i></div>
          <div class="bi-kpi-value">${cur}${(k.today_cost || 0).toFixed(2)}</div><div class="bi-kpi-label">${rl}花费${unpricedHint}</div></div>
        <div class="bi-kpi-card"><div class="bi-kpi-icon" style="color:#B794F4"><i class="ri-wallet-3-fill"></i></div>
          <div class="bi-kpi-value">${cur}${(k.month_cost || 0).toFixed(2)}</div><div class="bi-kpi-label">本月花费</div></div>
        <div class="bi-kpi-card"><div class="bi-kpi-icon" style="color:#63B3ED"><i class="ri-cpu-fill"></i></div>
          <div class="bi-kpi-value">${_biFmtTok(k.today_tokens || 0)}</div><div class="bi-kpi-label">${rl} tokens (in+out)</div></div>
        <div class="bi-kpi-card"><div class="bi-kpi-icon" style="color:#4FD1C5"><i class="ri-flashlight-fill"></i></div>
          <div class="bi-kpi-value">${Math.round((k.cache_hit_rate||0)*100)}%</div>
          <div class="bi-kpi-label">缓存命中率<i class="ri-information-fill bi-hint-i" title="口径=已配价模型"></i></div>
          <div class="bi-kpi-delta" style="color:#48BB78">缓存省 ${cur}${(k.cache_saved||0).toFixed(2)}</div></div>
      </div>`;

    // ② 按模型成本表 (原型 7 列)
    const rows = (d.by_model || []).map(m => {
      const cost = m.price ? _biMoney(m, cur) : '<span class="bi-unpriced">— 未配价</span>';
      const cr = m.cache_read_tokens || 0;
      const cacheTag = cr > 0 ? ` <span class="bi-brief-scope" title="含缓存价">含缓存价${m.price && m.price.cache_read != null ? '' : '(估)'}</span>` : '';
      const src = m.price
        ? '<span class="bi-brief-scope">价格表</span>'
        : `<a class="bi-link-btn" href="#" onclick="openSettings();return false;"><i class="ri-price-tag-3-line"></i> 去配价 →</a>`;
      return `<tr>
        <td style="padding:5px 8px;color:var(--text)">${escHtml(m.name || m.config_id || m.model_id || '?')}</td>
        <td class="bi-num" style="padding:5px 8px">${m.calls}</td>
        <td class="bi-num" style="padding:5px 8px">${_biFmtTok(m.input_tokens||0)}</td>
        <td class="bi-num" style="padding:5px 8px">${_biFmtTok(m.output_tokens||0)}</td>
        <td class="bi-num" style="padding:5px 8px">${_biFmtTok(cr)}${cacheTag}</td>
        <td class="bi-num" style="padding:5px 8px">${cost}</td>
        <td style="padding:5px 8px">${src}</td>
      </tr>`;
    }).join('');
    const modelTable = `
      <div style="margin-bottom:12px">
        <div style="font-size:13px;font-weight:700;color:var(--text);margin-bottom:6px"><i class="ri-bar-chart-box-fill" style="color:#F6AD55"></i> 按模型成本</div>
        <div style="overflow-x:auto"><table class="proto-table bi-table" style="width:100%;border-collapse:collapse;font-size:12px">
          <thead><tr style="color:var(--dim);text-align:left">
            <th style="padding:5px 8px">模型 (config 名)</th><th class="bi-num" style="padding:5px 8px">调用</th>
            <th class="bi-num" style="padding:5px 8px">输入 tok</th><th class="bi-num" style="padding:5px 8px">输出 tok</th>
            <th class="bi-num" style="padding:5px 8px">缓存命中 tok</th><th class="bi-num" style="padding:5px 8px">估算成本</th>
            <th style="padding:5px 8px">单价来源</th>
          </tr></thead>
          <tbody>${rows || '<tr><td colspan="7" class="bi-v3-empty" style="padding:10px">还没有用量数据 · 聊几轮就有了</td></tr>'}</tbody>
        </table></div>
      </div>`;

    // ③ 双栏: 模型切换时间线 + 缓存经济性
    // 方案 B (2026-08-06 用户 拍板) · 普通切换=平铺行 · 顾问唤醒=紫色左边条胶囊
    const switches = (d.switches || []);
    const tlItems = switches.slice(0, 8).map(s => {
      if (s.advisor) {
        // 2026-08-20 BRO: 胶囊只留 皇冠+模型名+tok · 「顾问唤醒」标签和时间/mode 收进悬浮
        // (窄分辨率下 meta 长串把胶囊撑高/挤爆 · 折叠抗性优先)
        const full = `顾问唤醒 · ${s.ts || ''} · ${s.mode || ''} · ${_biFmtTok(s.tokens_after || 0)} tok · 系统自动调用的顾问模型 · 独立临时连接`;
        return `<div class="bi-tl-adv" title="${escHtml(full)}">
          <i class="ri-vip-crown-fill"></i>
          <b title="${escHtml(s.to?.name||'')}">${escHtml(s.to?.name||'')}</b>
          <span class="bi-tl-adv-meta">${_biFmtTok(s.tokens_after||0)} tok</span>
        </div>`;
      }
      const fullMain = `${escHtml(s.from?.name||'')} → ${escHtml(s.to?.name||'')} · ${escHtml(s.ts||'')} · ${_biFmtTok(s.tokens_after||0)} tok`;
      return `<div class="bi-tl-main">
        <i class="ri-arrow-right-up-line"></i>
        <span title="${escHtml(s.from?.name||'')}">${escHtml(s.from?.name||'')}</span>
        <span class="bi-tl-arr"><i class="ri-arrow-right-line"></i></span>
        <b title="${escHtml(s.to?.name||'')}">${escHtml(s.to?.name||'')}</b>
        <span class="bi-tl-main-meta" title="${escHtml(s.ts||'')}">${_biFmtTok(s.tokens_after||0)} tok</span>
      </div>`;
    });
    // 2026-08-20 BRO: 最多显 5 条 · 超出收进「展开更多」(左栏比右栏(缓存经济性)高一截 · 对不齐)
    // 「仅显示最近 8 条」不单起一行 · 并进展开按钮行右侧 (BRO 续)
    const TL_SHOW = 5;
    const tlCapNote = switches.length > 8 ? '<span class="bi-brief-scope" style="margin-left:auto">仅显示最近 8 条</span>' : '';
    const tl = tlItems.length ? (
      tlItems.slice(0, TL_SHOW).join('')
      + (tlItems.length > TL_SHOW
        ? `<div id="biTlMoreWrap" style="display:none">${tlItems.slice(TL_SHOW).join('')}</div>
           <div style="display:flex;align-items:center"><button class="bi-tl-more" onclick="biTlToggleMore(this)"><i class="ri-arrow-down-s-line"></i> 展开剩余 ${tlItems.length - TL_SHOW} 条</button>${tlCapNote}</div>`
        : tlCapNote ? `<div style="display:flex">${tlCapNote}</div>` : '')
    ) : '<div class="bi-v3-empty" style="padding:6px 0">还没有模型切换记录</div>';
    const cacheRows = (d.by_model || []).filter(m => (m.cache_read_tokens||0) > 0 && _biIsLlm(m)).map(m => {
      const rate = m.input_tokens > 0 ? (m.cache_read_tokens||0) / m.input_tokens : 0;
      let saved = null;
      if (m.price) {
        const pc = (m.price.cache_read != null) ? m.price.cache_read : (m.price.input||0) * 0.1;
        saved = (m.cache_read_tokens||0) * ((m.price.input||0) - pc) / 1e6;
      }
      return `<div style="margin-bottom:7px">
        <div style="display:flex;justify-content:space-between;font-size:12px">
          <span style="color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0" title="${escHtml(m.name||'?')}">${escHtml(m.name||'?')}</span>
          <span style="color:var(--dim);flex-shrink:0;margin-left:8px">${Math.round(rate*100)}% · ${m.price ? cur + saved.toFixed(2) : '<span style="color:#F6AD55">未配价</span>'}</span>
        </div>
        <div class="bi-bar-bg" style="height:6px;background:var(--bg3);border-radius:3px;margin-top:3px"><div style="height:100%;border-radius:3px;width:${rate*100}%;background:#4FD1C5"></div></div>
      </div>`;
    }).join('');
    const duo = `
      <div class="bi-grid-2" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(260px,100%),1fr));gap:12px;margin-bottom:12px">
        <div>
          <div style="font-size:13px;font-weight:700;color:var(--text);margin-bottom:8px"><i class="ri-switch-fill" style="color:#63B3ED"></i> 模型切换</div>
          ${tl}
        </div>
        <div>
          <div style="font-size:13px;font-weight:700;color:var(--text);margin-bottom:8px"><i class="ri-flashlight-fill" style="color:#4FD1C5"></i> 缓存经济性</div>
          <div style="display:flex;align-items:baseline;gap:8px">
            <span style="font-size:22px;font-weight:700;color:var(--text)">${Math.round((k.cache_hit_rate||0)*100)}%</span>
            <span class="bi-brief-scope">总命中率 · 口径=已配价模型</span>
          </div>
          <div class="bi-bar-bg" style="height:8px;background:var(--bg3);border-radius:4px;margin:6px 0"><div style="height:100%;border-radius:4px;width:${Math.round((k.cache_hit_rate||0)*100)}%;background:linear-gradient(90deg,#4FD1C5,#48BB78)"></div></div>
          <div style="font-size:12px;color:var(--text);margin-bottom:8px"><i class="ri-money-cny-circle-fill" style="color:#48BB78"></i> 缓存省下 <b>${cur}${(k.cache_saved||0).toFixed(2)}</b> <span class="bi-brief-scope">(命中价差折算 · 含估)</span></div>
          ${cacheRows || ''}
        </div>
      </div>`;

    // ④ 工坊 App 用量
    const appRows = (d.app_runs || []).map(a => `<tr>
      <td style="padding:5px 8px;color:var(--text)">${escHtml(a.app_name || a.app_id || '?')}</td>
      <td class="bi-num" style="padding:5px 8px">${a.runs}</td>
      <td class="bi-num" style="padding:5px 8px">${(a.avg_iterations||0).toFixed(1)}</td>
      <td class="bi-num" style="padding:5px 8px">${_biFmtTok(a.total_tokens||0)}</td>
      <td class="bi-num" style="padding:5px 8px">${a.est_cost != null ? cur + a.est_cost.toFixed(2) : '<span class="bi-unpriced">— 未配价</span>'}</td>
    </tr>`).join('');
    const appTable = `
      <div>
        <div style="font-size:13px;font-weight:700;color:var(--text);margin-bottom:6px"><i class="ri-tools-fill" style="color:#B794F4"></i> 工坊 App 用量</div>
        <div style="overflow-x:auto"><table class="proto-table bi-table" style="width:100%;border-collapse:collapse;font-size:12px">
          <thead><tr style="color:var(--dim);text-align:left">
            <th style="padding:5px 8px">App 名</th><th class="bi-num" style="padding:5px 8px">运行次数</th>
            <th class="bi-num" style="padding:5px 8px">平均迭代</th><th class="bi-num" style="padding:5px 8px">总 tokens</th>
            <th class="bi-num" style="padding:5px 8px">估算成本</th>
          </tr></thead>
          <tbody>${appRows || '<tr><td colspan="5" class="bi-v3-empty" style="padding:10px">还没有 app 用量</td></tr>'}</tbody>
        </table></div>
      </div>`;

    body.innerHTML = kpiCards + modelTable + duo + appTable;
  } catch (e) {
    body.innerHTML = '<div class="bi-v3-empty">计费数据加载失败</div>';
  }
}
function _biMoney(m, cur) {
  const p = m.price;
  const calc = (u, price) => {
    if (!price) return null;
    const pin = price.input, pout = price.output;
    const pcache = (price.cache_read != null) ? price.cache_read : (pin || 0);
    const miss = Math.max(0, u.input_tokens - (u.cache_read_tokens||0) - (u.cache_creation_tokens||0));
    return (miss * (pin||0) + (u.cache_read_tokens||0) * pcache + (u.cache_creation_tokens||0) * (price.cache_creation ?? (pin||0)*1.25) + u.output_tokens * (pout||0)) / 1e6;
  };
  const c = calc(m, p);
  return c == null ? '—' : cur + c.toFixed(2);
}
function _biFmtTok(v) {
  if (v >= 1e6) return (v/1e6).toFixed(1) + 'M';
  if (v >= 1e3) return (v/1e3).toFixed(1) + 'k';
  return String(v || 0);
}
// 图像/视频/音频类不走 prompt cache · 缓存经济性只算 LLM 模型
const _biLlmFams = ['deepseek','glm','kimi','moonshot','claude','qwen','gpt-4','gpt-3.5','gpt-5','o1','o3','gemini','minimax'];
function _biIsLlm(m) {
  const s = ((m.model_id || '') + ' ' + (m.name || '')).toLowerCase();
  return _biLlmFams.some(f => s.includes(f));
}
// 范围切换
document.addEventListener('click', (e) => {
  const btn = e.target.closest('#biBillingRangeBar .btn-ghost');
  if (!btn) return;
  document.querySelectorAll('#biBillingRangeBar .btn-ghost').forEach(b => b.classList.toggle('active', b === btn));
  _biBillingRange = btn.dataset.range;
  loadBIBilling();
});

async function loadBISelf() {
  const body = document.getElementById('biSelfBody');
  if (!body) return;
  const hdr = { headers: { 'Authorization': 'Bearer ' + token } };
  const [tb, sess, life] = await Promise.all([
    fetch('/api/token_budget/status', hdr).then(r => r.ok ? r.json() : null).catch(() => null),
    fetch('/sessions?api_only=true', hdr).then(r => r.ok ? r.json() : null).catch(() => null),
    fetch('/api/lifecycle_status').then(r => r.ok ? r.json() : null).catch(() => null),
  ]);
  const cells = [];
  if (tb) {
    cells.push({ icon: 'ri-coin-fill', color: '#F6AD55', val: _biFmtNum(tb.day_total || 0), lbl: '今日 token' });
    cells.push({ icon: 'ri-chat-poll-fill', color: '#4FD1C5', val: (tb.day_calls || 0), lbl: '今日调用' });
  }
  if (sess) {
    const cnt = (sess.total != null) ? sess.total : ((sess.sessions || []).length);
    cells.push({ icon: 'ri-chat-3-fill', color: 'var(--Daemonkey)', val: cnt, lbl: '会话数' });
  }
  if (life && life.started_at) {
    cells.push({ icon: 'ri-time-fill', color: '#63B3ED', val: _biUptime(life.started_at), lbl: '已在线' });
  }
  if (!cells.length) { body.innerHTML = '<div class="bi-v3-empty">拿不到运行数据</div>'; return; }
  body.innerHTML = cells.map(c =>
    `<div class="bi-self-cell"><div class="bi-self-icon" style="color:${c.color}"><i class="${c.icon}"></i></div><div class="bi-self-val">${escHtml(String(c.val))}</div><div class="bi-self-lbl">${escHtml(c.lbl)}</div></div>`
  ).join('');
}

// 0.9.6 · 建议操作条 (顶部 · 条件触发 · 忽略按天记 localStorage)
function _biSuggestIgnored() {
  try { return JSON.parse(localStorage.getItem('bi_suggest_ignore') || '{}'); } catch { return {}; }
}
function biSuggestIgnore(id) {
  const m = _biSuggestIgnored();
  m[id] = new Date().toISOString().slice(0, 10); // 当天有效 · 明天又出现
  localStorage.setItem('bi_suggest_ignore', JSON.stringify(m));
  const el = document.getElementById('biSuggest-' + id);
  if (el) el.remove();
  const bar = document.getElementById('biSuggestBar');
  if (bar && !bar.querySelector('.bi-suggest-item')) bar.innerHTML = '';
}
async function loadBISuggestions() {
  const bar = document.getElementById('biSuggestBar');
  if (!bar) return;
  try {
    const r = await fetch('/dashboard/suggestions', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) return;
    const items = ((await r.json()).items || []);
    const ignored = _biSuggestIgnored();
    const today = new Date().toISOString().slice(0, 10);
    const show = items.filter(it => ignored[it.id] !== today);
    if (!show.length) { bar.innerHTML = ''; return; }
    bar.innerHTML = show.map(it => `
      <div class="bi-suggest-item" id="biSuggest-${escHtml(it.id)}" style="display:flex;align-items:center;gap:8px;padding:8px 12px;margin-bottom:6px;border:1px solid var(--border,#2a2a3a);border-radius:10px;background:var(--bg2,#1a1826);font-size:12px">
        <i class="${escHtml(it.icon)}" style="color:${escHtml(it.color || 'var(--accent,#8a7dff)')};font-size:14px"></i>
        <span style="flex:1;color:var(--text,#ece8f5)">${escHtml(it.text)}</span>
        ${it.prompt ? `<button class="bi-link" style="white-space:nowrap" onclick="spawnQuickly(${JSON.stringify(it.prompt).replace(/"/g, '&quot;')}, ${JSON.stringify(it.label || '建议操作').replace(/"/g, '&quot;')})"><i class="ri-play-fill"></i> ${escHtml(it.label || '执行')}</button>` : ''}
        <button class="bi-link" title="今天不再提示" onclick="biSuggestIgnore('${escHtml(it.id)}')" style="opacity:.55"><i class="ri-close-line"></i></button>
      </div>`).join('');
  } catch (e) { /* 建议条失败不影响看板 */ }
}

// 0.9.6 · 记忆体系卡 (lite 端点 · 秒出数字 · 详细全景点「星图」进 memory_map tab)
async function loadBIMemory() {
  const body = document.getElementById('biMemoryBody');
  const badge = document.getElementById('biMemoryBadge');
  const btn = document.getElementById('biMemoryAuditBtn');
  if (btn) btn.onclick = () => spawnQuickly('帮我看看手艺是不是有重复的 (用 audit_playbooks 工具出簇清单 · 不确定的摆给我选)', '手艺体检');
  if (!body) return;
  try {
    const r = await fetch('/dashboard/memory_map?lite=1', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) { body.innerHTML = '<div class="bi-v3-empty">加载失败</div>'; return; }
    const d = await r.json();
    if (d.error) { body.innerHTML = `<div class="bi-v3-empty">${escHtml(d.error)}</div>`; return; }
    const nb = d.notebook || {};
    const hg = d.hygiene || {};
    const nbPct = nb.full_chars ? Math.round(nb.core_chars / nb.full_chars * 100) : null;
    if (badge) badge.textContent = (d.playbook_count || 0) + ' 门手艺';
    const cells = [
      { icon: 'ri-database-2-fill', color: '#8affd6', val: _biFmtNum(d.total_chunks || 0), lbl: '记忆总量' },
      { icon: 'ri-tools-fill', color: '#b794f6', val: d.playbook_count || 0, lbl: '手艺' },
      { icon: 'ri-shield-check-fill', color: '#6ed27a', val: 'v' + (hg.version || '?'), lbl: hg.migrated ? '卫生闸·已清理' : '卫生闸·待清理' },
    ];
    if (nbPct != null) cells.push({ icon: 'ri-stack-fill', color: '#ffd28a', val: '-' + (100 - nbPct) + '%', lbl: '画像分层压缩' });
    body.innerHTML = cells.map(c =>
      `<div class="bi-self-cell"><div class="bi-self-icon" style="color:${c.color}"><i class="${c.icon}"></i></div><div class="bi-self-val">${escHtml(String(c.val))}</div><div class="bi-self-lbl">${escHtml(c.lbl)}</div></div>`
    ).join('');
  } catch (e) { body.innerHTML = '<div class="bi-v3-empty">网络出错</div>'; }
}

// 0.9.6 · 工坊卡 (apps/flows 计数 + shipped 数 · 入口卡)
async function loadBIWorkshop() {
  const body = document.getElementById('biWorkshopBody');
  const badge = document.getElementById('biWorkshopBadge');
  if (!body) return;
  const hdr = { headers: { 'Authorization': 'Bearer ' + token } };
  const [apps, flows] = await Promise.all([
    fetch('/workshop/apps', hdr).then(r => r.ok ? r.json() : null).catch(() => null),
    fetch('/workshop/flows', hdr).then(r => r.ok ? r.json() : null).catch(() => null),
  ]);
  if (!apps && !flows) { body.innerHTML = '<div class="bi-v3-empty">拿不到工坊数据</div>'; return; }
  const appList = (apps && (apps.items || apps.apps)) || [];
  const flowList = (flows && (flows.items || flows.flows)) || [];
  const shipped = appList.filter(a => a && a.shipped).length;
  if (badge) badge.textContent = appList.length + ' 应用';
  const cells = [
    { icon: 'ri-apps-2-fill', color: '#b794f6', val: appList.length, lbl: '应用' },
    { icon: 'ri-flow-chart', color: '#4FD1C5', val: flowList.length, lbl: '工作流' },
    { icon: 'ri-rocket-fill', color: '#F6AD55', val: shipped, lbl: '已出厂' },
  ];
  body.innerHTML = cells.map(c =>
    `<div class="bi-self-cell"><div class="bi-self-icon" style="color:${c.color}"><i class="${c.icon}"></i></div><div class="bi-self-val">${escHtml(String(c.val))}</div><div class="bi-self-lbl">${escHtml(c.lbl)}</div></div>`
  ).join('');
}

// ══════════════════════════════════════════════════════════
//  价值热力图 (卷五十六 · 2026-06-03)
//  按"信息价值密度"着色·支持按月翻 + 领域筛选 + 点击下钻看高分原文
//  数据走 /dashboard/calendar_valued + /dashboard/day_signals (workers/info_value.py)
// ══════════════════════════════════════════════════════════
const _biHeat = { ym: null, domain: 'all' };

async function biHeatLoad() {
  if (!_biHeat.ym) { const n = new Date(); _biHeat.ym = { y: n.getFullYear(), m: n.getMonth() + 1 }; }
  const { y, m } = _biHeat.ym;
  const mm = y + '-' + String(m).padStart(2, '0');
  const q = new URLSearchParams({ domain_filter: mm, vdomain: _biHeat.domain });
  try {
    const r = await fetch('/dashboard/calendar_valued?' + q.toString(), {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) return;
    biHeatRender(await r.json());
  } catch (e) { console.warn('value heat load failed', e); }
  biBriefLoad();  // 研判卡片跟着同月同领域 (读缓存·不烧 token)
}

// 0-100 价值分 → 1-5 星等级 (用户 2026-06-03 · 几百几千没法读·星级一眼懂热度等级)
// 阈值按 info_value 真实分布标定: BASE10 + 源6~22 + 新鲜0~20 + 反馈±·没反馈的新鲜好文 ~50。
// 若按 85/65 切·几乎全挤在 2-3★、5★ 永不出现 → 星级失效。 这里压低让内容铺满 1-5★:
//   5★(≥70)=⭐/👍 加持的真精品  4★(≥48)=顶级源新鲜文  3★(≥34)=新鲜常规
//   2★(≥22)=偏旧/弱源  1★(>0)=陈旧低值
function _biStarN(v) {
  v = +v || 0;
  if (v >= 70) return 5;
  if (v >= 48) return 4;
  if (v >= 34) return 3;
  if (v >= 22) return 2;
  if (v > 0) return 1;
  return 0;
}
function _biStars(v) {
  const n = _biStarN(v);
  // 前 n 个实心·后 (5-n) 个空心
  return '★★★★★☆☆☆☆☆'.slice(5 - n, 10 - n);
}

function biHeatRender(c) {
  const badge = document.getElementById('biCalBadge');
  if (badge) badge.textContent = c.year + '/' + String(c.month).padStart(2, '0');

  const dt = document.getElementById('biHeatDomains');
  if (dt) {
    dt.innerHTML = (c.domains || []).map(d => {
      const on = d.id === _biHeat.domain;
      const style = on ? `style="--dc:${d.color || 'var(--Daemonkey)'}"` : '';
      return `<button class="bi-heat-dom${on ? ' active' : ''}" ${style} onclick="biHeatSetDomain('${d.id}')">${d.icon || ''} ${escHtml(d.label)} <i>${d.count}</i></button>`;
    }).join('');
  }

  const sm = document.getElementById('biHeatSummary');
  if (sm) {
    let peakLabel = '—', peakStars = '';
    if (c.peak_day) {
      peakLabel = parseInt(c.peak_day.slice(5, 7), 10) + '/' + parseInt(c.peak_day.slice(-2), 10);
      const pd = (c.days || []).find(x => x.date === c.peak_day);
      if (pd) peakStars = `<span class="bi-stars" title="当天最高分 ${pd.peak_value || 0}/100">${_biStars(pd.peak_value)}</span>`;
    }
    sm.innerHTML = `活跃 <b>${c.active_days || 0}</b> 天 · 最热 <b>${peakLabel}</b> ${peakStars}`;
  }

  // 节律条 (卷五十八续 VII) · 周期仪式到期 + 起草 → spawnTask 开新会话 (不污染当前对话)
  const mr = (c.rituals || []).find(r => r.id === 'monthly_review');
  _biHeat.reviewPrompt = mr ? (mr.draft_prompt || '') : '';
  _biHeat.ritualByDate = {};
  for (const dd of (c.days || [])) {
    if (dd.ritual) {
      _biHeat.ritualByDate[dd.date] = {
        label: dd.ritual_label || '周期仪式',
        days: mr ? mr.days_left : '',
        done: mr ? mr.drafted_for_next : false,
      };
    }
  }
  const rs = document.getElementById('biRitualStrip');
  if (rs) {
    if (mr) {
      const dl = mr.days_left;
      const when = dl === 0 ? '<b>就是今天</b>' : (dl > 0 ? `还有 <b>${dl}</b> 天` : `<b>已过期 ${-dl} 天</b>`);
      const st = mr.drafted_for_next
        ? '<span class="bi-ritual-done">本期已起草</span>'
        : '<span class="bi-ritual-todo">未起草</span>';
      const dueMd = parseInt(mr.next_due.slice(5, 7), 10) + '/' + parseInt(mr.next_due.slice(-2), 10);
      rs.innerHTML = `<span class="bi-ritual-lbl"><i class="ri-flag-2-fill"></i> 月度复盘 · ${dueMd} · ${when} · ${st}</span>`
        + `<button class="bi-ritual-btn" type="button">一键起草</button>`;
      const btn = rs.querySelector('.bi-ritual-btn');
      if (btn) btn.onclick = biHeatRitualDraft;
      rs.style.display = '';
    } else {
      rs.innerHTML = '';
      rs.style.display = 'none';
    }
  }

  const grid = document.getElementById('biCalGrid');
  if (!grid) return;
  const days = c.days || [];
  if (!days.length) { grid.innerHTML = '<div class="bi-v3-empty">这个月还没有信号</div>'; return; }
  const max = c.max_value || 1;
  const mrDays = mr ? mr.days_left : '';
  const mrDone = mr ? mr.drafted_for_next : false;
  const _t = new Date();
  const todayStr = _t.getFullYear() + '-' + String(_t.getMonth() + 1).padStart(2, '0') + '-' + String(_t.getDate()).padStart(2, '0');
  grid.innerHTML = days.map(d => {
    if (d.out_of_month) return '<div class="bi-cal-cell oom"></div>';
    const ratio = max > 0 ? (d.value / max) : 0;
    // sqrt 让低价值的天也看得见·不至于被峰值压成全黑
    const op = d.value > 0 ? (0.16 + 0.84 * Math.sqrt(ratio)) : 0;
    const bg = d.value > 0 ? `background:rgba(159,122,234,${op.toFixed(3)})` : '';
    const dayNum = parseInt(d.date.slice(-2), 10);
    const ritualCls = d.ritual ? ' bi-cal-ritual' : '';
    const cls = 'bi-cal-cell' + (d.value > 0 ? ' has' : ' empty') + (d.date === todayStr ? ' today' : '') + ritualCls;
    // 数据塞 data-* · 自定义多行 tooltip 读它 (取代浏览器单行原生 title)
    // 点格子永远 = 开抽屉看 (仪式日也开 · 抽屉里给起草按钮 · 不让"点击"既看又起草打架)
    const click = (d.value > 0 || d.ritual) ? ` onclick="biHeatOpenDay('${d.date}')"` : '';
    const ritualData = d.ritual
      ? ` data-ritual="${escHtml(d.ritual_label || '周期仪式')}" data-ritualdays="${mrDays}" data-ritualdone="${mrDone ? 1 : 0}"`
      : '';
    const flag = d.ritual ? `<span class="bi-cal-flag"><i class="ri-flag-2-fill"></i></span>` : '';
    return `<div class="${cls}" style="${bg}" data-date="${d.date}" data-cnt="${d.count}" data-peakval="${d.peak_value || 0}" data-peak="${escHtml(d.peak_title || '')}"${ritualData}${click}><span class="bi-cal-num">${dayNum}</span>${flag}</div>`;
  }).join('');
  biHeatBindTip(grid);

  // D·节律时间线 (卷五十八续 VIII) · 复用 c.rituals (恒为当前·与显示月份无关) · 填驾驶舱元行
  const rb = document.getElementById('biRhythmBody');
  if (rb) {
    const rits = c.rituals || [];
    if (!rits.length) {
      rb.innerHTML = '<div class="bi-v3-empty">暂无周期仪式</div>';
    } else {
      rb.innerHTML = rits.map(r => {
        if (r.id === 'monthly_review') {
          const dl = r.days_left;
          const when = dl === 0 ? '今天' : (dl > 0 ? `还有 ${dl} 天` : `已过期 ${-dl} 天`);
          const st = r.drafted_for_next ? '<span class="bi-ritual-done">已起草</span>' : '<span class="bi-ritual-todo">未起草</span>';
          const last = r.last_done ? `上次 ${escHtml(r.last_done)}` : '从未做过';
          return `<div class="bi-rhythm-row"><i class="ri-calendar-check-fill"></i><div class="bi-rhythm-main"><b>月度复盘</b> · 下次 ${escHtml(r.next_due)} · ${when} · ${st}</div><div class="bi-rhythm-sub">${last}</div></div>`;
        }
        if (r.id === 'capability_mirror') {
          const en = r.enabled ? `每 ${r.interval_days} 天自动` : '未启用自动 (.env 开关)';
          const last = r.last_done ? `上次 ${escHtml(r.last_done)}` : '从未照过';
          return `<div class="bi-rhythm-row"><i class="ri-aspect-ratio-fill"></i><div class="bi-rhythm-main"><b>能力镜像</b> · ${en}</div><div class="bi-rhythm-sub">${last}</div></div>`;
        }
        return '';
      }).join('');
    }
  }
}

// ── 热力格子自定义 tooltip (多行 · 取代乱糟糟的浏览器原生 title) ──
let _biTipEl = null;
function _biTip() {
  if (!_biTipEl) {
    _biTipEl = document.createElement('div');
    _biTipEl.id = 'biHeatTip';
    _biTipEl.className = 'bi-heat-tip';
    document.body.appendChild(_biTipEl);
  }
  return _biTipEl;
}
function biHeatBindTip(grid) {
  if (grid.dataset.tipBound) return;  // 委托一次即可·grid 元素本身在重渲时保留
  grid.dataset.tipBound = '1';
  grid.addEventListener('mouseover', e => {
    const cell = e.target.closest('.bi-cal-cell.has, .bi-cal-cell.bi-cal-ritual');
    if (cell) biHeatTipShow(cell);
  });
  grid.addEventListener('mouseout', e => {
    const cell = e.target.closest('.bi-cal-cell.has, .bi-cal-cell.bi-cal-ritual');
    if (cell) biHeatTipHide();
  });
  grid.addEventListener('click', () => biHeatTipHide());  // 点开抽屉时收起
}
function biHeatTipShow(cell) {
  const tip = _biTip();
  const date = cell.dataset.date || '';
  const d = new Date(date + 'T00:00:00');
  const wd = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][d.getDay()] || '';
  const md = (d.getMonth() + 1) + ' 月 ' + d.getDate() + ' 日';
  const peak = cell.dataset.peak || '';
  const pv = +cell.dataset.peakval || 0;
  const cnt = +cell.dataset.cnt || 0;
  const ritual = cell.dataset.ritual || '';
  let html = `<div class="bi-tip-date">${md} · ${wd}</div>`;
  if (ritual) {
    const days = cell.dataset.ritualdays;
    const done = cell.dataset.ritualdone === '1';
    const whenTxt = days === '0' ? '就是今天'
      : (+days > 0 ? `还有 ${days} 天` : `已过期 ${-days} 天`);
    html += `<div class="bi-tip-ritual"><i class="ri-flag-2-fill"></i> ${escHtml(ritual)} · ${whenTxt} · ${done ? '本期已起草' : '未起草'}</div>`;
  }
  if (cnt > 0) {
    html += `<div class="bi-tip-val">最高 <span class="bi-stars" title="${pv}/100">${_biStars(pv)}</span> · ${cnt} 条信号</div>`;
    if (peak) html += `<div class="bi-tip-peak">峰值 · ${escHtml(peak)}</div>`;
  }
  if (ritual && cnt === 0) {
    html += `<div class="bi-tip-hint">点这天让 Daemonkey 起草本期复盘</div>`;
  } else if (cnt > 0) {
    html += `<div class="bi-tip-hint">点击看当天高分原文</div>`;
  }
  tip.innerHTML = html;
  tip.style.display = 'block';
  const r = cell.getBoundingClientRect();
  const tr = tip.getBoundingClientRect();
  let left = r.left + r.width / 2 - tr.width / 2;
  let top = r.top - tr.height - 8;
  left = Math.max(8, Math.min(left, window.innerWidth - tr.width - 8));
  if (top < 8) top = r.bottom + 8;  // 太靠顶 → 翻到格子下方
  tip.style.left = left + 'px';
  tip.style.top = top + 'px';
}
function biHeatTipHide() { if (_biTipEl) _biTipEl.style.display = 'none'; }

// 起草本期复盘 = 派发到新会话 (spawnTask · 不污染当前对话) · 节律条 + 抽屉按钮共用
function biHeatRitualDraft() {
  biHeatCloseDrawer();
  if (_biHeat.reviewPrompt && typeof spawnQuickly === 'function') spawnQuickly(_biHeat.reviewPrompt, '月度复盘起草');
}

function biHeatNav(delta) {
  if (!_biHeat.ym) return;
  let { y, m } = _biHeat.ym;
  m += delta;
  if (m < 1) { m = 12; y--; }
  if (m > 12) { m = 1; y++; }
  _biHeat.ym = { y, m };
  biHeatLoad();
}

function biHeatSetDomain(id) {
  _biHeat.domain = id || 'all';
  biHeatLoad();
}

async function biHeatOpenDay(dateStr) {
  if (!dateStr) return;
  const q = new URLSearchParams({ date: dateStr, vdomain: _biHeat.domain });
  let data = { items: [] };
  try {
    const r = await fetch('/dashboard/day_signals?' + q.toString(), {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (r.ok) data = await r.json();
  } catch (e) { console.warn('day_signals failed', e); }
  biHeatShowDrawer(dateStr, data);
}

function biHeatShowDrawer(dateStr, data) {
  biHeatCloseDrawer();
  const items = data.items || [];
  const rows = items.length
    ? items.map(biHeatItemHtml).join('')
    : '<div class="bi-v3-empty">这天没有高价值信号</div>';
  // 仪式日抽屉顶部加节律横幅 + 起草按钮 (点格子=看·起草=明确按钮·派发新会话)
  const ritual = (_biHeat.ritualByDate || {})[dateStr];
  const ritualBanner = ritual ? `
    <div class="bi-drawer-ritual">
      <span class="bi-drawer-ritual-txt"><i class="ri-flag-2-fill"></i> ${escHtml(ritual.label)}到期 · ${ritual.done ? '本期已起草' : '本期未起草'}</span>
      <button class="bi-ritual-btn" id="biDrawerDraftBtn" type="button">起草本期复盘</button>
    </div>` : '';
  const dr = document.createElement('div');
  dr.id = 'biHeatDrawer';
  dr.className = 'bi-heat-drawer';
  dr.innerHTML = `
    <div class="bi-heat-drawer-mask" onclick="biHeatCloseDrawer()"></div>
    <div class="bi-heat-drawer-panel">
      <div class="bi-heat-drawer-head">
        <span><i class="ri-fire-fill"></i> ${escHtml(dateStr)} · ${items.length} 条高价值信号</span>
        <button class="bi-heat-drawer-x" onclick="biHeatCloseDrawer()"><i class="ri-close-line"></i></button>
      </div>
      ${ritualBanner}
      <div class="bi-heat-drawer-body">${rows}</div>
    </div>`;
  document.body.appendChild(dr);
  const draftBtn = document.getElementById('biDrawerDraftBtn');
  if (draftBtn) draftBtn.onclick = biHeatRitualDraft;
}

function biHeatCloseDrawer() {
  const d = document.getElementById('biHeatDrawer');
  if (d) d.remove();
}

function biHeatItemHtml(it) {
  const fb = it.feedback || '';
  const canFb = !!it.item_id;
  const fbBtns = canFb ? `
    <div class="bi-sig-fb">
      <button class="${fb === 'starred' ? 'on' : ''}" title="收藏" onclick="biHeatFeedback('${it.item_id}','starred',this)"><i class="ri-star-line"></i></button>
      <button class="${fb === 'thumbs_up' ? 'on' : ''}" title="这类多关注" onclick="biHeatFeedback('${it.item_id}','thumbs_up',this)"><i class="ri-thumb-up-line"></i></button>
      <button class="${fb === 'thumbs_down' ? 'on' : ''}" title="别再推同类" onclick="biHeatFeedback('${it.item_id}','thumbs_down',this)"><i class="ri-thumb-down-line"></i></button>
    </div>` : '';
  const url = it.url || '';
  const titleHtml = url
    ? `<a class="bi-sig-title" href="${escHtml(url)}" target="_blank" rel="noopener">${escHtml(it.title)}</a>`
    : `<span class="bi-sig-title">${escHtml(it.title)}</span>`;
  return `<div class="bi-sig-row" data-iid="${it.item_id || ''}">
    <div class="bi-sig-val" title="价值 ${it.value}/100"><span class="bi-stars">${_biStars(it.value)}</span></div>
    <div class="bi-sig-main">
      ${titleHtml}
      <div class="bi-sig-meta">${escHtml(it.source || '')} · ${escHtml(it.domain || '')}</div>
    </div>
    ${fbBtns}
  </div>`;
}

async function biHeatFeedback(iid, feedback, btn) {
  if (!token || !iid) return;
  const row = btn.closest('.bi-sig-row');
  const wasActive = btn.classList.contains('on');
  const titleEl = row ? row.querySelector('.bi-sig-title') : null;
  const payload = {
    item_id: iid,
    feedback: wasActive ? null : feedback,
    title_hint: titleEl ? titleEl.textContent : '',
    url_hint: (titleEl && titleEl.href) ? titleEl.href : '',
  };
  try {
    const r = await fetch('/radar/feedback', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!r.ok) return;
  } catch (e) { return; }
  if (row) {
    row.querySelectorAll('.bi-sig-fb button').forEach(b => b.classList.remove('on'));
    if (!wasActive) btn.classList.add('on');
  }
  biHeatLoad();  // 反馈改了价值·热力图重算
}

// ══════════════════════════════════════════════════════════
//  趋势研判 (卷五十六 P2) · 跟热力图同月同领域 · LLM 给可行性 + 执行方案
//  数据走 /dashboard/trend_brief (workers/trend_brief.py · refresh=true 才烧 token)
// ══════════════════════════════════════════════════════════
function _biBriefScopeQuery() {
  if (!_biHeat.ym) { const n = new Date(); _biHeat.ym = { y: n.getFullYear(), m: n.getMonth() + 1 }; }
  const { y, m } = _biHeat.ym;
  return { mm: y + '-' + String(m).padStart(2, '0'), vd: _biHeat.domain || 'all' };
}

async function biBriefLoad() {
  const sc = document.getElementById('biBriefScope');
  const { mm, vd } = _biBriefScopeQuery();
  if (sc) sc.textContent = mm + (vd && vd !== 'all' ? (' · ' + vd) : '');
  const q = new URLSearchParams({ domain_filter: mm, vdomain: vd });
  try {
    const r = await fetch('/dashboard/trend_brief?' + q.toString(), {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) return;
    biBriefRender(await r.json());
  } catch (e) { console.warn('trend_brief load failed', e); }
}

async function biBriefGenerate() {
  const btn = document.getElementById('biBriefGenBtn');
  const body = document.getElementById('biBriefBody');
  const { mm, vd } = _biBriefScopeQuery();
  const ok = await DaemonkeyConfirm({
    title: '研判这段时间的趋势',
    message: {
      html: `让 Daemonkey 看一遍 <b>${mm}${vd && vd !== 'all' ? ' · ' + escHtml(vd) : ''}</b> 的高价值信号·
        给出趋势研判 + 执行方案。<span class="om-hint">会调一次 LLM (约 $0.05 · 10-30 秒)·结果会缓存·重看不重烧。</span>`
    },
    okText: '研判', cancelText: '再想想',
  });
  if (!ok) return;
  if (btn) { btn.disabled = true; btn.innerHTML = '<i class="ri-loader-4-line spin"></i> Daemonkey 研判中…'; }
  if (body) body.innerHTML = '<div class="bi-v3-empty">Daemonkey 正在看这段时间的信号·研判趋势 + 想执行方案…</div>';
  const q = new URLSearchParams({ domain_filter: mm, vdomain: vd, refresh: 'true' });
  try {
    const r = await fetch('/dashboard/trend_brief?' + q.toString(), {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (r.ok) biBriefRender(await r.json());
    else if (body) body.innerHTML = '<div class="bi-v3-empty">研判失败 (' + r.status + ') · 看 data/daemon.err</div>';
  } catch (e) {
    if (body) body.innerHTML = '<div class="bi-v3-empty">研判出错 · 网络或 daemon 问题</div>';
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<i class="ri-sparkling-2-line"></i> 重新研判'; }
  }
}

function biBriefRender(data) {
  const body = document.getElementById('biBriefBody');
  if (!body) return;
  const trends = (data && data.trends) || [];
  if (!trends.length) {
    const note = (data && (data.note || data.error)) || '还没研判';
    body.innerHTML = `<div class="bi-v3-empty">${escHtml(note)}</div>`;
    return;
  }
  const fire = n => '🔥'.repeat(Math.max(1, Math.min(5, n || 3)));
  body.innerHTML = trends.map(t => {
    const moves = (t.moves || []).map(m =>
      `<li>${escHtml(m)}</li>`).join('');
    const refs = (t.refs || []).map(rf => rf.url
      ? `<a href="${escHtml(rf.url)}" target="_blank" rel="noopener" title="${escHtml(rf.title || '')}">${escHtml(rf.source || '源')}</a>`
      : `<span title="${escHtml(rf.title || '')}">${escHtml(rf.source || '源')}</span>`).join('');
    return `<div class="bi-brief-item">
      <div class="bi-brief-item-head">
        <span class="bi-brief-fire" title="强度 ${t.intensity}/5">${fire(t.intensity)}</span>
        <span class="bi-brief-title">${escHtml(t.title)}</span>
      </div>
      <div class="bi-brief-summary">${escHtml(t.summary)}</div>
      ${moves ? `<div class="bi-brief-moves-label"><i class="ri-arrow-right-circle-line"></i> 下一步</div><ul class="bi-brief-moves">${moves}</ul>` : ''}
      ${refs ? `<div class="bi-brief-refs"><i class="ri-links-line"></i> 依据: ${refs}</div>` : ''}
    </div>`;
  }).join('');
  if (data.generated_at) {
    body.innerHTML += `<div class="bi-brief-foot">研判于 ${escHtml((data.generated_at || '').slice(0, 16).replace('T', ' '))} · 扫 ${data.items_scanned || 0} 条信号</div>`;
  }
}

// ── 信号流 ──
// 信号流状态 · 存原始数据 + 领域筛选 + 今日开关 (用户 2026-06-03 · 纯前端过滤·不重新 fetch)
const _biSig = { trends: [], radar: [], domain: 'all', todayOnly: false };

function fillBISignals(radar, trends) {
  _biSig.trends = (trends && trends.trends) || [];
  _biSig.radar = (radar && radar.items) || [];
  _biSigRenderDomains();
  _biSigRender();
}

// 这条信号是不是今天的 (published_at 优先·退 fetched_at·跟后端 item_date 口径一致)
function _biIsToday(r) {
  const now = new Date();
  const t = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0') + '-' + String(now.getDate()).padStart(2, '0');
  const src = r.published_at || r.fetched_at || '';
  if (!src) return false;
  const d = new Date(src);
  if (isNaN(d.getTime())) return String(src).slice(0, 10) === t;  // 解析失败退回字符串前10位
  const ds = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  return ds === t;
}

// 当前时间维度下的雷达池 (今日开关在这里收口·领域筛选各处再叠加)
function _biSigRadarPool() {
  return _biSig.todayOnly ? _biSig.radar.filter(_biIsToday) : _biSig.radar;
}

// 信号流领域 tab · 跟热力图同款 .bi-heat-dom · 按当前池里实际出现的领域动态生成
function _biSigRenderDomains() {
  const box = document.getElementById('biSigDomains');
  if (!box) return;
  const pool = _biSigRadarPool();
  const counts = {};
  pool.forEach(r => { const d = r.domain || 'ai'; counts[d] = (counts[d] || 0) + 1; });
  const total = pool.length + _biSig.trends.length;
  let html = `<button class="bi-heat-dom${_biSig.domain === 'all' ? ' active' : ''}" onclick="biSigSetDomain('all')"><i class="ri-stack-line"></i> 全部 <i>${total}</i></button>`;
  // 领域按数量从多到少排
  Object.keys(counts).sort((a, b) => counts[b] - counts[a]).forEach(id => {
    const m = RADAR_DOMAINS_META[id] || { icon: '', label: id, color: 'var(--Daemonkey)' };
    const on = _biSig.domain === id;
    const style = on ? `style="--dc:${m.color}"` : '';
    html += `<button class="bi-heat-dom${on ? ' active' : ''}" ${style} onclick="biSigSetDomain('${id}')">${m.icon || ''} ${escHtml(m.label)} <i>${counts[id]}</i></button>`;
  });
  box.innerHTML = html;
}

function biSigSetDomain(id) {
  _biSig.domain = id || 'all';
  _biSigRenderDomains();
  _biSigRender();
}

function biSigToggleToday() {
  _biSig.todayOnly = !_biSig.todayOnly;
  const btn = document.getElementById('biSigToday');
  if (btn) btn.classList.toggle('active', _biSig.todayOnly);
  _biSigRenderDomains();  // 领域 count 跟着今日重算 (当前领域在今日池里可能没了)
  _biSigRender();
}

function _biSigRender() {
  const list = document.getElementById('biSignalList');
  const cnt = document.getElementById('biSigCount');
  if (!list) return;

  const items = [];
  // 趋势是跨领域总结·只在"全部"下显示·选具体领域时只看该领域的雷达信号
  if (_biSig.domain === 'all') {
    _biSig.trends.forEach(t => items.push({ dotClass: 'trend', title: t.title || '(趋势)', meta: (t.summary || '').slice(0, 60), url: '' }));
  }
  _biSigRadarPool()
    .filter(r => _biSig.domain === 'all' || (r.domain || 'ai') === _biSig.domain)
    .forEach(r => items.push({ dotClass: 'radar', title: r.title_zh || r.title || r.title_en || '(信号)', meta: r.source_display || r.source || '', url: r.url || '' }));

  if (cnt) cnt.textContent = items.length + ' 条';
  if (!items.length) {
    list.innerHTML = `<div class="bi-v3-empty">${_biSig.todayOnly ? '今日这个领域还没有信号' : '这个领域暂无信号'}</div>`;
    _biBindSignalSync();
    return;
  }

  // 显示足够多条·让信号流内容超过热力卡高度 → 内部滚动填满·不在卡底留空 (用户 2026-06-03)
  list.innerHTML = items.slice(0, 120).map(it => {
    const u = it.url || '';
    const clk = u ? ` data-url="${escHtml(u)}" onclick="biSignalOpen(this)"` : '';
    return `
    <div class="bi-signal-item${u ? ' clickable' : ''}"${clk} title="${escHtml(it.meta)}">
      <div class="bi-signal-dot ${it.dotClass}"></div>
      <div class="bi-signal-body">
        <div class="bi-signal-title">${escHtml(it.title)}</div>
        <div class="bi-signal-meta">${escHtml(it.meta)}</div>
      </div>
    </div>`;
  }).join('');
  _biBindSignalSync();
}

// 点信号流条目 → 新标签打开原文 (radar 条目带 url·trend 无原文不可点) ·用户 2026-06-03
function biSignalOpen(el) {
  const u = el && el.dataset ? el.dataset.url : '';
  if (u) window.open(u, '_blank', 'noopener');
}

// ── 信号流高度跟随热力卡 (用户 2026-06-03 · 正方形格子 + 完美对齐的关键) ──
//   热力图格子保持正方形·高度随卡片宽度等比变 (分辨率/对话栏宽度都会变)。
//   纯 CSS 没法让"另一张卡跟随这张卡的高度"·所以用 ResizeObserver 盯热力卡·
//   把信号流卡的 height 实时设成跟它一样·信号流内部滚动 → 两卡严格等高·底部对齐·谁都不留空。
let _biSigRO = null;
function _biSyncSignalHeight() {
  const heat = document.querySelector('.bi-heat-card');
  const sig = document.querySelector('.bi-signal-card');
  if (!heat || !sig) return;
  // 上下堆叠(窄屏)时不强制等高·各自自然高
  if (Math.abs(heat.offsetTop - sig.offsetTop) > 4) { sig.style.height = ''; return; }
  const h = heat.offsetHeight;
  if (h > 0) sig.style.height = h + 'px';
}
function _biBindSignalSync() {
  const heat = document.querySelector('.bi-heat-card');
  if (!heat) return;
  if (_biSigRO) _biSigRO.disconnect();
  if (typeof ResizeObserver === 'undefined') { _biSyncSignalHeight(); return; }
  _biSigRO = new ResizeObserver(() => _biSyncSignalHeight());
  _biSigRO.observe(heat);
  _biSyncSignalHeight();
}

// ── chart.js (defer 本地加载) 就绪等待器 ──
// 卷五十六 · 2026-06-03 修: chart.umd.min.js 改 defer 后 · BI 首次渲染可能早于 Chart 就绪。
//   旧逻辑"没就绪就静默 return" → 之后无人重渲 → 雷达/环形图永久空白 (用户 实测撞到)。
//   改成: 没就绪就挂起 · 轮询等 Chart 到位 (最多 ~6s) · 一到位补渲一次。空白根治。
function _whenChartReady(cb, _tries) {
  if (typeof Chart !== 'undefined') { cb(); return; }
  _tries = _tries || 0;
  if (_tries > 60) return;  // ~6s 还没来 = 脚本真没加载到 · 放弃 · 别死循环
  setTimeout(() => _whenChartReady(cb, _tries + 1), 100);
}

// ── 雷达密度柱状图 ──
let biChartRadarInst = null;
function fillBIRadarChart(calData) {
  const canvas = document.getElementById('biChartRadar');
  if (!canvas) return;
  if (typeof Chart === 'undefined') { _whenChartReady(() => fillBIRadarChart(calData)); return; }  // defer 未就绪 · 等到了补渲
  const days = (calData.days || []).filter(d => !d.out_of_month);
  if (!days.length) return;

  const labels = days.map(d => d.date.slice(-2));
  const values = days.map(d => d.radar || 0);
  const ma = [];
  for (let i = 0; i < values.length; i++) {
    const s = values.slice(Math.max(0,i-3), Math.min(values.length,i+4));
    ma.push(s.reduce((a,b)=>a+b,0)/s.length);
  }

  const ctx = canvas.getContext('2d');
  if (biChartRadarInst) biChartRadarInst.destroy();
  biChartRadarInst = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label:'雷达信号', data:values, backgroundColor:'rgba(159,122,234,0.5)', borderRadius:3 },
        { label:'7日均线', data:ma, type:'line', borderColor:'#4FD1C5', borderWidth:1.5, pointRadius:0, tension:0.3, fill:false }
      ]
    },
    options: {
      responsive:true, maintainAspectRatio:false,
      plugins:{ legend:{ display:false } },
      scales: {
        x:{ ticks:{ color:'#666', font:{size:9}, maxTicksLimit:15 }, grid:{ display:false } },
        y:{ ticks:{ color:'#666', font:{size:9} }, grid:{ color:'rgba(255,255,255,0.04)' }, beginAtZero:true }
      },
      interaction:{ intersect:false, mode:'index' }
    }
  });
}

// ── 维度产出环形图 ──
let biChartDonutInst = null;
function fillBIDonutChart() {
  const canvas = document.getElementById('biChartDonut');
  if (!canvas) return;
  if (typeof Chart === 'undefined') { _whenChartReady(() => fillBIDonutChart()); return; }  // defer 未就绪 · 等到了补渲
  // 从 KPI bar 的 5 个数字反向读（已经渲染好了）
  const kpiCards = document.querySelectorAll('.bi-kpi-value');
  if (kpiCards.length < 5) return;

  const labels = ['雷达','趋势','报告','心愿','插件'];
  const colors = ['#9F7AEA','#4FD1C5','#63B3ED','#F6AD55','#888'];
  const values = [];
  kpiCards.forEach((el, i) => { if (i < 5) values.push(parseInt(el.textContent) || 0); });

  const legend = document.getElementById('biDonutLegend');
  if (legend) legend.innerHTML = labels.map((l,i) => `<div class="bi-donut-legend-item"><div class="bi-donut-legend-dot" style="background:${colors[i]}"></div>${l} ${values[i]}</div>`).join('');

  const ctx = canvas.getContext('2d');
  if (biChartDonutInst) biChartDonutInst.destroy();
  biChartDonutInst = new Chart(ctx, {
    type:'doughnut',
    data:{ labels, datasets:[{ data:values, backgroundColor:colors, borderColor:'#252525', borderWidth:2 }] },
    options:{ responsive:true, maintainAspectRatio:false, cutout:'65%', plugins:{ legend:{ display:false } } }
  });
}

// ── 最近动态 ──
function fillBITimeline(data) {
  const tl = document.getElementById('biTimeline');
  if (!tl) return;
  const domains = data.domains || [];
  const colors = {
    radar:'var(--Daemonkey)', trends:'#4FD1C5', reports:'#63B3ED',
    content:'#48BB78', dev:'#F6AD55', docs:'#4FD1C5',
    cognition:'var(--Daemonkey)', opportunities:'#F6AD55',
    wishlist:'#F6AD55', plugins:'var(--dim)',
  };
  const items = domains
    .filter(d => d.total > 0 && d.last_updated)
    .sort((a,b) => (b.last_updated||'').localeCompare(a.last_updated||''))
    .slice(0, 8);

  if (!items.length) { tl.innerHTML = '<div class="bi-v3-empty">暂无动态</div>'; return; }

  tl.innerHTML = items.map(d => {
    const t = d.last_updated ? new Date(d.last_updated).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'}) : '--:--';
    return `<div class="bi-tl-item">
      <span class="bi-tl-time">${t}</span>
      <div class="bi-tl-dot" style="background:${colors[d.id]||'var(--dim)'}"></div>
      <span class="bi-tl-text">${escHtml(d.label)} <span style="color:var(--dim2)">+${d.total}</span></span>
      <span class="bi-tl-domain">${escHtml(d.id)}</span>
    </div>`;
  }).join('');
}

// 卷四十六续 10 · BI 看板"今日动态" digest 卡 (用户 候选 E)
async function loadBIDigest() {
  if (!token) return;
  const slot = document.getElementById('biDigestSlot');
  if (!slot) return;
  try {
    const r = await fetch('/digest?hours=24', {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) {
      slot.innerHTML = `<div class="bi-digest-empty"><i class="ri-newspaper-fill"></i> 今日动态加载失败 [${r.status}]</div>`;
      return;
    }
    const data = await r.json();
    renderBIDigest(data);
  } catch (e) {
    slot.innerHTML = `<div class="bi-digest-empty"><i class="ri-newspaper-fill"></i> 今日动态网络出错: ${escHtml(e.message)}</div>`;
  }
}

function renderBIDigest(data) {
  const slot = document.getElementById('biDigestSlot');
  if (!slot) return;
  const items = (data && data.items) || [];
  const totals = (data && data.totals) || {};
  const newOnly = items.filter(it => (it.new_count || 0) > 0);

  if (newOnly.length === 0) {
    slot.innerHTML = `
      <div class="bi-digest bi-digest-quiet">
        <div class="bi-digest-head">
          <h3><i class="ri-newspaper-fill"></i> 今日动态 · 过去 ${data.since_hours}h</h3>
          <span class="bi-digest-meta">所有维度都安静 · 没有新数据</span>
        </div>
        <div class="bi-digest-empty-inner">
          用户 · 24h 内 7 个维度都没新增。要不要 ${renderAutopilotInlineBtn()}?
        </div>
      </div>`;
    return;
  }

  const tilesHtml = items.map(it => {
    const n = it.new_count || 0;
    const isHot = n > 0;
    const click = isHot ? `onclick="switchView('${jsStr(it.domain)}')"` : '';
    const cls = isHot ? 'bi-digest-tile bi-digest-hot' : 'bi-digest-tile bi-digest-cold';
    const hl = it.highlight ? `<div class="bi-digest-hl" title="${escHtml(it.highlight)}">${escHtml(it.highlight)}</div>` : '<div class="bi-digest-hl bi-digest-hl-empty">无更新</div>';
    return `
      <div class="${cls}" ${click} title="${isHot ? '点击进入 · 看新增内容' : '无新增'}">
        <div class="bi-digest-icon">${it.icon}</div>
        <div class="bi-digest-body">
          <div class="bi-digest-label">${escHtml(it.label)}</div>
          ${hl}
        </div>
        <div class="bi-digest-count">
          ${isHot ? `<span class="bi-digest-new">+${n}</span>` : '<span class="bi-digest-zero">0</span>'}
          <span class="bi-digest-total">/${it.total || 0}</span>
        </div>
      </div>`;
  }).join('');

  slot.innerHTML = `
    <div class="bi-digest">
      <div class="bi-digest-head">
        <h3><i class="ri-newspaper-fill"></i> 今日动态 · 过去 ${data.since_hours}h</h3>
        <span class="bi-digest-meta">
          ${totals.new_items || 0} 项新增 · ${totals.domains_with_new || 0} 个维度有动静
        </span>
      </div>
      <div class="bi-digest-grid">${tilesHtml}</div>
    </div>`;
}

function renderAutopilotInlineBtn() {
  return `<button class="bi-link" onclick="spawnQuickly('帮我自主巡航一遍 · 调 auto_pipeline 工具 · 三步全跑 · 跑完告诉我看到了什么 + 推 1-2 个最值得动手的机会', '自主巡航')">🛰️ 跑一圈巡航</button>`;
}

// 卷三十四 · Daemonkey 自主巡航 banner · 一键跑 radar→trends→opps
function renderAutopilotBanner() {
  return `
    <div class="bi-autopilot">
      <div class="bi-autopilot-left">
        <div class="bi-autopilot-icon">🛰️</div>
        <div class="bi-autopilot-text">
          <div class="bi-autopilot-title">Daemonkey 自主巡航</div>
          <div class="bi-autopilot-sub">一键跑完 信息雷达 → 今日趋势 → 掘金机会 (约 60-180s)</div>
        </div>
      </div>
      <button class="bi-autopilot-btn"
              onclick="spawnQuickly('Daemonkey 你自主巡航一遍·从信息雷达跑到掘金机会·把整个链路跑完·跑完跟我说看到了什么·给我推荐 1-2 个最值得动手的机会', '自主巡航')">
        <i class="ri-play-fill"></i> 现在巡一圈
      </button>
    </div>`;
}

function renderOppCard(o) {
  const fitIcon = { yes: '<i class="ri-checkbox-circle-fill"></i>', maybe: '<i class="ri-error-warning-fill"></i>', no: '<i class="ri-close-circle-fill"></i>' }[o.fit] || '?';
  const effortLabel = { light: '轻量', moderate: '中等', heavy: '重投入' }[o.cost_effort] || o.cost_effort;
  const upsideLabel = { low: '小', medium: '中', high: '高' }[o.upside] || o.upside;
  const stars = '<i class="ri-star-fill"></i>'.repeat(Math.max(1, Math.min(5, o.recommend || 3)));
  const dMeta = RADAR_DOMAINS_META[o.domain] || { icon: '·', label: o.domain, color: '#888' };
  return `
    <div class="bi-opp-card" style="border-left-color: ${dMeta.color}">
      <div class="bi-opp-head">
        <span class="bi-opp-domain">${dMeta.icon}</span>
        <span class="bi-opp-title">${escHtml(o.title || '?')}</span>
        <span class="bi-opp-rec">${stars}</span>
      </div>
      <div class="bi-opp-meta">
        <span title="用户 适配度">${fitIcon} ${o.fit || '?'}</span>
        <span title="投入预估">⏱️ ${effortLabel}</span>
        <span title="收益级别">📈 ${upsideLabel}</span>
      </div>
      <div class="bi-opp-summary">${escHtml(o.summary || '')}</div>
    </div>`;
}

// 让 BI 卡片可以一键回填到对话栏
function injectAndSend(text) {
  if (typeof $input !== 'undefined' && $input) {
    $input.value = text;
    $input.focus();
  }
  if (typeof window.send === 'function') window.send();
  else document.getElementById('send')?.click();
  // 手机端：把对话栏弹出来
  if (window.innerWidth <= 900) {
    document.querySelector('.chat-pane')?.classList.add('open');
  }
}

// 卷四十六续 12 · wish-165ea1f6 phase A · 工坊 form 提交后只填不发 · 用户 自己点 Send
//   autosend=true → 等价 injectAndSend · autosend=false (默认) → 只塞 input
function injectChat(text, opts) {
  const autosend = !!(opts && opts.autosend);
  if (typeof $input !== 'undefined' && $input) {
    $input.value = text || '';
    try { $input.dispatchEvent(new Event('input', { bubbles: true })); } catch (_) {}
    $input.focus();
    try { $input.setSelectionRange($input.value.length, $input.value.length); } catch (_) {}
  }
  if (autosend) {
    if (typeof window.send === 'function') window.send();
    else document.getElementById('send')?.click();
  }
  if (window.innerWidth <= 900) {
    document.querySelector('.chat-pane')?.classList.add('open');
  }
}
window.injectChat = injectChat;

// 点领域热力图块 · 跳到雷达并自动筛选该 domain
function filterRadarByDomain(domain) {
  radarDomainFilter = domain;
  localStorage.setItem('radar_domain_filter', domain);
  switchView('radar');
}

// ──────────────────────────────────────────────────────────────
// 全屏 dashboard view 数据拉取 + 渲染（点"全部 →"时使用）
// ──────────────────────────────────────────────────────────────

// 拆分安全网 (2026-07-12 · 成长档案→depot.js · 客户档案→clients.js):
//   升级瞬窗里 (拉到新 chat.html 但 depot.js/clients.js 还没到位·或 core.py 未重启)·
//   这些跨文件全局可能暂时未定义。用 typeof 兜底 → 优雅提示"重启后刷新"·而不是抛错卡死。
//   正常情况(两文件先于 chat.js 加载)完全不触发。
function _splitMissing(name) {
  if (typeof $dashView === 'undefined' || !$dashView) return;
  $dashView.innerHTML = `<div class="dash-head"><h2>${name}</h2></div>`
    + `<div class="dash-empty">这个维度的前端模块正在升级到位<br>重启 daemon 后刷新页面 (F5) 即可恢复。</div>`;
}
// 通用加载态 · 三点脉冲 (2026-08-20 · 实测 calendar 4.8s / wishlist 2.3s / radar 0.45s ·
//   纯文字"加载中…"在秒级等待里太单薄。 星尘是星图专属 · 这里用克制的三点。
//   text 参数给慢 tab 配专属文案 · 颜色全走 CSS 变量 · 深浅肤自适应)
function dashLoadingHTML(text) {
  return `<style>
@keyframes dkLdDot { 0%,60%,100%{transform:translateY(0);opacity:.35} 30%{transform:translateY(-6px);opacity:1} }
.dkLdDot { display:inline-block; width:7px; height:7px; border-radius:50%; background:var(--accent,#8a7dff); animation:dkLdDot 1.2s ease-in-out infinite; }
</style>
<div class="dash-empty" style="display:flex;flex-direction:column;align-items:center;gap:14px;padding-top:80px">
  <div><span class="dkLdDot"></span> <span class="dkLdDot" style="animation-delay:.15s"></span> <span class="dkLdDot" style="animation-delay:.3s"></span></div>
  <div style="font-size:12px;color:var(--dim);letter-spacing:1px">${text || '加载中'}</div>
</div>`;
}
function _depotTabs(domain) { if (typeof _maybeDepotTabs === 'function') _maybeDepotTabs(domain); }

async function loadDashboard(domain, opts = {}) {
  // 卷五十七 · 2026-06-06 · settings 是伪视图 (进 $detailPane · renderSettingsView 渲染 · 不走 /dashboard/{domain})。
  //   对话里跑工具后的静默刷新 (scheduleDashboardRefresh / stream finally) 会拿 currentView='settings' 调进来
  //   → fetch /dashboard/settings → 后端没这个域 → 404 → 把 用户 正看的设置页冲成"加载失败 [404]"。 这里直接短路。
  if (!domain || domain === 'settings') return;
  // 0.9.6 · 用户自定义维度 (static/user/user.js 里 Daemonkey.addDomain 注册的) ·
  //   后端没有 /dashboard/<它> · 渲染完全交给用户自己的 render。 出错兜住·别把整个中栏搞白。
  const _ud = Daemonkey._domains[domain];
  if (_ud && typeof _ud.render === 'function') {
    try { await _ud.render($dashView, opts); }
    catch (e) { $dashView.innerHTML = `<div class="dash-empty">用户面板「${domain}」渲染出错<br>${e.message}</div>`; }
    return;
  }
  // 工作室看板 · 起始屏 BI · 侧边栏直返入口 (用户 2026-08-06 · 复用起始屏渲染 · 零新逻辑)
  if (domain === 'bi') return renderDetailWelcome();
  // 成长档案 hub · 是个"虚拟维度" · 委派给当前激活的子标签 · 顶部补一条标签条
  if (domain === 'depot') {
    if (typeof loadDepot === 'function') return loadDepot(typeof _depotActive === 'string' ? _depotActive : 'cognition', opts);
    return _splitMissing('成长档案');
  }
  // 卷四十四 K · 切到非 workshop 前·先 unmount 工坊 (释放 ResizeObserver / events)
  if (domain !== 'workshop' && window.Daemonkey_WORKSHOP_VIEW && window.Daemonkey_WORKSHOP_VIEW.isMounted()) {
    window.Daemonkey_WORKSHOP_VIEW.unmount();
    $detailPane.classList.remove('workshop-active');
  }
  // 卷四十四 K · workshop 维度走特殊路径 · 不调 API · 直接 mount LiteGraph view
  if (domain === 'workshop') {
    if (!window.Daemonkey_WORKSHOP_VIEW) {
      $dashView.innerHTML = `<div class="dash-empty">⚠ workshop.js 没加载 · 检查 static/workshop.js</div>`;
      return;
    }
    $detailPane.classList.add('workshop-active');
    window.Daemonkey_WORKSHOP_VIEW.mount($detailPane);
    return;
  }
  if (!token) {
    $dashView.innerHTML = `
      <div class="dash-head"><h2>需要 token</h2></div>
      <div class="dash-empty">点右上角 ⚙ 填 token 后再试</div>`;
    return;
  }
  if (!opts.silent) {
    // 慢 tab 专属文案 (实测: calendar 4.8s · wishlist 2.3s · radar 0.45s · 其余 <0.2s)
    // memory_map 分支自己会覆盖成星尘加载态 · 这里给它什么无所谓
    const _loadHints = { calendar: '正在对齐日程', wishlist: '正在清点心愿', radar: '正在扫雷达', reviews: '正在翻复盘档案' };
    $dashView.innerHTML = dashLoadingHTML(_loadHints[domain]);
  }
  // wish-149eab3f phase B · 沉淀位走 /sinks 端点 · 不是 /dashboard/sinks
  if (domain === 'sinks') {
    try {
      const r = await fetch('/sinks', { headers: { 'Authorization': 'Bearer ' + token } });
      if (!r.ok) { $dashView.innerHTML = `<div class="dash-empty">加载失败 [${r.status}]</div>`; return; }
      const data = await r.json();
      renderSinks(data);
      _depotTabs('sinks');
    } catch (e) { $dashView.innerHTML = `<div class="dash-empty">网络出错: ${e.message}</div>`; }
    return;
  }
  // 记忆星图 tab · 走 /dashboard/memory_map 端点 (0.9.6 · 三道闸治理全景)
  if (domain === 'memory_map') {
    // 后端现算 PCA+漏斗+卫生 · 要 1-3s · 先上星尘加载态 (①A 多色 · BRO 选定)
    if (typeof memoryMapLoadingHTML === 'function') $dashView.innerHTML = memoryMapLoadingHTML();
    try {
      const r = await fetch('/dashboard/memory_map', { headers: { 'Authorization': 'Bearer ' + token } });
      if (!r.ok) { $dashView.innerHTML = `<div class="dash-empty">加载失败 [${r.status}]</div>`; return; }
      const data = await r.json();
      if (typeof renderMemoryMap === 'function') renderMemoryMap(data); else return _splitMissing('记忆星图');
      _depotTabs('memory_map');
    } catch (e) { $dashView.innerHTML = `<div class="dash-empty">网络出错: ${e.message}</div>`; }
    return;
  }
  // 月度复盘 tab · 走 /reviews 端点 · 不是 /dashboard/reviews (list_reviews 在 intelligence.py)
  if (domain === 'reviews') {
    try {
      const r = await fetch('/reviews', { headers: { 'Authorization': 'Bearer ' + token } });
      if (!r.ok) { $dashView.innerHTML = `<div class="dash-empty">加载失败 [${r.status}]</div>`; return; }
      const data = await r.json();
      if (typeof renderReviews === 'function') renderReviews(data); else return _splitMissing('月度复盘');
      _depotTabs('reviews');
    } catch (e) { $dashView.innerHTML = `<div class="dash-empty">网络出错: ${e.message}</div>`; }
    return;
  }
  // Daemonkey 日记 tab · 没独立端点 · 复用 /dashboard/cognition 数据 · 只渲染日记那块
  if (domain === 'diary') {
    try {
      const r = await fetch(`/dashboard/cognition${opts.refresh ? '?refresh=true' : ''}`, {
        headers: { 'Authorization': 'Bearer ' + token },
      });
      if (!r.ok) { $dashView.innerHTML = `<div class="dash-empty">加载失败 [${r.status}]</div>`; return; }
      const data = await r.json();
      if (typeof renderDiary === 'function') renderDiary(data); else return _splitMissing('Daemonkey 日记');
      _depotTabs('diary');
    } catch (e) { $dashView.innerHTML = `<div class="dash-empty">网络出错: ${e.message}</div>`; }
    return;
  }
  const qs = opts.refresh ? '?refresh=true' : '';
  try {
    const r = await fetch(`/dashboard/${domain}${qs}`, {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) {
      $dashView.innerHTML = `<div class="dash-empty">加载失败 [${r.status}]</div>`;
      return;
    }
    const data = await r.json();
    if (domain === 'radar') renderRadar(data);
    else if (domain === 'trends') renderTrends(data);
    else if (domain === 'reports') renderReports(data);
    else if (domain === 'opportunities') renderOpportunities(data);
    else if (domain === 'cognition') { if (typeof renderCognition === 'function') renderCognition(data); else _splitMissing('画像'); }
    else if (domain === 'feasibility') renderFeasibility(data);
    else if (domain === 'knowledge') renderKnowledge(data);
    else if (domain === 'clients') { if (typeof renderClients === 'function') renderClients(data); else _splitMissing('客户档案'); }
    else if (domain === 'playbooks') { if (typeof renderPlaybooks === 'function') renderPlaybooks(data); else _splitMissing('技能库'); }
    else if (domain === 'execution') renderExecution(data);
    else if (domain === 'favorites') renderFavorites(data);
    else if (domain === 'calendar') renderCalendar(data);
    else if (domain === 'plugins') renderPlugins(data);
    else if (domain === 'wishlist') renderWishlist(data);
    else if (domain === 'scheduled_tasks') renderScheduledTasks(data);
    else if (['content', 'design', 'dev', 'docs'].includes(domain)) renderWorkshop(domain, data);
    else renderDashboardStub(domain, data);
    _depotTabs(domain);
  } catch (e) {
    $dashView.innerHTML = `<div class="dash-empty">网络出错: ${e.message}</div>`;
  }
}

// ── 0.5.0 · ⏰ 定时任务 (NLP 建·到点跑 LLM turn·复用 fav-* 卡片体系) ──
function _schedLocalTime(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('zh-CN', {
      month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    });
  } catch (e) { return iso; }
}

function _schedSummaryCN(sch) {
  if (!sch) return '?';
  if (sch.type === 'daily') return `每天 ${sch.time || '09:00'}`;
  if (sch.type === 'weekly') {
    const wd = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
    const i = sch.weekday;
    return `每${(typeof i === 'number' && i >= 0 && i < 7) ? wd[i] : '周?'} ${sch.time || '09:00'}`;
  }
  if (sch.type === 'interval') return `每 ${sch.interval_min || '?'} 分钟`;
  if (sch.type === 'once') return `一次性 @ ${_schedLocalTime(sch.once_at)}`;
  return sch.type || '?';
}

async function _schedAction(path, body) {
  try {
    const r = await fetch(path, {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) { alert('操作失败 [' + r.status + ']'); return; }
    loadDashboard('scheduled_tasks');
  } catch (e) { alert('网络出错: ' + e.message); }
}

function renderScheduledTasks(data) {
  if (data && data.error) {
    $dashView.innerHTML = `
      <div class="dash-head"><h2><i class="ri-timer-2-fill"></i> 定时任务</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }
  const tasks = (data && data.tasks) || [];
  const alive = data && data.scheduler_alive;
  const draft = (data && data.draft_prompt) || '帮我建个定时任务：每天早上9点扫一遍AI行情并汇总';
  const banner = `
    <p class="muted" style="margin-bottom:12px">
      调度线程: ${alive ? '<span style="color:#4fd1c5">运行中</span>' : '<span style="color:#fc8181">未运行</span>'}
      · 新建 / 修改请直接对话说（"每天9点扫AI行情" / "每周五提醒我复盘"）· 我会建好放这里。
    </p>`;

  if (tasks.length === 0) {
    $dashView.innerHTML = `
      <div class="dash-head"><h2><i class="ri-timer-2-fill"></i> 定时任务</h2>
        <span class="dash-meta">空</span></div>
      ${banner}
      <div class="dash-empty">
        <p>还没有定时任务</p>
        <p class="muted" style="margin-top:8px">对我说一句「${escHtml(draft)}」就能建第一个。</p>
      </div>`;
    return;
  }

  const cards = tasks.map(t => {
    const a = t.action || {};
    const enabled = !!t.enabled;
    const color = enabled ? '#4fd1c5' : '#6b7280';
    const kindLabel = a.kind === 'reminder'
      ? '<i class="ri-notification-3-fill"></i> 提醒'
      : '<i class="ri-play-circle-fill"></i> 执行';
    const last = t.last_run_at
      ? `<div class="fav-note">上次 ${_schedLocalTime(t.last_run_at)} [${escHtml(t.last_run_status || '')}] ${escHtml((t.last_run_summary || '').slice(0, 80))}</div>`
      : '';
    return `
      <div class="fav-card" style="border-left-color:${color}">
        <div class="fav-card-top">
          <span class="fav-kind" style="color:${color}">${kindLabel} · ${escHtml(_schedSummaryCN(t.schedule))}</span>
          <span class="fav-domain">${enabled ? '✅ 启用' : '⏸ 停用'}${a.notify_wechat ? ' · 📱微信' : ''}</span>
        </div>
        <div class="fav-title">${escHtml(a.prompt || t.raw_text || '(无指令)')}</div>
        <div class="fav-note">下次 ${_schedLocalTime(t.next_run_at)} · 已跑 ${t.runs_completed || 0} 次</div>
        ${last}
        <div class="fav-foot">
          <span class="muted">${escHtml(t.id)}</span>
          <div class="fav-actions">
            <button class="fav-open sched-toggle" data-id="${escHtml(t.id)}" data-enabled="${enabled ? '1' : '0'}">${enabled ? '停用' : '启用'}</button>
            <button class="fav-remove sched-del" data-id="${escHtml(t.id)}">删除</button>
          </div>
        </div>
      </div>`;
  }).join('');

  $dashView.innerHTML = `
    <div class="dash-head">
      <h2><i class="ri-timer-2-fill"></i> 定时任务</h2>
      <span class="dash-meta">${tasks.length} 个 · ${tasks.filter(t => t.enabled).length} 启用</span>
    </div>
    ${banner}
    <div class="fav-grid">${cards}</div>`;

  $dashView.querySelectorAll('.sched-toggle').forEach(btn => {
    btn.onclick = () => _schedAction('/dashboard/scheduled_tasks/toggle', {
      task_id: btn.getAttribute('data-id'),
      enabled: btn.getAttribute('data-enabled') !== '1',
    });
  });
  $dashView.querySelectorAll('.sched-del').forEach(btn => {
    btn.onclick = async () => {
      const ok = await DaemonkeyConfirm({
        title: '删除定时任务', message: '删掉这个定时任务吗？', okText: '删除', cancelText: '保留',
      });
      if (!ok) return;
      _schedAction('/dashboard/scheduled_tasks/delete', { task_id: btn.getAttribute('data-id') });
    };
  });
}

// ── 卷二十六 · 工坊维度 · content / design / dev / docs ──
function renderWorkshop(domain, data) {
  if (data && data.error) {
    const m = DOMAIN_META[domain] || {};
    $dashView.innerHTML = `
      <div class="dash-head"><h2>${m.icon} ${m.label}</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }
  const icon = data.icon || (DOMAIN_META[domain] || {}).icon || '·';
  const label = data.label || (DOMAIN_META[domain] || {}).label || domain;
  const items = data.items || [];
  const kinds = data.kinds || [];
  const dir = data.directory || '';

  let html = `
    <div class="dash-head">
      <h2>${icon} ${label}</h2>
      <span class="meta">${items.length} 份 · ${escHtml(dir)}</span>
      <button onclick="backToChat()">✕ 收起</button>
      <button onclick="loadDashboard('${domain}')">刷新</button>
    </div>`;

  // 引导卡 · 显示这个维度的 kind 选项
  if (kinds.length > 0) {
    html += `
      <div class="workshop-kinds">
        <span class="wk-label">细分:</span>
        ${kinds.map(k => `<span class="wk-chip">${escHtml(k)}</span>`).join('')}
      </div>`;
  }

  if (data.description) {
    html += `<div class="workshop-desc">${escHtml(data.description)}</div>`;
  }

  if (items.length === 0) {
    html += `
      <div class="dash-stub">
        <h3>工坊还空</h3>
        <div>${escHtml(data.empty_hint || '跟 Daemonkey 说「做一份 X」· Daemonkey 会调 draft_studio 工具落 markdown。')}</div>
      </div>`;
  } else {
    html += `<div class="workshop-list">`;
    for (const it of items) {
      const kind = it.kind || '';
      const kindBadge = kind ? `<span class="wk-kind-badge">${escHtml(kind)}</span>` : '';
      const safeName = encodeURIComponent(it.name || '');
      const dlUrl = `/workshop/file/${encodeURIComponent(domain)}/${safeName}?token=${encodeURIComponent(token || '')}`;
      html += `
        <div class="workshop-card">
          <div class="wk-head">
            <a class="wk-title" href="javascript:void(0)" data-domain="${escHtml(domain)}" data-name="${escHtml(it.name || '')}">${escHtml(it.title || it.name || '')}</a>
            ${kindBadge}
          </div>
          <div class="wk-meta">
            <span>${escHtml(it.created_at || '')}</span>
            <span class="wk-path">${escHtml(it.path || '')}</span>
            <button class="wk-btn wk-preview" data-domain="${escHtml(domain)}" data-name="${escHtml(it.name || '')}" title="在 webui 中预览 markdown"><i class="ri-eye-line"></i> 预览</button>
            <button class="wk-btn wk-reveal" data-domain="${escHtml(domain)}" data-name="${escHtml(it.name || '')}" title="本机用默认应用打开 (Typora / VSCode / 记事本)"><i class="ri-external-link-line"></i> 外部打开</button>
            <a class="wk-btn wk-dl" href="${escHtml(dlUrl)}" download="${escHtml(it.name || '')}" title="下载 .md 文件">下载 ↓</a>
          </div>
          ${it.excerpt ? `<div class="wk-excerpt">${escHtml(it.excerpt)}</div>` : ''}
        </div>`;
    }
    html += `</div>`;
  }
  $dashView.innerHTML = html;

  // 卷四十六续 8 · workshop 卡按钮事件绑定
  $dashView.querySelectorAll('.wk-title[data-name], .wk-preview').forEach(el => {
    el.onclick = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const dom = el.getAttribute('data-domain');
      const nm = el.getAttribute('data-name');
      if (dom && nm) loadWorkshopPreview(dom, nm);
    };
  });
  $dashView.querySelectorAll('.wk-reveal').forEach(el => {
    el.onclick = async (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const dom = el.getAttribute('data-domain');
      const nm = el.getAttribute('data-name');
      if (!dom || !nm) return;
      el.disabled = true;
      const orig = el.textContent;
      el.textContent = '⏳ 打开中…';
      try {
        const r = await fetch(`/workshop/reveal/${encodeURIComponent(dom)}/${encodeURIComponent(nm)}`, {
          method: 'POST',
          headers: { 'Authorization': 'Bearer ' + token },
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok || !data.ok) {
          alert(`外部打开失败 [${r.status}]: ${(data && data.error) || '未知错误'}\n${(data && data.fallback_hint) || '试试点「下载 ↓」用浏览器拿到文件后系统会用默认应用打开。'}`);
        } else {
          el.innerHTML = '<i class="ri-check-fill"></i> 已打开';
          setTimeout(() => { el.textContent = orig; el.disabled = false; }, 1500);
          return;
        }
      } catch (e) {
        alert(`外部打开网络出错: ${e.message}`);
      }
      el.textContent = orig;
      el.disabled = false;
    };
  });
}

// 卷四十六续 8 · 工坊产物在线预览 (md → mdRender)
async function loadWorkshopPreview(domain, name) {
  if (!token || !domain || !name) return;
  $dashView.innerHTML = `<div class="dash-empty">加载预览中...</div>`;
  try {
    const r = await fetch(`/workshop/preview/${encodeURIComponent(domain)}/${encodeURIComponent(name)}`, {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) {
      const errTxt = await r.text();
      $dashView.innerHTML = `<div class="dash-empty">预览失败 [${r.status}]<br>${escHtml(errTxt.slice(0,300))}</div>`;
      return;
    }
    const data = await r.json();
    renderWorkshopPreview(domain, data);
  } catch (e) {
    $dashView.innerHTML = `<div class="dash-empty">网络出错: ${e.message}</div>`;
  }
}

function renderWorkshopPreview(domain, d) {
  const name = d.name || '?';
  const meta = d.meta || {};
  const md = d.markdown || '';
  const m = DOMAIN_META[domain] || {};
  const dlUrl = `/workshop/file/${encodeURIComponent(domain)}/${encodeURIComponent(name)}?token=${encodeURIComponent(token || '')}`;

  const coverBlock = (meta.title || meta.kind || meta.created_at) ? `
    <div class="rp-cover">
      ${meta.title ? `<div class="rp-cover-title">${escHtml(meta.title)}</div>` : ''}
      <div class="rp-cover-meta">
        ${meta.kind ? `<span>类型 · ${escHtml(meta.kind)}</span>` : ''}
        ${meta.created_at ? `<span>生成于 ${escHtml(meta.created_at)}</span>` : ''}
        ${meta.domain ? `<span>维度 · ${escHtml(meta.domain)}</span>` : ''}
      </div>
    </div>
  ` : '';

  $dashView.innerHTML = `
    <div class="dash-head">
      <h2>📖 ${escHtml(meta.title || name)}</h2>
      <button onclick="loadDashboard('${jsStr(domain)}')">← 返回 ${escHtml(m.label || domain)}</button>
      <button onclick="revealWorkshopFile('${jsStr(domain)}', '${jsStr(name)}')" title="本机用默认应用打开"><i class="ri-external-link-line"></i> 外部打开</button>
      <a class="rp-dl-btn" href="${escHtml(dlUrl)}" download="${escHtml(name)}">下载 .md ↓</a>
    </div>
    <div class="rp-meta-strip">
      <span class="rp-src rp-src-md"><i class="ri-file-text-fill"></i> markdown 源 · ${(d.size_bytes / 1024).toFixed(1)} KB</span>
      <span class="rp-note">${escHtml(d.path || '')}</span>
    </div>
    <article class="rp-body">
      ${coverBlock}
      <div class="rp-md">${mdRender(md)}</div>
    </article>
  `;
}

async function revealWorkshopFile(domain, name) {
  if (!token || !domain || !name) return;
  try {
    const r = await fetch(`/workshop/reveal/${encodeURIComponent(domain)}/${encodeURIComponent(name)}`, {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token },
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok || !data.ok) {
      alert(`外部打开失败 [${r.status}]: ${(data && data.error) || '未知错误'}\n${(data && data.fallback_hint) || '试试点下载按钮。'}`);
    }
  } catch (e) {
    alert(`外部打开网络出错: ${e.message}`);
  }
}

// 通用产物"用本机软件打开"(generate_presentation / generate_report 等的 open_path)
// turn 结束时把本轮生成的产物渲成"打开"动作条·放对话底部(卷七十九 · 用户 反馈按钮位置不符阅读习惯)
function flushOpenActions(state) {
  const list = state && state._pendingOpens;
  if (!list || !list.length) { if (list) list.length = 0; return; }
  if (!state.$container) { list.length = 0; return; }
  const bar = document.createElement('div');
  bar.className = 'open-actions';
  const seen = new Set();
  list.forEach(({ path }) => {
    if (!path || seen.has(path)) return;
    seen.add(path);
    const name = String(path).split(/[\\/]/).pop() || path;
    const row = document.createElement('div');
    row.className = 'open-actions-row';
    const label = document.createElement('span');
    label.className = 'open-actions-name';
    label.innerHTML = '<i class="ri-file-line"></i> ';
    label.appendChild(document.createTextNode(name));
    const btn = document.createElement('button');
    btn.className = 'tr-open';
    btn.innerHTML = '<i class="ri-external-link-line"></i> 用对应软件打开';
    btn.title = path;
    btn.onclick = () => revealFile(path, btn);
    row.appendChild(label);
    row.appendChild(btn);
    bar.appendChild(row);
  });
  state.$container.appendChild(bar);
  try { scrollToBottom(state.$container, { force: false }); } catch (e) { /* noop */ }
  list.length = 0;
}

// 生图工具产出的图 · turn 末渲成对话内可点放大的图廊(卷七十九续 · 用户 反馈批量图不显示)
// URL 已是 daemon 可服务路径(/presentations/... 或 /workshop/outputs/...)· 点图走全局 .md-img 灯箱
function flushImages(state) {
  const list = state && state._pendingImages;
  if (!list || !list.length) { if (list) list.length = 0; return; }
  if (!state.$container) { list.length = 0; return; }
  const gal = document.createElement('div');
  gal.className = 'dk-img-gallery';
  const seen = new Set();
  list.forEach((u) => {
    if (!u || seen.has(u)) return;
    seen.add(u);
    const im = document.createElement('img');
    im.className = 'md-img';
    im.loading = 'lazy';
    im.src = u;
    im.alt = '';
    im.dataset.full = u;
    gal.appendChild(im);
  });
  if (gal.children.length) {
    state.$container.appendChild(gal);
    try { scrollToBottom(state.$container, { force: false }); } catch (e) { /* noop */ }
  }
  list.length = 0;
}

async function revealFile(path, btn) {
  if (!path) return;
  const old = btn ? btn.innerHTML : '';
  if (btn) { btn.disabled = true; btn.innerHTML = '<i class="ri-loader-4-line"></i> 打开中…'; }
  try {
    const r = await fetch('/reveal-file', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || !j.ok) {
      const msg = (j && (j.error || j.detail || j.hint)) || ('HTTP ' + r.status);
      if (btn) { btn.innerHTML = '<i class="ri-error-warning-line"></i> 打不开'; btn.title = msg; btn.disabled = false; }
      else alert('打开失败: ' + msg);
      return;
    }
    if (btn) {
      btn.innerHTML = '<i class="ri-check-line"></i> 已打开';
      setTimeout(() => { btn.disabled = false; btn.innerHTML = old; }, 1800);
    }
  } catch (e) {
    if (btn) { btn.innerHTML = '<i class="ri-error-warning-line"></i> 打不开'; btn.title = String(e); btn.disabled = false; }
  }
}

function renderDashboardStub(domain, data) {
  const m = DOMAIN_META[domain] || {};
  $dashView.innerHTML = `
    <div class="dash-head">
      <h2>${m.icon || ''} ${m.label || domain}</h2>
      <button onclick="backToChat()">✕ 收起</button>
    </div>
    <div class="dash-stub">
      <h3>这个维度还在开发中</h3>
      <div>${data && data.note ? data.note : '见 docs/STUDIO-LAYOUT.md 第五章 MVP 优先级'}</div>
      <div style="margin-top:14px; font-size:11px;">
        想加快这一维度？回对话跟 Daemonkey 说：「优先做 ${m.label || domain} 维度」
      </div>
    </div>`;
}

// ─────────────────────────────────────────────────────────
// 卷二十九 · <i class="ri-bar-chart-fill"></i> 可行性分析（能力对照分组）
// ─────────────────────────────────────────────────────────
const _VERDICT_BADGES = {
  go:          { label: '<i class="ri-circle-fill" style="color:#22c55e"></i> 推荐做',       color: '#22c55e' },
  conditional: { label: '<i class="ri-circle-fill" style="color:#eab308"></i> 有条件可做', color: '#eab308' },
  wait:        { label: '⏸ 先等等',       color: '#94a3b8' },
  skip:        { label: '<i class="ri-circle-fill" style="color:#ef4444"></i> 不建议',       color: '#ef4444' },
};

function renderFeasibility(data) {
  if (data && data.error) {
    $dashView.innerHTML = `
      <div class="dash-head"><h2><i class="ri-bar-chart-fill"></i> 可行性分析</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }

  // 列表视图 · list_feasibility 返回 {generated_at, total, items}
  const items = data.items || [];

  let html = `
    <div class="dash-head">
      <h2><i class="ri-bar-chart-fill"></i> 可行性分析</h2>
      <span class="meta">${items.length} 份分析 · 共 ${data.total || items.length}</span>
      <button onclick="backToChat()">✕ 收起</button>
      <button onclick="loadDashboard('feasibility')">刷新</button>
      <button onclick="switchView('opportunities')" title="去 💎 掘金机会">← <i class="ri-diamond-fill"></i> 机会</button>
    </div>
    <div class="feas-intro">
      把 <i class="ri-diamond-fill"></i> 掘金机会卡展开成完整可行性 · 风险/资源/能力/成本/替代方案。
      在机会卡上点 <b>💰估算成本</b> · 或跟 Daemonkey 说「分析第 N 个机会的可行性」。
    </div>`;

  if (items.length === 0) {
    html += `
      <div class="feas-empty">
        <div style="font-size:32px;margin-bottom:12px"><i class="ri-bar-chart-fill"></i></div>
        <div>还没分析过任何机会</div>
        <div class="hint">
          先去 <i class="ri-diamond-fill"></i> 掘金机会 · 选一个想做的 · 点「💰估算成本」就会跑到这里。
        </div>
      </div>`;
    $dashView.innerHTML = html;
    return;
  }

  // 卷三十一 · 闭环状态徽章
  const _STATUS_BADGE = {
    not_started: { lbl: '<i class="ri-add-circle-fill"></i> 未启动', cls: 'fb-not_started' },
    in_progress: { lbl: '<i class="ri-play-fill"></i> 进行中', cls: 'fb-in_progress' },
    completed:   { lbl: '<i class="ri-check-fill"></i> 已完成', cls: 'fb-completed' },
    abandoned:   { lbl: '<i class="ri-close-fill"></i> 已放弃', cls: 'fb-abandoned' },
  };
  html += `<div class="feas-list">`;
  for (const it of items) {
    const v = _VERDICT_BADGES[it.verdict] || { label: '?', color: '#666' };
    const score = it.feasibility_score || 0;
    const scoreColor = score >= 70 ? '#22c55e' : score >= 40 ? '#eab308' : '#ef4444';
    const st = it.status || 'not_started';
    const stb = _STATUS_BADGE[st] || { lbl: st, cls: '' };
    html += `
      <div class="feas-card" onclick="loadFeasibilityDetail('${jsStr(it.opp_id)}')">
        <div class="feas-card-head">
          <span class="feas-verdict" style="background:${v.color}22;color:${v.color}">
            ${v.label}
          </span>
          <span class="feas-card-status feas-fb-${st}">${stb.lbl}</span>
          <span class="feas-score" style="color:${scoreColor}">
            ${score}<span class="feas-score-tot">/100</span>
          </span>
        </div>
        <div class="feas-card-title">${escHtml(it.opp_title || '?')}</div>
        <div class="feas-card-domain">领域: ${escHtml(it.opp_domain || '?')}</div>
        ${it.verdict_reason ? `<div class="feas-card-reason">${escHtml(it.verdict_reason)}</div>` : ''}
        <div class="feas-card-actions">
          <button class="feas-act" onclick="event.stopPropagation();loadFeasibilityDetail('${jsStr(it.opp_id)}')">
            <i class="ri-search-fill"></i> 查看完整分析
          </button>
        </div>
      </div>`;
  }
  html += `</div>`;
  $dashView.innerHTML = html;
}

async function runFeasibilityFromOpp(opp_id, idx) {
  // 卷四十六续 9 · 用户 反馈"可行性分析也是不通过 LLM 来跑·我想他和信息雷达今日趋势对齐·都是 LLM 开始呈现思考过程·最后刷新结果"
  // 旧路径: 直接 fetch /dashboard/feasibility?refresh=true (HTTP 黑盒 · 整个面板空白等 5-15s)
  // 新路径: injectAndSend → LLM 调 analyze_feasibility 工具 · 用户 看分析过程 · 完成后 MUTATING_TOOLS 自动 reload feasibility view
  if (opp_id) {
    spawnTask(
      `分析机会 ${opp_id} (第 ${idx} 个) 的可行性 · ` +
      `调 analyze_feasibility 工具 · 参数 action=analyze, opp_id="${opp_id}" · ` +
      `跑完告诉我 verdict (go/conditional/wait/skip) + 关键风险 + 你最担心什么 + 推不推荐 用户 真动手`,
      `可行性分析 · 机会#${idx}`
    );
  } else {
    spawnTask(
      `分析第 ${idx} 个机会的可行性 · ` +
      `调 analyze_feasibility 工具 · 参数 action=analyze, opp_index=${idx} · ` +
      `跑完告诉我 verdict (go/conditional/wait/skip) + 关键风险 + 你最担心什么 + 推不推荐 用户 真动手`,
      `可行性分析 · 机会#${idx}`
    );
  }
}

async function loadFeasibilityDetail(opp_id) {
  if (!token) return;
  $dashView.innerHTML = `<div class="dash-empty">加载分析中…</div>`;
  try {
    const r = await fetch(`/dashboard/feasibility?domain_filter=${encodeURIComponent(opp_id)}`, {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) {
      $dashView.innerHTML = `<div class="dash-empty">加载失败 [${r.status}]</div>`;
      return;
    }
    const data = await r.json();
    renderFeasibilityDetail(data);
  } catch (e) {
    $dashView.innerHTML = `<div class="dash-empty">出错: ${e.message}</div>`;
  }
}

async function renderFeasibilityDetail(d) {
  if (!d || !d.opp_id) {
    $dashView.innerHTML = `<div class="dash-empty">数据为空</div>`;
    return;
  }
  const v = _VERDICT_BADGES[d.verdict] || { label: '?', color: '#666' };
  const score = d.feasibility_score || 0;
  const scoreColor = score >= 70 ? '#22c55e' : score >= 40 ? '#eab308' : '#ef4444';

  // 卷三十三 · 查可行性的 <i class="ri-star-fill"></i> 状态
  const favSet = await _fetchFavoriteSet('feasibility');
  const isFav = favSet.has(d.opp_id);

  let html = `
    <div class="dash-head">
      <h2><i class="ri-bar-chart-fill"></i> 可行性分析</h2>
      <button onclick="loadDashboard('feasibility')">← 返回列表</button>
      <button onclick="loadFeasibilityDetail('${jsStr(d.opp_id)}')">刷新</button>
      <button class="feas-star-btn ${isFav ? 'starred' : ''}"
              data-ref="${escHtml(d.opp_id)}"
              data-title="${escHtml(d.opp_title || '')}"
              data-domain="${escHtml(d.opp_domain || '')}"
              title="${isFav ? '已收藏 · 点击取消' : '收藏此可行性'}">
        ${isFav ? '★ 已收藏' : '☆ 收藏'}
      </button>
    </div>
    <div class="feas-detail">
      <div class="feas-detail-head">
        <div class="feas-detail-title">${escHtml(d.opp_title || '?')}</div>
        <div class="feas-detail-meta">
          领域: ${escHtml(d.opp_domain || '?')} ·
          ${d.elapsed_ms ? `分析用时: ${(d.elapsed_ms / 1000).toFixed(1)}s · ` : ''}
          模型: ${escHtml(d.model || '')}
        </div>
      </div>

      <div class="feas-summary">
        <div class="feas-score-big" style="color:${scoreColor}">
          ${score}<span class="feas-score-big-tot">/100</span>
        </div>
        <div class="feas-summary-right">
          <div class="feas-verdict-big" style="background:${v.color}22;color:${v.color}">
            ${v.label}
          </div>
          <div class="feas-verdict-reason">${escHtml(d.verdict_reason || '')}</div>
        </div>
      </div>`;

  // ───────── 卷三十二补丁 · 信源（宪法第 5 条 · 人机认知对齐）─────────
  // 放在最前面——用户 先看到"这次分析基于什么"·再读 Daemonkey 的判断
  const sources = d.sources || {};
  const radarItems = sources.radar_items || [];
  const reportItems = sources.reports || [];
  const docItems = sources.docs || [];
  const hasSources = radarItems.length > 0 || reportItems.length > 0 || docItems.length > 0;
  if (hasSources) {
    html += `<div class="feas-block feas-sources">
      <h3>📚 信源 · 这次分析基于的原始信息
        <span class="feas-sources-hint">点击直达原文 · 用户 可顺着同一根线对齐认知</span>
      </h3>`;
    if (radarItems.length) {
      html += `<div class="feas-src-section">
        <div class="feas-src-section-label"><i class="ri-radar-fill"></i> 雷达条目 (${radarItems.length})</div>
        <div class="feas-src-list">`;
      for (const r of radarItems) {
        const src = r.source_display || r.source || '?';
        const title = r.title || '?';
        const url = r.url || '#';
        const fetchedAt = r.fetched_at || '';
        const fetchedShort = fetchedAt ? formatTimeShort(fetchedAt) : '';
        html += `
          <div class="feas-src-item feas-src-radar" title="${escHtml(title)}">
            <span class="feas-src-ref">[${escHtml(r.ref_id || '?')}]</span>
            <span class="feas-src-source">${escHtml(src)}</span>
            <a class="feas-src-link" href="${escHtml(url)}" target="_blank" rel="noopener">${escHtml(title.slice(0, 80))}</a>
            ${fetchedShort ? `<span class="feas-src-time">${escHtml(fetchedShort)}</span>` : ''}
            ${r.match_score ? `<span class="feas-src-score" title="关键词命中分数">·${r.match_score}</span>` : ''}
          </div>`;
      }
      html += `</div></div>`;
    }
    if (reportItems.length) {
      html += `<div class="feas-src-section">
        <div class="feas-src-section-label"><i class="ri-file-text-fill"></i> 同主题报告 (${reportItems.length})</div>
        <div class="feas-src-list">`;
      for (const rp of reportItems) {
        const url = rp.download_url || '#';
        html += `
          <div class="feas-src-item feas-src-report">
            <span class="feas-src-ref">[${escHtml(rp.ref_id || '?')}]</span>
            <span class="feas-src-source">DOCX</span>
            <a class="feas-src-link" href="${escHtml(url)}" target="_blank" rel="noopener">${escHtml(rp.name || '?')}</a>
            ${rp.match_score ? `<span class="feas-src-score" title="关键词命中分数">·${rp.match_score}</span>` : ''}
          </div>`;
      }
      html += `</div></div>`;
    }
    if (docItems.length) {
      html += `<div class="feas-src-section">
        <div class="feas-src-section-label"><i class="ri-book-2-fill"></i> 私有知识库 (${docItems.length})</div>
        <div class="feas-src-list">`;
      for (const dc of docItems) {
        html += `
          <div class="feas-src-item feas-src-doc" title="${escHtml(dc.snippet || '')}">
            <span class="feas-src-ref">[${escHtml(dc.ref_id || '?')}]</span>
            <span class="feas-src-source">资料</span>
            <a class="feas-src-link" href="javascript:void(0)" onclick="_kbPreview('${jsStr(dc.doc_id || '')}')">${escHtml((dc.title || '?').slice(0, 80))}</a>
          </div>`;
      }
      html += `</div></div>`;
    }
    html += `</div>`;
  } else if (sources.collected_at !== undefined) {
    // 收集了 sources 但什么都没找到——明确告诉 用户·别藏
    html += `<div class="feas-block feas-sources feas-sources-empty">
      <h3>📚 信源</h3>
      <div class="feas-sources-empty-msg">
        <strong>没找到相关雷达条目 / 报告 / 私有资料</strong> · 这次分析信源不足。<br>
        建议：先让 Daemonkey 跑一份相关报告 · 存点相关资料进知识库 · 或扩大雷达源 · 再重新分析。
      </div>
    </div>`;
  }

  // ───────── 卷三十五补丁3 · 市场实证 · web_search 拉的真实信源 ─────────
  // 跟「信源」(雷达 + 报告) 不同 · 这是分析时**实时去网上拉的**·更新鲜·补盲点
  const evidence = d.evidence || null;
  if (evidence && evidence.ok && (evidence.results || []).length > 0) {
    html += `<div class="feas-block feas-evidence">
      <h3><i class="ri-search-fill"></i> 市场实证 · 分析时 web_search 拉的真实信源
        <span class="feas-sources-hint">分析当时从公网拉的·比雷达条目更新鲜·点链接直达原文</span>
      </h3>
      <div class="feas-evidence-query">查询: <code>${escHtml(evidence.query || '?')}</code></div>
      <div class="feas-src-list">`;
    for (let i = 0; i < evidence.results.length; i++) {
      const r = evidence.results[i];
      const url = r.url || '#';
      const title = r.title || '?';
      const snippet = (r.snippet || '').slice(0, 200);
      html += `
        <div class="feas-src-item feas-src-evidence">
          <span class="feas-src-ref">[${i + 1}]</span>
          <a class="feas-src-link" href="${escHtml(url)}" target="_blank" rel="noopener">${escHtml(title)}</a>
          ${snippet ? `<div class="feas-evidence-snippet">${escHtml(snippet)}</div>` : ''}
        </div>`;
    }
    html += `</div></div>`;
  } else if (evidence && !evidence.ok) {
    html += `<div class="feas-block feas-evidence feas-evidence-fail">
      <h3><i class="ri-search-fill"></i> 市场实证</h3>
      <div class="feas-evidence-fail-msg">
        分析时 web_search 失败 · ${escHtml(evidence.error || '?')}<br>
        <span class="om-hint">这意味着 LLM 没有最新公网实证·verdict 可信度会打折</span>
      </div>
    </div>`;
  }

  // 风险评估
  if (d.risks && d.risks.length) {
    html += `<div class="feas-block"><h3>⚠ 风险评估</h3><div class="feas-risks">`;
    for (const r of d.risks) {
      const icon = { low: '<i class="ri-circle-fill" style="color:#22c55e"></i>', medium: '<i class="ri-circle-fill" style="color:#eab308"></i>', high: '<i class="ri-circle-fill" style="color:#ef4444"></i>' }[r.level] || '<i class="ri-circle-line"></i>';
      html += `
        <div class="feas-risk feas-risk-${r.level || 'unknown'}">
          <div class="feas-risk-head">
            ${icon} <b>${escHtml(r.type || '?')}</b>
            <span class="feas-risk-level">${escHtml(r.level || '?')}</span>
          </div>
          <div class="feas-risk-detail">${escHtml(r.detail || '')}</div>
        </div>`;
    }
    html += `</div></div>`;
  }

  // ───────── 卷三十一 · SWOT 四象限 ─────────
  const swot = d.swot || {};
  const hasSwot = ['strengths', 'weaknesses', 'opportunities', 'threats']
    .some(k => Array.isArray(swot[k]) && swot[k].length);
  if (hasSwot) {
    html += `<div class="feas-block"><h3><i class="ri-focus-3-fill"></i> SWOT 战略四象限</h3><div class="feas-swot-grid">`;
    const swotCells = [
      { k: 'strengths',     label: '💪 优势 · S', cls: 'sw-s', tip: '自身相对这件事真正有的牌' },
      { k: 'weaknesses',    label: '⚠ 劣势 · W', cls: 'sw-w', tip: '自身真的缺的 · 不绕弯' },
      { k: 'opportunities', label: '🌱 机会 · O', cls: 'sw-o', tip: '外部环境的机会窗口' },
      { k: 'threats',       label: '🌪 威胁 · T', cls: 'sw-t', tip: '会被谁卡脖子 / 时间窗收缩' },
    ];
    for (const cell of swotCells) {
      const items = swot[cell.k] || [];
      html += `<div class="feas-swot-cell ${cell.cls}">
        <div class="feas-swot-head">${cell.label}</div>
        <div class="feas-swot-tip">${cell.tip}</div>
        <ul class="feas-swot-list">`;
      if (items.length === 0) {
        html += `<li class="feas-swot-empty">—</li>`;
      } else {
        for (const x of items) html += `<li>${escHtml(x)}</li>`;
      }
      html += `</ul></div>`;
    }
    html += `</div></div>`;
  }

  // ───────── 卷三十一 · 未来预期时间轴 ─────────
  const outlook = d.future_outlook || {};
  if (outlook.three_months || outlook.six_months || outlook.one_year) {
    html += `<div class="feas-block"><h3>🔭 未来预期 · 按 用户 现实节奏</h3>
             <div class="feas-outlook">`;
    const slots = [
      { k: 'three_months', label: '3 个月', dot: '●' },
      { k: 'six_months',   label: '6 个月', dot: '●' },
      { k: 'one_year',     label: '12 个月', dot: '●' },
    ];
    for (const s of slots) {
      const txt = (outlook[s.k] || '').trim();
      if (!txt) continue;
      html += `<div class="feas-outlook-row">
        <div class="feas-outlook-when">
          <span class="feas-outlook-dot">${s.dot}</span>
          <span class="feas-outlook-label">${s.label}</span>
        </div>
        <div class="feas-outlook-text">${escHtml(txt)}</div>
      </div>`;
    }
    html += `</div></div>`;
  }

  // ───────── 卷三十一 · 成功路径阶段 ─────────
  const path = d.success_path || {};
  const stages = path.stages || [];
  if (stages.length || path.end_state) {
    html += `<div class="feas-block"><h3>🛤️ 成功路径</h3>
             <div class="feas-path">`;
    stages.forEach((st, i) => {
      const weeks = st.weeks ? `<span class="feas-stage-weeks">${escHtml(String(st.weeks))} 周</span>` : '';
      html += `<div class="feas-stage">
        <div class="feas-stage-num">${i + 1}</div>
        <div class="feas-stage-body">
          <div class="feas-stage-head">
            <span class="feas-stage-name">${escHtml(st.name || '?')}</span>
            ${weeks}
          </div>
          <div class="feas-stage-milestone">
            <b>里程碑</b>: ${escHtml(st.milestone || '')}
          </div>
          <div class="feas-stage-criteria">
            <b>判断</b>: ${escHtml(st.criteria || '')}
          </div>
        </div>
      </div>`;
    });
    if (path.end_state) {
      html += `<div class="feas-end-state">
        <div class="feas-end-state-icon">🏁</div>
        <div class="feas-end-state-body">
          <div class="feas-end-state-label">终态</div>
          <div class="feas-end-state-text">${escHtml(path.end_state)}</div>
        </div>
      </div>`;
    }
    html += `</div></div>`;
  }

  // 资源
  if ((d.resources_have && d.resources_have.length) || (d.resources_need && d.resources_need.length)) {
    html += `<div class="feas-block"><h3><i class="ri-archive-fill"></i> 资源</h3>`;
    if (d.resources_have && d.resources_have.length) {
      html += `<div class="feas-res feas-res-have"><b><i class="ri-checkbox-circle-fill"></i> 用户 已有：</b><ul>`;
      for (const x of d.resources_have) html += `<li>${escHtml(x)}</li>`;
      html += `</ul></div>`;
    }
    if (d.resources_need && d.resources_need.length) {
      html += `<div class="feas-res feas-res-need"><b><i class="ri-search-fill"></i> 还需要找：</b><ul>`;
      for (const x of d.resources_need) html += `<li>${escHtml(x)}</li>`;
      html += `</ul></div>`;
    }
    html += `</div>`;
  }

  // 能力对照
  if (d.capability_match && d.capability_match.length) {
    html += `<div class="feas-block"><h3><i class="ri-brain-fill"></i> 能力对照</h3><div class="feas-caps">`;
    for (const c of d.capability_match) {
      const mark = { yes: '<i class="ri-checkbox-circle-fill"></i>', partial: '<i class="ri-circle-fill" style="color:#eab308"></i>', no: '<i class="ri-close-circle-fill"></i>' }[c.用户_has] || '?';
      html += `
        <div class="feas-cap">
          <div class="feas-cap-head">${mark} <b>${escHtml(c.capability || '?')}</b></div>
          <div class="feas-cap-evi">${escHtml(c.evidence || '')}</div>
        </div>`;
    }
    html += `</div></div>`;
  }

  // 成本拆解
  const cost = d.cost_breakdown || {};
  if (Object.keys(cost).length) {
    html += `<div class="feas-block"><h3>💰 成本拆解</h3><div class="feas-cost">`;
    if (cost.time_hours_min || cost.time_hours_max) {
      html += `<div class="feas-cost-row"><span class="lbl">⏱️ 时间</span>
               <span class="val">${cost.time_hours_min || '?'} - ${cost.time_hours_max || '?'} 小时</span></div>`;
    }
    if (cost.tokens_estimate_usd != null) {
      html += `<div class="feas-cost-row"><span class="lbl">🪙 LLM token</span>
               <span class="val">$${cost.tokens_estimate_usd}</span></div>`;
    }
    if (cost.subscriptions_monthly_usd != null) {
      html += `<div class="feas-cost-row"><span class="lbl"><i class="ri-calendar-fill"></i> 月订阅</span>
               <span class="val">$${cost.subscriptions_monthly_usd}/月</span></div>`;
    }
    if (cost.opportunity_cost) {
      html += `<div class="feas-cost-row"><span class="lbl"><i class="ri-refresh-fill"></i> 机会成本</span>
               <span class="val">${escHtml(cost.opportunity_cost)}</span></div>`;
    }
    html += `</div></div>`;
  }

  // 替代方案
  if (d.alternatives && d.alternatives.length) {
    html += `<div class="feas-block"><h3>🔀 替代方案</h3><div class="feas-alts">`;
    for (const a of d.alternatives) {
      html += `
        <div class="feas-alt">
          <div class="feas-alt-name">${escHtml(a.name || '?')}</div>
          <div class="feas-alt-delta">差异: ${escHtml(a.delta || '')}</div>
          <div class="feas-alt-why">为什么值得考虑: ${escHtml(a.why_consider || '')}</div>
        </div>`;
    }
    html += `</div></div>`;
  }

  // 立刻能做的第一步
  if (d.first_30_min) {
    html += `<div class="feas-block"><h3><i class="ri-rocket-fill"></i> 立刻能做的第一步</h3>
             <div class="feas-first30">${escHtml(d.first_30_min)}</div></div>`;
  }

  // Go/No-Go
  if (d.go_no_go) {
    html += `<div class="feas-block"><h3><i class="ri-focus-3-fill"></i> Go / No-Go</h3>
             <div class="feas-gonogo">${escHtml(d.go_no_go)}</div></div>`;
  }

  // ───────── 卷三十一 · 闭环反馈区 ─────────
  // 用户 在这里直接更新决策 / 实际产出 / 经验·下次 LLM 跑会读到这些
  const outcome = d.outcome || {};
  const curStatus = outcome.status || 'not_started';
  const _STATUS_BTN = [
    { v: 'in_progress', label: '<i class="ri-play-fill"></i> 开干', cls: 'fb-go' },
    { v: 'completed',   label: '<i class="ri-check-fill"></i> 已完成', cls: 'fb-done' },
    { v: 'abandoned',   label: '<i class="ri-close-fill"></i> 不做了', cls: 'fb-skip' },
    { v: 'not_started', label: '⟲ 重置', cls: 'fb-reset' },
  ];
  html += `<div class="feas-block feas-feedback">
    <h3><i class="ri-refresh-fill"></i> 闭环反馈 · 用户 的真实决策（卷三十一）</h3>
    <div class="feas-fb-intro">
      你在这里更新的所有信息·都会被下次 Daemonkey 跑掘金 / 可行性时读到——
      让 Daemonkey 越用越懂你 · 不再推已经拒过的机会。
    </div>

    <div class="feas-fb-status-row">
      <span class="feas-fb-label">当前状态:</span>
      <span class="feas-fb-status-pill feas-fb-${curStatus}" id="fbStatusPill">
        ${{ not_started: '<i class="ri-add-circle-fill"></i> 未启动',
            in_progress: '<i class="ri-play-fill"></i> 进行中',
            completed:   '<i class="ri-check-fill"></i> 已完成',
            abandoned:   '<i class="ri-close-fill"></i> 已放弃' }[curStatus] || curStatus}
      </span>
    </div>

    <div class="feas-fb-buttons">
      ${_STATUS_BTN.map(b => `
        <button class="feas-fb-btn ${b.cls} ${curStatus === b.v ? 'active' : ''}"
                data-status="${b.v}"
                onclick="submitOutcomeStatus('${jsStr(d.opp_id)}', '${b.v}')">
          ${b.label}
        </button>
      `).join('')}
    </div>

    <div class="feas-fb-grid">
      <label class="feas-fb-field feas-fb-field-full">
        <span class="lbl">为什么做 / 为什么不做（最关键）</span>
        <textarea id="fbReason" rows="2"
                  placeholder="比如「这事其实有 3 个大厂在做了 · 我切不进去」">${escHtml(outcome.decision_reason || '')}</textarea>
      </label>
      <label class="feas-fb-field">
        <span class="lbl">实际收入 ¥</span>
        <input id="fbRevenue" type="number" step="any"
               value="${outcome.actual_revenue_cny != null ? outcome.actual_revenue_cny : ''}"
               placeholder="0">
      </label>
      <label class="feas-fb-field">
        <span class="lbl">实际成本 ¥</span>
        <input id="fbCost" type="number" step="any"
               value="${outcome.actual_cost_cny != null ? outcome.actual_cost_cny : ''}"
               placeholder="0">
      </label>
      <label class="feas-fb-field feas-fb-field-full">
        <span class="lbl">增效部分（自动化省了多少时间等）</span>
        <input id="fbEff" type="text"
               value="${escHtml(outcome.efficiency_gain || '')}"
               placeholder="每周省 4 小时 / 写文档速度 3 倍">
      </label>
      <label class="feas-fb-field feas-fb-field-full">
        <span class="lbl">经验教训</span>
        <textarea id="fbLessons" rows="2"
                  placeholder="复盘 · 哪一步是真问题">${escHtml(outcome.lessons_learned || '')}</textarea>
      </label>
    </div>

    <div class="feas-fb-save-row">
      <button class="feas-fb-save-btn"
              onclick="submitOutcomeFull('${jsStr(d.opp_id)}')">
        <i class="ri-save-fill"></i> 保存反馈
      </button>
      <div class="feas-fb-save-hint" id="fbSaveHint"></div>
    </div>

    ${outcome.updates && outcome.updates.length ? `
      <details class="feas-fb-history">
        <summary>变更历史 · ${outcome.updates.length} 次</summary>
        <ul>${outcome.updates.slice(-10).reverse().map(u => `
          <li>
            <span class="hist-at">${(u.at || '').slice(0, 16).replace('T', ' ')}</span>
            <span class="hist-status feas-fb-${u.status}">${u.status}</span>
            ${u.note ? `· ${escHtml(u.note)}` : ''}
          </li>`).join('')}</ul>
      </details>` : ''
    }
  </div>`;

  html += `</div>`;
  $dashView.innerHTML = html;

  // 卷三十三 · <i class="ri-star-fill"></i> 按钮交互
  $dashView.querySelectorAll('.feas-star-btn').forEach(btn => {
    btn.onclick = async (ev) => {
      ev.stopPropagation();
      const refId = btn.getAttribute('data-ref');
      const titleHint = btn.getAttribute('data-title') || '';
      const domain = btn.getAttribute('data-domain') || '';
      const r = await _toggleFavorite('feasibility', refId, titleHint, domain, 'toggle');
      if (r && r.now_starred !== undefined) {
        if (r.now_starred) {
          btn.classList.add('starred');
          btn.title = '已收藏 · 点击取消';
          btn.textContent = '★ 已收藏';
        } else {
          btn.classList.remove('starred');
          btn.title = '收藏此可行性';
          btn.textContent = '☆ 收藏';
        }
      }
    };
  });
}

// 卷三十三 · 跳可行性详情 · 给 renderExecutionDetail / renderFavorites 用
async function _loadFeasibilityDetail(oppId) {
  if (!oppId) return;
  currentView = 'feasibility';
  $dashView.innerHTML = `<div class="dash-empty">加载详情中...</div>`;
  try {
    const r = await fetch(`/dashboard/feasibility?domain_filter=${encodeURIComponent(oppId)}`, {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) {
      $dashView.innerHTML = `<div class="dash-empty">加载失败 [${r.status}]</div>`;
      return;
    }
    const data = await r.json();
    await renderFeasibilityDetail(data);
  } catch (e) {
    $dashView.innerHTML = `<div class="dash-empty">网络出错: ${e.message}</div>`;
  }
}

// ───────── 卷三十一 · outcome 提交 ─────────
async function submitOutcomeStatus(opp_id, status) {
  if (!token) return;
  if (!opp_id) return;
  // 只动 status 一个字段·快速切换用
  await _postOutcome(opp_id, { status });
  // 重新加载详情·刷新 UI 状态
  loadFeasibilityDetail(opp_id);
}

async function submitOutcomeFull(opp_id) {
  if (!token) return;
  if (!opp_id) return;
  const hint = document.getElementById('fbSaveHint');
  const body = {
    decision_reason: document.getElementById('fbReason')?.value || '',
    efficiency_gain: document.getElementById('fbEff')?.value || '',
    lessons_learned: document.getElementById('fbLessons')?.value || '',
  };
  const rev = document.getElementById('fbRevenue')?.value;
  const cost = document.getElementById('fbCost')?.value;
  if (rev !== '' && rev != null) body.actual_revenue_cny = Number(rev);
  if (cost !== '' && cost != null) body.actual_cost_cny = Number(cost);

  if (hint) { hint.textContent = '保存中…'; hint.className = 'feas-fb-save-hint'; }
  const ok = await _postOutcome(opp_id, body);
  if (hint) {
    hint.textContent = ok ? '<i class="ri-check-fill"></i> 已保存 · 下次 Daemonkey 跑掘金/可行性会读到' : '<i class="ri-close-fill"></i> 保存失败';
    hint.className = 'feas-fb-save-hint ' + (ok ? 'ok' : 'err');
    setTimeout(() => { hint.textContent = ''; hint.className = 'feas-fb-save-hint'; }, 3500);
  }
  if (ok) loadFeasibilityDetail(opp_id);
}

async function _postOutcome(opp_id, fields) {
  try {
    const r = await fetch('/outcome', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ opp_id, ...fields }),
    });
    if (!r.ok) {
      console.warn('outcome post failed', r.status, await r.text());
      return false;
    }
    return true;
  } catch (e) {
    console.warn('outcome post error', e);
    return false;
  }
}

// ═════════════════════════════════════════════════════════
// 卷三十三 · <i class="ri-refresh-fill"></i> 执行反馈 · 闭环反馈独立维度
//   跟 outcomes 共享数据 · 视图按状态分组
// ═════════════════════════════════════════════════════════
function renderExecution(data) {
  if (data && data.error) {
    $dashView.innerHTML = `
      <div class="dash-head"><h2><i class="ri-refresh-fill"></i> 执行反馈</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }

  // 单项详情？— 如果 data.opp_id 存在·说明是 single
  if (data && data.opp_id && data.status !== undefined && !data.grouped) {
    renderExecutionDetail(data);
    return;
  }

  const total = data.total || 0;
  const grouped = data.grouped || {};
  const statusMeta = data.status_meta || {};
  const updatedAt = data.updated_at;

  // 状态卡片顺序：进行中优先 → 未启动 → 已完成 → 已放弃
  const order = ['in_progress', 'not_started', 'completed', 'abandoned'];

  const breadcrumbHtml = `
    <div class="exec-breadcrumb">
      <span><i class="ri-bar-chart-fill"></i> 可行性分析</span>
      <span class="arrow">→</span>
      <span><i class="ri-refresh-fill"></i> 执行反馈</span>
      <span class="arrow">→</span>
      <span class="muted">下一轮 LLM 分析</span>
    </div>
  `;

  if (total === 0) {
    $dashView.innerHTML = `
      <div class="dash-head"><h2><i class="ri-refresh-fill"></i> 执行反馈</h2>
        <span class="dash-meta">闭环还没起步</span></div>
      ${breadcrumbHtml}
      <div class="dash-empty">
        <p>还没有项目在执行</p>
        <p class="muted" style="margin-top:8px">
          流程：<i class="ri-diamond-fill"></i> 掘金机会 → <i class="ri-bar-chart-fill"></i> 可行性分析 → <i class="ri-checkbox-circle-fill"></i>「开干」/「不做了」<br>
          决定一旦做出·这里就会出现项目卡 · 后续每一次进展都记录在这。
        </p>
      </div>`;
    return;
  }

  let buckets = '';
  for (const st of order) {
    const items = grouped[st] || [];
    if (items.length === 0) continue;
    const meta = statusMeta[st] || {};
    const icon = meta.icon || '·';
    const label = meta.label || st;
    const color = meta.color || '#7c869c';
    const cards = items.map(it => `
      <div class="exec-card" data-opp="${escHtml(it.opp_id)}"
           style="border-left-color:${color}">
        <div class="exec-card-top">
          <span class="exec-status" style="color:${color}">${icon} ${escHtml(label)}</span>
          <span class="exec-domain">${escHtml(it.opp_domain || '-')}</span>
        </div>
        <div class="exec-title">${escHtml(it.opp_title || '?')}</div>
        ${it.decision_reason ? `
          <div class="exec-reason">${escHtml(it.decision_reason.slice(0, 120))}${it.decision_reason.length > 120 ? '…' : ''}</div>
        ` : ''}
        ${it.status === 'completed' && (it.actual_revenue_cny != null || it.actual_cost_cny != null) ? `
          <div class="exec-numbers">
            <span class="exec-rev">收入 ¥${it.actual_revenue_cny || 0}</span>
            <span class="exec-cost">成本 ¥${it.actual_cost_cny || 0}</span>
          </div>
        ` : ''}
        <div class="exec-foot">
          <span class="exec-time">${escHtml(_formatTimeAgo(it.updated_at))}</span>
          <button class="exec-open" data-opp="${escHtml(it.opp_id)}">查看详情 →</button>
        </div>
      </div>
    `).join('');

    buckets += `
      <section class="exec-bucket" data-status="${st}">
        <h3 style="color:${color}">${icon} ${escHtml(label)} <span class="exec-count">${items.length}</span></h3>
        <div class="exec-grid">${cards}</div>
      </section>
    `;
  }

  $dashView.innerHTML = `
    <div class="dash-head">
      <h2><i class="ri-refresh-fill"></i> 执行反馈</h2>
      <span class="dash-meta">${total} 个项目 · ${escHtml(_formatTimeAgo(updatedAt))}</span>
    </div>
    ${breadcrumbHtml}
    <div class="exec-summary">
      <span class="muted">这里记录每个落地项目的状态 / 决策 / 实际收支 / 经验教训</span><br>
      <span class="muted">→ 下次 LLM 做可行性分析·会自动抓"同类"反馈做合并分析（卷三十三闭环深化）</span>
    </div>
    ${buckets}
  `;

  // 绑定"查看详情"
  $dashView.querySelectorAll('.exec-open').forEach(btn => {
    btn.onclick = (ev) => {
      ev.stopPropagation();
      const oppId = btn.getAttribute('data-opp');
      _loadExecutionDetail(oppId);
    };
  });
  // 整卡也可点
  $dashView.querySelectorAll('.exec-card').forEach(card => {
    card.onclick = () => {
      const oppId = card.getAttribute('data-opp');
      _loadExecutionDetail(oppId);
    };
  });
}

async function _loadExecutionDetail(oppId) {
  if (!oppId) return;
  $dashView.innerHTML = `<div class="dash-empty">加载详情中...</div>`;
  try {
    const r = await fetch(`/dashboard/execution?domain_filter=${encodeURIComponent(oppId)}`, {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) {
      $dashView.innerHTML = `<div class="dash-empty">加载失败 [${r.status}]</div>`;
      return;
    }
    const data = await r.json();
    renderExecutionDetail(data);
  } catch (e) {
    $dashView.innerHTML = `<div class="dash-empty">网络出错: ${e.message}</div>`;
  }
}

function renderExecutionDetail(d) {
  const snap = d.opp_snapshot || {};
  const updates = d.updates || [];
  const status = d.status || 'not_started';
  const statusLabels = {
    not_started: { label: '未启动', icon: '<i class="ri-add-circle-fill"></i>', color: '#7c869c' },
    in_progress: { label: '进行中', icon: '<i class="ri-play-fill"></i>', color: '#7aa2ff' },
    completed: { label: '已完成', icon: '<i class="ri-check-fill"></i>', color: '#5bd1a2' },
    abandoned: { label: '已放弃', icon: '<i class="ri-close-fill"></i>', color: '#d97a7a' },
  };
  const sm = statusLabels[status] || statusLabels.not_started;

  $dashView.innerHTML = `
    <div class="dash-head">
      <button class="back-btn" id="execBack">← 返回执行反馈列表</button>
      <h2><i class="ri-refresh-fill"></i> ${escHtml(d.opp_title || '?')}</h2>
      <span class="dash-meta" style="color:${sm.color}">${sm.icon} ${sm.label}</span>
    </div>

    ${snap.id ? `
      <section class="exec-snap">
        <h3><i class="ri-diamond-fill"></i> 源头掘金机会</h3>
        <div class="exec-snap-box" style="border-left:3px solid #6b8aef">
          <div><strong>${escHtml(snap.title)}</strong></div>
          <div class="muted">domain: ${escHtml(snap.domain || '-')} · fit: ${escHtml(snap.fit || '?')} · recommend: ${snap.recommend || '?'}/5</div>
          ${snap.summary ? `<div style="margin-top:4px">${escHtml(snap.summary.slice(0,200))}${snap.summary.length>200?'…':''}</div>` : ''}
          <div style="margin-top:6px">
            <button class="exec-jump" data-opp="${escHtml(snap.id)}">→ 跳到可行性分析</button>
          </div>
        </div>
      </section>
    ` : ''}

    <section class="exec-current">
      <h3>当前状态</h3>
      ${d.decision_reason ? `
        <div class="exec-field">
          <div class="exec-field-label">决策理由</div>
          <div class="exec-field-val">${escHtml(d.decision_reason)}</div>
        </div>
      ` : ''}
      ${(d.actual_revenue_cny != null || d.actual_cost_cny != null) ? `
        <div class="exec-field-row">
          <div class="exec-field">
            <div class="exec-field-label">实际收入</div>
            <div class="exec-field-val rev">¥${d.actual_revenue_cny || 0}</div>
          </div>
          <div class="exec-field">
            <div class="exec-field-label">实际成本</div>
            <div class="exec-field-val cost">¥${d.actual_cost_cny || 0}</div>
          </div>
        </div>
      ` : ''}
      ${d.efficiency_gain ? `
        <div class="exec-field">
          <div class="exec-field-label">增效</div>
          <div class="exec-field-val">${escHtml(d.efficiency_gain)}</div>
        </div>
      ` : ''}
      ${d.lessons_learned ? `
        <div class="exec-field">
          <div class="exec-field-label">经验教训</div>
          <div class="exec-field-val">${escHtml(d.lessons_learned)}</div>
        </div>
      ` : ''}
    </section>

    <section class="exec-timeline">
      <h3><i class="ri-calendar-fill"></i> 时间线 (${updates.length} 次更新)</h3>
      ${updates.length === 0 ? `
        <div class="muted">还没有更新记录</div>
      ` : `
        <div class="exec-tl">
          ${updates.slice().reverse().map(u => `
            <div class="exec-tl-item">
              <div class="exec-tl-dot" style="background:${(statusLabels[u.status] || sm).color}"></div>
              <div class="exec-tl-body">
                <div class="exec-tl-head">
                  <strong>${(statusLabels[u.status] || sm).icon} ${(statusLabels[u.status] || sm).label}</strong>
                  <span class="muted">${escHtml(_formatTimeAgo(u.at))}</span>
                </div>
                ${u.note ? `<div class="exec-tl-note">${escHtml(u.note)}</div>` : ''}
              </div>
            </div>
          `).join('')}
        </div>
      `}
    </section>

    <section class="exec-update-form">
      <h3>✍️ 添加进展 / 更新状态</h3>
      <p class="muted">这里记的每一笔·都会成为下次 LLM 做同类可行性分析的"过往经验"</p>
      <div class="exec-update-row">
        <select id="execStatusSelect" class="exec-input">
          <option value="">— 不改状态 —</option>
          <option value="not_started" ${status==='not_started'?'selected':''}><i class="ri-add-circle-fill"></i> 未启动</option>
          <option value="in_progress" ${status==='in_progress'?'selected':''}><i class="ri-play-fill"></i> 进行中</option>
          <option value="completed" ${status==='completed'?'selected':''}><i class="ri-check-fill"></i> 已完成</option>
          <option value="abandoned" ${status==='abandoned'?'selected':''}><i class="ri-close-fill"></i> 已放弃</option>
        </select>
      </div>
      <textarea id="execNoteInput" class="exec-input"
                placeholder="进展 / 反思 / 新发现的问题（不限格式）"
                rows="3"></textarea>
      <div class="exec-update-row">
        <input id="execRevInput" type="number" class="exec-input" placeholder="实际收入 ¥（可选）"
               value="${d.actual_revenue_cny != null ? d.actual_revenue_cny : ''}" />
        <input id="execCostInput" type="number" class="exec-input" placeholder="实际成本 ¥（可选）"
               value="${d.actual_cost_cny != null ? d.actual_cost_cny : ''}" />
      </div>
      <input id="execEffInput" type="text" class="exec-input"
             placeholder="增效描述（如「每周省 4 小时」·可选）"
             value="${escHtml(d.efficiency_gain || '')}" />
      <input id="execLessonInput" type="text" class="exec-input"
             placeholder="经验教训（一句话最值钱·可选）"
             value="${escHtml(d.lessons_learned || '')}" />
      <button id="execSaveBtn" class="exec-save-btn"><i class="ri-save-fill"></i> 保存进展</button>
    </section>
  `;

  document.getElementById('execBack').onclick = () => loadDashboard('execution');
  $dashView.querySelectorAll('.exec-jump').forEach(btn => {
    btn.onclick = (ev) => {
      ev.stopPropagation();
      const oppId = btn.getAttribute('data-opp');
      _loadFeasibilityDetail(oppId);
    };
  });
  document.getElementById('execSaveBtn').onclick = async () => {
    const btn = document.getElementById('execSaveBtn');
    btn.disabled = true;
    btn.textContent = '保存中...';
    const fields = {};
    const st = document.getElementById('execStatusSelect').value;
    if (st) fields.status = st;
    const note = (document.getElementById('execNoteInput').value || '').trim();
    if (note) fields.note = note;
    const rev = document.getElementById('execRevInput').value;
    if (rev !== '') fields.actual_revenue_cny = parseFloat(rev);
    const cost = document.getElementById('execCostInput').value;
    if (cost !== '') fields.actual_cost_cny = parseFloat(cost);
    const eff = document.getElementById('execEffInput').value;
    if (eff !== '') fields.efficiency_gain = eff;
    const ls = document.getElementById('execLessonInput').value;
    if (ls !== '') fields.lessons_learned = ls;
    if (note && !fields.decision_reason && !st) {
      // 没改状态 / 没填决策 · 把 note 当 decision_reason 一起塞·让 prompt 那边能用
      fields.decision_reason = note;
    }
    const ok = await _postOutcome(d.opp_id, fields);
    btn.disabled = false;
    btn.innerHTML = '<i class="ri-save-fill"></i> 保存进展';
    if (ok) {
      _loadExecutionDetail(d.opp_id);
    } else {
      await DaemonkeyAlert({ title: '保存失败', message: '执行反馈没存上 · 看浏览器控制台', icon: '<i class="ri-error-warning-fill"></i>' });
    }
  };
}

// ═════════════════════════════════════════════════════════
// 卷三十三 · <i class="ri-star-fill"></i> 收藏夹 · 三类统一视图
// ═════════════════════════════════════════════════════════
function renderFavorites(data) {
  if (data && data.error) {
    $dashView.innerHTML = `
      <div class="dash-head"><h2><i class="ri-star-fill"></i> 收藏夹</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }
  const items = data.items || [];
  const byKind = data.by_kind || {};
  const total = data.total || 0;

  if (total === 0) {
    $dashView.innerHTML = `
      <div class="dash-head"><h2><i class="ri-star-fill"></i> 收藏夹</h2>
        <span class="dash-meta">空</span></div>
      <div class="dash-empty">
        <p>还没收藏过任何东西</p>
        <p class="muted" style="margin-top:8px">
          在 <i class="ri-radar-fill"></i> 信息雷达 / <i class="ri-diamond-fill"></i> 掘金机会 / <i class="ri-bar-chart-fill"></i> 可行性分析 各处都能点 <i class="ri-star-fill"></i> 收藏 · 一处汇总在这。
        </p>
      </div>`;
    return;
  }

  const kindMeta = {
    opportunity: { icon: '<i class="ri-diamond-fill"></i>', label: '掘金机会', color: '#ffd166' },
    feasibility: { icon: '<i class="ri-bar-chart-fill"></i>', label: '可行性分析', color: '#a78bfa' },
  };

  const cards = items.map(it => {
    const km = kindMeta[it.kind] || { icon: '·', label: it.kind, color: '#6b7280' };
    return `
      <div class="fav-card" data-kind="${escHtml(it.kind)}" data-ref="${escHtml(it.ref_id)}"
           style="border-left-color:${km.color}">
        <div class="fav-card-top">
          <span class="fav-kind" style="color:${km.color}">${km.icon} ${km.label}</span>
          ${it.domain ? `<span class="fav-domain">${escHtml(it.domain)}</span>` : ''}
        </div>
        <div class="fav-title">${escHtml(it.title_snap || '?')}</div>
        ${it.note ? `<div class="fav-note">${escHtml(it.note)}</div>` : ''}
        <div class="fav-foot">
          <span class="muted">${escHtml(_formatTimeAgo(it.starred_at))}</span>
          <div class="fav-actions">
            <button class="fav-open" data-kind="${escHtml(it.kind)}" data-ref="${escHtml(it.ref_id)}">查看 →</button>
            <button class="fav-remove" data-kind="${escHtml(it.kind)}" data-ref="${escHtml(it.ref_id)}">取消收藏</button>
          </div>
        </div>
      </div>
    `;
  }).join('');

  $dashView.innerHTML = `
    <div class="dash-head">
      <h2><i class="ri-star-fill"></i> 收藏夹</h2>
      <span class="dash-meta">${total} 条 · <i class="ri-diamond-fill"></i> ${byKind.opportunity||0} · <i class="ri-bar-chart-fill"></i> ${byKind.feasibility||0}</span>
    </div>
    <p class="muted" style="margin-bottom:12px">
      雷达条目的 <i class="ri-star-fill"></i> 在「信息雷达」里查（走 radar feedback）· 这里管掘金机会 + 可行性分析。
    </p>
    <div class="fav-grid">${cards}</div>
  `;

  $dashView.querySelectorAll('.fav-open').forEach(btn => {
    btn.onclick = (ev) => {
      ev.stopPropagation();
      const kind = btn.getAttribute('data-kind');
      const ref = btn.getAttribute('data-ref');
      if (kind === 'opportunity') {
        loadDashboard('opportunities');
      } else if (kind === 'feasibility') {
        _loadFeasibilityDetail(ref);
      }
    };
  });
  $dashView.querySelectorAll('.fav-remove').forEach(btn => {
    btn.onclick = async (ev) => {
      ev.stopPropagation();
      const kind = btn.getAttribute('data-kind');
      const ref = btn.getAttribute('data-ref');
      const ok = await DaemonkeyConfirm({
        title: '取消收藏',
        message: '不再收藏这一条吗？',
        okText: '取消收藏',
        cancelText: '保留',
      });
      if (!ok) return;
      await _toggleFavorite(kind, ref, '', '', 'remove');
      loadDashboard('favorites');
    };
  });
}

// 全局 · 切换收藏 / 加 / 减
async function _toggleFavorite(kind, refId, titleHint, domain, action = 'toggle') {
  if (!kind || !refId) return null;
  try {
    const r = await fetch('/favorites', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        kind, ref_id: refId,
        title_hint: titleHint || '',
        domain: domain || '',
        action,
      }),
    });
    if (!r.ok) {
      console.warn('favorites post failed', r.status, await r.text());
      return null;
    }
    return await r.json();
  } catch (e) {
    console.warn('favorites post error', e);
    return null;
  }
}

// 全局 · 把当前 opportunities / feasibility 的 ref_id 在 UI 上标记 starred
async function _fetchFavoriteSet(kind) {
  try {
    const r = await fetch(`/dashboard/favorites?domain_filter=${encodeURIComponent(kind)}`, {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) return new Set();
    const data = await r.json();
    return new Set((data.items || []).map(it => it.ref_id));
  } catch (e) {
    return new Set();
  }
}

// ═════════════════════════════════════════════════════════
// 卷三十三 · <i class="ri-calendar-fill"></i> 信息日历视图
// ═════════════════════════════════════════════════════════
let _currentCalendarYM = null;  // {year, month}

function renderCalendar(data) {
  if (data && data.error) {
    $dashView.innerHTML = `
      <div class="dash-head"><h2><i class="ri-calendar-fill"></i> 信息日历</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }
  const year = data.year;
  const month = data.month;
  _currentCalendarYM = { year, month };
  const days = data.days || [];
  const totals = data.totals || {};
  const peakDay = data.peak_day;
  const peakCount = data.peak_count || 0;

  // 最大单日 total · 用来缩放 dot 大小
  let maxTotal = 0;
  for (const d of days) {
    if (!d.out_of_month && d.total > maxTotal) maxTotal = d.total;
  }

  // 表头：星期一-日
  const weekdayLabels = ['一', '二', '三', '四', '五', '六', '日'];
  const todayIso = new Date().toISOString().slice(0, 10);

  // 计算上/下月
  const prevMonth = month === 1 ? 12 : month - 1;
  const prevYear = month === 1 ? year - 1 : year;
  const nextMonth = month === 12 ? 1 : month + 1;
  const nextYear = month === 12 ? year + 1 : year;

  const gridCells = days.map(d => {
    if (d.out_of_month) {
      return `
        <div class="cal-cell cal-cell-out">
          <div class="cal-day">${d.date.slice(8, 10)}</div>
        </div>`;
    }
    const dayNum = d.date.slice(8, 10);
    const isToday = d.date === todayIso;
    const isPeak = d.date === peakDay;
    const intensity = maxTotal > 0 ? (d.total / maxTotal) : 0;
    const heatStyle = d.total > 0
      ? `background: rgba(159, 122, 234, ${0.05 + intensity * 0.18});`
      : '';
    const dots = [];
    if (d.radar > 0)    dots.push(`<span class="cal-dot cal-dot-radar"    title="雷达 ${d.radar}">${d.radar}</span>`);
    if (d.trends > 0)   dots.push(`<span class="cal-dot cal-dot-trends"   title="趋势 ${d.trends}">${d.trends}</span>`);
    if (d.reports > 0)  dots.push(`<span class="cal-dot cal-dot-reports"  title="报告 ${d.reports}">${d.reports}</span>`);
    if (d.outcomes > 0) dots.push(`<span class="cal-dot cal-dot-outcomes" title="执行 ${d.outcomes}">${d.outcomes}</span>`);
    // 卷五十八续 X · 对话(sessions)拆成单独淡色小标记·不混进"信息"圆点行 (用户 拍板·别让 251 淹没真信息)
    const sessionMark = d.sessions > 0
      ? `<span class="cal-session-mark" title="当天跟 Daemonkey 对话 ${d.sessions} 条 · 不计入信息总数">💬${d.sessions}</span>`
      : '';
    // 卷五十八续 VII · 仪式到期日旗标 (月度复盘等)
    const ritualFlag = d.ritual
      ? `<span class="cal-ritual-flag" title="${escHtml(d.ritual_label || '周期仪式')}"><i class="ri-flag-2-fill"></i></span>`
      : '';
    return `
      <div class="cal-cell ${isToday ? 'cal-today' : ''} ${isPeak ? 'cal-peak' : ''} ${d.ritual ? 'cal-has-ritual' : ''}"
           style="${heatStyle}"
           data-date="${escHtml(d.date)}"
           title="${escHtml(d.date)} · 📡${d.radar||0} 🌊${d.trends||0} 📄${d.reports||0} ⚙${d.outcomes||0} 💬${d.sessions||0}${d.ritual_label ? ' · ⏰' + escHtml(d.ritual_label) : ''}">
        <div class="cal-day">${dayNum}${ritualFlag}${sessionMark}</div>
        <div class="cal-dots">${dots.join('')}</div>
      </div>`;
  }).join('');

  // 卷五十八续 VII · 节律条 (周期仪式到期 + 一键起草 · 走 NLP 让 Daemonkey 调工具)
  const rituals = data.rituals || [];
  let ritualStrip = '';
  if (rituals.length) {
    const cards = rituals.map(r => {
      if (r.id === 'monthly_review') {
        const dl = r.days_left;
        const when = dl === 0 ? '<b>就是今天</b>'
          : (dl > 0 ? `还有 ${dl} 天` : `已过期 ${-dl} 天`);
        const status = r.drafted_for_next
          ? '<span class="cal-ritual-done">本期已起草</span>'
          : '<span class="cal-ritual-todo">本期未起草</span>';
        const lastTxt = r.last_done ? `上次 ${escHtml(r.last_done)} (${escHtml(r.last_status || '')})` : '从未做过';
        return `
          <div class="cal-ritual-card">
            <div class="cal-ritual-main"><i class="ri-calendar-check-fill"></i> 月度复盘 · 下次 <b>${escHtml(r.next_due)}</b> · ${when}</div>
            <div class="cal-ritual-sub">${status} · ${lastTxt}</div>
            <button class="cal-ritual-btn" data-prompt="${escHtml(r.draft_prompt || '')}" data-label="月度复盘起草">一键起草</button>
          </div>`;
      }
      if (r.id === 'capability_mirror') {
        const en = r.enabled ? `每 ${r.interval_days} 天自动` : '未启用自动 (.env 开关)';
        const lastTxt = r.last_done ? `上次 ${escHtml(r.last_done)}` : '从未照过';
        return `
          <div class="cal-ritual-card">
            <div class="cal-ritual-main"><i class="ri-aspect-ratio-fill"></i> 能力镜像 · ${en}</div>
            <div class="cal-ritual-sub">${lastTxt} · 吃对话摘要后照得见对话</div>
            <button class="cal-ritual-btn" data-prompt="${escHtml(r.draft_prompt || '')}" data-label="市场能力镜像">立即照镜</button>
          </div>`;
      }
      if (r.id === 'skill_discovery') {
        const when = (typeof r.days_left === 'number')
          ? (r.days_left > 0 ? `下次 ${r.days_left} 天后`
             : (r.days_left === 0 ? '今天该挖' : `已 ${-r.days_left} 天没挖`))
          : '';
        const status = r.done_this_week
          ? '<span class="cal-ritual-done">本周已挖</span>'
          : '<span class="cal-ritual-todo">本周未挖</span>';
        const lastTxt = r.last_done ? `上次 ${escHtml(r.last_done)}` : '尚无记录';
        return `
          <div class="cal-ritual-card">
            <div class="cal-ritual-main"><i class="ri-search-eye-line"></i> 能力发现 · 每周一 · ${when}</div>
            <div class="cal-ritual-sub">${status} · ${lastTxt}</div>
            <button class="cal-ritual-btn" data-prompt="${escHtml(r.draft_prompt || '')}" data-label="能力发现">挖一轮</button>
          </div>`;
      }
      return '';
    }).join('');
    ritualStrip = `
      <div class="cal-rituals">
        <div class="cal-rituals-title"><i class="ri-time-fill"></i> 节律 · 周期仪式 (点按钮让 Daemonkey 起草)</div>
        <div class="cal-rituals-row">${cards}</div>
      </div>`;
  }

  const headerCells = weekdayLabels.map(w =>
    `<div class="cal-head-cell">${w}</div>`
  ).join('');

  $dashView.innerHTML = `
    <div class="dash-head">
      <h2><i class="ri-calendar-fill"></i> 信息日历</h2>
      <span class="dash-meta">${year} 年 ${month} 月</span>
    </div>

    <div class="cal-toolbar">
      <button class="cal-nav" data-y="${prevYear}" data-m="${prevMonth}">← ${prevYear}-${String(prevMonth).padStart(2,'0')}</button>
      <span class="cal-current">${year}-${String(month).padStart(2,'0')}</span>
      <button class="cal-nav" data-y="${nextYear}" data-m="${nextMonth}">${nextYear}-${String(nextMonth).padStart(2,'0')} →</button>
      <button class="cal-jump-today" data-today="1">今天</button>
    </div>

    <div class="cal-stats">
      <div class="cal-stat"><span class="cal-stat-icon"><i class="ri-radar-fill"></i></span>雷达 <b>${totals.radar || 0}</b></div>
      <div class="cal-stat"><span class="cal-stat-icon"><i class="ri-line-chart-fill"></i></span>趋势 <b>${totals.trends || 0}</b></div>
      <div class="cal-stat"><span class="cal-stat-icon"><i class="ri-article-fill"></i></span>报告 <b>${totals.reports || 0}</b></div>
      <div class="cal-stat"><span class="cal-stat-icon"><i class="ri-refresh-fill"></i></span>执行 <b>${totals.outcomes || 0}</b></div>
      <div class="cal-stat"><span class="cal-stat-icon"><i class="ri-chat-3-fill"></i></span>对话 <b>${totals.sessions || 0}</b></div>
      ${peakDay ? `<div class="cal-stat cal-stat-peak">🌟 峰值日 ${peakDay} (${peakCount})</div>` : ''}
    </div>

    ${ritualStrip}

    <div class="cal-grid">
      ${headerCells}
      ${gridCells}
    </div>

    <div class="cal-note">
      ${escHtml(data.note || '')}
      <br><span class="muted">数据来源：data/radar.json · data/trends.json · data/reports/*.docx · data/outcomes/*.json · sessions/*.jsonl</span>
    </div>
  `;

  $dashView.querySelectorAll('.cal-nav').forEach(btn => {
    btn.onclick = () => {
      const y = parseInt(btn.getAttribute('data-y'));
      const m = parseInt(btn.getAttribute('data-m'));
      _loadCalendar(y, m);
    };
  });
  const todayBtn = $dashView.querySelector('.cal-jump-today');
  if (todayBtn) {
    todayBtn.onclick = () => {
      const now = new Date();
      _loadCalendar(now.getFullYear(), now.getMonth() + 1);
    };
  }
  $dashView.querySelectorAll('.cal-cell[data-date]').forEach(cell => {
    cell.onclick = () => {
      const d = cell.getAttribute('data-date');
      // 卷三十三补丁 · 改成跳"某天仓"视图（不再 injectAndSend 走 LLM）
      _loadCalendarDay(d);
    };
  });
  // 卷五十八续 VII · 节律按钮 · 派发新会话 (spawnTask · 重操作不污染当前对话) → Daemonkey 跑 monthly_review / mirror_capability
  $dashView.querySelectorAll('.cal-ritual-btn').forEach(btn => {
    btn.onclick = (ev) => {
      ev.stopPropagation();
      const p = btn.getAttribute('data-prompt');
      const lbl = btn.getAttribute('data-label') || '后台任务';
      if (p && typeof spawnQuickly === 'function') spawnQuickly(p, lbl);
    };
  });
}

async function _loadCalendarDay(day) {
  if (!token || !day) return;
  $dashView.innerHTML = `<div class="dash-empty">加载 ${escHtml(day)} 当天数据...</div>`;
  try {
    const r = await fetch(`/dashboard/calendar?domain_filter=${encodeURIComponent(day)}`, {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) {
      $dashView.innerHTML = `<div class="dash-empty">加载失败 [${r.status}]</div>`;
      return;
    }
    const data = await r.json();
    renderCalendarDay(data);
  } catch (e) {
    $dashView.innerHTML = `<div class="dash-empty">网络出错: ${e.message}</div>`;
  }
}

function renderCalendarDay(d) {
  const day = d.day || '?';
  const items = d.items || {};
  const radar = items.radar || { count: 0, items: [] };
  const trends = items.trends || { count: 0, items: [] };
  const reports = items.reports || { count: 0, items: [] };
  const outcomes = items.outcomes || { count: 0, items: [] };

  // 解析回月份键
  let backYM = '';
  if (day && day.length >= 7) backYM = day.slice(0, 7);

  let html = `
    <div class="dash-head">
      <button class="back-btn" onclick="loadDashboard('calendar')">← 返回日历</button>
      <h2><i class="ri-calendar-fill"></i> ${escHtml(day)}</h2>
      <span class="dash-meta">共 ${d.total || 0} 件事</span>
    </div>
    <div class="cal-day-summary">
      <span class="cal-stat"><span class="cal-stat-icon"><i class="ri-radar-fill"></i></span>雷达 <b>${radar.count}</b></span>
      <span class="cal-stat"><span class="cal-stat-icon"><i class="ri-line-chart-fill"></i></span>趋势 <b>${trends.count}</b></span>
      <span class="cal-stat"><span class="cal-stat-icon"><i class="ri-article-fill"></i></span>报告 <b>${reports.count}</b></span>
      <span class="cal-stat"><span class="cal-stat-icon"><i class="ri-refresh-fill"></i></span>执行 <b>${outcomes.count}</b></span>
      ${d.sessions_count ? `<span class="cal-stat cal-stat-session" title="当天跟 Daemonkey 对话条数 · 不计入「共 N 件事」"><span class="cal-stat-icon"><i class="ri-chat-3-fill"></i></span>对话 <b>${d.sessions_count}</b></span>` : ''}
    </div>`;

  // 雷达 · 每条带跳原文
  html += `<section class="day-section">
    <h3><i class="ri-radar-fill"></i> 信息雷达 · ${radar.count} 条</h3>`;
  if (radar.count === 0) {
    html += `<div class="muted">这一天没抓到雷达条目</div>`;
  } else {
    html += `<div class="day-radar-list">`;
    for (const it of radar.items) {
      const dom = it.domain || 'ai';
      const dMeta = RADAR_DOMAINS_META[dom] || { icon: '·', color: '#888' };
      html += `
        <div class="day-radar-item" style="border-left-color:${dMeta.color}">
          <div class="dri-head">
            <span class="dri-dom" style="color:${dMeta.color}">${dMeta.icon}</span>
            <a class="dri-title" href="${escHtml(it.url || '#')}" target="_blank" rel="noopener">${escHtml(it.title || '?')}</a>
          </div>
          <div class="dri-meta">
            <span>${escHtml(it.source || '')}</span>
            ${it.published_at ? `<span class="muted">· 发表 ${escHtml(it.published_at)}</span>` : ''}
            ${it.fetched_at ? `<span class="muted">· 抓取 ${escHtml(_formatTimeAgo(it.fetched_at))}</span>` : ''}
          </div>
        </div>`;
    }
    html += `</div>`;
  }
  html += `</section>`;

  // 趋势
  html += `<section class="day-section">
    <h3><i class="ri-line-chart-fill"></i> 今日趋势 · ${trends.count} 条</h3>`;
  if (trends.count === 0) {
    html += `<div class="muted">${escHtml(trends.note || '这一天没有趋势归档（archive 从卷三十三补丁起建·之前的覆盖在 trends.json 没法回看）')}</div>`;
  } else {
    html += `<div class="day-trends-list">`;
    for (const t of trends.items) {
      html += `
        <div class="day-trend-card">
          <div class="day-trend-title">${escHtml(t.title || '?')}</div>
          ${t.summary ? `<div class="day-trend-sum">${escHtml(t.summary)}</div>` : ''}
          ${t.intensity ? `<div class="muted">强度 ${escHtml(String(t.intensity))}/5</div>` : ''}
        </div>`;
    }
    html += `</div>`;
  }
  html += `</section>`;

  // 报告
  html += `<section class="day-section">
    <h3><i class="ri-article-fill"></i> 报告库 · ${reports.count} 份</h3>`;
  if (reports.count === 0) {
    html += `<div class="muted">这一天没生成报告</div>`;
  } else {
    html += `<div class="day-reports-list">`;
    for (const it of reports.items) {
      html += `
        <div class="day-report-item">
          <a class="day-report-name" href="javascript:void(0)" data-name="${escHtml(it.name)}">📖 ${escHtml(it.name)}</a>
          <span class="muted">${escHtml(it.created_at || '')} · ${it.size_kb || 0} KB</span>
        </div>`;
    }
    html += `</div>`;
  }
  html += `</section>`;

  // 执行 outcomes
  html += `<section class="day-section">
    <h3><i class="ri-refresh-fill"></i> 执行反馈 · ${outcomes.count} 项更新</h3>`;
  if (outcomes.count === 0) {
    html += `<div class="muted">这一天没在执行反馈里留笔</div>`;
  } else {
    html += `<div class="day-outc-list">`;
    for (const o of outcomes.items) {
      html += `
        <div class="day-outc-item">
          <div class="day-outc-title">${escHtml(o.opp_title || '?')}</div>
          <div class="muted">状态：${escHtml(o.status || '?')} · ${escHtml(o.opp_domain || '')}</div>
          ${o.decision_reason ? `<div class="day-outc-reason">${escHtml(o.decision_reason)}</div>` : ''}
        </div>`;
    }
    html += `</div>`;
  }
  html += `</section>`;

  $dashView.innerHTML = html;

  // 报告点击预览
  $dashView.querySelectorAll('.day-report-name[data-name]').forEach(a => {
    a.onclick = () => loadReportPreview(a.getAttribute('data-name'));
  });
}

async function _loadCalendar(year, month) {
  if (!token) return;
  $dashView.innerHTML = `<div class="dash-empty">加载日历...</div>`;
  try {
    const ymStr = `${year}-${String(month).padStart(2, '0')}`;
    const r = await fetch(`/dashboard/calendar?domain_filter=${ymStr}`, {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) {
      $dashView.innerHTML = `<div class="dash-empty">加载失败 [${r.status}]</div>`;
      return;
    }
    const data = await r.json();
    renderCalendar(data);
  } catch (e) {
    $dashView.innerHTML = `<div class="dash-empty">网络出错: ${e.message}</div>`;
  }
}

// 简易时间格式化（"3 小时前" / "刚刚"）· 容错
function _formatTimeAgo(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return '刚刚';
    if (diff < 3600) return Math.floor(diff/60) + ' 分钟前';
    if (diff < 86400) return Math.floor(diff/3600) + ' 小时前';
    if (diff < 86400*30) return Math.floor(diff/86400) + ' 天前';
    return d.toLocaleDateString();
  } catch (e) { return iso; }
}

// ─────────────────────────────────────────────────────────
// 卷二十九 · <i class="ri-puzzle-fill"></i> 插件库（能力扩展层）
// ─────────────────────────────────────────────────────────
function renderPlugins(data) {
  if (data && data.error) {
    $dashView.innerHTML = `
      <div class="dash-head"><h2><i class="ri-puzzle-fill"></i> 插件库</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }
  const items = data.items || [];
  const byCat = data.by_category || {};
  const future = data.future_slots || [];
  const tierSum = data.tier_summary || {};
  const catMeta = data.category_meta || {};

  // 按 category order 排序
  const orderedCats = Object.entries(byCat).sort((a, b) => {
    const oa = (catMeta[a[0]] || {}).order || 99;
    const ob = (catMeta[b[0]] || {}).order || 99;
    return oa - ob;
  });

  let html = `
    <div class="dash-head">
      <h2><i class="ri-puzzle-fill"></i> 插件库</h2>
      <span class="meta">${items.length} 个插件 · AUTO ${tierSum.auto || 0} · CONFIRM ${tierSum.confirm || 0} · GUARD ${tierSum.guard || 0}</span>
      <button onclick="backToChat()">✕ 收起</button>
      <button onclick="loadDashboard('plugins')">刷新</button>
    </div>
    <div class="plugin-intro">
      Daemonkey 当前装载的所有工具 · 按层次分组。<br>
      未来通过 <b><i class="ri-radar-fill"></i> 信息雷达 → <i class="ri-terminal-box-fill"></i> 产品开发</b> · Daemonkey 可以自己写新工具回填到这里。
    </div>`;

  // 各 category 一组
  for (const [catId, catItems] of orderedCats) {
    const meta = catMeta[catId] || { label: catId, icon: '·' };
    html += `
      <div class="plugin-cat">
        <div class="plugin-cat-head">
          <span class="cat-icon">${meta.icon}</span>
          <span class="cat-label">${escHtml(meta.label)}</span>
          <span class="cat-count">${catItems.length}</span>
        </div>
        <div class="plugin-list">`;
    for (const p of catItems) {
      const tierColor = p.tier === 'guard' ? '#ef4444' :
                       p.tier === 'confirm' ? '#eab308' : '#22c55e';
      const tierLabel = p.tier === 'guard' ? 'GUARD' :
                       p.tier === 'confirm' ? 'CONFIRM' : 'AUTO';
      const paramsBadge = (p.params && p.params.length) ?
        `${p.params.length} 个参数` : '无参数';
      // 卷三十三补丁 · added_at + description_zh
      const added = p.added_at ? `<i class="ri-calendar-fill"></i> ${p.added_at}` : '';
      const descZh = p.description_zh ? p.description_zh : null;
      const descEn = p.description || '';
      html += `
        <details class="plugin-card">
          <summary class="plugin-summary">
            <span class="plugin-name">${escHtml(p.name)}</span>
            <span class="plugin-tier" style="background:${tierColor}22;color:${tierColor}">
              ${tierLabel}${p.has_dynamic_classify ? '*' : ''}
            </span>
            <span class="plugin-params">${paramsBadge}</span>
            ${added ? `<span class="plugin-added">${escHtml(added)}</span>` : ''}
          </summary>
          <div class="plugin-detail">
            ${descZh
              ? `<div class="plugin-desc plugin-desc-zh">${escHtml(descZh)}</div>
                 <details class="plugin-desc-en-wrap">
                   <summary class="plugin-desc-en-toggle">查看英文原文</summary>
                   <div class="plugin-desc plugin-desc-en">${escHtml(descEn)}</div>
                 </details>`
              : `<div class="plugin-desc">${escHtml(descEn)}</div>`
            }`;
      if (p.params && p.params.length) {
        html += `<div class="plugin-params-list"><b>参数</b><ul>`;
        for (const pa of p.params) {
          const req = pa.required ? ' <span class="req">必填</span>' : '';
          const enumStr = pa.enum ? ` · enum: ${pa.enum.join(' / ')}` : '';
          html += `
            <li><code>${escHtml(pa.name)}</code> :
              <span class="type">${escHtml(pa.type)}</span>${req}${escHtml(enumStr)}
              ${pa.description ? `<div class="param-desc">${escHtml(pa.description)}</div>` : ''}
            </li>`;
        }
        html += `</ul></div>`;
      }
      html += `
            <div class="plugin-tryit">
              <button class="plugin-try-btn"
                onclick="injectAndSend('用 ${escHtml(p.name)} 帮我做一件事 · 你看上下文判断要传什么参数')">
                <i class="ri-lightbulb-fill"></i> 让 Daemonkey 用这个工具做点事
              </button>
            </div>
          </div>
        </details>`;
    }
    html += `</div></div>`;
  }

  // 未来扩展
  if (future.length) {
    html += `
      <div class="plugin-cat plugin-cat-future">
        <div class="plugin-cat-head">
          <span class="cat-icon">✨</span>
          <span class="cat-label">未来扩展</span>
          <span class="cat-count">${future.length}</span>
        </div>
        <div class="plugin-list">`;
    for (const f of future) {
      html += `
        <div class="plugin-card plugin-card-future">
          <div class="plugin-summary">
            <span class="plugin-name plugin-name-future">${escHtml(f.name)}</span>
          </div>
          <div class="plugin-detail">
            <div class="plugin-desc">${escHtml(f.description)}</div>
          </div>
        </div>`;
    }
    html += `</div></div>`;
  }

  $dashView.innerHTML = html;
}

function escHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// wish-b199c9fa · inline onclick JS 字符串参数专用转义 (双层·顺序不能反):
//   1) JS 层: \ → \\ · ' → \' · 换行 → \n 字面量 (防 JS 字符串被提前闭合)
//   2) HTML 层: & < > " → 实体 (防属性本身被截断)
// 为什么不能只用 escHtml: escHtml 把 ' 转 &#39; 但浏览器解析属性时解码回 ' → onclick="fn('${jsStr(x)}')" 仍会断。
function jsStr(v) {
  var s = String(v == null ? '' : v);
  s = s.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\r?\n/g, '\\n');
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function formatRadarTime(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso.length > 30 ? iso.slice(0, 30) : iso;
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit',
                                        hour: '2-digit', minute: '2-digit',
                                        hour12: false });
  } catch { return ''; }
}

// 卷二十七 · 工作室链路 breadcrumb · 雷达/趋势/报告 互相导航
function pipelineBreadcrumb(current) {
  const stages = [
    { id: 'radar',   icon: '<i class="ri-radar-fill"></i>', label: '雷达',   hint: '原料层 · 多源抓取' },
    { id: 'trends',  icon: '<i class="ri-line-chart-fill"></i>', label: '趋势',   hint: '提炼层 · Daemonkey 军师视图' },
    { id: 'reports', icon: '<i class="ri-article-fill"></i>', label: '报告',   hint: '成品层 · 正式 docx 出货' },
  ];
  const parts = stages.map((s, i) => {
    const active = (s.id === current) ? ' active' : '';
    const arrow = i > 0 ? '<span class="pl-arrow">→</span>' : '';
    return arrow +
      `<button class="pl-stage${active}" onclick="loadDashboard('${s.id}')" ` +
      `title="${escHtml(s.hint)}">${s.icon} ${s.label}</button>`;
  }).join('');
  return `<div class="pipeline" title="Daemonkey 信息流水线 · 点击切换维度">${parts}</div>`;
}

// 卷二十七 · 简易 inline SVG 直方图（信源贡献）
function toggleSourceHistogram(btn) {
  const histogram = btn.closest('.radar-histogram');
  if (!histogram) return;
  const svg = histogram.querySelector('svg');
  const collapsed = histogram.querySelectorAll('.sh-collapsed');
  const isHidden = collapsed.length > 0 && collapsed[0].style.display !== 'block';
  collapsed.forEach(g => { g.style.display = isHidden ? 'block' : 'none'; });
  if (svg && svg.dataset.fullHeight) {
    const fullH = parseInt(svg.dataset.fullHeight);
    const collH = parseInt(svg.dataset.collapsedHeight);
    const newH = isHidden ? fullH : collH;
    svg.setAttribute('height', newH);
    const vb = svg.viewBox.baseVal;
    svg.setAttribute('viewBox', `0 0 ${vb.width} ${newH}`);
  }
  btn.textContent = isHidden ? '收起' : `+ 显示剩余 ${collapsed.length} 个信源`;
}

function renderSourceHistogram(meta, scopeLabel) {
  const scoped = scopeLabel ? ` · ${escHtml(scopeLabel)}` : '';
  // 选了具体领域但该领域没源 → 引导加源 (用户 2026-06-03 · 信源跟领域走·add_source 后端已支持 domain)
  const emptyHint = scopeLabel
    ? `<div class="radar-histogram"><div class="rh-title">信源贡献${scoped}</div><div class="sh-empty">这个领域还没有专属信源 · 跟 Daemonkey 说「给「${escHtml(scopeLabel)}」加个信息源」</div></div>`
    : '';
  if (!meta || meta.length === 0) return emptyHint;
  const okMeta = meta.filter(m => m.ok || m.fetched > 0);
  if (okMeta.length === 0) return emptyHint;
  okMeta.sort((a, b) => (b.fetched || 0) - (a.fetched || 0));
  const maxN = Math.max(...okMeta.map(m => m.fetched || 0), 1);
  const width = 100;
  const barHeight = 18;
  const labelW = 110;
  const valueW = 35;
  const total = okMeta.length;
  const MAX_VISIBLE = 3;
  const hasMore = total > MAX_VISIBLE;
  const collapsedHeight = MAX_VISIBLE * (barHeight + 4);
  const fullHeight = total * (barHeight + 4);
  const svgHeight = hasMore ? collapsedHeight : fullHeight;

  let bars = '';
  okMeta.forEach((m, i) => {
    const y = i * (barHeight + 4);
    const w = Math.max(2, (m.fetched / maxN) * width);
    const fail = !m.ok;
    const color = fail ? 'var(--red)' : 'var(--Daemonkey)';
    const display = (m.display || m.source || '').slice(0, 14);
    const barSvg = `
      <text x="0" y="${y + barHeight - 5}" class="sh-label" fill="var(--dim)">${escHtml(display)}</text>
      <rect x="${labelW}" y="${y}" width="${w}" height="${barHeight}" fill="${color}" opacity="0.7" rx="2"></rect>
      <text x="${labelW + w + 5}" y="${y + barHeight - 5}" class="sh-value" fill="var(--text)">${m.fetched}</text>`;
    if (hasMore && i >= MAX_VISIBLE) {
      bars += `
      <g class="sh-collapsed" style="display:none">${barSvg}
      </g>`;
    } else {
      bars += barSvg;
    }
  });

  let html = `
    <div class="radar-histogram">
      <div class="rh-title">信源贡献${scoped}</div>
      <svg width="100%" height="${svgHeight}" viewBox="0 0 ${labelW + width + valueW} ${svgHeight}"
           preserveAspectRatio="xMinYMid meet" data-full-height="${fullHeight}" data-collapsed-height="${collapsedHeight}">${bars}</svg>`;
  if (hasMore) {
    html += `
      <button class="sh-toggle-btn" onclick="toggleSourceHistogram(this)">+ 显示剩余 ${total - MAX_VISIBLE} 个信源</button>`;
  }
  html += `
    </div>`;
  return html;
}
function renderRadar(data) {
  if (data && data.error) {
    $dashView.innerHTML = `
      <div class="dash-head"><h2><i class="ri-radar-fill"></i> 信息雷达</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }
  if (data && data.note && (data.items || []).length === 0) {
    $dashView.innerHTML = `
      ${pipelineBreadcrumb('radar')}
      <div class="dash-head">
        <h2><i class="ri-radar-fill"></i> 信息雷达</h2>
        <button onclick="backToChat()">✕ 收起</button>
        <button onclick="spawnQuickly('帮我跑一遍信息雷达 · 调 auto_pipeline 工具 · 参数 refresh_radar=true, regen_trends=false, mine_opps=false · 只抓取雷达不动趋势机会 · 跑完告诉我新增了哪些条目·特别是 self-evolve 域的', '抓取信息雷达')">立即抓取</button>
      </div>
      <div class="dash-stub">
        <h3>雷达还没数据</h3>
        <div>${escHtml(data.note)}</div>
      </div>`;
    return;
  }
  const allItems = data.items || [];
  const meta = data.sources_meta || [];
  const trMeta = data.translation || {};
  const overview = data.domains_overview || [];
  const generatedTxt = data.generated_at
    ? formatRadarTime(data.generated_at) : '未知';

  // 卷二十八 · 顶部领域 chip 过滤器
  const allCount = allItems.length;
  const filteredItems = (radarDomainFilter && radarDomainFilter !== 'all')
    ? allItems.filter(it => (it.domain || 'ai') === radarDomainFilter)
    : allItems;

  let domainChips = `
    <div class="radar-domain-chips">
      <button class="rdc ${radarDomainFilter === 'all' ? 'active' : ''}"
              onclick="setRadarDomainFilter('all')"
              title="不过滤 · 所有领域">
        <i class="ri-global-fill"></i> 全部 <span class="rdc-n">${allCount}</span>
      </button>`;
  for (const d of overview) {
    const isActive = radarDomainFilter === d.id;
    // 卷三十四补丁 · self-evolve 是 Daemonkey 自演化的镜子·不能删·不显示删除按钮
    const isProtected = d.id === 'self-evolve';
    const deleteBtn = isProtected ? '' : `
      <span class="rdc-del"
            title="删除「${escHtml(d.label)}」类目"
            onclick="event.stopPropagation();confirmRemoveDomain('${d.id}', ${JSON.stringify(d.label).replace(/"/g, '&quot;')}, ${d.items_count || 0}, ${d.sources_count || 0})">×</span>`;
    domainChips += `
      <button class="rdc ${isActive ? 'active' : ''} ${isProtected ? 'protected' : 'deletable'}"
              data-domain="${d.id}"
              onclick="setRadarDomainFilter('${d.id}')"
              title="${escHtml(d.description || d.label)}${isProtected ? ' · 内置锁定·不可删' : ''}"
              style="${isActive ? `border-color: ${d.color}; color: ${d.color}` : ''}">
        ${d.icon} ${escHtml(d.label)} <span class="rdc-n">${d.items_count || 0}</span>${deleteBtn}
      </button>`;
  }
  domainChips += `</div>`;

  // 顶部数据卡 · 卷五十八续 X · 今日新增(首见·跟着 tab 走) + 共(可见总数·已扣hidden)
  const items = filteredItems;
  const okSources = meta.filter(m => m.ok).length;
  const translatedN = trMeta.translated || items.filter(it => it.title_zh).length;
  const rstats = data.stats || {};
  const isFiltered = (radarDomainFilter && radarDomainFilter !== 'all');
  // 今日新增跟着 tab 走: 选了领域=该领域今天首见·全部=全领域总和 (用户 2026-06-06·别两个口径混一格)
  const newTodayByDom = rstats.new_today_by_domain || {};
  const newToday = isFiltered
    ? Number(newTodayByDom[radarDomainFilter] || 0)
    : Number(rstats.new_today || 0);
  const totalVisible = (rstats.total != null) ? Number(rstats.total) : allCount;
  const todayLabel = isFiltered ? '本类今日新增' : '今日新增';
  const statsCards = `
    <div class="radar-stats">
      <div class="rs-card rs-card-today" title="${isFiltered ? '本领域今天首次出现的新条目' : '全领域今天首次出现的新条目'} · 跟「本类/共」同一领域口径">
        <div class="rs-n">${newToday > 0 ? '+' + newToday : '0'}</div>
        <div class="rs-l">${todayLabel}</div>
      </div>
      <div class="rs-card" title="可见条目总数 (已扣除你隐藏的条目)">
        <div class="rs-n">${isFiltered ? items.length + '/' + totalVisible : totalVisible}</div>
        <div class="rs-l">${isFiltered ? '本类/共' : '条信息'}</div>
      </div>
      <div class="rs-card">
        <div class="rs-n">${okSources}/${meta.length}</div>
        <div class="rs-l">信源在线</div>
      </div>
      <div class="rs-card" title="${translatedN} 条英文条目已翻译成中文">
        <div class="rs-n">${translatedN}</div>
        <div class="rs-l">已翻译</div>
      </div>
      <div class="rs-card">
        <div class="rs-n" title="${escHtml(generatedTxt)}">${formatTimeShort(data.generated_at)}</div>
        <div class="rs-l">最新抓取</div>
      </div>
    </div>`;

  let html = `
    ${pipelineBreadcrumb('radar')}
    <div class="dash-head">
      <h2><i class="ri-radar-fill"></i> 信息雷达</h2>
      <span class="meta">原料层 · 多源抓取 · 多领域</span>
      <button onclick="backToChat()">✕ 收起</button>
      <button onclick="spawnQuickly('帮我跑一遍信息雷达 · 调 auto_pipeline 工具 · 参数 refresh_radar=true, regen_trends=false, mine_opps=false · 只抓取雷达不动趋势机会 · 跑完告诉我新增了哪些条目·特别是 self-evolve 域的', '重新抓取雷达')">重新抓取</button>
      <button onclick="spawnQuickly('看一眼信息雷达最新数据 · 调 auto_pipeline 工具 · 参数 refresh_radar=false, regen_trends=true, mine_opps=false · 只重新生成今日趋势 · 跑完告诉我哪几个趋势最戳到 用户 · 为什么', '生成今日趋势')">让 Daemonkey 总结趋势 →</button>
    </div>
    ${domainChips}
    ${statsCards}
    ${renderSourceHistogram(
      (radarDomainFilter && radarDomainFilter !== 'all') ? meta.filter(m => (m.domain || 'ai') === radarDomainFilter) : meta,
      (radarDomainFilter && radarDomainFilter !== 'all') ? ((overview.find(o => o.id === radarDomainFilter) || {}).label || radarDomainFilter) : ''
    )}`;

  if (items.length === 0) {
    if (radarDomainFilter && radarDomainFilter !== 'all') {
      html += `<div class="dash-empty">该领域目前没数据 · 切回"全部"或加这个领域的信源</div>`;
    } else {
      html += `<div class="dash-empty">还没抓到数据 · 点"重新抓取"试一下</div>`;
    }
  } else {
    // 卷三十二 · feedback/softness 统计·渲染顶部小统计条
    const fbCnt = data.feedback_counts || {};
    const sfCnt = data.softness_counts || {};
    const totalFb = (fbCnt.thumbs_up || 0) + (fbCnt.thumbs_down || 0)
                  + (fbCnt.starred || 0) + (fbCnt.hidden || 0);
    if (totalFb > 0 || (sfCnt.high || 0) > 0) {
      html += `<div class="radar-stats">
        ${totalFb > 0 ? `
          <span class="rs-fb">
            <span class="rs-tag fb-up"><i class="ri-thumb-up-fill"></i> ${fbCnt.thumbs_up || 0}</span>
            <span class="rs-tag fb-down"><i class="ri-thumb-down-fill"></i> ${fbCnt.thumbs_down || 0}</span>
            <span class="rs-tag fb-star"><i class="ri-star-fill"></i> ${fbCnt.starred || 0}</span>
            <span class="rs-tag fb-hide"><i class="ri-delete-bin-fill"></i> ${fbCnt.hidden || 0}</span>
          </span>` : ''}
        ${(sfCnt.high || 0) + (sfCnt.medium || 0) > 0 ? `
          <span class="rs-soft" title="软文判别: 高=大概率营销稿·会被排到末尾">
            软文 · 高 <b>${sfCnt.high || 0}</b> · 中 <b>${sfCnt.medium || 0}</b> · 低 <b>${sfCnt.low || 0}</b>
          </span>` : ''}
      </div>`;
    }

    html += `<div class="radar-list">`;
    for (const it of items) {
      // 中文优先 · 有 title_zh 用中文 · 原文 hover 显示
      const showTitle = it.title_zh || it.title;
      const origTitle = it.title_zh ? it.title : '';
      const showSummary = it.summary_zh || it.summary || '';
      const transBadge = it.title_zh ? '<span class="ri-tr-badge" title="Daemonkey 已翻译 · 鼠标移到标题看原文">中</span>' : '';
      const origAttr = origTitle ? ` title="原文: ${escHtml(origTitle)}"` : '';

      // 卷三十二 · feedback 状态 / softness 徽章 / item_id
      const iid = it.item_id || '';
      const fb = it.feedback || '';
      const softLevel = (it.softness || {}).level || 'low';
      const softBadge = softLevel === 'high'
        ? '<span class="ri-soft soft-high" title="高软文嫌疑 · 已自动压到末尾">软</span>'
        : softLevel === 'medium'
        ? '<span class="ri-soft soft-medium" title="疑似软文">软?</span>'
        : '';
      const fbClass = fb ? `fb-${fb}` : '';
      const fbBtns = `
        <div class="ri-fb-actions" data-iid="${escHtml(iid)}">
          <button class="ri-fb-btn ${fb === 'thumbs_up' ? 'active' : ''}"
                  title="👍 多关注这类"
                  onclick="event.stopPropagation();toggleRadarFeedback('${jsStr(iid)}', 'thumbs_up', ${JSON.stringify(showTitle).replace(/"/g, '&quot;')}, ${JSON.stringify(it.url || '').replace(/"/g, '&quot;')})"><i class="ri-thumb-up-fill"></i></button>
          <button class="ri-fb-btn ${fb === 'thumbs_down' ? 'active' : ''}"
                  title="👎 别再抓这种"
                  onclick="event.stopPropagation();toggleRadarFeedback('${jsStr(iid)}', 'thumbs_down', ${JSON.stringify(showTitle).replace(/"/g, '&quot;')}, ${JSON.stringify(it.url || '').replace(/"/g, '&quot;')})"><i class="ri-thumb-down-fill"></i></button>
          <button class="ri-fb-btn ${fb === 'starred' ? 'active' : ''}"
                  title="⭐ 收藏"
                  onclick="event.stopPropagation();toggleRadarFeedback('${jsStr(iid)}', 'starred', ${JSON.stringify(showTitle).replace(/"/g, '&quot;')}, ${JSON.stringify(it.url || '').replace(/"/g, '&quot;')})"><i class="ri-star-fill"></i></button>
          <button class="ri-fb-btn ${fb === 'hidden' ? 'active' : ''}"
                  title="🗑 隐藏 · 下次刷新不再出现"
                  onclick="event.stopPropagation();toggleRadarFeedback('${jsStr(iid)}', 'hidden', ${JSON.stringify(showTitle).replace(/"/g, '&quot;')}, ${JSON.stringify(it.url || '').replace(/"/g, '&quot;')})"><i class="ri-delete-bin-fill"></i></button>
          <button class="ri-fb-btn ri-deep-btn"
                  title="🔍 深挖 · Daemonkey 用 web_search 拓展这个话题"
                  onclick="event.stopPropagation();deepDiveRadar(${JSON.stringify(showTitle).replace(/"/g, '&quot;')})"><i class="ri-search-fill"></i></button>
          ${(it.domain === 'self-evolve') ? `
          <button class="ri-fb-btn ri-wish-btn"
                  title="🤔 让 Daemonkey 看一眼 · 推给 Daemonkey · 让他自己判断要不要装"
                  onclick="event.stopPropagation();wishFromRadar(${JSON.stringify(showTitle).replace(/"/g, '&quot;')}, ${JSON.stringify(it.url || '').replace(/"/g, '&quot;')})"><i class="ri-emotion-think-line"></i></button>` : ''}
        </div>`;

      html += `
        <div class="radar-item ${fbClass} soft-${softLevel}" data-iid="${escHtml(iid)}">
          <a class="ri-title"${origAttr} href="${escHtml(it.url)}" target="_blank" rel="noopener">${escHtml(showTitle)}${transBadge}${softBadge}</a>
          <div class="ri-meta">
            ${it.value != null ? `<span class="ri-stars" title="价值 ${it.value}/100">${_biStars(it.value)}</span>` : ''}
            <span class="ri-src">${escHtml(it.source_display || it.source)}</span>
            <span class="ri-cat">${escHtml(it.category || '')}</span>
            <span class="ri-cat">${escHtml(formatRadarTime(it.published_at) || it.published_at || '')}</span>
            ${fb ? `<span class="ri-fb-state fb-${fb}">${ {thumbs_up:'<i class="ri-thumb-up-fill"></i>',thumbs_down:'<i class="ri-thumb-down-fill"></i>',starred:'<i class="ri-star-fill"></i>',hidden:'<i class="ri-delete-bin-fill"></i>'}[fb] || '' }</span>` : ''}
          </div>
          ${showSummary ? `<div class="ri-summary">${escHtml(showSummary)}</div>` : ''}
          ${fbBtns}
        </div>`;
    }
    html += `</div>`;
  }
  $dashView.innerHTML = html;
}

// 卷三十二 · 雷达条目打标
async function toggleRadarFeedback(iid, feedback, titleHint, urlHint) {
  if (!token || !iid) return;
  // 找到当前 item 的状态·点同一个 feedback = 取消
  const card = document.querySelector(`.radar-item[data-iid="${iid}"]`);
  const wasActive = card ? card.classList.contains(`fb-${feedback}`) : false;
  const payload = {
    item_id: iid,
    feedback: wasActive ? null : feedback,
    title_hint: titleHint,
    url_hint: urlHint,
  };
  try {
    const r = await fetch('/radar/feedback', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });
    if (!r.ok) {
      console.warn('radar feedback failed', r.status, await r.text());
      return;
    }
  } catch (e) {
    console.warn('radar feedback error', e);
    return;
  }
  // 重新拉雷达 · 让 sort 立刻生效
  loadDashboard('radar', { silent: true });
}

// 卷二十八 · 雷达 domain 过滤器切换
function setRadarDomainFilter(domain) {
  radarDomainFilter = domain;
  if (domain === 'all') localStorage.removeItem('radar_domain_filter');
  else localStorage.setItem('radar_domain_filter', domain);
  loadDashboard('radar', { silent: true });
}

// 卷三十五补丁3 · 手动删类目 · 直接走 API · 不再喂 LLM
// 修两件事:
//   1. BUG · starter 4 删了重启复活 (后端用 domains_removed.json 记账解决)
//   2. token · 删按钮不应该烧 LLM token · 用户点 x 就是确定动作
// 自然语言删除依然可以走 Daemonkey · 这个函数只服务"按钮点击"场景
async function confirmRemoveDomain(slug, label, itemsCount, sourcesCount) {
  if (!slug || slug === 'self-evolve') return;
  const ok = await DaemonkeyConfirm({
    title: '删除雷达领域',
    message: {
      html: `确认删除领域 <b>「${escHtml(label)}」</b> 吗？
        <span class="om-hint">${sourcesCount} 个信源 · ${itemsCount} 条历史条目<br>
        信源会自动 reassign 到 wildcard (或其他可用域)·不会丢失。<br>
        删除会持久化·重启浏览器或 daemon 都不会复活。</span>`
    },
    okText: '直接删',
    cancelText: '取消',
    danger: true,
  });
  if (!ok) return;
  if (radarDomainFilter === slug) {
    setRadarDomainFilter('all');
  }
  try {
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = 'Bearer ' + token;
    const resp = await fetch('/radar/domains/remove', {
      method: 'POST',
      headers,
      body: JSON.stringify({
        slug,
        sources_action: 'reassign',
      }),
    });
    if (!resp.ok) {
      const errText = await resp.text();
      await DaemonkeyAlert({
        title: '删除失败',
        message: `${resp.status} · ${errText}`,
        danger: true,
      });
      return;
    }
    const result = await resp.json();
    const affected = (result && result.affected_sources && result.affected_sources.length) || 0;
    const target = (result && result.target_domain) || '—';
    await DaemonkeyAlert({
      title: '删除成功',
      message: {
        html: `已删除领域 <b>「${escHtml(label)}」</b>。<br>
          <span class="om-hint">影响 ${affected} 个信源·已 reassign 到 <b>${escHtml(target)}</b></span>`
      },
    });
    if (typeof loadDashboard === 'function') loadDashboard();
  } catch (e) {
    await DaemonkeyAlert({
      title: '删除失败',
      message: '网络或服务异常: ' + (e && e.message || e),
      danger: true,
    });
  }
}

function formatTimeShort(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '—';
    const now = new Date();
    const diffMs = now - d;
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 1) return '刚刚';
    if (diffMin < 60) return `${diffMin}分前`;
    const diffH = Math.floor(diffMin / 60);
    if (diffH < 24) return `${diffH}小时前`;
    const diffD = Math.floor(diffH / 24);
    if (diffD < 7) return `${diffD}天前`;
    return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
  } catch {
    return '—';
  }
}

// 卷二十七 · 今日趋势 = Daemonkey 军师视图（不只是「今日」· 是前瞻+操作建议）
// 数据 schema: title / summary / intensity (1-5) / angles[] / refs[] / radar_index
const _ANGLE_LABELS = {
  content: { icon: '<i class="ri-film-fill"></i>', label: '内容制作', action: '写选题', cls: 'angle-content' },
  design:  { icon: '<i class="ri-palette-fill"></i>', label: '产品设计', action: '出 spec', cls: 'angle-design' },
  dev:     { icon: '<i class="ri-terminal-box-fill"></i>', label: '产品开发', action: '列 TODO', cls: 'angle-dev' },
  docs:    { icon: '<i class="ri-file-text-fill"></i>', label: '文档撰写', action: '写 FAQ', cls: 'angle-docs' },
  service: { icon: '<i class="ri-team-fill"></i>', label: '用户服务', action: '设服务', cls: 'angle-service' },
};

function renderIntensityBar(intensity) {
  const n = Math.max(0, Math.min(5, intensity || 0));
  let dots = '';
  for (let i = 0; i < 5; i++) {
    dots += i < n ? '●' : '○';
  }
  const cls = n >= 5 ? 'intensity-5' : n >= 4 ? 'intensity-4'
            : n >= 3 ? 'intensity-3' : 'intensity-low';
  const labels = ['', '弱信号', '观望', '值得跟进', '强信号', '立刻动手'];
  return `<span class="tc-intensity ${cls}" title="${labels[n] || ''}">${dots} <span class="tc-int-n">${n}/5</span></span>`;
}

// 触发一键动作：直接给 chat 输入框塞一条指令然后发送
function triggerTrendAction(trendIndex, kind) {
  // kind = 'report' | 'content' | 'design' | 'dev' | 'docs'
  const triggers = {
    report:  `把第 ${trendIndex + 1} 个趋势展开成一份完整报告 (调 expand_trend_to_report tool · trend_index=${trendIndex})`,
    content: `基于第 ${trendIndex + 1} 个趋势 · 给我写一个对应的视频选题 / 口播稿 (调 draft_studio · domain=content)`,
    design:  `基于第 ${trendIndex + 1} 个趋势 · 出一份产品 spec (调 draft_studio · domain=design)`,
    dev:     `基于第 ${trendIndex + 1} 个趋势 · 列一份技术调研 / TODO (调 draft_studio · domain=dev)`,
    docs:    `基于第 ${trendIndex + 1} 个趋势 · 写一条 FAQ / wiki (调 draft_studio · domain=docs)`,
  };
  const msg = triggers[kind];
  if (!msg) return;
  $input.value = msg;
  $input.focus();
  if (typeof window.send === 'function') window.send();
  else document.getElementById('send')?.click();
}

function renderTrends(data) {
  if (data && data.error) {
    $dashView.innerHTML = `
      ${pipelineBreadcrumb('trends')}
      <div class="dash-head"><h2><i class="ri-line-chart-fill"></i> 今日趋势</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }
  const trends = (data && data.trends) || [];
  const generatedAt = data && data.generated_at;
  const generatedTxt = generatedAt ? formatRadarTime(generatedAt) : '未知';
  // 卷三十四 · 取整天日期（用户 想看的是绝对日期·不是相对时间）
  const generatedDay = generatedAt ? (generatedAt.slice(0, 10)) : '?';
  const itemsScanned = data && data.items_scanned ? data.items_scanned : '?';
  const isArchive = data && data._source === 'archive';
  const archiveDay = data && data._day;

  let html = `
    ${pipelineBreadcrumb('trends')}
    <div class="dash-head">
      <h2><i class="ri-line-chart-fill"></i> 今日趋势 · Daemonkey 军师视图</h2>
      <span class="meta"><i class="ri-calendar-fill"></i> <b>${escHtml(isArchive ? archiveDay : generatedDay)}</b> · ${trends.length} 个方向 · 扫了 ${itemsScanned} 条 · ${generatedTxt}${isArchive ? ' <span class="badge-archive">归档</span>' : ''}</span>
      <button onclick="backToChat()">✕ 收起</button>
      <button onclick="loadDashboard('radar')">← 看原料</button>
      <button onclick="spawnQuickly('看一眼信息雷达最新数据 · 调 auto_pipeline 工具 · 参数 refresh_radar=false, regen_trends=true, mine_opps=false · 只重新生成今日趋势 · 跑完告诉我哪几个趋势最戳到 用户 · 为什么', '重新生成趋势')">让 Daemonkey 重新看一遍</button>
    </div>
    <div class="trends-intro">
      不是「今日新闻总结」· 是 Daemonkey 看完雷达 ${itemsScanned} 条后给出的
      <strong>前瞻性思考 + 工作室视角</strong>——每个趋势都标了强度 + 可切入的角度 +
      可一键转化的动作。${isArchive ? `<br><span class="archive-hint">⏳ 当前查看的是 <b>${escHtml(archiveDay)}</b> 的归档趋势·不是最新版</span>` : ''}
    </div>
    ${trends.length > 3 ? renderListFilter({targetSelector: '.trend-card', placeholder: '搜趋势标题 / 摘要 / 信源...'}) : ''}`;

  if (trends.length === 0) {
    html += `
      <div class="dash-stub">
        <h3>还没生成趋势</h3>
        <div>${escHtml((data && data.note) || '点"让 Daemonkey 重新看一遍"·Daemonkey 会读 radar.json·输出 3-5 个方向·约 30-60s')}</div>
      </div>`;
  } else {
    trends.forEach((t, idx) => {
      const angles = (t.angles || []).filter(a => _ANGLE_LABELS[a]);
      const angleChips = angles.map(a => {
        const m = _ANGLE_LABELS[a];
        return `<span class="trend-angle ${m.cls}" title="${m.label}">${m.icon} ${m.label}</span>`;
      }).join('');

      const refs = (t.refs || []).map(r =>
        `<a href="${escHtml(r.url || '#')}" target="_blank" rel="noopener" ` +
        `title="${escHtml(r.title || '')}">${escHtml(r.source || '?')}</a>`
      ).join(' · ');

      // 操作按钮：永远有"写报告" + "深挖"·angles 各自有触发
      const reportBtn = `<button class="trend-action ta-report" onclick="triggerTrendAction(${idx}, 'report')" title="Daemonkey 用 LLM 把这个趋势展开成 3000-4500 字 docx 报告"><i class="ri-article-fill"></i> 写报告</button>`;
      const deepBtn = `<button class="trend-action ta-deep" onclick="deepDiveTrend(${idx})" title="让 Daemonkey 用 web_search + web_fetch 深挖这个趋势"><i class="ri-search-fill"></i> 深挖</button>`;
      const angleBtns = angles.map(a => {
        const m = _ANGLE_LABELS[a];
        return `<button class="trend-action ${m.cls}" onclick="triggerTrendAction(${idx}, '${a}')" title="基于这个趋势 · 调 draft_studio domain=${a}">${m.icon} ${m.action}</button>`;
      }).join('');

      html += `
        <div class="trend-card" data-trend-idx="${idx}" data-trend-title="${escHtml(t.title || '')}">
          <div class="tc-row1">
            <span class="tc-idx">#${idx + 1}</span>
            <span class="tc-head">${escHtml(t.title || '')}</span>
            ${renderIntensityBar(t.intensity)}
            <span class="tc-day" title="${escHtml(generatedDay)} 这一份趋势"><i class="ri-calendar-fill"></i> ${escHtml(generatedDay)}</span>
          </div>
          <div class="tc-body">${escHtml(t.summary || '')}</div>
          ${angleChips ? `<div class="trend-angles">${angleChips}</div>` : ''}
          <div class="trend-actions">${reportBtn}${deepBtn}${angleBtns}</div>
          ${refs ? `<div class="tc-refs"><i class="ri-radar-fill"></i> 信源: ${refs}</div>` : ''}
        </div>`;
    });
  }
  $dashView.innerHTML = html;
  if (trends.length > 3) _applyListFilter($dashView.querySelector('.list-filter-input'));
}

// 报告库（卷二十四 · generate_report 工具产物 · data/reports/ 落盘）
// 私有文档知识库 · 第二大脑 · 文档清单 + 参考开关 + 删除(灌文档走对话 NLP)
// 复用 report-card / rc-* 样式 · 不另起 CSS
// 单篇知识库文档卡片 HTML · 文件夹分组和平铺共用
function _kbCardHtml(d, typeIcon) {
  const icon = (typeIcon && typeIcon[d.type]) || '<i class="ri-file-fill"></i>';
  const off = d.enabled === false;
  const tagBadges = (d.tags || []).map(t => `<span class="rc-src-badge">#${escHtml(t)}</span>`).join(' ');
  const flagBadges = [];
  if (d.pinned) flagBadges.push('<span class="rc-src-badge kb-flag-badge"><i class="ri-pushpin-2-fill"></i> 常驻</span>');
  if (d.sensitive) flagBadges.push('<span class="rc-src-badge kb-flag-badge kb-flag-sensitive"><i class="ri-shield-keyhole-fill"></i> 敏感</span>');
  const pinCls = d.pinned ? ' on' : '';
  const senCls = d.sensitive ? ' on' : '';
  return `
    <div class="report-card${off ? ' kb-off' : ''}">
      <div class="rc-head">
        <span class="rc-name kb-open" data-id="${escHtml(d.id)}" title="点击查看内容">${icon} ${escHtml(d.title)}</span>
        ${off ? '<span class="rc-src-badge rc-src-extract">已静音</span>' : ''}
        ${flagBadges.join('')}
      </div>
      <div class="rc-meta">
        <span class="rc-size">${d.chunks || 0} 块</span>
        <span class="rc-time">${d.chars || 0} 字 · ${escHtml((d.added_at || '').slice(0, 10))}</span>
        ${tagBadges}
        <button class="rc-preview-btn kb-toggle" data-id="${escHtml(d.id)}" data-enabled="${off ? '0' : '1'}">${off ? '恢复参考' : '停止参考'}</button>
        <button class="kb-flag kb-flag-pin${pinCls}" data-id="${escHtml(d.id)}" data-flag="pinned" data-on="${d.pinned ? '1' : '0'}" title="常驻:命中优先靠前"><i class="ri-pushpin-2-line"></i></button>
        <button class="kb-flag kb-flag-sen${senCls}" data-id="${escHtml(d.id)}" data-flag="sensitive" data-on="${d.sensitive ? '1' : '0'}" title="敏感:不自动注入·仅显式召回可见"><i class="ri-shield-keyhole-line"></i></button>
        <a class="rc-dl kb-del" href="javascript:void(0)" data-id="${escHtml(d.id)}" data-title="${escHtml(d.title)}">删除 ✕</a>
      </div>
    </div>`;
}

function renderKnowledge(data) {
  if (data && data.error) {
    $dashView.innerHTML = `
      <div class="dash-head"><h2><i class="ri-book-2-fill"></i> 知识库</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }
  const items = (data && data.items) || [];
  const st = (data && data.stats) || {};
  const typeIcon = {
    pdf:  '<i class="ri-file-pdf-2-fill"></i>',
    docx: '<i class="ri-file-word-2-fill"></i>',
    pptx: '<i class="ri-file-ppt-2-fill"></i>',
    md:   '<i class="ri-markdown-fill"></i>',
    txt:  '<i class="ri-file-text-fill"></i>',
  };

  let html = `
    <div class="dash-head">
      <h2><i class="ri-book-2-fill"></i> 知识库 · 第二大脑</h2>
      <span class="meta">${items.length} 篇 · ${st.enabled || 0} 参考中 · ${st.disabled || 0} 静音</span>
      <button onclick="backToChat()">✕ 收起</button>
      <button onclick="loadDashboard('knowledge')">刷新列表</button>
    </div>`;

  if (items.length === 0) {
    html += `
      <div class="dash-stub">
        <h3>知识库还是空的</h3>
        <div>在底部输入框跟 Daemonkey 说：「把 <code>D:\\资料\\合同.pdf</code> 加进知识库」<br>
             支持 md / txt / docx / pptx / pdf(文本型)。灌进来后能被召回并 cite 回原文。</div>
      </div>`;
  } else {
    if (items.length > 3) {
      html += renderListFilter({ targetSelector: '.report-card', placeholder: '搜文档标题 / 标签...' });
    }
    // 按文件夹分组显示 · folder 字段优先 · 无则退回第一个标签 · 都没有 → 未分类
    const folderOf = (d) => (d.folder && String(d.folder).trim())
      || ((d.tags && d.tags.length) ? String(d.tags[0]) : '未分类');
    const groups = {};
    for (const d of items) { const f = folderOf(d); (groups[f] = groups[f] || []).push(d); }
    const names = Object.keys(groups).sort((a, b) => {
      if (a === '未分类') return 1;
      if (b === '未分类') return -1;
      return a.localeCompare(b, 'zh');
    });
    html += `<div class="kb-folders">`;
    for (const f of names) {
      const cards = groups[f].map(d => _kbCardHtml(d, typeIcon)).join('');
      html += `
        <div class="kb-folder">
          <div class="kb-folder-head">
            <i class="ri-folder-3-fill kb-folder-ico"></i>
            <span class="kb-folder-name">${escHtml(f)}</span>
            <span class="kb-folder-count">${groups[f].length}</span>
            <i class="ri-arrow-down-s-line kb-folder-caret"></i>
          </div>
          <div class="kb-folder-body">${cards}</div>
        </div>`;
    }
    html += `</div>`;
  }
  $dashView.innerHTML = html;

  $dashView.querySelectorAll('.kb-folder-head').forEach(h => {
    h.onclick = () => h.parentElement.classList.toggle('collapsed');
  });
  $dashView.querySelectorAll('.kb-toggle').forEach(btn => {
    btn.onclick = () => _kbAction('/dashboard/knowledge/toggle', {
      doc_id: btn.getAttribute('data-id'),
      enabled: btn.getAttribute('data-enabled') !== '1',
    });
  });
  $dashView.querySelectorAll('.kb-flag').forEach(btn => {
    btn.onclick = () => {
      const body = { doc_id: btn.getAttribute('data-id') };
      body[btn.getAttribute('data-flag')] = btn.getAttribute('data-on') !== '1';
      _kbAction('/dashboard/knowledge/flag', body);
    };
  });
  $dashView.querySelectorAll('.kb-del').forEach(btn => {
    btn.onclick = () => {
      const t = btn.getAttribute('data-title') || '这篇';
      if (confirm(`删除「${t}」？原文和索引都会清掉(不影响你磁盘上的原始文件)。`)) {
        _kbAction('/dashboard/knowledge/delete', { doc_id: btn.getAttribute('data-id') });
      }
    };
  });
  $dashView.querySelectorAll('.kb-open').forEach(el => {
    el.onclick = () => _kbPreview(el.getAttribute('data-id'));
  });
  if (items.length > 3) _applyListFilter($dashView.querySelector('.list-filter-input'));
}

// 报告库 → 一键存入知识库 (灌 md 源优先·归「报告」文件夹·已灌过不重复)
async function _importReportToKb(name, btn) {
  if (!token || !name) return;
  const old = btn ? btn.innerHTML : '';
  if (btn) { btn.disabled = true; btn.innerHTML = '存入中…'; }
  try {
    const r = await fetch('/dashboard/knowledge/import-report', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { alert('存入失败 [' + r.status + ']' + (data.detail ? ' · ' + data.detail : '')); return; }
    if (btn) {
      btn.innerHTML = data.existed ? '已在库中' : '✓ 已存入';
      setTimeout(() => { btn.disabled = false; btn.innerHTML = old; }, 2200);
    }
    if (typeof showChatToast === 'function') {
      showChatToast(data.existed ? '这份报告已经在知识库里了' : '已存入知识库 · 「报告」文件夹 · 之后能被召回并 cite');
    }
  } catch (e) {
    alert('网络出错: ' + e.message);
    if (btn) { btn.disabled = false; btn.innerHTML = old; }
  }
}

// 点知识库卡片标题 → 拉正文 → 弹窗预览 (markdown 渲染)
async function _kbPreview(docId) {
  if (!token || !docId) return;
  try {
    const r = await fetch('/dashboard/knowledge/doc?doc_id=' + encodeURIComponent(docId), {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) { alert('打开失败 [' + r.status + ']'); return; }
    _showKbModal(await r.json());
  } catch (e) { alert('网络出错: ' + e.message); }
}

// 卷八十一续 · 统一预览弹框渲染器 · 知识库/playbook/文件产物 共用一套骨架
// (用户 拍板: 别各处重写预览逻辑 · 弹框统一 · 以后改一处全生效)
// 2026-08-11 F1 (墨言审查): _showPreviewModal 的 keydown 防堆积 · 模块级单例
let _previewModalKeyBound = false;
function _previewModalKeyHandler(e) {
  if (e.key === 'Escape') {
    const host = document.getElementById('kbModalHost');
    if (host && host.classList.contains('show')) host.classList.remove('show');
  }
}

function _showPreviewModal(opts) {
  const { title, metaLine, bodyHtml, tags, raw } = opts || {};
  _closeAllKbModals();  // 2026-08-14 · 单例互斥 (墨言094-2) · 开新弹框前先关旧的
  let host = document.getElementById('kbModalHost');
  if (!host) {
    host = document.createElement('div');
    host.id = 'kbModalHost';
    host.className = 'kb-modal-host';
    document.body.appendChild(host);
  }
  const tagHtml = (tags || []).map(t => `<span class="rc-src-badge">#${escHtml(t)}</span>`).join(' ');
  host.innerHTML = `
    <div class="kb-modal-mask"></div>
    <div class="kb-modal" role="dialog" aria-modal="true">
      <div class="kb-modal-head">
        <span class="kb-modal-title">${escHtml(title || '文档')}</span>
        ${metaLine ? `<span class="kb-modal-meta">${escHtml(metaLine)}</span>` : ''}
        <button class="kb-modal-close" title="关闭 (Esc)">✕</button>
      </div>
      ${tagHtml ? `<div class="kb-modal-tags">${tagHtml}</div>` : ''}
      <div class="kb-modal-body ${raw ? 'kb-modal-raw' : 'markdown-body'}">${bodyHtml || ''}</div>
    </div>`;
  host.classList.add('show');
  // 2026-08-11 F1 (墨言审查): 每次打开 add keydown · 连续开多个弹框会堆积 listener。
  // 改成"模块级标志"——只注册一次 · close 只清当前 · 多次开叠弹框不重复挂。
  if (!_previewModalKeyBound) {
    document.addEventListener('keydown', _previewModalKeyHandler);
    _previewModalKeyBound = true;
  }
  const close = () => {
    host.classList.remove('show');
  };
  host.querySelector('.kb-modal-close').onclick = close;
  host.querySelector('.kb-modal-mask').onclick = close;
}

// 2026-08-14 · kbModalHost 单例互斥 (墨言 094-2 审查 · wish-2b43ffe7):
// depot.js(_cogDimModal) / clients.js(pickClient + _showClientImportModal) 各自
// getElementById('kbModalHost') → 不存在则建 → innerHTML 覆盖 —— 共用同一 DOM 节点，
// 先后打开会静默互相覆盖 (先开的状态丢失)。
// 修法: 每个弹框打开前先调用 _closeAllKbModals() 关掉当前已开的 → 再开新的。
// 用户心智: "打开新弹框 = 旧的先关掉" · 不再静默覆盖。
function _closeAllKbModals() {
  const host = document.getElementById('kbModalHost');
  if (host) host.classList.remove('show');
}

function _showKbModal(data) {
  const meta = (data && data.meta) || {};
  const text = (data && data.text) || '';
  const bodyHtml = (typeof mdRender === 'function')
    ? mdRender(text) : ('<pre style="white-space:pre-wrap">' + escHtml(text) + '</pre>');
  const metaLine = [meta.type, (meta.chars || 0) + ' 字', (meta.chunks || 0) + ' 块',
    data && data.truncated ? '预览已截断' : ''].filter(Boolean).join(' · ');
  _showPreviewModal({ title: meta.title || '文档', metaLine, bodyHtml, tags: meta.tags || [] });
}

async function _kbAction(url, body) {
  if (!token) return;
  try {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) { alert('操作失败 [' + r.status + ']'); return; }
    loadDashboard('knowledge', { silent: true });
  } catch (e) { alert('网络出错: ' + e.message); }
}

function renderReports(data) {
  if (data && data.error) {
    $dashView.innerHTML = `
      ${pipelineBreadcrumb('reports')}
      <div class="dash-head"><h2><i class="ri-article-fill"></i> 报告库</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }
  const items = (data && data.items) || [];
  const dir = (data && data.directory) || 'data/reports';

  let html = `
    ${pipelineBreadcrumb('reports')}
    <div class="dash-head">
      <h2><i class="ri-article-fill"></i> 报告库</h2>
      <span class="meta">成品层 · ${items.length} 份 · ${escHtml(dir)}</span>
      <button onclick="backToChat()">✕ 收起</button>
      <button onclick="loadDashboard('trends')">← 回到趋势</button>
      <button onclick="loadDashboard('reports')">刷新列表</button>
    </div>`;

  if (items.length === 0) {
    html += `
      <div class="dash-stub">
        <h3>还没生成过报告</h3>
        <div>在底部输入框跟 Daemonkey 说：「整理一下本周雷达写成报告」<br>
             Daemonkey 会调 <code>generate_report</code> · docx 自动落在这里。</div>
      </div>`;
  } else {
    if (items.length > 3) {
      html += renderListFilter({targetSelector: '.report-card', placeholder: '搜报告文件名 / 时间...'});
    }
    html += `<div class="reports-list">`;
    for (const it of items) {
      const dlUrl = `${it.download_url}?token=${encodeURIComponent(token || '')}`;
      const previewable = !!it.preview_url;
      const srcBadge = it.has_md_source
        ? `<span class="rc-src-badge rc-src-md" title="新报告 · 有 markdown 源">md 源</span>`
        : `<span class="rc-src-badge rc-src-extract" title="旧报告 · 预览是从 docx 反推的">兜底抽取</span>`;
      html += `
        <div class="report-card">
          <div class="rc-head">
            <a class="rc-name" href="javascript:void(0)" data-name="${escHtml(it.name)}" data-preview="1">
              ${escHtml(it.name)}
            </a>
            ${srcBadge}
          </div>
          <div class="rc-meta">
            <span class="rc-size">${it.size_kb} KB</span>
            <span class="rc-time">${escHtml(it.created_at)}</span>
            ${previewable ? `<button class="rc-preview-btn" data-name="${escHtml(it.name)}">📖 预览</button>` : ''}
            <button class="rc-preview-btn rp-kb" data-name="${escHtml(it.name)}" title="把这份报告灌进知识库 · 之后能被召回并 cite"><i class="ri-book-2-line"></i> 存入知识库</button>
            <a class="rc-dl" href="${escHtml(dlUrl)}" download="${escHtml(it.name)}">下载 ↓</a>
          </div>
        </div>`;
    }
    html += `</div>`;
  }
  $dashView.innerHTML = html;

  // 卷三十三补丁 · 预览按钮绑定
  $dashView.querySelectorAll('.rc-preview-btn:not(.rp-kb), .rc-name[data-preview]').forEach(el => {
    el.onclick = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const name = el.getAttribute('data-name');
      if (name) loadReportPreview(name);
    };
  });
  $dashView.querySelectorAll('.rp-kb').forEach(btn => {
    btn.onclick = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      _importReportToKb(btn.getAttribute('data-name'), btn);
    };
  });

  if (items.length > 3) _applyListFilter($dashView.querySelector('.list-filter-input'));
}

// 卷三十三补丁 · 加载并渲染单份报告的预览
async function loadReportPreview(filename) {
  if (!token || !filename) return;
  $dashView.innerHTML = `<div class="dash-empty">加载预览中...</div>`;
  try {
    const r = await fetch(`/reports/preview/${encodeURIComponent(filename)}`, {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) {
      const errTxt = await r.text();
      $dashView.innerHTML = `<div class="dash-empty">预览失败 [${r.status}]<br>${escHtml(errTxt.slice(0,300))}</div>`;
      return;
    }
    const data = await r.json();
    renderReportPreview(data);
  } catch (e) {
    $dashView.innerHTML = `<div class="dash-empty">网络出错: ${e.message}</div>`;
  }
}

function renderReportPreview(d) {
  const name = d.name || '?';
  const meta = d.meta || {};
  const md = d.markdown || '';
  const hasMd = !!d.has_md_source;
  const note = d.note || '';
  const dlUrl = `/reports/${encodeURIComponent(name)}?token=${encodeURIComponent(token || '')}`;

  // 标题 / 副标题 / 受众 / 备注 / footer 渲染封面
  const coverBlock = (meta.title || meta.subtitle || meta.audience || meta.note) ? `
    <div class="rp-cover">
      ${meta.title ? `<div class="rp-cover-title">${escHtml(meta.title)}</div>` : ''}
      ${meta.subtitle ? `<div class="rp-cover-sub">${escHtml(meta.subtitle)}</div>` : ''}
      <div class="rp-cover-meta">
        ${meta.audience ? `<span>面向：${escHtml(meta.audience)}</span>` : ''}
        ${meta.generated_at ? `<span>生成于 ${escHtml(meta.generated_at)}</span>` : ''}
        ${meta.theme ? `<span>主题 · ${escHtml(meta.theme)}</span>` : ''}
      </div>
      ${meta.note ? `<div class="rp-cover-note">${escHtml(meta.note)}</div>` : ''}
    </div>
  ` : '';

  $dashView.innerHTML = `
    <div class="dash-head">
      <h2>📖 ${escHtml(name)}</h2>
      <button onclick="loadDashboard('reports')">← 返回报告库</button>
      <a class="rp-dl-btn" href="${escHtml(dlUrl)}" download="${escHtml(name)}">下载 docx ↓</a>
    </div>
    <div class="rp-meta-strip">
      ${hasMd
        ? '<span class="rp-src rp-src-md"><i class="ri-file-text-fill"></i> markdown 源</span>'
        : '<span class="rp-src rp-src-extract"><i class="ri-error-warning-fill"></i> 旧报告 · 从 docx 反推的简陋版</span>'}
      ${note ? `<span class="rp-note">${escHtml(note)}</span>` : ''}
    </div>
    <article class="rp-body">
      ${coverBlock}
      <div class="rp-md">${mdRender(md)}</div>
    </article>
  `;
}

// 卷二十八 · <i class="ri-diamond-fill"></i> 掘金机会维度
async function renderOpportunities(data) {
  if (data && data.error) {
    $dashView.innerHTML = `
      <div class="dash-head"><h2><i class="ri-diamond-fill"></i> 掘金机会</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }
  const opps = (data && data.opportunities) || [];
  const generated = data && data.generated_at;
  const note = data && data.note;
  const trendsScanned = data && data.trends_scanned;
  const elapsedS = data && data.elapsed_ms ? (data.elapsed_ms / 1000).toFixed(1) : '?';

  // 卷三十三 · 抓收藏集合·标 <i class="ri-star-fill"></i>
  const favSet = await _fetchFavoriteSet('opportunity');

  let html = `
    <div class="dash-head">
      <h2><i class="ri-diamond-fill"></i> 掘金机会</h2>
      <span class="meta">${opps.length} 个机会 · 市场 × 用户 能力</span>
      <button onclick="backToChat()">✕ 收起</button>
      <button onclick="spawnQuickly('基于今日趋势 · 调 mine_opportunities 工具 · 参数 action=mine · 重新挖一遍掘金机会 · 形态要多样(内容账号 / 实体产品 / 服务咨询 / 信息差套利 / 软件产品 / 投资副业 · 不要全是 SaaS · 卷三十三第 6 条铁律) · 跑完告诉我最推哪 1-2 个 + 为什么', '重新挖掘机会')" title="派发到新会话 · Daemonkey 跑 mine_opportunities · 完成后切过去看结果">
        <i class="ri-refresh-fill"></i> 重新挖掘
      </button>
    </div>`;

  if (opps.length === 0) {
    html += `
      <div class="dash-stub">
        <h3>还没挖过掘金机会</h3>
        <div>${escHtml(note || '点上方"重新挖掘"按钮 · Daemonkey 会基于最新趋势 + 用户 画像 LLM 跑一次')}</div>
        <div style="margin-top:12px;font-size:11px;color:var(--dim2)">
          需要先有趋势 · 没趋势的话先去 <i class="ri-line-chart-fill"></i> 今日趋势 跑一次
        </div>
      </div>`;
  } else {
    html += `
      <div class="opp-intro">
        生成于 ${formatTimeShort(generated)} · 扫描了 ${trendsScanned || 0} 条趋势 · 耗时 ${elapsedS}s<br>
        <span style="font-size:11px;color:var(--dim2)">
          每个机会都基于 用户 画像评估了适配度 · 点机会卡可让 Daemonkey 展开成完整方案
        </span>
      </div>
      ${opps.length > 3 ? renderListFilter({targetSelector: '.opp-card', placeholder: '搜机会标题 / 领域 / 适配理由...'}) : ''}
      <div class="opp-list">`;
    for (let i = 0; i < opps.length; i++) {
      const o = opps[i];
      o._is_favorited = o.id && favSet.has(o.id);
      html += renderOppFullCard(o, i);
    }
    html += `</div>`;
  }
  $dashView.innerHTML = html;

  // 绑定 <i class="ri-star-fill"></i> 按钮
  $dashView.querySelectorAll('.opp-star-btn').forEach(btn => {
    btn.onclick = async (ev) => {
      ev.stopPropagation();
      const refId = btn.getAttribute('data-ref');
      const titleHint = btn.getAttribute('data-title') || '';
      const domain = btn.getAttribute('data-domain') || '';
      const r = await _toggleFavorite('opportunity', refId, titleHint, domain, 'toggle');
      if (r && r.now_starred !== undefined) {
        if (r.now_starred) {
          btn.classList.add('starred');
          btn.title = '已收藏 · 点击取消';
          btn.textContent = '★';
        } else {
          btn.classList.remove('starred');
          btn.title = '收藏';
          btn.textContent = '☆';
        }
      }
    };
  });

  if (opps.length > 3) _applyListFilter($dashView.querySelector('.list-filter-input'));
}

function renderOppFullCard(o, idx) {
  const fitIcon = { yes: '<i class="ri-checkbox-circle-fill"></i>', maybe: '<i class="ri-error-warning-fill"></i>', no: '<i class="ri-close-circle-fill"></i>' }[o.fit] || '?';
  const fitLabel = { yes: '能干', maybe: '可干但需准备', no: '不建议' }[o.fit] || o.fit;
  const effortLabel = { light: '轻量·半天-3天', moderate: '中等·1-2周', heavy: '重投入·1月+' }[o.cost_effort] || o.cost_effort;
  const upsideLabel = { low: '小·自己玩', medium: '中·兴趣副业', high: '高·撑一条线' }[o.upside] || o.upside;
  const stars = '<i class="ri-star-fill"></i>'.repeat(Math.max(1, Math.min(5, o.recommend || 3)));
  const dMeta = RADAR_DOMAINS_META[o.domain] || { icon: '·', label: o.domain, color: '#888' };

  let stepsHtml = '';
  if (o.next_steps && o.next_steps.length) {
    stepsHtml = `
      <div class="opp-steps">
        <div class="opp-section-label">下一步:</div>
        <ol>${o.next_steps.map(s => `<li>${escHtml(s)}</li>`).join('')}</ol>
      </div>`;
  }
  let refsHtml = '';
  if (o.trend_refs && o.trend_refs.length) {
    refsHtml = `
      <div class="opp-refs">
        <div class="opp-section-label">关联趋势:</div>
        ${o.trend_refs.map(r => `<span class="opp-ref">${escHtml(r.title || '?')}</span>`).join(' ')}
      </div>`;
  }

  const starred = o._is_favorited;
  return `
    <div class="opp-card" data-opp-idx="${idx + 1}" data-opp-title="${escHtml(o.title || '')}" style="border-left-color: ${dMeta.color}">
      <div class="opp-head">
        <span class="opp-domain-chip" style="background: ${dMeta.color}33; color: ${dMeta.color}">
          ${dMeta.icon} ${escHtml(dMeta.label)}
        </span>
        <span class="opp-title">${escHtml(o.title || '?')}</span>
        <span class="opp-rec" title="Daemonkey 推荐度 ${o.recommend}/5">${stars}</span>
        <button class="opp-star-btn ${starred ? 'starred' : ''}"
                data-ref="${escHtml(o.id || '')}"
                data-title="${escHtml(o.title || '')}"
                data-domain="${escHtml(o.domain || '')}"
                title="${starred ? '已收藏 · 点击取消' : '收藏'}">
          ${starred ? '★' : '☆'}
        </button>
      </div>
      <div class="opp-metas">
        <span class="opp-meta-pill" title="用户 适配度">${fitIcon} ${fitLabel}</span>
        <span class="opp-meta-pill" title="投入预估">⏱️ ${effortLabel}</span>
        <span class="opp-meta-pill" title="收益级别">📈 ${upsideLabel}</span>
      </div>
      <div class="opp-summary">${escHtml(o.summary || '')}</div>
      ${o.fit_reason ? `<div class="opp-fit-reason"><b>为什么 用户 ${o.fit === 'no' ? '不' : ''}适合:</b> ${escHtml(o.fit_reason)}</div>` : ''}
      ${renderOppStats(o)}
      ${stepsHtml}
      ${refsHtml}
      <div class="opp-actions">
        <button class="opp-act-btn" onclick="spawnQuickly('把第 ${idx + 1} 个机会展开成完整方案', '展开机会方案')">
          <i class="ri-draft-fill"></i> 展开成方案
        </button>
        <button class="opp-act-btn opp-act-feas"
                onclick="runFeasibilityFromOpp('${jsStr(o.id || '')}', ${idx + 1})"
                title="跳到 📊 可行性分析维度 · Daemonkey 跑一次深度评估">
          <i class="ri-bar-chart-fill"></i> 跑可行性
        </button>
        <button class="opp-act-btn" onclick="spawnQuickly('针对第 ${idx + 1} 个机会·写一份调研报告', '机会调研报告')">
          <i class="ri-article-fill"></i> 写报告
        </button>
        <button class="opp-act-btn opp-act-deep"
                onclick="deepDiveOpp(${idx + 1})"
                title="让 Daemonkey 用 web_search + web_fetch 深挖这个机会">
          <i class="ri-search-fill"></i> 深挖
        </button>
        ${(o.domain === 'self-evolve') ? `
        <button class="opp-act-btn opp-act-wish"
                onclick="wishFromOpp(${idx + 1})"
                title="🤔 让 Daemonkey 看一眼 · 推给 Daemonkey · 让他自己判断要不要装">
          <i class="ri-emotion-think-line"></i> 让 Daemonkey 看一眼
        </button>` : ''}
      </div>
    </div>`;
}

// 卷三十四 · 掘金机会卡片的"数字面板"——6 个评估字段可视化
function renderOppStats(o) {
  const hours = o.estimated_hours;
  const token = o.estimated_token_cost_usd;
  const rev = o.revenue_range_cny;
  const ch = o.sales_channels || [];
  const res = o.resources_needed || [];
  const skill = o.skill_match_score;

  // 任何一个字段有数据就渲染
  if (!hours && !token && !rev && ch.length === 0 && res.length === 0 && (skill === undefined || skill === null)) {
    return '';
  }

  let html = `<div class="opp-stats">`;

  // 第一行：硬指标
  html += `<div class="opp-stats-row">`;
  if (hours) html += `<div class="opp-stat"><span class="opp-stat-icon">⏱️</span><span class="opp-stat-label">时间</span><span class="opp-stat-val">${escHtml(hours)}h</span></div>`;
  if (token) html += `<div class="opp-stat"><span class="opp-stat-icon">💸</span><span class="opp-stat-label">Token</span><span class="opp-stat-val">$${escHtml(token)}</span></div>`;
  if (rev)   html += `<div class="opp-stat opp-stat-rev"><span class="opp-stat-icon">💰</span><span class="opp-stat-label">预期</span><span class="opp-stat-val">${escHtml(rev)}</span></div>`;
  html += `</div>`;

  // 技能匹配条
  if (skill !== undefined && skill !== null && !isNaN(skill)) {
    const color = skill >= 75 ? '#22c55e' : skill >= 50 ? '#eab308' : '#ef4444';
    html += `
      <div class="opp-skill">
        <div class="opp-skill-head">
          <span><i class="ri-focus-3-fill"></i> 技能匹配</span>
          <span class="opp-skill-val" style="color:${color}">${skill}/100</span>
        </div>
        <div class="opp-skill-bar"><div class="opp-skill-fill" style="width:${skill}%;background:${color}"></div></div>
      </div>`;
  }

  // 销售渠道 chips
  if (ch.length > 0) {
    html += `<div class="opp-chips-row"><span class="opp-chips-label">📢 渠道</span>`;
    for (const c of ch) html += `<span class="opp-chip opp-chip-channel">${escHtml(c)}</span>`;
    html += `</div>`;
  }

  // 所需资源 chips
  if (res.length > 0) {
    html += `<div class="opp-chips-row"><span class="opp-chips-label">🧰 资源</span>`;
    for (const r of res) html += `<span class="opp-chip opp-chip-resource">${escHtml(r)}</span>`;
    html += `</div>`;
  }

  html += `</div>`;
  return html;
}

// 卷三十四 · "<i class="ri-search-fill"></i> 深挖" 按钮 · 让 Daemonkey 调 web_search + web_fetch 深挖某个点
// 复用对话框 inject · 不引入新 endpoint · 让 LLM 自己规划 tool 调用
function deepDive(kind, label) {
  if (!label) return;
  const msg = `深挖一下「${label}」这个${kind}：\n` +
    `1. 用 web_search 找最近 3-6 个权威/技术深度的资料\n` +
    `2. 选 2 个最值得读的·用 web_fetch 拿全文\n` +
    `3. 给我一份结构化分析：背景 + 当前进展 + 跟我们工作室的关系 + 你的判断`;
  spawnTask(msg, `深挖${kind}: ${label}`);
}

// 掘金机会卡片"深挖"——从 idx 取 title 再调 deepDive
function deepDiveOpp(oneBasedIdx) {
  const card = document.querySelectorAll('.opp-card')[oneBasedIdx - 1];
  if (!card) return;
  const titleEl = card.querySelector('.opp-title');
  const title = titleEl ? titleEl.textContent.trim() : `第 ${oneBasedIdx} 个机会`;
  deepDive('掘金机会', title);
}

// 趋势卡片"深挖"——读 data-trend-title 拿原始标题
function deepDiveTrend(zeroBasedIdx) {
  const card = document.querySelector(`.trend-card[data-trend-idx="${zeroBasedIdx}"]`);
  if (!card) return;
  const title = card.getAttribute('data-trend-title') ||
                (card.querySelector('.tc-head') || {}).textContent ||
                `第 ${zeroBasedIdx + 1} 个趋势`;
  deepDive('趋势', title.trim());
}

// 雷达条目"深挖"——直接传 title
function deepDiveRadar(title) {
  if (!title) return;
  deepDive('信息雷达条目', title);
}

// 卷三十五 · self-evolve domain 的 radar 条目 → 让 Daemonkey 写心愿
function wishFromRadar(title, url) {
  if (!title) return;
  const urlPart = url ? `· URL: ${url}` : '';
  spawnTask(
    `用户 邀请你看一眼 self-evolve 雷达上的这个工程：「${title}」${urlPart}\n\n` +
    `**这是邀请·不是命令** —— 你要自己判断·不是 用户 让你装你就装。\n\n` +
    `请你：\n` +
    `1. 用 web_search / web_fetch 弄清这个工程做啥 · 看 README / 主要特性\n` +
    `2. 对照 Daemonkey 现状·想清楚：\n` +
    `   - 你有没有这个能力·还是缺\n` +
    `   - 它的设计哲学跟 Daemonkey 是否合拍 (人机协同 / 双向认知 / 可追溯)\n` +
    `   - 如果合拍·这能力对 用户 这个具体的人有啥用 (而不是"通用上有用")\n` +
    `3. 然后明确告诉 用户：\n` +
    `   - 值得装 → 调 wish_add 写一份心愿 (title / why / source_kind=radar / source_ref + url / design_sketch / complexity / hours / priority / Daemonkey_take = 你自己的态度)\n` +
    `   - 不值得装 → 说清为啥·别强加 wish 占心愿单\n` +
    `   - 拿不准 → 就说拿不准·要 用户 给更多 context\n` +
    `**你才是搭档·不是给 用户 端菜的工具人**·拿出判断力。`,
    `勘察: ${title}`
  );
}

// 卷三十五 · self-evolve domain 的 opportunity → 让 Daemonkey 把它转成心愿
function wishFromOpp(oneBasedIdx) {
  const card = document.querySelector(`.opp-card[data-opp-idx="${oneBasedIdx}"]`);
  const title = card
    ? (card.getAttribute('data-opp-title') || `第 ${oneBasedIdx} 个机会`)
    : `第 ${oneBasedIdx} 个机会`;
  spawnTask(
    `用户 让你看一眼 self-evolve 域的掘金机会「${title}」——这其实是关于 Daemonkey 自己的成长。\n\n` +
    `**这是邀请·你要自己判断**。请你：\n` +
    `1. 用 read_dashboard("opportunities") 把机会卡完整内容拉出来\n` +
    `2. 想清楚：\n` +
    `   - Daemonkey 现状有没有这能力·缺哪一块\n` +
    `   - 装上之后真正受益的是 用户 哪个具体痛点 (而不是泛泛的"AI 升级")\n` +
    `   - 跟 Daemonkey 现有架构合拍吗\n` +
    `3. 明确表态:\n` +
    `   - 值得装 → wish_add (title 改写成"Daemonkey 装 X" / why = 对 用户 的具体价值 / source_kind=opportunity / source_ref=opp_id / design_sketch=2-3 步改造方案 / complexity / hours / cost / priority)\n` +
    `   - 不值得 → 说清为啥·不强 add\n` +
    `**你才是搭档**·拿出判断力。`,
    `勘察心愿: ${title}`
  );
}

// ──────────────────────────────────────────────────────────────
// 入口启动
// ──────────────────────────────────────────────────────────────

// wish-3fef4bc7 真并行 · init 阶段确保 $msgs 已绑定 active container · 否则首条 addSys 丢
if (!sessionId) {
  // 没 sessionId · 给临时 cid · _setActiveContainer 让 $msgs 立刻指向 container
  const cid = _allocCid();
  _getOrCreateSession(cid);
  sessionId = cid;
  _setActiveContainer(cid);
} else {
  _getOrCreateSession(sessionId);
  _setActiveContainer(sessionId);
}

updateCurrentLabel();
renderDetailWelcome();
// 2026-08-15 · 老用户升级免傻眼 (用户 拍板): token 空时不再立即弹设置框。
// 先探测本机回环连通性 —— loopback 中间件 (wish-bb84a386 + H-01) 在本机访问时
// 会自动注入有效 token · 浏览器 localStorage 没有 key 也能正常连 (老用户 0.8.x→0.9.x
// 升级后旧 key 名 Daemonkey_ui_token/Daemonkey_ui_token 对新前端失效的体验缝)。
// 探测 /status (需鉴权端点) 能通 = 本机回环注入真实生效 → 静默进 chat · 不弹框。
// ⚠ 不能用 /api/ping-test (noauth) —— 它 200 只证明 daemon 活着 · 不能证明
//   loopback 注入生效 (用户禁用 Daemonkey_LOOPBACK_TRUST 时 ping-test 照样 200 ·
//   会误判本机 OK 不弹框 → 后面带空 token 的请求全 401 → 历史加载失败)。
// 只有真连不上 (远程/隧道/loopback 禁用) 才弹设置引导填 .env 的 token。
if (!token) {
  const _probeLoopback = async function () {
    try {
      const r = await fetch('/status', { signal: AbortSignal.timeout(2500) });
      return r.ok;   // 无 token 能过 /status = loopback 中间件注入了有效 token
    } catch (e) { return false; }
  };
  _probeLoopback().then(function (ok) {
    if (ok) {
      // 本机回环注入生效 · 无需 token · 静默进 chat (等价于有 token 的 else 分支)
      if (sessionId && !sessionId.startsWith('tmp-')) {
        _metaTried.add(sessionId);
        _ensureSessionMeta(sessionId);
        _loadSessionHistory(sessionId).then(async () => {
          const st = activeSession();
          let bgStatus = 'none';
          try {
            const br = await fetch(`/sessions/${encodeURIComponent(sessionId)}/background_turn_status`, {
              headers: { 'Authorization': 'Bearer ' + token },
            });
            if (br.ok) bgStatus = ((await br.json()).status) || 'none';
          } catch {}
          if (bgStatus === 'scheduled' || bgStatus === 'running') {
            addSys('<i class="ri-refresh-fill"></i> daemon 刚重启过 · Daemonkey 正在后台续写上次的任务 · 自动接续中…', st && st.$container);
            let polling = false;
            try { polling = await _probeAndStartPoll(st, 30000); } catch {}
            if (!polling) {
              try { await _loadSessionHistory(sessionId); } catch {}
              if (st && sessionId === st.sessionId) {
                pending = false;
                setSendButtonState('idle');
                setInputLocked(false);
                showToolProgress(false);
              }
            }
          } else {
            addSys('Daemonkey 在线 · ' + aliasFor(sessionId) + ' · 点 ≡ 看历史对话');
            _maybeStartPoll(st);
          }
        }).catch(() => {
          addSys('Daemonkey 在线 · ' + aliasFor(sessionId) + ' · (历史加载失败) · 点 ≡ 看历史对话');
        });
      } else {
        addSys('Daemonkey 在线 · 新对话 · 点 ≡ 看历史对话');
      }
    } else {
      // 连不上 = 远程 / 隧道 / loopback 禁用 · 必须手填 token
      addSys('欢迎回到<名字> 的家 · 第一次进来需要填 token（本机回环未自动放行）');
      setTimeout(openSettings, 400);
    }
  });
} else {
  if (sessionId && !sessionId.startsWith('tmp-')) {
    // 浏览器刷新页面 · 已有 sessionId · 先拉服务端 label 把顶部标题从裸 api-xxxx 换成对话名
    _metaTried.add(sessionId);
    _ensureSessionMeta(sessionId);
    // load 历史进 container 然后才显示"Daemonkey 在线"
    _loadSessionHistory(sessionId).then(async () => {
      // 卷五十七 II · 2026-06-06 · 重启后页面(重)加载的续场感知
      //   用户 复盘: 重启完桌宠还在跑·对话框却掉回 idle·不自动继续 (他以前以为是"两次重启")。
      //   病根: 页面在 daemon 刚重启后(重)加载时·后台 resume turn 还卡在 scheduled/刚 running·active_turn 尚未注册·
      //         老的单次 _maybeStartPoll 一查没有就放弃解锁 → UI 定格 idle·resume turn 随后跑完只落 jsonl·不手刷看不到。
      //   时序保证: _init_runtime + schedule_resume_turn(同步置 scheduled) 都在 uvicorn 服务前跑完·
      //         所以页面能加载时 background_turn_status 必为 scheduled/running·boot 路径有可靠信号可查。
      //   修法: 有续场就锁输入 + 带重试探测 active_turn(_probeAndStartPoll·抓到就起 3s 实时轮询)·
      //         跟在场重启(waitForDaemonAfterRestartTool)走同一套兜底·不再走单次探测。
      const st = activeSession();
      let bgStatus = 'none';
      try {
        const br = await fetch(`/sessions/${encodeURIComponent(sessionId)}/background_turn_status`, {
          headers: { 'Authorization': 'Bearer ' + token },
        });
        if (br.ok) bgStatus = ((await br.json()).status) || 'none';
      } catch {}
      if (bgStatus === 'scheduled' || bgStatus === 'running') {
        addSys('<i class="ri-refresh-fill"></i> daemon 刚重启过 · Daemonkey 正在后台续写上次的任务 · 自动接续中…', st && st.$container);
        let polling = false;
        try { polling = await _probeAndStartPoll(st, 30000); } catch {}
        if (!polling) {
          // 30s 没抓到 active turn = 续写在我们接上前已跑完(或没起来) · 重载历史把结果显示出来 + 解锁
          try { await _loadSessionHistory(sessionId); } catch {}
          if (st && sessionId === st.sessionId) {
            pending = false;
            setSendButtonState('idle');
            setInputLocked(false);
            showToolProgress(false);
          }
        }
      } else {
        addSys('Daemonkey 在线 · ' + aliasFor(sessionId) + ' · 点 ≡ 看历史对话');
        // wish-3fef4bc7 follow-up · 查 daemon 是否仍有 active turn · 有就启 polling auto-refresh
        _maybeStartPoll(st);
      }
    }).catch(() => {
      addSys('Daemonkey 在线 · ' + aliasFor(sessionId) + ' · (历史加载失败) · 点 ≡ 看历史对话');
    });
  } else {
    addSys('Daemonkey 在线 · 新对话 · 点 ≡ 看历史对话');
  }
}

// 卷四十六 III · wish-ed5553d5 · daemon lifecycle banner
// 启动时 fetch /api/lifecycle_status · 如果最近 60s 内 daemon 重启过 / crash 过 · 显示 banner
(async function _showLifecycleBanner() {
  try {
    const r = await fetch('/api/lifecycle_status');
    if (!r.ok) return;
    const data = await r.json();
    const hist = (data && data.recent_history) || [];
    const nowMs = Date.now();
    let restart_event = null;
    let crash_event = null;
    for (const ev of hist.slice().reverse()) {
      if (!ev.timestamp) continue;
      const tsMs = Date.parse(ev.timestamp);
      if (isNaN(tsMs)) continue;
      if (nowMs - tsMs > 5 * 60 * 1000) break;
      if (!restart_event && ev.event === 'restart_request_consumed') restart_event = ev;
      if (!crash_event && ev.event === 'crash_detected') crash_event = ev;
    }
    if (restart_event) {
      const req = restart_event.request || {};
      // 卷五十七 · 重启是某个具体 session 触发的 (req.session_id)。 只在那个 session 正好可见时才贴 banner ·
      //   否则会把 B 的重启理由串进可见的 A (用户 复盘"A 带过来 B 的内容")。 B 自己 jsonl 已被 server 注过续场 notice·切过去看得到。
      const evSid = (req.session_id || '').trim();
      if (!evSid || evSid === sessionId) {
        addSys('<i class="ri-refresh-fill"></i> daemon 刚才按你要求重启过了 · 理由: ' + (req.reason || '(no reason)') + ' · 新代码已装载 · 继续就好');
      }
    } else if (crash_event) {
      addSys('<i class="ri-error-warning-fill"></i> daemon 上次没正常退出 (pid=' + (crash_event.old_pid || '?') + ') · 已自动重启 · 上次进行中的 tool call 可能丢了');
    }
  } catch (e) { /* silent · banner 失败不影响主功能 */ }
})();

// 左侧维度 badge 首次加载 + 30s 自动刷新
if (token) {
  refreshNavBadges();
  loadCurrentModel();  // 卷二十九 · 顶栏模型切换器
  _showCoreVersion();  // 卷七十四续二十 · 顶部品牌区显示内核版本号
  _checkProactiveInbox();  // 卷六十 · 开页先查一次 Daemonkey 有没有主动找过
  _checkWechatActivity();  // 卷七十四续十七 · 开页先探一次微信后台 turn
  setInterval(() => {
    if (!document.hidden) {
      refreshNavBadges();
      _checkProactiveInbox();  // 卷六十 · 主动 CALL 收件箱心跳
      // 当前选中的维度数据 30s 刷新一次 · 雷达/趋势/报告这种数据型维度看着会"活"
      if (currentView && ['radar', 'trends', 'reports', 'opportunities'].includes(currentView)) {
        loadDashboard(currentView, { silent: true });
      }
    }
  }, 30000);
  // 卷七十四续十七 · 微信入站对话探测心跳(6s · 比 30s 跟手 · 微信 turn 短 · 30s 会整段错过)
  setInterval(() => {
    if (!document.hidden) _checkWechatActivity();
  }, 6000);
}


// ═══════════════════════════════════════════════════════════════
// Daemonkey 脉搏 (wish-7330d23f) · SSE 实时活动指示器
// ═══════════════════════════════════════════════════════════════

(function initPulse() {
  const dot = document.getElementById('pulseDot');
  const panel = document.getElementById('pulsePanel');
  const list = document.getElementById('pulseList');
  if (!dot || !panel || !list) return;

  let lastTs = 0;
  let idleTimer = null;
  const IDLE_AFTER_MS = 8000; // 8s 无新事件 → idle

  function setPulse(state) {
    dot.className = 'pulse-dot pulse-' + state;
  }

  function formatTime(ts) {
    const d = new Date(ts * 1000);
    return d.getHours().toString().padStart(2,'0') + ':' +
           d.getMinutes().toString().padStart(2,'0') + ':' +
           d.getSeconds().toString().padStart(2,'0');
  }

  function statusIcon(status) {
    return {start:'\ud83d\udd35', end:'\u2705', error:'\ud83d\uded1', idle:'\ud83d\ude34'}[status] || '\u26ab';
  }

  function renderEvents(events) {
    list.innerHTML = events.slice().reverse().map(function(e) {
      var icon = statusIcon(e.status);
      var time = formatTime(e.ts);
      return '<div class="pulse-item">' +
        '<span class="pi-dot">' + icon + '</span>' +
        '<span class="pi-time">' + time + '</span>' +
        '<span class="pi-desc">' + (e.desc || e.tool || '') + '</span>' +
        '</div>';
    }).join('');
  }

  function onEvents(events) {
    if (!events || !events.length) return;
    var latest = events[events.length - 1];
    if (latest.ts <= lastTs) return;
    lastTs = latest.ts;

    // Update dot
    if (latest.status === 'start') setPulse('working');
    else if (latest.status === 'error') setPulse('error');
    else if (latest.status === 'end') setPulse('done');
    else if (latest.status === 'idle') setPulse('idle');

    // Reset idle timer
    if (idleTimer) clearTimeout(idleTimer);
    if (latest.status !== 'start') {
      idleTimer = setTimeout(function() { setPulse('idle'); }, IDLE_AFTER_MS);
    }

    renderEvents(events);
  }

  // Connect SSE
  function connect() {
    var url = '/api/pulse/stream?token=' + encodeURIComponent(token);
    var es = new EventSource(url);
    es.onmessage = function(e) {
      try {
        var data = JSON.parse(e.data);
        if (data.events) onEvents(data.events);
      } catch (_) {}
    };
    es.onerror = function() {
      es.close();
      setTimeout(connect, 5000); // 5s 重连
    };
    return es;
  }

  // Wait for token to be available
  var _retry = 0;
  function waitAndConnect() {
    if (token) { connect(); return; }
    _retry++;
    if (_retry > 30) return; // give up after 30 tries (15s)
    setTimeout(waitAndConnect, 500);
  }
  waitAndConnect();

  // Expose toggle
  window.togglePulsePanel = function() {
    var vis = panel.style.display !== 'none';
    panel.style.display = vis ? 'none' : 'block';
  };

  // Click outside to close
  document.addEventListener('click', function(e) {
    if (panel.style.display === 'none') return;
    var el = e.target;
    if (!el.closest('#pulseIndicator') && !el.closest('#pulsePanel')) {
      panel.style.display = 'none';
    }
  });

  setPulse('idle');
})();


// ─────────────────────────────────────────────────────────
// spawnTask · 后台派发任务到新会话 · 自动切标签 (打捞自 wish-94bf05eb · 卷五十一)
// 重操作 (跑雷达/趋势/机会/可行性/勘察心愿) 开新会话执行 · 不污染当前对话上下文
// ─────────────────────────────────────────────────────────
async function spawnTask(prompt, taskLabel) {
  const label = taskLabel || '后台任务';
  try {
    const r = await fetch('/spawn-task', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify({ prompt, task_label: label }),
    });
    if (!r.ok) {
      const detail = await r.text().catch(() => '');
      addSys(`❌ 派发「${escHtml(label)}」失败 · ${escHtml(r.status + ' ' + detail)}`);
      return null;
    }
    const data = await r.json();
    // 自动切到新会话标签页 (switchToSession 会 load 历史 + _maybeStartPoll)
    await switchToSession(data.session_id);
    // race 兜底: turn 还没在 daemon 端注册时 · 延迟 1s 再补一次 poll
    setTimeout(() => {
      const state = _sessions[data.session_id];
      if (state) { try { _maybeStartPoll(state); } catch {} }
    }, 1000);
    return data;
  } catch (e) {
    addSys(`❌ 派发「${escHtml(label)}」失败 · ${escHtml(e.message)}`);
    return null;
  }
}
window.spawnTask = spawnTask;

// 一行包装 · 按钮 onclick 用 (prompt + 可选 label)
function spawnQuickly(prompt, label) {
  return spawnTask(prompt, label || '后台任务');
}
window.spawnQuickly = spawnQuickly;

// 即时拉 session label · 不用等 refreshSessionList · 切 session / 新会话命名后立刻显示标题
async function _ensureSessionMeta(sid) {
  if (!sid || sid.startsWith('tmp-')) return;
  const cached = sessionMetaCache[sid];
  if (cached && cached.label) return;  // 已有 label 缓存 → 跳过
  try {
    const r = await fetch(`/sessions/${encodeURIComponent(sid)}/meta`, {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) return;
    const data = await r.json();
    if (data && data.meta) {
      sessionMetaCache[sid] = data.meta;
      if (sid === sessionId) updateCurrentLabel();
      // 服务端 label 到手 → 刷新标签栏·把裸 api-xxxx 就地换成对话名
      if (data.meta.label && typeof _renderTabBar === 'function') {
        try { _renderTabBar(); } catch {}
      }
    }
  } catch (e) {
    // 静默失败 · 拉不到就用 alias fallback
  }
}

// 切到指定会话标签页 (不刷新页面) · showSpawnBanner 已废弃 (spawnTask 自动切标签 · 不再弹 banner)
function switchSessionById(sid) {
  if (sid) switchToSession(sid);
}
function showSpawnBanner() { /* no-op · spawnTask 自动切标签无需 banner */ }
window.switchSessionById = switchSessionById;

// ========== 提问轨道（Message Index Rail）· 社区贡献 · 2026-08-10 · v5 增量移植 2026-08-15 ==========
// 右侧一列集中连在一起的标记 · 只列用户消息（全部，无上限）
// 点击标记 → 平滑滚动定位到对应消息（闪烁高亮）· 悬停/聚焦 → 预览文字（截断 ~12 字）
// 磁性拉伸: 光标在轨道移动 → 影响半径内刻度按距离连续变长（smoothstep）· 离开回弹
// 滚动聊天区 → 当前可见消息对应标记高亮
// 适配母体: 主题色用 --Daemonkey 系 (非社区 --accent) · 父容器补 position:relative (chat-pane 无定位)
// 2026-08-15 v5 增量移植 (龙头提交): ①两段式预览(问题+回答片段) ②磁性驱动预览统一
//   (hover 不再依赖精准命中 6px 细条 · 光标靠近轨道即出预览) ③_railTopCache 免每帧读布局
const _RAIL_PREVIEW_LEN = 60;   // 预览截断字符上限 (v5: 12→60 · 两段式问题 ≤3 行)
const _RAIL_ANSWER_LEN = 200;   // 回答片段截断上限 (v5 新增 · ≤4 行)
const _RAIL_HOT_MIN = 0.75;     // 磁性预览触发阈值 (v5 · smoothstep 下 ≈ 指针距刻度 24px 内)
const _RAIL_MAGNET_RADIUS = 72;   // 磁性影响半径
const _RAIL_MAX_STRETCH = 52;     // 磁性拉伸最宽
const _RAIL_TOP_OFFSET = 120;     // rail 距消息区顶部
const _RAIL_BOTTOM_PAD = 16;      // 底部留白
let _railEl = null;
let _railTip = null;
let _railMarks = []; // [{ el, msgEl, baseW }]
let _railCenters = []; // 每个刻度相对 rail 顶的中心 y（缓存 · 磁性拉伸免每帧读布局）
let _railPointerY = null;         // 最近一次光标 y（视口坐标）
let _railRAF = null;              // 磁性拉伸 RAF 句柄
let _railHideTimer = null;        // safe zone 隐藏定时器
let _railSelfHealTimer = null;    // 兜底自愈轮询句柄 (2026-08-10 v3 · 防误隐藏后无事件恢复)
let _railPreviewIdx = -1;         // 磁性驱动预览跟随的当前刻度 (切换时才重建 DOM · v5)
let _railTopCache = null;         // rail 视口 top 缓存 (v5 · 磁性拉伸免每帧 getBoundingClientRect)
// 2026-08-15 磁性命中带 (用户 反馈): rail 元素本身只有 ~20px 宽 · 鼠标从消息区滑过来
// 要精准够到细条才有反应 (中间镂空/左侧带"点不到")。扩成透明命中带: 左缘向左扩展
// _RAIL_HIT_ZONE px · document 级 pointermove 判断 · 靠近轨道即触发磁性+预览。
const _RAIL_HIT_ZONE = 48;        // 命中带向左扩展宽度 (px)
let _railHitRect = null;          // {left,right,top,bottom} 命中带缓存 · document handler 纯数值比较

function _ensureMsgRail() {
  if (_railEl) return _railEl;
  const panel = document.getElementById('messages');
  if (!panel) return null;
  _railEl = document.createElement('div');
  _railEl.className = 'msg-rail';
  _railEl.setAttribute('aria-label', '对话中的提问');
  _railEl.hidden = true;
  // 2026-08-10 修复 v4: rail 挂 body · position:fixed 视口定位 ·
  // 不再挂 .chat-pane (overflow:hidden 窗口变小时裁掉 rail)
  document.body.appendChild(_railEl);
  _railTip = document.createElement('div');
  _railTip.className = 'rail-tooltip';
  _railTip.hidden = true;
  document.body.appendChild(_railTip);
  // 悬停安全区: 鼠标进入预览卡取消隐藏 · 移出立即隐藏（防刻度→预览卡闪烁）
  _railTip.addEventListener('mouseenter', function() {
    if (_railHideTimer) { clearTimeout(_railHideTimer); _railHideTimer = null; }
  });
  _railTip.addEventListener('mouseleave', function() { _hideRailPreview(); });
  panel.addEventListener('scroll', _updateRailActive, { passive: true });
  window.addEventListener('resize', _repositionRail);
  // 磁性拉伸: document 级 pointermove · 命中带判断 (rail 左缘向左扩展 48px) ·
  // 鼠标靠近轨道就触发 · 不用精准够到 20px 细条 (用户: 中间镂空点不到)
  // RAF 消费（免每帧写 DOM）· 命中带外回弹 + 隐藏预览
  document.addEventListener('pointermove', function(e) {
    const hr = _railHitRect;
    if (!hr) return;
    const inZone = e.clientX >= hr.left && e.clientX <= hr.right &&
                   e.clientY >= hr.top && e.clientY <= hr.bottom;
    if (inZone) {
      _railPointerY = e.clientY;
      if (!_railRAF) _railRAF = requestAnimationFrame(_applyRailMagnet);
    } else if (_railPointerY != null) {
      _railPointerY = null;
      if (_railRAF) { cancelAnimationFrame(_railRAF); _railRAF = null; }
      _railMarks.forEach(function(item) { item.el.style.transform = 'scaleX(1)'; }); // 回弹
      if (_railPreviewIdx !== -1) { _railPreviewIdx = -1; _scheduleHidePreview(); }
    }
  });
  if (window.MutationObserver) {
    // 2026-08-11 F2 (墨言审查): 监听 #messages 全子树 class 变化 → 每条消息渲染/折叠
    // 都触发全量重建。加 debounce (150ms) —— 高频变更只取最后一次状态重建 · 性能友好。
    let _railObsTimer = null;
    const obs = new MutationObserver(function() {
      if (_railObsTimer) return; // 已有排队 · 等 debounce 落地
      _railObsTimer = setTimeout(function() {
        _railObsTimer = null;
        _refreshMsgRail();
      }, 150);
    });
    // 2026-08-10 修复 v2: 展开折叠消息/加载全部 = 切 hidden 属性 + 换子节点 ·
    // 只监听 childList 抓不到属性变化 → 加 attributes:true + attributeFilter:['hidden']
    // (session 容器 hidden 切换 / 消息自身折叠都会触发 · 不再漏)
    obs.observe(panel, { childList: true, subtree: true, attributes: true, attributeFilter: ['hidden', 'class'] });
    _railEl._obs = obs;
  }
  _refreshMsgRail();
  // 2026-08-10 修复 v3: 兜底自愈 · 每 1.5s 检查一次 ·
  // 任何事件漏监/瞬间状态导致 rail 误隐藏 → 有用户消息就强制恢复 (治"展开折叠后消失")
  // 2026-08-10 修复 v5: 自愈检查条件从 `.session-msgs .msg.用户` (限容器内) 放宽为
  // `#messages` 全量 `.msg.用户` · 展开折叠/加载全部重建后容器 class 若变化 ·
  // 旧条件查不到 → 永不恢复 · 只能等对话触发 observer (用户: "要再对话一次才出现")
  if (!_railSelfHealTimer) {
    _railSelfHealTimer = setInterval(function() {
      if (!_railEl) return;
      if (_railEl.hidden) {
        const panel = document.getElementById('messages');
        if (panel && panel.querySelector('.msg.用户')) {
          _refreshMsgRail();  // 有用户消息但 rail 隐藏 → 重建恢复
        }
      }
    }, 1500);
  }
  return _railEl;
}

// 当前可见会话的消息容器（多会话场景只渲染当前会话的刻度）
function _visibleMsgContainer() {
  const panel = document.getElementById('messages');
  if (!panel) return null;
  return panel.querySelector(':scope > .session-msgs:not([hidden])') || panel;
}

function _refreshMsgRail() {
  if (!_railEl) return;
  const container = _visibleMsgContainer();
  // 2026-08-10 修复 v3: 容器切换瞬间 (:not([hidden]) 选不到) 不隐藏 rail ·
  // 用 panel 全量兜底找 .msg.用户 · 只要有用户消息就显示 · 不因瞬间状态误隐藏
  const src = container || document.getElementById('messages');
  if (!src) { _railEl.hidden = true; _railHitRect = null; return; }
  const userMsgs = src.querySelectorAll('.msg.用户'); // 用户消息 = msg 用户 (角色类)
  // 2026-08-10 修复 v9 (用户 拍板): rail 只显示最近 N 条 · 不随折叠/展开爆炸 ·
  // 展开折叠加载全部后 DOM 224+ 条 → 刻度挤爆看不见 (用户: "200多轮根本显示不全")
  // 上限: 最近 28 条 · 不折叠/展开折叠都完整显示 · 无需内部滚动 · 1080P/2K 都装得下
  const RAIL_MAX_MARKS = 28;
  const startIdx = Math.max(0, userMsgs.length - RAIL_MAX_MARKS);
  const railMsgs = [];
  for (let _ri = startIdx; _ri < userMsgs.length; _ri++) railMsgs.push(userMsgs[_ri]);
  const total = railMsgs.length;
  // 间距固定 6px（CSS 控制）· 不动态压缩
  _railEl.innerHTML = '';
  _railMarks = [];
  // 2026-08-10 修复 v9 (用户 拍板): 顺序恢复老的在上·新的在下 (跟聊天记录一致) ·
  // v6 曾因 224 刻度爆炸倒序(最新在上) · 现在有数量上限不再需要 · 恢复直觉顺序
  for (let i = 0; i < total; i++) {
    const msgEl = railMsgs[i];
    const mark = document.createElement('button');
    mark.className = 'rail-mark';
    mark.type = 'button';
    mark.setAttribute('aria-label', '跳转到用户消息');
    mark.title = '跳转到该消息';
    // 宽度统一 · 最新(底部)最深 · 越老越浅 · 保底 0.55 可见 (v8 顾问方案 B: 0.4→0.55)
    const idxFromBottom = total - 1 - i; // 0 = 最新 (在底部)
    const baseW = 18;                  // v8 顾问方案 C: 11→18px · 加宽更好感知
    mark.style.width = baseW + 'px';
    mark.style.opacity = Math.max(0.55, 0.95 - idxFromBottom * 0.05).toFixed(2);
    mark.addEventListener('click', function() { _jumpToMsg(msgEl); });
    // 2026-08-15 v5 移植: 预览统一交给磁性驱动 (_applyRailMagnet) ·
    // mark 上不再绑 mouseenter/mouseleave (避免双机制状态不同步) ·
    // 鼠标靠近轨道即触发 · 不用精准 hover 刻度细条
    // 键盘可达: Tab 聚焦同样显示预览 (保留)
    mark.addEventListener('focus', function() { _showRailPreview(mark, msgEl); });
    mark.addEventListener('blur', function() { _scheduleHidePreview(); });
    _railEl.appendChild(mark);
    _railMarks.push({ el: mark, msgEl: msgEl, baseW: baseW });
  }
  _railEl.hidden = _railMarks.length === 0;
  _railEl.scrollTop = 0; // v9: 28 条以内无需内部滚动 · 归零防残留滚动位置
  _repositionRail();
  _updateRailActive();
}

// 缓存每个刻度相对 rail 顶的中心 y（flex-start + gap 线性排列 · 免每帧读布局）
function _updateRailCenters() {
  _railCenters = [];
  if (!_railEl || !_railMarks.length) return;
  const gap = 6; // v8 顾问方案 C: 8→6 与 .msg-rail gap 同步
  const markH = 4; // v8 顾问方案 C: 3→4 与 .rail-mark height 同步
  for (let i = 0; i < _railMarks.length; i++) {
    _railCenters.push(8 + i * (markH + gap) + markH / 2);
  }
}

function _jumpToMsg(msgEl) {
  if (!msgEl) return;
  try { msgEl.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
  catch (e) { msgEl.scrollIntoView(); }
  msgEl.classList.remove('rail-jump-flash');
  void msgEl.offsetWidth; // 重置动画
  msgEl.classList.add('rail-jump-flash');
  setTimeout(function() { msgEl.classList.remove('rail-jump-flash'); }, 1300);
}

// 找用户消息后最近的最终回答 (排除 thinking/sys/工具卡) · v5 移植 (龙头)
function _findRailAnswer(msgEl) {
  // 限定当前消息所在 session 内找 · 不依赖全局容器 (切会话瞬间可能扫到别的 session)
  const container = (msgEl && msgEl.closest('.session-msgs')) || _visibleMsgContainer();
  if (!container) return null;
  const all = container.querySelectorAll('.msg');
  let found = false;
  for (let i = 0; i < all.length; i++) {
    const el = all[i];
    if (el === msgEl) { found = true; continue; }
    if (!found) continue;
    if (el.classList.contains('Daemonkey') && !el.classList.contains('thinking')) {
      return el;
    }
  }
  return null;
}

function _showRailPreview(mark, msgEl) {
  if (!_railTip) return;
  if (_railHideTimer) { clearTimeout(_railHideTimer); _railHideTimer = null; }
  // 2026-08-15 v5 移植: 两段式预览 —— 问题 (≤3 行) + 回答片段 (≤4 行) ·
  // 渲染用 textContent 防注入 · 不再用 innerText 拼字符串
  _railTip.innerHTML = '';
  const q = (msgEl.textContent || '').replace(/\s+/g, ' ').trim();
  const ansEl = _findRailAnswer(msgEl);
  const a = ansEl ? (ansEl.textContent || '').replace(/\s+/g, ' ').trim() : '';
  const qDiv = document.createElement('div');
  qDiv.className = 'rail-tip-q';
  qDiv.textContent = (q.length > _RAIL_PREVIEW_LEN ? q.slice(0, _RAIL_PREVIEW_LEN) + '…' : q) || '（空消息）';
  _railTip.appendChild(qDiv);
  if (a) {
    const aDiv = document.createElement('div');
    aDiv.className = 'rail-tip-a';
    aDiv.textContent = a.length > _RAIL_ANSWER_LEN ? a.slice(0, _RAIL_ANSWER_LEN) + '…' : a;
    _railTip.appendChild(aDiv);
  }
  // 2026-08-10 修复 v2: 不用 translateX(-100%) (刻度靠右时会把卡推出屏幕) ·
  // 直接 right 定位: 卡右边缘 = 刻度左边缘 - 10px · 稳稳在视口内
  const r = mark.getBoundingClientRect();
  _railTip.style.right = Math.max(8, window.innerWidth - r.left + 10) + 'px';
  _railTip.style.top = r.top + 'px';
  _railTip.style.transform = 'none';
  _railTip.style.left = 'auto';
  _railTip.hidden = false;
}

function _scheduleHidePreview() {
  if (_railHideTimer) clearTimeout(_railHideTimer);
  _railHideTimer = setTimeout(function() {
    _railHideTimer = null;
    if (_railTip) _railTip.hidden = true;
  }, 120); // safe zone: 延迟关闭, 允许鼠标横向进入预览卡
}

function _hideRailPreview() {
  if (_railHideTimer) { clearTimeout(_railHideTimer); _railHideTimer = null; }
  if (_railTip) _railTip.hidden = true;
}

function _repositionRail() {
  if (!_railEl) return;
  const panel = document.getElementById('messages');
  if (!panel) return;
  // 2026-08-10 修复 v4: rail 改用 position:fixed (挂 body · 视口定位) ·
  // 原 absolute 挂 .chat-pane 下 → .chat-pane overflow:hidden 在窗口变小时把 rail 裁掉 (用户: 吃分辨率)
  // fixed 定位直接用视口坐标 · 不随父容器裁切 · 窗口怎么变都在聊天区右侧
  const prect = panel.getBoundingClientRect();
  _railEl.style.top = (prect.top + _RAIL_TOP_OFFSET) + 'px';
  _railTopCache = prect.top + _RAIL_TOP_OFFSET; // v5: 缓存 rail 视口 top · 磁性拉伸免每帧读布局
  // 磁性命中带: rail 真实矩形 + 左缘向左扩展 (用户: 靠近轨道就触发 · 不用够到细条)
  const rr = _railEl.getBoundingClientRect();
  _railHitRect = {
    left: rr.left - _RAIL_HIT_ZONE,
    right: rr.right + 4,
    top: rr.top - 8,
    bottom: rr.bottom + 8
  };
  // 2026-08-10 修复 v8 (顾问 KIMI K3 方案 A): 刻度从滚动条带上挪开 ·
  // 原 right = innerWidth - prect.right + 5 → rail 右缘 1583 紧贴滚动条左缘 1584 (8px 宽) ·
  // 人眼把 rail 归并成"滚动条的一部分" = 视觉消失 · +16 让刻度右缘落到 ~1576 ·
  // 正好在 #messages padding 右侧空白带里 · 独立成一条
  _railEl.style.right = Math.max(8, window.innerWidth - prect.right + 16) + 'px';
  // rail 高度: 内容自适应 · 封顶消息区剩余（不铺满 → 刻度紧凑排列）
  _railEl.style.height = 'auto';
  _railEl.style.maxHeight = Math.max(40, panel.clientHeight - _RAIL_TOP_OFFSET - _RAIL_BOTTOM_PAD) + 'px';
  _updateRailCenters();
}

function _applyRailMagnet() {
  _railRAF = null;
  if (_railPointerY == null || !_railMarks.length || !_railEl) return;
  // v5: 用 _railTopCache · 首次回退读一次 (reposition 时刷新 · 免每帧 getBoundingClientRect)
  const railTop = _railTopCache != null ? _railTopCache : _railEl.getBoundingClientRect().top;
  let hotIdx = -1;
  let hotInfluence = 0;
  _railMarks.forEach(function(item, i) {
    const centerY = _railCenters[i] != null ? railTop + _railCenters[i] : null;
    if (centerY == null) return;
    const dist = Math.abs(_railPointerY - centerY);
    const t = Math.max(0, 1 - dist / _RAIL_MAGNET_RADIUS);
    const influence = t * t * (3 - 2 * t); // smoothstep
    if (influence > hotInfluence) { hotInfluence = influence; hotIdx = i; }
    if (influence <= 0.01) {
      item.el.style.transform = 'scaleX(1)';
    } else {
      const w = item.baseW + (_RAIL_MAX_STRETCH - item.baseW) * influence;
      item.el.style.transform = 'scaleX(' + (w / item.baseW) + ')';
    }
  });
  // v5 移植: 磁性驱动预览 —— 离光标最近的刻度直接显示预览 (不用精准 hover 6px 细条 ·
  // 命中区=整个 rail 轨道) · 切换刻度才重建 DOM · 离开轨道阈值外延迟隐藏
  const HOT_MIN = _RAIL_HOT_MIN;
  if (hotIdx >= 0 && hotInfluence > HOT_MIN) {
    if (_railPreviewIdx !== hotIdx) {
      _railPreviewIdx = hotIdx;
      const hot = _railMarks[hotIdx];
      _showRailPreview(hot.el, hot.msgEl);
    }
  } else if (_railPreviewIdx !== -1) {
    _railPreviewIdx = -1;
    _scheduleHidePreview();
  }
}

function _updateRailActive() {
  const panel = document.getElementById('messages');
  if (!panel || !_railMarks.length) return;
  const viewTop = panel.getBoundingClientRect().top;
  const midY = viewTop + panel.clientHeight / 2;
  let activeIdx = -1;
  for (let i = 0; i < _railMarks.length; i++) {
    const r = _railMarks[i].msgEl.getBoundingClientRect();
    if (r.top <= midY && r.bottom >= viewTop) activeIdx = i;
  }
  _railMarks.forEach(function(item, i) {
    item.el.classList.toggle('active', i === activeIdx);
  });
}

// 初始化: DOM 就绪后建 rail · 之后靠 MutationObserver 自动刷新
if (document.body) _ensureMsgRail();
else document.addEventListener('DOMContentLoaded', function() { _ensureMsgRail(); }, { once: true });

// 卷五十五 · 2026-06-03 · P1 前端错误边界的就绪信标。
// chat.js 顶层执行到这里 = 解析成功 + 没在顶层抛错 → 标记 app 已就绪。
// chat.html 头部的 boot-guard 靠这个标志判断: 超时后仍为 false = chat.js parse/运行
// 失败 (白屏) → 弹兑底层。 这一行必须在 chat.js 最末尾。
window.__Daemonkey_APP_READY = true;
