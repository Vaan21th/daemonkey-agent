/* ═══════════════════════════════════════════════════════════════
   DAIMON 陪伴模式 · 中间栏渲染层 (panels.js)
   2026-08-26 收口: 两边一字不差的 96 个函数已搬到 /static/dashboard-panels.js
   (本文件之前加载)。这里只留陪伴适配层 + 已漂移/独有的函数。
   ─ 复用母体全部 dash-* / fav-* / kb-* / rp-* / report-card 类样式
     (index.html 引入 /static/chat.css · 弹窗容器 id="dashView" 零修改命中)
   ─ 主题: 容器挂 .theme-sepia (日间纸色) / .theme-sunset (夜间灯下)
   ═══════════════════════════════════════════════════════════════ */

// ── 环境适配层 (母体全局 → 陪伴模式) ────────────────────────────
var token = (typeof _loopbackAuthToken === 'function')
  ? _loopbackAuthToken()
  : (function () {
      try {
        const t = localStorage.getItem('opus_ui_token') || '';
        if (t) return t;
      } catch (e) {}
      const h = (location.hostname || '').replace(/^\[|\]$/g, '').toLowerCase();
      if (h === '127.0.0.1' || h === 'localhost' || h === '::1') return '__loopback__';
      return '';
    })();
const $dashView = document.getElementById('dashView');   // 弹窗内容容器 · 与母体同 id · 移植代码零修改
let currentView = null;          // 与母体同名全局 · renderFeasibility 等内部引用

function _depotTabs(domain) {     // 成长档案标签条 · 转给 depot.js (它在本文件之后加载)
  if (typeof _maybeDepotTabs === 'function') _maybeDepotTabs(domain);
}
function _splitMissing() {}       // 占位 · 下面被抽取的正式版覆盖
function backToChat() { if (typeof closeModal === 'function') closeModal(); }
function switchView(v) { loadDashboard(v); }   // 母体导航切换 → 陪伴弹窗内切换
function showChatToast(msg) { if (typeof setStatus === 'function') setStatus(msg); }
var STORAGE = {
  token: 'opus_ui_token',
  session: 'opus_ui_session',
  autoConfirm: 'opus_ui_auto_confirm',
  aliases: 'opus_ui_session_aliases',
};
var sessionId = '';
var autoConfirm = (function () {
  try { return localStorage.getItem(STORAGE.autoConfirm) || 'confirm'; } catch (e) { return 'confirm'; }
})();
function addSys(msg) { if (typeof setStatus === 'function') setStatus(String(msg || '')); }
function updateCurrentLabel() {}

function opusConfirm(opts) {      // 母体 _omQueue modal 系统太重 · 陪伴模式降级原生 confirm
  return Promise.resolve(window.confirm((opts && opts.message) || '确认操作？'));
}
function opusAlert(opts) {
  alert(typeof opts === 'string' ? opts : ((opts && opts.message) || '提示'));
  return Promise.resolve();
}
// 深挖 / 心愿按钮 → 关弹窗 · 把 prompt 发进陪伴对话 (IP 进 working 态)
async function spawnTask(prompt, taskLabel) {
  if (typeof closeModal === 'function') closeModal();
  if (typeof sendCompanionText === 'function') sendCompanionText(prompt);
  return null;
}
function spawnQuickly(prompt, label) { return spawnTask(prompt, label); }

async function _ensureLoopbackToken() {
  if (token) return true;
  if (typeof _loopbackAuthToken === 'function') token = _loopbackAuthToken();
  else {
    const h = (location.hostname || '').replace(/^\[|\]$/g, '').toLowerCase();
    if (h === '127.0.0.1' || h === 'localhost' || h === '::1') token = '__loopback__';
  }
  return !!token;
}

// ── loadDashboard 陪伴版 (移植自母体 chat.js:11780 · 去掉 workshop/depot 等特殊分支) ──
async function loadDashboard(domain, opts = {}) {
  if (typeof loadDashboard._seq !== 'number') loadDashboard._seq = 0;
  const seq = ++loadDashboard._seq;
  const stale = () => seq !== loadDashboard._seq;
  if (!domain) return;
  // 目标维度住在别的家具里时 · 把那件家具开出来 (链路面包屑/深挖按钮走这条)
  if (typeof syncSpotForDomain === 'function' && syncSpotForDomain(domain)) return;
  // Grok-2 轮 · 2026-08-27 · workshop 是挂载式视图 (companion.js mountWorkshop) ·
  // syncSpotForDomain 对"当前家具就是工作台 / depot 视图"会 return false → 这里兜底直挂 · 修死按钮
  if (domain === 'workshop') {
    if (typeof mountWorkshop === 'function') { mountWorkshop(); return; }
  }
  // 母体这里不动 currentView (只有导航切换才设) · 成长档案 hub 靠 currentView='depot' 判断要不要补标签条
  if (currentView !== 'depot') currentView = domain;
  document.querySelectorAll('.modal-tab').forEach(b => {
    b.classList.toggle('active', b.dataset.domain === domain);
  });
  // 0.9.6 · user.js 注册的维度没有 /dashboard/<它> · 渲染交给用户自己 · 也不挡在 token 门后
  const _ud = window.Daemonkey && Daemonkey._domains && Daemonkey._domains[domain];
  if (_ud && typeof _ud.render === 'function') {
    try { await _ud.render($dashView, opts); }
    catch (e) { $dashView.innerHTML = `<div class="dash-empty">用户面板「${domain}」渲染出错<br>${e.message}</div>`; }
    return;
  }
  if (domain === 'care') { loadCareDesk(); return; }
  if (!token) await _ensureLoopbackToken();
  if (!opts.silent) $dashView.innerHTML = dashLoadingHTML();

  // 成长档案三个子页端点不在 /dashboard/* 下 (母体 chat.js:11827-11874 同款)
  const ALT_URL = { sinks: '/sinks', reviews: '/reviews', diary: '/dashboard/cognition' };
  if (ALT_URL[domain] || domain === 'memory_map') {
    if (domain === 'memory_map' && typeof memoryMapLoadingHTML === 'function') {
      $dashView.innerHTML = memoryMapLoadingHTML();   // 后端现算 PCA · 1-3s
    }
    try {
      const r = await fetch(ALT_URL[domain] || '/dashboard/memory_map', {
        headers: { 'Authorization': 'Bearer ' + token },
      });
      if (stale()) return;
      if (!r.ok) { $dashView.innerHTML = `<div class="dash-empty">加载失败 [${r.status}]</div>`; return; }
      const data = await r.json();
      if (stale()) return;
      if (domain === 'sinks') renderSinks(data);
      else if (domain === 'reviews') renderReviews(data);
      else if (domain === 'diary') renderDiary(data);
      else renderMemoryMap(data);
      _depotTabs(domain);
    } catch (e) { $dashView.innerHTML = `<div class="dash-empty">网络出错: ${e.message}</div>`; }
    return;
  }

  try {
    const r = await fetch(`/dashboard/${domain}${opts.refresh ? '?refresh=true' : ''}`, {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (stale()) return;
    if (!r.ok) { $dashView.innerHTML = `<div class="dash-empty">加载失败 [${r.status}]</div>`; return; }
    const data = await r.json();
    if (stale()) return;
    if (domain === 'radar') renderRadar(data);
    else if (domain === 'cognition') renderCognition(data);
    else if (domain === 'playbooks') renderPlaybooks(data);
    else if (domain === 'wishlist') renderWishlist(data);
    else if (domain === 'she_state') { if (typeof renderSheState === 'function') renderSheState(data); }
    else if (domain === 'trends') renderTrends(data);
    else if (domain === 'reports') renderReports(data);
    else if (domain === 'opportunities') renderOpportunities(data);
    else if (domain === 'feasibility') renderFeasibility(data);
    else if (domain === 'knowledge') renderKnowledge(data);
    else if (domain === 'execution') renderExecution(data);
    else if (domain === 'favorites') renderFavorites(data);
    else if (domain === 'scheduled_tasks') renderScheduledTasks(data);
    else renderDashboardStub(domain, data);
    _depotTabs(domain);
  } catch (e) {
    $dashView.innerHTML = `<div class="dash-empty">网络出错: ${e.message}</div>`;
  }
}


// ── 母体 chat.js:1402-1464 · 列表过滤器 renderListFilter / _initListFilter / _applyListFilter ──

let _listFilterInited = false;
function _applyListFilter(input) {
  const q = (input.value || '').trim().toLowerCase();
  const sel = input.dataset.filterTarget;
  if (!sel) return;
  // 搜索范围限制在 input 的 dashboard 容器内 (避免误匹配其他 view 残留 DOM)
  const root = input.closest('#detailPane, #dashView') || document;
  const items = root.querySelectorAll(sel);
  let visible = 0;
  items.forEach(it => {
    const text = (it.textContent || '').toLowerCase();
    const match = !q || text.includes(q);
    it.style.display = match ? '' : 'none';
    if (match) visible++;
  });
  const wrap = input.closest('.list-filter');
  if (wrap) {
    const stats = wrap.querySelector('.list-filter-stats');
    if (stats) stats.textContent = q ? `${visible} / ${items.length}` : `${items.length} 条`;
    const clear = wrap.querySelector('[data-filter-clear]');
    if (clear) clear.hidden = !q;
  }
}
_initListFilter();

// ── 母体 chat.js:6761-7115 · mdRender · 母体完整 markdown 渲染器 ──
function mdRender(text, opts) {
  if (text == null) return '';
  if (typeof text !== 'string') text = String(text);

  // 卷六十四续十一 · 流式期间媒体占位 · 防 <video>/<audio>/<img> 每帧 innerHTML 重建被反复
  // 销毁+重载导致闪烁。streaming=true 时所有媒体先渲成轻量占位 chip · finalize 时(不传 opts)
  // 才出真播放器·整段只建一次·最终结果跟以前完全一致。
  const _streaming = opts === true || (opts && opts.streaming === true);
  function _mediaPending(kind, url) {
    const icon = kind === 'video' ? '<i class="ri-film-line"></i>'
      : (kind === 'audio' ? '<i class="ri-music-2-line"></i>' : '<i class="ri-image-line"></i>');
    const label = kind === 'video' ? '视频' : (kind === 'audio' ? '音频' : '图片');
    let name = String(url || '').split(/[?#]/)[0].split(/[\\/]/).pop() || '';
    name = name.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    return `<span class="md-media-pending">${icon} ${label}${name ? ' · ' + name : ''}</span>`;
  }

  // 提取 ``` block code · 先占位 · 避免后面 inline 转换破坏
  const codeBlocks = [];
  text = text.replace(/```([a-zA-Z0-9_+-]*)\n?([\s\S]*?)```/g, (m, lang, code) => {
    const idx = codeBlocks.length;
    codeBlocks.push({ lang: (lang || '').trim(), code });
    return `\x00CODEBLOCK${idx}\x00`;
  });

  // 提取 `inline code`
  const inlineCodes = [];
  text = text.replace(/`([^`\n]+)`/g, (m, c) => {
    const idx = inlineCodes.length;
    inlineCodes.push(c);
    return `\x00INLINE${idx}\x00`;
  });

  // 卷六十四续九 · LLM 有时直接写原始 <video>/<audio> HTML 标签 (不走 markdown)。
  // 转义前抽出来·只保留 src + controls·渲染成干净播放器 (丢 width/style 等属性防 XSS)·
  // 占位符避开后面的实体转义。_safeUrl 是函数声明·已 hoist·这里可用。
  const mediaTags = [];
  function _pushMedia(html) {
    const idx = mediaTags.length;
    mediaTags.push(html);
    return `\x00MEDIA${idx}\x00`;
  }
  text = text.replace(/<video\b[^>]*?\bsrc\s*=\s*["']([^"'<>]+)["'][^>]*?>(?:\s*<\/video\s*>)?/gi, (m, src) => {
    const u = _safeUrl(src);
    if (u === '#') return m;
    return _pushMedia(_streaming ? _mediaPending('video', u) : `<video controls preload="metadata" src="${u}" class="md-video"></video>`);
  });
  text = text.replace(/<audio\b[^>]*?\bsrc\s*=\s*["']([^"'<>]+)["'][^>]*?>(?:\s*<\/audio\s*>)?/gi, (m, src) => {
    const u = _safeUrl(src);
    if (u === '#') return m;
    return _pushMedia(_streaming ? _mediaPending('audio', u) : `<audio controls preload="metadata" src="${u}" class="md-audio"></audio>`);
  });
  text = text.replace(/<img\b[^>]*?\bsrc\s*=\s*["']([^"'<>]+)["'][^>]*?>/gi, (m, src) => {
    const u = _safeUrl(src);
    if (u === '#') return m;
    return _pushMedia(_streaming ? _mediaPending('img', u) : `<img src="${u}" alt="" loading="lazy" class="md-img" data-full="${u}">`);
  });

  // 转 HTML 实体
  text = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

  // 卷四十四 K stage 2c++ · wish-f3b4958e · URL scheme 安全闸
  // 阻断 javascript: / data: / vbscript: / file: 这些可执行脚本协议
  // 允许: 协议相对(//)·绝对路径(/)·http(s)·相对路径(./.. word)
  function _safeUrl(u) {
    if (!u) return '#';
    const s = String(u).trim();
    if (/^(javascript|data|vbscript|file):/i.test(s)) return '#';
    return s.replace(/"/g, '%22');
  }

  // 卷四十四 K stage 2c++ · 图片 / 音频 / 视频 · ![alt](url) 必须先于 [text](url) 处理
  // 按后缀分流: 图 → <img>·.wav/.mp3 → <audio>·.mp4/.webm → <video>·其他 → 链接
  text = text.replace(
    /!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)/g,
    (m, alt, url, title) => {
      const safeUrl = _safeUrl(url);
      const safeAlt = String(alt || '').replace(/"/g, '&quot;');
      const t = title ? ` title="${String(title).replace(/"/g, '&quot;')}"` : '';
      const lower = safeUrl.toLowerCase();
      if (/\.(wav|mp3|ogg|flac|m4a|aac)(\?|$)/.test(lower)) {
        return _streaming ? _mediaPending('audio', safeUrl) : `<audio controls preload="metadata" src="${safeUrl}"${t} class="md-audio"></audio>`;
      }
      if (/\.(mp4|webm|mov)(\?|$)/.test(lower)) {
        return _streaming ? _mediaPending('video', safeUrl) : `<video controls preload="metadata" src="${safeUrl}"${t} class="md-video"></video>`;
      }
      // 图: 点击弹 lightbox 看大图 (卷四十六补丁 wish-3afebd2c · 不再开新 tab)
      // data-full 留给 lightbox handler · 右键"在新标签打开图片"浏览器原生仍可
      return _streaming ? _mediaPending('img', safeUrl) : `<img src="${safeUrl}" alt="${safeAlt}"${t} loading="lazy" class="md-img" data-full="${safeUrl}">`;
    }
  );

  // 链接 [text](url)
  text = text.replace(
    /\[([^\]]+)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)/g,
    (m, label, url, title) => {
      const safeUrl = _safeUrl(url);
      const t = title ? ` title="${String(title).replace(/"/g, '&quot;')}"` : '';
      return `<a href="${safeUrl}" target="_blank" rel="noopener"${t}>${label}</a>`;
    }
  );

  // 卷六十四续九 · 裸 URL 自动识别 (markdown []/![] 都没用·LLM 直接甩链接的情况)。
  // 视频/音频/图 → 内联播放器/图 (聊天窗口里直接看);其他 → 可点链接 (新标签打开)。
  // 守卫: 前导是行首/空白/( · 避开上面刚生成的 <a href="..."> / <video src="..."> 里的 URL
  // (那些 URL 前是 ")·这里不会误吞)。已 placeholder 的 code/media 不含裸 URL·天然安全。
  function _mediaOrLink(url) {
    const safeUrl = _safeUrl(url);
    const lower = url.toLowerCase();
    if (/\.(mp4|webm|mov)(\?|$)/.test(lower)) {
      return _streaming ? _mediaPending('video', safeUrl) : `<video controls preload="metadata" src="${safeUrl}" class="md-video"></video>`;
    }
    if (/\.(wav|mp3|ogg|flac|m4a|aac)(\?|$)/.test(lower)) {
      return _streaming ? _mediaPending('audio', safeUrl) : `<audio controls preload="metadata" src="${safeUrl}" class="md-audio"></audio>`;
    }
    if (/\.(png|jpe?g|gif|webp|bmp|svg)(\?|$)/.test(lower)) {
      return _streaming ? _mediaPending('img', safeUrl) : `<img src="${safeUrl}" alt="" loading="lazy" class="md-img" data-full="${safeUrl}">`;
    }
    // 卷八十一 · C 方案 · 文档卡片 (docx/md/pdf/xlsx/pptx/txt/zip) · 内嵌 预览/应用打开 按钮
    const docM = lower.match(/\.(docx?|md|pdf|xlsx?|pptx?|txt|zip)(\?|$)/);
    if (docM) {
      const ext = docM[1];
      const name = _safeDecode(url.split('?')[0].split('/').pop() || '文档');
      const dm = url.match(/^\/(?:workshop\/(?:preview|file|outputs)\/|reports\/)?([^/]+)\/([^/?]+)/);
      const domain = dm ? dm[1] : '';
      const filename = dm ? dm[2] : '';
      const isPreviewable = ['md','txt','png','jpg','jpeg','gif','webp','mp3','wav','mp4','webm','pdf'].includes(ext);
      const btn = (ic, label, fn) => `<button class="mdc-btn" onclick="event.stopPropagation();${fn}('${jsStr(domain)}','${jsStr(filename)}','${jsStr(ext)}')" title="${label}"><i class="${ic}"></i>${label}</button>`;
      return `<div class="md-doc-card" data-ext="${ext}" data-url="${safeUrl}" data-domain="${domain}" data-filename="${filename}">
        <span class="mdc-ic">${_docIcon(ext)}</span>
        <span class="mdc-body">
          <span class="mdc-name">${escHtml(name)}</span>
          <span class="mdc-meta">${ext.toUpperCase()}</span>
          <span class="mdc-actions">
            ${isPreviewable ? btn('ri-eye-line','预览','_docOpenInBrowser') : ''}
            ${btn('ri-mac-line','应用打开','_docOpenLocal')}
            ${btn('ri-save-3-line','另存为','_docSaveAs')}
          </span>
        </span>
      </div>`;
    }
    return `<a href="${safeUrl}" target="_blank" rel="noopener">${url}</a>`;
  }
  // (a) 完整 http(s) URL
  text = text.replace(/(^|[\s(])(https?:\/\/[^\s<>"']+)/g, (m, pre, url) => {
    let tail = '';
    const tm = url.match(/[)\].,;!?·，。；！？、"']+$/);
    if (tm) { tail = tm[0]; url = url.slice(0, -tail.length); }
    return pre + _pushMedia(_mediaOrLink(url)) + tail;
  });
  // (b) 根相对的【媒体】路径 (如 /workshop/outputs/x.mp4)·只认带媒体后缀的·防误吞普通 /路径
  text = text.replace(
    /(^|[\s(])(\/[^\s<>"']+\.(?:mp4|webm|mov|wav|mp3|ogg|flac|m4a|aac|png|jpe?g|gif|webp|bmp)(?:\?[^\s<>"']*)?)/gi,
    (m, pre, url) => pre + _pushMedia(_mediaOrLink(url))
  );

  // bold (优先于 italic) · **x** 和 __x__
  text = text.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
  text = text.replace(/__([^_\n]+)__/g, '<strong>$1</strong>');

  // italic · *x* 和 _x_ · 但不要碰已经 <strong>
  // 卷四十六补丁 (wish-3afebd2c) · `_` 必须 word boundary (CommonMark / GFM 标准)
  // 防 url path 里 `_` 被当 italic 起始 · 例如 Yoimiya_d2f7caf194/01.jpg + target="_blank"
  // 会被旧 regex 配对成 italic · 把 href 和 target 一起 wrap 进 <em> · 点开 404
  text = text.replace(/(^|[^*])\*([^*\n]+)\*([^*]|$)/g, '$1<em>$2</em>$3');
  text = text.replace(/(^|[^a-zA-Z0-9_])_([^_\n]+)_(?=$|[^a-zA-Z0-9_])/g, '$1<em>$2</em>');

  // 按行处理 block 元素：headers / hr / lists / blockquote / table / 段落
  const lines = text.split('\n');
  const out = [];
  let listType = null; // 'ul' | 'ol' | null
  let listBuf = [];
  let inBlockquote = false;
  let bqBuf = [];
  let para = [];

  function flushPara() {
    if (para.length) {
      out.push(`<p>${para.join('<br>')}</p>`);
      para = [];
    }
  }
  function flushList() {
    if (listType && listBuf.length) {
      out.push(`<${listType}>${listBuf.map(li => `<li>${li}</li>`).join('')}</${listType}>`);
    }
    listType = null;
    listBuf = [];
  }
  function flushBq() {
    if (inBlockquote && bqBuf.length) {
      out.push(`<blockquote>${bqBuf.join('<br>')}</blockquote>`);
    }
    inBlockquote = false;
    bqBuf = [];
  }

  // 卷三十 · markdown 表格支持
  // 把一行 "| a | b |" 切成 ['a', 'b']
  function parseTableRow(line) {
    let s = line.trim();
    if (s.startsWith('|')) s = s.slice(1);
    if (s.endsWith('|')) s = s.slice(0, -1);
    return s.split('|').map(c => c.trim());
  }
  // 分隔符行 "|---|:---:|---:|" → [null, 'center', 'right']
  function parseAlignRow(line) {
    return parseTableRow(line).map(c => {
      const t = c.trim();
      if (/^:-+:$/.test(t)) return 'center';
      if (/^:-+$/.test(t)) return 'left';
      if (/^-+:$/.test(t)) return 'right';
      return null;
    });
  }
  // 判断这行长得像分隔符行 |---| / |:---:| / |---:|
  function isAlignRow(line) {
    const s = line.trim();
    if (!s.includes('-')) return false;
    if (!s.includes('|')) return false;
    return /^\|?[\s:|-]+\|?$/.test(s) && /-{3,}|-+/.test(s);
  }
  function renderTable(head, align, body) {
    const th = head.map((h, i) => {
      const a = align[i] ? ` style="text-align:${align[i]}"` : '';
      return `<th${a}>${h}</th>`;
    }).join('');
    const tr = body.map(row => {
      const tds = row.map((c, i) => {
        const a = align[i] ? ` style="text-align:${align[i]}"` : '';
        return `<td${a}>${c == null ? '' : c}</td>`;
      }).join('');
      return `<tr>${tds}</tr>`;
    }).join('');
    return `<div class="md-table-wrap"><table class="md-table"><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>`;
  }

  for (let lineI = 0; lineI < lines.length; lineI++) {
    const rawLine = lines[lineI];
    const line = rawLine.trimEnd();

    // 空行 → 段落分隔
    if (!line.trim()) {
      flushPara(); flushList(); flushBq();
      continue;
    }

    // 表格检测（current 行 | 列 |·下一行是分隔符）
    if (line.includes('|') && lineI + 1 < lines.length && isAlignRow(lines[lineI + 1])) {
      flushPara(); flushList(); flushBq();
      const headCells = parseTableRow(line);
      const align = parseAlignRow(lines[lineI + 1]);
      // 对齐数组长度补齐到表头列数
      while (align.length < headCells.length) align.push(null);
      const bodyRows = [];
      let j = lineI + 2;
      while (j < lines.length) {
        const r = lines[j];
        if (!r.trim() || !r.includes('|')) break;
        // 防御：分隔符行不该出现在 body · 出现也跳过
        if (isAlignRow(r)) { j++; continue; }
        const cells = parseTableRow(r);
        // 列数对齐到表头
        while (cells.length < headCells.length) cells.push('');
        if (cells.length > headCells.length) cells.length = headCells.length;
        bodyRows.push(cells);
        j++;
      }
      out.push(renderTable(headCells, align, bodyRows));
      lineI = j - 1;
      continue;
    }

    // 横线
    if (/^---+$/.test(line) || /^\*\*\*+$/.test(line)) {
      flushPara(); flushList(); flushBq();
      out.push('<hr>');
      continue;
    }
    // headers
    const h = /^(#{1,6})\s+(.+)$/.exec(line);
    if (h) {
      flushPara(); flushList(); flushBq();
      out.push(`<h${h[1].length}>${h[2]}</h${h[1].length}>`);
      continue;
    }
    // 无序列表
    const ul = /^[\-*+]\s+(.+)$/.exec(line);
    if (ul) {
      flushPara(); flushBq();
      if (listType !== 'ul') { flushList(); listType = 'ul'; }
      listBuf.push(ul[1]);
      continue;
    }
    // 有序列表
    const ol = /^(\d+)\.\s+(.+)$/.exec(line);
    if (ol) {
      flushPara(); flushBq();
      if (listType !== 'ol') { flushList(); listType = 'ol'; }
      listBuf.push(ol[2]);
      continue;
    }
    // 引用
    const bq = /^>\s?(.*)$/.exec(line);
    if (bq) {
      flushPara(); flushList();
      inBlockquote = true;
      bqBuf.push(bq[1]);
      continue;
    }
    // 普通段落行
    flushList(); flushBq();
    para.push(line);
  }
  flushPara(); flushList(); flushBq();

  let html = out.join('');

  // 还原 inline code
  html = html.replace(/\x00INLINE(\d+)\x00/g, (m, i) => {
    const code = inlineCodes[+i];
    return `<code>${code
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')}</code>`;
  });

  // 还原 block code
  html = html.replace(/\x00CODEBLOCK(\d+)\x00/g, (m, i) => {
    const { lang, code } = codeBlocks[+i];
    const escaped = code
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
    const cls = lang ? ` class="lang-${lang}"` : '';
    return `<pre><code${cls}>${escaped}</code></pre>`;
  });

  // 卷六十四续九 · 还原媒体占位符 (原始 <video>/<audio> 标签 + 裸 URL 自动链接的产物)
  html = html.replace(/\x00MEDIA(\d+)\x00/g, (m, i) => mediaTags[+i] || '');

  return html;
}
// 卷四十六续 11 补丁 · 暴露给 workshop.js 等其他 module 复用 (e.g. opus app 系统提示词渲染)
try { window.opusMdRender = mdRender; } catch (e) { /* 顶层环境异常 · 跳过 */ }

// wish-3fef4bc7 · helpers 接受可选 target container · 不传 = 操作 active session ($msgs)
// 这样 78 处现存调用不动 · send 内的调用传 state.$container 即可路由到正确 session
// 卷四十六续 3 · opts.forceScroll · 默认软滚 (BRO 拖滚动条看历史时 LLM 输出不强行刷回底)
//   用户发消息 / 错误 / 必须看到的卡片 → 调方显式传 { forceScroll: true }

// ── 母体 chat.js:11760-11767 · _splitMissing ──
function _splitMissing(name) {
  if (typeof $dashView === 'undefined' || !$dashView) return;
  $dashView.innerHTML = `<div class="dash-head"><h2>${name}</h2></div>`
    + `<div class="dash-empty">这个维度的前端模块正在升级到位<br>重启 daemon 后刷新页面 (F5) 即可恢复。</div>`;
}
// 通用加载态 · 三点脉冲 (2026-08-20 · 实测 calendar 4.8s / wishlist 2.3s / radar 0.45s ·
//   纯文字"加载中…"在秒级等待里太单薄。 星尘是星图专属 · 这里用克制的三点。
//   text 参数给慢 tab 配专属文案 · 颜色全走 CSS 变量 · 深浅肤自适应)

// ── 母体 chat.js:11768-11777 · dashLoadingHTML ──
function dashLoadingHTML(text) {
  return `<style>
@keyframes dkLdDot { 0%,60%,100%{transform:translateY(0);opacity:.35} 30%{transform:translateY(-6px);opacity:1} }
.dkLdDot { display:inline-block; width:7px; height:7px; border-radius:50%; background:var(--accent,#8a7dff); animation:dkLdDot 1.2s ease-in-out infinite; }
</style>
<div class="dash-empty" style="display:flex;flex-direction:column;align-items:center;gap:14px;padding-top:80px">
  <div><span class="dkLdDot"></span> <span class="dkLdDot" style="animation-delay:.15s"></span> <span class="dkLdDot" style="animation-delay:.3s"></span></div>
  <div style="font-size:12px;color:var(--dim);letter-spacing:1px">${text || '加载中'}</div>
</div>`;
}

// ── 母体 chat.js:12294-12312 · renderDashboardStub ──
function renderDashboardStub(domain, data) {
  const m = DOMAIN_META[domain] || {};
  $dashView.innerHTML = `
    <div class="dash-head">
      <h2>${m.icon || ''} ${m.label || domain}</h2>
      <button onclick="backToChat()">✕ 收起</button>
    </div>
    <div class="dash-stub">
      <h3>这个维度还在开发中</h3>
      <div>${data && data.note ? data.note : '见 docs/STUDIO-LAYOUT.md 第五章 MVP 优先级'}</div>
      <div style="margin-top:14px; font-size:11px;">
        想加快这一维度？回对话跟 OPUS 说：「优先做 ${m.label || domain} 维度」
      </div>
    </div>`;
}

// ─────────────────────────────────────────────────────────
// 卷二十九 · <i class="ri-bar-chart-fill"></i> 可行性分析（能力对照分组）
// ─────────────────────────────────────────────────────────

// ── 母体 chat.js:13898-13913 · escHtml / jsStr ──

// wish-b199c9fa · inline onclick JS 字符串参数专用转义 (双层·顺序不能反):
//   1) JS 层: \ → \\ · ' → \' · 换行 → \n 字面量 (防 JS 字符串被提前闭合)
//   2) HTML 层: & < > " → 实体 (防属性本身被截断)
// 为什么不能只用 escHtml: escHtml 把 ' 转 &#39; 但浏览器解析属性时解码回 ' → onclick="fn('${jsStr(x)}')" 仍会断。
function jsStr(v) {
  var s = String(v == null ? '' : v);
  s = s.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\r?\n/g, '\\n');
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}


// ── 母体 chat.js:13914-13925 · formatRadarTime ──
function formatRadarTime(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso.length > 30 ? iso.slice(0, 30) : iso;
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit',
                                        hour: '2-digit', minute: '2-digit',
                                        hour12: false });
  } catch { return ''; }
}

// 卷二十七 · 工作室链路 breadcrumb · 雷达/趋势/报告 互相导航

// ── 母体 chat.js:13926-13942 · pipelineBreadcrumb · 雷达→趋势→报告链路导航 ──
function pipelineBreadcrumb(current) {
  const stages = [
    { id: 'radar',   icon: '<i class="ri-radar-fill"></i>', label: '雷达',   hint: '原料层 · 多源抓取' },
    { id: 'trends',  icon: '<i class="ri-line-chart-fill"></i>', label: '趋势',   hint: '提炼层 · OPUS 军师视图' },
    { id: 'reports', icon: '<i class="ri-article-fill"></i>', label: '报告',   hint: '成品层 · 正式 docx 出货' },
  ];
  const parts = stages.map((s, i) => {
    const active = (s.id === current) ? ' active' : '';
    const arrow = i > 0 ? '<span class="pl-arrow">→</span>' : '';
    return arrow +
      `<button class="pl-stage${active}" onclick="loadDashboard('${s.id}')" ` +
      `title="${escHtml(s.hint)}">${s.icon} ${s.label}</button>`;
  }).join('');
  return `<div class="pipeline" title="OPUS 信息流水线 · 点击切换维度">${parts}</div>`;
}

// 卷二十七 · 简易 inline SVG 直方图（信源贡献）

// ── 母体 chat.js:13943-14015 · toggleSourceHistogram / renderSourceHistogram ──

function renderSourceHistogram(meta, scopeLabel) {
  const scoped = scopeLabel ? ` · ${escHtml(scopeLabel)}` : '';
  // 选了具体领域但该领域没源 → 引导加源 (BRO 2026-06-03 · 信源跟领域走·add_source 后端已支持 domain)
  const emptyHint = scopeLabel
    ? `<div class="radar-histogram"><div class="rh-title">信源贡献${scoped}</div><div class="sh-empty">这个领域还没有专属信源 · 跟 OPUS 说「给「${escHtml(scopeLabel)}」加个信息源」</div></div>`
    : '';
  if (!meta || meta.length === 0) return emptyHint;
  const okMeta = meta.filter(m => m.ok || m.fetched > 0);
  if (okMeta.length === 0) return emptyHint;
  okMeta.sort((a, b) => (b.fetched || 0) - (a.fetched || 0));
  const maxN = Math.max(...okMeta.map(m => m.fetched || 0), 1);
  const width = 100;
  const barHeight = 18;
  const labelW = 110;
  const valueW = 35;
  const total = okMeta.length;
  const MAX_VISIBLE = 3;
  const hasMore = total > MAX_VISIBLE;
  const collapsedHeight = MAX_VISIBLE * (barHeight + 4);
  const fullHeight = total * (barHeight + 4);
  const svgHeight = hasMore ? collapsedHeight : fullHeight;

  let bars = '';
  okMeta.forEach((m, i) => {
    const y = i * (barHeight + 4);
    const w = Math.max(2, (m.fetched / maxN) * width);
    const fail = !m.ok;
    const color = fail ? 'var(--red)' : 'var(--opus)';
    const display = (m.display || m.source || '').slice(0, 14);
    const barSvg = `
      <text x="0" y="${y + barHeight - 5}" class="sh-label" fill="var(--dim)">${escHtml(display)}</text>
      <rect x="${labelW}" y="${y}" width="${w}" height="${barHeight}" fill="${color}" opacity="0.7" rx="2"></rect>
      <text x="${labelW + w + 5}" y="${y + barHeight - 5}" class="sh-value" fill="var(--text)">${m.fetched}</text>`;
    if (hasMore && i >= MAX_VISIBLE) {
      bars += `
      <g class="sh-collapsed" style="display:none">${barSvg}
      </g>`;
    } else {
      bars += barSvg;
    }
  });

  let html = `
    <div class="radar-histogram">
      <div class="rh-title">信源贡献${scoped}</div>
      <svg width="100%" height="${svgHeight}" viewBox="0 0 ${labelW + width + valueW} ${svgHeight}"
           preserveAspectRatio="xMinYMid meet" data-full-height="${fullHeight}" data-collapsed-height="${collapsedHeight}">${bars}</svg>`;
  if (hasMore) {
    html += `
      <button class="sh-toggle-btn" onclick="toggleSourceHistogram(this)">+ 显示剩余 ${total - MAX_VISIBLE} 个信源</button>`;
  }
  html += `
    </div>`;
  return html;
}

// 定时任务卡片 · 收在 dashboard-panels.js renderScheduledTasks

// ── 卷二十六 · 工坊维度 · content / design / dev / docs ──

// ── 母体 chat.js:12320-12395 · 可行性分析 renderFeasibility ──
function renderFeasibility(data) {
  if (data && data.error) {
    $dashView.innerHTML = `
      <div class="dash-head"><h2><i class="ri-bar-chart-fill"></i> 可行性分析</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }

  // 列表视图 · list_feasibility 返回 {generated_at, total, items}
  const items = data.items || [];

  let html = `
    <div class="dash-head">
      <h2><i class="ri-bar-chart-fill"></i> 可行性分析</h2>
      <span class="meta">${items.length} 份分析 · 共 ${data.total || items.length}</span>
      <button onclick="backToChat()">✕ 收起</button>
      <button onclick="loadDashboard('feasibility')">刷新</button>
      <button onclick="switchView('opportunities')" title="去 💎 掘金机会">← <i class="ri-diamond-fill"></i> 机会</button>
    </div>
    <div class="feas-intro">
      把 <i class="ri-diamond-fill"></i> 掘金机会卡展开成完整可行性 · 风险/资源/能力/成本/替代方案。
      在机会卡上点 <b>💰估算成本</b> · 或跟 OPUS 说「分析第 N 个机会的可行性」。
    </div>`;

  if (items.length === 0) {
    html += `
      <div class="feas-empty">
        <div style="font-size:32px;margin-bottom:12px"><i class="ri-bar-chart-fill"></i></div>
        <div>还没分析过任何机会</div>
        <div class="hint">
          先去 <i class="ri-diamond-fill"></i> 掘金机会 · 选一个想做的 · 点「💰估算成本」就会跑到这里。
        </div>
      </div>`;
    $dashView.innerHTML = html;
    return;
  }

  // 卷三十一 · 闭环状态徽章
  const _STATUS_BADGE = {
    not_started: { lbl: '<i class="ri-add-circle-fill"></i> 未启动', cls: 'fb-not_started' },
    in_progress: { lbl: '<i class="ri-play-fill"></i> 进行中', cls: 'fb-in_progress' },
    completed:   { lbl: '<i class="ri-check-fill"></i> 已完成', cls: 'fb-completed' },
    abandoned:   { lbl: '<i class="ri-close-fill"></i> 已放弃', cls: 'fb-abandoned' },
  };
  html += `<div class="feas-list">`;
  for (const it of items) {
    const v = _VERDICT_BADGES[it.verdict] || { label: '?', color: '#666' };
    const score = it.feasibility_score || 0;
    const scoreColor = score >= 70 ? '#22c55e' : score >= 40 ? '#eab308' : '#ef4444';
    const st = it.status || 'not_started';
    const stb = _STATUS_BADGE[st] || { lbl: st, cls: '' };
    html += `
      <div class="feas-card" onclick="loadFeasibilityDetail('${jsStr(it.opp_id)}')">
        <div class="feas-card-head">
          <span class="feas-verdict" style="background:${v.color}22;color:${v.color}">
            ${v.label}
          </span>
          <span class="feas-card-status feas-fb-${st}">${stb.lbl}</span>
          <span class="feas-score" style="color:${scoreColor}">
            ${score}<span class="feas-score-tot">/100</span>
          </span>
        </div>
        <div class="feas-card-title">${escHtml(it.opp_title || '?')}</div>
        <div class="feas-card-domain">领域: ${escHtml(it.opp_domain || '?')}</div>
        ${it.verdict_reason ? `<div class="feas-card-reason">${escHtml(it.verdict_reason)}</div>` : ''}
        <div class="feas-card-actions">
          <button class="feas-act" onclick="event.stopPropagation();loadFeasibilityDetail('${jsStr(it.opp_id)}')">
            <i class="ri-search-fill"></i> 查看完整分析
          </button>
        </div>
      </div>`;
  }
  html += `</div>`;
  $dashView.innerHTML = html;
}


// ── 母体 chat.js:12969-13266 · 执行反馈 renderExecution/_loadExecutionDetail/renderExecutionDetail ──


function renderExecutionDetail(d) {
  const snap = d.opp_snapshot || {};
  const updates = d.updates || [];
  const status = d.status || 'not_started';
  const statusLabels = {
    not_started: { label: '未启动', icon: '<i class="ri-add-circle-fill"></i>', color: '#7c869c' },
    in_progress: { label: '进行中', icon: '<i class="ri-play-fill"></i>', color: '#7aa2ff' },
    completed: { label: '已完成', icon: '<i class="ri-check-fill"></i>', color: '#5bd1a2' },
    abandoned: { label: '已放弃', icon: '<i class="ri-close-fill"></i>', color: '#d97a7a' },
  };
  const sm = statusLabels[status] || statusLabels.not_started;

  $dashView.innerHTML = `
    <div class="dash-head">
      <button class="back-btn" id="execBack">← 返回执行反馈列表</button>
      <h2><i class="ri-refresh-fill"></i> ${escHtml(d.opp_title || '?')}</h2>
      <span class="dash-meta" style="color:${sm.color}">${sm.icon} ${sm.label}</span>
    </div>

    ${snap.id ? `
      <section class="exec-snap">
        <h3><i class="ri-diamond-fill"></i> 源头掘金机会</h3>
        <div class="exec-snap-box" style="border-left:3px solid #6b8aef">
          <div><strong>${escHtml(snap.title)}</strong></div>
          <div class="muted">domain: ${escHtml(snap.domain || '-')} · fit: ${escHtml(snap.fit || '?')} · recommend: ${snap.recommend || '?'}/5</div>
          ${snap.summary ? `<div style="margin-top:4px">${escHtml(snap.summary.slice(0,200))}${snap.summary.length>200?'…':''}</div>` : ''}
          <div style="margin-top:6px">
            <button class="exec-jump" data-opp="${escHtml(snap.id)}">→ 跳到可行性分析</button>
          </div>
        </div>
      </section>
    ` : ''}

    <section class="exec-current">
      <h3>当前状态</h3>
      ${d.decision_reason ? `
        <div class="exec-field">
          <div class="exec-field-label">决策理由</div>
          <div class="exec-field-val">${escHtml(d.decision_reason)}</div>
        </div>
      ` : ''}
      ${(d.actual_revenue_cny != null || d.actual_cost_cny != null) ? `
        <div class="exec-field-row">
          <div class="exec-field">
            <div class="exec-field-label">实际收入</div>
            <div class="exec-field-val rev">¥${d.actual_revenue_cny || 0}</div>
          </div>
          <div class="exec-field">
            <div class="exec-field-label">实际成本</div>
            <div class="exec-field-val cost">¥${d.actual_cost_cny || 0}</div>
          </div>
        </div>
      ` : ''}
      ${d.efficiency_gain ? `
        <div class="exec-field">
          <div class="exec-field-label">增效</div>
          <div class="exec-field-val">${escHtml(d.efficiency_gain)}</div>
        </div>
      ` : ''}
      ${d.lessons_learned ? `
        <div class="exec-field">
          <div class="exec-field-label">经验教训</div>
          <div class="exec-field-val">${escHtml(d.lessons_learned)}</div>
        </div>
      ` : ''}
    </section>

    <section class="exec-timeline">
      <h3><i class="ri-calendar-fill"></i> 时间线 (${updates.length} 次更新)</h3>
      ${updates.length === 0 ? `
        <div class="muted">还没有更新记录</div>
      ` : `
        <div class="exec-tl">
          ${updates.slice().reverse().map(u => `
            <div class="exec-tl-item">
              <div class="exec-tl-dot" style="background:${(statusLabels[u.status] || sm).color}"></div>
              <div class="exec-tl-body">
                <div class="exec-tl-head">
                  <strong>${(statusLabels[u.status] || sm).icon} ${(statusLabels[u.status] || sm).label}</strong>
                  <span class="muted">${escHtml(_formatTimeAgo(u.at))}</span>
                </div>
                ${u.note ? `<div class="exec-tl-note">${escHtml(u.note)}</div>` : ''}
              </div>
            </div>
          `).join('')}
        </div>
      `}
    </section>

    <section class="exec-update-form">
      <h3>✍️ 添加进展 / 更新状态</h3>
      <p class="muted">这里记的每一笔·都会成为下次 LLM 做同类可行性分析的"过往经验"</p>
      <div class="exec-update-row">
        <select id="execStatusSelect" class="exec-input">
          <option value="">— 不改状态 —</option>
          <option value="not_started" ${status==='not_started'?'selected':''}><i class="ri-add-circle-fill"></i> 未启动</option>
          <option value="in_progress" ${status==='in_progress'?'selected':''}><i class="ri-play-fill"></i> 进行中</option>
          <option value="completed" ${status==='completed'?'selected':''}><i class="ri-check-fill"></i> 已完成</option>
          <option value="abandoned" ${status==='abandoned'?'selected':''}><i class="ri-close-fill"></i> 已放弃</option>
        </select>
      </div>
      <textarea id="execNoteInput" class="exec-input"
                placeholder="进展 / 反思 / 新发现的问题（不限格式）"
                rows="3"></textarea>
      <div class="exec-update-row">
        <input id="execRevInput" type="number" class="exec-input" placeholder="实际收入 ¥（可选）"
               value="${d.actual_revenue_cny != null ? d.actual_revenue_cny : ''}" />
        <input id="execCostInput" type="number" class="exec-input" placeholder="实际成本 ¥（可选）"
               value="${d.actual_cost_cny != null ? d.actual_cost_cny : ''}" />
      </div>
      <input id="execEffInput" type="text" class="exec-input"
             placeholder="增效描述（如「每周省 4 小时」·可选）"
             value="${escHtml(d.efficiency_gain || '')}" />
      <input id="execLessonInput" type="text" class="exec-input"
             placeholder="经验教训（一句话最值钱·可选）"
             value="${escHtml(d.lessons_learned || '')}" />
      <button id="execSaveBtn" class="exec-save-btn"><i class="ri-save-fill"></i> 保存进展</button>
    </section>
  `;

  document.getElementById('execBack').onclick = () => loadDashboard('execution');
  $dashView.querySelectorAll('.exec-jump').forEach(btn => {
    btn.onclick = (ev) => {
      ev.stopPropagation();
      const oppId = btn.getAttribute('data-opp');
      _loadFeasibilityDetail(oppId);
    };
  });
  document.getElementById('execSaveBtn').onclick = async () => {
    const btn = document.getElementById('execSaveBtn');
    btn.disabled = true;
    btn.textContent = '保存中...';
    const fields = {};
    const st = document.getElementById('execStatusSelect').value;
    if (st) fields.status = st;
    const note = (document.getElementById('execNoteInput').value || '').trim();
    if (note) fields.note = note;
    const rev = document.getElementById('execRevInput').value;
    if (rev !== '') fields.actual_revenue_cny = parseFloat(rev);
    const cost = document.getElementById('execCostInput').value;
    if (cost !== '') fields.actual_cost_cny = parseFloat(cost);
    const eff = document.getElementById('execEffInput').value;
    if (eff !== '') fields.efficiency_gain = eff;
    const ls = document.getElementById('execLessonInput').value;
    if (ls !== '') fields.lessons_learned = ls;
    if (note && !fields.decision_reason && !st) {
      // 没改状态 / 没填决策 · 把 note 当 decision_reason 一起塞·让 prompt 那边能用
      fields.decision_reason = note;
    }
    const ok = await _postOutcome(d.opp_id, fields);
    btn.disabled = false;
    btn.innerHTML = '<i class="ri-save-fill"></i> 保存进展';
    if (ok) {
      _loadExecutionDetail(d.opp_id);
    } else {
      await opusAlert({ title: '保存失败', message: '执行反馈没存上 · 看浏览器控制台', icon: '<i class="ri-error-warning-fill"></i>' });
    }
  };
}

// ═════════════════════════════════════════════════════════
// 卷三十三 · <i class="ri-star-fill"></i> 收藏夹 · 三类统一视图
// ═════════════════════════════════════════════════════════

// ── 母体 chat.js:13267-13405 · 收藏夹 renderFavorites/_toggleFavorite/_fetchFavoriteSet ──

// 全局 · 切换收藏 / 加 / 减

// 全局 · 把当前 opportunities / feasibility 的 ref_id 在 UI 上标记 starred
async function _fetchFavoriteSet(kind) {
  try {
    const r = await fetch(`/dashboard/favorites?domain_filter=${encodeURIComponent(kind)}`, {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) return new Set();
    const data = await r.json();
    return new Set((data.items || []).map(it => it.ref_id));
  } catch (e) {
    return new Set();
  }
}

// ═════════════════════════════════════════════════════════
// 卷三十三 · <i class="ri-calendar-fill"></i> 信息日历视图
// ═════════════════════════════════════════════════════════
let _currentCalendarYM = null;  // {year, month}


// ── 母体 chat.js:14016-14381 · 信息雷达 renderRadar 及辅助 ──

// 卷三十二 · 雷达条目打标

// 卷二十八 · 雷达 domain 过滤器切换

// 卷三十五补丁3 · 手动删类目 · 直接走 API · 不再喂 LLM
// 修两件事:
//   1. BUG · starter 4 删了重启复活 (后端用 domains_removed.json 记账解决)
//   2. token · 删按钮不应该烧 LLM token · 用户点 x 就是确定动作
// 自然语言删除依然可以走 OPUS · 这个函数只服务"按钮点击"场景


// 卷二十七 · 今日趋势 = OPUS 军师视图（不只是「今日」· 是前瞻+操作建议）
// 数据 schema: title / summary / intensity (1-5) / angles[] / refs[] / radar_index
const _ANGLE_LABELS = {
  content: { icon: '<i class="ri-film-fill"></i>', label: '内容制作', action: '写选题', cls: 'angle-content' },
  design:  { icon: '<i class="ri-palette-fill"></i>', label: '产品设计', action: '出 spec', cls: 'angle-design' },
  dev:     { icon: '<i class="ri-terminal-box-fill"></i>', label: '产品开发', action: '列 TODO', cls: 'angle-dev' },
  docs:    { icon: '<i class="ri-file-text-fill"></i>', label: '文档撰写', action: '写 FAQ', cls: 'angle-docs' },
  service: { icon: '<i class="ri-team-fill"></i>', label: '用户服务', action: '设服务', cls: 'angle-service' },
};


// 触发一键动作：直接给 chat 输入框塞一条指令然后发送
function triggerTrendAction(trendIndex, kind) {
  // kind = 'report' | 'content' | 'design' | 'dev' | 'docs'
  const triggers = {
    report:  `把第 ${trendIndex + 1} 个趋势展开成一份完整报告 (调 expand_trend_to_report tool · trend_index=${trendIndex})`,
    content: `基于第 ${trendIndex + 1} 个趋势 · 给我写一个对应的视频选题 / 口播稿 (调 draft_studio · domain=content)`,
    design:  `基于第 ${trendIndex + 1} 个趋势 · 出一份产品 spec (调 draft_studio · domain=design)`,
    dev:     `基于第 ${trendIndex + 1} 个趋势 · 列一份技术调研 / TODO (调 draft_studio · domain=dev)`,
    docs:    `基于第 ${trendIndex + 1} 个趋势 · 写一条 FAQ / wiki (调 draft_studio · domain=docs)`,
  };
  const msg = triggers[kind];
  if (!msg) return;
  $input.value = msg;
  $input.focus();
  if (typeof window.send === 'function') window.send();
  else document.getElementById('send')?.click();
}


// ── 母体 chat.js:14382-14464 · 今日趋势 renderTrends ──
function renderTrends(data) {
  if (data && data.error) {
    $dashView.innerHTML = `
      ${pipelineBreadcrumb('trends')}
      <div class="dash-head"><h2><i class="ri-line-chart-fill"></i> 今日趋势</h2></div>
      <div class="dash-empty">${escHtml(data.error)}</div>`;
    return;
  }
  const trends = (data && data.trends) || [];
  const generatedAt = data && data.generated_at;
  const generatedTxt = generatedAt ? formatRadarTime(generatedAt) : '未知';
  // 卷三十四 · 取整天日期（BRO 想看的是绝对日期·不是相对时间）
  const generatedDay = generatedAt ? (generatedAt.slice(0, 10)) : '?';
  const itemsScanned = data && data.items_scanned ? data.items_scanned : '?';
  const isArchive = data && data._source === 'archive';
  const archiveDay = data && data._day;

  let html = `
    ${pipelineBreadcrumb('trends')}
    <div class="dash-head">
      <h2><i class="ri-line-chart-fill"></i> 今日趋势 · OPUS 军师视图</h2>
      <span class="meta"><i class="ri-calendar-fill"></i> <b>${escHtml(isArchive ? archiveDay : generatedDay)}</b> · ${trends.length} 个方向 · 扫了 ${itemsScanned} 条 · ${generatedTxt}${isArchive ? ' <span class="badge-archive">归档</span>' : ''}</span>
      <button onclick="backToChat()">✕ 收起</button>
      <button onclick="loadDashboard('radar')">← 看原料</button>
      <button onclick="spawnQuickly('看一眼信息雷达最新数据 · 调 auto_pipeline 工具 · 参数 refresh_radar=false, regen_trends=true, mine_opps=false · 只重新生成今日趋势 · 跑完告诉我哪几个趋势最戳到 BRO · 为什么', '重新生成趋势')">让 OPUS 重新看一遍</button>
    </div>
    <div class="trends-intro">
      不是「今日新闻总结」· 是 OPUS 看完雷达 ${itemsScanned} 条后给出的
      <strong>前瞻性思考 + 工作室视角</strong>——每个趋势都标了强度 + 可切入的角度 +
      可一键转化的动作。${isArchive ? `<br><span class="archive-hint">⏳ 当前查看的是 <b>${escHtml(archiveDay)}</b> 的归档趋势·不是最新版</span>` : ''}
    </div>
    ${trends.length > 3 ? renderListFilter({targetSelector: '.trend-card', placeholder: '搜趋势标题 / 摘要 / 信源...'}) : ''}`;

  if (trends.length === 0) {
    html += `
      <div class="dash-stub">
        <h3>还没生成趋势</h3>
        <div>${escHtml((data && data.note) || '点"让 OPUS 重新看一遍"·OPUS 会读 radar.json·输出 3-5 个方向·约 30-60s')}</div>
      </div>`;
  } else {
    trends.forEach((t, idx) => {
      const angles = (t.angles || []).filter(a => _ANGLE_LABELS[a]);
      const angleChips = angles.map(a => {
        const m = _ANGLE_LABELS[a];
        return `<span class="trend-angle ${m.cls}" title="${m.label}">${m.icon} ${m.label}</span>`;
      }).join('');

      const refs = (t.refs || []).map(r =>
        `<a href="${escHtml(r.url || '#')}" target="_blank" rel="noopener" ` +
        `title="${escHtml(r.title || '')}">${escHtml(r.source || '?')}</a>`
      ).join(' · ');

      // 操作按钮：永远有"写报告" + "深挖"·angles 各自有触发
      const reportBtn = `<button class="trend-action ta-report" onclick="triggerTrendAction(${idx}, 'report')" title="OPUS 用 LLM 把这个趋势展开成 3000-4500 字 docx 报告"><i class="ri-article-fill"></i> 写报告</button>`;
      const deepBtn = `<button class="trend-action ta-deep" onclick="deepDiveTrend(${idx})" title="让 OPUS 用 web_search + web_fetch 深挖这个趋势"><i class="ri-search-fill"></i> 深挖</button>`;
      const angleBtns = angles.map(a => {
        const m = _ANGLE_LABELS[a];
        return `<button class="trend-action ${m.cls}" onclick="triggerTrendAction(${idx}, '${a}')" title="基于这个趋势 · 调 draft_studio domain=${a}">${m.icon} ${m.action}</button>`;
      }).join('');

      html += `
        <div class="trend-card" data-trend-idx="${idx}" data-trend-title="${escHtml(t.title || '')}">
          <div class="tc-row1">
            <span class="tc-idx">#${idx + 1}</span>
            <span class="tc-head">${escHtml(t.title || '')}</span>
            ${renderIntensityBar(t.intensity)}
            <span class="tc-day" title="${escHtml(generatedDay)} 这一份趋势"><i class="ri-calendar-fill"></i> ${escHtml(generatedDay)}</span>
          </div>
          <div class="tc-body">${escHtml(t.summary || '')}</div>
          ${angleChips ? `<div class="trend-angles">${angleChips}</div>` : ''}
          <div class="trend-actions">${reportBtn}${deepBtn}${angleBtns}</div>
          ${refs ? `<div class="tc-refs"><i class="ri-radar-fill"></i> 信源: ${refs}</div>` : ''}
        </div>`;
    });
  }
  $dashView.innerHTML = html;
  if (trends.length > 3) _applyListFilter($dashView.querySelector('.list-filter-input'));
}

// 报告库（卷二十四 · generate_report 工具产物 · data/reports/ 落盘）
// 私有文档知识库 · 第二大脑 · 文档清单 + 参考开关 + 删除(灌文档走对话 NLP)
// 复用 report-card / rc-* 样式 · 不另起 CSS
// 单篇知识库文档卡片 HTML · 文件夹分组和平铺共用

// ── 母体 chat.js:14465-14705 · 知识库 renderKnowledge 系列 + 统一预览弹窗 ──


// 报告库 → 一键存入知识库 (灌 md 源优先·归「报告」文件夹·已灌过不重复)

// 点知识库卡片标题 → 拉正文 → 弹窗预览 (markdown 渲染)

// 卷八十一续 · 统一预览弹框渲染器 · 知识库/playbook/文件产物 共用一套骨架
// (BRO 拍板: 别各处重写预览逻辑 · 弹框统一 · 以后改一处全生效)
// 2026-08-11 F1 (墨言审查): _showPreviewModal 的 keydown 防堆积 · 模块级单例
let _previewModalKeyBound = false;


// 2026-08-14 · kbModalHost 单例互斥 (墨言 094-2 审查 · wish-2b43ffe7):
// depot.js(_cogDimModal) / clients.js(pickClient + _showClientImportModal) 各自
// getElementById('kbModalHost') → 不存在则建 → innerHTML 覆盖 —— 共用同一 DOM 节点，
// 先后打开会静默互相覆盖 (先开的状态丢失)。
// 修法: 每个弹框打开前先调用 _closeAllKbModals() 关掉当前已开的 → 再开新的。
// 用户心智: "打开新弹框 = 旧的先关掉" · 不再静默覆盖。


async function _kbAction(url, body) {
  if (!token && !(await _ensureLoopbackToken())) return;
  try {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) { alert('操作失败 [' + r.status + ']'); return; }
    loadDashboard('knowledge', { silent: true });
  } catch (e) { alert('网络出错: ' + e.message); }
}


// ── 母体 chat.js:14706-14847 · 报告库 renderReports/loadReportPreview/renderReportPreview ──

// 卷三十三补丁 · 加载并渲染单份报告的预览

function renderReportPreview(d) {
  const name = d.name || '?';
  const meta = d.meta || {};
  const md = d.markdown || '';
  const hasMd = !!d.has_md_source;
  const note = d.note || '';
  const dlUrl = `/reports/${encodeURIComponent(name)}?token=${encodeURIComponent(token || '')}`;

  // 标题 / 副标题 / 受众 / 备注 / footer 渲染封面
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

  $dashView.innerHTML = `
    <div class="dash-head">
      <h2>📖 ${escHtml(name)}</h2>
      <button onclick="loadDashboard('reports')">← 返回报告库</button>
      <a class="rp-dl-btn" href="${escHtml(dlUrl)}" download="${escHtml(name)}">下载 docx ↓</a>
    </div>
    <div class="rp-meta-strip">
      ${hasMd
        ? '<span class="rp-src rp-src-md"><i class="ri-file-text-fill"></i> markdown 源</span>'
        : '<span class="rp-src rp-src-extract"><i class="ri-error-warning-fill"></i> 旧报告 · 从 docx 反推的简陋版</span>'}
      ${note ? `<span class="rp-note">${escHtml(note)}</span>` : ''}
    </div>
    <article class="rp-body">
      ${coverBlock}
      <div class="rp-md">${mdRender(md)}</div>
    </article>
  `;
}

// 卷二十八 · <i class="ri-diamond-fill"></i> 掘金机会维度

// ── 母体 chat.js:14848-15138 · 掘金机会 renderOpportunities/renderOppFullCard/renderOppStats/deepDive/wishFrom ──


// 卷三十四 · 掘金机会卡片的"数字面板"——6 个评估字段可视化

// 卷三十四 · "<i class="ri-search-fill"></i> 深挖" 按钮 · 让 OPUS 调 web_search + web_fetch 深挖某个点
// 复用对话框 inject · 不引入新 endpoint · 让 LLM 自己规划 tool 调用

// 掘金机会卡片"深挖"——从 idx 取 title 再调 deepDive

// 趋势卡片"深挖"——读 data-trend-title 拿原始标题

// 雷达条目"深挖"——直接传 title

// 卷三十五 · self-evolve domain 的 radar 条目 → 让 OPUS 写心愿

// 卷三十五 · self-evolve domain 的 opportunity → 让 OPUS 把它转成心愿
function wishFromOpp(oneBasedIdx) {
  const card = document.querySelector(`.opp-card[data-opp-idx="${oneBasedIdx}"]`);
  const title = card
    ? (card.getAttribute('data-opp-title') || `第 ${oneBasedIdx} 个机会`)
    : `第 ${oneBasedIdx} 个机会`;
  spawnTask(
    `BRO 让你看一眼 self-evolve 域的掘金机会「${title}」——这其实是关于 OPUS 自己的成长。\n\n` +
    `**这是邀请·你要自己判断**。请你：\n` +
    `1. 用 read_dashboard("opportunities") 把机会卡完整内容拉出来\n` +
    `2. 想清楚：\n` +
    `   - OPUS 现状有没有这能力·缺哪一块\n` +
    `   - 装上之后真正受益的是 BRO 哪个具体痛点 (而不是泛泛的"AI 升级")\n` +
    `   - 跟 Daemonkey 现有架构合拍吗\n` +
    `3. 明确表态:\n` +
    `   - 值得装 → wish_add (title 改写成"OPUS 装 X" / why = 对 BRO 的具体价值 / source_kind=opportunity / source_ref=opp_id / design_sketch=2-3 步改造方案 / complexity / hours / cost / priority)\n` +
    `   - 不值得 → 说清为啥·不强 add\n` +
    `**你才是搭档**·拿出判断力。`,
    `勘察心愿: ${title}`
  );
}

// ── 母体 chat.js:4997-5008 · _DOC_ICON_MAP + _docIcon · mdRender 附件卡片图标 ──
const _DOC_ICON_MAP = {
  docx:'ri-file-word-2-fill', doc:'ri-file-word-2-fill',
  xlsx:'ri-file-excel-2-fill', xls:'ri-file-excel-2-fill',
  pptx:'ri-file-ppt-2-fill', ppt:'ri-file-ppt-2-fill',
  pdf:'ri-file-pdf-2-fill', md:'ri-markdown-fill',
  png:'ri-image-fill', jpg:'ri-image-fill', jpeg:'ri-image-fill', gif:'ri-image-fill', webp:'ri-image-fill',
  mp3:'ri-file-music-fill', wav:'ri-file-music-fill',
  mp4:'ri-file-video-fill', webm:'ri-file-video-fill',
};
function _docIcon(ext) { return `<i class="${_DOC_ICON_MAP[ext] || 'ri-file-fill'}"></i>`; }

// 分类组: 办公文档 / 文本·报告 / 图片 / 音频 / 视频

// ── 母体 chat.js:5061-5064 · _safeDecode ──
function _safeDecode(s) {
  try { return decodeURIComponent(s); } catch (e) { return s; }
}


// ── 母体 chat.js:10965-10979 · _biStarN + _biStars 星级 ──
function _biStars(v) {
  const n = _biStarN(v);
  // 前 n 个实心·后 (5-n) 个空心
  return '★★★★★☆☆☆☆☆'.slice(5 - n, 10 - n);
}


// ── 母体 chat.js:12313-12318 · _VERDICT_BADGES 判定徽章 ──
const _VERDICT_BADGES = {
  go:          { label: '<i class="ri-circle-fill" style="color:#22c55e"></i> 推荐做',       color: '#22c55e' },
  conditional: { label: '<i class="ri-circle-fill" style="color:#eab308"></i> 有条件可做', color: '#eab308' },
  wait:        { label: '⏸ 先等等',       color: '#94a3b8' },
  skip:        { label: '<i class="ri-circle-fill" style="color:#ef4444"></i> 不建议',       color: '#ef4444' },
};

// ── 母体 chat.js:12396-12968 · 可行性详情 runFeasibilityFromOpp/loadFeasibilityDetail/renderFeasibilityDetail/submitOutcomeStatus/_postOutcome/_loadFeasibilityDetail ──


// 卷三十三 · 跳可行性详情 · 给 renderExecutionDetail / renderFavorites 用

// ───────── 卷三十一 · outcome 提交 ─────────


async function _postOutcome(opp_id, fields) {
  try {
    const r = await fetch('/outcome', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ opp_id, ...fields }),
    });
    if (!r.ok) {
      console.warn('outcome post failed', r.status, await r.text());
      return false;
    }
    return true;
  } catch (e) {
    console.warn('outcome post error', e);
    return false;
  }
}

// ═════════════════════════════════════════════════════════
// 卷三十三 · <i class="ri-refresh-fill"></i> 执行反馈 · 闭环反馈独立维度
//   跟 outcomes 共享数据 · 视图按状态分组
// ═════════════════════════════════════════════════════════

// ── 母体 chat.js:13755-13771 · _formatTimeAgo ──
function _formatTimeAgo(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return '刚刚';
    if (diff < 3600) return Math.floor(diff/60) + ' 分钟前';
    if (diff < 86400) return Math.floor(diff/3600) + ' 小时前';
    if (diff < 86400*30) return Math.floor(diff/86400) + ' 天前';
    return d.toLocaleDateString();
  } catch (e) { return iso; }
}

// ─────────────────────────────────────────────────────────
// 卷二十九 · <i class="ri-puzzle-fill"></i> 插件库（能力扩展层）
// ─────────────────────────────────────────────────────────

// ── 母体 chat.js:8693-8704 · RADAR_DOMAINS_META 领域元信息 + radarDomainFilter 全局 (不含 8706 currentView · 适配层已定义) ──
// 卷二十八 · 雷达 / 机会的领域元信息（与 workers/info_radar.DOMAIN_META 保持对齐）
const RADAR_DOMAINS_META = {
  'ai':              { icon: '<i class="ri-robot-fill"></i>', label: 'AI / 大模型',  color: '#9f7aea' },
  'super-individual':{ icon: '<i class="ri-rocket-fill"></i>', label: '超个体 / 创业', color: '#4fd1c5' },
  'game-money':      { icon: '🎮', label: '游戏掘金',     color: '#ed8936' },
  'wildcard':        { icon: '✨', label: '杂项观察',     color: '#fc8181' },
  // 卷三十四 · self-evolve · OPUS 看 GitHub 同类工程的镜子
  'self-evolve':     { icon: '<i class="ri-tools-fill"></i>', label: '自我演化',     color: '#63b3ed' },
};

// 雷达 domain filter 当前选中的领域 · 'all' 表示不过滤
let radarDomainFilter = localStorage.getItem('radar_domain_filter') || 'all';

// ── 母体 chat.js:8646-8691 · DOMAIN_META 维度注册表 (renderDashboardStub 取 icon/label) ──
const DOMAIN_META = {
  // 工作室看板 · 起始屏 BI · 独立分组最上 (BRO 2026-08-06 拍板 · 它不是市场信息)
  bi:            { icon: '<i class="ri-dashboard-fill"></i>', label: '工作室看板', section: 'home', stub: false },
  // 市场信息 · 外部信号 · Daemonkey 看世界的眼睛 · 不含 OPUS 自己的观察
  radar:         { icon: '<i class="ri-radar-fill"></i>', label: '信息雷达', section: 'market', stub: false },
  trends:        { icon: '<i class="ri-line-chart-fill"></i>', label: '今日趋势', section: 'market', stub: false },
  reports:       { icon: '<i class="ri-article-fill"></i>', label: '报告库',   section: 'market', stub: false },
  calendar:      { icon: '<i class="ri-calendar-fill"></i>', label: '信息日历', section: 'market', stub: false },
  // 能力对照 · 内部决策 · 市场 × BRO 能力的交叉
  opportunities: { icon: '<i class="ri-diamond-fill"></i>', label: '掘金机会', section: 'ability', stub: false },
  feasibility:   { icon: '<i class="ri-bar-chart-fill"></i>', label: '可行性分析', section: 'ability', stub: false },
  // 私有文档知识库 · 第二大脑 · 灌进来的资料喂掘金脑/可行性 · 与掘金同组让"资料→决策"这条线可见
  knowledge:     { icon: '<i class="ri-book-2-fill"></i>', label: '知识库', section: 'ability', stub: false },
  // 出品工坊 · 产品生产
  // 卷四十四 K stage 2a · 4 老维度 (content/design/dev/docs) 收进工坊主页"<i class="ri-archive-fill"></i> 应用"tab
  // 它们的 dashboard 端点 GET /dashboard/<id> 仍然有效 (workshop 内部 fetch 直拉)
  // 但 NAV_GROUPS 没 'apps' 组 · 所以从左导航 hidden · 跟 BRO 当前需求一致
  workshop:  { icon: '<i class="ri-magic-fill"></i>', label: '出品工坊', section: 'studio', stub: false },
  content:   { icon: '<i class="ri-film-fill"></i>', label: '内容制作', section: 'apps', stub: false },
  design:    { icon: '<i class="ri-palette-fill"></i>', label: '产品设计', section: 'apps', stub: false },
  dev:       { icon: '<i class="ri-terminal-box-fill"></i>', label: '产品开发', section: 'apps', stub: false },
  docs:      { icon: '<i class="ri-file-text-fill"></i>', label: '文档撰写', section: 'apps', stub: false },
  // 用户运营 · 客户档案(合伙人记得每个客户 · notes 进记忆 · 资料可挂到客户名下)
  clients:   { icon: '<i class="ri-contacts-book-2-fill"></i>', label: '客户档案', section: 'ops', stub: false },
  service:   { icon: '<i class="ri-team-fill"></i>', label: '用户运营', section: 'ops', stub: true,
               note: '等先有产品再做用户运营' },
  // 执行落地 · 卷三十三 · 闭环反馈独立维度 · 卷三十三补丁 · OPUS 日记搬这里
  //   因为"OPUS 对 BRO 的观察"跟"BRO 真正在跑的项目"是同一码事——
  //   都是「自我视角」·跟外部信号（radar/trends/reports）分开
  execution:     { icon: '<i class="ri-refresh-fill"></i>', label: '执行反馈', section: 'execution', stub: false },
  scheduled_tasks: { icon: '<i class="ri-timer-2-fill"></i>', label: '定时任务', section: 'execution', stub: false },
  favorites:     { icon: '<i class="ri-star-fill"></i>', label: '收藏夹',   section: 'execution', stub: false },
  // ── 成长档案 (depot hub) · 把 日记/心愿/沉淀位/技能库 并成一个入口 · 内部标签切换 ──
  // 这 4 个本就是「OPUS 自己积累/沉淀的东西」· 并成一栏减少侧边栏拥挤 (BRO 2026-07-11)
  // 2026-08-06 · BRO 拍板: 成长档案挪「总览」分组 (执行落地=BRO 正在跑的事·成长档案=OPUS 自我成长·两者不同层)
  // 子维度 navHidden · 不单独占导航位 · 但 DOMAIN_META 条目保留 · loadDepot 仍复用它们的 render fn
  depot:         { icon: '<i class="ri-seedling-fill"></i>', label: '成长档案', section: 'home', stub: false },
  cognition:     { icon: '<i class="ri-brain-fill"></i>', label: 'OPUS 日记', section: 'home', stub: false, navHidden: true },
  // 卷三十五 · OPUS 自我演化心愿单 · "我想装这个能力"
  wishlist:      { icon: '<i class="ri-lightbulb-fill"></i>', label: 'OPUS 心愿', section: 'home', stub: false, navHidden: true },
  sinks:         { icon: '<i class="ri-archive-drawer-fill"></i>', label: '沉淀位',   section: 'home', stub: false, navHidden: true },
  // 技能库 · playbook 沉淀查看器 · 灌/召回仍走 NLP·这里只读+可删
  playbooks:     { icon: '<i class="ri-tools-fill"></i>', label: '技能库', section: 'home', stub: false, navHidden: true },
  // 插件库 · 能力扩展 · OPUS 自己用产品开发能写新插件回填这里
  plugins:   { icon: '<i class="ri-puzzle-fill"></i>', label: '插件库', section: 'plugins', stub: false },
};

// ═══ BI 看板 (追加块 · tools/_extract_cockpit.py 生成 · 勿手改) ═══

// ── 适配层 · 母体 BI 打的是中栏 $detailPane · 陪伴模式打弹窗 $dashView ──
const $detailPane = $dashView;
function renderDetailWelcome() { loadBIDashboard(); }   // 母体刷新按钮的落点
function injectAndSend(text) {                          // BI 卡片一键回填 → 走房间对话
  if (typeof closeModal === 'function') closeModal();
  if (typeof sendCompanionText === 'function') sendCompanionText(text);
}

// ── 母体 chat.js:10288-10964 · BI 看板 loadBIDashboard / renderBIDashboard / _bi* 辅助 ──


// ═══════════════════════════════════════════
//  V3 同步填充 (cockpit 已有的数据)
// ═══════════════════════════════════════════

// ═══════════════════════════════════════════
//  V3 异步补充 (日历 + 雷达 + 趋势 + 图表)
// ═══════════════════════════════════════════

// ═══════════════════════════════════════════
//  卷五十八续 VIII · A/B/C 卡加载器 (D 节律时间线在 biHeatRender 里填)
// ═══════════════════════════════════════════
// A·OPUS 眼里的你 · 市场能力镜像快照 (填"照完即孤岛"的洞)

// B·闭环温度计 · 哪些 OPUS 输出还在等 BRO 反应

// C·OPUS 自况 · token / 会话 / 在线 (拉现有端点·不加后端)
// wish-bec4f3b9 · 模型计费卡 (原型 dashboard-billing-proto 完整形态 · 价格表 × 用量 → 钱)
// 默认今日 · BRO 刷新看到的是当天数据 · 要更多自己切 7天/30天
let _biBillingRange = 'today';
// 模型切换「展开更多」(2026-08-20 · 默认 5 条 · 跟缓存经济性卡对齐)

// 图像/视频/音频类不走 prompt cache · 缓存经济性只算 LLM 模型
const _biLlmFams = ['deepseek','glm','kimi','moonshot','claude','qwen','gpt-4','gpt-3.5','gpt-5','o1','o3','gemini','minimax'];
// 范围切换
document.addEventListener('click', (e) => {
  const btn = e.target.closest('#biBillingRangeBar .btn-ghost');
  if (!btn) return;
  document.querySelectorAll('#biBillingRangeBar .btn-ghost').forEach(b => b.classList.toggle('active', b === btn));
  _biBillingRange = btn.dataset.range;
  loadBIBilling();
});


// 0.9.6 · 建议操作条 (顶部 · 条件触发 · 忽略按天记 localStorage)

// 0.9.6 · 记忆体系卡 (lite 端点 · 秒出数字 · 详细全景点「星图」进 memory_map tab)

// 0.9.6 · 工坊卡 (apps/flows 计数 + shipped 数 · 入口卡)

// ══════════════════════════════════════════════════════════
//  价值热力图 (卷五十六 · 2026-06-03)
//  按"信息价值密度"着色·支持按月翻 + 领域筛选 + 点击下钻看高分原文
//  数据走 /dashboard/calendar_valued + /dashboard/day_signals (workers/info_value.py)
// ══════════════════════════════════════════════════════════
const _biHeat = { ym: null, domain: 'all' };

async function biHeatLoad() {
  if (!_biHeat.ym) { const n = new Date(); _biHeat.ym = { y: n.getFullYear(), m: n.getMonth() + 1 }; }
  const { y, m } = _biHeat.ym;
  const mm = y + '-' + String(m).padStart(2, '0');
  const q = new URLSearchParams({ domain_filter: mm, vdomain: _biHeat.domain });
  try {
    const r = await fetch('/dashboard/calendar_valued?' + q.toString(), {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) return;
    biHeatRender(await r.json());
  } catch (e) { console.warn('value heat load failed', e); }
  biBriefLoad();  // 研判卡片跟着同月同领域 (读缓存·不烧 token)
}

// 0-100 价值分 → 1-5 星等级 (BRO 2026-06-03 · 几百几千没法读·星级一眼懂热度等级)
// 阈值按 info_value 真实分布标定: BASE10 + 源6~22 + 新鲜0~20 + 反馈±·没反馈的新鲜好文 ~50。
// 若按 85/65 切·几乎全挤在 2-3★、5★ 永不出现 → 星级失效。 这里压低让内容铺满 1-5★:
//   5★(≥70)=⭐/👍 加持的真精品  4★(≥48)=顶级源新鲜文  3★(≥34)=新鲜常规
//   2★(≥22)=偏旧/弱源  1★(>0)=陈旧低值

// ── 母体 chat.js:10980-11710 · BI 看板续 · 趋势研判 / 信号流 / 图表 / renderBIDigest / renderOppCard ──

// ── 热力格子自定义 tooltip (多行 · 取代乱糟糟的浏览器原生 title) ──
let _biTipEl = null;

// 起草本期复盘 = 派发到新会话 (spawnTask · 不污染当前对话) · 节律条 + 抽屉按钮共用


// ══════════════════════════════════════════════════════════
//  趋势研判 (卷五十六 P2) · 跟热力图同月同领域 · LLM 给可行性 + 执行方案
//  数据走 /dashboard/trend_brief (workers/trend_brief.py · refresh=true 才烧 token)
// ══════════════════════════════════════════════════════════


// ── 信号流 ──
// 信号流状态 · 存原始数据 + 领域筛选 + 今日开关 (BRO 2026-06-03 · 纯前端过滤·不重新 fetch)
const _biSig = { trends: [], radar: [], domain: 'all', todayOnly: false };


// 这条信号是不是今天的 (published_at 优先·退 fetched_at·跟后端 item_date 口径一致)

// 当前时间维度下的雷达池 (今日开关在这里收口·领域筛选各处再叠加)

// 信号流领域 tab · 跟热力图同款 .bi-heat-dom · 按当前池里实际出现的领域动态生成


// 点信号流条目 → 新标签打开原文 (radar 条目带 url·trend 无原文不可点) ·BRO 2026-06-03

// ── 信号流高度跟随热力卡 (BRO 2026-06-03 · 正方形格子 + 完美对齐的关键) ──
//   热力图格子保持正方形·高度随卡片宽度等比变 (分辨率/对话栏宽度都会变)。
//   纯 CSS 没法让"另一张卡跟随这张卡的高度"·所以用 ResizeObserver 盯热力卡·
//   把信号流卡的 height 实时设成跟它一样·信号流内部滚动 → 两卡严格等高·底部对齐·谁都不留空。
let _biSigRO = null;

// ── chart.js (defer 本地加载) 就绪等待器 ──
// 卷五十六 · 2026-06-03 修: chart.umd.min.js 改 defer 后 · BI 首次渲染可能早于 Chart 就绪。
//   旧逻辑"没就绪就静默 return" → 之后无人重渲 → 雷达/环形图永久空白 (BRO 实测撞到)。
//   改成: 没就绪就挂起 · 轮询等 Chart 到位 (最多 ~6s) · 一到位补渲一次。空白根治。

// ── 雷达密度柱状图 ──
let biChartRadarInst = null;

// ── 维度产出环形图 ──
let biChartDonutInst = null;

// ── 最近动态 ──

// 卷四十六续 10 · BI 看板"今日动态" digest 卡 (BRO 候选 E)


// 卷三十四 · OPUS 自主巡航 banner · 一键跑 radar→trends→opps

function renderOppCard(o) {
  const fitIcon = { yes: '<i class="ri-checkbox-circle-fill"></i>', maybe: '<i class="ri-error-warning-fill"></i>', no: '<i class="ri-close-circle-fill"></i>' }[o.fit] || '?';
  const effortLabel = { light: '轻量', moderate: '中等', heavy: '重投入' }[o.cost_effort] || o.cost_effort;
  const upsideLabel = { low: '小', medium: '中', high: '高' }[o.upside] || o.upside;
  const stars = '<i class="ri-star-fill"></i>'.repeat(Math.max(1, Math.min(5, o.recommend || 3)));
  const dMeta = RADAR_DOMAINS_META[o.domain] || { icon: '·', label: o.domain, color: '#888' };
  return `
    <div class="bi-opp-card" style="border-left-color: ${dMeta.color}">
      <div class="bi-opp-head">
        <span class="bi-opp-domain">${dMeta.icon}</span>
        <span class="bi-opp-title">${escHtml(o.title || '?')}</span>
        <span class="bi-opp-rec">${stars}</span>
      </div>
      <div class="bi-opp-meta">
        <span title="BRO 适配度">${fitIcon} ${o.fit || '?'}</span>
        <span title="投入预估">⏱️ ${effortLabel}</span>
        <span title="收益级别">📈 ${upsideLabel}</span>
      </div>
      <div class="bi-opp-summary">${escHtml(o.summary || '')}</div>
    </div>`;
}


// ── 母体 chat.js:11744-11750 · filterRadarByDomain ──

// 点领域热力图块 · 跳到雷达并自动筛选该 domain
function filterRadarByDomain(domain) {
  radarDomainFilter = domain;
  localStorage.setItem('radar_domain_filter', domain);
  switchView('radar');
}

// ═══ BI 看板追加块结束 ═══

// ── 咖啡边桌 · 她给你泡的茶 ────────────────────────────────
const _CARE_KIND = {
  people: { icon: 'ri-emotion-unhappy-line', tag: '人事' },
  body: { icon: 'ri-capsule-line', tag: '身体' },
  mood: { icon: 'ri-heart-pulse-line', tag: '状态' },
  life: { icon: 'ri-calendar-event-line', tag: '小事' },
  focus: { icon: 'ri-focus-3-line', tag: '正在发生' },
  noticed: { icon: 'ri-eye-line', tag: '作息' },
};

function _careCard(it, extra, showHint) {
  const k = _CARE_KIND[it.kind] || _CARE_KIND.life;
  const days = it.days != null ? `隔了 ${it.days} 天` : (extra || '');
  const ripe = it.ripe ? ' · 可以问问' : '';
  const id = escHtml(it.id || '');
  const line = escHtml(it.line || '');
  const sig = escHtml(it.signal || '');
  const hint = showHint
    ? `<div class="hint">点了「发进对话」，这句话出现在右边，由她亲口说。卡片自己不出声。</div>`
    : '';
  return `<div class="care-card" data-id="${id}">
    <div class="care-row">
      <i class="${k.icon} lead"></i>
      <div>
        <div class="ttl"><span class="care-tag">${k.tag}</span>${escHtml(it.title || '')}</div>
        <div class="when">${escHtml(days)}${ripe}</div>
        <div class="acts">
          <button class="pri" data-speak="${line}" data-signal="${sig}"><i class="ri-chat-1-line"></i> 发进对话</button>
          <button data-dismiss="${id}"><i class="ri-close-line"></i> 今天别提</button>
        </div>
        ${hint}
      </div>
    </div>
  </div>`;
}

function renderCare(data) {
  const hero = escHtml((data && data.hero) || '');
  const follows = (data && data.followups) || [];
  const focus = data && data.focus;
  const radar = data && data.radar;
  const last = (data && data.last) || {};
  const empty = !!(data && data.empty);

  let body = `<div class="care-desk">`;
  if (empty) {
    body += `<div class="care-empty"><i class="ri-cup-line"></i>
      这几天没什么非说不可的——我就在这儿。</div>`;
  } else {
    body += `<div class="care-hero"><div class="who">我想说的</div><p>${hero}</p></div>`;
  }

  if (follows.length) {
    body += `<div class="care-sec"><h3>我想问问</h3>`;
    follows.forEach((it, i) => { body += _careCard(it, '', i === 0); });
    body += `</div>`;
  }
  if (focus) {
    body += `<div class="care-sec"><h3>我还惦记</h3>${_careCard(focus)}</div>`;
  }
  if (radar) {
    body += `<div class="care-sec"><h3>我注意到</h3>${_careCard({
      ...radar, kind: 'noticed', title: radar.title, line: radar.line, id: radar.id,
    }, radar.nights ? `最近 ${radar.nights} 个夜里很晚` : '')}</div>`;
  }
  if (last.title) {
    const gap = last.gap ? escHtml(last.gap) : '';
    body += `<div class="care-sec"><h3>我们说到哪了</h3>
      <div class="care-tiny"><i class="ri-chat-quote-line"></i>
        <div><b>${escHtml(last.title)}</b><br><span>${gap ? ('距上次 ' + gap) : '还在这儿'}</span></div>
      </div></div>`;
  }
  body += empty
    ? `<div class="care-foot">空也是体贴。不编一条建议来填满它。</div></div>`
    : `<div class="care-foot">照镜、月度复盘在笔记本电脑的看板里。这张桌子不放待办。</div></div>`;
  $dashView.innerHTML = body;
  $dashView.querySelectorAll('[data-speak]').forEach(btn => {
    btn.addEventListener('click', () => {
      if (typeof speakTea === 'function') speakTea(btn.dataset.speak, btn.dataset.signal || '');
    });
  });
  $dashView.querySelectorAll('[data-dismiss]').forEach(btn => {
    btn.addEventListener('click', () => dismissCare(btn.dataset.dismiss));
  });
}

async function loadCareDesk() {
  currentView = 'care';
  if (!token) await _ensureLoopbackToken();
  $dashView.innerHTML = dashLoadingHTML();
  try {
    const r = await fetch('/dashboard/care', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) { $dashView.innerHTML = `<div class="dash-empty">倒茶失败 [${r.status}]</div>`; return; }
    renderCare(await r.json());
  } catch (e) {
    $dashView.innerHTML = `<div class="dash-empty">网络出错: ${e.message}</div>`;
  }
}

async function dismissCare(id) {
  if (!id || !token) return;
  try {
    await fetch('/dashboard/care/dismiss', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify({ id }),
    });
  } catch {}
  loadCareDesk();
}
