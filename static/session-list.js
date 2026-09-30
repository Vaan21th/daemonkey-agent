/* static/session-list.js · 会话列表（工作台抽屉 + 专注版左栏 共用）（wish-16fa5930 第 5 步）
   ----------------------------------------------------------------------------
   从 chat.js 整块搬出（照 doc-shelf.js 的同一拆分模式：跨文件零改动 ·
   顶层 function 进全局作用域 · 所有调用点原样工作）。
   本文件【必须排在 chat.js 之后】加载（见 chat.html <script> 顺序）——
   依赖的 token / sessionId / sessionMetaCache / switchToSession / openSessionMenu /
   aliasFor / escHtml / updateCurrentLabel / _startSessionRunPoll / _renderCompactFoot
   等全在函数体内运行时解析。
   组成:
     [0] 状态      —— 抽屉 + 专注版两套分页/分组状态
     [1] 分组       —— 今天/昨天/本周/本月/更早 · 跨页不重复插标题
     [2] 行渲染     —— buildSessionRow（含档位徽标）
     [3] 抽屉列表   —— refreshSessionList + 归档视图
     [4] 专注版列表 —— renderCompactSessions + 分页 + 归档视图
     [5] 统一刷新口 —— _refreshSessionLists
   ============================================================================ */

// ══ [0] 状态 ══
// —— 抽屉（工作台）——
let showArchivedSessions = false;
let archivedCount = 0;

// —— 专注版 ——
let _compactSessionOffset = 0;
let _compactShowArchived = false;   // 专注版归档视图开关 (跟工作台抽屉的 showArchivedSessions 各自独立)
let _compactLastGroupKey = null;   // 分页续接时上一页最后的组 key · 跨页不重复插分组标题
const _COMPACT_PAGE = 30;

// —— 两套共用/各自 ——
const $sessionList = document.getElementById('sessionList');
let _sessionListOffset = 0;
let _drawerLastGroupKey = null;   // 分页续接时上一页最后的组 key · 跨页不重复插分组标题
const SESSION_PAGE = 50;

// ══ [1] 分组 ══
// 会话按时间分组 (BRO 2026-08-15 拍板 · 今天/昨天/本周/本月/更早 · 专注版 + 工作台共用)
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

// ══ [2] 行渲染 ══

// wish-1b00ca00 · 哪些会话在等延迟唤醒 —— “在等”是跨会话的状态，
// 用户在列表上一眼要能看到（避免切走了就忘），所以每行按 session_id 匹配打标记。
let _wakeupBySession = {};

async function _loadWakeups() {
  try {
    const r = await fetch('/api/wakeups', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) return;
    const d = await r.json();
    const m = {};
    for (const w of (d.wakeups || [])) if (!m[w.session_id]) m[w.session_id] = w;
    _wakeupBySession = m;
  } catch (e) { /* 拿不到就当作没有 · 绝不能打断列表渲染 */ }
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
  const _wk = _wakeupBySession[s.session_id];
  const wkIcon = _wk ? '<span class="sp-wake" title="' + escHtml('在等 · ' + (_wk.label || '唤醒') + ' · ' + Math.max(1, Math.round((_wk.remaining_sec || 0) / 60)) + ' 分钟后自己回来') + '"><i class="ri-timer-line"></i></span>' : '';
  const _prof = s.last_tool_profile || (sessionMetaCache[s.session_id] || {}).last_tool_profile || '';
  const _pbi = (typeof window.tpBadgeInfo === 'function') ? window.tpBadgeInfo(_prof) : null;
  // BRO 2026-09-16 · 每行都标（含标准档 · 标准做淡 dim）· 显示短名
  const profBadge = _pbi ? '<span class="sp-prof ' + _pbi.cls + (_pbi.dim ? ' dim' : '') + '" title="' + escHtml(_pbi.title) + '">' + escHtml(_pbi.short) + '</span>' : '';
  // wish-acc37841 · 项目药丸：这条对话挂在哪个外部项目下
  // （没挂就不显示 —— 不给存量对话添一个灰标，那是噪音）
  const _proj = s.project_id || (sessionMetaCache[s.session_id] || {}).project_id || '';
  const projBadge = _proj ? '<span class="sp-project" data-pjproj="' + escHtml(_proj) + '" title="' + escHtml('挂在项目「' + _proj + '」下 · 点一下看详情') + '"><i class="ri-folder-3-fill"></i>' + escHtml(_proj) + '</span>' : '';
  name.innerHTML = pinIcon + archIcon + runIcon + wkIcon + '<span class="sp-label">' + escHtml(aliasFor(s.session_id)) + '</span>' + profBadge + projBadge;
  // 药丸得自己拦一下：外层 div.onclick 是「切到这场会话」，不拦的话点药丸也把人切走了
  const _pjEl = name.querySelector('[data-pjproj]');
  if (_pjEl) {
    _pjEl.addEventListener('click', (ev) => {
      ev.stopPropagation();
      ev.preventDefault();
      if (typeof window.pjOpenSheet === 'function') window.pjOpenSheet(_pjEl.getAttribute('data-pjproj'));
    });
  }

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

// ══ [3] 抽屉列表（工作台） ══
async function refreshSessionList(reset = true) {
  if (reset) {
    _sessionListOffset = 0;
    _drawerLastGroupKey = null;
    $sessionList.innerHTML = '<div class="drawer-empty">加载中…</div>';
  }
  // 关掉可能开着的菜单
  closeSessionMenu();
  await _loadWakeups();   // wish-1b00ca00 · 拉一份"哪些会话在等唤醒"（拿不到不影响列表）
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
        last_think_cfg: s.last_think_cfg || {},   // wish-00490c86 · 思考开关跟对话实例走（免切会话多一次 fetch）
        last_tool_profile: s.last_tool_profile || null,   // wish-16fa5930 · 档位跟对话走（列表徽标数据源）
      };
    }
    if (reset && (!data.sessions || data.sessions.length === 0)) {
      const empty = showArchivedSessions
        ? '归档区是空的 · 已归档的话题会跑这儿'
        : '还没有话题 · 点 + 新话题开始';
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
      btn.textContent = '加载更早的话题';
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

function renderArchivedToggle() {
  let el = document.getElementById('archivedToggle');
  if (!el) {
    el = document.createElement('div');
    el.id = 'archivedToggle';
    el.className = 'archived-toggle';
    $sessionList.parentElement.appendChild(el);
  }
  if (showArchivedSessions) {
    el.innerHTML = `<button onclick="toggleArchivedView()">← 返回话题列表</button>`;
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

// ══ [4] 专注版列表 ══
// 左侧会话清单 (复用 /sessions API + buildSessionRow · 与抽屉同源 · 排序交给服务端 mtime desc)
async function renderCompactSessions(reset = true) {
  const list = document.getElementById('compactSessionList');
  if (!list) return;
  if (!token) { list.innerHTML = '<div class="docs-view-empty">还没填 token</div>'; return; }
  // 无快照缓存 · 直接拉最新 (排序实时性 > 加载微快) · 保留旧 DOM 顶住不闪 loading
  if (reset) _compactSessionOffset = 0;
  await _loadWakeups();   // wish-1b00ca00 · 等唤醒标记（拿不到不影响列表）
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
        last_think_cfg: s.last_think_cfg || {},   // wish-00490c86 · 思考开关跟对话实例走（免切会话多一次 fetch）
        last_tool_profile: s.last_tool_profile || null,   // wish-16fa5930 · 档位跟对话走（列表徽标数据源）
      };
    }
    if (reset) { list.innerHTML = ''; _compactLastGroupKey = null; }
    // 分组渲染 (今天/昨天/本周/本月/更早) · 分页续接时沿用上一页的组 key · 跨页不重复插标题
    let gk = _compactLastGroupKey;
    for (const s of data.sessions) gk = _appendSessionGrouped(list, s, gk);
    _compactLastGroupKey = gk;
    if (typeof _renderCompactFoot === 'function') _renderCompactFoot(list, data.sessions);
    _startSessionRunPoll();  // 运行状态轮询 · 专注版列表可见即启动 (也会顺带重排)
  } catch (e) {
    if (reset) list.innerHTML = '<div class="docs-view-empty">网络出错: ' + e.message + '</div>';
  }
}
function loadMoreCompactSessions() { _compactSessionOffset += _COMPACT_PAGE; renderCompactSessions(false); }
// 专注版归档视图切换 (BRO: 工作台有归档入口 · 专注版也该有)
function toggleCompactArchived() {
  _compactShowArchived = !_compactShowArchived;
  renderCompactSessions(true);
}

// ══ [5] 统一刷新口 ══
// 会话元数据变更后统一刷新两个列表 (工作台抽屉 + 专注版) · 改一处四处受益 (rename/pin/archive/delete 共用)
function _refreshSessionLists() {
  refreshSessionList();              // 工作台抽屉
  if (typeof renderCompactSessions === 'function' && !document.getElementById('compactSessionList')?.hidden) {
    renderCompactSessions(true);     // 专注版重拉 (无缓存 · 直接拿最新排序)
  }
}

// ══ [6] 专注版增量补行 ══
// wish-e5043955 · BRO 2026-09-28:「专注模式对话之后，不会出现新的对话卡」
//
// 病根：新话题的 sid 要等**第一句话发出**才在服务端建（点新话题只是本地 tmp-cid）。
//   tmp-cid 阶段列表里当然没它（不是 bug）· 但换成真 sid 后，列表也不一定补 ——
//   因为「重拉列表」只在 开抽屉 / 改名·归档·删除 / 后台消息 这几个时机，
//   而专注模式（body.compact）没有抽屉 → 新卡一直不出现，要等切模式才冒出来。
//
// 修法：不动整表（历史决策：整表重载会闪空白）—— 只**补当前这一行**。
//   已在列表里 → 什么都不做；服务端还没这条 → 静静走开（下一回再补）。
async function _insertCompactRow() {
  const list = document.getElementById('compactSessionList');
  if (!list || !token || !sessionId || String(sessionId).startsWith('tmp-')) return;
  // 已在列表里 → 不重复插
  const sel = (window.CSS && CSS.escape) ? CSS.escape(sessionId) : sessionId;
  if (list.querySelector('.session-item[data-sid="' + sel + '"]')) return;
  try {
    const r = await fetch('/sessions?api_only=true&limit=1', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) return;
    const data = await r.json();
    const s = (data.sessions || []).find(x => x.session_id === sessionId);
    if (!s) return;   // 服务端还没这条（第一句话还没落盘）→ 不硬插
    // 插到「今天」组的第一位 · 没有今天就插最前（新会话本来就是最新）
    const hdr = [].slice.call(list.children).find(
      c => c.classList && c.classList.contains('session-group-header') && c.textContent.trim() === '今天');
    const row = buildSessionRow(s);
    if (hdr) hdr.after(row); else list.prepend(row);
  } catch (e) { /* 静默 · 补行失败绝不影响对话本身 */ }
}
