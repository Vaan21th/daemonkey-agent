/*
 * dashboard-panels.js · 工作台 / 陪伴模式共享的看板面板函数
 *
 * 2026-08-26 从 chat.js + companion/panels.js 收口 (一字不差的 96 个)。
 * why: panels.js 当初是脚本复制出来的, 不是 depot.js 那种真拆 —— 99% 函数同名,
 * 其中 96 个原样重复 (~3190 行)。改一处必须记得改另一处, 忘了就是静默不一致。
 *
 * 装载顺序 (跟 depot.js 同款):
 *   工作台 chat.html:  dashboard-panels.js → depot.js → clients.js → chat.js
 *   陪伴   index.html: dashboard-panels.js → panels.js → depot.js → companion.js
 * 零构建、全局作用域。两边删掉同名定义后靠本文件提供。
 *
 * 本文件只收「两边一字不差」的函数。陪伴独有适配 / 已漂移的仍留在各自文件。
 */

/* 本机放行: 中间件会注 Bearer · 前端闸不能因 localStorage 空就直接死 */
function _loopbackAuthToken() {
  try {
    const t = localStorage.getItem('opus_ui_token') || '';
    if (t) return t;
  } catch (e) {}
  const h = (location.hostname || '').replace(/^\[|\]$/g, '').toLowerCase();
  if (h === '127.0.0.1' || h === 'localhost' || h === '::1') return '__loopback__';
  return '';
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

function _biBriefScopeQuery() {
  if (!_biHeat.ym) { const n = new Date(); _biHeat.ym = { y: n.getFullYear(), m: n.getMonth() + 1 }; }
  const { y, m } = _biHeat.ym;
  return { mm: y + '-' + String(m).padStart(2, '0'), vd: _biHeat.domain || 'all' };
}

function _biFmtNum(n) {
  n = +n || 0;
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k';
  return String(n);
}

function _biFmtTok(v) {
  if (v >= 1e6) return (v/1e6).toFixed(1) + 'M';
  if (v >= 1e3) return (v/1e3).toFixed(1) + 'k';
  return String(v || 0);
}

function _biIsLlm(m) {
  const s = ((m.model_id || '') + ' ' + (m.name || '')).toLowerCase();
  return _biLlmFams.some(f => s.includes(f));
}

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

function _biSigRadarPool() {
  return _biSig.todayOnly ? _biSig.radar.filter(_biIsToday) : _biSig.radar;
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
    const m = RADAR_DOMAINS_META[id] || { icon: '', label: id, color: 'var(--opus)' };
    const on = _biSig.domain === id;
    const style = on ? `style="--dc:${m.color}"` : '';
    html += `<button class="bi-heat-dom${on ? ' active' : ''}" ${style} onclick="biSigSetDomain('${id}')">${m.icon || ''} ${escHtml(m.label)} <i>${counts[id]}</i></button>`;
  });
  box.innerHTML = html;
}

function _biStarN(v) {
  v = +v || 0;
  if (v >= 70) return 5;
  if (v >= 48) return 4;
  if (v >= 34) return 3;
  if (v >= 22) return 2;
  if (v > 0) return 1;
  return 0;
}

function _biSuggestIgnored() {
  try { return JSON.parse(localStorage.getItem('bi_suggest_ignore') || '{}'); } catch { return {}; }
}

function _biSyncSignalHeight() {
  const heat = document.querySelector('.bi-heat-card');
  const sig = document.querySelector('.bi-signal-card');
  if (!heat || !sig) return;
  // 上下堆叠(窄屏)时不强制等高·各自自然高
  if (Math.abs(heat.offsetTop - sig.offsetTop) > 4) { sig.style.height = ''; return; }
  const h = heat.offsetHeight;
  if (h > 0) sig.style.height = h + 'px';
}

function _biTip() {
  if (!_biTipEl) {
    _biTipEl = document.createElement('div');
    _biTipEl.id = 'biHeatTip';
    _biTipEl.className = 'bi-heat-tip';
    document.body.appendChild(_biTipEl);
  }
  return _biTipEl;
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

function _closeAllKbModals() {
  const host = document.getElementById('kbModalHost');
  if (host) host.classList.remove('show');
}

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
      showChatToast(data.existed ? '这份报告已经在知识库里了' : '已存入知识库 · 「报告」文件夹 · 之后回答能引用原文');
    }
  } catch (e) {
    alert('网络出错: ' + e.message);
    if (btn) { btn.disabled = false; btn.innerHTML = old; }
  }
}

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

/* ── 知识库卡片·就地状态更新 ──────────────────────────────
   点了「停止参考 / 恢复参考」或常驻/敏感图标，立刻把这张卡改对，不重拉整页。
   接口回传的 doc 是权威值，照着它改 DOM，不做本地推断。 */
function _kbCardState(card, doc) {
  if (!card || !doc) return;
  const off = doc.enabled === false;
  card.classList.toggle('kb-off', off);
  const head = card.querySelector('.rc-head');
  const nameEl = head && head.querySelector('.rc-name');
  const badge = head && head.querySelector('.rc-src-extract');
  if (off && !badge && nameEl) {
    const sp = document.createElement('span');
    sp.className = 'rc-src-badge rc-src-extract';
    sp.textContent = '已静音';
    nameEl.insertAdjacentElement('afterend', sp);
  } else if (!off && badge) {
    badge.remove();
  }
  const btn = card.querySelector('.kb-toggle');
  if (btn) {
    btn.setAttribute('data-enabled', off ? '0' : '1');
    btn.textContent = off ? '恢复参考' : '停止参考';
  }
}

function _kbFlagState(btn, doc, flag) {
  if (!btn || !doc) return;
  const on = doc[flag] === true;
  btn.setAttribute('data-on', on ? '1' : '0');
  btn.classList.toggle('on', on);
}

/* 头部「X 篇 · Y 参考中 · Z 静音」就地重算（数卡片比等接口快、也不会过期） */
function _kbHeadStats() {
  const meta = $dashView && $dashView.querySelector('.dash-head .meta');
  if (!meta) return;
  const toggles = $dashView.querySelectorAll('.kb-toggle');
  const off = $dashView.querySelectorAll('.kb-toggle[data-enabled="0"]').length;
  meta.textContent = toggles.length + ' 篇 · ' + (toggles.length - off) + ' 参考中 · ' + off + ' 静音';
}

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

function _previewModalKeyHandler(e) {
  if (e.key === 'Escape') {
    const host = document.getElementById('kbModalHost');
    if (host && host.classList.contains('show')) host.classList.remove('show');
  }
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

function _clipSched(s) {
  s = String(s || '').replace(/\s+/g, ' ').replace(/\*+/g, '').trim();
  if (!s) return '未命名任务';
  return s.length > 18 ? s.slice(0, 18) + '…' : s;
}

function _schedShortTitle(t) {
  const src = String((t && t.raw_text) || (t && t.action && t.action.prompt) || '').trim();
  if (!src) return '未命名任务';
  const titled = src.match(/(?:文档标题|标题)\s*[「『"]([^」』"]{2,28})[」』"]/);
  if (titled) return _clipSched(titled[1]);
  const quoted = src.match(/[「『]([^」』]{4,24})[」』]/);
  if (quoted) return _clipSched(quoted[1]);
  const h = src.match(/^#{1,3}\s+(.+)$/m);
  let line = (h ? h[1] : (src.split(/\n/).find(x => x.trim()) || ''));
  line = line.replace(/^#+\s*/, '').replace(/`+/g, '').replace(/\*+/g, '').trim();
  line = line.replace(/\s*[·•]\s*自动任务\s*$/, '').trim();
  const colon = line.match(/^(.{2,12})[：:]/);
  if (colon) return colon[1];
  if (line.length > 18) {
    const cut = line.match(/^(.{6,18}?)[，。；、]/);
    if (cut) return cut[1];
  }
  return _clipSched(line);
}

function _schedLastWord(t) {
  const st = String((t && t.last_run_status) || '').toLowerCase();
  if (!t || !t.last_run_at) return '还没跑过';
  if (st === 'ok' || st === 'success' || st === 'done') return '成功';
  if (st === 'error' || st === 'fail' || st === 'failed') return '没跑成';
  return t.last_run_status || '已跑';
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
    <p class="muted sched-banner">
      调度：${alive ? '<span class="sched-alive">运行中</span>' : '<span class="sched-dead">未运行</span>'}
      · 直接跟我说「每天 9 点打行情」就行，建好会出现在这儿。
    </p>`;

  if (!tasks.length) {
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
    const kind = a.kind === 'reminder' ? '提醒' : '执行';
    const lastWord = _schedLastWord(t);
    const lastAt = t.last_run_at ? _schedLocalTime(t.last_run_at) : '—';
    const nextAt = t.next_run_at
      ? _schedLocalTime(t.next_run_at)
      : (enabled ? '未排' : '已停');
    const failed = /error|fail/.test(String(t.last_run_status || '').toLowerCase());
    const err = failed
      ? String(t.last_run_summary || '').replace(/^执行失败:\s*/i, '').replace(/^RuntimeError:\s*/i, '').slice(0, 90)
      : '';
    const lastTone = lastWord === '成功' ? 'ok' : (lastWord === '没跑成' ? 'bad' : '');
    return `
      <article class="sched-card${enabled ? ' on' : ' off'}">
        <div class="sched-card-top">
          <span class="sched-when"><i class="ri-time-line"></i> ${escHtml(_schedSummaryCN(t.schedule))}</span>
          <span class="sched-pills">
            <span class="sched-pill">${kind}</span>
            <span class="sched-pill ${enabled ? 'on' : 'off'}">${enabled ? '开着' : '停着'}</span>
            ${a.notify_wechat ? '<span class="sched-pill"><i class="ri-wechat-line"></i> 微信</span>' : ''}
          </span>
        </div>
        <h3 class="sched-card-title">${escHtml(_schedShortTitle(t))}</h3>
        <div class="sched-stats">
          <div>
            <small>上次</small>
            <b>${escHtml(lastAt)}</b>
            <em class="${lastTone}">${escHtml(lastWord)}</em>
          </div>
          <div>
            <small>下次</small>
            <b>${escHtml(nextAt)}</b>
          </div>
          <div>
            <small>已跑</small>
            <b>${Number(t.runs_completed) || 0} 次</b>
          </div>
        </div>
        ${err ? `<p class="sched-err"><i class="ri-error-warning-line"></i> ${escHtml(err)}</p>` : ''}
        <div class="sched-card-acts">
          <button type="button" class="sched-btn sched-toggle" data-id="${escHtml(t.id)}" data-enabled="${enabled ? '1' : '0'}">${enabled ? '停用' : '启用'}</button>
          <button type="button" class="sched-btn danger sched-del" data-id="${escHtml(t.id)}">删除</button>
        </div>
      </article>`;
  }).join('');

  $dashView.innerHTML = `
    <div class="dash-head">
      <h2><i class="ri-timer-2-fill"></i> 定时任务</h2>
      <div class="dh-chips">
        <div class="dh-chip"><b>${tasks.length}</b><span>个</span></div>
        <div class="dh-chip"><b>${tasks.filter(t => t.enabled).length}</b><span>开着</span></div>
      </div>
    </div>
    ${banner}
    <div class="sched-list">${cards}</div>`;

  $dashView.querySelectorAll('.sched-toggle').forEach(btn => {
    btn.onclick = () => _schedAction('/dashboard/scheduled_tasks/toggle', {
      task_id: btn.getAttribute('data-id'),
      enabled: btn.getAttribute('data-enabled') !== '1',
    });
  });
  $dashView.querySelectorAll('.sched-del').forEach(btn => {
    btn.onclick = async () => {
      const ask = typeof opusConfirm === 'function'
        ? opusConfirm({ title: '删除定时任务', message: '删掉这个定时任务吗？', okText: '删除', cancelText: '保留' })
        : Promise.resolve(window.confirm('删掉这个定时任务吗？'));
      if (!(await ask)) return;
      _schedAction('/dashboard/scheduled_tasks/delete', { task_id: btn.getAttribute('data-id') });
    };
  });
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

function _showPreviewModal(opts) {
  const { title, metaLine, bodyHtml, tags, raw, openPath } = opts || {};
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
        ${openPath ? `<button class="kb-modal-annotate" title="打开产物库铺进画布 · 圈字批注 / 加图"><i class="ri-quill-pen-line"></i> 查看 &amp; 批注</button>` : ''}
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
  const _oa = host.querySelector('.kb-modal-annotate');
  if (_oa) _oa.onclick = () => { close(); if (typeof _docOpenForAnnotate === 'function') _docOpenForAnnotate(openPath); };
}

async function _toggleFavorite(kind, refId, titleHint, domain, action = 'toggle', category) {
  if (!kind || !refId) return null;
  try {
    const payload = {
      kind, ref_id: refId,
      title_hint: titleHint || '',
      domain: domain || '',
      action,
    };
    // category 只对 kind=output 有意义 · 不传就不动原有值 (undefined ≠ 清空)
    if (category !== undefined) payload.category = category;
    const r = await fetch('/favorites', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
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

function _whenChartReady(cb, _tries) {
  if (typeof Chart !== 'undefined') { cb(); return; }
  _tries = _tries || 0;
  if (_tries > 60) return;  // ~6s 还没来 = 脚本真没加载到 · 放弃 · 别死循环
  setTimeout(() => _whenChartReady(cb, _tries + 1), 100);
}

async function biBriefGenerate() {
  const btn = document.getElementById('biBriefGenBtn');
  const body = document.getElementById('biBriefBody');
  const { mm, vd } = _biBriefScopeQuery();
  const ok = await opusConfirm({
    title: '研判这段时间的趋势',
    message: {
      html: `让 Daemonkey 看一遍 <b>${mm}${vd && vd !== 'all' ? ' · ' + escHtml(vd) : ''}</b> 的高价值信号·
        给出趋势研判 + 执行方案。<span class="om-hint">会问一次模型（大约几毛钱、半分钟）。看过的会记住，再看不重复花。</span>`
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
    else if (body) body.innerHTML = '<div class="bi-v3-empty">研判失败。出错记录在本机日志里。</div>';
  } catch (e) {
    if (body) body.innerHTML = '<div class="bi-v3-empty">研判出错 · 网络或 daemon 问题</div>';
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<i class="ri-sparkling-2-line"></i> 重新研判'; }
  }
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

function biHeatCloseDrawer() {
  const d = document.getElementById('biHeatDrawer');
  if (d) d.remove();
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
    if (!r.ok) {
      if (row) {
        row.querySelectorAll('.bi-sig-fb button').forEach(b => {
          /* 不改 class · 请求失败保持原样 */
        });
      }
      if (typeof addSys === 'function') addSys('热力图反馈失败 [' + r.status + ']');
      else console.warn('biHeatFeedback HTTP', r.status);
      return;
    }
  } catch (e) {
    if (typeof addSys === 'function') addSys('热力图反馈失败: ' + (e && e.message));
    return;
  }
  if (row) {
    row.querySelectorAll('.bi-sig-fb button').forEach(b => b.classList.remove('on'));
    if (!wasActive) btn.classList.add('on');
  }
  biHeatLoad();  // 反馈改了价值·热力图重算
}

function biHeatItemHtml(it) {
  const fb = it.feedback || '';
  const canFb = !!it.item_id;
  const fbBtns = canFb ? `
    <div class="bi-sig-fb">
      <button class="${fb === 'starred' ? 'on' : ''}" title="收藏" onclick="biHeatFeedback('${jsStr(it.item_id)}','starred',this)"><i class="ri-star-line"></i></button>
      <button class="${fb === 'thumbs_up' ? 'on' : ''}" title="这类多关注" onclick="biHeatFeedback('${jsStr(it.item_id)}','thumbs_up',this)"><i class="ri-thumb-up-line"></i></button>
      <button class="${fb === 'thumbs_down' ? 'on' : ''}" title="别再推同类" onclick="biHeatFeedback('${jsStr(it.item_id)}','thumbs_down',this)"><i class="ri-thumb-down-line"></i></button>
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

function biHeatNav(delta) {
  if (!_biHeat.ym) return;
  let { y, m } = _biHeat.ym;
  m += delta;
  if (m < 1) { m = 12; y--; }
  if (m > 12) { m = 1; y++; }
  _biHeat.ym = { y, m };
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
    const bg = d.value > 0 ? `--heat:${op.toFixed(3)}` : '';
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
          return `<div class="bi-rhythm-row"><i class="ri-aspect-ratio-fill"></i><div class="bi-rhythm-main"><b>能力对照</b> · ${en}</div><div class="bi-rhythm-sub">${last}</div></div>`;
        }
        return '';
      }).join('');
    }
  }
}

function biHeatRitualDraft() {
  biHeatCloseDrawer();
  if (_biHeat.reviewPrompt && typeof spawnQuickly === 'function') spawnQuickly(_biHeat.reviewPrompt, '月度复盘起草');
}

function biHeatSetDomain(id) {
  _biHeat.domain = id || 'all';
  biHeatLoad();
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

function biHeatTipHide() { if (_biTipEl) _biTipEl.style.display = 'none'; }

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

function biSignalOpen(el) {
  const u = el && el.dataset ? el.dataset.url : '';
  if (u) window.open(u, '_blank', 'noopener');
}

function biSuggestIgnore(el) {
  const item = (el && el.closest) ? el.closest('.bi-suggest-item') : document.getElementById('biSuggest-' + el);
  const id = (item && item.dataset && item.dataset.sid) || el;
  if (!id) return;
  const m = _biSuggestIgnored();
  m[id] = new Date().toISOString().slice(0, 10);
  localStorage.setItem('bi_suggest_ignore', JSON.stringify(m));
  if (item) item.remove();
  const bar = document.getElementById('biSuggestBar');
  if (bar && !bar.querySelector('.bi-suggest-item')) bar.innerHTML = '';
}

function biTlToggleMore(btn) {
  const more = document.getElementById('biTlMoreWrap');
  if (!more) return;
  const open = more.style.display !== 'none';
  more.style.display = open ? 'none' : '';
  btn.innerHTML = open
    ? `<i class="ri-arrow-down-s-line"></i> 展开剩余 ${more.children.length} 条`
    : '<i class="ri-arrow-up-s-line"></i> 收起';
}

async function confirmRemoveDomain(slug, label, itemsCount, sourcesCount) {
  if (!slug || slug === 'self-evolve') return;
  const ok = await opusConfirm({
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

function deepDive(kind, label) {
  if (!label) return;
  const msg = `深挖一下「${label}」这个${kind}：\n` +
    `1. 用 web_search 找最近 3-6 个权威/技术深度的资料\n` +
    `2. 选 2 个最值得读的·用 web_fetch 拿全文\n` +
    `3. 给我一份结构化分析：背景 + 当前进展 + 跟我们工作室的关系 + 你的判断`;
  spawnTask(msg, `深挖${kind}: ${label}`);
}

function deepDiveOpp(oneBasedIdx) {
  const card = document.querySelectorAll('.opp-card')[oneBasedIdx - 1];
  if (!card) return;
  const titleEl = card.querySelector('.opp-title');
  const title = titleEl ? titleEl.textContent.trim() : `第 ${oneBasedIdx} 个机会`;
  deepDive('掘金机会', title);
}

function deepDiveRadar(title) {
  if (!title) return;
  deepDive('信息雷达条目', title);
}

function deepDiveTrend(zeroBasedIdx) {
  const card = document.querySelector(`.trend-card[data-trend-idx="${zeroBasedIdx}"]`);
  if (!card) return;
  const title = card.getAttribute('data-trend-title') ||
                (card.querySelector('.tc-head') || {}).textContent ||
                `第 ${zeroBasedIdx + 1} 个趋势`;
  deepDive('趋势', title.trim());
}

function escHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function jsStr(v) {
  var s = String(v == null ? '' : v);
  s = s.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\r?\n/g, '\\n');
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

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

function fillBISignals(radar, trends) {
  _biSig.trends = (trends && trends.trends) || [];
  _biSig.radar = (radar && radar.items) || [];
  _biSigRenderDomains();
  _biSigRender();
}

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

function fillBIV3Blocks(data) {
  const domainsById = {};
  for (const d of data.domains || []) domainsById[d.id] = d;

  // KPI 条
  const picks = [
    { id:'radar',   icon:'ri-radar-fill',     color:'var(--opus)',  label:'雷达信号' },
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
        : `<a class="bi-link-btn" href="#" onclick="openSettings();return false;"><i class="ri-price-tag-3-line"></i> 去填价格 →</a>`;
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
        // 2026-08-20 用户: 胶囊只留 皇冠+模型名+tok · 「顾问唤醒」标签和时间/mode 收进悬浮
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
    // 2026-08-20 用户: 最多显 5 条 · 超出收进「展开更多」(左栏比右栏(缓存经济性)高一截 · 对不齐)
    // 「仅显示最近 8 条」不单起一行 · 并进展开按钮行右侧 (用户 续)
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

function _biStillWanted() {
  if (typeof currentView !== 'undefined' && currentView && currentView !== 'bi') return false;
  return true;
}

async function loadBIDashboard() {
  if (typeof window._dashLoadSeq === 'number') window._dashLoadSeq += 1;
  const seq = window._dashLoadSeq;
  if (!token) {
    if (!_biStillWanted()) return;
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
    if (seq !== window._dashLoadSeq || !_biStillWanted()) return;
    if (!r.ok) {
      $detailPane.innerHTML = `<div class="bi-loading">加载失败 [${r.status}]</div>`;
      return;
    }
    const data = await r.json();
    if (seq !== window._dashLoadSeq || !_biStillWanted()) return;
    renderBIDashboard(data);
  } catch (e) {
    if (seq !== window._dashLoadSeq || !_biStillWanted()) return;
    $detailPane.innerHTML = `<div class="bi-loading">网络出错: ${e.message}</div>`;
  }
}

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

async function loadBIMemory() {
  const body = document.getElementById('biMemoryBody');
  const badge = document.getElementById('biMemoryBadge');
  const btn = document.getElementById('biMemoryAuditBtn');
  if (btn) btn.onclick = () => spawnQuickly('帮我看看操作手册是不是有重复的 (用 audit_playbooks 工具出簇清单 · 不确定的摆给我选)', '检查操作手册');
  if (!body) return;
  try {
    const r = await fetch('/dashboard/memory_map?lite=1', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) { body.innerHTML = '<div class="bi-v3-empty">加载失败</div>'; return; }
    const d = await r.json();
    if (d.error) { body.innerHTML = `<div class="bi-v3-empty">${escHtml(d.error)}</div>`; return; }
    const nb = d.notebook || {};
    const hg = d.hygiene || {};
    const nbPct = nb.full_chars ? Math.round(nb.core_chars / nb.full_chars * 100) : null;
    if (badge) badge.textContent = (d.playbook_count || 0) + ' 份操作手册';
    const cells = [
      { icon: 'ri-database-2-fill', color: '#8affd6', val: _biFmtNum(d.total_chunks || 0), lbl: '记忆总量' },
      { icon: 'ri-tools-fill', color: '#b794f6', val: d.playbook_count || 0, lbl: '操作手册' },
      { icon: 'ri-shield-check-fill', color: '#6ed27a', val: 'v' + (hg.version || '?'), lbl: hg.migrated ? '卫生闸·已清理' : '卫生闸·待清理' },
    ];
    if (nbPct != null) cells.push({ icon: 'ri-stack-fill', color: '#ffd28a', val: '-' + (100 - nbPct) + '%', lbl: '画像分层压缩' });
    body.innerHTML = cells.map(c =>
      `<div class="bi-self-cell"><div class="bi-self-icon" style="color:${c.color}"><i class="${c.icon}"></i></div><div class="bi-self-val">${escHtml(String(c.val))}</div><div class="bi-self-lbl">${escHtml(c.lbl)}</div></div>`
    ).join('');
  } catch (e) { body.innerHTML = '<div class="bi-v3-empty">网络出错</div>'; }
}

async function loadBIMirror() {
  const body = document.getElementById('biMirrorBody');
  const timeEl = document.getElementById('biMirrorTime');
  const btn = document.getElementById('biMirrorBtn');
  if (btn) btn.onclick = () => spawnQuickly('帮我照一次市场能力镜像 (mirror_capability action=generate)', '能力对照');
  if (!body) return;
  try {
    const r = await fetch('/dashboard/capability_snapshot', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) { body.innerHTML = '<div class="bi-v3-empty">加载失败</div>'; return; }
    const d = await r.json();
    if (!d.snapshot) {
      body.innerHTML = `<div class="bi-v3-empty">${escHtml(d.note || '还没有能力对照 · 点右上「现在对照」')}</div>`;
      if (timeEl) timeEl.textContent = '';
      return;
    }
    body.innerHTML = (typeof mdRender === 'function') ? mdRender(d.snapshot) : escHtml(d.snapshot);
    if (timeEl) timeEl.textContent = d.generated_at ? ('· ' + d.generated_at) : '';
  } catch (e) { body.innerHTML = '<div class="bi-v3-empty">网络出错</div>'; }
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
      <div class="bi-suggest-item" data-sid="${escHtml(it.id)}" id="biSuggest-${escHtml(it.id)}" style="display:flex;align-items:center;gap:8px;padding:8px 12px;margin-bottom:6px;border:1px solid var(--border,#2a2a3a);border-radius:10px;background:var(--bg2,#1a1826);font-size:12px">
        <i class="${escHtml(it.icon)}" style="color:${escHtml(it.color || 'var(--accent,#8a7dff)')};font-size:14px"></i>
        <span style="flex:1;color:var(--text,#ece8f5)">${escHtml(it.text)}</span>
        ${it.prompt ? `<button class="bi-link" style="white-space:nowrap" onclick="spawnQuickly(${JSON.stringify(it.prompt).replace(/"/g, '&quot;')}, ${JSON.stringify(it.label || '建议操作').replace(/"/g, '&quot;')})"><i class="ri-play-fill"></i> ${escHtml(it.label || '执行')}</button>` : ''}
        <button class="bi-link" title="今天不再提示" onclick="biSuggestIgnore(this)" style="opacity:.55"><i class="ri-close-line"></i></button>
      </div>`).join('');
  } catch (e) { /* 建议条失败不影响看板 */ }
}

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
    loadBIMemory();   // 0.9.6 · 记忆体系卡 (lite 端点 · <100ms)
    loadBIWorkshop(); // 0.9.6 · 工坊卡
    loadBISuggestions(); // 0.9.6 · 建议操作条 (顶部 · 条件触发)
  } catch (e) {
    console.error('BI V3 async load error:', e);
  }
}

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

let _shelfPreviewOpen = false;

async function loadReportPreview(filename, previewUrl) {
  if (!token || !filename) return;
  let kind = _shelfKind || "reports";
  if (/\.pptx?$/i.test(filename)) kind = "decks";
  else if (/\.xlsx?$/i.test(filename)) kind = "sheets";
  else if (/\.html?$/i.test(filename)) kind = "protos";
  else if (/\.docx?$/i.test(filename)) kind = "reports";
  if (kind === "protos") {
    const protoRel = String(filename).replace(/\\/g, "/");
    const path = protoRel.startsWith("data/design/") ? protoRel : ("data/design/" + protoRel);
    if (typeof openStage === "function") {
      openStage({ path: path });
      return;
    }
  }
  const rel = kind === "decks"
    ? ("data/presentations/" + filename)
    : (kind === "sheets" ? ("data/spreadsheets/" + filename) : ("data/reports/" + filename));
  // 用户 2026-09-20:「所有的产物点开都只需要在中栏显示就行了」—— 不再自动跳它归属的那场对话。
  const isHistFile = !/^_hist_/i.test(filename);   // 是否历史稿 (保留这个判据: 功能哨兵)
  if (!isHistFile) { /* 产物点开只铺中栏 · 跳对话请用分组头的「进入话题」 */ }
  window._dashLoadSeq = (window._dashLoadSeq || 0) + 1;
  if (typeof loadDashboard === 'function') {
    if (typeof loadDashboard._seq !== 'number') loadDashboard._seq = 0;
    loadDashboard._seq++;
  }
  _shelfPreviewOpen = true;
  $dashView.innerHTML = _shelfLoadHTML('正在打开成品');
  try {
    const url = shelfPreviewUrl(kind, filename);
    const r = await fetch(url, {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) {
      _shelfPreviewOpen = false;
      const errTxt = await r.text();
      $dashView.innerHTML = `<div class="dash-empty">预览失败 [${r.status}]<br>${escHtml(errTxt.slice(0,300))}</div>`;
      return;
    }
    const data = await r.json();
    data.requested = filename;
    if (filename) data.name = filename;
    renderReportPreview(data);
  } catch (e) {
    _shelfPreviewOpen = false;
    $dashView.innerHTML = `<div class="dash-empty">网络出错: ${e.message}</div>`;
  }
}

function shelfKindOf(d) {
  if (d && d.kind === 'decks') return 'decks';
  if (d && d.kind === 'sheets') return 'sheets';
  if (d && d.kind === 'protos') return 'protos';
  if (d && /\.pptx$/i.test(d.name || '')) return 'decks';
  if (d && /\.xlsx$/i.test(d.name || '')) return 'sheets';
  if (d && /\.html?$/i.test(d.name || '')) return 'protos';
  return 'reports';
}

function shelfOpenPath(d) {
  if (d && d.open_path) return d.open_path;
  const name = (d && d.name) || '';
  const kind = shelfKindOf(d);
  if (kind === 'decks') return 'data/presentations/' + name;
  if (kind === 'sheets') return 'data/spreadsheets/' + name;
  if (kind === 'protos') return (String(name).replace(/\\/g, '/').startsWith('data/design/') ? String(name).replace(/\\/g, '/') : ('data/design/' + name));
  return 'data/reports/' + name;
}

function fmtShelfSize(kb) {
  const n = Number(kb) || 0;
  if (n >= 1024) return (n / 1024).toFixed(1) + ' MB';
  return (Math.round(n * 10) / 10) + ' KB';
}

function shelfPreviewUrl(kind, filename) {
  const name = encodeURIComponent(filename || '');
  if (kind === 'decks') return '/shelf/preview/decks/' + name;
  if (kind === 'sheets') return '/shelf/preview/sheets/' + name;
  if (kind === 'protos') return '/stage/file/data/design/' + name;
  return '/reports/preview/' + name;
}

function shelfStageBits(name, sizeKb) {
  const n = String(name || '');
  const hist = /^_hist_(.+)_v(\d+)_/i.exec(n);
  return {
    title: hist ? hist[1] : n,
    mark: hist ? ('历史 V' + hist[2]) : '当前',
    size: (sizeKb || sizeKb === 0) ? fmtShelfSize(sizeKb) : '',
    hist: !!hist,
  };
}

function paintStagePages(pages) {
  const el = document.getElementById('rpStageMeta');
  if (!el || !pages) return;
  const t = el.textContent || '';
  const m = t.match(/ · (\d+) 页$/);
  if (m && Number(m[1]) >= pages) return;
  el.textContent = t.replace(/ · \d+ 页$/, '') + ' · ' + pages + ' 页';
}

function withAuthToken(url) {
  if (!url) return url;
  const t = encodeURIComponent(token || '');
  return url + (url.includes('?') ? '&' : '?') + 'token=' + t;
}

async function restoreShelfVersion(kind, name, btn) {
  if (!token || !kind || !name) return;
  const old = btn ? btn.innerHTML : '';
  if (btn) { btn.disabled = true; btn.innerHTML = '<i class="ri-loader-4-line"></i> 抄回…'; }
  try {
    const r = await fetch('/shelf/restore/' + encodeURIComponent(kind) + '/' + encodeURIComponent(name), {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token },
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || !j.ok) {
      const msg = (j && (j.error || j.detail || j.hint)) || ('HTTP ' + r.status);
      if (btn) { btn.innerHTML = '<i class="ri-error-warning-line"></i> 抄不回'; btn.title = msg; btn.disabled = false; }
      return;
    }
    await loadReportPreview(j.name, j.preview_url);
  } catch (e) {
    if (btn) { btn.innerHTML = '<i class="ri-error-warning-line"></i> 抄不回'; btn.title = String(e); btn.disabled = false; }
    else if (old && btn) btn.innerHTML = old;
  }
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
      else if (typeof alert === 'function') alert('打开失败: ' + msg);
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

function renderShelfPreview(d) {
  window._dashLoadSeq = (window._dashLoadSeq || 0) + 1;
  _shelfPreviewOpen = true;
  const name = d.requested || d.name || '?';
  const meta = d.meta || {};
  const md = d.markdown || '';
  const hasMd = !!d.has_md_source;
  const note = d.note || '';
  const kind = shelfKindOf(d);
  const isDeck = kind === 'decks';
  const isSheet = kind === 'sheets';
  const rawDl = d.download_url || (isDeck ? `/presentations/${name}` : (isSheet ? `/spreadsheets/${name}` : `/reports/${name}`));
  const dlUrl = withAuthToken(rawDl);
  const dlLabel = isDeck ? '下载 pptx' : (isSheet ? '下载 xlsx' : '下载 docx');
  const openPath = shelfOpenPath(d);
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

  const canvasTag = isDeck ? 'PPT' : (isSheet ? '表' : '稿');
  const bits = shelfStageBits(name, d.size_kb);
  const pages = d.pages || 0;
  const metaBits = [bits.mark, bits.size, pages ? (pages + ' 页') : ''].filter(Boolean).join(' · ');
  $dashView.innerHTML = `
    <div class="stage-root">
    <div class="dash-head stage-bar">
      <span class="stage-tag">${canvasTag}</span>
      <h2 class="stage-title" title="${escHtml(name)}">${escHtml(bits.title)}</h2>
      <span class="stage-meta" id="rpStageMeta">${escHtml(metaBits)}</span>
      <button type="button" class="rp-dl-btn" data-open-path="${escHtml(openPath)}"><i class="ri-external-link-line"></i> 用软件打开</button>
      <a class="rp-dl-btn" href="${escHtml(dlUrl)}" download="${escHtml(name)}">${dlLabel}</a>
      <button type="button" class="stage-x" onclick="typeof stageClose==='function'?stageClose():loadDashboard('reports')" title="关掉画布"><i class="ri-close-line"></i></button>
    </div>
    <div class="depot-tabs rp-view-tabs" role="tablist">
      <button type="button" class="depot-tab active" data-rp-tab="visual"><i class="ri-landscape-line"></i><span>成品</span></button>
      <button type="button" class="depot-tab" data-rp-tab="source"><i class="ri-file-text-line"></i><span>文稿</span></button>
    </div>
    <div class="rp-pane" data-rp-pane="visual">
      <div class="rp-visual-wait" id="rpVisualWait">${_shelfLoadHTML('正在渲成品预览')}</div>
      <div id="rpVisual" hidden></div>
    </div>
    <div class="rp-pane" data-rp-pane="source" hidden>
      <div class="rp-meta-strip">
        ${hasMd
          ? '<span class="rp-src rp-src-md"><i class="ri-file-text-fill"></i> markdown 源</span>'
          : (isSheet
            ? '<span class="rp-src rp-src-extract"><i class="ri-table-line"></i> 没有 markdown 源 · 成品仍可看表</span>'
            : (isDeck
            ? '<span class="rp-src rp-src-extract"><i class="ri-error-warning-fill"></i> 没有 markdown 源</span>'
            : '<span class="rp-src rp-src-extract"><i class="ri-error-warning-fill"></i> 旧报告 · 从 docx 反推的简陋版</span>'))}
        ${note ? `<span class="rp-note">${escHtml(note)}</span>` : ''}
      </div>
      <article class="rp-body">
        ${coverBlock}
        <div class="rp-md">${typeof mdRender === 'function' ? mdRender(md) : escHtml(md)}</div>
      </article>
    </div>
    </div>
  `;

  $dashView.querySelectorAll('[data-rp-tab]').forEach(btn => {
    btn.onclick = () => {
      const tab = btn.getAttribute('data-rp-tab');
      $dashView.querySelectorAll('[data-rp-tab]').forEach(b => b.classList.toggle('active', b === btn));
      $dashView.querySelectorAll('[data-rp-pane]').forEach(p => {
        p.hidden = p.getAttribute('data-rp-pane') !== tab;
      });
      if (typeof window.stageNotesBind === 'function') {
        window.stageNotesBind({ mode: 'office', path: openPath, kind: kind, name: name });
      }
    };
  });
  const openBtn = $dashView.querySelector('[data-open-path]');
  if (openBtn) openBtn.onclick = () => revealFile(openBtn.getAttribute('data-open-path'), openBtn);
  if (typeof window.stageNotesBind === 'function') {
    window.stageNotesBind({ mode: 'office', path: openPath, kind: kind, name: name });
  }
  fetchShelfVisual(kind, name);
}

function _shelfLoadHTML(text) {
  if (typeof dashLoadingHTML === 'function') return dashLoadingHTML(text);
  // 兼底（chat.js 没加载时才走到这）· 2026-09-30 跟着主定义换成钥匙孔双环
  return `<div class="dash-empty dk-ld">
    <div class="dk-ld-mark"><img src="/static/img/logo-mark.png" alt=""><i></i><i></i></div>
    <div class="dk-ld-txt">${escHtml(text || '加载中')}</div>
  </div>`;
}

function _shelfWaitErr(wait, msg) {
  if (!wait) return;
  wait.hidden = false;
  wait.classList.add('is-err');
  wait.innerHTML = `<i class="ri-error-warning-line"></i> ${escHtml(msg)}`;
}

function fetchShelfVisual(kind, name) {
  const wait = document.getElementById('rpVisualWait');
  const box = document.getElementById('rpVisual');
  if (!box) return;
  fetch(`/shelf/visual/${encodeURIComponent(kind)}/${encodeURIComponent(name)}`, {
    headers: { 'Authorization': 'Bearer ' + token },
  })
    .then(r => r.json().then(j => ({ okHttp: r.ok, j })).catch(() => ({ okHttp: false, j: {} })))
    .then(({ okHttp, j }) => {
      if (!box.isConnected) return;
      if (!okHttp || !j.ok) {
        _shelfWaitErr(wait, (j.error || '成品预览渲不出来') + ' · 可切到文稿，或用软件打开');
        return;
      }
      if (wait) wait.hidden = true;
      box.hidden = false;
      paintStagePages(j.pages || (j.assets && j.assets.length) || 0);
      paintShelfVisual(box, j);
    })
    .catch(e => {
      if (wait && wait.isConnected) _shelfWaitErr(wait, e.message || '网络出错');
    });
}

function styleOfficePreviewFrame(fr) {
  if (!fr) return;
  const paint = () => {
    try {
      const doc = fr.contentDocument;
      if (!doc) return;
      const raw = (doc.body && getComputedStyle(doc.body).backgroundColor) || "";
      const m = raw.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
      const lum = m ? (0.2126 * +m[1] + 0.7152 * +m[2] + 0.0722 * +m[3]) / 255 : 0.12;
      const dark = lum < 0.45;
      const thumb = dark ? "rgba(232,223,201,0.32)" : "#b8a888";
      const hover = dark ? "rgba(232,223,201,0.5)" : "#8a7048";
      let s = doc.getElementById("dk-sb");
      if (!s) {
        s = doc.createElement("style");
        s.id = "dk-sb";
        (doc.head || doc.documentElement).appendChild(s);
      }
      s.textContent =
        "html{color-scheme:" + (dark ? "dark" : "light") + "}" +
        "*{scrollbar-width:thin!important;scrollbar-color:" + thumb + " transparent!important}" +
        "*::-webkit-scrollbar{width:8px!important;height:8px!important}" +
        "*::-webkit-scrollbar-track{background:transparent!important}" +
        "*::-webkit-scrollbar-thumb{background:" + thumb + "!important;border-radius:4px}" +
        "*::-webkit-scrollbar-thumb:hover{background:" + hover + "!important}";
    } catch (e) { /* PDF 查看器 / 跨域画不进去 */ }
  };
  paint();
  fr.addEventListener("load", paint);
}
window.styleOfficePreviewFrame = styleOfficePreviewFrame;

function paintShelfVisual(box, j) {
  const rebind = () => {
    if (typeof window.stageNotesBind === 'function') window.stageNotesBind();
  };
  const hook = (fr) => {
    if (!fr) return;
    styleOfficePreviewFrame(fr);
    const recount = () => {
      rebind();
      try {
        const doc = fr.contentDocument;
        const n = doc && doc.querySelectorAll('.slide, [class*="slide"]').length;
        if (n > 1) paintStagePages(n);
      } catch (e) { /* 跨域数不了 */ }
    };
    fr.addEventListener("load", recount);
    recount();
  };
  if (j.mode === 'pdf' && j.pdf_url) {
    box.innerHTML = `<iframe class="rp-pdf" title="成品预览" src="${escHtml(withAuthToken(j.pdf_url))}"></iframe>`;
    hook(box.querySelector("iframe"));
    return;
  }
  if (j.mode === 'html' && j.html_url) {
    box.innerHTML = `<iframe class="rp-pdf" title="成品预览" src="${escHtml(withAuthToken(j.html_url))}"></iframe>`;
    hook(box.querySelector("iframe"));
    return;
  }
  const assets = j.assets || [];
  if (!assets.length) {
    box.innerHTML = `<div class="rp-visual-wait">没有渲出页面</div>`;
    return;
  }
  let i = 0;
  const urls = assets.map(a => withAuthToken(a.url));
  const thumbs = urls.map((u, n) =>
    `<button type="button" class="rp-thumb${n ? '' : ' is-on'}" data-i="${n}" title="第 ${n + 1} 页">`
    + `<img alt="" src="${escHtml(u)}"><span class="rp-thumb-n">${n + 1}</span></button>`
  ).join('');
  box.innerHTML = `
    <div class="rp-slide-deck">
      <aside class="rp-slide-thumbs" id="rpSlideThumbs">${thumbs}</aside>
      <div class="rp-slide-main">
        <div class="rp-slide-stage"><img id="rpSlideImg" alt="幻灯片" src="${escHtml(urls[0])}"></div>
        <div class="rp-slide-nav">
          <button type="button" id="rpSlidePrev" class="rp-dl-btn"><i class="ri-arrow-left-s-line"></i></button>
          <span id="rpSlidePos">1 / ${urls.length}</span>
          <button type="button" id="rpSlideNext" class="rp-dl-btn"><i class="ri-arrow-right-s-line"></i></button>
        </div>
      </div>
    </div>
  `;
  const img = box.querySelector('#rpSlideImg');
  const pos = box.querySelector('#rpSlidePos');
  const show = (n) => {
    i = (n + urls.length) % urls.length;
    img.src = urls[i];
    pos.textContent = (i + 1) + ' / ' + urls.length;
    box.querySelectorAll('.rp-thumb').forEach((b, k) => b.classList.toggle('is-on', k === i));
    const on = box.querySelector('.rp-thumb.is-on');
    if (on && on.scrollIntoView) on.scrollIntoView({ block: 'nearest' });
    rebind();
  };
  box.querySelector('#rpSlidePrev').onclick = () => show(i - 1);
  box.querySelector('#rpSlideNext').onclick = () => show(i + 1);
  box.querySelectorAll('.rp-thumb').forEach((b) => {
    b.onclick = () => show(parseInt(b.getAttribute('data-i'), 10) || 0);
  });
  rebind();
}

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

function renderAutopilotInlineBtn() {
  return `<button class="bi-link" onclick="spawnQuickly('帮我自主巡航一遍 · 调 auto_pipeline 工具 · 三步全跑 · 跑完告诉我看到了什么 + 推 1-2 个最值得动手的机会', '自主巡航')">🛰️ 跑一圈巡航</button>`;
}

function renderBIDashboard(data) {
  if (typeof currentView !== 'undefined' && currentView && currentView !== 'bi') return;
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

      <!-- 建议操作 (0.9.6 · 用户: 页面分散 · 顶部放条件触发的行动建议 · 晨会汇报位) -->
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
            <button class="bi-brief-gen" id="biMirrorBtn" type="button"><i class="ri-camera-lens-fill"></i> 现在对照</button>
          </div>
          <div class="bi-mirror-body" id="biMirrorBody"><div class="bi-v3-empty">加载中…</div></div>
        </div>
        <div class="bi-card">
          <div class="bi-card-head"><h3><i class="ri-temp-hot-fill" style="color:#F6AD55"></i> 闭环温度计 <span class="badge" id="biClosureRate">…</span></h3></div>
          <div id="biClosureBody"><div class="bi-v3-empty">加载中…</div></div>
        </div>
      </div>

      <!-- 记忆体系 + 工坊 (0.9.6 · 用户: 看板 = 用户了解功能的大面板 · 按钮走 spawnQuickly 后台任务 · 跟照镜同款) -->
      <div class="bi-grid-2" style="margin-top:12px">
        <div class="bi-card">
          <div class="bi-card-head">
            <h3><i class="ri-brain-fill" style="color:#8affd6"></i> 记忆体系 <span class="badge" id="biMemoryBadge">…</span></h3>
            <span>
              <button class="bi-link" id="biMemoryAuditBtn" type="button" title="让 Daemonkey 用语义向量检查操作手册 · 重复簇摆出来你拍板"><i class="ri-search-eye-line"></i> 检查操作手册</button>
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

function renderExecution(data) {
  if (data && data.error) {
    $dashView.innerHTML = `
      ${pipelineBreadcrumb('execution')}
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

  // 执行反馈 = 链子的最后一格 (用户 2026-09-20:「执行反馈也要放进去」) ——
  //   原来它自带一条 exec-breadcrumb（可行性分析 → 执行反馈 → 下一轮 LLM 分析）·
  //   现在换成全站同一条链 · 避免两套箭头各说各的。链子末格那枚胶囊就是它自己。
  const breadcrumbHtml = pipelineBreadcrumb('execution');

  if (total === 0) {
    $dashView.innerHTML = `
      ${breadcrumbHtml}
      <div class="dash-head"><h2><i class="ri-refresh-fill"></i> 执行反馈</h2>
        <span class="dash-meta">还没有开始做的项目</span></div>
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
    ${breadcrumbHtml}
    <div class="dash-head">
      <h2><i class="ri-refresh-fill"></i> 执行反馈</h2>
      <div class="dh-chips">
        <div class="dh-chip"><b>${total}</b><span>个项目</span></div>
        <div class="dh-chip"><b>${escHtml(_formatTimeAgo(updatedAt))}</b><span>最近更新</span></div>
      </div>
    </div>
    <div class="dash-note">
      落地项目 · 状态 / 决策 / 收支 / 教训 · 反哺后续可行性分析
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

// ══════════════════════════════════════════════════════════════════
// 收藏夹 (wish-e16b1f52) · 用户 2026-09-18 重做
//
// 为什么重做：旧版把所有东西塞进一个网格 —— 掘金机会 / 可行性 / 产物挤一起，
// 只靠左边一条色线区分 —— 扫一眼分不出「这是我做的东西」还是「外面捡来的情报」。
// 用户 原话：「那两个是不一样的东西」「UI 也要重新设计一下」。
//
// 现在：顶部主分段把两类彻底分开。
//   产物区 = 我生成的东西 · 带【分类】(用户 自己命名) + 会话药丸
//   情报区 = 外面捡来的 · 掘金机会 / 可行性分析
// 数据层同一套 favorites.json (靠 kind 字段分) · 没有第二套机制。
// ══════════════════════════════════════════════════════════════════

const _FAV_KINDS = {
  opportunity: { icon: 'ri-diamond-fill', label: '掘金机会', color: '#ffd166' },
  feasibility: { icon: 'ri-bar-chart-fill', label: '可行性分析', color: '#a78bfa' },
};
const _FAV_EXT = {
  docx: { icon: 'ri-article-fill', label: '报告', left: '#b794f6' },
  md:   { icon: 'ri-article-fill', label: '报告', left: '#b794f6' },
  pptx: { icon: 'ri-slideshow-fill', label: '演示稿', left: '#ffd166' },
  xlsx: { icon: 'ri-table-fill', label: '表格', left: '#5bd1a2' },
  html: { icon: 'ri-window-fill', label: '原型', left: '#6ea8ff' },
};

let _favZone = 'prod';
let _favCat = '';
try { _favZone = localStorage.getItem('opus_fav_zone') || 'prod'; } catch (e) {}

function switchFavZone(z) {
  _favZone = z; _favCat = '';
  try { localStorage.setItem('opus_fav_zone', z); } catch (e) {}
  loadDashboard('favorites');
}
function switchFavCat(c) { _favCat = c; loadDashboard('favorites'); }

// 分类输入 (母体有 opusPrompt · 陪伴模式降级原生 prompt)
async function _favAskCategory(cur) {
  const msg = '给这份产物归个类（自己命名 · 比如「客户交付」「模板」 · 留空 = 未分类）';
  if (typeof opusPrompt === 'function') {
    return await opusPrompt({
      title: '分类', message: msg, defaultValue: cur || '',
      placeholder: '客户交付 / 模板 / 常用参考…',
    });
  }
  return window.prompt(msg, cur || '');
}

async function _favSetCategory(ref, cur) {
  const val = await _favAskCategory(cur);
  if (val === null || val === undefined) return;   // 取消
  const v = String(val).trim();
  const r = await _toggleFavorite('output', ref, '', '', 'set_category', v);
  if (!r || !r.ok) { if (typeof addSys === 'function') addSys('⚠ 分类没存上'); return; }
  // 不写 addSys · 分类是原地操作 (用户 2026-09-18)
  loadDashboard('favorites');
}

// ── 产物区 ──
function _favCatTag(it) {
  const cat = String(it.category || '').trim();
  const ref = escHtml(it.ref_id || '');
  return cat
    ? `<span class="cat-tag" data-cat-ref="${ref}" data-cat-cur="${escHtml(cat)}" title="点一下改分类"><i class="ri-price-tag-3-line"></i>${escHtml(cat)}</span>`
    : `<span class="cat-tag none" data-cat-ref="${ref}" data-cat-cur="" title="还没归类 · 点一下给它一个"><i class="ri-price-tag-3-line"></i>未分类</span>`;
}

function _favProdPill(it) {
  const sid = it.session_id || '', label = it.session_label || '';
  if (!sid) {
    return '<span class="rc-pill none" title="这份产物的归属机制上线前生成 · 没记下是哪场做的"><i class="ri-question-line"></i><span class="rc-pill-t">无归属</span></span>';
  }
  if (!label) {
    return '<span class="rc-pill gone" title="产出它的对话已被清理"><i class="ri-ghost-line"></i><span class="rc-pill-t">对话已归档</span></span>';
  }
  // 用户 2026-09-20:「所有的产物点开都只需要在中栏显示就行了, 毕竟我们已经有专门的进入话题
  //   和这个按钮能跳对话了不是吗？」—— 药丸退回【纯标识】: 不跳会话、不带可点大手、
  //   去掉右边那个 ↗ (那个箭头就是在说「点我跳」)。跳对话只留分组头的「进入话题」。
  return '<span class="rc-pill rc-pill-id" title="这份产自这场对话 · 要过去点分组头的「进入话题」">'
    + '<i class="ri-chat-3-line"></i><span class="rc-pill-t">' + escHtml(label) + '</span></span>';
}

function _favProdCard(it) {
  const ref = String(it.ref_id || '').replace(/\\/g, '/');
  const name = ref.split('/').pop() || ref;
  const ext = (name.split('.').pop() || '').toLowerCase();
  const e = _FAV_EXT[ext] || { icon: 'ri-file-line', label: '文件', left: '#6b7280' };
  const title = it.title_snap || name;
  return `
    <div class="report-card" style="border-left-color:${e.left}">
      <button class="rc-unstar" data-fav-remove-prod="${escHtml(ref)}" data-fav-title="${escHtml(title)}"
              title="取消收藏（文件还在产物库 · 只是不再挑出来）"><i class="ri-star-fill"></i></button>
      <div class="rc-head">
        <i class="${e.icon} rc-ico"></i>
        <a class="rc-name" href="javascript:void(0)" data-fav-prod-open="${escHtml(ref)}"
           title="在产物库里打开看它">${escHtml(title)}</a>
        <span class="rc-pill-slot">${_favProdPill(it)}</span>
      </div>
      <div class="rc-meta">
        ${_favCatTag(it)}
        <span class="rc-time">${escHtml(_formatTimeAgo(it.starred_at))}收藏</span>
        <span>· ${e.label}</span>
      </div>
    </div>`;
}

function _favCatRail(items) {
  const map = new Map();
  for (const it of items) {
    const c = String(it.category || '').trim() || '__none__';
    map.set(c, (map.get(c) || 0) + 1);
  }
  const keys = [...map.keys()].filter(k => k !== '__none__').sort();
  if (map.has('__none__')) keys.push('__none__');
  let html = `<button type="button" class="cat-chip${_favCat === '' ? ' on' : ''}" onclick="switchFavCat('')">全部 <span class="n">${items.length}</span></button>`;
  for (const k of keys) {
    const none = (k === '__none__');
    const on = (_favCat === k);
    html += `<button type="button" class="cat-chip${on ? ' on' : ''}" onclick="switchFavCat('${jsStr(k)}')">`
      + (none ? '' : '<i class="ri-price-tag-3-fill"></i>')
      + `${none ? '未分类' : escHtml(k)} <span class="n">${map.get(k)}</span></button>`;
  }
  return `<div class="cat-rail">${html}</div>`;
}

function _favProdZone(items) {
  if (!items.length) {
    return `<div class="zone-empty"><i class="ri-archive-2-line"></i>`
      + `还没收藏过产物。<br>去「产物库」把有用的那几份点个 <i class="ri-star-line"></i> —— 之后在这儿按分类找回来。</div>`;
  }
  let list = items;
  if (_favCat) {
    list = items.filter(i => (String(i.category || '').trim() || '__none__') === _favCat);
  }
  const cards = list.map(_favProdCard).join('');
  return `
    <div class="zone-note prod"><i class="ri-archive-2-line"></i>
      <span>这些是<b>你让我做出来的东西</b> · 星标只是「挑出来」。分类是你自己命名的 —— 修掉「<b>找不到之前做出来非常有用的东西</b>」这个毛病。</span>
    </div>
    ${_favCatRail(items)}
    ${cards ? `<div class="reports-list">${cards}</div>` : '<div class="zone-empty">这个分类下暂时是空的</div>'}`;
}

// ── 情报区 ──
function _favIntelCard(it) {
  const km = _FAV_KINDS[it.kind] || { icon: 'ri-bookmark-line', label: it.kind, color: '#6b7280' };
  return `
    <div class="fav-card" style="border-left-color:${km.color}">
      <div class="fc-top">
        <span class="fc-kind" style="color:${km.color}"><i class="${km.icon}"></i> ${km.label}</span>
        ${it.domain ? `<span class="fc-domain">${escHtml(it.domain)}</span>` : ''}
      </div>
      <div class="fc-title">${escHtml(it.title_snap || '?')}</div>
      ${it.note ? `<div class="fc-sum">${escHtml(it.note)}</div>` : ''}
      <div class="fc-foot">
        <span>${escHtml(_formatTimeAgo(it.starred_at))}收藏</span>
        <span class="fc-actions">
          <button type="button" class="fc-btn" data-fav-open="${escHtml(it.kind)}" data-fav-ref="${escHtml(it.ref_id)}">查看 →</button>
          <button type="button" class="fc-btn unstar" data-fav-remove-intel="${escHtml(it.kind)}|${escHtml(it.ref_id)}"><i class="ri-star-fill"></i> 取消</button>
        </span>
      </div>
    </div>`;
}

function _favIntelZone(items) {
  if (!items.length) {
    return `<div class="zone-empty"><i class="ri-radar-line"></i>`
      + `还没收藏过情报。<br>在「信息雷达」/「掘金机会」里点 <i class="ri-star-fill"></i> 星标的会汇到这儿。</div>`;
  }
  return `
    <div class="zone-note intel"><i class="ri-radar-line"></i>
      <span>这些是<b>外面捡来的情报</b> · 从信息雷达 / 掘金机会里星标的。跟产物不是一类东西，所以不跟它们混排。</span>
    </div>
    <div class="fav-grid">${items.map(_favIntelCard).join('')}</div>`;
}

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
  // 产物 和 情报 是两个区 (用户 2026-09-18: 这两类不一样 · 不能混排)
  const prodItems = items.filter(i => i.kind === 'output');
  const intelItems = items.filter(i => i.kind !== 'output');

  if (total === 0) {
    $dashView.innerHTML = `
      <div class="dash-head"><h2><i class="ri-star-fill"></i> 收藏夹</h2>
        <span class="dash-meta">空</span></div>
      <div class="dash-empty">
        <p>还没收藏过任何东西</p>
        <p class="muted" style="margin-top:8px">
          <i class="ri-archive-2-line"></i> 产物库里的 ⭐ 汇到「我的产物」·
          <i class="ri-radar-fill"></i> 信息雷达 / <i class="ri-diamond-fill"></i> 掘金机会 / <i class="ri-bar-chart-fill"></i> 可行性分析 的 ⭐ 汇到「情报」· 两个区互不干扰。
        </p>
      </div>`;
    return;
  }

  const bodyHtml = (_favZone === 'prod')
    ? _favProdZone(prodItems)
    : _favIntelZone(intelItems);

  const pN = prodItems.length, iN = intelItems.length;
  $dashView.innerHTML = `
    <div class="dash-head">
      <h2><i class="ri-star-fill"></i> 收藏夹</h2>
      <div class="dh-chips">
        <div class="dh-chip"><b>${total}</b><span>条</span></div>
        <div class="dh-chip"><b>${pN}</b><span>产物</span></div>
        <div class="dh-chip"><b>${iN}</b><span>情报</span></div>
      </div>
    </div>
    <div class="zone-seg" role="tablist">
      <button type="button" class="${_favZone === 'prod' ? 'on' : ''}" onclick="switchFavZone('prod')">
        <i class="ri-archive-2-fill"></i> 我的产物 <span class="n">${pN}</span>
        <span class="zn-sub">报告 / 演示稿 / 表格 / 原型</span>
      </button>
      <button type="button" class="${_favZone === 'intel' ? 'on' : ''}" onclick="switchFavZone('intel')">
        <i class="ri-radar-fill"></i> 情报 <span class="n">${iN}</span>
        <span class="zn-sub">掘金机会 / 可行性</span>
      </button>
    </div>
    ${bodyHtml}
  `;

  // 情报 · 查看
  $dashView.querySelectorAll('[data-fav-open]').forEach(btn => {
    btn.onclick = (ev) => {
      ev.stopPropagation();
      const kind = btn.getAttribute('data-fav-open');
      const ref = btn.getAttribute('data-fav-ref');
      if (kind === 'opportunity') {
        loadDashboard('opportunities');
      } else if (kind === 'feasibility') {
        _loadFeasibilityDetail(ref);
      }
    };
  });
  // 情报 · 取消收藏
  $dashView.querySelectorAll('[data-fav-remove-intel]').forEach(btn => {
    btn.onclick = async (ev) => {
      ev.stopPropagation();
      const [kind, ref] = String(btn.getAttribute('data-fav-remove-intel') || '').split('|');
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
  // 产物 · 取消收藏 (卡片右上角 ⭐)
  $dashView.querySelectorAll('[data-fav-remove-prod]').forEach(btn => {
    btn.onclick = async (ev) => {
      ev.stopPropagation();
      const ref = btn.getAttribute('data-fav-remove-prod');
      const title = btn.getAttribute('data-fav-title') || '';
      const ok = await opusConfirm({
        title: '取消收藏',
        message: '《' + title + '》不再留在收藏夹？\n（文件本身还在产物库 · 一份都不会删）',
        okText: '取消收藏',
        cancelText: '留着',
      });
      if (!ok) return;
      await _toggleFavorite('output', ref, '', '', 'remove');
      // 不写 addSys · 确认框里已说「文件还在产物库」 (用户 2026-09-18)
      loadDashboard('favorites');
    };
  });
  // 产物 · 点分类标签改分类
  $dashView.querySelectorAll('.cat-tag[data-cat-ref]').forEach(el => {
    el.onclick = (ev) => {
      ev.stopPropagation();
      _favSetCategory(el.getAttribute('data-cat-ref'), el.getAttribute('data-cat-cur') || '');
    };
  });
  // 产物 · 点名字去产物库看它
  $dashView.querySelectorAll('[data-fav-prod-open]').forEach(el => {
    el.onclick = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const ref = String(el.getAttribute('data-fav-prod-open') || '');
      const name = ref.split('/').pop() || ref;
      const ext = (name.split('.').pop() || '').toLowerCase();
      if (ext === 'html' && typeof openStage === 'function') {
        openStage({ path: ref });
      } else if (ext === 'docx' && typeof loadReportPreview === 'function') {
        loadReportPreview(name);
      } else {
        // 演示稿 / 表格没有单件预览路径 → 去产物库对应 tab 看它
        if (typeof addSys === 'function') addSys('这份在产物库里：' + name);
        loadDashboard('reports');
      }
    };
  });
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

/* 文档类型 → remixicon class · 【单一真相源】
   （之前 typeIcon 和 _kbCover 里各有一份，已经漂移：文件夹里的 csv/json 没图标。）
   新增格式只改这里。OK_EXT 收的格式都应该在这张表里。 */
const KB_TYPE_CLASS = {
  pdf: 'ri-file-pdf-2-fill', docx: 'ri-file-word-2-fill', pptx: 'ri-file-ppt-2-fill',
  md: 'ri-markdown-fill', txt: 'ri-file-text-fill', text: 'ri-file-text-fill',
  csv: 'ri-file-excel-2-fill', xlsx: 'ri-file-excel-2-fill', xlsm: 'ri-file-excel-2-fill',
  html: 'ri-html5-fill', htm: 'ri-html5-fill', json: 'ri-braces-fill',
  xml: 'ri-code-s-slash-fill', yaml: 'ri-code-s-slash-fill', yml: 'ri-code-s-slash-fill',
  log: 'ri-file-text-fill', rst: 'ri-file-text-fill', org: 'ri-file-text-fill',
};

function renderKnowledge(data) {
  if (data && data.items) _kbData = data;   // 下钻/返回时就地重渲要用（2026-09-30）
  if (data && data.error) {
    $dashView.innerHTML = `
      <div class="dash-head"><h2><i class="ri-book-2-fill"></i> 知识库</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }
  const items = (data && data.items) || [];
  const st = (data && data.stats) || {};
  const typeIcon = {};
  for (const k in KB_TYPE_CLASS) typeIcon[k] = '<i class="' + KB_TYPE_CLASS[k] + '"></i>';

  let html = `
    <div class="dash-head">
      <h2><i class="ri-book-2-fill"></i> 知识库 · 第二大脑</h2>
      <div class="dh-chips">
        <div class="dh-chip"><b>${items.length}</b><span>篇</span></div>
        <div class="dh-chip"><b>${st.enabled || 0}</b><span>参考中</span></div>
        <div class="dh-chip"><b>${st.disabled || 0}</b><span>静音</span></div>
      </div>
      <button class="dk-add" onclick="kbAskAdd()" title="从这台机器上选文件或整个文件夹加进来"><i class="ri-add-line"></i> 添加</button>
      <button class="dk-add" onclick="kbNewFolder()" title="建一个新的知识库文件夹（空文件夹也存得住）"><i class="ri-folder-add-line"></i> 新建文件夹</button>
      <button onclick="backToChat()">✕ 收起</button>
      <button onclick="loadDashboard('knowledge')">刷新列表</button>
    </div>`;

  if (items.length === 0) {
    html += `
      <div class="dash-stub">
        <h3>知识库还是空的</h3>
        <div>点右上角「<b>添加</b>」选文件或整个文件夹（也可以一次选多个）。<br>
             支持 md / txt / docx / pptx / pdf。存进去之后，回答能引用原文。<br>
             <span style="color:var(--dim2)">要在对话框里说也行：「把 <code>D:\\资料\\合同.pdf</code> 加进知识库」。</span></div>
      </div>`;
  } else {
    if (items.length > 3) {
      html += renderListFilter({ targetSelector: '.report-card', placeholder: '搜文档标题 / 标签...' });
    }
    // 按文件夹分组显示 · folder 字段优先 · 无则退回第一个标签 · 都没有 → 未分类
    const folderOf = (d) => (d.folder && String(d.folder).trim())
      || ((d.tags && d.tags.length) ? String(d.tags[0]) : '未分类');
    const groups = {};
    // 2026-10-01 · 先把显式登记的文件夹建出来（哪怕一篇都没有·不然刚建的组当场消失）
    for (const f of ((_kbData && _kbData.folders) || [])) { if (f && !groups[f]) groups[f] = []; }
    for (const d of items) { const f = folderOf(d); (groups[f] = groups[f] || []).push(d); }
    const names = Object.keys(groups).sort((a, b) => {
      if (a === '未分类') return 1;
      if (b === '未分类') return -1;
      return a.localeCompare(b, 'zh');
    });
    // 2026-09-30 · 用户:「复用产物库的工坊产物 - 按应用的模式，类似于有文件夹，然后有文件」
    //   原来是「折叠展开」（全部文件夹挤一屏），现在跟产物库一致：先看文件夹卡，点进去看文件。
    //   面包屑直接复用产物库的 .fld-crumb / .fld-back 那套样式 —— 不分叉。
    if (_kbFolderOpen && groups[_kbFolderOpen]) {
      const fs = groups[_kbFolderOpen];
      html += `<div class="fld-crumb">
          <button class="fld-back" onclick="kbLeaveFolder()"><i class="ri-arrow-left-line"></i></button>
          <span class="fld-cur"><i class="ri-folder-3-fill"></i>${escHtml(_kbFolderOpen)}</span>
          <span class="fld-cn">${fs.length} 篇</span>
        </div>`;
      html += `<div class="kb-folders">${fs.map(d => _kbCardHtml(d, typeIcon)).join('')}</div>`;
    } else {
      const _kbCover = (docs) => {
        // 封面：把里面文档的类型图标摆出来（最多 4 个）—— 一眼能看出这夹里是什么。
        // 2026-10-01 用户:「文件夹显示 启动X个」→ 要的就是这个图标堆，
        //   之前只有 markdown 一个字形是因为类型表没盖全（知识库资料几乎全是 md），
        //   补上 csv/xlsx/html/json 等新支持的格式后，不同类型才会真的长得不一样。
        const ico = KB_TYPE_CLASS;
        const picks = docs.slice(0, 4);
        return '<div class="fld-grid icon n' + Math.max(picks.length, 1) + '">'
          + picks.map(d => '<i class="kb-fld-ico ' + (ico[d.type] || 'ri-file-2-fill') + '"></i>').join('')
          + '</div>';
      };
      html += `<div class="shelf-folders">`;
      for (const f of names) {
        const docs = groups[f];
        html += `<a class="fld kb-fld" href="javascript:void(0)" onclick="kbEnterFolder('${escHtml(jsStr(f))}')" title="${escHtml(f)}">
            ${_kbCover(docs)}
            <button type="button" class="kb-fld-del" title="删掉这个文件夹"
                    onclick="event.preventDefault();event.stopPropagation();kbAskDeleteFolder('${escHtml(jsStr(f))}', ${docs.length})">
              <i class="ri-delete-bin-line"></i></button>
            <div class="fld-foot"><span class="fld-name">${escHtml(f)}</span>
            <span class="fld-n">${docs.length} 篇</span></div>
          </a>`;
      }
      html += `</div>`;
    }
  }
  $dashView.innerHTML = html;
  _kbBindDrop();      // 拖拽入栏（只绑一次 · 幂等）

  // 下钻替代折叠（见上面 ③ 注释）—— 没有 .kb-folder-head 了，不再需要那份绑定。
  // 开关类操作就地改这张卡 —— 不整页重渲。
  // 以前是 _kbAction 里 loadDashboard(silent) 重拉整页：慢、闪、把文件夹折叠状态冲掉，
  // 而且那次 silent 刷新一旦被 stale 丢掉(并发另一次 loadDashboard)，按钮就卡在原样，
  // 用户以为没生效，得手点「刷新列表」才看到。现在直接拿接口回传的 doc 改 DOM。
  $dashView.querySelectorAll('.kb-toggle').forEach(btn => {
    btn.onclick = () => _kbAction('/dashboard/knowledge/toggle', {
      doc_id: btn.getAttribute('data-id'),
      enabled: btn.getAttribute('data-enabled') !== '1',
    }, (j) => { _kbCardState(btn.closest('.report-card'), j.doc); _kbHeadStats(); });
  });
  $dashView.querySelectorAll('.kb-flag').forEach(btn => {
    btn.onclick = () => {
      const flag = btn.getAttribute('data-flag');
      const body = { doc_id: btn.getAttribute('data-id') };
      body[flag] = btn.getAttribute('data-on') !== '1';
      _kbAction('/dashboard/knowledge/flag', body, (j) => _kbFlagState(btn, j.doc, flag));
    };
  });
  $dashView.querySelectorAll('.kb-del').forEach(btn => {
    btn.onclick = () => {
      const t = btn.getAttribute('data-title') || '这篇';
      if (confirm(`删除「${t}」？原文和索引都会清掉（从你自己磁盘上选进来的，原文件不动）。`)) {
        _kbAction('/dashboard/knowledge/delete', { doc_id: btn.getAttribute('data-id') }, (j) => {
          // 拖拽进来的那类，原件是库里自己存的副本 —— 删档时一并进回收站。
          // 不说一声的话，用户会以为文件凭空消失了。
          if (j && j.original_dropped && typeof showChatToast === 'function') {
            showChatToast('副本也一起进回收站了 · 在「设置 → 本地数据 → 回收站」能找回');
          }
        });
      }
    };
  });
  $dashView.querySelectorAll('.kb-open').forEach(el => {
    el.onclick = () => _kbPreview(el.getAttribute('data-id'));
  });
  if (items.length > 3) _applyListFilter($dashView.querySelector('.list-filter-input'));
}

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
                title="去可行性分析 · 让 Daemonkey 跑一次深度评估">
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

async function renderOpportunities(data) {
  if (data && data.error) {
    $dashView.innerHTML = `
      ${pipelineBreadcrumb('opportunities')}
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
    ${pipelineBreadcrumb('opportunities')}
    <div class="dash-head">
      <h2><i class="ri-diamond-fill"></i> 掘金机会</h2>
      <div class="dh-chips" title="市场 × 用户 能力">
        <div class="dh-chip"><b>${opps.length}</b><span>个机会</span></div>
      </div>
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
      <div class="dash-note">
        用户 画像 × 市场 · 生成于 ${formatTimeShort(generated)} · 点卡展开完整方案
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
  // 2026-09-20 · 顶部统一（wish-553d36eb）：5 张统计大卡 → 页头右侧的摘要胶囊
  //   用户 原话：「两张统计大卡独占一行，内容被压下去」→ 数字收进标题右侧 chips
  const headChips = `
    <div class="dh-chips">
      <div class="dh-chip" title="${isFiltered ? '本领域今天首次出现的新条目' : '全领域今天首次出现的新条目'} · 跟「本类/共」同一领域口径">
        <b>${newToday > 0 ? '+' + newToday : '0'}</b><span>${todayLabel}</span>
      </div>
      <div class="dh-chip" title="可见条目总数 (已扣除你隐藏的条目)">
        <b>${isFiltered ? items.length + '/' + totalVisible : totalVisible}</b><span>${isFiltered ? '本类/共' : '条信息'}</span>
      </div>
      <div class="dh-chip" title="正常抓取的信源 / 总信源数">
        <b>${okSources}/${meta.length}</b><span>信源在线</span>
      </div>
      <div class="dh-chip" title="${translatedN} 条英文条目已翻译成中文">
        <b>${translatedN}</b><span>已翻译</span>
      </div>
      <div class="dh-chip" title="${escHtml(generatedTxt)}">
        <b>${formatTimeShort(data.generated_at)}</b><span>最新抓取</span>
      </div>
    </div>`;

  let html = `
    ${pipelineBreadcrumb('radar')}
    <div class="dash-head">
      <h2><i class="ri-radar-fill"></i> 信息雷达</h2>
      ${headChips}
      <button onclick="backToChat()">✕ 收起</button>
      <button onclick="spawnQuickly('帮我跑一遍信息雷达 · 调 auto_pipeline 工具 · 参数 refresh_radar=true, regen_trends=false, mine_opps=false · 只抓取雷达不动趋势机会 · 跑完告诉我新增了哪些条目·特别是 self-evolve 域的', '重新抓取雷达')">重新抓取</button>
      <button onclick="spawnQuickly('看一眼信息雷达最新数据 · 调 auto_pipeline 工具 · 参数 refresh_radar=false, regen_trends=true, mine_opps=false · 只重新生成今日趋势 · 跑完告诉我哪几个趋势最戳到 用户 · 为什么', '生成今日趋势')">让 Daemonkey 总结趋势 →</button>
    </div>
    <div class="dash-note"><i class="ri-information-line"></i> 原料层 · 多源抓取 · 多领域</div>
    ${domainChips}
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

// 产物库类目 (wish-1dc9c39d · 用户 2026-09-19 二次定案)
// 用户 原话:「把原型、开发、知识、内容，放到同一个一级标签...就叫预制应用，然后
//   把原型、开发、知识、内容，他们直接对应到内置应用的名字上吗，做成二级，
//   不然用户看了也容易混。结构也乱」
// 判据: 一级 5 个 · 「预制应用」下的二级 = draft_studio 的 4 个 domain (同名 · 不另起别名)
const _SHELF_KINDS = ['all', 'presets', 'reports', 'decks', 'sheets', 'workshop', 'trash', 'fav'];
const _SHELF_SUBS = ['design', 'dev', 'docs', 'content'];
// 'all' = 「全部」总览 (用户 2026-09-20:「他不是跳转到产物，而是产物里的报告库」) ——
//   从掘金雷达的「产物库」出口进来时一律落到这格，不沿用上次停在哪个类目。
let _shelfKind = 'all';
let _shelfSub = 'design';
try {
  const k0 = localStorage.getItem('opus_shelf_kind') || 'all';
  _shelfKind = _SHELF_KINDS.includes(k0) ? k0 : 'all';
  const s0 = localStorage.getItem('opus_shelf_sub') || 'design';
  _shelfSub = _SHELF_SUBS.includes(s0) ? s0 : 'design';
} catch (e) {}
let _shelfLastData = null;
let _shelfRefilling = false;   // 补齐正在进行中（防并发重复请求）
//   2026-09-28 修: 原来是 `_shelfRefillStarted` 一次性标志 —— 点「刷新」重新拉了数据
//   （其余类目又变回 deferred），但那标志已是 true → 永远不再补齐 →
//   面板停在「正在取这一格…」不动（用户 报的「点刷新就卡住·点标签才好」）。
//   改成「进行中」：每次渲染都有机会补；已经补过的不缺就不发请求（_shelfEnsure 自己判断）。

// 2026-09-28 · 产物库按需拉：首屏只带了 reports 那一格，切到哪格现拉现补。
//   拉回来 merge 进 _shelfLastData —— 再切回同一格不重复请求（跟老行为一致）。
const _shelfKindKeys = {
  reports:  ['reports'],
  decks:    ['decks'],
  sheets:   ['sheets'],
  workshop: ['workshop'],
  presets:  ['presets'],
  all:      ['reports', 'decks', 'sheets', 'presets'],
  fav:      ['reports', 'decks', 'sheets', 'presets', 'workshop'],
};

function _shelfMissing(kd, kind) {
  kd = kd || {};
  const need = _shelfKindKeys[kind] || [];
  return need.filter(k => {
    if (k === 'presets') {
      const p = kd.presets || {};
      const subs = p.subs || {};
      const keys = Object.keys(subs);
      return !keys.length || keys.some(s => subs[s] && subs[s].deferred);
    }
    return !kd[k] || kd[k].deferred === true;
  });
}

async function _shelfEnsure(kind) {
  const d = _shelfLastData;
  if (!d || d.error) return d;
  const missing = _shelfMissing(d.kinds, kind);
  if (!missing.length) return d;
  try {
    const r = await fetch('/dashboard/reports?kinds=' + encodeURIComponent(missing.join(',')), {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) return d;
    const add = await r.json();
    const ak = (add && add.kinds) || {};
    const merged = Object.assign({}, d, { kinds: Object.assign({}, d.kinds) });
    missing.forEach(k => {
      if (k === 'presets') {
        const cur = merged.kinds.presets || {};
        const subAdd = (ak.presets && ak.presets.subs) || {};
        merged.kinds.presets = Object.assign({}, cur, {
          subs: Object.assign({}, cur.subs, subAdd),
          count: (ak.presets && ak.presets.count != null) ? ak.presets.count : cur.count,
        });
        // 顶层 design/dev/docs/content 也补上（_subPack 的 fallback 要用）
        ['design', 'dev', 'docs', 'content'].forEach(sk => { if (ak[sk]) merged.kinds[sk] = ak[sk]; });
      } else if (ak[k]) {
        merged.kinds[k] = ak[k];
      }
    });
    if (merged.kinds.reports) {
      merged.items = merged.kinds.reports.items || [];
      merged.count = merged.kinds.reports.count;
    }
    _shelfLastData = merged;
    return merged;
  } catch (e) {
    return d;
  }
}

function switchShelfKind(kind) {
  _shelfKind = _SHELF_KINDS.includes(kind) ? kind : 'all';
  if (_shelfKind === 'trash') _shelfTrashData = null;   // 每次进这格都重读回收站
  _shelfPage = 1;                    // 换类目回到第 1 页
  _shelfFolder = '';                 // 换类目 = 从 app 文件夹里退出来
  try { localStorage.setItem('opus_shelf_kind', _shelfKind); } catch (e) {}
  if (!_shelfLastData) return;
  renderReports(_shelfLastData);     // 先上屏（骨架 / 已有数据）
  if (_shelfMissing(_shelfLastData.kinds, _shelfKind).length) {
    _shelfEnsure(_shelfKind).then(d => { if (d) renderReports(d); });
  }
}

// 掘金雷达 → 产物库出口 (用户 2026-09-20) —— 指定落哪个类目再进。
// 为什么不直接 loadDashboard('reports'): 那会把上次停着的记忆 (opus_shelf_kind)
// 一起带进来 —— 用户 看到的就不是他要的那个类目。
// 现场: 用户「留一个报告库的跳转就好。直接跳转到报告库」→ 链子右端只调 openShelfKind('reports')。
function openShelfKind(kind) {
  _shelfKind = _SHELF_KINDS.includes(kind) ? kind : 'all';
  _shelfPage = 1;
  _shelfFolder = '';
  try { localStorage.setItem('opus_shelf_kind', _shelfKind); } catch (e) {}
  loadDashboard('reports');
}

// 预制应用下的二级切换 (产品设计 / 产品开发 / 文档撰写 / 内容制作 · 与内置应用同名)
function switchShelfSub(sub) {
  _shelfSub = _SHELF_SUBS.includes(sub) ? sub : 'design';
  _shelfPage = 1;
  _shelfFolder = '';
  try { localStorage.setItem('opus_shelf_sub', _shelfSub); } catch (e) {}
  if (_shelfLastData) renderReports(_shelfLastData);
}

// ══════════ 产物库 · 排序 / 分组 / 会话药丸 (用户 2026-09-18) ══════════
// 三入口共享同一个 renderReports: 工作台中栏 / 专注版右栏 (取的是同一份中栏 DOM) /
// 陪伴模式 (companion/index.html:320 直接引本文件) —— 改这里三处同时生效 · 零分叉。
//
// 为什么默认「不分组 + 最近修改倒序」: 用户 原话「按说应该是可以按照修改时间排列的吧?
// 然后现在他整个的排序都很弱」。他要的第一件事是时间排序 · 分组是次要的组织手段。
// 后端 output_shelf.py 本来就在按 mtime 倒序 · 但一按会话归堆就看不出来了 ——
// 所以把「排序」与「分组」解耦: 排序管顺序 · 分组管归堆方式。
let _shelfSort = 'mtime';
let _shelfDir = 'desc';
let _shelfGrp = 'none';
// ── 分页 (wish-1dc9c39d · 用户 2026-09-19) ─────────────────────────────
// 用户 原话:「注意不要截断,可以有那个点击查看更多,然后保证所有的库内文件都可以
//   按照时间排序。所以全库而不是可见的,你也可以做个那个,就是每页显示X条那个」
// 数据层本来就是全量 (后端无 limit) —— 这里只管「一屏渲几条」· 0 = 全部。
// ⚠ 搜索框有字时不分页 (否则只能搜到当前页), 见 _shelfBody。
let _shelfPage = 1;
let _shelfPer = 50;
try {
  _shelfSort = localStorage.getItem('opus_shelf_sort') || 'mtime';
  _shelfDir = localStorage.getItem('opus_shelf_dir') || 'desc';
  _shelfGrp = localStorage.getItem('opus_shelf_grp') || 'none';
  const p0 = parseInt(localStorage.getItem('opus_shelf_per') || '', 10);
  if (!isNaN(p0) && p0 >= 0) _shelfPer = p0;
} catch (e) {}
const SHELF_PER_OPTS = [20, 50, 100, 0];   // 0 = 全部
// 分组模式下每堆最多渲多少张卡 —— 2858 条全渲 = 2.1MB innerHTML (实测估算) → 卡。
// 堆头仍显示真实总数；要看某堆全部 → 搜 app 名 (会走正常分页)。
const SHELF_GROUP_CAP = 20;

function switchShelfPage(n) {
  _shelfPage = Math.max(1, parseInt(n, 10) || 1);
  if (_shelfLastData) renderReports(_shelfLastData);
  const v = (typeof $dashView !== 'undefined' && $dashView)
    ? $dashView.querySelector('.reports-list, .shelf-groups') : null;
  if (v && v.scrollIntoView) { try { v.scrollIntoView({ block: 'start' }); } catch (e) {} }
}

function switchShelfPer(n) {
  _shelfPer = Math.max(0, parseInt(n, 10) || 0);
  _shelfPage = 1;
  try { localStorage.setItem('opus_shelf_per', String(_shelfPer)); } catch (e) {}
  if (_shelfLastData) renderReports(_shelfLastData);
}

const SHELF_SORTS = {
  mtime: { label: '最近修改', icon: 'ri-history-line', dir: 'desc' },
  name: { label: '名称', icon: 'ri-sort-alphabet-ascending', dir: 'asc' },
  size: { label: '大小', icon: 'ri-hdd-line', dir: 'desc' },
};

function _shelfPersist() {
  try {
    localStorage.setItem('opus_shelf_sort', _shelfSort);
    localStorage.setItem('opus_shelf_dir', _shelfDir);
    localStorage.setItem('opus_shelf_org', _shelfOrg);
    localStorage.setItem('opus_shelf_grp', _shelfGrp);
  } catch (e) {}
}

function switchShelfSort(mode) {
  if (!SHELF_SORTS[mode]) return;
  _shelfSort = mode;
  _shelfDir = SHELF_SORTS[mode].dir;   // 换键就回到这个键的自然方向 (名称升序 / 时间倒序)
  _shelfPage = 1;
  _shelfPersist();
  if (_shelfLastData) renderReports(_shelfLastData);
}

function toggleShelfDir() {
  _shelfDir = _shelfDir === 'desc' ? 'asc' : 'desc';
  _shelfPage = 1;
  _shelfPersist();
  if (_shelfLastData) renderReports(_shelfLastData);
}

// 组织方式 (wish-1dc9c39d · 用户 2026-09-19 二次定案)
// 用户 原话:「无论是前端页面设计，还是功能，分组、会话、类型这些都有问题」
// 病根: 「视图」(文件夹/网格/列表) 和「分组」(不分组/按会话/按应用/按类型) 是两个轴
//   各切一刀、互相抢 —— 选了文件夹视图后分组按钮全被提前 return 掉，点了没反应。
// 治法: 收成【一个】控件 · 五个选项 = 五种完整呈现 · 不再有笛卡尔积。
//   app  → 文件夹格子 (每个应用一格 · Windows 那种)
//   type → 按类型分堆 (图片墙 / 视频墙 / 文档堆) —— 「图片和非图片怎么放一起」的答案
//   sess → 按会话分堆
//   none → 网格 (不分堆 · 图片多的类目默认)
//   list → 列表 (文档卡 · 报告/演示稿那些卡上有按钮的)
const _SHELF_ORGS = ['none', 'type', 'app', 'sess', 'list'];
let _shelfOrg = '';
try {
  const o0 = localStorage.getItem('opus_shelf_org') || '';
  if (_SHELF_ORGS.includes(o0)) {
    _shelfOrg = o0;
  } else {
    // 旧键迁移: view=folder/grid/list + grp=none/sess/app/type → org
    const v0 = localStorage.getItem('opus_shelf_view') || '';
    const g0 = localStorage.getItem('opus_shelf_grp') || 'none';
    _shelfOrg = (v0 === 'folder' || g0 === 'app') ? 'app'
      : (g0 === 'type') ? 'type'
      : (g0 === 'sess') ? 'sess'
      : (v0 === 'list') ? 'list' : '';
  }
} catch (e) { _shelfOrg = ''; }

// 一个类目实际装了什么 —— 决定默认怎么摆 + 给哪些组织选项
// (用户 2026-09-19 二次:「你需要判定，只产出图片的，就是默认为缩略图，
//   只产出文档的，就是默认列表显示，都有的，就按照标准混合视图」)
function _shelfMix(items) {
  const types = {};
  let hasApp = false;
  for (const it of (items || [])) {
    const k = _shelfTypeOf(it).key;
    types[k] = (types[k] || 0) + 1;
    if (!hasApp && /^app-[0-9a-z]+$/i.test(String(it.app_id || ''))) hasApp = true;
  }
  const total = (items || []).length;
  const media = (types.image || 0) + (types.video || 0) + (types.audio || 0);
  return { total: total, hasApp: hasApp, media: media, doc: total - media, types: types };
}

// 自动摆法 —— 用户没手动选过时的默认
function _shelfAutoOrg(items, canApp) {
  const m = _shelfMix(items);
  if (canApp && m.hasApp) return 'app';   // 有 app 归属 → 先看文件夹
  if (!m.total) return 'none';
  if (m.media === 0) return 'list';       // 纯文档 → 列表
  return 'none';                          // 有图/视频 → 网格 (纯图 = 缩略图墙 · 混合 = 图3 那种)
}

// 这个类目的实际组织方式 —— 空 = 没选过 → 按内容给默认
function _shelfOrgOf(kind, items) {
  if (_shelfFolder) return 'app';   // 站在文件夹里: 外层还是 app · 里面由 _shelfFolderView 单独判
  if (_shelfOrg) {
    // 「按应用」只对真有 app 字段的类目有意义 · 别的类目上它退化成按类型
    if (_shelfOrg === 'app' && kind !== 'workshop' && kind !== 'fav') return 'type';
    if (_shelfOrg === 'app' && items && !_shelfMix(items).hasApp) return 'type';
    return _shelfOrg;
  }
  return _shelfAutoOrg(items, kind === 'workshop' || kind === 'fav');
}

function switchShelfOrg(v) {
  _shelfOrg = _SHELF_ORGS.includes(v) ? v : '';
  _shelfPage = 1;
  try { localStorage.setItem('opus_shelf_org', _shelfOrg); } catch (e) {}
  if (_shelfLastData) renderReports(_shelfLastData);
}

function _shelfSorted(items) {
  const a = (items || []).slice();
  const mul = _shelfDir === 'desc' ? -1 : 1;
  a.sort((x, y) => {
    let r = 0;
    if (_shelfSort === 'name') {
      r = String(x.title || x.name || '').localeCompare(String(y.title || y.name || ''), 'zh');
    } else if (_shelfSort === 'size') {
      r = (x.size_kb || 0) - (y.size_kb || 0);
    } else {
      r = String(x.created_at || '').localeCompare(String(y.created_at || ''));
    }
    if (!r) r = String(x.created_at || '').localeCompare(String(y.created_at || ''));
    return r * mul;
  });
  return a;
}

// ── 会话药丸 ─────────────────────────────────────────────────────────
// 后端 (workers/output_shelf.py · _attach_sessions) 已把 session_id / session_label
// 挂到每一项上。三态必须都在: 覆盖率事实是 125 份里只有 11 份有 origin (绑定机制
// 2026-09-14 才上线) —— 「无归属」是正常态 · 不能看着像坏了。
function shelfJumpToSession(sid, label) {
  if (!sid) return;
  // 用户 2026-09-20:「改成进入话题（点击后打开这个话题）」—— 原来只切会话、不收回画布,
  //   结果人还停在产物库页、看不见那场对话 (点了像没反应)。
  // 2026-09-20 稍后 用户 拍板:「切对话不用关中栏显示的东西啊。不影响的啊。」
  //   → 产物库是【看东西】的地方、对话栏是【说话】的地方 · 看东西不该牵动画布。
  //   原来那句 backToChat() 治的是「点了像没反应」· 病根其实在【没有提醒】不在没收画布 (治错了病)。
  //   现已删。
  // 用户 2026-09-20 二次报「点进入话题打不开」→ 按铁律 16 不再猜原因, 改成两条硬担保:
  //   ① 先收画布再切 (顺序反了 · 专注版会把产物库槽又带回来)
  //   ② 切完落地校验 —— sessionId 真换成目标才罢休·没换成明说（不许装成功）
  try {
    if (typeof switchSessionById === 'function') switchSessionById(sid);
    else if (typeof switchToSession === 'function') switchToSession(sid);
  } catch (e) { /* 下面落地校验会就实报出 */ }
  setTimeout(function () {
    let landed = false;
    try { landed = (typeof sessionId !== 'undefined') && sessionId === sid; } catch (e) {}
    if (landed) return;   // 切成功 —— switchToSession 自己已经弹了「已切到《…》」
    if (typeof _sessionSwitchToast === 'function') {
      _sessionSwitchToast('没切过去 · 《' + (label || sid) + '》',
        '它可能在归档区 · 左栏「查看已归档」能翻到');
    }
  }, 700);
}

async function toggleShelfStar(btn) {
  const ref = btn.getAttribute('data-fav-ref');
  const title = btn.getAttribute('data-fav-title') || '';
  if (!ref) return;
  btn.disabled = true;
  const r = await _toggleFavorite('output', ref, title, '', 'toggle');
  btn.disabled = false;
  if (!r) { if (typeof addSys === 'function') addSys('⚠ 收藏没存上 · 检查一下 token'); return; }
  const on = !!r.now_starred;
  btn.classList.toggle('on', on);
  btn.innerHTML = `<i class="ri-star-${on ? 'fill' : 'line'}"></i>`;
  btn.title = on
    ? '已收藏 · 再点一下取消（收藏夹里按分类找得到）'
    : '收藏这份 · 之后能在「收藏夹 → 我的产物」里按分类找回来';
  // 顶栏「⭐ 收藏 N」就地动 —— 不然点完像「没效果」，得重载才看见 (用户 2026-09-18 报的)
  const nEl = document.getElementById('shelfFavN');
  if (nEl) {
    const cur = parseInt(nEl.textContent, 10) || 0;
    nEl.textContent = String(Math.max(0, cur + (on ? 1 : -1)));
  }
  // ⚠ 不往对话栏写 addSys —— 收藏是【原地操作】，星变色 + 计数就是全部反馈。
  //   往对话流里冒「⭐ 收藏了《x》」既刷屏又要它自己滚一遍 (用户 2026-09-18 拍板)
  // 收藏视图里取消收藏 → 这份该从列表消失 · 重渲一次 (就地改 DOM 会留下一张已取消的卡)
  if (!on && _shelfKind === 'fav') loadDashboard('reports');
}

// 产物卡上的 ⭐ (wish-e16b1f52 · 收藏夹)
// ref_id 用 open_path: 跟数据库文件名同源·跨 kind 不重·比 name 稳 (同名时会串)
function _shelfStar(it) {
  const ref = it.open_path || '';
  if (!ref) return '';
  const on = !!it.is_favorited;
  return `<button type="button" class="rc-star${on ? ' on' : ''}" `
    + `data-fav-ref="${escHtml(ref)}" data-fav-title="${escHtml(it.title || it.name || '')}" `
    + `title="${on ? '已收藏 · 再点一下取消（收藏夹里按分类找得到）' : '收藏这份 · 之后能在「收藏夹 → 我的产物」里按分类找回来'}">`
    + `<i class="ri-star-${on ? 'fill' : 'line'}"></i></button>`;
}

function _shelfPill(it) {
  const sid = it.session_id || '';
  const label = it.session_label || '';
  if (!sid) {
    return '<span class="rc-pill none" title="这份产物产生于归属机制上线之前 (2026-09-14) · 没记下是哪场对话做的">'
      + '<i class="ri-question-line"></i><span class="rc-pill-t">无归属</span></span>';
  }
  if (!label) {
    return '<span class="rc-pill gone" title="产出它的对话已被清理 · 归到 ' + escHtml(sid) + '">'
      + '<i class="ri-ghost-line"></i><span class="rc-pill-t">对话已归档</span></span>';
  }
  // 同 _shelfPill: 药丸从「可跳会话」退回【纯标识】(用户 2026-09-20)
  return '<span class="rc-pill rc-pill-id" '
    + 'title="这份产自这场对话 · 要过去点分组头的「进入话题」">'
    + '<i class="ri-chat-3-line"></i><span class="rc-pill-t">' + escHtml(label) + '</span></span>';
}

// 工具条: 搜索 (复用 renderListFilter · 它按 .report-card 的 textContent 过滤 ·
// 药丸文字也在里面 → 「搜会话标题」自动可用) + 排序 + 分组开关
function _shelfBar(kind, items) {
  const ph = kind === 'decks' ? '搜演示稿文件名 / 会话标题…'
    : (kind === 'sheets' ? '搜表格文件名 / 会话标题…'
    : (kind === 'presets' ? '搜文件名 / 路径…'
    : (kind === 'workshop' ? '搜工坊产物 / 所属 app…'
    : (kind === 'fav' ? '搜收藏…' : '搜报告文件名 / 会话标题…'))));
  const sorts = Object.keys(SHELF_SORTS).map(k => {
    const s = SHELF_SORTS[k];
    return `<button type="button" class="ss-btn${_shelfSort === k ? ' on' : ''}" onclick="switchShelfSort('${k}')">`
      + `<i class="${s.icon}"></i>${s.label}</button>`;
  }).join('');
  // 组织方式: 一个控件五个选项 (不再有「视图 × 分组」两个轴互相抢)
  // 按钮表按内容给 (用户: 纯文档的类目正常用列表就好 · 不给它「按应用」这种没意义的选项)
  const mix = _shelfMix(items);
  const curOrg = _shelfOrgOf(kind, items);
  const orgOpts = [['none', 'ri-layout-grid-fill', '不分组'], ['type', 'ri-price-tag-3-line', '按类型']];
  if ((kind === 'workshop' || kind === 'fav') && mix.hasApp) orgOpts.push(['app', 'ri-folder-3-fill', '按应用']);
  orgOpts.push(['sess', 'ri-chat-3-line', '按会话'], ['list', 'ri-list-check-2', '列表']);
  const orgs = orgOpts.map(o =>
    `<button type="button" class="sg-btn${curOrg === o[0] ? ' on' : ''}" onclick="switchShelfOrg('${o[0]}')">`
    + `<i class="${o[1]}"></i>${o[2]}</button>`).join('');
  const desc = _shelfDir === 'desc';
  return `
    ${renderListFilter({ targetSelector: '.report-card', placeholder: ph })}
    <div class="shelf-bar">
      <div class="shelf-sort">${sorts}</div>
      <button type="button" class="shelf-dir" onclick="toggleShelfDir()" title="切换排列方向">
        <i class="ri-${desc ? 'arrow-down' : 'arrow-up'}-line"></i>${desc ? '降序' : '升序'}
      </button>
      <span class="shelf-bar-sp"></span>
      <button type="button" class="shelf-act" onclick="shelfPickMode(true)" title="进入选择模式：单击=只选它 · 按住拖过哪几张=哪几张一起选"><i class="ri-delete-bin-6-line"></i> 删除</button>
      <div class="shelf-grp">${orgs}</div>
    </div>`;
}

// 分页条 (wish-1dc9c39d): 全库 N 份 / 本页 M 份 · 每页 [20|50|100|全部] · 上/下页。
// 「全库」的数字来自 items.length —— 不是可见的 (用户:「所以全库而不是可见的」)。
function _shelfPager(total, shownN, page, totalPages, per) {
  const perBtns = SHELF_PER_OPTS.map(n => {
    const on = (_shelfPer === n);
    const label = n === 0 ? '全部' : String(n);
    return `<button type="button" class="sp-btn${on ? ' on' : ''}" onclick="switchShelfPer(${n})">${label}</button>`;
  }).join('');
  const nav = totalPages > 1
    ? `<button type="button" class="sp-nav"${page <= 1 ? ' disabled' : ''} onclick="switchShelfPage(${page - 1})"><i class="ri-arrow-left-s-line"></i>上一页</button>`
      + `<span class="sp-pos">${page} / ${totalPages}</span>`
      + `<button type="button" class="sp-nav"${page >= totalPages ? ' disabled' : ''} onclick="switchShelfPage(${page + 1})">下一页<i class="ri-arrow-right-s-line"></i></button>`
    : '';
  return `<div class="shelf-pager">
      <span class="sp-info">全库 <b>${total}</b> 份 · 本页 ${shownN} 份</span>
      <span class="sp-sp"></span>
      <span class="sp-perlabel">每页</span><span class="sp-pers">${perBtns}</span>
      <span class="sp-navs">${nav}</span>
    </div>`;
}

function _shelfBody(kind, items) {
  const list = _shelfSorted(items);
  // 组织方式 (wish-1dc9c39d 二次): 一个维度 · 五个选项 · 不再有「视图×分组」两个轴抢
  const org = _shelfOrgOf(kind, list);
  // 搜索框有字时不进「按应用」的文件夹层 (那是在找具体文件 · 不是在一层层进)
  const qEl2 = (typeof $dashView !== 'undefined' && $dashView)
    ? $dashView.querySelector('.list-filter-input') : null;
  const searching = !!(qEl2 && String(qEl2.value || '').trim());
  if (org === 'app' && !searching && list.some(it => it.app_id)) {
    // 站在某个 app 里 → 出它的内容 (面包屑 + 按内容判摆法) · 否则出文件夹格子
    return _shelfFolder ? _shelfFolderView(list, kind) : _shelfFolders(list, kind);
  }
  // 分堆类: 全库分堆 · 不分页 (分堆的意义就是「一眼看清有哪些堆」· 只分当前页
  //   会让他以为某个 app 的产物不见了) · 但每堆只渲前 SHELF_GROUP_CAP 条。
  if (org === 'type') return _shelfByType(kind, list, SHELF_GROUP_CAP);
  if (org === 'sess') return _shelfBySession(kind, list, SHELF_GROUP_CAP);
  if (org === 'app') return _shelfByApp(kind, list, SHELF_GROUP_CAP);
  // 剩下两种 (网格 / 列表) 走分页
  const per = (_shelfPer > 0) ? _shelfPer : 0;
  // 「全部」= 不翻页, 但不是「无限渲」—— 一次挂上千个瓦片会把页面顶死, 视频尤其
  //   (用户 2026-09-19「我随便点了点产物之后，发现页面卡的不行了，最后直接崩了」)。
  const SHELF_HARD = 400;
  const totalPages = per ? Math.max(1, Math.ceil(list.length / per)) : 1;
  if (_shelfPage > totalPages) _shelfPage = totalPages;
  const page = per ? _shelfPage : 1;
  const shown = per ? list.slice((page - 1) * per, page * per) : list.slice(0, SHELF_HARD);
  const body = (org === 'list')
    ? '<div class="reports-list">' + shown.map(it => _shelfCard(it, kind)).join('') + '</div>'
    : _shelfGrid(kind, shown, 0);
  return body
    + (per ? _shelfPager(list.length, shown.length, page, totalPages, per) : '')
    + (!per && list.length > SHELF_HARD
      ? '<div class="sg-more">共 <b>' + list.length + '</b> 个 · 一次最多铺 ' + SHELF_HARD + ' 个（选「每页 100」翻页看全部）</div>'
      : '');
}
// 二级 · 按应用 (wish-1dc9c39d) —— 工坊产物 45 个 app 一屏糊住 (最大一堆 1140 条)。
// 大堆在前 · app_label 来自后端 (workers.workshop_assets.list_apps)。
function _shelfByApp(kind, list, cap) {
  const map = new Map();
  for (const it of list) {
    const k = it.app_id || '__none__';
    if (!map.has(k)) map.set(k, []);
    map.get(k).push(it);
  }
  const keys = [...map.keys()].filter(k => k !== '__none__')
    .sort((a, b) => map.get(b).length - map.get(a).length);
  if (map.has('__none__')) keys.push('__none__');
  return '<div class="shelf-groups">' + keys.map(k => {
    const g = map.get(k);
    const isNone = (k === '__none__');
    return _shelfGroup({
      icon: isNone ? 'ri-question-line' : 'ri-apps-2-fill', tinted: !isNone, count: g.length,
      title: isNone ? '未归入任何应用' : (g[0].app_label || k),
      hint: isNone ? '' : (k + (g.length > cap ? ' · 共 ' + g.length + ' 条，这里只列前 ' + cap + '（搜 app 名看全部）' : '')),
      body: _shelfGrid(kind, g.slice(0, cap), 0),
    });
  }).join('') + '</div>';
}

// 二级 · 按类型 —— 判据只此一份 (_SHELF_TYPES + _shelfTypeOf)，
// 别在每个调用点各写一份后缀表 (那正是两份判据的老病)。
const _SHELF_TYPES = [
  { key: 'image',  label: '图片',        icon: 'ri-image-fill',           exts: ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp'] },
  { key: 'video',  label: '视频',        icon: 'ri-video-fill',           exts: ['mp4', 'webm', 'mov', 'mkv', 'avi'] },
  { key: 'audio',  label: '音频',        icon: 'ri-music-2-fill',         exts: ['mp3', 'wav', 'm4a', 'ogg', 'flac'] },
  { key: 'office', label: '办公文档',    icon: 'ri-briefcase-4-fill',     exts: ['docx', 'doc', 'pptx', 'ppt', 'xlsx', 'xls'] },
  { key: 'web',    label: '网页 · 原型', icon: 'ri-window-fill',          exts: ['html', 'htm'] },
  { key: 'text',   label: '文本 · 报告', icon: 'ri-file-text-fill',       exts: ['md', 'txt', 'pdf'] },
];

function _shelfTypeOf(it) {
  const ext = String(it.name || '').split('.').pop().toLowerCase();
  for (const t of _SHELF_TYPES) if (t.exts.includes(ext)) return t;
  return { key: 'other', label: '其他', icon: 'ri-file-fill', exts: [] };
}

function _shelfByType(kind, list, cap) {
  const map = new Map();
  for (const it of list) {
    const t = _shelfTypeOf(it);
    if (!map.has(t.key)) map.set(t.key, { t: t, arr: [] });
    map.get(t.key).arr.push(it);
  }
  const order = _SHELF_TYPES.map(t => t.key).concat(['other']);
  return '<div class="shelf-groups">' + order.filter(k => map.has(k)).map(k => {
    const g = map.get(k);
    return _shelfGroup({
      icon: g.t.icon, tinted: true, count: g.arr.length,
      title: g.t.label,
      hint: (g.arr.length > cap ? '共 ' + g.arr.length + ' 条，这里只列前 ' + cap : ''),
      body: _shelfGrid(kind, g.arr.slice(0, cap), 0),
    });
  }).join('') + '</div>';
}

// ══════════════════════════════════════════════════════════════════
// 网格 / 文件夹视图 (wish-1dc9c39d · 用户 2026-09-19)
// 用户 原话:「按应用其实我想要那种类似 WIN10 文件夹的，图片能显示缩略图，文档的话
//   就显示文档（WORD EXCEL PPT 等等）图标，进去后也不是单纯的横条，而是卡片，
//   就说白了照着 windows 的那种文件夹管理来做就好，因为工坊产物东西太杂了」
//
// 判据: 东西杂的 (工坊产物 / 档案 / 原型) → 网格或文件夹; 文档型的 (报告 / 演示稿 /
//   表格) → 保留宽卡片 —— 那些卡上有「查看 & 批注 / 历史版本 / 用这版继续」几个
//   按钮，瓦片里塞不下。
// ══════════════════════════════════════════════════════════════════

// 视图相关的旧状态已并入 _shelfOrg (见上方「组织方式」段) —— _shelfView/_shelfViewOf/
// switchShelfView/_SHELF_VIEW_DEFAULT 全部退役 · 别再加回来。

// 进一个 app 文件夹 —— 复用搜索框 (零新状态 · 输 app 名或标签都能命中)
// 真进文件夹 (wish-1dc9c39d 二次 · 用户:「你现在的应用分组有问题，文件夹是打不开的」)
// 以前是把 app 名塞进搜索框 —— 但搜索框只过滤 .report-card · 网格瓦片不是那个类 ·
// 过滤完什么也不剩。改成状态 + 面包屑 + 返回。
let _shelfFolder = '';   // 非空 = 站在这个 app 文件夹里 (存 app_id)

function shelfEnterFolder(appId) {
  _shelfFolder = String(appId || '');
  _shelfPage = 1;
  if (_shelfLastData) renderReports(_shelfLastData);
}

function shelfExitFolder() {
  _shelfFolder = '';
  _shelfPage = 1;
  if (_shelfLastData) renderReports(_shelfLastData);
}

// 文件夹里 —— 里层用什么摆法同样按内容判 (纯文档→列表 · 有媒体→网格)
function _shelfFolderView(list, kind) {
  const sub = list.filter(it => String(it.app_id || '') === _shelfFolder);
  if (!sub.length) { _shelfFolder = ''; return _shelfFolders(list, kind); }
  const label = sub[0].app_label || _shelfFolder;
  const inner = _shelfAutoOrg(sub, false);
  // 文件夹里层也要限流 —— 「散件（没归到某个应用）」那堆有 2858 条, 全渲直接把页面顶死
  //   (用户 2026-09-19「点了视频分类之后卡的不行了, 最后直接崩了」)。
  //   限流不等于藏起来: sg-more 会写明「共 N 个 · 只列前 20 个」, 那个 N 是真的。
  const _fcap = SHELF_GROUP_CAP;
  const _fmore = sub.length > _fcap
    ? '<div class="sg-more">共 <b>' + sub.length + '</b> 个 · 这里只列前 ' + _fcap + ' 个（点「全部应用」回去 · 或换个摆法看）</div>'
    : '';
  const body = (inner === 'list')
    ? '<div class="reports-list">' + sub.slice(0, _fcap).map(it => _shelfCard(it, kind)).join('') + '</div>' + _fmore
    : _shelfGrid(kind, sub, _fcap);
  return '<div class="fld-crumb">'
    + '<button type="button" class="fld-back" onclick="shelfExitFolder()"><i class="ri-arrow-left-line"></i> 全部应用</button>'
    + '<span class="fld-cur"><i class="ri-folder-3-fill"></i> ' + escHtml(label) + '</span>'
    + '<span class="fld-cn">' + sub.length + ' 个文件</span>'
    + '</div>' + body;
}

// 瓦片正面用什么画 —— 复用 doc-shelf.js 的 _DOC_ICON_MAP (同一份判据 · 不另写一张表)
const _TILE_IMAGE = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp'];
// ⚠ 和 viewer.js 的 VID、下面 _SHELF_TYPES 的 video 三张表必须对齐。
//   曾经 _TILE_VIDEO 漏了 mkv/avi，而 _SHELF_TYPES 认 → 同一个 .mkv 在「按类型」里
//   归视频组、瓦片里却显示文件图标、卡片上却又确实能预览。别只改一处。
const _TILE_VIDEO = ['mp4', 'webm', 'mov', 'mkv', 'avi'];

function _tileExt(it) {
  return String((it && it.name) || '').split('.').pop().toLowerCase();
}

function _tileIcon(ext) {
  if (typeof _DOC_ICON_MAP !== 'undefined' && _DOC_ICON_MAP[ext]) return _DOC_ICON_MAP[ext];
  return 'ri-file-fill';
}

// 图标颜色 —— 类型一眼分得出 (用户:「文档在缩略图视图当中，你要按照不同的文档，
//   图标不同，图标颜色也不同」) · 色值在 chat.css 的 .tile-ico.t-*
const _DOC_TINT = {
  docx: 't-word', doc: 't-word',
  xlsx: 't-xls', xls: 't-xls',
  pptx: 't-ppt', ppt: 't-ppt',
  pdf: 't-pdf', md: 't-md', txt: 't-txt',
  html: 't-web', htm: 't-web',
  json: 't-code', py: 't-code', js: 't-code', ts: 't-code', css: 't-code', sql: 't-code', sh: 't-code',
  zip: 't-zip', '7z': 't-zip', rar: 't-zip',
};
function _tileTint(ext) { return _DOC_TINT[String(ext || '').toLowerCase()] || ''; }

// 一张瓦片 —— 图片出真缩略图 · 视频出首帧 + 播放角标 · 其余出类型图标 (Word/Excel/PPT/MD)
function _shelfTile(it, kind) {
  const openRel = it.open_path || '';
  const ext = _tileExt(it);
  const src = '/stage/file/' + encodeURI(openRel) + '?token=' + encodeURIComponent(token || '');
  const title = it.title || it.name || '';
  let face;
  if (_TILE_IMAGE.includes(ext)) {
    face = '<img loading="lazy" src="' + src + '" alt="">';
  } else if (_TILE_VIDEO.includes(ext)) {
    // 视频瓦片**绝不能** preload="metadata" —— 一屏 20 个还好, 但滑到底 / 进文件夹 / 选「全部」
    //   时就会一次挂上千个 <video>, 浏览器同时去拉元数据 = 页面卡死然后崩
    //   (用户 2026-09-19:「我随便点了点产物之后，发现页面卡的不行了，最后直接崩了」)。
    //   preload="none" = 一个字节都不拉, 点了才加载; 空态靠 CSS 灰底 + 播放图标撑住脸。
    face = '<video preload="none" muted playsinline><source src="' + src + '"></video>'
      + '<i class="ri-play-circle-fill tile-play"></i>';
  } else {
    face = '<i class="' + _tileIcon(ext) + ' tile-ico ' + _tileTint(ext) + '"></i>';
  }
  const on = !!it.is_favorited;
  const spath = String(openRel || '').trim();
  return '<div class="sg-tile' + (on ? ' on' : '') + (spath ? ' sg-pickable' : '') + '"'
    + (spath ? ' data-shelf-path="' + escHtml(spath) + '"' : '') + '>'
    + '<a class="tile-face" href="javascript:void(0)" data-tile-open="' + escHtml(openRel) + '" title="' + escHtml(openRel) + '">' + face + '</a>'
    + '<div class="tile-foot">'
    + '<span class="tile-name" title="' + escHtml(title) + '">' + escHtml(title) + '</span>'
    + '<span class="tile-meta">' + escHtml(fmtShelfSize(it.size_kb)) + ' · ' + escHtml(String(it.created_at || '').slice(5, 16)) + '</span>'
    + '</div>'
    + '<div class="tile-acts">'
    + (openRel ? '<button type="button" class="ta-btn" data-fav-ref="' + escHtml(openRel) + '" data-fav-title="' + escHtml(title) + '" title="收藏"><i class="ri-star-' + (on ? 'fill' : 'line') + '"></i></button>' : '')
    + (openRel ? '<button type="button" class="ta-btn" data-open-view="' + escHtml(openRel) + '" title="预览"><i class="ri-eye-line"></i></button>' : '')
    + '<a class="ta-btn" href="' + escHtml(src) + '" download="' + escHtml(it.name || '') + '" title="下载"><i class="ri-download-line"></i></a>'
    + '</div>'
    + '</div>';
}

function _shelfGrid(kind, list, cap) {
  const shown = cap ? list.slice(0, cap) : list;
  return '<div class="shelf-grid">' + shown.map(it => _shelfTile(it, kind)).join('') + '</div>'
    + (cap && list.length > cap
      ? '<div class="sg-more">共 <b>' + list.length + '</b> 个 · 这里只列前 ' + cap + '个（搜 app 名 或切「列表」看全部）</div>'
      : '');
}

// 文件夹视图: 每个 app 一个格子 (像 Windows 的文件夹缩略图拼贴)
function _shelfFolders(list, kind) {
  // 只认真应用 (app-xxxx) —— _drafts / _tmp_review_run / searches / screenshots 这些
  // 散目录不是「应用」· 混进来会把「按应用」变成一锅乱焍
  // (用户 2026-09-19 实测: 25 个“文件夹”里只有 10 个真 app)。
  const isRealApp = (k) => /^app-[0-9a-z]+$/i.test(String(k || ''));
  const map = new Map();
  for (const it of list) {
    const a0 = String(it.app_id || '');
    const k = isRealApp(a0) ? a0 : '__none__';
    if (!map.has(k)) map.set(k, []);
    map.get(k).push(it);
  }
  const keys = [...map.keys()].filter(k => k !== '__none__')
    .sort((a, b) => map.get(b).length - map.get(a).length);
  if (map.has('__none__')) keys.push('__none__');
  return '<div class="shelf-folders">' + keys.map(k => {
    const g = map.get(k);
    const isNone = (k === '__none__');
    const label = isNone ? '散件（没归到某个应用）' : (g[0].app_label || k);
    // 封面: 图片优先 · 没图就退到视频首帧 (只取前 4 个 · preload=metadata 不会真拉全片)
    const pics = g.filter(x => _TILE_IMAGE.includes(_tileExt(x))).slice(0, 4);
    const vids = pics.length ? [] : g.filter(x => _TILE_VIDEO.includes(_tileExt(x))).slice(0, 4);
    let cover;
    if (pics.length) {
      cover = '<div class="fld-grid n' + pics.length + '">' + pics.map(p =>
        '<img loading="lazy" src="/stage/file/' + encodeURI(p.open_path) + '?token=' + encodeURIComponent(token || '') + '" alt="">').join('') + '</div>';
    } else if (vids.length) {
      cover = '<div class="fld-grid n' + vids.length + '">' + vids.map(p =>
        '<video preload="none" muted playsinline src="/stage/file/' + encodeURI(p.open_path) + '?token=' + encodeURIComponent(token || '') + '"></video>').join('') + '</div>';
    } else {
      cover = '<div class="fld-grid icon"><i class="' + _tileIcon(_tileExt(g[0])) + '"></i></div>';
    }
    const kinds_n = new Set(g.map(x => _tileExt(x))).size;
    return '<a class="fld" href="javascript:void(0)" onclick="shelfEnterFolder(\'' + jsStr(k) + '\')" title="' + escHtml(k) + '">'
      + cover
      + '<div class="fld-foot"><span class="fld-name">' + escHtml(label) + '</span>'
      + '<span class="fld-n">' + g.length + ' 个 · ' + kinds_n + ' 种格式</span></div>'
      + '</a>';
  }).join('') + '</div>';
}

// 「进入话题」的事件委派 (用户 2026-09-20「点了没效果」的修法)
//   用捕获阶段 —— 抢在 <details>/<summary> 的 toggle 默认行为之前把事件吞掉。
//   只认 data-session-jump, 不依赖内联 onclick 字符串, 也不怕它当时在哪个作用域。
if (!window.__shelfJumpDelegate) {
  window.__shelfJumpDelegate = true;
  document.addEventListener('click', function (e) {
    const t = e.target;
    const btn = (t && t.closest) ? t.closest('[data-session-jump]') : null;
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    shelfJumpToSession(btn.getAttribute('data-session-jump') || '', btn.getAttribute('data-session-name') || '');
  }, true);
}

function _shelfGroup(o) {
  // 用户 2026-09-20 报「进入话题点了没效果」—— 内联 onclick 走 <summary> 里那条路不可靠
  //   (要同时躲 summary 的 toggle 冒泡 + HTML 属性转义 + 全局作用域)。改成 data-* + 捕获阶段事件委派。
  const jump = o.sid
    ? `<button type="button" class="rc-preview-btn shelf-go" data-session-jump="${escHtml(o.sid)}" data-session-name="${escHtml(o.title)}" title="打开这个话题（跳到右侧对话栏里那场）"><i class="ri-arrow-right-up-line"></i> 进入话题</button>`
    : '';
  return `<details class="shelf-group" open>
    <summary class="shelf-group-head">
      <i class="ri-arrow-right-s-line shelf-caret"></i>
      <i class="${o.icon} shelf-gico${o.tinted ? '' : ' faded'}"></i>
      <span class="shelf-gname${o.tinted ? '' : ' faded'}">${escHtml(o.title)}</span>
      <span class="shelf-gn">${o.count}</span>
      <span class="shelf-gwhen">${escHtml(o.hint || '')}</span>
      ${jump}
    </summary>
    <div class="shelf-group-body">${o.body}</div>
  </details>`;
}

// 按会话归堆 ── 会话标题/归属来自后端 _attach_sessions。
// 「无归属」组永远垫底: 它是异常态的收容组 (91% 的稿在这里) · 不该撑着有归属的
function _shelfBySession(kind, list, cap) {
  cap = cap || 20;
  const map = new Map();
  for (const it of list) {
    const k = it.session_id || '__none__';
    if (!map.has(k)) map.set(k, []);
    map.get(k).push(it);
  }
  const keys = [...map.keys()].filter(k => k !== '__none__');
  if (map.has('__none__')) keys.push('__none__');
  return '<div class="shelf-groups">' + keys.map(k => {
    const group = map.get(k);
    if (k === '__none__') {
      return _shelfGroup({
        icon: 'ri-question-line', tinted: false, count: group.length,
        title: '无归属 · 归属机制上线前的老产物',
        hint: '没记下是哪场做的',
        body: group.slice(0, cap).map(it => _shelfCard(it, kind)).join(''),
      });
    }
    return _shelfGroup({
      sid: k, icon: 'ri-chat-3-fill', tinted: true, count: group.length,
      title: group[0].session_label || '（对话已归档）',
      hint: String(group[0].created_at || '').slice(0, 16),
      body: group.slice(0, cap).map(it => _shelfCard(it, kind)).join(''),
    });
  }).join('') + '</div>';
}

// 判据: 这份产物该「中栏打开」还是「报告预览」?
//   html / md / pdf / 图片 / 视频 → 中栏 (stage.js 的 stageClassify 说了算)
//   office (docx/pptx/xlsx) → 沿用原 loadReportPreview (reports 那套反推预览)
// 2026-09-19 原病: 图片也走了 loadReportPreview → 打 /reports/preview/x.jpg → 404
//   → 用户 原话「现在图片什么的完全打不开」。
const _SHELF_MEDIA_MODES = { image: 1, video: 1, pdf: 1, html: 1, md: 1 };

function _shelfOpenMode(rel) {
  if (typeof stageClassify !== 'function' || !rel) return '';
  try {
    const c = stageClassify(rel);
    return (c && _SHELF_MEDIA_MODES[c.mode]) ? c.mode : '';
  } catch (e) { return ''; }
}

// 单张产物卡 (从 renderReports 原循环体原样抽出 · 行为一字未改 · 只多了药丸)
// 「看它」的统一出口 (用户 2026-09-19):
//   能圈字批注的 (md / html / office) → 中栏;  只能看的 (图 / 视频 / 音频 / PDF) → 通用浮层。
//   判据只此一份 —— 产物卡 / 网格瓦片 / 工坊 app 卡都走这里。
//   为什么不再一律中栏: 用户「这些图片和视频类的，也要用中栏看嘛？…不然每次中栏看
//   再回来就要重新加载打开很麻烦」。中栏是工作区，瞄一眼不该占它。
function _shelfOpenRel(rel, el) {
  if (!rel) return;
  if (window.OpusViewer && OpusViewer.canView(rel)) {
    // 同批媒体一起递给浮层 → 里面能 ←→ 翻。从 DOM 现查 (不额外传数据 · 不存状态)
    const scope = (el && (el.closest('.reports-list') || el.closest('.shelf-group-body') || el.closest('.dash-view'))) || $dashView;
    const items = [];
    const seen = new Set();
    let idx = 0;
    scope.querySelectorAll('[data-open-view], [data-tile-open]').forEach(n => {
      const p = n.getAttribute('data-open-view') || n.getAttribute('data-tile-open');
      if (!p || seen.has(p) || !OpusViewer.canView(p)) return;
      seen.add(p);
      if (p === rel) idx = items.length;
      items.push({ path: p, name: String(p).split('/').pop() });
    });
    OpusViewer.open({ path: rel, name: String(rel).split('/').pop(), items: items.length > 1 ? items : null, idx: idx });
    return;
  }
  // 预览出口：只是「看一眼」· **不挂载**（2026-09-29 用户:「点开历史的预览就挂进对话了」）
  if (typeof openStage === 'function') openStage({ path: rel });
}

function _shelfCard(it, kind0) {
  // 收藏视图是跨类型的 → 每项自带 _kind; 其它视图 kind0 就是整批类型
  const kind = it._kind || kind0;
  const rawDl = it.download_url || (kind === 'decks' ? `/presentations/${it.name}` : (kind === 'sheets' ? `/spreadsheets/${it.name}` : (kind === 'protos' || kind === 'design' ? `/stage/file/data/design/${it.name}` : `/reports/${it.name}`)));
  const dlUrl = `${rawDl}${rawDl.includes('?') ? '&' : '?'}token=${encodeURIComponent(token || '')}`;
  const previewUrl = it.preview_url || '';
  // 预制应用四维 (design/dev/docs/content) 都是「有源文件」的 md/html —— 可中栏预览 · 可让我改
  const _isPreset = ['design', 'dev', 'docs', 'content'].includes(kind);
  const srcBadge = (_isPreset || kind === 'protos') && it.has_md_source
    ? `<span class="rc-src-badge rc-src-md" title="有源文件 · 中栏预览，跟我说改">可改</span>`
    : (it.has_md_source
    ? `<span class="rc-src-badge rc-src-md" title="有源文件">有源文件</span>`
    : `<span class="rc-src-badge rc-src-extract" title="${kind === 'decks' ? '没有源文件 · 下载用本机软件打开' : (kind === 'sheets' ? '没有源文件 · 成品仍可看表' : '旧报告 · 预览是从成品反推的')}">${kind === 'decks' || kind === 'sheets' ? '没有源文件' : '旧版预览'}</span>`);
  const kbBtn = kind === 'reports'
    ? `<button class="rc-preview-btn rp-kb" data-name="${escHtml(it.name)}" title="存进知识库，之后回答能引用原文"><i class="ri-book-2-line"></i> 存入知识库</button>`
    : '';
  const openRel = it.open_path || (kind === 'decks' ? ('data/presentations/' + it.name) : (kind === 'sheets' ? ('data/spreadsheets/' + it.name) : (kind === 'protos' ? ('data/design/' + it.name) : ('data/reports/' + it.name))));
  const reviseBtn = (kind === 'protos' || _isPreset)
    ? `<button type="button" class="rc-preview-btn" data-revise="${escHtml(openRel)}" title="丢给对话，按你的话改这份"><i class="ri-pencil-line"></i> 让我改</button>`
    : '';
  const showName = it.title || it.name;
  const ver = it.version ? `<span class="rc-ver">V${it.version}</span>` : '';
  const hist = Array.isArray(it.history) ? it.history : [];
  let histHtml = '';
  if (hist.length) {
    const rows = hist.map((h, i) => {
      const hv = h.version || ((it.version || (hist.length + 1)) - 1 - i);
      const lo = h.version_lo || hv;
      const verLabel = (h.dupes > 1 && lo && lo !== hv) ? (`V${lo}–V${hv}`) : (`V${hv}`);
      const hop = h.open_path || openRel;
      const hpv = shelfPreviewUrl(kind, h.name || '');
      const hdl = `${h.download_url || rawDl}${((h.download_url || rawDl).includes('?') ? '&' : '?')}token=${encodeURIComponent(token || '')}`;
      const dupe = h.dupes > 1 ? `<span class="rc-dupe">同一份 · 记了 ${h.dupes} 次</span>` : '';
      const pg = h.pages ? `<span class="rc-pages">${h.pages} 页</span>` : '';
      return `<div class="rc-hist-row"><span class="rc-ver">${verLabel}</span><span class="rc-size">${escHtml(fmtShelfSize(h.size_kb))}</span>${pg}<span class="rc-time">${escHtml(h.created_at || '')}</span>${dupe}`
        + `<button type="button" class="rc-preview-btn" data-open-rel="${escHtml(hop)}" title="浮层里看这一版（Esc 关掉）"><i class="ri-eye-line"></i> 预览</button>`
        + `<button type="button" class="rc-preview-btn rc-restore" data-restore="${escHtml(h.name || '')}" data-kind="${escHtml(kind)}" title="不会删任何旧文件。把这版抄成当前，现在的当前会另存进历史。"><i class="ri-arrow-go-back-line"></i> 用这版继续</button>`
        + `<button type="button" class="rc-preview-btn" data-open="${escHtml(hop)}" title="用本机软件打开"><i class="ri-external-link-line"></i></button>`
        + `<a class="rc-dl" href="${escHtml(hdl)}" download="${escHtml(h.name || '')}">下载</a></div>`;
    }).join('');
    histHtml = `<details class="rc-hist"><summary>历史 ${hist.length} 份</summary><p class="rc-hist-hint">卡片「预览」是当前这份。要看旧样子，点下面体积大、页数多的那行「预览」。顶栏必须出现「历史 Vx」，才是旧稿。</p>${rows}</details>`;
  }
  const openMode = _shelfOpenMode(openRel);
  const _imgRe = /\.(png|jpe?g|gif|webp)$/i;
  // 入口分开 (wish-1dc9c39d 二次 · 用户:「应用里面图片的预览，还和批注中栏那个功能混了」):
  //   能圈字批注的 (md / html / office) → 「查看 & 批注」; 只能看的 (图/视频/音频/PDF) → 「看大图」。
  //   判据复用 _shelfTypeOf (同一份后缀表 · 不另写一张)。
  const _tKey = _shelfTypeOf(it).key;
  const _isPdf = /\.pdf$/i.test(String(it.name || ''));
  const _annotatable = !_isPdf && ['web', 'office', 'text'].includes(_tKey);
  // 「预览」= 浮层。只给「浮层里真能看的」: 图 / 视频 / 音频 / PDF / 文稿(md)。
  //   html / office 不给 —— 它俩没有「只读看一遍」这种用法, 主场是中栏 (能看还能圈字批注),
  //   浮层是它的子集, 多一个按钮只是噪音。空格子旁边杵两个长得差不多的钮, 点击就很迷茫。
  //   用户 2026-09-19:「不支持的格式就不要有预览了吧？不然相当于多个无用的按钮」
  // 注: 另一个大坑 —— 卡片上原来有两处各出一个「预览」(previewUrl 那处 + _viewable 那处),
  //   md 两条都命中 → 真的并排两个「预览」。已收成一处 (同一件事两处各写一份判据 = 必然分叉)。
  const _viewable = _isPdf || ['image', 'video', 'audio', 'text'].includes(_tKey);
  const thumb = (openMode && _imgRe.test(String(it.name || '')))
    ? `<a class="rc-thumb" href="javascript:void(0)" data-open-view="${escHtml(openRel)}" title="点一下看大图（浮层 · Esc 关掉）"><img loading="lazy" src="/stage/file/${encodeURI(openRel)}?token=${encodeURIComponent(token || '')}" alt=""></a>`
    : '';
  // 左侧那格 (用户 2026-09-19:「会话是列表风格，然后最左侧有一张缩略图看」):
  //   图片 = 真缩略图; 其余 = 带色的类型图标 (Word蓝/Excel绿/PPT橙… 见 _DOC_TINT)
  const _td = _tileExt(it);
  const side = thumb || `<span class="rc-side-ico ${_tileTint(_td)}"><i class="${_tileIcon(_td)}"></i></span>`;
  // 2026-09-20 · 照原型重排 (用户:「和你给我看的原型根本不是一个东西？？」)—— 上一版只调了
  //   CSS 三处, 结构还是“一堆按钮平铺在第二行”, 跟原型差得远。这次真改结构:
  //   第一行只有标题 + ⭐; 第二行 = 版本/来源/💬归属/时间 …… 右脚 = 大小 + 主操作 + ⋯。
  //   次要操作(查看&批注 / 让我改 / 存入知识库 / 下载)全收进 ⋯ 菜单 —— 卡片从~90px 降到~64px。
  //   ⚠ 所有 data-* 绑定原样搬运 (只是换位置), 收藏/预览/批注/改/存知识库照旧。
  // 2026-09-20 三次 (用户:「点击文件名就是查看批注的中栏显示, 所以右侧按钮应该就是留个预览
  //   (或者本机应用打开), 能弹框的弹框快速查看」):
  //   主按钮 = 能弹框快速看的给「预览」, 弹不了框的给「本机应用打开」;
  //   「查看 & 批注」退回 ⋯ (中栏那条路走文件名点击就行, 不用再占主位), 留着是因为不一定人人知道点文件名。
  const _primary = _viewable
    ? `<button class="rc-preview-btn rc-main" data-open-view="${escHtml(openRel)}" title="弹框快速看一眼（Esc 关掉）"><i class="ri-eye-line"></i> 预览</button>`
    : `<button class="rc-preview-btn rc-main" data-open="${escHtml(openRel)}" title="用本机软件打开它"><i class="ri-external-link-line"></i> 本机应用打开</button>`;
  const _more = [
    _annotatable ? `<button class="rc-preview-btn rc-annotate" data-annotate="${escHtml(openRel)}" title="铺到中栏 · 圈字批注 / 加图（点文件名同效）"><i class="ri-quill-pen-line"></i> 查看 &amp; 批注</button>` : '',
    _viewable ? `<button class="rc-preview-btn" data-open="${escHtml(openRel)}" title="用本机软件打开它"><i class="ri-external-link-line"></i> 本机应用打开</button>` : '',
    reviseBtn,
    kbBtn,
    `<a class="rc-dl" href="${escHtml(dlUrl)}" download="${escHtml(it.name)}"><i class="ri-download-2-line"></i> 下载</a>`,
  ].filter(Boolean).join('');
  return `
    <div class="report-card rc-compact"${openRel ? ` data-shelf-path="${escHtml(openRel)}"` : ''}>
      <div class="rc-side">${side}</div>
      <div class="rc-body">
      <div class="rc-head">
        <a class="rc-name" href="javascript:void(0)" data-name="${escHtml(it.name)}" data-preview-url="${escHtml(previewUrl)}" data-preview="1" data-open-rel="${escHtml(openRel)}">
          ${escHtml(showName)}
        </a>
        <span class="rc-pill-slot">${_shelfStar(it)}</span>
      </div>
      <div class="rc-meta">
        ${ver}
        ${srcBadge}
        ${_shelfPill(it)}
        <span class="rc-time">${escHtml(it.created_at)}</span>
        ${it.pages ? `<span class="rc-pages">${it.pages} 页</span>` : ''}
        <span class="rc-size">${escHtml(fmtShelfSize(it.size_kb))}</span>
        ${_primary}
        ${_more ? `<details class="rc-more"><summary title="更多操作"><i class="ri-more-fill"></i></summary><div class="rc-more-menu">${_more}</div></details>` : ''}
      </div>
      </div>
      ${histHtml}
    </div>`;
}

function reviseShelfProto(path) {
  const rel = String(path || '').replace(/\\/g, '/');
  if (!rel || typeof spawnTask !== 'function') return;
  spawnTask(
    '改 HTML 原型 `' + rel + '` · 先 read_file 看现在的结构 · 按我接下来的要求改 (edit_file) · 改完中栏刷新能看到。我先点开了这份，你等我说改哪里。',
    '改原型'
  );
  // 明确「让我改」→ 挂进本场（显式 bind:true）
  if (typeof openStage === 'function') openStage({ path: rel, bind: true });
}

function renderReports(data) {
  _shelfPreviewOpen = false;
  _shelfLastData = data;
  if (data && data.error) {
    $dashView.innerHTML = `
      <div class="dash-head"><h2><i class="ri-archive-2-fill"></i> 产物库</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }
  const kinds = (data && data.kinds) || {};
  const reports = kinds.reports || {
    items: (data && data.items) || [],
    count: ((data && data.items) || []).length,
    directory: (data && data.directory) || 'data/reports',
  };
  const decks = kinds.decks || { items: [], count: 0, directory: 'data/presentations' };
  const sheets = kinds.sheets || { items: [], count: 0, directory: 'data/spreadsheets' };
  // ── 预制应用四维 (一级 presets · 二级 design/dev/docs/content · 与内置应用同名) ──
  const presets = kinds.presets || {};
  const subs = presets.subs || {};
  const _subPack = (k, fb) => subs[k] || kinds[k] || { items: [], count: 0, directory: fb, label: k };
  const design = _subPack('design', 'data/design');
  const dev = _subPack('dev', 'data/dev');
  const docs = _subPack('docs', 'data/docs');
  const content = _subPack('content', 'data/content');
  const workshop = kinds.workshop || { items: [], count: 0, directory: 'data/workshop/outputs' };
  // 每项挂上自己的 _kind —— _shelfCard 靠它画对的下载链 / 打开路径 / 徽章
  //   ⚠ 2026-09-20 修: 原先这里直接展开原始 items · 没打标 → 「全部」视图里演示稿/表格
  //   的下载与打开全按报告走 (/reports/xxx) · 是错的。复用下面 _all 用的同一支 _tag。
  const _tag = (arr, k) => (arr || []).map(i => Object.assign({}, i, { _kind: k }));
  // 「全部」总览的一篮子 = 六个文档型类目 (工坊产物不进这篮 —— 2858 条 + 已有自己的
  //   文件夹视图, 混进来就是 2026-09-19 那次「随便点一下就卡崩」的老病; 想看它点自己的 tab)
  const _allDocs = [
    ..._tag(reports.items, 'reports'), ..._tag(decks.items, 'decks'), ..._tag(sheets.items, 'sheets'),
    ..._tag(design.items, 'design'), ..._tag(dev.items, 'dev'), ..._tag(docs.items, 'docs'), ..._tag(content.items, 'content'),
  ];
  const kind = _SHELF_KINDS.includes(_shelfKind) ? _shelfKind : 'all';
  const pack = (kind === 'presets')
    ? ({ design: design, dev: dev, docs: docs, content: content }[_shelfSub] || design)
    : (kind === 'all')
    ? ({ items: _allDocs, count: _allDocs.length, directory: 'data/reports' })
    : ({ decks: decks, sheets: sheets, workshop: workshop }[kind] || reports);
  // ⭐ 收藏视图 · 跨 6 类合并 + 只留 is_favorited (用户 2026-09-18: 不想两头点)
  //    数据就是左栏收藏夹那套 favorites.json · 没有第二份。
  //    每项挂上 _kind → _shelfCard 才能画出对的下载链/徽章 (否则全按报告画)
  //    ⚠ 新两类也要进来 —— 否则「收了 data/dev 的档案·收藏视图里还是找不到」(wish-1dc9c39d)
  //   (_tag 定义已上提到 _allDocs 之前 · 两处共用同一支)
  const _all = [..._tag(reports.items, 'reports'), ..._tag(decks.items, 'decks'),
                ..._tag(sheets.items, 'sheets'),
                ..._tag(design.items, 'design'), ..._tag(dev.items, 'dev'),
                ..._tag(docs.items, 'docs'), ..._tag(content.items, 'content'),
                ..._tag(workshop.items, 'workshop')];
  // 2026-09-28 · 数据没拉全时收藏数算不准 —— 宁可空着等后台补齐，也不报假数
  const _favReady = ['reports', 'decks', 'sheets', 'workshop'].every(k => kinds[k] && kinds[k].deferred !== true)
    && !Object.values(subs).some(s => s && s.deferred);
  const nFav = _favReady ? _all.filter(i => i.is_favorited).length : '';
  const items = (kind === 'fav') ? _all.filter(i => i.is_favorited) : (pack.items || []);
  const dir = pack.directory || 'data/reports';
  // 2026-09-28 · count 为 null（那一格这轮没拉）= 先不显示数字，等后台补齐。
  //   原来显示「…」—— 一排省略号看着像“还有更多”，比空着更糟（用户 当场否掉）。
  const _nOf = (p) => (p && p.count != null) ? p.count
    : ((p && p.deferred) ? '' : (((p && p.items) || []).length));
  const nR = _nOf(reports);
  const nD = _nOf(decks);
  const nS = _nOf(sheets);
  const _pDefer = Object.values(subs).some(s => s && s.deferred);
  const nP = (presets.count != null) ? presets.count
    : (_pDefer ? '' : ((design.count || 0) + (dev.count || 0) + (docs.count || 0) + (content.count || 0)));
  const nW = _nOf(workshop);
  // 回收站件数（后端 list_shelf 顺手给的 · 不进索引缓存）—— 给 tab 上的数字用
  const trashN = (data && typeof data.trash_count === 'number') ? data.trash_count : '';

  let html = `
    <div class="dash-head">
      <h2><i class="ri-archive-2-fill"></i> 产物库</h2>
      <div class="dh-chips">
        <div class="dh-chip" title="报告库里的文件数"><b>${nR}</b><span>报告</span></div>
        <div class="dh-chip" title="演示稿文件数"><b>${nD}</b><span>演示稿</span></div>
        <div class="dh-chip" title="表格文件数"><b>${nS}</b><span>表格</span></div>
        <div class="dh-chip" title="预制应用产出数"><b>${nP}</b><span>预制</span></div>
        <div class="dh-chip" title="工坊产物数"><b>${nW}</b><span>工坊</span></div>
      </div>
      <button class="btn-ghost" onclick="backToChat()">收起</button>
      <button class="btn-primary" onclick="loadDashboard('reports')">刷新列表</button>
    </div>
    <div class="dash-note"><i class="ri-folder-2-line"></i> 成品层 · 共 ${items.length} 份 · ${kind === 'all' ? '六个类目混排' : escHtml(dir)}</div>
    <div class="depot-tabs" role="tablist">
      <button type="button" class="depot-tab${kind === 'all' ? ' active' : ''}" onclick="switchShelfKind('all')"
              title="全库混排 · 报告 / 演示稿 / 表格 / 预制应用 · 最近改过的排最前（工坊产物太多，单列在右边那格）">
        <i class="ri-apps-2-line"></i><span>全部</span><span class="shelf-n">${_favReady ? _allDocs.length : ''}</span>
      </button>
      <button type="button" class="depot-tab${kind === 'reports' ? ' active' : ''}" onclick="switchShelfKind('reports')">
        <i class="ri-article-fill"></i><span>报告</span><span class="shelf-n">${nR}</span>
      </button>
      <button type="button" class="depot-tab${kind === 'decks' ? ' active' : ''}" onclick="switchShelfKind('decks')">
        <i class="ri-slideshow-fill"></i><span>演示稿</span><span class="shelf-n">${nD}</span>
      </button>
      <button type="button" class="depot-tab${kind === 'sheets' ? ' active' : ''}" onclick="switchShelfKind('sheets')">
        <i class="ri-table-fill"></i><span>表格</span><span class="shelf-n">${nS}</span>
      </button>
      <button type="button" class="depot-tab${kind === 'presets' ? ' active' : ''}" onclick="switchShelfKind('presets')"
              title="内置应用的产出 · 二级四个维度（产品设计 / 产品开发 / 文档撰写 / 内容制作）">
        <i class="ri-apps-2-fill"></i><span>预制应用</span><span class="shelf-n">${nP}</span>
      </button>
      <button type="button" class="depot-tab${kind === 'workshop' ? ' active' : ''}" onclick="switchShelfKind('workshop')"
              title="出品工坊里 app 跑出来的成品 (data/workshop/outputs) —— 车间出的活儿也算我的东西">
        <i class="ri-hammer-fill"></i><span>工坊产物</span><span class="shelf-n">${nW}</span>
      </button>
      <button type="button" class="depot-tab shelf-trash-tab${kind === 'trash' ? ' active' : ''}" onclick="switchShelfKind('trash')"
              title="删掉的产物先放这儿 · 留 30 天 · 过期自动清 · 可逐件还原">
        <i class="ri-delete-bin-6-line"></i><span>回收站</span><span class="shelf-n">${typeof trashN === 'number' ? trashN : ''}</span>
      </button>
      <button type="button" class="depot-tab shelf-fav-tab${kind === 'fav' ? ' active' : ''}" onclick="switchShelfKind('fav')"
              title="只看收藏过的产物 · 跟左栏「收藏夹 → 我的产物」是同一份">
        <i class="ri-star-${kind === 'fav' ? 'fill' : 'line'}"></i><span>收藏</span><span class="shelf-n" id="shelfFavN">${nFav}</span>
      </button>
    </div>`;

  // 预制应用的二级 (用户:「做成二级 · 不然用户看了也容易混」) —— 只在选中一级时出现
  // 名字直接用内置应用名 (p.label 来自后端 draft_studio 那四个 domain) · 不另起别名
  if (kind === 'presets') {
    const _subPacks = { design: design, dev: dev, docs: docs, content: content };
    html += `<div class="depot-tabs depot-subtabs" role="tablist">
      ${_SHELF_SUBS.map(sk => {
        const p = _subPacks[sk] || {};
        return `<button type="button" class="depot-tab${_shelfSub === sk ? ' active' : ''}" onclick="switchShelfSub('${sk}')"
                title="${escHtml(p.where || '')}">
          <span>${escHtml(p.label || sk)}</span><span class="shelf-n">${p.deferred ? '' : (p.count || 0)}</span>
        </button>`;
      }).join('')}
    </div>`;
  }

  // 2026-09-28 · 这一格这轮还没拉（deferred）→ 说「正在取」，不能说「还没有 XX」
  //   那是假空态：工坊明明有 2959 条，却告诉 用户「还没有工坊产物」（他当场抓出来了）
  const _packDeferred = (kind === 'presets' || kind === 'all' || kind === 'fav')
    ? _shelfMissing(kinds, kind).length > 0
    : !!(kinds[kind] && kinds[kind].deferred === true);
  // ── 「回收站」不是产物类目：有自己的面板，不进排序 / 分页 / 搜索那一套 ──
  if (kind === 'trash') {
    html += _shelfTrashInline();
  } else if (items.length === 0 && _packDeferred) {
    html += `<div class="dash-stub">
      <h3>正在取这一格…</h3>
      <div>产物库先只算了「报告」这一格（它最快），其余在后台补 —— 一两秒就好。</div>
    </div>`;
  } else if (items.length === 0) {
    html += kind === 'all' ? `
      <div class="dash-stub">
        <h3>产物库还是空的</h3>
        <div>跟我做点什么，产出的东西会汇到这里。</div>
      </div>` : kind === 'fav' ? `
      <div class="dash-stub">
        <h3>还没收藏过产物</h3>
        <div>在卡片上点 <i class="ri-star-line"></i> 就能收藏 —— 收的都在这里，跟左栏「收藏夹 → 我的产物」是同一份数据。</div>
      </div>` : kind === 'decks' ? `
      <div class="dash-stub">
        <h3>还没生成过演示稿</h3>
        <div>跟我说做PPT，文件会出现在这里。</div>
      </div>` : kind === 'sheets' ? `
      <div class="dash-stub">
        <h3>还没生成过表格</h3>
        <div>跟我说做表格，文件会出现在这里。</div>
      </div>` : kind === 'presets' ? `
      <div class="dash-stub">
        <h3>这一格还是空的</h3>
        <div>${escHtml((pack && pack.label) || '')} · ${escHtml((pack && pack.where) || '')}</div>
      </div>` : kind === 'workshop' ? `
      <div class="dash-stub">
        <h3>还没有工坊产物</h3>
        <div>出品工坊里 app 跑出来的成品会汇到这里。</div>
      </div>` : `
      <div class="dash-stub">
        <h3>还没生成过报告</h3>
        <div>跟我说写报告，文件会出现在这里。</div>
      </div>`;
  } else {
    html += _shelfBar(kind, items);
    html += _shelfBody(kind, items);
  }
  const _prevShelfScroll = $dashView.scrollTop;
  $dashView.innerHTML = html;
  if (_prevShelfScroll > 0) $dashView.scrollTop = _prevShelfScroll;

  // 2026-09-28 · 首屏只带了 reports（42ms 秒出）· 其余类目在后台补齐（只补一次）——
  //   数字补上、切 tab 不用再等、更不会停在假空态上。
  //   ⚠ 这段必须待在 renderReports 里：第一次改时 old_string（`$dashView.innerHTML = html;`）
  //     在全文出现 5 次，静默命中了 renderFeasibility 那一处 —— 而那里没有 kinds 这个变量，
  //     整段一执行就抛 ReferenceError，补齐永远不触发（表里数字永远空着）。
  if (!_shelfRefilling && _shelfMissing(kinds, 'fav').length) {
    _shelfRefilling = true;
    _shelfEnsure('fav').then(d => {
      _shelfRefilling = false;
      // 补上了才重渲 —— 失败时 _shelfEnsure 返回原数据、missing 仍在，
      // 若照样重渲就成了「渲染→补齐→失败→再渲染」空转（这个判断 = 根本不会发生）
      if (d && !_shelfMissing(d.kinds, 'fav').length) renderReports(d);
    });
  }

  // 2026-09-20 · 用户：「点击后这些二级导航又掉回下面·过几秒又会升回去」——
  //   类目切换（switchShelfKind/Sub）直接重渲染·不走 loadDashboard 的收口；
  //   收口只有恰好在途的延迟 timer 才会补上（所以时好时坏）。
  //   这里渲染完立即收口 · 「掉回」窗口归零（350ms 双保险）。
  if (typeof _unifyDashHead === 'function') {
    _unifyDashHead(null, 'reports');
    setTimeout(() => _unifyDashHead(null, 'reports'), 350);
  }

  $dashView.querySelectorAll('.rc-preview-btn:not(.rp-kb):not([data-open]):not([data-restore]):not([data-revise]):not([data-annotate]), .rc-name[data-preview]').forEach(el => {
    el.onclick = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const name = el.getAttribute('data-name');
      const previewUrl = el.getAttribute('data-preview-url');
      // 原型 / 媒体 / 网页 / pdf / md → 中栏
      //  (wish-1dc9c39d: 原来只认 protos · 图片视频全掉进报告预览 → /reports/preview/x.jpg → 404)
      const card = el.closest('.report-card');
      const openEl = card && card.querySelector('[data-open]');
      const rel = el.getAttribute('data-open-rel')
        || (openEl && openEl.getAttribute('data-open'))
        || (kind === 'protos' ? ('data/design/' + name) : '');
      // 「预览」按钮 / 点文件名 → 统一出口。去处按格式自动分 (媒体/md/html → 浮层 · office → 中栏)
      //   不再走 loadReportPreview —— 那条会把整个产物库面板顶掉 (dashView.innerHTML=预览内容),
      //   关掉回来要重新 loadDashboard 拉数据重渲全部, 滚动位置/页码全丢
      //   (用户 2026-09-19:「每次中栏看再回来就要重新加载打开很麻烦」)。
      if (rel) { _shelfOpenRel(rel, el); return; }
      if (name) loadReportPreview(name, previewUrl || undefined);
    };
  });

  // 缩略图 / 瓦片 / 「预览」按钮 → 看图走通用浮层 (即看即走·不顶面板) · 文档走中栏
  //  入口分开 (wish-1dc9c39d 二次): 文档走 [data-annotate]（查看 & 批注）· 这里只管「看」
  $dashView.querySelectorAll('[data-open-view]').forEach(el => {
    el.onclick = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      _shelfOpenRel(el.getAttribute('data-open-view'), el);
    };
  });

  // 网格瓦片 (wish-1dc9c39d): 点面 / 点眼睛 → 同上 · 点星 → 复用 toggleShelfStar
  $dashView.querySelectorAll('.tile-face[data-tile-open]').forEach(el => {
    el.onclick = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      _shelfOpenRel(el.getAttribute('data-tile-open'), el);
    };
  });
  $dashView.querySelectorAll('.ta-btn[data-open-view]').forEach(el => {
    el.onclick = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      _shelfOpenRel(el.getAttribute('data-open-view'), el);
    };
  });
  $dashView.querySelectorAll('.ta-btn[data-fav-ref]').forEach(el => {
    el.onclick = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      if (typeof toggleShelfStar === 'function') toggleShelfStar(el);
    };
  });
  $dashView.querySelectorAll('[data-annotate]').forEach(btn => {
    btn.onclick = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const rel = btn.getAttribute('data-annotate');
      if (rel && typeof _docOpenForAnnotate === 'function') _docOpenForAnnotate(rel);
    };
  });
  $dashView.querySelectorAll('[data-open]').forEach(btn => {
    btn.onclick = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      revealFile(btn.getAttribute('data-open'), btn);
    };
  });
  $dashView.querySelectorAll('[data-revise]').forEach(btn => {
    btn.onclick = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      reviseShelfProto(btn.getAttribute('data-revise'));
    };
  });
  $dashView.querySelectorAll('[data-restore]').forEach(btn => {
    btn.onclick = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      restoreShelfVersion(btn.getAttribute('data-kind'), btn.getAttribute('data-restore'), btn);
    };
  });
  $dashView.querySelectorAll('.rp-kb').forEach(btn => {
    btn.onclick = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      _importReportToKb(btn.getAttribute('data-name'), btn);
    };
  });
  $dashView.querySelectorAll('.rc-star').forEach(btn => {
    btn.onclick = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      toggleShelfStar(btn);
    };
  });

  // 2026-09-30 · 回收站格没有搜索框 → 传 null 进去会让 _applyListFilter 抛
  //   「Cannot read properties of null (reading 'value')」，把这一格整个渲染卡死
  //   （用户 报「点回收站没反应」的真身）。这里明确跳过，函数自己也加 null 闸。
  if (kind !== 'trash' && items.length) _applyListFilter($dashView.querySelector('.list-filter-input'));
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

function setRadarDomainFilter(domain) {
  radarDomainFilter = domain;
  if (domain === 'all') localStorage.removeItem('radar_domain_filter');
  else localStorage.setItem('radar_domain_filter', domain);
  loadDashboard('radar', { silent: true });
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

async function submitOutcomeStatus(opp_id, status) {
  if (!token) return;
  if (!opp_id) return;
  // 只动 status 一个字段·快速切换用
  await _postOutcome(opp_id, { status });
  // 重新加载详情·刷新 UI 状态
  loadFeasibilityDetail(opp_id);
}

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

function wishFromRadar(title, url) {
  if (!title) return;
  const urlPart = url ? `· URL: ${url}` : '';
  spawnTask(
    `用户 邀请你看一眼 self-evolve 雷达上的这个工程：「${title}」${urlPart}\n\n` +
    `**这是邀请·不是命令** —— 你要自己判断·不是 用户 让你装你就装。\n\n` +
    `请你：\n` +
    `1. 用 web_search / web_fetch 弄清这个工程做啥 · 看 README / 主要特性\n` +
    `2. 对照本工作台现状·想清楚：\n` +
    `   - 你有没有这个能力·还是缺\n` +
    `   - 它的设计哲学跟本工作台是否合拍 (人机协同 / 双向认知 / 可追溯)\n` +
    `   - 如果合拍·这能力对 用户 这个具体的人有啥用 (而不是"通用上有用")\n` +
    `3. 然后明确告诉 用户：\n` +
    `   - 值得装 → 调 wish_add 写一份心愿 (title / why / source_kind=radar / source_ref + url / design_sketch / complexity / hours / priority / opus_take = 你自己的态度)\n` +
    `   - 不值得装 → 说清为啥·别强加 wish 占心愿单\n` +
    `   - 拿不准 → 就说拿不准·要 用户 给更多 context\n` +
    `**你才是搭档·不是给 用户 端菜的工具人**·拿出判断力。`,
    `勘察: ${title}`
  );
}


// ─── wish-0c9fdbf4 · 产物库删除 + 回收站 ─────────────────────────────
//
// 用户 2026-09-30 定死的交互：点「删除」进选择模式 · 单击=只选它 · 按住不动=加选。
// 删掉的先进回收站（留 30 天 · 能还原）· 回收站有按钮直接清空。

let _shelfPickOn = false;
const _shelfPicked = new Map();     // path -> {path, name}
let _shelfLpTimer = null;
let _shelfLpFired = false;

function _shelfNameOf(el, p) {
  const n = el.querySelector('.tile-name') || el.querySelector('.rc-title');
  return ((n && n.textContent) || String(p).split('/').pop() || '').trim();
}

function shelfPickMode(on) {
  _shelfPickOn = !!on;
  if (!_shelfPickOn) _shelfPicked.clear();
  document.body.classList.toggle('shelf-picking', _shelfPickOn);
  _shelfPaintPicked();
  _shelfEnsureBar();
}

function _shelfEnsureBar() {
  let bar = document.getElementById('shelfPickBar');
  if (!_shelfPickOn) { if (bar) bar.remove(); return; }
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'shelfPickBar';
    document.body.appendChild(bar);
  }
  const n = _shelfPicked.size;
  bar.innerHTML = '<span class="spb-n">已选 <b>' + n + '</b> 项</span>'
    + '<span class="spb-hint">单击 = 加上或去掉它 · 按住拖过哪几张 = 哪几张一起选</span>'
    + '<span class="spb-sp"></span>'
    + '<button type="button" class="btn-ghost" onclick="shelfPickAll()">全选本页</button>'
    + '<button type="button" class="btn-ghost" onclick="shelfPickMode(false)">取消</button>'
    + '<button type="button" class="spb-danger" onclick="shelfAskDelete()"' + (n ? '' : ' disabled') + '>'
    + '<i class="ri-delete-bin-6-line"></i> 删除</button>';
}

function _shelfPaintPicked() {
  document.querySelectorAll('[data-shelf-path]').forEach((el) => {
    el.classList.toggle('picked', _shelfPicked.has(el.getAttribute('data-shelf-path')));
  });
}

function shelfPickAll() {
  document.querySelectorAll('[data-shelf-path]').forEach((el) => {
    const p = el.getAttribute('data-shelf-path');
    _shelfPicked.set(p, { path: p, name: _shelfNameOf(el, p) });
  });
  _shelfPaintPicked();
  _shelfEnsureBar();
}

function _shelfToggle(el) {
  const p = el.getAttribute('data-shelf-path');
  if (!p) return;
  if (_shelfPicked.has(p)) _shelfPicked.delete(p);
  else _shelfPicked.set(p, { path: p, name: _shelfNameOf(el, p) });
  _shelfPaintPicked();
  _shelfEnsureBar();
}

function _shelfSingle(el) {
  const p = el.getAttribute('data-shelf-path');
  if (!p) return;
  // 2026-09-30 用户 二次定案：「1234 我点击13，就选中13，现在是只能选择1，再点3点不上」
  //   → 单击 = 给【这一张】加减，不动别的（能跳着多选）。
  //   取消整批走「取消」按钮，或逐张再点一遍点掉。
  //   拖动那条不变（用户:「长按选择这个这个没问题，OK的」）。
  if (_shelfPicked.has(p)) _shelfPicked.delete(p);
  else _shelfPicked.set(p, { path: p, name: _shelfNameOf(el, p) });
  _shelfPaintPicked();
  _shelfEnsureBar();
}

// 2026-09-30 · 用户 定的手感（对齐 Windows 资源管理器多选）：
//   「我要的按住不动是可以拖着选择删除的，和 windows 多选文件一样，单选点击即可」
//   → 单击 = 只选它 · 按住拖过哪几张 = 那几张一起选（不用等够多少毫秒）。
function _shelfAdd(el) {
  const p = el.getAttribute('data-shelf-path');
  if (!p || _shelfPicked.has(p)) return;
  _shelfPicked.set(p, { path: p, name: _shelfNameOf(el, p) });
  el.classList.add('picked');   // 只点这一张：拖动时每划过一张都跑，不整页重涂
  _shelfEnsureBar();
}

let _shelfDragOn = false;
let _shelfDragMoved = false;

document.addEventListener('mousedown', (e) => {
  if (!_shelfPickOn || e.button !== 0) return;
  const el = e.target.closest && e.target.closest('[data-shelf-path]');
  if (!el) return;
  e.preventDefault();
  e.stopPropagation();
  _shelfDragOn = true;
  _shelfDragMoved = false;
}, true);

// 按住拖过哪张 → 哪张进选区
document.addEventListener('mouseover', (e) => {
  if (!_shelfPickOn || !_shelfDragOn) return;
  const el = e.target.closest && e.target.closest('[data-shelf-path]');
  if (!el) return;
  e.preventDefault();
  e.stopPropagation();
  if (!_shelfDragMoved) {
    // 刚离开起点卡片的第一下：起点那张也得留着，否则一拖就把起点顶掉了
    _shelfDragMoved = true;
    const first = document.querySelector('[data-shelf-path].picked');
    if (first && first !== el) _shelfAdd(first);
  }
  _shelfAdd(el);
}, true);

document.addEventListener('mouseup', (e) => {
  if (!_shelfPickOn) return;
  const wasDrag = _shelfDragMoved;
  _shelfDragOn = false;
  _shelfDragMoved = false;
  if (wasDrag) { e.preventDefault(); e.stopPropagation(); return; }  // 拖过 = 一次多选，不算单击
  const el = e.target.closest && e.target.closest('[data-shelf-path]');
  if (!el) return;
  e.preventDefault();
  e.stopPropagation();
  _shelfSingle(el);   // 没拖动 → 就是单击
}, true);

// 选择模式下，卡片上原有的按钮/链接（预览/下载/收藏）一律不触发
document.addEventListener('click', (e) => {
  if (!_shelfPickOn) return;
  if (e.target.closest && e.target.closest('#shelfPickBar')) return;
  if (e.target.closest && e.target.closest('[data-shelf-path]')) {
    e.preventDefault();
    e.stopPropagation();
  }
}, true);

document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape' || !_shelfPickOn) return;
  // 必须先吃掉这个键：daemon 自己也拿 Esc 关面板，不拦就会「退了选择模式 + 顺手把产物库关了」
  e.preventDefault();
  e.stopPropagation();
  shelfPickMode(false);
}, true);

async function shelfAskDelete() {
  const items = Array.from(_shelfPicked.values());
  const bar = document.getElementById('shelfPickBar');
  if (!items.length || !bar || bar.querySelector('.spb-confirm')) return;
  const conf = document.createElement('div');
  conf.className = 'spb-confirm';
  conf.innerHTML = '<i class="ri-error-warning-line"></i> 把这 <b>' + items.length + '</b> 项删进回收站？'
    + '<span>回收站里留 30 天，随时能捞回来。</span>'
    + '<button type="button" class="spb-danger" id="spbGo">删进回收站</button>'
    + '<button type="button" class="btn-ghost" id="spbNo">再想想</button>';
  bar.appendChild(conf);
  document.getElementById('spbNo').onclick = () => conf.remove();
  document.getElementById('spbGo').onclick = async () => {
    const go = document.getElementById('spbGo');
    go.disabled = true;
    go.innerHTML = '<i class="ri-loader-fill cl-spin"></i> 删除中…';
    try {
      const r = await fetch('/shelf/delete', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
        body: JSON.stringify({ items: items }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || '删除失败');
      // 卡片直接从页面上撤掉（不必重拉整个产物库）
      Array.from(_shelfPicked.keys()).forEach((p) => {
        document.querySelectorAll('[data-shelf-path]').forEach((el) => {
          if (el.getAttribute('data-shelf-path') === p) {
            const t = el.closest('.sg-tile') || el.closest('.report-card') || el;
            t.remove();
          }
        });
      });
      if (typeof addSys === 'function') {
        addSys('已删进回收站 ' + (d.moved || 0) + ' 项 · ' + (d.freed_size || '0 B') + '（30 天内可还原）');
      }
      shelfPickMode(false);
    } catch (e2) {
      go.disabled = false;
      go.innerHTML = '<i class="ri-delete-bin-6-line"></i> 删除';
      if (typeof addSys === 'function') addSys('删除失败：' + e2.message);
      else alert('删除失败：' + e2.message);
    }
  };
}

// ── 回收站面板 ──────────────────────────────────────────────────
function closeShelfTrash() { const b = document.getElementById('shelfTrashBox'); if (b) b.remove(); }

async function openShelfTrash() {
  if (!document.getElementById('shelfTrashBox')) {
    const box = document.createElement('div');
    box.id = 'shelfTrashBox';
    box.className = 'shelf-trash-mask';
    box.innerHTML = '<div class="shelf-trash">'
      + '<div class="st-head"><i class="ri-archive-line"></i> 产物回收站'
      + '<span id="stSub" class="st-sub"></span>'
      + '<button type="button" class="st-x" onclick="closeShelfTrash()" title="关掉"><i class="ri-close-line"></i></button></div>'
      + '<div id="stBody" class="st-body">读回收站…</div>'
      + '<div class="st-foot"><span id="stInfo" class="st-info"></span><span class="spb-sp"></span>'
      + '<button type="button" class="btn-ghost" id="stRestore" onclick="shelfTrashRestore()" disabled><i class="ri-arrow-go-back-line"></i> 还原选中</button>'
      + '<button type="button" class="btn-danger" id="stEmpty" onclick="shelfTrashAskEmpty()"><i class="ri-delete-bin-2-line"></i> 清空回收站</button>'
      + '</div></div>';
    document.body.appendChild(box);
    box.onclick = (e) => { if (e.target === box) closeShelfTrash(); };
  }
  await shelfTrashLoad();
}

async function shelfTrashLoad() {
  const body = document.getElementById('stBody');
  if (!body) return;
  body.innerHTML = '<div class="st-empty">读回收站…</div>';
  try {
    const r = await fetch('/shelf/trash', { headers: { 'Authorization': 'Bearer ' + token } });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || '读不了');
    const batches = d.batches || [];
    const sub = document.getElementById('stSub');
    if (sub) sub.textContent = d.count ? (d.count + ' 件 · ' + d.size) : '';
    const info = document.getElementById('stInfo');
    if (info) info.textContent = d.count ? ('超过 ' + d.keep_days + ' 天自动清掉 · 现在清空就找不回了') : '';
    if (!batches.length) {
      body.innerHTML = '<div class="st-empty">回收站是空的。<br><span>删掉的产物会先放这儿，留 '
        + d.keep_days + ' 天。</span></div>';
      _stSync();
      return;
    }
    body.innerHTML = batches.map((b) => '<div class="st-batch">'
      + '<div class="st-batch-h"><i class="ri-time-line"></i> ' + escHtml(b.when)
      + '<em>' + b.count + ' 件 · ' + escHtml(b.size) + '</em>'
      + '<span class="st-left">还剩 ' + b.left_days + ' 天</span></div>'
      + '<div class="st-files">' + b.files.map((f) => '<label class="st-file">'
        + '<input type="checkbox" class="st-pick" value="' + escHtml(b.batch + '/' + f.rel) + '">'
        + '<span class="st-fname">' + escHtml(f.rel) + '</span>'
        + '<span class="st-fsize">' + escHtml(f.size) + '</span></label>').join('')
      + '</div></div>').join('');
    body.querySelectorAll('.st-pick').forEach((el) => { el.onchange = _stSync; });
    _stSync();
  } catch (e) {
    body.innerHTML = '<div class="st-empty" style="color:var(--red)">' + escHtml(e.message) + '</div>';
  }
}

function _stSync() {
  const n = document.querySelectorAll('.st-pick:checked').length;
  // 两个入口共用一份勾选状态：浮层的 stRestore + 内嵌 tab 的 stiRestore
  ['stRestore', 'stiRestore'].forEach((id) => {
    const b = document.getElementById(id);
    if (!b) return;
    b.disabled = !n;
    b.innerHTML = '<i class="ri-arrow-go-back-line"></i> 还原选中' + (n ? '（' + n + '）' : '');
  });
}

async function shelfTrashRestore() {
  const paths = Array.from(document.querySelectorAll('.st-pick:checked')).map((el) => el.value);
  if (!paths.length) return;
  try {
    const r = await fetch('/shelf/trash/restore', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ paths: paths }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || '还原失败');
    if (typeof addSys === 'function') addSys('已从回收站还原 ' + (d.moved || 0) + ' 件');
    await shelfTrashLoad();
  } catch (e) {
    if (typeof addSys === 'function') addSys('还原失败：' + e.message);
    else alert('还原失败：' + e.message);
  }
}

function shelfTrashAskEmpty() {
  const foot = document.querySelector('#shelfTrashBox .st-foot');
  if (!foot || foot.querySelector('.st-confirm')) return;
  const sub = document.getElementById('stSub');
  const conf = document.createElement('div');
  conf.className = 'st-confirm';
  conf.innerHTML = '<i class="ri-error-warning-fill"></i> 清空回收站'
    + (sub && sub.textContent ? '（' + escHtml(sub.textContent) + '）' : '')
    + '？<span>永久删除 · 找不回来。</span>'
    + '<button type="button" class="btn-danger" id="stGo">确认清空</button>'
    + '<button type="button" class="btn-ghost" id="stNo">算了</button>';
  foot.appendChild(conf);
  document.getElementById('stNo').onclick = () => conf.remove();
  document.getElementById('stGo').onclick = async () => {
    try {
      const r = await fetch('/shelf/trash/empty', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + token },
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || '清空失败');
      if (typeof addSys === 'function') addSys('回收站已清空 · 腾出 ' + (d.freed_size || '0 B'));
      await shelfTrashLoad();
    } catch (e) {
      if (typeof addSys === 'function') addSys('清空失败：' + e.message);
    }
  };
}


// ─── 回收站 · 产物库内嵌视图（用户 2026-09-30「回收站放到工坊产物右边，也显示数量」）──
//   取数是异步的、渲染是同步的 → 先摆骨架，回来了原地填（不整页重渲）。
let _shelfTrashData = null;

function _shelfTrashInline() {
  if (!_shelfTrashData) {
    setTimeout(shelfTrashInlineLoad, 0);
    return '<div class="dash-stub" id="shelfTrashSlot">'
      + '<h3>读回收站…</h3><div>每次进这一格都重新读一遍。</div></div>';
  }
  return _shelfTrashHtml(_shelfTrashData);
}

async function shelfTrashInlineLoad() {
  const slot = document.getElementById('shelfTrashSlot');
  try {
    const r = await fetch('/shelf/trash', { headers: { 'Authorization': 'Bearer ' + token } });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || '读不了');
    _shelfTrashData = d;
    const box = document.getElementById('shelfTrashSlot');
    if (box) box.outerHTML = _shelfTrashHtml(d);
    document.querySelectorAll('.shelf-trash-inline .st-pick').forEach((el) => { el.onchange = _stSync; });
    _stSync();
  } catch (e) {
    const box = document.getElementById('shelfTrashSlot');
    if (box) box.outerHTML = '<div class="dash-stub" style="color:var(--red)"><h3>读不了回收站</h3><div>'
      + escHtml(e.message) + '</div></div>';
  }
}

function _shelfTrashHtml(d) {
  const batches = (d && d.batches) || [];
  const keep = (d && d.keep_days) || 30;
  if (!batches.length) {
    return '<div class="dash-stub"><h3>回收站是空的</h3>'
      + '<div>删掉的产物会先放这儿，留 ' + keep + ' 天，随时能捞回来 —— 过了就自动清掉。</div></div>';
  }
  return '<div class="shelf-trash-inline">'
    + '<div class="sti-bar">'
    + '<span class="sti-info">共 <b>' + d.count + '</b> 件 · ' + escHtml(d.size || '') + ' · 留 ' + keep + ' 天，过期自动清</span>'
    + '<span class="spb-sp"></span>'
    + '<button type="button" class="btn-ghost" id="stiRestore" onclick="shelfTrashInlineRestore()" disabled>'
    + '<i class="ri-arrow-go-back-line"></i> 还原选中</button>'
    + '<button type="button" class="btn-danger" id="stiEmpty" onclick="shelfTrashInlineAskEmpty()">'
    + '<i class="ri-delete-bin-2-line"></i> 清空回收站</button>'
    + '</div>'
    + batches.map((b) => '<div class="st-batch">'
      + '<div class="st-batch-h"><i class="ri-time-line"></i> ' + escHtml(b.when)
      + '<em>' + b.count + ' 件 · ' + escHtml(b.size) + '</em>'
      + '<span class="st-left">还剩 ' + b.left_days + ' 天</span></div>'
      + '<div class="st-files">' + b.files.map((f) => '<label class="st-file">'
        + '<input type="checkbox" class="st-pick" value="' + escHtml(b.batch + '/' + f.rel) + '">'
        + '<span class="st-fname">' + escHtml(f.rel) + '</span>'
        + '<span class="st-fsize">' + escHtml(f.size) + '</span></label>').join('')
      + '</div></div>').join('')
    + '</div>';
}

async function shelfTrashInlineRestore() {
  const paths = Array.from(document.querySelectorAll('.st-pick:checked')).map((el) => el.value);
  if (!paths.length) return;
  try {
    const r = await fetch('/shelf/trash/restore', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ paths: paths }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || '还原失败');
    if (typeof addSys === 'function') addSys('已从回收站还原 ' + (d.moved || 0) + ' 件');
    _shelfTrashData = null;
    if (typeof loadDashboard === 'function') loadDashboard('reports', { silent: true });
  } catch (e) {
    if (typeof addSys === 'function') addSys('还原失败：' + e.message);
  }
}

function shelfTrashInlineAskEmpty() {
  const wrap = document.querySelector('.shelf-trash-inline');
  if (!wrap || wrap.querySelector('.st-confirm')) return;
  const conf = document.createElement('div');
  conf.className = 'st-confirm';
  conf.innerHTML = '<i class="ri-error-warning-fill"></i> 清空回收站？'
    + '<span>永久删除 · 找不回来。</span>'
    + '<button type="button" class="btn-danger" id="stiGo">确认清空</button>'
    + '<button type="button" class="btn-ghost" id="stiNo">算了</button>';
  wrap.insertBefore(conf, wrap.firstChild);
  document.getElementById('stiNo').onclick = () => conf.remove();
  document.getElementById('stiGo').onclick = async () => {
    try {
      const r = await fetch('/shelf/trash/empty', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + token },
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || '清空失败');
      if (typeof addSys === 'function') addSys('回收站已清空 · 腾出 ' + (d.freed_size || '0 B'));
      _shelfTrashData = null;
      if (typeof loadDashboard === 'function') loadDashboard('reports', { silent: true });
    } catch (e) {
      if (typeof addSys === 'function') addSys('清空失败：' + e.message);
    }
  };
}


// ─── 知识库 · 下钻 + 添加（用户 2026-09-30）──────────────────────────────────
//   复用产物库的交互骨架（.fld 卡 / .fld-crumb 面包屑 / .shelf-folders 栅格），
//   但状态自持（_kbFolderOpen），不去动产物库的 _shelfFolder —— 两边是独立的导航栈，
//   共用样式与卡片类，不共用状态，改一边不会串到另一边。
let _kbFolderOpen = '';
let _kbData = null;   // 知识库面板最近一次拿到的原始数据

function kbEnterFolder(name) {
  _kbFolderOpen = name;
  if (_kbData) renderKnowledge(_kbData);
}

function kbLeaveFolder() {
  _kbFolderOpen = '';
  if (_kbData) renderKnowledge(_kbData);
}

/* 粘贴路径时自动预览（敲完 400ms）—— 不用手点「预览」 */
let _kbScanTimer = null;
function kbAddScanDebounced() {
  clearTimeout(_kbScanTimer);
  _kbScanTimer = setTimeout(() => kbAddScan(), 400);
}

/* ──────────────────────────────────────────────────────────────
   拖拽入栏：把文件/文件夹拖进中栏 → 上传 → 落 data/knowledge/incoming/ → 入库

   为什么走上传而不是记路径：浏览器安全沙箱下，拖进来的 File 拿不到磁盘绝对
   路径 —— 只能拿到内容本身。所以拖拽 = 复制一份进库里，跟原文件脱钩。
   （要保原路径就用「选文件夹/选文件」那两个按钮，那条能拿到真路径。）
   2026-10-01 用户:「都要放到我们 daemonkey 某个固定的目录，这个不能乱」→ 落点写死 INCOMING。
   ────────────────────────────────────────────────────────────── */

/* 递归读一个 entry（文件或文件夹）→ [{file, rel}] · rel 是相对路径（拖文件夹时带子目录） */
function _kbReadEntry(entry, prefix) {
  return new Promise((resolve) => {
    if (!entry) return resolve([]);
    if (entry.isFile) {
      entry.file(
        (f) => resolve([{ file: f, rel: prefix + entry.name }]),
        () => resolve([])
      );
      return;
    }
    if (entry.isDirectory) {
      const reader = entry.createReader();
      const all = [];
      const step = () => reader.readEntries(async (batch) => {
        if (!batch.length) {
          const got = await Promise.all(all.map((e) => _kbReadEntry(e, prefix + entry.name + '/')));
          return resolve(got.flat());
        }
        all.push(...batch);
        step();            // readEntries 一次最多返 100 条，得反复读到空
      }, () => resolve([]));
      step();
      return;
    }
    resolve([]);
  });
}

/* 收下拖进来的东西（中栏） */
async function kbDropUpload(dt, zoneEl) {
  const items = dt.items ? Array.from(dt.items) : [];
  const entries = items.map((it) => (it.webkitGetAsEntry ? it.webkitGetAsEntry() : null));

  let picked = [];
  if (entries.some(Boolean)) {
    const got = await Promise.all(entries.map((e) => _kbReadEntry(e, '')));
    picked = got.flat();
  } else {
    // 退路：拿不到 entry 时只收裸文件（此时拖文件夹会空）
    picked = Array.from(dt.files || []).map((f) => ({ file: f, rel: f.name }));
  }
  if (!picked.length) {
    if (typeof showChatToast === 'function') showChatToast('没看出拖进来的是什么（试试直接拖文件）');
    return;
  }

  // 入库前先自己过一遍 —— 不支持的当场点名，不让你只看到一句「不支持」。
  // 这张表跟后端 workers/doc_ingest.py 的 SUPPORTED_EXT 同源，改了那边记得同步这里。
  const OK_EXT = ['md', 'markdown', 'txt', 'text', 'log', 'rst', 'org', 'pdf', 'docx', 'pptx',
                  'xlsx', 'xlsm', 'csv', 'tsv', 'json', 'yaml', 'yml', 'xml', 'html', 'htm'];
  const extOf = (n) => (String(n).split('.').pop() || '').toLowerCase();
  const okFiles = picked.filter(p => OK_EXT.includes(extOf(p.file.name)));
  const badFiles = picked.filter(p => !OK_EXT.includes(extOf(p.file.name)));

  if (badFiles.length) {
    const kinds = Array.from(new Set(badFiles.map(p => '.' + extOf(p.file.name)))).slice(0, 8);
    if (typeof showChatToast === 'function') {
      showChatToast('跳过 ' + badFiles.length + ' 个不支持的格式：' + kinds.join(' '));
    }
  }
  if (!okFiles.length) {
    if (typeof showChatToast === 'function') {
      showChatToast('没一个能进的 —— 现在支持 md / txt / log / pdf / docx / pptx / xlsx / csv / json / yaml / xml / html');
    }
    return;
  }

  // 提示：拖文件夹 → 按文件夹名归组；拖散文件 → 未分类
  const tops = new Set(okFiles.filter(p => p.rel.includes('/')).map(p => p.rel.split('/')[0]));
  const groupHint = tops.size === 1 ? ('· 归到「' + Array.from(tops)[0] + '」')
                  : (tops.size > 1 ? ('· 归到 ' + tops.size + ' 个文件夹') : '· 归到未分类');
  if (typeof showChatToast === 'function') {
    showChatToast('收到 ' + okFiles.length + ' 个文件 ' + groupHint + ' · 传完会提示（复制进来的副本）');
  }

  const fd = new FormData();
  okFiles.forEach((p) => {
    fd.append('files', p.file, p.file.name);
    fd.append('rels', p.rel);
  });

  try {
    const r = await fetch('/dashboard/knowledge/drop', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token },   // 不要设 Content-Type · 让浏览器带 boundary
      body: fd,
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || '拖拽入库失败');
    const parts = ['拖进来 ' + (d.added_n || 0) + ' 篇'];
    if (d.skipped_n) parts.push(d.skipped_n + ' 个格式不支持');
    if (d.errors && d.errors.length) {
      // 把后端的具体原因带出来（比如「没抽到文字·大概是扫描件」），不要只报个数
      const why = d.errors.slice(0, 2).map(e => e.error).filter(Boolean).join('；');
      parts.push(d.errors.length + ' 个没成功' + (why ? '（' + why + '）' : ''));
    }
    if (typeof showChatToast === 'function') showChatToast(parts.join(' · '));
    _kbData = null;
    loadDashboard('knowledge');
  } catch (e) {
    if (typeof showChatToast === 'function') showChatToast(String(e.message || e));
  } finally {
    if (zoneEl) zoneEl.classList.remove('kb-drop-on');
  }
}

/* 绑一次就行（loadDashboard 可能重复调 renderKnowledge）
   但 $dashView 是【所有 dashboard 面板共用的同一个节点】—— innerHTML 换了监听器还在，
   所以不能靠「绑过没绑过」判断，每次事件都要当场确认【现在渲染的是不是知识库】。
   （曾经就这么漏了：进过知识库后，在产物库拖文件也会往知识库灌。） */
function _kbDropActive(zone) {
  return !!(zone && zone.querySelector('.dk-add'));
}
function _kbBindDrop() {
  const zone = $dashView;
  if (!zone || zone._kbDropBound) return;
  zone._kbDropBound = true;

  let depth = 0;    // dragenter/leave 会因子元素反复触发 · 计数进出才不闪
  zone.addEventListener('dragenter', (e) => {
    if (!_kbDropActive(zone)) return;
    if (!e.dataTransfer || !Array.from(e.dataTransfer.types || []).includes('Files')) return;
    e.preventDefault();
    depth++;
    zone.classList.add('kb-drop-on');
  });
  zone.addEventListener('dragover', (e) => {
    if (!_kbDropActive(zone)) return;
    if (!e.dataTransfer || !Array.from(e.dataTransfer.types || []).includes('Files')) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  });
  zone.addEventListener('dragleave', () => { depth = Math.max(0, depth - 1); if (!depth) zone.classList.remove('kb-drop-on'); });
  zone.addEventListener('drop', async (e) => {
    if (!e.dataTransfer) return;
    if (!_kbDropActive(zone)) return;
    e.preventDefault();
    depth = 0;
    zone.classList.remove('kb-drop-on');
    await kbDropUpload(e.dataTransfer, zone);
  });
}

/* 添加面板：选文件夹 / 选文件 / 手输路径 → 预览 N 篇 → 确认入库
   三条路最后都汇到同一个 POST /dashboard/knowledge/add（后端幂等去重）。 */
function kbAskAdd() {
  const old = document.getElementById('kbAddBox');
  if (old) { old.remove(); return; }

  const folderNames = kbAllFolderNames();
  const opts = ['<option value="">未分类</option>']
    .concat(folderNames.map(f => '<option value="' + escHtml(f) + '">' + escHtml(f) + '</option>')).join('');

  const box = document.createElement('div');
  box.id = 'kbAddBox';
  box.className = 'kb-add-box';
  box.innerHTML = `
    <div class="kab-head"><i class="ri-add-circle-line"></i> 往知识库里加东西
      <button type="button" class="kab-x" onclick="document.getElementById('kbAddBox').remove()">✕</button></div>
    <div class="kab-row">
      <button type="button" class="kab-plain" onclick="kbPick('folder')"><i class="ri-folder-open-line"></i> 选文件夹</button>
      <button type="button" class="kab-plain" onclick="kbPick('files')"><i class="ri-file-list-3-line"></i> 选文件（可多选）</button>
      <span class="kab-hint">或直接把文件/文件夹拖进中栏</span>
    </div>
    <div class="kab-row">
      <input type="text" id="kbAddPath" class="kab-input" placeholder="也可以直接粘贴路径 · 多个用分号隔开"
             oninput="kbAddScanDebounced()">
      <button type="button" class="btn-ghost" onclick="kbAddScan()">预览</button>
    </div>
    <div class="kab-row">
      <select id="kbAddFolderSel" class="kab-input kab-narrow">${opts}</select>
      <button type="button" class="kab-plain" onclick="kbNewFolderFromPanel()"><i class="ri-folder-add-line"></i> 新建</button>
      <button type="button" class="kab-go" id="kbAddGo" onclick="kbAddCommit()" disabled>加入知识库</button>
    </div>
    <div class="kab-preview" id="kbAddPreview"></div>`;

  const host = document.querySelector('.dash-head') || $dashView;
  host.parentElement.insertBefore(box, host.nextSibling);

  // 记住这次要灌什么（预览/入库共用）
  window.__kbPending = null;
}

/* 所有已存在的文件夹名（显式登记的 + 文档里现算的）· 去重排序 */
function kbAllFolderNames() {
  const out = new Set(((_kbData && _kbData.folders) || []).filter(Boolean));
  for (const d of ((_kbData && _kbData.items) || [])) {
    const f = (d.folder && String(d.folder).trim()) || ((d.tags && d.tags.length) ? String(d.tags[0]) : '');
    if (f && f !== '未分类') out.add(f);
  }
  return Array.from(out).sort((a, b) => a.localeCompare(b, 'zh'));
}

/* 工具条上的「新建文件夹」—— 自绘内联输入，不用原生 prompt（那玩意儿跟设计系统格格不入） */
function kbNewFolder() {
  kbFolderPrompt((name) => kbCreateFolder(name));
}

/* 添加面板里的「新建」 —— 建完直接选中，不用重开面板 */
function kbNewFolderFromPanel() {
  kbFolderPrompt(async (name) => {
    const r = await kbCreateFolder(name);
    if (!r) return;
    const sel = document.getElementById('kbAddFolderSel');
    if (sel) {
      if (!Array.from(sel.options).some(o => o.value === name)) {
        const op = document.createElement('option');
        op.value = name; op.textContent = name;
        sel.appendChild(op);
      }
      sel.value = name;
    }
  });
}

/* 建文件夹的自绘输入条 —— 从哪调都长一样，用 .kb-add-box 同一套配色 */
function kbFolderPrompt(onOk) {
  const old = document.getElementById('kbFolderPrompt');
  if (old) { old.remove(); return; }
  const box = document.createElement('div');
  box.id = 'kbFolderPrompt';
  box.className = 'kb-add-box kb-fprompt';
  box.innerHTML = `
    <div class="kab-row kab-fprompt-row">
      <span class="kab-fprompt-label">新建文件夹</span>
      <input type="text" id="kbFolderName" class="kab-input" placeholder="给它起个名字…">
      <button type="button" class="btn-primary" id="kbFolderOk">创建</button>
      <button type="button" class="btn-ghost" id="kbFolderNo">取消</button>
    </div>`;
  const host = document.querySelector('.dash-head') || $dashView;
  host.parentElement.insertBefore(box, host.nextSibling);

  const inp = document.getElementById('kbFolderName');
  const go = async () => {
    const n = String(inp.value || '').trim();
    if (!n) { inp.focus(); return; }
    box.remove();
    await onOk(n);
  };
  document.getElementById('kbFolderOk').onclick = go;
  document.getElementById('kbFolderNo').onclick = () => box.remove();
  inp.onkeydown = (e) => {
    if (e.key === 'Enter') { e.preventDefault(); go(); }
    if (e.key === 'Escape') box.remove();
  };
  inp.focus();
}

/* 删文件夹 —— 先弹一句确认（空的也问，避免手滑）。
   非空时明说「里面有 N 篇 → 删掉后它们回未分类，文档本身不删」，
   不让用户以为一删就没了。 */
function kbAskDeleteFolder(name, n) {
  const old = document.getElementById('kbDelPrompt');
  if (old) { old.remove(); return; }
  const box = document.createElement('div');
  box.id = 'kbDelPrompt';
  box.className = 'kb-add-box kb-fprompt';
  box.innerHTML = `
    <div class="kab-row kab-fprompt-row">
      <span class="kab-fprompt-label">删掉文件夹「${escHtml(name)}」</span>
      <span class="kab-hint">${n ? ('里面有 ' + n + ' 篇 → 删掉后它们回「未分类」，文档本身不会删') : '空文件夹'}</span>
      <button type="button" class="btn-danger" id="kbDelOk">删掉</button>
      <button type="button" class="btn-ghost" id="kbDelNo">取消</button>
    </div>`;
  const host = document.querySelector('.dash-head') || $dashView;
  host.parentElement.insertBefore(box, host.nextSibling);
  document.getElementById('kbDelOk').onclick = async () => { box.remove(); await kbDeleteFolder(name, n > 0); };
  document.getElementById('kbDelNo').onclick = () => box.remove();
}

async function kbDeleteFolder(name, dropDocs) {
  try {
    const r = await fetch('/dashboard/knowledge/folder/remove', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, drop_docs: !!dropDocs }),
    });
    const d = await r.json();
    if (!d.ok) throw new Error(d.error || d.detail || '删文件夹失败');
    if (typeof showChatToast === 'function') {
      showChatToast(d.removed
        ? ('删掉了文件夹：' + name + (d.moved_docs ? ('（' + d.moved_docs + ' 篇回到未分类）') : ''))
        : (name + ' 本来就不在'));
    }
    _kbData = null;
    loadDashboard('knowledge');
    return d;
  } catch (e) {
    if (typeof showChatToast === 'function') showChatToast(String(e.message || e));
    return null;
  }
}

/* 建文件夹的统一出口 —— 工具条和面板都走这里 */
async function kbCreateFolder(name) {
  try {
    const r = await fetch('/dashboard/knowledge/folder', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || '建文件夹失败');
    if (typeof showChatToast === 'function') {
      showChatToast(d.created ? ('建好了：' + name) : (name + ' 已经有了'));
    }
    _kbData = null;
    loadDashboard('knowledge');
    return d;
  } catch (e) {
    if (typeof showChatToast === 'function') showChatToast(String(e.message || e));
    return null;
  }
}

async function kbPick(kind) {
  const url = kind === 'folder' ? '/api/pick/folder' : '/api/pick/files';
  const pv = document.getElementById('kbAddPreview');
  if (pv) pv.innerHTML = '<span class="kab-hint">正在拉系统选择器…（切到别的窗口会看不到它）</span>';
  try {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    const d = await r.json();
    if (!r.ok || !d.ok) {
      if (pv) pv.innerHTML = '<span class="kab-err">' + escHtml(d.error || d.detail || '选择器打不开') + '</span>';
      return;
    }
    const picked = kind === 'folder' ? [d.path] : (d.paths || []);
    const inp = document.getElementById('kbAddPath');
    if (inp) inp.value = picked.join('; ');
    await kbAddScan();
  } catch (e) {
    if (pv) pv.innerHTML = '<span class="kab-err">' + escHtml(String(e)) + '</span>';
  }
}

async function kbAddScan() {
  const inp = document.getElementById('kbAddPath');
  const pv = document.getElementById('kbAddPreview');
  const go = document.getElementById('kbAddGo');
  const raw = (inp && inp.value || '').split(/[;\n]/).map(s => s.trim()).filter(Boolean);
  if (!raw.length) { if (pv) pv.innerHTML = ''; if (go) go.disabled = true; return; }

  if (pv) pv.innerHTML = '<span class="kab-hint">正在看里面有哪些能加的…</span>';
  try {
    let files = [], skipped = 0, truncated = false, scanErrors = [];
    for (const p of raw) {
      const r = await fetch('/dashboard/knowledge/scan', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: p }),
      });
      const d = await r.json();
      if (d.ok) { files = files.concat(d.files || []); skipped += (d.skipped || 0); truncated = truncated || !!d.truncated; }
      else { scanErrors.push(d.error || ('打不开：' + p)); }   // 不静默: 「路径打不开」和「没有能加的」是两回事
    }
    window.__kbPending = files;
    window.__kbScanErrors = scanErrors;
    if (go) go.disabled = files.length === 0;
    if (pv) {
      if (!files.length && scanErrors.length) {
        // 「路径打不开」≠「这里没有能加的」—— 前者用户换多少个文件都没用，必须把真因说出来
        pv.innerHTML = '<span class="kab-err">' + escHtml(scanErrors[0])
          + (scanErrors.length > 1 ? '（还有 ' + (scanErrors.length - 1) + ' 个路径同样打不开）' : '') + '</span>';
      } else if (!files.length) {
        pv.innerHTML = '<span class="kab-err">这里没有能加的文档（支持 md / txt / docx / pptx / pdf）'
          + (skipped ? ' · 跳过了 ' + skipped + ' 个不支持的文件' : '') + '</span>';
      } else {
        const show = files.slice(0, 6).map(f => '<div class="kab-f">' + escHtml(f.split(/[\\/]/).pop()) + '</div>').join('');
        pv.innerHTML = '<div class="kab-ok">将加入 <b>' + files.length + '</b> 篇'
          + (skipped ? ' · 跳过 ' + skipped + ' 个不支持的文件' : '')
          + (truncated ? ' · <span class="kab-err">文件太多，只取了前 800 个</span>' : '')
          + '</div>' + show + (files.length > 6 ? '<div class="kab-more">…还有 ' + (files.length - 6) + ' 篇</div>' : '');
      }
    }
  } catch (e) {
    if (pv) pv.innerHTML = '<span class="kab-err">' + escHtml(String(e)) + '</span>';
  }
}

async function kbAddCommit() {
  const files = window.__kbPending || [];
  const go = document.getElementById('kbAddGo');
  if (!files.length) return;
  const sel = document.getElementById('kbAddFolderSel');
  const folder = (sel ? sel.value : '') || '';
  if (go) { go.disabled = true; go.innerText = '正在加入…'; }
  try {
    const r = await fetch('/dashboard/knowledge/add', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ paths: files, folder: folder.trim(), scan_dir: false }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || '入库失败');
    const box = document.getElementById('kbAddBox');
    if (box) box.remove();
    const msg = '加进知识库 ' + (d.added_n || 0) + ' 篇'
      + (d.skipped_n ? ' · ' + d.skipped_n + ' 篇之前已加过' : '')
      + (d.errors && d.errors.length ? ' · ' + d.errors.length + ' 篇没成功' : '');
    if (typeof showChatToast === 'function') showChatToast(msg);
    _kbData = null;
    loadDashboard('knowledge');
  } catch (e) {
    if (go) { go.disabled = false; go.innerText = '加入知识库'; }
    const pv = document.getElementById('kbAddPreview');
    if (pv) pv.innerHTML = '<span class="kab-err">' + escHtml(String(e)) + '</span>';
  }
}
