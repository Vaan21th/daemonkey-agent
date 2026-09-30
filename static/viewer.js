/**
 * OPUS 通用浮层查看器 · viewer.js
 * ══════════════════════════════════════════════════════════════════
 * 为什么要有它 (BRO 2026-09-19):
 *   产物库里点「预览」会把**整个面板顶掉** —— 关掉回去要重新 loadDashboard()，
 *   重新拉数据 + 重渲 2858 条，滚动位置 / 页码 / 分组全丢。BRO 原话:
 *     「这些图片和视频类的，也要用中栏看嘛？…不然每次中栏看再回来就要重新加载打开很麻烦」
 *   他还说:「这些弹框打开，是不是可以复用某些代码？把那部分代码独立拆出来？
 *              避免以后类似的都要写一套不同的」
 *
 * 判据 (一条管所有格式 · 不各写各的):
 *   能圈字批注的 (md / html / office)  → 中栏 (stage.js)
 *   只能看的   (图片 / 视频 / 音频 / PDF) → 这个浮层
 *   —— 跟产物卡上「能不能圈字」是同一个判据。
 *
 * 性质: 即看即走 · **不存任何状态** (不记「上次打开的是哪个」· 别做成常驻)
 * 形态: 全局唯一宿主 #opusViewer · 懒建 · 单例互斥
 *
 * 用法:
 *   OpusViewer.open({ path: 'data/design/x.png', name: 'x.png' });
 *   OpusViewer.open({ path: p, items: [{path,name},...], idx: 3 });   // 一批里左右翻
 *   OpusViewer.close();
 */
(function () {
  'use strict';

  var HOST_ID = 'opusViewer';
  var _items = [];
  var _idx = 0;
  var _bound = false;

  // ⚠ 这四张表和 dashboard-panels.js 的 _SHELF_TYPES 必须对齐 (同一件事别写两份)。
  //   曾经对不上：mkv / avi 在 _SHELF_TYPES 里算 video → 卡片会出「预览」按钮，
  //   而这里的 VID 不认它 → canView=false → 静默跳去中栏，按钮名不符实。
  //   改任何一张表时，另一张同步改。
  var IMG = { png: 1, jpg: 1, jpeg: 1, gif: 1, webp: 1, bmp: 1, svg: 1, ico: 1 };
  var VID = { mp4: 1, webm: 1, mov: 1, m4v: 1, ogv: 1, mkv: 1, avi: 1 };
  var AUD = { mp3: 1, wav: 1, m4a: 1, ogg: 1, flac: 1, aac: 1 };
  var MD = { md: 1, markdown: 1, txt: 1 };
  // 明确不可浮层看的 (会走中栏) —— 和 _SHELF_TYPES 里的 web / office 同上
  var NOT_HERE = { html: 1, htm: 1, docx: 1, doc: 1, pptx: 1, ppt: 1, xlsx: 1, xls: 1 };

  function _tok() { return (typeof token !== 'undefined' && token) ? token : ''; }
  function _ext(n) { var m = String(n || '').match(/\.([a-z0-9]+)$/i); return m ? m[1].toLowerCase() : ''; }
  function _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function kindOf(name) {
    var e = _ext(name);
    if (IMG[e]) return 'image';
    if (VID[e]) return 'video';
    if (AUD[e]) return 'audio';
    if (MD[e]) return 'md';
    if (e === 'pdf') return 'pdf';
    if (NOT_HERE[e]) return 'other';   // html / office —— 主场是中栏(能圈字批注)
    // 没见过的扩展名: 归 other → 不进浮层、走中栏。
    //   宁可保守 (少给一个按钮) 也不要给一个点了打不开的按钮。
    return 'other';
  }
  function urlOf(p) {
    return '/stage/file/' + String(p || '').replace(/\\/g, '/') + '?token=' + encodeURIComponent(_tok());
  }

  function _host() {
    var h = document.getElementById(HOST_ID);
    if (!h) {
      h = document.createElement('div');
      h.id = HOST_ID;
      h.className = 'ov-host';
      document.body.appendChild(h);
    }
    return h;
  }

  function _bodyHtml(it) {
    var k = kindOf(it.name);
    var u = _esc(urlOf(it.path));
    if (k === 'image') return '<img class="ov-img" src="' + u + '" alt="">';
    if (k === 'video') return '<video class="ov-video" src="' + u + '" controls autoplay playsinline></video>';
    if (k === 'audio') {
      return '<div class="ov-plain"><i class="ri-music-2-line"></i><p class="ov-plain-name">' + _esc(it.name) + '</p>'
        + '<audio src="' + u + '" controls autoplay></audio></div>';
    }
    if (k === 'pdf') return '<iframe class="ov-pdf" src="' + u + '"></iframe>';
    // 文稿 (BRO 2026-09-19:「预览和中栏看这个逻辑就覆盖全部产物吧，文档也是」)
    //   渲染通路直接复用中栏那份: stageMdApi() 拿地址 + 全局 mdRender() 渲 —— 不另造一套
    if (k === 'md') return '<article class="ov-md rp-md" id="ovMdBody"><div class="ov-tip">打开文稿…</div></article>';
    return '<div class="ov-plain"><i class="ri-file-unknow-line"></i><p class="ov-plain-name">' + _esc(it.name) + '</p>'
      + '<p class="ov-tip">这个格式浮层看不了 · 用「铺到中栏」或「下载」</p></div>';
  }

  function _render() {
    var h = _host();
    var it = _items[_idx];
    if (!it) return;
    h.innerHTML =
      '<div class="ov-mask"></div>'
      + '<div class="ov-box">'
      + '<div class="ov-head">'
      + '<span class="ov-title" title="' + _esc(it.name) + '">' + _esc(it.name) + '</span>'
      + '<span class="ov-sub"></span>'
      + '<span class="ov-spacer"></span>'
      + '<button type="button" class="ov-btn" data-ov="stage" title="需要圈字批注 / 配文？铺到中栏"><i class="ri-layout-right-2-line"></i> 铺到中栏</button>'
      + '<a class="ov-btn" data-ov="dl" href="' + _esc(urlOf(it.path)) + '" download="' + _esc(it.name) + '"><i class="ri-download-2-line"></i> 下载</a>'
      + '<button type="button" class="ov-btn ov-close" data-ov="close" title="关闭 (Esc)">✕</button>'
      + '</div>'
      + '<div class="ov-body">' + _bodyHtml(it) + '</div>'
      + (_items.length > 1
        ? '<div class="ov-nav">'
          + '<button type="button" class="ov-arrow" data-ov="prev" title="上一个 (←)">‹</button>'
          + '<span class="ov-pos">' + (_idx + 1) + ' / ' + _items.length + '</span>'
          + '<button type="button" class="ov-arrow" data-ov="next" title="下一个 (→)">›</button>'
          + '</div>'
        : '')
      + '</div>';
    h.classList.add('show');
    _wire(h);
    // 图片加载后补真实尺寸 (不预加载 · 拿到就算)
    var img = h.querySelector('.ov-img');
    if (img) {
      var sub = h.querySelector('.ov-sub');
      img.onload = function () { if (sub) sub.textContent = img.naturalWidth + ' × ' + img.naturalHeight; };
    }
    // 文稿异步拉正文 (拿完再填 · 期间用户可能已翻页或关掉)
    if (kindOf(it.name) === 'md') _loadMd(it);
  }

  function _loadMd(it) {
    var api = (typeof window.stageMdApi === 'function') ? window.stageMdApi(it.path) : null;
    var node0 = document.getElementById('ovMdBody');
    if (!node0) return;
    if (!api) {
      node0.innerHTML = '<div class="ov-tip">这份文稿浮层里打不开 · 用「铺到中栏」</div>';
      return;
    }
    var u = api.url + (api.url.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(_tok());
    var mine = it.path;
    fetch(u, { headers: { Authorization: 'Bearer ' + _tok() } })
      .then(function (r) {
        if (!r.ok) return null;
        return api.type === 'json' ? r.json() : r.text();
      })
      .then(function (j) {
        var cur = _items[_idx];
        if (!cur || cur.path !== mine) return;   // 已经翻走 / 关掉了
        var node = document.getElementById('ovMdBody');
        if (!node) return;
        if (j === null) { node.innerHTML = '<div class="ov-tip">打不开这份文稿</div>'; return; }
        var text = (api.type === 'json') ? ((j && j[api.field]) || '') : (j || '');
        if (!text) { node.innerHTML = '<div class="ov-tip">这份文稿是空的</div>'; return; }
        var html = '';
        if (typeof window.opusMdRender === 'function') html = window.opusMdRender(text);
        else if (typeof mdRender === 'function') html = mdRender(text);
        node.innerHTML = html || ('<pre class="ov-pre">' + _esc(text) + '</pre>');
      })
      .catch(function () {
        // 和 .then 一样得先确认「没翻走、没关掉」—— 否则 A 的请求失败时，
        //   这句会把错误提示写进 B 的格子，看着像 B 打不开（实际 B 还在加载）。
        //   快速翻页就撞得上，是一种「看起来不像 bug 的 bug」。
        var cur = _items[_idx];
        if (!cur || cur.path !== mine) return;
        var node = document.getElementById('ovMdBody');
        if (node) node.innerHTML = '<div class="ov-tip">打不开这份文稿</div>';
      });
  }

  function _wire(h) {
    var mask = h.querySelector('.ov-mask');
    if (mask) mask.onclick = close;
    h.querySelectorAll('[data-ov]').forEach(function (el) {
      el.onclick = function (e) {
        var a = el.getAttribute('data-ov');
        if (a === 'close') { close(); }
        else if (a === 'stage') {
          var it = _items[_idx];
          close();
          if (it && typeof window.openStage === 'function') window.openStage({ path: it.path });
        } else if (a === 'prev' || a === 'next') {
          e.preventDefault();
          _step(a === 'prev' ? -1 : 1);
        }
      };
    });
  }

  function _step(d) {
    if (_items.length < 2) return;
    _idx = (_idx + d + _items.length) % _items.length;
    _render();
  }

  function open(opts) {
    opts = opts || {};
    var path = opts.path || (opts.items && opts.items[opts.idx || 0] && opts.items[opts.idx || 0].path) || '';
    if (!path) return;
    if (Array.isArray(opts.items) && opts.items.length) {
      _items = opts.items.slice();
      var f = -1;
      for (var i = 0; i < _items.length; i++) { if (_items[i].path === path) { f = i; break; } }
      if (f >= 0) {
        _idx = f;
      } else {
        // 这一份不在同批里 (例: 「中栏看」按钮来的 · 它不携 data-open-view) ——
        // 就单开一格。绝不能 _idx=0 去显示别人:
        //   BRO 2026-09-19 实测「点 md 的中栏看，弹出来一张无关的图 1/34」就是这个。
        _items = [{ path: path, name: opts.name || String(path).split('/').pop() }];
        _idx = 0;
      }
    } else {
      _items = [{ path: path, name: opts.name || String(path).split('/').pop() }];
      _idx = 0;
    }
    if (!_bound) {
      document.addEventListener('keydown', _key);
      _bound = true;
    }
    _render();
  }

  function _key(e) {
    var h = document.getElementById(HOST_ID);
    if (!h || !h.classList.contains('show')) return;
    if (e.key === 'Escape') { close(); }
    else if (e.key === 'ArrowLeft') { _step(-1); }
    else if (e.key === 'ArrowRight') { _step(1); }
    else return;
    e.preventDefault();
  }

  function close() {
    var h = document.getElementById(HOST_ID);
    if (!h) return;
    h.classList.remove('show');
    h.innerHTML = '';   // 顺手停掉 video / audio 的播放
    _items = [];
    _idx = 0;
  }

  function isOpen() {
    var h = document.getElementById(HOST_ID);
    return !!(h && h.classList.contains('show'));
  }

  window.OpusViewer = {
    open: open,
    close: close,
    isOpen: isOpen,
    kindOf: kindOf,
    canView: function (n) { return kindOf(n) !== 'other'; },
  };
})();
