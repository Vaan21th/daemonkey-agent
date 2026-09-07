/* 插件库中间栏：插件 | 我的改装 | 扩展市场。房间门复用这一页。 */
(function () {
  var TAB_KEY = "dk_plugin_hub";
  var _data = null;
  var WHY = { unpublished: "货架没有", newer: "本机更新", edited: "装完后又改过" };
  var KIND = { skin: "皮肤", app: "工坊应用", flow: "流程", playbook: "操作手册", mod: "MOD" };

  function tab() {
    try { return sessionStorage.getItem(TAB_KEY) || "plugins"; } catch (e) { return "plugins"; }
  }
  function setTab(v) {
    try { sessionStorage.setItem(TAB_KEY, v); } catch (e) {}
  }
  function dash() {
    if (typeof $dashView !== "undefined" && $dashView) return $dashView;
    return document.getElementById("dashView") || document.getElementById("detailPane");
  }
  function auth() {
    var t = (typeof token !== "undefined" && token) || "";
    try { t = t || localStorage.getItem("opus_ui_token") || ""; } catch (e) {}
    return { Authorization: "Bearer " + (t || "__loopback__") };
  }
  function esc(s) {
    return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
  }
  function toast(msg) {
    if (typeof showChatToast === "function") showChatToast(msg);
  }

  function injectTabs(active, afterHead) {
    var el = dash();
    if (!el) return;
    var bar = document.createElement("div");
    bar.className = "depot-tabs";
    bar.innerHTML =
      '<button class="depot-tab' + (active === "plugins" ? " active" : "") + '" type="button" data-hub="plugins">' +
      '<i class="ri-tools-line"></i><span>插件</span></button>' +
      '<button class="depot-tab' + (active === "overlays" ? " active" : "") + '" type="button" data-hub="overlays">' +
      '<i class="ri-stack-line"></i><span>我的改装</span></button>' +
      '<button class="depot-tab' + (active === "market" ? " active" : "") + '" type="button" data-hub="market">' +
      '<i class="ri-store-2-line"></i><span>扩展市场</span></button>';
    bar.querySelectorAll("[data-hub]").forEach(function (b) {
      b.addEventListener("click", function () {
        setTab(b.getAttribute("data-hub"));
        if (typeof loadDashboard === "function") loadDashboard("plugins");
      });
    });
    var head = el.querySelector(".dash-head");
    if (afterHead && head && head.nextSibling) el.insertBefore(bar, head.nextSibling);
    else el.insertBefore(bar, el.firstChild);
  }

  function pubLine(it) {
    if (it.score == null) return "还没公共分";
    return Number(it.score).toFixed(1) + " 分" + (it.votes != null ? " · " + it.votes + " 人" : "");
  }

  function rateRow(it, installed, mine) {
    var html = '<div class="mkt-rate"><span class="mkt-pub"><i class="ri-star-fill"></i> ' +
      pubLine(it) + "</span>";
    if (installed) {
      html += '<span class="mkt-stars">';
      for (var n = 1; n <= 5; n++) {
        html += '<button type="button" class="mkt-star' + (mine === n ? " on" : "") +
          '" data-id="' + esc(it.id) + '" data-score="' + n + '" title="' + n + '分">' +
          '<i class="' + ((mine != null && n <= mine) ? "ri-star-fill" : "ri-star-line") + '"></i></button>';
      }
      html += "</span><span class=\"mkt-mine\">" + (mine ? ("你打了 " + mine + " 分") : "点星打分") + "</span>";
    } else {
      html += '<span class="mkt-mine">装了才能打分</span>';
    }
    return html + "</div>";
  }

  function card(it, extra, rateHtml) {
    return '<div class="mkt-card">' +
      '<div class="mkt-card-top">' +
      '<span class="mkt-name">' + esc(it.name || it.id) + "</span>" +
      '<span class="mkt-kind">' + esc(KIND[it.kind] || it.kind) + "</span>" +
      extra +
      "</div>" +
      '<div class="mkt-meta">分享人 ' + esc(it.author || "未署名") +
      " · v" + esc(it.version || "?") +
      (it.description || it.desc ? "<br>" + esc(it.description || it.desc) : "") +
      "</div>" + (rateHtml || "") + "</div>";
  }

  function verdictTag(v) {
    var map = { pass: "绿灯", review: "黄灯", reject: "红灯" };
    return '<span class="mkt-verdict mkt-verdict-' + esc(v || "") + '">' + esc(map[v] || v || "") + "</span>";
  }

  function renderMarket(snap) {
    var el = dash();
    if (!el) return;
    var items = snap.items || [];
    var share = snap.shareable || [];
    var html = '<div class="dash-head"><h2><i class="ri-store-2-line"></i> 扩展市场</h2>' +
      '<span class="meta">' + (snap.source === "local" ? "本机清单" : "远程货架") +
      " · " + items.length + " 个</span>" +
      '<button type="button" onclick="loadDashboard(\'plugins\')">刷新</button></div>';
    html += '<div class="plugin-intro"><b>上架</b>会先打本机袋子，机器闸过了再向市集仓开合并申请。' +
      "红灯当场挡住；仓主在下面待审里看黄灯、一批合绿灯。" +
      (snap.can_submit ? "" : " 这台电脑还没有 Gitee 令牌（.env 的 GITEE_TOKEN），现在只能导出文件。") +
      "</div>";
    if (snap.is_owner) {
      html += '<div id="mktInbox" class="plugin-cat"><div class="plugin-cat-head">' +
        '<span class="cat-label">待审</span><span class="cat-count">…</span></div>' +
        '<div class="plugin-list"><div class="mkt-meta">正在拉合并申请…</div></div></div>';
    }
    html += '<div class="plugin-cat"><div class="plugin-cat-head"><span class="cat-label">货架</span><span class="cat-count">' + items.length + "</span></div>";
    html += '<div class="plugin-list">';
    if (!items.length) {
      html += '<div class="mkt-meta">货架是空的。群里丢 .dkpkg 现在就能装，不必等合并。';
      html += "</div>";
    }
    var installed = {};
    (snap.installed || []).forEach(function (id) { installed[id] = true; });
    var mine = snap.ratings || {};
    items.forEach(function (it) {
      var have = !!installed[it.id];
      var btn = have
        ? '<span class="mkt-hold">已装</span>'
        : '<button class="plugin-try-btn" type="button" data-install="' + esc(it.id) + '">安装</button>';
      html += card(it, btn, rateRow(it, have, mine[it.id]));
    });
    html += "</div></div>";
    html += '<div class="plugin-cat"><div class="plugin-cat-head"><span class="cat-label">可以上架</span><span class="cat-count">' + share.length + "</span></div>";
    html += '<div class="plugin-list">';
    if (!share.length) {
      html += '<div class="mkt-meta">现在没有。做个皮肤、工坊应用或 MOD，就会出现在这里。</div>';
    }
    share.forEach(function (it) {
      var why = WHY[it.reason] || "";
      var btn = (it.kind === "playbook")
        ? '<span class="mkt-hold">操作手册下一刀再导出</span>'
        : '<button class="plugin-try-btn" type="button" data-kind="' + esc(it.kind) +
          '" data-id="' + esc(it.id) + '" data-name="' + esc(it.name) +
          '" data-desc="' + esc(it.description || it.name || "") + '">上架到货架</button>';
      html += card({
        name: it.name, id: it.id, kind: it.kind, author: it.author,
        version: it.version, description: why + (it.shelf_version ? "（货架 " + it.shelf_version + "）" : "")
      }, btn);
    });
    html += "</div></div>";
    el.innerHTML = html;
    injectTabs("market", true);
    el.querySelectorAll("[data-install]").forEach(function (b) {
      b.addEventListener("click", function () { doInstall(b.getAttribute("data-install")); });
    });
    el.querySelectorAll("[data-kind][data-id]").forEach(function (b) {
      b.addEventListener("click", function () {
        doShare(b.getAttribute("data-kind"), b.getAttribute("data-id"), b.getAttribute("data-name"), b.getAttribute("data-desc"));
      });
    });
    el.querySelectorAll(".mkt-star[data-id][data-score]").forEach(function (b) {
      b.addEventListener("click", function () {
        doRate(b.getAttribute("data-id"), Number(b.getAttribute("data-score")));
      });
    });
    if (snap.is_owner) loadInbox();
  }

  function inboxCard(it) {
    var extra = verdictTag(it.verdict);
    if (it.url) {
      extra += '<a class="mkt-pr" href="' + esc(it.url) + '" target="_blank" rel="noopener">打开申请</a>';
    }
    if (it.verdict === "pass") {
      extra += '<button class="plugin-try-btn" type="button" data-inbox="merge" data-n="' + esc(it.number) + '">合并</button>';
    } else if (it.verdict === "reject") {
      extra += '<button class="plugin-try-btn" type="button" data-inbox="close" data-n="' + esc(it.number) + '">关掉</button>';
    } else {
      extra += '<button class="plugin-try-btn" type="button" data-inbox="merge" data-n="' + esc(it.number) + '">仍要合并</button>';
      extra += '<button class="plugin-try-btn" type="button" data-inbox="close" data-n="' + esc(it.number) + '">关掉</button>';
    }
    return card({
      name: "#" + it.number + " " + (it.title || ""),
      id: String(it.number),
      kind: (it.meta && it.meta.kind) || "app",
      author: it.author,
      version: (it.meta && it.meta.version) || "",
      description: it.report || ""
    }, extra);
  }

  function renderInbox(box) {
    var host = document.getElementById("mktInbox");
    if (!host) return;
    var items = box.items || [];
    var c = box.counts || {};
    var html = '<div class="plugin-cat-head"><span class="cat-label">待审</span>' +
      '<span class="cat-count">' + items.length + "</span></div>";
    html += '<div class="mkt-inbox-bar">';
    html += '<span class="mkt-meta">绿 ' + (c.pass || 0) + " · 黄 " + (c.review || 0) + " · 红 " + (c.reject || 0) + "</span>";
    if (c.pass) html += '<button class="plugin-try-btn" type="button" data-inbox="merge_green">合全部绿灯</button>';
    if (c.reject) html += '<button class="plugin-try-btn" type="button" data-inbox="sweep_red">清掉红灯</button>';
    html += "</div><div class=\"plugin-list\">";
    if (!box.ok) {
      html += '<div class="mkt-meta">' + esc(box.error || "待审读不到") + "</div>";
    } else if (!items.length) {
      html += '<div class="mkt-meta">没有待审的合并申请。你不用去 Gitee 翻。</div>';
    } else {
      items.forEach(function (it) { html += inboxCard(it); });
    }
    html += "</div>";
    host.innerHTML = html;
    host.querySelectorAll("[data-inbox]").forEach(function (b) {
      b.addEventListener("click", function () {
        doInbox(b.getAttribute("data-inbox"), Number(b.getAttribute("data-n") || 0));
      });
    });
  }

  function loadInbox() {
    fetch("/market/inbox", { headers: auth() })
      .then(function (r) { return r.json(); })
      .then(renderInbox)
      .catch(function (e) {
        renderInbox({ ok: false, error: String(e.message || e), items: [], counts: {} });
      });
  }

  function doInstall(id) {
    fetch("/market/install", {
      method: "POST",
      headers: Object.assign({ "Content-Type": "application/json" }, auth()),
      body: JSON.stringify({ id: id })
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (x) {
        toast(x.ok ? (x.j.output || "已安装") : (x.j.detail || "安装失败"));
        if (typeof loadDashboard === "function") loadDashboard("plugins");
      }).catch(function (e) { toast(String(e.message || e)); });
  }

  function doRate(id, n) {
    fetch("/market/rate", {
      method: "POST",
      headers: Object.assign({ "Content-Type": "application/json" }, auth()),
      body: JSON.stringify({ id: id, score: n })
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (x) {
        toast(x.ok ? (x.j.output || "已记下") : (x.j.detail || "打分失败"));
        if (x.ok && typeof loadDashboard === "function") loadDashboard("plugins");
      }).catch(function (e) { toast(String(e.message || e)); });
  }

  function doShare(kind, id, name, desc) {
    fetch("/market/share", {
      method: "POST",
      headers: Object.assign({ "Content-Type": "application/json" }, auth()),
      body: JSON.stringify({ kind: kind, name: id || name, author: "", description: desc || name || "" })
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (x) {
        toast(x.ok ? (x.j.output || "已提交") : (x.j.detail || "上架失败"));
        if (x.ok && typeof loadDashboard === "function") loadDashboard("plugins");
      }).catch(function (e) { toast(String(e.message || e)); });
  }

  function doInbox(action, number) {
    fetch("/market/inbox", {
      method: "POST",
      headers: Object.assign({ "Content-Type": "application/json" }, auth()),
      body: JSON.stringify({ action: action, number: number || 0 })
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (x) {
        toast(x.ok ? (x.j.output || "已处理") : (x.j.detail || "待审失败"));
        if (x.ok) loadInbox();
      }).catch(function (e) { toast(String(e.message || e)); });
  }

  function pageRows() {
    var d = (window.Daemonkey && Daemonkey._domains) || {};
    return Object.keys(d).map(function (k) {
      var m = d[k] || {};
      return { id: k, label: m.label || k, section: m.section || "" };
    });
  }

  function paintPluginAlert(n) {
    n = Number(n) || 0;
    var item = document.querySelector('.nav-item[data-view="plugins"]');
    var badge = document.getElementById("navBadge_plugins");
    if (item) item.classList.toggle("overlay-alert", n > 0);
    if (!badge) return;
    if (n > 0) {
      badge.textContent = String(n);
      badge.className = "badge overlay-alert";
      badge.title = n + " 个改装要看一眼 · 插件库「我的改装」";
      badge.style.display = "";
    } else if (badge.classList.contains("overlay-alert")) {
      badge.textContent = "·";
      badge.className = "badge";
      badge.title = "";
      badge.style.display = "none";
    }
  }

  function fetchPluginAlert() {
    fetch("/api/overlays/health", { headers: auth() })
      .then(function (r) { return r.ok ? r.json() : { alert: 0 }; })
      .then(function (d) { paintPluginAlert(d.alert || 0); })
      .catch(function () {});
  }

  function wrapBadges() {
    var orig = window.refreshNavBadges;
    if (typeof orig !== "function" || orig._dkOverlay) return;
    window.refreshNavBadges = function () {
      var ret = orig.apply(this, arguments);
      if (ret && typeof ret.then === "function") {
        return ret.then(function (v) { fetchPluginAlert(); return v; });
      }
      fetchPluginAlert();
      return ret;
    };
    window.refreshNavBadges._dkOverlay = true;
  }

  function ovCard(name, kind, extra, meta, bad) {
    return '<div class="mkt-card' + (bad ? " overlay-bad" : "") + '">' +
      '<div class="mkt-card-top">' +
      '<span class="mkt-name">' + esc(name) + "</span>" +
      '<span class="mkt-kind">' + esc(kind) + "</span>" + extra + "</div>" +
      (meta ? '<div class="mkt-meta">' + meta + "</div>" : "") + "</div>";
  }

  function renderOverlays(data) {
    var el = dash();
    if (!el) return;
    var health = data.health || {};
    var mods = data.mods || [];
    var tools = data.user_tools || [];
    var skins = data.skins || [];
    var dec = data.decorate || {};
    var pages = pageRows();
    var alert = Number(health.alert || 0);
    var html = '<div class="dash-head"><h2><i class="ri-stack-line"></i> 我的改装</h2>' +
      '<span class="meta">' + (health.checked_at ? ("自检 " + esc(health.checked_at)) : "还没自检") +
      (alert ? (" · " + alert + " 个要看") : " · 没有红的") + "</span>" +
      '<button type="button" onclick="loadDashboard(\'plugins\')">刷新</button></div>';
    html += '<div class="plugin-intro">这里放 MOD：自己写的，以及别人分享装进来的。' +
      "官方升级不碰。红的只表示语法套不上。停用回官方；工具/路由要重启 daemon。</div>";

    html += '<div class="plugin-cat"><div class="plugin-cat-head"><span class="cat-label">MOD</span>' +
      '<span class="cat-count">' + mods.length + "</span></div><div class=\"plugin-list\">";
    if (!mods.length) {
      html += '<div class="mkt-meta">还没有。对话说「把工具魔改收成 MOD」，或写在 data/mods/。</div>';
    }
    mods.forEach(function (m) {
      var bad = m.enabled && !m.ok;
      var extra = '<button class="plugin-try-btn" type="button" data-mod="' +
        esc(m.id) + '" data-on="' + (m.enabled ? "0" : "1") + '">' +
        (m.enabled ? "停用" : "启用") + "</button>";
      var meta = "v" + esc(m.version || "?") + (m.has_ui ? " · 有前端页" : "");
      if (m.problems && m.problems.length) meta += "<br>" + esc(m.problems.join(" · "));
      if (m.hint) meta += "<br>" + esc(m.hint);
      html += ovCard(m.name || m.id, m.enabled ? "开" : "关", extra, meta, bad);
    });
    html += "</div></div>";

    html += '<div class="plugin-cat"><div class="plugin-cat-head"><span class="cat-label">本机工具</span>' +
      '<span class="cat-count">' + tools.length + "</span></div><div class=\"plugin-list\">";
    if (!tools.length) {
      html += '<div class="mkt-meta">agent_tools_user/ 是空的。只给自己用的工具放这里。</div>';
    }
    tools.forEach(function (t) {
      var meta = (t.problems && t.problems.length) ? esc(t.problems.join(" · ")) : "语法正常";
      if (t.hint) meta += "<br>" + esc(t.hint);
      html += ovCard(t.file, t.ok ? "本机" : "坏", '<span class="mkt-hold">修好或挪走</span>', meta, !t.ok);
    });
    html += "</div></div>";

    html += '<div class="plugin-cat"><div class="plugin-cat-head"><span class="cat-label">皮肤</span>' +
      '<span class="cat-count">' + skins.length + "</span></div><div class=\"plugin-list\">";
    if (!skins.length) {
      html += '<div class="mkt-meta">还没有自制皮肤。换肤仍走右上角调色板。</div>';
    }
    skins.forEach(function (s) {
      html += ovCard(s.name || s.id, "皮肤", '<span class="mkt-hold">右上角换肤</span>',
        "v" + esc(s.version || "?") + (s.hint ? "<br>" + esc(s.hint) : ""), false);
    });
    html += "</div></div>";

    html += '<div class="plugin-cat"><div class="plugin-cat-head"><span class="cat-label">装修页</span>' +
      '<span class="cat-count">' + pages.length + "</span></div><div class=\"plugin-list\">";
    if (!pages.length) {
      html += '<div class="mkt-meta">没有自定义侧栏页就不占位。要加抄 EXAMPLES.js，或直接说。</div>';
    }
    pages.forEach(function (p) {
      html += ovCard(p.label || p.id, "侧栏页",
        '<button class="plugin-try-btn" type="button" data-view="' + esc(p.id) + '">打开</button>',
        (p.section ? ("分组 " + esc(p.section) + " · ") : "") + esc(p.id), false);
    });
    if (dec.user_js && pages.length) {
      html += ovCard("装修区 user.js", "装修", '<span class="mkt-hold">' +
        (dec.user_js_bytes || 0) + " 字节</span>", esc(dec.hint || ""), false);
    }
    html += "</div></div>";

    el.innerHTML = html;
    injectTabs("overlays", true);
    el.querySelectorAll("[data-mod]").forEach(function (b) {
      b.addEventListener("click", function () {
        doToggleMod(b.getAttribute("data-mod"), b.getAttribute("data-on") === "1");
      });
    });
    el.querySelectorAll("[data-view]").forEach(function (b) {
      b.addEventListener("click", function () {
        var v = b.getAttribute("data-view");
        if (typeof switchView === "function") switchView(v);
      });
    });
  }

  function showOverlays() {
    var el = dash();
    if (el) el.innerHTML = '<div class="dash-empty">正在看叠层…</div>';
    fetch("/api/overlays?refresh=1", { headers: auth() })
      .then(function (r) {
        if (!r.ok) throw new Error("叠层加载失败 " + r.status);
        return r.json();
      })
      .then(function (data) {
        renderOverlays(data);
        paintPluginAlert((data.health && data.health.alert) || 0);
      })
      .catch(function (e) {
        if (!dash()) return;
        dash().innerHTML = '<div class="dash-head"><h2>我的改装</h2></div><div class="dash-empty">' +
          esc(e.message) + " · 新路由要重启 daemon</div>";
        injectTabs("overlays", true);
      });
  }

  function doToggleMod(id, on) {
    fetch("/api/mods/" + encodeURIComponent(id) + "/enabled", {
      method: "POST",
      headers: Object.assign({ "Content-Type": "application/json" }, auth()),
      body: JSON.stringify({ enabled: !!on })
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (x) {
        toast(x.ok ? (x.j.output || "已记下") : (x.j.detail || "开关失败"));
        if (typeof loadDashboard === "function") loadDashboard("plugins");
      }).catch(function (e) { toast(String(e.message || e)); });
  }

  function showMarket() {
    var el = dash();
    if (el) el.innerHTML = '<div class="dash-empty">正在拉货架…</div>';
    fetch("/market", { headers: auth() })
      .then(function (r) {
        if (!r.ok) throw new Error("货架加载失败 " + r.status);
        return r.json();
      })
      .then(renderMarket)
      .catch(function (e) {
        if (!dash()) return;
        dash().innerHTML = '<div class="dash-head"><h2>扩展市场</h2></div><div class="dash-empty">' +
          esc(e.message) + " · 新路由要重启 daemon</div>";
        injectTabs("market", true);
      });
  }

  function renderPluginsFallback() {
    var el = dash();
    if (!el) return;
    el.innerHTML = '<div class="dash-head"><h2><i class="ri-puzzle-fill"></i> 插件库</h2>' +
      '<span class="meta">完整清单在工作台左侧「插件库」</span></div>' +
      '<div class="plugin-intro">房间这扇门主要走扩展市场。要看本机已装工具，去工作台。</div>';
    injectTabs("plugins", true);
  }

  function wrap() {
    var orig = window.renderPlugins;
    if (orig && orig._dkMarket) return;
    function hub(data) {
      _data = data;
      if (tab() === "market") { showMarket(); return; }
      if (tab() === "overlays") { showOverlays(); return; }
      if (typeof orig === "function" && !orig._dkMarket) {
        orig(data);
        injectTabs("plugins", true);
        return;
      }
      renderPluginsFallback();
    }
    hub._dkMarket = true;
    window.renderPlugins = hub;
  }

  wrap();
  wrapBadges();
  fetchPluginAlert();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      wrap();
      wrapBadges();
      fetchPluginAlert();
    });
  }
})();
