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
  // builtin-content 已被真 agentic app『内容制作』(app-46efb986) 顶位 · 移除 stub
  const BUILTIN_APPS = [
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
  // 卷七十二 v2 · 当前加载的 flow 完整对象 (含 steps) + 当前 active flow id (左侧高亮)
  let _currentFlowFull = null;
  let _activeFlowId = null;
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

          <!-- ── canvas tab · 工作流列表 + 只读画布 (卷七十二 v2 · BRO 反馈: 左侧从工具集改成工作流列表) ── -->
          <div class="ws-pane ws-pane-canvas" data-pane="canvas">
            <aside class="ws-toolbox" id="wsToolbox">
              <div class="ws-tb-head">
                <span class="ws-tb-title"><i class="ri-list-ordered"></i> 工作流</span>
                <button class="ws-tb-toggle" data-act="hide-tb" title="收起左侧列表">«</button>
              </div>
              <div class="ws-tb-search">
                <input type="search" id="wsFlowsSearch" placeholder="搜工作流…" autocomplete="off">
              </div>
              <div class="ws-tb-body">
                <div class="ws-flows-list" id="wsFlowsList">
                  <div class="ws-flows-empty">
                    <div class="ws-flows-empty-hint">还没有工作流 · 跟右边对话框跟 OPUS 说「帮我做一条 X 工作流」</div>
                  </div>
                </div>
                <div class="ws-tb-add">
                  <button data-act="ask-opus-flow" title="跟右边对话框跟 OPUS 说想要的工作流">＋ 让 OPUS 排一条新工作流</button>
                </div>
              </div>
            </aside>

            <button class="ws-tb-show" id="wsToolboxShow" title="展开工作流列表" hidden>»</button>

            <div class="ws-canvas-wrap" id="wsCanvasWrap">
              <div class="ws-canvas-toolbar">
                <span class="ws-canvas-title"><i class="ri-magic-fill"></i> <span id="wsCanvasFlowName">未加载</span></span>
                <span class="ws-canvas-hint" id="wsCanvasFlowDesc">从左侧点一条工作流 · 这里显示分步流程</span>
                <span class="ws-spacer"></span>
                <!-- 卷七十二 v4 · 0.2.0 · 删"运行"按钮 · 工作流由对话启动 (run_flow 工具) · 不是 UI 按钮 -->
                <span class="ws-canvas-trustarea" id="wsCanvasTrustArea" hidden></span>
              </div>
              <!-- 卷七十二 · steps-as-core · canvas-as-view · 画布只读说明带 -->
              <div class="ws-canvas-readonly-banner" id="wsCanvasReadonlyBanner">
                <i class="ri-information-fill"></i>
                <span><strong>画布 = 工作流的运行状态投影</strong> · 跑工作流 → 右侧对话框跟 OPUS 说「跑 X 工作流」 · 调整 → 「优化 step N 的 app」</span>
              </div>
              <canvas id="wsCanvas"></canvas>
              <div class="ws-canvas-empty" id="wsCanvasEmpty">
                <div class="ws-empty-icon">⚛</div>
                <div class="ws-empty-title">画布为空</div>
                <div class="ws-empty-hint">从左侧点一条工作流加载 · 或跟右边对话框跟 OPUS 说「做一份 X 工作流」</div>
              </div>
              <!-- 卷七十二 · steps 列表面板 · steps 是主 · 画布是投影 -->
              <div class="ws-steps-panel" id="wsStepsPanel" hidden>
                <div class="ws-steps-header">
                  <i class="ri-list-ordered"></i> 步骤列表 <span class="ws-steps-count" id="wsStepsCount"></span>
                  <span class="ws-spacer"></span>
                  <span class="ws-steps-hint">编辑请跟右边对话框跟 OPUS 说 · 不要直接改下面的卡</span>
                </div>
                <div class="ws-steps-list" id="wsStepsList"></div>
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
      const isShipped = app.kind === 'opus' && app.shipped;  // 自带 agentic app · 随 DK 出厂 · 不可删
      const kindLabel = isBuiltin ? '内置' : (isShipped ? '自带' : 'OPUS 造');
      let meta;
      if (isBuiltin) meta = '<span class="wac-stage">stage 2b 可配置</span>';
      else if (isShipped) meta = `<span class="wac-stage">📦 随 DK 出厂 · v${Number(app.version || 1)}</span>`;
      else meta = `<span class="wac-stage">${_esc((app.created_at || '').slice(0, 10))} · OPUS 造</span>`;
      // 删除按钮: 内置 / shipped 都不能删 · 只有纯 OPUS 临时造的 app 可删
      const canDelete = !isBuiltin && !isShipped;
      const trashBtn = canDelete ? `<button class="wac-trash-btn" data-act="app-delete-card" data-app-id="${_esc(app.id)}" title="移到回收站 (可恢复)">🗑</button>` : '';
      return `
        <div class="ws-app-card ${isShipped ? 'shipped' : ''}" data-app-id="${_esc(app.id)}" data-act="open-app">
          ${trashBtn}
          <div class="wac-icon">${app.icon || '<i class="ri-puzzle-fill"></i>'}</div>
          <div class="wac-body">
            <div class="wac-title">${_esc(app.name)}</div>
            <div class="wac-desc">${_esc(app.description)}</div>
            <div class="wac-meta">
              <span class="wac-kind">${kindLabel}</span>
              ${meta}
            </div>
          </div>
        </div>
      `;
    }).join('');
    const addCard = `
      <div class="ws-app-card ws-app-add" data-act="ask-opus-app" title="跳到右侧 OPUS · 直接说想要什么应用">
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
  // 卷七十二 v3 · 缓存 in-flight promise 防重复 fetch · _loadRemoteFlow 能 await 之
  let _assetsPromise = null;
  function _loadAssetsFromDaemon() {
    if (_assetsPromise) return _assetsPromise;
    _assetsPromise = _doLoadAssetsFromDaemon().finally(() => { _assetsPromise = null; });
    return _assetsPromise;
  }
  // 卷七十二 v5 · 2026-06-10 · BRO bug: 「刷新后应用先看不到 · 要再次刷新才能看到」
  // 病根: _doLoadAssetsFromDaemon fetch 失败 (daemon 启动还没全 ready / 偶发 5xx / 网络抖)
  //      try/catch 静默吃了错 · _apps 不更新 · 用户只见 3 个 builtin · 必须二刷
  // 修法: 失败时退避重试 2 次 (500ms · 1500ms) · 还失败才放弃显示 builtin
  async function _fetchWithRetry(url, init, maxRetry = 2) {
    const delays = [500, 1500];
    for (let i = 0; i <= maxRetry; i++) {
      try {
        const r = await fetch(url, init);
        if (r.ok) return r;
        // 4xx 非 401/403 也算最终错 · 不重试 (例: 404 endpoint 没了)
        if (r.status >= 400 && r.status < 500 && r.status !== 408 && r.status !== 429) return r;
      } catch (e) { /* 网络 / abort · 落入重试 */ }
      if (i < maxRetry) await new Promise(res => setTimeout(res, delays[i] || 1500));
    }
    return null;
  }

  async function _doLoadAssetsFromDaemon() {
    const token = _getToken();
    if (!token) return;
    const headers = { 'Authorization': 'Bearer ' + token };
    const rApps = await _fetchWithRetry('/workshop/apps', { headers });
    if (rApps && rApps.ok) {
      try {
        const data = await rApps.json();
        const opusApps = (data.apps || []).map(a => Object.assign({}, a, { kind: 'opus' }));
        // shipped app (自带·随 DK 出厂) 排在所有 opus app 之前
        // 顺序: BUILTIN_APPS (产品设计/开发/文档撰写) → shipped (内容制作) → 其他 opus app (按 mtime desc)
        const shippedApps = opusApps.filter(a => a.shipped);
        const otherApps = opusApps.filter(a => !a.shipped);
        _apps = BUILTIN_APPS.concat(shippedApps, otherApps);
        // 卷七十二 v3 · 共享 _apps 给 chat.js 的 flow runs banner 用 (查 step.app id → 名字)
        window._opusWorkshopApps = _apps.slice();
        // 卷四十六续 12 · wish-165ea1f6 phase B · 每次拿到新 app 列表都注册成 LiteGraph node
        _registerAppNodes();
      } catch (e) { /* json parse · 静默走 builtin */ }
    }
    const rFlows = await _fetchWithRetry('/workshop/flows', { headers });
    if (rFlows && rFlows.ok) {
      try {
        const data = await rFlows.json();
        _flows = data.flows || [];
      } catch (e) { /* 静默 */ }
    }
    _rerenderToolbox();
    // 卷七十二 v2 · BRO 反馈: app 名字显示错 → _apps 异步加载完后重渲染当前 steps panel
    if (_currentFlowFull) _renderStepsPanel(_currentFlowFull);
    _renderFlowsSidebar();
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
    const kindLabel = app.kind === 'builtin'
      ? '内置应用'
      : (app.shipped ? '📦 自带应用 · 随 DK 出厂' : 'OPUS 造的应用');
    return `
      <div class="ws-ad-head">
        <button class="ws-ad-back" data-act="back-to-apps" title="返回应用列表">← 应用</button>
        <span class="ws-ad-icon">${app.icon || '<i class="ri-puzzle-fill"></i>'}</span>
        <span class="ws-ad-title">${_esc(app.name)}</span>
        <span class="ws-ad-kind">${kindLabel}</span>
        <span class="ws-spacer"></span>
        ${app.kind === 'opus' && !app.shipped ? `<button class="ws-btn" data-act="ad-delete" data-app-id="${_esc(app.id)}" title="删除这个 OPUS 造的 app">🗑 删</button>` : ''}
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
        <div class="ws-ad-loading"><i class="ri-radar-fill"></i> 加载配置中…</div>
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

  // 卷七十二 v2 · BRO 反馈: 左侧改成工作流列表 · 点击直接加载 (替代旧 toolbox)
  function _rerenderToolbox() {
    _renderFlowsSidebar();
  }

  function _renderFlowsSidebar() {
    if (!_container) return;
    const list = _container.querySelector('#wsFlowsList');
    if (!list) return;
    const search = (_container.querySelector('#wsFlowsSearch')?.value || '').toLowerCase().trim();
    let flows = _flows.slice();
    if (search) {
      flows = flows.filter(f => (f.name || '').toLowerCase().includes(search)
        || (f.description || '').toLowerCase().includes(search));
    }
    if (flows.length === 0) {
      list.innerHTML = `<div class="ws-flows-empty">
        <div class="ws-flows-empty-hint">${search ? '没有匹配 「' + _escapeHtml(search) + '」 的工作流' : '还没有工作流 · 跟右边对话框跟 OPUS 说「帮我做一条 X 工作流」'}</div>
      </div>`;
      return;
    }
    list.innerHTML = flows.map(f => {
      const isSteps = f.flow_kind === 'steps';
      const active = (_activeFlowId === f.id) ? ' active' : '';
      const kindBadge = isSteps
        ? '<span class="ws-flow-kind steps" title="steps 二层结构 · 主编辑路径">steps</span>'
        : '<span class="ws-flow-kind legacy" title="旧版 LiteGraph 画布数据">legacy</span>';
      const trustBadge = _trustBadgeHtml(f.trust_level, f.trusted_by, f.success_runs);
      return `
        <div class="ws-flow-item${active}" data-act="load-flow" data-flow-id="${_escapeHtml(f.id)}" title="${_escapeHtml(f.description || '')}">
          <div class="ws-flow-item-name">${_escapeHtml(f.name || f.id)}${kindBadge}</div>
          <div class="ws-flow-item-meta">
            <span><i class="ri-list-ordered"></i> ${f.node_count || 0} 步</span>
            ${f.runs ? `<span><i class="ri-play-fill"></i> 跑过 ${f.runs} 次</span>` : ''}
            ${trustBadge}
          </div>
        </div>
      `;
    }).join('');
  }

  // 卷七十二 v5 · 2026-06-10 · BRO 反馈: emoji 状态点 + ⭐ 在不同系统下渲染不一致 · 换 remix icon
  // lvl 0-3 用 fill 实心圆 (已点亮) + line 空心圆 (未点亮) 拼出进度条 · lvl3 用 shield-star-fill (盾+星 · BRO 钦定)
  function _trustDotsHtml(lvl) {
    let html = '';
    for (let i = 0; i < 4; i++) {
      html += `<i class="ri-circle-${i < lvl ? 'fill' : 'line'}"></i>`;
    }
    return html;
  }

  function _trustBadgeHtml(level, by, successRuns) {
    const lvl = Math.max(0, Math.min(3, parseInt(level || 0, 10)));
    const dots = _trustDotsHtml(lvl);
    const label = ['未信任', '入口免审', '自动跑', 'BRO 钦定'][lvl];
    const star = (by === 'BRO' && lvl === 3) ? '<i class="ri-shield-star-fill ws-trust-crown"></i>' : '';
    const tip = `信任度 lvl ${lvl} · ${label} · 成功跑过 ${successRuns || 0} 次 · 点改`;
    return `<span class="ws-flow-trust trust-lvl-${lvl}" title="${tip}">${dots}${star}</span>`;
  }

  // 卷七十二 v4 · 0.2.0 · 渲染画布顶部 trust area (打开 flow 时同步)
  function _renderCanvasTrustArea() {
    if (!_container) return;
    const area = _container.querySelector('#wsCanvasTrustArea');
    if (!area) return;
    if (!_currentFlowFull || !_activeFlowId) {
      area.hidden = true;
      area.innerHTML = '';
      return;
    }
    const f = _currentFlowFull;
    const lvl = Math.max(0, Math.min(3, parseInt(f.trust_level || 0, 10)));
    const dots = _trustDotsHtml(lvl);
    const label = ['未信任', '入口免审', '自动跑 (CONFIRM 放行)', 'BRO 钦定'][lvl];
    const crown = (lvl === 3) ? '<i class="ri-shield-star-fill ws-trust-crown"></i>' : '';
    const next = lvl >= 2 ? 0 : (lvl + 2);  // 0/1 → 2 (信任) · 2 → 0 (收回)
    const nextIcon = next >= 2 ? 'ri-shield-check-fill' : 'ri-shield-cross-fill';
    const nextLabel = next >= 2 ? '信任这条' : '收回信任';
    area.hidden = false;
    area.innerHTML = `
      <span class="ws-trust-badge trust-lvl-${lvl}" title="${label} · 跑过 ${f.success_runs || 0} 次">${dots}${crown} <span class="ws-trust-text">${label}</span></span>
      <button class="ws-btn ws-btn-small" data-act="trust" data-flow-id="${_escapeHtml(_activeFlowId)}" data-next-level="${next}" title="${nextLabel}"><i class="${nextIcon}"></i> ${nextLabel}</button>
    `;
  }

  async function _onTrustClick() {
    if (!_activeFlowId || !_currentFlowFull) return;
    const area = _container && _container.querySelector('#wsCanvasTrustArea');
    const btn = area && area.querySelector('[data-act="trust"]');
    if (!btn) return;
    const nextLevel = parseInt(btn.dataset.nextLevel || '0', 10);
    const token = _getToken && _getToken();
    if (!token) { _toast('需要 token'); return; }
    try {
      const r = await fetch('/workshop/flows/' + encodeURIComponent(_activeFlowId) + '/trust', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
        body: JSON.stringify({ level: nextLevel, by: 'BRO' }),
      });
      if (!r.ok) { _toast(`信任设置失败 [${r.status}]`); return; }
      const data = await r.json();
      _currentFlowFull = Object.assign({}, _currentFlowFull, data.flow || {});
      // 同步 _flows 列表里这条
      const idx = _flows.findIndex(x => x.id === _activeFlowId);
      if (idx >= 0) _flows[idx] = Object.assign({}, _flows[idx], data.flow || {});
      _renderCanvasTrustArea();
      _renderFlowsSidebar();
      const lvl = data.flow.trust_level;
      const msg = lvl >= 2
        ? `已信任「${data.flow.name}」 · 下次跑工作流不再问 CONFIRM (GUARD 仍要 y)`
        : `已收回信任 · 下次跑这条 flow 恢复每步审`;
      _toast(msg);
    } catch (e) {
      _toast('信任设置异常: ' + e.message);
    }
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
      // 配置 tab 资产填写按钮 → 弹 modal
      else if (act === 'asset-edit') {
        _openAssetEditModal({
          aid: tgt.dataset.assetAid,
          name: tgt.dataset.assetName,
          type: tgt.dataset.assetType,
          label: tgt.dataset.assetLabel,
          help: tgt.dataset.assetHelp,
          app_context: tgt.dataset.assetAppContext,
        });
      }
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
      else if (act === 'run') {
        // 卷七十二 v4 · 0.2.0 · 老"运行"按钮已删 · 这里兜底 · 万一有缓存版本点了给提示
        _toast('🚀 工作流由对话启动 · 跟右侧 OPUS 说「跑这条 flow」 · 这里是状态投影');
      }
      else if (act === 'trust') _onTrustClick();
      else if (act === 'save') _onSave();
      else if (act === 'load') _onLoad();
      else if (act === 'clear') _onClear();
      else if (act === 'lang') _toggleLang();
      // 卷七十二 v2 · BRO 反馈: 左侧工作流列表 · 点击直接加载
      else if (act === 'load-flow') {
        const fid = tgt.dataset.flowId;
        const flow = _flows.find(f => f.id === fid);
        if (flow) _loadRemoteFlow(flow);
      }
      else if (act === 'ask-opus-flow') _askOpusInChat('flow');
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

    // 卷七十二 v2 · 左侧已换成工作流列表 · 搜索 input id 改为 #wsFlowsSearch
    const searchInput = _container.querySelector('#wsFlowsSearch');
    if (searchInput) {
      _searchHandler = () => _renderFlowsSidebar();
      searchInput.addEventListener('input', _searchHandler);
    }

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
    // 卷七十二 · canvas-as-view · 工具集拖入禁用 · 编辑路径回 NLP
    _dropHandler = (e) => {
      e.preventDefault();
      _toast('📌 画布是步骤的可视化投影 · 编辑请用 NLP (跟右侧 OPUS 说「做一个 X 工作流」)');
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
    // 卷七十二 v5 · 2026-06-10 · BRO bug 第二层修复: 切回 apps tab 时强制重渲染 grid
    // 如果 mount 时 _activeTab 不是 apps · _doLoadAssetsFromDaemon 完成时跳过了重渲染 ·
    // _apps 已更新但 grid 还停在 builtin 3 个 · BRO 切回 apps tab 看到的就是旧版
    if (tab === 'apps' && _container) {
      const grid = _container.querySelector('#wsAppsGrid');
      if (grid) {
        grid.innerHTML = _renderAppCards();
        if (_activeAppId) {
          const card = grid.querySelector(`.ws-app-card[data-app-id="${_activeAppId}"]`);
          if (card) card.classList.add('active');
        }
      }
    }
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
    // opus app · 切到详情 tab 时动态加载系统提示词
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
    // 切到配置 tab 时拉 asset registry 真值 + 渲染槽位卡片
    if (tabName === 'config' && _activeAppId) {
      const app = _apps.find(a => a.id === _activeAppId);
      const pane = _container.querySelector('.ws-ad-pane[data-ad-pane="config"]');
      if (app && pane && !pane.dataset.loaded) {
        _loadAppConfigPane(app, pane);
        pane.dataset.loaded = '1';
      }
    }
  }

  // ─── 配置 tab 加载 + 渲染 (NLP First · 只读为主) ───
  async function _loadAppConfigPane(app, pane) {
    const token = _getToken();
    // 拉本 app + _shared 资产 (两份合并 · _shared 标识"跨 app")
    let myAssets = [];
    let sharedAssets = [];
    if (token && app.kind === 'opus') {
      try {
        const [r1, r2] = await Promise.all([
          fetch(`/workshop/assets/${encodeURIComponent(app.id)}`, { headers: { 'Authorization': 'Bearer ' + token } }),
          fetch('/workshop/assets/_shared', { headers: { 'Authorization': 'Bearer ' + token } }),
        ]);
        if (r1.ok) myAssets = (await r1.json()).assets || [];
        if (r2.ok) sharedAssets = (await r2.json()).assets || [];
      } catch (e) { /* 静默 · 用空列表渲染 */ }
    }
    pane.innerHTML = _renderAppConfigPane(app, myAssets, sharedAssets);
  }

  function _renderAppConfigPane(app, myAssets, sharedAssets) {
    if (app.kind === 'builtin') {
      return `<div class="ws-ad-stub"><div class="ws-stub-icon">⚙</div><h3>${_esc(app.name)} · 内置 app</h3><p>内置 app 没有可配置的资产槽 · 配置 = 真 OPUS-app 才用 (那些有 system_prompt / asset_slots / 表单 schema 的)。</p></div>`;
    }
    const slots = Array.isArray(app.asset_slots) ? app.asset_slots : [];
    const tools = Array.isArray(app.tools) ? app.tools : [];
    const schema = Array.isArray(app.ui_form_schema) ? app.ui_form_schema : [];
    const version = Number(app.version || 1);
    const specV = Number(app.spec_version || 1);

    const slotsHtml = slots.length
      ? slots.map(s => _renderAssetSlotCard(app.id, s, myAssets, sharedAssets)).join('')
      : `<div class="ws-app-empty">这个 app 没声明 asset_slots · 它不需要用户个性资产。 想加 → 主对话: <code>update_app(aid=${_esc(app.id)}, asset_slots=[{name:"voice",type:"text",label:"声音"}])</code></div>`;

    const toolsHtml = tools.length
      ? tools.map(t => `<code>${_esc(t)}</code>`).join(' ')
      : '<i>(全部 OPUS 工具都可用)</i>';

    const schemaHtml = schema.length
      ? `<table class="ws-app-schema-table"><thead><tr><th>字段</th><th>类型</th><th>标签</th><th>必填</th></tr></thead><tbody>${schema.map(f => `<tr><td><code>${_esc(f.name)}</code></td><td>${_esc(f.type || 'text')}</td><td>${_esc(f.label || '')}</td><td>${f.required ? '是' : '—'}</td></tr>`).join('')}</tbody></table>`
      : '<div class="ws-app-empty">这个 app 没声明 ui_form_schema · 测试 tab 没表单</div>';

    const changelog = Array.isArray(app.changelog) ? app.changelog.slice(-5).reverse() : [];
    const changelogHtml = changelog.length
      ? `<ul class="ws-app-changelog">${changelog.map(c => `<li><b>v${c.v}</b> · ${_esc(c.at || '')} · ${_esc(c.note || '')}</li>`).join('')}</ul>`
      : '<div class="ws-app-empty">还没改过</div>';

    return `
      <div class="ws-app-stub">
        <div class="ws-app-meta-chips">
          <span class="wamc-chip" title="版本号">📦 v${version}</span>
          <span class="wamc-chip" title="规格版本 · v2=六段校验严格模式">⚙ spec_v${specV}</span>
          <span class="wamc-chip" title="exec_kind">${(app.exec_kind || 'agentic') === 'scripted' ? '⚡ scripted' : '🧠 agentic'}</span>
          <span class="wamc-chip" title="推荐模型"><i class="ri-brain-fill"></i> ${app.model_hint ? `<code>${_esc(app.model_hint)}</code>` : '<i>RUNTIME 默认</i>'}</span>
          <span class="wamc-chip" title="跑过几次"><i class="ri-play-fill"></i> ${Number(app.runs || 0)}</span>
        </div>

        <div class="ws-app-section">
          <div class="ws-app-section-head"><i class="ri-archive-fill"></i> 资产槽位 (asset_slots) · ${slots.length} 个声明</div>
          <div class="ws-app-section-hint">用户个性资产存这里 · 改值 → 主对话: <code>manage_app_asset(action=set, app_id=${_esc(app.id)}, name=..., value=...)</code></div>
          <div class="ws-app-slot-grid">${slotsHtml}</div>
        </div>

        <div class="ws-app-section">
          <div class="ws-app-section-head">🧰 工具白名单 · ${tools.length || '∞'}</div>
          <div class="ws-app-tools">${toolsHtml}</div>
          <div class="ws-app-section-hint">改 → <code>update_app(aid=${_esc(app.id)}, tools=[...])</code></div>
        </div>

        <div class="ws-app-section">
          <div class="ws-app-section-head">📋 表单字段 (ui_form_schema) · ${schema.length} 个字段</div>
          ${schemaHtml}
          <div class="ws-app-section-hint">测试 tab 的表单按这个渲染 · 改 → 主对话说 <code>update_app</code> 改字段</div>
        </div>

        <div class="ws-app-section">
          <div class="ws-app-section-head">📜 版本历史 (最近 5 条)</div>
          ${changelogHtml}
          <div class="ws-app-section-hint">全部历史 / 回滚 → 主对话: <code>app_versions(action=list, app_id=${_esc(app.id)})</code></div>
        </div>

        <div class="ws-app-section">
          <div class="ws-app-section-head"><i class="ri-draft-fill"></i> 系统提示词 (详情 tab 看全文)</div>
          <div class="ws-app-section-hint">prompt 长 ${(app.system_prompt || '').length} 字 · 改 → 主对话: <code>update_app(aid=${_esc(app.id)}, system_prompt='...', change_note='...')</code></div>
        </div>
      </div>
    `;
  }

  function _renderAssetSlotCard(appId, slot, myAssets, sharedAssets) {
    // 找资产真值: name 在本 app 优先 · 否则尝试 _shared (跨 app 槽)
    const name = slot.name || '';
    const myEntry = myAssets.find(a => a.name === name);
    const sharedEntry = sharedAssets.find(a => a.name === name);
    const entry = myEntry || sharedEntry;
    const fromShared = !myEntry && !!sharedEntry;
    const valuePreview = entry ? _esc(String(entry.value_preview || entry.value || '').slice(0, 200)) : '';
    const updatedAt = entry ? _esc(entry.updated_at || '') : '';
    const note = entry ? _esc(entry.note || '') : '';
    const historyN = entry ? Number(entry.history_count || 0) : 0;
    const filled = !!entry;
    // asset_slot 卡片加"填资产/换资产"按钮 · 治"白说了"的痛
    const editTargetAid = fromShared ? '_shared' : appId;
    const editLabel = filled ? '📎 换' : '📎 填';
    return `
      <div class="ws-app-slot-card ${filled ? 'filled' : 'empty'} ${fromShared ? 'shared' : ''}">
        <div class="ws-app-slot-head">
          <code class="ws-app-slot-name">${_esc(name)}</code>
          <span class="ws-app-slot-type">${_esc(slot.type || 'text')}</span>
          ${fromShared ? '<span class="ws-app-slot-shared" title="跨 app 共享 · 来自 _shared">_shared</span>' : ''}
          <button class="ws-app-slot-edit"
            data-act="asset-edit"
            data-asset-aid="${_esc(editTargetAid)}"
            data-asset-name="${_esc(name)}"
            data-asset-type="${_esc(slot.type || 'text')}"
            data-asset-label="${_esc(slot.label || name)}"
            data-asset-help="${_esc(slot.help || '')}"
            data-asset-app-context="${_esc(appId)}"
            title="${filled ? '替换 · 旧值进 history 不丢' : '填这个槽位的真值'}">${editLabel}</button>
        </div>
        <div class="ws-app-slot-label">${_esc(slot.label || name)}</div>
        ${slot.help ? `<div class="ws-app-slot-help">${_esc(slot.help)}</div>` : ''}
        ${filled
          ? `<div class="ws-app-slot-value"><pre>${valuePreview}</pre><div class="ws-app-slot-meta">v ${updatedAt}${historyN ? ` · history ${historyN}` : ''}${note ? ` · ${note}` : ''}</div></div>`
          : `<div class="ws-app-slot-empty-hint">空 · 点上方 <b>📎 填</b> 按钮 · 或主对话: <code>manage_app_asset(action=set, app_id=${_esc(editTargetAid)}, name=${_esc(name)}, value=..., note=...)</code></div>`}
      </div>
    `;
  }

  // ─── 资产填写 modal · 治"白说了"的痛 ───
  // BRO 之前必须打 manage_app_asset(...) 命令才能填资产 · 这是 NLP 优先的不在场证明
  // 现在: 配置 tab 点📎填 → modal 弹出 → 按 type 分支 → 提交直接 POST /workshop/assets/set (跟 NLP 同一咽喉)
  let _assetModalEl = null;
  let _assetModalActiveAid = null;  // 关 modal 后刷新当前 app 的配置 tab

  function _openAssetEditModal(opts) {
    // opts: {aid, name, type, label, help, app_context}
    _assetModalActiveAid = opts.app_context || opts.aid;
    const isShared = opts.aid === '_shared';
    const type = (opts.type || 'text').toLowerCase();
    const isImage = type === 'images' || type === 'file';
    const isJson = type === 'json';

    // 用原生 <dialog> · 浏览器自带 backdrop / Esc 关闭
    if (_assetModalEl) {
      try { _assetModalEl.remove(); } catch (e) {}
    }
    const dlg = document.createElement('dialog');
    dlg.className = 'ws-asset-modal';
    dlg.innerHTML = `
      <form method="dialog" class="ws-asset-modal-form">
        <div class="ws-am-head">
          <div class="ws-am-title">📎 填资产 · <code>${_esc(opts.name)}</code></div>
          <div class="ws-am-sub">
            <span>app_id: <code>${_esc(opts.aid)}</code>${isShared ? ' <span class="ws-am-shared-tag">跨 app 共享</span>' : ''}</span>
            <span>type: <code>${_esc(type)}</code></span>
          </div>
          ${opts.help ? `<div class="ws-am-help">${_esc(opts.help)}</div>` : ''}
        </div>
        <div class="ws-am-body">
          ${isImage ? `
            <label class="ws-am-label">上传图片 (PNG/JPG/WEBP · ≤20MB)</label>
            <input type="file" data-am-field="file" accept="image/png,image/jpeg,image/webp,image/gif" />
            <div class="ws-am-upload-preview" data-am-preview></div>
            <label class="ws-am-label" style="margin-top:12px">图片描述 (用于 LLM 理解这张图是什么)</label>
            <input type="text" data-am-field="image_label" placeholder="例：白色小猪 IP · 戴红围巾的卡通形象" />
          ` : isJson ? `
            <label class="ws-am-label">JSON 值 (粘合法 JSON · 提交时解析)</label>
            <textarea data-am-field="value_json" rows="8" placeholder='例: {"voice_id": "bro-final-v1", "speed": 1.0}'></textarea>
          ` : `
            <label class="ws-am-label">${_esc(opts.label || opts.name)}</label>
            <textarea data-am-field="value_text" rows="6" placeholder="${type === 'textarea' ? '多行文本 · 例:口播文风参考样例 ~200 字' : '单行/多行文本均可'}"></textarea>
          `}
          <label class="ws-am-label" style="margin-top:12px">这次写入的说明 (note · 强烈建议填 · 进 history 留痕)</label>
          <input type="text" data-am-field="note" placeholder="例：第三版克隆·BRO 试听满意 · 取代 bro-clone-01" />
        </div>
        <div class="ws-am-foot">
          <span class="ws-am-status" data-am-status></span>
          <button type="button" data-am-act="cancel">取消</button>
          <button type="button" data-am-act="submit" class="ws-am-primary">保存</button>
        </div>
      </form>
    `;
    document.body.appendChild(dlg);
    _assetModalEl = dlg;
    if (typeof dlg.showModal === 'function') dlg.showModal();
    else dlg.setAttribute('open', '');

    const $ = (sel) => dlg.querySelector(sel);
    const status = $('[data-am-status]');
    const setStatus = (msg, isError) => {
      if (status) { status.textContent = msg || ''; status.classList.toggle('error', !!isError); }
    };

    // 文件预览 (image only)
    const fileInput = $('[data-am-field="file"]');
    const previewEl = $('[data-am-preview]');
    if (fileInput && previewEl) {
      fileInput.addEventListener('change', () => {
        const f = fileInput.files && fileInput.files[0];
        if (f && /^image\//.test(f.type)) {
          const url = URL.createObjectURL(f);
          previewEl.innerHTML = `<img src="${url}" alt="preview" /><div class="ws-am-fname">${_esc(f.name)} · ${Math.round(f.size / 1024)} KB</div>`;
        } else {
          previewEl.innerHTML = '';
        }
      });
    }

    // 取消
    dlg.querySelector('[data-am-act="cancel"]').addEventListener('click', () => {
      try { dlg.close(); } catch (e) {}
      dlg.remove();
      _assetModalEl = null;
    });

    // 保存
    dlg.querySelector('[data-am-act="submit"]').addEventListener('click', async () => {
      try {
        setStatus('保存中…', false);
        const note = ($('[data-am-field="note"]') || {}).value || '';
        let value;
        if (isImage) {
          // step 1: 文件上传
          const f = fileInput && fileInput.files && fileInput.files[0];
          if (!f) { setStatus('请选择一张图片', true); return; }
          const fd = new FormData();
          fd.append('app_id', opts.aid);
          fd.append('name', opts.name);
          fd.append('file', f);
          const token = _getToken();
          const upR = await fetch('/workshop/assets/upload', {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + token },
            body: fd,
          });
          if (!upR.ok) {
            const err = await upR.text();
            setStatus('上传失败: ' + err.slice(0, 200), true);
            return;
          }
          const upJson = await upR.json();
          const imageLabel = (($('[data-am-field="image_label"]') || {}).value || '').trim();
          // value 形态固定: {path, label, uploaded_at} · 跟 GPT Image 2 prompt 里的 IP_images 处理规则对得上
          value = { path: upJson.path, label: imageLabel, uploaded_at: upJson.filename };
        } else if (isJson) {
          const raw = (($('[data-am-field="value_json"]') || {}).value || '').trim();
          if (!raw) { setStatus('JSON 不能为空', true); return; }
          try { value = JSON.parse(raw); } catch (e) { setStatus('JSON 解析失败: ' + e.message, true); return; }
        } else {
          const raw = (($('[data-am-field="value_text"]') || {}).value || '').trim();
          if (!raw) { setStatus('内容不能为空', true); return; }
          value = raw;
        }

        // step 2: POST set
        const token = _getToken();
        const r = await fetch('/workshop/assets/set', {
          method: 'POST',
          headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
          body: JSON.stringify({
            app_id: opts.aid,
            name: opts.name,
            value: value,
            type: opts.type || 'text',
            label: opts.label || opts.name,
            note: note,
          }),
        });
        if (!r.ok) {
          const err = await r.text();
          setStatus('保存失败: ' + err.slice(0, 200), true);
          return;
        }
        const result = await r.json();
        setStatus('✓ 已保存 · history_count=' + (result.history_count || 0), false);
        // 关 modal · 刷新配置 tab
        setTimeout(() => {
          try { dlg.close(); } catch (e) {}
          dlg.remove();
          _assetModalEl = null;
          // 重刷配置 tab
          if (_assetModalActiveAid) {
            const app = _apps.find(a => a.id === _assetModalActiveAid);
            const pane = _container && _container.querySelector('.ws-ad-pane[data-ad-pane="config"]');
            if (app && pane) {
              delete pane.dataset.loaded;
              _loadAppConfigPane(app, pane);
              pane.dataset.loaded = '1';
            }
          }
        }, 600);
      } catch (e) {
        setStatus('异常: ' + (e.message || e), true);
      }
    });
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
          <span class="wamc-chip" title="推荐模型"><i class="ri-brain-fill"></i> ${app.model_hint ? `<code>${_esc(app.model_hint)}</code>` : '<i>BRO 默认</i>'}</span>
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
  // 卷七十三 P0-2 (2026-06-10) · BRO 痛点修补:
  //   ① other (md/json/txt) 卡片**没有 onclick** = 哑卡片打不开 · 加 modal preview
  //   ② 文件名是 timestamp 看不懂 → 解析成人话标题 (`导演蓝图 · 6月10日 15:24`)
  //   ③ 加"复制路径"按钮 · BRO 想去文件管理器自己定位
  function _renderOpusOutputsHTML(app, data) {
  const files = data.files || [];
  if (files.length === 0) {
    return `<div class="ws-ad-empty">
      <div style="font-size:32px;margin-bottom:12px">📁</div>
      <div>还没有产出</div>
      <div class="ws-ad-hint">去「▶ 测试」tab 跑一次 ${_esc(app.name || app.id)} · 产物会出现在这里</div>
    </div>`;
  }
  let html = `<div class="ws-ad-meta">${files.length} 个文件 · 点卡片打开预览 · 路径按钮复制本地路径到剪贴板</div>`;
  html += '<div class="ws-output-gallery">';
  for (const f of files) {
    const fname = _esc(f.name || '');
    const furl = _esc(f.url || '');
    const fsize = f.size ? (f.size / 1024).toFixed(0) + 'KB' : '';
    // 卷七十三 P0-2 · 人性化标题 (从文件名解析 · 失败回 raw 文件名)
    const niceTitle = _esc(_humanizeOutputFileName(f.name || ''));
    const localPath = _esc(f.path || '');  // 后端给了就用 · 没给前端没法准确组路径
    // 复制路径按钮 (无路径就不显示) · stopPropagation 防卡片 onclick 一起触发
    const copyBtn = localPath
      ? `<button class="ws-gallery-pathbtn" onclick="event.stopPropagation(); window._copyOutputPath('${localPath}')" title="复制本地路径到剪贴板 · 然后去文件管理器粘贴"><i class="ri-clipboard-line"></i> 路径</button>`
      : '';
    if (f.type === 'image') {
      html += `
        <div class="ws-gallery-card" onclick="window._openLightbox('${furl}', '${fname}')">
          <img src="${furl}" alt="${fname}" loading="lazy" class="ws-gallery-img">
          <div class="ws-gallery-info">
            <span class="ws-gallery-name" title="${fname}">${niceTitle}</span>
            <span class="ws-gallery-size">${fsize}</span>
            ${copyBtn}
          </div>
        </div>`;
    } else if (f.type === 'audio') {
      html += `
        <div class="ws-gallery-card ws-gallery-audio">
          <div class="ws-gallery-icon">🎵</div>
          <audio controls src="${furl}" class="ws-gallery-player"></audio>
          <div class="ws-gallery-info">
            <span class="ws-gallery-name" title="${fname}">${niceTitle}</span>
            <span class="ws-gallery-size">${fsize}</span>
            ${copyBtn}
          </div>
        </div>`;
    } else if (f.type === 'video') {
      html += `
        <div class="ws-gallery-card ws-gallery-video">
          <div class="ws-gallery-icon">🎬</div>
          <video controls src="${furl}" class="ws-gallery-player"></video>
          <div class="ws-gallery-info">
            <span class="ws-gallery-name" title="${fname}">${niceTitle}</span>
            <span class="ws-gallery-size">${fsize}</span>
            ${copyBtn}
          </div>
        </div>`;
    } else {
      // md / json / txt / 其他文本 · 新加 onclick 弹 modal preview
      html += `
        <div class="ws-gallery-card ws-gallery-other" onclick="window._openOutputPreview('${furl}', '${fname}', '${_esc(f.type || 'text')}')" title="点击预览">
          <div class="ws-gallery-icon">📄</div>
          <div class="ws-gallery-info">
            <span class="ws-gallery-name" title="${fname}">${niceTitle}</span>
            <span class="ws-gallery-size">${fsize}</span>
            ${copyBtn}
          </div>
        </div>`;
    }
  }
  html += '</div>';
  return html;
}

// 卷七十三 P0-2 (2026-06-10) · 文件名 → 人话标题
// 规则:
//   blueprint-20260610_152426.md → "导演蓝图 · 6月10日 15:24"
//   storyboard-20260610_152426.json → "分镜表 · 6月10日 15:24"
//   blueprint-review-... → "蓝图审稿 · ..."
//   _narration_final.txt → "口播稿 (final)"
//   通用: <kind 翻译> · <时间格式化> · 解析失败回 raw 文件名
function _humanizeOutputFileName(name) {
  if (!name) return '(未命名)';
  // 常见 kind 字典
  const KIND_MAP = {
    'blueprint-review': '蓝图审稿',
    'storyboard-review': '分镜审稿',
    'blueprint': '导演蓝图',
    'storyboard': '分镜表',
    'narration': '口播稿',
    'narration_final': '口播稿 (final)',
    '_narration_final': '口播稿 (final)',
    'tts': '配音音频',
    'render': '渲染视频',
    'review': '审稿',
  };
  // 拆 ext
  const m = name.match(/^(.+?)(?:\.(md|json|txt|wav|mp3|mp4|png|jpg|jpeg|webp))?$/);
  if (!m) return name;
  const stem = m[1];
  // 时间戳 pattern: 20260610_152426 / 20260610-152426
  const tsRe = /(\d{4})(\d{2})(\d{2})[_-](\d{2})(\d{2})(\d{2})/;
  const tsMatch = stem.match(tsRe);
  let kindPart = stem;
  let timePart = '';
  if (tsMatch) {
    kindPart = stem.replace(tsMatch[0], '').replace(/[-_]+$/, '');
    const [, , MM, DD, hh, mm] = tsMatch;
    timePart = `${parseInt(MM, 10)}月${parseInt(DD, 10)}日 ${hh}:${mm}`;
  }
  // kind 翻译 (KIND_MAP exact match → 否则保留 stem)
  let kindLabel = KIND_MAP[kindPart] || kindPart;
  if (timePart) return `${kindLabel} · ${timePart}`;
  return kindLabel || name;
}

// 卷七十三 P0-2 · 输出文件预览 modal (md 渲染 / json 高亮 / txt 等宽)
window._openOutputPreview = async function(url, name, type) {
  let backdrop = document.createElement('div');
  backdrop.className = 'confirm-modal-backdrop';

  let wrap = document.createElement('div');
  wrap.className = 'output-preview-modal';
  wrap.innerHTML = `
    <div class="opm-head">
      <span class="opm-title"><i class="ri-file-text-fill"></i> ${_esc(_humanizeOutputFileName(name))}</span>
      <span class="opm-fname"><code>${_esc(name)}</code></span>
      <button class="opm-close" type="button" title="关闭 (ESC)">×</button>
    </div>
    <div class="opm-body"><div class="opm-loading">加载中…</div></div>
    <div class="opm-foot">
      <a class="opm-link" href="${_esc(url)}" target="_blank" rel="noopener"><i class="ri-external-link-line"></i> 新 tab 打开 raw</a>
    </div>
  `;
  const closeIt = () => {
    backdrop.classList.remove('confirm-modal-backdrop-show');
    wrap.classList.remove('output-preview-show');
    setTimeout(() => {
      if (backdrop.parentNode) backdrop.remove();
      if (wrap.parentNode) wrap.remove();
      document.removeEventListener('keydown', escHandler);
    }, 180);
  };
  function escHandler(e) { if (e.key === 'Escape') closeIt(); }
  wrap.querySelector('.opm-close').addEventListener('click', closeIt);
  backdrop.addEventListener('click', closeIt);
  document.addEventListener('keydown', escHandler);

  document.body.appendChild(backdrop);
  document.body.appendChild(wrap);
  requestAnimationFrame(() => {
    backdrop.classList.add('confirm-modal-backdrop-show');
    wrap.classList.add('output-preview-show');
  });

  // 拉内容
  const body = wrap.querySelector('.opm-body');
  try {
    const token = _getToken && _getToken();
    const r = await fetch(url, {
      headers: token ? { 'Authorization': 'Bearer ' + token } : {},
    });
    if (!r.ok) {
      body.innerHTML = `<div class="opm-error">加载失败 [${r.status}] · 试试 "新 tab 打开 raw"</div>`;
      return;
    }
    const text = await r.text();
    const lname = (name || '').toLowerCase();
    if (lname.endsWith('.md')) {
      const md = (window.opusMdRender || ((t) => `<pre>${_esc(t)}</pre>`))(text);
      body.innerHTML = `<div class="opm-md">${md}</div>`;
    } else if (lname.endsWith('.json')) {
      let pretty = text;
      try { pretty = JSON.stringify(JSON.parse(text), null, 2); } catch (e) { /* 保留 raw */ }
      body.innerHTML = `<pre class="opm-pre opm-pre-json">${_esc(pretty)}</pre>`;
    } else {
      body.innerHTML = `<pre class="opm-pre">${_esc(text)}</pre>`;
    }
  } catch (e) {
    body.innerHTML = `<div class="opm-error">网络出错: ${_esc(e.message || String(e))}</div>`;
  }
};

// 复制路径按钮 click 处理 (event delegation 在 _bindEvents 里 · 这里只暴露函数)
window._copyOutputPath = async function(path) {
  if (!path) return;
  try {
    await navigator.clipboard.writeText(path);
    if (window._toast) _toast('路径已复制 · 去文件管理器粘贴'); else alert('路径已复制 · 去文件管理器粘贴');
  } catch (e) {
    // fallback: 创建 input · select · execCommand
    const ta = document.createElement('textarea');
    ta.value = path;
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); if (window._toast) _toast('路径已复制'); else alert('路径已复制'); }
    finally { ta.remove(); }
  }
};

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
    let tpl;
    if (kind === 'app') {
      tpl = '我想要一个 ___ 应用 · 功能是 ___ · 检索本地是否有现成的可调用 (例如 ___) · 没有就写代码 / 启程序 / 装依赖 · 完成后注册到工坊里给我看';
    } else if (kind === 'flow') {
      tpl = '帮我做一条工作流 · 目标是 ___ · 串这几个 app: ___ (按顺序写出来) · 用 steps 二层结构 (主步骤 + 内部 substeps) · 落到 data/workshop/flows/';
    } else {
      tpl = '我想要一个 ___ 工具 (单步动作 · 不是完整应用) · 功能是 ___ · 写到 agent_tools/<name>.py · 注册成工具集里能拖的节点';
    }
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
        : `→ 已塞到主对话框 · BRO 看一眼就按 Enter`);
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
    const tpl = `帮我给应用「${app.name}」(${app.id}) 设计一个 UI 表单 · 看下它的 description / system_prompt / tools · 推断出 BRO 重复用时需要填什么字段 · 然后调 update_app 把 ui_form_schema 塞进去。 设计原则: 字段数 ≤ 5 · 命名清晰 · 必填项最少。 设计完告诉我每个字段是啥意义。`;
    if (typeof window.injectChat === 'function') {
      window.injectChat(tpl, { autosend: false });
      _toast('→ 已塞到主对话框 · BRO 按 Enter 让 OPUS 设计');
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
        body: JSON.stringify({ name, description: desc, litegraph_json: data, created_by: 'BRO' }),
      });
      if (!r.ok) { _toast(`💾 localStorage 已存 · daemon 落档失败 [${r.status}]`); return; }
      const flow = await r.json();
      _flows.unshift({ id: flow.id, name, description: desc, node_count: (data.nodes || []).length, created_at: flow.created_at, created_by: 'BRO' });
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
    token = token || _getToken();
    if (!token) { _toast('需要 token 才能加载远端工作流'); return; }
    // 卷七十二 v3 · BRO 反馈"名字没正常过来" · _apps 还没拉就渲染 → 显示 app id 而非名字
    // 修法: 渲染 steps 前先确保 _apps 加载完 (内部缓存 in-flight promise · 不会重复 fetch)
    if (_apps.length <= BUILTIN_APPS.length) {
      try { await _loadAssetsFromDaemon(); } catch (e) { /* 静默 · 走 fallback 显示 id */ }
    }
    try {
      const r = await fetch('/workshop/flows/' + encodeURIComponent(flow.id), {
        headers: { 'Authorization': 'Bearer ' + token },
      });
      if (!r.ok) { _toast(`加载失败 [${r.status}]`); return; }
      const full = await r.json();
      const graphData = full.litegraph_json;
      if (graphData) {
        _graph.clear();
        _graph.configure(graphData);
        _updateEmpty();
        _renderCanvas();
      } else {
        _graph.clear();
        _updateEmpty();
        _renderCanvas();
      }
      // 卷七十二 · steps 是主 · 拉到就渲染步骤列表 (canvas-as-view 兑现)
      _currentFlowFull = full;
      _activeFlowId = full.id || flow.id;
      _renderStepsPanel(full);
      _renderFlowsSidebar();
      _renderCanvasTrustArea();  // 卷七十二 v4 · 0.2.0 · 顶部显示信任度 + 一键按钮
      // 顶部 toolbar 标题 + 描述
      const nameEl = _container && _container.querySelector('#wsCanvasFlowName');
      const descEl = _container && _container.querySelector('#wsCanvasFlowDesc');
      if (nameEl) nameEl.textContent = full.name || flow.name || flow.id;
      if (descEl) descEl.textContent = full.description || '';
      const sCount = (full.steps || []).length;
      _toast(`📂 已载入 · ${full.name || flow.name}\n  - ${sCount} 步`);
    } catch (e) {
      _toast('加载异常: ' + e.message);
    }
  }

  // 卷七十二 · steps-as-core · 渲染步骤列表卡片到画布下方
  function _renderStepsPanel(flow) {
    if (!_container) return;
    const panel = _container.querySelector('#wsStepsPanel');
    const list = _container.querySelector('#wsStepsList');
    const count = _container.querySelector('#wsStepsCount');
    if (!panel || !list) return;
    const steps = (flow && flow.steps) || [];
    if (steps.length === 0) {
      panel.hidden = true;
      list.innerHTML = '';
      return;
    }
    panel.hidden = false;
    if (count) count.textContent = `${steps.length} 步`;
    list.innerHTML = steps.map((step, idx) => _renderStepCard(step, idx)).join('');
  }

  function _renderStepCard(step, idx) {
    const appRef = step.app || step.app_id || step.app_name || '(?)';
    const meta = _apps.find(a => a.id === appRef || a.name === appRef);
    const icon = meta && meta.icon ? meta.icon : '<i class="ri-puzzle-fill"></i>';
    const name = meta && meta.name ? meta.name : appRef;
    const goal = _escapeHtml(step.goal || step.step_goal || '');
    // 卷六六 BRO 提的"STEPS1 2-1 2-2 STEPS3 STEPS4"二层结构 = substeps (内部 checklist · 不分裂执行)
    const substeps = Array.isArray(step.substeps) ? step.substeps : [];
    const subList = substeps.length
      ? `<ul class="ws-step-substeps">${substeps.map((s, i) => `<li><span class="ws-step-subnum">${idx + 1}-${i + 1}</span>${_escapeHtml(s)}</li>`).join('')}</ul>`
      : '';
    // on_fail 默认值是 "stop" (失败就停 · 这是预期行为) · 只在非默认时才显示 tag
    const onFail = step.on_fail || step.continue_on_error;
    const failTag = (() => {
      if (!onFail || onFail === 'stop') return '';  // 默认行为不冗余显示
      if (onFail === 'continue' || onFail === true) return '<span class="ws-step-tag warn" title="该步失败下一步继续跑">⚠ 容错(continue)</span>';
      if (typeof onFail === 'string' && onFail.startsWith('goto:')) {
        return `<span class="ws-step-tag warn" title="该步失败回跳到第 ${_escapeHtml(onFail.slice(5))} 步">↩ ${_escapeHtml(onFail)}</span>`;
      }
      return `<span class="ws-step-tag warn">${_escapeHtml(String(onFail))}</span>`;
    })();
    return `
      <div class="ws-step-card" data-step-idx="${idx}">
        <div class="ws-step-num">#${idx + 1}</div>
        <div class="ws-step-body">
          <div class="ws-step-app">${icon}<span>${_escapeHtml(name)}</span><span class="ws-step-appid">${_escapeHtml(appRef)}</span>${failTag}</div>
          ${goal ? `<div class="ws-step-goal">${goal}</div>` : ''}
          ${subList}
        </div>
      </div>
    `;
  }

  function _escapeHtml(s) {
    return String(s || '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  // ── 卷七十三 P0 · 跑时实时进度高亮 (画布节点 + 步骤卡两侧同步染色) ──
  // 设计:
  //   - workshop tab 一直在 DOM 时 · 每 2.5s 拉一次 /workshop/runs?status=running
  //   - 找当前打开 flow 的 active run · 拉详情 (step_statuses)
  //   - 染 LiteGraph 节点 (bgcolor) + 步骤卡 (class)
  //   - 没 active run 时退化为 idle (节点恢复默认色)
  //
  // 色板 (chat.css 紫色 + workshop 调和):
  //   pending  → #252525 (默认 dim · 未跑)
  //   running  → #c79931 (橘金 · 走马灯效果)
  //   done     → #3a7d44 (墨绿 · 通过)
  //   failed   → #a13d2d (砖红 · 卡住)
  //   skipped  → #555555 (银灰 · 跳过)
  const STEP_COLORS = {
    pending: '#252525',
    running: '#c79931',
    done:    '#3a7d44',
    failed:  '#a13d2d',
    skipped: '#555555',
  };

  let _runPollTimer = null;
  let _lastRunSignature = '';  // diff cache · 状态没变就别重绘 LiteGraph

  function _startRunPoll() {
    if (_runPollTimer) return;
    // 立即拉一次 + 每 2.5s 一次 · workshop tab 不在 DOM 时自动停 (见 _stopRunPoll)
    _tickRunPoll();
    _runPollTimer = setInterval(_tickRunPoll, 2500);
  }

  function _stopRunPoll() {
    if (_runPollTimer) { clearInterval(_runPollTimer); _runPollTimer = null; }
    _lastRunSignature = '';
  }

  async function _tickRunPoll() {
    // 没打开任何 flow · 不用 poll
    if (!_activeFlowId || !_currentFlowFull) return;
    // 容器不在 DOM 了 · 自我清理
    if (!_container || !document.body.contains(_container)) {
      _stopRunPoll();
      return;
    }
    const token = _getToken && _getToken();
    if (!token) return;
    try {
      // 1. 列所有 running · 通常 0-1 条 · 不贵
      const r = await fetch('/workshop/runs?status=running', {
        headers: { 'Authorization': 'Bearer ' + token },
      });
      if (!r.ok) return;
      const data = await r.json();
      const runs = (data && data.runs) || [];
      // 只关心当前打开 flow 的 run
      const mine = runs.find(rr => rr.flow_id === _activeFlowId);
      if (!mine) {
        // idle · 把节点/卡片恢复默认
        if (_lastRunSignature !== 'idle') {
          _applyStepStatuses(null);
          _lastRunSignature = 'idle';
        }
        return;
      }
      // 2. 拉详情拿每 step 的 status
      const r2 = await fetch('/workshop/runs/' + encodeURIComponent(mine.run_id), {
        headers: { 'Authorization': 'Bearer ' + token },
      });
      if (!r2.ok) return;
      const state = await r2.json();
      const stepsState = (state && state.steps) || [];
      // 用 sig 判 diff (status string 拼起来) · 没变就不重绘
      const sig = mine.run_id + '|' + stepsState.map(s => `${s.idx}:${s.status || 'pending'}`).join(',');
      if (sig === _lastRunSignature) return;
      _lastRunSignature = sig;
      _applyStepStatuses(stepsState);
    } catch (e) {
      // 静默 · 下一轮 tick 再试
    }
  }

  function _applyStepStatuses(stepsState) {
    // stepsState = null → 恢复默认 idle
    // 1. 染 LiteGraph 节点 bgcolor
    if (_graph && _graph._nodes) {
      _graph._nodes.forEach(n => {
        const idx = n.id;  // steps_to_litegraph 让 id = step.idx (1-based)
        if (!stepsState) {
          n.bgcolor = STEP_COLORS.pending;
          n.boxcolor = null;
        } else {
          const st = stepsState.find(s => s.idx === idx);
          const status = (st && st.status) || 'pending';
          n.bgcolor = STEP_COLORS[status] || STEP_COLORS.pending;
          // boxcolor 让 LiteGraph 在节点左上角小灯亮起
          n.boxcolor = status === 'running' ? '#ffd76b' :
                       status === 'done'    ? '#7ee084' :
                       status === 'failed'  ? '#ff8a7a' : null;
        }
      });
      if (_canvas) _canvas.setDirty(true, true);
    }
    // 2. 染步骤面板卡片
    if (_container) {
      const cards = _container.querySelectorAll('.ws-step-card');
      cards.forEach((card, i) => {
        card.classList.remove('is-pending', 'is-running', 'is-done', 'is-failed', 'is-skipped');
        if (!stepsState) {
          card.classList.add('is-pending');
          return;
        }
        const idx = i + 1;
        const st = stepsState.find(s => s.idx === idx);
        const status = (st && st.status) || 'pending';
        card.classList.add('is-' + status);
        // 错误提示 · 失败时露 error string
        const existing = card.querySelector('.ws-step-error');
        if (status === 'failed' && st && st.error) {
          if (!existing) {
            const err = document.createElement('div');
            err.className = 'ws-step-error';
            err.textContent = '✗ ' + st.error;
            card.querySelector('.ws-step-body').appendChild(err);
          }
        } else if (existing) {
          existing.remove();
        }
      });
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

    // 卷七十二 · steps-as-core · canvas-as-view (兑现卷六六承诺)
    // 画布只读: drag/搜框/重连/添加/删除/右键菜单全关; pan + zoom 保留 (要能看大图)
    _canvas.allow_interaction = false;
    _canvas.allow_dragnodes = false;
    _canvas.allow_searchbox = false;
    _canvas.allow_reconnect_links = false;
    _canvas.read_only = true;
    _canvas.getCanvasMenuOptions = () => null;
    _canvas.getNodeMenuOptions = () => null;

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

    // 卷七十三 P0 · workshop tab 一打开就启动实时进度高亮轮询
    _startRunPoll();
  }

  function unmount() {
    _stopRunPoll();
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
