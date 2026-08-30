/* 对话内检查点 · 共用网络层（工作台 / 陪伴都引）
   只负责 sid、停轮、两条 restore 路径。UI 各页自己画。 */
(function (g) {
  function token() {
    if (typeof g.token === 'string' && g.token) return g.token;
    try {
      return localStorage.getItem('opus_ui_token')
        || localStorage.getItem('Daemonkey_ui_token')
        || '';
    } catch (e) { return ''; }
  }

  function headers() {
    var h = { 'Content-Type': 'application/json' };
    var t = token();
    if (t) h.Authorization = 'Bearer ' + t;
    return h;
  }

  function resolveSid(el) {
    var host = el && el.closest && (el.closest('.session-msgs') || el.closest('[data-sid]'));
    var fromBox = host && host.dataset && host.dataset.sid;
    var active = (typeof g.activeSession === 'function') ? g.activeSession() : null;
    var rt = g.SessionRuntime && SessionRuntime.activeSid && SessionRuntime.activeSid();
    var page = (typeof g.getSid === 'function' && g.getSid()) || g.sessionId || '';
    var cand = [fromBox, active && active.sessionId, rt, page];
    var tmp = '';
    for (var i = 0; i < cand.length; i++) {
      var v = cand[i] ? String(cand[i]) : '';
      if (!v) continue;
      if (v.indexOf('tmp-') !== 0) return v;
      if (!tmp) tmp = v;
    }
    return tmp;
  }

  function idsOf(el) {
    var turnId = (el && el.dataset && el.dataset.turnId) || '';
    var raw = el && el.dataset ? el.dataset.line : '';
    var line = (raw !== undefined && raw !== '') ? Number(raw) : null;
    if (line != null && isNaN(line)) line = null;
    if (!turnId && line == null && g.SessionRuntime) {
      var sid = resolveSid(el);
      var s = sid && SessionRuntime.get(sid);
      if (s && s.currentTurnId) turnId = s.currentTurnId;
    }
    return { turnId: turnId, line: line };
  }

  async function abortRunning(sid) {
    if (!sid) return;
    if (g.SessionRuntime && SessionRuntime.holdOutbound) SessionRuntime.holdOutbound(sid);
    if (g.SessionRuntime && SessionRuntime.abortSession) SessionRuntime.abortSession(sid);
    await new Promise(function (r) { setTimeout(r, 80); });
  }

  function err(plan, status) {
    if (!plan) return 'HTTP ' + status;
    var d = plan.error || plan.detail;
    if (typeof d === 'string' && d) return d;
    if (d && typeof d === 'object') {
      try { return JSON.stringify(d); } catch (e) {}
    }
    return 'HTTP ' + status;
  }

  async function post(sid, body) {
    var h = headers();
    var r = await fetch('/sessions/' + encodeURIComponent(sid) + '/restore', {
      method: 'POST', headers: h, body: JSON.stringify(body),
    });
    if (r.status !== 404) return { r: r, headers: h };
    var r2 = await fetch('/restore-checkpoint', {
      method: 'POST', headers: h,
      body: JSON.stringify(Object.assign({ sid: sid }, body)),
    });
    return { r: r2, headers: h };
  }

  async function preview(el) {
    var sid = resolveSid(el);
    if (!sid) throw new Error('这本话题还没落稳');
    if (!token()) throw new Error('还没填 token');
    var ids = idsOf(el);
    if (!ids.turnId && ids.line == null) throw new Error('这句还没挂上，等这轮出字再点，或硬刷后再试');
    await abortRunning(sid);
    var body = { apply: false };
    if (ids.turnId) body.turn_id = ids.turnId;
    if (ids.line != null) body.line = ids.line;
    var got = await post(sid, body);
    var plan = {};
    try { plan = await got.r.json(); } catch (e) {}
    if (!got.r.ok || plan.ok === false) throw new Error(err(plan, got.r.status));
    return { sid: sid, body: body, plan: plan, el: el };
  }

  async function apply(ctx, dropKeep) {
    var sid = ctx.sid;
    if (!sid) throw new Error('这本话题还没落稳');
    await abortRunning(sid);
    var body = Object.assign({}, ctx.body, { apply: true, drop_keep: !!dropKeep });
    var got = await post(sid, body);
    var out = {};
    try { out = await got.r.json(); } catch (e) {}
    if (!got.r.ok || out.ok === false) throw new Error(err(out, got.r.status));
    return out;
  }

  g.CkptRestore = {
    token: token,
    resolveSid: resolveSid,
    idsOf: idsOf,
    abortRunning: abortRunning,
    post: post,
    preview: preview,
    apply: apply,
    err: err,
  };
})(window);
