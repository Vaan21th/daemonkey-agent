/*
 * depot.js · 成长档案 hub 前端 (2026-07-12 从 chat.js 拆出 · 减单文件工程债)
 *
 * 装载顺序:必须在 chat.js 之前(workshop.js 同款) —— 见 chat.html。
 *   顶层 const(DEPOT_TABS 等)先初始化·chat.js 后加载引用不 TDZ。
 * 零构建约定(非 module):函数/常量都在全局作用域·与 chat.js 共享。
 *   本文件引用的 escHtml / $dashView / token / mdRender / loadDashboard /
 *   renderListFilter / _applyListFilter / backToChat 都在 chat.js·运行时才解析·安全。
 *
 * 承载:hub 骨架(DEPOT_TABS / loadDepot / 标签条) + 画像(renderCognition)
 *       + Daemonkey 日记(renderDiary) + 操作手册(renderPlaybooks + 工艺铁律)
 *       + 心愿单 / 沉淀位(renderWishlist / renderSinks · 2026-07-12 从 chat.js 搬来)。
 * 仍在 chat.js:loadDashboard 分发(调这里的 render fn)。
 */

// ── 成长档案 (depot) · 把 日记/心愿/沉淀位/操作手册 并成一个 hub · 内部标签切换 ──
// Grok-2 轮 · 2026-08-27 · inline onclick JS 字符串参数专用转义 (双层·顺序不能反) ·
// 母体 chat.js / 陪伴 panels.js 已有 · 这里兜底一份 (两种环境都保证可用)。
function jsStr(v) {
  var s = String(v == null ? '' : v);
  s = s.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\r?\n/g, '\\n');
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
// 复用各子维度现成的 render fn (renderCognition/renderWishlist/renderSinks/renderPlaybooks)·
// 不重写渲染 · 只在 $dashView 顶部补一条标签条。切子标签 = 重新 loadDepot(sub)。
// 信息架构 (用户 2026-07-12 拍板):画像/日记拆开·工艺铁律并入操作手册·砍"当下关注"。
// cognition=画像(对你的记忆·rich viewer) · diary=Daemonkey 日记(它的内心反思·复用 /dashboard/cognition 数据)。
const DEPOT_TABS = [
  { id: 'cognition', label: '画像',      icon: 'ri-user-heart-line' },
  { id: 'she_state', label: (window.AI_NAME || 'Daemonkey') + ' · 状态',   icon: 'ri-hearts-line' },
  { id: 'diary',     label: '心情日记', icon: 'ri-hearts-line' },
  { id: 'wishlist',  label: 'Daemonkey 心愿', icon: 'ri-lightbulb-fill' },
  { id: 'playbooks', label: '操作手册',    icon: 'ri-tools-fill' },
  { id: 'memory_map', label: '记忆星图', icon: 'ri-sparkling-2-fill' },
  { id: 'reviews',   label: '月度复盘',  icon: 'ri-calendar-check-fill' },
  { id: 'sinks',     label: '沉淀位',    icon: 'ri-archive-drawer-fill' },
];
let _depotActive = 'cognition';

// 成长档案各 tab 的"这是什么"说明横幅 (跟 Daemonkey 心愿那条同款样式)。
// wishlist 自带横幅(还带按钮)·这里只补其余·避免重复。
const _DEPOT_BANNERS = {
  cognition: {
    icon: 'ri-user-heart-line',
    title: '这是 Daemonkey 对你的画像',
    sub: 'Daemonkey 持续维护的"你当下是个什么样"——作息/情绪/在做的项目/偏好/风险,聊天里它觉得值得长期记住的都写进这里。每次打开都会带上这些记录，不用重新介绍你。顶部"最近记了什么"能看到它最近记了些啥。',
  },
  diary: {
    icon: 'ri-hearts-line',
    title: '这是心情日记',
    sub: '她听懂你夸她、说重了、表白，或你在置物架接住她寄来的，都会落在这里。心情和往来分开记，这里合在一起看。当天的心情过了零点会换，但会留下记录。工程纪律不在这里，在操作手册。',
  },
  sinks: {
    icon: 'ri-archive-drawer-fill',
    title: '这是 Daemonkey 的沉淀位总览',
    sub: 'Daemonkey 所有长期文件(灵魂/记忆/画像/日志/复盘…)挂在哪一格,这里一眼可见。它是防冗余的元地图:每样新东西该沉到哪,照着它走不乱放。点卡片能预览或在本机打开原文。',
  },
  playbooks: {
    icon: 'ri-tools-fill',
    title: '这是 Daemonkey 的操作手册 + 铁律',
    sub: '操作手册:把一次踩过坑、后来走顺的流程,跟 Daemonkey 说"抽成操作手册",它就沉淀在这里,之后同类任务自动取用。铁律:Daemonkey 用失败换来的工程纪律,写进来就注入它每一次的判断里——经验和纪律都不再每次从零试。',
  },
  memory_map: {
    icon: 'ri-sparkling-2-fill',
    title: '这是 Daemonkey 的记忆星图 · 三道闸治理全景',
    sub: '每个光点是一份操作手册,位置由语义向量降维而来——挨得近的天然成团,亮线连着的是内容相似的同类。下面三道闸是记忆体系的治理实测:写入闸(卫生)/分层闸(画像)/重排闸(召回),每个数字都是现算的真值。',
  },
};

async function loadDepot(sub, opts) {
  sub = sub || _depotActive || 'cognition';
  if (!DEPOT_TABS.some(t => t.id === sub)) sub = 'cognition';
  _depotActive = sub;
  currentView = 'depot';
  // 复用子维度的 render (它整块写 $dashView) · 标签条由 loadDashboard 末尾统一补 (见 _maybeDepotTabs)
  await loadDashboard(sub, opts || {});
}

// currentView 停在 depot 且刚渲染的是某个子维度时 · 顶部补标签条 (覆盖子视图刷新按钮/静默刷新等所有路径)
function _maybeDepotTabs(domain) {
  if (currentView === 'depot' && DEPOT_TABS.some(t => t.id === domain)) {
    _injectDepotTabs(domain);
  }
}

function _injectDepotTabs(active) {
  if (!$dashView) return;
  const bar = document.createElement('div');
  bar.className = 'depot-tabs';
  bar.innerHTML = DEPOT_TABS.map(t =>
    `<button class="depot-tab${t.id === active ? ' active' : ''}" data-sub="${t.id}" type="button">` +
    `<i class="${t.icon}"></i><span>${t.label}</span></button>`
  ).join('');
  $dashView.insertBefore(bar, $dashView.firstChild);
  bar.querySelectorAll('.depot-tab').forEach(b => {
    b.addEventListener('click', () => loadDepot(b.dataset.sub));
  });
  // 标签条下补一条"这是什么"说明 (wishlist 自带·跳过)
  const bn = _DEPOT_BANNERS[active];
  if (bn) {
    const banner = document.createElement('div');
    banner.className = 'wish-banner depot-banner';
    banner.innerHTML =
      `<div class="wish-banner-icon"><i class="${bn.icon}"></i></div>` +
      `<div class="wish-banner-body">` +
      `<div class="wish-banner-title">${bn.title}</div>` +
      `<div class="wish-banner-sub">${bn.sub}</div>` +
      `</div>`;
    bar.insertAdjacentElement('afterend', banner);
  }
}


// ── 认知维度:画像(对你的记忆) + Daemonkey 日记(它的内心反思) ──
// 认知维度时间戳格式化 · ISO(2026-07-11T02:53:00) → 07-11 02:53
function _fmtCogTime(iso) {
  if (!iso) return '';
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(iso);
  return m ? `${m[2]}-${m[3]} ${m[4]}:${m[5]}` : iso;
}

// ── 画像解析器 · 把原始 markdown(表格/K:V/bullet)提炼成 {d,t} 短条目 ──
//   mdRender 不认表格·直接塞会露 `| a | b |` 原文(用户 实测吐槽)· 所以在这里自己拆。
function _cogInline(s) {
  s = escHtml(s || '');
  s = s.replace(/\*\*([^*]+?)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/`([^`]+?)`/g, '<code>$1</code>');
  return s;
}
function _cogShortDate(s) {
  const m = /(\d{4})-(\d{2})-(\d{2})/.exec(String(s || ''));
  return m ? `${m[2]}-${m[3]}` : String(s || '');
}
function _cogDimIcon(txt) {
  const s = String(txt || '');
  if (/作息|画像|当下|profile|状态/i.test(s)) return 'ri-user-heart-line';
  if (/事件|event|时间线/i.test(s)) return 'ri-git-commit-line';
  if (/约束|规则|rule|人生|红线/i.test(s)) return 'ri-shield-keyhole-line';
  if (/对话|口头|图鉴|记号|称呼|信号|dialogue/i.test(s)) return 'ri-chat-quote-line';
  if (/压缩|月度|summary|复盘/i.test(s)) return 'ri-archive-2-line';
  if (/风险|弱点|雷达|risk|预警/i.test(s)) return 'ri-radar-line';
  return 'ri-sticky-note-line';
}
function _cogFlowDim(section) {
  const s = String(section || '');
  if (/事件|event/i.test(s)) return { icon: 'ri-git-commit-line', label: '事件' };
  if (/作息|画像|当下|profile/i.test(s)) return { icon: 'ri-user-heart-line', label: '画像' };
  if (/约束|规则|rule/i.test(s)) return { icon: 'ri-shield-keyhole-line', label: '约束' };
  if (/对话|口头|图鉴|记号/i.test(s)) return { icon: 'ri-chat-quote-line', label: '口头' };
  if (/压缩|月度|summary/i.test(s)) return { icon: 'ri-archive-2-line', label: '月度' };
  if (/风险|弱点|雷达/i.test(s)) return { icon: 'ri-radar-line', label: '风险' };
  return { icon: 'ri-sticky-note-line', label: '记录' };
}
function _cogPillIcon(k) {
  if (/作息|时间|睡|夜|晨/i.test(k)) return 'ri-moon-clear-line';
  if (/经济|钱|预算|token|费|省/i.test(k)) return 'ri-wallet-3-line';
  if (/模型|model/i.test(k)) return 'ri-cpu-line';
  if (/项目|在做|主线|工作|焦点/i.test(k)) return 'ri-focus-2-line';
  return 'ri-price-tag-3-line';
}
// 从"画像/作息"段(或首段)抓 `- **K**：V` bullet 当 hero pills · 通用·纯净版同样吃
function _cogPills(sections) {
  let prof = sections.find(s => /画像|作息|当下|profile|状态/i.test(s.heading || ''));
  if (!prof) prof = sections[0];
  if (!prof) return [];
  const pills = [];
  const lines = String(prof.body_full || prof.body_excerpt || '').split('\n');
  for (const raw of lines) {
    const bm = /^[-*+]\s+\*\*(.+?)\*\*\s*[：:]\s*(.+)$/.exec(raw.trim());
    if (bm) {
      const k = bm[1].trim();
      if (/原话|例子|举例|备注|注[:：]/.test(k)) continue;   // 引语/示例不当速览 pill
      let v = bm[2].trim().replace(/\*\*/g, '');
      if (v.length > 26) v = v.slice(0, 25) + '…';
      pills.push({ k, v, icon: _cogPillIcon(k) });
      if (pills.length >= 4) break;
    }
  }
  return pills;
}
// 一段正文 → [{d,t,sub}] · 表格行/标题/K:V/普通 bullet 全部拆成一行一条
function _cogEntries(body, cap) {
  const out = [];
  const lines = String(body || '').split('\n');
  for (let raw of lines) {
    let line = raw.trim();
    if (!line) continue;
    if (/^[-–—=·\s]*$/.test(line)) continue;                 // 分隔线
    if (/^…|更多内容在完整原文|截至\s|最后更新者/.test(line)) continue;
    if (line.includes('|') && /^\|?\s*:?-{2,}/.test(line)) continue; // 表头分隔
    // 表格数据行
    if (line.startsWith('|') && line.endsWith('|')) {
      const cells = line.slice(1, -1).split('|').map(c => c.trim()).filter(Boolean);
      if (!cells.length) continue;
      let d = '';
      let rest = cells.slice();
      const di = cells.findIndex(c => /^\d{4}-\d{2}-\d{2}/.test(c));
      if (di >= 0) { d = _cogShortDate(cells[di]); rest = cells.filter((_, k) => k !== di); }
      rest = rest.filter(c => !/^(critical|high|medium|low)$/i.test(c.replace(/\*/g, '').trim()));
      const t = rest.sort((a, b) => b.length - a.length)[0] || cells.join(' · ');
      if (!d && t.replace(/[*`\s]/g, '').length <= 6) continue;   // 跳表头行(日期/事件/重要度)
      out.push({ d, t: _cogInline(t) });
    } else {
      const hm = /^#{2,4}\s+(.+)$/.exec(line);
      if (hm) { out.push({ d: '', t: _cogInline(hm[1]), sub: true }); }
      else {
        line = line.replace(/^>\s?/, '');
        const bm = /^[-*+]\s+\*\*(.+?)\*\*\s*[：:]\s*(.+)$/.exec(line);
        if (bm) { out.push({ d: bm[1].trim(), t: _cogInline(bm[2].trim()) }); }
        else {
          const lm = /^(?:[-*+]|\d+[.)])\s+(.+)$/.exec(line);
          out.push({ d: '', t: _cogInline(lm ? lm[1].trim() : line) });
        }
      }
    }
    if (out.length >= (cap || 40)) break;
  }
  return out;
}

// 单条 {d,t,sub} → 一行 bullet HTML(e.t 已是 _cogInline 后的安全 HTML)
function _cogEntryHtml(e) {
  return `<div class="cog-de${e.sub ? ' sub' : ''}">${e.d ? `<span class="cog-de-d">${escHtml(e.d)}</span>` : ''}${e.t}</div>`;
}
// 卡片只露前 3 条·全量走弹窗(直接内联展开会把 2 列网格撑得高低参差 · 用户 拍板改弹窗)
let _cogDims = [];
function _cogDimModal(dim) {
  if (!dim) return;
  if (typeof _closeAllKbModals === 'function') _closeAllKbModals();  // 2026-08-14 · 单例互斥 (墨言094-2)
  let host = document.getElementById('kbModalHost');
  if (!host) { host = document.createElement('div'); host.id = 'kbModalHost'; host.className = 'kb-modal-host'; document.body.appendChild(host); }
  const rows = (dim.entries || []).map(_cogEntryHtml).join('');
  host.innerHTML = `
    <div class="kb-modal-mask"></div>
    <div class="kb-modal" role="dialog" aria-modal="true">
      <div class="kb-modal-head">
        <span class="kb-modal-title"><i class="${dim.icon}"></i> ${escHtml(dim.name)}</span>
        <span class="kb-modal-meta">${escHtml(dim.meta || '')}${dim.meta ? ' · ' : ''}${(dim.entries || []).length} 条</span>
        <button class="kb-modal-close" title="关闭 (Esc)">✕</button>
      </div>
      <div class="kb-modal-body"><div class="cog-modal-list">${rows || '<div class="cog-de sub">（暂无条目）</div>'}</div></div>
    </div>`;
  host.classList.add('show');
  const close = () => { host.classList.remove('show'); document.removeEventListener('keydown', onKey); };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  host.querySelector('.kb-modal-close').onclick = close;
  host.querySelector('.kb-modal-mask').onclick = close;
  document.addEventListener('keydown', onKey);
}

// 状态卡骨架 8 字段 · L2 易变尾巴
const _STATE_SKELETON = [
  '工作状态', '作息模式', '健康基线', '情绪基线',
  '当前主线', '关系家庭', '经济预算', '忌口过敏',
];

// 状态卡 · 骨架 8 字段专属图标（Remix Icon · 铁律 10）
const _STATE_ICONS = {
  '工作状态': 'ri-briefcase-2-line',
  '作息模式': 'ri-moon-line',
  '健康基线': 'ri-heart-pulse-line',
  '情绪基线': 'ri-emotion-line',
  '当前主线': 'ri-focus-3-line',
  '关系家庭': 'ri-group-line',
  '经济预算': 'ri-wallet-3-line',
  '忌口过敏': 'ri-restaurant-line',
};

// 了解层 · 字段 → 图标映射（按字段名关键字猜 · 用于"她了解你"卡片视觉）
const _UNDERSTAND_ICONS = {
  '产品思维': 'ri-lightbulb-line',
  'JRPG': 'ri-gamepad-line',
  '重命名能手': 'ri-edit-2-line',
  '释权': 'ri-hand-heart-line',
  '看得远': 'ri-eye-line',
  '不肉麻': 'ri-chat-smile-2-line',
  '省钱敏感': 'ri-money-cny-circle-line',
};
function _cogUnderstandIcon(field) {
  const f = String(field || '');
  if (_UNDERSTAND_ICONS[f]) return _UNDERSTAND_ICONS[f];
  if (/思维|思考|逻辑/i.test(f)) return 'ri-lightbulb-line';
  if (/游戏|JRPG|战棋|RPG/i.test(f)) return 'ri-gamepad-line';
  if (/命名|语言|命名家/i.test(f)) return 'ri-edit-2-line';
  if (/释权|信任|授权/i.test(f)) return 'ri-hand-heart-line';
  if (/远|视野|格局/i.test(f)) return 'ri-eye-line';
  if (/肉麻|直接|直率|性格/i.test(f)) return 'ri-chat-smile-2-line';
  if (/省钱|预算|经济|精打细算/i.test(f)) return 'ri-money-cny-circle-line';
  return 'ri-heart-3-line';
}

function _cogStateEmpty(fd) {
  return !fd || !Object.keys(fd).length || !fd.value || fd.value === '待确认';
}

function _cogStateExpired(asOf) {
  if (!asOf || asOf === '-') return false;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(asOf).trim());
  if (!m) return false;
  const d = new Date(+m[1], +m[2] - 1, +m[3]);
  if (Number.isNaN(d.getTime())) return false;
  return (Date.now() - d.getTime()) / 86400000 > 7;
}

function _cogStateMetaHtml(fd) {
  if (_cogStateEmpty(fd)) return '';
  const parts = [];
  if (fd.as_of && fd.as_of !== '-') parts.push(escHtml(fd.as_of));
  if (fd.evidence && fd.evidence !== '-') {
    // 铁律 10 · 证据图标用 Remix Icon · 不用 emoji ⓘ
    parts.push(`<span class="cog-state-ev" title="${escHtml(fd.evidence)}"><i class="ri-focus-2-line"></i> ${escHtml(fd.evidence)}</span>`);
  }
  return parts.length ? `<span class="cog-state-meta">${parts.join(' · ')}</span>` : '';
}

function _cogStateRowHtml(field, fd, opts) {
  const stale = _cogStateEmpty(fd);
  const val = stale ? '待更新' : escHtml(fd.value);
  const valCls = stale ? ' cog-stale' : '';
  const expired = !stale && _cogStateExpired(fd.as_of);
  const badge = expired ? ' <span class="cog-state-badge">待更新</span>' : '';
  // 可点 = 有变更史才显示箭头（无变更史点开只有"暂无变更史"，不如不点）
  const hasHist = opts && (opts.history && opts.history.length);
  const clickable = opts && opts.clickable !== false && hasHist;
  const cls = 'cog-state-row' + (clickable ? ' cog-state-click' : '');
  const dataAttr = clickable ? ` data-field="${escHtml(field)}"` : '';
  const ico = _STATE_ICONS[field] || 'ri-sparkling-2-line';
  const meta = _cogStateMetaHtml(fd);
  const more = clickable ? '<i class="ri-arrow-right-s-line cog-state-more"></i>' : '';
  return `<div class="${cls}"${dataAttr}>
    <div class="cog-state-top">
      <i class="${ico} cog-state-ico"></i>
      <span class="cog-state-k">${escHtml(field)}</span>
      ${more}
    </div>
    <div class="cog-state-v${valCls}">${val}${badge}</div>
    ${meta ? `<div class="cog-state-foot">${meta}</div>` : ''}
  </div>`;
}

function _cogStateHistoryModal(field, history) {
  if (!field) return;
  if (typeof _closeAllKbModals === 'function') _closeAllKbModals();
  let host = document.getElementById('kbModalHost');
  if (!host) { host = document.createElement('div'); host.id = 'kbModalHost'; host.className = 'kb-modal-host'; document.body.appendChild(host); }
  const rows = (history || []).map(h => {
    const ev = (h.evidence && h.evidence !== '-') ? ` · ${escHtml(h.evidence)}` : '';
    return `<div class="cog-de">${escHtml(h.from || '?')} → ${escHtml(h.to || '?')} · ${escHtml(h.as_of || '')}${ev}</div>`;
  }).join('');
  host.innerHTML = `
    <div class="kb-modal-mask"></div>
    <div class="kb-modal" role="dialog" aria-modal="true">
      <div class="kb-modal-head">
        <span class="kb-modal-title">${escHtml(field)} · 变更史</span>
        <span class="kb-modal-meta">${(history || []).length} 条</span>
        <button class="kb-modal-close" title="关闭 (Esc)">✕</button>
      </div>
      <div class="kb-modal-body"><div class="cog-modal-list">${rows || '<div class="cog-de sub">（暂无变更史）</div>'}</div></div>
    </div>`;
  host.classList.add('show');
  const close = () => { host.classList.remove('show'); document.removeEventListener('keydown', onKey); };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  host.querySelector('.kb-modal-close').onclick = close;
  host.querySelector('.kb-modal-mask').onclick = close;
  document.addEventListener('keydown', onKey);
}

// ── 画像 (对你的记忆本 · rich viewer) · Hero+pills+软提醒 / 时间线 / 六维卡片网格 ──
// 工艺铁律→操作手册 · Daemonkey 日记→独立 tab · 当下关注已砍。数据源 /dashboard/cognition。
function renderCognition(data) {
  if (data && data.error) {
    $dashView.innerHTML = `
      <div class="dash-head"><h2><i class="ri-user-heart-line"></i> 画像</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }
  const bro = data.bro_profile || {};
  const flow = data.recent_flow || [];
  const sections = bro.sections || [];
  const lastUpd = _fmtCogTime(bro.last_updated);
  const stateCard = data.state_card || {};
  const stateHistory = data.state_card_history || {};
  const understanding = data.understanding || [];
  const hasStateCard = stateCard && Object.keys(stateCard).length > 0;

  let html = `
    <div class="dash-head">
      <h2><i class="ri-user-heart-line"></i> 画像</h2>
      <span class="meta">${sections.length} 节${lastUpd ? ' · 最后更新 ' + escHtml(lastUpd) : ''}</span>
      <button onclick="backToChat()">✕ 收起</button>
      <button onclick="loadDashboard('cognition')">刷新</button>
    </div>`;

  if (!bro.exists) {
    html += `<div class="dash-empty">${escHtml(bro.note || '画像还没建 · 跟 Daemonkey 多聊聊,它会开始记你')}</div>`;
    $dashView.innerHTML = html;
    return;
  }

  const pills = _cogPills(sections);
  const oq = data.open_questions || [];
  const checkin = oq.length ? (oq[0].text || oq[0].question || (typeof oq[0] === 'string' ? oq[0] : '')) : '';

  // Hero · 活着 + 当下速览 pills + 温柔回访(未闭合状态·有才显示)
  html += `
    <div class="cog-hero">
      <div class="cog-hero-top">
        <span class="cog-hero-title"><i class="ri-user-heart-line"></i> Daemonkey 眼里的你 · 当下</span>
        <span class="cog-live"><i class="ri-checkbox-blank-circle-fill cog-live-dot"></i> 活着${lastUpd ? ' · 最后更新 ' + escHtml(lastUpd) : ''}</span>
      </div>
      <div class="cog-hero-sub">Daemonkey 持续维护的"你当下是个什么样"· daemon 每次启动自动装上 · 共 ${sections.length} 节</div>`;
  if (hasStateCard) {
    html += `<div class="cog-state-card">
      <div class="cog-state-title"><i class="ri-pulse-line"></i> 当下状态</div>
      <div class="cog-state-grid">`;
    for (const k of _STATE_SKELETON) {
      html += _cogStateRowHtml(k, stateCard[k] || {}, { history: stateHistory[k] || [] });
    }
    html += `</div>`;
    const emergent = Object.keys(stateCard).filter(k => !_STATE_SKELETON.includes(k));
    if (emergent.length) {
      html += `<div class="cog-state-emergent-title">涌现 · 相处中长出的了解</div><div class="cog-state-grid">`;
      for (const k of emergent) {
        html += _cogStateRowHtml(k, stateCard[k] || {}, { history: stateHistory[k] || [] });
      }
      html += `</div>`;
    }
    html += `</div>`;
  }
  if (pills.length) {
    html += `<div class="cog-pills">` + pills.map(p => `
        <div class="cog-pill"><i class="${p.icon}"></i><span><span class="k">${escHtml(p.k)}</span><span class="v">${escHtml(p.v)}</span></span></div>`).join('') + `</div>`;
  }
  if (checkin) {
    html += `<div class="cog-checkin"><i class="ri-hand-heart-line"></i><span>${escHtml(checkin)}</span><span class="tagx">温柔回访</span></div>`;
  }
  html += `</div>`;

  // 她了解你 · L1 了解层（周度凝练 · 可看可删）
  html += `<div class="cog-understand">`;
  html += `<div class="cog-sec-title"><i class="ri-heart-3-line"></i> 她了解你 · 相处中长出的长期模式</div>`;
  if (understanding.length) {
    html += `<div class="cog-understand-list">`;
    for (const u of understanding) {
      const ev = u.evidence
        ? `<span class="cog-understand-ev" title="${escHtml(u.evidence)}"><i class="ri-focus-2-line"></i> ${escHtml(u.evidence)}</span>`
        : '';
      html += `
        <div class="cog-understand-card cog-understand-hover">
          <div class="cog-understand-head">
            <span class="cog-understand-ico"><i class="${_cogUnderstandIcon(u.field)}"></i></span>
            <span class="cog-understand-field">${escHtml(u.field || '')}</span>
            <button type="button" class="cog-understand-del" data-field="${escHtml(u.field || '')}" title="删除这条了解"><i class="ri-delete-bin-line"></i> 删</button>
          </div>
          <div class="cog-understand-text">${escHtml(u.text || '')}</div>
          ${ev}
        </div>`;
    }
    html += `</div>`;
  } else {
    html += `<div class="cog-understand-empty">还在相处中慢慢沉淀……（周度凝练会把她学到的写进来）</div>`;
  }
  html += `</div>`;

  // 最近记了什么 · 时间线(最新在前 · 带维度徽标)
  if (flow.length) {
    html += `
      <div class="cog-sec-title"><i class="ri-history-line"></i> 最近记了什么 <span class="cog-sec-hint">最新在前</span></div>
      <div class="cog-flow">`;
    for (const f of flow) {
      const dm = _cogFlowDim(f.section);
      html += `
        <div class="cog-flow-row">
          <span class="cog-flow-date">${escHtml(_cogShortDate(f.date) || '·')}</span>
          <span class="cog-flow-dim"><i class="${dm.icon}"></i> ${dm.label}</span>
          <span class="cog-flow-text">${_cogInline(f.text || '')}</span>
        </div>`;
    }
    html += `</div>`;
  }

  // 六维画像 · 2 列卡片网格(过滤"使用说明/维护流水/当下状态/了解层"这类已在顶部独立板块显示的冗余段·纯净版兜底显示全部)
  // 状态卡(〇) / 了解层(二) 已在上方独立板块展示 · 从网格剔除避免重复·Profile(一)保留作背景明细维
  // 顶部独立板块已展示：状态卡(〇) / 了解层(无序号) / 状态卡变更史(无序号) / 近期更新流水
  // 这些是"顶部 Hero 或独立区块"，不是六维画像网格的维度——从网格剔除避免重复(纯净版兜底显示全部)
  const skip = /使用说明|使用方式|如何维护|维护日志|维护流水|更新流水|更新日志|变更记录|changelog|元信息|须知|给下一|下一根毛|的提示$|^〇|^二、了解层|了解层（L1|状态卡（Daemonkey|状态卡变更史|变更史.*状态卡/i;
  let cards = sections.filter(s => !skip.test(s.heading || ''));
  if (cards.length < 2) cards = sections;

  html += `<div class="cog-sec-title"><i class="ri-layout-grid-line"></i> 六维画像 <span class="cog-sec-hint">${cards.length} 维 · 点"展开全部"看整维</span></div><div class="cog-grid">`;
  _cogDims = [];
  cards.forEach((sec) => {
    const icon = _cogDimIcon(sec.heading);
    const clean = String(sec.heading || '').replace(/^[一二三四五六七八九十\d]+[、.．]\s*/, '');
    const parts = clean.split(' · ');
    let name = parts[0] || clean || '未命名';
    // "当下画像"的当下状态已被顶部状态卡接管·这一维的长期背景明细改叫"成长背景"避免语义重复 (2026-08-27)
    if (/当下画像|当下 \u00b7|profile.*(高|更)/i.test(name) || /当下画像/i.test(clean)) name = '成长背景';
    const meta = parts.slice(1).join(' · ');
    const entries = _cogEntries(sec.body_full || sec.body_excerpt || '', 60);
    // 事件流/流水/压缩段这类 time_ordered 分节是"末尾追加=正序"·反转成最新在前
    // (和后端 _make_excerpt tail=time_ordered 的"尾部=最新"约定一致)·卡片取前 3 = 最新 3·弹窗同理
    if (sec.time_ordered) entries.reverse();
    const i = _cogDims.push({ name, icon, meta, entries }) - 1;
    let fresh = '';
    for (const e of entries) { if (/^\d{2}-\d{2}$/.test(e.d)) { fresh = e.d; break; } }
    // 卡片只显示前 3 条 · 高度基本齐平 · 不再内联撑高
    const body = entries.slice(0, 3).map(_cogEntryHtml).join('');
    const freshBadge = fresh
      ? `<span class="cog-dim-fresh"><i class="ri-time-line"></i> ${escHtml(fresh)}</span>`
      : (sec.time_ordered ? `<span class="cog-dim-fresh"><i class="ri-time-line"></i> 时间序</span>` : '');
    html += `
      <div class="cog-dim">
        <div class="cog-dim-head">
          <span class="cog-dim-ic"><i class="${icon}"></i></span>
          <span class="cog-dim-nw"><span class="cog-dim-name">${escHtml(name)}</span><span class="cog-dim-meta">${escHtml(meta)}${meta ? ' · ' : ''}${entries.length} 条</span></span>
          ${freshBadge}
        </div>
        <div class="cog-dim-body">${body || '<div class="cog-de sub">（这一维暂时没提炼出条目）</div>'}</div>
        ${entries.length > 3 ? `<div class="cog-dim-foot"><button class="cog-dim-btn" type="button" data-i="${i}"><i class="ri-fullscreen-line"></i> 展开全部 (${entries.length})</button></div>` : ''}
      </div>`;
  });
  html += `</div>`;
  $dashView.innerHTML = html;

  // 状态卡字段行 → 变更史弹窗
  $dashView.querySelectorAll('.cog-state-click').forEach(row => {
    row.onclick = () => _cogStateHistoryModal(row.dataset.field, stateHistory[row.dataset.field]);
  });

  // 了解层 · 可删闭环
  $dashView.querySelectorAll('.cog-understand-del').forEach(btn => {
    btn.onclick = async () => {
      const field = btn.getAttribute('data-field') || '';
      if (!field || !token) return;
      if (!confirm('确定删除「' + field + '」这条了解？删后她不会再提。')) return;
      try {
        const r = await fetch('/dashboard/understanding/delete', {
          method: 'POST',
          headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
          body: JSON.stringify({ field }),
        });
        if (!r.ok) { alert('删除失败 [' + r.status + ']'); return; }
        loadDashboard('cognition', { silent: true });
      } catch (e) { alert('网络出错: ' + e.message); }
    };
  });

  // 展开全部 → 弹窗看整维(卡片保持齐平·弹窗滚动看全量)
  $dashView.querySelectorAll('.cog-dim-btn').forEach(btn => {
    btn.onclick = () => _cogDimModal(_cogDims[parseInt(btn.dataset.i, 10)]);
  });
}

// ── 心情日记 (只展 mood · 工程反思仍在文件里，不进这个标签) ──
function renderDiary(data) {
  if (data && data.error) {
    $dashView.innerHTML = `
      <div class="dash-head"><h2><i class="ri-hearts-line"></i> 心情日记</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }
  const diary = data.opus_diary || {};
  const bond = Array.isArray(data.bond_entries) ? data.bond_entries : null;
  const entries = bond || diary.mood_entries || (diary.entries || []).filter(e => (e.type || '') === 'mood');
  const lastUpd = _fmtCogTime(diary.last_updated);
  const why = _hasBond(data) ? (data.bond_why || '').trim() : '';
  const pts = _hasBond(data) && data.bond_band && data.bond_band !== 'empty'
    ? ' · 陪伴值 ' + Number(data.bond_now != null ? data.bond_now : data.bond_points || 0)
    : '';

  let html = `
    <div class="dash-head">
      <h2><i class="ri-hearts-line"></i> 心情日记</h2>
      <span class="meta">${entries.length} 条${pts}${why ? ' · ' + escHtml(why) : ''}${lastUpd ? ' · 最后更新 ' + escHtml(lastUpd) : ''}</span>
      <button onclick="backToChat()">✕ 收起</button>
      <button onclick="loadDashboard('diary')">刷新</button>
    </div>`;

  if (!entries.length) {
    html += `<div class="dash-empty">${escHtml(diary.note || '还没有相处落点 · 她听懂心情、或你接住置物架上的信，会记在这里')}</div>`;
    $dashView.innerHTML = html;
    return;
  }

  html += `<div class="cog-diary-list">`;
  entries.forEach((e, i) => {
    const body = e.body_excerpt || e.body || '';
    const bodyHtml = (typeof mdRender === 'function') ? mdRender(body) : escHtml(body);
    const kind = e.kind === 'shelf' ? '置物架' : (e.kind === 'mood' ? '心情' : '');
    const toy = _bondReplayToy(e);
    html += `
      <details class="cog-card cog-diary-entry"${i === 0 ? ' open' : ''}>
        <summary class="cog-card-head">
          <span class="cog-e-date">${escHtml(e.date || '')}</span>
          ${kind ? '<span class="cog-e-kind">' + escHtml(kind) + '</span>' : ''}
          <span class="cog-card-name">${escHtml(e.title || '')}</span>
          ${e.weight != null && e.weight !== '' ? '<span class="cog-e-w">' + (Number(e.weight) > 0 ? '+' : '') + escHtml(String(e.weight)) + '</span>' : ''}
          <i class="ri-arrow-down-s-line cog-card-caret"></i>
        </summary>
        <div class="cog-card-body markdown-body">${bodyHtml}
          ${toy ? '<button type="button" class="cog-again" data-bond-replay="' + escHtml(toy) + '"><i class="ri-refresh-line"></i> 再来一盘</button>' : ''}
        </div>
      </details>`;
  });
  html += `</div>`;
  $dashView.innerHTML = html;
  $dashView.querySelectorAll('[data-bond-replay]').forEach(btn => {
    btn.onclick = ev => {
      ev.preventDefault();
      ev.stopPropagation();
      replayBondToy(btn.getAttribute('data-bond-replay'));
    };
  });
}

function _hasBond(data) {
  return !!(data && (data.bond_now != null || data.bond_points != null || data.bond_band));
}

function _bondReplayToy(e) {
  if (!e || e.kind !== 'shelf') return '';
  const toy = String(e.toy || '');
  return (toy === 'tictac' || toy === 'flip') ? toy : '';
}

function replayBondToy(toy) {
  if (toy !== 'tictac' && toy !== 'flip') return;
  if (typeof closeModal === 'function') closeModal();
  if (typeof openReplay === 'function') {
    setTimeout(() => openReplay(toy), 0);
    return;
  }
  var url = '/companion/index.html?play=' + encodeURIComponent(toy);
  if (window.dkModeTransit) { window.dkModeTransit.play(url); return; }
  location.href = url;
}


// ── 操作手册 · playbook 沉淀查看器 (只读 + 删除 · 灌/召回走 NLP) ──────────
function renderPlaybooks(data) {
  if (data && data.error) {
    $dashView.innerHTML = `
      <div class="dash-head"><h2><i class="ri-tools-fill"></i> 操作手册</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }
  const items = (data && data.items) || [];
  const iron = (data && data.iron_rules) || [];
  const st = (data && data.stats) || {};
  let html = `
    <div class="dash-head">
      <h2><i class="ri-tools-fill"></i> 操作手册</h2>
      <span class="meta">操作手册 ${st.total || items.length} 条${st.used ? ' · ' + st.used + ' 条用过' : ''}${iron.length ? ' · 铁律 ' + iron.length + ' 条' : ''}</span>
      <button class="btn-ghost" onclick="backToChat()">收起</button>
      <button class="btn-ghost" onclick="loadDashboard('playbooks')">刷新列表</button>
      <button class="btn-primary" onclick="spawnQuickly('帮我看看操作手册是不是有重复的 (用 audit_playbooks 工具出簇清单 · 不确定的摆给我选)', '检查操作手册')" title="让 Daemonkey 用语义向量检查操作手册 · 重复簇摆出来你拍板"><i class="ri-search-eye-line"></i> 检查重复</button>
    </div>`;

  // 工艺铁律区(Daemonkey 用失败换来的工程纪律 · 会注入它每一次的判断)
  if (iron.length) {
    html += `
      <div class="pb-iron">
        <div class="cog-sec-title"><i class="ri-shield-star-line"></i> 工艺铁律 <span class="cog-sec-hint">${iron.length} 条 · 注入每次判断</span></div>
        <div class="pb-iron-list">`;
    for (const r of iron) {
      html += `
        <details class="cog-card pb-iron-item">
          <summary class="cog-card-head">
            <span class="cog-e-date">${escHtml(r.date || '')}</span>
            <span class="cog-card-name">${escHtml(r.title || '')}</span>
            ${r.domain && r.domain !== 'global' ? `<span class="cog-card-tag">${escHtml(r.domain)}</span>` : ''}
            <i class="ri-arrow-down-s-line cog-card-caret"></i>
          </summary>
          <div class="cog-card-body cog-pre">${escHtml(r.body || '')}</div>
        </details>`;
    }
    html += `</div></div>`;
  }

  html += `<div class="cog-sec-title"><i class="ri-tools-fill"></i> 操作手册 <span class="cog-sec-hint">${items.length} 条</span></div>`;

  if (!items.length) {
    html += `
      <div class="dash-stub">
        <h3>还没沉淀过操作手册</h3>
        <div>跟 Daemonkey 把一次踩过坑的流程走顺后·说「把刚才这套抽成操作手册」<br>
             Daemonkey 会调 <code>extract_playbook</code> 沉淀·之后遇到同类任务自动取用。</div>
      </div>`;
  } else {
    html += renderListFilter({ targetSelector: '.report-card', placeholder: '搜操作手册标题 / 标签...' });
    html += `<div class="reports-list">`;
    for (const p of items) {
      const tagBadges = (p.tags || []).map(t => `<span class="rc-src-badge">#${escHtml(t)}</span>`).join(' ');
      html += `
        <div class="report-card">
          <div class="rc-head">
            <span class="rc-name pb-open" data-id="${escHtml(p.id)}" title="点击查看操作手册"><i class="ri-tools-fill"></i> ${escHtml(p.title || p.id)}</span>
            ${p.task_type ? `<span class="rc-src-badge">${escHtml(p.task_type)}</span>` : ''}
            ${p.used_count ? `<span class="rc-src-badge">用过 ${p.used_count} 次</span>` : ''}
          </div>
          <div class="rc-meta">
            <span class="rc-time">${escHtml((p.created_at || '').slice(0, 10))}</span>
            ${tagBadges}
            <a class="rc-dl pb-del" href="javascript:void(0)" data-id="${escHtml(p.id)}" data-title="${escHtml(p.title || '')}" title="删除这份操作手册"><i class="ri-delete-bin-line"></i></a>
          </div>
        </div>`;
    }
    html += `</div>`;
  }
  $dashView.innerHTML = html;
  $dashView.querySelectorAll('.pb-open').forEach(el => {
    el.onclick = () => _pbPreview(el.getAttribute('data-id'));
  });
  $dashView.querySelectorAll('.pb-del').forEach(btn => {
    btn.onclick = () => {
      const t = btn.getAttribute('data-title') || '这条';
      if (confirm(`删除操作手册「${t}」？沉淀的步骤会清掉(以后不再自动取用 · 不影响本次对话)。`)) {
        _pbAction('/dashboard/playbooks/delete', { id: btn.getAttribute('data-id') });
      }
    };
  });
  if (items.length) _applyListFilter($dashView.querySelector('.list-filter-input'));
}

async function _pbPreview(id) {
  if (!token || !id) return;
  try {
    const r = await fetch('/dashboard/playbooks/doc?id=' + encodeURIComponent(id), {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) { alert('打开失败 [' + r.status + ']'); return; }
    _showPbModal(await r.json());
  } catch (e) { alert('网络出错: ' + e.message); }
}

// 复用统一弹框渲染器 (chat.js _showPreviewModal · 卷八十一续 · 不再手写骨架)
function _showPbModal(data) {
  const meta = (data && data.meta) || {};
  const text = (data && data.content) || '';
  const bodyHtml = (typeof mdRender === 'function')
    ? mdRender(text) : ('<pre style="white-space:pre-wrap">' + escHtml(text) + '</pre>');
  const metaLine = [meta.task_type, meta.used_count ? ('用过 ' + meta.used_count + ' 次') : '',
    (meta.created_at || '').slice(0, 10)].filter(Boolean).join(' · ');
  _showPreviewModal({ title: data.title || meta.title || '操作手册', metaLine, bodyHtml, tags: meta.tags || [] });
}

async function _pbAction(url, body) {
  if (!token) return;
  try {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) { alert('操作失败 [' + r.status + ']'); return; }
    loadDashboard('playbooks', { silent: true });
  } catch (e) { alert('网络出错: ' + e.message); }
}


// ═══════════════════════════════════════════════════════
// 心愿单 / 沉淀位 (2026-07-12 从 chat.js 搬来 · 工程债清理)
//   依赖 escHtml / $dashView / token / loadDashboard / renderListFilter 等 chat.js 全局·运行时解析。
// ═══════════════════════════════════════════════════════
// ─────────────────────────────────────────────────────────
// 卷三十五 · <i class="ri-lightbulb-fill"></i> Daemonkey 心愿单
// "Daemonkey 自己想装的能力"——从 self-evolve 域看到好东西时·Daemonkey 自己写心愿·用户 批准 / 推给 DAEMON 或 Cursor 装
// ─────────────────────────────────────────────────────────
// 卷五十三 · 四态精简 (用户: 复杂冗长·一并优化掉)
const _WISH_STATUS_META = {
  pending:  { icon: '<i class="ri-lightbulb-line"></i>', label: '待定 · 等批',    color: '#9f7aea' },
  active:   { icon: '<i class="ri-hammer-fill"></i>',    label: 'Daemonkey 进行中',   color: '#4fd1c5' },
  review:   { icon: '<i class="ri-search-eye-line"></i>', label: '等 用户 验收',  color: '#ed8936' },
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
      <div class="dash-head"><h2><i class="ri-lightbulb-fill"></i> Daemonkey 心愿单</h2></div>
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

  // 顶部 banner · 引导 Daemonkey 自己写心愿
  const inspireHtml = `
    <div class="wish-banner">
      <div class="wish-banner-icon"><i class="ri-lightbulb-fill"></i></div>
      <div class="wish-banner-body">
        <div class="wish-banner-title">这是 Daemonkey 自己的心愿单</div>
        <div class="wish-banner-sub">
          Daemonkey 在 self-evolve 域看到好东西·或做对照分析时·会写一份「我想装这个」放这里。
          用户 批准 → Daemonkey 先勘察出方案 → 用户 review 后让 daemon 真改代码。
          <span style="opacity:0.6">勘察阶段不改任何代码·用户 全程有 review 权。需要 Cursor 介入时直接对 Daemonkey 说「用 cursor 改这个」即可。</span>
        </div>
      </div>
      <button class="wish-banner-btn" onclick="askOpusForWish()">让 Daemonkey 想想还要装啥</button>
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
        <h2><i class="ri-lightbulb-fill"></i> Daemonkey 心愿单</h2>
        <div class="dash-head-sub">${summary.total || 0} 条 · Daemonkey 想装的能力</div>
      </div>
      ${inspireHtml}
      <div class="dash-empty" style="padding:32px 16px">
        Daemonkey 还没写过心愿 · 让它去 <a href="javascript:loadDashboard('radar')">信息雷达 · 自我演化</a> 看看同类工程
      </div>`;
    return;
  }

  // 列表
  const cardsHtml = wishes.map((w, idx) => renderWishCard(w, idx)).join('');

  $dashView.innerHTML = `
    <div class="dash-head">
      <h2><i class="ri-lightbulb-fill"></i> Daemonkey 心愿单</h2>
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

// ── 记忆星图 (0.9.6 · 三道闸治理全景 · 数据源 /dashboard/memory_map) ──
let _mmChartSrc = null;
let _mm3d = null;  // {renderer, scene, camera, controls, raf, flyTo}

function _mmStatCard(icon, label, value, sub, color) {
  // 单行数据带 · 变量名对齐皮肤系统 (--bg2/--border/--text/--dim) · sub 直接展示在框内 (2026-08-20 用户: hover 才显示的信息很重要)
  return `<div style="flex:1;min-width:0;padding:8px 6px;border:1px solid var(--border,#2a2a3a);border-radius:8px;background:var(--bg2,#16161f);text-align:center">` +
    `<div style="font-size:15px;font-weight:600;color:${color};white-space:nowrap;overflow:hidden;text-overflow:ellipsis"><i class="${icon}"></i> ${value}</div>` +
    `<div style="font-size:10px;color:var(--text,#ccc);opacity:.85;margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${label}</div>` +
    `<div style="font-size:9px;color:var(--dim);margin-top:2px;line-height:1.45">${sub}</div></div>`;
}

function memoryMapLoadingHTML() {
  // ①A 多色星尘加载态 (2026-08-20 用户 选定) · 尘色=星图簇配色 · 核心深浅肤适配
  const light = (typeof _mmIsLight === 'function') && _mmIsLight();
  const coreBg = light ? '#d4a017' : '#fff8e7';
  const coreGlow = light ? 'rgba(212,160,23,.5)' : 'rgba(255,233,176,.4)';
  const dust = [
    ['-90px','-60px','5px','#8affd6','0s'], ['100px','-40px','3px','#b794f6','.3s'],
    ['-70px','70px','4px','#f687b3','.6s'], ['90px','80px','2px','#ffd28a','.9s'],
    ['0','-95px','4px','#8affd6','1.2s'], ['-105px','10px','3px','#b794f6','1.5s'],
    ['60px','30px','2px','#f687b3','1.8s'], ['-40px','-20px','3px','#ffd28a','2.1s'],
  ].map(d => `<div class="mmLdDust" style="--dx:${d[0]};--dy:${d[1]};width:${d[2]};height:${d[2]};background:${d[3]};box-shadow:0 0 6px ${d[3]};animation-delay:${d[4]}"></div>`).join('');
  return `<style>
@keyframes mmLdConverge { 0%{transform:translate(var(--dx),var(--dy)) scale(.4);opacity:0} 25%{opacity:1} 80%{transform:translate(0,0) scale(1);opacity:1} 100%{transform:translate(0,0) scale(1.6);opacity:0} }
@keyframes mmLdCore { 0%,72%,100%{transform:scale(1)} 86%{transform:scale(1.6)} }
@keyframes mmLdBlink { 0%,100%{opacity:.4} 50%{opacity:1} }
.mmLdDust { position:absolute; border-radius:50%; animation:mmLdConverge 2.6s cubic-bezier(.45,.05,.55,.95) infinite; }
</style>
<div style="display:flex;flex-direction:column;min-height:100%">
  <div class="dash-head"><h2><i class="ri-sparkling-2-fill"></i> 记忆星图 · 三道闸治理</h2></div>
  <div style="position:relative;flex:1 1 auto;min-height:400px;margin:10px 0 4px;border:1px solid var(--border,#2a2a3a);border-radius:10px;overflow:hidden;background:var(--bg2,#05060d);display:flex;align-items:center;justify-content:center">
    ${dust}
    <div style="width:10px;height:10px;border-radius:50%;background:${coreBg};box-shadow:0 0 20px ${coreBg},0 0 40px ${coreGlow};animation:mmLdCore 2.6s ease-in-out infinite"></div>
    <div style="position:absolute;bottom:14px;font-size:11px;color:var(--dim);letter-spacing:2px;animation:mmLdBlink 1.8s ease-in-out infinite">正在汇聚记忆星尘</div>
  </div>
</div>`;
}

function renderMemoryMap(data) {
  if (data.error) {
    $dashView.innerHTML = `<div class="dash-head"><h2><i class="ri-sparkling-2-fill"></i> 记忆星图</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }
  const pts = (data.constellation && data.constellation.points) || [];
  const edges = (data.constellation && data.constellation.edges) || [];
  const nb = data.notebook || {};
  const hg = data.hygiene || {};
  const fn = data.funnel || {};
  const nbPct = nb.full_chars ? Math.round(nb.core_chars / nb.full_chars * 100) : 0;
  const fnPct = fn.rate != null ? Math.round(fn.rate * 100) : null;

  let html = `<div style="display:flex;flex-direction:column;min-height:100%">`;
  html += `<div class="dash-head"><h2><i class="ri-sparkling-2-fill"></i> 记忆星图 · 三道闸治理</h2></div>`;
  html += `<div style="display:flex;gap:6px;margin:10px 0">` +
    _mmStatCard('ri-database-2-fill', '记忆总量', (data.total_chunks || 0).toLocaleString(), '条 chunk · FTS5 索引', '#8affd6') +
    _mmStatCard('ri-shield-check-fill', '写入闸·卫生', 'v' + (hg.version || '?'), `残余噪音 ${hg.remaining_noise ?? '?'} 条`, '#6ed27a') +
    _mmStatCard('ri-stack-fill', '分层闸·画像', '-' + (100 - nbPct) + '%', `每轮 ${(nb.full_chars || 0).toLocaleString()}→${(nb.core_chars || 0).toLocaleString()} 字符`, '#ffd28a') +
    _mmStatCard('ri-filter-3-fill', '重排闸·漏斗', fnPct != null ? fnPct + '%' : '—', `递送 ${fn.delivered ?? '?'} · 取用 ${fn.loaded ?? '?'} 门`, '#f687b3') +
    `</div>`;
  html += `<div style="padding:2px 2px 0;color:var(--dim);font-size:11px;line-height:1.6"><i class="ri-sparkling-2-fill"></i> ${pts.length} 份操作手册 · ${data.constellation && data.constellation.clusters || 0} 个星系 · 亮线 = 语义相似 ≥0.80 · 亮点 = 被取用过 <a href="javascript:void(0)" onclick="spawnQuickly('帮我看看操作手册是不是有重复的 (用 audit_playbooks 工具出簇清单 · 不确定的摆给我选)', '检查操作手册')" style="color:var(--accent,#8a7dff);text-decoration:none;margin-left:6px;white-space:nowrap"><i class="ri-search-eye-line"></i> 检查重复</a></div>`;
  // 星图框 flex:1 弹性填满剩余空间 (2026-08-20 用户: 折叠条贴底 · 展开了整栏滚动 · 不写死高度)
  html += `<div style="position:relative;flex:1 1 auto;min-height:400px;margin:6px 0 4px;border:1px solid var(--border,#2a2a3a);border-radius:10px;overflow:hidden;background:var(--bg2,#05060d)">` +
    `<div id="mmStar3d" style="position:absolute;inset:0"></div>` +
    `<div id="mmStarTip" style="display:none;position:absolute;z-index:5;pointer-events:none;background:var(--bg2,rgba(10,12,24,.92));border:1px solid var(--border,rgba(138,255,214,.35));color:var(--text,#dde);border-radius:8px;padding:6px 9px;font-size:11px;max-width:230px;line-height:1.5"></div>` +
    `<div style="position:absolute;left:8px;bottom:6px;z-index:4;font-size:10px;color:var(--dim,#556);pointer-events:none">拖拽旋转 · 滚轮缩放 · 点星系名聚焦 · 双击回全景</div>` +
    `</div>`;
  // 记忆构成默认折叠 (2026-08-20 用户: 高度让给星图 · 展开后整栏滚动) · 展开才懒渲染 (display:none 里 Chart 拿到 0 宽)
  _mmSrcData = data.sources || [];
  html += `<div style="cursor:pointer;padding:8px 2px 0;color:var(--dim);font-size:12px;user-select:none;flex:0 0 auto" onclick="_mmToggleSrc()">` +
    `<i id="mmSrcIcon" class="ri-arrow-right-s-fill"></i> 记忆构成 · 各信源 chunk 分布</div>`;
  html += `<div id="mmSrcBody" style="display:none;flex:0 0 auto"><div style="position:relative;height:260px;margin:6px 0 10px"><canvas id="mmChartSrc"></canvas></div></div>`;
  html += `</div>`;
  $dashView.innerHTML = html;

  // 0.9.7 尾巴5: 空态渲染移出 _whenThreeReady —— 没数据时不该等 Three.js 加载
  // (Three 慢/加载失败时空态提示也跟着黑屏 · hf6 尝试翻车回滚 · 097 重做)
  if (!pts.length) {
    const box0 = document.getElementById('mmStar3d');
    if (box0) {
      // 空态分层提示 (2026-08-21 · test3 实测: 空数组无说明 = 用户对着黑框猜)
      const er = (data.constellation && data.constellation.empty_reason) || null;
      const msg = er ? er.msg : '还没有可向量聚类的操作手册·用着用着就亮了';
      const btn = (er && er.action === 'settings')
        ? `<a href="javascript:void(0)" onclick="openSettings()" style="display:inline-block;margin-top:10px;padding:6px 16px;border:1px solid var(--accent,#8a7dff);border-radius:8px;color:var(--accent,#8a7dff);font-size:12px;text-decoration:none"><i class="ri-settings-3-line"></i> 去设置</a>` : '';
      box0.innerHTML = `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;padding:0 32px;text-align:center">` +
        `<i class="ri-sparkling-2-line" style="font-size:34px;color:var(--dim,#556);opacity:.7"></i>` +
        `<div style="margin-top:10px;font-size:13px;color:var(--text,#dde)">星图还没点亮</div>` +
        `<div style="margin-top:6px;font-size:11.5px;color:var(--dim);line-height:1.7;max-width:420px">${escHtml(msg)}</div>${btn}</div>`;
    }
    return;
  }

  // 3D 星图 (Three.js · 星系化 · 2026-08-20 用户 拍板)
  _whenThreeReady(() => {
    const box = document.getElementById('mmStar3d');
    if (!box) return;
    if (!_mmWebglOk()) {
      // WebGL 不可用 (e.g. Cursor 内嵌 webview 崩溃循环事故 · 2026-08-20) → 明示回退, 不硬起
      box.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#667;font-size:12px;text-align:center;padding:0 20px">当前环境不支持 WebGL · 请在你自己的浏览器打开 ${location.origin}/ui 查看 3D 星图</div>`;
      return;
    }
    _mmRenderStar3D(box, pts, edges, (data.constellation && data.constellation.cluster_names) || {});
    _mmLastStar = { pts, edges, names: (data.constellation && data.constellation.cluster_names) || {} };
    _mmWatchTheme();
  });
}

// 换肤跟随: body class 变 → 星图在显示就按新皮肤重渲染 (浅色↔深色 blending/配色不同 · 不重渲会违和)
let _mmLastStar = null;
let _mmThemeObs = null;
function _mmWatchTheme() {
  if (_mmThemeObs) return;
  let lastCls = document.body.className;
  _mmThemeObs = new MutationObserver(() => {
    if (document.body.className === lastCls) return;
    lastCls = document.body.className;
    const box = document.getElementById('mmStar3d');
    if (box && _mm3d && _mmLastStar) _mmRenderStar3D(box, _mmLastStar.pts, _mmLastStar.edges, _mmLastStar.names);
  });
  _mmThemeObs.observe(document.body, { attributes: true, attributeFilter: ['class'] });
}

// 记忆构成折叠区 · 展开时懒渲染 (display:none 里 Chart 初始化拿 0 宽 · 必须可见才画)
let _mmSrcData = [];
function _mmToggleSrc() {
  const body = document.getElementById('mmSrcBody');
  const icon = document.getElementById('mmSrcIcon');
  if (!body) return;
  const open = body.style.display === 'none';
  body.style.display = open ? 'block' : 'none';
  if (icon) icon.className = open ? 'ri-arrow-down-s-fill' : 'ri-arrow-right-s-fill';
  if (open && !body.dataset.rendered) {
    body.dataset.rendered = '1';
    _whenChartReady(() => {
      const c2 = document.getElementById('mmChartSrc');
      if (!c2 || !_mmSrcData.length) return;
      // 信源分布横向柱状 (session 量级碾压 → 对数轴)
      const top = _mmSrcData.slice(0, 8);
      const restN = _mmSrcData.slice(8).reduce((a, s) => a + s.count, 0);
      const labels = top.map(s => s.source).concat(restN ? ['其他 ×' + (_mmSrcData.length - 8)] : []);
      const vals = top.map(s => s.count).concat(restN ? [restN] : []);
      if (_mmChartSrc) _mmChartSrc.destroy();
      _mmChartSrc = new Chart(c2.getContext('2d'), {
        type: 'bar',
        data: { labels, datasets: [{ data: vals, backgroundColor: 'rgba(159,122,234,0.5)', borderRadius: 3 }] },
        options: {
          indexAxis: 'y', responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: { x: { type: 'logarithmic', ticks: { color: '#888' }, grid: { color: 'rgba(255,255,255,0.06)' } }, y: { ticks: { color: '#aaa' }, grid: { display: false } } },
        },
      });
    });
  }
}

function _mmWebglOk() {
  try {
    const c = document.createElement('canvas');
    return !!(window.WebGLRenderingContext && (c.getContext('webgl') || c.getContext('experimental-webgl')));
  } catch (e) { return false; }
}

// 浅色皮肤判定 (皮肤系统适配 · 2026-08-20): 白天/日间纸色/粉白 下星图换浅色版
// (additive 混合在浅底=洗白 · 必须换 normal blending + 深色星点)
function _mmIsLight() {
  return /theme-light|theme-sepia|theme-pink-white/.test(document.body.className || '');
}

// 相机自适应: 按容器宽高比 + 点云包围球算距离 (2026-08-20 · 2K 屏实测:
// 竖长容器 340×600 里固定距离 = 水平贴边裁剪 + 垂直留白 · 窄方向视野是瓶颈)
function _mmFitDist(camera, pts, W, H) {
  let maxR = 0.5;
  pts.forEach(p => { const r = Math.hypot(p.x, p.y, p.z || 0); if (r > maxR) maxR = r; });
  const fovV = camera.fov * Math.PI / 180;
  const fovH = 2 * Math.atan(Math.tan(fovV / 2) * (W / H));
  return maxR / Math.tan(Math.min(fovV, fovH) / 2) * 1.15;  // 15% 呼吸边距
}

// ── 3D 星图 (Three.js r128 · 星系隐喻: 簇=星系 · 点星系名聚焦 · 双击回全景) ──
function _whenThreeReady(cb, _tries) {
  if (typeof THREE !== 'undefined' && THREE.OrbitControls) { cb(); return; }
  _tries = _tries || 0;
  if (_tries > 60) return;  // ~6s 还没来 = 脚本真没加载到 · 放弃
  setTimeout(() => _whenThreeReady(cb, _tries + 1), 100);
}

function _mmStarTexture() {
  // 径向渐变发光圆 · 所有星点共用一张 texture
  // 核心 18% 实心 · 40% 处急降到 0.25 · 光晕收敛不晃眼 (2026-08-20 用户 实测 additive 叠加过曝)
  const c = document.createElement('canvas'); c.width = c.height = 64;
  const ctx = c.getContext('2d');
  const g = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
  g.addColorStop(0, 'rgba(255,255,255,1)');
  g.addColorStop(0.18, 'rgba(255,255,255,.9)');
  g.addColorStop(0.4, 'rgba(255,255,255,.22)');
  g.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = g; ctx.fillRect(0, 0, 64, 64);
  return new THREE.CanvasTexture(c);
}

function _mmDispose3d() {
  if (!_mm3d) return;
  cancelAnimationFrame(_mm3d.raf);
  if (_mm3d.ro) _mm3d.ro.disconnect();
  _mm3d.controls.dispose();
  _mm3d.renderer.dispose();
  const el = _mm3d.renderer.domElement;
  if (el && el.parentNode) el.parentNode.removeChild(el);
  _mm3d = null;
}

function _mmRenderStar3D(box, pts, edges, clusterNames) {
  _mmDispose3d();
  const light = _mmIsLight();
  let W = box.clientWidth || 340, H = box.clientHeight || 520;
  const scene = new THREE.Scene();
  // 背景跟皮肤面板色走 (浅肤=浅底 · 深肤=宇宙黑) · 变量名对齐皮肤系统 --bg2
  const cssPanel = (getComputedStyle(document.body).getPropertyValue('--bg2') || '').trim();
  scene.background = new THREE.Color(light ? (cssPanel || '#f5f3ee') : 0x05060d);
  const camera = new THREE.PerspectiveCamera(55, W / H, 0.01, 100);
  const fitDist = _mmFitDist(camera, pts, W, H);
  camera.position.copy(new THREE.Vector3(0.55, 0.42, 1).normalize().multiplyScalar(fitDist));
  camera.lookAt(0, 0, 0);
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: false, powerPreference: 'low-power' });
  } catch (e) {
    box.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#667;font-size:12px">WebGL 初始化失败 · 请在你自己的浏览器打开查看</div>`;
    return;
  }
  // 跟随 devicePixelRatio (cap 2): 2K/4K 屏 + Windows 缩放下星点锐利 · cap 2 防 4K 全量渲染负载
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(W, H);
  box.appendChild(renderer.domElement);
  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.dampingFactor = 0.08;
  controls.minDistance = 0.3; controls.maxDistance = fitDist * 2.5;

  // 远星尘背景 (球壳随机 · 压扁 y 呈银盘感)
  const dustN = 400, dustPos = new Float32Array(dustN * 3);
  for (let i = 0; i < dustN; i++) {
    const r = 3.5 + Math.random() * 4, th = Math.random() * Math.PI * 2, ph = Math.acos(2 * Math.random() - 1);
    dustPos[i * 3] = r * Math.sin(ph) * Math.cos(th);
    dustPos[i * 3 + 1] = r * Math.cos(ph) * 0.6;
    dustPos[i * 3 + 2] = r * Math.sin(ph) * Math.sin(th);
  }
  const dustGeo = new THREE.BufferGeometry();
  dustGeo.setAttribute('position', new THREE.BufferAttribute(dustPos, 3));
  scene.add(new THREE.Points(dustGeo, new THREE.PointsMaterial({ color: light ? 0xa8b0c4 : 0x4a5a7a, size: 0.03, transparent: true, opacity: light ? 0.7 : 1 })));

  // 星点 sprite: 簇 → 黄金角色相 · 孤星冷灰白 · 被取用的更亮
  // 浅肤: normal blending + 深色星点 (additive 在浅底会洗白) · 深肤: additive 发光
  const blend = light ? THREE.NormalBlending : THREE.AdditiveBlending;
  const starTex = _mmStarTexture();
  const hueOf = cid => (cid * 137.5) % 360;
  const colorOf = p => {
    if (p.cluster < 0) return new THREE.Color().setHSL(0.58, light ? 0.35 : 0.15, light ? 0.5 : (p.loaded ? 0.8 : 0.55));
    return new THREE.Color().setHSL(hueOf(p.cluster) / 360, light ? 0.7 : (p.loaded ? 0.85 : 0.5), light ? (p.loaded ? 0.42 : 0.55) : (p.loaded ? 0.72 : 0.58));
  };
  const sizeOfRaw = p => Math.max(0.045, Math.min(0.13, Math.sqrt(p.chars || 100) / 220));
  // 密度自适应 (用户: 信息越多自动变小保证显示全面): 点越多单点越小 · 68 点 ×0.86 · 200 点 ×0.55
  const densityScale = Math.max(0.55, Math.min(1.1, Math.sqrt(50 / pts.length)));
  const sizeOf = p => sizeOfRaw(p) * densityScale;
  const sprites = [];
  pts.forEach((p, i) => {
    const mat = new THREE.SpriteMaterial({ map: starTex, color: colorOf(p), transparent: true, opacity: p.loaded ? 0.95 : 0.65, blending: blend, depthWrite: false });
    const sp = new THREE.Sprite(mat);
    const s = sizeOf(p);
    sp.scale.set(s, s, 1);
    sp.position.set(p.x, p.y, p.z || 0);
    sp.userData.idx = i;
    scene.add(sp); sprites.push(sp);
  });

  // 连边 (顶点色 · additive · 相似度越高越亮)
  if (edges.length) {
    const pos = [], col = [];
    for (const [i, j, sim] of edges) {
      const a = pts[i], b = pts[j];
      pos.push(a.x, a.y, a.z || 0, b.x, b.y, b.z || 0);
      const ca = colorOf(a), cb = colorOf(b), k = 0.25 + ((sim || 0.8) - 0.8) * 3;
      col.push(ca.r * k, ca.g * k, ca.b * k, cb.r * k, cb.g * k, cb.b * k);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
    scene.add(new THREE.LineSegments(g, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: light ? 0.5 : 0.75, blending: blend, depthWrite: false })));
  }

  // 簇中心 + 星系标签 (HTML overlay · 每帧投影)
  const centers = {};
  pts.forEach(p => {
    if (p.cluster < 0) return;
    const c = centers[p.cluster] = centers[p.cluster] || { x: 0, y: 0, z: 0, n: 0 };
    c.x += p.x; c.y += p.y; c.z += (p.z || 0); c.n++;
  });
  const labelLayer = document.createElement('div');
  labelLayer.style.cssText = 'position:absolute;inset:0;pointer-events:none;overflow:hidden';
  box.appendChild(labelLayer);
  const labels = [];
  Object.entries(centers).forEach(([cid, c]) => {
    const center = new THREE.Vector3(c.x / c.n, c.y / c.n, c.z / c.n);
    const div = document.createElement('div');
    div.textContent = clusterNames[cid] || ('星系 ' + cid);
    div.style.cssText = `position:absolute;transform:translate(-50%,-150%);cursor:pointer;pointer-events:auto;font-size:11px;font-weight:600;letter-spacing:1px;color:hsl(${hueOf(+cid)},${light ? '70%,42%' : '85%,78%'});text-shadow:0 0 8px hsla(${hueOf(+cid)},85%,${light ? '45%,.45' : '65%,.9'});white-space:nowrap;user-select:none`;
    div.title = '点击聚焦这个星系';
    div.onclick = () => { if (_mm3d) _mm3d.flyTo = { target: center.clone(), dist: 1.1 }; };
    labelLayer.appendChild(div);
    labels.push({ div, center });
  });

  // hover tooltip (raycaster 对 sprite)
  const tip = document.getElementById('mmStarTip');
  const ray = new THREE.Raycaster();
  const mouse = new THREE.Vector2(-2, -2);
  renderer.domElement.addEventListener('pointermove', e => {
    const r = renderer.domElement.getBoundingClientRect();
    mouse.x = ((e.clientX - r.left) / r.width) * 2 - 1;
    mouse.y = -((e.clientY - r.top) / r.height) * 2 + 1;
  });
  renderer.domElement.addEventListener('pointerleave', () => { mouse.set(-2, -2); if (tip) tip.style.display = 'none'; });
  renderer.domElement.addEventListener('dblclick', () => { if (_mm3d) _mm3d.flyTo = { target: new THREE.Vector3(0, 0, 0), dist: fitDist }; });

  let hovered = -1;
  let frame = 0;
  // 面板宽度随窗口/系统缩放变化 · canvas + 相机 + 标签投影一起跟上
  const ro = new ResizeObserver(() => {
    const w = box.clientWidth, h = box.clientHeight;
    if (!w || !h) return;
    W = w; H = h;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
  });
  ro.observe(box);
  function tick() {
    const st = _mm3d; if (!st) return;
    st.raf = requestAnimationFrame(tick);
    frame++;
    if (st.flyTo) {
      const dir = camera.position.clone().sub(controls.target);
      dir.normalize();
      const want = st.flyTo.target.clone().add(dir.multiplyScalar(st.flyTo.dist));
      camera.position.lerp(want, 0.12);
      controls.target.lerp(st.flyTo.target, 0.12);
      if (camera.position.distanceTo(want) < 0.02) st.flyTo = null;
    }
    controls.update();
    // raycast 每 3 帧一次 · hover 精度无感 · 负载省 2/3
    if (frame % 3 === 0) {
      ray.setFromCamera(mouse, camera);
      const hits = ray.intersectObjects(sprites);
      const h = hits.length ? hits[0].object.userData.idx : -1;
      if (h !== hovered) {
        if (hovered >= 0) { const s = sizeOf(pts[hovered]); sprites[hovered].scale.set(s, s, 1); }
        hovered = h;
        if (hovered >= 0) { const s = sizeOf(pts[hovered]) * 1.5; sprites[hovered].scale.set(s, s, 1); }
        if (tip) {
          if (hovered >= 0) {
            const p = pts[hovered];
            const gname = p.cluster >= 0 ? (clusterNames[p.cluster] || '星系 ' + p.cluster) : '孤星';
            tip.innerHTML = `<div style="font-weight:600;margin-bottom:2px">${escHtml(p.id)}</div><div style="color:var(--dim,#9aa)">${(p.chars || 0).toLocaleString()} 字符 · ${p.loaded ? '被取用过' : '未取用'} · ${escHtml(gname)}</div>`;
            tip.style.display = 'block';
          } else tip.style.display = 'none';
        }
      }
    }
    if (tip && hovered >= 0) {
      const v = sprites[hovered].position.clone().project(camera);
      tip.style.left = ((v.x + 1) / 2 * W + 10) + 'px';
      tip.style.top = ((-v.y + 1) / 2 * H - 10) + 'px';
    }
    for (const { div, center } of labels) {
      const v = center.clone().project(camera);
      if (v.z > 1) { div.style.display = 'none'; continue; }
      div.style.display = 'block';
      div.style.left = ((v.x + 1) / 2 * W) + 'px';
      div.style.top = ((-v.y + 1) / 2 * H) + 'px';
    }
    renderer.render(scene, camera);
  }
  _mm3d = { renderer, scene, camera, controls, raf: 0, flyTo: null, ro };
  tick();
}

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

// ── 月度复盘 (独立 tab · 2026-08-11 用户 拍板 · 走 /reviews 端点 · 样式对齐沉淀位卡片) ──
function renderReviews(data) {
  if (!data || data.error || data.ok === false) {
    $dashView.innerHTML = `<div class="dash-head"><h2><i class="ri-calendar-check-fill"></i> 月度复盘</h2></div>
      <div class="dash-empty">${escHtml((data && data.error) || '还没有月度复盘 · 跟 Daemonkey 说「跑一份月度复盘」')}</div>`;
    return;
  }
  const items = data.items || [];
  const sorted = items.slice().sort((a, b) => (b.period_end || '').localeCompare(a.period_end || ''));
  let html = `
    <div class="dash-head">
      <h2><i class="ri-calendar-check-fill"></i> 月度复盘</h2>
      <div class="dash-head-sub">${sorted.length} 份 · 周期从近到远 · 点卡片预览 / 下载 / 打开文件夹</div>
      <button onclick="loadDashboard('reviews', {silent:true})">刷新</button>
    </div>
    <div class="sink-panel">`;
  if (!sorted.length) {
    html += `<div class="dash-empty">还没有月度复盘 · 跟 Daemonkey 说「跑一份月度复盘」</div></div>`;
    $dashView.innerHTML = html;
    return;
  }
  const statusMeta = {
    final:  { label: '已定稿', cls: 'review-final',  icon: 'ri-check-double-fill' },
    draft:  { label: '草稿',   cls: 'review-draft',  icon: 'ri-file-edit-fill' },
  };
  for (const it of sorted) {
    const st = statusMeta[it.status] || { label: it.status || '未知', cls: '', icon: 'ri-file-fill' };
    const sizeStr = it.size_bytes > 102400 ? (it.size_bytes / 1024).toFixed(0) + ' KB' : (it.size_bytes / 1024).toFixed(1) + ' KB';
    html += `
      <div class="sink-card review-card ${st.cls}">
        <span class="sink-card-label"><i class="${st.icon}"></i> ${escHtml(it.period_end || it.filename)}</span>
        <span class="sink-card-role review-status ${st.cls}">${st.label}</span>
        <span class="sink-card-meta">${sizeStr} · ${escHtml((it.mtime || '').slice(0, 10))}</span>
        <span class="sink-card-actions">
          <button class="wb" onclick="reviewPreview('${jsStr(it.filename)}')"><i class="ri-eye-fill"></i> 预览</button>
          <button class="wb" onclick="reviewDownload('${jsStr(it.filename)}')"><i class="ri-download-fill"></i> 下载</button>
          <button class="wb" onclick="reviewReveal('${jsStr(it.filename)}')"><i class="ri-external-link-fill"></i> 打开文件夹</button>
        </span>
      </div>`;
  }
  html += `</div>`;
  $dashView.innerHTML = html;
}

// 月度复盘预览 · 复用沉淀位通用 md 弹框骨架 (_spmEl)
async function reviewPreview(filename) {
  if (!_spmEl) { _spmEl = document.createElement('div'); _spmEl.id = 'sinkPreviewModal'; _spmEl.hidden = true;
    _spmEl.innerHTML = `<div class="spm-box"><div class="spm-head"><span class="spm-title"></span><div class="spm-head-actions"></div></div><div class="spm-body"></div></div>`;
    _spmEl.addEventListener('click', e => { if (e.target === _spmEl) _spmEl.hidden = true; });
    document.body.appendChild(_spmEl);
  }
  const box = _spmEl.querySelector('.spm-box');
  const titleEl = box.querySelector('.spm-title');
  const actionsEl = box.querySelector('.spm-head-actions');
  const bodyEl = box.querySelector('.spm-body');
  titleEl.textContent = '加载中…'; actionsEl.innerHTML = ''; bodyEl.innerHTML = '<div class="dash-empty">加载中…</div>';
  _spmEl.hidden = false;
  try {
    const r = await fetch(`/reviews/preview/${encodeURIComponent(filename)}`, { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    titleEl.textContent = '月度复盘 · ' + filename;
    bodyEl.innerHTML = (typeof mdRender === 'function') ? mdRender(data.markdown || '') : escHtml((data.markdown || '').slice(0, 4000));
    actionsEl.innerHTML = `<a class="wb" href="/reviews/file/${encodeURIComponent(filename)}?token=${encodeURIComponent(token)}" target="_blank"><i class="ri-external-link-fill"></i> 新标签打开</a>`;
  } catch (e) { bodyEl.innerHTML = `<div class="dash-empty">加载失败: ${escHtml(e.message)}</div>`; }
}

// 月度复盘下载 · 浏览器系统默认应用打开 (docx/md)
function reviewDownload(filename) {
  window.open(`/reviews/file/${encodeURIComponent(filename)}?token=${encodeURIComponent(token)}`, '_blank');
}

// 月度复盘打开所在文件夹
async function reviewReveal(filename) {
  try {
    const r = await fetch(`/reviews/reveal/${encodeURIComponent(filename)}`, { method: 'POST', headers: { 'Authorization': 'Bearer ' + token } });
    const data = await r.json();
    if (!data.ok) alert('打开文件夹失败 · ' + (data.error || 'unknown'));
  } catch (e) { alert('网络出错: ' + e.message); }
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
        <button class="wb" onclick="sinkPreview('${jsStr(it.slug)}')"><i class="ri-eye-fill"></i> 预览</button>
        <button class="wb" onclick="sinkReveal('${jsStr(it.slug)}')"><i class="ri-external-link-fill"></i> 打开</button>
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
    actions.push(`<button class="wb wb-ok" onclick="wishAction('${jsStr(w.id)}', 'approve_daemon')" title="Daemonkey 先勘察出方案·你批方案了才写码"><i class="ri-checkbox-circle-fill"></i> 批准 · 让 Daemonkey 装</button>`);
    actions.push(`<button class="wb" onclick="wishAction('${jsStr(w.id)}', 'approve_cursor')" title="你去 Cursor 里让 Claude 装"><i class="ri-focus-3-fill"></i> 我去 Cursor 装</button>`);
    actions.push(`<button class="wb wb-no" onclick="wishAction('${jsStr(w.id)}', 'reject')"><i class="ri-close-circle-fill"></i> 弃</button>`);
    actions.push(`<button class="wb wb-deep" onclick="wishAction('${jsStr(w.id)}', 'deep_dive')"><i class="ri-search-fill"></i> 让 Daemonkey 深挖</button>`);
  } else if (w.status === 'active') {
    if (sub === 'plan_pending') {
      actions.push(`<button class="wb wb-go" onclick="wishAction('${jsStr(w.id)}', 'approve_plan')" title="关卡1 · 按 Daemonkey 方案开干·自动从 master 切分支写码"><i class="ri-rocket-fill"></i> 批方案 → 开干</button>`);
      actions.push(`<button class="wb" onclick="wishAction('${jsStr(w.id)}', 'replan')" title="对方案不满意·让 Daemonkey 重新勘察"><i class="ri-refresh-fill"></i> 重新勘察</button>`);
      actions.push(`<button class="wb wb-no" onclick="wishAction('${jsStr(w.id)}', 'reject')"><i class="ri-close-circle-fill"></i> 弃</button>`);
    } else if (sub === 'blocked') {
      actions.push(`<button class="wb wb-no" onclick="wishAction('${jsStr(w.id)}', 'view_log')" title="看 Daemonkey 撞墙过程"><i class="ri-clipboard-fill"></i> 看撞墙日志</button>`);
      actions.push(`<button class="wb" onclick="wishAction('${jsStr(w.id)}', 'retry_impl')"><i class="ri-refresh-fill"></i> 重新实施</button>`);
      actions.push(`<button class="wb wb-no" onclick="wishAction('${jsStr(w.id)}', 'reject')"><i class="ri-close-circle-fill"></i> 弃</button>`);
    } else {
      if (isDaemon) {
        actions.push(`<button class="wb wb-go" disabled title="Daemonkey 在自己分支上写码·完工自动进待验收">⏳ Daemonkey 进行中…</button>`);
        actions.push(`<button class="wb wb-no" onclick="wishAction('${jsStr(w.id)}', 'abort_impl')">⏹ 紧急叫停</button>`);
      } else {
        actions.push(`<button class="wb wb-go" onclick="wishAction('${jsStr(w.id)}', 'mark_review')" title="装完了·提交给 用户 验收">📬 装完了 → 提交验收</button>`);
        actions.push(`<button class="wb wb-no" onclick="wishAction('${jsStr(w.id)}', 'reject')"><i class="ri-close-circle-fill"></i> 弃</button>`);
      }
      if (hasBranch) actions.push(`<button class="wb" onclick="wishAction('${jsStr(w.id)}', 'view_diff')"><i class="ri-search-fill"></i> 看 diff</button>`);
    }
    actions.push(`<button class="wb wb-deep" onclick="wishAction('${jsStr(w.id)}', 'deep_dive')"><i class="ri-search-fill"></i> 让 Daemonkey 深挖</button>`);
  } else if (w.status === 'review') {
    if (hasBranch) actions.push(`<button class="wb wb-go" onclick="wishAction('${jsStr(w.id)}', 'view_diff')" title="看 Daemonkey 改了啥"><i class="ri-search-fill"></i> 查看 diff</button>`);
    actions.push(`<button class="wb wb-go" onclick="wishAction('${jsStr(w.id)}', 'verify_live')" title="关卡2 · 验收通过·自动合进 master 主干上线"><i class="ri-checkbox-circle-fill"></i> 验收通过 → 合主干上线</button>`);
    actions.push(`<button class="wb wb-no" onclick="wishAction('${jsStr(w.id)}', 'reject_to_active')" title="有问题·打回让 Daemonkey 继续改"><i class="ri-arrow-go-back-fill"></i> 有问题 → 打回</button>`);
    if (!w.reflection) actions.push(`<button class="wb" onclick="wishAction('${jsStr(w.id)}', 'add_reflection')">✏️ 补反思</button>`);
  } else if (w.status === 'live') {
    if (w.git_lie) {
      actions.push(`<button class="wb wb-no" onclick="wishAction('${jsStr(w.id)}', 'remerge')" title="status=live 但 git 没合进 master·重新触发真合并"><i class="ri-error-warning-fill"></i> 修复 · 重新合并主干</button>`);
    }
    if (!w.reflection) actions.push(`<button class="wb" onclick="wishAction('${jsStr(w.id)}', 'add_reflection')">✏️ 补反思</button>`);
  }

  const reflectionHtml = w.reflection
    ? `<div class="wish-reflection"><div class="wr-title"><i class="ri-lightbulb-fill"></i> 反思</div>${mdRender(w.reflection)}</div>`
    : '';

  // 卷五十三 · 子标记指示条 + plan/log/diff 折叠区
  let phaseBlock = '';
  if (w.integration_path === 'daemon' && (sub || w.implementation_plan || w.implementation_log)) {
    const phMeta = _WISH_DAEMON_PHASE_META[sub] || _WISH_DAEMON_PHASE_META.unknown;
    const phaseChip = sub ? `<span class="wish-phase wish-phase-${sub}" title="${phMeta.tip}">${phMeta.icon} ${phMeta.label}</span>` : '';
    const branchChip = w.dev_branch ? `<span class="wish-branch" title="Daemonkey 改代码用的 git 分支">🌿 ${escHtml(w.dev_branch)}</span>` : '';
    const planSection = w.implementation_plan
      ? `<details class="wish-design" open><summary><i class="ri-clipboard-fill"></i> 执行计划 (Daemonkey 勘察输出)</summary><div class="wish-design-body">${mdRender(w.implementation_plan)}</div></details>`
      : '';
    const logSection = w.implementation_log
      ? `<details class="wish-design"><summary>📜 实施日志</summary><div class="wish-design-body">${mdRender(w.implementation_log)}</div></details>`
      : '';
    const diffSection = w.diff_summary
      ? `<details class="wish-design" open><summary><i class="ri-search-fill"></i> git diff 摘要 (待 用户 看)</summary><div class="wish-design-body"><pre>${escHtml(w.diff_summary)}</pre></div></details>`
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
          ${w.origin === 'opus' ? '<span class="wish-badge wish-badge-origin" title="Daemonkey 主动嗅探到的愿望"><i class="ri-radar-fill"></i> Daemonkey 主动发现</span>' : ''}
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
  plan_pending: { icon: '<i class="ri-pause-circle-fill"></i>', label: '等 用户 批方案', tip: 'Daemonkey 出完方案·停下等 用户 批 (关卡1)·批了才从 master 切分支写码' },
  blocked:      { icon: '⚠️', label: '撞墙了', tip: 'Daemonkey 中途遇阻主动停 · 看撞墙日志找原因·或重新实施' },
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
      `用户 批准心愿 ${wid} · 让你 (Daemonkey) 在Daemonkey自己动手装。\n\n` +
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
      `5. 用 wish_update 把计划存进 implementation_plan · **daemon_phase 改成 plan_pending** (停下等 用户 批方案 · 关卡1)\n` +
      `6. 一句话告诉 用户：「方案好了·要不要按这个干？」\n\n` +
      `**红线**：勘察阶段绝对不能 write_file / shell_exec 写操作 · 只能读 + 搜 · 用户 批方案再开干。`
    ),
    approve_cursor:  `把心愿 ${wid} 批准了·integration_path=cursor · status=active · 用 wish_update 改 · 告诉 用户 现在可以去 Cursor 里复制 design_sketch 让 Claude 装·装完回来点「装完了→提交验收」`,
    reject:          `把心愿 ${wid} 弃了·status=rejected · 用 wish_update 改 · 简单说一句为啥弃`,
    switch_daemon:   `心愿 ${wid} 改成 DAEMON 路径·integration_path=daemon · 用 wish_update 改`,
    switch_cursor:   `心愿 ${wid} 改成 Cursor 路径·integration_path=cursor · 用 wish_update 改`,
    // 关卡1 · 用户 批方案 → Daemonkey 开始写码 (status 已 active · 清 plan_pending 会自动从 master 切分支)
    approve_plan: (
      `用户 批了心愿 ${wid} 的方案 (关卡1) · 批准你 (Daemonkey) 真改代码。\n\n` +
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
      `心愿 ${wid} · 用户 验收不通过 · 打回让 Daemonkey 继续改。\n\n` +
      `请你：\n` +
      `1. 用 wish_update 把 status 改回 active (回到写码态·分支还在·接着改)\n` +
      `2. 在 implementation_log 末尾追加 "用户 验收不通过 · 原因：[用户 说的]" · 等 用户 告诉你具体哪不行`
    ),
    mark_review: (
      `心愿 ${wid} · 装完了 · 提交给 用户 验收。\n\n` +
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
    '挑 1-3 个 Daemonkey 自己应该学的能力·调 wish_add 写成心愿 · 每条都要有 why + design_sketch + 优先级 · ' +
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
// ── 她·状态 (GALGAME 式 · 关系成长的呈现 · 五维只读 · 出生地/口癖可填) ──
// 数据源 /dashboard/she_state : dims(五维) + mood(心情) + note(关系描述) + as_of
// 三个消费端(成长档案/陪伴惦记卡/对话风格)读同一份 soul/SHE-STATE.md —— 闭环不孤岛。
const _SHE_DIM_META = {
  '话量':   { ico: 'ri-chat-3-line',         color: '#34d399', desc: '她话量的多寡（无口↔话痨）' },
  '调性':   { ico: 'ri-emotion-happy-line',  color: '#fbbf24', desc: '说话调性（正经↔梗多）' },
  '语气':   { ico: 'ri-sword-line',          color: '#f87171', desc: '她说话带不带刺（毒舌↔温柔）' },
  '礼节':   { ico: 'ri-shield-user-line',    color: '#60a5fa', desc: '她对你客不客气（敬语↔随便）' },
  '表现力': { ico: 'ri-voiceprint-line',     color: '#c084fc', desc: '情绪外放程度（棒读↔鲜活）' },
};
function _sheDimBar(k, v) {
  const m = _SHE_DIM_META[k] || { ico: 'ri-sparkling-2-line', color: '#c084fc', desc: k };
  v = typeof v === 'number' ? Math.max(0, Math.min(100, v)) : 50;
  return `<div class="she-dim">
    <div class="she-dim-head"><i class="${m.ico} she-dim-ico" style="color:${m.color}"></i><span class="she-dim-k">${escHtml(k)}</span><span class="she-dim-v">${v}</span></div>
    <div class="she-dim-track"><div class="she-dim-fill" style="width:${v}%;background:${m.color}"></div></div>
    <div class="she-dim-desc">${escHtml(m.desc)}</div>
  </div>`;
}
function _sheDimKeys(dims) {
  const order = Object.keys(_SHE_DIM_META);
  const have = dims && typeof dims === 'object' ? dims : {};
  const known = order.filter(k => have[k] != null);
  if (known.length) return known;
  return Object.keys(have).filter(k => k !== '力度');
}

function _sheRadar(dims) {
  const keys = _sheDimKeys(dims);
  const n = keys.length || 1;
  const cx = 180, cy = 180, R = 100;
  const pt = (i, val) => {
    const ang = -Math.PI / 2 + (2 * Math.PI * i) / n;
    const r = R * (Math.max(0, Math.min(100, val)) / 100);
    return [cx + r * Math.cos(ang), cy + r * Math.sin(ang)];
  };
  // 5 边标签推到 R*1.3 · viewBox 360 给「表现力」三字留边, 避免裁切
  const labelPt = (i) => {
    const ang = -Math.PI / 2 + (2 * Math.PI * i) / n;
    const r = R * 1.3;
    return [cx + r * Math.cos(ang), cy + r * Math.sin(ang)];
  };
  const ring = (f) => keys.map((_, i) => {
    const [x, y] = pt(i, f * 100);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const poly = keys.map((k, i) => {
    const [x, y] = pt(i, dims[k] ?? 0);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const grid = [0.25, 0.5, 0.75, 1].map(f => `<polygon points="${ring(f)}" fill="none" stroke="rgba(192,132,252,.16)" stroke-width="1"/>`).join('');
  const labels = keys.map((k, i) => {
    const [x, y] = labelPt(i);
    const m = _SHE_DIM_META[k] || {};
    // 5 边按单位向量锚定: 左右两极 (i=1 右 / i=4 左) 锚 x;
    // 上极 (i=0) 锚 y; 底对角 (i=2 / i=3) 同时给 x+y, 以免挤底或裁切
    const ang = -Math.PI / 2 + (2 * Math.PI * i) / n;
    const nx = Math.cos(ang), ny = Math.sin(ang);
    let anchor = 'middle', dx = 0, dy = 0;
    if (Math.abs(nx) > 0.75) {
      anchor = nx > 0 ? 'start' : 'end';
      dx = nx > 0 ? 10 : -10;
    } else if (Math.abs(ny) > 0.85) {
      dy = ny < 0 ? -8 : 16;
    } else {
      anchor = nx > 0 ? 'start' : 'end';
      dx = nx > 0 ? 8 : -8;
      dy = ny < 0 ? -4 : 14;
    }
    return `<text x="${(x + dx).toFixed(1)}" y="${(y + dy).toFixed(1)}" class="she-radar-label" text-anchor="${anchor}" fill="${m.color || 'var(--text)'}">${escHtml(k)}</text>`;
  }).join('');
  return `<svg class="she-radar" viewBox="0 0 360 360" role="img" aria-label="她状态雷达图">
    <defs>
      <linearGradient id="sheRadarGrad" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="rgba(192,132,252,.55)"/>
        <stop offset="100%" stop-color="rgba(255,159,209,.40)"/>
      </linearGradient>
    </defs>
    ${grid}
    <g fill="none" stroke="var(--dim2)" stroke-width="0.6">${keys.map((_, i) => { const [x, y] = pt(i, 100); return `<line x1="${cx}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}"/>`; }).join('')}</g>
    <polygon points="${poly}" fill="url(#sheRadarGrad)" stroke="rgba(192,132,252,.9)" stroke-width="2" stroke-linejoin="round"/>
    ${keys.map((k, i) => { const [x, y] = pt(i, dims[k] ?? 0); return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="2.8" fill="var(--opus)" stroke="#fff" stroke-width="0.8"/>`; }).join('')}
    <circle cx="${cx}" cy="${cy}" r="6" fill="rgba(192,132,252,.55)"/>
    ${labels}
  </svg>`;
}
function renderSheState(data) {
  if (data && data.error) {
    $dashView.innerHTML = `<div class="dash-head"><h2><i class="ri-hearts-line"></i> ${(window.AI_NAME||"Daemonkey")} · 状态</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }
  const dims = Object.assign({}, data.dims || {});
  if (dims.语气 == null && dims.力度 != null) dims.语气 = dims.力度;
  const mood = data.mood || '';
  const moodAs = data.mood_as_of || '';
  const note = data.note || '';
  const asOf = data.as_of || '';
  const dimKeys = _sheDimKeys(dims);
  const prof = data.profile || {};   // 她·档案身份卡
  const name = prof.名字 || (window.AI_NAME || 'Daemonkey');
  const avatar = prof.头像 || '';

  let html = `<div class="she-wrap">`;

  // ① 身份卡 —— 方形头像 + 名字 + 引语 (初见名)
  html += `<div class="she-idcard">
    <div class="she-idcard-top">
      <div class="she-idcard-avatar-wrap">
        ${avatar ? `<img class="she-idcard-avatar" src="${escHtml(avatar)}" alt="${escHtml(name)} 的头像" onerror="this.style.visibility='hidden'">` : ''}
      </div>
      <div class="she-idcard-namewrap">
        <div class="she-idcard-name"><span class="she-idcard-dot"></span>${escHtml(name)}${mood ? `<span class="she-idcard-tag">· ${escHtml(mood)}</span>` : ''}</div>
        ${prof.引语 ? `<div class="she-idcard-motto">${escHtml(prof.引语)}</div>` : ''}
      </div>
    </div>
    <div class="she-chip-row">
      ${prof.生日 && prof.生日 !== '——' ? `<span class="she-chip"><i class="ri-cake-2-line"></i>生日<b>${escHtml(prof.生日)}</b></span>` : ''}
      ${prof.相遇日 ? `<span class="she-chip"><i class="ri-hand-heart-line"></i>相遇<b>${escHtml(prof.相遇日)}</b></span>` : ''}
      ${prof.关注点 ? `<span class="she-chip"><i class="ri-focus-3-line"></i>关注<b>${escHtml(prof.关注点)}</b></span>` : ''}
      ${(data.voice || prof.口吻) ? `<span class="she-chip"><i class="ri-chat-voice-line"></i>口吻<b>${escHtml(data.voice || prof.口吻)}</b></span>` : ''}
      ${_hasBond(data) ? `<span class="she-chip"><i class="ri-hearts-line"></i>陪伴值<b>${escHtml(String(data.bond_now != null ? data.bond_now : (data.bond_points || 0)))}</b></span>` : ''}
    </div>
    <div class="she-chip-row">
      ${_sheProfChip('origin', '出生地', 'ri-map-pin-2-line', prof.出生地, '填一个出生地，会影响我说话的语气')}
      ${_sheProfChip('quirk', '口癖', 'ri-chat-quote-line', prof.口癖, '填一个口癖（比如「的说」），她说话会带着')}
    </div>
  </div>`;

  // ② 心情横条
  html += `<div class="she-block">
    <div class="she-sec-title"><i class="ri-live-line"></i>她现在的感受</div>
    <div class="she-mood"><span class="she-mood-pulse"></span><span class="she-mood-txt">${mood ? escHtml(mood) : '她很平静 · 多聊聊她会更有情绪'}</span>${moodAs ? `<span class="she-mood-asof">${escHtml(moodAs)}</span>` : ''}</div>
  </div>`;

  // ③ 五维雷达 —— GALGAME 状态面板 (雷达 + 五维条左右)
  html += `<div class="she-block she-dims-block">
    <div class="she-sec-title"><i class="ri-radar-line"></i>相处质感 · AI 自然生长</div>
    <div class="she-dim-desc" style="margin-top:-8px;margin-bottom:12px">${escHtml(dimKeys.join(' / ') || '相处质感')}</div>
    <div class="she-taste"><span class="she-taste-label"><i class="ri-vip-diamond-line"></i>整体对话风格</span><span class="she-taste-val">${note ? escHtml(note) : '自然'}</span></div>
    ${data.bond_why ? `<div class="she-dim-desc">${escHtml(data.bond_why)}</div>` : ''}
    <div class="she-body">
      <div class="she-radar-wrap">
        <div class="she-radar-box">${_sheRadar(dims)}</div>
      </div>
      <div class="she-dims">
        ${dimKeys.map(k => _sheDimBar(k, dims[k])).join('')}
      </div>
    </div>
  </div>`;

  // ④ 关系描述 —— 味道行已并入上方「整体对话风格」，若另有描述字段再显示
  if (note && note.indexOf('对话') !== -1) {}

  // ⑤ 她·画廊 —— 羁绊式朋友圈 (像 LOFTER 瀑布流卡片)
  if (Array.isArray(data.gallery) && data.gallery.length) {
    html += `<div class="she-block she-gallery">
      <div class="she-sec-title"><i class="ri-gallery-line"></i>她 · 画廊 · ${data.gallery.length} 条想对你说的话</div>
      <div class="she-gallery-grid">`;
    for (const g of data.gallery) {
      let gImg = (g.image || '').trim();
      // 磁盘路径 data/workshop/outputs/... → 可访问 URL /workshop/outputs/...
      if (gImg.startsWith('data/')) gImg = '/' + gImg.slice(5);
      else if (gImg.startsWith('static/')) gImg = '/' + gImg;
      html += `<div class="she-gallery-item">
        <div class="she-gallery-head">
          <div class="she-gallery-meta">
            <span class="she-gallery-name">${escHtml(name)}</span>
            <span class="she-gallery-date">${g.date ? escHtml(g.date) : ''}</span>
          </div>
        </div>
        ${gImg ? `<img class="she-gallery-img" src="${escHtml(gImg)}" alt="她寄给你的照片 · 点击查看大图" loading="lazy" onerror="this.style.display='none'" onclick="if(window._showLightbox)_showLightbox('${escHtml(gImg)}','她寄给你的照片')">` : ''}
        <div class="she-gallery-body">
          <div class="she-gallery-msg">${g.text ? escHtml(g.text) : ''}</div>
          <div class="she-gallery-meta">
            ${g.mood ? `<span class="she-gallery-mood"><i class="ri-heart-2-line"></i>${escHtml(g.mood)}</span>` : ''}
            <span class="she-gallery-like"><i class="ri-heart-3-line"></i>她想着你</span>
          </div>
        </div>
      </div>`;
    }
    html += `</div></div>`;
  }

  // ⑥ 让她说一句 —— 不设按钮 · 羁绊式小惊喜是她悄悄来 (像旅行青蛙)
  if (!(Array.isArray(data.gallery) && data.gallery.length)) {
    html += `<div class="she-gallery-hint"><i class="ri-magic-line"></i> 她会在某个合适的时刻，悄悄给你留一句话、一张照片——想到你的时候。</div>`;
  }

  html += `<div class="she-foot">数值是 AI 在相处中自然生长出来的 · 不是你能拖拽的开关</div>`;
  html += `</div>`;

  $dashView.innerHTML = html;
}

// 出生地 / 口癖 · 成长档案里唯一可编辑处 (五维本身不能拖)
function _sheProfFilled(v) {
  return !!(v && v !== '——');
}
function _sheProfChip(field, label, ico, value, placeholder) {
  const shown = _sheProfFilled(value);
  return `<span class="she-chip" id="she-prof-${field}" data-field="${field}" data-value="${escHtml(shown ? value : '')}">
    <i class="${ico}"></i>${escHtml(label)}
    ${shown ? `<b>${escHtml(value)}</b>` : `<span>${escHtml(placeholder)}</span>`}
    <button type="button" class="btn-ghost" title="编辑${escHtml(label)}" onclick="sheBeginEditProfile('${field}')"><i class="ri-pencil-line"></i></button>
  </span>`;
}
function sheBeginEditProfile(field) {
  const chip = document.getElementById('she-prof-' + field);
  if (!chip) return;
  const cur = chip.getAttribute('data-value') || '';
  const isOrigin = field === 'origin';
  const label = isOrigin ? '出生地' : '口癖';
  const ico = isOrigin ? 'ri-map-pin-2-line' : 'ri-chat-quote-line';
  const ph = isOrigin ? '填一个出生地，会影响我说话的语气' : '填一个口癖（比如「的说」），她说话会带着';
  chip.innerHTML = `<i class="${ico}"></i>${label}
    <input id="she-prof-${field}-input" value="${escHtml(cur)}" placeholder="${escHtml(ph)}" maxlength="40" style="width:180px;padding:4px 10px;font-size:12.5px;background:var(--bg3);color:var(--text);border:1px solid var(--border);border-radius:8px;font-family:inherit">
    <button type="button" class="btn-ghost" title="保存" onclick="sheSaveProfile('${field}')"><i class="ri-check-line"></i></button>
    <button type="button" class="btn-ghost" title="取消" onclick="loadDashboard('she_state')"><i class="ri-close-line"></i></button>`;
  const inp = document.getElementById('she-prof-' + field + '-input');
  if (inp) {
    inp.focus();
    inp.select();
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); sheSaveProfile(field); }
      if (e.key === 'Escape') { e.preventDefault(); loadDashboard('she_state'); }
    });
  }
}
async function sheSaveProfile(field) {
  const inp = document.getElementById('she-prof-' + field + '-input');
  const val = ((inp && inp.value) || '').trim();
  if (!val) {
    if (typeof loadDashboard === 'function') loadDashboard('she_state');
    return;
  }
  const payload = field === 'origin' ? { origin: val } : { quirk: val };
  try {
    const r = await fetch('/dashboard/she_profile', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!r.ok) { alert('保存失败 [' + r.status + ']'); return; }
    if (typeof loadDashboard === 'function') loadDashboard('she_state');
  } catch (e) {
    alert('保存出错了: ' + e.message);
  }
}

// 她·画廊 —— 让她说一句 (羁绊式小惊喜 · 不刷屏)
async function sheMakeGalleryEntry(btn) {
  if (!btn) return;
  btn.disabled = true;
  const old = btn.textContent;
  btn.textContent = '她想了一会儿…';
  try {
    const r = await fetch('/api/dashboard/she_gallery/make', { method: 'POST' });
    const j = await r.json();
    if (j && j.ok) {
      // 刷新展示
      if (typeof loadDashboard === 'function') loadDashboard('she_state');
    } else {
      let hint = (j && j.reason === 'no_image_app') ? (j.hint || '没有生图应用') : ((j && j.reason) || '这次她没想说');
      alert(hint || '这次她没想说');
    }
  } catch (e) {
    alert('调用出错了: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}
