/* static/settings-pane.js · 工作台设置页 (LLM/多模态/Embedding/访问/微信/通知/掘金雷达/本地数据)
   从 chat.js 抽出 · 工作台中栏 + 陪伴家具弹窗共用同一份。
   依赖: token / sessionId / autoConfirm / STORAGE / $detailPane / escHtml / jsStr
         opusConfirm / opusPrompt / opusAlert / backToChat
   房间里 $detailPane === #dashView · backToChat === closeModal */

// 卷三十七 · 中栏 settings view (BRO 截图反馈 · 弹窗装不下 · 改 tabs)
// wish-3edbf065 · 没走完过向导 → 首次进设置就停在上手向导那页（点过「就这样」之后不再自动停）
let _settingsTab = (() => {
  try { return localStorage.getItem('opus_ui_setup_done') ? 'llm' : 'setup'; } catch (_) { return 'llm'; }
})();  // 'setup' | 'llm' | 'vision' | 'embedding' | 'access' | 'wechat' | 'notify' | 'radar' | 'data'
let _settingsPaintGen = 0;
function _settingsStill(tab, gen) {
  if (gen != null && gen !== _settingsPaintGen) return false;
  if (typeof currentView !== 'undefined' && currentView !== 'settings') return false;
  if (tab && _settingsTab !== tab) return false;
  return !!document.getElementById('settingsBody');
}
function openSettingsView() {
  if (typeof window._dashLoadSeq === 'number') window._dashLoadSeq += 1;
  currentView = 'settings';
  // 清左 nav 高亮 · settings 不属于任何 dashboard 维度
  document.querySelectorAll('.nav-item.active').forEach(b => b.classList.remove('active'));
  // 给底部 ⚙ 按钮加个高亮 · 让 BRO 知道当前在设置里
  document.querySelectorAll('.nav-settings-btn').forEach(b => b.classList.add('active'));
  renderSettingsView();
}

function renderSettingsView() {
  const tabs = [
    { id: 'setup', label: '<i class="ri-rocket-2-fill"></i> 上手向导', hint: '把能力一项项配齐 · 每项都写明「不配会失去什么」' },
    { id: 'llm', label: '<i class="ri-brain-fill"></i> LLM 模型', hint: '平台、模型和密钥，可存多套配置' },
    { id: 'vision', label: '<i class="ri-cpu-fill"></i> 多模态', hint: '看图 + 听 + 说 + 画 · 默认生图/语音合成/语音识别也在这里选择' },
    { id: 'embedding', label: '<i class="ri-search-eye-line"></i> Embedding & 搜索', hint: '记忆语义检索 + 可选外网搜索 KEY' },
    { id: 'access', label: '<i class="ri-key-fill"></i> 访问 & 会话', hint: 'API Token / Session / Auto-confirm' },
    { id: 'wechat', label: '<i class="ri-wechat-fill"></i> 微信 & 飞书', hint: '扫码连微信 · 配飞书机器人 · 主动找你的频率 (猫系↔犬系)' },
    { id: 'notify', label: '<i class="ri-notification-3-fill"></i> 通知', hint: '做完或等你点确认时，怎么提醒你 · 音效 / Windows 通知 / 标签闪烁' },
    { id: 'radar', label: '<i class="ri-radar-fill"></i> 掘金雷达', hint: '后台自动刷新的开关和频率 · 关掉就不抓' },
    { id: 'data', label: '<i class="ri-save-fill"></i> 本地数据', hint: '占用 / 可选清理' },
  ];
  $detailPane.innerHTML = `
    <div class="settings-pane">
      <div class="settings-head">
        <h2><i class="ri-settings-3-fill"></i> 设置</h2>
        <span class="meta">改完立刻生效，不用重启</span>
        <button onclick="backToChat()" title="返回对话"><i class="ri-close-line"></i> 关闭</button>
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
      { setup: '上手向导', llm: 'LLM 模型', vision: '多模态', embedding: 'Embedding', access: '访问', wechat: '微信 & 飞书', notify: '通知', radar: '掘金雷达', data: '本地数据' }[tabId]
    ));
  });
  renderSettingsBody();
}

function renderSettingsBody() {
  _settingsPaintGen += 1;
  if (_settingsTab === 'setup') renderSettingsSetup(true);
  else if (_settingsTab === 'llm') renderSettingsLLM();
  else if (_settingsTab === 'vision') renderSettingsVision();
  else if (_settingsTab === 'embedding') renderSettingsEmbedding();
  else if (_settingsTab === 'access') renderSettingsAccess();
  else if (_settingsTab === 'wechat') renderSettingsWechat();
  else if (_settingsTab === 'notify') renderSettingsNotify();
  else if (_settingsTab === 'radar') renderSettingsRadar();
  else if (_settingsTab === 'data') renderSettingsData();
}

// ─── wish-3edbf065 · 上手向导（定稿）──────────────────────────────
// 五项能力 · 每项写明「配了能干嘛 / 不配差在哪 / 怎么配（多服务可选 · 点开看优缺点 · 直达官网）」
// 下面是文案与服务清单的唯一数据源 · 改这里整页同步。
const SETUP_CAPS = [
  {
    id: 'embedding', name: '记忆语义检索', icon: 'ri-search-eye-line', tab: 'embedding',
    what: '让「翻旧账」不用抠原话 —— 你说个意思，它就能找到相关的那段记忆。属于增强项：不配也照样能用，只是联想弱一点。',
    gains: ['换个说法也能搜到旧事（"上次那个配色"直接命中那一次）', '知识库问一句话就定位到原文', '跨会话的联想召回更准，越用越懂你'],
    losses: ['最直接的影响是记忆星图的关联会稀疏一些', '翻旧账 / 知识库退化成按原词硬搜 —— 换个说法就找不到', '不影响正常使用 —— 她照样记得你说过的话，只是联想没这么灵'],
    lossTitle: '不配的话，差在这（不影响正常使用）',
    check: '点「测试连接」；或直接问我「上次我们聊的那个配色是啥」—— 我答得上来就是通了。',
    manual: {
      title: '记忆语义检索 · 完整手册',
      cost: '云端约 ¥0.5 / 百万字（日常一年几块钱）· 本地 ¥0',
      routes: [
        { h: '路线 A · 接云端 API', tag: '最省事', art: 'ri-cloud-fill',
          kv: [['首选', '硅基流动 siliconflow.cn · 送 2000 万 token · 国内直连'], ['备选', '智谱 bigmodel.cn · 已配过对话 key 可直接复用'],
               ['花钱', '约 ¥0.5 / 百万字'], ['怎么填', '粘 sk-... → 模型 BAAI/bge-m3'], ['耗时', '约 5 分钟']] },
        { h: '路线 B · 本地跑', tag: '零成本', art: 'ri-hard-drive-3-fill',
          kv: [['要装', 'Ollama（ollama.com · 一键安装包）'], ['一条命令', 'ollama pull nomic-embed-text'],
               ['地址', 'http://127.0.0.1:11434/v1'], ['占用', '磁盘 270MB · 内存约 500MB'], ['代价', '首次慢一两秒 · 完全离线']] },
      ],
      pits: '别把对话模型的 key 填进这里（报错就换 bge-m3）· 地址要带 /v1 · 本地跑的话 Ollama 得先启动着。',
    },
    paths: [
      { k: '接云端 API', h: '最省事 · 5 分钟', lv: '★☆☆',
        body: '<ol class="setup-steps"><li>挑一个服务（下面有对比），注册 → 拿 <code>sk-...</code></li>'
            + '<li>粘回设置页的 API Key，模型填 <code>BAAI/bge-m3</code>，保存</li><li>点「测试连接」，绿了就成</li></ol>'
            + '<div class="setup-note">已经配过智谱对话 key 的话，这里能一键复用，不用再注册。</div>',
        vendors: [
          { name: '硅基流动', tag: '推荐', price: '免费 2000 万 token · 约 ¥0.5/百万字', url: 'https://cloud.siliconflow.cn',
            pros: ['国内直连，不用梯子', '注册就送 2000 万 token', 'bge-m3 这个模型完全免费', '首字延迟低，搜索几乎无感'],
            cons: ['要手机号注册', '高峰期偶尔要排队'] },
          { name: '智谱 AI', tag: '可复用', price: '约 ¥0.5/百万字', url: 'https://open.bigmodel.cn',
            pros: ['国内大厂，稳定性好', '已配过智谱对话 key 可一键复用', '中文语料贴合度高'],
            cons: ['免费额度比硅基流动少', '新账号要实名认证'] },
          { name: '阿里云百炼', price: '约 ¥0.7/百万字', url: 'https://bailian.console.aliyun.com',
            pros: ['企业级稳定性，有 SLA', '和阿里云其他服务打通', 'text-embedding-v3 中文很强'],
            cons: ['要开通百炼服务，配置步骤偏多', '个人用偏重，控制台复杂'] },
        ] },
      { k: '本地跑', h: '不花钱 · 装一个东西', lv: '★★☆',
        body: '<ol class="setup-steps"><li>装 <b>Ollama</b>（ollama.com 下载，双击安装）</li>'
            + '<li>命令行跑一条：<code>ollama pull nomic-embed-text</code>（约 270MB）</li>'
            + '<li>设置页填地址 <code>http://127.0.0.1:11434/v1</code>，模型 <code>nomic-embed-text</code></li></ol>'
            + '<div class="setup-note">之后完全离线、永不花钱。代价是占约 500MB 内存，第一次搜慢一两秒。</div>',
        vendors: [
          { name: 'Ollama', tag: '推荐', price: '¥0', url: 'https://ollama.com',
            pros: ['完全离线，记忆数据不出本机', '一次装好永久免费', '一条命令就能跑，不用配环境'],
            cons: ['占约 500MB 内存', '首次搜索慢一两秒', '要自己保证 Ollama 后台在跑'] },
          { name: 'LM Studio', price: '¥0', url: 'https://lmstudio.ai',
            pros: ['图形界面，不用碰命令行', '同一套工具还能跑本地对话模型', '模型市场里一键下'],
            cons: ['比 Ollama 更吃资源', '要手动开「本地服务器」开关', '启动比 Ollama 慢'] },
        ] },
      { k: '先跳过', h: '', lv: '',
        body: '<p>不配也能用 —— 记忆检索会退化成「按原词搜」，你攒的东西一条都不会丢。以后想开，随时回来补。</p>' },
    ],
  },
  {
    id: 'search', name: '外网搜索', icon: 'ri-global-line', tab: 'embedding',
    what: '让我能上网查实时的事。不配也有搜索，只是走内置兜底通道 —— 抓得慢、结果糙；配上专业 API 后查得准、带出处。',
    gains: ['查得准：返回结构化结果 + 原文链接，不是我编的', '快：专业 API 一秒出结果，兜底通道要等好几秒', '掘金雷达能稳定抓到新信息', '问「今天有什么新闻」不会扑空'],
    losses: ['内置兜底：偶尔抓不到、慢几秒、结果页不干净，得自己筛', '问实时的事更容易扑空，或者答得含糊', '雷达 / 趋势这类「看世界」的功能时灵时不灵'],
    lossTitle: '不配的话，差在这（不是「不能用」）',
    check: '说一句「帮我搜一下今天的 AI 新闻」—— 回你带链接的结果、且快，就是通了。',
    manual: {
      title: '外网搜索 · 完整手册',
      cost: '云端约 ¥0.03 / 次（有免费额度）· 兜底通道 ¥0',
      routes: [
        { h: '路线 A · 专业搜索 API', tag: '查得准', art: 'ri-search-2-line',
          kv: [['首选', '博查 bochaai.com · 国内直连 · 为 AI 设计'], ['备选', 'Serper.dev / Tavily（要能访问外网）'],
               ['花钱', '约 ¥0.03 / 次 · 有免费额度'], ['怎么填', '设置页「外网搜索」粘 key'], ['耗时', '约 3 分钟']] },
        { h: '路线 B · 什么都不做', tag: '零配置', art: 'ri-shield-line',
          kv: [['要装', '不用装'], ['花钱', '¥0'], ['效果', '偶尔抓不到 · 慢几秒 · 结果不干净'], ['适合', '只是偶尔问一句、不急着要']] },
      ],
      pits: '不配不会瘫 —— 别被"没 key 就不能搜"吓到。真配了之后，最大的差别是「快 + 带出处」。',
    },
    paths: [
      { k: '接专业搜索 API', h: '查得准、够快', lv: '★☆☆',
        body: '<ol class="setup-steps"><li>从下面挑一个（都给了优缺点），注册拿 key</li>'
            + '<li>粘回设置页「外网搜索」的 API Key，保存</li><li>让它搜一条新闻试试 —— 带链接、出得快就成</li></ol>'
            + '<div class="setup-note">这一步随时可以配 —— 不配也不会瘫，只是慢和糙。</div>',
        vendors: [
          { name: '博查 Bocha', tag: '推荐', price: '有免费额度 · 约 ¥0.03/次', url: 'https://open.bochaai.com',
            pros: ['国内直连，不用梯子', '专为 AI 设计，返回干净的结构化结果', '中文内容覆盖好', '按次计费不心疼'],
            cons: ['要实名认证', '免费额度用完要充值'] },
          { name: 'Serper.dev', price: '注册送 2500 次', url: 'https://serper.dev',
            pros: ['走 Google，结果质量高', '一次注册送 2500 次，够用很久', '响应极快'],
            cons: ['要能访问外网（海外站）', '之后按美元结算，充值门槛高'] },
          { name: 'Tavily', price: '每月 1000 次免费', url: 'https://tavily.com',
            pros: ['专为 AI Agent 设计，直接返回摘要', '免费额度每月刷新', '和对话流程贴合'],
            cons: ['要能访问外网', '中文/国内内容覆盖不如博查'] },
        ] },
      { k: '用免费兜底', h: '零配置', lv: '',
        body: '<p>什么都不用做 —— 系统本来就走内置的免费搜索通道。什么时候适合先这样：你只是偶尔问一句、不急着要，或者还在犹豫要不要掏钱。</p>',
        vendors: [
          { name: '内置兜底（不填 key）', tag: '零配置', price: '¥0', url: '',
            pros: ['开箱即用，不用注册不用花钱', '不用管 key 过期、余额这些事'],
            cons: ['偶尔抓不到结果', '慢几秒（要等它试完几个源）', '结果页不干净，得自己筛'] },
        ] },
      { k: '先跳过', h: '', lv: '',
        body: '<p>等于把「上网看看」这件事整个关掉。适合短期只当本地助手用。</p>' },
    ],
  },
  {
    id: 'image', name: '图片生成', icon: 'ri-image-fill', tab: 'vision',
    what: '让我能画图、给 PPT / 报告配图、做封面。',
    gains: ['对话里说「画一张…」直接出图', '报告、演示稿要配图时自动补上', '封面、头像、素材不用再切别的工具'],
    losses: ['说「画一张」没反应 —— 只能给你一段文字', 'PPT / 报告要配图时留一块灰底占位', '封面、素材都得你自己去别处做'],
    check: '说一句「画一只在打字的猫」—— 半分多钟内出图就是通了。',
    manual: {
      title: '图片生成 · 完整手册',
      cost: '云端约 ¥0.05 / 张 · 本地 ¥0（要显卡）',
      routes: [
        { h: '路线 A · 接云端 API', tag: '画质最好', art: 'ri-cloud-fill',
          kv: [['可选', '即梦（火山）/ 通义万相（阿里）/ GPT Image'], ['花钱', '约 ¥0.05 / 张'],
               ['怎么接', '工坊找生图应用填 key → 设置页选成默认'], ['耗时', '约 5 分钟']] },
        { h: '路线 B · 本地 ComfyUI', tag: '零成本', art: 'ri-hard-drive-3-fill',
          kv: [['要装', 'ComfyUI（有整合包，解压即用）'], ['要下', 'SDXL / Flux 模型（几个 G）'],
               ['地址', 'http://127.0.0.1:8188'], ['门槛', '建议 ≥8G 显存'], ['出图', '一张 10~20 秒']] },
      ],
      pits: '没独显就别走本地 —— 会慢到没法用，老老实实接云端按张买。',
    },
    paths: [
      { k: '接云端 API', h: '画质最好', lv: '★★☆',
        body: '<ol class="setup-steps"><li>挑一个服务，注册并开通图片生成</li><li>到工坊找现成的生图应用，把 key 填进去</li>'
            + '<li>回设置页「多模态 → 生图」，把它选成默认</li></ol>',
        vendors: [
          { name: '即梦（火山引擎）', tag: '推荐', price: '约 ¥0.05/张', url: 'https://jimeng.jianying.com',
            pros: ['中文提示词理解好', '出图快，风格现代', '国内直连、按张计费'],
            cons: ['要在火山引擎开通服务', '部分模型要企业认证'] },
          { name: '通义万相（阿里云）', price: '约 ¥0.06/张', url: 'https://tongyi.aliyun.com/wanxiang',
            pros: ['阿里云生态，稳定', '中文场景、国风内容强', '有免费体验额度'],
            cons: ['控制台配置偏绕', '单张价格略高'] },
          { name: 'GPT Image（OpenAI）', price: '约 $0.04/张', url: 'https://platform.openai.com',
            pros: ['指令跟随最强，能画准文字', '风格上限高', '多轮改图体验好'],
            cons: ['要能访问外网', '美元结算，单张最贵', '生成速度偏慢'] },
        ] },
      { k: '本地 ComfyUI', h: '零成本 · 要有显卡', lv: '★★★',
        body: '<ol class="setup-steps"><li>装 <b>ComfyUI</b>（有整合包，解压即用）</li>'
            + '<li>下一个 SDXL / Flux 模型放到 <code>models/checkpoints</code></li>'
            + '<li>启动后设置页填 <code>http://127.0.0.1:8188</code></li></ol>'
            + '<div class="setup-note">一张图 10~20 秒，完全不花钱。建议 8G 显存以上；没独显会非常慢。</div>',
        vendors: [
          { name: 'ComfyUI', tag: '推荐', price: '¥0', url: 'https://github.com/comfyanonymous/ComfyUI',
            pros: ['节点式，能力上限最高', '社区模型/工作流生态最大', '有整合包，解压即用'],
            cons: ['要 ≥8G 显存，没独显基本跑不动', '第一次下模型要几个 G', '工作流学习曲线陡'] },
          { name: 'Stable Diffusion WebUI', price: '¥0', url: 'https://github.com/AUTOMATIC1111/stable-diffusion-webui',
            pros: ['界面简单，像传统画图软件', '插件多', '教程最多，出问题好搜'],
            cons: ['出图速度比 ComfyUI 慢', '显存占用更高', '新模型支持跟进偏慢'] },
        ] },
      { k: '先跳过', h: '', lv: '',
        body: '<p>不影响任何文字功能 —— 只是要画图时得临时去配一下。</p>' },
    ],
  },
  {
    id: 'tts', name: '语音合成（说）', icon: 'ri-volume-up-fill', tab: 'vision',
    what: '让我能出声：语音对话、念稿试听、提醒事项直接读给你听。',
    gains: ['对话能变成「聊」，而不是「看」', '口播稿能直接听效果，不用自己读', '定时提醒可以念出来'],
    losses: ['我只能打字，你只能看 —— 没有声音', '口播、配音的稿子没法在对话里直接试听'],
    check: '设置页「语音合成」点「试听」—— 出声音就是通了。',
    manual: {
      title: '语音合成 · 完整手册',
      cost: '本地 ¥0 · 云端约 ¥0.001 / 千字',
      routes: [
        { h: '路线 A · 本地免费', tag: '零成本', art: 'ri-hard-drive-3-fill',
          kv: [['要装', '工坊「语音合成」应用，一键装'], ['音色', '晓晓 / 云希 / 小艺…几十种'],
               ['花钱', '¥0'], ['代价', '要联网（走微软在线语音）'], ['耗时', '约 5 分钟']] },
        { h: '路线 B · 云端音色 / 克隆', tag: '音色更多', art: 'ri-mic-line',
          kv: [['可选', '火山引擎（豆包）/ 阿里云 CosyVoice / Azure'], ['花钱', '约 ¥0.001 / 千字'],
               ['亮点', '能克隆你自己的声音'], ['门槛', '要实名 + 开通服务']] },
      ],
      pits: '想「听起来像人」优先试云端；想「不要钱」用本地 edge-tts，日常够用。',
    },
    paths: [
      { k: '本地免费', h: '零成本 · 5 分钟', lv: '★☆☆',
        body: '<ol class="setup-steps"><li>工坊里找「语音合成」应用，一键装</li>'
            + '<li>回设置页「多模态 → 语音合成」选成默认</li><li>挑一个音色，点试听</li></ol>',
        vendors: [
          { name: 'edge-tts', tag: '推荐', price: '¥0', url: 'https://github.com/rany2/edge-tts',
            pros: ['完全免费，音质自然', '音色多（几十种中文）', '装一次就能用，不用注册'],
            cons: ['要联网（走微软在线语音）', '不能克隆你自己的声音', '语速/情绪控制较弱'] },
          { name: 'GPT-SoVITS', price: '¥0', url: 'https://github.com/RVC-Boss/GPT-SoVITS',
            pros: ['能克隆音色，几分钟素材就够', '完全本地，隐私最好', '中文效果第一梯队'],
            cons: ['要独立显卡，配置偏麻烦', '要自己准备一段干净录音', '首次训练要花时间'] },
        ] },
      { k: '接云端音色', h: '音色更多 · 能克隆', lv: '★★☆',
        body: '<p>云端 TTS 的选择更多、音色更专业，还能克隆你的声音。按字符计费，通常 ¥0.001/千字这个级别。</p>',
        vendors: [
          { name: '火山引擎（豆包语音）', tag: '推荐', price: '约 ¥0.001/千字', url: 'https://www.volcengine.com/product/tts',
            pros: ['音色多、情感自然', '延迟低，适合实时对话', '能克隆音色'],
            cons: ['要实名 + 开通服务', '有免费额度但额度不大'] },
          { name: '阿里云 CosyVoice', price: '约 ¥0.001/千字', url: 'https://help.aliyun.com/zh/isi/',
            pros: ['支持音色克隆和情感控制', '中文方言覆盖好', '和阿里云打通'],
            cons: ['控制台配置偏绕', '克隆功能要单独申请'] },
          { name: 'Azure TTS（微软）', price: '约 $16/百万字符', url: 'https://azure.microsoft.com/products/ai-services/text-to-speech',
            pros: ['音质天花板级', '语言/音色最全', 'SSML 控制粒度细'],
            cons: ['要能访问外网', '要绑国际信用卡', '注册流程对国内用户偏难'] },
        ] },
      { k: '先跳过', h: '', lv: '',
        body: '<p>跳过就保持「纯文字」模式。以后想听声音，随时回来开。</p>' },
    ],
  },
  {
    id: 'stt', name: '语音识别（听）', icon: 'ri-mic-2-fill', tab: 'vision',
    what: '让你能对着麦克风说话，也让我能听见你的唤醒词。',
    gains: ['不用打字，直接说话给我听', '口令唤醒（喊一声就出来）', '录音 / 语音备忘能自动转成文字'],
    losses: ['只能用键盘打字', '唤醒词用不了 —— 得手动点开窗口', '录的音没法自动转文字'],
    check: '按一下麦克风说句话 —— 文字落进输入框就是通了。',
    manual: {
      title: '语音识别 · 完整手册',
      cost: '本地 ¥0 · 云端约 ¥0.02 / 分钟',
      routes: [
        { h: '路线 A · 本地 whisper', tag: '隐私最好', art: 'ri-hard-drive-3-fill',
          kv: [['怎么开', '设置页「本地语音识别」打开开关'], ['模型', '自动下 whisper-base（约 150MB）'],
               ['花钱', '¥0'], ['隐私', '录音完全不出本机'], ['耗时', '约 5 分钟']] },
        { h: '路线 B · 云端转写', tag: '更准', art: 'ri-cloud-fill',
          kv: [['可选', '讯飞听见 / 阿里云 / OpenAI Whisper API'], ['花钱', '约 ¥0.02 / 分钟'],
               ['亮点', '识别更准，不吃本机资源'], ['代价', '录音要上传']] },
      ],
      pits: '口音重或环境嘈杂时，云端明显更准；日常安静环境本地 whisper 就够。',
    },
    paths: [
      { k: '本地 whisper', h: '隐私最好 · 零成本', lv: '★☆☆',
        body: '<ol class="setup-steps"><li>设置页「多模态 → 本地语音识别」打开开关</li>'
            + '<li>点「下载模型」，自动拉 <code>whisper-base</code>（约 150MB）</li><li>等它跑通，麦克风按钮就出来了</li></ol>'
            + '<div class="setup-note">录音完全不出本机。想更准可以换 <code>whisper-small</code>（约 500MB）。</div>',
        vendors: [
          { name: 'faster-whisper（内置）', tag: '推荐', price: '¥0', url: 'https://github.com/SYSTRAN/faster-whisper',
            pros: ['录音不出本机，隐私最好', '开关一点自动下模型，零门槛', '中文识别够日常用'],
            cons: ['首次下模型要等一会儿', '大模型会吃内存', '口音重/嘈杂环境不如云端'] },
          { name: 'whisper.cpp', price: '¥0', url: 'https://github.com/ggml-org/whisper.cpp',
            pros: ['CPU 也能跑，不用显卡', '体积极小，启动快', '支持量化，内存占用低'],
            cons: ['要自己编译 / 下模型', '准确率略低于 faster-whisper'] },
          { name: '硅基流动 SenseVoice', price: '约 ¥0.01/分钟', url: 'https://cloud.siliconflow.cn',
            pros: ['中文识别特别准', '几乎不要钱', '不用占本机资源'],
            cons: ['录音要上传到云端', '依赖网络'] },
        ] },
      { k: '接云端转写', h: '更准 · 不占本机', lv: '★★☆',
        body: '<p>云端的识别模型更大更准，也不吃你本机资源。代价是录音要上传、按分钟计费。</p>',
        vendors: [
          { name: '讯飞听见', tag: '推荐', price: '约 ¥0.02/分钟', url: 'https://www.iflytek.com',
            pros: ['中文识别国内第一梯队', '方言支持好', '有实时转写接口'],
            cons: ['要实名 + 开通', '按分钟计费，长录音会花钱'] },
          { name: '阿里云智能语音', price: '约 ¥0.02/分钟', url: 'https://www.aliyun.com/product/nls',
            pros: ['和阿里云生态打通', '支持实时/录音文件两种', '企业级稳定'],
            cons: ['控制台配置偏绕', '免费额度有限'] },
          { name: 'OpenAI Whisper API', price: '约 $0.006/分钟', url: 'https://platform.openai.com',
            pros: ['多语言最强，含口音', '接口极其简单', '带标点、带时间戳'],
            cons: ['要能访问外网', '美元结算', '国内网络不稳定'] },
        ] },
      { k: '先跳过', h: '', lv: '',
        body: '<p>跳过就是纯键盘模式。别的功能一切正常。</p>' },
    ],
  },
];

const OPUS_SETUP_KEY = 'opus_ui_setup_done';
let _setupCur = -1;   // -1 = 首页（开始之前）· 0..4 = 五项能力
let _setupCardH = 0;    // 卡片历史最大高度 —— 锁住它，切页时框架不跳
let _setupState = {};       // capId -> true/false（实时探测）
const _setupPath = {};      // capId -> 路径下标
const _setupVendor = {};    // capId:pi -> 服务下标
const _setupManualOpen = {};// capId -> 是否展开手册

function _setupFetch(path) {
  return fetch(path, { headers: { 'Authorization': 'Bearer ' + token } })
    .then(r => (r.ok ? r.json() : null)).catch(() => null);
}

async function _setupProbe() {
  const [emb, media, srch] = await Promise.all([
    _setupFetch('/embed-config'), _setupFetch('/media-defaults'), _setupFetch('/search-config'),
  ]);
  return {
    embedding: !!(emb && emb.enabled && emb.configured),
    search: !!(srch && srch.configured),
    image: !!(media && media.image && media.image.ready),
    tts: !!(media && media.tts && media.tts.ready),
    stt: !!(media && media.stt && media.stt.ready),
  };
}

function _setupDoneCount() {
  return SETUP_CAPS.filter(c => _setupState[c.id]).length;
}

// force=true（首次进入 / 从别的 tab 切回）才重新探测状态。
// 翻页 · 切路径 · 选服务 · 展开手册一律走 _setupPaint()（同步 · 不经过「正在查…」白屏）
async function renderSettingsSetup(force) {
  const gen = _settingsPaintGen;
  const body = document.getElementById('settingsBody');
  if (!body) return;
  if (force || !Object.keys(_setupState).length) {
    body.innerHTML = '<div class="dash-empty">正在查你配到哪了…</div>';
    const st = await _setupProbe();
    if (!_settingsStill('setup', gen)) return;
    _setupState = st;
  }
  _setupPaint();
}

// ── 首页（BRO: 放 IP 形象 · 讲清向导是什么 · 说明工坊跑通的应用也是能力来源）──
function _setupIntroHtml() {
  return `
    <div class="setup-intro">
      <img class="setup-intro-ip" alt="" onerror="this.style.display='none'"
           src="/companion/assets/ip-greet.png">
      <div class="setup-intro-body">
        <h3>这页带你把这 5 项能力配齐</h3>
        <p>没配齐她也能用 —— 只是会少掉写明的那些功能。一项一项来，随时能跳过，以后想补再回来。</p>
        <div class="setup-intro-grid">
          ${SETUP_CAPS.map(c => `<div class="setup-intro-card">
            <i class="${c.icon}"></i>
            <b>${escHtml(c.name)}</b>
            <span>${escHtml(c.what)}</span></div>`).join('')}
        </div>
        <div class="setup-tip">
          <div class="setup-tip-h"><i class="ri-lightbulb-flash-fill"></i> 能力不一定靠外部服务 —— 先看看工坊里已经装了什么</div>
          <ul>
            <li><b>语音合成</b>：工坊里的「语音合成」应用装好就能出声（edge-tts · 免费）</li>
            <li><b>图片生成</b>：工坊里现成的生图应用，这里选成默认即可</li>
            <li><b>语音识别</b>：设置里的本地 whisper 开关，点一下自动下模型，录音不出本机</li>
            <li><b>记忆检索</b>：属于增强项，可以本地跑（Ollama · 零成本），也可以先不配 —— 不影响正常使用</li>
            <li><b>外网搜索</b>：不配也有内置兜底，只是慢一点、糙一点</li>
          </ul>
          <div class="setup-tip-f">先翻翻工坊里已经装了什么 —— 有些能力是「装上就有」。</div>
        </div>
        <div class="setup-acts">
          <button class="btn-primary" type="button" onclick="setupGo(0)">开始 · 看第一项 <i class="ri-arrow-right-line"></i></button>
          <span class="ld-bar-gap"></span>
          <a class="setup-manual-btn" onclick="setupMarkDone()">这些我懂了 · 先不看</a>
        </div>
      </div>
    </div>`;
}

// ── 单项能力的卡片正文 ──
function _setupCapHtml(cur, ok) {
  const pIdx = _setupPath[cur.id] || 0;
  const p = cur.paths[pIdx];

  const gains = `<div class="setup-blk gain"><div class="setup-blk-h"><i class="ri-sparkling-2-fill"></i> 配好之后能干嘛</div>
    <ul>${cur.gains.map(x => `<li>${escHtml(x)}</li>`).join('')}</ul></div>`;
  const loses = `<div class="setup-blk loss"><div class="setup-blk-h"><i class="ri-close-circle-fill"></i> ${escHtml(cur.lossTitle || '不配会失去这些')}</div>
    <ul>${cur.losses.map(x => `<li>${escHtml(x)}</li>`).join('')}</ul></div>`;

  const ptabs = cur.paths.map((x, i) =>
    `<div class="setup-ptab${i === pIdx ? ' on' : ''}" onclick="setupPickPath('${cur.id}',${i})">${escHtml(x.k)}</div>`).join('');

  // 服务清单：只列名字/价格/优缺点，不打「推荐」这类倾向标记 —— 让他自己挑
  let vendorHtml = '';
  if (p.vendors && p.vendors.length) {
    const vkey = cur.id + ':' + pIdx;
    const vSel = _setupVendor[vkey] != null ? _setupVendor[vkey] : 0;
    const v = p.vendors[vSel];
    const vchips = p.vendors.map((x, i) =>
      `<div class="setup-vchip${i === vSel ? ' on' : ''}" onclick="setupPickVendor('${cur.id}',${pIdx},${i})">
         ${escHtml(x.name)}${x.price ? `<span>${escHtml(x.price)}</span>` : ''}</div>`).join('');
    const link = v.url
      ? `<a class="setup-vgo" href="${escHtml(v.url)}" target="_blank" rel="noopener">去拿 KEY <i class="ri-external-link-line"></i></a>` : '';
    vendorHtml = `<div class="setup-vchips">${vchips}</div>
      <div class="setup-vdet">
        <div class="setup-vhd">${escHtml(v.name)}${link}</div>
        <ul class="setup-vpc">${(v.pros || []).map(x => `<li class="p">${escHtml(x)}</li>`).join('')}${(v.cons || []).map(x => `<li class="c">${escHtml(x)}</li>`).join('')}</ul>
      </div>`;
  }

  const manualOpen = !!_setupManualOpen[cur.id];
  const m = cur.manual;
  const manualHtml = (manualOpen && m) ? `
    <div class="setup-manual">
      <div class="setup-manual-h"><i class="ri-book-2-fill"></i> ${escHtml(m.title)}
        <span class="setup-manual-x" onclick="setupManual('${cur.id}',false)"><i class="ri-close-line"></i></span></div>
      <div class="setup-manual-grid">
        ${m.routes.map(r => `<div class="setup-manual-card">
          <h6><i class="${r.art}"></i> ${escHtml(r.h)}${r.tag ? `<span class="pick">${escHtml(r.tag)}</span>` : ''}</h6>
          <dl>${r.kv.map(kv => `<dt>${escHtml(kv[0])}</dt><dd>${escHtml(kv[1])}</dd>`).join('')}</dl>
        </div>`).join('')}
      </div>
      <div class="setup-pits"><i class="ri-error-warning-fill"></i> <b>常见坑</b>：${escHtml(m.pits)}</div>
    </div>` : '';

  const doneN = _setupDoneCount();
  return `
    ${doneN === SETUP_CAPS.length
      ? '<div class="setup-allok"><i class="ri-checkbox-circle-fill"></i> 五项全配齐了 —— 记忆能联想、能上网查、能画、能听会说。</div>' : ''}
    <div class="setup-head">
      <h3><i class="${cur.icon}"></i> ${escHtml(cur.name)}
        ${ok ? '<span class="setup-badge ok"><i class="ri-check-fill"></i> 已配好</span>'
             : '<span class="setup-badge no"><i class="ri-error-warning-line"></i> 没配</span>'}</h3>
      <div class="setup-sub">${escHtml(cur.what)}</div>
    </div>
    <div class="setup-blkrow">${gains}${loses}</div>
    <div class="setup-ptabs">${ptabs}</div>
    <div class="setup-pane">
      ${p.h ? `<h5>${escHtml(p.h)}${p.lv ? ` <span class="lv">难度 ${escHtml(p.lv)}</span>` : ''}</h5>` : ''}
      ${p.body}${vendorHtml}
    </div>
    <div class="setup-chk"><i class="ri-checkbox-circle-line"></i> <b>怎么知道配对没有</b>：${escHtml(cur.check)}</div>
    ${manualHtml}
    <div class="setup-acts">
      ${_setupCur > -1 ? `<button class="btn-ghost" type="button" onclick="setupGo(${_setupCur - 1})"><i class="ri-arrow-left-line"></i> 上一项</button>` : ''}
      <button class="btn-primary" type="button" onclick="setupGoConfig('${cur.id}')"><i class="ri-settings-3-line"></i> 去配置这项</button>
      ${_setupCur < SETUP_CAPS.length - 1 ? `<button class="btn-ghost" type="button" onclick="setupGo(${_setupCur + 1})">下一项 <i class="ri-arrow-right-line"></i></button>` : ''}
      <span class="ld-bar-gap"></span>
      <a class="setup-manual-btn" onclick="setupManual('${cur.id}',${manualOpen ? 'false' : 'true'})">
        <i class="ri-book-2-fill"></i> ${manualOpen ? '收起手册' : '不会配？看完整手册'}</a>
    </div>`;
}

// 骨架只建一次，之后只 patch「芯片行 + 卡片」两块 —— 不再整页重建
function _setupPaint() {
  const body = document.getElementById('settingsBody');
  if (!body) return;
  const doneN = _setupDoneCount();
  if (doneN === SETUP_CAPS.length) {
    try { localStorage.setItem(OPUS_SETUP_KEY, '1'); } catch (_) {}
  }
  const onIntro = _setupCur < 0;
  const cur = onIntro ? null : SETUP_CAPS[_setupCur];

  const chips = `<div class="setup-chip${onIntro ? ' on' : ''}" onclick="setupGo(-1)">
      <i class="ri-play-circle-line"></i><span>开始之前</span><em>这是什么</em></div>`
    + SETUP_CAPS.map((c, i) => {
        const good = !!_setupState[c.id];
        return `<div class="setup-chip${i === _setupCur ? ' on' : ''}${good ? ' ok' : ''}" onclick="setupGo(${i})">
          <i class="${c.icon}"></i><span>${escHtml(c.name)}</span>
          <em>${good ? '✓ 已配' : '没配'}</em></div>`;
      }).join('');

  if (!document.getElementById('setupHero')) {
    body.innerHTML = `
      <div class="llm-section setup-hero" id="setupHero">
        <div class="llm-section-head">
          <h3><i class="ri-rocket-2-fill"></i> 上手向导 · <span id="setupDone">0</span>/${SETUP_CAPS.length} 项已配齐</h3>
          <span class="llm-hint">不配也能用，只是会少掉写明的那些功能。随时可以跳回来补。</span>
        </div>
        <div class="setup-prog"><i id="setupProg"></i></div>
        <div class="setup-chips" id="setupChips"></div>
      </div>
      <div class="llm-section setup-card" id="setupCard"></div>
      <div class="actions" style="margin-top:16px;align-items:center">
        <button class="btn-ghost" type="button" onclick="setupMarkDone()"><i class="ri-check-double-line"></i> 不折腾了 · 就这样</button>
        <span class="field-hint">点过之后不再自动停在这一页（随时还能从上面的 tab 进来）</span>
      </div>`;
  }
  const $done = document.getElementById('setupDone');
  if ($done) $done.textContent = String(doneN);
  const $prog = document.getElementById('setupProg');
  if ($prog) $prog.style.width = Math.round(doneN / SETUP_CAPS.length * 100) + '%';
  document.getElementById('setupChips').innerHTML = chips;
  // 先松掉旧的 min-height 再量，免得量到被自己撑高的值（否则会一轮轮往上滚）
  const $card = document.getElementById('setupCard');
  $card.style.minHeight = '0px';
  $card.innerHTML = onIntro ? _setupIntroHtml() : _setupCapHtml(cur, !!_setupState[cur.id]);
  const h = $card.scrollHeight;
  if (h > _setupCardH) _setupCardH = h;
  $card.style.minHeight = _setupCardH + 'px';
}

function setupGo(i) {
  _setupCur = Math.max(-1, Math.min(SETUP_CAPS.length - 1, i));
  _setupPaint();
}
function setupPickPath(capId, i) {
  _setupPath[capId] = i;
  _setupPaint();
}
function setupPickVendor(capId, pi, vi) {
  _setupVendor[capId + ':' + pi] = vi;
  _setupPaint();
}
function setupManual(capId, open) {
  _setupManualOpen[capId] = open !== false;
  _setupPaint();
}
function setupMarkDone() {
  try { localStorage.setItem(OPUS_SETUP_KEY, '1'); } catch (_) {}
  switchSettingsTab('llm');
}
// 跳到对应设置页把那一块闪一下，让用户知道该动哪里
function setupGoConfig(capId) {
  const cap = SETUP_CAPS.find(c => c.id === capId);
  if (!cap) return;
  switchSettingsTab(cap.tab);
  setTimeout(() => {
    let el = null;
    if (cap.id === 'embedding' || cap.id === 'search') el = document.getElementById('embBody');
    else if (cap.id === 'image') el = document.getElementById('mediaImageApp');
    else if (cap.id === 'tts') el = document.getElementById('mediaTtsApp');
    else if (cap.id === 'stt') el = document.getElementById('sttBody');
    const sec = el && el.closest ? el.closest('.llm-section') : null;
    if (!sec) return;
    sec.classList.add('setup-flash');
    sec.scrollIntoView({ block: 'center', behavior: 'smooth' });
    setTimeout(() => sec.classList.remove('setup-flash'), 2400);
  }, 450);
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
      body: JSON.stringify(Object.assign({}, cfg, {
        session_id: (typeof getSid === 'function' ? getSid() : (window.getSid ? window.getSid() : '')),
      })),
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
let _providerConfigsDefaultId = null;   // wish-c6422f9c · 新对话默认模型
let _providerConfigsSubagentId = null;  // wish-c6422f9c · 分身默认模型
let _providerPresets = [];      // 预设 (来自 GET /providers)

async function renderSettingsLLM() {
  const gen = _settingsPaintGen;
  const body = document.getElementById('settingsBody');
  if (!_settingsStill('llm', gen) || !body) return;
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
    _providerConfigsDefaultId = confData.default_id || '';
    _providerConfigsSubagentId = confData.subagent_id || '';
    _providerPresets = presetData.presets || [];
  } catch (e) {
    if (!_settingsStill('llm', gen)) return;
    const dead = document.getElementById('settingsBody');
    if (dead) dead.innerHTML = `<div class="dash-empty">加载失败: ${escHtml(e.message)}</div>`;
    return;
  }
  if (!_settingsStill('llm', gen)) return;

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

async function setDefaultConfig(cfgId) {
  const token = localStorage.getItem('opus_token') || '';
  try {
    const r = await fetch('/provider-configs/' + encodeURIComponent(cfgId) + '/default', {
      method: 'POST', headers: { 'Authorization': 'Bearer ' + token },
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || data.message || ('HTTP ' + r.status));
    addSys(data.note || '已设为默认模型');
    await renderSettingsLLM();
  } catch (e) {
    addSys('设为默认失败: ' + e.message);
  }
}

async function setSubagentConfig(cfgId, on) {
  const token = localStorage.getItem('opus_token') || '';
  try {
    const r = await fetch('/provider-configs/' + encodeURIComponent(on ? cfgId : '-') + '/subagent', {
      method: 'POST', headers: { 'Authorization': 'Bearer ' + token },
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || data.message || ('HTTP ' + r.status));
    addSys(data.note || (on ? '已设为子代理模型' : '已取消子代理模型'));
    await renderSettingsLLM();
  } catch (e) {
    addSys('设置子代理模型失败: ' + e.message);
  }
}

function renderLlmConfigCard(c) {
  const isActive = c.id === _providerConfigsActiveId;
  const isDefault = c.id === _providerConfigsDefaultId;
  const isSub = c.id === _providerConfigsSubagentId;
  const presetIcon = ({
    'deepseek-official': '<i class="ri-brain-line"></i>',
    'aihubmix': '<i class="ri-apps-2-line"></i>',
    'anthropic': '<i class="ri-sparkling-2-line"></i>',
    'openrouter': '<i class="ri-route-line"></i>',
    'dashscope': '<i class="ri-cloud-line"></i>',
    'custom': '<i class="ri-settings-3-line"></i>',
  })[c.preset_id] || '<i class="ri-cpu-line"></i>';
  return `
    <div class="llm-config-card${isActive ? ' active' : ''}${isDefault ? ' default-on' : ''}${isSub ? ' subagent-on' : ''}${c.director ? ' director-on' : ''}" data-cfg-id="${escHtml(c.id)}">
      <div class="lc-row1">
        <span class="lc-icon">${presetIcon}</span>
        <span class="lc-name">${escHtml(c.name || c.model || c.id)}</span>
        ${isActive ? '<span class="lc-active-badge">当前</span>' : ''}
        ${isDefault ? '<span class="lc-default-badge" title="新开的对话默认用这条"><i class="ri-home-4-fill"></i> 默认</span>' : ''}
        ${isSub ? '<span class="lc-subagent-badge" title="分身（子代理）默认用这条"><i class="ri-share-forward-fill"></i> 子代理</span>' : ''}
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
          ${isActive ? '' : `<button onclick="activateConfig('${jsStr(c.id)}')" title="切换 OPUS 用这个跑">激活</button>`}
          <button onclick="testConfig('${jsStr(c.id)}')" title="ping 一下试通不通">测试</button>
          <button class="lc-director-btn${c.director ? ' on' : ''}" onclick="toggleDirectorConfig('${jsStr(c.id)}', ${c.director ? 'false' : 'true'})" title="${c.director ? '取消这个配置的顾问身份' : '设为顾问。出方案、卡住、收尾时会请来看一眼。只能有一个。'}"><i class="ri-vip-crown-${c.director ? 'fill' : 'line'}"></i> ${c.director ? '取消顾问' : '设为顾问'}</button><i class="ri-question-line lc-director-help" onclick="showDirectorHelp()" title="顾问模型是干啥的？点我"></i>
          <button class="lc-default-btn${isDefault ? ' on' : ''}" onclick="setDefaultConfig('${jsStr(c.id)}')" title="${isDefault ? '已经是默认了 · 新对话就是用它' : '设为默认模型 · 以后新开的对话默认用它（不影响当前对话）'}"><i class="ri-home-4-${isDefault ? 'fill' : 'line'}"></i> ${isDefault ? '已是默认' : '设为默认'}</button>
          <button class="lc-subagent-btn${isSub ? ' on' : ''}" onclick="setSubagentConfig('${jsStr(c.id)}', ${isSub ? 'false' : 'true'})" title="${isSub ? '取消子代理模型 · 分身跟随主模型' : '设为子代理模型 · 分身(dispatch_subagent)跑任务时用它'}"><i class="ri-share-forward-${isSub ? 'fill' : 'line'}"></i> ${isSub ? '取消子代理' : '设为子代理'}</button>
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
        <div style="margin-top:6px">
          <button type="button" class="btn-ghost" id="llmEditFetchModels" onclick="fetchLocalModels()" title="从 base_url 拉模型列表 (LM Studio / Ollama 等 OpenAI 兼容端点)"><i class="ri-download-cloud-2-line"></i> 拉取本机模型</button>
        </div>
        <div class="field-hint" id="llmEditModelFetchHint"></div>
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
        <div class="field-hint" id="llmEditPricingHint">未配置 · 点「自动查官方价」由 OPUS 搜官网填入 · 你确认后才保存</div>
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
  // wish-cef00196 · LM Studio 本地模型：占位 key + 自动拉取本机模型
  // wish-cc1f37af · 本机 fork llama.cpp（自定义量化）：同款处理 · 换占位 key
  if (preset.id === 'lm-studio' || preset.id === 'llama-prism') {
    const keyInput = document.getElementById('llmEditApiKey');
    if (keyInput && !keyInput.value) keyInput.value = preset.id;
    const keyHint = keyInput?.parentElement?.querySelector('.field-hint');
    if (keyHint) keyHint.textContent = '本机模型不需要真 key · 已自动填占位符 · 不用改';
    fetchLocalModels();
  }
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

// wish-cef00196 · 从 base_url 拉模型列表 (LM Studio 本地发现 · 也适用 Ollama 等 OpenAI 兼容端点)
async function fetchLocalModels() {
  const base = document.getElementById('llmEditBaseUrl')?.value.trim() || '';
  const sel = document.getElementById('llmEditModelSelect');
  const hintEl = document.getElementById('llmEditModelFetchHint');
  if (!base) {
    if (hintEl) hintEl.textContent = '先填 Base URL · LM Studio 默认 http://localhost:1234/v1';
    return;
  }
  if (hintEl) hintEl.textContent = '正在拉取本机模型列表…';
  try {
    const r = await fetch('/providers/models?base_url=' + encodeURIComponent(base), {
      headers: { 'Authorization': 'Bearer ' + token },
    });
    const data = await r.json();
    if (!data.ok) {
      if (hintEl) hintEl.innerHTML = `<span style="color:#FC8181">${escHtml(data.hint || data.error || '拉取失败')}</span>`;
      return;
    }
    const models = data.models || [];
    if (!models.length) {
      if (hintEl) hintEl.textContent = '连上了 · 但模型列表为空 · 先在 LM Studio 里加载一个模型';
      return;
    }
    sel.innerHTML = '';
    models.forEach(m => {
      const opt = document.createElement('option');
      opt.value = m.id;
      opt.textContent = m.id;
      sel.appendChild(opt);
    });
    sel.insertAdjacentHTML('afterbegin', '<option value="">— 手填 —</option>');
    sel.value = models[0].id;
    document.getElementById('llmEditModel').value = models[0].id;
    if (hintEl) hintEl.innerHTML = `<i class="ri-check-fill"></i> 拉到 ${models.length} 个本机模型 · 已填第一个 · 下拉里可换`;
  } catch (e) {
    if (hintEl) hintEl.innerHTML = `<span style="color:#FC8181">网络出错: ${escHtml(e.message || '')}</span>`;
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
  const gen = _settingsPaintGen;
  const body = document.getElementById('settingsBody');
  if (!_settingsStill('vision', gen) || !body) return;
  body.innerHTML = '<div class="dash-empty">加载中…</div>';

  let cfg = { model: '', base_url: '', api_key: '', configured: false };
  try {
    const resp = await fetch('/vision-config', { headers: { 'Authorization': 'Bearer ' + token } });
    if (resp.ok) cfg = await resp.json();
  } catch (_) {}
  if (!_settingsStill('vision', gen)) return;

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

    <!-- wish-241e0014 · 本地 whisper (可选 · 设置页开关驱动安装) -->
    <div class="llm-section" style="margin-top:18px">
      <div class="llm-section-head">
        <h3><i class="ri-mic-fill"></i> 本地语音识别 (whisper) · <span id="sttStatusLabel" style="color:var(--dim)">加载中…</span></h3>
        <span class="llm-hint">本机转写 · 可选 · 打开后下载依赖与你选的模型。唤醒词走这一份，不替你改大小</span>
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
    const mark = a.kind === kind
      ? (kind === 'tts' ? ' · 适合配音' : kind === 'stt' ? ' · 适合转写' : ' · 适合生图')
      : '';
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
  if (!prompt) {
    if (kind === 'tts') prompt = '帮我接上配音。先看工坊有没有现成的；没有就建一个应用。带我去官网拿 Key，不要登录、不要编造。Key 写进应用后，告诉我回设置里把它选成默认。';
    else if (kind === 'stt') prompt = '帮我接上云端语音识别。先看工坊有没有现成的转写应用；没有就建一个。带我去官网拿 Key，不要登录、不要编造。Key 写进应用后，告诉我回设置→多模态把它选成默认。没接就继续用本机 whisper。';
    else prompt = '帮我接上生图。先看工坊有没有现成的；没有就建一个应用。带我去官网拿 Key，不要登录、不要编造。Key 写进应用后，告诉我回设置里把它选成默认。';
  }
  const label = kind === 'tts' ? '接入语音合成' : kind === 'stt' ? '接入语音识别' : '接入生图';
  if (typeof backToChat === 'function') try { backToChat(); } catch (_) {}
  if (typeof closeModal === 'function') try { closeModal(); } catch (_) {}
  if (_currentTopicHasTalk()) await _mediaGuideNewTopic(prompt, label);
  else _mediaGuideStayHere(prompt);
}

async function loadMediaDefaults() {
  const host = document.getElementById('mediaCaps');
  if (!host) return;
  let d = { apps: [], image: {}, tts: {}, stt: {} };
  try {
    const r = await fetch('/media-defaults', { headers: { 'Authorization': 'Bearer ' + token } });
    if (r.ok) d = await r.json();
  } catch (_) {}
  const img = d.image || {};
  const tts = d.tts || {};
  const stt = d.stt || {};
  const apps = d.apps || [];
  const imgOk = !!img.ready;
  const ttsOk = !!tts.ready;
  const sttOk = !!stt.ready;
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
    <div class="llm-section" style="margin-top:18px">
      <div class="llm-section-head">
        <h3><i class="ri-mic-2-fill"></i> 语音识别 · ${sttOk ? '<span style="color:#6ed27a">已装载 ✓</span>' : '<span style="color:var(--sys)">未接入 · 用本机 whisper</span>'}</h3>
        <span class="llm-hint">和配音一样，愿意接云端就接。整句走 API；唤醒词仍用下面你选的本地模型。没接不影响现有功能。</span>
      </div>
      <div class="field-hint">接上之后可以用：</div>
      <ul class="field-hint" style="margin:4px 0 10px 1.2em">${_mediaUnlocks(stt.unlocks)}</ul>
      <div class="field">
        <label>默认语音识别应用</label>
        <select id="mediaSttApp" style="max-width:360px">${_mediaAppOptions(apps, stt.app_id || '', 'stt')}</select>
      </div>
      <div class="actions" style="margin-top:10px">
        <button class="btn-ghost" type="button" id="mediaSttGuide"><i class="ri-compass-3-line"></i> 帮我接入</button>
        <span class="field-hint">当前对话是空的就在这儿接入；正在聊别的会新开一个对话</span>
      </div>
      <div id="mediaSttNote" style="margin-top:8px;font-size:13px"></div>
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
  bindPin('mediaSttApp', 'stt', 'mediaSttNote');
  const ig = document.getElementById('mediaImageGuide');
  if (ig) ig.onclick = () => startMediaGuide('image');
  const tg = document.getElementById('mediaTtsGuide');
  if (tg) tg.onclick = () => startMediaGuide('tts');
  const sg = document.getElementById('mediaSttGuide');
  if (sg) sg.onclick = () => startMediaGuide('stt');
}

// ─── wish-241e0014 · 本地 whisper (可选 · 开关驱动安装) ───
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
        启用本地 whisper
      </label>
      <div class="field-hint">本机 faster-whisper，按你选的大小来，现在是 <b>${escHtml(st.model_name || '')}</b>。不替你换成别的。<br>桌宠叫名字、以及没接云端时的整句 / 微信转写，都用这一只。接了云端 API，整句走云，唤醒仍用你选的这只。<br>工作台 / 房间浏览器听环不靠它。</div>
    </div>
    <div class="field">
      <label>模型大小</label>
      <select id="sttModelSize" style="max-width:220px">
        <option value="tiny" ${st.model_name === 'tiny' ? 'selected' : ''}>tiny · ~75MB · 最快最省</option>
        <option value="base" ${st.model_name === 'base' ? 'selected' : ''}>base · ~150MB · 均衡</option>
        <option value="small" ${st.model_name === 'small' ? 'selected' : ''}>small · ~460MB · 更大更准</option>
      </select>
      <div class="field-hint">换大小只在你点选之后生效，并要下载对应模型。没下好不会拿旧模型顶替</div>
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
      await loadSttConfig();
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
        $res.innerHTML = '<span style="color:#6ed27a"><i class="ri-check-fill"></i> 本地 whisper 已就绪 · 微信转写与桌宠语音唤醒可用</span>';
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
  const processExpand = (typeof chatProcessExpanded === 'function') && chatProcessExpanded();
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

      <div class="llm-section-head" style="margin-top:18px"><h3><i class="ri-expand-up-down-line"></i> 对话过程密度</h3></div>
      <div class="field">
        <label>思考链和过程卡片</label>
        <select id="accProcessIn">
          <option value="fold" ${processExpand ? '' : 'selected'}>默认折叠 · 一行摘要，点开再看</option>
          <option value="expand" ${processExpand ? 'selected' : ''}>默认展开 · 思考和卡片都摊开</option>
        </select>
        <div class="field-hint">只影响工作台对话栏。折叠是现在这样；展开是改密度之前那种过程全看得见。当场改，不用刷新。你点开或折上的这一轮按你点的来。</div>
      </div>

      <div class="llm-section-head" style="margin-top:18px"><h3><i class="ri-brain-line"></i> 记忆整理线</h3></div>
      <div class="field">
        <label>长到多少就开始整理旧对话（tokens）</label>
        <input id="accCapIn" type="number" min="40000" step="10000" placeholder="留空 = 用系统缺省">
        <div class="field-hint">超过这条线，最久远的对话会被压成摘要。填大 = 记得久但每一轮更贵；填小 = 省钱但容易忘。系统下限 40,000。</div>
        <div class="field-hint" id="accCapLive">读取中…</div>
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
        把命令头加到信任清单后·窗口期内 OPUS 调这类命令自动通过。
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
        <button class="btn-primary" onclick="addTrustedCommand()">+ 加入</button>
      </div>
      <div id="accTrustList" class="field-hint" style="margin-top:8px;font-size:12px">加载中…</div>

      <div class="actions" style="margin-top:18px">
        <button class="btn-primary" onclick="saveAccessSettings()">保存</button>
      </div>
      <div id="accSaveStatus" class="field-hint" style="margin-top:6px"></div>
    </div>
  `;
  const processSel = document.getElementById('accProcessIn');
  if (processSel) {
    processSel.onchange = () => {
      if (typeof setChatProcessMode === 'function') setChatProcessMode(processSel.value);
    };
  }
  // 异步刷一次 trusted 列表
  setTimeout(() => { try { refreshTrustedCommands(); } catch {} }, 50);
  // 0.9.x · 读当前记忆整理线 (当场生效 · 不用重启)
  setTimeout(() => { try { loadCompactCap(); } catch {} }, 50);
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
      target.innerHTML = '<i>暂无 trusted commands · OPUS 调 CONFIRM 档命令时会被 auto_confirm 策略卡住</i>';
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
  const processSel = document.getElementById('accProcessIn');
  if (processSel && typeof setChatProcessMode === 'function') setChatProcessMode(processSel.value);
  if (typeof updateCurrentLabel === 'function') updateCurrentLabel();
  if (typeof saveSid === 'function') saveSid(sessionId);
  const capInp = document.getElementById('accCapIn');
  if (capInp) { try { saveCompactCap(capInp.value); } catch {} }
  document.getElementById('accSaveStatus').innerHTML = '<i class="ri-check-fill"></i> 已保存 · ' + (token ? '可以聊了' : '⚠ token 为空');
  document.getElementById('accSaveStatus').className = 'field-hint ok';
  // 同步刷新右上角模型切换器
  if (typeof loadCurrentModel === 'function') loadCurrentModel();
}

// 0.9.x · 记忆整理线 (压缩绝对线) · 「访问 & 会话」面板
// 原先只有 env OPUS_AUTO_COMPACT_MAX_TOKENS 一条路 · 用户看不到也改不了 (BRO 2026-09-14 指出)
async function loadCompactCap() {
  const live = document.getElementById('accCapLive');
  const inp = document.getElementById('accCapIn');
  if (!live || !inp) return;
  try {
    const r = await fetch('/api/settings/compact-cap', {
      headers: { Authorization: 'Bearer ' + token },
    });
    const d = await r.json();
    if (d && d.ok) {
      inp.value = d.abs_cap;
      const src = d.source === 'webui' ? '你设的'
        : (d.source === 'env' ? '.env 里的' : '系统缺省');
      live.innerHTML = '<i class="ri-information-line"></i> 真实生效线 <b>'
        + Number(d.effective != null ? d.effective : d.abs_cap).toLocaleString() + '</b> tokens'
        + '（你设的整理线 ' + Number(d.abs_cap).toLocaleString() + ' · 来源：' + src
        + '）· 下限 ' + Number(d.floor).toLocaleString() + compactCapNote(d);
    }
  } catch (e) {
    live.textContent = '读取失败 · ' + e;
  }
}

async function saveCompactCap(v) {
  const live = document.getElementById('accCapLive');
  const num = String(v == null ? '' : v).trim() === '' ? 0 : (parseInt(v, 10) || 0);
  try {
    const r = await fetch('/api/settings/compact-cap', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
      body: JSON.stringify({ value: num }),
    });
    const d = await r.json();
    if (!live) return;
    if (d && d.ok) {
      // 存完重拉一次：POST 只回 abs_cap，真实生效线要 GET 才算得出（窗口那道闸）
      await loadCompactCap();
      const el = document.getElementById('accCapIn');
      if (el) el.value = d.abs_cap;
    } else {
      live.textContent = '保存失败';
    }
  } catch (e) {
    if (live) live.textContent = '保存失败 · ' + e;
  }
}

// 记忆整理线：为什么真实生效值 ≠ 你设的值（窗口×ratio 这道闸更靠前）
function compactCapNote(d) {
  if (!d || d.effective == null) return '';
  if (d.bounded_by === 'window') {
    return '<br><i class="ri-arrow-right-s-line"></i> 被上下文窗口压住：'
      + Number(d.ctx_window).toLocaleString() + ' × ' + d.ratio + ' = '
      + Number(d.window_line).toLocaleString()
      + ' tokens（窗口这道闸在你的整理线之前）· 当前模型 ' + (d.model || '未知');
  }
  if (d.bounded_by === 'prefix') {
    return '<br><i class="ri-arrow-right-s-line"></i> 系统提示词（'
      + Number(d.prefix || 0).toLocaleString()
      + ' tokens）已超窗口线 · 压历史救不了 · 改走绝对线 '
      + Number(d.abs_cap).toLocaleString();
  }
  return '<br><i class="ri-arrow-right-s-line"></i> 由你的整理线决定（窗口线 '
    + Number(d.window_line || 0).toLocaleString() + ' 还没到）· 当前模型 ' + (d.model || '未知');
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
          <div class="chan-info-bar warn"><i class="ri-time-line"></i> <b>24 小时窗口</b>：你在微信先发一句 → 开窗 · 窗口内 OPUS 能主动找你 · 跨天零互动发不出（腾讯反骚扰）</div>
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
  const gen = _settingsPaintGen;
  const body = document.getElementById('settingsBody');
  if (!_settingsStill('notify', gen) || !body) return;
  body.innerHTML = '<div class="dash-empty">加载中…</div>';

  let cfg = { pet_sound: true, windows_toast: false, tab_flash: false };
  try {
    const resp = await fetch('/notification-config', { headers: { 'Authorization': 'Bearer ' + token } });
    if (resp.ok) cfg = await resp.json();
  } catch (_) {}
  if (!_settingsStill('notify', gen)) return;

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

// ─── wish-7f38376e · 掘金雷达设置面板 ───
// 后台自动刷新的开关与频率 · 存 data/radar_config.json · scheduler 每 10s 热读 → 改完不用重启
const _RADAR_INTERVAL_OPTIONS = [
  [30, '每 30 分钟'],
  [60, '每 1 小时'],
  [120, '每 2 小时'],
  [360, '每 6 小时'],
  [720, '每 12 小时'],
  [1440, '每天'],
];

function _radarTs(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    const p = n => String(n).padStart(2, '0');
    return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  } catch (_) {
    return String(iso);
  }
}

async function renderSettingsRadar() {
  const gen = _settingsPaintGen;
  const body = document.getElementById('settingsBody');
  if (!_settingsStill('radar', gen) || !body) return;
  body.innerHTML = '<div class="dash-empty">加载中…</div>';

  let data = { config: { enabled: true, interval_min: 30 }, runtime: {} };
  try {
    const resp = await fetch('/radar-config', { headers: { 'Authorization': 'Bearer ' + token } });
    if (resp.ok) data = await resp.json();
  } catch (_) {}
  if (!_settingsStill('radar', gen)) return;

  const cfg = data.config || {};
  const rt = data.runtime || {};
  const curInterval = Number(cfg.interval_min) || 30;
  const opts = _RADAR_INTERVAL_OPTIONS.slice();
  if (!opts.some(o => o[0] === curInterval)) opts.push([curInterval, `每 ${curInterval} 分钟`]);
  opts.sort((a, b) => a[0] - b[0]);

  const lastLine = rt.last_run_at
    ? `${_radarTs(rt.last_run_at)} 那轮${rt.last_run_ok === false ? '没跑成' : `抓到 ${rt.last_run_items == null ? 0 : rt.last_run_items} 条`}`
    : '还没跑过';
  const nextLine = cfg.enabled
    ? (rt.next_run_at ? _radarTs(rt.next_run_at) : '—')
    : '已关闭 · 不跑';

  body.innerHTML = `
    <div class="llm-section">
      <div class="llm-section-head">
        <h3><i class="ri-radar-fill"></i> 掘金雷达 · 后台自动刷新</h3>
        <span class="llm-hint">关掉就不抓 · 手动「抓一下雷达」仍然可用</span>
      </div>
      <div class="field">
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
          <input type="checkbox" id="rdrEnabled" ${cfg.enabled ? 'checked' : ''}>
          <span><i class="ri-refresh-line"></i> 自动刷新雷达</span>
        </label>
        <div class="field-hint">开着时后台按下面的频率去刷信息源 · 关掉后完全不跑 · 不再有 token 消耗。</div>
      </div>
      <div class="field">
        <label><i class="ri-time-line"></i> 刷新频率</label>
        <select id="rdrInterval">
          ${opts.map(o => `<option value="${o[0]}" ${o[0] === curInterval ? 'selected' : ''}>${o[1]}</option>`).join('')}
        </select>
      </div>
      <div class="field">
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
          <input type="checkbox" id="rdrTranslate" ${cfg.translate !== false ? 'checked' : ''}>
          <span><i class="ri-translate-2"></i> 翻译新条目标题</span>
        </label>
        <div class="field-hint">这是整条链唯一花 token 的一步（一轮就几百 token）· 关掉后雷达照抓、标题留英文原文。</div>
      </div>
      <div class="field">
        <label><i class="ri-history-line"></i> 现在这样</label>
        <div class="field-hint" style="line-height:1.8">
          上次刷新：${escHtml(lastLine)}<br>
          下次刷新：${escHtml(nextLine)}<br>
          累计自动跑了 ${rt.runs_completed == null ? 0 : rt.runs_completed} 轮
        </div>
      </div>
      <div class="actions" style="margin-top:12px">
        <button class="btn-primary" id="rdrSave"><i class="ri-save-fill"></i> 保存</button>
      </div>
      <div id="rdrResult" style="margin-top:8px;font-size:13px"></div>
    </div>
  `;

  document.getElementById('rdrSave').onclick = async () => {
    const resEl = document.getElementById('rdrResult');
    resEl.innerHTML = '<span style="color:var(--sys)"><i class="ri-loader-fill"></i> 保存中…</span>';
    try {
      const resp = await fetch('/radar-config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
        body: JSON.stringify({
          enabled: document.getElementById('rdrEnabled').checked,
          interval_min: parseInt(document.getElementById('rdrInterval').value, 10) || 30,
          translate: document.getElementById('rdrTranslate').checked,
        }),
      });
      const out = await resp.json();
      if (!resp.ok) {
        resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-error-warning-fill"></i> ${escHtml(out.detail || '保存失败')}</span>`;
        return;
      }
      resEl.innerHTML = `<span style="color:#6ed27a"><i class="ri-check-fill"></i> ${escHtml(out.note || '已保存')}</span>`;
    } catch (e) {
      resEl.innerHTML = `<span style="color:var(--red)"><i class="ri-close-fill"></i> ${escHtml(e.message)}</span>`;
    }
  };
}

function renderSettingsData() {
  const body = document.getElementById('settingsBody');
  body.innerHTML = `<div id="ldUsage" class="field-hint">正在扫磁盘… 文件多时要几秒，扫完还在这一页，不会跳走。</div>`;
  loadLocalDataUsage();
}

let _ldLoadGen = 0;
function _ldStillHere(gen) {
  if (gen != null && gen !== _ldLoadGen) return false;
  if (typeof currentView !== 'undefined' && currentView !== 'settings') return false;
  if (_settingsTab !== 'data') return false;
  return !!document.getElementById('ldUsage');
}

async function loadLocalDataUsage() {
  const gen = ++_ldLoadGen;
  const box = document.getElementById('ldUsage');
  if (!box) return;
  try {
    const resp = await fetch('/local-data', { headers: { 'Authorization': 'Bearer ' + token } });
    const data = await resp.json();
    if (!_ldStillHere(gen)) return;
    if (!resp.ok) {
      box.innerHTML = '<span style="color:var(--red)"><i class="ri-error-warning-fill"></i> ' + escHtml(data.detail || '扫盘失败') + '</span>';
      return;
    }
    paintLocalDataUsage(data);
  } catch (e) {
    if (!_ldStillHere(gen)) return;
    box.innerHTML = '<span style="color:var(--red)"><i class="ri-close-fill"></i> ' + escHtml(e.message) + '</span>';
  }
}

const LD_COLORS = {
  workshop_outputs: '#7c5cbf',
  sessions: '#e07a5f',
  presentations: '#4ea8d9',
  shelf_preview: '#6bbf8a',
  attachments: '#d4a373',
  design: '#5c9ead',
  scratch: '#9aa0a6',
  reports: '#8b7ec8',
  cache: '#6b7280',
  spreadsheets: '#3d9b8f',
  workshop_exports: '#c4b5fd',
  _other: '#64748b',
};

function _ldHuman(n) {
  n = Math.max(0, Number(n) || 0);
  if (n >= 1073741824) return (n / 1073741824).toFixed(1) + ' GB';
  if (n >= 1048576) return (n / 1048576).toFixed(1) + ' MB';
  if (n >= 1024) return (n / 1024).toFixed(1) + ' KB';
  return n + ' B';
}

function paintLocalDataUsage(data) {
  const box = document.getElementById('ldUsage');
  if (!box) return;
  const buckets = (data.buckets || []).slice().sort((a, b) => (b.bytes || 0) - (a.bytes || 0));
  const totalBytes = buckets.reduce((s, b) => s + (b.bytes || 0), 0);
  const stack = totalBytes
    ? buckets.filter((b) => b.bytes > 0).map((b) => {
        const color = LD_COLORS[b.id] || '#888';
        return `<span class="ld-stack-slice" style="flex:${b.bytes};background:${color}" title="${escHtml(b.label)} ${escHtml(b.size || '')}"></span>`;
      }).join('')
    : '';
  const rows = buckets.map((b) => {
    const color = LD_COLORS[b.id] || '#888';
    const danger = b.danger ? ' ld-row-danger' : '';
    const checked = b.suggest ? ' checked' : '';
    const warn = b.danger ? '<i class="ri-error-warning-line" title="清了找不回"></i>' : '';
    return `<label class="ld-row${danger}" title="${escHtml(b.hint || '')}">
      <span class="ld-name"><i class="ld-dot" style="background:${color}"></i>${escHtml(b.label)}${warn}</span>
      <span class="ld-count">${Number(b.files || 0).toLocaleString('zh-CN')}</span>
      <span class="ld-size">${escHtml(b.size || '0 B')}</span>
      <input type="checkbox" class="ld-pick" value="${escHtml(b.id)}" data-label="${escHtml(b.label)}" data-size="${escHtml(b.size || '')}" data-danger="${b.danger ? '1' : '0'}"${checked}>
    </label>`;
  }).join('');
  const html = `
    <div class="llm-section ld-section">
      <div class="llm-section-head">
        <h3><i class="ri-magic-line"></i> 智能清理 · 临时文件</h3>
        <span class="llm-hint">扫一眼根目录和 data/ 里堆着的临时件（日志、临时脚本、开发时留下的源码拷），自动判哪条能删、哪条该留。清掉的东西先搬进回收站，找得回。</span>
      </div>
      <div class="actions"><button type="button" class="btn-primary" id="ldTempScan"><i class="ri-radar-line"></i> 扫一遍看看</button></div>
      <div id="ldTempBox"></div>
      <div class="ld-trash-bar">
        <button type="button" class="btn-ghost" id="ldTrashBtn"><i class="ri-delete-bin-6-line"></i> 回收站</button>
        <span class="llm-hint" id="ldTrashHint">清掉的东西都先放这儿 · 30 天后自动清 · 也能现在就清掉</span>
      </div>
      <div id="ldTrashBox"></div>
    </div>
    <div class="llm-section ld-section">
      <div class="llm-section-head">
        <h3><i class="ri-hard-drive-2-line"></i> 磁盘占用 · ${escHtml(data.total_size || '0 B')} · ${Number(data.total_files || 0).toLocaleString('zh-CN')} 个文件</h3>
        <span class="llm-hint">勾选再清。灵魂、应用配方、知识库不在这里。</span>
      </div>
      ${stack ? `<div class="ld-stack">${stack}</div>` : ''}
      <div class="ld-table">
        <div class="ld-thead"><span>类别</span><span>文件</span><span>占用</span><span>清</span></div>
        <div class="ld-list">${rows}</div>
      </div>
      <div class="ld-bar">
        <button type="button" class="btn-ghost" id="ldSuggest">只勾缓存</button>
        <button type="button" class="btn-ghost" id="ldNone">取消全选</button>
        <span class="ld-bar-gap"></span>
        <button type="button" class="btn-danger" id="ldPurge"><i class="ri-delete-bin-line"></i> 清理选中的</button>
      </div>
    </div>
    <div class="llm-section">
      <div class="llm-section-head">
        <h3><i class="ri-window-line"></i> 浏览器缓存</h3>
        <span class="llm-hint">只清草稿和界面状态。WebUI 密码和当前对话不动，不用重填。</span>
      </div>
      <div class="actions">
        <button type="button" class="btn-ghost" id="ldBrowserClear">清理浏览器缓存</button>
      </div>
    </div>
    <div id="ldResult" class="field-hint"></div>
  `;
  const body = document.getElementById('settingsBody');
  if (body) body.innerHTML = `<div id="ldUsage">${html}</div>`;
  else { box.className = ''; box.innerHTML = html; }
  const root = document.getElementById('ldUsage') || box;
  const suggest = document.getElementById('ldSuggest');
  if (suggest) suggest.onclick = () => {
    root.querySelectorAll('.ld-pick').forEach((el) => {
      const spec = (data.buckets || []).find((b) => b.id === el.value);
      el.checked = !!(spec && spec.suggest);
    });
  };
  const none = document.getElementById('ldNone');
  if (none) none.onclick = () => root.querySelectorAll('.ld-pick').forEach((el) => { el.checked = false; });
  const btn = document.getElementById('ldPurge');
  if (btn) btn.onclick = () => purgeLocalDataPicks();
  const br = document.getElementById('ldBrowserClear');
  if (br) br.onclick = () => resetAll();
  const ts = document.getElementById('ldTempScan');
  if (ts) ts.onclick = () => ldTempStart();
  const tb = document.getElementById('ldTrashBtn');
  if (tb) tb.onclick = () => ldTrashToggle();
  ldTempInit();   // 每次进这一页都先照一次镜子：后端什么状态，这里就显示什么
  ldTrashRefresh();
}

/* ── 回收站（2026-10-01 补）──────────────────────────────
   智能清理和知识库删档搬走的东西都落在 data/runtime/trash/<批次>/。
   之前只有往里写的口，没有往外的 —— 挪进去就既看不见也清不掉。 */
let _ldTrashOpen = false;

async function ldTrashRefresh() {
  let d = null;
  try {
    const r = await fetch('/local-data/trash', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    d = await r.json();
    if (!d || typeof d.count !== 'number') throw new Error('返回格式不对');
  } catch (e) {
    // 不能静默 —— 否则 401/500 会被当成「回收站是空的」，用户以为清干净了
    const h = document.getElementById('ldTrashHint');
    if (h) h.innerHTML = '<span style="color:var(--red)"><i class="ri-error-warning-fill"></i> 回收站信息获取失败，请重试</span>';
    return null;
  }
  const h = document.getElementById('ldTrashHint');
  if (h) {
    h.textContent = d.count
      ? (d.count + ' 批 · ' + d.total_files + ' 个文件 · ' + d.total_size + ' · 30 天后自动清')
      : '空的 · 清掉的东西会先放这儿，30 天后自动清';
  }
  if (_ldTrashOpen) ldTrashRender(d);
  return d;
}

function ldTrashToggle() {
  _ldTrashOpen = !_ldTrashOpen;
  const box = document.getElementById('ldTrashBox');
  if (!_ldTrashOpen) { if (box) box.innerHTML = ''; return; }
  ldTrashRefresh();
}

function ldTrashRender(d) {
  const box = document.getElementById('ldTrashBox');
  if (!box) return;
  if (!d || !d.count) { box.innerHTML = '<div class="ld-trash-empty">回收站是空的</div>'; return; }
  box.innerHTML = `<div class="ld-trash-list">`
    + d.batches.map((b) => `<div class="ld-trash-batch">
        <div class="ld-trash-top">
          <b>${escHtml(b.batch)}</b>
          <span>${b.files} 个 · ${escHtml(b.size)} · ${b.left_days} 天后自动清</span>
          <button type="button" class="btn-ghost" onclick="ldTrashRestore('${escHtml(jsStr(b.batch))}')">还原</button>
          <button type="button" class="btn-ghost ld-del" onclick="ldTrashEmpty('${escHtml(jsStr(b.batch))}')">清掉</button>
        </div>
        <div class="ld-trash-items">${b.items.slice(0, 6).map(escHtml).join(' · ')}${b.items.length > 6 ? ' …' : ''}</div>
      </div>`).join('')
    + `</div><div class="ld-trash-foot">
        <button type="button" class="btn-ghost ld-del" onclick="ldTrashEmpty('')">全部清空（${escHtml(d.total_size)}）</button>
      </div>`;
}

async function ldTrashRestore(batch) {
  const d = await ldTrashRefresh();
  const b = (d && d.batches || []).find((x) => x.batch === batch);
  if (!b || !b.items.length) return;
  try {
    const r = await fetch('/local-data/trash/restore', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ items: b.items.map((x) => batch + '/' + x) }),
    });
    const j = await r.json();
    if (typeof showChatToast === 'function') {
      showChatToast('还原 ' + (j.moved || 0) + ' 个' + (j.errors && j.errors.length ? ' · ' + j.errors[0] : ''));
    }
    await ldTrashRefresh();
  } catch (e) { /* 静默 · 下面的刷新会把真相带回来 */ }
}

async function ldTrashEmpty(batch) {
  const what = batch ? ('这一批（' + batch + '）') : '整个回收站';
  if (!window.confirm('确定永久删掉' + what + '？找不回了。')) return;
  try {
    const r = await fetch('/local-data/trash/empty', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify(batch ? { batch } : {}),
    });
    const j = await r.json();
    if (typeof showChatToast === 'function') showChatToast('清掉 ' + (j.batches_removed || 0) + ' 批 · 腾出 ' + (j.freed_size || '0 B'));
    await ldTrashRefresh();
  } catch (e) { /* 同上 */ }
}

async function purgeLocalDataPicks() {
  const picks = [...document.querySelectorAll('.ld-pick:checked')];
  const resEl = document.getElementById('ldResult');
  if (!picks.length) {
    if (resEl) resEl.innerHTML = '<span style="color:var(--red)">先勾要清的类别</span>';
    return;
  }
  const danger = picks.filter((el) => el.dataset.danger === '1');
  const lines = picks.map((el) => el.dataset.label + ' · ' + el.dataset.size).join('\n');
  const ok = await opusConfirm({
    title: danger.length ? '清掉选中的（含对话记录）' : '清掉选中的',
    message: '会从这台电脑删掉：\n' + lines + (danger.length ? '\n\n对话记录清了找不回。' : ''),
    okText: '删',
    cancelText: '再想想',
    danger: true,
  });
  if (!ok) return;
  if (resEl) resEl.innerHTML = '<span style="color:var(--sys)"><i class="ri-loader-fill"></i> 清理中…</span>';
  try {
    const resp = await fetch('/local-data/purge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify({ ids: picks.map((el) => el.value) }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      if (resEl) resEl.innerHTML = '<span style="color:var(--red)"><i class="ri-error-warning-fill"></i> ' + escHtml(data.detail || '清理失败') + '</span>';
      return;
    }
    if (data.usage) paintLocalDataUsage(data.usage);
    const after = document.getElementById('ldResult');
    if (after) after.innerHTML = '<span style="color:#6ed27a"><i class="ri-check-fill"></i> 已清 ' + escHtml(String(data.deleted || 0)) + ' 个文件 · 腾出 ' + escHtml(data.freed_size || '0 B') + '</span>';
  } catch (e) {
    if (resEl) resEl.innerHTML = '<span style="color:var(--red)"><i class="ri-close-fill"></i> ' + escHtml(e.message) + '</span>';
  }
}

async function resetAll() {
  const ok = await opusConfirm({
    title: '清理浏览器缓存',
    message: '只清草稿和界面临时状态。\nWebUI 密码和当前对话不动，不用重填，也不会跳出这一页。',
    okText: '清缓存',
    cancelText: '再想想',
  });
  if (!ok) return;
  const keep = new Set([
    'opus_ui_token', 'Daemonkey_ui_token',
    'opus_ui_session', 'opus_ui_auto_confirm',
    'opus_chat_process',
    'opus_ui_theme', 'opus_ui_theme_custom', 'opus_ui_theme_label',
  ]);
  const keys = [];
  for (let i = 0; i < localStorage.length; i++) keys.push(localStorage.key(i));
  keys.forEach((k) => { if (k && !keep.has(k)) localStorage.removeItem(k); });
  const after = document.getElementById('ldResult');
  if (after) after.innerHTML = '<span style="color:#6ed27a"><i class="ri-check-fill"></i> 浏览器缓存已清 · 密码还在</span>';
}

// ─── wish-9d30a22e · 临时件智能清理（扫 → 判 → 勾 → 回收站 / 真删）───
//
// 状态活在 data/runtime/temp_scan.json（后端），前端只是它的镜子 ——
// 所以「扫到一半切走再回来」「扫完切走再回来」看到的都是同一份进度/结果。

let _clTimer = null;
let _clTick = null;

function _clStopAll() {
  if (_clTimer) { clearInterval(_clTimer); _clTimer = null; }
  if (_clTick) { clearInterval(_clTick); _clTick = null; }
}

function _clSize(bytes) {
  bytes = parseInt(bytes, 10) || 0;
  if (bytes >= 1048576) return (bytes / 1048576).toFixed(1) + ' MB';
  if (bytes >= 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return bytes + ' B';
}

async function _clStatus() {
  try {
    const r = await fetch('/local-data/temp-scan', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) return null;
    return await r.json();
  } catch (e) { return null; }
}

function _clPollStart() {
  _clStopAll();
  _clTimer = setInterval(async () => {
    if (!document.getElementById('ldTempBox')) { _clStopAll(); return; }   // 切走了就停 · 后端照跑
    const st = await _clStatus();
    if (!st) return;
    _clRender(st);
    if (st.status !== 'running') _clStopAll();
  }, 3000);
}

// 进这一页时调 —— 后端的进行中/已完成，在这儿如实还原
async function ldTempInit() {
  _clStopAll();
  const st = await _clStatus();
  if (!st) return;
  _clRender(st);
  if (st.status === 'running') _clPollStart();
}

async function ldTempStart() {
  const btn = document.getElementById('ldTempScan');
  if (btn) { btn.disabled = true; btn.innerHTML = '<i class="ri-loader-fill ld-spin"></i> 正在起…'; }
  let st = { status: 'error', error: '请求没发出去' };
  try {
    const r = await fetch('/local-data/temp-scan', { method: 'POST', headers: { 'Authorization': 'Bearer ' + token } });
    st = r.ok ? await r.json() : { status: 'error', error: (await r.json()).detail || '起不来' };
  } catch (e) { st = { status: 'error', error: e.message }; }
  if (btn) { btn.disabled = false; btn.innerHTML = '<i class="ri-radar-line"></i> 再扫一遍'; }
  _clRender(st);
  if (st.status === 'running') _clPollStart();
}

function _clRender(st) {
  const box = document.getElementById('ldTempBox');
  if (!box) return;
  _clStopAll();
  const status = (st && st.status) || 'idle';

  if (status === 'running') {
    const t0 = st.started_at ? new Date(String(st.started_at).replace('T', ' ')).getTime() : 0;
    const sec = t0 ? Math.max(0, Math.round((Date.now() - t0) / 1000)) : 0;
    box.innerHTML = `<div class="ld-running">
      <div class="ld-run-h"><i class="ri-loader-fill ld-spin"></i> ${escHtml(st.step || '正在扫…')}</div>
      <div class="ld-run-bar"><i id="clRunBar" style="width:${Math.min(95, sec / 120 * 100)}%"></i></div>
      <div class="ld-run-f">已经跑了 <b id="clRunSec">${sec}</b> 秒 · 实测一~三分钟（看模型响应快慢）。
        放心切走 —— 它在后台跑，回来还是这一页。</div>
    </div>`;
    _clTick = setInterval(() => {
      const el = document.getElementById('clRunSec');
      if (!el) { _clStopAll(); return; }
      const n = (parseInt(el.textContent, 10) || 0) + 1;
      el.textContent = String(n);
      const bar = document.getElementById('clRunBar');
      if (bar) bar.style.width = Math.min(95, n / 120 * 100) + '%';
    }, 1000);
    return;
  }

  if (status === 'error') {
    box.innerHTML = `<div class="ld-err"><i class="ri-error-warning-fill"></i> ${escHtml(st.error || '扫失败了')}
      · 可以再点一次「再扫一遍」</div>`;
    return;
  }

  if (status === 'done' && st.result) { paintTempForm(st.result, st); return; }

  box.innerHTML = '<div class="field-hint" style="margin-top:10px">还没扫过 —— 点上面「扫一遍看看」，它会列出堆在目录里的临时件，逐条说明是什么、能不能删。</div>';
}

function _clRow(it) {
  const tag = it.keep
    ? '<span class="ld-tag keep"><i class="ri-shield-check-line"></i> 建议留</span>'
    : '<span class="ld-tag drop' + (it.risk === 'high' ? ' risky' : '') + '"><i class="ri-delete-bin-6-line"></i> 建议清</span>';
  const why = [it.what, it.reason].filter(Boolean).join(' · ');
  return `<label class="ld-row">
    <input type="checkbox" class="ld-pick" value="${escHtml(it.id)}" data-bytes="${escHtml(String(it.bytes || 0))}" data-size="${escHtml(it.size || '')}" data-path="${escHtml(it.path)}"${it.keep ? '' : ' checked'}>
    <span class="ld-main">
      <span class="ld-pathline"><code>${escHtml(it.path)}</code>${tag}<span class="ld-size">${escHtml(it.size || '')}</span></span>
      <span class="ld-why">${escHtml(why || '（没给说明）')}</span>
    </span>
  </label>`;
}

function paintTempForm(d, st) {
  const box = document.getElementById('ldTempBox');
  if (!box) return;
  const items = d.items || [];
  if (!items.length) {
    box.innerHTML = '<div class="field-hint" style="margin-top:10px">没扫到可以清理的临时件 —— 挺干净的。</div>';
    return;
  }
  const dropItems = items.filter((x) => !x.keep);
  const keepItems = items.filter((x) => x.keep);
  const dropBytes = dropItems.reduce((s, x) => s + (parseInt(x.bytes, 10) || 0), 0);
  const when = String((st && st.finished_at) || '').replace('T', ' ');

  box.innerHTML = `
    <div class="ld-head">
      共 <b>${items.length}</b> 条候选 · 建议清 <b class="ld-warn">${dropItems.length}</b> 条
      <em>（${escHtml(_clSize(dropBytes))}）</em>
      ${when ? `<span class="ld-when">扫于 ${escHtml(when)}</span>` : ''}
    </div>
    <div class="ld-groups">
      <details class="ld-group" open>
        <summary><i class="ri-delete-bin-6-line"></i> 建议清理
          <em>${dropItems.length} 条 · ${escHtml(_clSize(dropBytes))}</em></summary>
        <div class="ld-list">${dropItems.map(_clRow).join('')}</div>
      </details>
      ${keepItems.length ? `<details class="ld-group">
        <summary><i class="ri-shield-check-line"></i> 建议保留 <em>${keepItems.length} 条</em></summary>
        <div class="ld-list">${keepItems.map(_clRow).join('')}</div>
      </details>` : ''}
    </div>
    <div class="ld-actbar">
      <span class="ld-picked" id="clPicked">已勾 0 项 · 0 B</span>
      <span class="ld-bar-gap"></span>
      <button type="button" class="btn-ghost" id="clSuggest">只勾建议清</button>
      <button type="button" class="btn-ghost" id="clNone">全不勾</button>
      <button type="button" class="btn-ghost" id="clToTrash"><i class="ri-archive-line"></i> 移到回收站</button>
      <button type="button" class="btn-danger" id="clDelete"><i class="ri-delete-bin-2-line"></i> 永久删除</button>
    </div>
    <div id="clConfirm"></div>
    <div id="clResult" class="field-hint"></div>
  `;

  const $ = (id) => document.getElementById(id);
  if ($('clSuggest')) $('clSuggest').onclick = () => {
    box.querySelectorAll('.ld-pick').forEach((el) => {
      const it = items.find((x) => x.id === el.value);
      el.checked = !!(it && !it.keep);
    });
    _clPicked();
  };
  if ($('clNone')) $('clNone').onclick = () => {
    box.querySelectorAll('.ld-pick').forEach((el) => { el.checked = false; });
    _clPicked();
  };
  if ($('clToTrash')) $('clToTrash').onclick = () => _clAsk('trash');
  if ($('clDelete')) $('clDelete').onclick = () => _clAsk('delete');
  box.querySelectorAll('.ld-pick').forEach((el) => { el.onchange = () => { _clPicked(); if ($('clConfirm')) $('clConfirm').innerHTML = ''; }; });
  _clPicked();
}

function _clPicked() {
  const picks = [...document.querySelectorAll('.ld-pick:checked')];
  const bytes = picks.reduce((s, el) => s + (parseInt(el.dataset.bytes, 10) || 0), 0);
  const el = document.getElementById('clPicked');
  if (el) el.textContent = '已勾 ' + picks.length + ' 项 · ' + _clSize(bytes);
  return picks;
}

// 确认不弹窗、就在原地展开一条 —— 之前把 50 行路径塞进通用弹窗才是「丑」的根源
function _clAsk(mode) {
  const cEl = document.getElementById('clConfirm');
  if (!cEl) return;
  const picks = _clPicked();
  if (!picks.length) { cEl.innerHTML = '<div class="ld-err2">先勾要清的</div>'; return; }
  const bytes = picks.reduce((s, el) => s + (parseInt(el.dataset.bytes, 10) || 0), 0);
  const n = picks.length, sz = _clSize(bytes);

  cEl.innerHTML = (mode === 'trash')
    ? `<div class="ld-confirm">
         <div class="ld-cf-t"><i class="ri-archive-line"></i>
           把勾选的 <b>${n}</b> 项（${escHtml(sz)}）搬到 <code>data/runtime/trash/</code>？
           <span>原位置会空出来，东西留在回收站里，随时能捞回来。</span></div>
         <div class="ld-cf-b">
           <button type="button" class="btn-primary" id="clCfmGo">搬过去</button>
           <button type="button" class="btn-ghost" id="clCfmNo">再想想</button>
         </div>
       </div>`
    : `<div class="ld-confirm danger">
         <div class="ld-cf-t"><i class="ri-error-warning-fill"></i>
           <b>永久删除</b>这 <b>${n}</b> 项（${escHtml(sz)}）？
           <span>直接删干净 —— 不进回收站，找不回。</span></div>
         <div class="ld-cf-b">
           <button type="button" class="btn-danger" id="clCfmGo">确认永久删除</button>
           <button type="button" class="btn-ghost" id="clCfmNo">算了</button>
         </div>
       </div>`;
  document.getElementById('clCfmNo').onclick = () => { cEl.innerHTML = ''; };
  document.getElementById('clCfmGo').onclick = () => ldTempPurge(mode);
}

async function ldTempPurge(mode) {
  const picks = [...document.querySelectorAll('.ld-pick:checked')];
  const resEl = document.getElementById('clResult');
  const cEl = document.getElementById('clConfirm');
  if (cEl) cEl.innerHTML = '';
  if (!picks.length) return;
  if (resEl) resEl.innerHTML = '<span style="color:var(--sys)"><i class="ri-loader-fill ld-spin"></i> 处理中…</span>';
  try {
    const r = await fetch('/local-data/temp-purge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify({ paths: picks.map((el) => el.value), mode: mode }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || '清理失败');
    const verb = mode === 'trash' ? '搬走' : '删掉';
    const tail = mode === 'trash'
      ? ' · 在 <code>' + escHtml(d.trash || '') + '</code>（能捞回来）'
      : ' · 已永久删除';
    picks.forEach((el) => { const row = el.closest('.ld-row'); if (row) row.remove(); });
    if (resEl) resEl.innerHTML = '<span style="color:#6ed27a"><i class="ri-check-fill"></i> '
      + verb + ' ' + escHtml(String(d.moved || 0)) + ' 项 · 腾出 ' + escHtml(d.freed_size || '0 B') + tail + '</span>';
    _clPicked();
  } catch (e) {
    if (resEl) resEl.innerHTML = '<span style="color:var(--red)"><i class="ri-close-fill"></i> ' + escHtml(e.message) + '</span>';
  }
}
