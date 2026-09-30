/* chat-md.js · 对话 Markdown 渲染
 * 从 chat.js 抽出。depot / 工作台 / opusMdRender 共用。不进 LLM 系统提示词。
 */
// ──────────────────────────────────────────────────────────────
// 卷三十 · 简易 markdown 渲染器（chat 右栏用 · OPUS 输出 ### / **/ - / 1. / ``` 等都正确渲染）
// 不引外部 lib · 100 行自给自足 · 永远工作（trycloudflare 偶尔抽风也无所谓）
//
// 支持：
//   - # / ## / ### / #### / ##### / ###### headers
//   - **bold** *italic*  __bold__ _italic_
//   - `inline code`  + ```block code```
//   - --- 横线
//   - - / * / + 无序列表  · 1. 2. 3. 有序列表
//   - [text](url) 链接
//   - > 引用
//   - 段落 + 换行
//
// 安全：所有用户/LLM 内容先 escapeHtml · 再做 markdown 转换 · 防 XSS
// ──────────────────────────────────────────────────────────────
/* ═══ 2026-09-20 · 正文里的 wish-xxxxxxxx 鼠标移上去看标题 ═══
   BRO 拍板：「我能接受你再对话里面显示 wish-xxxxx，鼠标移过去显示标题也行啊」。
   原则：**宁可保留 hash，也不让信息丢** —— 表没加载好就照常显示原 id，只少了 hover 提示；
   任何时候不把正文换成无意义的占位。只有多行代码块 <pre> 里原样不动。 */
const _WISH_TITLES = {};
// 接口每页硬上限 50 条（实测：传 500 也只回 50）· 心愿单已有近 300 条 → 一页页拉全
const _WISH_API = '/dashboard/wishlist';
const _WISH_PAGE_SIZE = 50;
const _WISH_MAX_PAGES = 40;    // 防爆上限（≈2000 条）；超了只意味着老 id 的 hover 缺标题
const _WISH_RETRY_MS = 30000;  // 拉失败后 30s 冷却再试（别把瞬时失败变成永久没表）
const _WL_ID_STYLE = 'font-size:11px;color:var(--dim2);border-bottom:1px dotted var(--dim2);cursor:help';
try { window._WL_ID_STYLE = _WL_ID_STYLE; } catch (eW) {}
let _wishTitlesRetryAt = 0;
let _wishTitlesLoaded = false;

function _uiTokenForWish() {
  // 只用 daemon 自己的 token（localStorage 里那个可能是脏值 → 带了反而被拒）
  try { if (typeof token === 'string' && token && token !== '__loopback__') return token; } catch (e) {}
  return '';
}

function _fillWishRefs() {
  document.querySelectorAll('.wl-ref[data-wish]').forEach((el) => {
    const t = _WISH_TITLES[el.dataset.wish];
    if (t) { el.title = t; el.classList.add('wl-ok'); }   // 只补 hover 标题，不动文字
  });
}

function _ensureWishTitles() {
  if (_wishTitlesLoaded) return;                  // 已拉全 → 不再重复请求
  const _now = Date.now();
  if (_now < _wishTitlesRetryAt) return;          // 冷却中（失败过就 30s 后再试）
  _wishTitlesRetryAt = _now + _WISH_RETRY_MS;
  const _tk = _uiTokenForWish();
  const _pull = (page, useAuth) => {
    const url = _WISH_API + '?page=' + page + '&page_size=' + _WISH_PAGE_SIZE;
    const h = {};
    if (useAuth && _tk) h['Authorization'] = 'Bearer ' + _tk;
    return fetch(url, { headers: h }).then((r) => {
      // 默认不带 auth（loopback 不校验）；401/403 才带真 token 重试
      if ((r.status === 401 || r.status === 403) && !useAuth && _tk) return _pull(page, true);
      return r.ok ? r.json() : null;
    });
  };
  const _retryLater = () => {
    if (_wishTitlesLoaded) return;
    try { setTimeout(_ensureWishTitles, _WISH_RETRY_MS); } catch (e) {}   // 自驱动重试（不回头依赖渲染路径）
  };
  const _loop = (page) => _pull(page, false).then((d) => {
    if (!d) { _retryLater(); return; }            // 拿不到 → 30s 后自己再来
    ((d.wishes || d.items) || []).forEach((w) => { if (w && w.id) _WISH_TITLES[w.id] = w.title || ''; });
    _fillWishRefs();                              // 每拉到一页就先回填一次
    if (d.has_more && page < _WISH_MAX_PAGES) return _loop(page + 1);
    _wishTitlesLoaded = true;
  });
  try { _loop(1).catch(_retryLater); } catch (e) { _retryLater(); }
}

/* 渲染路径保持纯的：表在页面初始化时拉一次，渲染时只读表（不在 mdRender 里发请求）。 */
try {
  const _bootWishTitles = () => { try { setTimeout(_ensureWishTitles, 0); } catch (e) {} };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _bootWishTitles, { once: true });
  } else {
    _bootWishTitles();
  }
} catch (eBoot) {}

/** 只在「文本节点」上跑替换 —— 标签本身和属性值一律不碰（渲染出口专用）。
    <pre> 整块挖掉保护（那是看日志/源码的地方）。 */
function _eachTextNode(html, fn) {
  const s = String(html == null ? '' : html);
  const guards = [];
  let out = s.replace(/<pre[\s\S]*?<\/pre>/g, (m) => {
    guards.push(m);
    return '\u0000PRE' + (guards.length - 1) + '\u0000';
  });
  out = out.split(/(<[^>]*>)/g)
    .map((seg, i) => (i % 2 ? seg : fn(seg)))
    .join('');
  return out.replace(/\u0000PRE(\d+)\u0000/g, (m, n) => guards[+n] || '');
}
try { window._eachTextNode = _eachTextNode; } catch (eTN) {}

function _escapeAttr(v) {
  return String(v == null ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function _wishSpan(id) {
  const t = _WISH_TITLES[id];
  const sid = _escapeAttr(id);
  return '<span class="wl-ref' + (t ? ' wl-ok' : '') + '" data-wish="' + sid + '"'
       + ' title="' + _escapeAttr(t || '心愿单里的这条') + '" style="' + _WL_ID_STYLE + '">'
       + sid + '</span>';   // 文字保留原 id —— 信息不丢
}

/** 渲染出口：给正文里的 wish-xxxxxxxx 挂上 hover 标题。失败一律返回原样。
    两条铁律：
    ① 只改「文本节点」——标签属性里的 id（href/data-*）绝不碰，否则会把 span 注进属性里破结构；
    ② 不在这里发网络请求（渲染路径保持纯的）→ 请求推到渲染之后的 setTimeout。
    多行代码块 <pre> 整块挖掉保护。 */
function wishRefsToTitles(html) {
  const s = String(html == null ? '' : html);
  if (s.indexOf('wish-') < 0) return s;
  try {
    return _eachTextNode(s, (seg) => seg.replace(/\bwish-[0-9a-f]{6,}\b/g, _wishSpan));
  } catch (e) {
    return s;   // 渲染出口宁可不改，也不能让正文挂掉
  }
}
try { window.wishRefsToTitles = wishRefsToTitles; } catch (eWT) {}

/* 项目内相对路径 → 可点、点了铺中栏 (BRO 2026-09-28 · wish-6b0dcf4d)
   「现在对话里出现的文件名，是不是可以点击之后直接在中栏显示？」
   判据故意收窄: 必须以【已知顶层目录】开头 + 已知扩展名 + 至少两级。
   收窄的代价是少数真路径没变按钮（照样能读），
   放宽的代价是普通代码片段被当成链接 —— 后者更烦人，所以宁窄不宽。 */
const _MD_PATH_ROOT = /^(data|static|workers|agent_tools|api_routes|tools|docs|soul|sessions|vendor|scripts|tests)\//;
const _MD_PATH_EXT = /\.(md|markdown|html?|py|js|mjs|css|json|txt|csv|log|ya?ml|toml|ini|docx?|xlsx?|pptx?|pdf|png|jpe?g|gif|webp|svg|mp4|db)$/i;

function _looksLikeProjectPath(s) {
  const t = String(s || "").trim().replace(/^\.\//, "");
  if (!t || t.length > 320) return false;
  if (/[\s<>"'|*?\n\\]/.test(t)) return false;              // 空白/引号/反斜杠 → 不像路径
  if (/^[a-z][a-z0-9+.\-]*:\/\//i.test(t)) return false;   // URL 走媒体/文档卡那条路
  if (t.indexOf("/") < 0) return false;                     // 至少两级
  if (!_MD_PATH_ROOT.test(t)) return false;                 // 必须以已知顶层目录开头
  if (!_MD_PATH_EXT.test(t)) return false;                  // 必须以已知扩展名结尾
  return true;
}

function _mdEsc(x) {
  return String(x).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function _fileRefHtml(p) {
  const name = p.split("/").pop() || p;
  const icon = /\.(md|markdown)$/i.test(p) ? "ri-file-text-line"
    : /\.(html?)$/i.test(p) ? "ri-window-line"
    : /\.(docx?|rtf)$/i.test(p) ? "ri-file-word-line"
    : /\.(xlsx?|csv)$/i.test(p) ? "ri-file-excel-line"
    : /\.(pptx?)$/i.test(p) ? "ri-file-ppt-line"
    : /\.(png|jpe?g|gif|webp|svg|bmp)$/i.test(p) ? "ri-image-line"
    : /\.(mp4|webm|mov)$/i.test(p) ? "ri-film-line"
    : /\.(py|js|mjs|css|json|ya?ml|toml)$/i.test(p) ? "ri-code-line"
    : "ri-file-line";
  return '<button type="button" class="md-file-ref" data-path="' + _mdEsc(p) + '"'
    + ' title="' + _mdEsc(p) + ' · 点开铺到中栏"'
    + ' onclick="event.stopPropagation();return window._mdOpenPath(this)">'
    + '<i class="' + icon + '"></i><span>' + _mdEsc(name) + '</span></button>';
}

// 点了铺中栏。打不开就给一句人话（手册: 用户触发的操作失败别静默 return）
window._mdOpenPath = function (el) {
  const p = (el && el.getAttribute && el.getAttribute("data-path")) || "";
  if (!p) return false;
  let ok = false;
  try { ok = !!(typeof openStage === "function" && openStage({ path: p })); } catch (e) { ok = false; }
  if (ok) return false;
  const span = el && el.querySelector ? el.querySelector("span") : null;
  if (el && el.classList) {
    const old = span ? span.textContent : "";
    el.classList.add("is-fail");
    if (span) span.textContent = "打不开这个路径";
    setTimeout(function () {
      if (el.classList) el.classList.remove("is-fail");
      if (span) span.textContent = old;
    }, 1600);
  }
  return false;
};

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
      const btn = (ic, label, fn) => `<button class="mdc-btn" onclick="event.stopPropagation();${fn}('${jsStr(domain)}','${jsStr(filename)}','${jsStr(ext)}')" title="${escHtml(label)}"><i class="${ic}"></i>${label}</button>`;
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
  // 还原 inline code —— 项目内相对路径渲成可点按钮（点了铺中栏），其余原样
  html = html.replace(/\x00INLINE(\d+)\x00/g, (m, i) => {
    const code = inlineCodes[+i];
    if (_looksLikeProjectPath(code)) return _fileRefHtml(String(code).trim());
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

  return wishRefsToTitles(html);
}
// 卷四十六续 11 补丁 · 暴露给 workshop.js 等其他 module 复用 (e.g. opus app 系统提示词渲染)
try { window.opusMdRender = mdRender; } catch (e) { /* 顶层环境异常 · 跳过 */ }
