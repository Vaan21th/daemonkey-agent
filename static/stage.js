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
  if (document.body.classList.contains("compact") && typeof toggleCompact === "function") {
    toggleCompact(false);
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
  document.body.classList.toggle("dk-stage-open", !!on);
}

function stageRemember() {
  if (!window._stageMode) {
    _stageView = (typeof currentView !== "undefined" && currentView) ? currentView : "bi";
  }
}

function stageClose() {
  if (typeof window.stageNotesReset === "function") window.stageNotesReset();
  window._stageMode = null;
  stageMarkOpen(false);
  if (typeof window._syncPlanToggle === "function") window._syncPlanToggle();
  const view = _stageView || ((typeof currentView !== "undefined" && currentView) ? currentView : "bi");
  _stageView = "";
  if (typeof loadDashboard === "function") loadDashboard(view);
  else if (typeof renderDetailWelcome === "function") renderDetailWelcome();
}

function stageEsc(s) {
  return (typeof escHtml === "function") ? escHtml(s) : String(s || "");
}

function stagePaint(pane, spec, inner, paper) {
  stageRemember();
  window._stageMode = spec.mode;
  stageMarkOpen(true);
  const tag = spec.tag || stageTag(spec.mode, spec.kind);
  pane.innerHTML = `
    <div class="stage-root${paper ? " is-paper" : ""}">
      <div class="stage-bar">
        <span class="stage-tag">${stageEsc(tag)}</span>
        <h2 class="stage-title">${stageEsc(spec.name || "画布")}</h2>
        ${spec.meta ? `<span class="stage-meta">${stageEsc(spec.meta)}</span>` : ""}
        ${spec.path ? `<button type="button" class="stage-open" id="stageRevealBtn" title="用软件打开"><i class="ri-external-link-line"></i></button>` : ""}
        <button type="button" class="stage-x" id="stageCloseBtn" title="关掉画布"><i class="ri-close-line"></i></button>
      </div>
      <div class="stage-body${paper ? " stage-paper" : ""}" id="stageBody">${inner || ""}</div>
    </div>`;
  const x = pane.querySelector("#stageCloseBtn");
  if (x) x.onclick = stageClose;
  const reveal = pane.querySelector("#stageRevealBtn");
  if (reveal && spec.path && typeof revealFile === "function") {
    reveal.onclick = () => revealFile(spec.path, reveal);
  }
  if (typeof window._syncPlanToggle === "function") window._syncPlanToggle();
  if (typeof window.stageNotesBind === "function") window.stageNotesBind(spec);
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
  if (input && input.auto && document.body.classList.contains("compact")) return false;
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
  if (spec.mode === "office" && !histFile && !(input && input._homed) && typeof window.goOfficeHome === "function") {
    window.goOfficeHome(spec.path).then(function () {
      openStage(Object.assign({}, input || {}, { path: spec.path, _homed: true, refresh: true }));
    });
    return true;
  }
  if (spec.mode === "office") {
    if (typeof window.bindWorkingDoc === "function") window.bindWorkingDoc(spec.path);
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
  const src = stageEsc(stageWithAuth(spec.url));
  const embed = {
    video: `<video class="stage-media" controls preload="metadata" src="${src}"></video>`,
    html: `<iframe class="stage-frame" title="HTML" src="${src}" sandbox="allow-same-origin allow-scripts allow-popups" loading="lazy"></iframe>`,
    pdf: `<iframe class="stage-frame" title="PDF" src="${src}"></iframe>`,
    image: `<img class="stage-img" alt="" src="${src}">`,
  };
  if (!embed[spec.mode]) return false;
  stagePaint(pane, spec, embed[spec.mode]);
  const fr = pane.querySelector("iframe.stage-frame");
  if (fr && typeof window.styleOfficePreviewFrame === "function") {
    window.styleOfficePreviewFrame(fr);
  }
  return true;
}

function openStageLast(paths) {
  const list = (paths || []).filter(Boolean);
  let picked = "";
  for (let i = list.length - 1; i >= 0; i--) {
    if (stageCanOpen(list[i])) { picked = list[i]; break; }
  }
  if (!picked) return false;
  if (document.body.classList.contains("compact")) return false;
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
