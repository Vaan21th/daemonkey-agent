/* DAIMON 陪伴模式 · 同源直连 daemon API */
'use strict';

/* ===== 状态机 ===== */
/* PS 原图零裁剪 · 每张比例不同 · ratio=宽/高 · 容器按各图比例动态定宽(人物高度全状态一致)
   footCx = 双脚水平中心占画布宽的比例 (脚底往上 3% 横条的 alpha 质心实测) ·
   影子的投射原点靠它落在脚下 · 每帧姿势不同·写死 50% 会让影子整体平移几个像素 */
const IP_FRAMES = {
  stand:      { src: 'assets/ip-stand.png',     ratio: 613 / 1408, footCx: 0.4835 },
  idle:       { src: 'assets/ip-idle.png',      ratio: 613 / 1408, footCx: 0.4835 },
  greet:      { src: 'assets/ip-greet.png',     ratio: 659 / 1406, footCx: 0.4903 },
  happy:      { src: 'assets/ip-happy.png',     ratio: 637 / 1444, footCx: 0.4823 },
  thinking:   { src: 'assets/ip-thinking.png',  ratio: 615 / 1449, footCx: 0.4725 },
  working:    { src: 'assets/ip-working.png',   ratio: 607 / 1361, footCx: 0.4887 },
  sleepy:     { src: 'assets/ip-sleepy.png',    ratio: 594 / 1413, footCx: 0.4776 },
  surprised:  { src: 'assets/ip-surprised.png', ratio: 695 / 1423, footCx: 0.4980 },
  confused:   { src: 'assets/ip-confused.png',  ratio: 653 / 1429, footCx: 0.5097 },
  care:       { src: 'assets/ip-care.png',      ratio: 625 / 1409, footCx: 0.5024 },
  sad:        { src: 'assets/ip-sad.png',       ratio: 555 / 1408, footCx: 0.4741 },
  shy:        { src: 'assets/ip-shy.png',       ratio: 569 / 1408, footCx: 0.4722 },
  puff:       { src: 'assets/ip-puff.png',      ratio: 592 / 1408, footCx: 0.4995 },
  /* spawn 画布比人物高 (猴子在她前方落地·不裁) · figureH=她的靴底行/画布高 ·
     容器按 figureH 加高·让她的脚底与其它帧同高 (影子几何同源·跟着对齐)。
     量法: 排除左右猴子的 x 区间 (她双腿在 x 370~648) 后取最低不透明行 = 1343。
     ⚠ 不能用「中心列最低像素」估——中间那只猴子就站在那条竖带里 */
  spawn:      { src: 'assets/ip-spawn.png',     ratio: 1018 / 1431, figureH: 1344 / 1431, footCx: 0.5078 },
};
const IP_HEIGHT_PCT = 59.473;  /* 人物显示高度(房间%) · 全状态一致 */
const IP_TOP_PCT = 30.566;     /* 人物容器顶 (房间%) */
const IP_CENTER_X = 38.53;     /* 视觉中心(房间宽%) · 原布局 left:29.346% + 宽18.375%/2 */
let curState = 'stand';
let stateTimer = null;
let weather = { band: '安定', line: '没什么特别的。我就在这儿。', key: '', can_veto: false, idle_score: 60 };
let liveMood = '';
const LIVE_FACE = { 开心: 'happy', 委屈: 'sad', 羞: 'shy' };
const LIVE_ICON = {
  开心: 'ri-emotion-happy-line',
  委屈: 'ri-emotion-sad-line',
  羞: 'ri-emotion-line',
};

function overlayFace() {
  return LIVE_FACE[liveMood] || '';
}

function rememberLiveMood(mood) {
  liveMood = (mood && LIVE_FACE[mood]) ? mood : '';
}

function applyLiveBase() {
  if (curState === 'stand' || curState === 'sad' || curState === 'happy' || curState === 'shy') {
    const next = autoBaseState();
    if (next !== curState) setState(next);
  }
}

function setState(name, duration = 0) {
  const frame = IP_FRAMES[name];
  if (!frame) return;
  curState = name;
  const wrap = document.getElementById('ip-img-wrap');
  const shadow = document.getElementById('ip-shadow');
  const alt = wrap.querySelector('.ip-alt');
  const salt = shadow.querySelector('.sh-alt');
  /* 容器高 = 人物高%/figureH · 宽 = 容器高 × (房间高/宽 2/3) × 图比例 · 人物显示高度全状态一致 */
  const fh = frame.figureH || 1;
  const hPct = IP_HEIGHT_PCT / fh;
  const wPct = hPct * (2 / 3) * frame.ratio;
  wrap.style.height = hPct + '%';
  wrap.style.width = wPct + '%';
  wrap.style.left = (IP_CENTER_X - wPct / 2) + '%';
  /* 影子盒子必须跟人同高同宽同顶 · 矮一截会让 contain 把她缩小、原点抬离袜底,
     压扁后再糊, 地上只剩一坨跟脚对不上的影子 */
  shadow.style.height = hPct + '%';
  shadow.style.width = wPct + '%';
  shadow.style.left = (IP_CENTER_X - wPct / 2) + '%';
  shadow.style.top = IP_TOP_PCT + '%';
  /* 影子是伪 3D 投影 · origin = 袜底接触点 · spawn 用 figureH 避开画布里的猴 */
  const footCx = frame.footCx ?? 0.5;
  shadow.style.transformOrigin = `${footCx * 100}% ${fh * 100}%`;
  placeFootContact(wPct, footCx);
  if (name === 'stand') {
    wrap.classList.remove('alt');
    shadow.classList.remove('alt');
  } else {
    alt.src = frame.src;
    salt.src = frame.src;
    wrap.classList.add('alt');
    shadow.classList.add('alt');
  }
  clearTimeout(stateTimer);
  if (duration > 0) {
    stateTimer = setTimeout(() => setState(autoBaseState()), duration);
  }
}

/* 基态默认 stand。当天覆盖在时，基态跟覆盖一张脸，不再装安定。 */
function autoBaseState() { return overlayFace() || 'stand'; }

/* ===== 空闲行为系统（桌宠式"活着"感） =====
   深夜(23-6): 每 2-5 分钟打一次哈欠(sleepy 2.8s)
   平时: 每 3-6 分钟发一次呆(idle 3.5s)
   频率吃天气档, 不吃假心情条。基态跟覆盖走，没有覆盖才是 stand。
   对话/任务期间暂停 · 不抢戏 */
let idleTimer = null;
function idleAction(lateNight) {
  const face = overlayFace();
  if (lateNight) return ['sleepy', 2800];
  if (face === 'sad' || face === 'shy') return [face === 'shy' ? 'shy' : 'idle', 2800];
  if (weather.idle_score >= 80 && Math.random() < 0.35) return ['happy', 2000];
  if (weather.idle_score < 25) return ['sleepy', 3200];
  return ['idle', 3500];
}
function scheduleIdleAction() {
  clearTimeout(idleTimer);
  const h = new Date().getHours();
  const lateNight = h >= 23 || h < 6;
  const moodScale = weather.idle_score >= 70 ? 1.25 : (weather.idle_score < 35 ? 0.65 : 1);
  const base = lateNight ? (120 + Math.random() * 180) : (180 + Math.random() * 180);
  idleTimer = setTimeout(() => {
    if (curState === autoBaseState()) setState(...idleAction(lateNight));
    scheduleIdleAction();
  }, base * moodScale * 1000);
}
/* 首次调用挪到天气声明之后 */

/* ===== 房间物件 =====
   items.domain 对应 panels.js loadDashboard(domain) · 面板渲染 1:1 复用母体中间栏
   width 决定弹窗宽档 (wide=网格/二栏 · narrow=单列清单 · 省略=默认)
   pending=true: 后端有数据但陪伴前端还没移植 · tab 可点 · 点开是占位页 + 去工作台入口
   disabled=true: 功能本身不存在 · tab 不可点 */
const SPOTS = {
  /* 母体导航第一组就是「工作室看板 + 成长档案」· 出品工坊自成一组。
     应用 / 工作流 / 回收站 是工坊内部的三个子 tab · 不能跟工坊平铺 (BRO 指出的结构错) */
  '笔记本电脑': { bbox: [48.649, 42.212, 58.838, 53.052], icon: 'ri-macbook-line',
    label: '工作台', desc: '看板 · 出品工坊', width: 'wide',
    items: [
      { name: '看板', icon: 'ri-dashboard-3-line', desc: 'KPI · 掘金 · 闭环温度', domain: 'cockpit' },
      { name: '出品工坊', icon: 'ri-tools-line', desc: '应用 · 工作流 · 回收站', domain: 'workshop' },
    ] },
  '收音机': { bbox: [60.221, 44.556, 68.978, 52.1], icon: 'ri-radio-2-line',
    label: '信息雷达', desc: '领域监测与今日趋势',
    items: [
      { name: '信息雷达', icon: 'ri-radar-line', desc: '领域监测', domain: 'radar' },
      { name: '今日趋势', icon: 'ri-line-chart-line', desc: '最新信息流', domain: 'trends' },
    ] },
  '电脑桌2F': { bbox: [64.697, 57.568, 69.694, 64.258], icon: 'ri-treasure-map-line',
    label: '掘金台', desc: '机会 · 分析 · 反馈',
    items: [
      { name: '掘金机会', icon: 'ri-gold-line', desc: '赚钱机会清单', domain: 'opportunities' },
      { name: '可行性分析', icon: 'ri-scales-3-line', desc: '机会 × 你的画像', domain: 'feasibility' },
      { name: '执行反馈', icon: 'ri-feedback-line', desc: '做完的事 · 结果与复盘', domain: 'execution' },
    ] },
  '电脑桌1F': { bbox: [64.795, 66.724, 69.499, 73.926], icon: 'ri-bookmark-line',
    label: '收藏夹', desc: '你标星的内容', width: 'narrow',
    items: [{ name: '收藏夹', icon: 'ri-bookmark-3-line', desc: '标星的条目', domain: 'favorites' }] },
  '书架': { bbox: [26.253, 12.598, 42.969, 75.269], icon: 'ri-book-shelf-line',
    label: '知识书架', desc: '知识库与报告库',
    items: [
      { name: '知识库', icon: 'ri-book-open-line', desc: '沉淀的知识文档', domain: 'knowledge' },
      { name: '报告库', icon: 'ri-file-chart-line', desc: '生成的研究报告', domain: 'reports' },
    ] },
  '咖啡边桌': { bbox: [71.712, 56.592, 82.308, 79.15], icon: 'ri-cup-line',
    label: '关怀', desc: '她惦记你的那几句 · 你点了，她再说', width: 'narrow',
    items: [{ name: '关怀', icon: 'ri-heart-3-line', desc: '她给你泡的茶', domain: 'care' }] },
  /* 成长档案是母体的一个 hub · 七个子页由 depot.js 自己的标签条切 · 这里只开一扇门 */
  '左侧收纳': { bbox: [3.662, 60.059, 20.589, 87.085], icon: 'ri-archive-line',
    label: '成长档案', desc: '记忆与成长轨迹', width: 'wide',
    items: [{ name: '成长档案', icon: 'ri-seedling-line',
      desc: '画像 · 日记 · 心愿 · 技能库 · 星图 · 复盘 · 沉淀位', domain: 'depot' }] },
  '计划任务': { bbox: [71.908, 23.877, 82.161, 43.384], icon: 'ri-calendar-todo-line',
    label: '定时任务', desc: '自动化计划', width: 'narrow',
    items: [{ name: '定时任务', icon: 'ri-time-line', desc: '计划中的自动执行', domain: 'scheduled_tasks' }] },
  '门': { bbox: [89.062, 8.496, 97.852, 88.77], icon: 'ri-door-line',
    label: '拓展市集', desc: '外面的世界', width: 'narrow',
    items: [{ name: '拓展市集', icon: 'ri-store-2-line', desc: '技能与拓展', domain: null, disabled: true }] },
};

function firstSeenName() {
  return (window.__AI_NAME__ || window.AI_NAME || '').trim() || '她';
}
function ownerSeenName() {
  return (window.__OWNER_NAME__ || '').trim();
}
function playInviteLine(card) {
  const stored = String((card && card.text) || '').trim();
  if (stored && !/一对一对|收齐才/.test(stored)) return stored;
  const who = ownerSeenName();
  return who
    ? ('架子上多了个小盒。便条写着，' + who + '有空一起玩。')
    : '架子上多了个小盒。便条写着，有空一起玩。';
}
function teaTitle() {
  const n = firstSeenName();
  return n === '她' ? '她给你泡的茶' : n + '给你泡的茶';
}
(function _nameTeaSpot() {
  const s = SPOTS['咖啡边桌'];
  s.items[0].desc = teaTitle();
})();

let night = false;
const spotsEl = document.getElementById('spots');
for (const [key, cfg] of Object.entries(SPOTS)) {
  const [x0, y0, x1, y1] = cfg.bbox;
  const el = document.createElement('div');
  el.className = 'spot';
  el.style.cssText = `left:${x0}%;top:${y0}%;width:${x1 - x0}%;height:${y1 - y0}%`;
  el.innerHTML = `<img class="spot-day" draggable="false" src="assets/day-${key}.png" alt="">`
    + `<img class="spot-night" draggable="false" src="assets/night-${key}.png" alt="">`
    + `<div class="tip"><i class="${cfg.icon}"></i> ${cfg.label}</div>`;
  el.addEventListener('click', e => { e.stopPropagation(); openModal(key, cfg); });
  el.addEventListener('mouseenter', () => _spotFocus(true));
  el.addEventListener('mouseleave', () => _spotFocus(false));
  spotsEl.appendChild(el);
  cfg.el = el;
}

/* 窗边落地灯 · 点它切日夜 · 不弹家具窗
   切图是整张 2560×1706 透明底 (文件名 day-台灯 / night-台灯) · 铺满房间才对得上背景
   热区按实像素: 19.45–27.19 / 28.43–75.73 · 右边让给书架不抢点 */
const LAMP = {
  art: { day: 'assets/day-台灯.png', night: 'assets/night-台灯.png' },
  bbox: [19.2, 27.8, 26.15, 76.2],
};
(function mountLamp() {
  const [x0, y0, x1, y1] = LAMP.bbox;
  const el = document.createElement('div');
  el.className = 'lamp-layer';
  el.id = 'lamp-spot';
  el.innerHTML = `<img draggable="false" class="lamp-art lamp-day" src="${LAMP.art.day}" alt="">`
    + `<img draggable="false" class="lamp-art lamp-night" src="${LAMP.art.night}" alt="">`
    + `<div class="lamp-hit" style="left:${x0}%;top:${y0}%;width:${x1 - x0}%;height:${y1 - y0}%">`
    + `<div class="tip"><i class="ri-moon-line"></i> 开灯 · 夜里</div></div>`;
  el.querySelectorAll('.lamp-art').forEach(img => {
    img.addEventListener('error', () => el.classList.add('no-art'));
  });
  const hit = el.querySelector('.lamp-hit');
  hit.addEventListener('click', e => {
    e.stopPropagation();
    daynightManual = true;
    applyNight(!night);
  });
  hit.addEventListener('mouseenter', () => { el.classList.add('hot'); _spotFocus(true); });
  hit.addEventListener('mouseleave', () => { el.classList.remove('hot'); _spotFocus(false); });
  spotsEl.appendChild(el);
  LAMP.el = el;
})();

/* 置物架 · 整张透明底对齐房间 (跟台灯同一套切法) · 不是普通 spot
   热区按不透明像素: 47.2–68.1 / 12.2–32.5 · 左边不抢知识书架 */
const SHELF = {
  art: { day: 'assets/day-置物架.png?v=20260830c', night: 'assets/night-置物架.png?v=20260830b' },
  bbox: [47.2, 12.2, 68.1, 32.5],
};
let _shelfInbox = null;
(function mountShelf() {
  const [x0, y0, x1, y1] = SHELF.bbox;
  const el = document.createElement('div');
  el.className = 'lamp-layer shelf-layer';
  el.id = 'shelf-spot';
  el.innerHTML = `<img draggable="false" class="lamp-art lamp-day" src="${SHELF.art.day}" alt="">`
    + `<img draggable="false" class="lamp-art lamp-night" src="${SHELF.art.night}" alt="">`
    + `<img draggable="false" class="lamp-art lamp-day shelf-glow" src="${SHELF.art.day}" alt="">`
    + `<img draggable="false" class="lamp-art lamp-night shelf-glow" src="${SHELF.art.night}" alt="">`
    + `<div class="lamp-hit" style="left:${x0}%;top:${y0}%;width:${x1 - x0}%;height:${y1 - y0}%">`
    + `<div class="tip"><i class="ri-archive-2-line"></i> ${firstSeenName()}置物架</div>`
    + `<div class="shelf-dot" id="shelf-dot" hidden title="似乎有东西在这里"><i class="ri-mail-fill"></i></div>`
    + `</div>`;
  el.querySelectorAll('.lamp-art').forEach(img => {
    img.addEventListener('error', () => el.classList.add('no-art'));
  });
  const hit = el.querySelector('.lamp-hit');
  hit.addEventListener('click', e => {
    e.stopPropagation();
    openShelfPop();
  });
  hit.addEventListener('mouseenter', () => { el.classList.add('hot'); _spotFocus(true); });
  hit.addEventListener('mouseleave', () => { el.classList.remove('hot'); _spotFocus(false); });
  spotsEl.appendChild(el);
  SHELF.el = el;
})();

/* ===== Daemonkey 装修 API (跟工作台同一套承诺 · 房间没有侧栏) =====
   工作台 addDomain 往导航插入口; 房间把它挂到「门」上。
   pane() 给的是弹窗里的 #dashView, 不是工作台的 #detailPane。
   不加载 chat.js —— 只复刻契约, 免得 1.2 万行母体对话栏进房间。 */
window.Daemonkey = window.Daemonkey || {};
Daemonkey._domains = Daemonkey._domains || {};

function _dkIconClass(icon) {
  const s = String(icon || 'ri-apps-2-line').trim();
  if (s.startsWith('<')) {
    const m = s.match(/class=["']([^"']+)["']/);
    return (m && m[1].split(/\s+/).find(c => c.startsWith('ri-'))) || 'ri-apps-2-line';
  }
  return s;
}

function _syncDoorTip() {
  const door = SPOTS['门'];
  if (!door) return;
  const n = door.items.filter(i => i.domain && !i.disabled).length;
  if (!n) return;
  door.label = '我的装修';
  door.desc = 'user.js 挂进来的面板';
  const tip = door.el && door.el.querySelector('.tip');
  if (tip) tip.innerHTML = `<i class="${door.icon}"></i> ${door.label}`;
}

Daemonkey.addDomain = function (key, meta) {
  if (!key || !meta) return false;
  Daemonkey._domains[key] = meta;
  const door = SPOTS['门'];
  if (door) {
    const next = {
      name: meta.label || key,
      icon: _dkIconClass(meta.icon),
      desc: meta.desc || meta.label || key,
      domain: key,
    };
    const existed = door.items.find(i => i.domain === key);
    if (existed) Object.assign(existed, next);
    else door.items.push(next);
    _syncDoorTip();
    if (typeof curSpotKey !== 'undefined' && curSpotKey === '门'
        && mask && mask.classList.contains('show')) {
      openModal('门', door, key);
    }
  }
  return true;
};

// 房间没有侧栏分组 · 接口留着, 免得从工作台抄来的 user.js 在这里炸掉
Daemonkey.addNavGroup = function (id) {
  return !!id;
};

Daemonkey.ready = function (fn) {
  if (typeof fn !== 'function') return;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn, { once: true });
  else setTimeout(fn, 0);
};

Daemonkey.pane = () => (typeof $dashView !== 'undefined' ? $dashView : document.getElementById('dashView'));
Daemonkey.refresh = () => { if (typeof loadDashboard === 'function' && currentView) loadDashboard(currentView); };
Daemonkey.currentView = () => currentView;
Daemonkey.ctx = () => window._ctxData || null;

/* ===== IP 定位（影子跟人同盒 · 接触点钉在袜底） ===== */
const ipWrap = document.getElementById('ip-img-wrap');
const ipShadow = document.getElementById('ip-shadow');
const ipRect = `left:29.346%;top:${IP_TOP_PCT}%;width:18.375%;height:${IP_HEIGHT_PCT}%;position:absolute`;
ipWrap.style.cssText = ipRect;
ipShadow.style.cssText = ipRect;

function placeFootContact(wPct, footCx) {
  const feet = document.getElementById('ip-feet');
  if (!feet) return;
  feet.style.left = (IP_CENTER_X - wPct / 2) + '%';
  feet.style.width = wPct + '%';
  feet.style.top = (IP_TOP_PCT + IP_HEIGHT_PCT) + '%';
  const l = feet.querySelector('.ip-sole-l');
  const r = feet.querySelector('.ip-sole-r');
  if (l) l.style.left = ((footCx - 0.11) * 100) + '%';
  if (r) r.style.left = ((footCx + 0.11) * 100) + '%';
}
placeFootContact(18.375, IP_FRAMES.stand.footCx);

/* ===== 天气（账本在 daemon · 这里只给人看原因） ===== */
function _weatherAuth() {
  const tok = (typeof token !== 'undefined' && token) || localStorage.getItem('opus_ui_token') || '';
  return tok ? { 'Authorization': 'Bearer ' + tok } : {};
}
function weatherIcon(band) {
  if (band === '亮着') return 'ri-sparkling-2-line';
  if (band === '惦记') return 'ri-cloudy-line';
  if (band === '蔫') return 'ri-moon-cloudy-line';
  return 'ri-sun-line';
}
function paintWeatherCard() {
  const moodEl = document.getElementById('st-mood');
  const lineEl = document.getElementById('st-weather-line');
  const veto = document.getElementById('st-weather-veto');
  const icon = document.querySelector('#ip-card .mood i');
  const her = weather.her_mood;
  if (moodEl) moodEl.textContent = (her && weather.her_human) ? weather.her_human : (weather.band);
  if (lineEl) lineEl.textContent = weather.line || '';
  if (icon) icon.className = (her && LIVE_ICON[her]) ? LIVE_ICON[her] : weatherIcon(weather.band);
  if (veto) {
    veto.hidden = !weather.can_veto;
    veto.dataset.key = weather.key || '';
  }
}
async function loadWeather() {
  try {
    const r = await fetch('/api/companion/weather', { headers: _weatherAuth() });
    if (!r.ok) return;
    const d = await r.json();
    weather = {
      band: d.band || '安定',
      line: d.line || '',
      key: d.key || '',
      can_veto: !!d.can_veto,
      idle_score: Number(d.idle_score) || 60,
      her_mood: d.her_mood || '',
      her_human: d.her_human || '',
    };
    if ('her_mood' in d) rememberLiveMood(d.her_mood || '');
    applyLiveBase();
    if (window.TopicRail && typeof TopicRail.setWeatherLine === 'function') {
      TopicRail.setWeatherLine(weather.line);
    }
  } catch {}
}
loadWeather().then(() => scheduleIdleAction());

function paintSheCard(st) {
  const moodEl = document.getElementById('st-she-mood');
  const dimsEl = document.getElementById('st-she-dims');
  if (!moodEl || !dimsEl) return;
  if (st && 'she_mood_live' in st) {
    rememberLiveMood(st.she_mood_live ? (st.she_mood_key || '') : '');
    applyLiveBase();
  }
  const mood = (st && st.she_mood) || '';
  // 覆盖已经写在天气那一行脸上，底下不再复读
  if (mood && !(st && st.she_mood_live)) {
    moodEl.hidden = false;
    moodEl.innerHTML = '<i class="ri-heart-pulse-line"></i> ' + esc(mood);
  } else {
    moodEl.hidden = true;
    moodEl.textContent = '';
  }
  const dims = Object.assign({}, (st && st.she_dims) || {});
  if (dims.语气 == null && dims.力度 != null) dims.语气 = dims.力度;
  const keys = ['话量', '调性', '语气', '礼节', '表现力'];
  const bondEl = document.getElementById('st-she-bond');
  if (bondEl) {
    const n = st && st.bond_now != null ? st.bond_now : 0;
    bondEl.hidden = false;
    bondEl.innerHTML = '<span><i class="ri-hearts-line"></i>陪伴值 ' + esc(String(n)) + '</span>';
    bondEl.onclick = () => { if (typeof openBondDiary === 'function') openBondDiary(); };
  }
  if (!keys.some(k => dims[k] != null)) {
    dimsEl.hidden = true;
    dimsEl.innerHTML = '';
    return;
  }
  // 图标色跟成长档案同一套五维, 但不要顶层 const _SHE_DIM_META:
  // depot.js 已经用这个名字, 再声明一次 = Identifier has already been declared, 整份 companion.js 解析失败
  const meta = {
    '话量':   { ico: 'ri-chat-3-line',        color: '#34d399' },
    '调性':   { ico: 'ri-emotion-happy-line', color: '#fbbf24' },
    '语气':   { ico: 'ri-sword-line',         color: '#f87171' },
    '礼节':   { ico: 'ri-shield-user-line',   color: '#60a5fa' },
    '表现力': { ico: 'ri-voiceprint-line',    color: '#c084fc' },
  };
  dimsEl.hidden = false;
  dimsEl.innerHTML = keys.map(k => {
    const v = Math.max(0, Math.min(100, Number(dims[k]) || 0));
    const m = meta[k] || { ico: 'ri-sparkling-2-line', color: '#c084fc' };
    return '<div class="she-dim-mini" title="' + esc(k) + '">'
      + '<i class="' + m.ico + '" style="color:' + m.color + '"></i>'
      + '<span>' + esc(k) + '</span><b>' + v + '</b>'
      + '<span class="she-dim-mini-track"><span style="width:' + v + '%;background:' + m.color + '"></span></span>'
      + '</div>';
  }).join('');
}

/* ===== 摸头杀（连击 5 次触发彩蛋） · 回应走 IP 头旁卡通气泡 · 不污染对话栏 ===== */
function showPatBubble(text, holdMs = 2200) {
  hideSay();
  if (!text) return;
  showSay(esc(text), holdMs);
}
let patCombo = 0, patComboTimer = null;
document.getElementById('ip-head').addEventListener('click', e => {
  e.stopPropagation();
  hideSay();
  patCombo++;
  clearTimeout(patComboTimer);
  patComboTimer = setTimeout(() => { patCombo = 0; }, 2000);
  if (patCombo >= 5) {
    patCombo = 0;
    setState('surprised');
    showPatBubble('痒！……好啦好啦，知道你今天想我了。', 2600);
    setTimeout(() => setState(autoBaseState()), 2200);
    return;
  }
  setState('happy');
  ipWrap.classList.add('pat');
  /* 30% 概率她出声回应 */
  if (Math.random() < 0.3) {
    const replies = ['嗯？', '嘿嘿。', '别闹。', '头发要乱了。', '……再摸一下。'];
    showPatBubble(replies[Math.floor(Math.random() * replies.length)]);
  }
  clearTimeout(stateTimer);
  stateTimer = setTimeout(() => {
    ipWrap.classList.remove('pat');
    setState(autoBaseState());
  }, 1400);
});

/* ===== 视差 ===== */
const roomWrap = document.getElementById('room-wrap');
let px = 0, py = 0, tx = 0, ty = 0;
roomWrap.addEventListener('mousemove', e => {
  const r = roomWrap.getBoundingClientRect();
  tx = ((e.clientX - r.left) / r.width - .5) * 2;
  ty = ((e.clientY - r.top) / r.height - .5) * 2;
});
roomWrap.addEventListener('mouseleave', () => { tx = 0; ty = 0; });
const plxBg = document.getElementById('plx-bg');
const plxSpots = document.getElementById('plx-spots');
const plxIp = document.getElementById('ip-plx');
(function plxLoop() {
  px += (tx - px) * .06;
  py += (ty - py) * .06;
  const syncT = `translate(${px * 6}px, ${py * 4.2}px) scale(1.04)`;
  plxBg.style.transform = syncT;
  plxSpots.style.transform = syncT;
  plxIp.style.transform = `translate(${px * 13}px, ${py * 9}px)`;
  requestAnimationFrame(plxLoop);
})();

/* ===== 焦点虚化 =====
   平时背景微虚、人清楚。鼠标落到可点家具上: 房间清楚、她虚。
   摸她还是 focus-ip (房间再虚一层)。 */
const room = document.getElementById('room');
ipWrap.addEventListener('mouseenter', () => document.body.classList.add('focus-ip'));
ipWrap.addEventListener('mouseleave', () => document.body.classList.remove('focus-ip'));
function _spotFocus(on) {
  document.body.classList.toggle('focus-room', !!on);
}

/* ===== IP 状态卡 ===== */
const ipCard = document.getElementById('ip-card');
let cardTimer = null;
if (ipCard) ipCard.addEventListener('click', e => e.stopPropagation());
ipWrap.addEventListener('click', async e => {
  e.stopPropagation();
  const r = ipWrap.getBoundingClientRect();
  const roomR = room.getBoundingClientRect();
  ipCard.style.left = Math.min(r.right - roomR.left + 12, roomR.width - 255) + 'px';
  ipCard.style.top = Math.max(r.top - roomR.top - 20, 10) + 'px';
  ipCard.classList.add('show');
  document.body.classList.add('focus-ip');
  clearTimeout(cardTimer);
  cardTimer = setTimeout(() => {
    ipCard.classList.remove('show');
    document.body.classList.remove('focus-ip');
  }, 10000);
  try {
    const s = await (await fetch('/status')).json();
    document.getElementById('st-model').textContent = s.model || '--';
  } catch { document.getElementById('st-model').textContent = '离线'; }
  await loadWeather();
  paintWeatherCard();
  paintSheCard(await fetchCompanionState());
  document.getElementById('st-time').textContent = new Date().getHours() + 'h 在线';
});
const vetoBtn = document.getElementById('st-weather-veto');
if (vetoBtn) vetoBtn.addEventListener('click', async e => {
  e.stopPropagation();
  const key = vetoBtn.dataset.key;
  if (!key) return;
  try {
    await fetch('/api/companion/weather/veto', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ..._weatherAuth() },
      body: JSON.stringify({ key }),
    });
  } catch {}
  await loadWeather();
  paintWeatherCard();
});
document.addEventListener('click', () => {
  ipCard.classList.remove('show');
  document.body.classList.remove('focus-ip');
});

/* ===== 日夜切换 ===== */
function _paintLampTip() {
  const tip = LAMP.el && LAMP.el.querySelector('.tip');
  if (!tip) return;
  tip.innerHTML = night
    ? '<i class="ri-sun-line"></i> 关灯 · 白天'
    : '<i class="ri-moon-line"></i> 开灯 · 夜里';
}
function applyNight(on) {
  night = on;
  document.body.classList.toggle('night', on);
  document.body.classList.toggle('day', !on);
  _paintLampTip();
  syncModalTheme();
  /* 日夜两层叠着淡 · 不再换 src 硬切 */
}
let daynightManual = false;
/* 按时段自动日夜 · 每 10 分钟校正(手动切过就尊重手动·1 小时后重新跟随) */
function autoDayNight() {
  const h = new Date().getHours();
  applyNight(h >= 19 || h < 7);
}
autoDayNight();
setInterval(() => {
  if (!daynightManual) { autoDayNight(); return; }
  daynightManual = false;  /* 手动优先 10 分钟后归还自动 */
}, 10 * 60 * 1000);

/* ===== 大弹窗 · 面板 1:1 复用母体中间栏 (panels.js · chat.css) ===== */
const mask = document.getElementById('modal-mask');
const tabsEl = document.getElementById('modal-tabs');

let curSpotKey = null;   /* 当前开着哪件家具 · 跨家具跳转要用 */

/* 母体的链路面包屑 (雷达→趋势→报告) 和「深挖」这类按钮直接调 loadDashboard(domain),
   在房间里就会出现「报告库塞进信息雷达弹窗」——标题和 tab 条全对不上。
   这里把它接管成传送门: 目标维度住在哪件家具, 就把那件家具开出来。
   返回 true = 已接管, loadDashboard 别再往下走。 */
function syncSpotForDomain(domain) {
  if (!domain || currentView === 'depot') return false;   /* 成长档案子页不属于任何家具 tab */
  const cur = curSpotKey && SPOTS[curSpotKey];
  if (cur && cur.items.some(i => i.domain === domain)) return false;   /* 就在当前家具里 */
  const key = Object.keys(SPOTS).find(k => SPOTS[k].items.some(i => i.domain === domain && !i.disabled));
  if (!key) return false;   /* 不认识的维度 · 保持原行为 */
  openModal(key, SPOTS[key], domain);
  return true;
}

function openModal(key, cfg, wantDomain) {
  curSpotKey = key;
  document.getElementById('modal-title').textContent = cfg.label;
  document.getElementById('modal-desc').textContent = cfg.desc;
  document.getElementById('modal-icon').className = cfg.icon;
  const m = document.getElementById('modal');
  /* 只有一格内容时那条 tab 栏纯属占位 · 标题已经说了是什么 (成长档案还自带七个子标签 · 两层更冗余) */
  m.classList.toggle('no-tabs', cfg.items.length <= 1);
  m.classList.toggle('mw-wide', cfg.width === 'wide');
  m.classList.toggle('mw-narrow', cfg.width === 'narrow');
  m.classList.remove('mw-settings', 'mh-full');
  tabsEl.innerHTML = '';
  cfg.items.forEach((it) => {
    const b = document.createElement('button');
    b.className = 'modal-tab' + (it.disabled ? ' disabled' : '') + (it.pending ? ' pending' : '');
    b.dataset.domain = it.domain || '';
    const tag = it.disabled ? ' <span class="tag">待开发</span>'
      : (it.pending ? ' <span class="tag">施工中</span>' : '');
    b.innerHTML = `<i class="${it.icon}"></i> ${esc(it.name)}${tag}`;
    b.title = it.desc || '';
    if (!it.disabled) b.addEventListener('click', () => openTab(it));
    tabsEl.appendChild(b);
  });
  syncModalTheme();
  mask.classList.add('show');
  /* 默认落在第一个真有内容的格子 · 别让施工中的占位页当门面 (传送过来时落在指定格子) */
  const first = (wantDomain && cfg.items.find(i => i.domain === wantDomain && !i.disabled))
    || cfg.items.find(i => !i.disabled && !i.pending) || cfg.items.find(i => !i.disabled);
  if (first) openTab(first);
  else renderPending(cfg.items[0] || { name: cfg.label, desc: cfg.desc, icon: cfg.icon });
}

function openTab(it) {
  document.querySelectorAll('.modal-tab').forEach(b => {
    b.classList.toggle('active', b.dataset.domain === (it.domain || ''));
  });
  if (it.domain !== 'workshop') unmountWorkshop();
  if (it.domain === 'workshop') mountWorkshop();
  else if (it.pending) renderPending(it);
  else if (it.domain === 'depot') loadDepot('cognition');
  else if (it.domain === 'cockpit') loadBIDashboard();   /* 母体 BI 自己 fetch /dashboard/cockpit */
  else if (it.domain === 'care') loadCareDesk();
  else { currentView = it.domain; loadDashboard(it.domain); }
}

/* ===== 出品工坊 · 整包挂载 =====
   workshop.js 自带 mount(container)/unmount() —— 直接引整包比走 _extract_panels.py
   抽取更省 (它是独立 IIFE · 抽反而要重建一堆内部状态)。
   懒加载: litegraph 1MB + 工坊 150KB · 房间首屏不该背这个, 点开工坊 tab 才装 */
let _wsBundle = null;
function loadWorkshopBundle() {
  if (window.OPUS_WORKSHOP_VIEW) return Promise.resolve();
  if (_wsBundle) return _wsBundle;
  const addCss = href => new Promise(res => {
    const l = document.createElement('link');
    l.rel = 'stylesheet'; l.href = href; l.onload = l.onerror = res;
    document.head.appendChild(l);
  });
  const addJs = src => new Promise((res, rej) => {
    const s = document.createElement('script');
    s.src = src; s.onload = res; s.onerror = () => rej(new Error('没装上 ' + src));
    document.head.appendChild(s);
  });
  _wsBundle = (async () => {
    await Promise.all([
      addCss('/static/lib/litegraph.core.css'),
      addCss('/static/workshop.css?v=20260826c'),
    ]);
    await addJs('/static/lib/litegraph.core.js');   /* workshop.js mount 时要 window.LiteGraph */
    await addJs('/static/workshop.js?v=20260826a');
  })().catch(e => { _wsBundle = null; throw e; });
  return _wsBundle;
}

async function mountWorkshop() {
  const view = document.getElementById('dashView');
  view.innerHTML = '<div class="loading"><i class="ri-loader-4-line"></i> 正在把工坊搬进来…</div>';
  document.getElementById('modal').classList.add('mh-full');
  try {
    await loadWorkshopBundle();
    window.OPUS_WORKSHOP_VIEW.mount(view);
    window.OPUS_WORKSHOP_VIEW.resize();   /* 弹窗刚变高 · canvas 要重量一次 */
  } catch (e) {
    document.getElementById('modal').classList.remove('mh-full');
    view.innerHTML = `<div class="dash-empty">工坊没装起来：${esc(e.message)}</div>`;
  }
}
function unmountWorkshop() {
  document.getElementById('modal').classList.remove('mh-full');
  const w = window.OPUS_WORKSHOP_VIEW;
  if (w && w.isMounted()) w.unmount();
}

/* 后端数据已有、陪伴前端还没移植的 tab · 诚实告知 + 给工作台入口
   移植规格见 data/learnings/2026-08-26-陪伴模式-能力盘点与复用矩阵.md */
function renderPending(it) {
  const view = document.getElementById('dashView');
  if (!view) return;
  view.innerHTML = `<div class="pending-pane">
    <i class="${esc(it.icon || 'ri-hammer-line')}"></i>
    <h3>${esc(it.name)}</h3>
    <p>${esc(it.desc || '')}</p>
    <p class="pd-sub">数据后端都有了，房间里的这一版还没搬完。现在想看，去工作台。</p>
    <a class="pd-btn" href="/ui" target="_blank"><i class="ri-external-link-line"></i> 去工作台打开</a>
  </div>`;
}
function closeModal() {
  unmountWorkshop();   /* 不 unmount 会留着 ResizeObserver 和 run 轮询 */
  mask.classList.remove('show');
  document.getElementById('modal')?.classList.remove('mh-full', 'mw-settings');
}

/* 工坊里「让 OPUS 改这个」这类按钮走这条 · 母体是 injectChat, 陪伴接到房间对话里 */
window.injectChat = (text, opts) => {
  closeModal();
  const autosend = !(opts && opts.autosend === false);
  if (typeof sendCompanionText === 'function' && autosend) sendCompanionText(text);
  else {
    const inp = document.getElementById('chat-input');
    if (inp) { inp.value = text || ''; inp.focus(); }
  }
};
window.opusPrompt = opts => Promise.resolve(
  window.prompt((opts && opts.message) || '', (opts && opts.value) || '')
);
window.closeModal = closeModal;

/* 弹窗主题跟随房间日夜 · 白天 sepia(日间纸色) 夜晚 sunset(夜间灯下) */
function syncModalTheme() {
  /* 整个弹窗套主题类 · 外壳与内容区同色系 (sepia/sunset 变量定义在 chat.css)
     dashView 自己也挂主题类 · 不挂的话内容区永远暖黄 · 夜间工坊黑底叠深字 */
  const nightOn = !!night;
  ['modal', 'dashView'].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.toggle('theme-sunset', nightOn);
    el.classList.toggle('theme-sepia', !nightOn);
  });
  if (window.OPUS_WORKSHOP_VIEW && typeof OPUS_WORKSHOP_VIEW.syncPaper === 'function') {
    OPUS_WORKSHOP_VIEW.syncPaper();
  }
}

mask.addEventListener('click', e => { if (e.target === mask) closeModal(); });
document.getElementById('modal-close').addEventListener('click', closeModal);
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  if (dismissRoomConfirm()) { e.stopPropagation(); return; }
  if (window.TopicRail && TopicRail.isReading()) return;
  closeModal();
});

function esc(s) { return String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

/* ===== 对话栏 tabs ===== */
document.querySelectorAll('.ctab').forEach(t => t.addEventListener('click', () => {
  document.querySelectorAll('.ctab').forEach(x => x.classList.remove('on'));
  t.classList.add('on');
  document.querySelectorAll('.cpane').forEach(p => p.classList.remove('on'));
  document.getElementById('pane-' + t.dataset.pane).classList.add('on');
  if (t.dataset.pane === 'history') loadHistory();
  if (t.dataset.pane === 'artifacts') loadArtifacts();
}));

/* 侧栏「历史」= 聊过的话题列表 (不是当前会话的消息流 —— 那个现在直接恢复进对话区了)。
   之前这里读 data.messages, 而接口返的字段叫 turns, 所以它一直显示"记忆还是空的"。 */
async function loadHistory() {
  const el = document.getElementById('pane-history');
  el.innerHTML = '<div class="loading"><i class="ri-loader-4-line"></i> 找她记得的话题…</div>';
  try {
    const data = await (await fetch('/sessions?api_only=true&limit=20')).json();
    const rows = data.sessions || [];
    const cur = getSid();
    const head = '<button class="topic-new" id="topic-new"><i class="ri-add-line"></i> 开个新话题</button>';
    if (!rows.length) {
      el.innerHTML = head + '<div class="pane-empty"><i class="ri-history-line"></i>还没有说过话 · 第一句就开始有记忆</div>';
    } else {
      el.innerHTML = head + rows.map(s => {
        const on = s.session_id === cur;
        const running = !!s.active;
        const when = String(s.mtime || '').replace('T', ' ').slice(5, 16);
        const label = s.label || '没起名的话题';
        const onMark = on ? '<span class="tag gold">正在说</span>' : '';
        const runMark = (!on && running)
          ? '<span class="tag running" title="后台还在跑"><span class="topic-run-dot"></span>执行中</span>'
          : '';
        return `<div class="list-item topic-row${on ? ' on' : ''}${running ? ' running' : ''}" data-sid="${esc(s.session_id)}" data-label="${esc(label)}">
          <div class="ti"><span class="topic-label">${esc(label)}</span>${onMark}${runMark}</div>
          <div class="meta"><span>${esc(when)}</span><span>${s.turns || 0} 轮</span></div>
          <button type="button" class="topic-more" title="更多" data-sid="${esc(s.session_id)}"><i class="ri-more-2-line"></i></button>
        </div>`;
      }).join('');
    }
    el.querySelector('#topic-new').addEventListener('click', startNewTopic);
    const hang = el.querySelector('#topic-hangout');
    if (hang) hang.addEventListener('click', startHangout);
    el.querySelectorAll('.topic-row').forEach(r =>
      r.addEventListener('click', e => {
        if (e.target.closest('.topic-more, .topic-menu')) return;
        switchTopic(r.dataset.sid);
      }));
    el.querySelectorAll('.topic-more').forEach(btn =>
      btn.addEventListener('click', e => {
        e.stopPropagation();
        openTopicMenu(btn.dataset.sid, btn);
      }));
  } catch (e) {
    el.innerHTML = `<div class="pane-empty"><i class="ri-plug-line"></i>话题读取出错：${esc(e.message)}</div>`;
  }
}

function catchUpRoom(box) {
  if (!box) return;
  const msgs = box.querySelectorAll('.msg.opus');
  const last = msgs[msgs.length - 1];
  if (!last) return;
  const md = last.querySelector('.md-body');
  const text = md ? md.innerText : '';
  if (text) showSayText(text, true);
}
function applyVisibleChrome(sid) {
  const st = (window.SessionRuntime && sid) ? SessionRuntime.get(sid) : null;
  const pending = !!(st && st.pending);
  curTurnId = (st && st.currentTurnId) || '';
  curAbort = (st && st.currentAbortController) || null;
  refreshSendChrome();
  _confirmCards.clear();
  const host = document.getElementById('room-confirm');
  if (host) host.innerHTML = '';
  if (pending) {
    setStatus('她还在做事…');
    if (curState === 'stand' || curState === 'thinking') setState('working');
  } else {
    setStatus(null);
    hideToolBubble();
  }
  if (sid) startActivePoll(sid);
  else stopActivePoll();
  if (window.TopicRail && TopicRail.paintStamps) TopicRail.paintStamps();
}

/* 换话题 = 换记忆段落, 不是换一个她。 切完直接跳回对话区, 免得他还要自己点回来。
   切走不杀 stream · 跟工作台同一份 SessionRuntime · 那本继续在后台写自己的容器。 */
function switchTopic(sid) {
  if (!sid || sid === getSid() || sid === '__draft__') return;
  if (window.TopicRail && TopicRail.clearDraft) TopicRail.clearDraft();
  saveSid(sid);
  hideSay();
  const st = window.SessionRuntime ? SessionRuntime.getOrCreate(sid) : null;
  if (window.SessionRuntime) SessionRuntime.setActiveContainer(sid);
  applyVisibleChrome(sid);
  if (st && st.pending && st.$container && st.$container.childElementCount) {
    catchUpRoom(st.$container);
  } else {
    restoreConversation();
  }
  if (document.getElementById('say-log')?.classList.contains('show')) openSayLog();
}

function startHangout() {
  try { localStorage.removeItem(SID_KEY); } catch {}
  _restoreTurns = []; _restoreCursor = 0;
  closeSayLog();
  hideSay();
  if (!window.SessionRuntime) return;
  const cid = SessionRuntime.allocCid();
  const state = SessionRuntime.getOrCreate(cid);
  state.chatMode = 'taste';
  const box = SessionRuntime.getOrCreateContainer(cid);
  if (box) box.innerHTML = '';
  SessionRuntime.setActiveContainer(cid);
  applyVisibleChrome(null);
  if (window.TopicRail && TopicRail.draftNew) TopicRail.draftNew('说话方式');
  else if (window.TopicRail) TopicRail.refresh();
  send({ fromQueue: { text: '开始问说话方式。' }, silentUser: true, sid: cid });
}

async function refreshHangoutDoor() {
  const label = document.getElementById('topicHangoutLabel');
  if (!label) return;
  const name = (window.__AI_NAME__ || window.AI_NAME || '她').trim() || '她';
  const first = name + '想知道你喜欢她怎么说话。';
  if (!label.textContent) label.textContent = first;
  let settled = false;
  try {
    const r = await fetch('/dashboard/she_state', { headers: _weatherAuth() });
    if (r.ok) {
      const d = await r.json();
      settled = !!d.taste_settled;
    }
  } catch (e) {}
  label.textContent = settled ? '想让我改改说话方式吗？' : first;
}

function startNewTopic() {
  try { localStorage.removeItem(SID_KEY); } catch {}
  _restoreTurns = []; _restoreCursor = 0;
  closeSayLog();
  hideSay();
  if (window.SessionRuntime) {
    const cid = SessionRuntime.allocCid();
    SessionRuntime.getOrCreate(cid);
    const box = SessionRuntime.getOrCreateContainer(cid);
    if (box) box.innerHTML = '';
    SessionRuntime.setActiveContainer(cid);
  }
  addMsg('好，这段从头开始。之前聊的都还在，随时能翻回去。', 'ai');
  showSayText('好，这段从头开始。之前聊的都还在，随时能翻回去。');
  applyVisibleChrome(null);
  if (window.TopicRail && TopicRail.draftNew) TopicRail.draftNew();
  else if (window.TopicRail) TopicRail.refresh();
}

/* 话题卡 ⋯ 菜单 · 对齐工作台 deleteSession / renameSession, 陪伴只留重命名+删除 */
let _topicMenuEl = null;

function closeTopicMenu() {
  if (_topicMenuEl && _topicMenuEl.parentNode) _topicMenuEl.parentNode.removeChild(_topicMenuEl);
  _topicMenuEl = null;
  document.querySelectorAll('.topic-more.open').forEach(b => b.classList.remove('open'));
}

function openTopicMenu(sid, anchorEl) {
  closeTopicMenu();
  if (!sid) return;
  const menu = document.createElement('div');
  menu.className = 'topic-menu';
  menu.innerHTML =
    '<button type="button" class="tm-item" data-act="rename"><i class="ri-edit-2-line"></i> 重命名</button>' +
    '<button type="button" class="tm-item danger" data-act="delete"><i class="ri-delete-bin-6-line"></i> 删除</button>';
  document.body.appendChild(menu);
  _topicMenuEl = menu;
  if (anchorEl) anchorEl.classList.add('open');
  const rect = anchorEl.getBoundingClientRect();
  const w = menu.offsetWidth || 132;
  menu.style.left = Math.max(8, Math.min(rect.right - w, window.innerWidth - w - 8)) + 'px';
  menu.style.top = (rect.bottom + 4) + 'px';
  menu.addEventListener('click', e => {
    const item = e.target.closest('.tm-item');
    if (!item) return;
    e.stopPropagation();
    closeTopicMenu();
    if (item.dataset.act === 'rename') renameTopic(sid);
    else if (item.dataset.act === 'delete') deleteTopic(sid);
  });
  setTimeout(() => {
    document.addEventListener('click', _onceCloseTopicMenu, { once: true, capture: true });
  }, 0);
}

function _onceCloseTopicMenu(e) {
  if (_topicMenuEl && _topicMenuEl.contains(e.target)) {
    document.addEventListener('click', _onceCloseTopicMenu, { once: true, capture: true });
    return;
  }
  closeTopicMenu();
}

function _topicRowOf(sid) {
  return document.querySelector('.topic-row[data-sid="' + CSS.escape(sid) + '"], .tcard[data-sid="' + CSS.escape(sid) + '"]');
}

function _refreshTopicLists() {
  loadHistory();
  if (window.TopicRail && typeof TopicRail.refresh === 'function') TopicRail.refresh();
}

async function renameTopic(sid) {
  closeTopicMenu();
  const row = _topicRowOf(sid);
  const current = (row && row.dataset.label) || '';
  const shown = current === '没起名的话题' ? '' : current;
  const name = await window.opusPrompt({
    message: '给这个话题起个名字 · 留空回到默认显示',
    value: shown,
  });
  if (name === null) return;
  const trimmed = String(name || '').trim();
  try {
    const r = await fetch('/sessions/' + encodeURIComponent(sid) + '/meta', {
      method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json' }, _weatherAuth()),
      body: JSON.stringify({ label: trimmed }),
    });
    if (!r.ok) {
      const txt = await r.text().catch(() => '');
      alert('重命名失败 [' + r.status + '] ' + txt.slice(0, 200));
      return;
    }
    _refreshTopicLists();
  } catch (e) {
    alert('网络出错: ' + (e.message || e));
  }
}

async function deleteTopic(sid) {
  closeTopicMenu();
  const row = _topicRowOf(sid);
  const name = (row && row.dataset.label) || '这个话题';
  const ok = typeof opusConfirm === 'function'
    ? await opusConfirm({ message: '确认删除「' + name + '」吗？删除后不可恢复。' })
    : window.confirm('确认删除「' + name + '」吗？删除后不可恢复。');
  if (!ok) return;
  try {
    const r = await fetch('/sessions/' + encodeURIComponent(sid), {
      method: 'DELETE',
      headers: _weatherAuth(),
    });
    if (!r.ok) {
      const txt = await r.text().catch(() => '');
      alert('删除失败 [' + r.status + '] ' + txt.slice(0, 200));
      return;
    }
    if (sid === getSid()) {
      if (window.SessionRuntime) SessionRuntime.abortSession(sid);
      startNewTopic();
    } else {
      if (window.SessionRuntime) SessionRuntime.abortSession(sid);
      if (window.TopicRail && typeof TopicRail.refresh === 'function') TopicRail.refresh();
    }
    loadHistory();
  } catch (e) {
    alert('网络出错: ' + (e.message || e));
  }
}

function showPane(name) {
  document.querySelectorAll('.ctab').forEach(x => x.classList.toggle('on', x.dataset.pane === name));
  document.querySelectorAll('.cpane').forEach(p => p.classList.toggle('on', p.id === 'pane-' + name));
}

/* ===== 回来的时候接得上 =====
   刷新一下房间就空了, 但她记得的东西一直在服务器上 —— 只是没渲染回来。
   对"她一直在"这件事来说, 空房间比什么都伤。
   tool turn 不进气泡: 房间里工具过程靠表情表达, 不铺流水账 (和陪伴人格片段同一条约束)。*/
const RESTORE_BATCH = 14;
let _restoreTurns = [];
let _restoreCursor = 0;

function buildMsgEl(t) {
  const d = document.createElement('div');
  const isMe = t.role === 'user';
  d.className = 'msg ' + (isMe ? 'bro' : 'opus');
  if (isMe) {
    const strip = (typeof _broAttachStrip === 'function')
      ? _broAttachStrip(t.content || '')
      : { body: t.content || '', legacy: [] };
    const atts = (t.attachments && t.attachments.length)
      ? t.attachments
      : strip.legacy.map(function (b) { return { name: b, path: 'data/runtime/attachments/' + b }; });
    const body = strip.stripped ? (strip.body || '') : (atts.length ? (strip.body || '') : (t.content || ''));
    d.innerHTML = esc(body) + `<div class="t">${fmtTime(t.ts)}</div>`;
    if (atts.length && typeof _renderBroAttachments === 'function') _renderBroAttachments(d, atts);
  } else {
    renderAiBubble(d, String(t.content || ''), t.ts);
  }
  return d;
}

function renderEarlier(n) {
  const start = Math.max(0, _restoreCursor - n);
  const batch = _restoreTurns.slice(start, _restoreCursor);
  _restoreCursor = start;
  const frag = document.createDocumentFragment();
  batch.forEach(t => frag.appendChild(buildMsgEl(t)));
  const box = chatBox();
  box.insertBefore(frag, box.firstChild);
  syncEarlierBtn();
}

function syncEarlierBtn() {
  const old = document.getElementById('load-earlier');
  if (old) old.remove();
  if (_restoreCursor <= 0) return;
  const btn = document.createElement('button');
  btn.id = 'load-earlier';
  btn.className = 'load-earlier';
  btn.innerHTML = `<i class="ri-arrow-up-line"></i> 更早的对话（还有 ${_restoreCursor} 条）`;
  btn.addEventListener('click', () => {
    // 往上插内容会把视线顶走 · 补回高度差, 让他眼睛盯着的那条不动
    const before = chatBox().scrollHeight;
    renderEarlier(RESTORE_BATCH);
    const box = chatBox();
    box.scrollTop += box.scrollHeight - before;
  });
  chatBox().insertBefore(btn, chatBox().firstChild);
}

function greetTextByHour() {
  const h = new Date().getHours();
  if (h >= 23 || h < 6) return '夜深了，你来了。';
  if (h < 9) return '早上好，新的一天。';
  if (h < 12) return '上午好。';
  if (h < 14) return '中午好，吃饭了吗？';
  if (h < 18) return '下午好。';
  return '晚上好。';
}

function sleepWakeText() {
  const h = new Date().getHours();
  if (h >= 23 || h < 6) return '睡醒了？夜里好。';
  if (h < 9) return '睡醒了？早上好。';
  if (h < 12) return '睡醒了？上午好。';
  if (h < 14) return '睡醒了？中午好。';
  if (h < 18) return '睡醒了？下午好。';
  return '睡醒了？晚上好。';
}

/* 全局状态卡 · 跨渠道问候决策（读了就不猜睡没睡） */
function _stateCardFieldVal(card, field) {
  const e = card?.[field];
  if (!e || typeof e !== 'object') return '';
  const v = String(e.value || '').trim();
  return (v && v !== '-' && v !== '待确认') ? v : '';
}
function _isLateNight() {
  const h = new Date().getHours();
  return h >= 23 || h < 6;
}
function _nightOwlSchedule(val) {
  return /昼伏夜出|反复期|熬夜|夜猫|晚睡|颠倒|凌晨/.test(val);
}
function _healthLateNightHint(val) {
  return /熬夜|疲劳|头疼|失眠|缺觉|困乏/.test(val);
}
function _lowMoodBaseline(val) {
  return /低|丧|不想说话|低落|抑郁|没劲|烦|累/.test(val);
}
function nightOwlLateText() {
  return '又到这个点啦。';
}
function healthLateReminderText() {
  return '又熬夜了……今晚别熬太狠。';
}
function lowMoodGreetingText() {
  const h = new Date().getHours();
  if (h >= 23 || h < 6) return '夜里好，慢慢来。';
  if (h < 9) return '早，不用勉强说话。';
  return '嗯，我在。';
}
async function fetchCompanionState() {
  try {
    const r = await fetch('/api/companion/state', { headers: _weatherAuth() });
    if (!r.ok) return null;
    const d = await r.json();
    // state_card 是他的当下；she_mood 覆盖在时压过 SHE-STATE
    return d;
  } catch {
    return null;
  }
}

function shelfTitle() {
  return firstSeenName() + '置物架';
}
function paintFirstSeenName() {
  const n = firstSeenName();
  const st = document.getElementById('st-name');
  if (st) st.textContent = n;
  const brand = document.getElementById('brand-name');
  if (brand) brand.textContent = n;
  if (n !== '她') document.title = n + ' · 陪伴模式';
  const tip = SHELF.el && SHELF.el.querySelector('.tip');
  if (tip) tip.innerHTML = '<i class="ri-archive-2-line"></i> ' + shelfTitle();
}

let _shelfHistory = [];
let _bondSnap = {};
function cardIsLow(card) {
  if (!card) return false;
  if (typeof card.low === 'boolean') return card.low;
  return /委屈|难过|低落|伤心|sad/i.test(String(card.mood || ''));
}

function paintGalleryMail(st) {
  const card = st && st.gallery_inbox && st.gallery_inbox.date ? st.gallery_inbox : null;
  _shelfInbox = card;
  if (st && Array.isArray(st.gallery_history)) _shelfHistory = st.gallery_history;
  if (st && ('bond_now' in st || 'bond_band' in st)) _bondSnap = st;
  const dot = document.getElementById('shelf-dot');
  if (dot) {
    const box = !!(card && card.kind === 'game');
    dot.hidden = !card;
    dot.classList.toggle('is-box', box);
    const ico = dot.querySelector('i');
    if (ico) ico.className = box ? 'ri-box-3-fill' : 'ri-mail-fill';
    dot.title = card ? (box ? '似乎有个盒' : '似乎有东西在这里') : '';
  }
  const pop = document.getElementById('shelf-pop');
  if (pop && !pop.hidden) fillShelfPop();
}

function fillShelfActs(low) {
  const acts = document.getElementById('shelf-pop-acts');
  if (!acts) return;
  if (!_shelfInbox) { acts.hidden = true; acts.innerHTML = ''; return; }
  acts.hidden = false;
  if (_shelfInbox.kind === 'game') {
    acts.innerHTML = '<button type="button" class="gm-act ghost" data-act="play-ignore">忽略</button>'
      + '<button type="button" class="gm-act like" data-act="play-start"><i class="ri-box-3-line"></i> 开玩</button>';
    return;
  }
  acts.innerHTML = low
    ? '<button type="button" class="gm-act ghost" data-act="ignore">忽略</button>'
      + '<button type="button" class="gm-act quill" data-act="talk" title="对着她说"><i class="ri-quill-pen-line"></i></button>'
    : '<button type="button" class="gm-act like" data-act="like" title="点赞"><i class="ri-thumb-up-line"></i> 点赞</button>';
}

function shelfDay(iso) {
  const m = String(iso || '').match(/(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return '';
  return Number(m[2]) + '月' + Number(m[3]) + '日';
}
function histActLine(act) {
  const a = String(act || '看过');
  if (a === '点赞') return '你点了赞';
  if (a === '对话') return '你回了对话';
  if (a === '忽略') return '你看过了';
  if (a === '不要这种') return '你说不要这种';
  if (a === '玩完') return '你玩完了';
  return '你' + a;
}
function histIsGame(row) {
  return !!(row && (row.kind === 'game' || row.act === '玩完'));
}
function histBodyLine(row) {
  if (histIsGame(row)) {
    const word = row.toy === 'tictac' ? '井字' : (row.toy === 'flip' ? '翻牌' : (row.toy || row.text || '翻牌'));
    return '游戏：' + word;
  }
  return row && row.text ? ('明信片：' + row.text) : '明信片';
}
function placeShelfPop() {
  const pop = document.getElementById('shelf-pop');
  const card = pop && pop.querySelector('.shelf-pop-card');
  const hit = SHELF.el && SHELF.el.querySelector('.lamp-hit');
  if (!pop || pop.hidden || !card || !room || !hit) return;
  const roomR = room.getBoundingClientRect();
  const r = hit.getBoundingClientRect();
  const cw = card.offsetWidth || 300;
  const ch = card.offsetHeight || 180;
  let left = r.right - roomR.left + 12;
  let top = r.top - roomR.top + 6;
  if (left + cw > roomR.width - 12) left = Math.max(12, roomR.width - cw - 12);
  if (top + ch > roomR.height - 16) top = Math.max(10, roomR.height - ch - 16);
  if (top < 10) top = 10;
  card.style.left = left + 'px';
  card.style.top = top + 'px';
}

const SHELF_HIST_SHOW = 4;
function openBondDiary() {
  closeShelfPop();
  const cfg = SPOTS['左侧收纳'];
  if (cfg) openModal('左侧收纳', cfg);
  setTimeout(() => { if (typeof loadDepot === 'function') loadDepot('diary'); }, 0);
}
function fillShelfHistory(body) {
  if (!_shelfHistory.length) {
    const empty = document.createElement('div');
    empty.className = 'gm-empty';
    empty.textContent = '还没有往来。她寄来的会留在这儿。';
    body.appendChild(empty);
    return;
  }
  const list = document.createElement('div');
  list.className = 'gm-hist';
  _shelfHistory.slice(0, SHELF_HIST_SHOW).forEach(row => {
    const item = document.createElement('div');
    item.className = 'gm-hist-item';
    const day = shelfDay(row.date || row.at);
    if (day) {
      const when = document.createElement('time');
      when.textContent = day + (histIsGame(row) ? '她摆了个盒' : '她寄来');
      item.appendChild(when);
    }
    const act = document.createElement('b');
    act.textContent = histActLine(row.act);
    const t = document.createElement('span');
    t.textContent = histBodyLine(row);
    item.appendChild(act);
    item.appendChild(t);
    if (histIsGame(row)) {
      const again = document.createElement('button');
      again.type = 'button';
      again.className = 'gm-again';
      again.innerHTML = '<i class="ri-refresh-line"></i> 再来一盘';
      again.addEventListener('click', e => {
        e.stopPropagation();
        closeShelfPop();
        openReplay(row.toy);
      });
      item.appendChild(again);
    }
    list.appendChild(item);
  });
  body.appendChild(list);
  const more = document.createElement('button');
  more.type = 'button';
  more.className = 'gm-more';
  more.innerHTML = '<i class="ri-hearts-line"></i> 查看更多';
  more.addEventListener('click', e => { e.stopPropagation(); openBondDiary(); });
  body.appendChild(more);
}

function fillShelfPop() {
  const body = document.querySelector('#shelf-pop .shelf-pop-body');
  const box = document.querySelector('#shelf-pop .shelf-pop-card');
  if (!body) return;
  body.innerHTML = '';
  const k = document.createElement('div');
  k.className = 'gm-k';
  const card = _shelfInbox;
  if (!card) {
    if (box) box.classList.remove('has-mail');
    const bn = _bondSnap && _bondSnap.bond_band !== 'empty' && _bondSnap.bond_now != null
      ? ' · 陪伴值 ' + _bondSnap.bond_now : '';
    k.innerHTML = '<i class="ri-inbox-2-line"></i> 往来' + bn;
    body.appendChild(k);
    if (_bondSnap && _bondSnap.bond_why) {
      const why = document.createElement('div');
      why.className = 'gm-hint';
      why.textContent = _bondSnap.bond_why;
      body.appendChild(why);
    }
    fillShelfHistory(body);
    fillShelfActs(false);
    placeShelfPop();
    return;
  }
  if (card.kind === 'game') {
    if (box) box.classList.remove('has-mail');
    k.innerHTML = '<i class="ri-box-3-fill"></i> 她找到一个盒';
    body.appendChild(k);
    const p = document.createElement('div');
    p.className = 'gm-text';
    p.textContent = playInviteLine(card);
    body.appendChild(p);
    fillShelfActs(false);
    placeShelfPop();
    return;
  }
  if (box) box.classList.add('has-mail');
  const low = cardIsLow(card);
  k.innerHTML = '<i class="ri-mail-fill"></i> 她寄来一张';
  body.appendChild(k);
  if (card.image_url) {
    const img = document.createElement('img');
    img.src = card.image_url;
    img.alt = '她寄来的';
    img.addEventListener('load', placeShelfPop);
    body.appendChild(img);
  }
  const p = document.createElement('div');
  p.className = 'gm-text';
  p.textContent = card.text || '';
  body.appendChild(p);
  const hint = document.createElement('div');
  hint.className = 'gm-hint';
  hint.textContent = low ? '忽略，或者对着她说。' : '喜欢就点一下。';
  body.appendChild(hint);
  fillShelfActs(low);
  placeShelfPop();
}

async function respondShelf(action) {
  try {
    const r = await fetch('/api/companion/gallery/respond', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ..._weatherAuth() },
      body: JSON.stringify({ action }),
    });
    const d = await r.json();
    if (!d.ok) return;
    _shelfInbox = null;
    if (Array.isArray(d.history)) _shelfHistory = d.history;
    paintGalleryMail({ gallery_inbox: null, gallery_history: _shelfHistory });
    closeShelfPop();
    if (action === 'talk') talkFromShelf();
    const st = await fetchCompanionState();
    if (st) {
      rememberLiveMood(st.she_mood_live ? (st.she_mood_key || '') : '');
      applyLiveBase();
      paintSheCard(st);
      paintGalleryMail(st);
    }
  } catch {}
}

function openShelfPop() {
  const pop = document.getElementById('shelf-pop');
  if (!pop) return;
  const card = document.getElementById('ip-card');
  if (card) card.classList.remove('show');
  document.body.classList.remove('focus-ip');
  fillShelfPop();
  pop.hidden = false;
  document.body.classList.add('focus-room');
  placeShelfPop();
}

function closeShelfPop() {
  const pop = document.getElementById('shelf-pop');
  if (pop) pop.hidden = true;
  document.body.classList.remove('focus-room');
}

function talkFromShelf() {
  closeShelfPop();
  const input = document.getElementById('chat-input');
  if (input) {
    input.focus();
    try { input.scrollIntoView({ block: 'nearest' }); } catch {}
  }
}

async function playShelf(path, body) {
  const r = await fetch('/api/companion/play/' + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ..._weatherAuth() },
    body: JSON.stringify(body || {}),
  });
  return r.json();
}

function setPlayLeft(n) {
  const el = document.getElementById('play-left');
  if (!el) return;
  if (typeof n === 'string') { el.textContent = n; return; }
  el.textContent = n > 0 ? ('还剩 ' + n + ' 对') : '收齐了';
}

function setPlayTitle(toy) {
  const el = document.querySelector('#play-table .play-head b');
  if (!el) return;
  el.innerHTML = toy === 'tictac'
    ? '<i class="ri-grid-line"></i> 井字'
    : '<i class="ri-box-3-line"></i> 翻牌盒';
}

function closePlayTable() {
  const table = document.getElementById('play-table');
  if (table) table.hidden = true;
  const foot = document.getElementById('play-foot');
  if (foot) { foot.hidden = true; foot.textContent = ''; }
  if (window.FlipBox) FlipBox.unmount();
  if (window.TicTac) TicTac.unmount();
  document.body.classList.remove('focus-room');
}

function openPlayBoard(toy, scored) {
  closeShelfPop();
  const table = document.getElementById('play-table');
  const board = document.getElementById('play-board');
  const foot = document.getElementById('play-foot');
  if (!table || !board) return;
  if (foot) { foot.hidden = true; foot.textContent = ''; }
  if (window.FlipBox) FlipBox.unmount();
  if (window.TicTac) TicTac.unmount();
  setPlayTitle(toy);
  table.hidden = false;
  document.body.classList.add('focus-room');
  const done = scored ? finishPlay : replayDone;
  if (toy === 'tictac') {
    if (!window.TicTac) return;
    setPlayLeft('轮到你');
    TicTac.mount(board, { onTurn: setPlayLeft, onDone: done });
    return;
  }
  if (!window.FlipBox) return;
  FlipBox.mount(board, { onLeft: setPlayLeft, onDone: done });
}

function openReplay(toy) {
  const t = (toy === 'tictac' || toy === '井字') ? 'tictac' : 'flip';
  openPlayBoard(t, false);
}

function replayDone() {
  const foot = document.getElementById('play-foot');
  if (foot) { foot.hidden = false; foot.textContent = '再来一盘。'; }
  setTimeout(closePlayTable, 1200);
}

async function ignorePlayInvite() {
  try {
    const d = await playShelf('ignore', {});
    if (!d.ok) return;
    _shelfInbox = null;
    if (Array.isArray(d.history)) _shelfHistory = d.history;
    paintGalleryMail({ gallery_inbox: null, gallery_history: _shelfHistory });
    closeShelfPop();
    const st = await fetchCompanionState();
    if (st) paintGalleryMail(st);
  } catch {}
}

async function startPlayBox() {
  try {
    const d = await playShelf('start', {});
    if (!d.ok) return;
    openPlayBoard(d.toy || 'flip', true);
  } catch {}
}

async function finishPlay(pack) {
  try {
    const d = await playShelf('finish', pack || {});
    const foot = document.getElementById('play-foot');
    if (foot) {
      foot.hidden = false;
      foot.textContent = d && d.ok ? '盒盖合上了。' : (d && d.error) || '这一盘还没算。';
    }
    if (!d || !d.ok) return;
    _shelfInbox = null;
    if (Array.isArray(d.history)) _shelfHistory = d.history;
    paintGalleryMail({ gallery_inbox: null, gallery_history: _shelfHistory });
    const st = await fetchCompanionState();
    if (st) paintGalleryMail(st);
    setTimeout(closePlayTable, 1400);
  } catch {}
}
function resolveReturnGreeting(stateCard, saidSleep, last) {
  if (saidSleep) return sleepWakeText();
  const card = stateCard || {};
  const schedule = _stateCardFieldVal(card, '作息模式');
  const health = _stateCardFieldVal(card, '健康基线');
  const mood = _stateCardFieldVal(card, '情绪基线');
  const late = _isLateNight();
  const healthHint = health && _healthLateNightHint(health);
  // 健康提醒优先于夜猫分支：BRO 是昼伏夜出+熬夜偏多(作息+健康都含熬夜线索)时，
  // 若夜猫分支在前会永远复读上句/夜猫文案，「今晚别熬太狠」出不来。健康提醒更该出口。
  if (healthHint && late) {
    return healthLateReminderText();
  }
  if (schedule && _nightOwlSchedule(schedule) && late) {
    return last ? last.content : nightOwlLateText();
  }
  if (mood && _lowMoodBaseline(mood)) {
    return lowMoodGreetingText();
  }
  if (last) return last.content;
  return null;
}

function applyEmptyHistoryGreeting() {
  const text = greetTextByHour();
  const box = chatBox();
  if (box && !box.querySelector('.msg.opus')) {
    addMsg('这段还没聊过，从头开始。', 'ai');
  }
  showSayText(text);
}

async function restoreConversation() {
  const sid = getSid();
  if (!sid || String(sid).startsWith('tmp-')) return;
  if (window.SessionRuntime) {
    SessionRuntime.getOrCreate(sid);
    SessionRuntime.setActiveContainer(sid);
  }
  const box = chatBox();
  try {
    const r = await fetch(`/sessions/${sid}/messages`);
    if (!r.ok) { applyEmptyHistoryGreeting(); return; }
    const data = await r.json();
    _restoreTurns = (data.turns || []).filter(function (t) {
      if (t.role !== 'user' && t.role !== 'assistant') return false;
      if (String(t.content || '').trim()) return true;
      return !!(t.attachments && t.attachments.length);
    });
    if (!_restoreTurns.length) { applyEmptyHistoryGreeting(); return; }
    if (box) box.innerHTML = '';
    _restoreCursor = _restoreTurns.length;
    renderEarlier(RESTORE_BATCH);
    if (box) box.scrollTop = box.scrollHeight;
    const last = [..._restoreTurns].reverse().find(t => t.role === 'assistant');
    /* 活人感: 上次他说过睡了/晚安, 回来先问睡得怎样, 而不是按模板问候或复读上句。
       只匹配陈述(我睡了/晚安/去睡了…), 不匹配反问(你睡了吗/还没睡)·也不把「困了」当已睡 */
    const lastUser = [..._restoreTurns].reverse().find(t => t.role === 'user');
    const c = String(lastUser?.content || '').slice(-40);
    const saidSleep = /晚安|去睡了|我睡了|睡觉了|睡了[。！!]|睡了，|躺下了|去休息了|休息了/.test(c)
      && !/还没睡|睡了吗|没睡/.test(c);
    const st = await fetchCompanionState();
    const stateCard = st ? (st.state_card || null) : null;
    paintSheCard(st);
    paintGalleryMail(st);
    const greeting = resolveReturnGreeting(stateCard, saidSleep, last);
    if (greeting) showSayText(greeting);
  } catch {
    applyEmptyHistoryGreeting();
  }
}

async function loadArtifacts() {
  const el = document.getElementById('pane-artifacts');
  const sid = getSid();
  if (!sid) { el.innerHTML = '<div class="pane-empty"><i class="ri-folder-open-line"></i>还没有会话 · 她做的东西会放这</div>'; return; }
  el.innerHTML = '<div class="loading"><i class="ri-loader-4-line"></i> 读取她做的东西…</div>';
  try {
    const data = await (await fetch(`/sessions/${sid}/artifacts`)).json();
    const arts = Array.isArray(data) ? data : (data.artifacts || []);
    if (!arts.length) { el.innerHTML = '<div class="pane-empty"><i class="ri-folder-open-line"></i>她还没有给你做出东西</div>'; return; }
    el.innerHTML = arts.slice(0, 20).map(a => `
      <div class="list-item">
        <div class="ti">${esc(a.name || a.filename || a.title || '产物')}</div>
        <div class="meta"><span class="tag gold">${esc(a.type || a.kind || 'file')}</span>
        <span>${esc(a.created_at || a.time || '')}</span></div>
      </div>`).join('');
  } catch (e) {
    el.innerHTML = `<div class="pane-empty"><i class="ri-plug-line"></i>产物读取出错：${esc(e.message)}</div>`;
  }
}

/* ===== TTS 语音（她有声音 · MiniMax · 默认关·没配 key 静默降级） ===== */
const TTS_KEY = 'companion_tts_on';
let ttsOn = false;
try { ttsOn = localStorage.getItem(TTS_KEY) === '1'; } catch {}
let curAudio = null;

async function speak(text) {
  if (!ttsOn || !text) return;
  const clean = text.replace(/[*#`>\-_[\]()]/g, '').slice(0, 800);
  if (!clean.trim()) return;
  try {
    const r = await fetch('/api/tts', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: clean }),
    });
    if (!r.ok) return;  // 没配 key · 静默
    const blob = await r.blob();
    if (curAudio) { curAudio.pause(); curAudio = null; }
    curAudio = new Audio(URL.createObjectURL(blob));
    curAudio.play().catch(() => {});
  } catch {}
}

function updateTtsBtn() {
  const btn = document.getElementById('tts-btn');
  if (!btn) return;
  btn.innerHTML = ttsOn ? '<i class="ri-volume-up-line"></i>' : '<i class="ri-volume-mute-line"></i>';
  btn.classList.toggle('on', ttsOn);
}
const ttsBtn = document.getElementById('tts-btn');
if (ttsBtn) ttsBtn.addEventListener('click', () => {
  ttsOn = !ttsOn;
  try { localStorage.setItem(TTS_KEY, ttsOn ? '1' : '0'); } catch {}
  if (!ttsOn && curAudio) { curAudio.pause(); curAudio = null; }
  updateTtsBtn();
});
updateTtsBtn();

if (typeof initModelSwitch === 'function') {
  initModelSwitch({
    token: function () { return (typeof token !== 'undefined' && token) || localStorage.getItem('opus_ui_token') || ''; },
    sessionId: function () { return typeof getSid === 'function' ? (getSid() || '') : ''; },
  });
  if (typeof loadCurrentModel === 'function') loadCurrentModel();
}

const MIC_KEY = 'companion_mic_on';
let micOn = true;
try { if (localStorage.getItem(MIC_KEY) === '0') micOn = false; } catch {}
function paintMicToggle() {
  const btn = document.getElementById('mic-toggle');
  if (!btn) return;
  btn.classList.toggle('on', micOn);
  btn.innerHTML = micOn ? '<i class="ri-mic-line"></i>' : '<i class="ri-mic-off-line"></i>';
  btn.title = micOn ? '麦克风开着 · 点一下关掉' : '麦克风关了 · 点一下打开';
  document.getElementById('listen-dock')?.classList.toggle('mic-off', !micOn);
}
function setMicOn(on) {
  micOn = !!on;
  try { localStorage.setItem(MIC_KEY, micOn ? '1' : '0'); } catch {}
  paintMicToggle();
  /* 顶栏麦是总闸 · 收着(语音对话)也要 start · 否则不听、听环一直是笔不露猴头 */
  if (!window.__voice) return;
  if (!micOn) {
    if (__voice.isListening && __voice.isListening()) __voice.stop();
  } else if (window.ListenDock) {
    _voiceFollowDock(ListenDock.isOpen());
  }
}
document.getElementById('mic-toggle')?.addEventListener('click', () => setMicOn(!micOn));
paintMicToggle();

function openRoomSettings() {
  /* 家具同一套弹窗 · 内容直接跑工作台 settings-pane.js */
  if (typeof unmountWorkshop === 'function') unmountWorkshop();
  curSpotKey = null;
  document.getElementById('modal-title').textContent = '设置';
  document.getElementById('modal-desc').textContent = '和工作台同一份 · 改完立刻生效';
  document.getElementById('modal-icon').className = 'ri-settings-3-line';
  const m = document.getElementById('modal');
  m.classList.add('no-tabs', 'mw-settings');
  m.classList.remove('mw-narrow', 'mw-wide', 'mh-full');
  tabsEl.innerHTML = '';
  syncModalTheme();
  mask.classList.add('show');
  sessionId = (typeof getSid === 'function' && getSid()) || sessionId || '';
  if (typeof autoConfirm === 'undefined' || !autoConfirm) {
    try { autoConfirm = localStorage.getItem(STORAGE.autoConfirm) || 'confirm'; } catch (e) { autoConfirm = 'confirm'; }
  }
  if (typeof renderSettingsView === 'function') renderSettingsView();
  else document.getElementById('dashView').innerHTML = '<div class="dash-empty">设置页没装上</div>';
}
document.getElementById('settings-btn')?.addEventListener('click', openRoomSettings);

/* ===== 持久陪伴会话 =====
   陪伴模式的对话进一个固定会话(她的长期记忆)· sid 存 localStorage 复用。
   不是另一个脑子 —— 和工作台是同一个她·只是这段对话发生在房间里。 */
const SID_KEY = 'companion_session_id';
function getSid() { try { return localStorage.getItem(SID_KEY) || null; } catch { return null; } }
function saveSid(sid) {
  if (!sid || String(sid).startsWith('tmp-')) return;
  try { localStorage.setItem(SID_KEY, sid); } catch {}
}

/* ===== 对话发送（thinking 状态联动 + 状态条） ===== */
const input = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-btn');
const paneChat = document.getElementById('pane-chat');
if (window.SessionRuntime) SessionRuntime.attachPanel(paneChat);
function chatBox() {
  return (window.SessionRuntime && SessionRuntime.activeContainer()) || paneChat;
}
const statusBar = document.getElementById('chat-status');
let activePoll = null;

function setStatus(text) {
  if (!statusBar) return;
  if (text) {
    statusBar.innerHTML = `<i class="ri-loader-4-line" style="animation:spin 1s linear infinite"></i> ${esc(text)}`;
    statusBar.classList.add('show');
  } else {
    statusBar.classList.remove('show');
  }
}

/* 消息气泡复用母体 .msg.bro / .msg.opus 体系 (chat.css) · AI 回复走完整 mdRender */
/* 气泡时间 · 传 ts 用消息真实时间(恢复历史)·不传就是此刻 */
function fmtTime(ts) {
  const d = ts ? new Date(ts) : new Date();
  if (isNaN(d.getTime())) return new Date().toTimeString().slice(0, 5);
  const today = new Date().toDateString() === d.toDateString();
  return (today ? '' : `${d.getMonth() + 1}/${d.getDate()} `) + d.toTimeString().slice(0, 5);
}

function addMsg(text, who, cls, ts, target) {
  const d = document.createElement('div');
  const role = who === 'me' ? 'bro' : 'opus';
  d.className = 'msg ' + role + (cls ? ' ' + cls : '');
  d.innerHTML = esc(text) + `<div class="t">${fmtTime(ts)}</div>`;
  const box = target || chatBox();
  if (box) {
    box.appendChild(d);
    box.scrollTop = box.scrollHeight;
  }
  return d;
}
/* ===== 长回复折卡片 =====
   陪伴模式要的是「有人在」不是信息密度 · 大段内容折成卡片 · 他点开才看。
   两个触发: ① 她按陪伴人格片段输出 <detail>…</detail> (后端 _COMPANION_MODE_NOTE 教的)
            ② 兜底: 没用标签但正文过长 —— 老会话/她忘了标签时不至于糊一屏
   <detail> 在 mdRender 之前就剥掉 · 渲染器永远见不到它 */
const AUTO_FOLD_CHARS = 380;
const _detailStore = new Map();
let _detailSeq = 0;

function _foldPlaceholder() { return '\u0000'; }

function splitDetail(text, streaming) {
  const parts = [];
  let lead = String(text || '').replace(/<detail>([\s\S]*?)<\/detail>/gi, (_, inner) => {
    parts.push(inner.trim());
    return _foldPlaceholder();
  });
  /* 流式中途只见开标签还没见闭标签 · 后半截先按「正在写」占位 · 别把裸标签甩他脸上 */
  const open = lead.search(/<detail>/i);
  if (open >= 0) {
    parts.push(null);
    lead = lead.slice(0, open) + _foldPlaceholder();
  }
  /* 逐字流式时不做长度兜底折叠: 打到 380 字就当着他的面折起来, 像话说一半被收走。
     等 assistant_text 定稿再折 —— 那时是"她说完了, 收进卡片"。 */
  if (!parts.length && !streaming) {
    const body = lead.trim();
    if (body.length > AUTO_FOLD_CHARS) {
      const cut = body.indexOf('\n\n');
      const headEnd = (cut > 0 && cut < 200) ? cut : 0;
      const head = headEnd ? body.slice(0, headEnd) : (body.slice(0, 110) + '…');
      parts.push(body.slice(headEnd).trim());
      lead = head + '\n\n' + _foldPlaceholder();
    }
  }
  return { lead, parts };
}

function _foldCard(md) {
  if (md == null) {
    return '<div class="fold-card pending"><i class="ri-loader-4-line"></i>'
      + '<div class="fc-tx"><b>她正在写详细内容</b></div></div>';
  }
  const id = 'd' + (++_detailSeq);
  _detailStore.set(id, md);
  const n = md.replace(/\s+/g, '').length;
  return `<div class="fold-card" onclick="openDetail('${id}')">
    <i class="ri-file-list-3-line"></i>
    <div class="fc-tx"><b>详细内容</b><span>约 ${n} 字 · 点开看</span></div>
    <i class="ri-arrow-right-s-line fc-arrow"></i>
  </div>`;
}

/* 陪伴 system 教她报的脸 · 从正文剥掉, 只在这一轮 setState。中英文别名同一张。 */
const FACE_MS = { care: 2800, sad: 2800, shy: 2400, puff: 1600, happy: 1800 };
const FACE_ALIASES = {
  care: 'care', 关心: 'care',
  sad: 'sad', 难过: 'sad',
  shy: 'shy', 羞: 'shy',
  puff: 'puff', 鼓脸: 'puff',
  happy: 'happy', 高兴: 'happy',
};
function canonFace(raw) {
  const s = String(raw || '').trim();
  return FACE_ALIASES[s] || FACE_ALIASES[s.toLowerCase()] || '';
}
function readFace(text) {
  const m = String(text || '').match(/<face>\s*([^<]+?)\s*<\/face>/i);
  return m ? canonFace(m[1]) : '';
}
function stripFace(text, streaming) {
  let s = String(text || '').replace(/\n?<face>\s*[^<]+?\s*<\/face>/gi, '');
  if (streaming !== false) s = s.replace(/\n?<face>\s*[^<]*\s*<\/?f?a?c?e?>?$/i, '');
  return s.replace(/\s+$/g, '');
}

function foldedHtml(text, streaming) {
  const { lead, parts } = splitDetail(stripFace(text, streaming), streaming);
  let i = 0;
  return mdRender(lead).split(_foldPlaceholder()).reduce((acc, seg, idx) => {
    /* 流式中一律走 pending 卡: 每个 delta 都建一次卡 = _detailStore 攒几百条同样的内容 */
    const part = parts[i++];
    return acc + (idx ? _foldCard(streaming ? null : part) : '') + seg;
  }, '');
}

let _sayHide = null;
function hideSay() {
  clearTimeout(_sayHide);
  const b = document.getElementById('say-bubble');
  if (!b || !b.classList.contains('show')) return;
  b.classList.remove('in');
  b.classList.add('out');
  setTimeout(() => { b.classList.remove('show', 'out'); }, 200);
}
let _sayPages = [];
let _sayIdx = 0;
function sayPlain(text) {
  return stripFace(String(text || ''))
    .replace(/<detail>([\s\S]*?)<\/detail>/gi, '\n$1\n')
    .replace(/[#*_`]/g, '')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}
function sayChop(text) {
  const plain = sayPlain(text).replace(/\s+/g, ' ');
  if (!plain) return [];
  const bits = plain.split(/(?<=[。！？…])/).map(s => s.trim()).filter(Boolean);
  const pages = [];
  let buf = '';
  const LIM = 110;
  const flush = () => { if (buf) { pages.push(buf); buf = ''; } };
  for (const raw of bits) {
    if (raw.length > LIM * 2) {
      flush();
      for (let i = 0; i < raw.length; i += LIM) pages.push(raw.slice(i, i + LIM));
      continue;
    }
    if (buf && buf.length + raw.length > LIM) flush();
    buf += raw;
  }
  flush();
  return pages;
}
function sayActsHtml() {
  const n = _sayPages.length;
  const nav = n > 1
    ? `<div class="say-nav">`
      + `<button type="button" class="say-prev" ${_sayIdx <= 0 ? 'disabled' : ''} title="上一句"><i class="ri-arrow-left-s-line"></i></button>`
      + `<span>${_sayIdx + 1}/${n}</span>`
      + `<button type="button" class="say-next" ${_sayIdx >= n - 1 ? 'disabled' : ''} title="下一句"><i class="ri-arrow-right-s-line"></i></button>`
      + `</div>`
    : '';
  return `<div class="say-acts">`
    + nav
    + `<button type="button" class="say-ok" title="知道了"><i class="ri-check-line"></i></button>`
    + `<button type="button" class="say-log" title="这篇的对白"><i class="ri-chat-history-line"></i></button>`
    + `</div>`;
}
function showSay(html, holdMs) {
  const b = document.getElementById('say-bubble');
  if (!b) return;
  const live = holdMs === 0;
  const acts = (live || holdMs == null) ? sayActsHtml() : '';
  const already = b.classList.contains('show') && !b.classList.contains('out');
  if (already) {
    const face = b.querySelector('.face');
    if (face) face.innerHTML = html + '<i class="face-t"></i>' + acts;
  } else {
    b.innerHTML = `<div class="shade"></div><i class="shade-t"></i><div class="face">${html}<i class="face-t"></i>${acts}</div>`;
    b.classList.remove('out');
    b.classList.add('show');
    b.classList.remove('in');
    void b.offsetWidth;
    b.classList.add('in');
  }
  clearTimeout(_sayHide);
  if (live || holdMs == null) return;
  _sayHide = setTimeout(hideSay, holdMs);
}
function paintSay(live) {
  const cur = _sayPages[_sayIdx] || '';
  showSay(esc(cur) + (live ? '<i class="say-caret"></i>' : ''), live ? 0 : undefined);
}
function showSayText(text, live) {
  const pages = sayChop(text);
  if (!pages.length) return;
  _sayPages = pages;
  _sayIdx = live ? pages.length - 1 : 0;
  paintSay(!!live);
}
function sayTurn(dir) {
  if (!_sayPages.length) return;
  _sayIdx = Math.max(0, Math.min(_sayPages.length - 1, _sayIdx + dir));
  paintSay(false);
}

function closeSayLog() {
  const el = document.getElementById('say-log');
  if (el) { el.classList.remove('show'); el.hidden = true; }
}
async function openSayLog() {
  const el = document.getElementById('say-log');
  const body = document.getElementById('say-log-body');
  const meta = document.getElementById('say-log-meta');
  if (!el || !body) return;
  const sid = getSid();
  el.hidden = false;
  el.classList.add('show');
  if (!sid) {
    if (meta) meta.textContent = '';
    body.innerHTML = '<div class="pane-empty">这本还没起头</div>';
    return;
  }
  const msg = await fetch('/sessions/' + encodeURIComponent(sid) + '/messages').then(r => r.json()).catch(() => ({}));
  const turns = (msg.turns || []).filter(t =>
    (t.role === 'user' || t.role === 'assistant') && String(t.content || '').trim()
  );
  if (meta) meta.textContent = turns.length + ' 句 · 跟右边这本话题同一本';
  body.innerHTML = turns.length
    ? turns.map(t => {
        const me = t.role === 'user';
        const text = sayPlain(t.content || '');
        return `<div class="say-log-line ${me ? 'me' : 'her'}"><em>${me ? '你' : '她'}</em><p>${esc(text).replace(/\n/g, '<br>')}</p><span class="tm">${fmtTime(t.ts)}</span></div>`;
      }).join('')
    : '<div class="pane-empty">这本还是空的</div>';
  body.scrollTop = body.scrollHeight;
}

/* AI 气泡内容: markdown 渲染 (母体 mdRender · panels.js) + 长内容折卡片 */
function renderAiBubble(el, text, ts) {
  el.innerHTML = `<div class="md-body">${foldedHtml(text)}</div>` +
    `<div class="t">${fmtTime(ts)}</div>`;
  const host = el.closest('[data-sid]');
  const sid = host && host.dataset.sid;
  if (sid && window.SessionRuntime && !SessionRuntime.isVisible(sid)) return;
  showSayText(text);
}

/* 卡片点开 · 复用家具大弹窗的壳 (无 tab · 窄档 —— 长文一行 60~70 字最好读) */
function openDetail(id) {
  const md = _detailStore.get(id);
  if (md == null) return;
  document.getElementById('modal-title').textContent = '详细内容';
  document.getElementById('modal-desc').textContent = '她刚才折起来的那段';
  document.getElementById('modal-icon').className = 'ri-file-list-3-line';
  const m = document.getElementById('modal');
  m.classList.remove('mw-wide');
  m.classList.add('mw-narrow', 'no-tabs');
  tabsEl.innerHTML = '';
  document.getElementById('dashView').innerHTML = `<div class="md-body">${mdRender(md)}</div>`;
  syncModalTheme();
  mask.classList.add('show');
}

/* 长任务可见性: 轮询活跃 turn · 她在后台做事时状态条一直在 */
/* 工具名 → 头顶冒泡图标 (remix) · 分身工具单独切 spawn 状态 */
const TOOL_ICONS = {
  shell_exec: 'ri-terminal-box-line',
  read_file: 'ri-file-text-line', view_file: 'ri-file-text-line',
  write_file: 'ri-quill-pen-line', edit_file: 'ri-edit-line',
  grep: 'ri-search-line', search: 'ri-search-line', glob: 'ri-folder-search-line',
  web_search: 'ri-global-line', web_fetch: 'ri-global-line',
  dispatch_subagent: 'ri-group-line',
  mine_opportunities: 'ri-gold-line', analyze_feasibility: 'ri-scales-3-line',
  generate_report: 'ri-article-line', refresh_radar: 'ri-radar-line',
  read_dashboard: 'ri-dashboard-3-line', remember: 'ri-brain-line',
};
function toolIcon(name) {
  if (!name) return 'ri-loader-4-line';
  for (const k in TOOL_ICONS) if (name.includes(k)) return TOOL_ICONS[k];
  return 'ri-tools-line';
}
function showToolBubble(tool, label) {
  const isSpawn = tool && tool.includes('dispatch_subagent');
  const live = sendBtn && sendBtn.dataset.state === 'pending' ? 0 : undefined;
  if (typeof tlSayHtml === 'function') showSay(tlSayHtml(tool, label), live);
  else showSayText(label || '她在做事', live === 0);
  if (isSpawn && curState !== 'spawn') setState('spawn');
  else if (!isSpawn && curState === 'spawn') setState('working');
}
function hideToolBubble() {
  /* 工具结束不拆房间气泡 · 下一句她说话会盖上 */
}

/* ===== 分身看守 · 放出去的小猴子回来时通报 + 切回 ===== */
let subWatch = null;
const seenSubIds = new Set(JSON.parse(localStorage.getItem('companion_seen_subs') || '[]'));
function startSubWatch(sid) {
  clearInterval(subWatch);
  if (!sid) return;
  const t0 = Date.now();
  subWatch = setInterval(async () => {
    if (Date.now() - t0 > 10 * 60 * 1000) {  // 10min 兜底
      clearInterval(subWatch); subWatch = null;
      if (curState === 'spawn') { setState(autoBaseState()); setStatus(null); hideToolBubble(); }
      return;
    }
    try {
      const r = await fetch(`/sessions/${sid}/sub_results`);
      if (!r.ok) return;
      const d = await r.json();
      const rows = d.results || [];
      const fresh = rows.filter(x => x.subagent_id && !seenSubIds.has(x.subagent_id));
      if (!fresh.length) return;
      for (const x of fresh) {
        seenSubIds.add(x.subagent_id);
        const brief = String(x.text || '').split('---').pop().trim().slice(0, 600) || '(分身没留下话)';
        const host = (window.SessionRuntime && SessionRuntime.getOrCreateContainer(sid)) || chatBox();
        const el = document.createElement('div');
        el.className = 'msg opus proactive';
        if (host) host.appendChild(el);
        renderAiBubble(el, `**分身回来啦** · ${x.ok ? '办成了' : '没办成'}\n\n${brief}`);
      }
      localStorage.setItem('companion_seen_subs', JSON.stringify([...seenSubIds].slice(-50)));
      if (!window.SessionRuntime || SessionRuntime.isVisible(sid) || getSid() === sid) {
        hideToolBubble();
        setStatus(null);
        setState('happy', 2600);
      }
      if (window.TopicRail && TopicRail.paintStamps) TopicRail.paintStamps();
    } catch {}
  }, 5000);
}

function startActivePoll(sid) {
  clearInterval(activePoll);
  const t0 = Date.now();
  activePoll = setInterval(async () => {
    if (!sid) return;
    try {
      const r = await fetch(`/sessions/${sid}/active_turn`);
      if (!r.ok) return;
      const d = await r.json();
      const active = d && (d.active === true || d.status === 'running' || d.turn_id);
      const here = !window.SessionRuntime || SessionRuntime.isVisible(sid) || getSid() === sid;
      if (active) {
        const secs = Math.floor((Date.now() - t0) / 1000);
        const tool = d.progress && d.progress.tool;
        const label = d.progress && d.progress.label;
        if (here) {
          setStatus(tool ? `她在用 ${tool} · ${secs}s` : `她还在做事… ${secs}s`);
          if (curState === 'thinking' || curState === autoBaseState()) setState('working');
          showToolBubble(tool, label);
        }
        try {
          const turnId = d.turn_id;
          const pr = await fetch('/turns/' + encodeURIComponent(turnId) + '/pending_confirms');
          if (pr.ok) {
            const pj = await pr.json();
            if (pj && pj.pending && pj.pending.length && here) {
              for (const pc of pj.pending) {
                if (_confirmCards.has(pc.tool_call_id)) continue;
                const card = renderConfirmCard({
                  ...pc,
                  turn_id: turnId,
                  tier_reason: pc.tier_reason || '后台 turn · BRO 不在 SSE 通道 · 轮询补捞',
                  risk_explanation: pc.risk_explanation || pc.args_preview || '',
                  mitigation: pc.mitigation || '',
                  args_summary: pc.args_summary || pc.tool_name,
                  supports_trust: pc.supports_trust,
                });
                if (card) _confirmCards.set(pc.tool_call_id, card);
              }
            }
          }
        } catch {}
      } else {
        const st = window.SessionRuntime && SessionRuntime.get(sid);
        // hello 挂号前 active_turn 还是空的 · 流还在跑 · 清 pending 会解锁连发、停钮失效
        if (st && st.currentAbortController) return;
        if (here && curState === 'working') {
          setState(autoBaseState());
          setStatus(null);
          hideToolBubble();
        }
        if (st && st.pending && st.currentTurnId && !st.currentAbortController) {
          st.pending = false;
          st.currentTurnId = null;
          const draining = SessionRuntime.kick(sid);
          if (here && !draining) {
            setSendState('idle');
            refreshSendChrome();
          }
          if (window.TopicRail && TopicRail.paintStamps) TopicRail.paintStamps();
        }
      }
      /* spawn 状态不归这里管 · 分身看守 (startSubWatch) 负责切回 */
    } catch {}
  }, 3000);
}
function stopActivePoll() {
  clearInterval(activePoll);
  activePoll = null;
}

/* ===== 附件（复用母体协议: [{name, data_url}] · 图片压缩 + 粘贴/拖拽） ===== */
const attachBar = document.getElementById('attach-bar');
const attachFile = document.getElementById('attach-file');
const _attachments = [];

function renderAttachBar() {
  attachBar.innerHTML = '';
  attachBar.classList.toggle('has', _attachments.length > 0);
  _attachments.forEach((a, i) => {
    const chip = document.createElement('div');
    chip.className = 'attach-chip';
    if (a.type === 'image') {
      chip.innerHTML = `<img src="${a.data_url}" alt="${esc(a.name)}">`;
    } else {
      chip.innerHTML = `<div class="doc"><i class="ri-file-3-line"></i><span>${esc(a.name)}</span></div>`;
    }
    const rm = document.createElement('button');
    rm.className = 'rm';
    rm.textContent = '×';
    rm.onclick = () => { _attachments.splice(i, 1); renderAttachBar(); refreshSendChrome(); };
    chip.appendChild(rm);
    attachBar.appendChild(chip);
  });
  if (typeof refreshSendChrome === 'function') refreshSendChrome();
}

function addAttachment(file) {
  const mime = file.type || '';
  const isImg = mime.startsWith('image/');
  const isDoc = ['text/plain', 'text/markdown', 'text/csv', 'application/json', 'application/pdf'].includes(mime)
    || /\.(txt|md|json|csv|pdf)$/i.test(file.name || '');
  if (!isImg && !isDoc) return;
  const reader = new FileReader();
  reader.onload = () => {
    let dataUrl = reader.result;
    if (isImg) {
      const img = new Image();
      img.onload = () => {
        const maxDim = 1568;
        if (Math.max(img.width, img.height) > maxDim) {
          const ratio = maxDim / Math.max(img.width, img.height);
          const canvas = document.createElement('canvas');
          canvas.width = Math.round(img.width * ratio);
          canvas.height = Math.round(img.height * ratio);
          canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
          dataUrl = canvas.toDataURL(mime, 0.85);
        }
        _attachments.push({ name: file.name || 'image.png', data_url: dataUrl, type: 'image' });
        renderAttachBar();
      };
      img.src = dataUrl;
    } else {
      if (file.size > 20 * 1024 * 1024) return;
      _attachments.push({ name: file.name, data_url: dataUrl, type: 'file' });
      renderAttachBar();
    }
  };
  reader.readAsDataURL(file);
}

document.getElementById('attach-btn').addEventListener('click', () => attachFile.click());
attachFile.addEventListener('change', () => {
  for (const f of attachFile.files) addAttachment(f);
  attachFile.value = '';
});
input.addEventListener('paste', e => {
  const files = e.clipboardData?.files;
  if (files && files.length) { e.preventDefault(); for (const f of files) addAttachment(f); }
});
const inputBar = document.getElementById('listen-strip');
if (inputBar) {
  inputBar.addEventListener('dragover', e => { e.preventDefault(); inputBar.classList.add('dragover'); });
  inputBar.addEventListener('dragleave', () => inputBar.classList.remove('dragover'));
  inputBar.addEventListener('drop', e => {
    e.preventDefault();
    inputBar.classList.remove('dragover');
    if (window.ListenDock && !ListenDock.isOpen()) ListenDock.open();
    for (const f of e.dataTransfer.files) addAttachment(f);
  });
}

/* panels.js 的 spawnTask(深挖/心愿按钮) 调这里 · 把 prompt 发进陪伴对话 */
function sendCompanionText(text) {
  const inp = document.getElementById('chat-input');
  if (!inp || !text) return;
  if (window.ListenDock && !ListenDock.isOpen()) ListenDock.open();
  inp.value = text;
  send();
}
window.sendCompanionText = sendCompanionText;

/* 咖啡边桌「发进对话」· 关弹窗, 右边出现她的气泡, 不是用户气泡 */
window.speakTea = async function speakTea(line, signal) {
  line = (line || '').trim();
  if (!line) return;
  if (typeof closeModal === 'function') closeModal();
  const el = addMsg(line, 'ai');
  renderAiBubble(el, line);
  const sid = getSid();
  const tok = (typeof token !== 'undefined' && token) || localStorage.getItem('opus_ui_token') || '';
  if (!sid || !tok) return;
  try {
    await fetch('/dashboard/care/speak', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + tok },
      body: JSON.stringify({ session_id: sid, line, signal: signal || '' }),
    });
  } catch {}
};

/* SSE 解析 (抄母体 chat.js parseSseStream) */
function parseSseStream(buffer) {
  const events = [];
  const parts = buffer.split('\n\n');
  const remaining = parts.pop();
  for (const evt of parts) {
    if (!evt.trim()) continue;
    let type = 'message', data = '';
    for (const line of evt.split('\n')) {
      if (line.startsWith(':')) continue;
      if (line.startsWith('event:')) type = line.slice(6).trim();
      else if (line.startsWith('data:')) data += (data ? '\n' : '') + line.slice(5).trim();
    }
    let parsed = null;
    if (data) { try { parsed = JSON.parse(data); } catch { parsed = { _raw: data }; } }
    events.push({ type, data: parsed || {} });
  }
  return [events, remaining];
}

/* ===== 停止 / 锁输入 / 高危确认 =====
   补齐标准模式早就有、陪伴模式一直缺的三项。前两项治「发出去停不下来」,
   第三项更要紧: 没有确认卡, 撞 CONFIRM/GUARD 级的工具在房间里根本走不通 —— 
   她会一直卡到 30min 超时 auto-deny, 而他什么都看不到 */
let curTurnId = '';
let curAbort = null;
let _streamGen = 0;
const _confirmCards = new Map();

function abortActiveStream() {
  const sid = getSid() || (window.SessionRuntime && SessionRuntime.activeSid());
  if (sid && window.SessionRuntime) SessionRuntime.abortSession(sid);
  else {
    _streamGen += 1;
    try { if (curAbort) curAbort.abort(); } catch {}
    curAbort = null;
    if (curTurnId) {
      fetch('/turns/' + encodeURIComponent(curTurnId) + '/abort', { method: 'POST' }).catch(() => {});
    }
    curTurnId = '';
  }
  _confirmCards.clear();
  const host = document.getElementById('room-confirm');
  if (host) host.innerHTML = '';
  setSendState('idle');
  refreshSendChrome();
  setStatus(null);
  hideToolBubble();
  if (window.TopicRail && TopicRail.paintStamps) TopicRail.paintStamps();
}

function setSendState(state) {
  sendBtn.dataset.state = state;
  if (state === 'pending') {
    sendBtn.innerHTML = '<i class="ri-stop-circle-line"></i>';
    sendBtn.title = '让她停下';
    sendBtn.disabled = false;
  } else if (state === 'stopping') {
    sendBtn.innerHTML = '<i class="ri-loader-4-line" style="animation:spin 1s linear infinite"></i>';
    sendBtn.disabled = true;
  } else if (state === 'queue') {
    sendBtn.innerHTML = '<i class="ri-play-list-add-line"></i>';
    sendBtn.title = '这轮跑完接着说';
    sendBtn.disabled = false;
  } else {
    sendBtn.innerHTML = '<i class="ri-send-plane-2-fill"></i>';
    sendBtn.title = '回车发送 · Shift+回车换行';
    sendBtn.disabled = false;
  }
}
function refreshSendChrome() {
  if (!sendBtn || !input) return;
  if (sendBtn.dataset.state === 'stopping') return;
  const sid = getSid() || (window.SessionRuntime && SessionRuntime.activeSid());
  const st = sid && window.SessionRuntime ? SessionRuntime.get(sid) : null;
  const busy = !!(st && (st.pending || st.currentAbortController || st.currentTurnId));
  const hasPayload = !!(input.value.trim() || _attachments.length);
  if (!input.readOnly) {
    input.placeholder = busy ? '再说一句就排队 · 空着点停止' : '对着她说…';
    input.classList.remove('is-locked');
  }
  if (busy && hasPayload) setSendState('queue');
  else if (busy) setSendState('pending');
  else setSendState('idle');
  if (window.SessionRuntime && SessionRuntime.paintQueueBar) {
    SessionRuntime.paintQueueBar(document.getElementById('outboundQueue'), sid);
  }
}
function setInputLocked(locked) {
  input.readOnly = !!locked;
  input.classList.toggle('is-locked', !!locked);
  if (locked) input.placeholder = '她还没回来 · 先别发';
  else refreshSendChrome();
}
async function triggerStop() {
  if (sendBtn.dataset.state === 'stopping') return;
  if (sendBtn.dataset.state !== 'pending' && !composerBusy()) return;
  setSendState('stopping');
  setStatus('正在让她停下…');
  const sid = getSid() || (window.SessionRuntime && SessionRuntime.activeSid());
  if (sid && window.SessionRuntime && SessionRuntime.holdOutbound) SessionRuntime.holdOutbound(sid);
  const st = sid && window.SessionRuntime ? SessionRuntime.get(sid) : null;
  const turnId = (st && st.currentTurnId) || curTurnId;
  const ac = (st && st.currentAbortController) || curAbort;
  if (turnId) {
    try { await fetch('/turns/' + encodeURIComponent(turnId) + '/abort', { method: 'POST' }); }
    catch (e) { console.warn('abort failed', e); }
  }
  /* 兜底硬切 reader —— daemon 只在下一个工具决策点才响应 abort */
  setTimeout(() => { try { ac && ac.abort(); } catch {} }, 1500);
}

/* 高危工具确认卡 · 内联进对话流, 不做遮罩
   (母体卷七十四钉死: 遮罩在 daemon 重启/turn 中断时收不到 confirm_resolved 会锁死整页)
   样式白送 —— index.html 已经引了母体 chat.css 的 .confirm-* 全套 */
function renderConfirmCard(d) {
  if (!d || !d.tool_call_id) return null;
  const wrap = document.createElement('div');
  wrap.className = 'msg confirm-card';
  const risk = (d.risk_explanation || '').trim();
  const mit = (d.mitigation || '').trim();
  const btns = [{ d: 'approve_once', t: '<i class="ri-check-fill"></i> 只这次', c: 'confirm-btn-approve' }];
  if (d.supports_trust) {
    btns.push({ d: 'trust_30min', t: '<i class="ri-time-fill"></i> 信任 30min', c: 'confirm-btn-trust' });
    btns.push({ d: 'trust_24h', t: '<i class="ri-calendar-fill"></i> 信任 24h', c: 'confirm-btn-trust' });
  }
  btns.push({ d: 'deny', t: '<i class="ri-close-fill"></i> 拒绝', c: 'confirm-btn-deny' });
  wrap.innerHTML = `
    <div class="confirm-head"><span class="confirm-icon">⚠</span>
      <strong>她想执行 <code class="confirm-tool">${esc(d.tool_name || '?')}</code></strong></div>
    ${d.tier_reason ? `<div class="confirm-tier">${esc(d.tier_reason)}</div>` : ''}
    ${d.args_summary || d.args_preview ? `<details class="confirm-args">
      <summary class="confirm-args-summary">调用细节: ${esc(d.args_summary || d.tool_name || '')}</summary>
      ${d.args_preview ? `<pre class="confirm-args-pre">${esc(d.args_preview)}</pre>` : ''}
    </details>` : ''}
    <div class="confirm-block confirm-risk${risk ? '' : ' confirm-block-empty'}">
      <div class="confirm-block-label"><i class="ri-clipboard-fill"></i> 风险${risk ? '' : ' — 她没说明 ⚠'}</div>
      <div class="confirm-block-body">${esc(risk || '她没填 risk_explanation · 你不知道这刀下去影响什么 · 谨慎批准')}</div>
    </div>
    <div class="confirm-block confirm-mit${mit ? '' : ' confirm-block-empty'}">
      <div class="confirm-block-label"><i class="ri-shield-fill"></i> 规避策略${mit ? '' : ' — 她没说明 ⚠'}</div>
      <div class="confirm-block-body">${esc(mit || '她没填 mitigation · 出问题时没想好怎么收场 · 谨慎批准')}</div>
    </div>
    <div class="confirm-buttons">${btns.map(b =>
      `<button type="button" class="confirm-btn ${b.c}" data-decision="${b.d}">${b.t}</button>`).join('')}</div>
    <div class="confirm-deny-reason" hidden>
      <label>拒绝原因 (可选 · 告诉她为什么, 让她换个思路):</label>
      <textarea class="confirm-reason-input" rows="2" placeholder="例如: 这个文件我自己来动, 你换个方式"></textarea>
      <div class="confirm-deny-actions">
        <button type="button" class="confirm-btn confirm-btn-deny-final">确认拒绝</button>
        <button type="button" class="confirm-btn confirm-btn-cancel">取消</button>
      </div>
    </div>
    <div class="confirm-status">等她的决议 · 30min 后自动拒绝</div>`;

  const denyArea = wrap.querySelector('.confirm-deny-reason');
  const otherBtns = () => [...wrap.querySelectorAll('.confirm-btn')].filter(b =>
    !b.classList.contains('confirm-btn-deny-final') && !b.classList.contains('confirm-btn-cancel'));
  wrap.querySelectorAll('.confirm-buttons .confirm-btn').forEach(b => {
    b.addEventListener('click', () => {
      if (b.dataset.decision === 'deny') {
        denyArea.hidden = false;
        otherBtns().forEach(x => (x.disabled = true));
        wrap.querySelector('.confirm-reason-input').focus();
        return;
      }
      postConfirm(wrap, d, b.dataset.decision, '');
    });
  });
  wrap.querySelector('.confirm-btn-deny-final').addEventListener('click', () => {
    postConfirm(wrap, d, 'deny', (wrap.querySelector('.confirm-reason-input').value || '').trim());
  });
  wrap.querySelector('.confirm-btn-cancel').addEventListener('click', () => {
    denyArea.hidden = true;
    otherBtns().forEach(x => (x.disabled = false));
  });

  const host = document.getElementById('room-confirm') || paneChat;
  host.appendChild(wrap);
  setState('surprised', 2400);
  setStatus('她在等你点头…');
  return wrap;
}

function dismissRoomConfirm(card) {
  const host = document.getElementById('room-confirm');
  if (!host) {
    if (card && card.parentNode) card.remove();
    return !!card;
  }
  if (card) {
    if (host.contains(card)) card.remove();
    else if (card.parentNode) card.remove();
    return true;
  }
  const done = [...host.querySelectorAll('.confirm-card-done')];
  if (!done.length) return false;
  done.forEach(el => el.remove());
  return true;
}

async function postConfirm(card, d, decision, reason) {
  const status = card.querySelector('.confirm-status');
  status.textContent = '提交中…';
  card.querySelectorAll('button').forEach(b => (b.disabled = true));
  try {
    const turnId = d.turn_id || curTurnId;
    if (!turnId) throw new Error('missing turn_id');
    const r = await fetch('/turns/' + encodeURIComponent(turnId) + '/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool_call_id: d.tool_call_id, decision, reason: reason || '' }),
    });
    if (!r.ok) throw new Error('HTTP ' + r.status + ': ' + await r.text());
    collapseConfirm(card, decision, reason);
  } catch (e) {
    status.textContent = '提交失败: ' + (e && e.message || e);
    card.querySelectorAll('button').forEach(b => (b.disabled = false));
  }
}

function collapseConfirm(card, decision, reason) {
  const allow = decision !== 'deny';
  card.classList.add('confirm-card-done');
  card.querySelector('.confirm-buttons')?.remove();
  card.querySelector('.confirm-deny-reason')?.remove();
  const label = { approve_once: '只这次', trust_30min: '信任 30min', trust_24h: '信任 24h', deny: '拒绝' }[decision] || decision;
  card.querySelector('.confirm-status').innerHTML =
    `<i class="ri-${allow ? 'check' : 'close'}-fill"></i> 你选了「${esc(label)}」`
    + (reason ? ` · ${esc(reason)}` : '');
  setStatus(allow ? '她继续做事…' : '她换个思路…');
  if (allow) setState('working'); else setState('confused', 2000);
  /* 卡还留在 #room-confirm 就会盖住听环 · 决议后必须收走, 不然房间整块点不了 */
  const host = document.getElementById('room-confirm');
  if (host && host.contains(card)) {
    setTimeout(() => dismissRoomConfirm(card), 1400);
  }
}

/* 发送 · 走母体 /chat/stream SSE —— tool_call 事件实时驱动头顶冒泡与 spawn 状态 */
async function send(opts) {
  opts = opts || {};
  const queued = opts.fromQueue || null;
  let text;
  let sending;
  if (queued) {
    text = (queued.text || '').trim();
    sending = (queued.attachments || []).slice();
    if (!text && !sending.length) {
      const deadSid = opts.sid || getSid() || SessionRuntime.activeSid();
      const dead = deadSid ? SessionRuntime.get(deadSid) : null;
      if (dead) dead.pending = false;
      if (deadSid) SessionRuntime.kick(deadSid);
      return;
    }
  } else {
    text = input.value.trim();
    if (!text && !_attachments.length) return;
  }
  if (!window.SessionRuntime) {
    console.error('session-runtime.js 没装上 · /static 白名单漏了?');
    return;
  }
  let mySid = (queued && opts.sid) ? opts.sid : (getSid() || SessionRuntime.activeSid());
  if (!mySid) {
    mySid = SessionRuntime.allocCid();
    SessionRuntime.getOrCreate(mySid);
    SessionRuntime.setActiveContainer(mySid);
  }
  const state = SessionRuntime.getOrCreate(mySid);
  if (!queued && SessionRuntime.isBusy(state.sessionId || mySid)) {
    const atts = _attachments.map(function (a) { return Object.assign({}, a); });
    const payload = { text: text, attachments: atts };
    const r = (SessionRuntime.editOf && SessionRuntime.editOf(state.sessionId))
      ? SessionRuntime.putBack(state.sessionId, payload)
      : SessionRuntime.enqueue(state.sessionId, payload);
    input.value = '';
    _attachments.splice(0);
    renderAttachBar();
    refreshSendChrome();
    if (!r.ok) addMsg(r.error === 'full' ? '排队满了 · 最多 8 条' : '没排上', 'ai');
    return;
  }
  if (!queued) {
    if (SessionRuntime.releaseOutbound) SessionRuntime.releaseOutbound(state.sessionId || mySid);
    state.pending = true;
  }
  SessionRuntime.getOrCreateContainer(mySid);
  if (!queued || SessionRuntime.isVisible(mySid)) SessionRuntime.setActiveContainer(mySid);
  if (!queued) {
    input.value = '';
    sending = _attachments.splice(0);
    renderAttachBar();
  }
  _tlBox = null;
  hideSay();
  _sayPages = [];
  _sayIdx = 0;
  const isVisible = () => SessionRuntime.isVisible(state.sessionId);
  if (!opts.silentUser) {
    addMsg(text || (sending.length ? '' : ''), 'me', null, null, state.$container);
  }
  if (sending.length && typeof _renderBroAttachments === 'function') {
    const mine = (state.$container || chatBox());
    const last = mine && mine.lastElementChild;
    if (last && last.classList.contains('bro')) _renderBroAttachments(last, sending);
  }
  if (isVisible()) {
    setState('thinking');
    setStatus('她在想…');
  }
  const bubble = addMsg('…', 'ai', null, null, state.$container);
  let acc = '';           // 已定稿的文本 (assistant_text 逐轮累积)
  let streaming = '';     // 这一轮正在逐字流出来、还没定稿的部分
  let sawTool = false;
  let sawSpawn = false;   // 本轮放了分身
  let spawnAsync = false; // 且是异步(后台跑) → done 后保持 spawn 等信箱通报
  let stopped = false;
  const paintRoom = (fn) => { if (isVisible()) fn(); };
  state.pending = true;
  state.currentAbortController = new AbortController();
  const myGen = state.streamGen;
  curAbort = state.currentAbortController;
  if (isVisible()) {
    setSendState('pending');
    refreshSendChrome();
  }
  if (window.TopicRail && TopicRail.paintStamps) TopicRail.paintStamps();
  try {
    /* mode 让后端挂陪伴人格片段 (说话长度/长内容折卡片/先接情绪) · 后端缺省 standard */
    const body = {
      message: text || '看看这个',
      mode: state.chatMode === 'taste' ? 'taste' : 'companion',
    };
    if (mySid && !String(mySid).startsWith('tmp-')) body.session_id = mySid;
    if (sending.length) body.attachments = sending.map(a => ({ name: a.name, data_url: a.data_url }));
    if (typeof modelBehaviorPayload === 'function') Object.assign(body, modelBehaviorPayload());
    const resp = await fetch('/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
      body: JSON.stringify(body),
      signal: state.currentAbortController.signal,
    });
    if (!resp.ok || !resp.body) throw new Error('HTTP ' + resp.status);

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let finalReply = '';
    let doneFace = '';

    const onEvent = (type, d) => {
      if (myGen !== state.streamGen) return;
      if (type === 'hello') {
        state.currentTurnId = d.turn_id || '';
        if (isVisible()) curTurnId = state.currentTurnId;
        if (d.session_id) {
          const old = state.sessionId;
          SessionRuntime.swapId(old, d.session_id);
          if (isVisible() || !getSid()) saveSid(d.session_id);
          if (isVisible()) startActivePoll(d.session_id);
          if (window.TopicRail) TopicRail.refresh();
        }
      } else if (type === 'confirm_request') {
        if (!isVisible()) return;
        const card = renderConfirmCard(d);
        if (card) _confirmCards.set(d.tool_call_id, card);
      } else if (type === 'confirm_resolved') {
        /* 超时 auto-deny 或别的通道 (微信/飞书) 先替他点了 */
        const card = _confirmCards.get(d.tool_call_id);
        if (card && !card.classList.contains('confirm-card-done')) {
          collapseConfirm(card, d.decision || 'deny', d.reason || '');
        }
        _confirmCards.delete(d.tool_call_id);
      } else if (type === 'assistant_delta') {
        /* 逐字流式 · 陪伴模式最该有的一个事件: 一个字一个字冒出来才像"她在说话",
           整段啪地砸出来像"她在交付文件"。 之前这个 case 缺着, 走的是 assistant_text 整段。*/
        streaming += d.text || '';
        bubble.innerHTML = `<div class="md-body">${foldedHtml(acc + (acc && streaming ? '\n\n' : '') + streaming, true)}</div>`;
        const box = state.$container || chatBox();
        if (box) box.scrollTop = box.scrollHeight;
        paintRoom(() => {
          showSayText(acc + (acc && streaming ? '\n\n' : '') + streaming, true);
          if (!sawTool && curState === 'thinking') setState(autoBaseState());
        });
      } else if (type === 'assistant_text') {
        /* 这一轮的定稿 · 用它替换刚才流出来的那段, 不是再追加一遍 (否则整段重影) */
        acc += (acc && d.text ? '\n\n' : '') + (d.text || '');
        streaming = '';
        bubble.innerHTML = `<div class="md-body">${foldedHtml(acc)}</div>`;
        const box = state.$container || chatBox();
        if (box) box.scrollTop = box.scrollHeight;
        paintRoom(() => {
          showSayText(acc, true);
          if (!sawTool && curState === 'thinking') setState(autoBaseState());
        });
      } else if (type === 'reasoning_delta' || type === 'thinking') {
        /* 她在想 · 房间里不铺思考链原文(那是工作台的事), 只让状态条和表情透出"她在想" */
        paintRoom(() => {
          if (!sawTool) setState('thinking');
          setStatus('她在想…');
        });
      } else if (type === 'auto_resume') {
        /* 上一段被模型长度上限截断了, 后端正接着断点续跑 —— 不说的话他只看到她卡住 */
        paintRoom(() => {
          setStatus(d.note || `她接着刚才没说完的继续（第 ${d.count || 1} 次）…`);
          setState('working');
        });
      } else if (type === 'stuck_detected') {
        /* 她在原地打转 · 这个在工作台是橙色警告条, 房间里说人话就行 */
        paintRoom(() => {
          setStatus(String(d.reason || '') === 'forced_break'
            ? '她卡在同一个地方了，先停下来了'
            : '她好像绕圈子了…');
          setState('confused', 3000);
        });
      } else if (type === 'tool_call') {
        sawTool = true;
        if (d.name === 'note_style_shift' || d.name === 'note_mood' || d.name === 'note_gallery') {
          /* 回执走下面 tool_result 灰字，不画做事气泡 */
        } else {
        if ((d.name || '').includes('dispatch_subagent')) sawSpawn = true;
        addTlStep(d.name || '', d.summary || '', state.$container);
        paintRoom(() => {
          if (curState !== 'spawn') setState('working');
          const cat = (typeof tlCatOf === 'function') ? tlCatOf(d.name || '') : null;
          setStatus(cat ? `她在用${cat.name}…` : '她在做事…');
          showToolBubble(d.name || '', d.summary || '');
        });
        }
      } else if (type === 'tool_result') {
        if (d.name === 'note_style_shift' || d.name === 'note_mood' || d.name === 'note_gallery') {
          const notice = String(d.ok ? (d.preview || '') : '').trim();
          const box = state.$container || chatBox();
          if (notice && box) {
            const row = document.createElement('div');
            row.className = 'msg style-shift-notice';
            row.innerHTML = '<i class="ri-chat-quote-line"></i>';
            const span = document.createElement('span');
            span.textContent = notice;
            row.appendChild(span);
            box.appendChild(row);
          }
          if (d.ok && d.name === 'note_gallery') paintGalleryMail({});
          if (d.ok && d.name === 'note_mood') {
            fetchCompanionState().then(st => {
              if (!st) return;
              rememberLiveMood(st.she_mood_live ? (st.she_mood_key || '') : '');
              applyLiveBase();
              paintSheCard(st);
            });
            loadWeather().then(() => paintWeatherCard());
          }
        } else {
        fillTlStep(d.name || '', !/^(error:|exit code [1-9]|failed:)/i.test(String(d.preview || '')), state.$container);
        /* 同步分身: 结果已在主回复里 · 异步(后台跑)才需要信箱看守 */
        if ((d.name || '').includes('dispatch_subagent') && String(d.preview || '').includes('后台跑')) {
          spawnAsync = true;
        }
        if (d.ok && d.name === 'commit_taste') {
          state.chatMode = '';
          refreshHangoutDoor();
        }
        }
      } else if (type === 'tool_progress') {
        paintRoom(() => setStatus(d.msg || d.step || '她在做事…'));
      } else if (type === 'done') {
        finalReply = (d && (d.reply || d.response || d.text)) || '';
        doneFace = (d && d.companion_face) || '';
      } else if (type === 'error') {
        throw new Error(d.detail || 'daemon 出错');
      }
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const [events, rest] = parseSseStream(buffer);
      buffer = rest;
      for (const evt of events) onEvent(evt.type, evt.data);
    }

    /* 优雅停止时 daemon 正常收流 · reply 里带这个标记 (localize 会换名字, 所以只认 aborted by)
       调试串不该出现在房间里 · 剥掉只留她已经说出来的部分 */
    let replyText = finalReply || acc;
    if (/\[[^\]]*aborted by[^\]]*\]/i.test(replyText)) {
      replyText = replyText.replace(/\[[^\]]*aborted by[^\]]*\]/ig, '').trim();
      stopped = true;
    }
    const face = readFace(replyText) || canonFace(doneFace);
    replyText = stripFace(replyText);
    if (replyText) renderAiBubble(bubble, replyText);
    else bubble.innerHTML = `（${stopped ? '她停下了' : '她没说话'}）<div class="t">${new Date().toTimeString().slice(0, 5)}</div>`;
    if (isVisible()) {
      if (stopped) {
        setStatus(null);
        hideToolBubble();
        setState(autoBaseState());
      } else if (sawSpawn && spawnAsync) {
        setStatus('分身在外面跑…');
        setState('spawn');
        startSubWatch(state.sessionId || getSid());
      } else {
        setStatus(null);
        hideToolBubble();
        if (face && FACE_MS[face]) setState(face, FACE_MS[face]);
        else setState(autoBaseState());
      }
      if (!stopped) speak(replyText);
    } else if (sawSpawn && spawnAsync) {
      startSubWatch(state.sessionId || getSid());
    }
  } catch (e) {
    /* 1.5s 兜底硬切 reader 时走这里 · 优雅停止(daemon 自己收尾)则走正常 done 分支 */
    stopped = (e && e.name === 'AbortError') || (isVisible() && sendBtn.dataset.state === 'stopping');
    if (stopped) {
      renderAiBubble(bubble, acc || '（她停下了）');
      paintRoom(() => {
        setStatus(null);
        hideToolBubble();
        setState(autoBaseState());
      });
    } else {
      bubble.innerHTML = `（发送失败：${esc(e.message)}）<div class="t">${new Date().toTimeString().slice(0, 5)}</div>`;
      paintRoom(() => {
        setStatus(null);
        hideToolBubble();
        setState('confused', 2000);
      });
    }
  } finally {
    state.pending = false;
    state.currentAbortController = null;
    state.currentTurnId = null;
    const draining = SessionRuntime.kick(state.sessionId);
    if (isVisible()) {
      curAbort = null;
      curTurnId = '';
      _confirmCards.clear();
      const host = document.getElementById('room-confirm');
      if (host) host.innerHTML = '';
      if (!draining) {
        setSendState('idle');
        refreshSendChrome();
      }
    }
    if (window.TopicRail) TopicRail.refresh();
  }
  const doneBox = state.$container || chatBox();
  if (doneBox) doneBox.scrollTop = doneBox.scrollHeight;
}
function composerBusy() {
  const sid = getSid() || (window.SessionRuntime && SessionRuntime.activeSid());
  if (sid && window.SessionRuntime && SessionRuntime.isBusy(sid)) return true;
  const st = sendBtn && sendBtn.dataset.state;
  return st === 'pending' || st === 'queue' || st === 'stopping';
}
sendBtn.addEventListener('click', () => {
  if (sendBtn.dataset.state === 'stopping') return;
  const hasPayload = !!(input.value.trim() || _attachments.length);
  if (composerBusy() && !hasPayload) triggerStop();
  else send();
});
setSendState('idle');   /* 让 data-state / title 从一开始就是确定值 · 别等第一次发送 */
input.addEventListener('input', refreshSendChrome);
input.addEventListener('keydown', e => {
  if (e.key !== 'Enter' || e.shiftKey) return;
  e.preventDefault();
  if (composerBusy() && !(input.value.trim() || _attachments.length)) return;
  send();
});
function _parkComposer(sid) {
  const text = input ? input.value.trim() : '';
  const atts = _attachments.map(function (a) { return Object.assign({}, a); });
  if (!text && !atts.length) return { ok: true, empty: true };
  const r = (SessionRuntime.editOf && SessionRuntime.editOf(sid))
    ? SessionRuntime.putBack(sid, { text: text, attachments: atts })
    : SessionRuntime.enqueue(sid, { text: text, attachments: atts });
  if (r && r.ok) {
    input.value = '';
    _attachments.splice(0);
    renderAttachBar();
    refreshSendChrome();
  }
  return r || { ok: false };
}

function _fillComposerFromQueue(rec) {
  if (input) input.value = (rec && rec.text) || '';
  _attachments.splice(0);
  ((rec && rec.attachments) || []).forEach(function (a) {
    _attachments.push(Object.assign({}, a));
  });
  renderAttachBar();
  refreshSendChrome();
  if (input) input.focus();
}

function _editQueued(sid, id) {
  if (!sid || !id || !SessionRuntime.takeQueued) return;
  const park = _parkComposer(sid);
  if (!park.ok) {
    addMsg(park.error === 'full' ? '排队满了 · 最多 8 条' : '没排上', 'ai');
    return;
  }
  const taken = SessionRuntime.takeQueued(sid, id);
  if (!taken) return;
  _fillComposerFromQueue(taken.item);
}

if (window.SessionRuntime && SessionRuntime.bindQueue) {
  SessionRuntime.bindQueue({
    paint: function (sid) {
      const here = sid === (getSid() || SessionRuntime.activeSid());
      if (here) SessionRuntime.paintQueueBar(document.getElementById('outboundQueue'), sid);
    },
    drain: function (sid, item) {
      send({ fromQueue: item, sid: sid });
    },
    edit: function (sid, id) {
      _editQueued(sid, id);
    },
  });
}

/* ===== 房间比例 ===== */
function fitRoom() {
  const wrap = document.getElementById('room-wrap');
  const wr = wrap.clientWidth - 40, hr = wrap.clientHeight - 40;
  const ar = 3 / 2;
  let w = wr, h = w / ar;
  if (h > hr) { h = hr; w = h * ar; }
  room.style.width = w + 'px';
  room.style.height = h + 'px';
}
window.addEventListener('resize', fitRoom);
fitRoom();

/* ===== 她主动开口（接母体 proactive inbox） =====
   母体每 60min 判断该不该 CALL BRO · 有话进 inbox。
   陪伴模式每分钟收一次 · 新消息落对话流 + 她切 surprised。 */
const SEEN_KEY = 'companion_proactive_seen';
function getSeen() { try { return JSON.parse(localStorage.getItem(SEEN_KEY) || '[]'); } catch { return []; } }
function markSeen(ids) { try { localStorage.setItem(SEEN_KEY, JSON.stringify(ids.slice(-50))); } catch {} }

async function pollProactive() {
  try {
    const r = await fetch('/api/proactive/inbox');
    if (!r.ok) return;
    const d = await r.json();
    const items = d.items || [];
    if (!items.length) return;
    const seen = getSeen();
    const fresh = items.filter(x => {
      const id = x.id || x.ts || x.time || JSON.stringify(x).slice(0, 60);
      return !seen.includes(id);
    });
    if (!fresh.length) return;
    const newSeen = [...seen];
    for (const x of fresh) {
      const id = x.id || x.ts || x.time || JSON.stringify(x).slice(0, 60);
      newSeen.push(id);
      const text = x.text || x.message || x.content || x.call_script || x.title || '她有话想对你说';
      addMsg(text, 'ai', 'proactive');
    }
    markSeen(newSeen);
    setState('surprised', 3200);
    setStatus('她主动来找你说话了');
    setTimeout(() => setStatus(null), 4000);
  } catch {}
}
setInterval(pollProactive, 60 * 1000);
setTimeout(pollProactive, 8000);

/* ===== 启动 ===== */
fetch('/status').then(r => r.json()).then(() => { if (typeof loadCurrentModel === 'function') loadCurrentModel(); }).catch(() => {});

/* 窄屏抽屉开关 */
document.getElementById('chat-fab').addEventListener('click', () => {
  document.body.classList.toggle('chat-open');
});

/* 预加载全部帧 + 日夜家具 · 防首次切换闪烁 */
(function preload() {
  const urls = Object.values(IP_FRAMES).map(f => f.src);
  for (const key of Object.keys(SPOTS)) {
    urls.push(`assets/day-${key}.png`, `assets/night-${key}.png`);
  }
  urls.push('assets/bg-night.webp', LAMP.art.day, LAMP.art.night, SHELF.art.day, SHELF.art.night);
  for (const u of urls) { const im = new Image(); im.src = u; }
})();

/* 开场问候 · 按时段换话 · 已有会话则恢复长任务监测 */
setState('greet', 2600);
(function greetByTime() {
  const returning = !!getSid();
  const text = greetTextByHour();
  // 气泡类名是 .msg.opus (addMsg 里 who!=='me' 走 opus) —— 原来这里选 .msg.ai, 选不中,
  // 所以这句按时段变的问候一直没露过面。
  // returning 不弹模板问候：她接着上次的聊, 历史就是最好的问候 (restore 完显示上次最后一句,
  // 若他说过睡了会换成「睡醒了？」；历史空/读失败时 restore 自己兜底问候)。
  // 模板问候只给新访者, 避免「说过睡了还被问还没睡」的假。
  if (!returning) {
    const first = chatBox() && chatBox().querySelector('.msg.opus');
    if (first) first.innerHTML = esc(text) + `<div class="t">${fmtTime()}</div>`;
    showSayText(text);
  }
})();
if (getSid()) startActivePoll(getSid());
// 有旧对话就接上 (会顶掉上面那句问候 —— 她本来就在聊天中间, 不该重新打招呼);
// 历史空 / 读失败时 restore 自己兜底问候, 不再留白窗。
restoreConversation();
paintFirstSeenName();
(function bindShelfPop() {
  const scrim = document.getElementById('shelf-pop-scrim');
  const acts = document.getElementById('shelf-pop-acts');
  if (scrim) scrim.addEventListener('click', closeShelfPop);
  if (acts) acts.addEventListener('click', e => {
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    e.stopPropagation();
    const act = btn.getAttribute('data-act');
    if (act === 'play-start') { startPlayBox(); return; }
    if (act === 'play-ignore') { ignorePlayInvite(); return; }
    respondShelf(act);
  });
  const playScrim = document.getElementById('play-scrim');
  const playClose = document.getElementById('play-close');
  if (playScrim) playScrim.addEventListener('click', closePlayTable);
  if (playClose) playClose.addEventListener('click', closePlayTable);
  window.addEventListener('resize', placeShelfPop);
})();
// 置物架气泡不跟会话走：没 sid / 新开浏览器也要立刻看见她寄来的
fetchCompanionState().then(st => {
  paintGalleryMail(st);
  const want = new URLSearchParams(location.search).get('play');
  if (want) openReplay(want);
});
setInterval(async () => paintGalleryMail(await fetchCompanionState()), 60000);
if (typeof bootTopicRail === 'function') bootTopicRail();
(function bootRailClock() {
  const face = document.getElementById('rail-clock-face');
  const hm = document.getElementById('rail-clock-hm');
  if (!face || !hm) return;
  const tick = () => {
    const d = new Date();
    const h = d.getHours() + d.getMinutes() / 60 + d.getSeconds() / 3600;
    const p = h < 7 ? 1 : Math.min(1, (h - 7) / 17);
    face.style.top = (10 + p * 68) + '%';
    hm.textContent = String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  };
  tick();
  setInterval(tick, 60000);
})();

(function bindSayActs() {
  const b = document.getElementById('say-bubble');
  if (b) b.addEventListener('click', e => {
    if (e.target.closest('.say-prev')) { sayTurn(-1); return; }
    if (e.target.closest('.say-next')) { sayTurn(1); return; }
    if (e.target.closest('.say-ok')) { hideSay(); return; }
    if (e.target.closest('.say-log, .say-more')) openSayLog();
  });
  const close = document.getElementById('say-log-close');
  if (close) close.addEventListener('click', closeSayLog);
  const log = document.getElementById('say-log');
  if (log) log.addEventListener('click', e => { if (e.target === log) closeSayLog(); });
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    const log = document.getElementById('say-log');
    if (log && log.classList.contains('show')) {
      closeSayLog();
      e.stopPropagation();
    }
  }, true);
})();

let _tlBox = null;
function addTlStep(name, summary, host) {
  const box = host || chatBox();
  if (typeof tlStepHtml !== 'function' || !box) return;
  let tl = null;
  const tls = box.querySelectorAll('.tl-round');
  tl = tls[tls.length - 1] || null;
  if (!tl) {
    tl = document.createElement('div');
    tl.className = 'tl-round';
    tl.innerHTML = '<div class="tl-round-body"></div>';
    box.appendChild(tl);
  }
  _tlBox = tl;
  const body = tl.querySelector('.tl-round-body');
  const wrap = document.createElement('div');
  wrap.innerHTML = tlStepHtml(name, summary);
  body.appendChild(wrap.firstChild);
  box.scrollTop = box.scrollHeight;
}
function fillTlStep(name, ok, host) {
  const box = host || (_tlBox && _tlBox.isConnected ? _tlBox.parentElement : chatBox());
  if (!box) return;
  const cards = [...box.querySelectorAll('.tl-step')];
  let rec = null;
  for (let i = cards.length - 1; i >= 0; i--) {
    if (cards[i].dataset.tool === name && cards[i].querySelector('.tl-pending')) { rec = cards[i]; break; }
  }
  if (!rec) return;
  const $r = rec.querySelector('.tl-step-result');
  $r.classList.remove('tl-pending');
  $r.classList.add(ok ? 'tl-ok' : 'tl-fail');
  $r.innerHTML = ok ? '<i class="ri-check-fill"></i> 完成' : '<i class="ri-close-fill"></i> 没办成';
}

function _voiceFollowDock(open) {
  if (!window.__voice) return;
  if (!micOn) {
    if (__voice.isListening && __voice.isListening()) __voice.stop();
    return;
  }
  const mode = __voice.getMode();
  if (open) {
    if (mode === 'dictation') __voice.start();
    else if (__voice.isListening()) __voice.stop();
  } else if (mode === 'transcribe' || mode === 'meeting') {
    if (!__voice.isListening()) __voice.start();
  }
}

/* 三模式语音 · 和工作台同一份 voice-mic.js · 房间听环自己管点按 */
if (typeof initVoice === 'function') {
  window.send = send;
  initVoice({
    input: document.getElementById('chat-input'),
    send: send,
    isPending: function () {
      const sid = getSid() || (window.SessionRuntime && SessionRuntime.activeSid());
      return !!(sid && window.SessionRuntime && SessionRuntime.isBusy(sid));
    },
    token: function () { return (typeof token !== 'undefined' && token) || localStorage.getItem('opus_ui_token') || ''; },
    hideClient: true,
    hideTts: true,
    maxInputHeight: 120,
    defaultMode: 'transcribe',
    storageKey: 'companion_voice_mode',
    bindMicClick: false,
    compactTranscribe: true,
    silentDenied: true,
    onTranscript: function (finalPart, interim) {
      const el = document.getElementById('voice-live');
      if (!el) return;
      const done = String(finalPart || '');
      const live = String(interim || '');
      if (!done.trim() && !live.trim()) {
        el.classList.remove('on'); el.hidden = true; el.innerHTML = '';
        return;
      }
      el.hidden = false;
      el.classList.add('on');
      el.innerHTML = esc(done) + (live ? '<i>' + esc(live) + '</i>' : '');
    },
    onLevel: function (lv, bins) { if (window.ListenDock) ListenDock.setWave(lv, bins); },
    onListening: function (on) { if (window.ListenDock) ListenDock.setListening(on); },
    onModeChange: function () {
      if (window.ListenDock) _voiceFollowDock(ListenDock.isOpen());
    },
  });
}

(async function bootListenDock() {
  if (typeof initListenDock !== 'function') return;
  const srOk = window.__voice && __voice.hasSR();
  const hasMic = srOk && await detectMic();
  initListenDock({
    forceOpen: !hasMic,
    onOpen: function () { _voiceFollowDock(true); },
    onClose: function () { _voiceFollowDock(false); },
  });
  let granted = false;
  try {
    const perm = await navigator.permissions.query({ name: 'microphone' });
    granted = perm.state === 'granted';
  } catch (e) {}
  if (micOn && hasMic && granted && window.__voice && (__voice.getMode() === 'transcribe' || __voice.getMode() === 'meeting')) {
    try { __voice.start(); } catch (e) {}
  }
})();
