/* static/voice-mic.js · 三模式语音 (工作台 + 陪伴共用)
   从 chat.js initVoice 抽出 · 两边同一套三角菜单。
   挂钩: input / send / isPending / token / pickClient / hideClient / hideTts
*/
// wish-41ed72ef · 语音输入 → 卷七十五续六 · 三模式语音 (BRO 2026-07-11 校准语义)
//   · 语音输入 (dictation): 说完填输入框·手动发 (最初功能·不变);
//   · 语音对话 (transcribe): 持续听麦克风·你说完停约 1 秒自动发给 AI·
//       AI 回完继续听 —— hands-free 语音对话·给未来桌面版对话模式留的扣·UI 比会议纪要轻;
//   · 会议纪要 (meeting) = 【录制文本】: 持续把麦克风转成文字累积·点【停止录制】后
//       把整段交给 AI 拆分整理 (议题/结论/待办/风险)。
// 边界: 浏览器 SpeechRecognition 只认默认麦克风·线上会议对方声音要转文字得等后端 ASR·
//   本轮不纠结系统音频 (getDisplayMedia 那套已移除)。
function initVoice(opts) {
  const $micBtn = document.getElementById('micBtn');
  if (!$micBtn) return;
  const $micMode = document.getElementById('micMode');
  const $micMenu = document.getElementById('micMenu');
  const $panel = document.getElementById('voicePanel');
  const $script = document.getElementById('voiceTranscript');
  const $timer = document.getElementById('voiceTimer');
  const $panelMode = document.getElementById('voicePanelMode');
  const $recNote = document.getElementById('voiceRecNote');
  const $close = document.getElementById('voiceClose');

  opts = opts || {};
  const $input = opts.input || document.getElementById('input') || document.getElementById('chat-input');
  if (!$input) return;
  const isPending = typeof opts.isPending === 'function' ? opts.isPending : function () { return false; };
  const getToken = typeof opts.token === 'function' ? opts.token : function () { return localStorage.getItem('opus_ui_token') || ''; };
  const doSend = typeof opts.send === 'function' ? opts.send : function () {};
  const doPick = typeof opts.pickClient === 'function' ? opts.pickClient : null;
  const maxH = opts.maxInputHeight || 160;
  const storageKey = opts.storageKey || 'opus_voice_mode';
  const bindMicClick = opts.bindMicClick !== false;
  function escHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  if (opts.hideClient && $panel) {
    const b = $panel.querySelector('[data-act="toclient"]');
    if (b) b.hidden = true;
  }

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const SILENCE_MS = 1000;      // 语音对话: 停顿约 1 秒自动发给 AI (BRO 定 · 给桌面版对话模式留扣)
  const MODES = {
    dictation:  { label: '语音输入', panel: false, icon: 'ri-mic-line' },
    transcribe: { label: '语音对话', panel: true,  icon: 'ri-chat-voice-line' },   // 持续听 · 停约 1 秒自动发
    meeting:    { label: '会议纪要', panel: true,  icon: 'ri-group-line' },         // = 持续录成文本 · 停止后整理
  };
  let mode = localStorage.getItem(storageKey) || opts.defaultMode || 'dictation';
  if (!MODES[mode]) mode = opts.defaultMode || 'dictation';
  if (!MODES[mode]) mode = 'dictation';
  if (!SR) { $micBtn.classList.add('unsupported'); $micBtn.title = '语音功能需 Chrome / Edge 浏览器'; }

  // ── 2026-08-08 · TTS 开关 (语音对话模式: AI 回复自动朗读) ──
  // 能力探测: /api/tts 端点存在才显示开关 (纯净版无 voice.py → 探测 404 → 开关隐藏 · 优雅降级)
  // 挂到 window 上让 finalizeStreamingAssistant 能触发 (它在 initVoice 闭包外)
  window.__voiceTtsEnabled = false;
  const $ttsToggle = document.getElementById('voiceTtsToggle');
  const $ttsWrap = document.getElementById('voiceTtsWrap');
  if ($ttsToggle && $ttsWrap && !opts.hideTts) {
    fetch('/api/tts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: '' }) })
      .then(r => {
        if (r.status === 404 || r.status === 405) return; // 端点不存在/未注册 → 保持隐藏
        $ttsWrap.hidden = false;
        window.__voiceTtsEnabled = localStorage.getItem('opus_voice_tts') === '1';
        $ttsToggle.checked = !!window.__voiceTtsEnabled;
        $ttsToggle.addEventListener('change', () => {
          window.__voiceTtsEnabled = $ttsToggle.checked;
          localStorage.setItem('opus_voice_tts', $ttsToggle.checked ? '1' : '0');
          if (typeof _setRecNote === 'function' && _listening && mode === 'transcribe') {
            _setRecNote($ttsToggle.checked
              ? '<i class="ri-volume-up-line"></i> TTS 已开 · OPUS 回复会朗读'
              : '<i class="ri-volume-mute-line"></i> TTS 已关', 'wait');
          }
        });
      })
      .catch(() => { /* 网络异常 → 保持隐藏 */ });
  }
  // 播放一条语音回复: 调 /api/tts 合成 → <audio> 播放 → 播完回调 (恢复收音)
  window.__speakReply = function (text, onDone) {
    if (!window.__voiceTtsEnabled || !(text || '').trim()) { if (onDone) onDone(); return; }
    const body = JSON.stringify({ text: (text || '').slice(0, 1500) });
    fetch('/api/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
    }).then(r => {
      if (!r.ok) throw new Error('TTS HTTP ' + r.status);
      return r.blob();
    }).then(blob => {
      const url = URL.createObjectURL(blob);
      const au = new Audio(url);
      au.onended = () => { URL.revokeObjectURL(url); if (onDone) onDone(); };
      au.onerror = () => { URL.revokeObjectURL(url); if (onDone) onDone(); };
      au.play().catch(() => { if (onDone) onDone(); });
    }).catch(e => {
      console.warn('TTS 播放失败:', e);
      if (onDone) onDone();
    });
  };

  let _rec = null;              // SpeechRecognition 实例
  let _listening = false;
  let _manualStop = false;      // true = 用户主动停 · 阻止 onend 自动重启
  let _finalText = '';          // 会议纪要累积的确认文字
  let _dictBase = '';           // 语音输入: 开录前输入框已有内容
  let _pendingBuf = '';         // 语音对话: 已确认待发的一段
  let _silenceTimer = null;     // 语音对话: 停顿检测 timer
  let _voicePaused = false;     // 语音对话: AI 回复中 → 暂停收音 (轮流说话·别录进杂音/AI 的话)
  let _replyWatcher = null;     // 语音对话: 盯 pending·AI 回完自动恢复收音
  let _sawPending = false;      // 语音对话: 确认这轮 turn 真起来了·防提前恢复
  let _pauseTicks = 0;          // 语音对话: 兜底·久等没起 turn 也恢复
  let _srGen = 0;               // SR 代号·暂停/停止/重启时 +1·让旧实例延迟触发的 onend 作废 (防并发双识别)
  let _timerId = null;
  let _startTs = 0;

  function _autosize() {
    $input.style.height = 'auto';
    $input.style.height = Math.min($input.scrollHeight, maxH) + 'px';
  }
  function _setListening(on) {
    _listening = on;
    $micBtn.classList.toggle('listening', on);
    _updateActions();
    if (typeof opts.onListening === 'function') opts.onListening(on);
  }
  // 面板按钮按 模式 + 是否在听 显隐:
  //   听着时 → 只显示【停止】(语音对话:停止对话 · 会议纪要:停止录制);
  //   会议纪要停下后 → 显示【整理成纪要/插入/清空】让 BRO 处理文本。
  function _updateActions() {
    if (!$panel) return;
    const meetingStopped = (mode === 'meeting' && !_listening);
    $panel.querySelectorAll('.voice-act').forEach((b) => {
      const a = b.dataset.act;
      if (a === 'stop') b.hidden = !_listening;
      else if (a === 'toclient' && opts.hideClient) b.hidden = true;
      else b.hidden = !meetingStopped;
    });
    const $stop = $panel.querySelector('[data-act="stop"]');
    if ($stop) {
      $stop.innerHTML = (mode === 'meeting')
        ? '<i class="ri-stop-circle-line"></i> 停止录制'
        : '<i class="ri-stop-circle-line"></i> 停止对话';
    }
  }
  function _applyModeMeta() {
    const m = MODES[mode];
    $micBtn.title = m.panel ? `${m.label} · 点一下开始` : '语音输入 · 点一下开始说';
    const $ic = $micBtn.querySelector('i');   // 左侧麦克风图标跟着当前模式变 · 一眼看出在哪个模式
    if ($ic) $ic.className = m.icon;
    $micMenu && $micMenu.querySelectorAll('.mic-menu-item').forEach(b => {
      b.classList.toggle('active', b.dataset.mode === mode);
    });
  }
  _applyModeMeta();

  // ── 模式菜单 ──
  function _closeMenu() { if ($micMenu) $micMenu.hidden = true; }
  function _openMenu() { if ($micMenu) $micMenu.hidden = false; }
  if ($micMode) {
    $micMode.addEventListener('click', (e) => {
      e.stopPropagation();
      $micMenu.hidden ? _openMenu() : _closeMenu();
    });
  }
  document.addEventListener('click', (e) => {
    if ($micMenu && !$micMenu.hidden && !e.target.closest('.mic-group, #micMenu, #hubBtn')) _closeMenu();
  });
  $micMenu && $micMenu.querySelectorAll('.mic-menu-item').forEach(btn => {
    btn.addEventListener('click', () => {
      if (!SR) { alert('语音功能需要 Chrome / Edge 浏览器'); return; }
      mode = btn.dataset.mode;
      localStorage.setItem(storageKey, mode);
      _applyModeMeta();
      _closeMenu();
      if (typeof opts.onModeChange === 'function') opts.onModeChange(mode);
    });
  });

  // ── 计时器 ──
  function _startTimer() {
    _startTs = Date.now();
    const tick = () => {
      const s = Math.floor((Date.now() - _startTs) / 1000);
      if ($timer) $timer.textContent = String((s / 60) | 0).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0');
    };
    tick();
    _timerId = setInterval(tick, 1000);
  }
  function _stopTimer() { if (_timerId) { clearInterval(_timerId); _timerId = null; } }

  // ── 转写面板 ──
  function _openPanel() {
    if (!$panel) return;
    if (mode === 'transcribe' && opts.compactTranscribe) return;
    const isChat = (mode === 'transcribe');
    $panel.classList.toggle('is-chat', isChat);
    $panel.classList.toggle('is-meeting', !isChat);
    if ($panelMode) $panelMode.textContent = isChat ? '语音对话 · 通话中' : '会议纪要 · 录制中';
    $panel.hidden = false;
    if ($recNote) { $recNote.hidden = true; $recNote.className = 'voice-rec-note'; }
  }
  function _emitLive(finalPart, interim) {
    if (typeof opts.onTranscript === 'function') opts.onTranscript(finalPart || '', interim || '');
  }
  function _renderTranscript(interim) {
    _emitLive(_finalText, interim);
    if (!$script) return;
    $script.innerHTML = escHtml(_finalText) + (interim ? '<span class="voice-interim">' + escHtml(interim) + '</span>' : '');
    $script.scrollTop = $script.scrollHeight;
  }
  function _setRecNote(html, cls) {
    if (!$recNote) return;
    $recNote.hidden = false;
    $recNote.className = 'voice-rec-note ' + (cls || '');
    $recNote.innerHTML = html;
  }

  // ── SpeechRecognition ──
  function _makeSR() {
    const r = new SR();
    r.lang = 'zh-CN'; r.interimResults = true; r.continuous = true; r.maxAlternatives = 1;
    return r;
  }
  function _startDictation() {
    _rec = _makeSR();
    _dictBase = $input.value ? $input.value.replace(/\s+$/, '') + ' ' : '';
    let finalText = '';
    _rec.onresult = (e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) finalText += r[0].transcript; else interim += r[0].transcript;
      }
      $input.value = _dictBase + finalText + interim;
      _autosize();
      $input.dispatchEvent(new Event('input', { bubbles: true }));
      _emitLive(_dictBase + finalText, interim);
    };
    _rec.onend = () => {
      _rec = null; _setListening(false);
      if (finalText) {
        $input.value = _dictBase + finalText;
        _autosize();
        $input.dispatchEvent(new Event('input', { bubbles: true }));
      }
      $input.focus();
    };
    _rec.onerror = _srError;
    _rec.start();
    _setListening(true);
  }
  // 绑一个 SR 实例并启动。 onend 里【建新实例】重启 (不是复用旧实例 .start()):
  //   Chromium 复用旧实例重启会把上一段 final 再 replay 一次 onresult → 没说话也被当新话发出去
  //   (BRO 撞到的"第一句后自动又发个'查'")。 新实例 e.results 从零·根治重复。
  function _bindSR(onResult) {
    const r = _makeSR();
    const gen = _srGen;   // 绑死本代号·换代后这个实例的 onend 一律作废
    r.onresult = onResult;
    r.onerror = _srError;
    r.onend = () => {
      if (gen !== _srGen) { return; }   // 已被暂停/停止/换代 → 旧实例的收尾不再重启·防并发双识别
      if (!_manualStop && _listening && !_voicePaused) {
        try { _rec = _bindSR(onResult); }
        catch (_) { setTimeout(() => { if (gen === _srGen && !_manualStop && _listening && !_voicePaused) { try { _rec = _bindSR(onResult); } catch (__) {} } }, 300); }
      } else {
        _rec = null;
      }
    };
    r.start();
    return r;
  }
  function _renderChat(interim) {
    _emitLive(_pendingBuf, interim);
    if (!$script) return;
    $script.innerHTML = escHtml(_pendingBuf) + (interim ? '<span class="voice-interim">' + escHtml(interim) + '</span>' : '');
    $script.scrollTop = $script.scrollHeight;
  }
  // ── 语音对话 · 停顿约 1 秒把这段自动发给 AI ──
  function _startVoiceChat() {
    _pendingBuf = '';
    _rec = _bindSR((e) => {
      let interim = '', gotFinal = false;
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) { _pendingBuf += r[0].transcript; gotFinal = true; } else interim += r[0].transcript;
      }
      _renderChat(interim);
      if (gotFinal) _scheduleFlush();
    });
  }
  function _scheduleFlush() {
    if (_silenceTimer) clearTimeout(_silenceTimer);
    _silenceTimer = setTimeout(_tryFlush, SILENCE_MS);
  }
  function _tryFlush() {
    _silenceTimer = null;
    if (_voicePaused) return;                    // AI 回复中 · 收音已停 · 不该有可发内容
    const txt = (_pendingBuf || '').trim();
    if (!txt) return;
    _pendingBuf = '';
    _renderChat('');
    $input.value = txt;
    _autosize();
    $input.dispatchEvent(new Event('input', { bubbles: true }));
    doSend();
    _pauseForReply();                            // 发完就停收音 · 排队也算发出去了 · 听环能看见条
  }
  // AI 回复期间暂停麦克风 (BRO: 语音对话该轮流说·回消息时别录音) · 盯 pending·回完自动恢复
  function _pauseForReply() {
    if (mode !== 'transcribe') return;
    _voicePaused = true; _sawPending = false; _pauseTicks = 0;
    _srGen++;                                    // 作废当前实例·停了别自动重启
    if (_rec) { try { _rec.stop(); } catch (_) {} }
    _stopMeter();
    $micBtn.classList.remove('listening');
    _renderChat('');
    _setRecNote('<i class="ri-pause-circle-line"></i> OPUS 回复中 · 已暂停收音 · 回完自动继续听', 'wait');
    if (_replyWatcher) clearInterval(_replyWatcher);
    _replyWatcher = setInterval(() => {
      _pauseTicks++;
      if (isPending()) { _sawPending = true; return; }
      if (_sawPending || _pauseTicks > 12) _resumeAfterReply();   // 见过 turn 又结束·或 ~5s 没起 turn 兜底
    }, 400);
  }
  function _resumeAfterReply() {
    if (_replyWatcher) { clearInterval(_replyWatcher); _replyWatcher = null; }
    if (!_voicePaused) return;
    _voicePaused = false;
    if (_manualStop || !_listening || mode !== 'transcribe') return;  // 期间用户点了停 → 不恢复
    $micBtn.classList.add('listening');
    _setRecNote('<i class="ri-mic-fill"></i> 在听 · 你说完停约 1 秒会自动发给 OPUS', 'rec');
    _startMeter();
    _startVoiceChat();                           // 建新 SR 实例·继续听下一句
  }
  // ── 会议纪要 = 持续把麦克风转成文本累积 · 停止后交给 AI 拆分 ──
  function _startMeetingTranscribe() {
    _rec = _bindSR((e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) _finalText += r[0].transcript; else interim += r[0].transcript;
      }
      _renderTranscript(interim);
      _setRecNote('<i class="ri-record-circle-fill"></i> 录制中 · 已记录 ' + _finalText.trim().length + ' 字', 'rec');
    });
  }
  function _srError(e) {
    if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
      _manualStop = true;
      if (!opts.silentDenied) alert('麦克风权限被拒 · 请在浏览器设置中允许访问麦克风');
      _stopVoice(true);
    } else if (e.error !== 'aborted' && e.error !== 'no-speech') {
      console.warn('语音识别出错:', e.error);
    }
  }

  // (卷七十五续六 · 系统音频 getDisplayMedia/MediaRecorder 那套已移除:BRO 定会议纪要=纯麦克风
  //  录成文本·停止后交给 AI 拆分;线上会议对方声音等后端 ASR 落地再补·不在此纠结。)

  // 听环电平 · 跟 SpeechRecognition 并行拿一条麦 · 给外圈波形用
  let _meterStream = null, _meterCtx = null, _meterAnalyser = null, _meterRaf = 0;
  function _stopMeter() {
    if (_meterRaf) { cancelAnimationFrame(_meterRaf); _meterRaf = 0; }
    if (_meterStream) { _meterStream.getTracks().forEach(t => t.stop()); _meterStream = null; }
    if (_meterCtx) { try { _meterCtx.close(); } catch (_) {} _meterCtx = null; }
    _meterAnalyser = null;
    if (typeof opts.onLevel === 'function') opts.onLevel(0, null);
  }
  function _startMeter() {
    if (typeof opts.onLevel !== 'function' || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
    _stopMeter();
    navigator.mediaDevices.getUserMedia({ audio: true, video: false }).then(stream => {
      _meterStream = stream;
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      _meterCtx = new AC();
      const src = _meterCtx.createMediaStreamSource(stream);
      _meterAnalyser = _meterCtx.createAnalyser();
      _meterAnalyser.fftSize = 64;
      _meterAnalyser.smoothingTimeConstant = 0.55;
      src.connect(_meterAnalyser);
      const bins = new Uint8Array(_meterAnalyser.fftSize);
      const tick = () => {
        if (!_meterAnalyser) return;
        _meterAnalyser.getByteTimeDomainData(bins);
        let sum = 0;
        for (let i = 0; i < bins.length; i++) {
          const v = (bins[i] - 128) / 128;
          sum += v * v;
        }
        opts.onLevel(Math.sqrt(sum / bins.length), bins);
        _meterRaf = requestAnimationFrame(tick);
      };
      tick();
    }).catch(() => { if (typeof opts.onLevel === 'function') opts.onLevel(0, null); });
  }

  // ── 启停总入口 ──
  function _startVoice() {
    if (!SR) { alert('语音功能需要 Chrome / Edge 浏览器'); return; }
    _manualStop = false;
    _voicePaused = false;
    _srGen++;                                    // 新一轮·作废上一轮任何残留实例
    if (_replyWatcher) { clearInterval(_replyWatcher); _replyWatcher = null; }
    if (mode === 'dictation') { _startMeter(); _startDictation(); return; }
    _finalText = '';
    _pendingBuf = '';
    if ($script) $script.innerHTML = '';
    _openPanel();
    _startTimer();
    _startMeter();
    _setListening(true);
    if (mode === 'transcribe') {
      _setRecNote('<i class="ri-mic-fill"></i> 在听 · 你说完停约 1 秒会自动发给 OPUS', 'rec');
      _startVoiceChat();
    } else {
      _setRecNote('<i class="ri-record-circle-fill"></i> 录制中 · 边说边记 · 完了点【停止录制】', 'rec');
      _startMeetingTranscribe();
    }
  }
  function _stopVoice(manual) {
    _manualStop = !!manual;
    _voicePaused = false;
    _srGen++;                                    // 换代·让在途 onend 全部失效
    if (_replyWatcher) { clearInterval(_replyWatcher); _replyWatcher = null; }
    if (_silenceTimer) { clearTimeout(_silenceTimer); _silenceTimer = null; }
    if (_rec) { try { _rec.stop(); } catch (_) {} }
    _stopTimer();
    _stopMeter();
    _setListening(false);
    _emitLive('', '');
    _afterStop();
  }
  // 停下后收尾:语音对话 → 关面板(没后续动作);会议纪要 → 留文本·亮出整理/插入/清空。
  function _afterStop() {
    if (mode === 'transcribe') {
      if ($panel) $panel.hidden = true;
    } else if (mode === 'meeting') {
      if ($panelMode) $panelMode.textContent = '会议纪要 · 已停止';
      const n = (_finalText || '').trim().length;
      if (n > 0) _setRecNote('<i class="ri-stop-circle-fill"></i> 已停止 · 记录 ' + n + ' 字 · 点【整理成纪要】交给 OPUS 拆分', 'done');
      else _setRecNote('<i class="ri-information-line"></i> 没记到文字 · 检查麦克风权限后重录', 'warn');
    }
  }

  if (bindMicClick) {
    $micBtn.addEventListener('click', () => {
      if (_listening) { _stopVoice(true); return; }
      _startVoice();
    });
  }

  window.__voice = {
    start: _startVoice,
    stop: function () { _stopVoice(true); },
    setMode: function (m) {
      if (!MODES[m]) return;
      mode = m;
      localStorage.setItem(storageKey, mode);
      _applyModeMeta();
      if (typeof opts.onModeChange === 'function') opts.onModeChange(mode);
    },
    getMode: function () { return mode; },
    isListening: function () { return _listening; },
    hasSR: function () { return !!SR; },
    modes: MODES,
  };

  // ── 面板动作 ──
  $panel && $panel.querySelectorAll('.voice-act').forEach(btn => {
    btn.addEventListener('click', () => {
      const act = btn.dataset.act;
      if (act === 'stop') { _stopVoice(true); return; }
      if (act === 'clear') {
        _finalText = ''; _renderTranscript('');
        _setRecNote('<i class="ri-eraser-line"></i> 已清空 · 点麦克风可重新录制', 'done');
        return;
      }
      const txt = (_finalText || '').trim();
      if (!txt) { return; }
      if (act === 'insert') {
        $input.value = ($input.value ? $input.value.trimEnd() + '\n' : '') + txt;
        _autosize();
        $panel.hidden = true;
        $input.focus();
      } else if (act === 'toclient') {
        // 会议纪要 ↔ 客户时间线打通 · 转写文字一键存成某客户 kind=meeting 条
        if (!doPick) { alert('客户档案模块未加载'); return; }
        doPick((cid, name) => {
          fetch('/dashboard/clients/note', {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + getToken(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ client_id: cid, text: txt, kind: 'meeting' }),
          }).then(r => {
            if (r.ok) _setRecNote('<i class="ri-check-line"></i> 已存进「' + name + '」的会议记录 · 想要结构化纪要可再点【整理成纪要】', 'done');
            else alert('存失败 [' + r.status + ']');
          }).catch(e => alert('网络出错: ' + e.message));
        });
      } else if (act === 'minutes') {
        $input.value = '【整理会议纪要】下面是会议的语音转写文字，帮我拆分整理成结构化会议纪要：\n'
          + '1) 议题概述  2) 关键结论/决议  3) 待办事项(含负责人与时间)  4) 风险/待确认。\n'
          + '保留关键人名、数字、日期，语言精炼;转写可能有同音错别字，按语境修正。\n'
          + '整理完若这场会议对应某个已知客户，主动问我要不要用 manage_client 把纪要存成他的会议记录(kind=meeting)。\n\n---\n' + txt;
        $panel.hidden = true;
        doSend();
      }
    });
  });
  $close && $close.addEventListener('click', () => {
    _stopVoice(true);
    $panel.hidden = true;
  });
}

window.initVoice = initVoice;
