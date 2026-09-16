/* 本机脉搏 · 输入框上方分身 / 服务药丸 */
(function (g) {
  var root = null;
  var data = { spawns: [], services: [] };
  var openKind = null;
  var openId = null;
  var timer = null;
  var lastSig = "";
  var lastSid = "";
  var sessionFn = null;

  function token() {
    try {
      return localStorage.getItem("opus_ui_token") || localStorage.getItem("Daemonkey_ui_token") || "";
    } catch (e) { return ""; }
  }
  function headers() {
    var t = token();
    var h = { "Accept": "application/json" };
    if (t) h.Authorization = "Bearer " + t;
    return h;
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
    });
  }
  function fmt(sec) {
    if (sec == null || sec === "") return "—";
    sec = Math.max(0, Math.floor(Number(sec)));
    var h = Math.floor(sec / 3600);
    var m = Math.floor((sec % 3600) / 60);
    var s = sec % 60;
    if (h) return h + "h " + String(m).padStart(2, "0") + "m";
    if (m) return m + "m " + String(s).padStart(2, "0") + "s";
    return s + "s";
  }
  function currentSid() {
    try { return String(sessionFn ? (sessionFn() || "") : ""); } catch (e) { return ""; }
  }
  function scopedSid() {
    var s = currentSid();
    if (!s || s.indexOf("tmp-") === 0) return "";
    return s;
  }
  function pulseQuery(sid) {
    var s = sid == null ? scopedSid() : String(sid || "");
    return "?session_id=" + encodeURIComponent(s);
  }
  function hasItems(snap) {
    return !!((snap && snap.spawns && snap.spawns.length) || (snap && snap.services && snap.services.length));
  }
  function emit(name, detail) {
    if (g.Daemonkey && typeof g.Daemonkey.emit === "function") g.Daemonkey.emit(name, detail || {});
  }
  function deadProxy() {
    return (data.services || []).some(function (s) { return s.kind === "proxy" && !s.ok; });
  }
  function iconFor(item, kind) {
    if (kind === "spawns") return "ri-group-line";
    if (item.kind === "proxy") return "ri-shield-flash-line";
    if (item.kind === "comfy") return "ri-movie-2-line";
    return "ri-terminal-box-line";
  }

  function stashTalk() {
    if (!root) return "";
    var inp = root.querySelector("input[data-talk]");
    return inp ? String(inp.value || "") : "";
  }
  function restoreTalk(v) {
    if (!root || !v) return;
    var inp = root.querySelector("input[data-talk]");
    if (inp) inp.value = v;
  }

  function render() {
    if (!root) return;
    var draft = stashTalk();
    var sp = data.spawns || [];
    var sv = data.services || [];
    if (!sp.length && !sv.length) {
      root.hidden = true;
      root.innerHTML = "";
      openKind = null;
      openId = null;
      return;
    }
    root.hidden = false;
    var pills = "";
    if (sp.length) {
      pills += '<button type="button" class="hp-pill' + (openKind === "spawns" ? " on" : "") + '" data-kind="spawns">'
        + '<span class="hp-dots" aria-hidden="true"><i></i><i></i></span>'
        + '<span class="n">' + sp.length + "</span> 分身</button>";
    }
    if (sv.length) {
      pills += '<button type="button" class="hp-pill' + (deadProxy() ? " warn" : "") + (openKind === "services" ? " on" : "") + '" data-kind="services">'
        + '<i class="ri-terminal-box-line"></i>'
        + '<span class="n">' + sv.length + "</span> 服务</button>";
    }
    var panel = "";
    if (openKind) {
      var list = openKind === "spawns" ? sp : sv;
      var title = openKind === "spawns" ? (list.length + " 个分身在外面") : (list.length + " 服务在跑");
      var ico = openKind === "spawns" ? "ri-group-line" : "ri-terminal-box-line";
      panel = '<div class="hp-panel">'
        + '<div class="hp-head"><i class="' + ico + '"></i><span>' + esc(title) + "</span>"
        + '<button type="button" class="hp-x" data-hp="close" title="收起"><i class="ri-close-line"></i></button></div>'
        + '<div class="hp-list">' + list.map(rowHtml).join("") + "</div></div>";
    }
    root.innerHTML = panel + '<div class="hp-row">' + pills + "</div>";
    restoreTalk(draft);
    hydrateLogs();
  }

  /* 服务详情里的「命令行输出」· 点开才拉 · 拉过就缓在内存里（刷新按钮手动重拉）
     —— 这就是以前那个弹出来的 cmd 黑框的去处。
     注：缓存放内存、不放 DOM 属性 —— render() 每次 root.innerHTML 重建，
     挂在元素上的 data-loaded 会被整棵重建清掉，那个守卫永远不会命中。 */
  var logCache = {};

  function hydrateLogs() {
    if (!root) return;
    var boxes = root.querySelectorAll(".hp-logwrap[data-log]");
    for (var i = 0; i < boxes.length; i++) {
      var nm = boxes[i].getAttribute("data-log");
      if (Object.prototype.hasOwnProperty.call(logCache, nm)) {
        var p = boxes[i].querySelector(".hp-log");
        if (p) p.textContent = logCache[nm];
        continue;
      }
      loadLog(nm, boxes[i]);
    }
  }

  function loadLog(name, box, force) {
    if (!box || !name) return;
    var pre = box.querySelector(".hp-log");
    if (!force && Object.prototype.hasOwnProperty.call(logCache, name)) {
      if (pre) pre.textContent = logCache[name];
      return;
    }
    if (pre) pre.textContent = "读取中…";
    fetch("/host/pulse/service/" + encodeURIComponent(name) + "/log?tail=80", { headers: headers() })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!pre) return;
        var lines = (j && j.lines) || [];
        var txt = lines.length ? lines.join("\n") : ((j && j.message) || "（暂无输出）");
        logCache[name] = txt;
        pre.textContent = txt;
        if (lines.length) pre.scrollTop = pre.scrollHeight;
      })
      .catch(function () { if (pre) pre.textContent = "（读取失败）"; });
  }

  function spawnSub(item) {
    if ((item.status || "") === "pending") return "排队";
    if (item.doing) return item.doing;
    var n = item.tool_calls || 0;
    return n ? ("工具 " + n + " 次") : (item.status || "running");
  }

  function actChips(item) {
    var acts = item.acts || [];
    if (!acts.length) return "";
    return '<div class="hp-acts">' + acts.map(function (a, i) {
      var live = i === acts.length - 1 && (item.status || "") === "running";
      return '<span class="hp-act' + (live ? " live" : "") + '">'
        + esc((a.v || "") + " " + (a.t || "")) + "</span>";
    }).join("") + "</div>";
  }

  function rowHtml(item) {
    var kind = openKind;
    var id = item.id || item.name || "";
    var open = openId === id;
    var title = kind === "spawns" ? (item.goal || id) : (item.title || item.name || id);
    var sub = item.sub || (kind === "spawns" ? spawnSub(item) : "");
    var dot = kind === "spawns"
      ? '<span class="hp-dot busy"></span>'
      : '<span class="hp-dot ' + (item.ok === false ? "dead" : "ok") + '"></span>';
    var canStop = kind === "spawns" || item.can_stop;
    var stopTitle = kind === "spawns" ? "打断分身" : "停下";
    var talk = "";
    if (open && kind === "spawns") {
      talk = '<div class="hp-talk">'
        + '<input type="text" data-talk="' + esc(id) + '" maxlength="2000" placeholder="给这个分身补一句">'
        + '<button type="button" data-send="' + esc(id) + '">传话</button></div>';
    }
    var extra;
    if (kind === "spawns") {
      extra = (item.note ? '<div class="hp-note">' + esc(item.note) + "</div>" : "")
        + actChips(item)
        + '<div class="hp-id">id ' + esc(id)
        + (item.parent_session_id ? " · 会话 " + esc(item.parent_session_id) : "")
        + "</div>";
    } else {
      extra = esc(item.detail || "");
      if (open) {
        extra += '<div class="hp-logwrap" data-log="' + esc(id) + '">'
          + '<div class="hp-loghdr">'
          + '<span><i class="ri-terminal-line"></i> 命令行输出</span>'
          + '<button type="button" class="hp-logx" data-logrefresh="' + esc(id) + '" title="刷新"><i class="ri-refresh-line"></i></button>'
          + "</div>"
          + '<pre class="hp-log">读取中…</pre></div>';
      }
    }
    return '<div class="hp-item" data-id="' + esc(id) + '" role="button" tabindex="0">'
      + '<i class="ic ' + iconFor(item, kind) + '"></i>'
      + '<div><div class="ttl">' + esc(title) + '</div><div class="sub">' + dot + esc(sub) + "</div></div>"
      + '<div class="dur">' + esc(item.ok === false ? "—" : (item.age_sec == null ? "发现" : fmt(item.age_sec))) + "</div>"
      + (canStop && item.ok !== false
        ? '<button type="button" class="act" data-stop="' + esc(id) + '" title="' + stopTitle + '"><i class="ri-stop-circle-line"></i></button>'
        : "<span></span>")
      + "</div>"
      + '<div class="hp-detail"' + (open ? "" : " hidden") + ">" + extra + talk + "</div>";
  }

  function onClick(ev) {
    var t = ev.target;
    if (!(t instanceof Element)) return;
    var close = t.closest("[data-hp=close]");
    if (close) { openKind = null; openId = null; render(); return; }
    var stop = t.closest("[data-stop]");
    if (stop) { ev.preventDefault(); ev.stopPropagation(); actStop(stop.getAttribute("data-stop")); return; }
    var send = t.closest("[data-send]");
    if (send) { ev.preventDefault(); ev.stopPropagation(); actTalk(send.getAttribute("data-send")); return; }
    var lr = t.closest("[data-logrefresh]");
    if (lr) {
      ev.preventDefault(); ev.stopPropagation();
      loadLog(lr.getAttribute("data-logrefresh"), lr.closest(".hp-logwrap"), true);
      return;
    }
    // 日志区（含选中/复制文字）不触发整卡折叠 —— 否则想复制一行输出就把面板收掉了
    if (t.closest(".hp-logwrap")) return;
    var pill = t.closest(".hp-pill");
    if (pill) {
      var k = pill.getAttribute("data-kind");
      openKind = openKind === k ? null : k;
      openId = null;
      render();
      return;
    }
    var item = t.closest(".hp-item");
    if (item) {
      var id = item.getAttribute("data-id");
      openId = openId === id ? null : id;
      render();
    }
  }

  function onKey(ev) {
    if (ev.key === "Enter") {
      var inp = ev.target;
      if (inp && inp.getAttribute && inp.getAttribute("data-talk")) {
        ev.preventDefault();
        actTalk(inp.getAttribute("data-talk"));
      }
    }
    if (ev.key === "Escape") { openKind = null; openId = null; render(); }
  }

  function actStop(id) {
    if (!id) return;
    var url = openKind === "spawns"
      ? "/host/pulse/spawn/" + encodeURIComponent(id) + "/cancel" + pulseQuery()
      : "/host/pulse/service/" + encodeURIComponent(id) + "/stop" + pulseQuery();
    fetch(url, { method: "POST", headers: headers() }).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, j: j }; });
    }).then(function (x) {
      if (x.j && x.j.pulse) paintCurrent(x.j.pulse);
      else refresh();
      if (openKind === "spawns") emit("hostpulse:spawn-cancel", { id: id, pulse: data });
    }).catch(function () { refresh(); });
  }

  function actTalk(id) {
    if (!root || !id) return;
    var inp = root.querySelector('input[data-talk="' + id.replace(/"/g, "") + '"]');
    var msg = inp ? String(inp.value || "").trim() : "";
    if (!msg) return;
    fetch("/host/pulse/spawn/" + encodeURIComponent(id) + "/message" + pulseQuery(), {
      method: "POST",
      headers: Object.assign({ "Content-Type": "application/json" }, headers()),
      body: JSON.stringify({ message: msg }),
    }).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, j: j }; });
    }).then(function (x) {
      if (!x.ok) return;
      if (inp) inp.value = "";
      if (x.j && x.j.pulse) paintCurrent(x.j.pulse);
      emit("hostpulse:spawn-message", { id: id, message: msg });
    }).catch(function () {});
  }

  function tickLive() {
    if (!root || !openKind) return;
    var list = openKind === "spawns" ? (data.spawns || []) : (data.services || []);
    var items = root.querySelectorAll(".hp-item");
    for (var i = 0; i < items.length; i++) {
      var id = items[i].getAttribute("data-id");
      var row = null;
      for (var j = 0; j < list.length; j++) {
        if ((list[j].id || list[j].name) === id) { row = list[j]; break; }
      }
      if (!row) continue;
      var dur = items[i].querySelector(".dur");
      if (dur) dur.textContent = row.ok === false ? "—" : (row.age_sec == null ? "发现" : fmt(row.age_sec));
      if (openKind === "spawns") {
        var sub = items[i].querySelector(".sub");
        if (sub) {
          sub.innerHTML = '<span class="hp-dot busy"></span>' + esc(spawnSub(row));
        }
        var det = items[i].nextElementSibling;
        if (det && det.classList.contains("hp-detail") && !det.hidden) {
          var nEl = det.querySelector(".hp-note");
          if (row.note) {
            if (nEl) nEl.textContent = row.note;
            else det.insertAdjacentHTML("afterbegin", '<div class="hp-note">' + esc(row.note) + "</div>");
          }
          var chips = actChips(row);
          var aEl = det.querySelector(".hp-acts");
          if (aEl) {
            if (chips) aEl.outerHTML = chips;
            else aEl.remove();
          } else if (chips) {
            var idEl = det.querySelector(".hp-id");
            if (idEl) idEl.insertAdjacentHTML("beforebegin", chips);
            else det.insertAdjacentHTML("afterbegin", chips);
          }
        }
      }
    }
  }

  /* 回包必须还是眼前这场 · 切对话 / 停别人家 / 全局快照都不能刷这条 */
  function belongsHere(snap) {
    if (!snap) return false;
    var key = String(snap.session_id != null ? snap.session_id : "");
    if (key === "*") return false;
    return key === scopedSid();
  }

  function apply(snap) {
    if (!belongsHere(snap)) return false;
    data = { spawns: snap.spawns || [], services: snap.services || [] };
    var sig = JSON.stringify([
      data.spawns.map(function (s) { return [s.id, s.status, s.cancel_requested]; }),
      data.services.map(function (s) { return [s.id, s.ok, s.port]; }),
    ]);
    if (sig !== lastSig) {
      lastSig = sig;
      render();
      emit("hostpulse:tick", data);
    } else {
      tickLive();
    }
    return true;
  }

  function paintCurrent(snap) {
    if (apply(snap)) return;
    refresh();
  }

  function refresh() {
    if (document.hidden) return Promise.resolve();
    var sid = scopedSid();
    if (sid !== lastSid) {
      lastSid = sid;
      lastSig = "";
      openKind = null;
      openId = null;
      data = { spawns: [], services: [] };
      render();
    }
    return fetch("/host/pulse" + pulseQuery(sid), { headers: headers() }).then(function (r) {
      return r.ok ? r.json() : null;
    }).then(function (j) {
      if (!j) return;
      if (scopedSid() !== sid) return;
      apply(j);
    }).catch(function () {});
  }

  function peek(sid, all) {
    var q = all ? "?all=1" : pulseQuery(sid);
    return fetch("/host/pulse" + q, { headers: headers() }).then(function (r) {
      return r.ok ? r.json() : { spawns: [], services: [] };
    }).catch(function () { return { spawns: [], services: [] }; });
  }

  function stopSession(sid, all) {
    return fetch("/host/pulse/stop", {
      method: "POST",
      headers: Object.assign({ "Content-Type": "application/json" }, headers()),
      body: JSON.stringify(all ? { all: true } : { session_id: sid || scopedSid() }),
    }).then(function (r) { return r.json(); }).then(function (j) {
      if (j && j.pulse) paintCurrent(j.pulse);
      else refresh();
      return j;
    }).catch(function () { refresh(); });
  }

  function confirmClose(opts) {
    opts = opts || {};
    var sid = opts.sid != null ? opts.sid : scopedSid();
    var mode = opts.mode || "close";
    var load = opts.pulse ? Promise.resolve(opts.pulse) : peek(sid, !!opts.all);
    return load.then(function (snap) {
      if (!hasItems(snap)) return "keep";
      return showAsk(mode, snap);
    });
  }

  function showAsk(mode, snap) {
    return new Promise(function (resolve) {
      var old = document.getElementById("hpAsk");
      if (old) old.remove();
      var nSp = (snap.spawns || []).length;
      var nSv = (snap.services || []).length;
      var bits = [];
      if (nSp) bits.push(nSp + " 个分身");
      if (nSv) bits.push(nSv + " 个服务");
      var what = bits.join("、");
      var title = "还有工作在跑";
      var body = "这个对话里还有 " + what + "。";
      var keepLabel = "继续跑";
      var stopLabel = "停掉";
      var showKeep = true;
      if (mode === "delete") {
        title = "删除这个对话？";
        body = "这个对话里还有 " + what + "。删除会停掉它们，历史也回不来。";
        keepLabel = "";
        stopLabel = "停掉并删除";
        showKeep = false;
      } else if (mode === "quit") {
        title = "关掉后台？";
        body = "还有 " + what + " 在跑。关掉 daemon 以后它们可能还留在本机。";
        keepLabel = "继续跑";
        stopLabel = "停掉再关";
      } else {
        body = "这个对话里还有 " + what + "。关掉的时候要一起停掉吗？";
        keepLabel = "继续跑";
        stopLabel = "停掉";
      }
      var rows = (snap.spawns || []).map(function (s) {
        return '<li><i class="ri-group-line"></i> ' + esc(s.goal || s.id || "分身") + "</li>";
      }).concat((snap.services || []).map(function (s) {
        return '<li><i class="ri-terminal-box-line"></i> ' + esc(s.title || s.name || "服务") + "</li>";
      })).join("");
      var box = document.createElement("div");
      box.id = "hpAsk";
      box.className = "hp-ask";
      box.innerHTML = '<div class="hp-ask-card" role="dialog" aria-modal="true">'
        + '<div class="hp-ask-title"><i class="ri-error-warning-line"></i> ' + esc(title) + "</div>"
        + '<div class="hp-ask-body">' + esc(body) + "</div>"
        + '<ul class="hp-ask-list">' + rows + "</ul>"
        + '<div class="hp-ask-acts">'
        + '<button type="button" data-hp-ask="cancel">取消</button>'
        + (showKeep ? '<button type="button" data-hp-ask="keep">' + esc(keepLabel) + "</button>" : "")
        + '<button type="button" class="danger" data-hp-ask="stop">' + esc(stopLabel) + "</button>"
        + "</div></div>";
      function finish(ans) {
        document.removeEventListener("keydown", onEsc, true);
        box.remove();
        resolve(ans);
      }
      function onEsc(ev) {
        if (ev.key === "Escape") { ev.preventDefault(); finish("cancel"); }
      }
      box.addEventListener("click", function (ev) {
        var t = ev.target;
        if (!(t instanceof Element)) return;
        var btn = t.closest("[data-hp-ask]");
        if (btn) { finish(btn.getAttribute("data-hp-ask")); return; }
        if (t === box) finish("cancel");
      });
      document.addEventListener("keydown", onEsc, true);
      document.body.appendChild(box);
    });
  }

  function mount(el, opts) {
    sessionFn = opts && typeof opts.session === "function"
      ? opts.session
      : function () {
        try { return (g.SessionRuntime && SessionRuntime.activeSid && SessionRuntime.activeSid()) || ""; }
        catch (e) { return ""; }
      };
    root = typeof el === "string" ? document.getElementById(el) : el;
    if (!root) return;
    root.classList.add("host-pulse");
    root.addEventListener("click", onClick);
    root.addEventListener("keydown", onKey);
    refresh();
    if (timer) clearInterval(timer);
    timer = setInterval(refresh, 3000);
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden) refresh();
    });
  }

  g.HostPulse = {
    mount: mount,
    refresh: refresh,
    peek: peek,
    stopSession: stopSession,
    confirmClose: confirmClose,
    hasItems: hasItems,
  };
})(typeof window !== "undefined" ? window : this);
