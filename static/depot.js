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
 *       + Daemonkey 日记(renderDiary) + 技能库(renderPlaybooks + 工艺铁律)
 *       + 心愿单 / 沉淀位(renderWishlist / renderSinks · 2026-07-12 从 chat.js 搬来)。
 * 仍在 chat.js:loadDashboard 分发(调这里的 render fn)。
 */

// ── 成长档案 (depot) · 把 日记/心愿/沉淀位/技能库 并成一个 hub · 内部标签切换 ──
// 复用各子维度现成的 render fn (renderCognition/renderWishlist/renderSinks/renderPlaybooks)·
// 不重写渲染 · 只在 $dashView 顶部补一条标签条。切子标签 = 重新 loadDepot(sub)。
// 信息架构 (用户 2026-07-12 拍板):画像/日记拆开·工艺铁律并入技能库·砍"当下关注"。
// cognition=画像(对你的记忆·rich viewer) · diary=Daemonkey 日记(它的内心反思·复用 /dashboard/cognition 数据)。
const DEPOT_TABS = [
  { id: 'cognition', label: '画像',      icon: 'ri-user-heart-line' },
  { id: 'diary',     label: 'Daemonkey 日记', icon: 'ri-brain-fill' },
  { id: 'wishlist',  label: 'Daemonkey 心愿', icon: 'ri-lightbulb-fill' },
  { id: 'playbooks', label: '技能库',    icon: 'ri-tools-fill' },
  { id: 'sinks',     label: '沉淀位',    icon: 'ri-archive-drawer-fill' },
];
let _depotActive = 'cognition';

// 成长档案各 tab 的"这是什么"说明横幅 (跟 Daemonkey 心愿那条同款样式)。
// wishlist 自带横幅(还带按钮)·这里只补其余·避免重复。
const _DEPOT_BANNERS = {
  cognition: {
    icon: 'ri-user-heart-line',
    title: '这是 Daemonkey 对你的画像',
    sub: 'Daemonkey 持续维护的"你当下是个什么样"——作息/情绪/在做的项目/偏好/风险,聊天里它觉得值得长期记住的都写进这里。daemon 每次启动都自动装上,让它一上线就带着"你的当下"。顶部"最近记了什么"能看到它最近记了些啥。',
  },
  diary: {
    icon: 'ri-brain-fill',
    title: '这是 Daemonkey 的日记',
    sub: 'Daemonkey 给自己写的笔记——每次大动作后的反思/观察/学到的东西。你在这里读到的等于"读 Daemonkey 的眼睛"。这不是给你的报告,是它自己的内心记录。',
  },
  sinks: {
    icon: 'ri-archive-drawer-fill',
    title: '这是 Daemonkey 的沉淀位总览',
    sub: 'Daemonkey 所有长期文件(灵魂/记忆/画像/日志/复盘…)挂在哪一格,这里一眼可见。它是防冗余的元地图:每样新东西该沉到哪,照着它走不乱放。点卡片能预览或在本机打开原文。',
  },
  playbooks: {
    icon: 'ri-tools-fill',
    title: '这是 Daemonkey 的工艺库 · 打法 + 铁律',
    sub: '打法:把一次踩过坑、后来走顺的流程,跟 Daemonkey 说"抽成 playbook",它就沉淀在这里,之后同类任务自动取用。铁律:Daemonkey 用失败换来的工程纪律,写进来就注入它每一次的判断里——经验和纪律都不再每次从零试。',
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

// ── 画像 (对你的记忆本 · rich viewer) · Hero+pills+软提醒 / 时间线 / 六维卡片网格 ──
// 工艺铁律→技能库 · Daemonkey 日记→独立 tab · 当下关注已砍。数据源 /dashboard/cognition。
function renderCognition(data) {
  if (data && data.error) {
    $dashView.innerHTML = `
      <div class="dash-head"><h2><i class="ri-user-heart-line"></i> 画像</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }
  const 用户 = data.用户_profile || {};
  const flow = data.recent_flow || [];
  const sections = 用户.sections || [];
  const lastUpd = _fmtCogTime(用户.last_updated);

  let html = `
    <div class="dash-head">
      <h2><i class="ri-user-heart-line"></i> 用户 画像</h2>
      <span class="meta">${sections.length} 节${lastUpd ? ' · 最后更新 ' + escHtml(lastUpd) : ''}</span>
      <button onclick="backToChat()">✕ 收起</button>
      <button onclick="loadDashboard('cognition')">刷新</button>
    </div>`;

  if (!用户.exists) {
    html += `<div class="dash-empty">${escHtml(用户.note || '画像还没建 · 跟 Daemonkey 多聊聊,它会开始记你')}</div>`;
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
  if (pills.length) {
    html += `<div class="cog-pills">` + pills.map(p => `
        <div class="cog-pill"><i class="${p.icon}"></i><span><span class="k">${escHtml(p.k)}</span><span class="v">${escHtml(p.v)}</span></span></div>`).join('') + `</div>`;
  }
  if (checkin) {
    html += `<div class="cog-checkin"><i class="ri-hand-heart-line"></i><span>${escHtml(checkin)}</span><span class="tagx">温柔回访</span></div>`;
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

  // 六维画像 · 2 列卡片网格(过滤"使用说明/维护流水"这类噪声段·纯净版兜底显示全部)
  const skip = /使用说明|使用方式|如何维护|维护日志|维护流水|更新流水|更新日志|变更记录|changelog|元信息|须知|给下一|下一根毛|的提示$/i;
  let cards = sections.filter(s => !skip.test(s.heading || ''));
  if (cards.length < 2) cards = sections;

  html += `<div class="cog-sec-title"><i class="ri-layout-grid-line"></i> 六维画像 <span class="cog-sec-hint">${cards.length} 维 · 点"展开全部"看整维</span></div><div class="cog-grid">`;
  _cogDims = [];
  cards.forEach((sec) => {
    const icon = _cogDimIcon(sec.heading);
    const clean = String(sec.heading || '').replace(/^[一二三四五六七八九十\d]+[、.．]\s*/, '');
    const parts = clean.split(' · ');
    const name = parts[0] || clean || '未命名';
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

  // 展开全部 → 弹窗看整维(卡片保持齐平·弹窗滚动看全量)
  $dashView.querySelectorAll('.cog-dim-btn').forEach(btn => {
    btn.onclick = () => _cogDimModal(_cogDims[parseInt(btn.dataset.i, 10)]);
  });
}

// ── Daemonkey 日记 (它的内心反思 · 独立 tab · 复用 /dashboard/cognition 数据) ──
function renderDiary(data) {
  if (data && data.error) {
    $dashView.innerHTML = `
      <div class="dash-head"><h2><i class="ri-brain-fill"></i> Daemonkey 日记</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }
  const diary = data.Daemonkey_diary || {};
  const entries = (diary.entries || []).filter(e => (e.type || 'reflection') !== 'iron_rule');
  const lastUpd = _fmtCogTime(diary.last_updated);

  let html = `
    <div class="dash-head">
      <h2><i class="ri-brain-fill"></i> Daemonkey 日记</h2>
      <span class="meta">${entries.length} 条${lastUpd ? ' · 最后更新 ' + escHtml(lastUpd) : ''}</span>
      <button onclick="backToChat()">✕ 收起</button>
      <button onclick="loadDashboard('diary')">刷新</button>
    </div>`;

  if (!entries.length) {
    html += `<div class="dash-empty">${escHtml(diary.note || '还没写过 · 跟 Daemonkey 说「记一笔今天的观察」')}</div>`;
    $dashView.innerHTML = html;
    return;
  }

  html += `<div class="cog-diary-list">`;
  entries.forEach((e, i) => {
    const body = e.body_excerpt || e.body || '';
    const bodyHtml = (typeof mdRender === 'function') ? mdRender(body) : escHtml(body);
    html += `
      <details class="cog-card cog-diary-entry"${i === 0 ? ' open' : ''}>
        <summary class="cog-card-head">
          <span class="cog-e-date">${escHtml(e.date || '')}</span>
          <span class="cog-card-name">${escHtml(e.title || '')}</span>
          <i class="ri-arrow-down-s-line cog-card-caret"></i>
        </summary>
        <div class="cog-card-body markdown-body">${bodyHtml}</div>
      </details>`;
  });
  html += `</div>`;
  $dashView.innerHTML = html;
}


// ── 技能库 · playbook 沉淀查看器 (只读 + 删除 · 灌/召回走 NLP) ──────────
function renderPlaybooks(data) {
  if (data && data.error) {
    $dashView.innerHTML = `
      <div class="dash-head"><h2><i class="ri-tools-fill"></i> 技能库</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }
  const items = (data && data.items) || [];
  const iron = (data && data.iron_rules) || [];
  const st = (data && data.stats) || {};
  let html = `
    <div class="dash-head">
      <h2><i class="ri-tools-fill"></i> 技能库</h2>
      <span class="meta">工艺库 · 打法 ${st.total || items.length} 条${st.used ? ' · ' + st.used + ' 条用过' : ''}${iron.length ? ' · 铁律 ' + iron.length + ' 条' : ''}</span>
      <button onclick="backToChat()">✕ 收起</button>
      <button onclick="loadDashboard('playbooks')">刷新列表</button>
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

  html += `<div class="cog-sec-title"><i class="ri-tools-fill"></i> 打法 · playbook <span class="cog-sec-hint">${items.length} 条</span></div>`;

  if (!items.length) {
    html += `
      <div class="dash-stub">
        <h3>还没沉淀过打法</h3>
        <div>跟 Daemonkey 把一次踩过坑的流程走顺后·说「把刚才这套抽成 playbook」<br>
             Daemonkey 会调 <code>extract_playbook</code> 沉淀·之后遇到同类任务自动取用。</div>
      </div>`;
  } else {
    if (items.length > 3) {
      html += renderListFilter({ targetSelector: '.report-card', placeholder: '搜技能标题 / 标签...' });
    }
    html += `<div class="reports-list">`;
    for (const p of items) {
      const tagBadges = (p.tags || []).map(t => `<span class="rc-src-badge">#${escHtml(t)}</span>`).join(' ');
      html += `
        <div class="report-card">
          <div class="rc-head">
            <span class="rc-name pb-open" data-id="${escHtml(p.id)}" title="点击查看招式全文"><i class="ri-tools-fill"></i> ${escHtml(p.title || p.id)}</span>
            ${p.task_type ? `<span class="rc-src-badge">${escHtml(p.task_type)}</span>` : ''}
            ${p.used_count ? `<span class="rc-src-badge">用过 ${p.used_count} 次</span>` : ''}
          </div>
          <div class="rc-meta">
            <span class="rc-time">${escHtml((p.created_at || '').slice(0, 10))}</span>
            ${tagBadges}
            <a class="rc-dl pb-del" href="javascript:void(0)" data-id="${escHtml(p.id)}" data-title="${escHtml(p.title || '')}" title="删除这条打法"><i class="ri-delete-bin-line"></i></a>
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
      if (confirm(`删除技能「${t}」？沉淀的招式会清掉(以后不再自动取用 · 不影响本次对话)。`)) {
        _pbAction('/dashboard/playbooks/delete', { id: btn.getAttribute('data-id') });
      }
    };
  });
  if (items.length > 3) _applyListFilter($dashView.querySelector('.list-filter-input'));
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

// 复用知识库预览弹窗的样式 (.kb-modal-*) · 只是 meta 行换成 playbook 语义
function _showPbModal(data) {
  const meta = (data && data.meta) || {};
  const text = (data && data.content) || '';
  let host = document.getElementById('kbModalHost');
  if (!host) {
    host = document.createElement('div');
    host.id = 'kbModalHost';
    host.className = 'kb-modal-host';
    document.body.appendChild(host);
  }
  const tags = (meta.tags || []).map(t => `<span class="rc-src-badge">#${escHtml(t)}</span>`).join(' ');
  const bodyHtml = (typeof mdRender === 'function')
    ? mdRender(text) : ('<pre style="white-space:pre-wrap">' + escHtml(text) + '</pre>');
  const metaLine = [meta.task_type, meta.used_count ? ('用过 ' + meta.used_count + ' 次') : '',
    (meta.created_at || '').slice(0, 10)].filter(Boolean).join(' · ');
  host.innerHTML = `
    <div class="kb-modal-mask"></div>
    <div class="kb-modal" role="dialog" aria-modal="true">
      <div class="kb-modal-head">
        <span class="kb-modal-title">${escHtml(data.title || meta.title || '技能')}</span>
        <span class="kb-modal-meta">${escHtml(metaLine)}</span>
        <button class="kb-modal-close" title="关闭 (Esc)">✕</button>
      </div>
      ${tags ? `<div class="kb-modal-tags">${tags}</div>` : ''}
      <div class="kb-modal-body markdown-body">${bodyHtml}</div>
    </div>`;
  host.classList.add('show');
  const close = () => {
    host.classList.remove('show');
    document.removeEventListener('keydown', onKey);
  };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  document.addEventListener('keydown', onKey);
  host.querySelector('.kb-modal-close').onclick = close;
  host.querySelector('.kb-modal-mask').onclick = close;
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
      <button class="wish-banner-btn" onclick="askDaemonkeyForWish()">让 Daemonkey 想想还要装啥</button>
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
    actions.push(`<button class="wb wb-ok" onclick="wishAction('${w.id}', 'approve_daemon')" title="Daemonkey 先勘察出方案·你批方案了才写码"><i class="ri-checkbox-circle-fill"></i> 批准 · 让 Daemonkey 装</button>`);
    actions.push(`<button class="wb" onclick="wishAction('${w.id}', 'approve_cursor')" title="你去 Cursor 里让 Claude 装"><i class="ri-focus-3-fill"></i> 我去 Cursor 装</button>`);
    actions.push(`<button class="wb wb-no" onclick="wishAction('${w.id}', 'reject')"><i class="ri-close-circle-fill"></i> 弃</button>`);
    actions.push(`<button class="wb wb-deep" onclick="wishAction('${w.id}', 'deep_dive')"><i class="ri-search-fill"></i> 让 Daemonkey 深挖</button>`);
  } else if (w.status === 'active') {
    if (sub === 'plan_pending') {
      actions.push(`<button class="wb wb-go" onclick="wishAction('${w.id}', 'approve_plan')" title="关卡1 · 按 Daemonkey 方案开干·自动从 master 切分支写码"><i class="ri-rocket-fill"></i> 批方案 → 开干</button>`);
      actions.push(`<button class="wb" onclick="wishAction('${w.id}', 'replan')" title="对方案不满意·让 Daemonkey 重新勘察"><i class="ri-refresh-fill"></i> 重新勘察</button>`);
      actions.push(`<button class="wb wb-no" onclick="wishAction('${w.id}', 'reject')"><i class="ri-close-circle-fill"></i> 弃</button>`);
    } else if (sub === 'blocked') {
      actions.push(`<button class="wb wb-no" onclick="wishAction('${w.id}', 'view_log')" title="看 Daemonkey 撞墙过程"><i class="ri-clipboard-fill"></i> 看撞墙日志</button>`);
      actions.push(`<button class="wb" onclick="wishAction('${w.id}', 'retry_impl')"><i class="ri-refresh-fill"></i> 重新实施</button>`);
      actions.push(`<button class="wb wb-no" onclick="wishAction('${w.id}', 'reject')"><i class="ri-close-circle-fill"></i> 弃</button>`);
    } else {
      if (isDaemon) {
        actions.push(`<button class="wb wb-go" disabled title="Daemonkey 在自己分支上写码·完工自动进待验收">⏳ Daemonkey 进行中…</button>`);
        actions.push(`<button class="wb wb-no" onclick="wishAction('${w.id}', 'abort_impl')">⏹ 紧急叫停</button>`);
      } else {
        actions.push(`<button class="wb wb-go" onclick="wishAction('${w.id}', 'mark_review')" title="装完了·提交给 用户 验收">📬 装完了 → 提交验收</button>`);
        actions.push(`<button class="wb wb-no" onclick="wishAction('${w.id}', 'reject')"><i class="ri-close-circle-fill"></i> 弃</button>`);
      }
      if (hasBranch) actions.push(`<button class="wb" onclick="wishAction('${w.id}', 'view_diff')"><i class="ri-search-fill"></i> 看 diff</button>`);
    }
    actions.push(`<button class="wb wb-deep" onclick="wishAction('${w.id}', 'deep_dive')"><i class="ri-search-fill"></i> 让 Daemonkey 深挖</button>`);
  } else if (w.status === 'review') {
    if (hasBranch) actions.push(`<button class="wb wb-go" onclick="wishAction('${w.id}', 'view_diff')" title="看 Daemonkey 改了啥"><i class="ri-search-fill"></i> 查看 diff</button>`);
    actions.push(`<button class="wb wb-go" onclick="wishAction('${w.id}', 'verify_live')" title="关卡2 · 验收通过·自动合进 master 主干上线"><i class="ri-checkbox-circle-fill"></i> 验收通过 → 合主干上线</button>`);
    actions.push(`<button class="wb wb-no" onclick="wishAction('${w.id}', 'reject_to_active')" title="有问题·打回让 Daemonkey 继续改"><i class="ri-arrow-go-back-fill"></i> 有问题 → 打回</button>`);
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
          ${w.origin === 'Daemonkey' ? '<span class="wish-badge wish-badge-origin" title="Daemonkey 主动嗅探到的愿望"><i class="ri-radar-fill"></i> Daemonkey 主动发现</span>' : ''}
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

function askDaemonkeyForWish() {
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

