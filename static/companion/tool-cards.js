/* 陪伴房间 · 工具卡人话层
   跟工作台 chat.js 的 TL_CATS / TL_HUMAN 同一套名字和颜色 · 不加载 chat.js */
'use strict';

const TL_T2C = {
  read_file: 'file', write_file: 'file', edit_file: 'file', glob_files: 'file', grep_files: 'file',
  outline_file: 'file', search_code: 'file', lint_check: 'file', read_scenario: 'file', pdf_read: 'file', read_dashboard: 'file',
  shell_exec: 'exec', python_exec: 'exec', service_start: 'exec', service_stop: 'exec', service_status: 'exec', service_list: 'exec',
  open_app: 'exec', worktree_status: 'exec', verify_daemon_endpoints: 'exec', request_restart: 'exec', update_core: 'exec',
  web_search: 'web', web_fetch: 'web', browser_fetch: 'web', browser_act: 'web', web_search_image: 'web', verify_claim: 'web',
  update_owner_note: 'memory', recall_memory: 'memory', session_search: 'memory', update_self_evolution: 'memory',
  summarize_session: 'memory', manage_knowledge: 'memory', manage_client: 'memory', extract_playbook: 'memory', track_task: 'memory',
  create_app: 'workshop', update_app: 'workshop', list_apps: 'workshop', run_app: 'workshop', app_versions: 'workshop',
  manage_app_asset: 'workshop', dispatch_subagent: 'workshop', create_workflow: 'workshop', list_flows: 'workshop',
  run_flow: 'workshop',
  manage_info_source: 'radar', mine_opportunities: 'radar', analyze_feasibility: 'radar', record_outcome: 'radar',
  auto_pipeline: 'radar', toggle_favorite: 'radar',
  generate_report: 'report', generate_presentation: 'report', generate_image: 'report', draft_studio: 'report',
  replan: 'flow', wish_add: 'flow', wish_update: 'flow', intent_to_wish: 'flow',
  wechat_send: 'comm', read_clipboard: 'comm', write_clipboard: 'comm',
  take_screenshot: 'sense', look_at: 'sense', set_emotion: 'sense', set_model: 'sense',
  create_scheduled_task: 'sched', list_scheduled_tasks: 'sched', update_scheduled_task: 'sched', delete_scheduled_task: 'sched',
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
function tlFileName(s) {
  const m = String(s || '').match(/[\w.\-一-龥]+\.\w+/);
  return m ? m[0] : String(s || '').slice(0, 40);
}
function _escTl(s) {
  return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

const TL_HUMAN = {
  read_file: c => ({ action: `读了 <b>${_escTl(tlFileName(c.s))}</b>` }),
  write_file: c => ({ action: `写入文件 <b>${_escTl(tlFileName(c.s))}</b>` }),
  edit_file: c => ({ action: `修改代码文件 <b>${_escTl(tlFileName(c.s))}</b>` }),
  grep_files: c => ({ action: `在代码里搜索 <b>${_escTl(String(c.s).replace(/^pattern=/, '').split(' · ')[0].slice(0, 40))}</b>` }),
  glob_files: c => ({ action: `按文件名找 <b>${_escTl(tlFileName(c.s))}</b>` }),
  shell_exec: c => ({ action: /git commit/.test(c.s) ? '存档代码' : `跑了命令 <b>${_escTl(String(c.s).slice(0, 36))}</b>` }),
  python_exec: () => ({ action: '跑一段 Python 验证' }),
  web_search: c => ({ action: `上网搜索 <b>${_escTl(String(c.s).replace(/"/g, '').slice(0, 36))}</b>` }),
  web_fetch: () => ({ action: '抓取网页正文' }),
  recall_memory: () => ({ action: '翻长期记忆' }),
  update_owner_note: () => ({ action: '记一笔到你的画像档案' }),
  generate_report: () => ({ action: '生成了一份报告文档' }),
  generate_image: () => ({ action: '画了一张图' }),
  mine_opportunities: () => ({ action: '在挖掘金机会' }),
  analyze_feasibility: () => ({ action: '在做可行性分析' }),
  dispatch_subagent: () => ({ action: '放出一只分身' }),
  replan: () => ({ action: '请顾问出方案' }),
  take_screenshot: () => ({ action: '看了一眼你的屏幕' }),
  look_at: () => ({ action: '看了一张图片' }),
  wish_add: () => ({ action: '往心愿单记了一条' }),
  wish_update: () => ({ action: '更新心愿单状态' }),
};

function tlHumanize(tool, summary) {
  const c = { s: summary || '' };
  const f = TL_HUMAN[tool];
  if (f) { try { return f(c); } catch (e) {} }
  const cat = tlCatOf(tool);
  const s = String(summary || '').slice(0, 40);
  return { action: s ? `${cat.name} · ${_escTl(s)}` : cat.name };
}

function tlStepHtml(name, summary) {
  const cat = tlCatOf(name);
  const h = tlHumanize(name, summary);
  return `<div class="tl-step" data-tool="${_escTl(name)}">`
    + `<div class="tl-step-dot" style="--tlc:${cat.color}"><i class="${cat.icon}"></i></div>`
    + `<div class="tl-step-main"><div class="tl-step-head">`
    + `<span class="tl-step-cat" style="color:${cat.color}">${cat.name}</span>`
    + `<span class="tl-step-dur"></span></div>`
    + `<div class="tl-step-action">${h.action}</div>`
    + `<div class="tl-step-result tl-pending"><i class="ri-loader-4-line tl-spin"></i> 进行中…</div>`
    + `</div></div>`;
}

function tlSayHtml(name, summary) {
  const cat = tlCatOf(name);
  const h = tlHumanize(name, summary);
  return `<div class="say-tool" style="--tlc:${cat.color}">`
    + `<i class="${cat.icon}"></i>`
    + `<div><b style="color:${cat.color}">${cat.name}</b><span>${h.action}</span></div></div>`;
}

window.tlCatOf = tlCatOf;
window.tlHumanize = tlHumanize;
window.tlStepHtml = tlStepHtml;
window.tlSayHtml = tlSayHtml;
