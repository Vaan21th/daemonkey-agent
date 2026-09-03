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

  // 显示足够多条·让信号流内容超过热力卡高度 → 内部滚动填满·不在卡底留空 (BRO 2026-06-03)
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
      <span class="dash-meta">${tasks.length} 个 · ${tasks.filter(t => t.enabled).length} 开着</span>
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
      html: `让 OPUS 看一遍 <b>${mm}${vd && vd !== 'all' ? ' · ' + escHtml(vd) : ''}</b> 的高价值信号·
        给出趋势研判 + 执行方案。<span class="om-hint">会问一次模型（大约几毛钱、半分钟）。看过的会记住，再看不重复花。</span>`
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
    { id:'wishlist',icon:'ri-lightbulb-fill',  color:'#F6AD55',     label:'OPUS 心愿' },
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
    // 方案 B (2026-08-06 BRO 拍板) · 普通切换=平铺行 · 顾问唤醒=紫色左边条胶囊
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
    loadBIMirror();   // A·OPUS 眼里的你
    loadBIClosure();  // B·闭环温度计
    loadBISelf();     // C·OPUS 自况
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
  else if (/\.docx?$/i.test(filename)) kind = "reports";
  const rel = kind === "decks"
    ? ("data/presentations/" + filename)
    : (kind === "sheets" ? ("data/spreadsheets/" + filename) : ("data/reports/" + filename));
  if (typeof window.goOfficeHome === "function" && !/^_hist_/i.test(filename)) {
    await window.goOfficeHome(rel);
  }
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
  if (d && /\.pptx$/i.test(d.name || '')) return 'decks';
  if (d && /\.xlsx$/i.test(d.name || '')) return 'sheets';
  return 'reports';
}

function shelfOpenPath(d) {
  if (d && d.open_path) return d.open_path;
  const name = (d && d.name) || '';
  const kind = shelfKindOf(d);
  if (kind === 'decks') return 'data/presentations/' + name;
  if (kind === 'sheets') return 'data/spreadsheets/' + name;
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
  return `<div class="dash-empty dk-ld">
    <div class="dk-ld-row"><span class="dk-ld-dot"></span><span class="dk-ld-dot"></span><span class="dk-ld-dot"></span></div>
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

function renderAutopilotInlineBtn() {
  return `<button class="bi-link" onclick="spawnQuickly('帮我自主巡航一遍 · 调 auto_pipeline 工具 · 三步全跑 · 跑完告诉我看到了什么 + 推 1-2 个最值得动手的机会', '自主巡航')">🛰️ 跑一圈巡航</button>`;
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
            <button class="bi-brief-gen" id="biMirrorBtn" type="button"><i class="ri-camera-lens-fill"></i> 现在对照</button>
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
              <button class="bi-link" id="biMemoryAuditBtn" type="button" title="让 OPUS 用语义向量体检手艺箱 · 重复簇摆出来你拍板"><i class="ri-search-eye-line"></i> 手艺体检</button>
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

      <!-- 元行 (卷五十八续 VIII)：OPUS 自况 + 节律时间线 -->
      <div class="bi-grid-2">
        <div class="bi-card">
          <div class="bi-card-head"><h3><i class="ri-pulse-fill" style="color:#4FD1C5"></i> OPUS 自况</h3></div>
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
          BRO · 24h 内 7 个维度都没新增。要不要 ${renderAutopilotInlineBtn()}?
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
        <span class="dash-meta">还没有开始做的项目</span></div>
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
      <span class="muted">以后做可行性分析时，会自动参考这里做过的同类项目</span>
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
  // 放在最前面——BRO 先看到"这次分析基于什么"·再读 OPUS 的判断
  const sources = d.sources || {};
  const radarItems = sources.radar_items || [];
  const reportItems = sources.reports || [];
  const docItems = sources.docs || [];
  const hasSources = radarItems.length > 0 || reportItems.length > 0 || docItems.length > 0;
  if (hasSources) {
    html += `<div class="feas-block feas-sources">
      <h3>📚 信源 · 这次分析基于的原始信息
        <span class="feas-sources-hint">点击直达原文 · BRO 可顺着同一根线对齐认知</span>
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
    // 收集了 sources 但什么都没找到——明确告诉 BRO·别藏
    html += `<div class="feas-block feas-sources feas-sources-empty">
      <h3>📚 信源</h3>
      <div class="feas-sources-empty-msg">
        <strong>没找到相关雷达条目 / 报告 / 私有资料</strong> · 这次分析信源不足。<br>
        建议：先让 OPUS 跑一份相关报告 · 存点相关资料进知识库 · 或扩大雷达源 · 再重新分析。
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
    html += `<div class="feas-block"><h3>🔭 未来预期 · 按 BRO 现实节奏</h3>
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
      html += `<div class="feas-res feas-res-have"><b><i class="ri-checkbox-circle-fill"></i> BRO 已有：</b><ul>`;
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
  // BRO 在这里直接更新决策 / 实际产出 / 经验·下次 LLM 跑会读到这些
  const outcome = d.outcome || {};
  const curStatus = outcome.status || 'not_started';
  const _STATUS_BTN = [
    { v: 'in_progress', label: '<i class="ri-play-fill"></i> 开干', cls: 'fb-go' },
    { v: 'completed',   label: '<i class="ri-check-fill"></i> 已完成', cls: 'fb-done' },
    { v: 'abandoned',   label: '<i class="ri-close-fill"></i> 不做了', cls: 'fb-skip' },
    { v: 'not_started', label: '⟲ 重置', cls: 'fb-reset' },
  ];
  html += `<div class="feas-block feas-feedback">
    <h3><i class="ri-refresh-fill"></i> 闭环反馈 · BRO 的真实决策（卷三十一）</h3>
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
        <div>在底部输入框跟 OPUS 说：「把 <code>D:\\资料\\合同.pdf</code> 加进知识库」<br>
             支持 md / txt / docx / pptx / pdf。存进去之后，回答能引用原文。</div>
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
        <span class="opp-meta-pill" title="BRO 适配度">${fitIcon} ${fitLabel}</span>
        <span class="opp-meta-pill" title="投入预估">⏱️ ${effortLabel}</span>
        <span class="opp-meta-pill" title="收益级别">📈 ${upsideLabel}</span>
      </div>
      <div class="opp-summary">${escHtml(o.summary || '')}</div>
      ${o.fit_reason ? `<div class="opp-fit-reason"><b>为什么 BRO ${o.fit === 'no' ? '不' : ''}适合:</b> ${escHtml(o.fit_reason)}</div>` : ''}
      ${renderOppStats(o)}
      ${stepsHtml}
      ${refsHtml}
      <div class="opp-actions">
        <button class="opp-act-btn" onclick="spawnQuickly('把第 ${idx + 1} 个机会展开成完整方案', '展开机会方案')">
          <i class="ri-draft-fill"></i> 展开成方案
        </button>
        <button class="opp-act-btn opp-act-feas"
                onclick="runFeasibilityFromOpp('${jsStr(o.id || '')}', ${idx + 1})"
                title="去可行性分析 · 让 OPUS 跑一次深度评估">
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
      <span class="meta">${opps.length} 个机会 · 市场 × BRO 能力</span>
      <button onclick="backToChat()">✕ 收起</button>
      <button onclick="spawnQuickly('基于今日趋势 · 调 mine_opportunities 工具 · 参数 action=mine · 重新挖一遍掘金机会 · 形态要多样(内容账号 / 实体产品 / 服务咨询 / 信息差套利 / 软件产品 / 投资副业 · 不要全是 SaaS · 卷三十三第 6 条铁律) · 跑完告诉我最推哪 1-2 个 + 为什么', '重新挖掘机会')" title="派发到新会话 · OPUS 跑 mine_opportunities · 完成后切过去看结果">
        <i class="ri-refresh-fill"></i> 重新挖掘
      </button>
    </div>`;

  if (opps.length === 0) {
    html += `
      <div class="dash-stub">
        <h3>还没挖过掘金机会</h3>
        <div>${escHtml(note || '点上方"重新挖掘"按钮 · OPUS 会基于最新趋势 + BRO 画像 LLM 跑一次')}</div>
        <div style="margin-top:12px;font-size:11px;color:var(--dim2)">
          需要先有趋势 · 没趋势的话先去 <i class="ri-line-chart-fill"></i> 今日趋势 跑一次
        </div>
      </div>`;
  } else {
    html += `
      <div class="opp-intro">
        生成于 ${formatTimeShort(generated)} · 扫描了 ${trendsScanned || 0} 条趋势 · 耗时 ${elapsedS}s<br>
        <span style="font-size:11px;color:var(--dim2)">
          每个机会都基于 BRO 画像评估了适配度 · 点机会卡可让 OPUS 展开成完整方案
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
  // 今日新增跟着 tab 走: 选了领域=该领域今天首见·全部=全领域总和 (BRO 2026-06-06·别两个口径混一格)
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
      <button onclick="spawnQuickly('看一眼信息雷达最新数据 · 调 auto_pipeline 工具 · 参数 refresh_radar=false, regen_trends=true, mine_opps=false · 只重新生成今日趋势 · 跑完告诉我哪几个趋势最戳到 BRO · 为什么', '生成今日趋势')">让 OPUS 总结趋势 →</button>
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

let _shelfKind = 'reports';
try { _shelfKind = localStorage.getItem('opus_shelf_kind') || 'reports'; } catch (e) {}
let _shelfLastData = null;

function switchShelfKind(kind) {
  _shelfKind = (kind === 'decks' || kind === 'sheets') ? kind : 'reports';
  try { localStorage.setItem('opus_shelf_kind', _shelfKind); } catch (e) {}
  if (_shelfLastData) renderReports(_shelfLastData);
}

function renderReports(data) {
  _shelfPreviewOpen = false;
  _shelfLastData = data;
  if (data && data.error) {
    $dashView.innerHTML = `
      ${pipelineBreadcrumb('reports')}
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
  const kind = (_shelfKind === 'decks' || _shelfKind === 'sheets') ? _shelfKind : 'reports';
  const pack = kind === 'decks' ? decks : (kind === 'sheets' ? sheets : reports);
  const items = pack.items || [];
  const dir = pack.directory || (kind === 'decks' ? 'data/presentations' : (kind === 'sheets' ? 'data/spreadsheets' : 'data/reports'));
  const nR = reports.count != null ? reports.count : (reports.items || []).length;
  const nD = decks.count != null ? decks.count : (decks.items || []).length;
  const nS = sheets.count != null ? sheets.count : (sheets.items || []).length;

  let html = `
    ${pipelineBreadcrumb('reports')}
    <div class="dash-head">
      <h2><i class="ri-archive-2-fill"></i> 产物库</h2>
      <span class="meta">成品层 · ${items.length} 份 · ${escHtml(dir)}</span>
      <button onclick="backToChat()">收起</button>
      <button onclick="loadDashboard('trends')">← 回到趋势</button>
      <button onclick="loadDashboard('reports')">刷新列表</button>
    </div>
    <div class="depot-tabs" role="tablist">
      <button type="button" class="depot-tab${kind === 'reports' ? ' active' : ''}" onclick="switchShelfKind('reports')">
        <i class="ri-article-fill"></i><span>报告</span><span class="shelf-n">${nR}</span>
      </button>
      <button type="button" class="depot-tab${kind === 'decks' ? ' active' : ''}" onclick="switchShelfKind('decks')">
        <i class="ri-slideshow-fill"></i><span>演示稿</span><span class="shelf-n">${nD}</span>
      </button>
      <button type="button" class="depot-tab${kind === 'sheets' ? ' active' : ''}" onclick="switchShelfKind('sheets')">
        <i class="ri-table-fill"></i><span>表格</span><span class="shelf-n">${nS}</span>
      </button>
    </div>`;

  if (items.length === 0) {
    html += kind === 'decks' ? `
      <div class="dash-stub">
        <h3>还没生成过演示稿</h3>
        <div>跟我说做PPT，文件会出现在这里。</div>
      </div>` : kind === 'sheets' ? `
      <div class="dash-stub">
        <h3>还没生成过表格</h3>
        <div>跟我说做表格，文件会出现在这里。</div>
      </div>` : `
      <div class="dash-stub">
        <h3>还没生成过报告</h3>
        <div>跟我说写报告，文件会出现在这里。</div>
      </div>`;
  } else {
    if (items.length > 3) {
      html += renderListFilter({targetSelector: '.report-card', placeholder: kind === 'decks' ? '搜演示稿文件名 / 时间...' : (kind === 'sheets' ? '搜表格文件名 / 时间...' : '搜报告文件名 / 时间...')});
    }
    html += `<div class="reports-list">`;
    for (const it of items) {
      const rawDl = it.download_url || (kind === 'decks' ? `/presentations/${it.name}` : (kind === 'sheets' ? `/spreadsheets/${it.name}` : `/reports/${it.name}`));
      const dlUrl = `${rawDl}${rawDl.includes('?') ? '&' : '?'}token=${encodeURIComponent(token || '')}`;
      const previewUrl = it.preview_url || '';
      const srcBadge = it.has_md_source
        ? `<span class="rc-src-badge rc-src-md" title="有源文件">有源文件</span>`
        : `<span class="rc-src-badge rc-src-extract" title="${kind === 'decks' ? '没有源文件 · 下载用本机软件打开' : (kind === 'sheets' ? '没有源文件 · 成品仍可看表' : '旧报告 · 预览是从成品反推的')}">${kind === 'decks' || kind === 'sheets' ? '没有源文件' : '旧版预览'}</span>`;
      const kbBtn = kind === 'reports'
        ? `<button class="rc-preview-btn rp-kb" data-name="${escHtml(it.name)}" title="存进知识库，之后回答能引用原文"><i class="ri-book-2-line"></i> 存入知识库</button>`
        : '';
      const openRel = it.open_path || (kind === 'decks' ? ('data/presentations/' + it.name) : (kind === 'sheets' ? ('data/spreadsheets/' + it.name) : ('data/reports/' + it.name)));
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
            + `<button type="button" class="rc-preview-btn" data-name="${escHtml(h.name || '')}" data-preview-url="${escHtml(hpv)}"><i class="ri-eye-line"></i> 中栏看</button>`
            + `<button type="button" class="rc-preview-btn rc-restore" data-restore="${escHtml(h.name || '')}" data-kind="${escHtml(kind)}" title="不会删任何旧文件。把这版抄成当前，现在的当前会另存进历史。"><i class="ri-arrow-go-back-line"></i> 用这版继续</button>`
            + `<button type="button" class="rc-preview-btn" data-open="${escHtml(hop)}" title="用本机软件打开"><i class="ri-external-link-line"></i></button>`
            + `<a class="rc-dl" href="${escHtml(hdl)}" download="${escHtml(h.name || '')}">下载</a></div>`;
        }).join('');
        histHtml = `<details class="rc-hist"><summary>历史 ${hist.length} 份</summary><p class="rc-hist-hint">卡片「预览」是当前这份。要看旧样子，点下面体积大、页数多的那行「中栏看」。顶栏必须出现「历史 Vx」，才是旧稿。</p>${rows}</details>`;
      }
      html += `
        <div class="report-card">
          <div class="rc-head">
            <a class="rc-name" href="javascript:void(0)" data-name="${escHtml(it.name)}" data-preview-url="${escHtml(previewUrl)}" data-preview="1">
              ${escHtml(showName)}
            </a>
            ${ver}
            ${srcBadge}
          </div>
          <div class="rc-meta">
            <span class="rc-size">${escHtml(fmtShelfSize(it.size_kb))}</span>
            ${it.pages ? `<span class="rc-pages">${it.pages} 页</span>` : ''}
            <span class="rc-time">${escHtml(it.created_at)}</span>
            ${previewUrl ? `<button class="rc-preview-btn" data-name="${escHtml(it.name)}" data-preview-url="${escHtml(previewUrl)}"><i class="ri-eye-line"></i> 预览</button>` : ''}
            <button class="rc-preview-btn" data-open="${escHtml(openRel)}"><i class="ri-external-link-line"></i> 打开</button>
            ${kbBtn}
            <a class="rc-dl" href="${escHtml(dlUrl)}" download="${escHtml(it.name)}">下载</a>
          </div>
          ${histHtml}
        </div>`;
    }
    html += `</div>`;
  }
  $dashView.innerHTML = html;

  $dashView.querySelectorAll('.rc-preview-btn:not(.rp-kb):not([data-open]):not([data-restore]), .rc-name[data-preview]').forEach(el => {
    el.onclick = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const name = el.getAttribute('data-name');
      const previewUrl = el.getAttribute('data-preview-url');
      if (name) loadReportPreview(name, previewUrl || undefined);
    };
  });
  $dashView.querySelectorAll('[data-open]').forEach(btn => {
    btn.onclick = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      revealFile(btn.getAttribute('data-open'), btn);
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

  if (items.length > 3) _applyListFilter($dashView.querySelector('.list-filter-input'));
}

async function runFeasibilityFromOpp(opp_id, idx) {
  // 卷四十六续 9 · BRO 反馈"可行性分析也是不通过 LLM 来跑·我想他和信息雷达今日趋势对齐·都是 LLM 开始呈现思考过程·最后刷新结果"
  // 旧路径: 直接 fetch /dashboard/feasibility?refresh=true (HTTP 黑盒 · 整个面板空白等 5-15s)
  // 新路径: injectAndSend → LLM 调 analyze_feasibility 工具 · BRO 看分析过程 · 完成后 MUTATING_TOOLS 自动 reload feasibility view
  if (opp_id) {
    spawnTask(
      `分析机会 ${opp_id} (第 ${idx} 个) 的可行性 · ` +
      `调 analyze_feasibility 工具 · 参数 action=analyze, opp_id="${opp_id}" · ` +
      `跑完告诉我 verdict (go/conditional/wait/skip) + 关键风险 + 你最担心什么 + 推不推荐 BRO 真动手`,
      `可行性分析 · 机会#${idx}`
    );
  } else {
    spawnTask(
      `分析第 ${idx} 个机会的可行性 · ` +
      `调 analyze_feasibility 工具 · 参数 action=analyze, opp_index=${idx} · ` +
      `跑完告诉我 verdict (go/conditional/wait/skip) + 关键风险 + 你最担心什么 + 推不推荐 BRO 真动手`,
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
    hint.textContent = ok ? '<i class="ri-check-fill"></i> 已保存 · 下次 OPUS 跑掘金/可行性会读到' : '<i class="ri-close-fill"></i> 保存失败';
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
    `BRO 邀请你看一眼 self-evolve 雷达上的这个工程：「${title}」${urlPart}\n\n` +
    `**这是邀请·不是命令** —— 你要自己判断·不是 BRO 让你装你就装。\n\n` +
    `请你：\n` +
    `1. 用 web_search / web_fetch 弄清这个工程做啥 · 看 README / 主要特性\n` +
    `2. 对照本工作台现状·想清楚：\n` +
    `   - 你有没有这个能力·还是缺\n` +
    `   - 它的设计哲学跟本工作台是否合拍 (人机协同 / 双向认知 / 可追溯)\n` +
    `   - 如果合拍·这能力对 BRO 这个具体的人有啥用 (而不是"通用上有用")\n` +
    `3. 然后明确告诉 BRO：\n` +
    `   - 值得装 → 调 wish_add 写一份心愿 (title / why / source_kind=radar / source_ref + url / design_sketch / complexity / hours / priority / opus_take = 你自己的态度)\n` +
    `   - 不值得装 → 说清为啥·别强加 wish 占心愿单\n` +
    `   - 拿不准 → 就说拿不准·要 BRO 给更多 context\n` +
    `**你才是搭档·不是给 BRO 端菜的工具人**·拿出判断力。`,
    `勘察: ${title}`
  );
}
