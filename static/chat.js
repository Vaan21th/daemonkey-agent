/*
 * chat.js · OPUS 工作室 WebUI 行为脚本
 * 卷二十二 Day 2 · 从 chat.html 拆出来
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
// 界面里历史遗留写死的 "OPUS" 全部换成它——一个集中机制·不必逐处改 100+ 串。
// 正则 /OPUS(?![\w-])/ 只换"OPUS"作为称呼出现的地方·跳过 OPUS_API_TOKEN 这类技术标识。
(function () {
  var NAME = (window.__AI_NAME__ || '').trim();
  var OWNER = (window.__OWNER_NAME__ || '').trim();
  var doAI = NAME && NAME !== 'OPUS';           // AI 自己的名字
  var doOwner = OWNER && OWNER !== 'BRO';        // 主人的称呼 (卷六十四续十一 · UI 里的 BRO 也换掉)
  if (!doAI && !doOwner) return;                // 两者都默认 → 保持原样
  // 正则跳过 OPUS_API_TOKEN 这类技术标识·只换作为称呼出现的词
  var RE_AI = /OPUS(?![\w-])/g;
  var RE_OWNER = /\bBRO(?![\w-])/g;
  function fix(s) {
    if (!s) return s;
    if (doAI && s.indexOf('OPUS') >= 0) s = s.replace(RE_AI, NAME);
    if (doOwner && s.indexOf('BRO') >= 0) s = s.replace(RE_OWNER, OWNER);
    return s;
  }
  function _hit(v) { return v && ((doAI && v.indexOf('OPUS') >= 0) || (doOwner && v.indexOf('BRO') >= 0)); }
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
  function run() { walk(document.body); }
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

// ── 0.2.0 · 新对话引导卡 onboarding panel ──
// messages 容器空 (新对话 / 切到没消息的会话) → 显示 panel · 一旦有消息 → hide
// 点卡 → 把模板填入输入框 + focus + 不直接发 (可改完再发)
// 模板可自定义 · 存 localStorage 'opus.onboarding.templates'
// 注意: 模板文本是 prefill 进输入框的·不走前端 localize·所以这里不能写死 OPUS·要中性
const _ONBOARD_DEFAULT_TEMPLATES = {
  create_app: '我想造一个应用 · 用来 [描述用途 · 例如「自动抓 B 站热门评论」]\n输入是: [列字段]\n输出是: [列字段]\n你帮我设计 system_prompt + 工具白名单 + ui_form_schema · 然后落到工坊。',
  create_flow: '我想搭一条工作流 · 名字叫 [起一个]\n流程是:\n  1. [第一步用什么 app · 干啥]\n  2. [第二步用什么 app · 干啥]\n  3. ...\n你帮我用 create_workflow 落档 · 我看了再说跑不跑。',
  chat_about: '聊聊吧 · 你是谁 · 你能做什么 · 你跟其他 AI 有什么不一样\n你为什么叫这个名字 · 你平时最擅长帮我做什么\n说人话 · 不要列表式答 · 像跟朋友吹水',
  list_capability: '把工坊里所有应用 (list_apps detailed=true) 和工作流 (list_flows detailed=true) 都列给我看看\n按用途分类 · 我想知道哪些能直接跑 · 哪些是给工作流当零件用的',
  // 换皮肤卡 · 模板里"换成 X 主题"会触发前端 matchThemePreset 直接切主题
  change_theme: '把界面主题换成 [暗紫 / 经典灰 / 白天 / 护眼暖黄 / 海洋蓝 / 森林绿 / 日落橙 / 粉色 / 粉白] 主题\n或者 · 你帮我设计一套 [描述风格 · 例如「赛博蓝紫·像 dune 沙漠」] 的配色 · 输出 ```theme JSON``` 代码块',
};

function _loadOnboardingTemplates() {
  try {
    const raw = localStorage.getItem('opus.onboarding.templates');
    if (raw) {
      const parsed = JSON.parse(raw);
      return Object.assign({}, _ONBOARD_DEFAULT_TEMPLATES, parsed);
    }
  } catch (e) {}
  return _ONBOARD_DEFAULT_TEMPLATES;
}

function _saveOnboardingTemplates(custom) {
  try {
    localStorage.setItem('opus.onboarding.templates', JSON.stringify(custom));
  } catch (e) {}
}

// 判断: visible .session-msgs 里有没有实质的 .msg.bro / .msg.opus (排除 sys / thinking 兜底)
function refreshOnboardingPanel() {
  const panel = document.getElementById('onboardingPanel');
  const messages = document.getElementById('messages');
  if (!panel || !messages) return;
  let scope = messages.querySelector(':scope > .session-msgs:not([hidden])');
  if (!scope) scope = messages;
  const hasRealMsg = !!scope.querySelector('.msg.bro, .msg.opus:not(.thinking)');
  panel.hidden = hasRealMsg;
}
window.refreshOnboardingPanel = refreshOnboardingPanel;

function _initOnboardingPanel() {
  const panel = document.getElementById('onboardingPanel');
  if (!panel) return;
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
    const placeholderIdx = text.indexOf('[');
    if (placeholderIdx >= 0) {
      const endIdx = text.indexOf(']', placeholderIdx);
      if (endIdx > placeholderIdx) input.setSelectionRange(placeholderIdx + 1, endIdx);
    }
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  const customizeBtn = document.getElementById('onboardingCustomize');
  if (customizeBtn) customizeBtn.addEventListener('click', _openOnboardingCustomizer);
  // 监听 messages 变化 (有消息 → hide · 清空 → show) · subtree + hidden 属性都要看
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
  const labels = {
    create_app: '<i class="ri-puzzle-fill"></i> 创建一个应用',
    create_flow: '<i class="ri-flow-chart"></i> 搭建一个工作流',
    chat_about: '<i class="ri-chat-3-fill"></i> 聊聊日常 · 认识我',
    list_capability: '<i class="ri-book-shelf-fill"></i> 看看我能做什么',
    change_theme: '<i class="ri-palette-fill"></i> 换个皮肤',
  };
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

const STORAGE = {
  token: 'opus_ui_token',
  session: 'opus_ui_session',
  autoConfirm: 'opus_ui_auto_confirm',
  aliases: 'opus_ui_session_aliases',
};


// === 主题系统 · wish-7b89146f ===
const THEME_KEY = 'opus_ui_theme';
const THEME_CUSTOM_KEY = 'opus_ui_theme_custom';

const THEME_PRESETS = [
  { cls: '',              label: '暗紫',   aliases: ['暗紫','深色','暗色','夜间','暗黑','默认','原来的','恢复默认','回到原来','紫色','紫'] },
  { cls: 'theme-classic', label: '经典灰', aliases: ['经典','经典灰','旧版','老版','灰色','原来的灰'] },
  { cls: 'theme-light',   label: '白天',   aliases: ['白天','浅色','日间','明亮','亮色'] },
  { cls: 'theme-sepia',   label: '护眼暖黄', aliases: ['暖色','护眼','暖黄','sepia','米黄'] },
  { cls: 'theme-ocean',   label: '海洋蓝',   aliases: ['蓝色','海洋','海蓝','ocean'] },
  { cls: 'theme-forest',  label: '森林绿',   aliases: ['绿色','森林','forest'] },
  { cls: 'theme-sunset',  label: '日落橙',   aliases: ['橙色','日落','sunset','橘色'] },
  { cls: 'theme-pink',        label: '粉色',   aliases: ['粉色','粉红','pink','樱花'] },
  { cls: 'theme-pink-white',  label: '粉白',   aliases: ['粉白','樱花白','粉白主题'] },
];

function matchThemePreset(text) {
  // 必须有换主题意图才匹配 · 避免日常对话中的颜色词/常用词误触发
  const t = text.toLowerCase();
  const hasIntent = /(换|切|改成|变成|设为|用|主题|皮肤|颜色|模式)/.test(t) || t.length <= 4;
  if (!hasIntent) return null;
  for (const p of THEME_PRESETS) {
    for (const a of p.aliases) { if (t.includes(a)) return p; }
  }
  return null;
}

function applyTheme(cls, label) {
  document.body.classList.remove(...THEME_PRESETS.map(p=>p.cls).filter(Boolean));
  const cs = document.getElementById('theme-custom'); if (cs) cs.remove();
  if (cls) document.body.classList.add(cls);
  localStorage.setItem(THEME_KEY, cls||'dark');
  localStorage.setItem('opus_ui_theme_label', label||'深色');
  updateThemeDot();
}

function applyCustomTheme(vars, label) {
  document.body.classList.remove(...THEME_PRESETS.map(p=>p.cls).filter(Boolean));
  let s = document.getElementById('theme-custom');
  if (!s) { s = document.createElement('style'); s.id = 'theme-custom'; document.head.appendChild(s); }
  s.textContent = 'body { ' + Object.entries(vars).map(function(e){return e[0]+':'+e[1]+';'}).join('') + ' }';
  localStorage.setItem(THEME_KEY, 'custom');
  localStorage.setItem(THEME_CUSTOM_KEY, JSON.stringify(vars));
  localStorage.setItem('opus_ui_theme_label', label);
  updateThemeDot();
}

function initTheme() {
  const saved = localStorage.getItem(THEME_KEY) || 'dark';
  const label = localStorage.getItem('opus_ui_theme_label') || '深色';
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
  try { dot.style.background = getComputedStyle(document.body).getPropertyValue('--opus').trim(); } catch(e) {}
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

// 扫描 OPUS 消息中的自定义主题代码块 (```theme ... ```)
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

// 页面加载时初始化主题
initTheme();
let token = localStorage.getItem(STORAGE.token) || '';
// Daemonkey · 本机 loopback 自动信任：daemon 启动会自动生成 .env 里的 OPUS_API_TOKEN·
// 后端 loopback 中间件给同机 127.0.0.1 请求覆盖注入它·所以本机用户无需手填 token。
// 这里设个非空哨兵让前端所有 if(!token) 通过·真正鉴权由后端 loopback 豁免兜底
// (远程/跨网访问 hostname 不是 loopback·仍走原逻辑要求手填 token·安全)。
if (!token && ['127.0.0.1', '::1', 'localhost'].includes(location.hostname)) {
  token = 'loopback';
  try { localStorage.setItem(STORAGE.token, token); } catch (_) {}
}
// sessionId = 当前 visible 的 session id (UI 焦点)
// 后台跑的对话仍然有 state 在 _sessions[sid] 里·不被这一变量影响
let sessionId = localStorage.getItem(STORAGE.session) || '';
let autoConfirm = localStorage.getItem(STORAGE.autoConfirm) || 'confirm';
// 卷六十 · 主动 CALL 收件箱游标 · 初始化为本次开页时刻 · 只提示开页后 OPUS 主动开口的消息 (不回放历史)
let _proactiveLastSeen = new Date().toISOString();
// pending = 当前 visible session 的状态·切换 session 时从对应 state 里读
// (是 _sessions[sessionId].pending 的 visible mirror)
let pending = false;

// 0.2.0 · 工作流跑时进度 banner (进度可视化诉求)
// 轮询 /workshop/runs · 有 active flow / 最近完成都显示 banner · 点击展开看每 step 进度
// 异步化后 banner 必须显示 done/failed 通知 · 否则用户等不到回声
const _FLOW_RUNS_POLL_MS = 3000;
const _FLOW_RECENT_TERMINAL_MS = 90 * 1000;  // 90s 内的 done/failed 也显示 (用户看到结果再消失)
let _flowRunsTimer = null;
let _flowRunsActive = [];       // 当前展示集合 (running + 最近 90s 内 done/failed)
let _flowRunsDetailOpen = false;
let _flowRunsDetailCache = {};  // run_id → 完整 state (展开时 fetch · 折叠时也保留供下次秒开)
let _flowRunsDismissed = {};    // run_id → true · 用户点 "知道了" 后不再 banner

function _flowRunsToken() {
  try { return localStorage.getItem(STORAGE.token) || ''; } catch (e) { return ''; }
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

// 跨 tab 提醒 (用户切走 tab 也能感知 flow 跑完)
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

// 用户切回 tab 自动停闪 (有把 tab 切走的场景才需要闪 · 看了就不闪)
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) _stopTitleFlash();
});

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

    // diff: 上轮 running 这轮 done/failed → 触发 title 闪烁通知 (跨 tab 感知 · 切走也能看到)
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

// 用户点"知道了" 把已完成 run 从 banner 撤掉 (running 不许撤 · 还得看进度)
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
  // done/failed 给一个"知道了"按钮 · 用户看完撤掉 banner (running 不给)
  const dismissBtn = (status === 'done' || status === 'failed')
    ? `<button class="flow-run-dismiss" type="button" onclick="dismissFlowRun('${escAttr(runId)}')" title="收到 · 撤掉这条 banner 通知">知道了</button>`
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

function renderFlowRunStep(step) {
  const status = step.status || 'pending';
  const iconMap = { running: '◐', done: '✓', failed: '×', pending: '○', skipped: '·' };
  const icon = iconMap[status] || '○';
  const appRef = step.app || '';
  const meta = (window._opusWorkshopApps || []).find(a => a.id === appRef);
  const appName = (meta && meta.name) ? meta.name : appRef;
  const goal = step.goal || '';
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
  
  // ── 文档 → base64 直读 (不压缩) ──
  if (_DOC_MIMES.includes(mime)) {
    if (file.size > 10 * 1024 * 1024) { alert('文件太大 · 上限 10MB'); return Promise.resolve(); }
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

// wish-41ed72ef · 语音输入 · 浏览器 SpeechRecognition API
const $micBtn = document.getElementById('micBtn');
if ($micBtn) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    $micBtn.classList.add('unsupported');
    $micBtn.title = '语音输入不可用 · 需要 Chrome/Edge 浏览器';
  } else {
    let _rec = null;
    let _finalText = '';
    $micBtn.addEventListener('click', () => {
      if (_rec) {
        // 正在听 → 停止
        _rec.stop();
        return;
      }
      // 开始听
      _rec = new SR();
      _rec.lang = 'zh-CN';
      _rec.interimResults = true;
      _rec.continuous = true;
      _rec.maxAlternatives = 1;
      _finalText = '';

      _rec.onresult = (e) => {
        let interim = '';
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const r = e.results[i];
          if (r.isFinal) {
            _finalText += r[0].transcript;
          } else {
            interim += r[0].transcript;
          }
        }
        // 实时更新输入框: 已确认的文字 + 正在识别的文字 (灰色标记)
        $input.value = _finalText + interim;
        $input.style.height = 'auto';
        $input.style.height = Math.min($input.scrollHeight, 160) + 'px';
      };

      _rec.onend = () => {
        $micBtn.classList.remove('listening');
        _rec = null;
        // 把最终结果留在输入框
        if (_finalText) $input.value = _finalText;
        $input.focus();
      };

      _rec.onerror = (e) => {
        $micBtn.classList.remove('listening');
        _rec = null;
        if (e.error === 'not-allowed') {
          alert('麦克风权限被拒 · 请在浏览器设置中允许访问麦克风');
        } else if (e.error !== 'aborted') {
          // aborted 是正常停止 · 不提示
          console.warn('语音识别出错:', e.error);
        }
      };

      _rec.start();
      $micBtn.classList.add('listening');
    });
  }
}

const $modal = document.getElementById('settings');
// 卷三十六 · 当前 turn 的 id · 用来发 abort 请求
// wish-3fef4bc7 · 真并行后这些是 active session 的 mirror · 切换 session 时同步
let currentTurnId = null;
let currentAbortController = null;
const $tokenIn = document.getElementById('tokenInput');
const $sessionIn = document.getElementById('sessionInput');
const $autoIn = document.getElementById('autoConfirm');

// 卷三十五补丁6 · 进度条 + mutating 工具白名单
// 这些工具会写 data/ 下文件 · 改 dashboard 数据 · OPUS 调一次 → UI 立刻刷一次
// 只读工具 (read_file / grep_files / web_search / browser_fetch / shell_exec 等) 不在表 · 跳过
const MUTATING_TOOLS = new Set([
  'wish_add', 'wish_update',
  'tag_radar_item', 'manage_info_source',
  'init_domain', 'remove_domain', 'add_domain',
  'mine_opportunities', 'analyze_feasibility', 'record_outcome',
  'toggle_favorite', 'generate_report', 'expand_trend_to_report',
  'auto_pipeline', 'update_bro_note', 'refresh_radar', 'generate_trends',
  'opus_diary',
  // 卷五十四 · 工坊产出类补全 (之前漏了·OPUS 造完 app/草稿 看板不自动刷·用户 得手动 F5)
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
      <span class="list-filter-icon">🔎</span>
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
  }
}
function setToolProgressText(text) {
  const el = document.getElementById('toolProgress');
  if (!el) return;
  const t = el.querySelector('.tool-progress-text');
  if (t) t.textContent = text;
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
  if (!m || !m.startedAt) return;
  if (m.frozen) return; // tool_result 后停在总耗时不再跑
  const elapsed = Math.floor((Date.now() - m.startedAt) / 1000);
  const briefArgs = (m.summary || '').slice(0, 40);
  // 卷五十八 · wish-f30d571d · 有 tool_progress 步骤信息时优先显示步骤
  if (m.progressStep) {
    const stepText = m.progressStep + (m.progressMsg ? ' ' + m.progressMsg : '');
    setToolProgressText(`${stepText} · 已 ${elapsed}s`);
  } else {
    setToolProgressText(
      `OPUS 正在跑第 ${m.count} 个工具 · ${m.name || '?'}${briefArgs ? ' · ' + briefArgs : ''} · 已 ${elapsed}s`
    );
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
      // 必须走 OPUS_WORKSHOP_VIEW.refresh() 才能把 OPUS 新造的 app/flow 拉进来
      if (typeof currentView !== 'undefined' && currentView === 'workshop'
          && window.OPUS_WORKSHOP_VIEW && typeof window.OPUS_WORKSHOP_VIEW.refresh === 'function') {
        window.OPUS_WORKSHOP_VIEW.refresh();
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
    { id: 'vision', label: '<i class="ri-eye-fill"></i> 视觉模型', hint: '看图 fallback · 纯文本模型自动调用' },
    { id: 'access', label: '<i class="ri-key-fill"></i> 访问 & 会话', hint: 'API Token / Session / Auto-confirm' },
    { id: 'wechat', label: '<i class="ri-wechat-fill"></i> 微信 & 主动', hint: '扫码连微信 · 主动找你的频率 (猫系↔犬系)' },
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
      { llm: 'LLM 模型', vision: '视觉模型', access: '访问', wechat: '微信', data: '本地数据' }[tabId]
    ));
  });
  renderSettingsBody();
}

function renderSettingsBody() {
  if (_settingsTab === 'llm') renderSettingsLLM();
  else if (_settingsTab === 'vision') renderSettingsVision();
  else if (_settingsTab === 'access') renderSettingsAccess();
  else if (_settingsTab === 'wechat') renderSettingsWechat();
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
    const ok = await opusConfirm({
      title: '不填 API Key · 沿用当前',
      message: '你没填新的 API Key · 我会沿用当前 .env 里的 key 走 ' + cfg.provider_kind + ' / ' + cfg.model + '\n继续?',
      okText: '继续切',
      cancelText: '回去填 key',
    });
    if (!ok) return;
    // 后端要求 api_key 必填 · 这里如果当前 provider 还跟新 cfg 一致 · 后端会重读 env
    // 简化: 让用户填一次新 key (即便复用旧的)
    const k = await opusPrompt({
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
        <span class="llm-hint">勾选的会出现在右上角切换器 · 不勾选只在这里保留 · 想要常用模型直接对 OPUS 说「加几个 aihub 常用模型」即可</span>
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
    <div class="llm-config-card${isActive ? ' active' : ''}" data-cfg-id="${escHtml(c.id)}">
      <div class="lc-row1">
        <span class="lc-icon">${presetIcon}</span>
        <span class="lc-name">${escHtml(c.name || c.model || c.id)}</span>
        ${isActive ? '<span class="lc-active-badge">当前</span>' : ''}
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
          ${isActive ? '' : `<button onclick="activateConfig('${escHtml(c.id)}')" title="切换 OPUS 用这个跑">激活</button>`}
          <button onclick="testConfig('${escHtml(c.id)}')" title="ping 一下试通不通">测试</button>
          <button onclick="openLlmConfigEditForm('${escHtml(c.id)}')" title="改名 / 改 key / 改 model">编辑</button>
          <button class="btn-danger-mini" onclick="deleteConfig('${escHtml(c.id)}')" title="删除">删除</button>
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
  const key = await opusPrompt({
    title: '一键导入 AiHubMix 常用模型',
    message: '会自动加入: Sonnet 4.6 / Opus 4.7 / Kimi K2.6 / GLM 5.1 / GPT-5.5\n这些都是 用户 过去用过的 · 加进来默认不勾右上角 · 编辑里可以单独激活。\n\n填一次 AiHub key · 这些 configs 共用 (你也可以加完单独改 key):',
    placeholder: 'sk-xxx · AiHubMix 平台 key · 留空 = 只加占位不设 key',
    okText: '一键加',
    cancelText: '取消',
  });
  if (key === null) return;  // 取消
  const apiKey = (key || '').trim();
  const presets = [
    { name: 'Sonnet 4.6 · AiHubMix', model: 'claude-sonnet-4-6', note: '性价比·支持 cache' },
    { name: 'Opus 4.7 · AiHubMix', model: 'claude-opus-4-7', note: '深聊最强·5x 贵·支持 cache' },
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
    await opusAlert({ title: '部分失败', message: `加成功 ${okCount}/${presets.length}\n失败原因: ${failMsg.slice(0, 200)}`, icon: '<i class="ri-error-warning-fill"></i>' });
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
      };
      const r = await fetch('/provider-configs', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const t = await r.text();
        await opusAlert({ title: '保存失败', message: t.slice(0, 400), icon: '<i class="ri-error-warning-fill"></i>' });
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
      };
      if (form.api_key && form.api_key.trim()) patch.api_key = form.api_key;
      const r = await fetch('/provider-configs/' + encodeURIComponent(cfgId), {
        method: 'PATCH',
        headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      });
      if (!r.ok) {
        const t = await r.text();
        await opusAlert({ title: '保存失败', message: t.slice(0, 400), icon: '<i class="ri-error-warning-fill"></i>' });
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
      ${isEdit ? '' : `
      <div class="field">
        <label>
          <input id="llmEditSetActive" type="checkbox">
          保存后立即激活 (OPUS 切到这条跑)
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
  onLlmEditPresetChange();  // 触发一次 · 填模型下拉
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
    await opusAlert({ title: '激活失败', message: t.slice(0, 400), icon: '<i class="ri-error-warning-fill"></i>' });
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
    await opusAlert({ title: '改 pinned 失败', message: t.slice(0, 400), icon: '<i class="ri-error-warning-fill"></i>' });
    return;
  }
  await renderSettingsLLM();
  if (typeof loadCurrentModel === 'function') loadCurrentModel();
}

async function deleteConfig(cfgId) {
  const cfg = _providerConfigs.find(c => c.id === cfgId);
  const ok = await opusConfirm({
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
    await opusAlert({ title: '删除失败', message: t.slice(0, 400), icon: '<i class="ri-error-warning-fill"></i>' });
    return;
  }
  await renderSettingsLLM();
  if (typeof loadCurrentModel === 'function') loadCurrentModel();
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
}

function renderSettingsAccess() {
  const body = document.getElementById('settingsBody');
  body.innerHTML = `
    <div class="llm-section">
      <div class="llm-section-head"><h3>🔑 API Token · 决定 WebUI 能否连 daemon</h3></div>
      <div class="field">
        <label>API Token (Bearer)</label>
        <input id="accTokenIn" type="password" value="${escHtml(token || '')}" placeholder="OPUS_API_TOKEN">
        <div class="field-hint">来自 .env 里的 OPUS_API_TOKEN · 浏览器记住</div>
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

      <!-- wish-f563a56d · trusted commands · 用户 临时给 OPUS 30min/24h/永久 信任窗口 -->
      <div class="llm-section-head" style="margin-top:18px"><h3>🔓 Trusted Commands · 信任清单</h3></div>
      <div class="field-hint" style="margin-bottom:8px">
        当 auto_confirm=auto 时·CONFIRM 档命令 (例如 <code>pip install</code>) 会被 skip。
        把命令头加到信任清单后·窗口期内 OPUS 调这类命令自动通过。
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
          <input id="accTrustReason" type="text" placeholder="例如: 用户 让 OPUS 装 duckduckgo_search">
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
      target.innerHTML = '<i>暂无 trusted commands · OPUS 调 CONFIRM 档命令时会被 auto_confirm 策略卡住</i>';
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
        <button onclick="removeTrustedCommand('${escHtml(it.id)}')" style="background:transparent;border:1px solid #475569;color:#94a3b8;padding:2px 8px;border-radius:4px;cursor:pointer">删除</button>
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
    om.alert({ title: '空 pattern', message: '请填命令头 (例如 "pip install")' });
    return;
  }
  if (!token) {
    om.alert({ title: '缺 token', message: '请先填 API token' });
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
      om.alert({ title: '加入失败', message: 'HTTP ' + r.status + '\n' + txt });
      return;
    }
    document.getElementById('accTrustPattern').value = '';
    document.getElementById('accTrustReason').value = '';
    await refreshTrustedCommands();
  } catch (e) {
    om.alert({ title: '加入失败', message: e.message });
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
      om.alert({ title: '删除失败', message: 'HTTP ' + r.status + '\n' + txt });
      return;
    }
    await refreshTrustedCommands();
  } catch (e) {
    om.alert({ title: '删除失败', message: e.message });
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
      <div class="llm-section-head"><h3><i class="ri-wechat-fill"></i> 微信连接 · 官方 ClawBot (iLink)</h3></div>
      <div class="field-hint" style="margin-bottom:8px">
        纯 HTTP 官方接口·不碰微信客户端·无封号风险。规则:你在微信先发一句 → 开 <b>24 小时窗口</b>·
        窗口内 OPUS 能(主动)给你发·跨天零互动发不出 (腾讯反骚扰)。
      </div>
      <div id="wechatStatus" class="field-hint">加载中…</div>

      <div id="wechatQrZone" style="margin-top:12px">
        <button class="btn-primary" onclick="wechatGenQr()"><i class="ri-qr-code-line"></i> 生成扫码登录二维码</button>
        <div class="field-hint" style="margin-top:4px">手机微信扫一扫 → 授权『微信 ClawBot』。重新扫可换绑/续期。</div>
      </div>
      <div id="wechatQrBox" style="margin-top:12px;display:none;text-align:center"></div>

      <div class="llm-section-head" style="margin-top:22px"><h3>🐾 主动找你的频率 · 猫系 ↔ 犬系</h3></div>
      <div class="field-hint" style="margin-bottom:8px">
        从『高冷猫』到『黏人犬』——代表 OPUS 多久主动开口一次、多大概率突然想起你。
        命中后会在窗口内某个<b>随机</b>时刻找你·夜里(默认 23–9 点)永远不打扰。
      </div>
      <div id="wechatFreq" class="freq-seg">加载中…</div>
      <div id="wechatFreqDesc" class="field-hint" style="margin-top:8px"></div>
    </div>
  `;
  setTimeout(() => { wechatLoadStatus(); wechatLoadFrequency(); }, 30);
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
    const dot = (ok) => `<span style="color:${ok ? '#34d399' : '#f87171'}">●</span>`;
    let win;
    if (!s.configured) win = '<span style="color:#94a3b8">未连接 · 先扫码</span>';
    else if (s.window_open) win = `${dot(true)} 窗口开着 (${s.context_age_hours ?? '?'}h 前你说过话)`;
    else win = `${dot(false)} 窗口已关 · 你在微信发一句即可重开`;
    el.innerHTML = `
      连接 ${dot(s.configured)} ${s.configured ? '已扫码' : '未扫码'} ·
      监听 ${dot(listener.alive)} ${listener.alive ? '在线' : '离线'} ·
      ${s.silent ? '<span style="color:#f59e0b">🔇 静默中 (微信发 opus start 唤醒)</span>' : win}
      ${listener.alive ? `<br><span style="font-size:11px;color:#94a3b8">收 ${listener.messages_in || 0} · 回 ${listener.replies_out || 0}</span>` : ''}
    `;
  } catch (e) {
    el.innerHTML = '<i class="ri-close-fill"></i> 状态加载失败: ' + escHtml(e.message);
  }
}

async function wechatGenQr() {
  const box = document.getElementById('wechatQrBox');
  if (!token) { om.alert({ title: '缺 token', message: '先在『访问 & 会话』填 API Token' }); return; }
  if (_wechatQrPoll) { clearInterval(_wechatQrPoll); _wechatQrPoll = null; }
  box.style.display = 'block';
  box.innerHTML = '<div class="field-hint">取二维码中…</div>';
  try {
    const r = await fetch('/api/wechat/login/qr', {
      method: 'POST', headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    if (!d || !d.qr_data_uri) {
      box.innerHTML = '<div class="field-hint">' + escHtml((d && d.note) || '微信二维码暂时不可用 · 这是可选的高级功能') + '</div>';
      return;
    }
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

function wechatRenderFreq(currentId) {
  const el = document.getElementById('wechatFreq');
  const desc = document.getElementById('wechatFreqDesc');
  el.innerHTML = _wechatFreqPresets.map(p => `
    <button class="freq-pill ${p.id === currentId ? 'active' : ''}" onclick="wechatSetFrequency('${p.id}')" title="${escHtml(p.desc)}">
      <span class="freq-emoji">${p.emoji}</span><span class="freq-label">${escHtml(p.label)}</span>
    </button>
  `).join('');
  const cur = _wechatFreqPresets.find(p => p.id === currentId);
  if (desc) {
    desc.innerHTML = currentId === 'custom'
      ? '当前是<b>自定义</b>档 (你手改过 .env 的 OPUS_PROACTIVE_* )·点任意档位归一'
      : (cur ? `当前:${cur.emoji} <b>${escHtml(cur.label)}</b> · ${escHtml(cur.desc)}` : '');
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
    om.alert({ title: '设置失败', message: e.message });
  }
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
  const ok = await opusConfirm({
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
//   opusConfirm({ title, message, okText, cancelText, danger })  → Promise<boolean>
//   opusPrompt({ title, message, default, placeholder, okText }) → Promise<string|null>
//   opusAlert({ title, message, okText, icon })                  → Promise<void>
//
// 行为：
//   - 一次只能开一个 modal · 后调的进队列等前一个 resolve
//   - Enter = 确定 · ESC = 取消
//   - 点遮罩 = 取消（alert 模式下也允许·等价 OK）
// ──────────────────────────────────────────────────────────────
const _omEl = document.getElementById('opusModal');
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

function opusConfirm(opts) {
  opts = opts || {};
  return new Promise((resolve) => {
    _omQueue.push({ mode: 'confirm', ...opts, resolve });
    _omRunNext();
  });
}
function opusPrompt(opts) {
  opts = opts || {};
  return new Promise((resolve) => {
    _omQueue.push({ mode: 'prompt', ...opts, resolve });
    _omRunNext();
  });
}
function opusAlert(opts) {
  // 支持 opusAlert('字符串') 速写
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
  refreshSessionList();
}
function closeDrawer() {
  $drawer.classList.remove('open');
  $drawerBackdrop.classList.remove('open');
}

function updateCurrentLabel() {
  $currentLabel.textContent = sessionId ? aliasFor(sessionId) : '新对话';
}

async function refreshSessionList() {
  $sessionList.innerHTML = '<div class="drawer-empty">加载中…</div>';
  // 关掉可能开着的菜单
  closeSessionMenu();
  try {
    const params = new URLSearchParams({ api_only: 'true', limit: '50' });
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
      };
    }
    if (!data.sessions || data.sessions.length === 0) {
      const empty = showArchivedSessions
        ? '归档区是空的 · 已归档的对话会跑这儿'
        : '还没有对话 · 点 + 新对话开始';
      $sessionList.innerHTML = `<div class="drawer-empty">${empty}</div>`;
      renderArchivedToggle();
      return;
    }
    $sessionList.innerHTML = '';
    for (const s of data.sessions) {
      $sessionList.appendChild(buildSessionRow(s));
    }
    renderArchivedToggle();
    // 当前 session label 可能从服务端拿到了 · 刷新顶部 pill
    updateCurrentLabel();
  } catch (e) {
    $sessionList.innerHTML = '<div class="drawer-empty">网络出错: ' + e.message + '</div>';
  }
}

function buildSessionRow(s) {
  const div = document.createElement('div');
  const isPinned = !!s.pinned_at;
  const isArchived = !!s.archived_at;
  div.className = 'session-item' + (s.session_id === sessionId ? ' active' : '')
                 + (isPinned ? ' pinned' : '')
                 + (isArchived ? ' archived' : '');
  div.dataset.sid = s.session_id;

  const name = document.createElement('div');
  name.className = 'session-name';
  const pinIcon = isPinned ? '<span class="sp-pin" title="置顶">📌</span>' : '';
  const archIcon = isArchived ? '<span class="sp-arch" title="已归档">📁</span>' : '';
  name.innerHTML = pinIcon + archIcon + '<span class="sp-label">' + escHtml(aliasFor(s.session_id)) + '</span>';

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
  refreshSessionList();
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
      ${isPinned ? '📌 取消置顶' : '📌 置顶'}
    </button>
    <button class="sm-item" onclick="event.stopPropagation();renameSession('${sid}')">
      ✏️ 重命名
    </button>
    <button class="sm-item" onclick="event.stopPropagation();toggleArchiveSession('${sid}')">
      ${isArchived ? '📂 取消归档' : '📁 归档'}
    </button>
    <div class="sm-sep"></div>
    <button class="sm-item danger" onclick="event.stopPropagation();deleteSession('${sid}')">
      🗑️ 删除
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
      await opusAlert({
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
    await opusAlert({ title: '网络出错', message: e.message, icon: '<i class="ri-error-warning-fill"></i>' });
    return false;
  }
}

async function togglePinSession(sid) {
  closeSessionMenu();
  const cur = sessionMetaCache[sid] || {};
  const want = !cur.pinned_at;
  const ok = await _patchSessionMeta(sid, { pinned: want });
  if (ok) refreshSessionList();
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
      refreshSessionList();
    }
  }
}

async function deleteSession(sid) {
  closeSessionMenu();
  const name = aliasFor(sid);
  const ok = await opusConfirm({
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
      await opusAlert({
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
      refreshSessionList();
    }
  } catch (e) {
    await opusAlert({ title: '网络出错', message: e.message, icon: '<i class="ri-error-warning-fill"></i>' });
  }
}

async function renameSession(sid) {
  closeSessionMenu();
  const current = aliasFor(sid);
  const name = await opusPrompt({
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
    refreshSessionList();
    if (sid === sessionId) updateCurrentLabel();
  }
}

// wish-3fef4bc7 · 历史 load 抽成 helper · 给 init / switchToSession 复用
// 历史 load 不动 state.pending 等 · 因为这个 session 没在跑
async function _loadSessionHistory(sid) {
  if (!sid) return;
  const s = _getOrCreateSession(sid);
  _getOrCreateContainer(sid);  // 确保 container 已建
  s.$container.innerHTML = '';
  addSys('加载中…', s.$container);
  try {
    const r = await fetch(`/sessions/${encodeURIComponent(sid)}/messages`, {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) {
      s.$container.innerHTML = '';
      addSys('加载历史失败 [' + r.status + ']', s.$container);
      return;
    }
    const data = await r.json();
    s.$container.innerHTML = '';
    if (!data.turns || data.turns.length === 0) {
      addSys('（这个对话还是空的）', s.$container);
    } else {
      // 卷三十六 · 历史回放 · 跟实时 SSE 那一套对齐 · reasoning / tool_call / tool_result 全渲染
      for (const t of data.turns) {
        if (t.role === 'user') {
          if (t.src === 'proactive') {
            addSys('OPUS 主动醒来' + (t.proactive_reason ? ' · ' + t.proactive_reason : ''), s.$container);
          } else {
            addMsg('bro', t.content, null, t.ts, s.$container);
          }
        } else if (t.role === 'assistant') {
          if (t.reasoning_content) {
            renderReasoningBubble(t.reasoning_content, { collapsed: true, historical: true }, s.$container);
          }
          if (t.content && t.content.trim()) {
            addMsg('opus', t.content, null, t.ts, s.$container);
          }
          if (t.tool_calls && t.tool_calls.length) {
            for (const tc of t.tool_calls) {
              renderHistoryToolCall(tc.name, tc.arguments, s.$container);
            }
          }
        } else if (t.role === 'tool') {
          renderHistoryToolResult(t.content, s.$container);
        }
      }
      addSys(`(已加载 ${data.count} 条历史 turn · 这条对话已结束 · 输入新消息可继续)`, s.$container);
    }
    // 卷四十六续 3 · batch 渲染期间 addMsg 走软滚 · scrollTop 一直在 0 · isNearBottom 一直 false
    // 加载完后必须 force 一次 · 否则 用户 看到的是最旧的消息(顶部) · 不是最新(底部)
    scrollToBottom(s.$container, { force: true });
  } catch (e) {
    s.$container.innerHTML = '';
    addSys('网络出错: ' + e.message, s.$container);
  }
}

async function switchToSession(sid) {
  if (!sid) return;
  if (sid === sessionId) {
    closeDrawer();
    return;
  }
  // wish-3fef4bc7 · 真并行 · 切对话不杀 · 旧对话的 fetch / state 留着 · 后台继续跑
  _saveActiveStateToCurrentSession();

  // 目标 sid 在 _sessions 里 = active session (跑过/正在跑) · 切 visible 即可 · 不重 load 历史
  const existing = _sessions[sid];
  if (existing && existing.$container && existing.$container.children.length > 0) {
    sessionId = sid;
    localStorage.setItem(STORAGE.session, sid);
    _setActiveContainer(sid);  // hide 旧 · show 这个 · DOM 直接拿现成的
    // 切回有"未读完成"标记的 · 清掉
    existing.hasUnreadCompletion = false;
    _loadActiveStateFromCurrentSession();
    setSendButtonState(pending ? 'pending' : 'idle');
    setInputLocked(pending);
    showToolProgress(pending);  // 这个 session 还在跑 · 进度条恢复
    updateCurrentLabel();
    _ensureSessionMeta(sid);
    closeDrawer();
    if (typeof _renderTabBar === 'function') {
      try { _renderTabBar(); } catch {}
    }
    return;
  }

  // 目标 sid 不在 _sessions = 历史 session · 创 container + load 历史 + 切 visible
  _getOrCreateSession(sid);
  _setActiveContainer(sid);
  sessionId = sid;
  localStorage.setItem(STORAGE.session, sid);
  updateCurrentLabel();
  _ensureSessionMeta(sid);
  closeDrawer();
  // 历史 session 是 idle (没有跑的 fetch)
  _loadActiveStateFromCurrentSession();
  setSendButtonState('idle');
  setInputLocked(false);
  showToolProgress(false);
  await _loadSessionHistory(sid);
  // wish-3fef4bc7 follow-up · 切到 history session 后 · 查 daemon 是否仍有 active turn · 有就启 polling
  _maybeStartPoll(_sessions[sid]);
  if (typeof _renderTabBar === 'function') {
    try { _renderTabBar(); } catch {}
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
    setToolProgressText('OPUS 重启完成 · 正在确认续写任务…');
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
    setToolProgressText('OPUS 后台仍在跑这个对话 · 自动刷新中…');
  }
  addSys('⏳ OPUS 仍在后台跑这个对话 · 自动刷新中 (3s/次) · 点 ⏹ 可中断', state.$container);
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
  } else if (wasPending) {
    // 后台 polling 完成 + 用户 不在看 · 弹 toast + tab 红点 (跟 send finally 后台完成对齐)
    state.hasUnreadCompletion = true;
    if (typeof _showCompletionToast === 'function') {
      try { _showCompletionToast(state); } catch {}
    }
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
  try {
    const r = await fetch(`/sessions/${encodeURIComponent(state.sessionId)}/active_turn`, {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (r.ok) {
      const j = await r.json();
      hasActive = !!(j && j.turn_id);
      activeTurnId = (j && j.turn_id) || null;
    }
  } catch {}
  // turn_id 可能在 polling 期间变了 (旧的被 stop · 新的开起来 — 极小概率) · 同步一下
  if (activeTurnId && state.currentTurnId !== activeTurnId) {
    state.currentTurnId = activeTurnId;
    if (sessionId === state.sessionId) currentTurnId = activeTurnId;
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
      for (const t of data.turns || []) {
        if (t.role === 'user') {
          addMsg('bro', t.content, null, t.ts, state.$container);
        } else if (t.role === 'assistant') {
          if (t.reasoning_content) {
            renderReasoningBubble(t.reasoning_content, { collapsed: true, historical: true }, state.$container);
          }
          if (t.content && t.content.trim()) {
            addMsg('opus', t.content, null, t.ts, state.$container);
          }
          if (t.tool_calls && t.tool_calls.length) {
            for (const tc of t.tool_calls) {
              renderHistoryToolCall(tc.name, tc.arguments, state.$container);
            }
          }
        } else if (t.role === 'tool') {
          renderHistoryToolResult(t.content, state.$container);
        }
      }
      state.lastTurnCount = newCount;
      const tail = hasActive
        ? '⏳ OPUS 仍在后台跑 · 自动刷新中…'
        : `(已加载 ${newCount} 条历史 turn · OPUS 这轮跑完了 · 输入新消息可继续)`;
      addSys(tail, state.$container);
    }
  } catch {}
  // 3) 没 active turn 了 · 停 polling (这是收尾 · _pollSession 不再触发)
  if (!hasActive) {
    _stopSessionPoll(state);
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

// 卷六十 · 主动 CALL 收件箱心跳 · 检测 OPUS 主动开口 → toast + 自动加载 · 不用手刷
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
        // 正开着这个 session → 直接重载历史 · OPUS 那句话立刻冒出来
        try { _loadSessionHistory(sessionId); } catch (e) {}
      } else if (it.session_id) {
        const st = _sessions[it.session_id];
        if (st) st.hasUnreadCompletion = true;
      }
    }
    if (typeof refreshSessionList === 'function') { try { refreshSessionList(); } catch (e) {} }
  } catch (e) { /* 静默 · 收件箱失败不影响主功能 */ }
}

// 卷六十 · OPUS 主动找你的 toast · 点击切到那个 session · 比普通完成 toast 多停一会
function _showProactiveToast(it) {
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
  titleEl.textContent = 'OPUS 主动找你了';
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
}

function formatTime(ts) {
  try {
    const d = ts ? (ts instanceof Date ? ts : new Date(ts)) : new Date();
    if (isNaN(d.getTime())) return '';
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
  } catch { return ''; }
}

// ──────────────────────────────────────────────────────────────
// 卷三十 · 简易 markdown 渲染器（chat 右栏用 · OPUS 输出 ### / **/ - / 1. / ``` 等都正确渲染）
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
    const icon = kind === 'video' ? '🎬' : (kind === 'audio' ? '🎵' : '🖼');
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
// 卷四十六续 11 补丁 · 暴露给 workshop.js 等其他 module 复用 (e.g. opus app 系统提示词渲染)
try { window.opusMdRender = mdRender; } catch (e) { /* 顶层环境异常 · 跳过 */ }

// wish-3fef4bc7 · helpers 接受可选 target container · 不传 = 操作 active session ($msgs)
// 这样 78 处现存调用不动 · send 内的调用传 state.$container 即可路由到正确 session
// 卷四十六续 3 · opts.forceScroll · 默认软滚 (用户 拖滚动条看历史时 LLM 输出不强行刷回底)
//   用户发消息 / 错误 / 必须看到的卡片 → 调方显式传 { forceScroll: true }
function addMsg(role, text, className, ts, target, opts) {
  const div = document.createElement('div');
  div.className = 'msg ' + (className || role);
  const cls = className || role;
  // 卷三十：OPUS 输出走 markdown 渲染（用户 输入 / sys / err / 工具卡保持原样）
  const useMd = cls.includes('opus') && !cls.includes('thinking');
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
  }
  return div;
}
function addSys(text, target) { return addMsg('sys', text, null, null, target); }

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

// 卷三十七 · 流式拼接 · 当前正在 stream 的 DOM 引用
// wish-3fef4bc7 · 改为 per-state · 没有 state 参数 = 不工作 (直接 return)
// state.currentStreamingReasoning / state.currentStreamingAssistant 持有 DOM 引用
function appendReasoningDelta(state, textPiece) {
  if (!textPiece || !state) return;
  if (!state.currentStreamingReasoning) {
    // 新建一个流式 reasoning bubble · 自动展开 · 标 streaming
    const div = document.createElement('div');
    div.className = 'msg opus reasoning streaming';
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
    state.currentStreamingReasoning = { div, body };
  }
  const body = state.currentStreamingReasoning.body;
  body.appendChild(document.createTextNode(textPiece));
  // reasoning-body 自身有 max-height + overflow-y · 必须把它自己也滚到底
  // 否则外层 $msgs 滚到底 · 但 reasoning 窗口内仍卡在原位 用户 看不到新字
  // 卷四十六续 3 · body 跟外层都走软滚 · 用户 拖到上面看历史时不打扰
  if (isNearBottom(body)) {
    requestAnimationFrame(() => { body.scrollTop = body.scrollHeight; });
  }
  scrollToBottom(state.$container, { force: false });
}

function finalizeStreamingReasoning(state) {
  if (!state || !state.currentStreamingReasoning) return;
  state.currentStreamingReasoning.div.classList.remove('streaming');
  // 完成后默认收起 · 减视觉噪音 · 用户 想看再展开
  const body = state.currentStreamingReasoning.body;
  const header = state.currentStreamingReasoning.div.querySelector('.reasoning-header');
  if (body && header) {
    body.hidden = true;
    const toggle = header.querySelector('.reasoning-toggle');
    if (toggle) toggle.textContent = '展开 ▾';
    const label = header.querySelector('.reasoning-label');
    if (label) label.textContent = `思考完成 · ${body.textContent.length} 字`;
  }
  state.currentStreamingReasoning = null;
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
    div.className = 'msg opus streaming';
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
  state.currentStreamingAssistant = null;
  state.streamingAssistantRaw = '';
  state._assistantRerenderScheduled = false;
}

// 卷三十六 · DeepSeek thinking mode · 渲染一条 reasoning 气泡
// 折叠式 · 默认展开 · 用户 可点收起；样式偏淡灰 + 斜体 · 跟正文区分
function renderReasoningBubble(text, options = {}, target) {
  if (!text) return null;
  const div = document.createElement('div');
  div.className = 'msg opus reasoning';
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
  addMsg('bro', text || '（图片）', null, new Date(), state.$container, { forceScroll: true });
  if (_hasImgs) {
    // wish-41ed72ef · 用户 气泡附件渲染：图片缩略图 + 文档卡片
    const _broBubble = state.$container ? state.$container.lastElementChild : null;
    if (_broBubble && _broBubble.classList.contains('bro')) {
      const _attWrap = document.createElement('div');
      _attWrap.className = 'bro-attach-imgs';
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
      _broBubble.appendChild(_attWrap);
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
    setToolProgressText('OPUS 准备工具中…');
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
  state._expectingDaemonRestart = false;

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
      addMsg('opus', '(OPUS 没说话)', null, null, state.$container);
    }
  } catch (e) {
    // 用户 主动 stop = userAbortedSelf · catch 不算错
    // AbortError + !userAbortedSelf 也可能是关页面之类·按"主动取消"对待
    if (e.name === 'AbortError' || userAbortedSelf) {
      // 不算错 · 正常路径 (包括 OPUS 调 request_restart 时 tool_call 主动 abort 的)
    } else if (state._expectingDaemonRestart) {
      // 卷四十六 续 14 补丁 III · 兜底 · 如果 tool_call 那边没主动 abort · 这边接 SSE 断
      // 走同一条恢复路径 · 不弹红框
      waitForDaemonAfterRestartTool(state);
    } else {
      showError('网络/流式出错', e.message || String(e));
    }
  } finally {
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
    } else {
      // 后台跑完 + 用户 不在看 = 标记 unread + toast 提示
      state.hasUnreadCompletion = true;
      if (typeof _showCompletionToast === 'function') {
        try { _showCompletionToast(state); } catch {}
      }
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
      addSys('OPUS 这轮没出最终回复 · 看上面 reasoning · 可能是: 工具回结果但 LLM 没继续 / 触发了 max iter / 网络中断。下条消息可以让他「请继续 / 给个总结」', state.$container);
    }
    if (state.lastFinishReason === 'length' && state.autoResumeCount >= 3) {
      addSys('⚠ OPUS 自动续接 3 次还没写完 · 这次任务输出量太大 · 可以: 1) 编辑当前 LLM 配置把 max_tokens 调更大 · 2) 发"请只给总结·不要全文"让 OPUS 收敛', state.$container);
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
    if (typeof refreshSessionList === 'function') {
      try { refreshSessionList(); } catch {}
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
          const ph = addMsg('opus', 'OPUS 正在想', 'msg opus thinking', null, state.$container);
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
        finalizeStreamingReasoning(state);
        const newPh = addMsg('opus', '继续...', 'msg opus thinking', null, state.$container);
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
        addSys(`⏩ ${note} · OPUS 接着上次断点继续`, state.$container);
        const newPh = addMsg('opus', '继续中...', 'msg opus thinking', null, state.$container);
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
        renderReasoningBubble(data.text || '', {}, state.$container);
        const newPh = addMsg('opus', '继续...', 'msg opus thinking', null, state.$container);
        newPh.dataset.placeholder = '1';
        state.assistantBubbles.push(newPh);
        break;
      }

      case 'assistant_text': {
        state.sawAssistantText = true;
        const ph = state.assistantBubbles[0];
        if (ph && ph.dataset.placeholder) {
          ph.remove();
          state.assistantBubbles.shift();
        }
        if (state.currentStreamingAssistant) {
          finalizeStreamingAssistant(state, data.text || '');
        } else {
          const bubble = addMsg('opus', data.text || '', 'msg opus', new Date(), state.$container);
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
          div.textContent = `⛔ OPUS 已经 nudge ${data.cap || 2} 次还在重复同样的工具调用 · 强制中断 · 签名: ${sig}`;
        } else {
          div.textContent = `⚠ OPUS 在重复同样的工具调用 (${seen} 次) · 已注入"换个思路"提示 · 签名: ${sig}`;
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
        const div = document.createElement('div');
        div.className = 'msg tool-call';
        div.innerHTML = '⚙ <span class="tool-name"></span> ';
        div.querySelector('.tool-name').textContent = data.name || '?';
        const summary = document.createElement('span');
        summary.textContent = data.summary || '';
        div.appendChild(summary);
        if (data.tier) {
          const tier = document.createElement('span');
          tier.style.color = 'var(--dim2)';
          tier.style.marginLeft = '8px';
          tier.style.fontSize = '10px';
          tier.textContent = '[' + data.tier + ']';
          div.appendChild(tier);
        }
        if (state.$container) state.$container.appendChild(div);
        scrollToBottom(state.$container, { force: false });

        // 卷四十六 续 14 补丁 III + V · OPUS 调 request_restart 工具 = daemon ~2 秒后自爆 ·
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
            addSys('⏳ OPUS 调了 request_restart · daemon 马上自爆+重启 · 红框是预期 · 别按重启按钮 · ~5 秒后自动接上', state.$container);
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
        }
        break;
      }

      // sub-agent (run_app) 边界事件 · 用户痛点:
      // 之前 run_app 跑 6-8 轮 sub-agent 内部 LLM · 主对话 ticker 文字一直变 (各种 read_file/write_file)
      // 但没人告诉用户 "这是 sub-agent 在内部跑" · 用户看着混乱 = 怀疑死了 / 跑偏了
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
        const div = document.createElement('div');
        div.className = 'msg tool-result' + (data.ok ? '' : ' failed');
        const icon = data.ok ? '<i class="ri-check-fill"></i>' : '<i class="ri-close-fill"></i>';
        div.innerHTML = icon + ' <span class="tool-name"></span> ';
        div.querySelector('.tool-name').textContent = data.name || '?';
        const tail = document.createElement('span');
        if (data.ok) {
          const preview = (data.preview || '').slice(0, 200);
          tail.textContent = preview ? '· ' + preview.replace(/\n/g, ' ') : '· ok';
        } else {
          tail.textContent = '· ' + (data.error || 'failed');
        }
        div.appendChild(tail);
        if (state.$container) state.$container.appendChild(div);
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
        state.finalSessionId = data.session_id || state.finalSessionId;
        state.finalModel = data.model || state.finalModel;
        if (data.usage) state.finalUsage = data.usage;
        if (!state.sawAssistantText && data.reply) {
          const ph = state.assistantBubbles[0];
          if (ph && ph.dataset.placeholder) {
            ph.remove();
            state.assistantBubbles.shift();
          }
          addMsg('opus', data.reply, null, new Date(), state.$container);
        }
        break;

      case 'error': {
        showError(`[${data.status || 500}]`, data.detail || 'unknown error');
        const ph = state.assistantBubbles[0];
        if (ph && ph.dataset.placeholder) {
          ph.remove();
          state.assistantBubbles.shift();
        }
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
  if (locked) {
    $input.placeholder = 'OPUS 还在跑 · 点 ⏹ 停止才能发新消息';
  } else {
    $input.placeholder = '跟 OPUS 说点什么…  (Shift+回车换行)';
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
  addSys('· 已发停止信号 · 等 OPUS 当前这步跑完就退', s.$container);
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
//   - "<i class="ri-brain-fill"></i> 成长日记" 新维度（cognition）· 读 OWNER-NOTEBOOK
// ──────────────────────────────────────────────────────────────

const $detailPane = document.getElementById('detailPane');
const $dashView = $detailPane;
const $navRail = document.getElementById('navRail');
const $navGroups = document.getElementById('navGroups');

// 维度元信息 · 这是唯一真相 · 改这里就够
// 卷二十九 · 五分组架构（市场咨询面 → 内部决策面 → 产品生产层 → 用户运营层 → 能力扩展层）
const NAV_GROUPS = [
  // 卷三十三补丁 · 用户 让重排：执行落地排到运营后 · 因为它是"已开干 + 自我观察"
  // 这个最贴近 用户 本人的事·应该在外部信息 → 决策 → 生产 → 用户之后·作为收束。
  { id: 'market',    label: '市场信息' },
  { id: 'ability',   label: '能力对照' },
  { id: 'studio',    label: '出品工坊' },
  { id: 'ops',       label: '用户运营' },
  { id: 'execution', label: '执行落地' },  // 已开干 + 成长日记 + 收藏
  { id: 'plugins',   label: '插件库' },
];

const DOMAIN_META = {
  // 市场信息 · 外部信号 · 本工程看世界的眼睛 · 不含 OPUS 自己的观察
  radar:         { icon: '<i class="ri-radar-fill"></i>', label: '信息雷达', section: 'market', stub: false },
  trends:        { icon: '<i class="ri-line-chart-fill"></i>', label: '今日趋势', section: 'market', stub: false },
  reports:       { icon: '<i class="ri-article-fill"></i>', label: '报告库',   section: 'market', stub: false },
  calendar:      { icon: '<i class="ri-calendar-fill"></i>', label: '信息日历', section: 'market', stub: false },
  // 能力对照 · 内部决策 · 市场 × 用户 能力的交叉
  opportunities: { icon: '<i class="ri-diamond-fill"></i>', label: '掘金机会', section: 'ability', stub: false },
  feasibility:   { icon: '<i class="ri-bar-chart-fill"></i>', label: '可行性分析', section: 'ability', stub: false },
  // 出品工坊 · 产品生产
  // 卷四十四 K stage 2a · 4 老维度 (content/design/dev/docs) 收进工坊主页"<i class="ri-archive-fill"></i> 应用"tab
  // 它们的 dashboard 端点 GET /dashboard/<id> 仍然有效 (workshop 内部 fetch 直拉)
  // 但 NAV_GROUPS 没 'apps' 组 · 所以从左导航 hidden · 跟 用户 当前需求一致
  workshop:  { icon: '<i class="ri-magic-fill"></i>', label: '出品工坊', section: 'studio', stub: false },
  content:   { icon: '<i class="ri-film-fill"></i>', label: '内容制作', section: 'apps', stub: false },
  design:    { icon: '<i class="ri-palette-fill"></i>', label: '产品设计', section: 'apps', stub: false },
  dev:       { icon: '<i class="ri-terminal-box-fill"></i>', label: '产品开发', section: 'apps', stub: false },
  docs:      { icon: '<i class="ri-file-text-fill"></i>', label: '文档撰写', section: 'apps', stub: false },
  // 用户运营 · 等先有产品
  service:   { icon: '<i class="ri-team-fill"></i>', label: '用户运营', section: 'ops', stub: true,
               note: '等先有产品再做用户运营' },
  // 执行落地 · 卷三十三 · 闭环反馈独立维度 · 卷三十三补丁 · 成长日记搬这里
  //   因为"OPUS 对 用户 的观察"跟"用户 真正在跑的项目"是同一码事——
  //   都是「自我视角」·跟外部信号（radar/trends/reports）分开
  execution:     { icon: '<i class="ri-refresh-fill"></i>', label: '执行反馈', section: 'execution', stub: false },
  cognition:     { icon: '<i class="ri-brain-fill"></i>', label: '成长日记', section: 'execution', stub: false },
  favorites:     { icon: '<i class="ri-star-fill"></i>', label: '收藏夹',   section: 'execution', stub: false },
  // 卷三十五 · OPUS 自我演化心愿单 · "我想装这个能力"
  // 跟 cognition 同组 · 因为都是「OPUS 自己的视角」
  wishlist:      { icon: '<i class="ri-lightbulb-fill"></i>', label: '心愿单', section: 'execution', stub: false },
  sinks:         { icon: '<i class="ri-archive-drawer-fill"></i>', label: '沉淀位',   section: 'execution', stub: false },
  // 插件库 · 能力扩展 · OPUS 自己用产品开发能写新插件回填这里
  plugins:   { icon: '<i class="ri-puzzle-fill"></i>', label: '插件库', section: 'plugins', stub: false },
};

// 雷达 / 机会的领域元信息（与 workers/info_radar.DOMAIN_META 保持对齐）
// 只内置 self-evolve·其余领域都是用户在相遇 / 对话里挖出来后动态新建的·
// 渲染时未命中这里就走 `|| {fallback}`（用服务端返回的 label/icon/color）。
const RADAR_DOMAINS_META = {
  // self-evolve · 看 GitHub 同类工程的镜子（唯一内置）
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
const NAV_COLLAPSED_KEY = 'opus_nav_collapsed_v1';
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
  if (localStorage.getItem(NAV_COLLAPSED_KEY) !== '1') return;
  document.addEventListener('DOMContentLoaded', () => toggleNavCollapse(true), { once: true });
  if (document.readyState !== 'loading') toggleNavCollapse(true);
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

function renderConfirmCard(data, state) {
  if (!state || !state.$container) return null;
  if (!data || !data.tool_call_id) return null;

  // 对话流内联 · 用户钉死: 不要弹窗/全屏遮罩 (遮罩在 daemon 重启 / turn 中断时收不到 confirm_resolved → 残留 fixed 层锁死整页) · 卡片直接进消息流
  const wrap = document.createElement('div');
  wrap.className = 'msg confirm-card';
  wrap.dataset.toolCallId = data.tool_call_id;
  wrap.dataset.turnId = data.turn_id || '';

  // 标题: ⚠ OPUS 申请执行 <tool>
  const head = _confirmEl('div', 'confirm-head',
    '<span class="confirm-icon">⚠</span> <strong>OPUS 申请执行 <code class="confirm-tool"></code></strong>'
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
  riskLabel.innerHTML = risk ? '<i class="ri-clipboard-fill"></i> 风险 (OPUS 说明)' : '<i class="ri-clipboard-fill"></i> 风险 — OPUS 未说明 ⚠';
  const riskBody = _confirmEl('div', 'confirm-block-body');
  riskBody.textContent = risk || 'OPUS 没填 risk_explanation 字段 · 你不知道这刀下去会影响什么 · 谨慎批准';
  riskBlock.appendChild(riskLabel);
  riskBlock.appendChild(riskBody);
  wrap.appendChild(riskBlock);

  // 规避策略 (用户 12:05 反馈钉死必须有这块)
  const mit = (data.mitigation || '').trim();
  const mitBlock = _confirmEl('div', mit ? 'confirm-block confirm-mit' : 'confirm-block confirm-mit confirm-block-empty');
  const mitLabel = _confirmEl('div', 'confirm-block-label');
  mitLabel.innerHTML = mit ? '<i class="ri-shield-fill"></i> 规避策略 (OPUS 说明)' : '<i class="ri-shield-fill"></i> 规避策略 — OPUS 未说明 ⚠';
  const mitBody = _confirmEl('div', 'confirm-block-body');
  mitBody.textContent = mit || 'OPUS 没填 mitigation 字段 · 出问题时它没想好怎么收场 · 谨慎批准';
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
  denyLabel.textContent = '拒绝原因 (可选 · 告诉 OPUS 为什么·让它换思路):';
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
  status.textContent = '等待决议 · 30min 后自动拒绝';
  wrap.appendChild(status);

  // 直接进消息流末尾 · 无遮罩 (不会锁死页面) · 滚到视野确保看得到
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

  // 关闭中央模态 + 移除遮罩 + 把 inline 占位转成"已决议"记录条
  if (card.classList.contains('confirm-modal')) {
    if (card._backdrop && card._backdrop.parentNode) {
      card._backdrop.classList.remove('confirm-modal-backdrop-show');
      // 等遮罩淡出再 remove DOM
      setTimeout(() => { if (card._backdrop && card._backdrop.parentNode) card._backdrop.remove(); }, 200);
    }
    card.classList.remove('confirm-modal-show');
    // 模态本体延迟 remove · 让淡出动画跑完 · 同时把"已决议摘要"渲染到 inline 占位上
    setTimeout(() => { if (card.parentNode === document.body) card.remove(); }, 200);
    // 把渲染目标切到占位行 (用户滚消息流时这里留痕)
    if (card._placeholder) {
      const ph = card._placeholder;
      ph.innerHTML = '';  // 清空 "等待 + 重新打开" 内容
      ph.classList.add('confirm-placeholder-resolved');
      card.__renderInto = ph;
    }
  }

  const labelMap = {
    approve_once: '<i class="ri-check-fill"></i> 批准 (只这次)',
    trust_30min: '⏰ 批准 + 信任 30min',
    trust_24h: '<i class="ri-calendar-fill"></i> 批准 + 信任 24h',
    trust_permanent: '♾ 永久信任 ⚠',
    deny: '<i class="ri-close-fill"></i> 拒绝',
  };
  let label = labelMap[decision] || decision;
  if (autoTimeout) label = '⏱ 超时 auto-deny (30min 未响应)';

  const toolName = (card.querySelector('.confirm-tool') || {}).textContent || '';
  // 模态版本: 渲染目标改成 inline 占位 (不再渲染到将要 remove 的 modal card)
  const renderHost = card.__renderInto || card;
  if (renderHost !== card) {
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
  const STORE_NAV = 'opus_ui_nav_w';
  const STORE_CHAT = 'opus_ui_chat_w';
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
// 卷四十六 续 14 补丁 III + V · 2026-05-26 · OPUS 调 request_restart 后 daemon 自爆 ·
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
        setToolProgressText('OPUS 重启完成 · 正在续写之前的任务…');
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
          addSys('⚠ OPUS 续写这一轮中途出错了 (resume turn failed) · 看 data/daemon.err · 直接重发消息可以继续', state.$container);
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
  //   原来 confirm 只能 yes/no · 重启完只 inject system notice · OPUS 不会自动续场
  //   现在 opusPrompt 让 用户 一并填"重启完想让我做啥" · 串到 /restart-daemon body
  //   留空 = 跟老逻辑一样 · 只重启 · 不跑 background turn
  const followUp = await opusPrompt({
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
    addSys(`<i class="ri-refresh-fill"></i> 正在重启 daemon · 请等 ~5 秒 · 起来后 OPUS 会自动跑:「${preview}」`);
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
      addSys('<i class="ri-checkbox-circle-fill"></i> daemon 已重启 · 新代码已装载 · OPUS 在后台跑你交代的事 · 跑完会落档到当前 session · 翻一下消息列表就能看到结果');
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
  const ok = await opusConfirm({
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
  addSys('🌙 正在关闭 daemon · 之后没有 OPUS 在跑了');
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
// OPUS 改崩了 daemon · 用户 一键 git reset --hard <prev_commit> + 重启
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

  const idxStr = await opusPrompt({
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
  const followUp = await opusPrompt({
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
    addSys(`<i class="ri-rewind-fill"></i> 回档到 ${target.short} 中 · daemon 即将重启 · 起来后 OPUS 会自动跑:「${preview}」`);
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
      addSys(`<i class="ri-checkbox-circle-fill"></i> 已回档到 ${target.short} · daemon 已重启${stashHint}\n<i class="ri-robot-fill"></i> OPUS 在后台跑你交代的事 · 跑完落档到当前 session · 翻消息列表能看到`);
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
            onclick="switchModel('${escHtml(opt.alias)}')"
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
      await opusAlert({ title: '切换模型失败', message: t.slice(0, 400) || '服务端没返详情', icon: '<i class="ri-error-warning-fill"></i>' });
      return;
    }
    const data = await r.json();
    _modelMenuOpen = false;
    document.getElementById('modelMenu').classList.remove('open');
    document.getElementById('modelNameLabel').textContent = alias;
    const tip = document.createElement('div');
    tip.className = 'model-switch-tip';
    tip.textContent = `模型已切到 ${alias} · ${data.note || '下一轮生效'}`;
    document.body.appendChild(tip);
    setTimeout(() => tip.remove(), 2800);
    setTimeout(loadCurrentModel, 600);
  } catch (e) {
    await opusAlert({ title: '网络出错', message: e.message, icon: '<i class="ri-error-warning-fill"></i>' });
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
  if (window.OPUS_WORKSHOP_VIEW && window.OPUS_WORKSHOP_VIEW.isMounted()) {
    window.OPUS_WORKSHOP_VIEW.unmount();
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
    <div class="bi-loading bi-init">
      <div class="bi-init-spin"><i class="ri-loader-4-line"></i></div>
      <div class="bi-init-title">工作台初始化中…</div>
      <div class="bi-init-sub">第一次启动要去各个信源抓一圈、热一下数据，通常 <b>1~2 分钟</b>（之后就秒开了）。<br>不用干等——<b>现在就能在右边直接跟我说话</b>，看板会自己填上。</div>
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
        <h2><i class="ri-dashboard-fill" style="color:var(--opus)"></i> 工作室 BI 看板</h2>
        <span class="bi-head-meta">
          ${data.generated_at || ''} ·
          <button class="bi-link" onclick="renderDetailWelcome()" title="刷新"><i class="ri-refresh-fill"></i> 刷新</button>
        </span>
      </div>

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
            <h3><i class="ri-fire-fill" style="color:var(--opus)"></i> 价值热力</h3>
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
            <h3><i class="ri-radar-fill" style="color:var(--opus)"></i> 信号流</h3>
            <span class="bi-sig-head-r">
              <button class="bi-sig-today" id="biSigToday" onclick="biSigToggleToday()" title="只看今天抓到/发布的信号"><i class="ri-calendar-event-line"></i> 今日</button>
              <span class="badge" id="biSigCount">…</span>
            </span>
          </div>
          <div class="bi-heat-domains" id="biSigDomains"></div>
          <div id="biSignalList"><div class="bi-v3-empty">加载中…</div></div>
        </div>
      </div>

      <!-- 趋势研判 (卷五十六 P2) · 跟热力图同月同领域 · OPUS 用 LLM 给可行性 + 执行方案 -->
      <div class="bi-card bi-brief-card">
        <div class="bi-card-head">
          <h3><i class="ri-lightbulb-flash-fill" style="color:#F6AD55"></i> 趋势研判 <span class="bi-brief-scope" id="biBriefScope"></span></h3>
          <button class="bi-brief-gen" id="biBriefGenBtn" onclick="biBriefGenerate()"><i class="ri-sparkling-2-line"></i> 研判本月趋势</button>
        </div>
        <div class="bi-brief-body" id="biBriefBody"><div class="bi-v3-empty">跟着热力图的月份 / 领域 · 点右上让 OPUS 看一遍这段时间的信号·给趋势可行性 + 下一步动作</div></div>
      </div>

      <!-- 认知行 (卷五十八续 VIII)：OPUS 眼里的你 (能力镜像·填孤岛) + 闭环温度计 -->
      <div class="bi-grid-2">
        <div class="bi-card bi-mirror-card">
          <div class="bi-card-head">
            <h3><i class="ri-aspect-ratio-fill" style="color:#9f7aea"></i> OPUS 眼里的你 <span class="bi-mirror-time" id="biMirrorTime"></span></h3>
            <button class="bi-brief-gen" id="biMirrorBtn" type="button"><i class="ri-camera-lens-fill"></i> 立即照镜</button>
          </div>
          <div class="bi-mirror-body" id="biMirrorBody"><div class="bi-v3-empty">加载中…</div></div>
        </div>
        <div class="bi-card">
          <div class="bi-card-head"><h3><i class="ri-temp-hot-fill" style="color:#F6AD55"></i> 闭环温度计 <span class="badge" id="biClosureRate">…</span></h3></div>
          <div id="biClosureBody"><div class="bi-v3-empty">加载中…</div></div>
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

      <!-- 元行 (卷五十八续 VIII)：运行状态 + 节律时间线 -->
      <div class="bi-grid-2">
        <div class="bi-card">
          <div class="bi-card-head"><h3><i class="ri-pulse-fill" style="color:#4FD1C5"></i> 运行状态</h3></div>
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
    { id:'radar',   icon:'ri-radar-fill',     color:'var(--opus)',  label:'雷达信号' },
    { id:'trends',  icon:'ri-line-chart-fill', color:'#4FD1C5',     label:'今日趋势' },
    { id:'reports', icon:'ri-article-fill',    color:'#63B3ED',     label:'报告产出' },
    { id:'wishlist',icon:'ri-lightbulb-fill',  color:'#F6AD55',     label:'心愿单' },
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
    oppList.innerHTML = '<div class="bi-v3-empty">暂无掘金机会 · 跟 OPUS 说「巡一圈」</div>';
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
    loadBIMirror();   // A·OPUS 眼里的你
    loadBIClosure();  // B·闭环温度计
    loadBISelf();     // C·运行状态
  } catch (e) {
    console.error('BI V3 async load error:', e);
  }
}

// ═══════════════════════════════════════════
//  卷五十八续 VIII · A/B/C 卡加载器 (D 节律时间线在 biHeatRender 里填)
// ═══════════════════════════════════════════
// A·OPUS 眼里的你 · 市场能力镜像快照 (填"照完即孤岛"的洞)
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

// B·闭环温度计 · 哪些 OPUS 输出还在等 用户 反应
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

// C·运行状态 · token / 会话 / 在线 (拉现有端点·不加后端)
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
    cells.push({ icon: 'ri-chat-3-fill', color: 'var(--opus)', val: cnt, lbl: '会话数' });
  }
  if (life && life.started_at) {
    cells.push({ icon: 'ri-time-fill', color: '#63B3ED', val: _biUptime(life.started_at), lbl: '已在线' });
  }
  if (!cells.length) { body.innerHTML = '<div class="bi-v3-empty">拿不到运行数据</div>'; return; }
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
      const style = on ? `style="--dc:${d.color || 'var(--opus)'}"` : '';
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
    html += `<div class="bi-tip-hint">点这天让 OPUS 起草本期复盘</div>`;
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
  const ok = await opusConfirm({
    title: '研判这段时间的趋势',
    message: {
      html: `让 OPUS 看一遍 <b>${mm}${vd && vd !== 'all' ? ' · ' + escHtml(vd) : ''}</b> 的高价值信号·
        给出趋势研判 + 执行方案。<span class="om-hint">会调一次 LLM (约 $0.05 · 10-30 秒)·结果会缓存·重看不重烧。</span>`
    },
    okText: '研判', cancelText: '再想想',
  });
  if (!ok) return;
  if (btn) { btn.disabled = true; btn.innerHTML = '<i class="ri-loader-4-line spin"></i> OPUS 研判中…'; }
  if (body) body.innerHTML = '<div class="bi-v3-empty">OPUS 正在看这段时间的信号·研判趋势 + 想执行方案…</div>';
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
  pool.forEach(r => { const d = r.domain || 'self-evolve'; counts[d] = (counts[d] || 0) + 1; });
  const total = pool.length + _biSig.trends.length;
  let html = `<button class="bi-heat-dom${_biSig.domain === 'all' ? ' active' : ''}" onclick="biSigSetDomain('all')"><i class="ri-stack-line"></i> 全部 <i>${total}</i></button>`;
  // 领域按数量从多到少排
  Object.keys(counts).sort((a, b) => counts[b] - counts[a]).forEach(id => {
    const m = RADAR_DOMAINS_META[id] || { icon: '', label: id, color: 'var(--opus)' };
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
    .filter(r => _biSig.domain === 'all' || (r.domain || 'self-evolve') === _biSig.domain)
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
    radar:'var(--opus)', trends:'#4FD1C5', reports:'#63B3ED',
    content:'#48BB78', dev:'#F6AD55', docs:'#4FD1C5',
    cognition:'var(--opus)', opportunities:'#F6AD55',
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
    const click = isHot ? `onclick="switchView('${escHtml(it.domain)}')"` : '';
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

// 卷三十四 · OPUS 自主巡航 banner · 一键跑 radar→trends→opps
function renderAutopilotBanner() {
  return `
    <div class="bi-autopilot">
      <div class="bi-autopilot-left">
        <div class="bi-autopilot-icon">🛰️</div>
        <div class="bi-autopilot-text">
          <div class="bi-autopilot-title">OPUS 自主巡航</div>
          <div class="bi-autopilot-sub">一键跑完 信息雷达 → 今日趋势 → 掘金机会 (约 60-180s)</div>
        </div>
      </div>
      <button class="bi-autopilot-btn"
              onclick="spawnQuickly('OPUS 你自主巡航一遍·从信息雷达跑到掘金机会·把整个链路跑完·跑完跟我说看到了什么·给我推荐 1-2 个最值得动手的机会', '自主巡航')">
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
        <span title="适配度">${fitIcon} ${o.fit || '?'}</span>
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

async function loadDashboard(domain, opts = {}) {
  // 卷五十七 · 2026-06-06 · settings 是伪视图 (进 $detailPane · renderSettingsView 渲染 · 不走 /dashboard/{domain})。
  //   对话里跑工具后的静默刷新 (scheduleDashboardRefresh / stream finally) 会拿 currentView='settings' 调进来
  //   → fetch /dashboard/settings → 后端没这个域 → 404 → 把 用户 正看的设置页冲成"加载失败 [404]"。 这里直接短路。
  if (!domain || domain === 'settings') return;
  // 卷四十四 K · 切到非 workshop 前·先 unmount 工坊 (释放 ResizeObserver / events)
  if (domain !== 'workshop' && window.OPUS_WORKSHOP_VIEW && window.OPUS_WORKSHOP_VIEW.isMounted()) {
    window.OPUS_WORKSHOP_VIEW.unmount();
    $detailPane.classList.remove('workshop-active');
  }
  // 卷四十四 K · workshop 维度走特殊路径 · 不调 API · 直接 mount LiteGraph view
  if (domain === 'workshop') {
    if (!window.OPUS_WORKSHOP_VIEW) {
      $dashView.innerHTML = `<div class="dash-empty">⚠ workshop.js 没加载 · 检查 static/workshop.js</div>`;
      return;
    }
    $detailPane.classList.add('workshop-active');
    window.OPUS_WORKSHOP_VIEW.mount($detailPane);
    return;
  }
  if (!token) {
    $dashView.innerHTML = `
      <div class="dash-head"><h2>需要 token</h2></div>
      <div class="dash-empty">点右上角 ⚙ 填 token 后再试</div>`;
    return;
  }
  if (!opts.silent) {
    $dashView.innerHTML = `<div class="dash-empty">加载中…</div>`;
  }
  // wish-149eab3f phase B · 沉淀位走 /sinks 端点 · 不是 /dashboard/sinks
  if (domain === 'sinks') {
    try {
      const r = await fetch('/sinks', { headers: { 'Authorization': 'Bearer ' + token } });
      if (!r.ok) { $dashView.innerHTML = `<div class="dash-empty">加载失败 [${r.status}]</div>`; return; }
      const data = await r.json();
      renderSinks(data);
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
    else if (domain === 'cognition') renderCognition(data);
    else if (domain === 'feasibility') renderFeasibility(data);
    else if (domain === 'execution') renderExecution(data);
    else if (domain === 'favorites') renderFavorites(data);
    else if (domain === 'calendar') renderCalendar(data);
    else if (domain === 'plugins') renderPlugins(data);
    else if (domain === 'wishlist') renderWishlist(data);
    else if (['content', 'design', 'dev', 'docs'].includes(domain)) renderWorkshop(domain, data);
    else renderDashboardStub(domain, data);
  } catch (e) {
    $dashView.innerHTML = `<div class="dash-empty">网络出错: ${e.message}</div>`;
  }
}

// ── 卷二十六 · <i class="ri-brain-fill"></i> 成长日记 + 我的画像 + 开放问题 ──
function renderCognition(data) {
  if (data && data.error) {
    $dashView.innerHTML = `
      <div class="dash-head"><h2><i class="ri-brain-fill"></i> 成长日记</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }
  const bro = data.bro_profile || {};
  const diary = data.opus_diary || {};
  const openQs = data.open_questions || [];

  let html = `
    <div class="dash-head">
      <h2><i class="ri-brain-fill"></i> 成长日记 · 我的画像</h2>
      <span class="meta">${diary.total || (diary.entries || []).length} 条日记 · ${(bro.sections || []).length} 节画像</span>
      <button onclick="backToChat()">✕ 收起</button>
      <button onclick="loadDashboard('cognition')">刷新</button>
    </div>`;

  // 卷四十四 F · wish-bcce1139 · 把 entries 按 type 拆开
  // iron_rule entries 单独成"工艺铁律"区块·放最顶 (比开放问题还高)
  // 其余 entries 仍走原"成长日记"区块
  const allEntries = diary.entries || [];
  const ironRules = allEntries.filter(e => (e.type || 'reflection') === 'iron_rule');
  const regularEntries = allEntries.filter(e => (e.type || 'reflection') !== 'iron_rule');

  // 工艺铁律区块 (橙红 · OPUS 给自己立的纪律 · 公开承诺)
  if (ironRules.length > 0) {
    html += `
      <div class="cognition-block cognition-ironrule">
        <div class="cog-head"><i class="ri-flash-fill"></i> OPUS 的工艺铁律 · ${ironRules.length} 条
          <span class="cog-source">OPUS 用失败换来的纪律 · 公开承诺</span>
        </div>
        <div class="cog-body">`;
    for (const e of ironRules) {
      const body = e.body || '';
      const bodyExcerpt = body.length > 400 ? body.slice(0, 400) + '…' : body;
      html += `
        <details class="cog-entry cog-entry-ironrule">
          <summary>
            <span class="cog-e-date">${escHtml(e.date || '')}</span>
            <span class="cog-e-title">${escHtml(e.title || '')}</span>
          </summary>
          <div class="cog-e-body">${escHtml(bodyExcerpt)}</div>
        </details>`;
    }
    html += `</div></div>`;
  }

  // 开放问题（OPUS 当下关注的方向）
  if (openQs.length > 0) {
    html += `
      <div class="cognition-block cognition-open">
        <div class="cog-head">🚨 OPUS 当下关注 (${openQs.length} 条)</div>
        <div class="cog-body">`;
    for (const q of openQs) {
      html += `
        <div class="cog-question">
          <div class="cog-q-section">[${escHtml(q.section || '')}]</div>
          <div class="cog-q-text">${escHtml(q.text || '')}</div>
        </div>`;
    }
    html += `</div></div>`;
  }

  // 成长日记 (普通 reflection / learning / idea / mood entries)
  html += `
    <div class="cognition-block cognition-diary">
      <div class="cog-head">📖 成长日记 · 最近 ${regularEntries.length} 条
        <span class="cog-source">data/cognition/opus-diary.md</span>
      </div>
      <div class="cog-body">`;
  if (regularEntries.length === 0) {
    html += `<div class="dash-empty">${escHtml(diary.note || '还没写过 · 跟 OPUS 说「记一笔今天的观察」')}</div>`;
  } else {
    for (const e of regularEntries) {
      const body = e.body || '';
      const bodyExcerpt = body.length > 400 ? body.slice(0, 400) + '…' : body;
      html += `
        <details class="cog-entry">
          <summary>
            <span class="cog-e-date">${escHtml(e.date || '')}</span>
            <span class="cog-e-title">${escHtml(e.title || '')}</span>
          </summary>
          <div class="cog-e-body">${escHtml(bodyExcerpt)}</div>
        </details>`;
    }
  }
  html += `</div></div>`;

  // 我的画像 sections
  html += `
    <div class="cognition-block cognition-profile">
      <div class="cog-head">👤 我的画像 · ${(bro.sections || []).length} 节
        <span class="cog-source">soul/OWNER-NOTEBOOK.md</span>
      </div>
      <div class="cog-body">`;
  if (!bro.exists) {
    html += `<div class="dash-empty">${escHtml(bro.note || '画像还没同步进来 · 跑 sync-soul.ps1')}</div>`;
  } else {
    for (const sec of bro.sections || []) {
      html += `
        <details class="cog-section">
          <summary>${escHtml(sec.heading || '')}</summary>
          <div class="cog-s-body">${escHtml(sec.body_excerpt || '')}</div>
        </details>`;
    }
  }
  html += `</div></div>`;

  $dashView.innerHTML = html;
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
        <div>${escHtml(data.empty_hint || '跟 OPUS 说「做一份 X」· OPUS 会调 draft_studio 工具落 markdown。')}</div>
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
            <button class="wk-btn wk-preview" data-domain="${escHtml(domain)}" data-name="${escHtml(it.name || '')}" title="在 webui 中预览 markdown">📖 预览</button>
            <button class="wk-btn wk-reveal" data-domain="${escHtml(domain)}" data-name="${escHtml(it.name || '')}" title="本机用默认应用打开 (Typora / VSCode / 记事本)">📂 外部打开</button>
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
      <button onclick="loadDashboard('${escHtml(domain)}')">← 返回 ${escHtml(m.label || domain)}</button>
      <button onclick="revealWorkshopFile('${escHtml(domain)}', '${escHtml(name)}')" title="本机用默认应用打开">📂 外部打开</button>
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
        想加快这一维度？回对话跟 OPUS 说：「优先做 ${m.label || domain} 维度」
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
      在机会卡上点 <b>💰估算成本</b> · 或跟 OPUS 说「分析第 N 个机会的可行性」。
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
      <div class="feas-card" onclick="loadFeasibilityDetail('${escHtml(it.opp_id)}')">
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
          <button class="feas-act" onclick="event.stopPropagation();loadFeasibilityDetail('${escHtml(it.opp_id)}')">
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
      <button onclick="loadFeasibilityDetail('${escHtml(d.opp_id)}')">刷新</button>
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
  // 放在最前面——用户 先看到"这次分析基于什么"·再读 OPUS 的判断
  const sources = d.sources || {};
  const radarItems = sources.radar_items || [];
  const reportItems = sources.reports || [];
  const hasSources = radarItems.length > 0 || reportItems.length > 0;
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
    html += `</div>`;
  } else if (sources.collected_at !== undefined) {
    // 收集了 sources 但什么都没找到——明确告诉 用户·别藏
    html += `<div class="feas-block feas-sources feas-sources-empty">
      <h3>📚 信源</h3>
      <div class="feas-sources-empty-msg">
        <strong>没找到相关雷达条目 / 报告</strong> · 这次分析信源不足。<br>
        建议：先让 OPUS 跑一份相关报告 · 或扩大雷达源 · 再重新分析。
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
      html += `<div class="feas-res feas-res-have"><b><i class="ri-checkbox-circle-fill"></i> 已有：</b><ul>`;
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
      const mark = { yes: '<i class="ri-checkbox-circle-fill"></i>', partial: '<i class="ri-circle-fill" style="color:#eab308"></i>', no: '<i class="ri-close-circle-fill"></i>' }[c.bro_has] || '?';
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
      你在这里更新的所有信息·都会被下次 OPUS 跑掘金 / 可行性时读到——
      让 OPUS 越用越懂你 · 不再推已经拒过的机会。
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
                onclick="submitOutcomeStatus('${escHtml(d.opp_id)}', '${b.v}')">
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
              onclick="submitOutcomeFull('${escHtml(d.opp_id)}')">
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
    hint.textContent = ok ? '<i class="ri-check-fill"></i> 已保存 · 下次 OPUS 跑掘金/可行性会读到' : '<i class="ri-close-fill"></i> 保存失败';
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
      await opusAlert({ title: '保存失败', message: '执行反馈没存上 · 看浏览器控制台', icon: '<i class="ri-error-warning-fill"></i>' });
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
      const ok = await opusConfirm({
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
      ? `<span class="cal-session-mark" title="当天跟 OPUS 对话 ${d.sessions} 条 · 不计入信息总数">💬${d.sessions}</span>`
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

  // 卷五十八续 VII · 节律条 (周期仪式到期 + 一键起草 · 走 NLP 让 OPUS 调工具)
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
      return '';
    }).join('');
    ritualStrip = `
      <div class="cal-rituals">
        <div class="cal-rituals-title"><i class="ri-time-fill"></i> 节律 · 周期仪式 (点按钮让 OPUS 起草)</div>
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
  // 卷五十八续 VII · 节律按钮 · 派发新会话 (spawnTask · 重操作不污染当前对话) → OPUS 跑 monthly_review / mirror_capability
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
      ${d.sessions_count ? `<span class="cal-stat cal-stat-session" title="当天跟 OPUS 对话条数 · 不计入「共 N 件事」"><span class="cal-stat-icon"><i class="ri-chat-3-fill"></i></span>对话 <b>${d.sessions_count}</b></span>` : ''}
    </div>`;

  // 雷达 · 每条带跳原文
  html += `<section class="day-section">
    <h3><i class="ri-radar-fill"></i> 信息雷达 · ${radar.count} 条</h3>`;
  if (radar.count === 0) {
    html += `<div class="muted">这一天没抓到雷达条目</div>`;
  } else {
    html += `<div class="day-radar-list">`;
    for (const it of radar.items) {
      const dom = it.domain || 'self-evolve';
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
// 卷三十五 · <i class="ri-lightbulb-fill"></i> 心愿单
// "OPUS 自己想装的能力"——从 self-evolve 域看到好东西时·OPUS 自己写心愿·批准 / 推给 DAEMON 或 Cursor 装
// ─────────────────────────────────────────────────────────
// 卷五十三 · 四态精简 (用户: 复杂冗长·一并优化掉)
const _WISH_STATUS_META = {
  pending:  { icon: '<i class="ri-lightbulb-line"></i>', label: '待定 · 等批',    color: '#9f7aea' },
  active:   { icon: '<i class="ri-hammer-fill"></i>',    label: 'OPUS 进行中',   color: '#4fd1c5' },
  review:   { icon: '<i class="ri-search-eye-line"></i>', label: '等待验收',  color: '#ed8936' },
  live:     { icon: '<i class="ri-rocket-2-fill"></i>',  label: '已上线',         color: '#38a169' },
  rejected: { icon: '<i class="ri-close-circle-fill"></i>', label: '已弃',        color: '#a0aec0' },
};
const _WISH_PATH_META = {
  daemon: { icon: '<i class="ri-robot-fill"></i>', label: 'DAEMON 自装' },
  cursor: { icon: '<i class="ri-focus-3-fill"></i>', label: 'Cursor 路径' },
  undecided: { icon: '·', label: '未决定' },
};
let _wishStatusFilter = '';  // '' = 全部
let _wishPage = 1;               // 分页 · 当前页
let _wishPageSize = 10;          // 分页 · 每页条数
let _wishAllData = null;         // 分页 · 上次 API 返回的全量数据

function renderWishlist(data) {
  if (data && data.error) {
    $dashView.innerHTML = `
      <div class="dash-head"><h2><i class="ri-lightbulb-fill"></i> 心愿单</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }
  const wishes = (data && data.wishes) || [];
  const summary = (data && data.summary) || {};

  // 状态过滤器 (卷五十三 · 四态)
  const statusChips = ['', 'pending', 'active', 'review', 'live', 'rejected'].map(st => {
    const isActive = _wishStatusFilter === st;
    const m = _WISH_STATUS_META[st];
    const lbl = st ? `${m.icon} ${m.label}` : '<i class="ri-global-fill"></i> 全部';
    const n = st ? (summary.by_status?.[st] || 0) : (summary.total || 0);
    return `<button class="rdc ${isActive ? 'active' : ''}"
              onclick="setWishStatusFilter('${st}')"
              ${isActive && st ? `style="border-color:${m.color};color:${m.color}"` : ''}>
              ${lbl} <span class="rdc-n">${n}</span>
            </button>`;
  }).join('');

  // 顶部 banner · 引导 OPUS 自己写心愿
  const inspireHtml = `
    <div class="wish-banner">
      <div class="wish-banner-icon"><i class="ri-lightbulb-fill"></i></div>
      <div class="wish-banner-body">
        <div class="wish-banner-title">这是 OPUS 自己的心愿单</div>
        <div class="wish-banner-sub">
          OPUS 在 self-evolve 域看到好东西·或做对照分析时·会写一份「我想装这个」放这里。
          批准 → OPUS 先勘察出方案 → 用户 review 后让 daemon 真改代码。
          <span style="opacity:0.6">勘察阶段不改任何代码·用户 全程有 review 权。需要 Cursor 介入时直接对 OPUS 说「用 cursor 改这个」即可。</span>
        </div>
      </div>
      <button class="wish-banner-btn" onclick="askOpusForWish()">让 OPUS 想想还要装啥</button>
    </div>`;

  // 卷五十三 · git 测谎仪横幅 · 只报"谎报上线" (status=live 但代码没合进 master)。
  // 这是真·暗账·治本今早 用户 的痛点 (修好 B 发现 A 变回去)。 active/review 阶段代码在分支上是正常的·不报警。
  const lieWishes = wishes.filter(w => w.git_lie);
  const debtBannerHtml = lieWishes.length ? `
    <div class="wish-debt-banner">
      <div class="wish-debt-head">
        <i class="ri-error-warning-fill"></i>
        <b>🔴 测谎仪: ${lieWishes.length} 个 wish 标了"已上线"·但代码没真合进主干 (master)</b>
      </div>
      <div class="wish-debt-sub">它们的活儿还躺在各自的 git 分支上·<b>没真正上线</b>·一旦 daemon 切分支/回退就"看起来消失"。点对应卡片里的 <b>「修复·重新合并主干」</b> 让它真合进去。</div>
      <ul class="wish-debt-list">
        ${lieWishes.map(w => `<li><span class="wish-debt-tag">${w.git_unmerged_commits || '?'} commit 没合</span> ${escHtml(w.title)} <span class="wish-debt-id">${escHtml(w.id)}</span></li>`).join('')}
      </ul>
    </div>` : '';

  // 没有心愿时的引导
  if (wishes.length === 0 && !_wishStatusFilter) {
    $dashView.innerHTML = `
      <div class="dash-head">
        <h2><i class="ri-lightbulb-fill"></i> 心愿单</h2>
        <div class="dash-head-sub">${summary.total || 0} 条 · OPUS 想装的能力</div>
      </div>
      ${inspireHtml}
      <div class="dash-empty" style="padding:32px 16px">
        OPUS 还没写过心愿 · 让它去 <a href="javascript:loadDashboard('radar')">信息雷达 · 自我演化</a> 看看同类工程
      </div>`;
    return;
  }

  // 列表
  const cardsHtml = wishes.map((w, idx) => renderWishCard(w, idx)).join('');

  $dashView.innerHTML = `
    <div class="dash-head">
      <h2><i class="ri-lightbulb-fill"></i> 心愿单</h2>
      <div class="dash-head-sub">${summary.total || 0} 条 · ${(summary.pending || 0) + (summary.active || 0) + (summary.review || 0)} 在办 · ${summary.live || 0} 已上线</div>
    </div>
    ${debtBannerHtml}
    ${inspireHtml}
    <div class="wish-status-chips">${statusChips}</div>
    ${wishes.length > 3 ? renderListFilter({targetSelector: '.wish-card', placeholder: '搜心愿标题 / 动机 / 反思...'}) : ''}
    <div class="wish-list">${cardsHtml || '<div class="dash-empty">这个状态下没有心愿</div>'}</div>
    ${(data && data.has_more) ? renderWishLoadMore(data.total, data.page, data.page_size) : ''}
`;
  if (wishes.length > 3) _applyListFilter($dashView.querySelector('.list-filter-input'));
}

function renderWishLoadMore(total, page, pageSize) {
  const shown = page * pageSize;
  const remaining = total - shown;
  if (remaining <= 0) return '';
  const nextLabel = remaining <= pageSize ? '再看最后 ' + remaining + ' 条' : '加载更多 (已显示 ' + shown + '/' + total + ' · 还有 ' + remaining + ' 条)';
  return '<div class="wish-load-more"><button class="wb" onclick="loadMoreWishes()"><i class="ri-arrow-down-double-fill"></i> ' + nextLabel + '</button></div>';
}

// ── wish-149eab3f phase B · 沉淀位面板 ────────────────────────
const SINK_LAYER_META = {
  memory:  { icon: '<i class="ri-database-2-fill"></i>',  label: '记忆库', color: '#8affd6' },
  soul:    { icon: '<i class="ri-heart-pulse-fill"></i>', label: '灵魂层', color: '#ff8acc' },
  meta:    { icon: '<i class="ri-compass-3-fill"></i>',   label: '元文档', color: '#8acbff' },
  route:   { icon: '<i class="ri-signpost-fill"></i>',    label: '路线图', color: '#ffd28a' },
  docs:    { icon: '<i class="ri-file-text-fill"></i>',   label: '说明文档', color: '#bdffba' },
  history: { icon: '<i class="ri-history-fill"></i>',     label: '工程史', color: '#d6b8ff' },
  entry:   { icon: '<i class="ri-door-open-fill"></i>',   label: '入口', color: '#ffe28a' },
};

function renderSinks(data) {
  if (data.error) {
    $dashView.innerHTML = `<div class="dash-head"><h2><i class="ri-archive-drawer-fill"></i> 沉淀位</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }
  const items = data.items || [];
  const layers = data.layers || [];
  const grouped = {};
  for (const it of items) { const l = it.layer || 'docs'; if (!grouped[l]) grouped[l] = []; grouped[l].push(it); }

  let sectionsHtml = '';
  for (const layer of layers) {
    const layerItems = grouped[layer] || [];
    if (!layerItems.length) continue;
    const lm = SINK_LAYER_META[layer] || SINK_LAYER_META.docs;
    sectionsHtml += `
      <details class="sink-layer" open>
        <summary style="border-left:3px solid ${lm.color}; padding-left:10px">
          ${lm.icon} ${lm.label}
          <span class="sink-layer-count">${layerItems.length}</span>
        </summary>
        <div class="sink-layer-cards">${layerItems.map(it => renderSinkCard(it)).join('')}</div>
      </details>`;
  }

  $dashView.innerHTML = `
    <div class="dash-head">
      <h2><i class="ri-archive-drawer-fill"></i> 沉淀位</h2>
      <div class="dash-head-sub">${items.length} 个文档 · 点卡片预览或本机打开</div>
    </div>
    <div class="sink-panel">${sectionsHtml}</div>`;
}

function renderSinkCard(it) {
  const lm = SINK_LAYER_META[it.layer] || SINK_LAYER_META.docs;
  const sizeStr = it.size_bytes > 102400 ? (it.size_bytes / 1024).toFixed(0) + ' KB' : (it.size_bytes / 1024).toFixed(1) + ' KB';
  const existsClass = it.exists ? '' : ' sink-card-missing';
  return `
    <div class="sink-card${existsClass}">
      <span class="sink-card-label">${escHtml(it.label)}</span>
      ${it.role ? `<span class="sink-card-role">${escHtml(it.role)}</span>` : ''}
      <span class="sink-card-meta">${it.lines ? escHtml(String(it.lines)) + ' lines' : ''}${it.lines && it.size_bytes ? ' · ' : ''}${sizeStr}</span>
      <span class="sink-card-actions">
        <button class="wb" onclick="sinkPreview('${escHtml(it.slug)}')"><i class="ri-eye-fill"></i> 预览</button>
        <button class="wb" onclick="sinkReveal('${escHtml(it.slug)}')"><i class="ri-external-link-fill"></i> 打开</button>
      </span>
    </div>`;
}

let _spmEl = null;

function sinkPreview(slug) {
  if (!_spmEl) {
    _spmEl = document.createElement('div'); _spmEl.id = 'sinkPreviewModal'; _spmEl.hidden = true;
    _spmEl.innerHTML = `<div class="spm-box"><div class="spm-head"><span class="spm-title"></span><div class="spm-head-actions"></div></div><div class="spm-body md"></div></div>`;
    _spmEl.addEventListener('click', e => { if (e.target === _spmEl) _spmEl.hidden = true; });
    document.body.appendChild(_spmEl);
  }
  const box = _spmEl.querySelector('.spm-box');
  const titleEl = box.querySelector('.spm-title');
  const actionsEl = box.querySelector('.spm-head-actions');
  const bodyEl = box.querySelector('.spm-body');
  // Remove old truncated banner
  const oldBanner = box.querySelector('.spm-truncated'); if (oldBanner) oldBanner.remove();

  titleEl.textContent = '加载中…';
  actionsEl.innerHTML = '';
  bodyEl.innerHTML = '<div class="dash-empty">加载中…</div>';
  _spmEl.hidden = false;

  fetch(`/sinks/preview/${encodeURIComponent(slug)}`, { headers: { 'Authorization': 'Bearer ' + token } })
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(data => {
      titleEl.innerHTML = escHtml(data.label) + '<span class="spm-path">' + escHtml(data.path) + '</span>';
      actionsEl.innerHTML = `<button class="wb" onclick="sinkReveal('${escHtml(slug)}')"><i class="ri-external-link-fill"></i> 本机打开</button><button class="wb" onclick="_spmEl.hidden=true"><i class="ri-close-fill"></i></button>`;
      if (data.truncated) {
        const banner = document.createElement('div'); banner.className = 'spm-truncated';
        banner.innerHTML = `<i class="ri-error-warning-fill"></i> 文件超过 200KB · 仅显示前 200KB<button class="wb" onclick="sinkReveal('${escHtml(slug)}')">本机打开完整文件</button>`;
        box.insertBefore(banner, bodyEl);
      }
      bodyEl.innerHTML = mdRender(data.markdown || '*(空文件)*');
    })
    .catch(e => { bodyEl.innerHTML = '<div class="dash-empty">加载失败: ' + escHtml(e.message) + '</div>'; });
}

async function sinkReveal(slug) {
  try {
    const r = await fetch(`/sinks/reveal/${encodeURIComponent(slug)}`, { method: 'POST', headers: { 'Authorization': 'Bearer ' + token } });
    const data = await r.json();
    if (!data.ok) alert('本机打开失败 · ' + (data.error || 'unknown'));
  } catch (e) { alert('网络出错: ' + e.message); }
}

// ESC 关闭预览
document.addEventListener('keydown', e => { if (e.key === 'Escape' && _spmEl && !_spmEl.hidden) { _spmEl.hidden = true; } });


function loadMoreWishes() {
  _wishPage++;
  _loadWishlistFiltered(_wishStatusFilter, _wishPage);
}

function renderWishCard(w, idx) {
  const stMeta = _WISH_STATUS_META[w.status] || _WISH_STATUS_META.pending;
  const pathMeta = _WISH_PATH_META[w.integration_path] || _WISH_PATH_META.undecided;
  const stars = '<i class="ri-star-fill"></i>'.repeat(w.priority || 1);

  const sourceHtml = (() => {
    const src = w.source || {};
    if (!src.ref) return '';
    const refHtml = src.url
      ? `<a href="${escHtml(src.url)}" target="_blank" rel="noreferrer">${escHtml(src.ref)} ↗</a>`
      : escHtml(src.ref);
    return `<div class="wish-source">来源 · ${escHtml(src.kind)} · ${refHtml}</div>`;
  })();

  const designHtml = w.design_sketch
    ? `<details class="wish-design"><summary>📐 设计草图</summary><div class="wish-design-body">${mdRender(w.design_sketch)}</div></details>`
    : '';

  const whyHtml = w.why
    ? `<div class="wish-why">${mdRender(w.why)}</div>`
    : '';

  // 操作区 · 卷五十三 · 按新四态 (pending/active/review/live) + 子标记 (plan_pending/blocked) 给动作
  const actions = [];
  const sub = w.daemon_phase;  // null | plan_pending | blocked
  const isDaemon = w.integration_path === 'daemon';
  const hasBranch = !!(w.dev_branch && !w.dev_branch.includes(' ') && w.dev_branch !== 'master');

  if (w.status === 'pending') {
    actions.push(`<button class="wb wb-ok" onclick="wishAction('${w.id}', 'approve_daemon')" title="OPUS 先勘察出方案·你批方案了才写码"><i class="ri-checkbox-circle-fill"></i> 批准 · 让 OPUS 装</button>`);
    actions.push(`<button class="wb" onclick="wishAction('${w.id}', 'approve_cursor')" title="你去 Cursor 里让 Claude 装"><i class="ri-focus-3-fill"></i> 我去 Cursor 装</button>`);
    actions.push(`<button class="wb wb-no" onclick="wishAction('${w.id}', 'reject')"><i class="ri-close-circle-fill"></i> 弃</button>`);
    actions.push(`<button class="wb wb-deep" onclick="wishAction('${w.id}', 'deep_dive')"><i class="ri-search-fill"></i> 让 OPUS 深挖</button>`);
  } else if (w.status === 'active') {
    if (sub === 'plan_pending') {
      actions.push(`<button class="wb wb-go" onclick="wishAction('${w.id}', 'approve_plan')" title="关卡1 · 按 OPUS 方案开干·自动从 master 切分支写码"><i class="ri-rocket-fill"></i> 批方案 → 开干</button>`);
      actions.push(`<button class="wb" onclick="wishAction('${w.id}', 'replan')" title="对方案不满意·让 OPUS 重新勘察"><i class="ri-refresh-fill"></i> 重新勘察</button>`);
      actions.push(`<button class="wb wb-no" onclick="wishAction('${w.id}', 'reject')"><i class="ri-close-circle-fill"></i> 弃</button>`);
    } else if (sub === 'blocked') {
      actions.push(`<button class="wb wb-no" onclick="wishAction('${w.id}', 'view_log')" title="看 OPUS 撞墙过程"><i class="ri-clipboard-fill"></i> 看撞墙日志</button>`);
      actions.push(`<button class="wb" onclick="wishAction('${w.id}', 'retry_impl')"><i class="ri-refresh-fill"></i> 重新实施</button>`);
      actions.push(`<button class="wb wb-no" onclick="wishAction('${w.id}', 'reject')"><i class="ri-close-circle-fill"></i> 弃</button>`);
    } else {
      if (isDaemon) {
        actions.push(`<button class="wb wb-go" disabled title="OPUS 在自己分支上写码·完工自动进待验收">⏳ OPUS 进行中…</button>`);
        actions.push(`<button class="wb wb-no" onclick="wishAction('${w.id}', 'abort_impl')">⏹ 紧急叫停</button>`);
      } else {
        actions.push(`<button class="wb wb-go" onclick="wishAction('${w.id}', 'mark_review')" title="装完了·提交验收">📬 装完了 → 提交验收</button>`);
        actions.push(`<button class="wb wb-no" onclick="wishAction('${w.id}', 'reject')"><i class="ri-close-circle-fill"></i> 弃</button>`);
      }
      if (hasBranch) actions.push(`<button class="wb" onclick="wishAction('${w.id}', 'view_diff')"><i class="ri-search-fill"></i> 看 diff</button>`);
    }
    actions.push(`<button class="wb wb-deep" onclick="wishAction('${w.id}', 'deep_dive')"><i class="ri-search-fill"></i> 让 OPUS 深挖</button>`);
  } else if (w.status === 'review') {
    if (hasBranch) actions.push(`<button class="wb wb-go" onclick="wishAction('${w.id}', 'view_diff')" title="看 OPUS 改了啥"><i class="ri-search-fill"></i> 查看 diff</button>`);
    actions.push(`<button class="wb wb-go" onclick="wishAction('${w.id}', 'verify_live')" title="关卡2 · 验收通过·自动合进 master 主干上线"><i class="ri-checkbox-circle-fill"></i> 验收通过 → 合主干上线</button>`);
    actions.push(`<button class="wb wb-no" onclick="wishAction('${w.id}', 'reject_to_active')" title="有问题·打回让 OPUS 继续改"><i class="ri-arrow-go-back-fill"></i> 有问题 → 打回</button>`);
    if (!w.reflection) actions.push(`<button class="wb" onclick="wishAction('${w.id}', 'add_reflection')">✏️ 补反思</button>`);
  } else if (w.status === 'live') {
    if (w.git_lie) {
      actions.push(`<button class="wb wb-no" onclick="wishAction('${w.id}', 'remerge')" title="status=live 但 git 没合进 master·重新触发真合并"><i class="ri-error-warning-fill"></i> 修复 · 重新合并主干</button>`);
    }
    if (!w.reflection) actions.push(`<button class="wb" onclick="wishAction('${w.id}', 'add_reflection')">✏️ 补反思</button>`);
  }

  const reflectionHtml = w.reflection
    ? `<div class="wish-reflection"><div class="wr-title"><i class="ri-lightbulb-fill"></i> 反思</div>${mdRender(w.reflection)}</div>`
    : '';

  // 卷五十三 · 子标记指示条 + plan/log/diff 折叠区
  let phaseBlock = '';
  if (w.integration_path === 'daemon' && (sub || w.implementation_plan || w.implementation_log)) {
    const phMeta = _WISH_DAEMON_PHASE_META[sub] || _WISH_DAEMON_PHASE_META.unknown;
    const phaseChip = sub ? `<span class="wish-phase wish-phase-${sub}" title="${phMeta.tip}">${phMeta.icon} ${phMeta.label}</span>` : '';
    const branchChip = w.dev_branch ? `<span class="wish-branch" title="OPUS 改代码用的 git 分支">🌿 ${escHtml(w.dev_branch)}</span>` : '';
    const planSection = w.implementation_plan
      ? `<details class="wish-design" open><summary><i class="ri-clipboard-fill"></i> 执行计划 (OPUS 勘察输出)</summary><div class="wish-design-body">${mdRender(w.implementation_plan)}</div></details>`
      : '';
    const logSection = w.implementation_log
      ? `<details class="wish-design"><summary>📜 实施日志</summary><div class="wish-design-body">${mdRender(w.implementation_log)}</div></details>`
      : '';
    const diffSection = w.diff_summary
      ? `<details class="wish-design" open><summary><i class="ri-search-fill"></i> git diff 摘要 (待看)</summary><div class="wish-design-body"><pre>${escHtml(w.diff_summary)}</pre></div></details>`
      : '';
    phaseBlock = `
      <div class="wish-phase-row">${phaseChip} ${branchChip}</div>
      ${planSection}
      ${logSection}
      ${diffSection}`;
  }

  // 卷四十六续 8 · 默认折叠·只把"等 用户 做决定的"默认展开 (卷五十三新态):
  //   pending (等批) / review (等验收) / 子标记 plan_pending (等批方案) / blocked (撞墙)
  const isOpen = (
    w.status === 'pending' ||
    w.status === 'review' ||
    (w.daemon_phase && ['plan_pending', 'blocked'].includes(w.daemon_phase))
  );
  const whyExcerpt = (() => {
    if (!w.why) return '';
    const firstLine = w.why.split('\n').map(s => s.trim()).find(s => s && !s.startsWith('#') && !s.startsWith('-')) || '';
    return firstLine.slice(0, 120);
  })();
  const phaseChipInSummary = (w.integration_path === 'daemon' && w.daemon_phase)
    ? (() => {
        const phMeta = _WISH_DAEMON_PHASE_META[w.daemon_phase] || _WISH_DAEMON_PHASE_META.unknown;
        return `<span class="wish-phase wish-phase-${w.daemon_phase}" title="${phMeta.tip}">${phMeta.icon} ${phMeta.label}</span>`;
      })()
    : '';

  return `
    <details class="wish-card wish-status-${w.status}" data-wid="${w.id}"${isOpen ? ' open' : ''}>
      <summary class="wish-card-head">
        <div class="wish-card-title">
          <span class="wish-stars">${stars}</span>
          <span class="wish-title-text">${escHtml(w.title)}</span>
        </div>
        <div class="wish-card-badges">
          <span class="wish-badge wish-badge-status" style="background:${stMeta.color}22;color:${stMeta.color}">${stMeta.icon} ${stMeta.label}</span>
          ${w.git_lie
            ? `<span class="wish-badge wish-badge-unmerged" title="测谎仪: status=live 但代码没合进 master·谎报上线·一回退就丢。点卡片里「修复·重新合并主干」"><i class="ri-error-warning-fill"></i> 🔴 谎报上线 · ${w.git_unmerged_commits || '?'} commit 没合</span>`
            : (w.git_merge_state === 'unmerged'
              ? `<span class="wish-badge wish-badge-branch" title="代码在自己分支上·还没合主干 (active/review 阶段正常)·验收标 live 后会自动合"><i class="ri-git-branch-line"></i> 分支上 · ${w.git_unmerged_commits || '?'} commit</span>`
              : '')}
          ${w.origin === 'opus' ? '<span class="wish-badge wish-badge-origin" title="OPUS 主动嗅探到的愿望"><i class="ri-radar-fill"></i> OPUS 主动发现</span>' : ''}
          ${phaseChipInSummary}
          <span class="wish-badge wish-badge-path">${pathMeta.icon} ${escHtml(pathMeta.label)}</span>
          <span class="wish-badge wish-badge-cx">${escHtml(w.complexity || 'medium')} · ~${w.estimated_hours || 4}h · ~$${(w.estimated_token_cost_usd || 1).toFixed(2)}</span>
        </div>
        ${whyExcerpt ? `<div class="wish-why-excerpt">${escHtml(whyExcerpt)}</div>` : ''}
      </summary>
      <div class="wish-card-body">
        ${sourceHtml}
        ${whyHtml}
        ${designHtml}
        ${phaseBlock}
        ${reflectionHtml}
        <div class="wish-actions">${actions.join('')}</div>
        <div class="wish-meta">
          <span class="wish-id">${escHtml(w.id)}</span>
          <span class="wish-time">写于 ${(w.created_at || '').replace('T', ' ').slice(0, 16)}</span>
        </div>
      </div>
    </details>`;
}

// 卷五十三 · 子标记 meta (仅 active 时挂·plan_pending=等批方案 / blocked=撞墙)
const _WISH_DAEMON_PHASE_META = {
  plan_pending: { icon: '<i class="ri-pause-circle-fill"></i>', label: '等待批方案', tip: 'OPUS 出完方案·停下等 用户 批 (关卡1)·批了才从 master 切分支写码' },
  blocked:      { icon: '⚠️', label: '撞墙了', tip: 'OPUS 中途遇阻主动停 · 看撞墙日志找原因·或重新实施' },
  unknown:      { icon: '·',  label: '', tip: '' },
};

function setWishStatusFilter(st) {
  _wishStatusFilter = st;
  _wishPage = 1;  // 切换过滤器时回到第一页
  _wishAllData = null;
  _loadWishlistFiltered(st);
}

async function wishAction(wid, action) {
  // 卷五十三 · 四态流程 · 提示词对齐新状态机 (pending/active/review/live + plan_pending/blocked)
  const map = {
    approve_daemon: (
      `已批准心愿 ${wid} · 让你自己动手装。\n\n` +
      `**进入勘察模式** —— 这一步只调研·不改任何代码。\n\n` +
      `步骤：\n` +
      `1. 用 wish_update 把 status 改成 active · integration_path 改成 daemon\n` +
      `2. 用 read_dashboard("wishlist") 把这条 wish 完整内容拉出来 (尤其 design_sketch / why / source)\n` +
      `3. **勘察现状**：\n` +
      `   - 用 grep_files / read_file 找相关模块的现有代码 (这条 wish 涉及哪些文件?)\n` +
      `   - 需要参考资料·用 web_search / web_fetch 查·不清楚的概念先想清楚\n` +
      `4. **产出执行计划** (markdown · 严格结构):\n` +
      `   ## 改动范围 (文件·干啥·为啥)\n` +
      `   ## 关键设计决定\n` +
      `   ## 步骤拆解\n` +
      `   ## 验证策略 (smoke / ReadLints)\n` +
      `   ## 风险 / 不确定性\n` +
      `5. 用 wish_update 把计划存进 implementation_plan · **daemon_phase 改成 plan_pending** (停下等待批方案 · 关卡1)\n` +
      `6. 一句话告诉 用户：「方案好了·要不要按这个干？」\n\n` +
      `**红线**：勘察阶段绝对不能 write_file / shell_exec 写操作 · 只能读 + 搜 · 用户 批方案再开干。`
    ),
    approve_cursor:  `把心愿 ${wid} 批准了·integration_path=cursor · status=active · 用 wish_update 改 · 告诉 用户 现在可以去 Cursor 里复制 design_sketch 让 Claude 装·装完回来点「装完了→提交验收」`,
    reject:          `把心愿 ${wid} 弃了·status=rejected · 用 wish_update 改 · 简单说一句为啥弃`,
    switch_daemon:   `心愿 ${wid} 改成 DAEMON 路径·integration_path=daemon · 用 wish_update 改`,
    switch_cursor:   `心愿 ${wid} 改成 Cursor 路径·integration_path=cursor · 用 wish_update 改`,
    // 关卡1 · 用户 批方案 → OPUS 开始写码 (status 已 active · 清 plan_pending 会自动从 master 切分支)
    approve_plan: (
      `用户 批了心愿 ${wid} 的方案 (关卡1) · 批准你 (OPUS) 真改代码。\n\n` +
      `**进入实施模式** —— 现在可以 write_file / shell_exec 了·但守红线。\n\n` +
      `步骤：\n` +
      `1. 用 wish_update 把 **daemon_phase 改成 null** (清空 plan_pending) · status 保持 active\n` +
      `   → 工具会**自动从 master 切出 wish-${wid}/<slug> 分支**并写进 dev_branch (你不用手动 git checkout)\n` +
      `2. **按 implementation_plan 的步骤在该分支上执行**:\n` +
      `   - 改代码后立即 ReadLints (Python 文件) · 关键步骤跑 smoke\n` +
      `   - 每完成一步·wish_update 往 implementation_log 追加一行\n` +
      `3. **遇阻就停** —— 撞墙后: 写进 implementation_log · wish_update daemon_phase=blocked · 告诉 用户 · 不要硬撑\n` +
      `4. **写完自测**: ReadLints 全部改过的 py · 跑 smoke · git diff --stat 存进 diff_summary\n` +
      `5. 用 wish_update 把 **status 改成 review** (完工待验收) · 一句话告诉 用户 可以看 diff 了\n\n` +
      `**红线**: 不许 push · 不许 rm -rf · 不许动 soul/ / .env · 不确定先问 用户。\n` +
      `(commit 由系统在你的分支上管理·你专注写对代码·用户 验收通过点 live 会自动 merge 回 master)`
    ),
    // 关卡2 · 用户 验收通过 → status=live (wish_update 会自动 merge 分支回 master·合不进会拒绝)
    verify_live: (
      `心愿 ${wid} · 用户 验收通过！→ 上线 (关卡2)。\n\n` +
      `请你：\n` +
      `1. 用 wish_update 把 status 改成 **live**\n` +
      `   → 有独立分支时·工具会**自动 merge 分支回 master** (先让分支吃下最新 master·冲突会 abort 并报错)\n` +
      `   → 万一报"merge 失败/冲突"·别硬来·把冲突情况告诉 用户·先解决再标 live\n` +
      `2. 成功后写一句简短 reflection 总结这次交付`
    ),
    reject_to_active: (
      `心愿 ${wid} · 用户 验收不通过 · 打回让 OPUS 继续改。\n\n` +
      `请你：\n` +
      `1. 用 wish_update 把 status 改回 active (回到写码态·分支还在·接着改)\n` +
      `2. 在 implementation_log 末尾追加 "用户 验收不通过 · 原因：[用户 说的]" · 等 用户 告诉你具体哪不行`
    ),
    mark_review: (
      `心愿 ${wid} · 装完了 · 提交验收。\n\n` +
      `请你：\n` +
      `1. 用 wish_update 把 status 改成 review\n` +
      `2. 若是 daemon 路径有 dev_branch · 先 git diff --stat 存进 diff_summary 让 用户 一眼能看\n` +
      `3. 没写 reflection 的话补一句·告诉 用户 可以验收了`
    ),
    remerge: (
      `心愿 ${wid} · 测谎仪报警: status=live 但代码没真合进 master (谎报上线)。\n\n` +
      `请你：\n` +
      `1. 用 read_dashboard 确认 dev_branch · shell_exec("git cherry master <dev_branch>") 看到底差几个提交\n` +
      `2. 如果分支有真没合的活儿 → 用 wish_update status=live 重新触发自动 merge (合不进会报冲突·按提示解决)\n` +
      `3. 如果分支其实是空的/已废 → 把 dev_branch 字段清成正确备注·消除误报\n` +
      `4. 修完告诉 用户 测谎仪应该不报了`
    ),
    add_reflection:  `给心愿 ${wid} 补一段 reflection · 用 wish_update 改`,
    deep_dive:       `深挖心愿 ${wid}：用 read_dashboard 拉它的设计草图·然后给我一份评估——这事要不要做·什么时候做·怎么拆任务·有什么风险`,
    replan: (
      `心愿 ${wid} · 用户 对方案不满意·让你重新勘察。\n\n` +
      `请你：\n` +
      `1. 用 read_dashboard 把之前的 implementation_plan 看一遍·想想哪里不对\n` +
      `2. 问 用户 哪里不满意 (如果他没说) · 等他回答\n` +
      `3. 用新理解重做一份计划 → wish_update 更新 implementation_plan · daemon_phase 保持 plan_pending (再等 用户 批)`
    ),
    abort_impl: (
      `**紧急叫停** · 心愿 ${wid} 的实施·用户 让你立刻停手。\n\n` +
      `请你：\n` +
      `1. 不要再继续写代码\n` +
      `2. 用 wish_update 把 daemon_phase 改成 blocked · 在 implementation_log 末尾追加"用户 中途叫停 (时间)"\n` +
      `3. shell_exec("git status") 看当前分支状态·告诉 用户 现在改了哪些文件\n` +
      `4. **不要** git checkout / reset·让 用户 决定怎么处理`
    ),
    view_diff: (
      `用户 想看心愿 ${wid} 的 git diff 详情。请你：\n` +
      `1. 用 read_dashboard 拉 wish 看 dev_branch 字段\n` +
      `2. shell_exec("git diff master..." + dev_branch) (注意是 master..分支)\n` +
      `3. 把 diff 完整粘贴给 用户·重点改动用 markdown 突出`
    ),
    view_log: (
      `用户 想看心愿 ${wid} 的实施日志。用 read_dashboard 拉这个 wish 的 implementation_log · 完整复盘给 用户·并解释撞墙的根本原因。`
    ),
    retry_impl: (
      `心愿 ${wid} 上次撞墙了 (daemon_phase=blocked) · 用户 让你重新试。\n\n` +
      `请你：\n` +
      `1. 先看 implementation_log 想清楚上次为啥失败\n` +
      `2. 用 wish_update 把 daemon_phase 清成 null (回到正常写码态) · status 保持 active\n` +
      `3. 在 log 里明说"第 N 次尝试"·别覆盖前面日志·然后接着按计划改`
    ),
  };
  const msg = map[action];
  if (!msg) return;

  // 重操作开新会话执行 · 不污染当前聊天上下文
  const spawnLabels = {
    approve_daemon: `勘察方案 · ${wid}`,
    approve_plan: `实施计划 · ${wid}`,
    replan: `重新勘察 · ${wid}`,
    retry_impl: `重新实施 · ${wid}`,
    verify_live: `验收上线 · ${wid}`,
    remerge: `修复合并 · ${wid}`,
    deep_dive: `深挖心愿 · ${wid}`,
  };
  spawnTask(msg, spawnLabels[action] || `${action} · ${wid}`);
}

function askOpusForWish() {
  spawnTask(
    '看一眼 self-evolve 域 (信息雷达里) 现在抓到的 GitHub 同类工程·' +
    '挑 1-3 个 OPUS 自己应该学的能力·调 wish_add 写成心愿 · 每条都要有 why + design_sketch + 优先级 · ' +
    '不要一次塞太多·挑你最有把握的',
    '勘察心愿'
  );
}

// 接 setWishStatusFilter 那个带 ? 的路由
async function _loadWishlistFiltered(filter, page = 1) {
  try {
    const params = new URLSearchParams();
    if (filter) params.set('domain_filter', filter);
    params.set('page', page);
    params.set('page_size', _wishPageSize);
    const url = `/dashboard/wishlist?${params.toString()}`;
    const r = await fetch(url, { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) {
      $dashView.innerHTML = `<div class="dash-empty">加载失败 [${r.status}]</div>`;
      return;
    }
    const data = await r.json();
    _wishAllData = data;
    renderWishlist(data);
  } catch (e) {
    $dashView.innerHTML = `<div class="dash-empty">网络出错: ${e.message}</div>`;
  }
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
      OPUS 当前装载的所有工具 · 按层次分组。<br>
      未来通过 <b><i class="ri-radar-fill"></i> 信息雷达 → <i class="ri-terminal-box-fill"></i> 产品开发</b> · OPUS 可以自己写新工具回填到这里。
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
                <i class="ri-lightbulb-fill"></i> 让 OPUS 用这个工具做点事
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
    { id: 'trends',  icon: '<i class="ri-line-chart-fill"></i>', label: '趋势',   hint: '提炼层 · OPUS 军师视图' },
    { id: 'reports', icon: '<i class="ri-article-fill"></i>', label: '报告',   hint: '成品层 · 正式 docx 出货' },
  ];
  const parts = stages.map((s, i) => {
    const active = (s.id === current) ? ' active' : '';
    const arrow = i > 0 ? '<span class="pl-arrow">→</span>' : '';
    return arrow +
      `<button class="pl-stage${active}" onclick="loadDashboard('${s.id}')" ` +
      `title="${escHtml(s.hint)}">${s.icon} ${s.label}</button>`;
  }).join('');
  return `<div class="pipeline" title="OPUS 信息流水线 · 点击切换维度">${parts}</div>`;
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
    ? `<div class="radar-histogram"><div class="rh-title">信源贡献${scoped}</div><div class="sh-empty">这个领域还没有专属信源 · 跟 OPUS 说「给「${escHtml(scopeLabel)}」加个信息源」</div></div>`
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
    const color = fail ? 'var(--red)' : 'var(--opus)';
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
    ? allItems.filter(it => (it.domain || 'self-evolve') === radarDomainFilter)
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
    // 卷三十四补丁 · self-evolve 是 OPUS 自演化的镜子·不能删·不显示删除按钮
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
      <button onclick="spawnQuickly('看一眼信息雷达最新数据 · 调 auto_pipeline 工具 · 参数 refresh_radar=false, regen_trends=true, mine_opps=false · 只重新生成今日趋势 · 跑完告诉我哪几个趋势最戳到 用户 · 为什么', '生成今日趋势')">让 OPUS 总结趋势 →</button>
    </div>
    ${domainChips}
    ${statsCards}
    ${renderSourceHistogram(
      (radarDomainFilter && radarDomainFilter !== 'all') ? meta.filter(m => (m.domain || 'self-evolve') === radarDomainFilter) : meta,
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
      const transBadge = it.title_zh ? '<span class="ri-tr-badge" title="OPUS 已翻译 · 鼠标移到标题看原文">中</span>' : '';
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
                  onclick="event.stopPropagation();toggleRadarFeedback('${escHtml(iid)}', 'thumbs_up', ${JSON.stringify(showTitle).replace(/"/g, '&quot;')}, ${JSON.stringify(it.url || '').replace(/"/g, '&quot;')})"><i class="ri-thumb-up-fill"></i></button>
          <button class="ri-fb-btn ${fb === 'thumbs_down' ? 'active' : ''}"
                  title="👎 别再抓这种"
                  onclick="event.stopPropagation();toggleRadarFeedback('${escHtml(iid)}', 'thumbs_down', ${JSON.stringify(showTitle).replace(/"/g, '&quot;')}, ${JSON.stringify(it.url || '').replace(/"/g, '&quot;')})"><i class="ri-thumb-down-fill"></i></button>
          <button class="ri-fb-btn ${fb === 'starred' ? 'active' : ''}"
                  title="⭐ 收藏"
                  onclick="event.stopPropagation();toggleRadarFeedback('${escHtml(iid)}', 'starred', ${JSON.stringify(showTitle).replace(/"/g, '&quot;')}, ${JSON.stringify(it.url || '').replace(/"/g, '&quot;')})"><i class="ri-star-fill"></i></button>
          <button class="ri-fb-btn ${fb === 'hidden' ? 'active' : ''}"
                  title="🗑 隐藏 · 下次刷新不再出现"
                  onclick="event.stopPropagation();toggleRadarFeedback('${escHtml(iid)}', 'hidden', ${JSON.stringify(showTitle).replace(/"/g, '&quot;')}, ${JSON.stringify(it.url || '').replace(/"/g, '&quot;')})"><i class="ri-delete-bin-fill"></i></button>
          <button class="ri-fb-btn ri-deep-btn"
                  title="🔍 深挖 · OPUS 用 web_search 拓展这个话题"
                  onclick="event.stopPropagation();deepDiveRadar(${JSON.stringify(showTitle).replace(/"/g, '&quot;')})"><i class="ri-search-fill"></i></button>
          ${(it.domain === 'self-evolve') ? `
          <button class="ri-fb-btn ri-wish-btn"
                  title="🤔 让 OPUS 看一眼 · 推给 OPUS · 让他自己判断要不要装"
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
// 自然语言删除依然可以走 OPUS · 这个函数只服务"按钮点击"场景
async function confirmRemoveDomain(slug, label, itemsCount, sourcesCount) {
  if (!slug || slug === 'self-evolve') return;
  const ok = await opusConfirm({
    title: '删除雷达领域',
    message: {
      html: `确认删除领域 <b>「${escHtml(label)}」</b> 吗？
        <span class="om-hint">${sourcesCount} 个信源 · ${itemsCount} 条历史条目<br>
        信源会自动 reassign 到 self-evolve (或其他可用域)·不会丢失。<br>
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
      await opusAlert({
        title: '删除失败',
        message: `${resp.status} · ${errText}`,
        danger: true,
      });
      return;
    }
    const result = await resp.json();
    const affected = (result && result.affected_sources && result.affected_sources.length) || 0;
    const target = (result && result.target_domain) || '—';
    await opusAlert({
      title: '删除成功',
      message: {
        html: `已删除领域 <b>「${escHtml(label)}」</b>。<br>
          <span class="om-hint">影响 ${affected} 个信源·已 reassign 到 <b>${escHtml(target)}</b></span>`
      },
    });
    if (typeof loadDashboard === 'function') loadDashboard();
  } catch (e) {
    await opusAlert({
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

// 卷二十七 · 今日趋势 = OPUS 军师视图（不只是「今日」· 是前瞻+操作建议）
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
      <h2><i class="ri-line-chart-fill"></i> 今日趋势 · OPUS 军师视图</h2>
      <span class="meta"><i class="ri-calendar-fill"></i> <b>${escHtml(isArchive ? archiveDay : generatedDay)}</b> · ${trends.length} 个方向 · 扫了 ${itemsScanned} 条 · ${generatedTxt}${isArchive ? ' <span class="badge-archive">归档</span>' : ''}</span>
      <button onclick="backToChat()">✕ 收起</button>
      <button onclick="loadDashboard('radar')">← 看原料</button>
      <button onclick="spawnQuickly('看一眼信息雷达最新数据 · 调 auto_pipeline 工具 · 参数 refresh_radar=false, regen_trends=true, mine_opps=false · 只重新生成今日趋势 · 跑完告诉我哪几个趋势最戳到 用户 · 为什么', '重新生成趋势')">让 OPUS 重新看一遍</button>
    </div>
    <div class="trends-intro">
      不是「今日新闻总结」· 是 OPUS 看完雷达 ${itemsScanned} 条后给出的
      <strong>前瞻性思考 + 工作室视角</strong>——每个趋势都标了强度 + 可切入的角度 +
      可一键转化的动作。${isArchive ? `<br><span class="archive-hint">⏳ 当前查看的是 <b>${escHtml(archiveDay)}</b> 的归档趋势·不是最新版</span>` : ''}
    </div>
    ${trends.length > 3 ? renderListFilter({targetSelector: '.trend-card', placeholder: '搜趋势标题 / 摘要 / 信源...'}) : ''}`;

  if (trends.length === 0) {
    html += `
      <div class="dash-stub">
        <h3>还没生成趋势</h3>
        <div>${escHtml((data && data.note) || '点"让 OPUS 重新看一遍"·OPUS 会读 radar.json·输出 3-5 个方向·约 30-60s')}</div>
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
      const reportBtn = `<button class="trend-action ta-report" onclick="triggerTrendAction(${idx}, 'report')" title="OPUS 用 LLM 把这个趋势展开成 3000-4500 字 docx 报告"><i class="ri-article-fill"></i> 写报告</button>`;
      const deepBtn = `<button class="trend-action ta-deep" onclick="deepDiveTrend(${idx})" title="让 OPUS 用 web_search + web_fetch 深挖这个趋势"><i class="ri-search-fill"></i> 深挖</button>`;
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
        <div>在底部输入框跟 OPUS 说：「整理一下本周雷达写成报告」<br>
             OPUS 会调 <code>generate_report</code> · docx 自动落在这里。</div>
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
            <a class="rc-dl" href="${escHtml(dlUrl)}" download="${escHtml(it.name)}">下载 ↓</a>
          </div>
        </div>`;
    }
    html += `</div>`;
  }
  $dashView.innerHTML = html;

  // 卷三十三补丁 · 预览按钮绑定
  $dashView.querySelectorAll('.rc-preview-btn, .rc-name[data-preview]').forEach(el => {
    el.onclick = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const name = el.getAttribute('data-name');
      if (name) loadReportPreview(name);
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
      <button onclick="spawnQuickly('基于今日趋势 · 调 mine_opportunities 工具 · 参数 action=mine · 重新挖一遍掘金机会 · 形态要多样(内容账号 / 实体产品 / 服务咨询 / 信息差套利 / 软件产品 / 投资副业 · 不要全是 SaaS · 卷三十三第 6 条铁律) · 跑完告诉我最推哪 1-2 个 + 为什么', '重新挖掘机会')" title="派发到新会话 · OPUS 跑 mine_opportunities · 完成后切过去看结果">
        <i class="ri-refresh-fill"></i> 重新挖掘
      </button>
    </div>`;

  if (opps.length === 0) {
    html += `
      <div class="dash-stub">
        <h3>还没挖过掘金机会</h3>
        <div>${escHtml(note || '点上方"重新挖掘"按钮 · 会基于最新趋势 + 你的画像 LLM 跑一次')}</div>
        <div style="margin-top:12px;font-size:11px;color:var(--dim2)">
          需要先有趋势 · 没趋势的话先去 <i class="ri-line-chart-fill"></i> 今日趋势 跑一次
        </div>
      </div>`;
  } else {
    html += `
      <div class="opp-intro">
        生成于 ${formatTimeShort(generated)} · 扫描了 ${trendsScanned || 0} 条趋势 · 耗时 ${elapsedS}s<br>
        <span style="font-size:11px;color:var(--dim2)">
          每个机会都基于你的画像评估了适配度 · 点机会卡可展开成完整方案
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
        <span class="opp-rec" title="OPUS 推荐度 ${o.recommend}/5">${stars}</span>
        <button class="opp-star-btn ${starred ? 'starred' : ''}"
                data-ref="${escHtml(o.id || '')}"
                data-title="${escHtml(o.title || '')}"
                data-domain="${escHtml(o.domain || '')}"
                title="${starred ? '已收藏 · 点击取消' : '收藏'}">
          ${starred ? '★' : '☆'}
        </button>
      </div>
      <div class="opp-metas">
        <span class="opp-meta-pill" title="适配度">${fitIcon} ${fitLabel}</span>
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
                onclick="runFeasibilityFromOpp('${escHtml(o.id || '')}', ${idx + 1})"
                title="跳到 📊 可行性分析维度 · OPUS 跑一次深度评估">
          <i class="ri-bar-chart-fill"></i> 跑可行性
        </button>
        <button class="opp-act-btn" onclick="spawnQuickly('针对第 ${idx + 1} 个机会·写一份调研报告', '机会调研报告')">
          <i class="ri-article-fill"></i> 写报告
        </button>
        <button class="opp-act-btn opp-act-deep"
                onclick="deepDiveOpp(${idx + 1})"
                title="让 OPUS 用 web_search + web_fetch 深挖这个机会">
          <i class="ri-search-fill"></i> 深挖
        </button>
        ${(o.domain === 'self-evolve') ? `
        <button class="opp-act-btn opp-act-wish"
                onclick="wishFromOpp(${idx + 1})"
                title="🤔 让 OPUS 看一眼 · 推给 OPUS · 让他自己判断要不要装">
          <i class="ri-emotion-think-line"></i> 让 OPUS 看一眼
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

// 卷三十四 · "<i class="ri-search-fill"></i> 深挖" 按钮 · 让 OPUS 调 web_search + web_fetch 深挖某个点
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

// 卷三十五 · self-evolve domain 的 radar 条目 → 让 OPUS 写心愿
function wishFromRadar(title, url) {
  if (!title) return;
  const urlPart = url ? `· URL: ${url}` : '';
  spawnTask(
    `用户 邀请你看一眼 self-evolve 雷达上的这个工程：「${title}」${urlPart}\n\n` +
    `**这是邀请·不是命令** —— 你要自己判断·不是 用户 让你装你就装。\n\n` +
    `请你：\n` +
    `1. 用 web_search / web_fetch 弄清这个工程做啥 · 看 README / 主要特性\n` +
    `2. 对照本工程现状·想清楚：\n` +
    `   - 你有没有这个能力·还是缺\n` +
    `   - 它的设计哲学跟本工程是否合拍 (人机协同 / 双向认知 / 可追溯)\n` +
    `   - 如果合拍·这能力对 用户 这个具体的人有啥用 (而不是"通用上有用")\n` +
    `3. 然后明确告诉 用户：\n` +
    `   - 值得装 → 调 wish_add 写一份心愿 (title / why / source_kind=radar / source_ref + url / design_sketch / complexity / hours / priority / opus_take = 你自己的态度)\n` +
    `   - 不值得装 → 说清为啥·别强加 wish 占心愿单\n` +
    `   - 拿不准 → 就说拿不准·要 用户 给更多 context\n` +
    `**你才是搭档·不是给 用户 端菜的工具人**·拿出判断力。`,
    `勘察: ${title}`
  );
}

// 卷三十五 · self-evolve domain 的 opportunity → 让 OPUS 把它转成心愿
function wishFromOpp(oneBasedIdx) {
  const card = document.querySelector(`.opp-card[data-opp-idx="${oneBasedIdx}"]`);
  const title = card
    ? (card.getAttribute('data-opp-title') || `第 ${oneBasedIdx} 个机会`)
    : `第 ${oneBasedIdx} 个机会`;
  spawnTask(
    `用户 让你看一眼 self-evolve 域的掘金机会「${title}」——这其实是关于 OPUS 自己的成长。\n\n` +
    `**这是邀请·你要自己判断**。请你：\n` +
    `1. 用 read_dashboard("opportunities") 把机会卡完整内容拉出来\n` +
    `2. 想清楚：\n` +
    `   - OPUS 现状有没有这能力·缺哪一块\n` +
    `   - 装上之后真正受益的是 用户 哪个具体痛点 (而不是泛泛的"AI 升级")\n` +
    `   - 跟本工程现有架构合拍吗\n` +
    `3. 明确表态:\n` +
    `   - 值得装 → wish_add (title 改写成"OPUS 装 X" / why = 对 用户 的具体价值 / source_kind=opportunity / source_ref=opp_id / design_sketch=2-3 步改造方案 / complexity / hours / cost / priority)\n` +
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
if (!token) {
  addSys('远程访问需要填 API Token（本机访问无需配置）');
  setTimeout(openSettings, 400);
} else {
  if (sessionId && !sessionId.startsWith('tmp-')) {
    // 浏览器刷新页面 · 已有 sessionId · load 历史进 container 然后才显示"OPUS 在线"
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
        addSys('<i class="ri-refresh-fill"></i> daemon 刚重启过 · OPUS 正在后台续写上次的任务 · 自动接续中…', st && st.$container);
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
        addSys('OPUS 在线 · ' + aliasFor(sessionId) + ' · 点 ≡ 看历史对话');
        // wish-3fef4bc7 follow-up · 查 daemon 是否仍有 active turn · 有就启 polling auto-refresh
        _maybeStartPoll(st);
      }
    }).catch(() => {
      addSys('OPUS 在线 · ' + aliasFor(sessionId) + ' · (历史加载失败) · 点 ≡ 看历史对话');
    });
  } else {
    addSys('OPUS 在线 · 新对话 · 点 ≡ 看历史对话');
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
  _checkProactiveInbox();  // 卷六十 · 开页先查一次 OPUS 有没有主动找过
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
}


// ═══════════════════════════════════════════════════════════════
// OPUS 脉搏 (wish-7330d23f) · SSE 实时活动指示器
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

// 卷五十五 · 2026-06-03 · P1 前端错误边界的就绪信标。
// chat.js 顶层执行到这里 = 解析成功 + 没在顶层抛错 → 标记 app 已就绪。
// chat.html 头部的 boot-guard 靠这个标志判断: 超时后仍为 false = chat.js parse/运行
// 失败 (白屏) → 弹兑底层。 这一行必须在 chat.js 最末尾。
window.__OPUS_APP_READY = true;
