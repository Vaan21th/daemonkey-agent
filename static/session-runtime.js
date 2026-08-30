/* session-runtime.js · 真并行多会话内核
   从 static/chat.js wish-3fef4bc7 抽出。工作台 / 陪伴同一份。

   合同: 每个 sid 自己的 fetch / abort / pending / DOM 容器。
   切会话只切 visibility · 不杀 stream · 停只停当前看见的那本。
   2026-08-29 · 每本自己的发送队列 · 这轮跑着也能再丢一句。 */
'use strict';

(function (global) {
  const sessions = {};
  let cidCounter = 0;
  let panel = null;
  let activeSid = '';
  const CONTAINER_CLASS = 'session-msgs';
  const QUEUE_MAX = 8;
  let queuePainter = null;
  let drainHandler = null;
  let queueEditor = null;

  function escSid(sid) {
    if (global.CSS && CSS.escape) return CSS.escape(sid);
    return String(sid).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  }

  function newState(sid) {
    return {
      sessionId: sid,
      pending: false,
      currentTurnId: null,
      currentAbortController: null,
      streamGen: 0,
      currentStreamingReasoning: null,
      currentStreamingAssistant: null,
      assistantBubbles: [],
      sawAssistantText: false,
      finalUsage: null,
      finalSessionId: null,
      finalModel: null,
      errorShown: false,
      lastFinishReason: null,
      autoResumeCount: 0,
      streamHadToolCall: false,
      toolCallCount: 0,
      lastDashboardRefreshAt: 0,
      toolStartedAt: 0,
      $container: null,
      hasUnreadCompletion: false,
      inputDraft: '',
      title: null,
      progressText: '',
      outboundQueue: [],
      chatMode: '',
      holdQueue: false,
      queueEdit: null,
    };
  }

  function get(sid) {
    return sid ? (sessions[sid] || null) : null;
  }

  function getOrCreate(sid) {
    if (!sid) return null;
    if (!sessions[sid]) sessions[sid] = newState(sid);
    return sessions[sid];
  }

  function allocCid() {
    cidCounter += 1;
    return 'tmp-' + Date.now().toString(36) + '-' + cidCounter.toString(36);
  }

  function swapId(oldSid, newSid) {
    if (!oldSid || !newSid || oldSid === newSid) return false;
    if (!sessions[oldSid]) return false;
    const s = sessions[oldSid];
    s.sessionId = newSid;
    sessions[newSid] = s;
    delete sessions[oldSid];
    if (s.$container) s.$container.dataset.sid = newSid;
    if (activeSid === oldSid) activeSid = newSid;
    return true;
  }

  function attachPanel(el) {
    panel = el || null;
  }

  function getOrCreateContainer(sid) {
    if (!sid || !panel) return null;
    let c = panel.querySelector('.' + CONTAINER_CLASS + '[data-sid="' + escSid(sid) + '"]');
    if (!c) {
      c = document.createElement('div');
      c.className = CONTAINER_CLASS;
      c.dataset.sid = sid;
      c.hidden = true;
      panel.appendChild(c);
      const s = getOrCreate(sid);
      if (s) s.$container = c;
    }
    return c;
  }

  function setActiveContainer(sid) {
    if (panel) {
      Array.from(panel.children).forEach(function (child) {
        if (child.classList && child.classList.contains(CONTAINER_CLASS)) child.hidden = true;
      });
    }
    activeSid = sid || '';
    if (!sid) return null;
    const c = getOrCreateContainer(sid);
    if (c) c.hidden = false;
    return c;
  }

  function activeContainer() {
    if (!activeSid) return null;
    const s = sessions[activeSid];
    return (s && s.$container) || null;
  }

  function isVisible(sid) {
    return !!sid && sid === activeSid;
  }

  function isPending(sid) {
    const s = sessions[sid];
    return !!(s && s.pending);
  }

  function isBusy(sid) {
    const s = sessions[sid];
    return !!(s && (s.pending || s.currentAbortController || s.currentTurnId));
  }

  function abortSession(sid) {
    const s = sessions[sid];
    if (!s) return;
    s.streamGen = (s.streamGen || 0) + 1;
    try { if (s.currentAbortController) s.currentAbortController.abort(); } catch (e) {}
    s.currentAbortController = null;
    if (s.currentTurnId) {
      var tok = '';
      try {
        tok = (typeof global.token === 'string' && global.token)
          || localStorage.getItem('opus_ui_token')
          || localStorage.getItem('Daemonkey_ui_token')
          || '';
      } catch (e) {}
      var headers = tok ? { 'Authorization': 'Bearer ' + tok } : {};
      fetch('/turns/' + encodeURIComponent(s.currentTurnId) + '/abort', {
        method: 'POST',
        headers: headers,
      }).catch(function () {});
    }
    s.currentTurnId = null;
    s.pending = false;
    s.holdQueue = true;
  }

  function holdOutbound(sid) {
    const s = sid ? getOrCreate(sid) : null;
    if (s) s.holdQueue = true;
  }

  function releaseOutbound(sid) {
    const s = get(sid);
    if (s) s.holdQueue = false;
  }

  function queueOf(sid) {
    const s = get(sid);
    return (s && s.outboundQueue) ? s.outboundQueue.slice() : [];
  }

  function _emitQueue(sid) {
    if (typeof queuePainter === 'function') {
      try { queuePainter(sid, queueOf(sid)); } catch (e) {}
    }
  }

  function enqueue(sid, item) {
    if (!sid) return { ok: false, error: 'no-sid' };
    const s = getOrCreate(sid);
    if (!s.outboundQueue) s.outboundQueue = [];
    if (s.outboundQueue.length >= QUEUE_MAX) return { ok: false, error: 'full' };
    const rec = {
      id: 'q-' + Date.now().toString(36) + '-' + (++cidCounter).toString(36),
      text: (item && item.text) ? String(item.text) : '',
      attachments: (item && item.attachments) ? item.attachments.slice() : [],
    };
    if (!rec.text && !rec.attachments.length) return { ok: false, error: 'empty' };
    s.outboundQueue.push(rec);
    _noteInserted(s, s.outboundQueue.length - 1);
    _emitQueue(sid);
    return { ok: true, item: rec };
  }

  function _noteRemoved(s, at) {
    if (!s || !s.queueEdit) return;
    if (at < s.queueEdit.index) s.queueEdit.index -= 1;
  }

  function _noteInserted(s, at) {
    if (!s || !s.queueEdit) return;
    if (at <= s.queueEdit.index) s.queueEdit.index += 1;
  }

  function editOf(sid) {
    const s = get(sid);
    return (s && s.queueEdit) ? { id: s.queueEdit.id, index: s.queueEdit.index } : null;
  }

  function takeQueued(sid, id) {
    const s = get(sid);
    if (!s || !s.outboundQueue) return null;
    const i = s.outboundQueue.findIndex(function (x) { return x.id === id; });
    if (i < 0) return null;
    const rec = s.outboundQueue.splice(i, 1)[0];
    s.queueEdit = { id: rec.id, index: i };
    _emitQueue(sid);
    return { item: rec, index: i };
  }

  function insertQueued(sid, index, item) {
    if (!sid) return { ok: false, error: 'no-sid' };
    const s = getOrCreate(sid);
    if (!s.outboundQueue) s.outboundQueue = [];
    if (s.outboundQueue.length >= QUEUE_MAX) return { ok: false, error: 'full' };
    const rec = {
      id: (item && item.id) || ('q-' + Date.now().toString(36) + '-' + (++cidCounter).toString(36)),
      text: (item && item.text) ? String(item.text) : '',
      attachments: (item && item.attachments) ? item.attachments.slice() : [],
    };
    if (!rec.text && !rec.attachments.length) return { ok: false, error: 'empty' };
    const dest = Math.max(0, Math.min(s.outboundQueue.length, Number(index) || 0));
    s.outboundQueue.splice(dest, 0, rec);
    s.queueEdit = null;
    _emitQueue(sid);
    return { ok: true, item: rec };
  }

  function putBack(sid, item) {
    const s = get(sid);
    const edit = s && s.queueEdit;
    if (!edit) return enqueue(sid, item);
    const rec = {
      id: (item && item.id) || edit.id,
      text: item && item.text,
      attachments: item && item.attachments,
    };
    return insertQueued(sid, edit.index, rec);
  }

  function cancelQueued(sid, id) {
    const s = get(sid);
    if (!s || !s.outboundQueue) return false;
    const i = s.outboundQueue.findIndex(function (x) { return x.id === id; });
    if (i < 0) return false;
    s.outboundQueue.splice(i, 1);
    _noteRemoved(s, i);
    _emitQueue(sid);
    return true;
  }

  function moveQueued(sid, id, toIndex) {
    const s = get(sid);
    if (!s || !s.outboundQueue) return false;
    const from = s.outboundQueue.findIndex(function (x) { return x.id === id; });
    if (from < 0) return false;
    const next = s.outboundQueue.slice();
    const rec = next.splice(from, 1)[0];
    const dest = Math.max(0, Math.min(next.length, Number(toIndex) || 0));
    next.splice(dest, 0, rec);
    if (next.every(function (x, i) { return x.id === s.outboundQueue[i].id; })) return false;
    s.outboundQueue = next;
    _noteRemoved(s, from);
    _noteInserted(s, dest);
    _emitQueue(sid);
    return true;
  }

  function _insertAtFromPoint(host, y, dragId) {
    const others = Array.prototype.filter.call(host.querySelectorAll('.oq-item'), function (el) {
      return el.dataset.qid !== dragId;
    });
    let insertAt = others.length;
    for (let i = 0; i < others.length; i++) {
      const r = others[i].getBoundingClientRect();
      if (y < r.top + r.height / 2) {
        insertAt = i;
        break;
      }
    }
    host.querySelectorAll('.oq-item').forEach(function (el) {
      el.classList.remove('is-drop-above', 'is-drop-below');
    });
    if (insertAt < others.length) others[insertAt].classList.add('is-drop-above');
    else if (others.length) others[others.length - 1].classList.add('is-drop-below');
    return insertAt;
  }

  function bindQueueSort(host) {
    let dragId = null;
    let originY = 0;
    let armed = false;
    let lastAt = null;

    function clearMarks() {
      host.querySelectorAll('.oq-item').forEach(function (el) {
        el.classList.remove('is-dragging', 'is-drop-above', 'is-drop-below');
      });
    }

    function endDrag() {
      if (!dragId) return;
      const id = dragId;
      const dest = lastAt;
      const moved = armed;
      dragId = null;
      armed = false;
      lastAt = null;
      clearMarks();
      if (!moved || dest == null) return;
      moveQueued(host.dataset.queueSid, id, dest);
    }

    host.addEventListener('pointerdown', function (e) {
      if (e.button !== 0) return;
      if (e.target.closest && e.target.closest('.oq-x')) return;
      if (!e.target.closest || !e.target.closest('.oq-grip')) return;
      const item = e.target.closest('.oq-item');
      if (!item || !host.contains(item)) return;
      dragId = item.dataset.qid;
      originY = e.clientY;
      armed = false;
      lastAt = null;
      try { host.setPointerCapture(e.pointerId); } catch (err) {}
    });
    host.addEventListener('pointermove', function (e) {
      if (!dragId) return;
      if (!armed && Math.abs(e.clientY - originY) < 4) return;
      if (!armed) {
        armed = true;
        const cur = host.querySelector('.oq-item[data-qid="' + dragId + '"]');
        if (cur) cur.classList.add('is-dragging');
      }
      lastAt = _insertAtFromPoint(host, e.clientY, dragId);
      e.preventDefault();
    });
    host.addEventListener('pointerup', endDrag);
    host.addEventListener('pointercancel', function () {
      dragId = null;
      armed = false;
      lastAt = null;
      clearMarks();
    });
  }

  function kick(sid) {
    const s = get(sid);
    if (!s || s.pending) return false;
    if (s.holdQueue) return false;
    if (!s.outboundQueue || !s.outboundQueue.length) return false;
    s.pending = true;
    const rec = s.outboundQueue.shift();
    _noteRemoved(s, 0);
    _emitQueue(sid);
    queueMicrotask(function () {
      if (typeof drainHandler === 'function') drainHandler(sid, rec);
      else s.pending = false;
    });
    return true;
  }

  function bindQueue(opts) {
    opts = opts || {};
    if (opts.paint) queuePainter = opts.paint;
    if (opts.drain) drainHandler = opts.drain;
    if (opts.edit) queueEditor = opts.edit;
  }

  function _isQueueImage(a) {
    if (!a) return false;
    if (a.type === 'image') return true;
    const mime = String(a.mime || '').toLowerCase();
    if (mime.indexOf('image/') === 0) return true;
    return /^data:image\//i.test(String(a.data_url || a.url || ''));
  }

  function _safeThumbUrl(a) {
    if (!a) return '';
    const url = String(a.data_url || a.url || '');
    if (/^data:image\//i.test(url)) return url;
    if (/^https?:\/\//i.test(url)) return url;
    if (url.charAt(0) === '/' && url.charAt(1) !== '/') return url;
    return '';
  }

  function paintQueueBar(host, sid) {
    if (!host) return;
    host.dataset.queueSid = sid || '';
    if (!host.dataset.oqSort) {
      host.dataset.oqSort = '1';
      bindQueueSort(host);
    }
    const items = queueOf(sid);
    host.hidden = items.length === 0;
    if (!items.length) {
      host.innerHTML = '';
      return;
    }
    host.innerHTML = items.map(function (it, i) {
      return '<div class="oq-item" data-qid="' + it.id + '" title="点这条改，再发送回原位">'
        + '<span class="oq-thumb" hidden></span>'
        + '<span class="oq-grip" title="拖动改顺序" aria-hidden="true"><i class="ri-draggable"></i></span>'
        + '<span class="oq-n">' + (i + 1) + '</span>'
        + '<span class="oq-t"></span>'
        + '<span class="oq-pen" aria-hidden="true"><i class="ri-pencil-line"></i></span>'
        + '<button type="button" class="oq-x" data-qid="' + it.id + '" title="取消这条">'
        + '<i class="ri-close-line"></i></button></div>';
    }).join('');
    const rows = host.querySelectorAll('.oq-item');
    items.forEach(function (it, i) {
      const row = rows[i];
      if (!row) return;
      const atts = it.attachments || [];
      const imgs = atts.filter(_isQueueImage);
      const src = imgs.length ? _safeThumbUrl(imgs[0]) : '';
      const thumb = row.querySelector('.oq-thumb');
      if (thumb && src) {
        const img = document.createElement('img');
        img.alt = '';
        img.src = src;
        thumb.appendChild(img);
        if (imgs.length > 1) {
          const more = document.createElement('span');
          more.className = 'oq-thumb-n';
          more.textContent = '+' + (imgs.length - 1);
          thumb.appendChild(more);
        }
        thumb.hidden = false;
      }
      const label = (it.text || '').trim()
        || (atts.length ? ('附件 ×' + atts.length) : '（空）');
      const t = row.querySelector('.oq-t');
      if (t) t.textContent = label.length > 36 ? label.slice(0, 36) + '…' : label;
    });
    host.querySelectorAll('.oq-x').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        cancelQueued(sid, btn.dataset.qid);
      });
    });
    host.querySelectorAll('.oq-item').forEach(function (row) {
      row.addEventListener('click', function (e) {
        if (e.target.closest && (e.target.closest('.oq-x') || e.target.closest('.oq-grip'))) return;
        const qid = row.dataset.qid;
        if (qid && typeof queueEditor === 'function') queueEditor(sid, qid);
      });
    });
  }

  global.SessionRuntime = {
    sessions: sessions,
    newState: newState,
    get: get,
    getOrCreate: getOrCreate,
    allocCid: allocCid,
    swapId: swapId,
    attachPanel: attachPanel,
    getOrCreateContainer: getOrCreateContainer,
    setActiveContainer: setActiveContainer,
    activeContainer: activeContainer,
    activeSid: function () { return activeSid; },
    isVisible: isVisible,
    isPending: isPending,
    isBusy: isBusy,
    abortSession: abortSession,
    holdOutbound: holdOutbound,
    releaseOutbound: releaseOutbound,
    QUEUE_MAX: QUEUE_MAX,
    enqueue: enqueue,
    cancelQueued: cancelQueued,
    moveQueued: moveQueued,
    takeQueued: takeQueued,
    insertQueued: insertQueued,
    putBack: putBack,
    editOf: editOf,
    queueOf: queueOf,
    kick: kick,
    bindQueue: bindQueue,
    paintQueueBar: paintQueueBar,
  };
})(window);
