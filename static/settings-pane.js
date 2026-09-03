/* static/settings-pane.js · 工作台设置页 (LLM/多模态/Embedding/访问/微信/通知/本地数据)
   从 chat.js 抽出 · 工作台中栏 + 陪伴家具弹窗共用同一份。
   依赖: token / sessionId / autoConfirm / STORAGE / $detailPane / escHtml / jsStr
         opusConfirm / opusPrompt / opusAlert / backToChat
   房间里 $detailPane === #dashView · backToChat === closeModal */

// 卷三十七 · 中栏 settings view (BRO 截图反馈 · 弹窗装不下 · 改 tabs)
let _settingsTab = 'llm';  // 'llm' | 'access' | 'data'
function openSettingsView() {
  currentView = 'settings';
  // 清左 nav 高亮 · settings 不属于任何 dashboard 维度
  document.querySelectorAll('.nav-item.active').forEach(b => b.classList.remove('active'));
  // 给底部 ⚙ 按钮加个高亮 · 让 BRO 知道当前在设置里
  document.querySelectorAll('.nav-settings-btn').forEach(b => b.classList.add('active'));
  renderSettingsView();
}

function renderSettingsView() {
  const tabs = [
    { id: 'llm', label: '<i class="ri-brain-fill"></i> LLM 模型', hint: '平台、模型和密钥，可存多套配置' },
    { id: 'vision', label: '<i class="ri-cpu-fill"></i> 多模态', hint: '看图 + 听 + 说 + 画 · 默认生图/语音合成也在这里选择' },
    { id: 'embedding', label: '<i class="ri-search-eye-line"></i> Embedding & 搜索', hint: '记忆语义检索 + 可选外网搜索 KEY' },
    { id: 'access', label: '<i class="ri-key-fill"></i> 访问 & 会话', hint: 'API Token / Session / Auto-confirm' },
    { id: 'wechat', label: '<i class="ri-wechat-fill"></i> 微信 & 飞书', hint: '扫码连微信 · 配飞书机器人 · 主动找你的频率 (猫系↔犬系)' },
    { id: 'notify', label: '<i class="ri-notification-3-fill"></i> 通知', hint: '做完或等你点确认时，怎么提醒你 · 音效 / Windows 通知 / 标签闪烁' },
    { id: 'data', label: '<i class="ri-save-fill"></i> 本地数据', hint: '别名 / 缓存 / 重置' },
  ];
  $detailPane.innerHTML = `
    <div class="settings-pane">
      <div class="settings-head">
        <h2>⚙ 设置</h2>
        <span class="meta">改完立刻生效，不用重启</span>
        <button onclick="backToChat()" title="返回对话">✕ 关闭</button>
      </div>
      <div class="settings-tabs">
        ${tabs.map(t => `
          <button class="settings-tab ${_settingsTab === t.id ? 'active' : ''}"
                  onclick="switchSettingsTab('${t.id}')"
                  title="${escHtml(t.hint)}">${t.label}</button>
        `).join('')}
      </div>
      <div class="settings-body" id="settingsBody"></div>
    </div>
  `;
  renderSettingsBody();
}

function switchSettingsTab(tabId) {
  _settingsTab = tabId;
  document.querySelectorAll('.settings-tab').forEach(b => {
    b.classList.toggle('active', b.textContent.includes(
      { llm: 'LLM 模型', vision: '多模态', embedding: 'Embedding', access: '访问', wechat: '微信 & 飞书', notify: '通知', data: '本地数据' }[tabId]
    ));
  });
  renderSettingsBody();
}

function renderSettingsBody() {
  if (_settingsTab === 'llm') renderSettingsLLM();
  else if (_settingsTab === 'vision') renderSettingsVision();
  else if (_settingsTab === 'embedding') renderSettingsEmbedding();
  else if (_settingsTab === 'access') renderSettingsAccess();
  else if (_settingsTab === 'wechat') renderSettingsWechat();
  else if (_settingsTab === 'notify') renderSettingsNotify();
  else if (_settingsTab === 'data') renderSettingsData();
}

// ─── 卷三十六 · LLM 配置面板 ───
let _llmPresets = [];
let _llmActive = null;

async function loadLlmConfig() {
  if (!token) {
    document.getElementById('llmStatus').textContent = '⚠ 请先填 API Token';
    return;
  }
  try {
    const resp = await fetch('/providers', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const data = await resp.json();
    _llmPresets = data.presets || [];
    _llmActive = data.active || null;
    renderLlmPresetSelect();
    renderLlmActiveLabel();
  } catch (e) {
    document.getElementById('llmStatus').textContent = '加载失败: ' + e.message;
    document.getElementById('llmStatus').className = 'field-hint fail';
  }
}

function renderLlmActiveLabel() {
  const $cur = document.getElementById('llmCurrentLabel');
  const $det = document.getElementById('llmCurrentDetail');
  if (!_llmActive) { $cur.textContent = '?'; $det.textContent = '—'; return; }
  const preset = _llmPresets.find(p => p.id === _llmActive.preset_id);
  $cur.textContent = preset ? preset.name : _llmActive.preset_id;
  $det.textContent = `模型 ${_llmActive.model} · base ${_llmActive.base_url || '(SDK 默认)'} · key ${_llmActive.api_key_masked || '(未设)'}`;
}

function renderLlmPresetSelect() {
  const $sel = document.getElementById('llmPreset');
  $sel.innerHTML = '';
  _llmPresets.forEach(p => {
    const opt = document.createElement('option');
    opt.value = p.id;
    opt.textContent = p.name;
    $sel.appendChild(opt);
  });
  if (_llmActive && _llmActive.preset_id) {
    $sel.value = _llmActive.preset_id;
  }
  onLlmPresetChange();
}

function onLlmPresetChange() {
  const $sel = document.getElementById('llmPreset');
  const preset = _llmPresets.find(p => p.id === $sel.value);
  if (!preset) return;
  document.getElementById('llmPresetNote').textContent = preset.note || '—';
  document.getElementById('llmBaseUrl').value = preset.base_url || '';
  document.getElementById('llmApiKey').placeholder = preset.key_hint
    ? `${preset.key_hint} (留空 = 沿用当前 key)`
    : '(留空 = 沿用当前 key)';
  const link = document.getElementById('llmSignupLink');
  if (preset.signup_url) {
    link.href = preset.signup_url;
    link.textContent = preset.signup_url;
    link.style.display = '';
  } else {
    link.style.display = 'none';
  }
  // 模型下拉
  const $mSel = document.getElementById('llmModel');
  $mSel.innerHTML = '';
  (preset.recommended_models || []).forEach(m => {
    const opt = document.createElement('option');
    opt.value = m.id;
    opt.textContent = m.label;
    opt.title = m.note || '';
    $mSel.appendChild(opt);
  });
  // 自定义模型选项
  const customOpt = document.createElement('option');
  customOpt.value = '__custom__';
  customOpt.textContent = '(自定义 model id)';
  $mSel.appendChild(customOpt);
  // 如果是当前活动 preset · 选回当前 model
  if (_llmActive && _llmActive.preset_id === preset.id) {
    const has = (preset.recommended_models || []).some(m => m.id === _llmActive.model);
    $mSel.value = has ? _llmActive.model : '__custom__';
  }
  onLlmModelChange();
}

function onLlmModelChange() {
  const $sel = document.getElementById('llmPreset');
  const $mSel = document.getElementById('llmModel');
  const preset = _llmPresets.find(p => p.id === $sel.value);
  if (!preset) return;
  const m = (preset.recommended_models || []).find(x => x.id === $mSel.value);
  document.getElementById('llmModelNote').textContent = m ? (m.note || '—') : '自定义 model id · 自己填';
  if ($mSel.value === '__custom__') {
    $mSel.insertAdjacentHTML('afterend', '');
    const input = document.getElementById('llmCustomModelInput');
    if (!input) {
      const div = document.createElement('input');
      div.type = 'text';
      div.id = 'llmCustomModelInput';
      div.placeholder = '自定义 model id · 比如 gpt-4o';
      div.style.marginTop = '6px';
      $mSel.parentNode.insertBefore(div, $mSel.nextSibling);
    }
  } else {
    const input = document.getElementById('llmCustomModelInput');
    if (input) input.remove();
  }
}

function _readLlmFormConfig() {
  const $sel = document.getElementById('llmPreset');
  const preset = _llmPresets.find(p => p.id === $sel.value);
  if (!preset) return null;
  let model = document.getElementById('llmModel').value;
  if (model === '__custom__') {
    model = (document.getElementById('llmCustomModelInput')?.value || '').trim();
  }
  let apiKey = document.getElementById('llmApiKey').value.trim();
  if (!apiKey && _llmActive && _llmActive.preset_id === preset.id) {
    // 没填 = 沿用当前 (后端从 .env 读)
    apiKey = '__keep_current__';
  }
  return {
    provider_kind: preset.provider_kind,
    base_url: document.getElementById('llmBaseUrl').value.trim(),
    model,
    api_key: apiKey,
  };
}

async function testLlmConfig() {
  const cfg = _readLlmFormConfig();
  if (!cfg) return;
  const $status = document.getElementById('llmStatus');
  if (!cfg.model) { $status.textContent = '⚠ 没填模型名'; $status.className = 'field-hint fail'; return; }
  if (cfg.api_key === '__keep_current__') {
    $status.textContent = '⚠ 测试必须填 API Key (不能沿用 .env 里的 · 那是后端的事)';
    $status.className = 'field-hint fail';
    return;
  }
  $status.textContent = '测试中…';
  $status.className = 'field-hint';
  try {
    const resp = await fetch('/providers/test', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify(cfg),
    });
    const data = await resp.json();
    if (data.ok) {
      $status.innerHTML = `<i class="ri-check-fill"></i> 通了 · ${escHtml(data.model)} 回复: ${escHtml(data.reply_preview || '(空 · 但调用成功)')}`;
      $status.className = 'field-hint ok';
    } else {
      $status.innerHTML = `<i class="ri-close-fill"></i> ${escHtml(data.error || '?')} · ${escHtml(data.hint || '')}`;
      $status.className = 'field-hint fail';
    }
  } catch (e) {
    $status.innerHTML = '<i class="ri-close-fill"></i> 测试请求失败: ' + escHtml(e.message);
    $status.className = 'field-hint fail';
  }
}

async function switchLlmConfig() {
  const cfg = _readLlmFormConfig();
  if (!cfg) return;
  const $status = document.getElementById('llmStatus');
  if (!cfg.model) { $status.textContent = '⚠ 没填模型名'; $status.className = 'field-hint fail'; return; }
  // 没填 key · 用户想沿用 · 让用户确认
  if (cfg.api_key === '__keep_current__') {
    const ok = await opusConfirm({
      title: '不填 API Key · 沿用当前',
      message: '你没填新的 API Key · 我会沿用当前 .env 里的 key 走 ' + cfg.provider_kind + ' / ' + cfg.model + '\n继续?',
      okText: '继续切',
      cancelText: '回去填 key',
    });
    if (!ok) return;
    // 后端要求 api_key 必填 · 这里如果当前 provider 还跟新 cfg 一致 · 后端会重读 env
    // 简化: 让用户填一次新 key (即便复用旧的)
    const k = await opusPrompt({
      title: '粘一下当前 API Key',
      message: '后端写 .env 需要明文 · 不会发到 LLM',
      placeholder: 'sk-xxx',
    });
    if (!k) return;
    cfg.api_key = k.trim();
  }
  $status.textContent = '切换中…';
  $status.className = 'field-hint';
  try {
    const resp = await fetch('/providers/switch', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify(cfg),
    });
    const data = await resp.json();
    if (resp.ok && data.ok) {
      $status.innerHTML = `<i class="ri-check-fill"></i> 已切到 ${data.provider_kind} / ${data.model}`;
      $status.className = 'field-hint ok';
      // 刷新当前显示
      loadLlmConfig();
      addSys(`已换成这个模型 · ${data.provider_kind} / ${data.model} · 当前对话还在`);
    } else {
      $status.innerHTML = '<i class="ri-close-fill"></i> ' + (data.detail || data.error || 'failed');
      $status.className = 'field-hint fail';
    }
  } catch (e) {
    $status.innerHTML = '<i class="ri-close-fill"></i> 切换失败: ' + e.message;
    $status.className = 'field-hint fail';
  }
}
function saveSettings() {
  token = $tokenIn.value.trim();
  sessionId = $sessionIn.value.trim();
  autoConfirm = $autoIn.value;
  localStorage.setItem(STORAGE.token, token);
  localStorage.setItem(STORAGE.session, sessionId);
  localStorage.setItem(STORAGE.autoConfirm, autoConfirm);
  closeSettings();
  addSys('已保存。' + (token ? '可以聊了。' : '⚠ token 还是空的'));
}
// ─── 卷三十七 · settings tabs body 渲染 ───

let _providerConfigs = [];     // 当前 configs (掩码后)
let _providerConfigsActiveId = null;
let _providerPresets = [];      // 预设 (来自 GET /providers)

async function renderSettingsLLM() {
  const body = document.getElementById('settingsBody');
  body.innerHTML = `<div class="dash-empty">加载中…</div>`;
  // 同时拉 configs + presets
  try {
    const [confResp, presetResp] = await Promise.all([
      fetch('/provider-configs', { headers: { 'Authorization': 'Bearer ' + token } }),
      fetch('/providers', { headers: { 'Authorization': 'Bearer ' + token } }),
    ]);
    if (!confResp.ok) throw new Error('configs ' + confResp.status);
    if (!presetResp.ok) throw new Error('presets ' + presetResp.status);
    const confData = await confResp.json();
    const presetData = await presetResp.json();
    _providerConfigs = confData.configs || [];
    _providerConfigsActiveId = confData.active_id;
    _providerPresets = presetData.presets || [];
  } catch (e) {
    body.innerHTML = `<div class="dash-empty">加载失败: ${escHtml(e.message)}</div>`;
    return;
  }

  const activeCount = _providerConfigs.length;
  const pinnedCount = _providerConfigs.filter(c => c.pinned).length;

  body.innerHTML = `
    <div class="llm-section">
      <div class="llm-section-head">
        <h3>已保存的 LLM 配置 · ${activeCount} 条 · ${pinnedCount} 条已勾选显示</h3>
        <span class="llm-hint">打勾的会出现在右上角。没打勾的只留在这页。常用模型也可以直接跟我说「加几个常用模型」。</span>
        <button class="btn-primary" onclick="openLlmConfigAddForm()">+ 新增配置</button>
      </div>
      <div class="llm-config-list" id="llmConfigList">
        ${_providerConfigs.length === 0
          ? '<div class="dash-empty">还没有配置 · 点 "+ 新增配置" 加一个</div>'
          : _providerConfigs.map(renderLlmConfigCard).join('')}
      </div>
    </div>

    <div id="llmEditPanel" class="llm-edit-panel" hidden></div>
  `;
}

function renderLlmConfigCard(c) {
  const isActive = c.id === _providerConfigsActiveId;
  const presetIcon = ({
    'deepseek-official': '<i class="ri-brain-line"></i>',
    'aihubmix': '<i class="ri-apps-2-line"></i>',
    'anthropic': '<i class="ri-sparkling-2-line"></i>',
    'openrouter': '<i class="ri-route-line"></i>',
    'dashscope': '<i class="ri-cloud-line"></i>',
    'custom': '<i class="ri-settings-3-line"></i>',
  })[c.preset_id] || '<i class="ri-cpu-line"></i>';
  return `
    <div class="llm-config-card${isActive ? ' active' : ''}${c.director ? ' director-on' : ''}" data-cfg-id="${escHtml(c.id)}">
      <div class="lc-row1">
        <span class="lc-icon">${presetIcon}</span>
        <span class="lc-name">${escHtml(c.name || c.model || c.id)}</span>
        ${isActive ? '<span class="lc-active-badge">当前</span>' : ''}
        ${c.director ? '<span class="lc-director-badge" title="顾问 · 出方案、卡住、收尾时会请它把关"><i class="ri-vip-crown-fill"></i> 顾问</span>' : ''}
        <label class="lc-pin" title="勾选 = 右上角切换器显示">
          <input type="checkbox" ${c.pinned ? 'checked' : ''}
                 onchange="togglePinConfig('${escHtml(c.id)}', this.checked)">
          <span>${c.pinned ? '已显示' : '隐藏'}</span>
        </label>
      </div>
      <div class="lc-row2">
        <span class="lc-kind">${escHtml(c.provider_kind || 'openai')}</span>
        <span class="lc-model">${escHtml(c.model || '?')}</span>
        <span class="lc-base">${escHtml(c.base_url || '(SDK 默认)')}</span>
        ${c.max_tokens ? `<span class="lc-mt" title="单次输出上限">↗ ${formatTokenK(c.max_tokens)} max</span>` : ''}
        ${c.context_window ? `<span class="lc-mt" title="上下文长度（用来判断何时压缩）">${formatTokenK(c.context_window)}</span>` : ''}
      </div>
      <div class="lc-row3">
        <span class="lc-key">${escHtml(c.api_key || '(未设)')}</span>
        <div class="lc-actions">
          ${isActive ? '' : `<button onclick="activateConfig('${jsStr(c.id)}')" title="切换 Daemonkey 用这个跑">激活</button>`}
          <button onclick="testConfig('${jsStr(c.id)}')" title="ping 一下试通不通">测试</button>
          <button class="lc-director-btn${c.director ? ' on' : ''}" onclick="toggleDirectorConfig('${jsStr(c.id)}', ${c.director ? 'false' : 'true'})" title="${c.director ? '取消这个配置的顾问身份' : '设为顾问。出方案、卡住、收尾时会请来看一眼。只能有一个。'}"><i class="ri-vip-crown-${c.director ? 'fill' : 'line'}"></i> ${c.director ? '取消顾问' : '设为顾问'}</button><i class="ri-question-line lc-director-help" onclick="showDirectorHelp()" title="顾问模型是干啥的？点我"></i>
          <button onclick="openLlmConfigEditForm('${jsStr(c.id)}')" title="改名称、密钥、模型">编辑</button>
          <button class="btn-danger-mini" onclick="deleteConfig('${jsStr(c.id)}')" title="删除">删除</button>
        </div>
      </div>
      <div class="lc-test-result" id="lcTestResult_${escHtml(c.id)}"></div>
    </div>
  `;
}

// 卷三十八 · 一键导入过去用过的 AiHubMix 模型 · BRO 反馈"以后还会用·默认放进来"
// 弹一个对话框让 BRO 填一次 AiHub key · 然后批量加 4-5 条 config (pinned=false 默认)
async function quickImportAihubMix() {
  // 让 BRO 输入 AiHub key (一次 · 公用)
  const key = await opusPrompt({
    title: '一键导入 AiHubMix 常用模型',
    message: '会自动加入: Sonnet 4.6 / Opus 4.7 / Kimi K2.6 / GLM 5.1 / GPT-5.5\n这些都是 BRO 过去用过的 · 加进来默认不勾右上角 · 编辑里可以单独激活。\n\n填一次 AiHub key · 这些 configs 共用 (你也可以加完单独改 key):',
    placeholder: 'sk-xxx · AiHubMix 平台 key · 留空 = 只加占位不设 key',
    okText: '一键加',
    cancelText: '取消',
  });
  if (key === null) return;  // 取消
  const apiKey = (key || '').trim();
  const presets = [
    { name: 'Sonnet 4.6 · AiHubMix', model: 'claude-sonnet-4-6', note: '性价比·支持 cache' },
    { name: 'Opus 4.7 · AiHubMix', model: 'claude-opus-4-7', note: '深聊最强·5x 贵·支持 cache' },
    { name: 'Kimi K2.6 · AiHubMix', model: 'kimi-k2.6', note: '262K·Agent/工具能力强' },
    { name: 'GLM 5.1 · AiHubMix', model: 'glm-5.1', note: '200K·智谱旗舰·写代码强' },
    { name: 'GPT-5.5 · AiHubMix', model: 'gpt-5.5', note: 'GPT 系最新' },
  ];
  let okCount = 0, failMsg = '';
  for (const p of presets) {
    try {
      const r = await fetch('/provider-configs', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: p.name,
          provider_kind: 'openai',
          base_url: 'https://aihubmix.com/v1',
          model: p.model,
          api_key: apiKey || '___placeholder___',  // 后端要求 key 非空 · 占位让 BRO 之后改
          preset_id: 'aihubmix',
          pinned: false,
          set_active: false,
        }),
      });
      if (r.ok) okCount++;
      else { failMsg = await r.text(); break; }
    } catch (e) { failMsg = e.message; break; }
  }
  if (failMsg) {
    await opusAlert({ title: '部分失败', message: `加成功 ${okCount}/${presets.length}\n失败原因: ${failMsg.slice(0, 200)}`, icon: '<i class="ri-error-warning-fill"></i>' });
  } else if (apiKey) {
    addSys(`<i class="ri-check-fill"></i> 已加 ${okCount} 条 AiHubMix · 想用就去右上角 ● 勾选`);
  } else {
    addSys(`<i class="ri-check-fill"></i> 已加 ${okCount} 条 AiHubMix 占位 (key 还没填) · 编辑里填 key 才能用`);
  }
  await renderSettingsLLM();
  if (typeof loadCurrentModel === 'function') loadCurrentModel();
}

function openLlmConfigAddForm() {
  _showLlmEditForm({
    title: '+ 新增 LLM 配置',
    submit: '保存',
    config: {
      id: '',
      name: '',
      provider_kind: 'openai',
      base_url: '',
      model: '',
      api_key: '',
      preset_id: 'deepseek-official',
      pinned: true,
    },
    onSubmit: async (form) => {
      const body = {
        name: form.name,
        provider_kind: form.provider_kind,
        base_url: form.base_url,
        model: form.model,
        api_key: form.api_key,
        preset_id: form.preset_id,
        pinned: form.pinned,
        set_active: form.set_active,
        max_tokens: form.max_tokens,
        context_window: form.context_window,
        vision: form.vision,
        director: form.director,
        pricing: form.pricing,  // wish-bec4f3b9
      };
      const r = await fetch('/provider-configs', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const t = await r.text();
        await opusAlert({ title: '保存失败', message: t.slice(0, 400), icon: '<i class="ri-error-warning-fill"></i>' });
        return;
      }
      hideLlmEditForm();
      await renderSettingsLLM();
      if (typeof loadCurrentModel === 'function') loadCurrentModel();
    },
  });
}

function openLlmConfigEditForm(cfgId) {
  const cfg = _providerConfigs.find(c => c.id === cfgId);
  if (!cfg) return;
  _showLlmEditForm({
    title: '编辑配置 · ' + (cfg.name || cfg.id),
    submit: '保存修改',
    config: { ...cfg },
    isEdit: true,
    onSubmit: async (form) => {
      const patch = {
        name: form.name,
        base_url: form.base_url,
        model: form.model,
        preset_id: form.preset_id,
        pinned: form.pinned,
        max_tokens: form.max_tokens,
        context_window: form.context_window,
        vision: form.vision,
        director: form.director,
        pricing: form.pricing,  // wish-bec4f3b9
      };
      if (form.api_key && form.api_key.trim()) patch.api_key = form.api_key;
      const r = await fetch('/provider-configs/' + encodeURIComponent(cfgId), {
        method: 'PATCH',
        headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      });
      if (!r.ok) {
        const t = await r.text();
        await opusAlert({ title: '保存失败', message: t.slice(0, 400), icon: '<i class="ri-error-warning-fill"></i>' });
        return;
      }
      hideLlmEditForm();
      await renderSettingsLLM();
      if (typeof loadCurrentModel === 'function') loadCurrentModel();
    },
  });
}

function _showLlmEditForm({ title, submit, config, onSubmit, isEdit }) {
  const panel = document.getElementById('llmEditPanel');
  panel.hidden = false;
  panel.innerHTML = `
    <div class="llm-edit-card">
      <h3>${escHtml(title)}</h3>
      <div class="field">
        <label>名字 (给自己看 · 任意起)</label>
        <input id="llmEditName" type="text" value="${escHtml(config.name || '')}" placeholder="比如 'DeepSeek V4 Pro · 官方'">
      </div>
      <div class="field">
        <label>Provider 预设</label>
        <select id="llmEditPreset" onchange="onLlmEditPresetChange()">
          ${_providerPresets.map(p => `
            <option value="${escHtml(p.id)}" ${p.id === config.preset_id ? 'selected' : ''}>${escHtml(p.name)}</option>
          `).join('')}
        </select>
        <div class="field-hint" id="llmEditPresetNote"></div>
      </div>
      <div class="field">
        <label>Provider Kind</label>
        <select id="llmEditKind">
          <option value="openai" ${config.provider_kind === 'openai' ? 'selected' : ''}>openai (OpenAI 兼容协议)</option>
          <option value="anthropic" ${config.provider_kind === 'anthropic' ? 'selected' : ''}>anthropic (Anthropic 原生)</option>
        </select>
      </div>
      <div class="field">
        <label>Base URL (anthropic 走 SDK 默认可以空)</label>
        <input id="llmEditBaseUrl" type="text" value="${escHtml(config.base_url || '')}" placeholder="https://api.deepseek.com/v1">
      </div>
      <div class="field">
        <label>Model · 选预设里推荐的 / 也可自定义</label>
        <select id="llmEditModelSelect" onchange="onLlmEditModelSelectChange()"></select>
        <input id="llmEditModel" type="text" value="${escHtml(config.model || '')}" placeholder="model id" style="margin-top:6px">
      </div>
      <div class="field">
        <label>API Key ${isEdit ? '(留空 = 不改)' : ''}</label>
        <input id="llmEditApiKey" type="password" value="" placeholder="${isEdit ? '不填就用原 key' : 'sk-xxx'}">
        <div class="field-hint">密钥存在本机配置里，不会被提交到网上</div>
      </div>
      <div class="field">
        <label>输出长度上限 (max_tokens · 单次 LLM 调用的最长输出)</label>
        <input id="llmEditMaxTokens" type="number" min="512" max="384000" step="512"
               value="${escHtml(String(config.max_tokens || 8192))}"
               placeholder="按模型推荐">
        <div class="field-hint" id="llmEditMaxTokensHint">
          数字越大，一次能写越长。太小会写到一半停；太大有的模型会拒。
        </div>
      </div>
      <div class="field">
        <label>上下文长度 (可选 · 用来判断何时压缩)</label>
        <input id="llmEditCtxWindow" type="number" min="0" max="10000000" step="1024"
               value="${escHtml(config.context_window ? String(config.context_window) : '')}"
               placeholder="不填就用常见值">
        <div class="field-hint">官方常用模型不用填。自己加的填了更准，忘了也能用。</div>
      </div>
      <div class="field">
        <label><i class="ri-price-tag-3-fill"></i> 价格表 (每 1M tokens · 用于成本估算)</label>
        <div class="pricing-row">
          <select id="llmEditCurrency">
            <option value="USD">USD $</option>
            <option value="CNY">CNY ¥</option>
          </select>
          <input type="number" step="0.0001" min="0" placeholder="输入价" id="llmEditPriceIn" value="${escHtml(String((config.pricing && config.pricing.input) ?? ''))}">
          <input type="number" step="0.0001" min="0" placeholder="输出价" id="llmEditPriceOut" value="${escHtml(String((config.pricing && config.pricing.output) ?? ''))}">
          <input type="number" step="0.0001" min="0" placeholder="缓存命中价(可空)" id="llmEditPriceCache" value="${escHtml(String((config.pricing && config.pricing.cache_read) ?? ''))}">
          <button type="button" class="btn-ghost" id="llmEditLookup"><i class="ri-search-eye-line"></i> 自动查官方价</button>
        </div>
        <div class="field-hint" id="llmEditPricingHint">未配置 · 点「自动查官方价」由 Daemonkey 搜官网填入 · 你确认后才保存</div>
      </div>
      <div class="field">
        <label>
          <input id="llmEditPinned" type="checkbox" ${config.pinned ? 'checked' : ''}>
          勾选 = 显示在右上角切换器
        </label>
      </div>
      <div class="field">
        <label><i class="ri-eye-fill"></i> 多模态视觉</label>
        <div class="vision-radio-group">
          <label class="vision-radio">
            <input type="radio" name="llmEditVision" id="llmEditVisionAuto" value="auto" ${config.vision == null ? 'checked' : ''}>
            <i class="ri-settings-3-fill"></i> 自动检测
          </label>
          <label class="vision-radio">
            <input type="radio" name="llmEditVision" id="llmEditVisionYes" value="yes" ${config.vision === true ? 'checked' : ''}>
            <i class="ri-checkbox-circle-fill"></i> 多模态
          </label>
          <label class="vision-radio">
            <input type="radio" name="llmEditVision" id="llmEditVisionNo" value="no" ${config.vision === false ? 'checked' : ''}>
            <i class="ri-close-circle-fill"></i> 纯文本
          </label>
        </div>
        <div class="field-hint">一般会自动判断。不对再手改。</div>
      </div>
      <div class="field">
        <label>
          <input type="checkbox" id="llmEditDirector" ${config.director ? 'checked' : ''}>
          <i class="ri-vip-crown-fill"></i> 设为顾问模型
          <i class="ri-question-line director-help-icon" id="directorHelpIcon" title="顾问模型是干啥的？点我"></i>
        </label>
        <div class="field-hint" id="directorHelpText" hidden>
          日常用便宜模型干活。出方案、卡住、收尾时，另请一个更强的模型看一眼。只能设一个。不设就还是当前这个模型自己看。常见搭配：便宜的干活，贵的当顾问，能省不少。
        </div>
      </div>
      ${isEdit ? '' : `
      <div class="field">
        <label>
          <input id="llmEditSetActive" type="checkbox">
          保存后立即激活
        </label>
      </div>`}
      <div class="actions">
        <button class="btn-ghost" onclick="hideLlmEditForm()">取消</button>
        <button class="btn-primary" id="llmEditSubmit">${escHtml(submit)}</button>
      </div>
      <div id="llmEditStatus" class="field-hint" style="margin-top:6px"></div>
    </div>
  `;
  // 编辑模式：base_url 已有值 → 标记 touched · 防止 onLlmEditPresetChange 覆盖
  if (isEdit && config.base_url) {
    document.getElementById('llmEditBaseUrl').dataset.touched = '1';
  }
  // wish-bec4f3b9 · 已有 pricing 回填币种
  if (config.pricing && config.pricing.currency) {
    const _cur = document.getElementById('llmEditCurrency');
    if (_cur) _cur.value = config.pricing.currency;
  }
  onLlmEditPresetChange();  // 触发一次 · 填模型下拉
  const _dhIcon = document.getElementById('directorHelpIcon');
  if (_dhIcon) _dhIcon.addEventListener('click', () => {
    const h = document.getElementById('directorHelpText');
    if (h) h.hidden = !h.hidden;
  });
  document.getElementById('llmEditSubmit').addEventListener('click', async () => {
    const form = _readLlmEditForm();
    if (!form.name || !form.model) {
      document.getElementById('llmEditStatus').textContent = '⚠ 名称和模型必填';
      return;
    }
    if (!isEdit && !form.api_key) {
      document.getElementById('llmEditStatus').textContent = '⚠ 新增时 api_key 必填';
      return;
    }
    document.getElementById('llmEditStatus').textContent = '保存中…';
    try {
      await onSubmit(form);
    } catch (e) {
      document.getElementById('llmEditStatus').innerHTML = '<i class="ri-close-fill"></i> ' + e.message;
    }
  });
  // wish-bec4f3b9 · 自动查官方价 (回填≠保存 · 仍走保存按钮)
  const _lookupBtn = document.getElementById('llmEditLookup');
  if (_lookupBtn) _lookupBtn.addEventListener('click', async () => {
    const _hint = document.getElementById('llmEditPricingHint');
    _lookupBtn.disabled = true;
    _lookupBtn.innerHTML = '<i class="ri-loader-4-line spin"></i> 查价中…';
    try {
      const _resp = await fetch('/llm-pricing/lookup', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          preset_id: document.getElementById('llmEditPreset')?.value || '',
          model: document.getElementById('llmEditModel')?.value || '',
          base_url: document.getElementById('llmEditBaseUrl')?.value || '',
        }),
      });
      if (!_resp.ok) {
        let hint = '查价失败 · 请手动填';
        try {
          const _j = await _resp.json();
          if (_j && (_j.hint || _j.error)) hint = (_j.hint || _j.error) + ' · 请手动填';
          if (_j && _j.source_url) window._llmPricingSource = _j.source_url;
        } catch (_e) { /* ignore */ }
        _hint.innerHTML = `<span style="color:#FC8181">${escHtml(hint)}</span>`;
        return;
      }
      const _j = await _resp.json();
      if (_j && _j.pricing) {
        document.getElementById('llmEditCurrency').value = _j.pricing.currency || 'USD';
        document.getElementById('llmEditPriceIn').value = _j.pricing.input ?? '';
        document.getElementById('llmEditPriceOut').value = _j.pricing.output ?? '';
        document.getElementById('llmEditPriceCache').value = _j.pricing.cache_read ?? '';
        window._llmPricingSource = _j.source_url || '';
        window._llmPricingCheckedAt = _j.checked_at || '';
        _hint.innerHTML = `来源: <a href="${escAttr(_j.source_url || '#')}" target="_blank">官方定价页</a> · 查于 ${escHtml(_j.checked_at || '')} · <b>请核对后保存</b>`;
      } else {
        _hint.innerHTML = '<span style="color:#FC8181">查价失败 · 请手动填</span>';
      }
    } catch (e) {
      _hint.innerHTML = `<span style="color:#FC8181">自动查价失败: ${escHtml(e.message || '')} · 请手动填写价格</span>`;
    } finally {
      _lookupBtn.disabled = false;
      _lookupBtn.innerHTML = '<i class="ri-search-eye-line"></i> 自动查官方价';
    }
  });
  panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function hideLlmEditForm() {
  const panel = document.getElementById('llmEditPanel');
  if (panel) { panel.hidden = true; panel.innerHTML = ''; }
}

function _readLlmEditForm() {
  return {
    name: document.getElementById('llmEditName').value.trim(),
    provider_kind: document.getElementById('llmEditKind').value,
    base_url: document.getElementById('llmEditBaseUrl').value.trim(),
    model: document.getElementById('llmEditModel').value.trim(),
    api_key: document.getElementById('llmEditApiKey').value.trim(),
    preset_id: document.getElementById('llmEditPreset').value,
    pinned: document.getElementById('llmEditPinned').checked,
    set_active: document.getElementById('llmEditSetActive')?.checked || false,
    max_tokens: parseInt(document.getElementById('llmEditMaxTokens').value || '8192', 10),
    context_window: (() => {
      const raw = (document.getElementById('llmEditCtxWindow')?.value || '').trim();
      if (!raw) return 0;
      const n = parseInt(raw, 10);
      return n > 0 ? n : 0;
    })(),
    vision: (() => {
      const a = document.getElementById('llmEditVisionAuto');
      const y = document.getElementById('llmEditVisionYes');
      const n = document.getElementById('llmEditVisionNo');
      if (a && a.checked) return null;
      if (y && y.checked) return true;
      if (n && n.checked) return false;
      return null;
    })(),
    director: !!document.getElementById('llmEditDirector')?.checked,
    pricing: (() => {
      const inp = parseFloat(document.getElementById('llmEditPriceIn')?.value);
      const outp = parseFloat(document.getElementById('llmEditPriceOut')?.value);
      if (isNaN(inp) && isNaN(outp)) return null;   // 未配置
      return {
        currency: document.getElementById('llmEditCurrency')?.value || 'USD',
        input: isNaN(inp) ? null : inp,
        output: isNaN(outp) ? null : outp,
        cache_read: (() => {
          const c = parseFloat(document.getElementById('llmEditPriceCache')?.value);
          return isNaN(c) ? null : c;
        })(),
        source_url: window._llmPricingSource || '',
        checked_at: window._llmPricingCheckedAt || '',
        note: '',
      };
    })(),
  };
}

function onLlmEditPresetChange() {
  const pid = document.getElementById('llmEditPreset').value;
  const preset = _providerPresets.find(p => p.id === pid);
  if (!preset) return;
  document.getElementById('llmEditPresetNote').textContent = preset.note || '';
  // 自动填 base_url / provider_kind 如果是新增时
  const baseInput = document.getElementById('llmEditBaseUrl');
  const kindSelect = document.getElementById('llmEditKind');
  if (!baseInput.value || baseInput.dataset.touched !== '1') {
    baseInput.value = preset.base_url || '';
  }
  if (preset.provider_kind) kindSelect.value = preset.provider_kind;
  // 填模型下拉
  const sel = document.getElementById('llmEditModelSelect');
  sel.innerHTML = '<option value="">— 选推荐模型 / 或在下方手填 —</option>';
  (preset.recommended_models || []).forEach(m => {
    const opt = document.createElement('option');
    opt.value = m.id;
    opt.textContent = m.label;
    opt.title = m.note || '';
    sel.appendChild(opt);
  });
}

function onLlmEditModelSelectChange() {
  const sel = document.getElementById('llmEditModelSelect');
  if (!sel.value) return;
  document.getElementById('llmEditModel').value = sel.value;
  // 卷三十八 · 选了推荐模型 · 自动填 max_tokens 推荐值 + 更新 hint 显示模型 spec
  const pid = document.getElementById('llmEditPreset').value;
  const preset = _providerPresets.find(p => p.id === pid);
  if (!preset) return;
  const m = (preset.recommended_models || []).find(x => x.id === sel.value);
  if (!m) return;
  const mtInput = document.getElementById('llmEditMaxTokens');
  if (m.max_tokens_default) {
    mtInput.value = m.max_tokens_default;
    mtInput.max = m.max_output || 384000;
  }
  if (m.context_window) {
    const cwInput = document.getElementById('llmEditCtxWindow');
    if (cwInput && !cwInput.value) cwInput.value = m.context_window;
  }
  const hint = document.getElementById('llmEditMaxTokensHint');
  if (hint) {
    const ctx = m.context_window ? ` · 上下文上限 ${formatTokenK(m.context_window)}` : '';
    const out = m.max_output ? ` · 输出上限 ${formatTokenK(m.max_output)}` : '';
    hint.innerHTML = `单位: token · 约 token×0.7 个汉字${ctx}${out}<br>推荐 ${m.max_tokens_default || 8192} (按模型 spec 算的安全值)`;
  }
}

// 1234 → "1.2K" · 12345 → "12K" · 1234567 → "1.2M"
function formatTokenK(n) {
  if (!n) return '0';
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1).replace('.0', '') + 'M';
  if (n >= 1000) return Math.round(n / 1000) + 'K';
  return String(n);
}

async function activateConfig(cfgId) {
  const r = await fetch('/provider-configs/' + encodeURIComponent(cfgId) + '/activate', {
    method: 'POST',
    headers: { 'Authorization': 'Bearer ' + token },
  });
  if (!r.ok) {
    const t = await r.text();
    await opusAlert({ title: '激活失败', message: t.slice(0, 400), icon: '<i class="ri-error-warning-fill"></i>' });
    return;
  }
  const data = await r.json();
  addSys('已激活 · ' + (data.model || '?') + ' · session 不丢');
  await renderSettingsLLM();
  if (typeof loadCurrentModel === 'function') loadCurrentModel();
}

async function testConfig(cfgId) {
  const tag = document.getElementById('lcTestResult_' + cfgId);
  if (tag) { tag.textContent = '测试中…'; tag.className = 'lc-test-result loading'; }
  try {
    const r = await fetch('/provider-configs/' + encodeURIComponent(cfgId) + '/test', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token },
    });
    const data = await r.json();
    if (data.ok) {
      tag.innerHTML = `<i class="ri-check-fill"></i> 通了 · 回复: ${escHtml(data.reply_preview || '(空 · 但通)')}`;
      tag.className = 'lc-test-result ok';
    } else {
      tag.innerHTML = `<i class="ri-close-fill"></i> ${escHtml(data.error || '?')} · ${escHtml(data.hint || '')}`;
      tag.className = 'lc-test-result fail';
    }
  } catch (e) {
    tag.innerHTML = '<i class="ri-close-fill"></i> 网络出错: ' + escHtml(e.message);
    tag.className = 'lc-test-result fail';
  }
}

async function togglePinConfig(cfgId, pinned) {
  const r = await fetch('/provider-configs/' + encodeURIComponent(cfgId), {
    method: 'PATCH',
    headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ pinned }),
  });
  if (!r.ok) {
    const t = await r.text();
    await opusAlert({ title: '改 pinned 失败', message: t.slice(0, 400), icon: '<i class="ri-error-warning-fill"></i>' });
    return;
  }
  await renderSettingsLLM();
  if (typeof loadCurrentModel === 'function') loadCurrentModel();
}

async function deleteConfig(cfgId) {
  const cfg = _providerConfigs.find(c => c.id === cfgId);
  const ok = await opusConfirm({
    title: '删除 LLM 配置',
    message: `确定删除 "${cfg?.name || cfgId}"?\nAPI key 也会从本地删除·不可恢复。`,
    okText: '删',
    cancelText: '不删',
    danger: true,
  });
  if (!ok) return;
  const r = await fetch('/provider-configs/' + encodeURIComponent(cfgId), {
    method: 'DELETE',
    headers: { 'Authorization': 'Bearer ' + token },
  });
  if (!r.ok) {
    const t = await r.text();
    await opusAlert({ title: '删除失败', message: t.slice(0, 400), icon: '<i class="ri-error-warning-fill"></i>' });
    return;
  }
  await renderSettingsLLM();
  if (typeof loadCurrentModel === 'function') loadCurrentModel();
}

// wish-6ee0cd18 · 总监模型入口前置 · 卡片上一键设/取消总监（复用 8ffb9d65 的 PATCH director 链路）
async function toggleDirectorConfig(cfgId, val) {
  const cfg = _providerConfigs.find(c => c.id === cfgId);
  if (!cfg) return;
  const label = cfg.name || cfg.model || cfgId;
  const ok = await opusConfirm(val ? {
    title: '设为顾问模型',
    message: `把 "${label}" 设为顾问？\n\n日常用便宜模型干活。出方案、卡住、收尾时，另请一个更强的模型看一眼。只能设一个。设它之后，之前的顾问会自动取消。\n\n常见搭配：便宜的干活，贵的当顾问，能省不少。`,
    okText: '设为顾问',
    cancelText: '再想想',
  } : {
    title: '取消顾问模型',
    message: `取消 "${label}" 的顾问身份？\n取消后，出方案、卡住、收尾时还是当前这个模型自己看。`,
    okText: '取消顾问',
    cancelText: '保留',
  });
  if (!ok) return;
  const r = await fetch('/provider-configs/' + encodeURIComponent(cfgId), {
    method: 'PATCH',
    headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ director: !!val }),
  });
  if (!r.ok) {
    const t = await r.text();
    await opusAlert({ title: '改顾问失败', message: t.slice(0, 400), icon: '<i class="ri-error-warning-fill"></i>' });
    return;
  }
  await renderSettingsLLM();
  if (typeof loadCurrentModel === 'function') loadCurrentModel();
}

function showDirectorHelp() {
  opusAlert({
    title: '<i class="ri-vip-crown-fill"></i> 顾问模型是干啥的？',
    message: '日常用便宜模型干活。出方案、卡住、收尾时，另请一个更强的模型看一眼。只能设一个。不设就还是当前这个模型自己看。\n\n常见搭配：便宜的干活，贵的当顾问，能省不少。',
  });
}

// ─── wish-4a6331b2 · 视觉模型配置 tab ───
async function renderSettingsVision() {
  const body = document.getElementById('settingsBody');
  body.innerHTML = '<div class="dash-empty">加载中…</div>';

  let cfg = { model: '', base_url: '', api_key: '', configured: false };
  try {
    const resp = await fetch('/vision-config', { headers: { 'Authorization': 'Bearer ' + token } });
    if (resp.ok) cfg = await resp.json();
  } catch (_) {}

  const hasCfg = cfg.configured;
  body.innerHTML = `
    <div class="llm-section">
      <div class="llm-section-head">
        <h3><i class="ri-eye-fill"></i> 视觉模型 · ${hasCfg ? '<span style="color:#6ed27a">已配置 ✓</span>' : '<span style="color:var(--sys)">未配置</span>'}</h3>
        <span class="llm-hint">主模型不支持看图时自动调用 · 多模态模型（Claude/GPT/Gemini）不经过这里 · 配一个 OpenAI 兼容的视觉模型即可</span>
      </div>
      <div class="field">
        <label>模型名</label>
        <input id="visModel" type="text" value="${escHtml(cfg.model || '')}" placeholder="gemini-2.0-flash-lite">
        <div class="field-hint">任意 OpenAI 兼容的视觉模型名</div>
      </div>
      <div class="field">
        <label>API 地址</label>
        <input id="visBaseUrl" type="text" value="${escHtml(cfg.base_url || '')}" placeholder="https://api.openai.com/v1">
      </div>
      <div class="field">
        <label>API Key</label>
        <input id="visApiKey" type="password" value="${escHtml(cfg.api_key || '')}" placeholder="${hasCfg ? '不改就留空' : 'sk-xxx'}">
        ${hasCfg ? '<div class="field-hint">已存 key · 不改就留空</div>' : ''}
      </div>
      <div class="actions" style="margin-top:12px">
        <button class="btn-primary" id="visSave"><i class="ri-save-fill"></i> 保存</button>
        <button class="btn-ghost" id="visTest"><i class="ri-flashlight-fill"></i> 测试连接</button>
      </div>
      <div id="visResult" style="margin-top:8px;font-size:13px"></div>
    </div>

    <div id="mediaCaps"></div>

    <!-- wish-241e0014 · 语音识别增强 whisper (可选更新 · 设置页开关驱动安装) -->
    <div class="llm-section" style="margin-top:18px">
      <div class="llm-section-head">
        <h3><i class="ri-mic-fill"></i> 语音识别增强 (whisper) · <span id="sttStatusLabel" style="color:var(--dim)">加载中…</span></h3>
        <span class="llm-hint">微信语音转文字 · 可选功能 · 打开开关才下载依赖+模型 (~500MB) · 不需要就不装 · 装好前语音自动降级存证</span>
      </div>
      <div id="sttBody" style="min-height:60px"><span class="field-hint">加载中…</span></div>
    </div>
  `;

  async function doSave(testOnly) {
    const m = document.getElementById('visModel').value.trim();
    const u = document.getElementById('visBaseUrl').value.trim();
    const k = document.getElementById('visApiKey').value.trim();
    let storedKey = k;
    const resNeed = document.getElementById('visResult');
    if (!m || !u) {
      if (resNeed) resNeed.innerHTML = '<span style="color:var(--red)"><i class="ri-error-warning-fill"></i> 模型名和 API 地址必填</span>';
      return;
    }
    if (storedKey.includes('****')) storedKey = '';
    if (!storedKey && !hasCfg) {
      if (resNeed) resNeed.innerHTML = '<span style="color:var(--red)"><i class="ri-error-warning-fill"></i> 第一次要填完整 API key</span>';
      return;
    }
    const resEl = document.getElementById('visResult');
    if (resEl) resEl.innerHTML = '<span style="color:var(--sys)"><i class="ri-loader-fill"></i> 保存中…</span>';
    try {
      const resp = await fetch('/vision-config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
        body: JSON.stringify({ model: m, base_url: u, api_key: storedKey, test: testOnly }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        if (resEl) resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-error-warning-fill"></i> ${escHtml(data.detail || '保存失败')}</span>`;
        return;
      }
      if (testOnly && data.test) {
        if (data.test.ok) {
          if (resEl) resEl.innerHTML = `<span style="color:#6ed27a"><i class="ri-check-fill"></i> 测试通过 · ${escHtml(data.test.reply)}</span>`;
        } else {
          if (resEl) resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-close-fill"></i> 连接失败: ${escHtml(data.test.error)}</span>`;
        }
      } else {
        if (resEl) resEl.innerHTML = '<span style="color:#6ed27a"><i class="ri-check-fill"></i> 已保存</span>';
        setTimeout(() => renderSettingsVision(), 600);
      }
    } catch (e) {
      if (resEl) resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-close-fill"></i> ${escHtml(e.message)}</span>`;
    }
  }

  document.getElementById('visSave').onclick = () => doSave(false);
  document.getElementById('visTest').onclick = () => doSave(true);

  loadMediaDefaults();
  loadSttConfig();
}

function _mediaUnlocks(items) {
  return (items || []).map(x => `<li>${escHtml(x)}</li>`).join('');
}

function _mediaAppOptions(apps, selected, kind) {
  const guessed = (apps || []).filter(a => a.kind === kind);
  const rest = (apps || []).filter(a => a.kind !== kind);
  const rows = [{ id: '', name: '（还没指定默认应用）' }].concat(guessed, rest);
  if (selected && !rows.some(a => a.id === selected)) {
    rows.splice(1, 0, { id: selected, name: selected + '（工坊里暂时找不到）' });
  }
  return rows.map(a => {
    const mark = a.kind === kind ? (kind === 'tts' ? ' · 适合配音' : ' · 适合生图') : '';
    const sel = a.id === selected ? ' selected' : '';
    return `<option value="${escHtml(a.id)}"${sel}>${escHtml(a.name || a.id || '未选')}${mark}</option>`;
  }).join('');
}

async function pinMediaDefault(kind, appId) {
  const r = await fetch('/media-defaults', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
    body: JSON.stringify({ kind, app_id: appId || '' }),
  });
  if (!r.ok) throw new Error('保存失败');
  return r.json();
}

function _activeChatRoot() {
  if (typeof chatBox === 'function') {
    const box = chatBox();
    if (box) return box;
  }
  if (window.SessionRuntime && typeof SessionRuntime.activeContainer === 'function') {
    const box = SessionRuntime.activeContainer();
    if (box) return box;
  }
  return document.getElementById('messages') || document.getElementById('pane-chat');
}

function _currentTopicHasTalk() {
  const root = _activeChatRoot();
  if (!root) return false;
  return !!root.querySelector('.msg.bro');
}

function _mediaGuideStayHere(prompt) {
  if (typeof injectAndSend === 'function') {
    injectAndSend(prompt);
    return true;
  }
  if (typeof sendCompanionText === 'function') {
    sendCompanionText(prompt);
    return true;
  }
  if (typeof send === 'function') {
    send({ fromQueue: { text: prompt } });
    return true;
  }
  return false;
}

async function _mediaGuideNewTopic(prompt, label) {
  if (typeof switchToSession === 'function' && typeof spawnTask === 'function') {
    await spawnTask(prompt, label);
    return;
  }
  if (typeof startNewTopic === 'function' && typeof send === 'function') {
    startNewTopic();
    send({ fromQueue: { text: prompt } });
    return;
  }
  _mediaGuideStayHere(prompt);
}

async function startMediaGuide(kind) {
  let prompt = '';
  try {
    const r = await fetch('/media-defaults', { headers: { 'Authorization': 'Bearer ' + token } });
    if (r.ok) {
      const d = await r.json();
      prompt = (d.guides && d.guides[kind]) || '';
    }
  } catch (_) {}
  if (!prompt) prompt = kind === 'tts'
    ? '帮我接上配音。先看工坊有没有现成的；没有就建一个应用。带我去官网拿 Key，不要登录、不要编造。Key 写进应用后，告诉我回设置里把它选成默认。'
    : '帮我接上生图。先看工坊有没有现成的；没有就建一个应用。带我去官网拿 Key，不要登录、不要编造。Key 写进应用后，告诉我回设置里把它选成默认。';
  const label = kind === 'tts' ? '接入语音合成' : '接入生图';
  if (typeof backToChat === 'function') try { backToChat(); } catch (_) {}
  if (typeof closeModal === 'function') try { closeModal(); } catch (_) {}
  if (_currentTopicHasTalk()) await _mediaGuideNewTopic(prompt, label);
  else _mediaGuideStayHere(prompt);
}

async function loadMediaDefaults() {
  const host = document.getElementById('mediaCaps');
  if (!host) return;
  let d = { apps: [], image: {}, tts: {} };
  try {
    const r = await fetch('/media-defaults', { headers: { 'Authorization': 'Bearer ' + token } });
    if (r.ok) d = await r.json();
  } catch (_) {}
  const img = d.image || {};
  const tts = d.tts || {};
  const apps = d.apps || [];
  const imgOk = !!img.ready;
  const ttsOk = !!tts.ready;
  host.innerHTML = `
    <div class="llm-section" style="margin-top:18px">
      <div class="llm-section-head">
        <h3><i class="ri-image-fill"></i> 生图 · ${imgOk ? '<span style="color:#6ed27a">已装载 ✓</span>' : '<span style="color:var(--sys)">未接入</span>'}</h3>
        <span class="llm-hint">选一个工坊生图应用当默认。没接好 Key 就不会出图。</span>
      </div>
      <div class="field-hint">接上之后可以用：</div>
      <ul class="field-hint" style="margin:4px 0 10px 1.2em">${_mediaUnlocks(img.unlocks)}</ul>
      <div class="field">
        <label>默认生图应用</label>
        <select id="mediaImageApp" style="max-width:360px">${_mediaAppOptions(apps, img.app_id || '', 'image')}</select>
      </div>
      <div class="actions" style="margin-top:10px">
        <button class="btn-ghost" type="button" id="mediaImageGuide"><i class="ri-compass-3-line"></i> 帮我接入</button>
        <span class="field-hint">当前对话是空的就在这儿接入；正在聊别的会新开一个对话</span>
      </div>
      <div id="mediaImageNote" style="margin-top:8px;font-size:13px"></div>
    </div>
    <div class="llm-section" style="margin-top:18px">
      <div class="llm-section-head">
        <h3><i class="ri-volume-up-fill"></i> 语音合成 · ${ttsOk ? '<span style="color:#6ed27a">已装载 ✓</span>' : '<span style="color:var(--sys)">未接入</span>'}</h3>
        <span class="llm-hint">海螺 MiniMax 或火山语音都可以。没接好她还能打字，只是没声音。想好听：去官网拿 Key，回来选成默认。</span>
      </div>
      <div class="field-hint">接上之后可以用：</div>
      <ul class="field-hint" style="margin:4px 0 10px 1.2em">${_mediaUnlocks(tts.unlocks)}</ul>
      <div class="field">
        <label>默认语音合成应用</label>
        <select id="mediaTtsApp" style="max-width:360px">${_mediaAppOptions(apps, tts.app_id || '', 'tts')}</select>
      </div>
      <div class="actions" style="margin-top:10px">
        <button class="btn-ghost" type="button" id="mediaTtsGuide"><i class="ri-compass-3-line"></i> 帮我接入</button>
        <span class="field-hint">当前对话是空的就在这儿接入；正在聊别的会新开一个对话</span>
      </div>
      <div id="mediaTtsNote" style="margin-top:8px;font-size:13px"></div>
    </div>
  `;
  const bindPin = (selId, kind, noteId) => {
    const sel = document.getElementById(selId);
    if (!sel) return;
    sel.onchange = async () => {
      const note = document.getElementById(noteId);
      try {
        await pinMediaDefault(kind, sel.value);
        await loadMediaDefaults();
        const after = document.getElementById(noteId);
        if (after) after.innerHTML = '<span style="color:#6ed27a"><i class="ri-check-fill"></i> 已设为默认</span>';
      } catch (e) {
        if (note) note.innerHTML = `<span style="color:var(--red)">${escHtml(e.message || '没存上')}</span>`;
      }
    };
  };
  bindPin('mediaImageApp', 'image', 'mediaImageNote');
  bindPin('mediaTtsApp', 'tts', 'mediaTtsNote');
  const ig = document.getElementById('mediaImageGuide');
  if (ig) ig.onclick = () => startMediaGuide('image');
  const tg = document.getElementById('mediaTtsGuide');
  if (tg) tg.onclick = () => startMediaGuide('tts');
}

// ─── wish-241e0014 · 语音识别增强 whisper (可选更新 · 开关驱动安装) ───
async function loadSttConfig() {
  const $status = document.getElementById('sttStatusLabel');
  const $body = document.getElementById('sttBody');
  if (!$status || !$body) return;
  let st = { deps_installed: false, model_name: 'small', model_downloaded: false, ready: false, model_dir: '', expected_size_mb: 460 };
  try {
    const resp = await fetch('/stt/status', { headers: { 'Authorization': 'Bearer ' + token } });
    if (resp.ok) st = await resp.json();
  } catch (_) {}
  const stateLabel = st.ready
    ? '<span style="color:#6ed27a">已就绪 ✓</span>'
    : (st.deps_installed && !st.model_downloaded)
      ? '<span style="color:var(--sys)">依赖已装 · 模型未下载</span>'
      : '<span style="color:var(--red)">未安装</span>';
  $status.innerHTML = stateLabel;
  $body.innerHTML = `
    <div class="field">
      <label style="display:flex;align-items:center;gap:8px">
        <input type="checkbox" id="sttEnable" ${(st.enabled !== false && st.ready) ? 'checked' : ''} style="width:auto">
        启用语音识别增强 (whisper)
      </label>
      <div class="field-hint">开启后：①安装转写依赖 (pilk + faster-whisper) ②下载模型 (~${st.expected_size_mb}MB · 国内镜像) · 装好微信语音自动转文字</div>
    </div>
    <div class="field">
      <label>模型大小</label>
      <select id="sttModelSize" style="max-width:220px">
        <option value="tiny" ${st.model_name === 'tiny' ? 'selected' : ''}>tiny · ~75MB · 最快最省</option>
        <option value="base" ${st.model_name === 'base' ? 'selected' : ''}>base · ~150MB · 均衡</option>
        <option value="small" ${st.model_name === 'small' ? 'selected' : ''}>small · ~460MB · 最准 (默认)</option>
      </select>
      <div class="field-hint">切换大小后需重新下载对应模型</div>
    </div>
    <div class="field">
      <label>随 daemon 启动加载模型</label>
      <div class="field-hint">开启后启动即加载 (~1-2s) · 微信语音首条秒回 · 关掉则首次语音时懒加载 (多等几秒)</div>
      <label style="display:flex;align-items:center;gap:8px">
        <input type="checkbox" id="sttBootLoad" ${st.boot_load ? 'checked' : ''} style="width:auto">
        启动时预加载
      </label>
    </div>
    <div class="actions" style="margin-top:12px">
      <button class="btn-primary" id="sttSetup"><i class="ri-download-fill"></i> ${st.ready ? '重新安装' : '下载并启用'}</button>
      ${st.model_downloaded ? '<button class="btn-ghost" id="sttRemove"><i class="ri-delete-bin-line"></i> 删除模型</button>' : ''}
    </div>
    <div id="sttResult" style="margin-top:10px;font-size:13px"></div>
  `;
  document.getElementById('sttSetup').onclick = () => setupStt();
  const rmBtn = document.getElementById('sttRemove');
  if (rmBtn) rmBtn.onclick = () => removeSttModel();
  document.getElementById('sttModelSize').onchange = async (e) => {
    try {
      await fetch('/stt/model', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
        body: JSON.stringify({ model_name: e.target.value }),
      });
    } catch (_) {}
  };
  document.getElementById('sttBootLoad').onchange = async (e) => {
    try {
      await fetch('/stt/boot-load', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
        body: JSON.stringify({ enabled: e.target.checked }),
      });
    } catch (_) {}
  };
  document.getElementById('sttEnable').onchange = async (e) => {
    const on = e.target.checked;
    try {
      await fetch('/stt/enabled', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
        body: JSON.stringify({ enabled: on }),
      });
    } catch (_) {}
    if (on && !st.ready) setupStt();
  };
}

// 安装依赖 + 下载模型 (后台 · 轮询进度)
async function setupStt() {
  const $res = document.getElementById('sttResult');
  if (!$res) return;
  $res.innerHTML = '<span style="color:var(--sys)"><i class="ri-loader-fill"></i> 开始安装依赖 (pilk + faster-whisper ~100MB) · 需 1-3 分钟…</span>';
  try {
    const resp = await fetch('/stt/setup', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token },
    });
    const data = await resp.json();
    if (!resp.ok) {
      $res.innerHTML = `<span style="color:var(--red)"><i class="ri-error-warning-fill"></i> ${escHtml(data.detail || '安装失败')}</span>`;
      return;
    }
    // 依赖装完 → 开始下载模型 → 轮询进度
    $res.innerHTML = '<span style="color:var(--sys)"><i class="ri-loader-fill"></i> 依赖已装 · 开始下载模型…</span>';
    pollSttProgress();
  } catch (e) {
    $res.innerHTML = `<span style="color:var(--red)"><i class="ri-close-fill"></i> ${escHtml(e.message)}</span>`;
  }
}

// 轮询安装进度
function pollSttProgress() {
  const $res = document.getElementById('sttResult');
  if (!$res) return;
  let n = 0;
  const timer = setInterval(async () => {
    n++;
    try {
      const resp = await fetch('/stt/status', { headers: { 'Authorization': 'Bearer ' + token } });
      const st = await resp.json();
      if (st.ready) {
        clearInterval(timer);
        $res.innerHTML = '<span style="color:#6ed27a"><i class="ri-check-fill"></i> 语音识别增强已就绪 · 微信语音现在能转文字了</span>';
        loadSttConfig();
      } else if (n > 600) {  // 10 分钟超时 (small 模型 ~460MB · hf-mirror 下载可能要几分钟)
        clearInterval(timer);
        $res.innerHTML = '<span style="color:var(--red)"><i class="ri-error-warning-fill"></i> 安装超时 · 查看 daemon 日志 · 可重试</span>';
      } else {
        $res.innerHTML = `<span style="color:var(--sys)"><i class="ri-loader-fill"></i> 安装中 (${Math.min(n, 600)}s) · 依赖/模型下载中…</span>`;
      }
    } catch (_) {
      if (n > 600) { clearInterval(timer); }
    }
  }, 1000);
}

async function removeSttModel() {
  const $res = document.getElementById('sttResult');
  if (!$res) return;
  if (!confirm('删除 whisper 模型文件 (~几百 MB)？依赖保留，可重新下载。')) return;
  try {
    const resp = await fetch('/stt/remove-model', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token },
    });
    const data = await resp.json();
    $res.innerHTML = data.ok
      ? '<span style="color:#6ed27a"><i class="ri-check-fill"></i> 模型已删除</span>'
      : `<span style="color:var(--red)"><i class="ri-error-warning-fill"></i> ${escHtml(data.error || '删除失败')}</span>`;
    loadSttConfig();
  } catch (e) {
    $res.innerHTML = `<span style="color:var(--red)"><i class="ri-close-fill"></i> ${escHtml(e.message)}</span>`;
  }
}

// ─── wish-b313583b · Embedding 语义检索配置卡 (独立 tab · wish-241e0014 拆分) ───
async function renderSettingsEmbedding() {
  const body = document.getElementById('settingsBody');
  body.innerHTML = `
    <div class="llm-section">
      <div class="llm-section-head">
        <h3><i class="ri-brain-line"></i> 记忆语义检索 (Embedding) · <span id="embStatusLabel" style="color:var(--dim)">加载中…</span></h3>
        <span class="llm-hint">给记忆检索加语义理解：用近义词、换种说法也能搜到相关记忆（纯字面匹配做不到）· 未配置时自动复用已配的智谱 key · 也可自定义任意兼容 API</span>
      </div>
      <div id="embBody" style="min-height:60px"><span class="field-hint">加载中…</span></div>
    </div>
    <div class="llm-section" style="margin-top:22px">
      <div class="llm-section-head">
        <h3><i class="ri-global-line"></i> 外网搜索 · <span id="srchStatusLabel" style="color:var(--dim)">加载中…</span></h3>
        <span class="llm-hint">可选。不填也能搜（免费刮网页）。贴上搜索 KEY 之后，中文教程 / 口播 /「怎么做」能搜到真文章，对话里会列出带站点的结果卡。</span>
      </div>
      <div id="srchBody" style="min-height:60px"><span class="field-hint">加载中…</span></div>
    </div>
  `;
  loadEmbedConfig();
  loadSearchConfig();
}

// ─── wish-b313583b · Embedding 语义检索配置卡 ───
async function loadEmbedConfig() {
  const $status = document.getElementById('embStatusLabel');
  const $body = document.getElementById('embBody');
  if (!$status || !$body) return;

  let cfg = { enabled: true, configured: false, source: '', model: 'embedding-3', base_url: '', api_key: '', covered: 0, total: 0 };
  try {
    const resp = await fetch('/embed-config', { headers: { 'Authorization': 'Bearer ' + token } });
    if (resp.ok) cfg = await resp.json();
  } catch (_) {}

  const pct = cfg.total > 0 ? Math.round(cfg.covered / cfg.total * 100) : 0;
  const srcLabel = cfg.source === 'user' ? '自定义配置' : (cfg.source === 'zhipu-provider' ? '自动复用智谱' : (cfg.source === 'env' ? '.env' : '未配置'));
  $status.innerHTML = cfg.enabled
    ? '<span style="color:#6ed27a">已开启 ✓</span>'
    : '<span style="color:var(--red)">已关闭</span>';

  $body.innerHTML = `
    <div class="field">
      <label>模型名</label>
      <input id="embModel" type="text" value="${escHtml(cfg.model || '')}" placeholder="embedding-3">
      <div class="field-hint">任意兼容 Embedding API 的模型名 · 如智谱 embedding-3 / OpenAI text-embedding-3-small</div>
    </div>
    <div class="field">
      <label>API 地址</label>
      <input id="embBaseUrl" type="text" value="${escHtml(cfg.base_url || '')}" placeholder="https://open.bigmodel.cn/api/paas/v4">
      <div class="field-hint">OpenAI 兼容的 API 根地址 (不带 /embeddings)</div>
    </div>
    <div class="field">
      <label>API Key</label>
      <input id="embApiKey" type="password" value="${escHtml(cfg.api_key || '')}" placeholder="${cfg.configured ? '已存 key · 不改就留空' : 'sk-xxx'}">
      <div class="field-hint">${cfg.configured ? `当前来源: ${srcLabel} · 改配置请粘贴新 key` : '未配置 · 填 key 保存后即可用'}</div>
    </div>
    <div class="field">
      <label>语义增强开关</label>
      <label class="switch" style="margin-left:0">
        <input type="checkbox" id="embToggle" ${cfg.enabled ? 'checked' : ''} onchange="toggleEmbed()">
        <span class="slider"></span>
      </label>
      <div class="field-hint">关 = 记忆检索退化为纯字面匹配 · 开 = 补语义命中 (推荐)</div>
    </div>
    <div class="field">
      <label>覆盖状态</label>
      <div class="field-hint" style="font-size:13px">
        ${cfg.total > 0
          ? `高信号记忆向量覆盖 <b>${cfg.covered}</b>/${cfg.total} (<b>${pct}%</b>)`
          : '尚无记忆向量'}
      </div>
      <div class="field-hint" style="font-size:12px;color:#888;margin-top:2px">
        语义索引只覆盖摘要 / 操作手册 / 知识库等高质量源 · 历史对话原文走字面检索 (FTS5) 不计入向量
      </div>
    </div>
    <div class="actions" style="margin-top:8px;gap:8px">
      <button class="btn-primary" id="embSave"><i class="ri-save-fill"></i> 保存配置</button>
      <button class="btn-ghost" id="embTest"><i class="ri-flashlight-fill"></i> 测试连接</button>
      <button class="btn-ghost" id="embBackfill" ${cfg.covered >= cfg.total ? 'disabled' : ''}>
        <i class="ri-refresh-fill"></i> 回填缺失向量 (${Math.max(cfg.total - cfg.covered, 0)} 条)
      </button>
    </div>
    <div id="embResult" style="margin-top:8px;font-size:13px"></div>
  `;
  document.getElementById('embSave').onclick = () => doEmbedSave(false);
  document.getElementById('embTest').onclick = () => doEmbedSave(true);
  const $bf = document.getElementById('embBackfill');
  if ($bf) $bf.onclick = () => doEmbedBackfill();
}

async function doEmbedSave(testOnly) {
  const m = document.getElementById('embModel').value.trim();
  const u = document.getElementById('embBaseUrl').value.trim();
  const k = document.getElementById('embApiKey').value.trim();
  const resEl = document.getElementById('embResult');
  if (!m || !u) {
    if (resEl) resEl.innerHTML = '<span style="color:var(--red)"><i class="ri-error-warning-fill"></i> 模型名和 API 地址必填</span>';
    return;
  }
  const body = { model: m, base_url: u, action: testOnly ? 'test' : undefined };
  // 掩码回传检测: 输入框还是掩码 (sk-****xxxx) 说明用户没改 → 不传 key · 后端用已存
  if (k && !k.includes('****')) body.api_key = k;
  if (resEl) resEl.innerHTML = `<span style="color:var(--sys)"><i class="ri-loader-fill"></i> ${testOnly ? '测试中…' : '保存中…'}</span>`;
  try {
    const resp = await fetch('/embed-config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok) {
      if (resEl) resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-error-warning-fill"></i> ${escHtml(data.detail || '失败')}</span>`;
      return;
    }
    if (testOnly && data.test) {
      if (data.test.ok) {
        if (resEl) resEl.innerHTML = `<span style="color:#6ed27a"><i class="ri-check-fill"></i> 连接成功 · 维度 ${data.test.dim} · ${Math.round(data.test.ms)}ms</span>`;
      } else {
        if (resEl) resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-close-fill"></i> 连接失败: ${escHtml(data.test.error)}</span>`;
      }
    } else {
      if (resEl) resEl.innerHTML = '<span style="color:#6ed27a"><i class="ri-check-fill"></i> 已保存</span>';
      setTimeout(() => loadEmbedConfig(), 600);
    }
  } catch (e) {
    if (resEl) resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-close-fill"></i> ${escHtml(e.message)}</span>`;
  }
}

async function toggleEmbed() {
  const $on = document.getElementById('embToggle');
  const enabled = $on.checked;
  const resEl = document.getElementById('embResult');
  try {
    const resp = await fetch('/embed-config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify({ enabled }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      if (resEl) resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-error-warning-fill"></i> ${escHtml(data.detail || '保存失败')}</span>`;
      return;
    }
    if (resEl) resEl.innerHTML = `<span style="color:#6ed27a"><i class="ri-check-fill"></i> 语义增强已${enabled ? '开启' : '关闭'} · 下次记忆查询生效</span>`;
    loadEmbedConfig();
  } catch (e) {
    if (resEl) resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-close-fill"></i> ${escHtml(e.message)}</span>`;
  }
}

async function loadSearchConfig() {
  const $status = document.getElementById('srchStatusLabel');
  const $body = document.getElementById('srchBody');
  if (!$status || !$body) return;

  let cfg = { enabled: true, configured: false, active: false, source: '', api_key: '', provider: 'bocha' };
  try {
    const resp = await fetch('/search-config', { headers: { 'Authorization': 'Bearer ' + token } });
    if (resp.ok) cfg = await resp.json();
  } catch (_) {}

  const on = !!(cfg.active && cfg.enabled);
  $status.innerHTML = on
    ? '<span style="color:#6ed27a">已接博查 ✓</span>'
    : '<span style="color:var(--sys)">免费刮取 · 可选加强</span>';

  $body.innerHTML = `
    <div class="srch-guide">
      <div class="srch-guide-title"><i class="ri-information-line"></i> 不是必须填</div>
      <p>空着就能用现在的搜索。加了博查 KEY 会变好的地方：</p>
      <ul>
        <li>中文长尾：口播文案、短视频开头、平台玩法</li>
        <li>「怎么做 / 今天有什么」不再被拆成单字词典</li>
        <li>对话里出现带站点、日期的结果卡，点得开</li>
        <li>雷达深挖、选题查资料更准</li>
      </ul>
      <p class="srch-guide-link">去 <a href="https://open.bochaai.com/" target="_blank" rel="noopener">open.bochaai.com</a> 领取，新用户有免费次数。</p>
    </div>
    <div class="field">
      <label>博查 API Key</label>
      <input id="srchApiKey" type="password" value="${escHtml(cfg.api_key || '')}" placeholder="${cfg.configured ? '已存 key · 不改就留空' : '选填 · sk-…'}">
      <div class="field-hint">${cfg.configured ? '已存 key · 改的话贴新的' : '不填也没关系 · 搜索继续走免费刮取'}</div>
    </div>
    <div class="field">
      <label>使用搜索 API</label>
      <label class="switch" style="margin-left:0">
        <input type="checkbox" id="srchToggle" ${cfg.enabled ? 'checked' : ''} onchange="toggleSearchApi()">
        <span class="slider"></span>
      </label>
      <div class="field-hint">关 = 即使贴了 KEY 也走免费刮取</div>
    </div>
    <div class="actions" style="margin-top:8px;gap:8px">
      <button class="btn-primary" id="srchSave"><i class="ri-save-fill"></i> 保存</button>
      <button class="btn-ghost" id="srchTest"><i class="ri-flashlight-fill"></i> 测试（口播文案技巧）</button>
    </div>
    <div id="srchResult" style="margin-top:8px;font-size:13px"></div>
  `;
  document.getElementById('srchSave').onclick = () => doSearchSave(false);
  document.getElementById('srchTest').onclick = () => doSearchSave(true);
}

async function doSearchSave(testOnly) {
  const k = (document.getElementById('srchApiKey') || {}).value || '';
  const on = !!(document.getElementById('srchToggle') || {}).checked;
  const resEl = document.getElementById('srchResult');
  const body = { enabled: on, action: testOnly ? 'test' : undefined };
  if (k.trim() && !k.includes('****')) body.api_key = k.trim();
  if (resEl) resEl.innerHTML = `<span style="color:var(--sys)"><i class="ri-loader-fill"></i> ${testOnly ? '测试中…' : '保存中…'}</span>`;
  try {
    const resp = await fetch('/search-config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok) {
      if (resEl) resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-error-warning-fill"></i> ${escHtml(data.detail || '失败')}</span>`;
      return;
    }
    if (testOnly && data.test) {
      if (data.test.ok) {
        const titles = (data.test.titles || []).map(t => escHtml(String(t).slice(0, 42))).join('<br>');
        if (resEl) resEl.innerHTML = `<span style="color:#6ed27a"><i class="ri-check-fill"></i> 通了 · ${data.test.n} 条</span><div class="field-hint" style="margin-top:6px">${titles}</div>`;
      } else {
        if (resEl) resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-close-fill"></i> ${escHtml(data.test.error || '失败')}</span>`;
      }
      return;
    }
    if (resEl) resEl.innerHTML = '<span style="color:#6ed27a"><i class="ri-check-fill"></i> 已保存</span>';
    setTimeout(() => loadSearchConfig(), 500);
  } catch (e) {
    if (resEl) resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-close-fill"></i> ${escHtml(e.message)}</span>`;
  }
}

async function toggleSearchApi() {
  const $on = document.getElementById('srchToggle');
  const resEl = document.getElementById('srchResult');
  try {
    const resp = await fetch('/search-config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify({ enabled: !!$on.checked }),
    });
    if (!resp.ok) throw new Error('保存失败');
    if (resEl) resEl.innerHTML = `<span style="color:#6ed27a"><i class="ri-check-fill"></i> 已${$on.checked ? '开启' : '关闭'}搜索 API</span>`;
    loadSearchConfig();
  } catch (e) {
    if (resEl) resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-close-fill"></i> ${escHtml(e.message)}</span>`;
  }
}

async function doEmbedBackfill() {
  const resEl = document.getElementById('embResult');
  if (resEl) resEl.innerHTML = '<span style="color:var(--sys)"><i class="ri-loader-fill"></i> 回填启动… 后台跑 · 刷新此页看进度</span>';
  try {
    const resp = await fetch('/embed-config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify({ action: 'backfill' }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      if (resEl) resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-error-warning-fill"></i> ${escHtml(data.detail || '启动失败')}</span>`;
      return;
    }
    if (resEl) resEl.innerHTML = '<span style="color:#6ed27a"><i class="ri-check-fill"></i> 后台回填已启动 · 稍后刷新看覆盖增长</span>';
  } catch (e) {
    if (resEl) resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-close-fill"></i> ${escHtml(e.message)}</span>`;
  }
}

function renderSettingsAccess() {
  const body = document.getElementById('settingsBody');
  body.innerHTML = `
    <div class="llm-section">
      <div class="llm-section-head"><h3>🔑 API Token · 决定 WebUI 能否连 daemon</h3></div>
      <div class="field">
        <label>API Token (Bearer)</label>
        <input id="accTokenIn" type="password" value="${escHtml(token || '')}" placeholder="OPUS_API_TOKEN 的值">
        <div class="field-hint">⚠ 这是打开这个页面用的密码，不是模型的 Key。模型 Key 在「模型」里配。</div>
        <div class="field-hint">在这个软件目录的 <code>.env</code> 文件里找 <code>OPUS_API_TOKEN</code> 那一行，把等号后面复制进来。本机一般不用填。</div>
      </div>

      <div class="llm-section-head" style="margin-top:18px"><h3>📂 当前对话</h3></div>
      <div class="field">
        <label>当前对话编号</label>
        <input id="accSessionIn" type="text" value="${escHtml(sessionId || '')}" placeholder="留空 = 新对话，或粘贴已有对话的编号">
      </div>

      <div class="llm-section-head" style="margin-top:18px"><h3>✋ 工具确认策略</h3></div>
      <div class="field">
        <label>工具确认</label>
        <select id="accAutoIn">
          <option value="auto" ${autoConfirm === 'auto' ? 'selected' : ''}>保守 · 只跑安全的</option>
          <option value="confirm" ${autoConfirm === 'confirm' ? 'selected' : ''}>推荐 · 普通操作自动跑，危险的仍要你点</option>
          <option value="guard" ${autoConfirm === 'guard' ? 'selected' : ''}>全自动 · 没人看着才用</option>
        </select>
        <div class="field-hint">推荐档：危险操作会弹出卡片等你点。全自动档：连危险操作也不问，只在没人能点的时候用。</div>
      </div>

      <!-- wish-f563a56d · trusted commands · BRO 临时给 OPUS 30min/24h/永久 信任窗口 -->
      <div class="llm-section-head" style="margin-top:18px"><h3>🔓 Trusted Commands · 信任清单</h3></div>
      <div class="field-hint" style="margin-bottom:8px">
        当 auto_confirm=auto 时·CONFIRM 档命令 (例如 <code>pip install</code>) 会被 skip。
        把命令头加到信任清单后·窗口期内 Daemonkey 调这类命令自动通过。
        <br><strong>红线</strong>: GUARD 黑名单 (rm -rf / format / git push --force) 永远不会被 trusted。
      </div>
      <div class="field" style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;">
        <div style="flex:1;min-width:180px">
          <label style="font-size:11px">命令头 pattern</label>
          <input id="accTrustPattern" type="text" placeholder="例如: pip install" style="width:100%">
        </div>
        <div>
          <label style="font-size:11px">时长</label>
          <select id="accTrustDuration">
            <option value="30">30 分钟</option>
            <option value="240">4 小时</option>
            <option value="1440">24 小时</option>
            <option value="0">永久 (谨慎)</option>
          </select>
        </div>
        <div style="flex:2;min-width:180px">
          <label style="font-size:11px">为什么信任（可选）</label>
          <input id="accTrustReason" type="text" placeholder="例如：让它装一个搜索库">
        </div>
        <button class="btn-primary" onclick="addTrustedCommand()">➕ 加入</button>
      </div>
      <div id="accTrustList" class="field-hint" style="margin-top:8px;font-size:12px">加载中…</div>

      <div class="actions" style="margin-top:18px">
        <button class="btn-primary" onclick="saveAccessSettings()">保存</button>
      </div>
      <div id="accSaveStatus" class="field-hint" style="margin-top:6px"></div>
    </div>
  `;
  // 异步刷一次 trusted 列表
  setTimeout(() => { try { refreshTrustedCommands(); } catch {} }, 50);
}

// wish-f563a56d · trusted commands UI helpers
async function refreshTrustedCommands() {
  const target = document.getElementById('accTrustList');
  if (!target) return;
  if (!token) { target.textContent = '⚠ 先填 token'; return; }
  try {
    const r = await fetch('/trusted_commands', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) {
      target.innerHTML = '<i class="ri-close-fill"></i> 加载失败 HTTP ' + r.status;
      return;
    }
    const j = await r.json();
    const items = (j && j.items) || [];
    if (!items.length) {
      target.innerHTML = '<i>暂无 trusted commands · Daemonkey 调 CONFIRM 档命令时会被 auto_confirm 策略卡住</i>';
      return;
    }
    const rows = items.map(it => {
      const remain = it._remaining_seconds;
      let remainStr;
      if (remain === null) {
        remainStr = '<span style="color:#f59e0b">永久</span>';
      } else if (remain <= 0) {
        remainStr = '<span style="color:#999">已过期</span>';
      } else if (remain < 60) {
        remainStr = remain + 's';
      } else if (remain < 3600) {
        remainStr = Math.floor(remain / 60) + 'min';
      } else {
        remainStr = Math.floor(remain / 3600) + 'h ' + Math.floor((remain % 3600) / 60) + 'min';
      }
      const reasonStr = it.reason ? ' · ' + escHtml(it.reason) : '';
      return `<div style="display:flex;justify-content:space-between;align-items:center;padding:4px 8px;border-bottom:1px solid #2a2f3a">
        <span><code>${escHtml(it.pattern)}</code> · ${remainStr}${reasonStr}</span>
        <button onclick="removeTrustedCommand('${jsStr(it.id)}')" style="background:transparent;border:1px solid #475569;color:#94a3b8;padding:2px 8px;border-radius:4px;cursor:pointer">删除</button>
      </div>`;
    }).join('');
    target.innerHTML = rows;
  } catch (e) {
    target.innerHTML = '<i class="ri-close-fill"></i> ' + e.message;
  }
}

async function addTrustedCommand() {
  const pat = document.getElementById('accTrustPattern').value.trim();
  const dur = parseInt(document.getElementById('accTrustDuration').value, 10);
  const reason = document.getElementById('accTrustReason').value.trim();
  if (!pat) {
    opusAlert({ title: '空 pattern', message: '请填命令头 (例如 "pip install")' });
    return;
  }
  if (!token) {
    opusAlert({ title: '缺 token', message: '请先填 API token' });
    return;
  }
  try {
    const r = await fetch('/trusted_commands', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        pattern: pat,
        duration_minutes: dur || null,
        reason,
      }),
    });
    if (!r.ok) {
      const txt = await r.text();
      opusAlert({ title: '加入失败', message: 'HTTP ' + r.status + '\n' + txt });
      return;
    }
    document.getElementById('accTrustPattern').value = '';
    document.getElementById('accTrustReason').value = '';
    await refreshTrustedCommands();
  } catch (e) {
    opusAlert({ title: '加入失败', message: e.message });
  }
}

async function removeTrustedCommand(itemId) {
  if (!token) return;
  try {
    const r = await fetch('/trusted_commands/' + encodeURIComponent(itemId), {
      method: 'DELETE',
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) {
      const txt = await r.text();
      opusAlert({ title: '删除失败', message: 'HTTP ' + r.status + '\n' + txt });
      return;
    }
    await refreshTrustedCommands();
  } catch (e) {
    opusAlert({ title: '删除失败', message: e.message });
  }
}

function saveAccessSettings() {
  const newToken = document.getElementById('accTokenIn').value.trim();
  const newSession = document.getElementById('accSessionIn').value.trim();
  const newAuto = document.getElementById('accAutoIn').value;
  token = newToken;
  sessionId = newSession;
  autoConfirm = newAuto;
  localStorage.setItem(STORAGE.token, token);
  localStorage.setItem(STORAGE.session, sessionId);
  localStorage.setItem(STORAGE.autoConfirm, autoConfirm);
  if (typeof updateCurrentLabel === 'function') updateCurrentLabel();
  if (typeof saveSid === 'function') saveSid(sessionId);
  document.getElementById('accSaveStatus').innerHTML = '<i class="ri-check-fill"></i> 已保存 · ' + (token ? '可以聊了' : '⚠ token 为空');
  document.getElementById('accSaveStatus').className = 'field-hint ok';
  // 同步刷新右上角模型切换器
  if (typeof loadCurrentModel === 'function') loadCurrentModel();
}

// ─── 卷六十一 · 微信 & 主动 CALL 设置面板 ───
let _wechatQrPoll = null;

function renderSettingsWechat() {
  const body = document.getElementById('settingsBody');
  body.innerHTML = `
    <div class="llm-section">
      <div class="chan-grid">
        <!-- 微信卡 -->
        <div class="chan-card">
          <div class="chan-card-head">
            <div class="chan-icon wx"><i class="ri-wechat-fill"></i></div>
            <div><div class="chan-title">微信 · 官方 ClawBot (iLink)</div>
                 <div class="chan-sub">纯 HTTP 官方接口 · 不碰客户端 · 无封号风险</div></div>
            <span class="chan-badge off" id="wechatBadge">未连接</span>
          </div>
          <div class="chan-live" id="wechatStatus"><span class="live-dot idle"></span> 加载中…</div>
          <div class="chan-actions">
            <button class="btn-primary" onclick="wechatGenQr()"><i class="ri-qr-code-line"></i> 生成扫码登录二维码</button>
            <span class="field-hint" style="margin:0">手机微信扫一扫 → 授权『微信 ClawBot』· 重新扫可换绑</span>
          </div>
          <div id="wechatQrBox" style="display:none;text-align:center;margin-top:12px"></div>
          <div class="chan-info-bar warn"><i class="ri-time-line"></i> <b>24 小时窗口</b>：你在微信先发一句 → 开窗 · 窗口内 Daemonkey 能主动找你 · 跨天零互动发不出（腾讯反骚扰）</div>
        </div>
        <!-- 飞书卡 (0.9.1 · 两层: L1 webhook 推送 + L2 机器人对话) -->
        <div class="chan-card">
          <div class="chan-card-head">
            <div class="chan-icon fs"><i class="ri-flight-takeoff-line"></i></div>
            <div><div class="chan-title">飞书 · 对话 & 工作区</div>
                 <div class="chan-sub">群聊 @即回 · 读文档/表格 · 总结群消息</div></div>
            <span class="chan-badge off" id="feishuBadge">未配置</span>
          </div>
          <div class="chan-live" id="feishuStatus"><span class="live-dot idle"></span> 加载中…</div>
          <div class="chan-form">
            <div><label class="field-label">App ID</label>
                 <input id="feishuAppId" class="field-input" placeholder="cli_xxxxxxxxxxxxxxxx"
                        onkeydown="if(event.key==='Enter')feishuSaveConfig()"/></div>
            <div><label class="field-label">App Secret</label>
                 <input id="feishuAppSecret" type="password" class="field-input" placeholder="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                        onkeydown="if(event.key==='Enter')feishuSaveConfig()"/></div>
          </div>
          <div class="chan-actions">
            <button class="btn-primary" onclick="feishuSaveConfig()"><i class="ri-save-fill"></i> 保存并连接</button>
            <button class="btn-ghost" onclick="feishuToggle()"><i class="ri-power-line"></i> 启用/停用</button>
            <span id="feishuSaveMsg" class="field-hint" style="margin:0"></span>
          </div>
          <details class="chan-wizard">
            <summary><i class="ri-magic-line"></i> 还没有机器人？6 步接入向导</summary>
            <ol class="wizard-steps">
              <li><a href="https://open.feishu.cn/app?lang=zh-CN" target="_blank">创建企业自建应用</a>（开放平台 → 开发者后台 → 创建企业自建应用）</li>
              <li>添加 <b>机器人</b> 能力（应用能力 → 添加应用能力 → 机器人 → 创建）</li>
              <li>添加权限：飞书「权限管理」→ <b>批量导入</b> → 粘贴下面的 JSON → 一次配齐（也可逐条搜索添加）</li>
              <li>事件订阅：选 <b>使用长连接接收事件</b> + 订阅 <code>im.message.receive_v1</code>（事件与回调）</li>
              <li><b>创建版本并发布</b>（版本管理与发布 · 可用范围含自己）← 搜不到机器人 99% 是漏这步</li>
              <li>回来填上方 App ID / Secret → 保存并连接</li>
            </ol>
            <div class="perms-import">
              <div class="perms-import-head"><i class="ri-shield-keyhole-line"></i> 权限 JSON · 一键配齐
                <button class="btn-ghost perms-copy" onclick="copyFeishuScopes(this)"><i class="ri-file-copy-line"></i> 复制</button></div>
              <pre class="perms-json">{
  "scopes": {
    "tenant": [
      "im:message.p2p_msg:readonly",
      "im:message:send_as_bot",
      "im:message.group_at_msg:readonly",
      "im:message.group_msg",
      "im:message:readonly",
      "im:chat:readonly",
      "im:resource",
      "docx:document:readonly",
      "sheets:spreadsheet:readonly",
      "bitable:app:readonly"
    ],
    "user": [
      "docx:document:readonly"
    ]
  }
}</pre>
              <div class="perms-hint">用法：飞书开放平台 → 你的应用 → <b>权限管理</b> → 右上角 <b>批量导入</b> → 粘贴 → 确认 → <b>创建版本并发布</b>（不发布不生效！）。读文档/表格/群消息（im:message.group_msg=拉群历史 · 不带 :readonly）+ 群聊@（group_at_msg:readonly）+ 读文件（im:resource）都在里面了。</div>
            </div>
          </details>
          <div class="chan-info-bar ok" style="margin-top:10px"><i class="ri-check-line"></i> 官方 API + 长连接 · <b>无窗口限制</b> · 发布后去飞书搜你的机器人就能聊</div>
        </div>
        <!-- 频率卡 -->
        <div class="chan-card">
          <div class="chan-card-head">
            <div class="chan-icon cat"><i class="ri-paw-line"></i></div>
            <div><div class="chan-title">主动找你的频率</div>
                 <div class="chan-sub">高冷猫 ↔ 黏人犬 · 夜里永远不打扰</div></div>
          </div>
          <div id="wechatFreq" class="freq-seg">加载中…</div>
          <div class="chan-info-bar ok" style="margin-top:12px"><i class="ri-sun-line"></i> <span id="wechatFreqDesc">命中后随机时刻开口 · 23:00–9:00 静默</span></div>
        </div>
      </div>
    </div>
  `;
  setTimeout(() => { wechatLoadStatus(); wechatLoadFrequency(); feishuLoadStatus(); }, 30);
}

// ─── 0.9.0 (wish-aac348a1) · 飞书配置 UI ───

async function feishuLoadStatus() {
  const el = document.getElementById('feishuStatus');
  if (!el) return;
  if (!token) { el.innerHTML = '⚠ 先在『访问 & 会话』填 API Token'; return; }
  try {
    const r = await fetch('/api/feishu/status', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const s = await r.json();
    const listener = s.listener || {};
    const badge = document.getElementById('feishuBadge');
    if (badge) {
      if (s.configured && s.token_ok && listener.alive) { badge.textContent = '在线'; badge.className = 'chan-badge on'; }
      else if (s.configured && !s.token_ok) { badge.textContent = 'Token 异常'; badge.className = 'chan-badge warn'; }
      else { badge.textContent = '未配置'; badge.className = 'chan-badge off'; }
    }
    let liveInner;
    if (!s.configured) {
      liveInner = '<span class="live-dot idle"></span> 未配置 · 填 App ID + Secret 保存即连 · 群里 @ 它就能用';
    } else {
      const chips = [
        listener.ws_connected ? '<span class="chan-chip">ws <b>已连</b></span>' : '',
        listener.messages_in != null ? `<span class="chan-chip">收 <b>${listener.messages_in}</b></span><span class="chan-chip">回 <b>${listener.replies_out}</b></span>` : '',
        !s.token_ok ? '<span style="color:#fbbf24">· token 获取失败</span>' : '',
      ].filter(Boolean).join(' ');
      liveInner = `<span class="live-dot ${listener.alive ? 'on' : 'off'}"></span> 长连接 ${listener.alive ? '在线' : '离线'} ${chips}`;
    }
    el.innerHTML = liveInner;
    if (listener.last_error) {
      const info = el.parentElement.querySelector('.chan-info-bar.ok');
      if (info) {
        info.className = 'chan-info-bar warn';
        info.innerHTML = `<i class="ri-alert-line"></i> ${escHtml(listener.last_error)} · 去飞书开放平台检查权限/事件订阅`;
      }
    }
    // 回填已存配置 (只回填 app_id · secret 不回显)
    if (s.configured && document.getElementById('feishuAppId')) {
      document.getElementById('feishuAppId').placeholder = '已保存: ' + s.app_id;
      document.getElementById('feishuAppSecret').placeholder = '已保存 · 留空=不修改';
    }
  } catch (e) {
    el.innerHTML = '<i class="ri-close-fill"></i> 飞书状态加载失败: ' + escHtml(e.message);
  }
}

async function feishuSaveConfig() {
  const msg = document.getElementById('feishuSaveMsg');
  const appId = (document.getElementById('feishuAppId').value || '').trim();
  const appSecret = (document.getElementById('feishuAppSecret').value || '').trim();
  if (!appId && !appSecret) { msg.innerHTML = '<span style="color:#f59e0b">填一下 App ID 或 Secret</span>'; return; }
  if (!token) { msg.innerHTML = '<span style="color:#f59e0b">⚠ 先在『访问 & 会话』填 API Token</span>'; return; }
  msg.innerHTML = '⏳ 保存中…';
  try {
    const r = await fetch('/api/feishu/config', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ app_id: appId, app_secret: appSecret, enabled: true }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status));
    msg.innerHTML = d.token_ok
      ? '<span style="color:#34d399"><i class="ri-check-fill"></i> 已保存并连接成功！在飞书里找机器人发句话试试</span>'
      : '<span style="color:#f59e0b">⚠ 已保存但 token 失败: ' + escHtml(d.warning || '') + '</span>';
    document.getElementById('feishuAppId').value = '';
    document.getElementById('feishuAppSecret').value = '';
    feishuLoadStatus();
  } catch (e) {
    msg.innerHTML = '<span style="color:#f87171"><i class="ri-close-fill"></i> 保存失败: ' + escHtml(e.message) + '</span>';
  }
}

async function feishuToggle() {
  if (!token) return;
  try {
    const r = await fetch('/api/feishu/toggle', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: true }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error('HTTP ' + r.status);
    feishuLoadStatus();
  } catch (e) {
    const el = document.getElementById('feishuSaveMsg');
    if (el) el.innerHTML = '<span style="color:#f87171">切换失败: ' + escHtml(e.message) + '</span>';
  }
}

// ─── 0.9.1 · L1 群机器人 webhook (推送模式) ───

async function copyFeishuScopes(btn) {
  const json = `{
  "scopes": {
    "tenant": [
      "im:message.p2p_msg:readonly",
      "im:message:send_as_bot",
      "im:message.group_at_msg:readonly",
      "im:message.group_msg",
      "im:message:readonly",
      "im:chat:readonly",
      "im:resource",
      "docx:document:readonly",
      "sheets:spreadsheet:readonly",
      "bitable:app:readonly"
    ],
    "user": [
      "docx:document:readonly"
    ]
  }
}`;
  try {
    await navigator.clipboard.writeText(json);
    if (btn) { const old = btn.innerHTML; btn.innerHTML = '<i class="ri-check-fill"></i> 已复制'; setTimeout(() => { btn.innerHTML = old; }, 1500); }
  } catch (e) {
    if (btn) btn.innerHTML = '<i class="ri-close-fill"></i> 复制失败'; 
  }
}

async function wechatLoadStatus() {
  const el = document.getElementById('wechatStatus');
  if (!el) return;
  if (!token) { el.innerHTML = '⚠ 先在『访问 & 会话』填 API Token'; return; }
  try {
    const r = await fetch('/api/wechat/status', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const s = await r.json();
    const listener = s.listener || {};
    const badge = document.getElementById('wechatBadge');
    if (badge) {
      if (!s.configured) { badge.textContent = '未连接'; badge.className = 'chan-badge off'; }
      else if (s.silent) { badge.textContent = '已静默'; badge.className = 'chan-badge warn'; }
      else if (!s.window_open) { badge.textContent = '窗口已关'; badge.className = 'chan-badge warn'; }
      else { badge.textContent = '已连接'; badge.className = 'chan-badge on'; }
    }
    let liveInner;
    if (!s.configured) {
      liveInner = '<span class="live-dot idle"></span> 未连接 · 生成二维码扫码登录后开启';
    } else {
      const winTxt = s.window_open
        ? `<span style="color:var(--dim2)">· 窗口开着 (${s.context_age_hours ?? '?'}h 前说过话)</span>`
        : s.silent
          ? '<span style="color:var(--dim2)">· 已静默 (微信发 opus start 唤醒)</span>'
          : '<span style="color:#fbbf24">· 24h 窗口已关 · 你先发一句即开</span>';
      liveInner = `<span class="live-dot ${listener.alive ? 'on' : 'off'}"></span> 监听 ${listener.alive ? '在线' : '离线'}
        ${listener.messages_in != null ? `<span class="chan-chip">收 <b>${listener.messages_in}</b></span><span class="chan-chip">回 <b>${listener.replies_out}</b></span>` : ''}
        ${winTxt}`;
    }
    el.innerHTML = liveInner;
  } catch (e) {
    el.innerHTML = '<i class="ri-close-fill"></i> 状态加载失败: ' + escHtml(e.message);
  }
}

async function wechatGenQr() {
  const box = document.getElementById('wechatQrBox');
  if (!token) { opusAlert({ title: '缺 token', message: '先在『访问 & 会话』填 API Token' }); return; }
  if (_wechatQrPoll) { clearInterval(_wechatQrPoll); _wechatQrPoll = null; }
  box.style.display = 'block';
  box.innerHTML = '<div class="field-hint">取二维码中…</div>';
  try {
    const r = await fetch('/api/wechat/login/qr', {
      method: 'POST', headers: { 'Authorization': 'Bearer ' + token },
    });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    box.innerHTML = `
      <img src="${d.qr_data_uri}" alt="微信扫码" style="width:220px;height:220px;border-radius:10px;background:#fff;padding:8px"/>
      <div class="field-hint" style="margin-top:6px">用<b>手机微信</b>扫这个码 → 授权。约 3-4 分钟有效。</div>
      <div id="wechatQrPollMsg" class="field-hint" style="margin-top:4px">⏳ 等待扫码…</div>
    `;
    let tries = 0;
    _wechatQrPoll = setInterval(() => wechatPollQr(d.qrcode_id, ++tries), 2500);
  } catch (e) {
    box.innerHTML = '<div class="field-hint fail"><i class="ri-close-fill"></i> ' + escHtml(e.message) + '</div>';
  }
}

async function wechatPollQr(qrcodeId, tries) {
  const msg = document.getElementById('wechatQrPollMsg');
  if (tries > 96) { // ~4 分钟
    if (_wechatQrPoll) { clearInterval(_wechatQrPoll); _wechatQrPoll = null; }
    if (msg) msg.innerHTML = '⌛ 二维码过期了·点上面按钮重新生成';
    return;
  }
  try {
    const r = await fetch('/api/wechat/login/poll?qrcode=' + encodeURIComponent(qrcodeId), {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    const d = await r.json();
    if (d.logged_in) {
      if (_wechatQrPoll) { clearInterval(_wechatQrPoll); _wechatQrPoll = null; }
      if (msg) msg.innerHTML = '<span style="color:#34d399"><i class="ri-check-fill"></i> 已连接!监听已自动拉起·你在微信发句话试试</span>';
      wechatLoadStatus();
    } else if (d.status === 'expired') {
      if (_wechatQrPoll) { clearInterval(_wechatQrPoll); _wechatQrPoll = null; }
      if (msg) msg.innerHTML = '⌛ 二维码过期·点上面按钮重新生成';
    } else if (msg) {
      msg.innerHTML = '⏳ 等待扫码…';
    }
  } catch (e) { /* 网络抖动·下一拍再试 */ }
}

let _wechatFreqPresets = [];
async function wechatLoadFrequency() {
  const el = document.getElementById('wechatFreq');
  if (!el) return;
  if (!token) { el.innerHTML = '⚠ 先填 token'; return; }
  try {
    const r = await fetch('/api/wechat/frequency', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    _wechatFreqPresets = d.presets || [];
    wechatRenderFreq(d.current);
  } catch (e) {
    el.innerHTML = '<i class="ri-close-fill"></i> 加载失败: ' + escHtml(e.message);
  }
}

// 0.9.0 · 频率档 emoji → Remix 表情图标 (统一线条风格 · 替代 🐱🐶 emoji)
const _FREQ_EMOJI_ICON = {
  '\u{1F6AB}': 'ri-close-circle-line',   // 🚫 关闭
  '\u{1F63C}': 'ri-emotion-2-line',      // 😼 高冷猫 → 面瘫脸
  '\u{1F431}': 'ri-emotion-2-line',      // 🐱 猫系
  '\u2696\uFE0F': 'ri-emotion-normal-line', // ⚖️ 均衡 → 正常脸
  '\u{1F436}': 'ri-emotion-happy-line',  // 🐶 犬系 → 笑脸
  '\u{1F415}': 'ri-emotion-happy-line',  // 🐕 黏人犬
};
function freqIcon(emoji) { return _FREQ_EMOJI_ICON[emoji] || null; }

function wechatRenderFreq(currentId) {
  const el = document.getElementById('wechatFreq');
  const desc = document.getElementById('wechatFreqDesc');
  el.innerHTML = _wechatFreqPresets.map(p => {
    const ic = freqIcon(p.emoji);
    const iconHtml = ic ? `<span class="freq-emoji"><i class="${ic}"></i></span>` : `<span class="freq-emoji">${p.emoji}</span>`;
    return `<button class="freq-pill ${p.id === currentId ? 'active' : ''}" onclick="wechatSetFrequency('${p.id}')" title="${escHtml(p.desc)}">
      ${iconHtml}<span class="freq-label">${escHtml(p.label)}</span>
    </button>`;
  }).join('');
  const cur = _wechatFreqPresets.find(p => p.id === currentId);
  if (desc) {
    const ic = cur ? freqIcon(cur.emoji) : null;
    const curIcon = ic ? `<i class="${ic}"></i>` : (cur ? cur.emoji : '');
    desc.innerHTML = currentId === 'custom'
      ? '你以前在配置文件里手改过。点下面任一档就按档走。'
      : (cur ? `当前:${curIcon} <b>${escHtml(cur.label)}</b> · ${escHtml(cur.desc)}` : '');
  }
}

async function wechatSetFrequency(presetId) {
  if (!token) return;
  const el = document.getElementById('wechatFreq');
  try {
    const r = await fetch('/api/wechat/frequency', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ preset: presetId }),
    });
    if (!r.ok) { const t = await r.text(); throw new Error('HTTP ' + r.status + ' ' + t); }
    const d = await r.json();
    wechatRenderFreq(d.current);
  } catch (e) {
    opusAlert({ title: '设置失败', message: e.message });
  }
}

// ─── wish-fb6b7427 · 通知设置面板 ───
// 三条通道各自开关 · 音效(事项A已上线) / Windows toast(事项B) / 标签闪烁(事项C)
async function renderSettingsNotify() {
  const body = document.getElementById('settingsBody');
  body.innerHTML = '<div class="dash-empty">加载中…</div>';

  let cfg = { pet_sound: true, windows_toast: false, tab_flash: false };
  try {
    const resp = await fetch('/notification-config', { headers: { 'Authorization': 'Bearer ' + token } });
    if (resp.ok) cfg = await resp.json();
  } catch (_) {}

  body.innerHTML = `
    <div class="llm-section">
      <div class="llm-section-head">
        <h3><i class="ri-notification-3-fill"></i> 通知 · 做完或等你点确认时，怎么提醒你</h3>
        <span class="llm-hint">三个开关分开，保存就生效</span>
      </div>
      <div class="field">
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
          <input type="checkbox" id="ntfPetSound" ${cfg.pet_sound ? 'checked' : ''}>
          <span><i class="ri-volume-up-fill"></i> 桌宠提示音</span>
        </label>
        <div class="field-hint">做完一轮时桌宠出声。桌宠没开就没声音。</div>
      </div>
      <div class="field">
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
          <input type="checkbox" id="ntfToast" ${cfg.windows_toast ? 'checked' : ''}>
          <span><i class="ri-windows-fill"></i> Windows 系统通知</span>
        </label>
        <div class="field-hint">浏览器没开也能弹系统通知。</div>
      </div>
      <div class="field">
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
          <input type="checkbox" id="ntfTabFlash" ${cfg.tab_flash ? 'checked' : ''}>
          <span><i class="ri-flashlight-fill"></i> 浏览器标签闪烁</span>
        </label>
        <div class="field-hint">WebUI 标签在后台时标题闪烁 · 切回标签自动停</div>
      </div>
      <div class="actions" style="margin-top:12px">
        <button class="btn-primary" id="ntfSave"><i class="ri-save-fill"></i> 保存</button>
      </div>
      <div id="ntfResult" style="margin-top:8px;font-size:13px"></div>
    </div>
  `;

  document.getElementById('ntfSave').onclick = async () => {
    const resEl = document.getElementById('ntfResult');
    resEl.innerHTML = '<span style="color:var(--sys)"><i class="ri-loader-fill"></i> 保存中…</span>';
    try {
      const resp = await fetch('/notification-config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
        body: JSON.stringify({
          pet_sound: document.getElementById('ntfPetSound').checked,
          windows_toast: document.getElementById('ntfToast').checked,
          tab_flash: document.getElementById('ntfTabFlash').checked,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-error-warning-fill"></i> ${escHtml(data.detail || '保存失败')}</span>`;
        return;
      }
      if (data.config) _ntfCfg = data.config;  // 保存即生效 · 不用刷新
      resEl.innerHTML = '<span style="color:#6ed27a"><i class="ri-check-fill"></i> 已保存 · 下次完成通知起生效</span>';
    } catch (e) {
      resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-close-fill"></i> ${escHtml(e.message)}</span>`;
    }
  };
}

function renderSettingsData() {
  const body = document.getElementById('settingsBody');
  body.innerHTML = `
    <div class="llm-section">
      <div class="llm-section-head"><h3><i class="ri-save-fill"></i> 本地数据</h3></div>
      <div class="field-hint">
        浏览器只记住：
        <ul style="margin:6px 0 0 18px;padding:0;color:var(--dim)">
          <li>登录密码</li>
          <li>当前对话</li>
          <li>工具确认策略</li>
          <li>对话的别名、置顶、归档</li>
        </ul>
        对话和工坊都在这台电脑的磁盘上，清这里清不掉。
      </div>
      <div class="actions" style="margin-top:18px">
        <button class="btn-danger" onclick="resetAll()">清空本地数据 + 刷新</button>
      </div>
    </div>
  `;
}

async function resetAll() {
  const ok = await opusConfirm({
    title: '清空所有本地数据',
    message: '会清掉 token / sessionId / 别名等浏览器本地数据·然后刷新。\n服务端的对话不会动·随时能找回来。',
    okText: '清空并退出',
    cancelText: '再想想',
    danger: true,
  });
  if (!ok) return;
  localStorage.clear();
  location.reload();
}
