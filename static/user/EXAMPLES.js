/* ===========================================================================
 * static/user/EXAMPLES.js —— 装修区示例与 API speed sheet
 * ===========================================================================
 *
 * 【这个文件是官方维护的·会随内核升级更新·别改它】(改了下次升级会被覆盖)
 * 想要哪段·复制到同目录的 user.js / user.css —— 那两个文件永远属于你。
 *
 * 更省事的办法:直接跟你的 Daemonkey 说话·让它替你写:
 *     「帮我在对话区加个 token 消耗显示」
 *     「侧边栏调宽一点」
 *     「加一个我自己的面板·放我常看的几个数」
 * 它知道该写哪个文件、该用哪个 API。
 *
 * ---------------------------------------------------------------------------
 * 为什么是这套机制
 *
 *   该写哪一层（升级后还想原样留下、还能打包给别人 → 只写叠层）:
 *
 *     D0 叠层 · 官方升级物理不碰 · 可打成 .dkpkg (kind=mod) 上架市集
 *       data/mods/<id>/          完整 MOD（tools / routes / ui）
 *       agent_tools_user/        本机工具（同名盖住官方工具）
 *       api_routes_user/         本机路由（不要占 /dashboard/{任意}）
 *       static/user/user.js|css  装修区（本文件 EXAMPLES 会被覆盖，别改它）
 *
 *     D2 浅叉 · 内核白名单文件只改了几十行
 *       升级会先 checkpoint + 备份再覆盖。能叠的工具先收成 MOD；叠不了的再合并。
 *
 *     D3 深叉 / 整文件接管
 *       不要整文件揉 chat.js。工具收成 MOD；前端说「用回我的 …」或接管。
 *       接管后官方修复不进盘，但会落到 data/runtime/official_incoming/ 供你摘。
 *
 *   chat.js 已经拆出 depot / clients / panels / rail……但对话主循环仍在 chat.js。
 *   改气泡 / SSE 请等官方钩子或先写 user.js 叠一层；不要 fork 整份内核再升级合并。
 *
 *   已经改过内核、升完想收口：先说「把工具魔改收成 MOD」（只叠能跑的工具）。
 *   叠不了的 chat.js / worker 不会自己跑。要界面回来再说「用回」或「合并」。
 *
 * ---------------------------------------------------------------------------
 * window.Daemonkey —— 官方承诺的接口·会随内核一起维护
 *
 *   Daemonkey.addDomain(key, meta)     加一个自定义维度(侧边栏入口 + 你自己的渲染函数)
 *   Daemonkey.addNavGroup(id, label)   加一个侧边栏分组·opts.before 可指定插在谁前面
 *   Daemonkey.ready(fn)                等页面就绪后执行
 *   Daemonkey.pane()                   中栏容器 DOM (工作台=#detailPane · 陪伴房间=#dashView)
 *   Daemonkey.refresh()                重新渲染当前维度
 *   Daemonkey.currentView()            当前在看哪个维度
 *   Daemonkey.ctx()                    当前会话的 token / 缓存命中等实时数据
 *   Daemonkey.on / off / emit          事件总线（改气泡/看 SSE/切视图 · 不要 fork chat.js）
 *     view:switch       {view, previous}  return false 则官方不切
 *     message:render    {phase, role, text, el}  before 里 return false 则官方不画
 *     sse:event         {type, data}  可改 data；return false 则官方不处理这条
 *
 * 陪伴房间同一套 API: addDomain 挂到房间右边那扇「门」上, 不进侧栏。
 * addNavGroup 在房间里是空操作 (没有导航分组可插), 从工作台抄来的代码不会炸。
 *
 * 改完刷新页面 (F5) 生效·样式没变通常是缓存 → Ctrl+F5 强刷。
 * 你的代码报错不会拖垮主界面·但会记在浏览器控制台 (F12)。
 * =========================================================================== */


/* ── 例 1 · 加一个自己的面板 ────────────────────────────────────────────────
 * 侧边栏多出一个入口·点进去中栏由你的 render 全权渲染 (后端不需要任何配合)。
 * 图标名去 https://remixicon.com 挑·工程已本地化全套图标。
 * section 可选: home / market / ability / studio / ops / execution / plugins
 *              或者先用 addNavGroup 建一个自己的分组。

Daemonkey.addNavGroup('mine', '我的装修', { before: 'plugins' });

Daemonkey.addDomain('mypanel', {
  label: '我的面板',
  icon: 'ri-star-line',
  section: 'mine',
  render(pane) {
    pane.innerHTML = `
      <div class="dash-head"><h2>我的面板</h2></div>
      <div class="dash-empty">想放什么放什么 —— 这块归你。</div>`;
  },
});
*/


/* ── 例 2 · 在对话区显示 token 消耗与缓存命中 ──────────────────────────────
 * Daemonkey.ctx() 就是当前会话的实时上下文数据 (官方自己的用量环也读它)。
 * 字段随版本可能增减 → 先在控制台 console.log(Daemonkey.ctx()) 看看有什么再用。

Daemonkey.ready(() => {
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;right:16px;bottom:88px;z-index:50;'
    + 'padding:6px 10px;border-radius:8px;font-size:12px;opacity:.75;'
    + 'background:var(--panel,#1b1b22);border:1px solid var(--line,#2c2c36)';
  document.body.appendChild(box);
  setInterval(() => {
    const c = Daemonkey.ctx();
    box.textContent = c ? `token ${c.used ?? '?'} · 缓存命中 ${c.cache_hit ?? '?'}` : '等待会话…';
  }, 2000);
});
*/


/* ── 例 3 · 事件总线（改气泡 / 看 SSE · 不要 fork chat.js） ─────────────
 * return false 会跳过官方那一步。能叠就叠，不要整份复制 chat.js。

Daemonkey.on('view:switch', (ev) => {
  console.log('[mod] 切到', ev.view, '从', ev.previous);
});

Daemonkey.on('message:render', (ev) => {
  if (ev.phase !== 'after' || !ev.el) return;
  if (ev.role === 'opus') ev.el.classList.add('mod-bubble');
});

Daemonkey.on('sse:event', (ev) => {
  if (ev.type === 'usage') console.log('[mod] token', ev.data);
});
*/

/* ── 例 4 · 把魔改收成 MOD ──────────────────────────────────────────────
 * 目录: data/mods/token-hud/mod.json + ui/mod.js
 * 对话: 「导出 MOD token-hud」→ 得到 .dkpkg → 别人「导入 MOD <路径>」或上架市集。
 * 工具写 tools/*.py ，路由写 routes/*.py。重启 daemon 后工具/路由生效，前端刷新即可。
 * 本机清单在插件库「我的叠层」。升完自检红了会在插件库打点，点进去看，不必每次测。
 */


/* ===========================================================================
 * 样式示例 —— 下面这些是 CSS·复制到同目录的 user.css (不是这个文件)
 * ===========================================================================
 *
 * 官方颜色都走 CSS 变量·改变量比改具体规则省事得多。 想知道有哪些变量:
 * F12 → Elements → 选中 <body> → Computed 里搜 "--"。
 *
 * 主题切换(深色/浅色/自定义)走 UI 里的主题选择器·存 localStorage 不落文件 →
 * 换主题不会动 user.css·user.css 也不会被换主题冲掉·两者独立。
 *
 *   // 调侧边栏宽度
 *   .nav-rail { width: 240px !important; }
 *
 *   // 换主色调 (只改变量·所有用到它的地方一起变)
 *   body { --accent: #7c9cff; --panel: #17171d; }
 *
 *   // 对话气泡改宽、字大一点
 *   .msg { max-width: 90% !important; }
 *   .msg .bubble { font-size: 15px; line-height: 1.7; }
 *
 * =========================================================================== */
