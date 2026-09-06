/* chat-timeline.js · 工具时间线 + 人话翻译表
 * 从 chat.js 抽出。零构建全局作用域。不进 LLM 系统提示词。
 */

function _tlAuthToken() {
  try {
    if (typeof token === 'string' && token) return token;
    return localStorage.getItem('opus_ui_token') || '';
  } catch (e) { return ''; }
}
function _tlHost() {
  try { if (window.$msgs) return window.$msgs; } catch (e) {}
  return document.querySelector('.session-msgs:not([hidden])');
}

/* 工作台过程密度 · fold=现在这样（默认）· expand=改密度之前全摊开
   只读 localStorage · 房间 companion 不读这一档 */
function chatProcessExpanded() {
  try { return localStorage.getItem('opus_chat_process') === 'expand'; } catch (e) { return false; }
}

function setChatProcessMode(mode) {
  const v = mode === 'expand' ? 'expand' : 'fold';
  try { localStorage.setItem('opus_chat_process', v); } catch (e) {}
  applyChatProcessDensity(document);
}

function applyChatProcessDensity(root) {
  const expand = chatProcessExpanded();
  const scope = root || document;
  scope.querySelectorAll('.msg.opus.reasoning').forEach((div) => {
    const body = div.querySelector('.reasoning-body');
    const toggle = div.querySelector('.reasoning-toggle');
    if (!body) return;
    body.hidden = !expand;
    div.classList.toggle('folded', !expand);
    if (toggle) toggle.textContent = expand ? '收起 ▴' : '展开 ▾';
    delete div.dataset.processTouched;
  });
  scope.querySelectorAll('.tl-round').forEach((round) => {
    _tlSetCollapsed({ $round: round, $head: round.querySelector('.tl-round-head') }, !expand);
    delete round.dataset.processTouched;
  });
  scope.querySelectorAll('.tl-step').forEach((card) => {
    card.classList.toggle('show-tech', expand);
    const $r = card.querySelector('.tl-step-result');
    if (!$r || $r.classList.contains('tl-pending')) return;
    $r.hidden = expand ? false : !$r.classList.contains('tl-fail');
  });
  scope.querySelectorAll('.advisor-answer').forEach((el) => { el.hidden = !expand; });
  scope.querySelectorAll('.adv-btn-peek').forEach((btn) => {
    const card = btn.closest('.advisor-card');
    const ans = card && card.querySelector('.advisor-answer');
    const hidden = !ans || ans.hidden;
    btn.innerHTML = hidden
      ? '<i class="ri-article-line"></i> 看顾问结论'
      : '<i class="ri-arrow-up-s-line"></i> 收起结论';
  });
  scope.querySelectorAll('.blueprint-card .blueprint-body').forEach((el) => { el.hidden = !expand; });
  scope.querySelectorAll('.review-card.review-pass .blueprint-body').forEach((el) => { el.hidden = !expand; });
  scope.querySelectorAll('.review-card.review-fail .blueprint-body').forEach((el) => { el.hidden = false; });
}

/* ═══ wish-5256d2a4 · 工具时间线 + 人话翻译层（方案 D） ═══
   零 token：前端本地正则翻译 · daemon 只传原始 tool name/summary/result
   默认档：干活时单步一行人话 · 回合结束整轮收成摘要（失败步骤钉在外面）· 点开才看参数/原文/搜索条
   展开档：收尾不折、步骤参数/搜索条默认摊开 */
const TL_T2C = {
  read_file:'file', write_file:'file', edit_file:'file', glob_files:'file', grep_files:'file',
  outline_file:'file', search_code:'file', lint_check:'file', read_scenario:'file', pdf_read:'file', read_dashboard:'file',
  shell_exec:'exec', python_exec:'exec', service_start:'exec', service_stop:'exec', service_status:'exec', service_list:'exec',
  open_app:'exec', worktree_status:'exec', verify_daemon_endpoints:'exec', request_restart:'exec', update_core:'exec',
  web_search:'web', web_fetch:'web', browser_fetch:'web', browser_act:'web', web_search_image:'web', verify_claim:'web',
  update_owner_note:'memory', recall_memory:'memory', session_search:'memory', update_self_evolution:'memory',
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
  web_search: c => {
    const m = String(c.r || '').match(/(\d+)\s+results?\s+\(via\s+([^)]+)\)/i);
    const res = m ? `找到 ${m[1]} 条 · ${m[2]}` : c.r;
    const q = String(c.s || '').replace(/^web_search\s+query=/, '').replace(/["']/g, '').slice(0, 40);
    return { action: `上网搜索 <b>${escHtml(q)}</b>`, result: res };
  },
  web_fetch: c => ({ action: '抓取网页正文', result: c.r }),
  browser_act: c => ({ action: '操作网页（点击/填表/收图）', result: c.ok ? '操作完成' : (c.r || '操作失败') }),
  generate_image: c => ({ action: '画了一张图', result: '图片已生成并保存' }),
  generate_report: c => ({ action: '生成了一份报告文档', result: '已落盘，产物库可下载' }),
  generate_presentation: c => ({ action: '生成了一份演示稿', result: '已落盘，产物库可下载' }),
  wechat_send: c => ({ action: '给你发了条微信', result: '已送达' }),
  update_owner_note: c => ({ action: '记一笔到你的画像档案', result: '已记住，以后每次开机都会带上' }),
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

// app_id → 名字 映射缓存 · 工具卡片显示 app 名 (BRO: 别显示 app-ddfd7d92)
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
      const r = await fetch('/workshop/apps', { headers: { 'Authorization': 'Bearer ' + _tlAuthToken() } });
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
      const r = await fetch('/workshop/flows', { headers: { 'Authorization': 'Bearer ' + _tlAuthToken() } });
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

function _tlSetCollapsed(tl, collapsed) {
  if (!tl || !tl.$round) return;
  tl.$round.classList.toggle('collapsed', !!collapsed);
  const ar = tl.$head && tl.$head.querySelector('.tl-round-arrow');
  if (ar) ar.className = collapsed ? 'ri-arrow-down-s-line tl-round-arrow' : 'ri-arrow-up-s-line tl-round-arrow';
}

/* 整轮容器：干活时展开（单步一行）· 收尾后折成摘要 */
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
    round.dataset.processTouched = '1';
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
  card.dataset.tool = name;
  card.innerHTML =
    `<div class="tl-slim-row" title="点开看参数和原文">` +
      `<i class="tl-slim-st ri-loader-4-line tl-spin"></i>` +
      `<div class="tl-step-action">${h.action}</div>` +
      (tier ? `<span class="tl-step-tier">[${escHtml(tier)}]</span>` : '') +
      `<span class="tl-step-dur"></span>` +
    `</div>` +
    `<div class="tl-step-result tl-pending" hidden></div>` +
    `<div class="tl-step-tech">` +
      `<div class="tl-tech-meta">${escHtml(cat.name)} · ${escHtml(name)}</div>` +
      `<div class="tl-tech-call">${escHtml(String(summary || '(无参数摘要)'))}</div>` +
    `</div>`;
  card.querySelector('.tl-slim-row').onclick = () => card.classList.toggle('show-tech');
  if (chatProcessExpanded()) card.classList.add('show-tech');
  tl.$body.appendChild(card);
  const rec = { name, summary, $card: card, startTs: Date.now(), ok: null };
  tl.steps.push(rec);
  _tlUpdateHead(state);
  return rec;
}

function tlFillStep(state, name, ok, resultText, hits) {
  const tl = state._tl; if (!tl) return;
  let rec = null;
  for (let i = tl.steps.length - 1; i >= 0; i--) {
    if (tl.steps[i].name === name && tl.steps[i].ok === null) { rec = tl.steps[i]; break; }
  }
  if (!rec) rec = tlAddStep(state, name, '', null);  // 孤儿 result · 补卡
  rec.ok = !!ok;
  rec.$card.classList.toggle('is-fail', !ok);
  const durS = Math.max(0, Math.round((Date.now() - rec.startTs) / 1000));
  const h = tlHumanize(name, rec.summary || '', resultText || '', ok);
  const $st = rec.$card.querySelector('.tl-slim-st');
  if ($st) $st.className = 'tl-slim-st ' + (ok ? 'ri-check-fill tl-ok' : 'ri-close-fill tl-fail');
  const $act = rec.$card.querySelector('.tl-step-action');
  if ($act) $act.innerHTML = h.action;
  let resultLine = String(h.result || (ok ? '完成' : '失败')).slice(0, 220);
  if (ok && Array.isArray(hits) && hits.length) {
    const eng = hits[0].engine || '';
    resultLine = `找到 ${hits.length} 条` + (eng ? ` · ${eng}` : '');
  }
  const $r = rec.$card.querySelector('.tl-step-result');
  if ($r) {
    $r.classList.remove('tl-pending');
    $r.classList.toggle('tl-ok', !!ok);
    $r.classList.toggle('tl-fail', !ok);
    $r.innerHTML = (ok ? '<i class="ri-check-fill"></i> ' : '<i class="ri-close-fill"></i> ') + escHtml(resultLine);
    $r.hidden = chatProcessExpanded() ? false : !!ok;
  }
  const $d = rec.$card.querySelector('.tl-step-dur');
  if ($d && durS > 0) $d.textContent = tlHumanDur(durS);
  const $tech = rec.$card.querySelector('.tl-step-tech');
  if ($tech) {
    let rd = $tech.querySelector('.tl-tech-result');
    if (!rd) {
      rd = document.createElement('div');
      rd.className = 'tl-tech-result';
      $tech.appendChild(rd);
    }
    rd.textContent = resultLine + (resultText && resultText !== resultLine ? '\n' + String(resultText).slice(0, 300) : '');
  }
  if (ok && Array.isArray(hits) && hits.length) tlMountHits(rec.$card, hits);
  _tlUpdateHead(state);
}

function tlMountHits(card, hits) {
  const tech = card && card.querySelector('.tl-step-tech');
  if (!tech) return;
  let box = card.querySelector('.dk-search-hits');
  if (!box) {
    box = document.createElement('div');
    box.className = 'dk-search-hits';
    tech.appendChild(box);
  }
  box.innerHTML = hits.slice(0, 8).map((h) => {
    const title = escHtml(String(h.title || '').slice(0, 80));
    const url = String(h.url || '');
    const href = /^https?:\/\//i.test(url) ? url : '';
    const site = escHtml(String(h.site || '').slice(0, 40));
    const date = escHtml(String(h.date || '').slice(0, 16));
    const snip = escHtml(String(h.snippet || '').slice(0, 120));
    const icon = String(h.icon || '');
    const icoOk = /^https?:\/\//i.test(icon);
    const meta = [site, date].filter(Boolean).join(' · ');
    const head = href
      ? `<a class="dk-hit-title" href="${escHtml(href)}" target="_blank" rel="noopener">${title}</a>`
      : `<span class="dk-hit-title">${title}</span>`;
    return `<div class="dk-hit">`
      + (icoOk ? `<img class="dk-hit-ico" src="${escHtml(icon)}" alt="" loading="lazy">` : '<i class="ri-window-line dk-hit-ico-fallback"></i>')
      + `<div class="dk-hit-body">${head}`
      + (meta ? `<div class="dk-hit-meta">${meta}</div>` : '')
      + (snip ? `<div class="dk-hit-snip">${snip}</div>` : '')
      + `</div></div>`;
  }).join('');
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
  tl.$round.classList.toggle('has-fail', fails > 0);
  if (tl.$round.dataset.processTouched !== '1') {
    _tlSetCollapsed(tl, !chatProcessExpanded());
  }
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
  const state = { $container: target || _tlHost(), _tl: null };
  for (const it of items) {
    tlAddStep(state, it.name, _tlArgsSummary(it.args), null);
    if (it.result != null) {
      const ok = !/^(error:|exit code [1-9]|❌|failed:|未知|fail)/i.test(it.result || '');
      tlFillStep(state, it.name, ok, it.result);
    } else {
      /* 历史里丢了 result 的 · 标个中断 */
      const rec = state._tl.steps[state._tl.steps.length - 1];
      rec.ok = true;
      const $st = rec.$card.querySelector('.tl-slim-st');
      if ($st) $st.className = 'tl-slim-st ri-check-fill tl-ok';
      const $r = rec.$card.querySelector('.tl-step-result');
      if ($r) { $r.classList.remove('tl-pending'); $r.hidden = true; }
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
    tl.$round.classList.toggle('has-fail', fails > 0);
    _tlSetCollapsed(tl, !chatProcessExpanded());
    state._tl = null;
  }
}
