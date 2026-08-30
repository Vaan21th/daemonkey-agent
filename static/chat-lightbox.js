/* 灯箱 + BRO 气泡附件。工作台 / 陪伴同一份。
   历史重建走 /attachments/文件名；刚发出去的还带着 data_url。 */
'use strict';

(function (g) {
  function escHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function broAttachStrip(raw) {
    const s = String(raw || '');
    const head = s.slice(0, 500);
    const dirty = s.indexOf('[用户上传了') === 0
      || head.indexOf('路径 B ·') >= 0
      || head.indexOf('竞速池 winner') >= 0;
    if (!dirty) return { body: s, legacy: [], stripped: false };
    let body = s;
    const sep = s.lastIndexOf('\n---\n');
    if (sep >= 0) body = s.slice(sep + 5).trim();
    else if (s.indexOf('[用户上传了') >= 0) body = '';
    const legacy = [];
    const re = /attachments[/\\]([^\s·\]\r\n]+)/g;
    let m;
    while ((m = re.exec(s)) !== null) { if (m[1]) legacy.push(m[1]); }
    return { body: body, legacy: legacy, stripped: true };
  }

  function attachUrl(a) {
    if (a && a.data_url) return a.data_url;
    const raw = String((a && (a.path || a.name)) || '');
    const base = raw.split('/').pop().split('\\').pop();
    return base ? '/attachments/' + encodeURIComponent(base) : '';
  }

  function isImgAtt(a, url) {
    return (a && (a.kind === 'image' || a.type === 'image'))
      || String((a && a.mime) || '').indexOf('image/') === 0
      || /\.(png|jpe?g|gif|webp|bmp|svg)(\?|$)/i.test(url || '');
  }

  function renderBroAttachments(bubble, atts) {
    if (!bubble || !atts || !atts.length) return;
    const wrap = document.createElement('div');
    wrap.className = 'bro-attach-imgs';
    atts.forEach(function (a) {
      const url = attachUrl(a);
      if (!url) return;
      if (isImgAtt(a, url)) {
        const img = document.createElement('img');
        img.className = 'bro-attach-img md-img';
        img.src = url;
        img.dataset.full = url;
        img.alt = a.name || '';
        img.title = a.name || '点开看大图';
        img.loading = 'lazy';
        img.addEventListener('error', function () {
          img.classList.add('bro-attach-missing');
          img.removeAttribute('data-full');
          img.alt = '图已经不在了';
          img.title = '这张图已经找不到了';
        });
        wrap.appendChild(img);
      } else {
        const card = document.createElement('a');
        card.className = 'attach-doc-card bro-attach-doc';
        card.href = url;
        card.target = '_blank';
        card.rel = 'noopener';
        card.innerHTML = '<i class="ri-file-3-line"></i><span class="doc-name">'
          + escHtml(a.name || url.split('/').pop()) + '</span>';
        wrap.appendChild(card);
      }
    });
    if (wrap.children.length) bubble.appendChild(wrap);
  }

  function ensureLightbox() {
    let box = document.getElementById('md-lightbox');
    if (box) return box;
    box = document.createElement('div');
    box.id = 'md-lightbox';
    box.hidden = true;
    box.innerHTML =
      '<img id="md-lightbox-img" alt="">'
      + '<button id="md-lightbox-close" type="button" aria-label="关闭 (Esc)">×</button>'
      + '<div id="md-lightbox-caption"></div>';
    document.body.appendChild(box);
    box.addEventListener('click', function (e) {
      if (e.target === box || e.target.id === 'md-lightbox-close') hideLightbox();
    });
    return box;
  }

  function showLightbox(src, alt) {
    if (!src) return;
    const box = ensureLightbox();
    const img = box.querySelector('#md-lightbox-img');
    const cap = box.querySelector('#md-lightbox-caption');
    img.src = src;
    img.alt = alt || '';
    cap.textContent = alt || '';
    box.hidden = false;
    document.body.style.overflow = 'hidden';
  }

  function hideLightbox() {
    const box = document.getElementById('md-lightbox');
    if (!box || box.hidden) return;
    box.hidden = true;
    document.body.style.overflow = '';
    const img = box.querySelector('#md-lightbox-img');
    if (img) img.removeAttribute('src');
  }

  if (!g.__opusLightboxBound) {
    g.__opusLightboxBound = true;
    document.addEventListener('click', function (e) {
      const img = e.target.closest && e.target.closest('.md-img, .bro-attach-img');
      if (!img || img.classList.contains('bro-attach-missing')) return;
      if (e.target.closest && e.target.closest('#md-lightbox')) return;
      e.preventDefault();
      showLightbox(img.dataset.full || img.src, img.alt);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      const box = document.getElementById('md-lightbox');
      if (!box || box.hidden) return;
      e.preventDefault();
      e.stopPropagation();
      hideLightbox();
    }, true);
  }

  g._broAttachStrip = broAttachStrip;
  g._renderBroAttachments = renderBroAttachments;
  g._showLightbox = showLightbox;
  g._hideLightbox = hideLightbox;
  g._ensureLightbox = ensureLightbox;
})(window);
