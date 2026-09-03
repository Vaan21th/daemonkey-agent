/* chat-rail.js · 提问轨道
 * 从 chat.js 抽出。只画用户消息刻度。不进 LLM 系统提示词。
 */
// ========== 提问轨道（Message Index Rail）· 社区贡献 · 2026-08-10 · v5 增量移植 2026-08-15 ==========
// 右侧一列集中连在一起的标记 · 只列用户消息（全部，无上限）
// 点击标记 → 平滑滚动定位到对应消息（闪烁高亮）· 悬停/聚焦 → 预览文字（截断 ~12 字）
// 磁性拉伸: 光标在轨道移动 → 影响半径内刻度按距离连续变长（smoothstep）· 离开回弹
// 滚动聊天区 → 当前可见消息对应标记高亮
// 适配母体: 主题色用 --opus 系 (非社区 --accent) · 父容器补 position:relative (chat-pane 无定位)
// 2026-08-15 v5 增量移植 (龙头提交): ①两段式预览(问题+回答片段) ②磁性驱动预览统一
//   (hover 不再依赖精准命中 6px 细条 · 光标靠近轨道即出预览) ③_railTopCache 免每帧读布局
const _RAIL_PREVIEW_LEN = 60;   // 预览截断字符上限 (v5: 12→60 · 两段式问题 ≤3 行)
const _RAIL_ANSWER_LEN = 200;   // 回答片段截断上限 (v5 新增 · ≤4 行)
const _RAIL_HOT_MIN = 0.75;     // 磁性预览触发阈值 (v5 · smoothstep 下 ≈ 指针距刻度 24px 内)
const _RAIL_MAGNET_RADIUS = 72;   // 磁性影响半径
const _RAIL_MAX_STRETCH = 52;     // 磁性拉伸最宽
const _RAIL_TOP_OFFSET = 120;     // rail 距消息区顶部
const _RAIL_BOTTOM_PAD = 16;      // 底部留白
let _railEl = null;
let _railTip = null;
let _railMarks = []; // [{ el, msgEl, baseW }]
let _railCenters = []; // 每个刻度相对 rail 顶的中心 y（缓存 · 磁性拉伸免每帧读布局）
let _railPointerY = null;         // 最近一次光标 y（视口坐标）
let _railRAF = null;              // 磁性拉伸 RAF 句柄
let _railHideTimer = null;        // safe zone 隐藏定时器
let _railSelfHealTimer = null;    // 兜底自愈轮询句柄 (2026-08-10 v3 · 防误隐藏后无事件恢复)
let _railPreviewIdx = -1;         // 磁性驱动预览跟随的当前刻度 (切换时才重建 DOM · v5)
let _railTopCache = null;         // rail 视口 top 缓存 (v5 · 磁性拉伸免每帧 getBoundingClientRect)
// 2026-08-15 磁性命中带 (BRO 反馈): rail 元素本身只有 ~20px 宽 · 鼠标从消息区滑过来
// 要精准够到细条才有反应 (中间镂空/左侧带"点不到")。扩成透明命中带: 左缘向左扩展
// _RAIL_HIT_ZONE px · document 级 pointermove 判断 · 靠近轨道即触发磁性+预览。
const _RAIL_HIT_ZONE = 48;        // 命中带向左扩展宽度 (px)
let _railHitRect = null;          // {left,right,top,bottom} 命中带缓存 · document handler 纯数值比较

function _ensureMsgRail() {
  if (_railEl) return _railEl;
  const panel = document.getElementById('messages');
  if (!panel) return null;
  _railEl = document.createElement('div');
  _railEl.className = 'msg-rail';
  _railEl.setAttribute('aria-label', '对话中的提问');
  _railEl.hidden = true;
  // 2026-08-10 修复 v4: rail 挂 body · position:fixed 视口定位 ·
  // 不再挂 .chat-pane (overflow:hidden 窗口变小时裁掉 rail)
  document.body.appendChild(_railEl);
  _railTip = document.createElement('div');
  _railTip.className = 'rail-tooltip';
  _railTip.hidden = true;
  document.body.appendChild(_railTip);
  // 悬停安全区: 鼠标进入预览卡取消隐藏 · 移出立即隐藏（防刻度→预览卡闪烁）
  _railTip.addEventListener('mouseenter', function() {
    if (_railHideTimer) { clearTimeout(_railHideTimer); _railHideTimer = null; }
  });
  _railTip.addEventListener('mouseleave', function() { _hideRailPreview(); });
  panel.addEventListener('scroll', _updateRailActive, { passive: true });
  window.addEventListener('resize', _repositionRail);
  // 磁性拉伸: document 级 pointermove · 命中带判断 (rail 左缘向左扩展 48px) ·
  // 鼠标靠近轨道就触发 · 不用精准够到 20px 细条 (BRO: 中间镂空点不到)
  // RAF 消费（免每帧写 DOM）· 命中带外回弹 + 隐藏预览
  document.addEventListener('pointermove', function(e) {
    const hr = _railHitRect;
    if (!hr) return;
    const inZone = e.clientX >= hr.left && e.clientX <= hr.right &&
                   e.clientY >= hr.top && e.clientY <= hr.bottom;
    if (inZone) {
      _railPointerY = e.clientY;
      if (!_railRAF) _railRAF = requestAnimationFrame(_applyRailMagnet);
    } else if (_railPointerY != null) {
      _railPointerY = null;
      if (_railRAF) { cancelAnimationFrame(_railRAF); _railRAF = null; }
      _railMarks.forEach(function(item) { item.el.style.transform = 'scaleX(1)'; }); // 回弹
      if (_railPreviewIdx !== -1) { _railPreviewIdx = -1; _scheduleHidePreview(); }
    }
  });
  if (window.MutationObserver) {
    // 2026-08-11 F2 (墨言审查): 监听 #messages 全子树 class 变化 → 每条消息渲染/折叠
    // 都触发全量重建。加 debounce (150ms) —— 高频变更只取最后一次状态重建 · 性能友好。
    let _railObsTimer = null;
    const obs = new MutationObserver(function() {
      if (_railObsTimer) return; // 已有排队 · 等 debounce 落地
      _railObsTimer = setTimeout(function() {
        _railObsTimer = null;
        _refreshMsgRail();
      }, 150);
    });
    // 2026-08-10 修复 v2: 展开折叠消息/加载全部 = 切 hidden 属性 + 换子节点 ·
    // 只监听 childList 抓不到属性变化 → 加 attributes:true + attributeFilter:['hidden']
    // (session 容器 hidden 切换 / 消息自身折叠都会触发 · 不再漏)
    obs.observe(panel, { childList: true, subtree: true, attributes: true, attributeFilter: ['hidden', 'class'] });
    _railEl._obs = obs;
  }
  _refreshMsgRail();
  // 2026-08-10 修复 v3: 兜底自愈 · 每 1.5s 检查一次 ·
  // 任何事件漏监/瞬间状态导致 rail 误隐藏 → 有用户消息就强制恢复 (治"展开折叠后消失")
  // 2026-08-10 修复 v5: 自愈检查条件从 `.session-msgs .msg.bro` (限容器内) 放宽为
  // `#messages` 全量 `.msg.bro` · 展开折叠/加载全部重建后容器 class 若变化 ·
  // 旧条件查不到 → 永不恢复 · 只能等对话触发 observer (BRO: "要再对话一次才出现")
  if (!_railSelfHealTimer) {
    _railSelfHealTimer = setInterval(function() {
      if (!_railEl) return;
      if (_railEl.hidden) {
        const panel = document.getElementById('messages');
        if (panel && panel.querySelector('.msg.bro')) {
          _refreshMsgRail();  // 有用户消息但 rail 隐藏 → 重建恢复
        }
      }
    }, 1500);
  }
  return _railEl;
}

// 当前可见会话的消息容器（多会话场景只渲染当前会话的刻度）
function _visibleMsgContainer() {
  const panel = document.getElementById('messages');
  if (!panel) return null;
  return panel.querySelector(':scope > .session-msgs:not([hidden])') || panel;
}

function _refreshMsgRail() {
  if (!_railEl) return;
  const container = _visibleMsgContainer();
  // 2026-08-10 修复 v3: 容器切换瞬间 (:not([hidden]) 选不到) 不隐藏 rail ·
  // 用 panel 全量兜底找 .msg.bro · 只要有用户消息就显示 · 不因瞬间状态误隐藏
  const src = container || document.getElementById('messages');
  if (!src) { _railEl.hidden = true; _railHitRect = null; return; }
  const userMsgs = src.querySelectorAll('.msg.bro'); // 用户消息 = msg bro (角色类)
  // 2026-08-10 修复 v9 (BRO 拍板): rail 只显示最近 N 条 · 不随折叠/展开爆炸 ·
  // 展开折叠加载全部后 DOM 224+ 条 → 刻度挤爆看不见 (BRO: "200多轮根本显示不全")
  // 上限: 最近 28 条 · 不折叠/展开折叠都完整显示 · 无需内部滚动 · 1080P/2K 都装得下
  const RAIL_MAX_MARKS = 28;
  const startIdx = Math.max(0, userMsgs.length - RAIL_MAX_MARKS);
  const railMsgs = [];
  for (let _ri = startIdx; _ri < userMsgs.length; _ri++) railMsgs.push(userMsgs[_ri]);
  const total = railMsgs.length;
  // 间距固定 6px（CSS 控制）· 不动态压缩
  _railEl.innerHTML = '';
  _railMarks = [];
  // 2026-08-10 修复 v9 (BRO 拍板): 顺序恢复老的在上·新的在下 (跟聊天记录一致) ·
  // v6 曾因 224 刻度爆炸倒序(最新在上) · 现在有数量上限不再需要 · 恢复直觉顺序
  for (let i = 0; i < total; i++) {
    const msgEl = railMsgs[i];
    const mark = document.createElement('button');
    mark.className = 'rail-mark';
    mark.type = 'button';
    mark.setAttribute('aria-label', '跳转到用户消息');
    mark.title = '跳转到该消息';
    // 宽度统一 · 最新(底部)最深 · 越老越浅 · 保底 0.55 可见 (v8 顾问方案 B: 0.4→0.55)
    const idxFromBottom = total - 1 - i; // 0 = 最新 (在底部)
    const baseW = 18;                  // v8 顾问方案 C: 11→18px · 加宽更好感知
    mark.style.width = baseW + 'px';
    mark.style.opacity = Math.max(0.55, 0.95 - idxFromBottom * 0.05).toFixed(2);
    mark.addEventListener('click', function() { _jumpToMsg(msgEl); });
    // 2026-08-15 v5 移植: 预览统一交给磁性驱动 (_applyRailMagnet) ·
    // mark 上不再绑 mouseenter/mouseleave (避免双机制状态不同步) ·
    // 鼠标靠近轨道即触发 · 不用精准 hover 刻度细条
    // 键盘可达: Tab 聚焦同样显示预览 (保留)
    mark.addEventListener('focus', function() { _showRailPreview(mark, msgEl); });
    mark.addEventListener('blur', function() { _scheduleHidePreview(); });
    _railEl.appendChild(mark);
    _railMarks.push({ el: mark, msgEl: msgEl, baseW: baseW });
  }
  _railEl.hidden = _railMarks.length === 0;
  _railEl.scrollTop = 0; // v9: 28 条以内无需内部滚动 · 归零防残留滚动位置
  _repositionRail();
  _updateRailActive();
}

// 缓存每个刻度相对 rail 顶的中心 y（flex-start + gap 线性排列 · 免每帧读布局）
function _updateRailCenters() {
  _railCenters = [];
  if (!_railEl || !_railMarks.length) return;
  const gap = 6; // v8 顾问方案 C: 8→6 与 .msg-rail gap 同步
  const markH = 4; // v8 顾问方案 C: 3→4 与 .rail-mark height 同步
  for (let i = 0; i < _railMarks.length; i++) {
    _railCenters.push(8 + i * (markH + gap) + markH / 2);
  }
}

function _jumpToMsg(msgEl) {
  if (!msgEl) return;
  try { msgEl.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
  catch (e) { msgEl.scrollIntoView(); }
  msgEl.classList.remove('rail-jump-flash');
  void msgEl.offsetWidth; // 重置动画
  msgEl.classList.add('rail-jump-flash');
  setTimeout(function() { msgEl.classList.remove('rail-jump-flash'); }, 1300);
}

// 找用户消息后最近的最终回答 (排除 thinking/sys/工具卡) · v5 移植 (龙头)
function _findRailAnswer(msgEl) {
  // 限定当前消息所在 session 内找 · 不依赖全局容器 (切会话瞬间可能扫到别的 session)
  const container = (msgEl && msgEl.closest('.session-msgs')) || _visibleMsgContainer();
  if (!container) return null;
  const all = container.querySelectorAll('.msg');
  let found = false;
  for (let i = 0; i < all.length; i++) {
    const el = all[i];
    if (el === msgEl) { found = true; continue; }
    if (!found) continue;
    if (el.classList.contains('opus') && !el.classList.contains('thinking')) {
      return el;
    }
  }
  return null;
}

function _showRailPreview(mark, msgEl) {
  if (!_railTip) return;
  if (_railHideTimer) { clearTimeout(_railHideTimer); _railHideTimer = null; }
  // 2026-08-15 v5 移植: 两段式预览 —— 问题 (≤3 行) + 回答片段 (≤4 行) ·
  // 渲染用 textContent 防注入 · 不再用 innerText 拼字符串
  _railTip.innerHTML = '';
  const q = (msgEl.textContent || '').replace(/\s+/g, ' ').trim();
  const ansEl = _findRailAnswer(msgEl);
  const a = ansEl ? (ansEl.textContent || '').replace(/\s+/g, ' ').trim() : '';
  const qDiv = document.createElement('div');
  qDiv.className = 'rail-tip-q';
  qDiv.textContent = (q.length > _RAIL_PREVIEW_LEN ? q.slice(0, _RAIL_PREVIEW_LEN) + '…' : q) || '（空消息）';
  _railTip.appendChild(qDiv);
  if (a) {
    const aDiv = document.createElement('div');
    aDiv.className = 'rail-tip-a';
    aDiv.textContent = a.length > _RAIL_ANSWER_LEN ? a.slice(0, _RAIL_ANSWER_LEN) + '…' : a;
    _railTip.appendChild(aDiv);
  }
  // 2026-08-10 修复 v2: 不用 translateX(-100%) (刻度靠右时会把卡推出屏幕) ·
  // 直接 right 定位: 卡右边缘 = 刻度左边缘 - 10px · 稳稳在视口内
  const r = mark.getBoundingClientRect();
  _railTip.style.right = Math.max(8, window.innerWidth - r.left + 10) + 'px';
  _railTip.style.top = r.top + 'px';
  _railTip.style.transform = 'none';
  _railTip.style.left = 'auto';
  _railTip.hidden = false;
}

function _scheduleHidePreview() {
  if (_railHideTimer) clearTimeout(_railHideTimer);
  _railHideTimer = setTimeout(function() {
    _railHideTimer = null;
    if (_railTip) _railTip.hidden = true;
  }, 120); // safe zone: 延迟关闭, 允许鼠标横向进入预览卡
}

function _hideRailPreview() {
  if (_railHideTimer) { clearTimeout(_railHideTimer); _railHideTimer = null; }
  if (_railTip) _railTip.hidden = true;
}

function _repositionRail() {
  if (!_railEl) return;
  const panel = document.getElementById('messages');
  if (!panel) return;
  // 2026-08-10 修复 v4: rail 改用 position:fixed (挂 body · 视口定位) ·
  // 原 absolute 挂 .chat-pane 下 → .chat-pane overflow:hidden 在窗口变小时把 rail 裁掉 (BRO: 吃分辨率)
  // fixed 定位直接用视口坐标 · 不随父容器裁切 · 窗口怎么变都在聊天区右侧
  const prect = panel.getBoundingClientRect();
  _railEl.style.top = (prect.top + _RAIL_TOP_OFFSET) + 'px';
  _railTopCache = prect.top + _RAIL_TOP_OFFSET; // v5: 缓存 rail 视口 top · 磁性拉伸免每帧读布局
  // 磁性命中带: rail 真实矩形 + 左缘向左扩展 (BRO: 靠近轨道就触发 · 不用够到细条)
  const rr = _railEl.getBoundingClientRect();
  _railHitRect = {
    left: rr.left - _RAIL_HIT_ZONE,
    right: rr.right + 4,
    top: rr.top - 8,
    bottom: rr.bottom + 8
  };
  // 2026-08-10 修复 v8 (顾问 KIMI K3 方案 A): 刻度从滚动条带上挪开 ·
  // 原 right = innerWidth - prect.right + 5 → rail 右缘 1583 紧贴滚动条左缘 1584 (8px 宽) ·
  // 人眼把 rail 归并成"滚动条的一部分" = 视觉消失 · +16 让刻度右缘落到 ~1576 ·
  // 正好在 #messages padding 右侧空白带里 · 独立成一条
  _railEl.style.right = Math.max(8, window.innerWidth - prect.right + 16) + 'px';
  // rail 高度: 内容自适应 · 封顶消息区剩余（不铺满 → 刻度紧凑排列）
  _railEl.style.height = 'auto';
  _railEl.style.maxHeight = Math.max(40, panel.clientHeight - _RAIL_TOP_OFFSET - _RAIL_BOTTOM_PAD) + 'px';
  _updateRailCenters();
}

function _applyRailMagnet() {
  _railRAF = null;
  if (_railPointerY == null || !_railMarks.length || !_railEl) return;
  // v5: 用 _railTopCache · 首次回退读一次 (reposition 时刷新 · 免每帧 getBoundingClientRect)
  const railTop = _railTopCache != null ? _railTopCache : _railEl.getBoundingClientRect().top;
  let hotIdx = -1;
  let hotInfluence = 0;
  _railMarks.forEach(function(item, i) {
    const centerY = _railCenters[i] != null ? railTop + _railCenters[i] : null;
    if (centerY == null) return;
    const dist = Math.abs(_railPointerY - centerY);
    const t = Math.max(0, 1 - dist / _RAIL_MAGNET_RADIUS);
    const influence = t * t * (3 - 2 * t); // smoothstep
    if (influence > hotInfluence) { hotInfluence = influence; hotIdx = i; }
    if (influence <= 0.01) {
      item.el.style.transform = 'scaleX(1)';
    } else {
      const w = item.baseW + (_RAIL_MAX_STRETCH - item.baseW) * influence;
      item.el.style.transform = 'scaleX(' + (w / item.baseW) + ')';
    }
  });
  // v5 移植: 磁性驱动预览 —— 离光标最近的刻度直接显示预览 (不用精准 hover 6px 细条 ·
  // 命中区=整个 rail 轨道) · 切换刻度才重建 DOM · 离开轨道阈值外延迟隐藏
  const HOT_MIN = _RAIL_HOT_MIN;
  if (hotIdx >= 0 && hotInfluence > HOT_MIN) {
    if (_railPreviewIdx !== hotIdx) {
      _railPreviewIdx = hotIdx;
      const hot = _railMarks[hotIdx];
      _showRailPreview(hot.el, hot.msgEl);
    }
  } else if (_railPreviewIdx !== -1) {
    _railPreviewIdx = -1;
    _scheduleHidePreview();
  }
}

function _updateRailActive() {
  const panel = document.getElementById('messages');
  if (!panel || !_railMarks.length) return;
  const viewTop = panel.getBoundingClientRect().top;
  const midY = viewTop + panel.clientHeight / 2;
  let activeIdx = -1;
  for (let i = 0; i < _railMarks.length; i++) {
    const r = _railMarks[i].msgEl.getBoundingClientRect();
    if (r.top <= midY && r.bottom >= viewTop) activeIdx = i;
  }
  _railMarks.forEach(function(item, i) {
    item.el.classList.toggle('active', i === activeIdx);
  });
}

// 初始化: DOM 就绪后建 rail · 之后靠 MutationObserver 自动刷新
if (document.body) _ensureMsgRail();
else document.addEventListener('DOMContentLoaded', function() { _ensureMsgRail(); }, { once: true });
