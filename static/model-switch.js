/* static/model-switch.js · 顶栏切模型 (工作台 + 陪伴共用)
   从 chat.js loadCurrentModel / switchModel 抽出。
   挂钩: token / sessionId / rememberSession / onError */

/* wish-00490c86 · 思考开关跟对话实例走
   以前 thinking/effort/max_tokens 存 localStorage 全局单键 —— B 对话关掉思考，切回 A
   对话时 A 也被关（全局覆盖）。现在 _curThink 只代表【当前对话】的记录，由 chat.js
   切会话时调 applySessionThink() 刷新；localStorage 退化为「新建对话的默认值」。
   _curThink = null 表示当前对话没记过 → 回退全局默认。 */
var _curThink = null;

/* wish-4fd607c5 · 当前模型真实的推理强度档位 (后端 /models 给 · 随模型变)
   null = 还没拿到 (别动现有值) · [] = 该模型不吃这参数 (标灰) */
var _effortLevels = null;
var _effortDefault = '';
var EFFORT_LABELS = { minimal: '最小 · 最快', low: '低 · 快', medium: '中', high: '高', max: '极高 · 最深' };
var EFFORT_SHORT = { minimal: '最小', low: '低', medium: '中', high: '高', max: '极高' };

function _globalThink() {
  var out = { thinking: '', reasoning_effort: '', max_tokens: '' };
  try {
    out.thinking = localStorage.getItem('opus_mb_thinking') || '';
    out.reasoning_effort = localStorage.getItem('opus_mb_effort') || '';
    out.max_tokens = localStorage.getItem('opus_mb_max_tokens') || '';
  } catch (_) {}
  return out;
}
function currentThink() { return _curThink || _globalThink(); }
window.currentThink = currentThink;

/* 切会话时由 chat.js 调 · meta.last_think_cfg 有记录就用它 · 否则回退全局默认 */
function applySessionThink(meta) {
  var cfg = meta && meta.last_think_cfg;
  if (cfg && typeof cfg === 'object' && Object.keys(cfg).length) {
    _curThink = {
      thinking: cfg.thinking || '',
      reasoning_effort: cfg.reasoning_effort || '',
      max_tokens: cfg.max_tokens ? String(cfg.max_tokens) : '',
    };
  } else {
    _curThink = null;
  }
  fillThinkUi();
}
window.applySessionThink = applySessionThink;

function fillThinkUi() {
  var t = currentThink();
  var $think = document.getElementById('mbThinking');
  var $effort = document.getElementById('mbEffort');
  var $mt = document.getElementById('mbMaxTokens');
  if ($think) $think.value = t.thinking || 'auto';
  if ($effort) {
    var lv = t.reasoning_effort || '';
    // wish-4fd607c5 · 存的档当前模型不认 (从 deepseek 的 high 切到只有 low 的模型) → 回落默认
    if (_effortLevels) {
      if (!_effortLevels.length) lv = '';
      else if (lv && _effortLevels.indexOf(lv) === -1) lv = _effortDefault || '';
      else if (!lv) lv = _effortDefault || '';   // wish-3d02d762 · 没存过档 → 落到模型默认档（select 里得有可匹配项 · 否则显示空白）
    }
    $effort.value = lv;
  }
  if ($mt) $mt.value = t.max_tokens || '';
}

/* 用户拨了开关 → 更新内存 + 写进本对话的 meta（localStorage 保留当新对话默认） */
function _patchThink(patch) {
  var b = currentThink();
  var next = {
    thinking: b.thinking || '',
    reasoning_effort: b.reasoning_effort || '',
    max_tokens: b.max_tokens || '',
  };
  Object.keys(patch || {}).forEach(function (k) { next[k] = patch[k]; });
  _curThink = next;
  try {
    var sid = (typeof sessionId === 'string' && sessionId) || '';
    var tok = (typeof token === 'string' && token) || localStorage.getItem('opus_ui_token') || '';
    if (!sid || sid.indexOf('tmp-') === 0 || !tok) return;   // 新对话还没落盘 → 只改内存
    fetch('/sessions/' + encodeURIComponent(sid) + '/meta', {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + tok, 'Content-Type': 'application/json' },
      body: JSON.stringify({ last_think_cfg: next }),
    }).catch(function () {});
  } catch (_) {}
}

function modelBehaviorPayload() {
  const out = {};
  try {
    const t = currentThink();
    const think = t.thinking || 'auto';
    const effort = t.reasoning_effort || '';
    const mt = t.max_tokens || '';
    if (think && think !== 'auto') out.thinking = think;
    if (effort) out.reasoning_effort = effort;
    const n = parseInt(mt, 10);
    if (n > 0) out.max_tokens = n;
  } catch (_) {}
  return out;
}
window.modelBehaviorPayload = modelBehaviorPayload;

/* wish-33624071 · 当前模型能不能【真关】思考 · 据 /models 的 current.think_off 同步开关态。
   none → 标灰 + 如实说明 (不假装能关) · soft_prompt → 提示走 prompt 软开关。
   每次 load() 重算·所以切模型后状态自动跟着变。 */
function applyThinkOffUi(cur) {
  var $think = document.getElementById('mbThinking');
  if (!$think) return;
  var mode = (cur && cur.think_off) || '';
  var row = $think.closest ? $think.closest('.mmb-row') : null;
  var hint = document.getElementById('mbThinkOffHint');
  if (mode === 'none') {
    $think.disabled = true;
    $think.title = '当前模型没有关思考的通路 (thinking 是模型定义的一部分) · 想省 token 请换模型';
    if (row && !hint) {
      hint = document.createElement('div');
      hint.id = 'mbThinkOffHint';
      hint.className = 'mmb-hint';
      row.parentNode.insertBefore(hint, row.nextSibling);
    }
    if (hint) hint.textContent = '该模型关不掉思考 · 想省 token 就换模型';
  } else {
    $think.disabled = false;
    $think.title = mode === 'soft_prompt'
      ? '关掉会走 prompt 软开关 (Qwen3 系 /no_think) · 实测省 ~88% token'
      : '';
    if (hint) hint.remove();
  }
}
window.applyThinkOffUi = applyThinkOffUi;

/* wish-4fd607c5 · 推理强度档位跟模型走 (不再写死 low/medium/high)。
   后端 /models 给 effort_levels / effort_default / effort_note:
   - levels 空 → 该模型不吃这个参数 → 标灰 + 如实说原因 (没意义的选择就别摆)
   - default 空 → 「不发送」(认不出的模型·保持老行为)；非空 → 那档就是模型默认·标签标注
   档位名对齐官方: low 低 / medium 中 / high 高 / max 极限 */
function _effortHint(text) {
  var $effort = document.getElementById('mbEffort');
  if (!$effort) return;
  var row = $effort.closest ? $effort.closest('.mmb-row') : null;
  if (!row) return;
  var hint = document.getElementById('mbEffortHint');
  if (!text) { if (hint) hint.remove(); return; }
  if (!hint) {
    hint = document.createElement('div');
    hint.id = 'mbEffortHint';
    hint.className = 'mmb-hint';
    row.parentNode.insertBefore(hint, row.nextSibling);
  }
  hint.textContent = text;
}

function applyEffortLevels(cur) {
  var $effort = document.getElementById('mbEffort');
  if (!$effort || !cur) return;
  var levels = cur.effort_levels || [];
  var supported = cur.effort_supported || [];
  var emap = cur.effort_map || {};
  var note = cur.effort_note || '';
  if (!levels.length || !supported.length) {
    // 该模型不吃这个参数 → 整行标灰 + 说明 (没意义的选择就别摆出来)
    _effortLevels = [];
    _effortDefault = '';
    $effort.innerHTML = '<option value="">不适用</option>';
    $effort.value = '';
    $effort.disabled = true;
    $effort.title = note || '该模型不支持推理强度参数';
    _effortHint(note || '该模型不支持推理强度参数');
    // wish-3d02d762 · 渲染路径不写持久层。旧写法无条件 _patchThink({reasoning_effort:''})：
    // 本对话没记过档时，会把全局默认整套快照进本会话并把档抹空 —— 用户只是轮询到一个
    // 不支持强度的模型，切回去也再回不来。只在「本对话确实存过一个档」时才清
    // （清完即空 → 下次刷新不再写 · 渲染恢复幂等）。
    if (_curThink && (_curThink.reasoning_effort || '')) _patchThink({ reasoning_effort: '' });
    return;
  }
  _effortLevels = levels.slice();
  _effortDefault = typeof cur.effort_default === 'string' ? cur.effort_default : '';
  var html = '';
  if (!_effortDefault) html += '<option value="">默认（不发送）</option>';
  levels.forEach(function (lv) {
    var label = EFFORT_LABELS[lv] || lv;
    if (lv === _effortDefault) label += '（模型默认）';
    var to = emap[lv];
    if (to && to !== lv) label += '（→' + (EFFORT_SHORT[to] || to) + '）';   // 就近映射如实标注
    html += '<option value="' + lv + '">' + label + '</option>';
  });
  $effort.innerHTML = html;
  $effort.disabled = false;
  $effort.title = note || '';
  _effortHint(note || '');
  fillThinkUi();   // 用新档位重算选中 (存的档不支持就回落默认)
}
window.applyEffortLevels = applyEffortLevels;

function initModelBehavior() {
  const $think = document.getElementById('mbThinking');
  const $effort = document.getElementById('mbEffort');
  const $mt = document.getElementById('mbMaxTokens');
  if (!$think && !$effort && !$mt) return;
  if (document.documentElement.dataset.mbBound) return;
  document.documentElement.dataset.mbBound = '1';
  fillThinkUi();
  $think && $think.addEventListener('change', () => {
    localStorage.setItem('opus_mb_thinking', $think.value);
    _patchThink({ thinking: $think.value === 'auto' ? '' : $think.value });
  });
  $effort && $effort.addEventListener('change', () => {
    localStorage.setItem('opus_mb_effort', $effort.value);
    _patchThink({ reasoning_effort: $effort.value || '' });
  });
  $mt && $mt.addEventListener('change', () => {
    const n = parseInt($mt.value, 10);
    if (n > 0) { localStorage.setItem('opus_mb_max_tokens', String(n)); _patchThink({ max_tokens: String(n) }); }
    else { localStorage.removeItem('opus_mb_max_tokens'); $mt.value = ''; _patchThink({ max_tokens: '' }); }
  });
}

function initModelSwitch(opts) {
  opts = opts || {};
  const box = document.getElementById('modelSwitch');
  const lab = document.getElementById('modelNameLabel');
  const menu = document.getElementById('modelMenu');
  const list = document.getElementById('modelMenuList');
  if (!box || !lab || !menu) return;

  const getToken = typeof opts.token === 'function'
    ? opts.token
    : function () { return (typeof token === 'string' && token) || localStorage.getItem('opus_ui_token') || ''; };
  const getSid = typeof opts.sessionId === 'function'
    ? opts.sessionId
    : function () { return (typeof sessionId === 'string' && sessionId) || ''; };
  const remember = typeof opts.rememberSession === 'function' ? opts.rememberSession : null;
  const onError = typeof opts.onError === 'function' ? opts.onError : null;

  let open = false;
  let options = [];

  function escHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function closeMenu() {
    open = false;
    menu.classList.remove('open');
  }
  function renderList() {
    if (!list) return;
    if (!options.length) {
      list.innerHTML = '<div class="model-menu-empty">没有可选模型</div>';
      return;
    }
    list.innerHTML = options.map(opt =>
      `<button type="button" class="model-menu-item${opt.current ? ' current' : ''}" data-alias="${escHtml(opt.alias)}" data-family="${escHtml(opt.family)}">`
      + `<div class="mmi-row1"><span class="mmi-alias">${escHtml(opt.name || opt.real_id)}</span>`
      + `<span class="mmi-family">${escHtml(opt.family)}</span>`
      + (opt.cache ? '<span class="mmi-cache" title="支持 cache · 省钱">$</span>' : '')
      + (opt.current ? '<span class="mmi-current">●</span>' : '')
      + `</div><div class="mmi-real">${escHtml(opt.real_id || '')}</div>`
      + `<div class="mmi-note">${escHtml(opt.note || '')}</div></button>`
    ).join('');
  }

  async function load(opts) {
    try {
      const tok = getToken();
      const r = await fetch('/models', { headers: tok ? { Authorization: 'Bearer ' + tok } : {} });
      if (!r.ok) { lab.textContent = '加载失败'; return; }
      const data = await r.json();
      const current = data.current || {};
      options = data.options || [];
      window._currentModelId = current.model || '';
      window._currentConfigId = current.config_id || '';
      window._directorModelId = (data.director && data.director.model) || '';
      if (typeof _advisorCoopRender === 'function') _advisorCoopRender();
      let display = current.model || '?';
      const matched = options.find(o => o.config_id === current.config_id || o.alias === current.config_id);
      if (matched && matched.name) display = matched.name;
      // wish-1518b97f · 切回正在跑的对话时 · 顶栏该显示「本对话记的模型」·
      // 而不是「上一场正在跑的」。后端要到下一轮才对齐 · 中间这段先显示对。
      const _want = (opts && opts.sessionCfg) || '';
      if (_want && _want !== (current.config_id || '')) {
        const _w = options.find(o => o.config_id === _want);
        if (_w) {
          display = (_w.name || _w.model || _want) + ' · 本对话';
          box.dataset.sessionCfg = '1';
        }
      } else {
        delete box.dataset.sessionCfg;
      }
      lab.textContent = display;
      box.dataset.family = current.family || '';
      applyThinkOffUi(current);   // wish-33624071 · 同步「思考能不能真关」
      applyEffortLevels(current); // wish-4fd607c5 · 同步「推理强度档位」(随模型变)
      renderList();
    } catch (e) {
      lab.textContent = 'offline';
    }
  }

  function rememberSession(alias) {
    if (remember) { remember(alias); return; }
    const sid = getSid();
    if (!sid || String(sid).startsWith('tmp-')) return;
    if (typeof sessionMetaCache === 'object' && sessionMetaCache) {
      if (!sessionMetaCache[sid]) sessionMetaCache[sid] = {};
      sessionMetaCache[sid].last_model_cfg = alias;
    }
    const tok = getToken();
    if (!tok) return;
    fetch('/sessions/' + encodeURIComponent(sid) + '/meta', {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + tok, 'Content-Type': 'application/json' },
      body: JSON.stringify({ last_model_cfg: alias }),
    }).catch(function () {});
  }

  async function switchTo(alias) {
    const tok = getToken();
    if (!tok || !alias) return;
    try {
      const r = await fetch('/models/switch', {
        method: 'POST',
        headers: { Authorization: 'Bearer ' + tok, 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: alias }),
      });
      if (!r.ok) {
        const t = await r.text();
        const msg = t.slice(0, 400) || '服务端没返详情';
        if (onError) await onError('切换模型失败', msg);
        else if (typeof opusAlert === 'function') {
          await opusAlert({ title: '切换模型失败', message: msg, icon: '<i class="ri-error-warning-fill"></i>' });
        }
        return;
      }
      const data = await r.json();
      closeMenu();
      rememberSession(alias);
      lab.textContent = alias;
      const tip = document.createElement('div');
      tip.className = 'model-switch-tip';
      tip.textContent = '模型已切到 ' + alias + ' · ' + (data.note || '下一轮生效');
      document.body.appendChild(tip);
      setTimeout(function () { tip.remove(); }, 2800);
      setTimeout(load, 600);
    } catch (e) {
      if (onError) await onError('网络出错', e.message);
      else if (typeof opusAlert === 'function') {
        await opusAlert({ title: '网络出错', message: e.message, icon: '<i class="ri-error-warning-fill"></i>' });
      }
    }
  }

  function toggle() {
    if (!open && !options.length) load();
    open = !open;
    menu.classList.toggle('open', open);
  }

  if (list && !list.dataset.msBound) {
    list.dataset.msBound = '1';
    list.addEventListener('click', function (e) {
      const hit = e.target.closest('[data-alias]');
      if (hit) switchTo(hit.dataset.alias);
    });
  }
  if (!document.documentElement.dataset.msOutside) {
    document.documentElement.dataset.msOutside = '1';
    document.addEventListener('click', function (e) {
      if (!open || e.target.closest('#modelSwitch')) return;
      closeMenu();
    });
  }

  window.loadCurrentModel = load;
  window.switchModel = switchTo;
  window.toggleModelMenu = toggle;
  window.ModelSwitch = {
    load: load,
    switchTo: switchTo,
    toggle: toggle,
    options: function () { return options.slice(); },
    behavior: modelBehaviorPayload,
  };
  initModelBehavior();
}
window.initModelSwitch = initModelSwitch;
window.toggleModelMenu = window.toggleModelMenu || function () {
  if (!window.ModelSwitch && typeof initModelSwitch === 'function') initModelSwitch();
  if (window.ModelSwitch && typeof window.ModelSwitch.toggle === 'function') window.ModelSwitch.toggle();
};
