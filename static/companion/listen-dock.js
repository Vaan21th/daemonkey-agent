/* 陪伴房间 · 纸白听环
   收着: 圆 + 笔
   在听: 笔换成猴头 · 音量把头放大, 背后一团墨晕
   点笔: 先收到输入框高度, 再左右拉开 (两头半圆 · 中间直条)
   点麦: 原路收回 · 展开后点别处不收, 免得误触把框弄没
   没麦: 直接开条
   收着长按: 三种语音模式 */
'use strict';

function _dockEls() {
  return {
    stage: document.getElementById('listen-dock'),
    strip: document.getElementById('listen-strip'),
    hub: document.getElementById('hubBtn'),
  };
}

function _isOpen() {
  const { stage } = _dockEls();
  return !!(stage && stage.classList.contains('open'));
}

function _setTalking(on) {
  document.body.classList.toggle('talking', !!on);
  if (on) document.body.classList.remove('focus-room');
}

function openStrip() {
  const { stage } = _dockEls();
  if (!stage || stage.dataset.busy === '1' || stage.classList.contains('open')) return;
  stage.dataset.busy = '1';
  stage.classList.add('shrink');
  setTimeout(() => {
    stage.classList.add('open');
    _setTalking(true);
    const ta = document.getElementById('chat-input');
    if (ta) setTimeout(() => ta.focus(), 180);
    setTimeout(() => { stage.dataset.busy = '0'; }, 480);
    if (typeof stage._onOpen === 'function') stage._onOpen();
  }, 220);
}

function closeStrip() {
  const { stage } = _dockEls();
  if (!stage || stage.dataset.busy === '1' || !stage.classList.contains('open')) return;
  if (stage.dataset.forceOpen === '1') return;
  stage.dataset.busy = '1';
  const menu = document.getElementById('micMenu');
  if (menu) menu.hidden = true;
  stage.classList.remove('open');
  _setTalking(false);
  setTimeout(() => {
    stage.classList.remove('shrink');
    setTimeout(() => { stage.dataset.busy = '0'; }, 220);
    if (typeof stage._onClose === 'function') stage._onClose();
  }, 360);
}

function setWave(level, bins) {
  const { stage } = _dockEls();
  if (!stage || stage.classList.contains('open')) return;
  let lv = Math.max(0, Math.min(1, Number(level) || 0));
  if (bins && bins.length) {
    let peak = 0;
    for (let i = 0; i < bins.length; i += 3) {
      peak = Math.max(peak, Math.abs((bins[i] - 128) / 128));
    }
    lv = Math.max(lv, Math.min(1, peak));
  }
  if (!stage.classList.contains('listening')) lv = 0;
  stage.style.setProperty('--mouth-s', (1 + lv * 0.7).toFixed(3));
  stage.style.setProperty('--halo-s', (0.82 + lv * 0.52).toFixed(3));
  stage.style.setProperty('--halo-o', (0.28 + lv * 0.5).toFixed(3));
}

async function detectMic() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return false;
  try {
    const list = await navigator.mediaDevices.enumerateDevices();
    return list.some(d => d.kind === 'audioinput');
  } catch (e) { return false; }
}

function initListenDock(opts) {
  opts = opts || {};
  const { stage, hub } = _dockEls();
  if (!stage || !hub) return;
  stage._onOpen = opts.onOpen || null;
  stage._onClose = opts.onClose || null;
  if (opts.forceOpen) stage.dataset.forceOpen = '1';

  let longDone = false, pressTimer = null;
  function _toggleMicMenu() {
    const menu = document.getElementById('micMenu');
    if (menu) menu.hidden = !menu.hidden;
  }
  hub.addEventListener('pointerdown', e => {
    if (e.button && e.button !== 0) return;
    longDone = false;
    try { hub.setPointerCapture(e.pointerId); } catch (err) {}
    pressTimer = setTimeout(() => {
      longDone = true;
      _toggleMicMenu();
    }, 480);
  });
  const cancelPress = () => { if (pressTimer) { clearTimeout(pressTimer); pressTimer = null; } };
  hub.addEventListener('pointerup', cancelPress);
  hub.addEventListener('pointercancel', cancelPress);
  hub.addEventListener('click', e => {
    e.stopPropagation();
    if (longDone) { longDone = false; return; }
    const menu = document.getElementById('micMenu');
    if (menu && !menu.hidden) { menu.hidden = true; return; }
    if (_isOpen()) closeStrip();
    else openStrip();
  });

  const room = document.getElementById('room');
  if (room) {
    room.addEventListener('click', e => {
      if (e.target.closest('#listen-strip, #voicePanel, #attach-bar, #voice-live, #say-bubble, #say-log, #room-confirm, #micMenu')) return;
      if (typeof dismissRoomConfirm === 'function' && document.querySelector('#room-confirm .confirm-card-done')) {
        dismissRoomConfirm();
      }
    });
  }

  document.getElementById('micMode') && document.getElementById('micMode').addEventListener('click', e => e.stopPropagation());

  if (opts.forceOpen) {
    openStrip();
    _setTalking(true);
  } else setWave(0, null);

  (function idlePulse() {
    if (!stage.classList.contains('open') && !stage.classList.contains('listening')) setWave(0, null);
    requestAnimationFrame(idlePulse);
  })();

  window.ListenDock = {
    open: openStrip,
    close: closeStrip,
    isOpen: _isOpen,
    setWave: setWave,
    setListening: function (on) {
      stage.classList.toggle('listening', !!on);
      if (!on) setWave(0, null);
    },
  };
}

window.initListenDock = initListenDock;
window.detectMic = detectMic;
