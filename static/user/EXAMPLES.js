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
 *   chat.js / chat.html / chat.css 在内核白名单里 —— 官方升级会覆盖它们。
 *   直接改这几个文件·迟早被盖掉。
 *
 *   而 static/user/ 在 never_sync 里 —— 不管升多少版·你的 user.js / user.css
 *   一个字节都不会被动。 它们排在所有官方资源【之后】加载 → 你的改动总能盖住官方默认。
 *
 *   真想直接改内核文件也行(比如整个重写 chat.js):
 *     改完对 Daemonkey 说「chat.js 我自己管」→ 接管后官方升级物理上不再碰它。
 *     代价: 官方对它的修复也不会自动进来。 后悔了说「取消接管 chat.js」。
 *
 * ---------------------------------------------------------------------------
 * window.Daemonkey —— 官方承诺的接口·会随内核一起维护
 *
 *   Daemonkey.addDomain(key, meta)     加一个自定义维度(侧边栏入口 + 你自己的渲染函数)
 *   Daemonkey.addNavGroup(id, label)   加一个侧边栏分组·opts.before 可指定插在谁前面
 *   Daemonkey.ready(fn)                等页面就绪后执行
 *   Daemonkey.pane()                   中栏容器 DOM
 *   Daemonkey.refresh()                重新渲染当前维度
 *   Daemonkey.currentView()            当前在看哪个维度
 *   Daemonkey.ctx()                    当前会话的 token / 缓存命中等实时数据
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


/* ── 例 3 · 覆盖官方行为 ────────────────────────────────────────────────────
 * 官方函数都在全局作用域·重新赋值就能换掉。 先存原函数·这样还能调回去。

const _origSwitchView = window.switchView;
window.switchView = function (view) {
  console.log('[user] 切到', view);
  return _origSwitchView(view);
};
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
