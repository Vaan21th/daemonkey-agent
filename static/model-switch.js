/* static/model-switch.js · 顶栏切模型 (工作台 + 陪伴共用)
   从 chat.js loadCurrentModel / switchModel 抽出。
   挂钩: token / sessionId / rememberSession / onError */

function modelBehaviorPayload() {
  const out = {};
  try {
    const think = localStorage.getItem('opus_mb_thinking') || 'auto';
    const effort = localStorage.getItem('opus_mb_effort') || '';
    const mt = localStorage.getItem('opus_mb_max_tokens') || '';
    if (think && think !== 'auto') out.thinking = think;
    if (effort) out.reasoning_effort = effort;
    const n = parseInt(mt, 10);
    if (n > 0) out.max_tokens = n;
  } catch (_) {}
  return out;
}
window.modelBehaviorPayload = modelBehaviorPayload;

function initModelBehavior() {
  const $think = document.getElementById('mbThinking');
  const $effort = document.getElementById('mbEffort');
  const $mt = document.getElementById('mbMaxTokens');
  if (!$think && !$effort && !$mt) return;
  if (document.documentElement.dataset.mbBound) return;
  document.documentElement.dataset.mbBound = '1';
  try {
    if ($think) $think.value = localStorage.getItem('opus_mb_thinking') || 'auto';
    if ($effort) $effort.value = localStorage.getItem('opus_mb_effort') || '';
    if ($mt) $mt.value = localStorage.getItem('opus_mb_max_tokens') || '';
  } catch (_) {}
  $think && $think.addEventListener('change', () => localStorage.setItem('opus_mb_thinking', $think.value));
  $effort && $effort.addEventListener('change', () => localStorage.setItem('opus_mb_effort', $effort.value));
  $mt && $mt.addEventListener('change', () => {
    const n = parseInt($mt.value, 10);
    if (n > 0) localStorage.setItem('opus_mb_max_tokens', String(n));
    else { localStorage.removeItem('opus_mb_max_tokens'); $mt.value = ''; }
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

  async function load() {
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
      lab.textContent = display;
      box.dataset.family = current.family || '';
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
