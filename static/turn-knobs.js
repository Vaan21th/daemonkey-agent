/* 本轮旋钮条 · 思考 / 强度 (用户 2026-09-15 · 二次修订)
   ────────────────────────────────────────────────────────────────
   为什么有这一层:
     思考模式 / 推理强度 原本在顶栏「模型切换」菜单的「模型行为」区块里。
     它们是「这一轮怎么跑」的旋钮，不是全局设置；埋在模型菜单里要两步才够到。
     搬来输入框下面（跟顾问协同并排）· 做成 chip + 浮层菜单，功能条不被撑爆。
     输出上限没搬 —— 那是模型级设置，留在原处，两边不重复。

   设计原则: 不复制控件，只用桥。
     真正的 <select id=mbThinking>/<select id=mbEffort> 还留在模型菜单里，
     本文件负责:
       · 把它们做进 chip 浮层菜单（值/文案/禁用态一致）
       · 点 chip → 弹菜单 → 选中 → 回写原控件 + 派发 change
     于是 model-switch.js 里那一整套档位逻辑（applyEffortLevels / fillThinkUi /
     applyThinkOffUi / _patchThink 落本会话 meta）一行都不用改，两边永远同源。

   两个同步方向:
     用户拨 chip        → 回写原控件，派发 change（下游照旧）
     程序改原控件(切模型/切对话/切标签) → MutationObserver 把 chip 状态拉回来

   记两笔坑 (2026-09-15):
     ① 文件要进 api_routes/core.py 的 _STATIC_WHITELIST，否则 /static/turn-knobs.js
        直接 404 → 脚本从没跑过 → chip 点了完全没反应（而且静默无报错）。
     ② 第一版用 addEventListener('scroll', closeMenu, true) —— 捕获阶段监听 scroll
        会把页面里任何滚动都当成"关上菜单"，菜单刚插进 DOM 就被下一次滚动同步关掉
        → 看着也像"点了不弹"。现在只在"点了别处"和 ESC 时关。 */

(function () {
  'use strict';

  var ID_THINK = 'mbThinking';
  var ID_EFFORT = 'mbEffort';

  function el(id) { return document.getElementById(id); }

  /* ── chip 文案 (只显短名 · 具体档位在菜单里看) ────────────── */

  var THINK_SHORT = { auto: '自动', on: '开', off: '关' };

  function chipState() {
    var $t = el(ID_THINK);
    var $e = el(ID_EFFORT);
    var think = $t ? ($t.value || 'auto') : '';
    var effort = '';
    if ($e && !$e.disabled) {
      var o = $e.options[$e.selectedIndex];
      effort = ($e.value || '') ? ((o && o.textContent) || $e.value) : '默认';
    }
    return {
      think: think,
      thinkDisabled: !!($t && $t.disabled),
      effort: effort,
      effortDisabled: !!(($e && $e.disabled) || !$e),
    };
  }

  function refreshChips() {
    var st = chipState();
    var bt = document.getElementById('turnThinkBtn');
    var et = document.getElementById('turnEffortBtn');
    if (bt) {
      bt.classList.toggle('tk-off', st.thinkDisabled || st.think === 'off');
      bt.classList.toggle('tk-on', st.think === 'on');
      bt.title = st.thinkDisabled
        ? '该模型关不掉思考'
        : ('思考 · ' + (THINK_SHORT[st.think] || st.think) + '（点一下切换）');
    }
    if (et) {
      et.classList.toggle('tk-off', st.effortDisabled || !st.effort || st.effort === '默认');
      et.classList.toggle('tk-on', !!st.effort && st.effort !== '默认');
      et.title = st.effortDisabled
        ? '该模型不吃推理强度参数'
        : ('强度 · ' + (st.effort || '默认') + '（点一下切换）');
    }
    // ③ 用户 2026-09-15 图3: 选哪档 · chip 的图标和颜色就跟着换 (= 一眼看出这一轮跑多猛)
    _paintChipIcon(bt, ICON[st.think] || 'ri-brain-line', TONE[st.think] || '');
    var ek = _effortKey();
    _paintChipIcon(et, EICON[ek] || 'ri-flashlight-line', ETONE[ek] || '');
  }

  /* 强度档位原始 key (minimal/low/medium/high/max) —— 中文 label 查不到图标表 */
  function _effortKey() {
    var $e = el(ID_EFFORT);
    return ($e && $e.value) ? String($e.value).toLowerCase().trim() : '';
  }
  function _paintChipIcon(btn, iconCls, tone) {
    if (!btn) return;
    var i = btn.querySelector('i');
    if (i) {
      if (i.className !== iconCls) i.className = iconCls;
      i.style.color = tone || '';
    }
    // ② 用户 2026-09-15 图2: 按钮本体也跟着图标颜色变 (文字/边框/淡底同色系·不再是固定蓝紫)
    if (tone) {
      btn.style.color = tone;
      btn.style.borderColor = _toneRgba(tone, 0.55);
      btn.style.background = _toneRgba(tone, 0.10);
    } else {
      btn.style.color = ''; btn.style.borderColor = ''; btn.style.background = '';
    }
  }
  function _toneRgba(hex, a) {
    var s = String(hex || '').replace('#', '');
    if (s.length === 3) s = s[0] + s[0] + s[1] + s[1] + s[2] + s[2];
    if (s.length !== 6) return '';
    var n = parseInt(s, 16);
    if (isNaN(n)) return '';
    return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')';
  }

  /* 选项的图标与色调 (用户 2026-09-15: 用图标和颜色区分不同选项)
     思考: 自动=灰 / 开=蓝 / 关=青
     强度: 由冷到暖 (最小→极高 · 火力越大越暖) —— 一眼看出“这一轮跑多猛” */
  var ICON = { auto: 'ri-question-line', on: 'ri-brain-line', off: 'ri-flashlight-line' };
  var TONE = { auto: '#8b93a1', on: '#6ea8ff', off: '#35c9a0' };
  var EICON = { minimal: 'ri-speed-mini-line', low: 'ri-speed-line', medium: 'ri-speed-up-line', high: 'ri-rocket-line', max: 'ri-fire-line' };
  var ETONE = { minimal: '#5ec8ff', low: '#6ea8fe', medium: '#a97bff', high: '#e07bff', max: '#ff8a5c' };

  /* ── 浮层菜单 ──────────────────────────────────────────────── */

  var _menu = null;
  var _owner = null;

  function closeMenu() {
    if (_menu && _menu.parentNode) _menu.parentNode.removeChild(_menu);
    _menu = null;
    if (_owner) _owner.classList.remove('tk-open');
    _owner = null;
  }

  function esc(s) {
    return String(s || '').replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  /* 选中后回写原控件 + 派发 change（下游 model-switch.js 照常处理） */
  function writeBack($e, value) {
    if (!$e) return;
    $e.value = value;
    try { $e.dispatchEvent(new Event('change', { bubbles: true })); } catch (err) { /* noop */ }
  }

  /* 菜单位置：fixed 定位 + 挂 body
     为什么不用 absolute 挂在 chip 里：功能条/输入区祖先有 overflow 裁剪，
     菜单向上弹会被裁成"看不见"（DOM 里有、屏幕上没有，看着就像"点了不弹"）。
     fixed 挂 body 就完全脱离裁剪与层叠上下文。 */
  function positionMenu() {
    if (!_menu || !_owner) return;
    var r = _owner.getBoundingClientRect();
    var mh = _menu.offsetHeight || 0;
    var mw = _menu.offsetWidth || 240;
    var left = Math.max(8, Math.min(r.left, window.innerWidth - mw - 8));
    _menu.style.left = left + 'px';
    if (mh && (r.top - 8) < mh) {          // 上方放不下 → 改弹下方
      _menu.style.top = (r.bottom + 6) + 'px';
      _menu.style.bottom = 'auto';
    } else {
      _menu.style.top = 'auto';
      _menu.style.bottom = (window.innerHeight - r.top + 6) + 'px';
    }
  }

  var _raf = 0;
  function scheduleReposition() {
    if (_raf) return;
    _raf = window.requestAnimationFrame(function () { _raf = 0; positionMenu(); });
  }

  function openMenu(ownerBtn, items) {
    var wasOpen = (_owner === ownerBtn) && !!_menu;
    closeMenu();
    if (wasOpen) return;             // 再点一次同一个 chip = 收起
    _owner = ownerBtn;
    ownerBtn.classList.add('tk-open');

    var box = document.createElement('div');
    box.className = 'turn-menu';
    box.setAttribute('role', 'menu');

    items.forEach(function (it) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'turn-menu-item' + (it.on ? ' on' : '');
      if (it.disabled) {
        b.disabled = true;
        b.style.opacity = '0.45';
        b.style.cursor = 'default';
      }
      if (it.tone) b.style.setProperty('--tmi', it.tone);
      b.innerHTML = '<i class="tmi-ic ' + esc(it.icon || 'ri-circle-line') + '" aria-hidden="true"></i>'
        + '<span class="tmi-body"><b>' + esc(it.label) + '</b>'
        + (it.note ? '<small>' + esc(it.note) + '</small>' : '')
        + '</span><i class="ri-check-line tmi-check"></i>';
      if (!it.disabled && it.pick) {
        b.onclick = function (ev) {
          ev.stopPropagation();
          it.pick();
          closeMenu();
          refreshChips();
        };
      }
      box.appendChild(b);
    });

    document.body.appendChild(box);
    _menu = box;
    positionMenu();
  }

  /* ── 两个菜单的内容 (从原 select 的 option 现取 · 天然同源) ── */

  function thinkItems() {
    var $t = el(ID_THINK);
    var cur = $t ? ($t.value || 'auto') : 'auto';
    var off = !!($t && $t.disabled);
    var out = [{
      label: '自动',
      note: '跟随模型与设置：能关就关，关不掉如实标注',
      icon: ICON.auto, tone: TONE.auto,
      on: cur === 'auto',
      disabled: off,
      pick: function () { writeBack($t, 'auto'); },
    }];
    if ($t) {
      for (var i = 0; i < $t.options.length; i++) {
        var o = $t.options[i];
        if (o.value === 'auto') continue;
        out.push({
          label: o.textContent.replace(/^[^·]*·\s*/, '').trim() || o.textContent,
          icon: ICON[o.value] || 'ri-circle-line',
          tone: TONE[o.value] || '',
          note: o.value === 'off'
            ? '最快最省 · 复杂题会掉质量'
            : '强制深度思考 · 复杂任务更稳，但慢且贵',
          on: cur === o.value,
          disabled: off,
          pick: (function (v) { return function () { writeBack($t, v); }; })(o.value),
        });
      }
    }
    if (off) out.push({ label: '该模型关不掉思考', note: '想省 token 只能换模型', icon: 'ri-lock-line', tone: '#8b93a1', disabled: true });
    return out;
  }

  function effortItems() {
    var $e = el(ID_EFFORT);
    if (!$e) return [{ label: '不可用', note: '没找到强度控件', disabled: true }];
    if ($e.disabled) {
      return [{ label: '该模型不吃推理强度参数', note: $e.title || '', disabled: true }];
    }
    var cur = $e.value || '';
    var out = [];
    for (var i = 0; i < $e.options.length; i++) {
      var o = $e.options[i];
      out.push({
        label: o.textContent,
        note: (o.value === '' ? '不发送这个参数' : ''),
        icon: EICON[o.value] || 'ri-equalizer-line',
        tone: o.value ? (ETONE[o.value] || '') : '#8b93a1',
        on: (o.value || '') === cur,
        pick: (function (v) { return function () { writeBack($e, v); }; })(o.value),
      });
    }
    return out;
  }

  /* ── 绑定 + 双向同步 ──────────────────────────────────────── */

  function bind() {
    var bt = document.getElementById('turnThinkBtn');
    var be = document.getElementById('turnEffortBtn');
    if (!bt || !be) return false;
    if (bt.dataset.tkBound) return true;
    bt.dataset.tkBound = '1';

    bt.onclick = function (e) {
      e.preventDefault();
      e.stopPropagation();
      openMenu(bt, thinkItems());
    };
    be.onclick = function (e) {
      e.preventDefault();
      e.stopPropagation();
      openMenu(be, effortItems());
    };

    // 点别处 / ESC 关菜单。
    // 注意: 绝对不要监听 scroll 来关 —— 见文件头注释②（那会让菜单"点了不弹"）。
    if (!document.documentElement.dataset.tkOutside) {
      document.documentElement.dataset.tkOutside = '1';
      document.addEventListener('click', function (e) {
        if (e.target && e.target.closest && e.target.closest('.turn-menu, .turn-knob')) return;
        closeMenu();
      });
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') closeMenu();
      });
      /* 滚动 / 缩放时跟随 chip 重新定位（捕获阶段能收到所有内部滚动）。
         注意：只重定位、不关闭 —— 流式输出会不停自滚，一滚就关等于菜单打不开。 */
      window.addEventListener('scroll', scheduleReposition, true);
      window.addEventListener('resize', scheduleReposition);
    }

    /* 程序改原控件 → chip 跟上。
       切模型 / 切对话 / 切标签走 fillThinkUi / applyEffortLevels / applyThinkOffUi，
       这三条都会改原控件的 value / disabled / innerHTML；MutationObserver 盯住就够，
       不必在那三个函数里插钩子（插钩子等于又多三处会漏掉的同步点）。 */
    var obs = window.MutationObserver ? new MutationObserver(function () { refreshChips(); }) : null;
    [el(ID_THINK), el(ID_EFFORT)].forEach(function (node) {
      if (!node) return;
      if (obs) obs.observe(node, { attributes: true, childList: true, subtree: true, characterData: true });
      // value 是 property，改它不触发 attribute mutation → 再补 change/input
      node.addEventListener('change', refreshChips);
      node.addEventListener('input', refreshChips);
    });

    refreshChips();
    /* 兜底轮询：程序直接改 select.value（fillThinkUi / applyEffortLevels）既不触发
       attribute mutation 也不派发 change → chip 会滞后。1s 比一次签名，变了才刷。 */
    var lastSig = '';
    setInterval(function () {
      var st = chipState();
      var sig = st.think + '|' + st.thinkDisabled + '|' + st.effort + '|' + st.effortDisabled;
      if (sig !== lastSig) { lastSig = sig; refreshChips(); }
    }, 1000);
    return true;
  }

  /* 对外: 别处（切对话/切模型后）想主动刷一下就调它 */
  window.refreshTurnKnobs = refreshChips;
  window.closeTurnKnobMenu = closeMenu;   // wish-16fa5930 · 档位 chip 菜单打开时互斥用

  function tryBind() { return bind(); }
  if (!tryBind()) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', tryBind);
    }
    var n = 0;
    var timer = setInterval(function () {
      if (tryBind() || ++n > 40) clearInterval(timer);
    }, 250);
  }
})();
