"use strict";

const $ = (id) => document.getElementById(id);
const chat = $("chat");

async function api(path, body) {
  const opt = { method: body ? "POST" : "GET" };
  if (body) {
    opt.headers = { "Content-Type": "application/json" };
    opt.body = JSON.stringify(body);
  }
  const r = await fetch(path, opt);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || ("HTTP " + r.status));
  return data;
}

// ── 轻量 markdown 渲染（够用即可：粗体/斜体/行内代码/列表/标题/链接）──
function escHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function inlineMd(s) {
  s = s.replace(/`([^`]+)`/g, (m, c) => `<code>${c}</code>`);
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
  s = s.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  return s;
}
function mdToHtml(text) {
  const lines = String(text).replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let i = 0, para = [];
  const flush = () => {
    if (para.length) {
      out.push("<p>" + para.map((l) => inlineMd(escHtml(l))).join("<br>") + "</p>");
      para = [];
    }
  };
  while (i < lines.length) {
    const line = lines[i], t = line.trim();
    const hm = t.match(/^(#{1,4})\s+(.*)$/);
    if (hm) { flush(); out.push('<div class="md-h">' + inlineMd(escHtml(hm[2])) + "</div>"); i++; continue; }
    if (/^[-*]\s+/.test(t)) {
      flush();
      const items = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) { items.push("<li>" + inlineMd(escHtml(lines[i].replace(/^\s*[-*]\s+/, ""))) + "</li>"); i++; }
      out.push("<ul>" + items.join("") + "</ul>");
      continue;
    }
    if (/^\d+\.\s+/.test(t)) {
      flush();
      const items = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) { items.push("<li>" + inlineMd(escHtml(lines[i].replace(/^\s*\d+\.\s+/, ""))) + "</li>"); i++; }
      out.push("<ol>" + items.join("") + "</ol>");
      continue;
    }
    if (t === "") { flush(); i++; continue; }
    para.push(line);
    i++;
  }
  flush();
  return out.join("");
}

// ── 渲染 ──
function addMsg(role, content) {
  const m = document.createElement("div");
  m.className = "msg " + role;
  if (role === "ai") {
    const av = document.createElement("img");
    av.className = "avatar";
    av.src = "/static/favicon.ico";
    av.alt = "";
    m.appendChild(av);
  }
  const col = document.createElement("div");
  col.className = "col";
  const b = document.createElement("div");
  b.className = "bubble";
  if (role === "ai") { b.classList.add("md"); b.innerHTML = mdToHtml(content); }
  else b.textContent = content;
  col.appendChild(b);
  m.appendChild(col);
  chat.appendChild(m);
  scroll();
  return m;
}

function addChips(msgEl, events) {
  if (!events || !events.length) return;
  const wrap = document.createElement("div");
  wrap.className = "tool-chips";
  for (const e of events) {
    const c = document.createElement("span");
    c.className = "chip" + (e.ok ? " ok" : "");
    c.textContent = (e.ok ? "✓ " : "✗ ") + e.out;
    wrap.appendChild(c);
  }
  (msgEl.querySelector(".col") || msgEl).appendChild(wrap);
  scroll();
}

function doneBanner() {
  if (chat.querySelector(".done-banner")) return;
  const d = document.createElement("div");
  d.className = "done-banner";
  const t = document.createElement("div");
  t.className = "db-text";
  t.textContent = "── 相遇完成 · 你和它的故事开始了 ──";
  d.appendChild(t);
  const btn = document.createElement("button");
  btn.className = "db-enter";
  btn.textContent = "进入正式界面 →";
  btn.addEventListener("click", playOpeningTransition);
  d.appendChild(btn);
  chat.appendChild(d);
  scroll();
}

// 录 key 后 · 开场片头：告诉用户接下来是一段「它想认识你」的对话·不是最终工作台
function showIntro(then) {
  const ov = document.createElement("div");
  ov.id = "intro";
  ov.innerHTML =
    '<div class="op-glow"></div>' +
    '<div class="intro-title">接下来，让它先认识认识你</div>' +
    '<div class="intro-sub">下面是一段对话——<b>它想了解你</b>，好成为更懂你的搭档。<br>这还不是你的工作台；聊完，它会亲自带你进去。</div>' +
    '<button class="intro-go">好，开始相遇 →</button>';
  document.body.appendChild(ov);
  requestAnimationFrame(() => ov.classList.add("show"));
  let done = false;
  const go = () => {
    if (done) return;
    done = true;
    ov.classList.remove("show");
    setTimeout(() => ov.remove(), 500);
    then();
  };
  ov.querySelector(".intro-go").addEventListener("click", go);
}

// 进操作台 · 电影开幕式转场：黑屏渐入 → 心跳脉冲 → 名字浮现 → 一行字 → 进门
let _going = false;
async function playOpeningTransition() {
  if (_going) return;
  _going = true;
  let name = "Daemonkey";
  try { const st = await api("/api/onboarding/status"); if (st && st.name) name = st.name; } catch (_) {}
  const ov = document.createElement("div");
  ov.id = "opening";
  ov.innerHTML =
    '<div class="op-glow"></div>' +
    '<div class="op-name">「' + escHtml(name) + '」</div>' +
    '<div class="op-line">我们的故事，从这里开始</div>';
  document.body.appendChild(ov);
  requestAnimationFrame(() => ov.classList.add("show"));
  setTimeout(() => { location.href = "/ui"; }, 3400);
}

let typingEl = null;
function showTyping() {
  typingEl = document.createElement("div");
  typingEl.className = "msg ai typing";
  typingEl.innerHTML = '<img class="avatar" src="/static/favicon.ico" alt=""><div class="col"><div class="bubble"><span class="dot">●</span><span class="dot">●</span><span class="dot">●</span></div></div>';
  chat.appendChild(typingEl);
  scroll();
}
function hideTyping() {
  if (typingEl) { typingEl.remove(); typingEl = null; }
}

function scroll() { chat.scrollTop = chat.scrollHeight; }

// ── key 配置 ──
const PRESET_MODEL = {
  "https://api.deepseek.com": "deepseek-v4-pro",
  "https://open.bigmodel.cn/api/paas/v4": "glm-4.6",
};
$("presetSel").addEventListener("change", (e) => {
  const v = e.target.value;
  if (v === "__custom__") { $("baseUrlInp").value = ""; $("baseUrlInp").focus(); }
  else {
    $("baseUrlInp").value = v;
    if (PRESET_MODEL[v]) $("modelInp").value = PRESET_MODEL[v];
  }
});

$("eyeBtn").addEventListener("click", () => {
  const inp = $("apiKeyInp");
  const icon = $("eyeBtn").querySelector("i");
  if (inp.type === "password") { inp.type = "text"; icon.className = "ri-eye-off-line"; }
  else { inp.type = "password"; icon.className = "ri-eye-line"; }
});

$("keyHelpBtn").addEventListener("click", () => {
  $("keyHelp").classList.toggle("hidden");
});

$("saveKeyBtn").addEventListener("click", async () => {
  const api_key = $("apiKeyInp").value.trim();
  const base_url = $("baseUrlInp").value.trim();
  const model = $("modelInp").value.trim();
  const msg = $("keyMsg");
  if (!api_key || !base_url) { msg.className = "key-msg err"; msg.textContent = "key 和接口地址都要填。"; return; }
  $("saveKeyBtn").disabled = true;
  msg.className = "key-msg"; msg.textContent = "保存中…";
  try {
    await api("/api/onboarding/save-key", { api_key, base_url, model });
    msg.className = "key-msg ok"; msg.textContent = "已保存 · 正在唤醒它…";
    $("keyCard").classList.add("hidden");
    showIntro(() => startChat());
  } catch (err) {
    msg.className = "key-msg err"; msg.textContent = "保存失败：" + err.message;
    $("saveKeyBtn").disabled = false;
  }
});

// ── 对话 ──
async function startChat() {
  $("composer").classList.remove("hidden");
  showTyping();
  try {
    const data = await api("/api/onboarding/open", {});
    hideTyping();
    for (const m of data.messages) addMsg(m.role, m.content);
    if (data.tool_events && data.tool_events.length && chat.lastElementChild)
      addChips(chat.lastElementChild, data.tool_events);
    if (data.onboarded) doneBanner();
    $("input").focus();
  } catch (err) {
    hideTyping();
    addMsg("ai", "（唤醒失败：" + err.message + "）");
  }
}

async function send() {
  const inp = $("input");
  const text = inp.value.trim();
  if (!text) return;
  inp.value = ""; autoGrow();
  addMsg("user", text);
  showTyping();
  $("sendBtn").disabled = true;
  try {
    const data = await api("/api/onboarding/send", { message: text });
    hideTyping();
    const el = addMsg("ai", data.reply || "");
    addChips(el, data.tool_events);
    if (data.onboarded) doneBanner();
  } catch (err) {
    hideTyping();
    addMsg("ai", "（出错了：" + err.message + "）");
  } finally {
    $("sendBtn").disabled = false;
    inp.focus();
  }
}

$("sendBtn").addEventListener("click", send);

$("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});

function autoGrow() {
  const inp = $("input");
  inp.style.height = "auto";
  inp.style.height = Math.min(inp.scrollHeight, 140) + "px";
}
$("input").addEventListener("input", autoGrow);

$("resetBtn").addEventListener("click", async () => {
  if (!confirm("重新相遇？会清空这段对话和它对你的记忆，从头再来一次。")) return;
  try { await api("/api/onboarding/reset", {}); } catch (_) {}
  location.reload();
});

// ── 启动 ──
(async function init() {
  try {
    const st = await api("/api/onboarding/status");
    if (!st.has_key) {
      $("keyCard").classList.remove("hidden");
    } else {
      await startChat();
    }
  } catch (err) {
    $("keyCard").classList.remove("hidden");
    $("keyMsg").className = "key-msg err";
    $("keyMsg").textContent = "后端连接异常：" + err.message;
  }
})();
