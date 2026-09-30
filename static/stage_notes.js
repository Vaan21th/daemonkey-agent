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
      const base = notesRootBase(doc, root, rr);
      return {
        left: frBox.left + base.left - root.scrollLeft + it.x * Math.max(root.scrollWidth, rr.width, 1),
        top: frBox.top + base.top - root.scrollTop + it.y * Math.max(root.scrollHeight, rr.height, 1),
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
  // 清单优先 (BRO 2026-09-28 二次反馈): 他点「批注 2」想看清单，却弹出了批注卡 ——
  //   因为画布上还残留着上次的选区，「有选区 → 弹卡」那条分支先把它拦下了。
  //   划字本来就会自动弹卡（mouseup 那条路），不用按钮帮忙；
  //   所以只要已经有批注，按钮一律开清单。
  if (window._stageNoteListOpen) { notesCloseList(); return; }
  if (notesLoad().length) { notesOpenList(); return; }
  // 还没有任何批注 → 保持原来的两条路：有选区弹卡 / 无选区进待命态
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

/* ── 批注清单 (BRO 2026-09-28 · wish-58f30a5a) ──────────────────
   他要「看到圈了什么，写了什么」。本版只做「看 + 删 + 钉新的」；
   点条目跳到那一条的位置先不做（pptx 翻页 / 滚动定位各有各的坑，等他看过再说）。 */
function notesEsc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
  });
}

function notesWhereLabel(it) {
  const n = Number(it && it.slide);
  if (n > 0) return "第 " + n + " 页";
  return (it && it.rel === "page") ? "当前页" : "画布";
}

function notesListEl() {
  return document.getElementById("stageNoteList");
}

function notesListOutside(ev) {
  const el = notesListEl();
  if (!el || el.hidden) {
    document.removeEventListener("click", notesListOutside, true);
    return;
  }
  const btn = document.getElementById("stageNoteBtn");
  if (el.contains(ev.target)) return;
  if (btn && btn.contains(ev.target)) return;
  notesCloseList();
}

function notesCloseList() {
  const el = notesListEl();
  if (el) el.hidden = true;
  window._stageNoteListOpen = false;
  const btn = document.getElementById("stageNoteBtn");
  if (btn && !window._stageNoteArmed) btn.classList.remove("is-on");
  document.removeEventListener("click", notesListOutside, true);
}

function notesOpenList() {
  const items = notesLoad();
  if (!items.length) { notesCloseList(); return; }
  const btn = document.getElementById("stageNoteBtn");
  let el = notesListEl();
  if (!el) {
    el = document.createElement("div");
    el.id = "stageNoteList";
    el.className = "stage-note-list";
    document.body.appendChild(el);
  }
  let html = '<div class="snl-head"><i class="ri-sticky-note-line"></i> 批注 ' + items.length + ' 条'
    + '<button type="button" class="snl-x" title="收起清单">×</button></div>'
    + '<div class="snl-body">';
  items.forEach(function (it) {
    const sel = String(it.sel || "").trim();
    const txt = String(it.text || "").trim();
    html += '<div class="snl-item" data-id="' + notesEsc(it.id) + '">'
      + '<div class="snl-top"><span class="snl-where">' + notesWhereLabel(it) + '</span>'
      + '<button type="button" class="snl-del" title="删掉这条批注">删除</button></div>'
      + (sel
        ? '<div class="snl-sel">圈了：' + notesEsc(sel) + '</div>'
        : '<div class="snl-sel snl-none">（钉在空白处 · 没圈字）</div>')
      + (txt
        ? '<div class="snl-text">' + notesEsc(txt) + '</div>'
        : '<div class="snl-text snl-none">（还没写内容）</div>')
      + '</div>';
  });
  html += '</div><div class="snl-foot">'
    + '<button type="button" class="snl-add"><i class="ri-add-line"></i> 在画布上钉一条</button></div>';
  el.innerHTML = html;

  el.querySelector(".snl-x").onclick = function (ev) { ev.stopPropagation(); notesCloseList(); };
  // 点整条 → 跳到它在画布上的位置（删除按钮自己 stopPropagation，不会误触）
  Array.prototype.forEach.call(el.querySelectorAll(".snl-item"), function (row) {
    row.title = "跳到这条批注在画布上的位置";
    row.onclick = function (ev) {
      ev.stopPropagation();
      const id = row.getAttribute("data-id");
      const hit = notesLoad().filter(function (x) { return String(x.id) === String(id); })[0];
      if (!hit) return;
      if (notesGotoNote(hit)) { notesCloseList(); return; }
      // 找不到位置就别悄悄关掉 —— 让他知道刚才那一下发生了什么（原来会静默失败）
      const w = row.querySelector(".snl-where");
      if (w) {
        w.textContent = "这条在当前画布上找不到位置";
        w.style.color = "#d0604c";
      }
    };
  });
  Array.prototype.forEach.call(el.querySelectorAll(".snl-del"), function (b) {
    b.onclick = function (ev) {
      ev.stopPropagation();
      const row = b.closest(".snl-item");
      const id = row ? row.getAttribute("data-id") : "";
      const left = notesLoad().filter(function (x) { return String(x.id) !== String(id); });
      notesSave(left);
      notesRenderPins();
      notesUpdateCount();
      if (left.length) notesOpenList(); else notesCloseList();
    };
  });
  el.querySelector(".snl-add").onclick = function (ev) {
    ev.stopPropagation();
    notesCloseList();
    window._stageNoteArmed = true;
    if (btn) btn.classList.add("is-on");
    notesEnsureLayer();
  };
  el.onclick = function (ev) { ev.stopPropagation(); };

  el.hidden = false;
  window._stageNoteListOpen = true;
  if (btn) btn.classList.add("is-on");
  // 贴着按钮下沿放 · 右边超出就左移 · 下面放不下就翻到按钮上方
  const r = btn ? btn.getBoundingClientRect() : { left: 60, right: 0, top: 60, bottom: 60 };
  const w = el.offsetWidth || 320;
  const h = el.offsetHeight || 260;
  el.style.left = Math.min(Math.max(8, r.left), Math.max(8, window.innerWidth - w - 12)) + "px";
  let top = r.bottom + 8;
  if (top + h > window.innerHeight - 8) top = Math.max(8, r.top - h - 8);
  el.style.top = top + "px";
  setTimeout(function () {
    document.addEventListener("click", notesListOutside, true);
  }, 0);
}

/* 点清单里某一条 → 跳到它在画布上的位置 (BRO 2026-09-28「点了清单不能跳转吗？」)
   三条路盖住三种预览：
     ① 图片式幻灯片 → 点第 N 个缩略图（走预览器自己的 show(n)，不碰它的内部状态）
     ② iframe 版幻灯片 → 页是 DOM 元素（.slide-container），滚过去
     ③ 单页文档 / 画布 → 按 y 比例滚宿主
   跳完给那颗钉子套个临时描边（inline style，跨 iframe 也生效，不依赖样式表）。 */
function notesFlashPin(id) {
  if (!id) return;
  const one = function (doc) {
    if (!doc) return false;
    let pin = null;
    try {
      pin = doc.querySelector('.stage-pin[data-id="' + String(id).replace(/"/g, '\\"') + '"]');
    } catch (e) { pin = null; }
    if (!pin) return false;
    pin.style.outline = "3px solid var(--opus, #b794f6)";
    pin.style.outlineOffset = "2px";
    setTimeout(function () {
      pin.style.outline = "";
      pin.style.outlineOffset = "";
    }, 1500);
    return true;
  };
  if (one(document)) return;
  notesAllFrames().forEach(function (fr) {
    try { one(fr.contentDocument); } catch (e) { /* 跨域 / 还没就绪 */ }
  });
}

function notesScrollTo(it) {
  const y = Math.max(0, Math.min(1, Number(it && it.y) || 0));
  const aim = function (sc) {
    if (!sc) return false;
    if (sc.scrollHeight <= sc.clientHeight + 8) return false;
    sc.scrollTop = Math.max(0, Math.round(sc.scrollHeight * y - sc.clientHeight * 0.35));
    return true;
  };
  // ① 文档在 iframe 里（md / docx 预览常常是整篇塞进去，滚的是 iframe 自己）
  const doc = notesPreviewDoc();
  if (doc) {
    const sc = doc.scrollingElement || doc.documentElement || doc.body;
    if (aim(sc)) return true;
    // iframe 里也可能内层容器在滚 —— 扫一遍找最大的可滚块
    const inner = doc.querySelectorAll("article, main, section, .rp-md, .stage-doc, .document");
    for (let i = 0; i < inner.length; i++) { if (aim(inner[i])) return true; }
  }
  // ② 主文档：从各候选容器【向上】找第一个真能滚的
  //    手册教训：别拿容器自己判溢出会得到假结论，真正滚的往往是它自己或它某个祖先
  const cands = [
    document.querySelector(".rp-slide-stage"),
    document.getElementById("rpVisual"),
    document.getElementById("stageBody"),
    document.querySelector(".rp-body"),
    document.querySelector(".rp-md"),
  ];
  for (let i = 0; i < cands.length; i++) {
    const start = cands[i];
    if (!start || !notesShown(start)) continue;
    let n = start;
    while (n) {   // 一路走到 documentElement —— 别在这里就停，整页滚也是一种情况
      let st = null;
      try { st = getComputedStyle(n); } catch (e) { st = null; }
      if (st && /(auto|scroll|overlay)/.test(st.overflowY) && aim(n)) return true;
      n = n.parentElement;
    }
  }
  return false;
}

function notesGotoNote(it) {
  const slide = Number(it && it.slide) || 0;
  let ok = false;
  // ① 图片式幻灯片：点缩略图（等价于翻到第 N 页）
  if (slide > 0) {
    const th = document.querySelector('.rp-thumb[data-i="' + (slide - 1) + '"]');
    if (th) { th.click(); ok = true; }
  }
  // ② iframe 版幻灯片：页元素滚到视野开头
  if (!ok && slide > 0) {
    const doc = notesPreviewDoc();
    const el = doc ? notesSlideEl(doc, slide) : null;
    if (el && el.scrollIntoView) {
      try { el.scrollIntoView({ block: "start" }); ok = true; } catch (e) { /* 滚不动就算了 */ }
    }
  }
  // ③ 单页文档 / 画布：按 y 比例滚（通用找滚动容器，见 notesScrollTo）
  if (!ok) ok = notesScrollTo(it);
  notesFlashPin(it && it.id);
  return ok;
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
    const base = notesRootBase(inner, root, rr);
    x = (clientX - (frBox.left + base.left) + root.scrollLeft) / Math.max(root.scrollWidth, rr.width, 1);
    y = (clientY - (frBox.top + base.top) + root.scrollTop) / Math.max(root.scrollHeight, rr.height, 1);
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

function notesRootBase(doc, root, rr) {
  // 整页滚动(documentElement / scrollingElement / body)的 rect 已被滚动推移(top = -scrollTop)·
  // 再叠一次 root.scrollTop 就把滚动量算了两遍 → 批注钉整体偏一个滚动量(滚越远偏越多)。
  // 这里统一取「静态基准」：整页滚动归零·内部滚动容器(.main)维持原值·行为不变。
  const page = (root === doc.documentElement || root === doc.scrollingElement || root === doc.body);
  return page ? { left: 0, top: 0 } : { left: rr.left, top: rr.top };
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
  // 圈了字的卡要多排一颗「复制」→ 实测四颗需 268px、240px 卡的内容区只有 213px
  //   → 只给这类卡加宽到 300px（点空白钉的两颗卡保持 240px 不动）
  if (it.sel) card.classList.add("has-sel");
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
  // BRO 2026-09-28: 圈字有时候不是想批注，是想把那句话拿到对话里用
  //   （原话「可以不要复制，要一个按钮，就是文本发到对话框」）
  //   只在「圈了字」的卡上出现 —— 点空白钉的卡没有原文可送，就不该有这颗。
  // BRO 2026-09-28 补：「还想要个复制按钮」—— 送去剪贴板（不关卡片，他可能还要接着写批注）
  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "stage-note-copy";
  copy.textContent = "复制";
  copy.title = "把圈选的原文复制到剪贴板";
  const send = document.createElement("button");
  send.type = "button";
  send.className = "stage-note-send";
  send.textContent = "发到对话框";
  send.title = "把圈选的原文送进对话输入框（不保存这条批注）";
  const ok = document.createElement("button");
  ok.type = "button";
  ok.className = "stage-note-ok";
  ok.textContent = "记下";
  row.appendChild(del);
  if (it.sel) row.appendChild(copy);
  if (it.sel) row.appendChild(send);
  row.appendChild(ok);
  card.appendChild(h);
  card.appendChild(ta);
  card.appendChild(row);
  copy.onclick = function (ev) {
    ev.stopPropagation();
    const quote = String(it.sel || "").trim();
    if (!quote) return;
    const done = function () {
      // 只把按钮文字闪一下 · 不弹提示不新增元素
      copy.textContent = "已复制";
      setTimeout(function () { copy.textContent = "复制"; }, 1200);
    };
    const fail = function () {
      // 两种方式都不行 → 明确说一句，别让他点了没反应还不知道成没成
      // 只 3 个字：.stage-note-copy 宽度固定 64px，4 字会溢出
      copy.textContent = "没复制";
      setTimeout(function () { copy.textContent = "复制"; }, 1200);
    };
    const legacy = function () {
      // 老浏览器/无 clipboard API 的兑底（execCommand 已废弃但还能用）
      const ta = document.createElement("textarea");
      ta.value = quote;
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      ta.setAttribute("readonly", "");
      document.body.appendChild(ta);
      ta.select();
      let okCopy = false;
      try { okCopy = document.execCommand("copy"); } catch (e) { okCopy = false; }
      ta.remove();
      if (okCopy) done(); else fail();   // 看返回值 · 不给假反馈
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(quote).then(done, legacy);
    } else {
      legacy();
    }
  };
  send.onclick = function (ev) {
    ev.stopPropagation();
    // 送进输入框（复用 askMergeDebtNLP 那套: set + focus + dispatch input，
    // 草稿保存 / 自动高度都会跟上）· 输入框已有内容就追加，不盖掉他打了一半的
    const inp = document.getElementById("input");
    const quote = String(it.sel || "").trim();
    if (inp && quote) {
      const cur = inp.value.trim();
      inp.value = cur ? (cur + "\n\n" + quote) : quote;
      inp.focus();
      inp.dispatchEvent(new Event("input", { bubbles: true }));
    }
    // 这条批注不存 —— 意图是「拿去用」，不是「记下来」（等同「关闭批注」）
    notesSave(items.filter(function (n) { return n.id !== id; }));
    notesCloseCard();
    notesRenderPins();
  };
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
    // BRO 2026-09-20:「跳对话只归『进入话题』」—— 原来这里会因「这份文档不属于当前会话」
    //   自动切到它归属的那场对话(顺手把中栏关了)。现在批注就发在当前这场。
    //   (老逻辑: if (!mine) { const home = data && data.home_sid; if (home) await switchToSession(home); })
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
