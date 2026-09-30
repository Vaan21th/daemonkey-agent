/* 工作台画布：产出铺中栏，看完关掉。计划书 / 文稿 / PPT / 表 / HTML / 视频。 */

let _stageView = "";
window._stageMode = null;

function stagePane() {
  if (typeof $dashView !== "undefined" && $dashView) return $dashView;
  return document.getElementById("detailPane") || document.getElementById("dashView");
}

function stageIsVisible() {
  const pane = stagePane();
  if (!pane) return false;
  const box = pane.getBoundingClientRect();
  return box.width >= 80 && box.height >= 80;
}

function stageEnsureWorkbench() {
  // 2026-09-15 · 专注版下不再退出 compact (BRO: 看一份稿就要丢专注版布局 · 回回跳)。
  //   22:57 定案: 画布复用「产物库面板」这套壳 (BRO: 复用产物库那套 · 别写两套) ——
  //   把面板撑开 + #detailPane 挪进 .cl-slot · 与「查看 & 批注」同一条链。
  //   曾走「第 6 列真分栏」: 竖条被挤到画布左边 · 点开关就崩 (BRO 图1/图2) · 已撤。
  if (document.body.classList.contains("compact")) {
    document.body.classList.add("dk-stage-drawer");
    if (typeof toggleCompactLibrary === "function") {
      // BRO 2026-09-15 22:52: 自动弹出时先闪一下 BI 看板 —— 挪槽前先垫「打开中…」，
      //   槽里立刻是加载态，画布渲染完再替换（与「查看 & 批注」同款 · doc-shelf _docOpenForAnnotate）。
      const _pane = document.getElementById("detailPane");
      if (_pane && !_pane.querySelector(".stage-root")) {
        _pane.innerHTML = '<div class="dash-empty dk-ld dk-ld-sm"><div class="dk-ld-mark"><img src="/static/img/logo-mark.png" alt=""><i></i><i></i></div><div class="dk-ld-txt">打开中…</div></div>';
      }
      toggleCompactLibrary(true, { skipDomain: true });
      // 面板壳要两层: .open(展开) + .ca-lib-open(槽视图) —— toggleCompactLibrary 只管后者，
      // 少一层 .open 面板宽度不到位 → 槽里画布 0 宽（实测 stageRect width=0）。
      const _wrap = document.getElementById("compactArtifacts");
      if (_wrap && !_wrap.classList.contains("open") && typeof toggleCompactArtifacts === "function") {
        toggleCompactArtifacts();
      }
    }
    if (typeof _syncCompactStageDrawer === "function") _syncCompactStageDrawer();
    return;
  }
}

function stageToken() {
  return (typeof token !== "undefined" && token) ? String(token) : "";
}

function stageWithAuth(url) {
  if (!url) return url;
  const t = encodeURIComponent(stageToken());
  if (!t) return url;
  return url + (url.includes("?") ? "&" : "?") + "token=" + t;
}

function stageRel(path) {
  return String(path || "").trim().replace(/\\/g, "/").replace(/^\/+/, "");
}

function stageName(path) {
  const p = stageRel(path);
  return p.split("/").pop() || p;
}

function stageExt(path) {
  const n = stageName(path);
  const m = n.match(/\.([a-z0-9]+)$/i);
  return m ? m[1].toLowerCase() : "";
}

function stageFileUrl(path) {
  const p = stageRel(path);
  if (p.startsWith("data/workshop/outputs/")) {
    return "/workshop/outputs/" + p.slice("data/workshop/outputs/".length);
  }
  if (p.startsWith("data/presentations/")) {
    return "/presentations/" + p.slice("data/presentations/".length);
  }
  if (p.startsWith("data/spreadsheets/")) {
    return "/spreadsheets/" + p.slice("data/spreadsheets/".length);
  }
  if (p.startsWith("data/reports/")) {
    return "/reports/" + p.slice("data/reports/".length);
  }
  if (/^data\/(design|docs|dev|content)\//.test(p)) {
    return "/stage/file/" + p;
  }
  if (p.startsWith("workshop/outputs/")) return "/" + p;
  if (p.startsWith("/")) return p;
  return "";
}

function stageMdApi(path) {
  const p = stageRel(path);
  const wm = p.match(/^data\/(docs|content|design|dev|reports)\/([^/]+\.md)$/i);
  if (wm) {
    return { type: "json", url: "/workshop/preview/" + wm[1] + "/" + encodeURIComponent(wm[2]), field: "markdown" };
  }
  if (p.startsWith("data/workshop/outputs/") && /\.(md|txt)$/i.test(p)) {
    return { type: "text", url: "/workshop/outputs/" + p.slice("data/workshop/outputs/".length) };
  }
  const pb = p.match(/^data\/playbooks\/([^/]+)\.md$/i);
  if (pb) {
    return { type: "json", url: "/dashboard/playbooks/doc?id=" + encodeURIComponent(pb[1]), field: "content" };
  }
  return null;
}

function stageTag(mode, kind) {
  if (mode === "plan") return "PLAN";
  if (mode === "md") return "文稿";
  if (mode === "office") {
    if (kind === "decks") return "PPT";
    if (kind === "sheets") return "表";
    return "稿";
  }
  if (mode === "html") return "HTML";
  if (mode === "video") return "视频";
  if (mode === "pdf") return "PDF";
  if (mode === "image") return "图";
  return "画布";
}

function stageClassify(path) {
  const p = stageRel(path);
  if (!p) return null;
  const name = stageName(p);
  const ext = stageExt(p);
  if (ext === "pptx" || ext === "ppt") return { mode: "office", kind: "decks", name, path: p };
  if (ext === "xlsx" || ext === "xls") return { mode: "office", kind: "sheets", name, path: p };
  if (ext === "docx" || ext === "doc") return { mode: "office", kind: "reports", name, path: p };
  if (ext === "mp4" || ext === "webm" || ext === "mov") {
    return { mode: "video", name, path: p, url: stageFileUrl(p) };
  }
  if (ext === "html" || ext === "htm") return { mode: "html", name, path: p, url: stageFileUrl(p) };
  if (ext === "pdf") return { mode: "pdf", name, path: p, url: stageFileUrl(p) };
  if (["png", "jpg", "jpeg", "gif", "webp"].includes(ext)) {
    return { mode: "image", name, path: p, url: stageFileUrl(p) };
  }
  if ((ext === "md" || ext === "txt") && stageMdApi(p)) return { mode: "md", name, path: p };
  return null;
}

function stageCanOpen(path) {
  return !!stageClassify(path);
}

function stageMarkOpen(on) {
  if (typeof _shelfPreviewOpen !== "undefined") {
    try { _shelfPreviewOpen = !!on; } catch (e) { /* noop */ }
  }
  window._shelfPreviewOpen = !!on;
  // 不能叫 stage-open：按钮也用这个 class，套到 body 会变成 32px 方块，整栏工作台被收没
  document.body.classList.remove("stage-open");
  // on=false 必须摘掉 —— 原实现无条件 add · 关画布后 body 一直挂着画布态 · 中栏按抽屉浮着 = "关不掉" (BRO 2026-09-15)
  document.body.classList.toggle("dk-stage-open", !!on);
  if (typeof _syncCompactStageDrawer === "function") _syncCompactStageDrawer();
}

function stageRemember() {
  if (!window._stageMode) {
    // 优先用「中栏实际在放的域」(loadDashboard 记的) · currentView 只在走导航时更新 ·
    // 专注版产物库是直调 loadDashboard · 不经过导航 → 只看 currentView 会误判成 bi (BRO 2026-09-15)
    _stageView = window._stageHomeHint
      || window._dashDomain
      || ((typeof currentView !== "undefined" && currentView) ? currentView : "");
    window._stageHomeHint = "";
  }
}

function stageClose() {
  stageWatchStop();
  if (typeof window.stageNotesReset === "function") window.stageNotesReset();
  window._stageMode = null;
  stageMarkOpen(false);
  if (typeof _syncCompactStageDrawer === "function") _syncCompactStageDrawer();
  if (typeof window._syncPlanToggle === "function") window._syncPlanToggle();
  // 关画布一律回「产物库」(BRO 2026-09-16) · 不再按「打开前的域」回 ——
  //   实测: 中栏停在 BI 看板时开画布 · 点 X 会被弹回 BI 看板
  _stageView = "";
  if (typeof loadDashboard === "function") loadDashboard("reports");
  else if (typeof renderDetailWelcome === "function") renderDetailWelcome();
}

// 静默清画布态 (不 loadDashboard · 不切域) —— 收起面板/收右栏槽时带着画布一起收
//   BRO 2026-09-15: 收起后画布被 #detailPane 挪回中栏 = "关不掉" · 收的语义要含产物
function stageClearQuiet() {
  if (!window._stageMode && !document.body.classList.contains("dk-stage-open")) return;
  stageWatchStop();
  window._stageMode = null;
  if (typeof window.stageNotesReset === "function") window.stageNotesReset();
  stageMarkOpen(false);
  if (typeof window._syncPlanToggle === "function") window._syncPlanToggle();
  // 内容也别留 —— 否则退出专注版 / 切回工作台时 · 中栏会露出残留画布 = "收起没把产物收起来" (BRO 2026-09-15)
  const pane = stagePane();
  if (pane && pane.querySelector(":scope > .stage-root")) {
    if (typeof renderDetailWelcome === "function") renderDetailWelcome();
    else pane.innerHTML = "";
  }
}

function stageEsc(s) {
  return (typeof escHtml === "function") ? escHtml(s) : String(s || "");
}

// ── ⭐ 画布收藏 (wish-e6620e35) ──
// 复用 doc-shelf.js 那套（wish-e16b1f52）：数据层就是那份 favorites.json (kind=output)，
//   ref_id 跟产物库 open_path 同源 —— 画布里点星 = 产物库点星，同一条收藏，不会变两条。
//   BRO 原话：「最好不要分叉，直接看能不能复用前面的代码」
function stageFavRel(path) {
  const p = String(path || "");
  if (!p) return "";
  if (p.startsWith("data/")) return p.split("?")[0];
  if (typeof _docRelFromUrl === "function") return _docRelFromUrl(p, "", "") || "";
  return "";
}

function stageFavPaint(btn, on) {
  if (!btn) return;
  btn.classList.toggle("on", !!on);
  btn.innerHTML = `<i class="ri-star-${on ? "fill" : "line"}"></i>`;
  btn.title = on
    ? "已收藏 · 再点取消（收藏夹里按分类找得到）"
    : "收藏这份 · 之后能在「收藏夹 → 我的产物」里按分类找回来";
}

function stageFavBind(btn, spec) {
  const rel = stageFavRel(spec.path);
  // 归不出工程内相对路径 → 不给星（照 _docCardHtml 的做法 · 不假装能收）
  if (!rel || typeof _loadDocFavSet !== "function" || typeof _docToggleFav !== "function") {
    btn.remove();
    return;
  }
  btn.dataset.rel = rel;
  let painted = false;
  const show = (set) => {
    painted = true;
    if (btn.isConnected) stageFavPaint(btn, !!(set && set.has(rel)));
  };
  _loadDocFavSet().then(show).catch(() => {});
  // 已缓存时上面是同步进微任务的 · 不闪；未缓存则等网络回来再纠正一次
  setTimeout(() => { if (!painted && btn.isConnected) stageFavPaint(btn, false); }, 0);
  btn.onclick = () => _docToggleFav(rel, spec.name || rel, btn);
}

function stagePaint(pane, spec, inner, paper) {
  stageRemember();
  window._stageMode = spec.mode;
  stageMarkOpen(true);
  // wish-6350cced · 装配台 ≠ 产物预览（BRO：不能和产物预览混在一起 · 要独立）——
  //   换自己的身份（tag=装配台 · title=工具装配台）· 藏掉文件向按钮（用软件打开 / 收藏）·
  //   不挂画布批注（那是给稿子划字的）· 只留「保存预设」+ 关闭。
  const _isAsm = /前缀全貌（实时）\.html$/.test(spec.path || "");
  const tag = _isAsm ? "装配台" : (spec.tag || stageTag(spec.mode, spec.kind));
  pane.innerHTML = `
    <div class="stage-root${paper ? " is-paper" : ""}">
      <div class="stage-bar">
        <span class="stage-tag">${stageEsc(tag)}</span>
        <h2 class="stage-title">${stageEsc(_isAsm ? "工具装配台" : (spec.name || "画布"))}</h2>
        ${_isAsm ? `<span class="stage-asm-stats" id="stageAsmStats" title="装配台实时账"></span>` : ""}
        ${spec.meta ? `<span class="stage-meta">${stageEsc(spec.meta)}</span>` : ""}
        ${(spec.path && !_isAsm) ? `<button type="button" class="stage-open" id="stageRevealBtn" title="用软件打开"><i class="ri-external-link-line"></i></button>` : ""}
        ${(spec.path && !_isAsm) ? `<button type="button" class="stage-open" id="stageFavBtn" title="收藏这份"><i class="ri-star-line"></i></button>` : ""}
        ${_isAsm ? `<button type="button" class="stage-asm-save" id="stageAsmSave2" title="把当前勾选保存到所选的档 / 预设（BRO 2026-09-21：从底部挪来）"><i class="ri-save-3-line"></i>保存</button>` : ""}
        ${_isAsm ? `<button type="button" class="stage-asm-save stage-asm-reset" id="stageAsmReset" title="还原到出厂 / 初始"><i class="ri-arrow-go-back-line"></i>还原</button>` : ""}
        ${_isAsm ? `<button type="button" class="stage-asm-save" id="stageAsmSave" title="保存为预设…（存完新对话的选档卡里就能选它）"><i class="ri-bookmark-3-line"></i>保存预设</button>` : ""}
        <button type="button" class="stage-x" id="stageCloseBtn" title="关掉画布"><i class="ri-close-line"></i></button>
      </div>
      <div class="stage-body${paper ? " stage-paper" : ""}" id="stageBody">${inner || ""}</div>
    </div>`;
  const x = pane.querySelector("#stageCloseBtn");
  if (x) x.onclick = stageClose;
  // wish-6350cced · 装配台专属标题栏（BRO：保存这些放到标题栏位置）
  //   BRO 2026-09-21：底部「保存修改 / 回到初始」也挪上来 → 三按钮统一走 asmFire 直连 iframe（同源）
  const asmFire = (fnName) => {
    const tryFire = () => {
      const fr = pane.querySelector("iframe.stage-frame");
      try {
        if (fr && fr.contentWindow && typeof fr.contentWindow[fnName] === "function") { fr.contentWindow[fnName](); return true; }
      } catch (e) { /* 还没就绪 */ }
      return false;
    };
    // BRO 实测：刚铺开就点 → iframe 还差一拍（lazy）→ 等 600ms 再试一次
    if (tryFire()) return;
    setTimeout(() => { if (!tryFire()) alert("装配台还没加载好，稍等一秒再点"); }, 600);
  };
  const asmSave2 = pane.querySelector("#stageAsmSave2");
  if (asmSave2) asmSave2.onclick = () => asmFire("pedSave");
  const asmReset = pane.querySelector("#stageAsmReset");
  if (asmReset) asmReset.onclick = () => asmFire("pedReset");
  const asmSave = pane.querySelector("#stageAsmSave");
  if (asmSave) asmSave.onclick = () => asmFire("svOpen");
  const reveal = pane.querySelector("#stageRevealBtn");
  if (reveal && spec.path && typeof revealFile === "function") {
    reveal.onclick = () => revealFile(spec.path, reveal);
  }
  const favBtn = pane.querySelector("#stageFavBtn");
  if (favBtn && spec.path) stageFavBind(favBtn, spec);
  if (typeof window._syncPlanToggle === "function") window._syncPlanToggle();
  if (!_isAsm && typeof window.stageNotesBind === "function") window.stageNotesBind(spec);
}

function stageOpenMd(pane, spec) {
  const api = stageMdApi(spec.path);
  if (!api) return false;
  stagePaint(pane, spec, '<div class="stage-wait">打开文稿…</div>', true);
  const hdr = { headers: { Authorization: "Bearer " + stageToken() } };
  fetch(stageWithAuth(api.url), hdr).then(async (r) => {
    if (window._stageMode !== "md") return;
    const body = pane.querySelector("#stageBody");
    if (!body) return;
    if (!r.ok) { body.innerHTML = '<div class="stage-wait">打不开这份文稿</div>'; return; }
    let text = "";
    if (api.type === "json") {
      const j = await r.json();
      text = (j && j[api.field]) || "";
    } else {
      text = await r.text();
    }
    const html = (typeof mdRender === "function")
      ? mdRender(text)
      : ("<pre>" + stageEsc(text) + "</pre>");
    body.innerHTML = '<article class="stage-doc rp-md">' + html + "</article>";
    if (typeof window.stageNotesBind === "function") window.stageNotesBind(spec);
  }).catch(() => {
    const body = pane.querySelector("#stageBody");
    if (body && window._stageMode === "md") {
      body.innerHTML = '<div class="stage-wait">打不开这份文稿</div>';
    }
  });
  return true;
}

function openStage(input) {
  if (input && input.mode === "plan") {
    return typeof window.openPlanOnStage === "function" && window.openPlanOnStage(!!input.refresh);
  }
  const refresh = !!(input && (input.refresh || input.silent));
  // 2026-09-15 · 专注版下 auto 打开不再拒 (BRO: 产物栏在需要时自己弹 · 与工作台同一出口) ·
  //   改成先把抽屉挂好 — stageEnsureWorkbench() 在 compact 下挂 body.dk-stage-drawer · 中栏从右侧浮出。
  if (document.body.classList.contains("compact")) stageEnsureWorkbench();
  if (!refresh) {
    stageEnsureWorkbench();
    if (!stageIsVisible() && !(input && input._waited)) {
      let n = 0;
      const again = Object.assign({}, input, { _waited: true });
      const tick = function () {
        if (stageIsVisible() || ++n > 16) openStage(again);
        else requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
      return true;
    }
  }
  const path = (input && (input.path || input.url)) || "";
  const spec = stageClassify(path);
  const pane = stagePane();
  if (!spec || !pane) return false;
  const histFile = /^_hist_/i.test(spec.name || "") || /(?:^|\/)_hist_/i.test(spec.path || "");
  // BRO 2026-09-20:「所有的产物点开都只需要在中栏显示就行了」
  //   → 去掉「打开 office 文档就自动跳到它归属的那场对话」。goOfficeHome 会切会话,
  //     看着就像「点产物把对话切走了」。要跳对话请用分组头的「进入话题」。
  //   (老逻辑: goOfficeHome(spec.path).then(… _homed:true …); return true;)
  if (spec.mode === "office") {
    // 2026-09-29 · 只有明确「要改它」才挂进对话 (input.bind === true)。
    //   原来这里无条件调 bindWorkingDoc —— 后果：在产物库点「预览」看一眼，
    //   这份稿就被挂进当前对话（via='manual'）。BRO 2026-09-29 原话：
    //   「当我点开这个历史的预览时候，他就会被挂载到对话窗口！」
    //   他查了好几轮，一直以为是自己误触 —— 实际是这个默认值。
    //   合法挂载入口（显式传 bind:true）：[data-annotate](查看&批注) /
    //   [data-revise](让我改) / 点对话里的附件。
    if (input && input.bind === true && typeof window.bindWorkingDoc === "function") {
      window.bindWorkingDoc(spec.path);
    }
    stageRemember();
    window._stageMode = "office";
    stageMarkOpen(true);
    window._dashLoadSeq = (window._dashLoadSeq || 0) + 1;
    if (typeof loadReportPreview === "function" && spec.kind === "reports") {
      loadReportPreview(spec.name, `/reports/preview/${encodeURIComponent(spec.name)}`);
      return true;
    }
    if (typeof renderShelfPreview === "function") {
      renderShelfPreview({
        name: spec.name, kind: spec.kind, open_path: spec.path,
        has_md_source: false, markdown: "", download_url: stageFileUrl(spec.path),
      });
      return true;
    }
    return false;
  }
  if (spec.mode === "md") return stageOpenMd(pane, spec);
  if (!spec.url) return false;
  const authUrl = stageWithAuth(spec.url);
  const src = stageEsc(authUrl);
  const embed = {
    video: `<video class="stage-media" controls preload="metadata" src="${src}"></video>`,
    html: `<iframe class="stage-frame" title="HTML" src="${src}" sandbox="allow-same-origin allow-scripts allow-popups" loading="lazy"></iframe>`,
    pdf: `<iframe class="stage-frame" title="PDF" src="${src}"></iframe>`,
    image: `<img class="stage-img" alt="" src="${src}">`,
  };
  if (!embed[spec.mode]) return false;
  stagePaint(pane, spec, embed[spec.mode]);
  if (spec.mode === "html" || spec.mode === "pdf") stageWatchStart(authUrl);
  const fr = pane.querySelector("iframe.stage-frame");
  if (fr && typeof window.styleOfficePreviewFrame === "function") {
    window.styleOfficePreviewFrame(fr);
  }
  return true;
}

// ===== 画布自动刷新 (BRO 2026-09-16) =====
//   病根: 画布 iframe 只在打开那一刻取一次内容 · 盘上文件被改 (原型/canvas 迭代中) 画布不跟 → 看到旧版
//   做法: 打开 html/pdf 后每 3s GET 问一次 (no-cache) · 内容变了就换 src 重载 (带原 token)
//   注: /stage/file 不支持 HEAD (405) → 用 GET + 全文比对 · 本地 ~16KB 无感 (BRO 2026-09-16)
let _stageWatchTimer = null;
let _stageWatchUrl = "";
let _stageWatchStamp = "";

function stageWatchStop() {
  if (_stageWatchTimer) { clearInterval(_stageWatchTimer); _stageWatchTimer = null; }
  _stageWatchUrl = "";
  _stageWatchStamp = "";
}

function stageWatchStart(url) {
  stageWatchStop();
  if (!url) return;
  _stageWatchUrl = url;
  window._stageWatchTicks = 0;
  window._stageWatchReloads = 0;
  // 基线 = 打开这一刻盘上的内容 · 立刻取一次 (不等第一个 3s tick) ——
  //   否则「打开画布后 3s 内改了文件」会被当成基线 · 之后永远判「没变」· 画布再不刷新
  //   (BRO 2026-09-16 实测: ticks=3 / reloads=0 / iframe 仍是旧内容)
  fetch(url, { cache: "no-store" }).then(function (r) { return r.ok ? r.text() : null; }).then(function (t) {
    if (typeof t === "string" && !_stageWatchStamp) _stageWatchStamp = t;
  }).catch(function () {});
  _stageWatchTimer = setInterval(function () {
    if (!_stageWatchUrl || !window._stageMode) return;
    window._stageWatchTicks = (window._stageWatchTicks || 0) + 1;
    fetch(_stageWatchUrl, { cache: "no-store" }).then(function (r) {
      if (!r.ok) return null;
      return r.text();
    }).then(function (t) {
      if (typeof t !== "string") return;
      if (!_stageWatchStamp) { _stageWatchStamp = t; return; }
      if (t === _stageWatchStamp) return;
      _stageWatchStamp = t;
      const fr = document.querySelector(".stage-frame");
      if (!fr) return;
      window._stageWatchReloads = (window._stageWatchReloads || 0) + 1;
      const sep = _stageWatchUrl.indexOf("?") >= 0 ? "&" : "?";
      const fresh = _stageWatchUrl + sep + "_r=" + Date.now();
      // 换 fr.src 实测不生效 (iframe 没真重取) → 优先让 iframe 自己导航 · src 只作兜底 (BRO 2026-09-16)
      let done = false;
      try { if (fr.contentWindow) { fr.contentWindow.location.replace(fresh); done = true; } } catch (e) { done = false; }
      if (!done) { try { fr.src = fresh; } catch (e2) { /* noop */ } }
    }).catch(function () {});
  }, 3000);
}

function openStageLast(paths) {
  const list = (paths || []).filter(Boolean);
  let picked = "";
  for (let i = list.length - 1; i >= 0; i--) {
    if (stageCanOpen(list[i])) { picked = list[i]; break; }
  }
  if (!picked) return false;
  // 2026-09-15 · 原 compact 早退已删 — 专注版也走同一出口 (右栏抽屉浮出) · 不再分叉两套。
  return openStage({ path: picked, refresh: true, auto: true });
}

window.openStage = openStage;
window.stageCanOpen = stageCanOpen;
window.openStageLast = openStageLast;
window.stageClose = stageClose;
window.stageBack = stageClose;
window.stagePaint = stagePaint;
window.stageIsVisible = stageIsVisible;
window.stageEnsureWorkbench = stageEnsureWorkbench;
window.stagePane = stagePane;
if (window.Daemonkey) {
  window.Daemonkey.openStage = openStage;
  window.Daemonkey.stageClose = stageClose;
}
