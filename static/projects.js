/* static/projects.js · 外部项目管理（「我的项目」）· 独立模块
 * ────────────────────────────────────────────────────────────────────
 * 2026-09-20 · wish-acc37841
 *   第一刀：纯前端架子（演示数据）→ commit 25c629b9 / 7ae90742
 *   第二刀：接真后端（data/projects.json + 会话 project_id 外键）← 本文件现在
 *
 * 为什么是独立文件 —— BRO 2026-09-20 原话：
 *   「最好这个东西不要挤在 chat.js 里面，如果已经在，正好把他拆出去。chat.js 太大了」
 *
 * 怎么做到 chat.js / chat.css 零改动（全是复用官方现成接口）：
 *   导航入口 → Daemonkey.addDomain（chat.js:6192 装修接口 · 内部自动 renderNav）
 *   中栏渲染 → 同一个接口的 render（loadDashboard chat.js:8051 自动委派）
 *   引导卡点击 → data-view 属性（不碰 chat.js 的 data-template 通道）
 *   会话外键 → 订阅 sse:event 的 hello（真 sid 落地那一刻）→ POST /sessions/{sid}/meta
 *   认证     → 复用 _flowRunsToken()（全站同一把 opus_ui_token）
 *   按钮样式 → .btn-primary / .btn-ghost（铁律 10）· 图标 Remix Icon（铁律 10）
 *   样式     → 本模块自带注入（.pj- 前缀）· 不碰 chat.css
 *
 * 为什么不在 newConversation() 里挂 project_id：
 *   那时 sessionId 还是个临时 cid（chat.js:3837 `_allocCid()`），真 sid 要等第一条
 *   消息发出、SSE `hello` 事件回来才换（chat.js:4994 commitSessionId）。所以挂在
 *   hello 那一刻 —— 早挂会往一个不存在的 sid 写 meta。
 *
 * 还没做（第三刀）：拉系统原生目录选择器（现在手输路径）· 交接条生成 · 专注版抽屉
 * ────────────────────────────────────────────────────────────────────
 */
(function () {
  'use strict';

  var API = '/api/projects';
  var state = { items: [], err: '', loaded: false, busy: false };
  // wish-8f9e4f05 · 旧的「pendingPid + TTL + SSE 判据」整套已拆 —— 那套靠猜时序，
  //   打字慢一点就过期（实测：3 个项目 chat_count 全 0）。现在项目 id 随首轮请求直接带走，
  //   见下面的 pjPendingId()（就在 newChatFor 旁边）。
  var _pjFromNewChatFor = false;   // newChatFor 自己调 newConversation 的那一次 · override 别清 pending

  /* ══════════ 样式（自带 · 不碰 chat.css） ══════════ */
  var STYLE_ID = 'pj-style';
  function injectStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = [
      '.pj-wrap{font-size:13px}',
      '.pj-head{display:flex;align-items:center;gap:12px;margin-bottom:14px;flex-wrap:wrap}',
      '.pj-title{font-size:15.5px;font-weight:600;display:flex;align-items:center;gap:8px}',
      '.pj-title i{color:var(--opus)}',
      '.pj-sub{font-size:11.5px;color:var(--dim2);margin-top:2px;font-family:Consolas,ui-monospace,monospace}',
      '.pj-demo{margin-left:auto;font-size:10.5px;color:var(--dim2);border:1px dashed var(--border);',
      '  padding:3px 9px;border-radius:8px;white-space:nowrap}',
      '.pj-proj{margin-bottom:2px}',
      '.pj-proj.dim{opacity:.55}',
      '.pj-row{display:flex;align-items:center;gap:8px;padding:8px;border-radius:8px;cursor:pointer}',
      '.pj-row:hover{background:var(--bg3)}',
      '.pj-caret{color:var(--dim2);font-size:15px;width:16px;display:flex;justify-content:center;flex:none}',
      '.pj-caret:hover{color:var(--opus)}',
      '.pj-fi{color:var(--sys);font-size:14px;flex:none}',
      '.pj-fi.gone{color:var(--red);opacity:.7}',
      '.pj-name{color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
      '.pj-when{margin-left:auto;color:var(--dim2);font-size:10.5px;white-space:nowrap}',
      '.pj-acts{display:flex;gap:6px;opacity:.3;transition:opacity .15s;flex:none}',
      '.pj-row:hover .pj-acts{opacity:1}',
      '.pj-kids{margin:2px 0 9px 30px;border-left:1px solid var(--border);padding-left:10px}',
      '.pj-hand{display:flex;align-items:flex-start;gap:7px;font-size:11.5px;line-height:1.6;',
      '  color:var(--sys);padding:7px 9px;background:var(--bg3);border-radius:7px;margin-bottom:6px}',
      '.pj-hand b{color:var(--sys);font-weight:500}',
      '.pj-hand i{margin-top:2px;flex:none}',
      '.pj-meta{display:flex;align-items:center;gap:10px;font-size:11px;color:var(--dim2);padding:4px 8px}',
      '.pj-meta code{background:var(--bg);padding:1px 6px;border-radius:5px;color:var(--opus);',
      '  font-size:11px;font-family:Consolas,ui-monospace,monospace}',
      '.pj-sesslist{margin-top:4px;display:flex;flex-direction:column;gap:2px}',
      '.pj-sess{display:flex;align-items:center;gap:7px;padding:5px 8px;border-radius:6px;',
      '  cursor:pointer;font-size:11.5px;color:var(--sys);transition:background .12s}',
      '.pj-sess:hover{background:var(--bg3);color:var(--text)}',
      '.pj-sess i{color:var(--dim2);font-size:12px;flex:none}',
      '.pj-sess-t{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
      '.pj-sess-w{margin-left:auto;color:var(--dim2);font-size:10px;flex:none}',
      '.pj-live{display:inline-flex;align-items:center;gap:3px;font-size:10px;color:#68d391;flex:none}',
      '.pj-live::before{content:"";width:6px;height:6px;border-radius:50%;background:#68d391;',
      '  box-shadow:0 0 6px rgba(104,211,145,.55)}',
      '.pj-tag{font-size:10px;padding:1px 7px;border-radius:20px;border:1px solid var(--border);',
      '  color:var(--dim2);flex:none}',
      '.pj-tag.bad{border-color:#6b3030;color:#e08585}',
      '.pj-mini{font-size:11.5px;padding:5px 10px;cursor:pointer;white-space:nowrap}',
      // 2026-09-21 · 窄容器适配（BRO 报「点开后 CSS 吞掉说明」· 专注版右栏 ~360px）：
      //   产物库在同样容器里正常 —— 它的卡片为窄设计过。这里补最小集：
      //   ① 内容自己能滚（detail-pane 是 overflow:hidden · 不滚就被硬切）② 长句可断行。
      '.pj-wrap{display:flex;flex-direction:column;min-height:0}',
      'body.compact .cl-slot .pj-wrap{height:100%;overflow-y:auto;overflow-x:hidden}',
      '.pj-empty{font-size:12px;color:var(--dim2);margin:0;line-height:1.75;word-break:break-word}',
      '.pj-err{font-size:11.5px;color:#e08585;margin-right:auto}',
      /* 会话行里的项目药丸（session-list.js 用同一个类名） */
      '.sp-project{display:inline-flex;align-items:center;gap:4px;font-size:10px;padding:1px 7px;',
      '  border-radius:20px;background:#2a2340;border:1px solid #4a3a6e;color:var(--opus);',
      '  cursor:pointer;transition:background .15s,border-color .15s;',
      '  margin-left:5px;max-width:120px;overflow:hidden;text-overflow:ellipsis;',
      '  white-space:nowrap;vertical-align:1px}',
      '.sp-project:hover{background:#35295a;border-color:#6b52a0}',
      // ⚠ 2026-09-21 修：上面两行（margin-left / white-space）原来悬在 .sp-project 规则外面 ——
      //   悬空声明 + 一个孤零零的 } 把紧随其后的 .pj-mask 整条规则吞了 → 详情浮层没了遮罩、
      //   掉进文档流、还把对话栏顶上去（BRO 现场报的「焊死」）。
      //   教训同 b55916b2（注释未闭合吞掉 .tp-gal）：CSS 串里断一条就赔一条，改完必须拉开距离看交界处。
      /* 挂载浮层 → 2026-09-21 重写（wish-178a8517）：骨架改为复用全站在用的 .kb-modal*（产物库/客户/沉淀位/文档预览同款），
         这里只补项目详情专属类。⚠ 全部走主题变量 —— 老版一水儿硬编码 #2a2340/#4a3a6e，主题一换就不跟（BRO 点名的主因）。 */
      '.pj-ico{width:30px;height:30px;border-radius:9px;flex:none;display:flex;align-items:center;',
      '  justify-content:center;background:var(--bg3);border:1px solid var(--border);color:var(--opus);font-size:15px}',
      '.pj-badge{font-size:11px;padding:1px 9px;border-radius:20px;flex:none;background:var(--bg3);',
      '  border:1px solid var(--border);color:var(--opus);white-space:nowrap}',
      '.pj-badge.ver{color:var(--bro);border-color:var(--bro)}',
      '.pj-st{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12.5px;color:var(--dim)}',
      '.pj-st b{color:var(--text);font-weight:500}',
      '.pj-st .dot{width:7px;height:7px;border-radius:50%;background:var(--bro);flex:none}',
      '.pj-st .dot.warn{background:var(--sys)}',
      '.pj-st .dot.bad{background:var(--red)}',
      '.pj-st .sep{color:var(--dim2)}',
      '.pj-blk{margin-top:18px}',
      '.pj-blk-t{font-size:11.5px;color:var(--dim2);letter-spacing:.5px;display:flex;align-items:center;',
      '  gap:6px;margin-bottom:7px}',
      '.pj-blk-t::after{content:"";flex:1;height:1px;background:var(--border)}',
      '.pj-prog{height:6px;border-radius:4px;background:var(--bg3);overflow:hidden;margin-bottom:9px}',
      '.pj-prog i{display:block;height:100%;background:var(--opus);border-radius:4px}',
      '.pj-ms{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:5px;font-size:12.5px}',
      '.pj-ms li{display:flex;align-items:center;gap:8px;color:var(--dim)}',
      '.pj-ms li::before{content:"○";color:var(--dim2);font-size:11px}',
      '.pj-ms li.done{color:var(--text)}',
      '.pj-ms li.done::before{content:"●";color:var(--bro)}',
      '.pj-hand{display:flex;align-items:flex-start;gap:8px;font-size:12.5px;line-height:1.7;',
      '  color:var(--dim);padding:10px 13px;background:var(--bg3);border-left:2px solid var(--opus);',
      '  border-radius:0 9px 9px 0}',
      '.pj-hand b{color:var(--sys);font-weight:500}',
      '.pj-hand i{color:var(--opus);margin-top:2px;flex:none}',
      '.pj-sess{display:flex;align-items:center;gap:9px;padding:7px 10px;border-radius:9px;',
      '  cursor:pointer;font-size:13px;color:var(--text);border:1px solid transparent}',
      '.pj-sess:hover{background:var(--bg3);border-color:var(--border)}',
      '.pj-sess i{color:var(--dim2);font-size:13px;flex:none}',
      '.pj-sess .t{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
      '.pj-sess .w{margin-left:auto;font-size:11px;color:var(--dim2);flex:none}',
      '.pj-sess .go{color:var(--dim2);font-size:11px;flex:none}',
      '.pj-sess:hover .go{color:var(--opus)}',
      '.pj-prof{display:flex;align-items:center;gap:10px;flex-wrap:wrap}',
      '.pj-prof select{background:var(--bg3);color:var(--text);border:1px solid var(--border);',
      '  border-radius:8px;padding:5px 10px;font-size:12.5px;font-family:inherit;cursor:pointer}',
      '.pj-prof .hint{font-size:11.5px;color:var(--dim2)}',
      '.pj-foot{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:12px 18px;',
      '  border-top:1px solid var(--border);background:var(--bg3)}',
      '.pj-foot .sp{flex:1}',
      '.pj-hint code{background:var(--bg);padding:1px 6px;border-radius:5px;',
      '  font-family:Consolas,ui-monospace,monospace;font-size:11.5px}',
      '.pj-input{width:100%;box-sizing:border-box;background:var(--bg);border:1px solid var(--border);',
      '  border-radius:9px;padding:10px 12px;color:var(--text);font-size:12.8px;outline:none;',
      '  font-family:Consolas,ui-monospace,monospace}',
      '.pj-input:focus{border-color:var(--opus)}',
      '.pj-hint{font-size:10.5px;color:var(--dim2);margin-top:8px;line-height:1.7}',
      '.pj-toast{position:fixed;left:50%;bottom:34px;transform:translate(-50%,14px);opacity:0;',
      '  background:#2a2340;border:1px solid #4a3a6e;color:var(--text);font-size:12.5px;',
      '  padding:9px 16px;border-radius:10px;transition:.2s;pointer-events:none;z-index:70}',
      '.pj-toast.on{opacity:1;transform:translate(-50%,0)}',
      /* 引导卡上那一行「这个对话做的是 X」 */
      '.pj-onb-line{margin-top:11px;font-size:12px;color:var(--text);display:inline-flex;',
      '  align-items:center;gap:6px;padding:5px 13px;border-radius:20px;background:#2a2340;',
      '  border:1px solid #4a3a6e;max-width:100%}',
      '.pj-onb-line i{color:var(--opus)}',
      '.pj-onb-line b{color:var(--opus);font-weight:600}',
      '.pj-onb-path{color:var(--dim2);font-size:10.5px;',
      '  font-family:Consolas,ui-monospace,monospace;overflow:hidden;',
      '  text-overflow:ellipsis;white-space:nowrap}'
    ].join('\n');
    document.head.appendChild(s);
  }

  /* ══════════ 小工具 ══════════ */
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function tip(msg) {
    var el = document.getElementById('pjToast');
    if (!el) { el = document.createElement('div'); el.id = 'pjToast'; el.className = 'pj-toast'; document.body.appendChild(el); }
    el.textContent = msg;
    el.classList.add('on');
    clearTimeout(el._t);
    el._t = setTimeout(function () { el.classList.remove('on'); }, 2600);
  }
  // 项目默认档（存中文名）→ 档位 id —— 开新对话时预设进选档卡。
  // ⚠ 档位表（data/cognition/tool_profiles.json）加档时，这里要跟着加一行。
  var PROFILE_ID = {
    '闲聊': 'chat', '标准': 'standard', '工作': 'work', '编程': 'code',
    '3D 建模': 'dev3d', '生图': 'image', '写作': 'writing'
  };

  /* 当前这场是真 sid 还是空 —— chat.js 的 sessionId 是 let（从外面读不到），
     但 commitSessionId 会把它写进 localStorage，就从那儿读。 */
  function curSid() {
    try { return localStorage.getItem('opus_ui_session') || ''; } catch (e) { return ''; }
  }

  function ago(iso) {
    if (!iso) return '';
    var t = new Date(iso).getTime();
    if (isNaN(t)) return '';
    var d = Date.now() - t;
    if (d < 60000) return '刚刚';
    if (d < 3600000) return Math.floor(d / 60000) + ' 分钟前';
    if (d < 86400000) return Math.floor(d / 3600000) + ' 小时前';
    if (d < 172800000) return '昨天';
    if (d < 2592000000) return Math.floor(d / 86400000) + ' 天前';
    var dt = new Date(iso);
    return (dt.getMonth() + 1) + '/' + dt.getDate();
  }

  /* 2026-09-21 · 只在自己的坑还在时才重渲染。
     两个场景都要放行：
       ① 普通视图：Daemonkey.currentView() === 'projects'；
       ② 专注版右栏：域是绕过 switchView 直接 loadDashboard('projects') 塞进来的，
          currentView 不更新 → 不能只看它，还得认「#detailPane 里还是 .pj-wrap」这个事实。
     晚到的 render 只在【坑已被别的域重写】时才会造成覆盖 —— 用坑的在场与否当判据，
     比问「当前视图叫什么」更本质。 */
  function pjViewNow() {
    try {
      if (window.Daemonkey && typeof Daemonkey.currentView === 'function'
          && Daemonkey.currentView() === 'projects') return true;
      var pane = window._pjPane;
      return !!(pane && pane.querySelector && pane.querySelector('.pj-wrap'));
    } catch (e) { return false; }
  }

  /* ══════════ API（复用全站同一把 UI token） ══════════ */
  async function pjApi(method, path, body) {
    var tk = (typeof _flowRunsToken === 'function') ? _flowRunsToken() : '';
    if (!tk) return { ok: false, error: '拿不到 UI token（页面还没热起来？）' };
    var opt = { method: method, headers: { 'Authorization': 'Bearer ' + tk } };
    if (body) {
      opt.headers['Content-Type'] = 'application/json';
      opt.body = JSON.stringify(body);
    }
    try {
      var r = await fetch(path, opt);
      var d = null;
      try { d = await r.json(); } catch (e) { /* 非 JSON（比如 500 的 HTML） */ }
      if (!r.ok) return { ok: false, error: (d && d.detail) || ('HTTP ' + r.status) };
      return d || { ok: true };
    } catch (e) {
      return { ok: false, error: String(e && e.message || e) };
    }
  }

  async function load() {
    state.busy = true;
    var d = await pjApi('GET', API);
    if (!d || d.ok === false) {
      state.err = (d && d.error) || '拉列表失败';
      state.items = [];
    } else {
      state.items = d.items || [];
      state.err = '';
    }
    state.loaded = true;
    state.busy = false;
    if (window._pjPane && pjViewNow()) render(window._pjPane);
  }

  /* ══════════ 渲染 ══════════ */
  function rowHtml(p, i) {
    var op = !!p.open;
    var alive = p.path_exists !== false;
    var carets = op ? 'ri-arrow-down-s-line' : 'ri-arrow-right-s-line';
    var fold = 'pj-proj' + (p.archived_at ? ' pj-proj dim' : '');
    var tags = '';
    if (p.archived_at) tags += '<span class="pj-tag">归档</span>';
    if (!alive) tags += '<span class="pj-tag bad" title="磁盘上找不到这个目录了">目录不在了</span>';
    if (p.profile) tags += '<span class="pj-tag" title="这个项目的默认档位 · 开新对话时自动选中">' + esc(p.profile) + '</span>';

    var kids = '';
    if (op) {
      var inner = '';
      if (p.handoff) {
        inner += '<div class="pj-hand"><i class="ri-corner-down-right-line"></i><span>'
               + esc(p.handoff) + '</span></div>';
      } else {
        inner += '<div class="pj-meta"><i class="ri-information-line"></i>还没有交接条'
               + '（点「开新对话」会从上一场的任务账本里攒一句「上次停在哪 / 下一步」）</div>';
      }
      inner += '<div class="pj-meta"><i class="ri-folder-open-line"></i><code>' + esc(p.path) + '</code></div>';
      if (p.chat_count) {
        if (p.sessions === undefined) {
          inner += '<div class="pj-meta"><i class="ri-loader-4-line spin"></i>正在拉这个项目下的对话…</div>';
        } else if (!p.sessions.length) {
          inner += '<div class="pj-meta"><i class="ri-chat-3-line"></i>标着 ' + p.chat_count
                 + ' 条，但一条都查不到（可能刚被删了）</div>';
        } else {
          inner += '<div class="pj-sesslist">' + p.sessions.map(function (s) {
            return '<div class="pj-sess" data-pjsess="' + esc(s.session_id) + '" title="点一下切到这场对话">'
                 + '<i class="ri-chat-3-line"></i>'
                 + '<span class="pj-sess-t">' + esc(s.label || s.session_id) + '</span>'
                 + '<span class="pj-sess-w">' + esc(ago(s.mtime)) + ' · ' + (s.turns || 0) + ' 楼</span>'
                 + '</div>';
          }).join('') + '</div>';
        }
      } else {
        inner += '<div class="pj-meta"><i class="ri-chat-3-line"></i>还没有对话 · 点上面的「开新对话」就是第一场</div>';
      }
      kids = '<div class="pj-kids">' + inner + '</div>';
    }

    return '<div class="' + fold + '">'
      + '<div class="pj-row" data-pjrow="' + esc(p.id) + '">'
      +   '<span class="pj-caret" data-pjtoggle="' + esc(p.id) + '"><i class="' + carets + '"></i></span>'
      +   '<i class="ri-folder-3' + (p.archived_at ? '' : '-fill') + ' pj-fi' + (alive ? '' : ' gone') + '"></i>'
      +   '<span class="pj-name">' + esc(p.name || p.id) + '</span>'
      +   (p.chat_count ? '<span class="pj-live" title="这个项目下有 ' + p.chat_count + ' 条对话">' + p.chat_count + '</span>' : '')
      +   tags
      +   '<span class="pj-when">' + esc(ago(p.last_used_at || p.created_at)) + '</span>'
      +   '<span class="pj-acts">'
      +     '<button class="btn-ghost pj-mini" data-pjnew="' + esc(p.id) + '">开新对话</button>'
      +     '<button class="btn-ghost pj-mini" data-pjsheet="' + esc(p.id) + '">详情</button>'
      +     '<button class="btn-ghost pj-mini" data-pjunmount="' + esc(p.id) + '">移出项目</button>'
      +   '</span>'
      + '</div>' + kids + '</div>';
  }

  function render(pane) {
    injectStyle();
    window._pjPane = pane;

    var body;
    if (!state.loaded && !state.busy) { load(); }
    if (!state.loaded) {
      body = '<p class="pj-empty">正在拉项目列表…</p>';
    } else if (state.err) {
      body = '<p class="pj-empty">拉列表失败：' + esc(state.err)
           + '<br><span style="color:var(--dim2)">（点上面的「添加一个新项目」重试，或看 daemon 日志）</span></p>';
    } else if (!state.items.length) {
      body = '<p class="pj-empty">还没有挂任何项目。<br>'
           + '「添加一个新项目」把你要开发的目录挂上来 —— 以后在它里面开的对话都算这个项目的，'
           + '新对话会自动带上它的交接条和默认档位。</p>';
    } else {
      body = state.items.map(rowHtml).join('');
    }

    // ⚠ 2026-09-20 统一骨架：这里原来是【自己一套】的页头类名（.pj-head/.pj-title/.pj-sub）·
    //   没有标准的 .dash-head → _unifyDashHead 第一行就 return，它从头到尾没被整理过
    //   （实测页头块 0 个）。改成标准骨架类名，同时【保留原类名】不让既有样式崩。
    //   不给它硬加链子：它是独立域、不在掘金那条线上，空槽位就该空着。
    // 头部 chip 的两个数：项目数 + 挂载对话总数（对齐 .dh-chip 全站样式 · BRO 2026-09-21「包括数字显示」）
    var totalChats = 0;
    state.items.forEach(function (p) { totalChats += (p.chat_count || 0); });

    pane.innerHTML =
      '<div class="pj-wrap">'
      + '<div class="dash-head pj-head">'
      +   '<div class="dh-title-block">'
      +     '<h2 class="pj-title"><i class="ri-folders-fill"></i> 我的项目</h2>'
      +   '</div>'
      +   '<div class="dh-chips">'
      +     '<div class="dh-chip"><b>' + state.items.length + '</b><span>项目</span></div>'
      +     '<div class="dh-chip"><b>' + totalChats + '</b><span>条对话</span></div>'
      +   '</div>'
      +   '<button class="btn-primary pj-mini" data-pjadd="1">'
      +     '<i class="ri-add-line"></i> 添加一个新项目</button>'
      + '</div>'
      + '<div class="pj-tree">' + body + '</div>'
      + '<p class="pj-empty" style="margin-top:16px;padding-top:12px;border-top:1px solid var(--border)">'
      +   '<b>开新对话</b> = 起一条新会话，并把这条会话挂到这个项目下 · '
      +   '<b>移出项目</b> = 只从这张表里划掉，<b>磁盘上一个字节都不动</b>。</p>'
      + '</div>';
  }

  /* ══════════ 挂载浮层 ══════════ */
  function openPicker(initial, why) {
    injectStyle();
    if (document.getElementById('pjMask')) return;
    var m = document.createElement('div');
    m.className = 'pj-mask';
    m.id = 'pjMask';
    m.innerHTML =
      '<div class="pj-dlg">'
      + '<div class="pj-dlg-h"><div class="pj-dic"><i class="ri-folder-open-line"></i></div>'
      +   '<div><div class="pj-dlg-t">添加一个新项目</div>'
      +   '<div class="pj-dlg-s">' + (why ? esc(why) : '把要开发的目录路径粘进来') + '</div></div></div>'
      + '<div class="pj-dlg-b">'
      +   '<input class="pj-input" id="pjPathInput" placeholder="F:\\Desktop\\我的项目" spellcheck="false" value="' + esc(initial || '') + '">'
      +   '<div class="pj-hint">· 目录必须<b>已经存在</b>（不存在的会被挡下，防手滑粘错）<br>'
      +   '· 同一个目录只会挂一次，重复粘会直接跳回已有的那条<br>'
      +   '· 挂上之后，在这个目录里开的对话都归它</div>'
      + '</div>'
      + '<div class="pj-dlg-f">'
      +   '<span class="pj-err" id="pjErr"></span>'
      +   '<button class="btn-ghost pj-mini" data-pjcancel="1">取消</button>'
      +   '<button class="btn-primary pj-mini" data-pjok="1">挂上</button>'
      + '</div></div>';
    document.body.appendChild(m);
    var inp = document.getElementById('pjPathInput');
    if (inp) { inp.focus(); }
  }
  function closePicker() {
    var m = document.getElementById('pjMask');
    if (m) m.remove();
  }

  async function doMount() {
    var inp = document.getElementById('pjPathInput');
    var err = document.getElementById('pjErr');
    var path = inp ? inp.value.trim() : '';
    if (!path) { if (err) err.textContent = '先粘一个路径'; return; }
    if (err) err.textContent = '挂载中…';
    var d = await pjApi('POST', API, { path: path });
    if (!d || d.ok === false) {
      if (err) err.textContent = (d && d.error) || '挂载失败';
      return;
    }
    closePicker();
    await load();
    tip(d.duplicate ? ('这个目录已经挂过了：「' + (d.project && d.project.name || '') + '」')
                    : ('挂上了：「' + (d.project && d.project.name || '') + '」'));
  }

  /* ══════════ 拉系统原生选择器 ══════════ */
  async function startPick() {
    var lastPath = '';
    for (var i = 0; i < state.items.length; i++) {
      if (state.items[i].path) { lastPath = state.items[i].path; break; }
    }
    tip('正在拉系统选择器… 去桌面上选');
    var d = await pjApi('POST', API + '/pick-folder'
      + (lastPath ? ('?initial=' + encodeURIComponent(lastPath)) : ''));
    if (d && d.ok && d.path) {
      var r = await pjApi('POST', API, { path: d.path });
      if (r && r.ok !== false) {
        await load();
        tip(r.duplicate ? '这个目录已经挂过了' : ('挂上了：' + ((r.project && r.project.name) || '')));
      } else {
        tip((r && r.error) || '挂载失败');
        openPicker(d.path, (r && r.error) || '这个目录挂不上');   // 路径拿到了但挂不上 → 退回手输（带着已选的）
      }
      return;
    }
    if (d && d.cancelled) { tip('没选目录'); return; }

    // 没弹成 —— 在手输框里把「为什么」说清楚，别让人对着一个输入框猜
    var err = (d && d.error) || '拉不起选择器';
    if (/\b(405|404)\b|Not Found|Method Not Allowed/i.test(err)) {
      openPicker('', '后端这段还没装载 —— 让 OPUS 重启一次 daemon，本机点它就会直接弹系统自己的选目录框');
    } else if (d && d.remote) {
      openPicker('', '你这次是远程接入 —— 弹不出那台机器的选择器，所以先手输（在同一台机器上访问就会直接弹）');
    } else {
      openPicker('', err + ' —— 先手输，或者让 OPUS 看看后排');
    }
  }

  /* ══════════ 动作 ══════════ */
  /* 移出项目 = 只从这张表里划掉这一行 BRO 2026-09-20 原话：「不删本地文件，但是要可以从这里移出」——
     所以先弹一张确认卡把「磁盘一个字节都不动」写在脸上，再动手。 */
  function confirmUnmount(pid) {
    injectStyle();
    var hit = null;
    state.items.forEach(function (p) { if (p.id === pid) hit = p; });
    var nm = (hit && (hit.name || hit.id)) || pid;
    var pth = (hit && hit.path) || '';
    var cnt = (hit && hit.chat_count) || 0;
    var old = document.getElementById('pjSheet');
    if (old) old.remove();
    var m = document.createElement('div');
    m.className = 'pj-mask';
    m.id = 'pjSheet';
    m.innerHTML =
      '<div class="pj-dlg">'
      + '<div class="pj-dlg-h"><div class="pj-dic"><i class="ri-eject-line"></i></div>'
      +   '<div><div class="pj-dlg-t">把「' + esc(nm) + '」移出项目列表？</div>'
      +   '<div class="pj-dlg-s">只从这张列表里划掉 · 磁盘上一个字节都不动</div></div></div>'
      + '<div class="pj-dlg-b">'
      +   '<div class="pj-meta" style="padding:5px 2px"><span style="min-width:58px;color:var(--dim2)">目录</span>'
      +     '<span><code>' + esc(pth) + '</code></span></div>'
      +   (cnt ? '<div class="pj-hand"><i class="ri-information-line"></i><span>挂在它下面的 '
              + cnt + ' 条对话的项目标记会跟着摘掉（对话本身留着，一个字不动）</span></div>' : '')
      +   '<div class="pj-hint">以后想再用，重新「添加一个新项目」把这个目录挂回来就行 —— 记录没了，目录还在。</div>'
      + '</div>'
      + '<div class="pj-dlg-f">'
      +   '<button class="btn-ghost pj-mini" data-pjsheet-close="1">算了</button>'
      +   '<button class="btn-danger pj-mini" data-pjunmount-ok="' + esc(pid) + '">移出</button>'
      + '</div></div>';
    document.body.appendChild(m);
  }

  async function unmount(pid) {
    var d = await pjApi('DELETE', API + '/' + encodeURIComponent(pid));
    if (!d || d.ok === false) { tip((d && d.error) || '移出失败'); return; }
    await load();
    var n = (d && d.unbound_sessions) || 0;
    tip('移出了 · 磁盘上什么都没动' + (n ? (' · 顺带摘掉 ' + n + ' 条对话的项目标记') : ''));
    // 展开过的项目缓存了 sessions，重列一次免得下次展开看到旧的
    state.items.forEach(function (p) { delete p.sessions; });
  }
  /* ══════════ 引导卡上那一行「这个对话做的是 X」 ══════════
     BRO 2026-09-20：「选择了项目点了开新对话，直接改在图2这个位置下面不行吗？
     一句话说明是做哪个项目就好。」
     —— 原来我把「继续 X」预填进输入框，他得先删掉才能说自己想说的，碍事。
     改成挂在引导卡标题下：只说明这一场做哪个项目，输入框留空给他。 */
  function showProjectBanner(name, path) {
    clearProjectBanner();
    var head = document.querySelector('#onboardingPanel .onboarding-head');
    if (!head) return;                      // 老版页面没这结构 → 静默跳过，不影响开新对话
    var el = document.createElement('div');
    el.className = 'pj-onb-line';
    el.id = 'pjOnbLine';
    el.innerHTML = '<i class="ri-folder-3-fill"></i> 这个对话做的是 <b>' + esc(name) + '</b>'
                 + (path ? '<span class="pj-onb-path">' + esc(path) + '</span>' : '');
    head.appendChild(el);
  }

  function clearProjectBanner() {
    var el = document.getElementById('pjOnbLine');
    if (el) el.remove();
  }

  /* 每次「新对话」先清掉横幅与「挂项目」意图 —— 谁要显示谁自己插。
     包一层全局 newConversation 就不必去改 chat.js（BRO 说过别往那儿塞东西）：
     他自己点「新对话」也走这儿，不会把上一场的项目横幅留在新场上。
     wish-8f9e4f05 补：也在这里作废 _pjPendingId ——
       否则「点项目开新对话 → 不发消息 → 再手动点新对话 → 发消息」那句会被错挂到项目上。
       但 newChatFor 自己会调本函数、而且刚设好 pending —— 那一次不能清，用 flag 区分。 */
  if (typeof newConversation === 'function') {
    var _pjOrigNewConv = newConversation;
    window.newConversation = function () {
      if (!_pjFromNewChatFor) window._pjPendingId = '';
      var r = _pjOrigNewConv.apply(this, arguments);
      clearProjectBanner();
      return r;
    };
  }

  async function newChatFor(pid) {
    var hit = null;
    state.items.forEach(function (p) { if (p.id === pid) hit = p; });
    var nm = (hit && (hit.name || hit.id)) || pid;
    var pth = (hit && hit.path) || '';

    // 攒一次交接条存进项目资产（项目列表里展开那行能看到「上次停在哪」）
    pjApi('POST', API + '/' + encodeURIComponent(pid) + '/handoff').then(function () {}, function () {});

    // wish-8f9e4f05 · 项目跟着「首轮请求」进 daemon（照档位 tool_profile 那条通道）
    //   老做法是「记个标记 · 等 30 秒内冒陌生 sid 就挂」—— 打字稍慢就过期，永远挂不上。
    //   现在参数本来就在手上，不用猜任何时序。
    //   作废时机 = 「切新对话」（newConversation 的 override 里清），不是发请求时清 ——
    //   清了就丢：首轮请求万一失败/被中断，用户重发也挂不上。
    window._pjPendingId = pid;
    if (typeof newConversation !== 'function') { tip('找不到 newConversation —— 检查脚本加载顺序'); return; }
    _pjFromNewChatFor = true;                 // 告诉 override：这次是我们自己调的，别清 pending
    try { newConversation(); } finally { _pjFromNewChatFor = false; }
    // 项目默认档 → 替用户点亮「选档卡」那一张（想改再点别的卡）。
    // 链路：选档卡 → tpPendingProfile() → chat.js 随首轮传 tool_profile → 服务端锁进 meta。
    // （BRO 2026-09-21：档位那边收尾后接上）
    var wantProf = (hit && hit.profile) ? PROFILE_ID[String(hit.profile).trim()] : '';
    if (wantProf && typeof window.tpPresetPick === 'function') window.tpPresetPick(wantProf);
    showProjectBanner(nm, pth);
    tip('这一场做「' + nm + '」'
        + (wantProf ? ('· 默认档「' + hit.profile + '」已选好（想换点别的卡）') : '')
        + ' · 发第一句话就挂到它名下');
  }

  /* wish-8f9e4f05 · 项目随首轮请求进 daemon。
     只读不清 —— 清了的话，首轮请求万一失败/被中断，这个 id 就永久丢了（用户重发也挂不上）。
     作废时机在「切新对话」那一处（newConversation 的 override）· 那才是意图真正结束的时刻。 */
  function pjPendingId() { return window._pjPendingId || ''; }
  window.pjPendingId = pjPendingId;

  /* ══════════ 点击分发（一个入口 · 不散落） ══════════ */
  /* ══════════ 项目详情浮层（wish-178a8517） ══════════
     BRO 2026-09-21 定的形态（原型 data/design/开发项目详情-原型v1.html）：
       · 骨架复用全站在用的 .kb-modal —— 不再自造遮罩/圆角/动画（那套硬编码色不跟主题）
       · 信息分层：状态条 → 进度 → 接着上次 → 对话 → 默认档位 → 动作区
       · 版本号 = git tag 优先；进度 = 项目自己目录里的 OPUS.md 里程碑（勾要带证据）
     数据并行拉：/detail（git + opus_md）+ /sessions（对话列表）。 */
  async function showProjectSheet(pid) {
    injectStyle();
    var enc = encodeURIComponent(pid);
    var rs = await Promise.all([
      pjApi('GET', API + '/' + enc + '/detail'),
      pjApi('GET', API + '/' + enc + '/sessions')
    ]);
    var d = rs[0], s = rs[1];
    var p = (d && d.ok !== false && d.project) ? d.project : null;
    if (!p) { tip('读不到这个项目（可能已经被移出了）'); return; }
    var old = document.getElementById('pjSheet');
    if (old) old.remove();

    var g = p.git || {};
    var om = p.opus_md || {};
    var ms = om.milestones || [];
    var msDone = ms.filter(function (m) { return !!m.done; }).length;
    var alive = p.path_exists !== false;

    // ── ① 状态条：一眼看完这个项目此刻的样子 ──
    var dotCls = 'dot' + (!alive ? ' bad' : (g.is_repo && g.dirty > 0 ? ' warn' : ''));
    var stMain = !alive ? '目录不在了' : (g.is_repo && g.dirty > 0 ? '有活没落盘' : '在开发中');
    var chips = [];
    if (!alive) {
      chips.push('上次扫到它还在');
    } else if (g.is_repo) {
      chips.push('Git <b>' + esc(g.branch || '—') + '</b> · ' + (g.dirty ? '<b>' + g.dirty + ' 个未提交</b>' : '干净')
        + (g.ahead ? ' · 领先 ' + g.ahead : '') + (g.behind ? ' · 落后 ' + g.behind : ''));
    } else {
      chips.push('不是 git 仓库');
    }
    if (p.chat_count) chips.push('<b>' + p.chat_count + '</b> 条对话');
    var lastAt = ago(p.last_used_at || p.created_at);
    if (lastAt) chips.push('<b>' + esc(lastAt) + '</b>动过');

    var html = '<div class="pj-st"><span class="' + dotCls + '"></span><b>' + esc(stMain) + '</b>'
             + chips.map(function (c) { return '<span class="sep">·</span><span>' + c + '</span>'; }).join('')
             + '</div>';

    // ── ② 进度（有里程碑才画 —— 没就一行小字指路，不编数字） ──
    if (ms.length) {
      var pct = Math.max(0, Math.min(100, Math.round(msDone / ms.length * 100)));
      html += '<div class="pj-blk"><div class="pj-blk-t">进度 <span>' + msDone + '/' + ms.length + '</span></div>'
           +  '<div class="pj-prog"><i style="width:' + pct + '%"></i></div>'
           +  '<ul class="pj-ms">' + ms.map(function (m) {
                return '<li class="' + (m.done ? 'done' : '') + '">' + esc(m.text) + '</li>';
              }).join('') + '</ul></div>';
    } else if (alive) {
      html += '<div class="pj-blk"><div class="pj-blk-t">进度</div><div class="pj-hint" style="margin-top:0">'
           +  '项目目录里放一个 <code>OPUS.md</code>（版本号 + <code>- [x]</code> 里程碑），这里就会显出来'
           +  (om.err ? ' · 读了但没读成：' + esc(om.err) : '') + '</div></div>';
    }

    // ── ③ 接着上次（交接条） ──
    if (p.handoff) {
      html += '<div class="pj-blk"><div class="pj-blk-t">接着上次</div>'
           +  '<div class="pj-hand"><i class="ri-corner-down-right-line"></i><span>' + esc(p.handoff) + '</span></div></div>';
    }

    // ── ④ 对话（点一下进那一场 —— data-pjsess 分发是现成的） ──
    var sess = (s && s.ok !== false && s.sessions) ? s.sessions : [];
    html += '<div class="pj-blk"><div class="pj-blk-t">对话' + (sess.length ? ' <span>' + sess.length + '</span>' : '') + '</div>';
    if (sess.length) {
      html += sess.slice(0, 8).map(function (r) {
        var t = r.title || r.label || r.preview || '（没标题）';
        var raw = r.mtime || r.updated_at || r.last_active || '';
        if (typeof raw === 'number') raw = new Date(raw * 1000).toISOString();
        var when = ago(raw);
        var cnt = r.msg_count || r.message_count || 0;
        return '<div class="pj-sess" data-pjsess="' + esc(r.session_id) + '">'
             + '<i class="ri-chat-1-line"></i><span class="t">' + esc(t) + '</span>'
             + '<span class="w">' + esc(when) + (cnt ? ' · ' + cnt + ' 楼' : '') + '</span>'
             + '<span class="go">进入 →</span></div>';
      }).join('');
    } else {
      html += '<div class="pj-hint" style="margin-top:0">还没开过对话 —— 点右下角「开新对话」起一场</div>';
    }
    html += '</div>';

    // ── ⑤ 默认档位（能看也能改 —— 改走现成的 PATCH） ──
    var profOpts = Object.keys(PROFILE_ID).map(function (nm) {
      return '<option value="' + esc(nm) + '"' + (nm === (p.profile || '标准') ? ' selected' : '') + '>' + esc(nm) + '</option>';
    }).join('');
    html += '<div class="pj-blk"><div class="pj-blk-t">默认档位</div><div class="pj-prof">'
         +  '<select data-pjprof="' + esc(p.id) + '">' + profOpts + '</select>'
         +  '<span class="hint">这个项目里开新对话时自动带上 · 想临时换点别的卡也行</span></div></div>';

    // ── 装壳（骨架全用 chat.css 现成的 .kb-modal*） ──
    var m = document.createElement('div');
    m.className = 'kb-modal-host show';
    m.id = 'pjSheet';
    m.innerHTML =
      '<div class="kb-modal-mask" data-pjsheet-close="1"></div>'
      + '<div class="kb-modal" role="dialog" aria-modal="true">'
      + '<div class="kb-modal-head">'
      +   '<span class="pj-ico"><i class="ri-folder-3-fill"></i></span>'
      +   '<span class="kb-modal-title">' + esc(p.name || p.id) + '</span>'
      +   (p.version ? '<span class="pj-badge ver">v' + esc(p.version) + '</span>' : '')
      +   '<span class="pj-badge">' + esc(p.profile || '标准') + '</span>'
      +   '<span class="kb-modal-meta">' + esc(p.path) + '</span>'
      +   '<button class="kb-modal-close" data-pjsheet-close="1" title="关闭 (Esc)">✕</button>'
      + '</div>'
      + '<div class="kb-modal-body">' + html + '</div>'
      + '<div class="pj-foot">'
      +   '<button class="btn-ghost pj-mini" data-pjopen="' + esc(p.id) + '"><i class="ri-folder-open-line"></i> 在文件夹里打开</button>'
      +   '<button class="btn-ghost pj-mini" data-pjcopy="' + esc(p.path) + '"><i class="ri-file-copy-line"></i> 复制路径</button>'
      +   '<button class="btn-ghost pj-mini" data-pjgoto="' + esc(p.id) + '"><i class="ri-layout-left-line"></i> 去我的项目看</button>'
      +   '<span class="sp"></span>'
      +   '<button class="btn-ghost pj-mini" data-pjunmount="' + esc(p.id) + '">移出项目</button>'
      +   '<button class="btn-primary pj-mini" data-pjnew="' + esc(p.id) + '"><i class="ri-add-line"></i> 开新对话</button>'
      + '</div></div>';
    document.body.appendChild(m);
  }
  window.pjOpenSheet = showProjectSheet;

  /* 在 daemon 那台机器的文件管理器里打开项目目录（远程会被服务端拒 —— 见路由注释） */
  async function openFolder(pid) {
    var r = await pjApi('POST', API + '/' + encodeURIComponent(pid) + '/open-folder');
    if (r && r.ok !== false) { tip('已在文件管理器里打开'); return; }
    tip((r && (r.error || r.detail)) || '打不开');
  }

  /* 复制路径 —— Clipboard API 优先，http 下退 document.execCommand */
  function copyPath(path) {
    var done = function () { tip('路径已复制'); };
    var fallback = function () {
      try {
        var ta = document.createElement('textarea');
        ta.value = path;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        ta.remove();
        done();
      } catch (e) { tip('复制失败（浏览器不让）'); }
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(path).then(done, fallback);
    } else { fallback(); }
  }

  /* 档位下拉 → PATCH（改的是项目默认档 · 正在跑的这场不受影响） */
  document.addEventListener('change', function (e) {
    var t = e.target;
    if (!t || !t.closest) return;
    var sel = t.closest('[data-pjprof]');
    if (!sel) return;
    var pid = sel.getAttribute('data-pjprof');
    var val = sel.value;
    pjApi('PATCH', API + '/' + encodeURIComponent(pid), { profile: val }).then(function (r) {
      if (r && r.ok !== false) { tip('默认档位已改成「' + val + '」'); load(); }
      else { tip('改档失败：' + ((r && (r.error || r.detail)) || '未知')); }
    });
  });

  function closeSheet() {
    var s = document.getElementById('pjSheet');
    if (s) s.remove();
  }

  function ensureOpen(pid) {
    var hit = null;
    state.items.forEach(function (p) { if (p.id === pid) hit = p; });
    if (hit) hit.open = true;
    if (window._pjPane) render(window._pjPane);
  }

  document.addEventListener('click', function (e) {
    var t = e.target;
    if (!t || !t.closest) return;

    // 引导卡 data-view="projects" → 切中栏（chat.js 的 data-template 通道不受影响）
    if (t.closest('[data-view="projects"]')) {
      if (typeof switchView === 'function') switchView('projects');
      return;
    }
    if (t.closest('[data-pjadd]')) { startPick(); return; }
    if (t.closest('[data-pjcancel]')) { closePicker(); return; }
    if (t.closest('[data-pjok]')) { doMount(); return; }

    var tg = t.closest('[data-pjtoggle]');
    if (tg) { toggle(tg.getAttribute('data-pjtoggle')); return; }

    if (t.closest('[data-pjsheet-close]')) { closeSheet(); return; }

    var op = t.closest('[data-pjopen]');
    if (op) { openFolder(op.getAttribute('data-pjopen')); return; }

    var cp = t.closest('[data-pjcopy]');
    if (cp) { copyPath(cp.getAttribute('data-pjcopy')); return; }

    // 项目行的「详情」—— 以前只有话题药丸能点开这个浮层，项目列表里反而没入口
    var sh = t.closest('[data-pjsheet]');
    if (sh) { showProjectSheet(sh.getAttribute('data-pjsheet')); return; }

    var gt = t.closest('[data-pjgoto]');
    if (gt) {
      var gid = gt.getAttribute('data-pjgoto');
      closeSheet();
      if (typeof switchView === 'function') switchView('projects');
      ensureOpen(gid);
      return;
    }

    var nb = t.closest('[data-pjnew]');
    if (nb) { closeSheet(); newChatFor(nb.getAttribute('data-pjnew')); return; }

    var ss = t.closest('[data-pjsess]');
    if (ss) {
      if (typeof switchToSession === 'function') switchToSession(ss.getAttribute('data-pjsess'));
      else tip('找不到 switchToSession —— 检查脚本加载顺序');
      return;
    }

    var un = t.closest('[data-pjunmount]');
    if (un) { confirmUnmount(un.getAttribute('data-pjunmount')); return; }

    var uok = t.closest('[data-pjunmount-ok]');
    if (uok) { var upid = uok.getAttribute('data-pjunmount-ok'); closeSheet(); unmount(upid); return; }

    var rw = t.closest('[data-pjrow]');
    if (rw) { toggle(rw.getAttribute('data-pjrow')); return; }
  });

  function toggle(pid) {
    var hit = null;
    state.items.forEach(function (p) { if (p.id === pid) hit = p; });
    if (!hit) return;
    hit.open = !hit.open;
    if (hit.open && hit.sessions === undefined) loadProjectSessions(pid);   // 首次展开才拉
    if (window._pjPane) render(window._pjPane);
  }

  async function loadProjectSessions(pid) {
    var d = await pjApi('GET', API + '/' + encodeURIComponent(pid) + '/sessions');
    var hit = null;
    state.items.forEach(function (p) { if (p.id === pid) hit = p; });
    if (!hit) return;
    hit.sessions = (d && d.ok !== false) ? (d.sessions || []) : [];
    if (window._pjPane && pjViewNow()) render(window._pjPane);
  }

  /* ══════════ 注册（导航 + 中栏渲染 · 都走官方装修接口） ══════════ */
  if (window.Daemonkey && typeof Daemonkey.addDomain === 'function') {
    Daemonkey.addDomain('projects', {
      label: '我的项目',
      icon: 'ri-folders-fill',
      section: 'studio',
      render: function (pane) { render(pane); }
    });
  } else {
    console.warn('[projects] Daemonkey.addDomain 不在 —— 检查 static/projects.js 是否在 chat.js 之后加载');
  }
})();
