/* 画布批注：点在稿子上说话，按批注改塞进下一轮对话。 */

const STAGE_NOTES_KEY = "dk_stage_notes_v1";
window._stageNotePath = "";
window._stageNoteArmed = false;
window._stageNoteSel = "";

function notesKey() {
  const path = String(window._stageNotePath || "").replace(/\\/g, "/");
  if (window._stageMode === "plan" || path === "plan") return "plan";
  return path || (window._stageMode || "canvas");
}

function notesAll() {
  try {
    const raw = JSON.parse(localStorage.getItem(STAGE_NOTES_KEY) || "{}");
    if (raw && typeof raw === "object") {
      window._stageNoteMem = raw;
      return raw;
    }
  } catch (e) { /* 隐私模式 */ }
  if (!window._stageNoteMem || typeof window._stageNoteMem !== "object") {
    window._stageNoteMem = {};
  }
  return window._stageNoteMem;
}

function notesLoad() {
  const cur = notesAll()[notesKey()];
  return Array.isArray(cur) ? cur : [];
}

function notesSave(items) {
  const all = notesAll();
  const key = notesKey();
  if (items && items.length) all[key] = items;
  else delete all[key];
  window._stageNoteMem = all;
  try {
    localStorage.setItem(STAGE_NOTES_KEY, JSON.stringify(all));
  } catch (e) { /* 隐私模式 / 配额 */ }
}

function notesShown(el) {
  if (!el || !el.isConnected || el.hidden) return false;
  const pane = el.closest("[data-rp-pane]");
  if (pane && pane.hidden) return false;
  const box = el.getBoundingClientRect();
  return box.width > 8 && box.height > 8;
}

function notesHost() {
  const slide = document.querySelector(".rp-slide-stage");
  if (notesShown(slide)) return slide;
  const vis = document.getElementById("rpVisual");
  if (vis && !vis.hidden && notesShown(vis)) return vis;
  const body = document.getElementById("stageBody");
  if (notesShown(body)) return body;
  const paper = document.querySelector(".rp-body") || document.querySelector(".rp-md");
  return notesShown(paper) ? paper : null;
}

function notesPreviewFrame() {
  const host = notesHost();
  return (host && host.querySelector("iframe")) || null;
}

function notesSlideImg() {
  const stage = document.querySelector(".rp-slide-stage");
  if (!notesShown(stage)) return null;
  return stage.querySelector("#rpSlideImg") || stage.querySelector("img");
}

function notesPreviewDoc() {
  const fr = notesPreviewFrame();
  try { return (fr && fr.contentDocument) || null; } catch (e) { return null; }
}

function notesSlideEl(doc, slideNo) {
  if (!doc || !slideNo) return null;
  const list = doc.querySelectorAll(".main > .slide-container, .slide-container");
  const wrap = list[slideNo - 1];
  return (wrap && (wrap.querySelector(".slide") || wrap)) || null;
}

function notesSlideFromSel(doc) {
  try {
    const sel = doc && doc.getSelection && doc.getSelection();
    const node = sel && sel.anchorNode;
    const el = node && (node.nodeType === 1 ? node : node.parentElement);
    const wrap = el && el.closest && el.closest(".slide-container");
    if (!wrap) return 0;
    const marked = parseInt(wrap.getAttribute("data-slide") || "0", 10);
    if (marked) return marked;
    const list = doc.querySelectorAll(".slide-container");
    for (let i = 0; i < list.length; i++) {
      if (list[i] === wrap) return i + 1;
    }
  } catch (e) { /* 选区不在某一页里 */ }
  return 0;
}

function notesSlideAtPoint(doc, ix, iy) {
  if (!doc) return 0;
  const list = doc.querySelectorAll(".main > .slide-container, .slide-container");
  for (let i = 0; i < list.length; i++) {
    const el = list[i].querySelector(".slide") || list[i];
    const r = el.getBoundingClientRect();
    if (ix >= r.left && ix <= r.right && iy >= r.top && iy <= r.bottom) {
      return parseInt(list[i].getAttribute("data-slide") || "0", 10) || (i + 1);
    }
  }
  return 0;
}

function notesSlideIndex() {
  const pos = document.getElementById("rpSlidePos");
  if (pos) {
    const m = String(pos.textContent || "").match(/(\d+)\s*\/\s*\d+/);
    if (m) return parseInt(m[1], 10);
  }
  const doc = notesPreviewDoc();
  if (!doc) return 0;
  const counter = doc.querySelector(".page-counter");
  if (counter) {
    const m = String(counter.textContent || "").match(/(\d+)\s*\/\s*\d+/);
    if (m) return parseInt(m[1], 10);
  }
  const num = doc.querySelector(".thumb.active .thumb-num") || doc.querySelector(".thumb.active");
  const thumb = parseInt(String((num && num.textContent) || "").replace(/\D/g, ""), 10);
  if (thumb) return thumb;
  const fs = doc.querySelector(".slide-container.fs-active");
  if (fs) {
    const n = parseInt(fs.getAttribute("data-slide") || "0", 10);
    if (n) return n;
  }
  const main = doc.querySelector(".main");
  if (main) {
    const view = main.getBoundingClientRect();
    let best = 0;
    let area = 0;
    doc.querySelectorAll(".main > .slide-container, .slide-container").forEach(function (c, i) {
      const r = c.getBoundingClientRect();
      const hit = Math.max(0, Math.min(r.bottom, view.bottom) - Math.max(r.top, view.top));
      if (hit > area) {
        area = hit;
        best = parseInt(c.getAttribute("data-slide") || "0", 10) || (i + 1);
      }
    });
    if (best) return best;
  }
  return 0;
}

function notesSlideForDrop(clientX, clientY) {
  const fr = notesPreviewFrame();
  const doc = notesPreviewDoc();
  if (fr && doc) {
    const box = fr.getBoundingClientRect();
    const at = notesSlideAtPoint(doc, clientX - box.left, clientY - box.top);
    if (at) return at;
    const fromSel = notesSlideFromSel(doc);
    if (fromSel) return fromSel;
  }
  return notesSlideIndex();
}

function notesPinOnPage(it, slide) {
  const pinSlide = (it && it.slide) || 0;
  if (!pinSlide || !slide) return true;
  return pinSlide === slide;
}

function notesPinViewport(it, layer) {
  const box = (layer || document.getElementById("rpVisual") || document.body).getBoundingClientRect();
  const fr = notesPreviewFrame();
  const doc = notesPreviewDoc();
  if (it.rel === "slide" && fr) {
    const slideEl = notesSlideEl(doc, it.slide);
    if (slideEl) {
      const frBox = fr.getBoundingClientRect();
      const sr = slideEl.getBoundingClientRect();
      return {
        left: frBox.left + sr.left + it.x * sr.width,
        top: frBox.top + sr.top + it.y * sr.height,
      };
    }
  }
  if (it.rel === "content" && fr && doc) {
    const root = notesScrollRoot(doc);
    if (root) {
      const frBox = fr.getBoundingClientRect();
      const rr = root.getBoundingClientRect();
      return {
        left: frBox.left + rr.left - root.scrollLeft + it.x * Math.max(root.scrollWidth, rr.width, 1),
        top: frBox.top + rr.top - root.scrollTop + it.y * Math.max(root.scrollHeight, rr.height, 1),
      };
    }
  }
  const img = notesSlideImg();
  if (img && !fr && (it.rel === "page" || it.slide)) {
    const sr = img.getBoundingClientRect();
    return {
      left: sr.left + it.x * sr.width,
      top: sr.top + it.y * sr.height,
    };
  }
  return {
    left: box.left + it.x * Math.max(box.width, 1),
    top: box.top + it.y * Math.max(box.height, 1),
  };
}

function notesPaintChrome() {
  const bar = document.querySelector(".dash-head.stage-bar") || document.querySelector(".stage-bar");
  if (!bar) return;
  if (bar.querySelector("#stageNoteBtn")) {
    notesHoldSelBtn(document.getElementById("stageNoteBtn"));
    notesUpdateCount();
    return;
  }
  const wrap = document.createElement("div");
  wrap.className = "stage-notes-tools";
  wrap.innerHTML = ""
    + "<button type=\"button\" class=\"stage-note-arm\" id=\"stageNoteBtn\" title=\"划字出批注；或点这里再点空白处钉位置\">"
    + "<i class=\"ri-sticky-note-line\"></i><span>批注</span><b id=\"stageNoteCount\" hidden></b></button>"
    + "<button type=\"button\" class=\"stage-note-send\" id=\"stageNoteSend\" hidden title=\"把批注发给对话里改\">"
    + "<i class=\"ri-chat-forward-line\"></i> 按批注改</button>";
  const close = bar.querySelector(".stage-x") || bar.querySelector("#stageCloseBtn");
  if (close) bar.insertBefore(wrap, close);
  else bar.appendChild(wrap);
  notesHoldSelBtn(document.getElementById("stageNoteBtn"));
  document.getElementById("stageNoteBtn").onclick = notesToggleArm;
  document.getElementById("stageNoteSend").onclick = notesSend;
  notesUpdateCount();
}

function notesHoldSelBtn(btn) {
  if (!btn || btn._dkNoteHold) return;
  btn._dkNoteHold = true;
  btn.addEventListener("mousedown", function (ev) {
    ev.preventDefault();
    notesMarkSel();
  });
}

function notesEnsureLayer() {
  const host = notesHost();
  if (!host) return null;
  host.classList.add("stage-note-host");
  let layer = host.querySelector(":scope > .stage-note-layer");
  if (!layer) {
    layer = document.createElement("div");
    layer.className = "stage-note-layer";
    host.appendChild(layer);
  }
  layer.classList.toggle("is-aim", !!window._stageNoteArmed);
  host.classList.toggle("is-aim", !!window._stageNoteArmed);
  // iframe 里滚 · 层跟着宿主可视框走 · 拉成 scrollHeight 会把 % 坐标漂掉
  if (!notesPreviewFrame() && host.scrollHeight > host.clientHeight + 8) {
    layer.style.height = host.scrollHeight + "px";
  } else {
    layer.style.height = "";
  }
  notesBindFrames();
  return layer;
}

function notesDocSel(doc) {
  try {
    return ((doc && doc.getSelection && doc.getSelection().toString()) || "").trim();
  } catch (e) {
    return "";
  }
}

function notesLiveSel() {
  let text = notesDocSel(document);
  notesAllFrames().forEach(function (fr) {
    try {
      const inner = notesDocSel(fr.contentDocument);
      if (inner) text = inner;
    } catch (e) { /* 跨域 */ }
  });
  return text.slice(0, 200);
}

function notesMarkSel() {
  window._stageNoteSel = notesLiveSel();
}

function notesIgnoreTarget(el) {
  if (!el || !el.closest) return false;
  return !!el.closest([
    ".stage-pin", ".dk-stage-pin", ".stage-note-card", ".stage-notes-tools", ".stage-x",
    ".stage-note-arm", ".stage-note-send", ".depot-tab", ".rp-slide-nav",
    ".rp-slide-thumbs", ".rp-thumb",
    ".sidebar", ".thumb", "button", "a",
  ].join(","));
}

function notesSelRange(doc) {
  try {
    const sel = doc && doc.getSelection && doc.getSelection();
    const text = ((sel && sel.toString()) || "").trim();
    if (!sel || !text || !sel.rangeCount) return null;
    if (doc === document) {
      const host = notesHost();
      const node = sel.anchorNode;
      const el = node && (node.nodeType === 1 ? node : node.parentElement);
      if (!host || !el || !host.contains(el)) return null;
    }
    const r = sel.getRangeAt(0).getBoundingClientRect();
    let cx = 0;
    let cy = 0;
    if (r && (r.width >= 1 || r.height >= 1)) {
      cx = (r.left + r.right) / 2;
      cy = r.bottom || r.top;
    } else {
      const box = ((doc.querySelector && doc.querySelector(".slide")) || doc.documentElement).getBoundingClientRect();
      cx = (box.left + box.right) / 2;
      cy = (box.top + box.bottom) / 2;
    }
    return { text: text.slice(0, 200), cx: cx, cy: cy };
  } catch (e) {
    return null;
  }
}

function notesShiftFromFrame(got, fr) {
  if (!got || !fr) return got;
  const box = fr.getBoundingClientRect();
  got.cx += box.left;
  got.cy += box.top;
  return got;
}

function notesGotFrom(fr) {
  if (fr) {
    try { return notesShiftFromFrame(notesSelRange(fr.contentDocument), fr); } catch (e) { return null; }
  }
  return notesSelRange(document);
}

function notesMaybeFromSel(fr) {
  const got = notesGotFrom(fr);
  if (!got || got.text.length < 2) return false;
  window._stageNoteSel = got.text;
  if (notesIsBusy()) {
    const same = notesLoad().some(function (n) { return n.sel === got.text; });
    if (same) return true;
    notesCloseCard();
  }
  notesDropAt(got.cx, got.cy, null, got.text);
  return true;
}

function notesAllFrames() {
  const seen = [];
  const roots = [
    document.getElementById("rpVisual"),
    document.getElementById("stageBody"),
    document.querySelector(".rp-slide-stage"),
    notesHost(),
  ];
  roots.forEach(function (root) {
    if (!root) return;
    root.querySelectorAll("iframe").forEach(function (fr) {
      if (seen.indexOf(fr) < 0) seen.push(fr);
    });
  });
  return seen;
}

function notesHookDoc(doc, fr) {
  if (!doc || doc._dkNoteBound) return;
  doc._dkNoteBound = true;
  const snap = function () {
    const t = notesDocSel(doc);
    if (t.length >= 2) window._stageNoteSel = t.slice(0, 200);
  };
  doc.addEventListener("selectionchange", snap);
  doc.addEventListener("mouseup", function () {
    snap();
    setTimeout(function () { notesMaybeFromSel(fr); }, 10);
  }, true);
  doc.addEventListener("click", function (ev) {
    if (notesIgnoreTarget(ev.target)) return;
    if (notesMaybeFromSel(fr)) return;
    if (!window._stageNoteArmed) return;
    const box = fr.getBoundingClientRect();
    notesDropAt(box.left + ev.clientX, box.top + ev.clientY, ev, "");
  }, true);
  doc.querySelectorAll("iframe").forEach(notesWatchFrame);
  notesWatchPage(doc, fr);
  notesRenderPins();
}

function notesWatchPage(doc, fr) {
  if (!doc || doc._dkNotePageWatch) return;
  doc._dkNotePageWatch = true;
  const bump = function () { notesSyncPage(); };
  const hard = function () { notesSyncPage(true); };
  const listen = function (el) {
    if (!el || el._dkNoteScroll) return;
    el._dkNoteScroll = true;
    el.addEventListener("scroll", hard, { passive: true, capture: true });
  };
  listen(doc);
  listen(doc.documentElement);
  listen(doc.body);
  listen(doc.querySelector(".main"));
  if (fr) listen(fr);
  try {
    if (fr && fr.contentWindow) listen(fr.contentWindow);
  } catch (e) { /* 跨域 */ }
  doc.addEventListener("click", function (ev) {
    if (ev.target && ev.target.closest && ev.target.closest(".thumb, .sidebar, .page-counter")) {
      setTimeout(bump, 40);
    }
  }, true);
  doc.addEventListener("keydown", function () { setTimeout(bump, 40); }, true);
  const watch = doc.querySelector(".page-counter") || doc.querySelector(".sidebar");
  if (watch) {
    new MutationObserver(bump).observe(watch, {
      childList: true,
      characterData: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["class"],
    });
  }
}

function notesSyncPage(force) {
  const n = notesSlideIndex();
  const pageChanged = n !== window._stageNoteSlide;
  if (!force && !pageChanged) return;
  window._stageNoteSlide = n;
  const card = document.getElementById("stageNoteCard");
  if (pageChanged && card && card.dataset.id) {
    const it = notesLoad().find(function (x) { return x.id === card.dataset.id; });
    if (it && !notesPinOnPage(it, n)) notesCloseCard();
  }
  if (pageChanged) notesRenderPins();
  else notesPlaceFloating();
}

function notesWatchFrame(fr) {
  if (!fr) return;
  const hook = function () {
    try { notesHookDoc(fr.contentDocument, fr); } catch (e) { /* 跨域 */ }
  };
  if (!fr._dkNoteWatch) {
    fr._dkNoteWatch = true;
    fr.addEventListener("load", hook);
  }
  hook();
}

function notesBindFrames() {
  notesAllFrames().forEach(notesWatchFrame);
}

function notesToggleArm() {
  notesMarkSel();
  const live = window._stageNoteSel || notesLiveSel();
  if (live && live.length >= 2) {
    const host = notesHost();
    const box = (host || document.body).getBoundingClientRect();
    notesDropAt(box.left + box.width * 0.55, box.top + box.height * 0.35, null, live);
    return;
  }
  window._stageNoteArmed = !window._stageNoteArmed;
  const btn = document.getElementById("stageNoteBtn");
  if (btn) btn.classList.toggle("is-on", window._stageNoteArmed);
  notesEnsureLayer();
}

function notesDisarm() {
  window._stageNoteArmed = false;
  const btn = document.getElementById("stageNoteBtn");
  if (btn) btn.classList.remove("is-on");
  document.querySelectorAll(".stage-note-layer").forEach(function (el) {
    el.classList.remove("is-aim");
  });
  document.querySelectorAll(".stage-note-host").forEach(function (el) {
    el.classList.remove("is-aim");
  });
}

function notesUnder(e, layer) {
  if (!e || !layer) return null;
  const prev = layer.style.pointerEvents;
  layer.style.pointerEvents = "none";
  const under = document.elementFromPoint(e.clientX, e.clientY);
  layer.style.pointerEvents = prev;
  return under;
}

function notesOnClick(e) {
  if (notesIgnoreTarget(e.target)) return;
  const host = notesHost();
  if (!host || !host.contains(e.target)) return;
  if (e.target.tagName === "IFRAME") return;
  if (notesMaybeFromSel(null)) return;
  if (!window._stageNoteArmed) return;
  notesDropAt(e.clientX, e.clientY, e, "");
}

function notesDropAt(clientX, clientY, ev, forcedSel) {
  const sel = (forcedSel != null ? forcedSel : (notesLiveSel() || window._stageNoteSel || "")).trim();
  if (!sel && !window._stageNoteArmed) return;
  if (notesIsBusy()) return;
  const layer = notesEnsureLayer();
  const slide = notesSlideForDrop(clientX, clientY);
  const fr = notesPreviewFrame();
  const slideEl = notesSlideEl(notesPreviewDoc(), slide);
  let x;
  let y;
  let rel = "host";
  if (fr && slideEl) {
    const frBox = fr.getBoundingClientRect();
    const sr = slideEl.getBoundingClientRect();
    x = (clientX - (frBox.left + sr.left)) / Math.max(sr.width, 1);
    y = (clientY - (frBox.top + sr.top)) / Math.max(sr.height, 1);
    rel = "slide";
  } else if (fr && notesPreviewDoc() && notesScrollRoot(notesPreviewDoc())) {
    const inner = notesPreviewDoc();
    const root = notesScrollRoot(inner);
    const frBox = fr.getBoundingClientRect();
    const rr = root.getBoundingClientRect();
    x = (clientX - (frBox.left + rr.left) + root.scrollLeft) / Math.max(root.scrollWidth, rr.width, 1);
    y = (clientY - (frBox.top + rr.top) + root.scrollTop) / Math.max(root.scrollHeight, rr.height, 1);
    rel = "content";
  } else {
    const img = notesSlideImg();
    const box = (img || layer || document.getElementById("rpVisual") || document.body).getBoundingClientRect();
    x = (clientX - box.left) / Math.max(box.width, 1);
    y = (clientY - box.top) / Math.max(box.height, 1);
    if (img) rel = "page";
  }
  const under = (ev && layer) ? notesUnder(ev, layer) : null;
  const stepEl = under && under.closest && under.closest(".plan-step");
  let step = 0;
  if (stepEl) {
    step = parseInt(((stepEl.querySelector(".plan-step-i") || {}).textContent || "0"), 10) || 0;
  }
  const items = notesLoad();
  const same = sel && items.find(function (n) { return n.sel === sel; });
  if (same) {
    notesDisarm();
    notesRenderPins();
    notesOpenCard(same.id);
    return;
  }
  const id = Date.now().toString(36);
  items.push({
    id: id,
    x: Math.max(0, Math.min(1, x)),
    y: Math.max(0, Math.min(1, y)),
    text: "",
    sel: sel,
    slide: slide,
    rel: rel,
    step: step,
  });
  notesSave(items);
  notesDisarm();
  notesRenderPins();
  notesOpenCard(id);
}

function notesIsBusy() {
  return !!document.getElementById("stageNoteCard");
}

function notesInjectPinCss(doc) {
  if (!doc || doc.getElementById("dk-stage-pin-css")) return;
  const s = doc.createElement("style");
  s.id = "dk-stage-pin-css";
  s.textContent = ""
    + ".dk-stage-pin{position:absolute!important;z-index:2147483646!important;"
    + "width:22px!important;height:22px!important;padding:0!important;margin:0!important;"
    + "border:0!important;border-radius:50%!important;background:#9F7AEA!important;"
    + "color:#fff!important;font:700 11px/22px sans-serif!important;text-align:center!important;"
    + "cursor:pointer!important;pointer-events:auto!important;"
    + "transform:translate(-50%,-50%)!important;box-shadow:0 1px 4px rgba(0,0,0,.4)!important;"
    + "left:var(--dk-x)!important;top:var(--dk-y)!important}";
  (doc.head || doc.documentElement).appendChild(s);
}

function notesClearPins() {
  const layer = document.querySelector(".stage-note-layer");
  if (layer) layer.querySelectorAll(".stage-pin").forEach(function (n) { n.remove(); });
  document.querySelectorAll(".stage-pin.dk-overlay-pin").forEach(function (n) { n.remove(); });
  const doc = notesPreviewDoc();
  if (doc) doc.querySelectorAll(".dk-stage-pin").forEach(function (n) { n.remove(); });
}

function notesVisibleBox() {
  const fr = notesPreviewFrame();
  if (fr) return fr.getBoundingClientRect();
  const host = notesHost();
  return host ? host.getBoundingClientRect() : null;
}

function notesScrollRoot(doc) {
  if (!doc) return null;
  const main = doc.querySelector(".main");
  if (main && main.scrollHeight > main.clientHeight + 8) return main;
  return doc.scrollingElement || doc.documentElement || doc.body;
}

function notesMountContentPin(doc, it, label) {
  if (!doc || !it || it.rel !== "content") return false;
  const root = notesScrollRoot(doc);
  if (!root) return false;
  notesInjectPinCss(doc);
  try {
    if (doc.defaultView.getComputedStyle(root).position === "static") {
      root.style.position = "relative";
    }
  } catch (e) {
    root.style.position = "relative";
  }
  const pin = doc.createElement("button");
  pin.type = "button";
  pin.className = "dk-stage-pin";
  pin.setAttribute("data-id", it.id);
  pin.textContent = label;
  pin.style.setProperty("--dk-x", (it.x * root.scrollWidth) + "px");
  pin.style.setProperty("--dk-y", (it.y * root.scrollHeight) + "px");
  pin.title = it.text || it.sel || "批注";
  pin.addEventListener("click", function (ev) {
    ev.preventDefault();
    ev.stopPropagation();
    notesOpenCard(it.id);
  });
  root.appendChild(pin);
  return true;
}

function notesMountSlidePin(doc, it, label) {
  if (!doc || !it || it.rel !== "slide" || !it.slide) return false;
  const slideEl = notesSlideEl(doc, it.slide);
  if (!slideEl) return false;
  notesInjectPinCss(doc);
  try {
    if (doc.defaultView.getComputedStyle(slideEl).position === "static") {
      slideEl.style.position = "relative";
    }
  } catch (e) {
    slideEl.style.position = "relative";
  }
  const pin = doc.createElement("button");
  pin.type = "button";
  pin.className = "dk-stage-pin";
  pin.setAttribute("data-id", it.id);
  pin.textContent = label;
  pin.style.setProperty("--dk-x", (it.x * 100) + "%");
  pin.style.setProperty("--dk-y", (it.y * 100) + "%");
  pin.title = it.text || it.sel || "批注";
  pin.addEventListener("click", function (ev) {
    ev.preventDefault();
    ev.stopPropagation();
    notesOpenCard(it.id);
  });
  slideEl.appendChild(pin);
  return true;
}

function notesPlaceOneOverlay(pin, it) {
  const at = notesPinViewport(it, notesEnsureLayer());
  const box = notesVisibleBox();
  const inside = !box
    || (at.left >= box.left - 4 && at.left <= box.right + 4
      && at.top >= box.top - 4 && at.top <= box.bottom + 4);
  pin.hidden = !inside;
  pin.style.left = Math.round(at.left) + "px";
  pin.style.top = Math.round(at.top) + "px";
}

function notesPlaceCard() {
  const card = document.getElementById("stageNoteCard");
  if (!card || !card.dataset.id) return;
  const it = notesLoad().find(function (x) { return x.id === card.dataset.id; });
  if (!it) return;
  const at = notesPinViewport(it, notesEnsureLayer());
  card.style.left = Math.round(at.left) + "px";
  card.style.top = Math.round(at.top) + "px";
}

function notesPlaceFloating() {
  notesLoad().forEach(function (it) {
    const pin = document.querySelector(".stage-pin.dk-overlay-pin[data-id=\"" + it.id + "\"]");
    if (pin) notesPlaceOneOverlay(pin, it);
  });
  notesPlaceCard();
}

function notesMountOverlayPin(it, label) {
  const pin = document.createElement("button");
  pin.type = "button";
  pin.className = "stage-pin dk-overlay-pin";
  pin.dataset.id = it.id;
  pin.textContent = label;
  pin.title = it.text || it.sel || "批注";
  pin.onclick = function (ev) {
    ev.stopPropagation();
    notesOpenCard(it.id);
  };
  document.body.appendChild(pin);
  notesPlaceOneOverlay(pin, it);
}

function notesRenderPins() {
  if (window._dkNoteRendering) return;
  window._dkNoteRendering = true;
  try {
    const layer = notesEnsureLayer();
    if (!layer) {
      notesClearPins();
      notesUpdateCount();
      return;
    }
    notesClearPins();
    if (!document.getElementById("stageNoteCard")) {
      layer.querySelectorAll(".stage-note-card").forEach(function (n) { n.remove(); });
    }
    const slide = notesSlideIndex();
    const doc = notesPreviewDoc();
    notesLoad().forEach(function (it, i) {
      const label = String(i + 1);
      if (notesMountSlidePin(doc, it, label)) return;
      if (notesMountContentPin(doc, it, label)) return;
      if (!notesPinOnPage(it, slide)) return;
      notesMountOverlayPin(it, label);
    });
    notesPlaceCard();
    notesUpdateCount();
  } finally {
    window._dkNoteRendering = false;
  }
}

function notesCloseCard() {
  const c = document.getElementById("stageNoteCard");
  if (c) c.remove();
}

function notesOpenCard(id) {
  notesCloseCard();
  const items = notesLoad();
  const it = items.find(function (n) { return n.id === id; });
  if (!it) return;
  const layer = notesEnsureLayer();
  const hint = it.sel
    ? ("圈了：「" + it.sel.slice(0, 40) + "」")
    : (it.slide > 0 ? ("第 " + it.slide + " 页") : (it.step > 0 ? ("第 " + it.step + " 步") : "钉在这里"));
  const card = document.createElement("div");
  card.className = "stage-note-card";
  card.id = "stageNoteCard";
  card.dataset.id = it.id;
  const at = notesPinViewport(it, layer);
  card.style.position = "fixed";
  card.style.left = Math.round(at.left) + "px";
  card.style.top = Math.round(at.top) + "px";
  card.style.zIndex = "8600";
  if (it.x > 0.62) card.classList.add("is-left");
  if (it.y > 0.72) card.classList.add("is-up");
  const h = document.createElement("div");
  h.className = "stage-note-hint";
  h.textContent = hint;
  const ta = document.createElement("textarea");
  ta.className = "stage-note-input";
  ta.rows = 3;
  ta.placeholder = "告诉她这里怎么改…";
  ta.value = it.text || "";
  const row = document.createElement("div");
  row.className = "stage-note-row";
  const del = document.createElement("button");
  del.type = "button";
  del.className = "stage-note-del";
  del.textContent = "关闭批注";
  const ok = document.createElement("button");
  ok.type = "button";
  ok.className = "stage-note-ok";
  ok.textContent = "记下";
  row.appendChild(del);
  row.appendChild(ok);
  card.appendChild(h);
  card.appendChild(ta);
  card.appendChild(row);
  ok.onclick = function (ev) {
    ev.stopPropagation();
    it.text = ta.value.trim();
    notesSave(items);
    notesCloseCard();
    notesRenderPins();
  };
  del.onclick = function (ev) {
    ev.stopPropagation();
    notesSave(items.filter(function (n) { return n.id !== id; }));
    notesCloseCard();
    notesRenderPins();
  };
  ta.addEventListener("input", function () {
    it.text = ta.value;
    notesSave(items);
  });
  ta.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) ok.click();
  });
  document.body.appendChild(card);
  ta.focus();
}

function notesUpdateCount() {
  const n = notesLoad().length;
  const el = document.getElementById("stageNoteCount");
  if (el) {
    el.textContent = n ? String(n) : "";
    el.hidden = !n;
  }
  const send = document.getElementById("stageNoteSend");
  if (send) send.hidden = !n;
}

function notesToolHint() {
  const path = window._stageNotePath || "";
  const mode = window._stageMode || "";
  if (mode === "plan") return "用 track_task 的 plan/step 改当前计划，不要另写一份";
  if (/\.(pptx?|docx?|xlsx?)$/i.test(path)) {
    return "按意图伸手：圈字改句 revise_office（excerpt 用圈出的成品原文，body 只写改完的那一句）；加图 illustrate_office；插页 extend_office(after=页码)；换版式 revise_office(整页 markdown)。禁止 generate_presentation / 搜记忆。成品里划中文再钉更准";
  }
  if (mode === "md") return "只改圈出的那段，用 edit_file，不要整篇重写";
  return "按批注改这份稿，改完铺回中栏";
}

function notesIntent(ask) {
  const t = String(ask || "");
  if (/加图|配图|插图|放一张|贴一张|配一张|加一张/.test(t)) return "image";
  if (/插一页|后面加|加一页|插入一页|后面插|这页后面/.test(t)) return "insert";
  if (/版式|两栏|改成流程|换成|布局|改成图/.test(t) && !notesBareReplace(ask)) return "layout";
  return "text";
}

function notesXY(it) {
  const x = Math.max(0, Math.min(1, Number(it && it.x) || 0.5));
  const y = Math.max(0, Math.min(1, Number(it && it.y) || 0.5));
  return { x: x.toFixed(2), y: y.toFixed(2) };
}

function notesBareReplace(ask) {
  const t = String(ask || "").trim();
  const m = t.match(/^改成\s*[「『"']?(.+?)[」』"']?$/);
  return m ? m[1].trim() : "";
}

function notesRegion(it) {
  const hx = it.x < 0.33 ? "左" : (it.x > 0.66 ? "右" : "中");
  const hy = it.y < 0.33 ? "上" : (it.y > 0.66 ? "下" : "中");
  return hx === "中" && hy === "中" ? "中部" : (hy + hx);
}

function notesWhere(it) {
  const bits = [];
  if (it.slide > 0) bits.push("第" + it.slide + "页");
  if (it.step > 0) bits.push("第" + it.step + "步");
  if (it.sel) bits.push("「" + it.sel + "」");
  bits.push(notesRegion(it));
  return bits.join(" ");
}

function notesDispatch(msg) {
  if (typeof injectAndSend === "function") return injectAndSend(msg);
  if (typeof window.injectAndSend === "function") return window.injectAndSend(msg);
  if (typeof window.sendCompanionText === "function") return window.sendCompanionText(msg);
}

async function notesSend() {
  const items = notesLoad();
  if (!items.length) return;
  notesCloseCard();
  notesDisarm();
  const path = window._stageNotePath || "";
  const circled = items.some(function (it) { return !!(it.sel || "").trim(); });
  const office = /\.(pptx?|docx?|xlsx?)$/i.test(path);
  let msg;
  if (office) {
    const rows = items.map(function (it, i) {
      const excerpt = (it.sel || "").trim();
      const ask = (it.text || "").trim() || (excerpt ? "按圈出的这段改" : "看这里");
      const body = notesBareReplace(ask);
      const xy = notesXY(it);
      const page = it.slide > 0 ? it.slide : 1;
      const intent = notesIntent(ask);
      if (intent === "image") {
        return (i + 1) + ". illustrate_office path=" + path
          + " page=" + page + " x=" + xy.x + " y=" + xy.y
          + " prompt=" + ask;
      }
      if (intent === "insert") {
        return (i + 1) + ". extend_office path=" + path
          + " after=" + page + " body=按批注写新增页：" + ask;
      }
      if (intent === "layout") {
        return (i + 1) + ". revise_office path=" + path
          + " page=" + page + " body=按批注把这一页改成新版式：" + ask;
      }
      const bits = ["revise_office", "path=" + path, "page=" + page];
      bits.push("x=" + xy.x, "y=" + xy.y);
      if (excerpt) bits.push("excerpt=" + excerpt);
      bits.push(body ? ("body=" + body) : ("body=按批注写出改完的那一句：" + ask));
      return (i + 1) + ". " + bits.join(" ");
    });
    const warn = (!circled)
      ? "没圈出原文的条目只有页码。改一段请在成品里划中文字再钉。"
      : "";
    msg = ["【中栏批注】" + notesToolHint() + "。", warn, rows.join("\n")].filter(Boolean).join("\n");
  } else {
    const lines = items.map(function (it, i) {
      const body = (it.text || "").trim() || (it.sel ? "按圈出的这段改" : "看这里");
      return (i + 1) + ". [" + notesWhere(it) + "] " + body;
    });
    msg = [
      "我在中栏画布上批了 " + items.length + " 条，按这些改。" + notesToolHint() + "。改完会铺回中栏。",
      path && path !== "plan" ? ("文件：" + path) : (window._stageMode === "plan" ? "对象：当前计划书" : ""),
      "",
    ].concat(lines).filter(Boolean).join("\n");
  }
  if (office && path && typeof window.bindWorkingDoc === "function") {
    const data = await window.bindWorkingDoc(path);
    const mine = ((data && data.working_docs) || []).some(function (d) {
      let p = String((d && d.path) || "").replace(/\\/g, "/").replace(/^\/+/, "");
      let q = String(path).replace(/\\/g, "/").replace(/^\/+/, "");
      if (/^(presentations|reports|spreadsheets)\//i.test(p)) p = "data/" + p;
      if (/^(presentations|reports|spreadsheets)\//i.test(q)) q = "data/" + q;
      return p === q;
    });
    if (!mine) {
      const home = data && data.home_sid;
      if (home && typeof window.switchToSession === "function") {
        await window.switchToSession(home);
      }
    }
  }
  notesDispatch(msg);
  notesSave([]);
  notesRenderPins();
}

function notesBind(spec) {
  if (spec) {
    if (spec.path) window._stageNotePath = String(spec.path).replace(/\\/g, "/");
    else if (spec.mode === "plan") window._stageNotePath = "plan";
  }
  if (!document._dkNotesDoc) {
    document._dkNotesDoc = true;
    document.addEventListener("mouseup", function () {
      notesMarkSel();
      setTimeout(function () { notesMaybeFromSel(null); }, 10);
    }, true);
    document.addEventListener("click", notesOnClick, true);
    if (document.body && !document._dkNotesObs) {
      document._dkNotesObs = new MutationObserver(function () { notesBindFrames(); });
      document._dkNotesObs.observe(document.body, { childList: true, subtree: true });
    }
  }
  notesPaintChrome();
  notesBindFrames();
  notesRenderPins();
  if (!window._dkNoteMove) {
    window._dkNoteMove = true;
    window.addEventListener("scroll", notesPlaceFloating, true);
    window.addEventListener("resize", notesPlaceFloating);
    const pane = document.querySelector(".detail-pane");
    if (pane) pane.addEventListener("scroll", notesPlaceFloating, { passive: true });
  }
  if (!window._stageNotePageTick) {
    window._stageNotePageTick = setInterval(function () {
      if (!notesPreviewFrame() && !document.getElementById("rpSlidePos")) return;
      notesSyncPage();
      notesPlaceFloating();
    }, 400);
  }
}

function notesReset() {
  notesCloseCard();
  notesDisarm();
  notesClearPins();
}

window.stageNotesBind = notesBind;
window.stageNotesReset = notesReset;
window.stageNotesBusy = notesIsBusy;
if (window.Daemonkey) {
  window.Daemonkey.stageNotesBind = notesBind;
}
