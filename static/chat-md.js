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
