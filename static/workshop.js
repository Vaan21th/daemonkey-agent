/*
 * workshop.js · OPUS 出品工坊 · LiteGraph 二栏内嵌 view
 *
 * 卷四十四 K stage 1b · 从独立页 /workshop 改成 /ui 中央 detail-pane 的 view
 *
 * 暴露:
 *   window.OPUS_WORKSHOP_VIEW = {
 *     mount(container)   - 把工坊 DOM 注入 container · 第一次会 init LiteGraph
 *     unmount()          - 切到别的 view 时清理 listener · graph 状态保留
 *     isMounted()        - 是否当前挂着
 *     resize()           - 强制 canvas 重画 (e.g. 主 nav 隐藏后可调)
 *     serialize() / load(data)  - 给 chat.js 持久化用
 *   }
 *
 * 不做 (留给 stage 2):
 *   - 真跑 (<i class="ri-play-fill"></i> 当前 mock · 拓扑顺序 + 假进度)
 *   - 跟 daemon /workflow/run SSE 接力
 *   - LLM 生成自定义工具时落 data/workflow/tools/*.json
 */

(function () {
  'use strict';
  if (window.OPUS_WORKSHOP_VIEW) return;  // 防双重加载

  // ─── 工具节点 schema (跟未来 data/workflow/tools/*.json 对齐) ───
  const TOOL_SPECS = {
    'composite/content': {
      icon: '<i class="ri-film-fill"></i>', title: '内容制作', group: 'composite',
      desc: 'LLM 选题 → 文稿 → 标题', color: '#9F7AEA',
      inputs: [{ name: 'topic', type: 'string' }],
      outputs: [{ name: 'script', type: 'string' }, { name: 'title', type: 'string' }],
      props: { template: 'content_default' },
    },
    'composite/design': {
      icon: '<i class="ri-palette-fill"></i>', title: '产品设计', group: 'composite',
      desc: 'spec → wireframe → 用户旅程', color: '#9F7AEA',
      inputs: [{ name: 'idea', type: 'string' }],
      outputs: [{ name: 'spec', type: 'string' }, { name: 'wireframe', type: 'string' }],
      props: { template: 'design_default' },
    },
    'composite/dev': {
      icon: '<i class="ri-terminal-box-fill"></i>', title: '产品开发', group: 'composite',
      desc: 'cursor 写码 → 测试 → 部署', color: '#9F7AEA',
      inputs: [{ name: 'spec', type: 'string' }],
      outputs: [{ name: 'repo', type: 'string' }, { name: 'test_log', type: 'string' }],
      props: { template: 'dev_default' },
    },
    'composite/docs': {
      icon: '<i class="ri-file-text-fill"></i>', title: '文档撰写', group: 'composite',
      desc: 'md → docx → 归档', color: '#9F7AEA',
      inputs: [{ name: 'subject', type: 'string' }],
      outputs: [{ name: 'docx_path', type: 'string' }],
      props: { template: 'docs_default' },
    },
    'atomic/llm': {
      icon: '<i class="ri-robot-fill"></i>', title: 'LLM 调用', group: 'atomic',
      desc: 'agent_tools.run_llm', color: '#5DA3F0',
      inputs: [{ name: 'prompt', type: 'string' }, { name: 'system', type: 'string' }],
      outputs: [{ name: 'text', type: 'string' }],
      props: { model: 'auto', temperature: 0.7 },
    },
    'atomic/web_search': {
      icon: '<i class="ri-search-fill"></i>', title: 'web 搜索', group: 'atomic',
      desc: 'agent_tools.web_search', color: '#5DA3F0',
      inputs: [{ name: 'query', type: 'string' }],
      outputs: [{ name: 'results', type: 'array' }],
      props: { top_k: 10 },
    },
    'atomic/browser_fetch': {
      icon: '<i class="ri-global-fill"></i>', title: '浏览器抓取', group: 'atomic',
      desc: 'agent_tools.browser_fetch', color: '#5DA3F0',
      inputs: [{ name: 'url', type: 'string' }],
      outputs: [{ name: 'content', type: 'string' }],
      props: {},
    },
    'atomic/write_file': {
      icon: '<i class="ri-save-fill"></i>', title: '写文件', group: 'atomic',
      desc: 'agent_tools.write_file', color: '#5DA3F0',
      inputs: [{ name: 'path', type: 'string' }, { name: 'body', type: 'string' }],
      outputs: [{ name: 'ok', type: 'boolean' }],
      props: {},
    },
    'atomic/shell_exec': {
      icon: '<i class="ri-flash-fill"></i>', title: 'shell 命令', group: 'atomic',
      desc: 'agent_tools.shell_exec', color: '#5DA3F0',
      inputs: [{ name: 'cmd', type: 'string' }],
      outputs: [{ name: 'stdout', type: 'string' }, { name: 'exit_code', type: 'number' }],
      props: {},
    },
  };
  // custom/sovits 占位符已删除 (卷四十六续 13)
  // 自定义工具组现在从 _apps (kind='app') 动态生成 · 见 _renderToolGroup('custom') 分支
  // GPT-SoVITS / GPT Image 2 等 OPUS 真造的 app 直接进 sidebar · 拖到画布生成 opus/app/<aid> 节点

  // ─── LiteGraph 右键菜单中文化 (MENU_I18N) ───
  // 来源:阅读 LiteGraph.js 源码 · 内置菜单文案就这些
  const MENU_I18N = {
    'Add Node': '➕ 添加节点',
    'Add Group': '<i class="ri-archive-fill"></i> 添加分组',
    'Search': '<i class="ri-search-fill"></i> 搜索',
    'Title': '标题',
    'Mode': '模式',
    'Resize': '调大小',
    'Collapse': '折叠',
    'Pin': '固定',
    'Colors': '颜色',
    'Shapes': '形状',
    'Properties': '属性',
    'Properties Panel': '属性面板',
    'Inputs': '输入',
    'Outputs': '输出',
    'Remove': '删除',
    'Clone': '克隆',
    'Reset': '重置',
    'Always': '始终',
    'On Event': '事件触发',
    'Never': '从不',
    'On Trigger': '触发时',
    'Add Input': '加输入口',
    'Add Output': '加输出口',
    'Remove Input': '删输入口',
    'Remove Output': '删输出口',
    'Convert to': '转成',
    'Group Selected Nodes': '把选中的节点分组',
  };

  let _menuLang = localStorage.getItem('opus_workshop_lang') || 'zh';

  // ─── HTML icon → emoji 映射 (canvas title 用 · LiteGraph 不解析 HTML) ───
  // workshop.js 里所有节点 title 走 canvas drawText · 任何 <i class="ri-...">
  // 都会变成裸文本。所有 canvas-bound 的地方走这个 helper · 拿到一个 emoji。
  const RI_TO_EMOJI = {
    'ri-film-fill': '🎬', 'ri-palette-fill': '🎨', 'ri-terminal-box-fill': '💻',
    'ri-file-text-fill': '📝', 'ri-robot-fill': '🤖', 'ri-search-fill': '🔍',
    'ri-global-fill': '🌐', 'ri-save-fill': '💾', 'ri-flash-fill': '⚡',
    'ri-mic-fill': '🎙️', 'ri-puzzle-fill': '🧩', 'ri-image-fill': '🖼️',
    'ri-magic-fill': '✨', 'ri-music-fill': '🎵', 'ri-brush-fill': '🖌️',
  };
  function iconToEmoji(s) {
    if (typeof s !== 'string' || !s) return '🧩';
    if (!/^<i\s/i.test(s)) return s;  // 已经是 emoji 字面字符 · 直接返
    const m = s.match(/\bri-[a-z0-9-]+/);
    return m ? (RI_TO_EMOJI[m[0]] || '🧩') : '🧩';
  }

  // ─── 内置应用 (跟 chat.js DOMAIN_META 4 老维度对齐 · 走 /dashboard/<dim>) ───
  // stage 2c · OPUS 自己造的 app 从 /workshop/apps 拉 · 跟内置共存
  const BUILTIN_APPS = [
    {
      id: 'builtin-content', icon: '<i class="ri-film-fill"></i>', name: '内容制作', kind: 'builtin',
      description: '公众号 / 视频脚本 / 短文 · LLM 选题 → 文稿 → 标题',
      dashboard_domain: 'content',
    },
    {
      id: 'builtin-design', icon: '<i class="ri-palette-fill"></i>', name: '产品设计', kind: 'builtin',
      description: '需求 → spec → wireframe → 用户旅程',
      dashboard_domain: 'design',
    },
    {
      id: 'builtin-dev', icon: '<i class="ri-terminal-box-fill"></i>', name: '产品开发', kind: 'builtin',
      description: 'spec → cursor 写码 → 测试 → 部署',
      dashboard_domain: 'dev',
    },
    {
      id: 'builtin-docs', icon: '<i class="ri-file-text-fill"></i>', name: '文档撰写', kind: 'builtin',
      description: 'md → docx → 归档',
      dashboard_domain: 'docs',
    },
  ];

  // 当前的应用列表 (built-in + OPUS 造) · mount 时填充
  let _apps = BUILTIN_APPS.slice();
  let _flows = [];  // workflow 列表 · 仅 OPUS 造
  // 卷四十四 K stage 2c++ · wish-6fd76512 · 回收站状态 (lazy load · 切到 trash tab 才拉)
  let _trash = { apps: [], flows: [] };
  let _trashLoaded = false;

  function _getToken() { return localStorage.getItem('opus_ui_token') || ''; }

  function tr(s) {
    if (_menuLang === 'en' || !s) return s;
    return MENU_I18N[s] || s;
  }

  function _translateMenu(opts) {
    if (!opts) return opts;
    return opts.map(o => {
      if (!o) return o;
      const c = Object.assign({}, o);
      if (c.content) c.content = tr(c.content);
      if (c.submenu && c.submenu.options) {
        c.submenu = Object.assign({}, c.submenu, { options: _translateMenu(c.submenu.options) });
      }
      return c;
    });
  }

  // ─── 模块状态 ───
  let _container = null;
  let _graph = null;
  let _canvas = null;
  let _canvasEl = null;
  let _canvasWrap = null;
  let _resizeObs = null;
  let _onResize = null;
  let _nodesRegistered = false;
  let _menuPatched = false;
  // 卷四十四 K stage 2a · tabs + 应用详情状态
  // stage 2b · 砍 'create' tab (BRO: 跟右侧 OPUS 重复 · 自然语言已够) · 残留 'create' 回退 'apps'
  // stage 2c++ · wish-6fd76512 · 加 'trash' tab
  let _activeTab = localStorage.getItem('opus_workshop_tab') || 'apps';  // apps | canvas | trash
  if (_activeTab === 'create') _activeTab = 'apps';
  if (!['apps', 'canvas', 'trash'].includes(_activeTab)) _activeTab = 'apps';
  let _activeAppId = null;  // null = 看应用网格 · 否则 = 看应用详情

  // ─── 一次性: 注册内置工具节点类型 ───
  function _registerNodes() {
    if (_nodesRegistered) return;
    _nodesRegistered = true;
    for (const [key, spec] of Object.entries(TOOL_SPECS)) {
      const fullType = 'opus/' + key;
      const canvasTitle = iconToEmoji(spec.icon) + ' ' + spec.title;

      function OpusNode() {
        this.title = canvasTitle;
        this.color = spec.color;
        this.bgcolor = '#252525';
        this.boxcolor = spec.color;
        for (const inp of spec.inputs) this.addInput(inp.name, inp.type);
        for (const out of spec.outputs) this.addOutput(out.name, out.type);
        this.properties = Object.assign({ _toolKey: key }, spec.props || {});
        this.size = [200, 24 + Math.max(spec.inputs.length, spec.outputs.length) * 20 + 8];
      }
      OpusNode.title = canvasTitle;
      OpusNode.desc = spec.desc;
      OpusNode.prototype.onExecute = function () { /* phase B 由 daemon workflow_engine 真跑 · 前端不本地执行 */ };
      OpusNode.prototype.onAdded = function () { if (/<i\s[^>]*>/i.test(this.title || '')) this.title = canvasTitle; };
      OpusNode.prototype.onConfigure = function () { if (/<i\s[^>]*>/i.test(this.title || '')) this.title = canvasTitle; };
      LiteGraph.registerNodeType(fullType, OpusNode);
    }
  }

  // 卷四十六续 12 · wish-165ea1f6 phase B · 把 OPUS 造的 app 注册成 LiteGraph 节点
  //   - 每张 OPUS app 卡片 → 一个 node type 'opus/app/<aid>'
  //   - ui_form_schema → input ports (BRO 画布上可以连上游 outputs)
  //   - output_schema  → output ports (能接下游 inputs · 没声明默认单端口 'output')
  //   - 每次 _apps 更新都调一次 (idempotent · 已注册的同 type 跳过)
  const _registeredAppTypes = new Set();
  function _registerAppNodes() {
    if (typeof LiteGraph === 'undefined') return;
    for (const app of _apps) {
      if (!app || !app.id) continue;
      if (app.kind === 'builtin') continue;
      const fullType = 'opus/app/' + app.id;
      if (_registeredAppTypes.has(fullType)) continue;

      const inputs = (Array.isArray(app.ui_form_schema) ? app.ui_form_schema : []).map(f => ({
        name: f.name,
        type: _mapFieldTypeToLG(f.type),
      }));
      const outputs = (Array.isArray(app.output_schema) && app.output_schema.length)
        ? app.output_schema.map(o => ({ name: o.name, type: _mapOutputTypeToLG(o.type) }))
        : [{ name: 'output', type: 'string' }];

      const title = iconToEmoji(app.icon) + ' ' + app.name;

      function AppNode() {
        this.title = title;
        this.color = '#48BB78';
        this.bgcolor = '#252525';
        this.boxcolor = '#48BB78';
        for (const inp of inputs) this.addInput(inp.name, inp.type);
        for (const out of outputs) this.addOutput(out.name, out.type);
        this.properties = { _appId: app.id, _kind: 'opus_app' };
        this.size = [220, 24 + Math.max(inputs.length, outputs.length) * 20 + 8];
      }
      AppNode.title = title;
      AppNode.desc = app.description || '';
      AppNode.prototype.onExecute = function () { /* daemon workflow_engine 真跑 · 不本地执行 */ };
      AppNode.prototype.onAdded = function () { if (/<i\s[^>]*>/i.test(this.title || '')) this.title = title; };
      AppNode.prototype.onConfigure = function () { if (/<i\s[^>]*>/i.test(this.title || '')) this.title = title; };
      try {
        LiteGraph.registerNodeType(fullType, AppNode);
        _registeredAppTypes.add(fullType);
      } catch (e) { /* 同 type 已注册 · 静默 */ }
    }

    // 兜底: 画布上已存在的节点 (老代码注册时 title 是裸 HTML)·in-place 修正
    // 同时 cover OPUS app 节点和内置 TOOL_SPECS 节点 (两种都可能有裸 HTML title)
    if (_graph && Array.isArray(_graph._nodes)) {
      let touched = false;
      for (const n of _graph._nodes) {
        if (!n || !/<i\s[^>]*>/i.test(n.title || '')) continue;
        const kind = n.properties && n.properties._kind;
        if (kind === 'opus_app') {
          const app = _apps.find(a => a && a.id === n.properties._appId);
          if (app) { n.title = iconToEmoji(app.icon) + ' ' + app.name; touched = true; }
        } else if (n.properties && n.properties._toolKey) {
          const spec = TOOL_SPECS[n.properties._toolKey];
          if (spec) { n.title = iconToEmoji(spec.icon) + ' ' + spec.title; touched = true; }
        }
      }
      if (touched && _canvas) _canvas.setDirty(true, true);
    }
  }

  function _mapFieldTypeToLG(t) {
    // ui_form_schema 字段 type → LiteGraph 端口 type
    if (t === 'number') return 'number';
    if (t === 'boolean') return 'boolean';
    if (t === 'file') return 'file';
    return 'string';  // text/textarea/select 都是字符串
  }
  function _mapOutputTypeToLG(t) {
    if (t === 'number') return 'number';
    if (t === 'boolean') return 'boolean';
    if (t === 'array') return 'array';
    if (t === 'object') return 'object';
    if (t === 'file') return 'file';
    return 'string';
  }

  // ─── 一次性: 拦 LiteGraph 右键菜单做翻译 ───
  function _patchMenu() {
    if (_menuPatched) return;
    _menuPatched = true;
    const origCanvas = LGraphCanvas.prototype.getCanvasMenuOptions;
    LGraphCanvas.prototype.getCanvasMenuOptions = function () {
      return _translateMenu(origCanvas.call(this));
    };
    const origNode = LGraphCanvas.prototype.getNodeMenuOptions;
    LGraphCanvas.prototype.getNodeMenuOptions = function (node) {
      return _translateMenu(origNode.call(this, node));
    };
  }

  // ─── HTML 模板 (卷四十四 K stage 2a · tabs 三段式) ───
  function _html() {
    return `
      <div class="workshop-view" data-tab="${_activeTab}" data-tb-collapsed="0">
        <div class="ws-tabs">
          <button class="ws-tab" data-tab="apps" data-act="switch-tab"><i class="ri-archive-fill"></i> 应用</button>
          <button class="ws-tab" data-tab="canvas" data-act="switch-tab">⚛ 工作流画布</button>
          <button class="ws-tab" data-tab="trash" data-act="switch-tab" title="回收站 · 软删的 app/flow 在这里 · 可恢复或永久删">🗑 回收站</button>
          <span class="ws-tabs-spacer"></span>
          <span class="ws-tabs-hint">应用 = 独立模块 · 工作流 = 把它们串起来 · 删除走回收站</span>
        </div>

        <div class="ws-content">
          <!-- ── apps tab · 卷四十六续 11 · sidebar list + main detail 二栏 ── -->
          <!-- 设计: 左侧固定 sidebar (220px) 列应用 · 右侧 main 显示详情或 welcome -->
          <!-- 折叠按钮 «/» 把 sidebar 缩成 icon-only (52px) · localStorage 记忆 -->
          <!-- 不动 .ws-ad-* (detail head/tabs/pane) · 另一根毛改 [data-ad-pane="test"] 内部 -->
          <div class="ws-pane ws-pane-apps" data-pane="apps">
            <aside class="ws-apps-sidebar" id="wsAppsSidebar">
              <div class="ws-apps-side-head">
                <span class="wash-title"><i class="ri-archive-fill"></i> 应用</span>
                <button class="wash-collapse" data-act="toggle-apps-sidebar" title="折叠应用列表 (留 icon)">«</button>
              </div>
              <div class="ws-apps-side-search">
                <input type="search" id="wsAppsSideFilter" placeholder="搜应用…" autocomplete="off">
              </div>
              <!-- 容器名 #wsAppsGrid 保留 · _loadAssetsFromDaemon / _onDeleteApp 还在用 -->
              <div class="ws-apps-grid" id="wsAppsGrid">
                ${_renderAppCards()}
              </div>
            </aside>
            <div class="ws-apps-main" id="wsAppDetail">
              ${_renderAppsMainWelcome()}
            </div>
          </div>

          <!-- ── canvas tab · 工具集 + LiteGraph 画布 ── -->
          <div class="ws-pane ws-pane-canvas" data-pane="canvas">
            <aside class="ws-toolbox" id="wsToolbox">
              <div class="ws-tb-head">
                <span class="ws-tb-title">🧰 工具集</span>
                <button class="ws-tb-toggle" data-act="hide-tb" title="收起工具集 (展开后从右侧 » 按钮重开)">«</button>
              </div>
              <div class="ws-tb-search">
                <input type="search" id="wsToolboxSearch" placeholder="搜工具…" autocomplete="off">
              </div>
              <div class="ws-tb-body">
                ${_renderToolGroup('composite', '<i class="ri-archive-fill"></i> 复合工具 · 生产线模板')}
                ${_renderToolGroup('atomic', '⚛ 原子工具 · 单步动作')}
                ${_renderToolGroup('custom', '✨ 自定义工具 · OPUS 长出来的')}
                <div class="ws-tb-add">
                  <button data-act="ask-opus-tool" title="跟右侧 OPUS 说『我想要一个 X 工具』 · OPUS 自己去做">＋ 让 OPUS 长一个新工具</button>
                </div>
              </div>
            </aside>

            <button class="ws-tb-show" id="wsToolboxShow" title="展开工具集" hidden>»</button>

            <div class="ws-canvas-wrap" id="wsCanvasWrap">
              <div class="ws-canvas-toolbar">
                <span class="ws-canvas-title"><i class="ri-magic-fill"></i> 工作流</span>
                <span class="ws-canvas-hint">跟右侧 OPUS 说「做 X 事」 · OPUS 排好工作流落到画布 · 你保存/微调/再跑</span>
                <span class="ws-spacer"></span>
                <button class="ws-btn ws-btn-emphasis" data-act="save" title="保存当前画布到本地草稿"><i class="ri-save-fill"></i> 保存</button>
                <button class="ws-btn ws-btn-emphasis" data-act="load" title="载入保存过的工作流">📂 加载</button>
                <span class="ws-btn-divider"></span>
                <button class="ws-btn" data-act="run" title="运行 (原型 · stage 2c 真跑)"><i class="ri-play-fill"></i> 运行</button>
                <button class="ws-btn" data-act="clear" title="清空画布">🗑 清空</button>
                <button class="ws-btn ws-lang-btn" data-act="lang" id="wsLangBtn" title="切换右键菜单语言">${_menuLang === 'zh' ? '中' : 'EN'}</button>
              </div>
              <canvas id="wsCanvas"></canvas>
              <div class="ws-canvas-empty" id="wsCanvasEmpty">
                <div class="ws-empty-icon">⚛</div>
                <div class="ws-empty-title">画布为空</div>
                <div class="ws-empty-hint">两种来法:跟右侧 OPUS 说「做一份 X 工作流」让它给你排 · 或者从左侧工具集拖工具自己组装</div>
              </div>
            </div>
          </div>

          <!-- ── trash tab · 回收站 (wish-6fd76512) ── -->
          <div class="ws-pane" data-pane="trash">
            <div class="ws-trash-pane" id="wsTrashPane">
              <div class="ws-trash-loading"><i class="ri-radar-fill"></i> 拉回收站中…</div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  // ─── 应用卡片网格 (<i class="ri-archive-fill"></i> 应用 tab) ───
  function _renderAppCards() {
    const cards = _apps.map(app => {
      const isBuiltin = app.kind === 'builtin';
      const meta = isBuiltin
        ? '<span class="wac-stage">stage 2b 可配置</span>'
        : `<span class="wac-stage">${_esc((app.created_at || '').slice(0, 10))} · OPUS 造</span>`;
      // wish-6fd76512 · OPUS 造的 app 卡片右上角悬停浮出 🗑 (软删到回收站) · 内置不可删
      const trashBtn = isBuiltin ? '' : `<button class="wac-trash-btn" data-act="app-delete-card" data-app-id="${_esc(app.id)}" title="移到回收站 (可恢复)">🗑</button>`;
      return `
        <div class="ws-app-card" data-app-id="${_esc(app.id)}" data-act="open-app">
          ${trashBtn}
          <div class="wac-icon">${app.icon || '<i class="ri-puzzle-fill"></i>'}</div>
          <div class="wac-body">
            <div class="wac-title">${_esc(app.name)}</div>
            <div class="wac-desc">${_esc(app.description)}</div>
            <div class="wac-meta">
              <span class="wac-kind">${isBuiltin ? '内置' : 'OPUS 造'}</span>
              ${meta}
            </div>
          </div>
        </div>
      `;
    }).join('');
    const addCard = `
      <div class="ws-app-card ws-app-add" data-act="ask-opus-app" title="跳到右侧对话 · 直接说想要什么应用">
        <div class="wac-icon">＋</div>
        <div class="wac-body">
          <div class="wac-title">长一个新应用</div>
          <div class="wac-desc">跟右侧 OPUS 说「我想要一个 X 应用」 · OPUS 自己查资料 / 写代码 / 启程序 · 长完落到这里</div>
          <div class="wac-meta"><span class="wac-stage">点这里 → 跳右侧填模板</span></div>
        </div>
      </div>
    `;
    return cards + addCard;
  }

  // ─── 拉远端 apps + flows (mount 后异步) ───
  async function _loadAssetsFromDaemon() {
    const token = _getToken();
    if (!token) return;  // 没 token 静默 · 只显示 builtin
    try {
      const r = await fetch('/workshop/apps', { headers: { 'Authorization': 'Bearer ' + token } });
      if (r.ok) {
        const data = await r.json();
        const opusApps = (data.apps || []).map(a => Object.assign({}, a, { kind: 'opus' }));
        _apps = BUILTIN_APPS.concat(opusApps);
        // 卷四十六续 12 · wish-165ea1f6 phase B · 每次拿到新 app 列表都注册成 LiteGraph node
        _registerAppNodes();
      }
    } catch (e) { /* 静默 · UI 仍能用 builtin */ }
    try {
      const r = await fetch('/workshop/flows', { headers: { 'Authorization': 'Bearer ' + token } });
      if (r.ok) {
        const data = await r.json();
        _flows = data.flows || [];
      }
    } catch (e) { /* 静默 */ }
    _rerenderToolbox();
    // 重渲染应用网格 (sidebar 内列表 · 卷四十六续 11)
    if (_container && _activeTab === 'apps') {
      const grid = _container.querySelector('#wsAppsGrid');
      if (grid) {
        grid.innerHTML = _renderAppCards();
        // 卷四十六续 11 · 保持当前 active app 高亮 (重渲染会丢失)
        if (_activeAppId) {
          const card = grid.querySelector(`.ws-app-card[data-app-id="${_activeAppId}"]`);
          if (card) card.classList.add('active');
        }
      }
      // 没选 app + 主区是空的 → 显示 welcome (新加 app 后即时刷新统计数字)
      if (!_activeAppId) {
        const detail = _container.querySelector('#wsAppDetail');
        if (detail && !detail.querySelector('.ws-ad-head')) {
          detail.innerHTML = _renderAppsMainWelcome();
        }
      }
    }
  }

  // ─── 卷四十六续 11 · 没选应用时主区的 welcome ───
  // sidebar list + main detail 布局 · 没选应用时 main 显示这块引导
  function _renderAppsMainWelcome() {
    const total = _apps.length;
    return `
      <div class="ws-apps-welcome">
        <div class="ws-apps-welcome-icon"><i class="ri-magic-fill"></i></div>
        <h2 class="ws-apps-welcome-title">出品工坊 · 应用</h2>
        <p class="ws-apps-welcome-sub">左侧选一个应用 · 看产物历史 / 配置 / 测试它</p>
        <div class="ws-apps-welcome-stats">
          <span class="wawm-stat"><b>${total}</b> 个应用</span>
          <span class="wawm-stat"><b>${_apps.filter(a => a.kind === 'builtin').length}</b> 个内置</span>
          <span class="wawm-stat"><b>${_apps.filter(a => a.kind === 'opus').length}</b> 个 OPUS 造</span>
        </div>
        <div class="ws-apps-welcome-tips">
          <div class="wawt-row"><i class="ri-lightbulb-fill"></i> 想要新应用 · 点左下「＋ 长一个新应用」 · 跟主对话区 OPUS 说想要什么</div>
          <div class="wawt-row"><i class="ri-flash-fill"></i> 应用多了 · 左上搜索框可以快速过滤</div>
          <div class="wawt-row">« 折叠左侧 · 沉浸看详情 · 鼠标移到 icon 可以看名字</div>
        </div>
      </div>
    `;
  }

  // ─── 应用详情视图 · 卷四十四 K stage 2a ───
  // 复用 GET /dashboard/<domain> 拿历史产物 · stage 2b 加配置 tab · stage 2c 加测试运行
  function _renderAppDetailShell(appId) {
    const app = _apps.find(a => a.id === appId);
    if (!app) return '';
    const kindLabel = app.kind === 'builtin' ? '内置应用' : 'OPUS 造的应用';
    return `
      <div class="ws-ad-head">
        <button class="ws-ad-back" data-act="back-to-apps" title="返回应用列表">← 应用</button>
        <span class="ws-ad-icon">${app.icon || '<i class="ri-puzzle-fill"></i>'}</span>
        <span class="ws-ad-title">${_esc(app.name)}</span>
        <span class="ws-ad-kind">${kindLabel}</span>
        <span class="ws-spacer"></span>
        ${app.kind === 'opus' ? `<button class="ws-btn" data-act="ad-delete" data-app-id="${_esc(app.id)}" title="删除这个 OPUS 造的 app">🗑 删</button>` : ''}
        <button class="ws-btn" data-act="ad-refresh" title="刷新产物">⟳ 刷新</button>
      </div>
      <div class="ws-ad-tabs">
        <button class="ws-ad-tab active" data-ad-tab="output">📁 产出</button>
        ${app.kind === 'opus' ? '<button class="ws-ad-tab" data-ad-tab="detail">📋 详情</button>' : ''}
        <button class="ws-ad-tab" data-ad-tab="config">⚙ 配置</button>
        <button class="ws-ad-tab" data-ad-tab="test"><i class="ri-play-fill"></i> 测试</button>
      </div>
      <div class="ws-ad-pane" data-ad-pane="output">
        <div class="ws-ad-loading"><i class="ri-radar-fill"></i> 拉产出中…</div>
      </div>
      <div class="ws-ad-pane" data-ad-pane="detail" hidden>
        <div class="ws-ad-loading"><i class="ri-radar-fill"></i> 加载中…</div>
      </div>
      <div class="ws-ad-pane" data-ad-pane="config" hidden>
        <div class="ws-ad-stub">
          <div class="ws-stub-icon">⚙</div>
          <h3>应用配置 · stage 2b 上线</h3>
          <p>会有这些槽 (照 Coze bot 编辑器):</p>
          <ul>
            <li><b>人设 / 系统 prompt</b> — markdown 编辑 · 角色/目标/工作流/限制</li>
            <li><b>模型偏好</b> — 用 OPUS 的 provider_configs · 可锁定某 provider/model</li>
            <li><b>技能</b> — 从工具集勾选哪些 atomic/composite 工具可用</li>
            <li><b>知识 (RAG)</b> — 接 data/reports/*.md · 用户画像笔记 · 自填粘贴</li>
            <li><b>记忆</b> — sessions 持续 / 每次重置 / 共享用户画像笔记</li>
          </ul>
          <p class="ws-stub-hint">这些 OPUS 都已经有 · stage 2b 把它们装进 UI 槽位 · stage 2c 把"测试"接 SSE 真跑</p>
        </div>
      </div>
      <div class="ws-ad-pane" data-ad-pane="test" hidden>
        ${_renderAppTestForm(app)}
      </div>
    `;
  }

  // 卷四十六续 12 · wish-165ea1f6 phase A · 渲染 app 的测试表单 (NLP First 路径)
  //   - 有 ui_form_schema 时 · 渲染声明式表单 · 提交后拼 prompt 塞主对话框 (window.injectChat)
  //   - 无 schema 时 · 显示提示 + 一键『让 OPUS 给这个 app 加表单』
  function _renderAppTestForm(app) {
    if (!app) return '';
    const schema = Array.isArray(app.ui_form_schema) ? app.ui_form_schema : [];
    if (!schema.length) {
      return `
        <div class="ws-ad-stub ws-form-empty">
          <div class="ws-stub-icon"><i class="ri-play-fill"></i></div>
          <h3>测试运行 · 这个 app 还没声明 UI 表单</h3>
          <p>声明 <code>ui_form_schema</code> 后 · 这里会出现一张表单 · 你填字段 → 点提交 → 拼成 prompt 塞到右侧对话框。 重复跑同一 app 不用每次打字 (典型场景 SOVITS / GPT-Image)。</p>
          <p class="ws-stub-hint">现在你可以:</p>
          <ul class="ws-form-empty-actions">
            <li>对右侧 OPUS 说: <code>用 update_app 给 ${_esc(app.id)} 加个表单 · 字段是 …</code></li>
            <li>或者继续直接 NLP 调用: <code>用 ${_esc(app.name)} 帮我 …</code></li>
          </ul>
          <button class="ws-btn ws-btn-primary" data-act="ad-suggest-form" data-app-id="${_esc(app.id)}" type="button">
            ✨ 让 OPUS 替我给这个 app 设计表单
          </button>
        </div>
      `;
    }
    const fieldsHtml = schema.map((f, i) => _renderFormField(f, i)).join('');
    return `
      <form class="ws-ad-form" data-app-id="${_esc(app.id)}" data-act="ad-form-submit" novalidate>
        <div class="ws-form-head">
          <span class="ws-form-app-icon">${app.icon || '<i class="ri-puzzle-fill"></i>'}</span>
          <span class="ws-form-app-name">${_esc(app.name)}</span>
          <span class="ws-form-app-desc">${_esc(app.description || '')}</span>
        </div>
        <div class="ws-form-body">
          ${fieldsHtml}
        </div>
        <div class="ws-form-actions">
          <label class="ws-form-autosend">
            <input type="checkbox" data-form-autosend>
            <span>填完直接发送 (走主对话路径时生效)</span>
          </label>
          <button type="button" class="ws-btn" data-act="ad-form-clear" data-app-id="${_esc(app.id)}">清空</button>
          <button type="submit" class="ws-btn" data-form-target="chat" title="拼成 prompt 塞主对话框 · NLP First 路径">
            → 塞主对话框
          </button>
          <button type="submit" class="ws-btn ws-btn-primary" data-form-target="run" title="后端 daemon 直接跑这个 app · SSE 流式输出 · 不污染主对话">
            <i class="ri-play-fill"></i> 后端真跑
          </button>
        </div>
        <div class="ws-form-preview" data-form-preview hidden>
          <div class="ws-form-preview-head">prompt 预览</div>
          <pre class="ws-form-preview-body" data-form-preview-body></pre>
        </div>
        <div class="ws-form-run" data-form-run hidden>
          <div class="ws-form-run-head">
            <span class="ws-form-run-title"><i class="ri-play-fill"></i> 真跑输出</span>
            <span class="ws-form-run-status" data-run-status>等待…</span>
            <span class="ws-spacer"></span>
            <button type="button" class="ws-btn" data-act="ad-form-cancel" data-app-id="${_esc(app.id)}" hidden>取消</button>
          </div>
          <div class="ws-form-run-events" data-run-events></div>
          <div class="ws-form-run-outputs" data-run-outputs hidden>
            <div class="ws-form-preview-head">outputs (给工作流下游用)</div>
            <pre class="ws-form-preview-body" data-run-outputs-body></pre>
          </div>
        </div>
      </form>
    `;
  }

  function _renderFormField(f, i) {
    if (!f || !f.name) return '';
    const fieldId = `ws-f-${i}-${f.name}`;
    const label = _esc(f.label || f.name);
    const required = f.required ? '<span class="ws-form-req">*</span>' : '';
    const help = f.help ? `<div class="ws-form-help">${_esc(f.help)}</div>` : '';
    const def = f.default;
    const reqAttr = f.required ? 'required' : '';
    let control = '';
    if (f.type === 'textarea') {
      const maxAttr = f.max_chars ? `maxlength="${parseInt(f.max_chars, 10)}"` : '';
      control = `<textarea id="${fieldId}" name="${_esc(f.name)}" rows="3" ${reqAttr} ${maxAttr}>${_esc(def == null ? '' : String(def))}</textarea>`;
    } else if (f.type === 'number') {
      const minAttr = (f.min != null) ? `min="${Number(f.min)}"` : '';
      const maxAttr = (f.max != null) ? `max="${Number(f.max)}"` : '';
      control = `<input id="${fieldId}" name="${_esc(f.name)}" type="number" ${reqAttr} ${minAttr} ${maxAttr} value="${def == null ? '' : _esc(String(def))}">`;
    } else if (f.type === 'select') {
      const opts = Array.isArray(f.options) ? f.options : [];
      const optsHtml = opts.map(o => {
        const val = String(o.value == null ? '' : o.value);
        const lbl = _esc(o.label != null ? o.label : val);
        const sel = (def != null && String(def) === val) ? 'selected' : '';
        return `<option value="${_esc(val)}" ${sel}>${lbl}</option>`;
      }).join('');
      control = `<select id="${fieldId}" name="${_esc(f.name)}" ${reqAttr}>${optsHtml}</select>`;
    } else if (f.type === 'boolean') {
      const checked = def ? 'checked' : '';
      control = `<label class="ws-form-bool"><input id="${fieldId}" name="${_esc(f.name)}" type="checkbox" ${checked}><span>${label}</span></label>`;
      return `<div class="ws-form-field ws-form-field-bool" data-field-name="${_esc(f.name)}">${control}${help}</div>`;
    } else if (f.type === 'file') {
      const acceptAttr = f.accept ? `accept="${_esc(f.accept)}"` : '';
      control = `<input id="${fieldId}" name="${_esc(f.name)}" type="file" ${reqAttr} ${acceptAttr}>`;
    } else {
      const maxAttr = f.max_chars ? `maxlength="${parseInt(f.max_chars, 10)}"` : '';
      control = `<input id="${fieldId}" name="${_esc(f.name)}" type="text" ${reqAttr} ${maxAttr} value="${def == null ? '' : _esc(String(def))}">`;
    }
    return `
      <div class="ws-form-field" data-field-name="${_esc(f.name)}" data-field-type="${_esc(f.type || 'text')}">
        <label class="ws-form-label" for="${fieldId}">${label}${required}</label>
        ${control}
        ${help}
      </div>
    `;
  }

  // 把 form 字段拼成自然语言 prompt · 喂给主 OPUS
  // 设计: 走 NLP First 路径 · 跟 BRO 用嘴说调这个 app 完全等价
  function _buildPromptFromForm(app, values) {
    const lines = [
      `请用应用「${app.name}」(${app.id}) 处理我的请求 · 通过表单提供以下输入:`,
      '',
    ];
    const schema = Array.isArray(app.ui_form_schema) ? app.ui_form_schema : [];
    for (const f of schema) {
      const v = values[f.name];
      if (v == null || v === '') continue;
      const labelTxt = f.label || f.name;
      if (f.type === 'textarea') {
        lines.push(`- **${labelTxt}** (${f.name}):`);
        lines.push('  ```');
        String(v).split('\n').forEach(l => lines.push('  ' + l));
        lines.push('  ```');
      } else if (f.type === 'boolean') {
        lines.push(`- **${labelTxt}** (${f.name}): ${v ? '是' : '否'}`);
      } else {
        lines.push(`- **${labelTxt}** (${f.name}): ${v}`);
      }
    }
    if (app.description) {
      lines.push('');
      lines.push(`(应用用途: ${app.description})`);
    }
    return lines.join('\n');
  }

  function _rerenderToolbox() {
    if (!_container) return;
    const tbBody = _container.querySelector('#wsToolbox .ws-tb-body');
    if (!tbBody) return;
    tbBody.innerHTML = `
      ${_renderToolGroup('composite', '<i class="ri-archive-fill"></i> 复合工具 · 生产线模板')}
      ${_renderToolGroup('atomic', '⚛ 原子工具 · 单步动作')}
      ${_renderToolGroup('custom', '✨ 自定义工具 · OPUS 长出来的')}
      <div class="ws-tb-add">
        <button data-act="ask-opus-tool" title="跟右侧 OPUS 说『我想要一个 X 工具』 · OPUS 自己去做">＋ 让 OPUS 长一个新工具</button>
      </div>
    `;
  }

  // 卷五十四 · 孪法第4条 · 画布引擎 (workflow_engine.run_workflow) 目前只实装 opus/app/<aid> 节点。
  // composite/* (生产线模板) 和 atomic/* (单步动作) 还没接执行器·拖进画布跑会被引擎跳过报错 =
  // "UI 有按钮但 NLP 跑不通"。 在真接执行器之前·明标"未实装"+禁拖·不误导 BRO。
  const _UNIMPL_GROUPS = new Set(['composite', 'atomic']);

  function _renderToolGroup(group, label) {
    let items;
    if (group === 'custom') {
      items = _apps
        .filter(a => a && a.id && a.kind !== 'builtin')
        .map(app => [
          'app/' + app.id,
          {
            icon: app.icon || '<i class="ri-puzzle-fill"></i>',
            title: app.name || app.id,
            desc: (app.description || '') + (app.exec_kind === 'scripted'
              ? ' · <i class="ri-flash-fill"></i> scripted (0 LLM 直接 HTTP)'
              : ' · <i class="ri-brain-fill"></i> agentic (LLM session)'),
          },
        ]);
    } else {
      items = Object.entries(TOOL_SPECS).filter(([_, s]) => s.group === group);
    }
    const unimpl = _UNIMPL_GROUPS.has(group);
    const headLabel = unimpl ? `${label} <span class="ws-tg-soon">未实装</span>` : label;
    return `
      <div class="ws-tg" data-group="${group}">
        <div class="ws-tg-head" data-act="toggle-tg">
          <span class="ws-tg-arrow">▾</span>
          <span class="ws-tg-label">${headLabel}</span>
          <span class="ws-tg-count">${items.length}</span>
        </div>
        <div class="ws-tg-body">
          ${items.map(([key, s]) => unimpl
            ? `<div class="ws-tool ws-tool-unimpl" data-act="unimpl-tool" title="${_esc(s.desc)} · 画布执行器还没接这类节点·暂不能拖。目前画布只跑『自定义工具 · OPUS 长出来的』里的应用节点">
                 <span class="ws-tool-ico">${s.icon}</span>
                 <span class="ws-tool-name">${_esc(s.title)}</span>
                 <span class="ws-tool-soon">未实装</span>
               </div>`
            : `<div class="ws-tool" draggable="true" data-tool="${key}" title="${_esc(s.desc)}">
                 <span class="ws-tool-ico">${s.icon}</span>
                 <span class="ws-tool-name">${_esc(s.title)}</span>
               </div>`
          ).join('')}
        </div>
      </div>
    `;
  }

  function _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  // ─── 事件绑定 (用 event delegation · 一根 listener 全包) ───
  let _delegated = null;
  let _searchHandler = null;
  let _appsFilterHandler = null;  // 卷四十六续 11 · sidebar 内应用搜索
  let _dragHandler = null;
  let _dragOverHandler = null;
  let _dropHandler = null;

  // 卷四十六续 11 · 应用 sidebar 折叠态切换 · localStorage 持久化
  function _toggleAppsSidebar() {
    const sidebar = _container.querySelector('#wsAppsSidebar');
    if (!sidebar) return;
    const next = !sidebar.classList.contains('collapsed');
    _setAppsSidebarCollapsed(next);
    try { localStorage.setItem('ws.apps.sidebar.collapsed', next ? '1' : '0'); } catch (e) {}
  }
  function _setAppsSidebarCollapsed(collapsed) {
    const sidebar = _container.querySelector('#wsAppsSidebar');
    if (!sidebar) return;
    sidebar.classList.toggle('collapsed', collapsed);
    // 卷四十六续 11 补丁 · 折叠态下复用同一个按钮 · 文字 + title 切换 (BRO 觉得外侧 » 多余)
    const btn = sidebar.querySelector('.wash-collapse');
    if (btn) {
      btn.textContent = collapsed ? '»' : '«';
      btn.title = collapsed ? '展开应用列表' : '折叠应用列表 (留 icon)';
    }
  }

  function _bindEvents() {
    _delegated = (e) => {
      const tgt = e.target.closest('[data-act]');
      if (!tgt || !_container.contains(tgt)) return;
      const act = tgt.dataset.act;
      // ── 卷四十四 K stage 2a · tabs / apps / app detail 路由 ──
      if (act === 'switch-tab') _switchTab(tgt.dataset.tab);
      else if (act === 'open-app') _showAppDetail(tgt.dataset.appId);
      else if (act === 'back-to-apps') _hideAppDetail();
      else if (act === 'ad-refresh') _activeAppId && _loadAppOutputs(_activeAppId, true);
      else if (act === 'preview-workshop') {
        const domain = tgt.dataset.domain;
        const name = tgt.dataset.name;
        if (domain && name) {
          const card = tgt.closest('.ws-ad-card');
          if (card) _previewWorkshopInline(domain, name, card);
        }
      }
      else if (act === 'ad-delete') _onDeleteApp(tgt.dataset.appId);
      // 卷四十六续 12 · wish-165ea1f6 phase A/B · 应用测试表单
      else if (act === 'ad-form-clear') _onAppFormClear(tgt.dataset.appId);
      else if (act === 'ad-suggest-form') _onAskOpusDesignForm(tgt.dataset.appId);
      else if (act === 'ad-form-cancel') _onAppFormCancel(tgt.dataset.appId);
      // 卷四十四 K stage 2c++ · wish-6fd76512 · 卡片右上角 🗑 软删 · stopPropagation 不打开详情
      else if (act === 'app-delete-card') { e.stopPropagation(); _onDeleteApp(tgt.dataset.appId); }
      // 卷四十四 K stage 2c++ · wish-6fd76512 · 回收站操作
      else if (act === 'trash-refresh') _loadTrashFromDaemon(true);
      else if (act === 'trash-restore') _onRestoreFromTrash(tgt.dataset.trashId);
      else if (act === 'trash-empty-one') _onEmptyTrashOne(tgt.dataset.trashId);
      else if (act === 'trash-empty-all') _onEmptyTrashAll();
      // 卷四十四 K stage 2b · ＋ 卡 / ＋ 工具 → focus 右侧主 chat 预填模板 (NLP First 闭环)
      else if (act === 'ask-opus-app') _askOpusInChat('app');
      else if (act === 'ask-opus-tool') _askOpusInChat('tool');
      // 卷四十六续 11 · sidebar 折叠 (« 收 / » 展)
      else if (act === 'toggle-apps-sidebar') _toggleAppsSidebar();
      // ── 卷四十四 K stage 1b · canvas 工具集 + 节点编辑 ──
      else if (act === 'hide-tb') _toggleToolbox(true);
      else if (act === 'unimpl-tool') _toast('这类节点 (复合/原子) 画布执行器还没实装 · 暂不能拖到画布。目前画布只能跑「自定义工具 · OPUS 长出来的」里的应用节点 · 想要它跑就先让 OPUS 把它做成一个 app');
      else if (act === 'toggle-tg') tgt.parentElement.classList.toggle('collapsed');
      else if (act === 'run') _onRun();
      else if (act === 'save') _onSave();
      else if (act === 'load') _onLoad();
      else if (act === 'clear') _onClear();
      else if (act === 'lang') _toggleLang();
    };
    _container.addEventListener('click', _delegated);

    // 应用详情内 tab 切换 (.ws-ad-tab) · 跟外层 .ws-tab 区分开 · 不混 data-act
    _container.addEventListener('click', (e) => {
      const adTab = e.target.closest('.ws-ad-tab');
      if (adTab && _container.contains(adTab)) _switchAppDetailTab(adTab.dataset.adTab);
    });

    // 卷四十六续 12 · wish-165ea1f6 phase A/B · 应用测试表单 submit
    _container.addEventListener('submit', (e) => {
      const form = e.target.closest('form[data-act="ad-form-submit"]');
      if (form && _container.contains(form)) {
        e.preventDefault();
        const target = (e.submitter && e.submitter.dataset && e.submitter.dataset.formTarget) || 'chat';
        _onAppFormSubmit(form, target);
      }
    });

    const showBtn = _container.querySelector('#wsToolboxShow');
    showBtn.addEventListener('click', () => _toggleToolbox(false));

    const searchInput = _container.querySelector('#wsToolboxSearch');
    _searchHandler = (e) => {
      const q = e.target.value.toLowerCase().trim();
      _container.querySelectorAll('.ws-tool').forEach(el => {
        if (!q) { el.style.display = ''; return; }
        const text = el.textContent.toLowerCase();
        el.style.display = text.includes(q) ? '' : 'none';
      });
    };
    searchInput.addEventListener('input', _searchHandler);

    // 卷四十六续 11 · sidebar 应用搜索 (跟 toolbox 同样用 textContent.includes)
    const appsFilterInput = _container.querySelector('#wsAppsSideFilter');
    if (appsFilterInput) {
      _appsFilterHandler = (e) => {
        const q = e.target.value.toLowerCase().trim();
        const grid = _container.querySelector('#wsAppsGrid');
        if (!grid) return;
        grid.querySelectorAll('.ws-app-card').forEach(el => {
          if (!q) { el.style.display = ''; return; }
          // "+ 长一个新应用" 卡 (ws-app-add) 也参与过滤 · q 为空才显示
          const text = el.textContent.toLowerCase();
          el.style.display = text.includes(q) ? '' : 'none';
        });
      };
      appsFilterInput.addEventListener('input', _appsFilterHandler);
    }
    // 卷四十六续 11 · 启动时按 localStorage 还原 sidebar 折叠态
    try {
      if (localStorage.getItem('ws.apps.sidebar.collapsed') === '1') {
        _setAppsSidebarCollapsed(true);
      }
    } catch (e) { /* localStorage 可能不可用 · 忽略 */ }

    _dragHandler = (e) => {
      const el = e.target.closest('.ws-tool[draggable="true"]');
      if (!el) return;
      el.classList.add('dragging');
      e.dataTransfer.setData('text/opus-tool', el.dataset.tool);
      e.dataTransfer.effectAllowed = 'copy';
    };
    _container.addEventListener('dragstart', _dragHandler);
    _container.addEventListener('dragend', (e) => {
      const el = e.target.closest('.ws-tool');
      if (el) el.classList.remove('dragging');
    });

    _dragOverHandler = (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
    };
    _dropHandler = (e) => {
      e.preventDefault();
      const toolKey = e.dataTransfer.getData('text/opus-tool');
      if (!toolKey) return;
      const isAppNode = toolKey.startsWith('app/');
      if (!isAppNode && !TOOL_SPECS[toolKey]) return;
      const rect = _canvasEl.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const gx = (sx - _canvas.ds.offset[0]) / _canvas.ds.scale;
      const gy = (sy - _canvas.ds.offset[1]) / _canvas.ds.scale;
      const node = LiteGraph.createNode('opus/' + toolKey);
      if (!node) {
        if (isAppNode) {
          _toast('opus/' + toolKey + ' 节点未注册 · 试试刷新页面或重启 daemon');
        }
        return;
      }
      node.pos = [gx - 100, gy - 16];
      _graph.add(node);
      _updateEmpty();
    };
    _canvasEl.addEventListener('dragover', _dragOverHandler);
    _canvasEl.addEventListener('drop', _dropHandler);

    _onResize = () => _renderCanvas();
    window.addEventListener('resize', _onResize);
  }

  function _unbindEvents() {
    if (_container && _delegated) _container.removeEventListener('click', _delegated);
    if (_canvasEl && _dragOverHandler) _canvasEl.removeEventListener('dragover', _dragOverHandler);
    if (_canvasEl && _dropHandler) _canvasEl.removeEventListener('drop', _dropHandler);
    if (_onResize) window.removeEventListener('resize', _onResize);
    _delegated = _searchHandler = _dragHandler = _dragOverHandler = _dropHandler = _onResize = null;
  }

  // ─── canvas 重绘 ───
  function _renderCanvas() {
    if (!_canvasEl || !_canvasWrap) return;
    const w = _canvasWrap.clientWidth;
    const h = _canvasWrap.clientHeight - 36;  // 减 toolbar
    if (w <= 0 || h <= 0) return;
    _canvasEl.width = w;
    _canvasEl.height = h;
    _canvas.draw(true, true);
  }

  function _updateEmpty() {
    const empty = _container.querySelector('#wsCanvasEmpty');
    if (!empty) return;
    empty.hidden = _graph._nodes.length > 0;
  }

  function _toggleToolbox(collapse) {
    const view = _container.querySelector('.workshop-view');
    const showBtn = _container.querySelector('#wsToolboxShow');
    view.dataset.tbCollapsed = collapse ? '1' : '0';
    showBtn.hidden = !collapse;
    requestAnimationFrame(_renderCanvas);
  }

  function _toggleLang() {
    _menuLang = _menuLang === 'zh' ? 'en' : 'zh';
    localStorage.setItem('opus_workshop_lang', _menuLang);
    const btn = _container.querySelector('#wsLangBtn');
    if (btn) btn.textContent = _menuLang === 'zh' ? '中' : 'EN';
  }

  // ─── tabs 切换 (<i class="ri-archive-fill"></i> 应用 / ⚛ 工作流 / 🗑 回收站) ───
  function _switchTab(tab) {
    if (!['apps', 'canvas', 'trash'].includes(tab)) return;
    _activeTab = tab;
    localStorage.setItem('opus_workshop_tab', tab);
    const view = _container.querySelector('.workshop-view');
    if (view) view.dataset.tab = tab;
    _container.querySelectorAll('.ws-tab').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
    // 切回 canvas tab 时 · canvas 之前可能 0×0 · 触发 redraw
    if (tab === 'canvas') requestAnimationFrame(_renderCanvas);
    // 卷四十四 K stage 2c++ · wish-6fd76512 · 切到 trash tab 时 lazy load
    if (tab === 'trash') _loadTrashFromDaemon();
  }

  // ─── 应用详情 · 卷四十六续 11 · sidebar 高亮 + main 渲染 (不再 hidden 切换) ───
  function _showAppDetail(appId) {
    const app = _apps.find(a => a.id === appId);
    if (!app) return;
    _activeAppId = appId;
    const sidebar = _container.querySelector('#wsAppsSidebar');
    const detail = _container.querySelector('#wsAppDetail');
    if (!sidebar || !detail) return;
    // 高亮 sidebar 内 active app · 移除其他卡的 active
    sidebar.querySelectorAll('.ws-app-card.active').forEach(el => el.classList.remove('active'));
    const activeCard = sidebar.querySelector(`.ws-app-card[data-app-id="${appId}"]`);
    if (activeCard) {
      activeCard.classList.add('active');
      // 应用多时滚到可见 (折叠态下 sidebar 也滚)
      activeCard.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
    detail.innerHTML = _renderAppDetailShell(appId);
    _loadAppOutputs(appId, false);
  }

  function _hideAppDetail() {
    _activeAppId = null;
    const sidebar = _container.querySelector('#wsAppsSidebar');
    const detail = _container.querySelector('#wsAppDetail');
    if (!sidebar || !detail) return;
    sidebar.querySelectorAll('.ws-app-card.active').forEach(el => el.classList.remove('active'));
    detail.innerHTML = _renderAppsMainWelcome();
  }

  function _switchAppDetailTab(tabName) {
    _container.querySelectorAll('.ws-ad-tab').forEach(b => b.classList.toggle('active', b.dataset.adTab === tabName));
    _container.querySelectorAll('.ws-ad-pane').forEach(p => { p.hidden = p.dataset.adPane !== tabName; });
    // opus app · 切到配置 tab 时动态加载系统提示词
    if (tabName === 'detail' && _activeAppId) {
      const app = _apps.find(a => a.id === _activeAppId);
      if (app && app.kind === 'opus') {
        const pane = _container.querySelector('.ws-ad-pane[data-ad-pane="detail"]');
        if (pane && !pane.dataset.loaded) {
          pane.innerHTML = _renderOpusAppConfigHTML(app);
          pane.dataset.loaded = '1';
        }
      }
    }
  }

  // ─── 拉应用历史产物 ───
  // builtin app: GET /dashboard/<domain>
  // opus 造的 app: 暂时显示 stub (system_prompt + 工具白名单 + 推荐模型) · 产物历史留 stage 2d
  async function _loadAppOutputs(appId, refresh) {
    const app = _apps.find(a => a.id === appId);
    if (!app) return;
    const pane = _container.querySelector('.ws-ad-pane[data-ad-pane="output"]');
    if (!pane) return;

    if (app.kind === 'opus') {
      const token2 = _getToken();
      if (!token2) {
        pane.innerHTML = '<div class="ws-ad-error">需要 token · 右上角 ⚙ 设置里填一下</div>';
        return;
      }
      pane.innerHTML = '<div class="ws-ad-loading"><i class="ri-radar-fill"></i> 拉产出中…</div>';
      try {
        const r2 = await fetch(`/workshop/outputs-list/${encodeURIComponent(appId)}`, {
          headers: { 'Authorization': 'Bearer ' + token2 },
        });
        if (!r2.ok) {
          pane.innerHTML = `<div class="ws-ad-error">加载产出失败 [${r2.status}]</div>`;
          return;
        }
        const outData = await r2.json();
        pane.innerHTML = _renderOpusOutputsHTML(app, outData);
      } catch (e2) {
        pane.innerHTML = `<div class="ws-ad-error">网络出错: ${_esc(e2.message)}</div>`;
      }
      return;
    }
    if (!app.dashboard_domain) {
      pane.innerHTML = '<div class="ws-ad-error">这个 app 没接 dashboard_domain</div>';
      return;
    }
    pane.innerHTML = '<div class="ws-ad-loading"><i class="ri-radar-fill"></i> 拉历史产物中…</div>';
    const token = _getToken();
    if (!token) {
      pane.innerHTML = '<div class="ws-ad-error">需要 token · 右上角 ⚙ 设置里填一下</div>';
      return;
    }
    const qs = refresh ? '?refresh=true' : '';
    try {
      const r = await fetch(`/dashboard/${app.dashboard_domain}${qs}`, {
        headers: { 'Authorization': 'Bearer ' + token },
      });
      if (!r.ok) {
        pane.innerHTML = `<div class="ws-ad-error">加载失败 [${r.status}]</div>`;
        return;
      }
      const data = await r.json();
      pane.innerHTML = _renderAppOutputsHTML(data, app.dashboard_domain || '');
    } catch (e) {
      pane.innerHTML = `<div class="ws-ad-error">网络出错: ${_esc(e.message)}</div>`;
    }
  }

  // 卷四十六续 11 补丁 · BRO 反馈: 外框冗余 / 不自适应 / 系统提示词 markdown 没渲染
  // 改造: 撤掉 max-width:580px auto · 用 padding 撑满 main 宽度
  //       用 window.opusMdRender 真渲染 system_prompt (chat.js 那套表格/代码块/标题全套支持)
  //       metadata (工具 / 模型 / 时间 / 调用) 压成 chip 行 · 不再一项一行
  function _renderOpusAppConfigHTML(app) {
    const tools = (app.tools && app.tools.length)
      ? app.tools.map(t => `<code>${_esc(t)}</code>`).join(' ')
      : '<i>(全部 OPUS 工具都可用)</i>';
    const promptPreview = (app.system_prompt || '').trim();
    const mdRender = window.opusMdRender || ((t) => `<pre>${_esc(t)}</pre>`);
    const promptHtml = promptPreview
      ? `<div class="ws-app-md">${mdRender(promptPreview)}</div>`
      : '<div class="ws-app-empty">(未配置系统提示词)</div>';
    const descHtml = app.description
      ? `<div class="ws-app-desc">${_esc(app.description)}</div>`
      : '';
    return `
      <div class="ws-app-stub">
        ${descHtml}
        <div class="ws-app-meta-chips">
          <span class="wamc-chip" title="推荐模型"><i class="ri-brain-fill"></i> ${app.model_hint ? `<code>${_esc(app.model_hint)}</code>` : '<i>默认</i>'}</span>
          <span class="wamc-chip" title="创建时间">🕐 ${_esc(app.created_at || '—')}</span>
          <span class="wamc-chip" title="调用次数"><i class="ri-play-fill"></i> ${Number(app.runs || 0)} 次</span>
        </div>
        <div class="ws-app-section">
          <div class="ws-app-section-head"><i class="ri-draft-fill"></i> 系统提示词</div>
          ${promptHtml}
        </div>
        <div class="ws-app-section">
          <div class="ws-app-section-head">🧰 工具白名单</div>
          <div class="ws-app-tools">${tools}</div>
        </div>
        <div class="ws-app-hint">stage 2d 上线后这里会有产物历史 · 现在跟主 OPUS 说「用 ${_esc(app.name)} 风格做 X」 · OPUS 调对应工具落产物</div>
      </div>
    `;
  }

  function _renderAppOutputsHTML(data, domain) {
    if (data && data.error) return `<div class="ws-ad-error">${_esc(data.error)}</div>`;
    const items = data.items || [];
    const kinds = data.kinds || [];
    const dir = data.directory || '';
    let html = '';
    if (kinds.length > 0) {
      html += `<div class="ws-ad-kinds"><span class="wkk-label">细分:</span>${kinds.map(k => `<span class="wkk-chip">${_esc(k)}</span>`).join('')}</div>`;
    }
    html += `<div class="ws-ad-meta">${items.length} 份产出 · ${_esc(dir)}</div>`;
    if (items.length === 0) {
      html += `<div class="ws-ad-empty">${_esc(data.empty_hint || '工坊还空 · 跟右侧 OPUS 说「做一份 X」 · OPUS 调 draft_studio 工具落 markdown')}</div>`;
      return html;
    }
    html += '<div class="ws-ad-list">';
    for (const it of items) {
      const kind = it.kind || '';
      const kindBadge = kind ? `<span class="ws-ad-kind">${_esc(kind)}</span>` : '';
      const path = it.path || '';
      const created = it.created_at || it.mtime || '';
      const size = it.size || '';
      html += `
        <div class="ws-ad-card">
          <div class="ws-ad-c-head">
            <span class="ws-ad-c-title">${_esc(it.title || it.name || '(无标题)')}</span>
            ${kindBadge}
          </div>
          <div class="ws-ad-c-meta">
            ${created ? `<span>${_esc(created)}</span>` : ''}
            ${size ? `<span>${_esc(size)}</span>` : ''}
            ${path ? `<span class="ws-ad-c-path">${_esc(path)}</span>` : ''}
          </div>
          ${it.summary ? `<div class="ws-ad-c-summary">${_esc(it.summary).slice(0, 240)}</div>` : ''}
          <div class="ws-ad-c-actions">
            <button class="ws-btn ws-btn-sm" data-act="preview-workshop" data-domain="${_esc(domain || '')}" data-name="${_esc(it.name || '')}">📖 预览</button>
          </div>
          <div class="ws-ad-c-preview" data-preview="${_esc(it.name || '')}" hidden></div>
        </div>`;
    }
    html += '</div>';
    return html;
  }

  // 卷四十四 K stage 2b · NLP First 闭环 · ＋ 卡片不打开新 UI · 直接焦点到主 chat + 预填模板
  function _renderOpusOutputsHTML(app, data) {
  const files = data.files || [];
  if (files.length === 0) {
    return `<div class="ws-ad-empty">
      <div style="font-size:32px;margin-bottom:12px">📁</div>
      <div>还没有产出</div>
      <div class="ws-ad-hint">去「▶ 测试」tab 跑一次 ${_esc(app.name || app.id)} · 产物会出现在这里</div>
    </div>`;
  }
  let html = `<div class="ws-ad-meta">${files.length} 个文件</div>`;
  html += '<div class="ws-output-gallery">';
  for (const f of files) {
    const fname = _esc(f.name || '');
    const furl = _esc(f.url || '');
    const fsize = f.size ? (f.size / 1024).toFixed(0) + 'KB' : '';
    if (f.type === 'image') {
      html += `
        <div class="ws-gallery-card" onclick="window._openLightbox('${furl}', '${fname}')">
          <img src="${furl}" alt="${fname}" loading="lazy" class="ws-gallery-img">
          <div class="ws-gallery-info">
            <span class="ws-gallery-name" title="${fname}">${fname}</span>
            <span class="ws-gallery-size">${fsize}</span>
          </div>
        </div>`;
    } else if (f.type === 'audio') {
      html += `
        <div class="ws-gallery-card ws-gallery-audio">
          <div class="ws-gallery-icon">🎵</div>
          <audio controls src="${furl}" class="ws-gallery-player"></audio>
          <div class="ws-gallery-info">
            <span class="ws-gallery-name">${fname}</span>
            <span class="ws-gallery-size">${fsize}</span>
          </div>
        </div>`;
    } else if (f.type === 'video') {
      html += `
        <div class="ws-gallery-card ws-gallery-video">
          <div class="ws-gallery-icon">🎬</div>
          <video controls src="${furl}" class="ws-gallery-player"></video>
          <div class="ws-gallery-info">
            <span class="ws-gallery-name">${fname}</span>
            <span class="ws-gallery-size">${fsize}</span>
          </div>
        </div>`;
    } else {
      html += `
        <div class="ws-gallery-card ws-gallery-other">
          <div class="ws-gallery-icon">📄</div>
          <div class="ws-gallery-info">
            <span class="ws-gallery-name">${fname}</span>
            <span class="ws-gallery-size">${fsize}</span>
          </div>
        </div>`;
    }
  }
  html += '</div>';
  return html;
}

// 工坊内 markdown 预览 · 内嵌展开
async function _previewWorkshopInline(domain, name, cardEl) {
  const previewEl = cardEl.querySelector('.ws-ad-c-preview');
  if (!previewEl) return;
  // 如果已经展开 · 收起
  if (!previewEl.hidden) {
    previewEl.hidden = true;
    previewEl.innerHTML = '';
    return;
  }
  const token = _getToken();
  if (!token) { _toast('需要 token'); return; }
  previewEl.hidden = false;
  previewEl.innerHTML = '<div class="ws-ad-loading">加载预览中…</div>';
  try {
    const r = await fetch(`/workshop/preview/${encodeURIComponent(domain)}/${encodeURIComponent(name)}`, {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) {
      previewEl.innerHTML = `<div class="ws-ad-error">预览失败 [${r.status}]</div>`;
      return;
    }
    const data = await r.json();
    const mdRender = window.opusMdRender || ((t) => `<pre>${_esc(t)}</pre>`);
    previewEl.innerHTML = `<div class="ws-ad-preview-body"><div class="ws-ad-preview-md">${mdRender(data.markdown || '')}</div></div>`;
    previewEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  } catch (e) {
    previewEl.innerHTML = `<div class="ws-ad-error">网络出错: ${_esc(e.message)}</div>`;
  }
}



// 图片 lightbox 预览
function _openLightbox(url, name) {
  let lb = document.getElementById('ws-lightbox');
  if (!lb) {
    lb = document.createElement('div');
    lb.id = 'ws-lightbox';
    lb.className = 'ws-lightbox';
    lb.innerHTML = '<div class="ws-lightbox-bg" onclick="_closeLightbox()"></div><div class="ws-lightbox-body"><button class="ws-lightbox-close" onclick="_closeLightbox()">✕</button><img class="ws-lightbox-img" src="" alt=""><div class="ws-lightbox-name"></div></div>';
    document.body.appendChild(lb);
  }
  lb.querySelector('.ws-lightbox-img').src = url;
  lb.querySelector('.ws-lightbox-name').textContent = name || '';
  lb.classList.add('active');
  document.body.style.overflow = 'hidden';
}
function _closeLightbox() {
  const lb = document.getElementById('ws-lightbox');
  if (lb) { lb.classList.remove('active'); document.body.style.overflow = ''; }
}
window._openLightbox = _openLightbox;
window._closeLightbox = _closeLightbox;

function _askOpusInChat(kind) {
    const tpl = kind === 'app'
      ? '我想要一个 ___ 应用 · 功能是 ___ · 检索本地是否有现成的可调用 (例如 ___) · 没有就写代码 / 启程序 / 装依赖 · 完成后注册到工坊里给我看'
      : '我想要一个 ___ 工具 (单步动作 · 不是完整应用) · 功能是 ___ · 写到 agent_tools/<name>.py · 注册成工具集里能拖的节点';
    const $input = document.getElementById('input');
    if (!$input) {
      _toast('找不到主对话输入框 · 你可以直接跟右侧 OPUS 说想要的应用 / 工具');
      return;
    }
    $input.value = tpl;
    $input.focus();
    // 把光标停到第一个 ___ 处方便 BRO 直接打字
    const idx = tpl.indexOf('___');
    if (idx >= 0) {
      try { $input.setSelectionRange(idx, idx + 3); } catch (e) {}
    }
    // 卷三十六 textarea 自适应高度的逻辑跟 chat.js 一样 · 触发 input event 让它撑开
    $input.dispatchEvent(new Event('input', { bubbles: true }));
  }

  // ─── 卷四十六续 12 · wish-165ea1f6 phase A/B · app 测试 form 提交逻辑 ───
  // target='chat' → NLP First 路径 (拼 prompt 塞主对话框 · phase A)
  // target='run'  → 后端 SSE 真跑 (phase B · /workshop/apps/{aid}/run)
  function _onAppFormSubmit(form, target) {
    target = target || 'chat';
    if (!form) return;
    const appId = form.dataset.appId;
    const app = _apps.find(a => a.id === appId);
    if (!app) {
      _toast('找不到 app · 刷新一下应用列表试试');
      return;
    }
    const collected = _collectFormValues(form, app);
    if (collected.missing.length) {
      _toast('❌ 必填项缺失:\n  - ' + collected.missing.join('\n  - '));
      return;
    }
    const values = collected.values;

    const previewBox = form.querySelector('[data-form-preview]');
    const previewBody = form.querySelector('[data-form-preview-body]');
    if (previewBox && previewBody) {
      previewBody.textContent = _buildPromptFromForm(app, values);
      previewBox.hidden = false;
    }

    if (target === 'run') {
      _runAppViaDaemon(form, app, values);
      return;
    }

    const prompt = _buildPromptFromForm(app, values);
    const autosendCb = form.querySelector('[data-form-autosend]');
    const autosend = !!(autosendCb && autosendCb.checked);

    if (typeof window.injectChat === 'function') {
      window.injectChat(prompt, { autosend });
      _toast(autosend
        ? `<i class="ri-play-fill"></i> 已发送 · 主对话区已用「${app.name}」处理`
        : `→ 已塞到主对话框 · 看一眼按 Enter`);
    } else {
      _toast('找不到主对话输入框 · 复制下面的 prompt 自己粘:\n\n' + prompt.slice(0, 400));
    }
  }

  function _collectFormValues(form, app) {
    const schema = Array.isArray(app.ui_form_schema) ? app.ui_form_schema : [];
    const values = {};
    const missing = [];
    for (const f of schema) {
      const el = form.querySelector(`[name="${CSS.escape(f.name)}"]`);
      if (!el) continue;
      let v;
      if (f.type === 'boolean') {
        v = !!el.checked;
      } else if (f.type === 'number') {
        v = el.value === '' ? '' : Number(el.value);
        if (el.value !== '' && Number.isNaN(v)) {
          missing.push(`「${f.label || f.name}」不是合法数字`);
          continue;
        }
      } else if (f.type === 'file') {
        const file = el.files && el.files[0];
        v = file ? file.name : '';
      } else {
        v = (el.value || '').trim();
      }
      if (f.required) {
        const blank = (v === '' || v == null || (f.type === 'boolean' && v === false));
        if (blank) missing.push(`「${f.label || f.name}」必填`);
      }
      values[f.name] = v;
    }
    return { values, missing };
  }

  // 卷四十六续 12 · wish-165ea1f6 phase B · 后端真跑 (SSE 流式)
  // 复用 _activeRuns map 让取消按钮能 abort
  const _activeRuns = new Map();  // appId → AbortController

  const _IMG_EXT = ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg'];
  const _AUDIO_EXT = ['.wav', '.mp3', '.ogg', '.flac', '.m4a'];
  const _VIDEO_EXT = ['.mp4', '.webm', '.mov'];

  function _mediaKindOf(url) {
    if (typeof url !== 'string' || !url) return null;
    const low = url.toLowerCase().split('?')[0];
    if (_IMG_EXT.some(e => low.endsWith(e))) return 'image';
    if (_AUDIO_EXT.some(e => low.endsWith(e))) return 'audio';
    if (_VIDEO_EXT.some(e => low.endsWith(e))) return 'video';
    return null;
  }

  function _renderRunOutputs(box, outputs, app) {
    box.innerHTML = '';
    if (!outputs || typeof outputs !== 'object') {
      box.textContent = JSON.stringify(outputs);
      return;
    }
    const mediaBox = document.createElement('div');
    mediaBox.className = 'ws-run-media';
    let mediaCount = 0;

    for (const [k, v] of Object.entries(outputs)) {
      if (k.startsWith('_')) continue;
      const kind = _mediaKindOf(v);
      if (!kind) continue;
      mediaCount += 1;
      const wrap = document.createElement('div');
      wrap.className = 'ws-run-media-item';
      const label = document.createElement('div');
      label.className = 'ws-run-media-label';
      label.textContent = `${k}:`;
      wrap.appendChild(label);
      if (kind === 'image') {
        const img = document.createElement('img');
        img.src = v;
        img.alt = k;
        img.loading = 'lazy';
        img.className = 'ws-run-media-img';
        wrap.appendChild(img);
      } else if (kind === 'audio') {
        const au = document.createElement('audio');
        au.src = v;
        au.controls = true;
        au.preload = 'metadata';
        wrap.appendChild(au);
      } else if (kind === 'video') {
        const vd = document.createElement('video');
        vd.src = v;
        vd.controls = true;
        vd.preload = 'metadata';
        vd.className = 'ws-run-media-video';
        wrap.appendChild(vd);
      }
      const link = document.createElement('a');
      link.href = v;
      link.target = '_blank';
      link.rel = 'noopener';
      link.className = 'ws-run-media-link';
      link.textContent = '↗ ' + v;
      wrap.appendChild(link);
      mediaBox.appendChild(wrap);
    }
    if (mediaCount > 0) {
      box.appendChild(mediaBox);
    }

    const jsonView = document.createElement('pre');
    jsonView.className = 'ws-run-outputs-json';
    const clean = Object.fromEntries(Object.entries(outputs).filter(([k]) => !k.startsWith('_')));
    jsonView.textContent = JSON.stringify(clean, null, 2);
    box.appendChild(jsonView);
  }

  async function _runAppViaDaemon(form, app, values) {
    const token = _getToken();
    if (!token) {
      _toast('需要 OPUS_API_TOKEN · 设置里填 · 这次跑不了');
      return;
    }
    const runBox = form.querySelector('[data-form-run]');
    const eventsBox = form.querySelector('[data-run-events]');
    const statusBox = form.querySelector('[data-run-status]');
    const cancelBtn = form.querySelector('[data-act="ad-form-cancel"]');
    const outputsBox = form.querySelector('[data-run-outputs]');
    const outputsBody = form.querySelector('[data-run-outputs-body]');

    if (!runBox || !eventsBox) {
      _toast('UI 渲染缺位 · 刷新页面重试');
      return;
    }

    runBox.hidden = false;
    eventsBox.innerHTML = '';
    if (statusBox) statusBox.textContent = '连接中…';
    if (cancelBtn) cancelBtn.hidden = false;
    if (outputsBox) outputsBox.hidden = true;

    const prev = _activeRuns.get(app.id);
    if (prev) try { prev.abort(); } catch (e) {}

    const controller = new AbortController();
    _activeRuns.set(app.id, controller);

    const appendEvent = (kind, text, cls) => {
      const row = document.createElement('div');
      row.className = 'ws-form-run-event' + (cls ? ' ws-fre-' + cls : '');
      const ts = new Date();
      const hm = `${String(ts.getHours()).padStart(2,'0')}:${String(ts.getMinutes()).padStart(2,'0')}:${String(ts.getSeconds()).padStart(2,'0')}`;
      row.innerHTML = `<span class="ws-fre-ts">${hm}</span><span class="ws-fre-kind">${_esc(kind)}</span><span class="ws-fre-text">${_esc(text)}</span>`;
      eventsBox.appendChild(row);
      eventsBox.scrollTop = eventsBox.scrollHeight;
    };

    let resp;
    try {
      resp = await fetch(`/workshop/apps/${encodeURIComponent(app.id)}/run`, {
        method: 'POST',
        signal: controller.signal,
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + token,
        },
        body: JSON.stringify({ inputs: values }),
      });
    } catch (e) {
      if (statusBox) statusBox.textContent = '连接失败';
      appendEvent('error', String(e), 'err');
      if (cancelBtn) cancelBtn.hidden = true;
      _activeRuns.delete(app.id);
      return;
    }

    if (!resp.ok || !resp.body) {
      const txt = resp.body ? await resp.text() : '(无 body)';
      if (statusBox) statusBox.textContent = `HTTP ${resp.status}`;
      appendEvent('error', `HTTP ${resp.status} · ${txt.slice(0, 300)}`, 'err');
      if (cancelBtn) cancelBtn.hidden = true;
      _activeRuns.delete(app.id);
      return;
    }

    if (statusBox) statusBox.textContent = '跑动中…';

    const reader = resp.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    const parseEvents = (chunk) => {
      buffer += chunk;
      const out = [];
      let idx;
      while ((idx = buffer.indexOf('\n\n')) >= 0) {
        const raw = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        const lines = raw.split('\n');
        let evt = 'message';
        let data = '';
        for (const ln of lines) {
          if (ln.startsWith(':')) continue;
          if (ln.startsWith('event:')) evt = ln.slice(6).trim();
          else if (ln.startsWith('data:')) data += ln.slice(5).trim();
        }
        if (data) out.push({ evt, data });
      }
      return out;
    };

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value, { stream: true });
        for (const { evt, data } of parseEvents(chunk)) {
          let payload = null;
          try { payload = JSON.parse(data); } catch (e) { payload = { raw: data }; }
          if (evt === 'hello') {
            const tag = payload.exec_kind === 'scripted' ? '<i class="ri-flash-fill"></i> scripted' : '<i class="ri-brain-fill"></i> agentic';
            appendEvent('hello', `${tag} · run ${payload.run_id || ''}`);
          } else if (evt === 'app_run_start') {
            appendEvent('start', `app 启动 · 工具白名单 ${(payload.tools || []).length} 个`);
          } else if (evt === 'assistant_text') {
            appendEvent('LLM', (payload.text || '').slice(0, 400), 'llm');
          } else if (evt === 'tool_call') {
            appendEvent('<i class="ri-tools-fill"></i> ' + (payload.name || '?'), payload.summary || '', 'tool');
          } else if (evt === 'tool_result') {
            const ok = payload.ok === false ? '<i class="ri-close-fill"></i>' : '<i class="ri-check-fill"></i>';
            appendEvent(ok + ' ' + (payload.name || '?'),
              (payload.preview || payload.error || '').slice(0, 300),
              payload.ok === false ? 'err' : 'tool-ok');
          } else if (evt === 'usage') {
            appendEvent('usage',
              `in ${payload.input_tokens || 0} · out ${payload.output_tokens || 0} · cache ${payload.cache_read_tokens || 0}`);
          } else if (evt === 'app_run_done') {
            appendEvent('done', `iter=${payload.iterations}`);
          } else if (evt === 'http_request') {
            appendEvent('→ HTTP', `${payload.method || '?'} ${(payload.url || '').slice(0, 120)}${payload.when && payload.when !== 'default' ? ' · route ' + payload.when : ''}`, 'tool');
          } else if (evt === 'http_response') {
            const ms = payload.elapsed_ms || 0;
            const sz = payload.content_length || 0;
            const status = payload.status === -1 ? '<i class="ri-close-fill"></i> 失败' : `HTTP ${payload.status}`;
            const cls = (payload.status >= 200 && payload.status < 300) ? 'tool-ok' : 'err';
            appendEvent('← ' + status, `${ms}ms · ${(sz/1024).toFixed(1)}KB · ${payload.content_type || ''}`, cls);
          } else if (evt === 'scripted_run_done') {
            appendEvent('done', `outputs=${(payload.outputs_keys || []).join(',')} · ${payload.elapsed_ms || 0}ms`);
          } else if (evt === 'done') {
            if (statusBox) statusBox.textContent = payload.ok ? '<i class="ri-check-fill"></i> 完成' : '<i class="ri-close-fill"></i> 失败';
            if (payload.outputs && outputsBox && outputsBody) {
              _renderRunOutputs(outputsBody, payload.outputs, app);
              outputsBox.hidden = false;
            }
            if (payload.text) {
              appendEvent('final', payload.text.slice(0, 600), 'llm');
            }
            if (payload.error) appendEvent('error', payload.error, 'err');
          } else if (evt === 'error') {
            if (statusBox) statusBox.innerHTML = '<i class="ri-close-fill"></i> 错';
            appendEvent('error', payload.detail || JSON.stringify(payload), 'err');
          } else if (evt === 'node_start' || evt === 'flow_start' || evt === 'flow_done' || evt === 'node_done') {
            appendEvent(evt, JSON.stringify(payload).slice(0, 200));
          }
        }
      }
    } catch (e) {
      if (e.name === 'AbortError') {
        if (statusBox) statusBox.textContent = '↻ 取消';
        appendEvent('cancel', '用户中止', 'err');
      } else {
        if (statusBox) statusBox.innerHTML = '<i class="ri-close-fill"></i> 流断';
        appendEvent('error', String(e), 'err');
      }
    } finally {
      if (cancelBtn) cancelBtn.hidden = true;
      _activeRuns.delete(app.id);
    }
  }

  function _onAppFormCancel(appId) {
    const ctrl = _activeRuns.get(appId);
    if (ctrl) {
      try { ctrl.abort(); } catch (e) {}
    }
  }

  function _onAppFormClear(appId) {
    const form = _container.querySelector(`form[data-app-id="${CSS.escape(appId)}"]`);
    if (!form) return;
    form.reset();
    const previewBox = form.querySelector('[data-form-preview]');
    if (previewBox) previewBox.hidden = true;
    _toast('表单已清空');
  }

  // 没有 schema 时 · 一键让 OPUS 给这个 app 设计表单
  function _onAskOpusDesignForm(appId) {
    const app = _apps.find(a => a.id === appId);
    if (!app) { _toast('找不到 app'); return; }
    const tpl = `帮我给应用「${app.name}」(${app.id}) 设计一个 UI 表单 · 看下它的 description / system_prompt / tools · 推断出用户重复用时需要填什么字段 · 然后调 update_app 把 ui_form_schema 塞进去。 设计原则: 字段数 ≤ 5 · 命名清晰 · 必填项最少。 设计完告诉我每个字段是啥意义。`;
    if (typeof window.injectChat === 'function') {
      window.injectChat(tpl, { autosend: false });
      _toast('→ 已塞到主对话框 · 按 Enter 让它设计');
    } else {
      _toast('没找到主对话输入框 · 直接跟 OPUS 说: ' + tpl);
    }
  }

  // 卷四十六续 12 · wish-165ea1f6 phase B · 工作流真跑 · SSE 流式
  //   - 画布直接序列化 → POST /workshop/flows/run (inline · 不强迫先 save)
  //   - 弹一个浮层 (在工坊视图右下角) 实时显示 node_start/node_done · 跟主对话同样工艺
  let _flowRunCtrl = null;

  function _onRun() {
    if (!_graph._nodes.length) { _toast('画布是空的 · 先拖个工具进来'); return; }
    const token = _getToken();
    if (!token) { _toast('需要 OPUS_API_TOKEN · 设置里填'); return; }

    const order = _graph.computeExecutionOrder(false);
    const hasAppNode = _graph._nodes.some(n => (n.type || '').startsWith('opus/app/'));
    if (!hasAppNode) {
      _toast('画布上还没有 OPUS app 节点 · phase B 仅支持 opus/app/<aid> 节点真跑');
      return;
    }

    const graph = _graph.serialize();
    const overlay = _ensureFlowRunOverlay();
    const eventsBox = overlay.querySelector('[data-flow-events]');
    const statusBox = overlay.querySelector('[data-flow-status]');
    const finalBox = overlay.querySelector('[data-flow-final]');
    const finalBody = overlay.querySelector('[data-flow-final-body]');
    eventsBox.innerHTML = '';
    statusBox.textContent = `准备跑 ${order.length} 节点…`;
    finalBox.hidden = true;
    overlay.hidden = false;

    if (_flowRunCtrl) try { _flowRunCtrl.abort(); } catch (e) {}
    const ctrl = new AbortController();
    _flowRunCtrl = ctrl;

    const append = (kind, text, cls) => {
      const row = document.createElement('div');
      row.className = 'ws-form-run-event' + (cls ? ' ws-fre-' + cls : '');
      const ts = new Date();
      const hm = `${String(ts.getHours()).padStart(2,'0')}:${String(ts.getMinutes()).padStart(2,'0')}:${String(ts.getSeconds()).padStart(2,'0')}`;
      row.innerHTML = `<span class="ws-fre-ts">${hm}</span><span class="ws-fre-kind">${_esc(kind)}</span><span class="ws-fre-text">${_esc(text)}</span>`;
      eventsBox.appendChild(row);
      eventsBox.scrollTop = eventsBox.scrollHeight;
    };

    (async () => {
      let resp;
      try {
        resp = await fetch('/workshop/flows/run', {
          method: 'POST',
          signal: ctrl.signal,
          headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
          body: JSON.stringify({ litegraph_json: graph, entry_inputs: {} }),
        });
      } catch (e) {
        statusBox.textContent = '连接失败';
        append('error', String(e), 'err');
        return;
      }
      if (!resp.ok || !resp.body) {
        statusBox.textContent = `HTTP ${resp.status}`;
        const txt = resp.body ? await resp.text() : '';
        append('error', `HTTP ${resp.status} · ${txt.slice(0, 300)}`, 'err');
        return;
      }
      statusBox.textContent = '跑动中…';

      const reader = resp.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buf = '';
      const parse = (chunk) => {
        buf += chunk;
        const out = [];
        let idx;
        while ((idx = buf.indexOf('\n\n')) >= 0) {
          const raw = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          const lines = raw.split('\n');
          let evt = 'message';
          let data = '';
          for (const ln of lines) {
            if (ln.startsWith(':')) continue;
            if (ln.startsWith('event:')) evt = ln.slice(6).trim();
            else if (ln.startsWith('data:')) data += ln.slice(5).trim();
          }
          if (data) out.push({ evt, data });
        }
        return out;
      };

      try {
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          const chunk = decoder.decode(value, { stream: true });
          for (const { evt, data } of parse(chunk)) {
            let p = null;
            try { p = JSON.parse(data); } catch (e) { p = { raw: data }; }
            if (evt === 'hello') append('hello', 'run_id ' + (p.run_id || ''));
            else if (evt === 'flow_start') append('flow', `开跑 · ${p.node_count} 节点`);
            else if (evt === 'node_start') append('node <i class="ri-play-fill"></i>', `#${p.node_id} · ${p.type || ''}`, 'tool');
            else if (evt === 'node_done') append('node <i class="ri-check-fill"></i>', `#${p.node_id} · outputs ${(p.outputs_keys||[]).join(',')}`, 'tool-ok');
            else if (evt === 'node_error') append('node <i class="ri-close-fill"></i>', `#${p.node_id} · ${p.error || ''}`, 'err');
            else if (evt === 'tool_call') append('<i class="ri-tools-fill"></i> ' + (p.name || '?'), p.summary || '', 'tool');
            else if (evt === 'tool_result') {
              const ok = p.ok === false ? '<i class="ri-close-fill"></i>' : '<i class="ri-check-fill"></i>';
              append(ok + ' ' + (p.name || '?'), (p.preview || p.error || '').slice(0, 240), p.ok === false ? 'err' : 'tool-ok');
            } else if (evt === 'assistant_text') {
              append('LLM', (p.text || '').slice(0, 300), 'llm');
            } else if (evt === 'flow_done') {
              statusBox.innerHTML = '<i class="ri-check-fill"></i> 完成';
            } else if (evt === 'done') {
              statusBox.textContent = p.ok ? '<i class="ri-check-fill"></i> 完成' : '<i class="ri-close-fill"></i> 失败';
              if (p.error) append('error', p.error, 'err');
              if (p.final && p.final.outputs) {
                finalBody.textContent = JSON.stringify(p.final.outputs, null, 2);
                finalBox.hidden = false;
              }
            } else if (evt === 'error') {
              statusBox.innerHTML = '<i class="ri-close-fill"></i> 错';
              append('error', p.detail || JSON.stringify(p), 'err');
            }
          }
        }
      } catch (e) {
        if (e.name === 'AbortError') {
          statusBox.textContent = '↻ 取消';
          append('cancel', '用户中止', 'err');
        } else {
          statusBox.innerHTML = '<i class="ri-close-fill"></i> 流断';
          append('error', String(e), 'err');
        }
      } finally {
        if (_flowRunCtrl === ctrl) _flowRunCtrl = null;
      }
    })();
  }

  function _ensureFlowRunOverlay() {
    let overlay = _container.querySelector('.ws-flow-run-overlay');
    if (overlay) return overlay;
    overlay = document.createElement('div');
    overlay.className = 'ws-flow-run-overlay';
    overlay.hidden = true;
    overlay.innerHTML = `
      <div class="ws-form-run-head">
        <span class="ws-form-run-title"><i class="ri-play-fill"></i> 工作流真跑</span>
        <span class="ws-form-run-status" data-flow-status>等待…</span>
        <span class="ws-spacer"></span>
        <button type="button" class="ws-btn" data-act="flow-run-cancel">取消</button>
        <button type="button" class="ws-btn" data-act="flow-run-close">×</button>
      </div>
      <div class="ws-form-run-events" data-flow-events></div>
      <div class="ws-form-run-outputs" data-flow-final hidden>
        <div class="ws-form-preview-head">最终输出</div>
        <pre class="ws-form-preview-body" data-flow-final-body></pre>
      </div>
    `;
    _container.appendChild(overlay);
    overlay.addEventListener('click', (e) => {
      const t = e.target.closest('[data-act]');
      if (!t) return;
      if (t.dataset.act === 'flow-run-cancel') {
        if (_flowRunCtrl) try { _flowRunCtrl.abort(); } catch (err) {}
      } else if (t.dataset.act === 'flow-run-close') {
        overlay.hidden = true;
      }
    });
    return overlay;
  }

  // 卷四十四 K stage 2c · 保存到 daemon (POST /workshop/flows) · 同时 localStorage 备份
  async function _onSave() {
    if (!_graph._nodes.length) { _toast('画布是空的 · 没东西可存'); return; }
    const data = _graph.serialize();
    localStorage.setItem('opus_workshop_draft', JSON.stringify(data));

    if (typeof window.opusPrompt !== 'function') {
      _toast(`💾 已存到 localStorage · ${_graph._nodes.length} 节点 · ${(data.links || []).length} 连线\n(没找到对话框组件 · daemon 端没存)`);
      return;
    }
    const name = await window.opusPrompt({
      title: '保存工作流',
      message: '给这条工作流起个名字 (会落到 data/workshop/flows/)',
      placeholder: '比如: 内容选题 → 文稿 → SoVITS 转语音',
    });
    if (!name) return;  // 用户取消 · localStorage 已存
    const desc = await window.opusPrompt({
      title: '一句话简介',
      message: `「${name}」 · 这条工作流是干啥的?`,
      placeholder: '比如: 一键产出短视频文案 + 配音 mp3',
    }) || name;
    const token = _getToken();
    if (!token) { _toast('需要 token · 设置里填 · localStorage 已存'); return; }
    try {
      const r = await fetch('/workshop/flows', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + token,
        },
        body: JSON.stringify({ name, description: desc, litegraph_json: data, created_by: 'user' }),
      });
      if (!r.ok) { _toast(`💾 localStorage 已存 · daemon 落档失败 [${r.status}]`); return; }
      const flow = await r.json();
      _flows.unshift({ id: flow.id, name, description: desc, node_count: (data.nodes || []).length, created_at: flow.created_at, created_by: 'user' });
      _toast(`💾 已落档 · ${flow.id}\n  - 名: ${name}\n  - ${_graph._nodes.length} 节点 · ${(data.links || []).length} 连线`);
    } catch (e) {
      _toast(`💾 localStorage 已存 · daemon 落档异常: ${e.message}`);
    }
  }

  // 卷四十四 K stage 2c · 加载 · 弹列表 (用 opusPrompt 暂代 · stage 2d 换正经下拉)
  async function _onLoad() {
    const localRaw = localStorage.getItem('opus_workshop_draft');
    const hasLocal = !!localRaw;

    // 拉远端 flow 列表 (mount 时已加载 · 这里再 refresh 一下保证最新)
    const token = _getToken();
    let remote = _flows.slice();
    if (token) {
      try {
        const r = await fetch('/workshop/flows', { headers: { 'Authorization': 'Bearer ' + token } });
        if (r.ok) {
          const data = await r.json();
          remote = data.flows || [];
          _flows = remote;
        }
      } catch (e) { /* 静默 · 用本地 _flows */ }
    }

    if (!hasLocal && remote.length === 0) {
      _toast('还没存过工作流 · 先在画布上画一个 → 点 💾 保存');
      return;
    }
    // 右侧抽屉点选 (BRO 2026-06-03 · 取代输入序号弹窗·跟 BI 下钻同款交互)
    _showFlowLoadDrawer(remote, hasLocal, localRaw, token);
  }

  // ── 加载工作流: 本地草稿 / 远端 flow (从抽屉点选触发) ──
  function _loadLocalDraft(localRaw) {
    try { _graph.configure(JSON.parse(localRaw)); _updateEmpty(); _renderCanvas(); _toast('📂 已载入 · localStorage 草稿'); }
    catch (e) { _toast('localStorage 解析失败: ' + e.message); }
  }

  async function _loadRemoteFlow(flow, token) {
    if (!flow) return;
    if (!token) { _toast('需要 token 才能加载远端工作流'); return; }
    try {
      const r = await fetch('/workshop/flows/' + encodeURIComponent(flow.id), {
        headers: { 'Authorization': 'Bearer ' + token },
      });
      if (!r.ok) { _toast(`加载失败 [${r.status}]`); return; }
      const full = await r.json();
      const graphData = full.litegraph_json;
      if (!graphData) { _toast('这条 flow 没有 litegraph_json 数据'); return; }
      _graph.configure(graphData);
      _updateEmpty();
      _renderCanvas();
      _toast(`📂 已载入 · ${flow.name}\n  - ${(graphData.nodes || []).length} 节点 · ${(graphData.links || []).length} 连线`);
    } catch (e) {
      _toast('加载异常: ' + e.message);
    }
  }

  // ── 工作流加载抽屉 · 右侧滑出点选 (取代输入序号弹窗·BRO 2026-06-03) ──
  function _wfDrawerEsc(e) { if (e.key === 'Escape') _closeFlowLoadDrawer(); }
  function _closeFlowLoadDrawer() {
    const d = document.getElementById('wfLoadDrawer');
    if (d) d.remove();
    document.removeEventListener('keydown', _wfDrawerEsc);
  }
  function _showFlowLoadDrawer(remote, hasLocal, localRaw, token) {
    _closeFlowLoadDrawer();
    const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    let rows = '';
    if (hasLocal) {
      rows += `<div class="wf-load-row" data-kind="local">
        <div class="wf-load-ic"><i class="ri-draft-line"></i></div>
        <div class="wf-load-main">
          <div class="wf-load-name">localStorage 草稿</div>
          <div class="wf-load-meta">上次未命名 save · 存在本地浏览器</div>
        </div></div>`;
    }
    (remote || []).forEach((f, i) => {
      rows += `<div class="wf-load-row" data-kind="remote" data-idx="${i}">
        <div class="wf-load-ic"><i class="ri-flow-chart"></i></div>
        <div class="wf-load-main">
          <div class="wf-load-name">${esc(f.name)}</div>
          <div class="wf-load-meta">${f.node_count || 0} 节点 · ${esc((f.created_at || '').slice(0, 16))}</div>
        </div></div>`;
    });
    if (!rows) rows = '<div class="wf-load-empty">没有可加载的工作流</div>';

    const total = (remote || []).length + (hasLocal ? 1 : 0);
    const dr = document.createElement('div');
    dr.id = 'wfLoadDrawer';
    dr.className = 'wf-drawer';
    dr.innerHTML = `
      <div class="wf-drawer-mask"></div>
      <div class="wf-drawer-panel">
        <div class="wf-drawer-head">
          <span><i class="ri-folder-open-line"></i> 加载工作流 · ${total} 条</span>
          <button class="wf-drawer-x" title="关闭"><i class="ri-close-line"></i></button>
        </div>
        <div class="wf-drawer-body">${rows}</div>
      </div>`;
    document.body.appendChild(dr);

    dr.querySelector('.wf-drawer-mask').addEventListener('click', _closeFlowLoadDrawer);
    dr.querySelector('.wf-drawer-x').addEventListener('click', _closeFlowLoadDrawer);
    dr.querySelectorAll('.wf-load-row').forEach(row => {
      row.addEventListener('click', () => {
        const kind = row.dataset.kind;
        _closeFlowLoadDrawer();
        if (kind === 'local') _loadLocalDraft(localRaw);
        else _loadRemoteFlow(remote[parseInt(row.dataset.idx, 10)], token);
      });
    });
    document.addEventListener('keydown', _wfDrawerEsc);
  }

  function _onClear() {
    if (!_graph._nodes.length) return;
    if (!confirm('清空画布?')) return;
    _graph.clear();
    _updateEmpty();
  }

  function _showAddCustomToolModal() {
    _toast('阶段 2 真接 · 那时候你跟右边 OPUS 说一句"我有 GPT-SOVITS 在 D:\\ai\\sovits"·OPUS 就给你长出来一个能拖的节点');
  }

  // 卷四十四 K stage 2c · 删 OPUS 造的 app · 内置不允许删
  // 卷四十四 K stage 2c++ · wish-6fd76512 · 软删 · 移到回收站可恢复
  async function _onDeleteApp(appId) {
    const app = _apps.find(a => a.id === appId);
    if (!app || app.kind !== 'opus') return;
    if (typeof window.opusConfirm === 'function') {
      const ok = await window.opusConfirm({
        title: '移到回收站?',
        message: `「${app.name}」 · 会移到回收站 · 30 天内可恢复 · 真删要再点 [永久删]`,
        danger: false,
      });
      if (!ok) return;
    } else if (!confirm(`移到回收站 「${app.name}」?`)) {
      return;
    }
    const token = _getToken();
    if (!token) { _toast('需要 token'); return; }
    try {
      const r = await fetch('/workshop/apps/' + encodeURIComponent(appId), {
        method: 'DELETE',
        headers: { 'Authorization': 'Bearer ' + token },
      });
      if (!r.ok) { _toast(`移到回收站失败 [${r.status}]`); return; }
      _apps = _apps.filter(a => a.id !== appId);
      _trashLoaded = false;  // trash 数据变了 · 下次切到 trash tab 重拉
      _hideAppDetail();
      const grid = _container.querySelector('#wsAppsGrid');
      if (grid) grid.innerHTML = _renderAppCards();
      _rerenderToolbox();
      _toast(`✓ 已移到回收站 · ${app.name}`);
    } catch (e) {
      _toast(`移到回收站异常: ${e.message}`);
    }
  }

  // ─── 回收站 (wish-6fd76512) ───
  function _renderTrashPane() {
    const apps = _trash.apps || [];
    const flows = _trash.flows || [];
    const total = apps.length + flows.length;

    if (total === 0) {
      return `
        <div class="ws-trash-head">
          <span class="ws-trash-title">🗑 回收站</span>
          <span class="ws-spacer"></span>
          <button class="ws-btn" data-act="trash-refresh" title="拉最新回收站">⟳ 刷新</button>
        </div>
        <div class="ws-trash-empty">
          <div class="ws-empty-icon">🗑</div>
          <div class="ws-empty-title">回收站是空的</div>
          <div class="ws-empty-hint">软删的 app / workflow 会进这里 · 30 天后系统自动清 (未来) · 或者你手动【清空】</div>
        </div>
      `;
    }

    const appRows = apps.map(a => `
      <div class="ws-trash-row" data-trash-id="${_esc(a.id)}">
        <span class="ws-trash-icon">${a.icon || '<i class="ri-puzzle-fill"></i>'}</span>
        <span class="ws-trash-name">${_esc(a.name || '(未命名)')}</span>
        <span class="ws-trash-kind">app</span>
        <span class="ws-trash-id">${_esc(a.id)}</span>
        <span class="ws-trash-deleted">删于 ${_esc((a.deleted_at || '').replace('T', ' '))}</span>
        <span class="ws-spacer"></span>
        <button class="ws-btn ws-trash-restore" data-act="trash-restore" data-trash-id="${_esc(a.id)}" title="恢复到应用列表">↩ 恢复</button>
        <button class="ws-btn ws-trash-hard-del" data-act="trash-empty-one" data-trash-id="${_esc(a.id)}" title="永久删除 · 不可恢复"><i class="ri-close-circle-fill"></i> 永久删</button>
      </div>
    `).join('');

    const flowRows = flows.map(f => `
      <div class="ws-trash-row" data-trash-id="${_esc(f.id)}">
        <span class="ws-trash-icon">⚛</span>
        <span class="ws-trash-name">${_esc(f.name || '(未命名)')}</span>
        <span class="ws-trash-kind">flow</span>
        <span class="ws-trash-id">${_esc(f.id)}</span>
        <span class="ws-trash-deleted">删于 ${_esc((f.deleted_at || '').replace('T', ' '))}</span>
        <span class="ws-spacer"></span>
        <button class="ws-btn ws-trash-restore" data-act="trash-restore" data-trash-id="${_esc(f.id)}" title="恢复到工作流列表">↩ 恢复</button>
        <button class="ws-btn ws-trash-hard-del" data-act="trash-empty-one" data-trash-id="${_esc(f.id)}" title="永久删除 · 不可恢复"><i class="ri-close-circle-fill"></i> 永久删</button>
      </div>
    `).join('');

    return `
      <div class="ws-trash-head">
        <span class="ws-trash-title">🗑 回收站 · ${total} 项 (${apps.length} app · ${flows.length} flow)</span>
        <span class="ws-spacer"></span>
        <button class="ws-btn" data-act="trash-refresh" title="拉最新回收站">⟳ 刷新</button>
        <button class="ws-btn ws-btn-danger" data-act="trash-empty-all" title="清空回收站 · 全部永久删 · 不可恢复">🧹 清空回收站</button>
      </div>
      ${apps.length ? `<div class="ws-trash-section-title"><i class="ri-archive-fill"></i> 应用 (${apps.length})</div>${appRows}` : ''}
      ${flows.length ? `<div class="ws-trash-section-title">⚛ 工作流 (${flows.length})</div>${flowRows}` : ''}
    `;
  }

  async function _loadTrashFromDaemon(force = false) {
    if (_trashLoaded && !force) return;
    const token = _getToken();
    const pane = _container && _container.querySelector('#wsTrashPane');
    if (!pane) return;
    if (!token) {
      pane.innerHTML = '<div class="ws-trash-empty">需要 token</div>';
      return;
    }
    try {
      const r = await fetch('/workshop/trash', { headers: { 'Authorization': 'Bearer ' + token } });
      if (!r.ok) {
        pane.innerHTML = `<div class="ws-trash-empty">拉回收站失败 [${r.status}]</div>`;
        return;
      }
      const data = await r.json();
      _trash = { apps: data.apps || [], flows: data.flows || [] };
      _trashLoaded = true;
      pane.innerHTML = _renderTrashPane();
    } catch (e) {
      pane.innerHTML = `<div class="ws-trash-empty">异常: ${_esc(e.message)}</div>`;
    }
  }

  async function _onRestoreFromTrash(trashId) {
    if (!trashId) return;
    const kind = trashId.startsWith('flow-') ? 'flow' : 'app';
    const item = (kind === 'flow' ? _trash.flows : _trash.apps).find(it => it.id === trashId);
    const name = (item && item.name) || trashId;

    if (typeof window.opusConfirm === 'function') {
      const ok = await window.opusConfirm({
        title: '恢复到应用列表?',
        message: `「${name}」 · ${kind === 'flow' ? '工作流' : '应用'} · 会从回收站移回到 active 列表`,
        danger: false,
      });
      if (!ok) return;
    } else if (!confirm(`恢复 「${name}」?`)) {
      return;
    }

    const token = _getToken();
    if (!token) { _toast('需要 token'); return; }
    try {
      const r = await fetch('/workshop/trash/' + encodeURIComponent(trashId) + '/restore', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + token },
      });
      if (!r.ok) {
        let msg = `恢复失败 [${r.status}]`;
        try { const d = await r.json(); if (d.detail) msg += ' · ' + d.detail; } catch (e) {}
        _toast(msg);
        return;
      }
      _trashLoaded = false;
      await _loadTrashFromDaemon(true);
      await _loadAssetsFromDaemon();  // active 列表也变了
      _toast(`✓ 已恢复 · ${name}`);
    } catch (e) {
      _toast(`恢复异常: ${e.message}`);
    }
  }

  async function _onEmptyTrashOne(trashId) {
    if (!trashId) return;
    const kind = trashId.startsWith('flow-') ? 'flow' : 'app';
    const item = (kind === 'flow' ? _trash.flows : _trash.apps).find(it => it.id === trashId);
    const name = (item && item.name) || trashId;

    if (typeof window.opusConfirm === 'function') {
      const ok = await window.opusConfirm({
        title: '<i class="ri-error-warning-fill"></i> 永久删除?',
        message: `「${name}」 · ${kind === 'flow' ? '工作流' : '应用'} · 真 unlink · 不可恢复 · 这次按下就再也找不回了`,
        danger: true,
      });
      if (!ok) return;
    } else if (!confirm(`⚠️ 永久删 「${name}」 · 不可恢复?`)) {
      return;
    }

    const token = _getToken();
    if (!token) { _toast('需要 token'); return; }
    try {
      const r = await fetch('/workshop/trash/' + encodeURIComponent(trashId), {
        method: 'DELETE',
        headers: { 'Authorization': 'Bearer ' + token },
      });
      if (!r.ok) { _toast(`永久删失败 [${r.status}]`); return; }
      _trashLoaded = false;
      await _loadTrashFromDaemon(true);
      _toast(`✓ 已永久删 · ${name}`);
    } catch (e) {
      _toast(`永久删异常: ${e.message}`);
    }
  }

  async function _onEmptyTrashAll() {
    const total = (_trash.apps || []).length + (_trash.flows || []).length;
    if (total === 0) { _toast('回收站已经是空的'); return; }

    if (typeof window.opusConfirm === 'function') {
      const ok = await window.opusConfirm({
        title: '<i class="ri-error-warning-fill"></i><i class="ri-error-warning-fill"></i> 清空整个回收站?',
        message: `${total} 项 · 全部真 unlink · 不可恢复 · 这次按下就再也找不回任何一个了`,
        danger: true,
      });
      if (!ok) return;
    } else if (!confirm(`⚠️⚠️ 清空回收站 · 真删 ${total} 项 · 不可恢复?`)) {
      return;
    }

    const token = _getToken();
    if (!token) { _toast('需要 token'); return; }
    try {
      const r = await fetch('/workshop/trash?kind=all', {
        method: 'DELETE',
        headers: { 'Authorization': 'Bearer ' + token },
      });
      if (!r.ok) { _toast(`清空失败 [${r.status}]`); return; }
      const data = await r.json().catch(() => ({}));
      _trashLoaded = false;
      await _loadTrashFromDaemon(true);
      _toast(`✓ 已清空回收站 · 真删 ${data.deleted_count || total} 项`);
    } catch (e) {
      _toast(`清空异常: ${e.message}`);
    }
  }

  function _toast(msg) {
    if (typeof window.opusAlert === 'function') {
      window.opusAlert({ icon: '✨', title: '工坊', message: msg });
    } else {
      console.log('[workshop]', msg);
      alert(msg);
    }
  }

  function _loadDemoFlow() {
    // 卷五十四 · 原 demo 流用 opus/atomic/llm (未实装) + opus/custom/sovits (卷四十六续 13 已删除) 搭。
    // sovits 节点 createNode 返 null → 下一行 .pos 抛 TypeError → mount() 半路崩 → 工坊首开白屏/卡死
    // (localStorage 'seen_demo' 让它每浏览器只崩一次·正好是 BRO 说的"偶尔卡死")。
    // 这些节点画布执行器又跑不了 = 纯误导。 直接不铺 demo · 让空状态引导 (_updateEmpty) 接管。
    _updateEmpty();
  }

  // ─── public API ───
  function mount(container) {
    if (_container && _container !== container) unmount();
    if (_container === container && _graph) {
      requestAnimationFrame(_renderCanvas);
      return;
    }
    if (!window.LiteGraph) {
      container.innerHTML = '<div class="dash-empty">⚠ LiteGraph 没加载 · 检查 static/lib/litegraph.core.js</div>';
      return;
    }
    _container = container;
    container.innerHTML = _html();

    _registerNodes();
    _patchMenu();

    _canvasEl = container.querySelector('#wsCanvas');
    _canvasWrap = container.querySelector('#wsCanvasWrap');

    if (!_graph) _graph = new LGraph();
    _graph.onNodeAdded = _updateEmpty;
    _graph.onNodeRemoved = _updateEmpty;
    _canvas = new LGraphCanvas(_canvasEl, _graph);
    _canvas.background_image = null;
    _canvas.render_canvas_border = false;
    _canvas.render_connections_shadows = false;
    _canvas.render_connection_arrows = true;
    _canvas.clear_background_color = 'transparent';
    _canvas.default_link_color = '#7B5DC4';
    _canvas.node_title_color = '#e8e8e8';

    _bindEvents();

    _resizeObs = new ResizeObserver(_renderCanvas);
    _resizeObs.observe(_canvasWrap);

    if (!_graph._nodes.length) _loadDemoFlow();
    _updateEmpty();

    // 卷四十四 K stage 2a · 同步 active tab 视觉态 (HTML 模板初始按 _activeTab data attr)
    _container.querySelectorAll('.ws-tab').forEach(b => b.classList.toggle('active', b.dataset.tab === _activeTab));
    if (_activeTab === 'canvas') requestAnimationFrame(_renderCanvas);

    // 卷四十四 K stage 2c · 异步拉 daemon 端 apps + flows · 拉到再重渲染
    _loadAssetsFromDaemon();
  }

  function unmount() {
    if (_resizeObs) { _resizeObs.disconnect(); _resizeObs = null; }
    _unbindEvents();
    _container = null;
    _canvasEl = null;
    _canvasWrap = null;
    _canvas = null;
    // _graph 不动 · 切回工坊 view 时复用
  }

  window.OPUS_WORKSHOP_VIEW = {
    mount,
    unmount,
    isMounted: () => !!_container,
    resize: () => requestAnimationFrame(_renderCanvas),
    serialize: () => _graph ? _graph.serialize() : null,
    load: (data) => { if (_graph) { _graph.configure(data); _updateEmpty(); _renderCanvas(); } },
    // 卷五十四 · 让 MUTATING_TOOLS 刷新能穿透到工坊 · mount() 已挂载时会短路·不重拉资产·
    // 所以 OPUS 造完 app/flow 后 scheduleDashboardRefresh 改调这个 · 真正重拉并重渲染。
    refresh: () => {
      if (!_container) return;
      _loadAssetsFromDaemon();
      if (_activeTab === 'trash') _loadTrashFromDaemon(true);
    },
    TOOL_SPECS,
  };
})();
