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

  /* wish-eeff6e5e · 密度档挂上 <html data-proc> · fold 档的过程样式全走这个钩子 · expand 一律原样 */

  try { document.documentElement.dataset.proc = expand ? 'expand' : 'fold'; } catch (e) {}

  /* 切档清窗口标记（fold 档干活时被压出窗口的老步骤 · 切回来全部可见） */

  scope.querySelectorAll('.tl-step.tl-out').forEach((el) => { el.classList.remove('tl-out'); });

  scope.querySelectorAll('.msg.opus.reasoning').forEach((div) => {

    const body = div.querySelector('.reasoning-body');

    const toggle = div.querySelector('.reasoning-toggle');

    if (expand) div.classList.remove('proc-think-hidden');   // wish-eeff6e5e · expand 全摊开：被卡片收拢的思考也还原

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

  /* wish-eeff6e5e 终轮 · 高频工具人话补齐（图1里 session_search 双重名 + 裸参数不可读）*/

  session_search: c => ({ action: `翻了会话记录 <b>${String(c.s).replace(/^query=|.*?query=/, '').replace(/'/g, '').slice(0, 24)}</b>`, result: '记录翻完，相关内容已装进上下文' }),

  browser_act: c => ({ action: `在浏览器里${/goto/.test(c.s) ? '打开了页面' : /click/.test(c.s) ? '点了页面元素' : /read|inspect/.test(c.s) ? '读了页面内容' : '做了操作'}`, result: c.ok ? '页面响应正常' : '操作失败' }),

  catalog_call: c => ({ action: `调用扩展工具 <b>${String(c.s).replace(/^name=|.*?name=/, '').split(/[,&\s]/)[0].slice(0, 20)}</b>`, result: '调用完成' }),

  catalog_search: c => ({ action: `找了可用的扩展工具`, result: '清单已拿到' }),

  track_task: c => ({ action: `更新了任务账本`, result: '账本已同步' }),

  lint_check: c => ({ action: `代码体检 <b>${tlFileName(c.s)}</b>`, result: c.ok ? '没扫到问题' : '扫到问题，需修' }),

  look_at: c => ({ action: `看了张图`, result: '图已识别' }),

  service_start: c => ({ action: `起了后台服务 <b>${String(c.s).replace(/^name=|.*?name=/, '').slice(0, 20)}</b>`, result: c.ok ? '服务已在跑' : '起服务失败' }),

  service_stop: c => ({ action: `停了后台服务`, result: '已停' }),

  web_search: c => ({ action: `网上搜了 <b>${String(c.s).replace(/^query=|.*?query=/, '').slice(0, 24)}</b>`, result: '结果已拿到' }),

  web_fetch: c => ({ action: `读了网页 <b>${String(c.s).replace(/^url=|.*?url=/, '').slice(0, 28)}</b>`, result: '正文已抓取' }),

  worktree_status: c => ({ action: `看了 git 工作区`, result: '分支状态已确认' }),

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

  let h = null;

  if (f) { try { h = f(c); } catch (e) {} }

  if (!h) {

    // 默认兜底: 统一把 app-xxx / flow-xxx 换成名字 (所有 workshop 工具自动覆盖 · 不漏)

    let s0 = String(summary || '');

    /* wish-eeff6e5e 终轮 · daemon 的参数摘要自带工具名前缀 · 去重（图1里「session_search session_search · …」双重名）*/

    if (s0.toLowerCase().startsWith(String(tool).toLowerCase())) s0 = s0.slice(tool.length).replace(/^[·\s:：]+/, '');

    let s = s0.slice(0, 60);

    s = s.replace(/app-[0-9a-f]{6,}/gi, m => { const n = appNameOf(m); return n ? n : m; })

          .replace(/flow-[0-9a-f]{6,}/gi, m => { const n = flowNameOf(m); return n ? n : m; });

    h = { action: `<b>${escHtml(tool)}</b> ${escHtml(s)}`, result: String(resultText || '') };

  }

  // 失败兜底 (2026-09-10): TL_HUMAN 里大量映射是照「成功」写死的硬编码人话

  // (wish_add → '已存档，等你拍板' / wechat_send → '已送达' / generate_image → '图片已生成并保存' …)，

  // 它们都不看 ok，失败时于是渲染出「✗ 已存档，等你拍板」这种图标与文字自相矛盾的卡。

  // 这里统一兜住：ok === false 时不用人话成功文案，一律换成真实错误文本。

  if (ok === false) {

    h = { action: h.action, result: String(resultText || '').replace(/^\[TOOL ERROR\]\s*/, '').trim() || '失败' };

  }

  return h;

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

  /* wish-eeff6e5e fold21 · 上栏：思考槽。
     单一所有权 —— 只有流式(appendReasoningDelta)和一次性收养(_tlLiveAdopt)往里写；
     里程碑重建(_tlMilesRender)只碰 .tl-miles，永不碰这里。
     fold21 结构调整：摘要行 lrow 留在 round 下（收拢态可见）；
     思考正文 lbox 搬进 .tl-round-body —— 与步骤共用同一个限高滚动区，卡里只一个滚动条。 */
  const live = document.createElement('div');
  live.className = 'tl-live';
  const lrow = document.createElement('div');
  lrow.className = 'tl-mile tl-think-row';
  lrow.innerHTML = '<span class="tl-mile-k">▸</span><span class="tl-mile-x">思考中</span><span class="tl-think-hint">点击展开</span>';
  let selfTl = null;   /* 汇总行常驻（生长态也看得到）· 点它 = 摊开/收起段列表 */
  lrow.onclick = () => {
    lbox.hidden = !lbox.hidden;
    if (selfTl) _tlLiveRowText(selfTl, false);
  };
  const lbox = document.createElement('div');
  lbox.className = 'tl-thinks tl-live-box';
  lbox.hidden = true;   /* 段列表默认收着 —— 先看「思考共 N 段 · 共 X 字」，点开才见 1234 */
  live.appendChild(lrow);
  live.appendChild(lbox);   /* 留在卡外（与汇总行同层）—— 收拢态也点得开；它不自己滚，卡里仍只一个滚动条 */

  head.onclick = () => {

    round.classList.toggle('collapsed');

    round.dataset.processTouched = '1';

    const ar = head.querySelector('.tl-round-arrow');

    if (ar) ar.className = round.classList.contains('collapsed') ? 'ri-arrow-down-s-line tl-round-arrow' : 'ri-arrow-up-s-line tl-round-arrow';

  };

  round.appendChild(head);

  round.appendChild(live);   /* 上栏 · 思考 */

  round.appendChild(body);   /* 下栏 · 工具步骤 */

  /* wish-eeff6e5e 终轮+2 · 收起条固定在滚动窗口正下方（不随内容滚 · 拉到哪都能点）· head 已恒藏没有它展开后回不去 */

  const foldBar = document.createElement('div');

  foldBar.className = 'tl-fold-bar';

  foldBar.textContent = '收起 ▴';

  /* 2026-09-15 · 「生长中不给收起」只在 CSS 单点判定：
     .tl-round:not(.collapsed):not(.tl-growing) .tl-fold-bar { display:block }
     这里不重复判定：CSS 已让生长中的按钮 display:none（收不到 click），写了也是死分支；
     两处各写一遍反而会在将来改判定时分成两岔（code_review 20260915-013135）。
     收拢时会摘掉 tl-growing（_tlSetCollapsed），所以展开态仍有「收起」入口。 */
  foldBar.onclick = () => { round.classList.add('collapsed'); round.dataset.processTouched = '1'; };

  round.appendChild(foldBar);

  if (state.$container) state.$container.appendChild(round);

  /* wish-eeff6e5e 终轮+7 · 生长中标记：限高/渐隐/呼吸点只挂在它身上 · 收拢后展开态全量展示 */

  round.classList.add('tl-growing');

  state._tl = { $round: round, $head: head, $live: live, $liveRow: lrow, $liveBox: lbox, $body: body, steps: [], startTs: Date.now() };

  selfTl = state._tl;

  return state._tl;

}



/* wish-eeff6e5e fold21 · 汇总行文案：生长态「思考中…」/ 完成态「思考共 N 段 · 共 X 字」（箭头跟段列表开合）*/
function _tlLiveRowText(tl, streaming) {
  const row = tl && tl.$liveRow;
  if (!row) return;
  /* fold28 · BRO：过程中也要能自己刷新「思考到第几段 · 多少字」——只有"一段都还没有"时才报思考中 */
  const n = tl._histThinkN || 0;
  if (!n) {
    row.innerHTML = '<span class="tl-mile-k">▸</span><span class="tl-mile-x">思考中…</span><span class="tl-think-hint"></span>';
    return;
  }
  const cs = _tlFmtChars(tl._histThinkChars || 0);
  const open = !!(tl.$liveBox && !tl.$liveBox.hidden);
  row.innerHTML = '<span class="tl-mile-k">' + (open ? '▾' : '▸') + '</span>'
    + '<span class="tl-mile-x">思考共 <b>' + n + ' 段</b>' + (cs ? ' · 共 ' + cs + ' 字' : '') + '</span>'
    + '<span class="tl-think-hint">' + (open ? '点击收起' : '点击展开') + '</span>';
}

function _tlFmtChars(c) {
  if (!c) return '';
  return c > 999 ? (c / 1000).toFixed(1) + 'k' : String(c);
}

/* wish-eeff6e5e fold21 · 思考分段条目（BRO：一个思考一段 · 展开后才看得到每段）
   一段一行 · 点这行摊开/收起那一段正文 —— 建时即绑，不靠重建后的查询（R2）。 */
/* 段条目：左「思考 01」右「共 11.0k 字」（字数列靠右对齐 · BRO 拍板）*/
function _tlSegLabel(idx) {
  const i = parseInt(idx, 10) || 0;
  return '思考 ' + (i < 10 ? '0' + i : String(i));
}
function _tlSegChars(chars) {
  const c = _tlFmtChars(chars);
  return c ? '共 ' + c + ' 字' : '';
}

function _tlSegHead(idx, chars, open) {
  const h = document.createElement('div');
  h.className = 'tl-seg-head';
  h.dataset.idx = idx;
  h.dataset.chars = chars || '';
  h.dataset.open = open ? '1' : '0';
  const k = document.createElement('span');
  k.className = 'tl-seg-k';
  k.textContent = open ? '▾' : '▸';
  const x = document.createElement('span');
  x.className = 'tl-seg-x';
  x.textContent = _tlSegLabel(idx);
  const c = document.createElement('span');
  c.className = 'tl-seg-c';
  c.textContent = _tlSegChars(chars);
  h.appendChild(k);
  h.appendChild(x);
  h.appendChild(c);
  h._k = k; h._x = x; h._c = c;   /* 引用直存：结算时不再查 DOM */
  return h;
}

/* 段头 ↔ 段正文绑定（引用捕获 · 不查 DOM）*/
function _tlSegBind(head, el) {
  head.onclick = () => {
    const open = head.dataset.open === '1';
    head.dataset.open = open ? '0' : '1';
    el.hidden = open;
    if (head._k) head._k.textContent = open ? '▸' : '▾';
  };
}

/* 流完定格这段的字数 */
function _tlSegSettle(head, chars) {
  if (!head || !head.classList || !head.classList.contains('tl-seg-head')) return;
  head.dataset.chars = chars || '';
  if (head._x) head._x.textContent = _tlSegLabel(head.dataset.idx);
  if (head._c) head._c.textContent = _tlSegChars(chars);
  if (head._k) head._k.textContent = head.dataset.open === '1' ? '▾' : '▸';   /* 结算时同步箭头 */
}

/* ═══════════════════════════════════════════════════════════════
   wish-eeff6e5e fold23 · 过程卡【统一渲染出口】

   铁律：思考与工具都只经过这里长进卡里 —— 实时(SSE 事件)与回放(jsonl 历史)
   喂的是同一套函数 · 所以两条路永远长得一样。
   思考【不再】先建“对话栏里的独立泡”再往卡里搬 —— 那是野指针与双写的老巢。
   ═══════════════════════════════════════════════════════════════ */

/* 拿本回复所属的卡：有则复用 · 否则新建（回放续卡靠 _tlHistLive 的“无边界”判定）*/
function _procRound(state) {
  if (!state) return null;
  if (state._tl && state._tl.$round && state._tl.$round.isConnected) return state._tl;
  if (_tlHistLive && _tlHistLive.tl && _tlHistLive.tl.$round && _tlHistLive.tl.$round.isConnected
      && _tlHistLive.$container === state.$container) {
    let el = _tlHistLive.tl.$round.nextElementSibling, boundary = false;
    while (el) { if (_tlHistBoundary(el)) { boundary = true; break; } el = el.nextElementSibling; }
    if (!boundary) { state._tl = _tlHistLive.tl; _tlSetCollapsed(_tlHistLive.tl, false); return _tlHistLive.tl; }
  }
  return _tlEnsureRound(state);
}

/* fold27 · 新回合开始：断掉“续卡链”。
   _tlHistLive 的语义是「回放/同轮内连续 assistant 段共用一张卡」；
   它一旦跨到下一轮，procThinkIdle/procThinkPush 就会把上一轮的卡认领走并 appendChild 到容器末尾
   —— BRO 实测：上一轮的卡跑到输入框(用户气泡)下面。回合起点清一次，卡就各归各位。 */
function procTurnStart(state) {
  _tlHistLive = null;
  if (state) state._tl = null;
}

/* 回合刚开始、还没有任何思考字/工具时：把卡立起来并显示一行「▸ 思考中…」
   —— BRO：你输出过程也要能看到折叠卡片（否则第一个字之前屏幕上什么都没有）。
   若这轮最终既没思考也没工具，回合末的 tlFinishRound / procHistSeal 会把它清掉。 */
function procThinkIdle(state) {
  if (!state) return;
  /* 非折叠模式（expand）完全不插手：那边要的就是全部铺开，不该冒出过程卡 */
  if (typeof chatProcessExpanded === 'function' && chatProcessExpanded()) return;
  const tl = _procRound(state);
  if (!tl) return;
  tl.$live.classList.add('has-think');
  if (!(tl._histThinkN > 0)) _tlLiveRowText(tl, true);   /* 没段数就显示「▸ 思考中…」 */
  _tlKeepAtEnd(state);
  try { scrollToBottom(state.$container, { force: false }); } catch (e) {}   /* 立卡就拉到看得见 */
}

/* 一段思考入卡（回放传全文 / 实时传空串后用 delta 追加）· 返回段句柄 */
function procThinkPush(state, text, opts) {
  if (!state) return null;
  const streaming = !!(opts && opts.streaming);
  const tl = _procRound(state);
  tl.$live.classList.add('has-think');
  if (!tl._histThinkEls) tl._histThinkEls = [];
  if (!tl._segSeq) tl._segSeq = 0;
  const idx = ++tl._segSeq;
  const head = _tlSegHead(idx, text ? text.length : 0, streaming);
  const div = document.createElement('div');
  div.className = 'msg opus reasoning';
  const body = document.createElement('div');
  body.className = 'reasoning-body';
  if (text) body.appendChild(document.createTextNode(text));
  div.appendChild(body);
  _tlSegBind(head, div);
  tl.$liveBox.appendChild(head);
  tl.$liveBox.appendChild(div);
  tl._histThinkEls.push(div);
  tl._histThinkN = tl._histThinkEls.length;
  div.hidden = true;   /* fold28 · BRO 拍板：实时也收着 —— 点「思考 NN」才展开，正在写的那段只给动效 */
  if (streaming) head.classList.add('is-live');
  const seg = { tl, head, div, body };
  _procThinkSettle(tl);   /* 立刻刷新「N 段 · X 字」，不等这段写完 */
  _tlHistLive = { tl, tailEl: state.$container ? state.$container.lastElementChild : null, $container: state.$container };
  if (!streaming) {
    /* 回放：本轮同步渲染跑完再封卡（同一回复后面还有 turn · 会清掉这个定时器接着长）*/
    clearTimeout(tl._sealTimer);
    tl._sealTimer = setTimeout(() => {
      if (tl.$round && tl.$round.isConnected) procHistSeal({ _tl: tl });
    }, 0);
  }
  return seg;
}

function procThinkDelta(seg, piece) {
  if (!seg || !seg.body || !piece) return;
  seg.body.appendChild(document.createTextNode(piece));
  /* fold28 · 边写边刷汇总（节流到一帧一次），BRO 才能看着段数 / 字数涨 */
  if (!seg._settleRaf) {
    seg._settleRaf = requestAnimationFrame(() => { seg._settleRaf = 0; _procThinkSettle(seg.tl); });
  }
}

/* 一段写完：原地收成一条目（不搬父节点）*/
function procThinkSeal(seg) {
  if (!seg || !seg.head) return;
  const chars = (seg.body.textContent || '').length;
  seg.head.classList.remove('is-live');   /* fold28 · 这段写完了，别再呼吸 */
  _tlSegSettle(seg.head, chars);
  seg.head.dataset.open = '0';
  const k = seg.head.querySelector('.tl-seg-k');
  if (k) k.textContent = '▸';
  seg.div.hidden = true;
  if (seg.tl) _procThinkSettle(seg.tl);
}

/* 汇总行（思考共 N 段 · 共 X 字）· 从存活元素重算 —— 幂等 · 重渲不双计 */
function _procThinkSettle(tl) {
  if (!tl) return;
  let chars = 0;
  (tl._histThinkEls || []).forEach((el) => {
    const bd = el.querySelector('.reasoning-body');
    const len = bd ? (bd.textContent || '').length : 0;
    chars += len;
    /* fold28 · 段条目右侧字数也跟着实时涨 */
    const head = el.previousElementSibling;
    if (head && head.classList && head.classList.contains('tl-seg-head')) _tlSegSettle(head, len);
  });
  tl._histThinkN = (tl._histThinkEls || []).length;
  tl._histThinkChars = chars;
  if (tl._histThinkN) { tl.$live.classList.add('has-think'); _tlLiveRowText(tl, false); }
}

/* 让卡跟在「当前回复已渲染内容的末尾」（BRO：卡该在我输出的下面）
   正文是容器的直接子元素，每追加一段就会跑到卡前面 —— 所以每次追加后把卡再跟下去。
   卡【必须在容器末尾】：容器里只有本回合在追加 · 不会像回放那样跨回复。 */
function _tlKeepAtEnd(state) {
  const tl = state && state._tl;
  if (!tl || !tl.$round || !tl.$round.parentElement) return;
  const cont = tl.$round.parentElement;
  if (cont.lastElementChild !== tl.$round) cont.appendChild(tl.$round);
}

/* 【回复边界】封卡：收拢 + 让下一段内容另起一张 · 实时与回放都调它 */
function procHistSeal(state) {
  if (!state || !state._tl) return;
  const tl = state._tl;
  if (!tl.$round || !tl.$round.isConnected) { state._tl = null; return; }
  const cont = state.$container || tl.$round.parentElement;
  tl.$round.classList.remove('tl-growing');
  _procThinkSettle(tl);
  _tlMilesRender(tl, false, {});
  _tlSetCollapsed(tl, !chatProcessExpanded());
  /* 收拢后把卡移到【本回复末尾】（BRO：卡该在我输出的下面）
     —— 从卡到下一个回复边界之间的最后一个兄弟之后。
     不能用容器末尾：定时封卡是全渲染完成后才跑，那样每张卡都会往底部挤成一摞。 */
  if (cont && tl.$round.parentElement === cont) {
    let last = tl.$round, el = tl.$round.nextElementSibling;
    while (el && !_tlHistBoundary(el)) { last = el; el = el.nextElementSibling; }
    if (last !== tl.$round) last.after(tl.$round);
  }
  _tlHistLive = null;   /* 封卡 = 回复边界 · 断开续卡链，下个回复另起一张 */
  state._tl = null;
}

/* wish-eeff6e5e fold29 · _tlLiveAdopt 已删 —— fold23 统一出口后思考一开始就长在槽里，没人再需要"收养"。 */



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

  const rec = { name, summary, $card: card, startTs: Date.now(), ok: null, action: h.action };

  tl.steps.push(rec);

  _tlUpdateHead(state);

  _tlWindowPush(state);   /* wish-eeff6e5e · fold 档干活窗口：老步骤压 .tl-out 只留最近几条 */

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

  rec.action = h.action;   /* wish-eeff6e5e · 人话留进数据层 · 收拢算里程碑时用 */

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



/* ═══ wish-eeff6e5e · 长任务过程「生长→收拢」（仅 fold 档 · expand 档原样） ═══

   生长：干活窗口只留最近几条 · 老步骤压成 .tl-out（不删 · 收拢/展开后还在）

   收拢：轮末从 steps 的结构化信号算里程碑（失败必露 / 改文件·验证·产物露 / 纯读取收）

   全程不引容器、不改挂点 —— 数据从 state._tl.steps 内存数组算 · 与 DOM 归属无关 */

const _TL_WIN_KEEP = 3;

function _tlWindowPush(state) {

  if (!state || state.noWindow || chatProcessExpanded()) return;

  const tl = state._tl; if (!tl || !tl.$body) return;

  const rows = tl.$body.querySelectorAll('.tl-step');

  const cutoff = rows.length - _TL_WIN_KEEP;

  rows.forEach((el, i) => { el.classList.toggle('tl-out', i < cutoff); });

}



/* 里程碑分级：fail=失败/被打断必露 · ok=改文件/验证/产物/git存档 露 · null=收进 quiet 计数 */

const _TL_MILE_LOUD = {

  edit_file: 1, write_file: 1, lint_check: 1, verify_daemon_endpoints: 1, python_exec: 1,

  generate_report: 1, generate_presentation: 1, generate_image: 1, draft_studio: 1,

  create_app: 1, create_workflow: 1, request_restart: 1, safe_merge: 1

};

function _tlMileLevel(rec) {

  if (rec.ok !== true) return 'fail';   /* 失败 · 或收尾时仍 pending（abort/出错被打断）· 都必露 */

  if (_TL_MILE_LOUD[rec.name]) return 'ok';

  if (rec.name === 'shell_exec' && /git\s+(commit|push|merge)/i.test(rec.summary || '')) return 'ok';

  return null;

}

function _tlMileFile(rec) {

  /* 从 args 摘要提文件名（path=xxx · N+ args）*/

  const m = /path=([^·\n]+)/.exec(rec.summary || '');

  return m ? m[1].trim() : '';

}

function _tlMilesBuild(tl) {

  const miles = []; let quiet = 0;

  const isEdit = (n) => n === 'edit_file' || n === 'write_file';

  const isCheck = (n) => n === 'lint_check' || n === 'verify_daemon_endpoints' || n === 'python_exec' || n === 'shell_exec';

  /* v1 原型同类合并：14 条「修改代码文件」= 1 条「改了 N 个文件（…）」· 检查/命令类同理归并 */

  const buckets = new Map();   /* key -> { count, files, first } */

  for (let i = 0; i < tl.steps.length; i++) {

    const rec = tl.steps[i];

    let lvl = _tlMileLevel(rec);

    if (lvl === 'fail') {

      /* 自愈降级：失败后同工具后续成功 = 只是抖动 · 不举红叉 · 收 quiet */

      const healed = tl.steps.slice(i + 1).some(s => s.name === rec.name && s.ok === true);

      if (healed) lvl = null;

    }

    if (!lvl) { quiet++; continue; }

    if (lvl === 'fail') { miles.push({ lvl, html: rec.action || ('<b>' + escHtml(rec.name) + '</b>') }); continue; }

    /* write_file 并进 edit_file 桶 · 各检查工具归一桶 · 统一「改了 N 个文件」「跑了 N 次检查/命令」 */

    const gkey = isEdit(rec.name) ? '_edit' : (isCheck(rec.name) ? '_check' : rec.name);

    if (!buckets.has(gkey)) buckets.set(gkey, { count: 0, files: [], first: rec });

    const b = buckets.get(gkey);

    b.count++;

    const f = _tlMileFile(rec);

    if (f && b.files.length < 6 && b.files.indexOf(f) < 0) b.files.push(f);

  }

  buckets.forEach((b, gkey) => {

    if (gkey === '_edit') {

      const det = b.files.length ? '（' + escHtml(b.files.slice(0, 4).join(' · ')) + (b.files.length > 4 ? ' 等' : '') + '）' : '';

      miles.push({ lvl: 'ok', html: `改了 <b>${b.count} 个文件</b>${det}` });

    } else if (gkey === '_check') {

      miles.push({ lvl: 'ok', html: `跑了 <b>${b.count} 次</b>检查/命令` });

    } else {

      miles.push({ lvl: 'ok', html: (b.first.action || ('<b>' + escHtml(gkey) + '</b>')) + (b.count > 1 ? ` <span class="tl-mile-n">× ${b.count}</span>` : '') });

    }

  });

  return { miles, quiet };

}

/* 渲染进 .tl-round · 与步骤列表共存 · CSS 按密度档切换显隐 · 零重渲 */

function _tlMilesRender(tl, animate, extra) {

  const old = tl.$round.querySelector(':scope > .tl-miles');

  if (old) old.remove();

  const built = _tlMilesBuild(tl);

  const miles = built.miles, quiet = built.quiet;

  const think = (extra && extra.think) || 0;
  const thinkChars = (extra && extra.thinkChars) || 0;
  const thinkEls = (extra && extra.thinkEls) || null;

  /* 空态①（v1 原型）：没有里程碑 → 轻量一行（收起计数 + 展开入口）· 无头部无卡片体 */

  if (!miles.length) {

    /* fold17 · 纯思考回复（一步工具都没跑）→ 不出「顺手处理了几步」空框 · 摘要行在上栏思考槽 */

    if (!quiet && !(tl.steps && tl.steps.length)) return null;

    const box = document.createElement('div');

    box.className = 'tl-miles tl-miles-quiet';

    const bits = [];

    if (quiet) bits.push(quiet + ' 次工具');

    /* wish-eeff6e5e 终轮+4 · 思考收进卡片：▸ 思考 N 段（点击展开原文）*/
    if (thinkEls && thinkEls.length) {
      const trow = document.createElement('div');
      trow.className = 'tl-mile tl-think-row';
      trow.innerHTML = '<span class="tl-mile-k">▸</span><span class="tl-mile-x">思考 <b>' + think + ' 段</b>' + (thinkChars ? ' · ' + (thinkChars > 999 ? (thinkChars / 1000).toFixed(1) + 'k' : thinkChars) + ' 字' : '') + '</span><span class="tl-think-hint">点击展开</span>';
      const tbox = document.createElement('div');
      tbox.className = 'tl-thinks';
      tbox.hidden = true;
      thinkEls.forEach((el) => { el.classList.remove('proc-think-hidden'); tbox.appendChild(el); });
      trow.onclick = () => {
        tbox.hidden = !tbox.hidden;
        const k = trow.querySelector('.tl-mile-k');
        if (k) k.textContent = tbox.hidden ? '▸' : '▾';
        const h = trow.querySelector('.tl-think-hint');
        if (h) h.textContent = tbox.hidden ? '点击展开' : '点击收起';
      };
      box.appendChild(trow);
      box.appendChild(tbox);
    }

    const q = document.createElement('div');

    q.className = 'tl-quiet';

    const sp = document.createElement('span');

    sp.textContent = bits.length ? ('另 ' + bits.join(' · ') + ' 已收起') : '顺手处理了几步';

    q.appendChild(sp);

    const more = document.createElement('span');

    more.className = 'tl-miles-more';

    more.textContent = '展开全部 ▾';

    more.onclick = () => _tlSetCollapsed(tl, false);

    q.appendChild(more);

    box.appendChild(q);

    tl.$round.appendChild(box);

    return box;

  }

  const box = document.createElement('div');

  box.className = 'tl-miles';

  const reduce = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

  if (animate && !reduce) box.classList.add('fx');

  miles.forEach((m, i) => {

    const row = document.createElement('div');

    row.className = 'tl-mile tl-' + m.lvl;

    if (box.classList.contains('fx')) row.style.animationDelay = (i * 40) + 'ms';

    row.innerHTML = '<span class="tl-mile-k">' + (m.lvl === 'fail' ? '✕' : '●') + '</span>'

      + '<span class="tl-mile-x">' + m.html + '</span>';

    box.appendChild(row);

  });

  const bits = [];

  if (quiet) bits.push(quiet + ' 次工具');

  /* wish-eeff6e5e 终轮+4 · 思考收进卡片：▸ 思考 N 段（点击展开原文）*/
  if (thinkEls && thinkEls.length) {
    const trow = document.createElement('div');
    trow.className = 'tl-mile tl-think-row';
    trow.innerHTML = '<span class="tl-mile-k">▸</span><span class="tl-mile-x">思考 <b>' + think + ' 段</b>' + (thinkChars ? ' · ' + (thinkChars > 999 ? (thinkChars / 1000).toFixed(1) + 'k' : thinkChars) + ' 字' : '') + '</span><span class="tl-think-hint">点击展开</span>';
    const tbox = document.createElement('div');
    tbox.className = 'tl-thinks';
    tbox.hidden = true;
    thinkEls.forEach((el) => { el.classList.remove('proc-think-hidden'); tbox.appendChild(el); });
    trow.onclick = () => {
      tbox.hidden = !tbox.hidden;
      const k = trow.querySelector('.tl-mile-k');
      if (k) k.textContent = tbox.hidden ? '▸' : '▾';
      const h = trow.querySelector('.tl-think-hint');
      if (h) h.textContent = tbox.hidden ? '点击展开' : '点击收起';
    };
    box.appendChild(trow);
    box.appendChild(tbox);
  }

  if (bits.length) {

    const q = document.createElement('div');

    q.className = 'tl-quiet';

    const sp = document.createElement('span');

    sp.textContent = '另 ' + bits.join(' · ') + ' 已收起';

    q.appendChild(sp);

    const more = document.createElement('span');

    more.className = 'tl-miles-more';

    more.textContent = '展开全部 ▾';

    more.onclick = () => _tlSetCollapsed(tl, false);

    q.appendChild(more);

    if (box.classList.contains('fx')) q.style.animationDelay = (miles.length * 40) + 'ms';

    box.appendChild(q);

  }

  tl.$round.appendChild(box);

  return box;

}



/* 读取/检索类 · head 人话统计单独归类（对齐 v1 原型空态①「读了 3 个文件 · 搜了 2 次」） */

const _TL_READ_TOOLS = new Set(['read_file', 'grep_files', 'glob_files', 'search_code', 'recall_memory', 'session_search', 'web_search', 'web_fetch', 'browser_fetch', 'pdf_read', 'look_at', 'list_apps', 'list_flows', 'list_scheduled_tasks', 'read_dashboard', 'inspect_office', 'client_handoff', 'manage_knowledge', 'worktree_status', 'service_list', 'outline_file', 'app_list_secrets', 'list_mods', 'list_dkpkg', 'list_market', 'list_shareable', 'inspect_market', 'mcp_list', 'mcp_describe_tool']);



function _tlHeadSummary(steps) {

  const edits = steps.filter(s => ['edit_file', 'write_file'].includes(s.name)).length;

  const checks = steps.filter(s => ['python_exec', 'verify_daemon_endpoints', 'lint_check', 'shell_exec'].includes(s.name)).length;

  const reads = steps.filter(s => _TL_READ_TOOLS.has(s.name)).length;

  const fails = steps.filter(s => s.ok === false).length;

  const parts = [];

  if (edits) parts.push(`<b>改了 ${edits} 个文件</b>`);

  if (checks) parts.push(`<b>跑了 ${checks} 次检查/命令</b>`);

  if (reads) parts.push(`读取/检索 ${reads} 次`);

  const others = steps.length - edits - checks - reads;

  if (others > 0) parts.push(`<b>处理 ${others} 件事务</b>`);

  return (parts.join('、') || '<b>工具时间线</b>') + (fails ? ` · <span class="tl-fail-text">${fails} 个失败</span>` : '');

}



function tlFinishRound(state) {

  const tl = state._tl; if (!tl) return;

  const n = tl.steps.length;

  if (!n && !(tl._histThinkN || 0)) { tl.$round.remove(); state._tl = null; return; }   /* fold17 · 纯思考无工具也留卡（▸ 思考 N 段）*/

  const fails = tl.steps.filter(s => s.ok === false).length;

  const totalS = Math.round((Date.now() - tl.startTs) / 1000);

  const $t = tl.$head.querySelector('.tl-round-title');

  if ($t) $t.innerHTML = _tlHeadSummary(tl.steps);

  const $s = tl.$head.querySelector('.tl-round-stats');

  if ($s) $s.textContent = `${n} 步 · ${tlHumanDur(totalS)}${fails ? ` · ${fails} 失败` : ''}`;

  tl.$round.classList.toggle('has-fail', fails > 0);

  /* wish-eeff6e5e · 一个回复一张卡：收拢时把本回复内的思考泡泡藏进卡片 · quiet 行计数 · 展开全部不恢复（内容在会话记录里） */

  /* fold23 · 思考不计这里 —— 它由 procThinkPush 从第一个字就长进卡（实时与回放同源）· 无搬运 */

  tl.$round.classList.remove('tl-growing');   /* 终轮+7 · 收拢即退出生长态（展开后全量展示·无限高无渐隐）*/

  const touched = tl.$round.dataset.processTouched === '1';

  /* wish-eeff6e5e · fold 档收拢：步骤区塌下 → 里程碑错峰长出（历史回放/用户手动摸过 → 直接终态） */

  if (!chatProcessExpanded()) {

    tl.$body.querySelectorAll('.tl-step.tl-out').forEach((el) => { el.classList.remove('tl-out'); });

    const animate = !touched && !state.noWindow;

    _procThinkSettle(tl);

    _tlMilesRender(tl, animate, {});

    /* 卡片移到本回复末尾（正文/图廊之后）· 对齐原型：过程卡收在回复底部 */

    if (state.$container && tl.$round.parentElement === state.$container) {

      state.$container.appendChild(tl.$round);

    }

    const reduce = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

    if (animate && !reduce) {

      const body = tl.$body;

      body.style.maxHeight = body.scrollHeight + 'px';

      body.style.overflow = 'hidden';

      requestAnimationFrame(() => {

        body.style.transition = 'max-height .42s cubic-bezier(.22,1,.36,1), opacity .3s';

        body.style.maxHeight = '0px';

        body.style.opacity = '0';

      });

      setTimeout(() => {

        _tlSetCollapsed(tl, true);

        body.style.cssText = '';

      }, 460);

      state._tl = null;

      return;

    }

  }

  if (!touched) {

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

    /* wish-eeff6e5e · 优先 path（文件类工具的人话提取靠它）· 对象/数组值 JSON 化防 [object Object] */

    const k = keys.includes('path') ? 'path' : keys[0];

    const raw = obj[k] == null ? '' : obj[k];

    const v = typeof raw === 'string' ? raw.slice(0, 60) : JSON.stringify(raw).slice(0, 60);

    return `${k}=${v}${keys.length > 1 ? ` · ${keys.length - 1}+ args` : ''}`;

  } catch { return String(argumentsStr).slice(0, 60); }

}



/* wish-eeff6e5e · 历史回放聚合：连续 assistant 段（中间只夹正文/思考，无 bro/sys 边界）共用一张卡 */

let _tlHistLive = null;   /* { tl, tailEl, $container } · 上一张历史卡与它渲完后容器末尾 */

function _tlHistBoundary(el) {

  return el.classList && el.classList.contains('msg')

    && (el.classList.contains('bro') || el.classList.contains('sys') || el.classList.contains('err'));

}



function renderToolTimeline(items, target) {

  /* wish-eeff6e5e · 空 items：本 turn 没工具调用，但可能有一段收尾思考要收编进本回复的卡
     （不收就会裸在对话栏 —— BRO 实测：卡里一截、卡外一截）*/

  if (!items || !items.length) {

    const c0 = target || _tlHost();

    const tl0 = (_tlHistLive && _tlHistLive.$container === c0 && _tlHistLive.tl
      && _tlHistLive.tl.$round && _tlHistLive.tl.$round.isConnected) ? _tlHistLive.tl : null;

    if (!tl0) return;

    _procThinkSettle(tl0);

    _tlSetCollapsed(tl0, !chatProcessExpanded());

    _tlHistLive.tailEl = c0.lastElementChild || _tlHistLive.tailEl;

    return;

  }

  const $c = target || _tlHost();

  let state = null, think = 0, thinkChars = 0; let thinkEls = [];

  /* 续卡判定：上张卡之后到容器末尾之间没有边界元素 → 同一回复 · 步骤接着长在同一张卡里 */

  if (_tlHistLive && _tlHistLive.tl && _tlHistLive.$container === $c

      && _tlHistLive.tailEl && _tlHistLive.tailEl.isConnected) {

    let el = _tlHistLive.tailEl.nextElementSibling, boundary = false;

    const hides = [];

    while (el) {

      if (_tlHistBoundary(el)) { boundary = true; break; }

      if (el.classList.contains('msg') && el.classList.contains('opus') && el.classList.contains('reasoning')) hides.push(el);

      el = el.nextElementSibling;

    }

    if (!boundary) {

      state = { $container: $c, _tl: _tlHistLive.tl, noWindow: true };

      /* wish-eeff6e5e 终轮+6 · thinkEls 改挂 tl 上跨组累积 · 否则续卡重渲时 old.remove 连上一组 thinkBox 里的思考 div 一起删（BRO 实测：有思考的卡展开是空的）*/
      if (!state._tl._histThinkEls) state._tl._histThinkEls = [];
      thinkEls = state._tl._histThinkEls;
      think = state._tl._histThinkN || 0;
      thinkChars = state._tl._histThinkChars || 0;

      hides.forEach((h) => {

        const hb = h.querySelector('.reasoning-body');

        if (hb) thinkChars += (hb.textContent || '').length;

        thinkEls.push(h);

        think++;

      });

      state._tl._histThinkN = think;

      state._tl._histThinkChars = thinkChars;

      /* 解开上一轮的收拢态 · 继续长 */

      const oldMiles = state._tl.$round.querySelector(':scope > .tl-miles');

      if (oldMiles) oldMiles.remove();

      state._tl.$round.classList.remove('collapsed', 'has-fail');

    }

  }

  if (!state) state = { $container: $c, _tl: null, noWindow: true };   /* noWindow: 历史回放不跑生长窗口 · 直接终态 */

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

  /* fold23 · 思考不再由这里负责 —— 它在 chat.js 渲染每个 turn 时就走 procThinkPush 直接长进卡。
     这里只汇总思考账（幂等重算），收拢交给 procHistSeal。 */

  if (state._tl) _procThinkSettle(state._tl);

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

    /* wish-eeff6e5e · fold 档：历史回放直接出里程碑终态（无动效）· quiet 行带上本组藏掉的思考数 */

    if (!chatProcessExpanded()) {

      tl.$body.querySelectorAll('.tl-step.tl-out').forEach((el) => { el.classList.remove('tl-out'); });

      /* fold23 · 思考由 procThinkPush 长进来 · 这里只刷新账与里程碑 */

      _procThinkSettle(tl);

      _tlMilesRender(tl, false, {});

    }

    _tlSetCollapsed(tl, !chatProcessExpanded());

    _tlHistLive = { tl, tailEl: $c.lastElementChild, $container: $c };

    state._tl = null;

    /* 卡片移到本回复末尾（正文之后）· 历史循环同步渲完后宏任务里做 · 幂等 */

    setTimeout(() => {

      if (!tl.$round.isConnected) return;

      let el = tl.$round.nextElementSibling, last = tl.$round;

      while (el && !_tlHistBoundary(el)) { last = el; el = el.nextElementSibling; }

      if (last !== tl.$round) last.after(tl.$round);

    }, 0);

  }

}



/* ═══ wish-eeff6e5e 终轮+4 · 思考泡泡从 chat.js 拆入（防 chat.js 膨胀）

   appendReasoningDelta / finalizeStreamingReasoning / renderReasoningBubble 三函数原样迁入 ·

   依赖 scrollToBottom/isNearBottom/$msgs 均为运行时全局（chat.js 后加载）· 零构建作用域不受影响 ═══ */



// 卷三十七 · 流式拼接 · 当前正在 stream 的 DOM 引用

// wish-3fef4bc7 · 改为 per-state · 没有 state 参数 = 不工作 (直接 return)

// state.currentStreamingReasoning / state.currentStreamingAssistant 持有 DOM 引用

function appendReasoningDelta(state, textPiece) {

  if (!textPiece || !state) return;

  if (!state.currentStreamingReasoning) {

    const expand = chatProcessExpanded();

    /* ── wish-eeff6e5e fold23 · fold 档：思考走【统一渲染出口】──
       从第一个字就长在卡里（段默认收在段列表 · 只露汇总行「▸ 思考中…」）·
       不再先建“对话栏里的独立泡”再往卡里搬。与历史回放完全同源。 */
    if (!expand) {

      const seg = procThinkPush(state, '', { streaming: true });

      const rc = { div: seg.div, body: seg.body, _pending: '', _raf: 0, _seg: seg };

      state.currentStreamingReasoning = rc;

      rc._pending += textPiece;

      if (!rc._raf) {

        rc._raf = requestAnimationFrame(() => {

          rc._raf = 0;

          if (!rc._pending) return;

          rc.body.appendChild(document.createTextNode(rc._pending));

          rc._pending = '';

        });

      }

      return;

    }

    /* wish-eeff6e5e fold17 · fold 档：思考从第一个字就长在卡里（上栏）
       预建卡 → 呼吸点从第一个思考字亮起 · 此后这个 div 的父节点不变（R1 不搬家）*/
    let host = state.$container;

    if (!expand) {

      const tl0 = _tlEnsureRound(state);

      tl0.$live.classList.add('has-think');

      if (!tl0._histThinkEls) tl0._histThinkEls = [];

      tl0._histThinkN = (tl0._histThinkN || 0) + 1;

      _tlLiveRowText(tl0, true);

      host = tl0.$liveBox;

    }

    const div = document.createElement('div');

    div.className = 'msg opus reasoning streaming';

    if (expand) div.dataset.procTurn = '1';

    else div.dataset.procLive = '1';   /* 在槽里 · 不参与收拢扫描（防与兜底思考双计）*/

    const header = document.createElement('div');

    header.className = 'reasoning-header';

    header.innerHTML = `<span class="reasoning-icon"><i class="ri-brain-fill"></i></span> <span class="reasoning-label">思考中</span> <span class="reasoning-toggle">${expand ? '收起 ▴' : '展开 ▾'}</span>`;

    header.style.cursor = 'pointer';

    div.appendChild(header);

    const body = document.createElement('div');

    body.className = 'reasoning-body';

    body.hidden = !expand;   /* fold 档：思考收着 —— 只留汇总行「▸ 思考中…」（BRO：别铺屏）；expand 档摊开 */

    div.appendChild(body);

    header.addEventListener('click', () => {

      const showing = !body.hidden;

      body.hidden = showing;

      div.classList.toggle('folded', showing);

      div.dataset.processTouched = '1';

      const toggle = header.querySelector('.reasoning-toggle');

      if (toggle) toggle.textContent = showing ? '展开 ▾' : '收起 ▴';

      if (!showing) {

        body.scrollTop = body.scrollHeight;

        scrollToBottom(state.$container, { force: false });

      }

    });

    if (host) {

      if (!expand && state._tl) {

        /* 一段一行 · 这段默认摊开（正在写）· 建时即绑（R2）*/

        const segHead = _tlSegHead(state._tl._histThinkN, 0, false);   /* 流式中也收着 · 点汇总行才见段列表 */

        _tlSegBind(segHead, div);

        host.appendChild(segHead);

      }

      host.appendChild(div);

    }

    scrollToBottom(state.$container, { force: false });

    state.currentStreamingReasoning = { div, body, _pending: '', _raf: 0 };

  }

  // 0.8.3 性能修复 · DeepSeek reasoning 逐 chunk 推 (每秒几十个) ·

  // 老代码每 chunk appendChild + isNearBottom 读布局 ×2 + 两次滚动 → layout thrashing ·

  // 长思考 + 大 DOM 时主线程吃满 → 滚动条拖不动 (BRO 实测反馈)。

  // 修复: 累积到 _pending · RAF 合并每帧最多一次 append + 一次滚动判断 (肉眼无感·主线程降一个数量级)

  const r = state.currentStreamingReasoning;

  r._pending += textPiece;

  if (!r._raf) {

    r._raf = requestAnimationFrame(() => {

      r._raf = 0;

      if (!r._pending) return;

      r.body.appendChild(document.createTextNode(r._pending));

      r._pending = '';

      if (r.body.hidden) return;

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

  // fold 档完成后收进卡片 · expand 档保持摊开 · 这轮手点过的按手点的来

  const body = r.body;

  const header = r.div.querySelector('.reasoning-header');

  if (body && header) {

    const label = header.querySelector('.reasoning-label');

    if (label) label.textContent = `思考完成 · ${body.textContent.length} 字`;

    if (r.div.dataset.processTouched !== '1') {

      const expand = chatProcessExpanded();

      /* R3 · 原地收：长在卡里的思考只藏 body + 摘要行定格 · 不搬父节点
         （fold14/+9 的「展开空 / 点不动」就是在这一步搬出来的）*/
      if (!expand && r._seg) {

        /* fold23 · 统一出口：这一段写完 → 原地收成一条目（不搬父节点）*/

        procThinkSeal(r._seg);

      } else if (!expand && !!(r.div.parentElement && r.div.parentElement.classList
        && r.div.parentElement.classList.contains('tl-thinks'))) {

        /* 这段写完了 → 原地收成一行条目（BRO：一个思考一段 · 展开才看内容）
           段头就在它前面（同父）· 只改 hidden + 文案 —— 不搬家 */

        const tl0 = state._tl;

        const chars = (body.textContent || '').length;

        if (tl0) tl0._histThinkChars = (tl0._histThinkChars || 0) + chars;

        const segHead = r.div.previousElementSibling;

        if (segHead && segHead.classList.contains('tl-seg-head')) {

          _tlSegSettle(segHead, chars);

          segHead.dataset.open = '0';

          const k = segHead.querySelector('.tl-seg-k');

          if (k) k.textContent = '▸';

        }

        r.div.hidden = true;

      } else {

        body.hidden = !expand;

        r.div.classList.toggle('folded', !expand);

        const toggle = header.querySelector('.reasoning-toggle');

        if (toggle) toggle.textContent = expand ? '收起 ▴' : '展开 ▾';

      }

    }

  }

  state.currentStreamingReasoning = null;
  /* fold17 · 不再有「流完搬进卡片」这一步：思考从第一个字就长在卡里，收拢只收 body */

}



// 卷三十六 · DeepSeek thinking mode · 渲染一条 reasoning 气泡

// fold 档默认折起 · expand 档默认摊开 · 点开/折上当次优先

function renderReasoningBubble(text, options = {}, target) {

  if (!text) return null;

  const collapsed = options.collapsed != null ? !!options.collapsed : !chatProcessExpanded();

  const div = document.createElement('div');

  div.className = 'msg opus reasoning' + (collapsed ? ' folded' : '');

  if (!options.historical) div.dataset.procTurn = '1';   // wish-eeff6e5e · 回复进行中的思考打标 · 收拢时藏

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

    div.classList.toggle('folded', showing);

    div.dataset.processTouched = '1';

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



/* wish-eeff6e5e fold17 · _tlLiveThinkFlush 已删 —— 思考不再搬家（第一个字起就长在卡的 .tl-live 里）*/


/* wish-eeff6e5e · 密度钩子初始化（applyChatProcessDensity 只在切档时调 · 首启也要挂上） */

try { document.documentElement.dataset.proc = chatProcessExpanded() ? 'expand' : 'fold'; } catch (e) {}

